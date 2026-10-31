"""Gate N2a: closing the N1 minors with negative tests. Own literal numbers, nothing is scored.

Each guard of `resolve_profile` and `transmit_profile` that the third N1 review found without a
test has one here, and each new guard (a boolean instead of a text match, a scenario never
overrides a table, a scenario D states its wavelength, a measurement wavelength inside its own
range, the base label kept, the extreme-loss refusal) has a case that fails without it.
"""

import numpy as np
import pytest

from nanf_profile_helpers import known, make_profile, unknown
from opticps.optical_channel.fiber import (
    FiberProfileError,
    OutOfValidityRangeError,
    ParameterProvenance,
    PrecedenceDeclaration,
    ProvenanceCategory,
    SensitivityScenario,
    WavelengthTable,
    is_real_citation,
    load_fiber_config,
    resolve_profile,
)
from opticps.optical_channel.link import (
    LinkConfig,
    PowerProtocol,
    transmit_profile,
)

WIDE = (1400.0, 1700.0)
S_UNIT = "ps/(nm^2 km)"
D_UNIT = "ps/(nm km)"


def d_table(values=(9.0, 11.0), knots=(1500.0, 1600.0), name="D(lambda)", citation=None):
    return WavelengthTable(
        name,
        knots,
        values,
        D_UNIT,
        ParameterProvenance(ProvenanceCategory.MEASURED, citation or "Lab notebook 7, 2024-03-02"),
    )


def declaration(winner, citation="Owner decision 2026-10-31 (unit test)"):
    return PrecedenceDeclaration(
        winner, ParameterProvenance(ProvenanceCategory.USER_ASSUMED, citation)
    )


def known_s(value):
    return known(value, S_UNIT, measurement_wavelength_nm=1550.0, validity_range_nm=WIDE)


def table_profile(table, s=None, **over):
    """D unknown as a scalar (the table gives D), S as given (None means unknown)."""
    return make_profile(
        dispersion_table=table,
        dispersion_ps_per_nm_km=unknown(D_UNIT),
        dispersion_slope_ps_per_nm2_km=unknown(S_UNIT) if s is None else known_s(s),
        **over,
    )


def scalar_d_with_table(table, **over):
    """A known D of 10 stated at 1550 nm, valid over 1400 to 1700 nm, beside a D table."""
    return make_profile(
        dispersion_table=table,
        dispersion_ps_per_nm_km=known(
            10.0, D_UNIT, measurement_wavelength_nm=1550.0, validity_range_nm=WIDE
        ),
        **over,
    )


# --- table against scalar: the agreement tolerance (relative 1e-6) -------------------------------


@pytest.mark.parametrize(("table_d", "agrees"), [(10.000009, True), (10.00002, False)])
def test_the_scalar_and_the_table_agree_to_a_relative_one_part_in_a_million(table_d, agrees):
    # table midpoint at 1550 nm is table_d; scalar D is 10 (relative gap 9e-7 or 2e-6)
    table = d_table(values=(table_d - 1.0, table_d + 1.0))
    profile = scalar_d_with_table(table)
    if agrees:
        assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == pytest.approx(table_d)
    else:
        with pytest.raises(FiberProfileError, match="declares no winner"):
            resolve_profile(profile, 1550.0)


def test_the_scalar_is_compared_after_the_slope_has_placed_it():
    # D 10 at 1550 and S 0.06 place D at 10.06 at 1551 nm; the table (7 to 13 over 1500 to 1600)
    # says 10.06 there. The raw 10 would disagree with it by 6e-3; the placed value agrees.
    table = d_table(values=(7.0, 13.0))
    profile = scalar_d_with_table(table, dispersion_slope_ps_per_nm2_km=known_s(0.06))
    resolved = resolve_profile(profile, 1551.0)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(10.06)
    # an S that places D away from the table is refused as a table conflict at the same point
    off = scalar_d_with_table(table, dispersion_slope_ps_per_nm2_km=known_s(0.07))
    with pytest.raises(FiberProfileError):
        resolve_profile(off, 1551.0)


