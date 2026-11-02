"""Scoring entry point for the TERIPHIC holdouts (Stage 3A, gate E2 part a, plan Revision 12).

`score_holdout` is the only code in `src` that reads a sample of the 2 km or 10 km capture (plan
R10.1, R12.1; a source scan in the tests keeps it so). It does, in this order, and refuses at the
first failure. Every refusal in steps 1 to 5 happens before the holdout is hashed, opened or read
(a test records the order of the file events):

1. name the file: the registered name of the resolved path fixes its role in code (2 km is
   `VALIDATION`, 10 km is `LOCKED_TEST`); a register that says otherwise is refused;
2. `require_frozen_criterion`, before any other step (the E2 obligation of plan R9.1 as code);
3. the freeze commit found must equal `expected_freeze_commit`, which the caller pins outside the
   repository, and must be the first commit on the first-parent history that holds the criterion;
4. the working code must be the code that is loaded, and every file the result depends on (model,
   scenario list, pre-registration, evaluation script, role register, code files) must equal its
   bytes at the freeze commit; the 10 km stage also needs `selected_scenario.yaml`, added once;
5. the B2B comparator is read through its gate, the pre-registered predictions are recomputed and
   must reproduce, and the carried scenario ids must be listed;
6. the holdout's MD5 and SHA-256 are checked against the recorded values at read time;
7. only then the header and a fixed window of samples are read, through `ExternalCapture`.

Scoring (plan R12.3): every window, measured, predicted and the B2B copy, is put through the same
gain-invariant map from its own four level centroids, and the amplitude ratio is reported, not
tested. The four metrics of `e2_metrics` are scored against the frozen limits for each listed
scenario (all at 2 km, the carried ones at 10 km) and for the B2B copy. A result reads
`PASS, DISCRIMINATING` only if some non-control scenario is within every limit while the B2B copy
and the no-fibre control are not; `PASS, NOT DISCRIMINATING` if one of them is also within the
limits; otherwise `FAIL`. Even `PASS, DISCRIMINATING` is capped: the claim is `PARTIAL` and
`VALIDATED` is never returned, because an unmodelled low-pass passes (power study, R12.4).

Never computed here: BER, SER, post-FEC BER (REFERENCE_SEQUENCE_MISSING) or any proxy of them.
No instrument serial and no fibre value that is not a recorded source or a declared scenario.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from opticps.benchmarks import e2_model, teriphic
from opticps.benchmarks.catalog import load_strict_yaml
from opticps.benchmarks.e2_metrics import (
    QUANTILE_POINTS,
    WindowSummary,
    metrics_between,
    normalise,
    renormalise,
    require_window,
    summarise_window,
)
from opticps.benchmarks.external_capture import ExternalCapture
from opticps.benchmarks.holdout import (
    CRITERION_PATH,
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
POWER_STUDY_PATH = E2_DIR / "power_study.yaml"
SELECTED_PATH = E2_DIR / "selected_scenario.yaml"  # written by E2b after the 2 km stage
EVALUATION_SCRIPT = Path("scripts/score_teriphic_e2.py")
LENGTH_KM = {
    "50G_PAM4_PD1_2km_Subassembly1.bin": 2.0,
    "50G_PAM4_PD1_10km_Subassembly1.bin": 10.0,
}
# The role of each holdout is fixed here, in frozen code, and not read from the register.
ROLE_BY_NAME = {
    "50G_PAM4_PD1_2km_Subassembly1.bin": Split.VALIDATION,
    "50G_PAM4_PD1_10km_Subassembly1.bin": Split.LOCKED_TEST,
}
# The import closure of `score_holdout` (a test recomputes it): the files whose bytes are the code
# identity of E2 (plan R10.4, R12.5). Narrow: these files only, as committed.
CODE_IDENTITY_FILES = (
    "src/opticps/__init__.py",
    "src/opticps/benchmarks/__init__.py",
    "src/opticps/benchmarks/capture_stats.py",
    "src/opticps/benchmarks/catalog.py",
    "src/opticps/benchmarks/e2_metrics.py",
    "src/opticps/benchmarks/e2_model.py",
    "src/opticps/benchmarks/e2_score.py",
    "src/opticps/benchmarks/external_capture.py",
    "src/opticps/benchmarks/holdout.py",
    "src/opticps/benchmarks/provenance.py",
    "src/opticps/benchmarks/teriphic.py",
    "src/opticps/benchmarks/timing.py",
)
MODEL_VERSION = 1
SCENARIO_VERSION = 2
PREREGISTRATION_VERSION = 2
SELECTION_MARGIN = 0.25  # psi units: a single scenario is carried only if it wins by this much
REPRODUCTION_RTOL = 1e-6
REPRODUCTION_ATOL = 1e-9
SAMPLE_RATE_RTOL = 1e-6
OUTCOME_FAIL = "FAIL"
OUTCOME_PASS_NOT_DISCRIMINATING = "PASS, NOT DISCRIMINATING"
OUTCOME_PASS_DISCRIMINATING = "PASS, DISCRIMINATING"
OUTCOME_BLOCKED = "BLOCKED"
CLAIM_PARTIAL = "PARTIAL"
CLAIM_GRID_LIMITED = "NO_GRID_SCENARIO_FITS"
BER_STATUS = "REFERENCE_SEQUENCE_MISSING"
# One caveat per nuisance, printed with every result (plan R12.4). A FAIL says no scenario of the
# family fits, not that the fibre model is wrong; a PASS never validates dispersion.
FAIL_CAVEATS = (
    "chirp: unknown, set to zero (MODEL GAP: CHIRP); it changes the dispersion response",
    "dispersion outside 0 to 6.352 ps/(nm km), or between grid points above 3 (a true D can FAIL)",
    "at 10 km a FAIL is reported INCONCLUSIVE: about 40 percent of true D above 3 miss the grid",
    "SNR change beyond noise factor 2.2, or a noise colour unlike B2B",
    "an unmodelled low-pass, reflection or export filter (fails at 2 km for 32 to 36 GHz)",
    "symbol statistics unlike uniform and independent; large-signal operation (not modelled)",
    "amplitude and launch power are NOT a cause: the amplitude ratio is reported and not tested",
)
PASS_CAVEATS = (
    "a pass does not validate dispersion: an unmodelled low-pass passes at 10 km (power study)",
    "the surviving dispersions are a fit to the capture and are a set, not a prediction",
    "chirp, wavelength and fibre type stay UNKNOWN; the chirp-free assumption is not tested",
    "VALIDATED is never returned: the claim is PARTIAL at most",
)
_SHA1 = re.compile(r"[0-9a-f]{40}")


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
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
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
    noise_factor: float  # noise standard deviation relative to B2B (SNR change)
    noise_through_fibre: bool  # the noise crosses the fibre too (the other noise-origin bound)
    null_control: bool
    label: str


SCENARIO_KEYS = frozenset({"scenario_list_version", "count", "scenarios", "provenance"})
SCENARIO_ENTRY_KEYS = frozenset(
    {"id", "dispersion_ps_nm_km", "noise_factor", "noise_through_fibre", "null_control", "label"}
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
        for flag in ("null_control", "noise_through_fibre"):
            if type(entry[flag]) is not bool:
                raise BenchmarkError(f"scenario {identifier}: {flag} must be true or false")
        scenario = Scenario(
            identifier,
            _non_negative(entry["dispersion_ps_nm_km"], f"{identifier} dispersion"),
            _positive(entry["noise_factor"], f"{identifier} noise factor"),
            entry["noise_through_fibre"],
            entry["null_control"],
            str(entry["label"]),
        )
        if scenario.noise_through_fibre and scenario.dispersion_ps_nm_km == 0.0:
            raise BenchmarkError(
                f"scenario {identifier}: no dispersion, nothing for noise to cross"
            )
        if scenario.null_control and (
            scenario.dispersion_ps_nm_km != 0.0 or scenario.noise_factor != 1.0
        ):
            raise BenchmarkError(f"scenario {identifier}: the control must be D = 0, factor 1")
        scenarios.append(scenario)
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


def loaded_code_files() -> dict[str, Path]:
    """Where each code-identity module was actually imported from."""
    found: dict[str, Path] = {}
    for relative in CODE_IDENTITY_FILES:
        name = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
        name = name.removesuffix(".__init__")
        module = sys.modules.get(name)
        origin = getattr(module, "__file__", None)
        if origin is None:
            raise BenchmarkError(f"code identity: module {name} is not loaded")
        found[relative] = Path(origin).resolve()
    return found


def verify_loaded_code(root: Path) -> None:
    """Refuse when the running modules are not the files of `root` (a different checkout)."""
    for relative, origin in loaded_code_files().items():
        if origin != (root / relative).resolve():
            raise BenchmarkError(f"{relative}: the code that is running is not the code of {root}")


# ---------------------------------------------------------------------------- prediction
def predict(
    model: Mapping[str, Any], scenario: Scenario, length_km: float, n_samples: int
) -> FloatArray:
    """The predicted B2B-normalised window for one scenario and length, from the model's seeds."""
    seeds = model["seeds"]
    return e2_model.synthesize(
        model,
        n_samples=n_samples,
        symbol_seed=seeds["prediction_symbols"],
        noise_seed=seeds["prediction_noise"],
        dispersion_ps_nm_km=scenario.dispersion_ps_nm_km,
        length_km=length_km,
        sigma=float(model["noise_sigma"]) * scenario.noise_factor,
        noise_through_fibre=scenario.noise_through_fibre,
    )


