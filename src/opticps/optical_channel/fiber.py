"""Selectable fiber models, including ITU-T G.652.D (08/2024, edition 10.0).

Each value carries its provenance, because a specification limit, a typical link value,
a data sheet figure and a laboratory measurement are different kinds of number. Limits
describe what a compliant cable may not exceed; they do not describe any particular fiber.

Equation and table numbers refer to Recommendation ITU-T G.652 (08/2024). Limits on
attenuation apply to cable, and Note 1 of Table 2 excludes short cables such as jumpers.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import re
from collections.abc import Hashable, Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import yaml

SOURCE_G652 = "Rec. ITU-T G.652 (08/2024), edition 10.0"
BAND_LOW_NM = 1260.0
BAND_HIGH_NM = 1625.0
SELLMEIER_LIMIT_NM = 1460.0

# Table 2.
LAMBDA0_MIN_NM = 1300.0
LAMBDA0_MAX_NM = 1324.0
S0_MIN = 0.073
S0_MAX = 0.092
ATTENUATION_MAX = 0.40
ATTENUATION_MAX_C_BAND = 0.30
ATTENUATION_NOTE2_ADDITION = 0.07
PMD_Q_MAX = 0.20

# Table I.1: typical link values.
TYPICAL_D1550 = 17.0
TYPICAL_S1550 = 0.056
TYPICAL_ATTENUATION = (
    (1260.0, 1360.0, 0.5),
    (1530.0, 1565.0, 0.275),
    (1565.0, 1625.0, 0.35),
)


class ValueSource(StrEnum):
    """The kind of number a fiber parameter is."""

    SPECIFICATION_LIMIT = "specification-limit"
    REPRESENTATIVE = "representative-simulation-value"
    MANUFACTURER = "manufacturer-data"
    MEASURED = "laboratory-measured"
    DEFAULT = "simulation-default"
    USER_SPECIFIED = "user-specified"


def _check_band(wavelength_nm: float) -> None:
    if not BAND_LOW_NM <= wavelength_nm <= BAND_HIGH_NM:
        raise ValueError(
            f"{wavelength_nm} nm is outside the {BAND_LOW_NM:g} to {BAND_HIGH_NM:g} nm range "
            "that G.652.D bounds"
        )


def sellmeier_dispersion(wavelength_nm: float, lambda0_nm: float, s0: float) -> float:
    """Return D in ps/(nm km) by the three-term form, Eq. (I-5)."""
    return float(wavelength_nm * s0 / 4 * (1 - (lambda0_nm / wavelength_nm) ** 4))


def sellmeier_slope(wavelength_nm: float, lambda0_nm: float, s0: float) -> float:
    """Return dD/d(lambda) in ps/(nm^2 km), the derivative of Eq. (I-5)."""
    return float(s0 / 4 * (1 + 3 * (lambda0_nm / wavelength_nm) ** 4))


def g652d_dispersion_limits(wavelength_nm: float) -> tuple[float, float]:
    """Return the (lower, upper) bound on D from Eq. (6-2a,b,c) and (6-3)."""
    _check_band(wavelength_nm)
    if wavelength_nm > SELLMEIER_LIMIT_NM:
        offset = wavelength_nm - SELLMEIER_LIMIT_NM
        return 8.625 + 0.052 * offset, 12.472 + 0.068 * offset
    if wavelength_nm < LAMBDA0_MIN_NM:
        return (
            sellmeier_dispersion(wavelength_nm, LAMBDA0_MAX_NM, S0_MAX),
            sellmeier_dispersion(wavelength_nm, LAMBDA0_MIN_NM, S0_MIN),
        )
    if wavelength_nm <= LAMBDA0_MAX_NM:
        return (
            sellmeier_dispersion(wavelength_nm, LAMBDA0_MAX_NM, S0_MAX),
            sellmeier_dispersion(wavelength_nm, LAMBDA0_MIN_NM, S0_MAX),
        )
    return (
        sellmeier_dispersion(wavelength_nm, LAMBDA0_MAX_NM, S0_MIN),
        sellmeier_dispersion(wavelength_nm, LAMBDA0_MIN_NM, S0_MAX),
    )


def g652d_attenuation_limit(wavelength_nm: float) -> float:
    """Return the maximum cable attenuation in dB/km from Table 2.

    Below 1310 nm, Note 2 extends the range to 1260 nm by adding 0.07 dB/km. The text does
    not give the intermediate curve, so the addition is applied across the whole extension.
    """
    _check_band(wavelength_nm)
    if 1530.0 <= wavelength_nm <= 1565.0:
        return ATTENUATION_MAX_C_BAND
    if wavelength_nm < 1310.0:
        return ATTENUATION_MAX + ATTENUATION_NOTE2_ADDITION
    return ATTENUATION_MAX


def fit_sellmeier_to_typical(
    d1550: float = TYPICAL_D1550, s1550: float = TYPICAL_S1550
) -> tuple[float, float]:
    """Return (lambda0, S0) of the three-term curve through D and S at 1550 nm.

    This is a derived model choice, not a value stated in the Recommendation.
    """
    ratio = d1550 / (1550.0 * s1550)
    r = (1 - ratio) / (1 + 3 * ratio)
    return 1550.0 * r**0.25, 4 * s1550 / (1 + 3 * r)


def typical_attenuation(wavelength_nm: float) -> float:
    """Return the Table I.1 link value; between bands, a linear interpolation (assumption)."""
    _check_band(wavelength_nm)
    for low, high, value in TYPICAL_ATTENUATION:
        if low <= wavelength_nm <= high:
            return value
    return float(np.interp(wavelength_nm, [1360.0, 1530.0], [0.5, 0.275]))


@dataclass(frozen=True)
class FiberParameters:
    """Fiber values at one wavelength, each with its provenance."""

    fiber_type: str
    wavelength_nm: float
    attenuation_db_per_km: float
    dispersion_ps_per_nm_km: float
    dispersion_slope_ps_per_nm2_km: float
    attenuation_source: ValueSource
    dispersion_source: ValueSource
    dispersion_slope_source: ValueSource
    assumptions: str
    reference: str

    def __post_init__(self) -> None:
        if self.wavelength_nm <= 0 or self.attenuation_db_per_km < 0:
            raise ValueError("Wavelength must be positive and attenuation non-negative")

    def to_metadata(self) -> dict[str, Any]:
        """Return values with units for saving alongside a simulation."""
        record = asdict(self)
        record["attenuation_source"] = self.attenuation_source.value
        record["dispersion_source"] = self.dispersion_source.value
        record["dispersion_slope_source"] = self.dispersion_slope_source.value
        record["units"] = {
            "wavelength": "nm",
            "attenuation": "dB/km",
            "dispersion": "ps/(nm km)",
            "dispersion_slope": "ps/(nm^2 km)",
        }
        return record


def g652d_preset(wavelength_nm: float, variant: str = "representative") -> FiberParameters:
    """Return a G.652.D preset.

    variant is representative, or limit-low or limit-high, which sit on a dispersion bound
    with attenuation at the Table 2 maximum. Limits are a worst-case envelope, not a fiber.
    """
    _check_band(wavelength_nm)
    if variant == "representative":
        lambda0, s0 = fit_sellmeier_to_typical()
        return FiberParameters(
            "ITU-T G.652.D",
            wavelength_nm,
            typical_attenuation(wavelength_nm),
            sellmeier_dispersion(wavelength_nm, lambda0, s0),
            sellmeier_slope(wavelength_nm, lambda0, s0),
            ValueSource.REPRESENTATIVE,
            ValueSource.REPRESENTATIVE,
            ValueSource.REPRESENTATIVE,
            f"Attenuation: Table I.1 link values, linear between bands. Dispersion: three-term "
            f"curve fitted through Table I.1 D1550 and S1550 (lambda0 {lambda0:.1f} nm, S0 "
            f"{s0:.4f}). Not a specific fiber.",
            SOURCE_G652,
        )
    if variant not in ("limit-low", "limit-high"):
        raise ValueError(f"Unknown G.652.D variant {variant!r}")
    low, high = g652d_dispersion_limits(wavelength_nm)
    bound = low if variant == "limit-low" else high
    step = 0.5
    edge_a = max(BAND_LOW_NM, wavelength_nm - step)
    edge_b = min(BAND_HIGH_NM, wavelength_nm + step)
    index = 0 if variant == "limit-low" else 1
    slope = (g652d_dispersion_limits(edge_b)[index] - g652d_dispersion_limits(edge_a)[index]) / (
        edge_b - edge_a
    )
    return FiberParameters(
        "ITU-T G.652.D",
        wavelength_nm,
        g652d_attenuation_limit(wavelength_nm),
        bound,
        slope,
        ValueSource.SPECIFICATION_LIMIT,
        ValueSource.SPECIFICATION_LIMIT,
        ValueSource.SPECIFICATION_LIMIT,
        "On a specification boundary; the slope is the local slope of the bound curve. "
        "Worst-case envelope, not a real fiber.",
        SOURCE_G652,
    )


def custom_fiber(
    fiber_type: str,
    wavelength_nm: float,
    attenuation_db_per_km: float,
    dispersion_ps_per_nm_km: float,
    dispersion_slope_ps_per_nm2_km: float,
    source: ValueSource,
    reference: str,
) -> FiberParameters:
    """Describe a fiber that is not G.652.D, or one with a data sheet or measured values."""
    return FiberParameters(
        fiber_type,
        wavelength_nm,
        attenuation_db_per_km,
        dispersion_ps_per_nm_km,
        dispersion_slope_ps_per_nm2_km,
        source,
        source,
        source,
        "User-supplied values; no standard limits applied.",
        reference,
    )


def apply_measurements(
    base: FiberParameters,
    reference: str,
    attenuation_db_per_km: float | None = None,
    dispersion_ps_per_nm_km: float | None = None,
    dispersion_slope_ps_per_nm2_km: float | None = None,
) -> FiberParameters:
    """Override preset values with Southampton measurements, keeping what was not measured.

    Each value has its own provenance tag: a measured D does not relabel the slope, and a
    measured slope is tagged as measured. Length and wavelength are not set here; they are the
    fiber_length_km of the link and the wavelength passed to the preset.
    """
    updated = base
    if attenuation_db_per_km is not None:
        updated = replace(
            updated,
            attenuation_db_per_km=attenuation_db_per_km,
            attenuation_source=ValueSource.MEASURED,
        )
    if dispersion_ps_per_nm_km is not None:
        updated = replace(
            updated,
            dispersion_ps_per_nm_km=dispersion_ps_per_nm_km,
            dispersion_source=ValueSource.MEASURED,
        )
    if dispersion_slope_ps_per_nm2_km is not None:
        updated = replace(
            updated,
            dispersion_slope_ps_per_nm2_km=dispersion_slope_ps_per_nm2_km,
            dispersion_slope_source=ValueSource.MEASURED,
        )
    return replace(updated, reference=f"{base.reference}; measured: {reference}")


def within_g652d_limits(fiber: FiberParameters) -> dict[str, bool]:
    """Compare values with Table 2 and Eq. (6-2,6-3). Does not imply compliance of a cable."""
    low, high = g652d_dispersion_limits(fiber.wavelength_nm)
    return {
        "dispersion": low <= fiber.dispersion_ps_per_nm_km <= high,
        "attenuation": fiber.attenuation_db_per_km
        <= g652d_attenuation_limit(fiber.wavelength_nm) + 1e-12,
    }


FIBER_PRESETS = ("none", "g652d-representative", "g652d-limit-low", "g652d-limit-high", "custom")


def select_fiber(
    preset: str, wavelength_nm: float = 1550.0, **custom: Any
) -> FiberParameters | None:
    """Return the fiber for a preset name, or None for the v1.0 defaults ("none").

    "custom" passes its keyword arguments (fiber_type, attenuation_db_per_km, and so on) to
    custom_fiber. No fiber type is chosen unless asked for.
    """
    if preset == "none":
        return None
    if preset == "custom":
        return custom_fiber(wavelength_nm=wavelength_nm, **custom)
    if preset.startswith("g652d-"):
        return g652d_preset(wavelength_nm, preset.removeprefix("g652d-"))
    raise ValueError(f"Unknown fiber preset {preset!r}; choose from {FIBER_PRESETS}")


# ---------------------------------------------------------------------------------------------
# Configurable fiber profiles (NANF workstream, Gate N1)
#
# A profile is a described physical fiber sample. Nothing in it is a default: a property whose
# value is not known is stored as unknown, and asking for it raises. The G.652.D functions above
# are unchanged and still the only place a standard value is supplied.
# ---------------------------------------------------------------------------------------------

PROFILE_FILE_VERSION = 1
# Effects the propagation model does not implement. A profile may state them "off"; asking for
# one to be on raises when the profile is used.
UNSUPPORTED_EFFECTS = ("kerr", "intermodal_coupling", "gas_absorption", "amplifier_noise")
_WAVELENGTH_TOLERANCE_NM = 1e-9


class FiberProfileError(ValueError):
    """A profile is malformed or cannot be used as asked."""


class MissingFiberPropertyError(FiberProfileError):
    """A property the propagation needs is unknown; no default is substituted."""


class OutOfValidityRangeError(FiberProfileError):
    """The wavelength lies outside what a value or table is stated for."""


class UnsupportedEffectError(FiberProfileError, NotImplementedError):
    """An effect the model does not implement was requested."""


class ProvenanceCategory(StrEnum):
    """How a profile value became known (closed set of eight)."""

    MEASURED = "measured"
    PUBLISHED_EXPERIMENTAL = "published-experimental"
    PUBLISHED_NUMERICAL_ASSUMPTION = "published-numerical-assumption"
    DERIVED = "derived"
    REPRESENTATIVE_LITERATURE = "representative-literature"
    USER_ASSUMED = "user-assumed"
    FITTED_TRAINING_ONLY = "fitted-training-only"
    UNKNOWN = "unknown"


# Words that, alone, are not a citation. A measured or published value needs a citation that has at
# least 8 non-space characters and at least one word outside this set (form check only: it cannot
# tell whether the cited place exists).
_PLACEHOLDER_WORDS = frozenset(
    "none n a na nil null tbd todo unknown unspecified not available applicable given provided "
    "no citation source sources ref reference see text paper article tba x".split()
)
_CITED_CATEGORIES = ("measured", "published-experimental", "published-numerical-assumption")


def is_real_citation(citation: str) -> bool:
    """Return True if the text is more than a blank or placeholder such as "none" or "n/a"."""
    if len(citation.replace(" ", "")) < 8:
        return False
    words = re.findall(r"[a-z0-9]+", citation.casefold())
    return any(w not in _PLACEHOLDER_WORDS for w in words)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise FiberProfileError(f"{name} must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class ParameterProvenance:
    """Where one value comes from: category, exact citation, wavelength, uncertainty, validity."""

    category: ProvenanceCategory
    citation: str
    measurement_wavelength_nm: float | None = None
    uncertainty: float | None = None
    validity_range_nm: tuple[float, float] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", ProvenanceCategory(self.category))
        if not isinstance(self.citation, str):
            raise FiberProfileError("citation must be text")
        if self.category is not ProvenanceCategory.UNKNOWN and not self.citation.strip():
            raise FiberProfileError(f"a {self.category.value} value needs an exact citation")
        if self.category.value in _CITED_CATEGORIES and not is_real_citation(self.citation):
            raise FiberProfileError(
                f"a {self.category.value} value needs a real citation, not {self.citation!r} "
                "(at least 8 characters and a word that is not a placeholder such as none)"
            )
        if self.measurement_wavelength_nm is not None and (
            _finite(self.measurement_wavelength_nm, "measurement_wavelength_nm") <= 0
        ):
            raise FiberProfileError("measurement_wavelength_nm must be positive")
        if self.uncertainty is not None and _finite(self.uncertainty, "uncertainty") < 0:
            raise FiberProfileError("uncertainty must be non-negative")
        if self.validity_range_nm is not None:
            low, high = (_finite(v, "validity_range_nm") for v in self.validity_range_nm)
            if not 0 < low <= high:
                raise FiberProfileError("validity_range_nm must be positive and ordered")
            object.__setattr__(self, "validity_range_nm", (low, high))


@dataclass(frozen=True)
class ProfileValue:
    """A number with unit and provenance; value None if and only if the category is unknown."""

    value: float | None
    unit: str
    provenance: ParameterProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise FiberProfileError("a value needs a unit")
        unknown = self.provenance.category is ProvenanceCategory.UNKNOWN
        if unknown != (self.value is None):
            raise FiberProfileError("value is null if and only if the category is unknown")
        if self.value is not None:
            object.__setattr__(self, "value", _finite(self.value, "value"))

    @property
    def known(self) -> bool:
        return self.value is not None

    @property
    def stated_range_nm(self) -> tuple[float, float] | None:
        """Wavelength span the value is stated for; None means no restriction was declared.

        An explicit validity range wins; else the measurement wavelength alone; else none.
        """
        p = self.provenance
        if p.validity_range_nm is not None:
            return p.validity_range_nm
        if p.measurement_wavelength_nm is not None:
            return (p.measurement_wavelength_nm, p.measurement_wavelength_nm)
        return None

    def covers(self, wavelength_nm: float) -> bool:
        span = self.stated_range_nm
        if span is None:
            return True
        tol = _WAVELENGTH_TOLERANCE_NM
        return span[0] - tol <= wavelength_nm <= span[1] + tol


@dataclass(frozen=True)
class WavelengthTable:
    """A measured or published curve (loss or dispersion) on a strictly increasing grid."""

    name: str
    wavelengths_nm: tuple[float, ...]
    values: tuple[float, ...]
    unit: str
    provenance: ParameterProvenance

    def __post_init__(self) -> None:
        wl = tuple(_finite(v, "table wavelength") for v in self.wavelengths_nm)
        vals = tuple(_finite(v, "table value") for v in self.values)
        if len(wl) < 2 or len(wl) != len(vals):
            raise FiberProfileError("a table needs at least two knots and one value per knot")
        if any(b <= a for a, b in zip(wl, wl[1:], strict=False)) or wl[0] <= 0:
            raise FiberProfileError("table wavelengths must be positive and strictly increasing")
        if self.provenance.category is ProvenanceCategory.UNKNOWN:
            raise FiberProfileError("a table with values cannot be of unknown provenance")
        object.__setattr__(self, "wavelengths_nm", wl)
        object.__setattr__(self, "values", vals)

    def at(self, wavelength_nm: float, allow_extrapolation: bool = False) -> tuple[float, bool]:
        """Return (value, extrapolated). Outside the knots raise unless extrapolation is asked.

        Inside, linear interpolation. Extrapolation continues the end segment linearly.
        """
        wl, vals = self.wavelengths_nm, self.values
        if wl[0] <= wavelength_nm <= wl[-1]:
            return float(np.interp(wavelength_nm, wl, vals)), False
        if not allow_extrapolation:
            raise OutOfValidityRangeError(
                f"{wavelength_nm:g} nm is outside table {self.name!r} "
                f"({wl[0]:g} to {wl[-1]:g} nm); no extrapolation was requested"
            )
        i, j = (0, 1) if wavelength_nm < wl[0] else (-2, -1)
        slope = (vals[j] - vals[i]) / (wl[j] - wl[i])
        return vals[j] + slope * (wavelength_nm - wl[j]), True


@dataclass(frozen=True)
class LossEnvelope:
    """A total-link loss range over a band. It is not assigned to any single wavelength."""

    low_db: float
    high_db: float
    band_nm: tuple[float, float]
    provenance: ParameterProvenance
    note: str = ""

    def __post_init__(self) -> None:
        if not 0 <= _finite(self.low_db, "low_db") <= _finite(self.high_db, "high_db"):
            raise FiberProfileError("envelope must satisfy 0 <= low <= high")
        if not 0 < self.band_nm[0] <= self.band_nm[1]:
            raise FiberProfileError("envelope band must be positive and ordered")


@dataclass(frozen=True)
class ContextMeasurement:
    """A number valid only in its own measurement context (not a fiber property)."""

    name: str
    value: float
    unit: str
    wavelength_nm: float
    context: str
    provenance: ParameterProvenance

    def __post_init__(self) -> None:
        _finite(self.value, "value")
        if _finite(self.wavelength_nm, "wavelength_nm") <= 0 or not self.context.strip():
            raise FiberProfileError("a context measurement needs a wavelength and a context")


@dataclass(frozen=True)
class SensitivityScenario:
    """An explicit, labelled stand-in for unknown values. It never overrides a known value."""

    label: str
    values: Mapping[str, float]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise FiberProfileError("a sensitivity scenario needs a label")
        allowed = set(_SCENARIO_FIELDS)
        extra = set(self.values) - allowed
        if extra:
            raise FiberProfileError(f"scenario fields not allowed: {sorted(extra)}")
        checked = {k: _finite(v, k) for k, v in dict(self.values).items()}
        for name, value in checked.items():
            _, minimum, strict = _SCALAR_FIELDS[name]
            if minimum is not None and (value < minimum or (strict and value == minimum)):
                raise FiberProfileError(
                    f"scenario value {name}={value} is outside its physical range "
                    f"(minimum {minimum}{', exclusive' if strict else ''})"
                )
        object.__setattr__(self, "values", MappingProxyType(checked))


# profile field name -> (unit, minimum, strict minimum?)
_SCALAR_FIELDS: dict[str, tuple[str, float | None, bool]] = {
    "length_km": ("km", 0.0, True),
    "reference_wavelength_nm": ("nm", 0.0, True),
    "attenuation_db_per_km": ("dB/km", 0.0, False),
    "connector_loss_db": ("dB", 0.0, False),
    "pigtail_loss_db": ("dB", 0.0, False),
    "splice_loss_db": ("dB", 0.0, False),
    "dispersion_ps_per_nm_km": ("ps/(nm km)", None, False),
    "dispersion_slope_ps_per_nm2_km": ("ps/(nm^2 km)", None, False),
    "group_index": ("1", 1.0, False),
    "gamma_per_w_km": ("1/(W km)", 0.0, False),
}
_SCENARIO_FIELDS = tuple(f for f in _SCALAR_FIELDS if f != "reference_wavelength_nm")
_LUMPED_FIELDS = ("connector_loss_db", "pigtail_loss_db", "splice_loss_db")


@dataclass(frozen=True)
class FiberProfile:
    """A described fiber sample with per-parameter provenance.

    No property has a default. Unknown values are explicit (`ProfileValue` with category
    unknown) and raise when the propagation needs them. `gamma_per_w_km` is stored only: the
    model has no Kerr effect, and requesting it raises. Lumped losses are separate components,
    each counted once. `link_loss_envelope` is informational and never enters a calculation.
    """

    profile_id: str
    fiber_type: str
    sample_id: str | None
    length_km: ProfileValue
    reference_wavelength_nm: ProfileValue
    attenuation_db_per_km: ProfileValue
    connector_loss_db: ProfileValue
    pigtail_loss_db: ProfileValue
    splice_loss_db: ProfileValue
    dispersion_ps_per_nm_km: ProfileValue
    dispersion_slope_ps_per_nm2_km: ProfileValue
    group_index: ProfileValue
    gamma_per_w_km: ProfileValue
    effects: Mapping[str, str]
    loss_table: WavelengthTable | None = None
    dispersion_table: WavelengthTable | None = None
    geometry: Mapping[str, ProfileValue] = field(default_factory=dict)
    link_loss_envelope: LossEnvelope | None = None
    measurements: tuple[ContextMeasurement, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.fiber_type.strip():
            raise FiberProfileError("profile_id and fiber_type must be non-blank")
        if self.sample_id is not None and not self.sample_id.strip():
            raise FiberProfileError("sample_id is null or non-blank")
        for name, (unit, minimum, strict) in _SCALAR_FIELDS.items():
            pv = getattr(self, name)
            if not isinstance(pv, ProfileValue) or pv.unit != unit:
                raise FiberProfileError(f"{name} must be a ProfileValue in {unit}")
            if pv.value is not None and minimum is not None:
                if pv.value < minimum or (strict and pv.value == minimum):
                    raise FiberProfileError(f"{name}={pv.value} is outside its physical range")
        bad = set(self.effects) - set(UNSUPPORTED_EFFECTS)
        missing = set(UNSUPPORTED_EFFECTS) - set(self.effects)
        if bad or missing or any(v not in ("off", "on") for v in self.effects.values()):
            raise FiberProfileError(
                f"effects must state each of {UNSUPPORTED_EFFECTS} as 'off' or 'on'"
            )
        for table, field_name in (
            (self.loss_table, "attenuation_db_per_km"),
            (self.dispersion_table, "dispersion_ps_per_nm_km"),
        ):
            if table is not None:
                unit = _SCALAR_FIELDS[field_name][0]
                if table.unit != unit:
                    raise FiberProfileError(
                        f"table {table.name!r} for {field_name} must be in {unit}, got "
                        f"{table.unit!r}"
                    )
                if field_name == "attenuation_db_per_km" and min(table.values) < 0:
                    raise FiberProfileError(f"loss table {table.name!r} has a negative loss")
        object.__setattr__(self, "effects", MappingProxyType(dict(self.effects)))
        object.__setattr__(self, "geometry", MappingProxyType(dict(self.geometry)))
        object.__setattr__(self, "measurements", tuple(self.measurements))

    def requested_effects(self) -> tuple[str, ...]:
        return tuple(k for k in UNSUPPORTED_EFFECTS if self.effects[k] == "on")


@dataclass(frozen=True)
class ResolvedFiber:
    """Profile values at one wavelength, all known, each with where it came from."""

    profile_id: str
    sample_id: str | None
    wavelength_nm: float
    length_km: float
    attenuation_db_per_km: float
    connector_loss_db: float
    pigtail_loss_db: float
    splice_loss_db: float
    dispersion_ps_per_nm_km: float
    dispersion_slope_ps_per_nm2_km: float | None
    group_index: float | None
    gamma_per_w_km: float | None
    sources: Mapping[str, str]
    extrapolated: tuple[str, ...] = ()
    scenario_label: str | None = None

    @property
    def lumped_loss_db(self) -> float:
        return self.connector_loss_db + self.pigtail_loss_db + self.splice_loss_db

    @property
    def distributed_loss_db(self) -> float:
        return self.attenuation_db_per_km * self.length_km

    @property
    def total_loss_db(self) -> float:
        return self.distributed_loss_db + self.lumped_loss_db

    def to_record(self) -> dict[str, Any]:
        """Return the values with units, sources and flags, for saving beside a result."""
        return {
            "profile_id": self.profile_id,
            "sample_id": self.sample_id,
            "wavelength_nm": self.wavelength_nm,
            "length_km": self.length_km,
            "attenuation_db_per_km": self.attenuation_db_per_km,
            "connector_loss_db": self.connector_loss_db,
            "pigtail_loss_db": self.pigtail_loss_db,
            "splice_loss_db": self.splice_loss_db,
            "distributed_loss_db": self.distributed_loss_db,
            "lumped_loss_db": self.lumped_loss_db,
            "total_loss_db": self.total_loss_db,
            "dispersion_ps_per_nm_km": self.dispersion_ps_per_nm_km,
            "dispersion_slope_ps_per_nm2_km": self.dispersion_slope_ps_per_nm2_km,
            "slope_omitted_second_order_only": self.dispersion_slope_ps_per_nm2_km is None,
            "group_index": self.group_index,
            "gamma_per_w_km_stored_not_active": self.gamma_per_w_km,
            "sources": dict(self.sources),
            "extrapolated": list(self.extrapolated),
            "sensitivity_scenario": self.scenario_label,
            **({"not_a_benchmark_result": True} if self.scenario_label is not None else {}),
            "kerr_intermodal_gas_absorption_amplifier_noise": "off (unsupported)",
            "units": {
                "wavelength": "nm",
                "length": "km",
                "attenuation": "dB/km",
                "lumped": "dB",
                "dispersion": "ps/(nm km)",
                "dispersion_slope": "ps/(nm^2 km)",
                "gamma": "1/(W km)",
            },
        }


def resolve_profile(
    profile: FiberProfile,
    wavelength_nm: float,
    *,
    scenario: SensitivityScenario | None = None,
    allow_extrapolation: bool = False,
) -> ResolvedFiber:
    """Return the profile's values at one wavelength, or raise.

    Unknown values raise MissingFiberPropertyError unless the scenario supplies them, and then
    they are labelled as scenario values. A known value is never overridden. A wavelength outside
    the stated range of a value or table raises OutOfValidityRangeError unless extrapolation is
    requested; extrapolated names are listed in the result. The G.652.D numbers are never used.
    """
    wavelength_nm = _finite(wavelength_nm, "wavelength_nm")
    if wavelength_nm <= 0:
        raise FiberProfileError("wavelength must be positive")
    requested = profile.requested_effects()
    if requested:
        raise UnsupportedEffectError(
            f"effects {requested} are not implemented (Kerr, inter-modal coupling, gas "
            "absorption and amplifier noise are unsupported); set them to 'off'"
        )
    values = dict(scenario.values) if scenario is not None else {}
    label = None if scenario is None else scenario.label
    sources: dict[str, str] = {}
    extrapolated: list[str] = []
    missing: list[str] = []
    out: dict[str, float | None] = {}
    tabled = {
        "attenuation_db_per_km": profile.loss_table is not None,
        "dispersion_ps_per_nm_km": profile.dispersion_table is not None,
    }
    for name in values:
        if getattr(profile, name).known or tabled.get(name, False):
            raise FiberProfileError(
                f"scenario {label!r} would override the known value of {name}; a scenario "
                "may fill unknown values only"
            )
    # Tables first: they replace the scalar for loss and for D.
    table_value: dict[str, float] = {}
    for name, table in (
        ("attenuation_db_per_km", profile.loss_table),
        ("dispersion_ps_per_nm_km", profile.dispersion_table),
    ):
        if table is not None:
            value, extr = table.at(wavelength_nm, allow_extrapolation)
            table_value[name] = value
            sources[name] = f"{table.provenance.category.value} (table {table.name})"
            if extr:
                extrapolated.append(name)
    slope_pv = profile.dispersion_slope_ps_per_nm2_km
    slope_known = slope_pv.known
    for name in _SCENARIO_FIELDS:
        pv = getattr(profile, name)
        if name in table_value:
            out[name] = table_value[name]
            continue
        if not pv.known:
            if name in values:
                out[name] = values[name]
                sources[name] = f"scenario: {label}"
            elif name in (
                "dispersion_slope_ps_per_nm2_km",
                "group_index",
                "gamma_per_w_km",
            ):
                out[name] = None
                sources[name] = "unknown (not needed; omitted)"
            else:
                missing.append(name)
            continue
        assert pv.value is not None
        sources[name] = pv.provenance.category.value
        value = pv.value
        is_d = name == "dispersion_ps_per_nm_km"
        if is_d and pv.stated_range_nm is None:
            raise OutOfValidityRangeError(
                "dispersion_ps_per_nm_km states no wavelength (neither a measurement wavelength "
                "nor a validity range), so it cannot be placed on the wavelength axis; state one"
            )
        if not pv.covers(wavelength_nm):
            if not allow_extrapolation:
                span = pv.stated_range_nm
                raise OutOfValidityRangeError(
                    f"{name} is stated for {span} nm only; {wavelength_nm:g} nm needs an explicit "
                    "extrapolation request or a table"
                )
            extrapolated.append(name)
        if is_d and slope_known:
            # D(lambda) = D_ref + S (lambda - lambda_ref), from the profile's reference wavelength,
            # inside the stated range and, when extrapolation was requested, beyond it (no clamp).
            ref_pv = profile.reference_wavelength_nm
            if not ref_pv.known:
                raise MissingFiberPropertyError(
                    "reference_wavelength_nm is unknown; a dispersion slope needs it"
                )
            assert slope_pv.value is not None and ref_pv.value is not None
            value = pv.value + slope_pv.value * (wavelength_nm - ref_pv.value)
        out[name] = value
    if missing:
        raise MissingFiberPropertyError(
            f"profile {profile.profile_id!r} has unknown {missing}; supply a measurement, or an "
            "explicit SensitivityScenario with a label. G.652.D or other defaults are never "
            "substituted"
        )
    if scenario is not None and not any(s.startswith("scenario") for s in sources.values()):
        raise FiberProfileError(f"scenario {label!r} was given but filled nothing")
    length = out["length_km"]
    attenuation = out["attenuation_db_per_km"]
    dispersion = out["dispersion_ps_per_nm_km"]
    assert length is not None and attenuation is not None and dispersion is not None
    lumps = [out[n] for n in _LUMPED_FIELDS]
    assert all(v is not None for v in lumps)
    for name, bound in (("length_km", 0.0), ("attenuation_db_per_km", 0.0)):
        if (out[name] or 0.0) < bound:
            raise FiberProfileError(f"{name} resolved to a negative value")
    return ResolvedFiber(
        profile_id=profile.profile_id,
        sample_id=profile.sample_id,
        wavelength_nm=wavelength_nm,
        length_km=length,
        attenuation_db_per_km=attenuation,
        connector_loss_db=float(out["connector_loss_db"] or 0.0),
        pigtail_loss_db=float(out["pigtail_loss_db"] or 0.0),
        splice_loss_db=float(out["splice_loss_db"] or 0.0),
        dispersion_ps_per_nm_km=dispersion,
        dispersion_slope_ps_per_nm2_km=out["dispersion_slope_ps_per_nm2_km"],
        group_index=out["group_index"],
        gamma_per_w_km=out["gamma_per_w_km"],
        sources=MappingProxyType(sources),
        extrapolated=tuple(extrapolated),
        scenario_label=label,
    )


# --- strict YAML loader ------------------------------------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping key given twice (PyYAML keeps the last one silently)."""


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    loader.flatten_mapping(node)
    seen: set[Hashable] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"duplicate key {key!r}"
            )
        seen.add(key)
    return loader.construct_mapping(node, deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)

