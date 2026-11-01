"""Gate N3 part a: the RLS decision feedback equaliser, on synthetic channels only."""

import math

import numpy as np
import pytest

from opticps.receiver.dfe import (
    RlsDfeConfig,
    RlsInstabilityError,
    rls_equalize,
    slicer_thresholds,
)

LEVELS = np.array([-3.0, -1.0, 1.0, 3.0])


def _symbols(n, seed):
    idx = np.random.default_rng(seed).integers(0, 4, n)
    return idx, LEVELS[idx]


def _t2_channel(symbols, h_sym, snr_db=None, seed=0):
    """A symbol-spaced channel h_sym on the T/2 grid (2 samples per symbol), optional AWGN."""
    h = np.zeros(2 * len(h_sym) - 1)
    h[::2] = h_sym
    up = np.zeros(2 * symbols.size)
    up[::2] = symbols
    x = np.convolve(up, h)[: up.size]
    if snr_db is not None:
        sigma = math.sqrt(np.mean(x**2) / 10 ** (snr_db / 10))
        x = x + np.random.default_rng(seed).normal(0.0, sigma, x.size)
    return x


def _snr_db(out, s):
    return 10 * math.log10(np.mean(s**2) / np.mean((out - s) ** 2))


def test_the_dfe_converges_on_a_known_isi_channel_to_near_zero_error_without_noise():
    for h in ([1.0, 0.6, 0.4, 0.2], [0.5, 1.0, 0.9, 0.7]):
        idx, s = _symbols(20000, 1)
        x = _t2_channel(s, h)
        r = rls_equalize(x, s, RlsDfeConfig(training_symbols=2000))
        tail = slice(3000, None)
        assert np.array_equal(r.decision_indices[tail], idx[tail])  # zero decision errors
        assert _snr_db(r.output[tail], s[tail]) > 80.0  # noise-free: the channel is cancelled


def test_the_dfe_beats_a_linear_ffe_at_high_isi_with_noise():
    # h = [1, 1] has a spectral null at the Nyquist frequency: a linear equaliser enhances noise.
    idx, s = _symbols(30000, 2)
    x = _t2_channel(s, [1.0, 1.0], snr_db=27.0, seed=3)
    dfe = rls_equalize(x, s, RlsDfeConfig(training_symbols=2000))
    ffe = rls_equalize(x, s, RlsDfeConfig.ffe_only(17, 2, training_symbols=2000))
    tail = slice(3000, None)
    ser_dfe = float(np.mean(dfe.decision_indices[tail] != idx[tail]))
    ser_ffe = float(np.mean(ffe.decision_indices[tail] != idx[tail]))
    assert ser_dfe == 0.0 and ser_ffe > 0.05
    assert _snr_db(dfe.output[tail], s[tail]) > _snr_db(ffe.output[tail], s[tail]) + 10.0
    assert dfe.weights.size == 24 and ffe.weights.size == 17  # (17, 7) and FFE only


def test_ffe_only_mode_has_no_feedback_taps_and_is_a_usable_generic_interface():
    cfg = RlsDfeConfig.ffe_only(5, 1, training_symbols=500, levels=(-1.0, 1.0))
    assert cfg.fb_taps == 0 and cfg.n_weights == 5 and cfg.samples_per_symbol == 1
    rng = np.random.default_rng(4)
    s = rng.choice([-1.0, 1.0], 6000)
    x = np.convolve(s, [1.0, 0.3, -0.1])[: s.size]
    r = rls_equalize(x, s, cfg)
    assert set(np.unique(r.decisions)) <= {-1.0, 1.0}
    assert np.mean(r.decisions[1000:] != s[1000:]) == 0.0
    assert slicer_thresholds((-1.0, 1.0)) == [0.0]
    assert slicer_thresholds((-3.0, -1.0, 1.0, 3.0)) == [-2.0, 0.0, 2.0]


def test_the_equaliser_is_deterministic():
    idx, s = _symbols(5000, 5)
    x = _t2_channel(s, [1.0, 0.5, 0.2], snr_db=22.0, seed=6)
    cfg = RlsDfeConfig(training_symbols=1000)
    a, b = rls_equalize(x, s, cfg), rls_equalize(x, s, cfg)
    assert np.array_equal(a.output, b.output) and np.array_equal(a.weights, b.weights)
    assert np.array_equal(a.p_matrix, b.p_matrix)


