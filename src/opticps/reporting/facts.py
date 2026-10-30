"""Derive every reported number and conclusion from saved results.

Text elsewhere uses these values; wording of a conclusion depends on the data, so a
negative or inconclusive outcome reads as one.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

import numpy as np

from opticps.statistics.intervals import paired_difference_interval

LABELS = ("Uniform", "PS70 (inner)", "PS80 (inner)", "Adaptive", "Outer70")


def operating_index(points: list[dict[str, Any]]) -> int:
    """Return the sweep point where Uniform is closest to 1 bit/symbol."""
    return int(np.argmin([abs(p["r_bmd"] - 1.0) for p in points]))


def verdict(mean: float, interval: tuple[float, float], unit: str) -> str:
    """Describe a paired difference without overstating it."""
    low, high = interval
    span = f"{mean:+.3f} {unit} (95% CI {low:+.3f} to {high:+.3f})"
    if low > 0:
        return f"higher by {span}"
    if high < 0:
        return f"lower: {span}"
    return f"not resolved: {span}"


def profile_facts(results: dict[str, Any], key: str) -> dict[str, Any]:
    """Summarize one profile at its reference operating point."""
    section = results[key]
    sweep = section["back_to_back"]
    index = operating_index(sweep["Uniform"])
    rate = section["symbol_rate_Bd"]
    table = []
    uniform_runs = sweep["Uniform"][index]["r_bmd_runs"]
    rng = np.random.default_rng(results["seed"])
    differences = {}
    for label in LABELS:
        point = sweep[label][index]
        table.append(
            {
                "label": label,
                "r_bmd": point["r_bmd"],
                "r_bmd_ci95": point["r_bmd_ci95"],
                "ser": point["ser"],
                "ber": point["ber"],
                "ser_ci95": point["ser_ci95"],
                "symbol_errors": point["symbol_errors"],
                "air_gbps": point["r_bmd"] * rate / 1e9,
                "launch_dbm": point["launch_dbm"],
                "received_dbm": point["received_dbm"],
                "oma_dbm": point["oma_dbm"],
                "er_db": point["er_db"],
            }
        )
        if label != "Uniform":
            mean, interval = paired_difference_interval(point["r_bmd_runs"], uniform_runs, rng)
            differences[label] = {"mean": mean, "ci95": interval}
    best = max(
        range(len(sweep["Uniform"])),
        key=lambda i: sweep["Outer70"][i]["r_bmd"] - sweep["Uniform"][i]["r_bmd"],
    )
    return {
        "index": index,
        "attenuation_db": sweep["Uniform"][index]["link"]["extra_attenuation_db"],
        "received_dbm": sweep["Uniform"][index]["received_dbm"],
        "table": table,
        "versus_uniform": differences,
        "best_outer_gain_received_dbm": sweep["Uniform"][best]["received_dbm"],
        "best_outer_gain": sweep["Outer70"][best]["r_bmd"] - sweep["Uniform"][best]["r_bmd"],
    }


def all_facts(results: dict[str, Any]) -> dict[str, Any]:
    """Return the facts used by the report and slides."""
    theory = results["theory"]
    gain = theory["gain_at_1bpcu"]
    psnr = theory["psnr_db"]
    i14 = psnr.index(14.0)
    curves = theory["rate_curves"]
    inner_never_wins = all(
        curves["PS70"]["smd"][i] <= curves["Uniform"]["smd"][i] + 1e-9 for i in range(len(psnr))
    )
    average_snr = theory["average_power_snr_db"]
    average = theory["average_power_smd"]
    crossover = next(
        (
            x
            for x, a, b in zip(average_snr, average["PS70"], average["Uniform"], strict=True)
            if a > b
        ),
        None,
    )
    return {
        "a": profile_facts(results, "profile_A"),
        "b": profile_facts(results, "profile_B"),
        "gain": gain,
        "rates_14db": {k: v["smd"][i14] for k, v in curves.items()},
        "inner_never_wins": inner_never_wins,
        "average_power_inner_wins_from_db": crossover,
    }
