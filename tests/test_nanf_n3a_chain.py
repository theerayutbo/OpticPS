"""Gate N3 part a: the NANF simulation chain, on synthetic data only (no workbook is read)."""

import math
import time

import numpy as np
import pytest

from nanf_profile_helpers import known, make_profile
from opticps.measurement import nanf_chain as nc
from opticps.measurement.nanf_benchmark import numerical_profile
from opticps.transmitter.pulse import PulseConfig, resample_periodic, shape

SMALL = nc.ChainConfig(n_symbols=14_000, training_symbols=2_000)  # 140 x 100


# --- the sample grid and exact resampling -------------------------------------------------------


@pytest.mark.parametrize(
    ("baud", "awg", "analogue", "scope"),
    [(40, 7, 28, 8), (50, 7, 28, 8), (56, 7, 28, 8)],
)
def test_sample_counts_for_40_50_and_56_gbd_are_the_integers_of_plan_f1(baud, awg, analogue, scope):
    n = 655_200
    counts = nc.sample_counts(n, baud)
    # fs / Rs samples per symbol: 70/40, 70/50, 70/56 at the AWG; 280/Rs; 80/Rs; 2 at T/2
    assert counts["awg"] * baud * 10**9 == n * nc.AWG_RATE_HZ
    assert counts["analogue"] * baud * 10**9 == n * nc.ANALOGUE_RATE_HZ
    assert counts["scope"] * baud * 10**9 == n * nc.SCOPE_RATE_HZ
    assert counts["t2"] == 2 * n


def test_the_declared_samples_per_symbol_arithmetic():
    n = 655_200
    assert nc.sample_counts(n, 40) == {
        "awg": 1_146_600,
        "analogue": 4_586_400,
        "scope": 1_310_400,
        "t2": 1_310_400,
    }
    assert nc.sample_counts(n, 50) == {
        "awg": 917_280,
        "analogue": 3_669_120,
        "scope": 1_048_320,
        "t2": 1_310_400,
    }
    assert nc.sample_counts(n, 56) == {
        "awg": 819_000,
        "analogue": 3_276_000,
        "scope": 936_000,
        "t2": 1_310_400,
    }
    assert n == 140 * 4680 and n - nc.TRAINING_SYMBOLS == 647_008
    assert 2 * (n - nc.TRAINING_SYMBOLS) == 1_294_016


def test_a_multiple_of_140_is_needed_and_the_old_length_of_a_multiple_of_20_is_refused():
    for n in (140, 280, 14_000, 655_200):
        for baud in (40, 50, 56):
            nc.sample_counts(n, baud)
    # 655360 = 20 x 32768 is fine at 70 GSa/s and wrong at the 80 GSa/s scope for 56 GBd
    with pytest.raises(nc.ChainGridError, match="not a multiple of 140|samples at"):
        nc.sample_counts(655_360, 56)
    assert 655_360 * 10 / 7 == pytest.approx(936_228.571, abs=1e-3)
    with pytest.raises(nc.ChainGridError):
        nc.ChainConfig(n_symbols=655_360)
    # any multiple of 20 that is not a multiple of 7 breaks at 56 GBd; any multiple of 28 that is not
    # of 5 breaks at 50 GBd; lcm(4, 5, 7) = 140 is the least length that serves all three
    for n in (20, 40, 60, 100, 120):
        with pytest.raises(nc.ChainGridError):
            nc.sample_counts(n, 56)
    for n in (28, 56, 84, 112):
        with pytest.raises(nc.ChainGridError):
            nc.sample_counts(n, 50)
    for n in (35, 70, 105):
        with pytest.raises(nc.ChainGridError):
            nc.sample_counts(n, 40)  # 7n/4 is not whole
    with pytest.raises(nc.ChainGridError):
        nc.ChainConfig(n_symbols=0)


def test_exact_length_refuses_any_non_integer_result():
    from fractions import Fraction

    assert nc.exact_length(1400, Fraction(2, 7)) == 400
    with pytest.raises(nc.ChainGridError):
        nc.exact_length(1401, Fraction(2, 7))
    with pytest.raises(nc.ChainGridError):
        nc.resample_exact(np.zeros(1401), 280_000_000_000, 80_000_000_000)
    with pytest.raises(nc.ChainGridError):
        nc.resample_exact(np.zeros(100), 280e9 + 0.5, 80e9)  # not whole Hz


