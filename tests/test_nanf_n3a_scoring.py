"""Gate N3 part a: criterion scoring C1 to C8, B2B-copy, d, the B2B gate, the verdict and the
identifiability check, on synthetic series only. No workbook value is used."""

import math

import numpy as np
import pytest

from opticps.measurement import nanf_scoring as sc
from opticps.measurement.nanf_chain import B4_NAMES, B4_PARAMETERS

R = [-12.0, -11.0, -10.0, -9.0]  # rising ROP, dBm


def crossing(ber, rop=None):
    return sc.c1_crossing(R if rop is None else rop, ber)


# --- C1, the crossing rule: every worked case of Amendment 3 and the rest ------------------------


def test_c1_worked_cases_of_the_amendment():
    c = crossing([1e-2, 1e-3, 6e-3, 0.0])  # above, below, above, censored: interval [r3, r4]
    assert (c.kind, c.lo, c.hi) == ("interval", -10.0, -9.0)
    c = crossing([1e-2, 1e-3, 6e-3, 5e-3])  # ends above: right-censored "above r4"
    assert (c.kind, c.lo, c.hi) == ("right", -9.0, math.inf)
    c = crossing([1e-2, 1e-3, 6e-3, 1e-3])  # last downward bracket is r3 to r4
    assert c.kind == "point" and -10.0 < c.x < -9.0
    la, lb, lt = math.log10(6e-3), math.log10(1e-3), math.log10(3.8e-3)
    assert c.x == pytest.approx(-10.0 + (lt - la) / (lb - la))
    c = crossing([1e-2, 1e-3, 0.0, 0.0])  # crossing between r1 and r2
    assert c.kind == "point" and -12.0 < c.x < -11.0
    c = crossing([1e-2, 5e-3, 0.0, 0.0])  # interval [r2, r3]
    assert (c.kind, c.lo, c.hi) == ("interval", -11.0, -10.0)


def test_c1_interpolates_log10_ber_linearly_in_rop_and_hits_the_threshold_exactly():
    c = crossing([1e-1, 1e-3, 1e-4, 1e-5])
    expected = -12.0 + (math.log10(3.8e-3) - math.log10(1e-1)) / (
        math.log10(1e-3) - math.log10(1e-1)
    )
    assert c.kind == "point" and c.x == pytest.approx(expected)
    # a point exactly at the threshold counts as above
    at_limit = crossing([1e-2, 3.8e-3, 1e-3, 1e-4])
    assert at_limit.kind == "point" and at_limit.x == pytest.approx(-11.0)  # the bracket is r2, r3


def test_c1_last_downward_bracket_is_taken_when_there_are_several():
    r = [-12.0, -11.0, -10.0, -9.0, -8.0, -7.0]
    c = sc.c1_crossing(r, [1e-2, 1e-3, 1e-2, 1e-3, 2e-2, 1e-4])
    assert c.kind == "point" and -8.0 < c.x < -7.0


def test_c1_left_and_right_censoring_and_all_censored():
    c = crossing([1e-4, 1e-5, 1e-5, 1e-5])  # first scored point already below
    assert (c.kind, c.hi) == ("left", -12.0)
    c = crossing([float("nan")] * 4)
    assert (c.kind, c.hi) == ("left", -12.0)
    c = crossing([1e-1, 5e-2, 2e-2, 1e-2])  # never below
    assert (c.kind, c.lo) == ("right", -9.0)
    c = crossing([1e-2, 1e-3, 5e-6, float("nan")])  # censored points are never nodes
    assert c.kind == "point" and -12.0 < c.x < -11.0


def test_c1_censoring_boundary_is_below_1e_minus_5():
    assert sc.is_censored(1e-5).item() is False
    assert sc.is_censored(9.99e-6).item() is True
    assert sc.is_censored(0.0).item() is True and sc.is_censored(float("nan")).item() is True
    assert sc.is_censored(float("inf")).item() is True


def test_c1_drops_points_above_the_rop_cap_and_refuses_bad_axes():
    r = [-8.0, -7.0, -6.0, -5.0, -4.0, -3.0]
    c = sc.c1_crossing(r, [1e-1, 1e-2, 1e-3, 1e-4, 1e-9, 1e-9])  # -4 and -3 are above the cap
    assert c.kind == "point" and -7.0 < c.x < -6.0
    # exactly -5.0 is scored
    c2 = sc.c1_crossing([-6.0, -5.0], [1e-2, 1e-4])
    assert c2.kind == "point" and -6.0 < c2.x < -5.0
    with pytest.raises(ValueError, match="no scored point"):
        sc.c1_crossing([-4.0, -3.0], [1e-2, 1e-3])
    with pytest.raises(ValueError, match="strictly increasing"):
        sc.c1_crossing([-9.0, -9.0, -8.0], [1e-2, 1e-3, 1e-4])
    with pytest.raises(ValueError):
        sc.c1_crossing([-9.0, float("nan")], [1e-2, 1e-3])
    with pytest.raises(ValueError):
        sc.c1_crossing([-9.0, -8.0], [1e-2])
    with pytest.raises(ValueError, match="in \\(0, 1\\]"):
        sc.c1_crossing([-9.0, -8.0], [2.0, 1e-3])


