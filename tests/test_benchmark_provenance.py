"""Stage 3A gate E0: provenance schema, strict catalog loader, plan pin, holdout guards, importer.

Everything here is offline and synthetic. No external dataset is read or needed. Lists of field
names, statuses and metrics are written out literally in the tests, on purpose: a test that
loops over the implementation's own constant cannot notice that the constant lost an entry.
"""

import dataclasses
import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.benchmarks import catalog, holdout, provenance
from opticps.benchmarks.catalog import load_source_config, parse_source, require_local_asset
from opticps.benchmarks.holdout import (
    Verdict,
    allowed_verdicts,
    require_frozen_criterion,
    require_reference_for_ber,
)
from opticps.benchmarks.provenance import (
    ASSET_FIELDS,
    SOURCE_FIELDS,
    AssetRecord,
    BenchmarkError,
    Checksum,
    ErrorCode,
    LicenseRecord,
    LicenseStatus,
    Md5State,
    ParameterValue,
    Permission,
    Provenance,
    SourceRecord,
    Split,
    assert_no_split_overlap,
    verify_local_asset,
)
from opticps.measurement.uxr_import import UxrImportError, read_bin, read_scope_file
from opticps.transmitter.mpam_config import ConfigError, load_mpam_config

CONFIGS = Path("configs/benchmarks")
TERIPHIC = CONFIGS / "teriphic_pd1_pam4.yaml"
RAN = CONFIGS / "ran_2025_g652d.yaml"
WIEGART = CONFIGS / "wiegart_2021_peak_pam4.yaml"
PLAN = Path("docs/benchmarks/FIT_HOLDOUT_PLAN.md")
REGISTER = Path("docs/benchmarks/SOURCE_REGISTER.md")
# Pinned for Revision 1 of the plan (2026-10-31, before any sample was read). The text of the
# previous version (commit 8900748) hashed to PREVIOUS_PLAN_SHA256. A deliberate amendment must
# change this line, the plan_sha256 in the TERIPHIC config and add a dated section.
PLAN_SHA256 = "42a578f5c3e9d28d1fad69800416faa2330510c37007a7c56c7bc940d42d358a"
PREVIOUS_PLAN_SHA256 = "6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a"
MD5_B2B = "d7bd6d48bc020a138f4f129bc2ba7312"
MD5_2KM = "d9e3c533394c53c3575491558ffc35b1"
MD5_10KM = "3d8774b068deaf50f37892b38953dfd6"

# Written out on purpose (see module docstring).
MEASURED_ASSET_FIELDS = (
    "sample_rate_hz", "baud_bd", "modulation_order", "wavelength_nm", "fibre_type",
    "fibre_length_km", "transmitter_type", "detector", "reference_sequence", "raw_format",
    "calibration",
)  # fmt: skip
MEASURED_SOURCE_ONLY_FIELDS = ("dispersion_ps_per_nm_km", "fec_threshold", "wavelength_band")
FREE_SOURCE_FIELDS = (
    "equalizer", "rate_definition", "ber_definition", "chirp_model_status", "constraint",
    "distribution_family", "noise_definition",
)  # fmt: skip
GOOD_VALUES = {
    "sample_rate_hz": (256e9, "Hz"),
    "baud_bd": (50e9, "Bd"),
    "modulation_order": (4, None),
    "wavelength_nm": (1271, "nm"),
    "fibre_type": ("G652.D", None),
    "fibre_length_km": (2, "km"),
    "transmitter_type": ("COTS laser", None),
    "detector": ("InP PD", None),
    "reference_sequence": ("PRBS", None),
    "raw_format": ("float32", None),
    "calibration": ("volts", None),
    "dispersion_ps_per_nm_km": (-3.99, "ps/(nm km)"),
    "fec_threshold": ("3.8e-3", None),
    "wavelength_band": ("O-band", None),
}


def raw(path: Path = TERIPHIC) -> dict:
    return yaml.safe_load(path.read_text())


