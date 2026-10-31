"""Stage 3A gate E0: provenance schema, strict catalog loader, plan pin, importer rejection.

Everything here is offline and synthetic. No external dataset is read or needed.
"""

import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.benchmarks import catalog, provenance
from opticps.benchmarks.catalog import load_source_config, parse_source, require_local_asset
from opticps.benchmarks.provenance import (
    ASSET_FIELDS,
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
    verify_md5,
)
from opticps.measurement.uxr_import import UxrImportError, read_bin, read_scope_file
from opticps.transmitter.mpam_config import load_mpam_config

CONFIGS = Path("configs/benchmarks")
TERIPHIC = CONFIGS / "teriphic_pd1_pam4.yaml"
PLAN = Path("docs/benchmarks/FIT_HOLDOUT_PLAN.md")
# Pinned when the plan was declared (2026-10-31, before any sample was read). A deliberate
# amendment must change this line, the plan_sha256 in the TERIPHIC config and add a dated section.
PLAN_SHA256 = "6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a"
MD5_B2B = "d7bd6d48bc020a138f4f129bc2ba7312"


def raw(path: Path = TERIPHIC) -> dict:
    return yaml.safe_load(path.read_text())


def write(tmp_path: Path, document: dict, name: str = "c.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def known(value, how=Provenance.PUBLISHED_MEASUREMENT):
    return ParameterValue(value, how, source_ref="test")


def asset_parameters() -> dict:
    return {name: ParameterValue.unknown() for name in ASSET_FIELDS}


def make_asset(group="g/B2B", split=Split.CHARACTERISATION, sha=None, name="a.bin", **extra):
    return AssetRecord(
        source_id="s",
        doi="10.0/x",
        url="https://example.invalid/r",
        asset_version="v1",
        filename=name,
        checksum=Checksum(sha256_local=sha),
        size_bytes=10,
        split=split,
        group=group,
        parameters=asset_parameters() | extra,
    )


# ------------------------------------------------------------------ plan pin
def test_plan_hash_is_pinned_in_test_and_config():
    digest = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert digest == PLAN_SHA256, (
        "FIT_HOLDOUT_PLAN.md changed: amend with a dated section and a new pin"
    )
    assert load_source_config(TERIPHIC).plan_sha256 == PLAN_SHA256


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


# ------------------------------------------------------------------ configs
@pytest.mark.parametrize("name", ["teriphic_pd1_pam4", "ran_2025_g652d", "wiegart_2021_peak_pam4"])
def test_committed_configs_load_with_licence_state(name):
    source = load_source_config(CONFIGS / f"{name}.yaml")
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


def test_article_and_data_licences_are_separate():
    ran = load_source_config(CONFIGS / "ran_2025_g652d.yaml")
    article, data = ran.license_for("article"), ran.license_for("data")
    assert article.status is LicenseStatus.VERIFIED and article.license_id == "CC-BY-NC-ND-4.0"
    assert data.status is LicenseStatus.UNVERIFIED and data.license_id is None
    assert data.status.label == "LICENSE/REUSE TERMS UNVERIFIED"
    with pytest.raises(BenchmarkError) as error:
        ran.require_public_redistribution("data")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    wiegart = load_source_config(CONFIGS / "wiegart_2021_peak_pam4.yaml")
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        wiegart.require_public_redistribution("article")
    with pytest.raises(BenchmarkError, match="no data licence"):
        wiegart.license_for("data")


def test_ran_uses_1271_not_the_1550_default():
    ran = load_source_config(CONFIGS / "ran_2025_g652d.yaml").parameters
    assert ran["wavelength_nm"].value == 1271 and ran["dispersion_ps_per_nm_km"].value < 0
    assert ran["rate_definition"].value is None and ran["ber_definition"].value is None
    assert ran["chirp_model_status"].value == "MODEL_GAP"


def test_benchmark_configs_cannot_change_an_experiment_id():
    cfg = Path("configs/mpam_profiles.yaml")
    assert load_mpam_config(cfg).sha256 == hashlib.sha256(cfg.read_bytes()).hexdigest()
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


def test_simulated_default_cannot_fill_a_measured_field():
    with pytest.raises(BenchmarkError) as error:
        make_asset(wavelength_nm=known(1550, Provenance.SIMULATED))
    assert error.value.code is ErrorCode.NOT_COMPARABLE
    for field in provenance.MEASURED_FIELDS & set(ASSET_FIELDS):
        with pytest.raises(BenchmarkError, match="SIMULATED"):
            make_asset(**{field: known(1, Provenance.SIMULATED)})
    # an INFERRED or digitised value stays allowed but keeps its label
    asset = make_asset(wavelength_nm=known(1271, Provenance.INFERRED))
    assert asset.parameters["wavelength_nm"].provenance is Provenance.INFERRED


def test_asset_must_state_every_field_and_no_others():
    parameters = asset_parameters()
    del parameters["wavelength_nm"]
    with pytest.raises(BenchmarkError, match="wavelength_nm"):
        AssetRecord("s", "d", "u", "v", "a.bin", Checksum(), 1, Split.RESERVED, "g", parameters)
    with pytest.raises(BenchmarkError, match="unknown parameter"):
        make_asset(laser_power_dbm=ParameterValue.unknown())
    with pytest.raises(BenchmarkError, match="bare file name"):
        make_asset(name="../x.bin")


# ------------------------------------------------------------------ licence rules
def test_source_without_licence_state_is_refused():
    with pytest.raises(BenchmarkError) as error:
        SourceRecord("s", "dataset", "t", "d", "u", None, "2026-10-31", licenses=())
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    document = raw()
    del document["source"]["licenses"]
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        parse_source(document["source"])


def test_licence_rules():
    with pytest.raises(BenchmarkError, match="identifier"):
        LicenseRecord("data", LicenseStatus.VERIFIED, None, Permission.ALLOWED, Permission.ALLOWED)
    with pytest.raises(BenchmarkError, match="unverified terms"):
        LicenseRecord(
            "data", LicenseStatus.UNVERIFIED, None, Permission.UNVERIFIED, Permission.ALLOWED
        )
    with pytest.raises(BenchmarkError, match="scope"):
        LicenseRecord(
            "code", LicenseStatus.RESTRICTED, None, Permission.UNVERIFIED, Permission.NOT_ALLOWED
        )


# ------------------------------------------------------------------ checksums
def test_md5_supplied_is_never_verified(tmp_path):
    checksum = Checksum(md5_supplied=MD5_B2B)
    assert checksum.md5_state is Md5State.SUPPLIED
    assert Checksum().md5_state is Md5State.ABSENT
    with pytest.raises(BenchmarkError, match="local SHA-256"):
        Checksum(md5_supplied=MD5_B2B, md5_local=MD5_B2B)
    with pytest.raises(BenchmarkError, match="hexadecimal"):
        Checksum(md5_supplied="XYZ")


def test_md5_verified_only_after_local_bytes_match(tmp_path):
    payload = b"synthetic fixture, not a capture"
    path = tmp_path / "f.bin"
    path.write_bytes(payload)
    supplied = hashlib.md5(payload).hexdigest()
    verified = verify_md5(path, Checksum(md5_supplied=supplied))
    assert verified.md5_state is Md5State.VERIFIED
    assert verified.sha256_local == hashlib.sha256(payload).hexdigest()
    wrong = verify_md5(path, Checksum(md5_supplied=MD5_B2B))
    assert wrong.md5_state is Md5State.MISMATCH
    assert verify_md5(path, Checksum()).md5_state is Md5State.ABSENT
    assert path.read_bytes() == payload  # untouched


def test_missing_dataset_is_source_missing(tmp_path):
    asset = load_source_config(TERIPHIC).assets[0]
    with pytest.raises(BenchmarkError) as error:
        require_local_asset(asset, tmp_path)
    assert error.value.code is ErrorCode.SOURCE_MISSING
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        verify_md5(tmp_path / asset.filename, asset.checksum)
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        load_source_config(tmp_path / "absent.yaml")
    (tmp_path / asset.filename).write_bytes(b"x")
    assert require_local_asset(asset, tmp_path).name == asset.filename


# ------------------------------------------------------------------ leakage
def test_split_overlap_by_group_and_hash():
    digest = "a" * 64
    with pytest.raises(BenchmarkError) as error:
        assert_no_split_overlap(
            [make_asset("g/B2B", Split.CHARACTERISATION), make_asset("g/B2B", Split.LOCKED_TEST)]
        )
    assert error.value.code is ErrorCode.LEAKAGE_DETECTED
    with pytest.raises(BenchmarkError, match="identical bytes"):
        assert_no_split_overlap(
            [
                make_asset("g/B2B", Split.CHARACTERISATION, digest, "a.bin"),
                make_asset("g/10km", Split.LOCKED_TEST, digest, "b.bin"),
            ]
        )
    assert_no_split_overlap([make_asset("g/B2B"), make_asset("g/2km", Split.VALIDATION)])


# ------------------------------------------------------------------ strict loader
def mutate(tmp_path, edit):
    document = raw()
    edit(document)
    return write(tmp_path, document)


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.update(extra=1), "unknown keys"),
        (lambda d: d.update(benchmark_config_version=2), "benchmark_config_version"),
        (lambda d: d.update(benchmark_config_version=True), "benchmark_config_version"),
        (lambda d: d["source"].update(extra=1), "unknown keys"),
        (lambda d: d["source"].pop("doi"), "missing keys"),
        (lambda d: d["source"].update(kind="notebook"), "dataset or publication"),
        (lambda d: d["source"]["licenses"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["licenses"][0].update(status="open"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(scope="code"), "scope"),
        (lambda d: d["source"]["licenses"].append(dict(d["source"]["licenses"][0])), "twice"),
        (lambda d: d["source"]["assets"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["assets"][0].update(split="TEST"), "not one of"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=-5), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=True), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(md5_supplied="nothex"), "hexadecimal"),
        (lambda d: d["source"]["assets"][0].update(md5_local="0" * 32), "local SHA-256"),
        (lambda d: d["source"]["assets"].append(dict(d["source"]["assets"][0])), "twice"),
        (lambda d: d["source"]["assets"][0]["parameters"].pop("raw_format"), "raw_format"),
        (lambda d: d["source"]["assets"][0]["parameters"].update(laser={"value": None, "provenance": "UNKNOWN"}), "unknown parameter"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].pop("provenance"), "missing keys"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(provenance="MEASURED"), "not one of"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(source_ref=None), "source_ref"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value=True), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(extra=1), "unknown keys"),
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