def test_decisions_after_training_come_from_the_slicer_and_never_from_the_reference():
    # the reference beyond the training length is never read: change it, nothing changes
    idx, s = _symbols(4000, 7)
    x = _t2_channel(s, [1.0, 0.4], snr_db=24.0, seed=8)
    cfg = RlsDfeConfig(training_symbols=800)
    s2 = s.copy()
    s2[800:] = 99.0
    a, b = rls_equalize(x, s, cfg), rls_equalize(x, s2, cfg)
    assert np.array_equal(a.output, b.output) and np.array_equal(a.decisions, b.decisions)


def test_adaptation_stops_after_training_when_decision_directed_is_off():
    idx, s = _symbols(6000, 9)
    x = _t2_channel(s, [1.0, 0.5, 0.2], snr_db=26.0, seed=10)
    train = 1500
    # a second capture that is identical over everything the training reads (its windows, including
    # the wrapped start) and different afterwards
    x2 = x.copy()
    x2[2 * train + 40 : -40] += np.random.default_rng(20).normal(0.0, 5.0, x2.size - 2 * train - 80)
    off = RlsDfeConfig(training_symbols=train, decision_directed=False)
    on = RlsDfeConfig(training_symbols=train, decision_directed=True)
    assert np.array_equal(rls_equalize(x, s, off).weights, rls_equalize(x2, s, off).weights)
    assert not np.array_equal(rls_equalize(x, s, on).weights, rls_equalize(x2, s, on).weights)


# --- closed form on AWGN: PAM4 with Gray labels -------------------------------------------------


def _q(x):
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def _gray_pam4_ber(sigma):
    """Exact bit error rate of Gray PAM4 (levels -3, -1, 1, 3, thresholds -2, 0, 2) in AWGN."""
    return 0.75 * _q(1 / sigma) + 0.5 * _q(3 / sigma) - 0.25 * _q(5 / sigma)


def _binomial_z(errors, n, p):
    return (errors - n * p) / math.sqrt(n * p * (1 - p))


def test_ber_on_awgn_matches_the_q_function_with_the_equaliser_off():
    from opticps.measurement.nanf_chain import count_bit_errors

    n = 400_000
    idx, s = _symbols(n, 11)
    cfg = RlsDfeConfig.ffe_only(1, 1)
    thresholds = slicer_thresholds(cfg.levels)
    rng = np.random.default_rng(12)
    for sigma in (0.35, 0.45, 0.55):
        y = s + rng.normal(0.0, sigma, n)
        rx = np.searchsorted(thresholds, y)  # the slicer alone: "DFE off"
        errors = count_bit_errors(idx, rx)
        p = _gray_pam4_ber(sigma)
        # 4 sigma of the binomial count (99.99 %); bit errors of one symbol are not independent
        # across the two bits of different symbols, so the bit count is binomial to a good
        # approximation for Gray mapping (one bit per adjacent-level error)
        assert abs(_binomial_z(errors, 2 * n, p)) < 4.0, (sigma, errors, 2 * n * p)


def test_ber_on_awgn_with_a_one_tap_rls_matches_the_q_function_at_the_learned_gain():
    from opticps.measurement.nanf_chain import count_bit_errors

    n = 200_000
    idx, s = _symbols(n, 13)
    rng = np.random.default_rng(14)
    for sigma in (0.40, 0.50):
        x = s + rng.normal(0.0, sigma, n)
        r = rls_equalize(x, s, RlsDfeConfig.ffe_only(1, 1, training_symbols=2000))
        gain = float(r.weights[0])
        assert gain == pytest.approx(5.0 / (5.0 + sigma**2), rel=0.02)  # the LS (Wiener) gain
        # decisions on gain * x with thresholds -2, 0, 2: thresholds on x are -2/g, 0, 2/g
        t = 2.0 / gain
        p_sym = 0.0
        for lev, lo, hi in ((-3, -math.inf, -t), (-1, -t, 0.0), (1, 0.0, t), (3, t, math.inf)):
            inside = _q((lo - lev) / sigma) if math.isfinite(lo) else 1.0
            above = _q((hi - lev) / sigma) if math.isfinite(hi) else 0.0
            p_sym += 0.25 * (1.0 - (inside - above))
        scored = slice(2000, None)
        sym_errors = int(np.count_nonzero(r.decision_indices[scored] != idx[scored]))
        n_scored = n - 2000
        assert abs(_binomial_z(sym_errors, n_scored, p_sym)) < 4.0
        bits = count_bit_errors(idx[scored], r.decision_indices[scored])
        assert bits >= sym_errors  # Gray: at least one bit per symbol error


# --- numerical stability ------------------------------------------------------------------------


