"""Achievable rates of discrete inputs on the real AWGN channel, for PAM-M.

R_SMD = I(X;Y) is the symbol-metric rate. R_BMD = [H(X) - sum_k H(B_k|Y)]^+ is
Boecherer's bit-metric decoding rate (Boecherer et al., 2015; Wiegart et al., 2020)
for a Gray labelling with m = log2 M bit levels and the exact bit posteriors. Without
the clip, H(X) - sum_k H(B_k|Y) is the GMI at s = 1 of the decoding metric
q(x,y) = prod_k P(b_k|y) / P_X(x). It is NOT the GMI at s = 1 of q = prod_k P(b_k|y),
which differs for shaped PMFs. The GMI also maximises over s >= 0, which is not done,
so the name R_BMD is kept and "GMI" is not used for it. The unclipped value is
returned as `bmd_raw`; it can be negative, and `bmd` is [bmd_raw]^+.

PSNR is defined on the unipolar alphabet {0, ..., M-1} as (M-1)^2 / sigma^2. For
M = 4 this is 3^2 / sigma^2, which keeps the numbers comparable with Wiegart et al.
Equal PSNR across M therefore means equal peak-to-peak swing and equal noise. The
average SNR E[x^2] / sigma^2 differs between PMFs and orders and is reported
separately by `average_snr`.

Numerics: with equal sigma on all levels, expectations over the Gaussian noise use
Gauss-Hermite quadrature. `nodes` defaults to 120 for M = 4 (the legacy value) and 240
otherwise, see `default_nodes`. For M = 4 the original direct-likelihood kernel is kept
operation for operation, so legacy results are bit-identical; it falls back to the
log-domain kernel if it ever produces a non-finite value. Every other order uses the
log-domain kernel (log-sum-exp), which cannot underflow. A non-finite rate raises
ValueError. The result records the nodes used, the sigma spread max(sd)/min(sd) and the
quadrature. The spread is taken over levels with P > 0 only: a dead level enters no rate.
Equal-sigma convergence, 8-30 dB in 2 dB steps, three PMFs per order: 120
nodes are 1.9e-8 (M=16), 2.6e-8 (M=2), 3.7e-8 (M=8) and 4.1e-8 (M=4) from the 320-node
value; 240 nodes (the default for M != 4) are within 4.2e-10 (M=8), 1.5e-10 (M=16) and
7.6e-11 (M=2) of it, and within 3.9e-10 of an independent adaptive Gauss-Kronrod integral
at those orders (5.8e-10 at M=4 forced to 240 nodes). Comparisons finer than 1e-7 across
orders must fix `nodes` on both sides.

With unequal per-level sigma the per-symbol Gauss-Hermite rule is not reliable: nodes
centred on level i with its own sigma do not resolve the narrower Gaussians of the other
levels. Measured worst error (SMD and bmd_raw, PSNR 8-30 dB in 2 dB steps, six sigma
patterns) for sigma spread max/min = 2, 4, 9, 16, 64: M=4 at 120 nodes 1.0e-6, 2.0e-4,
6.3e-3, 6.6e-2, 0.23; M=8 at 240 nodes 1.2e-8, 1.4e-6, 1.1e-3, 7.2e-3, 5.6e-2 (see
docs/ALGORITHM_PROVENANCE.md for all orders and node counts). `gaussian_rates` therefore
integrates unequal-sigma M != 4 with a common-y composite Gauss-Legendre rule (panel
edges at every level mean and mean +- k sd, k = 1..12, 10 nodes per panel, log-sum-exp
throughout), which agrees with an adaptive Gauss-Kronrod reference to 1.0e-13 at spreads
2 to 64 (worst over M = 4, 8, 16, 8-30 dB, six patterns). `quadrature="auto"` selects it
for M != 4 when max(sd)/min(sd) > 1 + 1e-12, and keeps Gauss-Hermite otherwise.
`quadrature="common_grid"` forces it, also at M = 4. M = 4 with the default quadrature
always uses the legacy kernel, so committed PAM4 numbers do not move; a max/min above
3.0 there is unreliable (the 120-node error first exceeds 1e-4 bit at 3.4) and emits a
UserWarning that names the measured error. A call with a spread above 3.0 should pass
quadrature="common_grid". The committed PAM4 path has a spread of about 1.005 (error 3e-8).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq
from scipy.special import logsumexp

from opticps.modulation.pam import SUPPORTED_ORDERS, label_bits
from opticps.shaping.distributions import entropy_bits, symmetric_pam4, validate_probabilities

# Gauss-Hermite nodes per order. 120 is the legacy PAM4 value and must not change. For
# the other orders 120 nodes are 1.9e-8 to 4.1e-8 from convergence at 8-30 dB (equal
# sigma, measured against 320 nodes), so they default to 240 (4.2e-10 vs 320 nodes).
_DEFAULT_NODES = {2: 240, 4: 120, 8: 240, 16: 240}
_LN2 = float(np.log(2.0))

# Common-grid composite Gauss-Legendre integrator. Panel edges sit at mu_i + t sd_i for every
# level i with P(i) > 0 and every integer t in -12..12, so each Gaussian is resolved at its
# own scale and the range covers +-12 sd of every level. 10 Gauss-Legendre nodes per panel.
# Self-convergence against 32 nodes on half-sd panels (M = 2, 4, 8, 16; 8-30 dB in 2 dB
# steps; six sigma patterns; spreads 2, 4, 9, 16, 64, 400), worst of SMD and bmd_raw:
# 6 nodes 7.3e-10, 8 nodes 5.0e-12, 10 nodes 1.0e-13 (chosen), 12 nodes 4.0e-15. Panels
# at the means only with 48 nodes are off by 3e-3 (M=2) to 4e-2 (M=16); see
# docs/ALGORITHM_PROVENANCE.md.
_PANEL_ORDER = 10
_PANEL_SD_STEPS = np.arange(-12, 13, dtype=float)
_SPREAD_EQUAL_TOL = 1e-12  # max(sd) / min(sd) above 1 + this counts as unequal sigma
_MASS_TOL = 1e-9  # the integrated joint density must be 1 to this

# Legacy Gauss-Hermite, nodes centred on each level with that level's sigma, loses accuracy
# as the sigma spread max(sd) / min(sd) grows. Measured worst error in bit (SMD and bmd_raw)
# of the M = 4, 120-node legacy path against the common-grid integrator over PSNR 0-45 dB
# (3 dB steps, plus 8-30 dB in 2 dB steps) and 26 sigma patterns: 4.9e-5 at spread 3,
# 9.2e-5 at 3.3, 1.4e-4 at 3.4 (first above 1e-4), 3.5e-4 at 4. The warning threshold is
# 3.0, below the first crossing, where the error is still half of 1e-4. On the 8-30 dB, six
# pattern grid the crossing is between 3.6 (7.7e-5) and 4 (2.0e-4). Above the threshold the
# Gauss-Hermite result is reported as unreliable with a UserWarning.
_GH_SPREAD_THRESHOLD = 3.0
_GH4_120_WORST_ERROR = (  # (spread, worst error in bit up to that spread)
    (3.0, 4.9e-5),
    (3.5, 1.4e-4),
    (4.0, 3.5e-4),
    (5.0, 1.3e-3),
    (6.0, 2.9e-3),
    (8.0, 1.1e-2),
    (9.0, 1.1e-2),
    (12.0, 3.7e-2),
    (16.0, 7.0e-2),
    (32.0, 1.8e-1),
    (64.0, 2.7e-1),
)


@lru_cache(maxsize=8)
def _quadrature(nodes: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x, w = np.polynomial.hermite.hermgauss(nodes)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(w))):
        raise ValueError(f"Gauss-Hermite rule with {nodes} nodes overflowed; use fewer nodes")
    return x, w / np.sqrt(np.pi)


def _check_order(order: int) -> int:
    if order not in SUPPORTED_ORDERS:
        raise ValueError(f"PAM order must be one of {SUPPORTED_ORDERS}, got {order}")
    return int(order)


def default_nodes(order: int) -> int:
    """Return the default Gauss-Hermite node count for a PAM order."""
    return _DEFAULT_NODES[_check_order(order)]


def _check_nodes(nodes: int | None, order: int) -> int:
    if nodes is None:
        return default_nodes(order)
    if int(nodes) != nodes or nodes < 2:
        raise ValueError(f"Quadrature nodes must be an integer >= 2, got {nodes}")
    return int(nodes)


def noise_sigma_from_psnr_db(psnr_db: float, order: int = 4) -> float:
    """Return sigma on the unipolar alphabet {0, ..., M-1} of unit spacing."""
    _check_order(order)
    return float(order - 1) / 10 ** (psnr_db / 20.0)


@dataclass(frozen=True)
class Rates:
    """Entropy and achievable rates, bits per channel use.

    `bmd` is `max(0, bmd_raw)`. `order` and `nodes` record what was used. `nodes` is the
    Gauss-Hermite node count, or the number of y points of the common grid. `sigma_spread`
    is max(sd) / min(sd) and `quadrature` is "gauss_hermite" or "common_grid".
    """

    entropy: float
    smd: float
    bmd: float
    bmd_raw: float = float("nan")
    order: int = 4
    nodes: int = 120
    sigma_spread: float = 1.0
    quadrature: str = "gauss_hermite"


def _conditional_entropies_direct(
    p: NDArray[np.float64],
    mu: NDArray[np.float64],
    sd: NDArray[np.float64],
    labels: NDArray[np.int8],
    weights: NDArray[np.float64],
    nodes_x: NDArray[np.float64],
) -> tuple[float, float]:
    """Return (H(X|Y), sum_k H(B_k|Y)); legacy kernel kept verbatim for byte identity."""
    conditional_x = 0.0
    conditional_bits = 0.0
    for i in np.flatnonzero(p > 0):
        y = mu[i] + np.sqrt(2.0) * sd[i] * nodes_x
        likelihood = np.exp(-((y[:, None] - mu) ** 2) / (2 * sd**2)) / sd * p
        posterior = likelihood / likelihood.sum(axis=1, keepdims=True)
        conditional_x += p[i] * float(weights @ -np.log2(posterior[:, i]))
        for k in range(labels.shape[1]):
            same = labels[:, k] == labels[i, k]
            conditional_bits += p[i] * float(weights @ -np.log2(posterior[:, same].sum(axis=1)))
    return conditional_x, conditional_bits


def _conditional_entropies_log(
    p: NDArray[np.float64],
    mu: NDArray[np.float64],
    sd: NDArray[np.float64],
    labels: NDArray[np.int8],
    weights: NDArray[np.float64],
    nodes_x: NDArray[np.float64],
) -> tuple[float, float]:
    """Return (H(X|Y), sum_k H(B_k|Y)) with log-sum-exp throughout, no underflow."""
    positive = p > 0
    log_p = np.full(p.shape, -np.inf)
    log_p[positive] = np.log(p[positive])
    log_norm = -np.log(sd) + log_p
    conditional_x = 0.0
    conditional_bits = 0.0
    for i in np.flatnonzero(positive):
        y = mu[i] + np.sqrt(2.0) * sd[i] * nodes_x
        log_joint = -((y[:, None] - mu) ** 2) / (2 * sd**2) + log_norm
        log_total = logsumexp(log_joint, axis=1)
        conditional_x += p[i] * float(weights @ ((log_total - log_joint[:, i]) / _LN2))
        for k in range(labels.shape[1]):
            same = labels[:, k] == labels[i, k]
            log_same = logsumexp(log_joint[:, same], axis=1)
            conditional_bits += p[i] * float(weights @ ((log_total - log_same) / _LN2))
    return conditional_x, conditional_bits


@lru_cache(maxsize=4)
def _legendre(order: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x, w = np.polynomial.legendre.leggauss(order)
    return x, w


def _common_grid(
    p: NDArray[np.float64],
    mu: NDArray[np.float64],
    sd: NDArray[np.float64],
    panel_order: int = _PANEL_ORDER,
    sd_steps: NDArray[np.float64] = _PANEL_SD_STEPS,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return (y, weights) of a composite Gauss-Legendre rule on one y axis.

    Panel edges are mu_i + t sd_i (t in `sd_steps`) for every level with P(i) > 0, so the
    narrowest Gaussian is resolved at its own scale. The range is the union of
    mu_i +- 12 sd_i. Edges closer than 1e-6 min(sd) are merged.
    """
    live = p > 0
    m, s = mu[live], sd[live]
    edges = np.unique((m[:, None] + s[:, None] * sd_steps[None, :]).ravel())
    lo, hi = float((m - 12 * s).min()), float((m + 12 * s).max())
    edges = edges[(edges >= lo) & (edges <= hi)]
    keep = np.concatenate(([True], np.diff(edges) > 1e-6 * float(s.min())))
    edges = edges[keep]
    nodes_x, nodes_w = _legendre(panel_order)
    a, b = edges[:-1], edges[1:]
    half = 0.5 * (b - a)
    y = half[:, None] * nodes_x[None, :] + 0.5 * (a + b)[:, None]
    weights = half[:, None] * nodes_w[None, :]
    return y.ravel(), weights.ravel()


