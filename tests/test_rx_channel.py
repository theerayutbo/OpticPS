import numpy as np
import pytest
from scipy.integrate import quad
from scipy.special import erfc

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.modulation.pam import pam_levels
from opticps.optical_channel.link import (
    ELEMENTARY_CHARGE,
    LinkConfig,
    cd_null_frequency_hz,
    dbm_to_watt,
    mzm_intensity,
    noise_power_gain,
    transmit,
    watt_to_dbm,
)
from opticps.optimization.rates import achievable_rates, noise_sigma_from_psnr_db
from opticps.receiver.dsp import (
    Likelihood,
    align,
    calibrate,
    detect_map,
    frame_sync,
    lms_ffe,
    matched_filter,
    process_capture,
    resample_to_symbols,
    train_ffe,
)
from opticps.shaping.distributions import OUTER70, PS70, UNIFORM
from opticps.statistics.intervals import (
    bootstrap_interval,
    clopper_pearson,
    paired_difference_interval,
)
from opticps.transmitter.frame import build_frame
from opticps.transmitter.pulse import PulseConfig, shape


def frame_for(p, total=32768, seed=7):
    return build_frame("t", p, total, seed, direct_uniform=p is UNIFORM)


def nrz(frame, sps=8):
    return shape(pam_levels(4)[frame.indices], sps, PulseConfig())


def test_noise_free_chain_recovers_everything():
    frame = frame_for(PS70)
    result = process_capture(nrz(frame), 64e9, 8e9, frame, np.array(PS70))
    assert result.map.symbol_errors == 0
    assert result.map.bit_errors == 0
    assert result.sync.peak_to_sidelobe > 5
    decisions = result.decisions_map[frame.payload_start :]
    matcher = ConstantCompositionMatcher(frame.matcher_counts)
    recovered = np.concatenate(
        [matcher.decode(b) for b in decisions.reshape(frame.n_blocks, frame.block_length)]
    )
    assert np.array_equal(recovered, frame.info_bits)


@pytest.mark.parametrize("delay", [0, 137, 20011])
@pytest.mark.parametrize("gain", [0.002, -0.5])
def test_sync_handles_offset_inversion_and_dc(delay, gain):
    frame = frame_for(UNIFORM)
    capture = np.roll(nrz(frame), delay) * gain + 0.7
    result = process_capture(capture, 64e9, 8e9, frame, np.full(4, 0.25))
    assert result.map.symbol_errors == 0
    assert result.sync.inverted == (gain < 0)


def test_non_integer_oversampling_capture():
    frame = frame_for(UNIFORM)
    wave = nrz(frame, 28)
    spectrum = np.fft.rfft(wave)
    target = int(wave.size * 80 / 224)
    size = target // 2 + 1
    capture = np.fft.irfft(spectrum[:size], n=target) * target / wave.size
    result = process_capture(capture, 80e9, 8e9, frame, np.full(4, 0.25))
    assert result.map.symbol_errors == 0


def analytic_pam4_ser(sigma_spacing2):
    return 0.75 * erfc(1 / (np.sqrt(2) * sigma_spacing2))


def test_ser_and_ber_match_analytic_awgn():
    rng = np.random.default_rng(5)
    errors = 0
    bit_errors = 0
    total = 0
    sigma = 0.42
    for _ in range(8):
        frame = frame_for(UNIFORM, seed=int(rng.integers(1 << 30)))
        noisy = pam_levels(4)[frame.indices] + rng.normal(0, sigma, frame.indices.size)
        wave = np.repeat(noisy, 8)
        result = process_capture(wave, 64e9, 8e9, frame, np.full(4, 0.25), taps=1)
        errors += result.minimum_distance.symbol_errors
        bit_errors += result.minimum_distance.bit_errors
        total += result.minimum_distance.symbols
    low, high = clopper_pearson(errors, total, 0.999)
    expected = analytic_pam4_ser(sigma)
    assert low <= expected <= high
    assert bit_errors / (2 * total) == pytest.approx(expected / 2, rel=0.08)


def test_map_beats_minimum_distance_for_shaped_input():
    rng = np.random.default_rng(9)
    md = mp = 0
    for _ in range(6):
        frame = frame_for(PS70, seed=int(rng.integers(1 << 30)))
        wave = np.repeat(pam_levels(4)[frame.indices] + rng.normal(0, 0.9, frame.indices.size), 8)
        result = process_capture(wave, 64e9, 8e9, frame, np.array(PS70), taps=1)
        md += result.minimum_distance.symbol_errors
        mp += result.map.symbol_errors
    assert mp < md


