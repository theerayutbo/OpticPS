"""Select a symmetric PAM4 distribution from training data only.

The same code path serves simulated training captures now and Southampton training
captures later. Every candidate is logged. Test captures can never enter: selection
refuses overlapping capture identifiers.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.modulation.pam import pam_levels
from opticps.optimization.rates import gaussian_rates, noise_sigma_from_psnr_db, psnr_for_rate
from opticps.shaping.distributions import UNIFORM, lambda_of_symmetric_pam4, symmetric_pam4


class DataLeakageError(ValueError):
    """A capture was used for both tuning and final evaluation."""


def assert_disjoint(training_ids: Iterable[str], test_ids: Iterable[str]) -> None:
    """Raise if any capture appears in both sets."""
    overlap = set(training_ids) & set(test_ids)
    if overlap:
        raise DataLeakageError(f"Captures used for both tuning and test: {sorted(overlap)}")


@dataclass(frozen=True)
class ChannelEstimate:
    """Per-level Gaussian model fitted to training data."""

    means: list[float]
    sigmas: list[float]
    samples: int


def estimate_channel(indices: NDArray[np.integer], received: NDArray[np.floating]) -> ChannelEstimate:
    """Fit a mean and standard deviation for each of the four levels."""
    indices = np.asarray(indices)
    received = np.asarray(received, dtype=float)
    if indices.size != received.size:
        raise ValueError("Reference and received lengths differ")
    means, sigmas = [], []
    for level in range(4):
        values = received[indices == level]
        if values.size < 2:
            raise ValueError(f"Training data has too few samples of level {level}")
        means.append(float(values.mean()))
        sigmas.append(float(values.std(ddof=1)))
    return ChannelEstimate(means, sigmas, int(indices.size))


def simulate_training_capture(
    psnr_db: float, samples: int, seed: int
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Return simulated, uniformly sent training symbols through peak-limited AWGN."""
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, 4, samples)
    sigma = 2.0 * noise_sigma_from_psnr_db(psnr_db)
    return indices, pam_levels(4)[indices] + rng.normal(0.0, sigma, samples)


@dataclass(frozen=True)
class Selection:
    """Chosen distribution, with the full record of how it was chosen."""

    p_outer: float
    probabilities: list[float]
    lambda_value: float
    objective: float
    metric: str
    block_length: int
    source: str
    channel: ChannelEstimate
    candidates: list[dict[str, float]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def select_distribution(
    training_indices: NDArray[np.integer],
    training_received: NDArray[np.floating],
    source: str,
    metric: str = "bmd",
    block_length: int = 1024,
    grid_step: float = 0.005,
) -> Selection:
    """Maximize rate minus finite-block matcher loss over the symmetric family."""
    channel = estimate_channel(training_indices, training_received)
    candidates = []
    for p_outer in np.arange(0.05, 0.4951, grid_step):
        p_outer = round(float(p_outer), 6)
        probabilities = symmetric_pam4(p_outer)
        rates = gaussian_rates(probabilities, channel.means, channel.sigmas)
        loss = ConstantCompositionMatcher.from_probabilities(probabilities, block_length).rate_loss
        rate = rates.bmd if metric == "bmd" else rates.smd
        candidates.append(
            {
                "p_outer": p_outer,
                "lambda": lambda_of_symmetric_pam4(p_outer),
                "entropy": rates.entropy,
                "rate": rate,
                "matcher_loss": loss,
                "objective": rate - loss,
            }
        )
    best = max(candidates, key=lambda c: c["objective"])
    return Selection(
        p_outer=best["p_outer"],
        probabilities=symmetric_pam4(best["p_outer"]).tolist(),
        lambda_value=best["lambda"],
        objective=best["objective"],
        metric=metric,
        block_length=block_length,
        source=source,
        channel=channel,
        candidates=candidates,
    )


def design_point_selection(
    design_rate: float, metric: str, samples: int, seed: int, block_length: int, grid_step: float
) -> tuple[float, Selection]:
    """Select at the PSNR where uniform PAM4 reaches the declared design rate."""
    psnr_db = psnr_for_rate(UNIFORM, design_rate, metric)
    indices, received = simulate_training_capture(psnr_db, samples, seed)
    selection = select_distribution(
        indices,
        received,
        source=f"simulated AWGN training, peak-limited, PSNR {psnr_db:.3f} dB; not measured",
        metric=metric,
        block_length=block_length,
        grid_step=grid_step,
    )
    return psnr_db, selection
