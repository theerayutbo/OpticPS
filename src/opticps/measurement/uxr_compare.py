"""Paired comparison and report for scope captures analysed by ingest-uxr.

Uses the capture-level results (pooled over frames), the fairness audit and the same
MIN_PAIRED_RUNS and verdict wording as the simulated comparison. Training captures are
counted but never scored, and captures whose rate estimate is unreliable are excluded from the
paired rate comparison and listed.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from opticps.measurement.capture import Capture
from opticps.measurement.compare import MIN_PAIRED_RUNS, fairness_audit
from opticps.optimization.adaptive import assert_disjoint
from opticps.reporting.facts import verdict
from opticps.statistics.intervals import paired_difference_interval


def _row(item: dict[str, Any]) -> dict[str, Any]:
    meta = item["sidecar"]
    pooled = item["map"]
    return {
        "capture_id": item["capture_id"],
        "waveform": item["waveform"],
        "run_id": meta["run_id"],
        "data_source": meta["data_source"],
        "received_power_dBm": meta.get("optical_received_power_dBm"),
        "symbol_errors": pooled["symbol_errors"],
        "symbols": pooled["symbols"],
        "ser": pooled["ser"],
        "ser_report": pooled["ser_report"],
        "ser_ci_low": pooled["ser_ci"][0],
        "ser_ci_high": pooled["ser_ci"][1],
        "ser_upper_95": pooled["ser_upper_95"],
        "ber": pooled["ber"],
        "ber_report": pooled["ber_report"],
        "r_smd": item["r_smd"],
        "r_bmd": item["r_bmd"],
        "snr_db": item["snr_db"],
        "frames_analyzed": item["frames_analyzed"],
        "frames_lost": item["frames_lost"],
        "clock_offset_ppm": item["clock_offset_ppm"],
        "clock_confidence": item["clock_confidence"],
        "rate_estimate_reliable": item["rate_estimate_reliable"],
        "air_gbps": item["r_bmd"] * item["symbol_rate_nominal_Bd"] / 1e9,
    }


def compare_uxr(results_dir: Path, out_dir: Path | None = None) -> dict[str, Any]:
    """Build the paired comparison, fairness audit and report from ingest-uxr results."""
    out_dir = results_dir if out_dir is None else out_dir
    items = [json.loads(p.read_text()) for p in sorted(results_dir.glob("*_analysis.json"))]
    items = [i for i in items if "sidecar" in i]
    if not items:
        raise FileNotFoundError(f"No ingest-uxr results (*_analysis.json) in {results_dir}")
    training = [i for i in items if i["split"] == "training"]
    test = [i for i in items if i["split"] == "test"]
    assert_disjoint([i["capture_id"] for i in training], [i["capture_id"] for i in test])
    rows = [_row(i) for i in test]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["waveform"], row["run_id"])
        if key in seen:
            raise ValueError(f"Two test captures for waveform {key[0]} run {key[1]}")
        seen.add(key)
    usable = [r for r in rows if r["rate_estimate_reliable"]]
    excluded = [r["capture_id"] for r in rows if not r["rate_estimate_reliable"]]
    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in usable:
        groups[row["waveform"]][row["run_id"]] = row
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
                    "verdict": verdict(mean, interval, "bit/symbol"),
                }
            )
    audit = fairness_audit([Capture(i["sidecar"], np.empty(0)) for i in test]) if test else []
    summary: dict[str, Any] = {
        "data_sources": sorted({i["sidecar"]["data_source"] for i in items}),
        "test_captures": len(test),
        "training_captures": len(training),
        "excluded_unreliable_rate_estimate": excluded,
        "comparisons": comparisons,
        "fairness_audit": audit,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        with (out_dir / "capture_metrics.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (out_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "uxr_report.md").write_text(_report(summary, rows))
    return summary


def _report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# UXR capture comparison",
        "",
        f"Data sources: {', '.join(summary['data_sources'])}. "
        f"{summary['test_captures']} test and {summary['training_captures']} training captures; "
        "training captures are never scored.",
        "",
        "## Captures",
        "",
    ]
    for row in rows:
        flag = "" if row["rate_estimate_reliable"] else " (rate estimate unreliable, excluded)"
        lines.append(
            f"- {row['capture_id']} ({row['waveform']}, run {row['run_id']}): "
            f"SER {row['ser_report']}; {row['frames_analyzed']} frames analysed, "
            f"{row['frames_lost']} lost{flag}."
        )
    lines += ["", "## Paired comparisons (R_BMD)", ""]
    for item in summary["comparisons"]:
        pair = " vs ".join(item["pair"])
        text = item.get("verdict") or f"{item['result']}, {item['runs']} runs"
        lines.append(f"- {pair}: {text}.")
    if not summary["comparisons"]:
        lines.append("- No pairs.")
    lines += ["", "## Fairness audit", "", "| Variable | Status | Range |", "|---|---|---|"]
    lines += [
        f"| {r['variable']} | {r['status']} | {r['range']} |" for r in summary["fairness_audit"]
    ]
    lines += [
        "",
        "Frames repeat the same payload, so pooled symbols are not independent data. A lower "
        "error rate or symbol energy is not a throughput gain.",
        "",
    ]
    return "\n".join(lines)
