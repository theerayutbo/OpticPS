"""Gate E2 part a: frozen estimators, B2B surrogate, scorer entry point (Stage 3A).

Every fixture is synthetic: a PAM4 NRZ waveform smoothed by a Gaussian, with a fibre effect applied
by this file's own derivation (cos(pi lambda^2 D L f^2 / c) by FFT) and its own noise. No TERIPHIC
sample is read except in the tests whose name starts with `test_real_`, which read the B2B file only
and skip when it is absent. The 2 km and 10 km files are never opened here.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
import dataclasses
import hashlib
import math
import os
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy.ndimage import gaussian_filter1d
from scipy.signal import welch

from opticps.benchmarks import e2_metrics, e2_model, e2_score, holdout, teriphic
from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.provenance import (
    BenchmarkError,
    Checksum,
    ErrorCode,
    Split,
)
from test_benchmark_external_capture import keysight_image

ROOT = Path(__file__).resolve().parents[1]
FS = 8e11
BAUD = 5e10
SPS = 16
N = 1 << 18
WINDOWS = {
    "fit": {"start": 0, "samples": N},
    "spread": {"start": N, "samples": N},
    "evaluation": {"start": 2 * N, "samples": N},
}
RECORD = 3 * N
C0 = 0.0
G0 = 1.0
MULTIPLIER = 3.0  # the fixture's own multiplier; the frozen criterion states its own
LEVELS = np.array([-1.45, -0.5, 0.5, 1.5])
LIGHT = 299_792_458.0
LAMBDA = 1310e-9


# ---------------------------------------------------------------------------- the test's own channel
TRUE_PSD = [
    math.exp(-(((k * FS / 4096) / 30e9) ** 2)) for k in range(2049)
]  # a Gaussian low-pass, 30 GHz scale
TRUE_MODEL = {
    "sample_rate_hz": FS, "baud_bd": BAUD, "pulse_samples": 1024, "psd_relative": TRUE_PSD,
    "level_probabilities": [0.25] * 4, "pulse_levels": [-1.45, -0.5, 0.5, 1.5], "noise_sigma": 0.0,
}  # fmt: skip


def channel(
    seed: int,
    *,
    n: int = RECORD,
    dispersion: float = 0.0,
    length_km: float = 0.0,
    ratio: float = 1.0,
    noise: float = 0.25,
    noise_follows_signal: bool = False,
) -> np.ndarray:
    """A PAM4 record with a fibre applied by this file's own derivation.

    The noise-free pulse train comes from the surrogate's generator (a Gaussian low-pass and the
    levels of `TRUE_MODEL`, which the fit never sees); the fibre (cos(pi lambda^2 D L f^2 / c) by
    FFT over the whole record), the amplitude ratio and the noise are applied here, with a
    separate random generator.
    """
    clean = e2_model.synthesize(
        TRUE_MODEL, n_samples=n, symbol_seed=seed, noise_seed=seed + 1, sigma=0.0
    )
    f = np.fft.rfftfreq(n, 1.0 / FS)
    theta = math.pi * LAMBDA**2 * (dispersion * 1e-6) * (length_km * 1e3) * f**2 / LIGHT
    x = np.fft.irfft(np.fft.rfft(clean) * np.cos(theta), n) * ratio
    rng = np.random.default_rng(seed + 5000)
    floor = np.fft.irfft(
        np.fft.rfft(rng.normal(size=n))
        * np.sqrt(np.interp(f, np.arange(2049) * FS / 4096, TRUE_PSD)),
        n,
    )
    floor *= noise / floor.std()
    return x + (ratio * floor if noise_follows_signal else floor)


def normaliser(raw: np.ndarray) -> tuple[float, float]:
    centroids, _ = e2_metrics.kmeans_levels(raw[: WINDOWS["fit"]["samples"]])
    return float(centroids.mean()), float(np.diff(centroids).mean())


def window(x: np.ndarray, name: str) -> np.ndarray:
    w = WINDOWS[name]
    return x[w["start"] : w["start"] + w["samples"]]


@pytest.fixture(scope="module")
def world():
    """B2B-like fixture, its normalisation, a fitted model and a limit set (B2B only)."""
    b2b = channel(1)
    c0, g0 = normaliser(b2b)
    fit = e2_metrics.normalise(window(b2b, "fit"), c0, g0)
    fitted = e2_model.fit_b2b_model(
        fit, sample_rate_hz=FS, baud_bd=BAUD, fit_seed=11, fit_samples=N, iterations=4,
        polish_evaluations=40,
    )  # fmt: skip
    model = {
        "model_version": e2_score.MODEL_VERSION,
        **fitted,
        "normalisation": {"c0": c0, "g0": g0, "units": "fixture"},
        "windows": WINDOWS,
        "seeds": {"fit": 11, "prediction_symbols": 12, "prediction_noise": 13},
        "parameters": {"x": {"provenance": "INFERRED", "how": "fixture"}},
        "model_gaps": list(e2_model.MODEL_GAPS),
        "assumptions": list(e2_model.ASSUMPTIONS),
        "code_identity": e2_score.code_identity(ROOT),
    }

    def entry(identifier, dispersion, attenuation, borne=False, null=False):
        return {
            "id": identifier, "dispersion_ps_nm_km": dispersion,
            "attenuation_db_per_km": attenuation, "noise_follows_signal": borne,
            "null_control": null, "label": identifier,
        }  # fmt: skip

    scenarios_doc = {
        "scenario_list_version": 1,
        "count": 5,
        "scenarios": [
            entry("NULL", 0.0, 0.0, null=True),
            entry("DMAX", 6.352, 0.0),
            entry("LOSS", 0.0, 0.5),
            entry("LOSS_BORNE", 0.0, 0.5, borne=True),
            entry("BOTH", 6.352, 0.5),
        ],
        "provenance": {"status": "fixture"},
    }
    scenarios = e2_score.check_scenarios(scenarios_doc)
    checked = e2_score.check_model(model)
    ev = e2_metrics.normalise(window(b2b, "evaluation"), c0, g0)
    sp = e2_metrics.normalise(window(b2b, "spread"), c0, g0)
    surrogate = e2_score.predict(checked, scenarios[0], 0.0, N)
    misfit = e2_metrics.all_metrics(ev, surrogate, FS, BAUD)
    spread = e2_metrics.all_metrics(ev, sp, FS, BAUD)
    basis = {m: max(misfit[m], spread[m]) for m in holdout.METRICS}
    limits = {m: MULTIPLIER * basis[m] for m in holdout.METRICS}
    return {
        "b2b": b2b, "c0": c0, "g0": g0, "model": checked, "model_doc": model,
        "scenarios": scenarios, "scenarios_doc": scenarios_doc, "limits": limits, "basis": basis,
        "evaluation": ev, "misfit": misfit, "spread": spread,
    }  # fmt: skip


def norm(world, x: np.ndarray) -> np.ndarray:
    return e2_metrics.normalise(window(x, "evaluation"), world["c0"], world["g0"])


def score(world, measured, comparator=None, *, length_km=10.0, split=Split.VALIDATION, **extra):
    return e2_score.score_windows(
        measured,
        world["evaluation"] if comparator is None else comparator,
        model=world["model"],
        scenarios=world["scenarios"],
        limits=world["limits"],
        length_km=length_km,
        split=split,
        **extra,
    )


# ---------------------------------------------------------------------------- estimators M1 to M4
def point_masses(values, each=2000, spread=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return np.concatenate([v + spread * rng.standard_normal(each) for v in values])


def test_kmeans_levels_find_four_exact_masses_and_shares():
    x = np.concatenate([np.full(1000, v) for v in (-3.0, -1.0, 1.0, 5.0)])
    centroids, shares = e2_metrics.kmeans_levels(x)
    assert centroids == pytest.approx([-3.0, -1.0, 1.0, 5.0], abs=1e-12)
    assert shares == pytest.approx([0.25] * 4)
    assert e2_metrics.level_gaps(centroids) == pytest.approx([2.0, 2.0, 4.0])


def test_kmeans_matches_a_brute_force_lloyd_on_noisy_levels():
    x = point_masses((-1.5, -0.5, 0.5, 1.5), spread=0.25, seed=3)
    centroids, _ = e2_metrics.kmeans_levels(x)
    c = np.quantile(x, [0.125, 0.375, 0.625, 0.875])
    for _ in range(200):
        assign = np.argmin(np.abs(x[:, None] - c[None, :]), axis=1)
        new = np.array([x[assign == k].mean() for k in range(4)])
        move = np.max(np.abs(new - c))
        c = new
        if move < 1e-9 * x.std():
            break
    assert centroids == pytest.approx(np.sort(c), abs=1e-9)


def test_kmeans_converges_to_the_fixed_point_on_a_skewed_window():
    x = np.random.default_rng(4).exponential(size=20000)  # many iterations are needed
    centroids, shares = e2_metrics.kmeans_levels(x)
    c = np.quantile(x, [0.125, 0.375, 0.625, 0.875])
    for _ in range(200):
        assign = np.argmin(np.abs(x[:, None] - c[None, :]), axis=1)
        new = np.array([x[assign == k].mean() for k in range(4)])
        move = np.max(np.abs(new - c))
        c = new
        if move < 1e-9 * x.std():
            break
    assert centroids == pytest.approx(np.sort(c), abs=1e-6)
    assert shares.sum() == pytest.approx(1.0)


def test_kmeans_refuses_flat_nonfinite_short_and_empty_cluster_windows():
    with pytest.raises(BenchmarkError, match="no spread"):
        e2_metrics.kmeans_levels(np.ones(500))
    with pytest.raises(BenchmarkError, match="non-finite"):
        e2_metrics.kmeans_levels(np.r_[np.nan, np.arange(500.0)])
    with pytest.raises(BenchmarkError, match="at least"):
        e2_metrics.kmeans_levels(np.arange(10.0))
    with pytest.raises(BenchmarkError, match="empty"):
        e2_metrics.kmeans_levels(np.r_[np.zeros(400), np.ones(100)])
    with pytest.raises(BenchmarkError, match="one-dimensional"):
        e2_metrics.require_window(np.zeros((4, 40000)), "x")


def test_level_gaps_need_four_ascending_centroids():
    with pytest.raises(BenchmarkError, match="four strictly ascending"):
        e2_metrics.level_gaps(np.array([0.0, 1.0, 1.0, 2.0]))
    with pytest.raises(BenchmarkError, match="four strictly ascending"):
        e2_metrics.level_gaps(np.array([0.0, 1.0, 2.0]))


def test_normalise_is_the_one_affine_map_and_refuses_a_bad_scale():
    x = np.array([2.0, 4.0, 6.0])
    assert e2_metrics.normalise(x, 4.0, 2.0) == pytest.approx([-1.0, 0.0, 1.0])
    for c0, g0 in ((np.nan, 1.0), (0.0, 0.0), (0.0, -1.0), (0.0, np.inf)):
        with pytest.raises(BenchmarkError, match="normalisation"):
            e2_metrics.normalise(x, c0, g0)


def test_m1_is_the_l_infinity_norm_of_the_gap_difference():
    a = np.concatenate([np.full(9000, v) for v in (-1.5, -0.5, 0.5, 1.5)])
    b = np.concatenate([np.full(9000, v) for v in (-1.5, -0.3, 0.5, 1.7)])
    # gaps a: 1, 1, 1; gaps b: 1.2, 0.8, 1.2 -> differences 0.2, 0.2, 0.2
    assert e2_metrics.m1_level_spacing(a, b) == pytest.approx(0.2, abs=1e-12)
    c = np.concatenate([np.full(9000, v) for v in (-1.5, -0.5, 0.5, 2.5)])
    assert e2_metrics.m1_level_spacing(a, c) == pytest.approx(1.0, abs=1e-12)
    assert e2_metrics.m1_level_spacing(a, a) == 0.0


def test_m2_is_the_mean_absolute_quantile_difference():
    rng = np.random.default_rng(5)
    x = rng.normal(size=40000)
    assert e2_metrics.m2_wasserstein1(x, x + 0.25) == pytest.approx(0.25, abs=1e-9)
    assert e2_metrics.m2_wasserstein1(x, x) == 0.0
    y = rng.normal(size=50000) * 1.3
    u = (np.arange(65536) + 0.5) / 65536
    expected = np.mean(np.abs(np.percentile(x, 100 * u) - np.percentile(y, 100 * u)))
    assert e2_metrics.m2_wasserstein1(x, y) == pytest.approx(expected, rel=1e-9)


def test_quantile_function_is_type_7_and_refuses_probabilities_outside_0_1():
    x = np.random.default_rng(9).normal(size=1001)
    p = np.array([0.0, 0.001, 0.3, 0.5, 0.999, 1.0])
    assert e2_metrics.quantile_function(x, p) == pytest.approx(np.percentile(x, 100 * p), abs=1e-12)
    for bad in (-0.01, 1.01, np.nan):
        with pytest.raises(BenchmarkError, match="probabilities"):
            e2_metrics.quantile_function(x, np.array([0.5, bad]))


def test_m3_is_the_largest_difference_over_the_seven_stated_points():
    rng = np.random.default_rng(6)
    x = rng.normal(size=40000)
    y = x * 1.2
    points = np.array([1, 5, 25, 50, 75, 95, 99]) / 100
    assert e2_metrics.QUANTILE_POINTS == tuple(points)
    expected = np.max(np.abs(np.percentile(x, 100 * points) - np.percentile(y, 100 * points)))
    assert e2_metrics.m3_quantile_error(x, y) == pytest.approx(expected, rel=1e-12)
    tails = max(abs(np.percentile(x, 1)), abs(np.percentile(x, 99)))
    assert expected == pytest.approx(0.2 * tails, rel=1e-9)  # an outer point decides
    spike = x.copy()
    spike[0] = 1e6  # outside every stated point: M3 must not see it
    assert e2_metrics.m3_quantile_error(x, spike) < 0.01


def test_m4_is_the_rms_db_ratio_up_to_the_baud_rate_only():
    rng = np.random.default_rng(7)
    x = gaussian_filter1d(rng.normal(size=1 << 17), 3.0)
    assert e2_metrics.m4_log_spectral_distance(x, 2.0 * x, FS, BAUD) == pytest.approx(
        20 * math.log10(2.0), abs=1e-9
    )
    assert e2_metrics.m4_log_spectral_distance(x, x, FS, BAUD) == 0.0
    f, p = welch(x, FS, window="hann", nperseg=4096, noverlap=2048, detrend="constant")
    y = gaussian_filter1d(x, 5.0)
    _, q = welch(y, FS, window="hann", nperseg=4096, noverlap=2048, detrend="constant")
    keep = f <= BAUD
    expected = math.sqrt(np.mean((10 * np.log10(p[keep] / q[keep])) ** 2))
    assert e2_metrics.m4_log_spectral_distance(x, y, FS, BAUD) == pytest.approx(expected, rel=1e-9)
    # a change above the baud rate leaves M4 unchanged: scale only the bins above 60 GHz
    spectrum = np.fft.rfft(x)
    freq = np.fft.rfftfreq(x.size, 1 / FS)
    spectrum[freq > 60e9] *= 3.0
    z = np.fft.irfft(spectrum, x.size)
    assert e2_metrics.m4_log_spectral_distance(x, z, FS, BAUD) < 0.05
    spectrum = np.fft.rfft(x)
    spectrum[(freq > 20e9) & (freq < 30e9)] *= 3.0
    w = np.fft.irfft(spectrum, x.size)
    assert e2_metrics.m4_log_spectral_distance(x, w, FS, BAUD) > 1.0


def test_m4_ignores_a_constant_offset_because_each_segment_is_detrended():
    x = gaussian_filter1d(np.random.default_rng(10).normal(size=1 << 17), 3.0)
    assert e2_metrics.m4_log_spectral_distance(x, x + 7.5, FS, BAUD) < 1e-6


def test_m4_refuses_a_bad_rate_a_bad_band_and_a_silent_spectrum():
    x = np.random.default_rng(8).normal(size=1 << 16)
    with pytest.raises(BenchmarkError, match="sample rate"):
        e2_metrics.m4_log_spectral_distance(x, x, 0.0, BAUD)
    with pytest.raises(BenchmarkError, match="fewer than 8"):
        e2_metrics.m4_log_spectral_distance(x, x, FS, 1e6)
    with pytest.raises(BenchmarkError, match="not positive"):
        e2_metrics.m4_log_spectral_distance(x, np.zeros_like(x), FS, BAUD)


def test_all_metrics_has_exactly_the_four_frozen_names_and_refuses_nan():
    x = channel(2)[:N]
    names = set(e2_metrics.all_metrics(x, x, FS, BAUD))
    assert names == set(holdout.METRICS)
    bad = x.copy()
    bad[17] = np.nan
    with pytest.raises(BenchmarkError, match="non-finite"):
        e2_metrics.all_metrics(x, bad, FS, BAUD)
    with pytest.raises(BenchmarkError, match="non-finite"):
        e2_metrics.all_metrics(bad, x, FS, BAUD)
    with pytest.raises(BenchmarkError, match="at least"):
        e2_metrics.all_metrics(x[:100], x[:100], FS, BAUD)


# ---------------------------------------------------------------------------- surrogate pieces
def test_ratio_of_is_exact_and_refuses_what_is_not_a_small_ratio():
    assert e2_model.ratio_of(2.048e12, 50e9) == Fraction(1024, 25)
    assert e2_model.ratio_of(FS, BAUD) == 16
    for rate, baud in (
        (np.pi * 1e11, 5e10),
        (1e11, 5e10),
        (0.0, 5e10),
        (8e11, -1.0),
        (np.nan, 1.0),
    ):
        with pytest.raises(BenchmarkError):
            e2_model.ratio_of(rate, baud)


def test_dispersion_response_is_the_chirp_free_cosine_with_a_null_where_expected():
    f = np.linspace(0.0, 80e9, 801)
    assert e2_model.dispersion_response(f, 0.0, 10.0) == pytest.approx(np.ones_like(f))
    assert e2_model.dispersion_response(f, 5.0, 0.0) == pytest.approx(np.ones_like(f))
    d, length = 6.352, 10.0
    f_null = math.sqrt(LIGHT / (2 * d * 1e-6 * length * 1e3 * LAMBDA**2))
    assert 30e9 < f_null < 45e9
    null = e2_model.dispersion_response(np.array([f_null]), d, length)[0]
    assert abs(null) < 1e-9
    h = e2_model.dispersion_response(f, d, length)
    theta = math.pi * LAMBDA**2 * d * 1e-6 * length * 1e3 * f**2 / LIGHT
    assert h == pytest.approx(np.cos(theta))
    assert e2_model.dispersion_response(f, -d, length) == pytest.approx(h)  # even in D
    for bad in (np.nan, np.inf):
        with pytest.raises(BenchmarkError):
            e2_model.dispersion_response(f, bad, 1.0)
        with pytest.raises(BenchmarkError):
            e2_model.dispersion_response(f, 1.0, bad)
    with pytest.raises(BenchmarkError, match="negative"):
        e2_model.dispersion_response(f, 1.0, -1.0)


def test_loss_amplitude_ratio_follows_power_in_db():
    assert e2_model.loss_amplitude_ratio(0.5, 0.0) == 1.0
    assert e2_model.loss_amplitude_ratio(0.5, 10.0) == pytest.approx(10 ** (-0.5))
    assert e2_model.loss_amplitude_ratio(3.0103, 1.0) == pytest.approx(0.5, abs=1e-4)
    for a, length in ((-0.1, 1.0), (np.nan, 1.0), (0.5, np.nan), (0.5, -2.0)):
        with pytest.raises(BenchmarkError):
            e2_model.loss_amplitude_ratio(a, length)


def test_lumped_pulse_is_symmetric_unit_centre_and_dispersion_changes_it(world):
    model = world["model"]
    base = e2_model.lumped_pulse(model["psd_relative"], FS, pulse_samples=256)
    assert base[128] == pytest.approx(1.0)
    assert base[128 + 5] == pytest.approx(base[128 - 5], abs=1e-9)
    dispersed = e2_model.lumped_pulse(
        model["psd_relative"], FS, dispersion_ps_nm_km=6.352, length_km=10.0, pulse_samples=256
    )
    assert np.max(np.abs(dispersed - base)) > 0.01
    assert dispersed[128] < base[128]
    with pytest.raises(BenchmarkError, match="even"):
        e2_model.lumped_pulse(model["psd_relative"], FS, pulse_samples=255)
    with pytest.raises(BenchmarkError, match="2049"):
        e2_model.lumped_pulse([1.0] * 10, FS)
    with pytest.raises(BenchmarkError, match="positive"):
        e2_model.lumped_pulse([0.0] * 2049, FS)


def test_synthesize_is_deterministic_seeded_and_places_symbols_at_exact_instants(world):
    model = dict(world["model"])
    a = e2_model.synthesize(model, n_samples=8192, symbol_seed=1, noise_seed=2)
    b = e2_model.synthesize(model, n_samples=8192, symbol_seed=1, noise_seed=2)
    assert np.array_equal(a, b)
    assert not np.array_equal(
        a, e2_model.synthesize(model, n_samples=8192, symbol_seed=3, noise_seed=2)
    )
    assert not np.array_equal(
        a, e2_model.synthesize(model, n_samples=8192, symbol_seed=1, noise_seed=4)
    )
    # a flat spectrum gives a delta pulse: with no noise the output is the level at each symbol
    flat = dict(model, psd_relative=[1.0] * 2049, noise_sigma=0.0)
    levels = [-3.0, -1.0, 1.0, 3.0]
    y = e2_model.synthesize(
        flat, n_samples=4096, symbol_seed=5, noise_seed=6, levels=levels, sigma=0.0
    )
    phases = [y[p::SPS] for p in range(SPS)]
    hits = [p for p, v in enumerate(phases) if np.all(np.isin(np.round(v, 6), levels))]
    assert len(hits) == 1
    seen = np.round(phases[hits[0]], 6)
    assert set(seen) == set(levels) and abs(np.mean(seen)) < 0.25


def test_synthesize_uses_the_25_class_geometry_of_a_fractional_ratio(world):
    # 5.12 samples per symbol is 128 samples in 25 symbols; compare with a naive sum of pulses
    model = dict(world["model"], sample_rate_hz=5.12 * BAUD, pulse_samples=128, noise_sigma=0.0)
    n = 2048
    y = e2_model.synthesize(model, n_samples=n, symbol_seed=9, noise_seed=1, sigma=0.0)
    pulse = e2_model.lumped_pulse(model["psd_relative"], model["sample_rate_hz"], pulse_samples=128)
    blocks = e2_model.block_count(n, 128, 128)
    probabilities = np.asarray(model["level_probabilities"])
    symbols = e2_model.draw_symbols(blocks, 25, probabilities, 9)
    expected = np.zeros(blocks * 128 + 4 * 128)
    levels = np.asarray(model["pulse_levels"])
    for m in range(blocks):
        for c in range(25):
            start, rem = divmod(c * 128, 25)
            shifted = e2_model.fractional_pulse(pulse, rem / 25)
            at = start + m * 128
            expected[at : at + 128] += levels[symbols[m, c]] * shifted
    assert y == pytest.approx(expected[128 : 128 + n], abs=1e-9)


def test_synthesize_refuses_bad_inputs(world):
    model = dict(world["model"])
    for kwargs in (
        {"n_samples": 10},
        {"n_samples": 4096, "amplitude_ratio": -1.0},
        {"n_samples": 4096, "amplitude_ratio": np.nan},
        {"n_samples": 4096, "levels": [1.0, 2.0, 3.0]},
        {"n_samples": 4096, "levels": [1.0, 2.0, 3.0, np.nan]},
    ):
        with pytest.raises(BenchmarkError):
            e2_model.synthesize(model, symbol_seed=1, noise_seed=2, **kwargs)
    with pytest.raises(BenchmarkError, match="sum to 1"):
        e2_model.synthesize(
            dict(model, level_probabilities=[0.5, 0.5, 0.5, 0.5]), n_samples=4096,
            symbol_seed=1, noise_seed=2,
        )  # fmt: skip
    with pytest.raises(BenchmarkError, match="negative"):
        e2_model.synthesize(
            dict(model, level_probabilities=[1.5, -0.5, 0.0, 0.0]), n_samples=4096,
            symbol_seed=1, noise_seed=2,
        )  # fmt: skip
    with pytest.raises(BenchmarkError, match="non-negative|not be negative|not negative"):
        e2_model.shaped_noise(model["psd_relative"], FS, 4096, -1.0, 1)


def test_fit_is_b2b_only_deterministic_and_matches_the_b2b_centroids(world):
    fit = e2_metrics.normalise(window(world["b2b"], "fit"), world["c0"], world["g0"])
    again = e2_model.fit_b2b_model(
        fit, sample_rate_hz=FS, baud_bd=BAUD, fit_seed=11, fit_samples=N, iterations=4,
        polish_evaluations=40,
    )  # fmt: skip
    model = world["model"]
    assert again["pulse_levels"] == model["pulse_levels"]
    assert again["noise_sigma"] == model["noise_sigma"]
    centroids, _ = e2_metrics.kmeans_levels(fit)
    assert model["b2b_centroids_normalised"] == pytest.approx(list(centroids))
    assert model["level_probabilities"] == [0.25] * 4  # assumed, declared
    synthetic = e2_score.predict(model, world["scenarios"][0], 0.0, N)
    got, _ = e2_metrics.kmeans_levels(synthetic)
    assert got == pytest.approx(list(centroids), abs=0.15)  # the surrogate reproduces the levels


def test_fractional_pulse_delays_a_smooth_pulse_by_the_stated_fraction():
    n = np.arange(256)
    sigma = 6.0
    pulse = np.exp(-((n - 128) ** 2) / (2 * sigma**2))
    for fraction in (0.0, 0.2, 0.5, 0.96):
        expected = np.exp(-((n - 128 - fraction) ** 2) / (2 * sigma**2))
        assert e2_model.fractional_pulse(pulse, fraction) == pytest.approx(expected, abs=1e-6)


def test_shaped_noise_has_the_requested_spread_and_the_spectrum_shape(world):
    psd = world["model"]["psd_relative"]
    noise = e2_model.shaped_noise(psd, FS, 1 << 16, 0.37, 5)
    assert noise.std() == pytest.approx(0.37, rel=1e-9)
    assert np.array_equal(noise, e2_model.shaped_noise(psd, FS, 1 << 16, 0.37, 5))
    f, p = e2_metrics.welch_density(noise, FS)
    keep = f <= BAUD
    reference = np.asarray(psd)[keep]
    low, high = p[keep][1:30].mean(), p[keep][-30:].mean()
    assert (low / high) == pytest.approx(reference[1:30].mean() / reference[-30:].mean(), rel=0.35)
    assert not e2_model.shaped_noise(psd, FS, 1 << 16, 0.0, 5).any()


def test_window_summaries_give_the_same_metrics_as_the_stand_alone_functions():
    a, b = channel(51)[:N], channel(52, dispersion=3.0, length_km=10.0)[:N]
    direct = e2_metrics.all_metrics(a, b, FS, BAUD)
    assert direct["M1_level_spacing"] == pytest.approx(e2_metrics.m1_level_spacing(a, b), abs=1e-15)
    assert direct["M2_wasserstein1_amplitude"] == pytest.approx(e2_metrics.m2_wasserstein1(a, b))
    assert direct["M3_quantile_error"] == pytest.approx(e2_metrics.m3_quantile_error(a, b))
    assert direct["M4_log_spectral_distance"] == pytest.approx(
        e2_metrics.m4_log_spectral_distance(a, b, FS, BAUD)
    )


def test_the_code_identity_lists_the_files_that_decide_the_result():
    assert e2_score.CODE_IDENTITY_FILES == (
        "src/opticps/benchmarks/e2_metrics.py",
        "src/opticps/benchmarks/e2_model.py",
        "src/opticps/benchmarks/e2_score.py",
        "src/opticps/benchmarks/holdout.py",
        "src/opticps/benchmarks/external_capture.py",
        "src/opticps/benchmarks/teriphic.py",
        "src/opticps/benchmarks/provenance.py",
    )


# ---------------------------------------------------------------------------- documents
def test_check_model_default_denies_missing_extra_and_bad_values(world):
    doc = world["model_doc"]
    assert e2_score.check_model(doc)["model_version"] == 1
    for key in list(doc):
        missing = {k: v for k, v in doc.items() if k != key}
        with pytest.raises(BenchmarkError, match="exactly the keys"):
            e2_score.check_model(missing)
    with pytest.raises(BenchmarkError, match="exactly the keys"):
        e2_score.check_model(doc | {"extra": 1})
    cases = {
        "model_version": 2, "sample_rate_hz": np.nan, "baud_bd": 0.0, "pulse_samples": 10,
        "psd_relative": [1.0] * 5, "noise_sigma": -1.0, "b2b_std_normalised": np.inf,
        "model_gaps": [], "assumptions": [], "parameters": {}, "seeds": {"fit": 1},
        "windows": {"fit": {"start": 0, "samples": 5}, "spread": {}, "evaluation": {}},
        "normalisation": {"c0": 0.0, "g0": -1.0, "units": "x"},
        "code_identity": {"src/x.py": "0" * 64},
    }  # fmt: skip
    for key, value in cases.items():
        with pytest.raises(BenchmarkError):
            e2_score.check_model(doc | {key: value})
    nan_levels = list(doc["pulse_levels"])
    nan_levels[0] = float("nan")
    with pytest.raises(BenchmarkError, match="finite"):
        e2_score.check_model(doc | {"pulse_levels": nan_levels})
    with pytest.raises(BenchmarkError, match="SHA-256"):
        e2_score.check_model(
            doc
            | {
                "code_identity": dict(
                    doc["code_identity"], **{e2_score.CODE_IDENTITY_FILES[0]: "x"}
                )
            }
        )


def test_check_scenarios_default_denies(world):
    doc = world["scenarios_doc"]
    assert len(e2_score.check_scenarios(doc)) == 5
    with pytest.raises(BenchmarkError, match="count"):
        e2_score.check_scenarios(doc | {"count": 3})
    with pytest.raises(BenchmarkError, match="non-empty"):
        e2_score.check_scenarios(doc | {"scenarios": [], "count": 0})
    dup = [dict(doc["scenarios"][0]), dict(doc["scenarios"][0])]
    with pytest.raises(BenchmarkError, match="duplicate"):
        e2_score.check_scenarios(doc | {"scenarios": dup, "count": 2})
    no_null = [dict(s, null_control=False) for s in doc["scenarios"]]
    with pytest.raises(BenchmarkError, match="exactly one"):
        e2_score.check_scenarios(doc | {"scenarios": no_null})
    two_null = [dict(s, null_control=True) for s in doc["scenarios"]]
    with pytest.raises(BenchmarkError, match="exactly one"):
        e2_score.check_scenarios(doc | {"scenarios": two_null})
    for bad in (np.nan, -1.0, "x", True):
        entry = dict(doc["scenarios"][1], dispersion_ps_nm_km=bad)
        with pytest.raises(BenchmarkError):
            e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    entry = dict(doc["scenarios"][1], attenuation_db_per_km=np.inf)
    with pytest.raises(BenchmarkError):
        e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    entry = dict(doc["scenarios"][1], null_control="no")
    with pytest.raises(BenchmarkError, match="true or false"):
        e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    entry = dict(doc["scenarios"][1], id="  ")
    with pytest.raises(BenchmarkError, match="non-empty string"):
        e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    with pytest.raises(BenchmarkError, match="exactly the keys"):
        e2_score.check_scenarios({k: v for k, v in doc.items() if k != "provenance"})


def test_code_identity_is_a_sha256_of_the_listed_files_only(tmp_path):
    table = e2_score.code_identity(ROOT)
    assert set(table) == set(e2_score.CODE_IDENTITY_FILES)
    path = ROOT / e2_score.CODE_IDENTITY_FILES[0]
    assert table[e2_score.CODE_IDENTITY_FILES[0]] == hashlib.sha256(path.read_bytes()).hexdigest()
    copy = copy_code(tmp_path)
    model = {"code_identity": e2_score.code_identity(copy)}
    e2_score.verify_code_identity(model, copy)
    target = copy / e2_score.CODE_IDENTITY_FILES[1]
    target.write_text(target.read_text() + "\n# changed\n")
    with pytest.raises(BenchmarkError, match="e2_model.py"):
        e2_score.verify_code_identity(model, copy)
    target.unlink()
    with pytest.raises(BenchmarkError, match="missing"):
        e2_score.code_identity(copy)
    link = copy / e2_score.CODE_IDENTITY_FILES[1]
    link.symlink_to(path)
    with pytest.raises(BenchmarkError, match="symbolic link"):
        e2_score.code_identity(copy)


def copy_code(dest: Path) -> Path:
    root = dest / "code"
    for relative in e2_score.CODE_IDENTITY_FILES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, root / relative)
    return root


# ---------------------------------------------------------------------------- scoring core
def test_a_real_fibre_difference_is_detected_and_the_b2b_copy_cannot_explain_it(world):
    truth = channel(21, dispersion=6.352, length_km=10.0)
    measured = norm(world, truth)
    result = score(world, measured, length_km=10.0)
    assert result.selected == "DMAX"
    assert result.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING
    assert result.within_criterion and not result.comparator_within_criterion
    assert result.scenarios["DMAX"]["psi"] <= 1.0 < result.comparator["psi"]
    assert result.scenarios["NULL"]["psi"] > 1.0  # the no-fibre control cannot explain it either
    assert result.verdict is None  # 2 km selection stage: no verdict, plan R.5
    # the copy fails on the spectrum, which is where a dispersion notch lives
    limits = world["limits"]
    assert (
        result.comparator["metrics"]["M4_log_spectral_distance"]
        > limits["M4_log_spectral_distance"]
    )


def test_a_loss_difference_is_detected_by_level_spacing_and_amplitude(world):
    ratio = 10 ** (-0.5 * 10.0 / 10.0)  # 5 dB of optical loss at the receiver
    # with the signal 10 dB down in receiver noise the dispersion notch is not visible: a lossy
    # scenario with or without dispersion may be selected, which is an identifiability fact
    for borne, expected in ((False, {"LOSS", "BOTH"}), (True, {"LOSS_BORNE"})):
        truth = channel(22, ratio=ratio, noise_follows_signal=borne)
        result = score(world, norm(world, truth), length_km=10.0)
        assert result.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING, result.scenarios
        assert result.selected in expected
        assert result.scenarios["NULL"]["psi"] > 1.0
        copy = result.comparator["metrics"]
        assert copy["M1_level_spacing"] > world["limits"]["M1_level_spacing"]
        assert copy["M2_wasserstein1_amplitude"] > world["limits"]["M2_wasserstein1_amplitude"]


def test_a_b2b_copy_reads_not_discriminating(world):
    other = channel(1)  # same seed: identical symbols, so the "copy" is exact
    again = channel(31)  # a fresh B2B-like record with other symbols and noise
    for truth in (other, again):
        result = score(world, norm(world, truth), length_km=2.0)
        assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
        assert result.comparator_within_criterion
        assert result.verdict in (
            holdout.Verdict.INCONCLUSIVE,
            holdout.Verdict.UNIDENTIFIABLE_PARAMETER,
        )
        assert "also within every limit" in " ".join(result.notes)


def test_a_waveform_no_scenario_can_explain_fails(world):
    truth = channel(23, ratio=0.6)  # neither 1.0 nor the 0.316 loss scenario
    result = score(world, norm(world, truth), length_km=10.0)
    assert result.outcome == e2_score.OUTCOME_FAIL and result.verdict is holdout.Verdict.FAILED
    assert not result.within_criterion
    assert min(v["psi"] for v in result.scenarios.values()) > 1.0


def test_locked_test_scores_the_fixed_scenario_with_the_control_and_can_validate(world):
    truth = channel(25, dispersion=6.352, length_km=10.0)
    measured = norm(world, truth)
    common = {
        "validation_stage": holdout.ValidationStage.NOT_FAILED,
        "sequence_check": holdout.SequenceCheck.NOT_SHARED,
        "state": holdout.HoldoutState.INTACT,
    }
    result = score(world, measured, split=Split.LOCKED_TEST, fixed_scenario="DMAX", **common)
    assert set(result.scenarios) == {"DMAX", "NULL"} and result.selected == "DMAX"
    assert result.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING
    assert result.verdict is holdout.Verdict.VALIDATED
    # without the declarations VALIDATED is not offered (default-deny)
    undeclared = score(world, measured, split=Split.LOCKED_TEST, fixed_scenario="DMAX")
    assert undeclared.verdict is holdout.Verdict.INCONCLUSIVE
    failed_stage = score(
        world, measured, split=Split.LOCKED_TEST, fixed_scenario="DMAX",
        **(common | {"validation_stage": holdout.ValidationStage.FAILED}),
    )  # fmt: skip
    assert failed_stage.verdict is holdout.Verdict.INCONCLUSIVE
    burned = score(
        world, measured, split=Split.LOCKED_TEST, fixed_scenario="DMAX",
        **(common | {"state": holdout.HoldoutState.BURNED}),
    )  # fmt: skip
    assert burned.verdict is holdout.Verdict.INCONCLUSIVE
    # the fixed scenario cannot be one that is not listed, and the 2 km stage cannot fix one
    with pytest.raises(BenchmarkError, match="not in the scenario list"):
        score(world, measured, split=Split.LOCKED_TEST, fixed_scenario="NOPE", **common)
    with pytest.raises(BenchmarkError, match="needs the scenario"):
        score(world, measured, split=Split.LOCKED_TEST, **common)
    with pytest.raises(BenchmarkError, match="selects its own"):
        score(world, measured, fixed_scenario="DMAX")


def test_the_no_fibre_control_never_reads_as_discriminating_even_if_the_copy_fails(world):
    model, scenarios = world["model"], world["scenarios"]
    prediction = e2_score.predict(model, scenarios[0], 2.0, N)  # exactly the control's prediction
    bad_copy = norm(world, channel(61, ratio=0.5))
    result = score(world, prediction, bad_copy, length_km=2.0)
    assert result.selected == "NULL" and result.within_criterion
    assert not result.comparator_within_criterion
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert "chosen scenario is the no-fibre control" in " ".join(result.notes)


def test_a_copy_within_the_limits_is_not_discriminating_even_if_the_control_is_outside(world):
    model, scenarios = world["model"], world["scenarios"]
    dmax = next(s for s in scenarios if s.scenario_id == "DMAX")
    prediction = e2_score.predict(model, dmax, 2.0, N)
    tight = {m: v * 0.01 for m, v in world["limits"].items()}
    result = e2_score.score_windows(
        prediction, prediction.copy(), model=model, scenarios=scenarios, limits=tight,
        length_km=2.0, split=Split.VALIDATION,
    )  # fmt: skip
    assert (
        result.selected == "DMAX" and result.within_criterion and result.comparator_within_criterion
    )
    assert result.scenarios["NULL"]["psi"] > 1.0  # the control alone would not excuse it
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert result.notes == ("the B2B copy is also within every limit",)


def test_a_fibre_scenario_that_the_control_explains_equally_well_is_not_discriminating(world):
    model, scenarios = world["model"], world["scenarios"]
    dmax = next(s for s in scenarios if s.scenario_id == "DMAX")
    prediction = e2_score.predict(model, dmax, 2.0, N)  # a weak 2 km effect: control also fits
    bad_copy = norm(world, channel(62, ratio=0.5))
    result = score(world, prediction, bad_copy, length_km=2.0)
    assert result.selected == "DMAX" and result.scenarios["DMAX"]["psi"] == pytest.approx(
        0.0, abs=1e-9
    )
    assert result.scenarios["NULL"]["psi"] <= 1.0 and not result.comparator_within_criterion
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert "no-fibre control scenario is also within every limit" in " ".join(result.notes)


def test_the_selection_prefers_the_smallest_psi_and_breaks_ties_by_list_order(world):
    measured = norm(world, channel(63, dispersion=6.352, length_km=10.0))
    result = score(world, measured, length_km=10.0)
    psis = {k: v["psi"] for k, v in result.scenarios.items()}
    assert result.selected == min(psis, key=psis.get)
    assert list(result.scenarios) == [
        "NULL",
        "DMAX",
        "LOSS",
        "LOSS_BORNE",
        "BOTH",
    ]  # list order is kept


def test_a_not_discriminating_result_is_unidentifiable_when_no_scenario_was_separable(world):
    measured = norm(world, channel(32))
    quiet = score(world, measured, length_km=2.0, identifiable_in_principle=False)
    assert quiet.verdict is holdout.Verdict.UNIDENTIFIABLE_PARAMETER
    loud = score(world, measured, length_km=2.0, identifiable_in_principle=True)
    assert loud.verdict is holdout.Verdict.INCONCLUSIVE


def test_scoring_core_default_denies_nan_missing_and_malformed_inputs(world):
    good = norm(world, channel(33))
    bad = good.copy()
    bad[100] = np.nan
    with pytest.raises(BenchmarkError, match="non-finite"):
        score(world, bad)
    with pytest.raises(BenchmarkError, match="non-finite"):
        score(world, good, bad)
    inf = good.copy()
    inf[3] = np.inf
    with pytest.raises(BenchmarkError, match="non-finite"):
        score(world, inf)
    with pytest.raises(BenchmarkError, match="exactly"):
        score(world, good[:-1])
    with pytest.raises(BenchmarkError, match="exactly"):
        score(world, good, good[:-5])
    limits = world["limits"]
    for name in holdout.METRICS:
        for value in (np.nan, 0.0, -1.0, np.inf, None):
            patched = dict(limits, **{name: value})
            with pytest.raises(BenchmarkError):
                e2_score.score_windows(
                    good, world["evaluation"], model=world["model"], scenarios=world["scenarios"],
                    limits=patched, length_km=2.0, split=Split.VALIDATION,
                )  # fmt: skip
        missing = {k: v for k, v in limits.items() if k != name}
        with pytest.raises(BenchmarkError, match="exactly"):
            e2_score.score_windows(
                good, world["evaluation"], model=world["model"], scenarios=world["scenarios"],
                limits=missing, length_km=2.0, split=Split.VALIDATION,
            )  # fmt: skip
    with pytest.raises(BenchmarkError, match="not a holdout"):
        score(world, good, split=Split.CHARACTERISATION)
    with pytest.raises(BenchmarkError, match="not a holdout"):
        score(world, good, split=Split.RESERVED)


def test_exceedance_is_the_largest_ratio_and_refuses_bad_metrics():
    limits = dict.fromkeys(holdout.METRICS, 2.0)
    values = dict.fromkeys(holdout.METRICS, 1.0)
    assert e2_score.exceedance(values, limits) == 0.5
    assert e2_score.exceedance(values | {"M3_quantile_error": 5.0}, limits) == 2.5
    for bad in (np.nan, np.inf, -0.1):
        with pytest.raises(BenchmarkError, match="not a finite non-negative"):
            e2_score.exceedance(values | {"M2_wasserstein1_amplitude": bad}, limits)


def test_result_keys_never_name_a_bit_or_symbol_error_rate_or_an_instrument(world):
    result = score(world, norm(world, channel(34)))
    text = repr(result)
    assert not re.search(r"\b(ber|ser)\b|post_fec|serial", text.lower())


def test_preregistration_has_no_result_and_a_separability_flag_for_every_length(world):
    registered = e2_score.compute_preregistration(
        world["model"], world["scenarios"], world["evaluation"], world["limits"], (2.0, 10.0)
    )
    assert set(registered["predictions"]) == {"2", "10"}
    for per_scenario in registered["predictions"].values():
        assert set(per_scenario) == {"NULL", "DMAX", "LOSS", "LOSS_BORNE", "BOTH"}
        assert per_scenario["NULL"]["separable"] is False  # the control is never separable
        for entry in per_scenario.values():
            assert set(entry["separation_from_b2b_copy"]) == set(holdout.METRICS)
    assert registered["identifiable_in_principle"]["10"] is True
    # dispersion at 2 km with the same D is weaker than at 10 km
    two = registered["predictions"]["2"]["DMAX"]["separation_psi"]
    ten = registered["predictions"]["10"]["DMAX"]["separation_psi"]
    assert ten > two
    assert "results" not in registered


def test_the_control_is_never_separable_whatever_the_limits(world):
    tight = {m: 1e-9 for m in holdout.METRICS}
    registered = e2_score.compute_preregistration(
        world["model"], world["scenarios"], world["evaluation"], tight, (2.0,)
    )
    two = registered["predictions"]["2"]
    assert two["NULL"]["separation_psi"] > 1.0 and two["NULL"]["separable"] is False
    assert all(two[k]["separable"] is True for k in ("DMAX", "LOSS", "LOSS_BORNE", "BOTH"))


def test_check_reproduction_refuses_drift_flipped_flags_and_changed_keys(world):
    registered = e2_score.compute_preregistration(
        world["model"], world["scenarios"], world["evaluation"], world["limits"], (2.0,)
    )
    e2_score.check_reproduction(registered, yaml.safe_load(yaml.safe_dump(registered)))
    drifted = yaml.safe_load(yaml.safe_dump(registered))
    drifted["predictions"]["2"]["DMAX"]["summary"]["std"] *= 1.001
    with pytest.raises(BenchmarkError, match="is .* now"):
        e2_score.check_reproduction(registered, drifted)
    tiny = yaml.safe_load(yaml.safe_dump(registered))
    tiny["predictions"]["2"]["DMAX"]["summary"]["std"] *= 1 + 1e-9
    e2_score.check_reproduction(registered, tiny)  # inside the stated tolerance
    flipped = yaml.safe_load(yaml.safe_dump(registered))
    flipped["predictions"]["2"]["DMAX"]["separable"] = not flipped["predictions"]["2"]["DMAX"][
        "separable"
    ]
    with pytest.raises(BenchmarkError, match="changed"):
        e2_score.check_reproduction(registered, flipped)
    dropped = yaml.safe_load(yaml.safe_dump(registered))
    del dropped["predictions"]["2"]["LOSS"]
    with pytest.raises(BenchmarkError, match="keys differ"):
        e2_score.check_reproduction(registered, dropped)


# ---------------------------------------------------------------------------- entry point
HOLDOUT_2KM = "50G_PAM4_PD1_2km_Subassembly1.bin"
HOLDOUT_10KM = "50G_PAM4_PD1_10km_Subassembly1.bin"
B2B_NAME = teriphic.B2B_FILENAME
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid",
}  # fmt: skip


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=os.environ | GIT_ENV,
    )  # fmt: skip
    return done.stdout.strip()


def write_bin(path: Path, samples: np.ndarray, xinc: float = 1.0 / FS) -> None:
    path.write_bytes(keysight_image(samples.astype(np.float32), xinc=xinc))


def fixture_source(directory: Path, files: dict[str, Path]):
    """The real register with the three assets' supplied MD5 replaced by those of the fixtures."""
    source = load_source_config(ROOT / teriphic.CONFIG_PATH)
    assets = []
    for asset in source.assets:
        md5 = hashlib.md5(files[asset.filename].read_bytes()).hexdigest()
        assets.append(dataclasses.replace(asset, checksum=Checksum(md5_supplied=md5)))
    return dataclasses.replace(source, assets=tuple(assets))


