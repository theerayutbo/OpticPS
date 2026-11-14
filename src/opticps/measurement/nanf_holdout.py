"""N3 part b: the freeze writer, the holdout runner and the report (plan Amendment 11 J-G).

Nothing here runs by itself and nothing here was run on real data when it was written. The module
is part of the code identity (it is an entry module of `nanf_freeze`), so an edit to it after the
freeze relocks the holdout.

`write_freeze_record` writes the record of a committed calibration artefact. `run_holdout` is the
one scoring run: `require_freeze` first, then the marker, then one read of the workbook with the
holdout and the freeze hash, then the simulation of the points with `run_point` and `curve_arrays`,
the scores C1 to C5, the B2B-copy comparator, d, the B2B gate and the verdict, which is made by
`overall_verdict` and by nothing else. The C5 links are built from the read by the recipe of
`nanf_chain.declare_c5_links` (Amendment 13 L-B); C6 to C8 are `NOT BUILT` (Amendment 11 J-F).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.measurement import nanf_chain, nanf_freeze
from opticps.measurement.nanf_chain import curve_arrays, run_point
from opticps.measurement.nanf_import import (
    NanfSeries,
    NanfWorkbook,
    read_nanf_workbook,
    series_key,
)
from opticps.measurement.nanf_scoring import (
    C1_TOL_DB,
    C2_MEAN_DB,
    C5_TOL_DB,
    RATES,
    B2bGate,
    C1Score,
    C3Score,
    C4Score,
    C5Score,
    Crossing,
    RateScores,
    SnrScore,
    b2b_copy,
    b2b_gate,
    c1_crossing,
    copy_crossing,
    d_c1,
    d_snr,
    discriminating,
    overall_verdict,
    score_c1,
    score_c2,
    score_c3,
    score_c4,
    score_c5,
)

FloatArray = NDArray[np.float64]

LABEL = "LITERATURE BENCHMARK / CALIBRATION ONLY"
NOT_BLIND = "The holdout is not fully blind"  # plan Amendment 8 G-A: every report says so
MARKER_REL = "docs/benchmarks/NANF_HOLDOUT_READ.json"
MARKER_PATH = nanf_freeze.ROOT / MARKER_REL
NANF_LINK, SSMF_LINK = "NANF-4.76km-1550", "SSMF-4.53km-1550"
C5_NOT_SIMULATED = "1630 and 1640 nm: not simulated (plan B2); C5 is scored on the 17 wavelengths"
C6_TO_C8_STATUS = "NOT BUILT"
ROP_CAP_DBM = -5.0
CALIBRATED_ROP_DBM = (-12.0, ROP_CAP_DBM)  # the calibrated ROP range (A3, A4)
# Plan Amendment 13 L-D: the script prints this when a run ends; the code does not check it.
MARKER_RULE = (
    "The holdout marker was written before the read. Commit the marker and the report now, by "
    "explicit path, before the report is read for another purpose and before any other change "
    "(plan Amendment 13 L-D). A deleted or replaced marker then shows as a change in history. The "
    "rule cannot stop a marker deleted before it was committed, a rewritten history, or anyone "
    "who controls the repository."
)


class FreezeRefusedError(RuntimeError):
    """The freeze script refuses: a record exists already, or the work tree is not the commit."""


class HoldoutAlreadyReadError(RuntimeError):
    """The holdout was read under another freeze record: no scoring follows a change of vector."""


# --- the freeze script (D4) ----------------------------------------------------------------------


def _dirty_paths(base: Path, files: list[str]) -> list[str]:
    done = nanf_freeze._git(base, "status", "--porcelain", "--untracked-files=all", "--", *files)
    if done.returncode != 0:
        raise FreezeRefusedError("git could not report the state of the work tree")
    return [line[3:] for line in done.stdout.decode("utf-8", "replace").splitlines()]


def write_freeze_record(
    artifact_path: str,
    *,
    root: Path | None = None,
    plan_path: Path | None = None,
    record_path: Path | None = None,
) -> dict[str, Any]:
    """Write the freeze record of a committed calibration artefact and return it.

    Refuses if a record exists already (one freeze), if the work tree differs from HEAD in any
    path of the code identity, the plan or the artefact, or if the artefact is not committed at
    HEAD (`build_freeze_record` raises `HoldoutLockedError`). Writes nothing on a refusal.
    """
    base = nanf_freeze.ROOT if root is None else root
    target = nanf_freeze.FREEZE_RECORD_PATH if record_path is None else record_path
    if target.exists() or target.is_symlink():
        raise FreezeRefusedError("a freeze record exists already: one freeze only")
    plan = nanf_freeze.PLAN_PATH if plan_path is None else plan_path
    files = [*nanf_freeze.identity_files(base), plan.relative_to(base).as_posix(), artifact_path]
    dirty = _dirty_paths(base, files)
    if dirty:
        raise FreezeRefusedError("the work tree differs from HEAD in: " + ", ".join(sorted(dirty)))
    record = nanf_freeze.build_freeze_record(artifact_path, plan_path=plan_path, root=root)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


# --- the points ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldoutTask:
    """One point: the link (a key of `DECLARED_LINKS` or of the C5 recipe, None for the default
    back-to-back), rate, ROP, index."""

    label: str
    link_key: str | None
    rate: int
    rop_dbm: float
    point_index: int


@dataclass(frozen=True)
class HoldoutPoint:
    """What the scoring keeps of one run: no waveform, no equaliser state."""

    lost: bool
    reason: str
    ber: float  # NaN where lost
    snr_db: float  # NaN where lost
    n_bits: int


HoldoutRunner = Callable[[HoldoutTask], HoldoutPoint]


def simulate_holdout_point(task: HoldoutTask) -> HoldoutPoint:
    """The real runner: `run_point` under the freeze record, then `curve_arrays` (scoring mode)."""
    kwargs: dict[str, Any] = {"point_index": task.point_index}
    if task.link_key is not None:
        kwargs["link"] = nanf_chain.declared_link(task.link_key)
    outcome = run_point(task.label, None, task.rate, task.rop_dbm, **kwargs)
    arrays = curve_arrays([outcome])  # refuses a result that did not run under the record
    if outcome.result is None:
        return HoldoutPoint(True, outcome.reason, math.nan, math.nan, 0)
    return HoldoutPoint(
        False, "", float(arrays.ber[0]), float(arrays.snr_db[0]), outcome.result.reading.n_bits
    )


# --- the scores ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class C5Report:
    """C5 of one rate (Amendment 13 L-C): three links, the NANF part's copy and d."""

    nanf: C5Score
    ssmf: C5Score
    b2b: C5Score
    copy: C5Score  # the published Fig.6 B2B SNR as the prediction of the NANF SNR (D3.1)
    d: float | None
    discriminating: bool
    rop_outside: tuple[int, int]  # NANF and SSMF operating points outside the calibrated ROP range
    ssmf_above_cap: int  # SSMF operating points above -5 dBm (D1)
    lost: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return bool(self.nanf.passed and self.ssmf.passed and self.b2b.passed)


