"""Scoring entry point for the TERIPHIC holdouts (Stage 3A, gate E2 part a).

`score_holdout` is the only code in `src` that reads a sample of the 2 km or 10 km capture (plan
Revision 10, R10.1; a source scan in the tests keeps it so). It does, in this order, and refuses at
the first failure:

1. name the file: the registered name of the resolved path must be a `VALIDATION` or `LOCKED_TEST`
   asset; nothing is opened, hashed or read yet;
2. `require_frozen_criterion`, before any other step: no frozen, unchanged, committed criterion
   and inputs, no scoring. This is the E2 obligation of plan R9.1 as code;
3. the committed model, scenario list and pre-registration must agree with each other and with the
   inputs the guard hashed, and the working-tree bytes of the listed code files must equal the code
   identity recorded in the model document (a narrow identity: those files only, see R10.4);
4. the holdout's MD5 and SHA-256 are checked against the recorded values at read time;
5. only then the header and a fixed window of samples are read, through `ExternalCapture`, and the
   four metrics of `e2_metrics` are computed for every listed scenario and for the B2B copy.

The comparator is the B2B copy: the B2B window at the same sample indices, scored against the
holdout with the same frozen limits. A result reads `PASS, DISCRIMINATING` only if the chosen
fibre scenario is within every limit and the B2B copy is not; if both are within the limits, or the
chosen scenario is the no-fibre control, it reads `PASS, NOT DISCRIMINATING`; otherwise `FAIL`.

Never computed here: BER, SER, post-FEC BER (REFERENCE_SEQUENCE_MISSING) or any proxy of them.
No instrument serial and no fibre value that is not a recorded source or a declared scenario.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.benchmarks import e2_model, teriphic
from opticps.benchmarks.catalog import load_strict_yaml
from opticps.benchmarks.e2_metrics import (
    QUANTILE_POINTS,
    kmeans_levels,
    level_gaps,
    metrics_between,
    normalise,
    require_window,
    summarise_window,
    welch_density,
)
from opticps.benchmarks.external_capture import ExternalCapture
from opticps.benchmarks.holdout import (
    DEFAULT_PLAN,
    HOLDOUT_SPLITS,
    METRICS,
    HoldoutState,
    SequenceCheck,
    ValidationStage,
    Verdict,
    _blob,
    _committed_bytes,
    _git,
    _git_ok,
    allowed_verdicts,
    require_frozen_criterion,
)
from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    ErrorCode,
    Md5State,
    SourceRecord,
    Split,
    verify_local_asset,
)

FloatArray = NDArray[np.float64]

E2_DIR = Path("docs/benchmarks/teriphic_e2")
MODEL_PATH = E2_DIR / "b2b_model.yaml"
SCENARIO_PATH = E2_DIR / "scenario_list.yaml"
PREREGISTRATION_PATH = E2_DIR / "preregistered_predictions.yaml"
SELECTED_PATH = E2_DIR / "selected_scenario.yaml"  # written by E2b after the 2 km stage
EVALUATION_SCRIPT = Path("scripts/score_teriphic_e2.py")
LENGTH_KM = {
    "50G_PAM4_PD1_2km_Subassembly1.bin": 2.0,
    "50G_PAM4_PD1_10km_Subassembly1.bin": 10.0,
}
# Files whose bytes are the code identity of E2 (plan R10.4). Narrow: only these, as committed.
CODE_IDENTITY_FILES = (
    "src/opticps/benchmarks/e2_metrics.py",
    "src/opticps/benchmarks/e2_model.py",
    "src/opticps/benchmarks/e2_score.py",
    "src/opticps/benchmarks/holdout.py",
    "src/opticps/benchmarks/external_capture.py",
    "src/opticps/benchmarks/teriphic.py",
    "src/opticps/benchmarks/provenance.py",
)
MODEL_VERSION = 1
SCENARIO_VERSION = 1
PREREGISTRATION_VERSION = 1
REPRODUCTION_RTOL = 1e-6
REPRODUCTION_ATOL = 1e-9
SAMPLE_RATE_RTOL = 1e-6
OUTCOME_FAIL = "FAIL"
OUTCOME_PASS_NOT_DISCRIMINATING = "PASS, NOT DISCRIMINATING"
OUTCOME_PASS_DISCRIMINATING = "PASS, DISCRIMINATING"
OUTCOME_BLOCKED = "BLOCKED"
BER_STATUS = "REFERENCE_SEQUENCE_MISSING"


# ---------------------------------------------------------------------------- documents
def _positive(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise BenchmarkError(f"{where} must be finite and positive")
    return number


def _non_negative(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise BenchmarkError(f"{where} must be finite and not negative")
    return number


def _integer(value: object, where: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BenchmarkError(f"{where} must be an integer of at least {minimum}")
    return value


def _mapping(value: object, where: str, keys: set[str] | frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise BenchmarkError(f"{where} must have exactly the keys {sorted(keys)}")
    return value


def _parse(data: bytes, name: str) -> dict[str, Any]:
    try:
        document = load_strict_yaml(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BenchmarkError(f"{name}: cannot be read as strict YAML: {error}") from error
    if not isinstance(document, dict):
        raise BenchmarkError(f"{name}: must be a mapping")
    return document


MODEL_KEYS = frozenset(
    {
        "model_version", "sample_rate_hz", "baud_bd", "pulse_samples", "psd_relative",
        "level_probabilities", "pulse_levels", "noise_sigma", "b2b_centroids_normalised",
        "b2b_cluster_shares", "b2b_std_normalised", "fit", "normalisation", "windows", "seeds",
        "parameters", "model_gaps", "assumptions", "code_identity",
    }
)  # fmt: skip
WINDOW_KEYS = frozenset({"fit", "spread", "evaluation"})
SEED_KEYS = frozenset({"fit", "prediction_symbols", "prediction_noise"})


def check_model(model: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the committed B2B model document; return it as a plain dict. Default-deny."""
    document = _mapping(dict(model), "b2b model", MODEL_KEYS)
    if document["model_version"] != MODEL_VERSION or type(document["model_version"]) is not int:
        raise BenchmarkError(f"b2b model: model_version must be {MODEL_VERSION}")
    _positive(document["sample_rate_hz"], "b2b model sample_rate_hz")
    _positive(document["baud_bd"], "b2b model baud_bd")
    _integer(document["pulse_samples"], "b2b model pulse_samples", minimum=64)
    for name, size in (
        ("psd_relative", 2049), ("level_probabilities", 4), ("pulse_levels", 4),
        ("b2b_centroids_normalised", 4), ("b2b_cluster_shares", 4),
    ):  # fmt: skip
        values = document[name]
        if not isinstance(values, list) or len(values) != size:
            raise BenchmarkError(f"b2b model: {name} must be a list of {size} numbers")
        for item in values:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise BenchmarkError(f"b2b model: {name} must hold numbers")
            if not math.isfinite(float(item)):
                raise BenchmarkError(f"b2b model: {name} must be finite")
    _non_negative(document["noise_sigma"], "b2b model noise_sigma")
    _positive(document["b2b_std_normalised"], "b2b model b2b_std_normalised")
    norm = _mapping(document["normalisation"], "b2b model normalisation", {"c0", "g0", "units"})
    if not math.isfinite(float(norm["c0"])):
        raise BenchmarkError("b2b model: normalisation c0 must be finite")
    _positive(norm["g0"], "b2b model normalisation g0")
    windows = _mapping(document["windows"], "b2b model windows", WINDOW_KEYS)
    for key, window in windows.items():
        entry = _mapping(window, f"b2b model window {key}", {"start", "samples"})
        _integer(entry["start"], f"window {key} start")
        _integer(entry["samples"], f"window {key} samples", minimum=32768)
    seeds = _mapping(document["seeds"], "b2b model seeds", SEED_KEYS)
    for key, seed in seeds.items():
        _integer(seed, f"seed {key}")
    identity = document["code_identity"]
    if not isinstance(identity, dict) or set(identity) != set(CODE_IDENTITY_FILES):
        raise BenchmarkError(
            f"b2b model: code_identity must list exactly {list(CODE_IDENTITY_FILES)}"
        )
    for path, digest in identity.items():
        if not isinstance(digest, str) or len(digest) != 64:
            raise BenchmarkError(f"b2b model: code_identity {path} must be a SHA-256")
    for key in ("model_gaps", "assumptions"):
        if not isinstance(document[key], list) or not document[key]:
            raise BenchmarkError(f"b2b model: {key} must be a non-empty list (declared, not empty)")
    if not isinstance(document["parameters"], dict) or not document["parameters"]:
        raise BenchmarkError("b2b model: parameters (with provenance) must be declared")
    return document


