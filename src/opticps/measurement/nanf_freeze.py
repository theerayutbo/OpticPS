"""NANF benchmark: the freeze record and the guard on the holdout read (plan Amendment 4 D6,
Amendment 5 F8, Amendment 6 G4 and G5). LITERATURE BENCHMARK / CALIBRATION ONLY.

`read_nanf_workbook(include_holdout=True)` returns holdout series only when the caller proves that
the Tx/Rx vector is frozen: a record `docs/benchmarks/NANF_FREEZE_RECORD.json` binds the plan pin,
the code identity, a named calibration artefact committed in the repository (path, SHA-256, commit),
the parameter vector inside that artefact and the calibration partition, and the caller passes the
record's `freeze_hash`. The default is deny: no record, no holdout. This module creates no record;
`build_freeze_record` only returns one for a later, deliberate freeze, and nothing is frozen by
importing it.

What this does not prove (plan Amendment 6, in the same words as
`docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md`): the guard catches accidents and casual re-tuning by
ordinary commits. Records inside the repository cannot prove the order of the calibration against a
holdout access, because commit dates and authors are typed by whoever commits and history can be
rewritten; only an external timestamp can. Nothing here is a date proof, and the Git checks below
(artefact tracked, unmodified at HEAD, commit an ancestor of HEAD) are accident checks, not
protection against deliberate tampering by someone who controls the repository.

Code identity (F8 as amended): every source file reachable by imports from the scoring entry
modules, found by parsing the imports (not a hand list), plus the configuration files. The plan
file is pinned separately by `plan_sha256`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from opticps.measurement.nanf_chain import B4_NAMES, B4_PARAMETERS, TxRxParameters

HOLDOUT_LOCKED = "HOLDOUT_LOCKED"
ROOT = Path(__file__).resolve().parents[3]
FREEZE_RECORD_PATH = ROOT / "docs/benchmarks/NANF_FREEZE_RECORD.json"
# the record that unlocks the REAL workbook is read from here and from nowhere else, so patching
# FREEZE_RECORD_PATH (a test-only record) cannot unlock a file with the real workbook's hash
COMMITTED_RECORD_PATH = FREEZE_RECORD_PATH
PLAN_PATH = ROOT / "docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md"
CALIBRATION_ARTIFACT_DIR = "docs/benchmarks/"
SRC_PREFIX = "src"
PACKAGE = "opticps"
# the scoring path: the entry modules whose imports (transitively) make up the code identity
ENTRY_MODULES = (
    "opticps.receiver.dfe",
    "opticps.measurement.nanf_chain",
    "opticps.measurement.nanf_scoring",
    "opticps.measurement.nanf_freeze",
    "opticps.measurement.nanf_import",
    "opticps.measurement.nanf_benchmark",
    "opticps.optical_channel.link",
    "opticps.optical_channel.fiber",
)
CONFIG_FILES = ("pyproject.toml", "uv.lock")
RECORD_KEYS = frozenset(
    {
        "plan_sha256",
        "code_identity",
        "parameters",
        "unidentifiable",
        "calibration",
        "calibration_partition_sha256",
        "freeze_hash",
    }
)
CALIBRATION_REF_KEYS = frozenset({"path", "sha256", "commit"})
ARTIFACT_KEYS = frozenset(
    {"parameters", "unidentifiable", "fit_result", "calibration_partition_sha256"}
)
FIT_RESULT_KEYS = frozenset(
    {"method", "converged", "n_evaluations", "n_calibration_points", "cost"}
)
MAX_RECORD_BYTES = 65_536
MAX_ARTIFACT_BYTES = 262_144
GIT_TIMEOUT_S = 30
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
# anything a hostile or damaged file can raise while being parsed or checked: always a refusal
_MALFORMED = (ValueError, TypeError, OverflowError, RecursionError, KeyError, AttributeError)


class HoldoutLockedError(ValueError):
    """A holdout read was refused: no valid proof of a freeze. The message holds no value."""

    code = HOLDOUT_LOCKED

    def __init__(self, message: str) -> None:
        super().__init__(f"{HOLDOUT_LOCKED}: {message}")


@dataclass(frozen=True)
class FreezeRecord:
    """A verified freeze record."""

    plan_sha256: str
    code_identity: str
    parameters: TxRxParameters
    unidentifiable: tuple[str, ...]
    calibration_path: str
    calibration_sha256: str
    calibration_commit: str
    calibration_partition_sha256: str
    freeze_hash: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_sha256(path: Path | None = None) -> str:
    """SHA-256 of the plan file as it is now."""
    return _sha256(PLAN_PATH if path is None else path)


# --- code identity from imports (F8 as amended by Amendment 6) -----------------------------------


def _module_file(module: str, base: Path) -> Path | None:
    """The source file of a module of the package under `base/src`, or None if it is not ours."""
    parts = module.split(".")
    if parts[0] != PACKAGE:
        return None
    stem = base / SRC_PREFIX / Path(*parts)
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imported_modules(tree: ast.AST, package: str) -> set[str]:
    """Names of all modules a parsed source imports (also in function bodies, TYPE_CHECKING)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                module = ".".join([*anchor, *(node.module.split(".") if node.module else [])])
            else:
                module = node.module or ""
            if module:
                found.add(module)
                found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def reachable_sources(root: Path | None = None) -> tuple[str, ...]:
    """Every source file of the package reachable by imports from `ENTRY_MODULES`, sorted.

    A module brings in its own file, the `__init__.py` of each of its parent packages (they run on
    import) and, by parsing, every module its source imports. Files outside the package (the
    standard library, NumPy) are not listed: their versions are pinned by `uv.lock`.
    """
    base = ROOT if root is None else root
    seen: dict[str, Path] = {}
    queue = list(ENTRY_MODULES)
    while queue:
        module = queue.pop()
        file = _module_file(module, base)
        if file is None or module in seen:
            continue
        seen[module] = file
        parts = module.split(".")
        queue.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        is_package = file.name == "__init__.py"
        package = module if is_package else ".".join(parts[:-1])
        tree = ast.parse(file.read_bytes(), filename=str(file))
        queue.extend(_imported_modules(tree, package))
    return tuple(sorted(file.relative_to(base).as_posix() for file in seen.values()))


