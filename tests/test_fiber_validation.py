import json
from pathlib import Path

import numpy as np
import pytest

from opticps.cli.main import build_parser
from opticps.measurement.fiber_validation import (
    analytical_curves,
    reproduction_check,
    simulated_null_hz,
)
from opticps.optical_channel.fiber import g652d_preset
from opticps.optical_channel.link import LinkConfig, cd_null_frequency_hz
from opticps.reporting.fiber_report import (
    fiber_facts,
    fiber_section,
    fiber_slide,
    load_fiber_results,
    markdown,
)
from opticps.reporting.report import markdown as main_markdown
from opticps.reporting.slides import deck

DEMO = Path("results/synthetic/demo_results.json")
FIBER = Path("results/fiber_validation/fiber_results.json")
needs_demo = pytest.mark.skipif(not DEMO.exists(), reason="run opticps simulate first")
needs_fiber = pytest.mark.skipif(not FIBER.exists(), reason="run opticps fiber-validate first")


def test_cli_has_fiber_validate_and_keeps_other_commands():
    text = build_parser().format_help()
    for name in "fiber-validate generate validate simulate ingest analyze compare report slides demo".split():
        assert name in text


def test_analytical_curves_follow_the_tables():
    curves = analytical_curves(1260, 1625, 5)
    w = curves["wavelength_nm"]
    assert w[0] == 1260 and w[-1] == 1625
    at = w.index(1550)
    assert curves["attenuation_limit_db_per_km"][at] == 0.30
    assert curves["dispersion_lower_ps_per_nm_km"][at] == pytest.approx(13.3, abs=0.05)
    assert curves["dispersion_upper_ps_per_nm_km"][at] == pytest.approx(18.6, abs=0.05)
    assert curves["representative_within_limits"] is True
    exceed = curves["typical_attenuation_exceeds_limit_nm"]
    # Table I.1 is above the Table 2 limit from 1260 nm to where the interpolation meets 0.40.
    assert exceed["first_nm"] == 1260.0
    assert exceed["last_on_grid_nm"] == 1435.0
    assert exceed["crossover_interpolated_nm"] == pytest.approx(1435.56, abs=0.01)
    assert exceed["stated_by_table_i1_nm"] == [1260.0, 1360.0]
    assert (
        1310.0 in exceed["wavelengths_on_grid_nm"]
        and 1550.0 not in exceed["wavelengths_on_grid_nm"]
    )


@pytest.mark.parametrize("wavelength", [1550.0, 1310.0])
def test_simulated_null_agrees_with_theory_off_grid(wavelength):
    config = LinkConfig(fiber=g652d_preset(wavelength), fiber_length_km=10.0)
    simulated, resolution = simulated_null_hz(config, 1 << 13, 0.02)
    theory = cd_null_frequency_hz(config)
    assert abs(simulated - theory) / theory < 1e-3
    assert 0.01 < (theory / resolution) % 1 < 0.99


def test_reproduction_check_reports_every_difference():
    point = {
        f: 1.0 for f in ("ser", "ber", "r_bmd", "r_smd", "snr_db", "received_dbm", "launch_dbm")
    }
    point |= {"symbol_errors": 3, "bit_errors": 4, "symbols": 100}
    stored = {"profile_A": {"fiber": {"Uniform": [point, point]}}}
    changed = point | {"symbol_errors": 5, "link": {"fiber_length_km": 5.0}}
    same = point | {"link": {"fiber_length_km": 0.0}}
    check = reproduction_check(stored, {"Uniform": [same, changed]}, "profile_A")
    assert check["points_compared"] == 2 and check["points_identical"] == 1
    assert check["mismatches"][0]["symbol_errors"] == [3, 5]


def test_fiber_content_is_optional(tmp_path):
    assert load_fiber_results(tmp_path / "synthetic" / "demo_results.json") is None


@needs_demo
def test_main_report_and_deck_work_without_fiber_results():
    results = json.loads(DEMO.read_text())
    assert "Fiber model" not in main_markdown(results, "figures")
    assert "Fiber model" not in [s.title for s in deck(results, Path("figures"))]


@needs_fiber
def test_saved_fiber_results_are_honest_and_complete():
    fr = json.loads(FIBER.read_text())
    assert fr["data_source"] == "simulated" and fr["experimentally_validated"] is False
    assert "NOTHING HERE IS EXPERIMENTALLY VALIDATED" in fr["banner"]
    assert "08/2024" in fr["standard"]
    facts = fiber_facts(fr)
    assert facts["all_reproduced"], "re-running v1.0 must reproduce the saved v1.0 points"
    assert facts["max_null_error"] < 1e-3
    for row in fr["numerical_validation"]["third_order_phase_at_nyquist"]:
        assert row["third_order_phase_rad"] < 1e-2 * row["second_order_phase_rad"]
    rep = fr["before_after"]["preset"]
    assert rep["attenuation_db_per_km"] == pytest.approx(0.275)
    assert np.isclose(rep["dispersion_ps_per_nm_km"], 17.0)


@needs_fiber
def test_fiber_report_text_states_scope_and_cites_the_standard():
    fr = json.loads(FIBER.read_text())
    text = markdown(fr, "figures")
    for phrase in (
        "edition 10.0",
        "approved 2024-08-29",
        "Not experimentally validated",
        "short cables such as jumpers",
        "link value",
        "confirmed by continuity",
        "PMD is listed",
        "unconfirmed",
    ):
        assert phrase in text
    assert "[analytical]" in text
    assert "Fiber model" in fiber_section(fr, "figures")
    assert fiber_slide(fr)[0].startswith("Fiber model")


@needs_fiber
def test_report_corrections_after_review():
    fr = json.loads(FIBER.read_text())
    text = markdown(fr, "figures")
    assert "Excess loss (dB)" in text and text.count("Excess loss (dB)") >= 8
    assert "includes splices and connectors" not in text
    assert "Inference, not stated in the Recommendation" in text
    assert "double" in text and "twice" in text
    assert "from 1260 to 1435 nm" in text
    assert "1383 \u00b1 3 nm" in text
    assert "0.1268" in text and "0.0357" in text and "slope only" not in text
    assert "Only the before and after comparison below is paired with v1.0" in text
    assert "same at 1550 nm and 1310 nm" in text
    assert "read 2026-10-30" in text
    assert "length and laser wavelength enter" not in text
    assert "`" not in fiber_section(fr, "figures").replace("```", "")
    assert "sections above" not in fiber_section(fr, "figures")


def test_main_report_does_not_call_the_receiver_unidentified():
    source = Path("src/opticps/reporting/report.py").read_text()
    assert "yet to be identified" not in source
    assert "Infiniium UXR" in source and "unconfirmed" in source