def _conditional_entropies_common_grid(
    p: NDArray[np.float64],
    mu: NDArray[np.float64],
    sd: NDArray[np.float64],
    labels: NDArray[np.int8],
    panel_order: int = _PANEL_ORDER,
    sd_steps: NDArray[np.float64] = _PANEL_SD_STEPS,
) -> tuple[float, float, int]:
    """Return (H(X|Y), sum_k H(B_k|Y), number of y points) on one common y grid.

    Every quantity is integral p(x, y) f(x, y) dy with the joint density p(x, y) on one y
    axis, in log-sum-exp form. Levels with P(x) = 0 do not contribute.
    """
    y, w = _common_grid(p, mu, sd, panel_order, sd_steps)
    live = np.flatnonzero(p > 0)
    log_joint = (
        -0.5 * ((y[:, None] - mu[live]) / sd[live]) ** 2
        - np.log(sd[live])
        - 0.5 * np.log(2 * np.pi)
        + np.log(p[live])
    )
    log_total = logsumexp(log_joint, axis=1)
    joint = np.exp(log_joint)
    mass = float(w @ joint.sum(axis=1))
    if not abs(mass - 1.0) < _MASS_TOL:
        raise ValueError(f"Common-grid integral of the joint density is {mass}, not 1")
    conditional_x = float(w @ (joint * (log_total[:, None] - log_joint)).sum(axis=1)) / _LN2
    log_bits = np.zeros_like(log_joint)
    for k in range(labels.shape[1]):
        bit = labels[live, k]
        group = np.stack(
            [logsumexp(log_joint[:, bit == b], axis=1) if np.any(bit == b) else log_total
             for b in (0, 1)],
            axis=1,
        )  # fmt: skip
        log_bits += group[:, bit] - log_total[:, None]
    conditional_bits = float(w @ -(joint * log_bits).sum(axis=1)) / _LN2
    return conditional_x, conditional_bits, int(y.size)


