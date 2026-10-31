"""Independent checks of the PAM-M rate computations.

Every reference here is derived separately from src/opticps/optimization/rates.py:
the closed-form symbol error rate of a uniform minimum-distance detector, a
binary-AWGN capacity integral, a trapezoid integrator and an adaptive Gauss-Kronrod
integrator (scipy.integrate.quad_vec), each with its own posteriors and hand-written
Gray tables. None of them uses the production integrators.
"""

import math
import warnings

import numpy as np
import pytest
from scipy import integrate
from scipy.stats import norm

from opticps.modulation.pam import label_bits
from opticps.optimization import rates as rates_module
from opticps.optimization.rates import (
    achievable_rates,
    average_snr,
    default_nodes,
    gaussian_rates,
    noise_sigma_from_psnr_db,
    optimal_outer_probability,
    psnr_for_rate,
)
from opticps.shaping.distributions import symmetric_pam4

ORDERS = (2, 4, 8, 16)


def uniform(order: int) -> np.ndarray:
    return np.full(order, 1.0 / order)


def mb_pmf(order: int, lam: float) -> np.ndarray:
    """Symmetric exp(-lam x^2) PMF on centred levels: lam > 0 inner-heavy, < 0 outer-heavy."""
    x = np.arange(order) - (order - 1) / 2
    w = np.exp(-lam * x**2)
    return w / w.sum()


# --- closed-form symbol error rate ---------------------------------------------------


