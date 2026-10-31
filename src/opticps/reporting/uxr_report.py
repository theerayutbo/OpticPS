"""Receiver-analysis report (Markdown and PDF) from ingest-uxr and compare-uxr outputs.

Everything here is read from saved files: the *_analysis.json, *_eye.npz and *_excerpt.npz
written by ingest-uxr, the analysis_summary.json written by compare-uxr, the exported
transmitter waveform files, and optionally the simulated results. Nothing is recomputed from
raw captures.

Label rule: the header states the data_source of the captures. When any capture is simulated
the report prints MOCK_BANNER prominently, and every figure and its caption carry the data
source. Simulated data is never called measured. The data_source label is the one the sidecar
declares; this module cannot verify it.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import json
import os
import tempfile
from itertools import islice
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from opticps import __version__
from opticps.measurement.uxr_ingest import EXCERPT_FIRST_SYMBOL, EXCERPT_SYMBOLS
from opticps.receiver.capture_dsp import describe_error_rate
from opticps.reporting.report import _table, render_pdf

MOCK_BANNER = "MOCK/SIMULATED CAPTURES: NOT LABORATORY MEASUREMENTS"
DEFAULT_STEM = "UXR_Receiver_Analysis"
DEFAULT_TITLE = "UXR Receiver Analysis"
# (waveform file stem, label in this report, label in the simulated results)
WAVEFORMS = (
    ("PAM4_Uniform", "Uniform", "Uniform"),
    ("PAM4_Fixed_PS70", "Fixed PS70", "PS70 (inner)"),
    ("PAM4_Fixed_PS80", "Fixed PS80", "PS80 (inner)"),
    ("PAM4_Adaptive", "Adaptive", "Adaptive"),
    ("PAM4_Fixed_Outer70", "Outer70", "Outer70"),
)
COLORS = {
    "Uniform": "#1f4e79",
    "Fixed PS70": "#c0504d",
    "Fixed PS80": "#e39a3b",
    "Adaptive": "#2e7d32",
    "Outer70": "#6a4c93",
}
LEVELS = (-3, -1, 1, 3)
FIGURE_DPI = 100
EYE_INTERPOLATION = 8
NOT_RECORDED = "not recorded"
NO_SIMULATED_POINT = "no comparable simulated point"
POSITION_TOLERANCE_KM = 1e-3
MOCK_DIFFERENCE = (
    "The mock captures use the same link parameters as the simulation (same configuration, "
    "profile and attenuation setting). They differ in the capture sample rate (the mock "
    "capture runs at the rate in the acquisition table, the simulation at 8 samples per "
    "symbol) and in the receiver chain (a non-periodic record with symbol clock estimation "
    "and a matched filter, against one exact period), in the noise realisation, and in the "
    "received power offset in the table above."
)
MEASURED_DIFFERENCE = (
    "The simulation is a model with assumed parameters, not a description of this link, so "
    "equal received power does not mean an equal link; the power offset in the table above "
    "is only one of the differences."
)


def _source_text(sources: list[str]) -> str:
    if len(sources) == 1:
        return sources[0]
    return f"{', '.join(sources)} (mixed)"


def _load(results_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the ingest results and the compare-uxr summary; refuse a missing or stale summary."""
    items = [json.loads(p.read_text()) for p in sorted(results_dir.glob("*_analysis.json"))]
    items = [i for i in items if isinstance(i, dict) and "sidecar" in i]
    if not items:
        raise FileNotFoundError(
            f"No ingest-uxr results with a sidecar (*_analysis.json) in {results_dir}"
        )
    summary_path = results_dir / "analysis_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Run opticps compare-uxr first; {summary_path} is missing")
    summary = json.loads(summary_path.read_text())
    if "excluded_unreliable_rate_estimate" not in summary:
        raise ValueError(f"{summary_path} was not written by compare-uxr")
    tests = sum(1 for i in items if i["split"] == "test")
    if summary.get("test_captures") != tests:
        raise ValueError(
            f"{summary_path} counts {summary.get('test_captures')} test captures but "
            f"{tests} results are present; re-run opticps compare-uxr"
        )
    return items, summary


def _condition_text(item: dict[str, Any]) -> str:
    meta = item["sidecar"]
    return (
        f"attenuation {meta['attenuation_dB']:g} dB, fiber {meta['fiber_length_km']:g} km, "
        f"run {meta['run_id']}"
    )


