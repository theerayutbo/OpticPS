"""Independent checks of the symmetric shaping family and the CCDM matcher.

References are derived separately from the code under test: type classes come from
itertools, block loss from a log-gamma calculation, and the legacy PAM4 comparison
runs the untouched quantize_composition.
"""

import itertools
import math

import numpy as np
import pytest

from opticps.distribution_matching.ccdm import (
    BlockShapeError,
    CompositionError,
    ConstantCompositionMatcher,
    DistributionMatcherError,
    InvalidSymbolError,
    RankOverflowError,
    multinomial,
    quantize_composition,
    quantize_symmetric_composition,
    symmetric_rate_loss,
)
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    entropy_bits,
    lambda_of_symmetric_pam4,
    maxwell_boltzmann,
    mb_for_entropy,
    pairs_of,
    symmetric_from_pairs,
    symmetric_pam4,
)

ORDERS = (2, 4, 8, 16)


def bits_of(rank: int, width: int) -> np.ndarray:
    return np.array([(rank >> (width - 1 - i)) & 1 for i in range(width)], dtype=np.int8)


# ---------------------------------------------------------------- pair family


def test_pairs_round_trip_and_level_order():
    q = [0.05, 0.1, 0.15, 0.2]
    p = symmetric_from_pairs(q)
    assert p == pytest.approx([0.2, 0.15, 0.1, 0.05, 0.05, 0.1, 0.15, 0.2])
    assert p.sum() == pytest.approx(1.0)
    assert pairs_of(p) == pytest.approx(q)


def test_pairs_match_symmetric_pam4():
    assert symmetric_from_pairs([0.35, 0.15]) == pytest.approx(PS70)
    assert symmetric_from_pairs([0.5 - 0.2, 0.2]) == pytest.approx(symmetric_pam4(0.2))


