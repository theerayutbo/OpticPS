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
        group.create_dataset(f"Channel {channel}Data", data=data, **kw.pop("dataset_kwargs", {}))


def make_bin(
    samples, xinc=1e-11, xorg=0.0, y_units=1, x_units=2, buffer_type=1, size_delta=0,
    cookie=b"AG", version=b"10", wave_type=1,
):  # fmt: skip
    """Write a synthetic BIN image with the assumed 4-byte layout."""
    n = len(samples)
    wave = struct.pack(
        "<iiiiifdddii16s16s24s16sdI",
        140, wave_type, 1, n, 1, 0.0, 0.0, xinc, xorg, x_units, y_units,
        b"01 JAN 2026", b"12:00:00", b"SYNTH:SN0", b"Channel 1", 0.0, 0,
    )  # fmt: skip
    data = struct.pack("<ihhi", 12, buffer_type, 4, 4 * n) + np.asarray(samples, "<f4").tobytes()
    total = 12 + len(wave) + len(data)
    return struct.pack("<2s2sii", cookie, version, total + size_delta, 1) + wave + data


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
    assert (
        "p598" in wave.attributes["scaling_rule"]
        and "raw * YInc" in wave.attributes["scaling_rule"]
    )


def test_hdf5_float_dataset_is_volts_and_flagged(tmp_path):
    write_h5(tmp_path / "f.h5", RAMP, dtype="float32", yinc=1.0, yorg=100.0)
    wave = read_hdf5(tmp_path / "f.h5")
    assert np.allclose(wave.samples_v, RAMP.astype(np.float32))
    assert "actual vertical values" in wave.attributes["scaling_rule"]


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
        ({"NumPoints": 1}, (), 1, "at least 2"),
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


def test_hdf5_zero_segments_is_one_with_a_note_and_interp_factor_warns(tmp_path):
    write_h5(tmp_path / "z.h5", np.arange(64), attrs={"NumSegments": 0})
    wave = read_hdf5(tmp_path / "z.h5")
    assert wave.samples_v.size == 64 and "p2090" in wave.attributes["num_segments_note"]
    assert "warnings" not in wave.attributes
    write_h5(tmp_path / "i.h5", np.arange(64), attrs={"SavedInterpFactor": 4})
    warned = read_hdf5(tmp_path / "i.h5")
    assert any(
        "SavedInterpFactor is 4" in w and "unverified" in w for w in warned.attributes["warnings"]
    )
    write_h5(tmp_path / "n.h5", np.arange(64), attrs={"NumSegments": -1})
    with pytest.raises(UxrImportError, match="NumSegments"):
        read_hdf5(tmp_path / "n.h5")


def test_hdf5_links_external_and_virtual_storage_are_refused(tmp_path):
    for kind in ("soft_data", "external_data", "soft_group", "soft_waveforms", "soft_frame"):
        path = tmp_path / f"{kind}.h5"
        write_h5(path, np.arange(64))
        with h5py.File(path, "a") as f:
            f.create_dataset("elsewhere", data=np.arange(64, dtype="int16"))
            if kind == "soft_data":
                del f["Waveforms/Channel 1/Channel 1Data"]
                f["Waveforms/Channel 1/Channel 1Data"] = h5py.SoftLink("/elsewhere")
            elif kind == "external_data":
                del f["Waveforms/Channel 1/Channel 1Data"]
                f["Waveforms/Channel 1/Channel 1Data"] = h5py.ExternalLink("other.h5", "/data")
            elif kind == "soft_group":
                f["Waveforms/Channel 2"] = h5py.SoftLink("/Waveforms/Channel 1")
            elif kind == "soft_waveforms":
                f["Alias"] = h5py.SoftLink("/Waveforms")
                del f["Waveforms"]
                f["Waveforms"] = h5py.SoftLink("/Alias")
            else:
                del f["Frame/TheFrame"]
                f["Frame/TheFrame"] = h5py.SoftLink("/elsewhere")
        channel = 2 if kind == "soft_group" else 1
        if kind == "soft_frame":
            with pytest.raises(UxrImportError, match="links are not followed"):
                read_hdf5(path, channel)
        else:
            with pytest.raises(UxrImportError, match="SoftLink|ExternalLink"):
                read_hdf5(path, channel)
    raw = tmp_path / "raw.bin"
    write_h5(tmp_path / "ext.h5", np.arange(64), dataset_kwargs={"external": [(str(raw), 0, 128)]})
    with pytest.raises(UxrImportError, match="virtual or external storage"):
        read_hdf5(tmp_path / "ext.h5")
    write_h5(tmp_path / "virtual.h5", np.arange(64))
    with h5py.File(tmp_path / "virtual.h5", "a") as f:
        group = f["Waveforms/Channel 1"]
        del group["Channel 1Data"]
        layout = h5py.VirtualLayout(shape=(64,), dtype="int16")
        layout[:] = h5py.VirtualSource(".", "elsewhere_missing", shape=(64,))
        group.create_virtual_dataset("Channel 1Data", layout, fillvalue=0)
    with pytest.raises(UxrImportError, match="virtual or external storage"):
        read_hdf5(tmp_path / "virtual.h5")