def write(tmp_path: Path, document: dict, name: str = "c.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def known(value, how=Provenance.PUBLISHED_MEASUREMENT, unit=None):
    return ParameterValue(value, how, unit=unit, source_ref="test")


def good(field, how=Provenance.PUBLISHED_MEASUREMENT):
    value, unit = GOOD_VALUES[field]
    return known(value, how, unit)


def asset_parameters() -> dict:
    return {name: ParameterValue.unknown() for name in ASSET_FIELDS}


def make_asset(group="g/B2B", split=Split.CHARACTERISATION, name="a.bin", md5=None, **extra):
    checksum = extra.pop("checksum", Checksum(md5_supplied=md5))
    return AssetRecord(
        source_id="s",
        doi="10.1234/x",
        url="https://example.invalid/r",
        asset_version="v1",
        filename=name,
        checksum=checksum,
        size_bytes=extra.pop("size_bytes", 10),
        split=split,
        group=group,
        parameters=asset_parameters() | extra,
    )


def make_licence(**overrides):
    fields = {
        "scope": "data",
        "status": LicenseStatus.RECORD_LEVEL,
        "license_id": "CC-BY-4.0",
        "private_research_use": Permission.ALLOWED,
        "public_redistribution": Permission.ALLOWED_WITH_CONDITIONS,
        "derivatives": Permission.ALLOWED_WITH_CONDITIONS,
        "commercial_use": Permission.ALLOWED_WITH_CONDITIONS,
    }
    return LicenseRecord(**(fields | overrides))


def make_source(licence=None, **overrides):
    fields = {
        "source_id": "s",
        "kind": "dataset",
        "title": "t",
        "doi": "10.1234/x",
        "url": "https://example.invalid/r",
        "version": None,
        "retrieved": "2026-10-31",
        "licenses": (licence or make_licence(),),
    }
    return SourceRecord(**(fields | overrides))


def with_local_hash(asset: AssetRecord, path: Path) -> AssetRecord:
    return dataclasses.replace(
        asset, checksum=verify_local_asset(path, asset.checksum.md5_supplied)
    )


# ------------------------------------------------------------------ plan pin and revision
def test_plan_hash_is_pinned_in_test_and_config():
    digest = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert digest == PLAN_SHA256, (
        "FIT_HOLDOUT_PLAN.md changed: amend with a dated section and a new pin"
    )
    assert load_source_config(TERIPHIC).plan_sha256 == PLAN_SHA256
    assert PLAN_SHA256 != PREVIOUS_PLAN_SHA256


def test_plan_roles_match_config_splits():
    source = load_source_config(TERIPHIC)
    roles = {a.filename: a.split for a in source.assets}
    assert roles == {
        "50G_PAM4_PD1_B2B_Subassembly1.bin": Split.CHARACTERISATION,
        "50G_PAM4_PD1_2km_Subassembly1.bin": Split.VALIDATION,
        "50G_PAM4_PD1_10km_Subassembly1.bin": Split.LOCKED_TEST,
    }
    assert_no_split_overlap(source.assets)
    text = PLAN.read_text()
    for needle in (
        "2 km (first declared validation)",
        "10 km (locked test)",
        "Identifiability caveat",
    ):
        assert needle in text


def test_plan_revision_is_visible_and_truthful():
    text = " ".join(PLAN.read_text().split())
    assert "## Revision 1 (2026-10-31)" in text
    assert PREVIOUS_PLAN_SHA256 in text  # previous version recorded
    assert "no sample of any TERIPHIC capture has been read, decoded, plotted or summarised" in text
    assert "the files have only been hashed" in text
    # the superseded clauses stay visible, struck through, and are marked
    assert "~~If they were re-tuned between lengths" in text
    assert "~~Numeric pass/fail tolerances" in text
    assert text.count("Revision 1") >= 8
    # shared-sequence and lock wording (R.2, R.3), validation limit (R.5), named metrics (R.4)
    for needle in (
        "one repeating sequence may be used for all three",
        "inferred candidate",
        "pattern correlation, timing or clock recovery, sequence extraction",
        "covers **every** statistic",
        "2 km cannot by itself be VALIDATED",
        "Only the single 10 km evaluation",
        "`FAILED`",
        "`INCONCLUSIVE`",
        "M1 level spacing",
        "M2 amplitude histogram distance",
        "M3 quantile error",
        "M4 spectrum shape",
        "require_frozen_criterion",
        "committed before any 2 km statistic is computed",
        "commit SHA",
    ):
        if needle != "commit SHA":
            assert needle in text, needle


def test_plan_has_no_open_contradiction_between_header_and_section_3():
    text = PLAN.read_text()
    header = text.split("## 0.")[0]
    assert "Revision 1" in header and "required input file" in header
    assert "separate dated addendum with its own SHA-256 before any 2 km" in text  # struck text
    assert "~~Numeric pass/fail tolerances depend on the B2B noise floor" in text


# ------------------------------------------------------------------ configs
@pytest.mark.parametrize("path", [TERIPHIC, RAN, WIEGART])
def test_committed_configs_load_with_licence_state(path):
    source = load_source_config(path)
    assert source.licenses and source.retrieved == "2026-10-31"


def test_teriphic_unknowns_stay_none_with_unknown_provenance():
    source = load_source_config(TERIPHIC)
    for asset in source.assets:
        for field in (
            "wavelength_nm",
            "fibre_type",
            "reference_sequence",
            "raw_format",
            "calibration",
        ):
            parameter = asset.parameters[field]
            assert parameter.value is None and parameter.provenance is Provenance.UNKNOWN
        assert asset.missing_fields == (
            "wavelength_nm", "fibre_type", "reference_sequence", "raw_format", "calibration",
        )  # fmt: skip
        assert asset.checksum.md5_state is Md5State.SUPPLIED
        assert asset.checksum.sha256_local is None and asset.checksum.md5_local is None
        assert asset.parameters["sample_rate_hz"].provenance is Provenance.INFERRED
        assert asset.sample_rate_wording == "256 Gbaud sample rate"
    lengths = {a.group.split("/")[-1]: a.parameters["fibre_length_km"].value for a in source.assets}
    assert lengths == {"B2B": 0, "2km": 2, "10km": 10}
    supplied = {a.group.split("/")[-1]: a.checksum.md5_supplied for a in source.assets}
    assert supplied == {"B2B": MD5_B2B, "2km": MD5_2KM, "10km": MD5_10KM}


def test_teriphic_transmitter_wording_follows_the_record():
    # The record says "commercially available off-the-shelf (COTS) laser source"; it does not say CW.
    for asset in load_source_config(TERIPHIC).assets:
        transmitter = asset.parameters["transmitter_type"].value
        assert "COTS" in transmitter and "laser source" in transmitter
        assert "CW" not in transmitter and "continuous" not in transmitter.lower()
    assert "CW" not in TERIPHIC.read_text().replace("CC-BY", "")


def test_teriphic_licence_is_record_level_and_grants_what_the_record_says():
    source = load_source_config(TERIPHIC)
    data = source.license_for("data")
    assert data.status is LicenseStatus.RECORD_LEVEL and data.license_id == "CC-BY-4.0"
    assert data.read_how == "verified"
    source.require_public_redistribution("data")
    source.require_derivatives("data")


def test_article_and_data_licences_are_separate():
    ran = load_source_config(RAN)
    article, data = ran.license_for("article"), ran.license_for("data")
    assert article.status is LicenseStatus.RECORD_LEVEL
    assert article.license_id == "CC-BY-NC-ND-4.0"
    assert data.status is LicenseStatus.UNVERIFIED and data.license_id is None
    assert data.status.label == "LICENSE/REUSE TERMS UNVERIFIED"
    with pytest.raises(BenchmarkError) as error:
        ran.require_public_redistribution("data")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    wiegart = load_source_config(WIEGART)
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        wiegart.require_public_redistribution("article")
    with pytest.raises(BenchmarkError, match="no data licence"):
        wiegart.license_for("data")


def test_ran_uses_1271_not_the_1550_default():
    ran = load_source_config(RAN).parameters
    assert ran["wavelength_nm"].value == 1271 and ran["dispersion_ps_per_nm_km"].value < 0
    assert ran["rate_definition"].value is None and ran["ber_definition"].value is None
    assert ran["chirp_model_status"].value == "MODEL_GAP"
    assert ran["fibre_type"].value == "G652.D"  # as printed in the paper


def test_licence_status_names_say_what_was_read():
    assert {m.value for m in LicenseStatus} == {"RECORD_LEVEL", "UNVERIFIED", "RESTRICTED"}
    assert not hasattr(LicenseStatus, "VERIFIED")
    for status in ("status: VERIFIED",):
        assert all(status not in p.read_text() for p in (TERIPHIC, RAN, WIEGART))
    assert {m.value for m in provenance.ReadHow} == {
        "verified", "summary", "user-supplied", "unconfirmed",
    }  # fmt: skip


def test_benchmark_configs_cannot_change_an_experiment_id():
    # A benchmark config is not a transmit config: the loader that defines experiment_ids refuses it.
    for path in (TERIPHIC, RAN, WIEGART):
        with pytest.raises(ConfigError):
            load_mpam_config(path)
    outside = [
        p
        for p in Path("src/opticps").rglob("*.py")
        if "benchmarks" not in p.parts and "configs/benchmarks" in p.read_text()
    ]
    assert outside == []  # no existing module reads the benchmark configs


def test_error_codes_are_the_eight_standard_ones():
    assert {c.value for c in ErrorCode} == {
        "SOURCE_MISSING", "LICENSE_UNVERIFIED", "FORMAT_UNKNOWN", "REFERENCE_SEQUENCE_MISSING",
        "MODEL_GAP", "NOT_COMPARABLE", "LEAKAGE_DETECTED", "UNIDENTIFIABLE_PARAMETER",
    }  # fmt: skip


def test_no_network_code_in_the_package():
    forbidden = ("socket", "urllib", "http.client", "requests", "httpx", "ftplib", "aiohttp")
    for path in Path("src/opticps/benchmarks").glob("*.py"):
        text = path.read_text()
        for name in forbidden:
            assert f"import {name}" not in text and f"from {name}" not in text, (path, name)


# ------------------------------------------------------------------ register wording
def test_register_quotes_the_record_and_states_the_corrections():
    text = " ".join(REGISTER.read_text().split())
    for needle in (
        'commercially available off-the-shelf (COTS) laser source',
        'more than 70 GHz 3-dB bandwidth',
        'A low-pass filter with a 50 GHz 3-dB cut-off frequency was digitally applied',
        'The data sets are actually the samples extracted from the oscilloscope.',
        "0 NRZ",
        "hashed locally by orchestrator on owner-approved download, 2026-10-31",
        MD5_B2B, MD5_2KM, MD5_10KM,
        "b9c5968ae4cac4ea53b6bbda62c7255b3ecfa2ff530985c1e4ae0f4e55b9e0b2",
        "22fc7bb592681ed6135b5be28a28b1f124344924316b4333508823f7674266d3",
        "053bf8c9ba8df00063f5d686508833dc18685ec320d7e373b1877947e15b118b",
        "Licence conflict",
        "CC BY-NC-ND",
        "E1 will run `verify_local_asset`",
    ):  # fmt: skip
        assert needle in text, needle
    assert "`transmitter_type` omits CW" not in text
    assert "Revision 2; HTML page says v1" not in text  # discrepancy 1 was an artefact


# ------------------------------------------------------------------ parameter provenance
def test_value_without_provenance_raises():
    for bad in (None, "PUBLISHED_MEASUREMENT", 3):
        with pytest.raises(BenchmarkError, match="provenance"):
            ParameterValue(50e9, bad, source_ref="x")  # type: ignore[arg-type]


def test_unknown_cannot_become_a_value_or_the_reverse():
    with pytest.raises(BenchmarkError, match="UNKNOWN"):
        ParameterValue(1271, Provenance.UNKNOWN, source_ref="x")
    with pytest.raises(BenchmarkError, match="missing value"):
        ParameterValue(None, Provenance.PUBLISHED_MEASUREMENT)
    with pytest.raises(BenchmarkError, match="missing value"):
        ParameterValue(None, Provenance.SIMULATED)
    with pytest.raises(BenchmarkError, match="source_ref"):
        ParameterValue(1271, Provenance.PUBLISHED_MEASUREMENT)
    assert ParameterValue.unknown().value is None


@pytest.mark.parametrize("field", MEASURED_ASSET_FIELDS)
def test_simulated_value_is_refused_in_every_measured_asset_field(field):
    with pytest.raises(BenchmarkError) as error:
        make_asset(**{field: good(field, Provenance.SIMULATED)})
    assert error.value.code is ErrorCode.NOT_COMPARABLE


@pytest.mark.parametrize("field", MEASURED_ASSET_FIELDS[:0] + MEASURED_SOURCE_ONLY_FIELDS)
def test_simulated_value_is_refused_in_every_measured_source_field(field):
    with pytest.raises(BenchmarkError) as error:
        make_source(parameters={field: good(field, Provenance.SIMULATED)})
    assert error.value.code is ErrorCode.NOT_COMPARABLE


@pytest.mark.parametrize("field", FREE_SOURCE_FIELDS)
def test_simulated_value_may_describe_a_model_choice(field):
    source = make_source(parameters={field: known("a model choice", Provenance.SIMULATED)})
    assert source.parameters[field].provenance is Provenance.SIMULATED


def test_known_field_names_are_exactly_the_documented_ones():
    assert set(ASSET_FIELDS) == set(MEASURED_ASSET_FIELDS)
    assert set(SOURCE_FIELDS) == (
        set(MEASURED_ASSET_FIELDS) | set(MEASURED_SOURCE_ONLY_FIELDS) | set(FREE_SOURCE_FIELDS)
    )
    assert set(provenance.MEASURED_FIELDS) == (
        set(MEASURED_ASSET_FIELDS) | set(MEASURED_SOURCE_ONLY_FIELDS)
    )
    assert set(GOOD_VALUES) == set(provenance.MEASURED_FIELDS)


def test_an_inferred_value_stays_allowed_but_labelled():
    asset = make_asset(wavelength_nm=good("wavelength_nm", Provenance.INFERRED))
    assert asset.parameters["wavelength_nm"].provenance is Provenance.INFERRED


def test_asset_must_state_every_field_and_no_others():
    parameters = asset_parameters()
    del parameters["wavelength_nm"]
    with pytest.raises(BenchmarkError, match="wavelength_nm"):
        AssetRecord(
            "s", "10.1234/x", "https://e.invalid/x", "v", "a.bin", Checksum(), 1, Split.RESERVED,
            "g", parameters,
        )  # fmt: skip
    with pytest.raises(BenchmarkError, match="unknown parameter"):
        make_asset(laser_power_dbm=ParameterValue.unknown())
    with pytest.raises(BenchmarkError, match="no provenance record"):
        make_asset(wavelength_nm=1271)


# ------------------------------------------------------------------ per-field validation
BAD_VALUES = [
    ("baud_bd", float("nan"), "Bd", "finite"),
    ("baud_bd", float("inf"), "Bd", "finite"),
    ("baud_bd", -5, "Bd", "positive"),
    ("baud_bd", 0, "Bd", "positive"),
    ("baud_bd", "fast", "Bd", "number"),
    ("baud_bd", "", "Bd", "non-empty"),
    ("baud_bd", "  ", "Bd", "non-empty"),
    ("modulation_order", 3.7, None, "integer"),
    ("modulation_order", 4.0, None, "integer"),
    ("modulation_order", 3, None, "integer"),
    ("modulation_order", 32, None, "integer"),
    ("modulation_order", "4", None, "integer"),
    ("fibre_length_km", -2, "km", "negative"),
    ("fibre_length_km", float("-inf"), "km", "finite"),
    ("wavelength_nm", "null", "nm", "not a known value"),
    ("wavelength_nm", 0, "nm", "positive"),
    ("wavelength_nm", -1271, "nm", "positive"),
    ("sample_rate_hz", 256, "GHz", "inconsistent"),
    ("sample_rate_hz", 256e9, "GHz", "inconsistent"),
    ("sample_rate_hz", 256e9, "Hz and more", "inconsistent"),
    ("sample_rate_hz", 256e9, None, "inconsistent"),
    ("sample_rate_hz", 0, "Hz", "positive"),
    ("baud_bd", 50e9, "GBd", "inconsistent"),
    ("wavelength_nm", 1271, "um", "inconsistent"),
    ("fibre_length_km", 2, "m", "inconsistent"),
    ("dispersion_ps_per_nm_km", float("nan"), "ps/(nm km)", "finite"),
    ("dispersion_ps_per_nm_km", -3.99, "ps/nm", "inconsistent"),
    ("dispersion_ps_per_nm_km", "-3.99", "ps/(nm km)", "number"),
    ("fibre_type", 652, None, "text"),
    ("fibre_type", "none", None, "not a known value"),
    ("fibre_type", "Unknown", None, "not a known value"),
    ("detector", "n/a", None, "not a known value"),
    ("calibration", "volts", "V", "no unit"),
    ("calibration", "volts\x7f", None, "control character"),
    ("modulation_order", 4, "PAM", "no unit"),
    ("raw_format", "bin\x00", None, "control character"),
]


@pytest.mark.parametrize("field, value, unit, message", BAD_VALUES)
def test_known_values_are_typed_per_field_in_the_constructor(field, value, unit, message):
    with pytest.raises(BenchmarkError, match=message):
        parameter = known(value, unit=unit)  # some are already refused by ParameterValue itself
        if field in ASSET_FIELDS:
            make_asset(**{field: parameter})
        else:
            make_source(parameters={field: parameter})


@pytest.mark.parametrize("value", [True, False, [1], {"a": 1}, (1,), b"x", object()])
def test_a_value_is_a_number_or_a_string_never_a_bool_list_or_mapping(value):
    with pytest.raises(BenchmarkError, match="number, a string or null"):
        ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, source_ref="x")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_never_known(value):
    with pytest.raises(BenchmarkError, match="finite"):
        ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, source_ref="x")