@dataclass(frozen=True)
class RateReport:
    rate: int
    c1: C1Score
    c1_published: Crossing
    c1_simulated: Crossing
    c2: SnrScore
    c3: C3Score
    d_c1: float | None
    d_snr: float | None
    c1_discriminating: bool
    c2_discriminating: bool
    gate: B2bGate
    c5: C5Report
    copy_c1: C1Score
    copy_c2: SnrScore
    copy_unbracketed: tuple[float, ...]
    lost: tuple[str, ...]


@dataclass(frozen=True)
class HoldoutResult:
    rates: dict[int, RateReport]
    c4: C4Score
    verdict: str
    freeze_hash: str
    parameters: dict[str, float]
    unidentifiable: tuple[str, ...]
    lost: tuple[str, ...] = field(default=())


def _scored(series: NanfSeries) -> list[int]:
    return [i for i, x in enumerate(series.x) if x <= ROP_CAP_DBM]


def _curve(
    runner: HoldoutRunner, label: str, link: str | None, rate: int, series: NanfSeries
) -> tuple[FloatArray, list[int], list[HoldoutPoint]]:
    idx = _scored(series)
    rop = np.array([series.x[i] for i in idx])
    pts = [
        runner(HoldoutTask(f"{label}/{rate}G/{series.x[i]:g}", link, rate, series.x[i], i))
        for i in idx
    ]
    return rop, idx, pts


def _arrays(points: list[HoldoutPoint]) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
    return (
        np.array([p.ber for p in points]),
        np.array([p.snr_db for p in points]),
        np.array([not p.lost for p in points], dtype=bool),
    )


