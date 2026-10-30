"""Receiver DSP for real, non-periodic oscilloscope captures.

A scope record is not one exact period: it may hold several or partial frames and runs on
a clock that differs from the AWG's. Everything here is linear (no circular FFT filtering
or wraparound), finds frames by correlation with the known preamble, estimates the actual
symbol rate, and fits gain, offset, equalizer and likelihoods on preamble and training only.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline
from scipy.signal import correlate, find_peaks, firwin, oaconvolve

from opticps.measurement.uxr_import import ScopeWaveform
from opticps.modulation.pam import pam_levels
from opticps.receiver.dsp import (
    HEAD,
    Calibration,
    Likelihood,
    Metrics,
    apply_ffe,
    calibrate,
    detect_map,
    detect_minimum_distance,
    estimate_likelihood,
    evaluate,
    lms_ffe,
    train_ffe,
)
from opticps.statistics.intervals import bootstrap_interval, clopper_pearson
from opticps.transmitter.frame import PREAMBLE_LENGTH, Frame, preamble_indices

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
OVERSAMPLING = 8
MAX_CLOCK_PPM = 2000.0
MIN_PREAMBLE_CORRELATION = 8 / np.sqrt(PREAMBLE_LENGTH)
PHASE_STEP = 0.25
MAX_EYE_TRACES = 2000
MIN_LEVEL_SYMBOLS = 100
RESIDUAL_LIMIT_SAMPLES = 1.0
DECIMATE_RATIO = 1.05
PLATEAU = 1.25


@dataclass(frozen=True)
class FrameAnalysis:
    """Result for one complete frame inside the capture."""

    frame_number: int
    start_time_s: float
    phase_samples: float
    gain_v_per_level: float
    offset_v: float
    ffe_taps: FloatArray
    likelihood: Likelihood
    symbols: FloatArray
    decisions_map: IntArray
    minimum_distance: Metrics
    map: Metrics


@dataclass(frozen=True)
class PooledErrors:
    """Errors pooled over all complete frames. Zero errors give an upper bound, not a rate."""

    symbols: int
    symbol_errors: int
    ser: float | None
    ser_ci: tuple[float, float]
    ser_upper_95: float
    ser_report: str
    bits: int
    bit_errors: int
    ber: float | None
    ber_ci: tuple[float, float]
    ber_upper_95: float
    ber_report: str
    ser_bootstrap_ci: tuple[float, float] | None
    ber_bootstrap_ci: tuple[float, float] | None


@dataclass(frozen=True)
class ScopeAnalysis:
    """Everything derived from one scope capture."""

    measured_sample_rate: float
    symbol_rate_nominal: float
    estimated_symbol_rate: float
    clock_offset_ppm: float
    clock_stderr_ppm: float | None
    clock_confidence: str
    polarity_inverted: bool
    preamble_correlation: float
    frames_found: int
    frames_complete: int
    frames: list[FrameAnalysis]
    minimum_distance: PooledErrors
    map: PooledErrors
    r_smd: float
    r_bmd: float
    snr_db: float
    rate_estimate_reliable: bool
    level_test_symbols: list[int]
    gain_v_per_level: float
    offset_v: float
    symbol_histogram: IntArray
    eye: FloatArray
    eye_time_ui: FloatArray
    warnings: list[str] = field(default_factory=list)


def describe_error_rate(errors: int, trials: int, unit: str) -> str:
    """Describe an error count; zero errors become a one-sided 95% upper bound."""
    if errors == 0:
        bound = clopper_pearson(0, trials, 0.90)[1]
        return f"0 errors in {trials} {unit}, 95% upper bound {bound:.3g}"
    low, high = clopper_pearson(errors, trials)
    return (
        f"{errors} errors in {trials} {unit}, rate {errors / trials:.3g} "
        f"(95% interval {low:.3g} to {high:.3g})"
    )


def resample_linear(x: FloatArray, sample_rate: float, target_rate: float) -> FloatArray:
    """Resample a non-periodic record: FIR anti-alias when decimating, then cubic spline.

    Ratios within 5% of unity are only interpolated: a filter there would add ringing and
    remove nothing, since content above four symbol rates is assumed negligible.
    """
    ratio = sample_rate / target_rate
    if abs(ratio - 1) < 1e-12:
        return x.copy()
    if ratio > DECIMATE_RATIO:
        length = 64 * int(np.ceil(ratio)) + 1
        kernel = firwin(length, 0.45 * target_rate, window=("kaiser", 8.0), fs=sample_rate)
        x = oaconvolve(x, kernel, mode="same")
    count = int(np.floor((x.size - 1) / ratio)) + 1
    spline = CubicSpline(np.arange(x.size), x)
    return np.asarray(spline(np.arange(count) * ratio), dtype=float)


def _normalized_correlation(signal: FloatArray, template: FloatArray) -> FloatArray:
    """Linear (valid-only) correlation scaled by the local signal energy."""
    length = template.size
    raw = correlate(signal, template, mode="valid", method="fft")
    total = np.concatenate([[0.0], np.cumsum(signal)])
    squares = np.concatenate([[0.0], np.cumsum(signal**2)])
    window_sum = total[length:] - total[:-length]
    energy = np.maximum((squares[length:] - squares[:-length]) - window_sum**2 / length, 1e-30)
    return np.asarray(raw / (np.linalg.norm(template) * np.sqrt(energy)), dtype=float)


def _score(
    spline: CubicSpline, template: FloatArray, start: float, shifts: FloatArray
) -> FloatArray:
    grid = start + shifts[:, None] + np.arange(template.size)[None, :]
    return np.asarray(spline(grid) @ template, dtype=float)


def _refine(
    spline: CubicSpline, template: FloatArray, centre: float, half_width: float, sign: int
) -> float:
    """Return the sub-sample start that maximizes sign * correlation near centre."""
    coarse = np.arange(-half_width, half_width + 1e-9, 0.5)
    best = float(coarse[np.argmax(sign * _score(spline, template, centre, coarse))])
    fine = best + np.arange(-0.5, 0.5 + 1e-9, 0.05)
    values = sign * _score(spline, template, centre, fine)
    k = int(np.argmax(values))
    shift = float(fine[k])
    if 0 < k < fine.size - 1:
        denominator = values[k - 1] - 2 * values[k] + values[k + 1]
        if denominator < 0:
            shift += (
                float(np.clip(0.5 * (values[k - 1] - values[k + 1]) / denominator, -1, 1)) * 0.05
            )
    return centre + shift


@dataclass(frozen=True)
class _Timing:
    frame_numbers: IntArray
    positions: FloatArray
    starts: FloatArray
    q: float
    stderr_ppm: float | None
    confidence: str
    sign: int
    strength: float
    warnings: list[str]


def _locate_timing(spline: CubicSpline, signal: FloatArray, frame: Frame) -> _Timing:
    """Find preambles by linear correlation and estimate the symbol clock ratio q.

    q is the true symbol period divided by the nominal one on the current time grid.
    """
    n_symbols = frame.indices.size
    frame_samples = n_symbols * OVERSAMPLING
    template = np.repeat(pam_levels(4)[preamble_indices()], OVERSAMPLING)
    ncc = _normalized_correlation(signal, template)
    magnitude = np.abs(ncc)
    top = float(magnitude.max())
    if top < MIN_PREAMBLE_CORRELATION:
        raise ValueError(
            f"No preamble found: best normalized correlation {top:.2f} is below "
            f"{MIN_PREAMBLE_CORRELATION:.2f}"
        )
    padded = np.concatenate([[0.0], magnitude, [0.0]])
    indices, _ = find_peaks(
        padded, height=max(0.5 * top, MIN_PREAMBLE_CORRELATION), distance=max(1, frame_samples // 2)
    )
    indices = indices - 1
    signs = np.sign(ncc[indices]).astype(int)
    sign = 1 if signs.sum() >= 0 else -1
    warnings: list[str] = []
    if np.any(signs != sign):
        warnings.append("Preamble peaks of opposite polarity were ignored")
    peaks = [
        (_refine(spline, template, float(i), 2.0, sign), float(magnitude[i]))
        for i, s in zip(indices, signs, strict=True)
        if s == sign
    ]
    ref_position = max(peaks, key=lambda p: p[1])[0]
    kept: dict[int, float] = {}
    for position, _ in sorted(peaks):
        number = int(round((position - ref_position) / frame_samples))
        residual = position - ref_position - number * frame_samples
        tolerance = MAX_CLOCK_PPM * 1e-6 * frame_samples * max(abs(number), 1) + OVERSAMPLING
        if abs(residual) <= tolerance and number not in kept:
            kept[number] = position
    numbers = np.array(sorted(kept), dtype=np.int64)
    positions = np.array([kept[n] for n in numbers])
    stderr = None
    if numbers.size >= 2:
        slope, intercept = np.polyfit(numbers, positions, 1)
        fitted = intercept + slope * numbers
        residuals = positions - fitted
        q = float(slope) / frame_samples
        if numbers.size >= 3:
            spread = float(np.sum((numbers - numbers.mean()) ** 2))
            sigma = float(np.sqrt(np.sum(residuals**2) / (numbers.size - 2)))
            stderr = 1e6 * sigma / np.sqrt(spread) / frame_samples
        confidence = "high" if numbers.size >= 3 else "medium"
        rms = float(np.sqrt(np.mean(residuals**2)))
        if rms > RESIDUAL_LIMIT_SAMPLES:
            warnings.append(f"Frame spacing is irregular (rms {rms:.2f} samples); fit not used")
            starts = positions
        else:
            starts = fitted
    else:
        start = float(positions[0])
        training = np.repeat(pam_levels(4)[frame.indices[PREAMBLE_LENGTH:HEAD]], OVERSAMPLING)
        offset = PREAMBLE_LENGTH * OVERSAMPLING
        found = _refine(spline, training, start + offset, 16.0, sign)
        q = (found - start) / offset
        confidence = "low"
        starts = positions
        warnings.append(
            "One preamble only: clock estimated from preamble and training, low confidence"
        )
    if abs(q - 1) > MAX_CLOCK_PPM * 1e-6:
        raise ValueError(f"Estimated clock offset {1e6 * (1 / q - 1):.0f} ppm exceeds the limit")
    return _Timing(numbers, positions, starts, q, stderr, confidence, sign, top, warnings)


def _sample(
    spline: CubicSpline, n_samples: int, start: float, q: float, phase: float, first: int, last: int
) -> tuple[FloatArray, NDArray[np.bool_]]:
    """Sample symbol centres first..last-1 relative to the frame start."""
    centres = start + (np.arange(first, last) + 0.5) * OVERSAMPLING * q + phase
    valid = (centres >= 1) & (centres <= n_samples - 2)
    values = np.zeros(centres.size)
    values[valid] = spline(centres[valid])
    return values, valid


PHASES = np.arange(-OVERSAMPLING / 2, OVERSAMPLING / 2 + 1e-9, PHASE_STEP)


def _phase_errors(
    spline: CubicSpline, n_samples: int, start: float, q: float, sign: int, frame: Frame, taps: int
) -> FloatArray:
    """Mean-square error of the training-fitted FFE on preamble and training, per phase."""
    half = taps // 2
    target = pam_levels(4)[frame.indices[:HEAD]]
    errors = []
    for phase in PHASES:
        values, valid = _sample(spline, n_samples, start, q, float(phase), 0, HEAD)
        if not valid.all():
            errors.append(np.inf)
            continue
        calibration = calibrate(sign * values, frame.indices)
        normalized = (sign * values - calibration.offset) / calibration.gain
        output = apply_ffe(normalized, train_ffe(normalized, frame.indices, taps))
        errors.append(
            float(np.mean((output[half : HEAD - half] - target[half : HEAD - half]) ** 2))
        )
    return np.array(errors)


def _pool(frames: list[FrameAnalysis], pick: str, rng: np.random.Generator) -> PooledErrors:
    metrics = [getattr(f, pick) for f in frames]
    symbols = sum(m.symbols for m in metrics)
    errors = sum(m.symbol_errors for m in metrics)
    bits = sum(m.bits for m in metrics)
    bit_errors = sum(m.bit_errors for m in metrics)
    ser_bootstrap = ber_bootstrap = None
    if len(frames) >= 2 and errors > 0:
        ser_units = [(m.symbol_errors, m.symbols) for m in metrics]
        ber_units = [(m.bit_errors, m.bits) for m in metrics]

        def ratio(units: Sequence[tuple[int, int]]) -> float:
            return sum(e for e, _ in units) / sum(n for _, n in units)

        ser_bootstrap = bootstrap_interval(ser_units, ratio, rng)
        ber_bootstrap = bootstrap_interval(ber_units, ratio, rng)
    return PooledErrors(
        symbols=symbols,
        symbol_errors=errors,
        ser=errors / symbols if errors else None,
        ser_ci=clopper_pearson(errors, symbols),
        ser_upper_95=clopper_pearson(errors, symbols, 0.90)[1],
        ser_report=describe_error_rate(errors, symbols, "symbols"),
        bits=bits,
        bit_errors=bit_errors,
        ber=bit_errors / bits if bit_errors else None,
        ber_ci=clopper_pearson(bit_errors, bits),
        ber_upper_95=clopper_pearson(bit_errors, bits, 0.90)[1],
        ber_report=describe_error_rate(bit_errors, bits, "bits"),
        ser_bootstrap_ci=ser_bootstrap,
        ber_bootstrap_ci=ber_bootstrap,
    )


def analyze_scope_capture(
    waveform: ScopeWaveform,
    symbol_rate_nominal: float,
    frame: Frame,
    priors: FloatArray,
    taps: int = 15,
    equalizer: str = "ls",
    seed: int = 0,
    compensate_clock: bool = True,
) -> ScopeAnalysis:
    """Analyze a non-periodic scope capture against the known transmitted frame.

    compensate_clock=False keeps the nominal symbol rate (a diagnostic, to show what clock
    estimation buys); each frame is then aligned only by its own preamble.
    """
    sample_rate = waveform.measured_sample_rate
    if symbol_rate_nominal <= 0 or sample_rate < 2 * symbol_rate_nominal:
        raise ValueError("Need a positive symbol rate and at least 2 samples per symbol")
    if equalizer not in ("ls", "lms"):
        raise ValueError(f"Unknown equalizer {equalizer!r}")
    if taps % 2 == 0:
        raise ValueError("Use an odd number of taps")
    x = waveform.samples_v - waveform.samples_v.mean()
    n_symbols = frame.indices.size
    rate = symbol_rate_nominal
    for attempt in range(2 if compensate_clock else 1):
        signal = resample_linear(x, sample_rate, OVERSAMPLING * rate)
        spline = CubicSpline(np.arange(signal.size), signal)
        timing = _locate_timing(spline, signal, frame)
        if not compensate_clock:
            timing = replace(
                timing, q=1.0, starts=timing.positions, stderr_ppm=None, confidence="none"
            )
        if attempt == 0 and compensate_clock:
            rate = rate / timing.q
    estimated_rate = rate / timing.q
    sign, q, guard = timing.sign, timing.q, taps // 2
    results: list[FrameAnalysis] = []
    eye_rows: list[FloatArray] = []
    histogram = np.zeros(4, dtype=np.int64)
    warnings = list(timing.warnings)
    eye_offsets = np.arange(-OVERSAMPLING, OVERSAMPLING + 1) / OVERSAMPLING
    complete = []
    for number, start in zip(timing.frame_numbers, timing.starts, strict=True):
        _, inside = _sample(spline, signal.size, start, q, 0.0, 0, n_symbols)
        if inside.all():
            complete.append((int(number), float(start)))
    if not complete:
        raise ValueError(
            f"No complete frame: {timing.frame_numbers.size} preamble(s) found but each "
            "frame runs past the ends of the capture"
        )
    # One sampling phase for the capture, chosen on all heads together to limit noise bias.
    total = sum(_phase_errors(spline, signal.size, st, q, sign, frame, taps) for _, st in complete)
    smooth = np.convolve(np.pad(total, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    best = int(np.argmin(smooth))
    low = high = best
    while low > 0 and smooth[low - 1] <= PLATEAU * smooth[best]:
        low -= 1
    while high < smooth.size - 1 and smooth[high + 1] <= PLATEAU * smooth[best]:
        high += 1
    phase = float(PHASES[low] + PHASES[high]) / 2  # centre of the open part of the eye
    for number, start in complete:
        raw, valid = _sample(spline, signal.size, start, q, phase, -guard, n_symbols + guard)
        raw = sign * raw
        body = raw[guard : guard + n_symbols]
        calibration: Calibration = calibrate(body, frame.indices)
        padded = np.where(valid, (raw - calibration.offset) / calibration.gain, 0.0)
        normalized = padded[guard : guard + n_symbols]
        if equalizer == "ls":
            weights = train_ffe(normalized, frame.indices, taps)
        else:
            weights = lms_ffe(normalized, frame.indices, taps)
        equalized = apply_ffe(padded, weights)[guard : guard + n_symbols]
        law = estimate_likelihood(equalized, frame.indices)
        decided = detect_map(equalized, law, priors)
        results.append(
            FrameAnalysis(
                frame_number=number,
                start_time_s=waveform.x_origin_s + start / (OVERSAMPLING * rate),
                phase_samples=phase,
                gain_v_per_level=sign * calibration.gain,
                offset_v=float(waveform.samples_v.mean()) + sign * calibration.offset,
                ffe_taps=weights,
                likelihood=law,
                symbols=equalized,
                decisions_map=decided,
                minimum_distance=evaluate(
                    detect_minimum_distance(equalized), equalized, frame, law, priors
                ),
                map=evaluate(decided, equalized, frame, law, priors),
            )
        )
        histogram += np.bincount(decided[frame.payload_start :], minlength=4)
        payload = np.arange(frame.payload_start, n_symbols)
        chosen = payload[np.linspace(0, payload.size - 1, MAX_EYE_TRACES, dtype=int)]
        grid = start + (chosen[:, None] + 0.5 + eye_offsets[None, :]) * OVERSAMPLING * q + phase
        ok = np.all((grid >= 1) & (grid <= signal.size - 2), axis=1)
        traces = sign * spline(grid[ok])
        eye_rows.append((traces - calibration.offset) / calibration.gain)
    rng = np.random.default_rng(seed)
    sent = frame.indices[frame.payload_start :]
    level_counts = [int((sent == k).sum()) * len(results) for k in range(4)]
    reliable = all(count >= MIN_LEVEL_SYMBOLS for count in level_counts)
    if not reliable:
        warnings.append(
            f"Fewer than {MIN_LEVEL_SYMBOLS} test symbols on a level; MI/GMI unreliable"
        )
    if len(results) > 1:
        warnings.append(
            "Frames repeat the same payload, so pooled symbols are not independent data"
        )
    eye = np.concatenate(eye_rows)
    return ScopeAnalysis(
        measured_sample_rate=sample_rate,
        symbol_rate_nominal=symbol_rate_nominal,
        estimated_symbol_rate=estimated_rate,
        clock_offset_ppm=1e6 * (estimated_rate / symbol_rate_nominal - 1),
        clock_stderr_ppm=timing.stderr_ppm,
        clock_confidence=timing.confidence,
        polarity_inverted=sign < 0,
        preamble_correlation=timing.strength,
        frames_found=int(timing.frame_numbers.size),
        frames_complete=len(results),
        frames=results,
        minimum_distance=_pool(results, "minimum_distance", rng),
        map=_pool(results, "map", rng),
        r_smd=float(np.mean([f.map.r_smd for f in results])),
        r_bmd=float(np.mean([f.map.r_bmd for f in results])),
        snr_db=float(np.mean([f.map.snr_db for f in results])),
        rate_estimate_reliable=reliable,
        level_test_symbols=level_counts,
        gain_v_per_level=float(np.mean([f.gain_v_per_level for f in results])),
        offset_v=float(np.mean([f.offset_v for f in results])),
        symbol_histogram=histogram,
        eye=eye,
        eye_time_ui=eye_offsets,
        warnings=warnings,
    )
