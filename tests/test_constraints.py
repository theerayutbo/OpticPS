"""Independent checks of the distribution-search constraints.

Closed forms are derived here from the Mach-Zehnder transfer function written out in the
test (quadrature: T(v) = L (1 + V sin(pi v / V_pi)) / 2), not read from constraints.py. The
statuses asserted are consequences of that algebra, not of the implementation's wording.
"""

import math
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.modulation.pam import pam_levels
from opticps.optical_channel.link import LinkConfig
from opticps.optimization.adaptive import (
    ChannelEstimate,
    evaluate_menu,
    fixed_menu,
    optimise_symmetric,
)
from opticps.optimization.constraints import (
    EqualRealizedUserRate,
    Feasibility,
    FeasibilityStatus,
    FixedAverageOpticalPower,
    FixedOMA,
    FixedPeak,
    FrameAccounting,
    drive_voltages,
    mean_power_w,
    oma_w,
)
from opticps.optimization.rates import noise_sigma_from_psnr_db
from opticps.shaping.distributions import mb_for_entropy

CONFIG = LinkConfig()  # quadrature MZM, 10 mW, V_pi 4 V, V_pp 2 V, ER 30 dB, IL 4 dB
LOSS = 10 ** (-CONFIG.insertion_loss_db / 10)
VIS = 1 - 2 / (1 + 10 ** (CONFIG.extinction_db / 10))


def symmetric_pmfs(order: int) -> list[np.ndarray]:
    pmfs = [np.full(order, 1.0 / order)]
    top = math.log2(order)
    for sign in (1, -1):
        for deficit in (0.12, 0.28, 0.6):
            pmfs.append(mb_for_entropy(top - deficit, order, sign))
    zero_outer = np.zeros(order)
    zero_outer[1:-1] = 1.0 / (order - 2)
    pmfs.append(zero_outer)
    return pmfs


def transmission(v: np.ndarray, bias: float) -> np.ndarray:
    """Written out from the MZM transfer function, independent of link.mzm_intensity."""
    return LOSS * 0.5 * (1 - VIS * np.cos(np.pi * (v / CONFIG.v_pi + bias)))


def test_status_names_are_the_three_documented_values():
    assert {s.value for s in FeasibilityStatus} == {"FEASIBLE", "INACTIVE", "INFEASIBLE"}
    f = Feasibility(FeasibilityStatus.FEASIBLE, "x")
    assert f.adjustments == {}
    with pytest.raises(FrozenInstanceError):
        f.reason = "y"  # type: ignore[misc]


# --------------------------------------------------------------------- average optical power


@pytest.mark.parametrize("order", [4, 8, 16])
@pytest.mark.parametrize("predistort", [False, True])
def test_mean_power_is_independent_of_a_symmetric_pmf_at_quadrature(order, predistort):
    config = replace(CONFIG, predistort=predistort)
    expected = config.laser_power_w * LOSS / 2  # E[sin] = 0 for an odd drive map
    for p in symmetric_pmfs(order):
        assert mean_power_w(config, p) == pytest.approx(expected, rel=1e-12)
        result = FixedAverageOpticalPower().check(config, p)
        assert result.status is FeasibilityStatus.INACTIVE
        assert "independent of the PMF" in result.reason and result.adjustments == {}


def test_mean_power_formula_matches_the_independent_transfer_function():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    for bias in (0.5, 0.45, 0.6):
        config = replace(CONFIG, bias_fraction_of_vpi=bias)
        v = pam_levels(4) / 3 * config.drive_vpp / 2
        expected = config.laser_power_w * float(p @ transmission(v, bias))
        assert mean_power_w(config, p) == pytest.approx(expected, rel=1e-12)