def _lost_lines(label: str, rop: FloatArray, points: list[HoldoutPoint]) -> list[str]:
    return [
        f"LOST LOCK {label} at {float(r):g} dBm: {p.reason}"
        for r, p in zip(rop, points, strict=True)
        if p.lost
    ]


def _c5_axis(series: NanfSeries) -> None:
    """The series must be on the 19-point axis of Fig.5 and Fig.6 whose first 17 points are the
    wavelengths of the recipe (plan B2, Amendment 13 L-B.5)."""
    wl = nanf_chain.C5_WAVELENGTHS_NM
    if len(series.x) != 19 or not np.allclose(series.x[: len(wl)], wl, atol=1e-6):
        raise ValueError(f"{series.key}: not the 19-point axis of plan B2 (1460 to 1640 nm)")


def _c5_rate(wb: NanfWorkbook, runner: HoldoutRunner, rate: int, gate_passed: bool) -> C5Report:
    """C5 of one rate: the NANF, SSMF and back-to-back runs at the 17 wavelengths, scored."""
    wl = np.array(nanf_chain.C5_WAVELENGTHS_NM)
    rop = {n: wb[series_key("Fig.5", "link", f"ROP@{n}")] for n in ("NANF", "SSMF")}
    pub = {
        n: wb[series_key("Fig.6", f"SNR@{rate}", f"{n}-{rate}-SNR")] for n in ("NANF", "SMF", "B2B")
    }
    for series in (*rop.values(), *pub.values()):
        _c5_axis(series)
    runs: dict[str, list[HoldoutPoint]] = {}
    lost: list[str] = []
    for kind, column in (("NANF", "NANF"), ("SSMF", "SSMF"), ("B2B", "NANF")):  # B2B at ROP@NANF
        runs[kind] = [
            runner(
                HoldoutTask(
                    f"C5-{kind}/{rate}G/{w:g}",
                    nanf_chain.c5_link_key(kind, w),
                    rate,
                    rop[column].y[k],
                    k,
                )
            )
            for k, w in enumerate(wl)
        ]
        lost += [
            f"LOST LOCK C5 {kind} at {w:g} nm, {rop[column].y[k]:g} dBm: {p.reason}"
            for k, (w, p) in enumerate(zip(wl, runs[kind], strict=True))
            if p.lost
        ]
    snr = {k: _arrays(v)[1] for k, v in runs.items()}
    ok = {k: _arrays(v)[2] for k, v in runs.items()}
    pub_snr = {n: np.array(s.y[: len(wl)]) for n, s in pub.items()}
    nanf = score_c5("nanf", wl, snr["NANF"], pub_snr["NANF"], simulated_valid=ok["NANF"])
    ssmf = score_c5("ssmf", wl, snr["SSMF"], pub_snr["SMF"], simulated_valid=ok["SSMF"])
    b2b = score_c5("b2b", wl, snr["B2B"], pub_snr["B2B"], simulated_valid=ok["B2B"])
    copy = score_c5("nanf", wl, pub_snr["B2B"], pub_snr["NANF"])  # D3.1: the copy is the B2B SNR
    d = d_snr(snr["NANF"], snr["B2B"]) if ok["NANF"].all() and ok["B2B"].all() else None
    lo, hi = CALIBRATED_ROP_DBM
    outside = tuple(
        sum(1 for r in rop[n].y[: len(wl)] if not lo <= r <= hi + 1e-9) for n in ("NANF", "SSMF")
    )
    return C5Report(
        nanf, ssmf, b2b, copy, d,
        discriminating(d, C5_TOL_DB["nanf"]) and gate_passed,
        (outside[0], outside[1]),
        sum(1 for r in rop["SSMF"].y[: len(wl)] if r > ROP_CAP_DBM),
        tuple(lost),
    )  # fmt: skip


