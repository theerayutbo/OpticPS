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
from dataclasses import replace

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
    DataLeakageError,
    estimate_channel,
    evaluate_menu,
    fixed_menu,
    optimise_symmetric,
    oracle_not_a_baseline,
    pair_bounds,
    select_distribution,
    simulate_acquisitions,
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


def best_fixed_on(order, metric, block_length, psnr_db, seed=3, menu=None):
    """best_fixed on simulated training acquisitions (the only accepted input)."""
    train, _ = simulate_acquisitions(psnr_db, order, 20000 * order // 4, seed, 2, 0)
    return adaptive.best_fixed(train, order, metric, block_length, menu), train


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
    assert sel.claim.startswith("global for the unquantised SMD objective over the constrained set")
    assert "q_j >= 1/n" in sel.claim and "on this channel estimate" in sel.claim
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
        if c["status"] == "infeasible":
            continue
        if c["direct"]:  # direct uniform: no matcher, so no composition and no loss
            assert c["kind"] == "uniform" and c["counts"] is None and c["matcher_loss"] == 0.0
            assert c["objective"] == pytest.approx(rate, abs=1e-12)
            continue
        assert c["matcher_loss"] == pytest.approx(independent_matcher_loss(p, 1024), abs=1e-12)
        assert c["objective"] == pytest.approx(rate - c["matcher_loss"], abs=1e-12)
        assert sum(c["counts"]) == 1024 and c["counts"] == c["counts"][::-1]
    json.dumps(sel.to_dict())  # fully serialisable
    assert sel.order == 8 and sel.p_outer is None and sel.lambda_value is None


@pytest.mark.parametrize("order", [4, 8, 16])
def test_uniform_is_the_direct_mapping_with_zero_matcher_loss(order):
    """frame.py direct_uniform sends bits straight onto labels: no composition, no loss."""
    channel = awgn_channel(order, 20.0, 0.02)
    problem = adaptive._Problem(channel, order, "smd", 1024)
    uniform = problem.evaluate(np.full(order, 1.0 / order), "u", "uniform")
    assert uniform["direct"] is True and uniform["matcher_loss"] == 0.0
    assert uniform["objective"] == uniform["rate"] and uniform["counts"] is None
    # the old accounting (CCDM on the uniform composition) would have charged a real loss
    ccdm_loss = ConstantCompositionMatcher.from_probabilities(
        np.full(order, 1.0 / order), 1024
    ).rate_loss
    assert ccdm_loss > 0.01
    # anything not exactly uniform pays the matcher
    half = np.array([1e-4, -1e-4] * (order // 4))
    near = np.full(order, 1.0 / order) + np.concatenate([half, half[::-1]])
    other = problem.evaluate(near, "n", "x")
    assert other["direct"] is False and other["matcher_loss"] > 0.0
    # evaluate_menu charges the menu's uniform member nothing and its shaped members the matcher
    rows = {r["name"]: r for r in evaluate_menu(channel, order, "smd", 1024)}
    assert rows[f"PAM{order}_Uniform"]["matcher_loss"] == 0.0
    assert all(r["matcher_loss"] > 0.0 for k, r in rows.items() if not k.endswith("Uniform"))


def test_legacy_m4_path_still_charges_its_uniform_the_ccdm_loss():
    """Documented limit of the committed v1.x result: select_distribution is not changed."""
    indices, received = simulate_training_capture(13.0, 40000, 42)
    sel = select_distribution(indices, received, "ref", "bmd", 1024, 0.02)
    loss = ConstantCompositionMatcher.from_probabilities(np.full(4, 0.25), 1024).rate_loss
    assert loss == pytest.approx(0.0146484375, abs=1e-12)  # 2 - 2033 / 1024
    uniform = next(c for c in sel.candidates if c["p_outer"] == 0.25)  # the uniform member
    assert uniform["matcher_loss"] == pytest.approx(loss, abs=1e-15)


def test_selection_picks_the_direct_uniform_when_it_is_best():
    channel = awgn_channel(8, 40.0, 0.01)  # shaping cannot help near saturation
    sel = optimise_symmetric(channel, 8, "smd", 1024, 2, multistart_check=False)
    # the uniform start may end exactly where it began; that endpoint is the same PMF
    assert sel.parameters["selected"] in ("uniform", "optimised_from:uniform")
    assert sel.probabilities == [1 / 8] * 8
    chosen = next(c for c in sel.candidates if c["name"] == sel.parameters["selected"])
    assert chosen["direct"] and sel.objective == chosen["objective"] == chosen["rate"]


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
    sel = optimise_symmetric(awgn_channel(8, 22.0, 0.02), 8, "smd", 16, 1, multistart_check=False)
    bad = [c for c in sel.candidates if c["status"] == "infeasible"]
    assert bad and sel.parameters["infeasible_candidates"] == len(bad)
    for c in bad:
        assert c["objective"] is None and c["counts"] is None
        assert "cannot represent" in c["reason"] and "DistributionMatcherError" in c["reason"]
    chosen = next(c for c in sel.candidates if c["name"] == sel.parameters["selected"])
    assert chosen["status"] == "ok" and chosen["objective"] == sel.objective
    # a block shorter than M leaves no box (q_j >= 1/n for every pair): refused, not a silent pick
    with pytest.raises(ValueError, match="box q_j >= 1/n is empty"):
        optimise_symmetric(awgn_channel(4, 14.0), 4, "smd", 2, 1, multistart_check=False)


def test_bad_arguments_are_rejected():
    ch = awgn_channel(4, 14.0)
    with pytest.raises(ValueError, match="even"):
        optimise_symmetric(ch, 4, "smd", 1023, 1)
    with pytest.raises(ValueError, match="metric"):
        optimise_symmetric(ch, 4, "gmi", 1024, 1)
    with pytest.raises(ValueError, match="M = 4, 8, 16"):
        pair_bounds(2, 1024)
    assert pair_bounds(8, 1024) == (1 / 1024, 0.5)  # the floor is 1/n, not 1/(4n)
    with pytest.raises(ValueError, match="8 levels"):
        optimise_symmetric(ch, 8, "smd", 1024, 1)


# --------------------------------------------------------------------------- documented numbers


def shaped_minus_direct_uniform(sel):
    uniform = next(c for c in sel.candidates if c["name"] == "uniform")
    shaped = [c for c in sel.candidates if c["status"] == "ok" and not c["direct"]]
    return max(c["objective"] for c in shaped) - uniform["objective"], uniform["objective"]


def test_m8_22db_numbers_in_the_note_with_the_uniform_at_zero_loss():
    """Equal-sigma peak-limited AWGN, n = 1024, seed 7 (docs/notes/mpam_adaptive_constraints.md)."""
    channel = awgn_channel(8, 22.0)
    expected = {  # metric: (continuous rate, selected objective, direct uniform objective)
        "smd": (1.99584, 1.96391, 1.95468),
        "bmd": (1.97325, 1.94119, 1.93579),
    }
    for metric, (cont, selected, uniform) in expected.items():
        sel = optimise_symmetric(channel, 8, metric, 1024, 7)
        assert sel.parameters["continuous_optimum"]["objective"] == pytest.approx(cont, abs=5e-6)
        assert sel.objective == pytest.approx(selected, abs=5e-6)
        margin, direct = shaped_minus_direct_uniform(sel)
        assert direct == pytest.approx(uniform, abs=5e-6) and margin > 0
        assert sel.objective - direct == pytest.approx(selected - uniform, abs=1e-5)
        # every start agrees to a measured 3.4e-13 bit and 2.7e-7 in q
        assert sel.parameters["agreement"]["max_objective_gap_bit"] < 1e-12
        assert sel.parameters["agreement"]["max_q_gap_to_best_start"] < 5e-7
        best = max(
            (r for r in evaluate_menu(channel, 8, metric, 1024) if r["status"] == "ok"),
            key=lambda r: r["objective"],
        )
        assert best["name"] == "PAM8_Uniform"  # best fixed is the direct uniform, not Outer_H288
        assert sel.objective - best["objective"] == pytest.approx(selected - uniform, abs=1e-5)


@pytest.mark.slow
def test_m16_28db_adaptive_loses_to_the_direct_uniform_and_selection_says_so():
    channel = awgn_channel(16, 28.0)
    for metric, uniform, shaped in (("smd", 2.78194, 2.75057), ("bmd", 2.75102, 2.71668)):
        sel = optimise_symmetric(channel, 16, metric, 1024, 7)
        margin, direct = shaped_minus_direct_uniform(sel)
        assert direct == pytest.approx(uniform, abs=5e-6)
        assert direct + margin == pytest.approx(shaped, abs=5e-6)
        assert margin == pytest.approx(shaped - uniform, abs=1e-5) and margin < -0.03
        assert sel.objective == direct and sel.probabilities == [1 / 16] * 16  # uniform wins
        assert sel.parameters["agreement"]["max_objective_gap_bit"] < 1e-12


# --------------------------------------------------------------------------- the floor 1/n


def mb_grid_best(sel):
    return max(
        c["objective"] for c in sel.candidates if c["kind"] == "mb_grid" and c["status"] == "ok"
    )


def endpoints_feasible(sel):
    ends = [c for c in sel.candidates if c["kind"] == "endpoint"]
    return sum(c["status"] == "ok" for c in ends), len(ends)


def test_floor_one_over_n_makes_endpoints_representable_at_m8():
    """With a floor of 1/(4n) the optimum at the floor quantised to a zero count and 11 of 11
    endpoints were infeasible over this sweep (n = 1024, equal-sigma AWGN); with 1/n none are."""
    for psnr in (8.0, 12.0, 18.0):
        sel = optimise_symmetric(awgn_channel(8, psnr), 8, "smd", 1024, 7)
        feasible, total = endpoints_feasible(sel)
        assert (feasible, total) == (11, 11)
        assert sel.parameters["infeasible_candidates"] <= 20  # only MB-grid points can be
        assert sel.objective > mb_grid_best(sel) + 0.02  # the fallback the old floor forced
        assert sel.parameters["floor_active_pairs"]  # the floor binds at low PSNR ...
        assert "active at pair(s)" in sel.claim and "q_j >= 1/n" in sel.claim
    # M = 8, 16 dB, BMD: 1.2652 against the MB-grid fallback 1.1545 (values computed here)
    sel = optimise_symmetric(awgn_channel(8, 16.0), 8, "bmd", 1024, 7)
    assert endpoints_feasible(sel) == (11, 11)
    assert sel.objective == pytest.approx(1.2652, abs=5e-5)
    assert mb_grid_best(sel) == pytest.approx(1.1545, abs=5e-5)
    assert sel.parameters["floor_active_pairs"] == [1, 2]


def test_floor_is_reported_inactive_when_the_optimum_is_interior():
    sel = optimise_symmetric(awgn_channel(8, 22.0), 8, "smd", 1024, 7)
    assert sel.parameters["floor_active_pairs"] == []
    assert "inactive at the continuous optimum" in sel.claim
    assert "over the constrained set q_j >= 1/n" in sel.claim


@pytest.mark.slow
def test_floor_one_over_n_makes_endpoints_representable_at_m16():
    for psnr, metric in ((10.0, "smd"), (16.0, "smd"), (22.0, "smd"), (22.0, "bmd")):
        sel = optimise_symmetric(awgn_channel(16, psnr), 16, metric, 1024, 7)
        feasible, total = endpoints_feasible(sel)
        assert feasible >= total - 1  # measured 11 of 11
        assert sel.objective > mb_grid_best(sel) + 0.003


# --------------------------------------------------------------------------- claim strings


def test_single_start_smd_claim_says_unquantised_and_names_the_channel_caveat():
    sel = optimise_symmetric(awgn_channel(8, 16.0), 8, "smd", 512, 1, multistart_check=False)
    assert "unquantised" in sel.claim and "this channel estimate" in sel.claim
    assert "one start only" in sel.claim and "not confirmed" in sel.claim
    assert "global for SMD by concavity" not in sel.claim  # the old, unqualified wording


def test_smd_starts_that_disagree_are_not_called_global(monkeypatch):
    real = adaptive._run_start
    calls = []

    def sabotaged(problem, q0):
        q, result = real(problem, q0)
        calls.append(1)
        if len(calls) == 3:  # one start reports a far-off point as its endpoint
            q = np.array([0.5 - 3 * problem.lower] + [problem.lower] * 3)
        return q, result

    monkeypatch.setattr(adaptive, "_run_start", sabotaged)
    sel = optimise_symmetric(awgn_channel(8, 16.0), 8, "smd", 512, 1)
    assert sel.parameters["agreement"]["max_objective_gap_bit"] > 1e-3
    assert sel.claim.startswith("best of 11 starts")
    assert "disagree" in sel.claim and "numerical failure" in sel.claim
    assert "global" not in sel.claim.split(";")[0] and "agree to" not in sel.claim
    assert "unquantised" in sel.claim


def test_agreeing_starts_state_their_measured_gap():
    sel = optimise_symmetric(awgn_channel(4, 14.0), 4, "smd", 512, 1)
    gap = sel.parameters["agreement"]["max_objective_gap_bit"]
    assert gap <= adaptive._AGREEMENT_RATE_TOL and sel.claim.startswith("global")
    assert f"{gap:.1e} bit" in sel.claim


# --------------------------------------------------------------------------- smooth fit, bounds


def test_bmd_is_fitted_as_the_unclipped_bmd_raw_and_reported_clipped():
    """Where BMD is below 0 the clipped value is a flat zero; the fit must use bmd_raw."""
    channel = awgn_channel(8, 0.0)
    problem = adaptive._Problem(channel, 8, "bmd", 1024)
    q = np.array([0.3, 0.2 / 3, 0.2 / 3, 0.2 / 3])  # a poor PMF at 0 dB
    p = symmetric_from_pairs(q)
    rates = gaussian_rates(p, channel.means, channel.sigmas, 8, quadrature="common_grid")
    assert rates.bmd_raw < -0.04 and rates.bmd == 0.0
    assert problem.smooth_rate(q) == rates.bmd_raw  # not the clipped 0
    assert problem.evaluate(p, "x", "x")["rate"] == 0.0  # the reported rate is clipped
    # a gradient start in the clipped region climbs only because the fit sees the raw value
    q_end, _ = adaptive._run_start(problem, q)
    assert problem.smooth_rate(q_end) > 0.04 and q_end[0] < 0.2
    sel = optimise_symmetric(channel, 8, "bmd", 1024, 1, multistart_check=False)
    assert sel.starts[0]["objective_metric"] == "bmd_raw"


def test_out_of_bounds_candidates_are_flagged_and_never_selected(monkeypatch):
    problem = adaptive._Problem(awgn_channel(4, 14.0), 4, "smd", 1024)
    below = np.array([0.4995, 0.0005, 0.0005, 0.4995])  # inner pair below 1/n = 0.000977
    assert problem.evaluate(below, "b", "x")["in_bounds"] is False
    assert problem.evaluate(np.full(4, 0.25), "u", "x")["in_bounds"] is True
    real = adaptive._Problem.evaluate

    def tempting(self, p, name, kind):
        record = real(self, p, name, kind)
        if kind == "mb_grid" and record["status"] == "ok":
            record["in_bounds"] = False
            record["objective"] += 10.0  # would win by far if bounds were ignored
        return record

    monkeypatch.setattr(adaptive._Problem, "evaluate", tempting)
    sel = optimise_symmetric(awgn_channel(4, 14.0), 4, "smd", 1024, 1, multistart_check=False)
    assert not sel.parameters["selected"].startswith("mb_")
    assert sel.objective < 5.0


def test_floor_active_selected_pairs_differs_from_the_continuous_report():
    """M = 16, n = 256, 22 dB SMD, one start: the continuous optimum sits at the floor on pairs
    2, 5, 6 but the selected candidate (the direct uniform) is above the floor everywhere."""
    sel = optimise_symmetric(awgn_channel(16, 22.0), 16, "smd", 256, 7, multistart_check=False)
    assert sel.parameters["floor_active_pairs"] == [2, 5, 6]
    assert sel.parameters["selected"] == "uniform"
    assert sel.parameters["floor_active_selected_pairs"] == []
    floor = 1.0 / 256
    q = sel.parameters["pair_probabilities"]  # of the selected candidate: uniform, 1/16 each
    assert [i for i, v in enumerate(q) if v <= floor + 1e-5] == []
    # a selected candidate that does sit at the floor is reported: M = 8, 12 dB SMD, n = 1024
    low = optimise_symmetric(awgn_channel(8, 12.0), 8, "smd", 1024, 7, multistart_check=False)
    q_low = low.parameters["pair_probabilities"]
    assert low.parameters["floor_active_selected_pairs"] == [
        i for i, v in enumerate(q_low) if v <= 1.0 / 1024 + 1e-5
    ]


def test_best_fixed_never_selects_an_out_of_bounds_menu_entry(monkeypatch):
    train, _ = simulate_acquisitions(14.0, 4, 8000, 3, 1, 0)
    real = adaptive._Problem.evaluate

    def tempting(self, p, name, kind):
        record = real(self, p, name, kind)
        if name == "PAM4_Fixed_Outer70":
            record["in_bounds"] = False
            record["objective"] += 10.0  # would win by far if bounds were ignored
        return record

    monkeypatch.setattr(adaptive._Problem, "evaluate", tempting)
    chosen = adaptive.best_fixed(train, 4, "bmd", 1024)
    assert chosen.name != "PAM4_Fixed_Outer70" and chosen.objective < 5.0
    oracle = oracle_not_a_baseline(awgn_channel(4, 14.0), 4, "bmd", 1024)
    assert oracle["oracle_not_a_baseline"]["name"] != "PAM4_Fixed_Outer70"
    only_bad = {"PAM4_Fixed_Outer70": fixed_menu(4)["PAM4_Fixed_Outer70"]}
    with pytest.raises(ValueError, match="in-bounds"):
        adaptive.best_fixed(train, 4, "bmd", 1024, only_bad)


# --------------------------------------------------------------------------- negative case


@pytest.mark.parametrize("psnr", [36.0, 40.0, 45.0])
def test_high_snr_pam16_direct_uniform_wins_because_every_composition_costs_more_than_the_gain(
    psnr,
):
    """Negative case, stated as measured: the unquantised gain of shaping over uniform is at most
    2.1e-4 bit here, while every non-uniform candidate is a quantised composition that pays a
    matcher loss. The direct uniform pays none, so it is selected. (An earlier text said the
    matcher loss exceeds the continuous gain; that compared against a uniform that was wrongly
    charged the same loss.)"""
    channel = awgn_channel(16, psnr, 0.02)
    sel = optimise_symmetric(channel, 16, "smd", 1024, 1, multistart_check=False)
    uniform = next(c for c in sel.candidates if c["name"] == "uniform")
    assert uniform["direct"] and uniform["matcher_loss"] == 0.0
    gain = sel.parameters["continuous_optimum"]["objective"] - uniform["rate"]
    assert -1e-9 <= gain < 5e-4
    shaped = [c for c in sel.candidates if c["status"] == "ok" and not c["direct"]]
    assert shaped and all(c["matcher_loss"] > 10 * max(gain, 1e-4) for c in shaped)
    assert all(c["objective"] < uniform["objective"] - 1e-3 for c in shaped)
    assert sel.parameters["selected"] == "uniform" or sel.objective == uniform["objective"]
    assert np.abs(np.array(sel.probabilities) - 1 / 16).sum() < 1e-9  # exactly uniform


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
    chosen, train = best_fixed_on(4, "bmd", 1024, 14.0)  # outer-heavy territory
    table = {r["name"]: r["objective"] for r in chosen.table}
    assert chosen.name == max(table, key=table.get)
    assert chosen.selected_on.startswith(
        "training acquisitions (content hash recomputed, split label declared)"
    )
    assert "checked" not in chosen.selected_on
    assert all(a.id.id in chosen.selected_on for a in train)
    assert chosen.objective == table[chosen.name]
    assert "oracle_not_a_baseline" not in json.dumps(chosen.to_dict())
    assert chosen.name == "PAM4_Fixed_Outer70"  # derived from the numbers, see the table
    assert table["PAM4_Fixed_Outer70"] > table["PAM4_Uniform"] > table["PAM4_Fixed_PS70"]
    # a different evaluation channel has a different best member; the baseline does not follow it
    oracle = oracle_not_a_baseline(awgn_channel(4, 30.0), 4, "bmd", 1024)
    assert list(oracle) == ["oracle_not_a_baseline"]
    assert oracle["oracle_not_a_baseline"]["name"] == "PAM4_Uniform"
    assert "not a baseline" in oracle["oracle_not_a_baseline"]["selected_on"]
    assert adaptive.best_fixed(train, 4, "bmd", 1024).name == chosen.name  # unaffected


def test_best_fixed_provenance_is_checked_not_asserted():
    """A channel cannot be passed, a test-split acquisition is refused and a wrong digest too."""
    train, test = simulate_acquisitions(14.0, 4, 8000, 3, 2, 1)
    with pytest.raises(DataLeakageError, match="not training"):
        adaptive.best_fixed([train[0], test[0]], 4, "bmd", 1024)
    forged = replace(train[0], id=replace(train[0].id, content_sha256="a" * 64))
    with pytest.raises(DataLeakageError, match="does not match its samples"):
        adaptive.best_fixed([forged], 4, "bmd", 1024)
    with pytest.raises(ValueError, match="At least one"):
        adaptive.best_fixed([], 4, "bmd", 1024)
    with pytest.raises((TypeError, AttributeError)):
        adaptive.best_fixed(awgn_channel(4, 14.0), 4, "bmd", 1024)  # type: ignore[arg-type]
    # the oracle path never carries the training label
    label = oracle_not_a_baseline(awgn_channel(4, 14.0), 4, "bmd", 1024)["oracle_not_a_baseline"]
    assert "training" not in label["selected_on"]


def test_best_fixed_logs_infeasible_members_and_excludes_them():
    rows = evaluate_menu(awgn_channel(8, 22.0), 8, "smd", 8)
    assert any(r["status"] == "infeasible" for r in rows)
    shaped_only = {k: v for k, v in fixed_menu(8).items() if not k.endswith("Uniform")}
    train, _ = simulate_acquisitions(22.0, 8, 20000, 3, 1, 0)
    with pytest.raises(ValueError, match="No feasible"):
        adaptive.best_fixed(train, 8, "smd", 8, shaped_only)  # no composition fits n = 8


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