@pytest.mark.parametrize(
    ("fs_in", "fs_out", "n_in"),
    [
        (70e9, 280e9, 700),  # x4
        (280e9, 80e9, 2800),  # x2/7
        (80e9, 100e9, 800),  # x5/4
        (80e9, 112e9, 1000),  # x7/5
        (80e9, 80e9, 100),
    ],
)
def test_resampling_preserves_in_band_tones_and_dc_to_rounding(fs_in, fs_out, n_in):
    fs_in, fs_out = int(fs_in), int(fs_out)
    n_out = n_in * fs_out // fs_in
    assert n_out * fs_in == n_in * fs_out
    k = np.array([3, 17, 29])  # cycles per capture, below both Nyquists
    t_in = np.arange(n_in) / n_in
    t_out = np.arange(n_out) / n_out
    amp, ph = [1.0, 0.5, 0.25], [0.3, 1.1, -0.7]
    x = 2.5 + sum(
        a * np.cos(2 * np.pi * kk * t_in + p) for a, kk, p in zip(amp, k, ph, strict=True)
    )
    y = nc.resample_exact(x, fs_in, fs_out)
    ref = 2.5 + sum(
        a * np.cos(2 * np.pi * kk * t_out + p) for a, kk, p in zip(amp, k, ph, strict=True)
    )
    assert y.size == n_out and np.max(np.abs(y - ref)) < 1e-12


def test_resampling_up_then_down_is_the_identity_for_a_band_limited_signal():
    rng = np.random.default_rng(1)
    spectrum = np.zeros(351, dtype=complex)  # 700-point signal, content below 0.4 of Nyquist
    spectrum[1:140] = rng.normal(size=139) + 1j * rng.normal(size=139)
    x = np.fft.irfft(spectrum, n=700)
    up = nc.resample_exact(x, 70_000_000_000, 280_000_000_000)
    back = nc.resample_exact(up, 280_000_000_000, 70_000_000_000)
    assert up.size == 2800 and np.max(np.abs(back - x)) < 1e-12
    assert np.isclose(np.mean(up), np.mean(x), atol=1e-14)


def test_a_nyquist_bin_is_split_on_the_way_up_and_dropped_on_the_way_down():
    n = 8
    x = np.cos(np.pi * np.arange(n))  # a tone exactly at the input Nyquist
    up = nc.resample_exact(x, 1, 2)
    assert np.allclose(up, np.cos(np.pi * np.arange(2 * n) / 2))  # one cycle per 2 input samples
    assert np.max(np.abs(nc.resample_exact(np.cos(np.pi * np.arange(16)), 2, 1))) < 1e-12


def test_shape_srrc_equals_the_papers_chain_of_70x_upsampling_srrc_and_decimation():
    rng = np.random.default_rng(2)
    levels = rng.choice([-3.0, -1.0, 1.0, 3.0], 140)
    for baud in (40, 50, 56):
        n_awg = nc.sample_counts(140, baud)["awg"]
        reference = resample_periodic(
            shape(levels, 70, PulseConfig("rrc", nc.SRRC_ROLL_OFF)), 1 / baud
        )
        assert reference.size == n_awg
        direct = nc.shape_srrc(levels, n_awg, nc.SRRC_ROLL_OFF)
        assert np.max(np.abs(direct - reference)) < 1e-10, baud


def test_the_srrc_roll_off_is_the_papers_0_1():
    assert nc.SRRC_ROLL_OFF == 0.1 and nc.ChainConfig().roll_off == 0.1
    levels = np.random.default_rng(3).choice([-3.0, -1.0, 1.0, 3.0], 140)
    wave = nc.shape_srrc(levels, 245, 0.1)
    spectrum = np.abs(np.fft.rfft(wave))
    # nothing above (1 + 0.1) / 2 symbol rates: bins at or above 0.55 x 140 = 77 are empty
    assert spectrum[78:].max() < 1e-9 * spectrum.max()
    assert spectrum[70] > 1e-3 * spectrum.max()  # inside the band


def test_dac_quantiser_is_eight_bit_with_full_scale_at_the_peak():
    x = np.random.default_rng(4).normal(size=5000)
    q = nc.dac_quantise(x, 8)
    assert np.max(np.abs(q)) == 1.0 and np.abs(q).max() <= 1.0 and np.unique(q).size <= 256
    assert np.max(np.abs(q - x / np.max(np.abs(x)))) <= 1 / 255 + 1e-12  # half a step is 1/255
    with pytest.raises(ValueError):
        nc.dac_quantise(np.zeros(10))


