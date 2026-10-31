"""Provenance schema for the published-experiment benchmark (Stage 3A, gate E0).

Every parameter of an external source carries the way it became known. A value without a
provenance is refused, an unknown value stays `None` with provenance UNKNOWN, a simulated
value can never fill a field that stands for a measurement, and an MD5 that was only copied
from a record is "supplied", never "verified". Nothing here touches the network; the only file
access is `verify_md5`, which reads one local file the caller names.

This module describes sources. It does not read any external capture format; that needs a
verified format and belongs to a later gate.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

_CHUNK = 1 << 20


class ErrorCode(StrEnum):
    """Standard outcome codes (roadmap v2.1 L3)."""

    SOURCE_MISSING = "SOURCE_MISSING"
    LICENSE_UNVERIFIED = "LICENSE_UNVERIFIED"
    FORMAT_UNKNOWN = "FORMAT_UNKNOWN"
    REFERENCE_SEQUENCE_MISSING = "REFERENCE_SEQUENCE_MISSING"
    MODEL_GAP = "MODEL_GAP"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    LEAKAGE_DETECTED = "LEAKAGE_DETECTED"
    UNIDENTIFIABLE_PARAMETER = "UNIDENTIFIABLE_PARAMETER"


class BenchmarkError(ValueError):
    """A benchmark record or configuration is refused. `code` is the standard outcome, if any."""

    def __init__(self, message: str, code: ErrorCode | None = None) -> None:
        super().__init__(f"{code.value}: {message}" if code else message)
        self.code = code


class Provenance(StrEnum):
    """How an individual parameter or data point became known."""

    PUBLISHED_MEASUREMENT = "PUBLISHED_MEASUREMENT"  # value a source reports as set or measured
    PUBLISHED_MODEL_ASSUMPTION = "PUBLISHED_MODEL_ASSUMPTION"
    DIGITIZED_FIGURE = "DIGITIZED_FIGURE"
    RAW_CAPTURE = "RAW_CAPTURE"
    SIMULATED = "SIMULATED"
    INFERRED = "INFERRED"  # derived by us from other facts; not stated by the source
    UNKNOWN = "UNKNOWN"


class LicenseStatus(StrEnum):
    VERIFIED = "VERIFIED"  # the licence identifier was read from the source's own record
    UNVERIFIED = "UNVERIFIED"
    RESTRICTED = "RESTRICTED"  # no reuse right granted beyond reading

    @property
    def label(self) -> str:
        """Wording used in reports; unclear terms are never rounded up to a permission."""
        return "LICENSE/REUSE TERMS UNVERIFIED" if self is LicenseStatus.UNVERIFIED else self.value


class Permission(StrEnum):
    ALLOWED = "ALLOWED"
    ALLOWED_WITH_CONDITIONS = "ALLOWED_WITH_CONDITIONS"
    NOT_ALLOWED = "NOT_ALLOWED"
    UNVERIFIED = "UNVERIFIED"


class Md5State(StrEnum):
    ABSENT = "absent"  # no MD5 recorded
    SUPPLIED = "supplied"  # copied from a record, not checked against local bytes
    VERIFIED = "verified"  # recomputed from local bytes and equal to the supplied value
    MISMATCH = "mismatch"  # recomputed and different


class Split(StrEnum):
    CHARACTERISATION = "CHARACTERISATION"
    VALIDATION = "VALIDATION"
    LOCKED_TEST = "LOCKED_TEST"
    RESERVED = "RESERVED"  # declared out of the current fit and holdout
    UNASSIGNED = "UNASSIGNED"


# Fields that stand for a physical setting or measurement of the experiment. A SIMULATED value
# is refused in them.
MEASURED_FIELDS = frozenset(
    {
        "sample_rate_hz",
        "baud_bd",
        "modulation_order",
        "wavelength_nm",
        "fibre_type",
        "fibre_length_km",
        "transmitter_type",
        "detector",
        "dispersion_ps_per_nm_km",
        "reference_sequence",
        "raw_format",
        "calibration",
    }
)
# Fields every asset record must state explicitly (null with UNKNOWN when not known).
ASSET_FIELDS = (
    "sample_rate_hz",
    "baud_bd",
    "modulation_order",
    "wavelength_nm",
    "fibre_type",
    "fibre_length_km",
    "transmitter_type",
    "detector",
    "reference_sequence",
    "raw_format",
    "calibration",
)
# Names a source-level parameter block may use (publications and shared facts).
SOURCE_FIELDS = frozenset(ASSET_FIELDS) | {
    "dispersion_ps_per_nm_km",
    "fec_threshold",
    "equalizer",
    "rate_definition",
    "ber_definition",
    "chirp_model_status",
    "constraint",
    "distribution_family",
    "noise_definition",
    "wavelength_band",
}


@dataclass(frozen=True)
class ParameterValue:
    """One parameter: value (None = not known), provenance, unit, wording and where it was read.

    `as_stated` keeps the source's own wording when it differs from the value stored (for
    example a sample rate printed with a baud unit). `read_how` follows the vocabulary of
    docs/engineering_log/VERIFICATION.md (verified, summary, user-supplied, unconfirmed).
    """

    value: Any
    provenance: Provenance
    unit: str | None = None
    as_stated: str | None = None
    source_ref: str | None = None
    read_how: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            raise BenchmarkError(f"a value needs a provenance, got {self.provenance!r}")
        if self.value is None and self.provenance is not Provenance.UNKNOWN:
            raise BenchmarkError(f"a missing value must carry UNKNOWN, not {self.provenance.value}")
        if self.value is not None and self.provenance is Provenance.UNKNOWN:
            raise BenchmarkError("a value cannot carry UNKNOWN provenance; give its source")
        if self.value is not None and not self.source_ref:
            raise BenchmarkError("a known value needs a source_ref saying where it was read")

    @property
    def known(self) -> bool:
        return self.value is not None

    @classmethod
    def unknown(cls, note: str | None = None) -> ParameterValue:
        return cls(None, Provenance.UNKNOWN, as_stated=note)


def _check_parameters(
    parameters: Mapping[str, ParameterValue], allowed: Iterable[str], where: str
) -> Mapping[str, ParameterValue]:
    allowed_set = set(allowed)
    for name, parameter in parameters.items():
        if name not in allowed_set:
            raise BenchmarkError(f"{where}: unknown parameter {name!r}")
        if not isinstance(parameter, ParameterValue):
            raise BenchmarkError(f"{where}: parameter {name!r} has no provenance record")
        if parameter.provenance is Provenance.SIMULATED and name in MEASURED_FIELDS:
            raise BenchmarkError(
                f"{where}: a SIMULATED value cannot occupy the measured field {name!r}",
                ErrorCode.NOT_COMPARABLE,
            )
    return MappingProxyType(dict(parameters))


@dataclass(frozen=True)
class LicenseRecord:
    """Rights of one thing (the article, or the attached data), stated separately."""

    scope: str  # "article" | "data"
    status: LicenseStatus
    license_id: str | None
    private_research_use: Permission
    public_redistribution: Permission
    note: str = ""
    read_how: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in ("article", "data"):
            raise BenchmarkError(f"licence scope must be 'article' or 'data', got {self.scope!r}")
        if self.status is LicenseStatus.VERIFIED and not self.license_id:
            raise BenchmarkError("a VERIFIED licence needs its identifier")
        if self.status is LicenseStatus.UNVERIFIED and (
            self.public_redistribution is not Permission.UNVERIFIED
        ):
            raise BenchmarkError("unverified terms cannot grant public redistribution")


@dataclass(frozen=True)
class Checksum:
    """MD5 as supplied by the record and as recomputed locally, plus a local SHA-256.

    The state is derived: an MD5 never checked against local bytes is `supplied`.
    """

    md5_supplied: str | None = None
    md5_local: str | None = None
    sha256_local: str | None = None

    def __post_init__(self) -> None:
        for name in ("md5_supplied", "md5_local"):
            value = getattr(self, name)
            if value is not None and not _is_hex(value, 32):
                raise BenchmarkError(f"{name} is not a 32-digit hexadecimal string")
        if self.sha256_local is not None and not _is_hex(self.sha256_local, 64):
            raise BenchmarkError("sha256_local is not a 64-digit hexadecimal string")
        if self.md5_local is not None and self.sha256_local is None:
            raise BenchmarkError("a locally computed MD5 needs the local SHA-256 of the same bytes")

    @property
    def md5_state(self) -> Md5State:
        if self.md5_supplied is None:
            return Md5State.ABSENT
        if self.md5_local is None:
            return Md5State.SUPPLIED
        return Md5State.VERIFIED if self.md5_local == self.md5_supplied else Md5State.MISMATCH


def _is_hex(text: str, length: int) -> bool:
    return len(text) == length and all(c in "0123456789abcdef" for c in text)


def verify_md5(path: Path, checksum: Checksum) -> Checksum:
    """Hash one local file (MD5 and SHA-256, streamed) and return the updated checksum.

    A missing file is SOURCE_MISSING. Reads only; never creates, moves or modifies the file.
    """
    if not path.is_file():
        raise BenchmarkError(f"{path.name} is not present locally", ErrorCode.SOURCE_MISSING)
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            md5.update(chunk)
            sha.update(chunk)
    return replace(checksum, md5_local=md5.hexdigest(), sha256_local=sha.hexdigest())


@dataclass(frozen=True)
class AssetRecord:
    """One file of a dataset, with per-parameter provenance."""

    source_id: str
    doi: str
    url: str
    asset_version: str
    filename: str
    checksum: Checksum
    size_bytes: int | None
    split: Split
    group: str  # acquisition group used by leakage checks
    parameters: Mapping[str, ParameterValue]
    sample_rate_wording: str | None = None  # unit as the record prints it

    def __post_init__(self) -> None:
        if not (self.source_id and self.doi and self.url and self.filename and self.group):
            raise BenchmarkError("an asset needs source_id, doi, url, filename and group")
        if Path(self.filename).name != self.filename:
            raise BenchmarkError(f"filename {self.filename!r} must be a bare file name")
        if not isinstance(self.split, Split):
            raise BenchmarkError(f"unknown split {self.split!r}")
        if self.size_bytes is not None and self.size_bytes <= 0:
            raise BenchmarkError("size_bytes must be positive")
        checked = _check_parameters(self.parameters, ASSET_FIELDS, self.filename)
        absent = [name for name in ASSET_FIELDS if name not in checked]
        if absent:
            raise BenchmarkError(
                f"{self.filename}: fields {absent} must be stated (null with UNKNOWN if unknown)"
            )
        object.__setattr__(self, "parameters", checked)

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(name for name in ASSET_FIELDS if not self.parameters[name].known)


@dataclass(frozen=True)
class SourceRecord:
    """A dataset record or a publication."""

    source_id: str
    kind: str  # "dataset" | "publication"
    title: str
    doi: str
    url: str
    version: str | None
    retrieved: str  # ISO date of the metadata read
    licenses: tuple[LicenseRecord, ...]
    assets: tuple[AssetRecord, ...] = ()
    parameters: Mapping[str, ParameterValue] = field(default_factory=dict)
    plan_sha256: str | None = None  # pinned hash of the fit/holdout plan, if any

    def __post_init__(self) -> None:
        if self.kind not in ("dataset", "publication"):
            raise BenchmarkError(f"{self.source_id}: kind must be dataset or publication")
        if not (self.source_id and self.title and self.doi and self.url and self.retrieved):
            raise BenchmarkError("a source needs source_id, title, doi, url and retrieved")
        if not self.licenses:
            raise BenchmarkError(
                f"{self.source_id}: licence state is required", ErrorCode.LICENSE_UNVERIFIED
            )
        scopes = [lic.scope for lic in self.licenses]
        if len(scopes) != len(set(scopes)):
            raise BenchmarkError(f"{self.source_id}: a licence scope is listed twice")
        for asset in self.assets:
            if asset.source_id != self.source_id:
                raise BenchmarkError(f"{asset.filename}: source_id differs from {self.source_id}")
        object.__setattr__(
            self,
            "parameters",
            _check_parameters(self.parameters, SOURCE_FIELDS, self.source_id),
        )
        if self.plan_sha256 is not None and not _is_hex(self.plan_sha256, 64):
            raise BenchmarkError("plan_sha256 is not a 64-digit hexadecimal string")

    def license_for(self, scope: str) -> LicenseRecord:
        for lic in self.licenses:
            if lic.scope == scope:
                return lic
        raise BenchmarkError(
            f"{self.source_id}: no {scope} licence recorded", ErrorCode.LICENSE_UNVERIFIED
        )

    def require_public_redistribution(self, scope: str) -> None:
        """Raise LICENSE_UNVERIFIED unless public redistribution of `scope` is allowed."""
        lic = self.license_for(scope)
        if lic.status is not LicenseStatus.VERIFIED or lic.public_redistribution not in (
            Permission.ALLOWED,
            Permission.ALLOWED_WITH_CONDITIONS,
        ):
            raise BenchmarkError(
                f"{self.source_id}: public redistribution of the {scope} is not established",
                ErrorCode.LICENSE_UNVERIFIED,
            )


def assert_no_split_overlap(assets: Iterable[AssetRecord]) -> None:
    """LEAKAGE_DETECTED if one acquisition group or one local hash sits in two roles."""
    by_group: dict[str, Split] = {}
    by_hash: dict[str, tuple[str, Split]] = {}
    for asset in assets:
        seen = by_group.setdefault(asset.group, asset.split)
        if seen is not asset.split:
            raise BenchmarkError(
                f"group {asset.group} is in both {seen.value} and {asset.split.value}",
                ErrorCode.LEAKAGE_DETECTED,
            )
        digest = asset.checksum.sha256_local
        if digest is not None:
            other = by_hash.setdefault(digest, (asset.group, asset.split))
            if other[0] != asset.group:
                raise BenchmarkError(
                    f"{asset.group} and {other[0]} have identical bytes (SHA-256 {digest[:12]})",
                    ErrorCode.LEAKAGE_DETECTED,
                )
