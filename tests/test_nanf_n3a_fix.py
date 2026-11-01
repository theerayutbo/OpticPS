"""Gate N3 part a, fix round (plan Amendment 6): the trace cap, the stages of the chain as known
answers, the freeze-aware `simulate_point`, and the scoring rules corrected by the first review.

Synthetic data only. No workbook is read, no fit is run, nothing is frozen.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from nanf_freeze_support import PARAMS, make_repo, patch_module_paths
from opticps.measurement import nanf_chain as nc
from opticps.measurement import nanf_freeze as nf
from opticps.measurement import nanf_scoring as sc
from opticps.receiver import dfe

SMALL = nc.ChainConfig(n_symbols=14_000, training_symbols=2_000)  # 140 x 100
WIDE = nc.TxRxParameters(tx_bandwidth_ghz=60.0, rx_bandwidth_ghz=60.0)
MID = nc.TxRxParameters()
R = [-12.0, -11.0, -10.0, -9.0]


# --- capture of the stages of one run --------------------------------------------------------


def capture(monkeypatch, params=WIDE, rate=80, rop=-5.0, config=SMALL, **kw):
    """Run `simulate_point` and record what each stage received. Wrappers only; no behaviour."""
    seen = SimpleNamespace(resample=[], analogue=None, mf_in=None, eq_in=None, levels=None)
    real_resample, real_analogue = nc.resample_exact, nc.analogue_path
    real_mf, real_eq = nc.matched_filter_t2, nc.rls_equalize

    def resample(x, fs_in, fs_out):
        out = real_resample(x, fs_in, fs_out)
        seen.resample.append((np.array(x), fs_in, fs_out, np.array(out)))
        return out

    def analogue(drive, fs, **k):
        seen.analogue = {"drive": np.array(drive), "fs": fs, **k}
        return real_analogue(drive, fs, **k)

    def mf(ac, roll_off=nc.SRRC_ROLL_OFF):
        seen.mf_in = np.array(ac)
        return real_mf(ac, roll_off)

    def eq(samples, reference, cfg=None):
        seen.eq_in, seen.levels = np.array(samples), np.array(reference)
        return real_eq(samples, reference, cfg)

    monkeypatch.setattr(nc, "resample_exact", resample)
    monkeypatch.setattr(nc, "analogue_path", analogue)
    monkeypatch.setattr(nc, "matched_filter_t2", mf)
    monkeypatch.setattr(nc, "rls_equalize", eq)
    seen.result = nc.simulate_point(params, rate, rop, config=config, **kw)
    return seen


def symbol_residual(x, levels, offset):
    s = x[offset::2]
    gain = float(np.dot(s, levels) / np.dot(levels, levels))
    return float(
        np.sqrt(np.mean((s - gain * levels) ** 2)) / abs(gain) / np.sqrt(np.mean(levels**2))
    )


# --- stages as known answers (the review's survivors) -----------------------------------------


@pytest.mark.parametrize("rate", [80, 100, 112])
def test_the_matched_output_is_isi_free_at_the_symbol_instants_and_not_half_a_symbol_away(
    monkeypatch, rate
):
    """Known answer for the matched filter (F4.8) and the timing phase (F4.9).

    Noise-free and wide-band, SRRC x SRRC is a raised cosine, so the 2-sps sequence at sample 2k is
    the symbol k times one gain, to the 8-bit DAC and the Butterworth. Without the matched filter the
    residual is 0.083; shifted by one T/2 sample the even samples are the mid-symbol points.
    """
    seen = capture(monkeypatch, rate=rate, noise=False)
    assert symbol_residual(seen.eq_in, seen.levels, 0) < 0.03
    assert symbol_residual(seen.eq_in, seen.levels, 1) > 0.5  # the other phase is not the symbol
    s = seen.eq_in[::2]
    assert np.dot(s, seen.levels) > 0  # and not inverted


def test_the_receiver_removes_the_mean_and_scales_to_unit_mean_square(monkeypatch):
    seen = capture(monkeypatch, noise=True)
    assert abs(float(np.mean(seen.mf_in))) < 1e-12 * 100  # the photocurrent mean is removed (F4.8)
    assert float(np.mean(seen.mf_in**2)) == pytest.approx(1.0, abs=1e-12)
    # the received photocurrent has a large mean; leaving it in would be a gross error
    scope_to_t2 = seen.resample[-1]
    assert abs(float(np.mean(scope_to_t2[3]))) > 1e-4  # input to the AC step had a mean
    assert seen.eq_in.size == 2 * SMALL.n_symbols and seen.levels.size == SMALL.n_symbols


def test_the_filters_of_the_analogue_path_are_the_declared_butterworth_responses():
    """Tx and Rx low-pass: a tone at the 3 dB frequency is 0.7071 of a tone at a tenth of it."""
    n, fs = 2800, 280e9
    t = np.arange(n) / fs
    base = dict(
        modulation_depth=0.6, bias_fraction=0.5, thermal_a_per_rthz=0.0, link=nc.LinkSpec(),
        rop_dbm=-5.0, config=nc.ChainConfig(),
    )  # fmt: skip

    def tone(freq, tx, rx):
        drive = 1e-3 * np.cos(2 * np.pi * freq * t)
        out = nc.analogue_path(drive, fs, tx_bandwidth_hz=tx, rx_bandwidth_hz=rx, **base)
        return 2 * abs(np.fft.rfft(out.signal)[round(freq * n / fs)]) / n

    fc = 20e9  # bin 200
    for tx, rx in ((fc, None), (None, fc), (fc, fc)):
        ratio = tone(fc, tx, rx) / tone(fc / 10, tx, rx)
        expected = (1 / math.sqrt(2)) ** ((tx is not None) + (rx is not None))
        assert ratio == pytest.approx(expected, rel=2e-3), (tx, rx)
    assert tone(fc, None, None) / tone(fc / 10, None, None) == pytest.approx(1.0, rel=1e-3)


def test_the_chain_passes_the_b4_bandwidths_to_both_filters(monkeypatch):
    p = nc.TxRxParameters(tx_bandwidth_ghz=22.0, rx_bandwidth_ghz=47.0)
    seen = capture(monkeypatch, params=p, noise=False)
    assert seen.analogue["tx_bandwidth_hz"] == 22e9 and seen.analogue["rx_bandwidth_hz"] == 47e9


def test_the_noise_is_low_pass_filtered_by_the_receiver_filter():
    """White noise through a 4th-order Butterworth keeps 2 x 1.0262 x fc / fs of its variance."""
    n, fs, fc = 40_000, 280e9, 10e9
    rng = np.random.default_rng(5)
    zs, zt = rng.standard_normal(n), rng.standard_normal(n)
    base = dict(
        tx_bandwidth_hz=None, modulation_depth=0.6, bias_fraction=0.5, thermal_a_per_rthz=30e-12,
        link=nc.LinkSpec(), rop_dbm=-8.0, config=nc.ChainConfig(), z_shot=zs, z_thermal=zt,
    )  # fmt: skip
    drive = np.zeros(n)
    drive[0] = 1e-9
    open_ = nc.analogue_path(drive, fs, rx_bandwidth_hz=None, **base).noise
    shut = nc.analogue_path(drive, fs, rx_bandwidth_hz=fc, **base).noise
    ratio = float(np.var(shut) / np.var(open_))
    assert ratio == pytest.approx(2 * 1.0262 * fc / fs, rel=0.12)


@pytest.mark.parametrize("rate,index", [(80, 0), (100, 2), (112, 5)])
def test_the_noise_draw_order_is_shot_then_thermal_then_ceiling(monkeypatch, rate, index):
    """Known answer for plan F4.2: three standard-normal arrays in this order from one stream."""
    seen = capture(monkeypatch, rate=rate, point_index=index)
    counts = nc.sample_counts(SMALL.n_symbols, nc.BAUD_GBD[rate])
    rng = nc.noise_generator(nc.BAUD_GBD[rate], index)
    shot = rng.standard_normal(counts["analogue"])
    thermal = rng.standard_normal(counts["analogue"])
    ceiling = rng.standard_normal(counts["scope"])
    assert np.array_equal(seen.analogue["z_shot"], shot)
    assert np.array_equal(seen.analogue["z_thermal"], thermal)
    assert not np.array_equal(shot, thermal)
    # the ceiling noise: scope = signal + noise + sigma z, reconstructed from the recorded calls
    sig_in, _, _, sig_out = seen.resample[1]
    noise_out = seen.resample[2][3]
    scope = seen.resample[3][0]
    sigma = nc.ceiling_noise_std(sig_out, WIDE.electrical_snr_ceiling_db)
    assert np.allclose((scope - sig_out - noise_out) / sigma, ceiling, atol=1e-9)


def test_the_dac_has_255_steps_and_the_chain_passes_the_configured_resolution(monkeypatch):
    x = np.linspace(-1.0, 1.0, 20_001)
    q = nc.dac_quantise(x, 8)
    grid = (q + 1.0) / 2.0 * 255
    assert np.max(np.abs(grid - np.round(grid))) < 1e-9  # exactly on the 255-step grid
    assert np.unique(q).size == 256 and q.min() == -1.0 and q.max() == 1.0
    assert np.min(np.diff(np.unique(q))) == pytest.approx(2 / 255, rel=1e-9)
    q4 = nc.dac_quantise(x, 4)
    assert np.unique(q4).size == 16 and np.min(np.diff(np.unique(q4))) == pytest.approx(2 / 15)
    # in the chain: the array handed to the up-sampler is the quantised AWG waveform
    seen = capture(monkeypatch, noise=False)
    dac = seen.resample[0][0]
    g = (dac + 1.0) / 2.0 * 255
    assert np.max(np.abs(g - np.round(g))) < 1e-9 and np.unique(dac).size > 100
    seen4 = capture(
        monkeypatch,
        noise=False,
        config=nc.ChainConfig(n_symbols=14_000, training_symbols=2_000, dac_bits=4),
    )
    assert np.unique(seen4.resample[0][0]).size <= 16


def test_the_tx_waveform_is_clipped_to_full_scale_after_up_sampling(monkeypatch):
    seen = capture(monkeypatch, noise=False)
    assert float(np.max(np.abs(seen.analogue["drive"]))) <= 1.0  # np.clip after up-sampling (G9)
    raw = seen.resample[0][3]
    assert float(np.max(np.abs(raw))) >= float(np.max(np.abs(seen.analogue["drive"])))


# --- the trace cap (plan Amendment 6 G1) ------------------------------------------------------


def test_the_cap_is_pinned_at_1e10_and_is_the_default():
    assert dfe.PINNED_P_TRACE_CAP == 1e10
    assert dfe.RlsDfeConfig().p_trace_cap == 1e10
    assert nc.PINNED_P_TRACE_CAP == 1e10


def test_on_the_real_chain_the_pinned_cap_never_acts_and_equals_no_cap(monkeypatch):
    """One full-size point (100 Gb/s back-to-back, -9 dBm, mid vector): cap 1e10 against no cap."""
    capped = nc.simulate_point(MID, 100, -9.0)
    open_cfg = dfe.RlsDfeConfig(p_trace_cap=1e300)  # finite, so never reached: no cap
    uncapped = nc.simulate_point(MID, 100, -9.0, equalizer=open_cfg)
    assert capped.dfe.n_trace_caps == 0 and uncapped.dfe.n_trace_caps == 0
    assert capped.dfe.max_p_trace < 1e10 and capped.dfe.max_p_trace == uncapped.dfe.max_p_trace
    assert np.array_equal(capped.dfe.decision_indices, uncapped.dfe.decision_indices)
    assert capped.reading.errors == uncapped.reading.errors
    assert capped.scorable and not uncapped.scorable  # an overridden equaliser is never scored
    nc.require_scorable([capped])
    with pytest.raises(nc.NotScorableError):
        nc.require_scorable([capped, uncapped])


def test_a_cap_that_acts_changes_the_result_and_cannot_score():
    """Cap 1e4 (the earlier default) acts on almost every symbol of a small real-chain point."""
    diagnostic = nc.simulate_point(
        MID,
        100,
        -9.0,
        config=SMALL,
        equalizer=dfe.RlsDfeConfig(training_symbols=2_000, p_trace_cap=1e4),
        diagnostic=True,
    )
    assert diagnostic.dfe.n_trace_caps > 10_000 and not diagnostic.scorable
    assert any("trace cap acted" in why for why in diagnostic.unscorable_reasons)
    assert any("diagnostic" in why for why in diagnostic.unscorable_reasons)
    with pytest.raises(nc.NotScorableError, match="trace cap acted"):
        nc.require_scorable([diagnostic])
    # without `diagnostic` the same run raises instead of returning a result
    with pytest.raises(nc.TraceCapActedError):
        nc.simulate_point(
            MID, 100, -9.0, config=SMALL,
            equalizer=dfe.RlsDfeConfig(training_symbols=2_000, p_trace_cap=1e4),
        )  # fmt: skip


def test_a_pinned_run_in_which_the_cap_acts_raises_and_never_returns_a_score(monkeypatch):
    monkeypatch.setattr(nc, "PINNED_P_TRACE_CAP", 1e4)  # as if the pin had been lowered
    with pytest.raises(nc.TraceCapActedError, match="cannot be scored"):
        nc.simulate_point(MID, 100, -9.0, config=SMALL)


def test_a_raised_cap_is_also_not_scorable():
    for cap in (1e4, 1e12, 1e300):
        res = nc.simulate_point(
            MID, 80, -5.0, config=SMALL,
            equalizer=dfe.RlsDfeConfig(training_symbols=2_000, p_trace_cap=cap), diagnostic=True,
        )  # fmt: skip
        assert not res.scorable
    plain = nc.simulate_point(MID, 80, -5.0, config=SMALL)
    assert not plain.scorable and "chain configuration overridden" in plain.unscorable_reasons
    assert not nc.simulate_point(MID, 80, -5.0, config=SMALL, noise=False).scorable


def test_require_scorable_rejects_anything_that_is_not_a_point_result():
    for junk in (None, 5, {"ber": 0.1}, SimpleNamespace(scorable=True)):
        with pytest.raises(nc.NotScorableError):
            nc.require_scorable([junk])
    nc.require_scorable([])


# --- simulate_point and the freeze (plan Amendment 6 G5) --------------------------------------


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    patch_module_paths(monkeypatch, repo)
    return repo


def test_after_a_freeze_parameter_and_configuration_overrides_are_refused(frozen):
    other = nc.TxRxParameters(tx_bandwidth_ghz=33.0)
    with pytest.raises(nc.FrozenOverrideError, match="parameters are those of the record"):
        nc.simulate_point(other, 80, -5.0)
    with pytest.raises(nc.FrozenOverrideError, match="configuration"):
        nc.simulate_point(PARAMS, 80, -5.0, config=SMALL)
    with pytest.raises(nc.FrozenOverrideError, match="equaliser"):
        nc.simulate_point(PARAMS, 80, -5.0, equalizer=dfe.RlsDfeConfig(p_trace_cap=1e4))
    with pytest.raises(nc.FrozenOverrideError, match="noise"):
        nc.simulate_point(PARAMS, 80, -5.0, noise=False)


def test_after_a_freeze_the_verified_record_supplies_the_vector(frozen, monkeypatch):
    seen = {}

    def stop(drive, fs, **k):
        seen.update(k)
        raise RuntimeError("stop after the analogue call")

    monkeypatch.setattr(nc, "analogue_path", stop)
    for given in (None, PARAMS):
        seen.clear()
        with pytest.raises(RuntimeError, match="stop after"):
            nc.simulate_point(given, 80, -5.0)
        assert seen["tx_bandwidth_hz"] == 31.0e9 and seen["rx_bandwidth_hz"] == 42.0e9
        assert seen["thermal_a_per_rthz"] == 21.5e-12


def test_after_a_freeze_a_stale_or_forged_record_stops_every_run(frozen, monkeypatch):
    plan = frozen.plan
    plan.write_text(plan.read_text() + "\nlate edit\n")
    with pytest.raises(nf.HoldoutLockedError, match="plan has changed"):
        nc.simulate_point(PARAMS, 80, -5.0)
    with pytest.raises(nf.HoldoutLockedError):
        nc.simulate_point(None, 80, -5.0)
    frozen.record_path.write_text("{")
    with pytest.raises(nf.HoldoutLockedError):
        nc.simulate_point(PARAMS, 80, -5.0)


def test_a_diagnostic_run_after_a_freeze_runs_but_is_never_scorable(frozen):
    res = nc.simulate_point(
        nc.TxRxParameters(tx_bandwidth_ghz=33.0), 80, -5.0, config=SMALL, diagnostic=True
    )
    assert not res.scorable and "diagnostic run" in res.unscorable_reasons


def test_before_a_freeze_a_vector_is_required():
    with pytest.raises(ValueError, match="params is required"):
        nc.simulate_point(None, 80, -5.0, config=SMALL)


# --- BER reading (F2) -------------------------------------------------------------------------


def test_the_report_string_for_ber_between_1e5_and_1e4_is_below_1e4():
    n = 1_294_016
    assert nc.BerReading.from_counts(13, n).text == "below 1e-4"  # 1.0046e-5
    assert nc.BerReading.from_counts(129, n).text == "below 1e-4"  # 9.97e-5
    assert nc.BerReading.from_counts(130, n).text == f"{130 / n:.3g}"  # 1.0046e-4
    assert nc.BerReading.from_counts(130, n).ber == pytest.approx(130 / n)
    assert nc.BerReading.from_counts(129, n).censored is False  # a number is kept for scoring
    assert "censored" in nc.BerReading.from_counts(12, n).text
    assert nc.BerReading.from_counts(0, n).text.startswith("below 1/N_b")


def test_the_ber_censoring_floor_is_exactly_1e5_not_below():
    """BER exactly 1e-5 is not censored (A3: below 1e-5); one error fewer is."""
    exactly = nc.BerReading.from_counts(1, 100_000)
    assert exactly.ber == 1e-5 and exactly.censored is False
    assert nc.BerReading.from_counts(1, 100_001).censored is True
    assert nc.BerReading.from_counts(1, 100_000).text == "below 1e-4"


# --- C1: no crossing in the common range (Amendment 6 G2) -------------------------------------


def test_a_published_point_against_a_simulated_left_bound_fails():
    published = sc.Crossing("point", -12.4, -12.4)
    left_bound = sc.Crossing("left", -math.inf, -13.0)  # simulated curve already below at -13
    got = sc.score_c1(published, left_bound)
    assert got.passed is False and "no crossing" in got.reason
    # literal F7.2 would read the bound at -13, inside the widened region [-13.4, -11.4]; B1.3 wins
    lo, hi = sc._widened(published, sc.C1_TOL_DB)
    assert lo <= left_bound.hi <= hi
    assert sc.score_c1(published, sc.Crossing("right", -9.0, math.inf)).passed is False


def test_the_same_curve_end_to_end_gives_a_fail_not_a_pass():
    sim = sc.c1_crossing([-13.0, -12.0, -11.0], [1e-4, 1e-5, 0.0])  # no crossing: left bound
    assert (sim.kind, sim.hi) == ("left", -13.0)
    assert sc.score_c1(sc.Crossing("point", -12.4, -12.4), sim).passed is False


def test_a_simulated_bound_is_read_at_its_ends_against_a_published_interval_or_bound():
    pub = sc.Crossing("interval", -12.0, -10.0)  # widened [-13, -9]
    assert sc.score_c1(pub, sc.Crossing("left", -math.inf, -11.5)).passed is True
    assert sc.score_c1(pub, sc.Crossing("right", -9.5, math.inf)).passed is True
    assert sc.score_c1(pub, sc.Crossing("right", -8.0, math.inf)).passed is False
    assert sc.score_c1(pub, sc.Crossing("left", -math.inf, -14.0)).passed is False
    far = sc.Crossing("right", -8.0, math.inf)  # published right bound widened [-9, inf)
    assert sc.score_c1(far, sc.Crossing("left", -math.inf, -12.0)).passed is False
    assert sc.score_c1(far, sc.Crossing("left", -math.inf, -8.5)).passed is True


# --- default deny (G3) -----------------------------------------------------------------------


def test_invalid_simulated_ber_never_gives_a_censored_point_or_a_pass():
    for bad in (float("nan"), float("inf"), -1e-3, 1.5):
        got = sc.c1_crossing(R, [1e-1, 5e-3, bad, bad])
        assert got.kind == "invalid"
        for published in (
            sc.Crossing("point", -10.16, -10.16),
            sc.Crossing("left", -math.inf, -12.0),
        ):
            assert sc.score_c1(published, got).passed is False
            assert sc.score_c1(got, sc.Crossing("point", -10.0, -10.0)).passed is False
    all_nan = sc.c1_crossing(R, [float("nan")] * 4)
    assert all_nan.kind == "invalid"
    assert sc.score_c1(sc.Crossing("left", -math.inf, -12.0), all_nan).passed is False
    # the review's repro: [1e-1, 5e-3, NaN, NaN] gave an interval that passed a point at -10.16
    assert (
        sc.score_c1(
            sc.Crossing("point", -10.16, -10.16),
            sc.c1_crossing(R, [1e-1, 5e-3, float("nan"), float("nan")]),
        ).passed
        is False
    )


def test_a_published_nan_is_a_flagged_cell_but_inf_negative_and_above_one_are_invalid():
    ok = sc.c1_crossing(R, [1e-1, 1e-3, float("nan"), float("nan")], published=True)
    assert ok.kind == "point"
    for bad in (float("inf"), -1.0, 3.0):
        assert sc.c1_crossing(R, [1e-1, 1e-3, bad, 0.0], published=True).kind == "invalid"


def test_the_other_criteria_refuse_invalid_ber_instead_of_passing_it():
    rop = [-9.0, -8.0, -7.0]
    for bad in (float("nan"), float("inf"), -1e-4, 2.0):
        with pytest.raises(sc.InvalidDataError):
            sc.score_c4(rop, [1e-2, 1e-3, 1e-4], [1e-2, bad, 1e-4], 1_000_000)
        with pytest.raises(sc.InvalidDataError):
            sc.score_c3(100, rop, [10.0] * 3, rop, [10.0] * 3, [0.1, bad, 0.1])
    for bad in (float("inf"), -1e-4, 2.0):
        with pytest.raises(sc.InvalidDataError):
            sc.score_c4(rop, [1e-2, bad, 1e-4], [1e-2, 1e-3, 1e-4], 1_000_000)
    # D3.1: invalid B2B BER is refused; NaN there is a flagged censored cell and is no node
    for bad in (float("inf"), -1e-4, 2.0):
        with pytest.raises(sc.InvalidDataError):
            sc.b2b_copy([-9.0, -8.0, -7.0], [10.0, 11.0, 12.0], [1e-2, bad, 1e-4], [-8.0])
    with pytest.raises(sc.InvalidDataError):
        sc.b2b_copy([-9.0, -8.0, -7.0], [10.0, float("nan"), 12.0], [1e-2, 1e-3, 1e-4], [-8.0])
    with pytest.raises(sc.InvalidDataError):
        sc.b2b_copy([-9.0, -8.0, -7.0], [10.0, 11.0, 12.0], [1e-2, 1e-3, 1e-4], [float("nan")])


def test_an_unbracketed_copy_point_is_not_scored_and_not_read_as_censored():
    """D3.1 and the review: NaN from `b2b_copy` was passed on to C1 as a censored point."""
    copy = sc.b2b_copy(
        [-9.0, -8.0, -7.0], [10.0, 11.0, 12.0], [1e-1, 1e-2, 1e-4], [-10.0, -8.5, -7.5, -6.0]
    )
    assert np.isnan(copy.ber[0]) and np.isnan(copy.ber[3]) and not np.isnan(copy.ber[1])
    rop, ber = copy.bracketed_ber([-10.0, -8.5, -7.5, -6.0])
    assert list(rop) == [-8.5, -7.5]
    got = sc.copy_crossing(copy, [-10.0, -8.5, -7.5, -6.0])
    assert got.kind == "point" and -8.5 < got.x < -7.5
    # raw NaN is no longer accepted as a censored simulated point
    assert sc.c1_crossing([-10.0, -8.5, -7.5, -6.0], copy.ber).kind == "invalid"
    # nothing bracketed at all: nothing to score, which fails
    none = sc.b2b_copy([-9.0, -8.0, -7.0], [10.0, 11.0, 12.0], [1e-2, 1e-3, 1e-4], [-20.0, -19.0])
    assert sc.copy_crossing(none, [-20.0, -19.0]).kind == "invalid"
    with pytest.raises(ValueError):
        copy.bracketed_ber([-10.0, -8.5])


def test_no_value_can_help_a_pass_in_the_verdict_and_the_gate():
    bad = sc.Crossing("invalid", math.nan, math.nan)
    point = sc.Crossing("point", -10.0, -10.0)
    gate = sc.b2b_gate([10.0, 11.0], [10.0, 11.0], bad, point)
    assert gate.passed is False and gate.crossing_ok is False
    assert sc.d_c1(bad, point) is None and sc.d_c1(point, bad) is None


# --- minors (finding 8 to 11) -----------------------------------------------------------------


def test_c4_counts_a_simulated_censored_nonzero_ber_as_a_miss():
    # 5e-6 against 1.2e-5 was counted within (about 6 errors, an undeclared case)
    got = sc.score_c4([-9.0], [1.2e-5], [5e-6], 1_294_016)
    assert (got.n_uncensored, got.n_within, got.passed) == (1, 0, False)
    ok = sc.score_c4([-9.0], [1.2e-5], [1.3e-5], 1_294_016)
    assert (ok.n_within, ok.passed) == (1, True)
    # a censored published point is still only reported
    rep = sc.score_c4([-9.0, -8.0], [float("nan"), 1e-3], [5e-6, 1.1e-3], 1_294_016)
    assert rep.censored_published == 1 and rep.censored_published_ok == 1 and rep.passed


def test_c4_includes_a_point_exactly_at_the_rop_cap_and_refuses_a_nan_rop():
    inside = sc.score_c4([-5.0], [1e-3], [1e-3], 1_000)
    assert inside.n_uncensored == 1  # exactly -5.0 is scored
    outside = sc.score_c4([-5.0, -4.99], [1e-3, 1e-3], [1e-3, 1e-3], 1_000)
    assert outside.n_uncensored == 1
    with pytest.raises(ValueError, match="finite"):
        sc.score_c4([-9.0, float("nan")], [1e-3, 1e-3], [1e-3, 9.0e-1], 1_000)


def test_c4_log_tolerance_and_fraction_boundaries_are_inclusive():
    within = sc.score_c4([-9.0], [1e-3], [10 ** (-3 + 0.5)], 10**7)
    assert within.n_within == 1
    assert sc.score_c4([-9.0], [1e-3], [10 ** (-3 + 0.51)], 10**7).n_within == 0
    four_of_five = sc.score_c4([-9.0] * 4 + [-8.0], [1e-3] * 5, [1e-3] * 4 + [1e-1], 10**7)
    assert four_of_five.fraction_within == 0.8 and four_of_five.passed


def test_c3_ber_condition_is_strictly_above_the_threshold_and_in_range():
    rop = [-9.0, -8.0]
    snr_n, snr_s = [20.0, 21.0], [20.0 - 5.0, 21.0 - 5.0]
    at = sc.score_c3(80, rop, snr_n, rop, snr_s, [3.8e-3, 3.8e-3])
    assert at.ssmf_ber_ok is False and at.penalty_ok is True
    above = sc.score_c3(80, rop, snr_n, rop, snr_s, [3.9e-3, 3.8e-3 + 1e-9])
    assert above.ssmf_ber_ok is True
    for bad in (2.0, -0.1):
        with pytest.raises(sc.InvalidDataError):
            sc.score_c3(80, rop, snr_n, rop, snr_s, [bad, 0.5])


def test_overall_verdict_rejects_truthy_junk():
    for junk in ("no", "False", float("nan"), 1, 0, None, [False]):
        with pytest.raises(ValueError, match="must be a boolean"):
            sc.RateScores(junk, True, True, True, True, True)
        with pytest.raises(ValueError, match="must be a boolean"):
            sc.RateScores(True, True, True, True, True, True, b2b_poor=junk)
    ok = sc.RateScores(np.True_, True, True, True, True, True)
    assert sc.overall_verdict({r: ok for r in sc.RATES}).failed == ()


def test_crossing_is_validated():
    bad = [
        ("point", math.inf, math.inf), ("point", 1.0, 2.0), ("point", math.nan, math.nan),
        ("left", 0.0, -5.0), ("left", -math.inf, math.inf), ("right", -5.0, 0.0),
        ("right", math.inf, math.inf), ("interval", -5.0, -9.0), ("interval", -math.inf, 0.0),
        ("interval", math.nan, 0.0), ("unknown", 0.0, 0.0), ("invalid", 0.0, 0.0),
        ("point", True, True), ("point", "1", "1"), ("point", None, None),
    ]  # fmt: skip
    for kind, lo, hi in bad:
        with pytest.raises(ValueError):
            sc.Crossing(kind, lo, hi)
    sc.Crossing("point", -10.0, -10.0)
    sc.Crossing("left", -math.inf, -10.0)
    sc.Crossing("right", -10.0, math.inf)
    sc.Crossing("interval", -10.0, -10.0)
    sc.Crossing("invalid", math.nan, math.nan)
    # a published point at infinity used to pass anything
    with pytest.raises(ValueError):
        sc.score_c1(sc.Crossing("point", math.inf, math.inf), sc.Crossing("point", 0.0, 0.0))


def test_c5_files_only_1630_and_1640_apart():
    wl = [1460.0 + 10.0 * k for k in range(17)]
    snr = [20.0] * 17
    ok = sc.score_c5("nanf", [*wl, 1630.0, 1640.0], [*snr, 99.0, 99.0], [*snr, 0.0, 0.0])
    assert ok.excluded_nm == (1630.0, 1640.0) and ok.passed
    for extra in (1700.0, 1450.0, 1635.0, float("nan")):
        with pytest.raises(ValueError, match="1630 and 1640|17 wavelengths"):
            sc.score_c5("nanf", [*wl, extra], [*snr, 0.0], [*snr, 0.0])


def test_c7_ratio_and_capacity_boundaries_are_inclusive(monkeypatch):
    monkeypatch.setattr(sc, "C7_RATIO_TOL", 0.125)  # exactly representable
    assert sc.score_c7(90.0, 80.0, 80.0, 80.0).passed  # er == 0.125, en == 10 exactly
    assert not sc.score_c7(90.0 + 1e-9, 80.0, 80.0, 80.0).passed  # beyond 10 Gb/s
    monkeypatch.setattr(sc, "C7_RATIO_TOL", 0.1249)
    assert not sc.score_c7(90.0, 80.0, 80.0, 80.0).passed  # ratio just beyond


def test_the_cap_text_in_the_validity_doc_and_dfe_are_corrected():
    doc = open("docs/NANF_MODEL_VALIDITY.md").read()
    assert "1e10" in doc and "np.clip" in doc and "3%" not in doc.split("## 8")[1].split("## 9")[0]
    text = open("src/opticps/receiver/dfe.py").read()
    assert "constant-trace" in text and "Overflow is not" in text
