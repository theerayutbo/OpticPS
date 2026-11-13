"""N3 part b: the declared sets, the cost, the optimiser and the fit driver, on a stub chain.

No real data, no workbook, no simulation: the point runner is a smooth synthetic function (see
`nanf_fit_stub`), so every test runs in seconds. Plan Amendment 11 J-A to J-E.
"""

import json
import math

import numpy as np
import pytest

from nanf_fit_stub import (
    CALLS,
    N_BITS,
    all_lost_runner,
    counting_runner,
    objective,
    rough_runner,
    stub_data,
    stub_runner,
)
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_fit as nfit
from opticps.measurement import nanf_freeze as nfz
from opticps.measurement.nanf_benchmark import numerical_profile
from opticps.measurement.nanf_import import (
    DataRole,
    NanfSeries,
    NanfWorkbook,
    PointFlag,
    ProvenanceCategory,
    series_key,
)
from opticps.measurement.nanf_scoring import EvaluationLog, evaluate

PLAN = "a" * 64
CODE = "b" * 64


def run_fit(tmp_path, name="log.jsonl", obj=None, **kwargs):
    return nfit.fit(
        objective() if obj is None else obj,
        log_path=tmp_path / name,
        plan_sha256=PLAN,
        code_identity=CODE,
        **kwargs,
    )


# --- the declared sets (J-E) -----------------------------------------------------------------


def test_the_declared_calibration_points_are_the_eight_scored_b2b_rops_of_each_rate():
    points = nc.DECLARED_CALIBRATION_POINTS
    assert len(points) == 24
    assert points == {(r, -12.0 + k, k) for r in (80, 100, 112) for k in range(8)}
    assert max(rop for _, rop, _ in points) == -5.0  # nothing above the cap of A4


def test_the_declared_indices_cover_the_published_axes_and_nothing_else():
    assert nc.DECLARED_POINT_INDICES == frozenset(range(19))  # 6, 11 and 19 point axes


def test_the_declared_links_are_the_two_1550_nm_profiles_of_the_benchmark_module():
    assert set(nc.DECLARED_LINKS) == {"NANF-4.76km-1550", "SSMF-4.53km-1550"}
    nanf, ssmf = nc.DECLARED_LINKS["NANF-4.76km-1550"], nc.DECLARED_LINKS["SSMF-4.53km-1550"]
    assert nanf.profile == numerical_profile("NANF", length_km=4.76, d_ps_per_nm_km=2.04)
    assert ssmf.profile == numerical_profile("SSMF", length_km=4.53, d_ps_per_nm_km=15.95)
    assert nanf.wavelength_nm == ssmf.wavelength_nm == 1550.0


# --- the cost (J-A) --------------------------------------------------------------------------


def test_the_residual_vector_is_snr_then_log_ber_over_half_a_decade_on_uncensored_cells():
    data = stub_data()
    obj = nfit.CalibrationObjective(data, stub_runner)
    vector = nfit.to_vector(np.full(6, 0.5))
    per = obj.points(vector)
    res = obj.residuals(vector)
    expected = []
    for rate in (80, 100, 112):
        d, pts = data[rate], per[rate]
        expected += [p.snr_db - d.snr[k] for k, p in enumerate(pts)]
        for k, p in enumerate(pts):
            if not np.isnan(d.ber[k]):  # a censored published cell is no term (A4)
                expected.append((math.log10(max(p.ber, 1 / p.n_bits)) - math.log10(d.ber[k])) / 0.5)
    assert np.allclose(res, expected)
    n_censored = sum(int(np.isnan(data[r].ber).sum()) for r in data)
    assert n_censored > 0 and res.size == 24 + 24 - n_censored
    assert obj.cost(vector) == pytest.approx(float(np.sum(np.array(expected) ** 2)))


def test_a_simulated_zero_error_point_enters_as_one_over_the_number_of_bits():
    def error_free(task):
        return nfit.PointSummary(False, "", 0.0, 20.0, N_BITS)

    data = stub_data()
    obj = nfit.CalibrationObjective(data, error_free)
    res = obj.residuals(nfit.to_vector(np.full(6, 0.5)))
    d = data[80]
    uncensored = [k for k in range(8) if not np.isnan(d.ber[k])]
    first_ber_term = res[8 : 8 + len(uncensored)]  # after the eight SNR terms of the 80 Gb/s rate
    expected = [(math.log10(1 / N_BITS) - math.log10(d.ber[k])) / 0.5 for k in uncensored]
    assert np.allclose(first_ber_term, expected) and np.all(np.isfinite(res))