def P(x):
    return sc.Crossing("point", x, x)


def test_c1_scoring_of_points_with_the_1_db_tolerance():
    assert sc.score_c1(P(-10.0), P(-9.0)).passed and sc.score_c1(P(-10.0), P(-11.0)).passed
    assert (
        not sc.score_c1(P(-10.0), P(-8.99)).passed and not sc.score_c1(P(-10.0), P(-11.01)).passed
    )
    s = sc.score_c1(P(-10.0), P(-10.2))
    assert s.both_points
    assert not sc.score_c1(P(-10.0), P(-9.0), tol=0.5).passed  # the B2B gate tolerance


def test_c1_scoring_of_bounds_and_intervals_follows_b1_3():
    left = sc.Crossing("left", -math.inf, -12.0)  # published "at or below -12"
    right = sc.Crossing("right", -7.0, math.inf)  # published "above -7"
    interval = sc.Crossing("interval", -10.0, -9.0)
    # left bound: simulated x <= r0 + 1; far below passes (one-sided)
    assert sc.score_c1(left, P(-11.0)).passed and sc.score_c1(left, P(-30.0)).passed
    assert not sc.score_c1(left, P(-10.9)).passed
    # right bound: x >= r0 - 1
    assert sc.score_c1(right, P(-8.0)).passed and sc.score_c1(right, P(5.0)).passed
    assert not sc.score_c1(right, P(-8.1)).passed
    # interval: lo - 1 <= x <= hi + 1
    assert sc.score_c1(interval, P(-11.0)).passed and sc.score_c1(interval, P(-8.0)).passed
    assert not sc.score_c1(interval, P(-11.1)).passed and not sc.score_c1(interval, P(-7.9)).passed
    assert not sc.score_c1(left, P(-11.0)).both_points  # a bound is never discriminating
    # a published point against a simulated curve with no crossing fails (B1.3)
    assert not sc.score_c1(P(-10.0), sc.Crossing("left", -math.inf, -12.0)).passed
    assert not sc.score_c1(P(-10.0), sc.Crossing("right", -9.0, math.inf)).passed
    # a simulated interval passes if it meets the widened region
    assert sc.score_c1(P(-10.0), sc.Crossing("interval", -8.0, -7.0)).passed is False
    assert sc.score_c1(P(-10.0), sc.Crossing("interval", -9.5, -7.0)).passed
    # a simulated bound against a published bound is read at its ROP
    assert sc.score_c1(left, sc.Crossing("left", -math.inf, -12.0)).passed
    assert not sc.score_c1(right, sc.Crossing("left", -math.inf, -12.0)).passed
    assert sc.score_c1(right, sc.Crossing("right", -8.0, math.inf)).passed


def test_crossing_value_is_defined_for_points_only():
    assert P(-3.0).x == -3.0
    with pytest.raises(ValueError):
        sc.Crossing("left", -math.inf, -3.0).x


# --- C2, C8, C5 ---------------------------------------------------------------------------------


def test_c2_mean_and_max_thresholds_are_inclusive_and_the_cap_applies():
    rop = [-12.0, -11.0, -10.0, -9.0]
    pub = [15.0, 16.0, 17.0, 18.0]
    assert sc.score_c2(rop, [x + 1.5 for x in pub], pub).passed  # mean 1.5 exactly
    assert not sc.score_c2(rop, [x + 1.51 for x in pub], pub).passed
    s = sc.score_c2(rop, [pub[0] + 3.0, pub[1], pub[2], pub[3]], pub)  # max 3.0 exactly, mean 0.75
    assert s.passed and s.max_abs_db == pytest.approx(3.0)
    assert not sc.score_c2(rop, [pub[0] + 3.01, pub[1], pub[2], pub[3]], pub).passed
    # points above -5 dBm are not scored: a huge error there is ignored
    rop2 = [-7.0, -6.0, -5.0, -4.0]
    sim = [15.0, 16.0, 17.0, 99.0]
    assert sc.score_c2(rop2, sim, [15.0, 16.0, 17.0, 18.0]).n_points == 3
    assert sc.score_c2(rop2, sim, [15.0, 16.0, 17.0, 18.0]).passed
    with pytest.raises(ValueError):
        sc.score_c2(rop, [1.0, 2.0, float("nan"), 4.0], pub)
    with pytest.raises(ValueError):
        sc.score_c2([-4.0, -3.0], [1.0, 2.0], [1.0, 2.0])


