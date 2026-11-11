"""Tests of the E2c power study code (design D18): fixtures only, no capture is read.

Tests named `test_real_` read the committed repository (git history, the R13 freeze); the mutation
script deselects them, as `mutate_e2.py` does.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from opticps.benchmarks import (
    e2_metrics,
    e2_model,
    e2_score,
    e2c_calibration,
    e2c_model,
    e2c_study,
    holdout,
    teriphic,
)
from opticps.benchmarks.e2c_study import Cell
from opticps.benchmarks.provenance import BenchmarkError, Checksum

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_benchmark_external_capture import keysight_image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FS = 8e11
BAUD = 5e10
PSD = [math.exp(-(((k * FS / 4096) / 30e9) ** 2)) for k in range(2049)]
BASE = {
    "sample_rate_hz": FS, "baud_bd": BAUD, "pulse_samples": 1024, "psd_relative": PSD,
    "level_probabilities": [0.25] * 4, "pulse_levels": [-1.5, -0.5, 0.5, 1.5], "noise_sigma": 0.1,
}  # fmt: skip
N = 1 << 16
TWO_KM = e2c_calibration.TWO_KM_NAME
TEN_KM = e2c_calibration.TEN_KM_NAME


def load_script() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "power_study_e2c", ROOT / "scripts/power_study_e2c.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------- the law
LAWS = [e2c_model.Law("poly", -0.03, -0.02), e2c_model.Law("tanh", 0.25, -0.2)]


@pytest.mark.parametrize("law", LAWS, ids=["poly", "tanh"])
def test_the_law_is_identity_at_zero_and_monotone_on_the_fit_range(law):
    v = np.linspace(-3.0, 3.0, 2001)
    assert law.apply(np.array([0.0]))[0] == pytest.approx(0.0, abs=1e-15)
    assert law.derivative(np.array([0.0]))[0] == pytest.approx(1.0, abs=1e-12)
    assert law.monotone_on(v)
    assert np.all(np.diff(law.apply(v)) > 0)
    assert e2c_model.IDENTITY.apply(v) == pytest.approx(v)


def test_a_law_that_folds_over_is_refused_where_it_is_applied_or_inverted():
    folding = e2c_model.Law("poly", -0.5, 0.0)  # f' = 1 - 1.5 v^2 < 0 beyond |v| 0.82
    v = np.linspace(-2.0, 2.0, 101)
    assert not folding.monotone_on(v)
    with pytest.raises(BenchmarkError, match="not monotone"):
        folding.checked_apply(v)
    with pytest.raises(BenchmarkError):
        folding.inverse(np.array([0.0, 2.0]))
    with pytest.raises(BenchmarkError):
        e2c_model.Law("cubic", 0.0, 0.0)
    with pytest.raises(BenchmarkError):
        e2c_model.Law("poly", float("nan"), 0.0)


@pytest.mark.parametrize("law", LAWS, ids=["poly", "tanh"])
def test_the_inverse_recovers_the_input(law):
    u = np.random.default_rng(3).normal(0.0, 1.2, 50_000).clip(-3.0, 3.0)  # monotone range
    assert np.max(np.abs(law.inverse(law.apply(u)) - u)) < 1e-9


def test_synthesis_applies_the_law_to_the_whole_received_waveform_before_receiver_noise():
    levels = tuple(e2c_model.tx_levels(-0.45, 0.55, 1.0))
    law = e2c_model.Law("poly", -0.04, -0.03)
    plain = e2c_model.Synthesis(levels, e2c_model.IDENTITY, 0.0, 0.0, 0.7)
    bent = dataclasses.replace(plain, law=law)
    kw = {"n_samples": N, "symbol_seed": 1, "noise_seed": 2}
    linear = e2c_model.synthesize(BASE, plain, **kw)
    assert e2c_model.synthesize(BASE, bent, **kw) == pytest.approx(law.apply(linear), abs=1e-12)
    rx = e2c_model.synthesize(BASE, dataclasses.replace(bent, sigma_rx=0.1), **kw)
    assert np.std(rx - law.apply(linear)) == pytest.approx(0.1, rel=1e-6)  # after the law, unbent


def test_optical_noise_scales_with_the_amplitude_and_receiver_noise_does_not():
    levels = tuple(e2c_model.tx_levels(-0.5, 0.5, 1.0))
    kw = {"n_samples": N, "symbol_seed": 1, "noise_seed": 2}
    for amplitude in (1.0, 0.5):
        clean = e2c_model.synthesize(
            BASE, e2c_model.Synthesis(levels, e2c_model.IDENTITY, 0.0, 0.0, amplitude), **kw
        )
        opt = e2c_model.synthesize(
            BASE, e2c_model.Synthesis(levels, e2c_model.IDENTITY, 0.2, 0.0, amplitude), **kw
        )
        rx = e2c_model.synthesize(
            BASE, e2c_model.Synthesis(levels, e2c_model.IDENTITY, 0.0, 0.2, amplitude), **kw
        )
        assert np.std(opt - clean) == pytest.approx(0.2 * amplitude, rel=1e-6)
        assert np.std(rx - clean) == pytest.approx(0.2, rel=1e-6)


def test_noise_bounds_and_control_splits():
    assert e2c_model.bound_sigmas(0.3, 0.4, "RX") == (0.3, 0.4)
    assert e2c_model.bound_sigmas(0.3, 0.4, "OPT") == pytest.approx((0.5, 0.0))
    assert e2c_model.control_sigmas(0.5, 0.36, "RX") == pytest.approx((0.3, 0.4))
    assert e2c_model.control_sigmas(0.5, 0.36, "OPT") == (0.5, 0.0)
    with pytest.raises(BenchmarkError):
        e2c_model.bound_sigmas(0.3, 0.4, "BOTH")
    with pytest.raises(BenchmarkError):
        e2c_model.control_sigmas(0.5, 1.5, "RX")


def test_tx_levels_have_two_free_values_and_round_trip_the_r13_levels():
    levels = [-1.6801562713244484, -0.4806332292736232, 0.5935059075582139, 1.6796338640836104]
    g = e2c_model.g_ref_of(levels)
    q1, q2 = e2c_model.q_of(levels)
    rebuilt = e2c_model.tx_levels(q1, q2, g)
    assert rebuilt == pytest.approx(np.asarray(levels) - np.mean(levels), abs=1e-12)
    assert np.mean(e2c_model.tx_levels(-0.3, 0.7, 2.0)) == pytest.approx(0.0, abs=1e-12)
    assert np.diff(e2c_model.tx_levels(-0.3, 0.7, 2.0))[[0, 2]].sum() / 2 > 0


def test_the_joint_fit_recovers_known_coefficients_on_synthetic_windows():
    """Targets made with the fit's own seeds, so the truth has objective 0; start close to it."""
    g = e2c_model.g_ref_of(BASE["pulse_levels"])
    truth = {"q1": -0.45, "q2": 0.55, "a": -0.04, "b": -0.04, "sigma_rx": 0.08, "sigma_opt": 0.06}
    law = e2c_model.Law("poly", truth["a"], truth["b"])
    levels = tuple(e2c_model.tx_levels(truth["q1"], truth["q2"], g))
    targets = []
    for amplitude in (1.0, 0.8):
        spec = e2c_model.Synthesis(levels, law, truth["sigma_opt"], truth["sigma_rx"], amplitude)
        y = e2c_model.synthesize(BASE, spec, n_samples=N, symbol_seed=5, noise_seed=5)
        targets.append(e2c_model.FitTarget(e2_score.window_summary(y, FS, BAUD), amplitude, "t"))
    start = {**truth, "a": -0.035, "b": -0.045}
    result = e2c_model.fit_law(
        BASE,
        targets,
        profile="poly",
        start=start,
        fit_seed=5,
        fit_samples=N,
        maxfev=120,
        restarts=1,
    )
    assert result["law"]["a"] == pytest.approx(truth["a"], abs=0.004)
    assert result["law"]["b"] == pytest.approx(truth["b"], abs=0.004)
    assert result["objective"] < 0.02
    wrong = e2c_model.fit_law(
        BASE, targets, profile="poly_a0", start={k: v for k, v in start.items() if k != "a"},
        fit_seed=5, fit_samples=N, maxfev=60, restarts=0,
    )  # fmt: skip
    assert wrong["objective"] > result["objective"]  # without the cubic term the fit is worse