@dataclass(frozen=True)
class Scenario:
    """One pre-listed fibre scenario. A scenario is a hypothesis, never ground truth."""

    scenario_id: str
    dispersion_ps_nm_km: float
    attenuation_db_per_km: float
    noise_follows_signal: bool
    null_control: bool
    label: str

    def amplitude_ratio(self, length_km: float) -> float:
        return e2_model.loss_amplitude_ratio(self.attenuation_db_per_km, length_km)


SCENARIO_KEYS = frozenset({"scenario_list_version", "count", "scenarios", "provenance"})
SCENARIO_ENTRY_KEYS = frozenset(
    {
        "id",
        "dispersion_ps_nm_km",
        "attenuation_db_per_km",
        "noise_follows_signal",
        "null_control",
        "label",
    }
)


def check_scenarios(document: Mapping[str, Any]) -> tuple[Scenario, ...]:
    body = _mapping(dict(document), "scenario list", SCENARIO_KEYS)
    if type(body["scenario_list_version"]) is not int or body["scenario_list_version"] != (
        SCENARIO_VERSION
    ):
        raise BenchmarkError(f"scenario list: scenario_list_version must be {SCENARIO_VERSION}")
    entries = body["scenarios"]
    if not isinstance(entries, list) or not entries:
        raise BenchmarkError("scenario list: scenarios must be a non-empty list")
    if body["count"] != len(entries) or type(body["count"]) is not int:
        raise BenchmarkError("scenario list: count must equal the number of scenarios")
    scenarios: list[Scenario] = []
    for index, raw in enumerate(entries):
        entry = _mapping(raw, f"scenario {index}", SCENARIO_ENTRY_KEYS)
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier.strip():
            raise BenchmarkError(f"scenario {index}: id must be a non-empty string")
        if identifier in {s.scenario_id for s in scenarios}:
            raise BenchmarkError(f"scenario list: duplicate id {identifier!r}")
        for flag in ("null_control", "noise_follows_signal"):
            if type(entry[flag]) is not bool:
                raise BenchmarkError(f"scenario {identifier}: {flag} must be true or false")
        scenarios.append(
            Scenario(
                identifier,
                _non_negative(entry["dispersion_ps_nm_km"], f"{identifier} dispersion"),
                _non_negative(entry["attenuation_db_per_km"], f"{identifier} attenuation"),
                entry["noise_follows_signal"],
                entry["null_control"],
                str(entry["label"]),
            )
        )
    if sum(s.null_control for s in scenarios) != 1:
        raise BenchmarkError("scenario list: exactly one scenario must be the no-fibre control")
    return tuple(scenarios)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_identity(root: Path) -> dict[str, str]:
    """SHA-256 of each file of `CODE_IDENTITY_FILES` as it is in the working tree under `root`."""
    table: dict[str, str] = {}
    for relative in CODE_IDENTITY_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise BenchmarkError(f"code identity: {relative} is missing or a symbolic link")
        table[relative] = sha256_of(path.read_bytes())
    return table