def test_hdf5_shape_is_checked_against_attributes_and_a_maximum_before_reading(tmp_path):
    write_h5(tmp_path / "s.h5", np.arange(128), attrs={"NumPoints": 64})
    with pytest.raises(UxrImportError, match="does not match NumPoints"):
        read_hdf5(tmp_path / "s.h5")
    write_h5(tmp_path / "m.h5", np.arange(64))
    with pytest.raises(UxrImportError, match="exceed the limit of 10"):
        read_hdf5(tmp_path / "m.h5", max_samples=10)
    write_h5(tmp_path / "lie.h5", np.arange(64), attrs={"NumPoints": 10**12})
    with pytest.raises(UxrImportError, match="exceed the limit"):
        read_hdf5(tmp_path / "lie.h5")
    write_h5(tmp_path / "cmp.h5", np.zeros(64), dtype=[("a", "f4"), ("b", "f4")])
    with pytest.raises(UxrImportError, match="Unsupported dataset type"):
        read_hdf5(tmp_path / "cmp.h5")


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
    (tmp_path / "u.csv").write_text(f"XInc,1e-11\nYUnits,Amp\n{body}")
    with pytest.raises(UxrImportError, match="Y unit 'Amp'"):
        read_csv(tmp_path / "u.csv")
    t = np.arange(50) * 1e-11
    t[25:] += 3e-12
    (tmp_path / "t.csv").write_text("t,v\n" + "".join(f"{float(a)!r},0.1\n" for a in t))
    with pytest.raises(UxrImportError, match="uniformly"):
        read_csv(tmp_path / "t.csv")
    (tmp_path / "w.csv").write_text("a,b,c\n1,2,3\n4,5,6\n")
    with pytest.raises(UxrImportError, match="one or two columns"):
        read_csv(tmp_path / "w.csv")


def test_csv_parses_units_in_column_titles_and_never_labels_millivolts_as_volts(tmp_path):
    t = np.arange(40) * 0.025  # nanoseconds
    values = np.linspace(-300, 300, 40)  # millivolts
    body = "".join(f"{a!r},{b!r}\n" for a, b in zip(t.tolist(), values.tolist(), strict=True))
    (tmp_path / "mv.csv").write_text(f"Time (ns),Voltage (mV)\n{body}")
    wave = read_csv(tmp_path / "mv.csv")
    assert np.allclose(wave.samples_v, values * 1e-3)
    assert wave.x_increment_s == pytest.approx(2.5e-11, rel=1e-9)
    (tmp_path / "bad.csv").write_text(f"Time (s),Voltage (furlong)\n{body}")
    with pytest.raises(UxrImportError, match="not recognised"):
        read_csv(tmp_path / "bad.csv")
    (tmp_path / "bt.csv").write_text(f"Time (fortnight),Voltage (V)\n{body}")
    with pytest.raises(UxrImportError, match="Time unit"):
        read_csv(tmp_path / "bt.csv")
    column = "".join(f"{v!r}\n" for v in values.tolist())
    (tmp_path / "one.csv").write_text(f"XInc,2e-11\nVoltage [mV]\n{column}")
    assert np.allclose(read_csv(tmp_path / "one.csv").samples_v, values * 1e-3)
    (tmp_path / "clash.csv").write_text(f"XInc,2e-11\nYUnits,V\nVoltage (mV)\n{column}")
    with pytest.raises(UxrImportError, match="disagree"):
        read_csv(tmp_path / "clash.csv")


