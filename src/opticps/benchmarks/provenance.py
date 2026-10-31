"""Provenance schema for the published-experiment benchmark (Stage 3A, gate E0).

Every parameter of an external source carries the way it became known. A value without a
provenance is refused, an unknown value stays `None` with provenance UNKNOWN, a simulated
value can never fill a field that stands for a measurement, and an MD5 that was only copied
from a record is "supplied", never "verified". Nothing here touches the network; the only file
access is `verify_local_asset`, which streams one local file the caller names.

Validation lives in the constructors, so a record built in code is held to the same rules as a
record loaded from YAML: known values are typed per field (finite, positive where physical,
enumerated units), text is non-blank, identifiers use character allow-lists, and collections
are copied into immutable containers.

This module describes sources. It does not read any external capture format; that needs a
verified format and belongs to a later gate.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import datetime
import hashlib
import math
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, overload

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


class ReadHow(StrEnum):
    """How we read a fact (vocabulary of docs/engineering_log/VERIFICATION.md)."""

    VERIFIED = "verified"  # raw text of the primary record read by us (JSON or XML, not a summary)
    SUMMARY = "summary"  # read through a fetch tool that returns a model-written summary
    USER_SUPPLIED = "user-supplied"
    UNCONFIRMED = "unconfirmed"


class LicenseStatus(StrEnum):
    """What was read about a licence. Neither value below means a lawyer's clearance."""

    # The licence identifier or wording was read in the raw metadata or full text of the source's
    # own record. No separate licence file or per-file terms were inspected.
    RECORD_LEVEL = "RECORD_LEVEL"
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


_GRANTING = (Permission.ALLOWED, Permission.ALLOWED_WITH_CONDITIONS)


class Md5State(StrEnum):
    ABSENT = "absent"  # no MD5 recorded
    SUPPLIED = "supplied"  # copied from a record, not checked against local bytes
    VERIFIED = "verified"  # recomputed by `verify_local_asset` and equal to the supplied value
    MISMATCH = "mismatch"  # recomputed and different


class Split(StrEnum):
    CHARACTERISATION = "CHARACTERISATION"
    VALIDATION = "VALIDATION"
    LOCKED_TEST = "LOCKED_TEST"
    RESERVED = "RESERVED"  # declared out of the current fit and holdout
    UNASSIGNED = "UNASSIGNED"