# ---------------------------------------------------------------------------- windows read
class RecordingCapture:
    def __init__(self) -> None:
        self.reads: list[tuple[int, int]] = []

    def read(self, start: int, stop: int) -> np.ndarray:
        self.reads.append((start, stop))
        return np.linspace(-1.0, 1.0, 64)


def test_the_fit_reads_fit_windows_only():
    capture = RecordingCapture()
    e2c_study.read_windows(capture, e2c_study.FIT_WINDOW_NAMES, 0.0, 1.0)
    assert capture.reads == [(0, 8388608)]


def test_the_fit_targets_are_built_from_the_fit_windows_only():
    script = load_script()
    rng = np.random.default_rng(1)
    fit = e2c_model.synthesize(
        BASE, e2c_model.Synthesis((-1.5, -0.5, 0.5, 1.5), e2c_model.IDENTITY, 0.1, 0.1, 1.0),
        n_samples=N, symbol_seed=3, noise_seed=4,
    )  # fmt: skip
    poison = rng.normal(size=N) * 50.0  # a window the fit must not see
    data = {label: {"fit": fit, "spread": poison, "evaluation": poison} for label in ("b2b", "2km")}
    targets = script.fit_targets(data, FS, BAUD)
    reference = e2_score.window_summary(fit, FS, BAUD)
    assert [t.amplitude for t in targets] == [1.0, 0.832]
    for target in targets:
        assert target.summary.gaps == pytest.approx(reference.gaps)
        assert target.summary.std == pytest.approx(reference.std)


