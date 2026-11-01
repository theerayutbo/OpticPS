"""TERIPHIC PD1 PAM4 adapter (Stage 3A, gate E1): B2B only, offline, read-only.

Roles (plan `docs/benchmarks/FIT_HOLDOUT_PLAN.md`, R.3 and R5.2): only the characterisation file,
`50G_PAM4_PD1_B2B_Subassembly1.bin`, may have a sample byte read. The 2 km and 10 km files may be
hashed (`verify_local_asset`) and nothing else. `gate_sample_read` is the one gate that every
sample-reading route of this module and of `opticps benchmark inspect-format` passes, for any
`--file` wherever it lives: registered name of the resolved path (symbolic links followed), any file
under `data/external/` that is not the B2B file, then the MD5 and SHA-256 of the whole file against
the recorded holdout hashes. The file is hashed (bytes pass through a digest, no sample value is
decoded) before any header or sample byte is returned, so a renamed or copied holdout is caught
whatever its name. Not covered, and listed in `docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md`:
`ExternalCapture.open_*` and `uxr_import.read_bin` called directly, which are generic readers.

The verdict of `verify_b2b_format` is evidence-based and only about B2B. It never says
anything about the other two files: the accepted hypothesis is applied to them unchanged
only after the plan's freeze, and until then their format is `NOT_ASSESSED_HOLDOUT`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from opticps.benchmarks.capture_stats import (
    describe_capture_with_timing,
    explore_eye,
    native_rate_reading,
)
from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.external_capture import (
    COVERAGE_BLOCK_SAMPLES,
    CoverageReport,
    ExternalCapture,
    FormatCheck,
    FormatStatus,
    RawSpec,
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
    SourceRecord,
    Split,
    verify_local_asset,
)

CONFIG_PATH = Path("configs/benchmarks/teriphic_pd1_pam4.yaml")
DEFAULT_ROOT = Path("data/external/teriphic")
B2B_FILENAME = "50G_PAM4_PD1_B2B_Subassembly1.bin"
BAUD_BD = 50e9  # PUBLISHED_MEASUREMENT (record text and file name)
RECORD_SAMPLE_RATE_HZ = 256e9  # INFERRED: the record prints "256 Gbaud sample rate"
TONE_TOLERANCE_PPM = 1000.0
TONE_MIN_STRENGTH = 0.02
SPUR_BAND_HZ = 40e9  # half width of the band inspected round the record sample rate
HOLDOUT_STATUS = (
    "NOT_ASSESSED_HOLDOUT: hash only; no header, size-based decode or statistic (plan R.3, R5.2)"
)


def load_config(path: Path = CONFIG_PATH) -> SourceRecord:
    return load_source_config(path)


def _in_external(path: Path) -> bool:
    """True when the resolved path has `data/external` as consecutive components."""
    parts = [fold_name(part) for part in path.resolve().parts]
    return any(parts[i : i + 2] == ["data", "external"] for i in range(len(parts) - 1))


def fold_name(name: str) -> str:
    """Case-folded, canonically decomposed: names equal on a case- and normalisation-blind disk."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def guard_sample_read(path: Path, source: SourceRecord | None = None) -> AssetRecord | None:
    """Refuse any path that is, or may be, a holdout or unregistered capture. Reads no byte.

    Returns the B2B asset record when `path` is the B2B file, `None` for a path that is neither
    registered nor under `data/external/` (a fixture), and raises LEAKAGE_DETECTED otherwise.
    """
    source = source or load_config()
    name = Path(path).resolve().name
    by_name = {fold_name(a.filename): a for a in source.assets}
    asset = by_name.get(fold_name(name))
    if asset is not None and asset.split is not Split.CHARACTERISATION:
        raise BenchmarkError(
            f"{name} is a {asset.split.value} file: only hash-only checks are allowed before the "
            "plan's freeze (plan R.3, R5.2); no sample byte is read",
            ErrorCode.LEAKAGE_DETECTED,
        )
    if asset is None and _in_external(Path(path)):
        raise BenchmarkError(
            f"{name} is under data/external/ but is not a registered characterisation file",
            ErrorCode.LEAKAGE_DETECTED,
        )
    return asset


