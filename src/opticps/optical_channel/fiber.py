"""Selectable fiber models, including ITU-T G.652.D (08/2024, edition 10.0).

Each value carries its provenance, because a specification limit, a typical link value,
a data sheet figure and a laboratory measurement are different kinds of number. Limits
describe what a compliant cable may not exceed; they do not describe any particular fiber.

Equation and table numbers refer to Recommendation ITU-T G.652 (08/2024). Limits on
attenuation apply to cable, and Note 1 of Table 2 excludes short cables such as jumpers.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

import numpy as np

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
