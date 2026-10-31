"""Symbol probability distributions and their signal statistics.

The electrical and information quantities here say nothing about optical power.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq

from opticps.modulation.pam import pam_levels

Prob = NDArray[np.float64]

UNIFORM = (0.25, 0.25, 0.25, 0.25)
PS70 = (0.15, 0.35, 0.35, 0.15)
PS80 = (0.10, 0.40, 0.40, 0.10)
OUTER70 = (0.35, 0.15, 0.15, 0.35)


def validate_probabilities(probabilities: object, order: int | None = None) -> Prob:
    """Return probabilities as an array, or raise ValueError if they are invalid."""
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 1 or p.size < 2:
        raise ValueError("Probabilities must be a one-dimensional vector")
    if order is not None and p.size != order:
        raise ValueError(f"Expected {order} probabilities, got {p.size}")
    if not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError(f"Probabilities must be finite and non-negative: {p}")
    if abs(p.sum() - 1.0) > 1e-9:
        raise ValueError(f"Probabilities must sum to 1, got {p.sum()}")
    return p


def entropy_bits(probabilities: object) -> float:
    """Return the entropy H(X) in bits."""
    p = validate_probabilities(probabilities)
    nonzero = p[p > 0]
    return float(-(nonzero * np.log2(nonzero)).sum())


def maxwell_boltzmann(lam: float, order: int = 4) -> Prob:
    """Return P(x) = exp(-lam |x|^2) / Z.

    Sign convention: lam > 0 is inner-heavy, lam = 0 is uniform, lam < 0 is outer-heavy.
    """
    levels = pam_levels(order)
    weights = np.exp(-lam * levels**2)
    return weights / weights.sum()


def symmetric_pam4(p_outer: float) -> Prob:
    """Return the symmetric PAM4 distribution with P(-3) = P(+3) = p_outer."""
    if not 0 < p_outer < 0.5:
        raise ValueError(f"p_outer must be inside (0, 0.5), got {p_outer}")
    inner = 0.5 - p_outer
    return np.array([p_outer, inner, inner, p_outer])


def lambda_of_symmetric_pam4(p_outer: float) -> float:
    """Return the Maxwell-Boltzmann lambda equivalent to a symmetric PAM4 distribution."""
    symmetric_pam4(p_outer)
    return float(np.log((0.5 - p_outer) / p_outer) / 8.0)


def symmetric_from_pairs(pair_probabilities: object) -> Prob:
    """Return the symmetric PMF with P(-x_j) = P(+x_j) = q_j, j = 1..M/2.

    q is ordered inner pair first (|x| = 1, 3, ...). The result is in level order,
    lowest level first, so M = 4 gives [q_2, q_1, q_1, q_2]. Each q_j must be finite
    and non-negative and the q_j must sum to 1/2.
    """
    q = np.asarray(pair_probabilities, dtype=float)
    if q.ndim != 1 or q.size < 1:
        raise ValueError("Pair probabilities must be a non-empty one-dimensional vector")
    if not np.all(np.isfinite(q)) or np.any(q < 0):
        raise ValueError(f"Pair probabilities must be finite and non-negative: {q}")
    if abs(q.sum() - 0.5) > 1e-9:
        raise ValueError(f"Pair probabilities must sum to 1/2, got {q.sum()}")
    return np.concatenate([q[::-1], q])


def pairs_of(probabilities: object, tol: float = 1e-9) -> Prob:
    """Return q_j = P(+x_j), inner pair first, of a symmetric PMF; raise if not symmetric."""
    p = validate_probabilities(probabilities)
    if p.size % 2:
        raise ValueError(f"A symmetric PMF needs an even alphabet size, got {p.size}")
    if np.max(np.abs(p - p[::-1])) > tol:
        raise ValueError(f"Distribution is not symmetric about zero: {p.tolist()}")
    return p[p.size // 2 :].copy()


def _mb_stable(lam: float, order: int) -> Prob:
    """Maxwell-Boltzmann PMF with the exponent shifted, safe for large |lam|."""
    exponent = -lam * pam_levels(order) ** 2
    weights = np.exp(exponent - exponent.max())
    return weights / weights.sum()


def mb_for_entropy(entropy: float, order: int, sign: int = 1) -> Prob:
    """Return the Maxwell-Boltzmann PMF of the given entropy, by a root find on lambda.

    sign = +1 selects inner-heavy (lam > 0), sign = -1 outer-heavy (lam < 0), with the
    repo convention P(x) proportional to exp(-lam x^2). MB(+lam) and MB(-lam) have the
    same entropy only at M = 4 (M = 2 is trivially uniform), not for M >= 8, so the
    entropy is matched on the chosen side.
    The reachable range is (1, log2 M] bits for M >= 4: lam -> +-infinity puts all mass
    on the two innermost or outermost levels (1 bit, never attained). M = 2 admits only
    1 bit. Raises ValueError when the target is outside that range.
    """
    if sign not in (1, -1):
        raise ValueError(f"sign must be +1 (inner-heavy) or -1 (outer-heavy), got {sign}")
    pam_levels(order)  # validates the order
    top = float(np.log2(order))
    if not np.isfinite(entropy):
        raise ValueError(f"Entropy must be finite, got {entropy}")
    if order == 2:
        if abs(entropy - 1.0) > 1e-9:
            raise ValueError(f"PAM2 has entropy 1 bit at most, target {entropy} is unreachable")
        return np.array([0.5, 0.5])
    if entropy > top + 1e-12 or entropy <= 1.0:
        raise ValueError(
            f"Entropy {entropy} is unreachable for MB at M={order}: need 1 < H <= {top}"
        )
    if entropy >= top - 1e-12:
        return np.full(order, 1.0 / order)

    def gap(mu: float) -> float:
        return entropy_bits(_mb_stable(sign * mu, order)) - entropy

    hi = 1.0
    while gap(hi) > 0:
        hi *= 2.0  # ends: for large mu the PMF is exactly (1/2, 1/2) on two levels, H = 1 < target
    mu = brentq(gap, 0.0, hi, xtol=1e-15, rtol=1e-14)
    return _mb_stable(sign * mu, order)


@dataclass(frozen=True)
class SignalStatistics:
    """Moments of the symbol alphabet, in normalized level units."""

    entropy_bits: float
    energy: float
    rms: float
    peak: float
    papr_db: float
    mean: float


def signal_statistics(probabilities: object, levels: object | None = None) -> SignalStatistics:
    """Compute entropy, energy, RMS, peak and PAPR of a discrete alphabet."""
    p = validate_probabilities(probabilities)
    x = pam_levels(p.size) if levels is None else np.asarray(levels, dtype=float)
    energy = float(p @ x**2)
    peak = float(np.abs(x[p > 0]).max())
    return SignalStatistics(
        entropy_bits=entropy_bits(p),
        energy=energy,
        rms=float(np.sqrt(energy)),
        peak=peak,
        papr_db=float(10 * np.log10(peak**2 / energy)),
        mean=float(p @ x),
    )