# --- parameters, seeds ---------------------------------------------------------------------------


def test_tx_rx_parameters_are_the_six_of_plan_b4_and_are_never_clipped():
    assert nc.B4_NAMES == (
        "tx_bandwidth_ghz", "rx_bandwidth_ghz", "thermal_noise_pa_per_rthz",
        "modulation_depth", "bias_fraction", "electrical_snr_ceiling_db",
    )  # fmt: skip
    p = nc.TxRxParameters()
    assert p.as_dict() == {s.name: s.prior for s in nc.B4_PARAMETERS}
    for spec in nc.B4_PARAMETERS:
        nc.TxRxParameters(**{spec.name: spec.low})
        nc.TxRxParameters(**{spec.name: spec.high})
        for bad in (spec.low - 1e-9, spec.high + 1e-9, float("nan"), float("inf"), True, "1"):
            with pytest.raises(ValueError):
                nc.TxRxParameters(**{spec.name: bad})
    with pytest.raises(ValueError):
        nc.TxRxParameters.from_mapping({"tx_bandwidth_ghz": 30.0})
    with pytest.raises(ValueError):
        nc.TxRxParameters.from_mapping({**p.as_dict(), "chirp": 0.0})


def test_symbols_and_noise_follow_the_declared_seed_policy():
    a, b = nc.symbol_indices(1400), nc.symbol_indices(1400)
    assert np.array_equal(a, b) and set(np.unique(a)) == {0, 1, 2, 3}
    assert np.array_equal(a, np.random.default_rng(20261101).integers(0, 4, 1400))
    first = nc.noise_generator(56, 3).standard_normal(5)
    assert np.array_equal(first, nc.noise_generator(56, 3).standard_normal(5))
    assert not np.array_equal(first, nc.noise_generator(56, 4).standard_normal(5))
    assert not np.array_equal(first, nc.noise_generator(50, 3).standard_normal(5))
    expected = np.random.default_rng(np.random.SeedSequence([20261101, 7919, 56, 3]))
    assert np.array_equal(first, expected.standard_normal(5))
    # roughly uniform symbols
    assert np.all(np.abs(np.bincount(nc.symbol_indices(200_000)) / 200_000 - 0.25) < 0.01)


# --- tone mode: the chain reproduces the first null ----------------------------------------------


def test_the_chain_reproduces_the_first_null_of_the_closed_form_in_tone_mode():
    c = 299_792_458.0
    for name, length, d_ps, window in (
        ("SSMF", 4.53, 15.95, (26.0, 33.0)),
        ("SSMF", 5.0, 15.95, (24.0, 31.0)),
        ("NANF", 4.76, 2.04, (74.0, 87.0)),
    ):
        link = nc.LinkSpec(numerical_profile(name, length_km=length, d_ps_per_nm_km=d_ps))
        closed = math.sqrt(c / (2 * (1550e-9) ** 2 * d_ps * 1e-6 * length * 1e3)) / 1e9
        found = nc.first_null_ghz(link, window, step_ghz=0.1)
        assert abs(found - closed) < 0.3, (name, found, closed)  # plan A1.3 tolerance
    assert closed == pytest.approx(80.2, abs=0.05)


def test_tone_mode_refuses_off_grid_tones_and_a_window_without_an_interior_null():
    link = nc.LinkSpec(numerical_profile("SSMF", length_km=4.53, d_ps_per_nm_km=15.95))
    with pytest.raises(nc.ChainGridError):
        nc.tone_amplitude(10.01e9, link)
    with pytest.raises(ValueError, match="no interior null"):
        nc.first_null_ghz(link, (5.0, 10.0), step_ghz=0.1)
    with pytest.raises(ValueError):
        nc.first_null_ghz(link, (26.0, 33.0), step_ghz=0.001)


# --- the analogue path ---------------------------------------------------------------------------


def _drive(n=2800):
    return np.random.default_rng(5).uniform(-1, 1, n)