def identity_files(root: Path | None = None) -> tuple[str, ...]:
    """The files of the code identity: reachable sources and the configuration files, sorted."""
    return tuple(sorted({*reachable_sources(root), *CONFIG_FILES}))


def code_identity(root: Path | None = None, files: Iterable[str] | None = None) -> str:
    """SHA-256 of the lines `path NUL sha256(file)`, sorted by path (plan F8 as amended)."""
    base = ROOT if root is None else root
    names = identity_files(root) if files is None else tuple(files)
    lines = b"".join(
        name.encode() + b"\x00" + _sha256(base / name).encode() + b"\n" for name in names
    )
    return hashlib.sha256(lines).hexdigest()


# --- canonical hashing ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, separators "," and ":", ASCII-escaped, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_freeze_hash(
    plan_pin: str,
    identity: str,
    parameters: Mapping[str, float],
    unidentifiable: Iterable[str],
    calibration: Mapping[str, str],
    partition: str,
) -> str:
    """The hash of the content fields of a record."""
    body = {
        "plan_sha256": plan_pin,
        "code_identity": identity,
        "parameters": dict(parameters),
        "unidentifiable": list(unidentifiable),
        "calibration": dict(calibration),
        "calibration_partition_sha256": partition,
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _refuse(message: str) -> HoldoutLockedError:
    return HoldoutLockedError(message)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


# --- the calibration artefact (G4) ---------------------------------------------------------------


def calibration_artifact(
    parameters: TxRxParameters,
    unidentifiable: Iterable[str],
    fit_result: Mapping[str, Any],
    partition: str,
) -> bytes:
    """The bytes of a calibration artefact: the vector, its flags, the fit result and the partition.

    Written by a later calibration step; nothing here runs a fit. The bytes are canonical JSON.
    """
    return canonical_json(
        {
            "parameters": parameters.as_dict(),
            "unidentifiable": list(unidentifiable),
            "fit_result": dict(fit_result),
            "calibration_partition_sha256": partition,
        }
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
    }
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        capture_output=True,
        timeout=GIT_TIMEOUT_S,
        env=env,
        check=False,
    )


