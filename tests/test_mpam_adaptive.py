"""Independent checks of the generic symmetric optimiser and the best-fixed baseline.

References are derived here, not taken from adaptive.py: the matcher term is rebuilt from the
integer composition and an exact multinomial, the concavity claim is tested on midpoints, the
M = 4 optimum is compared with the existing exhaustive grid search of rates.py, and the
Maxwell-Boltzmann entropy targets are recomputed from the PMFs. The synthetic channels are
declared in the tests: nothing here is fitted to the result it checks.
"""

import json
import math
import time

import numpy as np
import pytest

from opticps.distribution_matching.ccdm import (
    ConstantCompositionMatcher,
    quantize_composition,
    quantize_symmetric_composition,
)
from opticps.modulation.pam import pam_levels
from opticps.optimization import adaptive
from opticps.optimization.adaptive import (
    ChannelEstimate,
    best_fixed,
    estimate_channel,
    evaluate_menu,
    fixed_menu,
    optimise_symmetric,
    oracle_not_a_baseline,
    pair_bounds,
    select_distribution,
    simulate_training_capture,
)
from opticps.optimization.rates import (
    gaussian_rates,
    noise_sigma_from_psnr_db,
    optimal_outer_probability,
)
from opticps.shaping.distributions import (
    entropy_bits,
    symmetric_from_pairs,
    symmetric_pam4,
)


def awgn_channel(order: int, psnr_db: float, wobble: float = 0.0) -> ChannelEstimate:
    """Peak-limited AWGN on the bipolar levels (spacing 2), optionally with unequal sigma."""
    sigma = 2.0 * noise_sigma_from_psnr_db(psnr_db, order)
    sigmas = [sigma * (1.0 + wobble * (i % 3 - 1)) for i in range(order)]
    return ChannelEstimate([float(x) for x in pam_levels(order)], sigmas, 10**6)


def independent_matcher_loss(p, n: int) -> float:
    """H(counts / n) - floor(log2 multinomial) / n, from the counts alone."""
    counts = quantize_symmetric_composition(p, n)
    ways = math.factorial(n)
    for c in counts:
        ways //= math.factorial(c)
    k = ways.bit_length() - 1
    h = -sum(c / n * math.log2(c / n) for c in counts if c)
    return h - k / n


# --------------------------------------------------------------------------- legacy path


def test_legacy_estimate_and_simulation_keep_the_pam4_draw_order():
    indices, received = simulate_training_capture(12.0, 5000, 42)
    rng = np.random.default_rng(42)
    ref_idx = rng.integers(0, 4, 5000)
    ref_rx = pam_levels(4)[ref_idx] + rng.normal(0.0, 2.0 * noise_sigma_from_psnr_db(12.0), 5000)
    assert np.array_equal(indices, ref_idx) and np.array_equal(received, ref_rx)
    default = estimate_channel(indices, received)
    explicit = estimate_channel(indices, received, 4)
    assert default == explicit and len(default.means) == 4


def test_legacy_selection_equals_a_reference_copy_and_keeps_its_keys():
    indices, received = simulate_training_capture(13.0, 40000, 42)
    got = select_distribution(indices, received, "ref", "bmd", 1024, 0.02)
    channel = estimate_channel(indices, received)
    best = None
    for p_outer in np.arange(0.05, 0.4951, 0.02):
        p_outer = round(float(p_outer), 6)
        p = symmetric_pam4(p_outer)
        rate = gaussian_rates(p, channel.means, channel.sigmas).bmd
        loss = ConstantCompositionMatcher.from_probabilities(p, 1024).rate_loss
        if best is None or rate - loss > best[1]:
            best = (p_outer, rate - loss)
    assert (got.p_outer, got.objective) == best
    keys = set(got.to_dict())
    committed = json.loads(open("output/keysight_m8199b/adaptive_selection.json").read())
    assert keys == set(committed) - {"design_psnr_db"}
    assert got.family == adaptive.LEGACY_FAMILY and got.order == 4
    # the legacy composition rule is untouched and used by the legacy path
    assert quantize_composition(symmetric_pam4(got.p_outer), 1024) == tuple(
        ConstantCompositionMatcher.from_probabilities(got.probabilities, 1024).counts
    )