def verify_code_identity(model: Mapping[str, Any], root: Path) -> None:
    """Refuse when the working code differs from the identity recorded in the model document."""
    recorded = model["code_identity"]
    actual = code_identity(root)
    changed = sorted(p for p in actual if actual[p] != recorded[p])
    if changed:
        raise BenchmarkError(
            f"code identity: {', '.join(changed)} differ from the frozen identity in the model"
        )


# ---------------------------------------------------------------------------- prediction
def predict(
    model: Mapping[str, Any], scenario: Scenario, length_km: float, n_samples: int
) -> FloatArray:
    """The predicted normalised window for one scenario and length, from the seeds in the model."""
    seeds = model["seeds"]
    return e2_model.synthesize(
        model,
        n_samples=n_samples,
        symbol_seed=seeds["prediction_symbols"],
        noise_seed=seeds["prediction_noise"],
        dispersion_ps_nm_km=scenario.dispersion_ps_nm_km,
        length_km=length_km,
        amplitude_ratio=scenario.amplitude_ratio(length_km),
        noise_follows_signal=scenario.noise_follows_signal,
    )


def summarise(window: FloatArray, sample_rate_hz: float, baud_bd: float) -> dict[str, Any]:
    """Descriptive values of a predicted window that the pre-registration records."""
    centroids, shares = kmeans_levels(window)
    frequency, density = welch_density(window, sample_rate_hz)
    keep = frequency <= baud_bd * (1.0 + 1e-9)
    edges = np.linspace(0.0, baud_bd, 11)
    bands = []
    peak = float(density[keep].max())
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        mask = keep & (frequency >= low) & (frequency < high + (1e-9 if high == edges[-1] else 0))
        bands.append(float(10.0 * np.log10(density[mask].mean() / peak)))
    return {
        "centroids": [float(v) for v in centroids],
        "gaps": [float(v) for v in level_gaps(centroids)],
        "cluster_shares": [float(v) for v in shares],
        "std": float(window.std()),
        "quantiles": {
            repr(p): float(v)
            for p, v in zip(QUANTILE_POINTS, np.quantile(window, QUANTILE_POINTS), strict=True)
        },
        "psd_db_by_5ghz_band_rel_peak": bands,
    }


