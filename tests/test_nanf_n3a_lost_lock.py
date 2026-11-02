"""Gate N3 part a, plan Amendment 7: lost-lock runs are invalid, reported, and never help a score.

Synthetic data only. No workbook is read, no fit is run, nothing is frozen.
"""

import dataclasses
import math

import numpy as np
import pytest

from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_scoring as sc
from opticps.receiver.dfe import RlsInstabilityError

SMALL = nc.ChainConfig(n_symbols=14_000, training_symbols=2_000)
MID = nc.TxRxParameters()
NAN = math.nan
ROP = [-14.0, -13.0, -12.0, -11.0, -10.0, -9.0, -8.0]
BER = [NAN, NAN, 0.2, 0.05, 1e-2, 1e-3, 1e-4]
LOCKED = [False, False, True, True, True, True, True]


def healthy_result():
    run = nc.simulate_point(MID, 80, -5.0, config=SMALL)
    return dataclasses.replace(run, unscorable_reasons=())  # stands in for a scorable full run


# --- rule 1: reported with its point and reason, never scored, never silently skipped -----------


def test_a_run_where_the_cap_acts_is_a_lost_outcome_with_its_point_and_reason(monkeypatch):
    monkeypatch.setattr(nc, "PINNED_P_TRACE_CAP", 1e4)  # the cap now acts on this small real run
    out = nc.run_point("80G/B2B/-9", MID, 80, -9.0, config=SMALL)
    assert out.lost and out.result is None and "trace cap acted" in out.reason
    assert out.label == "80G/B2B/-9" and out.rop_dbm == -9.0
    report = nc.lost_report([out])
    assert len(report) == 1 and "80G/B2B/-9" in report[0] and "trace cap acted" in report[0]
    with pytest.raises(nc.NotScorableError):  # a lost outcome can never enter a score
        nc.require_scorable([out])


def test_an_instability_is_a_lost_outcome_too(monkeypatch):
    def boom(*a, **k):
        raise RlsInstabilityError("P lost positive definiteness at symbol 5")

    monkeypatch.setattr(nc, "simulate_point", boom)
    out = nc.run_point("112G/SSMF/-10", MID, 112, -10.0)
    assert (
        out.lost and "RlsInstabilityError" in out.reason and "positive definiteness" in out.reason
    )
    assert "112G/SSMF/-10" in nc.lost_report([out])[0]


def test_other_errors_are_not_swallowed_and_an_unscorable_result_is_refused(monkeypatch):
    unscorable = nc.simulate_point(MID, 80, -5.0, config=SMALL)  # config override: not scorable

    def refuse(*a, **k):
        raise nc.FrozenOverrideError("override")

    monkeypatch.setattr(nc, "simulate_point", refuse)
    with pytest.raises(nc.FrozenOverrideError):
        nc.run_point("x", MID, 80, -5.0)
    monkeypatch.setattr(nc, "simulate_point", lambda *a, **k: unscorable)
    with pytest.raises(nc.NotScorableError):
        nc.run_point("x", MID, 80, -5.0)


def test_a_good_outcome_carries_a_scorable_result_and_lost_ones_stay_in_the_arrays(monkeypatch):
    good = healthy_result()
    monkeypatch.setattr(nc, "simulate_point", lambda *a, **k: good)
    ok = nc.run_point("p", MID, 80, -5.0)
    assert not ok.lost and ok.result is good and nc.lost_report([ok]) == []
    lost = nc.PointOutcome("q", -12.0, None, "RlsInstabilityError: x")
    arrays = nc.curve_arrays([lost, ok])
    assert list(arrays.valid) == [False, True] and arrays.n_lost == 1
    assert math.isnan(arrays.ber[0]) and math.isnan(arrays.snr_db[0])  # not zero, not censored
    assert arrays.rop_dbm.tolist() == [-12.0, -5.0]  # the lost point keeps its place


# --- rule 2: the crossing from a contiguous locked run that brackets the threshold --------------


def test_lost_points_below_the_bracket_do_not_affect_the_crossing_and_are_counted():
    got = sc.c1_crossing(ROP, BER, valid=LOCKED)
    ref = sc.c1_crossing(ROP[2:], BER[2:])
    assert got.kind == "point" and got.x == ref.x and got.n_lost == 2
    # the value stored at a lost point is irrelevant
    other = sc.c1_crossing(ROP, [1e-9, 5.0, *BER[2:]], valid=LOCKED)
    assert other.x == ref.x
    score = sc.score_c1(sc.Crossing("point", ref.x, ref.x), got)
    assert score.passed and score.n_lost == 2


