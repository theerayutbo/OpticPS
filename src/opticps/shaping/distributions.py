"""Symbol probability distributions and their signal statistics.

The electrical and information quantities here say nothing about optical power.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

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
    """Return P(x) = exp(-lam |x|^2) / Z. lam = 0 is uniform; lam < 0 is outer-heavy."""
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