def test_truths_come_from_study_windows_only_and_those_overlap_nothing_else():
    capture = RecordingCapture()
    e2c_study.read_windows(capture, e2c_study.STUDY_WINDOW_NAMES, 0.0, 1.0)
    assert capture.reads == [(s, s + 4194304) for s in e2c_study.STUDY_STARTS]
    spans = [(s, s + n) for s, n in e2c_study.WINDOWS.values()] + capture.reads
    for i, (a0, a1) in enumerate(spans):
        for b0, b1 in spans[i + 1 :]:
            assert a1 <= b0 or b1 <= a0
    with pytest.raises(BenchmarkError):
        e2c_study.read_windows(capture, ("holdout",), 0.0, 1.0)


# ---------------------------------------------------------------------------- amendment A2
COMMON = {"q1": -0.5, "q2": 0.5, "sigma_rx": 0.07, "sigma_opt": 0.07}


def test_a2_starts_are_the_declared_deterministic_grid():
    starts = {p: e2c_model.a2_starts(p, COMMON) for p in ("identity", "poly_b0", "poly_a0", "tanh")}
    assert [len(starts[p]) for p in starts] == [1, 3, 3, 3]
    assert starts["identity"] == [COMMON]
    assert [s["a"] for s in starts["poly_b0"]] == [-0.03, 0.0, 0.03]
    assert [s["b"] for s in starts["poly_a0"]] == [-0.05, 0.0, 0.05]
    assert [(s["k"], s["o"]) for s in starts["tanh"]] == [(0.1, -0.4), (0.1, 0.0), (0.1, 0.4)]
    with pytest.raises(BenchmarkError, match="optima of poly_b0 and poly_a0"):
        e2c_model.a2_starts("poly", COMMON)
    nested = {"poly_b0": {**COMMON, "a": 0.011}, "poly_a0": {**COMMON, "b": -0.022, "q1": -0.4}}
    poly = e2c_model.a2_starts("poly", COMMON, nested)
    assert len(poly) == 11
    assert [(s["a"], s["b"]) for s in poly[:9]] == [
        (a, b) for a in (-0.03, 0.0, 0.03) for b in (-0.05, 0.0, 0.05)
    ]
    assert poly[9] == {**COMMON, "a": 0.011, "b": 0.0}
    assert poly[10] == {**COMMON, "q1": -0.4, "a": 0.0, "b": -0.022}
    assert all(s[k] == COMMON[k] for s in poly[:9] for k in COMMON)
    assert e2c_model.A2_STEPS["a"] == 0.02 and e2c_model.A2_STEPS["b"] == 0.03
    assert e2c_model.A2_STEPS["q1"] == 0.02 and e2c_model.A2_STEPS["k"] == 0.1
    assert e2c_model.A2_SCREEN_MAXFEV == 200 and e2c_model.A2_FULL_MAXFEV == 600
    assert e2c_model.A2_KEEP == 2


def run_record(kind: str, start: int, objective: float, a: float = 0.0, b: float = 0.0):
    x = {"q1": -0.5, "q2": 0.5, "a": a, "b": b, "sigma_rx": 0.07, "sigma_opt": 0.07}
    return {"kind": kind, "start": start, "objective": objective, "x": x, "evaluations": 10}


def test_a2_selection_and_the_optimum_are_the_best_of_every_run():
    screens = [run_record("screen", i, v) for i, v in enumerate([0.30, 0.20, 0.25, 0.20])]
    assert e2c_model.a2_select(screens) == [1, 3]  # ties by start position
    runs = [*screens, run_record("full", 1, 0.19), run_record("restart", 1, 0.185),
            run_record("full", 3, 0.17, a=0.02), run_record("restart", 3, 0.18)]  # fmt: skip
    best = e2c_model.a2_optimum(runs)
    assert best["objective"] == 0.17 and best["start"] == 3
    document = e2c_model.a2_profile_document(
        "poly", BASE, [], [{}] * 4, runs, fit_seed=1, fit_samples=N
    )
    assert document["objective"] == 0.17 and document["law"]["a"] == 0.02
    assert document["a2"]["selected_for_full"] == [1, 3]


