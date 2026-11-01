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
import os
import re
import struct
import tracemalloc
import warnings
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import welch

from opticps.benchmarks import teriphic
from opticps.benchmarks import timing as timing_module
from opticps.benchmarks.capture_stats import (
    PublishedReference,
    decision_clusters,
    describe_capture,
    describe_capture_with_timing,
    explore_eye,
    measured_ber,
    measured_ser,
    native_rate_reading,
    post_fec_ber,
)
from opticps.benchmarks.external_capture import (
    ExternalCapture,
    FormatCheck,
    FormatStatus,
    Hypothesis,
    RawSpec,
    SampleLayout,
    default_hypotheses,
    evaluate_hypotheses,
    parse_keysight_bin_header,
    unique_survivor,
    waveform_checks,
)
from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    Checksum,
    ErrorCode,
    Md5State,
    Provenance,
    Split,
    verify_local_asset,
)
from opticps.benchmarks.timing import (
    TimingError,
    TimingTracker,
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
    levels: tuple[float, ...] = (-3.0, -1.0, 1.0, 3.0),
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(samples, symbols, true symbol times in samples) of a PAM4 waveform with a drifting clock.

    Symbol k sits at s_k = 40 + k*sps*(1+drift) + wander*sps*sin(2 pi k / period). The waveform is
    the sum of pulses evaluated at the exact fractional sample times: no resampling is involved.
    """
    rng = np.random.default_rng(seed)
    symbols = rng.choice(list(levels), size=n_symbols)
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
    x_range: float | None = None,
    x_origin: float = 0.0,
    frame: bytes = b"SYNTH:SN0",
) -> bytes:
    """A Keysight-BIN-like file written field by field (independent of the reader's packing)."""
    e = byte_order
    data = np.asarray(samples, dtype=e + "f4").tobytes()
    n = len(samples)
    wave = b"".join(
        [
            struct.pack(e + "i", 140), struct.pack(e + "i", 1), struct.pack(e + "i", 1),
            struct.pack(e + "i", n + points_delta), struct.pack(e + "i", 1),
            struct.pack(e + "f", n * xinc if x_range is None else x_range), struct.pack(e + "d", 0.0),
            struct.pack(e + "d", xinc), struct.pack(e + "d", x_origin),
            struct.pack(e + "i", x_units), struct.pack(e + "i", y_units),
            b"01 JAN 2026".ljust(16, b"\x00"), b"12:00:00".ljust(16, b"\x00"),
            frame.ljust(24, b"\x00"), b"Channel 1".ljust(16, b"\x00"),
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
    assert "physical pass: yes" in capsys.readouterr().out
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


# ----------------------------------------------------------------------------- fix round (E1 review)
STORED_XINC = 1.0 / 2.048e12  # the stored-stream time increment of the B2B file
HOLDOUT_2KM = "50G_PAM4_PD1_2km_Subassembly1.bin"
HOLDOUT_10KM = "50G_PAM4_PD1_10km_Subassembly1.bin"


def upsample8(native: np.ndarray) -> np.ndarray:
    """Endpoint-preserving 8x windowed-sinc interpolation: samples at multiples of 8 are kept."""
    taps = 8 * 16
    k = np.arange(-taps, taps + 1)
    h = np.sinc(k / 8.0) * np.hanning(2 * taps + 3)[1:-1]
    stuffed = np.zeros(8 * (native.size - 1) + 1)
    stuffed[::8] = native
    return np.convolve(stuffed, h, mode="same")


def held_pam4(
    n_symbols: int,
    sps: float,
    *,
    seed: int = 11,
    drift: float = 0.0,
    levels: tuple[float, ...] = (-3.0, -1.0, 1.0, 3.0),
    noise: float = 0.03,
    edge: float = 0.12,
) -> np.ndarray:
    """Levels held for one symbol each, edges smoothed by a Gaussian of `edge` symbols, plus noise.

    A heavily oversampled waveform of this kind shows separated amplitude humps (unlike a
    raised-cosine train sampled at 40 points per symbol), as an oscilloscope trace does.
    """
    rng = np.random.default_rng(seed)
    symbols = rng.choice(list(levels), size=n_symbols)
    n = np.arange(int(n_symbols * sps * (1.0 + drift)))
    index = np.minimum((n / (sps * (1.0 + drift))).astype(int), n_symbols - 1)
    sigma = edge * sps
    half = int(4 * sigma) + 1
    kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    x = np.convolve(symbols[index], kernel / kernel.sum(), mode="same")
    return x + rng.normal(0.0, noise, size=x.size)


@pytest.fixture(scope="module")
def stored_signal() -> np.ndarray:
    """PAM4 at 40.96 samples per symbol (header rate 2.048 THz), analytic, not interpolated."""
    return held_pam4(3000, 40.96)


@pytest.fixture(scope="module")
def interpolated_signal() -> np.ndarray:
    """A native 256 GSa/s PAM4 waveform stored after our own 8x interpolation (2.048 THz axis)."""
    return upsample8(held_pam4(20000, 5.12, seed=12, edge=0.15))


def write_fixture(tmp_path: Path, samples: np.ndarray, name: str = "fx.bin", **kwargs) -> Path:
    path = tmp_path / name
    path.write_bytes(keysight_image(samples, xinc=kwargs.pop("xinc", STORED_XINC), **kwargs))
    return path


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def source_with_b2b_md5(md5: str):
    source = teriphic.load_config()
    assets = []
    for asset in source.assets:
        if asset.split is Split.CHARACTERISATION:
            asset = dataclasses.replace(asset, checksum=Checksum(md5_supplied=md5))
        assets.append(asset)
    return dataclasses.replace(source, assets=tuple(assets))


def forbid_sample_readers(monkeypatch) -> list[str]:
    """Make any mapping or constructor call of a reader fail the test; hashing stays possible."""
    called: list[str] = []

    def refuse(*args, **kwargs):
        called.append("reader")
        raise AssertionError("a sample reader was called before the gate refused")

    monkeypatch.setattr(np, "memmap", refuse)
    monkeypatch.setattr(ExternalCapture, "open_keysight_bin", classmethod(refuse))
    monkeypatch.setattr(ExternalCapture, "open_raw", classmethod(refuse))
    return called


# --- finding 1: one gate for every route, any file name or place
def test_cli_gate_catches_a_renamed_holdout_on_every_route(tmp_path, signal, monkeypatch, capsys):
    innocent = tmp_path / "innocent.bin"
    innocent.write_bytes(keysight_image(signal[0][:8192]))
    injected = source_with_holdout_md5(md5_of(innocent))
    monkeypatch.setattr(teriphic, "load_config", lambda *a, **k: injected)
    sidecar = tmp_path / "side.json"
    sidecar.write_text(json.dumps({"dtype": "<f4"}))
    called = forbid_sample_readers(monkeypatch)
    for extra in ([], ["--metadata", str(sidecar)]):
        assert cli_main(["benchmark", "inspect-format", "--file", str(innocent), *extra]) == 1
        error = capsys.readouterr().err
        assert "LEAKAGE_DETECTED" in error and "MD5" in error and HOLDOUT_10KM in error
    assert called == []


def test_gate_catches_a_holdout_by_sha256_and_by_symlink(tmp_path, signal):
    path = tmp_path / "innocent.bin"
    path.write_bytes(keysight_image(signal[0][:8192]))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED") as caught:
        teriphic.gate_sample_read(path, holdout_sha256={HOLDOUT_2KM: sha})
    assert "SHA-256" in str(caught.value) and HOLDOUT_2KM in str(caught.value)
    assert teriphic.gate_sample_read(path, holdout_sha256={HOLDOUT_2KM: "0" * 64}).asset is None
    target = tmp_path / HOLDOUT_2KM
    target.write_bytes(b"x")
    link = tmp_path / "harmless_name.bin"
    link.symlink_to(target)
    with bad(ErrorCode.LEAKAGE_DETECTED):
        teriphic.gate_sample_read(link)
    assert cli_main(["benchmark", "inspect-format", "--file", str(link)]) == 1


def test_gate_hashes_every_file_and_knows_the_b2b_by_hash(tmp_path, signal):
    path = tmp_path / "any_name.bin"
    path.write_bytes(keysight_image(signal[0][:8192]))
    gate = teriphic.gate_sample_read(path)
    assert gate.checksum.md5_local == md5_of(path) and gate.checksum.sha256_local
    assert gate.is_b2b is False and gate.asset is None
    twin = teriphic.gate_sample_read(path, source_with_b2b_md5(md5_of(path)))
    assert twin.is_b2b is True


def test_recorded_holdout_sha256_table_equals_the_register():
    register = " ".join(Path("docs/benchmarks/SOURCE_REGISTER.md").read_text().split())
    assert set(teriphic.HOLDOUT_SHA256) == {HOLDOUT_2KM, HOLDOUT_10KM}
    for name, sha in teriphic.HOLDOUT_SHA256.items():
        assert re.search(rf"`{re.escape(name)}`.*?`{sha}`", register), name


# --- finding 2: a valid header never earns "accepted"; structure and physical are separate
def test_cli_refuses_noise_scaled_noise_and_nan_blocks_behind_a_valid_header(
    tmp_path, signal, capsys
):
    rng = np.random.default_rng(21)
    noise = rng.normal(size=30000)
    nan_block = signal[0].copy()
    nan_block[12000:12100] = np.nan
    cases = {
        "white_noise": noise,
        "noise_times_1e30": noise * 1e30,
        "nan_block": nan_block,
        "smooth_but_absurd_scale": signal[0] * 1e30,
    }
    for tag, samples in cases.items():
        path = tmp_path / f"{tag}.bin"
        path.write_bytes(keysight_image(samples, xinc=1.0 / 256e9))
        assert cli_main(["benchmark", "inspect-format", "--file", str(path)]) == 1, tag
        captured = capsys.readouterr()
        assert "structure pass: yes" in captured.out, tag
        assert "physical pass: NO" in captured.out, tag
        assert "accepted" not in captured.out and "FORMAT_UNKNOWN" in captured.err, tag


def test_cli_good_fixture_reports_two_passes_not_acceptance(fixture_bin, capsys):
    assert cli_main(["benchmark", "inspect-format", "--file", str(fixture_bin)]) == 0
    out = capsys.readouterr().out
    assert "structure pass: yes" in out and "physical pass: yes" in out
    assert "not a format verdict" in out and "accepted" not in out


def test_full_scan_finds_a_nan_block_that_the_slices_miss(tmp_path, signal):
    x = signal[0][:40000].copy()
    x[8000:8100] = np.nan  # between the start slice and the middle slice
    path = tmp_path / "gap.bin"
    path.write_bytes(keysight_image(x, xinc=1.0 / 256e9))
    gate = teriphic.gate_sample_read(path)
    capture = ExternalCapture.open_keysight_bin(path)
    assert all(c.passed for c in capture.physical_checks(3 * 4096))  # slices alone: all pass
    capture.close()
    result = teriphic.inspect_capture(path, gate, max_samples=3 * 4096)
    assert result.structure_pass is True and result.physical_pass is False
    failed = {c.name: c.detail for c in result.physical_detail if not c.passed}
    assert set(failed) == {"finite_everywhere"} and "100 non-finite" in failed["finite_everywhere"]
    assert "index 8000" in failed["finite_everywhere"]


def test_plausible_scale_is_a_named_check_with_both_limits():
    t = np.arange(20000)
    base = np.sin(t / 40.0) + 0.5 * np.sin(t / 97.0)
    for factor, expected in ((1.0, True), (1e30, False), (1e-30, False)):
        checks = {c.name: c for c in waveform_checks(base * factor)}
        assert checks["plausible_scale"].passed is expected, factor


# --- finding 3b: the negative path of verify_b2b_format, one test per guard
def verify(path: Path):
    return teriphic.verify_b2b_format(path)


def test_verify_supports_a_clean_stored_stream_fixture(tmp_path, stored_signal):
    report = verify(write_fixture(tmp_path, stored_signal))
    assert report.status is FormatStatus.SUPPORTED_BY_EVIDENCE, report.summary
    assert report.reasons_unknown == () and report.blocked_label == ""
    assert report.summary.startswith("SUPPORTED_BY_EVIDENCE (B2B only): Keysight BIN v10")
    assert report.evidence["level_structure"]["four_levels"] is True


def test_verify_is_unknown_when_levels_are_not_four(tmp_path):
    pam2 = held_pam4(3000, 40.96, levels=(-1.0, 1.0))
    report = verify(write_fixture(tmp_path, pam2))
    assert report.status is FormatStatus.FORMAT_UNKNOWN
    assert report.reasons_unknown == ("amplitude histogram does not show four separated levels",)
    assert report.blocked_label == "BLOCKED: FORMAT_UNVERIFIED"
    assert report.summary.startswith("FORMAT_UNKNOWN (BLOCKED: FORMAT_UNVERIFIED)")


def test_verify_is_unknown_when_the_tone_is_off_by_more_than_the_tolerance(tmp_path):
    drifted = held_pam4(3000, 40.96, drift=0.0013)  # symbol rate 1300 ppm low
    report = verify(write_fixture(tmp_path, drifted))
    assert report.status is FormatStatus.FORMAT_UNKNOWN
    assert len(report.reasons_unknown) == 1
    assert report.reasons_unknown[0].startswith("no symbol tone at the published baud")
    assert abs(report.evidence["timebase"]["measured_offset_ppm_vs_published_baud"]) > 1000


def test_verify_is_unknown_when_the_tone_is_too_weak(tmp_path, stored_signal, monkeypatch):
    path = write_fixture(tmp_path, stored_signal)
    strength = verify(path).evidence["timebase"]["tone_strength_median"]
    assert 0.02 < strength < 0.9  # a real tone; only the threshold changes below
    monkeypatch.setattr(teriphic, "TONE_MIN_STRENGTH", 0.9)
    report = verify(path)
    assert report.status is FormatStatus.FORMAT_UNKNOWN
    assert len(report.reasons_unknown) == 1 and "strength" in report.reasons_unknown[0]


def test_verify_is_unknown_when_the_survivor_is_not_the_declared_layout(
    tmp_path, stored_signal, monkeypatch
):
    path = write_fixture(tmp_path, stored_signal)
    monkeypatch.setattr(teriphic, "unique_survivor", lambda results: Hypothesis("<f4", 168))
    report = verify(path)
    assert report.status is FormatStatus.FORMAT_UNKNOWN
    assert report.reasons_unknown == ("survivor <f4@168 is not the structurally declared layout",)


def test_verify_is_unknown_when_no_or_several_hypotheses_survive(
    tmp_path, stored_signal, monkeypatch
):
    noise = np.random.default_rng(4).normal(size=60000)
    report = verify(write_fixture(tmp_path, noise, "noise.bin"))
    assert report.status is FormatStatus.FORMAT_UNKNOWN and report.reasons_unknown
    path = write_fixture(tmp_path, stored_signal)
    real = teriphic.evaluate_hypotheses

    def all_pass(*args, **kwargs):
        return tuple(
            dataclasses.replace(r, checks=(FormatCheck("physical_checks", True, "forced"),))
            for r in real(*args, **kwargs)
        )

    monkeypatch.setattr(teriphic, "evaluate_hypotheses", all_pass)
    ambiguous = verify(path)
    assert ambiguous.status is FormatStatus.FORMAT_UNKNOWN
    assert "ambiguous format" in ambiguous.reasons_unknown[0]


def test_verify_refuses_an_empty_band_instead_of_warning_or_returning_nan(tmp_path, signal):
    path = tmp_path / "rate256.bin"  # 256 GSa/s header: no bin near the record rate to inspect
    path.write_bytes(keysight_image(signal[0], xinc=1.0 / 256e9))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        report = verify(path)
    assert report.status is FormatStatus.FORMAT_UNKNOWN
    assert "holds no spectral bin" in report.summary
    assert report.evidence == {} and "2.048 THz" not in repr(report)


def test_band_db_refuses_empty_and_silent_bands():
    freq = np.linspace(0.0, 100.0, 11)
    psd = np.ones(11)
    assert teriphic._band_db(freq, psd, 0.0, 50.0) == pytest.approx(0.0)
    with bad():
        teriphic._band_db(freq, psd, 200.0, 300.0)
    with bad():
        teriphic._band_db(freq, np.zeros(11), 0.0, 50.0)
    with bad():
        teriphic._band_db(freq, np.where(freq < 50.0, 0.0, psd), 0.0, 50.0)


# --- finding 4: evidence text comes from the file
def test_rate_chain_and_size_reading_follow_the_file(tmp_path, stored_signal):
    report = verify(write_fixture(tmp_path, stored_signal))
    text = report.evidence["rate_chain_reading"]
    assert "2048 GHz" in text and "40.96 samples per symbol" in text and "confirms" in text
    other = verify(write_fixture(tmp_path, held_pam4(3000, 20.0, seed=5), xinc=1e-12))
    assert other.status is FormatStatus.SUPPORTED_BY_EVIDENCE, other.summary
    other_text = other.evidence["rate_chain_reading"]
    assert "1000 GHz" in other_text and "20 samples per symbol" in other_text
    assert "2048 GHz" not in other_text and "40.96" not in other_text
    size_text = other.layout["size_hypothesis_136_bytes"]
    assert f"{other.layout['samples']:,}" in size_text
    assert "40,959,993" not in repr(other)
    drifted = held_pam4(3000, 40.96, drift=0.0013)
    weak = verify(write_fixture(tmp_path, drifted, "d.bin"))
    assert "NO symbol tone confirms" in weak.evidence["rate_chain_reading"]


# --- finding 7: x origin is reported, an inconsistent display range is fatal
def test_x_origin_is_reported_and_display_range_must_agree(tmp_path, stored_signal):
    report = verify(write_fixture(tmp_path, stored_signal, x_origin=-1.1755e-5))
    assert report.layout["x_origin_s"] == -1.1755e-5
    path = write_fixture(tmp_path, stored_signal, "range.bin", x_range=1.0)
    with pytest.raises(BenchmarkError, match="display_range_matches_record"):
        ExternalCapture.open_keysight_bin(path)
    span = stored_signal.size * STORED_XINC
    near = write_fixture(tmp_path, stored_signal, "near.bin", x_range=span * 1.0005)
    assert ExternalCapture.open_keysight_bin(near).count == stored_signal.size
    zero = write_fixture(tmp_path, stored_signal, "zero.bin", x_range=0.0)
    with bad():
        ExternalCapture.open_keysight_bin(zero)


# --- finding 8: the 8x reading is reproduced by our own code
def test_native_rate_reading_finds_integer_upsampling_and_not_its_absence(
    interpolated_signal, stored_signal, tmp_path
):
    up = ExternalCapture.open_keysight_bin(write_fixture(tmp_path, interpolated_signal, "up.bin"))
    reading = native_rate_reading(up, 256e9)
    assert reading["status"] == "tested" and reading["integer_factor"] == 8
    counting = reading["counting"]
    assert counting["points_minus_one"] == 8 * (counting["native_points"] - 1)
    assert counting["native_span_s_at_record_rate"] == pytest.approx(
        counting["native_points"] / 256e9
    )
    profiles = reading["second_difference_period"]["profiles"]
    assert profiles["8"]["max_over_min"] > 1.05
    assert all(profiles[k]["max_over_min"] < 1.02 for k in ("7", "9"))
    assert profiles["8"]["argmin_residue"] != 0
    assert profiles["8"]["mirror_symmetry_max_relative_difference"] < 0.01
    assert "READING" in reading["label"] and "not a verified fact" in reading["label"]
    # control: edges at an incommensurate fractional spacing, so no period-8 beat by accident
    # (40.96 samples per symbol would repeat its edge phase every 25 symbols = 3 x 8 samples)
    plain = ExternalCapture.open_keysight_bin(
        write_fixture(tmp_path, held_pam4(20000, 41.1, seed=3), "plain.bin")
    )
    flat = native_rate_reading(plain, 256e9)["second_difference_period"]["profiles"]["8"]
    assert flat["max_over_min"] < 1.02  # no 8-periodic curvature without interpolation
    same = ExternalCapture.open_keysight_bin(
        write_fixture(tmp_path, stored_signal, "same.bin", xinc=1 / 256e9)
    )
    assert native_rate_reading(same, 256e9)["status"].startswith("not testable")
    for capture in (up, plain, same):
        capture.close()


def test_line_detector_finds_a_planted_line_at_the_record_rate_multiple(tmp_path, stored_signal):
    n = np.arange(stored_signal.size)
    planted = stored_signal + 0.8 * np.cos(2 * np.pi * n / 16.0 + 0.3)  # its square: line at fs/8
    with_line = ExternalCapture.open_keysight_bin(write_fixture(tmp_path, planted, "line.bin"))
    without = ExternalCapture.open_keysight_bin(write_fixture(tmp_path, stored_signal, "no.bin"))
    strong = native_rate_reading(with_line, 256e9)["lines_in_squared_signal"][0]
    weak = native_rate_reading(without, 256e9)["lines_in_squared_signal"][0]
    assert strong["multiple_k"] == 1 and abs(strong["offset_from_nominal_hz"]) < 1e6
    assert strong["measured_frequency_hz"] == pytest.approx(256e9, rel=1e-5)
    assert strong["line_over_median_db"] > 25.0 and weak["line_over_median_db"] < 15.0
    with_line.close()
    without.close()


def test_verify_carries_the_reading_labelled_and_computed(tmp_path, interpolated_signal):
    report = verify(write_fixture(tmp_path, interpolated_signal))
    assert report.status is FormatStatus.SUPPORTED_BY_EVIDENCE, report.summary
    assert report.evidence["native_rate_reading"]["integer_factor"] == 8
    text = report.evidence["rate_chain_reading"]
    assert "reading (not a fact)" in text and "8x integer upsampling" in text
    assert "The exporter must confirm it" in text


# --- finding 9: the frame string is a header claim about a model; no serial anywhere
def test_frame_string_is_recorded_as_a_model_claim_without_its_serial(tmp_path, stored_signal):
    path = write_fixture(tmp_path, stored_signal, frame=b"UXR0704AP" + b":" + b"ZZ00000000")
    report = verify(path)
    fields = report.layout["header_fields"]
    assert fields["frame_model_claim"] == "UXR0704AP"
    assert "frame" not in fields and "not instrument evidence" in fields["frame_model_claim_note"]
    blob = repr(report) + repr([c.detail for c in report.structural_checks])
    assert "ZZ00000000" not in blob and "UXR0704AP" in blob


def test_no_instrument_serial_in_committed_text():
    pattern = re.compile(r"UXR0704AP:[A-Z0-9]{4,}|MY\d{8}")
    for root in (Path("docs"), Path("src"), Path("tests"), Path("configs"), Path("reports")):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".yml", ".json", ".txt"}:
                assert not pattern.search(path.read_text(errors="ignore")), path


# --- finding 5: the generic readers are listed as known limits and the gate rule is stated
def test_known_limits_list_the_generic_readers_and_the_route_rule():
    limits = " ".join(Path("docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md").read_text().split())
    for needle in (
        "read_bin",
        "ExternalCapture.open_keysight_bin",
        "gate_sample_read",
        "MD5 and SHA-256",
    ):
        assert needle in limits, needle


# --- finding 6: guards that other checks used to shadow
def test_bounded_is_decided_by_its_own_check():
    t = np.arange(20000)
    base = np.sin(t / 40.0) + 0.5 * np.sin(t / 97.0)
    assert {c.name: c.passed for c in waveform_checks(base)}["bounded"] is True
    spiked = base.copy()
    spiked[10000] = 40.0 * float(base.std())
    results = {c.name: c for c in waveform_checks(spiked)}
    assert results["bounded"].passed is False and "limit 20" in results["bounded"].detail


def test_a_stale_checksum_is_refused_whatever_the_change(tmp_path, signal):
    path = tmp_path / "s.bin"
    path.write_bytes(keysight_image(signal[0][:8192]))
    checksum = verify_local_asset(path)
    assert checksum.still_current(path) is True
    assert checksum.still_current(tmp_path / "missing.bin") is False
    status = path.stat()
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 10**9))  # time only
    assert checksum.still_current(path) is False
    with pytest.raises(BenchmarkError, match="changed after it was hashed"):
        ExternalCapture.open_keysight_bin(path, checksum=checksum)
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))
    assert checksum.still_current(path) is True
    with path.open("ab") as handle:
        handle.write(b"\x00" * 4)  # size only
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))
    assert checksum.still_current(path) is False