@pytest.mark.parametrize("field", list(GOOD_VALUES))
def test_a_well_formed_value_is_accepted_in_each_field(field):
    parameter = good(field)
    if field in ASSET_FIELDS:
        asset = make_asset(**{field: parameter})
        assert field not in asset.missing_fields
    else:
        assert make_source(parameters={field: parameter}).parameters[field] is parameter


def test_zero_length_is_allowed_for_b2b_and_modulation_orders_are_the_listed_ones():
    assert make_asset(fibre_length_km=known(0, unit="km")).parameters["fibre_length_km"].known
    for order in (2, 4, 8, 16):
        make_asset(modulation_order=known(order))


def test_missing_fields_stays_truthful_about_unknowns():
    asset = make_asset(baud_bd=good("baud_bd"), detector=good("detector"))
    assert asset.missing_fields == (
        "sample_rate_hz", "modulation_order", "wavelength_nm", "fibre_type", "fibre_length_km",
        "transmitter_type", "reference_sequence", "raw_format", "calibration",
    )  # fmt: skip


def test_bad_values_in_a_yaml_file_are_refused_too(tmp_path):
    def edit(field, **change):
        document = raw()
        document["source"]["assets"][0]["parameters"][field].update(change)
        return write(tmp_path, document)

    for field, change, message in [
        ("baud_bd", {"value": float("nan")}, "finite"),
        ("baud_bd", {"value": float("inf")}, "finite"),
        ("baud_bd", {"value": -5}, "positive"),
        ("baud_bd", {"value": "fast"}, "number"),
        ("baud_bd", {"value": ""}, "non-empty"),
        ("modulation_order", {"value": 3.7}, "integer"),
        ("fibre_length_km", {"value": -2}, "negative"),
        ("sample_rate_hz", {"value": 256, "unit": "GHz"}, "inconsistent"),
        ("detector", {"value": "null"}, "not a known value"),
    ]:
        with pytest.raises(BenchmarkError, match=message):
            load_source_config(edit(field, **change))
    document = raw()
    document["source"]["assets"][0]["parameters"]["wavelength_nm"].update(
        value="null", provenance="PUBLISHED_MEASUREMENT", source_ref="x"
    )
    with pytest.raises(BenchmarkError, match="not a known value"):
        load_source_config(write(tmp_path, document))