def score_holdout(
    wb: NanfWorkbook, runner: HoldoutRunner, freeze: nanf_freeze.FreezeRecord
) -> HoldoutResult:
    """Simulate and score: C1 to C3 and C5 per rate, C4 pooled, the comparator, d and the B2B gate.

    The C5 links are declared first, from the Fig.1(a) curves of this workbook (Amendment 13 L-B).
    """
    nanf_chain.declare_c5_links(wb)

    def published(name: str, rate: int, kind: str) -> NanfSeries:
        return wb[series_key("Fig.4", f"{kind}@{rate}", f"{name}-{rate}-{kind}")]

    reports: dict[int, RateReport] = {}
    lost_all: list[str] = []
    pooled: dict[str, list[Any]] = {"rop": [], "pub": [], "sim": [], "valid": []}
    n_bits = 2 * (
        nanf_chain.CAPTURE_SYMBOLS - nanf_chain.TRAINING_SYMBOLS
    )  # F2: N_b of the capture
    for rate in RATES:
        pub = {
            n: (published(n, rate, "BER"), published(n, rate, "SNR"))
            for n in ("NANF", "SMF", "B2B")
        }
        n_rop, n_idx, n_pts = _curve(runner, "NANF", NANF_LINK, rate, pub["NANF"][0])
        s_rop, s_idx, s_pts = _curve(runner, "SSMF", SSMF_LINK, rate, pub["SMF"][0])
        f_rop, f_idx, f_pts = _curve(runner, "no-fibre", None, rate, pub["NANF"][0])
        g_rop, g_idx, g_pts = _curve(runner, "B2B", None, rate, pub["B2B"][0])
        n_ber, n_snr, n_ok = _arrays(n_pts)
        s_ber, s_snr, s_ok = _arrays(s_pts)
        f_ber, f_snr, f_ok = _arrays(f_pts)
        g_ber, g_snr, g_ok = _arrays(g_pts)
        lost = (
            _lost_lines("NANF", n_rop, n_pts)
            + _lost_lines("SSMF", s_rop, s_pts)
            + _lost_lines("no-fibre", f_rop, f_pts)
            + _lost_lines("B2B", g_rop, g_pts)
        )

        def pick(series: NanfSeries, idx: list[int]) -> FloatArray:
            return np.array([series.y[i] for i in idx])

        pub_n_ber, pub_n_snr = pick(pub["NANF"][0], n_idx), pick(pub["NANF"][1], n_idx)
        pub_s_snr = pick(pub["SMF"][1], s_idx)
        crossing_pub = c1_crossing(pub["NANF"][0].x, pub["NANF"][0].y, published=True)
        crossing_sim = c1_crossing(n_rop, n_ber, valid=n_ok)
        crossing_nofibre = c1_crossing(f_rop, f_ber, valid=f_ok)
        c3 = score_c3(
            rate, n_rop, n_snr, s_rop, s_snr, s_ber, pub_n_snr, pub_s_snr,
            nanf_valid=n_ok, ssmf_valid=s_ok,
        )  # fmt: skip
        copy = b2b_copy(pub["B2B"][0].x, pub["B2B"][1].y, pub["B2B"][0].y, n_rop)
        bracketed = ~np.isnan(copy.snr_db)  # a NANF ROP with no B2B bracket is not scored (D3.1)
        copy_c2 = (
            score_c2(n_rop[bracketed], copy.snr_db[bracketed], pub_n_snr[bracketed])
            if bracketed.any()
            else SnrScore(math.nan, math.nan, 0, False, 0, "no B2B bracket at any scored ROP")
        )
        gate = b2b_gate(
            g_snr,
            pick(pub["B2B"][1], g_idx),
            c1_crossing(g_rop, g_ber, valid=g_ok),
            c1_crossing(pub["B2B"][0].x, pub["B2B"][0].y, published=True),
            rop=g_rop,
            simulated_valid=g_ok,
        )
        both_locked = bool(n_ok.all() and f_ok.all())
        d1 = d_c1(crossing_sim, crossing_nofibre)
        d2 = d_snr(n_snr, f_snr) if both_locked else None  # d is undefined at a lost point (H3)
        c5 = _c5_rate(wb, runner, rate, gate.passed)
        lost += list(c5.lost)
        lost_all += [f"{rate} Gb/s: {line}" for line in lost]
        reports[rate] = RateReport(
            rate,
            score_c1(crossing_pub, crossing_sim),
            crossing_pub,
            crossing_sim,
            score_c2(n_rop, n_snr, pub_n_snr, simulated_valid=n_ok),
            c3,
            d1,
            d2,
            discriminating(d1, C1_TOL_DB) and gate.passed,  # B3.2: a poor gate cannot discriminate
            discriminating(d2, C2_MEAN_DB) and gate.passed,
            gate,
            c5,
            score_c1(crossing_pub, copy_crossing(copy, n_rop)),
            copy_c2,
            copy.unbracketed_snr,
            tuple(lost),
        )
        pooled["rop"] += [*n_rop, *s_rop]
        pooled["pub"] += [*pub_n_ber, *pick(pub["SMF"][0], s_idx)]
        pooled["sim"] += [*n_ber, *s_ber]
        pooled["valid"] += [*n_ok, *s_ok]
    c4 = score_c4(
        np.array(pooled["rop"]),
        np.array(pooled["pub"]),
        np.array(pooled["sim"]),
        n_bits,
        simulated_valid=np.array(pooled["valid"], dtype=bool),
    )
    return HoldoutResult(
        reports,
        c4,
        verdict_of(reports),
        freeze.freeze_hash,
        freeze.parameters.as_dict(),
        freeze.unidentifiable,
        tuple(lost_all),
    )


