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

Numerics: expectations over the Gaussian noise use Gauss-Hermite quadrature. `nodes`
defaults to 120 for M = 4 (the legacy value) and 240 otherwise, see `default_nodes`.
For M = 4 the original direct-likelihood kernel is kept operation for operation, so
legacy results are bit-identical; it falls back to the log-domain kernel if it ever
produces a non-finite value. Every other order uses the log-domain kernel
(log-sum-exp), which cannot underflow. A non-finite rate raises ValueError. The
result records the nodes used. The node-count convergence figures were measured with
equal sigma on all levels; with unequal per-level sigma the rule converges more slowly
(see docs/ALGORITHM_PROVENANCE.md). Comparisons finer than 1e-7 across orders must fix
`nodes` on both sides.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

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

    `bmd` is `max(0, bmd_raw)`. `order` and `nodes` record what was used.
    """

    entropy: float
    smd: float
    bmd: float
    bmd_raw: float = float("nan")
    order: int = 4
    nodes: int = 120


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


def gaussian_rates(
    probabilities: object,
    means: object,
    sigmas: object,
    order: int | None = None,
    nodes: int | None = None,
) -> Rates:
    """Compute SMD and BMD rates for per-symbol Gaussian likelihoods.

    `order` is inferred from the PMF length when omitted. `bmd_raw` is the unclipped
    H(X) - sum_k H(B_k|Y); `bmd` applies the explicit [.]^+ clip.
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
    n = _check_nodes(nodes, m_order)
    nodes_x, weights = _quadrature(n)
    labels = label_bits(m_order)
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
    )


def achievable_rates(
    probabilities: object,
    psnr_db: float,
    order: int | None = None,
    nodes: int | None = None,
) -> Rates:
    """Compute SMD and BMD rates on the peak-limited AWGN channel."""
    size = int(np.asarray(probabilities, dtype=float).size)
    m_order = _check_order(size if order is None else order)
    sigma = noise_sigma_from_psnr_db(psnr_db, m_order)
    levels = np.arange(m_order, dtype=float)
    return gaussian_rates(probabilities, levels, np.full(m_order, sigma), m_order, nodes)


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
) -> float:
    """Return the PSNR in dB at which a distribution reaches a target rate.

    The root is searched in [-10, 45] dB, the bracket used for PAM4 (unchanged). For
    other orders the bracket is widened outwards only if the target is not bracketed.
    """
    size = int(np.asarray(probabilities, dtype=float).size)
    m_order = _check_order(size if order is None else order)

    def gap(psnr_db: float) -> float:
        rates = achievable_rates(probabilities, psnr_db, m_order, nodes)
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