def test_unit_and_text_arguments_are_checked_for_type_and_blankness():
    for name in ("unit", "as_stated", "source_ref"):
        with pytest.raises(BenchmarkError, match="non-empty string"):
            ParameterValue(None, Provenance.UNKNOWN, **{name: " "})
        with pytest.raises(BenchmarkError, match="non-empty string"):
            ParameterValue(None, Provenance.UNKNOWN, **{name: 5})
    with pytest.raises(BenchmarkError, match="ReadHow"):
        ParameterValue(None, Provenance.UNKNOWN, read_how="probably")


# ------------------------------------------------------------------ licence rules
def test_source_without_licence_state_is_refused():
    with pytest.raises(BenchmarkError) as error:
        make_source(licenses=())
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    document = raw()
    del document["source"]["licenses"]
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        parse_source(document["source"])


def test_licence_rules():
    with pytest.raises(BenchmarkError, match="identifier"):
        make_licence(license_id=None)
    with pytest.raises(BenchmarkError, match="scope"):
        make_licence(scope="code")
    with pytest.raises(BenchmarkError, match="LicenseStatus"):
        make_licence(status="RECORD_LEVEL")
    with pytest.raises(BenchmarkError, match="Permission"):
        make_licence(derivatives="ALLOWED")
    with pytest.raises(BenchmarkError, match="non-empty"):
        make_licence(license_id="  ")
    with pytest.raises(BenchmarkError, match="ReadHow"):
        make_licence(read_how="guess")
    with pytest.raises(BenchmarkError, match="note"):
        make_licence(note=5)


@pytest.mark.parametrize(
    "field", ["private_research_use", "public_redistribution", "derivatives", "commercial_use"]
)
@pytest.mark.parametrize("grant", [Permission.ALLOWED, Permission.ALLOWED_WITH_CONDITIONS])
def test_unverified_and_restricted_terms_cannot_grant_anything(field, grant):
    unverified = {
        "private_research_use": Permission.UNVERIFIED,
        "public_redistribution": Permission.UNVERIFIED,
        "derivatives": Permission.UNVERIFIED,
        "commercial_use": Permission.UNVERIFIED,
    }
    with pytest.raises(BenchmarkError, match="unverified terms"):
        make_licence(
            status=LicenseStatus.UNVERIFIED, license_id=None, **(unverified | {field: grant})
        )
    restricted = {
        "private_research_use": Permission.NOT_ALLOWED,
        "public_redistribution": Permission.NOT_ALLOWED,
        "derivatives": Permission.NOT_ALLOWED,
        "commercial_use": Permission.NOT_ALLOWED,
    }
    if field == "private_research_use" and grant is Permission.ALLOWED_WITH_CONDITIONS:
        make_licence(
            status=LicenseStatus.RESTRICTED, license_id=None, **(restricted | {field: grant})
        )
    else:
        with pytest.raises(BenchmarkError, match="RESTRICTED"):
            make_licence(
                status=LicenseStatus.RESTRICTED, license_id=None, **(restricted | {field: grant})
            )


def test_nc_licence_is_incompatible_with_the_mit_repository():
    ran = load_source_config(RAN)
    article = ran.license_for("article")
    assert article.commercial_use is Permission.NOT_ALLOWED
    assert article.derivatives is Permission.NOT_ALLOWED
    assert article.public_redistribution is Permission.ALLOWED_WITH_CONDITIONS
    with pytest.raises(BenchmarkError) as error:
        ran.require_public_redistribution("article")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    assert "commercial use" in str(error.value)
    with pytest.raises(BenchmarkError, match="commercial use"):
        ran.require_derivatives("article")


def test_redistribution_gate_checks_status_permission_commercial_and_derivatives():
    source = make_source()
    source.require_public_redistribution("data")
    source.require_derivatives("data")
    no_public = make_source(make_licence(public_redistribution=Permission.NOT_ALLOWED))
    with pytest.raises(BenchmarkError, match="public redistribution"):
        no_public.require_public_redistribution("data")
    nc = make_source(make_licence(commercial_use=Permission.NOT_ALLOWED))
    with pytest.raises(BenchmarkError, match="commercial use"):
        nc.require_public_redistribution("data")
    no_derivatives = make_source(make_licence(derivatives=Permission.NOT_ALLOWED))
    no_derivatives.require_public_redistribution("data")  # verbatim publication is fine
    with pytest.raises(BenchmarkError, match="adapted material"):
        no_derivatives.require_derivatives("data")
    # defence in depth: a record forced past its constructor with a status that grants nothing
    forced = make_source()
    object.__setattr__(forced.licenses[0], "status", LicenseStatus.UNVERIFIED)
    with pytest.raises(BenchmarkError, match="UNVERIFIED"):
        forced.require_public_redistribution("data")
    object.__setattr__(forced.licenses[0], "status", LicenseStatus.RESTRICTED)
    with pytest.raises(BenchmarkError, match="RESTRICTED"):
        forced.require_public_redistribution("data")


def test_register_states_the_nc_mit_conflict():
    text = " ".join(REGISTER.read_text().split())
    for needle in (
        "NC restricts commercial use, MIT grants it",
        "incompatible",
        "Ran article material, figures even verbatim, and any adapted content stay out of the repository",
        "independently computed results from cleared numeric data",
        "[article text removed: CC BY-NC-ND].",
    ):  # fmt: skip
        assert needle in text, needle