def test_csv_documented_header_fields_are_parsed_in_both_plausible_layouts(tmp_path):
    column = "".join(f"{v!r}\n" for v in RAMP.tolist())
    fields = [
        ("Revision", "0"), ("Type", "raw"), ("Start", "0"), ("Points", "64"), ("Count", "1"),
        ("XDispRange", "1e-9"), ("XDispOrg", "0"), ("XInc", "2e-11"), ("XOrg", "-3e-10"),
        ("XUnits", "Second"), ("YUnits", "Volt"), ("Frame", "UXR:SN0"),
    ]  # fmt: skip
    pairs = "".join(f"{k},{v}\n" for k, v in fields)
    (tmp_path / "kv.csv").write_text(f"{pairs}Data\n{column}")
    wave = read_csv(tmp_path / "kv.csv")
    assert wave.x_increment_s == 2e-11 and wave.x_origin_s == -3e-10
    assert wave.attributes["header_fields"]["frame"] == "UXR:SN0"
    names = ",".join(k for k, _ in fields) + "\n" + ",".join(v for _, v in fields) + "\nData\n"
    (tmp_path / "row.csv").write_text(names + column)
    again = read_csv(tmp_path / "row.csv")
    assert again.x_increment_s == 2e-11 and again.x_origin_s == -3e-10
    (tmp_path / "pts.csv").write_text(pairs.replace("Points,64", "Points,99") + f"Data\n{column}")
    assert "Points is 99" in read_csv(tmp_path / "pts.csv").attributes["warnings"][0]
    (tmp_path / "xu.csv").write_text(pairs.replace("Second", "Hertz") + f"Data\n{column}")
    with pytest.raises(UxrImportError, match="X unit"):
        read_csv(tmp_path / "xu.csv")


# ----------------------------------------------------------------------------- BIN
def test_bin_round_trip_strict_layout(tmp_path):
    (tmp_path / "a.bin").write_bytes(make_bin(RAMP, xinc=4e-12, xorg=1e-9))
    wave = read_bin(tmp_path / "a.bin")
    assert np.allclose(wave.samples_v, RAMP.astype(np.float32))
    assert wave.x_increment_s == 4e-12 and wave.x_origin_s == 1e-9
    assert (
        "pp2093" in wave.attributes["widths"] and "no real file" in wave.attributes["layout_source"]
    )
    assert read_scope_file(tmp_path / "a.bin").source_format == "bin"


def test_bin_bad_files_rejected(tmp_path):
    for name, blob, word in [
        ("size", make_bin(RAMP, size_delta=4), "File Size"),
        ("type", make_bin(RAMP, buffer_type=2), "buffer type"),
        ("yunit", make_bin(RAMP, y_units=3), "units"),
        ("xinc", make_bin(RAMP, xinc=0.0), "positive"),
        ("short", make_bin(RAMP)[:-8], "File Size"),
        ("cookie", make_bin(RAMP, cookie=b"XX"), "cookie"),
        ("version", make_bin(RAMP, version=b"01"), "version"),
        ("wtype", make_bin(RAMP, wave_type=2), "waveform type"),
    ]:
        (tmp_path / f"{name}.bin").write_bytes(blob)
        with pytest.raises(UxrImportError, match=word):
            read_bin(tmp_path / f"{name}.bin")


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
    bandwidth=None,
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
        if bandwidth is not None:  # 4th-order Butterworth magnitude, zero phase
            f = np.fft.rfftfreq(tiled.size, 1 / fs_awg)
            continuous = np.fft.irfft(
                np.fft.rfft(tiled) / np.sqrt(1 + (f / bandwidth) ** 8), n=tiled.size
            )
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
    assert result.clock_confidence == "medium" and result.clock_stderr_ppm is not None
    assert any("One preamble" in w for w in result.warnings)
    assert any("decision-directed" in w for w in result.warnings)
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
    assert pooled.ser_report.startswith(
        f"0 errors in {pooled.symbols} symbols, 95% upper bound {bound:.3g}"
    )
    assert pooled.ber_report.startswith(f"0 errors in {pooled.bits} bits, 95% upper bound")
    # capture-level statistics exist at zero errors too, and count distinct symbols once
    distinct_bound = 1 - 0.05 ** (1 / pooled.distinct_symbols)
    assert pooled.per_frame_symbol_errors == [0] * result.frames_analyzed
    assert pooled.ser_upper_95_distinct == pytest.approx(distinct_bound, rel=1e-6)
    assert f"{distinct_bound:.3g}" in pooled.ser_report and "repeat the same" in pooled.ser_report
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
    # Payload decisions may steer timing (a hundredth of a sample here), never the fits.
    for good, hurt in zip(a.frames, b.frames, strict=True):
        assert np.allclose(good.ffe_taps, hurt.ffe_taps, atol=5e-3)
        assert np.allclose(good.likelihood.means, hurt.likelihood.means, atol=5e-3)
        assert np.allclose(good.likelihood.sigmas, hurt.likelihood.sigmas, atol=5e-3)
        assert good.gain_v_per_level == pytest.approx(hurt.gain_v_per_level, rel=5e-3)
        assert good.offset_v == pytest.approx(hurt.offset_v, abs=5e-3)
    assert all(abs(f.timing_drift_samples) < 0.5 for f in b.frames)