def test_a_lost_lock_point_makes_the_cost_plus_infinity_and_every_lost_point_is_listed():
    obj = objective()
    low = nfit.to_vector(np.array([0.0, 0.5, 0.5, 0.5, 0.5, 0.5]))  # the stub loses lock here
    log = EvaluationLog()
    ev = evaluate(log, low, obj.cost)
    assert ev.objective == math.inf and len(ev.lost) == 24  # all 24 points were run and listed
    assert log.n_worst_case == 1
    with pytest.raises(Exception, match="lost lock"):
        obj.residuals(low)


def test_the_published_axis_must_be_the_declared_calibration_grid():
    def series(sheet_block, header, quantity, x, y, flags=None):
        return NanfSeries(
            series_key("Fig.4", sheet_block, header), "Fig.4", quantity, "1", "ROP", "dBm",
            tuple(x), tuple(y), tuple(flags or [PointFlag.OK] * len(x)), DataRole.CALIBRATION,
            ProvenanceCategory.MEASURED, "synthetic",
        )  # fmt: skip

    def workbook(shift=0.0):
        out = {}
        data = stub_data()
        for rate, d in data.items():
            x = [-12.0 + k + shift for k in range(11)]
            snr = [30.0 - k for k in range(11)]
            out[series_key("Fig.4", f"BER@{rate}", f"B2B-{rate}-BER")] = series(
                f"BER@{rate}", f"B2B-{rate}-BER", "BER", x, d.ber_all
            )
            out[series_key("Fig.4", f"SNR@{rate}", f"B2B-{rate}-SNR")] = series(
                f"SNR@{rate}", f"B2B-{rate}-SNR", "SNR", x, snr
            )
        return NanfWorkbook("0" * 64, out)

    got = nfit.calibration_data(workbook())
    assert set(got) == {80, 100, 112} and all(
        len(g.rop) == 8 and g.rop[-1] == -5.0 for g in got.values()
    )
    assert got[80].indices == tuple(range(8)) and got[80].rop_all.size == 11
    with pytest.raises(nfit.FitRefusedError, match="declared calibration grid"):
        nfit.calibration_data(workbook(shift=0.5))  # a wrong reading of the axis stops N3


# --- the optimiser (J-B) ---------------------------------------------------------------------


def test_the_design_is_a_seeded_latin_hypercube_and_does_not_change():
    a, b = nfit.latin_hypercube(), nfit.latin_hypercube()
    assert a.shape == (24, 6) and np.array_equal(a, b)
    for col in a.T:  # exactly one point in each of the 24 strata of every coordinate
        assert sorted(np.floor(col * 24).astype(int)) == list(range(24))
    rng = np.random.default_rng(np.random.SeedSequence([20261101, 4101]))
    first = (rng.permutation(24) + rng.random(24)) / 24
    assert np.array_equal(a[:, 0], first)  # the exact draw order of J-B.2
    assert nfit.FIT_SEED == (20261101, 4101) and nfit.BUDGET == 70


def test_the_budget_of_70_evaluations_is_a_hard_cap_and_a_stall_is_not_converged(tmp_path):
    CALLS[0] = 0
    out = run_fit(
        tmp_path, obj=nfit.CalibrationObjective(stub_data(), lambda t: _count(rough_runner, t))
    )
    assert out.status == nfit.STATUS_NOT_CONVERGED and not out.converged
    assert out.n_evaluations <= 70 and out.artefact is None
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    assert len(lines) == 1 + out.n_evaluations  # header and one line per evaluation


def _count(runner, task):
    CALLS[0] += 1
    return runner(task)


def test_a_search_that_needs_more_than_the_budget_stops_at_exactly_the_budget(tmp_path):
    out = run_fit(tmp_path, budget=30)
    assert out.status == nfit.STATUS_NOT_CONVERGED and out.n_evaluations == 30
    assert out.artefact is None and out.chosen is None
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 31