class Setup:
    """A git repository holding a frozen criterion, the E2 inputs, code copies, and fixture files."""

    def __init__(self, world, tmp_path: Path, *, freeze: bool = True) -> None:
        self.world = world
        self.root = tmp_path / "repo"
        self.data = tmp_path / "files"
        self.data.mkdir()
        self.root.mkdir()
        copy_code(tmp_path)
        for relative in e2_score.CODE_IDENTITY_FILES:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(tmp_path / "code" / relative, self.root / relative)
        model = dict(world["model_doc"], code_identity=e2_score.code_identity(self.root))
        self.model_doc = model
        self.holdout_2 = self.data / HOLDOUT_2KM
        self.holdout_10 = self.data / HOLDOUT_10KM
        self.b2b = self.data / B2B_NAME
        write_bin(self.b2b, world["b2b"])
        write_bin(self.holdout_2, channel(41, dispersion=6.352, length_km=2.0, ratio=0.97))
        write_bin(self.holdout_10, channel(42, dispersion=6.352, length_km=10.0))
        self.sha = {
            HOLDOUT_2KM: hashlib.sha256(self.holdout_2.read_bytes()).hexdigest(),
            HOLDOUT_10KM: hashlib.sha256(self.holdout_10.read_bytes()).hexdigest(),
        }
        self.source = fixture_source(
            tmp_path,
            {B2B_NAME: self.b2b, HOLDOUT_2KM: self.holdout_2, HOLDOUT_10KM: self.holdout_10},
        )
        self.write_documents()
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "inputs")
        if freeze:
            self.freeze()

    def comparator(self) -> np.ndarray:
        """The B2B window as the scorer reads it: through the float32 file."""
        stored = self.world["b2b"].astype(np.float32).astype(np.float64)
        return e2_metrics.normalise(
            window(stored, "evaluation"), self.world["c0"], self.world["g0"]
        )

    def write_documents(self) -> None:
        e2 = self.root / e2_score.E2_DIR
        e2.mkdir(parents=True, exist_ok=True)
        (self.root / holdout.DEFAULT_PLAN).parent.mkdir(parents=True, exist_ok=True)
        (self.root / holdout.DEFAULT_PLAN).write_text("fixture plan text\n")
        model_bytes = yaml.safe_dump(self.model_doc, sort_keys=False).encode()
        (self.root / e2_score.MODEL_PATH).write_bytes(model_bytes)
        scenario_bytes = yaml.safe_dump(self.world["scenarios_doc"], sort_keys=False).encode()
        (self.root / e2_score.SCENARIO_PATH).write_bytes(scenario_bytes)
        model = e2_score.check_model(yaml.safe_load(model_bytes))
        scenarios = e2_score.check_scenarios(yaml.safe_load(scenario_bytes))
        registered = e2_score.compute_preregistration(
            model, scenarios, self.comparator(), self.world["limits"], (2.0, 10.0)
        )
        document = {
            "preregistration_version": 1,
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "scenario_list_sha256": hashlib.sha256(scenario_bytes).hexdigest(),
            "scenario_count": len(scenarios),
            "limits": self.world["limits"],
            **registered,
            "results": None,
        }
        (self.root / e2_score.PREREGISTRATION_PATH).write_text(yaml.safe_dump(document))
        (self.root / e2_score.SELECTED_PATH).write_text(
            yaml.safe_dump({"scenario_id": "DMAX", "selected_at_stage": "2km"})
        )
        (self.root / e2_score.EVALUATION_SCRIPT).parent.mkdir(exist_ok=True)
        (self.root / e2_score.EVALUATION_SCRIPT).write_text("# evaluation script fixture\n")

    def criterion_document(self) -> dict:
        plan = (self.root / holdout.DEFAULT_PLAN).read_bytes()
        basis = self.world["basis"]
        return {
            "criterion_version": 3,
            "plan_sha256": hashlib.sha256(plan).hexdigest(),
            "limits": self.world["limits"],
            "b2b_basis": basis,
            "multipliers": dict.fromkeys(holdout.METRICS, MULTIPLIER),
            "estimators": dict(holdout.ESTIMATORS),
        }

    def freeze(self) -> None:
        path = self.root / holdout.CRITERION_PATH
        path.write_text(yaml.safe_dump(self.criterion_document()))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "freeze")

    def score(self, which=None, **extra):
        target = which or self.holdout_2
        arguments = {
            "b2b_path": self.b2b, "repo_root": self.root, "source": self.source,
            "holdout_sha256": self.sha,
        }  # fmt: skip
        if target == self.holdout_10:
            arguments["validation_stage"] = holdout.ValidationStage.NOT_FAILED
        return e2_score.score_holdout(target, **(arguments | extra))