def test_single_frame_ser_matches_multi_frame_ser_on_a_long_frame():
    """One preamble gives a clock good to tens of ppm; over 32768 symbols that drifts."""
    frame = uniform_frame(32768, seed=5)
    for ppm, seed in ((150.0, 3), (-110.0, 4)):
        kw = {"link": False, "sigma": 0.33, "sps": 8, "bandwidth": 0.9 * SYMBOL_RATE, "seed": seed}
        single = scope_capture(frame, ppm, frames=1.02, start_frac=0.985, **kw)
        multi = scope_capture(frame, ppm, frames=3.4, start_frac=0.2, **kw)
        one = analyze_scope_capture(single, SYMBOL_RATE, frame, UNIFORM_PRIORS)
        many = analyze_scope_capture(multi, SYMBOL_RATE, frame, UNIFORM_PRIORS)
        assert one.frames_analyzed == 1 and one.clock_confidence == "medium"
        assert many.frames_analyzed >= 2 and many.map.symbol_errors > 0
        assert abs(one.clock_offset_ppm - ppm) < 1.0 and abs(many.clock_offset_ppm - ppm) < 1.0
        assert one.clock_stderr_ppm is not None and one.clock_stderr_ppm < 2.0
        assert one.timing_residual_rms_samples < 0.3 and one.rate_estimate_reliable
        assert abs(one.frames[0].timing_drift_samples) > 0.3  # the drift was real and followed
        ser_one = one.map.symbol_errors / one.map.symbols
        ser_many = many.map.symbol_errors / many.map.symbols
        assert ser_one < 1.5 * ser_many + 1e-4


def test_untracked_diagnostic_shows_the_drift_that_tracking_removes():
    frame = uniform_frame(32768, seed=5)
    wave = scope_capture(
        frame, 150.0, frames=3.4, start_frac=0.2, sps=8, link=False, sigma=0.3,
        bandwidth=0.9 * SYMBOL_RATE,
    )  # fmt: skip
    on = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    off = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS, compensate_clock=False)
    assert off.map.symbol_errors > 100 * (on.map.symbol_errors + 1)


def blank_preamble(wave, frame, number, sps=32):
    """Replace the preamble of one looped frame (its index in the record) by zeros."""
    samples = wave.samples_v.copy()
    length = frame.indices.size * sps
    begin = number * length
    samples[begin : begin + PREAMBLE_LENGTH * sps] = 0.0
    return ScopeWaveform(
        samples, wave.x_increment_s, 0.0, "V", 1, None, None, None, "synthetic", {}
    )