def simulated_ser(order: int, psnr_db: float, n: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    sigma = (order - 1) / 10 ** (psnr_db / 20)  # written out, not taken from rates.py
    x = rng.integers(0, order, n)
    y = x + sigma * rng.standard_normal(n)
    decided = np.clip(np.rint(y), 0, order - 1)
    return float(np.mean(decided != x))


def closed_form_ser(order: int, sigma: float) -> float:
    return 2 * (1 - 1 / order) * float(norm.sf(1 / (2 * sigma)))


@pytest.mark.parametrize(("order", "psnr_db"), [(2, 9.0), (8, 24.0), (16, 30.0)])
def test_uniform_minimum_distance_ser_matches_closed_form(order, psnr_db):
    n = 200_000
    sigma = noise_sigma_from_psnr_db(psnr_db, order)
    expected = closed_form_ser(order, sigma)
    tolerance = 4 * math.sqrt(expected * (1 - expected) / n)
    observed = simulated_ser(order, psnr_db, n, seed=2024 + order)
    assert abs(observed - expected) < tolerance
    # A 6 dB error in the PSNR-to-sigma map (sigma off by a factor 2 either way) is caught.
    for wrong_sigma in (2 * sigma, sigma / 2):
        assert abs(observed - closed_form_ser(order, wrong_sigma)) > tolerance


def test_pam2_at_12_db_has_ser_0233():
    sigma = noise_sigma_from_psnr_db(12.0, 2)
    assert closed_form_ser(2, sigma) == pytest.approx(0.0233, abs=5e-5)
    n = 200_000
    observed = simulated_ser(2, 12.0, n, seed=12)
    assert abs(observed - 0.0233) < 4 * math.sqrt(0.0233 * (1 - 0.0233) / n)
    # Taking the PSNR as 6 dB higher or lower would give a visibly different SER.
    assert closed_form_ser(2, sigma * 2) > 0.1
    assert closed_form_ser(2, sigma / 2) < 1e-4


def test_sigma_follows_the_peak_to_peak_definition():
    for order in ORDERS:
        for db in (0.0, 12.0, 30.0):
            sigma = noise_sigma_from_psnr_db(db, order)
            assert (order - 1) ** 2 / sigma**2 == pytest.approx(10 ** (db / 10), rel=1e-12)
    assert noise_sigma_from_psnr_db(12.0) == noise_sigma_from_psnr_db(12.0, 4)
    with pytest.raises(ValueError):
        noise_sigma_from_psnr_db(12.0, 6)


# --- binary AWGN capacity --------------------------------------------------------------


def binary_awgn_mutual_information(sigma: float) -> float:
    """I(X;Y) for equiprobable inputs at 0 and 1, from h(Y) - h(N) by adaptive quadrature."""

    def neg_f_log_f(y: float) -> float:
        a = -((y) ** 2) / (2 * sigma**2)
        b = -((y - 1) ** 2) / (2 * sigma**2)
        log_f = np.logaddexp(a, b) - math.log(2 * sigma * math.sqrt(2 * math.pi))
        return float(-math.exp(log_f) * log_f / math.log(2))

    lo, hi = -14 * sigma, 1 + 14 * sigma
    h_y, _ = integrate.quad(neg_f_log_f, lo, hi, points=[0.0, 0.5, 1.0], limit=400, epsabs=1e-13)
    h_noise = 0.5 * math.log2(2 * math.pi * math.e * sigma**2)
    return h_y - h_noise


@pytest.mark.parametrize("psnr_db", [-3.0, 0.0, 6.0, 12.0, 18.0])
def test_pam2_matches_binary_awgn_capacity_integral(psnr_db):
    reference = binary_awgn_mutual_information(noise_sigma_from_psnr_db(psnr_db, 2))
    r = achievable_rates([0.5, 0.5], psnr_db)
    assert abs(r.smd - reference) < 1e-6
    assert abs(r.bmd - reference) < 1e-6


@pytest.mark.parametrize("psnr_db", [-6.0, 0.0, 5.0, 12.0, 25.0])
@pytest.mark.parametrize("pmf", [[0.5, 0.5], [0.3, 0.7]])
def test_one_bit_alphabet_has_bmd_equal_to_smd(pmf, psnr_db):
    r = achievable_rates(pmf, psnr_db)
    assert r.bmd_raw == pytest.approx(r.smd, abs=1e-12)


# --- embeddings ------------------------------------------------------------------------


@pytest.mark.parametrize("order", [4, 8, 16])
@pytest.mark.parametrize("psnr_db", [3.0, 9.0, 15.0, 21.0])
@pytest.mark.parametrize("pair", [(0.5, 0.5), (0.35, 0.65)])
def test_outer_pair_embeds_pam2(order, psnr_db, pair):
    """Indices {0, M-1} differ only in the first Gray bit, so BMD also matches PAM2."""
    pmf = np.zeros(order)
    pmf[[0, order - 1]] = pair
    assert label_bits(order)[0].tolist()[1:] == label_bits(order)[order - 1].tolist()[1:]
    big = achievable_rates(pmf, psnr_db, nodes=240)  # same rule on both sides
    small = achievable_rates(list(pair), psnr_db, nodes=240)
    assert big.smd == pytest.approx(small.smd, abs=1e-9)
    assert big.bmd_raw == pytest.approx(small.bmd_raw, abs=1e-9)
    assert big.entropy == pytest.approx(small.entropy, abs=1e-12)


@pytest.mark.parametrize("psnr_db", [4.0, 12.0, 20.0, 28.0])
def test_pam4_on_pam16_indices_has_equal_smd_but_not_bmd(psnr_db):
    pam4 = np.array([0.1, 0.4, 0.4, 0.1])
    pam16 = np.zeros(16)
    pam16[[0, 5, 10, 15]] = pam4  # levels 0, 5, 10, 15 are 5 x {0, 1, 2, 3}
    a = achievable_rates(pam16, psnr_db, nodes=240)  # same rule on both sides
    b = achievable_rates(pam4, psnr_db, nodes=240)
    assert a.smd == pytest.approx(b.smd, abs=1e-9)
    # The PAM16 Gray labels of these four levels (0000, 0111, 1111, 1000) are not the
    # PAM4 Gray labels (00, 01, 11, 10), and the bit metric depends on the labelling, so
    # the bit-metric rate is lower here. This is a labelling effect, not an error.
    assert a.bmd_raw < b.bmd_raw - 5e-5


# --- integrator independence -----------------------------------------------------------


# Gray labels written out by hand (binary-reflected), not taken from the package.
GRAY_TABLES = {
    2: ["0", "1"],
    4: ["00", "01", "11", "10"],
    8: ["000", "001", "011", "010", "110", "111", "101", "100"],
    16: [
        "0000", "0001", "0011", "0010", "0110", "0111", "0101", "0100",
        "1100", "1101", "1111", "1110", "1010", "1011", "1001", "1000",
    ],
}  # fmt: skip


def reference_rates(
    pmf: np.ndarray, means: np.ndarray, sigmas: np.ndarray, points: int = 2**15
) -> dict[str, float]:
    """Trapezoid integration over the mixture with its own posteriors and Gray tables.

    Returns smd, bmd_raw, and the GMI at s = 1 of two bit metrics: `gmi_over_px`
    (q = prod_k P(b_k|y) / P_X(x)) and `gmi_plain` (q = prod_k P(b_k|y)). Requires
    P_X(x) > 0 for every level (the metric divides by it).
    """
    order = len(pmf)
    table = np.array([[int(c) for c in word] for word in GRAY_TABLES[order]])
    y = np.linspace((means - 12 * sigmas).min(), (means + 12 * sigmas).max(), points)
    log_q = np.full((points, order), -np.inf)
    for i in np.flatnonzero(pmf > 0):
        log_q[:, i] = (
            math.log(pmf[i])
            - (y - means[i]) ** 2 / (2 * sigmas[i] ** 2)
            - math.log(sigmas[i] * math.sqrt(2 * math.pi))
        )
    peak = log_q.max(axis=1)
    mass = np.exp(log_q - peak[:, None])
    posterior = mass / mass.sum(axis=1, keepdims=True)
    joint = np.exp(log_q)

    def expect(f: np.ndarray) -> float:
        """sum_x integral of p(x, y) f(x, y) dy, in bits."""
        g = np.where(joint > 0, joint * f, 0.0).sum(axis=1)
        return float(np.trapezoid(g, y)) / math.log(2)

    with np.errstate(divide="ignore", invalid="ignore"):
        log_post = np.log(posterior)
        log_bits = np.zeros((points, order))
        for k in range(table.shape[1]):
            for bit in (0, 1):
                members = np.flatnonzero(table[:, k] == bit)
                log_bits[:, members] += np.log(posterior[:, members].sum(axis=1))[:, None]
        entropy = float(-(pmf[pmf > 0] * np.log2(pmf[pmf > 0])).sum())

        def gmi(q: np.ndarray) -> float:
            """GMI at s = 1 of a decoding metric q(x, y), shape (points, order).

            The denominator sum_x' P_X(x') q(x', y) is summed explicitly for each metric.
            """
            denominator = (pmf[None, :] * q).sum(axis=1)
            return expect(np.log(q) - np.log(denominator)[:, None])

        q_over_px = np.exp(log_bits) / pmf[None, :]  # prod_k P(b_k|y) / P_X(x)
        q_plain = np.exp(log_bits)  # prod_k P(b_k|y)
        return {
            "smd": entropy + expect(log_post),
            "bmd_raw": entropy + expect(log_bits),
            "gmi_over_px": gmi(q_over_px),
            "gmi_plain": gmi(q_plain),
        }


def equal_sigma_reference(pmf: np.ndarray, psnr_db: float) -> dict[str, float]:
    order = len(pmf)
    sigma = (order - 1) / 10 ** (psnr_db / 20)
    return reference_rates(pmf, np.arange(order, dtype=float), np.full(order, sigma))


def sweep_pmfs() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    return {
        "uniform": uniform(16),
        "inner_heavy": mb_pmf(16, 0.05),
        "outer_heavy": mb_pmf(16, -0.02),
        "random": rng.dirichlet(np.ones(16)),
    }


@pytest.mark.parametrize("name", list(sweep_pmfs()))
def test_default_quadrature_matches_trapezoid_at_m16(name):
    pmf = sweep_pmfs()[name]
    for psnr_db in range(8, 31, 2):
        ref = equal_sigma_reference(pmf, psnr_db)
        smd, bmd_raw = ref["smd"], ref["bmd_raw"]
        for nodes in (120, None):  # 120 as originally specified, and the M=16 default
            r = achievable_rates(pmf, psnr_db, nodes=nodes)
            assert abs(r.smd - smd) < 1e-6
            assert abs(r.bmd_raw - bmd_raw) < 1e-6


def test_default_nodes_are_order_dependent_and_pam4_stays_120():
    assert default_nodes(4) == 120
    assert default_nodes(16) == 240
    assert achievable_rates(uniform(4), 12.0).nodes == 120
    assert achievable_rates(uniform(16), 12.0).nodes == default_nodes(16)
    assert achievable_rates(uniform(16), 12.0, nodes=77).nodes == 77


@pytest.mark.parametrize("order", [2, 8, 16])
def test_default_quadrature_has_converged(order):
    """Equal sigma: the default against a 320-node rule, plus the 120-node error.

    120 nodes are 1.9e-8 to 4.1e-8 from converged (M = 4 is the worst, and keeps 120 on
    purpose); the defaults for M != 4 are within 1e-9 (measured 4.2e-10).
    """
    rng = np.random.default_rng(order)
    pmfs = [uniform(order), mb_pmf(order, 0.05), rng.dirichlet(np.ones(order))]
    worst_120 = 0.0
    for pmf in pmfs:
        for psnr_db in range(8, 31, 2):
            ref = achievable_rates(pmf, psnr_db, nodes=320)
            r = achievable_rates(pmf, psnr_db)
            assert abs(r.smd - ref.smd) < 1e-9
            assert abs(r.bmd_raw - ref.bmd_raw) < 1e-9
            low = achievable_rates(pmf, psnr_db, nodes=120)
            worst_120 = max(worst_120, abs(low.smd - ref.smd), abs(low.bmd_raw - ref.bmd_raw))
    assert worst_120 < 1e-6  # still far inside the 1e-6 integrator tolerance


def test_oversized_quadrature_rule_is_rejected():
    with pytest.raises(ValueError):
        achievable_rates(uniform(4), 10.0, nodes=1)
    with np.errstate(all="ignore"), pytest.raises(ValueError):
        achievable_rates(uniform(4), 10.0, nodes=1000)  # numpy's rule overflows


@pytest.mark.parametrize("order", [8, 16])
@pytest.mark.parametrize("psnr_db", [8.0, 14.0, 20.0, 28.0])
def test_rates_match_independent_integrator_with_hand_written_gray_tables(order, psnr_db):
    # A swap of two Gray labels at M = 8 changes bmd by 0.13 bit; the SMD does not see it.
    for pmf in (uniform(order), mb_pmf(order, 0.05), mb_pmf(order, -0.02)):
        ref = equal_sigma_reference(pmf, psnr_db)
        r = achievable_rates(pmf, psnr_db)
        assert abs(r.smd - ref["smd"]) < 1e-8
        assert abs(r.bmd_raw - ref["bmd_raw"]) < 1e-8


def test_package_gray_labels_equal_the_hand_written_tables():
    for order, words in GRAY_TABLES.items():
        assert ["".join(map(str, row)) for row in label_bits(order).tolist()] == words


def unequal_sigmas(order: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    pmf = rng.dirichlet(np.ones(order) * 2)
    sigma = noise_sigma_from_psnr_db(18.0, order) * rng.uniform(0.7, 1.4, order)
    return pmf, np.arange(order, dtype=float), sigma


def quad_reference(pmf: np.ndarray, means: np.ndarray, sigmas: np.ndarray) -> dict[str, float]:
    """smd and bmd_raw by adaptive Gauss-Kronrod (scipy quad_vec) with hand-written Gray tables.

    A different rule from both production integrators: adaptive, not fixed-node. The
    integrand is the vector (p(x, y) log P(x|y), p(x, y) sum_k log P(b_k|y)) summed over x
    on one y axis, with its own posteriors and break points at mean +- {0, 1, 3, 6} sd.
    """
    order = len(pmf)
    table = np.array([[int(c) for c in word] for word in GRAY_TABLES[order]])
    live = np.flatnonzero(pmf > 0)

    def integrand(y: float) -> np.ndarray:
        log_q = np.full(order, -np.inf)
        log_q[live] = (
            np.log(pmf[live])
            - (y - means[live]) ** 2 / (2 * sigmas[live] ** 2)
            - np.log(sigmas[live] * math.sqrt(2 * math.pi))
        )
        total = np.log(np.exp(log_q - log_q.max()).sum()) + log_q.max()
        log_post = log_q - total
        log_bits = np.zeros(order)
        for k in range(table.shape[1]):
            for bit in (0, 1):
                members = table[:, k] == bit
                member_mass = np.exp(log_post[members]).sum()
                log_bits[members] += math.log(max(member_mass, 1e-300))
        weight = np.exp(log_q[live])
        return np.array([(weight * log_post[live]).sum(), (weight * log_bits[live]).sum()])

    lo = float((means[live] - 12 * sigmas[live]).min())
    hi = float((means[live] + 12 * sigmas[live]).max())
    breaks = sorted(
        {
            float(b)
            for t in (-6, -3, -1, 0, 1, 3, 6)
            for b in means[live] + t * sigmas[live]
            if lo < b < hi
        }
    )
    value, _ = integrate.quad_vec(
        integrand, lo, hi, epsabs=1e-13, epsrel=0, limit=2000, points=breaks, norm="max"
    )
    entropy = float(-(pmf[live] * np.log2(pmf[live])).sum())
    return {
        "smd": entropy + float(value[0]) / math.log(2),
        "bmd_raw": entropy + float(value[1]) / math.log(2),
    }


def sigma_pattern(
    order: int, psnr_db: float, low: float, high: float, pattern: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """PMF, levels and per-level sigma with a sigma ratio spanning exactly [low, high].

    Patterns 0-3 draw log-uniform factors with the extremes forced onto two random levels;
    pattern 4 ramps the sigma up with the level, pattern 5 ramps it down. The base is the
    equal-sigma PSNR sigma, so the spread is high / low.
    """
    rng = np.random.default_rng(1000 * order + pattern)
    factors = np.exp(rng.uniform(math.log(low), math.log(high), order))
    i, j = rng.choice(order, 2, replace=False)
    factors[i], factors[j] = low, high
    if pattern == 4:
        factors = np.geomspace(low, high, order)
    elif pattern == 5:
        factors = np.geomspace(high, low, order)
    pmf = rng.dirichlet(np.ones(order) * 2)
    sigma = noise_sigma_from_psnr_db(psnr_db, order) * factors
    return pmf, np.arange(order, dtype=float), sigma


# (low, high) sigma-factor ranges: sigma spread max/min = 2, 4, 9, 16, 64.
SIGMA_RANGES = [(0.7, 1.4), (0.5, 2.0), (1 / 3, 3.0), (0.25, 4.0), (0.125, 8.0)]

# Common grid against the adaptive reference. Measured worst disagreement (SMD and bmd_raw)
# over M = 4, 8, 16, the five ranges above, 8-30 dB in 2 dB steps and six sigma patterns
# (1080 cases): 1.04e-13 (M = 4, spread 4); per M and spread 1e-15 to 1e-13. The reference
# itself is only converged to its epsabs of 1e-13. The tolerance 1e-11 is 100 times the
# measured worst and 1e-8 times the legacy Gauss-Hermite error at the same spreads.
COMMON_GRID_TOL = 1e-11


@pytest.mark.parametrize("order", [4, 8, 16])
@pytest.mark.parametrize(("low", "high"), SIGMA_RANGES)
def test_common_grid_matches_adaptive_reference_at_every_spread(order, low, high):
    for psnr_db in (8.0, 19.0, 30.0):
        for pattern in (0, 4):  # a random pattern and an ascending sigma ramp
            pmf, means, sigmas = sigma_pattern(order, psnr_db, low, high, pattern)
            ref = quad_reference(pmf, means, sigmas)
            r = gaussian_rates(pmf, means, sigmas, quadrature="common_grid")
            assert r.quadrature == "common_grid"
            assert r.sigma_spread == pytest.approx(high / low, rel=1e-12)
            assert abs(r.smd - ref["smd"]) < COMMON_GRID_TOL
            assert abs(r.bmd_raw - ref["bmd_raw"]) < COMMON_GRID_TOL


def test_common_grid_is_an_integral_of_the_whole_joint_density():
    pmf, means, sigmas = sigma_pattern(16, 20.0, 0.125, 8.0, 5)
    ref = quad_reference(pmf, means, sigmas)
    r = gaussian_rates(pmf, means, sigmas, quadrature="common_grid")
    # Mutation guard: dropping the sd-scaled panels or the +-12 sd range moves the result.
    assert abs(r.smd - ref["smd"]) < COMMON_GRID_TOL
    assert r.nodes > 1000  # y points actually used, recorded in `nodes`
    narrow = rates_module._common_grid(pmf, means, sigmas, sd_steps=np.zeros(1))
    assert narrow[0].size < r.nodes / 5  # panels at the means alone are far fewer


def test_common_grid_rejects_a_grid_that_misses_probability_mass():
    # Panels at the means only (no sd-scaled edges) lose most of the mass: the guard raises.
    pmf, means, sigmas = sigma_pattern(16, 20.0, 0.125, 8.0, 5)
    with pytest.raises(ValueError, match="not 1"):
        rates_module._conditional_entropies_common_grid(
            pmf, means, sigmas, label_bits(16), sd_steps=np.zeros(1)
        )


def test_common_grid_with_zero_mass_levels_matches_reference():
    pmf = np.array([0.0, 0.4, 0.0, 0.2, 0.1, 0.0, 0.3, 0.0])
    means = np.arange(8.0)
    sigmas = noise_sigma_from_psnr_db(16.0, 8) * np.geomspace(0.4, 2.5, 8)
    ref = quad_reference(pmf, means, sigmas)
    r = gaussian_rates(pmf, means, sigmas)
    assert r.quadrature == "common_grid"
    assert abs(r.smd - ref["smd"]) < COMMON_GRID_TOL
    assert abs(r.bmd_raw - ref["bmd_raw"]) < COMMON_GRID_TOL


@pytest.mark.parametrize("order", [2, 4, 8, 16])
def test_common_grid_agrees_with_gauss_hermite_at_equal_sigma(order):
    # Equal sigma, 320-node Gauss-Hermite (converged to about 4e-10 at M != 4).
    for pmf in (uniform(order), mb_pmf(order, 0.05)):
        for psnr_db in (8.0, 20.0, 30.0):
            grid = achievable_rates(pmf, psnr_db, quadrature="common_grid")
            ghq = achievable_rates(pmf, psnr_db, nodes=320, quadrature="gauss_hermite")
            assert abs(grid.smd - ghq.smd) < 1e-9
            assert abs(grid.bmd_raw - ghq.bmd_raw) < 1e-9


def test_auto_routing_and_recorded_fields():
    equal = np.full(8, 0.6)
    pmf, means = mb_pmf(8, 0.05), np.arange(8.0)
    r = gaussian_rates(pmf, means, equal)
    assert (r.quadrature, r.nodes, r.sigma_spread) == ("gauss_hermite", 240, 1.0)
    # Equal-sigma M != 4 numbers do not change: auto is bit-identical to forced GH.
    assert r == gaussian_rates(pmf, means, equal, quadrature="gauss_hermite")
    # A spread of 1 + 1e-13 is treated as equal; 1 + 1e-11 is not.
    nearly = equal.copy()
    nearly[3] = 0.6 * (1 + 1e-13)
    assert gaussian_rates(pmf, means, nearly).quadrature == "gauss_hermite"
    nearly[3] = 0.6 * (1 + 1e-11)
    assert gaussian_rates(pmf, means, nearly).quadrature == "common_grid"
    for order in (2, 8, 16):
        p, m, s = sigma_pattern(order, 18.0, 0.7, 1.4, 1)
        auto = gaussian_rates(p, m, s)
        assert auto.quadrature == "common_grid" and auto.sigma_spread == pytest.approx(2.0)
        assert auto == gaussian_rates(p, m, s, quadrature="common_grid")
    # M = 4 stays on the legacy kernel for every spread, and equals it exactly.
    p, m, s = sigma_pattern(4, 18.0, 0.7, 1.4, 1)
    legacy = gaussian_rates(p, m, s)
    assert (legacy.quadrature, legacy.nodes) == ("gauss_hermite", 120)
    nodes_x, weights = rates_module._quadrature(120)
    cx, cb = rates_module._conditional_entropies_direct(p, m, s, label_bits(4), weights, nodes_x)
    h = float(-(p * np.log2(p)).sum())
    assert (legacy.smd, legacy.bmd_raw) == (h - cx, h - cb)
    # ... unless the common grid is forced.
    forced = gaussian_rates(p, m, s, quadrature="common_grid")
    assert forced.quadrature == "common_grid"
    assert abs(forced.smd - quad_reference(p, m, s)["smd"]) < COMMON_GRID_TOL
    with pytest.raises(ValueError):
        gaussian_rates(p, m, s, nodes=240, quadrature="common_grid")
    with pytest.raises(ValueError):
        gaussian_rates(p, m, s, quadrature="trapezoid")
    assert achievable_rates(uniform(4), 12.0, quadrature="common_grid").quadrature == "common_grid"
    assert psnr_for_rate(uniform(8), 1.5, quadrature="common_grid") == pytest.approx(
        psnr_for_rate(uniform(8), 1.5), abs=1e-3
    )


def no_warning(*args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return gaussian_rates(*args, **kwargs)


def test_pam4_legacy_warns_above_the_spread_threshold_and_not_below():
    threshold = rates_module._GH_SPREAD_THRESHOLD
    assert threshold == 3.0
    for spread in (1.005, 2.0, 2.99):  # 1.005 is the committed-path size
        p, m, s = sigma_pattern(4, 12.0, spread**-0.5, spread**0.5, 2)
        r = no_warning(p, m, s)
        assert r.quadrature == "gauss_hermite" and r.sigma_spread == pytest.approx(spread)
    for spread in (3.01, 4.0, 9.0, 64.0):
        p, m, s = sigma_pattern(4, 12.0, spread**-0.5, spread**0.5, 2)
        with pytest.warns(UserWarning, match="unreliable") as caught:
            r = gaussian_rates(p, m, s)
        assert r.quadrature == "gauss_hermite"  # still the legacy result, never silent
        text = str(caught[0].message)
        assert f"{spread:.4g}" in text and "1e-4" in text and "common_grid" in text
        assert "3.4" in text and "bit at spread" in text
        # warning is attributed to the caller, not to rates.py
        assert caught[0].filename == __file__
    # The measured error quoted at spread 4 is the table entry for spread 4.
    p, m, s = sigma_pattern(4, 12.0, 0.5, 2.0, 2)
    with pytest.warns(UserWarning, match=r"3\.5e-04 bit at spread 4"):
        gaussian_rates(p, m, s)
    # The common grid never warns, at any spread and any order.
    for order in (4, 8, 16):
        p, m, s = sigma_pattern(order, 12.0, 0.125, 8.0, 2)
        assert no_warning(p, m, s, quadrature="common_grid").quadrature == "common_grid"
    p, m, s = sigma_pattern(8, 12.0, 0.125, 8.0, 2)
    assert no_warning(p, m, s).quadrature == "common_grid"  # M = 8 auto routes to the grid
    # Forced Gauss-Hermite above the threshold at M != 4 warns as well.
    with pytest.warns(UserWarning, match="unreliable"):
        gaussian_rates(p, m, s, quadrature="gauss_hermite")
    # Equal sigma never warns.
    assert no_warning(uniform(4), np.arange(4.0), np.full(4, 0.4)).sigma_spread == 1.0


def test_the_pam4_warning_threshold_sits_below_the_1e_4_crossing():
    """Legacy 120-node PAM4 error against the independent adaptive reference.

    Measured worst (8, 18, 30 dB, six patterns) 2.3e-5 at spread 3 and 2.0e-4 at spread 4; the
    first spread with an error above 1e-4 is 3.4 on the wider 0-45 dB, 26 pattern scan.
    """
    worst = {}
    for spread in (3.0, 4.0):
        errors = []
        for psnr_db in (8.0, 18.0, 30.0):
            for pattern in range(6):
                p, m, s = sigma_pattern(4, psnr_db, spread**-0.5, spread**0.5, pattern)
                ref = quad_reference(p, m, s)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    r = gaussian_rates(p, m, s, quadrature="gauss_hermite")
                errors.append(max(abs(r.smd - ref["smd"]), abs(r.bmd_raw - ref["bmd_raw"])))
        worst[spread] = max(errors)
    assert worst[3.0] < 1e-4  # at the threshold the legacy path is inside 1e-4
    assert worst[4.0] > 1e-4  # a little above it, it is not
    assert worst[4.0] > 3 * worst[3.0]


@pytest.mark.parametrize("order", [2, 4, 8, 16])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_default_with_per_level_sigma_matches_adaptive_reference(order, seed):
    """Default routing with sigma factors in 0.7-1.4 (spreads 1.08 to 1.97 for these seeds).

    M != 4 goes to the common grid: measured worst 6.2e-14 over these cases, tolerance
    1e-11 (the common-grid tolerance). M = 4 stays on the legacy 120-node rule, whose
    measured worst here is 5.5e-9 (3 PMFs at spreads up to 1.7), so its tolerance is 2e-8,
    not tighter; at spread 2 the legacy worst is 1.0e-6 over 8-30 dB and six patterns.
    """
    pmf, means, sigmas = unequal_sigmas(order, seed)
    ref = quad_reference(pmf, means, sigmas)
    r = gaussian_rates(pmf, means, sigmas)
    tolerance = 2e-8 if order == 4 else COMMON_GRID_TOL
    assert r.quadrature == ("gauss_hermite" if order == 4 else "common_grid")
    assert abs(r.smd - ref["smd"]) < tolerance
    assert abs(r.bmd_raw - ref["bmd_raw"]) < tolerance


def test_direct_and_log_kernels_agree_with_unequal_sigma_on_pam4():
    nodes_x, weights = rates_module._quadrature(120)
    pmf, means, sigmas = unequal_sigmas(4, 9)
    labels = label_bits(4)
    direct = rates_module._conditional_entropies_direct(
        pmf, means, sigmas, labels, weights, nodes_x
    )
    log = rates_module._conditional_entropies_log(pmf, means, sigmas, labels, weights, nodes_x)
    assert direct == pytest.approx(log, abs=1e-12)


@pytest.mark.parametrize("psnr_db", [6.0, 14.0, 20.0])
def test_bmd_raw_is_the_gmi_of_the_px_normalised_bit_metric_only(psnr_db):
    pmf = mb_pmf(8, 0.1)
    ref = equal_sigma_reference(pmf, psnr_db)  # denominators summed explicitly per metric
    r = achievable_rates(pmf, psnr_db, nodes=320)
    # H(X) - sum_k H(B_k|Y) is the GMI at s = 1 of q = prod_k P(b_k|y) / P_X(x) ...
    assert ref["gmi_over_px"] == pytest.approx(ref["bmd_raw"], abs=1e-9)
    assert r.bmd_raw == pytest.approx(ref["gmi_over_px"], abs=1e-8)
    # ... and not of q = prod_k P(b_k|y), which differs for a shaped PMF.
    assert abs(ref["gmi_plain"] - r.bmd_raw) > 1e-3
    uniform_ref = equal_sigma_reference(uniform(8), psnr_db)
    assert uniform_ref["gmi_plain"] == pytest.approx(uniform_ref["bmd_raw"], abs=1e-9)


def test_gmi_values_quoted_in_the_provenance_note():
    """M = 8, exp(-0.1 x^2), 20 dB: 1.43647 for q / P_X and 1.40726 for plain q."""
    ref = equal_sigma_reference(mb_pmf(8, 0.1), 20.0)
    assert ref["gmi_over_px"] == pytest.approx(1.43647, abs=5e-6)
    assert ref["gmi_plain"] == pytest.approx(1.40726, abs=5e-6)
    r = achievable_rates(mb_pmf(8, 0.1), 20.0)
    assert r.bmd_raw == pytest.approx(1.43647, abs=5e-6)


def test_pam4_falls_back_to_the_log_domain_kernel_when_the_direct_one_underflows():
    pmf = np.array([1e-320, 0.5, 0.25, 0.25 - 1e-320])
    sigma = np.full(4, noise_sigma_from_psnr_db(20.0))
    nodes_x, weights = rates_module._quadrature(120)
    labels = label_bits(4)
    with np.errstate(all="ignore"):
        direct = rates_module._conditional_entropies_direct(
            pmf, np.arange(4.0), sigma, labels, weights, nodes_x
        )
    assert not np.isfinite(direct[0])  # the legacy kernel returns inf here
    r = achievable_rates(pmf, 20.0)
    assert math.isfinite(r.smd) and math.isfinite(r.bmd_raw)
    log = rates_module._conditional_entropies_log(
        pmf, np.arange(4.0), sigma, labels, weights, nodes_x
    )
    assert r.smd == pytest.approx(r.entropy - log[0], abs=1e-15)


def test_non_finite_rate_raises_instead_of_reporting_zero():
    with np.errstate(all="ignore"), pytest.raises(ValueError):
        gaussian_rates(uniform(8), np.arange(8.0), np.full(8, 1e-200))


# --- bounds ----------------------------------------------------------------------------


def seeded_pmfs(order: int, count: int = 25) -> list[np.ndarray]:
    rng = np.random.default_rng(100 + order)
    pmfs = [uniform(order), mb_pmf(order, 0.1), mb_pmf(order, -0.05)]
    for k in range(count):
        p = rng.dirichlet(np.ones(order) * (0.3 if k % 2 else 2.0))
        if k % 5 == 0 and order > 2:
            p[rng.integers(0, order, 2)] = 0.0  # zero-mass levels
            p = p / p.sum()
        pmfs.append(p)
    return pmfs


@pytest.mark.parametrize("order", ORDERS)
def test_rate_bounds_hold_over_random_pmfs(order):
    tol = 1e-9
    for pmf in seeded_pmfs(order):
        for psnr_db in (-6.0, 0.0, 8.0, 16.0, 24.0, 32.0):
            r = achievable_rates(pmf, psnr_db)
            assert -tol <= r.smd <= r.entropy + tol
            assert r.entropy <= math.log2(order) + tol
            assert r.bmd <= r.smd + tol
            assert r.bmd_raw <= r.smd + tol
            assert r.bmd >= 0.0
            assert r.bmd == max(0.0, r.bmd_raw)


@pytest.mark.parametrize(("order", "lam"), [(4, 0.2), (8, 0.2), (16, 0.2)])
def test_bmd_raw_is_negative_for_a_nonuniform_pmf_at_0_db(order, lam):
    r = achievable_rates(mb_pmf(order, lam), 0.0)
    if order == 4:
        assert r.bmd_raw > 0  # PAM4 happens to stay positive here
    else:
        assert r.bmd_raw < -0.01
        assert r.bmd == 0.0  # the explicit clip


def test_bmd_raw_negative_found_for_pam4_too():
    r = achievable_rates(np.array([0.2, 0.3, 0.1, 0.4]), 0.0)
    assert r.bmd_raw < 0 and r.bmd == 0.0


# --- robustness and validation ---------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_zero_mass_levels_and_extreme_psnr_stay_finite(order):
    pmf = np.zeros(order)
    pmf[[0, order - 1]] = 0.5
    if order > 2:
        pmf[order // 2] = 0.0  # an interior level that is never used
    for psnr_db in (-20.0, 0.0, 45.0, 80.0, 120.0):
        r = achievable_rates(pmf, psnr_db)
        assert all(np.isfinite([r.entropy, r.smd, r.bmd, r.bmd_raw]))
    high = achievable_rates(uniform(order), 80.0)
    assert high.smd == pytest.approx(math.log2(order), abs=1e-9)


def test_direct_and_log_domain_kernels_agree_on_pam4():
    nodes_x, weights = rates_module._quadrature(120)
    p = np.array([0.4, 0.1, 0.2, 0.3])
    mu = np.arange(4, dtype=float)
    sd = np.full(4, noise_sigma_from_psnr_db(18.0))
    labels = label_bits(4)
    direct = rates_module._conditional_entropies_direct(p, mu, sd, labels, weights, nodes_x)
    log = rates_module._conditional_entropies_log(p, mu, sd, labels, weights, nodes_x)
    assert direct == pytest.approx(log, abs=1e-12)


@pytest.mark.parametrize("bad", [[0.5, 0.25, 0.25], [1.0], [0.1] * 10, np.full(32, 1 / 32)])
def test_invalid_pmf_length_raises(bad):
    with pytest.raises(ValueError):
        achievable_rates(bad, 10.0)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        achievable_rates(uniform(8), 10.0, order=4)  # PMF length disagrees with order
    with pytest.raises(ValueError):
        achievable_rates([0.5, 0.6, 0, 0], 10.0)  # does not sum to 1
    with pytest.raises(ValueError):
        achievable_rates([-0.1, 0.6, 0.3, 0.2], 10.0)
    with pytest.raises(ValueError):
        gaussian_rates(uniform(4), np.arange(4), np.zeros(4))
    with pytest.raises(ValueError):
        gaussian_rates(uniform(4), np.arange(8), np.ones(8))


def test_order_is_inferred_or_passed_equally():
    pmf = mb_pmf(8, 0.1)
    assert achievable_rates(pmf, 14.0) == achievable_rates(pmf, 14.0, order=8)
    sigma = noise_sigma_from_psnr_db(14.0, 8)
    assert gaussian_rates(pmf, np.arange(8), np.full(8, sigma)) == achievable_rates(pmf, 14.0)


def test_average_snr_is_reported_separately_from_psnr():
    sigma = noise_sigma_from_psnr_db(12.0, 4)
    assert average_snr(uniform(4), sigma) == pytest.approx(3.5 / sigma**2, rel=1e-12)
    # Shaping changes E[x^2] while PSNR (hence sigma) is unchanged.
    assert average_snr(symmetric_pam4(0.4), sigma) != average_snr(uniform(4), sigma)
    assert average_snr(uniform(2), noise_sigma_from_psnr_db(12.0, 2)) == pytest.approx(
        0.5 * 10 ** (12 / 10), rel=1e-12
    )
    with pytest.raises(ValueError):
        average_snr(uniform(4), 0.0)


# --- PSNR for a target rate ------------------------------------------------------------


@pytest.mark.parametrize("order", [2, 8, 16])
@pytest.mark.parametrize("metric", ["smd", "bmd"])
def test_psnr_for_rate_round_trips(order, metric):
    pmf = uniform(order)
    for fraction in (0.1, 0.5, 0.9, 0.99):
        target = fraction * math.log2(order)
        psnr_db = psnr_for_rate(pmf, target, metric)
        assert getattr(achievable_rates(pmf, psnr_db), metric) == pytest.approx(target, abs=2e-3)


def test_psnr_for_rate_bracket_is_widened_only_for_orders_other_than_4():
    # Within the PAM4 bracket [-10, 45] dB the answer is found without widening.
    assert -10.0 < psnr_for_rate(uniform(16), 3.9, "smd") < 45.0
    # At 45 dB PAM4 is already at H (to the last bit), so its bracket always suffices.
    assert achievable_rates(uniform(4), 45.0).smd == 2.0
    assert psnr_for_rate(uniform(4), 2.0 - 1e-9, "smd") <= 45.0
    # M = 16 is still 1.3e-8 below H at 45 dB, so a target 1e-10 under H needs widening.
    assert achievable_rates(uniform(16), 45.0).smd < 4.0 - 1e-9
    assert psnr_for_rate(uniform(16), 4.0 - 1e-10, "smd") > 45.0


# --- negative result and PAM4 exactness --------------------------------------------------


def test_inner_heavy_loses_to_uniform_at_fixed_peak_for_m8():
    for psnr_db in (14.0, 18.0, 22.0, 26.0):
        base = achievable_rates(uniform(8), psnr_db)
        for lam in (0.05, 0.1, 0.2):
            shaped = achievable_rates(mb_pmf(8, lam), psnr_db)
            assert shaped.smd < base.smd
            assert shaped.bmd_raw < base.bmd_raw
    # The same rate costs more PSNR: shaping is a loss here, not a gain.
    assert psnr_for_rate(mb_pmf(8, 0.1), 2.0, "smd") > psnr_for_rate(uniform(8), 2.0, "smd") + 1.0


def test_pam4_values_are_exactly_those_computed_before_the_change():
    """Pinned at de1fc73 (v1.2 rates.py); equality is exact, not approximate."""
    u = uniform(4)
    outer = symmetric_pam4(0.4)
    inner = symmetric_pam4(0.1)
    cases = [
        (u, 12.0, 2.0, 0.8147517535911124, 0.7813325829993625),
        (u, 20.0, 2.0, 1.7359862359320892, 1.7359770778002956),
        (outer, 14.0, 1.721928094887362, 1.094361922043916, 1.0761361515607915),
        (inner, 10.0, 1.7219280948873623, 0.39189653814650494, 0.3669390157129033),
        (outer, 0.0, 1.721928094887362, 0.13475851717043197, 0.12425657892012776),
    ]
    for pmf, psnr_db, h, smd, bmd in cases:
        r = achievable_rates(pmf, psnr_db)
        assert (r.entropy, r.smd, r.bmd) == (h, smd, bmd)
        assert r.bmd_raw == r.bmd  # no clipping in these cases
        assert r.nodes == 120
    assert noise_sigma_from_psnr_db(12.0) == 0.753565929452874
    assert psnr_for_rate(u, 1.0, "smd") == 13.691649690317183
    assert psnr_for_rate(u, 1.0, "bmd") == 13.8538069668088
    assert psnr_for_rate(outer, 1.5, "smd") == 19.22575288366302
    assert optimal_outer_probability(14.0) == (0.3624999999999998, 1.102138587773097)


# ---------------------------------------------------------------------------------------
# C4 minors from the C2 review: dead levels, warning text at M != 4, pinned grid constants.
# ---------------------------------------------------------------------------------------


def test_common_grid_constants_are_pinned():
    """Direct asserts on the integrator constants the provenance numbers were measured with."""
    assert rates_module._PANEL_ORDER == 10  # 10 Gauss-Legendre nodes per panel
    steps = rates_module._PANEL_SD_STEPS
    assert steps.tolist() == [float(t) for t in range(-12, 13)]  # integer sd steps, +-12 sd
    assert steps[0] == -12.0 and steps[-1] == 12.0 and steps.size == 25
    # A single live level at mean 0, sd 1: 24 panels of 10 nodes, covering exactly +-12 sd.
    p = np.array([0.0, 1.0, 0.0, 0.0])
    y, w = rates_module._common_grid(p, np.arange(4.0), np.ones(4))
    assert y.size == 24 * 10 and w.sum() == pytest.approx(24.0, abs=1e-12)
    assert y.min() > 1.0 - 12.0 and y.max() < 1.0 + 12.0


def test_dead_levels_do_not_enter_the_sigma_spread():
    """Spread, routing and warnings come from the levels with P > 0 only."""
    levels = np.arange(8, dtype=float)
    sigma = np.full(8, 0.35)
    sigma[0] = 100.0  # a dead level with an absurd sigma: spread 285 if it counted
    p = np.array([0.0, 0.1, 0.1, 0.3, 0.3, 0.1, 0.1, 0.0])
    r = no_warning(p, levels, sigma)  # no UserWarning and no common grid
    assert r.sigma_spread == 1.0 and r.quadrature == "gauss_hermite"
    forced = no_warning(p, levels, sigma, quadrature="gauss_hermite")
    assert forced.smd == r.smd and forced.bmd_raw == r.bmd_raw
    # The result does not depend on the dead level's sigma at all.
    other = sigma.copy()
    other[0] = 0.35
    assert gaussian_rates(p, levels, other).smd == pytest.approx(r.smd, abs=1e-12)
    # PAM4 legacy path: a dead outer level with a wild sigma neither warns nor changes the rate.
    p4 = np.array([0.0, 0.5, 0.5, 0.0])
    wild = np.array([50.0, 0.3, 0.3, 0.3])
    calm = np.array([0.3, 0.3, 0.3, 0.3])
    a, b = no_warning(p4, np.arange(4.0), wild), no_warning(p4, np.arange(4.0), calm)
    assert a.sigma_spread == 1.0 and a.smd == pytest.approx(b.smd, abs=1e-12)
    # A live level with the same wild sigma does count: the grid is used and no GH warning.
    live = no_warning(
        np.array([0.1, 0.4, 0.4, 0.1]), np.arange(4.0), wild, quadrature="common_grid"
    )
    assert live.sigma_spread == pytest.approx(50.0 / 0.3)
    # Edge: when all but one level is dead the spread is 1 by definition (single live level).
    single = no_warning(
        np.array([0.0, 1.0, 0.0, 0.0]), np.arange(4.0), np.array([9.0, 1.0, 5.0, 2.0])
    )
    assert single.sigma_spread == 1.0 and single.smd == pytest.approx(0.0, abs=1e-9)


def test_dead_level_with_live_unequal_sigma_still_uses_the_grid():
    levels = np.arange(8, dtype=float)
    sigma = np.array([100.0, 0.3, 0.3, 0.6, 0.3, 0.3, 0.3, 0.3])
    p = np.array([0.0, 0.1, 0.1, 0.3, 0.3, 0.1, 0.1, 0.0])
    r = gaussian_rates(p, levels, sigma)
    assert r.quadrature == "common_grid" and r.sigma_spread == pytest.approx(2.0)


def test_warning_at_other_orders_does_not_quote_the_pam4_table():
    levels = np.arange(8, dtype=float)
    sigma = np.full(8, 0.3)
    sigma[3] = 1.2  # spread 4
    with pytest.warns(UserWarning, match="unreliable") as caught:
        gaussian_rates(uniform(8), levels, sigma, quadrature="gauss_hermite")
    text = str(caught[0].message)
    assert "PAM8" in text and "240 nodes" in text and "common_grid" in text
    assert "measured for PAM4" in text and "not a measurement for PAM8" in text
    assert "3.5e-04" not in text and "measured up to" not in text  # no PAM4 numbers as if PAM8's
    # The PAM4 text is unchanged and still quotes the table.
    p, m, s = sigma_pattern(4, 12.0, 0.5, 2.0, 2)
    with pytest.warns(UserWarning, match=r"3\.5e-04 bit at spread 4") as caught4:
        gaussian_rates(p, m, s)
    assert "PAM4 120-node error" in str(caught4[0].message)
