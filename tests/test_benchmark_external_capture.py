"""Gate E1: external capture reader, format verification, receiver QA (Stage 3A).

Every fixture here is built from scratch in this file, with its own byte packing and its own
signal generator (analytic raised-cosine pulses evaluated at fractional times). Nothing is taken
from a TERIPHIC file except in the tests marked with the `real_b2b` skip condition, which read the
B2B file only and never open the 2 km or 10 km file.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import struct
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import welch

from opticps.benchmarks import teriphic
from opticps.benchmarks.capture_stats import (
    PublishedReference,
    decision_clusters,
    describe_capture,
    describe_capture_with_timing,
    explore_eye,
    measured_ber,
    measured_ser,
    post_fec_ber,
)
from opticps.benchmarks.external_capture import (
    ExternalCapture,
    FormatStatus,
    Hypothesis,
    RawSpec,
    SampleLayout,
    default_hypotheses,
    evaluate_hypotheses,
    parse_keysight_bin_header,
    unique_survivor,
)
from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    Checksum,
    ErrorCode,
    Md5State,
    Provenance,
    Split,
)
from opticps.benchmarks.timing import (
    TimingError,
    interpolate_cubic,
    recover_timing,
    samples_per_symbol,
)
from opticps.cli.main import main as cli_main
from opticps.measurement.uxr_import import UxrImportError, read_bin


# ----------------------------------------------------------------------------- fixtures
def raised_cosine(x: np.ndarray, alpha: float) -> np.ndarray:
    """Raised-cosine pulse, time in symbols, evaluated analytically at any real time."""
    x = np.asarray(x, dtype=float)
    denominator = 1.0 - (2.0 * alpha * x) ** 2
    singular = np.abs(denominator) < 1e-9
    out = np.sinc(x) * np.cos(np.pi * alpha * x) / np.where(singular, 1.0, denominator)
    out[singular] = (np.pi / 4.0) * np.sinc(1.0 / (2.0 * alpha))
    return out


def pam4_waveform(
    n_symbols: int,
    sps: float,
    *,
    seed: int = 1,
    drift: float = 0.0,
    wander_symbols: float = 0.0,
    wander_period: float = 3000.0,
    noise: float = 0.03,
    alpha: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(samples, symbols, true symbol times in samples) of a PAM4 waveform with a drifting clock.

    Symbol k sits at s_k = 40 + k*sps*(1+drift) + wander*sps*sin(2 pi k / period). The waveform is
    the sum of pulses evaluated at the exact fractional sample times: no resampling is involved.
    """
    rng = np.random.default_rng(seed)
    symbols = rng.choice([-3.0, -1.0, 1.0, 3.0], size=n_symbols)
    k = np.arange(n_symbols)
    times = (
        40.0
        + k * sps * (1.0 + drift)
        + wander_symbols * sps * np.sin(2 * np.pi * k / wander_period)
    )
    n = np.arange(int(times[-1]) + 40, dtype=float)
    centre = np.clip(np.floor((n - 40.0) / (sps * (1.0 + drift))).astype(int), 0, n_symbols - 1)
    x = np.zeros_like(n)
    for offset in range(-12, 13):
        index = np.clip(centre + offset, 0, n_symbols - 1)
        valid = (centre + offset >= 0) & (centre + offset < n_symbols)
        x += np.where(valid, symbols[index] * raised_cosine((n - times[index]) / sps, alpha), 0.0)
    return x + rng.normal(0.0, noise, size=x.size), symbols, times


def keysight_image(
    samples: np.ndarray,
    *,
    xinc: float = 1.0 / 256e9,
    size_delta: int = 0,
    points_delta: int = 0,
    waveforms: int = 1,
    buffer_type: int = 1,
    width: int = 4,
    x_units: int = 2,
    y_units: int = 1,
    cookie: bytes = b"AG",
    version: bytes = b"10",
    byte_order: str = "<",
    extra: bytes = b"",
) -> bytes:
    """A Keysight-BIN-like file written field by field (independent of the reader's packing)."""
    e = byte_order
    data = np.asarray(samples, dtype=e + "f4").tobytes()
    n = len(samples)
    wave = b"".join(
        [
            struct.pack(e + "i", 140), struct.pack(e + "i", 1), struct.pack(e + "i", 1),
            struct.pack(e + "i", n + points_delta), struct.pack(e + "i", 1),
            struct.pack(e + "f", n * xinc), struct.pack(e + "d", 0.0),
            struct.pack(e + "d", xinc), struct.pack(e + "d", 0.0),
            struct.pack(e + "i", x_units), struct.pack(e + "i", y_units),
            b"01 JAN 2026".ljust(16, b"\x00"), b"12:00:00".ljust(16, b"\x00"),
            b"SYNTH:SN0".ljust(24, b"\x00"), b"Channel 1".ljust(16, b"\x00"),
            struct.pack(e + "d", 0.0), struct.pack(e + "I", 0),
        ]
    )  # fmt: skip
    data_header = (
        struct.pack(e + "i", 12) + struct.pack(e + "h", buffer_type)
        + struct.pack(e + "h", width) + struct.pack(e + "i", len(data))
    )  # fmt: skip
    body = wave + data_header + data + extra
    total = 12 + len(body)
    return (
        cookie
        + version
        + struct.pack(e + "i", total + size_delta)
        + struct.pack(e + "i", waveforms)
        + body
    )


