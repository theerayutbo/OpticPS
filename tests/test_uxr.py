"""Tests for the scope importers and the non-periodic capture DSP.

All fixtures are SYNTHETIC: files and waveforms written by this module, not instrument data.
"""

import json
import struct
from pathlib import Path

import h5py
import numpy as np
import pytest
from scipy.interpolate import CubicSpline
from scipy.special import erfc

from opticps.cli.main import main
from opticps.measurement.capture import CaptureValidationError, load_reference
from opticps.measurement.uxr_import import (
    ScopeWaveform,
    UxrImportError,
    read_bin,
    read_csv,
    read_hdf5,
    read_scope_file,
)
from opticps.modulation.pam import pam_levels
from opticps.optical_channel.link import LinkConfig, transmit
from opticps.optimization.adaptive import DataLeakageError
from opticps.receiver.capture_dsp import analyze_scope_capture, describe_error_rate
from opticps.statistics.intervals import clopper_pearson
from opticps.transmitter.frame import PREAMBLE_LENGTH, TRAINING_LENGTH, build_frame

UNIFORM_PRIORS = np.full(4, 0.25)


# ----------------------------------------------------------------------------- file fixtures
def write_h5(path, samples, dtype="int16", xinc=1e-11, xorg=-1e-9, yinc=1e-4, yorg=0.01, **kw):
    """Write a synthetic Infiniium-style HDF5 file (layout from the vendor schema page)."""
    attrs = {
        "NumPoints": len(samples),
        "XInc": xinc,
        "XOrg": xorg,
        "XUnits": "Second",
        "YInc": yinc,
        "YOrg": yorg,
        "YUnits": "Volt",
        "WaveformType": "NORMAL",
        "SavedInterpFactor": 1,
        "NumSegments": 1,
        "Start": 0,
    }
    attrs.update(kw.pop("attrs", {}))
    drop = kw.pop("drop", ())
    channel = kw.pop("channel", 1)
    data = np.asarray(samples).astype(dtype)
    with h5py.File(path, "w") as f:
        f.create_dataset("FileType/KeysightH5FileType", data="Keysight Infiniium (synthetic)")
        frame_type = np.dtype([("Model", "S32"), ("Serial", "S32"), ("Date", "S32")])
        f.create_dataset(
            "Frame/TheFrame",
            data=np.array([(b"UXR-SYNTHETIC", b"SN-0", b"2026-01-01")], frame_type),
        )
        waveforms = f.create_group("Waveforms")
        waveforms.attrs["NumWaveforms"] = 1
        group = waveforms.create_group(f"Channel {channel}")
        for name, value in attrs.items():
            if name not in drop:
                group.attrs[name] = value
        group.create_dataset(f"Channel {channel}Data", data=data)


def make_bin(samples, xinc=1e-11, xorg=0.0, y_units=1, x_units=2, buffer_type=1, size_delta=0):
    """Write a synthetic BIN image with the assumed 4-byte layout."""
    n = len(samples)
    wave = struct.pack(
        "<iiiiifdddii16s16s24s16sdI",
        140, 1, 1, n, 1, 0.0, 0.0, xinc, xorg, x_units, y_units,
        b"01 JAN 2026", b"12:00:00", b"SYNTH:SN0", b"Channel 1", 0.0, 0,
    )  # fmt: skip
    data = struct.pack("<ihhi", 12, buffer_type, 4, 4 * n) + np.asarray(samples, "<f4").tobytes()
    total = 12 + len(wave) + len(data)
    return struct.pack("<2s2sii", b"AG", b"01", total + size_delta, 1) + wave + data


RAMP = np.linspace(-0.3, 0.3, 64)


