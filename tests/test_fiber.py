import numpy as np
import pytest

from opticps.optical_channel.fiber import (
    ValueSource,
    apply_measurements,
    custom_fiber,
    fit_sellmeier_to_typical,
    g652d_attenuation_limit,
    g652d_dispersion_limits,
    g652d_preset,
    sellmeier_dispersion,
    sellmeier_slope,
    typical_attenuation,
    within_g652d_limits,
)


@pytest.mark.parametrize(
    "wavelength,low,high",
    [(1550, 13.3, 18.6), (1625, 17.2, 23.7)],
)
def test_table2_values_follow_from_equation_6_3(wavelength, low, high):
    a, b = g652d_dispersion_limits(wavelength)
    assert a == pytest.approx(low, abs=0.05)
    assert b == pytest.approx(high, abs=0.05)


def test_bounds_are_continuous_at_1460():
    below = g652d_dispersion_limits(1460.0)
    above = g652d_dispersion_limits(1460.000001)
    assert below == pytest.approx((8.625, 12.472), abs=0.001)
    assert above == pytest.approx(below, abs=0.001)


@pytest.mark.parametrize("wavelength", [1300.0, 1324.0])
def test_bounds_are_continuous_at_zero_dispersion_limits(wavelength):
    below = g652d_dispersion_limits(wavelength - 1e-7)
    above = g652d_dispersion_limits(wavelength + 1e-7)
    assert above == pytest.approx(below, abs=1e-5)


def test_bounds_are_ordered_over_the_band():
    for wavelength in np.arange(1260, 1625.5, 1.0):
        low, high = g652d_dispersion_limits(float(wavelength))
        assert low < high or wavelength == pytest.approx(1312, abs=12)


def test_zero_dispersion_is_inside_the_band_of_bounds():
    low, high = g652d_dispersion_limits(1312.0)
    assert low < 0 < high


@pytest.mark.parametrize("wavelength", [1259.9, 1625.1])
def test_out_of_range_is_refused(wavelength):
    with pytest.raises(ValueError, match="outside"):
        g652d_preset(wavelength)


def test_attenuation_limits_from_table2():
    assert g652d_attenuation_limit(1550) == 0.30
    assert g652d_attenuation_limit(1310) == 0.40
    assert g652d_attenuation_limit(1625) == 0.40
    assert g652d_attenuation_limit(1260) == pytest.approx(0.47)


def test_sellmeier_derivative_is_consistent():
    h = 1e-3
    numeric = (
        sellmeier_dispersion(1550 + h, 1312, 0.08) - sellmeier_dispersion(1550 - h, 1312, 0.08)
    ) / (2 * h)
    assert sellmeier_slope(1550, 1312, 0.08) == pytest.approx(numeric, rel=1e-6)
    assert sellmeier_dispersion(1312, 1312, 0.08) == 0
    assert sellmeier_slope(1312, 1312, 0.08) == pytest.approx(0.08)


def test_representative_curve_matches_table_i1_and_stays_in_limits():
    lambda0, s0 = fit_sellmeier_to_typical()
    assert 1300 <= lambda0 <= 1324 and 0.073 <= s0 <= 0.092
    preset = g652d_preset(1550)
    assert preset.dispersion_ps_per_nm_km == pytest.approx(17.0)
    assert preset.dispersion_slope_ps_per_nm2_km == pytest.approx(0.056)
    for wavelength in np.arange(1260, 1625.5, 5.0):
        low, high = g652d_dispersion_limits(float(wavelength))
        d = g652d_preset(float(wavelength)).dispersion_ps_per_nm_km
        assert low - 1e-9 <= d <= high + 1e-9


def test_typical_attenuation_exceeding_a_limit_is_reported_not_hidden():
    assert typical_attenuation(1310) == 0.5
    assert not within_g652d_limits(g652d_preset(1310))["attenuation"]
    assert within_g652d_limits(g652d_preset(1550))["attenuation"]


@pytest.mark.parametrize("wavelength", [1310.0, 1550.0, 1600.0])
def test_limit_presets_sit_on_boundaries(wavelength):
    low = g652d_preset(wavelength, "limit-low")
    high = g652d_preset(wavelength, "limit-high")
    assert low.dispersion_ps_per_nm_km == pytest.approx(g652d_dispersion_limits(wavelength)[0])
    assert high.dispersion_ps_per_nm_km == pytest.approx(g652d_dispersion_limits(wavelength)[1])
    assert low.dispersion_source is ValueSource.SPECIFICATION_LIMIT


def test_measured_values_override_and_change_provenance_only_where_measured():
    updated = apply_measurements(g652d_preset(1550), "Southampton log 12", 0.21)
    assert updated.attenuation_db_per_km == 0.21
    assert updated.attenuation_source is ValueSource.MEASURED
    assert updated.dispersion_source is ValueSource.REPRESENTATIVE
    assert "Southampton log 12" in updated.reference


def test_measuring_d_does_not_relabel_the_slope():
    base = g652d_preset(1550)
    updated = apply_measurements(base, "log", dispersion_ps_per_nm_km=16.4)
    assert updated.dispersion_source is ValueSource.MEASURED
    assert updated.dispersion_slope_source is ValueSource.REPRESENTATIVE
    assert updated.dispersion_slope_ps_per_nm2_km == base.dispersion_slope_ps_per_nm2_km
    assert updated.to_metadata()["dispersion_slope_source"] == "representative-simulation-value"


def test_a_measured_slope_is_tagged_measured_and_only_the_slope():
    updated = apply_measurements(g652d_preset(1550), "log", dispersion_slope_ps_per_nm2_km=0.058)
    assert updated.dispersion_slope_ps_per_nm2_km == 0.058
    assert updated.dispersion_slope_source is ValueSource.MEASURED
    assert updated.dispersion_source is ValueSource.REPRESENTATIVE
    assert updated.attenuation_source is ValueSource.REPRESENTATIVE


def test_every_preset_tags_its_slope():
    assert g652d_preset(1550).dispersion_slope_source is ValueSource.REPRESENTATIVE
    assert g652d_preset(1550, "limit-low").dispersion_slope_source is (
        ValueSource.SPECIFICATION_LIMIT
    )
    fiber = custom_fiber("x", 1550, 0.2, 17.0, 0.056, ValueSource.MANUFACTURER, "sheet")
    assert fiber.to_metadata()["dispersion_slope_source"] == "manufacturer-data"


def test_other_fiber_types_are_not_forced_onto_g652d():
    fiber = custom_fiber("G.655 example", 1550, 0.22, 4.5, 0.05, ValueSource.MANUFACTURER, "sheet")
    assert fiber.fiber_type == "G.655 example"
    assert fiber.to_metadata()["dispersion_source"] == "manufacturer-data"


def test_metadata_is_complete_with_units():
    record = g652d_preset(1550).to_metadata()
    for key in ("fiber_type", "wavelength_nm", "assumptions", "reference", "units"):
        assert record[key]
    assert "08/2024" in record["reference"]
    assert record["units"]["dispersion"] == "ps/(nm km)"


def test_unknown_variant_rejected():
    with pytest.raises(ValueError, match="variant"):
        g652d_preset(1550, "typical")