# ------------------------------------------------------------------ checksums
def test_md5_supplied_is_never_verified():
    checksum = Checksum(md5_supplied=MD5_B2B)
    assert checksum.md5_state is Md5State.SUPPLIED
    assert Checksum().md5_state is Md5State.ABSENT
    with pytest.raises(BenchmarkError, match="hexadecimal"):
        Checksum(md5_supplied="XYZ")


def test_md5_verified_cannot_be_typed():
    forged = {"md5_local": MD5_B2B, "sha256_local": "0" * 64}
    for name, value in forged.items():
        with pytest.raises(TypeError):
            Checksum(md5_supplied=MD5_B2B, **{name: value})  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Checksum(MD5_B2B, MD5_B2B, "0" * 64)  # type: ignore[call-arg]
    checksum = Checksum(md5_supplied=MD5_B2B)
    with pytest.raises(dataclasses.FrozenInstanceError):
        checksum.md5_local = MD5_B2B  # type: ignore[misc]
    with pytest.raises(ValueError):
        dataclasses.replace(checksum, md5_local=MD5_B2B)
    # a YAML file cannot supply a local hash either
    for key in ("md5_local", "sha256_local"):
        document = raw()
        document["source"]["assets"][0][key] = None
        with pytest.raises(BenchmarkError, match="unknown keys"):
            parse_source(document["source"])


def test_md5_verified_only_after_local_bytes_match(tmp_path):
    payload = b"synthetic fixture, not a capture"
    path = tmp_path / "f.bin"
    path.write_bytes(payload)
    supplied = hashlib.md5(payload).hexdigest()
    verified = verify_local_asset(path, supplied)
    assert verified.md5_state is Md5State.VERIFIED
    assert verified.md5_local == supplied
    assert verified.sha256_local == hashlib.sha256(payload).hexdigest()
    wrong = verify_local_asset(path, MD5_B2B)
    assert wrong.md5_state is Md5State.MISMATCH
    assert wrong.md5_local == supplied
    assert verify_local_asset(path).md5_state is Md5State.ABSENT
    assert path.read_bytes() == payload  # untouched
    # copying a verified checksum with another supplied MD5 cannot keep the verification
    replaced = dataclasses.replace(verified, md5_supplied=MD5_B2B)
    assert replaced.md5_state is Md5State.SUPPLIED and replaced.sha256_local is None


def test_verify_local_asset_streams_large_files(tmp_path):
    payload = bytes(range(256)) * 9000  # larger than one hashing chunk is not needed to be exact
    path = tmp_path / "big.bin"
    path.write_bytes(payload * 1)
    assert verify_local_asset(path).sha256_local == hashlib.sha256(payload).hexdigest()


def test_missing_dataset_is_source_missing(tmp_path):
    asset = load_source_config(TERIPHIC).assets[0]
    with pytest.raises(BenchmarkError) as error:
        require_local_asset(asset, tmp_path)
    assert error.value.code is ErrorCode.SOURCE_MISSING
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        verify_local_asset(tmp_path / asset.filename, asset.checksum.md5_supplied)
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        verify_local_asset(tmp_path)  # a directory is not a file
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        load_source_config(tmp_path / "absent.yaml")
    (tmp_path / asset.filename).write_bytes(b"x")
    assert require_local_asset(asset, tmp_path).name == asset.filename


@pytest.mark.parametrize("bad", [123, b"ab", "a" * 31, "a" * 33, "A" * 32, "g" * 32, ""])
def test_checksum_text_is_typed_and_lowercase_hex(bad):
    with pytest.raises(BenchmarkError, match="hexadecimal"):
        Checksum(md5_supplied=bad)


# ------------------------------------------------------------------ leakage
def test_split_overlap_by_group_and_hash(tmp_path):
    with pytest.raises(BenchmarkError) as error:
        assert_no_split_overlap(
            [make_asset("g/B2B", Split.CHARACTERISATION), make_asset("g/B2B", Split.LOCKED_TEST)]
        )
    assert error.value.code is ErrorCode.LEAKAGE_DETECTED
    assert_no_split_overlap(
        [make_asset("g/B2B", name="a.bin"), make_asset("g/2km", Split.VALIDATION, "b.bin")]
    )


def leaking(first: AssetRecord, second: AssetRecord, message: str):
    with pytest.raises(BenchmarkError, match=message) as error:
        assert_no_split_overlap([first, second])
    assert error.value.code is ErrorCode.LEAKAGE_DETECTED


def test_same_group_in_two_roles_is_leakage_even_when_the_case_differs():
    leaking(
        make_asset("g/B2B", name="a.bin"), make_asset("G/b2b", Split.LOCKED_TEST, "b.bin"), "both"
    )


def test_same_filename_in_two_roles_or_two_groups_is_leakage():
    leaking(
        make_asset("g/B2B", name="x.bin"),
        make_asset("g/10km", Split.LOCKED_TEST, "x.bin"),
        "file name",
    )
    leaking(make_asset("g/B2B", name="x.bin"), make_asset("g/other", name="x.bin"), "file name")
    leaking(
        make_asset("g/B2B", name="X.bin"),
        make_asset("g/10km", Split.LOCKED_TEST, "x.BIN"),
        "file name",
    )


def test_same_supplied_md5_in_two_roles_or_groups_is_leakage():
    leaking(
        make_asset("g/B2B", name="a.bin", md5=MD5_B2B),
        make_asset("g/10km", Split.LOCKED_TEST, "b.bin", md5=MD5_B2B),
        "supplied MD5",
    )
    leaking(
        make_asset("g/B2B", name="a.bin", md5=MD5_B2B),
        make_asset("g/other", name="b.bin", md5=MD5_B2B),
        "supplied MD5",
    )


def test_identical_local_bytes_in_two_roles_are_leakage(tmp_path):
    first, second = tmp_path / "a.bin", tmp_path / "b.bin"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")
    a = with_local_hash(make_asset("g/B2B", name="a.bin"), first)
    b = with_local_hash(make_asset("g/10km", Split.LOCKED_TEST, "b.bin"), second)
    leaking(a, b, "local MD5|local SHA-256")
    assert a.checksum.sha256_local == b.checksum.sha256_local
    # different bytes pass
    second.write_bytes(b"other bytes")
    c = with_local_hash(make_asset("g/10km", Split.LOCKED_TEST, "b.bin"), second)
    assert_no_split_overlap([a, c])


def forced_checksum(**local) -> Checksum:
    checksum = Checksum()
    for name, value in local.items():
        object.__setattr__(checksum, name, value)
    return checksum


def test_each_local_hash_branch_alone_detects_leakage():
    for name, length in (("md5_local", 32), ("sha256_local", 64)):
        one = make_asset("g/B2B", name="a.bin", checksum=forced_checksum(**{name: "a" * length}))
        two = make_asset(
            "g/10km", Split.LOCKED_TEST, "b.bin", checksum=forced_checksum(**{name: "a" * length})
        )
        leaking(one, two, "local MD5" if name == "md5_local" else "local SHA-256")
        other = make_asset(
            "g/10km", Split.LOCKED_TEST, "b.bin", checksum=forced_checksum(**{name: "b" * length})
        )
        assert_no_split_overlap([one, other])
    # the same bytes under the same group and role is one acquisition, not leakage
    twin = make_asset("g/B2B", name="b.bin", checksum=forced_checksum(sha256_local="a" * 64))
    assert_no_split_overlap(
        [make_asset("g/B2B", name="a.bin", checksum=forced_checksum(sha256_local="a" * 64)), twin]
    )