def accepted_profiles(**objectives: float) -> dict[str, dict]:
    """Profile records that pass every A2 check; keyword arguments override objectives."""
    obj = {"identity": 0.30, "poly_b0": 0.20, "poly_a0": 0.21, "tanh": 0.18, "poly": 0.15}
    obj |= objectives
    profiles = {}
    for p, v in obj.items():
        runs = [run_record("screen", 0, v + 0.01), run_record("full", 0, v)]
        profiles[p] = {"objective": v, "a2": {"runs": runs}}
    poly = obj["poly"]
    profiles["poly"]["a2"] = {
        "runs": [
            run_record("screen", 0, poly + 0.02),
            run_record("full", 0, poly),
            run_record("screen", 4, poly + 0.03),
            run_record("full", 4, poly + 0.0005),
            run_record("screen", 7, poly + 0.004),
            run_record("stationarity", 0, poly),
        ],
        "stationarity": {"gain": 0.0},
    }
    return profiles


def test_a2_acceptance_passes_a_consistent_fit():
    verdict = e2c_model.a2_acceptance(accepted_profiles())
    assert verdict["valid"] and verdict["failed"] == [] and verdict["status"] == "VALID"
    assert verdict["checks"]["AC4_two_basin_agreement"]["agreeing_starts"] == [0, 4]


def test_a2_ac1_poly_above_a_nested_profile_is_invalid():
    assert e2c_model.a2_acceptance(accepted_profiles(poly=0.2000005))["valid"]  # within 1e-6
    profiles = accepted_profiles(poly=0.2000020)
    verdict = e2c_model.a2_acceptance(profiles)
    assert not verdict["valid"] and "AC1_nested" in verdict["failed"]
    assert verdict["status"] == "FIT_INVALID, S2 not evaluable"


def test_a2_ac1_includes_the_identity_base():
    verdict = e2c_model.a2_acceptance(accepted_profiles(identity=0.19, tanh=0.18, poly=0.15))
    assert verdict["failed"] == ["AC1_nested"]  # min(nested) 0.20 above the identity 0.19
    lines = verdict["checks"]["AC1_nested"]["lines"]
    assert lines == {
        "poly <= min(poly_b0, poly_a0)": True,
        "min(poly_b0, poly_a0) <= identity": False,
        "tanh <= identity": True,
    }
    verdict = e2c_model.a2_acceptance(accepted_profiles(tanh=0.31))
    assert verdict["failed"] == ["AC1_nested"]
    assert not verdict["checks"]["AC1_nested"]["lines"]["tanh <= identity"]


def test_a2_ac2_a_reported_optimum_that_is_not_the_lowest_run_is_invalid():
    profiles = accepted_profiles()
    profiles["poly_a0"]["a2"]["runs"].append(run_record("restart", 0, 0.2099))
    verdict = e2c_model.a2_acceptance(profiles)
    assert verdict["failed"] == ["AC2_best_of_all_starts"]


def test_a2_ac3_a_stationarity_run_that_still_improves_is_invalid():
    profiles = accepted_profiles()
    profiles["poly"]["a2"]["stationarity"]["gain"] = 0.99e-4
    assert e2c_model.a2_acceptance(profiles)["valid"]
    profiles["poly"]["a2"]["stationarity"]["gain"] = 2e-4
    assert e2c_model.a2_acceptance(profiles)["failed"] == ["AC3_stationarity"]
    del profiles["poly"]["a2"]["stationarity"]
    assert e2c_model.a2_acceptance(profiles)["failed"] == ["AC3_stationarity"]


def test_a2_ac4_one_basin_alone_is_invalid():
    profiles = accepted_profiles()
    runs = profiles["poly"]["a2"]["runs"]
    runs[3] = run_record("full", 4, 0.15 + 0.0011)  # just outside 1e-3
    verdict = e2c_model.a2_acceptance(profiles)
    assert verdict["failed"] == ["AC4_two_basin_agreement"]
    assert verdict["checks"]["AC4_two_basin_agreement"]["agreeing_starts"] == [0]
    runs[4] = run_record("screen", 7, 0.15 + 0.0009)  # a screen end counts for its start
    assert e2c_model.a2_acceptance(profiles)["valid"]


def test_the_nested_invariant_refuses_a_poly_result_above_a_nested_profile():
    e2c_model.require_nested({"poly": 0.19, "poly_b0": 0.19, "poly_a0": 0.2})
    with pytest.raises(BenchmarkError, match="nested poly_a0"):
        e2c_model.require_nested({"poly": 0.1930, "poly_b0": 0.1931, "poly_a0": 0.1908})
    with pytest.raises(BenchmarkError, match="nested poly_b0"):
        e2c_model.require_nested({"poly": 0.1930, "poly_b0": 0.1911})