@pytest.fixture(scope="module")
def signal() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return pam4_waveform(30000, 5.12, seed=3)


@pytest.fixture()
def fixture_bin(tmp_path: Path, signal) -> Path:
    path = tmp_path / "fixture.bin"
    path.write_bytes(keysight_image(signal[0], xinc=1.0 / 256e9))
    return path


def open_fixture(path: Path) -> ExternalCapture:
    return ExternalCapture.open_keysight_bin(path)


def bad(code: ErrorCode = ErrorCode.FORMAT_UNKNOWN):
    return pytest.raises(BenchmarkError, match=code.value)


# ----------------------------------------------------------------------------- format: rejections
def test_fixture_with_keysight_layout_is_accepted_and_scale_is_normalized(fixture_bin):
    capture = open_fixture(fixture_bin)
    assert capture.layout.container == "keysight_bin" and capture.layout.data_offset == 164
    assert capture.scale == "normalized" and capture.layout.dtype == "<f4"
    assert capture.checksum is not None and capture.checksum.sha256_local


def test_fake_bin_files_are_not_keysight(tmp_path):
    rng = np.random.default_rng(5)
    noise = rng.normal(size=4096).astype("<f4").tobytes()
    cases = {
        "float32_noise": noise,
        "int16_noise": rng.integers(-2000, 2000, 4096).astype("<i2").tobytes(),
        "zeros": bytes(4096),
        "cookie_only": b"AG10" + bytes(8),
        "cookie_and_noise": b"AG10" + noise,
        "wrong_cookie": b"XX10" + bytes(4000),
        "tiny": b"AG",
    }
    for tag, blob in cases.items():
        path = tmp_path / f"50G_PAM4_PD1_B2B_Subassembly1_{tag}.bin"
        path.write_bytes(blob)
        with bad():
            ExternalCapture.open_keysight_bin(path)
        assert path.read_bytes() == blob  # never modified


@pytest.mark.parametrize(
    "overrides",
    [
        {"size_delta": 4}, {"size_delta": -4}, {"points_delta": 1}, {"points_delta": -3},
        {"waveforms": 2}, {"waveforms": 0}, {"buffer_type": 2}, {"width": 8},
        {"x_units": 1}, {"y_units": 3}, {"cookie": b"AX"}, {"version": b"11"},
        {"extra": b"\x00"}, {"extra": bytes(40)},
    ],
)  # fmt: skip
def test_corrupted_header_fields_are_refused(tmp_path, signal, overrides):
    path = tmp_path / "c.bin"
    path.write_bytes(keysight_image(signal[0][:4096], **overrides))
    with bad():
        ExternalCapture.open_keysight_bin(path)


def test_truncated_files_are_refused(tmp_path, signal):
    good = keysight_image(signal[0][:8192])
    for cut in (1, 3, 4, 100, len(good) - 150, len(good) - 163):
        path = tmp_path / f"t{cut}.bin"
        path.write_bytes(good[:-cut])
        with bad():
            ExternalCapture.open_keysight_bin(path)
    header_only = tmp_path / "h.bin"
    header_only.write_bytes(good[:164])
    with bad():
        ExternalCapture.open_keysight_bin(header_only)


def test_duplicate_header_and_second_waveform_are_refused(tmp_path, signal):
    good = keysight_image(signal[0][:4096])
    for tag, blob in {
        "doubled_file": good + good,
        "header_twice": good[:164] + good,
        "second_header_inside": good[:-8] + good[:164],
    }.items():
        path = tmp_path / f"{tag}.bin"
        path.write_bytes(blob)
        with bad():
            ExternalCapture.open_keysight_bin(path)


def test_wrong_endian_header_is_refused(tmp_path, signal):
    path = tmp_path / "be.bin"
    path.write_bytes(keysight_image(signal[0][:4096], byte_order=">"))
    with bad():
        ExternalCapture.open_keysight_bin(path)


@pytest.mark.parametrize("xinc", [0.0, -1e-12, float("nan"), float("inf"), 1e-20, 10.0])
def test_implausible_timebase_is_refused(tmp_path, signal, xinc):
    path = tmp_path / "x.bin"
    path.write_bytes(keysight_image(signal[0][:4096], xinc=xinc))
    with bad():
        ExternalCapture.open_keysight_bin(path)


