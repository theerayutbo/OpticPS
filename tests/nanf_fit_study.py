"""The stub study of plan Amendment 12: does `converged` ever hold far above the known minimum?

Synthetic targets only, on the stub chain (no workbook, no simulation, no real data). Each target is
a smooth point model like `nanf_fit_stub`, with its own best vector, weights and offset, in two
variants: continuous BER and BER quantised to error counts of N_b bits. The known minimum is found
by an independent routine (SciPy `least_squares`, many starts and tight tolerances, for the
quantised variant a dense seeded sample around the continuous optimum), which is not the optimiser
under test. Rerun with `.venv/bin/python tests/nanf_fit_study.py`; the same table is asserted by
`tests/test_nanf_n3b_study.py`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

import numpy as np
from scipy.optimize import least_squares

from opticps.measurement import nanf_fit as nfit
from opticps.measurement.nanf_chain import B4_PARAMETERS
from opticps.measurement.nanf_fit import PointSummary, PointTask, RateData

N_BITS = 1_294_016
LOST_BELOW = 0.03  # the stub loses lock when the first coordinate is below this
POLISH_ABOVE = 1.03  # a converged case this far above the minimum is polished and listed apart
MARGIN = (
    0.10  # a converged case whose cost exceeds the known minimum by more is a false convergence
)


@dataclass(frozen=True)
class Case:
    name: str
    target: tuple[float, ...]
    weights: tuple[float, ...]
    offset_db: float
    quantised: bool


@dataclass(frozen=True)
class Row:
    case: Case
    evaluations: int
    converged: bool
    stopped: str
    selected: float
    known_minimum: float
    polished: float | None = None  # cost after an independent polish from the selected vector

    @property
    def ratio(self) -> float:
        return self.selected / self.known_minimum

    @property
    def false_convergence(self) -> bool:
        return self.converged and self.selected > (1.0 + MARGIN) * self.known_minimum


def cases() -> list[Case]:
    """14 targets: the stub of the fit tests, nine interior ones, four with the optimum off the box."""
    rng = np.random.default_rng(np.random.SeedSequence([20261114, 12]))
    out = [
        Case(
            "stub", (0.40, 0.60, 0.50, 0.55, 0.50, 0.45), (2.0, 1.5, 1.0, 2.5, 0.8, 3.0), 0.1, False
        )
    ]
    for k in range(9):
        out.append(
            Case(
                f"interior-{k}",
                tuple(float(x) for x in rng.uniform(0.15, 0.85, 6)),
                tuple(float(x) for x in rng.uniform(0.8, 3.0, 6)),
                float(rng.uniform(0.1, 0.5)),
                False,
            )
        )
    for k, (idx, where) in enumerate(((1, 1.3), (3, -0.3), (4, 1.2), (5, -0.2))):
        target = rng.uniform(0.25, 0.75, 6)
        target[idx] = where
        out.append(
            Case(
                f"edge-{k}",
                tuple(float(x) for x in target),
                tuple(float(x) for x in rng.uniform(0.8, 3.0, 6)),
                float(rng.uniform(0.1, 0.5)),
                False,
            )
        )
    return out + [Case(c.name, c.target, c.weights, c.offset_db, True) for c in out]


class StubModel:
    """The point model of one case: SNR falls with the weighted squared distance from the target."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self.target = np.array(case.target)
        self.weights = np.array(case.weights)

    def snr(self, rate: int, rop: float, u: np.ndarray) -> float:
        return (
            22.0
            + 1.5 * (rop + 12.0)
            - rate / 20.0
            - 8.0 * float(np.sum(self.weights * (u - self.target) ** 2))
        )

    def runner(self, task: PointTask) -> PointSummary:
        vec = dict(task.vector)
        u = np.array([(vec[s.name] - s.low) / (s.high - s.low) for s in B4_PARAMETERS])
        if u[0] < LOST_BELOW:
            return PointSummary(True, "stub lost lock", math.nan, math.nan, 0)
        snr = self.snr(task.rate, task.rop_dbm, u)
        ber = min(0.5, 10 ** (-snr / 4.0))
        if self.case.quantised:
            ber = round(ber * N_BITS) / N_BITS
        elif ber < 1e-6:
            ber = 0.0
        return PointSummary(False, "", ber, snr, N_BITS)

    def data(self) -> dict[int, RateData]:
        out = {}
        for rate in (80, 100, 112):
            rop_all = np.array([-12.0 + k for k in range(11)])
            snr_all = np.array(
                [self.snr(rate, r, self.target) + self.case.offset_db for r in rop_all]
            )
            ber_all = np.array([min(0.5, 10 ** (-s / 4.0)) for s in snr_all])
            ber_all[ber_all < 1e-5] = math.nan  # a censored cell, as the importer returns it
            keep = rop_all <= -5.0
            out[rate] = RateData(
                rate, rop_all[keep], snr_all[keep], ber_all[keep],
                tuple(range(int(keep.sum()))), rop_all, ber_all,
            )  # fmt: skip
        return out


