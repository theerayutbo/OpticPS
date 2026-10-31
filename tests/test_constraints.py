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
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(p, block)
    return FrameAccounting(head, payload, block, matcher.k, sps)


def test_user_rate_accounting_matches_hand_arithmetic():
    p = np.full(4, 0.25)
    acc = accounting(p)
    k = ConstantCompositionMatcher.from_symmetric_probabilities(p, 1024).k
    expected = 224e9 / 4 * (8 * k) / (1024 + 8192)
    assert acc.user_rate_bps(224e9) == pytest.approx(expected, rel=1e-14)
    assert acc.information_bits == 8 * k and acc.frame_symbols == 9216
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
    # PS80 carries so few bits that +14.3 % of sample rate cannot make up the difference
    ratio80, result80 = rows["PAM4_Fixed_PS80"]
    assert ratio80 > 256 / 224 and result80.status is FeasibilityStatus.INFEASIBLE
    assert "GSa/s" in result80.reason and "outside 200 to 256" in result80.reason
    # PS70 is inside the range
    ratio70, result70 = rows["PAM4_Fixed_PS70"]
    assert 1.0 < ratio70 < 256 / 224 and result70.status is FeasibilityStatus.FEASIBLE


def test_no_per_waveform_rescale_without_the_declared_flag():
    uniform = np.full(4, 0.25)
    target = accounting(uniform).user_rate_bps(224e9)
    acc = accounting(np.array([0.15, 0.35, 0.35, 0.15]))  # PS70: needs about +6 %, in range
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


def test_inner_heavy_can_beat_uniform_with_compressed_outer_spacing_and_loses_at_fixed_peak_awgn():
    """No winner is assumed: both outcomes come from the same code and the same menu."""
    compressed = sine_compressed_channel(8, 0.8)
    gaps = np.diff(compressed.means)
    assert gaps[0] < 0.5 * gaps[3]  # the outermost spacing really is compressed
    awgn = awgn_channel(8, 22.0)
    results = {}
    for label, channel in (("compressed", compressed), ("awgn", awgn)):
        rows = evaluate_menu(channel, 8, "bmd", 1024)
        uniform = objective_of(rows, "Uniform")
        inner = max(r["objective"] for r in rows if "Inner" in r["name"])
        outer = max(r["objective"] for r in rows if "Outer" in r["name"])
        results[label] = (inner - uniform, outer - uniform)
    assert results["compressed"][0] > 0.01  # inner-heavy beats uniform here
    assert results["compressed"][0] > results["compressed"][1]  # and outer-heavy
    assert results["awgn"][0] < -0.05  # the reverse at fixed-peak AWGN
    # the optimiser, free over the whole symmetric family, also leaves uniform in the compressed
    # channel and moves the mass inward (outermost pair below its uniform share)
    sel = optimise_symmetric(compressed, 8, "bmd", 1024, 4, multistart_check=False)
    uniform_obj = next(c for c in sel.candidates if c["name"] == "uniform")["objective"]
    assert sel.objective > uniform_obj + 0.01
    assert sel.probabilities[0] < 1 / 8 and sel.probabilities[3] > 1 / 8
    # and the winning PMF is not explained by average optical power: that constraint is
    # INACTIVE for it (and for uniform) at quadrature
    for p in (sel.probabilities, [1 / 8] * 8):
        assert FixedAverageOpticalPower().check(CONFIG, p).status is FeasibilityStatus.INACTIVE


def test_outer_heavy_wins_at_m4_fixed_peak_awgn_and_not_in_a_wide_open_channel():
    rows = evaluate_menu(awgn_channel(4, 14.0), 4, "bmd", 1024)
    assert objective_of(rows, "Outer70") > objective_of(rows, "Uniform")
    assert objective_of(rows, "PS70") < objective_of(rows, "Uniform")
    rows = evaluate_menu(awgn_channel(4, 30.0), 4, "bmd", 1024)
    assert objective_of(rows, "Uniform") >= max(r["objective"] for r in rows) - 1e-12
