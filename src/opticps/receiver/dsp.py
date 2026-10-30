"""Receiver DSP for simulated and captured waveforms.

Everything that is tuned (gain, offset, equalizer, likelihoods) is fitted on the known
preamble and training symbols only, so payload statistics cannot leak in.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from opticps.modulation.pam import indices_to_bits, label_bits, pam_levels
from opticps.statistics.intervals import clopper_pearson
from opticps.transmitter.frame import PREAMBLE_LENGTH, TRAINING_LENGTH, Frame, preamble_indices

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
HEAD = PREAMBLE_LENGTH + TRAINING_LENGTH


def resample_to_symbols(
    capture: FloatArray, sample_rate: float, symbol_rate: float, oversampling: int = 8
) -> FloatArray:
    """Resample one or more periods to an integer number of samples per symbol.

    Uses band-limited (FFT) interpolation on the periodic capture. Non-periodic
    fragments are also accepted; their edges will show ordinary Gibbs ripple.
    """
    target = int(round(capture.size * symbol_rate * oversampling / sample_rate))
    if target == capture.size:
        return capture.copy()
    spectrum = np.fft.rfft(capture - capture.mean())
    size = target // 2 + 1
    resized = np.zeros(size, dtype=complex)
    keep = min(size, spectrum.size)
    resized[:keep] = spectrum[:keep]
    return np.fft.irfft(resized, n=target) * (target / capture.size) + capture.mean()


@dataclass(frozen=True)
class Sync:
    """Frame alignment result."""

    offset_samples: int
    inverted: bool
    peak_to_sidelobe: float


def frame_sync(signal: FloatArray, oversampling: int) -> Sync:
    """Locate the preamble by circular correlation, detecting polarity inversion."""
    template = np.repeat(pam_levels(4)[preamble_indices()], oversampling)
    padded = np.zeros(signal.size)
    padded[: template.size] = template
    correlation = np.fft.irfft(
        np.fft.rfft(signal - signal.mean()) * np.conj(np.fft.rfft(padded)), n=signal.size
    )
    peak = int(np.argmax(np.abs(correlation)))
    magnitude = np.abs(correlation)
    window = np.arange(peak - oversampling * 2, peak + oversampling * 2) % signal.size
    masked = magnitude.copy()
    masked[window] = 0
    return Sync(peak, bool(correlation[peak] < 0), float(magnitude[peak] / masked.max()))


def align(signal: FloatArray, sync: Sync, oversampling: int, n_symbols: int) -> FloatArray:
    """Return exactly one frame at symbol-centre samples, corrected for polarity."""
    offset = sync.offset_samples + oversampling // 2
    positions = (offset + oversampling * np.arange(n_symbols)) % signal.size
    aligned = signal[positions]
    return -aligned if sync.inverted else aligned


def matched_filter(signal: FloatArray, oversampling: int) -> FloatArray:
    """Apply the rectangular matched filter of an NRZ pulse, periodic in time."""
    box = np.zeros(signal.size)
    box[:oversampling] = 1 / oversampling
    box = np.roll(box, -(oversampling // 2))
    return np.asarray(np.fft.irfft(np.fft.rfft(signal) * np.fft.rfft(box), n=signal.size), float)


@dataclass(frozen=True)
class Calibration:
    """Offset and gain from the preamble, with symbols scaled to nominal levels."""

    offset: float
    gain: float


def calibrate(symbols: FloatArray, reference: IntArray) -> Calibration:
    """Least-squares fit on the known preamble, not on the payload mean."""
    levels = pam_levels(4)[reference[:PREAMBLE_LENGTH]]
    measured = symbols[:PREAMBLE_LENGTH]
    gain, offset = np.polyfit(levels, measured, 1)
    if gain == 0:
        raise ValueError("Calibration failed: zero gain")
    return Calibration(float(offset), float(gain))


def train_ffe(
    symbols: FloatArray,
    reference: IntArray,
    taps: int = 15,
    regularization: float = 1e-6,
) -> FloatArray:
    """Fit a symbol-spaced FFE by regularized least squares on preamble and training."""
    if taps % 2 == 0:
        raise ValueError("Use an odd number of taps")
    half = taps // 2
    target = pam_levels(4)[reference[:HEAD]]
    rows = np.arange(half, HEAD - half)
    matrix = np.stack([symbols[rows + k] for k in range(-half, half + 1)], axis=1)
    normal = matrix.T @ matrix + regularization * rows.size * np.eye(taps)
    return np.asarray(np.linalg.solve(normal, matrix.T @ target[rows]), dtype=float)


def lms_ffe(
    symbols: FloatArray,
    reference: IntArray,
    taps: int = 15,
    step: float = 0.002,
    epochs: int = 30,
) -> FloatArray:
    """Fit the same FFE by the LMS recursion on preamble and training only."""
    half = taps // 2
    target = pam_levels(4)[reference[:HEAD]]
    weights = np.zeros(taps)
    weights[half] = 1.0
    for _ in range(epochs):
        for n in range(half, HEAD - half):
            window = symbols[n - half : n + half + 1]
            weights += step * (target[n] - weights @ window) * window
    return weights


def apply_ffe(symbols: FloatArray, weights: FloatArray) -> FloatArray:
    """Apply an FFE with periodic boundaries."""
    half = weights.size // 2
    return sum(
        w * np.roll(symbols, -k) for k, w in zip(range(-half, half + 1), weights, strict=False)
    )


@dataclass(frozen=True)
class Likelihood:
    """Per-level Gaussian channel law estimated from training symbols."""

    means: FloatArray
    sigmas: FloatArray


def estimate_likelihood(symbols: FloatArray, reference: IntArray) -> Likelihood:
    """Fit level means and spreads on the training section."""
    block = symbols[PREAMBLE_LENGTH:HEAD]
    known = reference[PREAMBLE_LENGTH:HEAD]
    means = np.array([block[known == s].mean() for s in range(4)])
    sigmas = np.array([max(block[known == s].std(ddof=1), 1e-9) for s in range(4)])
    return Likelihood(means, sigmas)


def log_likelihoods(symbols: FloatArray, law: Likelihood) -> FloatArray:
    """Return log p(y|x) for each sample and level."""
    delta = (symbols[:, None] - law.means) / law.sigmas
    return -0.5 * delta**2 - np.log(law.sigmas)


def detect_minimum_distance(symbols: FloatArray) -> IntArray:
    """Decide the nearest nominal level, ignoring priors."""
    return np.argmin(np.abs(symbols[:, None] - pam_levels(4)), axis=1)


def detect_map(symbols: FloatArray, law: Likelihood, priors: FloatArray) -> IntArray:
    """Decide argmax_x p(y|x) P(x)."""
    return np.argmax(log_likelihoods(symbols, law) + np.log(priors), axis=1)


@dataclass(frozen=True)
class Metrics:
    """Payload performance. Rates are estimates using the training-fitted channel law."""

    symbols: int
    symbol_errors: int
    ser: float
    ser_ci: tuple[float, float]
    bits: int
    bit_errors: int
    ber: float
    ber_ci: tuple[float, float]
    r_smd: float
    r_bmd: float
    snr_db: float
    block_error_symbols: list[int]


def estimate_rates(
    symbols: FloatArray, sent: IntArray, law: Likelihood, priors: FloatArray
) -> tuple[float, float]:
    """Estimate R_SMD and R_BMD by the mismatched-decoding sample mean."""
    joint = np.exp(log_likelihoods(symbols, law)) * priors
    total = np.maximum(joint.sum(axis=1), 1e-300)
    posterior = joint / total[:, None]
    entropy = float(-(priors[priors > 0] * np.log2(priors[priors > 0])).sum())
    r_smd = entropy - float(
        np.mean(-np.log2(np.maximum(posterior[np.arange(sent.size), sent], 1e-300)))
    )
    labels = label_bits(4)
    conditional = 0.0
    for k in range(2):
        same = labels[:, k][:, None] == labels[:, k][None, :]
        bit_posterior = posterior @ same.astype(float)
        conditional += float(
            np.mean(-np.log2(np.maximum(bit_posterior[np.arange(sent.size), sent], 1e-300)))
        )
    return r_smd, max(0.0, entropy - conditional)


def evaluate(
    decisions: IntArray, symbols: FloatArray, frame: Frame, law: Likelihood, priors: FloatArray
) -> Metrics:
    """Compare payload decisions with the reference."""
    start = frame.payload_start
    sent = frame.indices[start:]
    received = decisions[start:]
    errors = int((received != sent).sum())
    bit_errors = int((indices_to_bits(received) != indices_to_bits(sent)).sum())
    bits = 2 * sent.size
    r_smd, r_bmd = estimate_rates(symbols[start:], sent, law, priors)
    deviation = symbols[start:] - law.means[sent]
    signal = float((priors * (law.means - priors @ law.means) ** 2).sum())
    per_block = (received != sent).reshape(frame.n_blocks, frame.block_length).sum(axis=1).tolist()
    return Metrics(
        symbols=sent.size,
        symbol_errors=errors,
        ser=errors / sent.size,
        ser_ci=clopper_pearson(errors, sent.size),
        bits=bits,
        bit_errors=bit_errors,
        ber=bit_errors / bits,
        ber_ci=clopper_pearson(bit_errors, bits),
        r_smd=r_smd,
        r_bmd=r_bmd,
        snr_db=10 * float(np.log10(signal / float(np.mean(deviation**2)))),
        block_error_symbols=per_block,
    )


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of processing one capture."""

    sync: Sync
    calibration: Calibration
    ffe_taps: FloatArray
    likelihood: Likelihood
    symbols: FloatArray
    minimum_distance: Metrics
    map: Metrics
    decisions_map: IntArray