def test_a_scalar_outside_its_own_range_cannot_conflict_with_the_table():
    # scalar D 10 valid 1540 to 1560 only; table says 2.0 at 1550 and 3.8 at 1590
    table = d_table(values=(1.0, 3.0))
    profile = make_profile(
        dispersion_table=table,
        dispersion_ps_per_nm_km=known(
            10.0, D_UNIT, measurement_wavelength_nm=1550.0, validity_range_nm=(1540.0, 1560.0)
        ),
    )
    with pytest.raises(FiberProfileError, match="declares no winner"):
        resolve_profile(profile, 1550.0)  # inside the scalar's range: the conflict is real
    resolved = resolve_profile(profile, 1590.0)  # outside it: only the table speaks
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(2.8)
    assert "dispersion_ps_per_nm_km" not in resolved.extrapolated


# --- slope against the table: tolerance 1e-3 plus 10% of the table slope --------------------------


@pytest.mark.parametrize(("s", "accepted"), [(0.0009, True), (0.0011, False)])
def test_the_absolute_slope_tolerance_is_one_thousandth(s, accepted):
    flat = d_table(values=(10.0, 10.0))  # table slope 0
    profile = table_profile(flat, s)
    if accepted:
        assert resolve_profile(profile, 1550.0).dispersion_slope_ps_per_nm2_km == s
    else:
        with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
            resolve_profile(profile, 1550.0)


@pytest.mark.parametrize(("s", "accepted"), [(0.54, True), (0.46, True), (0.56, False)])
def test_the_relative_slope_tolerance_is_ten_percent_of_the_table_slope(s, accepted):
    steep = d_table(values=(0.0, 50.0))  # table slope 0.5, tolerance 0.001 + 0.05
    profile = table_profile(steep, s)
    if accepted:
        assert resolve_profile(profile, 1550.0).dispersion_slope_ps_per_nm2_km == s
    else:
        with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
            resolve_profile(profile, 1550.0)


def test_a_missing_slope_or_a_missing_table_skips_the_slope_check():
    table = d_table()
    no_s = resolve_profile(table_profile(table), 1550.0)
    assert no_s.dispersion_slope_ps_per_nm2_km is None
    assert no_s.to_record()["slope_omitted_second_order_only"] is True
    no_table = resolve_profile(make_profile(dispersion_slope_ps_per_nm2_km=known_s(0.06)), 1550.0)
    assert no_table.dispersion_slope_ps_per_nm2_km == 0.06


def test_the_local_slope_of_a_table_is_the_segment_slope_everywhere():
    table = d_table(values=(0.0, 1.0, 4.0), knots=(1500.0, 1550.0, 1600.0))  # 0.02, then 0.06
    for wavelength, expected in (
        (1400.0, 0.02),  # left of the first knot: the first segment
        (1500.0, 0.02),
        (1549.9, 0.02),
        (1550.0, 0.06),  # at a knot: the segment to the right
        (1580.0, 0.06),
        (1600.0, 0.06),
        (1700.0, 0.06),  # right of the last knot: the last segment
    ):
        assert table.slope_at(wavelength) == pytest.approx(expected, abs=1e-12)
    # and through the resolver under a requested extrapolation: S 0.02 fits at 1450, S 0.06 does not
    ok = table_profile(table, 0.02)
    resolve_profile(ok, 1450.0, allow_extrapolation=True)
    with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
        resolve_profile(table_profile(table, 0.06), 1450.0, allow_extrapolation=True)


# --- precedence declarations ----------------------------------------------------------------------


def test_a_precedence_declaration_needs_a_stated_provenance_and_a_real_citation():
    with pytest.raises(FiberProfileError, match="stated provenance"):
        PrecedenceDeclaration(
            "table", ParameterProvenance(ProvenanceCategory.UNKNOWN, "Owner decision, unit test")
        )
    for placeholder in ("none", "n/a", "see the paper", "tbd tbd"):
        with pytest.raises(FiberProfileError, match="real citation"):
            declaration("table", citation=placeholder)
    assert declaration("scalar").winner == "scalar"


# --- item 1: a boolean, not a text match ----------------------------------------------------------


