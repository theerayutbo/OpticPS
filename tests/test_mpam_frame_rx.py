"""M-PAM frame, export and validator (v1.3-mpam C5).

Expected values are written out from the arithmetic of the plan (counts per level, head
lengths, sample counts, DAC steps), not read back from the code under test.
"""

import copy
import csv
import json
import math
import shutil
import zlib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.instruments.m8199b import M8199BConstraintError
from opticps.measurement.validate_export import (
    levels_of,
    manifest_schema,
    validate_profile,
)
from opticps.modulation.pam import (
    ModulationSpec,
    bits_to_indices,
    gray_labels,
    indices_to_bits,
    label_bits,
    pam_levels,
)
from opticps.optimization.adaptive import estimate_channel, fixed_menu
from opticps.optimization.constraints import FeasibilityStatus
from opticps.transmitter.export import (
    MANIFEST_COLUMNS,
    MANIFEST_COLUMNS_V2,
    dac_quantize,
    generate_mpam_all,
)
from opticps.transmitter.frame import (
    Frame,
    build_frame,
    payload_rng,
    preamble_indices,
    training_indices,
)
from opticps.transmitter.mpam_config import (
    MpamProfile,
    check_frame_fit,
    dac_codes_per_level_step,
    frame_length_rows,
    load_mpam_config,
    rate_equalisation,
)

CONFIG = Path("configs/mpam_profiles.yaml")
TRAINING = {2: 512, 4: 512, 8: 1536, 16: 2560}
PER_LEVEL = {2: 256, 4: 128, 8: 192, 16: 160}
BITS = {2: 1, 4: 2, 8: 3, 16: 4}


def independent_bits(counts):
    ways = math.factorial(sum(counts))
    for c in counts:
        ways //= math.factorial(c)
    return ways.bit_length() - 1


# ------------------------------------------------------------------ modulation and frame head


@pytest.mark.parametrize("order", [2, 4, 8, 16])
def test_levels_spacing_gray_and_spec(order):
    spec = ModulationSpec(order)
    assert list(pam_levels(order)) == [2 * i - (order - 1) for i in range(order)]
    assert list(levels_of(order)) == list(pam_levels(order))  # the validator's own formula
    assert spec.bits_per_symbol == BITS[order] and spec.name == f"PAM{order}"
    assert spec.full_scale_levels == order - 1 and np.all(np.diff(spec.levels) == 2)
    labels = gray_labels(order)
    assert sorted(labels.tolist()) == list(range(order))  # a permutation of the labels
    assert all(
        bin(int(a) ^ int(b)).count("1") == 1 for a, b in zip(labels, labels[1:], strict=False)
    )
    # the bit table is the binary expansion of the label, most significant bit first
    for lab, row in zip(labels.tolist(), label_bits(order).tolist(), strict=True):
        assert int("".join(map(str, row)), 2) == lab and len(row) == BITS[order]
    assert (spec.training_symbols, spec.training_per_level) == (TRAINING[order], PER_LEVEL[order])
    assert spec.head_symbols == 512 + TRAINING[order] and spec.head_symbols % 1024 == 0
    assert spec.label_bits.shape == (order, BITS[order])
    with pytest.raises(FrozenInstanceError):
        spec.order = 8  # type: ignore[misc]  # frozen
    for bad in (1, 3, 5, 6, 32):
        with pytest.raises(ValueError):
            ModulationSpec(bad)
    # defaults keep the old PAM4 calls working
    assert list(pam_levels()) == [-3, -1, 1, 3] and gray_labels().tolist() == [0, 1, 3, 2]