def test_a_capture_opened_before_a_change_refuses_every_read(fixture_bin):
    capture = ExternalCapture.open_keysight_bin(fixture_bin)
    assert capture.read(0, 16).size == 16
    status = fixture_bin.stat()
    os.utime(fixture_bin, ns=(status.st_atime_ns, status.st_mtime_ns + 10**9))
    with pytest.raises(BenchmarkError, match="changed after it was hashed"):
        capture.read(0, 16)
    with pytest.raises(BenchmarkError, match="changed after it was hashed"):
        capture.assert_unchanged()
    with pytest.raises(BenchmarkError, match="changed after it was hashed"):
        next(capture.blocks(4096))
    capture.close()


# --- finding 10: the window is a whole number of samples, not of symbols
def test_window_samples_is_rounded_and_documented_as_such():
    tracker = TimingTracker(40.96)
    assert tracker.window_samples == 10486 and tracker.window_samples != 256 * 40.96
    doc = " ".join((TimingTracker.window_samples.__doc__ or "").split())
    assert "nearest whole sample" in doc and "not a whole number of symbols" in doc
    assert "windows of whole symbols" not in " ".join((timing_module.__doc__ or "").split())


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
    assert report.layout["x_origin_s"] == pytest.approx(-1.1755e-5, rel=1e-6)  # reported
    assert report.layout["header_fields"]["frame_model_claim"] == "UXR0704AP"
    assert not re.search(r"MY\d{8}", repr(report))  # no serial leaves the file
    native = evidence["native_rate_reading"]  # the labelled reading, reproduced by our own code
    assert native["integer_factor"] == 8 and "READING" in native["label"]
    assert native["counting"]["points_minus_one"] == 8 * 5_119_999
    assert native["counting"]["native_points"] == 5_120_000
    assert native["counting"]["native_span_s_at_record_rate"] == pytest.approx(20e-6, rel=1e-12)
    for row, multiple in zip(native["lines_in_squared_signal"], (256e9, 512e9), strict=True):
        assert row["measured_frequency_hz"] == pytest.approx(multiple, abs=2e5)
        assert row["line_over_median_db"] > 20.0
    profiles = native["second_difference_period"]["profiles"]
    assert profiles["8"]["max_over_min"] > 1.1 and profiles["8"]["argmin_residue"] == 4
    assert profiles["8"]["mirror_symmetry_max_relative_difference"] < 1e-3
    assert profiles["7"]["max_over_min"] < 1.001 and profiles["9"]["max_over_min"] < 1.001
    text = evidence["rate_chain_reading"]
    assert "40.96 samples per symbol" in text and "confirms that time axis" in text
    assert "40,959,992 = 8 x 5,119,999" in text and "reading (not a fact)" in text
    assert "7 samples" in report.layout["size_hypothesis_136_bytes"]
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