# ----------------------------------------------------------------------------- HDF5
@pytest.mark.parametrize("dtype", ["int16", "int8", "uint8"])
def test_hdf5_integer_scaling_round_trip(tmp_path, dtype):
    raw = np.arange(-20, 44) if dtype != "uint8" else np.arange(0, 64)
    write_h5(tmp_path / "a.h5", raw, dtype=dtype, yinc=2e-3, yorg=0.5)
    wave = read_hdf5(tmp_path / "a.h5", channel=1)
    assert np.allclose(wave.samples_v, 0.5 + raw.astype(float) * 2e-3)
    assert wave.x_increment_s == 1e-11 and wave.x_origin_s == -1e-9
    assert wave.measured_sample_rate == pytest.approx(1e11)
    assert (wave.model, wave.serial, wave.saved_date) == ("UXR-SYNTHETIC", "SN-0", "2026-01-01")
    assert wave.source_format == "hdf5" and wave.channel == 1
    assert "unverified" in wave.attributes["scaling_assumption"]


def test_hdf5_float_dataset_is_volts_and_flagged(tmp_path):
    write_h5(tmp_path / "f.h5", RAMP, dtype="float32", yinc=1.0, yorg=100.0)
    wave = read_hdf5(tmp_path / "f.h5")
    assert np.allclose(wave.samples_v, RAMP.astype(np.float32))
    assert "float dataset treated as volts" in wave.attributes["scaling_assumption"]


def test_hdf5_bytes_and_one_element_array_attributes(tmp_path):
    attrs = {
        "YUnits": np.bytes_("Volt"),
        "XUnits": np.array([b"Second"]),
        "XInc": np.array([5e-12]),
        "WaveformType": np.bytes_("AVERAGE"),
        "NumSegments": np.array([1]),
        "Unrelated": np.arange(3),
    }
    write_h5(tmp_path / "b.h5", np.arange(64), attrs=attrs)
    wave = read_hdf5(tmp_path / "b.h5")
    assert wave.x_increment_s == 5e-12 and wave.attributes["WaveformType"] == "AVERAGE"
    assert wave.attributes["Unrelated"] == [0, 1, 2]


@pytest.mark.parametrize(
    "attrs,drop,channel,word",
    [
        ({"YUnits": "Amp"}, (), 1, "YUnits"),
        ({"XUnits": "Hertz"}, (), 1, "XUnits"),
        ({"XInc": 0.0}, (), 1, "positive"),
        ({"XInc": -1e-11}, (), 1, "positive"),
        ({"NumPoints": 65}, (), 1, "NumPoints"),
        ({"WaveformType": "PEAK_DETECT"}, (), 1, "WaveformType"),
        ({"NumSegments": 4}, (), 1, "segment"),
        ({}, ("XInc",), 1, "XInc"),
        ({}, (), 2, "Missing Channel 2"),
    ],
)
def test_hdf5_reject_cases(tmp_path, attrs, drop, channel, word):
    write_h5(tmp_path / "r.h5", np.arange(64), attrs=attrs, drop=drop)
    with pytest.raises(UxrImportError, match=word):
        read_hdf5(tmp_path / "r.h5", channel=channel)


def test_hdf5_waveform_type_can_be_allowed_and_segment_selected(tmp_path):
    write_h5(tmp_path / "w.h5", np.arange(64), attrs={"WaveformType": "PEAK_DETECT"})
    wave = read_hdf5(tmp_path / "w.h5", allow_waveform_types=["peak_detect"])
    assert wave.samples_v.size == 64
    write_h5(tmp_path / "s.h5", np.arange(128), attrs={"NumSegments": 2, "NumPoints": 64})
    chosen = read_hdf5(tmp_path / "s.h5", segment=1)
    assert np.allclose(chosen.samples_v, 0.01 + np.arange(64, 128) * 1e-4)
    with pytest.raises(UxrImportError, match="outside"):
        read_hdf5(tmp_path / "s.h5", segment=2)


def test_non_hdf5_and_non_finite_rejected(tmp_path):
    (tmp_path / "x.h5").write_bytes(b"not hdf5")
    with pytest.raises(UxrImportError, match="HDF5"):
        read_hdf5(tmp_path / "x.h5")
    write_h5(tmp_path / "n.h5", np.full(64, np.nan), dtype="float64")
    with pytest.raises(UxrImportError, match="non-finite"):
        read_hdf5(tmp_path / "n.h5")


