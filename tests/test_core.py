import numpy as np
import pytest

from opticps.distribution_matching.ccdm import (
    CompositionError,
    ConstantCompositionMatcher,
    multinomial,
    quantize_composition,
)
from opticps.modulation.pam import (
    bits_to_indices,
    gray_labels,
    indices_to_bits,
    pam_levels,
)
from opticps.optimization.rates import (
    achievable_rates,
    optimal_outer_probability,
    psnr_for_rate,
)
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    entropy_bits,
    lambda_of_symmetric_pam4,
    maxwell_boltzmann,
    signal_statistics,
    symmetric_pam4,
    validate_probabilities,
)
from opticps.transmitter.frame import build_frame, m_sequence, preamble_indices, training_indices


@pytest.mark.parametrize("order", [2, 4, 8, 16])
def test_gray_adjacent_labels_differ_by_one_bit(order):
    labels = gray_labels(order)
    assert all(bin(a ^ b).count("1") == 1 for a, b in zip(labels, labels[1:], strict=False))
    assert pam_levels(order)[0] == -(order - 1)


def test_pam4_gray_round_trip():
    indices = np.random.default_rng(1).integers(0, 4, 1000)
    assert np.array_equal(bits_to_indices(indices_to_bits(indices)), indices)
    assert indices_to_bits(np.arange(4)).tolist() == [0, 0, 0, 1, 1, 1, 1, 0]


def test_uniform_entropy_and_lambda_zero():
    assert entropy_bits(UNIFORM) == pytest.approx(2.0)
    assert maxwell_boltzmann(0.0) == pytest.approx(np.full(4, 0.25))


@pytest.mark.parametrize("lam", [-0.2, -0.05, 0.0, 0.03, 0.3])
def test_maxwell_boltzmann_normalized(lam):
    assert maxwell_boltzmann(lam).sum() == pytest.approx(1.0)


def test_lambda_inverts_symmetric_family():
    assert maxwell_boltzmann(lambda_of_symmetric_pam4(0.15)) == pytest.approx(PS70)
    assert lambda_of_symmetric_pam4(0.35) < 0


def test_ps70_and_outer70_share_entropy():
    assert entropy_bits(PS70) == pytest.approx(entropy_bits(OUTER70))
    assert entropy_bits(PS70) == pytest.approx(1.8813, abs=1e-4)
    assert entropy_bits(PS80) == pytest.approx(1.7219, abs=1e-4)


def test_signal_statistics_against_hand_values():
    stats = signal_statistics(UNIFORM)
    assert stats.energy == pytest.approx(5.0)
    assert stats.papr_db == pytest.approx(10 * np.log10(9 / 5))
    assert stats.mean == pytest.approx(0.0)


@pytest.mark.parametrize("bad", [[0.5, 0.6], [1.2, -0.2], [np.nan, 1.0], [1.0]])
def test_invalid_probabilities_rejected(bad):
    with pytest.raises(ValueError):
        validate_probabilities(bad)


def test_multinomial_small_value():
    assert multinomial((1, 2, 1)) == 12


def test_ccdm_enumerates_whole_small_type_class():
    matcher = ConstantCompositionMatcher((1, 2, 1))
    assert matcher.k == 3
    seen = set()
    for value in range(8):
        bits = np.array([(value >> s) & 1 for s in (2, 1, 0)], dtype=np.int8)
        symbols = matcher.encode(bits)
        seen.add(tuple(symbols.tolist()))
        assert np.array_equal(matcher.decode(symbols), bits)
    assert len(seen) == 8


@pytest.mark.parametrize("n", [64, 256, 1024, 4096, 65536])
@pytest.mark.parametrize("p", [PS70, PS80, OUTER70])
def test_ccdm_round_trip(n, p):
    matcher = ConstantCompositionMatcher.from_probabilities(p, n)
    bits = np.random.default_rng(n).integers(0, 2, matcher.k, dtype=np.int8)
    symbols = matcher.encode(bits)
    assert tuple(np.bincount(symbols, minlength=4)) == matcher.counts
    assert np.array_equal(matcher.decode(symbols), bits)
    assert matcher.k == multinomial(matcher.counts).bit_length() - 1


def test_ccdm_rate_loss_shrinks_with_block_length():
    losses = [
        ConstantCompositionMatcher.from_probabilities(PS70, n).rate_loss
        for n in (64, 256, 1024, 4096)
    ]
    assert all(a > b for a, b in zip(losses, losses[1:], strict=False))
    assert losses[2] == pytest.approx(0.0141, abs=0.002)