def test_matched_received_power_holds_with_and_without_fibre_and_loss():
    cfg = nc.ChainConfig()
    lossy = make_profile()  # 0.5 dB/km, 5 km: 2.5 dB
    for link, rop in (
        (nc.LinkSpec(), -8.0),
        (nc.LinkSpec(lossy), -8.0),
        (nc.LinkSpec(lossy), -5.0),
    ):
        out = nc.analogue_path(
            _drive(), 280e9, tx_bandwidth_hz=35e9, rx_bandwidth_hz=35e9, modulation_depth=0.6,
            bias_fraction=0.5, thermal_a_per_rthz=0.0, link=link, rop_dbm=rop, config=cfg,
        )  # fmt: skip
        assert nc.watt_to_dbm(out.mean_received_w) == pytest.approx(rop, abs=1e-9)
    # a larger loss needs a larger laser, which a 1 W sanity limit then refuses
    huge = make_profile(
        attenuation_db_per_km=known(
            60.0, "dB/km", measurement_wavelength_nm=1550.0, validity_range_nm=(1400.0, 1700.0)
        )
    )
    with pytest.raises(ValueError, match="laser"):
        nc.analogue_path(
            _drive(), 280e9, tx_bandwidth_hz=None, rx_bandwidth_hz=None, modulation_depth=0.6,
            bias_fraction=0.5, thermal_a_per_rthz=0.0, link=nc.LinkSpec(huge), rop_dbm=-5.0, config=cfg,
        )  # fmt: skip
    with pytest.raises(ValueError):
        nc.analogue_path(
            _drive() * 2, 280e9, tx_bandwidth_hz=None, rx_bandwidth_hz=None, modulation_depth=0.6,
            bias_fraction=0.5, thermal_a_per_rthz=0.0, link=nc.LinkSpec(), rop_dbm=-5.0, config=cfg,
        )  # fmt: skip


def test_noise_is_linear_and_additive_and_both_draws_are_needed():
    cfg = nc.ChainConfig()
    kwargs = dict(
        tx_bandwidth_hz=35e9, rx_bandwidth_hz=35e9, modulation_depth=0.6, bias_fraction=0.5,
        thermal_a_per_rthz=30e-12, link=nc.LinkSpec(), rop_dbm=-8.0, config=cfg,
    )  # fmt: skip
    z = np.random.default_rng(6)
    a, b = z.standard_normal(2800), z.standard_normal(2800)
    out = nc.analogue_path(_drive(), 280e9, z_shot=a, z_thermal=b, **kwargs)
    clean = nc.analogue_path(_drive(), 280e9, **kwargs)
    assert clean.noise is None and out.noise is not None
    assert np.array_equal(out.signal, clean.signal)
    with pytest.raises(ValueError):
        nc.analogue_path(_drive(), 280e9, z_shot=a, **kwargs)
    # thermal noise rms before the Rx filter is density x sqrt(fs / 2)
    zero_shot = nc.analogue_path(
        _drive(), 280e9, z_shot=np.zeros(2800), z_thermal=b, **{**kwargs, "rx_bandwidth_hz": None}
    )
    assert np.std(zero_shot.noise) == pytest.approx(30e-12 * math.sqrt(140e9), rel=0.05)


# --- the whole chain -----------------------------------------------------------------------------

WIDE = nc.TxRxParameters(tx_bandwidth_ghz=60.0, rx_bandwidth_ghz=60.0)


def test_a_noise_free_back_to_back_chain_has_zero_decision_errors():
    for rate in (80, 100, 112):
        r = nc.simulate_point(WIDE, rate, -8.0, config=SMALL, noise=False)
        assert r.reading.errors == 0 and r.reading.censored and "below 1/N_b" in r.reading.text
        assert r.ser == 0.0 and r.snr_db > 20.0
        assert r.n_scored_symbols == 12_000 and r.reading.n_bits == 24_000
        assert r.mean_received_dbm == pytest.approx(-8.0, abs=1e-9)


def test_the_chain_is_deterministic_and_noise_is_common_to_links_at_one_point():
    p = nc.TxRxParameters()
    a = nc.simulate_point(p, 112, -9.0, config=SMALL, point_index=2)
    b = nc.simulate_point(p, 112, -9.0, config=SMALL, point_index=2)
    c = nc.simulate_point(p, 112, -9.0, config=SMALL, point_index=3)
    assert (a.reading.errors, a.snr_db) == (b.reading.errors, b.snr_db)
    assert np.array_equal(a.dfe.output, b.dfe.output)
    assert a.snr_db != c.snr_db  # a different point has a different noise draw


