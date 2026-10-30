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
FLAT_ENERGY_FRACTION = 1e-4
BLOCK_SYMBOLS = 512
TRACK_OFFSET = 1.0
TRACK_CLIP = 2.0
TRACK_PASSES = 2
TRACK_RESIDUAL_LIMIT = 0.5
TRACK_MAX_CORRECTION_PPM = 10.0
# With a firm clock, a tracker/spacing disagreement is a note unless the symbols themselves
# disagree: payload minimum-distance SER more than FIRM_PAYLOAD_EXCESS above the 99% upper bound
# of the training SER, or a training block itself near chance.
FIRM_CONFIDENCE = 0.99
FIRM_PAYLOAD_EXCESS = 0.10
FIRM_TRAINING_SER = 0.6


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
    minimum_distance: Metrics | None
    map: Metrics | None
    timing_drift_samples: float


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
    distinct_symbols: int
    per_frame_symbol_errors: list[int]
    ser_upper_95_distinct: float | None
    lost_frames: int
    lost_symbols: int
    ser_worst_case: float | None
    ber_worst_case: float | None


@dataclass(frozen=True)
class ScopeAnalysis:
    """Everything derived from one scope capture.

    Without scoring (training captures) no value derived from the payload is reported:
    the error pools, rates, SNR, histogram and eye are None or empty.
    """

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
    frames_expected: int
    frames_analyzed: int
    frames_lost: int
    lost_frame_numbers: list[int]
    frames: list[FrameAnalysis]
    minimum_distance: PooledErrors | None
    map: PooledErrors | None
    r_smd: float | None
    r_bmd: float | None
    snr_db: float | None
    rate_estimate_reliable: bool
    level_test_symbols: list[int]
    distinct_payload_symbols: int
    training_symbols: int
    training_symbol_errors: int
    timing_residual_rms_samples: float | None
    gain_v_per_level: float
    offset_v: float
    symbol_histogram: IntArray | None
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
    """Linear (valid-only) correlation scaled by the local signal energy.

    Windows with almost no energy (flat or empty stretches) score 0 instead of a huge value.
    """
    length = template.size
    raw = correlate(signal, template, mode="valid", method="fft")
    total = np.concatenate([[0.0], np.cumsum(signal)])
    squares = np.concatenate([[0.0], np.cumsum(signal**2)])
    window_sum = total[length:] - total[:-length]
    energy = (squares[length:] - squares[:-length]) - window_sum**2 / length
    usable = energy > FLAT_ENERGY_FRACTION * length * float(np.var(signal))
    scale = np.linalg.norm(template) * np.sqrt(np.where(usable, energy, 1.0))
    return np.asarray(np.where(usable, raw / scale, 0.0), dtype=float)


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
    anchor: float
    spacing: float
    spacing_regular: bool


def _frame_inside(start: float, q: float, n_samples: int, n_symbols: int) -> bool:
    """True when the first and last symbol centres of a frame at start lie inside the record."""
    first = start + 0.5 * OVERSAMPLING * q
    last = start + (n_symbols - 0.5) * OVERSAMPLING * q
    return bool(first >= 1 and last <= n_samples - 2)