def window_summary(x: FloatArray, sample_rate_hz: float, baud_bd: float) -> WindowSummary:
    """Summary of the gain-invariant form of a window (R12.3): the same map for every window."""
    return summarise_window(renormalise(x)[0], sample_rate_hz, baud_bd)


def prediction_summaries(
    model: Mapping[str, Any], scenarios: Sequence[Scenario], lengths_km: Sequence[float]
) -> dict[tuple[float, str], WindowSummary]:
    n = int(model["windows"]["evaluation"]["samples"])
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    return {
        (length, s.scenario_id): window_summary(predict(model, s, length, n), fs, baud)
        for length in lengths_km
        for s in scenarios
    }


def describe(summary: WindowSummary, baud_bd: float) -> dict[str, Any]:
    """Descriptive values of a predicted window that the pre-registration records."""
    frequency, density = summary.frequency, summary.density
    edges = np.linspace(0.0, baud_bd, 11)
    peak = float(density.max())
    bands = []
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        mask = (frequency >= low) & (frequency < high + (1e-9 if high == edges[-1] else 0))
        bands.append(float(10.0 * np.log10(density[mask].mean() / peak)))
    return {
        "centroids": [float(v) for v in summary.centroids],
        "gaps": [float(v) for v in summary.gaps],
        "cluster_shares": [float(v) for v in summary.shares],
        "std": summary.std,
        "quantiles": {
            repr(p): float(v) for p, v in zip(QUANTILE_POINTS, summary.quantile_p, strict=True)
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
    claim: str | None
    verdict: Verdict | None
    best: str
    survivors: tuple[str, ...]
    carry_forward: tuple[str, ...]
    scenarios: dict[str, dict[str, Any]]
    comparator: dict[str, Any]
    gain_ratio: float
    within_criterion: bool
    comparator_within_criterion: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def carry_rule(table: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    """2 km stage: which scenarios go on to 10 km. Pre-stated, R12.3.

    The survivors are the scenarios within the criterion. One of them is carried alone only if it
    wins by `SELECTION_MARGIN` in psi over the next survivor (or is the only one); otherwise all
    survivors are carried. No survivor, nothing is carried.
    """
    survivors = sorted(
        (v["psi"], i, k) for i, (k, v) in enumerate(table.items()) if v["psi"] <= 1.0
    )
    if not survivors:
        return ()
    if len(survivors) == 1 or survivors[0][0] + SELECTION_MARGIN <= survivors[1][0]:
        return (survivors[0][2],)
    return tuple(k for _, _, k in sorted(survivors, key=lambda item: item[1]))


def score_windows(
    measured: FloatArray,
    comparator: FloatArray,
    *,
    model: Mapping[str, Any],
    scenarios: tuple[Scenario, ...],
    limits: Mapping[str, float],
    length_km: float,
    split: Split,
    carried: Sequence[str] | None = None,
    validation_stage: ValidationStage | None = None,
    sequence_check: SequenceCheck | None = None,
    state: HoldoutState | None = None,
    identifiable_in_principle: bool = False,
    summaries: Mapping[tuple[float, str], WindowSummary] | None = None,
) -> WindowScore:
    """Score one measured B2B-normalised window against the scenarios and the B2B copy.

    Both windows go through the gain-invariant map of R12.3 first; the measured amplitude ratio is
    returned, not tested. A non-finite or too short window is refused. The 2 km stage scores every
    scenario; the locked test scores the carried ones and the control (as a reference).
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
    ids = [s.scenario_id for s in scenarios]
    null_id = next(s.scenario_id for s in scenarios if s.null_control)
    if split is Split.LOCKED_TEST:
        if not carried:
            raise BenchmarkError("the locked test needs the scenarios carried from the 2 km stage")
        if len(set(carried)) != len(carried) or any(c not in ids for c in carried):
            raise BenchmarkError("a carried scenario is not in the scenario list")
        scored_ids = [i for i in ids if i in set(carried) or i == null_id]
    else:
        if carried is not None:
            raise BenchmarkError("the 2 km stage carries nothing in; it decides what is carried")
        scored_ids = ids
    cache = summaries or {}
    measured_n, _, gain = renormalise(measured)
    measured_summary = summarise_window(measured_n, fs, baud)
    table: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        if scenario.scenario_id not in scored_ids:
            continue
        key = (length_km, scenario.scenario_id)
        predicted = cache.get(key) or window_summary(
            predict(model, scenario, length_km, n_samples), fs, baud
        )
        metrics = metrics_between(measured_summary, predicted)
        table[scenario.scenario_id] = {
            "metrics": metrics,
            "psi": exceedance(metrics, limits),
            "null_control": scenario.null_control,
        }
    copy_metrics = metrics_between(measured_summary, window_summary(comparator, fs, baud))
    copy_psi = exceedance(copy_metrics, limits)
    judged = [i for i in table if split is Split.VALIDATION or i in set(carried or ())]
    survivors = tuple(i for i in judged if table[i]["psi"] <= 1.0)
    best = min(table, key=lambda key: (table[key]["psi"], ids.index(key)))
    copy_ok = bool(copy_psi <= 1.0)
    null_ok = bool(table[null_id]["psi"] <= 1.0)
    fibre_survivors = [i for i in survivors if i != null_id]
    notes: list[str] = []
    claim: str | None = None
    if not survivors:
        outcome = OUTCOME_FAIL
        if split is Split.LOCKED_TEST:
            claim = CLAIM_GRID_LIMITED
            notes.append(
                "no grid scenario fits at 10 km; a true dispersion above 3 ps/(nm km) between grid"
                " points fails too (power study), so this is INCONCLUSIVE, not FAILED"
            )
    elif copy_ok or null_ok or not fibre_survivors:
        outcome = OUTCOME_PASS_NOT_DISCRIMINATING
        if copy_ok:
            notes.append("the B2B copy is also within every limit")
        if null_ok:
            notes.append("the no-fibre control scenario is also within every limit")
        if not fibre_survivors:
            notes.append("only the no-fibre control is within every limit")
    else:
        outcome = OUTCOME_PASS_DISCRIMINATING
        claim = CLAIM_PARTIAL
        notes.append(
            "PARTIAL: some scenario fits, the copy and the control do not; an unmodelled low-pass"
            " fits too (power study), so dispersion is not established and VALIDATED is not offered"
        )
    allowed = allowed_verdicts(
        split, validation_stage=validation_stage, sequence_check=sequence_check, state=state
    )
    verdict: Verdict | None
    if outcome == OUTCOME_FAIL:
        verdict = Verdict.FAILED if split is Split.VALIDATION else Verdict.INCONCLUSIVE
    elif outcome == OUTCOME_PASS_NOT_DISCRIMINATING:
        verdict = (
            Verdict.INCONCLUSIVE if identifiable_in_principle else Verdict.UNIDENTIFIABLE_PARAMETER
        )
    elif split is Split.VALIDATION:
        verdict = None  # plan R.5: within criterion at the selection stage, no verdict
        notes.append("within criterion at the selection stage; the 2 km file cannot be VALIDATED")
    else:
        verdict = Verdict.INCONCLUSIVE  # capped: PARTIAL claim, never VALIDATED (R12.4)
    if verdict is not None and verdict not in allowed:
        # a burned file or a shared sequence leaves EXPLORATORY (or BLOCKED), nothing confirmatory
        verdict = Verdict.EXPLORATORY if Verdict.EXPLORATORY in allowed else Verdict.BLOCKED
    carry = carry_rule(table) if split is Split.VALIDATION else ()
    return WindowScore(
        outcome,
        claim,
        verdict,
        best,
        survivors,
        carry,
        table,
        {"metrics": copy_metrics, "psi": copy_psi},
        gain,
        bool(survivors),
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
    summaries: Mapping[tuple[float, str], WindowSummary] | None = None,
) -> dict[str, Any]:
    """Predicted values for every length and scenario from B2B and code alone.

    `comparator` is the B2B window at the evaluation indices. For each scenario, the separation is
    the four metrics between the scenario's prediction and the B2B copy (both gain-invariant). A
    dispersion scenario that even a perfect model would leave inside every limit of the B2B copy
    is not `separable`. `identifiable_in_principle` asks for a separable scenario that differs from
    the control by dispersion alone (same noise factor, noise not through the fibre), because
    that is what dispersion identifiability means. Nothing here reads a holdout.
    """
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    comparator = require_window(comparator, "B2B copy window")
    cache = summaries or prediction_summaries(model, scenarios, lengths_km)
    copy_summary = window_summary(comparator, fs, baud)
    predictions: dict[str, Any] = {}
    identifiable: dict[str, bool] = {}
    for length in lengths_km:
        per_scenario: dict[str, Any] = {}
        for scenario in scenarios:
            summary = cache[(length, scenario.scenario_id)]
            separation = metrics_between(copy_summary, summary)
            psi = exceedance(separation, limits)
            per_scenario[scenario.scenario_id] = {
                "summary": describe(summary, baud),
                "separation_from_b2b_copy": separation,
                "separation_psi": psi,
                "separable": bool(psi > 1.0) and not scenario.null_control,
            }
        key = f"{length:g}"
        predictions[key] = per_scenario
        identifiable[key] = any(
            per_scenario[s.scenario_id]["separable"]
            for s in scenarios
            if s.noise_factor == 1.0 and not s.noise_through_fibre and not s.null_control
        )
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
    claim: str | None
    verdict: str | None
    best_scenario: str | None
    survivors: tuple[str, ...]
    carry_forward: tuple[str, ...]
    scenarios_scored: int
    scenarios: dict[str, dict[str, Any]]
    b2b_copy: dict[str, Any]
    gain_ratio: float | None
    limits: dict[str, float]
    criterion_commit: str
    head_commit: str
    identifiable_in_principle: bool
    model_gaps: tuple[str, ...]
    assumptions: tuple[str, ...]
    notes: tuple[str, ...]
    hashes_verified: bool
    ber_status: str = BER_STATUS
    fail_caveats: tuple[str, ...] = FAIL_CAVEATS
    pass_caveats: tuple[str, ...] = PASS_CAVEATS
    fibre_knowledge: Mapping[str, str] = field(
        default_factory=lambda: {
            "fibre_type": "UNKNOWN",
            "wavelength": "UNKNOWN (O-band only)",
            "dispersion": "scenarios only (ASSUMED_G652D), not ground truth",
            "loss_and_launch_power": "UNKNOWN; the amplitude ratio is reported, not tested",
            "chirp": "UNKNOWN; MODEL GAP: CHIRP, scenarios assume zero",
        }
    )

    def report(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "length_km": self.length_km,
            "split": self.split,
            "outcome": self.outcome,
            "claim": self.claim,
            "verdict": self.verdict,
            "best_scenario": self.best_scenario,
            "survivors": list(self.survivors),
            "carry_forward": list(self.carry_forward),
            "scenarios_scored": self.scenarios_scored,
            "scenarios": self.scenarios,
            "b2b_copy": self.b2b_copy,
            "amplitude_ratio_vs_b2b": self.gain_ratio,
            "limits": self.limits,
            "criterion_commit": self.criterion_commit,
            "head_commit": self.head_commit,
            "identifiable_in_principle": self.identifiable_in_principle,
            "model_gaps": list(self.model_gaps),
            "assumptions": list(self.assumptions),
            "notes": list(self.notes),
            "hashes_verified": self.hashes_verified,
            "reference_sequence": self.ber_status,
            "caveats_if_fail": list(self.fail_caveats),
            "caveats_if_pass": list(self.pass_caveats),
            "fibre_knowledge": dict(self.fibre_knowledge),
        }


def _holdout_asset(path: Path, source: SourceRecord) -> AssetRecord:
    name = teriphic.fold_name(Path(path).resolve().name)
    for asset in source.assets:
        if teriphic.fold_name(asset.filename) != name or asset.split not in HOLDOUT_SPLITS:
            continue
        if ROLE_BY_NAME.get(asset.filename) is not asset.split:
            raise BenchmarkError(
                f"{asset.filename}: the register gives it the role {asset.split.value}; the frozen"
                f" code fixes {getattr(ROLE_BY_NAME.get(asset.filename), 'value', None)}",
                ErrorCode.LEAKAGE_DETECTED,
            )
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


def first_parent_freeze(root: Path) -> str:
    """The first commit on the first-parent history of HEAD that touches the criterion path."""
    out = _git_ok(
        root, "log", "--first-parent", "--reverse", "--format=%H", "--", CRITERION_PATH.as_posix()
    )
    commits = out.decode("ascii").split()
    if not commits:
        raise BenchmarkError("the criterion has no commit on the first-parent history")
    return commits[0]


def require_freeze_pin(root: Path, frozen: Any, expected: str) -> None:
    """The freeze commit must be the one the caller pinned outside the repository."""
    if not isinstance(expected, str) or not _SHA1.fullmatch(expected):
        raise BenchmarkError("expected_freeze_commit must be a full lower-case 40-digit commit id")
    if frozen.commit != expected:
        raise BenchmarkError(
            f"the freeze commit found ({frozen.commit[:12]}) is not the pinned {expected[:12]}"
        )
    if first_parent_freeze(root) != frozen.commit:
        raise BenchmarkError("the freeze commit is not the first on the first-parent history")


def bind_to_freeze(root: Path, frozen: Any) -> None:
    """Refuse unless every file the result depends on equals what the freeze commit held.

    `require_frozen_criterion` proves the criterion and the named inputs are committed and
    unchanged since `HEAD`; it does not prove they are what existed at the freeze. This reads each
    file at `frozen.commit` and compares it with the committed bytes at `HEAD`: model, scenario
    list, pre-registration, power study, evaluation script, the role register and every file of
    `CODE_IDENTITY_FILES`. The freeze commit must be an ancestor of `HEAD`. If the criterion path
    itself moves, the freeze commit moves with it and this binding restarts; only the pin held
    outside the repository (`require_freeze_pin`) catches that.
    """
    if _git(root, "merge-base", "--is-ancestor", frozen.commit, "HEAD").returncode != 0:
        raise BenchmarkError("the freeze commit is not an ancestor of HEAD")
    paths = (
        MODEL_PATH,
        SCENARIO_PATH,
        PREREGISTRATION_PATH,
        POWER_STUDY_PATH,
        EVALUATION_SCRIPT,
        teriphic.CONFIG_PATH,
    )
    for relative in (*paths, *map(Path, CODE_IDENTITY_FILES)):
        now, _ = _committed_bytes(root, root / relative, "frozen file")
        then = _blob(root, frozen.commit, relative.as_posix())
        if then is None:
            raise BenchmarkError(f"{relative.as_posix()}: did not exist at the freeze commit")
        if then != now:
            raise BenchmarkError(f"{relative.as_posix()}: changed since the freeze commit")


def read_selected_scenarios(root: Path, frozen: Any, scenarios: Sequence[Scenario]) -> list[str]:
    """The scenarios carried from the 2 km stage: added once after the freeze, never changed."""
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
    status = _git_ok(
        root, "diff-tree", "--no-commit-id", "--name-status", "-r", "--find-renames=20%", added
    ).decode("utf-8", "replace")
    if f"A\t{relative}" not in status.splitlines():
        raise BenchmarkError("selected scenario: must be a new file in its commit (not a rename)")
    now, _ = _committed_bytes(root, root / SELECTED_PATH, "selected scenario")
    if _blob(root, added, relative) != now:
        raise BenchmarkError("selected scenario: changed since it was added")
    chosen = _mapping(
        _parse(now, "selected scenario"),
        "selected scenario",
        {"scenario_ids", "rule", "selected_at_stage"},
    )
    if chosen["selected_at_stage"] != "2km":
        raise BenchmarkError("selected scenario: selected_at_stage must be '2km'")
    if chosen["rule"] not in ("single", "all_survivors"):
        raise BenchmarkError("selected scenario: rule must be 'single' or 'all_survivors'")
    ids = chosen["scenario_ids"]
    listed = {s.scenario_id for s in scenarios}
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(i, str) for i in ids)
        or len(set(ids)) != len(ids)
    ):
        raise BenchmarkError(
            "selected scenario: scenario_ids must be a non-empty list of unique ids"
        )
    if not set(ids) <= listed:
        raise BenchmarkError("selected scenario: an id is not in the scenario list")
    if chosen["rule"] == "single" and len(ids) != 1:
        raise BenchmarkError("selected scenario: rule 'single' carries exactly one scenario")
    return [str(i) for i in ids]


def _read_window(path: Path, checksum: Any, model: Mapping[str, Any], label: str) -> Any:
    """Open one capture, check its header against the model, read the evaluation window."""
    window = model["windows"]["evaluation"]
    start, count = int(window["start"]), int(window["samples"])
    fs = float(model["sample_rate_hz"])
    capture = ExternalCapture.open_keysight_bin(path, checksum=checksum)
    try:
        increment = capture.layout.x_increment_s
        if increment is None or not math.isclose(1.0 / increment, fs, rel_tol=SAMPLE_RATE_RTOL):
            return f"{label} header sample rate differs from the B2B model"
        if capture.count < start + count:
            return f"{label} record is shorter than the window"
        norm = model["normalisation"]
        return normalise(capture.read(start, start + count), float(norm["c0"]), float(norm["g0"]))
    finally:
        capture.close()


def score_holdout(
    holdout_path: Path,
    *,
    b2b_path: Path,
    expected_freeze_commit: str,
    repo_root: Path = Path("."),
    validation_stage: ValidationStage | None = None,
    sequence_check: SequenceCheck | None = None,
    state: HoldoutState | None = None,
    source: SourceRecord | None = None,
    holdout_sha256: Mapping[str, str] | None = None,
) -> E2Result:
    """Score one holdout against the frozen criterion. The only holdout reader in `src`.

    `expected_freeze_commit` is required: the caller pins the freeze commit outside the repository
    (a pin held on the same machine checks against ordinary commits and gives no date proof).
    `source` and `holdout_sha256` default to the register and the recorded hashes; they are
    injectable for tests, which must never touch a real holdout. Every refusal of steps 1 to 5 of
    the module docstring is a `BenchmarkError` and happens before the holdout is hashed, opened or
    read; the holdout's header and samples are read last.
    """
    root = Path(repo_root)
    holdout_path = Path(holdout_path)
    source = source or teriphic.load_config(root / teriphic.CONFIG_PATH)
    asset = _holdout_asset(holdout_path, source)
    # the E2 obligation of plan R9.1: no statistic, no header, not even a hash, before this.
    frozen = require_frozen_criterion(
        asset,
        plan_path=root / DEFAULT_PLAN,
        repo_root=root,
        inputs=_inputs(asset, root),
        validation_stage=validation_stage,
    )
    if frozen is None:
        raise BenchmarkError(f"{asset.filename}: no frozen criterion was issued")
    require_freeze_pin(root, frozen, expected_freeze_commit)
    verify_loaded_code(root)
    bind_to_freeze(root, frozen)
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
    carried: list[str] | None = None
    if asset.split is Split.LOCKED_TEST:
        carried = read_selected_scenarios(root, frozen, scenarios)
    # the B2B comparator and the pre-registered predictions: B2B only, still before the holdout.
    table = teriphic.HOLDOUT_SHA256 if holdout_sha256 is None else holdout_sha256
    expected_sha = table.get(asset.filename)
    if expected_sha is None:
        raise BenchmarkError(f"{asset.filename}: no recorded SHA-256, refusing to read")
    gate = teriphic.gate_sample_read(b2b_path, source, holdout_sha256=table)
    if not gate.is_b2b:
        raise BenchmarkError("the comparator file is not the B2B capture (MD5 differs); refused")
    comparator = _read_window(b2b_path, gate.checksum, model, "B2B")
    if isinstance(comparator, str):
        return _blocked(asset, frozen, model, comparator)
    summaries = prediction_summaries(model, scenarios, (2.0, 10.0))
    recomputed = compute_preregistration(
        model, scenarios, comparator, limits, (2.0, 10.0), summaries
    )
    check_reproduction(
        {k: registration[k] for k in ("predictions", "identifiable_in_principle")}, recomputed
    )
    # the holdout: hashes at read time, then header and samples, last.
    checksum = verify_local_asset(holdout_path, asset.checksum.md5_supplied)
    if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:
        raise BenchmarkError(
            f"{asset.filename}: the file's MD5 or SHA-256 does not match the recorded values;"
            " not read",
            ErrorCode.LEAKAGE_DETECTED,
        )
    measured = _read_window(holdout_path, checksum, model, "holdout")
    if isinstance(measured, str):
        return _blocked(asset, frozen, model, measured)
    length = LENGTH_KM[asset.filename]
    identifiable = bool(recomputed["identifiable_in_principle"][f"{length:g}"])
    scored = score_windows(
        measured,
        comparator,
        model=model,
        scenarios=scenarios,
        limits=limits,
        length_km=length,
        split=asset.split,
        carried=carried,
        validation_stage=validation_stage,
        sequence_check=sequence_check,
        state=state,
        identifiable_in_principle=identifiable,
        summaries=summaries,
    )
    return E2Result(
        filename=asset.filename,
        length_km=length,
        split=asset.split.value,
        outcome=scored.outcome,
        claim=scored.claim,
        verdict=scored.verdict.value if scored.verdict else None,
        best_scenario=scored.best,
        survivors=scored.survivors,
        carry_forward=scored.carry_forward,
        scenarios_scored=len(scored.scenarios),
        scenarios=scored.scenarios,
        b2b_copy=scored.comparator,
        gain_ratio=scored.gain_ratio,
        limits=limits,
        criterion_commit=frozen.commit,
        head_commit=frozen.head_commit,
        identifiable_in_principle=identifiable,
        model_gaps=tuple(str(x) for x in model["model_gaps"]),
        assumptions=tuple(str(x) for x in model["assumptions"]),
        notes=scored.notes,
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
        claim=None,
        verdict=Verdict.BLOCKED.value,
        best_scenario=None,
        survivors=(),
        carry_forward=(),
        scenarios_scored=0,
        scenarios={},
        b2b_copy={},
        gain_ratio=None,
        limits={name: float(frozen.limits[name]) for name in METRICS},
        criterion_commit=frozen.commit,
        head_commit=frozen.head_commit,
        identifiable_in_principle=False,
        model_gaps=tuple(str(x) for x in model["model_gaps"]),
        assumptions=tuple(str(x) for x in model["assumptions"]),
        notes=(reason,),
        hashes_verified=False,
    )
