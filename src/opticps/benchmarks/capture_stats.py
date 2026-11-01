"""Descriptive, reference-free statistics of one external capture (Stage 3A, gate E1).

Every number here is computed from the samples alone, in streaming blocks, and is labelled
`normalized`: samples are expressed as z = (x - mean) / std of the same capture (the mean and std in
file units are returned as `normalization`, and are neither volts nor optical power). Nothing is
fitted to another capture, and nothing here is a bit or symbol error rate.

Level-based values (cluster centres, spacings, eye openings, the decision-error proxy) are blind:
they come from clustering the waveform and carry the prefix `estimated_`. They are inferred
quantities, not measurements of transmitted levels. `measured_ber`, `measured_ser` and
`post_fec_ber` refuse with REFERENCE_SEQUENCE_MISSING unless a reference sequence that a source
states (`Provenance.PUBLISHED_MEASUREMENT`) is supplied; a sequence recovered from any capture is
never a reference.

Streaming results do not depend on the block size: moments are merged exactly, histogram counts are
integers over a range fixed by the first pass, and the Welch average and the timing windows are cut
by absolute sample index, not by block.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from opticps.benchmarks.external_capture import (
    DEFAULT_BLOCK_SAMPLES,
    SCALE_NORMALIZED,
    ExternalCapture,
    SampleLayout,
)
from opticps.benchmarks.provenance import BenchmarkError, ErrorCode, Provenance
from opticps.benchmarks.timing import (
    TimingModel,
    TimingTracker,
    Windower,
    interpolate_cubic,
    samples_per_symbol,
)

FloatArray = NDArray[np.float64]
Progress = Callable[[int, int], None]
QUANTILES = (0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999)
UNITS_NOTE = (
    "normalized: z = (x - mean) / std of this capture; not volts, not optical power, not dBm"
)
PROXY_CAVEAT = (
    "Gaussian-tail estimate from blind four-level clusters of the recovered waveform. It uses no "
    "transmitted reference, is circular (the clusters are fitted to the same samples), ignores ISI "
    "and non-Gaussian tails, and is NOT a BER or SER and not comparable with a published BER."
)


# ---------------------------------------------------------------------------- refusals
@dataclass(frozen=True)
class PublishedReference:
    """A transmitted sequence that a source states. Anything else is not a reference."""

    values: NDArray[np.int64]
    provenance: Provenance
    source_ref: str


def _require_reference(reference: PublishedReference | None, what: str) -> NDArray[np.int64]:
    if reference is None:
        raise BenchmarkError(
            f"{what}: no transmitted sequence is documented for this capture",
            ErrorCode.REFERENCE_SEQUENCE_MISSING,
        )
    if reference.provenance is not Provenance.PUBLISHED_MEASUREMENT or not reference.source_ref:
        raise BenchmarkError(
            f"{what}: the sequence is {reference.provenance.value}; only a sequence a source "
            "states "
            "is a reference, and a sequence recovered from a capture never is",
            ErrorCode.REFERENCE_SEQUENCE_MISSING,
        )
    return reference.values


def measured_ber(
    decided_bits: NDArray[np.int64], reference: PublishedReference | None = None
) -> float:
    """Bit error rate against a published reference; otherwise REFERENCE_SEQUENCE_MISSING."""
    truth = _require_reference(reference, "BER")
    if truth.shape != decided_bits.shape:
        raise BenchmarkError("BER: decisions and reference differ in length")
    return float(np.mean(truth != decided_bits))


def measured_ser(
    decided_symbols: NDArray[np.int64], reference: PublishedReference | None = None
) -> float:
    """Symbol error rate against a published reference; otherwise REFERENCE_SEQUENCE_MISSING."""
    truth = _require_reference(reference, "SER")
    if truth.shape != decided_symbols.shape:
        raise BenchmarkError("SER: decisions and reference differ in length")
    return float(np.mean(truth != decided_symbols))


def post_fec_ber(
    decided_bits: NDArray[np.int64], reference: PublishedReference | None = None
) -> float:
    """Post-FEC BER: REFERENCE_SEQUENCE_MISSING without a reference; FEC decoding is not built."""
    _require_reference(reference, "post-FEC BER")
    raise BenchmarkError("post-FEC BER needs an FEC decoder, which is not implemented in E1")


# ---------------------------------------------------------------------------- accumulators
class _Moments:
    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, block: FloatArray) -> None:
        nb = block.size
        mb = float(block.mean())
        m2b = float(((block - mb) ** 2).sum())
        total = self.n + nb
        delta = mb - self.mean
        self.mean += delta * nb / total
        self.m2 += m2b + delta * delta * self.n * nb / total
        self.n = total

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / self.n)


class _Extremes:
    def __init__(self) -> None:
        self.low = math.inf
        self.high = -math.inf
        self.at_low = 0
        self.at_high = 0
        self.run_last: float | None = None
        self.run_now = 0
        self.run_longest = 0

    def add(self, b: FloatArray) -> None:
        lo, hi = float(b.min()), float(b.max())
        if lo < self.low:
            self.low, self.at_low = lo, int((b == lo).sum())
        elif lo == self.low:
            self.at_low += int((b == lo).sum())
        if hi > self.high:
            self.high, self.at_high = hi, int((b == hi).sum())
        elif hi == self.high:
            self.at_high += int((b == hi).sum())
        edges = np.concatenate(([-1], np.flatnonzero(b[1:] != b[:-1]), [b.size - 1]))
        lengths = np.diff(edges)
        if self.run_last is not None and b[0] == self.run_last:
            lengths[0] += self.run_now
        self.run_longest = max(self.run_longest, int(lengths.max()))
        self.run_now, self.run_last = int(lengths[-1]), float(b[-1])


class WelchAccumulator:
    """Welch PSD of a stream: periodic Hann, 50 % overlap, constant detrend, density, one-sided.

    Frequencies are in cycles per sample (sample rate taken as 1), so the spectrum of a normalized
    waveform is scale-free. Segments are cut by absolute index, so the result does not depend on
    how the stream was split into blocks.
    """

    def __init__(self, nperseg: int = 4096) -> None:
        if nperseg < 8 or nperseg % 2:
            raise BenchmarkError("nperseg must be an even integer of at least 8")
        self.nperseg = nperseg
        self.step = nperseg // 2
        k = np.arange(nperseg)
        self.window = 0.5 - 0.5 * np.cos(2.0 * np.pi * k / nperseg)
        self._carry = np.empty(0)
        self._sum = np.zeros(nperseg // 2 + 1)
        self.segments = 0

    def add(self, block: FloatArray) -> None:
        buffer = block if self._carry.size == 0 else np.concatenate([self._carry, block])
        if buffer.size < self.nperseg:
            self._carry = buffer
            return
        count = (buffer.size - self.nperseg) // self.step + 1
        view = sliding_window_view(buffer, self.nperseg)[:: self.step][:count]
        rows = max(1, (1 << 14) // self.nperseg)  # bounds the working copies
        for first in range(0, count, rows):
            chunk = view[first : first + rows]
            chunk = (chunk - chunk.mean(axis=1, keepdims=True)) * self.window
            self._sum += (np.abs(np.fft.rfft(chunk, axis=1)) ** 2).sum(axis=0)
        self.segments += count
        self._carry = buffer[count * self.step :].copy()

    def result(self) -> tuple[FloatArray, FloatArray]:
        if self.segments == 0:
            raise BenchmarkError("no complete PSD segment: the record is shorter than nperseg")
        psd = self._sum / (self.segments * float((self.window**2).sum()))
        psd[1:-1] *= 2.0
        return np.asarray(np.fft.rfftfreq(self.nperseg, d=1.0), dtype=np.float64), psd


# ---------------------------------------------------------------------------- levels
def histogram_quantile(counts: NDArray[np.int64], edges: FloatArray, p: float) -> float:
    """Quantile from a histogram CDF, linear inside the bin (error at most one bin width)."""
    cumulative = np.cumsum(counts)
    target = p * cumulative[-1]
    index = int(np.searchsorted(cumulative, target, side="left"))
    index = min(index, counts.size - 1)
    below = cumulative[index - 1] if index else 0
    inside = counts[index]
    fraction = 0.0 if inside == 0 else (target - below) / inside
    return float(edges[index] + min(max(fraction, 0.0), 1.0) * (edges[index + 1] - edges[index]))


def lloyd_levels(centres: FloatArray, weights: FloatArray, k: int = 4) -> FloatArray:
    """One-dimensional k-means on a weighted histogram; initial centres at the (j-0.5)/k quantiles.

    Same estimator as plan R2.2 (Lloyd, stop below 1e-9 of the standard deviation or at 200
    iterations), applied to histogram bin centres. The result is inferred, not a transmitted level.
    """
    weights = weights.astype(np.float64)
    total = weights.sum()
    cdf = np.cumsum(weights) / total
    centroids = np.array(
        [centres[min(int(np.searchsorted(cdf, (j + 0.5) / k)), centres.size - 1)] for j in range(k)]
    )
    mean = float((centres * weights).sum() / total)
    std = math.sqrt(float((weights * (centres - mean) ** 2).sum() / total))
    for _ in range(200):
        edges = (centroids[:-1] + centroids[1:]) / 2.0
        cell = np.searchsorted(edges, centres)
        updated = centroids.copy()
        for j in range(k):
            w = weights[cell == j]
            if w.sum() > 0:
                updated[j] = float((centres[cell == j] * w).sum() / w.sum())
        moved = float(np.abs(updated - centroids).max())
        centroids = updated
        if moved < 1e-9 * std:
            break
    return np.sort(centroids)


def level_structure(counts: NDArray[np.int64], edges: FloatArray) -> dict[str, Any]:
    """Four-hump test of an amplitude histogram: peaks, valleys, spacing. Descriptive, blind.

    The histogram is smoothed (Gaussian, sigma = 1/200 of the bins), peaks below 10 % of the tallest
    are dropped, and the structure is `four_levels` when exactly four peaks remain and every valley
    is at most 90 % of the lower of its two peaks. Spacing is reported, not required.
    """
    n = counts.size
    sigma = max(n / 200.0, 1.0)
    grid = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
    kernel = np.exp(-0.5 * (grid / sigma) ** 2)
    smooth = np.convolve(counts.astype(np.float64), kernel / kernel.sum(), mode="same")
    centres = (edges[:-1] + edges[1:]) / 2.0
    interior = np.flatnonzero((smooth[1:-1] > smooth[:-2]) & (smooth[1:-1] >= smooth[2:])) + 1
    peaks = [int(i) for i in interior if smooth[i] >= 0.1 * smooth.max()]
    merged: list[int] = []
    for i in peaks:
        if merged and centres[i] - centres[merged[-1]] < 0.05 * (centres[-1] - centres[0]):
            if smooth[i] > smooth[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)
    valleys = [
        float(smooth[a : b + 1].min() / min(smooth[a], smooth[b]))
        for a, b in zip(merged[:-1], merged[1:], strict=True)
    ]
    positions = [float(centres[i]) for i in merged]
    gaps = np.diff(positions)
    four = len(merged) == 4 and all(v <= 0.9 for v in valleys)
    return {
        "four_levels": bool(four),
        "peak_count": len(merged),
        "estimated_peak_positions_normalized": positions,
        "valley_to_peak_ratio": valleys,
        "estimated_peak_gaps_normalized": [float(g) for g in gaps],
        "estimated_gap_spread_relative": float((gaps.max() - gaps.min()) / gaps.mean())
        if len(gaps) >= 2
        else None,
        "caveat": "blind histogram peaks; inferred, not transmitted levels",
    }


def _kmeans_samples(values: FloatArray, k: int = 4) -> FloatArray:
    """Lloyd k-means on raw values, quantile initialisation (the R2.2 estimator, on samples)."""
    centroids = np.quantile(values, [(j + 0.5) / k for j in range(k)])
    scale = float(values.std()) or 1.0
    for _ in range(200):
        cell = np.searchsorted((centroids[:-1] + centroids[1:]) / 2.0, values)
        updated = np.array(
            [values[cell == j].mean() if np.any(cell == j) else centroids[j] for j in range(k)]
        )
        moved = float(np.abs(updated - centroids).max())
        centroids = updated
        if moved < 1e-9 * scale:
            break
    return np.sort(centroids)


def _q(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def decision_clusters(values: FloatArray) -> dict[str, Any]:
    """Blind decisions: cluster `values` into four, return centres, spreads, occupancy and proxies.

    `estimated_decision_error_proxy` is the occupancy-weighted Gaussian tail mass of each cluster
    beyond the midpoint to its neighbours. See `PROXY_CAVEAT`: it is not a BER or SER.
    """
    centres = _kmeans_samples(values)
    cell = np.searchsorted((centres[:-1] + centres[1:]) / 2.0, values)
    sigma = np.array(
        [float(values[cell == j].std()) if np.sum(cell == j) > 1 else math.nan for j in range(4)]
    )
    occupancy = np.array([float(np.mean(cell == j)) for j in range(4)])
    gaps = np.diff(centres)
    proxy = math.nan
    opening = [math.nan] * 3
    if np.all(np.isfinite(sigma)) and np.all(sigma > 0):
        proxy = 0.0
        for j in range(4):
            for neighbour in (j - 1, j + 1):
                if 0 <= neighbour < 4:
                    half = abs(centres[neighbour] - centres[j]) / 2.0
                    proxy += occupancy[j] * _q(half / sigma[j])
        opening = [float(gaps[i] - 2.0 * (sigma[i] + sigma[i + 1])) for i in range(3)]
    return {
        "estimated_levels_normalized": [float(c) for c in centres],
        "estimated_cluster_std_normalized": [float(s) for s in sigma],
        "estimated_occupancy": [float(o) for o in occupancy],
        "estimated_decision_error_proxy": float(proxy),
        "estimated_decision_error_proxy_caveat": PROXY_CAVEAT,
        "estimated_eye_opening_proxy_normalized": opening,
        "within_cluster_sse": float(np.sum((values - centres[cell]) ** 2)),
    }


# ---------------------------------------------------------------------------- eye
def explore_eye(
    capture: ExternalCapture,
    timing: TimingModel,
    normalization: tuple[float, float],
    *,
    first_symbol: int = 0,
    symbols: int = 20000,
    scan_symbols: int = 4000,
    phase_steps: int = 32,
    amplitude_bins: int = 64,
    amplitude_range: tuple[float, float] = (-3.0, 3.0),
) -> dict[str, Any]:
    """Blind eye exploration on one stretch of symbols, using the measured symbol instants.

    The sampling phase inside a symbol is the one that minimises the within-cluster spread of blind
    four-level decisions (searched on `scan_symbols` symbols); then `symbols` symbols give the
    cluster statistics, and a two-symbol-wide folded amplitude histogram (the eye) is built by
    interpolating at fractional instants. Everything is `normalized` and `estimated_`.
    """
    mean, std = normalization
    instants_all = timing.symbol_instants(first_symbol, symbols + 2)
    lo = int(math.floor(instants_all[0])) - 4
    hi = int(math.ceil(instants_all[-1])) + 6
    window = (capture.read(max(lo, 0), min(hi, capture.count)) - mean) / std
    base = max(lo, 0)

    def sample(offset: float, count: int) -> FloatArray:
        t = timing.symbol_instants(first_symbol, count, offset) - base
        return interpolate_cubic(window, t)

    offsets = np.arange(phase_steps) / phase_steps
    costs = [
        decision_clusters(sample(float(o), scan_symbols))["within_cluster_sse"] for o in offsets
    ]
    best = float(offsets[int(np.argmin(costs))])
    decisions = decision_clusters(sample(best, symbols))
    centre_t = timing.symbol_instants(first_symbol, symbols, best) - base
    spacing = np.diff(timing.symbol_instants(first_symbol, symbols + 1, best))
    phases = (np.arange(2 * phase_steps) - phase_steps) / phase_steps  # -1 .. +1 symbol
    eye = np.zeros((phases.size, amplitude_bins), dtype=np.int64)
    edges = np.linspace(amplitude_range[0], amplitude_range[1], amplitude_bins + 1)
    keep = (centre_t - spacing.max() >= 1) & (centre_t + spacing.max() <= window.size - 4)
    for index, u in enumerate(phases):
        values = interpolate_cubic(window, centre_t[keep] + u * spacing[keep])
        eye[index] = np.histogram(values, bins=edges)[0]
    return {
        "scale": SCALE_NORMALIZED,
        "estimated_best_phase_offset_symbols": best,
        "estimated_phase_scan_within_cluster_sse": [float(c) for c in costs],
        "symbols_used": symbols,
        **{k: v for k, v in decisions.items() if k != "within_cluster_sse"},
        "eye_phase_symbols": [float(u) for u in phases],
        "eye_amplitude_edges_normalized": [float(e) for e in edges],
        "eye_counts": eye.tolist(),
        "caveat": "blind eye: levels and phase are inferred from the waveform, no reference used",
    }


# ---------------------------------------------------------------------------- timebase
def timebase_diagnostics(
    layout: SampleLayout,
    baud_bd: float,
    record_sample_rate_hz: float | None,
    timing: TimingModel | None,
) -> dict[str, Any]:
    """What the file header, the published record and the waveform each say about the time axis.

    `header_*` is what the file states; `record_*` is the dataset record's (INFERRED) sample rate.
    A disagreement is reported, not resolved here. `measured_*` is the symbol clock measured from
    the waveform with the header time increment as the time scale.
    """
    out: dict[str, Any] = {
        "header_time_increment_s": layout.x_increment_s,
        "baud_published_bd": baud_bd,
        "record_samples": layout.count,
    }
    if layout.x_increment_s is None:
        out["status"] = "no time increment in the file"
        return out
    header_rate = 1.0 / layout.x_increment_s
    out["header_sample_rate_hz"] = header_rate
    out["header_record_span_s"] = layout.count * layout.x_increment_s
    out["header_samples_per_symbol"] = samples_per_symbol(header_rate, baud_bd)
    declared = layout.header_fields.get("x_display_range_s")
    if declared:
        out["header_span_over_display_range"] = out["header_record_span_s"] / declared
    if record_sample_rate_hz is not None:
        out["record_sample_rate_hz_inferred"] = record_sample_rate_hz
        out["record_samples_per_symbol_nominal"] = samples_per_symbol(
            record_sample_rate_hz, baud_bd
        )
        ratio = header_rate / record_sample_rate_hz
        out["header_rate_over_record_rate"] = ratio
        out["conflict"] = bool(abs(ratio - 1.0) > 1e-3)
    if timing is not None:
        out["measured_symbol_rate_hz"] = timing.symbol_frequency * header_rate
        out["measured_offset_ppm_vs_published_baud"] = (
            timing.symbol_frequency * header_rate / baud_bd - 1.0
        ) * 1e6
        out["measured_samples_per_symbol"] = timing.sps_measured
        out["wander_rms_symbols"] = timing.wander_rms_symbols
        out["wander_rms_samples"] = timing.wander_rms_symbols * timing.sps_measured
        out["tone_strength_median"] = float(np.median(timing.strength))
        out["tone_strength_min"] = float(timing.strength.min())
        out["timing_windows"] = int(timing.centers.size)
        out["timing_notes"] = list(timing.field_notes)
    return out


# ---------------------------------------------------------------------------- main entry
def describe_capture(capture: ExternalCapture, **options: Any) -> dict[str, Any]:
    """Descriptive statistics only; see `describe_capture_with_timing` for the options."""
    return describe_capture_with_timing(capture, **options)[0]


def describe_capture_with_timing(
    capture: ExternalCapture,
    *,
    baud_bd: float | None = None,
    sample_rate_hz: float | None = None,
    record_sample_rate_hz: float | None = None,
    block_samples: int = DEFAULT_BLOCK_SAMPLES,
    hist_bins: int = 4096,
    nperseg: int = 4096,
    qc_window: int = 1 << 20,
    start: int = 0,
    stop: int | None = None,
    progress: Progress | None = None,
) -> tuple[dict[str, Any], TimingModel | None]:
    """Descriptive statistics of samples [start, stop) in two streaming passes, and the timing.

    `sample_rate_hz` is the rate the time axis uses (default: from the file's time increment).
    `record_sample_rate_hz` is only compared with it in the timebase diagnostics (a dataset
    record's inferred rate). With `baud_bd` given, the symbol clock is measured as well. A
    non-finite sample is refused.
    """
    stop = capture.count if stop is None else stop
    moments, extremes = _Moments(), _Extremes()
    welch = WelchAccumulator(nperseg)
    windower = Windower(qc_window)
    window_stats: list[tuple[float, float]] = []
    rate = sample_rate_hz if sample_rate_hz is not None else capture.layout.sample_rate_hz
    tracker: TimingTracker | None = None
    tone_windower: Windower | None = None
    if baud_bd is not None:
        if rate is None:
            raise BenchmarkError(
                "a baud rate needs a sample rate or a time increment", ErrorCode.FORMAT_UNKNOWN
            )
        tracker = TimingTracker(samples_per_symbol(rate, baud_bd))
        tone_windower = Windower(tracker.window_samples)
    total = stop - start
    for first, block in capture.blocks(block_samples, start, stop):
        if not np.isfinite(block).all():
            raise BenchmarkError(f"non-finite sample in block at {first}", ErrorCode.FORMAT_UNKNOWN)
        moments.add(block)
        extremes.add(block)
        welch.add(block)
        for _, window in windower.push(first, block):
            window_stats.append((float(window.mean()), float(window.std())))
        if tracker is not None and tone_windower is not None:
            for begin, window in tone_windower.push(first, block):
                tracker.add_window(begin - start, window)
        if progress is not None:
            progress(first - start + block.size, total)
    if extremes.high == extremes.low or not moments.std > 0:
        raise BenchmarkError("the capture is constant: no statistics", ErrorCode.FORMAT_UNKNOWN)
    mean, std = moments.mean, moments.std
    counts = np.zeros(hist_bins, dtype=np.int64)
    for first, block in capture.blocks(block_samples, start, stop):
        counts += np.histogram(block, bins=hist_bins, range=(extremes.low, extremes.high))[0]
        if progress is not None:
            progress(total + first - start + block.size, 2 * total)
    edges_raw = np.linspace(extremes.low, extremes.high, hist_bins + 1)
    edges = (edges_raw - mean) / std
    centres = (edges[:-1] + edges[1:]) / 2.0
    freq, psd = welch.result()
    psd = psd / (std * std)  # z-score scaling; the Welch estimate is quadratic in the samples
    ws = np.asarray(window_stats)
    timing: TimingModel | None = tracker.finish(total) if tracker is not None else None
    levels = lloyd_levels(centres, counts.astype(np.float64))
    cell = np.searchsorted((levels[:-1] + levels[1:]) / 2.0, centres)
    cluster_std = [
        math.sqrt(
            float(
                (counts[cell == j] * (centres[cell == j] - levels[j]) ** 2).sum()
                / max(counts[cell == j].sum(), 1)
            )
        )
        for j in range(4)
    ]
    quantile_values = {f"{p:g}": histogram_quantile(counts, edges, p) for p in QUANTILES}
    peak = float(psd.max())
    stats: dict[str, Any] = {
        "scale": SCALE_NORMALIZED,
        "units_note": UNITS_NOTE,
        "samples": int(moments.n),
        "range": [start, stop],
        "normalization": {"offset_file_units": mean, "scale_file_units": std},
        "mean_normalized": 0.0,
        "dc_over_std_file_units": mean / std,
        "min_normalized": (extremes.low - mean) / std,
        "max_normalized": (extremes.high - mean) / std,
        "histogram": {
            "bins": hist_bins,
            "counts": counts.tolist(),
            "edges_normalized": edges.tolist(),
        },
        "quantiles_normalized": quantile_values,
        "quantile_resolution_normalized": float(edges[1] - edges[0]),
        "psd": {
            "nperseg": nperseg,
            "segments": welch.segments,
            "frequency_cycles_per_sample": freq.tolist(),
            "density_normalized": psd.tolist(),
            "frequency_hz": None if rate is None else (freq * rate).tolist(),
            "peak_density": peak,
        },
        "level_exploration": {
            "estimated_levels_normalized": [float(v) for v in levels],
            "estimated_level_gaps_normalized": [float(v) for v in np.diff(levels)],
            "estimated_cluster_std_normalized": cluster_std,
            "structure": level_structure(counts, edges),
            "estimator": "weighted Lloyd k=4 on the amplitude histogram (plan R2.2 initialisation)",
        },
        "qc": {
            "finite": True,
            "constant": False,
            "samples_at_minimum": extremes.at_low,
            "samples_at_maximum": extremes.at_high,
            "rail_fraction": (extremes.at_low + extremes.at_high) / moments.n,
            "longest_identical_run": extremes.run_longest,
            "qc_windows": int(ws.shape[0]) if ws.size else 0,
            "qc_window_samples": qc_window,
            "samples_not_in_a_qc_window": windower.leftover,
            "window_mean_spread_over_std": float(ws[:, 0].std() / std) if ws.size else None,
            "window_std_spread_over_std": float(ws[:, 1].std() / std) if ws.size else None,
            "md5_state": None if capture.checksum is None else capture.checksum.md5_state.value,
        },
        "timebase": timebase_diagnostics(capture.layout, baud_bd, record_sample_rate_hz, timing)
        if baud_bd is not None
        else {"status": "no baud rate given"},
    }
    return stats, timing


# ---------------------------------------------------------------------------- native-rate reading
_LINE_CHUNK = 4096


def native_rate_reading(
    capture: ExternalCapture,
    record_sample_rate_hz: float,
    *,
    block_samples: int = DEFAULT_BLOCK_SAMPLES,
) -> dict[str, Any]:
    """Test the reading "native samples at the record's rate, stored after an integer upsampling".

    Everything here is computed from the samples and the header time increment, none of it from a
    document, and the result is a labelled READING: it says what the file would look like if that
    were so, and says nothing about the exporter. Three independent observations.

    1. Counting. With header rate R and record rate r, F = R / r. If F is an integer of at least 2
       and (N - 1) is a multiple of F, the file holds N_native = (N - 1) / F + 1 native points and
       an endpoint-preserving stretch; N_native / r is the native record span.
    2. Lines. The squared, mean-removed waveform of an upsampled stream carries a line at every
       multiple k * r below R / 2 (image residue of the upsampling). The squared waveform is
       demodulated at k * r, averaged over chunks of 4096 samples and Fourier transformed over the
       chunk sequence; the strongest bin gives the line frequency (parabolic refinement) and its
       power over the median bin gives the line height in dB.
    3. Curvature period. The mean squared second difference, grouped by sample index modulo F,
       has period F when samples were made by interpolation between native points: interpolated
       samples sit between native ones and have a different curvature from native ones. The
       profile is reported with control periods F - 1 and F + 1, which must stay flat.

    A record rate at or above the header rate (factor 1, or less) is reported "not testable".
    """
    layout = capture.layout
    out: dict[str, Any] = {
        "label": "READING from the samples; not an exporter statement, not a verified fact",
        "record_sample_rate_hz": record_sample_rate_hz,
    }
    if layout.x_increment_s is None or not record_sample_rate_hz > 0:
        out["status"] = "not testable: no time increment or record rate"
        return out
    rate = 1.0 / layout.x_increment_s
    ratio = rate / record_sample_rate_hz
    out["header_sample_rate_hz"] = rate
    out["header_rate_over_record_rate"] = ratio
    factor = round(ratio)
    if factor < 2 or abs(ratio / factor - 1.0) > 1e-3:
        out["status"] = (
            "not testable: the header rate is not an integer multiple (at least 2) of the record "
            "rate, so there is no integer upsampling factor to look for"
        )
        return out
    if block_samples % _LINE_CHUNK:
        raise BenchmarkError(f"block_samples must be a multiple of {_LINE_CHUNK}")
    out["status"] = "tested"
    out["integer_factor"] = factor
    count = layout.count
    steps = count - 1
    counting: dict[str, Any] = {
        "points_minus_one": steps,
        "points_minus_one_divisible_by_factor": steps % factor == 0,
    }
    if steps % factor == 0:
        native = steps // factor + 1
        counting.update(
            {
                "points_minus_one_over_factor": steps // factor,
                "native_points": native,
                "native_span_s_at_record_rate": native / record_sample_rate_hz,
                "header_span_s_points_times_increment": count * layout.x_increment_s,
            }
        )
    out["counting"] = counting
    lines = [k for k in (1, 2) if k * record_sample_rate_hz < rate / 2]
    cycles = {k: k * record_sample_rate_hz / rate for k in lines}
    chunk_sums: dict[int, list[complex]] = {k: [] for k in lines}
    periods = (factor, factor - 1, factor + 1)
    curvature = {p: np.zeros(p) for p in periods}
    curvature_n = {p: np.zeros(p) for p in periods}
    tail = np.empty(0)
    for first, block in capture.blocks(block_samples):
        if not np.isfinite(block).all():
            raise BenchmarkError(f"non-finite sample in block at {first}", ErrorCode.FORMAT_UNKNOWN)
        y = (block - block.mean()) ** 2
        n = first + np.arange(block.size, dtype=np.float64)
        usable = block.size // _LINE_CHUNK * _LINE_CHUNK
        for k in lines:
            phase = np.mod(n[:usable] * cycles[k], 1.0)
            z = y[:usable] * np.exp(-2j * np.pi * phase)
            chunk_sums[k].extend(z.reshape(-1, _LINE_CHUNK).mean(axis=1))
        joined = np.concatenate([tail, block]) if tail.size else block
        second = joined[2:] - 2.0 * joined[1:-1] + joined[:-2]
        centre = first - tail.size + 1 + np.arange(second.size)
        for p in periods:
            residue = centre % p
            curvature[p] += np.bincount(residue, weights=second**2, minlength=p)
            curvature_n[p] += np.bincount(residue, minlength=p)
        tail = block[-2:].copy()
    line_rows = []
    for k in lines:
        seq = np.asarray(chunk_sums[k])
        power = np.abs(np.fft.fft(seq - 0.0)) ** 2
        m = power.size
        peak = int(np.argmax(power))
        left, right = power[(peak - 1) % m], power[(peak + 1) % m]
        denom = left - 2.0 * power[peak] + right
        shift = 0.5 * (left - right) / denom if denom != 0 else 0.0
        bin_index = peak + shift
        if bin_index > m / 2:
            bin_index -= m
        offset_hz = bin_index / m * rate / _LINE_CHUNK
        floor = float(np.median(power))
        line_rows.append(
            {
                "multiple_k": k,
                "nominal_frequency_hz": k * record_sample_rate_hz,
                "measured_frequency_hz": k * record_sample_rate_hz + offset_hz,
                "offset_from_nominal_hz": offset_hz,
                "line_over_median_db": 10.0 * math.log10(float(power[peak]) / floor)
                if floor > 0
                else math.inf,
                "frequency_resolution_hz": rate / (m * _LINE_CHUNK),
            }
        )
    out["lines_in_squared_signal"] = line_rows
    profiles = {}
    for p in periods:
        mean_second = curvature[p] / np.maximum(curvature_n[p], 1.0)
        profiles[str(p)] = {
            "period": p,
            "mean_squared_second_difference": mean_second.tolist(),
            "max_over_min": float(mean_second.max() / mean_second.min())
            if mean_second.min() > 0
            else math.inf,
            "argmin_residue": int(np.argmin(mean_second)),
            "argmax_residue": int(np.argmax(mean_second)),
            "mirror_symmetry_max_relative_difference": float(
                max(
                    abs(mean_second[r] - mean_second[(p - r) % p])
                    / max(mean_second[r], mean_second[(p - r) % p])
                    for r in range(p)
                )
            ),
        }
    out["second_difference_period"] = {
        "factor_period": factor,
        "profiles": profiles,
        "control_periods": [factor - 1, factor + 1],
    }
    return out
