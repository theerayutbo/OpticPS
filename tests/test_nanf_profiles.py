"""Gate N1: fiber profiles, provenance categories, strict loading, no inherited G.652.D defaults."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from nanf_profile_helpers import OFF, known, make_profile, unknown
from opticps.optical_channel.fiber import (
    UNSUPPORTED_EFFECTS,
    ContextMeasurement,
    FiberParameters,
    FiberProfile,
    FiberProfileError,
    MissingFiberPropertyError,
    OutOfValidityRangeError,
    ParameterProvenance,
    ProfileValue,
    ProvenanceCategory,
    SensitivityScenario,
    UnsupportedEffectError,
    WavelengthTable,
    g652d_preset,
    load_fiber_config,
    resolve_profile,
)

FIBERS = Path("configs/fibers")
CATEGORIES = (
    "measured",
    "published-experimental",
    "published-numerical-assumption",
    "derived",
    "representative-literature",
    "user-assumed",
    "fitted-training-only",
    "unknown",
)
G652D_NUMBERS = (0.2, 17.0, 0.056, 15.95, 0.275, 0.35, 0.4)


def load(name: str):
    return load_fiber_config(FIBERS / f"{name}.yaml")


def test_provenance_categories_are_exactly_the_eight():
    assert tuple(c.value for c in ProvenanceCategory) == CATEGORIES


def test_value_is_null_if_and_only_if_unknown():
    with pytest.raises(FiberProfileError, match="null if and only if"):
        ProfileValue(1.0, "km", ParameterProvenance(ProvenanceCategory.UNKNOWN, "none"))
    with pytest.raises(FiberProfileError, match="null if and only if"):
        ProfileValue(None, "km", ParameterProvenance(ProvenanceCategory.MEASURED, "unit test"))
    with pytest.raises(FiberProfileError):
        ProfileValue(
            float("nan"), "km", ParameterProvenance(ProvenanceCategory.MEASURED, "unit test")
        )


def test_a_known_value_needs_an_exact_citation_and_valid_fields():
    with pytest.raises(FiberProfileError, match="citation"):
        ParameterProvenance(ProvenanceCategory.MEASURED, "  ")
    with pytest.raises(ValueError):
        ParameterProvenance("invented-category", "x")
    with pytest.raises(FiberProfileError):
        ParameterProvenance(ProvenanceCategory.MEASURED, "unit test", uncertainty=-0.1)
    with pytest.raises(FiberProfileError):
        ParameterProvenance(
            ProvenanceCategory.MEASURED, "unit test", validity_range_nm=(1600, 1500)
        )


def test_profile_rejects_wrong_units_and_unphysical_values():
    with pytest.raises(FiberProfileError, match="length_km"):
        make_profile(length_km=known(5.0, "m"))
    with pytest.raises(FiberProfileError, match="physical range"):
        make_profile(attenuation_db_per_km=known(-0.1, "dB/km"))
    with pytest.raises(FiberProfileError, match="physical range"):
        make_profile(group_index=known(0.9, "1"))
    with pytest.raises(FiberProfileError, match="effects"):
        make_profile(effects={"kerr": "off"})


def test_complete_profile_resolves_and_records_sources():
    resolved = resolve_profile(make_profile(), 1550.0)
    assert resolved.attenuation_db_per_km == 0.5
    assert resolved.dispersion_ps_per_nm_km == 10.0
    assert resolved.dispersion_slope_ps_per_nm2_km is None  # omitted, not defaulted
    record = resolved.to_record()
    assert record["slope_omitted_second_order_only"] is True
    assert record["sources"]["attenuation_db_per_km"] == "user-assumed"
    assert record["sensitivity_scenario"] is None


@pytest.mark.parametrize(
    "field,unit",
    [
        ("attenuation_db_per_km", "dB/km"),
        ("dispersion_ps_per_nm_km", "ps/(nm km)"),
        ("connector_loss_db", "dB"),
        ("pigtail_loss_db", "dB"),
        ("splice_loss_db", "dB"),
        ("length_km", "km"),
    ],
)
def test_an_unknown_required_value_raises_and_never_takes_a_g652d_default(field, unit):
    profile = make_profile(**{field: unknown(unit)})
    with pytest.raises(MissingFiberPropertyError, match=field) as err:
        resolve_profile(profile, 1550.0)
    assert "never" in str(err.value)


def test_hong_profile_has_unknown_loss_and_does_not_resolve_without_a_scenario():
    hong = load("NANF-HONG-2021-4P76KM")
    assert not hong.attenuation_db_per_km.known and not hong.connector_loss_db.known
    with pytest.raises(MissingFiberPropertyError) as err:
        resolve_profile(hong, 1550.0)
    assert "attenuation_db_per_km" in str(err.value) and "connector_loss_db" in str(err.value)


def test_labelled_scenario_fills_unknowns_only_and_is_recorded():
    hong = load("NANF-HONG-2021-4P76KM")
    scenario = SensitivityScenario(
        "zero distributed loss, sensitivity only",
        {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0},
    )
    resolved = resolve_profile(hong, 1550.0, scenario=scenario)
    assert resolved.attenuation_db_per_km == 0.0
    assert resolved.pigtail_loss_db == 2.0 and resolved.splice_loss_db == 0.1
    assert resolved.sources["attenuation_db_per_km"].startswith("scenario: zero distributed")
    assert resolved.to_record()["sensitivity_scenario"] == scenario.label
    # a scenario may not overwrite a value the profile knows
    with pytest.raises(FiberProfileError, match="override"):
        resolve_profile(hong, 1550.0, scenario=SensitivityScenario("x", {"pigtail_loss_db": 0.0}))
    with pytest.raises(FiberProfileError):
        SensitivityScenario("", {"attenuation_db_per_km": 0.0})
    with pytest.raises(FiberProfileError, match="not allowed"):
        SensitivityScenario("x", {"laser_power_w": 1.0})


def test_hong_values_and_tags():
    hong = load("NANF-HONG-2021-4P76KM")
    assert isinstance(hong, FiberProfile)
    d = hong.dispersion_ps_per_nm_km
    assert (
        d.value == 2.04
        and d.provenance.category is ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION
    )
    assert hong.group_index.value == 1.003
    assert hong.length_km.value == 4.76
    assert hong.pigtail_loss_db.value == 2.0
    assert hong.pigtail_loss_db.provenance.category is ProvenanceCategory.PUBLISHED_EXPERIMENTAL
    assert not hong.attenuation_db_per_km.known and not hong.gamma_per_w_km.known
    assert "N2" in hong.attenuation_db_per_km.provenance.note
    env = hong.link_loss_envelope
    assert (env.low_db, env.high_db) == (6.45, 8.33) and env.band_nm == (1460.0, 1640.0)
    assert "Not assigned to 1550" in env.note
    assert all(v == "off" for v in hong.effects.values())
    assert set(hong.geometry) >= {"core_diameter_um_piece_1", "membrane_thickness_um_piece_2"}


def test_envelope_is_informational_and_never_enters_a_resolved_loss():
    hong = load("NANF-HONG-2021-4P76KM")
    scenario = SensitivityScenario("s", {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0})
    resolved = resolve_profile(hong, 1550.0, scenario=scenario)
    assert resolved.total_loss_db == pytest.approx(2.1)  # pigtail + splice only
    assert not any(v in (6.45, 8.33) for v in resolved.to_record().values())


@pytest.mark.parametrize(
    "name,length,wavelength_stated",
    [("NANF-ALTUNA-2024-3P1KM", 3.1, 1480.0), ("NANF-ALTUNA-2024-11P1KM", 11.1, 1480.0)],
)
def test_altuna_pof_transmission_is_kept_in_its_context_only(name, length, wavelength_stated):
    profile = load(name)
    (meas,) = profile.measurements
    assert isinstance(meas, ContextMeasurement)
    assert meas.wavelength_nm == wavelength_stated and "not a fibre attenuation" in meas.context
    assert meas.provenance.category is ProvenanceCategory.USER_ASSUMED
    assert "not read from paper" in meas.provenance.note
    assert profile.length_km.value == length
    assert profile.length_km.provenance.category is ProvenanceCategory.USER_ASSUMED
    for field in (
        "attenuation_db_per_km",
        "dispersion_ps_per_nm_km",
        "dispersion_slope_ps_per_nm2_km",
    ):
        assert not getattr(profile, field).known
    with pytest.raises(MissingFiberPropertyError):
        resolve_profile(profile, 1550.0)
    assert load("NANF-ALTUNA-2024-3P1KM").measurements[0].value == 0.372
    assert load("NANF-ALTUNA-2024-11P1KM").measurements[0].value == 0.036


def test_wang_values_are_user_assumed_gamma_stored_and_never_active():
    wang = load("NANF-WANG-2025-2P032KM")
    assert wang.dispersion_ps_per_nm_km.value == 4.42 and wang.gamma_per_w_km.value == 0.007
    assert wang.length_km.value == 2.032
    for pv in (wang.dispersion_ps_per_nm_km, wang.gamma_per_w_km, wang.length_km):
        assert pv.provenance.category is ProvenanceCategory.USER_ASSUMED
        assert "not read from paper" in pv.provenance.note
    assert "No coherent workflow" in wang.notes
    assert wang.profile_id != load("NANF-HONG-2021-4P76KM").profile_id
    scenario = SensitivityScenario(
        "s",
        {
            "attenuation_db_per_km": 0.0,
            "connector_loss_db": 0.0,
            "pigtail_loss_db": 0.0,
            "splice_loss_db": 0.0,
        },
    )
    resolved = resolve_profile(wang, 1550.0, scenario=scenario)
    assert resolved.gamma_per_w_km == 0.007
    assert "stored_not_active" in " ".join(resolved.to_record())


def test_no_secondary_profile_mentions_a_shared_or_separate_spool_claim():
    for name in ("NANF-HONG-2021-4P76KM", "NANF-ALTUNA-2024-3P1KM", "NANF-WANG-2025-2P032KM"):
        text = (FIBERS / f"{name}.yaml").read_text().lower()
        assert "no shared spool" not in text and "different spool" not in text
        assert "separate sample" not in text and "separate spool" not in text
    wang = (FIBERS / "NANF-WANG-2025-2P032KM.yaml").read_text().lower()
    assert "separate record; sample identity unknown" in wang
    doc = Path("docs/NANF_MODEL_VALIDITY.md").read_text().lower()
    assert "separate record; sample identity unknown" in doc and "separate sample" not in doc


def test_g652d_reference_file_keeps_the_existing_implementation():
    loaded = load("ITU-G652D-REFERENCE")
    assert isinstance(loaded, FiberParameters)
    assert loaded == g652d_preset(1550.0, "representative")
    assert "17" not in (FIBERS / "ITU-G652D-REFERENCE.yaml").read_text().replace("1550", "")


def test_nanf_files_hold_no_g652d_number_as_a_value():
    for name in (
        "NANF-HONG-2021-4P76KM",
        "NANF-ALTUNA-2024-3P1KM",
        "NANF-ALTUNA-2024-11P1KM",
        "NANF-WANG-2025-2P032KM",
    ):
        data = yaml.safe_load((FIBERS / f"{name}.yaml").read_text())
        numbers = [
            v["value"]
            for k, v in data.items()
            if isinstance(v, dict) and "value" in v and v["value"] is not None
        ]
        assert not set(numbers) & set(G652D_NUMBERS), name


def test_effects_on_raise_when_resolving():
    for effect in UNSUPPORTED_EFFECTS:
        profile = make_profile(effects={**OFF, effect: "on"})
        with pytest.raises(UnsupportedEffectError, match="not implemented"):
            resolve_profile(profile, 1550.0)
    assert issubclass(UnsupportedEffectError, NotImplementedError)


def test_table_knots_midpoints_and_strict_range():
    table = WavelengthTable(
        "loss",
        (1500.0, 1550.0, 1600.0),
        (0.30, 0.20, 0.40),
        "dB/km",
        ParameterProvenance(ProvenanceCategory.MEASURED, "unit test"),
    )
    for wl, v in zip(table.wavelengths_nm, table.values, strict=True):
        assert table.at(wl) == (v, False)
    assert table.at(1525.0) == (pytest.approx(0.25), False)
    assert table.at(1575.0)[0] == pytest.approx(0.30)
    with pytest.raises(OutOfValidityRangeError, match="no extrapolation"):
        table.at(1499.9)
    with pytest.raises(OutOfValidityRangeError):
        table.at(1630.0)
    value, extrapolated = table.at(1650.0, allow_extrapolation=True)
    assert extrapolated and value == pytest.approx(0.40 + (0.40 - 0.20) / 50 * 50)


def test_table_must_be_increasing_and_have_provenance():
    prov = ParameterProvenance(ProvenanceCategory.MEASURED, "unit test")
    with pytest.raises(FiberProfileError):
        WavelengthTable("x", (1550.0, 1550.0), (1.0, 2.0), "dB/km", prov)
    with pytest.raises(FiberProfileError):
        WavelengthTable("x", (1550.0,), (1.0,), "dB/km", prov)
    with pytest.raises(FiberProfileError):
        WavelengthTable(
            "x",
            (1.0, 2.0),
            (1.0, 2.0),
            "dB/km",
            ParameterProvenance(ProvenanceCategory.UNKNOWN, ""),
        )


def test_tables_replace_scalars_and_wavelength_outside_is_rejected():
    table = WavelengthTable(
        "D",
        (1540.0, 1560.0),
        (1.0, 3.0),
        "ps/(nm km)",
        ParameterProvenance(ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION, "unit test"),
    )
    profile = make_profile(dispersion_table=table, dispersion_ps_per_nm_km=unknown("ps/(nm km)"))
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == pytest.approx(2.0)
    assert resolve_profile(profile, 1540.0).dispersion_ps_per_nm_km == pytest.approx(1.0)
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(profile, 1630.0)
    far = resolve_profile(profile, 1630.0, allow_extrapolation=True)
    assert far.extrapolated == ("dispersion_ps_per_nm_km",)
    assert far.dispersion_ps_per_nm_km == pytest.approx(1.0 + 0.1 * 90)


def test_scalar_value_is_valid_only_where_it_is_stated():
    hong = load("NANF-HONG-2021-4P76KM")
    scenario = SensitivityScenario("s", {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0})
    with pytest.raises(OutOfValidityRangeError, match="dispersion_ps_per_nm_km"):
        resolve_profile(hong, 1630.0, scenario=scenario)
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(hong, 1550.5, scenario=scenario)
    extr = resolve_profile(hong, 1630.0, scenario=scenario, allow_extrapolation=True)
    assert "dispersion_ps_per_nm_km" in extr.extrapolated
    # D continued with the stated slope, not held at a G.652.D-like value
    assert extr.dispersion_ps_per_nm_km == pytest.approx(2.04 + 0.004 * 80)


def test_measured_wavelength_alone_restricts_a_value():
    profile = make_profile(
        attenuation_db_per_km=known(0.5, "dB/km", measurement_wavelength_nm=1550)
    )
    resolve_profile(profile, 1550.0)
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(profile, 1500.0)


def test_loader_is_strict(tmp_path):
    good = (FIBERS / "NANF-WANG-2025-2P032KM.yaml").read_text()

    def write(text):
        path = tmp_path / "p.yaml"
        path.write_text(text)
        return path

    with pytest.raises(FiberProfileError, match="duplicate key"):
        load_fiber_config(write(good + "\nprofile_id: other\n"))
    with pytest.raises(FiberProfileError, match="unknown keys"):
        load_fiber_config(write(good + "\nextra_field: 1\n"))
    with pytest.raises(FiberProfileError, match="missing keys"):
        load_fiber_config(write(good.replace("gamma_per_w_km:", "gamma_typo:", 1)))
    with pytest.raises(FiberProfileError, match="null if and only if"):
        load_fiber_config(write(good.replace("value: 4.42", "value: null", 1)))
    with pytest.raises(FiberProfileError):
        load_fiber_config(write(good.replace("category: user-assumed", "category: guessed", 1)))
    with pytest.raises(FiberProfileError, match="citation"):
        load_fiber_config(
            write(good.replace('citation: "Owner brief for Gate N1"', 'citation: ""'))
        )


def test_context_measurement_needs_wavelength_and_context():
    prov = ParameterProvenance(ProvenanceCategory.USER_ASSUMED, "x")
    with pytest.raises(FiberProfileError):
        ContextMeasurement("t", 0.4, "fraction", 1480.0, "  ", prov)
    with pytest.raises(FiberProfileError):
        ContextMeasurement("t", 0.4, "fraction", -1.0, "ctx", prov)


def test_profile_is_immutable():
    profile = make_profile()
    with pytest.raises(AttributeError):
        profile.profile_id = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        profile.effects["kerr"] = "on"  # type: ignore[index]
    assert replace(profile, profile_id="Y").profile_id == "Y"


# --- Gate N1 fix round: loader strictness ---------------------------------------------------------


def _table(unit, name="t", category="measured", citation="Lab notebook 7, 2024-03-02"):
    return WavelengthTable(
        name,
        (1540.0, 1560.0),
        (1.0, 2.0),
        unit,
        ParameterProvenance(ProvenanceCategory(category), citation),
    )


def test_table_units_are_enforced():
    assert make_profile(loss_table=_table("dB/km")).loss_table is not None
    assert make_profile(dispersion_table=_table("ps/(nm km)")).dispersion_table is not None
    for unit in ("dB/m", "ps/nm", "dB", "ps/(nm m)", ""):
        with pytest.raises(FiberProfileError, match="must be in dB/km"):
            make_profile(loss_table=_table(unit))
    with pytest.raises(FiberProfileError, match="must be in ps/\\(nm km\\)"):
        make_profile(dispersion_table=_table("dB/km"))  # a loss table used as a D table
    with pytest.raises(FiberProfileError, match="negative loss"):
        make_profile(
            loss_table=WavelengthTable(
                "t",
                (1540.0, 1560.0),
                (0.1, -0.2),
                "dB/km",
                ParameterProvenance(ProvenanceCategory.MEASURED, "Lab notebook 7"),
            )
        )


@pytest.mark.parametrize(
    "citation",
    ["none", "None", "NONE.", "n/a", "N/A", "na", "tbd", "TODO", "unknown", "-", "--", "?", "",
     "  ", "not available", "none given", "no citation", "see paper", "x", "12345", "null",
     "unspecified"],
)  # fmt: skip
@pytest.mark.parametrize("category", ["measured", "published-experimental",
                                      "published-numerical-assumption"])  # fmt: skip
def test_a_measured_or_published_value_needs_a_real_citation(category, citation):
    with pytest.raises(FiberProfileError, match="citation"):
        ParameterProvenance(ProvenanceCategory(category), citation)


@pytest.mark.parametrize(
    "citation",
    ["Hong et al. 2021, Sec. II", "DOI 10.1109/JLT.2021.3097278", "Lab notebook 7, p. 3"],
)
def test_a_real_citation_is_accepted(citation):
    for category in ("measured", "published-experimental", "published-numerical-assumption"):
        assert ParameterProvenance(ProvenanceCategory(category), citation).citation == citation


def test_the_yaml_loader_refuses_a_measured_value_cited_as_none(tmp_path):
    text = (FIBERS / "NANF-HONG-2021-4P76KM.yaml").read_text()
    assert load_fiber_config(FIBERS / "NANF-HONG-2021-4P76KM.yaml")
    bad = text.replace("category: published-numerical-assumption", "category: measured", 1)
    bad = bad.replace(
        'citation: "Hong et al. 2021, Sec. II, assumed D of the NANF at 1550 nm (5 km simulation)"',
        "citation: none",
        1,
    )
    assert bad != text
    path = tmp_path / "bad.yaml"
    path.write_text(bad)
    with pytest.raises(FiberProfileError, match="real citation"):
        load_fiber_config(path)


def test_the_yaml_loader_refuses_a_table_in_the_wrong_unit(tmp_path):
    text = (FIBERS / "NANF-HONG-2021-4P76KM.yaml").read_text()
    table = (
        "loss_table:\n  name: t\n  unit: dB/m\n  wavelengths_nm: [1540, 1560]\n  values: [0.1, 0.2]\n"
        "  provenance: {category: measured, citation: Lab notebook 7 page 3}\n"
    )
    path = tmp_path / "t.yaml"
    path.write_text(text + table)
    with pytest.raises(FiberProfileError, match="must be in dB/km"):
        load_fiber_config(path)
