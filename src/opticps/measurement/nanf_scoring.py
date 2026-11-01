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
from typing import Literal

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
C6_TOL_GHZ = 2.0
C6_WINDOW_GHZ = (20.0, 32.8125)
C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 10.0, 0.10
C8_TOL_DB = {"nanf": 2.0, "ssmf": 3.0}
B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.0, 2.0, 0.5


def _arr(values: Sequence[float] | FloatArray, name: str) -> FloatArray:
    a = np.asarray(values, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return a


def _scored(rop: FloatArray, *columns: FloatArray) -> tuple[FloatArray, ...]:
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


def is_censored(ber: float | FloatArray) -> NDArray[np.bool_]:
    """A BER is censored if it is not finite or below 1e-5 (zero included), plan A3 and F7.1."""
    b = np.asarray(ber, dtype=float)
    return np.asarray(~np.isfinite(b) | (b < BER_CENSOR_FLOOR))


# --- C1: the crossing rule (A3, B1, C1-R) --------------------------------------------------------

Kind = Literal["point", "left", "right", "interval"]


@dataclass(frozen=True)
class Crossing:
    """A crossing of BER 3.8e-3 on the ROP axis: a point, a bound, or an interval (all in dBm).

    point: lo == hi. left ("at or below r0"): region (-inf, r0]. right ("above r0"): [r0, inf).
    interval: [lo, hi].
    """

    kind: Kind
    lo: float
    hi: float

    @property
    def x(self) -> float:
        if self.kind != "point":
            raise ValueError("only a point crossing has a single value")
        return self.lo


def c1_crossing(
    rop: Sequence[float] | FloatArray,
    ber: Sequence[float] | FloatArray,
    threshold: float = BER_THRESHOLD,
) -> Crossing:
    """The ROP at which BER crosses `threshold`, by rule C1-R (Amendment 3), at most -5 dBm.

    P is the last uncensored point. If P is below the threshold: the crossing is the linear
    interpolation of log10 BER against ROP in the last downward bracket (highest ROP) of two
    adjacent uncensored points, or, with no such bracket, a left-censored bound at the first scored
    ROP. If P is above: with a censored point after P, the interval [ROP of P, ROP of the first
    censored point after P]; otherwise the right-censored bound "above ROP of P". Adjacent means
    adjacent among the uncensored points (A3: "keep those uncensored and scored"). A value equal to
    the threshold counts as above. With no uncensored point the curve is left-censored.
    """
    r, b = _scored(_arr(rop, "rop"), _arr(ber, "ber"))
    if r.size == 0:
        raise ValueError("no scored point (every ROP is above the cap)")
    censored = is_censored(b)
    unc = np.flatnonzero(~censored)
    if unc.size == 0:
        return Crossing("left", -math.inf, float(r[0]))
    if np.any(b[unc] <= 0) or np.any(b[unc] > 1):
        raise ValueError("an uncensored BER must lie in (0, 1]")
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


def score_c1(published: Crossing, simulated: Crossing, tol: float = C1_TOL_DB) -> C1Score:
    """Score a simulated crossing against a published one (A3, B1.3; F7.2 for the open cases).

    The published region is widened by `tol` on each finite side. A simulated point must lie in
    it. A published point with a simulated bound ("no crossing in the scored range") fails (B1.3);
    a simulated interval passes if any part of it lies in the widened region. A simulated bound
    against a published bound or interval is read at its ROP.
    """
    lo, hi = _widened(published, tol)
    both = published.kind == "point" and simulated.kind == "point"
    if simulated.kind == "point":
        ok = lo <= simulated.lo <= hi
        return C1Score(
            ok, "crossing inside the accepted region" if ok else "crossing outside", both
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


def score_c2(
    rop: Sequence[float] | FloatArray,
    simulated_snr: Sequence[float] | FloatArray,
    published_snr: Sequence[float] | FloatArray,
) -> SnrScore:
    """C2: mean |error| at most 1.5 dB and no single |error| above 3.0 dB, on ROP at most -5 dBm."""
    r, s, p = _scored(_arr(rop, "rop"), _arr(simulated_snr, "sim"), _arr(published_snr, "pub"))
    if r.size == 0:
        raise ValueError("no scored point")
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


def score_c5(
    link: Literal["nanf", "ssmf", "b2b"],
    wavelength_nm: Sequence[float] | FloatArray,
    simulated_snr: Sequence[float] | FloatArray,
    published_snr: Sequence[float] | FloatArray,
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
    keep = wl <= 1620.0 + 1e-9
    kept = wl[keep]
    if kept.size != len(C5_WAVELENGTHS_NM) or not np.allclose(kept, C5_WAVELENGTHS_NM, atol=1e-6):
        raise ValueError("C5 needs exactly the 17 wavelengths 1460 to 1620 nm (plan B2)")
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
    _, ber_scored = _scored(s_rop, s_ber)
    if not (np.all(np.isfinite(n_snr)) and np.all(np.isfinite(s_snr))):
        raise ValueError("SNR values must be finite")
    if np.any(~np.isfinite(ber_scored)):
        raise ValueError("simulated BER must be finite (zero errors is 0.0, never NaN)")
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


def score_c4(
    rop: Sequence[float] | FloatArray,
    published_ber: Sequence[float] | FloatArray,
    simulated_ber: Sequence[float] | FloatArray,
    n_bits: int,
) -> C4Score:
    """C4 on pooled points (NANF and SSMF, concatenated by the caller; ROP is checked per point).

    For an uncensored published BER: |log10 simulated - log10 published| at most 0.5, counted over
    the points; at least 80% must be within. A simulated zero-error point has BER below 1/n_bits
    (7.7e-7 at the declared capture), more than a factor 10 under any published BER of at least
    1e-5, so it is a miss (F7.3); for any n_bits it is counted as a miss, never as within (default
    deny). A censored published point is scored only as "simulated BER below 1e-4", reported, and
    not counted in the 80%.
    """
    r = _arr(rop, "rop")
    p, s = _arr(published_ber, "pub"), _arr(simulated_ber, "sim")
    if not (r.size == p.size == s.size) or r.size == 0 or n_bits <= 0:
        raise ValueError("series must have equal length; n_bits must be positive")
    keep = r <= ROP_CAP_DBM
    p, s = p[keep], s[keep]
    if np.any(~np.isfinite(s)) or np.any(s < 0) or np.any(s > 1):
        raise ValueError("simulated BER must lie in [0, 1]")
    cens = is_censored(p)
    within = 0
    unc = np.flatnonzero(~cens)
    for i in unc:
        if s[i] == 0.0:  # below the detection floor 1/n_bits: a miss (F7.3)
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
    """Sum of bits loaded x 70 GSa/s / 512, in Gb/s (A3, C7)."""
    b = np.asarray(bits)
    if b.size == 0 or np.any(b < 0):
        raise ValueError("bits must be non-empty and not negative")
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
    snr_out = np.full(q.size, math.nan)
    ber_out = np.full(q.size, math.nan)
    if r.size >= 2:
        ok = (q >= r[0]) & (q <= r[-1])
        snr_out[ok] = np.interp(q[ok], r, snr)
    nodes = ~is_censored(ber)
    if nodes.sum() >= 2:
        rn, ln = r[nodes], np.log10(ber[nodes])
        ok = (q >= rn[0]) & (q <= rn[-1])
        ber_out[ok] = 10.0 ** np.interp(q[ok], rn, ln)
    return B2bCopy(
        snr_out, ber_out,
        tuple(float(x) for x in q[np.isnan(snr_out)]),
        tuple(float(x) for x in q[np.isnan(ber_out)]),
    )  # fmt: skip


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
) -> B2bGate:
    """B3.2 on the calibration points: mean |error| at most 1.0 dB, none beyond 2.0 dB, and the
    B2B crossing within 0.5 dB by the C1 rule (a bound by B1.3 with 0.5 dB)."""
    s, p = _arr(simulated_snr, "sim"), _arr(published_snr, "pub")
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
        out = np.asarray(residuals(values), dtype=float)
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