def test_c8_tolerances_are_2_db_nanf_and_3_db_ssmf():
    assert sc.score_c8("nanf", [10.0, 12.0], [11.0, 13.0]).passed
    assert sc.score_c8("nanf", [10.0, 12.0], [12.0, 14.0]).passed  # mean 2.0 inclusive
    assert not sc.score_c8("nanf", [10.0, 12.0], [12.01, 14.01]).passed
    assert sc.score_c8("ssmf", [10.0, 12.0], [13.0, 15.0]).passed
    assert not sc.score_c8("ssmf", [10.0, 12.0], [13.01, 15.01]).passed
    for bad in ("b2b", ""):
        with pytest.raises(ValueError):
            sc.score_c8(bad, [1.0], [1.0])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        sc.score_c8("nanf", [1.0], [1.0, 2.0])


WL = [1460.0 + 10.0 * k for k in range(19)]  # 19 published points


def test_c5_scores_the_17_wavelengths_and_reports_1630_and_1640_apart():
    pub = [20.0] * 19
    sim = [20.0 + (50.0 if w > 1620 else 0.0) for w in WL]  # a huge error only at 1630 and 1640
    s = sc.score_c5("nanf", WL, sim, pub)
    assert s.passed and s.n_points == 17 and s.excluded_nm == (1630.0, 1640.0)
    assert s.mean_abs_db == 0.0
    # the thresholds: NANF 2.0, SSMF 3.0, B2B 2.0 dB
    for link, tol in (("nanf", 2.0), ("ssmf", 3.0), ("b2b", 2.0)):
        assert sc.score_c5(link, WL, [20.0 + tol] * 19, pub).passed
        assert not sc.score_c5(link, WL, [20.0 + tol + 0.01] * 19, pub).passed
    # exactly the 17 wavelengths are needed (no silent change of the criterion)
    with pytest.raises(ValueError, match="17 wavelengths"):
        sc.score_c5("nanf", WL[1:], sim[1:], pub[1:])
    with pytest.raises(ValueError, match="17 wavelengths"):
        sc.score_c5("nanf", WL[:17][::-1], sim[:17], pub[:17])
    with pytest.raises(ValueError):
        sc.score_c5("ssmf", WL, sim, [float("nan")] + pub[1:])
    with pytest.raises(ValueError):
        sc.score_c5("other", WL, sim, pub)  # type: ignore[arg-type]
    assert sc.score_c5("nanf", WL[:17], sim[:17], pub[:17]).excluded_nm == ()


# --- C3 ------------------------------------------------------------------------------------------

N_ROP = [-12.0, -11.0, -10.0, -9.0, -8.0, -7.0]


def c3(rate, penalty, ssmf_ber=None, ssmf_rop=None):
    s_rop = np.array([-11.0, -10.0, -9.0, -8.0, -7.0, -6.0] if ssmf_rop is None else ssmf_rop)
    nanf = 20.0 + np.arange(len(N_ROP))  # = 32 + rop at the ROPs of N_ROP
    ssmf = 32.0 + s_rop - penalty  # the SSMF line: NANF minus `penalty` at every ROP
    ber = np.full(s_rop.size, 1e-2) if ssmf_ber is None else np.array(ssmf_ber, float)
    return sc.score_c3(rate, N_ROP, nanf, s_rop, ssmf, ber)


def test_c3_penalty_tolerance_is_3_db_inclusive_around_5_11_and_14():
    # NANF SNR = 32 + rop and SSMF SNR = 32 + rop - penalty: the penalty is the same at every ROP
    assert sc.STATED_PENALTY_DB == {80: 5.0, 100: 11.0, 112: 14.0}
    for rate, stated in sc.STATED_PENALTY_DB.items():
        assert c3(rate, stated).passed
        assert c3(rate, stated + 3.0).penalty_ok and c3(rate, stated - 3.0).penalty_ok
        assert not c3(rate, stated + 3.01).penalty_ok and not c3(rate, stated - 3.01).penalty_ok
    s = c3(100, 11.0)
    assert s.simulated_penalty_db == pytest.approx(11.0) and s.n_points == 5  # -11 to -7 overlap
    assert s.published_penalty_db is None


def test_c3_ssmf_ber_must_be_above_the_limit_at_every_scored_point_and_zero_errors_fail():
    assert c3(80, 5.0, ssmf_ber=[1e-2] * 6).passed
    s = c3(
        80, 5.0, ssmf_ber=[1e-2, 1e-2, 3.8e-3, 1e-2, 1e-2, 1e-2]
    )  # equal to the limit: not above
    assert not s.ssmf_ber_ok and not s.passed and s.reason == "SSMF BER at or below 3.8e-3"
    assert not c3(80, 5.0, ssmf_ber=[1e-2] * 5 + [0.0]).ssmf_ber_ok  # zero errors read "below 1/N"
    # a SSMF point above -5 dBm is not scored: its BER does not matter
    s = sc.score_c3(
        80, N_ROP, 20.0 + np.arange(6), [-11.0, -9.0, -4.0], [14.0, 16.0, 18.0], [1e-2, 1e-2, 1e-9]
    )
    assert s.ssmf_ber_ok
    with pytest.raises(ValueError):
        c3(80, 5.0, ssmf_ber=[1e-2, float("nan"), 1e-2, 1e-2, 1e-2, 1e-2])