def _transmitted_excerpt(
    item: dict[str, Any], waveform_root: Path
) -> tuple[np.ndarray, np.ndarray] | str:
    """Symbol index and samples of the exported waveform file for the saved excerpt window."""
    folder = waveform_root / item["profile"]
    manifest = folder / "experiment_manifest.csv"
    if not manifest.exists():
        return f"manifest {manifest} not found"
    with manifest.open(newline="") as handle:
        rows = {r["experiment_id"]: r for r in csv.DictReader(handle)}
    row = rows.get(item["sidecar"]["related_transmit_experiment_id"])
    if row is None:
        return "experiment not in the manifest"
    path = folder / row["waveform_filename"]
    if not path.exists():
        return f"waveform file {path} not found"
    per_symbol = int(row["samples_per_symbol"])
    first = EXCERPT_FIRST_SYMBOL * per_symbol
    count = EXCERPT_SYMBOLS * per_symbol
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        values = [float(r[0]) for r in islice(reader, first, first + count)]
    samples = np.array(values)
    return EXCERPT_FIRST_SYMBOL + np.arange(samples.size) / per_symbol, samples


def _stamp(source: str) -> str:
    return f"data source: {source}" + (
        " (MOCK, not laboratory data)" if source == "simulated" else ""
    )


def _save(fig: Any, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=FIGURE_DPI)
    plt.close(fig)


def _excerpt_figure(
    item: dict[str, Any], label: str, results_dir: Path, waveform_root: Path, path: Path
) -> str | None:
    """Transmitted (exported file) and received (saved excerpt) samples. None if drawn."""
    saved = results_dir / f"{item['capture_id']}_excerpt.npz"
    if not saved.exists():
        return f"no saved received excerpt ({saved.name}); re-run ingest-uxr to save one"
    with np.load(saved) as data:
        time_symbols, volts = data["time_symbols"], data["volts"]
    sent = _transmitted_excerpt(item, waveform_root)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(7, 4.2), sharex=True)
    if isinstance(sent, str):
        top.text(
            0.5,
            0.5,
            f"transmitted excerpt unavailable: {sent}",
            ha="center",
            va="center",
            transform=top.transAxes,
            fontsize=8,
        )
    else:
        top.plot(sent[0], sent[1], color=COLORS[label], linewidth=1.0)
    top.set_ylabel("Exported file\n(normalised drive)")
    bottom.plot(time_symbols, volts, color="#333333", linewidth=0.9, marker=".", markersize=3)
    bottom.set_ylabel("Received (V)")
    bottom.set_xlabel("Symbol index from the start of the frame")
    top.set_title(
        f"{label}: transmitted and received excerpt, symbols {EXCERPT_FIRST_SYMBOL} to "
        f"{EXCERPT_FIRST_SYMBOL + EXCERPT_SYMBOLS - 1}\n{_stamp(item['sidecar']['data_source'])}",
        fontsize=8,
    )
    for axis in (top, bottom):
        axis.grid(alpha=0.3)
    _save(fig, path)
    return None


def _distribution_figure(item: dict[str, Any], label: str, path: Path) -> str | None:
    histogram = item.get("symbol_histogram")
    if not histogram or sum(histogram) == 0:
        return "no recovered symbol histogram in the result"
    recovered = np.array(histogram, dtype=float) / sum(histogram)
    target = np.array(item["sidecar"]["symbol_probabilities"], dtype=float)
    fig, axis = plt.subplots(figsize=(5.5, 3.2))
    x = np.arange(4)
    axis.bar(x - 0.2, target, 0.4, label="Target (sidecar)", color="#bbbbbb")
    axis.bar(x + 0.2, recovered, 0.4, label="Recovered (MAP decisions)", color=COLORS[label])
    axis.set_xticks(x, [f"{v:+d}" for v in LEVELS])
    axis.set_xlabel("PAM4 level")
    axis.set_ylabel("Probability")
    axis.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    axis.set_title(
        f"{label}: recovered symbol distribution\n{_stamp(item['sidecar']['data_source'])}",
        fontsize=8,
    )
    _save(fig, path)
    return None