# ----------------------------------------------------------------------------- CSV
def test_csv_two_column_derives_increment(tmp_path):
    t = 3e-9 + np.arange(50) * 2.5e-11
    (tmp_path / "t.csv").write_text(
        "Time (s),Voltage (V)\n"
        + "".join(f"{float(a)!r},{float(b)!r}\n" for a, b in zip(t, np.sin(t * 1e9), strict=True))
    )
    wave = read_csv(tmp_path / "t.csv")
    assert wave.x_increment_s == pytest.approx(2.5e-11, rel=1e-9)
    assert wave.x_origin_s == pytest.approx(3e-9)
    assert wave.samples_v.size == 50


def test_csv_one_column_needs_header_or_argument(tmp_path):
    body = "".join(f"{float(v)!r}\n" for v in RAMP)
    (tmp_path / "h.csv").write_text(f"XInc,2e-11\nYUnits,Volt\nVoltage\n{body}")
    wave = read_csv(tmp_path / "h.csv")
    assert wave.x_increment_s == 2e-11 and wave.attributes["x_increment_source"] == "header"
    (tmp_path / "n.csv").write_text(f"Voltage\n{body}")
    with pytest.raises(UxrImportError, match="not guessing"):
        read_csv(tmp_path / "n.csv")
    assert read_csv(tmp_path / "n.csv", x_increment_s=1e-11).x_increment_s == 1e-11
    with pytest.raises(UxrImportError, match="disagrees"):
        read_csv(tmp_path / "h.csv", x_increment_s=1e-11)


def test_csv_rejects_transmitter_file_wrong_units_and_irregular_time(tmp_path):
    body = "".join(f"{float(v)!r}\n" for v in RAMP)
    (tmp_path / "d.csv").write_text(f"DataOut1\n{body}")
    with pytest.raises(UxrImportError, match="transmitter waveform"):
        read_csv(tmp_path / "d.csv", x_increment_s=1e-11)
    (tmp_path / "u.csv").write_text(f"XInc,1e-11\nYUnits,mV\n{body}")
    with pytest.raises(UxrImportError, match="Y units"):
        read_csv(tmp_path / "u.csv")
    t = np.arange(50) * 1e-11
    t[25:] += 3e-12
    (tmp_path / "t.csv").write_text("t,v\n" + "".join(f"{float(a)!r},0.1\n" for a in t))
    with pytest.raises(UxrImportError, match="uniformly"):
        read_csv(tmp_path / "t.csv")
    (tmp_path / "w.csv").write_text("a,b,c\n1,2,3\n4,5,6\n")
    with pytest.raises(UxrImportError, match="one or two columns"):
        read_csv(tmp_path / "w.csv")


# ----------------------------------------------------------------------------- BIN
def test_bin_round_trip_with_flag(tmp_path):
    (tmp_path / "a.bin").write_bytes(make_bin(RAMP, xinc=4e-12, xorg=1e-9))
    wave = read_bin(tmp_path / "a.bin", accept_unverified_bin=True)
    assert np.allclose(wave.samples_v, RAMP.astype(np.float32))
    assert wave.x_increment_s == 4e-12 and wave.x_origin_s == 1e-9
    assert "unverified" in wave.attributes["widths_assumed"]
    assert read_scope_file(tmp_path / "a.bin", accept_unverified_bin=True).source_format == "bin"


def test_bin_refused_without_flag_and_bad_files_rejected(tmp_path):
    (tmp_path / "a.bin").write_bytes(make_bin(RAMP))
    with pytest.raises(UxrImportError, match="unverified"):
        read_bin(tmp_path / "a.bin")
    for name, blob, word in [
        ("size", make_bin(RAMP, size_delta=4), "File Size"),
        ("type", make_bin(RAMP, buffer_type=2), "buffer type"),
        ("yunit", make_bin(RAMP, y_units=3), "units"),
        ("xinc", make_bin(RAMP, xinc=0.0), "positive"),
        ("short", make_bin(RAMP)[:-8], "File Size"),
    ]:
        (tmp_path / f"{name}.bin").write_bytes(blob)
        with pytest.raises(UxrImportError, match=word):
            read_bin(tmp_path / f"{name}.bin", accept_unverified_bin=True)


