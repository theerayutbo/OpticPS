"""Gate N1: profile-driven propagation checked against independent derivations.

Every expected number here comes from a closed form written in the test (or a literal physical
value), not from the code under test. No paper curve is simulated and nothing is scored.
"""

import math
from dataclasses import replace

import numpy as np
import pytest

from nanf_profile_helpers import known, make_profile, unknown
from opticps.optical_channel.fiber import (
    FiberProfileError,
    OutOfValidityRangeError,
    ParameterProvenance,
    PrecedenceDeclaration,
    ProfileValue,
    ProvenanceCategory,
    SensitivityScenario,
    UnsupportedEffectError,
    WavelengthTable,
    load_fiber_config,
    resolve_profile,
)
from opticps.optical_channel.link import (
    LinkConfig,
    PowerProtocol,
    beta2_s2_per_m,
    dispersive_field,
    group_delay_s,
    lowpass,
    mzm_intensity,
    profile_link_config,
    propagate_profile_field,
    transmit,
    transmit_profile,
)


def propagate_array(field, sample_rate, resolved):
    return propagate_profile_field(field, sample_rate, resolved).field


C = 299_792_458.0  # m/s, exact
LAMBDA = 1550e-9
ZERO_LOSS = {
    "attenuation_db_per_km": known(0.0, "dB/km", measurement_wavelength_nm=1550.0),
    "connector_loss_db": known(0.0, "dB"),
    "pigtail_loss_db": known(0.0, "dB"),
    "splice_loss_db": known(0.0, "dB"),
}


def lossless(**over):
    return make_profile(**{**ZERO_LOSS, **over})


def random_field(n=4096, seed=5):
    rng = np.random.default_rng(seed)
    return rng.normal(size=n) + 1j * rng.normal(size=n)


def power(x):
    return float(np.mean(np.abs(x) ** 2))


def test_lossless_dispersionless_fiber_is_the_identity():
    profile = lossless(
        dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0)
    )
    field = random_field()
    out = propagate_array(field, 64e9, resolve_profile(profile, 1550.0))
    assert np.allclose(out, field, rtol=0, atol=1e-12)


def test_lossless_dispersion_preserves_power_and_changes_the_field():
    resolved = resolve_profile(lossless(), 1550.0)
    field = random_field()
    out = propagate_array(field, 256e9, resolved)
    assert power(out) == pytest.approx(power(field), rel=1e-12)
    assert not np.allclose(out, field, atol=1e-3)


