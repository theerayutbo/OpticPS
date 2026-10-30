"""Ingest one oscilloscope export, check it against its sidecar, and analyze it.

The sidecar is the capture metadata schema of capture.py. The sample rate analysed is
always the one measured from the file; the declared one is only cross-checked (1%).
Training captures are never scored as test.

Leakage guard: a registry file (default under data/private/) records the SHA-256 of every
ingested file and of its decoded samples, with its split. A capture that matches an earlier
entry under the other split is refused. The guard only sees registries it is given: runs that
use different registry files, a different export of the same acquisition, or a re-acquisition
are not detected. Entries are written only after an ingest succeeds.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from opticps.measurement.capture import CaptureValidationError, load_reference, validate_metadata
from opticps.measurement.uxr_import import ScopeWaveform, read_scope_file
from opticps.optimization.adaptive import DataLeakageError
from opticps.receiver.capture_dsp import ScopeAnalysis, analyze_scope_capture

RATE_TOLERANCE = 0.01
DEFAULT_REGISTRY = Path("data/private/uxr_registry.json")
PROBABILITY_TOLERANCE = 1e-5
SYMBOL_RATE_TOLERANCE = 1e-6
MISMATCH_SNR_DB = 3.0
MISMATCH_SER_FRACTION = 0.8
PROBABILITY_COLUMNS = ("minus3", "minus1", "plus1", "plus3")


def _resolve_split(metadata: dict[str, Any], split: str | None) -> dict[str, Any]:
    """Return metadata with a split taken from the sidecar or the argument, never defaulted."""
    declared = metadata.get("split")
    if declared is not None and split is not None and declared != split:
        raise CaptureValidationError(f"Sidecar split {declared!r} conflicts with {split!r}")
    chosen = declared if declared is not None else split
    if chosen is None:
        raise CaptureValidationError("Sidecar has no split; set it to training or test")
    return {**metadata, "split": chosen}


def _load_registry(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return dict(data["entries"])


def _check_registry(
    registry: dict[str, dict[str, str]], capture_id: str, split: str, digests: dict[str, str]
) -> None:
    """Refuse the same id, file or decoded samples under the other split, or an id reused."""
    for name, entry in registry.items():
        same_content = any(entry.get(key) == value for key, value in digests.items())
        if name == capture_id and entry["split"] != split:
            raise DataLeakageError(
                f"Capture id {capture_id!r} is registered as {entry['split']}, not {split}"
            )
        if same_content and entry["split"] != split:
            raise DataLeakageError(
                f"This capture's content is already registered as {entry['split']} "
                f"(capture {name!r}); it cannot be used as {split}"
            )
        if name == capture_id and not same_content:
            raise CaptureValidationError(
                f"Capture id {capture_id!r} is already registered with different content"
            )


def _write_registry(
    path: Path, registry: dict[str, dict[str, str]], capture_id: str, entry: dict[str, str]
) -> None:
    registry = {**registry, capture_id: entry}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"entries": registry}, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _check_against_manifest(metadata: dict[str, Any], row: dict[str, str]) -> list[str]:
    """Sidecar priors and symbol rate must agree with the transmitter manifest."""
    notes = []
    declared = np.array(metadata["symbol_probabilities"], dtype=float)
    candidates = {
        "realised": [float(row[f"realised_probability_{k}"]) for k in PROBABILITY_COLUMNS],
        "design": [float(row[f"probability_{k}"]) for k in PROBABILITY_COLUMNS],
    }
    matched = [
        name
        for name, values in candidates.items()
        if np.max(np.abs(declared - np.array(values))) <= PROBABILITY_TOLERANCE
    ]
    if not matched:
        raise CaptureValidationError(
            f"Sidecar symbol_probabilities {declared.tolist()} do not match the manifest "
            f"(realised {candidates['realised']}, design {candidates['design']})"
        )
    notes.append(f"priors match the manifest {matched[0]} probabilities")
    manifest_rate = float(row["symbol_rate_Bd"])
    if abs(metadata["symbol_rate_Bd"] / manifest_rate - 1) > SYMBOL_RATE_TOLERANCE:
        raise CaptureValidationError(
            f"Sidecar symbol rate {metadata['symbol_rate_Bd']:g} Bd differs from the "
            f"manifest's {manifest_rate:g} Bd"
        )
    return notes


def _summary(analysis: ScopeAnalysis, priors: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {
        "measured_sample_rate_Sa_per_s": analysis.measured_sample_rate,
        "symbol_rate_nominal_Bd": analysis.symbol_rate_nominal,
        "estimated_symbol_rate_Bd": analysis.estimated_symbol_rate,
        "clock_offset_ppm": analysis.clock_offset_ppm,
        "clock_stderr_ppm": analysis.clock_stderr_ppm,
        "clock_confidence": analysis.clock_confidence,
        "polarity_inverted": analysis.polarity_inverted,
        "preamble_correlation": analysis.preamble_correlation,
        "frames_found": analysis.frames_found,
        "frames_complete": analysis.frames_complete,
        "frames_expected": analysis.frames_expected,
        "frames_analyzed": analysis.frames_analyzed,
        "frames_lost": analysis.frames_lost,
        "lost_frame_numbers": analysis.lost_frame_numbers,
        "distinct_payload_symbols": analysis.distinct_payload_symbols,
        "timing_residual_rms_samples": analysis.timing_residual_rms_samples,
        "gain_v_per_level": analysis.gain_v_per_level,
        "offset_v": analysis.offset_v,
        "rate_estimate_reliable": analysis.rate_estimate_reliable,
        "warnings": list(analysis.warnings),
    }
    if analysis.map is None or analysis.minimum_distance is None:
        out["error_metrics"] = None
        out["note"] = "training capture: used for fitting only; no payload-derived value reported"
        return out
    for key, pooled in (("map", analysis.map), ("minimum_distance", analysis.minimum_distance)):
        out[key] = asdict(pooled)
    out.update(
        r_smd=analysis.r_smd,
        r_bmd=analysis.r_bmd,
        snr_db=analysis.snr_db,
        level_test_symbols=analysis.level_test_symbols,
        symbol_histogram=None
        if analysis.symbol_histogram is None
        else analysis.symbol_histogram.tolist(),
    )
    random_ser = 1.0 - float(np.sum(priors**2))
    ser = analysis.map.symbol_errors / analysis.map.symbols
    suspect = (
        analysis.snr_db is not None
        and analysis.snr_db < MISMATCH_SNR_DB
        and ser >= MISMATCH_SER_FRACTION * random_ser
    )
    out["reference_mismatch_suspected"] = suspect
    if suspect:
        out["rate_estimate_reliable"] = False
        out["warnings"].append(
            f"reference_mismatch_suspected: symbol error rate {ser:.3g} is close to the random "
            f"guess rate {random_ser:.3g} at SNR {analysis.snr_db:.1f} dB. Check that the "
            "capture belongs to the stated transmit experiment"
        )
    return out


def ingest_uxr(
    input_path: Path,
    sidecar_path: Path,
    reference_root: Path,
    profile: str,
    results_dir: Path,
    channel: int = 1,
    x_increment_s: float | None = None,
    split: str | None = None,
    registry: Path | None = None,
    segment: int | None = None,
    allow_waveform_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Import, validate, analyze and write the results of one scope capture."""
    registry_path = DEFAULT_REGISTRY if registry is None else registry
    metadata = _resolve_split(json.loads(sidecar_path.read_text()), split)
    validate_metadata(metadata)
    waveform = read_scope_file(
        input_path,
        channel,
        x_increment_s=x_increment_s,
        segment=segment,
        allow_waveform_types=allow_waveform_types,
    )
    declared = metadata["capture_sample_rate_Sa_per_s"]
    if abs(waveform.measured_sample_rate / declared - 1) > RATE_TOLERANCE:
        raise CaptureValidationError(
            f"Sidecar sample rate {declared:g} Sa/s differs from the file's "
            f"{waveform.measured_sample_rate:g} Sa/s by more than {RATE_TOLERANCE:.0%}"
        )
    with (reference_root / profile / "experiment_manifest.csv").open(newline="") as handle:
        by_id = {r["experiment_id"]: r for r in csv.DictReader(handle)}
    experiment = metadata["related_transmit_experiment_id"]
    if experiment not in by_id:
        raise ValueError(f"Capture refers to unknown experiment {experiment}")
    checks = _check_against_manifest(metadata, by_id[experiment])
    name = Path(by_id[experiment]["waveform_filename"]).stem
    frame = load_reference(reference_root / profile / "references" / name, name)
    digests = _digests(input_path, waveform)
    registered = _load_registry(registry_path)
    _check_registry(registered, metadata["capture_id"], metadata["split"], digests)
    priors = np.array(metadata["symbol_probabilities"], dtype=float)
    scored = metadata["split"] == "test"
    analysis = analyze_scope_capture(
        waveform, float(metadata["symbol_rate_Bd"]), frame, priors, score_payload=scored
    )
    imported = [str(w) for w in waveform.attributes.get("warnings", [])]
    summary = {
        "capture_id": metadata["capture_id"],
        "split": metadata["split"],
        "waveform": name,
        "source_file": input_path.name,
        "source_sha256": digests["sha256"],
        "samples_sha256": digests["samples_sha256"],
        "source_format": waveform.source_format,
        "channel": waveform.channel,
        "scope_model": waveform.model,
        "scope_serial": waveform.serial,
        "scope_saved_date": waveform.saved_date,
        "declared_sample_rate_Sa_per_s": declared,
        "manifest_checks": checks,
        "import_attributes": waveform.attributes,
        "sidecar": metadata,
        **_summary(analysis, priors),
    }
    summary["warnings"] = [*imported, *summary["warnings"]]
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = results_dir / metadata["capture_id"]
    Path(f"{stem}_analysis.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    if scored:
        with Path(f"{stem}_frames.csv").open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["frame_number", "start_time_s", "symbols", "symbol_errors", "snr_db"])
            for f in analysis.frames:
                assert f.map is not None
                writer.writerow(
                    [
                        f.frame_number,
                        f.start_time_s,
                        f.map.symbols,
                        f.map.symbol_errors,
                        f.map.snr_db,
                    ]
                )
        np.savez(f"{stem}_eye.npz", eye=analysis.eye, time_ui=analysis.eye_time_ui)
    entry = {
        "split": metadata["split"],
        "source_file": input_path.name,
        "recorded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **digests,
    }
    _write_registry(registry_path, registered, metadata["capture_id"], entry)
    return summary


def _digests(path: Path, waveform: ScopeWaveform) -> dict[str, str]:
    """Content hashes of the file and of the decoded samples."""
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "samples_sha256": hashlib.sha256(
            np.ascontiguousarray(waveform.samples_v, dtype="<f8").tobytes()
        ).hexdigest(),
    }