def test_loader_applies_the_leakage_check(tmp_path):
    def move_10km_into_b2b_group(d):
        d["source"]["assets"][2]["group"] = d["source"]["assets"][0]["group"]

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, move_10km_into_b2b_group))

    def reuse_md5(d):
        d["source"]["assets"][2]["md5_supplied"] = d["source"]["assets"][0]["md5_supplied"]

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, reuse_md5))

    def swap_case(d):
        d["source"]["assets"][2]["group"] = d["source"]["assets"][0]["group"].lower()
        d["source"]["assets"][0]["group"] = d["source"]["assets"][0]["group"].upper()

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, swap_case))


# ------------------------------------------------------------------ schema holes
@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "a/b", "a\x00b", "..", "a b", "", " ", "-x", "a\\b"]
)
def test_source_id_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_source(source_id=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../x.bin",
        "a/b.bin",
        "a\\b.bin",
        "a\x00.bin",
        ".hidden",
        "a..b.bin",
        "",
        "a b.bin",
        "x" * 300,
    ],
)
def test_filename_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_asset(name=bad)


@pytest.mark.parametrize("bad", ["", "..", "a//b", "a/../b", "/abs", "a\\b", "a\x00", "a/ b"])
def test_group_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_asset(group=bad)


@pytest.mark.parametrize("field, bad", [
    ("doi", "not-a-doi"), ("doi", "10.1234/a b"), ("url", "file:///etc/passwd"), ("url", "ftp://x/y"),
    ("retrieved", "31/10/2026"), ("retrieved", "2026-13-01"), ("kind", "notebook"),
    ("title", "  "), ("version", " "), ("plan_sha256", "A" * 64), ("plan_sha256", "a" * 63),
    ("plan_sha256", "g" * 64), ("plan_sha256", 5),
])  # fmt: skip
def test_source_text_fields_are_validated_in_the_constructor(field, bad):
    with pytest.raises(BenchmarkError):
        make_source(**{field: bad})


def test_plan_sha256_accepts_only_64_lowercase_hex():
    assert make_source(plan_sha256="a" * 64).plan_sha256 == "a" * 64


def test_version_must_be_the_integer_one(tmp_path):
    for version in (1.0, "1", True, 2, None):
        with pytest.raises(BenchmarkError, match="benchmark_config_version"):
            load_source_config(
                mutate(tmp_path, lambda d, v=version: d.update(benchmark_config_version=v))
            )


def test_asset_identifiers_are_validated_without_a_source():
    for bad in ("../x", "a/b", "a\x00b", ""):
        with pytest.raises(BenchmarkError):
            dataclasses.replace(make_asset(), source_id=bad)
    for field, bad in (("doi", "x"), ("url", "file:///x")):
        with pytest.raises(BenchmarkError):
            dataclasses.replace(make_asset(), **{field: bad})


def test_asset_size_and_wording_are_validated_in_the_constructor():
    for bad in (0, -1, True, 1.5, "10"):
        with pytest.raises(BenchmarkError, match="positive integer"):
            make_asset(size_bytes=bad)
    assert make_asset(size_bytes=None).size_bytes is None
    with pytest.raises(BenchmarkError, match="non-empty"):
        dataclasses.replace(make_asset(), asset_version=" ")
    with pytest.raises(BenchmarkError, match="non-empty"):
        dataclasses.replace(make_asset(), sample_rate_wording=" ")
    with pytest.raises(BenchmarkError, match="Checksum"):
        dataclasses.replace(make_asset(), checksum=MD5_B2B)
    with pytest.raises(BenchmarkError, match="Split"):
        dataclasses.replace(make_asset(), split="TEST")


def test_source_id_of_an_asset_must_match_its_source():
    asset = make_asset()
    other = dataclasses.replace(asset, source_id="other")
    assert make_source(assets=(asset,)).assets == (asset,)
    with pytest.raises(BenchmarkError, match="source_id differs"):
        make_source(assets=(other,))


def test_a_filename_cannot_be_listed_twice_in_a_source():
    a = make_asset("g/a", name="x.bin")
    b = make_asset("g/a", name="X.bin")
    with pytest.raises(BenchmarkError, match="twice|file name"):
        make_source(assets=(a, b))


def test_a_licence_scope_cannot_be_listed_twice_and_licences_must_be_records():
    with pytest.raises(BenchmarkError, match="twice"):
        make_source(licenses=(make_licence(), make_licence()))
    with pytest.raises(BenchmarkError, match="LicenseRecord"):
        make_source(licenses=("CC-BY",))
    with pytest.raises(BenchmarkError, match="AssetRecord"):
        make_source(assets=("a.bin",))


def test_records_do_not_alias_the_callers_containers():
    parameters = asset_parameters()
    asset = make_asset()
    asset = AssetRecord(
        "s", "10.1234/x", "https://e.invalid/x", "v", "a.bin", Checksum(), 1, Split.RESERVED, "g",
        parameters,
    )  # fmt: skip
    parameters["baud_bd"] = good("baud_bd")  # caller edits its dict afterwards
    assert not asset.parameters["baud_bd"].known
    with pytest.raises(TypeError):
        asset.parameters["baud_bd"] = good("baud_bd")  # type: ignore[index]
    with pytest.raises(TypeError):
        del asset.parameters["baud_bd"]  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.split = Split.LOCKED_TEST  # type: ignore[misc]

    licences = [make_licence()]
    assets = [make_asset()]
    source_parameters = {"wavelength_band": good("wavelength_band")}
    source = make_source(licenses=licences, assets=assets, parameters=source_parameters)  # type: ignore[arg-type]
    licences.append(make_licence(scope="article"))
    assets.append(make_asset("g/other", name="b.bin"))
    source_parameters["equalizer"] = known("FFE")
    assert isinstance(source.licenses, tuple) and len(source.licenses) == 1
    assert isinstance(source.assets, tuple) and len(source.assets) == 1
    assert set(source.parameters) == {"wavelength_band"}
    with pytest.raises(TypeError):
        source.parameters["equalizer"] = known("FFE")  # type: ignore[index]


# ------------------------------------------------------------------ holdout guards
def test_only_the_locked_test_can_be_validated():
    everything = {
        "VALIDATED", "FAILED", "INCONCLUSIVE", "UNIDENTIFIABLE_PARAMETER", "BLOCKED",
    }  # fmt: skip
    assert {v.value for v in Verdict} == everything
    assert {v.value for v in allowed_verdicts(Split.LOCKED_TEST)} == everything
    assert {v.value for v in allowed_verdicts(Split.LOCKED_TEST, validation_failed=True)} == (
        everything - {"VALIDATED"}
    )
    assert {v.value for v in allowed_verdicts(Split.VALIDATION)} == everything - {"VALIDATED"}
    assert {v.value for v in allowed_verdicts(Split.VALIDATION)} >= {"FAILED", "INCONCLUSIVE"}
    assert {v.value for v in allowed_verdicts(Split.CHARACTERISATION)} == {
        "INCONCLUSIVE",
        "BLOCKED",
    }
    assert {v.value for v in allowed_verdicts(Split.RESERVED)} == {"BLOCKED"}
    assert {v.value for v in allowed_verdicts(Split.UNASSIGNED)} == {"BLOCKED"}