def test_the_default_budget_is_70_and_a_search_that_never_meets_its_tolerances_stops_at_70(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(nfit, "X_TOL", 0.0)  # tolerances that can never be met
    monkeypatch.setattr(nfit, "F_TOL", -1.0)
    CALLS[0] = 0
    out = run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), counting_runner))
    assert out.status == nfit.STATUS_NOT_CONVERGED and out.n_evaluations == 70
    assert CALLS[0] == 70 * 24  # the 71st evaluation is never started
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 71


def test_every_evaluation_stays_inside_the_box_and_no_range_is_widened(tmp_path):
    out = run_fit(tmp_path)
    assert out.status == nfit.STATUS_OK
    for ev in out.log.evaluations:
        for spec in nc.B4_PARAMETERS:
            assert spec.low <= ev.vector[spec.name] <= spec.high


def test_all_lost_lock_is_no_valid_fit_and_a_lost_vector_is_never_selected(tmp_path):
    out = run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), all_lost_runner))
    assert out.status == nfit.STATUS_NO_VALID_FIT and out.artefact is None
    assert out.log.n_worst_case == out.n_evaluations == 25  # prior and design, then it stops
    good = run_fit(tmp_path, name="good.jsonl")
    assert good.chosen is not None and not good.chosen.lost and math.isfinite(good.chosen.objective)
    assert good.log.n_worst_case >= 1  # the stub loses lock for some design points
    assert good.chosen.objective == min(
        e.objective for e in good.log.evaluations if not e.lost
    )  # the lowest finite cost of the whole log


def test_the_converged_stub_fit_gives_an_artefact_the_freeze_record_accepts_by_value(tmp_path):
    out = run_fit(tmp_path)
    assert out.status == nfit.STATUS_OK and out.converged and out.artefact is not None
    body = json.loads(out.artefact)
    assert set(body) == nfz.ARTIFACT_KEYS
    fit = body["fit_result"]
    assert fit["method"] == nfit.FIT_METHOD and fit["converged"] is True
    assert fit["n_evaluations"] == out.n_evaluations >= 7 and fit["n_calibration_points"] == 24
    assert fit["cost"] > 0 and fit["cost"] == out.chosen.objective
    nfz._check_checks(body["checks"], tuple(body["unidentifiable"]))  # eigenvalues match the flags
    assert body["checks"]["n_lost_points_in_grid"] == 0
    for name in body["unidentifiable"]:  # a flagged parameter is at its prior (B4.4)
        spec = next(s for s in nc.B4_PARAMETERS if s.name == name)
        assert body["parameters"][name] == spec.prior
    assert set(out.gates) == {80, 100, 112} and all(g.label == "" for g in out.gates.values())
    assert out.censored_diagnostic and all("simulated BER" in x for x in out.censored_diagnostic)


def test_a_gate_that_fails_labels_its_rate_and_stops_nothing(tmp_path):
    def biased(task):
        s = stub_runner(task)
        return s if s.lost else type(s)(False, "", s.ber, s.snr_db + 3.0, s.n_bits)

    data = stub_data()
    obj = nfit.CalibrationObjective(data, biased)
    gates = obj.gates(nfit.to_vector(np.array([0.4, 0.6, 0.5, 0.55, 0.5, 0.45])))
    assert {g.label for g in gates.values()} == {"B2B CALIBRATION POOR"}


# --- one run only, resume (J-D) ---------------------------------------------------------------