def _single_clock(spline: CubicSpline, frame: Frame, start: float, sign: int) -> float:
    """Clock ratio from the preamble-to-training spacing of one frame (low confidence)."""
    training = np.repeat(pam_levels(4)[frame.indices[PREAMBLE_LENGTH:HEAD]], OVERSAMPLING)
    offset = PREAMBLE_LENGTH * OVERSAMPLING
    found = _refine(spline, training, start + offset, 16.0, sign)
    return (found - start) / offset


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
    kept: dict[int, tuple[float, float]] = {}
    off_line = 0
    for position, strength in sorted(peaks):
        number = int(round((position - ref_position) / frame_samples))
        residual = position - ref_position - number * frame_samples
        tolerance = MAX_CLOCK_PPM * 1e-6 * frame_samples * max(abs(number), 1) + OVERSAMPLING
        off_line += abs(residual) > tolerance
        if number not in kept or strength > kept[number][1]:
            kept[number] = (position, strength)
    numbers = np.array(sorted(kept), dtype=np.int64)
    positions = np.array([kept[n][0] for n in numbers])
    stderr = None
    regular = True
    starts = positions
    q = 1.0
    confidence = "low"
    if numbers.size >= 2:
        slope, intercept = np.polyfit(numbers, positions, 1)
        fitted = intercept + slope * numbers
        residuals = positions - fitted
        rms = float(np.sqrt(np.mean(residuals**2)))
        if rms > RESIDUAL_LIMIT_SAMPLES or off_line:
            regular = False
            detail = (
                f"{off_line} preamble(s) off the clock limit"
                if off_line
                else f"rms {rms:.2f} samples"
            )
            warnings.append(
                f"Frame spacing is irregular ({detail}; a gap or dropped samples?), so the "
                "spacing fit is not used: the clock comes from the strongest frame's preamble "
                "and training (low confidence) and each frame keeps its own position. "
                "Missing frames cannot be counted."
            )
        else:
            q = float(slope) / frame_samples
            if numbers.size >= 3:
                spread = float(np.sum((numbers - numbers.mean()) ** 2))
                sigma = float(np.sqrt(np.sum(residuals**2) / (numbers.size - 2)))
                stderr = 1e6 * sigma / np.sqrt(spread) / frame_samples
            confidence = "high" if numbers.size >= 3 else "medium"
            starts = fitted
    if confidence == "low":
        q = _single_clock(spline, frame, ref_position, sign)
        if regular:
            warnings.append(
                "One preamble only: clock estimated from preamble and training, low confidence"
            )
    if abs(q - 1) > MAX_CLOCK_PPM * 1e-6:
        raise ValueError(f"Estimated clock offset {1e6 * (1 / q - 1):.0f} ppm exceeds the limit")
    spacing = frame_samples * q
    anchor = float(starts[0]) - float(numbers[0]) * spacing
    return _Timing(
        numbers,
        positions,
        starts,
        q,
        stderr,
        confidence,
        sign,
        top,
        warnings,
        anchor,
        spacing,
        regular,
    )


def _sample(
    spline: CubicSpline, n_samples: int, start: float, q: float, phase: float, first: int, last: int
) -> tuple[FloatArray, NDArray[np.bool_]]:
    """Sample symbol centres first..last-1 relative to the frame start."""
    return _sample_at(spline, n_samples, _centres(start, q, phase, first, last))


def _centres(start: float, q: float, phase: float, first: int, last: int) -> FloatArray:
    return np.asarray(start + (np.arange(first, last) + 0.5) * OVERSAMPLING * q + phase)


def _sample_at(
    spline: CubicSpline, n_samples: int, centres: FloatArray
) -> tuple[FloatArray, NDArray[np.bool_]]:
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


@dataclass(frozen=True)
class _Receiver:
    """Calibration, equalizer and channel law fitted on preamble and training only."""

    calibration: Calibration
    weights: FloatArray
    law: Likelihood


def _fit_receiver(
    spline: CubicSpline,
    n_samples: int,
    centres: FloatArray,
    guard: int,
    sign: int,
    frame: Frame,
    taps: int,
    equalizer: str,
) -> _Receiver:
    """Fit on the head; centres cover symbols -guard .. HEAD+guard-1."""
    values, valid = _sample_at(spline, n_samples, centres)
    raw = sign * values
    calibration = calibrate(raw[guard : guard + HEAD], frame.indices)
    padded = np.where(valid, (raw - calibration.offset) / calibration.gain, 0.0)
    body = padded[guard : guard + HEAD]
    if equalizer == "ls":
        weights = train_ffe(body, frame.indices, taps)
    else:
        weights = lms_ffe(body, frame.indices, taps)
    equalized = apply_ffe(padded, weights)[guard : guard + HEAD]
    return _Receiver(calibration, weights, estimate_likelihood(equalized, frame.indices))


@dataclass(frozen=True)
class _Track:
    """Decision-directed timing result for one frame."""

    start: float
    q: float
    stderr_ppm: float | None
    residual_rms: float | None
    drift_samples: float


def _early_late(
    spline: CubicSpline,
    n_samples: int,
    centres: FloatArray,
    levels: FloatArray,
    sign: int,
    gain: float,
) -> float:
    """Early-late timing statistic sum(level * (y(t+d) - y(t-d))) / sum(level^2)."""
    late, ok_late = _sample_at(spline, n_samples, centres + TRACK_OFFSET)
    early, ok_early = _sample_at(spline, n_samples, centres - TRACK_OFFSET)
    ok = ok_late & ok_early
    energy = float(np.sum(levels[ok] ** 2))
    if energy == 0:
        return float("nan")
    return float(np.sum(levels[ok] * sign * (late[ok] - early[ok])) / gain / energy)