def test_map_limits():
    symbols = np.array([-3.1, 0.2, 2.9])
    law = Likelihood(pam_levels(4), np.full(4, 0.3))
    assert detect_map(symbols, law, np.full(4, 0.25)).tolist() == [0, 2, 3]
    skewed = np.array([1e-12, 0.5, 0.5 - 2e-12, 1e-12])
    assert detect_map(symbols, law, skewed).tolist() == [1, 2, 2]


@pytest.mark.parametrize("p", [UNIFORM, PS70, OUTER70])
def test_estimated_gmi_matches_analytic(p):
    rng = np.random.default_rng(3)
    sigma = 2 * noise_sigma_from_psnr_db(16.0)
    values = []
    for _ in range(6):
        frame = frame_for(p, 65536, int(rng.integers(1 << 30)))
        noisy = pam_levels(4)[frame.indices] + rng.normal(0, sigma, frame.indices.size)
        result = process_capture(np.repeat(noisy, 8), 64e9, 8e9, frame, np.array(p), taps=1)
        values.append(result.map.r_bmd)
    assert np.mean(values) == pytest.approx(achievable_rates(p, 16.0).bmd, abs=0.03)


def test_ffe_removes_known_isi_with_ls_and_lms():
    frame = frame_for(UNIFORM)
    sent = pam_levels(4)[frame.indices]
    channel = 1.0 * sent + 0.25 * np.roll(sent, 1) - 0.1 * np.roll(sent, -1)
    ls = train_ffe(channel, frame.indices, 15)
    lms = lms_ffe(channel, frame.indices, 15, step=0.003, epochs=20)
    for weights in (ls, lms):
        half = weights.size // 2
        output = sum(
            w * np.roll(channel, -k) for k, w in zip(range(-half, half + 1), weights, strict=False)
        )
        assert np.std(output - sent) < 0.08


def test_calibration_uses_preamble_not_payload():
    frame = frame_for(PS70)
    sent = pam_levels(4)[frame.indices]
    measured = 0.3 * sent + 1.5
    measured[frame.payload_start :] += 0.5
    calibration = calibrate(measured, frame.indices)
    assert calibration.gain == pytest.approx(0.3)
    assert calibration.offset == pytest.approx(1.5)


def test_power_conversions():
    assert dbm_to_watt(0) == pytest.approx(1e-3)
    assert watt_to_dbm(dbm_to_watt(-13.7)) == pytest.approx(-13.7)
    with pytest.raises(ValueError):
        watt_to_dbm(0)


def _drive(p, n=8192):
    levels = pam_levels(4)
    indices = np.random.default_rng(2).choice(4, size=n, p=np.array(p))
    return np.concatenate([levels[indices], -levels[indices]]) / 3


@pytest.mark.parametrize("p", [UNIFORM, PS70, OUTER70])
def test_symmetric_drive_gives_equal_mean_power_at_quadrature(p):
    config = LinkConfig(extinction_db=200, insertion_loss_db=0, v_pi=4, drive_vpp=3)
    assert mzm_intensity(_drive(p) * 1.5, config).mean() == pytest.approx(0.5, abs=1e-9)


def test_off_quadrature_breaks_mean_power_equality():
    config = LinkConfig(
        extinction_db=200, insertion_loss_db=0, v_pi=4, drive_vpp=4, bias_fraction_of_vpi=0.6
    )
    uniform = mzm_intensity(_drive(UNIFORM) * 2, config).mean()
    outer = mzm_intensity(_drive(OUTER70) * 2, config).mean()
    assert abs(10 * np.log10(uniform / outer)) > 0.05


def test_predistortion_equalizes_optical_spacing():
    levels = pam_levels(4) / 3
    config = LinkConfig(predistort=True, drive_vpp=3.2, extinction_db=200, insertion_loss_db=0)
    from opticps.optical_channel.link import predistort

    plain = np.diff(mzm_intensity(levels * 1.6, config))
    even = np.diff(mzm_intensity(predistort(levels, config), config))
    assert np.ptp(plain) > 0.05
    assert np.ptp(even) < 1e-9


def _spectrum_gain(frequency, config, fs=512e9, n=1 << 15):
    k = round(frequency * n / fs)
    drive = 0.02 * np.cos(2 * np.pi * k * np.arange(n) / n)
    quiet = LinkConfig(
        **{
            **config.__dict__,
            "thermal_noise_a_per_rthz": 0.0,
            "include_shot_noise": False,
            "receiver_bandwidth_hz": 200e9,
        }
    )
    out = transmit(drive, fs, quiet, np.random.default_rng(0)).current_a
    return abs(np.fft.rfft(out - out.mean())[k])


