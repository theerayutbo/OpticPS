"""Timing for external captures: noninteger samples per symbol and the measured clock (E1).

Nothing here rounds the sampling ratio. The samples-per-symbol ratio is the exact quotient of the
sample rate and the baud rate (`samples_per_symbol`: 256/50 = 5.12, or 2048/50 = 40.96). The symbol
clock is then measured from the waveform, not assumed: the square of the mean-removed signal of an
intensity-modulated waveform carries a tone at the symbol rate, and the phase of that tone, tracked
over windows of whole symbols, gives the symbol phase at every sample. A frequency offset and slow
wander of the clock show up as a drifting phase, which is followed by piecewise-linear
interpolation, so the symbol instants are fractional sample positions that follow the measured
timing. Waveform values at those instants come from a four-point cubic Lagrange interpolator.

No transmitted symbol is used or recovered here. The sampling-phase offset within a symbol (where
the eye is open) is chosen by minimising the within-cluster spread of blind four-level decisions;
that choice is a level-based, inferred quantity.

Tracking range: the tone phase must move by less than 0.8 pi between neighbouring windows, which
limits the relative clock offset to about 0.4 / (symbols per window), 0.16 % for 256-symbol windows.
Outside that range the estimate is refused (`TimingError`), not guessed.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from opticps.benchmarks.provenance import BenchmarkError, ErrorCode

FloatArray = NDArray[np.float64]
DEFAULT_WINDOW_SYMBOLS = 256
MIN_SAMPLES_PER_SYMBOL = 2.0
MAX_PHASE_STEP = 0.8 * math.pi


class TimingError(BenchmarkError):
    """The timebase or the measured clock is not usable."""


def samples_per_symbol(sample_rate_hz: float, baud_bd: float) -> float:
    """Exact ratio of sample rate to symbol rate. Never rounded; refuses an implausible pair."""
    for name, value in (("sample rate", sample_rate_hz), ("baud", baud_bd)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise TimingError(
                f"{name} {value!r} is not a positive finite number", ErrorCode.FORMAT_UNKNOWN
            )
    ratio = float(sample_rate_hz) / float(baud_bd)
    if ratio < MIN_SAMPLES_PER_SYMBOL:
        raise TimingError(
            f"{ratio:.3g} samples per symbol is below {MIN_SAMPLES_PER_SYMBOL}: the timebase and "
            "the baud rate cannot both be right",
            ErrorCode.FORMAT_UNKNOWN,
        )
    return ratio


def interpolate_cubic(x: FloatArray, t: FloatArray) -> FloatArray:
    """Four-point cubic Lagrange interpolation of `x` at fractional indices `t`.

    `t` must lie in [1, len(x) - 3]; indices outside are refused rather than clamped.
    """
    if t.size == 0:
        return np.empty(0)
    if not (np.isfinite(t).all() and t.min() >= 1.0 and t.max() <= len(x) - 3):
        raise TimingError("interpolation instants fall outside the available samples")
    i = np.floor(t).astype(np.int64)
    mu = t - i
    w0 = -mu * (mu - 1.0) * (mu - 2.0) / 6.0
    w1 = (mu + 1.0) * (mu - 1.0) * (mu - 2.0) / 2.0
    w2 = -(mu + 1.0) * mu * (mu - 2.0) / 2.0
    w3 = (mu + 1.0) * mu * (mu - 1.0) / 6.0
    return x[i - 1] * w0 + x[i] * w1 + x[i + 1] * w2 + x[i + 2] * w3


@dataclass(frozen=True)
class TimingModel:
    """Measured symbol clock of one capture (or one segment of it)."""

    sps_nominal: float
    window_samples: int
    centers: FloatArray  # window centre sample indices
    phase_cycles: FloatArray  # unwrapped tone phase at each centre, cycles
    strength: FloatArray  # |tone| / sum(y) per window
    symbol_frequency: float  # measured symbols per sample (fit over all windows)
    n_samples: int
    wander_rms_symbols: float  # rms of the phase left after the linear fit, in symbols
    field_notes: tuple[str, ...] = field(default=())

    @property
    def sps_measured(self) -> float:
        """Samples per symbol from the measured clock (not rounded)."""
        return 1.0 / self.symbol_frequency

    @property
    def offset_ppm(self) -> float:
        """Measured symbol rate relative to the nominal one, parts per million of the nominal."""
        return (self.symbol_frequency * self.sps_nominal - 1.0) * 1e6

    def symbol_phase(self, n: FloatArray) -> FloatArray:
        """Symbol phase in cycles at sample positions `n`; linear extension beyond the windows."""
        f0 = 1.0 / self.sps_nominal
        extra = np.interp(n, self.centers, self.phase_cycles)
        if self.centers.size >= 2:
            low = n < self.centers[0]
            high = n > self.centers[-1]
            slope_low = (self.phase_cycles[1] - self.phase_cycles[0]) / (
                self.centers[1] - self.centers[0]
            )
            slope_high = (self.phase_cycles[-1] - self.phase_cycles[-2]) / (
                self.centers[-1] - self.centers[-2]
            )
            extra = np.where(low, self.phase_cycles[0] + slope_low * (n - self.centers[0]), extra)
            extra = np.where(
                high, self.phase_cycles[-1] + slope_high * (n - self.centers[-1]), extra
            )
        return f0 * n + extra

    def symbol_instants(
        self, first_symbol: int, count: int, offset_symbols: float = 0.0
    ) -> FloatArray:
        """Fractional sample positions of `count` consecutive symbols.

        Symbol m sits where the measured symbol phase equals m + offset (offset in symbols, the
        eye-centre choice). The positions are inverted from the piecewise-linear phase, so a
        drifting
        clock gives unequal spacing, and no spacing is rounded.
        """
        grid = np.linspace(0.0, float(self.n_samples - 1), max(int(self.centers.size) + 2, 2))
        grid = np.unique(np.concatenate([grid, self.centers]))
        phase = self.symbol_phase(grid)
        if not np.all(np.diff(phase) > 0):
            raise TimingError(
                "the measured symbol phase is not increasing: clock estimate unusable"
            )
        targets = np.arange(first_symbol, first_symbol + count, dtype=np.float64) + offset_symbols
        if targets.min() < phase[0] or targets.max() > phase[-1]:
            raise TimingError("requested symbols lie outside the record")
        return np.interp(targets, phase, grid)


@dataclass
class TimingTracker:
    """Accumulates the tone phase window by window; windows are of fixed, whole size."""

    sps_nominal: float
    window_symbols: int = DEFAULT_WINDOW_SYMBOLS
    _centers: list[float] = field(default_factory=list)
    _phase: list[float] = field(default_factory=list)
    _strength: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not math.isfinite(self.sps_nominal) or self.sps_nominal < MIN_SAMPLES_PER_SYMBOL:
            raise TimingError(f"samples per symbol {self.sps_nominal!r} is implausible")
        if self.window_symbols < 16:
            raise TimingError("a timing window needs at least 16 symbols")

    @property
    def window_samples(self) -> int:
        return max(int(round(self.window_symbols * self.sps_nominal)), 64)

    def add_window(self, start: int, window: FloatArray) -> None:
        """One full window beginning at global sample index `start`."""
        y = (window - window.mean()) ** 2
        n = start + np.arange(window.size, dtype=np.float64)
        cycles = np.mod(n / self.sps_nominal, 1.0)
        tone = np.sum(y * np.exp(-2j * np.pi * cycles))
        total = float(y.sum())
        self._centers.append(start + (window.size - 1) / 2.0)
        self._phase.append(float(np.angle(tone)))
        self._strength.append(float(abs(tone) / total) if total > 0 else 0.0)

    def finish(self, n_samples: int) -> TimingModel:
        if len(self._centers) < 3:
            raise TimingError(
                "fewer than three timing windows: the record is too short to track a clock"
            )
        phase = np.unwrap(np.asarray(self._phase))
        raw_steps = np.abs(np.angle(np.exp(1j * np.diff(np.asarray(self._phase)))))
        if float(raw_steps.max()) > MAX_PHASE_STEP:
            raise TimingError(
                "the tone phase moves by more than 0.8 pi between windows: the clock offset is "
                "outside the tracking range or the tone is too weak to follow"
            )
        centers = np.asarray(self._centers)
        cycles = phase / (2.0 * math.pi)
        slope, intercept = np.polyfit(centers, cycles, 1)
        symbol_frequency = 1.0 / self.sps_nominal + float(slope)
        residual = cycles - (slope * centers + intercept)
        notes = []
        strength = np.asarray(self._strength)
        if float(np.median(strength)) < 0.02:
            notes.append("weak symbol tone: timing estimate has low confidence")
        return TimingModel(
            sps_nominal=self.sps_nominal,
            window_samples=self.window_samples,
            centers=centers,
            phase_cycles=cycles,
            strength=strength,
            symbol_frequency=symbol_frequency,
            n_samples=n_samples,
            wander_rms_symbols=float(np.sqrt(np.mean(residual**2))),
            field_notes=tuple(notes),
        )


@dataclass
class Windower:
    """Cuts a stream of blocks into windows of exactly `size`, whatever the block size was."""

    size: int
    _buffer: FloatArray = field(default_factory=lambda: np.empty(0))
    _origin: int = 0
    _started: bool = False

    def push(self, start: int, block: FloatArray) -> list[tuple[int, FloatArray]]:
        if not self._started:
            self._origin, self._started = start, True
        self._buffer = block if self._buffer.size == 0 else np.concatenate([self._buffer, block])
        out = []
        while self._buffer.size >= self.size:
            out.append((self._origin, self._buffer[: self.size].copy()))
            self._buffer = self._buffer[self.size :]
            self._origin += self.size
        return out

    @property
    def leftover(self) -> int:
        """Samples held back because they do not fill a window."""
        return int(self._buffer.size)


def rechunk(
    blocks: Iterator[tuple[int, FloatArray]], size: int
) -> Iterator[tuple[int, FloatArray]]:
    """Re-cut a stream of blocks into whole windows of `size` (a short tail is dropped)."""
    windower = Windower(size)
    for start, block in blocks:
        yield from windower.push(start, block)


def recover_timing(
    x: FloatArray, sps_nominal: float, window_symbols: int = DEFAULT_WINDOW_SYMBOLS
) -> TimingModel:
    """Convenience for an in-memory record (tests, short captures)."""
    tracker = TimingTracker(sps_nominal, window_symbols)
    size = tracker.window_samples
    for start in range(0, x.size - size + 1, size):
        tracker.add_window(start, x[start : start + size])
    return tracker.finish(x.size)