@pytest.mark.parametrize("winner", ["scalar", "table"])
def test_a_phrase_in_a_name_or_a_citation_does_not_switch_the_slope_check_off(winner):
    phrase = "declared over table v2"
    # table D 10 at 1550 agrees with scalar D 10; table slope 0.06; known S 0.5 is far off
    table = d_table(values=(7.0, 13.0), name=phrase, citation=f"Lab notebook, {phrase}")
    profile = scalar_d_with_table(
        table,
        dispersion_slope_ps_per_nm2_km=known_s(0.5),
        precedence={
            "dispersion_slope_ps_per_nm2_km": declaration(winner, f"Owner, {phrase}"),
            "dispersion_ps_per_nm_km": declaration("table", f"Owner, {phrase}"),
        },
    )
    resolved = resolve_profile(profile, 1550.0)
    if winner == "scalar":
        assert resolved.dispersion_slope_ps_per_nm2_km == 0.5  # declared winner, by declaration
        assert "declared over table" in resolved.sources["dispersion_slope_ps_per_nm2_km"]
    else:
        assert resolved.dispersion_slope_ps_per_nm2_km == pytest.approx(0.06)
    # the same profile with no slope declaration is refused whatever the names say
    undeclared = scalar_d_with_table(
        table,
        dispersion_slope_ps_per_nm2_km=known_s(0.5),
        precedence={"dispersion_ps_per_nm_km": declaration("table", f"Owner, {phrase}")},
    )
    with pytest.raises(FiberProfileError, match="declares no winner"):
        resolve_profile(undeclared, 1550.0)


def test_the_slope_check_is_skipped_only_when_the_scalar_d_was_declared_over_the_table():
    table = d_table(values=(7.0, 13.0))
    declared = scalar_d_with_table(
        table,
        dispersion_slope_ps_per_nm2_km=known_s(0.5),
        precedence={"dispersion_ps_per_nm_km": declaration("scalar")},
    )
    # D 10 stated at 1550 and the table agree at 1550: nothing was declared over anything, so the
    # slope is still checked and the far S is refused
    with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
        resolve_profile(declared, 1550.0)
    # at 1590 the placed D (10 + 0.5 x 40 = 30) conflicts with the table (12.4) and is declared
    # the winner; the table slope then plays no part and a known S stands
    resolved = resolve_profile(declared, 1590.0)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(30.0)
    assert "declared over table" in resolved.sources["dispersion_ps_per_nm_km"]


# --- item 2: a scenario S never overrides a table, under any declaration --------------------------


@pytest.mark.parametrize("winner", ["scalar", "table"])
def test_a_scenario_slope_cannot_override_a_d_table_under_a_slope_declaration(winner):
    profile = table_profile(
        d_table(),  # table slope 0.02
        precedence={"dispersion_slope_ps_per_nm2_km": declaration(winner)},
    )
    scenario = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.06})
    with pytest.raises(FiberProfileError, match="a scenario cannot override a table"):
        resolve_profile(profile, 1550.0, scenario=scenario)
    # a scenario slope that agrees with the table is fine
    near = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.0205})
    assert resolve_profile(profile, 1550.0, scenario=near).dispersion_slope_ps_per_nm2_km == 0.0205


@pytest.mark.parametrize("winner", ["scalar", "table"])
def test_a_scenario_slope_cannot_move_a_scalar_d_away_from_the_table_under_a_d_declaration(winner):
    # D 10 at 1550 and the table (7 to 13) agree at 1550. A scenario S of 0.5 would put D at 30
    # at 1590 against the table's 12.4: the declaration cannot let a scenario win.
    profile = scalar_d_with_table(
        d_table(values=(7.0, 13.0)),
        dispersion_slope_ps_per_nm2_km=unknown(S_UNIT),
        precedence={"dispersion_ps_per_nm_km": declaration(winner)},
    )
    scenario = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.5})
    with pytest.raises(FiberProfileError, match="a scenario cannot override a table"):
        resolve_profile(profile, 1590.0, scenario=scenario)
    # a scenario slope equal to the table's own slope changes nothing and is accepted
    same = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.06})
    resolved = resolve_profile(profile, 1590.0, scenario=same)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(12.4)
    assert resolved.to_record()["not_a_benchmark_result"] is True


def test_a_scenario_slope_is_refused_even_when_the_declared_scalar_already_beat_the_table():
    # the scalar D (10) and the table (2.0 at 1550) disagree and the profile declares the scalar the
    # winner. A scenario S that agrees with the table's own slope would only place that D, yet the
    # rule is literal: a scenario S never overrides a table, under any declaration.
    profile = scalar_d_with_table(
        d_table(values=(1.0, 3.0)),
        dispersion_slope_ps_per_nm2_km=unknown(S_UNIT),
        precedence={"dispersion_ps_per_nm_km": declaration("scalar")},
    )
    scenario = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.02})
    with pytest.raises(FiberProfileError, match="a scenario cannot override a table"):
        resolve_profile(profile, 1550.0, scenario=scenario)
    # without a scenario S the declaration stands as before
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == pytest.approx(10.0)


