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
PROFILES_A2 = ("identity", "poly_b0", "poly_a0", "tanh", "poly")  # amendment A2.1, in fit order
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
        "identity": ("q1", "q2", "sigma_rx", "sigma_opt"),  # the identity-law base (A2.1)
        "poly_b0": ("q1", "q2", "a", "sigma_rx", "sigma_opt"),
        "poly_a0": ("q1", "q2", "b", "sigma_rx", "sigma_opt"),
        "poly": ("q1", "q2", "a", "b", "sigma_rx", "sigma_opt"),
        "tanh": ("q1", "q2", "k", "o", "sigma_rx", "sigma_opt"),
    }
    if profile not in table:
        raise BenchmarkError(f"profile {profile!r} is not one of {PROFILES_A2}")
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


def make_loss(
    base: Mapping[str, Any],
    targets: Sequence[FitTarget],
    *,
    profile: str,
    fit_seed: int,
    fit_samples: int = FIT_SAMPLES,
) -> Any:
    """The joint objective of plan I5 as a function of a profile's parameter vector."""
    if not targets:
        raise BenchmarkError("the joint fit needs at least one target window")
    profile_names(profile)
    g_ref = g_ref_of(base["pulse_levels"])
    fs, baud = float(base["sample_rate_hz"]), float(base["baud_bd"])

    def loss(vector: FloatArray) -> float:
        loss.count += 1  # type: ignore[attr-defined]
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

    loss.count = 0  # type: ignore[attr-defined]
    return loss


