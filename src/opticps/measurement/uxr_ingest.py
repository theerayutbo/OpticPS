"""Ingest one oscilloscope export, check it against its sidecar, and analyze it.

The sidecar is the capture metadata schema of capture.py. The sample rate analysed is
always the one measured from the file; the declared one is only cross-checked (1%).
Training captures are never scored as test, and one file cannot appear under both splits.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from opticps.measurement.capture import CaptureValidationError, load_reference, validate_metadata
from opticps.measurement.uxr_import import read_scope_file
from opticps.optimization.adaptive import assert_disjoint
from opticps.receiver.capture_dsp import ScopeAnalysis, analyze_scope_capture

RATE_TOLERANCE = 0.01
INDEX_NAME = "uxr_index.json"


def _resolve_split(metadata: dict[str, Any], split: str | None) -> dict[str, Any]:
    """Return metadata with a split taken from the sidecar or the argument, never defaulted."""
    declared = metadata.get("split")
    if declared is not None and split is not None and declared != split:
        raise CaptureValidationError(f"Sidecar split {declared!r} conflicts with {split!r}")
    chosen = declared if declared is not None else split
    if chosen is None:
        raise CaptureValidationError("Sidecar has no split; set it to training or test")
    return {**metadata, "split": chosen}


def _record_split(results_dir: Path, capture_id: str, split: str, digest: str) -> None:
    """Refuse to use the same capture id or the same file under both splits."""
    path = results_dir / INDEX_NAME
    index: dict[str, dict[str, str]] = json.loads(path.read_text()) if path.exists() else {}
    entries = [*index.items(), (capture_id, {"split": split, "sha256": digest})]
    for key in ("capture_id", "sha256"):
        groups: dict[str, list[str]] = {"training": [], "test": []}
        for name, entry in entries:
            groups[entry["split"]].append(name if key == "capture_id" else entry["sha256"])
        assert_disjoint(groups["training"], groups["test"])
    index[capture_id] = {"split": split, "sha256": digest}
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")


def _summary(analysis: ScopeAnalysis, scored: bool) -> dict[str, Any]:
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
        "gain_v_per_level": analysis.gain_v_per_level,
        "offset_v": analysis.offset_v,
        "snr_db": analysis.snr_db,
        "warnings": analysis.warnings,
    }
    if not scored:
        out["error_metrics"] = None
        out["note"] = "training capture: used for fitting only, never reported as test"
        return out
    for key, pooled in (("map", analysis.map), ("minimum_distance", analysis.minimum_distance)):
        out[key] = asdict(pooled)
    out.update(
        r_smd=analysis.r_smd,
        r_bmd=analysis.r_bmd,
        rate_estimate_reliable=analysis.rate_estimate_reliable,
        level_test_symbols=analysis.level_test_symbols,
        symbol_histogram=analysis.symbol_histogram.tolist(),
    )
    return out


def ingest_uxr(
    input_path: Path,
    sidecar_path: Path,
    reference_root: Path,
    profile: str,
    results_dir: Path,
    channel: int = 1,
    accept_unverified_bin: bool = False,
    x_increment_s: float | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    """Import, validate, analyze and write the results of one scope capture."""
    metadata = _resolve_split(json.loads(sidecar_path.read_text()), split)
    validate_metadata(metadata)
    waveform = read_scope_file(
        input_path,
        channel,
        x_increment_s=x_increment_s,
        accept_unverified_bin=accept_unverified_bin,
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
    name = Path(by_id[experiment]["waveform_filename"]).stem
    frame = load_reference(reference_root / profile / "references" / name, name)
    results_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    _record_split(results_dir, metadata["capture_id"], metadata["split"], digest)
    analysis = analyze_scope_capture(
        waveform,
        float(metadata["symbol_rate_Bd"]),
        frame,
        np.array(metadata["symbol_probabilities"], dtype=float),
    )
    scored = metadata["split"] == "test"
    summary = {
        "capture_id": metadata["capture_id"],
        "split": metadata["split"],
        "waveform": name,
        "source_file": input_path.name,
        "source_sha256": digest,
        "source_format": waveform.source_format,
        "channel": waveform.channel,
        "scope_model": waveform.model,
        "scope_serial": waveform.serial,
        "scope_saved_date": waveform.saved_date,
        "declared_sample_rate_Sa_per_s": declared,
        "import_attributes": waveform.attributes,
        **_summary(analysis, scored),
    }
    stem = results_dir / metadata["capture_id"]
    Path(f"{stem}_analysis.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    if scored:
        with Path(f"{stem}_frames.csv").open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["frame_number", "start_time_s", "symbols", "symbol_errors", "snr_db"])
            for f in analysis.frames:
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
    return summary
