"""The declared 2 km calibration route of the E2c power study (design D15 a, D16).

After R13 scored the 2 km TERIPHIC capture once and recorded FAIL, the 2 km file is calibration
data: it is read in full by the E2c study and is never again a holdout. This module is the only E2c
code that opens it, and it opens nothing else under `data/external` (the B2B file goes through
`teriphic.open_b2b`).

`open_two_km` refuses, in this order, before any file is opened, hashed or a process is started:

1. a path whose given name or resolved name is the registered 10 km name (`TEN_KM_NAME`);
2. any other name: only the registered 2 km name is accepted, wherever it lies.

Then it requires the committed R13 2 km record (`two_km_result.json`) to be the pinned bytes and to
say FAIL (verdict FAILED) for the 2 km file at the R13 freeze: the 2 km file becomes calibration
data only because its pre-registered test is over. Then it hashes the 2 km file (MD5 against the
register, SHA-256 against `teriphic.HOLDOUT_SHA256`) and only then opens it read-only. No other file
is hashed.

Nothing here reads, hashes, opens or stats the 10 km file. The `ROLE_BY_NAME` binding of `e2_score`
(2 km = VALIDATION) is unchanged; R14 rebinds it if it ever does.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opticps.benchmarks import holdout, teriphic
from opticps.benchmarks.external_capture import ExternalCapture
from opticps.benchmarks.provenance import (
    BenchmarkError,
    ErrorCode,
    Md5State,
    SourceRecord,
    Split,
    verify_local_asset,
)

TWO_KM_NAME = "50G_PAM4_PD1_2km_Subassembly1.bin"
TEN_KM_NAME = "50G_PAM4_PD1_10km_Subassembly1.bin"
TWO_KM_RECORD_PATH = Path("docs/benchmarks/teriphic_e2/two_km_result.json")
# The committed R13 record (E2b, commit 8775540) and the R13 freeze it was scored at.
TWO_KM_RECORD_SHA256 = "476642bc79cbc5b8634499fb8361bef0bf28d6e546a146d46232124cd765d9c5"
R13_FREEZE_COMMIT = "ce0ee732af1111c67d94943ad985469dea8c8389"
SOURCE_AMPLITUDE_2KM = 0.832  # D1, D9: the received amplitude at 2 km, as the design states


def refuse_unless_two_km_name(path: Path) -> Path:
    """The resolved path when both its given and resolved names are the registered 2 km name.

    Refuses the 10 km name first, then every other name. Opens and hashes nothing; resolving a path
    reads directory entries and link targets only.
    """
    given = teriphic.fold_name(Path(path).name)
    if given == teriphic.fold_name(TEN_KM_NAME):
        raise BenchmarkError(
            f"{Path(path).name}: the 10 km file is not calibration data; refused before any open",
            ErrorCode.LEAKAGE_DETECTED,
        )
    resolved = Path(path).resolve()
    target = teriphic.fold_name(resolved.name)
    if target == teriphic.fold_name(TEN_KM_NAME):
        raise BenchmarkError(
            f"{Path(path).name} resolves to the 10 km file; refused before any open",
            ErrorCode.LEAKAGE_DETECTED,
        )
    two_km = teriphic.fold_name(TWO_KM_NAME)
    if given != two_km or target != two_km:
        raise BenchmarkError(
            f"{Path(path).name}: the E2c calibration route opens only {TWO_KM_NAME}; refused",
            ErrorCode.LEAKAGE_DETECTED,
        )
    return resolved


def require_two_km_fail_record(
    root: Path, *, record_sha256: str = TWO_KM_RECORD_SHA256, freeze_commit: str = R13_FREEZE_COMMIT
) -> dict[str, Any]:
    """The committed R13 2 km record: the pinned bytes, saying FAIL. Refuses otherwise."""
    data, _ = holdout._committed_bytes(root, root / TWO_KM_RECORD_PATH, "2 km record")
    digest = hashlib.sha256(data).hexdigest()
    if digest != record_sha256:
        raise BenchmarkError(
            f"2 km record: SHA-256 {digest[:12]} is not the pinned {record_sha256[:12]}; refused"
        )
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BenchmarkError(f"2 km record: not JSON ({error})") from error
    if not isinstance(record, dict):
        raise BenchmarkError("2 km record: not a JSON object")
    checks = {
        "outcome": "FAIL",
        "verdict": "FAILED",
        "filename": TWO_KM_NAME,
        "split": Split.VALIDATION.value,
        "criterion_commit": freeze_commit,
    }
    for key, wanted in checks.items():
        if record.get(key) != wanted:
            raise BenchmarkError(
                f"2 km record: {key} is {record.get(key)!r}, not {wanted!r}; the 2 km file is"
                " calibration data only after its R13 test recorded FAIL"
            )
    if record.get("hashes_verified") is not True:
        raise BenchmarkError("2 km record: the 2 km file's hashes were not verified at R13")
    return record


def open_two_km(
    path: Path,
    *,
    root: Path = Path("."),
    source: SourceRecord | None = None,
    holdout_sha256: Mapping[str, str] | None = None,
    record_sha256: str = TWO_KM_RECORD_SHA256,
) -> ExternalCapture:
    """Open the 2 km capture read-only through the declared calibration route (see the module text).

    `source` and `holdout_sha256` default to the register and `teriphic.HOLDOUT_SHA256`; they are
    injectable so tests use fixtures and never a real capture.
    """
    resolved = refuse_unless_two_km_name(Path(path))
    root = Path(root)
    require_two_km_fail_record(root, record_sha256=record_sha256)
    source = source or teriphic.load_config(root / teriphic.CONFIG_PATH)
    asset = next(
        (
            a
            for a in source.assets
            if teriphic.fold_name(a.filename) == teriphic.fold_name(TWO_KM_NAME)
        ),
        None,
    )
    if asset is None or asset.split is not Split.VALIDATION:
        raise BenchmarkError(f"{TWO_KM_NAME}: not registered as the 2 km file; refused")
    table = teriphic.HOLDOUT_SHA256 if holdout_sha256 is None else holdout_sha256
    expected = table.get(TWO_KM_NAME)
    if expected is None:
        raise BenchmarkError(f"{TWO_KM_NAME}: no recorded SHA-256; refused")
    checksum = verify_local_asset(resolved, asset.checksum.md5_supplied)
    if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected:
        raise BenchmarkError(
            f"{TWO_KM_NAME}: MD5 or SHA-256 differs from the recorded values; not opened",
            ErrorCode.LEAKAGE_DETECTED,
        )
    return ExternalCapture.open_keysight_bin(resolved, checksum=checksum)