def _line_fit(n: list[float], shift: list[float]) -> tuple[float, float, float]:
    """Least-squares shift = alpha + beta * n; returns alpha, beta, rms residual."""
    x, y = np.array(n), np.array(shift)
    beta, alpha = np.polyfit(x, y, 1)
    return float(alpha), float(beta), float(np.sqrt(np.mean((y - alpha - beta * x) ** 2)))


def _track_timing(
    spline: CubicSpline,
    n_samples: int,
    start: float,
    q: float,
    phase: float,
    sign: int,
    frame: Frame,
    taps: int,
    equalizer: str,
    priors: FloatArray,
) -> _Track:
    """Follow the sampling instant across a frame with payload decisions.

    One preamble gives a clock accurate to tens of ppm, which drifts by a large part of a
    symbol over a long frame. Here the early-late statistic of blocks of payload symbols,
    steered by the receiver's own decisions (never the reference payload), is converted to a
    time shift with a slope calibrated on the known training symbols; a line fitted to the
    shifts corrects the start and the clock. A first sequential pass extrapolates the line
    block by block, then the whole frame is re-measured and refitted. Returns the corrected
    start and q; a failure leaves them unchanged and the residual None.
    """
    guard = taps // 2
    n_symbols = frame.indices.size
    levels_all = pam_levels(4)
    head_centres = _centres(start, q, phase, -guard, HEAD + guard)
    train = slice(PREAMBLE_LENGTH, HEAD)
    known = levels_all[frame.indices[train]]
    shifts = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
    gain0 = _fit_receiver(
        spline, n_samples, head_centres, guard, sign, frame, taps, equalizer
    ).calibration.gain
    stats = [
        _early_late(
            spline,
            n_samples,
            _centres(start, q, phase, PREAMBLE_LENGTH, HEAD) + s,
            known,
            sign,
            gain0,
        )
        for s in shifts
    ]
    slope, reference = np.polyfit(shifts, stats, 1)
    if not np.all(np.isfinite(stats)) or abs(slope) < 1e-3:
        return _Track(start, q, None, None, 0.0)
    edges = list(range(HEAD, n_symbols, BLOCK_SYMBOLS))
    blocks = [(lo, min(lo + BLOCK_SYMBOLS, n_symbols)) for lo in edges]
    if len(blocks) > 1 and blocks[-1][1] - blocks[-1][0] < BLOCK_SYMBOLS // 2:
        blocks[-2] = (blocks[-2][0], blocks[-1][1])
        blocks.pop()

    def measure(
        rx: _Receiver, begin: float, rate: float, line: tuple[float, float], lo: int, hi: int
    ) -> float:
        n = np.arange(lo - guard, hi + guard)
        wide = begin + (n + 0.5) * OVERSAMPLING * rate + phase + line[0] + line[1] * n
        values, valid = _sample_at(spline, n_samples, wide)
        padded = np.where(valid, (sign * values - rx.calibration.offset) / rx.calibration.gain, 0.0)
        equalized = apply_ffe(padded, rx.weights)[guard : guard + hi - lo]
        decided = detect_map(equalized, rx.law, priors)
        value = _early_late(
            spline, n_samples, wide[guard : guard + hi - lo], levels_all[decided], sign,
            rx.calibration.gain,
        )  # fmt: skip
        return float((reference - value) / slope)

    def fit(begin: float, rate: float) -> _Receiver:
        centres = _centres(begin, rate, phase, -guard, HEAD + guard)
        return _fit_receiver(spline, n_samples, centres, guard, sign, frame, taps, equalizer)

    anchor = (PREAMBLE_LENGTH + HEAD) / 2
    rx = fit(start, q)
    positions, totals = [anchor], [0.0]
    for lo, hi in blocks:  # sequential pass: extrapolate the line fitted so far
        centre = (lo + hi - 1) / 2
        if len(positions) >= 3:
            alpha, beta, _ = _line_fit(positions, totals)
            line = (alpha, beta)
        else:
            line = (totals[-1], 0.0)
        predicted = line[0] + line[1] * centre
        error = measure(rx, start, q, line, lo, hi)
        if not np.isfinite(error):
            continue
        positions.append(centre)
        totals.append(predicted + float(np.clip(error, -TRACK_CLIP, TRACK_CLIP)))
    if len(positions) < 4:
        return _Track(start, q, None, None, 0.0)
    alpha, beta, _ = _line_fit(positions, totals)
    start, q = start + alpha - 0.5 * beta, q + beta / OVERSAMPLING
    drift = beta * n_symbols
    residual = stderr = None
    for _ in range(TRACK_PASSES):  # whole-frame re-measure at the corrected timing
        rx = fit(start, q)
        positions, errors = [anchor], [0.0]
        for lo, hi in blocks:
            error = measure(rx, start, q, (0.0, 0.0), lo, hi)
            if np.isfinite(error):
                positions.append((lo + hi - 1) / 2)
                errors.append(float(np.clip(error, -TRACK_CLIP, TRACK_CLIP)))
        if len(positions) < 4:
            return _Track(start, q, None, None, drift)
        alpha, beta, residual = _line_fit(positions, errors)
        spread = float(np.sum((np.array(positions) - np.mean(positions)) ** 2))
        stderr = 1e6 * residual / np.sqrt(spread) / OVERSAMPLING
        start, q = start + alpha - 0.5 * beta, q + beta / OVERSAMPLING
        drift += beta * n_symbols
    return _Track(start, q, stderr, residual, drift)