def exceedance(metrics: Mapping[str, float], limits: Mapping[str, float]) -> float:
    """psi: the largest ratio of a metric to its limit (psi <= 1 is within the criterion)."""
    ratios = []
    for name in METRICS:
        value = metrics[name]
        if not math.isfinite(value) or value < 0:
            raise BenchmarkError(f"metric {name} is not a finite non-negative number")
        ratios.append(value / limits[name])
    return max(ratios)


# ---------------------------------------------------------------------------- scoring core
@dataclass(frozen=True)
class WindowScore:
    outcome: str
    verdict: Verdict | None
    selected: str | None
    scenarios: dict[str, dict[str, Any]]
    comparator: dict[str, Any]
    within_criterion: bool
    comparator_within_criterion: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def score_windows(
    measured: FloatArray,
    comparator: FloatArray,
    *,
    model: Mapping[str, Any],
    scenarios: tuple[Scenario, ...],
    limits: Mapping[str, float],
    length_km: float,
    split: Split,
    fixed_scenario: str | None = None,
    validation_stage: ValidationStage | None = None,
    sequence_check: SequenceCheck | None = None,
    state: HoldoutState | None = None,
    identifiable_in_principle: bool = False,
) -> WindowScore:
    """Score one measured normalised window against the scenarios and the B2B copy.

    `measured` and `comparator` must already carry the one B2B normalisation. A non-finite or too
    short window is refused. For the 2 km selection stage every scenario is scored and the one
    with the smallest psi is chosen (ties go to the earlier in the list); for the locked test
    `fixed_scenario` names the already chosen scenario and only it is scored.
    """
    if split not in HOLDOUT_SPLITS:
        raise BenchmarkError(f"{split.value} is not a holdout role")
    if set(limits) != set(METRICS):
        raise BenchmarkError(f"limits must be exactly {list(METRICS)}")
    for name in METRICS:
        _positive(limits[name], f"limit {name}")
    n_samples = int(model["windows"]["evaluation"]["samples"])
    measured = require_window(measured, "measured window")
    comparator = require_window(comparator, "B2B copy window")
    if measured.size != n_samples or comparator.size != n_samples:
        raise BenchmarkError(f"windows must have exactly {n_samples} samples")
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    if split is Split.LOCKED_TEST:
        if fixed_scenario is None:
            raise BenchmarkError("the locked test needs the scenario chosen at the 2 km stage")
        chosen = [s for s in scenarios if s.scenario_id == fixed_scenario]
        if len(chosen) != 1:
            raise BenchmarkError(f"scenario {fixed_scenario!r} is not in the scenario list")
        controls = [s for s in scenarios if s.null_control and s.scenario_id != fixed_scenario]
        scored = (*chosen, *controls)  # the no-fibre control is scored too, as a reference
    else:
        if fixed_scenario is not None:
            raise BenchmarkError("the 2 km stage selects its own scenario; none may be fixed")
        scored = scenarios
    table: dict[str, dict[str, Any]] = {}
    measured_summary = summarise_window(measured, fs, baud)
    for scenario in scored:
        predicted = predict(model, scenario, length_km, n_samples)
        metrics = metrics_between(measured_summary, summarise_window(predicted, fs, baud))
        table[scenario.scenario_id] = {
            "metrics": metrics,
            "psi": exceedance(metrics, limits),
            "null_control": scenario.null_control,
        }
    if fixed_scenario is not None:
        selected = fixed_scenario
    else:
        selected = min(table, key=lambda key: (table[key]["psi"], list(table).index(key)))
    null_id = next(s.scenario_id for s in scenarios if s.null_control)
    copy_metrics = metrics_between(measured_summary, summarise_window(comparator, fs, baud))
    copy_psi = exceedance(copy_metrics, limits)
    chosen_entry = table[selected]
    model_ok = bool(chosen_entry["psi"] <= 1.0)
    copy_ok = bool(copy_psi <= 1.0)
    notes: list[str] = []
    if not model_ok:
        outcome = OUTCOME_FAIL
    elif copy_ok or chosen_entry["null_control"] or table[null_id]["psi"] <= 1.0:
        outcome = OUTCOME_PASS_NOT_DISCRIMINATING
        if copy_ok:
            notes.append("the B2B copy is also within every limit")
        if chosen_entry["null_control"]:
            notes.append("the chosen scenario is the no-fibre control")
        elif table[null_id]["psi"] <= 1.0:
            notes.append("the no-fibre control scenario is also within every limit")
    else:
        outcome = OUTCOME_PASS_DISCRIMINATING
    allowed = allowed_verdicts(
        split, validation_stage=validation_stage, sequence_check=sequence_check, state=state
    )
    verdict: Verdict | None
    if outcome == OUTCOME_FAIL:
        verdict = Verdict.FAILED
    elif outcome == OUTCOME_PASS_NOT_DISCRIMINATING:
        verdict = (
            Verdict.INCONCLUSIVE if identifiable_in_principle else Verdict.UNIDENTIFIABLE_PARAMETER
        )
    elif split is Split.VALIDATION:
        verdict = None  # plan R.5: within criterion at the selection stage, no verdict
        notes.append("within criterion at the selection stage; the 2 km file cannot be VALIDATED")
    else:
        verdict = Verdict.VALIDATED if Verdict.VALIDATED in allowed else Verdict.INCONCLUSIVE
    if verdict is not None and verdict not in allowed:
        verdict = Verdict.INCONCLUSIVE
    return WindowScore(
        outcome,
        verdict,
        selected,
        table,
        {"metrics": copy_metrics, "psi": copy_psi},
        model_ok,
        copy_ok,
        tuple(notes),
    )


