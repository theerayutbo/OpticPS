"""Decision feedback equaliser (DFE) with exponentially weighted recursive least squares (RLS).

Clean room: derived here from the normal equations, with no simulator code consulted. The theory is
textbook (see `docs/ALGORITHM_PROVENANCE.md`).

Model. At symbol n the equaliser output is y(n) = w^T u(n), with the regressor

    u(n) = [ x(n s + 0 - c), ..., x(n s + (F - 1) - c) | a(n-1), ..., a(n-B) ]

where x is the received waveform at s samples per symbol (s = 2 for a T/2-spaced equaliser), F the
number of feed-forward taps, c the cursor (index of the main tap), and a(n-k) the past symbol
decisions fed back (B taps). With B = 0 the equaliser is a plain feed-forward equaliser (FFE).

Cost. J(n) = sum_i lambda^(n-i) |d(i) - w^T u(i)|^2, with forgetting factor lambda in (0, 1] and d
the desired symbol (known during training, the slicer decision afterwards). Setting dJ/dw = 0 gives
the normal equations Phi(n) w(n) = theta(n) with

    Phi(n) = lambda Phi(n-1) + u(n) u(n)^T,    theta(n) = lambda theta(n-1) + d(n) u(n).

With P(n) = Phi(n)^-1 the matrix inversion lemma (Woodbury) turns the rank-one update of Phi into

    pi(n) = P(n-1) u(n),    den = lambda + u(n)^T pi(n),    k(n) = pi(n) / den,
    xi(n) = d(n) - w(n-1)^T u(n)     (a priori error),
    w(n)  = w(n-1) + k(n) xi(n),
    P(n)  = ( P(n-1) - pi(n) pi(n)^T / den ) / lambda.

Numerical care. P(n-1) is symmetric, so the outer product pi pi^T is exactly symmetric in floating
point (a product of two numbers is commutative) and P stays exactly symmetric; the textbook form
k u^T P loses symmetry by rounding. P is also symmetrised explicitly every `symmetrize_every`
symbols (a no-op while the update keeps it exact, a guard if the form is ever changed). With
lambda < 1 and no excitation P grows like lambda^-n and overflows, so trace(P) is capped
(`p_trace_cap`; a scaled P stays symmetric and positive definite). The cap does not act while every
direction of the regressor carries some energy. It does act when part of the regressor space is
empty, which is the case for a band-limited T/2 input (nothing between 0.55 and 1 cycle per symbol
after an SRRC matched filter): trace(P) is then held at the cap by the empty directions and the
equaliser behaves as a constant-trace RLS, with an effectively unit forgetting factor in the
excited subspace. `DfeResult.n_trace_caps` reports how often it acted. A Cholesky factorisation
of P every `health_check_every` symbols raises `RlsInstabilityError` if P is no longer positive
definite or any value is not finite: the run fails closed instead of returning a wrong BER.

Deterministic: no random numbers, double precision NumPy only, no fixed point.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class RlsInstabilityError(ArithmeticError):
    """The inverse correlation matrix lost positive definiteness or a value is not finite."""


@dataclass(frozen=True)
class RlsDfeConfig:
    """Equaliser settings. Defaults are the (17, 7) T/2 DFE of the NANF benchmark (plan F6)."""

    ff_taps: int = 17
    fb_taps: int = 7
    samples_per_symbol: int = 2
    cursor: int | None = None  # index of the main feed-forward tap; None: ff_taps // 2
    forgetting: float = 0.998
    delta: float = 1e-2  # P(0) = I / delta
    training_symbols: int = 8192
    levels: tuple[float, ...] = (-3.0, -1.0, 1.0, 3.0)
    decision_directed: bool = True  # False: adaptation stops after training
    p_trace_cap: float = 1e4
    symmetrize_every: int = 64
    health_check_every: int = 4096

    def __post_init__(self) -> None:
        if self.ff_taps < 1 or self.fb_taps < 0 or self.samples_per_symbol < 1:
            raise ValueError(
                "ff_taps and samples_per_symbol must be at least 1, fb_taps not negative"
            )
        if self.cursor is not None and not 0 <= self.cursor < self.ff_taps:
            raise ValueError("cursor must index a feed-forward tap")
        if not 0.0 < self.forgetting <= 1.0:
            raise ValueError("forgetting factor must be in (0, 1]")
        if not (math.isfinite(self.delta) and self.delta > 0):
            raise ValueError("delta must be finite and positive")
        if self.training_symbols < 0:
            raise ValueError("training_symbols must not be negative")
        steps = zip(self.levels, self.levels[1:], strict=False)
        if len(self.levels) < 2 or any(b <= a for a, b in steps):
            raise ValueError("levels must be at least two strictly increasing values")
        if not (math.isfinite(self.p_trace_cap) and self.p_trace_cap > 0):
            raise ValueError("p_trace_cap must be finite and positive")
        if self.symmetrize_every < 1 or self.health_check_every < 1:
            raise ValueError("symmetrize_every and health_check_every must be at least 1")

    @property
    def n_weights(self) -> int:
        return self.ff_taps + self.fb_taps

    @property
    def main_tap(self) -> int:
        return self.ff_taps // 2 if self.cursor is None else self.cursor

    @classmethod
    def ffe_only(cls, taps: int, samples_per_symbol: int = 1, **kwargs: Any) -> RlsDfeConfig:
        """A feed-forward-only RLS equaliser (no feedback taps), e.g. for symbol-spaced use."""
        return cls(ff_taps=taps, fb_taps=0, samples_per_symbol=samples_per_symbol, **kwargs)


@dataclass(frozen=True)
class DfeResult:
    """Equaliser output before the decision, the decisions and the final state."""

    output: FloatArray  # w^T u at every symbol (a priori, before the decision)
    decisions: FloatArray  # slicer levels
    decision_indices: IntArray  # index into config.levels
    weights: FloatArray
    p_matrix: FloatArray
    max_p_trace: float
    max_p_asymmetry: float
    n_trace_caps: int


def slicer_thresholds(levels: tuple[float, ...]) -> list[float]:
    """Mid-points between adjacent levels (for -3, -1, 1, 3: -2, 0, 2)."""
    return [0.5 * (a + b) for a, b in zip(levels, levels[1:], strict=False)]


def rls_equalize(
    samples: FloatArray, reference: FloatArray, config: RlsDfeConfig | None = None
) -> DfeResult:
    """Equalise one periodic capture. `samples` holds n_symbols * samples_per_symbol points.

    The capture is treated as periodic (indices wrap), which is how the NANF chain captures a
    looped waveform. `reference` gives the transmitted symbol levels; only the first
    `training_symbols` are used (as the desired signal and in the feedback taps), the rest is
    never read by the equaliser, so a caller may pass the full sequence for scoring.
    """
    cfg = RlsDfeConfig() if config is None else config
    x = np.asarray(samples, dtype=float)
    ref = np.asarray(reference, dtype=float)
    sps, nf, nb = cfg.samples_per_symbol, cfg.ff_taps, cfg.fb_taps
    if x.ndim != 1 or x.size == 0 or x.size % sps != 0:
        raise ValueError("samples must be a non-empty 1-D array of n_symbols * samples_per_symbol")
    if not np.all(np.isfinite(x)):
        raise ValueError("samples must be finite")
    n_sym = x.size // sps
    if cfg.training_symbols > n_sym or ref.size < cfg.training_symbols:
        raise ValueError("reference must cover the training symbols and the capture must hold them")
    if not np.all(np.isfinite(ref[: cfg.training_symbols])):
        raise ValueError("training reference must be finite")
    cursor = cfg.main_tap
    padded = x.take(np.arange(-cursor, x.size + nf - cursor), mode="wrap")
    m = cfg.n_weights
    lam = cfg.forgetting
    inv_lam = 1.0 / lam
    levels = list(cfg.levels)
    thresholds = slicer_thresholds(cfg.levels)
    train = cfg.training_symbols
    adapt = cfg.decision_directed

    p = np.eye(m) / cfg.delta
    w = np.zeros(m)
    u = np.zeros(m)
    out = np.empty(n_sym)
    dec_idx = np.empty(n_sym, dtype=np.int64)
    max_trace = float(np.trace(p))
    max_asym = 0.0
    n_caps = 0
    outer = np.outer
    dot = np.dot
    for n in range(n_sym):
        base = n * sps
        u[:nf] = padded[base : base + nf]
        pi = dot(p, u)
        den = lam + dot(u, pi)
        y = dot(w, u)
        out[n] = y
        idx = bisect_right(thresholds, y)
        dec_idx[n] = idx
        target = ref[n] if n < train else levels[idx]
        if n < train or adapt:
            if not den > 0.0 or not math.isfinite(den):
                raise RlsInstabilityError(
                    f"non-positive or non-finite RLS denominator at symbol {n}"
                )
            w += (target - y) / den * pi
            p -= outer(pi, pi) / den
            p *= inv_lam
            trace = float(p.trace())
            if trace > cfg.p_trace_cap:
                p *= cfg.p_trace_cap / trace
                trace = cfg.p_trace_cap
                n_caps += 1
            if trace > max_trace:
                max_trace = trace
            if (n + 1) % cfg.symmetrize_every == 0:
                asym = float(np.max(np.abs(p - p.T)))
                max_asym = max(max_asym, asym)
                p = 0.5 * (p + p.T)
            if (n + 1) % cfg.health_check_every == 0:
                _check_health(p, w, n)
        if nb:
            u[nf + 1 :] = u[nf:-1]
            u[nf] = target
    _check_health(p, w, n_sym - 1)
    decisions = np.asarray(levels)[dec_idx]
    return DfeResult(out, decisions, dec_idx, w, p, max_trace, max_asym, n_caps)


def _check_health(p: FloatArray, w: FloatArray, n: int) -> None:
    if not (np.all(np.isfinite(p)) and np.all(np.isfinite(w))):
        raise RlsInstabilityError(f"non-finite RLS state at symbol {n}")
    try:
        np.linalg.cholesky(0.5 * (p + p.T))
    except np.linalg.LinAlgError as err:
        raise RlsInstabilityError(f"P lost positive definiteness at symbol {n}") from err