def _eye_figure(item: dict[str, Any], label: str, results_dir: Path, path: Path) -> str | None:
    saved = results_dir / f"{item['capture_id']}_eye.npz"
    if not saved.exists():
        return f"no saved eye data ({saved.name})"
    with np.load(saved) as data:
        eye, time_ui = data["eye"], data["time_ui"]
    if eye.size == 0:
        return "the saved eye holds no traces"
    # Density of the traces, linearly interpolated between the saved time points.
    fraction = np.linspace(0, 1, EYE_INTERPOLATION, endpoint=False)
    dense = np.concatenate(
        [
            eye[:, [k]] * (1 - fraction) + eye[:, [k + 1]] * fraction
            for k in range(eye.shape[1] - 1)
        ],
        axis=1,
    )
    time = np.tile(np.linspace(time_ui[0], time_ui[-1], dense.shape[1]), dense.shape[0])
    fig, axis = plt.subplots(figsize=(5, 3.2))
    axis.hist2d(time, dense.reshape(-1), bins=(dense.shape[1], 120), cmap="viridis", norm="log")
    axis.set_xlabel("Time (symbol periods)")
    axis.set_ylabel("Calibrated level units")
    axis.set_title(
        f"{label}: eye diagram, {eye.shape[0]} traces\n{_stamp(item['sidecar']['data_source'])}",
        fontsize=8,
    )
    _save(fig, path)
    return None


def _matched_filter_text(item: dict[str, Any]) -> str:
    used = item.get("matched_filter")
    if used is None:
        return "not recorded (analysed before the filter was recorded)"
    return "on" if used else "off (unfiltered samples)"


def _ppm(value: float) -> str:
    return f"{round(value, 1) + 0.0:+.1f}"  # + 0.0 turns -0.0 into 0.0


def _interval(low: float, high: float) -> str:
    return f"{low:.3g} to {high:.3g}"


def _statistical_interval(pooled: dict[str, Any], errors: str, ci: str, upper: str) -> str:
    """Two-sided interval, or at zero errors only the one-sided upper bound."""
    if pooled[errors] == 0:
        return f"0 errors: one-sided 95% upper bound {pooled[upper]:.3g} (no lower bound)"
    return _interval(*pooled[ci])


def _simulated_point(
    item: dict[str, Any], simulation: dict[str, Any] | None, simulated_label: str
) -> tuple[dict[str, Any], float] | str:
    """The simulated point of the same waveform and profile nearest in received power."""
    if simulation is None:
        return "no simulation file"
    section = simulation.get("profile_" + item["profile"].split("_")[0])
    if section is None:
        return f"profile {item['profile']} is not in the simulation"
    power = item["sidecar"].get("optical_received_power_dBm")
    if power is None:
        return "the capture has no recorded received power"
    length = item["sidecar"]["fiber_length_km"]
    if length == 0:
        points = section["back_to_back"].get(simulated_label, [])
    else:
        points = [
            p
            for p in section["fiber"].get(simulated_label, [])
            if abs(p["link"]["fiber_length_km"] - length) <= POSITION_TOLERANCE_KM
        ]
    if not points:
        return f"the simulation has no {length:g} km points for this waveform"
    nearest = min(points, key=lambda p: abs(p["received_dbm"] - power))
    return nearest, power - nearest["received_dbm"]


def _uncertainty_row(item: dict[str, Any]) -> list[str]:
    pooled = item["map"]
    boot = pooled.get("ser_bootstrap_ci")
    calibration = item["sidecar"].get("calibration")
    return [
        item["capture_id"],
        _statistical_interval(pooled, "symbol_errors", "ser_ci", "ser_upper_95"),
        _statistical_interval(pooled, "bit_errors", "ber_ci", "ber_upper_95"),
        _interval(*boot) if boot else "none (needs 2 or more frames and an error)",
        json.dumps(calibration, sort_keys=True) if calibration else NOT_RECORDED,
    ]