# ---------------------------------------------------------------------------- pre-registration
def compute_preregistration(
    model: Mapping[str, Any],
    scenarios: tuple[Scenario, ...],
    comparator: FloatArray,
    limits: Mapping[str, float],
    lengths_km: tuple[float, ...],
) -> dict[str, Any]:
    """Predicted values for every length and scenario from B2B and code alone.

    `comparator` is the B2B window at the evaluation indices. For each scenario, the separation is
    the four metrics between the scenario's prediction and the B2B copy; if even a perfect model of
    that scenario would stay within every limit of the B2B copy, the criterion cannot tell that
    scenario from no fibre (`separable` false). Nothing here reads a holdout.
    """
    n_samples = int(model["windows"]["evaluation"]["samples"])
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    comparator = require_window(comparator, "B2B copy window")
    predictions: dict[str, Any] = {}
    identifiable: dict[str, bool] = {}
    copy_summary = summarise_window(comparator, fs, baud)
    for length in lengths_km:
        per_scenario: dict[str, Any] = {}
        for scenario in scenarios:
            window = predict(model, scenario, length, n_samples)
            separation = metrics_between(copy_summary, summarise_window(window, fs, baud))
            psi = exceedance(separation, limits)
            per_scenario[scenario.scenario_id] = {
                "summary": summarise(window, fs, baud),
                "separation_from_b2b_copy": separation,
                "separation_psi": psi,
                "separable": bool(psi > 1.0) and not scenario.null_control,
            }
        key = f"{length:g}"
        predictions[key] = per_scenario
        identifiable[key] = any(v["separable"] for v in per_scenario.values())
    return {"predictions": predictions, "identifiable_in_principle": identifiable}


def _flatten(value: Any, prefix: str = "") -> dict[str, float | bool]:
    out: dict[str, float | bool] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.update(_flatten(item, f"{prefix}[{index}]"))
    elif isinstance(value, bool) or isinstance(value, (int, float)):
        out[prefix] = value
    return out


def check_reproduction(recorded: Mapping[str, Any], recomputed: Mapping[str, Any]) -> None:
    """Refuse when the recomputed prediction differs from the pre-registered one."""
    a, b = _flatten(recorded), _flatten(recomputed)
    if set(a) != set(b):
        raise BenchmarkError("pre-registered predictions: the recomputed keys differ")
    for key in sorted(a):
        x, y = a[key], b[key]
        if isinstance(x, bool) or isinstance(y, bool):
            if x is not y:
                raise BenchmarkError(f"pre-registered predictions: {key} changed ({x} vs {y})")
        elif not math.isclose(
            float(x), float(y), rel_tol=REPRODUCTION_RTOL, abs_tol=REPRODUCTION_ATOL
        ):
            raise BenchmarkError(
                f"pre-registered predictions: {key} is {y!r} now, {x!r} when registered"
            )