def test_c3_empty_overlap_fails_with_a_reason_and_extrapolation_is_never_done():
    s = sc.score_c3(80, [-12.0, -11.0], [20.0, 21.0], [-9.0, -8.0], [10.0, 11.0], [1e-2, 1e-2])
    assert not s.passed and s.reason == "no overlap" and s.n_points == 0
    # only the NANF ROPs inside the SSMF range [-9, -7] count
    s = sc.score_c3(
        80, [-12.0, -10.0, -9.0, -8.0, -7.0], [20.0, 22.0, 23.0, 24.0, 25.0],
        [-9.0, -7.0], [18.0, 20.0], [1e-2, 1e-2],
    )  # fmt: skip
    assert s.n_points == 3 and s.simulated_penalty_db == pytest.approx(5.0)
    with pytest.raises(ValueError):
        sc.score_c3(90, N_ROP, [1.0] * 6, N_ROP, [1.0] * 6, [1e-2] * 6)


def test_c3_reports_the_workbook_penalty_without_scoring_it():
    nanf, ssmf = 20.0 + np.arange(6), 15.0 + np.arange(6)
    s = sc.score_c3(80, N_ROP, nanf, N_ROP, ssmf, [1e-2] * 6, nanf, ssmf - 2.0)
    assert s.published_penalty_db == pytest.approx(7.0) and s.simulated_penalty_db == pytest.approx(
        5.0
    )
    assert s.passed  # scored against the prose 5 dB, not the workbook 7 dB


# --- C4 ------------------------------------------------------------------------------------------


def test_c4_needs_80_percent_within_half_a_decade_and_scores_censored_points_apart():
    rop = [-9.0] * 10
    pub = [1e-2, 5e-3, 2e-3, 1e-3, 5e-4, 2e-4, 1e-4, 5e-5, 2e-5, 1e-5]
    sim = [x * 10**0.49 for x in pub[:8]] + [x * 10**0.51 for x in pub[8:]]
    s = sc.score_c4(rop, pub, sim, 1_294_016)
    assert s.n_uncensored == 10 and s.n_within == 8 and s.passed  # 80% inclusive
    sim9 = [x * 10**0.49 for x in pub[:7]] + [x * 10**0.51 for x in pub[7:]]
    assert not sc.score_c4(rop, pub, sim9, 1_294_016).passed
    # censored published points: scored as "simulated below 1e-4", not counted in the 80%
    pub_c = pub[:8] + [float("nan"), 0.0]
    sim_c = [x * 1.0 for x in pub[:8]] + [5e-5, 2e-4]
    s = sc.score_c4(rop, pub_c, sim_c, 1_294_016)
    assert s.n_uncensored == 8 and s.censored_published == 2 and s.censored_published_ok == 1
    assert s.passed
    # a simulated zero-error point against an uncensored published BER is a miss
    s = sc.score_c4([-9.0] * 5, [1e-3] * 5, [1e-3, 1e-3, 1e-3, 1e-3, 0.0], 1_294_016)
    assert s.n_within == 4 and s.passed
    s = sc.score_c4([-9.0] * 5, [1e-3] * 5, [1e-3, 1e-3, 1e-3, 0.0, 0.0], 1_294_016)
    assert s.n_within == 3 and not s.passed
    # points above the cap are not scored
    s = sc.score_c4([-9.0, -4.0], [1e-3, 1e-3], [1e-3, 1.0], 1_294_016)
    assert s.n_uncensored == 1 and s.passed
    with pytest.raises(ValueError):
        sc.score_c4([-9.0], [1e-3], [float("nan")], 100)
    with pytest.raises(ValueError):
        sc.score_c4([-9.0], [1e-3], [0.1], 0)


# --- C6: the null estimator ----------------------------------------------------------------------

F = 32.8125 * np.arange(1, 241) / 240  # 0.1367 ... 32.8125 GHz, as the 240 subcarriers


def profile(null_ghz, depth=15.0, base=20.0, spike_at=None):
    snr = base - depth * np.exp(-0.5 * ((F - null_ghz) / 0.6) ** 2)
    if spike_at is not None:
        snr[np.argmin(np.abs(F - spike_at))] += 30.0 * 0 - 12.0
    return snr


def test_the_null_estimator_finds_the_interior_minimum_in_the_window():
    est = sc.null_frequency(F, profile(24.0))
    assert est.frequency_ghz == pytest.approx(24.0, abs=0.3) and est.reason == "interior null"
    est = sc.null_frequency(F, profile(29.4))
    assert est.frequency_ghz == pytest.approx(29.4, abs=0.3)
    assert not est.clock_spike_coincidence