def _warn_gauss_hermite_unreliable(spread: float, order: int, nodes: int) -> None:
    """Warn that per-level Gauss-Hermite is unreliable at this sigma spread.

    The error table was measured for PAM4 at 120 nodes only. At another order the message
    says so and does not quote it: the threshold is applied there by analogy, not measured.
    """
    if order == 4:
        entry = next(((sp, err) for sp, err in _GH4_120_WORST_ERROR if sp >= spread), None)
        if entry is None:
            measured = f"above {_GH4_120_WORST_ERROR[-1][1]:.1e} bit"
        else:
            measured = f"up to {entry[1]:.1e} bit at spread {entry[0]:g}"
        detail = (
            f"the PAM4 120-node error first exceeds 1e-4 bit at spread 3.4, so spreads above "
            f"{_GH_SPREAD_THRESHOLD:g} are not trusted; measured {measured} (0-45 dB)."
        )
    else:
        detail = (
            f"the error table (first above 1e-4 bit at spread 3.4) was measured for PAM4 at "
            f"120 nodes only and is not a measurement for PAM{order} at {nodes} nodes; the "
            f"threshold {_GH_SPREAD_THRESHOLD:g} is applied here by analogy. Per-order errors "
            f"at spreads 2 to 64 are in docs/ALGORITHM_PROVENANCE.md."
        )
    warnings.warn(
        f"Gauss-Hermite rates (PAM{order}, {nodes} nodes) with sigma spread max/min = "
        f"{spread:.4g} are unreliable: {detail} Pass quadrature='common_grid' for a "
        f"converged result.",
        UserWarning,
        stacklevel=3,
    )