def test_the_fit_step_refuses_r6_for_a_poly_result_above_a_nested_profile():
    script = load_script()
    fit = {"objective": 0.1930, "sigma_opt": 0.05, "sigma_rx": 0.05,
           "tx_levels": [-1.5, -0.5, 0.5, 1.5], "law": {"kind": "poly", "a": 0.0, "b": 0.0}}  # fmt: skip
    fits = {"poly": fit, "poly_b0": {**fit, "objective": 0.1911}, "tanh": fit}
    with pytest.raises(BenchmarkError, match="not an optimum, refused"):
        script.r6_rows(BASE, fits, {})


def test_the_a2_optimiser_screens_every_start_and_refines_the_best_two(monkeypatch):
    monkeypatch.setattr(e2c_model, "A2_SCREEN_MAXFEV", 12)
    monkeypatch.setattr(e2c_model, "A2_FULL_MAXFEV", 16)
    g = e2c_model.g_ref_of(BASE["pulse_levels"])
    law = e2c_model.Law("poly", 0.0, -0.04)
    levels = tuple(e2c_model.tx_levels(-0.5, 0.5, g))
    targets = []
    for amplitude in (1.0, 0.8):
        spec = e2c_model.Synthesis(levels, law, 0.06, 0.08, amplitude)
        y = e2c_model.synthesize(BASE, spec, n_samples=N, symbol_seed=5, noise_seed=5)
        targets.append(e2c_model.FitTarget(e2_score.window_summary(y, FS, BAUD), amplitude, "t"))
    starts = {"poly_a0": e2c_model.a2_starts("poly_a0", COMMON)}
    fits = e2c_model.fit_profiles_a2(
        BASE, targets, starts, fit_seed=5, fit_samples=N, stationarity_for=("poly_a0",)
    )
    record = fits["poly_a0"]
    runs = record["a2"]["runs"]
    assert sorted(r["start"] for r in runs if r["kind"] == "screen") == [0, 1, 2]
    screens = [r for r in runs if r["kind"] == "screen"]
    assert record["a2"]["selected_for_full"] == e2c_model.a2_select(screens)
    assert len(record["a2"]["selected_for_full"]) == 2
    assert [r["kind"] for r in runs].count("stationarity") == 1
    assert all(r["evaluations"] <= 16 + 2 for r in runs)
    assert record["objective"] == min(r["objective"] for r in runs)
    assert "stationarity" in record["a2"]


# ---------------------------------------------------------------------------- calibration route
OPEN_EVENTS = ("open", "os.open", "subprocess.Popen", "os.posix_spawn", "os.exec", "os.system")
_AUDIT: dict[str, list[tuple[str, str]] | None] = {"events": None}


def _hook(event: str, args: tuple) -> None:
    events = _AUDIT["events"]
    if events is not None and event in OPEN_EVENTS:
        events.append((event, str(args[0]) if args else ""))


sys.addaudithook(_hook)


@pytest.fixture
def audit():
    _AUDIT["events"] = []
    yield _AUDIT["events"]
    _AUDIT["events"] = None


def test_the_route_refuses_the_10km_name_before_any_open_or_process(tmp_path, audit):
    target = tmp_path / TEN_KM
    target.write_bytes(b"\0" * 64)
    link = tmp_path / "link" / TWO_KM
    link.parent.mkdir()
    link.symlink_to(target)
    audit.clear()
    for path in (target, Path("data/external/teriphic") / TEN_KM, link):
        with pytest.raises(BenchmarkError, match="10 km file"):
            e2c_calibration.open_two_km(path, root=tmp_path)
    assert audit == []


def test_the_route_refuses_every_other_name_before_any_open(tmp_path, audit):
    for name in (teriphic.B2B_FILENAME, "NOPE_2km.bin", "other.bin"):
        with pytest.raises(BenchmarkError, match="opens only"):
            e2c_calibration.open_two_km(tmp_path / name, root=tmp_path)
    assert audit == []