def test_frame_with_damaged_preamble_is_reported_lost_not_dropped_silently():
    frame = uniform_frame(5120)
    wave = scope_capture(frame, 40.0, frames=6.3, start_frac=0.0, link=False, sigma=0.3, seed=2)
    base = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    hurt = analyze_scope_capture(blank_preamble(wave, frame, 3), SYMBOL_RATE, frame, UNIFORM_PRIORS)
    assert base.frames_lost == 0 and base.frames_expected == base.frames_analyzed
    assert hurt.frames_lost == 1 and len(hurt.lost_frame_numbers) == 1
    assert hurt.frames_expected == hurt.frames_analyzed + 1 == base.frames_expected
    assert hurt.rate_estimate_reliable is False
    assert any("lost" in w for w in hurt.warnings)
    pooled = hurt.map
    payload = frame.indices.size - frame.payload_start
    assert pooled.lost_frames == 1 and pooled.lost_symbols == payload
    assert "EXCLUDES 1 lost frame(s)" in pooled.ser_report
    worst = (pooled.symbol_errors + payload) / (pooled.symbols + payload)
    assert pooled.ser_worst_case == pytest.approx(worst) and worst > 10 * (
        pooled.symbol_errors / pooled.symbols
    )
    assert "EXCLUDES" in pooled.ber_report and pooled.ber_worst_case > 0.1


def test_irregular_frame_spacing_is_not_fitted_and_the_warning_is_true():
    frame = uniform_frame(5120)
    wave = scope_capture(frame, 40.0, frames=6.3, start_frac=0.0, link=False, sigma=0.3, seed=2)
    length = frame.indices.size * 32
    samples = wave.samples_v
    gap = np.full(37 * 32, samples.mean())
    broken = np.concatenate([samples[: 3 * length], gap, samples[3 * length :]])
    result = analyze_scope_capture(
        ScopeWaveform(broken, wave.x_increment_s, 0.0, "V", 1, None, None, None, "synthetic", {}),
        SYMBOL_RATE,
        frame,
        UNIFORM_PRIORS,
    )
    assert any("irregular" in w and "not used" in w for w in result.warnings)
    assert result.clock_confidence == "low" and result.rate_estimate_reliable is False
    assert result.frames_lost == 0 and result.frames_analyzed >= 4
    # frames after the gap are still decoded with their own positions
    assert result.map.symbol_errors < 0.01 * result.map.symbols
    assert abs(result.clock_offset_ppm - 40) < 60  # fallback clock: low confidence, not the fit


def test_training_capture_reports_nothing_derived_from_the_payload():
    frame = uniform_frame()
    wave = scope_capture(frame, 30.0, link=False, sigma=0.3)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS, score_payload=False)
    assert result.map is None and result.minimum_distance is None
    assert result.snr_db is None and result.r_bmd is None and result.r_smd is None
    assert result.symbol_histogram is None and result.eye.shape[0] == 0
    for item in result.frames:
        assert item.map is None and item.minimum_distance is None and item.decisions_map.size == 0
    assert abs(result.clock_offset_ppm - 30) < 1.0 and result.frames_analyzed >= 3


def test_level_counts_are_distinct_payload_symbols_not_frames_times_symbols():
    probabilities = [0.04, 0.46, 0.46, 0.04]
    frame = build_frame("synthetic-rare", probabilities, 2048, 5)
    sent = frame.indices[frame.payload_start :]
    wave = scope_capture(frame, 20.0, frames=8.3, start_frac=0.5, sps=16)
    result = analyze_scope_capture(wave, SYMBOL_RATE, frame, np.array(probabilities))
    assert result.frames_analyzed >= 6
    assert result.level_test_symbols == [int((sent == k).sum()) for k in range(4)]
    assert result.distinct_payload_symbols == sent.size
    assert min(result.level_test_symbols) < 100 and not result.rate_estimate_reliable
    assert any("distinct test symbols" in w for w in result.warnings)
    assert any(f"repeat the same {sent.size} payload symbols" in w for w in result.warnings)