def gaussian_rates(
    probabilities: object,
    means: object,
    sigmas: object,
    order: int | None = None,
    nodes: int | None = None,
    quadrature: str = "auto",
) -> Rates:
    """Compute SMD and BMD rates for per-symbol Gaussian likelihoods.

    `order` is inferred from the PMF length when omitted. `bmd_raw` is the unclipped
    H(X) - sum_k H(B_k|Y); `bmd` applies the explicit [.]^+ clip.

    `quadrature` selects the integrator. "auto" uses the common-grid integrator for
    M != 4 when max(sd)/min(sd) > 1 + 1e-12 and Gauss-Hermite otherwise, so equal-sigma
    results are unchanged and M = 4 always stays on the legacy kernel (bit-identical).
    "common_grid" and "gauss_hermite" force one. `nodes` is the Gauss-Hermite node count
    and is rejected together with the common grid. Gauss-Hermite with a spread above
    `_GH_SPREAD_THRESHOLD` (3.0) emits a UserWarning: it is unreliable there.
    """
    size = int(np.asarray(probabilities, dtype=float).size)
    m_order = _check_order(size if order is None else order)
    p = validate_probabilities(probabilities, m_order)
    mu = np.asarray(means, dtype=float)
    sd = np.asarray(sigmas, dtype=float)
    if mu.shape != (m_order,) or sd.shape != (m_order,):
        raise ValueError(f"means and sigmas must each have {m_order} entries")
    if not (np.all(np.isfinite(mu)) and np.all(np.isfinite(sd))):
        raise ValueError("Means and noise standard deviations must be finite")
    if np.any(sd <= 0):
        raise ValueError("Noise standard deviations must be positive")
    if quadrature not in ("auto", "gauss_hermite", "common_grid"):
        raise ValueError(f"quadrature must be auto, gauss_hermite or common_grid: {quadrature!r}")
    live = p > 0  # a level with P = 0 does not enter any rate, so its sigma does not count
    spread = float(sd[live].max() / sd[live].min())
    unequal = spread > 1.0 + _SPREAD_EQUAL_TOL
    use_grid = quadrature == "common_grid" or (quadrature == "auto" and m_order != 4 and unequal)
    labels = label_bits(m_order)
    if use_grid:
        if nodes is not None:
            raise ValueError(
                "nodes applies to Gauss-Hermite only; the common grid has a fixed rule"
            )
        conditional_x, conditional_bits, n = _conditional_entropies_common_grid(p, mu, sd, labels)
        used = "common_grid"
    else:
        n = _check_nodes(nodes, m_order)
        nodes_x, weights = _quadrature(n)
        if spread > _GH_SPREAD_THRESHOLD:
            _warn_gauss_hermite_unreliable(spread, m_order, n)
        if m_order == 4:
            with np.errstate(all="ignore"):  # a non-finite result triggers the fallback below
                conditional_x, conditional_bits = _conditional_entropies_direct(
                    p, mu, sd, labels, weights, nodes_x
                )
            if not (np.isfinite(conditional_x) and np.isfinite(conditional_bits)):
                conditional_x, conditional_bits = _conditional_entropies_log(
                    p, mu, sd, labels, weights, nodes_x
                )
        else:
            conditional_x, conditional_bits = _conditional_entropies_log(
                p, mu, sd, labels, weights, nodes_x
            )
        used = "gauss_hermite"
    if not (np.isfinite(conditional_x) and np.isfinite(conditional_bits)):
        raise ValueError("Rate computation is not finite (extreme noise level or PMF)")
    h = entropy_bits(p)
    bmd_raw = h - conditional_bits
    return Rates(
        entropy=h,
        smd=h - conditional_x,
        bmd=max(0.0, bmd_raw),
        bmd_raw=bmd_raw,
        order=m_order,
        nodes=n,
        sigma_spread=spread,
        quadrature=used,
    )