@pytest.mark.parametrize("order", [2, 4, 8, 16])
def test_preamble_and_training_counts(order):
    pre = preamble_indices(order)
    assert pre.size == 512 and set(np.unique(pre).tolist()) == {0, order - 1}
    assert (pre == 0).sum() == (pre == order - 1).sum() == 256
    train = training_indices(42, order)
    assert train.size == TRAINING[order]
    assert np.bincount(train, minlength=order).tolist() == [PER_LEVEL[order]] * order
    assert (512 + train.size) % 1024 == 0
    assert np.array_equal(train, training_indices(42, order))  # deterministic
    assert not np.array_equal(train, training_indices(43, order))
    # M = 4 is the v1.2 head: chips x 3, 128 of each level
    if order == 4:
        chips = (pre // 3).tolist()
        assert pre.tolist() == [3 * c for c in chips]


@pytest.mark.parametrize("order", [2, 8, 16])
def test_direct_uniform_round_trip_and_bit_count(order):
    total = 2048 * (order // 2 + 1) + 1024
    frame = build_frame(f"PAM{order}_Uniform", None, total, 42, direct_uniform=True, order=order)
    head = 512 + TRAINING[order]
    payload = frame.payload_indices
    assert frame.order == order and frame.payload_start == head
    assert payload.size == total - head and payload.size % 1024 == 0
    assert frame.info_bits.size == BITS[order] * payload.size  # log2 M bits per symbol, no matcher
    assert frame.bits_per_block == BITS[order] * 1024 and frame.matcher_counts is None
    assert frame.distribution_matcher_rate == BITS[order]
    # the Gray label bits of the payload are exactly the information bits, and back
    assert np.array_equal(indices_to_bits(payload, order), frame.info_bits)
    assert np.array_equal(bits_to_indices(frame.info_bits, order), payload)
    # independent bit derivation: label of each symbol is its Gray code
    labels = [int(x) ^ (int(x) >> 1) for x in payload]
    rebuilt = "".join(format(lab, f"0{BITS[order]}b") for lab in labels)
    assert rebuilt == "".join(map(str, frame.info_bits.tolist()))
    # the payload stream key is crc32 of the waveform name
    rng = np.random.default_rng([42, zlib.crc32(f"PAM{order}_Uniform".encode())])
    assert np.array_equal(
        frame.info_bits, rng.integers(0, 2, BITS[order] * payload.size, dtype=np.int8)
    )
    assert np.array_equal(
        frame.indices,
        build_frame(
            f"PAM{order}_Uniform", None, total, 42, direct_uniform=True, order=order
        ).indices,
    )


def test_pam4_direct_uniform_is_the_v12_stream():
    frame = build_frame("PAM4_Uniform", None, 32768, 42, direct_uniform=True)
    payload_length = 32768 - 1024
    expected = payload_rng(42, "PAM4_Uniform").integers(0, 2, 2 * payload_length, dtype=np.int8)
    assert np.array_equal(frame.info_bits, expected) and frame.order == 4
    assert np.array_equal(frame.payload_indices, bits_to_indices(expected))
    assert [f.name for f in fields(Frame)][-1] == "order"
    assert next(f for f in fields(Frame) if f.name == "order").default == 4


@pytest.mark.parametrize("order", [8, 16])
def test_shaped_round_trip_through_ccdm(order):
    name, pmf = next(
        (n, p)
        for n, p in fixed_menu(order).items()
        if n.endswith(f"Inner_H{round(100 * (math.log2(order) - 0.28))}")
    )
    frame = build_frame(name, pmf, 512 + TRAINING[order] + 3 * 1024, 7, order=order)
    counts = frame.matcher_counts
    assert counts is not None and sum(counts) == 1024
    assert list(counts) == list(counts[::-1])  # symmetric composition, no split pair
    matcher = ConstantCompositionMatcher(counts)
    assert frame.bits_per_block == matcher.k == independent_bits(counts)
    payload = frame.payload_indices.reshape(frame.n_blocks, 1024)
    bits = frame.info_bits.reshape(frame.n_blocks, matcher.k)
    for block, info in zip(payload, bits, strict=True):
        assert np.bincount(block, minlength=order).tolist() == list(counts)  # constant composition
        assert np.array_equal(matcher.decode(block), info)
    assert frame.n_blocks == 3 and frame.order == order


def test_seed_and_name_determinism():
    a = build_frame("PAM8_Uniform", None, 4096, 1, direct_uniform=True, order=8)
    b = build_frame("PAM8_Uniform", None, 4096, 1, direct_uniform=True, order=8)
    c = build_frame("PAM8_Uniform", None, 4096, 2, direct_uniform=True, order=8)
    d = build_frame("PAM8_BestFixed", None, 4096, 1, direct_uniform=True, order=8)
    assert np.array_equal(a.indices, b.indices) and np.array_equal(a.info_bits, b.info_bits)
    assert not np.array_equal(a.indices[2048:], c.indices[2048:])
    assert not np.array_equal(a.indices[:2048], c.indices[:2048])  # training depends on the seed
    assert np.array_equal(a.indices[:2048], d.indices[:2048])  # the head is common to all waveforms
    assert not np.array_equal(a.indices[2048:], d.indices[2048:])  # the payload stream is per name


def test_frame_rejects_bad_lengths_and_orders():
    with pytest.raises(ValueError, match="multiple of 1024"):
        build_frame("x", None, 2048 + 1000, 1, direct_uniform=True, order=8)
    with pytest.raises(ValueError):
        build_frame("x", None, 2048, 1, direct_uniform=True, order=8)  # empty payload
    with pytest.raises(ValueError):
        build_frame("x", None, 4096, 1, direct_uniform=True, order=6)


# ------------------------------------------------------------------ DAC step


@pytest.mark.parametrize(
    ("order", "step"), [(2, 254.0), (4, 508 / 6), (8, 254 / 7), (16, 254 / 15)]
)
def test_dac_codes_per_level_step_at_8_bit(order, step):
    """Adjacent levels are 2 / (M - 1) apart on [-1, 1]; one unit is 127 codes (8-bit mid-tread)."""
    assert dac_codes_per_level_step(order, order - 1) == pytest.approx(step, rel=1e-12)
    assert step == pytest.approx(2 * 127 / (order - 1))
    # against the DAC model itself: codes of adjacent levels differ by the step, up to rounding
    x = (pam_levels(order) / (order - 1)).astype(float)
    codes = np.round(dac_quantize(x) * 127).astype(int)
    assert all(abs(d - step) <= 1.0 for d in np.diff(codes))
    assert codes[-1] - codes[0] == 254  # outer levels at +-127 codes
    assert dac_codes_per_level_step(order, order - 1, bits=12) == pytest.approx(
        2 * 2047 / (order - 1)
    )


# ------------------------------------------------------------------ sps, rates, lengths


def test_sps_and_rate_arithmetic_of_the_profiles():
    config = load_mpam_config(CONFIG)
    assert config.sample_rate == 224e9 and config.seed == 42 and config.block_length == 1024
    by_name = {p.name: p for p in config.profiles}
    assert len(by_name) == len(config.profiles) == 12  # 2 protocol A rates + protocol B, 4 orders
    for order in (2, 4, 8, 16):
        a8, a56 = by_name[f"A_8GBd_PAM{order}"], by_name[f"A_56GBd_PAM{order}"]
        assert (a8.sps, a56.sps) == (28, 4)  # 224 / 8, 224 / 56
        assert (a8.symbols, a56.symbols) == (32768, 65536)
        b = by_name[f"B_112G_PAM{order}"]
        assert b.sps == {2: 2, 4: 4, 8: 6, 16: 8}[order]
        assert b.symbol_rate * BITS[order] == pytest.approx(112e9, rel=1e-12)  # nominal 112 Gb/s
        assert b.symbol_rate * b.sps == pytest.approx(224e9, rel=1e-12)
    assert by_name["B_112G_PAM8"].symbol_rate == pytest.approx(112e9 / 3)


def test_frame_length_table_fits_every_m8199b_rule():
    expected = {  # (profile): (symbols, sps, samples, head, payload)
        "A_8GBd_PAM2": (32768, 28, 917504, 1024, 31744),
        "A_8GBd_PAM4": (32768, 28, 917504, 1024, 31744),
        "A_8GBd_PAM8": (32768, 28, 917504, 2048, 30720),
        "A_8GBd_PAM16": (32768, 28, 917504, 3072, 29696),
        "A_56GBd_PAM2": (65536, 4, 262144, 1024, 64512),
        "A_56GBd_PAM4": (65536, 4, 262144, 1024, 64512),
        "A_56GBd_PAM8": (65536, 4, 262144, 2048, 63488),
        "A_56GBd_PAM16": (65536, 4, 262144, 3072, 62464),
        "B_112G_PAM2": (131072, 2, 262144, 1024, 130048),
        "B_112G_PAM4": (65536, 4, 262144, 1024, 64512),
        "B_112G_PAM8": (43008, 6, 258048, 2048, 40960),
        "B_112G_PAM16": (32768, 8, 262144, 3072, 29696),
    }
    rows = {r["profile"]: r for r in frame_length_rows(load_mpam_config(CONFIG))}
    assert set(rows) == set(expected)
    for name, (symbols, sps, samples, head, payload) in expected.items():
        r = rows[name]
        assert (r["symbols"], r["samples_per_symbol"], r["samples"]) == (symbols, sps, samples)
        assert (r["head_symbols"], r["payload_symbols"]) == (head, payload)
        assert symbols * sps == samples and samples % 512 == 0 and samples <= 1_048_576
        assert head % 1024 == 0 and payload % 1024 == 0
        assert r["status"] == "FEASIBLE"


def test_infeasible_frames_are_reported_not_trimmed():
    rate = 224e9
    too_long = MpamProfile("A", "x", 16, rate, 8e9, 40000)  # 40000 x 28 = 1.12 M samples
    result = check_frame_fit(16, too_long)
    assert result.status is FeasibilityStatus.INFEASIBLE
    assert "1120000 samples exceed" in result.reason
    # payload not a multiple of the block, and a sample count that is not a multiple of 512
    odd = check_frame_fit(8, MpamProfile("A", "y", 8, rate, 56e9, 4096 + 1000))
    assert odd.status is FeasibilityStatus.INFEASIBLE and "positive multiple of 1024" in odd.reason
    # any valid frame has symbols a multiple of 1024, so its sample count is a multiple of 512 x 2
    for k in range(3, 40):
        fit = check_frame_fit(8, MpamProfile("A", "k", 8, rate, 56e9, 1024 * k))
        assert fit.status is FeasibilityStatus.FEASIBLE and (1024 * k * 4) % 512 == 0
    # the sample rate range and an integer sps
    fast = check_frame_fit(2, MpamProfile("A", "f", 2, 260e9, 56e9, 4096))
    assert fast.status is FeasibilityStatus.INFEASIBLE and "outside 200 to 256" in fast.reason
    frac = check_frame_fit(2, MpamProfile("A", "g", 2, 224e9, 50e9, 4096))
    assert frac.status is FeasibilityStatus.INFEASIBLE and "not an integer" in frac.reason
    # the real profiles are all fine, so the generator would not trim anything
    assert check_frame_fit(16, MpamProfile("A", "ok", 16, rate, 8e9, 32768)).status is (
        FeasibilityStatus.FEASIBLE
    )


# ------------------------------------------------------------------ realised-rate equalisation


def test_equalisation_is_reported_never_applied_and_ps80_class_is_infeasible_at_pam4():
    rows = {r["name"]: r for r in rate_equalisation(4, fixed_menu(4), 32768, 28)}
    # direct uniform = 2048 bits per 1024-symbol block; PS70 carries 1912, PS80 1747
    assert (
        independent_bits([154, 358, 358, 154]) == 1912
        or rows["PAM4_Fixed_PS70"]["bits_per_block"] == 1912
    )
    assert rows["PAM4_Fixed_PS70"]["bits_per_block"] == 1912
    assert rows["PAM4_Fixed_PS80"]["bits_per_block"] == 1747
    assert rows["PAM4_Uniform"]["bits_per_block"] == 2048
    assert rows["PAM4_Fixed_PS70"]["required_increase"] == pytest.approx(2048 / 1912 - 1, rel=1e-12)
    assert rows["PAM4_Fixed_PS80"]["required_increase"] == pytest.approx(2048 / 1747 - 1, rel=1e-12)
    assert rows["PAM4_Fixed_PS70"]["status"] == "FEASIBLE"  # +7.1 % is below +14.3 %
    assert rows["PAM4_Fixed_PS80"]["status"] == "INFEASIBLE"  # +17.2 % is above +14.3 %
    assert rows["PAM4_Uniform"]["status"] == "FEASIBLE" and rows["PAM4_Uniform"][
        "required_increase"
    ] in (None, 0.0)
    assert all(r["applied"] is False for r in rows.values())


@pytest.mark.parametrize("order", [8, 16])
def test_equalisation_rows_follow_independent_bit_counts(order):
    menu = fixed_menu(order)
    symbols = 32768
    rows = {r["name"]: r for r in rate_equalisation(order, menu, symbols, 6)}
    uniform_bits = BITS[order] * 1024
    for name, pmf in menu.items():
        if name.endswith("Uniform"):
            assert rows[name]["bits_per_block"] == uniform_bits
            continue
        counts = ConstantCompositionMatcher.from_symmetric_probabilities(pmf, 1024).counts
        bits = independent_bits(counts)
        ratio = uniform_bits / bits  # the head is common, so the ratio is the bit ratio
        assert rows[name]["bits_per_block"] == bits
        assert rows[name]["required_increase"] == pytest.approx(ratio - 1, rel=1e-12)
        assert (rows[name]["status"] == "FEASIBLE") == (ratio <= 256 / 224)
        assert rows[name]["applied"] is False


# ------------------------------------------------------------------ export, manifest, validator


def small_config(tmp_path: Path, symbols: dict[int, int] | None = None) -> Path:
    """The M-PAM config with short protocol-B frames, for fast tests."""
    config = yaml.safe_load(CONFIG.read_text())
    config["protocol_B"]["symbols"] = symbols or {2: 2048, 4: 4096, 8: 4096, 16: 4096}
    config["adaptive"]["training_samples"] = 6000
    config["adaptive"]["training_acquisitions"] = 1
    path = tmp_path / "mpam.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mpam")
    path = small_config(tmp)
    out = tmp / "out"
    rows = generate_mpam_all(path, out, orders=(2, 8), protocols=("B",))
    return path, out, rows


def read_manifest(folder: Path):
    with (folder / "experiment_manifest.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def test_v2_manifest_columns_rows_and_evidence(exported):
    path, out, rows = exported
    assert set(rows) == {"B_112G_PAM2", "B_112G_PAM8"}
    folder = out / "B_112G_PAM8"
    manifest, columns = read_manifest(folder)
    assert columns == MANIFEST_COLUMNS_V2
    for needed in (
        "manifest_schema_version", "modulation_order", "bits_per_symbol", "probabilities",
        "realised_probabilities", "shaping_family", "shaping_parameter", "entropy_target_bits",
        "constraint_protocol", "level_spacing_full_scale", "head_symbols",
        "dac_codes_per_level_step", "evidence",
    ):  # fmt: skip
        assert needed in columns
    names = [Path(r["waveform_filename"]).stem for r in manifest]
    assert names == [
        "PAM8_Uniform", "PAM8_Fixed_Inner_H288", "PAM8_Fixed_Inner_H272",
        "PAM8_Fixed_Outer_H288", "PAM8_Fixed_Outer_H272", "PAM8_Adaptive", "PAM8_BestFixed",
    ]  # fmt: skip
    for r in manifest:
        assert r["manifest_schema_version"] == "2" and r["modulation_order"] == "8"
        assert r["bits_per_symbol"] == "3" and r["evidence"] == "simulated"
        assert r["head_symbols"] == "2048" and r["training_symbols"] == "1536"
        assert r["samples_per_symbol"] == "6" and r["sample_rate_Sa_per_s"] == "224000000000"
        assert (
            len(json.loads(r["probabilities"])) == 8
            and len(json.loads(r["realised_probabilities"])) == 8
        )
        assert float(r["level_spacing_full_scale"]) == pytest.approx(2 / 7, abs=1e-9)
        assert float(r["dac_codes_per_level_step"]) == pytest.approx(254 / 7, abs=1e-6)
        assert r["constraint_protocol"] == "fixed_peak"
        assert r["payload_stream_key"] == str(
            zlib.crc32(r["waveform_filename"].split("/")[-1][:-4].encode())
        )
        assert r["training_stream_key"] == str(0x7A11)
    # PAM4 keeps its 40 columns and schema (the byte anchor pins the content)
    assert len(MANIFEST_COLUMNS) == 40 and "manifest_schema_version" not in MANIFEST_COLUMNS
    # metadata carries the stream keys
    meta = json.loads((folder / "references/PAM8_Adaptive/PAM8_Adaptive_metadata.json").read_text())
    assert meta["stream_keys"]["payload"] == zlib.crc32(b"PAM8_Adaptive")
    assert meta["stream_keys"]["training"] == 0x7A11
    assert meta["stream_keys"]["selection"] == {
        "simulated_payload": 1, "simulated_noise": 2, "dirichlet_starts": 3,
    }  # fmt: skip
    assert meta["evidence"] == "simulated" and meta["modulation_order"] == 8


def test_uniform_carries_log2_m_bits_per_symbol_and_no_matcher(exported):
    _, out, _ = exported
    for folder_name, order, symbols, sps in (
        ("B_112G_PAM8", 8, 4096, 6),
        ("B_112G_PAM2", 2, 2048, 2),
    ):
        manifest, _ = read_manifest(out / folder_name)
        row = next(r for r in manifest if r["waveform_filename"].endswith("Uniform.csv"))
        payload = symbols - (512 + TRAINING[order])
        assert int(row["payload_symbols"]) == payload
        assert int(row["payload_information_bits"]) == BITS[order] * payload
        assert float(row["distribution_matcher_rate"]) == BITS[order]
        assert float(row["distribution_matcher_rate_loss"]) == 0.0
        duration = symbols * sps / 224e9
        assert float(row["actual_net_payload_rate_bps"]) == pytest.approx(
            BITS[order] * payload / duration, rel=1e-6
        )
        assert int(row["number_of_samples"]) == symbols * sps
    meta = json.loads(
        (out / "B_112G_PAM8/references/PAM8_Uniform/PAM8_Uniform_metadata.json").read_text()
    )
    assert (
        meta["frame"]["matcher_composition"] is None
        and meta["rate_equalisation"]["status"] == "FEASIBLE"
    )
    assert meta["rate_equalisation"]["applied"] is False


def test_equalisation_never_changes_the_exported_sample_rate(exported):
    _, out, _ = exported
    manifest, _ = read_manifest(out / "B_112G_PAM8")
    assert {r["sample_rate_Sa_per_s"] for r in manifest} == {"224000000000"}
    for r in manifest:
        assert int(r["number_of_samples"]) == int(r["number_of_symbols"]) * 6


def test_exported_packages_validate(exported):
    _, out, _ = exported
    for name in ("B_112G_PAM8", "B_112G_PAM2"):
        results = validate_profile(out / name)
        failed = [c for c in results if not c.passed]
        assert not failed, failed
        checks = {c.check for c in results}
        assert {
            "modulation_matches_manifest_row", "head_multiple_of_1024",
            "training_balanced_per_level", "preamble_balanced", "reference_levels",
            "level_spacing_and_dac_step", "noise_free_reconstruction", "evidence_label",
        } <= checks  # fmt: skip
    results = validate_profile(out / "B_112G_PAM8")
    assert any(c.check == "ccdm_inverse_recovers_bits" and c.passed for c in results)


def test_all_waveforms_are_in_range_and_headers_are_dataout1(exported):
    _, out, _ = exported
    for path in (out / "B_112G_PAM8" / "waveforms").rglob("*.csv"):
        lines = path.read_text().splitlines()
        assert lines[0] == "DataOut1"
        values = np.array([float(x) for x in lines[1:]])
        assert values.size % 512 == 0 and np.abs(values).max() <= 1.0
    assert (out / "adaptive_selection_PAM8.json").exists()


def copy_package(exported, tmp_path: Path, name: str = "B_112G_PAM8") -> Path:
    _, out, _ = exported
    dest = tmp_path / name
    shutil.copytree(out / name, dest)
    return dest


def rewrite_manifest(folder: Path, edit) -> None:
    manifest, columns = read_manifest(folder)
    columns, manifest = edit(columns, manifest)
    with (folder / "experiment_manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest)


def failed_checks(results):
    return {c.check for c in results if not c.passed}


def test_unknown_schema_version_is_refused(exported, tmp_path):
    folder = copy_package(exported, tmp_path)

    def edit(columns, rows):
        for r in rows:
            r["manifest_schema_version"] = "3"
        return columns, rows

    rewrite_manifest(folder, edit)
    results = validate_profile(folder)
    assert failed_checks(results) == {"manifest_schema_known"} and len(results) == 1


@pytest.mark.parametrize("damage", ["drop_column", "extra_column", "reorder", "empty_version"])
def test_wrong_column_list_is_refused(exported, tmp_path, damage):
    folder = copy_package(exported, tmp_path)

    def edit(columns, rows):
        if damage == "drop_column":
            columns = [c for c in columns if c != "head_symbols"]
            for r in rows:
                del r["head_symbols"]
        elif damage == "extra_column":
            columns = [*columns, "surprise"]
            for r in rows:
                r["surprise"] = "1"
        elif damage == "reorder":
            columns = [columns[1], columns[0], *columns[2:]]
        else:
            for r in rows:
                r["manifest_schema_version"] = ""
        return columns, rows

    rewrite_manifest(folder, edit)
    assert failed_checks(validate_profile(folder)) == {"manifest_schema_known"}


def test_unknown_columns_without_a_version_are_refused(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "experiment_manifest.csv").write_text("a,b\n1,2\n")
    (folder / "checksums.sha256").write_text("")
    assert failed_checks(validate_profile(folder)) == {"manifest_schema_known"}
    assert manifest_schema(None, []) is None
    assert manifest_schema(list(MANIFEST_COLUMNS), []) == 1
    assert manifest_schema(list(MANIFEST_COLUMNS_V2), []) is None  # v2 needs a row that says 2


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        (
            "modulation_order",
            "16",
            {"modulation_matches_manifest_row", "modulation_order_matches_metadata"},
        ),
        ("modulation_order", "6", {"modulation_order_known"}),
        ("modulation", "PAM4", {"modulation_matches_manifest_row"}),
        ("bits_per_symbol", "2", {"modulation_matches_manifest_row"}),
        ("evidence", "measured-ish", {"evidence_label", "modulation_order_matches_metadata"}),
        ("head_symbols", "1024", {"head_symbols_manifest"}),
        ("training_symbols", "512", {"head_symbols_manifest"}),
        ("level_spacing_full_scale", "0.5", {"level_spacing_and_dac_step"}),
        ("dac_codes_per_level_step", "85.0", {"level_spacing_and_dac_step"}),
        ("entropy_target_bits", "2.0", {"entropy_target_matches_probabilities"}),
    ],
)
def test_row_tampering_is_caught_by_the_named_check(exported, tmp_path, column, value, expected):
    folder = copy_package(exported, tmp_path)

    def edit(columns, rows):
        rows[0][column] = value
        return columns, rows

    rewrite_manifest(folder, edit)
    failed = failed_checks(validate_profile(folder))
    assert expected <= failed, (failed, expected)


def test_metadata_order_mismatch_and_head_damage_are_caught(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    meta_path = folder / "references/PAM8_Uniform/PAM8_Uniform_metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["modulation_order"] = 16
    meta_path.write_text(json.dumps(meta))
    assert "modulation_order_matches_metadata" in failed_checks(validate_profile(folder))
    # a training symbol changed to another level breaks the per-level balance
    folder2 = copy_package(exported, tmp_path / "second")
    symbols = folder2 / "references/PAM8_Uniform/PAM8_Uniform_symbols.csv"
    lines = symbols.read_text().splitlines()
    index_of = [int(line.split(",")[1]) for line in lines[1 + 512 : 1 + 2048]]
    assert index_of[0] != index_of[1]  # seed 42: the first two training symbols differ
    lines[1 + 512] = f"512,{index_of[1]},{levels_of(8)[index_of[1]]:+d}"
    symbols.write_text("\n".join(lines) + "\n")
    assert "training_balanced_per_level" in failed_checks(validate_profile(folder2))


def test_preamble_not_on_outer_levels_of_this_order_fails(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    symbols = folder / "references/PAM8_Uniform/PAM8_Uniform_symbols.csv"
    lines = symbols.read_text().splitlines()
    # an index-3 symbol in the preamble (a PAM4 outer level) must not pass for PAM8
    lines[1] = f"0,3,{levels_of(8)[3]:+d}"
    symbols.write_text("\n".join(lines) + "\n")
    assert "preamble_balanced" in failed_checks(validate_profile(folder))


def test_v1_manifest_still_validates_as_schema_1():
    columns = list(MANIFEST_COLUMNS)
    assert manifest_schema(columns, []) == 1 and len(columns) == 40


def test_generation_refuses_infeasible_profiles_and_writes_nothing(tmp_path):
    config = yaml.safe_load(CONFIG.read_text())
    config["protocol_A"]["profiles"][0]["symbols"] = 40000  # 8 GBd, sps 28: 1.12 M samples
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config))
    out = tmp_path / "out"
    with pytest.raises(M8199BConstraintError, match="INFEASIBLE"):
        generate_mpam_all(path, out, orders=(16,), protocols=("A",))
    assert not out.exists() or not any(out.iterdir())
    rows = {r["profile"]: r for r in frame_length_rows(load_mpam_config(path))}
    assert rows["A_8GBd_PAM16"]["status"] == "INFEASIBLE"
    assert rows["A_56GBd_PAM16"]["status"] == "FEASIBLE"


def test_generation_is_deterministic(tmp_path):
    path = small_config(tmp_path, {2: 2048, 4: 4096, 8: 4096, 16: 4096})
    a = generate_mpam_all(path, tmp_path / "a", orders=(2,), protocols=("B",))
    b = generate_mpam_all(path, tmp_path / "b", orders=(2,), protocols=("B",))
    assert a == b
    first = (tmp_path / "a/B_112G_PAM2/waveforms/PAM2_Uniform.csv").read_bytes()
    assert first == (tmp_path / "b/B_112G_PAM2/waveforms/PAM2_Uniform.csv").read_bytes()


# ------------------------------------------------------------------ training length at M = 16


def relative_sigma_errors(order: int, per_level: int, trials: int, seed: int) -> np.ndarray:
    """sigma_hat / sigma - 1 for every level over `trials` unit-variance training blocks."""
    rng = np.random.default_rng(seed)
    indices = np.repeat(np.arange(order), per_level)
    errors = []
    for _ in range(trials):
        estimate = estimate_channel(indices, rng.normal(0.0, 1.0, indices.size), order)
        errors.extend(np.array(estimate.sigmas) - 1.0)
    return np.array(errors)


def test_training_length_sets_the_sigma_estimate_error_near_the_plan_figure():
    """The plan quotes +-5.6 % for PAM16 with 160 symbols per level. For Gaussian samples the
    relative standard deviation of the sample sigma is 1 / sqrt(2 (N - 1)) = 5.61 % at N = 160:
    it is a one-sigma figure, not a bound (the 95 % half width is about 11 %). Measured here
    by simulation with the repository's own estimator, 1200 blocks x 16 levels."""
    measured = {}
    for order, per_level in ((16, 160), (8, 192), (4, 128)):
        errors = relative_sigma_errors(order, per_level, 1200, 5)
        measured[(order, per_level)] = float(errors.std())
        theory = 1.0 / math.sqrt(2 * (per_level - 1))
        assert measured[(order, per_level)] == pytest.approx(theory, rel=0.04)
    assert measured[(16, 160)] == pytest.approx(0.056, abs=0.003)
    # the shorter 512-symbol head would give 32 symbols per level at PAM16: more than twice as bad
    short = float(relative_sigma_errors(16, 32, 600, 6).std())
    assert short == pytest.approx(1 / math.sqrt(62), rel=0.05) and short > 2 * measured[(16, 160)]
    errors = relative_sigma_errors(16, 160, 600, 7)
    half_width = float(np.percentile(np.abs(errors), 95))
    assert 0.095 < half_width < 0.125  # about two sigma: the 95 % interval is +-11 %, not +-5.6 %


# ------------------------------------------------------------------ PAM16 end to end (slow)


@pytest.mark.slow
def test_pam16_export_validates_and_head_is_3072(tmp_path):
    path = small_config(tmp_path, {2: 2048, 4: 4096, 8: 4096, 16: 5120})
    out = tmp_path / "out"
    generate_mpam_all(path, out, orders=(16,), protocols=("B",))
    folder = out / "B_112G_PAM16"
    manifest, columns = read_manifest(folder)
    assert columns == MANIFEST_COLUMNS_V2
    assert {r["head_symbols"] for r in manifest} == {"3072"}
    assert {r["samples_per_symbol"] for r in manifest} == {"8"}
    assert not failed_checks(validate_profile(folder))
    assert copy.deepcopy(manifest)[0]["bits_per_symbol"] == "4"