def test_a_spike_at_most_two_subcarriers_wide_is_removed_by_the_median():
    snr = profile(27.0)
    i = int(np.argmin(np.abs(F - 22.0)))
    snr[i] = -40.0  # one-subcarrier spike far deeper than the true null
    assert sc.null_frequency(F, snr).frequency_ghz == pytest.approx(27.0, abs=0.3)
    snr[i + 1] = -40.0  # two subcarriers
    assert sc.null_frequency(F, snr).frequency_ghz == pytest.approx(27.0, abs=0.3)
    snr[i + 2] = -40.0  # three subcarriers: the median follows it
    assert sc.null_frequency(F, snr).frequency_ghz == pytest.approx(F[i + 1], abs=0.3)


def test_a_minimum_on_a_window_edge_is_no_interior_null():
    est = sc.null_frequency(F, 20.0 + 0.5 * (F - 20.0))  # rising: lowest at the window start
    assert est.frequency_ghz is None and est.reason == "no interior null in window"
    est = sc.null_frequency(F, 20.0 - 0.5 * (F - 20.0))  # falling: lowest at 32.8125 GHz
    assert est.frequency_ghz is None
    # a deep notch outside the window (at 10 GHz) is ignored
    snr = profile(10.0)
    snr = snr - 0.5 * (F - 20.0).clip(min=0)  # window slopes down: edge minimum
    assert sc.null_frequency(F, snr).frequency_ghz is None


def test_the_median_uses_3_values_at_the_first_and_last_subcarrier():
    # one deep value at the last subcarrier is outvoted by its two neighbours (a median of 3), so
    # the genuine three-subcarrier dip inside the window is the null, not the edge
    snr = np.full(240, 20.0)
    snr[-1] = -50.0
    snr[180:183] = 15.0
    est = sc.null_frequency(F, snr)
    assert est.frequency_ghz == pytest.approx(F[180], abs=1e-9)  # three tied minima: the lowest
    snr2 = np.full(240, 20.0)
    snr2[
        -2:
    ] = -50.0  # two values: the median of the last three (20, -50, -50) is -50: an edge null
    assert sc.null_frequency(F, snr2).frequency_ghz is None


def test_ties_choose_the_lowest_frequency_and_clock_spike_coincidence_is_flagged():
    snr = np.full(240, 20.0)
    snr[(F > 25.0) & (F < 26.0)] = 10.0
    snr[(F > 28.0) & (F < 29.0)] = 10.0
    est = sc.null_frequency(F, snr)
    assert est.frequency_ghz is not None and 25.0 < est.frequency_ghz < 26.0
    flagged = sc.null_frequency(F, profile(23.4))  # within 0.5 GHz of 70 / 3 = 23.33
    assert flagged.clock_spike_coincidence
    assert not sc.null_frequency(F, profile(24.0)).clock_spike_coincidence  # 0.67 GHz away
    assert sc._clock_candidates_ghz() == (pytest.approx(70.0 / 3),)


def test_c6_scoring_and_input_checks():
    a, b = sc.null_frequency(F, profile(24.0)), sc.null_frequency(F, profile(26.0))
    s = sc.score_c6(a, b)
    assert s.passed and s.difference_ghz == pytest.approx(2.0, abs=0.3)
    far = sc.score_c6(a, sc.null_frequency(F, profile(29.4)))
    assert not far.passed and far.reason == "difference too large"  # the expected zero-chirp FAIL
    none = sc.NullEstimate(None, "no interior null in window", False)
    assert not sc.score_c6(a, none).passed and sc.score_c6(a, none).difference_ghz is None
    boundary = sc.score_c6(sc.NullEstimate(24.0, "", False), sc.NullEstimate(26.0, "", False))
    assert boundary.passed  # exactly 2.0 GHz is inclusive
    assert not sc.score_c6(
        sc.NullEstimate(24.0, "", False), sc.NullEstimate(26.01, "", False)
    ).passed
    with pytest.raises(ValueError):
        sc.null_frequency(F, np.where(F > 24, np.nan, 20.0))
    with pytest.raises(ValueError):
        sc.null_frequency(F[::-1], profile(24.0))
    with pytest.raises(ValueError):
        sc.null_frequency(F[:3], profile(24.0)[:3])


# --- C7 ------------------------------------------------------------------------------------------