def test_a_lost_point_above_the_locked_run_makes_the_curve_invalid():
    got = sc.c1_crossing(ROP, BER, valid=[False, False, True, True, True, False, True])
    assert got.kind == "invalid" and got.n_lost == 3  # the run above the lost point has no bracket
    top = sc.c1_crossing(ROP, BER, valid=[False, False, True, True, True, True, False])
    assert top.kind == "invalid" and "above the locked run" in top.reason
    assert sc.score_c1(sc.Crossing("point", -9.5, -9.5), top).passed is False


def test_the_crossing_is_never_interpolated_across_a_lost_point():
    # locked 1e-2 and 1e-4 on either side of a lost point would bracket 3.8e-3 only across it
    got = sc.c1_crossing([-12.0, -11.0, -10.0], [1e-2, NAN, 1e-4], valid=[True, False, True])
    assert got.kind == "invalid" and "no bracket" in got.reason
    assert sc.score_c1(sc.Crossing("point", -11.0, -11.0), got).passed is False


def test_no_bracket_among_locked_points_fails_under_the_no_crossing_rule():
    low = sc.c1_crossing(ROP, [NAN, NAN, 1e-4, 1e-4, 1e-5, 1e-5, 1e-5], valid=LOCKED)
    assert low.kind == "invalid" and low.n_lost == 2
    high = sc.c1_crossing(ROP, [NAN, NAN, 0.3, 0.2, 0.1, 0.05, 0.04], valid=LOCKED)
    assert high.kind == "invalid"
    for sim in (low, high):
        assert sc.score_c1(sc.Crossing("point", -9.0, -9.0), sim).passed is False
        assert sc.score_c1(sc.Crossing("left", -math.inf, -12.0), sim).passed is False
    every = sc.c1_crossing(ROP, [NAN] * 7, valid=[False] * 7)
    assert every.kind == "invalid" and every.n_lost == 7
    assert "every point lost lock" in every.reason  # not the lost-above-the-run reason


def test_a_nan_at_a_locked_point_is_still_invalid_data_and_the_mask_must_be_boolean():
    nan_locked = sc.c1_crossing(ROP, [NAN, NAN, 0.2, NAN, 1e-2, 1e-3, 1e-4], valid=LOCKED)
    assert nan_locked.kind == "invalid"
    for junk in ([1, 1, 1, 1, 1, 1, 1], ["yes"] * 7, [True] * 6):
        with pytest.raises(ValueError, match="boolean"):
            sc.c1_crossing(ROP, BER, valid=junk)
    assert sc.c1_crossing(ROP, [0.2, 0.05, 1e-2, 1e-3, 1e-4, 1e-4, 1e-4]).n_lost == 0


# --- rule 3: a criterion that needs a lost point fails; no substitution, no interpolation -------


def test_c2_c3_c4_c5_and_the_b2b_gate_fail_when_a_needed_point_is_lost():
    rop = [-9.0, -8.0, -7.0, -6.0]
    snr = [10.0, 11.0, 12.0, 13.0]
    ok = [True, False, True, True]
    assert sc.score_c2(rop, snr, snr).passed  # every point locked and exact
    got = sc.score_c2(rop, [10.0, NAN, 12.0, 13.0], snr, simulated_valid=ok)
    assert got.passed is False and got.n_invalid == 1 and "lost" in got.reason
    # a lost point above the -5 dBm cap is not scored, so it cannot fail the criterion
    cap = sc.score_c2([-9.0, -4.0], [10.0, NAN], [10.0, 10.0], simulated_valid=[True, False])
    assert cap.passed and cap.n_invalid == 0

    wl = [1460.0 + 10.0 * k for k in range(17)]
    s17 = [20.0] * 17
    assert sc.score_c5("nanf", wl, s17, s17).passed
    mask = [True] * 17
    mask[4] = False
    c5 = sc.score_c5("nanf", wl, s17, s17, simulated_valid=mask)
    assert c5.passed is False and c5.n_invalid == 1

    n_rop, s_rop = [-9.0, -8.0], [-9.0, -8.0]
    args = (80, n_rop, [20.0, 21.0], s_rop, [15.0, 16.0], [0.1, 0.1])
    assert sc.score_c3(*args).passed
    for kw in ({"nanf_valid": [True, False]}, {"ssmf_valid": [False, True]}):
        c3 = sc.score_c3(*args, **kw)
        assert c3.passed is False and "lost-lock" in c3.reason

    rop4 = [-9.0, -8.0, -7.0]
    pub = [1e-2, 1e-3, 1e-4]
    assert sc.score_c4(rop4, pub, pub, 10**6).passed
    c4 = sc.score_c4(rop4, pub, [1e-2, NAN, 1e-4], 10**6, simulated_valid=[True, False, True])
    assert c4.passed is False and c4.n_invalid == 1

    point = sc.Crossing("point", -9.0, -9.0)
    snr2 = [10.0, 11.0]
    assert sc.b2b_gate(snr2, snr2, point, point).passed
    gate = sc.b2b_gate(snr2, snr2, point, point, simulated_valid=[True, False])
    assert gate.passed is False and gate.label == "B2B CALIBRATION POOR"