def test_ber_needs_a_reference_stated_by_a_source():
    for asset in load_source_config(TERIPHIC).assets:
        with pytest.raises(BenchmarkError, match="no transmitted sequence is documented") as error:
            require_reference_for_ber(asset)
        assert error.value.code is ErrorCode.REFERENCE_SEQUENCE_MISSING
    for how in (Provenance.INFERRED, Provenance.DIGITIZED_FIGURE, Provenance.RAW_CAPTURE):
        recovered = make_asset(reference_sequence=known("recovered from B2B", how))
        with pytest.raises(BenchmarkError, match="inferred candidate") as error:
            require_reference_for_ber(recovered)
        assert error.value.code is ErrorCode.REFERENCE_SEQUENCE_MISSING
    stated = make_asset(reference_sequence=known("PRBS13Q"))
    assert require_reference_for_ber(stated) == "PRBS13Q"


METRIC_NAMES = (
    "M1_level_spacing", "M2_wasserstein1_amplitude", "M3_quantile_error", "M4_log_spectral_distance",
)  # fmt: skip


def git_available() -> bool:
    return shutil.which("git") is not None


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )  # fmt: skip


def criterion_document(plan: Path, **limits) -> dict:
    values = dict.fromkeys(METRIC_NAMES, 0.1) | limits
    return {
        "criterion_version": 1,
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "limits": values,
    }


@pytest.fixture
def repo(tmp_path):
    if not git_available():
        pytest.skip("git is not installed")
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "plan.md").write_text("plan text")
    git(root, "add", "plan.md")
    git(root, "commit", "-q", "-m", "plan")
    return root


def freeze(root: Path, document: dict, commit: bool = True) -> Path:
    path = root / "criterion.yaml"
    path.write_text(yaml.safe_dump(document))
    if commit:
        git(root, "add", "criterion.yaml")
        git(root, "commit", "-q", "-m", "freeze")
    return path


def holdout_assets():
    return {a.split: a for a in load_source_config(TERIPHIC).assets}


def test_holdout_without_a_frozen_criterion_is_refused(tmp_path):
    assets = holdout_assets()
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        with pytest.raises(BenchmarkError, match="no frozen criterion"):
            require_frozen_criterion(assets[split], tmp_path / "absent.yaml")
    # the characterisation file needs none
    assert (
        require_frozen_criterion(assets[Split.CHARACTERISATION], tmp_path / "absent.yaml") is None
    )
    assert holdout.HOLDOUT_SPLITS == {Split.VALIDATION, Split.LOCKED_TEST}
    assert holdout.METRICS == METRIC_NAMES


def test_a_committed_complete_criterion_is_returned_with_its_commit(repo):
    path = freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=0.25))
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        frozen = require_frozen_criterion(
            holdout_assets()[split], path, plan_path=repo / "plan.md", repo_root=repo
        )
        assert frozen is not None
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert frozen.commit == head and len(frozen.committed_at) >= 20
        assert frozen.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert frozen.limits["M1_level_spacing"] == 0.25
        assert set(frozen.limits) == set(METRIC_NAMES)
        with pytest.raises(TypeError):
            frozen.limits["M1_level_spacing"] = 9.0


def refuse(repo, path, message):
    with pytest.raises(BenchmarkError, match=message):
        require_frozen_criterion(
            holdout_assets()[Split.VALIDATION], path, plan_path=repo / "plan.md", repo_root=repo
        )


def test_an_uncommitted_or_modified_criterion_is_refused(repo):
    path = freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    refuse(repo, path, "not committed")
    git(repo, "add", "criterion.yaml")
    refuse(repo, path, "not committed")  # staged, not committed
    git(repo, "commit", "-q", "-m", "freeze")
    require_frozen_criterion(
        holdout_assets()[Split.VALIDATION], path, plan_path=repo / "plan.md", repo_root=repo
    )
    path.write_text(path.read_text().replace("0.1", "0.9"))
    refuse(repo, path, "not committed or modified")


def test_a_criterion_for_another_plan_or_with_bad_limits_is_refused(repo):
    other = criterion_document(repo / "plan.md") | {"plan_sha256": "0" * 64}
    refuse(repo, freeze(repo, other), "another version of the plan")
    for bad, message in [
        ({"M1_level_spacing": 0}, "finite and positive"),
        ({"M2_wasserstein1_amplitude": -1.0}, "finite and positive"),
        ({"M3_quantile_error": float("nan")}, "finite and positive"),
        ({"M4_log_spectral_distance": float("inf")}, "finite and positive"),
        ({"M1_level_spacing": True}, "finite and positive"),
        ({"M1_level_spacing": "0.1"}, "finite and positive"),
    ]:
        refuse(
            repo, freeze(repo, criterion_document(repo / "plan.md", **bad), commit=False), message
        )


def test_a_criterion_with_missing_extra_or_malformed_keys_is_refused(repo):
    base = criterion_document(repo / "plan.md")
    missing = dict(
        base, limits={k: v for k, v in base["limits"].items() if k != "M3_quantile_error"}
    )
    refuse(repo, freeze(repo, missing, commit=False), "limits must be exactly")
    refuse(
        repo,
        freeze(repo, dict(base, limits=base["limits"] | {"M5": 1.0}), commit=False),
        "limits must be exactly",
    )
    refuse(repo, freeze(repo, dict(base, extra=1), commit=False), "exactly criterion_version")
    refuse(repo, freeze(repo, dict(base, criterion_version=2), commit=False), "criterion_version")
    refuse(repo, freeze(repo, dict(base, criterion_version=1.0), commit=False), "criterion_version")
    refuse(repo, freeze(repo, dict(base, limits=[1]), commit=False), "limits must be exactly")
    path = repo / "criterion.yaml"
    path.write_text("- not\n- a mapping\n")
    refuse(repo, path, "exactly criterion_version")
    path.write_text("criterion_version: 1\ncriterion_version: 1\n")
    refuse(repo, path, "not valid YAML")


def test_a_git_ignored_criterion_is_refused(repo):
    (repo / ".gitignore").write_text("criterion.yaml\n")
    path = freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    refuse(repo, path, "no commit contains")


def test_a_criterion_outside_the_repository_is_refused(repo, tmp_path):
    outside = tmp_path / "elsewhere.yaml"
    outside.write_text(yaml.safe_dump(criterion_document(repo / "plan.md")))
    refuse(repo, outside, "outside the repository")


# ------------------------------------------------------------------ strict loader
def mutate(tmp_path, edit):
    document = raw()
    edit(document)
    return write(tmp_path, document)


def with_text(tmp_path, edit) -> Path:
    path = tmp_path / "dup.yaml"
    path.write_text(edit(TERIPHIC.read_text()))
    return path


