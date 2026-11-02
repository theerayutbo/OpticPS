"""B2B-calibrated surrogate of an IM/DD link with fibre (Stage 3A, gate E2 part a).

What it is. A synthetic waveform generator: seeded independent symbols drawn with stated level
probabilities, a zero-phase lumped pulse whose magnitude is the B2B power spectral density, four
level values and one noise standard deviation fitted on B2B, an optional small-signal
dispersion filter and an optional amplitude ratio at the receiver. It predicts what a 2 km or
10 km capture would show in the four metrics of `e2_metrics` (level spacing, amplitude histogram,
quantiles, spectrum shape up to the baud rate). It never uses a bit or symbol reference, and it is
never driven by a sequence recovered from B2B (plan R2.4): the drivers are the seed and the level
probabilities only.

What it assumes, declared in `MODEL_GAPS` and `ASSUMPTIONS` and carried into every result:

- chirp is zero (`MODEL GAP: CHIRP`): the dispersion response is the small-signal double-sideband
  intensity response cos(pi lambda^2 D L f^2 / c) of a chirp-free modulator. A COTS Mach-Zehnder
  modulator of unnamed model has an unknown chirp, so the dispersion-dependent part is a scenario,
  not a measured fact;
- small-signal: B2B has no recoverable optical offset or modulation depth, so the large-signal
  field-level response cannot be built;
- the phase of the lumped TX and RX response is unidentifiable from a power spectrum; zero phase is
  assumed;
- noise is shaped like the B2B spectrum and, by scenario, either unscaled (receiver dominated,
  added after the fibre) or scaled with the signal; the B2B split between the two is
  unidentifiable;
- the wavelength is unknown (O-band only), so the dispersion is a finite list of scenarios bounded
  by the ITU-T G.652.D limits, each labelled `ASSUMED_G652D`, never ground truth;
- launch power and fibre loss are unknown, so the amplitude ratio at the receiver is a scenario
  (matched, or the G.652 typical link loss).

Nothing here reads a capture. Fitting takes arrays; the scorer reads B2B.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from opticps.benchmarks.e2_metrics import (
    WELCH_SEGMENT,
    WindowSummary,
    kmeans_levels,
    metrics_between,
    require_window,
    summarise_window,
    welch_density,
)
from opticps.benchmarks.provenance import BenchmarkError

FloatArray = NDArray[np.float64]

SPEED_OF_LIGHT_M_S = 299_792_458.0
NOMINAL_WAVELENGTH_NM = 1310.0  # O-band centre; only enters lambda^2 of the dispersion response
PSD_FLOOR = 1e-16  # relative power floor (-160 dB); the B2B spectrum falls to about -96 dB
PULSE_SAMPLES = 1024
TAPER_FRACTION = 0.25  # outer quarter of the pulse on each side is tapered by a raised cosine
FIT_SAMPLES = 1 << 20
FIT_ITERATIONS = 8
POLISH_EVALUATIONS = 150
MODEL_GAPS = (
    "CHIRP: the modulator chirp is unidentifiable from B2B; the dispersion response assumes zero",
    "LARGE_SIGNAL: optical offset and modulation depth are not recoverable from AC-normalised B2B",
    "PHASE: the lumped response phase is unidentifiable from a power spectrum; zero phase assumed",
    "NOISE_ORIGIN: signal-borne and receiver noise are not separable on B2B; noise follows fibre",
)
ASSUMPTIONS = (
    "level probabilities uniform and symbols independent (the record states neither)",
    "fibre type, wavelength, dispersion and loss are scenarios (ASSUMED_G652D), not ground truth",
    "launch power unknown: the received amplitude ratio is a scenario",
    "AC-coupled: the amplitude ratio scales the signal about the B2B level centre",
)


def ratio_of(sample_rate_hz: float, baud_bd: float) -> Fraction:
    """Samples per symbol as an exact fraction (40.96 is 1024/25), or an error."""
    if not (math.isfinite(sample_rate_hz) and sample_rate_hz > 0):
        raise BenchmarkError("the sample rate must be finite and positive")
    if not (math.isfinite(baud_bd) and baud_bd > 0):
        raise BenchmarkError("the baud rate must be finite and positive")
    value = sample_rate_hz / baud_bd
    fraction = Fraction(value).limit_denominator(1000)
    if abs(float(fraction) - value) > 1e-9 * value or fraction < 4:
        raise BenchmarkError(f"samples per symbol {value!r} is not a ratio of small integers >= 4")
    return fraction


def dispersion_response(
    frequency_hz: NDArray[np.floating[Any]], dispersion_ps_nm_km: float, length_km: float
) -> FloatArray:
    """Small-signal intensity response of a chirp-free modulator: cos(pi lambda^2 D L f^2 / c)."""
    for name, value in (("dispersion", dispersion_ps_nm_km), ("length", length_km)):
        if not math.isfinite(value):
            raise BenchmarkError(f"{name} must be finite")
    if length_km < 0:
        raise BenchmarkError("the fibre length must not be negative")
    d_si = dispersion_ps_nm_km * 1e-6  # ps/(nm km) in s/m^2
    lam = NOMINAL_WAVELENGTH_NM * 1e-9
    theta = math.pi * lam**2 * d_si * (length_km * 1e3) * frequency_hz**2 / SPEED_OF_LIGHT_M_S
    return np.asarray(np.cos(theta), dtype=np.float64)


def loss_amplitude_ratio(attenuation_db_per_km: float, length_km: float) -> float:
    """Electrical amplitude ratio of a photodiode for an optical power loss in dB."""
    if not (math.isfinite(attenuation_db_per_km) and attenuation_db_per_km >= 0):
        raise BenchmarkError("attenuation must be finite and not negative")
    if not (math.isfinite(length_km) and length_km >= 0):
        raise BenchmarkError("the fibre length must be finite and not negative")
    return float(10.0 ** (-attenuation_db_per_km * length_km / 10.0))


def _check_psd(psd_rel: Sequence[float]) -> FloatArray:
    psd = np.asarray(psd_rel, dtype=np.float64)
    if psd.shape != (WELCH_SEGMENT // 2 + 1,):
        raise BenchmarkError(f"the B2B spectrum must have {WELCH_SEGMENT // 2 + 1} bins")
    if not np.isfinite(psd).all() or not (psd > 0).all():
        raise BenchmarkError("the B2B spectrum must be finite and positive")
    return psd


def _magnitude(psd_rel: FloatArray) -> FloatArray:
    return np.sqrt(np.maximum(psd_rel / psd_rel.max(), PSD_FLOOR))


def lumped_pulse(
    psd_rel: Sequence[float],
    sample_rate_hz: float,
    *,
    dispersion_ps_nm_km: float = 0.0,
    length_km: float = 0.0,
    pulse_samples: int = PULSE_SAMPLES,
) -> FloatArray:
    """Zero-phase pulse of unit centre value for the undispersed case, tapered at both ends.

    Its magnitude response is the square root of the B2B spectrum, times the dispersion response
    for the dispersed case. The centre value of the undispersed pulse is the reference, so a
    dispersed pulse is on the same scale. The pulse is `pulse_samples` long, centred on index
    `pulse_samples // 2`.
    """
    psd = _check_psd(psd_rel)
    if pulse_samples < 64 or pulse_samples % 2:
        raise BenchmarkError("the pulse length must be even and at least 64 samples")
    grid = np.arange(WELCH_SEGMENT // 2 + 1) * (sample_rate_hz / WELCH_SEGMENT)
    magnitude = _magnitude(psd)

    def build(response: FloatArray) -> FloatArray:
        half = magnitude * response
        full = np.concatenate([half, half[-2:0:-1]])
        raw = np.fft.ifft(full).real
        centred = np.roll(raw, pulse_samples // 2)[:pulse_samples]
        edge = int(pulse_samples * TAPER_FRACTION)
        ramp = 0.5 * (1.0 - np.cos(np.pi * (np.arange(edge) + 0.5) / edge))
        window = np.ones(pulse_samples)
        window[:edge] = ramp
        window[-edge:] = ramp[::-1]
        return np.asarray(centred * window, dtype=np.float64)

    reference = build(np.ones_like(magnitude))
    scale = float(reference[pulse_samples // 2])
    if not scale > 0:
        raise BenchmarkError("the B2B spectrum gives a pulse without a positive centre")
    response = dispersion_response(grid, dispersion_ps_nm_km, length_km)
    return build(response) / scale


def fractional_pulse(pulse: FloatArray, fraction: float) -> FloatArray:
    """The pulse delayed by `fraction` of a sample (frequency-domain shift)."""
    n = pulse.size
    spectrum = np.fft.rfft(pulse)
    phase = np.exp(-2j * np.pi * np.fft.rfftfreq(n) * fraction)
    return np.asarray(np.fft.irfft(spectrum * phase, n), dtype=np.float64)


def shaped_noise(
    psd_rel: Sequence[float], sample_rate_hz: float, n_samples: int, sigma: float, seed: int
) -> FloatArray:
    """Gaussian noise with the shape of the B2B spectrum and sample standard deviation `sigma`."""
    if not (math.isfinite(sigma) and sigma >= 0):
        raise BenchmarkError("the noise standard deviation must be finite and not negative")
    magnitude = _magnitude(_check_psd(psd_rel))
    rng = np.random.default_rng(np.random.PCG64(seed))
    white = rng.standard_normal(n_samples)
    freq = np.fft.rfftfreq(n_samples, 1.0 / sample_rate_hz)
    grid = np.arange(WELCH_SEGMENT // 2 + 1) * (sample_rate_hz / WELCH_SEGMENT)
    shape = np.interp(freq, grid, magnitude)
    noise = np.fft.irfft(np.fft.rfft(white) * shape, n_samples)
    spread = float(noise.std())
    if not spread > 0:
        raise BenchmarkError("the shaped noise has no spread")
    return np.asarray(noise * (sigma / spread), dtype=np.float64)


def block_count(n_samples: int, pulse_length: int, period: int) -> int:
    """Blocks of `period` samples that cover a window and the pulse tails round it."""
    return (n_samples + 3 * pulse_length) // period + 2


def draw_symbols(
    blocks: int, classes: int, probabilities: FloatArray, seed: int
) -> NDArray[np.int64]:
    """Seeded independent symbols, shape (blocks, classes); symbol m * classes + c is at
    block m, class c. The only driver of a prediction besides the level probabilities."""
    rng = np.random.default_rng(np.random.PCG64(seed))
    return np.asarray(rng.choice(4, size=(blocks, classes), p=probabilities), dtype=np.int64)


def synthesize(
    model: Mapping[str, Any],
    *,
    n_samples: int,
    symbol_seed: int,
    noise_seed: int,
    dispersion_ps_nm_km: float = 0.0,
    length_km: float = 0.0,
    amplitude_ratio: float = 1.0,
    noise_follows_signal: bool = False,
    noise_through_fibre: bool = False,
    levels: Sequence[float] | FloatArray | None = None,
    sigma: float | None = None,
) -> FloatArray:
    """A predicted normalised waveform of `n_samples` samples for one scenario.

    `model` is the B2B model document (`fit_b2b_model`). The signal is the sum of tapered zero-phase
    pulses at the symbol instants, each scaled by the fitted level of its seeded symbol; instants
    are exact (40.96 samples per symbol is 1024/25: 25 classes, each with its own fractional
    delay). The amplitude ratio scales the signal; the noise is added unscaled (receiver-dominated)
    or, with `noise_follows_signal`, scaled by the same ratio (signal-borne), or, with
    `noise_through_fibre`, filtered by the dispersion response like the signal: the origin of the
    B2B noise is unidentifiable, so these are scenarios.
    """
    if type(n_samples) is not int or n_samples < 1024:
        raise BenchmarkError("n_samples must be an integer of at least 1024")
    if not (math.isfinite(amplitude_ratio) and amplitude_ratio >= 0):
        raise BenchmarkError("the amplitude ratio must be finite and not negative")
    fs = float(model["sample_rate_hz"])
    baud = float(model["baud_bd"])
    ratio = ratio_of(fs, baud)
    period, classes = ratio.numerator, ratio.denominator  # `period` samples hold `classes` symbols
    level = np.asarray(model["pulse_levels"] if levels is None else levels, dtype=np.float64)
    noise_sigma = float(model["noise_sigma"] if sigma is None else sigma)
    probabilities = np.asarray(model["level_probabilities"], dtype=np.float64)
    if level.shape != (4,) or not np.isfinite(level).all():
        raise BenchmarkError("four finite level values are needed")
    if probabilities.shape != (4,) or not math.isclose(
        float(probabilities.sum()), 1.0, abs_tol=1e-9
    ):
        raise BenchmarkError("the level probabilities must be four numbers that sum to 1")
    if (probabilities < 0).any():
        raise BenchmarkError("a level probability is negative")
    pulse_length = int(model["pulse_samples"])
    base = lumped_pulse(
        model["psd_relative"],
        fs,
        dispersion_ps_nm_km=dispersion_ps_nm_km,
        length_km=length_km,
        pulse_samples=pulse_length,
    )
    chunks = -(-pulse_length // period)  # pulse length in blocks of `period` samples
    padded = np.zeros(chunks * period)
    blocks = block_count(n_samples, pulse_length, period)
    buffer = np.zeros(blocks * period + (chunks + 1) * period)
    amplitudes = level[draw_symbols(blocks, classes, probabilities, symbol_seed)]
    for c in range(classes):
        start, fraction = divmod(c * period, classes)
        shifted = fractional_pulse(base, fraction / classes)
        padded[:pulse_length] = shifted
        pieces = padded.reshape(chunks, period)
        for j in range(chunks):
            begin = start + j * period
            view = buffer[begin : begin + blocks * period].reshape(blocks, period)
            view += amplitudes[:, c, None] * pieces[j][None, :]
    crop = buffer[pulse_length : pulse_length + n_samples]
    noise = shaped_noise(model["psd_relative"], fs, n_samples, noise_sigma, noise_seed)
    if noise_through_fibre:
        # the other bound of the unidentifiable noise origin: the noise crosses the fibre too
        response = dispersion_response(
            np.fft.rfftfreq(n_samples, 1.0 / fs), dispersion_ps_nm_km, length_km
        )
        noise = np.fft.irfft(np.fft.rfft(noise) * response, n_samples)
    out = amplitude_ratio * crop + (amplitude_ratio * noise if noise_follows_signal else noise)
    if not np.isfinite(out).all():
        raise BenchmarkError("the synthetic waveform is not finite")
    return np.asarray(out, dtype=np.float64)


def fit_objective(reference: WindowSummary, predicted: WindowSummary) -> float:
    """Training loss: M1 + M2 + M3 + 0.05 * M4 between the B2B window and a synthetic one."""
    m = metrics_between(reference, predicted)
    return (
        m["M1_level_spacing"]
        + m["M2_wasserstein1_amplitude"]
        + m["M3_quantile_error"]
        + 0.05 * m["M4_log_spectral_distance"]
    )


def fit_b2b_model(
    fit_window_normalised: FloatArray,
    *,
    sample_rate_hz: float,
    baud_bd: float,
    fit_seed: int,
    pulse_samples: int = PULSE_SAMPLES,
    fit_samples: int = FIT_SAMPLES,
    iterations: int = FIT_ITERATIONS,
    polish_evaluations: int = POLISH_EVALUATIONS,
) -> dict[str, Any]:
    """Fit the four pulse levels and the noise standard deviation to B2B alone.

    Input is the B2B fit window after the one affine normalisation. The spectrum shape is the Welch
    estimate of the same window. Step 1 adjusts the levels until the synthetic centroids equal the
    B2B centroids and the noise until the synthetic standard deviation equals the B2B one. Step 2
    polishes the five numbers by Nelder-Mead on `fit_objective` (M1 + M2 + M3 + 0.05 M4 against the
    B2B window). Both steps use a synthetic window of `fit_samples` and the seeds `fit_seed` and
    `fit_seed + 1`; the objective is therefore deterministic. Returns the model document (plain
    Python types). No other capture enters.
    """
    window = require_window(fit_window_normalised, "B2B fit window")
    target_centroids, shares = kmeans_levels(window)
    target_std = float(window.std())
    _, psd = welch_density(window, sample_rate_hz)
    model: dict[str, Any] = {
        "sample_rate_hz": float(sample_rate_hz),
        "baud_bd": float(baud_bd),
        "pulse_samples": int(pulse_samples),
        "psd_relative": [float(v) for v in psd / psd.max()],
        "level_probabilities": [0.25, 0.25, 0.25, 0.25],
        "pulse_levels": [float(v) for v in target_centroids],
        "noise_sigma": 0.3 * target_std,
    }

    def draw(levels: FloatArray, sigma: float) -> FloatArray:
        return synthesize(
            model, n_samples=fit_samples, symbol_seed=fit_seed, noise_seed=fit_seed + 1,
            levels=levels, sigma=sigma,
        )  # fmt: skip

    levels = np.array(model["pulse_levels"])
    sigma = float(model["noise_sigma"])
    for _ in range(iterations):
        y = draw(levels, sigma)
        levels = levels + (target_centroids - kmeans_levels(y)[0])
        sigma = math.sqrt(max(sigma**2 + target_std**2 - float(y.var()), (0.02 * target_std) ** 2))

    reference = summarise_window(window, sample_rate_hz, baud_bd)

    def loss(v: FloatArray) -> float:
        synthetic = summarise_window(draw(v[:4], abs(float(v[4]))), sample_rate_hz, baud_bd)
        value = fit_objective(reference, synthetic)
        return value if math.isfinite(value) else 1e9

    start = np.concatenate([levels, [sigma]])
    if polish_evaluations > 0:
        result = minimize(
            loss, start, method="Nelder-Mead",
            options={"xatol": 1e-3, "fatol": 1e-5, "maxfev": polish_evaluations},
        )  # fmt: skip
        start = np.asarray(result.x, dtype=np.float64)
    model["pulse_levels"] = [float(v) for v in start[:4]]
    model["noise_sigma"] = abs(float(start[4]))
    model["b2b_centroids_normalised"] = [float(v) for v in target_centroids]
    model["b2b_cluster_shares"] = [float(v) for v in shares]
    model["b2b_std_normalised"] = target_std
    model["fit"] = {
        "seed": int(fit_seed),
        "fit_samples": int(fit_samples),
        "moment_iterations": int(iterations),
        "polish_evaluations": int(polish_evaluations),
        "objective": "M1 + M2 + M3 + 0.05 * M4 against the B2B fit window",
    }
    return model