@pytest.mark.parametrize("alpha,d,length", [(0.0, 17.0, 5.0), (0.2, 2.04, 5.0), (1.5, 0.0, 0.1)])
def test_passive_loss_cannot_raise_power(alpha, d, length):
    profile = make_profile(
        attenuation_db_per_km=known(alpha, "dB/km", measurement_wavelength_nm=1550.0),
        dispersion_ps_per_nm_km=known(d, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        length_km=known(length, "km"),
    )
    field = random_field()
    out = propagate_array(field, 128e9, resolve_profile(profile, 1550.0))
    assert power(out) <= power(field) * (1 + 1e-12)


def test_power_ratio_follows_ten_to_minus_alpha_l_over_ten():
    field = random_field()
    for alpha, length in ((0.2, 10.0), (0.5, 3.0), (1.0, 7.5)):
        profile = make_profile(
            attenuation_db_per_km=known(alpha, "dB/km", measurement_wavelength_nm=1550.0),
            length_km=known(length, "km"),
            connector_loss_db=known(0.0, "dB"),
            pigtail_loss_db=known(0.0, "dB"),
            splice_loss_db=known(0.0, "dB"),
        )
        out = propagate_array(field, 64e9, resolve_profile(profile, 1550.0))
        assert power(out) / power(field) == pytest.approx(10 ** (-alpha * length / 10), rel=1e-12)
    # ratio between two lengths of the same fibre
    p5 = power(
        propagate_array(
            field,
            64e9,
            resolve_profile(make_profile(length_km=known(5.0, "km")), 1550.0),
        )
    )
    p9 = power(
        propagate_array(
            field,
            64e9,
            resolve_profile(make_profile(length_km=known(9.0, "km")), 1550.0),
        )
    )
    assert p9 / p5 == pytest.approx(10 ** (-0.5 * 4.0 / 10), rel=1e-12)


def test_amplitude_not_power_is_what_the_loss_exponent_halves():
    profile = lossless(
        pigtail_loss_db=known(6.0, "dB"),
        dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    out = propagate_array(np.ones(8, complex), 64e9, resolve_profile(profile, 1550.0))
    assert np.allclose(np.abs(out), 10 ** (-6.0 / 20))
    assert 10 ** (-6.0 / 20) == pytest.approx(
        0.501187, rel=1e-5
    )  # 6 dB halves power, not amplitude


def test_two_db_lump_is_counted_once():
    profile = make_profile(
        attenuation_db_per_km=known(0.0, "dB/km", measurement_wavelength_nm=1550.0),
        pigtail_loss_db=known(2.0, "dB"),
        dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    resolved = resolve_profile(profile, 1550.0)
    assert resolved.total_loss_db == 2.0
    field = random_field()
    out = propagate_array(field, 64e9, resolved)
    assert power(out) / power(field) == pytest.approx(10 ** (-0.2), rel=1e-12)
    # three separate components add; none is applied twice
    three = make_profile(
        attenuation_db_per_km=known(0.0, "dB/km", measurement_wavelength_nm=1550.0),
        connector_loss_db=known(0.5, "dB"),
        pigtail_loss_db=known(2.0, "dB"),
        splice_loss_db=known(0.1, "dB"),
        dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    out3 = propagate_array(field, 64e9, resolve_profile(three, 1550.0))
    assert power(out3) / power(field) == pytest.approx(10 ** (-0.26), rel=1e-12)


def test_through_the_link_the_lump_is_applied_once_and_with_the_length_term():
    profile = make_profile(
        length_km=known(2.0, "km"),
        attenuation_db_per_km=known(0.25, "dB/km", measurement_wavelength_nm=1550.0),
        pigtail_loss_db=known(2.0, "dB"),
        dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    rng = np.random.default_rng(0)
    wave = np.repeat([-1.0, -1 / 3, 1 / 3, 1.0], 64)
    res = transmit_profile(wave, 64e9, profile, 1550.0, rng)
    expected_db = 2.0 * 0.25 + 2.0
    assert res.link.received_power_w / res.link.launch_power_w == pytest.approx(
        10 ** (-expected_db / 10), rel=1e-12
    )
    # an attenuator already in the base config is kept and is not double counted either
    base = LinkConfig(extra_attenuation_db=3.0)
    res2 = transmit_profile(wave, 64e9, profile, 1550.0, np.random.default_rng(0), base=base)
    assert res2.link.received_power_w / res2.link.launch_power_w == pytest.approx(
        10 ** (-(expected_db + 3.0) / 10), rel=1e-12
    )


def small_signal_response(field_builder, resolved, fs, n, k):
    """Signed small-signal intensity response at bin k: Re(out phasor / in phasor)."""
    t = np.arange(n) / fs
    f = k * fs / n
    field = np.sqrt(1 + 0.01 * np.cos(2 * np.pi * f * t)) + 0j
    out = propagate_array(field, fs, resolved)
    spec_in = np.fft.fft(np.abs(field) ** 2)[k]
    spec_out = np.fft.fft(np.abs(out) ** 2)[k]
    return float(np.real(spec_out / spec_in))


def first_null_ghz(resolved, fs=640e9, n=1 << 15, lo_ghz=5.0, hi_ghz=110.0):
    """First sign change of the signed response, located by bracketing then linear interpolation."""
    bin_hz = fs / n
    step = 24
    ks = np.arange(int(lo_ghz * 1e9 / bin_hz), int(hi_ghz * 1e9 / bin_hz), step)
    prev_k, prev_r = None, None
    for k in ks:
        r = small_signal_response(None, resolved, fs, n, int(k))
        if prev_r is not None and prev_r > 0 >= r:
            lo, hi, r_lo, r_hi = prev_k, int(k), prev_r, r
            while hi - lo > 1:  # bisect on bins
                mid = (lo + hi) // 2
                r_mid = small_signal_response(None, resolved, fs, n, mid)
                if r_mid > 0:
                    lo, r_lo = mid, r_mid
                else:
                    hi, r_hi = mid, r_mid
            frac = r_lo / (r_lo - r_hi)
            return (lo + frac) * bin_hz / 1e9
        prev_k, prev_r = int(k), r
    raise AssertionError("no null found")


def test_zero_dispersion_has_no_fading():
    resolved = resolve_profile(
        lossless(
            dispersion_ps_per_nm_km=known(0.0, "ps/(nm km)", measurement_wavelength_nm=1550.0)
        ),
        1550.0,
    )
    for k in (100, 1500, 6000, 12000):
        assert small_signal_response(None, resolved, 640e9, 1 << 15, k) == pytest.approx(
            1.0, abs=2e-3
        )


def test_response_follows_cosine_law_of_dispersion():
    resolved = resolve_profile(
        lossless(
            length_km=known(4.53, "km"),
            dispersion_ps_per_nm_km=known(15.95, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        ),
        1550.0,
    )
    fs, n = 640e9, 1 << 15
    for k in (400, 900, 1300, 1500):
        f = k * fs / n
        expected = math.cos(math.pi * LAMBDA**2 * 15.95e-6 * 4.53e3 * f**2 / C)
        assert small_signal_response(None, resolved, fs, n, k) == pytest.approx(expected, abs=3e-3)


@pytest.mark.parametrize(
    "d,length,pre_registered",
    [(15.95, 4.53, 29.39), (15.95, 5.0, 27.97), (2.04, 4.76, 80.2)],
)
def test_first_null_matches_the_pre_registered_zero_chirp_values(d, length, pre_registered):
    profile = lossless(
        length_km=known(length, "km"),
        dispersion_ps_per_nm_km=known(d, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    null = first_null_ghz(resolve_profile(profile, 1550.0))
    analytic = math.sqrt(C / (2 * LAMBDA**2 * d * 1e-6 * length * 1e3)) / 1e9
    assert null == pytest.approx(analytic, abs=0.02)
    assert abs(null - pre_registered) < 0.05  # the plan's gate is 0.3 GHz (A1.3)


def test_first_null_for_the_nanf_profile_with_its_own_d_and_slope_and_a_labelled_scenario():
    hong = load_fiber_config("configs/fibers/NANF-HONG-2021-4P76KM.yaml")
    scenario = SensitivityScenario(
        "loss-free, null location does not depend on loss",
        {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0},
    )
    resolved = resolve_profile(hong, 1550.0, scenario=scenario)
    assert resolved.dispersion_slope_ps_per_nm2_km == 0.004
    assert first_null_ghz(resolved) == pytest.approx(80.2, abs=0.05)


def test_sign_of_d_positive_d_delays_longer_wavelengths():
    """D > 0: tau(lambda) rises with lambda, so the shorter-wavelength component arrives first."""
    fs, n = 1.6e12, 1 << 15
    t = (np.arange(n) - n // 2) / fs
    delta = 2 * np.pi * 200e9

    def arrival(d_ps, physical_offset):
        # E = A exp(-i omega0 t): a component A ~ exp(-i w t) sits at omega0 + w
        pulse = np.exp(-((t / 20e-12) ** 2)) * np.exp(-1j * physical_offset * t)
        profile = lossless(
            length_km=known(50.0, "km"),
            dispersion_ps_per_nm_km=known(d_ps, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        )
        out = propagate_array(pulse, fs, resolve_profile(profile, 1550.0))
        p = np.abs(out) ** 2
        return float((p * t).sum() / p.sum())

    for d in (17.0, 2.04):
        blue_minus_red = arrival(d, +delta) - arrival(d, -delta)  # +delta = shorter wavelength
        assert blue_minus_red < 0
        d_lambda = LAMBDA**2 * (2 * delta) / (2 * np.pi * C)  # wavelength span of the two carriers
        assert blue_minus_red == pytest.approx(-d * 1e-6 * 50e3 * d_lambda, rel=0.02)
    assert arrival(-17.0, +delta) - arrival(-17.0, -delta) > 0  # anomalous sign reverses it


def test_d_to_beta2_matches_an_independent_reference_value():
    # 17 ps/(nm km) at 1550 nm: beta2 = -21.68 ps^2/km (standard single-mode fiber, textbook order)
    assert beta2_s2_per_m(LAMBDA, 17e-6) * 1e27 == pytest.approx(-21.68, rel=1e-3)  # ps^2/km
    # hand evaluation: -17e-6 * (1550e-9)^2 / (2 pi c)
    hand = -17e-6 * 2.4025e-12 / (2 * math.pi * 299792458.0)
    assert beta2_s2_per_m(LAMBDA, 17e-6) == pytest.approx(hand, rel=1e-9)
    # and for the NANF value the transfer-function phase of a tone is beta2 L Omega^2 / 2
    fs, n = 256e9, 4096
    k = 300
    omega = 2 * np.pi * k * fs / n
    tone = np.exp(1j * omega * np.arange(n) / fs)
    resolved = resolve_profile(
        lossless(
            dispersion_ps_per_nm_km=known(2.04, "ps/(nm km)", measurement_wavelength_nm=1550.0)
        ),
        1550.0,
    )
    out = propagate_array(tone, fs, resolved)
    phase = float(np.angle(out[0] / tone[0]))
    expected = 0.5 * beta2_s2_per_m(LAMBDA, 2.04e-6) * 5e3 * omega**2
    assert math.remainder(phase - expected, 2 * math.pi) == pytest.approx(0.0, abs=1e-6)


def test_slope_adds_the_third_order_term_with_independent_beta3():
    """tau(+d) + tau(-d) = beta3 L d^2 for the symmetric pair; the beta2 term cancels."""
    fs, n = 1.6e12, 1 << 15
    t = (np.arange(n) - n // 2) / fs
    delta = 2 * np.pi * 150e9
    d_si, s_si = 2.04e-6, 0.004e3 * 25  # slope 0.1 ps/(nm^2 km) in s/m^3
    beta3 = (LAMBDA**4 * s_si + 2 * LAMBDA**3 * d_si) / (4 * math.pi**2 * C**2)
    length_km = 200.0

    def arrival(slope_ps, offset):
        pulse = np.exp(-((t / 20e-12) ** 2)) * np.exp(-1j * offset * t)
        profile = lossless(
            length_km=known(length_km, "km"),
            dispersion_ps_per_nm_km=known(2.04, "ps/(nm km)", measurement_wavelength_nm=1550.0),
            dispersion_slope_ps_per_nm2_km=known(
                slope_ps, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
            ),
        )
        out = propagate_array(pulse, fs, resolve_profile(profile, 1550.0))
        p = np.abs(out) ** 2
        return float((p * t).sum() / p.sum())

    symmetric = arrival(0.1, +delta) + arrival(0.1, -delta)
    assert symmetric == pytest.approx(beta3 * length_km * 1e3 * delta**2, rel=0.03)
    # slope 0.0 still has the 2 lambda^3 D part; slope omitted (None) has no third order at all
    beta3_zero_slope = 2 * LAMBDA**3 * d_si / (4 * math.pi**2 * C**2)
    zero = arrival(0.0, +delta) + arrival(0.0, -delta)
    assert zero == pytest.approx(beta3_zero_slope * length_km * 1e3 * delta**2, rel=0.03)
    assert symmetric > zero > 0


def test_slope_does_not_move_the_intensity_null_at_first_order():
    base = lossless(
        length_km=known(4.76, "km"),
        dispersion_ps_per_nm_km=known(2.04, "ps/(nm km)", measurement_wavelength_nm=1550.0),
    )
    sloped = lossless(
        length_km=known(4.76, "km"),
        dispersion_ps_per_nm_km=known(2.04, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        dispersion_slope_ps_per_nm2_km=known(
            0.004, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
        ),
    )
    n0 = first_null_ghz(resolve_profile(base, 1550.0))
    n1 = first_null_ghz(resolve_profile(sloped, 1550.0))
    assert n1 == pytest.approx(n0, abs=0.05)


def test_group_delay_is_ng_l_over_c_and_scales_linearly():
    hong = load_fiber_config("configs/fibers/NANF-HONG-2021-4P76KM.yaml")
    scenario = SensitivityScenario("s", {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0})
    resolved = resolve_profile(hong, 1550.0, scenario=scenario)
    assert group_delay_s(resolved) == pytest.approx(1.003 * 4.76e3 / 299_792_458.0, rel=1e-12)
    assert group_delay_s(resolved) * 1e6 == pytest.approx(
        15.92528, abs=1e-5
    )  # microseconds; 15.925 to the unit shown
    twice = resolve_profile(
        make_profile(length_km=known(9.52, "km"), group_index=known(1.003, "1")), 1550.0
    )
    assert group_delay_s(twice) == pytest.approx(2 * group_delay_s(resolved), rel=1e-12)
    ssmf = resolve_profile(
        make_profile(length_km=known(5.0, "km"), group_index=known(1.4682, "1")), 1550.0
    )
    nanf = resolve_profile(
        make_profile(length_km=known(5.0, "km"), group_index=known(1.003, "1")), 1550.0
    )
    assert (group_delay_s(ssmf) - group_delay_s(nanf)) * 1e6 == pytest.approx(
        7.759, abs=0.001
    )  # Sources: ~7.8 us
    with pytest.raises(Exception, match="no group index"):
        group_delay_s(resolve_profile(make_profile(), 1550.0))


def quad_wave():
    return np.repeat(np.random.default_rng(2).choice([-1.0, -1 / 3, 1 / 3, 1.0], 128), 8)


def test_fixed_launch_power_protocol_received_power_follows_the_loss():
    wave = quad_wave()
    results = {}
    for length in (1.0, 6.0):
        profile = make_profile(
            length_km=known(length, "km"),
            attenuation_db_per_km=known(0.4, "dB/km", measurement_wavelength_nm=1550.0),
            dispersion_ps_per_nm_km=known(5.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        )
        results[length] = transmit_profile(
            wave, 64e9, profile, 1550.0, np.random.default_rng(1), protocol="fixed-launch-power"
        )
    # same launch power at both lengths; received ratio is the extra loss
    assert results[1.0].link.launch_power_w == results[6.0].link.launch_power_w
    ratio = results[6.0].link.received_power_w / results[1.0].link.received_power_w
    assert ratio == pytest.approx(10 ** (-0.4 * 5.0 / 10), rel=1e-10)
    assert results[1.0].protocol is PowerProtocol.FIXED_LAUNCH


def test_matched_received_power_protocol_hits_the_target_whatever_the_loss():
    wave = quad_wave()
    target_dbm = -7.0
    received, launches = [], []
    for length, lump in ((1.0, 0.0), (6.0, 2.0)):
        profile = make_profile(
            length_km=known(length, "km"),
            attenuation_db_per_km=known(0.4, "dB/km", measurement_wavelength_nm=1550.0),
            pigtail_loss_db=known(lump, "dB"),
            dispersion_ps_per_nm_km=known(5.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        )
        res = transmit_profile(
            wave,
            64e9,
            profile,
            1550.0,
            np.random.default_rng(1),
            protocol=PowerProtocol.MATCHED_RECEIVED,
            received_power_dbm=target_dbm,
        )
        received.append(res.link.received_power_w)
        launches.append(res.link.launch_power_w)
        assert res.link.fiber["power_protocol"] == "matched-received-power"
    target_w = 1e-3 * 10 ** (target_dbm / 10)
    assert received == [pytest.approx(target_w, rel=1e-9)] * 2
    # the laser had to be turned up by exactly the extra loss
    assert launches[1] / launches[0] == pytest.approx(10 ** ((0.4 * 5.0 + 2.0) / 10), rel=1e-9)


def test_protocol_argument_errors():
    profile = make_profile()
    wave = quad_wave()
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="needs received_power_dbm"):
        transmit_profile(wave, 64e9, profile, 1550.0, rng, protocol="matched-received-power")
    with pytest.raises(ValueError, match="only used"):
        transmit_profile(wave, 64e9, profile, 1550.0, rng, received_power_dbm=-7.0)
    with pytest.raises(ValueError):
        transmit_profile(wave, 64e9, profile, 1550.0, rng, protocol="bogus")


def test_unsupported_effects_raise_in_the_link():
    wave = quad_wave()
    for effect in ("kerr", "intermodal_coupling", "gas_absorption", "amplifier_noise"):
        with pytest.raises(UnsupportedEffectError):
            transmit_profile(
                wave, 64e9, make_profile(), 1550.0, np.random.default_rng(0), effects=(effect,)
            )


def test_gamma_is_stored_but_changes_nothing():
    wave = quad_wave()
    without = make_profile()
    with_gamma = make_profile(gamma_per_w_km=known(0.007, "1/(W km)"))
    a = transmit_profile(wave, 64e9, without, 1550.0, np.random.default_rng(3))
    b = transmit_profile(wave, 64e9, with_gamma, 1550.0, np.random.default_rng(3))
    assert np.array_equal(a.link.current_a, b.link.current_a)
    assert b.resolved.gamma_per_w_km == 0.007


def test_profile_link_equals_the_validated_config_path_bit_for_bit():
    """The profile route adds no new arithmetic: it equals a hand-built LinkConfig exactly."""
    wave = quad_wave()
    profile = make_profile(
        length_km=known(5.0, "km"),
        attenuation_db_per_km=known(0.3, "dB/km", measurement_wavelength_nm=1550.0),
        pigtail_loss_db=known(1.0, "dB"),
        dispersion_ps_per_nm_km=known(7.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        dispersion_slope_ps_per_nm2_km=known(
            0.02, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
        ),
    )
    from opticps.optical_channel.link import transmit

    manual = LinkConfig(
        fiber_length_km=5.0,
        attenuation_db_per_km=0.3,
        dispersion_ps_per_nm_km=7.0,
        dispersion_slope_ps_per_nm2_km=0.02,
        wavelength_m=1550.0 * 1e-9,
        extra_attenuation_db=1.0,
    )
    ref = transmit(wave, 64e9, manual, np.random.default_rng(9))
    res = transmit_profile(wave, 64e9, profile, 1550.0, np.random.default_rng(9))
    assert np.array_equal(res.link.current_a, ref.current_a)
    assert res.link.received_power_w == ref.received_power_w


def test_table_dispersion_drives_the_propagation_and_range_is_enforced():
    from opticps.optical_channel.fiber import WavelengthTable

    table = WavelengthTable(
        "D(lambda)",
        (1500.0, 1600.0),
        (2.0, 4.0),
        "ps/(nm km)",
        ParameterProvenance(ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION, "unit test"),
    )
    profile = lossless(dispersion_table=table, dispersion_ps_per_nm_km=unknown("ps/(nm km)"))
    resolved = resolve_profile(profile, 1550.0)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(3.0)
    expected = math.sqrt(C / (2 * LAMBDA**2 * 3.0e-6 * 5e3)) / 1e9
    assert first_null_ghz(resolved) == pytest.approx(expected, abs=0.05)
    with pytest.raises(Exception, match="no extrapolation"):
        propagate_array(random_field(), 64e9, resolve_profile(profile, 1640.0))


def test_g652d_path_is_unchanged_by_the_profile_code():
    """dispersive_field on a G.652.D-style config equals the v1.0 formula bit for bit."""
    field = random_field()
    config = LinkConfig(fiber_length_km=20.0, extra_attenuation_db=10.0)
    d = config.effective_dispersion_ps_per_nm_km * 1e-6
    beta2 = -d * config.effective_wavelength_m**2 / (2 * np.pi * C)
    omega = 2 * np.pi * np.fft.fftfreq(field.size, d=1 / 64e9)
    ref = np.fft.ifft(np.fft.fft(field) * np.exp(0.5j * beta2 * 20e3 * omega**2))
    assert np.array_equal(dispersive_field(field, 64e9, config), ref)


# --- Gate N1 fix round ---------------------------------------------------------------------------


def sloped(*, wavelength=1550.0, reference=1550.0, **over):
    """D 10 at `wavelength`, valid 1500 to 1600 nm, S 0.06 ps/(nm^2 km): own literal numbers."""
    return make_profile(
        reference_wavelength_nm=known(reference, "nm"),
        dispersion_ps_per_nm_km=known(
            10.0,
            "ps/(nm km)",
            measurement_wavelength_nm=wavelength,
            validity_range_nm=(1500.0, 1600.0),
        ),
        dispersion_slope_ps_per_nm2_km=known(
            0.06,
            "ps/(nm^2 km)",
            measurement_wavelength_nm=wavelength,
            validity_range_nm=(1500.0, 1600.0),
        ),  # fmt: skip
        **over,
    )


@pytest.mark.parametrize("reference", [1500.0, 1550.0, 1560.0, 1310.0])
def test_d_is_anchored_where_it_is_stated_whatever_the_carrier_reference(reference):
    profile = sloped(reference=reference)  # D stated at 1550 nm
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == 10.0
    resolved = resolve_profile(profile, 1590.0)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(12.4, abs=1e-12)  # 10 + 0.06 * 40
    assert resolved.dispersion_anchor_nm == 1550.0
    assert "dispersion_ps_per_nm_km" not in resolved.extrapolated  # inside the stated range
    assert resolve_profile(profile, 1510.0).dispersion_ps_per_nm_km == pytest.approx(7.6)


def test_d_stated_at_1550_only_reads_10_at_1550_for_reference_1560():
    profile = make_profile(
        reference_wavelength_nm=known(1560.0, "nm"),
        dispersion_ps_per_nm_km=known(10.0, "ps/(nm km)", measurement_wavelength_nm=1550.0),
        dispersion_slope_ps_per_nm2_km=known(
            0.06, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
        ),
    )
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == 10.0


def test_d_stated_at_another_wavelength_moves_the_anchor_with_it():
    # D 10 stated at 1530: D(1590) = 10 + 0.06 * 60 = 13.6, whatever the reference says
    profile = sloped(wavelength=1530.0, reference=1550.0)
    assert resolve_profile(profile, 1530.0).dispersion_ps_per_nm_km == 10.0
    assert resolve_profile(profile, 1590.0).dispersion_ps_per_nm_km == pytest.approx(13.6)


def test_slope_path_under_requested_extrapolation_is_not_clamped_to_the_range_edge():
    resolved = resolve_profile(sloped(), 1620.0, allow_extrapolation=True)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(14.2, abs=1e-12)  # 10 + 0.06 * 70
    assert "dispersion_ps_per_nm_km" in resolved.extrapolated  # truthful: outside the range
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(sloped(), 1620.0)


def test_a_range_only_d_with_a_slope_raises_because_it_has_no_single_wavelength():
    profile = make_profile(
        dispersion_ps_per_nm_km=ProfileValue(
            10.0,
            "ps/(nm km)",
            ParameterProvenance(
                ProvenanceCategory.USER_ASSUMED, "unit test", validity_range_nm=(1400.0, 1500.0)
            ),
        ),
        dispersion_slope_ps_per_nm2_km=known(
            0.06, "ps/(nm^2 km)", measurement_wavelength_nm=1450.0
        ),
        reference_wavelength_nm=known(1550.0, "nm"),
    )
    with pytest.raises(OutOfValidityRangeError, match="no single stated wavelength"):
        resolve_profile(profile, 1450.0)
    # without a slope the same D is a plain value over its stated range, held
    held = replace(profile, dispersion_slope_ps_per_nm2_km=unknown("ps/(nm^2 km)"))
    assert resolve_profile(held, 1450.0).dispersion_ps_per_nm_km == 10.0
    assert resolve_profile(held, 1500.0).dispersion_ps_per_nm_km == 10.0


def test_a_scenario_slope_places_a_known_d_exactly_like_a_known_slope():
    profile = sloped(wavelength=1550.0)
    profile = replace(profile, dispersion_slope_ps_per_nm2_km=unknown("ps/(nm^2 km)"))
    scenario = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.06})
    resolved = resolve_profile(profile, 1590.0, scenario=scenario)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(12.4, abs=1e-12)
    assert resolved.dispersion_slope_ps_per_nm2_km == 0.06
    assert resolved.sources["dispersion_slope_ps_per_nm2_km"] == "scenario: slope guess"
    assert resolved.to_record()["not_a_benchmark_result"] is True
    # no slope at all: D is held and the record says so
    held = resolve_profile(profile, 1590.0)
    assert held.dispersion_ps_per_nm_km == 10.0
    assert held.to_record()["slope_omitted_second_order_only"] is True


def test_wang_at_1560_extrapolated_with_a_scenario_slope_is_the_arithmetic_value():
    wang = load_fiber_config("configs/fibers/NANF-WANG-2025-2P032KM.yaml")
    scenario = SensitivityScenario(
        "wang slope and losses",
        {
            "attenuation_db_per_km": 0.0,
            "connector_loss_db": 0.0,
            "pigtail_loss_db": 0.0,
            "splice_loss_db": 0.0,
            "dispersion_slope_ps_per_nm2_km": 0.06,
        },
    )
    at_1560 = resolve_profile(wang, 1560.0, scenario=scenario, allow_extrapolation=True)
    assert at_1560.dispersion_ps_per_nm_km == pytest.approx(5.02, abs=1e-12)  # 4.42 + 0.06 * 10
    assert "dispersion_ps_per_nm_km" in at_1560.extrapolated
    at_1550 = resolve_profile(wang, 1550.0, scenario=scenario)
    assert at_1550.dispersion_ps_per_nm_km == 4.42
    assert "dispersion_ps_per_nm_km" not in at_1550.extrapolated
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(wang, 1560.0, scenario=scenario)


def test_a_dispersion_without_a_stated_wavelength_raises_and_the_reference_is_not_a_stand_in():
    d = ProfileValue(
        10.0, "ps/(nm km)", ParameterProvenance(ProvenanceCategory.USER_ASSUMED, "unit test")
    )
    for reference in (1450.0, 1550.0):
        profile = make_profile(
            dispersion_ps_per_nm_km=d, reference_wavelength_nm=known(reference, "nm")
        )
        for wavelength in (1450.0, 1550.0):
            with pytest.raises(OutOfValidityRangeError, match="states no wavelength"):
                resolve_profile(profile, wavelength)


def test_the_reference_wavelength_is_the_carrier_only_so_an_unknown_one_changes_nothing():
    profile = sloped(reference=1550.0)
    unknown_ref = replace(profile, reference_wavelength_nm=unknown("nm"))
    assert resolve_profile(unknown_ref, 1590.0).dispersion_ps_per_nm_km == pytest.approx(12.4)


@pytest.mark.parametrize(
    ("name", "unit", "value"),
    [
        ("attenuation_db_per_km", "dB/km", 0.5),
        ("dispersion_slope_ps_per_nm2_km", "ps/(nm^2 km)", 0.06),
        ("dispersion_ps_per_nm_km", "ps/(nm km)", 10.0),
    ],
)
def test_a_wavelength_dependent_value_with_no_stated_wavelength_is_refused(name, unit, value):
    bare = ProfileValue(
        value, unit, ParameterProvenance(ProvenanceCategory.USER_ASSUMED, "unit test")
    )
    wide_d = known(
        10.0, "ps/(nm km)", measurement_wavelength_nm=1550.0, validity_range_nm=(1400.0, 1700.0)
    )
    profile = make_profile(**{"dispersion_ps_per_nm_km": wide_d, name: bare})
    for wavelength in (1450.0, 1550.0):
        with pytest.raises(OutOfValidityRangeError, match=f"{name} states no wavelength"):
            resolve_profile(profile, wavelength)


def test_shipped_profiles_resolve_without_filler_where_they_state_a_wavelength():
    hong = load_fiber_config("configs/fibers/NANF-HONG-2021-4P76KM.yaml")
    scenario = SensitivityScenario(
        "losses", {"attenuation_db_per_km": 0.0, "connector_loss_db": 0.0}
    )
    resolved = resolve_profile(hong, 1550.0, scenario=scenario)
    assert resolved.dispersion_ps_per_nm_km == 2.04
    assert resolved.dispersion_anchor_nm == 1550.0


def test_the_validity_check_applies_to_every_parameter_used():
    for name, unit, value in (
        ("attenuation_db_per_km", "dB/km", 0.4),
        ("connector_loss_db", "dB", 0.1),
        ("pigtail_loss_db", "dB", 0.1),
        ("splice_loss_db", "dB", 0.1),
        ("group_index", "1", 1.003),
        ("dispersion_slope_ps_per_nm2_km", "ps/(nm^2 km)", 0.06),
    ):
        wide_d = known(
            10.0, "ps/(nm km)", measurement_wavelength_nm=1550.0, validity_range_nm=(1400.0, 1700.0)
        )
        profile = make_profile(
            dispersion_ps_per_nm_km=wide_d,
            **{name: known(value, unit, validity_range_nm=(1540.0, 1560.0))},
        )
        assert resolve_profile(profile, 1550.0)
        with pytest.raises(OutOfValidityRangeError, match=name):
            resolve_profile(profile, 1590.0)
        assert name in resolve_profile(profile, 1590.0, allow_extrapolation=True).extrapolated


def test_scenario_values_have_the_same_physical_minima_as_known_values():
    for name, bad in (
        ("connector_loss_db", -5.0),
        ("pigtail_loss_db", -0.1),
        ("splice_loss_db", -1e-9),
        ("attenuation_db_per_km", -0.2),
        ("length_km", 0.0),
        ("group_index", 0.2),
        ("group_index", 0.999),
        ("gamma_per_w_km", -1.0),
    ):
        with pytest.raises(FiberProfileError, match="physical range"):
            SensitivityScenario("s", {name: bad})
    ok = SensitivityScenario("s", {"connector_loss_db": 0.0, "group_index": 1.0})
    assert ok.values["group_index"] == 1.0


def _scenario_profile():
    return make_profile(connector_loss_db=unknown("dB"))


def test_the_scenario_label_survives_the_public_link_route():
    scenario = SensitivityScenario("connector guess 0.5 dB", {"connector_loss_db": 0.5})
    resolved = resolve_profile(_scenario_profile(), 1550.0, scenario=scenario)
    config = profile_link_config(resolved)
    assert config.sensitivity_scenario == "connector guess 0.5 dB"
    result = transmit(quad_wave(), 64e9, config, np.random.default_rng(0))
    assert result.fiber["sensitivity_scenario"] == "connector guess 0.5 dB"
    assert result.fiber["not_a_benchmark_result"] is True
    field = propagate_profile_field(random_field(256), 64e9, resolved)
    assert field.sensitivity_scenario == "connector guess 0.5 dB"
    assert field.record["not_a_benchmark_result"] is True
    assert field.field.shape == (256,)
    res = transmit_profile(
        quad_wave(), 64e9, _scenario_profile(), 1550.0, np.random.default_rng(0), scenario=scenario
    )
    assert res.link.fiber["not_a_benchmark_result"] is True
    assert res.link.fiber["sensitivity_scenario"] == "connector guess 0.5 dB"


def test_no_scenario_means_no_label_and_no_benchmark_flag():
    resolved = resolve_profile(make_profile(), 1550.0)
    assert resolved.to_record()["sensitivity_scenario"] is None
    assert "not_a_benchmark_result" not in resolved.to_record()
    result = transmit(quad_wave(), 64e9, profile_link_config(resolved), np.random.default_rng(0))
    assert "not_a_benchmark_result" not in result.fiber
    assert "sensitivity_scenario" not in result.fiber


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 60.0, 10.001])
def test_matched_power_refuses_a_non_finite_or_implausible_target(bad):
    wave, rng = quad_wave(), np.random.default_rng(0)
    for profile, scenario in (
        (make_profile(), None),
        (
            _scenario_profile(),
            SensitivityScenario("s", {"connector_loss_db": 0.5}),
        ),
    ):
        with pytest.raises(ValueError, match="received_power_dbm"):
            transmit_profile(
                wave,
                64e9,
                profile,
                1550.0,
                rng,
                protocol=PowerProtocol.MATCHED_RECEIVED,
                received_power_dbm=bad,
                scenario=scenario,
            )


def test_matched_power_accepts_the_stated_upper_bound_and_the_owner_receiver_range():
    from opticps.optical_channel.link import (
        MAX_MATCHED_RECEIVED_POWER_DBM,
        check_matched_received_power_dbm,
    )

    assert MAX_MATCHED_RECEIVED_POWER_DBM == 10.0
    for ok in (-30.0, -5.0, 0.0, 10.0):
        check_matched_received_power_dbm(ok)


def test_matched_power_follows_the_transmitter_filter_in_the_launch_mean():
    # A narrow transmitter filter changes the mean modulator output. The matched protocol must use
    # that mean; dropping the filter from launch_mean_per_watt would miss the target.
    wave = quad_wave()
    fs = 64e9
    base = LinkConfig(transmitter_bandwidth_hz=4e9, extra_attenuation_db=1.5)
    drive = wave * base.drive_vpp / 2
    mean_unfiltered = float(mzm_intensity(drive, base).mean())
    mean_filtered = float(mzm_intensity(lowpass(drive, fs, 4e9), base).mean())
    # the filter moves the mean by 4e-4 here, 1e5 times the 1e-9 tolerance below
    assert abs(mean_filtered / mean_unfiltered - 1) > 1e-4
    res = transmit_profile(
        wave,
        fs,
        make_profile(length_km=known(2.0, "km")),
        1550.0,
        np.random.default_rng(1),
        base=base,
        protocol=PowerProtocol.MATCHED_RECEIVED,
        received_power_dbm=-7.0,
    )
    target_w = 1e-3 * 10 ** (-7.0 / 10)
    assert res.link.received_power_w == pytest.approx(target_w, rel=1e-9)
    total_db = 0.5 * 2.0 + 1.5
    expected_laser = target_w / (mean_filtered * 10 ** (-total_db / 10))
    assert res.config.laser_power_w == pytest.approx(expected_laser, rel=1e-9)


# --- Gate N1 fix round 2: table conflicts, route checks, record on the public route ---------------


def _d_table(values=(1.0, 3.0), knots=(1500.0, 1600.0), category="measured"):
    return WavelengthTable(
        "D(lambda)",
        knots,
        values,
        "ps/(nm km)",
        ParameterProvenance(ProvenanceCategory(category), "Lab notebook 7, 2024-03-02"),
    )


def _declaration(winner):
    return PrecedenceDeclaration(
        winner,
        ParameterProvenance(
            ProvenanceCategory.USER_ASSUMED, "Owner decision 2026-10-31 (unit test)"
        ),
    )


def test_a_table_that_conflicts_with_a_known_scalar_raises_without_a_declared_winner():
    # table D 2.0 at 1550 (1 + 0.01 * 50), scalar D 10 stated at 1550
    profile = make_profile(dispersion_table=_d_table())
    with pytest.raises(FiberProfileError, match="declares no winner"):
        resolve_profile(profile, 1550.0)
    assert not profile.precedence


def test_a_table_that_agrees_with_the_scalar_is_used_without_a_declaration():
    profile = make_profile(dispersion_table=_d_table(values=(9.0, 11.0)))  # 10.0 at 1550
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == pytest.approx(10.0)


@pytest.mark.parametrize(("winner", "expected"), [("table", 2.0), ("scalar", 10.0)])
def test_a_declared_winner_is_used_and_recorded_with_provenance(winner, expected):
    profile = make_profile(
        dispersion_table=_d_table(),
        precedence={"dispersion_ps_per_nm_km": _declaration(winner)},
    )
    resolved = resolve_profile(profile, 1550.0)
    assert resolved.dispersion_ps_per_nm_km == pytest.approx(expected)
    source = resolved.sources["dispersion_ps_per_nm_km"]
    assert "declared over" in source
    assert "Owner decision 2026-10-31" in source
    assert "user-assumed" in source


def test_a_loss_table_conflicting_with_a_known_loss_raises_unless_declared():
    table = WavelengthTable(
        "loss",
        (1500.0, 1600.0),
        (0.1, 0.3),
        "dB/km",
        ParameterProvenance(ProvenanceCategory.MEASURED, "Lab notebook 7, 2024-03-02"),
    )
    profile = make_profile(loss_table=table)  # table 0.2 at 1550, scalar 0.5
    with pytest.raises(FiberProfileError, match="attenuation_db_per_km disagree"):
        resolve_profile(profile, 1550.0)
    declared = replace(profile, precedence={"attenuation_db_per_km": _declaration("table")})
    assert resolve_profile(declared, 1550.0).attenuation_db_per_km == pytest.approx(0.2)


def test_a_slope_conflicting_with_a_d_table_is_refused_whatever_the_source():
    table = _d_table(values=(9.0, 11.0))  # local slope 0.02 ps/(nm^2 km), D 10 at 1550
    known_s = make_profile(
        dispersion_table=table,
        dispersion_slope_ps_per_nm2_km=known(
            0.06, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
        ),
        dispersion_ps_per_nm_km=unknown("ps/(nm km)"),
    )
    with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
        resolve_profile(known_s, 1550.0)
    scenario_s = replace(known_s, dispersion_slope_ps_per_nm2_km=unknown("ps/(nm^2 km)"))
    scenario = SensitivityScenario("slope guess", {"dispersion_slope_ps_per_nm2_km": 0.06})
    with pytest.raises(FiberProfileError, match="a scenario cannot override a table"):
        resolve_profile(scenario_s, 1550.0, scenario=scenario)
    # a table with slope 0 and a known S of 0.06: refused, the beta3 would be 16 times too big
    flat = replace(known_s, dispersion_table=_d_table(values=(10.0, 10.0)))
    with pytest.raises(FiberProfileError, match="conflicts with the local slope"):
        resolve_profile(flat, 1550.0)
    close = replace(
        known_s,
        dispersion_slope_ps_per_nm2_km=known(
            0.0205, "ps/(nm^2 km)", measurement_wavelength_nm=1550.0
        ),
    )
    assert resolve_profile(close, 1550.0).dispersion_slope_ps_per_nm2_km == 0.0205
    declared = replace(
        known_s, precedence={"dispersion_slope_ps_per_nm2_km": _declaration("table")}
    )
    assert resolve_profile(declared, 1550.0).dispersion_slope_ps_per_nm2_km == pytest.approx(0.02)


def test_a_negative_d_table_is_accepted_and_interpolated():
    table = _d_table(values=(-4.0, 6.0))  # D passes through zero at 1550
    profile = make_profile(dispersion_table=table, dispersion_ps_per_nm_km=unknown("ps/(nm km)"))
    assert resolve_profile(profile, 1500.0).dispersion_ps_per_nm_km == pytest.approx(-4.0)
    assert resolve_profile(profile, 1550.0).dispersion_ps_per_nm_km == pytest.approx(1.0)


def test_precedence_is_loaded_from_yaml_and_refused_for_other_fields(tmp_path):
    text = open("configs/fibers/NANF-HONG-2021-4P76KM.yaml").read()
    block = (
        "precedence:\n  dispersion_ps_per_nm_km:\n    winner: table\n    provenance:\n"
        "      category: user-assumed\n      citation: Owner decision, unit test\n"
    )
    path = tmp_path / "p.yaml"
    path.write_text(text + block)
    assert load_fiber_config(path).precedence["dispersion_ps_per_nm_km"].winner == "table"
    path.write_text(text + block.replace("dispersion_ps_per_nm_km", "length_km"))
    with pytest.raises(FiberProfileError, match="table fields only"):
        load_fiber_config(path)
    path.write_text(text + block.replace("winner: table", "winner: both"))
    with pytest.raises(FiberProfileError, match="'table' or 'scalar'"):
        load_fiber_config(path)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -5.0, -1e-9])
def test_the_profile_route_refuses_a_bad_base_extra_attenuation(bad):
    resolved = resolve_profile(make_profile(), 1550.0)
    base = LinkConfig(extra_attenuation_db=bad)
    with pytest.raises(FiberProfileError, match="extra_attenuation_db"):
        profile_link_config(resolved, base)
    with pytest.raises(FiberProfileError, match="extra_attenuation_db"):
        transmit_profile(
            quad_wave(), 64e9, make_profile(), 1550.0, np.random.default_rng(0), base=base
        )
    with pytest.raises(FiberProfileError, match="extra_attenuation_db"):
        transmit_profile(
            quad_wave(), 64e9, make_profile(), 1550.0, np.random.default_rng(0), base=base,
            protocol=PowerProtocol.MATCHED_RECEIVED, received_power_dbm=-5.0,
        )  # fmt: skip


def test_the_g652_route_is_not_touched_by_the_profile_route_checks():
    config = LinkConfig(fiber_length_km=5.0, extra_attenuation_db=-5.0)  # validated path as before
    assert config.extra_attenuation_db == -5.0
    assert "profile_id" not in transmit(quad_wave(), 64e9, config, np.random.default_rng(0)).fiber
    assert profile_link_config(resolve_profile(make_profile(), 1550.0), LinkConfig()).profile_id


def test_the_laser_power_for_matched_received_power_is_bounded():
    from opticps.optical_channel.link import MAX_MATCHED_LASER_POWER_W

    assert MAX_MATCHED_LASER_POWER_W == 1.0
    wave, rng = quad_wave(), np.random.default_rng(0)
    absurd = make_profile(
        attenuation_db_per_km=known(100.0, "dB/km", measurement_wavelength_nm=1550.0)
    )  # 500 dB over 5 km
    with pytest.raises(ValueError, match="sanity limit"):
        transmit_profile(
            wave, 64e9, absurd, 1550.0, rng,
            protocol=PowerProtocol.MATCHED_RECEIVED, received_power_dbm=-5.0,
        )  # fmt: skip
    ok = transmit_profile(
        wave, 64e9, make_profile(), 1550.0, rng,
        protocol=PowerProtocol.MATCHED_RECEIVED, received_power_dbm=-5.0,
    )  # fmt: skip
    assert ok.config.laser_power_w < MAX_MATCHED_LASER_POWER_W


@pytest.mark.parametrize("protocol", ["matched-received-power", PowerProtocol.MATCHED_RECEIVED])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 10.5])
def test_the_received_power_bound_holds_for_a_string_protocol_too(protocol, bad):
    with pytest.raises(ValueError, match="received_power_dbm"):
        transmit_profile(
            quad_wave(), 64e9, make_profile(), 1550.0, np.random.default_rng(0),
            protocol=protocol, received_power_dbm=bad,
        )  # fmt: skip


def test_transmit_through_profile_link_config_keeps_the_extrapolation_and_sources():
    profile = sloped()
    resolved = resolve_profile(profile, 1620.0, allow_extrapolation=True)  # D 14.2, extrapolated
    result = transmit(quad_wave(), 64e9, profile_link_config(resolved), np.random.default_rng(0))
    assert result.fiber["profile_id"] == "TEST-PROFILE"
    assert result.fiber["extrapolated"] == list(resolved.extrapolated)
    assert "dispersion_ps_per_nm_km" in result.fiber["extrapolated"]
    assert result.fiber["sources"]["dispersion_ps_per_nm_km"] == "user-assumed"
    assert result.fiber["not_a_benchmark_result"] is True  # extrapolated, no scenario named
    inside = resolve_profile(profile, 1590.0)
    plain = transmit(quad_wave(), 64e9, profile_link_config(inside), np.random.default_rng(0))
    assert plain.fiber["profile_id"] == "TEST-PROFILE"
    assert plain.fiber["extrapolated"] == []
    assert "not_a_benchmark_result" not in plain.fiber


def test_not_a_benchmark_result_is_set_for_any_filled_or_extrapolated_value():
    filled = resolve_profile(
        make_profile(connector_loss_db=unknown("dB")),
        1550.0,
        scenario=SensitivityScenario("c", {"connector_loss_db": 0.5}),
    )
    assert filled.to_record()["not_a_benchmark_result"] is True
    extrapolated = resolve_profile(sloped(), 1620.0, allow_extrapolation=True)
    assert extrapolated.to_record()["not_a_benchmark_result"] is True
    assert "not_a_benchmark_result" not in resolve_profile(sloped(), 1590.0).to_record()
    res = transmit_profile(
        quad_wave(), 64e9, sloped(), 1620.0, np.random.default_rng(0), allow_extrapolation=True
    )
    assert res.link.fiber["not_a_benchmark_result"] is True


def test_a_label_on_the_base_config_is_not_silently_replaced_and_a_blank_one_is_refused():
    plain = resolve_profile(make_profile(), 1550.0)
    kept = profile_link_config(plain, LinkConfig(sensitivity_scenario="my own label"))
    assert kept.sensitivity_scenario == "my own label"
    scenario = SensitivityScenario("connector guess", {"connector_loss_db": 0.5})
    filled = resolve_profile(
        make_profile(connector_loss_db=unknown("dB")), 1550.0, scenario=scenario
    )
    with pytest.raises(FiberProfileError, match="never silently replaced"):
        profile_link_config(filled, LinkConfig(sensitivity_scenario="my own label"))
    same = profile_link_config(filled, LinkConfig(sensitivity_scenario="connector guess"))
    assert same.sensitivity_scenario == "connector guess"
    for blank in ("", "   "):
        with pytest.raises(FiberProfileError, match="blank"):
            profile_link_config(plain, LinkConfig(sensitivity_scenario=blank))