def nelder_mead(
    loss: Any,
    x0: FloatArray,
    names: Sequence[str],
    *,
    maxfev: int,
    steps: Mapping[str, float] | None = None,
) -> Any:
    """One Nelder-Mead run from `x0` with a fresh initial simplex of the given steps (plan I5)."""
    table = START_STEP if steps is None else steps
    simplex = [x0]
    for i, name in enumerate(names):
        vertex = x0.copy()
        vertex[i] += SIGMA_STEP if name.startswith("sigma") else table[name]
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
    objective by less than `FIT_RESTART_GAIN`. Superseded for the study by `fit_profile_a2` (A2).
    """
    names = profile_names(profile)
    g_ref = g_ref_of(base["pulse_levels"])
    loss = make_loss(base, targets, profile=profile, fit_seed=fit_seed, fit_samples=fit_samples)

    def run(x0: FloatArray) -> Any:
        return nelder_mead(loss, x0, names, maxfev=maxfev)

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
        "evaluations": int(loss.count),
        "converged": bool(result.success),
        "message": str(result.message),
        "start": {n: float(start[n]) for n in names},
        "targets": [{"label": t.label, "amplitude": t.amplitude} for t in targets],
        "fit_seed": int(fit_seed),
        "fit_samples": int(fit_samples),
        "maxfev": int(maxfev),
        "run_objectives": history,
    }


# ---------------------------------------------------------------------------- amendment A2
A2_STEPS = {**START_STEP, "a": 0.02, "b": 0.03}  # A2.3; sigma steps stay SIGMA_STEP
A2_SCREEN_MAXFEV = 200  # A2.4
A2_FULL_MAXFEV = FIT_MAXFEV  # A2.4 and A2.6: the A1 runs, maxfev 600
A2_KEEP = 2  # A2.4: the best two screened starts of a profile get the full A1 sequence
A2_GRID_A = (-0.03, 0.0, 0.03)  # A2.2, set by the D4 scale
A2_GRID_B = (-0.05, 0.0, 0.05)
A2_GRID_O = (-0.4, 0.0, 0.4)
A2_TANH_K = 0.1
A2_NESTED_TOL = 1e-6  # AC1
A2_STATIONARY_GAIN = 1e-4  # AC3
A2_BASIN_TOL = 1e-3  # AC4, objective units
A2_BASIN_MIN_STARTS = 2  # AC4
MODEL_OF_RECORD = "poly"
NESTED = ("poly_b0", "poly_a0")


def a2_starts(
    profile: str,
    common: Mapping[str, float],
    nested: Mapping[str, Mapping[str, float]] | None = None,
) -> list[dict[str, float]]:
    """The deterministic A2.2 start list of a profile; `common` holds the I5 q and sigma starts.

    `nested` (poly only) holds the A2 optima of poly_b0 and poly_a0 of the same run, as values."""
    base = {k: float(common[k]) for k in ("q1", "q2", "sigma_rx", "sigma_opt")}
    if profile == "identity":
        return [dict(base)]
    if profile == "poly_b0":
        return [{**base, "a": a} for a in A2_GRID_A]
    if profile == "poly_a0":
        return [{**base, "b": b} for b in A2_GRID_B]
    if profile == "tanh":
        return [{**base, "k": A2_TANH_K, "o": o} for o in A2_GRID_O]
    if profile == "poly":
        if nested is None or set(nested) != set(NESTED):
            raise BenchmarkError("the poly starts need the A2 optima of poly_b0 and poly_a0")
        grid = [{**base, "a": a, "b": b} for a in A2_GRID_A for b in A2_GRID_B]
        b0 = {n: float(nested["poly_b0"][n]) for n in profile_names("poly_b0")}
        a0 = {n: float(nested["poly_a0"][n]) for n in profile_names("poly_a0")}
        return [*grid, {**b0, "b": 0.0}, {**a0, "a": 0.0}]
    raise BenchmarkError(f"profile {profile!r} is not one of {PROFILES_A2}")


def _record(kind: str, start: int, result: Any, profile: str, evaluations: int) -> dict[str, Any]:
    values = unpack(profile, result.x)
    return {
        "kind": kind,
        "start": int(start),
        "objective": float(result.fun),
        "x": {n: float(values[n]) for n in profile_names(profile)},
        "evaluations": int(evaluations),
    }


def a2_job(
    job: tuple[
        str, Mapping[str, Any], Sequence[FitTarget], str, int, Mapping[str, float], int, int
    ],
) -> list[dict[str, Any]]:
    """One A2 job: `screen` (A2.4), `full` (the A1 sequence, A2.4) or `stationarity` (A2.6).

    Top level so a process pool can run it; deterministic for given inputs."""
    kind, base, targets, profile, start, x, fit_seed, fit_samples = job
    names = profile_names(profile)
    loss = make_loss(base, targets, profile=profile, fit_seed=fit_seed, fit_samples=fit_samples)
    x0 = np.array([float(x[n]) for n in names], dtype=np.float64)

    def run(point: FloatArray, maxfev: int) -> Any:
        before = loss.count
        result = nelder_mead(loss, point, names, maxfev=maxfev, steps=A2_STEPS)
        result.evaluations_used = loss.count - before
        return result

    if kind == "screen":
        result = run(x0, A2_SCREEN_MAXFEV)
        return [_record("screen", start, result, profile, result.evaluations_used)]
    if kind == "stationarity":
        result = run(x0, A2_FULL_MAXFEV)
        return [_record("stationarity", start, result, profile, result.evaluations_used)]
    if kind != "full":
        raise BenchmarkError(f"A2 job kind {kind!r} is not screen, full or stationarity")
    best = run(x0, A2_FULL_MAXFEV)
    records = [_record("full", start, best, profile, best.evaluations_used)]
    for _ in range(FIT_RESTARTS):
        again = run(np.asarray(best.x, dtype=np.float64), A2_FULL_MAXFEV)
        records.append(_record("restart", start, again, profile, again.evaluations_used))
        gain = float(best.fun) - float(again.fun)
        if gain > 0:
            best = again
        if gain < FIT_RESTART_GAIN:
            break
    return records


def a2_select(screens: Sequence[Mapping[str, Any]], keep: int = A2_KEEP) -> list[int]:
    """The starts that get the full A1 sequence: lowest screened objective, ties by position."""
    ranked = sorted(screens, key=lambda r: (float(r["objective"]), int(r["start"])))
    return [int(r["start"]) for r in ranked[:keep]]


def a2_optimum(runs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The lowest objective over every screen, full run and restart (A2.5); ties: the first."""
    if not runs:
        raise BenchmarkError("a profile without runs has no optimum")
    best = runs[0]
    for record in runs[1:]:
        if float(record["objective"]) < float(best["objective"]):
            best = record
    return best