# ---------------------------------------------------------------------------- entry point
@dataclass(frozen=True)
class E2Result:
    filename: str
    length_km: float
    split: str
    outcome: str
    verdict: str | None
    selected_scenario: str | None
    scenarios_scored: int
    scenarios: dict[str, dict[str, Any]]
    b2b_copy: dict[str, Any]
    limits: dict[str, float]
    criterion_commit: str
    head_commit: str
    identifiable_in_principle: bool
    model_gaps: tuple[str, ...]
    assumptions: tuple[str, ...]
    notes: tuple[str, ...]
    hashes_verified: bool
    ber_status: str = BER_STATUS
    fibre_knowledge: Mapping[str, str] = field(
        default_factory=lambda: {
            "fibre_type": "UNKNOWN",
            "wavelength": "UNKNOWN (O-band only)",
            "dispersion": "scenarios only (ASSUMED_G652D), not ground truth",
            "loss_and_launch_power": "UNKNOWN; amplitude ratio is a scenario",
            "chirp": "UNKNOWN; MODEL GAP: CHIRP, scenarios assume zero",
        }
    )

    def report(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "length_km": self.length_km,
            "split": self.split,
            "outcome": self.outcome,
            "verdict": self.verdict,
            "selected_scenario": self.selected_scenario,
            "scenarios_scored": self.scenarios_scored,
            "scenarios": self.scenarios,
            "b2b_copy": self.b2b_copy,
            "limits": self.limits,
            "criterion_commit": self.criterion_commit,
            "head_commit": self.head_commit,
            "identifiable_in_principle": self.identifiable_in_principle,
            "model_gaps": list(self.model_gaps),
            "assumptions": list(self.assumptions),
            "notes": list(self.notes),
            "hashes_verified": self.hashes_verified,
            "reference_sequence": self.ber_status,
            "fibre_knowledge": dict(self.fibre_knowledge),
        }


def bind_to_freeze(root: Path, frozen: Any) -> None:
    """Refuse unless every file the result depends on equals what the freeze commit held.

    `require_frozen_criterion` proves the criterion and the named inputs are committed and
    unchanged since `HEAD`; it does not prove they are what existed at the freeze, so a model, a
    pre-registration and a code-identity table could be replaced together after it. This reads each
    file at `frozen.commit` and compares it with the committed bytes at `HEAD`: model, scenario
    list, pre-registration, evaluation script and every file of `CODE_IDENTITY_FILES`. The freeze
    commit must be an ancestor of `HEAD`.
    """
    if _git(root, "merge-base", "--is-ancestor", frozen.commit, "HEAD").returncode != 0:
        raise BenchmarkError("the freeze commit is not an ancestor of HEAD")
    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)
    for relative in (*paths, *map(Path, CODE_IDENTITY_FILES)):
        now, _ = _committed_bytes(root, root / relative, "frozen file")
        then = _blob(root, frozen.commit, relative.as_posix())
        if then is None:
            raise BenchmarkError(f"{relative.as_posix()}: did not exist at the freeze commit")
        if then != now:
            raise BenchmarkError(f"{relative.as_posix()}: changed since the freeze commit")


def read_selected_scenario(root: Path, frozen: Any) -> str:
    """The scenario chosen at the 2 km stage: added once after the freeze and never changed."""
    relative = SELECTED_PATH.as_posix()
    if _blob(root, frozen.commit, relative) is not None:
        raise BenchmarkError("selected scenario: already present at the freeze commit")
    log = _git_ok(root, "log", "--full-history", "--format=%H", "--", relative)
    commits = log.decode("ascii").split()
    if len(commits) != 1:
        raise BenchmarkError(f"selected scenario: added once, never changed, found {len(commits)}")
    added = commits[0]
    if (
        added == frozen.commit
        or _git(root, "merge-base", "--is-ancestor", frozen.commit, added).returncode != 0
    ):
        raise BenchmarkError("selected scenario: not added after the freeze commit")
    now, _ = _committed_bytes(root, root / SELECTED_PATH, "selected scenario")
    if _blob(root, added, relative) != now:
        raise BenchmarkError("selected scenario: changed since it was added")
    chosen = _mapping(
        _parse(now, "selected scenario"), "selected scenario", {"scenario_id", "selected_at_stage"}
    )
    if not isinstance(chosen["scenario_id"], str):
        raise BenchmarkError("selected scenario: scenario_id must be a string")
    return str(chosen["scenario_id"])