def test_off_quadrature_or_asymmetric_pmf_makes_average_power_active_with_a_reported_laser_change():
    sym = np.array([0.15, 0.35, 0.35, 0.15])
    asym = np.array([0.4, 0.3, 0.2, 0.1])
    off = replace(CONFIG, bias_fraction_of_vpi=0.45)
    # the mean really depends on the PMF in both cases
    assert abs(mean_power_w(off, sym) - mean_power_w(off, np.full(4, 0.25))) > 1e-6
    assert abs(mean_power_w(CONFIG, asym) - mean_power_w(CONFIG, np.full(4, 0.25))) > 1e-4
    for config, p, cause in ((off, sym, "off quadrature"), (CONFIG, asym, "asymmetric")):
        target = mean_power_w(config, np.full(4, 0.25))
        factor = target / mean_power_w(config, p)
        undeclared = FixedAverageOpticalPower().check(config, p)
        assert undeclared.status is FeasibilityStatus.INFEASIBLE
        assert undeclared.adjustments["laser_power_w"] == pytest.approx(
            config.laser_power_w * factor, rel=1e-12
        )
        assert "not declared" in undeclared.reason and cause in undeclared.reason
        declared = FixedAverageOpticalPower(allow_laser_adjustment=True).check(config, p)
        assert declared.status is FeasibilityStatus.FEASIBLE
        assert declared.adjustments["laser_power_w"] == pytest.approx(
            config.laser_power_w * factor, rel=1e-12
        )
        # applying the reported change, and only then, restores the target
        fixed = replace(config, laser_power_w=declared.adjustments["laser_power_w"])
        assert mean_power_w(fixed, p) == pytest.approx(target, rel=1e-12)
        capped = FixedAverageOpticalPower(
            allow_laser_adjustment=True, max_laser_power_w=config.laser_power_w * factor * 0.99
        ).check(config, p)
        assert capped.status is FeasibilityStatus.INFEASIBLE and "limit" in capped.reason


def test_the_check_never_changes_the_configuration():
    config = replace(CONFIG, bias_fraction_of_vpi=0.45)
    before = (config.laser_power_w, config.drive_vpp)
    FixedAverageOpticalPower(allow_laser_adjustment=True).check(config, [0.4, 0.3, 0.2, 0.1])
    FixedOMA(allow_drive_rescale=True).check(config, [0.0, 0.5, 0.5, 0.0])
    assert (config.laser_power_w, config.drive_vpp) == before


# --------------------------------------------------------------------- peak and OMA


@pytest.mark.parametrize("order", [4, 8, 16])
def test_oma_equals_the_fixed_peak_value_when_the_extremes_are_used(order):
    full = np.full(order, 1.0 / order)
    peak_closed_form = (
        CONFIG.laser_power_w * LOSS * VIS * math.sin(math.pi * (CONFIG.drive_vpp / 2) / CONFIG.v_pi)
    )  # T(+v) - T(-v) = L V sin(pi v / V_pi) at quadrature
    for p in symmetric_pmfs(order)[:-1]:  # every one with mass on both outer levels
        assert oma_w(CONFIG, p) == pytest.approx(peak_closed_form, rel=1e-12)
        assert oma_w(CONFIG, p) == pytest.approx(oma_w(CONFIG, full), rel=1e-14)
        assert FixedPeak().check(CONFIG, p).status is FeasibilityStatus.FEASIBLE
        result = FixedOMA().check(CONFIG, p)
        assert result.status is FeasibilityStatus.INACTIVE and "fixed-peak" in result.reason


@pytest.mark.parametrize(("order", "factor"), [(4, 3.0), (8, 7 / 5)])
def test_oma_differs_from_fixed_peak_when_the_outer_levels_have_zero_mass(order, factor):
    p = symmetric_pmfs(order)[-1]  # outer pair unused
    inner_amplitude = (order - 3) / (order - 1)
    closed_form = (
        CONFIG.laser_power_w
        * LOSS
        * VIS
        * math.sin(math.pi * inner_amplitude * (CONFIG.drive_vpp / 2) / CONFIG.v_pi)
    )
    assert oma_w(CONFIG, p) == pytest.approx(closed_form, rel=1e-12)
    assert oma_w(CONFIG, p) < oma_w(CONFIG, np.full(order, 1.0 / order))
    peak = FixedPeak().check(CONFIG, p)
    assert peak.status is FeasibilityStatus.FEASIBLE and "no mass" in peak.reason
    assert peak.adjustments == {}  # fixed peak never rescales
    undeclared = FixedOMA().check(CONFIG, p)
    assert undeclared.status is FeasibilityStatus.INFEASIBLE and "not declared" in undeclared.reason
    # the swing that restores the outer-level OMA is the ratio of the amplitudes: derived, not read
    assert undeclared.adjustments["drive_vpp_factor"] == pytest.approx(factor, rel=1e-9)
    declared = FixedOMA(allow_drive_rescale=True).check(CONFIG, p)
    assert declared.status is FeasibilityStatus.FEASIBLE
    restored = replace(CONFIG, drive_vpp=declared.adjustments["drive_vpp"])
    assert oma_w(restored, p) == pytest.approx(oma_w(CONFIG, np.full(order, 1.0 / order)), rel=1e-9)


