"""Matched comparison of a published number with a computed one (gate E3).

`compare` refuses, with a result that names the reason, whenever the two numbers do not describe
the same thing: another quantity or unit, another rate definition, constraint type, wavelength,
fibre length, baud rate, BER definition, FEC threshold, DSP stage or drive domain, or a condition
that one side leaves null. Nothing is converted: a unit that differs is a refusal even when a
conversion factor exists. A condition that really does not apply (an information-theoretic curve
has no wavelength) must be declared in `not_applicable`, and then both sides must leave it null.

The tolerance and its justification are arguments, so they are written down before the
deviation is looked at; the result records both. A deviation exactly equal to the tolerance
counts as MATCH (the window is closed: |deviation| <= tolerance); the deviation is formed in
floating point, so a caller who needs a decision at the edge must not rely on rounding.

The evidence labels of both points are carried into the result. They are not a condition: a model
may be compared with a measurement. A MATCH then means agreement of the model with that
measurement under the stated conditions, not validation of the model.

Authored independently for this repository. It encodes no external software.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from opticps.benchmarks.provenance import BenchmarkError, ErrorCode, check_text
from opticps.benchmarks.published_points import (
    CONDITION_FIELDS,
    NUMERIC_CONDITIONS,
    EvidenceLabel,
    ModelPoint,
    PublishedPoint,
)

FIGURE_BLOCK = "FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED)"


class ComparisonStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_COMPARABLE = "NOT COMPARABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ComparisonResult:
    """Outcome of one comparison. `deviation` is model minus published, in the common unit."""

    status: ComparisonStatus
    reason: str
    published_value: float | None = None
    model_value: float | None = None
    deviation: float | None = None
    tolerance: float | None = None
    tolerance_justification: str | None = None
    unit: str | None = None
    published_evidence: EvidenceLabel | None = None
    model_evidence: EvidenceLabel | None = None

    @property
    def code(self) -> ErrorCode | None:
        return ErrorCode.NOT_COMPARABLE if self.status is ComparisonStatus.NOT_COMPARABLE else None


def refuse(
    reason: str, status: ComparisonStatus = ComparisonStatus.NOT_COMPARABLE
) -> ComparisonResult:
    """A row that cannot be computed or compared; `reason` must say what is missing."""
    if status not in (ComparisonStatus.NOT_COMPARABLE, ComparisonStatus.BLOCKED):
        raise BenchmarkError("refuse() produces NOT COMPARABLE or BLOCKED only")
    return ComparisonResult(status=status, reason=check_text(reason, "reason"))


@dataclass(frozen=True)
class Row:
    """One row of an E3 table: ids and texts for the report, and the comparison result."""

    row_id: str
    source_location: str
    source_text: str
    our_text: str
    result: ComparisonResult


def _differs(name: str, a: object, b: object) -> bool:
    if name in NUMERIC_CONDITIONS:
        assert isinstance(a, (int, float)) and isinstance(b, (int, float))
        return not math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)
    return a != b


def compare(
    published: PublishedPoint,
    model: ModelPoint,
    *,
    tolerance: float,
    tolerance_justification: str,
    not_applicable: Iterable[str] = (),
) -> ComparisonResult:
    """Compare in the unit shared by both points; absolute tolerance in that unit."""
    if isinstance(tolerance, bool) or not math.isfinite(tolerance) or tolerance <= 0:
        raise BenchmarkError(f"tolerance must be a positive finite number, got {tolerance!r}")
    justification = check_text(tolerance_justification, "tolerance_justification")
    skipped = frozenset(not_applicable)
    unknown = sorted(skipped - set(CONDITION_FIELDS))
    if unknown:
        raise BenchmarkError(f"not_applicable names unknown condition fields {unknown}")

    reasons: list[str] = []
    if published.quantity != model.quantity:
        reasons.append(f"quantity differs ({published.quantity!r} vs {model.quantity!r})")
    if published.unit != model.unit:
        reasons.append(
            f"unit differs ({published.unit!r} vs {model.unit!r}); no conversion is applied"
        )
    if published.value is None:
        reasons.append("published value is null")
    if model.value is None:
        reasons.append("model value is null")
    for name in CONDITION_FIELDS:
        a, b = getattr(published, name), getattr(model, name)
        if name in skipped:
            if a is not None or b is not None:
                reasons.append(f"{name} was declared not applicable but is set ({a!r}, {b!r})")
        elif a is None and b is None:
            reasons.append(f"{name} is null on both sides (declare it not applicable or fill it)")
        elif a is None or b is None:
            side = "published" if a is None else "model"
            reasons.append(f"{name} is null on the {side} side")
        elif _differs(name, a, b):
            reasons.append(f"{name} differs ({a!r} vs {b!r})")
    if reasons:
        return ComparisonResult(
            status=ComparisonStatus.NOT_COMPARABLE,
            reason="; ".join(reasons),
            published_value=published.value,
            model_value=model.value,
            tolerance=tolerance,
            tolerance_justification=justification,
            unit=published.unit,
            published_evidence=published.evidence,
            model_evidence=model.evidence,
        )
    assert published.value is not None and model.value is not None
    deviation = model.value - published.value
    matched = abs(deviation) <= tolerance
    return ComparisonResult(
        status=ComparisonStatus.MATCH if matched else ComparisonStatus.MISMATCH,
        reason="within tolerance" if matched else "outside tolerance",
        published_value=published.value,
        model_value=model.value,
        deviation=deviation,
        tolerance=tolerance,
        tolerance_justification=justification,
        unit=published.unit,
        published_evidence=published.evidence,
        model_evidence=model.evidence,
    )