def _blob_sha(root: Path, revision: str, rel: str) -> str | None:
    done = _git(root, "cat-file", "blob", f"{revision}:{rel}")
    if done.returncode != 0:
        return None
    return hashlib.sha256(done.stdout).hexdigest()


def _prior_of(name: str) -> float:
    return next(spec.prior for spec in B4_PARAMETERS if spec.name == name)


def _check_flags(flags: object) -> tuple[str, ...]:
    if (
        not isinstance(flags, list)
        or not all(isinstance(f, str) for f in flags)
        or len(set(flags)) != len(flags)
        or not set(flags) <= set(B4_NAMES)
    ):
        raise _refuse("the unidentifiable list is not a set of B4 names")
    return tuple(flags)


def _check_priors(parameters: TxRxParameters, flags: tuple[str, ...]) -> None:
    """B4.4: a flagged parameter is set to its prior, and no other is refitted."""
    values = parameters.as_dict()
    for name in flags:
        if values[name] != _prior_of(name):
            raise _refuse(f"the flagged parameter {name} is not at its prior (plan B4.4)")


def _check_calibration_ref(ref: object) -> dict[str, str]:
    if not isinstance(ref, dict) or set(ref) != CALIBRATION_REF_KEYS:
        raise _refuse("the calibration reference does not have exactly path, sha256 and commit")
    path, digest, commit = ref["path"], ref["sha256"], ref["commit"]
    if not (isinstance(path, str) and isinstance(digest, str) and isinstance(commit, str)):
        raise _refuse("the calibration reference fields must be strings")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "\\" in path
        or pure.as_posix() != path
        or not path.startswith(CALIBRATION_ARTIFACT_DIR)
        or pure.suffix != ".json"
    ):
        raise _refuse(
            f"the calibration artefact must be a .json file under {CALIBRATION_ARTIFACT_DIR}"
        )
    if _HEX64.match(digest) is None or _HEX40.match(commit) is None:
        raise _refuse("the calibration reference holds a malformed digest or commit")
    return {"path": path, "sha256": digest, "commit": commit}


