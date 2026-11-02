"""Gate E2 part a: the committed freeze, checked in the repository that holds it.

These tests read git history and the committed E2 files; they open no capture. They are not part of
`scripts/mutate_e2.py` (a mutated code file would fail the committed code identity and kill every
mutant for the wrong reason). In a repository without the criterion they fail by design.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from opticps.benchmarks import e2_score, holdout, teriphic
from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.provenance import Split

ROOT = Path(__file__).resolve().parents[1]


def assets():
    return {a.split: a for a in load_source_config(ROOT / teriphic.CONFIG_PATH).assets}


def test_the_criterion_is_frozen_and_tied_to_the_committed_plan_and_inputs():
    frozen = holdout.require_frozen_criterion(
        assets()[Split.VALIDATION],
        plan_path=ROOT / holdout.DEFAULT_PLAN,
        repo_root=ROOT,
        inputs=e2_score._inputs(assets()[Split.VALIDATION], ROOT),
    )
    assert frozen is not None and len(frozen.commit) == 40
    registered = yaml.safe_load((ROOT / e2_score.PREREGISTRATION_PATH).read_bytes())
    for metric in holdout.METRICS:
        assert frozen.limits[metric] == pytest.approx(registered["limits"][metric], rel=1e-12)
    criterion = yaml.safe_load((ROOT / holdout.CRITERION_PATH).read_bytes())
    plan = (ROOT / holdout.DEFAULT_PLAN).read_bytes()
    assert criterion["plan_sha256"] == hashlib.sha256(plan).hexdigest()
    assert criterion["criterion_version"] == holdout.CRITERION_VERSION
    assert criterion["estimators"] == dict(holdout.ESTIMATORS)
    assert criterion["b2b_basis"] == registered["b2b_basis"]
    assert criterion["multipliers"] == registered["multipliers"]
    # the inputs the guard hashed are the committed model and scenario list
    model = (ROOT / e2_score.MODEL_PATH).read_bytes()
    scenarios = (ROOT / e2_score.SCENARIO_PATH).read_bytes()
    assert frozen.inputs["b2b_model"] == hashlib.sha256(model).hexdigest()
    assert frozen.inputs["scenario_list"] == hashlib.sha256(scenarios).hexdigest()


def test_the_10km_stage_is_not_frozen_yet_and_no_result_exists():
    """E2b creates `selected_scenario.yaml` after the 2 km stage; until then 10 km is refused."""
    assert not (ROOT / e2_score.SELECTED_PATH).exists()
    assert (ROOT / e2_score.EVALUATION_SCRIPT).is_file()
    registered = yaml.safe_load((ROOT / e2_score.PREREGISTRATION_PATH).read_bytes())
    assert registered["results"] is None
    with pytest.raises(Exception, match="selected_scenario|not committed|cannot be read"):
        holdout.require_frozen_criterion(
            assets()[Split.LOCKED_TEST],
            plan_path=ROOT / holdout.DEFAULT_PLAN,
            repo_root=ROOT,
            inputs=e2_score._inputs(assets()[Split.LOCKED_TEST], ROOT),
            validation_stage=holdout.ValidationStage.NOT_FAILED,
        )


def test_the_known_limits_say_the_guard_has_a_caller_and_the_plan_says_so_too():
    limits = " ".join((ROOT / "docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md").read_text().split())
    assert "which now has a caller" in limits and "plan R10.1" in limits
    plan = " ".join((ROOT / holdout.DEFAULT_PLAN).read_text().split())
    assert "R9.1 now has a caller" in plan