def test_rls_stays_symmetric_positive_definite_and_bounded_over_a_long_run():
    n = 250_000
    idx, s = _symbols(n, 15)
    x = _t2_channel(s, [0.4, 1.0, 0.8, 0.3, 0.1], snr_db=24.0, seed=16)
    r = rls_equalize(x, s, RlsDfeConfig(training_symbols=8192))
    assert r.max_p_asymmetry == 0.0 and np.array_equal(r.p_matrix, r.p_matrix.T)
    eig = np.linalg.eigvalsh(r.p_matrix)
    assert eig.min() > 0.0 and np.all(np.isfinite(r.weights))
    assert r.max_p_trace <= RlsDfeConfig().p_trace_cap * (1 + 1e-9)
    tail = slice(20000, None)
    assert np.mean(r.decision_indices[tail] != idx[tail]) < 1e-3
    assert _snr_db(r.output[tail], s[tail]) > 17.0


def test_a_long_gap_without_excitation_does_not_overflow_and_the_equaliser_recovers():
    # 0.998^-n overflows a double after about 3.5e5 symbols; the cap keeps P finite (the run below is
    # 4e5 zero symbols, then data)
    n_zero, n_data = 400_000, 20_000
    idx, s = _symbols(n_data, 17)
    x = np.concatenate(
        [np.zeros(2 * n_zero), _t2_channel(s, [1.0, 0.5, 0.2], snr_db=28.0, seed=18)]
    )
    ref = np.concatenate([np.zeros(n_zero), s])
    cfg = RlsDfeConfig(training_symbols=n_zero + 3000)
    r = rls_equalize(x, ref, cfg)
    assert np.all(np.isfinite(r.p_matrix)) and r.n_trace_caps > 0
    assert np.linalg.eigvalsh(r.p_matrix).min() > 0
    tail = slice(n_zero + 5000, None)
    assert (
        np.mean(r.decision_indices[tail] != np.concatenate([np.zeros(n_zero, int), idx])[tail])
        < 1e-3
    )


@pytest.mark.filterwarnings("ignore:overflow encountered")
def test_without_a_cap_an_unexcited_run_fails_closed_with_a_typed_error():
    cfg = RlsDfeConfig(
        forgetting=0.9, p_trace_cap=1.7e308, training_symbols=9000, health_check_every=500
    )
    with pytest.raises(RlsInstabilityError):
        rls_equalize(np.zeros(2 * 9000), np.zeros(9000), cfg)


def test_invalid_settings_and_inputs_are_refused():
    bad = (
        {"ff_taps": 0}, {"fb_taps": -1}, {"samples_per_symbol": 0}, {"cursor": 17},
        {"cursor": -1}, {"forgetting": 0.0}, {"forgetting": 1.01}, {"delta": 0.0},
        {"delta": float("nan")}, {"training_symbols": -1}, {"levels": (1.0,)},
        {"levels": (1.0, 1.0)}, {"p_trace_cap": 0.0}, {"symmetrize_every": 0},
        {"health_check_every": 0},
    )  # fmt: skip
    for kwargs in bad:
        with pytest.raises(ValueError):
            RlsDfeConfig(**kwargs)
    cfg = RlsDfeConfig(training_symbols=10)
    with pytest.raises(ValueError):
        rls_equalize(np.zeros(21), np.zeros(10), cfg)  # not a multiple of samples_per_symbol
    with pytest.raises(ValueError):
        rls_equalize(np.array([np.nan] * 40), np.zeros(20), cfg)
    with pytest.raises(ValueError):
        rls_equalize(np.zeros(40), np.zeros(5), cfg)  # reference shorter than the training
    with pytest.raises(ValueError):
        rls_equalize(np.zeros((2, 20)), np.zeros(20), cfg)


def test_the_cursor_places_the_main_tap():
    cfg = RlsDfeConfig()
    assert cfg.main_tap == 8 and RlsDfeConfig(cursor=3).main_tap == 3
    # a pure delay of 3 T/2 samples is learned equally well with the cursor at 8: the equaliser output
    # for a noise-free symbol-rate channel with a pre-cursor of one symbol (2 samples) is exact
    idx, s = _symbols(6000, 19)
    delayed = np.concatenate([np.zeros(2), _t2_channel(s, [1.0, 0.3])])[: 2 * s.size]
    r = rls_equalize(delayed, s, RlsDfeConfig(training_symbols=1000))
    assert np.array_equal(r.decision_indices[1500:], idx[1500:])