def test_bit_loading_thresholds_follow_the_gray_qam_approximation():
    # the SNR at which each order first meets 3.8e-3: a bisection on the closed form, then a check
    # that loading flips exactly there
    for bits in sc.QAM_BITS:
        lo, hi = 0.0, 60.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if sc.qam_bit_error_approx(10 ** (mid / 10), bits) <= 3.8e-3:
                hi = mid
            else:
                lo = mid
        assert sc.bit_loading([hi + 1e-6])[0] >= bits and sc.bit_loading([hi - 1e-3])[0] < bits
    # the thresholds are 8.528, 15.193, 21.122 and 26.913 dB for orders 4, 16, 64 and 256
    for bits, edge in zip(sc.QAM_BITS, (8.528, 15.193, 21.122, 26.913), strict=True):
        assert sc.bit_loading([edge + 0.01])[0] == bits and sc.bit_loading([edge - 0.01])[0] < bits
    loads = sc.bit_loading([5.0, 9.0, 16.0, 22.0, 28.0, 40.0])
    assert list(loads) == [0, 2, 4, 6, 8, 8]
    assert sc.qam_bit_error_approx(10.0, 2) == pytest.approx(0.5 * math.erfc(math.sqrt(10.0 / 2)))
    with pytest.raises(ValueError):
        sc.bit_loading([float("nan")])


def test_capacity_is_bits_times_70_gsa_over_512():
    assert sc.capacity_gbps([4] * 240) == pytest.approx(240 * 4 * 70.0 / 512)
    assert sc.capacity_gbps([0] * 240) == 0.0
    assert sc.capacity_gbps([2, 6]) == pytest.approx(8 * 70 / 512)
    for bad in ([], [-1, 2]):
        with pytest.raises(ValueError):
            sc.capacity_gbps(bad)


def test_c7_capacities_within_10_gbps_and_the_ratio_within_0_1():
    assert sc.score_c7(138.0, 112.0, 138.09, 112.52).passed
    assert not sc.score_c7(149.0, 112.5, 138.09, 112.52).passed  # NANF off by more than 10
    assert not sc.score_c7(138.0, 123.0, 138.09, 112.52).passed  # SSMF off by more than 10
    # both within 10 but the ratio is off: published ratio 1.227
    s = sc.score_c7(145.0, 106.0, 138.09, 112.52)
    assert (
        s.nanf_error_gbps < 10 and s.ssmf_error_gbps < 10 and s.ratio_error > 0.1 and not s.passed
    )
    assert sc.score_c7(138.09 + 10.0, 112.52 + 9.0, 138.09, 112.52).ratio_error == pytest.approx(
        abs(148.09 / 121.52 - 138.09 / 112.52)
    )
    with pytest.raises(ValueError):
        sc.score_c7(0.0, 1.0, 1.0, 1.0)


# --- B2B-copy, d, discriminating, the B2B gate ---------------------------------------------------


def test_b2b_copy_interpolates_without_extrapolation_and_skips_censored_nodes():
    rop = [-12.0, -11.0, -10.0, -9.0, -8.0, -5.0, -4.0]
    snr = [10.0, 12.0, 14.0, 16.0, 18.0, 24.0, 26.0]
    ber = [1e-1, 1e-2, 5e-6, 1e-3, 1e-4, 1e-5, 1e-9]  # 5e-6 is finite and censored
    cp = sc.b2b_copy(rop, snr, ber, [-12.0, -10.5, -10.0, -6.5, -5.0, -4.5, -13.0])
    assert cp.snr_db[0] == 10.0 and cp.snr_db[1] == pytest.approx(13.0)
    assert cp.snr_db[3] == pytest.approx(21.0) and cp.snr_db[4] == pytest.approx(24.0)
    assert np.isnan(cp.snr_db[5]) and np.isnan(
        cp.snr_db[6]
    )  # -4.5 is above the cap; -13 is outside
    assert cp.unbracketed_snr == (-4.5, -13.0)
    # BER nodes: the censored point at -10 is not a node, so -10.5 interpolates between -11 and -9
    expected = 10 ** (
        math.log10(1e-2) + (math.log10(1e-3) - math.log10(1e-2)) * (-10.5 + 11.0) / 2.0
    )
    assert cp.ber[1] == pytest.approx(expected)
    assert cp.ber[2] == pytest.approx(10 ** (0.5 * (-2 - 3)))  # at -10.0, halfway between the nodes
    assert cp.ber[0] == pytest.approx(1e-1)
    assert cp.ber[3] == pytest.approx(10**-4.5)  # between the nodes -8 (1e-4) and -5 (1e-5)
    assert cp.ber[4] == pytest.approx(1e-5)  # exactly 1e-5 is uncensored and a node
    assert np.isnan(cp.ber[5]) and np.isnan(cp.ber[6])  # above the cap and outside the nodes
    assert cp.unbracketed_ber == (-4.5, -13.0)