def _pool(
    frames: list[FrameAnalysis],
    pick: str,
    rng: np.random.Generator,
    distinct: int,
    lost_symbols: int,
    lost_frames: int,
) -> PooledErrors:
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
    repeats = len(frames)

    def report(count: int, trials: int, unit: str, distinct_n: int, lost_n: int) -> str:
        text = describe_error_rate(count, trials, unit)
        if repeats > 1:
            text += f"; {repeats} frames repeat the same {distinct_n} payload {unit}"
            if count == 0:
                bound = clopper_pearson(0, distinct_n, 0.90)[1]
                text += f", so the bound counting each distinct one once is {bound:.3g}"
        if lost_frames:
            worst = (count + lost_n) / (trials + lost_n)
            text += (
                f"; EXCLUDES {lost_frames} lost frame(s) ({lost_n} payload {unit}); "
                f"counting all of them as errors gives a worst case of {worst:.3g}"
            )
        return text

    lost_bits = 2 * lost_symbols
    ser_worst = (errors + lost_symbols) / (symbols + lost_symbols) if lost_frames else None
    ber_worst = (bit_errors + lost_bits) / (bits + lost_bits) if lost_frames else None
    return PooledErrors(
        symbols=symbols,
        symbol_errors=errors,
        ser=errors / symbols if errors else None,
        ser_ci=clopper_pearson(errors, symbols),
        ser_upper_95=clopper_pearson(errors, symbols, 0.90)[1],
        ser_report=report(errors, symbols, "symbols", distinct, lost_symbols),
        bits=bits,
        bit_errors=bit_errors,
        ber=bit_errors / bits if bit_errors else None,
        ber_ci=clopper_pearson(bit_errors, bits),
        ber_upper_95=clopper_pearson(bit_errors, bits, 0.90)[1],
        ber_report=report(bit_errors, bits, "bits", 2 * distinct, lost_bits),
        ser_bootstrap_ci=ser_bootstrap,
        ber_bootstrap_ci=ber_bootstrap,
        distinct_symbols=distinct,
        per_frame_symbol_errors=[m.symbol_errors for m in metrics],
        ser_upper_95_distinct=clopper_pearson(0, distinct, 0.90)[1] if errors == 0 else None,
        lost_frames=lost_frames,
        lost_symbols=lost_symbols,
        ser_worst_case=ser_worst,
        ber_worst_case=ber_worst,
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
    score_payload: bool = True,
) -> ScopeAnalysis:
    """Analyze a non-periodic scope capture against the known transmitted frame.

    compensate_clock=False keeps the nominal symbol rate (a diagnostic, to show what clock
    estimation buys); each frame is then aligned only by its own preamble. With
    score_payload=False (training captures) the payload is used only to steer timing and
    nothing derived from it is reported.
    """
    sample_rate = waveform.measured_sample_rate
    if symbol_rate_nominal <= 0 or sample_rate < 2 * symbol_rate_nominal:
        raise ValueError("Need a positive symbol rate and at least 2 samples per symbol")
    if equalizer not in ("ls", "lms"):
        raise ValueError(f"Unknown equalizer {equalizer!r}")
    if taps % 2 == 0:
        raise ValueError("Use an odd number of taps")
    n_symbols = frame.indices.size
    held = waveform.samples_v.size * symbol_rate_nominal / sample_rate
    if held < n_symbols:
        raise ValueError(
            f"Capture too short: {waveform.samples_v.size} samples hold {held:.0f} symbols at "
            f"{symbol_rate_nominal:g} Bd, but one frame is {n_symbols} symbols "
            f"({n_symbols / symbol_rate_nominal * 1e6:.3f} us); capture at least 2 frames"
        )
    x = waveform.samples_v - waveform.samples_v.mean()
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
    sign, guard = timing.sign, taps // 2
    results: list[FrameAnalysis] = []
    training_symbols = training_errors = 0
    eye_rows: list[FloatArray] = []
    histogram = np.zeros(4, dtype=np.int64)
    warnings = list(timing.warnings)
    eye_offsets = np.arange(-OVERSAMPLING, OVERSAMPLING + 1) / OVERSAMPLING
    complete = []
    for number, start in zip(timing.frame_numbers, timing.starts, strict=True):
        _, inside = _sample(spline, signal.size, start, timing.q, 0.0, 0, n_symbols)
        if inside.all():
            complete.append((int(number), float(start)))
    if not complete:
        raise ValueError(
            f"No complete frame: {timing.frame_numbers.size} preamble(s) found but each "
            "frame runs past the ends of the capture"
        )
    found_numbers = {number for number, _ in complete}
    expected_numbers = set(found_numbers)
    if timing.spacing_regular:
        reach = int(np.ceil(signal.size / timing.spacing)) + 2
        for m in range(-reach, reach + 1):
            if _frame_inside(timing.anchor + m * timing.spacing, timing.q, signal.size, n_symbols):
                expected_numbers.add(m)
    lost = sorted(expected_numbers - found_numbers)
    if lost:
        warnings.append(
            f"{len(lost)} expected frame(s) lost (numbers {lost}): complete frames were "
            "predicted from the clock but no usable preamble was found there; they are not "
            "scored, and the error range states the exclusion"
        )
    # One sampling phase for the capture, chosen on all heads together to limit noise bias.
    total = sum(
        _phase_errors(spline, signal.size, st, timing.q, sign, frame, taps) for _, st in complete
    )
    smooth = np.convolve(np.pad(total, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    best = int(np.argmin(smooth))
    low = high = best
    while low > 0 and smooth[low - 1] <= PLATEAU * smooth[best]:
        low -= 1
    while high < smooth.size - 1 and smooth[high + 1] <= PLATEAU * smooth[best]:
        high += 1
    phase = float(PHASES[low] + PHASES[high]) / 2  # centre of the open part of the eye
    tracks = []
    disputed: list[tuple[float, float]] = []
    firm_disputed: list[tuple[float, float]] = []
    # Three or more regularly spaced preambles fit a line with a residual to check, so the
    # spacing clock stands against the in-frame tracker, which is the weaker estimate.
    firm_clock = compensate_clock and timing.confidence == "high"
    for _, start in complete:
        if not compensate_clock:
            tracks.append(_Track(start, timing.q, None, None, 0.0))
            continue
        track = _track_timing(
            spline, signal.size, start, timing.q, phase, sign, frame, taps, equalizer, priors
        )
        correction = 1e6 * abs(track.q / timing.q - 1)
        too_big = timing.confidence in ("high", "medium") and correction > TRACK_MAX_CORRECTION_PPM
        failed = track.residual_rms is not None and track.residual_rms > TRACK_RESIDUAL_LIMIT
        if too_big or failed:
            if too_big:
                (firm_disputed if firm_clock else disputed).append(
                    (
                        1e6 * (rate / track.q / symbol_rate_nominal - 1),
                        1e6 * (rate / timing.q / symbol_rate_nominal - 1),
                    )
                )
            track = replace(track, start=start, q=timing.q, drift_samples=0.0)
        tracks.append(track)
    for (number, _), track in zip(complete, tracks, strict=True):
        start, q = track.start, track.q
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
        known = frame.indices[PREAMBLE_LENGTH:HEAD]
        training_symbols += known.size
        training_errors += int(
            (detect_minimum_distance(equalized[PREAMBLE_LENGTH:HEAD]) != known).sum()
        )
        scored = None
        if score_payload:
            decided = detect_map(equalized, law, priors)
            scored = (
                decided,
                evaluate(detect_minimum_distance(equalized), equalized, frame, law, priors),
                evaluate(decided, equalized, frame, law, priors),
            )
        results.append(
            FrameAnalysis(
                frame_number=number,
                start_time_s=waveform.x_origin_s + start / (OVERSAMPLING * rate),
                phase_samples=phase,
                gain_v_per_level=sign * calibration.gain,
                offset_v=float(waveform.samples_v.mean()) + sign * calibration.offset,
                ffe_taps=weights,
                likelihood=law,
                symbols=equalized if score_payload else equalized[:HEAD],
                decisions_map=scored[0] if scored else np.zeros(0, dtype=np.int64),
                minimum_distance=scored[1] if scored else None,
                map=scored[2] if scored else None,
                timing_drift_samples=track.drift_samples,
            )
        )
        if scored:
            histogram += np.bincount(scored[0][frame.payload_start :], minlength=4)
            payload = np.arange(frame.payload_start, n_symbols)
            chosen = payload[np.linspace(0, payload.size - 1, MAX_EYE_TRACES, dtype=int)]
            grid = start + (chosen[:, None] + 0.5 + eye_offsets[None, :]) * OVERSAMPLING * q + phase
            ok = np.all((grid >= 1) & (grid <= signal.size - 2), axis=1)
            traces = sign * spline(grid[ok])
            eye_rows.append((traces - calibration.offset) / calibration.gain)
    rng = np.random.default_rng(seed)
    sent = frame.indices[frame.payload_start :]
    distinct = int(sent.size)
    level_counts = [int((sent == k).sum()) for k in range(4)]
    reliable = all(count >= MIN_LEVEL_SYMBOLS for count in level_counts)
    if not reliable:
        warnings.append(
            f"Fewer than {MIN_LEVEL_SYMBOLS} distinct test symbols on a level; MI/GMI unreliable"
        )
    if len(results) > 1:
        warnings.append(
            f"Frames repeat the same {distinct} payload symbols, so pooled symbols are not "
            "independent data and level counts are per frame"
        )
    if lost:
        reliable = False
    if not timing.spacing_regular:
        reliable = False
        warnings.append(
            "Frame spacing was irregular, so lost frames cannot be counted; rate estimate "
            "marked unreliable"
        )
    if disputed:
        tracker_ppm, spacing_ppm = max(disputed, key=lambda pair: abs(pair[0] - pair[1]))
        reliable = False
        warnings.append(
            f"Clock estimates disagree: timing tracking inside the frame gives {tracker_ppm:.1f} "
            f"ppm, the fit to frame spacing gives {spacing_ppm:.1f} ppm "
            f"({abs(tracker_ppm - spacing_ppm):.1f} ppm apart, "
            f"limit {TRACK_MAX_CORRECTION_PPM:g}). "
            "The tracked correction was discarded, but the spacing clock cannot be trusted: "
            "dropped or inserted samples between preambles shift it, and a fit through 2 "
            "preambles has no residual to reveal that. The clock is marked low confidence and "
            "the rate estimate unreliable; capture 3 or more full frames"
        )
    if firm_disputed:
        per_frame = training_symbols // len(results)
        train_ser = training_errors / training_symbols
        upper = clopper_pearson(
            min(per_frame, round(train_ser * per_frame)), per_frame, FIRM_CONFIDENCE
        )[1]
        poor = ""
        if score_payload:
            scored_md = [f.minimum_distance for f in results if f.minimum_distance is not None]
            payload_ser = sum(m.symbol_errors for m in scored_md) / sum(
                m.symbols for m in scored_md
            )
            if payload_ser > upper + FIRM_PAYLOAD_EXCESS:
                poor = (
                    f"the payload symbol error rate {payload_ser:.3g} is far above the "
                    f"{upper:.3g} (upper {FIRM_CONFIDENCE:.0%} bound) that the training block "
                    f"({train_ser:.3g}) predicts"
                )
        if not poor and train_ser >= FIRM_TRAINING_SER:
            poor = f"the training block is decided at {train_ser:.3g} errors, near chance"
        if poor:
            tracker_ppm, spacing_ppm = max(firm_disputed, key=lambda p: abs(p[0] - p[1]))
            disputed.append((tracker_ppm, spacing_ppm))
            reliable = False
            warnings.append(
                f"Clock estimates disagree despite {timing.frame_numbers.size} regular "
                f"preambles: timing tracking inside the frame gives {tracker_ppm:.1f} ppm, the "
                f"fit to frame spacing gives {spacing_ppm:.1f} ppm "
                f"({abs(tracker_ppm - spacing_ppm):.1f} ppm apart, limit "
                f"{TRACK_MAX_CORRECTION_PPM:g}), and {poor}. Equal dropped or inserted samples "
                "at every frame gap keep the spacing regular but shift its clock, so the rate "
                "estimate is marked unreliable"
            )
    residuals = [t.residual_rms for t in tracks if t.residual_rms is not None]
    untracked = [t for t in tracks if t.residual_rms is None]
    if residuals and max(residuals) > TRACK_RESIDUAL_LIMIT:
        if firm_clock:
            warnings.append(
                f"Note: timing tracking residual {max(residuals):.2f} samples exceeds "
                f"{TRACK_RESIDUAL_LIMIT} inside a frame (noise or a slow bandwidth-limited eye); "
                f"the clock from {timing.frame_numbers.size} regularly spaced preambles stands "
                "and the rate estimate stays reliable"
            )
        else:
            reliable = False
            warnings.append(
                f"Timing tracking residual {max(residuals):.2f} samples exceeds "
                f"{TRACK_RESIDUAL_LIMIT} across a frame; the sampling instant may drift in part "
                "of the frame, so the rate estimate is marked unreliable"
            )
    if untracked and timing.confidence in ("low", "none"):
        reliable = False
        warnings.append(
            "Timing could not be tracked across the frame and the clock rests on one preamble; "
            "rate estimate marked unreliable"
        )
    q_final = timing.q
    stderr_ppm = timing.stderr_ppm
    confidence = timing.confidence
    if (
        timing.confidence == "low"
        and not untracked
        and timing.spacing_regular
        and not (residuals and max(residuals) > TRACK_RESIDUAL_LIMIT)
    ):
        q_final = float(np.mean([t.q for t in tracks]))
        stderr_ppm = float(np.mean([t.stderr_ppm for t in tracks if t.stderr_ppm is not None]))
        confidence = "medium"
        warnings.append(
            "Clock refined by decision-directed timing tracking over the frame (medium confidence)"
        )
    if disputed:
        confidence = "low"
        stderr_ppm = None
    estimated_rate = rate / q_final
    expected_count = len(expected_numbers)
    lost_symbols = len(lost) * distinct
    pooled = {}
    if score_payload:
        for name in ("minimum_distance", "map"):
            pooled[name] = _pool(results, name, rng, distinct, lost_symbols, len(lost))
    metrics = [f.map for f in results if f.map is not None]
    return ScopeAnalysis(
        measured_sample_rate=sample_rate,
        symbol_rate_nominal=symbol_rate_nominal,
        estimated_symbol_rate=estimated_rate,
        clock_offset_ppm=1e6 * (estimated_rate / symbol_rate_nominal - 1),
        clock_stderr_ppm=stderr_ppm,
        clock_confidence=confidence,
        polarity_inverted=sign < 0,
        preamble_correlation=timing.strength,
        frames_found=int(timing.frame_numbers.size),
        frames_complete=len(results),
        frames_expected=max(expected_count, len(results)),
        frames_analyzed=len(results),
        frames_lost=len(lost),
        lost_frame_numbers=lost,
        frames=results,
        minimum_distance=pooled.get("minimum_distance"),
        map=pooled.get("map"),
        r_smd=float(np.mean([m.r_smd for m in metrics])) if metrics else None,
        r_bmd=float(np.mean([m.r_bmd for m in metrics])) if metrics else None,
        snr_db=float(np.mean([m.snr_db for m in metrics])) if metrics else None,
        rate_estimate_reliable=reliable,
        level_test_symbols=level_counts,
        distinct_payload_symbols=distinct,
        training_symbols=training_symbols,
        training_symbol_errors=training_errors,
        timing_residual_rms_samples=max(residuals) if residuals else None,
        gain_v_per_level=float(np.mean([f.gain_v_per_level for f in results])),
        offset_v=float(np.mean([f.offset_v for f in results])),
        symbol_histogram=histogram if score_payload else None,
        eye=np.concatenate(eye_rows) if eye_rows else np.zeros((0, eye_offsets.size)),
        eye_time_ui=eye_offsets,
        warnings=warnings,
    )