def test_unknown_suffix_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    with pytest.raises(UxrImportError, match="suffix"):
        read_scope_file(tmp_path / "a.txt")


# ----------------------------------------------------------------------------- capture DSP
SYMBOL_RATE = 8e9
HEAD = PREAMBLE_LENGTH + TRAINING_LENGTH
ROOT = Path("output/keysight_m8199b")
PROFILE = "A_initial_8GBd"


def uniform_frame(total=5120, seed=3):
    return build_frame("synthetic", None, total, seed, direct_uniform=True)


def clock_resample(continuous, ppm, start, length):
    """Sample a waveform on a scope clock whose symbol clock is ppm faster than nominal."""
    factor = 1 + ppm * 1e-6
    count = int(np.floor((continuous.size - 1) / factor)) + 1
    scope = CubicSpline(np.arange(continuous.size), continuous)(np.arange(count) * factor)
    return scope[start : start + length]


def band_limited_noise(size, rate, bandwidth, sigma, rng):
    """Gaussian noise limited to bandwidth Hz, scaled to std sigma (in level units)."""
    spectrum = np.fft.rfft(rng.normal(size=size))
    spectrum[np.fft.rfftfreq(size, 1 / rate) > bandwidth] = 0
    noise = np.fft.irfft(spectrum, n=size)
    return noise / noise.std() * sigma


def scope_capture(
    frame,
    ppm=0.0,
    frames=4.3,
    start_frac=0.37,
    sps=32,
    link=True,
    sigma=None,
    gain=1.0,
    dc=0.0,
    invert=False,
    seed=1,
):
    """Looped frame -> (link or ideal NRZ + noise) -> scope clock -> random window. SYNTHETIC."""
    rng = np.random.default_rng(seed)
    wave = np.repeat(pam_levels(4)[frame.indices], sps).astype(float)
    tiled = np.tile(wave, int(np.ceil(frames)) + 2)
    fs_awg = sps * SYMBOL_RATE
    if link:
        config = LinkConfig(predistort=True, receiver_bandwidth_hz=10e9, extra_attenuation_db=3)
        continuous = transmit(tiled / 3, fs_awg, config, rng).current_a * 50.0
        continuous = continuous - continuous.mean()
    else:
        continuous = tiled
        if sigma is not None:
            continuous = continuous + band_limited_noise(
                tiled.size, fs_awg, SYMBOL_RATE / 2, sigma, rng
            )
    scope = clock_resample(continuous, ppm, int(start_frac * wave.size), int(frames * wave.size))
    scope = scope * gain * (-1 if invert else 1) + dc
    return ScopeWaveform(scope, 1 / fs_awg, 0.0, "V", 1, None, None, None, "synthetic", {})


@pytest.mark.parametrize(
    "ppm,invert,seed", [(100.0, False, 1), (100.0, True, 2), (-60.0, False, 3)]
)
def test_partial_frames_clock_offset_and_polarity(ppm, invert, seed):
    frame = uniform_frame()
    start = np.random.default_rng(seed).uniform(0.05, 0.95)
    wave = scope_capture(frame, ppm, start_frac=start, invert=invert, seed=seed)
    assert wave.measured_sample_rate == pytest.approx(256e9)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    assert result.frames_complete >= 3 and result.frames_found > result.frames_complete - 1
    assert result.polarity_inverted == invert
    assert result.map.symbol_errors == 0 and result.minimum_distance.symbol_errors == 0
    assert result.clock_confidence == "high"
    assert abs(result.clock_offset_ppm - ppm) < 1.0
    assert result.estimated_symbol_rate == pytest.approx(SYMBOL_RATE * (1 + ppm * 1e-6), rel=1e-8)
    assert result.rate_estimate_reliable and result.eye.shape[1] == 17
    assert result.symbol_histogram.sum() == result.map.symbols


