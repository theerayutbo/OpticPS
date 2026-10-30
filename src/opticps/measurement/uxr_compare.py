"""Paired comparison and report for scope captures analysed by ingest-uxr.

Uses the capture-level results (pooled over frames), the fairness audit and the same
MIN_PAIRED_RUNS and verdict wording as the simulated comparison. Training captures are
counted but never scored, and captures whose rate estimate is unreliable are excluded from the
paired rate comparison and listed.

Comparisons are made per condition (profile, attenuation setting, fiber length): waveforms are
paired by run id inside one condition, so a sweep gives one verdict per point. Set-points
(symbol rate, AWG and capture sample rates, electrical amplitude, fiber length, attenuation,
receiver bandwidth) must match for a verdict. Measured outcomes (launch power, OMA, extinction
ratio) differ between waveforms at a fixed drive by design; they are reported and never gate.
Received power is reported with its spread and gates only beyond a tolerance (default 0.5 dB),
with a warning. A set-point not recorded in all or some captures gives a verdict with a
"not recorded: X" caveat.

Independence checks: a file or decoded-sample hash may appear in only one result, so one
acquisition cannot count as several runs, and never in both training and test. Only identical
bytes or samples are caught; a re-export with different bytes cannot be detected. A verdict for
a pair is withheld when data sources mix or a controlled field differs between the captures,
and when any capture it uses is flagged reference_mismatch_suspected (flagged captures stay
counted and listed).

Conditions group on attenuation rounded to CONDITION_ATTENUATION_DB (0.1 dB) and fiber length
to CONDITION_LENGTH_KM (0.001 km), so a set-point read back with instrument noise still lands
in its condition; the metrics table keeps the recorded values.
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
from opticps.measurement.compare import (
    MEASURED_FIELDS,
    MIN_PAIRED_RUNS,
    POWER_TOLERANCE_DB,
    fairness_audit,
)
from opticps.optimization.adaptive import DataLeakageError, assert_disjoint
from opticps.reporting.facts import verdict
from opticps.statistics.intervals import paired_difference_interval

HASH_KEYS = ("source_sha256", "samples_sha256")
UNDETECTED = "a re-export of the same acquisition with different bytes cannot be detected"
MISSING_STATUSES = ("not recorded", "partly recorded")
POWER_LABEL = "Optical received power"
CONDITION_ATTENUATION_DB = 0.1  # attenuation and length are rounded to these before grouping
CONDITION_LENGTH_KM = 0.001


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
        "attenuation_dB": meta["attenuation_dB"],
        "fiber_length_km": meta["fiber_length_km"],
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
        "reference_mismatch_suspected": bool(item.get("reference_mismatch_suspected")),
        "air_gbps": item["r_bmd"] * item["symbol_rate_nominal_Bd"] / 1e9,
    }


def _condition(row: dict[str, Any]) -> tuple[str, float, float]:
    return (
        row["profile"],
        round(
            round(row["attenuation_dB"] / CONDITION_ATTENUATION_DB) * CONDITION_ATTENUATION_DB, 6
        ),
        round(round(row["fiber_length_km"] / CONDITION_LENGTH_KM) * CONDITION_LENGTH_KM, 6),
    )


def _condition_name(condition: tuple[str, float, float]) -> str:
    profile, attenuation, length = condition
    return f"{profile}, attenuation {attenuation:g} dB, fiber {length:g} km"


def _excluded_flag_note(
    condition: tuple[str, float, float],
    waveforms: list[str],
    flagged_excluded: dict[tuple[tuple[str, float, float], str], list[str]],
) -> str:
    """Name captures dropped as unreliable that also carry the reference flag, if any."""
    names = sorted(i for w in waveforms for i in flagged_excluded.get((condition, w), []))
    if not names:
        return ""
    return (
        f"; {len(names)} capture(s) excluded as unreliable carry reference_mismatch_suspected "
        f"({', '.join(names)}), so a wrong reference may be the cause"
    )


def compare_uxr(
    results_dir: Path, out_dir: Path | None = None, power_tolerance_db: float = POWER_TOLERANCE_DB
) -> dict[str, Any]:
    """Build the per-condition paired comparison, fairness audit and report."""
    if not np.isfinite(power_tolerance_db) or power_tolerance_db < 0:
        raise ValueError(f"power tolerance must be finite and 0 or more, got {power_tolerance_db}")
    out_dir = results_dir if out_dir is None else out_dir
    loaded = [json.loads(p.read_text()) for p in sorted(results_dir.glob("*_analysis.json"))]
    items = [i for i in loaded if isinstance(i, dict) and "sidecar" in i]
    skipped = [
        str(i.get("capture_id", "?")) if isinstance(i, dict) else "?"
        for i in loaded
        if not (isinstance(i, dict) and "sidecar" in i)
    ]
    if not items:
        raise FileNotFoundError(
            f"No ingest-uxr results with a sidecar (*_analysis.json) in {results_dir}"
        )
    warnings = (
        [f"{len(skipped)} result file(s) without a sidecar were not compared: {', '.join(skipped)}"]
        if skipped
        else []
    )
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
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (*_condition(row), row["waveform"], row["run_id"])
        if key in seen:
            raise ValueError(
                f"Two test captures for {_condition_name(_condition(row))} waveform "
                f"{row['waveform']} run {row['run_id']}"
            )
        seen.add(key)
    usable = [r for r in rows if r["rate_estimate_reliable"]]
    excluded = [r["capture_id"] for r in rows if not r["rate_estimate_reliable"]]
    groups: dict[tuple[str, float, float], dict[str, dict[str, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for row in usable:
        groups[_condition(row)][row["waveform"]][row["run_id"]] = row
    comparisons: list[dict[str, Any]] = []
    rng = np.random.default_rng(0)
    present: dict[tuple[str, float, float], set[str]] = defaultdict(set)
    flagged_excluded: dict[tuple[tuple[str, float, float], str], list[str]] = defaultdict(list)
    for row in rows:
        present[_condition(row)].add(row["waveform"])
        if row["reference_mismatch_suspected"] and not row["rate_estimate_reliable"]:
            flagged_excluded[(_condition(row), row["waveform"])].append(row["capture_id"])
    for condition in sorted(present):
        if len(groups.get(condition, {})) < 2:
            only = ", ".join(sorted(present[condition]))
            alone = len(present[condition]) == 1
            note = _excluded_flag_note(condition, sorted(present[condition]), flagged_excluded)
            comparisons.append(
                {
                    "profile": condition[0],
                    "condition": _condition_name(condition),
                    "pair": sorted(present[condition]),
                    "result": (
                        f"no comparison, waveform {only} is alone in this condition"
                        if alone
                        else f"no comparison, fewer than 2 waveforms ({only}) have a usable rate "
                        "estimate in this condition"
                    )
                    + note,
                    "runs": 0,
                    "caveats": [],
                    "warnings": [],
                }
            )
    for condition in sorted(groups):
        names = sorted(groups[condition])
        for i, first in enumerate(names):
            for second in names[i + 1 :]:
                _compare_pair(
                    comparisons,
                    condition,
                    (first, second),
                    groups[condition],
                    by_id,
                    rng,
                    power_tolerance_db,
                    flagged_excluded,
                )
    flagged = [r["capture_id"] for r in rows if r["reference_mismatch_suspected"]]
    if flagged:
        warnings.append(
            f"{len(flagged)} test capture(s) flagged reference_mismatch_suspected, counted and "
            f"listed; any pair using one has its verdict withheld: {', '.join(flagged)}"
        )
    for item in comparisons:
        warnings.extend(item.get("warnings", []))
    audit = (
        fairness_audit([Capture(i["sidecar"], np.empty(0)) for i in test], power_tolerance_db)
        if test
        else []
    )
    summary: dict[str, Any] = {
        "data_sources": sorted({i["sidecar"]["data_source"] for i in items}),
        "test_captures": len(test),
        "training_captures": len(training),
        "excluded_unreliable_rate_estimate": excluded,
        "flagged_reference_mismatch": flagged,
        "skipped_without_sidecar": skipped,
        "power_tolerance_dB": power_tolerance_db,
        "condition_resolution": {
            "attenuation_dB": CONDITION_ATTENUATION_DB,
            "fiber_length_km": CONDITION_LENGTH_KM,
        },
        "warnings": warnings,
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
    condition: tuple[str, float, float],
    pair: tuple[str, str],
    groups: dict[str, dict[str, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
    rng: np.random.Generator,
    power_tolerance_db: float,
    flagged_excluded: dict[tuple[tuple[str, float, float], str], list[str]],
) -> None:
    """Append the paired result for two waveforms in one condition, or the reason for none."""
    first, second = pair
    base: dict[str, Any] = {
        "profile": condition[0],
        "condition": _condition_name(condition),
        "pair": [first, second],
    }
    one, two = groups[first], groups[second]
    common = sorted(set(one) & set(two))
    if len(common) < MIN_PAIRED_RUNS:
        comparisons.append(
            {
                **base,
                "result": f"insufficient paired runs (need {MIN_PAIRED_RUNS})"
                + _excluded_flag_note(condition, [first, second], flagged_excluded),
                "runs": len(common),
            }
        )
        return
    used = [by_id[g[r]["capture_id"]] for g in (one, two) for r in common]
    audit = fairness_audit([Capture(i["sidecar"], np.empty(0)) for i in used], power_tolerance_db)
    reasons, caveats, warnings = [], [], []
    sources = sorted({i["sidecar"]["data_source"] for i in used})
    if len(sources) > 1:
        reasons.append(f"data sources mix ({', '.join(sources)})")
    differing = []
    for r in audit:
        if r["status"] == "uncontrolled" and r["role"] == "set-point":
            differing.append(f"{r['variable']} ({r['status']}: {r['range']})")
        elif r["status"] == "uncontrolled":
            reasons.append(
                f"{r['variable']} spread ({r['range']}) exceeds the {power_tolerance_db:g} dB "
                "tolerance"
            )
            warnings.append(
                f"{base['condition']}, {first} vs {second}: {r['variable']} spread "
                f"({r['range']}) exceeds {power_tolerance_db:g} dB; verdict withheld"
            )
        elif r["status"] in MISSING_STATUSES and (
            r["role"] == "set-point" or r["variable"] == POWER_LABEL
        ):
            detail = "" if r["status"] == "not recorded" else f" (only {r['range'].split('; ')[1]})"
            caveats.append(f"not recorded: {r['variable']}{detail}")
    if differing:
        reasons.append("set-points differ: " + "; ".join(differing))
    reported = {
        r["variable"]: r["range"] for r in audit if r["variable"] in dict(MEASURED_FIELDS).values()
    }
    flagged = sorted(i["capture_id"] for i in used if i.get("reference_mismatch_suspected"))
    if flagged:
        reasons.append(
            f"{len(flagged)} of {len(used)} captures flagged reference_mismatch_suspected "
            f"({', '.join(flagged)}); a verdict from references that may not match the "
            "transmitted frames would be wrong"
        )
    base.update(
        {
            "runs": len(common),
            "captures": sorted(i["capture_id"] for i in used),
            "flagged_captures": flagged,
            "reported": reported,
            "caveats": caveats,
        }
    )
    base["warnings"] = warnings
    if reasons:
        comparisons.append({**base, "result": "verdict withheld, " + " and ".join(reasons)})
        return
    mean, interval = paired_difference_interval(
        [one[r]["r_bmd"] for r in common], [two[r]["r_bmd"] for r in common], rng
    )
    comparisons.append(
        {
            **base,
            "metric": "paired difference in R_BMD, bit/symbol",
            "mean": mean,
            "ci95": interval,
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
        if row["reference_mismatch_suspected"]:
            flag += " (reference_mismatch_suspected, pair verdicts withheld)"
        lines.append(
            f"- {row['capture_id']} ({row['profile']} {row['waveform']}, run {row['run_id']}): "
            f"SER {row['ser_report']}; {row['frames_analyzed']} frames analysed, "
            f"{row['frames_lost']} lost{flag}."
        )
    resolution = summary["condition_resolution"]
    lines += [
        "",
        "## Paired comparisons (R_BMD), one per condition",
        "",
        "Captures share a condition when profile matches and attenuation and fiber length agree "
        f"within {resolution['attenuation_dB']:g} dB and {resolution['fiber_length_km']:g} km "
        "(values are rounded to these before grouping).",
        "",
    ]
    for item in summary["comparisons"]:
        pair = f"{item['condition']}: " + " vs ".join(item["pair"])
        text = item.get("verdict") or f"{item['result']}, {item['runs']} runs"
        lines.append(f"- {pair}: {text}.")
        if item.get("caveats"):
            lines.append(f"  - Caveat, {'; '.join(item['caveats'])}.")
        if item.get("reported"):
            shown = "; ".join(f"{k} {v}" for k, v in item["reported"].items())
            lines.append(f"  - Measured outcomes, reported and not gating: {shown}.")
    if not summary["comparisons"]:
        lines.append("- No pairs.")
    if summary["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in summary["warnings"]]
    lines += [
        "",
        "## Fairness audit (all test captures)",
        "",
        "| Variable | Role | Status | Range |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r['variable']} | {r['role']} | {r['status']} | {r['range']} |"
        for r in summary["fairness_audit"]
    ]
    lines += [
        "",
        "Frames repeat the same payload, so pooled symbols are not independent data. A lower "
        "error rate or symbol energy is not a throughput gain.",
        "",
    ]
    return "\n".join(lines)
