"""Periodic pulse shaping for looped AWG playback.

The waveform is treated as one period, so there is no filter transient and no seam
at the loop point. A linear mode with explicit filter tails is also available.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class PulseConfig:
    """Pulse shape settings. Only rrc uses roll_off."""

    shape: str = "nrz"
    roll_off: float = 0.35
    boundary: str = "circular"

    def __post_init__(self) -> None:
        if self.shape not in ("nrz", "rrc"):
            raise ValueError(f"Unknown pulse shape {self.shape!r}")
        if self.boundary not in ("circular", "linear"):
            raise ValueError(f"Unknown boundary mode {self.boundary!r}")
        if not 0 < self.roll_off <= 1:
            raise ValueError(f"Roll-off must be in (0, 1], got {self.roll_off}")


def rrc_frequency_response(n: int, sps: int, roll_off: float) -> FloatArray:
    """Return the zero-phase root-raised-cosine response on an n-point FFT grid."""
    f = np.abs(np.fft.fftfreq(n, d=1.0 / sps))
    low = (1 - roll_off) / 2
    high = (1 + roll_off) / 2
    response = np.zeros(n)
    response[f <= low] = 1.0
    band = (f > low) & (f < high)
    response[band] = np.cos(np.pi / (2 * roll_off) * (f[band] - low))
    return response


def symbol_centre_offset(sps: int, config: PulseConfig) -> float:
    """Return the sample offset of the centre of symbol 0 from waveform sample 0."""
    return (sps - 1) / 2 if config.shape == "nrz" else 0.0


def peak_factor(sps: int, config: PulseConfig, n_symbols: int = 4096) -> float:
    """Return the worst-case sum of |pulse| over symbols, per unit level.

    Multiplying by the largest level bounds the waveform for any data, which gives a
    full scale that is independent of the distribution.
    """
    if config.shape == "nrz":
        return 1.0
    n = n_symbols * sps
    pulse = np.fft.ifft(rrc_frequency_response(n, sps, config.roll_off)).real * sps
    return float(max(np.abs(pulse[phase::sps]).sum() for phase in range(sps)))


def shape(indices_levels: FloatArray, sps: int, config: PulseConfig) -> FloatArray:
    """Convert symbol levels to samples; output length is len(levels) * sps when circular."""
    levels = np.asarray(indices_levels, dtype=float)
    if sps < 1:
        raise ValueError(f"Samples per symbol must be at least 1, got {sps}")
    if config.shape == "nrz":
        return np.repeat(levels, sps)
    if config.boundary == "linear":
        tail = 32
        padded = np.concatenate([np.zeros(tail), levels, np.zeros(tail)])
        return shape(padded, sps, PulseConfig("rrc", config.roll_off, "circular"))
    n = levels.size * sps
    impulses = np.zeros(n)
    impulses[::sps] = levels * sps
    spectrum = np.fft.fft(impulses) * rrc_frequency_response(n, sps, config.roll_off)
    return np.fft.ifft(spectrum).real


def resample_periodic(samples: FloatArray, ratio: float) -> FloatArray:
    """Resample one period by band-limited interpolation; output length rounds ratio * n."""
    target = int(round(samples.size * ratio))
    if target == samples.size:
        return samples.copy()
    spectrum = np.fft.rfft(samples)
    size = target // 2 + 1
    resized = np.zeros(size, dtype=complex)
    keep = min(size, spectrum.size)
    resized[:keep] = spectrum[:keep]
    return np.asarray(np.fft.irfft(resized, n=target) * (target / samples.size), float)
