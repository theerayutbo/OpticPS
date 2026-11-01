"""TERIPHIC PD1 PAM4 adapter (Stage 3A, gate E1): B2B only, offline, read-only.

Roles (plan `docs/benchmarks/FIT_HOLDOUT_PLAN.md`, R.3 and R5.2): only the characterisation file,
`50G_PAM4_PD1_B2B_Subassembly1.bin`, may have a sample byte read. The 2 km and 10 km files may be
hashed (`verify_local_asset`) and nothing else: this module refuses to open them, by registered
name, by any file under `data/external/` that is not the B2B file, and by supplied MD5 after the
hash-only step (so a renamed copy is caught before any header is read).

The verdict of `verify_b2b_format` is evidence-based and only about B2B. It never says
anything about the other two files: the accepted hypothesis is applied to them unchanged
only after the plan's freeze, and until then their format is `NOT_ASSESSED_HOLDOUT`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from opticps.benchmarks.capture_stats import (
    describe_capture_with_timing,
    explore_eye,
)
from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.external_capture import (
    ExternalCapture,
    FormatCheck,
    FormatStatus,
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
    parts = path.resolve().parts
    return any(parts[i : i + 2] == ("data", "external") for i in range(len(parts) - 1))


def guard_sample_read(path: Path, source: SourceRecord | None = None) -> AssetRecord | None:
    """Refuse any path that is, or may be, a holdout or unregistered capture. Reads no byte.

    Returns the B2B asset record when `path` is the B2B file, `None` for a path that is neither
    registered nor under `data/external/` (a fixture), and raises LEAKAGE_DETECTED otherwise.
    """
    source = source or load_config()
    name = Path(path).resolve().name
    by_name = {a.filename.casefold(): a for a in source.assets}
    asset = by_name.get(name.casefold())
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


def _refuse_renamed_holdout(checksum: Checksum, source: SourceRecord, name: str) -> None:
    """After the hash-only step: a file whose MD5 equals a holdout MD5 is that holdout."""
    if checksum.md5_local is None:
        return
    for asset in source.assets:
        if (
            asset.split is not Split.CHARACTERISATION
            and asset.checksum.md5_supplied == checksum.md5_local
        ):
            raise BenchmarkError(
                f"{name} has the MD5 of {asset.filename} ({asset.split.value}); refusing, "
                "no sample read",
                ErrorCode.LEAKAGE_DETECTED,
            )


def open_b2b(path: Path | None = None, *, source: SourceRecord | None = None) -> ExternalCapture:
    """Open the B2B capture read-only after the role, hash and structure checks."""
    source = source or load_config()
    path = Path(path) if path is not None else DEFAULT_ROOT / B2B_FILENAME
    asset = guard_sample_read(path, source)
    checksum = verify_local_asset(path, asset.checksum.md5_supplied if asset else None)
    _refuse_renamed_holdout(checksum, source, path.name)
    return ExternalCapture.open_keysight_bin(path, checksum=checksum)


def _band_db(freq: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    selected = (freq >= low) & (freq < high)
    return float(10.0 * np.log10(psd[selected].mean() / psd.max()))


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
    "sample-rate chain: the header time increment is 1/2.048 THz while the record says 256 (Gbaud "
    "sic); was the record captured at 256 GSa/s and interpolated 8x at export, and with "
    "what filter",
    "oscilloscope model and settings behind the frame string, bandwidth limit, ENOB, any digital "
    "filter applied before export (the EML record mentions a 50 GHz low-pass; this record "
    "is silent)",
    "transmitted sequence (PRBS order, pattern length, any repetition): none is documented",
    "laser wavelength, launch power, modulator bias and swing, photodiode bias and any amplifier",
)


def verify_b2b_format(
    path: Path | None = None, *, source: SourceRecord | None = None
) -> FormatReport:
    """Verify the B2B file's format by independent evidence, or leave it FORMAT_UNKNOWN.

    The evidence, all computed here from B2B bytes only: the documented Keysight BIN structure
    against the real file size (every redundant field must agree); the same bytes decoded under 84
    dtype/endianness/offset hypotheses with physical checks (one survivor required); a four-hump
    amplitude structure; and a symbol-rate tone in the squared waveform at the published baud under
    the header time increment. A hypothesis with the 136-byte offset the file size suggests is
    reported with the others; statistics cannot separate it from the structural 164-byte offset
    (seven samples), so structure decides.
    """
    source = source or load_config()
    path = Path(path) if path is not None else DEFAULT_ROOT / B2B_FILENAME
    capture = open_b2b(path, source=source)
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
        stats, timing = describe_capture_with_timing(
            capture, baud_bd=BAUD_BD, record_sample_rate_hz=RECORD_SAMPLE_RATE_HZ
        )
    except BenchmarkError as error:
        capture.close()
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
    structure = stats["level_exploration"]["structure"]
    if not structure["four_levels"]:
        reasons.append("amplitude histogram does not show four separated levels")
    timebase = stats["timebase"]
    offset_ppm = timebase["measured_offset_ppm_vs_published_baud"]
    if abs(offset_ppm) > TONE_TOLERANCE_PPM or timebase["tone_strength_median"] < TONE_MIN_STRENGTH:
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
    evidence = {
        "dc_over_std": stats["dc_over_std_file_units"],
        "level_structure": structure,
        "timebase": timebase,
        "spectrum": spur,
        "qc": stats["qc"],
        "physical_checks_on_slices": [
            (c.name, c.passed, c.detail) for c in capture.physical_checks()
        ],
        "rate_chain_reading": (
            "stored stream: header time increment 1/2.048 THz, confirmed by a symbol tone at the "
            "published 50 GBd (40.96 samples per symbol). The record's 256 GSa/s (INFERRED) gives "
            "5.12 samples per symbol; it is not the rate of the stored stream. Spectral energy "
            "round multiples of 256 GHz is consistent with 256 GSa/s native sampling stored after "
            "8x interpolation, which is a reading, not a verified fact."
        ),
    }
    layout_summary = {
        "container": layout.container,
        "dtype": layout.dtype,
        "data_offset": layout.data_offset,
        "samples": layout.count,
        "x_increment_s": layout.x_increment_s,
        "header_fields": dict(layout.header_fields),
        "scale": layout.scale,
        "size_hypothesis_136_bytes": "rejected by structure: header+data headers are 164 bytes "
        "and the declared point count is 40,959,993 (4 x 40,959,993 + 164 = file size)",
    }
    capture.close()
    status = FormatStatus.FORMAT_UNKNOWN if reasons else FormatStatus.SUPPORTED_BY_EVIDENCE
    summary = (
        "SUPPORTED_BY_EVIDENCE (B2B only): Keysight BIN v10, one waveform, float32 little-endian "
        "samples at byte 164, scale normalized"
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