def achievable_rates(
    probabilities: object,
    psnr_db: float,
    order: int | None = None,
    nodes: int | None = None,
    quadrature: str = "auto",
) -> Rates:
    """Compute SMD and BMD rates on the peak-limited AWGN channel."""
    size = int(np.asarray(probabilities, dtype=float).size)
    m_order = _check_order(size if order is None else order)
    sigma = noise_sigma_from_psnr_db(psnr_db, m_order)
    levels = np.arange(m_order, dtype=float)
    return gaussian_rates(
        probabilities, levels, np.full(m_order, sigma), m_order, nodes, quadrature
    )


def average_snr(probabilities: object, sigma: float, order: int | None = None) -> float:
    """Return E[x^2] / sigma^2 (linear) on the unipolar alphabet {0, ..., M-1}.

    This is not the PSNR: it depends on the PMF. At equal PSNR it shows how much
    average signal power a shaped PMF spends.
    """
    size = int(np.asarray(probabilities, dtype=float).size)
    p = validate_probabilities(probabilities, _check_order(size if order is None else order))
    if not (np.isfinite(sigma) and sigma > 0):
        raise ValueError("sigma must be positive and finite")
    levels = np.arange(p.size, dtype=float)
    return float(p @ levels**2) / sigma**2


def psnr_for_rate(
    probabilities: object,
    target: float,
    metric: str = "smd",
    order: int | None = None,
    nodes: int | None = None,
    quadrature: str = "auto",
) -> float:
    """Return the PSNR in dB at which a distribution reaches a target rate.

    The root is searched in [-10, 45] dB, the bracket used for PAM4 (unchanged). For
    other orders the bracket is widened outwards only if the target is not bracketed.
    """
    size = int(np.asarray(probabilities, dtype=float).size)
    m_order = _check_order(size if order is None else order)

    def gap(psnr_db: float) -> float:
        rates = achievable_rates(probabilities, psnr_db, m_order, nodes, quadrature)
        return float(getattr(rates, metric)) - target

    lo, hi = -10.0, 45.0
    if m_order != 4:
        while gap(lo) > 0 and lo > -80.0:
            lo -= 10.0
        while gap(hi) < 0 and hi < 120.0:
            hi += 10.0
    return float(brentq(gap, lo, hi, xtol=1e-4))


def optimal_outer_probability(
    psnr_db: float, metric: str = "smd", grid: NDArray[np.float64] | None = None
) -> tuple[float, float]:
    """Return (P0*, rate) over the symmetric PAM4 family by exhaustive grid search.

    PAM4 only. The general-M optimiser is not part of this module.
    """
    points = np.arange(0.02, 0.4951, 0.0025) if grid is None else grid
    values = [getattr(achievable_rates(symmetric_pam4(q), psnr_db), metric) for q in points]
    best = int(np.argmax(values))
    return float(points[best]), float(values[best])