def test_d_is_the_difference_to_the_no_fibre_output_and_discriminating_is_strict():
    assert sc.d_c1(P(-10.0), P(-9.2)) == pytest.approx(0.8)
    assert sc.d_c1(P(-10.0), sc.Crossing("left", -math.inf, -12.0)) is None
    assert sc.d_c1(sc.Crossing("interval", -10.0, -9.0), P(-9.0)) is None
    assert sc.d_snr([10.0, 12.0], [9.0, 14.0]) == pytest.approx(1.5)
    assert sc.discriminating(1.01, 1.0) and not sc.discriminating(1.0, 1.0)
    assert not sc.discriminating(None, 1.0) and not sc.discriminating(float("nan"), 1.0)
    assert sc.discriminating(1.51, 1.5) and not sc.discriminating(1.5, 1.5)
    assert sc.discriminating(2.01, 2.0) and not sc.discriminating(2.0, 2.0)
    with pytest.raises(ValueError):
        sc.d_snr([1.0], [1.0, 2.0])


def test_the_b2b_gate_needs_mean_max_and_crossing():
    ok = sc.b2b_gate([10.0, 11.0], [10.9, 11.9], P(-9.0), P(-9.4))
    assert ok.passed and ok.label == ""
    assert not sc.b2b_gate([10.0, 11.0], [11.1, 12.1], P(-9.0), P(-9.0)).passed  # mean above 1.0
    bad = sc.b2b_gate([10.0, 11.0], [10.0, 13.01], P(-9.0), P(-9.0))  # max above 2.0, mean 1.5
    assert not bad.passed and bad.label == "B2B CALIBRATION POOR"
    cross = sc.b2b_gate([10.0], [10.0], P(-9.0), P(-9.6))  # crossing 0.6 dB apart: above 0.5
    assert not cross.passed and not cross.crossing_ok
    assert sc.b2b_gate([10.0], [10.0], P(-9.0), P(-9.5)).passed  # 0.5 inclusive
    # a bound is judged by B1.3 with 0.5 dB
    assert sc.b2b_gate([10.0], [10.0], P(-12.4), sc.Crossing("left", -math.inf, -12.0)).passed
    assert not sc.b2b_gate([10.0], [10.0], P(-11.4), sc.Crossing("left", -math.inf, -12.0)).passed


# --- the verdict ---------------------------------------------------------------------------------


def rs(**over):
    base = dict(
        c1_passed=True, c1_discriminating=True, c2_passed=True, c2_discriminating=True,
        c3_passed=True, c5_passed=True, b2b_poor=False,
    )  # fmt: skip
    base.update(over)
    return sc.RateScores(**base)


def test_the_verdict_follows_the_decision_rule():
    all_ok = {r: rs() for r in sc.RATES}
    assert sc.overall_verdict(all_ok).text == "consistent with this one experiment"
    v = sc.overall_verdict({**all_ok, 100: rs(c2_passed=False), 112: rs(c5_passed=False)})
    assert v.text.startswith("failed: ") and v.failed == ("C2@100", "C5@112")
    weak = sc.overall_verdict({**all_ok, 80: rs(c1_discriminating=False)})
    assert weak.not_discriminating_rates == (80,) and "NOT DISCRIMINATING" in weak.text
    assert "80" in weak.text and not weak.failed
    poor = sc.overall_verdict({**all_ok, 112: rs(b2b_poor=True)})
    assert poor.not_discriminating_rates == (112,)
    assert sc.overall_verdict(
        {**all_ok, 100: rs(c2_discriminating=False)}
    ).not_discriminating_rates == (100,)
    # a failure outranks a lack of discrimination
    both = sc.overall_verdict({**all_ok, 80: rs(c1_discriminating=False, c3_passed=False)})
    assert both.text.startswith("failed") and both.failed == ("C3@80",)
    with pytest.raises(ValueError):
        sc.overall_verdict({80: rs(), 100: rs()})
    with pytest.raises(ValueError):
        sc.overall_verdict({**all_ok, 90: rs()})


# --- identifiability (A1.7, B4) ------------------------------------------------------------------

SPEC = {s.name: s for s in B4_PARAMETERS}


def mid_optimum():
    return {s.name: s.low + 0.4 * (s.high - s.low) for s in B4_PARAMETERS}


def separable(values):
    """Six residuals, each driven by one parameter only: every direction is identified."""
    return np.array(
        [
            (values[s.name] - s.low) / (s.high - s.low) * (1.0 + i)
            for i, s in enumerate(B4_PARAMETERS)
        ]
        + [0.3, 0.1]
    )


def test_identifiable_synthetic_case_flags_nothing():
    res = sc.identifiability_check(separable, mid_optimum())
    assert res.flagged == () and not res.singular
    assert res.eigenvalues[0] > 1e-3 * res.eigenvalues[-1]
    assert res.vector == mid_optimum()
    assert np.allclose(np.sort(res.eigenvalues), [(1 + i) ** 2 for i in range(6)], rtol=1e-6)