def test_legacy_path_does_not_force_the_common_grid(monkeypatch):
    seen = []
    real = adaptive.gaussian_rates

    def spy(*args, **kwargs):
        seen.append(kwargs.get("quadrature"))
        return real(*args, **kwargs)

    monkeypatch.setattr(adaptive, "gaussian_rates", spy)
    indices, received = simulate_training_capture(13.0, 8000, 1)
    select_distribution(indices, received, "x", "smd", 1024, 0.05)
    assert seen and set(seen) == {None}  # the legacy call never passes quadrature


# --------------------------------------------------------------------------- generic estimate


@pytest.mark.parametrize("order", [4, 8, 16])
def test_generic_simulation_and_estimate_recover_levels_and_sigma(order):
    psnr = 20.0
    indices, received = simulate_training_capture(psnr, 40000 * order // 4, 5, order)
    assert indices.min() == 0 and indices.max() == order - 1
    channel = estimate_channel(indices, received, order)
    sigma = 2.0 * (order - 1) / 10 ** (psnr / 20)  # PSNR definition, bipolar spacing 2
    assert len(channel.means) == len(channel.sigmas) == order
    assert np.allclose(channel.means, pam_levels(order), atol=6 * sigma / math.sqrt(10000))
    assert np.allclose(channel.sigmas, sigma, rtol=0.05)


def test_estimate_requires_samples_of_every_level():
    with pytest.raises(ValueError, match="too few samples of level 7"):
        estimate_channel(np.array([0, 1, 2, 3, 4, 5, 6] * 4), np.zeros(28), 8)


# --------------------------------------------------------------------------- quadrature


@pytest.mark.parametrize("order", [4, 8])
def test_unequal_sigma_forces_the_common_grid_including_m4(order, monkeypatch):
    seen = []
    real = adaptive.gaussian_rates

    def spy(*args, **kwargs):
        seen.append(kwargs.get("quadrature"))
        return real(*args, **kwargs)

    monkeypatch.setattr(adaptive, "gaussian_rates", spy)
    sel = optimise_symmetric(
        awgn_channel(order, 14.0, 0.01), order, "smd", 256, 1, multistart_check=False
    )
    assert seen and set(seen) == {"common_grid"}
    assert sel.parameters["quadrature"] == "common_grid"
    seen.clear()
    sel = optimise_symmetric(
        awgn_channel(order, 14.0), order, "smd", 256, 1, multistart_check=False
    )
    assert set(seen) == {"auto"} and sel.parameters["quadrature"] == "auto"  # exactly equal sigma


# --------------------------------------------------------------------------- concavity


@pytest.mark.parametrize(("order", "pairs"), [(4, 40), (8, 20), (16, 6)])
def test_smd_is_concave_on_midpoints_of_the_symmetric_box(order, pairs):
    """I(X;Y) at a fixed channel: I(mid) >= mean of the endpoints, for random box points."""
    channel = awgn_channel(order, 16.0, 0.05)
    lower, upper = pair_bounds(order, 1024)
    n = order // 2
    rng = np.random.default_rng(11)
    room = 0.5 - n * lower

    def smd(q):
        p = symmetric_from_pairs(q)
        return gaussian_rates(p, channel.means, channel.sigmas, order, quadrature="common_grid").smd

    gaps = []
    for _ in range(pairs):
        a = lower + room * rng.dirichlet(np.ones(n) * 0.7)
        b = lower + room * rng.dirichlet(np.ones(n) * 0.7)
        mid = 0.5 * (a + b)
        gaps.append(smd(mid) - 0.5 * (smd(a) + smd(b)))
        quarter = 0.75 * a + 0.25 * b  # an unequal weight as well
        assert smd(quarter) >= 0.75 * smd(a) + 0.25 * smd(b) - 1e-10
    assert min(gaps) >= -1e-10  # no violation beyond quadrature noise
    assert max(gaps) > 1e-4  # and the test is not vacuous: the midpoints are strictly above


# --------------------------------------------------------------------------- optimiser


@pytest.mark.parametrize("psnr", [13.85, 16.0])
@pytest.mark.parametrize("metric", ["smd", "bmd"])
def test_m4_fixed_peak_awgn_matches_the_existing_exhaustive_optimum(psnr, metric):
    """At M = 4 on equal-sigma AWGN the continuous optimum is the P0* of rates.py, to its grid."""
    grid_step = 0.0025
    p0, _ = optimal_outer_probability(psnr, metric)
    sel = optimise_symmetric(awgn_channel(4, psnr), 4, metric, 1024, 3)
    continuous = sel.parameters["continuous_optimum"]["q"][-1]
    assert abs(continuous - p0) <= grid_step
    assert abs(sel.p_outer - p0) <= grid_step + 1 / 1024  # quantised by the block
    assert sel.p_outer > 0.25  # outer-heavy, as the existing optimum is
    assert sel.p_outer == sel.probabilities[0] and sel.family == adaptive.GENERIC_FAMILY


def test_smd_multistart_agrees_and_claim_is_the_limited_one():
    sel = optimise_symmetric(awgn_channel(8, 22.0, 0.03), 8, "smd", 1024, 5)
    assert sel.claim.startswith("global for the unquantised SMD objective, on this channel")
    assert "11 starts agree" in sel.claim
    agree = sel.parameters["agreement"]
    assert agree["n_starts"] == 11 and agree["max_objective_gap_bit"] < 1e-6
    assert agree["max_q_gap_to_best_start"] < 1e-4
    finals = np.array([s["final_q"] for s in sel.starts])
    assert np.ptp(finals, axis=0).max() < 1e-4
    # independent check: no random point of the box beats the continuous optimum
    channel = sel.channel
    best = sel.parameters["continuous_optimum"]["objective"]
    rng = np.random.default_rng(2)
    lower, _ = pair_bounds(8, 1024)
    for _ in range(60):
        q = lower + (0.5 - 4 * lower) * rng.dirichlet(np.ones(4) * 0.5)
        r = gaussian_rates(
            symmetric_from_pairs(q), channel.means, channel.sigmas, 8, quadrature="common_grid"
        )
        assert r.smd <= best + 1e-9


def test_m4_smd_optimum_equals_brute_force_over_the_box():
    sel = optimise_symmetric(awgn_channel(4, 12.0, 0.04), 4, "smd", 1024, 1)
    channel = sel.channel
    lower, upper = pair_bounds(4, 1024)
    values = []
    for outer in np.linspace(lower, 0.5 - lower, 1001):
        r = gaussian_rates(
            symmetric_from_pairs(np.array([0.5 - outer, outer])),
            channel.means,
            channel.sigmas,
            4,
            quadrature="common_grid",
        )
        values.append(r.smd)
    assert sel.parameters["continuous_optimum"]["objective"] >= max(values) - 1e-9
    assert sel.parameters["continuous_optimum"]["objective"] - max(values) < 1e-6


def test_bmd_multistart_log_is_complete_and_the_claim_is_best_of_n():
    sel = optimise_symmetric(awgn_channel(8, 22.0, 0.03), 8, "bmd", 1024, 5)
    assert sel.claim.startswith("best of 11 starts")
    assert "global" not in sel.claim
    names = [s["name"] for s in sel.starts]
    assert names[0] == "uniform" and len(names) == 11 and len(set(names)) == 11
    assert [n for n in names if n.startswith("mb_inner")] == [
        f"mb_inner_H{h}" for h in (288, 272, 240)
    ]
    assert [n for n in names if n.startswith("mb_outer")] == [
        f"mb_outer_H{h}" for h in (288, 272, 240)
    ]
    assert [n for n in names if n.startswith("dirichlet")] == [f"dirichlet_{k}" for k in range(4)]
    for s in sel.starts:
        assert set(s) >= {
            "start_q", "final_q", "objective", "iterations", "status", "message", "success",
            "rate_evaluations", "mapped_into_bounds", "objective_metric",
        }  # fmt: skip
        assert s["objective_metric"] == "bmd_raw" and s["iterations"] >= 1
        assert sum(s["final_q"]) == pytest.approx(0.5, abs=1e-12)
    # the MB starts really sit at the stated entropies, each side
    for s in sel.starts[1:7]:
        h = float(s["name"].rsplit("H", 1)[1]) / 100
        p = symmetric_from_pairs(s["start_q"])
        assert entropy_bits(p) == pytest.approx(h, abs=6e-3)  # name is rounded to a centibit
    inner = symmetric_from_pairs(sel.starts[1]["start_q"])
    outer = symmetric_from_pairs(sel.starts[4]["start_q"])
    assert inner[3] > 1 / 8 > inner[0] and outer[0] > 1 / 8 > outer[3]  # inner- and outer-heavy
    assert sel.parameters["agreement"]["max_objective_gap_bit"] < 1e-6


def test_every_candidate_is_stored_and_the_selection_is_the_exact_argmax():
    sel = optimise_symmetric(awgn_channel(8, 22.0, 0.03), 8, "bmd", 1024, 5)
    kinds = [c["kind"] for c in sel.candidates]
    assert kinds.count("endpoint") == 11 and kinds.count("uniform") == 1
    assert kinds.count("mb_grid") == 2 * len(adaptive.DEFAULT_GRID_DEFICITS) == 20
    assert len(sel.candidates) == 32 and len({c["name"] for c in sel.candidates}) == 32
    ok = [c for c in sel.candidates if c["status"] == "ok" and c["in_bounds"]]
    best = max(ok, key=lambda c: c["objective"])
    assert sel.objective == best["objective"] and sel.probabilities == best["probabilities"]
    assert sel.parameters["selected"] == best["name"]
    channel = sel.channel
    for c in sel.candidates:  # every stored objective recomputed independently
        p = np.array(c["probabilities"])
        rate = gaussian_rates(p, channel.means, channel.sigmas, 8, quadrature="common_grid").bmd
        assert c["rate"] == pytest.approx(rate, abs=1e-12)
        assert c["matcher_loss"] == pytest.approx(independent_matcher_loss(p, 1024), abs=1e-12)
        assert c["objective"] == pytest.approx(rate - c["matcher_loss"], abs=1e-12)
        assert sum(c["counts"]) == 1024 and c["counts"] == c["counts"][::-1]
    json.dumps(sel.to_dict())  # fully serialisable
    assert sel.order == 8 and sel.p_outer is None and sel.lambda_value is None


def test_same_seed_gives_identical_logs_and_other_seed_changes_only_the_dirichlet_starts():
    a = optimise_symmetric(awgn_channel(4, 12.0, 0.02), 4, "bmd", 512, 9)
    b = optimise_symmetric(awgn_channel(4, 12.0, 0.02), 4, "bmd", 512, 9)
    assert a.to_dict() == b.to_dict()
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    c = optimise_symmetric(awgn_channel(4, 12.0, 0.02), 4, "bmd", 512, 10)
    for sa, sc in zip(a.starts, c.starts, strict=True):
        same = sa["start_q"] == sc["start_q"]
        assert same == (not sa["name"].startswith("dirichlet"))


def test_matcher_term_is_a_staircase_so_the_exact_objective_is_evaluated_after_the_fit():
    channel = awgn_channel(8, 22.0)
    q = np.array([0.1, 0.12, 0.13, 0.15])
    problem = adaptive._Problem(channel, 8, "smd", 1024)
    a = problem.evaluate(symmetric_from_pairs(q), "a", "x")
    nudged = q + np.array([1e-7, -1e-7, 1e-7, -1e-7])  # far smaller than 1/1024
    b = problem.evaluate(symmetric_from_pairs(nudged), "b", "x")
    assert a["counts"] == b["counts"] and a["matcher_loss"] == b["matcher_loss"]
    assert a["rate"] != b["rate"]  # the rate moves, the loss does not


def test_zero_count_quantisation_is_an_infeasible_candidate_never_selected():
    sel = optimise_symmetric(awgn_channel(8, 22.0, 0.02), 8, "smd", 8, 1, multistart_check=False)
    bad = [c for c in sel.candidates if c["status"] == "infeasible"]
    assert bad and sel.parameters["infeasible_candidates"] == len(bad)
    for c in bad:
        assert c["objective"] is None and c["counts"] is None
        assert "cannot represent" in c["reason"] and "DistributionMatcherError" in c["reason"]
    chosen = next(c for c in sel.candidates if c["name"] == sel.parameters["selected"])
    assert chosen["status"] == "ok" and chosen["objective"] == sel.objective
    # a block too short for any candidate: refused outright, not a silent pick
    with pytest.raises(ValueError, match="No feasible"):
        optimise_symmetric(awgn_channel(4, 14.0), 4, "smd", 2, 1, multistart_check=False)


def test_bad_arguments_are_rejected():
    ch = awgn_channel(4, 14.0)
    with pytest.raises(ValueError, match="even"):
        optimise_symmetric(ch, 4, "smd", 1023, 1)
    with pytest.raises(ValueError, match="metric"):
        optimise_symmetric(ch, 4, "gmi", 1024, 1)
    with pytest.raises(ValueError, match="M = 4, 8, 16"):
        pair_bounds(2, 1024)
    with pytest.raises(ValueError, match="8 levels"):
        optimise_symmetric(ch, 8, "smd", 1024, 1)


# --------------------------------------------------------------------------- negative case


@pytest.mark.parametrize("psnr", [36.0, 40.0, 45.0])
def test_high_snr_pam16_uniform_or_near_uniform_wins_because_matcher_loss_exceeds_gain(psnr):
    """Negative case: at high PSNR shaping cannot repay the finite-block matcher loss."""
    channel = awgn_channel(16, psnr, 0.02)
    sel = optimise_symmetric(channel, 16, "smd", 1024, 1, multistart_check=False)
    uniform = next(c for c in sel.candidates if c["name"] == "uniform")
    gain = sel.parameters["continuous_optimum"]["objective"] - uniform["rate"]
    assert uniform["matcher_loss"] > gain  # loss of the matcher exceeds the unquantised gain
    assert sel.objective - uniform["objective"] < 1e-5  # nothing beats uniform by a real margin
    assert np.abs(np.array(sel.probabilities) - 1 / 16).sum() < 5e-3  # uniform or near-uniform
    assert gain < 5e-3


# --------------------------------------------------------------------------- best fixed


def test_fixed_menu_names_entropies_and_exact_pam4_members():
    pam4 = fixed_menu(4)
    assert list(pam4) == [
        "PAM4_Uniform",
        "PAM4_Fixed_PS70",
        "PAM4_Fixed_PS80",
        "PAM4_Fixed_Outer70",
    ]
    assert pam4["PAM4_Fixed_PS70"] == (0.15, 0.35, 0.35, 0.15)
    assert pam4["PAM4_Fixed_PS80"] == (0.10, 0.40, 0.40, 0.10)
    assert pam4["PAM4_Fixed_Outer70"] == (0.35, 0.15, 0.15, 0.35)
    for order, top in ((8, 3.0), (16, 4.0)):
        menu = fixed_menu(order)
        centi = [round(100 * (top - d)) for d in (0.12, 0.28)]
        assert list(menu) == [
            f"PAM{order}_Uniform",
            f"PAM{order}_Fixed_Inner_H{centi[0]}",
            f"PAM{order}_Fixed_Inner_H{centi[1]}",
            f"PAM{order}_Fixed_Outer_H{centi[0]}",
            f"PAM{order}_Fixed_Outer_H{centi[1]}",
        ]
        assert centi == ([288, 272] if order == 8 else [388, 372])
        for name, p in menu.items():
            if name.endswith("Uniform"):
                assert entropy_bits(p) == pytest.approx(top, abs=1e-12)
                continue
            deficit = 0.12 if name.endswith(f"H{centi[0]}") else 0.28
            assert entropy_bits(p) == pytest.approx(top - deficit, abs=1e-9)
            half = np.array(p[order // 2 :])
            assert ("Inner" in name) == (half[0] > half[-1])  # inner pair vs outer pair mass
    with pytest.raises(ValueError):
        fixed_menu(2)


def test_best_fixed_is_the_argmax_of_the_training_objective_and_oracle_is_labelled():
    train = awgn_channel(4, 14.0)  # outer-heavy territory
    chosen = best_fixed(train, 4, "bmd", 1024)
    table = {r["name"]: r["objective"] for r in chosen.table}
    assert chosen.name == max(table, key=table.get) and chosen.selected_on == "training"
    assert chosen.objective == table[chosen.name]
    assert "oracle_not_a_baseline" not in json.dumps(chosen.to_dict())
    assert chosen.name == "PAM4_Fixed_Outer70"  # derived from the numbers, see the table
    assert table["PAM4_Fixed_Outer70"] > table["PAM4_Uniform"] > table["PAM4_Fixed_PS70"]
    # a different evaluation channel has a different best member; the baseline does not follow it
    test_channel = awgn_channel(4, 30.0)
    oracle = oracle_not_a_baseline(test_channel, 4, "bmd", 1024)
    assert list(oracle) == ["oracle_not_a_baseline"]
    assert oracle["oracle_not_a_baseline"]["name"] == "PAM4_Uniform"
    assert "not a baseline" in oracle["oracle_not_a_baseline"]["selected_on"]
    assert best_fixed(train, 4, "bmd", 1024).name == chosen.name  # unaffected by the oracle call


def test_best_fixed_logs_infeasible_members_and_excludes_them():
    rows = evaluate_menu(awgn_channel(8, 22.0), 8, "smd", 8)
    assert any(r["status"] == "infeasible" for r in rows)
    with pytest.raises(ValueError, match="No feasible"):
        best_fixed(awgn_channel(8, 22.0), 8, "smd", 2)


# --------------------------------------------------------------------------- runtime


@pytest.mark.slow
def test_m16_runtime_and_start_agreement_are_recorded(capsys):
    channel = awgn_channel(16, 28.0, 0.02)
    out = {}
    for metric in ("smd", "bmd"):
        t0 = time.perf_counter()
        sel = optimise_symmetric(channel, 16, metric, 1024, 7)
        out[metric] = (time.perf_counter() - t0, sel)
        assert sel.parameters["agreement"]["max_objective_gap_bit"] < 1e-6
        assert len(sel.starts) == 11 and sel.parameters["quadrature"] == "common_grid"
        assert all(s["success"] for s in sel.starts)
    with capsys.disabled():
        for metric, (dt, sel) in out.items():
            print(f"\nM=16 {metric}: {dt:.1f} s, {sel.parameters['rate_evaluations']} rate calls")
    # 13 to 23 s on an idle i5-8259U; 80 to 93 s measured with the machine at load average 45
    assert max(dt for dt, _ in out.values()) < 600.0


def test_m16_single_start_is_quick_enough_for_the_default_suite():
    t0 = time.perf_counter()
    sel = optimise_symmetric(
        awgn_channel(16, 28.0, 0.02), 16, "bmd", 1024, 7, multistart_check=False
    )
    assert time.perf_counter() - t0 < 20.0
    assert len(sel.starts) == 1 and sel.claim.startswith("best of 1 starts")