def test_baud_above_half_the_sample_rate_is_implausible():
    for rate, baud in [
        (50e9, 50e9),
        (80e9, 50e9),
        (0.0, 50e9),
        (256e9, -1.0),
        (float("nan"), 5e10),
    ]:
        with pytest.raises(TimingError, match="FORMAT_UNKNOWN"):
            samples_per_symbol(rate, baud)


def test_invalid_scale_is_refused_everywhere(tmp_path):
    for scale in ("V", "mV", "dBm", "volts", "", "Normalized", None):
        with bad():
            SampleLayout("raw", "<f4", 0, 100, None, None, scale)
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps({"dtype": "<f4", "scale": "volts"}))
    raw = tmp_path / "r.bin"
    raw.write_bytes(np.zeros(5000, dtype="<f4").tobytes())
    with bad():
        ExternalCapture.open_raw(raw, RawSpec.from_sidecar(sidecar))


def test_sidecar_is_default_deny(tmp_path):
    for body in ('{"dtype": "<f4", "gain": 2}', "[]", "{}", '{"count": 5}', "not json",
                 '{"dtype": "<f4", "count": 1.5}', '{"dtype": "<f4", "x_increment_s": "a"}'):  # fmt: skip
        path = tmp_path / "s.json"
        path.write_text(body)
        with bad():
            RawSpec.from_sidecar(path)


def test_header_unit_claim_is_recorded_but_never_becomes_volts(fixture_bin):
    capture = open_fixture(fixture_bin)
    assert "not a calibration" in capture.layout.header_fields["header_y_unit"]
    stats = describe_capture(capture, qc_window=1 << 14)
    assert stats["scale"] == "normalized" and "not volts" in stats["units_note"]


# ----------------------------------------------------------------------------- raw layouts
def raw_float_file(tmp_path: Path, x: np.ndarray, dtype: str = "<f4", header: bytes = b"") -> Path:
    path = tmp_path / "raw.bin"
    path.write_bytes(header + np.asarray(x).astype(dtype).tobytes())
    return path


def test_wrong_endian_raw_layout_is_refused_and_right_one_accepted(tmp_path, signal):
    x = signal[0][:30000]
    path = raw_float_file(tmp_path, x)
    assert ExternalCapture.open_raw(path, RawSpec("<f4")).count == 30000
    for dtype in (">f4", "<i4", "<u4", "<i2", "<f8", ">i2", "|u1"):
        try:
            spec = RawSpec(dtype)
            ExternalCapture.open_raw(path, spec)
        except BenchmarkError as error:
            assert error.code is ErrorCode.FORMAT_UNKNOWN, dtype
        else:  # pragma: no cover - the assertion is the failure
            pytest.fail(f"{dtype} accepted for float32 little-endian bytes")


def test_raw_layout_with_trailing_or_truncated_bytes_is_refused(tmp_path, signal):
    x = signal[0][:20000]
    path = raw_float_file(tmp_path, x)
    path.write_bytes(path.read_bytes() + b"\x01\x02")
    with bad():
        ExternalCapture.open_raw(path, RawSpec("<f4"))
    path.write_bytes(path.read_bytes()[:-2])
    assert ExternalCapture.open_raw(path, RawSpec("<f4", count=20000)).count == 20000
    with bad():
        ExternalCapture.open_raw(path, RawSpec("<f4", count=20001))  # declared more than present


def test_hypotheses_reject_wrong_dtype_endian_and_offset_by_evidence(tmp_path, signal):
    path = raw_float_file(tmp_path, signal[0][:40000])
    results = evaluate_hypotheses(path, default_hypotheses())
    passing = [r.hypothesis.name for r in results if r.passed]
    # no structure to decide here: offsets 0 and 136 differ by whole samples, so both pass, and the
    # honest outcome is ambiguity; every other dtype and byte order fails a named check
    assert passing == ["<f4@0", "<f4@136"], passing
    with pytest.raises(BenchmarkError, match="ambiguous"):
        unique_survivor(results)
    assert unique_survivor([r for r in results if r.hypothesis.data_offset == 0]).name == "<f4@0"
    by_name = {r.hypothesis.name: r for r in results}
    assert by_name[">f4@0"].failed_names  # wrong endianness
    assert by_name["<f8@0"].failed_names and by_name["<i2@0"].failed_names
    assert by_name["<f4@0"].failed_names == ()
    # a misaligned float32 reading is evidence-rejected
    shifted = evaluate_hypotheses(path, [Hypothesis("<f4", 1), Hypothesis("<f4", 2)])
    assert not any(r.passed for r in shifted)
    # 4-byte integers holding float bit patterns are rejected by continuity, not by luck
    assert "continuous" in by_name["<i4@0"].failed_names
    assert "continuous" in by_name["<u4@0"].failed_names