def test_ccdm_rate_loss_matches_stirling_estimate():
    matcher = ConstantCompositionMatcher.from_probabilities(PS70, 4096)
    p = matcher.realised_probabilities
    n = matcher.n
    estimate = (1.5 * np.log2(2 * np.pi * n) + 0.5 * np.log2(p).sum()) / n
    assert matcher.rate_loss == pytest.approx(estimate, abs=2 / n)


def test_ccdm_composition_error_detected():
    matcher = ConstantCompositionMatcher.from_probabilities(PS70, 256)
    symbols = matcher.encode(np.zeros(matcher.k, dtype=np.int8))
    symbols[0] = (symbols[0] + 1) % 4
    with pytest.raises(CompositionError):
        matcher.decode(symbols)
    assert matcher.try_decode(symbols).error == "CompositionError"


def test_ccdm_rejects_wrong_bit_count():
    matcher = ConstantCompositionMatcher.from_probabilities(PS70, 64)
    with pytest.raises(ValueError):
        matcher.encode(np.zeros(3, dtype=np.int8))


def test_unsupported_block_length_rejected():
    with pytest.raises(ValueError):
        quantize_composition((0.001, 0.499, 0.499, 0.001), 16)


def test_composition_trap_is_quantized_symmetrically():
    assert quantize_composition(PS70, 1024) == (154, 358, 358, 154)
    assert quantize_composition(PS80, 1024) == (102, 410, 410, 102)


def test_rate_limits():
    high = achievable_rates(PS70, 45)
    assert high.smd == pytest.approx(high.entropy, abs=1e-6)
    assert high.bmd == pytest.approx(high.entropy, abs=1e-6)
    assert achievable_rates(UNIFORM, -10).smd < 0.05


def test_rates_reproduce_wiegart_gains():
    uniform_smd = psnr_for_rate(UNIFORM, 1.0, "smd")
    uniform_bmd = psnr_for_rate(UNIFORM, 1.0, "bmd")
    best_smd = min(psnr_for_rate(symmetric_pam4(q), 1.0, "smd") for q in (0.39, 0.40, 0.41))
    best_bmd = min(psnr_for_rate(symmetric_pam4(q), 1.0, "bmd") for q in (0.385, 0.395, 0.405))
    assert uniform_smd - best_smd == pytest.approx(0.84, abs=0.03)
    assert uniform_bmd - best_bmd == pytest.approx(0.71, abs=0.03)
    assert uniform_bmd - psnr_for_rate(OUTER70, 1.0, "bmd") == pytest.approx(0.63, abs=0.03)


def test_optimal_probability_curve():
    assert optimal_outer_probability(12.9)[0] == pytest.approx(0.40, abs=0.015)
    assert optimal_outer_probability(26)[0] == pytest.approx(0.25, abs=0.01)


def test_inner_heavy_loses_at_fixed_peak():
    for psnr in range(10, 27, 2):
        assert achievable_rates(PS70, psnr).smd < achievable_rates(UNIFORM, psnr).smd


def test_m_sequence_properties():
    sequence = m_sequence()
    assert sequence.size == 511
    assert sequence.sum() == 256


def test_preamble_is_dc_balanced_and_outer_only():
    preamble = preamble_indices()
    assert preamble.size == 512
    assert set(np.unique(preamble)) == {0, 3}
    assert (preamble == 0).sum() == (preamble == 3).sum()
    assert np.array_equal(np.bincount(training_indices(42)), [128] * 4)


@pytest.mark.parametrize("total", [32768, 65536])
def test_frame_is_deterministic_and_sized(total):
    a = build_frame("x", PS70, total, 42)
    b = build_frame("x", PS70, total, 42)
    assert a.indices.size == total
    assert np.array_equal(a.indices, b.indices)
    assert np.array_equal(a.info_bits, b.info_bits)


def test_frame_rejects_bad_payload_length():
    with pytest.raises(ValueError):
        build_frame("x", PS70, 3000, 42)


def test_uniform_frame_bits_are_labels():
    frame = build_frame("u", UNIFORM, 32768, 42, direct_uniform=True)
    assert np.array_equal(frame.info_bits, frame.label_bits[2048:])
    assert frame.distribution_matcher_rate == 2.0