def _waveform_section(
    items: list[dict[str, Any]],
    label: str,
    simulated_label: str,
    context: dict[str, Any],
) -> str:
    results_dir, figure_dir, relative = (context[k] for k in ("results", "figures", "relative"))
    items = sorted(
        items,
        key=lambda i: (
            i["sidecar"]["attenuation_dB"],
            i["sidecar"]["fiber_length_km"],
            str(i["sidecar"]["run_id"]),
            i["capture_id"],
        ),
    )
    first = items[0]
    source = first["sidecar"]["data_source"]
    name = first["waveform"]
    notes: list[str] = []
    figures = []
    for kind, caption, draw in (
        (
            "excerpt",
            "transmitted and received waveform excerpts",
            lambda p: _excerpt_figure(first, label, results_dir, context["waveform_root"], p),
        ),
        (
            "symbols",
            "recovered symbol distribution against the target",
            lambda p: _distribution_figure(first, label, p),
        ),
        ("eye", "eye diagram", lambda p: _eye_figure(first, label, results_dir, p)),
    ):
        figure_path = figure_dir / f"uxr_{name}_{kind}.png"
        problem = draw(figure_path)
        if problem is None:
            figures.append(
                f"![{label}, {caption}, capture {first['capture_id']} "
                f"[data source: {source}]]({relative}/{figure_path.name})"
            )
            context["figure_files"].append(figure_path)
        else:
            notes.append(f"Figure omitted ({caption}): {problem}.")
    parts = [f"## {label} ({name})", ""]
    if len(items) > 1:
        parts += [
            f"{len(items)} captures. Figures show capture {first['capture_id']} only; the "
            "tables list every capture.",
            "",
        ]
    parts += ["### Error rates", ""]
    parts.append(
        _table(
            [["Capture", "Condition", "SER", "BER"]]
            + [
                [
                    i["capture_id"],
                    _condition_text(i),
                    i["map"]["ser_report"],
                    i["map"]["ber_report"],
                ]
                for i in items
            ]
        )
    )
    parts += ["", "Post-matcher BER is diagnostic only; there is no FEC.", ""]
    parts += ["### Figures", "", *[f"{f}\n" for f in figures], *[f"{n}\n" for n in notes]]
    parts += ["### Signal quality", ""]
    parts.append(
        _table(
            [
                [
                    "Capture",
                    "SNR (dB)",
                    "R_SMD (bit/sym)",
                    "R_BMD (bit/sym)",
                    "rate_estimate_reliable",
                ]
            ]
            + [
                [
                    i["capture_id"],
                    f"{i['snr_db']:.2f}",
                    f"{i['r_smd']:.3f}",
                    f"{i['r_bmd']:.3f}",
                    str(i["rate_estimate_reliable"]).lower(),
                ]
                for i in items
            ]
        )
    )
    rows = [
        [
            "Capture",
            "Level",
            "Symbols",
            "Mean (level units)",
            "Spread, std (level units)",
            "Spread, std (V)",
        ]
    ]
    for i in items:
        stats = i.get("level_statistics")
        if not stats:
            rows.append(
                [i["capture_id"], "n/a", "n/a", "not saved; re-run ingest-uxr", "n/a", "n/a"]
            )
            continue
        for row in stats["levels"]:
            rows.append(
                [i["capture_id"], f"{row['level']:+d}", str(row["symbols"])]
                + ["n/a" if row[k] is None else f"{row[k]:.4g}" for k in ("mean", "std", "std_v")]
            )
    parts += ["", _table(rows), ""]
    parts += ["### Receiver acquisition configuration", ""]
    parts.append(
        _table(
            [
                [
                    "Capture",
                    "Receiver model",
                    "Source format",
                    "Sample rate (GSa/s)",
                    "Bandwidth (GHz)",
                    "Matched filter (one-symbol NRZ)",
                ]
            ]
            + [
                [
                    i["capture_id"],
                    f"{i['sidecar']['receiver_instrument_model']}; file reports "
                    f"{i.get('scope_model') or 'no model'}",
                    str(i["source_format"]),
                    f"{i['measured_sample_rate_Sa_per_s'] / 1e9:.4g} (from the file)",
                    f"{i['sidecar']['receiver_bandwidth_Hz'] / 1e9:.4g} (declared)",
                    _matched_filter_text(i),
                ]
                for i in items
            ]
        )
    )
    parts += [
        "",
        _table(
            [
                [
                    "Capture",
                    "Estimated symbol rate (GBd)",
                    "Clock offset (ppm)",
                    "Frames found",
                    "Frames analysed",
                    "Frames lost",
                ]
            ]
            + [
                [
                    i["capture_id"],
                    f"{i['estimated_symbol_rate_Bd'] / 1e9:.6g}",
                    f"{_ppm(i['clock_offset_ppm'])} (confidence {i['clock_confidence']})",
                    str(i["frames_found"]),
                    str(i["frames_analyzed"]),
                    f"{i['frames_lost']} (expected {i['frames_expected']})",
                ]
                for i in items
            ]
        ),
        "",
    ]
    parts += [f"### Simulation versus {context['noun']}", ""]
    rows = [
        [
            "Capture",
            "Received power (dBm)",
            "Nearest simulated power (dBm)",
            "Power difference",
            "Simulated SER",
            "Capture SER",
        ]
    ]
    for i in items:
        found = _simulated_point(i, context["simulation"], simulated_label)
        power = i["sidecar"].get("optical_received_power_dBm")
        shown = NOT_RECORDED if power is None else f"{power:.2f}"
        if isinstance(found, str):
            rows.append(
                [i["capture_id"], shown, "n/a", f"{NO_SIMULATED_POINT} ({found})", "n/a", "n/a"]
            )
            continue
        point, difference = found
        rows.append(
            [
                i["capture_id"],
                shown,
                f"{point['received_dbm']:.2f}",
                f"{difference:+.2f} dB ({context['noun']} minus simulation)",
                describe_error_rate(point["symbol_errors"], point["symbols"], "symbols"),
                i["map"]["ser_report"],
            ]
        )
    parts += [_table(rows), ""]
    parts += [
        "The simulated point has the same waveform and profile and the nearest received power. "
        + context["difference_note"],
        "",
    ]
    parts += ["### Uncertainty", ""]
    parts.append(
        _table(
            [
                [
                    "Capture",
                    "Statistical: SER 95% interval, or one-sided upper bound at 0 errors",
                    "Statistical: BER 95% interval, or one-sided upper bound at 0 errors",
                    "Statistical: frame bootstrap, SER",
                    "Physical uncertainty, from the sidecar",
                ]
            ]
            + [_uncertainty_row(i) for i in items]
        )
    )
    parts += [""]
    return "\n".join(parts)