def test_pairs_of_uniform_each_order():
    for order in ORDERS:
        assert pairs_of(np.full(order, 1 / order)) == pytest.approx(np.full(order // 2, 1 / order))


@pytest.mark.parametrize(
    "q",
    [
        [0.3, 0.3],  # sums to 0.6
        [0.6, -0.1],
        [float("nan"), 0.5],
        [0.25, float("inf")],
        [],
        [[0.25, 0.25]],
    ],
)
def test_symmetric_from_pairs_rejects_bad_input(q):
    with pytest.raises(ValueError):
        symmetric_from_pairs(q)


@pytest.mark.parametrize(
    "p",
    [
        [0.1, 0.2, 0.3, 0.4],  # not symmetric
        [0.2, 0.3, 0.5],  # odd alphabet
        [0.5, 0.6, -0.1, 0.0],
        [0.25, 0.25, 0.25],
    ],
)
def test_pairs_of_rejects_bad_input(p):
    with pytest.raises(ValueError):
        pairs_of(p)


# ------------------------------------------------------------ MB entropy match


@pytest.mark.parametrize("order", [4, 8, 16])
@pytest.mark.parametrize("sign", [1, -1])
def test_mb_for_entropy_hits_target_and_sign(order, sign):
    top = math.log2(order)
    for target in (1.05, 1.5, top - 0.5, top - 0.12, top - 0.001):
        p = mb_for_entropy(target, order, sign)
        assert p.sum() == pytest.approx(1.0, abs=1e-12)
        assert entropy_bits(p) == pytest.approx(target, abs=1e-10)
        assert p == pytest.approx(p[::-1], abs=1e-15)
        mid = order // 2
        # sign +1 puts more mass on the innermost pair than the outermost, -1 the reverse
        assert (p[mid] > p[0]) if sign == 1 else (p[mid] < p[0])
        # P(x) proportional to exp(-lam x^2): recover lam from the two innermost pairs
        lam = math.log(p[mid] / p[mid + 1]) / 8.0
        assert math.copysign(1.0, lam) == sign
        assert maxwell_boltzmann(lam, order) == pytest.approx(p, abs=1e-12)


def test_mb_sign_convention_matches_repo_lambda():
    # PS70 is inner-heavy and its legacy lambda is positive: lam > 0 is inner-heavy.
    assert lambda_of_symmetric_pam4(0.15) > 0
    assert maxwell_boltzmann(0.1, 8)[4] > maxwell_boltzmann(0.1, 8)[0]
    assert maxwell_boltzmann(-0.1, 8)[4] < maxwell_boltzmann(-0.1, 8)[0]


def test_mb_uniform_at_top_entropy():
    for order in ORDERS:
        assert mb_for_entropy(math.log2(order), order, 1) == pytest.approx(
            np.full(order, 1 / order)
        )


def test_mb_pam2_only_one_bit():
    assert mb_for_entropy(1.0, 2, -1) == pytest.approx([0.5, 0.5])
    with pytest.raises(ValueError):
        mb_for_entropy(0.9, 2, 1)


def test_mb_plus_minus_lambda_entropy_equal_at_m4_only():
    # Derived, not assumed: at M=4 the pair weights are w and w*exp(-8 lam), so
    # lam -> -lam swaps the pairs of a two-point law and keeps its entropy.
    for lam in (0.05, 0.2, 0.7):
        h4 = [entropy_bits(maxwell_boltzmann(s * lam, 4)) for s in (1, -1)]
        assert h4[0] == pytest.approx(h4[1], abs=1e-12)
    # At M=8 and M=16 it fails, by a large margin.
    for order in (8, 16):
        h = [entropy_bits(maxwell_boltzmann(s * 0.05, order)) for s in (1, -1)]
        assert abs(h[0] - h[1]) > 0.1
    # Consequence for the entropy match: the same target needs different |lam|.
    inner = mb_for_entropy(2.0, 8, 1)
    outer = mb_for_entropy(2.0, 8, -1)
    lam_in = math.log(inner[4] / inner[5]) / 8
    lam_out = math.log(outer[4] / outer[5]) / 8
    assert abs(abs(lam_in) - abs(lam_out)) > 0.01
    p4_in, p4_out = (mb_for_entropy(1.7, 4, s) for s in (1, -1))
    assert math.log(p4_in[2] / p4_in[3]) == pytest.approx(-math.log(p4_out[2] / p4_out[3]))


@pytest.mark.parametrize(
    ("entropy", "order", "sign"),
    [
        (1.0, 4, 1),  # lower limit is only approached
        (0.5, 8, -1),
        (3.1, 8, 1),  # above log2 M
        (4.5, 16, -1),
        (float("nan"), 8, 1),
        (float("inf"), 8, 1),
        (2.0, 8, 0),  # bad sign
        (2.0, 8, 2),
        (2.0, 6, 1),  # bad order
    ],
)
def test_mb_for_entropy_rejects_unreachable(entropy, order, sign):
    with pytest.raises(ValueError):
        mb_for_entropy(entropy, order, sign)


# ------------------------------------------------------- exhaustive type classes


def type_class_sorted(counts):
    multiset = [s for s, c in enumerate(counts) for _ in range(c)]
    return sorted(set(itertools.permutations(multiset)))


def compositions(total, parts):
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for rest in compositions(total - first, parts - 1):
            yield (first, *rest)


@pytest.mark.parametrize(("alphabet", "n"), [(8, 5), (4, 6)])
def test_rank_is_a_bijection_onto_every_type_class(alphabet, n):
    checked = 0
    for counts in compositions(n, alphabet):
        members = type_class_sorted(counts)
        matcher = ConstantCompositionMatcher(counts)
        assert matcher.size == len(members)
        assert matcher.k == len(members).bit_length() - 1
        for rank in range(len(members)):
            block = np.array(members[rank])
            if rank < 1 << matcher.k:
                bits = bits_of(rank, matcher.k)
                assert tuple(matcher.encode(bits).tolist()) == members[rank]
                assert matcher.decode(block).tolist() == bits.tolist()
            else:
                with pytest.raises(RankOverflowError):
                    matcher.decode(block)
        checked += 1
    assert checked == math.comb(n + alphabet - 1, n)


# ------------------------------------------------------------------ round trips


@pytest.mark.parametrize("order", ORDERS)
def test_round_trip_random_bits_n1024(order):
    rng = np.random.default_rng(20261031 + order)
    if order == 2:
        pmfs = [np.array([0.5, 0.5])]
    else:
        top = math.log2(order)
        pmfs = [
            np.full(order, 1 / order),
            mb_for_entropy(top - 0.12, order, 1),
            mb_for_entropy(top - 0.28, order, -1),
        ]
    for p in pmfs:
        matcher = ConstantCompositionMatcher.from_symmetric_probabilities(p, 1024)
        assert matcher.n == 1024
        assert list(matcher.counts) == list(matcher.counts)[::-1]
        for _ in range(3):
            bits = rng.integers(0, 2, matcher.k).astype(np.int8)
            symbols = matcher.encode(bits)
            assert np.bincount(symbols, minlength=order).tolist() == list(matcher.counts)
            assert matcher.decode(symbols).tolist() == bits.tolist()
            result = matcher.try_decode(symbols)
            assert result.error is None and result.bits.tolist() == bits.tolist()


def test_extreme_bit_patterns_round_trip():
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(PS70, 1024)
    for bits in (np.zeros(matcher.k, np.int8), np.ones(matcher.k, np.int8)):
        assert matcher.decode(matcher.encode(bits)).tolist() == bits.tolist()


# --------------------------------------------------------- symmetric quantiser


def test_composition_never_splits_a_pair_across_seeded_sweep():
    rng = np.random.default_rng(7)
    done = 0
    for _ in range(600):
        order = int(rng.choice([2, 4, 8, 16]))
        n = 2 * int(rng.integers(order, 600))
        q = rng.dirichlet(np.full(order // 2, rng.choice([0.3, 1.0, 5.0]))) / 2
        p = symmetric_from_pairs(q)
        try:
            counts = quantize_symmetric_composition(p, n)
        except DistributionMatcherError:
            # allowed only when a non-zero probability rounds to no symbol at all
            assert np.any(np.floor(p * n + 1e-9) == 0)
            continue
        done += 1
        assert sum(counts) == n and len(counts) == order
        assert all(counts[i] == counts[order - 1 - i] for i in range(order))
        assert all(c > 0 for c, pi in zip(counts, p, strict=True) if pi > 0)
        # within one symbol per pair of the ideal composition
        assert max(abs(c - pi * n) for c, pi in zip(counts, p, strict=True)) < 2.0
    assert done > 300


def test_odd_remainder_is_not_split():
    # Uniform PAM4, n = 6: the legacy rule gives (2, 2, 1, 1); the pair rule must not.
    assert quantize_composition(UNIFORM, 6) == (2, 2, 1, 1)
    assert quantize_symmetric_composition(UNIFORM, 6) == (2, 1, 1, 2)


def legacy_or_none(p, n):
    try:
        return quantize_composition(p, n)
    except DistributionMatcherError:
        return None


def symmetric_or_none(p, n):
    try:
        return quantize_symmetric_composition(p, n)
    except DistributionMatcherError:
        return None


LEGACY_PMFS = [
    UNIFORM,
    PS70,
    PS80,
    OUTER70,
    *(tuple(symmetric_pam4(x)) for x in np.linspace(0.01, 0.49, 97)),
]


@pytest.mark.parametrize("n", [32, 64, 128, 256, 512, 1000, 1024, 2048, 4096, 16384])
def test_legacy_m4_equality_on_legacy_paths(n):
    for p in LEGACY_PMFS:
        assert symmetric_or_none(p, n) == legacy_or_none(p, n)


def test_legacy_m4_differs_only_where_legacy_splits_a_pair():
    # Over every even n up to 2048 and every legacy PMF, a difference occurs only when
    # the legacy composition is asymmetric (a split pair) or it raises.
    differences = 0
    for n in range(2, 2049, 2):
        for p in LEGACY_PMFS:
            legacy = legacy_or_none(p, n)
            new = symmetric_or_none(p, n)
            if legacy == new:
                continue
            differences += 1
            assert legacy is None or legacy != legacy[::-1]
            assert new is None or new == new[::-1]
    assert differences > 0  # the split really happens in the legacy rule


def test_quantize_symmetric_validation():
    for n in (0, -2, 7, 1023):
        with pytest.raises(ValueError):
            quantize_symmetric_composition(UNIFORM, n)
    for p in ([0.1, 0.2, 0.3, 0.4], [0.2, 0.3, 0.5], [0.5, 0.6, -0.1, 0.0], [0.3, 0.3, 0.3, 0.3]):
        with pytest.raises(ValueError):
            quantize_symmetric_composition(p, 64)
    with pytest.raises(DistributionMatcherError):  # 0.01 * 10 rounds to no symbol
        quantize_symmetric_composition(symmetric_pam4(0.01), 10)


# --------------------------------------------------------------- finite-block loss


def log2_multinomial(counts):
    n = sum(counts)
    return (math.lgamma(n + 1) - sum(math.lgamma(c + 1) for c in counts)) / math.log(2)


@pytest.mark.parametrize("order", [4, 8, 16])
def test_finite_block_loss_against_log_factorial(order):
    top = math.log2(order)
    p = mb_for_entropy(top - 0.2, order, 1)
    previous = None
    for n in (64, 256, 1024, 4096):
        counts = quantize_symmetric_composition(p, n)
        matcher = ConstantCompositionMatcher(counts)
        w = log2_multinomial(counts)
        assert matcher.k == math.floor(w + 1e-9) or abs(w - round(w)) < 1e-6
        assert matcher.k <= w + 1e-6 and w < matcher.k + 1 + 1e-6
        realised = np.array(counts) / n
        h_realised = -sum(x * math.log2(x) for x in realised if x > 0)
        assert matcher.rate_loss == pytest.approx(h_realised - matcher.k / n, abs=1e-12)
        # finite-length loss is non-negative: W <= 2^(n H(counts/n))
        assert h_realised - w / n >= -1e-12
        assert h_realised - w / n <= (order - 1) * math.log2(n) / (2 * n) + 1.0 / n
        total = symmetric_rate_loss(p, n)
        h_target = -sum(x * math.log2(x) for x in p if x > 0)
        assert total == pytest.approx(h_target - matcher.k / n, abs=1e-12)
        assert total == pytest.approx(matcher.target_rate_loss(p), abs=1e-15)
        if previous is not None:
            assert total < previous  # loss shrinks with block length for this PMF
        previous = total


def test_multinomial_matches_math():
    assert multinomial((2, 1, 1, 2)) == math.factorial(6) // 4
    assert multinomial((5,)) == 1


# --------------------------------------------------------- invalid-block behaviour


def small_matcher():
    return ConstantCompositionMatcher((1, 2, 1))  # W = 12, k = 3: ranks 8..11 overflow


def test_decode_wrong_composition_raises_typed_error():
    matcher = small_matcher()
    with pytest.raises(CompositionError):
        matcher.decode(np.array([0, 0, 1, 2]))
    result = matcher.try_decode(np.array([0, 0, 1, 2]))
    assert result.bits is None and result.error == "CompositionError"


def test_decode_rank_overflow_is_reported_not_garbage():
    matcher = small_matcher()
    members = type_class_sorted(matcher.counts)
    assert len(members) == 12
    for rank in range(8):
        assert matcher.decode(np.array(members[rank])).tolist() == bits_of(rank, 3).tolist()
    for rank in range(8, 12):
        with pytest.raises(RankOverflowError):
            matcher.decode(np.array(members[rank]))
        result = matcher.try_decode(np.array(members[rank]))
        assert result.bits is None and result.error == "RankOverflowError"


@pytest.mark.parametrize(
    "block",
    [
        [0, 1, 1, -1],  # negative index
        [0, 1, 1, 3],  # beyond the alphabet
        [0.0, 1.0, 1.0, 2.0],  # float dtype
    ],
)
def test_decode_invalid_symbol_is_typed(block):
    matcher = small_matcher()
    with pytest.raises(InvalidSymbolError):
        matcher.decode(np.array(block))
    assert matcher.try_decode(np.array(block)).error == "InvalidSymbolError"
    assert issubclass(InvalidSymbolError, CompositionError)


def test_decode_wrong_length_and_encode_wrong_bits_raise_value_error():
    matcher = small_matcher()
    with pytest.raises(ValueError):
        matcher.decode(np.array([0, 1, 1]))
    with pytest.raises(ValueError):
        matcher.encode(np.zeros(2, dtype=np.int8))
    with pytest.raises(ValueError):
        matcher.encode(np.array([0, 2, 1]))


def test_single_symbol_error_changes_composition_and_is_reported():
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(PS70, 256)
    rng = np.random.default_rng(3)
    bits = rng.integers(0, 2, matcher.k).astype(np.int8)
    block = matcher.encode(bits)
    block[0] = (block[0] + 1) % 4
    result = matcher.try_decode(block)
    assert result.bits is None and result.error == "CompositionError"


def test_composition_preserving_errors_decode_silently_to_wrong_bits():
    # Limit, not a feature: swapping two unequal symbols keeps the composition, so the
    # matcher returns wrong bits with error=None. C6 block erasure must report this.
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(PS70, 256)
    rng = np.random.default_rng(3)
    silent = wrong_bits = 0
    for _ in range(100):
        bits = rng.integers(0, 2, matcher.k).astype(np.int8)
        block = matcher.encode(bits)
        i, j = rng.choice(256, 2, replace=False)
        if block[i] == block[j]:
            continue
        block[i], block[j] = block[j], block[i]
        result = matcher.try_decode(block)
        if result.error is None:
            silent += 1
            wrong_bits += int(np.sum(result.bits != bits))
    # the other swaps land on a rank >= 2^k and are reported as RankOverflowError
    assert silent > 50
    assert wrong_bits / silent > 10


@pytest.mark.parametrize(
    "block",
    [
        [0, 1, 1],  # wrong length
        [],
        5,  # scalar
        None,
        [[0, 1], [1, 2]],  # 2-D with the right size
        [[0, 1], [1]],  # ragged
        [True, False, False, True],  # bool dtype
        "abcd",
    ],
)
def test_try_decode_returns_typed_failure_for_any_bad_input(block):
    matcher = small_matcher()
    result = matcher.try_decode(block)
    assert result.bits is None
    assert result.error in {"BlockShapeError", "InvalidSymbolError"}


def test_decode_shape_errors_are_value_errors():
    matcher = small_matcher()
    for block in ([0, 1, 1], [[0, 1], [1, 2]]):
        with pytest.raises(BlockShapeError):
            matcher.decode(np.array(block))
    assert issubclass(BlockShapeError, ValueError)


def test_bool_blocks_are_rejected_at_m2():
    matcher = ConstantCompositionMatcher((2, 2))
    with pytest.raises(InvalidSymbolError):
        matcher.decode(np.array([True, False, True, False]))
    assert matcher.decode(np.array([0, 0, 1, 1])).size == matcher.k


def test_mb_for_entropy_extreme_roots():
    for order in (4, 8, 16):
        for sign in (1, -1):
            for target in (1 + 1e-12, 1 + 1e-6):
                p = mb_for_entropy(target, order, sign)
                assert np.all(np.isfinite(p)) and p.sum() == pytest.approx(1.0, abs=1e-12)
                assert entropy_bits(p) == pytest.approx(target, abs=1e-12)
                mid = order // 2
                heavy = (p[mid - 1], p[mid]) if sign == 1 else (p[0], p[-1])
                assert sum(heavy) > 0.999999


def test_pairs_of_symmetry_tolerance_edge():
    base = np.array([0.1, 0.4, 0.4, 0.1])
    ok = base + np.array([0, 0, 5e-10, -5e-10])  # asymmetry 5e-10 < 1e-9
    assert pairs_of(ok).shape == (2,)
    bad = base + np.array([0, 0, 2e-9, -2e-9])
    with pytest.raises(ValueError):
        pairs_of(bad)


def test_symmetric_quantiser_is_l1_closest_not_kl_optimal():
    # Documented property: the half composition is the largest-remainder (L1) rounding of
    # n p, which here is not the KL-minimising composition.
    half = np.array([0.0256, 0.2324, 0.0532, 0.1888])
    p = np.concatenate([half, half[::-1]])
    counts = quantize_symmetric_composition(p, 28)
    assert counts[:4] == (1, 7, 1, 5)
    assert sum(counts) == 28

    def kl(c):
        return sum((x / 14) * math.log((x / 14) / (h / 0.5)) for x, h in zip(c, half, strict=True))

    assert kl((1, 6, 2, 5)) < kl(counts[:4])
    scaled = p * 28
    assert sum(abs(np.array(counts[:4]) - scaled[:4])) <= sum(
        abs(np.array((1, 6, 2, 5)) - scaled[:4])
    )