def test_ambiguous_format_is_refused(tmp_path, signal):
    path = raw_float_file(tmp_path, signal[0][:40000])
    results = evaluate_hypotheses(path, [Hypothesis("<f4", 0), Hypothesis("<f4", 4)])
    assert all(r.passed for r in results)  # a one-sample shift is statistically indistinguishable
    with pytest.raises(BenchmarkError, match="ambiguous"):
        unique_survivor(results)
    none = evaluate_hypotheses(path, [Hypothesis(">f4", 0)])
    with bad():
        unique_survivor(none)


def test_a_136_byte_header_offset_is_decided_by_structure_not_statistics(tmp_path, signal):
    blob = keysight_image(signal[0][:40000])
    path = tmp_path / "k.bin"
    path.write_bytes(blob)
    layout, _ = parse_keysight_bin_header(blob[:164], len(blob))
    assert layout.data_offset == 164
    results = {
        r.hypothesis.name: r
        for r in evaluate_hypotheses(path, default_hypotheses(layout), declared=layout)
    }
    assert results["<f4@136"].failed_names == ("matches_declared_structure",)
    assert [n for n, r in results.items() if r.passed] == ["<f4@164"]


# ----------------------------------------------------------------------------- bytes and files
def test_original_bytes_are_preserved_and_mapping_is_read_only(fixture_bin):
    before = fixture_bin.read_bytes()
    mtime = fixture_bin.stat().st_mtime_ns
    capture = open_fixture(fixture_bin)
    describe_capture(capture, qc_window=1 << 14)
    assert capture.raw_bytes() == before and capture.raw_bytes(0, 4) == b"AG10"
    assert fixture_bin.read_bytes() == before and fixture_bin.stat().st_mtime_ns == mtime
    with pytest.raises(ValueError):
        capture._samples[0] = 1.0  # noqa: SLF001 - the mapping must not be writable
    with pytest.raises(ValueError):
        capture._bytes[0] = 0  # noqa: SLF001


def test_read_only_file_is_readable(fixture_bin):
    fixture_bin.chmod(0o444)
    try:
        assert open_fixture(fixture_bin).count > 1000
    finally:
        fixture_bin.chmod(0o644)


def test_md5_mismatch_and_changed_file_are_refused(fixture_bin):
    with pytest.raises(BenchmarkError, match="MD5 differs"):
        ExternalCapture.open_keysight_bin(fixture_bin, md5_supplied="0" * 32)
    md5 = hashlib.md5(fixture_bin.read_bytes()).hexdigest()
    capture = ExternalCapture.open_keysight_bin(fixture_bin, md5_supplied=md5)
    assert capture.checksum is not None and capture.checksum.md5_state is Md5State.VERIFIED
    blob = bytearray(fixture_bin.read_bytes())
    blob[-1] ^= 0xFF
    fixture_bin.write_bytes(bytes(blob))  # changed after hashing
    with pytest.raises(BenchmarkError, match="changed after it was hashed"):
        next(capture.blocks(4096))


def test_nonfinite_samples_are_refused_by_the_statistics(tmp_path, signal):
    x = signal[0][:20000].copy()
    x[10000] = np.nan
    path = tmp_path / "nan.bin"
    path.write_bytes(keysight_image(x))
    capture = open_fixture(path)
    with bad():
        describe_capture(capture, qc_window=1 << 12)


def test_constant_capture_is_refused(tmp_path):
    path = tmp_path / "flat.bin"
    path.write_bytes(keysight_image(np.full(20000, 0.5)))
    with bad():
        describe_capture(open_fixture(path), qc_window=1 << 12)


# ----------------------------------------------------------------------------- streaming
def test_streaming_matches_non_streaming_and_independent_numpy_scipy(fixture_bin, signal):
    capture = open_fixture(fixture_bin)
    common = {"hist_bins": 512, "nperseg": 1024, "qc_window": 1 << 13}
    one = describe_capture(capture, block_samples=1 << 24, **common)  # whole record, one block
    many = describe_capture(capture, block_samples=997, **common)  # odd, small blocks
    assert one["histogram"]["counts"] == many["histogram"]["counts"]  # integers: exactly equal
    assert one["level_exploration"]["estimated_levels_normalized"] == pytest.approx(
        many["level_exploration"]["estimated_levels_normalized"], rel=1e-9
    )
    assert one["qc"]["longest_identical_run"] == many["qc"]["longest_identical_run"]
    assert one["normalization"]["offset_file_units"] == pytest.approx(
        many["normalization"]["offset_file_units"], rel=1e-12
    )
    assert one["normalization"]["scale_file_units"] == pytest.approx(
        many["normalization"]["scale_file_units"], rel=1e-12
    )
    assert one["quantiles_normalized"] == pytest.approx(
        many["quantiles_normalized"], rel=1e-9, abs=1e-12
    )
    assert one["psd"]["density_normalized"] == pytest.approx(
        many["psd"]["density_normalized"], rel=1e-9
    )
    assert one["qc"]["window_mean_spread_over_std"] == pytest.approx(
        many["qc"]["window_mean_spread_over_std"], rel=1e-9
    )
    # independent references: plain numpy on the float32 samples as stored, and scipy's Welch
    stored = np.asarray(signal[0], dtype=np.float32).astype(np.float64)
    assert one["normalization"]["offset_file_units"] == pytest.approx(
        stored.mean(), rel=1e-12, abs=1e-15
    )
    assert one["normalization"]["scale_file_units"] == pytest.approx(stored.std(), rel=1e-12)
    counts, _ = np.histogram(stored, bins=512, range=(stored.min(), stored.max()))
    assert one["histogram"]["counts"] == counts.tolist()
    z = (stored - stored.mean()) / stored.std()
    f, p = welch(
        z, fs=1.0, window="hann", nperseg=1024, noverlap=512, detrend="constant", scaling="density"
    )
    assert np.allclose(one["psd"]["frequency_cycles_per_sample"], f)
    assert one["psd"]["density_normalized"] == pytest.approx(p.tolist(), rel=1e-6)
    width = one["quantile_resolution_normalized"]
    for key, value in one["quantiles_normalized"].items():
        assert abs(value - np.quantile(z, float(key))) <= 1.5 * width


