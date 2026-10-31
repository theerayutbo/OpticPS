"""configs/mpam_profiles.yaml loader and the pinned best-fixed baseline (v1.3-mpam C5)."""

import hashlib
from pathlib import Path

import pytest
import yaml

from opticps.optimization.adaptive import (
    BaselineOverrideError,
    ExploratoryMenu,
    best_fixed,
    fixed_menu,
    oracle_not_a_baseline,
    simulate_acquisitions,
)
from opticps.transmitter.mpam_config import ConfigError, load_mpam_config

CONFIG = Path("configs/mpam_profiles.yaml")
TOP_CONFIG = Path("configs/m8199b_profiles.yaml")


def edited(tmp_path: Path, edit) -> Path:
    config = yaml.safe_load(CONFIG.read_text())
    edit(config)
    path = tmp_path / "edited.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_the_committed_config_loads_and_hashes_its_raw_bytes():
    config = load_mpam_config(CONFIG)
    assert config.sha256 == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    assert yaml.safe_load(CONFIG.read_text())["config_schema_version"] == 2
    assert config.fixed_deficits == (0.12, 0.28) and config.evidence == "simulated"
    assert config.constraint_protocol == "fixed_peak" and config.data_out == "DataOut1"
    assert len(config.profiles) == 12 and {p.protocol for p in config.profiles} == {"A", "B"}


def test_the_pam4_config_is_untouched_by_this_slice():
    """experiment_id hashes the raw bytes of this file, so its SHA-256 is pinned (as at 1.2.0)."""
    digest = hashlib.sha256(TOP_CONFIG.read_bytes()).hexdigest()
    assert digest == "840fdfb5bbdf1cb6e65e188d59b43ff72731dbbc0bfb309ff272ccdf0ad49424"


def test_reported_menu_comes_only_from_the_pinned_deficits():
    config = load_mpam_config(CONFIG)
    for order, names in (
        (4, ["PAM4_Uniform", "PAM4_Fixed_PS70", "PAM4_Fixed_PS80", "PAM4_Fixed_Outer70"]),
        (
            8,
            ["PAM8_Uniform", "PAM8_Fixed_Inner_H288", "PAM8_Fixed_Inner_H272",
             "PAM8_Fixed_Outer_H288", "PAM8_Fixed_Outer_H272"],
        ),
        (
            16,
            ["PAM16_Uniform", "PAM16_Fixed_Inner_H388", "PAM16_Fixed_Inner_H372",
             "PAM16_Fixed_Outer_H388", "PAM16_Fixed_Outer_H372"],
        ),
    ):  # fmt: skip
        menu = config.reported_fixed_menu(order)
        assert list(menu) == names and menu == fixed_menu(order)


def test_a_config_that_changes_the_menu_or_the_deficits_is_refused(tmp_path):
    for edit in (
        lambda c: c["fixed_menu"].update(entropy_deficits_bits=[0.10, 0.30]),
        lambda c: c["fixed_menu"].update(entropy_deficits_bits=[0.12]),
        lambda c: c["fixed_menu"].update(members=["Uniform", "Inner"]),
    ):
        with pytest.raises(BaselineOverrideError, match="cannot be changed"):
            load_mpam_config(edited(tmp_path, edit))


def test_run_time_menu_arguments_cannot_change_a_reported_baseline():
    with pytest.raises(BaselineOverrideError):
        fixed_menu(8, (0.10, 0.30))
    with pytest.raises(BaselineOverrideError):
        fixed_menu(4, (0.05, 0.28))
    assert fixed_menu(8, (0.12, 0.28)) == fixed_menu(8) and type(fixed_menu(8)) is dict
    exploratory = fixed_menu(8, (0.10, 0.30), exploratory=True)
    assert isinstance(exploratory, ExploratoryMenu) and exploratory.reportable is False
    assert "PAM8_Fixed_Inner_H290" in exploratory and "PAM8_Fixed_Inner_H288" not in exploratory


def test_best_fixed_marks_any_non_pinned_menu_non_reportable():
    train, _ = simulate_acquisitions(22.0, 8, 12000, 3, 1, 0)
    pinned = best_fixed(train, 8, "smd", 1024)
    assert pinned.reportable is True and "pinned menu" in pinned.reportable_reason
    explicit = best_fixed(train, 8, "smd", 1024, dict(fixed_menu(8)))
    assert explicit.reportable is True  # the same menu passed explicitly is still the baseline
    exploratory = best_fixed(train, 8, "smd", 1024, fixed_menu(8, (0.10, 0.30), exploratory=True))
    assert exploratory.reportable is False and "NON-REPORTABLE" in exploratory.reportable_reason
    # a plain dict with a changed PMF, a dropped member or a renamed member
    changed = dict(fixed_menu(8))
    changed["PAM8_Fixed_Inner_H288"] = fixed_menu(8)["PAM8_Fixed_Inner_H272"]
    dropped = {k: v for k, v in fixed_menu(8).items() if k != "PAM8_Fixed_Outer_H272"}
    renamed = {k.replace("Inner_H288", "Inner_H999"): v for k, v in fixed_menu(8).items()}
    for menu in (changed, dropped, renamed):
        result = best_fixed(train, 8, "smd", 1024, menu)
        assert result.reportable is False and "NON-REPORTABLE" in result.reportable_reason
        assert result.to_dict()["reportable"] is False
    # the oracle is never a baseline whatever the menu
    oracle = oracle_not_a_baseline(pinned_channel(train), 8, "smd", 1024)
    assert "not a baseline" in oracle["oracle_not_a_baseline"]["selected_on"]


def pinned_channel(train):
    from opticps.optimization.adaptive import estimate_channel

    return estimate_channel(train[0].indices, train[0].received, 8)


def test_unknown_versions_keys_and_labels_are_refused(tmp_path):
    for edit, match in (
        (lambda c: c.update(config_schema_version=3), "not supported"),
        (lambda c: c.pop("config_schema_version"), "not supported"),
        (lambda c: c.update(surprise=1), "unknown top-level"),
        (lambda c: c["common"].update(evidence="guessed"), "evidence must be"),
        (lambda c: c["common"].update(data_out="DataOut9"), "data_out"),
        (lambda c: c["protocol_B"]["samples_per_symbol"].update({8: 5}), "samples per symbol"),
    ):
        with pytest.raises(ConfigError, match=match):
            load_mpam_config(edited(tmp_path, edit))
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n")
    with pytest.raises(ConfigError):
        load_mpam_config(path)