def a2_profile_document(
    profile: str,
    base: Mapping[str, Any],
    targets: Sequence[FitTarget],
    starts: Sequence[Mapping[str, float]],
    runs: Sequence[Mapping[str, Any]],
    *,
    fit_seed: int,
    fit_samples: int,
) -> dict[str, Any]:
    """A fitted profile in the v1 layout (law, levels, sigmas, objective) plus its A2 record."""
    best = a2_optimum(runs)
    values = {**best["x"]}
    law = law_of(profile, values)
    g_ref = g_ref_of(base["pulse_levels"])
    levels = tx_levels(values["q1"], values["q2"], g_ref)
    stationarity = [r for r in runs if r["kind"] == "stationarity"]
    document: dict[str, Any] = {
        "profile": profile,
        "law": law.as_dict(),
        "q": [values["q1"], values["q2"]],
        "tx_levels": [float(v) for v in levels],
        "g_ref": g_ref,
        "sigma_rx": values["sigma_rx"],
        "sigma_opt": values["sigma_opt"],
        "objective": float(best["objective"]),
        "optimum_start": int(best["start"]),
        "optimum_run_kind": str(best["kind"]),
        "evaluations": int(sum(int(r["evaluations"]) for r in runs)),
        "targets": [{"label": t.label, "amplitude": t.amplitude} for t in targets],
        "fit_seed": int(fit_seed),
        "fit_samples": int(fit_samples),
        "a2": {
            "starts": [dict(s) for s in starts],
            "selected_for_full": sorted({int(r["start"]) for r in runs if r["kind"] == "full"}),
            "runs": [dict(r) for r in runs],
        },
    }
    if stationarity:
        before = [r for r in runs if r["kind"] != "stationarity"]
        document["a2"]["stationarity"] = {
            "objective_before": float(a2_optimum(before)["objective"]),
            "objective_after": float(stationarity[-1]["objective"]),
            "gain": float(a2_optimum(before)["objective"]) - float(stationarity[-1]["objective"]),
        }
    return document


def fit_profiles_a2(
    base: Mapping[str, Any],
    targets: Sequence[FitTarget],
    starts_by_profile: Mapping[str, Sequence[Mapping[str, float]]],
    *,
    fit_seed: int,
    fit_samples: int = FIT_SAMPLES,
    stationarity_for: Sequence[str] = (),
    map_fn: Any = map,
) -> dict[str, dict[str, Any]]:
    """A2.4 to A2.6 for several profiles at once; `map_fn` may be a process pool's map."""

    def jobs(kind: str, items: Sequence[tuple[str, int, Mapping[str, float]]]) -> list[Any]:
        return [(kind, base, targets, p, i, x, fit_seed, fit_samples) for p, i, x in items]

    runs: dict[str, list[dict[str, Any]]] = {p: [] for p in starts_by_profile}
    screen_items = [
        (p, i, s) for p, starts in starts_by_profile.items() for i, s in enumerate(starts)
    ]
    for (profile, _, _), out in zip(
        screen_items, map_fn(a2_job, jobs("screen", screen_items)), strict=True
    ):
        runs[profile].extend(out)
    full_items = []
    for profile in starts_by_profile:
        screens = {r["start"]: r for r in runs[profile] if r["kind"] == "screen"}
        for i in a2_select(list(screens.values())):
            full_items.append((profile, i, screens[i]["x"]))
    for (profile, _, _), out in zip(
        full_items, map_fn(a2_job, jobs("full", full_items)), strict=True
    ):
        runs[profile].extend(out)
    still = []
    for profile in stationarity_for:
        best = a2_optimum(runs[profile])
        still.append((profile, int(best["start"]), best["x"]))
    for (profile, _, _), out in zip(
        still, map_fn(a2_job, jobs("stationarity", still)), strict=True
    ):
        runs[profile].extend(out)
    return {
        p: a2_profile_document(
            p,
            base,
            targets,
            starts_by_profile[p],
            runs[p],
            fit_seed=fit_seed,
            fit_samples=fit_samples,
        )
        for p in starts_by_profile
    }