def test_ber_falls_and_snr_rises_with_received_power_and_the_fibre_costs_snr_at_high_rate():
    p = nc.TxRxParameters()
    cfg = nc.ChainConfig(n_symbols=28_000, training_symbols=2_000)
    snr = [
        nc.simulate_point(p, 100, rop, config=cfg, point_index=i).snr_db
        for i, rop in enumerate((-12, -10, -8, -6))
    ]
    assert all(b > a for a, b in zip(snr, snr[1:], strict=False))
    ssmf = nc.LinkSpec(numerical_profile("SSMF", length_km=4.53, d_ps_per_nm_km=15.95))
    b2b = nc.simulate_point(p, 112, -7.0, config=cfg, point_index=1)
    far = nc.simulate_point(p, 112, -7.0, config=cfg, point_index=1, link=ssmf)
    assert far.snr_db < b2b.snr_db - 2.0  # the dispersion penalty of 4.53 km SSMF at 56 GBd
    nanf = nc.LinkSpec(numerical_profile("NANF", length_km=4.76, d_ps_per_nm_km=2.04))
    near = nc.simulate_point(p, 112, -7.0, config=cfg, point_index=1, link=nanf)
    assert abs(near.snr_db - b2b.snr_db) < 1.5 and near.snr_db > far.snr_db + 2.0


def test_bit_error_counting_and_the_snr_definition_of_b6():
    tx = np.array([0, 1, 2, 3, 0, 1, 2, 3])
    rx = np.array([0, 2, 2, 3, 1, 1, 2, 0])  # Gray 00 01 11 10: 1->2, 0->1, 3->0 are one bit each
    assert nc.count_bit_errors(tx, rx) == 3
    assert nc.count_bit_errors(np.array([0]), np.array([2])) == 2  # 00 against 11
    levels = np.array([-3.0, -1.0, 1.0, 3.0] * 5)
    out = levels + 0.5
    assert nc.snr_db_b6(levels, out) == pytest.approx(10 * math.log10(5.0 / 0.25))
    assert nc.snr_db_b6(levels, levels) == math.inf
    # the mean is over the scored symbols, not a per-symbol ratio
    assert nc.snr_db_b6(np.array([3.0, 1.0]), np.array([3.0, 0.0])) == pytest.approx(
        10 * math.log10(5.0 / 0.5)
    )


def test_ber_reading_applies_the_plans_censoring():
    zero = nc.BerReading.from_counts(0, 1_294_016)
    assert (
        zero.censored and zero.ber == 0.0 and "below 1/N_b" in zero.text and "7.7e-07" in zero.text
    )
    low = nc.BerReading.from_counts(5, 1_294_016)  # 3.9e-6: below 1e-5
    assert low.censored and low.ber == pytest.approx(5 / 1_294_016)
    edge = nc.BerReading.from_counts(13, 1_294_016)  # 1.0046e-5
    assert not edge.censored
    assert not nc.BerReading.from_counts(129, 1_294_016).censored
    # at BER 1e-4 the scored bits give 129.4 errors (plan F2), not 65
    assert 1_294_016 * 1e-4 == pytest.approx(129.4, abs=0.05)
    for bad in ((-1, 10), (11, 10), (0, 0)):
        with pytest.raises(ValueError):
            nc.BerReading.from_counts(*bad)


def test_the_chain_refuses_a_bad_rate_a_bad_equaliser_and_a_bad_power():
    p = nc.TxRxParameters()
    with pytest.raises(ValueError):
        nc.simulate_point(p, 90, -8.0, config=SMALL)
    from opticps.receiver.dfe import RlsDfeConfig

    with pytest.raises(ValueError):
        nc.simulate_point(p, 80, -8.0, config=SMALL, equalizer=RlsDfeConfig(training_symbols=100))
    with pytest.raises(ValueError):
        nc.simulate_point(
            p,
            80,
            -8.0,
            config=SMALL,
            equalizer=RlsDfeConfig(samples_per_symbol=1, training_symbols=2000),
        )
    with pytest.raises(ValueError):
        nc.simulate_point(
            p, 80, 11.0, config=SMALL
        )  # above the sanity limit of the matched protocol