# --- rule 4: calibration evaluations --------------------------------------------------------


def lost_objective(vector):
    if vector["tx_bandwidth_ghz"] > 40.0:
        raise sc.EvaluationLostLockError(["80G/B2B/-14", "100G/B2B/-15"])
    return abs(vector["tx_bandwidth_ghz"] - 30.0)


def test_an_evaluation_with_a_lost_point_gets_the_worst_case_is_counted_logged_and_never_chosen():
    log = sc.EvaluationLog()
    good = sc.evaluate(log, {"tx_bandwidth_ghz": 31.0}, lost_objective)
    bad = sc.evaluate(log, {"tx_bandwidth_ghz": 50.0}, lost_objective)
    assert good.objective == 1.0 and good.n_lost == 0
    assert bad.objective == sc.WORST_CASE_OBJECTIVE == math.inf and bad.n_lost == 2
    assert log.n_worst_case == 1 and len(log.evaluations) == 2
    lines = log.lines()
    assert len(lines) == 1 and "80G/B2B/-14" in lines[0] and "WORST-CASE" in lines[0]
    # the worst case can never be selected, even when it is the only one that "improves"
    assert sc.select_best(log) is good
    only_bad = sc.EvaluationLog()
    sc.evaluate(only_bad, {"tx_bandwidth_ghz": 50.0}, lost_objective)
    with pytest.raises(sc.NoValidFitError):
        sc.select_best(only_bad)
    with pytest.raises(sc.NoValidFitError, match="B2B calibration grid"):
        sc.check_chosen_fit(bad)
    assert sc.check_chosen_fit(good) is good
    # selection also skips a recorded lost evaluation with a finite objective, and a non-finite one
    mixed = sc.EvaluationLog()
    mixed.record(sc.Evaluation({"x": 1.0}, 0.1, ("p",)))  # lost, objective looks excellent
    mixed.record(sc.Evaluation({"x": 2.0}, math.inf, ()))
    mixed.record(sc.Evaluation({"x": 3.0}, 7.0, ()))
    assert sc.select_best(mixed).vector == {"x": 3.0}
    with pytest.raises(sc.NoValidFitError):
        sc.check_chosen_fit(sc.Evaluation({"x": 2.0}, math.inf, ()))
    only_inf = sc.EvaluationLog()
    only_inf.record(sc.Evaluation({"x": 2.0}, math.inf, ()))
    with pytest.raises(sc.NoValidFitError):  # an infinite objective is no clean evaluation
        sc.select_best(only_inf)
    with pytest.raises(sc.NoValidFitError):
        sc.check_chosen_fit(sc.Evaluation({"x": 1.0}, 0.0, ("p",)))  # objective 0 with a lost point
    with pytest.raises(ValueError, match="not finite"):
        sc.evaluate(log, {"tx_bandwidth_ghz": 31.0}, lambda v: math.nan)  # NaN is not a lost run


def test_a_worst_case_value_never_enters_the_identifiability_jacobian():
    names = [s.name for s in sc.B4_PARAMETERS]
    optimum = {s.name: 0.5 * (s.low + s.high) for s in sc.B4_PARAMETERS}

    def fine(values):
        return np.array([values[n] / 100.0 for n in names])

    sc.identifiability_check(fine, optimum)  # the check itself still works

    calls = {"n": 0}

    def lost_at_a_step(values):
        calls["n"] += 1
        if calls["n"] == 5:  # a finite-difference evaluation near the optimum
            raise sc.EvaluationLostLockError(["80G/B2B/-14"])
        return fine(values)

    with pytest.raises(sc.IdentifiabilityUndefinedError, match="no Jacobian, no flags"):
        sc.identifiability_check(lost_at_a_step, optimum)

    def lost_at_optimum(values):
        raise sc.EvaluationLostLockError(["100G/B2B/-15"])

    with pytest.raises(sc.IdentifiabilityUndefinedError, match="100G/B2B/-15"):
        sc.identifiability_check(lost_at_optimum, optimum)