def test_gain_and_dc_offset_recovered():
    frame = uniform_frame()
    wave = scope_capture(frame, 70.0, link=False, gain=0.37, dc=0.21, invert=True)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    assert result.gain_v_per_level == pytest.approx(-0.37, rel=0.02)
    assert result.offset_v == pytest.approx(0.21, abs=0.005)
    assert result.map.symbol_errors == 0


def test_clock_compensation_matters():
    frame = uniform_frame(32768)
    wave = scope_capture(frame, 50.0, frames=3.4, start_frac=0.2, sps=16)
    on = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    off = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS, compensate_clock=False)
    assert on.map.symbol_errors == 0 and abs(on.clock_offset_ppm - 50) < 1
    assert off.map.symbol_errors > 1000 * (on.map.symbol_errors + 1)
    assert off.clock_offset_ppm == 0.0


def test_ser_inside_clopper_pearson_interval_of_analytic_value():
    frame = uniform_frame()
    sigma = 0.5
    wave = scope_capture(frame, 100.0, frames=8.3, sps=8, link=False, sigma=sigma, seed=4)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS, taps=1)
    analytic = 0.75 * erfc(1 / (np.sqrt(2) * sigma))
    for pooled in (result.minimum_distance, result.map):
        low, high = clopper_pearson(pooled.symbol_errors, pooled.symbols, 0.999)
        assert pooled.symbols >= 24000 and low <= analytic <= high
    boot = result.minimum_distance.ser_bootstrap_ci
    assert boot is not None and boot[0] < result.minimum_distance.ser < boot[1]
    assert abs(result.clock_offset_ppm - 100) < 1.0


def test_single_frame_clock_is_low_confidence_but_close():
    frame = uniform_frame()
    wave = scope_capture(frame, 100.0, frames=1.062, start_frac=0.95)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    assert result.frames_found == 1 and result.frames_complete == 1
    assert result.clock_confidence == "low" and result.clock_stderr_ppm is None
    assert any("One preamble" in w for w in result.warnings)
    assert abs(result.clock_offset_ppm - 100) < 5.0 and result.map.symbol_errors == 0
    assert result.map.ser_bootstrap_ci is None


def test_no_complete_frame_or_no_preamble_raises():
    frame = uniform_frame()
    short = scope_capture(frame, 100.0, frames=1.6, start_frac=0.05)
    with pytest.raises(ValueError, match="No complete frame"):
        analyze_scope_capture(short, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    noise = np.random.default_rng(0).normal(size=300000)
    wave = ScopeWaveform(noise, 1 / 256e9, 0.0, "V", 1, None, None, None, "synthetic", {})
    with pytest.raises(ValueError, match="No preamble"):
        analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    with pytest.raises(ValueError, match="samples per symbol"):
        analyze_scope_capture(wave, 200e9, frame, UNIFORM_PRIORS)


def test_zero_errors_are_reported_as_an_upper_bound_not_zero_ber():
    frame = uniform_frame()
    result = analyze_scope_capture(scope_capture(frame, 30.0), SYMBOL_RATE, frame, UNIFORM_PRIORS)
    pooled = result.map
    bound = 1 - 0.05 ** (1 / pooled.symbols)
    assert pooled.symbol_errors == 0 and pooled.ser is None and pooled.ber is None
    assert pooled.ser_report == f"0 errors in {pooled.symbols} symbols, 95% upper bound {bound:.3g}"
    assert pooled.ber_report.startswith(f"0 errors in {pooled.bits} bits, 95% upper bound")
    assert pooled.ser_upper_95 == pytest.approx(bound, rel=1e-6)
    assert "BER 0" not in pooled.ber_report and "rate 0" not in pooled.ser_report
    assert describe_error_rate(3, 1000, "symbols").startswith(
        "3 errors in 1000 symbols, rate 0.003"
    )


def test_rate_estimate_flagged_unreliable_with_rare_levels():
    probabilities = [0.04, 0.46, 0.46, 0.04]
    frame = build_frame("synthetic-rare", probabilities, 2048, 5)
    wave = scope_capture(frame, 20.0, frames=2.4, start_frac=0.5, sps=16)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, np.array(probabilities))
    assert min(result.level_test_symbols) < 100
    assert not result.rate_estimate_reliable
    assert any("MI/GMI unreliable" in w for w in result.warnings)