# SHA-256 of the two holdout files as recorded in SOURCE_REGISTER.md ("Local hashes", E1a, equal to
# the orchestrator's values); a test compares this table with the register text.
HOLDOUT_SHA256 = {
    "50G_PAM4_PD1_2km_Subassembly1.bin": (
        "22fc7bb592681ed6135b5be28a28b1f124344924316b4333508823f7674266d3"
    ),
    "50G_PAM4_PD1_10km_Subassembly1.bin": (
        "053bf8c9ba8df00063f5d686508833dc18685ec320d7e373b1877947e15b118b"
    ),
}


@dataclass(frozen=True)
class SampleGate:
    """What `gate_sample_read` learned about a file it let through."""

    asset: AssetRecord | None  # the B2B record when the registered name is the B2B file
    checksum: Checksum  # hashed locally; reused by the reader so the file is hashed once
    is_b2b: bool  # the bytes hash to the recorded B2B MD5, whatever the file is called


def _refuse_holdout_hash(
    checksum: Checksum,
    source: SourceRecord,
    name: str,
    holdout_sha256: Mapping[str, str],
) -> None:
    """After the hash-only step: a file whose MD5 or SHA-256 is a holdout's is that holdout."""
    for asset in source.assets:
        if asset.split is Split.CHARACTERISATION:
            continue
        md5_hit = (
            checksum.md5_local is not None and asset.checksum.md5_supplied == checksum.md5_local
        )
        sha = holdout_sha256.get(asset.filename)
        sha_hit = sha is not None and checksum.sha256_local == sha
        if md5_hit or sha_hit:
            which = "MD5" if md5_hit else "SHA-256"
            raise BenchmarkError(
                f"{name} has the {which} of {asset.filename} ({asset.split.value}); refusing, "
                "no sample read",
                ErrorCode.LEAKAGE_DETECTED,
            )


def gate_sample_read(
    path: Path,
    source: SourceRecord | None = None,
    *,
    holdout_sha256: Mapping[str, str] | None = None,
) -> SampleGate:
    """The single gate before any sample byte of any file is returned (plan R.3, R5.2).

    Checks, in order: the registered name of the resolved path (a symbolic link to a holdout is
    refused by the name of its target), any file under `data/external/` other than the B2B file,
    then the whole file's MD5 and SHA-256 (hashed here, streaming, no sample decoded) against the
    recorded hashes of every non-characterisation asset. Raises LEAKAGE_DETECTED on any hit. Returns
    the checksum so a reader does not hash again. `holdout_sha256` defaults to `HOLDOUT_SHA256`
    (injectable for tests, which must never touch a real holdout).
    """
    source = source or load_config()
    path = Path(path)
    asset = guard_sample_read(path, source)
    checksum = verify_local_asset(path, asset.checksum.md5_supplied if asset else None)
    _refuse_holdout_hash(
        checksum, source, path.name, HOLDOUT_SHA256 if holdout_sha256 is None else holdout_sha256
    )
    b2b = next(a for a in source.assets if a.split is Split.CHARACTERISATION)
    is_b2b = (
        checksum.md5_local is not None
        and b2b.checksum.md5_supplied is not None
        and checksum.md5_local == b2b.checksum.md5_supplied
    )
    return SampleGate(asset, checksum, is_b2b)


def load_register_for_gate() -> SourceRecord | None:
    """The source register from the working directory, else from the source tree; None if absent."""
    for candidate in (CONFIG_PATH, Path(__file__).resolve().parents[3] / CONFIG_PATH):
        if candidate.is_file():
            return load_config(candidate)
    return None


