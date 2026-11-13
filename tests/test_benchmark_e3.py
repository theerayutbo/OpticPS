"""Gate E3: comparison refusals, the Wiegart peak-constrained PAM4 computation, the Ran subcase.

Everything is offline and synthetic. The Wiegart numbers are pinned against closed forms, limits
and a second numerical method (not only against the OpticPS rate module they are built on). Lists
of expected statuses are written out literally on purpose.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import dataclasses
import inspect
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import minimize

from opticps.benchmarks import e3_ran, e3_wiegart
from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.comparison import (
    ComparisonStatus,
    compare,
    refuse,
)
from opticps.benchmarks.e3_wiegart import (
    FIXED_PMF,
    UNIFORM_PMF,
    psnr_db_from_sigma,
    rates_by_grid,
    rates_opticps,
    sigma_from_psnr_db,
    symmetric_pmf,
)
from opticps.benchmarks.provenance import BenchmarkError, ErrorCode, Provenance
from opticps.benchmarks.published_points import (
    ConstraintType,
    DriveDomain,
    EvidenceLabel,
    ModelPoint,
    PublishedPoint,
    ReadFrom,
)
from opticps.optical_channel.link import LinkConfig, cd_null_frequency_hz, dispersive_field
from opticps.optimization.rates import noise_sigma_from_psnr_db

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/benchmarks/E3_WIEGART_RAN.md"


# ------------------------------------------------------------------ comparison machinery
def published(**over):
    base = dict(
        source_id="src",
        location="Sec. 2, text",
        quantity="gain",
        value=0.83,
        unit="dB",
        rate_definition="SMD",
        constraint=ConstraintType.PEAK,
        wavelength_nm=1550.0,
        fibre_length_km=0.0,
        baud_bd=16e9,
        ber_definition="pre-FEC",
        fec_threshold_ber=3.8e-3,
        dsp_stage="FFE",
        drive=DriveDomain.ELECTRICAL,
        evidence=EvidenceLabel.MEASURED,
        read_from=ReadFrom.RUNNING_TEXT,
    )
    return PublishedPoint(**{**base, **over})


def ours(**over):
    base = dict(
        quantity="gain",
        value=0.84,
        unit="dB",
        rate_definition="SMD",
        constraint=ConstraintType.PEAK,
        wavelength_nm=1550.0,
        fibre_length_km=0.0,
        baud_bd=16e9,
        ber_definition="pre-FEC",
        fec_threshold_ber=3.8e-3,
        dsp_stage="FFE",
        drive=DriveDomain.ELECTRICAL,
        evidence=EvidenceLabel.SIMULATED,
        method="test",
    )
    return ModelPoint(**{**base, **over})


def run(p, m, **kw):
    return compare(
        p, m, tolerance=kw.pop("tolerance", 0.02), tolerance_justification="declared first", **kw
    )


def test_a_fully_matched_comparison_is_accepted_and_reports_the_deviation():
    result = run(published(), ours())
    assert result.status is ComparisonStatus.MATCH and result.code is None
    assert result.deviation == pytest.approx(0.01) and result.tolerance == 0.02
    assert result.tolerance_justification == "declared first"
    assert result.unit == "dB"


def test_a_deviation_beyond_the_tolerance_is_a_mismatch_not_a_refusal():
    result = run(published(), ours(value=0.90))
    assert result.status is ComparisonStatus.MISMATCH
    assert result.deviation == pytest.approx(0.07)


def test_mismatched_wavelength_is_refused():
    result = run(published(wavelength_nm=1271.0), ours(wavelength_nm=1550.0))
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert result.code is ErrorCode.NOT_COMPARABLE
    assert "wavelength_nm differs" in result.reason and result.deviation is None


def test_mismatched_unit_is_refused_and_nothing_is_converted():
    result = run(published(unit="dB"), ours(unit="dBm"))
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert "unit differs" in result.reason and "no conversion" in result.reason
    # a unit that could be converted exactly is still refused
    km_m = run(
        published(quantity="reach", unit="km", value=2.4),
        ours(quantity="reach", unit="m", value=2400.0),
    )
    assert km_m.status is ComparisonStatus.NOT_COMPARABLE and km_m.deviation is None


def test_mismatched_rate_definition_is_refused():
    result = run(published(rate_definition="BMD"), ours(rate_definition="SMD"))
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert "rate_definition differs" in result.reason


def test_mismatched_constraint_type_is_refused():
    result = run(published(constraint=ConstraintType.AVERAGE), ours(constraint=ConstraintType.PEAK))
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert "constraint differs" in result.reason


@pytest.mark.parametrize(
    "field, other",
    [
        ("fibre_length_km", 10.0),
        ("baud_bd", 32e9),
        ("ber_definition", "post-FEC"),
        ("fec_threshold_ber", 2.4e-2),
        ("dsp_stage", "none"),
        ("drive", DriveDomain.OPTICAL),
        ("quantity", "rate"),
    ],
)
def test_every_other_condition_mismatch_is_refused(field, other):
    result = run(published(), ours(**{field: other}))
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert f"{field} differs" in result.reason


@pytest.mark.parametrize("side", ["published", "model"])
def test_a_null_condition_on_one_side_is_refused(side):
    p = published(rate_definition=None) if side == "published" else published()
    m = ours(rate_definition=None) if side == "model" else ours()
    result = run(p, m)
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert f"rate_definition is null on the {side} side" in result.reason


def test_a_condition_null_on_both_sides_is_refused_unless_declared_not_applicable():
    p, m = published(wavelength_nm=None), ours(wavelength_nm=None)
    refused = run(p, m)
    assert refused.status is ComparisonStatus.NOT_COMPARABLE
    assert "wavelength_nm is null on both sides" in refused.reason
    assert run(p, m, not_applicable=["wavelength_nm"]).status is ComparisonStatus.MATCH


def test_declaring_a_set_condition_not_applicable_is_refused():
    result = run(published(), ours(), not_applicable=["wavelength_nm"])
    assert result.status is ComparisonStatus.NOT_COMPARABLE
    assert "declared not applicable but is set" in result.reason


def test_null_values_are_refused_and_unknown_not_applicable_names_raise():
    assert run(published(value=None), ours()).status is ComparisonStatus.NOT_COMPARABLE
    assert "published value is null" in run(published(value=None), ours()).reason
    assert "model value is null" in run(published(), ours(value=None)).reason
    with pytest.raises(BenchmarkError, match="unknown condition fields"):
        run(published(), ours(), not_applicable=["colour"])


def test_all_reasons_are_reported_together():
    result = run(published(wavelength_nm=1271.0, unit="dB"), ours(unit="W", rate_definition="BMD"))
    for fragment in ("unit differs", "wavelength_nm differs", "rate_definition differs"):
        assert fragment in result.reason


@pytest.mark.parametrize("bad", [0.0, -0.1, float("nan"), float("inf"), True])
def test_a_tolerance_must_be_positive_and_finite(bad):
    with pytest.raises(BenchmarkError, match="tolerance"):
        compare(published(), ours(), tolerance=bad, tolerance_justification="x")


def test_a_tolerance_needs_a_written_justification():
    with pytest.raises(BenchmarkError):
        compare(published(), ours(), tolerance=0.1, tolerance_justification="  ")


def test_a_number_read_from_a_figure_cannot_be_a_published_point():
    assert {m.value for m in ReadFrom} == {"running text", "table", "equation"}
    with pytest.raises(BenchmarkError, match="figure values are not redistributable"):
        published(read_from="figure")


def test_point_fields_are_validated():
    with pytest.raises(BenchmarkError):
        published(value=float("nan"))
    with pytest.raises(BenchmarkError):
        published(wavelength_nm=-1.0)
    with pytest.raises(BenchmarkError):
        published(constraint="peak")
    with pytest.raises(BenchmarkError):
        ours(evidence="measured")
    with pytest.raises(dataclasses.FrozenInstanceError):
        published().value = 1.0  # type: ignore[misc]


def test_refuse_builds_only_the_two_unrunnable_statuses():
    assert refuse("x").status is ComparisonStatus.NOT_COMPARABLE
    assert refuse("x", ComparisonStatus.BLOCKED).code is None
    with pytest.raises(BenchmarkError):
        refuse("x", ComparisonStatus.MATCH)
    assert [m.value for m in ComparisonStatus] == ["MATCH", "MISMATCH", "NOT COMPARABLE", "BLOCKED"]


# ------------------------------------------------------------------ Wiegart: definitions
@pytest.mark.parametrize("psnr_db", [5.0, 10.0, 13.7, 25.0])
def test_psnr_definition_is_max_x_squared_over_sigma_squared(psnr_db):
    sigma = sigma_from_psnr_db(psnr_db)
    assert 9.0 / sigma**2 == pytest.approx(10 ** (psnr_db / 10), rel=1e-12)
    assert psnr_db_from_sigma(sigma) == pytest.approx(psnr_db, abs=1e-12)
    assert sigma == pytest.approx(noise_sigma_from_psnr_db(psnr_db), rel=1e-12)


def test_symmetric_family_end_points():
    assert np.allclose(symmetric_pmf(0.25), UNIFORM_PMF)
    assert np.allclose(symmetric_pmf(0.5), [0.5, 0, 0, 0.5])
    assert np.allclose(symmetric_pmf(0.35), FIXED_PMF)
    with pytest.raises(ValueError):
        symmetric_pmf(0.6)


# ------------------------------------------------------------------ Wiegart: independent checks
PMFS = [UNIFORM_PMF, FIXED_PMF, tuple(symmetric_pmf(0.4)), (0.1, 0.2, 0.3, 0.4), (0.5, 0, 0, 0.5)]


@pytest.mark.parametrize("pmf", PMFS)
@pytest.mark.parametrize("psnr_db", [8.0, 12.0, 16.0, 22.0])
def test_second_method_agrees_with_the_opticps_rates(pmf, psnr_db):
    a, b = rates_opticps(pmf, psnr_db), rates_by_grid(pmf, psnr_db)
    assert a[0] == pytest.approx(b[0], abs=1e-7)
    assert a[1] == pytest.approx(b[1], abs=1e-7)


@pytest.mark.parametrize("pmf", PMFS)
def test_noise_free_limit_is_the_entropy(pmf):
    p = np.asarray(pmf)
    entropy = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
    smd, bmd = rates_by_grid(pmf, 60.0)
    assert smd == pytest.approx(entropy, abs=1e-9) and bmd == pytest.approx(entropy, abs=1e-9)


@pytest.mark.parametrize("pmf", [UNIFORM_PMF, FIXED_PMF, (0.1, 0.2, 0.3, 0.4)])
def test_low_snr_limit_is_variance_over_two_sigma_squared_ln2(pmf):
    p, levels = np.asarray(pmf), np.arange(4.0)
    variance = float(p @ levels**2 - (p @ levels) ** 2)
    psnr_db = -35.0
    sigma = sigma_from_psnr_db(psnr_db)
    closed = variance / (2 * sigma**2 * math.log(2))
    assert rates_by_grid(pmf, psnr_db)[0] == pytest.approx(closed, rel=2e-3)
    assert rates_opticps(pmf, psnr_db)[0] == pytest.approx(closed, rel=2e-3)


@pytest.mark.parametrize("psnr_db", [6.0, 10.0, 12.0, 15.0])
def test_on_off_keying_matches_a_third_method_and_bmd_equals_smd(psnr_db):
    ook = e3_wiegart.ook_rate_by_llr(psnr_db)
    pmf = (0.5, 0, 0, 0.5)
    assert rates_by_grid(pmf, psnr_db)[0] == pytest.approx(ook, abs=1e-8)
    smd, bmd = rates_opticps(pmf, psnr_db)
    assert smd == pytest.approx(ook, abs=1e-7)
    assert bmd == pytest.approx(smd, abs=1e-12)  # outer points differ in one bit only


@pytest.mark.parametrize("pmf", PMFS)
@pytest.mark.parametrize("psnr_db", [6.0, 11.0, 17.0, 30.0])
def test_bit_metric_rate_never_exceeds_the_symbol_metric_rate(pmf, psnr_db):
    smd, bmd = rates_by_grid(pmf, psnr_db)
    assert 0 <= bmd <= smd + 1e-9


def test_uniform_four_pam_saturates_at_two_bits():
    assert rates_by_grid(UNIFORM_PMF, 40.0)[0] == pytest.approx(2.0, abs=1e-6)


def test_required_psnr_agrees_between_methods():
    for pmf in (UNIFORM_PMF, FIXED_PMF, tuple(symmetric_pmf(0.4))):
        for metric in ("smd", "bmd"):
            a = e3_wiegart.required_psnr_db(pmf, 1.0, metric)
            b = e3_wiegart.required_psnr_db_grid(pmf, 1.0, metric)
            assert a == pytest.approx(b, abs=1e-4)


@pytest.mark.parametrize("metric", ["smd", "bmd"])
def test_line_search_optimum_beats_a_dense_scan_with_the_second_method(metric):
    best = e3_wiegart.best_symmetric(1.0, metric)
    for q in np.linspace(0.30, 0.49, 20):
        scan = e3_wiegart.required_psnr_db_grid(symmetric_pmf(float(q)), 1.0, metric)
        assert best.psnr_db <= scan + 2e-4


def test_unconstrained_optimum_is_symmetric_about_the_mean():
    # SMD is concave in the PMF, so a local search over all of the simplex finds the optimum.
    psnr_db = 12.9

    def negative_rate(z):
        p = np.exp(z - z.max())
        p /= p.sum()
        return -rates_by_grid(p, psnr_db, step_in_sigma=0.05)[0]

    start = np.log([0.3, 0.2, 0.2, 0.3]) + np.array([0.3, 0.0, 0.0, -0.3])
    result = minimize(
        negative_rate,
        start,
        method="Nelder-Mead",
        options={"xatol": 1e-5, "fatol": 1e-11, "maxiter": 2000},
    )
    p = np.exp(result.x - result.x.max())
    p /= p.sum()
    assert p[0] == pytest.approx(p[3], abs=2e-3) and p[1] == pytest.approx(p[2], abs=2e-3)
    assert p[0] == pytest.approx(0.4, abs=0.02)


# ------------------------------------------------------------------ Wiegart: the rows
@pytest.fixture(scope="module")
def wiegart_rows():
    return {row.row_id: row for row in e3_wiegart.wiegart_rows()}


def test_the_tolerances_were_fixed_before_the_deviations_were_computed():
    assert e3_wiegart.TOL_GAIN_DB == 0.01 and e3_wiegart.TOL_P0 == 0.05


def test_wiegart_row_statuses(wiegart_rows):
    statuses = {k: r.result.status.value for k, r in wiegart_rows.items()}
    assert statuses == {
        "W1": "MATCH", "W2": "MATCH", "W3": "MATCH", "W4a": "MATCH", "W4b": "MATCH",
        "W5": "MATCH", "W6": "NOT COMPARABLE", "W7": "NOT COMPARABLE",
        "W8": "NOT COMPARABLE", "W9": "NOT COMPARABLE",
    }  # fmt: skip


def test_wiegart_deviations_are_inside_their_declared_tolerance(wiegart_rows):
    for key, tolerance in (("W1", 0.01), ("W2", 0.01), ("W3", 0.01), ("W4a", 0.05), ("W4b", 0.05)):
        result = wiegart_rows[key].result
        assert result.tolerance == tolerance and abs(result.deviation) <= tolerance
    # recomputed here with the second method, independent of the row code
    uniform = e3_wiegart.required_psnr_db_grid(UNIFORM_PMF, 1.0, "bmd")
    fixed = e3_wiegart.required_psnr_db_grid(FIXED_PMF, 1.0, "bmd")
    assert wiegart_rows["W3"].result.model_value == pytest.approx(uniform - fixed, abs=2e-4)


def test_figure_rows_name_the_figure_and_the_axes(wiegart_rows):
    for key, fragment in (("W6", "Fig. 1"), ("W7", "Fig. 2a")):
        reason = wiegart_rows[key].result.reason
        assert "FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED)" in reason
        assert fragment in reason and "x: PSNR [dB]" in reason
        assert wiegart_rows[key].result.code is ErrorCode.NOT_COMPARABLE


def test_unmatched_conditions_are_never_adjusted(wiegart_rows):
    # the measured experiments are refused, with the missing parameter named
    assert "PSNR" in wiegart_rows["W9"].result.reason
    assert wiegart_rows["W9"].result.deviation is None


def test_wiegart_config_fields_are_known_with_locations_and_unknowns_stay_null():
    p = load_source_config(ROOT / "configs/benchmarks/wiegart_2021_peak_pam4.yaml").parameters
    for name in ("distribution_family", "noise_definition", "rate_definition", "wavelength_nm",
                 "dispersion_ps_per_nm_km", "equalizer", "transmitter_type", "detector"):  # fmt: skip
        assert p[name].known and p[name].source_ref and "arXiv v2" in p[name].source_ref
    for name in ("baud_bd", "fibre_length_km", "reference_sequence"):
        assert p[name].value is None and p[name].provenance is Provenance.UNKNOWN
    assert p["wavelength_nm"].value == 1550 and p["dispersion_ps_per_nm_km"].value == 17
    assert (
        "Eq. (3)" in p["noise_definition"].source_ref
        and "Eq. (4)" in p["noise_definition"].source_ref
    )


# ------------------------------------------------------------------ Ran
def test_cited_link_comes_from_the_config_and_follows_it(tmp_path):
    link = e3_ran.cited_link(ROOT)
    assert (link.wavelength_nm, link.dispersion_ps_per_nm_km) == (1271.0, -3.99)
    copy = tmp_path / "configs/benchmarks"
    copy.mkdir(parents=True)
    text = (ROOT / e3_ran.CONFIG_PATH).read_text().replace("value: 1271,", "value: 1300,")
    (copy / "ran_2025_g652d.yaml").write_text(text)
    assert e3_ran.cited_link(tmp_path).wavelength_nm == 1300.0


def test_no_default_wavelength_or_dispersion_exists_in_the_ran_functions():
    for function in (e3_ran.small_signal_response, e3_ran.null_frequencies_hz,
                     e3_ran.half_power_frequency_hz):  # fmt: skip
        parameters = inspect.signature(function).parameters
        for name in ("d_ps_per_nm_km", "length_km", "wavelength_nm"):
            assert parameters[name].default is inspect.Parameter.empty
    assert "1550" not in (ROOT / "src/opticps/benchmarks/e3_ran.py").read_text()
    with pytest.raises(ValueError):
        e3_ran.null_frequencies_hz(-3.99, 5.0, 0.0)
    with pytest.raises(ValueError):
        e3_ran.null_frequencies_hz(0.0, 5.0, 1271.0)


def test_accumulated_dispersion_and_nulls_at_the_published_wavelength():
    d, wl = -3.99, 1271.0
    assert e3_ran.accumulated_dispersion_ps_per_nm(d, 5.0) == pytest.approx(-19.95)
    assert e3_ran.accumulated_dispersion_ps_per_nm(d, 10.0) == pytest.approx(-39.90)
    # explicit arithmetic: f0 = sqrt(c / (2 |D| L lambda^2)) with D in s/m^2, L in m, lambda in m
    f0_5 = math.sqrt(299792458.0 / (2 * 3.99e-6 * 5e3 * (1271e-9) ** 2))
    assert e3_ran.null_frequencies_hz(d, 5.0, wl, 1)[0] == pytest.approx(f0_5, rel=1e-12)
    assert f0_5 / 1e9 == pytest.approx(68.199, abs=1e-3)
    f0_10 = e3_ran.null_frequencies_hz(d, 10.0, wl, 1)[0]
    assert f0_10 / 1e9 == pytest.approx(48.224, abs=1e-3)
    assert f0_10 == pytest.approx(f0_5 / math.sqrt(2), rel=1e-12)
    higher = e3_ran.null_frequencies_hz(d, 5.0, wl, 3)
    assert higher[1] / higher[0] == pytest.approx(math.sqrt(3)) and higher[2] / higher[
        0
    ] == pytest.approx(math.sqrt(5))
    # a 1550 nm default would give a different, wrong answer at this dispersion
    assert e3_ran.null_frequencies_hz(d, 5.0, 1550.0, 1)[0] < f0_5


def test_response_is_one_at_dc_zero_at_the_nulls_and_half_power_at_f3db():
    d, wl, length = -3.99, 1271.0, 5.0
    assert e3_ran.small_signal_response(0.0, d, length, wl) == pytest.approx(1.0)
    for f in e3_ran.null_frequencies_hz(d, length, wl, 4):
        assert float(e3_ran.small_signal_response(f, d, length, wl)) == pytest.approx(0.0, abs=1e-9)
    f3 = e3_ran.half_power_frequency_hz(d, length, wl)
    assert float(e3_ran.small_signal_response(f3, d, length, wl)) ** 2 == pytest.approx(
        0.5, rel=1e-12
    )
    # the sign of D does not matter for a chirp-free link
    assert float(e3_ran.small_signal_response(30e9, 3.99, length, wl)) == pytest.approx(
        float(e3_ran.small_signal_response(30e9, -3.99, length, wl))
    )


def test_null_frequency_agrees_with_the_existing_link_model():
    for length in (5.0, 10.0):
        config = LinkConfig(
            fiber_length_km=length, dispersion_ps_per_nm_km=-3.99, wavelength_m=1271e-9
        )
        assert e3_ran.null_frequencies_hz(-3.99, length, 1271.0, 1)[0] == pytest.approx(
            cd_null_frequency_hz(config), rel=1e-12
        )


@pytest.mark.parametrize("length", [5.0, 10.0])
def test_response_agrees_with_a_time_domain_dispersion_simulation(length):
    # second method: a real-valued sqrt(1 + m cos) envelope through the all-pass dispersion of the
    # link model at 1271 nm, square-law detection, tone amplitude from the FFT.
    d, wl, m, fs, n = -3.99, 1271.0, 1e-3, 1024e9, 8192
    config = LinkConfig(fiber_length_km=length, dispersion_ps_per_nm_km=d, wavelength_m=wl * 1e-9)
    t = np.arange(n) / fs
    for f in (10e9, 30e9, 48.25e9, 68.25e9, 100e9):
        field = np.sqrt(1 + m * np.cos(2 * np.pi * f * t)).astype(complex)
        intensity = np.abs(dispersive_field(field, fs, config)) ** 2
        k = round(f / (fs / n))
        measured = 2 * abs(np.fft.fft(intensity)[k]) / n / m
        predicted = float(e3_ran.small_signal_response(f, d, length, wl))
        assert measured == pytest.approx(predicted, abs=2e-3)


def test_source_data_check_lists_names_only_and_blocks_when_absent(tmp_path):
    (tmp_path / "teriphic").mkdir()
    (tmp_path / "teriphic" / "capture.bin").write_bytes(b"x")
    absent = e3_ran.source_data_status(tmp_path)
    assert not absent.present and absent.files_listed == ()
    assert (
        absent.status == "BLOCKED: SOURCE DATA XLSX NOT OBTAINED (LICENCE/REUSE TERMS UNVERIFIED)"
    )
    (tmp_path / "ran").mkdir()
    (tmp_path / "ran" / "41467_2025_61408_MOESM3_ESM.xlsx").write_bytes(b"not read")
    present = e3_ran.source_data_status(tmp_path)
    assert present.present and present.files_listed == ("ran/41467_2025_61408_MOESM3_ESM.xlsx",)


def test_chirp_model_gap_names_each_missing_parameter():
    gap = e3_ran.chirp_model_gap()
    assert gap.status is ComparisonStatus.NOT_COMPARABLE and gap.reason.startswith(
        "MODEL GAP: CHIRP"
    )
    for fragment in ("chirp parameter", "bias point", "drive swing", "symbol rate per lane",
                     "gross versus net", "BER definition", "optical power", "responsivity"):  # fmt: skip
        assert fragment in gap.reason
    assert len(e3_ran.CHIRP_MODEL_MISSING) >= 10


def test_ran_row_statuses_and_the_headline_rates_are_not_reproduced(tmp_path):
    rows = {r.row_id: r for r in e3_ran.ran_rows(ROOT)}
    assert {k: r.result.status.value for k, r in rows.items()} == {
        "R1": "NOT COMPARABLE", "R2": "NOT COMPARABLE", "R3": "BLOCKED", "R4": "NOT COMPARABLE",
    }  # fmt: skip
    assert (
        "256 Gb/s over 5 km" in rows["R1"].source_text
        and "200 Gb/s over 10 km" in rows["R2"].source_text
    )
    assert all(r.result.deviation is None and r.result.model_value is None for r in rows.values())
    assert "chirped" in rows["R4"].result.reason and "not a prediction" in rows["R4"].result.reason
    assert "68.20 GHz (5 km)" in rows["R4"].our_text and "48.22 GHz (10 km)" in rows["R4"].our_text


# ------------------------------------------------------------------ report agrees with the code
def doc_rows():
    rows = {}
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and cells and cells[0] in {
            "W1", "W2", "W3", "W4a", "W4b", "W5", "W6", "W7", "W8", "W9", "R1", "R2", "R3", "R4"
        }:  # fmt: skip
            rows[cells[0]] = cells
    return rows


def test_the_report_rows_carry_the_statuses_the_code_computes(wiegart_rows):
    table = doc_rows()
    computed = {**wiegart_rows, **{r.row_id: r for r in e3_ran.ran_rows(ROOT)}}
    assert set(table) == set(computed)
    for key, row in computed.items():
        assert table[key][-1].split(":")[0].strip() == row.result.status.value, key
        if row.result.deviation is not None:
            assert f"{row.result.model_value:.4f}" in " ".join(table[key]), key


def test_the_report_contains_no_figure_values_or_local_paths():
    text = DOC.read_text()
    assert "/Users/" not in text
    assert "NOT COMPARABLE: FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED)" in text