def test_a_parameter_that_does_not_enter_is_flagged_and_set_to_its_prior():
    def residual(values):
        full = separable(values)
        full[2] = 0.0  # thermal noise no longer drives any residual
        return full

    res = sc.identifiability_check(residual, mid_optimum())
    assert res.flagged == ("thermal_noise_pa_per_rthz",)
    assert (
        res.vector["thermal_noise_pa_per_rthz"] == SPEC["thermal_noise_pa_per_rthz"].prior == 32.5
    )
    assert res.vector["tx_bandwidth_ghz"] == mid_optimum()["tx_bandwidth_ghz"]  # no refit
    assert res.eigenvalues[0] < 1e-3 * res.eigenvalues[-1]


def test_two_degenerate_parameters_flag_exactly_one_of_them():
    # only the sum of the scaled bandwidths is observable: one direction is lost
    def residual(values):
        ut = (values["tx_bandwidth_ghz"] - 10) / 50
        ur = (values["rx_bandwidth_ghz"] - 10) / 50
        rest = separable(values)[2:6]
        return np.concatenate([[ut + ur], rest])

    res = sc.identifiability_check(residual, mid_optimum())
    assert len(res.flagged) == 1 and res.flagged[0] in ("tx_bandwidth_ghz", "rx_bandwidth_ghz")
    assert res.flagged == ("tx_bandwidth_ghz",)  # equal components: the lowest in the table
    assert (
        res.vector["tx_bandwidth_ghz"] == 35.0
        and res.vector["rx_bandwidth_ghz"] == mid_optimum()["rx_bandwidth_ghz"]
    )


def test_the_number_of_flags_equals_the_number_of_low_eigenvalues_and_a_flat_model_flags_all():
    def two_lost(values):
        r = separable(values)
        r[0] = r[4] = 0.0
        return r

    res = sc.identifiability_check(two_lost, mid_optimum())
    assert set(res.flagged) == {"tx_bandwidth_ghz", "bias_fraction"} and len(res.flagged) == 2
    assert np.sum(res.eigenvalues < 1e-3 * res.eigenvalues[-1]) == 2

    res = sc.identifiability_check(lambda v: np.array([1.0, 2.0, 3.0]), mid_optimum())
    assert res.singular and set(res.flagged) == set(B4_NAMES) and len(res.flagged) == 6
    assert all(res.vector[s.name] == s.prior for s in B4_PARAMETERS)


def test_the_threshold_is_1e_minus_3_of_the_largest_eigenvalue():
    def weak(scale):
        def residual(values):
            r = separable(values)
            r[3] = (values["modulation_depth"] - 0.2) / 0.8 * scale  # information scale**2
            return r

        return residual

    # largest eigenvalue is 36 (the sixth term); modulation_depth carries scale**2
    low = sc.identifiability_check(weak(math.sqrt(36e-3 * 0.9)), mid_optimum())
    high = sc.identifiability_check(weak(math.sqrt(36e-3 * 1.1)), mid_optimum())
    assert low.flagged == ("modulation_depth",) and high.flagged == ()


def test_a_parameter_at_a_range_edge_uses_a_one_sided_step_and_bad_inputs_are_refused():
    edge = {**mid_optimum(), "bias_fraction": 0.6}
    res = sc.identifiability_check(separable, edge)
    assert res.flagged == ()
    low = {**mid_optimum(), "bias_fraction": 0.4}
    assert sc.identifiability_check(separable, low).flagged == ()
    with pytest.raises(ValueError):
        sc.identifiability_check(separable, {**mid_optimum(), "bias_fraction": 0.61})
    with pytest.raises(ValueError):
        sc.identifiability_check(separable, {"tx_bandwidth_ghz": 30.0})
    with pytest.raises(ValueError):
        sc.identifiability_check(lambda v: np.array([float("nan")]), mid_optimum())
    with pytest.raises(ValueError):
        sc.identifiability_check(separable, mid_optimum(), step=0.0)


def test_a_notch_outside_the_window_is_ignored_whatever_its_depth():
    snr = profile(27.0, depth=6.0)
    i = int(np.argmin(np.abs(F - 19.0)))
    snr[i - 3 : i + 4] -= 12.0  # a wide, deep dip at 19 GHz, below the window start of 20.0 GHz
    est = sc.null_frequency(F, snr)
    assert est.frequency_ghz == pytest.approx(27.0, abs=0.3)
    j = int(np.argmin(np.abs(F - 33.0))) if F[-1] >= 33.0 else len(F) - 1
    assert F[j] <= 32.8125 and sc.C6_WINDOW_GHZ == (20.0, 32.8125)


def test_c4_needs_more_than_three_quarters_within():
    rop = [-9.0] * 20
    pub = [1e-2] * 20
    sim = [1e-2] * 15 + [1e-4] * 5  # 15 of 20 = 75%: below the 80% requirement
    s = sc.score_c4(rop, pub, sim, 1_294_016)
    assert s.n_within == 15 and not s.passed
    assert sc.score_c4(rop, pub, [1e-2] * 16 + [1e-4] * 4, 1_294_016).passed
