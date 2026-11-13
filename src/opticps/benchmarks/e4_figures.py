"""Reproducible figures of the external benchmark (gate E4).

Every plotted series carries exactly one legend label from `LEGAL_LABELS`, written as
`<LABEL>` or `<LABEL> | detail`. A series is drawn only through `Panel`, which refuses an
unlabelled series, a label outside the set, a label that holds two legal words, and any label
in the panel's `forbidden` set. The Wiegart and Ran panels forbid `DIGITIZED`: this repository
holds no digitised value of either article, and a figure of a source whose reuse terms are not
cleared is never redrawn.

Data sources, all committed or computed here:

* Wiegart: our own computed curves (`SIMULATED`) and the numbers the text states, as single
  points (`PUBLISHED DATA`), taken from the E3 rows (`e4_matrix.e3_result_rows`).
* Ran: only the analytical chirp-free small-signal response (`SIMULATED`); no measured point.
* TERIPHIC: the committed 2 km scoring record only (statistics derived from the captures, CC BY
  4.0 with attribution, see `docs/benchmarks/teriphic_e2/NOTICE.md`). No capture is opened and
  the 10 km capture is not named.

Authored independently for this repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from opticps.benchmarks.e4_matrix import FORBIDDEN_LABELS, LEGAL_LABELS, e3_result_rows
from opticps.benchmarks.provenance import BenchmarkError

SEPARATOR = " | "
FIGURE_DIR = Path("docs/benchmarks/figures")
TERIPHIC_ATTRIBUTION = (
    "Derived statistics of TERIPHIC PD-array dataset, Groumas et al., Zenodo "
    "10.5281/zenodo.7886498, CC BY 4.0; summaries only, no samples"
)


def check_series_label(label: object, forbidden: tuple[str, ...] = ()) -> str:
    """Return the legal word of `label`, or raise. Exactly one legal word, no other."""
    if not isinstance(label, str) or not label.strip():
        raise BenchmarkError("a plotted series needs a non-empty legend label")
    head = label.split(SEPARATOR, 1)[0]
    if head not in LEGAL_LABELS:
        raise BenchmarkError(f"legend label {label!r} does not start with one of {LEGAL_LABELS}")
    words = [w for w in LEGAL_LABELS if w in label]
    if words != [head]:
        raise BenchmarkError(f"legend label {label!r} must hold exactly one of {LEGAL_LABELS}")
    if head in forbidden:
        raise BenchmarkError(f"legend label {head!r} is not allowed in this figure")
    return head


@dataclass
class Panel:
    """An axes that draws only labelled series and remembers them."""

    ax: Axes
    forbidden: tuple[str, ...] = ()
    labels: list[str] = field(default_factory=list)

    def _register(self, label: str) -> None:
        check_series_label(label, self.forbidden)
        if label in self.labels:
            raise BenchmarkError(f"duplicate legend label {label!r} in one panel")
        self.labels.append(label)

    def line(self, x: Any, y: Any, label: str, **kwargs: Any) -> None:
        self._register(label)
        self.ax.plot(x, y, label=label, **kwargs)

    def points(self, x: Any, y: Any, label: str, **kwargs: Any) -> None:
        self._register(label)
        self.ax.scatter(x, y, label=label, **kwargs)

    def bars(self, x: Any, heights: Any, width: float, label: str, **kwargs: Any) -> None:
        self._register(label)
        self.ax.bar(x, heights, width=width, label=label, **kwargs)


@dataclass
class FigureSpec:
    name: str
    figure: Figure
    panels: list[Panel]


def _new(title: str, xlabel: str, ylabel: str, forbidden: tuple[str, ...]) -> tuple[Figure, Panel]:
    fig = Figure(figsize=(6.4, 4.2), dpi=100)
    ax = fig.subplots()
    ax.set_title(title, fontsize=9)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    return fig, Panel(ax, forbidden)


def _finish(fig: Figure, panel: Panel, footer: str) -> None:
    panel.ax.legend(fontsize=7, loc="best")
    fig.text(0.01, 0.01, footer, fontsize=6, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))


def wiegart_gain_check(root: Path) -> FigureSpec:
    wiegart, _ = e3_result_rows(root)
    rows = [r for r in wiegart if r.row_id in ("W1", "W2", "W3")]
    fig, panel = _new(
        "Wiegart rows W1-W3: PSNR gain over uniform 4-PAM at 1 bit/use (fixed peak)",
        "row",
        "PSNR gain (dB)",
        FORBIDDEN_LABELS,
    )
    x = np.arange(len(rows))
    ours = [r.result.model_value for r in rows]
    stated = [r.result.published_value for r in rows]
    panel.points(x, ours, "SIMULATED | OpticPS AWGN rates", marker="o", color="tab:blue")
    panel.points(
        x, stated, "PUBLISHED DATA | number in running text", marker="D", color="tab:red", s=18
    )
    names = ["W1 SMD, best PMF", "W2 BMD, best PMF", "W3 BMD, fixed PMF"]
    panel.ax.set_xticks(x, names, fontsize=7)
    panel.ax.set_xlim(-0.5, len(rows) - 0.5)
    for xi, o, s in zip(x, ours, stated, strict=True):
        panel.ax.annotate(
            f"ours {o:.4f}\ntext {s:.2f}",
            (xi, o),
            textcoords="offset points",
            xytext=(6, 8),
            fontsize=6,
        )
    panel.ax.set_ylim(0.5, 1.0)
    _finish(
        fig,
        panel,
        "Agreement with an analytic AWGN result (tolerance 0.01 dB), not experimental validation.",
    )
    return FigureSpec("wiegart_gain_check", fig, [panel])


def wiegart_required_psnr(root: Path) -> FigureSpec:
    from opticps.benchmarks.e3_wiegart import (
        UNIFORM_PMF,
        best_symmetric,
        required_psnr_db,
        symmetric_pmf,
    )

    del root
    rates = np.linspace(0.4, 1.6, 7)
    fig, panel = _new(
        "Own computation: peak SNR needed for a rate (AWGN, fixed peak, 4-PAM)",
        "target rate (bit per channel use)",
        "required peak SNR (dB)",
        FORBIDDEN_LABELS,
    )
    for metric, style in (("smd", "-"), ("bmd", "--")):
        uniform = [required_psnr_db(UNIFORM_PMF, float(r), metric) for r in rates]
        shaped = []
        for r in rates:
            best = best_symmetric(float(r), metric)
            shaped.append(required_psnr_db(symmetric_pmf(best.p0), float(r), metric))
        panel.line(
            rates, uniform, f"SIMULATED | uniform, {metric.upper()}", linestyle=style, color="k"
        )
        panel.line(
            rates,
            shaped,
            f"SIMULATED | best symmetric PMF, {metric.upper()}",
            linestyle=style,
            color="tab:blue",
        )
    _finish(fig, panel, "Computed by OpticPS; no value read from any figure of the article.")
    return FigureSpec("wiegart_required_psnr", fig, [panel])


def ran_chirp_free_response(root: Path) -> FigureSpec:
    from opticps.benchmarks.e3_ran import LINK_LENGTHS_KM, cited_link, small_signal_response

    link = cited_link(root)
    f_hz = np.linspace(0.0, 150e9, 1500)
    fig, panel = _new(
        "Ran link, chirp-free small-signal response (MODEL GAP: CHIRP; not a prediction)",
        "frequency (GHz)",
        "|cos(pi D L lambda^2 f^2 / c)|",
        FORBIDDEN_LABELS,
    )
    for length, colour in zip(LINK_LENGTHS_KM, ("tab:blue", "tab:orange"), strict=True):
        response = small_signal_response(
            f_hz, link.dispersion_ps_per_nm_km, length, link.wavelength_nm
        )
        panel.line(
            f_hz / 1e9,
            response,
            f"SIMULATED | analytical, {length:.0f} km, {link.wavelength_nm:.0f} nm",
            color=colour,
        )
    _finish(
        fig,
        panel,
        "Cited dispersion and wavelength only; no measured point; the real transmitter is chirped.",
    )
    return FigureSpec("ran_chirp_free_response", fig, [panel])


def teriphic_two_km_ratios(root: Path) -> FigureSpec:
    with (root / "docs/benchmarks/teriphic_e2/two_km_result.json").open(encoding="utf-8") as fh:
        record = json.load(fh)
    limits = record["limits"]
    keys = list(limits)
    best = record["scenarios"][record["best_scenario"]]["metrics"]
    copy = record["b2b_copy"]["metrics"]
    fig, panel = _new(
        "TERIPHIC 2 km holdout, scored once: outcome FAILED (pass needs every ratio <= 1)",
        "metric",
        "metric / pre-registered limit",
        (),
    )
    x = np.arange(len(keys))
    width = 0.38
    panel.bars(
        x - width / 2,
        [best[k] / limits[k] for k in keys],
        width,
        f"SIMULATED | best of {record['scenarios_scored']} scenarios vs 2 km capture",
        color="tab:blue",
    )
    panel.bars(
        x + width / 2,
        [copy[k] / limits[k] for k in keys],
        width,
        "SIMULATED | B2B copy vs 2 km capture",
        color="tab:gray",
    )
    panel.ax.set_xticks(x, [k.split("_")[0] for k in keys])
    panel.ax.set_yticks([0.0, 0.5, 1.0, 1.5, 2.0])
    panel.ax.text(
        0.99,
        0.97,
        "limit = 1.0; 10 km: UNSPENT, not plotted",
        transform=panel.ax.transAxes,
        fontsize=7,
        ha="right",
        va="top",
    )
    _finish(fig, panel, TERIPHIC_ATTRIBUTION)
    return FigureSpec("teriphic_two_km_ratios", fig, [panel])


BUILDERS = (
    wiegart_gain_check,
    wiegart_required_psnr,
    ran_chirp_free_response,
    teriphic_two_km_ratios,
)


def build_figures(root: Path = Path(".")) -> list[FigureSpec]:
    return [build(root) for build in BUILDERS]


def save_figures(specs: list[FigureSpec], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for spec in specs:
        path = out_dir / f"{spec.name}.png"
        spec.figure.savefig(path, format="png", metadata={"Software": None})
        paths.append(path)
    return paths
