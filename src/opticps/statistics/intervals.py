"""Uncertainty estimates: exact binomial intervals and block or run bootstrap."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from scipy.stats import beta


def clopper_pearson(errors: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Return the exact binomial interval. Valid at zero errors, unlike a normal approximation.

    Assumes independent trials, so treat it as optimistic for correlated errors.
    """
    if trials <= 0 or not 0 <= errors <= trials:
        raise ValueError(f"Invalid counts: {errors} errors in {trials} trials")
    alpha = 1 - confidence
    low = 0.0 if errors == 0 else float(beta.ppf(alpha / 2, errors, trials - errors + 1))
    high = 1.0 if errors == trials else float(beta.ppf(1 - alpha / 2, errors + 1, trials - errors))
    return low, high


def bootstrap_interval(
    units: Sequence[Any],
    statistic: Callable[[Sequence[Any]], float],
    rng: np.random.Generator,
    resamples: int = 2000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap that resamples whole units (blocks, captures or runs).

    Samples inside one unit are correlated, so the unit must be the block or capture.
    """
    if len(units) < 2:
        raise ValueError("Bootstrap needs at least two independent units")
    n = len(units)
    values = [statistic([units[i] for i in rng.integers(0, n, n)]) for _ in range(resamples)]
    alpha = (1 - confidence) / 2
    return float(np.quantile(values, alpha)), float(np.quantile(values, 1 - alpha))


def paired_difference_interval(
    a: Sequence[float],
    b: Sequence[float],
    rng: np.random.Generator,
    resamples: int = 4000,
) -> tuple[float, tuple[float, float]]:
    """Return mean(a - b) and its bootstrap interval, resampling paired runs."""
    if len(a) != len(b):
        raise ValueError("Paired comparison needs equal run counts")
    differences = [float(x - y) for x, y in zip(a, b, strict=True)]

    def mean_of(sample: Sequence[Any]) -> float:
        return float(np.mean(sample))

    interval = bootstrap_interval(differences, mean_of, rng, resamples)
    return float(np.mean(differences)), interval
