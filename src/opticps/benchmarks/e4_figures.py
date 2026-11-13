"""Reproducible figures of the external benchmark (gate E4).

Every plotted series carries one legend label, written as `<LABEL>` or `<LABEL> | detail`, where
`<LABEL>` is one of the five legend words (`LEGAL_LABELS`) or the one two-word label
`SIMULATED vs EXTERNAL RAW CAPTURE` (a simulated scenario compared with a capture). A statistic
computed from captures only is `EXTERNAL RAW CAPTURE`. A series is drawn only through `Panel`,
which refuses an unlabelled series, a label outside the set, a detail that holds another legal
word, and any label in the panel's `forbidden` set. The Wiegart and Ran panels forbid
`DIGITIZED`: this repository holds no digitised value of either article, and a figure of a source
whose reuse terms are not cleared is never redrawn.

Data sources, all committed or computed here:

* Wiegart: our own computed curves (`SIMULATED`) and the numbers the text states, as single
  points (`PUBLISHED DATA`), taken from the E3 rows (`e4_matrix.e3_result_rows`).
* Ran: only the analytical chirp-free small-signal response (`SIMULATED`); no measured point.
* TERIPHIC: the committed 2 km scoring record and scenario list only (statistics derived from the
  captures, CC BY 4.0 with attribution, see `docs/benchmarks/teriphic_e2/NOTICE.md`). No capture
  is opened and the 10 km capture is not named.

Each figure also has a pure specification (`FigureSpec.specification`: title, series labels,
evidence labels, a SHA-256 of the plotted numbers rounded to 5 significant digits). Its hash is
written into the PNG as a text chunk, so a test can bind the committed images to the code without
comparing pixels (font rendering differs between machines).

Authored independently for this repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.ticker import ScalarFormatter

from opticps.benchmarks.e4_matrix import (
    FORBIDDEN_LABELS,
    LEGAL_LABELS,
    ROW_LABELS,
    e3_result_rows,
    label_from_kinds,
)
from opticps.benchmarks.provenance import BenchmarkError

SEPARATOR = " | "
FIGURE_DIR = Path("docs/benchmarks/figures")
SPEC_KEY = "OpticPS-figure-spec-sha256"
DATA_DIGITS = 5
_TWO_KM_RECORD = "docs/benchmarks/teriphic_e2/two_km_result.json"
_SCENARIO_LIST = "docs/benchmarks/teriphic_e2/scenario_list.yaml"
TERIPHIC_ATTRIBUTION = (
    "Derived statistics of TERIPHIC PD-array dataset, Groumas et al., Zenodo "
    "10.5281/zenodo.7886498, CC BY 4.0; summaries only, no samples"
)


def series_label(kinds: tuple[str, ...], detail: str) -> str:
    """`<LABEL> | detail`, the label derived from the declared kinds of evidence."""
    return f"{label_from_kinds(kinds)}{SEPARATOR}{detail}"


def check_series_label(label: object, forbidden: tuple[str, ...] = ()) -> str:
    """Return the legal head of `label`, or raise. The detail may hold no legal word."""
    if not isinstance(label, str) or not label.strip():
        raise BenchmarkError("a plotted series needs a non-empty legend label")
    head = label.split(SEPARATOR, 1)[0]
    if head not in ROW_LABELS:
        raise BenchmarkError(f"legend label {label!r} does not start with one of {ROW_LABELS}")
    words = [w for w in LEGAL_LABELS if w in label]
    if words != [w for w in LEGAL_LABELS if w in head]:
        raise BenchmarkError(f"legend label {label!r} must hold exactly one of {ROW_LABELS}")
    if any(word in head for word in forbidden):
        raise BenchmarkError(f"legend label {head!r} is not allowed in this figure")
    return head


def _digits(values: Any) -> list[str]:
    flat = np.asarray(values, dtype=float).ravel()
    return [format(float(v), f".{DATA_DIGITS}g") for v in flat]


@dataclass
class Series:
    """One drawn series: its label, its numbers and the matrix cells it must agree with."""

    label: str
    kind: str
    x: list[str]
    y: list[str]
    kinds: tuple[str, ...]
    matrix_refs: tuple[tuple[str, str], ...]

    @property
    def evidence_label(self) -> str:
        return self.label.split(SEPARATOR, 1)[0]

    def specification(self) -> dict[str, Any]:
        numbers = json.dumps([self.x, self.y], separators=(",", ":"))
        return {
            "label": self.label,
            "evidence_label": self.evidence_label,
            "kind": self.kind,
            "evidence_kinds": list(self.kinds),
            "data_sha256": hashlib.sha256(numbers.encode("ascii")).hexdigest(),
            "matrix_refs": [list(ref) for ref in self.matrix_refs],
        }


@dataclass
class Panel:
    """An axes that draws only labelled series and remembers them."""

    ax: Axes
    forbidden: tuple[str, ...] = ()
    labels: list[str] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)

    def _register(
        self,
        kind: str,
        x: Any,
        y: Any,
        label: str,
        kinds: tuple[str, ...],
        matrix_refs: tuple[tuple[str, str], ...],
    ) -> None:
        head = check_series_label(label, self.forbidden)
        if head != label_from_kinds(kinds):
            raise BenchmarkError(f"legend label {label!r} disagrees with its kinds {kinds!r}")
        if label in self.labels:
            raise BenchmarkError(f"duplicate legend label {label!r} in one panel")
        self.labels.append(label)
        self.series.append(Series(label, kind, _digits(x), _digits(y), kinds, matrix_refs))

    def line(
        self,
        x: Any,
        y: Any,
        label: str,
        kinds: tuple[str, ...],
        matrix_refs: tuple[tuple[str, str], ...] = (),
        **kwargs: Any,
    ) -> None:
        self._register("line", x, y, label, kinds, matrix_refs)
        self.ax.plot(x, y, label=label, **kwargs)

    def points(
        self,
        x: Any,
        y: Any,
        label: str,
        kinds: tuple[str, ...],
        matrix_refs: tuple[tuple[str, str], ...] = (),
        **kwargs: Any,
    ) -> None:
        self._register("points", x, y, label, kinds, matrix_refs)
        self.ax.scatter(x, y, label=label, **kwargs)

    def bars(
        self,
        x: Any,
        heights: Any,
        width: float,
        label: str,
        kinds: tuple[str, ...],
        matrix_refs: tuple[tuple[str, str], ...] = (),
        **kwargs: Any,
    ) -> None:
        self._register("bars", x, heights, label, kinds, matrix_refs)
        self.ax.bar(x, heights, width=width, label=label, **kwargs)


def figure_texts(fig: Figure) -> list[str]:
    """Every non-empty text a reader sees, collected from the figure object itself.

    Titles, axis labels, annotations, footers, legend entries and explicitly set tick labels. The
    numeric tick labels a locator fills in at draw time are left out (they vary with the matplotlib
    version and appear only after drawing), so the result is the same before and after saving.
    """
    skipped: set[int] = set()
    fixed: list[str] = []
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            for tick in (*axis.majorTicks, *axis.minorTicks):
                skipped.update(id(t) for t in (tick.label1, tick.label2))
            skipped.add(id(axis.get_offset_text()))
            if not isinstance(axis.get_major_formatter(), ScalarFormatter):
                fixed.extend(t.get_text() for t in axis.get_ticklabels())
    found = [
        t.get_text() for t in fig.findobj(Text) if id(t) not in skipped and t.get_text().strip()
    ]
    return sorted(found + [t for t in fixed if t.strip()])


@dataclass
class FigureSpec:
    name: str
    figure: Figure
    panels: list[Panel]

    def specification(self) -> dict[str, Any]:
        """Pure description of the figure: title, series labels, evidence labels, data hashes."""
        return {
            "name": self.name,
            "texts": figure_texts(self.figure),
            "panels": [
                {
                    "title": panel.ax.get_title(),
                    "series": [series.specification() for series in panel.series],
                }
                for panel in self.panels
            ],
        }

    def specification_hash(self) -> str:
        text = json.dumps(self.specification(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("ascii")).hexdigest()


def read_png_text(path: Path) -> dict[str, str]:
    """The tEXt and zTXt chunks of a PNG file (no image library needed)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise BenchmarkError(f"{path.name} is not a PNG file")
    found: dict[str, str] = {}
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if kind == b"tEXt":
            key, _, value = body.partition(b"\x00")
            found[key.decode("latin-1")] = value.decode("latin-1")
        elif kind == b"zTXt":
            key, _, rest = body.partition(b"\x00")
            found[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
        elif kind == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            fields = rest[2:].split(b"\x00", 2)
            text = fields[2]
            found[key.decode("utf-8")] = (
                zlib.decompress(text) if rest[0:1] == b"\x01" else text
            ).decode("utf-8")
        pos += 12 + length
    return found


def _new(title: str, xlabel: str, ylabel: str, forbidden: tuple[str, ...]) -> tuple[Figure, Panel]:
    fig = Figure(figsize=(6.4, 4.2), dpi=100)
    ax = fig.subplots()
    ax.set_title(title, fontsize=9)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    return fig, Panel(ax, forbidden)


def _finish(
    fig: Figure, panel: Panel, footer: str, legend_loc: Literal["best", "upper left"] = "best"
) -> None:
    panel.ax.legend(fontsize=7, loc=legend_loc)
    fig.text(0.01, 0.01, footer, fontsize=6, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04 * (1 + footer.count("\n")), 1, 1))


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
    ids = [r.row_id for r in rows]
    panel.points(
        x,
        ours,
        series_label(("model",), "OpticPS AWGN rates"),
        ("model",),
        matrix_refs=tuple((i, "evidence_label") for i in ids),
        marker="o",
        color="tab:blue",
    )
    panel.points(
        x,
        stated,
        series_label(("published",), "number in running text"),
        ("published",),
        matrix_refs=tuple((i, "source_label") for i in ids),
        marker="D",
        color="tab:red",
        s=18,
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
            rates,
            uniform,
            series_label(("model",), f"uniform, {metric.upper()}"),
            ("model",),
            linestyle=style,
            color="k",
        )
        panel.line(
            rates,
            shaped,
            series_label(("model",), f"best symmetric PMF, {metric.upper()}"),
            ("model",),
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
            series_label(("model",), f"analytical, {length:.0f} km, {link.wavelength_nm:.0f} nm"),
            ("model",),
            matrix_refs=(("R4", "evidence_label"),),
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
        series_label(
            ("model", "capture"),
            f"best of {record['scenarios_scored']} scenarios vs 2 km capture",
        ),
        ("model", "capture"),
        matrix_refs=(("T-2KM", "evidence_label"),),
        color="tab:blue",
    )
    panel.bars(
        x + width / 2,
        [copy[k] / limits[k] for k in keys],
        width,
        series_label(("capture",), "B2B copy vs 2 km capture"),
        ("capture",),
        color="tab:gray",
    )
    panel.ax.set_xticks(x, [k.split("_")[0] for k in keys])
    panel.ax.set_ylim(0.0, 2.6)
    panel.ax.set_yticks([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    panel.ax.text(
        0.99,
        0.86,
        "limit = 1.0; 10 km: UNSPENT, not plotted",
        transform=panel.ax.transAxes,
        fontsize=7,
        ha="right",
        va="top",
    )
    _finish(fig, panel, TERIPHIC_ATTRIBUTION, legend_loc="upper left")
    return FigureSpec("teriphic_two_km_ratios", fig, [panel])


def teriphic_fibre_sensitivity(root: Path) -> FigureSpec:
    with (root / _TWO_KM_RECORD).open(encoding="utf-8") as fh:
        record = json.load(fh)
    with (root / _SCENARIO_LIST).open(encoding="utf-8") as fh:
        listed = yaml.safe_load(fh)["scenarios"]
    scored = record["scenarios"]
    fig, panel = _new(
        f"TERIPHIC 2 km, PARTIAL/FAILED: {record['scenarios_scored']} assumed fibre scenarios, "
        f"{len(record['survivors'])} passed (not a fit)",
        "assumed |D| (ps/(nm km))",
        "psi = worst metric / limit (pass needs psi <= 1)",
        (),
    )
    colours = {1.0: "tab:blue", 1.5: "tab:orange", 2.2: "tab:green"}
    for factor, colour in colours.items():
        for through, style, where in ((False, "-", "after the fibre"), (True, "--", "through it")):
            members = sorted(
                (
                    (float(sc["dispersion_ps_nm_km"]), float(scored[sc["id"]]["psi"]))
                    for sc in listed
                    if float(sc["noise_factor"]) == factor
                    and bool(sc["noise_through_fibre"]) is through
                ),
            )
            panel.line(
                [d for d, _ in members],
                [v for _, v in members],
                series_label(("model", "capture"), f"noise x{factor:g}, noise {where}"),
                ("model", "capture"),
                color=colour,
                linestyle=style,
                marker=".",
            )
    copy_psi = float(record["b2b_copy"]["psi"])
    panel.line(
        [0.0, 6.352],
        [copy_psi, copy_psi],
        series_label(("capture",), f"B2B copy vs 2 km capture, psi {copy_psi:.4f}"),
        ("capture",),
        color="tab:gray",
        linestyle=":",
    )
    panel.ax.set_ylim(0.0, 3.0)
    panel.ax.set_yticks([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
    panel.ax.text(
        0.01,
        0.97,
        f"no scenario reaches psi <= 1; lowest psi {min(v['psi'] for v in scored.values()):.4f}",
        transform=panel.ax.transAxes,
        fontsize=7,
        ha="left",
        va="top",
    )
    _finish(
        fig,
        panel,
        "Sensitivity of a failed holdout to assumed fibre scenarios (ASSUMED_G652D, zero chirp), "
        "not a fit; 10 km: UNSPENT, not plotted.\n" + TERIPHIC_ATTRIBUTION,
    )
    return FigureSpec("teriphic_fibre_sensitivity", fig, [panel])


BUILDERS = (
    wiegart_gain_check,
    wiegart_required_psnr,
    ran_chirp_free_response,
    teriphic_two_km_ratios,
    teriphic_fibre_sensitivity,
)


def build_figures(root: Path = Path(".")) -> list[FigureSpec]:
    return [build(root) for build in BUILDERS]


def save_figures(specs: list[FigureSpec], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for spec in specs:
        path = out_dir / f"{spec.name}.png"
        metadata: dict[str, str | None] = {"Software": None, SPEC_KEY: spec.specification_hash()}
        spec.figure.savefig(path, format="png", metadata=metadata)
        paths.append(path)
    return paths