def test_one_full_size_point_runs_in_seconds_and_reports_its_cost():
    start = time.perf_counter()
    r = nc.simulate_point(nc.TxRxParameters(), 100, -8.0, point_index=5)
    wall = time.perf_counter() - start
    assert r.n_scored_symbols == 647_008 and r.reading.n_bits == 1_294_016
    assert 1e-4 < r.ber < 5e-3 and not r.reading.censored  # about 5e-4 at the prior vector
    assert set(r.seconds) >= {
        "transmitter",
        "analogue",
        "scope",
        "front end",
        "equaliser",
        "metrics",
    }
    assert r.seconds["equaliser"] < 120.0 and wall < 300.0
    assert r.dfe.max_p_asymmetry == 0.0


def test_declared_constants_are_those_of_amendment_5():
    assert (nc.SYMBOL_SEED, nc.NOISE_SEED_TAG) == (20261101, 7919)
    assert (nc.AWG_RATE_HZ, nc.ANALOGUE_RATE_HZ, nc.SCOPE_RATE_HZ) == (
        70 * 10**9,
        280 * 10**9,
        80 * 10**9,
    )
    assert nc.DAC_BITS == 8 and nc.ChainConfig().dac_bits == 8
    assert (nc.TRAINING_SYMBOLS, nc.GRID_MULTIPLE, nc.CAPTURE_SYMBOLS) == (8192, 140, 655_200)
    assert nc.ChainConfig().training_symbols == 8192 and nc.ChainConfig().n_symbols == 655_200
    assert nc.RESPONSIVITY_A_PER_W == 0.8 and nc.ChainConfig().responsivity_a_per_w == 0.8
    assert nc.EXTINCTION_DB == 30.0 and nc.BER_CENSOR_FLOOR == 1e-5
    assert nc.BAUD_GBD == {80: 40, 100: 50, 112: 56}
    from opticps.receiver.dfe import RlsDfeConfig

    d = RlsDfeConfig()  # plan F6
    assert (d.ff_taps, d.fb_taps, d.samples_per_symbol, d.main_tap) == (17, 7, 2, 8)
    assert (d.forgetting, d.delta, d.training_symbols) == (0.998, 1e-2, 8192)
    assert d.levels == (-3.0, -1.0, 1.0, 3.0) and d.decision_directed


def test_the_ceiling_noise_has_the_declared_variance_and_shot_noise_follows_2qi():
    sig = np.random.default_rng(7).normal(0.0, 3.0, 10_000) + 5.0
    for c in (15.0, 25.0, 35.0):
        assert nc.ceiling_noise_std(sig, c) ** 2 == pytest.approx(np.var(sig) / 10 ** (c / 10))
    # shot noise only: variance 2 q I fs / 2 at the current, with the thermal draw set to zero
    cfg = nc.ChainConfig()
    n = 200_000
    z = np.random.default_rng(8).standard_normal(n)
    out = nc.analogue_path(
        np.zeros(n), 280e9, tx_bandwidth_hz=None, rx_bandwidth_hz=None, modulation_depth=0.6,
        bias_fraction=0.5, thermal_a_per_rthz=0.0, link=nc.LinkSpec(), rop_dbm=-3.0, config=cfg,
        z_shot=z, z_thermal=np.zeros(n),
    )  # fmt: skip
    current = 0.8 * 10 ** (-3.0 / 10) * 1e-3
    assert np.std(out.noise) == pytest.approx(
        math.sqrt(2 * nc.ELEMENTARY_CHARGE * current * 140e9), rel=0.01
    )
    assert out.signal.mean() == pytest.approx(current, rel=1e-9)


def test_the_matched_filter_makes_the_pulse_inter_symbol_interference_free():
    n = 140
    levels = np.zeros(n)
    levels[0] = 1.0
    pulse = nc.shape_srrc(levels, 2 * n, 0.1)  # one SRRC pulse at 2 samples per symbol
    both = nc.matched_filter_t2(pulse, 0.1)  # SRRC x SRRC = raised cosine: Nyquist
    assert both[0] == pytest.approx(both.max())
    assert np.max(np.abs(both[2::2][:100])) < 2e-3 * both[0]  # zeros at the other symbol instants
    assert abs(both[1]) > 0.1 * both[0]  # between symbols there is signal
    flat = np.ones(2 * n)
    assert np.allclose(nc.matched_filter_t2(flat, 0.1), 1.0)  # unit DC gain