def test_fixed_oma_unreachable_target_is_infeasible_even_when_rescale_is_declared():
    p = np.array([0.0, 0.5, 0.5, 0.0])
    too_big = 10 * oma_w(CONFIG, np.full(4, 0.25))
    result = FixedOMA(target_oma_w=too_big, allow_drive_rescale=True).check(CONFIG, p)
    assert result.status is FeasibilityStatus.INFEASIBLE and "V_pi" in result.reason
    assert result.adjustments == {} and "below the fixed" in result.reason  # direction is true
    # the largest OMA reachable is at V_pp = 2 V_pi: inner drive (1/3) V_pi, sin(pi / 3), quoted
    ceiling = CONFIG.laser_power_w * LOSS * VIS * math.sin(math.pi / 3)
    assert f"{ceiling:.4g}" in result.reason


def test_fixed_oma_target_below_the_current_oma_reduces_the_swing_on_the_rising_branch():
    """Target 0.5 x OMA: OMA = P L V sin(pi V_pp / (2 V_pi)) a_max, so V_pp = (8 / pi) asin(1/2 x
    sin(pi / 4)) = 0.9202 V, not the fold-over swing 7.08 V that an upward-only search finds."""
    p = np.full(4, 0.25)
    target = 0.5 * oma_w(CONFIG, p)
    expected = (2 * CONFIG.v_pi / math.pi) * math.asin(0.5 * math.sin(math.pi / 4))
    assert expected == pytest.approx(0.9202, abs=5e-5)
    undeclared = FixedOMA(target_oma_w=target).check(CONFIG, p)
    assert undeclared.status is FeasibilityStatus.INFEASIBLE
    assert undeclared.adjustments["drive_vpp"] == pytest.approx(expected, rel=1e-9)
    assert "above the fixed" in undeclared.reason and "reduced" in undeclared.reason
    assert "outer levels" not in undeclared.reason  # the old, false cause
    declared = FixedOMA(target_oma_w=target, allow_drive_rescale=True).check(CONFIG, p)
    assert declared.status is FeasibilityStatus.FEASIBLE
    assert declared.adjustments["drive_vpp"] == pytest.approx(expected, rel=1e-9)
    assert declared.adjustments["drive_vpp_factor"] < 1.0 and "reduced" in declared.reason
    # applying the reported swing, and only then, reaches the target
    assert oma_w(replace(CONFIG, drive_vpp=declared.adjustments["drive_vpp"]), p) == pytest.approx(
        target, rel=1e-9
    )
    # the fold-over swing is a second solution of the same equation, and is not the one reported
    fold = 2 * CONFIG.v_pi - expected  # sin(pi V_pp / 8) is symmetric about V_pp = V_pi = 4 V
    assert fold == pytest.approx(7.0798, abs=5e-4)
    assert oma_w(replace(CONFIG, drive_vpp=fold), p) == pytest.approx(target, rel=1e-9)
    assert declared.adjustments["drive_vpp"] < CONFIG.drive_vpp < fold
    # a target above the current OMA still increases the swing, from the same rising branch
    up = FixedOMA(target_oma_w=1.3 * oma_w(CONFIG, p), allow_drive_rescale=True).check(CONFIG, p)
    assert up.status is FeasibilityStatus.FEASIBLE and "increased" in up.reason
    assert up.adjustments["drive_vpp"] > CONFIG.drive_vpp
    assert oma_w(replace(CONFIG, drive_vpp=up.adjustments["drive_vpp"]), p) == pytest.approx(
        1.3 * oma_w(CONFIG, p), rel=1e-9
    )
    # a target below the current OMA is always reachable (OMA is 0 at no swing), so the
    # unreachable case is the one above the ceiling, covered in the test before this one