def verdict_of(reports: Mapping[int, RateReport]) -> str:
    """The verdict of `overall_verdict` of the scoring module and of nothing else (L-C.3)."""
    return overall_verdict(
        {
            rate: RateScores(
                bool(r.c1.passed),
                bool(r.c1_discriminating),
                bool(r.c2.passed),
                bool(r.c2_discriminating),
                bool(r.c3.passed),
                bool(r.c5.passed),
                b2b_poor=not r.gate.passed,
            )
            for rate, r in reports.items()
        }
    ).text


# --- the report (D5) -----------------------------------------------------------------------------


def build_report(result: HoldoutResult) -> str:
    """The text of the report: summary metrics only (plan section 2, rule 7), the label, the
    sentence of G-A, the verdict, the comparator, the lost points and what was not run."""
    lines = [
        "# NANF benchmark: holdout scoring",
        "",
        f"**{LABEL}**",
        "",
        f"{NOT_BLIND}: the ROP and wavelength axes and one cell of an excluded sheet were seen "
        "before the freeze (plan Amendment 8, G-A). The model is not retuned after a number is "
        "seen.",
        "",
        f"Freeze hash: `{result.freeze_hash}`. Vector: "
        + ", ".join(f"{k} {v:.6g}" for k, v in result.parameters.items())
        + ". Flagged and set to their priors (B4.4): "
        + (", ".join(result.unidentifiable) or "none")
        + ".",
        "",
        f"Verdict: **{result.verdict}**",
        "",
        "A pass would read at most as consistent with one published experiment. It is no claim"
        " of agreement with any other measurement.",
        "",
        "## Primary criteria per rate (C1, C2, C3)",
        "",
        "| Rate | C1 crossing (sim) | C1 | d(C1) | C2 mean / max dB | C2 | C3 dB | C3 | B2B gate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rate, r in result.rates.items():
        sim = r.c1_simulated
        lines.append(
            f"| {rate} Gb/s | {sim.kind} {sim.lo:.3g} | {_pf(r.c1.passed, r.c1_discriminating)} | "
            f"{_num(r.d_c1)} | {r.c2.mean_abs_db:.3g} / {r.c2.max_abs_db:.3g} | "
            f"{_pf(r.c2.passed, r.c2_discriminating)} | "
            f"{r.c3.simulated_penalty_db:.3g} | {'PASS' if r.c3.passed else 'FAIL'} | "
            f"{r.gate.label or 'ok'} |"
        )
    lines += [
        "",
        "## C5, the wavelength sweep (plan Amendment 13 L-B, L-C)",
        "",
        "| Rate | NANF mean / max dB | NANF | SSMF mean / max dB | SSMF | B2B mean / max dB | B2B "
        "| d(C5) | C5 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rate, r in result.rates.items():
        c5 = r.c5
        lines.append(
            f"| {rate} Gb/s | {_mm(c5.nanf)} | {_pf(c5.nanf.passed, c5.discriminating)} | "
            f"{_mm(c5.ssmf)} | {'PASS' if c5.ssmf.passed else 'FAIL'} | {_mm(c5.b2b)} | "
            f"{'PASS' if c5.b2b.passed else 'FAIL'} | {_num(c5.d)} | "
            f"{'PASS' if c5.passed else 'FAIL'} |"
        )
    lines += ["", C5_NOT_SIMULATED + ".", ""]
    lines += [
        f"- {rate} Gb/s: operating points outside the calibrated ROP range of 17, NANF "
        f"{r.c5.rop_outside[0]} and SSMF {r.c5.rop_outside[1]}; SSMF points above -5 dBm "
        f"(plan D1): {r.c5.ssmf_above_cap}."
        for rate, r in result.rates.items()
    ]
    lines += [
        "",
        "## B2B-copy comparator (plan A2, D3.1)",
        "",
        "The published B2B curve copied to the NANF ROPs, scored by the same rules as the model:",
        "",
    ]
    for rate, r in result.rates.items():
        gap = f", no B2B bracket at {_list(r.copy_unbracketed)}" if r.copy_unbracketed else ""
        lines.append(
            f"- {rate} Gb/s: C1 {'PASS' if r.copy_c1.passed else 'FAIL'}; "
            f"C2 mean / max {_mm(r.copy_c2)} dB, {'PASS' if r.copy_c2.passed else 'FAIL'}{gap}; "
            f"C5 NANF {_mm(r.c5.copy)} dB, {'PASS' if r.c5.copy.passed else 'FAIL'}."
        )
    lines += [
        "",
        "## Secondary and not built",
        "",
        f"- C4 (pooled, secondary): {'PASS' if result.c4.passed else 'FAIL'}, "
        f"{result.c4.n_within} of {result.c4.n_uncensored} uncensored points within 0.5 decades.",
        f"- C6, C7, C8: {C6_TO_C8_STATUS} (the OFDM chain does not exist). C6 was pre-registered "
        "as an expected FAIL at 2.0 GHz; that is an expectation and no result.",
        "",
        "## Lost-lock points (plan H1)",
        "",
    ]
    lines += [f"- {x}" for x in result.lost] if result.lost else ["- none"]
    lines += [
        "",
        "SSMF gaps, if any, are a mismatch of the model with this experiment; attributing one to "
        "chirp is a hypothesis (A1.5), not a finding.",
        "",
    ]
    return "\n".join(lines)


def _pf(passed: bool, discriminating: bool) -> str:
    """PASS or FAIL; a pass that cannot tell the model from a B2B copy says so (A2, B3.2)."""
    if not passed:
        return "FAIL"
    return "PASS" if discriminating else "PASS, NOT DISCRIMINATING"


def _mm(score: SnrScore | C5Score) -> str:
    return f"{_num(score.mean_abs_db)} / {_num(score.max_abs_db)}"


def _list(values: tuple[float, ...]) -> str:
    return ", ".join(f"{v:g}" for v in values) + " dBm"


def _num(value: float | None) -> str:
    return "undefined" if value is None or not math.isfinite(value) else f"{value:.3g}"


# --- the run (D5) --------------------------------------------------------------------------------


def _check_marker(marker: Path, freeze_hash: str) -> None:
    if marker.exists() or marker.is_symlink():
        try:
            held = json.loads(marker.read_text(encoding="utf-8"))["freeze_hash"]
        except (ValueError, KeyError, TypeError, OSError):
            raise HoldoutAlreadyReadError("the holdout marker exists and cannot be read") from None
        if held != freeze_hash:
            raise HoldoutAlreadyReadError(
                "the holdout was read under another freeze record: no second scoring run follows "
                "a change of parameters"
            )
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"freeze_hash": freeze_hash, "read": "holdout, one read, plan Amendment 11 J-G"})
        + "\n",
        encoding="utf-8",
    )


def run_holdout(
    workbook_path: str | Path,
    freeze_hash: str,
    *,
    runner: HoldoutRunner = simulate_holdout_point,
    reader: Callable[..., NanfWorkbook] = read_nanf_workbook,
    marker_path: Path | None = None,
) -> HoldoutResult:
    """The one scoring run. `require_freeze` first; then the marker, then the read, then the scores.

    A record that does not verify now, or a hash that is not its hash, ends the run before the
    marker is written and before the workbook is opened. With a record under another hash in the
    marker the run is refused.
    """
    record = nanf_freeze.require_freeze(freeze_hash)
    _check_marker(MARKER_PATH if marker_path is None else marker_path, record.freeze_hash)
    wb = reader(workbook_path, include_holdout=True, freeze_hash=freeze_hash)
    return score_holdout(wb, runner, record)
