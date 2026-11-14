"""N3 part b: the calibration objective, the optimiser of plan Amendment 12 and the fit driver.

Nothing here runs by itself. `fit` runs the optimiser of Amendment 12 K-B (a library search and the
certificate S1 to S4) on the Fig.4 B2B series (the only data a Tx/Rx fit may see, plan section 2)
through `evaluate`, writes an evaluation log as it goes (J-D, K-E), evaluates the selected vector
once more, then runs `check_chosen_fit`, the B4 identifiability check, the B2B gate per rate and
builds the bytes of the calibration artefact. The point runner is injected, so tests use a
stub chain; the real one is `simulate_calibration_point`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np
import scipy
from numpy.typing import NDArray
from scipy.optimize import least_squares

from opticps.measurement import nanf_chain, nanf_freeze
from opticps.measurement.nanf_chain import B4_PARAMETERS, TxRxParameters, run_point
from opticps.measurement.nanf_import import (
    NanfSeries,
    NanfWorkbook,
    calibration_partition_sha256,
    series_key,
)
from opticps.measurement.nanf_scoring import (
    RATES,
    B2bGate,
    Evaluation,
    EvaluationLog,
    EvaluationLostLockError,
    IdentifiabilityResult,
    IdentifiabilityUndefinedError,
    NoValidFitError,
    b2b_gate,
    c1_crossing,
    check_chosen_fit,
    evaluate,
    identifiability_check,
    is_censored,
    select_best,
)

FloatArray = NDArray[np.float64]

FIT_SEED = (20261101, 4101)  # Amendment 11 J-B.2
N_DESIGN = 24
BUDGET = 140  # every cost evaluation of a run, the final re-evaluation included (Amendment 12)
SEARCH_BUDGET = BUDGET - 1  # prior + design + local search; one is kept for the final re-evaluation
FD_STEP = 0.01  # forward difference step of every Jacobian, in u
LM_DAMPING_MIN = 1e-6  # the first damping tried for the step that S2 tests
N_DAMPING = 13  # dampings 1e-6, 1e-5, ..., 1e6 (times the largest diagonal of J^T J)
RHO = 0.15  # S2: largest coordinate move of the step that S2 and S3 test, in u
TAU = 0.05  # S2 to S4: the relative decrease of the cost that still counts as no progress
LIBRARY_TOL = 0.01  # ftol, xtol and gtol of the library search
LOST_RESIDUAL = 1e3  # what the library is told at a lost-lock vector (the log records +inf)
RANGE_EDGE_TOL = 0.01  # Amendment 12 J-C.1: the library keeps its iterates strictly inside the box
BER_RESIDUAL_SCALE = 0.5  # B4.2
FIT_METHOD = "latin-hypercube-24+scipy-trf-least-squares+certificate-s1-s4"
DEFAULT_LOG_PATH = nanf_freeze.ROOT / "docs/benchmarks/NANF_FIT_EVALUATION_LOG.jsonl"
STATUS_NOT_CONVERGED = "CALIBRATION NOT CONVERGED"
STATUS_NO_VALID_FIT = "NO VALID FIT"
STATUS_IDENTIFIABILITY_UNDEFINED = "IDENTIFIABILITY UNDEFINED"
STATUS_OK = "CALIBRATED"
_NAMES = tuple(s.name for s in B4_PARAMETERS)
_N = len(B4_PARAMETERS)


class FitRefusedError(RuntimeError):
    """The fit driver refuses to start or go on (a second run, a wrong axis, a changed log)."""


# --- the point runner ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PointTask:
    """One calibration point of an evaluation: rate, ROP, noise index and the vector."""

    rate: int
    rop_dbm: float
    point_index: int
    vector: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class PointSummary:
    """What the objective keeps of a run: no waveform, no equaliser state."""

    lost: bool
    reason: str
    ber: float  # NaN where lost
    snr_db: float  # NaN where lost
    n_bits: int


PointRunner = Callable[[PointTask], PointSummary]


def simulate_calibration_point(task: PointTask) -> PointSummary:
    """The real runner: one back-to-back point of the pinned chain (before any freeze)."""
    label = f"B2B/{task.rate}G/{task.rop_dbm:g}"
    outcome = run_point(
        label,
        TxRxParameters(**dict(task.vector)),
        task.rate,
        task.rop_dbm,
        point_index=task.point_index,
    )
    if outcome.result is None:
        return PointSummary(True, outcome.reason, math.nan, math.nan, 0)
    r = outcome.result
    return PointSummary(False, "", r.ber, r.snr_db, r.reading.n_bits)


# --- the calibration data and the residual vector (J-A) ------------------------------------------


@dataclass(frozen=True)
class RateData:
    """The published B2B series of one rate: the scored points (ROP at most -5 dBm) and the
    full arrays the crossing of the gate is read from."""

    rate: int
    rop: FloatArray
    snr: FloatArray
    ber: FloatArray  # NaN at a censored cell
    indices: tuple[int, ...]  # the position of each scored point on the published axis
    rop_all: FloatArray
    ber_all: FloatArray

    @property
    def censored(self) -> NDArray[np.bool_]:
        return np.asarray(is_censored(self.ber, published=True))


def _rate_data(rate: int, ber: NanfSeries, snr: NanfSeries) -> RateData:
    if ber.x != snr.x:
        raise FitRefusedError(f"the BER and SNR axes of B2B {rate} Gb/s differ")
    scored = [i for i, above in enumerate(ber.above_rop_cap) if not above]
    found = {(rate, round(ber.x[i], 9), i) for i in scored}
    declared = {
        (r, round(x, 9), k) for r, x, k in nanf_chain.DECLARED_CALIBRATION_POINTS if r == rate
    }
    if found != declared:
        raise FitRefusedError(
            f"the published B2B axis at {rate} Gb/s is not the declared calibration grid "
            "(Amendment 11 J-E.1): N3 stops and goes to the owner"
        )
    return RateData(
        rate,
        np.array([ber.x[i] for i in scored]),
        np.array([snr.y[i] for i in scored]),
        np.array([ber.y[i] for i in scored]),
        tuple(scored),
        np.array(ber.x),
        np.array(ber.y),
    )


def calibration_data(wb: NanfWorkbook) -> dict[int, RateData]:
    """The Fig.4 B2B series of the three rates from a workbook read WITHOUT the holdout."""
    out: dict[int, RateData] = {}
    for rate in RATES:
        ber = wb[series_key("Fig.4", f"BER@{rate}", f"B2B-{rate}-BER")]
        snr = wb[series_key("Fig.4", f"SNR@{rate}", f"B2B-{rate}-SNR")]
        out[rate] = _rate_data(rate, ber, snr)
    return out


def clamp_vector(values: Mapping[str, float]) -> dict[str, float]:
    """The values inside their B4 ranges (drops a last-digit overshoot of low + u (high - low))."""
    return {s.name: min(max(float(values[s.name]), s.low), s.high) for s in B4_PARAMETERS}


def to_vector(u: FloatArray) -> dict[str, float]:
    return clamp_vector(
        {s.name: s.low + float(u[i]) * (s.high - s.low) for i, s in enumerate(B4_PARAMETERS)}
    )


def to_unit(vector: Mapping[str, float]) -> FloatArray:
    return np.array([(vector[s.name] - s.low) / (s.high - s.low) for s in B4_PARAMETERS])


class CalibrationObjective:
    """The 24 calibration points of one vector, run serially or in up to `workers` processes.

    The noise stream of a point depends only on its rate and index (F4.2), so a parallel run
    returns what the serial run returns. Use as a context manager when `workers` is above 1.
    """

    def __init__(
        self,
        data: Mapping[int, RateData],
        runner: PointRunner = simulate_calibration_point,
        workers: int = 1,
    ) -> None:
        if workers < 1 or workers > 6:
            raise ValueError("workers must be 1 to 6")
        self.data = dict(data)
        self.runner = runner
        self.workers = workers
        self._pool: ProcessPoolExecutor | None = None
        self._memo: dict[tuple[float, ...], dict[int, tuple[PointSummary, ...]]] = {}

    def __enter__(self) -> CalibrationObjective:
        if self.workers > 1:
            self._pool = ProcessPoolExecutor(max_workers=self.workers)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None

    def points(self, vector: Mapping[str, float]) -> dict[int, tuple[PointSummary, ...]]:
        """All calibration points of the vector, per rate in axis order (kept for repeat calls)."""
        clamped = clamp_vector(vector)
        key = tuple(clamped[n] for n in _NAMES)
        if key not in self._memo:
            items = tuple(clamped.items())
            tasks = [
                PointTask(rate, float(rop), index, items)
                for rate in RATES
                for rop, index in zip(self.data[rate].rop, self.data[rate].indices, strict=True)
            ]
            done = (
                list(self._pool.map(self.runner, tasks))
                if self._pool is not None
                else [self.runner(t) for t in tasks]
            )
            per: dict[int, tuple[PointSummary, ...]] = {}
            start = 0
            for rate in RATES:
                n = len(self.data[rate].indices)
                per[rate] = tuple(done[start : start + n])
                start += n
            self._memo[key] = per
        return self._memo[key]

    def lost_points(self, vector: Mapping[str, float]) -> list[str]:
        per = self.points(vector)
        return [
            f"B2B {rate} Gb/s at {self.data[rate].rop[k]:g} dBm: {p.reason}"
            for rate in RATES
            for k, p in enumerate(per[rate])
            if p.lost
        ]

    def residuals(self, vector: Mapping[str, float]) -> FloatArray:
        """The vector of Amendment 11 J-A.1; `EvaluationLostLockError` on a lost point."""
        lost = self.lost_points(vector)
        if lost:
            raise EvaluationLostLockError(lost)
        per = self.points(vector)
        out: list[float] = []
        for rate in RATES:
            d, pts = self.data[rate], per[rate]
            out.extend(p.snr_db - float(d.snr[k]) for k, p in enumerate(pts))
            for k, p in enumerate(pts):
                if not d.censored[k]:
                    simulated = max(p.ber, 1.0 / p.n_bits)  # zero errors enter as 1/N_b
                    out.append(
                        (math.log10(simulated) - math.log10(float(d.ber[k]))) / BER_RESIDUAL_SCALE
                    )
        return np.array(out)

    def cost(self, vector: Mapping[str, float]) -> float:
        """Sum of the squares of the residual vector (J-A.2); a lost point raises."""
        r = self.residuals(vector)
        return float(np.sum(r * r))

    def fresh_cost(self, vector: Mapping[str, float]) -> float:
        """The cost with every point run again: nothing kept from an earlier call is used."""
        clamped = clamp_vector(vector)
        self._memo.pop(tuple(clamped[n] for n in _NAMES), None)
        return self.cost(clamped)

    def gates(self, vector: Mapping[str, float]) -> dict[int, B2bGate]:
        """The B2B fit-quality gate of B3.2 per rate at the vector (a lost point fails it, H3)."""
        per = self.points(vector)
        out: dict[int, B2bGate] = {}
        for rate in RATES:
            d, pts = self.data[rate], per[rate]
            valid = np.array([not p.lost for p in pts], dtype=bool)
            sim_snr = np.array([p.snr_db for p in pts])
            sim_ber = np.array([p.ber for p in pts])
            out[rate] = b2b_gate(
                sim_snr,
                d.snr,
                c1_crossing(d.rop, sim_ber, valid=valid),
                c1_crossing(d.rop_all, d.ber_all, published=True),
                rop=d.rop,
                simulated_valid=valid,
            )
        return out

    def censored_diagnostic(self, vector: Mapping[str, float]) -> list[str]:
        """A4: the simulated BER at each published censored cell, reported and never a term."""
        per = self.points(vector)
        lines = []
        for rate in RATES:
            d = self.data[rate]
            for k in np.flatnonzero(d.censored):
                p = per[rate][int(k)]
                text = (
                    "lost lock"
                    if p.lost
                    else f"{p.ber:.3g} ({'below' if p.ber < 1e-4 else 'NOT below'} 1e-4)"
                )
                lines.append(f"B2B {rate} Gb/s at {d.rop[int(k)]:g} dBm: simulated BER {text}")
        return lines


# --- the optimiser (J-B) -------------------------------------------------------------------------


@dataclass(frozen=True)
class OptimiserResult:
    converged: bool
    n_evaluations: int
    stopped: str


class _BudgetExhaustedError(Exception):
    pass


# One evaluation: the cost (+inf for a lost-lock vector) and the residual vector (None if lost).
Evaluated = tuple[float, FloatArray | None]


def latin_hypercube(n: int = N_DESIGN, dim: int = _N, seed: Sequence[int] = FIT_SEED) -> FloatArray:
    """J-B.2: per parameter `permutation(n)` then `random(n)`; point k is (perm + rnd) / n."""
    rng = np.random.default_rng(np.random.SeedSequence(list(seed)))
    cols = []
    for _ in range(dim):
        perm = rng.permutation(n)
        rnd = rng.random(n)
        cols.append((perm + rnd) / n)
    return np.stack(cols, axis=1)


def _lowest(
    seen: Sequence[tuple[float, FloatArray, FloatArray]],
) -> tuple[float, FloatArray, FloatArray]:
    """The lowest finite cost of the evaluations so far, ties by evaluation order (J-C.1)."""
    return min(seen, key=lambda e: e[0])


def tested_step(u: FloatArray, r: FloatArray, jac: FloatArray) -> tuple[FloatArray, float]:
    """S2 of Amendment 12: the damped step with the smallest damping that stays within RHO, and the
    relative decrease of the cost that the linear model predicts for it."""
    grad, info = jac.T @ r, jac.T @ jac
    # variables pushed outward by the descent direction at a range edge stay where they are
    free = [
        i for i in range(_N) if not ((u[i] <= 0.0 and grad[i] > 0) or (u[i] >= 1.0 and grad[i] < 0))
    ]
    smallest = u.copy()
    if free:
        sub = info[np.ix_(free, free)]
        level = max(float(np.max(np.diag(info))), 1e-300)
        for k in range(N_DAMPING):
            try:
                move = np.linalg.solve(
                    sub + LM_DAMPING_MIN * 10.0**k * level * np.eye(len(free)), -grad[free]
                )
            except np.linalg.LinAlgError:
                continue
            trial = u.copy()
            trial[free] += move
            smallest = np.clip(trial, 0.0, 1.0)
            if float(np.max(np.abs(move))) <= RHO:  # the step before the clip to the box
                break
    after = r + jac @ (smallest - u)
    rr = float(r @ r)
    return smallest, (rr - float(after @ after)) / rr if rr > 0.0 else 0.0


def run_optimiser(
    evaluate_u: Callable[[FloatArray], Evaluated], *, budget: int = SEARCH_BUDGET
) -> OptimiserResult:
    """Prior, Latin hypercube, then rounds of a library search and a certificate (Amendment 12 J-B).

    At most `budget` calls of `evaluate_u` (u in [0, 1]^6); a vector that repeats an earlier one
    exactly is answered from the log and is no new evaluation. Deterministic: no randomness besides
    the seeded design. `converged` only when S1 to S4 hold: a full finite-difference Jacobian at a
    point, a predicted and an evaluated decrease of at most TAU from it, and nothing in the whole
    log that beats the point by more than TAU.
    """
    count = 0
    seen: list[tuple[float, FloatArray, FloatArray]] = []  # finite evaluations, in order
    known: dict[bytes, Evaluated] = {}

    def call(u: FloatArray) -> Evaluated:
        nonlocal count
        clipped = np.clip(u, 0.0, 1.0)
        key = clipped.tobytes()
        if key in known:
            return known[key]
        if count >= budget:
            raise _BudgetExhaustedError
        count += 1
        f_c, r_c = evaluate_u(clipped)
        known[key] = (f_c, r_c)
        if r_c is not None and math.isfinite(f_c):
            seen.append((f_c, clipped, r_c))
        return f_c, r_c

    try:
        prior = np.array([(s.prior - s.low) / (s.high - s.low) for s in B4_PARAMETERS])
        for design_u in [prior, *latin_hypercube()]:
            call(design_u)
        if not seen:
            return OptimiserResult(False, count, STATUS_NO_VALID_FIT)
        n_residuals = len(seen[0][2])
        f, u, r = _lowest(seen)

        def lenient(rv: FloatArray | None) -> FloatArray:
            return np.full(n_residuals, LOST_RESIDUAL) if rv is None else rv

        def residuals_for_library(v: FloatArray) -> FloatArray:
            return lenient(call(v)[1])

        def finite_difference(at: FloatArray, *, library: bool) -> FloatArray | None:
            """Forward differences of the residual vector, six evaluations (backward at the upper
            edge). `library`: a lost probe is a penalty vector; otherwise it returns None."""
            _, r_at = call(at)
            base = lenient(r_at)
            columns = []
            for i in range(_N):
                v = at.copy()
                v[i] += FD_STEP if at[i] + FD_STEP <= 1.0 else -FD_STEP
                _, rv = call(v)
                if rv is None and not library:
                    return None
                columns.append((lenient(rv) - base) / (v[i] - at[i]))
            return np.stack(columns, axis=1)

        while True:
            before = count
            least_squares(
                residuals_for_library, u, jac=lambda v: finite_difference(v, library=True),
                bounds=(0.0, 1.0), method="trf", ftol=LIBRARY_TOL, xtol=LIBRARY_TOL,
                gtol=LIBRARY_TOL, x_scale=1.0, loss="linear", tr_solver="exact", max_nfev=None,
            )  # fmt: skip
            f, u, r = _lowest(seen)
            jac = finite_difference(u, library=False)  # S1: a full finite-difference Jacobian here
            if jac is None:
                return OptimiserResult(False, count, "a Jacobian point lost lock")
            smallest, predicted = tested_step(u, r, jac)  # S2
            if np.any(smallest != u):  # S3: the cost at the tested step is evaluated
                call(smallest)
            # S4: nothing in the whole log beats the point by more than TAU
            if predicted <= TAU and _lowest(seen)[0] >= (1.0 - TAU) * f:
                return OptimiserResult(True, count, "converged: S1 to S4 hold")
            top = _lowest(seen)
            if count == before and top[0] >= f:
                return OptimiserResult(False, count, "no step lowers the cost: search stalled")
            f, u, r = top
    except _BudgetExhaustedError:
        return OptimiserResult(False, count, "budget ended before S1 to S4 held")


# --- the evaluation log (J-D) --------------------------------------------------------------------


def _line(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"


def _number(value: float) -> float | str:
    return "inf" if value == math.inf else value


def _read_number(value: float | str) -> float:
    return math.inf if value == "inf" else float(value)


@dataclass
class _Journal:
    """The evaluations recorded by an earlier part of this run, replayed in order."""

    path: Path
    recorded: list[dict[str, Any]] = field(default_factory=list)

    def append(self, ev: Evaluation, index: int, residuals: FloatArray | None) -> None:
        entry = {
            "i": index,
            "vector": dict(ev.vector),
            "objective": _number(ev.objective),
            "lost": list(ev.lost),
            "residuals": None if residuals is None else [float(x) for x in residuals],
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_line(entry))
            handle.flush()


FIT_SCRIPT_PATH = nanf_freeze.ROOT / "scripts/nanf_fit.py"


def fit_identity() -> dict[str, str]:
    """What the log header binds besides the plan and the code identity (Amendment 12 J-D): the
    SHA-256 of this module and of the fit script, and the versions of the two libraries whose
    routines choose the evaluations."""
    return {
        "fit_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fit_script_sha256": hashlib.sha256(FIT_SCRIPT_PATH.read_bytes()).hexdigest(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
    }


def _open_journal(path: Path, header: Mapping[str, Any]) -> _Journal:
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            first = json.loads(lines[0])
            entries = [json.loads(x) for x in lines[1:]]
        except (ValueError, IndexError):
            raise FitRefusedError(
                "the evaluation log exists and cannot be read: not a resume"
            ) from None
        if first != dict(header):
            raise FitRefusedError(
                "an evaluation log of another run exists (plan, code or seed differ): "
                "one run only, and no second run is started (Amendment 11 J-D)"
            )
        return _Journal(path, entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_line(header), encoding="utf-8")
    return _Journal(path)


# --- the driver ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FitOutcome:
    status: str
    converged: bool
    n_evaluations: int
    log: EvaluationLog
    chosen: Evaluation | None = None
    identifiability: IdentifiabilityResult | None = None
    gates: dict[int, B2bGate] = field(default_factory=dict)
    at_range_edge: tuple[str, ...] = ()
    censored_diagnostic: tuple[str, ...] = ()
    artefact: bytes | None = None

    @property
    def lines(self) -> list[str]:
        return self.log.lines()


def fit(
    objective: CalibrationObjective,
    *,
    log_path: Path,
    plan_sha256: str,
    code_identity: str,
    partition: str | None = None,
    budget: int = BUDGET,
    fit_code: Mapping[str, str] | None = None,
) -> FitOutcome:
    """Run the one fit of Amendments 11 and 12. Refuses a second run; a log of the same run is
    replayed. `budget` counts every cost evaluation, the final re-evaluation included."""
    if nanf_freeze.freeze_record_present():
        raise FitRefusedError("a freeze record exists: the calibration is closed")
    header = {
        "plan_sha256": plan_sha256,
        "code_identity": code_identity,
        "seed": list(FIT_SEED),
        "budget": budget,
        "method": FIT_METHOD,
        **(fit_identity() if fit_code is None else fit_code),
    }
    journal = _open_journal(log_path, header)
    log = EvaluationLog()

    def evaluate_u(u: FloatArray) -> Evaluated:
        vector = to_vector(u)
        n = len(log.evaluations)
        if n < len(journal.recorded):  # a resume: replay, never restart
            rec = journal.recorded[n]
            if rec["vector"] != vector or rec["i"] != n:
                raise FitRefusedError(f"evaluation {n} of the log is not the one this run asks for")
            resid = None if rec["residuals"] is None else np.array(rec["residuals"], dtype=float)
            recorded = _read_number(rec["objective"])
            if (resid is None) != bool(rec["lost"]) or (resid is None) != (recorded == math.inf):
                raise FitRefusedError(f"evaluation {n} of the log: lost points and cost disagree")
            if resid is not None and recorded != float(np.sum(resid * resid)):
                raise FitRefusedError(f"evaluation {n} of the log: the cost is not its residuals'")
            ev = log.record(Evaluation(vector, recorded, tuple(rec["lost"])))
            return ev.objective, resid
        held: list[FloatArray] = []

        def cost(values: Mapping[str, float]) -> float:
            r = objective.residuals(values)  # raises EvaluationLostLockError on a lost point
            held.append(r)
            return float(np.sum(r * r))

        ev = evaluate(log, vector, cost)
        resid = held[0] if held else None
        journal.append(ev, n, resid)
        return ev.objective, resid

    result = run_optimiser(evaluate_u, budget=budget - 1)
    if len(journal.recorded) > len(log.evaluations):
        raise FitRefusedError("the log holds more evaluations than this run asks for")
    n_eval = len(log.evaluations)
    if not result.converged:
        status = (
            STATUS_NO_VALID_FIT if result.stopped == STATUS_NO_VALID_FIT else STATUS_NOT_CONVERGED
        )
        return FitOutcome(status, False, n_eval, log)
    try:
        chosen = check_chosen_fit(select_best(log))
        if objective.fresh_cost(chosen.vector) != chosen.objective:  # the same cost, bit for bit
            raise FitRefusedError(
                "the selected vector, evaluated again, does not give the logged cost: refused"
            )
        ident = identifiability_check(lambda values: objective.residuals(values), chosen.vector)
    except NoValidFitError:
        return FitOutcome(STATUS_NO_VALID_FIT, True, n_eval, log)
    except IdentifiabilityUndefinedError:
        return FitOutcome(STATUS_IDENTIFIABILITY_UNDEFINED, True, n_eval, log, chosen)
    hashed = clamp_vector(ident.vector)
    gates = objective.gates(hashed)
    unit = to_unit(hashed)
    edge = tuple(
        s.name
        for i, s in enumerate(B4_PARAMETERS)
        if unit[i] <= RANGE_EDGE_TOL or unit[i] >= 1.0 - RANGE_EDGE_TOL
    )
    n_points = sum(len(objective.data[r].indices) for r in RATES)
    artefact = nanf_freeze.calibration_artifact(
        TxRxParameters(**hashed),
        ident.flagged,
        {
            "method": FIT_METHOD,
            "converged": True,
            "n_evaluations": n_eval,
            "n_calibration_points": n_points,
            "cost": chosen.objective,
        },
        calibration_partition_sha256() if partition is None else partition,
        {
            "chosen_fit_checked": True,
            "n_lost_points_in_grid": 0,
            "identifiability_eigenvalues": [float(v) for v in ident.eigenvalues],
            "evaluation_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        },
    )
    return FitOutcome(
        STATUS_OK,
        True,
        n_eval,
        log,
        chosen,
        ident,
        gates,
        edge,
        tuple(objective.censored_diagnostic(hashed)),
        artefact,
    )