def require_nested(objectives: Mapping[str, float], tol: float = A2_NESTED_TOL) -> None:
    """The permanent invariant: a full-model poly result is never worse than a nested profile."""
    poly = float(objectives[MODEL_OF_RECORD])
    for name in NESTED:
        if name in objectives and poly > float(objectives[name]) + tol:
            raise BenchmarkError(
                f"the full poly objective {poly:.6g} is above the nested {name} objective "
                f"{float(objectives[name]):.6g}: not an optimum, refused"
            )


def a2_acceptance(profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The result-blind acceptance checks AC1 to AC4 of amendment A2; any failure: fit INVALID."""
    obj = {p: float(profiles[p]["objective"]) for p in PROFILES_A2}
    nested_min = min(obj["poly_b0"], obj["poly_a0"])
    ac1_lines = {
        "poly <= min(poly_b0, poly_a0)": obj["poly"] <= nested_min + A2_NESTED_TOL,
        "min(poly_b0, poly_a0) <= identity": nested_min <= obj["identity"] + A2_NESTED_TOL,
        "tanh <= identity": obj["tanh"] <= obj["identity"] + A2_NESTED_TOL,
    }
    ac2_lines: dict[str, dict[str, Any]] = {}
    for p in PROFILES_A2:
        lowest = min(float(r["objective"]) for r in profiles[p]["a2"]["runs"])
        ac2_lines[p] = {"reported": obj[p], "lowest_run": lowest, "holds": obj[p] == lowest}
    record = profiles[MODEL_OF_RECORD]["a2"]
    stationarity = record.get("stationarity")
    gain = None if stationarity is None else float(stationarity["gain"])
    ends: dict[int, float] = {}
    for r in record["runs"]:
        i = int(r["start"])
        ends[i] = min(ends.get(i, math.inf), float(r["objective"]))
    agreeing = sorted(i for i, e in ends.items() if e <= obj[MODEL_OF_RECORD] + A2_BASIN_TOL)
    checks: dict[str, dict[str, Any]] = {
        "AC1_nested": {
            "objectives": obj,
            "tolerance": A2_NESTED_TOL,
            "lines": ac1_lines,
            "holds": all(ac1_lines.values()),
        },
        "AC2_best_of_all_starts": {
            "profiles": ac2_lines,
            "holds": all(v["holds"] for v in ac2_lines.values()),
        },
        "AC3_stationarity": {
            "gain": gain,
            "threshold": A2_STATIONARY_GAIN,
            "holds": gain is not None and gain < A2_STATIONARY_GAIN,
        },
        "AC4_two_basin_agreement": {
            "tolerance": A2_BASIN_TOL,
            "start_ends": {str(i): e for i, e in sorted(ends.items())},
            "agreeing_starts": agreeing,
            "agreeing_end_points": {
                str(i): min(
                    (r for r in record["runs"] if int(r["start"]) == i),
                    key=lambda r: float(r["objective"]),
                )["x"]
                for i in agreeing
            },
            "minimum_starts": A2_BASIN_MIN_STARTS,
            "holds": len(agreeing) >= A2_BASIN_MIN_STARTS,
        },
    }
    valid = all(c["holds"] for c in checks.values())
    return {
        "checks": checks,
        "valid": valid,
        "status": "VALID" if valid else "FIT_INVALID, S2 not evaluable",
        "failed": [k for k, c in checks.items() if not c["holds"]],
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
