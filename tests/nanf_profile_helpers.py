"""Shared builders for the NANF profile and propagation tests (synthetic values, not a real fiber)."""

from opticps.optical_channel.fiber import (
    UNSUPPORTED_EFFECTS,
    FiberProfile,
    ParameterProvenance,
    ProfileValue,
    ProvenanceCategory,
)

OFF = {k: "off" for k in UNSUPPORTED_EFFECTS}


def known(value, unit, category="user-assumed", **prov):
    """A known value. D, S and attenuation must state a wavelength: pass it per call."""
    return ProfileValue(
        value, unit, ParameterProvenance(ProvenanceCategory(category), "unit test", **prov)
    )


def unknown(unit):
    return ProfileValue(None, unit, ParameterProvenance(ProvenanceCategory.UNKNOWN, "none"))


def make_profile(**over) -> FiberProfile:
    """A fully specified synthetic profile; the numbers are test inputs, not any real fiber."""
    base = {
        "profile_id": "TEST-PROFILE",
        "fiber_type": "synthetic test fiber",
        "sample_id": None,
        "length_km": known(5.0, "km"),
        "reference_wavelength_nm": known(1550.0, "nm"),
        "attenuation_db_per_km": known(
            0.5, "dB/km", measurement_wavelength_nm=1550.0, validity_range_nm=(1400.0, 1700.0)
        ),
        "connector_loss_db": known(0.0, "dB"),
        "pigtail_loss_db": known(0.0, "dB"),
        "splice_loss_db": known(0.0, "dB"),
        "dispersion_ps_per_nm_km": known(10.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        "dispersion_slope_ps_per_nm2_km": unknown("ps/(nm^2 km)"),
        "group_index": unknown("1"),
        "gamma_per_w_km": unknown("1/(W km)"),
        "effects": OFF,
    }
    base.update(over)
    return FiberProfile(**base)
