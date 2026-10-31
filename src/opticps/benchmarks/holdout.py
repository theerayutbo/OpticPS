"""Holdout guards for the TERIPHIC fit/holdout plan (Revision 1, section R.2 to R.5).

Three refusals, all offline:

- a `VALIDATION` or `LOCKED_TEST` asset is not evaluated unless a criterion file is committed in
  Git, unmodified, complete and tied to the current plan hash (`require_frozen_criterion`);
- a BER needs a transmitted sequence stated by a source, never one inferred from a capture
  (`require_reference_for_ber`);
- 2 km (the selection stage) cannot end VALIDATED, and 10 km cannot after a failed 2 km
  (`allowed_verdicts`).

Nothing here reads a capture. The only external process is `git`, run on the local repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import math
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from opticps.benchmarks.catalog import load_strict_yaml
from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    ErrorCode,
    Provenance,
    Split,
)

CRITERION_VERSION = 1
HOLDOUT_SPLITS = frozenset({Split.VALIDATION, Split.LOCKED_TEST})
# Metrics named by the plan (Revision 1, R.4). A criterion must give a limit for each of them.
METRICS = (
    "M1_level_spacing",
    "M2_wasserstein1_amplitude",
    "M3_quantile_error",
    "M4_log_spectral_distance",
)
DEFAULT_PLAN = Path("docs/benchmarks/FIT_HOLDOUT_PLAN.md")
DEFAULT_CRITERION = Path("docs/benchmarks/TERIPHIC_CRITERION.yaml")


class Verdict(StrEnum):
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNIDENTIFIABLE_PARAMETER = "UNIDENTIFIABLE_PARAMETER"
    BLOCKED = "BLOCKED"


def allowed_verdicts(split: Split, *, validation_failed: bool = False) -> frozenset[Verdict]:
    """Verdicts a role may end with. Only the locked test can be VALIDATED, and not after a
    failed validation stage."""
    if split is Split.LOCKED_TEST:
        everything = frozenset(Verdict)
        return everything - {Verdict.VALIDATED} if validation_failed else everything
    if split is Split.VALIDATION:
        return frozenset(Verdict) - {Verdict.VALIDATED}
    if split is Split.CHARACTERISATION:
        return frozenset({Verdict.INCONCLUSIVE, Verdict.BLOCKED})
    return frozenset({Verdict.BLOCKED})


def require_reference_for_ber(asset: AssetRecord) -> str:
    """The transmitted sequence for a BER, or REFERENCE_SEQUENCE_MISSING.

    Only a sequence stated by a source (`PUBLISHED_MEASUREMENT`) counts. A sequence recovered
    from a capture, including from B2B, is an inferred candidate and is refused.
    """
    reference = asset.parameters["reference_sequence"]
    if not reference.known:
        raise BenchmarkError(
            f"{asset.filename}: no transmitted sequence is documented",
            ErrorCode.REFERENCE_SEQUENCE_MISSING,
        )
    if reference.provenance is not Provenance.PUBLISHED_MEASUREMENT:
        raise BenchmarkError(
            f"{asset.filename}: the sequence is {reference.provenance.value}, an inferred"
            " candidate, not a reference for BER",
            ErrorCode.REFERENCE_SEQUENCE_MISSING,
        )
    return str(reference.value)


@dataclass(frozen=True)
class FrozenCriterion:
    """A criterion that passed `require_frozen_criterion`; reports must carry `commit`."""

    commit: str
    committed_at: str
    file_sha256: str
    limits: Any  # read-only mapping metric -> limit


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BenchmarkError(
            f"cannot establish that the criterion is committed: git failed ({error})"
        ) from error
    return done.stdout.strip()


def require_frozen_criterion(
    asset: AssetRecord,
    criterion_path: Path = DEFAULT_CRITERION,
    *,
    plan_path: Path = DEFAULT_PLAN,
    repo_root: Path = Path("."),
) -> FrozenCriterion | None:
    """Refuse a holdout evaluation that has no frozen criterion; return it otherwise.

    For a role that is not a holdout (`CHARACTERISATION` and others) nothing is required and
    None is returned. For `VALIDATION` and `LOCKED_TEST` the criterion file must exist, carry a
    finite positive limit for every metric in `METRICS`, name the SHA-256 of the current plan
    and be tracked and unmodified in Git; the commit that froze it is returned.
    """
    if asset.split not in HOLDOUT_SPLITS:
        return None
    if not criterion_path.is_file():
        raise BenchmarkError(
            f"{asset.filename}: holdout evaluation refused, no frozen criterion at {criterion_path}"
        )
    try:
        document = load_strict_yaml(criterion_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise BenchmarkError(f"{criterion_path.name}: not valid YAML: {error}") from error
    if not isinstance(document, dict) or set(document) != {
        "criterion_version",
        "plan_sha256",
        "limits",
    }:
        raise BenchmarkError(
            f"{criterion_path.name}: must have exactly criterion_version, plan_sha256, limits"
        )
    version = document["criterion_version"]
    if type(version) is not int or version != CRITERION_VERSION:
        raise BenchmarkError(
            f"{criterion_path.name}: criterion_version must be {CRITERION_VERSION}"
        )
    plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if document["plan_sha256"] != plan_hash:
        raise BenchmarkError(f"{criterion_path.name}: refers to another version of the plan")
    limits = document["limits"]
    if not isinstance(limits, dict) or set(limits) != set(METRICS):
        raise BenchmarkError(f"{criterion_path.name}: limits must be exactly {list(METRICS)}")
    for name, limit in limits.items():
        if (
            isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(limit)
            or limit <= 0
        ):
            raise BenchmarkError(f"{criterion_path.name}: limit {name} must be finite and positive")
    try:
        relative = criterion_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        raise BenchmarkError(f"{criterion_path} is outside the repository {repo_root}") from None
    if _git(repo_root, "status", "--porcelain", "--", str(relative)):
        raise BenchmarkError(f"{criterion_path.name}: not committed or modified since its commit")
    line = _git(repo_root, "log", "-1", "--format=%H %cI", "--", str(relative))
    if not line:
        raise BenchmarkError(f"{criterion_path.name}: no commit contains this file")
    commit, committed_at = line.split(" ", 1)
    return FrozenCriterion(
        commit=commit,
        committed_at=committed_at,
        file_sha256=hashlib.sha256(criterion_path.read_bytes()).hexdigest(),
        limits=MappingProxyType({name: float(value) for name, value in limits.items()}),
    )