# --- item 3: a scenario D states its wavelength, or S is refused ---------------------------------


def altuna_unknowns(**extra):
    return {
        "attenuation_db_per_km": 0.0,
        "connector_loss_db": 0.0,
        "pigtail_loss_db": 0.0,
        "splice_loss_db": 0.0,
        "dispersion_ps_per_nm_km": 10.0,
        **extra,
    }


def test_a_scenario_d_with_a_slope_and_no_wavelength_is_refused_for_every_slope_source():
    altuna = load_fiber_config("configs/fibers/NANF-ALTUNA-2024-3P1KM.yaml")
    bare = SensitivityScenario(
        "d and s", altuna_unknowns(dispersion_slope_ps_per_nm2_km=0.06), "no D wavelength"
    )
    for wavelength in (1510.0, 1550.0, 1590.0):
        with pytest.raises(OutOfValidityRangeError, match="scenario D states no wavelength"):
            resolve_profile(altuna, wavelength, scenario=bare)
    # a known S on a profile whose D is a scenario value is refused the same way
    from dataclasses import replace

    with_known_s = replace(altuna, dispersion_slope_ps_per_nm2_km=known_s(0.06))
    d_only = SensitivityScenario("d", altuna_unknowns())
    with pytest.raises(OutOfValidityRangeError, match="scenario D states no wavelength"):
        resolve_profile(with_known_s, 1590.0, scenario=d_only)


def test_the_altuna_route_supplies_the_wavelength_and_d_moves_with_the_slope():
    altuna = load_fiber_config("configs/fibers/NANF-ALTUNA-2024-3P1KM.yaml")
    scenario = SensitivityScenario(
        "d and s with wavelength",
        altuna_unknowns(dispersion_slope_ps_per_nm2_km=0.06),
        dispersion_wavelength_nm=1550.0,
    )
    at_1550 = resolve_profile(altuna, 1550.0, scenario=scenario)
    assert at_1550.dispersion_ps_per_nm_km == 10.0
    assert at_1550.dispersion_anchor_nm == 1550.0
    at_1590 = resolve_profile(altuna, 1590.0, scenario=scenario)
    assert at_1590.dispersion_ps_per_nm_km == pytest.approx(12.4, abs=1e-12)
    assert at_1590.dispersion_slope_ps_per_nm2_km == 0.06
    assert at_1590.to_record()["not_a_benchmark_result"] is True
    assert at_1590.sources["dispersion_ps_per_nm_km"] == "scenario: d and s with wavelength"


def test_a_scenario_d_without_any_slope_is_still_taken_as_d_and_a_wavelength_needs_a_d():
    altuna = load_fiber_config("configs/fibers/NANF-ALTUNA-2024-3P1KM.yaml")
    d_only = SensitivityScenario("d only", altuna_unknowns())
    for wavelength in (1510.0, 1590.0):
        resolved = resolve_profile(altuna, wavelength, scenario=d_only)
        assert resolved.dispersion_ps_per_nm_km == 10.0
        assert resolved.to_record()["slope_omitted_second_order_only"] is True
    with pytest.raises(FiberProfileError, match="states no D"):
        SensitivityScenario("x", {"connector_loss_db": 0.0}, dispersion_wavelength_nm=1550.0)
    for bad in (0.0, -1550.0, float("nan"), float("inf")):
        with pytest.raises(FiberProfileError):
            SensitivityScenario("x", {"dispersion_ps_per_nm_km": 1.0}, dispersion_wavelength_nm=bad)


# --- item 4: a measurement wavelength inside its own validity range ------------------------------


def test_a_measurement_wavelength_outside_its_own_validity_range_is_refused_at_construction():
    with pytest.raises(FiberProfileError, match="contradicts itself"):
        ParameterProvenance(
            ProvenanceCategory.USER_ASSUMED,
            "unit test",
            measurement_wavelength_nm=1550.0,
            validity_range_nm=(1400.0, 1500.0),
        )
    with pytest.raises(FiberProfileError, match="contradicts itself"):
        ParameterProvenance(
            ProvenanceCategory.USER_ASSUMED,
            "unit test",
            measurement_wavelength_nm=1550.0,
            validity_range_nm=(1550.1, 1600.0),
        )
    for rng in ((1400.0, 1550.0), (1550.0, 1600.0), (1550.0, 1550.0), (1500.0, 1600.0)):
        ParameterProvenance(
            ProvenanceCategory.USER_ASSUMED,
            "unit test",
            measurement_wavelength_nm=1550.0,
            validity_range_nm=rng,
        )
    # the shipped profiles all still load
    for name in (
        "HONG-2021-4P76KM",
        "ALTUNA-2024-3P1KM",
        "ALTUNA-2024-11P1KM",
        "WANG-2025-2P032KM",
    ):
        load_fiber_config(f"configs/fibers/NANF-{name}.yaml")


