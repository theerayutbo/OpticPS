"""Gate E3, source 4: fixed-peak constrained PAM4 information rates (Wiegart et al., JLT 2021).

Our own notation. Transmit alphabet a_i = i for i = 0..3 (unit spacing, a fixed peak a_3 = 3: the
peak-to-peak drive does not change with the distribution), PMF pi = (pi_0..pi_3), channel
Y = X + N with N ~ Normal(0, s^2). Peak SNR rho = a_3^2 / s^2 = 9 / s^2, so
s = 3 * 10^(-rho_dB / 20) (the source's electrical-domain definition, its Eq. 4).

Two rates, both in bits per channel use (bpcu):

* symbol-metric rate   R_S  = I(X;Y)                          (source Eq. 6)
* bit-metric rate      R_B  = [H(X) - sum_k H(B_k | Y)]^+     (source Eq. 7), with the two-bit
  binary reflected Gray label b(x) = x XOR (x >> 1), i.e. 0->00, 1->01, 2->11, 3->10 in order of
  increasing x. The source names the code but does not print the table; this is the standard
  binary reflected Gray code for four points.

Two independent evaluations of both rates are provided. The OpticPS implementation
(`opticps.optimization.rates`, Gauss-Hermite quadrature over the posterior form) is the primary
one; `rates_by_grid` is a second method written here from the differential-entropy form
I = h(Y) - h(N) and direct trapezoid integration of the marginal density on a fine grid. They
share no code. The tests also pin both against closed forms and limits.

The compared quantity is the PSNR gain in dB: the PSNR a uniform PAM4 needs to reach a target
rate minus the PSNR the best symmetric PMF P = (p, 1/2 - p, 1/2 - p, p) needs for the same rate,
at equal peak. In the source's notation p = P_X(0). Nothing is taken from a figure.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq, minimize_scalar
from scipy.stats import norm

from opticps.benchmarks.comparison import (
    FIGURE_BLOCK,
    ComparisonResult,
    ComparisonStatus,
    Row,
    compare,
    refuse,
)
from opticps.benchmarks.published_points import (
    ConstraintType,
    DriveDomain,
    EvidenceLabel,
    ModelPoint,
    PublishedPoint,
    ReadFrom,
)
from opticps.optimization.rates import achievable_rates, psnr_for_rate

SOURCE_ID = "wiegart_2021_jlt"
PEAK = 3.0
UNIFORM_PMF = (0.25, 0.25, 0.25, 0.25)
FIXED_PMF = (0.35, 0.15, 0.15, 0.35)  # the source's fixed experimental distribution (Sec. II)
TARGET_RATE_BPCU = 1.0
_LABELS = tuple(x ^ (x >> 1) for x in range(4))  # binary reflected Gray: 0, 1, 3, 2
_BITS = tuple(((lab >> 1) & 1, lab & 1) for lab in _LABELS)  # (b1, b2) of each x

RATE_SMD = "SMD: I(X;Y), bits per channel use (source Eq. 6)"
RATE_BMD = (
    "BMD: [H(X) - sum_k H(B_k|Y)]^+ with binary reflected Gray labels, "
    "bits per channel use (source Eq. 7)"
)
DSP_NONE = "none: information-theoretic rate of the linear AWGN model (source Eq. 3)"

# Tolerances, fixed in this file before any deviation was computed.
TOL_GAIN_DB = 0.01
TOL_GAIN_WHY = (
    "The source prints the gain with two decimals, so its own rounding is +-0.005 dB; a further "
    "0.005 dB is allowed for the line-search resolution and rate estimator the source does not "
    "report. Our two numerical methods agree to far better than this (tests)."
)
TOL_P0 = 0.05
TOL_P0_WHY = (
    "The source prints the optimal probability with one decimal (+-0.05 rounding), and says the "
    "fixed distribution at 0.35 stays close to optimal over a wide range, so the optimum is flat "
    "and cannot be resolved finer than the printed digit."
)


# ----------------------------------------------------------------------------- definitions
def sigma_from_psnr_db(psnr_db: float) -> float:
    """Noise standard deviation for a peak SNR in dB: s = 3 * 10^(-rho/20)."""
    return PEAK * 10.0 ** (-psnr_db / 20.0)


def psnr_db_from_sigma(sigma: float) -> float:
    """Peak SNR in dB: 10 log10(9 / s^2) (source Eq. 4)."""
    return float(10.0 * np.log10(PEAK**2 / sigma**2))


def symmetric_pmf(p0: float) -> NDArray[np.float64]:
    """P = (p, 1/2 - p, 1/2 - p, p); p = 1/2 is on-off keying, p = 1/4 is uniform."""
    if not 0.0 <= p0 <= 0.5:
        raise ValueError(f"P_X(0) must lie in [0, 0.5], got {p0}")
    return np.array([p0, 0.5 - p0, 0.5 - p0, p0])


# ----------------------------------------------------------------------------- second method
def _check_pmf(pmf: object) -> NDArray[np.float64]:
    p = np.asarray(pmf, dtype=float)
    if p.shape != (4,) or not np.all(np.isfinite(p)) or np.any(p < 0) or abs(p.sum() - 1) > 1e-9:
        raise ValueError(f"expected a 4-point PMF summing to 1, got {p}")
    return p


def rates_by_grid(pmf: object, psnr_db: float, step_in_sigma: float = 0.01) -> tuple[float, float]:
    """(R_S, R_B) in bpcu by direct trapezoid integration on a fine y grid.

    R_S = h(Y) - h(N), with h(Y) = -int f log2 f dy for the Gaussian mixture f and
    h(N) = (1/2) log2(2 pi e s^2). R_B = H(X) - sum_k H(B_k|Y), H(B_k|Y) = -int sum_b g_b
    log2(g_b / f) dy where g_b(y) = sum_{x: bit_k(x) = b} pi_x phi((y - x)/s)/s.
    """
    p = _check_pmf(pmf)
    s = sigma_from_psnr_db(psnr_db)
    y = np.arange(-14.0 * s, PEAK + 14.0 * s, step_in_sigma * s)
    phi = np.exp(-0.5 * ((y[None, :] - np.arange(4.0)[:, None]) / s) ** 2) / (
        s * np.sqrt(2 * np.pi)
    )
    joint = p[:, None] * phi  # pi_x f(y|x), shape (4, n)
    f = joint.sum(axis=0)
    floor = 1e-300
    h_y = -np.trapezoid(f * np.log2(np.maximum(f, floor)), y)
    h_n = 0.5 * np.log2(2 * np.pi * np.e * s**2)
    smd = float(h_y - h_n)
    h_x = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
    cond_bits = 0.0
    for k in range(2):
        for b in (0, 1):
            g = sum(joint[x] for x in range(4) if _BITS[x][k] == b)
            integrand = np.where(
                g > 0, g * np.log2(np.maximum(g, floor) / np.maximum(f, floor)), 0.0
            )
            cond_bits -= float(np.trapezoid(integrand, y))
    bmd_raw = h_x - cond_bits
    return smd, max(0.0, float(bmd_raw))


def ook_rate_by_llr(psnr_db: float) -> float:
    """Closed-form-integral rate of on-off keying on levels {0, 3}, equiprobable (third method).

    With gamma = 3/s and X = 0 sent, the log-likelihood ratio is gamma z - gamma^2/2 for
    z ~ Normal(0,1), and I = 1 - E[log2(1 + exp(LLR))].
    """
    from scipy.integrate import quad

    gamma = PEAK / sigma_from_psnr_db(psnr_db)

    def integrand(z: float) -> float:
        return float(norm.pdf(z) * np.logaddexp(0.0, gamma * z - gamma**2 / 2) / np.log(2.0))

    value, _ = quad(integrand, -12.0, 12.0 + gamma, epsabs=1e-13, epsrel=1e-13, limit=400)
    return 1.0 - float(value)


# ----------------------------------------------------------------------------- primary method
def rates_opticps(pmf: object, psnr_db: float) -> tuple[float, float]:
    """(R_S, R_B) in bpcu from the OpticPS rate module (primary evaluation)."""
    r = achievable_rates(pmf, psnr_db)
    return r.smd, r.bmd


def required_psnr_db(pmf: object, rate: float, metric: str) -> float:
    """PSNR in dB at which `pmf` reaches `rate` (OpticPS root search)."""
    return psnr_for_rate(pmf, rate, metric)


def required_psnr_db_grid(pmf: object, rate: float, metric: str) -> float:
    """Same quantity from the second method."""
    index = {"smd": 0, "bmd": 1}[metric]
    return float(brentq(lambda d: rates_by_grid(pmf, d)[index] - rate, -10.0, 45.0, xtol=1e-7))


@dataclass(frozen=True)
class OptimalSymmetric:
    p0: float
    psnr_db: float


def best_symmetric(
    rate: float, metric: str, lo: float = 0.2, hi: float = 0.4999
) -> OptimalSymmetric:
    """Symmetric PMF needing the least PSNR to reach `rate`, found by bounded line search."""
    result = minimize_scalar(
        lambda q: required_psnr_db(symmetric_pmf(q), rate, metric),
        bounds=(lo, hi),
        method="bounded",
        options={"xatol": 1e-6},
    )
    return OptimalSymmetric(float(result.x), float(result.fun))


def psnr_gain_db(pmf_shaped: object, rate: float, metric: str) -> float:
    """PSNR the uniform PAM4 needs minus the PSNR `pmf_shaped` needs, same peak, same rate."""
    return required_psnr_db(UNIFORM_PMF, rate, metric) - required_psnr_db(pmf_shaped, rate, metric)


def optimal_p0_at_psnr(psnr_db: float, metric: str) -> float:
    """P_X(0) maximising the chosen rate at a given PSNR, over the symmetric family."""
    index = {"smd": 0, "bmd": 1}[metric]
    grid = np.linspace(0.05, 0.5, 91)
    values = [rates_opticps(symmetric_pmf(q), psnr_db)[index] for q in grid]
    best = int(np.argmax(values))
    lo, hi = grid[max(best - 1, 0)], grid[min(best + 1, grid.size - 1)]
    if hi <= lo:
        return float(grid[best])
    refined = minimize_scalar(
        lambda q: -rates_opticps(symmetric_pmf(q), psnr_db)[index],
        bounds=(float(lo), float(hi)),
        method="bounded",
        options={"xatol": 1e-7},
    )
    return float(refined.x) if -refined.fun >= values[best] else float(grid[best])


def ook_threshold_psnr_db(metric: str, step_db: float = 0.05) -> float:
    """Smallest PSNR (dB, on a grid) at which on-off keying stops being the optimal PMF."""
    psnr = 6.0
    while psnr < 30.0:
        if optimal_p0_at_psnr(psnr, metric) < 0.4999:
            return psnr
        psnr += step_db
    raise RuntimeError("no OOK threshold found below 30 dB")


# ----------------------------------------------------------------------------- source points
def _published(
    location: str,
    quantity: str,
    value: float,
    unit: str,
    rate_definition: str,
    note: str,
) -> PublishedPoint:
    return PublishedPoint(
        source_id=SOURCE_ID,
        location=location,
        quantity=quantity,
        value=value,
        unit=unit,
        rate_definition=rate_definition,
        constraint=ConstraintType.PEAK,
        dsp_stage=DSP_NONE,
        drive=DriveDomain.ELECTRICAL,
        evidence=EvidenceLabel.ANALYTICAL,
        read_from=ReadFrom.RUNNING_TEXT,
        note=note,
    )


def _ours(quantity: str, value: float, unit: str, rate_definition: str, method: str) -> ModelPoint:
    return ModelPoint(
        quantity=quantity,
        value=value,
        unit=unit,
        rate_definition=rate_definition,
        constraint=ConstraintType.PEAK,
        dsp_stage=DSP_NONE,
        drive=DriveDomain.ELECTRICAL,
        evidence=EvidenceLabel.ANALYTICAL,
        method=method,
    )


NOT_APPLICABLE = (
    "wavelength_nm",
    "fibre_length_km",
    "baud_bd",
    "ber_definition",
    "fec_threshold_ber",
)


def _gain_row(
    row_id: str,
    location: str,
    published_db: float,
    pmf: object,
    metric: str,
    pmf_text: str,
    best: bool,
) -> Row:
    rate_def = RATE_SMD if metric == "smd" else RATE_BMD
    quantity = f"PSNR gain over uniform 4-PAM at R = {TARGET_RATE_BPCU:.1f} bpcu, {pmf_text}"
    if best:
        shaped = symmetric_pmf(best_symmetric(TARGET_RATE_BPCU, metric).p0)
    else:
        shaped = _check_pmf(pmf)
    ours = psnr_gain_db(shaped, TARGET_RATE_BPCU, metric)
    result = compare(
        _published(location, quantity, published_db, "dB", rate_def, "gain quoted in running text"),
        _ours(quantity, ours, "dB", rate_def, "OpticPS rates, root search on PSNR"),
        tolerance=TOL_GAIN_DB,
        tolerance_justification=TOL_GAIN_WHY,
        not_applicable=NOT_APPLICABLE,
    )
    return Row(
        row_id,
        location,
        f"{quantity}: {published_db:.2f} dB",
        f"same quantity, {metric.upper()}: {ours:.4f} dB",
        result,
    )


def _p0_row(row_id: str, metric: str) -> Row:
    location = "Sec. III, running text on the dispersion-less model optimum"
    quantity = f"optimal P_X(0) of the symmetric family at R = {TARGET_RATE_BPCU:.1f} bpcu"
    rate_def = RATE_SMD if metric == "smd" else RATE_BMD
    ours = best_symmetric(TARGET_RATE_BPCU, metric).p0
    result = compare(
        _published(
            location, quantity, 0.4, "probability", rate_def, "metric not stated for this value"
        ),
        _ours(quantity, ours, "probability", rate_def, "line search over p, least PSNR for 1 bpcu"),
        tolerance=TOL_P0,
        tolerance_justification=TOL_P0_WHY,
        not_applicable=NOT_APPLICABLE,
    )
    return Row(row_id, location, f"{quantity}: 0.4", f"{metric.upper()}: {ours:.4f}", result)


def wiegart_rows() -> list[Row]:
    """All E3 rows for source 4, in report order. Computes everything from scratch."""
    fig = f"NOT COMPARABLE: {FIGURE_BLOCK}"
    rows = [
        _gain_row(
            "W1",
            "Sec. II, running text after Fig. 2",
            0.83,
            None,
            "smd",
            "best symmetric PMF",
            True,
        ),
        _gain_row(
            "W2",
            "Sec. II, running text after Fig. 2",
            0.71,
            None,
            "bmd",
            "best symmetric PMF",
            True,
        ),
        _gain_row(
            "W3",
            "Sec. II, running text after Fig. 2",
            0.63,
            FIXED_PMF,
            "bmd",
            "PMF (0.35, 0.15, 0.15, 0.35)",
            False,
        ),
        _p0_row("W4a", "smd"),
        _p0_row("W4b", "bmd"),
    ]
    smd_t, bmd_t = ook_threshold_psnr_db("smd"), ook_threshold_psnr_db("bmd")
    ordered = bmd_t > smd_t
    rows.append(
        Row(
            "W5",
            "Sec. II, running text after Fig. 1 (qualitative)",
            "operation range of on-off keying is larger for BMD than for SMD",
            f"OOK stops being optimal at {smd_t:.2f} dB (SMD) and {bmd_t:.2f} dB (BMD), "
            "0.05 dB grid",
            ComparisonResult(
                status=ComparisonStatus.MATCH if ordered else ComparisonStatus.MISMATCH,
                reason="ordering reproduced" if ordered else "ordering not reproduced",
            ),
        )
    )
    for row_id, location, text, need in (
        (
            "W6",
            "Fig. 1",
            "optimal P_X(0) against PSNR",
            "Fig. 1, x: PSNR [dB], y: P_X(0); the curve for SMD and for BMD",
        ),
        (
            "W7",
            "Fig. 2a, 2b",
            "achievable rate curves and the annotated gaps in dB and bit",
            "Fig. 2a (BMD) and 2b (SMD), x: PSNR [dB], y: rate [bit/channel use]; "
            "curves and annotations",
        ),
    ):
        rows.append(Row(row_id, location, text, need, refuse(f"{fig}. Needed: {need}")))
    rows.append(
        Row(
            "W8",
            "Sec. II, running text, finite-length LDPC simulation",
            "0.47 dB gain at frame error rate 1e-3 for a protograph LDPC code with PAS and CCDM",
            "not computed: needs a finite-length coded simulation",
            refuse(
                "NOT COMPARABLE: coded-FER quantity, not an information rate; the code "
                "construction (protograph, girth optimisation, CCDM length) is not specified "
                "completely enough to rebuild it; out of scope for an AIR comparison"
            ),
        )
    )
    rows.append(
        Row(
            "W9",
            "Sec. III, running text, experiments",
            "measured gains (0.24 dB and 0.31 dB attenuation, 0.05 bpcu, reach gains) at 16 GBd",
            "not computed: needs the experiment's PSNR",
            refuse(
                "NOT COMPARABLE: measured with a 5/11-tap FFE and an estimated AIR; the "
                "experiment's electrical PSNR at the receiver, baud rate per point and the "
                "link loss budget are not stated, so no PSNR (the compared axis) is known; "
                "the fibre results include chromatic dispersion, which the AWGN model omits"
            ),
        )
    )
    return rows