def test_cd_null_matches_theory():
    config = LinkConfig(fiber_length_km=10, extra_attenuation_db=0)
    null = cd_null_frequency_hz(config)
    assert null == pytest.approx(19.2e9, rel=0.02)
    assert _spectrum_gain(null, config) < 0.02 * _spectrum_gain(null / 8, config)


def test_zero_fiber_reduces_to_awgn_with_known_variance():
    config = LinkConfig(include_shot_noise=False, receiver_bandwidth_hz=64e9)
    signal = np.zeros(1 << 16)
    result = transmit(signal, 128e9, config, np.random.default_rng(1))
    assert np.std(result.current_a) == pytest.approx(result.noise_rms_a, rel=0.01)
    assert result.extinction_ratio_db == pytest.approx(0, abs=1e-9)


def test_shot_noise_variance():
    config = LinkConfig(thermal_noise_a_per_rthz=0.0, laser_power_w=1.0, receiver_bandwidth_hz=1e12)
    fs = 200e9
    result = transmit(np.zeros(1 << 17), fs, config, np.random.default_rng(1))
    mean = result.current_a.mean()
    gain = noise_power_gain(result.current_a.size, fs, fs / 2)
    assert gain == pytest.approx(quad(lambda x: 1 / (1 + x**8), 0, 1)[0], abs=1e-3)
    assert result.current_a.var() == pytest.approx(
        2 * ELEMENTARY_CHARGE * mean * fs / 2 * gain, rel=0.01
    )
    assert np.std(result.current_a) == pytest.approx(result.noise_rms_a, rel=0.01)


def test_thermal_limited_snr_slope_is_two_db_per_optical_db():
    frame = frame_for(UNIFORM)
    wave = shape(pam_levels(4)[frame.indices], 8, PulseConfig()) / 3
    snrs = []
    for loss in (10.0, 13.0):
        config = LinkConfig(
            extra_attenuation_db=loss, include_shot_noise=False, receiver_bandwidth_hz=30e9
        )
        link = transmit(wave, 64e9, config, np.random.default_rng(4))
        snrs.append(process_capture(link.current_a, 64e9, 8e9, frame, np.full(4, 0.25)).map.snr_db)
    assert snrs[0] - snrs[1] == pytest.approx(6.0, abs=0.5)


def test_unit_mismatch_rejected():
    with pytest.raises(ValueError):
        LinkConfig(drive_vpp=9, v_pi=4)
    with pytest.raises(ValueError):
        transmit(np.array([2.0]), 1e9, LinkConfig(), np.random.default_rng(0))


def test_clopper_pearson_known_values():
    assert clopper_pearson(0, 1000)[1] == pytest.approx(0.003682, abs=1e-5)
    assert clopper_pearson(1000, 1000)[0] > 0.99
    low, high = clopper_pearson(50, 100)
    assert low == pytest.approx(0.3983, abs=1e-3) and high == pytest.approx(0.6017, abs=1e-3)


def test_bootstrap_is_wider_for_correlated_blocks():
    rng = np.random.default_rng(1)
    blocks = [np.full(100, v) for v in rng.normal(0, 1, 40)]
    by_block = bootstrap_interval(
        blocks, lambda s: float(np.concatenate(s).mean()), np.random.default_rng(2), 500
    )
    samples = list(np.concatenate(blocks))
    by_sample = bootstrap_interval(
        samples, lambda s: float(np.mean(s)), np.random.default_rng(2), 500
    )
    assert by_block[1] - by_block[0] > 3 * (by_sample[1] - by_sample[0])


def test_paired_difference_needs_pairs():
    mean, interval = paired_difference_interval(
        [1, 2, 3, 4], [0, 1, 2, 3], np.random.default_rng(0), 200
    )
    assert mean == 1 and interval == (1, 1)
    with pytest.raises(ValueError):
        paired_difference_interval([1], [1, 2], np.random.default_rng(0))


def test_matched_filter_and_align_are_consistent():
    frame = frame_for(UNIFORM)
    filtered = matched_filter(nrz(frame), 8)
    sync = frame_sync(filtered, 8)
    aligned = align(filtered, sync, 8, frame.indices.size)
    assert np.allclose(aligned, pam_levels(4)[frame.indices], atol=0.3)


def test_resample_identity():
    x = np.sin(np.arange(1024) / 7)
    assert np.array_equal(resample_to_symbols(x, 8.0, 1.0, 8), x)