@pytest.fixture
def setup(world, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Setup(world, tmp_path)


@pytest.fixture
def unfrozen(world, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Setup(world, tmp_path, freeze=False)


def forbid_reads(monkeypatch):
    """Any hash, header or sample read, or B2B gate, raises: the criterion must refuse first."""

    def boom(*args, **kwargs):
        raise AssertionError("a file was read before the frozen criterion was checked")

    monkeypatch.setattr(e2_score, "verify_local_asset", boom)
    monkeypatch.setattr(e2_score.ExternalCapture, "open_keysight_bin", boom)
    monkeypatch.setattr(e2_score.teriphic, "gate_sample_read", boom)
    monkeypatch.setattr(Path, "read_bytes", _guard_read_bytes(Path.read_bytes))


def _guard_read_bytes(original):
    def guarded(self):
        if self.suffix == ".bin":
            raise AssertionError(f"{self.name} was read before the criterion was checked")
        return original(self)

    return guarded


def test_the_scorer_runs_end_to_end_on_a_frozen_fixture_and_reports_no_error_rate(setup):
    result = setup.score()
    report = result.report()
    assert report["filename"] == HOLDOUT_2KM and report["length_km"] == 2.0
    assert report["split"] == "VALIDATION" and report["hashes_verified"] is True
    assert report["criterion_commit"] == git(setup.root, "log", "--format=%H", "-1", "--",
                                              str(holdout.CRITERION_PATH))  # fmt: skip
    assert (
        report["scenarios_scored"] == 5
        and report["reference_sequence"] == "REFERENCE_SEQUENCE_MISSING"
    )
    assert report["fibre_knowledge"]["fibre_type"] == "UNKNOWN"
    assert "MODEL GAP" in report["fibre_knowledge"]["chirp"]
    assert any("CHIRP" in gap for gap in report["model_gaps"])
    assert report["outcome"] in {
        e2_score.OUTCOME_FAIL,
        e2_score.OUTCOME_PASS_DISCRIMINATING,
        e2_score.OUTCOME_PASS_NOT_DISCRIMINATING,
    }
    assert not re.search(r"\b(ber|ser)\b|post_fec|serial", repr(report).lower())
    ten = setup.score(setup.holdout_10)
    assert ten.report()["split"] == "LOCKED_TEST" and ten.selected_scenario == "DMAX"
    assert set(ten.scenarios) == {"DMAX", "NULL"}


def test_no_frozen_criterion_refuses_before_any_file_is_touched(unfrozen, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score()
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score(unfrozen.holdout_10)
    # even a holdout path that does not exist: the refusal comes first
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score(
            unfrozen.data / HOLDOUT_2KM.replace("2km", "2km").upper().replace(".BIN", ".bin")
        )


def test_a_criterion_in_the_working_tree_but_not_committed_is_refused(unfrozen, monkeypatch):
    forbid_reads(monkeypatch)
    (unfrozen.root / holdout.CRITERION_PATH).write_text(
        yaml.safe_dump(unfrozen.criterion_document())
    )
    with pytest.raises(BenchmarkError, match="not committed"):
        unfrozen.score()


def test_an_altered_criterion_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    path = setup.root / holdout.CRITERION_PATH
    original = path.read_text()
    document = yaml.safe_load(original)
    document["limits"]["M4_log_spectral_distance"] *= 10
    document["multipliers"]["M4_log_spectral_distance"] *= 10
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(BenchmarkError, match="modified since HEAD"):
        setup.score()  # altered and not committed
    git(setup.root, "add", "-A")
    git(setup.root, "commit", "-q", "-m", "loosen")
    with pytest.raises(BenchmarkError, match="changed after the first commit"):
        setup.score()  # altered and committed: the loosened limit is not a freeze
    path.write_text(original)
    git(setup.root, "add", "-A")
    git(setup.root, "commit", "-q", "-m", "restore")
    with pytest.raises(BenchmarkError, match="changed after the first commit"):
        setup.score()  # restoring does not undo the change in history


def test_a_stale_criterion_after_a_plan_change_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    plan = setup.root / holdout.DEFAULT_PLAN
    plan.write_text(plan.read_text() + "a later change\n")
    with pytest.raises(BenchmarkError, match="modified since HEAD"):
        setup.score()
    git(setup.root, "add", "-A")
    git(setup.root, "commit", "-q", "-m", "plan changed")
    with pytest.raises(BenchmarkError, match="another version of the plan"):
        setup.score()


def test_a_missing_or_changed_input_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    model = setup.root / e2_score.MODEL_PATH
    model.write_text(model.read_text() + "\n")
    with pytest.raises(BenchmarkError, match="modified since HEAD"):
        setup.score()
    git(setup.root, "checkout", "--", str(e2_score.MODEL_PATH))
    git(setup.root, "rm", "-q", str(e2_score.SELECTED_PATH))
    git(setup.root, "commit", "-q", "-m", "drop selected scenario")
    monkeypatch.undo()
    setup.score()  # the 2 km stage does not need it
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="selected_scenario|not committed|cannot be read"):
        setup.score(setup.holdout_10)


def test_the_10km_stage_needs_the_2km_stage_declared(setup, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="2 km stage is done"):
        e2_score.score_holdout(
            setup.holdout_10, b2b_path=setup.b2b, repo_root=setup.root, source=setup.source,
            holdout_sha256=setup.sha,
        )  # fmt: skip


def test_a_holdout_whose_hash_mismatches_is_refused_and_never_opened(setup, monkeypatch):
    opened = []
    real_open = e2_score.ExternalCapture.open_keysight_bin

    def spy(path, *args, **kwargs):
        opened.append(Path(path).name)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(e2_score.ExternalCapture, "open_keysight_bin", spy)
    wrong_sha = dict(setup.sha, **{HOLDOUT_2KM: "0" * 64})
    with pytest.raises(BenchmarkError, match="does not match the recorded"):
        setup.score(holdout_sha256=wrong_sha)
    data = bytearray(setup.holdout_2.read_bytes())
    data[-1] ^= 0x01
    setup.holdout_2.write_bytes(bytes(data))  # one altered byte: MD5 (register) and SHA-256 differ
    with pytest.raises(BenchmarkError, match="does not match the recorded"):
        setup.score()
    with pytest.raises(BenchmarkError, match="no recorded SHA-256"):
        setup.score(holdout_sha256={})
    assert opened == []  # no header, no sample: refused before the reader


def test_an_md5_mismatch_alone_is_refused_even_with_a_matching_sha(setup):
    other = dataclasses.replace(
        next(a for a in setup.source.assets if a.filename == HOLDOUT_2KM),
        checksum=Checksum(md5_supplied="1" * 32),
    )
    assets = tuple(other if a.filename == HOLDOUT_2KM else a for a in setup.source.assets)
    source = dataclasses.replace(setup.source, assets=assets)
    with pytest.raises(BenchmarkError, match="does not match the recorded"):
        setup.score(source=source)


def test_only_registered_2km_and_10km_files_can_be_scored(setup, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="not a registered 2 km or 10 km holdout"):
        setup.score(setup.b2b)
    renamed = setup.data / "renamed.bin"
    shutil.copy(setup.holdout_2, renamed)
    with pytest.raises(BenchmarkError, match="not a registered 2 km or 10 km holdout"):
        setup.score(renamed)
    with pytest.raises(BenchmarkError, match="not a registered 2 km or 10 km holdout") as raised:
        setup.score(setup.data / "50G_PAM4_PD2_2km_Subassembly1.bin")
    assert raised.value.code is ErrorCode.LEAKAGE_DETECTED


def test_a_changed_code_file_is_refused_by_the_code_identity(setup, monkeypatch):
    forbid_reads(monkeypatch)
    target = setup.root / e2_score.CODE_IDENTITY_FILES[0]
    target.write_text(target.read_text() + "\n# tweak\n")
    with pytest.raises(BenchmarkError, match="code identity"):
        setup.score()


def test_preregistration_must_be_tied_to_the_model_and_scenarios_and_hold_no_result(
    setup, monkeypatch
):
    forbid_reads(monkeypatch)
    path = setup.root / e2_score.PREREGISTRATION_PATH
    document = yaml.safe_load(path.read_text())

    def commit_with(change: dict, message: str):
        path.write_text(yaml.safe_dump(document | change))
        git(setup.root, "add", "-A")
        git(setup.root, "commit", "-q", "-m", message)

    commit_with({"results": {"2": {"M1": 0.1}}}, "result column filled")
    with pytest.raises(BenchmarkError, match="result column is filled"):
        setup.score()
    commit_with({"results": None, "model_sha256": "0" * 64}, "untied")
    with pytest.raises(BenchmarkError, match="not tied"):
        setup.score()
    commit_with({"model_sha256": document["model_sha256"], "scenario_list_sha256": "0" * 64}, "t2")
    with pytest.raises(BenchmarkError, match="not tied"):
        setup.score()
    commit_with(
        {"scenario_list_sha256": document["scenario_list_sha256"], "scenario_count": 9}, "count"
    )
    with pytest.raises(BenchmarkError, match="scenario count"):
        setup.score()
    commit_with(
        {"scenario_count": 5, "limits": dict(document["limits"], M1_level_spacing=9.0)}, "lim"
    )
    with pytest.raises(BenchmarkError, match="differs from the frozen"):
        setup.score()


@pytest.mark.parametrize("which", ["model", "scenarios"])
def test_the_committed_bytes_read_for_scoring_must_equal_the_bytes_the_guard_hashed(
    setup, monkeypatch, which
):
    real = e2_score._committed_bytes
    target = e2_score.MODEL_PATH if which == "model" else e2_score.SCENARIO_PATH

    def altered(root, path, what):
        data, relative = real(root, path, what)
        return (data + b"\n", relative) if Path(path).name == target.name else (data, relative)

    monkeypatch.setattr(e2_score, "_committed_bytes", altered)
    with pytest.raises(BenchmarkError, match="differ from the input the guard hashed"):
        setup.score()


def test_a_drifted_preregistered_value_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    path = setup.root / e2_score.PREREGISTRATION_PATH
    document = yaml.safe_load(path.read_text())
    document["predictions"]["2"]["DMAX"]["summary"]["std"] *= 1.01
    path.write_text(yaml.safe_dump(document))
    git(setup.root, "add", "-A")
    git(setup.root, "commit", "-q", "-m", "drift")
    monkeypatch.undo()
    with pytest.raises(BenchmarkError, match="pre-registered predictions: .*std"):
        setup.score()


def test_a_header_with_another_sample_rate_or_a_short_record_is_blocked(setup):
    write_bin(setup.holdout_2, channel(41), xinc=1.0 / 2e11)
    setup.sha[HOLDOUT_2KM] = hashlib.sha256(setup.holdout_2.read_bytes()).hexdigest()
    source = fixture_source(
        setup.data.parent,
        {B2B_NAME: setup.b2b, HOLDOUT_2KM: setup.holdout_2, HOLDOUT_10KM: setup.holdout_10},
    )
    result = setup.score(source=source)
    assert result.outcome == e2_score.OUTCOME_BLOCKED and result.verdict == "BLOCKED"
    assert "sample rate" in " ".join(result.notes) and result.scenarios == {}
    write_bin(setup.holdout_2, channel(41, n=N))
    setup.sha[HOLDOUT_2KM] = hashlib.sha256(setup.holdout_2.read_bytes()).hexdigest()
    source = fixture_source(
        setup.data.parent,
        {B2B_NAME: setup.b2b, HOLDOUT_2KM: setup.holdout_2, HOLDOUT_10KM: setup.holdout_10},
    )
    short = setup.score(source=source)
    assert short.outcome == e2_score.OUTCOME_BLOCKED and "shorter" in " ".join(short.notes)


def test_a_nan_in_the_holdout_window_is_refused_not_scored(setup):
    samples = channel(43, dispersion=6.352, length_km=2.0)
    samples[2 * N + 500] = np.nan
    write_bin(setup.holdout_2, samples)
    setup.sha[HOLDOUT_2KM] = hashlib.sha256(setup.holdout_2.read_bytes()).hexdigest()
    source = fixture_source(
        setup.data.parent,
        {B2B_NAME: setup.b2b, HOLDOUT_2KM: setup.holdout_2, HOLDOUT_10KM: setup.holdout_10},
    )
    with pytest.raises(BenchmarkError):
        setup.score(source=source)


def test_the_b2b_comparator_must_be_the_b2b_capture(setup):
    wrong = setup.data / "other_b2b.bin"
    write_bin(wrong, channel(77))
    with pytest.raises(BenchmarkError, match="not the B2B capture"):
        setup.score(b2b_path=wrong)


# ---------------------------------------------------------------------------- routing (source scan)
def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            yield name, node.lineno


def test_only_the_scorer_and_the_b2b_adapter_open_captures_in_src():
    readers = {"open_keysight_bin", "open_raw", "read_bin", "read_scope_file"}
    callers: dict[str, set[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        for name, _ in _calls(ast.parse(path.read_text())):
            if name in readers:
                callers.setdefault(path.relative_to(ROOT).as_posix(), set()).add(name)
    allowed = {
        "src/opticps/benchmarks/e2_score.py",  # the one holdout reader
        "src/opticps/benchmarks/teriphic.py",  # B2B adapter and the gated inspect route
        "src/opticps/measurement/uxr_import.py",  # generic reader, listed in the known limits
        "src/opticps/measurement/uxr_ingest.py",  # `ingest-uxr`, CLI-gated, listed in the limits
    }
    assert set(callers) <= allowed, set(callers) - allowed
    assert "src/opticps/benchmarks/e2_score.py" in callers


def test_the_scoring_entry_point_calls_the_frozen_criterion_before_any_read():
    tree = ast.parse((ROOT / "src/opticps/benchmarks/e2_score.py").read_text())
    function = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "score_holdout"
    )
    calls = sorted(_calls(function), key=lambda item: item[1])
    order = [name for name, _ in calls]
    guard = order.index("require_frozen_criterion")
    for reader in ("verify_local_asset", "open_keysight_bin", "gate_sample_read", "read"):
        assert reader in order
        assert guard < order.index(reader), reader
    assert order.index("verify_local_asset") < order.index("open_keysight_bin")
    assert order.index("verify_code_identity") < order.index("verify_local_asset")


def test_no_other_module_in_src_imports_the_scorer_or_calls_the_guard():
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.endswith(("e2_score.py", "holdout.py")):
            continue
        text = path.read_text()
        assert "require_frozen_criterion(" not in text, relative
        assert "score_holdout" not in text, relative


def test_the_freeze_script_never_reads_a_holdout_or_imports_the_scorer_entry_point():
    text = (ROOT / "scripts/freeze_teriphic_e2.py").read_text()
    assert "score_holdout" not in text and "HOLDOUT_SHA256" not in text
    assert "50G_PAM4_PD1_2km" not in text and "50G_PAM4_PD1_10km" not in text
    assert "open_b2b" in text


# ---------------------------------------------------------------------------- the committed freeze
REAL_B2B = ROOT / "data/external/teriphic" / B2B_NAME
real_b2b = pytest.mark.skipif(not REAL_B2B.exists(), reason="the B2B capture is not present")


def real_documents():
    model_bytes = (ROOT / e2_score.MODEL_PATH).read_bytes()
    scenario_bytes = (ROOT / e2_score.SCENARIO_PATH).read_bytes()
    registered = yaml.safe_load((ROOT / e2_score.PREREGISTRATION_PATH).read_bytes())
    return model_bytes, scenario_bytes, registered


def test_real_committed_documents_are_tied_and_hold_no_result():
    model_bytes, scenario_bytes, registered = real_documents()
    model = e2_score.check_model(yaml.safe_load(model_bytes))
    scenarios = e2_score.check_scenarios(yaml.safe_load(scenario_bytes))
    assert registered["model_sha256"] == hashlib.sha256(model_bytes).hexdigest()
    assert registered["scenario_list_sha256"] == hashlib.sha256(scenario_bytes).hexdigest()
    assert registered["results"] is None and registered["scenario_count"] == len(scenarios) == 9
    assert set(registered["limits"]) == set(holdout.METRICS)
    for metric in holdout.METRICS:
        assert registered["limits"][metric] == pytest.approx(
            registered["b2b_basis"][metric] * registered["multipliers"][metric], rel=1e-12
        )
    assert model["parameters"]["wavelength_nm"]["provenance"] == "UNKNOWN"
    assert model["parameters"]["chirp_alpha"]["provenance"] == "UNKNOWN"
    assert set(registered["predictions"]) == {"2", "10"}
    text = (ROOT / e2_score.PREREGISTRATION_PATH).read_text().lower()
    assert not re.search(r"\b(ber|ser)\b|post_fec|serial", text)
    assert "50g_pam4_pd1_2km" not in text and "50g_pam4_pd1_10km" not in text


def test_real_committed_identity_matches_the_working_code():
    model = e2_score.check_model(yaml.safe_load((ROOT / e2_score.MODEL_PATH).read_bytes()))
    e2_score.verify_code_identity(model, ROOT)


@real_b2b
def test_real_preregistered_values_reproduce_from_b2b_alone():
    """B2B only: recompute the pre-registered predictions and compare (tolerance 1e-6)."""
    model_bytes, scenario_bytes, registered = real_documents()
    model = e2_score.check_model(yaml.safe_load(model_bytes))
    scenarios = e2_score.check_scenarios(yaml.safe_load(scenario_bytes))
    capture = teriphic.open_b2b(REAL_B2B)
    try:
        w = model["windows"]["evaluation"]
        raw = capture.read(w["start"], w["start"] + w["samples"])
    finally:
        capture.close()
    norm_ = model["normalisation"]
    comparator = e2_metrics.normalise(raw, norm_["c0"], norm_["g0"])
    recomputed = e2_score.compute_preregistration(
        model, scenarios, comparator, registered["limits"], (2.0, 10.0)
    )
    e2_score.check_reproduction(
        {k: registered[k] for k in ("predictions", "identifiable_in_principle")}, recomputed
    )