def test_fixed_oma_inactive_reason_is_true_when_the_outer_pair_is_unused():
    """The target equals the OMA of the levels in use: INACTIVE, and the text must not say that
    the extreme levels are in use (they carry no mass here)."""
    p = np.array([0.0, 0.5, 0.5, 0.0])
    result = FixedOMA(target_oma_w=oma_w(CONFIG, p)).check(CONFIG, p)
    assert result.status is FeasibilityStatus.INACTIVE and result.adjustments == {}
    assert "extreme levels are in use" not in result.reason and "no mass" in result.reason
    full = np.full(4, 0.25)  # outer levels used: the original wording is still true
    kept = FixedOMA(target_oma_w=oma_w(CONFIG, full)).check(CONFIG, full)
    assert kept.status is FeasibilityStatus.INACTIVE and "extreme levels are in use" in kept.reason


def test_fixed_oma_target_below_the_first_grid_value_is_reachable_with_a_tiny_swing():
    """1e-4 x OMA: OMA = P L V sin(pi V_pp a_max / (2 V_pi)) with a_max = 1, so V_pp =
    (2 V_pi / pi) asin(1e-4 sin(pi / 4)) = 1.8006e-4 V. A grid that starts above zero said
    that no swing reaches it and quoted a larger reachable OMA."""
    p = np.full(4, 0.25)
    target = 1e-4 * oma_w(CONFIG, p)
    expected = (2 * CONFIG.v_pi / math.pi) * math.asin(1e-4 * math.sin(math.pi / 4))
    assert expected == pytest.approx(1.8006e-4, rel=1e-4)
    declared = FixedOMA(target_oma_w=target, allow_drive_rescale=True).check(CONFIG, p)
    assert declared.status is FeasibilityStatus.FEASIBLE
    assert declared.adjustments["drive_vpp"] == pytest.approx(expected, rel=1e-8)
    assert oma_w(replace(CONFIG, drive_vpp=declared.adjustments["drive_vpp"]), p) == pytest.approx(
        target, rel=1e-8
    )
    undeclared = FixedOMA(target_oma_w=target).check(CONFIG, p)
    assert undeclared.status is FeasibilityStatus.INFEASIBLE and "not declared" in undeclared.reason
    assert undeclared.adjustments["drive_vpp"] == pytest.approx(expected, rel=1e-8)


@pytest.mark.parametrize("order", [8, 16])  # at M = 4 the peak swing 12 V is beyond 2 V_pi
def test_fixed_oma_at_the_analytic_peak_is_feasible_and_just_above_it_is_not(order):
    """With the outer pair unused the largest inner amplitude is a = (M - 3) / (M - 1) and OMA is
    P L V sin(pi V_pp a / (2 V_pi)), maximal (sin = 1) at V_pp = V_pi / a = 4 (M - 1) / (M - 3) V:
    M = 16 gives 4.6154 V, which falls between grid points of 2 V_pi / 8000 = 1 mV."""
    p = np.zeros(order)
    p[1:-1] = 1.0 / (order - 2)
    peak_oma = CONFIG.laser_power_w * LOSS * VIS  # sin = 1
    swing = CONFIG.v_pi * (order - 1) / (order - 3)  # 4 (M - 1) / (M - 3) V
    on = FixedOMA(target_oma_w=peak_oma, allow_drive_rescale=True).check(CONFIG, p)
    assert on.status is FeasibilityStatus.FEASIBLE
    assert on.adjustments["drive_vpp"] == pytest.approx(swing, abs=1e-6)
    assert oma_w(replace(CONFIG, drive_vpp=on.adjustments["drive_vpp"]), p) == pytest.approx(
        peak_oma, rel=1e-9
    )
    above = FixedOMA(target_oma_w=peak_oma * (1 + 1e-6), allow_drive_rescale=True).check(CONFIG, p)
    assert above.status is FeasibilityStatus.INFEASIBLE and f"{peak_oma:.4g}" in above.reason
    below = FixedOMA(target_oma_w=peak_oma * (1 - 1e-7), allow_drive_rescale=True).check(CONFIG, p)
    assert below.status is FeasibilityStatus.FEASIBLE  # on the rising branch, before the peak
    assert below.adjustments["drive_vpp"] < swing
    assert oma_w(replace(CONFIG, drive_vpp=below.adjustments["drive_vpp"]), p) == pytest.approx(
        peak_oma * (1 - 1e-7), rel=1e-8
    )


