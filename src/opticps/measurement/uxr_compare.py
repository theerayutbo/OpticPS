"""Paired comparison and report for scope captures analysed by ingest-uxr.

Uses the capture-level results (pooled over frames), the fairness audit and the same
MIN_PAIRED_RUNS and verdict wording as the simulated comparison. Training captures are
counted but never scored, and captures whose rate estimate is unreliable are excluded from the
paired rate comparison and listed.

Independence checks: a file or decoded-sample hash may appear in only one result, so one
acquisition cannot count as several runs, and never in both training and test. Only identical
bytes or samples are caught; a re-export with different bytes cannot be detected. A verdict for
a pair is withheld when data sources mix or a controlled field differs between the captures.
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
from opticps.optimization.adaptive import DataLeakageError, assert_disjoint
from opticps.reporting.facts import verdict
from opticps.statistics.intervals import paired_difference_interval

HASH_KEYS = ("source_sha256", "samples_sha256")
UNDETECTED = "a re-export of the same acquisition with different bytes cannot be detected"
WITHHOLD_STATUSES = ("uncontrolled", "partly recorded")


def _check_independent(training: list[dict[str, Any]], test: list[dict[str, Any]]) -> None:
    """Refuse shared content across splits, and one acquisition counted as several captures."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*training, *test]:
        for key in HASH_KEYS:
            digest = item.get(key)
            if not isinstance(digest, str) or not digest:
                raise ValueError(
                    f"Result {item['capture_id']!r} has no {key}; re-run ingest-uxr to record it"
                )
            earlier = seen.setdefault((key, digest), item)
            if earlier is item:
                continue
            if earlier["split"] != item["split"]:
                raise DataLeakageError(
                    f"Captures {earlier['capture_id']!r} ({earlier['split']}) and "
                    f"{item['capture_id']!r} ({item['split']}) have the same {key}: training "
                    f"and test must be different acquisitions ({UNDETECTED})"
                )
            raise ValueError(
                f"Captures {earlier['capture_id']!r} (run {earlier['sidecar']['run_id']}) and "
                f"{item['capture_id']!r} (run {item['sidecar']['run_id']}) have the same {key}: "
                f"one acquisition cannot count as several runs ({UNDETECTED})"
            )


def _row(item: dict[str, Any]) -> dict[str, Any]:
    meta = item["sidecar"]
    pooled = item["map"]
    return {
        "capture_id": item["capture_id"],
        "profile": item["profile"],
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
    _check_independent(training, test)
    for item in items:
        if "profile" not in item:
            raise ValueError(
                f"Result {item['capture_id']!r} has no profile; re-run ingest-uxr to record it"
            )
    by_id = {i["capture_id"]: i for i in test}
    rows = [_row(i) for i in test]
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["profile"], row["waveform"], row["run_id"])
        if key in seen:
            raise ValueError(f"Two test captures for {key[0]} waveform {key[1]} run {key[2]}")
        seen.add(key)
    usable = [r for r in rows if r["rate_estimate_reliable"]]
    excluded = [r["capture_id"] for r in rows if not r["rate_estimate_reliable"]]
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in usable:
        groups[(row["profile"], row["waveform"])][row["run_id"]] = row
    comparisons: list[dict[str, Any]] = []
    rng = np.random.default_rng(0)
    for profile in sorted({p for p, _ in groups}):
        names = sorted(w for p, w in groups if p == profile)
        for i, first in enumerate(names):
            for second in names[i + 1 :]:
                _compare_pair(comparisons, profile, first, second, groups, by_id, rng)
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


def _compare_pair(
    comparisons: list[dict[str, Any]],
    profile: str,
    first: str,
    second: str,
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
    rng: np.random.Generator,
) -> None:
    """Append the paired result for two waveforms of one profile, or the reason for none."""
    pair = [first, second]
    one, two = groups[(profile, first)], groups[(profile, second)]
    common = sorted(set(one) & set(two))
    if len(common) < MIN_PAIRED_RUNS:
        comparisons.append(
            {
                "profile": profile,
                "pair": pair,
                "result": f"insufficient paired runs (need {MIN_PAIRED_RUNS})",
                "runs": len(common),
            }
        )
        return
    used = [by_id[g[r]["capture_id"]] for g in (one, two) for r in common]
    reasons = []
    sources = sorted({i["sidecar"]["data_source"] for i in used})
    if len(sources) > 1:
        reasons.append(f"data sources mix ({', '.join(sources)})")
    differing = [
        f"{r['variable']} ({r['status']}: {r['range']})"
        for r in fairness_audit([Capture(i["sidecar"], np.empty(0)) for i in used])
        if r["status"] in WITHHOLD_STATUSES
    ]
    if differing:
        reasons.append("controlled fields differ: " + "; ".join(differing))
    if reasons:
        comparisons.append(
            {
                "profile": profile,
                "pair": pair,
                "result": "verdict withheld, " + " and ".join(reasons),
                "runs": len(common),
            }
        )
        return
    mean, interval = paired_difference_interval(
        [one[r]["r_bmd"] for r in common], [two[r]["r_bmd"] for r in common], rng
    )
    comparisons.append(
        {
            "profile": profile,
            "pair": pair,
            "metric": "paired difference in R_BMD, bit/symbol",
            "mean": mean,
            "ci95": interval,
            "runs": len(common),
            "verdict": verdict(mean, interval, "bit/symbol"),
        }
    )


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
            f"- {row['capture_id']} ({row['profile']} {row['waveform']}, run {row['run_id']}): "
            f"SER {row['ser_report']}; {row['frames_analyzed']} frames analysed, "
            f"{row['frames_lost']} lost{flag}."
        )
    lines += ["", "## Paired comparisons (R_BMD)", ""]
    for item in summary["comparisons"]:
        pair = f"{item['profile']}: " + " vs ".join(item["pair"])
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
