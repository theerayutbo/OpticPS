"""A stub chain and a synthetic workbook for the tests of the holdout runner and the report. The
series are made by a formula here; no real data is read and nothing is simulated."""

import math

from opticps.measurement.nanf_holdout import NANF_LINK, SSMF_LINK, HoldoutPoint, HoldoutTask
from opticps.measurement.nanf_import import (
    DataRole,
    NanfSeries,
    NanfWorkbook,
    PointFlag,
    ProvenanceCategory,
    series_key,
)

PENALTY = {80: 5.0, 100: 11.0, 112: 14.0}
PUBLISHED_OFFSET_DB = 0.2  # the published curves differ from the stub by this much
NANF_AXIS = (-12.0, -11.0, -10.0, -9.0, -8.0, -7.0)
FULL_AXIS = tuple(-12.0 + k for k in range(11))
N_BITS = 1_294_016


def base_snr(rate: int, rop: float) -> float:
    return 12.0 + 1.2 * (rop + 12.0) - rate / 40.0


def ber_of(snr: float) -> float:
    return min(0.5, 10 ** (-snr / 6.0))


def stub_point(task: HoldoutTask) -> HoldoutPoint:
    shift = {NANF_LINK: -0.3, SSMF_LINK: -PENALTY[task.rate]}.get(task.link_key or "", 0.0)
    snr = base_snr(task.rate, task.rop_dbm) + shift
    return HoldoutPoint(False, "", ber_of(snr), snr, N_BITS)


def lose_nanf_at_minus_12(task: HoldoutTask) -> HoldoutPoint:
    if task.link_key == NANF_LINK and task.rop_dbm == -12.0:
        return HoldoutPoint(True, "stub lost lock", math.nan, math.nan, 0)
    return stub_point(task)


def _series(kind, name, rate, axis, role, shift):
    ys = []
    for rop in axis:
        snr = base_snr(rate, rop) + shift + PUBLISHED_OFFSET_DB
        ys.append(ber_of(snr) if kind == "BER" else snr)
    return NanfSeries(
        series_key("Fig.4", f"{kind}@{rate}", f"{name}-{rate}-{kind}"), "Fig.4", kind,
        "1" if kind == "BER" else "dB", "ROP", "dBm", tuple(axis), tuple(ys),
        tuple([PointFlag.OK] * len(axis)), role, ProvenanceCategory.MEASURED, "synthetic",
    )  # fmt: skip


def holdout_workbook() -> NanfWorkbook:
    out = {}
    for rate in (80, 100, 112):
        for kind in ("BER", "SNR"):
            for name, axis, role, shift in (
                ("NANF", NANF_AXIS, DataRole.HOLDOUT, -0.3),
                ("SMF", FULL_AXIS, DataRole.HOLDOUT, -PENALTY[rate]),
                ("B2B", FULL_AXIS, DataRole.CALIBRATION, 0.0),
            ):
                s = _series(kind, name, rate, axis, role, shift)
                out[s.key] = s
    return NanfWorkbook("0" * 64, out)