_PROVENANCE_KEYS = {
    "category",
    "citation",
    "measurement_wavelength_nm",
    "uncertainty",
    "validity_range_nm",
    "note",
}
_VALUE_KEYS = {"value", "unit", "provenance"}
_PROFILE_REQUIRED = {
    "fiber_profile_version",
    "kind",
    "profile_id",
    "fiber_type",
    "sample_id",
    "effects",
    *_SCALAR_FIELDS,
}
_PROFILE_OPTIONAL = {"loss_table", "dispersion_table", "geometry", "link_loss_envelope"} | {
    "measurements",
    "notes",
}


def _mapping(node: object, where: str, required: set[str], optional: set[str]) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise FiberProfileError(f"{where}: expected a mapping")
    keys = set(node)
    if missing := required - keys:
        raise FiberProfileError(f"{where}: missing keys {sorted(missing)}")
    if extra := keys - required - optional:
        raise FiberProfileError(f"{where}: unknown keys {sorted(extra)}")
    return node


def _parse_provenance(node: object, where: str) -> ParameterProvenance:
    d = _mapping(node, where, {"category", "citation"}, _PROVENANCE_KEYS - {"category", "citation"})
    span = d.get("validity_range_nm")
    if span is not None:
        if not isinstance(span, list) or len(span) != 2:
            raise FiberProfileError(f"{where}: validity_range_nm is a two-item list")
        span = (span[0], span[1])
    try:
        return ParameterProvenance(
            d["category"],
            d["citation"],
            d.get("measurement_wavelength_nm"),
            d.get("uncertainty"),
            span,
            d.get("note", ""),
        )
    except ValueError as err:
        raise FiberProfileError(f"{where}: {err}") from err


