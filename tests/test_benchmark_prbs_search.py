"""B2B-only pattern search (plan R.2 characterisation): synthetic fixtures with known generators.

No capture is read. Fixtures are PAM4 waveforms built here from known symbol streams; the file route
is tested with names only (nothing is opened).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from opticps.benchmarks import prbs_search as ps
from opticps.benchmarks import teriphic
from opticps.benchmarks.holdout import require_reference_for_ber
from opticps.benchmarks.provenance import BenchmarkError, ErrorCode

ROOT = Path(__file__).resolve().parents[1]
FS, BAUD = 256e9, 50e9
SYMBOLS = 24000
BLOCK = 4096
LEVELS = np.array([-1.5, -0.5, 0.5, 1.5])


def lfsr_bits(lags, n, seed=1):
    top = max(lags)
    buf = [int(v) for v in np.random.default_rng(seed).integers(0, 2, top)]
    buf[0] = buf[0] or 1
    for i in range(top, n):
        value = 0
        for lag in lags:
            value ^= buf[i - lag]
        buf.append(value)
    return np.array(buf[:n], dtype=np.uint8)


def symbols_from_bits(bits, mapping):
    hi, lo = bits[0::2], bits[1::2]
    return ps.bits_to_symbols(hi, lo, mapping)


def waveform(symbols, sigma, seed=11, pulse=0.28):
    rng = np.random.default_rng(seed)
    spp = FS / BAUD
    n = int(len(symbols) * spp)
    t = np.arange(n)
    k0 = np.floor(t / spp).astype(int)
    x = np.zeros(n)
    for dk in range(-3, 4):
        k = k0 + dk
        ok = (k >= 0) & (k < len(symbols))
        g = np.exp(-0.5 * ((t - (k + 0.5) * spp) / (pulse * spp)) ** 2)
        x[ok] += LEVELS[symbols[k[ok]]] * g[ok]
    return x + rng.normal(0.0, sigma, n)


def search(symbols, sigma=0.2, **kwargs):
    x = waveform(symbols, sigma)
    return ps.run_search(x, FS, BAUD, id_samples=int(0.3 * x.size), timing_block=BLOCK, **kwargs)


@pytest.fixture(scope="module")
def prbs15_gray():
    bits = lfsr_bits(ps.GENERATORS["PRBS15"], 2 * SYMBOLS)
    return symbols_from_bits(bits, "gray")


@pytest.fixture(scope="module")
def positive(prbs15_gray):
    return search(prbs15_gray, 0.2)


# ---------------------------------------------------------------------------- the fixtures
def test_positive_prbs15_gray_is_recovered_uniquely(positive):
    assert positive["status"] == ps.STATUS_INFERRED
    assert positive["provenance"] == "INFERRED"
    winner = positive["winner"]
    assert winner["kind"] == "lfsr"
    assert winner["named_description"] == "PRBS15|gray|serial"
    assert positive["p6"]["verified"] is True
    assert positive["p6"]["mismatch_rate"] <= 2 * positive["p6"]["decision_error_estimate"]
    assert positive["p6"]["other_candidates_lowest_verification_syndrome"] > 0.4
    assert winner["syndrome_verification"] < 0.1
    # a serial PRBS also satisfies its lane test, so these are listed as equivalent, not counted
    assert "PRBS15|gray|lanes" in winner["equivalent_descriptions"]
    assert positive["p2_period_scan"]["period_symbols"] is None


def test_the_result_never_holds_the_sequence_and_ber_stays_missing(positive):
    assert positive["reference_sequence"] == "REFERENCE_SEQUENCE_MISSING"
    assert positive["ber_and_ser"] == "REFERENCE_SEQUENCE_MISSING"
    assert positive["proxy_name"] == "symbol_mismatch_vs_inferred_sequence"
    seed = positive["winner"]["seed"]
    assert len(seed["seed_bits"]) == 15  # the generator state, not the sequence

    def longest(value):
        if isinstance(value, str):
            return len(value)
        if isinstance(value, dict):
            return max((longest(v) for v in value.values()), default=0)
        if isinstance(value, list):
            return max([len(value)] + [longest(v) for v in value])
        return 0

    assert longest(positive) < 1000  # nothing sequence-sized (the table has a few hundred rows)
    asset = next(
        a
        for a in teriphic.load_config(ROOT / teriphic.CONFIG_PATH).assets
        if a.filename == teriphic.B2B_FILENAME
    )
    with pytest.raises(BenchmarkError) as error:
        require_reference_for_ber(asset)
    assert error.value.code is ErrorCode.REFERENCE_SEQUENCE_MISSING


def test_random_symbols_are_not_recovered():
    rng = np.random.default_rng(4)
    result = search(rng.integers(0, 4, SYMBOLS), 0.15)
    assert result["status"] == ps.STATUS_NOT_RECOVERED
    assert result["provenance"] is None
    assert result["reference_sequence"] == "REFERENCE_SEQUENCE_MISSING"
    assert min(r["syndrome_identification"] for r in result["p4_table"]) > 0.4
    assert "seed" not in (result["winner"] or {})


def test_wrong_mapping_alone_is_not_recovered():
    # PRBS31 needs complexity 31, so a wrong mapping cannot be rescued by a longer recurrence (for
    # PRBS15 every mapping is affinely related and Berlekamp-Massey finds one of complexity <= 31)
    symbols = symbols_from_bits(lfsr_bits(ps.GENERATORS["PRBS31"], 2 * SYMBOLS, seed=5), "gray")
    wrong = search(symbols, 0.15, maps=("gray-inv",))
    assert wrong["status"] == ps.STATUS_NOT_RECOVERED
    assert min(r["syndrome_identification"] for r in wrong["p4_table"]) > 0.4
    right = search(symbols, 0.15, maps=("gray",))
    assert right["status"] == ps.STATUS_INFERRED
    assert right["winner"]["mapping"] == "gray"
    assert right["winner"]["generator"] == "PRBS31"


def test_inverted_level_order_is_found_as_inverted():
    bits = lfsr_bits(ps.GENERATORS["PRBS15"], 2 * SYMBOLS, seed=7)
    result = search(symbols_from_bits(bits, "natural-inv"), 0.2)
    assert result["status"] == ps.STATUS_INFERRED
    equivalent = result["winner"]["equivalent_descriptions"]
    assert "PRBS15|natural-inv|serial" in equivalent
    assert "PRBS15|natural|serial" not in equivalent
    plain = search(symbols_from_bits(bits, "natural"), 0.2)
    assert "PRBS15|natural|serial" in plain["winner"]["equivalent_descriptions"]
    assert "PRBS15|natural-inv|serial" not in plain["winner"]["equivalent_descriptions"]


def test_noise_near_threshold_is_not_recovered_even_for_the_true_pattern(prbs15_gray):
    # 3.9 % decision errors from Gaussian noise: the mismatches sit just past a threshold but not in
    # the lowest 20 % of margins, so P6 (b) rejects it. The rule is not relaxed for noise.
    result = search(prbs15_gray, 0.3)
    assert result["p6"]["mismatch_rate"] > 0.02
    assert result["p6"]["c_winner_syndrome_below_0.1"] is True
    assert result["p6"]["b_mismatches_at_low_margin"] is False
    assert result["status"] == ps.STATUS_NOT_RECOVERED


def test_a_pattern_present_only_in_the_identification_window_is_not_verified(prbs15_gray):
    rng = np.random.default_rng(8)
    mixed = np.concatenate([prbs15_gray[:8000], rng.integers(0, 4, SYMBOLS - 8000)])
    result = search(mixed, 0.15)
    assert result["status"] == ps.STATUS_NOT_RECOVERED
    assert result["winner"]["syndrome_identification"] < 0.1
    assert result["winner"]["syndrome_verification"] > 0.4


def test_a_generator_outside_the_list_is_found_by_berlekamp_massey():
    lags = (10, 3)  # PRBS10, not in the list
    symbols = symbols_from_bits(lfsr_bits(lags, 2 * SYMBOLS, seed=3), "gray")
    result = search(symbols, 0.2)
    assert result["status"] == ps.STATUS_INFERRED
    assert result["p5_bm_candidates"]
    assert result["winner"]["generator"].startswith("BM")
    assert result["winner"]["named_description"] is None


def test_a_periodic_pattern_without_an_lfsr_is_recovered_by_vote():
    rng = np.random.default_rng(6)
    period = 200
    pattern = rng.integers(0, 4, period)
    symbols = np.tile(pattern, SYMBOLS // period)
    result = search(symbols, 0.2)
    assert result["p2_period_scan"]["period_symbols"] == period
    assert result["winner"]["kind"] == "periodic"
    assert result["status"] == ps.STATUS_INFERRED


def test_prbs7_is_seen_as_periodic_but_the_lfsr_wins():
    symbols = symbols_from_bits(lfsr_bits(ps.GENERATORS["PRBS7"], 2 * SYMBOLS, seed=9), "natural")
    result = search(symbols, 0.2)
    assert result["p2_period_scan"]["period_symbols"] == 127
    assert result["winner"]["kind"] == "lfsr"
    assert result["status"] == ps.STATUS_INFERRED


# ---------------------------------------------------------------------------- the pieces
def test_pre_registered_thresholds_are_pinned():
    assert ps.MISMATCH_FACTOR == 2.0
    assert ps.MISMATCH_MAX == 0.1
    assert ps.LOW_MARGIN_QUANTILE == 0.2
    assert ps.LOW_MARGIN_SHARE == 0.9
    assert ps.SYNDROME_WINNER_MAX == 0.1
    assert ps.SYNDROME_OTHER_MIN == 0.4
    assert ps.ID_SAMPLES == 8388608
    assert (ps.BM_STRETCH_SYMBOLS, ps.BM_STRETCHES, ps.BM_MIN_AGREE) == (64, 8, 3)
    assert ps.SEED_STRETCHES == 16
    assert ps.PERIOD_PEAK == 0.5
    assert ps.default_generators() == ps.GENERATORS
    assert len(ps.map_names()) == 6


def stats(rate, share, n=1000):
    return {"mismatch_rate": rate, "share_in_lowest_20pct_margin": share, "symbols": n}


def test_verdict_thresholds_are_exact():
    ok = ps.verdict(stats(0.01, 0.95), 0.01, 0.05, [0.5])
    assert ok["verified"] is True
    assert ps.verdict(stats(0.02000001, 0.95), 0.01, 0.05, [0.5])["verified"] is False  # a
    assert ps.verdict(stats(0.02, 0.95), 0.01, 0.05, [0.5])["verified"] is True
    assert ps.verdict(stats(0.11, 0.95), 0.2, 0.05, [0.5])["verified"] is False  # a, 0.1 cap
    assert ps.verdict(stats(0.1, 0.95), 0.2, 0.05, [0.5])["verified"] is True
    assert ps.verdict(stats(0.01, 0.89), 0.01, 0.05, [0.5])["verified"] is False  # b
    assert ps.verdict(stats(0.01, 0.9), 0.01, 0.05, [0.5])["verified"] is True
    assert ps.verdict(stats(0.0, None), 0.01, 0.05, [0.5])["verified"] is True  # no mismatches
    assert ps.verdict(stats(0.01, 0.95), 0.01, 0.1, [0.5])["verified"] is False  # c winner
    assert ps.verdict(stats(0.01, 0.95), 0.01, 0.099, [0.5])["verified"] is True
    assert ps.verdict(stats(0.01, 0.95), 0.01, 0.05, [0.4])["verified"] is False  # c others
    assert ps.verdict(stats(0.01, 0.95), 0.01, 0.05, [0.41, 0.5])["verified"] is True
    two = ps.verdict(stats(0.01, 0.95), 0.01, 0.05, [0.05, 0.5])
    assert two["verified"] is False
    assert two["not_unique"] is True


def test_berlekamp_massey_finds_the_recurrence_and_random_is_long():
    bits = [int(v) for v in lfsr_bits((15, 14), 128, seed=2)]
    length, lags = ps.berlekamp_massey(bits)
    assert (length, lags) == (15, (15, 14))
    rnd = [int(v) for v in np.random.default_rng(0).integers(0, 2, 128)]
    assert ps.berlekamp_massey(rnd)[0] > 50


def test_syndrome_is_zero_for_the_truth_and_half_for_random():
    bits = lfsr_bits((13, 12, 2, 1), 20000)
    assert ps.syndrome(bits, (13, 12, 2, 1), 0, 20000) == 0.0
    assert ps.syndrome(bits, (13, 12), 0, 20000) > 0.4
    rnd = np.random.default_rng(1).integers(0, 2, 20000).astype(np.uint8)
    assert 0.45 < ps.syndrome(rnd, (15, 14), 0, 20000) < 0.55
    flipped = bits.copy()
    flipped[5000] ^= 1
    assert ps.syndrome(flipped, (13, 12, 2, 1), 0, 20000) == pytest.approx(5 / 19987, abs=1e-5)


def test_lfsr_extend_runs_both_ways_from_a_seed():
    lags = (15, 14)
    bits = lfsr_bits(lags, 3000)
    out = ps.lfsr_extend(lags, bits[1000:1015], 1000, 0, 3000)
    assert np.array_equal(out, bits)


def test_lane_syndrome_is_the_larger_of_the_two_lanes():
    bits = lfsr_bits((15, 14), 20000)
    rnd = np.random.default_rng(2).integers(0, 2, 20000).astype(np.uint8)
    streams = ps.Streams(
        hi={"gray": bits}, lo={"gray": rnd}, serial={"gray": ps.serial_stream(bits, rnd)}
    )
    cand = ps.Candidate("PRBS15", (15, 14), "gray", "lanes")
    assert ps.candidate_syndrome(cand, streams, 0, 20000) > 0.45


def test_mappings_round_trip_and_invert():
    symbols = np.array([0, 1, 2, 3, 3, 2, 1, 0])
    for name in ps.map_names():
        hi, lo = ps.symbols_to_bits(symbols, name)
        assert np.array_equal(ps.bits_to_symbols(hi, lo, name), symbols)
    hi, lo = ps.symbols_to_bits(np.array([0, 1, 2, 3]), "gray")
    assert (hi.tolist(), lo.tolist()) == ([0, 0, 1, 1], [0, 1, 1, 0])
    hi, lo = ps.symbols_to_bits(np.array([0, 1, 2, 3]), "natural-inv")
    assert (hi.tolist(), lo.tolist()) == ([1, 1, 0, 0], [1, 0, 1, 0])


def test_decisions_use_the_r13_centroids():
    values = np.array([-1.51, -0.49, 0.5, 1.49, -1.0, -0.98, 0.02, 1.0])
    symbols, margin = ps.decide(values)
    assert symbols.tolist() == [0, 1, 2, 3, 0, 1, 2, 3]
    assert margin[4] < 0.01 and margin[6] < 0.01 and margin[0] > 0.4


# ---------------------------------------------------------------------------- the file route
def test_the_ten_and_two_km_names_and_others_are_refused_before_any_open(tmp_path):
    ten = tmp_path / ps.TEN_KM_NAME
    two = tmp_path / ps.TWO_KM_NAME
    other = tmp_path / "something.bin"
    for path in (ten, two, other):
        with pytest.raises(BenchmarkError) as error:
            ps.refuse_unless_b2b_name(path)
        assert error.value.code is ErrorCode.LEAKAGE_DETECTED
        assert not path.exists()  # nothing was created or opened
    with pytest.raises(BenchmarkError, match="10 km"):
        ps.open_b2b_only(ten)
    with pytest.raises(BenchmarkError, match="2 km"):
        ps.open_b2b_only(two)


def test_a_link_named_b2b_that_resolves_to_another_file_is_refused(tmp_path):
    target = tmp_path / ps.TEN_KM_NAME
    link = tmp_path / teriphic.B2B_FILENAME
    link.symlink_to(target)  # dangling: the target is never created or opened
    with pytest.raises(BenchmarkError, match="10 km"):
        ps.refuse_unless_b2b_name(link)
    other_target = tmp_path / ps.TWO_KM_NAME
    link2 = tmp_path / "sub" / teriphic.B2B_FILENAME
    link2.parent.mkdir()
    link2.symlink_to(other_target)
    with pytest.raises(BenchmarkError, match="2 km"):
        ps.refuse_unless_b2b_name(link2)


def test_the_b2b_name_alone_is_accepted_by_the_name_check(tmp_path):
    path = tmp_path / teriphic.B2B_FILENAME
    assert ps.refuse_unless_b2b_name(path) == path.resolve()


def test_the_script_refuses_a_ten_km_path_with_exit_code_2(tmp_path):
    out = tmp_path / "out.yaml"
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts/prbs_search_b2b.py"), "--data",
         str(tmp_path / ps.TEN_KM_NAME), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 2
    assert "refused" in run.stderr
    assert not out.exists()
    assert not (tmp_path / ps.TEN_KM_NAME).exists()


def test_the_seed_with_the_fewest_identification_mismatches_is_kept():
    lags = (15, 14)
    bits = lfsr_bits(lags, 3000, seed=4)
    margin = np.ones(3000)
    margin[500:515] = 5.0  # the most confident stretch is the corrupted one
    observed = bits.copy()
    observed[503] ^= 1
    full, info = ps._regenerate_stream(observed, lags, margin, 3000, 1)
    assert info["id_window_symbol_mismatches"] == 1  # only the corrupted bit differs
    assert np.array_equal(full, bits)