def test_short_flat_and_featureless_captures_fail_with_clear_messages():
    frame = uniform_frame()
    n = frame.indices.size
    for size in (2, 100, 9000):
        wave = ScopeWaveform(
            np.arange(size) % 7.0, 1 / 256e9, 0.0, "V", 1, None, None, None, "s", {}
        )
        with pytest.raises(ValueError, match="Capture too short"):
            analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)
    length = 3 * n * 32
    rng = np.random.default_rng(0)
    flat = {
        "zeros": np.zeros(length),
        "constant": np.full(length, 0.3),
        "step": np.r_[np.zeros(length // 2), np.ones(length - length // 2)],
        "tiny-noise-step": np.r_[np.zeros(length // 2), np.ones(length - length // 2)]
        + 1e-9 * rng.normal(size=length),
    }
    for samples in flat.values():
        wave = ScopeWaveform(samples, 1 / 256e9, 0.0, "V", 1, None, None, None, "s", {})
        with pytest.raises(ValueError, match="No preamble"):
            analyze_scope_capture(wave, SYMBOL_RATE, frame, UNIFORM_PRIORS)


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
    args += ["--registry", str(tmp_path / "registry.json")]
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
    summary = ingest_uxr(
        folder / "cap.h5", side, ROOT, PROFILE, tmp_path, registry=tmp_path / "reg.json"
    )
    assert summary["split"] == "training" and summary["error_metrics"] is None
    assert "map" not in summary and "no payload-derived value" in summary["note"]
    for key in ("snr_db", "r_bmd", "r_smd", "symbol_histogram", "minimum_distance"):
        assert key not in summary
    assert not list(tmp_path.glob("*_frames.csv"))


def test_ingest_uxr_rejects_rate_mismatch_and_missing_split(uxr_files, tmp_path):
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    reg = tmp_path / "reg.json"
    wrong = write_sidecar(folder, row, probabilities, "rate.json", rate=80e9)
    with pytest.raises(CaptureValidationError, match="differs from the file"):
        ingest_uxr(folder / "cap.h5", wrong, ROOT, PROFILE, tmp_path, registry=reg)
    near = write_sidecar(folder, row, probabilities, "near.json", rate=64e9 * 1.005, capture_id="n")
    out = ingest_uxr(folder / "cap.h5", near, ROOT, PROFILE, tmp_path / "near", registry=reg)
    assert out["split"] == "test"
    data = sidecar(row, probabilities=probabilities)
    del data["split"]
    nosplit = folder / "nosplit.json"
    nosplit.write_text(json.dumps(data))
    with pytest.raises(CaptureValidationError, match="no split"):
        ingest_uxr(folder / "cap.h5", nosplit, ROOT, PROFILE, tmp_path / "ns", registry=reg)


def test_leakage_registry_ignores_results_dir_and_is_written_only_after_success(
    uxr_files, tmp_path
):
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    reg = tmp_path / "shared" / "registry.json"
    first = write_sidecar(folder, row, probabilities, "a.json", split="training", capture_id="a")
    ingest_uxr(folder / "cap.h5", first, ROOT, PROFILE, tmp_path / "one", registry=reg)
    entry = json.loads(reg.read_text())["entries"]["a"]
    assert entry["split"] == "training" and len(entry["sha256"]) == 64
    assert len(entry["samples_sha256"]) == 64
    # a different results directory does not reset the guard
    again = write_sidecar(folder, row, probabilities, "b.json", split="test", capture_id="b")
    with pytest.raises(DataLeakageError, match="already registered as training"):
        ingest_uxr(folder / "cap.h5", again, ROOT, PROFILE, tmp_path / "two", registry=reg)
    assert "b" not in json.loads(reg.read_text())["entries"]
    renamed = write_sidecar(folder, row, probabilities, "c.json", split="test", capture_id="a")
    with pytest.raises(DataLeakageError):
        ingest_uxr(folder / "cap.h5", renamed, ROOT, PROFILE, tmp_path / "three", registry=reg)
    # same capture, same split, same content again is allowed (idempotent)
    ingest_uxr(folder / "cap.h5", first, ROOT, PROFILE, tmp_path / "one", registry=reg)
    # a failing ingest writes nothing
    other = tmp_path / "other.json"
    bad = write_sidecar(folder, row, probabilities, "d.json", capture_id="d")
    noise = tmp_path / "noise.h5"
    write_h5(noise, np.random.default_rng(0).normal(size=300000) * 1000, "int16", xinc=1 / 64e9)
    with pytest.raises(ValueError, match="No preamble"):
        ingest_uxr(noise, bad, ROOT, PROFILE, tmp_path / "four", registry=other)
    assert not other.exists()


def test_ingest_gates_priors_symbol_rate_and_reference_mismatch(uxr_files, tmp_path):
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    reg = tmp_path / "r.json"
    skew = [probabilities[0] + 0.01, probabilities[1] - 0.01, *probabilities[2:]]
    side = write_sidecar(folder, row, skew, "skew.json", capture_id="skew")
    with pytest.raises(CaptureValidationError, match="do not match the manifest"):
        ingest_uxr(folder / "cap.h5", side, ROOT, PROFILE, tmp_path, registry=reg)
    data = sidecar(row, probabilities=probabilities, capture_id="rate")
    data["symbol_rate_Bd"] = 7.9e9
    path = folder / "symrate.json"
    path.write_text(json.dumps(data))
    with pytest.raises(CaptureValidationError, match="symbol rate"):
        ingest_uxr(folder / "cap.h5", path, ROOT, PROFILE, tmp_path, registry=reg)
    assert not reg.exists()


def test_wrong_reference_is_flagged_as_suspected_mismatch(tmp_path):
    import csv

    from opticps.measurement.uxr_ingest import ingest_uxr

    with (ROOT / PROFILE / "experiment_manifest.csv").open() as handle:
        row = next(
            r for r in csv.DictReader(handle) if r["waveform_filename"].endswith("Uniform.csv")
        )
    probabilities = [float(row[f"probability_{k}"]) for k in ("minus3", "minus1", "plus1", "plus3")]
    other = uniform_frame(32768, seed=77)  # same preamble, different training and payload
    wave = scope_capture(other, 25.0, frames=3.4, start_frac=0.3, sps=8, link=False, seed=3)
    step = float(np.abs(wave.samples_v).max()) / 30000
    write_h5(
        tmp_path / "w.h5",
        np.round(wave.samples_v / step),
        "int16",
        xinc=1 / 64e9,
        yinc=step,
        yorg=0,
    )
    side = write_sidecar(tmp_path, row, probabilities, "w.json")
    summary = ingest_uxr(
        tmp_path / "w.h5", side, ROOT, PROFILE, tmp_path / "res", registry=tmp_path / "r.json"
    )
    assert summary["reference_mismatch_suspected"] is True
    assert summary["rate_estimate_reliable"] is False
    assert any("reference_mismatch_suspected" in w for w in summary["warnings"])


def clone_results(source, folder, waveform, runs, offset, unreliable=()):
    """Copy one real ingest-uxr result under new run ids, with a shifted R_BMD (test fixture)."""
    folder.mkdir(parents=True, exist_ok=True)
    for run in range(1, runs + 1):
        item = json.loads(source.read_text())
        item["capture_id"] = f"{waveform}-r{run}"
        item["waveform"] = waveform
        item["sidecar"]["capture_id"] = item["capture_id"]
        item["sidecar"]["run_id"] = f"r{run}"
        item["r_bmd"] = 1.5 + offset + 0.01 * run
        item["rate_estimate_reliable"] = run not in unreliable
        (folder / f"{item['capture_id']}_analysis.json").write_text(json.dumps(item))


def test_compare_uxr_builds_paired_comparison_audit_and_report(uxr_files, tmp_path, capsys):
    from opticps.measurement.compare import MIN_PAIRED_RUNS
    from opticps.measurement.uxr_compare import compare_uxr
    from opticps.measurement.uxr_ingest import ingest_uxr

    folder, row, probabilities = uxr_files
    side = write_sidecar(folder, row, probabilities, "cmp.json", capture_id="seed")
    ingest_uxr(
        folder / "cap.h5", side, ROOT, PROFILE, tmp_path / "one", registry=tmp_path / "r.json"
    )
    source = tmp_path / "one" / "seed_analysis.json"
    results = tmp_path / "res"
    clone_results(source, results, "PAM4_A", 6, 0.00, unreliable=(6,))
    clone_results(source, results, "PAM4_B", 6, 0.20)
    train = json.loads(source.read_text())
    train.update(capture_id="train", split="training", error_metrics=None)
    train["sidecar"].update(capture_id="train", split="training")
    (results / "train_analysis.json").write_text(json.dumps(train))
    summary = compare_uxr(results)
    assert summary["test_captures"] == 12 and summary["training_captures"] == 1
    assert summary["excluded_unreliable_rate_estimate"] == ["PAM4_A-r6"]
    (pair,) = summary["comparisons"]
    assert pair["runs"] == MIN_PAIRED_RUNS and pair["metric"].startswith(
        "paired difference in R_BMD"
    )
    assert pair["mean"] == pytest.approx(-0.20) and pair["verdict"].startswith("lower:")
    rows = {r["variable"]: r for r in summary["fairness_audit"]}
    assert rows["Symbol rate"]["status"] == "controlled"
    assert rows["Optical launch power"]["status"] == "not recorded"
    text = (results / "uxr_report.md").read_text()
    assert "Fairness audit" in text and "lower:" in text and "upper bound" in text
    assert (results / "capture_metrics.csv").exists()
    assert main(["compare-uxr", "--results", str(results)]) == 0
    out = capsys.readouterr().out
    assert "PAM4_A vs PAM4_B: lower:" in out and "unreliable estimate): PAM4_A-r6" in out
    # fewer paired runs than the minimum: the same wording as the simulated comparison
    clone_results(source, tmp_path / "few", "PAM4_A", 4, 0.0)
    clone_results(source, tmp_path / "few", "PAM4_B", 4, 0.2)
    (few,) = compare_uxr(tmp_path / "few")["comparisons"]
    assert few["result"] == f"insufficient paired runs (need {MIN_PAIRED_RUNS})"


def test_compare_uxr_refuses_empty_duplicate_and_mixed_split_results(uxr_files, tmp_path):
    from opticps.measurement.uxr_compare import compare_uxr

    folder, row, probabilities = uxr_files
    with pytest.raises(FileNotFoundError, match="ingest-uxr"):
        compare_uxr(tmp_path)
    assert main(["compare-uxr", "--results", str(tmp_path)]) == 1


def test_periodic_analyze_refuses_measured_captures_and_points_to_ingest_uxr(tmp_path, capsys):
    from opticps.measurement.compare import analyze_directory

    meta = {
        "schema_version": "1.0", "capture_id": "m1", "related_transmit_experiment_id": "e",
        "run_id": "r1", "split": "test", "data_source": "measured",
        "capture_timestamp": "2026-11-01T10:00:00+00:00", "receiver_instrument_model": "x",
        "transmitter_instrument_model": "Keysight M8199B",
        "capture_sample_rate_Sa_per_s": 80e9, "symbol_rate_Bd": 8e9,
        "receiver_bandwidth_Hz": 30e9, "fiber_length_km": 0, "attenuation_dB": 0,
        "optical_received_power_dBm": -10, "symbol_probabilities": [0.25] * 4,
        "units": {"time": "s", "voltage": "V"},
    }  # fmt: skip
    (tmp_path / "m1.json").write_text(json.dumps(meta))
    np.savez(tmp_path / "m1.npz", received_voltage_v=np.zeros(64) + np.arange(64))
    with pytest.raises(CaptureValidationError, match="ingest-uxr"):
        analyze_directory(tmp_path, ROOT, PROFILE, tmp_path / "out")
    args = ["analyze", "--input", str(tmp_path), "--profile", PROFILE]
    assert main([*args, "--results", str(tmp_path / "o")]) == 1
    assert "ingest-uxr" in capsys.readouterr().err


def test_ingest_uxr_cli_prints_clean_errors_and_accepts_segment_options(
    uxr_files, tmp_path, capsys
):
    folder, row, probabilities = uxr_files
    side = write_sidecar(folder, row, probabilities, "cli.json", rate=1e11, capture_id="cli")
    base = [
        "ingest-uxr", "--sidecar", str(side), "--profile", PROFILE,
        "--output", str(ROOT), "--results", str(tmp_path / "r"),
        "--registry", str(tmp_path / "reg.json"),
    ]  # fmt: skip
    assert main([*base, "--input", str(tmp_path / "missing.h5")]) == 1
    assert capsys.readouterr().err.startswith("error:")
    seg = tmp_path / "seg.h5"
    write_h5(seg, np.arange(128), attrs={"NumSegments": 2, "NumPoints": 64})
    assert main([*base, "--input", str(seg)]) == 1
    assert "select one with segment" in capsys.readouterr().err
    assert main([*base, "--input", str(seg), "--segment", "1"]) == 1  # selected, then too short
    assert "Capture too short" in capsys.readouterr().err
    peak = tmp_path / "peak.h5"
    write_h5(peak, np.arange(64), attrs={"WaveformType": "PEAK_DETECT"})
    assert main([*base, "--input", str(peak)]) == 1
    assert "WaveformType" in capsys.readouterr().err
    assert main([*base, "--input", str(peak), "--allow-waveform-type", "peak_detect"]) == 1
    assert "Capture too short" in capsys.readouterr().err
    assert not (tmp_path / "reg.json").exists()
