"""A stub chain and a synthetic workbook for the tests of the holdout runner and the report. The
series are made by a formula here; no real data is read and nothing is simulated."""

import math

from opticps.measurement.nanf_holdout import NANF_LINK, SSMF_LINK, HoldoutPoint, HoldoutTask
from opticps.measurement.nanf_import import (
    NANF_WORKBOOK_SHA256,
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


LINK_KIND = {NANF_LINK: "NANF", SSMF_LINK: "SSMF"}
FIG1_PARAMS = {"NANF": (2.04, 0.01), "SSMF": (15.95, 0.06)}  # D at 1550 nm, slope per nm (made up)
WAVELENGTHS = tuple(1460.0 + 10.0 * k for k in range(19))  # the 19-point axis of Fig.5 and Fig.6
ROP_NANF_COLUMN = tuple(-10.0 + 0.1 * k for k in range(19))
ROP_SSMF_COLUMN = tuple(
    {3: -4.99, 5: -4.98}.get(k, -9.0 + 0.1 * k) for k in range(19)
)  # two points a hair above the -5 dBm cap (D1)


def make_stub(nanf_shift: float = -0.3):
    """A stub chain: SNR is a formula of rate and ROP, shifted by the link."""

    def stub(task: HoldoutTask) -> HoldoutPoint:
        key = task.link_key or ""
        kind = key.split("-")[1] if key.startswith("C5-") else LINK_KIND.get(key, "")
        shift = {"NANF": nanf_shift, "SSMF": -PENALTY[task.rate]}.get(kind, 0.0)
        snr = base_snr(task.rate, task.rop_dbm) + shift
        return HoldoutPoint(False, "", ber_of(snr), snr, N_BITS)

    return stub


stub_point = make_stub()


def lose_nanf_at_minus_12(task: HoldoutTask) -> HoldoutPoint:
    if task.link_key == NANF_LINK and task.rop_dbm == -12.0:
        return HoldoutPoint(True, "stub lost lock", math.nan, math.nan, 0)
    return stub_point(task)


def lose_c5(kind: str, wavelength_nm: float):
    """A stub chain that loses the C5 point of one link kind at one wavelength."""

    def runner(task: HoldoutTask) -> HoldoutPoint:
        if task.link_key == f"C5-{kind}-{wavelength_nm:g}":
            return HoldoutPoint(True, "stub lost lock", math.nan, math.nan, 0)
        return stub_point(task)

    return runner


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


def _wavelength_series(sheet, block, header, kind, unit, ys, role):
    return NanfSeries(
        series_key(sheet, block, header), sheet, kind, unit, "wavelength", "nm", WAVELENGTHS,
        tuple(ys), tuple([PointFlag.OK] * len(ys)), role, ProvenanceCategory.MEASURED, "synthetic",
    )  # fmt: skip


def fig1_d(name: str, wavelength_nm: float) -> float:
    d_1550, slope = FIG1_PARAMS[name]
    return d_1550 + slope * (wavelength_nm - 1550.0)


def fig1_series(name: str) -> NanfSeries:
    """A made-up Fig.1(a) curve: 46 knots, 1400 to 1625 nm in 5 nm steps, the axis in um."""
    nm = [1400.0 + 5.0 * k for k in range(46)]
    return NanfSeries(
        series_key("Fig.1", "a-CD", name), "Fig.1", "CD", "ps/(nm km)", "wavelength", "um",
        tuple(w / 1000.0 for w in nm), tuple(fig1_d(name, w) for w in nm),
        tuple([PointFlag.OK] * 46), DataRole.CROSS_CHECK, ProvenanceCategory.MEASURED, "synthetic",
    )  # fmt: skip


def holdout_workbook(nanf_shift: float = -0.3, sha256: str = NANF_WORKBOOK_SHA256) -> NanfWorkbook:
    out = {}
    for rate in (80, 100, 112):
        for kind in ("BER", "SNR"):
            for name, axis, role, shift in (
                ("NANF", NANF_AXIS, DataRole.HOLDOUT, nanf_shift),
                ("SMF", FULL_AXIS, DataRole.HOLDOUT, -PENALTY[rate]),
                ("B2B", FULL_AXIS, DataRole.CALIBRATION, 0.0),
            ):
                s = _series(kind, name, rate, axis, role, shift)
                out[s.key] = s
        for name, column, shift in (
            ("NANF", ROP_NANF_COLUMN, nanf_shift),
            ("SMF", ROP_SSMF_COLUMN, -PENALTY[rate]),
            ("B2B", ROP_NANF_COLUMN, 0.0),
        ):
            ys = [base_snr(rate, r) + shift + PUBLISHED_OFFSET_DB for r in column]
            s = _wavelength_series(
                "Fig.6", f"SNR@{rate}", f"{name}-{rate}-SNR", "SNR", "dB", ys, DataRole.HOLDOUT
            )
            out[s.key] = s
    for name, column in (("NANF", ROP_NANF_COLUMN), ("SSMF", ROP_SSMF_COLUMN)):
        s = _wavelength_series(
            "Fig.5", "link", f"ROP@{name}", "ROP", "dBm", column, DataRole.CALIBRATION_INPUT
        )
        out[s.key] = s
    for name in ("NANF", "SSMF"):
        s = fig1_series(name)
        out[s.key] = s
    return NanfWorkbook(sha256, out)
