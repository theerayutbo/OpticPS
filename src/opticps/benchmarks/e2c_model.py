"""Static receiver-side law model of the E2c power study (design D1, D9; study plan I1 to I6).

Hypothesis H2 (formed after the 2 km result, design D15 c): a static memoryless law acts on the
whole received photocurrent before the receiver noise,

    y = f(A (s_D(t) + n_opt)) + n_rx,

with s_D the noiseless R13 pulse train (B2B Welch pulse spectrum, TX levels p_TX, small-signal
dispersion D over L km), A the received amplitude (1 at B2B, 0.832 at 2 km), n_opt optical noise
that crosses the fibre and scales with A, n_rx receiver noise added after the law, and f a
polynomial `v + b v^2 + a v^3` or a tanh law (plan I1), in units of one R13 pulse-level gap (plan
I2).

The pulse train is `e2_model.synthesize(sigma=0)` unchanged; this module adds only the law, its
inverse and its two noises. Nothing here reads a capture: the fit takes window summaries."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from opticps.benchmarks import e2_model
from opticps.benchmarks.e2_metrics import WindowSummary, metrics_between
from opticps.benchmarks.e2_score import window_summary
from opticps.benchmarks.provenance import BenchmarkError

FloatArray = NDArray[np.float64]

LAW_KINDS = ("poly", "tanh")
PROFILES = ("poly_b0", "poly_a0", "poly", "tanh")  # "poly" (a and b free) is the model of record
INVERSE_ITERATIONS = 60
INVERSE_TOLERANCE = 1e-9
FIT_SAMPLES = 1 << 20
FIT_MAXFEV = 600
FIT_XATOL = 1e-4
FIT_FATOL = 1e-6
FIT_RESTARTS = 3  # plan amendment A1: restarts from the best point with a fresh simplex
FIT_RESTART_GAIN = 1e-4  # stop restarting when a run improves the objective by less
PENALTY = 1e9
NOISE_STREAM_OPT = 1
NOISE_STREAM_RX = 2
OUTER = 1.5  # the outer TX levels in units of g_ref before centring (plan I2)


@dataclass(frozen=True)
class Law:
    """A static memoryless law with f(0) = 0 and f'(0) = 1 (plan I1)."""

    kind: str
    p1: float  # poly: a (cubic); tanh: k (curvature, used as |k|)
    p2: float  # poly: b (quadratic); tanh: o (offset)

    def __post_init__(self) -> None:
        if self.kind not in LAW_KINDS:
            raise BenchmarkError(f"law kind {self.kind!r} is not one of {LAW_KINDS}")
        if not (math.isfinite(self.p1) and math.isfinite(self.p2)):
            raise BenchmarkError("law parameters must be finite")

    @property
    def identity(self) -> bool:
        return self.p1 == 0.0 and (self.kind == "tanh" or self.p2 == 0.0)

    def apply(self, v: FloatArray) -> FloatArray:
        v = np.asarray(v, dtype=np.float64)
        if self.kind == "poly":
            a, b = self.p1, self.p2
            return np.asarray(v + b * v * v + a * v * v * v, dtype=np.float64)
        k, o = abs(self.p1), self.p2
        if k == 0.0:
            return v.copy()
        t0 = math.tanh(o)
        return np.asarray((np.tanh(k * v + o) - t0) / (k * (1.0 - t0 * t0)), dtype=np.float64)

    def derivative(self, v: FloatArray) -> FloatArray:
        v = np.asarray(v, dtype=np.float64)
        if self.kind == "poly":
            a, b = self.p1, self.p2
            return np.asarray(1.0 + 2.0 * b * v + 3.0 * a * v * v, dtype=np.float64)
        k, o = abs(self.p1), self.p2
        if k == 0.0:
            return np.ones_like(v)
        t0 = math.tanh(o)
        t = np.tanh(k * v + o)
        return np.asarray((1.0 - t * t) / (1.0 - t0 * t0), dtype=np.float64)

    def monotone_on(self, v: FloatArray) -> bool:
        """f' > 0 on every given sample (and finite)."""
        d = self.derivative(v)
        return bool(np.isfinite(d).all() and (d > 0.0).all())

    def checked_apply(self, v: FloatArray) -> FloatArray:
        if not self.monotone_on(v):
            raise BenchmarkError(
                f"the {self.kind} law is not monotone on the samples it is applied to"
            )
        return self.apply(v)

    def inverse(self, x: FloatArray) -> FloatArray:
        """u with f(u) = x by Newton from u = x; refused unless the residual is below 1e-9."""
        x = np.asarray(x, dtype=np.float64)
        if self.identity:
            return x.copy()
        u = x.copy()
        for _ in range(INVERSE_ITERATIONS):
            d = self.derivative(u)
            if not (np.isfinite(d).all() and (d > 0.0).all()):
                raise BenchmarkError("law inverse: the law is not monotone where it is inverted")
            step = (self.apply(u) - x) / d
            u = u - step
            if float(np.max(np.abs(step))) < 1e-13:
                break
        residual = float(np.max(np.abs(self.apply(u) - x)))
        if not residual <= INVERSE_TOLERANCE or not self.monotone_on(u):
            raise BenchmarkError(f"law inverse did not converge (residual {residual:.3g})")
        return np.asarray(u, dtype=np.float64)

    def scaled(self, factor: float) -> Law:
        """The polynomial with a and b times `factor` (truth family T4)."""
        if self.kind != "poly":
            raise BenchmarkError("only the polynomial law is scaled")
        return Law("poly", self.p1 * factor, self.p2 * factor)

    def as_dict(self) -> dict[str, Any]:
        names = ("a", "b") if self.kind == "poly" else ("k", "o")
        return {"kind": self.kind, names[0]: float(self.p1), names[1]: float(self.p2)}