def test_fixed_peak_rescale_needs_a_declaration():
    p = np.full(4, 0.25)
    undeclared = FixedPeak(peak_v=0.8).check(CONFIG, p)
    assert undeclared.status is FeasibilityStatus.INFEASIBLE
    assert undeclared.adjustments["drive_vpp"] == pytest.approx(1.6)
    declared = FixedPeak(peak_v=0.8, allow_drive_rescale=True).check(CONFIG, p)
    assert declared.status is FeasibilityStatus.FEASIBLE
    assert declared.adjustments["drive_vpp"] == pytest.approx(1.6)
    assert FixedPeak(peak_v=1.0).check(CONFIG, p).status is FeasibilityStatus.FEASIBLE
    with pytest.raises(ValueError):
        FixedPeak(peak_v=-1.0).check(CONFIG, p)


def test_drive_voltages_are_odd_and_span_the_configured_peak():
    for order in (4, 8, 16):
        v = drive_voltages(CONFIG, order)
        assert np.allclose(v, -v[::-1]) and v.max() == pytest.approx(CONFIG.drive_vpp / 2)


# --------------------------------------------------------------------- equal realised user rate


def accounting(p, head=1024, payload=8192, block=1024, sps=4) -> FrameAccounting:
    """Uniform PMFs are sent direct (2 bits per symbol at PAM4, as frame.py direct_uniform)."""
    if np.allclose(p, 1.0 / len(p)):
        return FrameAccounting(head, payload, block, int(math.log2(len(p)) * block), sps)
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(p, block)
    return FrameAccounting(head, payload, block, matcher.k, sps)


def test_user_rate_accounting_matches_hand_arithmetic():
    p = np.full(4, 0.25)
    acc = accounting(p)
    expected = 224e9 / 4 * (8 * 2048) / (1024 + 8192)  # direct uniform: 2 bits per symbol
    assert acc.user_rate_bps(224e9) == pytest.approx(expected, rel=1e-14)
    assert acc.information_bits == 8 * 2048 and acc.frame_symbols == 9216
    ps70 = ConstantCompositionMatcher.from_symmetric_probabilities([0.15, 0.35, 0.35, 0.15], 1024)
    assert accounting(np.array([0.15, 0.35, 0.35, 0.15])).block_bits == ps70.k == 1912
    # head symbols are overhead: with none the same blocks give a rate higher by 9216 / 8192
    bare = accounting(p, head=0)
    assert bare.user_rate_bps(224e9) / acc.user_rate_bps(224e9) == pytest.approx(9216 / 8192)
    with pytest.raises(ValueError):
        FrameAccounting(0, 1000, 1024, 1, 4)  # payload not a multiple of the block