def _parse_value(node: object, where: str) -> ProfileValue:
    d = _mapping(node, where, _VALUE_KEYS, set())
    return ProfileValue(d["value"], d["unit"], _parse_provenance(d["provenance"], where))


def _parse_table(node: object, where: str) -> WavelengthTable:
    d = _mapping(node, where, {"name", "unit", "wavelengths_nm", "values", "provenance"}, set())
    return WavelengthTable(
        d["name"],
        tuple(d["wavelengths_nm"]),
        tuple(d["values"]),
        d["unit"],
        _parse_provenance(d["provenance"], where),
    )


def profile_from_mapping(data: object) -> FiberProfile:
    """Build a FiberProfile from parsed YAML; unknown or missing keys raise."""
    d = _mapping(data, "profile", _PROFILE_REQUIRED, _PROFILE_OPTIONAL)
    if d["fiber_profile_version"] != PROFILE_FILE_VERSION or d["kind"] != "profile":
        raise FiberProfileError("expected fiber_profile_version 1 and kind: profile")
    scalars = {name: _parse_value(d[name], name) for name in _SCALAR_FIELDS}
    envelope = None
    if d.get("link_loss_envelope") is not None:
        e = _mapping(
            d["link_loss_envelope"],
            "link_loss_envelope",
            {"low_db", "high_db", "band_nm", "provenance"},
            {"note"},
        )
        envelope = LossEnvelope(
            e["low_db"],
            e["high_db"],
            (e["band_nm"][0], e["band_nm"][1]),
            _parse_provenance(e["provenance"], "link_loss_envelope"),
            e.get("note", ""),
        )
    measurements = []
    for i, m in enumerate(d.get("measurements") or []):
        md = _mapping(
            m,
            f"measurements[{i}]",
            {"name", "value", "unit", "wavelength_nm", "context", "provenance"},
            set(),
        )
        measurements.append(
            ContextMeasurement(
                md["name"],
                md["value"],
                md["unit"],
                md["wavelength_nm"],
                md["context"],
                _parse_provenance(md["provenance"], f"measurements[{i}]"),
            )
        )
    return FiberProfile(
        profile_id=d["profile_id"],
        fiber_type=d["fiber_type"],
        sample_id=d["sample_id"],
        effects=d["effects"],
        loss_table=_parse_table(d["loss_table"], "loss_table") if d.get("loss_table") else None,
        dispersion_table=(
            _parse_table(d["dispersion_table"], "dispersion_table")
            if d.get("dispersion_table")
            else None
        ),
        geometry={
            k: _parse_value(v, f"geometry.{k}") for k, v in (d.get("geometry") or {}).items()
        },
        link_loss_envelope=envelope,
        measurements=tuple(measurements),
        notes=d.get("notes", ""),
        **scalars,
    )


def load_fiber_config(path: str | Path) -> FiberProfile | FiberParameters:
    """Load a YAML fiber file.

    kind: profile gives a FiberProfile. kind: g652d-reference gives the existing G.652.D preset
    through g652d_preset, unchanged (keys: wavelength_nm, variant).
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as err:
        raise FiberProfileError(f"{path}: {err}") from err
    if isinstance(data, dict) and data.get("kind") == "g652d-reference":
        d = _mapping(
            data,
            "g652d-reference",
            {"fiber_profile_version", "kind", "wavelength_nm", "variant"},
            {"notes"},
        )
        return g652d_preset(float(d["wavelength_nm"]), str(d["variant"]))
    return profile_from_mapping(data)