IDENTITY = Law("poly", 0.0, 0.0)


def law_from_dict(document: Mapping[str, Any]) -> Law:
    kind = document["kind"]
    if kind == "poly":
        return Law("poly", float(document["a"]), float(document["b"]))
    return Law("tanh", float(document["k"]), float(document["o"]))


def g_ref_of(levels: Sequence[float]) -> float:
    """The gap unit of plan I2: (L4 - L1) / 3 of the R13 pulse levels."""
    values = np.asarray(levels, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all() or not values[3] > values[0]:
        raise BenchmarkError("four finite ascending levels are needed for the gap unit")
    return float((values[3] - values[0]) / 3.0)


def tx_levels(q1: float, q2: float, g_ref: float) -> FloatArray:
    """p_TX = g_ref * centre([-1.5, q1, q2, 1.5]) (plan I2)."""
    q = np.array([-OUTER, q1, q2, OUTER], dtype=np.float64)
    return np.asarray(g_ref * (q - q.mean()), dtype=np.float64)


def q_of(levels: Sequence[float]) -> tuple[float, float]:
    """The inner levels q1, q2 of four levels mapped to [-1.5, q1, q2, 1.5]."""
    values = np.asarray(levels, dtype=np.float64)
    q = (values - values[0]) / (values[3] - values[0]) * (2 * OUTER) - OUTER
    return float(q[1]), float(q[2])


def derived_seed(seed: int, stream: int) -> int:
    """An integer seed for stream `stream` of the declared seed (plan I3)."""
    state = np.random.SeedSequence([int(seed), int(stream)]).generate_state(1, dtype=np.uint64)
    return int(state[0])


@dataclass(frozen=True)
class Synthesis:
    """Everything one synthetic window depends on besides the base model (spectrum, rates)."""

    levels: tuple[float, float, float, float]
    law: Law
    sigma_opt: float
    sigma_rx: float
    amplitude: float
    dispersion_ps_nm_km: float = 0.0
    length_km: float = 0.0

    def __post_init__(self) -> None:
        for name in ("sigma_opt", "sigma_rx", "amplitude"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value >= 0.0):
                raise BenchmarkError(f"{name} must be finite and not negative")
        if not self.amplitude > 0.0:
            raise BenchmarkError("the amplitude must be positive")


def synthesize(
    base: Mapping[str, Any],
    spec: Synthesis,
    *,
    n_samples: int,
    symbol_seed: int,
    noise_seed: int,
) -> FloatArray:
    """y = f(A (s_D + n_opt)) + n_rx (plan I3). `base` gives the pulse spectrum and rates."""
    clean = e2_model.synthesize(
        base,
        n_samples=n_samples,
        symbol_seed=symbol_seed,
        noise_seed=noise_seed,
        dispersion_ps_nm_km=spec.dispersion_ps_nm_km,
        length_km=spec.length_km,
        levels=list(spec.levels),
        sigma=0.0,
    )
    fs = float(base["sample_rate_hz"])
    psd = base["psd_relative"]
    v = clean
    if spec.sigma_opt > 0.0:
        n_opt = e2_model.shaped_noise(
            psd, fs, n_samples, spec.sigma_opt, derived_seed(noise_seed, NOISE_STREAM_OPT)
        )
        if spec.dispersion_ps_nm_km != 0.0 and spec.length_km != 0.0:
            response = e2_model.dispersion_response(
                np.fft.rfftfreq(n_samples, 1.0 / fs), spec.dispersion_ps_nm_km, spec.length_km
            )
            n_opt = np.fft.irfft(np.fft.rfft(n_opt) * response, n_samples)
        v = clean + n_opt
    y = spec.law.checked_apply(spec.amplitude * v)
    if spec.sigma_rx > 0.0:
        y = y + e2_model.shaped_noise(
            psd, fs, n_samples, spec.sigma_rx, derived_seed(noise_seed, NOISE_STREAM_RX)
        )
    if not np.isfinite(y).all():
        raise BenchmarkError("the synthetic waveform is not finite")
    return np.asarray(y, dtype=np.float64)


def objective(reference: WindowSummary, predicted: WindowSummary) -> float:
    """The R13 training loss M1 + M2 + M3 + 0.05 M4 (plan I5)."""
    m = metrics_between(reference, predicted)
    return (
        m["M1_level_spacing"]
        + m["M2_wasserstein1_amplitude"]
        + m["M3_quantile_error"]
        + 0.05 * m["M4_log_spectral_distance"]
    )


def profile_names(profile: str) -> tuple[str, ...]:
    """The free parameters of a fit profile, in vector order."""
    table = {
        "poly_b0": ("q1", "q2", "a", "sigma_rx", "sigma_opt"),
        "poly_a0": ("q1", "q2", "b", "sigma_rx", "sigma_opt"),
        "poly": ("q1", "q2", "a", "b", "sigma_rx", "sigma_opt"),
        "tanh": ("q1", "q2", "k", "o", "sigma_rx", "sigma_opt"),
    }
    if profile not in table:
        raise BenchmarkError(f"profile {profile!r} is not one of {PROFILES}")
    return table[profile]


START_STEP = {"q1": 0.02, "q2": 0.02, "a": 0.01, "b": 0.01, "k": 0.1, "o": 0.05}
SIGMA_STEP = 0.03


def unpack(profile: str, vector: Sequence[float] | FloatArray) -> dict[str, float]:
    values = dict(zip(profile_names(profile), (float(v) for v in vector), strict=True))
    values["sigma_rx"] = abs(values["sigma_rx"])
    values["sigma_opt"] = abs(values["sigma_opt"])
    return values


def law_of(profile: str, values: Mapping[str, float]) -> Law:
    if profile == "tanh":
        return Law("tanh", abs(values["k"]), values["o"])
    return Law("poly", values.get("a", 0.0), values.get("b", 0.0))


@dataclass(frozen=True)
class FitTarget:
    """One fit window: its gain-invariant summary and the amplitude the model gives it."""

    summary: WindowSummary
    amplitude: float
    label: str


def fit_law(
    base: Mapping[str, Any],
    targets: Sequence[FitTarget],
    *,
    profile: str,
    start: Mapping[str, float],
    fit_seed: int,
    fit_samples: int = FIT_SAMPLES,
    maxfev: int = FIT_MAXFEV,
    restarts: int = FIT_RESTARTS,
) -> dict[str, Any]:
    """Joint Nelder-Mead on the targets (plan I5, amendment A1). Reads no capture; deterministic.

    One run of at most `maxfev` evaluations from `start`, then up to `restarts` runs, each from the
    best point so far with a fresh initial simplex (the same steps), until a run improves the
    objective by less than `FIT_RESTART_GAIN`.
    """
    if not targets:
        raise BenchmarkError("the joint fit needs at least one target window")
    names = profile_names(profile)
    g_ref = g_ref_of(base["pulse_levels"])
    fs, baud = float(base["sample_rate_hz"]), float(base["baud_bd"])
    evaluations = {"count": 0}

    def loss(vector: FloatArray) -> float:
        evaluations["count"] += 1
        values = unpack(profile, vector)
        law = law_of(profile, values)
        levels = tx_levels(values["q1"], values["q2"], g_ref)
        if not (np.diff(levels) > 0).all():
            return PENALTY
        total = 0.0
        for target in targets:
            spec = Synthesis(
                tuple(float(v) for v in levels),  # type: ignore[arg-type]
                law,
                values["sigma_opt"],
                values["sigma_rx"],
                target.amplitude,
            )
            try:
                y = synthesize(
                    base, spec, n_samples=fit_samples, symbol_seed=fit_seed, noise_seed=fit_seed
                )
                total += objective(target.summary, window_summary(y, fs, baud))
            except BenchmarkError:
                return PENALTY
        return total if math.isfinite(total) else PENALTY

    def run(x0: FloatArray) -> Any:
        simplex = [x0]
        for i, name in enumerate(names):
            vertex = x0.copy()
            vertex[i] += SIGMA_STEP if name.startswith("sigma") else START_STEP[name]
            simplex.append(vertex)
        return minimize(
            loss,
            x0,
            method="Nelder-Mead",
            options={
                "xatol": FIT_XATOL,
                "fatol": FIT_FATOL,
                "maxfev": maxfev,
                "initial_simplex": np.array(simplex),
            },
        )

    result = run(np.array([float(start[n]) for n in names], dtype=np.float64))
    history = [float(result.fun)]
    for _ in range(restarts):
        again = run(np.asarray(result.x, dtype=np.float64))
        gain = float(result.fun) - float(again.fun)
        if gain > 0:
            result = again
        history.append(float(again.fun))
        if gain < FIT_RESTART_GAIN:
            break
    values = unpack(profile, result.x)
    law = law_of(profile, values)
    levels = tx_levels(values["q1"], values["q2"], g_ref)
    return {
        "profile": profile,
        "law": law.as_dict(),
        "q": [values["q1"], values["q2"]],
        "tx_levels": [float(v) for v in levels],
        "g_ref": g_ref,
        "sigma_rx": values["sigma_rx"],
        "sigma_opt": values["sigma_opt"],
        "objective": float(result.fun),
        "evaluations": int(evaluations["count"]),
        "converged": bool(result.success),
        "message": str(result.message),
        "start": {n: float(start[n]) for n in names},
        "targets": [{"label": t.label, "amplitude": t.amplitude} for t in targets],
        "fit_seed": int(fit_seed),
        "fit_samples": int(fit_samples),
        "maxfev": int(maxfev),
        "run_objectives": history,
    }


def bound_sigmas(sigma_opt: float, sigma_rx: float, bound: str) -> tuple[float, float]:
    """(sigma_opt, sigma_rx) of a noise bound (plan I4): RX keeps the split, OPT all optical."""
    if bound == "RX":
        return sigma_opt, sigma_rx
    if bound == "OPT":
        return math.hypot(sigma_opt, sigma_rx), 0.0
    raise BenchmarkError(f"noise bound {bound!r} is not RX or OPT")


def control_sigmas(sigma_c: float, phi: float, bound: str) -> tuple[float, float]:
    """(sigma_opt, sigma_rx) of a control (plan I7): its noise split as the law's fraction phi."""
    if not (0.0 <= phi <= 1.0):
        raise BenchmarkError("the optical noise fraction must lie in [0, 1]")
    if bound == "RX":
        return sigma_c * math.sqrt(phi), sigma_c * math.sqrt(1.0 - phi)
    if bound == "OPT":
        return sigma_c, 0.0
    raise BenchmarkError(f"noise bound {bound!r} is not RX or OPT")
