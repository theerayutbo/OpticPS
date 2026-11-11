"""Scenarios, controls, limits, truths, outcomes and the decision rule of the E2c power study.

Pure functions of the pre-registered study plan (`docs/benchmarks/teriphic_e2c/STUDY_PLAN.md`,
design D7 to D14, D19, plan I9 to I14). Nothing here opens a file; window reads go through
`read_windows` on a capture object the caller opened (B2B through `teriphic.open_b2b`, 2 km through
`e2c_calibration`).

The verdict is `WORTH_SPENDING_10KM` iff Step 0 is viable and R6, S3, R1 and R2 hold; otherwise
`CLOSE_PARTIAL` with the first stop condition that fired. VALIDATED is never returned; BER and SER
stay REFERENCE_SEQUENCE_MISSING."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from opticps.benchmarks.e2_metrics import WindowSummary, normalise
from opticps.benchmarks.e2c_model import Law
from opticps.benchmarks.holdout import METRICS
from opticps.benchmarks.provenance import BenchmarkError

FloatArray = NDArray[np.float64]

# ---------------------------------------------------------------------------- the fixed plan
WINDOWS = {
    "fit": (0, 8388608),
    "spread": (8388608, 4194304),
    "evaluation": (16777216, 4194304),
}
STUDY_STARTS = (12582912, 20971520, 25165824, 29360128, 33554432)
STUDY_SAMPLES = 4194304
DISPERSION_GRID = (
    0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5, 4.75, 5.0, 5.25, 5.5,
    5.75, 6.0, 6.25, 6.352,
)  # fmt: skip  # the R13 grid (scenario_list.yaml), 21 values
AMPLITUDES = (0.35, 0.45, 0.55, 0.65, 0.75, 0.85)
BOUNDS = ("RX", "OPT")
CONTROLS = ("C-B2B", "C-2KM")
LENGTH_KM = 10.0
MULTIPLIER = 2.0
SEEDS = {
    "fit": 20261111,
    "prediction_symbols": 20261112,
    "prediction_noise": 20261113,
    "pseudo_capture_noise": 20261114,
    "model_spread": 20261115,
}
SOURCE_AMPLITUDE = {"b2b": 1.0, "2km": 0.832}
GATING_A = 0.45
R1_MIN_PASSES = 4  # of 5 windows
R2_MAX_PASSES = 1  # of 5 windows
R2_MAX_POOLED = 4  # of 40
WINDOW_COUNT = 5
S3_MIN_PSI = 1.0
COLLAPSE_MAX_PSI = 0.5
REACH_AMPLITUDES = (0.45, 0.65, 0.85)
REACH_D = 4.5
VIABLE_SPREADS = 3.0
CLIP_FRACTION = 1e-3
CODE_GRID_MAX_DISTINCT = 65536
CODE_GRID_TOLERANCE = 0.01
CODE_STEP_RTOL = 0.01
LIGHT = 299_792_458.0
LAMBDA_M = 1310e-9
ER_DB = 6.0
BUTTERWORTH_HZ = 45e9
BUTTERWORTH_ORDER = 4

OUTCOME_FAIL = "FAIL"
OUTCOME_PND = "PASS, NOT DISCRIMINATING"
OUTCOME_PD = "PASS, DISCRIMINATING"
VERDICT_WORTH = "WORTH_SPENDING_10KM"
VERDICT_CLOSE = "CLOSE_PARTIAL"
BER_STATUS = "REFERENCE_SEQUENCE_MISSING"
CLOSING_TEXT = (
    "H1 refuted at 2 km (R13, FAILED); H2 formed post hoc; the power study could not make a 10 km"
    " test that discriminates; claim PARTIAL; 10 km unspent."
)


# ---------------------------------------------------------------------------- window reads
class Capture(Protocol):
    def read(self, start: int, stop: int) -> FloatArray: ...


def read_windows(
    capture: Capture, names: Sequence[str], c0: float, g0: float
) -> dict[str, FloatArray]:
    """The named plan windows of one capture, B2B-normalised. Only these offsets are read."""
    out: dict[str, FloatArray] = {}
    for name in names:
        if name in WINDOWS:
            start, count = WINDOWS[name]
        elif name.startswith("study"):
            start, count = STUDY_STARTS[int(name.removeprefix("study"))], STUDY_SAMPLES
        else:
            raise BenchmarkError(f"{name!r} is not a window of the study plan")
        out[name] = normalise(capture.read(start, start + count), c0, g0)
    return out


FIT_WINDOW_NAMES = ("fit",)
STUDY_WINDOW_NAMES = tuple(f"study{k}" for k in range(len(STUDY_STARTS)))


# ---------------------------------------------------------------------------- scenarios
@dataclass(frozen=True)
class Cell:
    """One scenario: a family (law shape or control), dispersion, amplitude and noise bound."""

    family: str  # "law:poly", "law:tanh", "C-B2B" or "C-2KM"
    dispersion: float
    amplitude: float
    bound: str

    @property
    def is_law(self) -> bool:
        return self.family.startswith("law:")

    @property
    def key(self) -> str:
        return f"{self.family}|D{self.dispersion:g}|A{self.amplitude:g}|{self.bound}"


def scenario_cells(shapes: Sequence[str] = ("poly",)) -> tuple[list[Cell], list[Cell]]:
    """Law scenarios (21 D x 6 A x 2 bounds per shape) and controls (both, the same grid)."""
    grid = [(d, a, b) for d in DISPERSION_GRID for a in AMPLITUDES for b in BOUNDS]
    laws = [Cell(f"law:{s}", d, a, b) for s in shapes for d, a, b in grid]
    controls = [Cell(c, d, a, b) for c in CONTROLS for d, a, b in grid]
    return laws, controls


# ---------------------------------------------------------------------------- limits
def basis_of(tables: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """basis_m: the largest of the given metric tables (misfits and spreads), per metric."""
    if not tables:
        raise BenchmarkError("the basis needs at least one table")
    return {m: float(max(t[m] for t in tables)) for m in METRICS}


def cell_limits(basis: Mapping[str, float], spread: Mapping[str, float]) -> dict[str, float]:
    """Limit_m(A, noise) = 2.0 x max(basis_m, spread_m(A, noise)) (design D12)."""
    return {m: MULTIPLIER * max(float(basis[m]), float(spread[m])) for m in METRICS}


def spread_binds(basis: Mapping[str, float], spread: Mapping[str, float]) -> list[str]:
    return [m for m in METRICS if float(spread[m]) > float(basis[m])]


# ---------------------------------------------------------------------------- vectorised scoring
@dataclass
class Bank:
    """Stacked summaries of many predictions: one measured window is scored against all at once."""

    keys: list[str]
    gaps: FloatArray
    quantile_u: FloatArray
    quantile_p: FloatArray
    density: FloatArray
    limits: FloatArray  # (K, 4) in METRICS order
    is_law: NDArray[np.bool_]
    cells: list[Cell] = field(default_factory=list)


def stack(
    cells: Sequence[Cell],
    summaries: Mapping[str, WindowSummary],
    limits: Mapping[tuple[float, str], Mapping[str, float]],
) -> Bank:
    rows = [summaries[c.key] for c in cells]
    return Bank(
        [c.key for c in cells],
        np.array([r.gaps for r in rows]),
        np.array([r.quantile_u for r in rows]),
        np.array([r.quantile_p for r in rows]),
        np.array([r.density for r in rows]),
        np.array([[limits[(c.amplitude, c.bound)][m] for m in METRICS] for c in cells]),
        np.array([c.is_law for c in cells], dtype=bool),
        list(cells),
    )


def bank_metrics(measured: WindowSummary, bank: Bank) -> FloatArray:
    """(K, 4) metrics of `measured` against every row; equals `metrics_between` row by row."""
    m1 = np.max(np.abs(bank.gaps - measured.gaps[None, :]), axis=1)
    m2 = np.mean(np.abs(bank.quantile_u - measured.quantile_u[None, :]), axis=1)
    m3 = np.max(np.abs(bank.quantile_p - measured.quantile_p[None, :]), axis=1)
    if not ((bank.density > 0).all() and (measured.density > 0).all()):
        raise BenchmarkError("spectral distance: a power spectral density bin is not positive")
    ratio_db = 10.0 * np.log10(measured.density[None, :] / bank.density)
    m4 = np.sqrt(np.mean(ratio_db**2, axis=1))
    out = np.stack([m1, m2, m3, m4], axis=1)
    if not np.isfinite(out).all():
        raise BenchmarkError("a metric is not finite")
    return np.asarray(out, dtype=np.float64)


def bank_psi(measured: WindowSummary, bank: Bank) -> FloatArray:
    return np.asarray(np.max(bank_metrics(measured, bank) / bank.limits, axis=1), dtype=np.float64)


def outcome_of(law_survivors: int, control_survivors: int) -> str:
    """As R13 (design D10): no law survivor FAIL; a control survivor too, NOT DISCRIMINATING."""
    if law_survivors < 0 or control_survivors < 0:
        raise BenchmarkError("survivor counts cannot be negative")
    if law_survivors == 0:
        return OUTCOME_FAIL
    if control_survivors > 0:
        return OUTCOME_PND
    return OUTCOME_PD


def score_capture(measured: WindowSummary, bank: Bank) -> dict[str, Any]:
    """Outcome, survivors and best psi of one measured window against laws and controls."""
    psi = bank_psi(measured, bank)
    survive = psi <= 1.0
    law_rows = np.flatnonzero(bank.is_law)
    control_rows = np.flatnonzero(~bank.is_law)
    if law_rows.size == 0 or control_rows.size == 0:
        raise BenchmarkError("a capture is scored against both the law and the controls")
    law_survivors = [bank.cells[i] for i in law_rows if survive[i]]
    control_survivors = [bank.cells[i] for i in control_rows if survive[i]]
    return {
        "outcome": outcome_of(len(law_survivors), len(control_survivors)),
        "law_survivors": len(law_survivors),
        "control_survivors": len(control_survivors),
        "best_law_psi": float(psi[law_rows].min()),
        "best_control_psi": float(psi[control_rows].min()),
        "best_law": bank.keys[int(law_rows[np.argmin(psi[law_rows])])],
        "best_control": bank.keys[int(control_rows[np.argmin(psi[control_rows])])],
        "survivor_D": sorted({c.dispersion for c in law_survivors}),
        "survivor_A": sorted({c.amplitude for c in law_survivors}),
    }


# ---------------------------------------------------------------------------- truths
@dataclass(frozen=True)
class TruthConfig:
    family: str  # T1 to T7
    source: str  # "2km" or "b2b"
    dispersion: float
    amplitude: float
    bound: str
    law_factor: float = 1.0  # T4
    field_er_db: float | None = None  # T5
    butterworth_hz: float | None = None  # T6
    role: str = "reported"  # "R1", "R2" or "reported"

    @property
    def key(self) -> str:
        extra = ""
        if self.law_factor != 1.0:
            extra += f"|law_x{self.law_factor:g}"
        if self.field_er_db is not None:
            extra += f"|field_ER{self.field_er_db:g}dB"
        if self.butterworth_hz is not None:
            extra += f"|BW4_{self.butterworth_hz / 1e9:g}GHz"
        return (
            f"{self.family}|{self.source}|D{self.dispersion:g}|A{self.amplitude:g}|{self.bound}"
            + extra
        )


def truth_configs() -> list[TruthConfig]:
    """The 48 configurations of design D13 as read by plan I11."""
    out: list[TruthConfig] = []
    for d in (0.0, 4.5, 5.2, 6.352):
        for b in BOUNDS:
            role = "R1" if d in (0.0, 4.5, 6.352) else "reported"
            out.append(TruthConfig("T1", "2km", d, 0.45, b, role=role))
    for a in (0.65, 0.85):
        for b in BOUNDS:
            out.append(TruthConfig("T1", "2km", 4.5, a, b))
    for b in BOUNDS:
        out.append(TruthConfig("T1", "b2b", 4.5, 0.45, b))
    for family, source in (("T2", "b2b"), ("T3", "2km")):
        for d in (0.0, 4.5):
            for a in REACH_AMPLITUDES:
                for b in BOUNDS:
                    role = "R2" if a == GATING_A else "reported"
                    out.append(TruthConfig(family, source, d, a, b, role=role))
    for factor in (2.0, 0.5):
        out.append(TruthConfig("T4", "2km", 4.5, 0.45, "OPT", law_factor=factor))
    for d in (4.5, 6.352):
        out.append(TruthConfig("T5", "2km", d, 0.45, "OPT", field_er_db=ER_DB))
    for b in BOUNDS:
        out.append(TruthConfig("T6", "2km", 4.5, 0.45, b, butterworth_hz=BUTTERWORTH_HZ))
    for a in (0.30, 0.60):
        for b in BOUNDS:
            out.append(TruthConfig("T7", "2km", 4.5, a, b))
    return out


def cos_filter(x: FloatArray, fs: float, dispersion: float, length_km: float) -> FloatArray:
    """The study's own small-signal dispersion filter over the whole waveform (not e2_model's)."""
    if dispersion == 0.0 or length_km == 0.0:
        return np.asarray(x, dtype=np.float64).copy()
    f = np.fft.rfftfreq(x.size, 1.0 / fs)
    theta = np.pi * LAMBDA_M**2 * (dispersion * 1e-6) * (length_km * 1e3) * f**2 / LIGHT
    return np.asarray(np.fft.irfft(np.fft.rfft(x) * np.cos(theta), x.size), dtype=np.float64)


def field_dispersion(
    u: FloatArray,
    fs: float,
    dispersion: float,
    length_km: float,
    er_db: float,
    outer: tuple[float, float],
) -> FloatArray:
    """Large-signal field model (plan I11, T5): P = 1 + m u, field, phase dispersion, square law."""
    low, high = outer
    ratio = 10.0 ** (er_db / 10.0)
    # (1 + m high) / (1 + m low) = ratio  =>  m = (ratio - 1) / (high - ratio low)
    m = (ratio - 1.0) / (high - ratio * low)
    if not (math.isfinite(m) and m > 0):
        raise BenchmarkError("field model: no positive modulation index for this extinction ratio")
    power = 1.0 + m * np.asarray(u, dtype=np.float64)
    field_in = np.sqrt(np.maximum(power, 0.0))
    f = np.fft.fftfreq(u.size, 1.0 / fs)
    theta = np.pi * LAMBDA_M**2 * (dispersion * 1e-6) * (length_km * 1e3) * f**2 / LIGHT
    field_out = np.fft.ifft(np.fft.fft(field_in) * np.exp(-1j * theta))
    received = np.abs(field_out) ** 2
    return np.asarray((received - 1.0) / m, dtype=np.float64)


def butterworth(x: FloatArray, fs: float, cutoff_hz: float, order: int) -> FloatArray:
    """Zero-phase Butterworth magnitude 1 / sqrt(1 + (f / fc)^(2 order)) (plan I11, T6)."""
    f = np.fft.rfftfreq(x.size, 1.0 / fs)
    gain = 1.0 / np.sqrt(1.0 + (f / cutoff_hz) ** (2 * order))
    return np.asarray(np.fft.irfft(np.fft.rfft(x) * gain, x.size), dtype=np.float64)


def pseudo_capture(
    x: FloatArray,
    config: TruthConfig,
    *,
    law: Law,
    sigma_rx: float,
    fs: float,
    noise: Callable[[int, float], FloatArray],
    outer: tuple[float, float] | None = None,
) -> FloatArray:
    """One truth window from a real study window `x` (B2B-normalised), plan I11.

    `noise(n, sigma)` returns B2B-shaped noise of standard deviation sigma (seed 20261114 + window
    index, bound by the caller). `outer` gives the outer centroids of u for the T5 field model.
    """
    a_src = SOURCE_AMPLITUDE[config.source]
    is_law_truth = config.family in ("T1", "T4", "T5", "T6", "T7")
    if is_law_truth:
        u = law.inverse(x) / a_src
    elif config.family in ("T2", "T3"):
        u = np.asarray(x, dtype=np.float64) / a_src
    else:
        raise BenchmarkError(f"unknown truth family {config.family}")
    if config.field_er_db is not None:
        if outer is None:
            raise BenchmarkError("the field model needs the outer centroids of u")
        filtered = field_dispersion(u, fs, config.dispersion, LENGTH_KM, config.field_er_db, outer)
    else:
        filtered = cos_filter(u, fs, config.dispersion, LENGTH_KM)
    v = config.amplitude * filtered
    if is_law_truth:
        truth_law = law.scaled(config.law_factor) if config.law_factor != 1.0 else law
        y = truth_law.checked_apply(v)
    else:
        y = v
    if config.butterworth_hz is not None:
        y = butterworth(y, fs, config.butterworth_hz, BUTTERWORTH_ORDER)
    if config.bound == "RX":
        top_up = sigma_rx * math.sqrt(max(0.0, 1.0 - (config.amplitude / a_src) ** 2))
        if top_up > 0.0:
            y = y + noise(y.size, top_up)
    elif config.bound != "OPT":
        raise BenchmarkError(f"noise bound {config.bound!r} is not RX or OPT")
    if not np.isfinite(y).all():
        raise BenchmarkError("the pseudo-capture is not finite")
    return np.asarray(y, dtype=np.float64)


# ---------------------------------------------------------------------------- step 0
def code_step(values: FloatArray) -> dict[str, Any]:
    """Quantisation step of raw file values (plan I10): observable only on a regular grid."""
    distinct = np.unique(np.asarray(values, dtype=np.float64))
    if distinct.size < 2:
        raise BenchmarkError("code step: fewer than two distinct values")
    diffs = np.diff(distinct)
    step = float(diffs.min())
    multiples = diffs / step
    off_grid = float(np.max(np.abs(multiples - np.round(multiples))))
    observable = bool(distinct.size <= CODE_GRID_MAX_DISTINCT and off_grid <= CODE_GRID_TOLERANCE)
    return {
        "distinct_values": int(distinct.size),
        "smallest_step": step,
        "largest_off_grid": off_grid,
        "observable": observable,
    }


def code_step_changed(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool | None:
    """True or False when both steps are observable, None ("not observable") otherwise."""
    if not (a["observable"] and b["observable"]):
        return None
    sa, sb = float(a["smallest_step"]), float(b["smallest_step"])
    return bool(abs(sa - sb) > CODE_STEP_RTOL * max(sa, sb))


def clip_screen(values: FloatArray) -> dict[str, Any]:
    """Repeated extremes (plan I10): the maximum or minimum held by more than 0.1 % of samples."""
    x = np.asarray(values, dtype=np.float64)
    top, bottom = float(x.max()), float(x.min())
    n_top, n_bottom = int(np.count_nonzero(x == top)), int(np.count_nonzero(x == bottom))
    limit = CLIP_FRACTION * x.size
    return {
        "max": top,
        "min": bottom,
        "count_at_max": n_top,
        "count_at_min": n_bottom,
        "clip": bool(n_top > limit or n_bottom > limit),
    }


def viability(
    gaps_b2b: Sequence[float],
    gaps_2km: Sequence[float],
    b2b_spread_m1: float,
    any_clip: bool,
    step_changed: bool | None,
) -> dict[str, Any]:
    """The Step 0 lines V1 to V4 (design D7, plan I10). Gaps are of gain-invariant windows."""
    delta = np.asarray(gaps_2km, dtype=np.float64) - np.asarray(gaps_b2b, dtype=np.float64)
    if delta.shape != (3,):
        raise BenchmarkError("three gaps per window are needed")
    change = float(np.max(np.abs(delta)))
    lines = {
        "V1_change_exceeds_3_spreads": bool(change > VIABLE_SPREADS * b2b_spread_m1),
        "V2_top_gap_widens": bool(delta[2] > 0.0),
        "V3_no_clip": not any_clip,
        "V4_no_code_step_change": step_changed is not True,
    }
    return {
        "gap_change_signed": [float(v) for v in delta],
        "gap_change_max_abs": change,
        "three_b2b_spreads": VIABLE_SPREADS * b2b_spread_m1,
        "code_step_change": "not observable" if step_changed is None else step_changed,
        "lines": lines,
        "viable": all(lines.values()),
    }


# ---------------------------------------------------------------------------- the decision rule
def r1_holds(passes: Mapping[str, int]) -> bool:
    """R1: every T1 gating configuration PASS, DISCRIMINATING in at least 4 of 5 windows."""
    if not passes:
        raise BenchmarkError("R1 needs the T1 gating configurations")
    return all(n >= R1_MIN_PASSES for n in passes.values())


def r2_holds(passes: Mapping[str, int]) -> bool:
    """R2: every T2/T3 configuration at A 0.45 at most 1 of 5, and at most 4 of the pool."""
    if not passes:
        raise BenchmarkError("R2 needs the T2 and T3 configurations")
    return all(n <= R2_MAX_PASSES for n in passes.values()) and sum(passes.values()) <= (
        R2_MAX_POOLED
    )


def reach(
    t1_passes: Mapping[float, Sequence[int]], null_passes: Mapping[float, Sequence[int]]
) -> float | None:
    """A* of R3 (plan I14): the largest A at D 4.5 where the R1 and R2 counts hold."""
    best: float | None = None
    for a in REACH_AMPLITUDES:
        t1, null = t1_passes.get(a), null_passes.get(a)
        if not t1 or not null:
            continue
        pooled_limit = R2_MAX_POOLED * len(null) * WINDOW_COUNT / 40.0
        if (
            all(n >= R1_MIN_PASSES for n in t1)
            and all(n <= R2_MAX_PASSES for n in null)
            and sum(null) <= pooled_limit
        ):
            best = a
    return best


def decide(
    *,
    step0_viable: bool,
    r6: bool | None,
    s3: bool | None,
    r1: bool | None,
    r2: bool | None,
) -> dict[str, Any]:
    """The verdict and the first stop condition that fired (design D14, D19). None = not reached."""
    lines = [
        ("S1", "Step 0 viable", step0_viable),
        ("S2", "R6: the fitted law within the R13 limits on both evaluation windows", r6),
        ("S3", "S3: law predictions at A 0.45 separable from both controls", s3),
        (
            "S4",
            f"R1 power ({'holds' if r1 else 'fails'}) and R2 false pass"
            f" ({'holds' if r2 else 'fails'})",
            None if r1 is None or r2 is None else r1 and r2,
        ),
    ]
    for stop, text, held in lines:
        if held is not True:
            return {
                "decision": VERDICT_CLOSE,
                "stop_condition": stop,
                "failed_line": text if held is False else f"{text}: not reached",
                "closing_text": CLOSING_TEXT,
            }
    return {"decision": VERDICT_WORTH, "stop_condition": None, "failed_line": None}