def test_equal_rate_matches_by_sample_rate_and_reports_infeasible_when_out_of_range():
    uniform = np.full(4, 0.25)
    target = accounting(uniform).user_rate_bps(224e9)
    rows = {}
    for name, p in fixed_menu(4).items():
        acc = accounting(p)
        ratio = target / acc.user_rate_bps(224e9)  # independent of constraints.py
        in_range = 200e9 <= 224e9 * ratio <= 256e9
        result = EqualRealizedUserRate(target, allow_sample_rate_adjustment=True).check(acc)
        rows[name] = (ratio, result)
        assert (result.status is FeasibilityStatus.FEASIBLE) == in_range
        if ratio != 1.0:
            assert result.adjustments["sample_rate_hz"] == pytest.approx(224e9 * ratio, rel=1e-12)
    assert rows["PAM4_Uniform"][1].status is FeasibilityStatus.FEASIBLE
    assert rows["PAM4_Uniform"][1].adjustments == {}
    # against the direct uniform (2048 bits per block): PS80 carries 1747 and needs +17.2 %, which
    # +14.3 % of sample rate cannot make up; PS70 carries 1912 and needs +7.1 %
    ratio80, result80 = rows["PAM4_Fixed_PS80"]
    assert ratio80 == pytest.approx(2048 / 1747, rel=1e-12) and round(ratio80 - 1, 3) == 0.172
    assert ratio80 > 256 / 224 and result80.status is FeasibilityStatus.INFEASIBLE
    assert "GSa/s" in result80.reason and "outside 200 to 256" in result80.reason
    # PS70 is inside the range
    ratio70, result70 = rows["PAM4_Fixed_PS70"]
    assert ratio70 == pytest.approx(2048 / 1912, rel=1e-12) and round(ratio70 - 1, 3) == 0.071
    assert 1.0 < ratio70 < 256 / 224 and result70.status is FeasibilityStatus.FEASIBLE


def test_no_per_waveform_rescale_without_the_declared_flag():
    uniform = np.full(4, 0.25)
    target = accounting(uniform).user_rate_bps(224e9)
    acc = accounting(np.array([0.15, 0.35, 0.35, 0.15]))  # PS70: needs about +7 %, in range
    rate_before = acc.user_rate_bps(224e9)
    refused = EqualRealizedUserRate(target).check(acc)  # no flag
    assert refused.status is FeasibilityStatus.INFEASIBLE
    assert "not declared" in refused.reason and "sample_rate_hz" in refused.adjustments
    allowed = EqualRealizedUserRate(target, allow_sample_rate_adjustment=True).check(acc)
    assert allowed.status is FeasibilityStatus.FEASIBLE
    assert allowed.adjustments["sample_rate_hz"] == refused.adjustments["sample_rate_hz"]
    assert acc.user_rate_bps(224e9) == rate_before  # nothing was applied to the accounting
    with pytest.raises(FrozenInstanceError):
        acc.head_symbols = 0  # type: ignore[misc]
    # applying the reported rate, and only then, equalises the user rate
    assert acc.user_rate_bps(allowed.adjustments["sample_rate_hz"]) == pytest.approx(
        target, rel=1e-12
    )


def test_equal_rate_range_edges_and_overhead_dependence():
    p = np.full(4, 0.25)
    acc = accounting(p)
    nominal = acc.user_rate_bps(224e9)
    edge_low = EqualRealizedUserRate(nominal * 200 / 224, allow_sample_rate_adjustment=True)
    edge_high = EqualRealizedUserRate(nominal * 256 / 224, allow_sample_rate_adjustment=True)
    assert edge_low.check(acc).status is FeasibilityStatus.FEASIBLE
    assert edge_high.check(acc).status is FeasibilityStatus.FEASIBLE
    below = EqualRealizedUserRate(nominal * 0.89, allow_sample_rate_adjustment=True)
    above = EqualRealizedUserRate(nominal * 1.15, allow_sample_rate_adjustment=True)
    assert below.check(acc).status is FeasibilityStatus.INFEASIBLE  # 199.4 GSa/s
    assert above.check(acc).status is FeasibilityStatus.INFEASIBLE  # 257.6 GSa/s
    # a longer head (PAM16 training) costs rate; the same payload bits then need a higher f_s
    long_head = accounting(p, head=2560)
    ratio = acc.user_rate_bps(224e9) / long_head.user_rate_bps(224e9)
    assert ratio == pytest.approx((2560 + 8192) / (1024 + 8192))
    needed = EqualRealizedUserRate(nominal, allow_sample_rate_adjustment=True).check(long_head)
    assert needed.adjustments["sample_rate_hz"] == pytest.approx(224e9 * ratio)
    with pytest.raises(ValueError):
        EqualRealizedUserRate(-1.0).check(acc)