def process_capture(
    capture: FloatArray,
    sample_rate: float,
    symbol_rate: float,
    frame: Frame,
    priors: FloatArray,
    taps: int = 15,
    oversampling: int = 8,
    equalizer: str = "ls",
) -> CaptureResult:
    """Run the full chain: resample, matched filter, sync, calibrate, equalize, detect."""
    signal = resample_to_symbols(capture, sample_rate, symbol_rate, oversampling)
    filtered = matched_filter(signal - signal.mean(), oversampling)
    sync = frame_sync(filtered, oversampling)
    # Refine the sampling phase: choose the phase with the largest preamble correlation.
    best: tuple[float, FloatArray] | None = None
    template = pam_levels(4)[frame.indices[:PREAMBLE_LENGTH]]
    for shift in range(-oversampling // 2, oversampling // 2 + 1):
        trial = Sync((sync.offset_samples + shift) % signal.size, sync.inverted, 0.0)
        candidate = align(filtered, trial, oversampling, frame.indices.size)
        score = float(np.dot(candidate[:PREAMBLE_LENGTH], template))
        if best is None or score > best[0]:
            best = (score, candidate)
    assert best is not None
    symbols = best[1]
    calibration = calibrate(symbols, frame.indices)
    normalized = (symbols - calibration.offset) / calibration.gain
    if equalizer == "ls":
        taps_fit = train_ffe(normalized, frame.indices, taps)
    elif equalizer == "lms":
        taps_fit = lms_ffe(normalized, frame.indices, taps)
    else:
        raise ValueError(f"Unknown equalizer {equalizer!r}")
    equalized = apply_ffe(normalized, taps_fit)
    law = estimate_likelihood(equalized, frame.indices)
    md = detect_minimum_distance(equalized)
    decided = detect_map(equalized, law, priors)
    return CaptureResult(
        sync=sync,
        calibration=calibration,
        ffe_taps=taps_fit,
        likelihood=law,
        symbols=equalized,
        minimum_distance=evaluate(md, equalized, frame, law, priors),
        map=evaluate(decided, equalized, frame, law, priors),
        decisions_map=decided,
    )