def test_duplicate_yaml_keys_are_refused_at_every_level(tmp_path):
    # Repro 1 of the review: a second `split` under the 10 km asset used to win silently.
    def second_split(text):
        needle = "        split: LOCKED_TEST\n"
        assert text.count(needle) == 1
        return text.replace(needle, needle + "        split: CHARACTERISATION\n")

    with pytest.raises(BenchmarkError, match="duplicate key 'split'"):
        load_source_config(with_text(tmp_path, second_split))

    # Repro 2: a second wavelength_nm turned an unknown into a measured value.
    def second_wavelength(text):
        marker = "          wavelength_nm: {value: null, provenance: UNKNOWN"
        last = text.rindex(marker)
        end = text.index("\n", last) + 1
        extra = (
            "          wavelength_nm: {value: 1310, provenance: PUBLISHED_MEASUREMENT,"
            " unit: nm, source_ref: x}\n"
        )
        return text[:end] + extra + text[end:]

    with pytest.raises(BenchmarkError, match="duplicate key 'wavelength_nm'"):
        load_source_config(with_text(tmp_path, second_wavelength))

    def second_md5(text):
        needle = '        md5_supplied: "3d8774b068deaf50f37892b38953dfd6"\n'
        return text.replace(needle, needle + needle.replace("3d8774", "d7bd6d"))

    with pytest.raises(BenchmarkError, match="duplicate key 'md5_supplied'"):
        load_source_config(with_text(tmp_path, second_md5))

    for key, text in {
        "source_id": lambda t: t.replace("  source_id: teriphic_pd_array\n", "  source_id: teriphic_pd_array\n  source_id: other\n"),
        "benchmark_config_version": lambda t: t.replace("benchmark_config_version: 1\n", "benchmark_config_version: 1\nbenchmark_config_version: 1\n"),
        "value": lambda t: t.replace("{value: 0, provenance", "{value: 0, value: 9, provenance", 1),
    }.items():  # fmt: skip
        with pytest.raises(BenchmarkError, match=f"duplicate key '{key}'"):
            load_source_config(with_text(tmp_path, text))
    # merge keys count as keys: an override through `<<` is refused too
    merged = TERIPHIC.read_text().replace(
        '  retrieved: "2026-10-31"\n',
        '  retrieved: "2026-10-31"\n  <<: {retrieved: "2000-01-01"}\n',
    )
    path = tmp_path / "merge.yaml"
    path.write_text(merged)
    with pytest.raises(BenchmarkError, match="duplicate key 'retrieved'"):
        load_source_config(path)
    complex_key = TERIPHIC.read_text().replace("source:\n", "source:\n  ? [1, 2]\n  : x\n", 1)
    path.write_text(complex_key)
    with pytest.raises(BenchmarkError, match="unhashable"):
        load_source_config(path)


def test_the_committed_configs_have_no_duplicate_keys():
    for path in (TERIPHIC, RAN, WIEGART):
        assert catalog.load_strict_yaml(path.read_text()) == yaml.safe_load(path.read_text())


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.update(extra=1), "unknown keys"),
        (lambda d: d.update(benchmark_config_version=2), "benchmark_config_version"),
        (lambda d: d.update(benchmark_config_version=True), "benchmark_config_version"),
        (lambda d: d["source"].update(extra=1), "unknown keys"),
        (lambda d: d["source"].pop("doi"), "missing keys"),
        (lambda d: d["source"].update(kind="notebook"), "dataset or publication"),
        (lambda d: d["source"].update(title="   "), "non-empty string"),
        (lambda d: d["source"]["licenses"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["licenses"][0].update(status="open"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(status="VERIFIED"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(scope="code"), "scope"),
        (lambda d: d["source"]["licenses"][0].pop("derivatives"), "missing keys"),
        (lambda d: d["source"]["licenses"][0].pop("commercial_use"), "missing keys"),
        (lambda d: d["source"]["licenses"][0].update(commercial_use="YES"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(read_how="guess"), "ReadHow"),
        (lambda d: d["source"]["licenses"].append(dict(d["source"]["licenses"][0])), "twice"),
        (lambda d: d["source"]["licenses"].clear(), "licence state is required"),
        (lambda d: d["source"].update(licenses="CC-BY"), "licence state is required"),
        (lambda d: d["source"].update(assets="none"), "must be a list"),
        (lambda d: d["source"]["assets"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["assets"][0].update(split="TEST"), "not one of"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=-5), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=True), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(md5_supplied="nothex"), "hexadecimal"),
        (lambda d: d["source"]["assets"][0].update(md5_supplied="  "), "non-empty"),
        (lambda d: d["source"]["assets"][0].update(md5_local="0" * 32), "unknown keys"),
        (lambda d: d["source"]["assets"][0].update(filename="../x.bin"), "not allowed"),
        (lambda d: d["source"]["assets"].append(dict(d["source"]["assets"][0])), "twice"),
        (lambda d: d["source"]["assets"][0]["parameters"].pop("raw_format"), "raw_format"),
        (lambda d: d["source"]["assets"][0]["parameters"].update(laser={"value": None, "provenance": "UNKNOWN"}), "unknown parameter"),
        (lambda d: d["source"]["assets"][0]["parameters"].update(baud_bd="fast"), "mapping"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].pop("provenance"), "missing keys"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(provenance="MEASURED"), "not one of"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(source_ref=None), "source_ref"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value=True), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value=[1]), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value={"a": 1}), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(read_how="guess"), "ReadHow"),
        (lambda d: d["source"]["assets"][0]["parameters"]["wavelength_nm"].update(value=1310), "UNKNOWN"),
        (lambda d: d["source"]["assets"][0]["parameters"]["wavelength_nm"].update(provenance="SIMULATED"), "missing value"),
        (lambda d: d["source"]["assets"][0]["parameters"]["fibre_type"].update(
            value="G.652.D", provenance="SIMULATED", source_ref="default"), "SIMULATED"),
        (lambda d: d["source"].update(plan_sha256="abc"), "plan_sha256"),
    ],
)  # fmt: skip
def test_malformed_config_is_refused_at_every_level(tmp_path, edit, message):
    with pytest.raises(BenchmarkError, match=message):
        load_source_config(mutate(tmp_path, edit))


def test_loader_rejects_non_mapping_and_bad_yaml(tmp_path):
    for body in ("- a\n- b\n", "source: [", ""):
        path = tmp_path / "bad.yaml"
        path.write_text(body)
        with pytest.raises(BenchmarkError):
            load_source_config(path)
    for place in ("asset", "source"):
        document = raw()
        target = document["source"]["assets"][0] if place == "asset" else document["source"]
        target["parameters"] = ["baud_bd"]
        with pytest.raises(BenchmarkError, match="mapping of parameter name"):
            load_source_config(write(tmp_path, document))


def test_catalog_module_exports_no_loader_for_urls():
    assert not hasattr(catalog, "urlopen") and not hasattr(catalog, "download")


# ------------------------------------------------------------------ importer audit
def fake_teriphic_bins(tmp_path: Path) -> dict[str, Path]:
    """Independently made files that only carry a TERIPHIC name; none is a capture."""
    rng = np.random.default_rng(7)
    floats = rng.normal(size=4096).astype("<f4").tobytes()
    cases = {
        "float32_noise": floats,
        "int16_noise": rng.integers(-2000, 2000, 4096).astype("<i2").tobytes(),
        "zeros": bytes(4096),
        "cookie_only": b"AG10" + bytes(8),
        "cookie_wrong_size": b"AG10" + (9999).to_bytes(4, "little") + (1).to_bytes(4, "little") + floats,
        "wrong_cookie_right_size": b"XX10" + (4096 + 12).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4096),
        "header_only": b"AG10" + (12).to_bytes(4, "little") + (1).to_bytes(4, "little"),
    }  # fmt: skip
    out = {}
    for tag, blob in cases.items():
        path = tmp_path / f"50G_PAM4_PD1_B2B_Subassembly1_{tag}.bin"
        path.write_bytes(blob)
        out[tag] = path
    return out


def test_teriphic_named_fake_bin_is_rejected_by_the_keysight_parser(tmp_path):
    for tag, path in fake_teriphic_bins(tmp_path).items():
        with pytest.raises(UxrImportError):
            read_bin(path)
        with pytest.raises(UxrImportError):
            read_scope_file(path)
        assert path.exists(), tag  # the importer never modifies its input