def _holdout_asset(path: Path, source: SourceRecord) -> AssetRecord:
    name = teriphic.fold_name(Path(path).resolve().name)
    for asset in source.assets:
        if teriphic.fold_name(asset.filename) == name and asset.split in HOLDOUT_SPLITS:
            return asset
    raise BenchmarkError(
        f"{Path(path).name} is not a registered 2 km or 10 km holdout; scoring refused",
        ErrorCode.LEAKAGE_DETECTED,
    )


def _inputs(asset: AssetRecord, root: Path) -> dict[str, Path]:
    if asset.split is Split.VALIDATION:
        return {"b2b_model": root / MODEL_PATH, "scenario_list": root / SCENARIO_PATH}
    return {
        "frozen_parameters": root / MODEL_PATH,
        "selected_scenario": root / SELECTED_PATH,
        "evaluation_script": root / EVALUATION_SCRIPT,
    }


def score_holdout(
    holdout_path: Path,
    *,
    b2b_path: Path,
    repo_root: Path = Path("."),
    validation_stage: ValidationStage | None = None,
    sequence_check: SequenceCheck | None = None,
    state: HoldoutState | None = None,
    source: SourceRecord | None = None,
    holdout_sha256: Mapping[str, str] | None = None,
) -> E2Result:
    """Score one holdout against the frozen criterion. The only holdout reader in `src`.

    `source` and `holdout_sha256` default to the register and the recorded hashes; they are
    injectable for tests, which must never touch a real holdout. Every refusal is a
    `BenchmarkError` and happens before the holdout's header or any sample is read.
    """
    root = Path(repo_root)
    holdout_path = Path(holdout_path)
    source = source or teriphic.load_config(root / teriphic.CONFIG_PATH)
    asset = _holdout_asset(holdout_path, source)
    # (2) the E2 obligation of plan R9.1: no statistic, no header, not even a hash, before this.
    frozen = require_frozen_criterion(
        asset,
        plan_path=root / DEFAULT_PLAN,
        repo_root=root,
        inputs=_inputs(asset, root),
        validation_stage=validation_stage,
    )
    if frozen is None:
        raise BenchmarkError(f"{asset.filename}: no frozen criterion was issued")
    bind_to_freeze(root, frozen)
    # (3) committed documents, agreeing with each other and with the guard's hashes.
    model_bytes, _ = _committed_bytes(root, root / MODEL_PATH, "b2b model")
    scenario_bytes, _ = _committed_bytes(root, root / SCENARIO_PATH, "scenario list")
    registration_bytes, _ = _committed_bytes(
        root, root / PREREGISTRATION_PATH, "preregistered predictions"
    )
    model_key = "b2b_model" if asset.split is Split.VALIDATION else "frozen_parameters"
    if sha256_of(model_bytes) != frozen.inputs[model_key]:
        raise BenchmarkError("b2b model: bytes differ from the input the guard hashed")
    if (
        asset.split is Split.VALIDATION
        and sha256_of(scenario_bytes) != frozen.inputs["scenario_list"]
    ):
        raise BenchmarkError("scenario list: bytes differ from the input the guard hashed")
    model = check_model(_parse(model_bytes, "b2b model"))
    scenarios = check_scenarios(_parse(scenario_bytes, "scenario list"))
    registration = _parse(registration_bytes, "preregistered predictions")
    if (
        registration.get("preregistration_version") != PREREGISTRATION_VERSION
        or registration.get("model_sha256") != sha256_of(model_bytes)
        or registration.get("scenario_list_sha256") != sha256_of(scenario_bytes)
    ):
        raise BenchmarkError("preregistered predictions: not tied to this model and scenario list")
    if registration.get("results") is not None:
        raise BenchmarkError("preregistered predictions: a result column is filled")
    verify_code_identity(model, root)
    limits = {name: float(frozen.limits[name]) for name in METRICS}
    check_registered_limits(registration, scenarios, limits)
    selected: str | None = None
    if asset.split is Split.LOCKED_TEST:
        selected = read_selected_scenario(root, frozen)
    # (4) hashes at read time.
    table = teriphic.HOLDOUT_SHA256 if holdout_sha256 is None else holdout_sha256
    expected_sha = table.get(asset.filename)
    if expected_sha is None:
        raise BenchmarkError(f"{asset.filename}: no recorded SHA-256, refusing to read")
    checksum = verify_local_asset(holdout_path, asset.checksum.md5_supplied)
    if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:
        raise BenchmarkError(
            f"{asset.filename}: the file's MD5 or SHA-256 does not match the recorded values;"
            " not read",
            ErrorCode.LEAKAGE_DETECTED,
        )
    gate = teriphic.gate_sample_read(b2b_path, source, holdout_sha256=table)
    if not gate.is_b2b:
        raise BenchmarkError("the comparator file is not the B2B capture (MD5 differs); refused")
    # (5) read, at last.
    window = model["windows"]["evaluation"]
    start, count = int(window["start"]), int(window["samples"])
    norm = model["normalisation"]
    fs = float(model["sample_rate_hz"])
    notes: list[str] = []
    measured_capture = ExternalCapture.open_keysight_bin(holdout_path, checksum=checksum)
    b2b_capture: ExternalCapture | None = None
    try:
        b2b_capture = ExternalCapture.open_keysight_bin(b2b_path, checksum=gate.checksum)
        for label, capture in (("holdout", measured_capture), ("B2B", b2b_capture)):
            increment = capture.layout.x_increment_s
            if increment is None or not math.isclose(1.0 / increment, fs, rel_tol=SAMPLE_RATE_RTOL):
                return _blocked(
                    asset, frozen, model, f"{label} header sample rate differs from the B2B model"
                )
            if capture.count < start + count:
                return _blocked(asset, frozen, model, f"{label} record is shorter than the window")
        measured = normalise(
            measured_capture.read(start, start + count), float(norm["c0"]), float(norm["g0"])
        )
        comparator = normalise(
            b2b_capture.read(start, start + count), float(norm["c0"]), float(norm["g0"])
        )
    finally:
        measured_capture.close()
        if b2b_capture is not None:
            b2b_capture.close()
    length = LENGTH_KM[asset.filename]
    recomputed = compute_preregistration(model, scenarios, comparator, limits, (2.0, 10.0))
    check_reproduction(
        {k: registration[k] for k in ("predictions", "identifiable_in_principle")}, recomputed
    )
    scored = score_windows(
        measured,
        comparator,
        model=model,
        scenarios=scenarios,
        limits=limits,
        length_km=length,
        split=asset.split,
        fixed_scenario=selected,
        validation_stage=validation_stage,
        sequence_check=sequence_check,
        state=state,
        identifiable_in_principle=bool(recomputed["identifiable_in_principle"][f"{length:g}"]),
    )
    return E2Result(
        filename=asset.filename,
        length_km=length,
        split=asset.split.value,
        outcome=scored.outcome,
        verdict=scored.verdict.value if scored.verdict else None,
        selected_scenario=scored.selected,
        scenarios_scored=len(scored.scenarios),
        scenarios=scored.scenarios,
        b2b_copy=scored.comparator,
        limits=limits,
        criterion_commit=frozen.commit,
        head_commit=frozen.head_commit,
        identifiable_in_principle=bool(recomputed["identifiable_in_principle"][f"{length:g}"]),
        model_gaps=tuple(str(x) for x in model["model_gaps"]),
        assumptions=tuple(str(x) for x in model["assumptions"]),
        notes=(*notes, *scored.notes),
        hashes_verified=True,
    )