def _verdict_lines(summary: dict[str, Any]) -> tuple[list[str], list[str]]:
    verdicts, withheld = [], []
    for item in summary["comparisons"]:
        head = f"{item['condition']}: {' vs '.join(item['pair'])}"
        if item.get("verdict"):
            verdicts.append(f"- {head}: {item['verdict']}.")
        else:
            withheld.append(f"- {head}: {item['result']} (paired runs: {item['runs']}).")
        for caveat in item.get("caveats", []):
            (verdicts if item.get("verdict") else withheld).append(f"  - Caveat, {caveat}.")
    return verdicts, withheld


def _markdown(
    items: list[dict[str, Any]], summary: dict[str, Any], title: str, context: dict[str, Any]
) -> str:
    sources = sorted({i["sidecar"]["data_source"] for i in items})
    tests = [i for i in items if i["split"] == "test"]
    training = len(items) - len(tests)
    simulated = "simulated" in sources
    noun = context["noun"]
    lines = [f"# {title}", ""]
    if simulated:
        lines += [f"**{MOCK_BANNER}**", ""]
    lines += [
        f"Data source of the captures: {_source_text(sources)}. The label is the one each sidecar "
        "declares; this report cannot verify it.",
        "",
        f"{len(tests)} test captures were analysed. Training captures ({training}) are used for "
        f"fitting only and are never scored. Software version {__version__}. Generated by "
        "opticps uxr-report from the ingest-uxr and compare-uxr outputs.",
        "",
    ]
    if simulated:
        lines += [
            "The simulated captures come from a mock receiver: a simulated link and no instrument. "
            "Their numbers show the report format and say nothing about hardware.",
            "",
        ]
    if len(sources) > 1:
        lines += [
            "The data sources are mixed. A pair of captures from different sources never "
            "receives a verdict (see the comparisons).",
            "",
        ]
    lines += [context["simulation_note"], ""]
    by_waveform: dict[str, list[dict[str, Any]]] = {}
    for item in tests:
        by_waveform.setdefault(item["waveform"], []).append(item)
    known = {name for name, _, _ in WAVEFORMS}
    ignored = sorted(set(by_waveform) - known)
    if ignored:
        lines += [f"Captures of other waveforms are not detailed here: {', '.join(ignored)}.", ""]
    for name, label, simulated_label in WAVEFORMS:
        if name in by_waveform:
            lines.append(_waveform_section(by_waveform[name], label, simulated_label, context))
    verdicts, withheld = _verdict_lines(summary)
    lines += ["## Comparison verdicts", ""]
    lines += verdicts or ["- No pair received a verdict."]
    lines += ["", "## Withheld or absent verdicts, and reasons", ""]
    lines += withheld or ["- None."]
    lines += ["", "## Flagged and excluded captures", ""]
    flagged = summary["flagged_reference_mismatch"]
    by_id = {i["capture_id"]: i for i in items}
    if flagged:
        lines += [
            f"- {c} is flagged reference_mismatch_suspected: "
            f"{by_id[c].get('reference_check_reason') or 'reason not saved'}. It stays counted and "
            "listed, and the verdict of any pair that uses it is withheld."
            for c in flagged
        ]
    else:
        lines += ["- No capture is flagged reference_mismatch_suspected."]
    excluded = summary["excluded_unreliable_rate_estimate"]
    lines += [
        f"- Excluded from the rate comparison because the rate estimate is unreliable: "
        f"{', '.join(excluded) if excluded else 'none'}.",
    ]
    lines += [f"- Warning: {w}" for w in summary["warnings"]]
    lines += ["", "## Set-point audit", ""]
    lines.append(
        _table(
            [["Variable", "Role", "Status", "Range"]]
            + [
                [
                    r["variable"],
                    "outcome" if r["role"] == "measured" else r["role"],
                    r["status"],
                    r["range"],
                ]
                for r in summary["fairness_audit"]
            ]
        )
    )
    lines += [
        "",
        "Set-points must match for a verdict. Outcomes differ between waveforms at a fixed drive "
        "by design and are reported, never gating, except received power beyond its tolerance "
        f"({summary['power_tolerance_dB']:g} dB).",
        "",
        "## Uncertainty",
        "",
        "Statistical uncertainty is the sampling variation of the error counts: Clopper-Pearson "
        "95% intervals over the pooled symbols, which assume independent errors, and a "
        "bootstrap over frames. Frames repeat one payload, so these intervals are optimistic "
        "and describe noise only. Physical measurement uncertainty (instrument calibration, "
        "power meter, attenuator and bandwidth accuracy) is a separate matter, is not part of "
        f"any interval above, and is {NOT_RECORDED} unless the sidecar's calibration field gives "
        "it. For these captures it is stated per capture in the uncertainty tables.",
        "",
        "## Limitations",
        "",
        f"- No real UXR export has been imported by this project; the importer follows the "
        f"vendor guide and was tested on synthetic files. Treat every {noun} here accordingly.",
        "- Sample loss of less than about 1 symbol, synchronous with the frame period on one "
        "waveform in every run, may not be detected.",
        "- Lower error rate or lower symbol energy is not a throughput gain.",
        "",
    ]
    return "\n".join(lines)


