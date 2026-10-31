"""Holdout guards for the TERIPHIC fit/holdout plan (Revision 2, sections R.2 to R.5 and R2.3).

Three refusals, all offline:

- a `VALIDATION` or `LOCKED_TEST` asset is not evaluated unless a criterion file and the other
  inputs the plan names are committed in Git, byte-identical to the working tree, and the
  criterion is complete, tied to the committed plan and has never changed its `limits` since the
  first commit that held them (`require_frozen_criterion`);
- a BER needs a transmitted sequence stated by a source, never one inferred from a capture
  (`require_reference_for_ber`);
- 2 km (the selection stage) cannot end VALIDATED, and 10 km cannot after a failed 2 km, with an
  unrun shared-sequence check, or after the file is burned (`allowed_verdicts`).

What the freeze check proves, and what it does not. It proves consistency with the Git history
that is present in this local repository: the bytes it returns were read from the commit `HEAD`,
not from the working file; the limits it returns are the limits of the first commit that held
non-null limits; no later commit on the followed history of the file changed them. It does not
prove a date. Git history can be rewritten locally. An amended or rewritten first commit leaves
no trace here (undetectable), and a commit date, author or committer, is whatever its author
typed. Only an external timestamp, such as the same commit pushed to a remote the owner does not
control, shows that the criterion existed before a given time; that is an owner action and the
tool cannot perform or check it. The tool cannot see statistics computed outside it either.

Nothing here reads a capture. The only external process is `git`, run on the local repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import math
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

import yaml

from opticps.benchmarks.catalog import load_strict_yaml
from opticps.benchmarks.provenance import (
    AssetRecord,
    BenchmarkError,
    ErrorCode,
    Provenance,
    Split,
)

CRITERION_VERSION = 2
CRITERION_KEYS = frozenset(
    {"criterion_version", "plan_sha256", "limits", "b2b_basis", "multipliers"}
)
HOLDOUT_SPLITS = frozenset({Split.VALIDATION, Split.LOCKED_TEST})
# Metrics named by the plan (R.4). A criterion must give a limit for each of them.
METRICS = (
    "M1_level_spacing",
    "M2_wasserstein1_amplitude",
    "M3_quantile_error",
    "M4_log_spectral_distance",
)
# Files the plan requires to be committed before a holdout is evaluated (section 2 and R.4).
REQUIRED_INPUTS: Mapping[Split, tuple[str, ...]] = MappingProxyType(
    {
        Split.VALIDATION: ("b2b_model", "scenario_list"),
        Split.LOCKED_TEST: ("frozen_parameters", "selected_scenario", "evaluation_script"),
    }
)
DEFAULT_PLAN = Path("docs/benchmarks/FIT_HOLDOUT_PLAN.md")
DEFAULT_CRITERION = Path("docs/benchmarks/TERIPHIC_CRITERION.yaml")
_LIMIT_RELATIVE_TOLERANCE = 1e-9


class Verdict(StrEnum):
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNIDENTIFIABLE_PARAMETER = "UNIDENTIFIABLE_PARAMETER"
    BLOCKED = "BLOCKED"
    # A label, not a confirmatory outcome: a burned 10 km file, or a statistic on a file that
    # shares a transmitted sequence with the characterisation file (plan section 2, R.2).
    EXPLORATORY = "EXPLORATORY"


class ValidationStage(StrEnum):
    """Result of the 2 km selection stage, as the 10 km evaluation needs to know it."""

    NOT_DONE = "NOT_DONE"
    FAILED = "FAILED"
    NOT_FAILED = "NOT_FAILED"  # any 2 km result other than FAILED, reported without a verdict


class SequenceCheck(StrEnum):
    """Outcome of the shared-sequence check required by R.2 before VALIDATED."""

    NOT_RUN = "NOT_RUN"
    SHARED = "SHARED"  # a sequence recovered from B2B was found in this length
    NOT_SHARED = "NOT_SHARED"


class HoldoutState(StrEnum):
    INTACT = "INTACT"
    BURNED = "BURNED"  # anything was changed after the result was seen (plan section 2)


def _enum(kind: type[StrEnum], value: object, name: str) -> None:
    if value is not None and not isinstance(value, kind):
        raise BenchmarkError(f"{name} must be a {kind.__name__}, got {value!r}")


def allowed_verdicts(
    split: Split,
    *,
    validation_stage: ValidationStage | None = None,
    sequence_check: SequenceCheck | None = None,
    state: HoldoutState | None = None,
) -> frozenset[Verdict]:
    """Verdicts a role may end with. Every state argument defaults to "not established".

    Only the locked test can be VALIDATED, and only when the file is intact, the 2 km stage was
    done and did not fail, and the shared-sequence check was run and found no shared sequence.
    A state that is missing (None) never grants it. A burned file ends EXPLORATORY or BLOCKED. A
    file with a shared sequence may additionally be labelled EXPLORATORY.
    """
    _enum(ValidationStage, validation_stage, "validation_stage")
    _enum(SequenceCheck, sequence_check, "sequence_check")
    _enum(HoldoutState, state, "state")
    open_verdicts = frozenset(
        {Verdict.FAILED, Verdict.INCONCLUSIVE, Verdict.UNIDENTIFIABLE_PARAMETER, Verdict.BLOCKED}
    )
    if split is Split.LOCKED_TEST:
        if state is HoldoutState.BURNED:
            return frozenset({Verdict.EXPLORATORY, Verdict.BLOCKED})
        verdicts = set(open_verdicts)
        if sequence_check is SequenceCheck.SHARED:
            verdicts.add(Verdict.EXPLORATORY)
        if (
            state is HoldoutState.INTACT
            and validation_stage is ValidationStage.NOT_FAILED
            and sequence_check is SequenceCheck.NOT_SHARED
        ):
            verdicts.add(Verdict.VALIDATED)
        return frozenset(verdicts)
    if split is Split.VALIDATION:
        return open_verdicts
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


class _Mint:
    """Private token. Only `require_frozen_criterion` passes it."""


_MINT = _Mint()


@dataclass(frozen=True, init=False)
class FrozenCriterion:
    """A criterion that passed `require_frozen_criterion`; a report must carry `commit`.

    Python cannot make a class unforgeable: the constructor refuses, and so do `replace`,
    `copy` and `pickle`, but code that calls `object.__new__` and `object.__setattr__` can still
    build one. The guard stops mistakes and shortcuts, not a deliberate forgery in-process.

    `commit` is the first commit of the followed history that holds non-null limits.
    `committed_at` and `authored_at` are the dates Git stores in that commit, as stated: anyone
    can set them (backdating) and the tool cannot tell. `head_commit` is the commit the inputs
    were read from. `file_sha256` is the hash of the committed criterion bytes.
    """

    commit: str
    committed_at: str
    authored_at: str
    head_commit: str
    file_sha256: str
    limits: Any  # read-only mapping metric -> limit, taken from the committed bytes
    inputs: Any  # read-only mapping input name -> SHA-256 of its committed bytes

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("FrozenCriterion is issued by require_frozen_criterion only")

    def __reduce__(self) -> NoReturn:
        raise TypeError("FrozenCriterion cannot be copied or pickled")

    @classmethod
    def _issue(cls, mint: object, **fields: Any) -> FrozenCriterion:
        if mint is not _MINT:
            raise TypeError("FrozenCriterion is issued by require_frozen_criterion only")
        issued = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(issued, name, value)
        return issued


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    # GIT_* variables can point Git at another repository or object store; `git replace`
    # refs can substitute commits, which is a local history rewrite.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        return subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=off", *args],
            capture_output=True,
            check=False,
            timeout=60,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BenchmarkError(
            f"cannot establish that the criterion is committed: git failed ({error})"
        ) from error


def _git_ok(root: Path, *args: str) -> bytes:
    done = _git(root, *args)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()[:200]
        raise BenchmarkError(
            f"cannot establish that the criterion is committed: git {args[0]} failed ({detail})"
        )
    return done.stdout


def _blob(root: Path, revision: str, relative: str) -> bytes | None:
    """Bytes of `relative` in the commit `revision`, or None when the commit has no such file."""
    spec = f"{revision}:{relative}"
    done = _git(root, "cat-file", "blob", spec)
    if done.returncode == 0:
        return done.stdout
    if _git(root, "rev-parse", "--verify", "--quiet", spec).returncode != 0:
        return None  # the commit has no such path
    return _git_ok(root, "cat-file", "blob", spec)  # exists but unreadable: a typed error


def _relative(root: Path, path: Path, what: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise BenchmarkError(f"{path} ({what}) is outside the repository {root}") from None


def _committed_bytes(root: Path, path: Path, what: str) -> tuple[bytes, str]:
    """The bytes of `path` at HEAD, after checking that the working file has the same bytes.

    The comparison is on bytes, never on `git status`, so `--assume-unchanged`,
    `--skip-worktree` and a stale index cannot hide a change.
    """
    relative = _relative(root, path, what)
    committed = _blob(root, "HEAD", relative)
    if committed is None:
        raise BenchmarkError(f"{path.name}: not committed, no commit contains this file ({what})")
    try:
        working = path.read_bytes()
    except OSError as error:
        raise BenchmarkError(f"{path.name}: cannot be read ({what}): {error}") from error
    if working != committed:
        raise BenchmarkError(f"{path.name}: not committed or modified since HEAD ({what})")
    return committed, relative


def _parse(data: bytes, name: str) -> Any:
    try:
        return load_strict_yaml(data.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise BenchmarkError(f"{name}: not valid UTF-8: {error}") from error
    except yaml.YAMLError as error:
        raise BenchmarkError(f"{name}: not valid YAML: {error}") from error


def _positive_finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{where} must be finite and positive")
    try:
        number = float(value)
    except OverflowError:
        raise BenchmarkError(f"{where} must be finite and positive (too large)") from None
    if not math.isfinite(number) or number <= 0:
        raise BenchmarkError(f"{where} must be finite and positive")
    return number


def _metric_table(document: Mapping[str, Any], key: str, name: str) -> dict[str, float]:
    table = document[key]
    if not isinstance(table, dict) or set(table) != set(METRICS):
        raise BenchmarkError(f"{name}: {key} must be exactly {list(METRICS)}")
    return {m: _positive_finite(table[m], f"{name}: {key} {m}") for m in METRICS}


def _limits_signature(data: bytes) -> tuple[tuple[str, str], ...] | None:
    """The `limits` of one committed version of the file, or None when it holds none.

    Used on history: a version that does not parse, is not a mapping or has `limits: null` holds
    no limits. Numbers are compared with their type, so 1 and 1.0 count as a change.
    """
    try:
        document = load_strict_yaml(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(document, dict) or document.get("limits") is None:
        return None
    limits = document["limits"]
    if not isinstance(limits, dict):
        return (("<limits>", repr(limits)),)
    return tuple(sorted((str(k), f"{type(v).__name__}:{v!r}") for k, v in limits.items()))


def _history(root: Path, relative: str) -> list[tuple[str, str, str, str]]:
    """Commits that touched the file, oldest first: (commit, committer date, author date, path).

    Follows renames. The order is the parent-before-child order of the commit graph, not date
    order, because a date can be forged.
    """
    if _git_ok(root, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise BenchmarkError("the repository is a shallow clone: the first commit is not visible")
    text = _git_ok(
        root,
        "log",
        "--follow",
        "--topo-order",
        "--no-renames",
        "--name-only",
        "--format=@@%H %cI %aI",
        "--",
        relative,
    ).decode("utf-8", "replace")
    entries: list[tuple[str, str, str, str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("@@"):
            current = line[2:].split(" ")
            if len(current) != 3:
                raise BenchmarkError("unreadable git log output")
        elif line.strip() and current is not None:
            entries.append((current[0], current[1], current[2], line))
            current = None
    entries.reverse()
    return entries


def _check_criterion(document: Any, name: str, plan_hash: str) -> dict[str, float]:
    if not isinstance(document, dict) or set(document) != CRITERION_KEYS:
        raise BenchmarkError(f"{name}: must have exactly {sorted(CRITERION_KEYS)}")
    version = document["criterion_version"]
    if type(version) is not int or version != CRITERION_VERSION:
        raise BenchmarkError(f"{name}: criterion_version must be {CRITERION_VERSION}")
    if document["plan_sha256"] != plan_hash:
        raise BenchmarkError(f"{name}: refers to another version of the plan")
    limits = _metric_table(document, "limits", name)
    basis = _metric_table(document, "b2b_basis", name)
    multipliers = _metric_table(document, "multipliers", name)
    for metric in METRICS:
        if not math.isclose(
            limits[metric], basis[metric] * multipliers[metric], rel_tol=_LIMIT_RELATIVE_TOLERANCE
        ):
            raise BenchmarkError(
                f"{name}: limit {metric} is not b2b_basis x multiplier ({basis[metric]} x"
                f" {multipliers[metric]})"
            )
    return limits


def require_frozen_criterion(
    asset: AssetRecord,
    criterion_path: Path = DEFAULT_CRITERION,
    *,
    plan_path: Path = DEFAULT_PLAN,
    repo_root: Path = Path("."),
    inputs: Mapping[str, Path] | None = None,
    validation_stage: ValidationStage | None = None,
) -> FrozenCriterion | None:
    """Refuse a holdout evaluation that has no frozen criterion; return it otherwise.

    `CHARACTERISATION` needs nothing (None). `RESERVED` and `UNASSIGNED` are refused: nothing
    may be evaluated there (plan section 1, rule 5). For `VALIDATION` and `LOCKED_TEST`:

    - the plan, the criterion and every file in `inputs` (the names in `REQUIRED_INPUTS`) must
      be committed, and their bytes in the working tree must equal the bytes at `HEAD`;
    - the criterion is read from the `HEAD` bytes, never from a working file; it must have
      exactly the keys of `CRITERION_KEYS`, a finite positive limit equal to `b2b_basis` times
      the stated multiplier for every metric, and the SHA-256 of the committed plan;
    - the first commit of the followed history that holds non-null `limits` is the freeze commit,
      and no later commit may have changed them (a re-commit with other limits is refused);
    - for `LOCKED_TEST` the 2 km stage must be done (`validation_stage` FAILED or NOT_FAILED).

    Limits of this proof are in the module docstring: it does not prove when the commit was
    made, and an amended first commit is undetectable. Every failure is a `BenchmarkError`.
    """
    if asset.split is Split.CHARACTERISATION:
        return None
    if asset.split not in HOLDOUT_SPLITS:
        raise BenchmarkError(
            f"{asset.filename}: evaluation refused, role {asset.split.value} is not open"
        )
    required = REQUIRED_INPUTS[asset.split]
    supplied = dict(inputs or {})
    if set(supplied) != set(required):
        raise BenchmarkError(
            f"{asset.filename}: holdout evaluation refused, the inputs must be exactly"
            f" {list(required)}"
        )
    if asset.split is Split.LOCKED_TEST and not (
        validation_stage is ValidationStage.FAILED or validation_stage is ValidationStage.NOT_FAILED
    ):
        raise BenchmarkError(
            f"{asset.filename}: the 10 km file is not evaluated before the 2 km stage is done"
        )
    if not criterion_path.exists() and not criterion_path.is_symlink():
        raise BenchmarkError(
            f"{asset.filename}: holdout evaluation refused, no frozen criterion at {criterion_path}"
        )
    plan_bytes, _ = _committed_bytes(repo_root, plan_path, "plan")
    plan_hash = hashlib.sha256(plan_bytes).hexdigest()
    criterion_bytes, relative = _committed_bytes(repo_root, criterion_path, "criterion")
    name = criterion_path.name
    limits = _check_criterion(_parse(criterion_bytes, name), name, plan_hash)
    input_hashes: dict[str, str] = {}
    for key in required:
        input_bytes, _ = _committed_bytes(repo_root, supplied[key], key)
        input_hashes[key] = hashlib.sha256(input_bytes).hexdigest()
    first: tuple[str, str, str, str] | None = None
    baseline: tuple[tuple[str, str], ...] | None = None
    for commit, committed_at, authored_at, path_then in _history(repo_root, relative):
        data = _blob(repo_root, commit, path_then)
        signature = _limits_signature(data) if data is not None else None
        if baseline is None:
            if signature is not None:
                baseline, first = signature, (commit, committed_at, authored_at, path_then)
        elif signature != baseline:
            raise BenchmarkError(
                f"{name}: limits changed after the first commit that held them"
                f" ({first[0][:12] if first else '?'}); changed in {commit[:12]}"
            )
    if first is None or _limits_signature(criterion_bytes) != baseline:
        raise BenchmarkError(f"{name}: no commit in the followed history holds these limits")
    head = _git_ok(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
    return FrozenCriterion._issue(
        _MINT,
        commit=first[0],
        committed_at=first[1],
        authored_at=first[2],
        head_commit=head,
        file_sha256=hashlib.sha256(criterion_bytes).hexdigest(),
        limits=MappingProxyType(limits),
        inputs=MappingProxyType(input_hashes),
    )