def git_repo(path: Path, record: bytes | None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run = ["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*run, "init", "-q"], check=True)
    (path / "readme").write_text("fixture")
    if record is not None:
        target = path / e2c_calibration.TWO_KM_RECORD_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(record)
    subprocess.run([*run, "add", "-A"], check=True)
    subprocess.run([*run, "commit", "-q", "-m", "fixture"], check=True)
    return path


def fixture_two_km(tmp_path: Path):
    """A 2 km-named fixture file, a register naming its MD5 and a hash table with its SHA-256."""
    samples = np.random.default_rng(0).normal(size=4096).astype(np.float32)
    data = keysight_image(samples)
    path = tmp_path / "captures" / TWO_KM
    path.parent.mkdir()
    path.write_bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    source = teriphic.load_config(ROOT / teriphic.CONFIG_PATH)
    assets = tuple(
        dataclasses.replace(a, checksum=Checksum(md5_supplied=md5)) if a.filename == TWO_KM else a
        for a in source.assets
    )
    return (
        path,
        dataclasses.replace(source, assets=assets),
        {TWO_KM: hashlib.sha256(data).hexdigest()},
    )


def fail_record() -> bytes:
    return (ROOT / e2c_calibration.TWO_KM_RECORD_PATH).read_bytes()


def test_the_route_opens_only_the_registered_2km_file_with_its_hash(tmp_path, audit):
    path, source, table = fixture_two_km(tmp_path)
    repo = git_repo(tmp_path / "repo", fail_record())
    audit.clear()
    capture = e2c_calibration.open_two_km(path, root=repo, source=source, holdout_sha256=table)
    try:
        assert capture.count == 4096
    finally:
        capture.close()
    opened = {Path(p).name for e, p in audit if e == "open" and "captures" in p}
    assert opened == {TWO_KM}
    with pytest.raises(BenchmarkError, match="SHA-256 differs"):
        e2c_calibration.open_two_km(
            path, root=repo, source=source, holdout_sha256={TWO_KM: "0" * 64}
        )


def test_the_route_needs_the_committed_r13_record_saying_fail(tmp_path, audit):
    path, source, table = fixture_two_km(tmp_path)
    passing = json.loads(fail_record())
    passing["outcome"] = "PASS, DISCRIMINATING"
    passing["verdict"] = None
    changed = json.dumps(passing).encode()
    cases = {
        "missing": (git_repo(tmp_path / "none", None), e2c_calibration.TWO_KM_RECORD_SHA256),
        "pass": (git_repo(tmp_path / "pass", changed), hashlib.sha256(changed).hexdigest()),
        "unpinned": (
            git_repo(tmp_path / "unpinned", changed),
            e2c_calibration.TWO_KM_RECORD_SHA256,
        ),
    }
    for name, (repo, pin) in cases.items():
        audit.clear()
        with pytest.raises(BenchmarkError):
            e2c_calibration.open_two_km(
                path, root=repo, source=source, holdout_sha256=table, record_sha256=pin
            )
        assert not any(TWO_KM in p for e, p in audit if e == "open" and "captures" in p), name
    uncommitted = git_repo(tmp_path / "dirty", fail_record())
    (uncommitted / e2c_calibration.TWO_KM_RECORD_PATH).write_bytes(fail_record() + b" ")
    with pytest.raises(BenchmarkError, match="not committed or modified"):
        e2c_calibration.require_two_km_fail_record(uncommitted)


# ---------------------------------------------------------------------------- limits, outcomes
METRIC_NAMES = holdout.METRICS


def test_limits_take_the_larger_of_basis_and_model_spread_times_two():
    basis = dict(zip(METRIC_NAMES, (0.01, 0.03, 0.06, 0.6), strict=True))
    spread = dict(zip(METRIC_NAMES, (0.02, 0.01, 0.06, 0.9), strict=True))
    limits = e2c_study.cell_limits(basis, spread)
    assert [limits[m] for m in METRIC_NAMES] == pytest.approx([0.04, 0.06, 0.12, 1.8])
    assert e2c_study.spread_binds(basis, spread) == [METRIC_NAMES[0], METRIC_NAMES[3]]
    tables = [dict(zip(METRIC_NAMES, row, strict=True)) for row in ((1, 5, 2, 0), (3, 1, 2, 4))]
    assert e2c_study.basis_of(tables) == dict(zip(METRIC_NAMES, (3, 5, 2, 4), strict=True))


def test_controls_span_the_whole_d_by_a_grid():
    laws, controls = e2c_study.scenario_cells(("poly",))
    grid = {(d, a, b) for d in e2c_study.DISPERSION_GRID for a in e2c_study.AMPLITUDES
            for b in e2c_study.BOUNDS}  # fmt: skip
    assert len(grid) == 252 and len(laws) == 252 and len(controls) == 504
    for control in e2c_study.CONTROLS:
        assert {
            (c.dispersion, c.amplitude, c.bound) for c in controls if c.family == control
        } == grid
    assert {(c.dispersion, c.amplitude, c.bound) for c in laws} == grid
    assert len(e2c_study.scenario_cells(("poly", "tanh"))[0]) == 504


def summary_of(seed: int, shift: float = 0.0) -> e2_metrics.WindowSummary:
    x = e2c_model.synthesize(
        BASE, e2c_model.Synthesis((-1.5, -0.5 + shift, 0.5, 1.5), e2c_model.IDENTITY, 0.1, 0.1, 1.0),
        n_samples=N, symbol_seed=seed, noise_seed=seed,
    )  # fmt: skip
    return e2_score.window_summary(x, FS, BAUD)


def make_bank(rows: dict[Cell, e2_metrics.WindowSummary], limit: float) -> e2c_study.Bank:
    limits = {(c.amplitude, c.bound): {m: limit for m in METRIC_NAMES} for c in rows}
    return e2c_study.stack(list(rows), {c.key: s for c, s in rows.items()}, limits)


def test_the_bank_scores_equal_the_frozen_metrics_row_by_row():
    measured = summary_of(1)
    rows = {Cell("law:poly", 0.0, 0.45, "RX"): summary_of(2, 0.05),
            Cell("C-B2B", 0.0, 0.45, "RX"): summary_of(3)}  # fmt: skip
    bank = make_bank(rows, 1.0)
    got = e2c_study.bank_metrics(measured, bank)
    for i, summary in enumerate(rows.values()):
        want = e2_metrics.metrics_between(measured, summary)
        assert got[i] == pytest.approx([want[m] for m in METRIC_NAMES], rel=1e-12)


def test_a_control_survivor_makes_a_pass_not_discriminating():
    assert e2c_study.outcome_of(0, 0) == e2c_study.OUTCOME_FAIL
    assert e2c_study.outcome_of(0, 3) == e2c_study.OUTCOME_FAIL
    assert e2c_study.outcome_of(2, 1) == e2c_study.OUTCOME_PND
    assert e2c_study.outcome_of(2, 0) == e2c_study.OUTCOME_PD
    measured = summary_of(1)
    law, ctrl = Cell("law:poly", 4.5, 0.45, "RX"), Cell("C-2KM", 4.5, 0.45, "RX")
    close, far = summary_of(1), summary_of(4, 0.3)
    both = e2c_study.score_capture(measured, make_bank({law: close, ctrl: close}, 10.0))
    assert both["outcome"] == e2c_study.OUTCOME_PND and both["control_survivors"] == 1
    only = e2c_study.score_capture(measured, make_bank({law: close, ctrl: far}, 0.05))
    assert only["outcome"] == e2c_study.OUTCOME_PD and only["survivor_D"] == [4.5]
    with pytest.raises(BenchmarkError):
        e2c_study.score_capture(measured, make_bank({law: close}, 1.0))


# ---------------------------------------------------------------------------- the decision rule
def counts(values):
    return {f"c{i}": v for i, v in enumerate(values)}


def test_the_decision_rule_as_pre_registered():
    assert e2c_study.r1_holds(counts([5, 4, 4, 5, 4, 4]))
    assert not e2c_study.r1_holds(counts([5, 4, 3, 5, 4, 4]))  # 3 of 5 fails
    assert e2c_study.r2_holds(counts([1, 1, 1, 1, 0, 0, 0, 0]))  # 4 of 40
    assert not e2c_study.r2_holds(counts([1, 1, 1, 1, 1, 0, 0, 0]))  # pooled 5 of 40 fails
    assert not e2c_study.r2_holds(counts([2, 0, 0, 0, 0, 0, 0, 0]))  # 2 of 5 fails
    worth = e2c_study.decide(step0_viable=True, r6=True, s3=True, r1=True, r2=True)
    assert worth["decision"] == "WORTH_SPENDING_10KM" and worth["stop_condition"] is None
    stops = {
        "S1": {"step0_viable": False, "r6": None, "s3": None, "r1": None, "r2": None},
        "S2": {"step0_viable": True, "r6": False, "s3": None, "r1": None, "r2": None},
        "S3": {"step0_viable": True, "r6": True, "s3": False, "r1": None, "r2": None},
    }
    for stop, flags in stops.items():
        out = e2c_study.decide(**flags)
        assert out["decision"] == "CLOSE_PARTIAL" and out["stop_condition"] == stop
    for r1, r2 in ((False, True), (True, False), (None, None)):
        out = e2c_study.decide(step0_viable=True, r6=True, s3=True, r1=r1, r2=r2)
        assert out["decision"] == "CLOSE_PARTIAL" and out["stop_condition"] == "S4"
    assert e2c_study.reach({0.45: [5, 4], 0.65: [4, 4], 0.85: [2, 3]},
                           {0.45: [0, 1, 0, 0], 0.65: [1, 0, 0, 0], 0.85: [0, 0, 0, 0]}) == 0.65  # fmt: skip


def test_the_truth_families_are_the_48_configurations_of_d13():
    configs = e2c_study.truth_configs()
    assert len(configs) == 48 and len({c.key for c in configs}) == 48
    r1 = [c for c in configs if c.role == "R1"]
    r2 = [c for c in configs if c.role == "R2"]
    assert {(c.dispersion, c.bound) for c in r1} == {
        (d, b) for d in (0.0, 4.5, 6.352) for b in ("RX", "OPT")
    }
    assert all(c.family == "T1" and c.source == "2km" and c.amplitude == 0.45 for c in r1)
    assert len(r2) == 8 and all(c.family in ("T2", "T3") and c.amplitude == 0.45 for c in r2)


def test_pseudo_captures_reduce_to_the_source_when_nothing_changes():
    x = summary_source = e2c_model.synthesize(
        BASE, e2c_model.Synthesis((-1.5, -0.5, 0.5, 1.5), e2c_model.IDENTITY, 0.1, 0.1, 1.0),
        n_samples=N, symbol_seed=8, noise_seed=8,
    )  # fmt: skip
    law = e2c_model.Law("poly", -0.03, -0.02)
    bent = law.apply(0.832 * summary_source / 1.0)
    unit = e2c_study.TruthConfig("T1", "2km", 0.0, 0.832, "OPT")
    out = e2c_study.pseudo_capture(bent, unit, law=law, sigma_rx=0.1, fs=FS, noise=lambda n, s: 0)
    assert out == pytest.approx(bent, abs=1e-9)
    flat = e2c_study.TruthConfig("T2", "b2b", 0.0, 1.0, "RX")
    assert e2c_study.pseudo_capture(x, flat, law=law, sigma_rx=0.1, fs=FS, noise=None) == (
        pytest.approx(x)
    )
    half = e2c_study.TruthConfig("T2", "b2b", 0.0, 0.5, "RX")
    added = e2c_study.pseudo_capture(
        x, half, law=law, sigma_rx=0.2, fs=FS,
        noise=lambda n, s: e2_model.shaped_noise(PSD, FS, n, s, 1),
    )  # fmt: skip
    assert np.std(added - 0.5 * x) == pytest.approx(0.2 * math.sqrt(0.75), rel=1e-6)


def test_step0_screens_and_viability_lines():
    grid = np.round(np.random.default_rng(0).normal(size=20000) * 50) / 64.0
    step = e2c_study.code_step(grid)
    assert step["observable"] and step["smallest_step"] == pytest.approx(1 / 64)
    smooth = e2c_study.code_step(np.random.default_rng(1).normal(size=20000))
    assert not smooth["observable"]
    assert e2c_study.code_step_changed(step, smooth) is None
    assert e2c_study.code_step_changed(step, e2c_study.code_step(grid * 2)) is True
    clipped = np.random.default_rng(2).normal(size=10000)
    clipped[:20] = clipped.max()
    assert e2c_study.clip_screen(clipped)["clip"]
    assert not e2c_study.clip_screen(np.random.default_rng(3).normal(size=10000))["clip"]
    ok = e2c_study.viability([1.0, 1.0, 1.0], [1.01, 0.96, 1.03], 0.003, False, None)
    assert ok["viable"] and ok["code_step_change"] == "not observable"
    wrong_sign = e2c_study.viability([1.0, 1.0, 1.0], [1.03, 0.99, 0.98], 0.003, False, None)
    assert not wrong_sign["viable"] and not wrong_sign["lines"]["V2_top_gap_widens"]
    small = e2c_study.viability([1.0, 1.0, 1.0], [1.0, 0.995, 1.005], 0.003, False, None)
    assert not small["lines"]["V1_change_exceeds_3_spreads"]
    assert not e2c_study.viability([1, 1, 1], [1.0, 0.97, 1.03], 0.003, True, None)["viable"]
    assert not e2c_study.viability([1, 1, 1], [1.0, 0.97, 1.03], 0.003, False, True)["viable"]


# ---------------------------------------------------------------------------- the R13 binding
def test_real_no_r13_bound_file_changed():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs the repository history")
    frozen = types.SimpleNamespace(commit=e2c_calibration.R13_FREEZE_COMMIT)
    e2_score.bind_to_freeze(ROOT, frozen)  # model, scenarios, pre-registration, script, code
    criterion = (ROOT / holdout.CRITERION_PATH).read_text()
    plan_hash = hashlib.sha256((ROOT / holdout.DEFAULT_PLAN).read_bytes()).hexdigest()
    assert f"plan_sha256: {plan_hash}" in criterion
    changed = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-only", e2c_calibration.R13_FREEZE_COMMIT, "HEAD",
         "--", "docs/benchmarks/teriphic_e2", holdout.CRITERION_PATH.as_posix(),
         teriphic.CONFIG_PATH.as_posix()],
        capture_output=True, text=True, check=True, env={k: v for k, v in os.environ.items()
                                                          if not k.startswith("GIT_")},
    ).stdout.split()  # fmt: skip
    assert set(changed) <= {"docs/benchmarks/teriphic_e2/two_km_result.json"}