def _textbook_rls_training_only(x, ref, cfg):
    """Exponentially weighted LS by the normal equations, solved from scratch at every symbol.

    Phi(n) = lambda Phi(n-1) + u u^T and theta(n) = lambda theta(n-1) + d u, with the a priori
    output y(n) = w(n-1)^T u(n) and the regressor [T/2 window | past desired symbols]; Phi(0) is
    delta I (the inverse of P(0) = I / delta). No matrix inversion lemma is used, so this is an
    independent check of the recursion.
    """
    nf, nb, sps, c = cfg.ff_taps, cfg.fb_taps, cfg.samples_per_symbol, cfg.main_tap
    n_sym = x.size // sps
    m = nf + nb
    phi = np.eye(m) * cfg.delta
    theta = np.zeros(m)
    w = np.zeros(m)
    out = np.empty(n_sym)
    for n in range(n_sym):
        window = np.array([x[(n * sps + j - c) % x.size] for j in range(nf)])
        past = np.array([ref[n - 1 - k] if n - 1 - k >= 0 else 0.0 for k in range(nb)])
        u = np.concatenate([window, past])
        out[n] = w @ u
        phi = cfg.forgetting * phi + np.outer(u, u)
        theta = cfg.forgetting * theta + ref[n] * u
        w = np.linalg.solve(phi, theta)
    return out, w


def test_the_recursion_equals_the_normal_equations_solved_from_scratch():
    # lambda < 1 and delta chosen so that the delta I initial term is forgotten at the same rate
    # in both forms: Phi(0) = delta I enters Phi(n) as lambda^n delta I in the textbook form and
    # in the Woodbury form alike, so the two agree to rounding
    idx, s = _symbols(400, 21)
    x = _t2_channel(s, [1.0, 0.5, 0.25], snr_db=30.0, seed=22)
    cfg = RlsDfeConfig(
        ff_taps=7, fb_taps=3, forgetting=0.99, delta=1e-2, training_symbols=400, p_trace_cap=1e12
    )
    out, w = _textbook_rls_training_only(x, s, cfg)
    r = rls_equalize(x, s, cfg)
    assert np.max(np.abs(r.output - out)) < 1e-6 * max(1.0, np.max(np.abs(out)))
    assert np.max(np.abs(r.weights - w)) < 1e-6 * max(1.0, np.max(np.abs(w)))
    # a different forgetting factor gives a different answer (the factor is really used)
    other = rls_equalize(
        x, s, RlsDfeConfig(ff_taps=7, fb_taps=3, forgetting=0.95, delta=1e-2, training_symbols=400)
    )
    assert np.max(np.abs(other.weights - w)) > 1e-3


def test_the_health_check_runs_on_schedule(monkeypatch):
    from opticps.receiver import dfe

    calls = []
    real = dfe._check_health
    monkeypatch.setattr(dfe, "_check_health", lambda p, w, n: (calls.append(n), real(p, w, n)))
    idx, s = _symbols(1000, 30)
    x = _t2_channel(s, [1.0, 0.4], snr_db=25.0, seed=31)
    rls_equalize(x, s, RlsDfeConfig(training_symbols=200, health_check_every=250))
    assert calls == [249, 499, 749, 999, 999]  # every 250 symbols, then once at the end


def test_explicit_symmetrisation_repairs_an_asymmetric_update(monkeypatch):
    idx, s = _symbols(640, 32)
    x = _t2_channel(s, [1.0, 0.4], snr_db=25.0, seed=33)
    cfg = RlsDfeConfig(training_symbols=640, symmetrize_every=64, p_trace_cap=1e12)
    m = cfg.n_weights
    skew = 1e-9 * np.triu(np.ones((m, m)), 1)
    real_outer = np.outer
    monkeypatch.setattr(np, "outer", lambda a, b: real_outer(a, b) + skew)
    r = rls_equalize(x, s, cfg)
    assert r.max_p_asymmetry > 0.0  # the guard saw the asymmetry
    assert np.array_equal(r.p_matrix, r.p_matrix.T)  # and removed it at the last scheduled step


def test_a_non_finite_denominator_is_refused_at_the_symbol(monkeypatch):
    real_dot, state = np.dot, {"vec": 0}

    def dot(a, b):
        if np.ndim(a) == 1 and np.ndim(b) == 1:
            state["vec"] += 1
            if state["vec"] == 21:  # the 11th symbol's u^T pi
                return float("nan")
        return real_dot(a, b)

    monkeypatch.setattr(np, "dot", dot)
    idx, s = _symbols(100, 34)
    x = _t2_channel(s, [1.0, 0.4], snr_db=25.0, seed=35)
    with pytest.raises(RlsInstabilityError, match="denominator at symbol 10"):
        rls_equalize(x, s, RlsDfeConfig(training_symbols=100, health_check_every=10**9))
