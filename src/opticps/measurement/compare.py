"""Analyze captures and build fair comparisons.

Protocol A compares waveforms at equal baud. Protocol B compares at equal net rate.
Neither treats a lower BER or a lower symbol energy as a throughput gain.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opticps.instruments.m8199b import MAX_SAMPLE_RATE, MIN_SAMPLE_RATE
from opticps.measurement.capture import (
    Capture,
    CaptureValidationError,
    load_capture,
    load_reference,
)
from opticps.optimization.adaptive import assert_disjoint, select_distribution
from opticps.receiver.dsp import process_capture
from opticps.statistics.intervals import paired_difference_interval

CONTROLLED_FIELDS = (
    ("symbol_rate_Bd", "Symbol rate"),
    ("capture_sample_rate_Sa_per_s", "Capture sample rate"),
    ("awg_sample_rate_Sa_per_s", "AWG sample rate"),
    ("electrical_amplitude_Vpp", "Electrical amplitude"),
    ("optical_launch_power_dBm", "Optical launch power"),
    ("optical_received_power_dBm", "Optical received power"),
    ("oma_dBm", "Optical modulation amplitude"),
    ("extinction_ratio_dB", "Extinction ratio"),
    ("fiber_length_km", "Fiber length"),
    ("attenuation_dB", "Attenuation"),
    ("receiver_bandwidth_Hz", "Receiver bandwidth"),
)
TOLERANCE = 0.05
MIN_PAIRED_RUNS = 5
MIN_PREAMBLE_CORRELATION = 0.3


def fairness_audit(captures: list[Capture]) -> list[dict[str, str]]:
    """Report each variable as controlled, uncontrolled or not recorded, never assumed."""
    rows = []
    for field, label in CONTROLLED_FIELDS:
        values = [c.metadata.get(field) for c in captures]
        known = [v for v in values if v is not None]
        if not known:
            status, spread = "not recorded", "n/a"
        elif len(known) < len(values):
            status, spread = "partly recorded", f"{len(known)}/{len(values)} captures"
        else:
            span = max(known) - min(known)
            reference = max(abs(max(known)), 1e-30)
            matched = span <= TOLERANCE if "dB" in field else span <= 1e-6 * reference
            status = "controlled" if matched else "uncontrolled"
            spread = f"{min(known):.6g} to {max(known):.6g}"
        rows.append({"variable": label, "status": status, "range": spread})
    return rows


@dataclass(frozen=True)
class RateMatch:
    """Outcome of matching a uniform baseline to a shaped net rate."""

    feasible: bool
    reason: str
    target_net_bps: float
    uniform_symbol_rate: float | None = None
    sample_rate: float | None = None
    samples_per_symbol: int | None = None


def match_uniform_rate(
    target_net_bps: float, shaped_symbol_rate: float, symbols: int, reference_sps: int
) -> RateMatch:
    """Find an M8199B sample rate at which uniform PAM4 carries the target net rate.

    Net rate here is R_s * bits per symbol. It excludes FEC, because none is implemented.
    Equal rate is reached only by lowering the uniform baud rate, which is reported.
    """
    uniform_rate = target_net_bps / 2.0
    for sps in sorted(range(1, 257), key=lambda s: abs(s - reference_sps)):
        sample_rate = uniform_rate * sps
        samples = sps * symbols
        if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
            continue
        if samples % 512 or samples > 1_048_576:
            continue
        return RateMatch(
            True,
            f"Uniform baud lowered from {shaped_symbol_rate / 1e9:g} to "
            f"{uniform_rate / 1e9:.4f} GBaud; AWG rate changed to {sample_rate / 1e9:.4f} GSa/s",
            target_net_bps,
            uniform_rate,
            sample_rate,
            sps,
        )
    return RateMatch(False, "No integer samples per symbol fits the M8199B", target_net_bps)


def analyze_directory(
    capture_dir: Path, reference_root: Path, profile: str, out_dir: Path
) -> dict[str, Any]:
    """Analyze all test captures in a folder, with training captures used only to fit."""
    captures = [load_capture(path) for path in sorted(capture_dir.glob("*.json"))]
    if not captures:
        raise FileNotFoundError(f"No capture metadata in {capture_dir}")
    measured = [
        c.metadata["capture_id"] for c in captures if c.metadata["data_source"] == "measured"
    ]
    if measured:
        raise CaptureValidationError(
            f"Measured captures {measured} must not go through the periodic analyze path, "
            "which assumes one exact period. Use `opticps ingest-uxr` for each capture, then "
            "`opticps compare-uxr --results DIR`"
        )
    training = [c for c in captures if c.metadata["split"] == "training"]
    test = [c for c in captures if c.metadata["split"] == "test"]
    assert_disjoint(
        [c.metadata["capture_id"] for c in training], [c.metadata["capture_id"] for c in test]
    )
    with (reference_root / profile / "experiment_manifest.csv").open(newline="") as handle:
        by_id = {r["experiment_id"]: r for r in csv.DictReader(handle)}
    rows = []
    groups: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for capture in test:
        meta = capture.metadata
        experiment = meta["related_transmit_experiment_id"]
        if experiment not in by_id:
            raise ValueError(f"Capture refers to unknown experiment {experiment}")
        name = Path(by_id[experiment]["waveform_filename"]).stem
        frame = load_reference(reference_root / profile / "references" / name, name)
        priors = np.array(meta["symbol_probabilities"], dtype=float)
        result = process_capture(
            capture.samples,
            meta["capture_sample_rate_Sa_per_s"],
            meta["symbol_rate_Bd"],
            frame,
            priors,
        )
        row = {
            "capture_id": meta["capture_id"],
            "waveform": name,
            "run_id": meta["run_id"],
            "data_source": meta["data_source"],
            "received_power_dBm": meta["optical_received_power_dBm"],
            "ser": result.map.ser,
            "ser_ci_low": result.map.ser_ci[0],
            "ser_ci_high": result.map.ser_ci[1],
            "ber": result.map.ber,
            "ber_ci_low": result.map.ber_ci[0],
            "ber_ci_high": result.map.ber_ci[1],
            "symbol_errors": result.map.symbol_errors,
            "r_smd": result.map.r_smd,
            "r_bmd": result.map.r_bmd,
            "snr_db": result.map.snr_db,
            "preamble_correlation": result.preamble_correlation,
            "sync_reliable": result.preamble_correlation >= MIN_PREAMBLE_CORRELATION,
            "air_gbps": result.map.r_bmd * meta["symbol_rate_Bd"] / 1e9,
        }
        rows.append(row)
        groups[name][meta["run_id"]] = row
    out_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        with (out_dir / "capture_metrics.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    comparisons = []
    rng = np.random.default_rng(0)
    names = sorted(groups)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            common = sorted(set(groups[first]) & set(groups[second]))
            if len(common) < MIN_PAIRED_RUNS:
                comparisons.append(
                    {
                        "pair": [first, second],
                        "result": f"insufficient paired runs (need {MIN_PAIRED_RUNS})",
                        "runs": len(common),
                    }
                )
                continue
            mean, interval = paired_difference_interval(
                [groups[first][r]["r_bmd"] for r in common],
                [groups[second][r]["r_bmd"] for r in common],
                rng,
            )
            comparisons.append(
                {
                    "pair": [first, second],
                    "metric": "paired difference in R_BMD, bit/symbol",
                    "mean": mean,
                    "ci95": interval,
                    "runs": len(common),
                }
            )
    audit = fairness_audit(test) if test else []
    summary: dict[str, Any] = {
        "data_sources": sorted({c.metadata["data_source"] for c in captures}),
        "test_captures": len(test),
        "training_captures": len(training),
        "comparisons": comparisons,
        "fairness_audit": audit,
    }
    if training:
        summary["adaptive_from_training"] = adapt_from_training(training, reference_root, profile)
    (out_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def adapt_from_training(
    training: list[Capture], reference_root: Path, profile: str
) -> dict[str, Any]:
    """Select a distribution from training captures, which must carry uniform symbols."""
    indices, values = [], []
    with (reference_root / profile / "experiment_manifest.csv").open(newline="") as handle:
        by_id = {r["experiment_id"]: r for r in csv.DictReader(handle)}
    for capture in training:
        meta = capture.metadata
        name = Path(by_id[meta["related_transmit_experiment_id"]]["waveform_filename"]).stem
        frame = load_reference(reference_root / profile / "references" / name, name)
        priors = np.array(meta["symbol_probabilities"], dtype=float)
        result = process_capture(
            capture.samples,
            meta["capture_sample_rate_Sa_per_s"],
            meta["symbol_rate_Bd"],
            frame,
            priors,
        )
        indices.append(frame.indices)
        values.append(result.symbols)
    source = "training captures: " + ", ".join(c.metadata["capture_id"] for c in training)
    selection = select_distribution(np.concatenate(indices), np.concatenate(values), source)
    return {"p_outer": selection.p_outer, "objective": selection.objective, "source": source}
