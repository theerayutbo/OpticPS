"""A stub chain for the tests of the fit driver: a smooth synthetic point model, no simulation, no
workbook and no real data. Module level so that a process pool can import it."""

import math

import numpy as np

from opticps.measurement import nanf_fit as nfit
from opticps.measurement.nanf_chain import B4_PARAMETERS
from opticps.measurement.nanf_fit import PointSummary, PointTask, RateData

TARGET = np.array([0.40, 0.60, 0.50, 0.55, 0.50, 0.45])  # the vector the stub's data was made at
WEIGHTS = np.array([2.0, 1.5, 1.0, 2.5, 0.8, 3.0])
N_BITS = 1_294_016
OFFSET_DB = 0.5  # the published data differ from the best vector, so the minimum cost is above 0


def unit(task_vector: tuple[tuple[str, float], ...]) -> np.ndarray:
    vec = dict(task_vector)
    return np.array([(vec[s.name] - s.low) / (s.high - s.low) for s in B4_PARAMETERS])


def snr_at(rate: int, rop: float, u: np.ndarray) -> float:
    return (
        22.0 + 1.5 * (rop + 12.0) - rate / 20.0 - 8.0 * float(np.sum(WEIGHTS * (u - TARGET) ** 2))
    )


def ber_of(snr: float) -> float:
    return min(0.5, 10 ** (-snr / 4.0))


def stub_runner(task: PointTask) -> PointSummary:
    """Lost lock where the transmitter bandwidth is near its lower edge; otherwise smooth."""
    u = unit(task.vector)
    if u[0] < 0.03:
        return PointSummary(True, "stub lost lock", math.nan, math.nan, 0)
    snr = snr_at(task.rate, task.rop_dbm, u)
    ber = ber_of(snr)
    if ber < 1e-6:
        ber = 0.0
    return PointSummary(False, "", ber, snr, N_BITS)


def stub_data() -> dict[int, RateData]:
    out = {}
    for rate in (80, 100, 112):
        rop_all = np.array([-12.0 + k for k in range(11)])
        snr_all = np.array([snr_at(rate, r, TARGET) + OFFSET_DB for r in rop_all])
        ber_all = np.array([ber_of(s) for s in snr_all])
        ber_all[ber_all < 1e-5] = math.nan  # a censored cell, as the importer returns it
        keep = rop_all <= -5.0
        out[rate] = RateData(
            rate,
            rop_all[keep],
            snr_all[keep],
            ber_all[keep],
            tuple(range(int(keep.sum()))),
            rop_all,
            ber_all,
        )
    return out


def objective(workers: int = 1) -> nfit.CalibrationObjective:
    return nfit.CalibrationObjective(stub_data(), stub_runner, workers)


CALLS = [0]  # number of points run in this process by `counting_runner`


def counting_runner(task: PointTask) -> PointSummary:
    CALLS[0] += 1
    return stub_runner(task)


def rough_runner(task: PointTask) -> PointSummary:
    """A cost with no structure a local search can use: the stop tolerances are never met."""
    u = unit(task.vector)
    snr = 12.0 + 8.0 * math.sin(97.3 * float(np.sum(u * np.arange(1, 7))) + task.rop_dbm)
    return PointSummary(False, "", ber_of(snr), snr, N_BITS)


def all_lost_runner(task: PointTask) -> PointSummary:
    return PointSummary(True, "stub lost lock", math.nan, math.nan, 0)
