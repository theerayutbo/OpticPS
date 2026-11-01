"""NANF benchmark: the freeze record and the guard on the holdout read (plan Amendment 4 D6,
Amendment 5 F8). LITERATURE BENCHMARK / CALIBRATION ONLY.

`read_nanf_workbook(include_holdout=True)` returns holdout series only when the caller proves that
the Tx/Rx vector is frozen: a committed record `docs/benchmarks/NANF_FREEZE_RECORD.json` holds the
hashed vector, the plan pin and the code identity, and the caller passes the record's `freeze_hash`.
The default is deny: no record, no holdout. This module creates no record; `build_freeze_record`
only returns one for a later, deliberate freeze, and nothing is frozen by importing it.

That the record file is committed to Git before a holdout read is a process requirement of the plan;
the code checks the file's content and its agreement with the live plan and code, not Git state.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opticps.measurement.nanf_chain import B4_NAMES, TxRxParameters

HOLDOUT_LOCKED = "HOLDOUT_LOCKED"
ROOT = Path(__file__).resolve().parents[3]
FREEZE_RECORD_PATH = ROOT / "docs/benchmarks/NANF_FREEZE_RECORD.json"
PLAN_PATH = ROOT / "docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md"
CODE_FILES = (
    "src/opticps/receiver/dfe.py",
    "src/opticps/measurement/nanf_chain.py",
    "src/opticps/measurement/nanf_scoring.py",
    "src/opticps/measurement/nanf_freeze.py",
)
RECORD_KEYS = frozenset(
    {"plan_sha256", "code_identity", "parameters", "unidentifiable", "freeze_hash"}
)
MAX_RECORD_BYTES = 65_536
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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
    freeze_hash: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_sha256(path: Path | None = None) -> str:
    """SHA-256 of the plan file as it is now."""
    return _sha256(PLAN_PATH if path is None else path)


def code_identity(root: Path | None = None, files: Iterable[str] | None = None) -> str:
    """SHA-256 of the lines `path NUL sha256(file)`, in the declared order (plan F8)."""
    base = ROOT if root is None else root
    lines = b"".join(
        name.encode() + b"\x00" + _sha256(base / name).encode() + b"\n"
        for name in (CODE_FILES if files is None else tuple(files))
    )
    return hashlib.sha256(lines).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, separators "," and ":", ASCII-escaped, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_freeze_hash(
    plan_pin: str, identity: str, parameters: Mapping[str, float], unidentifiable: Iterable[str]
) -> str:
    """The hash of the four content fields of a record."""
    body = {
        "plan_sha256": plan_pin,
        "code_identity": identity,
        "parameters": dict(parameters),
        "unidentifiable": list(unidentifiable),
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()


def build_freeze_record(
    parameters: TxRxParameters | Mapping[str, float],
    unidentifiable: Iterable[str] = (),
    *,
    plan_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return the record for a vector, using the plan and code as they are now. Writes nothing."""
    vector = (
        parameters
        if isinstance(parameters, TxRxParameters)
        else TxRxParameters.from_mapping(dict(parameters))
    )
    flags = tuple(unidentifiable)
    if len(set(flags)) != len(flags) or not set(flags) <= set(B4_NAMES):
        raise ValueError("unidentifiable must be distinct names of the B4 parameters")
    values = vector.as_dict()
    pin = plan_sha256(plan_path)
    identity = code_identity(root)
    return {
        "plan_sha256": pin,
        "code_identity": identity,
        "parameters": values,
        "unidentifiable": list(flags),
        "freeze_hash": compute_freeze_hash(pin, identity, values, flags),
    }


def _refuse(message: str) -> HoldoutLockedError:
    return HoldoutLockedError(message)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def require_freeze(
    freeze_hash: object,
    *,
    record_path: Path | None = None,
    plan_path: Path | None = None,
    root: Path | None = None,
) -> FreezeRecord:
    """Return the verified record or raise HoldoutLockedError. Default deny.

    Checks, in this order: the caller's hash is a 64-digit lower-case hex string; the record file
    exists, is a regular file and is small; it parses as one JSON object with no duplicate keys and
    exactly the five fields; the six parameters are exactly the B4 names inside their ranges;
    `unidentifiable` is a set of B4 names; the stored hash equals the hash recomputed from the
    fields and equals the caller's; `plan_sha256` equals the SHA-256 of the plan file now;
    `code_identity` equals the code identity now.
    """
    if not isinstance(freeze_hash, str) or _HEX64.match(freeze_hash) is None:
        raise _refuse("a holdout read needs the freeze hash of a committed freeze record")
    path = FREEZE_RECORD_PATH if record_path is None else record_path
    try:
        if path.is_symlink() or not path.is_file():
            raise _refuse("there is no freeze record, so nothing is frozen")
        raw = path.read_bytes()
    except OSError:
        raise _refuse("the freeze record cannot be read") from None
    if len(raw) > MAX_RECORD_BYTES:
        raise _refuse("the freeze record is too large")
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, UnicodeDecodeError):
        raise _refuse("the freeze record is not valid JSON with unique keys") from None
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise _refuse("the freeze record does not have exactly the declared fields")
    for key in ("plan_sha256", "code_identity", "freeze_hash"):
        value = record[key]
        if not isinstance(value, str) or _HEX64.match(value) is None:
            raise _refuse(f"the freeze record field {key} is not a SHA-256 digest")
    try:
        parameters = TxRxParameters.from_mapping(record["parameters"])
    except (ValueError, TypeError):
        raise _refuse("the freeze record parameters are not a valid B4 vector") from None
    flags = record["unidentifiable"]
    if (
        not isinstance(flags, list)
        or not all(isinstance(f, str) for f in flags)
        or len(set(flags)) != len(flags)
        or not set(flags) <= set(B4_NAMES)
    ):
        raise _refuse("the freeze record unidentifiable list is not a set of B4 names")
    recomputed = compute_freeze_hash(
        record["plan_sha256"], record["code_identity"], parameters.as_dict(), flags
    )
    if record["freeze_hash"] != recomputed:
        raise _refuse("the freeze record is not consistent with its own hash")
    if freeze_hash != recomputed:
        raise _refuse("the freeze hash given does not match the freeze record")
    try:
        plan_now, code_now = plan_sha256(plan_path), code_identity(root)
    except OSError:
        raise _refuse("the plan or the code files cannot be read to verify the record") from None
    if record["plan_sha256"] != plan_now:
        raise _refuse("the plan has changed since the freeze (its SHA-256 differs from the record)")
    if record["code_identity"] != code_now:
        raise _refuse(
            "the code has changed since the freeze (its identity differs from the record)"
        )
    return FreezeRecord(
        record["plan_sha256"], record["code_identity"], parameters, tuple(flags), recomputed
    )