def test_equal_rate_range_edges_have_a_tight_tolerance_and_outside_negatives():
    """Needed sample rate within 1e-9 relative of an edge passes; 1e-6 and 1e-8 outside fail at
    both ends (a 1e-3 tolerance, or none at the lower edge, would change one of these)."""
    acc = accounting(np.full(4, 0.25))
    nominal = acc.user_rate_bps(224e9)

    def at(sample_rate: float) -> FeasibilityStatus:
        constraint = EqualRealizedUserRate(
            nominal * sample_rate / 224e9, allow_sample_rate_adjustment=True
        )
        return constraint.check(acc).status

    assert at(256e9 * (1 + 1e-10)) is FeasibilityStatus.FEASIBLE
    assert at(200e9 * (1 - 1e-10)) is FeasibilityStatus.FEASIBLE
    for outside in (1e-6, 1e-8):
        assert at(256e9 * (1 + outside)) is FeasibilityStatus.INFEASIBLE
        assert at(200e9 * (1 - outside)) is FeasibilityStatus.INFEASIBLE
    assert (
        at(256.1e9) is FeasibilityStatus.INFEASIBLE and at(199.9e9) is FeasibilityStatus.INFEASIBLE
    )


# --------------------------------------------------------------------- inner-heavy may win


def sine_compressed_channel(order: int, sigma: float, g: float = 1.55) -> ChannelEstimate:
    """Level means of a quadrature MZM driven near V_pi/2: m = sin(g a) / sin(g) (M - 1)."""
    a = pam_levels(order) / (order - 1)
    means = np.sin(g * a) / np.sin(g) * (order - 1)
    return ChannelEstimate([float(m) for m in means], [sigma] * order, 10**6)


def awgn_channel(order: int, psnr_db: float) -> ChannelEstimate:
    sigma = 2.0 * noise_sigma_from_psnr_db(psnr_db, order)
    return ChannelEstimate([float(x) for x in pam_levels(order)], [sigma] * order, 10**6)


def objective_of(rows, suffix_free: str) -> float:
    return next(r["objective"] for r in rows if r["name"].endswith(suffix_free))


SCAN_GS = (0.6, 1.0, 1.3, 1.55, math.pi / 2, 1.8, 2.2, 2.6)  # drive g = pi V_pp / (2 V_pi)
SCAN_SIGMAS = (0.15, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 3.0)
INNER_NAMES = ("Inner", "PS")


def inner_minus_uniform(order: int, channel: ChannelEstimate, metric: str = "bmd") -> float:
    """Best inner-heavy member of the declared menu minus the DIRECT uniform (no matcher)."""
    rows = evaluate_menu(channel, order, metric, 1024)
    uniform = objective_of(rows, "Uniform")
    return max(r["objective"] for r in rows if any(t in r["name"] for t in INNER_NAMES)) - uniform