def test_fits_use_preamble_and_training_only():
    frame = uniform_frame()
    clean = scope_capture(frame, 0.0, sps=8, link=False, sigma=0.3, start_frac=0.25, seed=6)
    corrupted = clean.samples_v.copy()
    length = frame.indices.size * 8
    first = length - int(0.25 * length)
    rng = np.random.default_rng(8)
    for begin in range(first, corrupted.size, length):
        lo = begin + HEAD * 8
        hi = min(begin + length, corrupted.size)
        if lo < hi:
            corrupted[lo:hi] += rng.normal(0, 1.5, hi - lo)
    bad = ScopeWaveform(
        corrupted, clean.x_increment_s, 0.0, "V", 1, None, None, None, "synthetic", {}
    )
    a = analyze_scope_capture(clean, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    b = analyze_scope_capture(bad, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    assert b.map.symbol_errors > a.map.symbol_errors + 100
    assert len(a.frames) == len(b.frames) >= 3
    for good, hurt in zip(a.frames, b.frames, strict=True):
        assert np.allclose(good.ffe_taps, hurt.ffe_taps, atol=1e-3)
        assert np.allclose(good.likelihood.means, hurt.likelihood.means, atol=1e-3)
        assert np.allclose(good.likelihood.sigmas, hurt.likelihood.sigmas, atol=1e-3)
        assert good.gain_v_per_level == pytest.approx(hurt.gain_v_per_level, rel=1e-3)
        assert good.offset_v == pytest.approx(hurt.offset_v, abs=1e-3)


# ----------------------------------------------------------------------------- ingest pipeline
def sidecar(frame_row, split="test", capture_id="uxr-synthetic-1", rate=64e9, probabilities=None):
    return {
        "schema_version": "1.0",
        "capture_id": capture_id,
        "related_transmit_experiment_id": frame_row["experiment_id"],
        "run_id": "r1",
        "split": split,
        "data_source": "simulated",
        "capture_timestamp": "2026-11-01T10:00:00+00:00",
        "receiver_instrument_model": "SYNTHETIC (no real instrument)",
        "transmitter_instrument_model": "Keysight M8199B",
        "capture_sample_rate_Sa_per_s": rate,
        "symbol_rate_Bd": SYMBOL_RATE,
        "receiver_bandwidth_Hz": 30e9,
        "fiber_length_km": 0,
        "attenuation_dB": 0,
        "optical_received_power_dBm": -10,
        "symbol_probabilities": probabilities,
        "units": {"time": "s", "voltage": "V"},
    }


@pytest.fixture(scope="module")
def uxr_files(tmp_path_factory):
    """A synthetic H5 export of the A-profile PS70 frame, plus its manifest row."""
    import csv

    folder = tmp_path_factory.mktemp("uxr")
    with (ROOT / PROFILE / "experiment_manifest.csv").open() as handle:
        row = next(r for r in csv.DictReader(handle) if r["waveform_filename"].endswith("PS70.csv"))
    frame = load_reference(ROOT / PROFILE / "references" / "PAM4_Fixed_PS70", "PAM4_Fixed_PS70")
    wave = scope_capture(frame, 40.0, frames=3.4, start_frac=0.3, sps=8, seed=9)
    volts = wave.samples_v
    step = float(np.abs(volts).max()) / 30000
    write_h5(
        folder / "cap.h5", np.round(volts / step), dtype="int16", xinc=1 / 64e9, yinc=step, yorg=0.0
    )
    probabilities = [
        float(row[f"realised_probability_{k}"]) for k in ("minus3", "minus1", "plus1", "plus3")
    ]
    return folder, row, probabilities


def write_sidecar(folder, row, probabilities, name="side.json", **kw):
    path = folder / name
    path.write_text(json.dumps(sidecar(row, probabilities=probabilities, **kw)))
    return path


def test_ingest_uxr_test_split_end_to_end(uxr_files, tmp_path, capsys):
    folder, row, probabilities = uxr_files
    side = write_sidecar(folder, row, probabilities, "test.json")
    args = [
        "ingest-uxr",
        "--input",
        str(folder / "cap.h5"),
        "--channel",
        "1",
        "--sidecar",
        str(side),
    ]
    args += ["--profile", PROFILE, "--output", str(ROOT), "--results", str(tmp_path / "res")]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "SER: 0 errors in" in out and "upper bound" in out and "clock offset" in out
    summary = json.loads((tmp_path / "res" / "uxr-synthetic-1_analysis.json").read_text())
    assert summary["split"] == "test" and summary["waveform"] == "PAM4_Fixed_PS70"
    assert abs(summary["clock_offset_ppm"] - 40) < 1.0
    assert summary["measured_sample_rate_Sa_per_s"] == pytest.approx(64e9)
    assert summary["map"]["symbol_errors"] == 0 and summary["map"]["ber"] is None
    assert "upper bound" in summary["map"]["ber_report"]
    assert (tmp_path / "res" / "uxr-synthetic-1_eye.npz").exists()
    assert (tmp_path / "res" / "uxr-synthetic-1_frames.csv").exists()


def test_ingest_uxr_training_split_is_not_scored(uxr_files, tmp_path):
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    side = write_sidecar(folder, row, probabilities, "train.json", split="training")
    summary = ingest_uxr(folder / "cap.h5", side, ROOT, PROFILE, tmp_path)
    assert summary["split"] == "training" and summary["error_metrics"] is None
    assert "map" not in summary and "never reported as test" in summary["note"]
    assert not list(tmp_path.glob("*_frames.csv"))


def test_ingest_uxr_rejects_rate_mismatch_missing_split_and_leakage(uxr_files, tmp_path):
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    wrong = write_sidecar(folder, row, probabilities, "rate.json", rate=80e9)
    with pytest.raises(CaptureValidationError, match="differs from the file"):
        ingest_uxr(folder / "cap.h5", wrong, ROOT, PROFILE, tmp_path)
    near = write_sidecar(folder, row, probabilities, "near.json", rate=64e9 * 1.005, capture_id="n")
    assert ingest_uxr(folder / "cap.h5", near, ROOT, PROFILE, tmp_path / "near")["split"] == "test"
    data = sidecar(row, probabilities=probabilities)
    del data["split"]
    nosplit = folder / "nosplit.json"
    nosplit.write_text(json.dumps(data))
    with pytest.raises(CaptureValidationError, match="no split"):
        ingest_uxr(folder / "cap.h5", nosplit, ROOT, PROFILE, tmp_path / "ns")
    chosen = ingest_uxr(
        folder / "cap.h5", nosplit, ROOT, PROFILE, tmp_path / "ns", split="training"
    )
    assert chosen["split"] == "training"
    first = write_sidecar(folder, row, probabilities, "a.json", split="training", capture_id="a")
    ingest_uxr(folder / "cap.h5", first, ROOT, PROFILE, tmp_path / "leak")
    again = write_sidecar(folder, row, probabilities, "b.json", split="test", capture_id="b")
    with pytest.raises(DataLeakageError):
        ingest_uxr(folder / "cap.h5", again, ROOT, PROFILE, tmp_path / "leak")
    renamed = write_sidecar(folder, row, probabilities, "c.json", split="test", capture_id="a")
    with pytest.raises(DataLeakageError):
        ingest_uxr(folder / "cap.h5", renamed, ROOT, PROFILE, tmp_path / "leak")