def check_registered_limits(
    registration: Mapping[str, Any], scenarios: tuple[Scenario, ...], limits: Mapping[str, float]
) -> None:
    """The limits recorded with the pre-registration must equal the frozen ones."""
    recorded = registration.get("limits")
    if not isinstance(recorded, dict) or set(recorded) != set(METRICS):
        raise BenchmarkError("preregistered predictions: limits are missing")
    for name in METRICS:
        if not math.isclose(float(recorded[name]), limits[name], rel_tol=1e-9):
            raise BenchmarkError(f"preregistered predictions: limit {name} differs from the frozen")
    if len(scenarios) != int(registration.get("scenario_count", -1)):
        raise BenchmarkError("preregistered predictions: the scenario count differs")


def _blocked(asset: AssetRecord, frozen: Any, model: Mapping[str, Any], reason: str) -> E2Result:
    return E2Result(
        filename=asset.filename,
        length_km=LENGTH_KM[asset.filename],
        split=asset.split.value,
        outcome=OUTCOME_BLOCKED,
        verdict=Verdict.BLOCKED.value,
        selected_scenario=None,
        scenarios_scored=0,
        scenarios={},
        b2b_copy={},
        limits={name: float(frozen.limits[name]) for name in METRICS},
        criterion_commit=frozen.commit,
        head_commit=frozen.head_commit,
        identifiable_in_principle=False,
        model_gaps=tuple(str(x) for x in model["model_gaps"]),
        assumptions=tuple(str(x) for x in model["assumptions"]),
        notes=(reason,),
        hashes_verified=True,
    )