@cache
def _smooth_optimum(
    target: tuple[float, ...], weights: tuple[float, ...], offset_db: float
) -> tuple[np.ndarray, float]:
    """The continuous-BER optimum by SciPy `least_squares`: the target and one seeded start."""
    model = StubModel(Case("smooth", target, weights, offset_db, False))
    smooth = nfit.CalibrationObjective(model.data(), model.runner)
    rng = np.random.default_rng(np.random.SeedSequence([20261114, 77]))
    lower = np.array([LOST_BELOW, 0, 0, 0, 0, 0])
    starts = [np.clip(np.array(target), lower + 1e-9, 1.0)]
    starts += [rng.uniform(lower, 1.0) for _ in range(1)]
    best_u, best_cost = starts[0], math.inf
    for x0 in starts:
        fit = least_squares(
            lambda u: smooth.residuals(nfit.to_vector(u)),
            x0, bounds=(lower + 1e-9, np.ones(6)), xtol=1e-12, ftol=1e-12, gtol=1e-12,
        )  # fmt: skip
        cost = float(np.sum(fit.fun**2))
        if cost < best_cost:
            best_u, best_cost = fit.x, cost
    return best_u, best_cost


def known_minimum(model: StubModel) -> float:
    """The lowest cost an independent routine reaches (not the optimiser under test)."""
    best_u, best_cost = _smooth_optimum(model.case.target, model.case.weights, model.case.offset_db)
    if not model.case.quantised:
        return best_cost
    # quantised BER: the cost is piecewise constant, so sample densely around the smooth optimum
    objective = nfit.CalibrationObjective(model.data(), model.runner)
    rng = np.random.default_rng(np.random.SeedSequence([20261114, 78]))
    lower = np.array([LOST_BELOW, 0, 0, 0, 0, 0])
    best = objective.cost(nfit.to_vector(best_u))
    for scale in (0.002, 0.01, 0.03):
        for _ in range(100):
            u = np.clip(best_u + rng.normal(0.0, scale, 6), lower + 1e-9, 1.0)
            best = min(best, objective.cost(nfit.to_vector(u)))
    return best


def run_case(case: Case, budget: int = nfit.SEARCH_BUDGET) -> Row:
    model = StubModel(case)
    objective = nfit.CalibrationObjective(model.data(), model.runner)
    costs: list[float] = []
    points: list[np.ndarray] = []

    def evaluate_u(u: np.ndarray) -> nfit.Evaluated:
        try:
            r = objective.residuals(nfit.to_vector(u))
        except nfit.EvaluationLostLockError:
            costs.append(math.inf)
            points.append(u)
            return math.inf, None
        costs.append(float(np.sum(r * r)))
        points.append(u)
        return costs[-1], r

    result = nfit.run_optimiser(evaluate_u, budget=budget)
    minimum, selected = known_minimum(model), min(costs)
    polished = None
    if result.converged and selected > POLISH_ABOVE * minimum:
        polished = _polish(case, points[int(np.argmin(costs))])
    return Row(
        case, result.n_evaluations, result.converged, result.stopped, selected, minimum, polished
    )


def _polish(case: Case, start: np.ndarray) -> float:
    """SciPy `least_squares` on the continuous model from the selected vector, tight tolerances."""
    model = StubModel(Case(case.name, case.target, case.weights, case.offset_db, False))
    smooth = nfit.CalibrationObjective(model.data(), model.runner)
    lower = np.array([LOST_BELOW, 0, 0, 0, 0, 0])
    fit = least_squares(
        lambda u: smooth.residuals(nfit.to_vector(u)),
        np.clip(start, lower + 1e-9, 1.0 - 1e-9), bounds=(lower + 1e-9, np.ones(6)),
        xtol=1e-12, ftol=1e-12, gtol=1e-12,
    )  # fmt: skip
    return float(np.sum(fit.fun**2))


def study(run: Callable[[Case], Row] = run_case) -> list[Row]:
    return [run(c) for c in cases()]


def main() -> int:
    rows = study()
    print(f"{'case':14}{'var':6}{'evals':>6}{'conv':>6}{'selected':>12}{'minimum':>12}{'ratio':>8}")
    for row in rows:
        c = row.case
        print(
            f"{c.name:14}{'quant' if c.quantised else 'cont':6}{row.evaluations:6d}"
            f"{'yes' if row.converged else 'no':>6}{row.selected:12.4g}{row.known_minimum:12.4g}"
            f"{row.ratio:8.3f}"
        )
    for row in rows:
        if row.polished is not None:
            print(
                f"polish from the selected vector of {row.case.name} "
                f"({'quant' if row.case.quantised else 'cont'}): cost {row.polished:.4g}, "
                f"{row.polished / row.known_minimum:.4f} x the known minimum"
            )
    done = [r for r in rows if r.converged]
    print(
        f"cases {len(rows)}; converged {len(done)}; not converged {len(rows) - len(done)}; "
        f"false convergence {sum(r.false_convergence for r in rows)}; "
        f"worst converged ratio {max((r.ratio for r in done), default=math.nan):.3f}; "
        f"most evaluations {max(r.evaluations for r in rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