# --- item 5: the base label is kept by transmit_profile, or the call raises ----------------------


def quad_wave():
    return np.repeat(np.random.default_rng(2).choice([-1.0, -1 / 3, 1 / 3, 1.0], 128), 8)


def test_transmit_profile_keeps_a_base_label_in_the_link_record():
    base = LinkConfig(sensitivity_scenario="base-only")
    result = transmit_profile(
        quad_wave(), 64e9, make_profile(), 1550.0, np.random.default_rng(0), base=base
    )
    assert result.config.sensitivity_scenario == "base-only"
    assert result.link.fiber["sensitivity_scenario"] == "base-only"
    assert result.link.fiber["not_a_benchmark_result"] is True
    plain = transmit_profile(quad_wave(), 64e9, make_profile(), 1550.0, np.random.default_rng(0))
    assert plain.link.fiber["sensitivity_scenario"] is None
    assert "not_a_benchmark_result" not in plain.link.fiber


def test_transmit_profile_with_a_different_label_raises_and_the_same_label_is_kept():
    profile = make_profile(connector_loss_db=unknown("dB"))
    scenario = SensitivityScenario("connector guess", {"connector_loss_db": 0.5})
    with pytest.raises(FiberProfileError, match="never silently replaced"):
        transmit_profile(
            quad_wave(), 64e9, profile, 1550.0, np.random.default_rng(0),
            base=LinkConfig(sensitivity_scenario="other"), scenario=scenario,
        )  # fmt: skip
    same = transmit_profile(
        quad_wave(), 64e9, profile, 1550.0, np.random.default_rng(0),
        base=LinkConfig(sensitivity_scenario="connector guess"), scenario=scenario,
    )  # fmt: skip
    assert same.link.fiber["sensitivity_scenario"] == "connector guess"


# --- item 9: an extreme loss is the stated refusal, not a ZeroDivisionError ----------------------


@pytest.mark.parametrize("loss_db_per_km", [200.0, 2000.0, 2e5])
def test_an_extreme_loss_in_matched_power_is_the_stated_refusal(loss_db_per_km):
    absurd = make_profile(
        attenuation_db_per_km=known(
            loss_db_per_km, "dB/km", measurement_wavelength_nm=1550.0, validity_range_nm=WIDE
        )
    )  # 10000 dB at 2000 dB/km over 5 km: the transmission underflows to exactly 0.0
    with pytest.raises(ValueError, match="above the sanity limit"):
        transmit_profile(
            quad_wave(), 64e9, absurd, 1550.0, np.random.default_rng(0),
            protocol=PowerProtocol.MATCHED_RECEIVED, received_power_dbm=-5.0,
        )  # fmt: skip


def test_the_laser_cap_is_not_applied_to_the_fixed_launch_protocol():
    big = make_profile(
        attenuation_db_per_km=known(
            100.0, "dB/km", measurement_wavelength_nm=1550.0, validity_range_nm=WIDE
        )
    )
    result = transmit_profile(
        quad_wave(), 64e9, big, 1550.0, np.random.default_rng(0),
        base=LinkConfig(laser_power_w=5.0),
    )  # fmt: skip
    assert result.config.laser_power_w == 5.0
    assert result.protocol is PowerProtocol.FIXED_LAUNCH


# --- item 10: the citation floor, stated truthfully (not chased) ----------------------------------


def test_the_citation_check_is_a_form_floor_and_admits_short_nonsense():
    # What it refuses: too short, fewer than 4 distinct characters, or only placeholder words.
    for refused in ("abcabc", "aaabbb", "12345678", "xxxxxxxx", "reference data", "abcd5", "none"):
        assert not is_real_citation(refused), refused
    assert is_real_citation("abcdabcd")  # 4 distinct characters is the floor
    # What it admits, and is documented to admit: it cannot tell a real place from a fake one.
    for admitted in ("asdfgh", "abc123", "Table 2", "to_be_determined"):
        assert is_real_citation(admitted), admitted