def gate_without_register(path: Path) -> None:
    """The holdout check that needs no register file. Raises LEAKAGE_DETECTED.

    Registered holdout names, `data/external` (other than the B2B file name) and the recorded
    SHA-256 of every holdout. Used by the CLI only when the register YAML cannot be found.
    """
    path = Path(path)
    name = path.resolve().name
    holdout_names = {fold_name(n): n for n in HOLDOUT_SHA256}
    if fold_name(name) in holdout_names or (
        _in_external(path) and fold_name(name) != fold_name(B2B_FILENAME)
    ):
        raise BenchmarkError(
            f"{name} is a holdout or an unregistered file under data/external/; no sample read",
            ErrorCode.LEAKAGE_DETECTED,
        )
    checksum = verify_local_asset(path, None)
    for holdout, sha in HOLDOUT_SHA256.items():
        if checksum.sha256_local == sha:
            raise BenchmarkError(
                f"{name} has the SHA-256 of {holdout}; refusing, no sample read",
                ErrorCode.LEAKAGE_DETECTED,
            )


def open_b2b(
    path: Path | None = None,
    *,
    source: SourceRecord | None = None,
    gate: SampleGate | None = None,
) -> ExternalCapture:
    """Open the B2B capture read-only after the gate and the structure checks."""
    source = source or load_config()
    path = Path(path) if path is not None else DEFAULT_ROOT / B2B_FILENAME
    gate = gate or gate_sample_read(path, source)
    return ExternalCapture.open_keysight_bin(path, checksum=gate.checksum)


@dataclass(frozen=True)
class CaptureInspection:
    """Structure pass and physical pass of a capture that is not the B2B file, kept apart.

    A well-formed header is a structure pass and nothing more: `accepted` needs both.
    """

    count: int
    scale: str
    layout: str
    structure_pass: bool
    structure_detail: tuple[FormatCheck, ...]
    physical_pass: bool
    physical_detail: tuple[FormatCheck, ...]
    coverage: CoverageReport | None = None  # the whole-record block pass behind physical_pass

    @property
    def accepted(self) -> bool:
        return self.structure_pass and self.physical_pass


def inspect_capture(
    path: Path,
    gate: SampleGate,
    spec: RawSpec | None = None,
    *,
    block_samples: int = COVERAGE_BLOCK_SAMPLES,
) -> CaptureInspection:
    """Structure and physical checks of one gated file (fixtures, other captures).

    Structure: the Keysight header against the file size (or the raw layout against the size).
    Physical: the whole-record block pass (`ExternalCapture.coverage_scan`): every block of the
    record passes the same checks, coverage is computed. Neither pass implies
    anything about the transmitted signal, a calibration or a format verdict. A structure failure
    raises FORMAT_UNKNOWN; a physical failure is reported, not raised.
    """
    if spec is None:
        capture = ExternalCapture.open_keysight_bin(path, checksum=gate.checksum)
        layout = f"{capture.layout.dtype}@{capture.layout.data_offset} (Keysight BIN header)"
    else:
        capture = ExternalCapture.open_raw(path, spec, checksum=gate.checksum, verify=False)
        layout = f"{spec.dtype}@{spec.data_offset} (sidecar)"
    try:
        structure = (FormatCheck("structure", True, "layout consistent with the file size"),)
        coverage = capture.coverage_scan(block_samples)
        return CaptureInspection(
            capture.count,
            capture.scale,
            layout,
            True,
            structure,
            coverage.passed,
            coverage.checks,
            coverage,
        )
    finally:
        capture.close()


