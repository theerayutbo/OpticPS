"""Frozen estimators M1 to M4 of plan section R2.2, as code (Stage 3A, gate E2 part a).

Every function takes samples that are already normalised by the one affine map of the plan
(`x_norm = (x - c0) / g0`, fixed on B2B and applied unchanged to every length). Nothing here reads
a file, rescales a length on its own, or touches a bit or symbol reference. Default-deny: a
non-finite value, an empty or too short window, a non-positive power spectral density or a
degenerate level estimate raises `BenchmarkError`; no function returns a number it could not
justify.

The estimator ids of `holdout.ESTIMATORS` label these functions. They do not verify the code; the
code identity of E2 (plan Revision 10) is a list of file hashes and is narrower still.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import welch

from opticps.benchmarks.provenance import BenchmarkError

FloatArray = NDArray[np.float64]

QUANTILE_POINTS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)  # M3
W1_POINTS = 65536  # M2: N equally spaced probabilities u = (j - 0.5) / N
KMEANS_K = 4
KMEANS_MAX_ITERATIONS = 200
KMEANS_TOLERANCE = 1e-9  # largest centroid move, in units of the sample standard deviation
KMEANS_INITIAL_QUANTILES = (0.125, 0.375, 0.625, 0.875)
WELCH_SEGMENT = 4096
WELCH_OVERLAP = 2048
MIN_SAMPLES = 8 * WELCH_SEGMENT  # fewer than this and a Welch average means little


def require_window(x: object, name: str, *, minimum: int = MIN_SAMPLES) -> FloatArray:
    """A one-dimensional finite float64 array of at least `minimum` samples, else an error."""
    array = np.asarray(x, dtype=np.float64)
    if array.ndim != 1:
        raise BenchmarkError(f"{name}: samples must be one-dimensional")
    if array.size < minimum:
        raise BenchmarkError(f"{name}: {array.size} samples, at least {minimum} are needed")
    if not np.isfinite(array).all():
        raise BenchmarkError(f"{name}: contains non-finite samples")
    return array


def normalise(x: FloatArray, c0: float, g0: float) -> FloatArray:
    """The one affine map of R2.2. A non-finite or non-positive scale is refused."""
    if not (math.isfinite(c0) and math.isfinite(g0)) or g0 <= 0:
        raise BenchmarkError("normalisation needs a finite offset and a positive finite gap")
    return (np.asarray(x, dtype=np.float64) - c0) / g0


def kmeans_levels(x: FloatArray) -> tuple[FloatArray, FloatArray]:
    """R2.2 level centroids: 1-D k-means, k = 4, Lloyd iterations. Returns (centroids, shares).

    Initial centroids at the 12.5, 37.5, 62.5 and 87.5 % quantiles (type 7); stop when the largest
    centroid move is below 1e-9 times the sample standard deviation or after 200 iterations;
    centroids ascending. The assignment uses the sorted samples, which gives the same partition as
    a nearest-centroid search. An empty cluster, or a window with no spread, is refused.
    """
    values = require_window(x, "level estimate", minimum=KMEANS_K * 16)
    spread = float(values.std())
    if not spread > 0.0:
        raise BenchmarkError("level estimate: the window has no spread")
    ordered = np.sort(values)
    cumulative = np.concatenate([[0.0], np.cumsum(ordered, dtype=np.float64)])
    centroids = np.quantile(values, KMEANS_INITIAL_QUANTILES)
    edges = np.array([0, 0, 0, 0, ordered.size])
    for _ in range(KMEANS_MAX_ITERATIONS):
        midpoints = (centroids[1:] + centroids[:-1]) / 2.0
        edges = np.concatenate(
            [[0], np.searchsorted(ordered, midpoints, side="left"), [ordered.size]]
        )
        counts = np.diff(edges)
        if (counts <= 0).any():
            raise BenchmarkError("level estimate: a cluster is empty")
        updated = (cumulative[edges[1:]] - cumulative[edges[:-1]]) / counts
        move = float(np.max(np.abs(updated - centroids)))
        centroids = updated
        if move < KMEANS_TOLERANCE * spread:
            break
    counts = np.diff(edges)
    order = np.argsort(centroids)
    return centroids[order], counts[order] / ordered.size


def renormalise(x: FloatArray) -> tuple[FloatArray, float, float]:
    """Gain-invariant form of a window: (x - c) / g from its own four centroids.

    Returns (window, c, g) with c the mean centroid and g the mean gap, in the units of the input.
    Plan R12.2 applies it to every length and every prediction alike and reports g as the
    amplitude ratio (launch power is unknown, so the amplitude is reported, never tested).
    """
    values = require_window(x, "window to renormalise", minimum=KMEANS_K * 16)
    centroids, _ = kmeans_levels(values)
    gap = float(np.diff(centroids).mean())
    if not gap > 0.0:
        raise BenchmarkError("renormalise: the mean level gap is not positive")
    centre = float(centroids.mean())
    return (values - centre) / gap, centre, gap


def level_gaps(centroids: FloatArray) -> FloatArray:
    """The three adjacent gaps of four ascending centroids."""
    gaps = np.diff(np.asarray(centroids, dtype=np.float64))
    if gaps.shape != (3,) or not (gaps > 0).all():
        raise BenchmarkError("level gaps need four strictly ascending centroids")
    return gaps


def m1_from_gaps(gaps_m: FloatArray, gaps_p: FloatArray) -> float:
    """M1 from two gap vectors: the L-infinity norm of their difference."""
    return float(np.max(np.abs(np.asarray(gaps_m) - np.asarray(gaps_p))))


def m1_level_spacing(measured: FloatArray, predicted: FloatArray) -> float:
    """M1: L-infinity norm of the difference of the three centroid gaps, in B2B gap units."""
    return m1_from_gaps(
        level_gaps(kmeans_levels(measured)[0]), level_gaps(kmeans_levels(predicted)[0])
    )


def quantile_function(x: FloatArray, probabilities: FloatArray) -> FloatArray:
    """Hyndman-Fan type 7: linear interpolation between order statistics, h = (n - 1) p.

    One sort and an interpolation (np.quantile with tens of thousands of probabilities is slow).
    """
    p = np.asarray(probabilities, dtype=np.float64)
    if not ((p >= 0.0).all() and (p <= 1.0).all()):
        raise BenchmarkError("quantile probabilities must lie in [0, 1]")
    ordered = np.sort(np.asarray(x, dtype=np.float64))
    h = (ordered.size - 1) * p
    lower = np.floor(h).astype(np.int64)
    upper = np.minimum(lower + 1, ordered.size - 1)
    return np.asarray(
        ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower]), dtype=np.float64
    )


def w1_probabilities() -> FloatArray:
    return (np.arange(W1_POINTS, dtype=np.float64) + 0.5) / W1_POINTS


def m2_wasserstein1(measured: FloatArray, predicted: FloatArray) -> float:
    """M2: mean over u = (j - 0.5) / 65536 of |Q_m(u) - Q_p(u)|."""
    u = w1_probabilities()
    q_m = quantile_function(require_window(measured, "measured"), u)
    q_p = quantile_function(require_window(predicted, "predicted"), u)
    return float(np.mean(np.abs(q_m - q_p)))


def m3_quantile_error(measured: FloatArray, predicted: FloatArray) -> float:
    """M3: largest |Q_m(p) - Q_p(p)| over the seven points of `QUANTILE_POINTS`."""
    p = np.asarray(QUANTILE_POINTS, dtype=np.float64)
    q_m = quantile_function(require_window(measured, "measured"), p)
    q_p = quantile_function(require_window(predicted, "predicted"), p)
    return float(np.max(np.abs(q_m - q_p)))


def welch_density(x: FloatArray, sample_rate_hz: float) -> tuple[FloatArray, FloatArray]:
    """R2.2 Welch estimate: periodic Hann, 4096-sample segments, 50 % overlap, constant detrend,
    density scaling, one-sided."""
    if not (math.isfinite(sample_rate_hz) and sample_rate_hz > 0):
        raise BenchmarkError("the sample rate must be finite and positive")
    f, p = welch(
        require_window(x, "spectrum input"),
        fs=sample_rate_hz,
        window="hann",
        nperseg=WELCH_SEGMENT,
        noverlap=WELCH_OVERLAP,
        detrend="constant",
        scaling="density",
        return_onesided=True,
    )
    return np.asarray(f, dtype=np.float64), np.asarray(p, dtype=np.float64)


def band_bins(frequency: FloatArray, baud_bd: float) -> NDArray[np.bool_]:
    """Bins with frequency up to the baud rate (inclusive, with a part in 1e9 of slack)."""
    mask: NDArray[np.bool_] = frequency <= baud_bd * (1.0 + 1e-9)
    if int(mask.sum()) < 8:
        raise BenchmarkError("fewer than 8 spectral bins up to the baud rate")
    return mask


def m4_from_densities(p_m: FloatArray, p_p: FloatArray) -> float:
    """M4 from two in-band density vectors: sqrt of the mean of (10 log10(P_m / P_p))^2, in dB."""
    if p_m.shape != p_p.shape or not ((p_m > 0).all() and (p_p > 0).all()):
        raise BenchmarkError("spectral distance: a power spectral density bin is not positive")
    ratio_db = 10.0 * np.log10(p_m / p_p)
    value = float(np.sqrt(np.mean(ratio_db**2)))
    if not math.isfinite(value):
        raise BenchmarkError("spectral distance is not finite")
    return value


def m4_log_spectral_distance(
    measured: FloatArray, predicted: FloatArray, sample_rate_hz: float, baud_bd: float
) -> float:
    """M4: sqrt of the mean over bins up to the baud rate of (10 log10(P_m / P_p))^2, in dB."""
    f, p_m = welch_density(measured, sample_rate_hz)
    _, p_p = welch_density(predicted, sample_rate_hz)
    keep = band_bins(f, baud_bd)
    return m4_from_densities(p_m[keep], p_p[keep])


@dataclass(frozen=True)
class WindowSummary:
    """Everything the four metrics use from one window, so a fixed reference is summarised once.

    The numbers are the ones the stand-alone functions compute; `metrics_between` of two summaries
    equals `all_metrics` of the two windows (a test checks it).
    """

    gaps: FloatArray
    quantile_u: FloatArray
    quantile_p: FloatArray
    density: FloatArray  # Welch density in the bins up to the baud rate
    frequency: FloatArray  # the frequencies of those bins
    centroids: FloatArray  # descriptive, for the pre-registration; no metric uses them
    shares: FloatArray
    std: float


def summarise_window(x: FloatArray, sample_rate_hz: float, baud_bd: float) -> WindowSummary:
    window = require_window(x, "window")
    frequency, density = welch_density(window, sample_rate_hz)
    centroids, shares = kmeans_levels(window)
    keep = band_bins(frequency, baud_bd)
    return WindowSummary(
        level_gaps(centroids),
        quantile_function(window, w1_probabilities()),
        quantile_function(window, np.asarray(QUANTILE_POINTS, dtype=np.float64)),
        density[keep],
        frequency[keep],
        centroids,
        shares,
        float(window.std()),
    )


def metrics_between(measured: WindowSummary, predicted: WindowSummary) -> dict[str, float]:
    return {
        "M1_level_spacing": m1_from_gaps(measured.gaps, predicted.gaps),
        "M2_wasserstein1_amplitude": float(
            np.mean(np.abs(measured.quantile_u - predicted.quantile_u))
        ),
        "M3_quantile_error": float(np.max(np.abs(measured.quantile_p - predicted.quantile_p))),
        "M4_log_spectral_distance": m4_from_densities(measured.density, predicted.density),
    }


def all_metrics(
    measured: FloatArray, predicted: FloatArray, sample_rate_hz: float, baud_bd: float
) -> dict[str, float]:
    """The four metrics of R2.2 between a measured and a predicted normalised window."""
    return metrics_between(
        summarise_window(measured, sample_rate_hz, baud_bd),
        summarise_window(predicted, sample_rate_hz, baud_bd),
    )
