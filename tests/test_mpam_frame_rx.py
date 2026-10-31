"""M-PAM frame, export and validator (v1.3-mpam C5).

Expected values are written out from the arithmetic of the plan (counts per level, head
lengths, sample counts, DAC steps), not read back from the code under test.
"""

import copy
import csv
import dataclasses
import json
import math
import shutil
import zlib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.cli.main import main as cli_main
from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.instruments.m8199b import M8199BConstraintError
from opticps.measurement.validate_export import (
    EXPECTED_TARGETS,
    SCALE_TOLERANCE,
    expected_names,
    expected_preamble,
    levels_of,
    manifest_schema,
    pinned_menu,
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
from opticps.optimization.adaptive import (
    BaselineOverrideError,
    BestFixed,
    best_fixed,
    estimate_channel,
    fixed_menu,
    simulate_acquisitions,
)
from opticps.optimization.constraints import FeasibilityStatus
from opticps.transmitter.export import (
    MANIFEST_COLUMNS,
    MANIFEST_COLUMNS_V2,
    _is_uniform,
    dac_quantize,
    generate_mpam_all,
    generate_mpam_profile,
    mpam_waveforms,
    select_for_order,
    sha256_file,
)
from opticps.transmitter.frame import (
    Frame,
    build_frame,
    make_matcher,
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
    pam4_uniform_rate_bps,
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
    # a header-only manifest is no package, in either schema (default-deny)
    assert manifest_schema(list(MANIFEST_COLUMNS), []) is None
    assert manifest_schema(list(MANIFEST_COLUMNS_V2), []) is None


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
    row = dict.fromkeys(columns, "x")
    assert manifest_schema(columns, [row]) == 1 and len(columns) == 40
    assert manifest_schema(columns, []) is None  # header only: no package
    for folder in sorted(Path("output/keysight_m8199b").iterdir()):
        if folder.is_dir():
            with (folder / "experiment_manifest.csv").open(newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                assert manifest_schema(list(reader.fieldnames or []), rows) == 1


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


# ------------------------------------------------------------------ review round: helpers


def refresh(folder: Path) -> None:
    """Recompute every hash a package keeps, as an honest rewrite of the files would."""
    manifest, columns = read_manifest(folder)
    for r in manifest:
        name = Path(r["waveform_filename"]).stem
        r["waveform_sha256"] = sha256_file(folder / r["waveform_filename"])
        r["reference_sha256"] = sha256_file(folder / "references" / name / f"{name}_symbols.csv")
    rewrite_manifest(folder, lambda c, _rows: (c, manifest))
    skip = {"checksums.sha256", "validation_results.csv"}
    lines = [
        f"{sha256_file(path)}  {path.relative_to(folder).as_posix()}"
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name not in skip
    ]
    (folder / "checksums.sha256").write_text("\n".join(lines) + "\n")


def edit_metadata(folder: Path, name: str, edit) -> None:
    path = folder / "references" / name / f"{name}_metadata.json"
    meta = json.loads(path.read_text())
    edit(meta)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def edit_row(folder: Path, index: int, **changes: str) -> None:
    def edit(columns, rows):
        rows[index].update(changes)
        return columns, rows

    rewrite_manifest(folder, edit)


def wave_lines(folder: Path, name: str) -> list[str]:
    return (folder / f"waveforms/{name}.csv").read_text().splitlines()


def write_wave(folder: Path, name: str, lines: list[str]) -> None:
    (folder / f"waveforms/{name}.csv").write_text("\n".join(lines) + "\n")


IDX = {name: i for i, name in enumerate(expected_names(2, 8))}
PAM8_NAMES = expected_names(2, 8)


# ------------------------------------------------------------------ finding 1: reportable


@pytest.fixture(scope="module")
def pam8(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pam8")
    path = small_config(tmp)
    config = load_mpam_config(path)
    profile = next(p for p in config.profiles if p.name == "B_112G_PAM8")
    return config, profile, select_for_order(config, 8)


def hand_built(name: str, pmf, *, order: int = 8, **kwargs) -> BestFixed:
    return BestFixed(name, list(pmf), 0.0, "bmd", 1024, order, [], "hand built", **kwargs)


def nothing_written(root: Path) -> bool:
    return not root.exists() or not any(root.iterdir())


def test_a_directly_built_best_fixed_is_not_reportable():
    assert hand_built("PAM8_Uniform", fixed_menu(8)["PAM8_Uniform"]).reportable is False
    assert "NON-REPORTABLE" in hand_built("X", [0.125] * 8).reportable_reason


def test_the_qa_repro_is_refused_by_the_export(pam8, tmp_path):
    """A best-fixed chosen from a menu that is not the pinned one must not reach a package."""
    config, profile, choice = pam8
    train, _ = simulate_acquisitions(22.0, 8, 12000, 3, 1, 0)
    other = best_fixed(train, 8, "bmd", 1024, {"X": (0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2)})
    assert other.reportable is False and other.name == "X"
    with pytest.raises(BaselineOverrideError, match="reportable is False"):
        generate_mpam_profile(profile, config, dataclasses.replace(choice, best=other), tmp_path)
    assert nothing_written(tmp_path)


def test_every_way_of_faking_a_reportable_baseline_is_refused(pam8, tmp_path):
    config, profile, choice = pam8
    pinned = fixed_menu(8)
    inner, outer = pinned["PAM8_Fixed_Inner_H288"], pinned["PAM8_Fixed_Outer_H272"]
    cases = {
        "default flag": hand_built("PAM8_Fixed_Inner_H288", inner),
        "flag True, member not pinned": hand_built("X", inner, reportable=True),
        "flag True, pinned name, another PMF": hand_built(
            "PAM8_Fixed_Inner_H288", outer, reportable=True
        ),
        "pinned name and PMF, flag False": hand_built(
            "PAM8_Fixed_Inner_H288", inner, reportable=False
        ),
        "flag True, wrong order": hand_built(
            "PAM8_Fixed_Inner_H288", inner, order=16, reportable=True
        ),
        "flag True, PMF of the wrong length": hand_built(
            "PAM8_Fixed_Inner_H288", inner[:4], reportable=True
        ),
    }
    for label, best in cases.items():
        with pytest.raises(BaselineOverrideError, match="BestFixed"):
            mpam_waveforms(config, dataclasses.replace(choice, best=best), 8)
        with pytest.raises(BaselineOverrideError):
            generate_mpam_profile(profile, config, dataclasses.replace(choice, best=best), tmp_path)
        assert nothing_written(tmp_path), label


def test_a_uniform_best_fixed_and_a_uniform_adaptive_are_sent_as_direct_uniform(pam8, tmp_path):
    """Also accepts a best-fixed that is exactly a pinned member (no matcher for uniform)."""
    config, profile, choice = pam8
    uniform = tuple([0.125] * 8)
    best = hand_built("PAM8_Uniform", uniform, reportable=True)
    adaptive = dataclasses.replace(choice.adaptive, probabilities=list(uniform))
    chosen = dataclasses.replace(choice, best=best, adaptive=adaptive)
    waveforms = {w.name: w for w in mpam_waveforms(config, chosen, 8)}
    assert waveforms["PAM8_BestFixed"].direct and waveforms["PAM8_Adaptive"].direct
    assert not waveforms["PAM8_Fixed_Inner_H288"].direct
    rows = generate_mpam_profile(profile, config, chosen, tmp_path)
    for row in rows:
        if row["waveform_filename"].endswith(("BestFixed.csv", "Adaptive.csv")):
            assert row["reportable"] == "true" and float(row["distribution_matcher_rate"]) == 3.0
            assert float(row["distribution_matcher_rate_loss"]) == 0.0
    meta = json.loads(
        (
            tmp_path / "B_112G_PAM8/references/PAM8_BestFixed/PAM8_BestFixed_metadata.json"
        ).read_text()
    )
    assert meta["frame"]["matcher_composition"] is None
    assert meta["best_fixed"]["member"] == "PAM8_Uniform" and meta["best_fixed"]["reportable"]
    assert not failed_checks(validate_profile(tmp_path / "B_112G_PAM8"))


def test_is_uniform_has_a_tight_tolerance():
    assert _is_uniform([0.125] * 8, 8) and _is_uniform(
        (0.125 + 5e-13, 0.125 - 5e-13, *[0.125] * 6), 8
    )
    assert not _is_uniform((0.125 + 1e-9, 0.125 - 1e-9, *[0.125] * 6), 8)
    assert not _is_uniform(fixed_menu(8)["PAM8_Fixed_Inner_H288"], 8)
    assert not _is_uniform([0.125] * 8, 16)


def test_the_v2_manifest_has_the_literal_column_list_with_reportable():
    assert MANIFEST_COLUMNS_V2 == [
        "manifest_schema_version", "experiment_id", "role", "reportable", "waveform_filename",
        "data_out", "modulation", "modulation_order", "bits_per_symbol", "protocol",
        "shaping_mode", "shaping_family", "shaping_parameter", "probabilities",
        "realised_probabilities", "entropy_target_bits", "symbol_entropy_bits",
        "constraint_protocol", "symbol_rate_Bd", "sample_rate_Sa_per_s", "samples_per_symbol",
        "number_of_symbols", "preamble_symbols", "training_symbols", "head_symbols",
        "payload_symbols", "number_of_samples", "waveform_duration_s",
        "distribution_matcher_rate", "distribution_matcher_rate_loss",
        "payload_information_bits", "nominal_information_rate_bps",
        "actual_net_payload_rate_bps", "level_spacing_full_scale", "dac_codes_per_level_step",
        "pulse_shape", "amplitude_scale", "waveform_peak", "waveform_rms", "waveform_papr_db",
        "waveform_mean", "evidence", "random_seed", "payload_stream_key",
        "training_stream_key", "waveform_sha256", "reference_sha256",
    ]  # fmt: skip


def test_exported_rows_say_reportable_and_the_validator_fails_a_required_row_that_is_not(
    exported, tmp_path
):
    folder = copy_package(exported, tmp_path)
    manifest, _ = read_manifest(folder)
    assert {r["reportable"] for r in manifest} == {"true"}
    meta = json.loads(
        (folder / "references/PAM8_BestFixed/PAM8_BestFixed_metadata.json").read_text()
    )
    assert meta["best_fixed"]["reportable"] is True
    for value in ("false", "maybe", ""):
        edit_row(folder, IDX["PAM8_BestFixed"], reportable=value)
        refresh(folder)
        assert failed_checks(validate_profile(folder)) == {"reportable"}, value
    edit_row(folder, IDX["PAM8_Uniform"], reportable="false")
    refresh(folder)
    assert failed_checks(validate_profile(folder)) == {"reportable"}


# ------------------------------------------------------------------ finding 11: equalisation


def test_adaptive_and_best_fixed_report_the_equalisation_of_their_own_pmf(exported):
    """Not "not applicable": the real result for the PMF that was sent, from its composition."""
    _, out, _ = exported
    for name in ("PAM8_Adaptive", "PAM8_BestFixed"):
        meta = json.loads((out / f"B_112G_PAM8/references/{name}/{name}_metadata.json").read_text())
        equalisation = meta["rate_equalisation"]
        counts = meta["frame"]["matcher_composition"]
        assert isinstance(equalisation, dict) and equalisation["name"] == name
        assert equalisation["applied"] is False
        assert counts is not None  # both are shaped in this fixture
        bits = independent_bits(counts)
        assert equalisation["bits_per_block"] == bits
        ratio = 3 * 1024 / bits  # the direct uniform carries 3 bits per symbol
        assert equalisation["required_increase"] == pytest.approx(ratio - 1, rel=1e-12)
        assert equalisation["required_sample_rate_hz"] == pytest.approx(224e9 * ratio, rel=1e-12)
        assert (equalisation["status"] == "FEASIBLE") == (ratio <= 256 / 224)
        # 2 payload blocks of the 4096-symbol frame, 6 samples per symbol at 224 GSa/s
        assert equalisation["user_rate_bps"] == pytest.approx(
            224e9 / 6 * 2 * bits / 4096, rel=1e-12
        )


def test_uniform_net_rates_of_protocol_b_are_not_the_nominal_112_gbps():
    """112 Gb/s is a nominal label: the head costs 1024 to 3072 of each frame's symbols."""
    config = load_mpam_config(CONFIG)
    heads = {2: 1024, 4: 1024, 8: 2048, 16: 3072}
    symbols = {2: 131072, 4: 65536, 8: 43008, 16: 32768}
    sps = {2: 2, 4: 4, 8: 6, 16: 8}
    expected = {2: 111.125e9, 4: 110.25e9, 8: 106.6666667e9, 16: 101.5e9}
    for order in (2, 4, 8, 16):
        net = 224e9 / sps[order] * BITS[order] * (symbols[order] - heads[order]) / symbols[order]
        assert net == pytest.approx(expected[order], rel=1e-9)
        profile = next(p for p in config.profiles if p.name == f"B_112G_PAM{order}")
        rows = rate_equalisation(order, {"u": [1 / order] * order}, profile.symbols, profile.sps)
        assert rows[0]["user_rate_bps"] == pytest.approx(net, rel=1e-12)
    pam4 = next(p for p in config.profiles if p.name == "B_112G_PAM4")
    assert pam4_uniform_rate_bps(config, pam4) == pytest.approx(110.25e9, rel=1e-12)


def test_common_target_equalisation_is_the_pam4_uniform_net_rate():
    """Against the PAM4 uniform net rate (110.25 Gb/s) both PS80-class members, H272 and
    H372, are INFEASIBLE, not only the PAM4 one; the status comes from the arithmetic here."""
    config = load_mpam_config(CONFIG)
    target = 224e9 / 4 * 2 * 63 / 64  # PAM4: 63 of 64 blocks carry 2048 bits
    seen = {}
    for order in (4, 8, 16):
        profile = next(p for p in config.profiles if p.name == f"B_112G_PAM{order}")
        assert pam4_uniform_rate_bps(config, profile) == pytest.approx(target, rel=1e-12)
        menu = fixed_menu(order)
        rows = {
            r["name"]: r
            for r in rate_equalisation(
                order,
                menu,
                profile.symbols,
                profile.sps,
                target_bps=pam4_uniform_rate_bps(config, profile),
            )
        }
        for name, pmf in menu.items():
            if name.endswith("Uniform"):
                bits = BITS[order] * 1024
            else:
                counts = ConstantCompositionMatcher.from_symmetric_probabilities(pmf, 1024).counts
                bits = independent_bits(counts) if order > 4 else rows[name]["bits_per_block"]
            blocks = (profile.symbols - {4: 1024, 8: 2048, 16: 3072}[order]) // 1024
            rate = 224e9 / profile.sps * bits * blocks / profile.symbols
            needed = 224e9 * target / rate
            assert rows[name]["required_sample_rate_hz"] == pytest.approx(needed, rel=1e-9) or (
                name.endswith("Uniform") and order == 4
            )
            assert (rows[name]["status"] == "FEASIBLE") == (200e9 <= needed <= 256e9), name
            seen[name] = (round(needed / 1e9, 1), rows[name]["status"])
    assert seen["PAM8_Fixed_Inner_H272"] == (258.4, "INFEASIBLE")  # 258.35
    assert seen["PAM8_Fixed_Outer_H272"] == (258.1, "INFEASIBLE")
    assert seen["PAM16_Fixed_Inner_H372"] == (265.8, "INFEASIBLE")
    assert seen["PAM16_Fixed_Outer_H372"] == (265.8, "INFEASIBLE")
    assert seen["PAM4_Fixed_PS80"][1] == "INFEASIBLE"
    for name in ("PAM8_Fixed_Inner_H288", "PAM8_Fixed_Outer_H288", "PAM16_Fixed_Inner_H388",
                 "PAM16_Fixed_Outer_H388", "PAM4_Fixed_PS70", "PAM8_Uniform", "PAM16_Uniform"):  # fmt: skip
        assert seen[name][1] == "FEASIBLE", name


def test_metadata_carries_the_common_target_result_for_protocol_b_only(exported, tmp_path):
    _, out, _ = exported
    folder = out / "B_112G_PAM8"
    # this fixture shortens the frames (PAM4: 4096 symbols, 3 of 4 blocks carry payload)
    target = 224e9 / 4 * 2 * 3 / 4
    for name in ("PAM8_Fixed_Inner_H272", "PAM8_Uniform", "PAM8_Adaptive"):
        meta = json.loads((folder / f"references/{name}/{name}_metadata.json").read_text())
        common = meta["rate_equalisation_common_target"]
        counts = meta["frame"]["matcher_composition"]
        bits = 3 * 1024 if counts is None else independent_bits(counts)
        needed = 224e9 * target / (224e9 / 6 * bits * 2 / 4096)
        assert common["target_bps"] == pytest.approx(target, rel=1e-12)
        assert common["required_sample_rate_hz"] == pytest.approx(needed, rel=1e-9)
        assert (common["status"] == "FEASIBLE") == (200e9 <= needed <= 256e9)
        assert common["applied"] is False and common["name"] == name
        assert meta["rate_equalisation"]["name"] == name  # the same-order result sits beside it
    path = small_config(tmp_path)
    generate_mpam_all(path, tmp_path / "a", orders=(2,), protocols=("A",))
    meta = json.loads(
        (tmp_path / "a/A_8GBd_PAM2/references/PAM2_Uniform/PAM2_Uniform_metadata.json").read_text()
    )
    assert "Protocol A holds the symbol rate" in meta["rate_equalisation_common_target"]


# ------------------------------------------------------------------ finding 2: evidence


@pytest.mark.parametrize("label", ["mock", "measured", "analytical"])
def test_a_synthetic_package_claiming_another_evidence_label_fails(exported, tmp_path, label):
    """The QA repro: every row and the metadata say `label`, the metadata source says synthetic."""
    folder = copy_package(exported, tmp_path)
    manifest, _ = read_manifest(folder)
    for index, row in enumerate(manifest):
        name = Path(row["waveform_filename"]).stem
        edit_row(folder, index, evidence=label)
        edit_metadata(folder, name, lambda m: m.update(evidence=label))
    refresh(folder)
    results = validate_profile(folder)
    assert failed_checks(results) == {"evidence_matches_source"}  # the label itself is a known one
    assert sum(not c.passed for c in results) == len(manifest)


def test_the_generator_hard_codes_the_simulated_label(exported):
    _, out, _ = exported
    for name in ("B_112G_PAM8", "B_112G_PAM2"):
        manifest, _ = read_manifest(out / name)
        assert {r["evidence"] for r in manifest} == {"simulated"}
        for row in manifest:
            stem = Path(row["waveform_filename"]).stem
            meta = json.loads((out / name / f"references/{stem}/{stem}_metadata.json").read_text())
            assert meta["evidence"] == "simulated" and "synthetic" in meta["source"]


def test_a_v1_package_claiming_measured_evidence_fails(tmp_path):
    folder = tmp_path / "B_highspeed_56GBd"
    shutil.copytree("output/keysight_m8199b/B_highspeed_56GBd", folder)
    assert not failed_checks(validate_profile(folder))
    edit_row(folder, 0, measured_or_simulated_source="measured")
    assert "evidence_matches_source" in failed_checks(validate_profile(folder))


# ------------------------------------------------------------------ finding 4: names and members


def test_the_validators_pinned_menu_agrees_with_the_generators_and_with_literals():
    for order in (4, 8, 16):
        mine, theirs = pinned_menu(order), fixed_menu(order)
        assert list(mine) == list(theirs) == expected_names(2, order)[:-2]
        for name in mine:
            assert mine[name] == pytest.approx(list(theirs[name]), abs=1e-9)
    assert pinned_menu(8)["PAM8_Fixed_Inner_H288"][:4] == pytest.approx(
        [0.0569, 0.1031, 0.1532, 0.1868], abs=5e-5
    )
    assert pinned_menu(16)["PAM16_Fixed_Outer_H372"][:2] == pytest.approx(
        [0.1544, 0.0998], abs=5e-5
    )
    assert set(EXPECTED_TARGETS) <= set(pinned_menu(4))


def test_a_pmf_put_under_the_wrong_name_is_caught(exported, tmp_path):
    """The QA repro: the H272 PMF in the H288 slot, consistently in row and metadata."""
    folder = copy_package(exported, tmp_path)
    wrong = pinned_menu(8)["PAM8_Fixed_Inner_H272"]
    entropy = -sum(p * math.log2(p) for p in wrong)
    edit_row(
        folder,
        IDX["PAM8_Fixed_Inner_H288"],
        probabilities=json.dumps([round(p, 6) for p in wrong]),
        entropy_target_bits=f"{entropy:.6f}",
    )
    edit_metadata(
        folder,
        "PAM8_Fixed_Inner_H288",
        lambda m: m["shaping"].update(target_probabilities=wrong, entropy_target_bits=entropy),
    )
    refresh(folder)
    failed = failed_checks(validate_profile(folder))
    assert "target_is_requested" in failed
    assert failed.isdisjoint(
        {"manifest_probabilities_match_metadata", "entropy_target_matches_probabilities"}
    )


@pytest.mark.parametrize("parameter", ["member=X", "member=PAM8_Fixed_Inner_H272", "pairs=[]", ""])
def test_best_fixed_member_must_be_a_pinned_member_with_its_pmf(exported, tmp_path, parameter):
    folder = copy_package(exported, tmp_path)
    manifest, _ = read_manifest(folder)
    current = manifest[IDX["PAM8_BestFixed"]]["shaping_parameter"]
    assert current.startswith("member=PAM8_")
    assert parameter != current
    edit_row(folder, IDX["PAM8_BestFixed"], shaping_parameter=parameter)
    refresh(folder)
    assert "target_is_requested" in failed_checks(validate_profile(folder))


def test_adaptive_pmf_must_be_symmetric(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    skew = [0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2 - 0.0]
    skew[0], skew[7] = 0.25, 0.15
    entropy = -sum(p * math.log2(p) for p in skew)
    edit_row(
        folder,
        IDX["PAM8_Adaptive"],
        probabilities=json.dumps(skew),
        entropy_target_bits=f"{entropy:.6f}",
    )
    edit_metadata(
        folder,
        "PAM8_Adaptive",
        lambda m: m["shaping"].update(target_probabilities=skew, entropy_target_bits=entropy),
    )
    refresh(folder)
    assert "target_is_requested" in failed_checks(validate_profile(folder))


# ------------------------------------------------------------------ finding 5: default-deny


def test_a_header_only_manifest_with_an_empty_checksum_list_fails_in_both_schemas(tmp_path):
    for columns in (MANIFEST_COLUMNS, MANIFEST_COLUMNS_V2):
        folder = tmp_path / f"p{len(columns)}"
        folder.mkdir()
        (folder / "experiment_manifest.csv").write_text(",".join(columns) + "\n")
        (folder / "checksums.sha256").write_text("")
        results = validate_profile(folder)
        assert results and failed_checks(results) == {"manifest_schema_known"}
        assert "no rows" in results[0].detail
    assert cli_main(["validate", "--output", str(tmp_path)]) == 1


def test_a_missing_manifest_fails_instead_of_crashing(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    results = validate_profile(folder)
    assert (
        failed_checks(results) == {"manifest_schema_known"} and "no manifest" in results[0].detail
    )


def test_the_cli_fails_when_there_is_nothing_to_validate(tmp_path):
    assert cli_main(["validate", "--output", str(tmp_path)]) == 1  # no profile folders at all


def test_the_cli_passes_a_good_v2_package_and_fails_a_damaged_one(exported, tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    shutil.copytree(exported[1] / "B_112G_PAM8", root / "B_112G_PAM8")
    assert cli_main(["validate", "--output", str(root)]) == 0
    (root / "B_112G_PAM8" / "checksums.sha256").write_text("")
    assert cli_main(["validate", "--output", str(root)]) == 1


def test_fewer_rows_than_expected_fail_even_after_a_rehash(exported, tmp_path):
    """The QA repro: 1 of 7 rows kept, the manifest hash updated."""
    folder = copy_package(exported, tmp_path)

    def keep_one(columns, rows):
        return columns, rows[:1]

    rewrite_manifest(folder, keep_one)
    refresh(folder)
    results = validate_profile(folder)
    assert failed_checks(results) == {"manifest_rows_complete"}
    assert "PAM8_BestFixed" in next(c.detail for c in results if not c.passed)
    folder2 = copy_package(exported, tmp_path / "second")
    rewrite_manifest(folder2, lambda c, rows: (c, rows + rows[:1]))  # a duplicate row
    refresh(folder2)
    assert "manifest_rows_complete" in failed_checks(validate_profile(folder2))


def test_an_empty_or_incomplete_checksum_list_fails(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    (folder / "checksums.sha256").write_text("")
    assert failed_checks(validate_profile(folder)) == {"checksum_list_complete"}
    refresh(folder)
    lines = (folder / "checksums.sha256").read_text().splitlines()
    (folder / "checksums.sha256").write_text("\n".join(lines[:-1]) + "\n")
    assert failed_checks(validate_profile(folder)) == {"checksum_list_complete"}
    (folder / "checksums.sha256").write_text("\n".join([*lines, "not a checksum line"]) + "\n")
    assert failed_checks(validate_profile(folder)) == {"checksum_list_complete"}
    (folder / "checksums.sha256").write_text("\n".join([*lines, f"{'0' * 64}  ../escape"]) + "\n")
    assert failed_checks(validate_profile(folder)) == {"checksum_file_entry"}


def test_a_v1_package_with_a_dropped_row_fails(tmp_path):
    folder = tmp_path / "B_highspeed_56GBd"
    shutil.copytree("output/keysight_m8199b/B_highspeed_56GBd", folder)
    rewrite_manifest(folder, lambda c, rows: (c, rows[:4]))
    refresh(folder)
    assert failed_checks(validate_profile(folder)) == {"manifest_rows_complete"}


def test_a_missing_reference_file_is_a_failed_check_not_a_crash(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    (folder / "references/PAM8_Uniform/PAM8_Uniform_info_bits.txt").unlink()
    assert "reference_files_readable" in failed_checks(validate_profile(folder))


# ------------------------------------------------------------------ finding 6: recomputation


def test_the_exported_manifest_values_are_the_independently_computed_ones(exported):
    """Not read back from the validator: the arithmetic is written out here."""
    _, out, _ = exported
    folder = out / "B_112G_PAM8"
    manifest, _ = read_manifest(folder)
    shaped = 0
    for row in manifest:
        name = Path(row["waveform_filename"]).stem
        meta = json.loads((folder / f"references/{name}/{name}_metadata.json").read_text())
        target = json.loads(row["probabilities"])
        realised = json.loads(row["realised_probabilities"])
        lines = (folder / f"references/{name}/{name}_symbols.csv").read_text().splitlines()[1:]
        payload = [int(line.split(",")[1]) for line in lines[2048:]]
        counts = [payload.count(s) / len(payload) for s in range(8)]
        assert realised == pytest.approx(counts, abs=1e-6)  # recomputed from the file
        bits_per_symbol, baud = 3, 224e9 / 6
        assert float(row["nominal_information_rate_bps"]) == pytest.approx(
            bits_per_symbol * baud, rel=1e-9
        )  # three bits per symbol, not two
        assert float(row["nominal_information_rate_bps"]) == pytest.approx(112e9, rel=1e-9)
        entropy = -sum(p * math.log2(p) for p in target)
        if meta["frame"]["matcher_composition"] is None:
            assert float(row["distribution_matcher_rate_loss"]) == 0.0
            assert float(row["distribution_matcher_rate"]) == 3.0
        else:
            shaped += 1
            composition = meta["frame"]["matcher_composition"]
            rate = independent_bits(composition) / 1024
            assert float(row["distribution_matcher_rate"]) == pytest.approx(rate, abs=1e-6)
            assert float(row["distribution_matcher_rate_loss"]) == pytest.approx(
                entropy - rate, abs=1e-5
            )
            assert float(row["distribution_matcher_rate_loss"]) > 0.0
            # realised is the composition of the file, not the target (rounded to a block of 1024)
            assert max(abs(a - b) for a, b in zip(realised, target, strict=True)) > 1e-5
        net = int(row["payload_information_bits"]) / (4096 * 6 / 224e9)
        assert float(row["actual_net_payload_rate_bps"]) == pytest.approx(net, rel=1e-6)
    assert shaped == 6


TAMPER = [
    ("realised_probabilities", IDX["PAM8_Fixed_Inner_H288"], "realised_matches_manifest"),
    ("symbol_entropy_bits", IDX["PAM8_Fixed_Inner_H288"], "symbol_entropy_matches_realised"),
    ("payload_information_bits", IDX["PAM8_Fixed_Inner_H288"], "payload_information_bits_manifest"),
    ("distribution_matcher_rate", IDX["PAM8_Fixed_Inner_H288"], "matcher_rate_manifest"),
    ("distribution_matcher_rate_loss", IDX["PAM8_Fixed_Inner_H288"], "matcher_loss_manifest"),
    ("distribution_matcher_rate_loss", IDX["PAM8_Uniform"], "matcher_loss_manifest"),
    ("nominal_information_rate_bps", IDX["PAM8_Uniform"], "rates_manifest"),
    ("actual_net_payload_rate_bps", IDX["PAM8_Uniform"], "rates_manifest"),
    ("protocol", IDX["PAM8_Uniform"], "protocol_consistent"),
    ("constraint_protocol", IDX["PAM8_Uniform"], "constraint_protocol_known"),
    ("payload_symbols", IDX["PAM8_Uniform"], "payload_symbols_manifest"),
    ("waveform_peak", IDX["PAM8_Uniform"], "waveform_statistics_manifest"),
    ("amplitude_scale", IDX["PAM8_Uniform"], "full_scale_expected"),
]


@pytest.mark.parametrize(("column", "index", "check"), TAMPER)
def test_manifest_values_are_compared_with_values_recomputed_from_the_files(
    exported, tmp_path, column, index, check
):
    """After a rehash, so that only the compared value is wrong: exactly one check fails."""
    folder = copy_package(exported, tmp_path)
    manifest, _ = read_manifest(folder)
    current = manifest[index][column]
    wrong = {
        "realised_probabilities": json.dumps([0.125] * 8),
        "symbol_entropy_bits": "2.5",
        "payload_information_bits": "1",
        "distribution_matcher_rate": "2.9",
        "distribution_matcher_rate_loss": "0.0" if index == IDX["PAM8_Fixed_Inner_H288"] else "0.5",
        "nominal_information_rate_bps": "74666666666",  # 2 bits x 37.333 GBd, not 3
        "actual_net_payload_rate_bps": "1",
        "protocol": "A",
        "constraint_protocol": "fixed_OMA",
        "payload_symbols": "2000",
        "waveform_peak": "0.5",
        "amplitude_scale": "0.5",
    }[column]
    assert wrong != current
    edit_row(folder, index, **{column: wrong})
    refresh(folder)
    failed = failed_checks(validate_profile(folder))
    assert check in failed, failed
    extra = {"protocol": {"manifest_rows_complete"}}  # one protocol per package
    if column not in ("constraint_protocol", "amplitude_scale"):
        assert failed == {check} | extra.get(column, set()), failed


def test_waveform_scale_tolerance_is_half_a_dac_code(exported, tmp_path):
    """A scale error below half a code (1/254 of full scale) passes, above it fails."""
    assert SCALE_TOLERANCE == pytest.approx(0.5 / 127)
    results = {}
    for factor in (0.9999, 0.997, 0.995, 0.9):
        folder = copy_package(exported, tmp_path / str(factor))
        lines = wave_lines(folder, "PAM8_Uniform")
        scaled = [f"{float(v) * factor:.9f}" for v in lines[1:]]
        write_wave(folder, "PAM8_Uniform", [lines[0], *scaled])
        refresh(folder)
        failed = failed_checks(validate_profile(folder))
        results[factor] = "waveform_scale" in failed
        assert failed <= {"waveform_scale", "waveform_statistics_manifest"}, (factor, failed)
    # the outer level (sample 1.0) moves by 1 - factor
    assert results == {0.9999: False, 0.997: False, 0.995: True, 0.9: True}


def test_two_swapped_preamble_chips_are_caught_by_the_m_sequence_check(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    symbols_path = folder / "references/PAM8_Uniform/PAM8_Uniform_symbols.csv"
    lines = symbols_path.read_text().splitlines()
    fields = [line.split(",") for line in lines[1:]]
    p = 0
    q = next(k for k in range(1, 40) if fields[k][1] != fields[0][1])
    assert {fields[p][1], fields[q][1]} == {"0", "7"}
    fields[p][1:], fields[q][1:] = fields[q][1:], fields[p][1:]
    symbols_path.write_text("\n".join([lines[0], *(",".join(f) for f in fields)]) + "\n")
    wave = wave_lines(folder, "PAM8_Uniform")
    sps = 6
    block_p = wave[1 + p * sps : 1 + (p + 1) * sps]
    block_q = wave[1 + q * sps : 1 + (q + 1) * sps]
    wave[1 + p * sps : 1 + (p + 1) * sps] = block_q
    wave[1 + q * sps : 1 + (q + 1) * sps] = block_p
    write_wave(folder, "PAM8_Uniform", wave)
    refresh(folder)
    assert failed_checks(validate_profile(folder)) == {"preamble_is_m_sequence"}


def test_the_expected_preamble_is_the_511_chip_m_sequence_plus_a_balance_symbol():
    chips = expected_preamble(8)
    assert len(chips) == 512 and set(chips) == {0, 7} and chips.count(0) == chips.count(7) == 256
    assert chips == [int(x) for x in preamble_indices(8)]
    assert chips[:9] == [7] * 9  # the all-ones start state is read out first
    ones = [c // 7 for c in chips[:511]]
    # an m-sequence of degree 9 repeats after 511 and has the two-valued autocorrelation
    shifted = ones[37:] + ones[:37]
    agreements = sum(a == b for a, b in zip(ones, shifted, strict=True))
    assert agreements == 255


def test_a_flipped_symbol_in_the_waveform_fails_the_noise_free_reconstruction(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    lines = wave_lines(folder, "PAM8_Uniform")
    sps, k = 6, 2048 + 5
    symbols = (folder / "references/PAM8_Uniform/PAM8_Uniform_symbols.csv").read_text().splitlines()
    index = int(symbols[1 + k].split(",")[1])
    other = levels_of(8)[(index + 1) % 8] / 7
    lines[1 + k * sps : 1 + (k + 1) * sps] = [f"{other:.9f}"] * sps
    write_wave(folder, "PAM8_Uniform", lines)
    refresh(folder)
    failed = failed_checks(validate_profile(folder))
    assert {"noise_free_reconstruction", "waveform_scale"} <= failed


def test_head_check_fails_when_the_payload_does_not_start_at_the_head(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    edit_metadata(folder, "PAM8_Uniform", lambda m: m["frame"].update(payload=[1024, 4096]))
    refresh(folder)
    assert failed_checks(validate_profile(folder)) == {"head_multiple_of_1024"}


def test_a_waveform_name_must_start_with_its_modulation(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    old, new = "PAM8_Uniform", "XPAM8_Uniform"
    shutil.move(folder / f"waveforms/{old}.csv", folder / f"waveforms/{new}.csv")
    shutil.move(folder / f"references/{old}", folder / f"references/{new}")
    for suffix in ("_symbols.csv", "_info_bits.txt", "_metadata.json"):
        shutil.move(
            folder / f"references/{new}/{old}{suffix}", folder / f"references/{new}/{new}{suffix}"
        )
    edit_row(folder, 0, waveform_filename=f"waveforms/{new}.csv")
    refresh(folder)
    results = validate_profile(folder)
    assert "modulation_matches_manifest_row" in failed_checks(results)
    assert all(
        c.waveform == new
        for c in results
        if c.check == "modulation_matches_manifest_row" and not c.passed
    )


# ------------------------------------------------------------------ finding 8: equivalents


def test_the_512_sample_rule_is_reachable_with_a_block_length_that_is_not_a_multiple_of_512():
    """With block 1024 it cannot fail (the symbol count is a multiple of 1024 and sps is whole),
    but check_frame_fit takes any block length: 1124 symbols x 2 = 2248 samples, payload 100."""
    odd = MpamProfile("B", "odd", 2, 224e9, 112e9, 1124)
    fit = check_frame_fit(2, odd, 100)
    assert fit.status is FeasibilityStatus.INFEASIBLE
    assert "2248 samples is not a multiple of 512" in fit.reason and "payload" not in fit.reason
    even = MpamProfile("B", "even", 2, 224e9, 112e9, 1024 + 256)
    assert check_frame_fit(2, even, 256).status is FeasibilityStatus.FEASIBLE  # 2560 = 5 x 512
    assert check_frame_fit(2, even, 256).reason.endswith("(head 1024, payload 256)")


def test_orders_above_pam4_use_the_symmetric_quantiser_and_pam4_the_legacy_one():
    """The two differ at ties (uniform PAM8 at n = 10: the legacy rule splits a +-x pair); on
    the pinned menus at n = 1024 they agree, so only this case tells them apart."""
    uniform8 = [1 / 8] * 8
    assert make_matcher(uniform8, 10, 8).counts == (2, 1, 1, 1, 1, 1, 1, 2)
    assert make_matcher([1 / 16] * 16, 18, 16).counts == (2, *([1] * 14), 2)
    assert make_matcher((0.15, 0.35, 0.35, 0.15), 10, 4).counts == (2, 4, 3, 1)  # legacy, pinned
    for order in (8, 16):
        for pmf in fixed_menu(order).values():
            counts = make_matcher(pmf, 1024, order).counts
            assert counts == counts[::-1]


def test_a_metadata_only_evidence_claim_on_a_synthetic_package_fails(exported, tmp_path):
    folder = copy_package(exported, tmp_path)
    edit_metadata(folder, "PAM8_Uniform", lambda m: m.update(evidence="measured"))
    refresh(folder)
    failed = failed_checks(validate_profile(folder))
    assert {"evidence_matches_source", "modulation_order_matches_metadata"} == failed
    folder2 = copy_package(exported, tmp_path / "second")
    edit_metadata(folder2, "PAM8_Uniform", lambda m: m.update(source="measured on a bench"))
    refresh(folder2)
    assert failed_checks(validate_profile(folder2)) == {"evidence_matches_source"}


@pytest.mark.parametrize(
    ("orders", "protocols"),
    [
        ((4,), ("A", "B")),
        ((), ("B",)),
        ((8,), ()),
        ((3,), ("B",)),
        ((8,), ("C",)),
        ((2, 4), ("B",)),
    ],
)
def test_orders_and_protocols_are_validated_before_anything_is_written(tmp_path, orders, protocols):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="orders must be a non-empty subset"):
        generate_mpam_all(CONFIG, out, orders=orders, protocols=protocols)
    assert not out.exists()


def test_the_cli_treats_zero_checks_as_a_failure(exported, tmp_path, monkeypatch):
    root = tmp_path / "out"
    root.mkdir()
    shutil.copytree(exported[1] / "B_112G_PAM2", root / "B_112G_PAM2")
    assert cli_main(["validate", "--output", str(root)]) == 0
    monkeypatch.setattr("opticps.measurement.validate_export.validate_profile", lambda *a: [])
    assert cli_main(["validate", "--output", str(root)]) == 1