def _band_db(freq: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    """Mean density in [low, high) over the peak, in dB; an empty or silent band is refused."""
    selected = (freq >= low) & (freq < high)
    if not selected.any():
        raise BenchmarkError(
            f"the band [{low:g}, {high:g}) Hz holds no spectral bin (sample rate or resolution)",
            ErrorCode.FORMAT_UNKNOWN,
        )
    level, peak = float(psd[selected].mean()), float(psd.max())
    if not (level > 0 and peak > 0 and np.isfinite(level) and np.isfinite(peak)):
        raise BenchmarkError(
            f"the band [{low:g}, {high:g}) Hz has no measurable power", ErrorCode.FORMAT_UNKNOWN
        )
    return float(10.0 * np.log10(level / peak))


@dataclass(frozen=True)
class FormatReport:
    """Result of the B2B format verification, with every piece of evidence."""

    status: FormatStatus
    summary: str
    layout: dict[str, Any]
    structural_checks: tuple[FormatCheck, ...]
    hypotheses: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    reasons_unknown: tuple[str, ...]
    exporter_must_tell: tuple[str, ...]
    holdout_status: str = HOLDOUT_STATUS
    notes: tuple[str, ...] = field(default=())

    @property
    def blocked_label(self) -> str:
        return (
            ""
            if self.status is FormatStatus.SUPPORTED_BY_EVIDENCE
            else "BLOCKED: FORMAT_UNVERIFIED"
        )


EXPORTER_QUESTIONS = (
    "vertical calibration: the header says Volt, but the input attenuation or probe, coupling "
    "(AC or DC), vertical gain and any normalisation applied at export are not stated, so the "
    "samples stay `normalized` (no volts, no optical power)",
    "sample-rate chain: compare the time increment in the file header (reported in this run) with "
    "the record's 256 (Gbaud sic); if the stored stream is faster, was the record captured at "
    "256 GSa/s and interpolated at export, and with what filter",
    "oscilloscope model and settings behind the frame string, bandwidth limit, ENOB, any digital "
    "filter applied before export (the EML record mentions a 50 GHz low-pass; this record "
    "is silent)",
    "transmitted sequence (PRBS order, pattern length, any repetition): none is documented",
    "laser wavelength, launch power, modulator bias and swing, photodiode bias and any amplifier",
)


def _unknown_report(error: BenchmarkError | str) -> FormatReport:
    return FormatReport(
        FormatStatus.FORMAT_UNKNOWN,
        f"FORMAT_UNKNOWN: {error}",
        {},
        (),
        (),
        {},
        (str(error),),
        EXPORTER_QUESTIONS,
    )


def _size_hypothesis_136(layout: Any, file_size: int) -> str:
    """The 136-byte-prefix reading, computed from this file's size and declared point count."""
    rest = file_size - 136
    if rest < 0 or rest % 4:
        return (
            f"136-byte prefix: arithmetically impossible, {rest} bytes after it are not a whole "
            "number of 4-byte samples"
        )
    points_136 = rest // 4
    start = layout.data_offset
    return (
        f"136-byte prefix + {points_136:,} four-byte samples would fill the file, but the header "
        f"declares {layout.count:,} points after a {start}-byte header ({4} x {layout.count:,} + "
        f"{start} = {4 * layout.count + start:,}; file size {file_size:,}): "
        + (
            "rejected by structure (statistics cannot separate the two: "
            f"{(start - 136) // 4} samples)"
            if 4 * layout.count + start == file_size
            else "the declared structure does not fill the file either"
        )
    )


UPSAMPLE_PERIOD_MIN = 1.02  # period-8 max/min: B2B 1.118, 8x fixture 1.066, no-upsampling <1.01
UPSAMPLE_CONTROL_MULTIPLE = 3.0  # (period ratio - 1) over the larger control's; B2B: about 590


def upsampling_criterion(native: dict[str, Any]) -> tuple[bool, str]:
    """Pass criterion of the integer-upsampling reading, and the numbers behind the answer.

    Passes only if the factor-period curvature profile has a max/min of at least
    UPSAMPLE_PERIOD_MIN and exceeds both controls (periods F-1 and F+1) by UPSAMPLE_CONTROL_MULTIPLE
    times in excess over 1. The lines in the squared signal are reported, not required: a fixture
    without upsampling shows a line of 11 dB over the median bin, so a line does not separate the
    cases. The curvature period does: B2B 1.118 against controls of 1.0002 and 1.0001; a fixture
    upsampled eight-fold by windowed-sinc interpolation 1.066; a fixture without upsampling 1.003
    against controls of 1.006.
    """
    if native.get("status") != "tested":
        return False, str(native.get("status", "not run"))
    period = native["second_difference_period"]
    profiles = period["profiles"]
    ratio = profiles[str(period["factor_period"])]["max_over_min"]
    controls = [profiles[str(c)]["max_over_min"] for c in period["control_periods"]]
    detail = (
        f"period {period['factor_period']} max/min {ratio:.4g} (needs {UPSAMPLE_PERIOD_MIN:g} and "
        f"{UPSAMPLE_CONTROL_MULTIPLE:g} times the excess of the controls {controls[0]:.4g} and "
        f"{controls[1]:.4g} over 1)"
    )
    excess = (ratio - 1.0) >= UPSAMPLE_CONTROL_MULTIPLE * (max(controls) - 1.0)
    return ratio >= UPSAMPLE_PERIOD_MIN and excess, detail


def _rate_chain_reading(
    layout: Any, timebase: dict[str, Any], native: dict[str, Any], tone_confirmed: bool
) -> str:
    """Words for the rate chain, built from this file's measured numbers only."""
    header_rate = timebase.get("header_sample_rate_hz")
    if header_rate is None:
        return "no time increment in the file: no rate chain can be stated"
    parts = [
        f"stored stream: header time increment {layout.x_increment_s:.10g} s "
        f"({header_rate / 1e9:.6g} GHz), {timebase['header_samples_per_symbol']:.6g} samples "
        f"per symbol at {BAUD_BD / 1e9:g} GBd"
    ]
    if tone_confirmed:
        parts.append(
            f"a symbol tone at {timebase['measured_symbol_rate_hz'] / 1e9:.6f} GHz "
            f"({timebase['measured_offset_ppm_vs_published_baud']:+.1f} ppm from the published "
            "baud) confirms that time axis"
        )
    else:
        parts.append("NO symbol tone confirms that time axis at the published baud")
    ratio = timebase.get("header_rate_over_record_rate")
    nominal = timebase.get("record_samples_per_symbol_nominal")
    if ratio is not None and abs(ratio - 1.0) > 1e-3:
        parts.append(
            f"the record's inferred {RECORD_SAMPLE_RATE_HZ / 1e9:g} GSa/s gives {nominal:.6g} "
            f"samples per symbol and is {ratio:.6g} times slower than the stored stream: it is not "
            "the rate of the stored stream"
        )
    elif ratio is not None:
        parts.append("the record's inferred rate agrees with the stored stream")
    seen, why = upsampling_criterion(native)
    if native.get("status") == "tested" and not seen:
        parts.append(f"no upsampling reading: the tests do not show it ({why})")
    elif native.get("status") == "tested":
        counting = native["counting"]
        lines = native["lines_in_squared_signal"]
        period = native["second_difference_period"]
        factor = native["integer_factor"]
        profile = period["profiles"][str(factor)]
        controls = [period["profiles"][str(c)]["max_over_min"] for c in period["control_periods"]]
        parts.append(
            f"reading (not a fact): {factor}x integer upsampling of a native stream at the "
            "record's rate, seen as "
            + (
                f"{counting['points_minus_one']:,} = {factor} x "
                f"{counting['points_minus_one_over_factor']:,} steps, "
                f"{counting['native_points']:,} native points in "
                f"{counting['native_span_s_at_record_rate'] * 1e6:.6g} us at the record rate; "
                if counting["points_minus_one_divisible_by_factor"]
                else "a point count that does not fit an endpoint-preserving stretch; "
            )
            + (
                "lines in the squared signal at "
                + ", ".join(
                    f"{row['measured_frequency_hz'] / 1e9:.3f} GHz "
                    f"(+{row['line_over_median_db']:.0f} dB over the median bin)"
                    for row in lines
                )
                + "; "
                if lines
                else "no line testable; "
            )
            + f"squared second difference with period {factor} (max/min "
            f"{profile['max_over_min']:.4g}, controls {controls[0]:.4g} and {controls[1]:.4g}). "
            "The exporter must confirm it"
        )
    else:
        parts.append(f"no integer upsampling test: {native.get('status', 'not run')}")
    return "; ".join(parts) + "."


def verify_b2b_format(
    path: Path | None = None,
    *,
    source: SourceRecord | None = None,
    gate: SampleGate | None = None,
) -> FormatReport:
    """Verify the B2B file's format by independent evidence, or leave it FORMAT_UNKNOWN.

    The evidence, all computed here from B2B bytes only: the documented Keysight BIN structure
    against the real file size (every redundant field must agree); the same bytes decoded under 84
    dtype/endianness/offset hypotheses with physical checks (one survivor required); a four-hump
    amplitude structure; a symbol-rate tone in the squared waveform at the published baud under
    the header time increment; and, as a labelled reading, a test for integer upsampling of the
    record's rate. A hypothesis with the 136-byte offset the file size suggests is reported with
    the others; statistics cannot separate it from the structural 164-byte offset (seven samples),
    so structure decides. The path passes `gate_sample_read` first.
    """
    source = source or load_config()
    path = Path(path) if path is not None else DEFAULT_ROOT / B2B_FILENAME
    capture = open_b2b(path, source=source, gate=gate)
    reasons: list[str] = []
    try:
        with path.open("rb") as handle:
            head = handle.read(164)
        layout, structural = parse_keysight_bin_header(head, path.stat().st_size)
        results = evaluate_hypotheses(path, default_hypotheses(layout), declared=layout)
        hypothesis_rows = tuple(
            {
                "hypothesis": r.hypothesis.name,
                "passed_all": r.passed,
                "failed_checks": sorted(set(r.failed_names)),
            }
            for r in results
        )
        try:
            survivor = unique_survivor(results)
            if (survivor.dtype, survivor.data_offset) != (layout.dtype, layout.data_offset):
                reasons.append(f"survivor {survivor.name} is not the structurally declared layout")
        except BenchmarkError as error:
            reasons.append(str(error))
        stats, _ = describe_capture_with_timing(
            capture, baud_bd=BAUD_BD, record_sample_rate_hz=RECORD_SAMPLE_RATE_HZ
        )
        structure = stats["level_exploration"]["structure"]
        if not structure["four_levels"]:
            reasons.append("amplitude histogram does not show four separated levels")
        timebase = stats["timebase"]
        offset_ppm = timebase["measured_offset_ppm_vs_published_baud"]
        tone_ok = not (
            abs(offset_ppm) > TONE_TOLERANCE_PPM
            or timebase["tone_strength_median"] < TONE_MIN_STRENGTH
        )
        if not tone_ok:
            reasons.append(
                f"no symbol tone at the published baud under the header time increment "
                f"(offset {offset_ppm:.1f} ppm, strength {timebase['tone_strength_median']:.3f})"
            )
        psd = stats["psd"]
        freq = np.asarray(psd["frequency_hz"])
        density = np.asarray(psd["density_normalized"])
        rate = timebase["header_sample_rate_hz"]
        spur = {
            "band_around_record_rate_db_vs_peak": _band_db(
                freq,
                density,
                RECORD_SAMPLE_RATE_HZ - SPUR_BAND_HZ,
                RECORD_SAMPLE_RATE_HZ + SPUR_BAND_HZ,
            ),
            "quiet_band_db_vs_peak": _band_db(freq, density, 0.16 * rate, 0.22 * rate),
            "band_below_25ghz_db_vs_peak": _band_db(freq, density, 0.0, 25e9),
            "band_above_100ghz_db_vs_peak": _band_db(freq, density, 100e9, 0.5 * rate),
        }
        spur["excess_around_record_rate_db"] = (
            spur["band_around_record_rate_db_vs_peak"] - spur["quiet_band_db_vs_peak"]
        )
        native = native_rate_reading(capture, RECORD_SAMPLE_RATE_HZ)
        evidence = {
            "dc_over_std": stats["dc_over_std_file_units"],
            "level_structure": structure,
            "timebase": timebase,
            "spectrum": spur,
            "qc": stats["qc"],
            "physical_checks_on_slices": [
                (c.name, c.passed, c.detail) for c in capture.physical_checks()
            ],
            "native_rate_reading": native,
            "rate_chain_reading": _rate_chain_reading(layout, timebase, native, tone_ok),
        }
        layout_summary = {
            "container": layout.container,
            "dtype": layout.dtype,
            "data_offset": layout.data_offset,
            "samples": layout.count,
            "x_increment_s": layout.x_increment_s,
            "x_origin_s": layout.x_origin_s,
            "header_fields": dict(layout.header_fields),
            "scale": layout.scale,
            "size_hypothesis_136_bytes": _size_hypothesis_136(layout, path.stat().st_size),
        }
    except BenchmarkError as error:
        return _unknown_report(error)
    finally:
        capture.close()
    status = FormatStatus.FORMAT_UNKNOWN if reasons else FormatStatus.SUPPORTED_BY_EVIDENCE
    kind = np.dtype(layout.dtype)
    sample_words = (
        f"{'float' if kind.kind == 'f' else 'integer'}{kind.itemsize * 8} "
        f"{'little' if kind.byteorder in '<=' else 'big'}-endian"
    )
    summary = (
        f"SUPPORTED_BY_EVIDENCE (B2B only): Keysight BIN v{layout.header_fields['version']}, one "
        f"waveform, {sample_words} samples at byte {layout.data_offset}, scale {layout.scale}"
        if not reasons
        else "FORMAT_UNKNOWN (BLOCKED: FORMAT_UNVERIFIED): " + "; ".join(reasons)
    )
    return FormatReport(
        status,
        summary,
        layout_summary,
        structural,
        hypothesis_rows,
        evidence,
        tuple(reasons),
        EXPORTER_QUESTIONS,
    )


def b2b_diagnostics(
    path: Path | None = None, *, source: SourceRecord | None = None, eye_symbols: int = 20000
) -> dict[str, Any]:
    """Descriptive B2B diagnostics (`normalized`): whole record, two halves, three eyes."""
    source = source or load_config()
    capture = open_b2b(path, source=source)
    try:
        whole, timing = describe_capture_with_timing(
            capture, baud_bd=BAUD_BD, record_sample_rate_hz=RECORD_SAMPLE_RATE_HZ
        )
        half = capture.count // 2
        first = describe_capture_with_timing(capture, stop=half)[0]
        second = describe_capture_with_timing(capture, start=half)[0]
        if timing is None:
            raise BenchmarkError("timing was not measured")
        norm = (
            whole["normalization"]["offset_file_units"],
            whole["normalization"]["scale_file_units"],
        )
        total_symbols = int(capture.count / timing.sps_measured) - 8
        eyes = [
            explore_eye(
                capture,
                timing,
                norm,
                first_symbol=int(fraction * total_symbols),
                symbols=eye_symbols,
            )
            for fraction in (0.02, 0.5, 0.95)
        ]
    finally:
        capture.close()
    return {
        "scale": whole["scale"],
        "whole": whole,
        "halves": {
            "first": _brief(first),
            "second": _brief(second),
            "note": "within-B2B consistency check of plan section 2; descriptive only",
        },
        "eye_stretches": eyes,
    }


def _brief(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "samples": stats["samples"],
        "dc_over_std_file_units": stats["dc_over_std_file_units"],
        "normalization": stats["normalization"],
        "quantiles_normalized": stats["quantiles_normalized"],
        "estimated_levels_normalized": stats["level_exploration"]["estimated_levels_normalized"],
        "estimated_level_gaps_normalized": stats["level_exploration"][
            "estimated_level_gaps_normalized"
        ],
    }
