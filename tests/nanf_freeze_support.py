"""Test support for the freeze record: a throw-away Git repository holding a copy of the code, the
plan, the configuration files and a synthetic calibration artefact. Nothing here freezes anything:
every repository lives in a temporary directory and the committed record path is never written.
All parameter vectors are synthetic and no fit is run.
"""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from opticps.measurement import nanf_freeze as nf
from opticps.measurement.nanf_chain import TxRxParameters
from opticps.measurement.nanf_import import calibration_partition_sha256

REPO = Path(__file__).resolve().parents[1]
ARTIFACT_REL = "docs/benchmarks/NANF_CALIBRATION_RESULT.json"
PLAN_REL = "docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md"
GOOD_FIT = {
    "method": "synthetic stand-in for the test of the record",
    "converged": True,
    "n_evaluations": 7,
    "n_calibration_points": 33,
    "cost": 1.25,
}
PARAMS = TxRxParameters(
    tx_bandwidth_ghz=31.0, rx_bandwidth_ghz=42.0, thermal_noise_pa_per_rthz=21.5
)
FLAGS = ("bias_fraction",)  # at its prior 0.5 in PARAMS


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(root), *args],
        capture_output=True,
        check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/nonexistent"},
    )
    return done.stdout.decode().strip()


def copy_tree(root: Path) -> None:
    shutil.copytree(
        REPO / "src",
        root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for rel in ("pyproject.toml", "uv.lock", PLAN_REL):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)


def write_artifact(
    root: Path,
    parameters: TxRxParameters = PARAMS,
    flags=FLAGS,
    fit_result=GOOD_FIT,
    partition: str | None = None,
    rel: str = ARTIFACT_REL,
) -> None:
    part = calibration_partition_sha256() if partition is None else partition
    raw = nf.calibration_artifact(parameters, flags, {}, part)
    if fit_result is not GOOD_FIT:
        body = json.loads(raw)
        body["fit_result"] = fit_result
        raw = nf.canonical_json(body)
    else:
        body = json.loads(raw)
        body["fit_result"] = dict(GOOD_FIT)
        raw = nf.canonical_json(body)
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(raw)


def make_repo(
    tmp_path: Path,
    parameters: TxRxParameters = PARAMS,
    flags=FLAGS,
    fit_result=GOOD_FIT,
    name: str = "repo",
) -> SimpleNamespace:
    """A committed repository with an artefact, and the record built from it (not yet written)."""
    root = tmp_path / name
    root.mkdir()
    copy_tree(root)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base: code and plan, no calibration artefact yet")
    base_commit = git(root, "rev-parse", "HEAD")
    write_artifact(root, parameters, flags, fit_result)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the synthetic calibration artefact")
    record = nf.build_freeze_record(ARTIFACT_REL, root=root, plan_path=root / PLAN_REL)
    return SimpleNamespace(
        base_commit=base_commit,
        root=root,
        plan=root / PLAN_REL,
        record=record,
        record_path=tmp_path / f"{name}-record.json",
        hash=record["freeze_hash"],
    )


def write_record(repo: SimpleNamespace, record=None) -> Path:
    repo.record_path.write_text(json.dumps(repo.record if record is None else record))
    return repo.record_path


def patch_module_paths(monkeypatch, repo: SimpleNamespace) -> None:
    """Point the module at the throw-away repository, as a synthetic-only unlock."""
    write_record(repo)
    monkeypatch.setattr(nf, "ROOT", repo.root)
    monkeypatch.setattr(nf, "PLAN_PATH", repo.plan)
    monkeypatch.setattr(nf, "FREEZE_RECORD_PATH", repo.record_path)


_SESSION: dict[str, SimpleNamespace] = {}


def session_repo(tmp_path_factory) -> SimpleNamespace:
    """One shared throw-away repository per test session, for the synthetic-workbook tests."""
    if "repo" not in _SESSION:
        base = tmp_path_factory.mktemp("freeze-session")
        _SESSION["repo"] = make_repo(base)
    return _SESSION["repo"]
