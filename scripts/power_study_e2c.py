"""E2c power study (design `E2c_power_study_fable.md`, plan `teriphic_e2c/STUDY_PLAN.md`).

    python scripts/power_study_e2c.py step0     # diagnostics and viability (S1)
    python scripts/power_study_e2c.py fit       # A2 joint fit on B2B and 2 km fit windows, R6 (S2)
    python scripts/power_study_e2c.py predict   # 10 km scenarios, controls, limits, D11, S3
    python scripts/power_study_e2c.py power     # truth families T1 to T7 x 5 windows
    python scripts/power_study_e2c.py decide    # the D14 rule, `power_study_e2c_v2.yaml`

Reads the B2B capture through `teriphic.open_b2b` and the 2 km capture through
`e2c_calibration.open_two_km` only, at the plan's window offsets only. Never names, opens, hashes or
stats the 10 km file. Each committed output is written once; a re-run that would change its bytes
writes a new version suffix instead. Amendment A2 (plan): the fit step runs the A2 optimiser and its
acceptance checks and writes `law_model_v2.yaml`; `decide` writes `power_study_e2c_v2.yaml`; the v1
files `law_model.yaml` and `power_study_e2c.yaml` stay as the v1 record and are never rewritten.
Heavy intermediates (prediction summaries, truth summaries) go to `--cache` (default
`build/e2c_cache_v2`, not committed). Exit codes: 0 done, 2 refused or a
prerequisite missing, 3 the study stopped at a pre-registered stop condition before this step.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle  # the cache is this script's own local output, never an external file
import subprocess
import sys
import time
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opticps.benchmarks import (  # noqa: E402
    e2_metrics,
    e2_model,
    e2_score,
    e2c_calibration,
    e2c_model,
    e2c_study,
    holdout,
    teriphic,
)
from opticps.benchmarks.e2c_study import AMPLITUDES, BOUNDS, DISPERSION_GRID, Cell  # noqa: E402

OUT = ROOT / "docs/benchmarks/teriphic_e2c"
PLAN_PATH = OUT / "STUDY_PLAN.md"
STEP0_PATH = OUT / "step0_diagnostics.yaml"
LAW_PATH_V1 = OUT / "law_model.yaml"  # the v1 record (CLOSE_PARTIAL, S2), never rewritten
RESULT_PATH_V1 = OUT / "power_study_e2c.yaml"
LAW_PATH = OUT / "law_model_v2.yaml"  # amendment A2
RESULT_PATH = OUT / "power_study_e2c_v2.yaml"
AMENDMENTS = ["A1", "A2"]
PRIOR = "v1 CLOSE_PARTIAL S2, optimiser stall"
A2_STATUS_INVALID = "FIT_INVALID, S2 not evaluable"
B2B_MODEL_PATH = ROOT / e2_score.MODEL_PATH
TWO_KM_PATH = ROOT / teriphic.DEFAULT_ROOT / e2c_calibration.TWO_KM_NAME
NEW_CODE = (
    "src/opticps/benchmarks/e2c_calibration.py",
    "src/opticps/benchmarks/e2c_model.py",
    "src/opticps/benchmarks/e2c_study.py",
    "scripts/power_study_e2c.py",
)
R13_LIMITS = {
    "M1_level_spacing": 0.018135348178638377,
    "M2_wasserstein1_amplitude": 0.060001309573172026,
    "M3_quantile_error": 0.13066363126696678,
    "M4_log_spectral_distance": 1.217921781382072,
}  # docs/benchmarks/TERIPHIC_CRITERION_R13.yaml, checked against the file at run time
DECLARATIONS = {
    "a": (
        "The 2 km file was read under R13 (one window) and is read in full in E2c; it is "
        "calibration data from now on and never again a holdout; its VALIDATION role in "
        "ROLE_BY_NAME and the config stays until R14 rebinds it (this phase edits no bound file)."
    ),
    "b": (
        "R13's 2 km FAIL stands as the result of the pre-registered test of H1 (the "
        "B2B-calibrated small-signal surrogate transfers); H1 is refuted at 2 km and no 10 km "
        "result can rehabilitate it."
    ),
    "c": (
        "H2 (D1) is a different hypothesis, formed after seeing 2 km; tested at most once, on 10 "
        "km, under an R14 freeze; if H2 fails, no third hypothesis gets a fresh holdout from this"
        " dataset."
    ),
    "d": (
        "Ceiling: VALIDATED is never returned; a 10 km PASS, DISCRIMINATING is PARTIAL, "
        "INCONCLUSIVE, confounded by a coincident settings change, a mild low-pass, chirp, "
        "wavelength, fibre type and the grid; the law's seat stays unidentified."
    ),
    "e": ("BER and SER stay REFERENCE_SEQUENCE_MISSING."),
    "f": ("Limits, scenarios and rule use B2B and 2 km only; the 10 km file is not touched."),
    "d12_spread_term": (
        "The per-scenario model-spread term of D12 is approved by Aria for this study only; it is"
        " a structural change that needs explicit owner approval before any R14 freeze."
    ),
}


class Stopped(Exception):
    """A pre-registered stop condition fired at an earlier step."""


# ---------------------------------------------------------------------------- bookkeeping
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return done.stdout.decode().strip()


def provenance() -> dict[str, Any]:
    plan_commit = git(
        "log", "--diff-filter=A", "--format=%H", "--", PLAN_PATH.relative_to(ROOT).as_posix()
    )
    amendment_commit = git("log", "-1", "--format=%H", "--", PLAN_PATH.relative_to(ROOT).as_posix())
    return {
        "study_plan": {
            "path": PLAN_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(PLAN_PATH),
            "commit": plan_commit,
            "amendment_a2_commit": amendment_commit,
        },
        "amendments": AMENDMENTS,
        "prior": PRIOR,
        "a2_disclosure": "A2 was written after v1's result was seen; 10 km untouched.",
        "head_commit": git("rev-parse", "HEAD"),
        "code_identity": {p: sha256_file(ROOT / p) for p in NEW_CODE},
        "declarations": DECLARATIONS,
        "reference_sequence": e2c_study.BER_STATUS,
        "ten_km_file": "not read, hashed, opened, stat'ed or linked",
    }


def dump_yaml(document: Mapping[str, Any], header: str) -> bytes:
    text = header + yaml.safe_dump(
        dict(document), sort_keys=False, default_flow_style=None, width=110
    )
    return text.encode("utf-8")


def write_once(path: Path, data: bytes) -> Path:
    """Write `data` to `path` unless it exists; a different existing file gets a version suffix."""
    if not path.exists():
        path.write_bytes(data)
        return path
    if path.read_bytes() == data:
        return path
    k = 2
    while True:
        candidate = path.with_name(f"{path.stem}_v{k}{path.suffix}")
        if not candidate.exists():
            candidate.write_bytes(data)
            print(f"note: {path.name} exists with other bytes; wrote {candidate.name}", flush=True)
            return candidate
        if candidate.read_bytes() == data:
            return candidate
        k += 1


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing prerequisite {path.relative_to(ROOT)}")
    document = yaml.safe_load(path.read_bytes())
    if not isinstance(document, dict):
        raise SystemExit(f"{path.name} is not a mapping")
    return document


def b2b_model() -> dict[str, Any]:
    model = e2_score.check_model(yaml.safe_load(B2B_MODEL_PATH.read_bytes()))
    criterion = yaml.safe_load((ROOT / holdout.CRITERION_PATH).read_bytes())
    for name, value in R13_LIMITS.items():
        if not math.isclose(float(criterion["limits"][name]), value, rel_tol=1e-12):
            raise SystemExit(f"R13 limit {name} differs from the criterion file")
    return model


def summary_to_doc(s: e2_metrics.WindowSummary) -> dict[str, Any]:
    return {
        "centroids": [float(v) for v in s.centroids],
        "gaps": [float(v) for v in s.gaps],
        "shares": [float(v) for v in s.shares],
        "std": float(s.std),
    }


def metrics_doc(m: Mapping[str, float]) -> dict[str, float]:
    return {k: float(v) for k, v in m.items()}


def open_b2b_capture() -> Any:
    return teriphic.open_b2b(source=teriphic.load_config(ROOT / teriphic.CONFIG_PATH))


def open_two_km_capture() -> Any:
    return e2c_calibration.open_two_km(TWO_KM_PATH, root=ROOT)


# ---------------------------------------------------------------------------- step 0
def window_diagnostics(x_norm: np.ndarray, fs: float, baud: float) -> dict[str, Any]:
    centroids, shares = e2_metrics.kmeans_levels(x_norm)
    gap = float(np.diff(centroids).mean())
    renorm, centre, _ = e2_metrics.renormalise(x_norm)
    rc, _ = e2_metrics.kmeans_levels(renorm)
    gaps = np.diff(rc)
    ordered = np.sort(x_norm)
    mids = (centroids[1:] + centroids[:-1]) / 2.0
    edges = np.concatenate([[0], np.searchsorted(ordered, mids), [ordered.size]])
    stds = [float(ordered[edges[i] : edges[i + 1]].std() / gap) for i in range(4)]
    return {
        "centroids_b2b_normalised": [float(v) for v in centroids],
        "signed_gap_pattern": [float(v - 1.0) for v in gaps],
        "gaps_gain_invariant": [float(v) for v in gaps],
        "cluster_shares": [float(v) for v in shares],
        "cluster_std_gap_units": stds,
        "raw_gain_vs_b2b": gap,
        "window_std_gap_units": float(x_norm.std() / gap),
        "centre_b2b_normalised": float(centre),
    }


def step0(args: argparse.Namespace) -> int:
    model = b2b_model()
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    c0, g0 = float(model["normalisation"]["c0"]), float(model["normalisation"]["g0"])
    names = ("fit", "spread", "evaluation", *e2c_study.STUDY_WINDOW_NAMES)
    files: dict[str, Any] = {}
    started = time.time()
    for label, opener in (("b2b", open_b2b_capture), ("2km", open_two_km_capture)):
        capture = opener()
        try:
            windows = e2c_study.read_windows(capture, names, c0, g0)
            start, count = e2c_study.WINDOWS["fit"]
            raw_fit = capture.read(start, start + count)
        finally:
            capture.close()
        per_window = {}
        for name in names:
            entry = {} if name == "fit" else window_diagnostics(windows[name], fs, baud)
            entry["clip_screen"] = e2c_study.clip_screen(windows[name])
            per_window[name] = entry
        files[label] = {
            "windows": per_window,
            "code_step_fit_window_raw": e2c_study.code_step(raw_fit),
            "eval_summary": e2_score.window_summary(windows["evaluation"], fs, baud),
            "spread_summary": e2_score.window_summary(windows["spread"], fs, baud),
        }
        print(f"step0: {label} read", flush=True)
    b2b_spread = e2_metrics.metrics_between(
        files["b2b"]["eval_summary"], files["b2b"]["spread_summary"]
    )
    two_spread = e2_metrics.metrics_between(
        files["2km"]["eval_summary"], files["2km"]["spread_summary"]
    )
    changed = e2c_study.code_step_changed(
        files["b2b"]["code_step_fit_window_raw"], files["2km"]["code_step_fit_window_raw"]
    )
    any_clip = any(w["clip_screen"]["clip"] for f in files.values() for w in f["windows"].values())
    verdict = e2c_study.viability(
        files["b2b"]["eval_summary"].gaps,
        files["2km"]["eval_summary"].gaps,
        b2b_spread["M1_level_spacing"],
        any_clip,
        changed,
    )
    document = {
        "step0_version": 1,
        "declared": "Step 0 of the E2c power study (design D7, D6 ii; plan I10), before any fit."
        " B2B and 2 km"
        " only; the 2 km file is calibration data (D15 a). The 10 km file was not read.",
        **provenance(),
        "windows": {k: {"start": v[0], "samples": v[1]} for k, v in e2c_study.WINDOWS.items()}
        | {
            f"study{k}": {"start": s, "samples": e2c_study.STUDY_SAMPLES}
            for k, s in enumerate(e2c_study.STUDY_STARTS)
        },
        "normalisation": {"c0": c0, "g0": g0, "source": "teriphic_e2/b2b_model.yaml (R13)"},
        "b2b": {k: v for k, v in files["b2b"].items() if not k.endswith("_summary")},
        "two_km": {k: v for k, v in files["2km"].items() if not k.endswith("_summary")},
        "b2b_spread_metrics": metrics_doc(b2b_spread),
        "two_km_spread_metrics": metrics_doc(two_spread),
        "viability": verdict,
        "compute_seconds": round(time.time() - started, 1),
    }
    path = write_once(
        STEP0_PATH,
        dump_yaml(document, "# E2c Step 0 diagnostics (design D7). B2B and 2 km only.\n"),
    )
    print(json.dumps(verdict, indent=1), flush=True)
    print(f"wrote {path.relative_to(ROOT)}", flush=True)
    return 0


# ---------------------------------------------------------------------------- fit
def law_spec(
    fit: Mapping[str, Any],
    *,
    amplitude: float,
    bound: str,
    d: float = 0.0,
    length: float = 0.0,
    law: e2c_model.Law | None = None,
) -> e2c_model.Synthesis:
    s_opt, s_rx = e2c_model.bound_sigmas(float(fit["sigma_opt"]), float(fit["sigma_rx"]), bound)
    return e2c_model.Synthesis(
        tuple(float(v) for v in fit["tx_levels"]),  # type: ignore[arg-type]
        law or e2c_model.law_from_dict(fit["law"]),
        s_opt,
        s_rx,
        amplitude,
        d,
        length,
    )


def predict_window(
    base: Mapping[str, Any], spec: e2c_model.Synthesis, *, second: bool = False
) -> np.ndarray:
    seeds = e2c_study.SEEDS
    symbol = seeds["model_spread"] if second else seeds["prediction_symbols"]
    noise = seeds["model_spread"] if second else seeds["prediction_noise"]
    return e2c_model.synthesize(
        base, spec, n_samples=e2c_study.STUDY_SAMPLES, symbol_seed=symbol, noise_seed=noise
    )


def fit_targets(
    data: Mapping[str, Mapping[str, np.ndarray]], fs: float, baud: float
) -> list[e2c_model.FitTarget]:
    """The two fit targets (design D9): the fit windows only, at A 1 and A 0.832."""
    return [
        e2c_model.FitTarget(
            e2_score.window_summary(data["b2b"]["fit"], fs, baud), 1.0, "B2B fit window"
        ),
        e2c_model.FitTarget(
            e2_score.window_summary(data["2km"]["fit"], fs, baud),
            e2c_study.SOURCE_AMPLITUDE["2km"],
            "2 km fit window",
        ),
    ]


def r6_rows(
    model: Mapping[str, Any],
    fits: Mapping[str, Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """R6 (plan I6) of poly, tanh reported; refused for a poly result above a nested profile."""
    e2c_model.require_nested({p: float(f["objective"]) for p, f in fits.items()})
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    a2 = e2c_study.SOURCE_AMPLITUDE["2km"]
    r6: dict[str, Any] = {}
    for profile in ("poly", "tanh"):
        rows = {}
        for label, amplitude in (("b2b", 1.0), ("2km", a2)):
            y = predict_window(model, law_spec(fits[profile], amplitude=amplitude, bound="RX"))
            m = e2_metrics.metrics_between(
                summaries[label]["evaluation"], e2_score.window_summary(y, fs, baud)
            )
            rows[label] = {"metrics": metrics_doc(m), "psi_r13": e2_score.exceedance(m, R13_LIMITS)}
        r6[profile] = rows
    return r6


def fit(args: argparse.Namespace) -> int:
    step0_doc = load_yaml(STEP0_PATH)
    if not step0_doc["viability"]["viable"]:
        raise Stopped("S1: Step 0 is not viable; the fit is not run")
    model = b2b_model()
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    c0, g0 = float(model["normalisation"]["c0"]), float(model["normalisation"]["g0"])
    started = time.time()
    data: dict[str, dict[str, np.ndarray]] = {}
    for label, opener in (("b2b", open_b2b_capture), ("2km", open_two_km_capture)):
        capture = opener()
        try:
            data[label] = e2c_study.read_windows(capture, ("fit", "spread", "evaluation"), c0, g0)
        finally:
            capture.close()
    targets = fit_targets(data, fs, baud)
    g_ref = e2c_model.g_ref_of(model["pulse_levels"])
    q1, q2 = e2c_model.q_of(model["pulse_levels"])
    sigma0 = float(model["noise_sigma"]) / math.sqrt(2.0)
    common = {"q1": q1, "q2": q2, "sigma_rx": sigma0, "sigma_opt": sigma0}  # plan I5
    seed = e2c_study.SEEDS["fit"]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # A2.2: identity, the nested profiles and tanh first; poly needs the nested optima
        first = {
            p: e2c_model.a2_starts(p, common) for p in ("identity", "poly_b0", "poly_a0", "tanh")
        }
        fits = e2c_model.fit_profiles_a2(model, targets, first, fit_seed=seed, map_fn=pool.map)
        print("fit A2: first profiles", {p: round(f["objective"], 6) for p, f in fits.items()},
              f"{time.time() - started:.0f} s", flush=True)  # fmt: skip
        nested = {p: e2c_model.a2_optimum(fits[p]["a2"]["runs"])["x"] for p in e2c_model.NESTED}
        poly_starts = {"poly": e2c_model.a2_starts("poly", common, nested)}
        fits |= e2c_model.fit_profiles_a2(
            model, targets, poly_starts, fit_seed=seed, stationarity_for=("poly",), map_fn=pool.map
        )
    fits = {p: fits[p] for p in e2c_model.PROFILES_A2}
    print("fit A2: profiles", {p: round(f["objective"], 6) for p, f in fits.items()},
          f"{time.time() - started:.0f} s", flush=True)  # fmt: skip
    acceptance = e2c_model.a2_acceptance(fits)
    # C-2KM: the frozen R13 fitting procedure re-run on the 2 km fit window (plan I7)
    c2 = e2_model.fit_b2b_model(
        data["2km"]["fit"], sample_rate_hz=fs, baud_bd=baud, fit_seed=e2c_study.SEEDS["fit"]
    )
    c2_amplitude = float(e2_metrics.renormalise(data["2km"]["fit"])[2])
    summaries = {
        k: {w: e2_score.window_summary(v, fs, baud) for w, v in d.items() if w != "fit"}
        for k, d in data.items()
    }
    r6: dict[str, Any] | None = None
    r6_holds: bool | None = None
    if acceptance["valid"]:
        r6 = r6_rows(model, fits, summaries)  # refuses a poly result above a nested profile
        r6_holds = all(r6["poly"][k]["psi_r13"] <= 1.0 for k in ("b2b", "2km"))
    spreads = {
        label: metrics_doc(
            e2_metrics.metrics_between(summaries[label]["evaluation"], summaries[label]["spread"])
        )
        for label in ("b2b", "2km")
    }
    poly = fits["poly"]
    document = {
        "law_model_version": 2,
        "declared": "Joint calibration of the E2c law model (design D9, plan I1 to I7, amendments"
        " A1 and A2) on the B2B fit window (A 1) and the 2 km fit window (A 0.832). The evaluation"
        " windows give misfit (R6), the spread windows spread; the 10 km file was not read.",
        **provenance(),
        "v1_record": {
            "law_model.yaml": sha256_file(LAW_PATH_V1),
            "power_study_e2c.yaml": sha256_file(RESULT_PATH_V1),
            "decision_of_record": "CLOSE_PARTIAL, S2 (R6), unchanged by A2",
        },
        "step0_sha256": sha256_file(STEP0_PATH),
        "base_model": {
            "path": e2_score.MODEL_PATH.as_posix(),
            "sha256": sha256_file(B2B_MODEL_PATH),
            "g_ref": g_ref,
        },
        "windows": {k: {"start": v[0], "samples": v[1]} for k, v in e2c_study.WINDOWS.items()},
        "seeds": e2c_study.SEEDS,
        "source_amplitude": e2c_study.SOURCE_AMPLITUDE,
        "optimiser_a2": {
            "steps": {**e2c_model.A2_STEPS, "sigma": e2c_model.SIGMA_STEP},
            "screen_maxfev": e2c_model.A2_SCREEN_MAXFEV,
            "full_maxfev": e2c_model.A2_FULL_MAXFEV,
            "full_per_profile": e2c_model.A2_KEEP,
            "restarts": e2c_model.FIT_RESTARTS,
            "restart_gain": e2c_model.FIT_RESTART_GAIN,
            "grid": {
                "a": list(e2c_model.A2_GRID_A),
                "b": list(e2c_model.A2_GRID_B),
                "o": list(e2c_model.A2_GRID_O),
                "tanh_k": e2c_model.A2_TANH_K,
            },
            "fit_samples": e2c_model.FIT_SAMPLES,
            "workers": args.workers,
        },
        "acceptance": acceptance,
        "profiles": fits,
        "model_of_record": "poly",
        "tanh_role": "report-only (R6 psi reported, never gating)",
        "noise_optical_fraction_phi": float(
            poly["sigma_opt"] ** 2 / (poly["sigma_opt"] ** 2 + poly["sigma_rx"] ** 2)
        ),
        "control_c2km": {
            "procedure": (
                "e2_model.fit_b2b_model on the 2 km fit window (B2B-normalised), fit seed 20261111"
            ),
            "source_amplitude": c2_amplitude,
            "pulse_levels": c2["pulse_levels"],
            "noise_sigma": c2["noise_sigma"],
            "psd_relative": c2["psd_relative"],
            "fit": c2["fit"],
        },
        "control_cb2b": {
            "procedure": "teriphic_e2/b2b_model.yaml unchanged",
            "source_amplitude": 1.0,
        },
        "r13_limits": R13_LIMITS,
        "r6": r6,
        "r6_holds": r6_holds,
        "window_spreads": spreads,
        "compute_seconds": round(time.time() - started, 1),
    }
    path = write_once(
        LAW_PATH,
        dump_yaml(
            document, "# E2c law model, amendment A2 (design D9). B2B and 2 km fit windows only.\n"
        ),
    )
    print(json.dumps({"acceptance": acceptance["status"], "failed": acceptance["failed"],
                      "r6_holds": r6_holds, "r6": r6}, indent=1), flush=True)  # fmt: skip
    print(f"wrote {path.relative_to(ROOT)}", flush=True)
    if not acceptance["valid"]:
        raise Stopped(f"A2 acceptance failed {acceptance['failed']}: {A2_STATUS_INVALID}")
    return 0


# ---------------------------------------------------------------------------- predict
def _bases(model: Mapping[str, Any], law_doc: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    c2 = law_doc["control_c2km"]
    return {
        "law": dict(model),
        "C-B2B": dict(model),
        "C-2KM": {
            **dict(model),
            "psd_relative": c2["psd_relative"],
            "pulse_levels": c2["pulse_levels"],
            "noise_sigma": c2["noise_sigma"],
        },
    }


def cell_spec(
    cell: Cell, model: Mapping[str, Any], law_doc: Mapping[str, Any]
) -> tuple[str, e2c_model.Synthesis]:
    d, length = cell.dispersion, e2c_study.LENGTH_KM
    if cell.is_law:
        shape = cell.family.split(":", 1)[1]
        return "law", law_spec(
            law_doc["profiles"][shape],
            amplitude=cell.amplitude,
            bound=cell.bound,
            d=d,
            length=length,
        )
    phi = float(law_doc["noise_optical_fraction_phi"])
    if cell.family == "C-B2B":
        levels, sigma_c, a_src = model["pulse_levels"], float(model["noise_sigma"]), 1.0
    else:
        c2 = law_doc["control_c2km"]
        levels, sigma_c, a_src = (
            c2["pulse_levels"],
            float(c2["noise_sigma"]),
            float(c2["source_amplitude"]),
        )
    s_opt, s_rx = e2c_model.control_sigmas(sigma_c, phi, cell.bound)
    spec = e2c_model.Synthesis(
        tuple(float(v) for v in levels),  # type: ignore[arg-type]
        e2c_model.IDENTITY,
        s_opt,
        s_rx,
        cell.amplitude / a_src,
        d,
        length,
    )
    return cell.family, spec


def _predict_job(
    job: tuple[str, dict[str, Any], Any, bool],
) -> tuple[str, e2_metrics.WindowSummary]:
    key, base, spec, second = job
    y = predict_window(base, spec, second=second)
    return key, e2_score.window_summary(y, float(base["sample_rate_hz"]), float(base["baud_bd"]))


def predict(args: argparse.Namespace) -> int:
    law_doc = load_yaml(LAW_PATH)
    if not law_doc["acceptance"]["valid"]:
        raise Stopped(f"A2: {A2_STATUS_INVALID}; the predictions are not made")
    e2c_model.require_nested({p: float(f["objective"]) for p, f in law_doc["profiles"].items()})
    if not law_doc["r6_holds"]:
        raise Stopped("S2: R6 failed; the predictions are not made")
    model = b2b_model()
    bases = _bases(model, law_doc)
    laws, controls = e2c_study.scenario_cells(("poly",))
    jobs: list[tuple[str, dict[str, Any], Any, bool]] = []
    for cell in (*laws, *controls):
        which, spec = cell_spec(cell, model, law_doc)
        jobs.append((cell.key, bases[which], spec, False))
    for a in AMPLITUDES:
        for b in BOUNDS:
            spec = law_spec(law_doc["profiles"]["poly"], amplitude=a, bound=b)
            jobs.append((f"spread|A{a:g}|{b}", bases["law"], spec, True))
    tanh_cells = [
        Cell("law:tanh", d, e2c_study.GATING_A, b) for d in DISPERSION_GRID for b in BOUNDS
    ]
    for cell in tanh_cells:
        which, spec = cell_spec(cell, model, law_doc)
        jobs.append((cell.key, bases[which], spec, False))
    print(f"predict: {len(jobs)} syntheses", flush=True)
    started = time.time()
    summaries: dict[str, e2_metrics.WindowSummary] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, (key, summary) in enumerate(pool.map(_predict_job, jobs, chunksize=4)):
            summaries[key] = summary
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(jobs)} {time.time() - started:.0f} s", flush=True)
    step0_doc = load_yaml(STEP0_PATH)
    misfits = [law_doc["r6"]["poly"][k]["metrics"] for k in ("b2b", "2km")]
    spreads = [law_doc["window_spreads"][k] for k in ("b2b", "2km")]
    basis = e2c_study.basis_of([*misfits, *spreads])
    spread_cells: dict[str, Any] = {}
    limits: dict[tuple[float, str], dict[str, float]] = {}
    for a in AMPLITUDES:
        for b in BOUNDS:
            primary = summaries[Cell("law:poly", 0.0, a, b).key]
            m = e2_metrics.metrics_between(primary, summaries[f"spread|A{a:g}|{b}"])
            limits[(a, b)] = e2c_study.cell_limits(basis, m)
            spread_cells[f"A{a:g}|{b}"] = {
                "spread": metrics_doc(m),
                "limits": limits[(a, b)],
                "spread_binds": e2c_study.spread_binds(basis, m),
            }
    # D11 collapse and S3 (plan I13)
    collapse_rows = {}
    for d in DISPERSION_GRID:
        for b in BOUNDS:
            poly = summaries[Cell("law:poly", d, e2c_study.GATING_A, b).key]
            tanh = summaries[Cell("law:tanh", d, e2c_study.GATING_A, b).key]
            m = e2_metrics.metrics_between(poly, tanh)
            collapse_rows[f"D{d:g}|{b}"] = e2_score.exceedance(m, limits[(e2c_study.GATING_A, b)])
    collapsed = all(v <= e2c_study.COLLAPSE_MAX_PSI for v in collapse_rows.values())
    shapes = ("poly",) if collapsed else ("poly", "tanh")
    s3_rows = {}
    for shape in shapes:
        for d in DISPERSION_GRID:
            for b in BOUNDS:
                law_s = summaries[Cell(f"law:{shape}", d, e2c_study.GATING_A, b).key]
                row = {}
                for control in e2c_study.CONTROLS:
                    ctrl = summaries[Cell(control, d, e2c_study.GATING_A, b).key]
                    row[control] = e2_score.exceedance(
                        e2_metrics.metrics_between(law_s, ctrl), limits[(e2c_study.GATING_A, b)]
                    )
                s3_rows[f"{shape}|D{d:g}|{b}"] = row
    s3_holds = all(v > e2c_study.S3_MIN_PSI for row in s3_rows.values() for v in row.values())
    binds = sum(1 for c in spread_cells.values() if c["spread_binds"])
    result = {
        "basis": basis,
        "basis_inputs": {
            "misfit_b2b": misfits[0],
            "misfit_2km": misfits[1],
            "spread_b2b": spreads[0],
            "spread_2km": spreads[1],
        },
        "spread_cells": spread_cells,
        "spread_term_binds_in_cells": binds,
        "cells": len(spread_cells),
        "d11_collapse_psi": collapse_rows,
        "d11_collapsed": collapsed,
        "shapes_kept": list(shapes),
        "s3_psi": s3_rows,
        "s3_holds": s3_holds,
        "s3_min_psi": min(v for row in s3_rows.values() for v in row.values()),
        "syntheses": len(jobs),
        "compute_seconds": round(time.time() - started, 1),
        "law_model_sha256": sha256_file(LAW_PATH),
        "step0_sha256": sha256_file(STEP0_PATH),
        "viable": step0_doc["viability"]["viable"],
    }
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "predict_summaries.pkl").open("wb") as handle:
        pickle.dump({"summaries": summaries, "limits": limits}, handle)
    (cache / "predict.json").write_text(json.dumps(result, indent=1, sort_keys=True))
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "basis",
                    "spread_term_binds_in_cells",
                    "d11_collapsed",
                    "s3_holds",
                    "s3_min_psi",
                )
            },
            indent=1,
        ),
        flush=True,
    )
    return 0


# ---------------------------------------------------------------------------- power
def _truth_job(
    job: tuple[int, str, np.ndarray, list[Any], dict[str, Any], float, float, list[float]],
) -> list[tuple[str, int, Any]]:
    k, source, x, configs, law_doc, fs, baud, psd = job
    law = e2c_model.law_from_dict(law_doc["law"])
    sigma_rx = float(law_doc["sigma_rx"])
    seed = e2c_study.SEEDS["pseudo_capture_noise"] + k

    def noise(n: int, sigma: float) -> np.ndarray:
        return e2_model.shaped_noise(psd, fs, n, sigma, seed)

    out = []
    for config in configs:
        if config.source != source:
            continue
        outer = None
        if config.field_er_db is not None:
            u = law.inverse(x) / e2c_study.SOURCE_AMPLITUDE[source]
            c, _ = e2_metrics.kmeans_levels(u)
            outer = (float(c[0]), float(c[3]))
        y = e2c_study.pseudo_capture(
            x, config, law=law, sigma_rx=sigma_rx, fs=fs, noise=noise, outer=outer
        )
        out.append((config.key, k, e2_score.window_summary(y, fs, baud)))
    return out


def power(args: argparse.Namespace) -> int:
    cache = Path(args.cache)
    result = json.loads((cache / "predict.json").read_text())
    if not result["s3_holds"]:
        raise Stopped("S3: the law predictions at A 0.45 are not separable from a control")
    law_doc = load_yaml(LAW_PATH)
    if result["law_model_sha256"] != sha256_file(LAW_PATH):
        raise SystemExit("the prediction cache is not from the committed law model")
    with (cache / "predict_summaries.pkl").open("rb") as handle:
        stored = pickle.load(handle)
    model = b2b_model()
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    c0, g0 = float(model["normalisation"]["c0"]), float(model["normalisation"]["g0"])
    laws, controls = e2c_study.scenario_cells(tuple(result["shapes_kept"]))
    bank = e2c_study.stack([*laws, *controls], stored["summaries"], stored["limits"])
    configs = e2c_study.truth_configs()
    started = time.time()
    sources: dict[str, dict[str, np.ndarray]] = {}
    for label, opener in (("b2b", open_b2b_capture), ("2km", open_two_km_capture)):
        capture = opener()
        try:
            sources[label] = e2c_study.read_windows(capture, e2c_study.STUDY_WINDOW_NAMES, c0, g0)
        finally:
            capture.close()
    jobs = [
        (
            k,
            label,
            sources[label][f"study{k}"],
            configs,
            law_doc["profiles"]["poly"],
            fs,
            baud,
            list(model["psd_relative"]),
        )
        for label in ("b2b", "2km")
        for k in range(e2c_study.WINDOW_COUNT)
    ]
    rows: dict[str, dict[int, Any]] = {c.key: {} for c in configs}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for batch in pool.map(_truth_job, jobs):
            for key, k, summary in batch:
                rows[key][k] = e2c_study.score_capture(summary, bank)
            print(f"  batch done {time.time() - started:.0f} s", flush=True)
    table = {}
    for config in configs:
        per = [rows[config.key][k] for k in range(e2c_study.WINDOW_COUNT)]
        tally: dict[str, int] = {}
        for r in per:
            tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
        table[config.key] = {
            "family": config.family,
            "source": config.source,
            "dispersion": config.dispersion,
            "amplitude": config.amplitude,
            "bound": config.bound,
            "role": config.role,
            "outcomes": tally,
            "pass_discriminating": tally.get(e2c_study.OUTCOME_PD, 0),
            "windows": per,
        }
    (cache / "power.json").write_text(
        json.dumps(
            {
                "table": table,
                "compute_seconds": round(time.time() - started, 1),
                "law_model_sha256": result["law_model_sha256"],
            },
            indent=1,
        )
    )
    for key, row in table.items():
        print(f"{key}: {row['outcomes']}", flush=True)
    return 0


# ---------------------------------------------------------------------------- decide
def decide(args: argparse.Namespace) -> int:
    cache = Path(args.cache)
    step0_doc = load_yaml(STEP0_PATH)
    viable = bool(step0_doc["viability"]["viable"])
    law_doc = load_yaml(LAW_PATH) if LAW_PATH.is_file() else None
    invalid = law_doc is not None and not law_doc["acceptance"]["valid"]
    r6 = None if law_doc is None or invalid else bool(law_doc["r6_holds"])
    predicted = (
        json.loads((cache / "predict.json").read_text())
        if (cache / "predict.json").is_file()
        else None
    )
    s3 = None if predicted is None else bool(predicted["s3_holds"])
    powered = (
        json.loads((cache / "power.json").read_text()) if (cache / "power.json").is_file() else None
    )
    r1 = r2 = None
    lines: dict[str, Any] = {}
    reach_value = None
    if powered is not None:
        if law_doc is None or powered["law_model_sha256"] != sha256_file(LAW_PATH):
            raise SystemExit("the power cache is not from the committed law model")
        table = powered["table"]
        r1_counts = {k: v["pass_discriminating"] for k, v in table.items() if v["role"] == "R1"}
        r2_counts = {k: v["pass_discriminating"] for k, v in table.items() if v["role"] == "R2"}
        if len(r1_counts) != 6 or len(r2_counts) != 8:
            raise SystemExit(
                "the gating configurations are not the six R1 and eight R2 of the plan"
            )
        r1, r2 = e2c_study.r1_holds(r1_counts), e2c_study.r2_holds(r2_counts)
        t1 = {
            a: [
                v["pass_discriminating"]
                for v in table.values()
                if v["family"] == "T1"
                and v["source"] == "2km"
                and v["dispersion"] == e2c_study.REACH_D
                and v["amplitude"] == a
            ]
            for a in e2c_study.REACH_AMPLITUDES
        }
        null = {
            a: [
                v["pass_discriminating"]
                for v in table.values()
                if v["family"] in ("T2", "T3")
                and v["dispersion"] == e2c_study.REACH_D
                and v["amplitude"] == a
            ]
            for a in e2c_study.REACH_AMPLITUDES
        }
        reach_value = e2c_study.reach(t1, null)
        lines = {
            "R1": {
                "rule": "each T1 gating configuration PASS, DISCRIMINATING in >= 4 of 5",
                "counts": r1_counts,
                "holds": r1,
            },
            "R2": {
                "rule": "each T2/T3 configuration at A 0.45 <= 1 of 5 and <= 4 of 40 pooled",
                "counts": r2_counts,
                "pooled": sum(r2_counts.values()),
                "holds": r2,
            },
            "R3_reach_A_star": reach_value,
            "R3_preregistered_for_R14": "g_10 above A*: law NOT DISCRIMINATING by construction",
        }
    verdict: dict[str, Any] = e2c_study.decide(step0_viable=viable, r6=r6, s3=s3, r1=r1, r2=r2)
    if invalid:  # amendment A2: an INVALID fit gives no verdict; v1's verdict of record stands
        verdict = {
            "decision": None,
            "a2_status": A2_STATUS_INVALID,
            "failed_checks": law_doc["acceptance"]["failed"] if law_doc else None,
            "stop_condition": None,
            "decision_of_record": "CLOSE_PARTIAL, S2 (v1, power_study_e2c.yaml)",
        }
    elif verdict["stop_condition"] == "S2":
        verdict["a2_status"] = "R6 fails for the corrected poly: CLOSE_PARTIAL at S2 (A2), final"
    else:
        verdict["a2_status"] = "fit VALID"
    document = {
        "power_study_e2c_version": 2,
        "declared": "The E2c power study (design D14, D19; plan). B2B and 2 km only; the 10 km file"
        " was not read."
        " The rule was fixed in STUDY_PLAN.md before any fit and applied here mechanically.",
        **provenance(),
        "inputs": {
            "step0_diagnostics.yaml": sha256_file(STEP0_PATH),
            "law_model_v2.yaml": None if law_doc is None else sha256_file(LAW_PATH),
            "v1 power_study_e2c.yaml": sha256_file(RESULT_PATH_V1),
        },
        "rule_lines": {
            "step0_viable": viable,
            "R6": r6,
            "S3": s3,
            **lines,
        },
        "predictions": predicted,
        "power_table": None
        if powered is None
        else {
            k: {kk: vv for kk, vv in v.items() if kk != "windows"}
            for k, v in powered["table"].items()
        },
        "power_windows": None
        if powered is None
        else {k: v["windows"] for k, v in powered["table"].items()},
        "power_compute_seconds": None if powered is None else powered["compute_seconds"],
        **verdict,
        "ceiling": (
            "VALIDATED is never returned; any later 10 km PASS, DISCRIMINATING is PARTIAL (D15 d)"
        ),
    }
    path = write_once(
        RESULT_PATH,
        dump_yaml(
            document,
            "# E2c power study result, amendment A2 (design D14). B2B and 2 km only.\n",
        ),
    )
    print(
        json.dumps(
            {"decision": verdict, "rule_lines": document["rule_lines"]}, indent=1, default=str
        ),
        flush=True,
    )
    print(f"wrote {path.relative_to(ROOT)}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("step0", "fit", "predict", "power", "decide"))
    parser.add_argument("--cache", default=str(ROOT / "build/e2c_cache_v2"))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()
    steps = {"step0": step0, "fit": fit, "predict": predict, "power": power, "decide": decide}
    try:
        return steps[args.step](args)
    except Stopped as stop:
        print(f"STOPPED: {stop}", file=sys.stderr)
        return 3
    except e2c_calibration.BenchmarkError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
