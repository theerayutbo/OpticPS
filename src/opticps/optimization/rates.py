"""Achievable rates of discrete inputs on the real AWGN channel.

R_SMD = I(X;Y) and R_BMD = [H(X) - sum_k H(B_k|Y)]^+ follow Boecherer et al. (2015)
and Wiegart et al. (2020). PSNR is defined on the unipolar alphabet {0, 1, 2, 3} as
3^2 / sigma^2, which keeps the numbers comparable with Wiegart et al.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq

from opticps.modulation.pam import label_bits
from opticps.shaping.distributions import entropy_bits, validate_probabilities, symmetric_pam4

_NODES, _WEIGHTS = np.polynomial.hermite.hermgauss(120)
_WEIGHTS = _WEIGHTS / np.sqrt(np.pi)
_UNIPOLAR = np.arange(4, dtype=float)


def noise_sigma_from_psnr_db(psnr_db: float) -> float:
    """Return sigma on the unipolar alphabet of unit spacing."""
    return 3.0 / 10 ** (psnr_db / 20.0)


@dataclass(frozen=True)
class Rates:
    """Entropy and achievable rates, bits per channel use."""

    entropy: float
    smd: float
    bmd: float


def achievable_rates(probabilities: object, psnr_db: float) -> Rates:
    """Compute SMD and BMD rates by Gauss-Hermite integration."""
    p = validate_probabilities(probabilities, 4)
    sigma = noise_sigma_from_psnr_db(psnr_db)
    labels = label_bits(4)
    support = np.flatnonzero(p > 0)
    conditional_x = 0.0
    conditional_bits = 0.0
    for i in support:
        y = _UNIPOLAR[i] + np.sqrt(2.0) * sigma * _NODES
        likelihood = np.exp(-((y[:, None] - _UNIPOLAR) ** 2) / (2 * sigma**2)) * p
        posterior = likelihood / likelihood.sum(axis=1, keepdims=True)
        conditional_x += p[i] * float(_WEIGHTS @ -np.log2(posterior[:, i]))
        for k in range(2):
            same = labels[:, k] == labels[i, k]
            conditional_bits += p[i] * float(_WEIGHTS @ -np.log2(posterior[:, same].sum(axis=1)))
    h = entropy_bits(p)
    return Rates(entropy=h, smd=h - conditional_x, bmd=max(0.0, h - conditional_bits))


def psnr_for_rate(probabilities: object, target: float, metric: str = "smd") -> float:
    """Return the PSNR in dB at which a distribution reaches a target rate."""

    def gap(psnr_db: float) -> float:
        return float(getattr(achievable_rates(probabilities, psnr_db), metric)) - target

    return float(brentq(gap, -10.0, 45.0, xtol=1e-4))


def optimal_outer_probability(
    psnr_db: float, metric: str = "smd", grid: NDArray[np.float64] | None = None
) -> tuple[float, float]:
    """Return (P0*, rate) over the symmetric PAM4 family by exhaustive grid search."""
    points = np.arange(0.02, 0.4951, 0.0025) if grid is None else grid
    values = [getattr(achievable_rates(symmetric_pam4(q), psnr_db), metric) for q in points]
    best = int(np.argmax(values))
    return float(points[best]), float(values[best])