def test_the_same_seed_gives_the_same_log_byte_for_byte(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    out_a, out_b = run_fit(a), run_fit(b)
    assert (a / "log.jsonl").read_bytes() == (b / "log.jsonl").read_bytes()
    assert out_a.artefact == out_b.artefact and out_a.n_evaluations == out_b.n_evaluations


def test_a_second_run_with_another_plan_code_or_a_foreign_log_is_refused(tmp_path):
    run_fit(tmp_path)
    for plan, code in (("c" * 64, CODE), (PLAN, "d" * 64)):
        with pytest.raises(nfit.FitRefusedError, match="another run"):
            nfit.fit(
                objective(), log_path=tmp_path / "log.jsonl", plan_sha256=plan, code_identity=code
            )
    (tmp_path / "junk.jsonl").write_text("not json\n")
    with pytest.raises(nfit.FitRefusedError, match="not a resume"):
        run_fit(tmp_path, name="junk.jsonl")
    (tmp_path / "empty.jsonl").write_text("")
    with pytest.raises(nfit.FitRefusedError, match="not a resume"):
        run_fit(tmp_path, name="empty.jsonl")


def test_a_log_with_another_budget_is_not_the_same_run(tmp_path):
    run_fit(tmp_path)
    with pytest.raises(nfit.FitRefusedError, match="another run"):
        run_fit(tmp_path, budget=60)


def test_a_resume_replays_the_log_and_continues_it_without_restarting(tmp_path):
    CALLS[0] = 0
    full = run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), counting_runner))
    fresh_calls = CALLS[0]
    text = (tmp_path / "log.jsonl").read_text()
    kept = 29  # header and the first 28 evaluations: an interrupted run
    lines = text.splitlines(keepends=True)
    (tmp_path / "log.jsonl").write_text("".join(lines[:kept]))
    CALLS[0] = 0
    resumed = run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), counting_runner))
    assert (tmp_path / "log.jsonl").read_text() == text  # the same file, the old lines untouched
    assert resumed.artefact == full.artefact and resumed.n_evaluations == full.n_evaluations
    # the replayed evaluations ran no point; the identifiability step re-runs the chosen vector, which
    # the fresh run still held in memory, so up to two evaluations of 24 points are run again
    assert 26 * 24 <= fresh_calls - CALLS[0] <= 28 * 24


def test_a_finished_log_resumes_to_the_same_result_with_no_new_evaluation(tmp_path):
    first = run_fit(tmp_path)
    before = (tmp_path / "log.jsonl").read_bytes()
    again = run_fit(tmp_path)
    assert (tmp_path / "log.jsonl").read_bytes() == before
    assert again.artefact == first.artefact and again.status == nfit.STATUS_OK


def test_a_recorded_vector_that_the_optimiser_does_not_ask_for_is_refused(tmp_path):
    run_fit(tmp_path)
    path = tmp_path / "log.jsonl"
    lines = path.read_text().splitlines()
    entry = json.loads(lines[5])
    entry["vector"]["tx_bandwidth_ghz"] += 0.5
    lines[5] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(nfit.FitRefusedError, match="not the one this run asks for"):
        run_fit(tmp_path)


def test_a_log_longer_than_the_run_is_refused(tmp_path):
    run_fit(tmp_path)
    path = tmp_path / "log.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines + [lines[-1]]) + "\n")
    with pytest.raises(nfit.FitRefusedError, match="more evaluations"):
        run_fit(tmp_path)


def test_no_fit_runs_once_a_freeze_record_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(nfz, "freeze_record_present", lambda: True)
    with pytest.raises(nfit.FitRefusedError, match="freeze record exists"):
        run_fit(tmp_path)
    assert not (tmp_path / "log.jsonl").exists()


# --- up to six processes, the same result (J-D) ------------------------------------------------


def test_six_processes_give_the_serial_result(tmp_path):
    vector = nfit.to_vector(np.array([0.3, 0.7, 0.2, 0.9, 0.4, 0.6]))
    serial = nfit.CalibrationObjective(stub_data(), stub_runner)
    with nfit.CalibrationObjective(stub_data(), stub_runner, workers=6) as parallel:
        assert parallel.points(vector) == serial.points(vector)
        assert np.array_equal(parallel.residuals(vector), serial.residuals(vector))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    one = run_fit(a)
    with nfit.CalibrationObjective(stub_data(), stub_runner, workers=3) as pool:
        many = run_fit(b, obj=pool)
    assert (a / "log.jsonl").read_bytes() == (b / "log.jsonl").read_bytes()
    assert one.artefact == many.artefact


def test_the_number_of_workers_is_one_to_six():
    for n in (0, 7):
        with pytest.raises(ValueError, match="workers"):
            nfit.CalibrationObjective(stub_data(), stub_runner, workers=n)
