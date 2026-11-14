"""N3b fix round, plan Amendment 12: the certificate of `converged` (S1 to S4), the evaluation log
that binds the fit code and does not trust a recorded cost, the final re-evaluation and the artefact
record of the log. Stub chain and synthetic functions only: no workbook, no simulation, no real data.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from nanf_fit_stub import CALLS, N_BITS, counting_runner, objective, stub_data, stub_runner
from nanf_freeze_support import good_checks
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_fit as nfit
from opticps.measurement import nanf_freeze as nfz
from opticps.measurement.nanf_freeze import HoldoutLockedError
from opticps.measurement.nanf_scoring import EvaluationLog, evaluate

PLAN = "a" * 64
CODE = "b" * 64
ROOT = Path(__file__).resolve().parents[1]


def run_fit(tmp_path, name="log.jsonl", obj=None, **kwargs):
    return nfit.fit(
        objective() if obj is None else obj,
        log_path=tmp_path / name,
        plan_sha256=PLAN,
        code_identity=CODE,
        **kwargs,
    )


def prior_unit():
    return np.array([(s.prior - s.low) / (s.high - s.low) for s in nc.B4_PARAMETERS])


def design_points():
    return [prior_unit(), *nfit.latin_hypercube()]


def no_library(monkeypatch):
    """A library search that stops at once: only the certificate of Amendment 12 is at work."""

    def stop_at_start(fun, x0, **kwargs):
        fun(np.asarray(x0, dtype=float))

    monkeypatch.setattr(nfit, "least_squares", stop_at_start)


# --- S1 to S4: when `converged` may be true -----------------------------------------------------


def test_s1_a_converged_search_holds_a_full_finite_difference_jacobian_at_its_point():
    seen = []

    def evaluate_u(u):
        seen.append(u.copy())
        r = np.array([4.0 * float(np.sum((u - 0.4) ** 2)) + 1.0])
        return float(r @ r), r

    result = nfit.run_optimiser(evaluate_u)
    assert result.converged

    def cost(u):
        return float((4.0 * np.sum((u - 0.4) ** 2) + 1.0) ** 2)

    def has_all_probes(x):
        for i in range(6):
            probe = x.copy()
            probe[i] += nfit.FD_STEP if x[i] + nfit.FD_STEP <= 1.0 else -nfit.FD_STEP
            if not any(np.array_equal(probe, u) for u in seen):
                return False
        return True

    lowest = min(cost(u) for u in seen)
    # the certified point has its six probes in the log, and nothing in the log beats it by TAU
    assert any(has_all_probes(x) and lowest >= (1.0 - nfit.TAU) * cost(x) for x in seen)


def test_s1_a_probe_that_loses_lock_ends_the_search_as_not_converged(monkeypatch):
    no_library(monkeypatch)
    start = min(design_points(), key=lambda u: float(np.sum(u)))  # the lowest cost below

    def evaluate_u(u):
        if len(seen) >= 25 and not np.array_equal(u, start):
            seen.append(u)
            return math.inf, None  # every point after the design loses lock
        seen.append(u)
        r = np.array([10.0 + float(np.sum(u))])
        return float(r @ r), r

    seen = []
    result = nfit.run_optimiser(evaluate_u)
    assert not result.converged and result.stopped == "a Jacobian point lost lock"
    assert result.n_evaluations == 26  # the first probe


def test_s2_a_predicted_decrease_above_tau_blocks_convergence_even_if_the_tested_step_is_not_lower(
    monkeypatch,
):
    no_library(monkeypatch)
    designs = design_points()

    def cost_of(u):
        return 100.0 + 1e-6 * float(np.sum(u))

    x_t = min(designs, key=cost_of)
    probes = []
    for i in range(6):
        probe = x_t.copy()
        probe[i] += nfit.FD_STEP if x_t[i] + nfit.FD_STEP <= 1.0 else -nfit.FD_STEP
        probes.append(probe)

    def evaluate_u(u):
        # a Jacobian probe is 0.5 below the point (the cost is 1 percent lower: within TAU), and
        # nowhere else is: the linear model predicts far more than TAU, the evaluated step is higher
        spike = any(np.array_equal(u, p) for p in probes)
        r = np.array([cost_of(u) - (0.5 if spike else 0.0)])
        return float(r @ r), r

    result = nfit.run_optimiser(evaluate_u)
    assert not result.converged


def test_s3_the_cost_at_the_tested_step_is_evaluated_and_a_drop_there_is_no_convergence(
    monkeypatch,
):
    no_library(monkeypatch)
    designs = design_points()
    x_t = min(designs, key=lambda u: 1000.0 + 1e-3 * u[0])  # the design point with the lowest u[0]
    assert x_t[0] > 0.02

    def evaluate_u(u):
        drop = 400.0 if u[0] < x_t[0] - 0.004 else 0.0  # a well that only a step into it can see
        r = np.array([1000.0 + 1e-3 * u[0] - drop])
        return float(r @ r), r

    result = nfit.run_optimiser(evaluate_u)
    assert result.n_evaluations > 25 + 6  # the six probes and at least one tested step
    deep = []

    def keep(u):
        f, r = evaluate_u(u)
        deep.append(f)
        return f, r

    nfit.run_optimiser(keep)
    best_design = min(float(evaluate_u(u)[0]) for u in designs)
    assert min(deep) < 0.9 * best_design  # the search went into the well and did not stop at x_t


def test_s4_nothing_in_the_log_may_beat_the_point_by_more_than_tau(monkeypatch):
    no_library(monkeypatch)
    designs = design_points()
    x_t = min(designs, key=lambda u: 1000.0 + 1e-3 * u[0])
    state = {"n": 0}

    def evaluate_u(u):
        state["n"] += 1
        wells = state["n"] > 25 and not np.array_equal(u, x_t) and u[0] < x_t[0]
        r = np.array([1000.0 + 1e-3 * u[0] - (300.0 if wells else 0.0)])
        return float(r @ r), r

    result = nfit.run_optimiser(evaluate_u)
    assert (
        not result.converged or state["n"] > 25 + 6 + 1
    )  # not stopped at x_t with the well in the log


def test_s2_a_coordinate_pushed_outward_at_a_range_edge_is_held_and_does_not_set_the_damping():
    u = np.array([0.0, 0.5, 0.5, 0.5, 0.5, 0.5])
    r = np.array([10.0, 0.3, -0.2, 0.0, 0.0, 0.0])  # J = I, so g = r: coordinate 0 is pushed out
    step, predicted = nfit.tested_step(u, r, np.eye(6))
    assert step[0] == 0.0
    for k in range(nfit.N_DAMPING):  # the ladder over the free coordinates alone
        move = -r[1:] / (1.0 + nfit.LM_DAMPING_MIN * 10.0**k)
        if float(np.max(np.abs(move))) <= nfit.RHO:
            break
    assert np.allclose(step[1:], u[1:] + move, rtol=0.0, atol=1e-12)
    after = r + (step - u)
    assert predicted == pytest.approx((float(r @ r) - float(after @ after)) / float(r @ r))


def test_s2_the_step_is_the_first_damping_that_stays_within_rho_and_stays_in_the_box():
    u = np.full(6, 0.5)
    r = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    step, predicted = nfit.tested_step(u, r, np.eye(6))
    assert float(np.max(np.abs(step - u))) <= nfit.RHO + 1e-12
    assert 0.0 < predicted < 1.0
    far, _ = nfit.tested_step(np.full(6, 0.99), np.full(6, -50.0), np.eye(6))
    assert np.all(far <= 1.0) and np.all(far >= 0.0)  # clipped to the box
    flat, none = nfit.tested_step(u, np.zeros(6), np.zeros((6, 6)))
    assert np.array_equal(flat, u) and none == 0.0


def test_the_library_is_called_with_the_options_the_amendment_states_and_a_lost_vector_is_bad(
    monkeypatch,
):
    seen = {}

    def fake(fun, x0, **kwargs):
        seen["lost"] = fun(np.full(6, 0.9))
        seen["options"] = kwargs

    monkeypatch.setattr(nfit, "least_squares", fake)

    def evaluate_u(u):
        if np.allclose(u, 0.9):
            return math.inf, None
        return 25.0, np.array([3.0, 4.0])

    nfit.run_optimiser(evaluate_u, budget=60)
    assert nfit.LOST_RESIDUAL == 1000.0 and np.array_equal(seen["lost"], np.full(2, 1000.0))
    options = dict(seen["options"])
    assert callable(options.pop("jac"))
    assert options == {
        "bounds": (0.0, 1.0), "method": "trf", "ftol": 0.01, "xtol": 0.01, "gtol": 0.01,
        "x_scale": 1.0, "loss": "linear", "tr_solver": "exact", "max_nfev": None,
    }  # fmt: skip


def test_a_coordinate_within_one_difference_step_of_an_edge_is_reported_and_beyond_it_is_not(
    tmp_path, monkeypatch
):
    assert nfit.RANGE_EDGE_TOL == nfit.FD_STEP == 0.01
    for value, expected in (
        (0.995, ("bias_fraction",)),
        (0.985, ()),
        (0.005, ("bias_fraction",)),
        (0.015, ()),
    ):
        monkeypatch.setattr(
            nfit, "to_unit", lambda vector, v=value: np.array([0.5, 0.5, 0.5, 0.5, v, 0.5])
        )
        out = run_fit(tmp_path, name=f"edge{value}.jsonl")
        assert out.status == nfit.STATUS_OK and out.at_range_edge == expected, value


def test_a_stalled_search_is_never_converged(tmp_path):
    out = run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), rough_runner_alias()))
    assert not out.converged and out.artefact is None


def rough_runner_alias():
    from nanf_fit_stub import rough_runner

    return rough_runner


def test_the_budget_is_140_and_one_evaluation_is_kept_for_the_final_re_evaluation():
    assert nfit.BUDGET == 140 and nfit.SEARCH_BUDGET == 139


def test_a_search_that_needs_more_than_its_budget_stops_at_budget_minus_one(tmp_path):
    CALLS[0] = 0
    out = run_fit(tmp_path, budget=30, obj=nfit.CalibrationObjective(stub_data(), counting_runner))
    assert not out.converged and out.n_evaluations == 29 and CALLS[0] == 29 * 24
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 30


# --- the log binds the fit code ------------------------------------------------------------------


def test_the_log_header_holds_the_hash_of_the_fit_module_and_of_the_fit_script(tmp_path):
    run_fit(tmp_path)
    header = json.loads((tmp_path / "log.jsonl").read_text().splitlines()[0])
    module = Path(nfit.__file__).read_bytes()
    script = (ROOT / "scripts/nanf_fit.py").read_bytes()
    assert header["fit_module_sha256"] == hashlib.sha256(module).hexdigest()
    assert header["fit_script_sha256"] == hashlib.sha256(script).hexdigest()


@pytest.mark.parametrize("field", ["fit_module_sha256", "fit_script_sha256"])
def test_a_log_made_by_another_fit_module_or_script_is_refused(tmp_path, field):
    run_fit(tmp_path)
    edited = {**nfit.fit_identity(), field: "0" * 64}
    with pytest.raises(nfit.FitRefusedError, match="another run"):
        run_fit(tmp_path, fit_code=edited)


@pytest.mark.parametrize("field", ["numpy_version", "scipy_version"])
def test_a_log_made_with_another_library_version_is_refused(tmp_path, field):
    run_fit(tmp_path)
    header = json.loads((tmp_path / "log.jsonl").read_text().splitlines()[0])
    assert header[field] == nfit.fit_identity()[field] != "0.0.1"
    with pytest.raises(nfit.FitRefusedError, match="another run"):
        run_fit(tmp_path, fit_code={**nfit.fit_identity(), field: "0.0.1"})


# --- a replay does not trust a recorded cost -----------------------------------------------------


def _edit(tmp_path, index, change):
    path = tmp_path / "log.jsonl"
    lines = path.read_text().splitlines()
    entry = json.loads(lines[index])
    change(entry)
    lines[index] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")


def test_a_recorded_cost_that_is_not_the_cost_of_its_residuals_is_refused(tmp_path):
    run_fit(tmp_path)
    _edit(tmp_path, 28, lambda e: e.update(objective=0.01))
    with pytest.raises(nfit.FitRefusedError, match="not its residuals"):
        run_fit(tmp_path)


def test_a_recorded_cost_one_unit_in_the_last_place_off_is_refused(tmp_path):
    run_fit(tmp_path)
    _edit(tmp_path, 3, lambda e: e.update(objective=math.nextafter(e["objective"], math.inf)))
    with pytest.raises(nfit.FitRefusedError, match="not its residuals"):
        run_fit(tmp_path)


def test_infinity_must_go_with_lost_points_and_lost_points_with_infinity(tmp_path):
    run_fit(tmp_path)
    lost_at = next(
        i for i, x in enumerate((tmp_path / "log.jsonl").read_text().splitlines()[1:], 1)
        if json.loads(x)["lost"]
    )  # fmt: skip
    ok_at = next(
        i for i, x in enumerate((tmp_path / "log.jsonl").read_text().splitlines()[1:], 1)
        if not json.loads(x)["lost"]
    )  # fmt: skip
    original = (tmp_path / "log.jsonl").read_text()
    _edit(tmp_path, lost_at, lambda e: e.update(lost=[]))  # +inf without a lost point
    with pytest.raises(nfit.FitRefusedError, match="lost points and cost disagree"):
        run_fit(tmp_path)
    (tmp_path / "log.jsonl").write_text(original)
    _edit(tmp_path, ok_at, lambda e: e.update(lost=["x"]))  # a lost point with a finite cost
    with pytest.raises(nfit.FitRefusedError, match="lost points and cost disagree"):
        run_fit(tmp_path)
    (tmp_path / "log.jsonl").write_text(original)
    _edit(tmp_path, lost_at, lambda e: e.update(objective=1.0))  # a finite cost, no residuals
    with pytest.raises(nfit.FitRefusedError, match="lost points and cost disagree"):
        run_fit(tmp_path)


def test_a_residual_that_is_not_finite_is_refused(tmp_path):
    run_fit(tmp_path)
    _edit(tmp_path, 4, lambda e: e["residuals"].__setitem__(0, None))
    with pytest.raises((nfit.FitRefusedError, TypeError, ValueError)):
        run_fit(tmp_path)


# --- the final re-evaluation ---------------------------------------------------------------------


def test_the_selected_vector_is_evaluated_once_more_with_every_point_run_again():
    CALLS[0] = 0
    obj = nfit.CalibrationObjective(stub_data(), counting_runner)
    vector = nfit.to_vector(np.full(6, 0.45))
    first = obj.cost(vector)
    assert obj.cost(vector) == first and CALLS[0] == 24  # a repeat is kept
    assert obj.fresh_cost(vector) == first and CALLS[0] == 48  # the fresh call runs the points


def test_a_cost_that_differs_in_the_last_bit_at_the_re_evaluation_is_refused(tmp_path):
    seen = {}

    def drifting(task):
        key = (task.vector, task.rate, task.point_index)
        seen[key] = seen.get(key, 0) + 1
        s = stub_runner(task)
        if seen[key] == 1 or s.lost:
            return s
        return type(s)(False, "", s.ber, math.nextafter(s.snr_db, math.inf), s.n_bits)

    with pytest.raises(nfit.FitRefusedError, match="evaluated again"):
        run_fit(tmp_path, obj=nfit.CalibrationObjective(stub_data(), drifting))


def test_a_run_whose_re_evaluation_agrees_is_calibrated(tmp_path):
    out = run_fit(tmp_path)
    assert out.status == nfit.STATUS_OK and out.chosen is not None


# --- resume, processes, a cut last line ---------------------------------------------------------


def test_a_resume_from_every_few_lines_equals_an_uninterrupted_run_byte_for_byte(tmp_path):
    full_dir = tmp_path / "full"
    full_dir.mkdir()
    full = run_fit(full_dir)
    text = (full_dir / "log.jsonl").read_text()
    lines = text.splitlines(keepends=True)
    for kept in (1, 2, 26, len(lines) // 2, len(lines) - 1):
        d = tmp_path / f"cut{kept}"
        d.mkdir()
        (d / "log.jsonl").write_text("".join(lines[:kept]))
        resumed = run_fit(d)
        assert (d / "log.jsonl").read_bytes() == text.encode()
        assert resumed.artefact == full.artefact and resumed.n_evaluations == full.n_evaluations


def test_six_processes_give_the_serial_log_and_artefact_byte_for_byte(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    serial = run_fit(a)
    with nfit.CalibrationObjective(stub_data(), stub_runner, workers=6) as pool:
        parallel = run_fit(b, obj=pool)
    assert (a / "log.jsonl").read_bytes() == (b / "log.jsonl").read_bytes()
    assert serial.artefact == parallel.artefact


def test_a_log_whose_last_line_is_cut_short_is_a_permanent_refusal(tmp_path):
    run_fit(tmp_path)
    path = tmp_path / "log.jsonl"
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 40])  # the last line stops inside a number
    with pytest.raises(nfit.FitRefusedError, match="not a resume"):
        run_fit(tmp_path)
    assert path.read_bytes() == raw[: len(raw) - 40]  # and nothing was written to it


# --- the artefact records the log ---------------------------------------------------------------


def test_the_artefact_records_the_sha256_of_the_evaluation_log(tmp_path):
    out = run_fit(tmp_path)
    checks = json.loads(out.artefact)["checks"]
    assert (
        checks["evaluation_log_sha256"]
        == hashlib.sha256((tmp_path / "log.jsonl").read_bytes()).hexdigest()
    )
    nfz._check_checks(checks, tuple(json.loads(out.artefact)["unidentifiable"]))


@pytest.mark.parametrize("bad", [None, "", "e" * 63, "E" * 64, "e" * 64 + "\n", 7, ["e" * 64]])
def test_a_calibration_artefact_without_a_well_formed_log_hash_is_refused(bad):
    checks = {**good_checks(1), "evaluation_log_sha256": bad}
    with pytest.raises(HoldoutLockedError, match="evaluation log"):
        nfz._check_checks(checks, ("bias_fraction",))
    missing = {k: v for k, v in good_checks(1).items() if k != "evaluation_log_sha256"}
    with pytest.raises((HoldoutLockedError, KeyError)):
        nfz._check_checks(missing, ("bias_fraction",))


def test_the_default_log_path_is_the_one_the_amendment_names():
    assert nfit.DEFAULT_LOG_PATH == ROOT / "docs/benchmarks/NANF_FIT_EVALUATION_LOG.jsonl"


def test_the_fit_script_has_no_log_option_and_prints_the_commit_rule():
    text = (ROOT / "scripts/nanf_fit.py").read_text()
    assert '"--log"' not in text and "log_path=nanf_fit.DEFAULT_LOG_PATH" in text
    assert "commit" in text and "same commit" in text


def test_a_lost_point_vector_still_costs_plus_infinity_and_is_logged():
    log = EvaluationLog()
    ev = evaluate(log, nfit.to_vector(np.array([0.0, 0.5, 0.5, 0.5, 0.5, 0.5])), objective().cost)
    assert ev.objective == math.inf and N_BITS > 0