# Fields that stand for a physical setting, a measurement or a published constant of the
# experiment. A SIMULATED value is refused in them.
MEASURED_FIELDS = frozenset(
    {
        "sample_rate_hz",
        "baud_bd",
        "modulation_order",
        "wavelength_nm",
        "wavelength_band",
        "fibre_type",
        "fibre_length_km",
        "transmitter_type",
        "detector",
        "dispersion_ps_per_nm_km",
        "fec_threshold",
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

# Typed rules per known field. Numeric fields are stored in the unit named by the field.
_NUMERIC_FIELDS: dict[str, tuple[str, str]] = {
    "sample_rate_hz": ("Hz", "positive"),
    "baud_bd": ("Bd", "positive"),
    "wavelength_nm": ("nm", "positive"),
    "fibre_length_km": ("km", "non-negative"),
    "dispersion_ps_per_nm_km": ("ps/(nm km)", "finite"),
}
MODULATION_ORDERS = frozenset({2, 4, 8, 16})
_TEXT_FIELDS = frozenset(
    {
        "fibre_type",
        "transmitter_type",
        "detector",
        "reference_sequence",
        "raw_format",
        "calibration",
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
)
# A known value that is really the word for "no value" is refused (e.g. the string "null").
# Compared after case folding and removal of all white space ("N / A" is "n/a").
_PLACEHOLDERS = frozenset(
    {"null", "none", "nan", "unknown", "n/a", "na", "~", "-", "tbd", "tba", "todo", "unspecified"}
)
# A numeric field also has a declared plausibility range: a value outside it is refused as a
# probable unit or typing error, not as a physical impossibility. Ranges are for optical-link
# captures and sources (an oscilloscope sampling at 256 Hz, or a rate of 10**400, is a mistake).
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "sample_rate_hz": (1e6, 1e13),
    "baud_bd": (1e6, 1e12),
    "wavelength_nm": (200.0, 20000.0),
    "fibre_length_km": (0.0, 1e5),
}

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,254}")
_DOI = re.compile(r"10\.[0-9]{4,9}/[!-~]+")
_URL = re.compile(r"https?://[!-~]+")


@overload
def check_text(value: object, where: str) -> str: ...


@overload
def check_text(value: object, where: str, *, nullable: bool) -> str | None: ...


def check_text(value: object, where: str, *, nullable: bool = False) -> str | None:
    """A non-blank string without control characters (NUL included), or None when allowed."""
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{where}: must be a non-empty string, got {value!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise BenchmarkError(f"{where}: contains a control character")
    return value


def _match(pattern: re.Pattern[str], value: object, where: str) -> str:
    text = check_text(value, where)
    if pattern.fullmatch(text) is None or ".." in text:
        raise BenchmarkError(f"{where}: {text!r} contains characters that are not allowed")
    return text


def _group(value: object, where: str) -> str:
    text = check_text(value, where)
    parts = text.split("/")
    if not all(_ID.fullmatch(part) and ".." not in part for part in parts):
        raise BenchmarkError(f"{where}: {text!r} is not a '/'-separated list of safe names")
    return text


def _hex(value: object, length: int, where: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != length
        or not all(c in "0123456789abcdef" for c in value)
    ):
        raise BenchmarkError(f"{where}: is not a {length}-digit lowercase hexadecimal string")
    return value


def is_placeholder(text: str) -> bool:
    """True for the words and marks that stand for "no value" (TBD, N / A, ?, ---, ...)."""
    squeezed = "".join(text.split()).casefold()
    return squeezed in _PLACEHOLDERS or (bool(squeezed) and set(squeezed) <= set("?-~.!"))


def _enum_member(kind: type[StrEnum], value: object, where: str) -> None:
    if not isinstance(value, kind):
        raise BenchmarkError(f"{where}: must be a {kind.__name__}, got {value!r}")


def group_key(group: str) -> str:
    """Normalised acquisition group used for leakage comparison."""
    return group.casefold()


@dataclass(frozen=True)
class ParameterValue:
    """One parameter: value (None = not known), provenance, unit, wording and where it was read.

    `as_stated` keeps the source's own wording when it differs from the value stored (for
    example a sample rate printed with a baud unit). `read_how` follows `ReadHow`.
    A known value is a finite number or a non-blank string; never a bool, list or mapping.
    """

    value: Any
    provenance: Provenance
    unit: str | None = None
    as_stated: str | None = None
    source_ref: str | None = None
    read_how: str | None = None

    def __post_init__(self) -> None:
        _enum_member(Provenance, self.provenance, "a value needs a provenance")
        if self.value is None and self.provenance is not Provenance.UNKNOWN:
            raise BenchmarkError(f"a missing value must carry UNKNOWN, not {self.provenance.value}")
        if self.value is not None and self.provenance is Provenance.UNKNOWN:
            raise BenchmarkError("a value cannot carry UNKNOWN provenance; give its source")
        for name in ("unit", "as_stated", "source_ref"):
            check_text(getattr(self, name), f"parameter.{name}", nullable=True)
        if self.read_how is not None and self.read_how not in {m.value for m in ReadHow}:
            raise BenchmarkError(f"parameter.read_how: {self.read_how!r} is not a ReadHow value")
        if self.value is None:
            return
        if not self.source_ref:
            raise BenchmarkError("a known value needs a source_ref saying where it was read")
        value = self.value
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise BenchmarkError(
                f"a value must be a number, a string or null, got {type(value).__name__}"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise BenchmarkError(f"a known value must be finite, got {value!r}")
        if isinstance(value, str):
            check_text(value, "parameter.value")
            if is_placeholder(value):
                raise BenchmarkError(f"the string {value!r} is not a known value; write null")

    @property
    def known(self) -> bool:
        return self.value is not None

    @classmethod
    def unknown(cls, note: str | None = None) -> ParameterValue:
        return cls(None, Provenance.UNKNOWN, as_stated=note)


def _check_field(name: str, parameter: ParameterValue, where: str) -> None:
    """Typed rule of one known field: kind, range, unit."""
    if not parameter.known:
        return
    value = parameter.value
    if name in _NUMERIC_FIELDS:
        unit, rule = _NUMERIC_FIELDS[name]
        if isinstance(value, str):
            raise BenchmarkError(f"{where}: {name} must be a number, got {value!r}")
        if rule == "positive" and not value > 0:
            raise BenchmarkError(f"{where}: {name} must be positive, got {value!r}")
        if rule == "non-negative" and value < 0:
            raise BenchmarkError(f"{where}: {name} must not be negative, got {value!r}")
        if parameter.unit != unit:
            raise BenchmarkError(
                f"{where}: {name} is stored in {unit}; unit {parameter.unit!r} is inconsistent"
                " (convert the value, keep the source wording in as_stated)"
            )
        if name in PLAUSIBLE_RANGES:
            low, high = PLAUSIBLE_RANGES[name]
            if not low <= value <= high:
                raise BenchmarkError(
                    f"{where}: {name} {value!r} is outside the plausible range [{low:g},"
                    f" {high:g}] {unit}: a unit or typing error is more likely than a value"
                )
    elif name == "modulation_order":
        if isinstance(value, (str, float)) or value not in MODULATION_ORDERS:
            raise BenchmarkError(
                f"{where}: modulation_order must be an integer in {sorted(MODULATION_ORDERS)},"
                f" got {value!r}"
            )
        if parameter.unit is not None:
            raise BenchmarkError(f"{where}: modulation_order has no unit")
    elif name in _TEXT_FIELDS:
        if not isinstance(value, str):
            raise BenchmarkError(f"{where}: {name} must be text, got {value!r}")
        if parameter.unit is not None:
            raise BenchmarkError(f"{where}: {name} has no unit")


def _check_parameters(
    parameters: Mapping[str, ParameterValue], allowed: Iterable[str], where: str
) -> Mapping[str, ParameterValue]:
    if not isinstance(parameters, Mapping):
        raise BenchmarkError(f"{where}: parameters must be a mapping")
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
        _check_field(name, parameter, where)
    return MappingProxyType(dict(parameters))


@dataclass(frozen=True)
class LicenseRecord:
    """Rights of one thing (the article, or the attached data), stated separately.

    `derivatives` is the right to publish adapted material (re-plotted figures, digitised
    points, translated or modified data). `commercial_use` is the right to use the material
    commercially, which a public MIT repository grants onward to every user.
    """

    scope: str  # "article" | "data"
    status: LicenseStatus
    license_id: str | None
    private_research_use: Permission
    public_redistribution: Permission
    derivatives: Permission
    commercial_use: Permission
    note: str = ""
    read_how: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in ("article", "data"):
            raise BenchmarkError(f"licence scope must be 'article' or 'data', got {self.scope!r}")
        _enum_member(LicenseStatus, self.status, "licence status")
        permissions = {
            "private_research_use": self.private_research_use,
            "public_redistribution": self.public_redistribution,
            "derivatives": self.derivatives,
            "commercial_use": self.commercial_use,
        }
        for name, permission in permissions.items():
            _enum_member(Permission, permission, f"licence {name}")
        check_text(self.license_id, "licence id", nullable=True)
        if not isinstance(self.note, str):
            raise BenchmarkError("licence note must be a string")
        if self.read_how is not None and self.read_how not in {m.value for m in ReadHow}:
            raise BenchmarkError(f"licence read_how {self.read_how!r} is not a ReadHow value")
        if self.status is LicenseStatus.RECORD_LEVEL and not self.license_id:
            raise BenchmarkError("a RECORD_LEVEL licence needs its identifier")
        if self.license_id:
            self._check_identifier_terms()
        if self.status is LicenseStatus.UNVERIFIED and any(
            p in _GRANTING for p in permissions.values()
        ):
            raise BenchmarkError("unverified terms cannot grant any permission")
        if self.status is LicenseStatus.RESTRICTED and (
            self.private_research_use is Permission.ALLOWED
            or any(
                p in _GRANTING
                for p in (self.public_redistribution, self.derivatives, self.commercial_use)
            )
        ):
            raise BenchmarkError("a RESTRICTED licence cannot grant redistribution or reuse")

    def _check_identifier_terms(self) -> None:
        """A licence identifier carrying NC or ND cannot be typed as granting what it excludes.

        The tokens of the identifier (split at every non-alphanumeric character, so "CC BY-NC-ND
        4.0" and the SPDX id "CC-BY-NC-ND-4.0" read alike) are checked: NC excludes commercial
        use, ND excludes adapted material. This does not interpret a licence; it only refuses a
        record that contradicts its own identifier.
        """
        tokens = {t for t in re.split(r"[^A-Za-z0-9]+", str(self.license_id).upper()) if t}
        if "NC" in tokens and self.commercial_use in _GRANTING:
            raise BenchmarkError(
                f"licence {self.license_id}: a NonCommercial licence cannot grant commercial use"
            )
        if "ND" in tokens and self.derivatives in _GRANTING:
            raise BenchmarkError(
                f"licence {self.license_id}: a NoDerivatives licence cannot grant adapted material"
            )


@dataclass(frozen=True, slots=True)
class Checksum:
    """MD5 as supplied by the record, plus the hashes of local bytes.

    The local MD5 and SHA-256 cannot be passed to the constructor: they are not `__init__`
    fields. Only `verify_local_asset`, which hashes the bytes of a real file, sets them, so the
    state `Md5State.VERIFIED` cannot be typed in. The state is derived: an MD5 never checked
    against local bytes is `supplied`.

    Two further local facts, `size_local` and `mtime_ns_local`, are those of the file at the time
    it was hashed. A `VERIFIED` state describes those bytes only: if the file changes afterwards
    the state is stale, which `still_current` detects by size and modification time. Any code
    that decodes the file after hashing it (E1) calls `still_current` first, or hashes again.

    Limits: `__slots__` and `__reduce__` close `__dict__` writes and unpickling (a pickle could
    otherwise carry a VERIFIED state that never saw any bytes). `object.__setattr__` in the same
    process cannot be prevented in Python; that is a deliberate act, not a typing mistake.
    """

    md5_supplied: str | None = None
    md5_local: str | None = field(default=None, init=False)
    sha256_local: str | None = field(default=None, init=False)
    size_local: int | None = field(default=None, init=False)
    mtime_ns_local: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        _hex(self.md5_supplied, 32, "md5_supplied")

    def __reduce__(self) -> NoReturn:
        raise TypeError("a Checksum is not pickled or copied: rebuild it with verify_local_asset")

    @property
    def md5_state(self) -> Md5State:
        if self.md5_supplied is None:
            return Md5State.ABSENT
        if self.md5_local is None:
            return Md5State.SUPPLIED
        return Md5State.VERIFIED if self.md5_local == self.md5_supplied else Md5State.MISMATCH

    def still_current(self, path: Path) -> bool:
        """True when `path` still has the size and modification time seen when it was hashed.

        False for a checksum that was never computed locally or a file that cannot be examined.
        It is a cheap staleness test, not a proof: only hashing again proves the bytes.
        """
        if self.size_local is None or self.mtime_ns_local is None:
            return False
        try:
            status = path.stat()
        except OSError:
            return False
        return status.st_size == self.size_local and status.st_mtime_ns == self.mtime_ns_local


def verify_local_asset(path: Path, md5_supplied: str | None = None) -> Checksum:
    """Stream one local file through MD5 and SHA-256 and return the resulting checksum.

    The only producer of local hashes, hence of `Md5State.VERIFIED`: the state is reached only
    when the digest of the bytes read here equals `md5_supplied`. A missing file is
    SOURCE_MISSING; any other failure to read it is a `BenchmarkError`. The file is opened
    read-only and read in chunks; it is never created, moved or modified. The result carries the
    size and modification time seen after reading, so a later change is detectable
    (`Checksum.still_current`). Nothing in E0 calls this on a capture: E1 runs it on the three
    downloaded TERIPHIC files.
    """
    if not path.is_file():
        raise BenchmarkError(f"{path.name} is not present locally", ErrorCode.SOURCE_MISSING)
    checksum = Checksum(md5_supplied=md5_supplied)
    md5, sha = hashlib.md5(), hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                md5.update(chunk)
                sha.update(chunk)
            status = os.fstat(handle.fileno())
    except OSError as error:
        raise BenchmarkError(f"{path.name} cannot be read: {error}") from error
    object.__setattr__(checksum, "md5_local", md5.hexdigest())
    object.__setattr__(checksum, "sha256_local", sha.hexdigest())
    object.__setattr__(checksum, "size_local", status.st_size)
    object.__setattr__(checksum, "mtime_ns_local", status.st_mtime_ns)
    return checksum


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
        _match(_ID, self.source_id, "asset.source_id")
        _match(_DOI, self.doi, "asset.doi")
        _match(_URL, self.url, "asset.url")
        check_text(self.asset_version, "asset.asset_version")
        _match(_FILENAME, self.filename, "asset.filename")
        _group(self.group, f"{self.filename}.group")
        check_text(self.sample_rate_wording, "asset.sample_rate_wording", nullable=True)
        if not isinstance(self.checksum, Checksum):
            raise BenchmarkError(f"{self.filename}: checksum must be a Checksum")
        _enum_member(Split, self.split, f"{self.filename}.split")
        if self.size_bytes is not None and (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes <= 0
        ):
            raise BenchmarkError(
                f"{self.filename}: size_bytes must be a positive integer or null,"
                f" got {self.size_bytes!r}"
            )
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
        _match(_ID, self.source_id, "source.source_id")
        if self.kind not in ("dataset", "publication"):
            raise BenchmarkError(f"{self.source_id}: kind must be dataset or publication")
        check_text(self.title, "source.title")
        _match(_DOI, self.doi, "source.doi")
        _match(_URL, self.url, "source.url")
        check_text(self.version, "source.version", nullable=True)
        retrieved = check_text(self.retrieved, "source.retrieved")
        try:
            datetime.date.fromisoformat(retrieved)
        except ValueError:
            raise BenchmarkError(f"source.retrieved: {retrieved!r} is not an ISO date") from None
        licenses = tuple(self.licenses)
        if not licenses:
            raise BenchmarkError(
                f"{self.source_id}: licence state is required", ErrorCode.LICENSE_UNVERIFIED
            )
        if not all(isinstance(lic, LicenseRecord) for lic in licenses):
            raise BenchmarkError(f"{self.source_id}: licences must be LicenseRecord objects")
        scopes = [lic.scope for lic in licenses]
        if len(scopes) != len(set(scopes)):
            raise BenchmarkError(f"{self.source_id}: a licence scope is listed twice")
        assets = tuple(self.assets)
        if not all(isinstance(asset, AssetRecord) for asset in assets):
            raise BenchmarkError(f"{self.source_id}: assets must be AssetRecord objects")
        for asset in assets:
            if asset.source_id != self.source_id:
                raise BenchmarkError(f"{asset.filename}: source_id differs from {self.source_id}")
        names = [asset.filename.casefold() for asset in assets]
        if len(names) != len(set(names)):
            raise BenchmarkError(f"{self.source_id}: a filename is listed twice")
        assert_no_split_overlap(assets)
        object.__setattr__(self, "licenses", licenses)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(
            self,
            "parameters",
            _check_parameters(self.parameters, SOURCE_FIELDS, self.source_id),
        )
        _hex(self.plan_sha256, 64, "plan_sha256")

    def license_for(self, scope: str) -> LicenseRecord:
        for lic in self.licenses:
            if lic.scope == scope:
                return lic
        raise BenchmarkError(
            f"{self.source_id}: no {scope} licence recorded", ErrorCode.LICENSE_UNVERIFIED
        )

    def require_public_redistribution(self, scope: str) -> None:
        """Raise LICENSE_UNVERIFIED unless `scope` may be published in this MIT repository.

        Publishing in an MIT repository passes the material to every user for any use, so the
        licence must grant public redistribution *and* commercial use. A non-commercial licence
        (CC BY-NC-ND) fails even though it permits sharing the article verbatim.
        """
        lic = self.license_for(scope)
        if lic.status is not LicenseStatus.RECORD_LEVEL:
            raise BenchmarkError(
                f"{self.source_id}: licence of the {scope} is {lic.status.label}",
                ErrorCode.LICENSE_UNVERIFIED,
            )
        if lic.public_redistribution not in _GRANTING:
            raise BenchmarkError(
                f"{self.source_id}: public redistribution of the {scope} is not granted",
                ErrorCode.LICENSE_UNVERIFIED,
            )
        if lic.commercial_use not in _GRANTING:
            raise BenchmarkError(
                f"{self.source_id}: the {scope} licence ({lic.license_id}) does not grant"
                " commercial use, which an MIT repository grants to everyone",
                ErrorCode.LICENSE_UNVERIFIED,
            )

    def require_derivatives(self, scope: str) -> None:
        """Raise LICENSE_UNVERIFIED unless adapted material of `scope` may be published."""
        self.require_public_redistribution(scope)
        lic = self.license_for(scope)
        if lic.derivatives not in _GRANTING:
            raise BenchmarkError(
                f"{self.source_id}: the {scope} licence ({lic.license_id}) does not grant"
                " adapted material (re-plotted figures, digitised points, modified data)",
                ErrorCode.LICENSE_UNVERIFIED,
            )


def assert_no_split_overlap(assets: Iterable[AssetRecord]) -> None:
    """LEAKAGE_DETECTED if one file identity sits in two roles or two acquisition groups.

    The identities compared, each after case normalisation: acquisition group (one group, one
    role), file name, MD5 supplied by the record, locally computed MD5 and locally computed
    SHA-256. Two files that share a name or a hash are one acquisition and must share the group
    and the role.
    """
    seen: dict[tuple[str, str], tuple[str, Split]] = {}
    group_role: dict[str, Split] = {}
    for asset in assets:
        group = group_key(asset.group)
        role = group_role.setdefault(group, asset.split)
        if role is not asset.split:
            raise BenchmarkError(
                f"group {asset.group} is in both {role.value} and {asset.split.value}",
                ErrorCode.LEAKAGE_DETECTED,
            )
        identities = {
            "file name": asset.filename.casefold(),
            "supplied MD5": asset.checksum.md5_supplied,
            "local MD5": asset.checksum.md5_local,
            "local SHA-256": asset.checksum.sha256_local,
        }
        for kind, value in identities.items():
            if value is None:
                continue
            # A supplied and a locally computed MD5 are the same kind of identity: one asset's
            # supplied value equals another's local value when they are the same file.
            family = "MD5" if kind.endswith("MD5") else kind
            other = seen.setdefault((family, value), (group, asset.split))
            if other[0] != group:  # the same group always has the same role (checked above)
                raise BenchmarkError(
                    f"{asset.group} and {other[0]} share the {kind} {value[:12]} but sit in"
                    f" {asset.split.value} and {other[1].value}",
                    ErrorCode.LEAKAGE_DETECTED,
                )