def test_inner_heavy_versus_direct_uniform_over_a_declared_sine_compression_scan_at_m8():
    """The earlier claim "inner-heavy beats uniform by 0.025 bit at g = 1.55, sigma = 0.8" came from
    charging the uniform a CCDM loss it does not pay. Against the direct uniform that margin is
    -0.0075. The scan below (8 drive gains g x 8 sigmas = 64 channels, BMD, n = 1024, the menu
    of fixed_menu) was run to find, honestly, where inner-heavy does win: nowhere for g <= pi/2
    (monotone, unfolded means), and in 5 of the 8 channels at g = 1.8, 7 of 8 at g = 2.2 and 2 of 8 at g = 2.6.
    g = 1.8 is the least overdriven winning gain (means still monotone, outer spacing compressed)."""
    base = sine_compressed_channel(8, 0.8, 1.55)
    assert inner_minus_uniform(8, base) == pytest.approx(-0.0075, abs=5e-4)
    for g in SCAN_GS:
        wins = [
            s for s in SCAN_SIGMAS if inner_minus_uniform(8, sine_compressed_channel(8, s, g)) > 0
        ]
        if g <= math.pi / 2 + 1e-9:
            assert wins == [], (g, wins)  # no inner-heavy win for any g <= pi/2
        elif g == 1.8:
            assert wins == [0.15, 0.3, 0.5, 0.8, 1.2]
        elif g == 2.2:
            assert wins == list(SCAN_SIGMAS[:7])
        else:
            assert wins == [2.0, 3.0]
    declared = sine_compressed_channel(8, 0.8, 1.8)  # found by the scan above, not tuned to a claim
    gaps = np.diff(declared.means)
    assert gaps[0] < 0.1 * gaps[3] and np.all(gaps > 0)  # monotone, outermost spacing compressed
    rows = evaluate_menu(declared, 8, "bmd", 1024)
    uniform = objective_of(rows, "Uniform")
    inner = max(r["objective"] for r in rows if "Inner" in r["name"])
    outer = max(r["objective"] for r in rows if "Outer" in r["name"])
    assert inner - uniform == pytest.approx(0.075, abs=2e-3) and outer < uniform - 0.1
    # at fixed-peak AWGN, 22 dB, the inner-heavy members lose (BMD, direct uniform)
    awgn = evaluate_menu(awgn_channel(8, 22.0), 8, "bmd", 1024)
    assert max(r["objective"] for r in awgn if "Inner" in r["name"]) < objective_of(awgn, "Uniform")
    # the optimiser, free over the symmetric family, moves mass inward in the declared channel
    sel = optimise_symmetric(declared, 8, "bmd", 1024, 4, multistart_check=False)
    uniform_obj = next(c for c in sel.candidates if c["name"] == "uniform")["objective"]
    assert sel.objective > uniform_obj + 0.05
    assert sel.probabilities[0] < 1 / 8 and sel.probabilities[3] > 1 / 8
    # and the winning PMF is not explained by average optical power: that constraint is
    # INACTIVE for it (and for uniform) at quadrature
    for p in (sel.probabilities, [1 / 8] * 8):
        assert FixedAverageOpticalPower().check(CONFIG, p).status is FeasibilityStatus.INACTIVE


def test_m4_inner_heavy_never_beats_direct_uniform_in_the_declared_scan_except_when_overdriven():
    """Scope of the M = 4 statement, as scanned: g in SCAN_GS x SIGMAS (64 channels), both
    metrics, n = 1024, PS70 and PS80 against the direct PAM4 uniform. Inner-heavy never wins
    for g <= 2.2 (all monotone-compressed and moderately folded means). It wins at g = 2.6, the
    overdriven class (means folded over), at sigma 2.0 and 3.0: by 0.012 and 0.054 bit (BMD),
    with the P(+-3) share of PS80 = 0.10 and PS70 = 0.15. Not scanned: other mean shapes."""
    wins = {}
    for metric in ("bmd", "smd"):
        for g in SCAN_GS:
            for sigma in SCAN_SIGMAS:
                if inner_minus_uniform(4, sine_compressed_channel(4, sigma, g), metric) > 0:
                    wins.setdefault(metric, []).append((round(g, 3), sigma))
    assert wins == {"bmd": [(2.6, 2.0), (2.6, 3.0)], "smd": [(2.6, 2.0), (2.6, 3.0)]}
    overdriven = sine_compressed_channel(4, 2.0, 2.6)
    assert inner_minus_uniform(4, overdriven) == pytest.approx(0.0122, abs=5e-4)
    assert np.diff(overdriven.means)[0] < 0  # the outermost mean folds back: not monotone


def test_outer_heavy_wins_at_m4_fixed_peak_awgn_and_not_in_a_wide_open_channel():
    rows = evaluate_menu(awgn_channel(4, 14.0), 4, "bmd", 1024)
    assert objective_of(rows, "Outer70") > objective_of(rows, "Uniform")
    assert objective_of(rows, "PS70") < objective_of(rows, "Uniform")
    rows = evaluate_menu(awgn_channel(4, 30.0), 4, "bmd", 1024)
    assert objective_of(rows, "Uniform") >= max(r["objective"] for r in rows) - 1e-12