def _verify_calibration(
    root: Path,
    ref: dict[str, str],
    parameters: TxRxParameters,
    flags: tuple[str, ...],
    partition: str,
) -> None:
    """Refuse unless the named artefact is committed, unmodified, ancestral and holds the vector."""
    rel = ref["path"]
    file = root / rel
    if file.is_symlink() or not file.is_file():
        raise _refuse("the calibration artefact is absent")
    raw = file.read_bytes()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise _refuse("the calibration artefact is too large")
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise _refuse("the calibration artefact does not match its recorded SHA-256")
    try:
        tracked = _git(root, "ls-files", "--error-unmatch", "--", rel)
        head_blob = _blob_sha(root, "HEAD", rel)
        commit_blob = _blob_sha(root, ref["commit"], rel)
        ancestor = _git(root, "merge-base", "--is-ancestor", ref["commit"], "HEAD")
    except (OSError, subprocess.SubprocessError):
        raise _refuse("Git could not be run to verify the calibration artefact") from None
    if tracked.returncode != 0 or head_blob is None:
        raise _refuse("the calibration artefact is not committed")
    if head_blob != ref["sha256"]:
        raise _refuse("the calibration artefact has uncommitted changes")
    if commit_blob != ref["sha256"]:
        raise _refuse("the named commit does not hold the calibration artefact")
    if ancestor.returncode != 0:
        raise _refuse("the commit holding the calibration artefact is not an ancestor of HEAD")
    artefact = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if not isinstance(artefact, dict) or set(artefact) != ARTIFACT_KEYS:
        raise _refuse("the calibration artefact does not have exactly the declared fields")
    fit = artefact["fit_result"]
    at_defaults = artefact["parameters"] == TxRxParameters().as_dict()
    if not isinstance(fit, dict) or not fit:
        raise _refuse(
            "the calibration artefact is at the default vector with no fit result"
            if at_defaults
            else "the calibration artefact has no fit result"
        )
    if set(fit) != FIT_RESULT_KEYS:
        raise _refuse("the fit result does not have exactly the declared fields")
    n_eval, n_pts, cost = fit["n_evaluations"], fit["n_calibration_points"], fit["cost"]
    if (
        not isinstance(fit["method"], str)
        or not fit["method"]
        or not isinstance(fit["converged"], bool)
        or isinstance(n_eval, bool)
        or not isinstance(n_eval, int)
        or n_eval < 1
        or isinstance(n_pts, bool)
        or not isinstance(n_pts, int)
        or n_pts < 1
        or isinstance(cost, bool)
        or not isinstance(cost, int | float)
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise _refuse("the fit result is not a valid result of a calibration")
    if TxRxParameters.from_mapping(artefact["parameters"]) != parameters:
        raise _refuse("the record vector is not the vector inside the calibration artefact")
    if _check_flags(artefact["unidentifiable"]) != flags:
        raise _refuse("the record flags are not the flags inside the calibration artefact")
    if artefact["calibration_partition_sha256"] != partition:
        raise _refuse("the calibration artefact was made on another calibration partition")


def current_partition() -> str:
    """The calibration partition hash of the importer now (lazy: the importer imports us)."""
    from opticps.measurement.nanf_import import calibration_partition_sha256

    return calibration_partition_sha256()


def build_freeze_record(
    artifact_path: str,
    *,
    plan_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return the record for a committed calibration artefact, using the plan and code as now.

    Writes nothing. The artefact is verified like a reader would (`HoldoutLockedError` if it is
    absent, uncommitted, modified, not an ancestor of HEAD, at the defaults with no fit result, or a
    flagged parameter is not at its prior).
    """
    base = ROOT if root is None else root
    try:
        file = base / artifact_path
        if file.is_symlink() or not file.is_file():
            raise _refuse("the calibration artefact is absent")
        raw = file.read_bytes()
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise _refuse("the calibration artefact is too large")
        artefact = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        parameters = TxRxParameters.from_mapping(artefact["parameters"])
        flags = _check_flags(artefact["unidentifiable"])
        _check_priors(parameters, flags)
        digest = hashlib.sha256(raw).hexdigest()
        done = _git(base, "log", "-n", "1", "--format=%H", "HEAD", "--", artifact_path)
        commit = done.stdout.decode("ascii", "replace").strip()
        ref = _check_calibration_ref({"path": artifact_path, "sha256": digest, "commit": commit})
        partition = current_partition()
        _verify_calibration(base, ref, parameters, flags, partition)
        pin = plan_sha256(plan_path)
        identity = code_identity(root)
    except HoldoutLockedError:
        raise
    except (*_MALFORMED, OSError, subprocess.SubprocessError, SyntaxError):
        raise _refuse("the calibration artefact or the code could not be read") from None
    values = parameters.as_dict()
    return {
        "plan_sha256": pin,
        "code_identity": identity,
        "parameters": values,
        "unidentifiable": list(flags),
        "calibration": ref,
        "calibration_partition_sha256": partition,
        "freeze_hash": compute_freeze_hash(pin, identity, values, flags, ref, partition),
    }


# --- the reader's side ---------------------------------------------------------------------------


def freeze_record_present() -> bool:
    """True if anything exists at the record path (a broken or forged record counts as present)."""
    return FREEZE_RECORD_PATH.exists() or FREEZE_RECORD_PATH.is_symlink()


def load_freeze_record(
    *,
    record_path: Path | None = None,
    plan_path: Path | None = None,
    root: Path | None = None,
) -> FreezeRecord:
    """Return the verified record or raise `HoldoutLockedError`. Default deny.

    Checks, in this order: the record file exists, is a regular file and is small; it parses as one
    JSON object with no duplicate keys and exactly the seven fields; the digests are digests; the
    six parameters are exactly the B4 names inside their ranges; `unidentifiable` is a set of B4
    names and each flagged parameter is at its prior; the stored hash equals the hash recomputed
    from the fields; the calibration artefact is present, its SHA-256 matches, it is committed and
    unmodified at HEAD, the named commit holds it and is an ancestor of HEAD, it holds a fit result
    (not the default vector with none), and it holds the same vector, flags and partition;
    `plan_sha256` equals the SHA-256 of the plan file now; `code_identity` equals the code identity
    now. Any malformed content (huge integers, deep nesting, wrong types) is a refusal, never a raw
    exception.
    """
    path = FREEZE_RECORD_PATH if record_path is None else record_path
    base = ROOT if root is None else root
    try:
        return _load(path, plan_path, base)
    except HoldoutLockedError:
        raise
    except (*_MALFORMED, OSError, subprocess.SubprocessError, SyntaxError, UnicodeDecodeError):
        raise _refuse("the freeze record is malformed or cannot be verified") from None


def _load(path: Path, plan_path: Path | None, base: Path) -> FreezeRecord:
    if path.is_symlink() or not path.is_file():
        raise _refuse("there is no freeze record, so nothing is frozen")
    raw = path.read_bytes()
    if len(raw) > MAX_RECORD_BYTES:
        raise _refuse("the freeze record is too large")
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _refuse("the freeze record is not valid JSON with unique keys") from None
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise _refuse("the freeze record does not have exactly the declared fields")
    for key in ("plan_sha256", "code_identity", "freeze_hash", "calibration_partition_sha256"):
        value = record[key]
        if not isinstance(value, str) or _HEX64.match(value) is None:
            raise _refuse(f"the freeze record field {key} is not a SHA-256 digest")
    try:
        parameters = TxRxParameters.from_mapping(record["parameters"])
    except (ValueError, TypeError, OverflowError):
        raise _refuse("the freeze record parameters are not a valid B4 vector") from None
    flags = _check_flags(record["unidentifiable"])
    _check_priors(parameters, flags)
    ref = _check_calibration_ref(record["calibration"])
    recomputed = compute_freeze_hash(
        record["plan_sha256"],
        record["code_identity"],
        parameters.as_dict(),
        flags,
        ref,
        record["calibration_partition_sha256"],
    )
    if record["freeze_hash"] != recomputed:
        raise _refuse("the freeze record is not consistent with its own hash")
    _verify_calibration(base, ref, parameters, flags, record["calibration_partition_sha256"])
    if record["calibration_partition_sha256"] != current_partition():
        raise _refuse("the calibration partition of the importer has changed since the freeze")
    if record["plan_sha256"] != plan_sha256(plan_path):
        raise _refuse("the plan has changed since the freeze (its SHA-256 differs from the record)")
    if record["code_identity"] != code_identity(base):
        raise _refuse(
            "the code has changed since the freeze (its identity differs from the record)"
        )
    return FreezeRecord(
        record["plan_sha256"],
        record["code_identity"],
        parameters,
        flags,
        ref["path"],
        ref["sha256"],
        ref["commit"],
        record["calibration_partition_sha256"],
        recomputed,
    )


def require_freeze(
    freeze_hash: object,
    *,
    record_path: Path | None = None,
    plan_path: Path | None = None,
    root: Path | None = None,
) -> FreezeRecord:
    """Return the verified record if the caller's hash is its hash; else raise. Default deny."""
    if not isinstance(freeze_hash, str) or _HEX64.match(freeze_hash) is None:
        raise _refuse("a holdout read needs the freeze hash of a committed freeze record")
    record = load_freeze_record(record_path=record_path, plan_path=plan_path, root=root)
    if freeze_hash != record.freeze_hash:
        raise _refuse("the freeze hash given does not match the freeze record")
    return record