def build_uxr_report(
    results_dir: Path,
    out_dir: Path,
    simulation_path: Path | None = None,
    waveform_root: Path = Path("output/keysight_m8199b"),
    stem: str = DEFAULT_STEM,
    title: str = DEFAULT_TITLE,
) -> Path:
    """Write figures, Markdown and PDF. Returns the PDF path.

    Figures go to results_dir/figures. simulation_path may be missing, in which case every
    simulated comparison reads "no comparable simulated point".
    """
    items, summary = _load(results_dir)
    simulation: dict[str, Any] | None = None
    if simulation_path is not None and simulation_path.exists():
        simulation = json.loads(simulation_path.read_text())
        note = (
            f"Simulation for comparison: {simulation_path} (data source: "
            f"{simulation.get('data_source', 'unknown')}, never a measurement)."
        )
    else:
        note = (
            f"No simulation file was found at {simulation_path}; every simulation comparison "
            f"reads {NO_SIMULATED_POINT}."
            if simulation_path is not None
            else "No simulation file was given; every simulation comparison reads "
            f"{NO_SIMULATED_POINT}."
        )
    figure_dir = results_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    relative = Path(os.path.relpath(figure_dir, out_dir)).as_posix()
    sources = {i["sidecar"]["data_source"] for i in items}
    context: dict[str, Any] = {
        "results": results_dir,
        "figures": figure_dir,
        "relative": relative,
        "waveform_root": waveform_root,
        "simulation": simulation,
        "simulation_note": note,
        "noun": "measurement" if sources == {"measured"} else "capture",
        "difference_note": MOCK_DIFFERENCE if sources == {"simulated"} else MEASURED_DIFFERENCE,
        "figure_files": [],
    }
    text = _markdown(items, summary, title, context)
    (out_dir / f"{stem}.md").write_text(text)
    banner = MOCK_BANNER if "simulated" in sources else f"Data source: {', '.join(sorted(sources))}"
    pdf = out_dir / f"{stem}.pdf"
    with tempfile.TemporaryDirectory() as work:
        render_pdf(text.replace(relative, figure_dir.as_posix()), pdf, Path(work), banner, title)
    return pdf
