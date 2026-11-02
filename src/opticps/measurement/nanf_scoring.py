"""NANF benchmark: the metric and criterion scoring functions C1 to C8, the B2B-copy comparator, the
discriminating measure d, the B2B fit-quality gate, the verdict rule, and the identifiability check
of plan A1.7 / B4 (LITERATURE BENCHMARK / CALIBRATION ONLY).

These are pure functions of arrays. They read no workbook and import none: in Gate N3 part a they
are exercised on synthetic series only. Each function follows the plan text it names (original
sections 3 and 4, Amendments 1 to 5); where the text left a case open, Amendment 5 F7 declares it
and the docstring says so. Tolerances are the plan's and are not parameters of the verdict.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from opticps.measurement.nanf_chain import B4_PARAMETERS, ParameterSpec

FloatArray = NDArray[np.float64]

BER_THRESHOLD = 3.8e-3
BER_CENSOR_FLOOR = 1e-5
ROP_CAP_DBM = -5.0
RATES = (80, 100, 112)
STATED_PENALTY_DB = {80: 5.0, 100: 11.0, 112: 14.0}  # paper prose, "around" (plan C3)
C1_TOL_DB = 1.0
C2_MEAN_DB, C2_MAX_DB = 1.5, 3.0
C3_TOL_DB = 3.0
C4_LOG_TOL, C4_FRACTION = 0.5, 0.8
C5_TOL_DB = {"nanf": 2.0, "ssmf": 3.0, "b2b": 2.0}
C5_WAVELENGTHS_NM = tuple(1460.0 + 10.0 * k for k in range(17))  # 1460 to 1620 (B2)
C5_REPORTED_ONLY_NM = (1630.0, 1640.0)  # reported apart, never scored (B2, F7.5)
C7_SUBCARRIERS = 240
C6_TOL_GHZ = 2.0
C6_WINDOW_GHZ = (20.0, 32.8125)
C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 10.0, 0.10
C8_TOL_DB = {"nanf": 2.0, "ssmf": 3.0}
B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.0, 2.0, 0.5


class InvalidDataError(ValueError):
    """A value that cannot be data: refused, and it never contributes to a pass (Amendment 6 G3)."""


def _arr(values: Sequence[float] | FloatArray, name: str) -> FloatArray:
    a = np.asarray(values, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return a


def _as_valid(valid: Sequence[bool] | NDArray[np.bool_] | None, n: int) -> NDArray[np.bool_]:
    """The mask of locked points of a simulated curve (Amendment 7). None: every point is locked.

    A mask must be a real boolean array of the right length: a truthy string or a number is refused.
    """
    if valid is None:
        return np.ones(n, dtype=bool)
    mask = np.asarray(valid)
    if mask.dtype != np.bool_ or mask.shape != (n,):
        raise ValueError("a validity mask must be a boolean array with one entry per point")
    return mask


def _scored(rop: FloatArray, *columns: NDArray[Any]) -> tuple[NDArray[Any], ...]:
    """Drop ROP above the -5 dBm cap (plan A4) and require a strictly rising finite axis."""
    if rop.size == 0 or not np.all(np.isfinite(rop)):
        raise ValueError("the ROP axis must be non-empty and finite")
    for c in columns:
        if c.size != rop.size:
            raise ValueError("series must have one value per ROP point")
    if np.any(np.diff(rop) <= 0):
        raise ValueError("the ROP axis must be strictly increasing")
    keep = rop <= ROP_CAP_DBM
    return (rop[keep], *(c[keep] for c in columns))


def is_censored(ber: float | FloatArray, *, published: bool = False) -> NDArray[np.bool_]:
    """Which BER values are censored (plan A3, F7.1 as corrected by Amendment 6 G3).

    Only a finite BER in [0, 1) below 1e-5 is censored (zero included). Infinity, a negative value
    or a value above 1 is invalid data (`InvalidDataError`). NaN is invalid for a simulated or
    derived BER; for a published series (`published=True`) NaN is the importer's flagged censored
    cell (zero, below 1e-5 or "-Inf" in the workbook) and counts as censored.
    """
    b = np.asarray(ber, dtype=float)
    nan = np.isnan(b)
    if (nan.any() and not published) or np.any(np.isinf(b)):
        raise InvalidDataError("a BER is not finite")
    finite = b[~nan]
    if np.any(finite < 0) or np.any(finite > 1):
        raise InvalidDataError("a BER lies outside [0, 1]")
    return np.asarray(nan | (b < BER_CENSOR_FLOOR))


# --- C1: the crossing rule (A3, B1, C1-R) --------------------------------------------------------

Kind = Literal["point", "left", "right", "interval", "invalid"]
_KINDS = ("point", "left", "right", "interval", "invalid")


@dataclass(frozen=True)
class Crossing:
    """A crossing of BER 3.8e-3 on the ROP axis: a point, a bound, or an interval (all in dBm).

    point: lo == hi. left ("at or below r0"): region (-inf, r0]. right ("above r0"): [r0, inf).
    interval: [lo, hi]. invalid: the curve held invalid data, lo and hi are NaN and it never scores.
    The fields are validated: an unknown kind, a non-numeric or NaN field (except invalid) or an
    infinite point is refused.
    """

    kind: Kind
    lo: float
    hi: float
    n_lost: int = 0  # lost-lock points among the scored ROPs of the curve (Amendment 7), reported
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown crossing kind {self.kind!r}")
        if isinstance(self.n_lost, bool) or not isinstance(self.n_lost, int) or self.n_lost < 0:
            raise ValueError("n_lost must be a non-negative integer")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        for v in (self.lo, self.hi):
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise ValueError("crossing fields must be numbers")
        lo, hi = self.lo, self.hi
        if self.kind == "invalid":
            ok = math.isnan(lo) and math.isnan(hi)
        elif math.isnan(lo) or math.isnan(hi):
            ok = False
        elif self.kind == "point":
            ok = math.isfinite(lo) and lo == hi
        elif self.kind == "left":
            ok = lo == -math.inf and math.isfinite(hi)
        elif self.kind == "right":
            ok = math.isfinite(lo) and hi == math.inf
        else:
            ok = math.isfinite(lo) and math.isfinite(hi) and lo <= hi
        if not ok:
            raise ValueError(f"the fields do not describe a {self.kind} crossing: {lo}, {hi}")

    @property
    def x(self) -> float:
        if self.kind != "point":
            raise ValueError("only a point crossing has a single value")
        return self.lo


def c1_crossing(
    rop: Sequence[float] | FloatArray,
    ber: Sequence[float] | FloatArray,
    threshold: float = BER_THRESHOLD,
    *,
    published: bool = False,
    valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> Crossing:
    """The ROP at which BER crosses `threshold`, by rule C1-R (Amendment 3), at most -5 dBm.

    P is the last uncensored point. If P is below the threshold: the crossing is the linear
    interpolation of log10 BER against ROP in the last downward bracket (highest ROP) of two
    adjacent uncensored points, or, with no such bracket, a left-censored bound at the first scored
    ROP. If P is above: with a censored point after P, the interval [ROP of P, ROP of the first
    censored point after P]; otherwise the right-censored bound "above ROP of P". Adjacent means
    adjacent among the uncensored points (A3: "keep those uncensored and scored"). A value equal to
    the threshold counts as above. With no uncensored point the curve is left-censored.

    Invalid data (Amendment 6 G3) gives `Crossing("invalid")`, which fails: see `is_censored`.
    `published=True` is for a published series, where NaN is a flagged censored cell.

    `valid` marks the locked points of a simulated curve (Amendment 7). A lost-lock point is never
    scored and never skipped silently. The crossing is computed only from the highest contiguous
    run of locked points, which must bracket the threshold by C1-R as a point. Lost points below
    that run (the noise-limited side) do not affect it and are counted in `n_lost`. A lost point
    above the run, no locked point, or no bracket among the locked points gives
    `Crossing("invalid")`, which fails (the no-crossing rule). Nothing is interpolated across a
    lost point.
    """
    rop_a, ber_a = _arr(rop, "rop"), _arr(ber, "ber")
    mask = _as_valid(valid, rop_a.size) if rop_a.size == ber_a.size else None
    if mask is None:
        raise ValueError("series must have one value per ROP point")
    r, b, locked = _scored(rop_a, ber_a, mask)
    if r.size == 0:
        raise ValueError("no scored point (every ROP is above the cap)")
    n_lost = int(np.count_nonzero(~locked))
    if n_lost:
        if not locked.any():
            return Crossing("invalid", math.nan, math.nan, n_lost, "every point lost lock")
        if not locked[-1]:
            return Crossing(
                "invalid", math.nan, math.nan, n_lost, "a lost-lock point lies above the locked run"
            )
        first = int(np.flatnonzero(~locked)[-1]) + 1
        inner = c1_crossing(r[first:], b[first:], threshold, published=published)
        if inner.kind != "point":
            why = "invalid data" if inner.kind == "invalid" else "no bracket among locked points"
            return Crossing("invalid", math.nan, math.nan, n_lost, why)
        return Crossing("point", inner.lo, inner.hi, n_lost, "locked run brackets the threshold")
    try:
        censored = is_censored(b, published=published)
    except InvalidDataError:
        return Crossing("invalid", math.nan, math.nan)
    unc = np.flatnonzero(~censored)
    if unc.size == 0:
        return Crossing("left", -math.inf, float(r[0]))
    last = int(unc[-1])
    if b[last] < threshold:
        log_t = math.log10(threshold)
        for a, c in zip(unc[-2::-1], unc[:0:-1], strict=False):  # pairs, highest ROP first
            if b[a] >= threshold and b[c] < threshold:
                la, lc = math.log10(b[a]), math.log10(b[c])
                x = float(r[a] + (log_t - la) / (lc - la) * (r[c] - r[a]))
                return Crossing("point", x, x)
        return Crossing("left", -math.inf, float(r[0]))
    after = np.flatnonzero(censored[last + 1 :])
    if after.size:
        return Crossing("interval", float(r[last]), float(r[last + 1 + int(after[0])]))
    return Crossing("right", float(r[last]), math.inf)


def _widened(c: Crossing, tol: float) -> tuple[float, float]:
    return (
        c.lo - tol if math.isfinite(c.lo) else -math.inf,
        c.hi + tol if math.isfinite(c.hi) else math.inf,
    )


@dataclass(frozen=True)
class C1Score:
    passed: bool
    reason: str
    both_points: bool  # a discriminating verdict needs a point crossing on both sides
    n_lost: int = 0  # lost-lock points of the simulated curve, reported (Amendment 7)


def score_c1(published: Crossing, simulated: Crossing, tol: float = C1_TOL_DB) -> C1Score:
    """Score a simulated crossing against a published one (A3, B1.3; F7.2 and Amendment 6 G2).

    The published region is widened by `tol` on each finite side. A simulated point must lie in
    it. If the published crossing is a point and the simulated curve has no crossing in the common
    ROP range (a left or right bound), the criterion FAILs: B1.3 governs and F7.2's reading of a
    bound at its first or last ROP does not apply to a published point. A simulated interval passes
    if any part of it lies in the widened region. A simulated bound against a published bound or
    interval is read at its ROP. A crossing from invalid data fails on either side.
    """
    if published.kind == "invalid" or simulated.kind == "invalid":
        why = simulated.reason or published.reason
        return C1Score(False, "invalid data" + (f": {why}" if why else ""), False, simulated.n_lost)
    lo, hi = _widened(published, tol)
    both = published.kind == "point" and simulated.kind == "point"
    if simulated.kind == "point":
        ok = lo <= simulated.lo <= hi
        return C1Score(
            ok,
            "crossing inside the accepted region" if ok else "crossing outside",
            both,
            simulated.n_lost,
        )
    if simulated.kind == "interval":
        ok = simulated.lo <= hi and simulated.hi >= lo
        return C1Score(ok, "interval meets the accepted region" if ok else "interval outside", both)
    if published.kind == "point":
        return C1Score(False, "no crossing in the simulated scored range", both)
    x = simulated.hi if simulated.kind == "left" else simulated.lo
    ok = lo <= x <= hi
    return C1Score(ok, "bound read at its ROP lies in the region" if ok else "bound outside", both)


# --- C2, C8, C5: mean absolute SNR error ---------------------------------------------------------


@dataclass(frozen=True)
class SnrScore:
    mean_abs_db: float
    max_abs_db: float
    n_points: int
    passed: bool
    n_invalid: int = 0  # lost-lock points at scored ROPs: any one fails the criterion (Amendment 7)
    reason: str = ""


def score_c2(
    rop: Sequence[float] | FloatArray,
    simulated_snr: Sequence[float] | FloatArray,
    published_snr: Sequence[float] | FloatArray,
    *,
    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> SnrScore:
    """C2: mean |error| at most 1.5 dB and no single |error| above 3.0 dB, on ROP at most -5 dBm.

    A lost-lock point at a scored ROP (`simulated_valid` False) fails the criterion: it is counted,
    never substituted and never interpolated across (Amendment 7).
    """
    rop_a = _arr(rop, "rop")
    r, s, p, ok_pts = _scored(
        rop_a,
        _arr(simulated_snr, "sim"),
        _arr(published_snr, "pub"),
        _as_valid(simulated_valid, rop_a.size),
    )
    if r.size == 0:
        raise ValueError("no scored point")
    if not ok_pts.all():
        k = int(np.count_nonzero(~ok_pts))
        return SnrScore(
            math.nan, math.nan, int(r.size), False, k, "lost-lock point at a scored ROP"
        )
    if not (np.all(np.isfinite(s)) and np.all(np.isfinite(p))):
        raise ValueError("SNR values must be finite (SNR cells are never censored)")
    err = np.abs(s - p)
    mean, mx = float(err.mean()), float(err.max())
    return SnrScore(mean, mx, int(err.size), mean <= C2_MEAN_DB and mx <= C2_MAX_DB)


def score_c8(
    fibre: Literal["nanf", "ssmf"],
    simulated_average_snr: Sequence[float] | FloatArray,
    published_average_snr: Sequence[float] | FloatArray,
) -> SnrScore:
    """C8: mean |simulated - published| average SNR at most 2.0 dB (NANF) or 3.0 dB (SSMF)."""
    if fibre not in C8_TOL_DB:
        raise ValueError("fibre must be 'nanf' or 'ssmf'")
    s, p = _arr(simulated_average_snr, "sim"), _arr(published_average_snr, "pub")
    if s.size == 0 or s.size != p.size or not (np.all(np.isfinite(s)) and np.all(np.isfinite(p))):
        raise ValueError("series must be finite, non-empty and of equal length")
    err = np.abs(s - p)
    return SnrScore(
        float(err.mean()), float(err.max()), int(err.size), float(err.mean()) <= C8_TOL_DB[fibre]
    )


@dataclass(frozen=True)
class C5Score:
    link: str
    mean_abs_db: float
    max_abs_db: float
    n_points: int
    passed: bool
    excluded_nm: tuple[float, ...]
    n_invalid: int = 0  # lost-lock wavelengths among the 17: any one fails (Amendment 7)
    reason: str = ""


def score_c5(
    link: Literal["nanf", "ssmf", "b2b"],
    wavelength_nm: Sequence[float] | FloatArray,
    simulated_snr: Sequence[float] | FloatArray,
    published_snr: Sequence[float] | FloatArray,
    *,
    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> C5Score:
    """C5: mean |error| over the 17 wavelengths 1460 to 1620 nm (B2); 1630 and 1640 are apart.

    Thresholds: NANF 2.0, SSMF 3.0, B2B 2.0 dB. After the exclusion the wavelengths must be exactly
    the 17 of B2, so a missing or extra point is an error and not a silent change of the criterion.
    """
    if link not in C5_TOL_DB:
        raise ValueError("link must be 'nanf', 'ssmf' or 'b2b'")
    wl, s, p = _arr(wavelength_nm, "wl"), _arr(simulated_snr, "sim"), _arr(published_snr, "pub")
    if not (wl.size == s.size == p.size):
        raise ValueError("series must have one value per wavelength")
    locked = _as_valid(simulated_valid, wl.size)
    keep = wl <= 1620.0 + 1e-9
    kept = wl[keep]
    if not np.all(np.isfinite(wl)) or any(
        not any(abs(w - ex) <= 1e-6 for ex in C5_REPORTED_ONLY_NM) for w in wl[~keep]
    ):
        raise ValueError("only 1630 and 1640 nm may lie outside the 17 wavelengths of plan B2")
    if kept.size != len(C5_WAVELENGTHS_NM) or not np.allclose(kept, C5_WAVELENGTHS_NM, atol=1e-6):
        raise ValueError("C5 needs exactly the 17 wavelengths 1460 to 1620 nm (plan B2)")
    if not locked[keep].all():
        k = int(np.count_nonzero(~locked[keep]))
        return C5Score(
            link, math.nan, math.nan, int(kept.size), False, tuple(float(w) for w in wl[~keep]),
            k, "lost-lock wavelength among the 17",
        )  # fmt: skip
    if not (np.all(np.isfinite(s[keep])) and np.all(np.isfinite(p[keep]))):
        raise ValueError("SNR values must be finite")
    err = np.abs(s[keep] - p[keep])
    mean = float(err.mean())
    return C5Score(
        link,
        mean,
        float(err.max()),
        int(err.size),
        mean <= C5_TOL_DB[link],
        tuple(float(w) for w in wl[~keep]),
    )


# --- C3 ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class C3Score:
    passed: bool
    reason: str
    simulated_penalty_db: float
    published_penalty_db: float | None  # reported next to the prose value
    penalty_ok: bool
    ssmf_ber_ok: bool
    n_points: int


def _penalty(
    nanf_rop: FloatArray, nanf_snr: FloatArray, ssmf_rop: FloatArray, ssmf_snr: FloatArray
) -> tuple[float, int]:
    n_r, n_s = _scored(nanf_rop, nanf_snr)
    s_r, s_s = _scored(ssmf_rop, ssmf_snr)
    inside = (n_r >= s_r.min()) & (n_r <= s_r.max()) if s_r.size else np.zeros(n_r.size, bool)
    if not inside.any():
        return math.nan, 0
    ssmf_at = np.interp(n_r[inside], s_r, s_s)
    return float(np.mean(n_s[inside] - ssmf_at)), int(inside.sum())


def score_c3(
    rate_gbps: int,
    nanf_rop: Sequence[float] | FloatArray,
    simulated_nanf_snr: Sequence[float] | FloatArray,
    ssmf_rop: Sequence[float] | FloatArray,
    simulated_ssmf_snr: Sequence[float] | FloatArray,
    simulated_ssmf_ber: Sequence[float] | FloatArray,
    published_nanf_snr: Sequence[float] | FloatArray | None = None,
    published_ssmf_snr: Sequence[float] | FloatArray | None = None,
    *,
    nanf_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
    ssmf_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> C3Score:
    """C3 exactly as Amendment 4 D3.3.

    The ROP set is the NANF ROPs at most -5 dBm lying inside the SSMF ROP range (no extrapolation);
    an empty set fails with "no overlap". Penalty = mean over the set of NANF SNR minus the SSMF SNR
    interpolated in dB. Pass needs (a) |simulated penalty - stated| at most 3.0 dB (inclusive) and
    (b) the simulated SSMF BER above 3.8e-3 at every SSMF ROP at most -5 dBm (zero errors fail (b)).
    The workbook penalty, if the published series are given, is reported and never scored.
    """
    if rate_gbps not in STATED_PENALTY_DB:
        raise ValueError(f"rate_gbps must be one of {RATES}")
    n_rop = _arr(nanf_rop, "nanf rop")
    s_rop = _arr(ssmf_rop, "ssmf rop")
    n_snr, s_snr = _arr(simulated_nanf_snr, "nanf snr"), _arr(simulated_ssmf_snr, "ssmf snr")
    s_ber = _arr(simulated_ssmf_ber, "ssmf ber")
    n_ok = _as_valid(nanf_valid, n_rop.size)
    s_ok = _as_valid(ssmf_valid, s_rop.size)
    if not (_scored(n_rop, n_ok)[1].all() and _scored(s_rop, s_ok)[1].all()):
        # a needed point lost lock: no substitution, no interpolation across it (Amendment 7)
        return C3Score(False, "lost-lock point at a scored ROP", math.nan, None, False, False, 0)
    _, ber_scored = _scored(s_rop, s_ber)
    if not (np.all(np.isfinite(n_snr)) and np.all(np.isfinite(s_snr))):
        raise ValueError("SNR values must be finite")
    if np.any(~np.isfinite(ber_scored)) or np.any(ber_scored < 0) or np.any(ber_scored > 1):
        raise InvalidDataError("simulated BER must lie in [0, 1] (zero errors is 0.0, never NaN)")
    published = None
    if published_nanf_snr is not None and published_ssmf_snr is not None:
        pen, _ = _penalty(
            n_rop, _arr(published_nanf_snr, "pub nanf"), s_rop, _arr(published_ssmf_snr, "pub ssmf")
        )
        published = None if math.isnan(pen) else pen
    penalty, n = _penalty(n_rop, n_snr, s_rop, s_snr)
    if n == 0:
        return C3Score(False, "no overlap", math.nan, published, False, False, 0)
    penalty_ok = abs(penalty - STATED_PENALTY_DB[rate_gbps]) <= C3_TOL_DB
    ber_ok = bool(np.all(ber_scored > BER_THRESHOLD))
    reason = (
        "pass"
        if penalty_ok and ber_ok
        else "penalty outside tolerance"
        if not penalty_ok
        else "SSMF BER at or below 3.8e-3"
    )
    return C3Score(penalty_ok and ber_ok, reason, penalty, published, penalty_ok, ber_ok, n)


# --- C4 ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class C4Score:
    fraction_within: float
    n_uncensored: int
    n_within: int
    censored_published: int
    censored_published_ok: int  # published censored points where the simulated BER is below 1e-4
    passed: bool
    n_invalid: int = 0  # lost-lock points at scored ROPs: any one fails (Amendment 7)
    reason: str = ""


def score_c4(
    rop: Sequence[float] | FloatArray,
    published_ber: Sequence[float] | FloatArray,
    simulated_ber: Sequence[float] | FloatArray,
    n_bits: int,
    *,
    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> C4Score:
    """C4 on pooled points (NANF and SSMF, concatenated by the caller; ROP is checked per point).

    For an uncensored published BER: |log10 simulated - log10 published| at most 0.5, counted over
    the points; at least 80% must be within. A simulated zero-error point has BER below 1/n_bits
    (7.7e-7 at the declared capture), more than a factor 10 under any published BER of at least
    1e-5, so it is a miss (F7.3). A simulated censored point (zero, or non-zero but below 1e-5, a
    BER carrying no magnitude) against an uncensored published BER is also a miss, never within
    (Amendment 6 G8: default deny). A censored published point is scored only as "simulated BER
    below 1e-4", reported, and not counted in the 80%.
    """
    r = _arr(rop, "rop")
    p, s = _arr(published_ber, "pub"), _arr(simulated_ber, "sim")
    if not (r.size == p.size == s.size) or r.size == 0 or n_bits <= 0:
        raise ValueError("series must have equal length; n_bits must be positive")
    if not np.all(np.isfinite(r)):
        raise ValueError("the ROP axis must be finite (a NaN would silently drop a point)")
    keep = r <= ROP_CAP_DBM
    locked = _as_valid(simulated_valid, r.size)[keep]
    p, s = p[keep], s[keep]
    if not locked.all():
        k = int(np.count_nonzero(~locked))
        return C4Score(math.nan, 0, 0, 0, 0, False, k, "lost-lock point at a scored ROP")
    sim_censored = is_censored(s)  # invalid simulated data raises; NaN is invalid here
    cens = is_censored(p, published=True)
    within = 0
    unc = np.flatnonzero(~cens)
    for i in unc:
        if sim_censored[i]:  # zero errors or below 1e-5: no usable magnitude, a miss (F7.3, G3)
            continue
        within += int(abs(math.log10(s[i]) - math.log10(p[i])) <= C4_LOG_TOL)
    cp = np.flatnonzero(cens)
    cp_ok = int(np.count_nonzero(s[cp] < 1e-4))
    frac = within / unc.size if unc.size else math.nan
    return C4Score(
        frac, int(unc.size), within, int(cp.size), cp_ok, bool(unc.size and frac >= C4_FRACTION)
    )


# --- C6: null estimator (A5, B5) -----------------------------------------------------------------


@dataclass(frozen=True)
class NullEstimate:
    frequency_ghz: float | None  # None: no interior null in window
    reason: str
    clock_spike_coincidence: bool


def _clock_candidates_ghz() -> tuple[float, ...]:
    lo, hi = C6_WINDOW_GHZ
    return tuple(70.0 / k for k in range(2, 9) if lo <= 70.0 / k <= hi)


def null_frequency(
    frequency_ghz: Sequence[float] | FloatArray, snr_db: Sequence[float] | FloatArray
) -> NullEstimate:
    """The null estimator of A5 as repaired by B5.

    (i) running median of the SNR profile over 5 subcarriers, centred, over the whole profile first
    (3 values at the first and last, 4 at the second and second last); (ii) restrict to 20.0 to
    32.8125 GHz; (iii) the null is where the median is lowest, the lowest frequency on ties. If the
    minimum falls on the first or last window point the result is "no interior null in window". A
    non-finite SNR or an unordered axis is refused.
    """
    f, s = _arr(frequency_ghz, "frequency"), _arr(snr_db, "snr")
    if f.size != s.size or f.size < 5 or not (np.all(np.isfinite(f)) and np.all(np.isfinite(s))):
        raise ValueError("need at least 5 finite points of equal length")
    if np.any(np.diff(f) <= 0):
        raise ValueError("the frequency axis must be strictly increasing")
    n = f.size
    med = np.array([np.median(s[max(0, i - 2) : min(n, i + 3)]) for i in range(n)])
    window = np.flatnonzero((f >= C6_WINDOW_GHZ[0]) & (f <= C6_WINDOW_GHZ[1]))
    if window.size < 3:
        raise ValueError("the window holds fewer than 3 points")
    k = int(np.argmin(med[window]))  # first index on ties = lowest frequency
    edge = k in (0, window.size - 1)
    freq = float(f[window[k]])
    coincide = any(abs(freq - c) <= 0.5 for c in _clock_candidates_ghz())
    if edge:
        return NullEstimate(None, "no interior null in window", coincide)
    return NullEstimate(freq, "interior null", coincide)


@dataclass(frozen=True)
class C6Score:
    passed: bool
    reason: str
    difference_ghz: float | None
    possible_clock_spike_coincidence: bool


def score_c6(published: NullEstimate, simulated: NullEstimate) -> C6Score:
    """C6: |simulated - published| null at most 2.0 GHz; no interior null on either side fails."""
    flag = published.clock_spike_coincidence or simulated.clock_spike_coincidence
    if published.frequency_ghz is None or simulated.frequency_ghz is None:
        return C6Score(False, "no interior null in window", None, flag)
    diff = simulated.frequency_ghz - published.frequency_ghz
    return C6Score(
        abs(diff) <= C6_TOL_GHZ,
        "difference within tolerance" if abs(diff) <= C6_TOL_GHZ else "difference too large",
        diff,
        flag,
    )


# --- C7: capacity (A3, F7.4) ---------------------------------------------------------------------

QAM_BITS = (2, 4, 6, 8)
_BIT_ERROR_TARGET = BER_THRESHOLD


def _q(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def qam_bit_error_approx(snr_linear: float, bits: int) -> float:
    """Gray bit-error approximation (4 / log2 M)(1 - 1/sqrt(M)) Q(sqrt(3 gamma/(M - 1))), F7.4."""
    m = 2**bits
    return (4.0 / bits) * (1.0 - 1.0 / math.sqrt(m)) * _q(math.sqrt(3.0 * snr_linear / (m - 1)))


def bit_loading(snr_db: Sequence[float] | FloatArray) -> NDArray[np.int64]:
    """Bits per subcarrier: largest of 2, 4, 6, 8 with approximate BER at most 3.8e-3, else 0."""
    s = _arr(snr_db, "snr")
    if not np.all(np.isfinite(s)):
        raise ValueError("SNR values must be finite")
    out = np.zeros(s.size, dtype=np.int64)
    for i, v in enumerate(s):
        gamma = 10.0 ** (v / 10.0)
        for bits in QAM_BITS:
            if qam_bit_error_approx(gamma, bits) <= _BIT_ERROR_TARGET:
                out[i] = bits
    return out


def capacity_gbps(
    bits: Sequence[int] | NDArray[np.int64], sample_rate_gsa: float = 70.0, fft_size: int = 512
) -> float:
    """Sum of bits loaded x 70 GSa/s / 512, in Gb/s over exactly 240 subcarriers (A3, C7, F7.4)."""
    b = np.asarray(bits)
    if b.size != C7_SUBCARRIERS or np.any(b < 0):
        raise ValueError(f"bits must hold exactly {C7_SUBCARRIERS} subcarriers, none negative")
    return float(b.sum() * sample_rate_gsa / fft_size)


@dataclass(frozen=True)
class C7Score:
    passed: bool
    nanf_error_gbps: float
    ssmf_error_gbps: float
    simulated_ratio: float
    published_ratio: float
    ratio_error: float


def score_c7(sim_nanf: float, sim_ssmf: float, pub_nanf: float, pub_ssmf: float) -> C7Score:
    """C7: each capacity within 10 Gb/s and the NANF/SSMF ratio within 0.10 of the published one."""
    values = (sim_nanf, sim_ssmf, pub_nanf, pub_ssmf)
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("capacities must be finite and positive")
    en, es = abs(sim_nanf - pub_nanf), abs(sim_ssmf - pub_ssmf)
    sim_r, pub_r = sim_nanf / sim_ssmf, pub_nanf / pub_ssmf
    er = abs(sim_r - pub_r)
    ok = en <= C7_CAPACITY_TOL_GBPS and es <= C7_CAPACITY_TOL_GBPS and er <= C7_RATIO_TOL
    return C7Score(ok, en, es, sim_r, pub_r, er)


# --- B2B-copy and d ------------------------------------------------------------------------------


@dataclass(frozen=True)
class B2bCopy:
    """The copy's prediction at the NANF ROPs; NaN where no B2B bracket exists (reported only)."""

    snr_db: FloatArray
    ber: FloatArray  # NaN where no uncensored B2B bracket
    unbracketed_snr: tuple[float, ...]
    unbracketed_ber: tuple[float, ...]

    def bracketed_ber(
        self, nanf_rop: Sequence[float] | FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """The ROPs and copy BER where a bracket exists. An unbracketed ROP is not scored (D3.1):
        it is dropped here, never passed on as a censored point."""
        q = _arr(nanf_rop, "nanf rop")
        if q.size != self.ber.size:
            raise ValueError("the ROP axis is not the one the copy was made for")
        ok = ~np.isnan(self.ber)
        return q[ok], self.ber[ok]


def b2b_copy(
    b2b_rop: Sequence[float] | FloatArray,
    b2b_snr: Sequence[float] | FloatArray,
    b2b_ber: Sequence[float] | FloatArray,
    nanf_rop: Sequence[float] | FloatArray,
) -> B2bCopy:
    """Amendment 4 D3.1: SNR in dB and log10 BER interpolated against ROP, no extrapolation.

    Only B2B points at most -5 dBm are used and, for BER, only uncensored points are nodes.
    """
    r, snr, ber = _scored(
        _arr(b2b_rop, "b2b rop"), _arr(b2b_snr, "b2b snr"), _arr(b2b_ber, "b2b ber")
    )
    q = _arr(nanf_rop, "nanf rop")
    if not np.all(np.isfinite(snr)) or not np.all(np.isfinite(q)):
        raise InvalidDataError("B2B SNR and the NANF ROP axis must be finite")
    nodes = ~is_censored(ber, published=True)  # inf, negative or above 1 raises
    snr_out = np.full(q.size, math.nan)
    ber_out = np.full(q.size, math.nan)
    if r.size >= 2:
        ok = (q >= r[0]) & (q <= r[-1])
        snr_out[ok] = np.interp(q[ok], r, snr)
    if nodes.sum() >= 2:
        rn, ln = r[nodes], np.log10(ber[nodes])
        ok = (q >= rn[0]) & (q <= rn[-1])
        ber_out[ok] = 10.0 ** np.interp(q[ok], rn, ln)
    return B2bCopy(
        snr_out, ber_out,
        tuple(float(x) for x in q[np.isnan(snr_out)]),
        tuple(float(x) for x in q[np.isnan(ber_out)]),
    )  # fmt: skip


def copy_crossing(copy: B2bCopy, nanf_rop: Sequence[float] | FloatArray) -> Crossing:
    """C1 of the B2B copy: the crossing of the copy BER at the scored NANF ROPs with a bracket.

    An unbracketed ROP is reported and not scored (D3.1); it is not read as a censored point. With
    no bracketed ROP at all there is nothing to score and the result is invalid (fails).
    """
    q, b = copy.bracketed_ber(nanf_rop)
    if q.size == 0:
        return Crossing("invalid", math.nan, math.nan)
    return c1_crossing(q, b)


def d_c1(model: Crossing, no_fibre: Crossing) -> float | None:
    """D3.2: absolute difference of the two crossings; None (undefined) if either is not a point."""
    if model.kind != "point" or no_fibre.kind != "point":
        return None
    return abs(model.lo - no_fibre.lo)


def d_snr(
    model_snr: Sequence[float] | FloatArray, no_fibre_snr: Sequence[float] | FloatArray
) -> float:
    """D3.2 for C2 and C5 NANF: mean absolute difference of the two predicted SNR series."""
    a, b = _arr(model_snr, "model"), _arr(no_fibre_snr, "no-fibre")
    if a.size == 0 or a.size != b.size or not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        raise ValueError("series must be finite, non-empty and of equal length")
    return float(np.mean(np.abs(a - b)))


def discriminating(d: float | None, tolerance: float) -> bool:
    """Discriminating means d strictly greater than the criterion's tolerance (D3.2)."""
    return d is not None and math.isfinite(d) and d > tolerance


# --- B2B fit-quality gate (B3.2) -----------------------------------------------------------------


@dataclass(frozen=True)
class B2bGate:
    passed: bool
    mean_abs_db: float
    max_abs_db: float
    crossing_ok: bool
    label: str  # "" or "B2B CALIBRATION POOR"


def b2b_gate(
    simulated_snr: Sequence[float] | FloatArray,
    published_snr: Sequence[float] | FloatArray,
    simulated_crossing: Crossing,
    published_crossing: Crossing,
    *,
    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,
) -> B2bGate:
    """B3.2 on the calibration points: mean |error| at most 1.0 dB, none beyond 2.0 dB, and the
    B2B crossing within 0.5 dB by the C1 rule (a bound by B1.3 with 0.5 dB)."""
    s, p = _arr(simulated_snr, "sim"), _arr(published_snr, "pub")
    locked = _as_valid(simulated_valid, s.size)
    if not locked.all():  # a lost-lock point of the calibration grid: the gate fails (Amendment 7)
        return B2bGate(False, math.nan, math.nan, False, "B2B CALIBRATION POOR")
    if s.size == 0 or s.size != p.size or not (np.all(np.isfinite(s)) and np.all(np.isfinite(p))):
        raise ValueError("series must be finite, non-empty and of equal length")
    err = np.abs(s - p)
    crossing = score_c1(published_crossing, simulated_crossing, tol=B2B_GATE_CROSSING_DB)
    ok = (
        float(err.mean()) <= B2B_GATE_MEAN_DB
        and float(err.max()) <= B2B_GATE_MAX_DB
        and crossing.passed
    )
    return B2bGate(
        ok,
        float(err.mean()),
        float(err.max()),
        crossing.passed,
        "" if ok else "B2B CALIBRATION POOR",
    )


# --- the verdict (section 4, A2, B3.3) -----------------------------------------------------------


@dataclass(frozen=True)
class RateScores:
    """The primary criteria of one rate."""

    c1_passed: bool
    c1_discriminating: bool
    c2_passed: bool
    c2_discriminating: bool
    c3_passed: bool
    c5_passed: bool  # NANF, SSMF and B2B all pass
    b2b_poor: bool = False

    def __post_init__(self) -> None:
        """Only real booleans: a truthy string or NaN must not read as a pass (Amendment 6 G8)."""
        for name in (
            "c1_passed", "c1_discriminating", "c2_passed", "c2_discriminating",
            "c3_passed", "c5_passed", "b2b_poor",
        ):  # fmt: skip
            if not isinstance(getattr(self, name), bool | np.bool_):
                raise ValueError(f"{name} must be a boolean, got {getattr(self, name)!r}")


@dataclass(frozen=True)
class Verdict:
    text: str
    failed: tuple[str, ...]
    not_discriminating_rates: tuple[int, ...]


def overall_verdict(scores: Mapping[int, RateScores]) -> Verdict:
    """The decision rule. Primary set C1, C2, C3, C5 at all three rates.

    Any primary failure: "failed" with the criteria and rates. All pass, but C1 or C2 not
    discriminating (or the rate's B2B calibration poor) at some rate: "primary criteria pass; NANF
    criteria NOT DISCRIMINATING" naming the rates. Otherwise "consistent with this one experiment".
    """
    if set(scores) != set(RATES):
        raise ValueError(f"scores are needed for exactly the rates {RATES}")
    failed = [
        f"{name}@{rate}"
        for rate in RATES
        for name, ok in (
            ("C1", scores[rate].c1_passed),
            ("C2", scores[rate].c2_passed),
            ("C3", scores[rate].c3_passed),
            ("C5", scores[rate].c5_passed),
        )
        if not ok
    ]
    if failed:
        return Verdict("failed: " + ", ".join(failed), tuple(failed), ())
    weak = tuple(
        rate
        for rate in RATES
        if scores[rate].b2b_poor
        or not (scores[rate].c1_discriminating and scores[rate].c2_discriminating)
    )
    if weak:
        names = ", ".join(str(r) for r in weak)
        return Verdict(
            f"primary criteria pass; NANF criteria NOT DISCRIMINATING (rates {names} Gb/s)",
            (),
            weak,
        )
    return Verdict("consistent with this one experiment", (), ())


# --- calibration evaluations with lost-lock points (Amendment 7) ---------------------------------

WORST_CASE_OBJECTIVE = math.inf


class EvaluationLostLockError(ArithmeticError):
    """An objective evaluation needed a point whose run lost lock. `lost` names the points."""

    def __init__(self, lost: Sequence[str]) -> None:
        self.lost = tuple(lost)
        super().__init__("lost lock at " + ", ".join(self.lost))


class NoValidFitError(ValueError):
    """No evaluation without a lost-lock point exists, so no vector can be chosen."""


class IdentifiabilityUndefinedError(ValueError):
    """The B4 Jacobian needs an evaluation with a lost-lock point: no flags are derived."""


@dataclass(frozen=True)
class Evaluation:
    """One objective evaluation of one vector. Any lost-lock point at a needed point makes the
    objective the worst case; the evaluation is counted and logged and can never be selected."""

    vector: Mapping[str, float]
    objective: float
    lost: tuple[str, ...]

    @property
    def n_lost(self) -> int:
        return len(self.lost)


class EvaluationLog:
    """Every evaluation of a calibration, so that the worst-case ones are counted and logged."""

    def __init__(self) -> None:
        self.evaluations: list[Evaluation] = []

    def record(self, ev: Evaluation) -> Evaluation:
        self.evaluations.append(ev)
        return ev

    @property
    def n_worst_case(self) -> int:
        return sum(1 for e in self.evaluations if e.lost)

    def lines(self) -> list[str]:
        return [
            f"WORST-CASE OBJECTIVE evaluation {i}: lost lock at {', '.join(e.lost)}"
            for i, e in enumerate(self.evaluations)
            if e.lost
        ]


def evaluate(
    log: EvaluationLog,
    vector: Mapping[str, float],
    objective: Callable[[Mapping[str, float]], float],
) -> Evaluation:
    """Evaluate `objective` at `vector`. If it raises `EvaluationLostLockError` the evaluation gets
    `WORST_CASE_OBJECTIVE`; it is recorded either way. Any other non-finite objective is refused.
    """
    try:
        value = float(objective(vector))
        lost: tuple[str, ...] = ()
    except EvaluationLostLockError as err:
        value, lost = WORST_CASE_OBJECTIVE, err.lost
    if not lost and not math.isfinite(value):
        raise ValueError("an objective that is not finite and not a lost-lock run is refused")
    return log.record(Evaluation(dict(vector), value, lost))


def select_best(log: EvaluationLog) -> Evaluation:
    """The lowest objective among evaluations with no lost-lock point; a worst-case one is never
    selected. `NoValidFitError` if there is none."""
    clean = [e for e in log.evaluations if not e.lost and math.isfinite(e.objective)]
    if not clean:
        raise NoValidFitError("every evaluation lost lock at a needed point")
    return min(clean, key=lambda e: e.objective)


def check_chosen_fit(chosen: Evaluation) -> Evaluation:
    """A fit whose chosen vector has lost-lock points in the Fig.4 B2B grid is invalid."""
    if chosen.lost or not math.isfinite(chosen.objective):
        raise NoValidFitError("the chosen vector has lost-lock points in the B2B calibration grid")
    return chosen


# --- identifiability (A1.7, B4) ------------------------------------------------------------------


@dataclass(frozen=True)
class IdentifiabilityResult:
    """The B4 check: eigenvalues of J^T J ascending, the flags, and the vector to be hashed."""

    eigenvalues: FloatArray
    information: FloatArray
    flagged: tuple[str, ...]
    vector: dict[str, float]  # flagged parameters set to their prior, the others as given
    singular: bool


def identifiability_check(
    residuals: Callable[[Mapping[str, float]], FloatArray],
    optimum: Mapping[str, float],
    specs: Sequence[ParameterSpec] = B4_PARAMETERS,
    *,
    step: float = 1e-3,
    ratio: float = 1e-3,
) -> IdentifiabilityResult:
    """Plan B4 made executable (A1.7).

    Each parameter is scaled to u = (value - low) / (high - low). J is the Jacobian of the residual
    vector with respect to u at the optimum by finite differences of step 1e-3 in u (central where
    the step stays inside [0, 1], one-sided inward at a range edge). The information matrix is
    J^T J. For each eigenvalue below `ratio` of the largest, in ascending order, the parameter with
    the largest absolute component in that eigenvector among those not yet flagged is flagged (ties:
    the lowest in the table). A singular matrix (largest eigenvalue not above zero) flags every
    parameter. A flagged parameter is set to its prior; nothing is refitted.

    Lost-lock points (Amendment 7): a residual evaluation, at the optimum or at any
    finite-difference
    step, that raises `EvaluationLostLockError` makes the check undefined
    (`IdentifiabilityUndefinedError`).
    No worst-case value ever enters J, no flag is derived, and the calibration cannot be frozen.
    """
    names = [s.name for s in specs]
    if set(optimum) != set(names):
        raise ValueError(f"optimum must have exactly the keys {names}")
    if not 0 < step < 0.5 or ratio <= 0:
        raise ValueError("step must be in (0, 0.5) and ratio positive")
    u0 = np.array([(optimum[s.name] - s.low) / (s.high - s.low) for s in specs])
    if np.any(u0 < -1e-12) or np.any(u0 > 1 + 1e-12) or not np.all(np.isfinite(u0)):
        raise ValueError("the optimum lies outside the allowed ranges")

    def at(u: FloatArray) -> FloatArray:
        values = {s.name: float(s.low + u[i] * (s.high - s.low)) for i, s in enumerate(specs)}
        try:
            out = np.asarray(residuals(values), dtype=float)
        except EvaluationLostLockError as err:
            raise IdentifiabilityUndefinedError(
                "the B4 check needs an evaluation with a lost-lock point ("
                + ", ".join(err.lost)
                + "): no Jacobian, no flags, and the vector is not frozen"
            ) from None
        if out.ndim != 1 or out.size == 0 or not np.all(np.isfinite(out)):
            raise ValueError("the residual vector must be finite, 1-D and non-empty")
        return out

    r0 = at(u0)
    cols = []
    for i in range(len(specs)):
        up, down = u0.copy(), u0.copy()
        up[i] = min(u0[i] + step, 1.0)
        down[i] = max(u0[i] - step, 0.0)
        cols.append((at(up) - at(down)) / (up[i] - down[i]))
    jac = np.stack(cols, axis=1)
    if jac.shape[0] != r0.size:
        raise ValueError("inconsistent residual length")
    info = jac.T @ jac
    values, vectors = np.linalg.eigh(info)
    largest = float(values[-1])
    singular = not largest > 0.0
    flagged: list[int] = []
    for k in range(values.size):
        if not (singular or values[k] < ratio * largest):
            continue
        vec = np.abs(vectors[:, k])
        free = [i for i in range(len(specs)) if i not in flagged]
        if not free:
            break
        top = max(vec[i] for i in free)
        flagged.append(next(i for i in free if vec[i] >= top * (1 - 1e-12)))
    result_vector = {s.name: float(optimum[s.name]) for s in specs}
    for i in flagged:
        result_vector[specs[i].name] = specs[i].prior
    return IdentifiabilityResult(
        values, info, tuple(specs[i].name for i in flagged), result_vector, singular
    )
