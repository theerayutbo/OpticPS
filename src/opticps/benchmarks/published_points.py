"""Typed records for the numbers a benchmark compares (gate E3).

A `PublishedPoint` is one number a source states in its running text, a table or an equation,
with the conditions under which the source states it. A `ModelPoint` is the number OpticPS
computes, with the conditions of that computation. The two share `Conditions`, so a comparison
can test every condition field by field (see `comparison.compare`).

Two rules are enforced here and not left to the caller:

* a number read from a figure cannot become a `PublishedPoint` (`ReadFrom` has no figure
  member): the reuse terms of the figures are not cleared, and digitising is not done;
* a field the source does not state stays `None`; nothing fills it in.

Authored independently for this repository. It encodes no external software.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from opticps.benchmarks.provenance import BenchmarkError, ErrorCode, check_text


class ConstraintType(StrEnum):
    """Which power constraint the quantity is stated under."""

    PEAK = "peak"
    AVERAGE = "average"


class DriveDomain(StrEnum):
    """Whether the stated drive or SNR refers to the optical or the electrical signal."""

    OPTICAL = "optical"
    ELECTRICAL = "electrical"


class EvidenceLabel(StrEnum):
    """Nature of the evidence behind a number (labels already used in this repository)."""

    SIMULATED = "simulated"
    MOCK = "mock"
    MEASURED = "measured"
    ANALYTICAL = "analytical"


class ReadFrom(StrEnum):
    """Where in the source a published number was read. A figure is deliberately absent."""

    RUNNING_TEXT = "running text"
    TABLE = "table"
    EQUATION = "equation"


# Condition fields that must agree for two numbers to be compared, in report order.
CONDITION_FIELDS = (
    "rate_definition",
    "constraint",
    "wavelength_nm",
    "fibre_length_km",
    "baud_bd",
    "ber_definition",
    "fec_threshold_ber",
    "dsp_stage",
    "drive",
)
NUMERIC_CONDITIONS = frozenset({"wavelength_nm", "fibre_length_km", "baud_bd", "fec_threshold_ber"})


@dataclass(frozen=True, kw_only=True)
class Conditions:
    """Quantity, unit and the conditions that define what the number means.

    `None` means "not stated". `rate_definition` names the rate and decoder metric (for example
    symbol-metric or bit-metric decoding, gross or net); `ber_definition` and `fec_threshold_ber`
    apply to BER-type quantities; `dsp_stage` names the receiver processing the number includes.
    """

    quantity: str
    unit: str
    rate_definition: str | None = None
    constraint: ConstraintType | None = None
    wavelength_nm: float | None = None
    fibre_length_km: float | None = None
    baud_bd: float | None = None
    ber_definition: str | None = None
    fec_threshold_ber: float | None = None
    dsp_stage: str | None = None
    drive: DriveDomain | None = None

    def __post_init__(self) -> None:
        check_text(self.quantity, "quantity")
        check_text(self.unit, "unit")
        for name in ("rate_definition", "ber_definition", "dsp_stage"):
            check_text(getattr(self, name), name, nullable=True)
        if self.constraint is not None and not isinstance(self.constraint, ConstraintType):
            raise BenchmarkError(f"constraint must be a ConstraintType, got {self.constraint!r}")
        if self.drive is not None and not isinstance(self.drive, DriveDomain):
            raise BenchmarkError(f"drive must be a DriveDomain, got {self.drive!r}")
        for name in NUMERIC_CONDITIONS:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BenchmarkError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value) or value < 0:
                raise BenchmarkError(f"{name} must be finite and not negative, got {value!r}")


def _check_value(value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BenchmarkError(f"a point value must be a finite number or None, got {value!r}")


@dataclass(frozen=True, kw_only=True)
class PublishedPoint(Conditions):
    """A number a source states, with its location and the source's own conditions."""

    source_id: str
    location: str
    value: float | None
    evidence: EvidenceLabel
    read_from: ReadFrom
    note: str = ""

    def __post_init__(self) -> None:
        Conditions.__post_init__(self)
        check_text(self.source_id, "source_id")
        check_text(self.location, "location")
        _check_value(self.value)
        if not isinstance(self.evidence, EvidenceLabel):
            raise BenchmarkError(f"evidence must be an EvidenceLabel, got {self.evidence!r}")
        if not isinstance(self.read_from, ReadFrom):
            raise BenchmarkError(
                f"read_from must be a ReadFrom (figure values are not redistributable), "
                f"got {self.read_from!r}",
                ErrorCode.LICENSE_UNVERIFIED,
            )


@dataclass(frozen=True, kw_only=True)
class ModelPoint(Conditions):
    """A number OpticPS computes, with the conditions of the computation."""

    value: float | None
    evidence: EvidenceLabel
    method: str

    def __post_init__(self) -> None:
        Conditions.__post_init__(self)
        _check_value(self.value)
        if not isinstance(self.evidence, EvidenceLabel):
            raise BenchmarkError(f"evidence must be an EvidenceLabel, got {self.evidence!r}")
        check_text(self.method, "method")