def test_timing_is_independent_of_block_size(fixture_bin):
    capture = open_fixture(fixture_bin)
    a, ta = describe_capture_with_timing(
        capture, baud_bd=50e9, block_samples=1 << 24, qc_window=1 << 13
    )
    b, tb = describe_capture_with_timing(
        capture, baud_bd=50e9, block_samples=1000, qc_window=1 << 13
    )
    assert ta is not None and tb is not None
    assert ta.symbol_frequency == pytest.approx(tb.symbol_frequency, rel=1e-12)
    assert np.allclose(ta.phase_cycles, tb.phase_cycles)
    assert a["timebase"]["header_samples_per_symbol"] == b["timebase"]["header_samples_per_symbol"]


def streaming_peak(tmp_path: Path, n_symbols: int) -> tuple[int, int]:
    x, _, _ = pam4_waveform(n_symbols, 5.12, seed=9)
    path = tmp_path / f"big{n_symbols}.bin"
    path.write_bytes(keysight_image(x))
    capture = open_fixture(path)
    tracemalloc.start()
    describe_capture(
        capture,
        baud_bd=50e9,
        block_samples=1 << 15,
        qc_window=1 << 15,
        hist_bins=1024,
        nperseg=1024,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return path.stat().st_size, peak


def test_memory_budget_does_not_grow_with_the_file(tmp_path):
    small_size, small_peak = streaming_peak(tmp_path, 100_000)  # about 2 MB
    large_size, large_peak = streaming_peak(tmp_path, 400_000)  # about 8 MB
    assert large_size > 3.5 * small_size
    assert large_peak < 1.25 * small_peak  # four times the file, the same working memory
    assert large_peak < large_size / 4  # and far below one copy of the file


def test_interruption_leaves_the_file_intact_and_a_rerun_is_identical(fixture_bin):
    digest = hashlib.sha256(fixture_bin.read_bytes()).hexdigest()
    listing = sorted(p.name for p in fixture_bin.parent.iterdir())
    capture = open_fixture(fixture_bin)

    def interrupt(done: int, total: int) -> None:
        if done > total // 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        describe_capture(capture, block_samples=4096, qc_window=1 << 13, progress=interrupt)
    assert hashlib.sha256(fixture_bin.read_bytes()).hexdigest() == digest
    assert sorted(p.name for p in fixture_bin.parent.iterdir()) == listing  # no partial output
    first = describe_capture(open_fixture(fixture_bin), qc_window=1 << 13)
    second = describe_capture(capture, qc_window=1 << 13)
    assert first["histogram"]["counts"] == second["histogram"]["counts"]


# ----------------------------------------------------------------------------- timing
def test_sps_of_256_over_50_is_5_12_and_never_rounded(fixture_bin):
    assert samples_per_symbol(256e9, 50e9) == 256 / 50 == 5.12
    assert samples_per_symbol(2.048e12, 50e9) == pytest.approx(40.96)
    capture = open_fixture(fixture_bin)
    stats = describe_capture(capture, baud_bd=50e9, record_sample_rate_hz=256e9, qc_window=1 << 13)
    timebase = stats["timebase"]
    assert timebase["header_samples_per_symbol"] == pytest.approx(5.12)
    assert timebase["measured_samples_per_symbol"] == pytest.approx(5.12, rel=2e-4)
    assert timebase["measured_samples_per_symbol"] != 5.0
    assert timebase["conflict"] is False and timebase[
        "header_rate_over_record_rate"
    ] == pytest.approx(1.0)


def test_timing_recovery_follows_a_drifting_fractional_clock(tmp_path):
    sps, drift = 5.12, 3e-4
    x, symbols, times = pam4_waveform(
        40000, sps, seed=11, drift=drift, wander_symbols=0.3, noise=0.03
    )
    model = recover_timing(x, sps)
    assert model.sps_measured == pytest.approx(sps * (1 + drift), rel=5e-5)  # not 5, not 5.12
    # a longer symbol period (positive drift) is a lower symbol rate: the offset is negative
    assert abs(model.offset_ppm + drift * 1e6) < 100
    path = tmp_path / "drift.bin"
    path.write_bytes(keysight_image(x, xinc=1.0 / 256e9))
    capture = open_fixture(path)
    mean, std = float(np.float32(x).mean()), float(np.float32(x).std())
    eye = explore_eye(
        capture, model, (mean, std), first_symbol=400, symbols=8000, scan_symbols=3000
    )
    best = eye["estimated_best_phase_offset_symbols"]
    instants = model.symbol_instants(400, 8000, best)
    stored = x.astype(np.float32).astype(np.float64)
    found = interpolate_cubic(stored, instants)
    levels = np.array(eye["estimated_levels_normalized"]) * std + mean
    index = np.argmin(np.abs(found[:, None] - levels[None, :]), axis=1)
    mapped = np.array([-3.0, -1.0, 1.0, 3.0])[index]  # ascending levels, ascending symbols
    # the reference is used here only to judge the estimator: align the symbol index, then SER
    best_ser, best_shift = 1.0, 0
    for shift in range(-20, 21):  # the absolute symbol index of the clock is arbitrary
        ser = float(np.mean(mapped != symbols[400 + shift : 400 + shift + 8000]))
        if ser < best_ser:
            best_ser, best_shift = ser, shift
    assert best_ser < 2e-3, (best_ser, best_shift)
    # the recovered instants track the true drifting symbol times to a small fraction of a sample
    residual = instants - times[400 + best_shift : 400 + best_shift + 8000]
    assert float(np.std(residual - residual.mean())) < 0.15


def test_rounding_the_sampling_ratio_to_5_would_fail_on_the_same_signal():
    sps = 5.12
    x, _, _ = pam4_waveform(20000, sps, seed=12, noise=0.01)
    model = recover_timing(x, sps)
    assert model.sps_measured == pytest.approx(5.12, rel=1e-4)

    def best_sse(position) -> float:
        return min(
            decision_clusters(interpolate_cubic(x, position(o)))["within_cluster_sse"]
            for o in np.arange(32) / 32
        )

    recovered = best_sse(lambda o: model.symbol_instants(200, 3000, o))
    rounded = best_sse(lambda o: 40.0 + (o + 200.0) * 5.0 + 5.0 * np.arange(3000))  # hidden 5.0
    assert rounded > 20 * recovered, (rounded, recovered)


def test_timing_refuses_a_clock_it_cannot_track(tmp_path):
    x, _, _ = pam4_waveform(20000, 5.12, seed=13, drift=3e-3)  # 0.3 % offset: outside the range
    with pytest.raises(TimingError):
        recover_timing(x, 5.12)
    with pytest.raises(TimingError, match="fewer than three"):
        recover_timing(x[:2000], 5.12)
    rng = np.random.default_rng(0)
    noise = rng.normal(size=60000)
    with pytest.raises(TimingError):
        recover_timing(noise, 5.12)


def test_interpolator_is_exact_on_cubics_and_refuses_the_edges():
    t = np.arange(50, dtype=float)
    x = 0.3 * t**3 - 2 * t**2 + t + 5
    at = np.array([3.25, 10.5, 40.75])
    assert np.allclose(interpolate_cubic(x, at), 0.3 * at**3 - 2 * at**2 + at + 5)
    for edge in (np.array([0.5]), np.array([48.5]), np.array([np.nan])):
        with pytest.raises(TimingError):
            interpolate_cubic(x, edge)


# ----------------------------------------------------------------------------- metrics and names
def test_ber_ser_and_post_fec_refuse_without_a_published_reference():
    decisions = np.array([0, 1, 1, 0, 1, 0, 0, 1])
    for function in (measured_ber, measured_ser, post_fec_ber):
        with bad(ErrorCode.REFERENCE_SEQUENCE_MISSING):
            function(decisions)
        for provenance in (Provenance.INFERRED, Provenance.SIMULATED, Provenance.DIGITIZED_FIGURE):
            with bad(ErrorCode.REFERENCE_SEQUENCE_MISSING):
                function(decisions, PublishedReference(decisions.copy(), provenance, "recovered"))
    published = PublishedReference(
        decisions.copy(), Provenance.PUBLISHED_MEASUREMENT, "record text"
    )
    assert measured_ber(decisions, published) == 0.0
    assert measured_ser(np.array([0, 1, 1, 1, 1, 0, 0, 1]), published) == pytest.approx(1 / 8)
    with pytest.raises(BenchmarkError, match="FEC decoder"):
        post_fec_ber(decisions, published)
    with pytest.raises(BenchmarkError, match="differ in length"):
        measured_ber(decisions[:4], published)


def keys(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{prefix}{key}"
            yield from keys(value, f"{prefix}{key}.")


def test_descriptive_metrics_work_and_level_values_carry_estimated_names(fixture_bin):
    capture = open_fixture(fixture_bin)
    stats, timing = describe_capture_with_timing(capture, baud_bd=50e9, qc_window=1 << 13)
    assert timing is not None
    for field in (
        "histogram",
        "quantiles_normalized",
        "psd",
        "level_exploration",
        "qc",
        "timebase",
    ):
        assert field in stats
    assert stats["level_exploration"]["structure"]["peak_count"] >= 1
    eye = explore_eye(
        capture,
        timing,
        (stats["normalization"]["offset_file_units"], stats["normalization"]["scale_file_units"]),
        first_symbol=100,
        symbols=3000,
        scan_symbols=1500,
    )
    assert 0.0 <= eye["estimated_decision_error_proxy"] <= 1.0
    assert "NOT a BER or SER" in eye["estimated_decision_error_proxy_caveat"]
    forbidden = re.compile(r"(^|[._])(ber|ser|post_fec\w*|error_rate\w*)($|[._])")
    for name in list(keys(stats)) + list(keys(eye)):
        assert not forbidden.search(name), name
    for name in keys(eye):
        if "level" in name or "proxy" in name or "opening" in name or "cluster" in name:
            assert (
                "estimated" in name
                or "caveat" in name
                or "eye_" in name
                or name.startswith("symbols")
            ), name


# ----------------------------------------------------------------------------- holdout and CLI
def source_with_holdout_md5(md5: str):
    source = teriphic.load_config()
    assets = []
    for asset in source.assets:
        if asset.split is Split.LOCKED_TEST:
            asset = dataclasses.replace(asset, checksum=Checksum(md5_supplied=md5))
        assets.append(asset)
    return dataclasses.replace(source, assets=tuple(assets))


def test_holdout_names_are_refused_before_any_byte_is_read(tmp_path):
    for name in ("50G_PAM4_PD1_2km_Subassembly1.bin", "50G_PAM4_PD1_10KM_SUBASSEMBLY1.BIN"):
        path = tmp_path / name
        path.write_bytes(b"x")
        with bad(ErrorCode.LEAKAGE_DETECTED):
            teriphic.guard_sample_read(path)
        with bad(ErrorCode.LEAKAGE_DETECTED):
            teriphic.open_b2b(path)
        with bad(ErrorCode.LEAKAGE_DETECTED):
            teriphic.verify_b2b_format(path)


def test_unregistered_file_under_data_external_is_refused(tmp_path):
    folder = tmp_path / "data" / "external" / "teriphic"
    folder.mkdir(parents=True)
    other = folder / "50G_PAM4_PD2_B2B_Subassembly1.bin"
    other.write_bytes(b"x")
    with bad(ErrorCode.LEAKAGE_DETECTED):
        teriphic.guard_sample_read(other)
    assert teriphic.guard_sample_read(tmp_path / "anything.bin") is None  # a fixture elsewhere


def test_a_renamed_copy_of_a_holdout_is_caught_by_its_hash_before_the_header(tmp_path, signal):
    path = tmp_path / "innocent_name.bin"
    path.write_bytes(keysight_image(signal[0][:4096]))
    md5 = hashlib.md5(path.read_bytes()).hexdigest()
    with bad(ErrorCode.LEAKAGE_DETECTED):
        teriphic.open_b2b(path, source=source_with_holdout_md5(md5))
    other = tmp_path / "other.bin"
    other.write_bytes(keysight_image(signal[0][:8192]))
    assert teriphic.open_b2b(other, source=source_with_holdout_md5(md5)).count == 8192


def test_cli_refuses_download_and_holdout_and_reads_nothing_for_metadata_only(tmp_path, capsys):
    assert cli_main(["benchmark", "inspect-format", "--allow-download"]) == 2
    assert "REFUSED" in capsys.readouterr().err
    holdout = tmp_path / "50G_PAM4_PD1_2km_Subassembly1.bin"
    holdout.write_bytes(b"x")
    assert cli_main(["benchmark", "inspect-format", "--file", str(holdout)]) == 1
    assert "LEAKAGE_DETECTED" in capsys.readouterr().err
    missing = tmp_path / "50G_PAM4_PD1_10km_Subassembly1.bin"  # does not exist: never opened
    assert cli_main(["benchmark", "inspect-format", "--metadata-only", "--file", str(missing)]) == 0
    out = capsys.readouterr().out
    assert "LOCKED_TEST" in out and "the file was not opened" in out
    assert not missing.exists()


def test_cli_inspects_fixtures(fixture_bin, tmp_path, capsys):
    assert cli_main(["benchmark", "inspect-format", "--file", str(fixture_bin)]) == 0
    assert "Keysight BIN structure accepted" in capsys.readouterr().out
    raw = raw_float_file(tmp_path, np.sin(np.arange(20000) / 7.0) + 0.01 * np.cos(np.arange(20000)))
    sidecar = tmp_path / "raw.json"
    sidecar.write_text(json.dumps({"dtype": "<f4", "x_increment_s": 4e-12}))
    assert (
        cli_main(["benchmark", "inspect-format", "--file", str(raw), "--metadata", str(sidecar)])
        == 0
    )
    sidecar.write_text(json.dumps({"dtype": ">f4"}))
    assert (
        cli_main(["benchmark", "inspect-format", "--file", str(raw), "--metadata", str(sidecar)])
        == 1
    )
    assert "FORMAT_UNKNOWN" in capsys.readouterr().err


def test_no_network_or_download_code_in_the_new_modules():
    for name in ("external_capture", "capture_stats", "timing", "teriphic"):
        text = Path(f"src/opticps/benchmarks/{name}.py").read_text()
        for forbidden in ("urllib", "requests", "socket", "http.client", "subprocess", "curl"):
            assert f"import {forbidden}" not in text and f"from {forbidden}" not in text, name
        assert "allow_download" not in text and "def download" not in text


def test_read_bin_still_refuses_what_the_adapter_refuses(tmp_path, signal):
    path = tmp_path / "t.bin"
    path.write_bytes(keysight_image(signal[0][:4096]) + b"\x00")  # size field now disagrees
    with pytest.raises(UxrImportError):
        read_bin(path)
    good = tmp_path / "g.bin"
    good.write_bytes(keysight_image(signal[0][:4096]))
    assert len(read_bin(good).samples_v) == 4096  # the two parsers agree on a well-formed file
    assert open_fixture(good).count == 4096


# ----------------------------------------------------------------------------- real B2B file
B2B = Path("data/external/teriphic") / teriphic.B2B_FILENAME
real_b2b = pytest.mark.skipif(not B2B.is_file(), reason="local TERIPHIC B2B file absent")


@real_b2b
def test_real_b2b_format_verdict_and_evidence(monkeypatch):
    opened: list[str] = []
    real_memmap = np.memmap
    real_open = Path.open

    def spy_open(self, *args, **kwargs):
        if self.suffix == ".bin":
            opened.append(self.name)
        return real_open(self, *args, **kwargs)

    def spy_memmap(path, *args, **kwargs):
        opened.append(Path(path).name)
        return real_memmap(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    monkeypatch.setattr(np, "memmap", spy_memmap)
    report = teriphic.verify_b2b_format()
    assert set(opened) == {teriphic.B2B_FILENAME}  # no other file was opened or mapped
    assert report.status is FormatStatus.SUPPORTED_BY_EVIDENCE, report.summary
    assert report.layout["dtype"] == "<f4" and report.layout["data_offset"] == 164
    assert report.layout["samples"] == 40_959_993 and report.layout["scale"] == "normalized"
    survivors = [h["hypothesis"] for h in report.hypotheses if h["passed_all"]]
    assert survivors == ["<f4@164"], survivors
    rows = {h["hypothesis"]: h for h in report.hypotheses}
    assert rows["<f4@136"]["failed_checks"] == ["matches_declared_structure"]  # structure decides
    assert "continuous" in rows["<i4@164"]["failed_checks"]
    assert (
        "finite" in rows[">f4@164"]["failed_checks"]
        or "bounded" in rows[">f4@164"]["failed_checks"]
    )
    evidence = report.evidence
    assert evidence["level_structure"]["four_levels"]
    timebase = evidence["timebase"]
    assert timebase["header_sample_rate_hz"] == pytest.approx(2.048e12, rel=1e-6)
    assert timebase["conflict"] is True and timebase[
        "header_rate_over_record_rate"
    ] == pytest.approx(8.0)
    assert abs(timebase["measured_offset_ppm_vs_published_baud"]) < 50
    assert timebase["header_samples_per_symbol"] == pytest.approx(40.96)
    assert timebase["record_samples_per_symbol_nominal"] == pytest.approx(5.12)
    assert abs(evidence["dc_over_std"]) < 0.01
    assert report.holdout_status.startswith("NOT_ASSESSED_HOLDOUT")
    source = teriphic.load_config()
    b2b = next(a for a in source.assets if a.split is Split.CHARACTERISATION)
    assert b2b.parameters["sample_rate_hz"].provenance is Provenance.INFERRED  # kept as the record
    assert b2b.parameters["raw_format"].provenance is Provenance.UNKNOWN  # config not rewritten


@real_b2b
def test_real_b2b_is_opened_read_only_and_not_modified():
    before = B2B.stat()
    capture = teriphic.open_b2b()
    head = capture.raw_bytes(0, 164)
    assert head[:4] == b"AG10" and capture.checksum is not None
    assert capture.checksum.md5_state is Md5State.VERIFIED
    capture.close()
    after = B2B.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert isinstance(
        next(a for a in teriphic.load_config().assets if a.filename == B2B.name), AssetRecord
    )
