"""Gate E2 part a: frozen estimators, B2B surrogate, scorer entry point (Stage 3A).

Every fixture is synthetic. The noise-free PAM4 pulse train comes from the surrogate's own pulse
generator (a Gaussian low-pass, levels the fit never sees), so a PASS on fixture truth proves little
about the physics; the fibre (cos(pi lambda^2 D L f^2 / c) by FFT), the gain, the noise and the
unmodelled low-pass are applied by this file's own code with a separate generator, and the refusal
tests do not depend on the model form. No TERIPHIC
sample is read except in the tests whose name starts with `test_real_`, which read the B2B file only
and skip when it is absent. The 2 km and 10 km files are never opened here.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import types
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
    noise_through_fibre: bool = False,
    low_pass_hz: float | None = None,
) -> np.ndarray:
    """A PAM4 record with a fibre applied by this file's own derivation.

    The noise-free pulse train comes from the surrogate's generator (a Gaussian low-pass and the
    levels of `TRUE_MODEL`, which the fit never sees); the fibre (cos(pi lambda^2 D L f^2 / c) by
    FFT over the whole record), the gain, the noise and an optional unmodelled Gaussian low-pass
    are applied here, with a separate random generator.
    """
    clean = e2_model.synthesize(
        TRUE_MODEL, n_samples=n, symbol_seed=seed, noise_seed=seed + 1, sigma=0.0
    )
    f = np.fft.rfftfreq(n, 1.0 / FS)
    theta = math.pi * LAMBDA**2 * (dispersion * 1e-6) * (length_km * 1e3) * f**2 / LIGHT
    rng = np.random.default_rng(seed + 5000)
    floor = np.fft.irfft(
        np.fft.rfft(rng.normal(size=n))
        * np.sqrt(np.interp(f, np.arange(2049) * FS / 4096, TRUE_PSD)),
        n,
    )
    floor *= noise / floor.std()
    response = np.cos(theta)
    x = np.fft.irfft(np.fft.rfft(clean + (floor if noise_through_fibre else 0.0)) * response, n)
    x = x + (0.0 if noise_through_fibre else floor)
    if low_pass_hz is not None:
        x = np.fft.irfft(np.fft.rfft(x) * np.exp(-0.5 * math.log(2) * (f / low_pass_hz) ** 2), n)
    return x * ratio


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

    def entry(identifier, dispersion, factor=1.0, through=False, null=False):
        return {
            "id": identifier, "dispersion_ps_nm_km": dispersion, "noise_factor": factor,
            "noise_through_fibre": through, "null_control": null, "label": identifier,
        }  # fmt: skip

    scenarios_doc = {
        "scenario_list_version": e2_score.SCENARIO_VERSION,
        "count": 6,
        "scenarios": [
            entry("NULL", 0.0, null=True),
            entry("D3", 3.0),
            entry("D6", 6.352),
            entry("D6_THRU", 6.352, through=True),
            entry("N2", 0.0, 2.0),
            entry("D6_N2", 6.352, 2.0),
        ],
        "provenance": {"status": "fixture"},
    }
    scenarios = e2_score.check_scenarios(scenarios_doc)
    checked = e2_score.check_model(model)
    ev = e2_metrics.normalise(window(b2b, "evaluation"), c0, g0)
    sp = e2_metrics.normalise(window(b2b, "spread"), c0, g0)
    surrogate = e2_score.predict(checked, scenarios[0], 0.0, N)
    copy_summary = e2_score.window_summary(ev, FS, BAUD)
    misfit = e2_metrics.metrics_between(copy_summary, e2_score.window_summary(surrogate, FS, BAUD))
    spread = e2_metrics.metrics_between(copy_summary, e2_score.window_summary(sp, FS, BAUD))
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


def test_the_amplitude_ratio_scales_the_signal_and_the_noise_follows_only_when_asked(world):
    base = dict(world["model"])
    kw = {"n_samples": 1 << 15, "symbol_seed": 3, "noise_seed": 4}
    quiet = dict(base, noise_sigma=0.0)
    full = e2_model.synthesize(quiet, sigma=0.0, **kw)
    half = e2_model.synthesize(quiet, sigma=0.0, amplitude_ratio=0.5, **kw)
    assert half == pytest.approx(0.5 * full, abs=1e-12)
    silent = dict(base, pulse_levels=[0.0] * 4)
    plain = e2_model.synthesize(silent, sigma=1.0, **kw)
    unscaled = e2_model.synthesize(silent, sigma=1.0, amplitude_ratio=0.5, **kw)
    follows = e2_model.synthesize(
        silent, sigma=1.0, amplitude_ratio=0.5, noise_follows_signal=True, **kw
    )
    assert unscaled == pytest.approx(plain, abs=1e-12)  # receiver noise: not scaled
    assert follows == pytest.approx(0.5 * plain, abs=1e-12)  # signal-borne noise: scaled


def test_noise_through_the_fibre_is_filtered_by_the_dispersion_response(world):
    silent = dict(world["model"], pulse_levels=[0.0] * 4)
    kwargs = {"n_samples": 1 << 17, "symbol_seed": 1, "noise_seed": 2, "sigma": 1.0}
    plain = e2_model.synthesize(silent, dispersion_ps_nm_km=6.352, length_km=10.0, **kwargs)
    crossed = e2_model.synthesize(
        silent, dispersion_ps_nm_km=6.352, length_km=10.0, noise_through_fibre=True, **kwargs
    )
    f, p0 = e2_metrics.welch_density(plain, FS)
    _, p1 = e2_metrics.welch_density(crossed, FS)
    band = (f > 35e9) & (f < 39e9)  # around the null of 37 GHz
    assert p1[band].mean() < 0.1 * p0[band].mean()
    low = (f > 2e9) & (f < 8e9)
    assert p1[low].mean() == pytest.approx(p0[low].mean(), rel=0.2)
    again = e2_model.synthesize(
        silent, dispersion_ps_nm_km=0.0, length_km=0.0, noise_through_fibre=True, **kwargs
    )
    assert again == pytest.approx(
        e2_model.synthesize(silent, dispersion_ps_nm_km=0.0, length_km=0.0, **kwargs)
    )


def test_renormalise_removes_gain_and_offset_and_reports_them():
    x = point_masses((-1.5, -0.5, 0.5, 1.5), spread=0.1, seed=11)
    y = 0.4 * x + 0.7
    out, centre, gap = e2_metrics.renormalise(y)
    ref, c0, g0 = e2_metrics.renormalise(x)
    assert out == pytest.approx(ref, abs=1e-9)
    assert gap == pytest.approx(0.4 * g0, rel=1e-9) and centre == pytest.approx(0.4 * c0 + 0.7)
    with pytest.raises(BenchmarkError, match="non-finite"):
        e2_metrics.renormalise(np.r_[np.nan, x])


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


def test_the_pre_registration_description_comes_from_the_window_summary(world):
    window10 = e2_score.predict(world["model"], world["scenarios"][2], 10.0, N)
    summary = e2_score.window_summary(window10, FS, BAUD)
    described = e2_score.describe(summary, BAUD)
    renormalised, _, gap = e2_metrics.renormalise(window10)
    assert described["gaps"] == pytest.approx(list(summary.gaps))
    assert described["std"] == pytest.approx(float(renormalised.std()), rel=1e-12)
    assert sum(described["cluster_shares"]) == pytest.approx(1.0)
    assert described["quantiles"]["0.5"] == pytest.approx(float(np.median(renormalised)), abs=1e-3)
    bands = described["psd_db_by_5ghz_band_rel_peak"]
    assert len(bands) == 10 and max(bands) <= 1e-9
    assert gap > 0


def test_the_code_identity_is_the_import_closure_of_the_scoring_entry_point():
    """A fresh interpreter imports the scorer; every opticps module it loads must be listed."""
    code = (
        "import sys, opticps.benchmarks.e2_score;"
        "print('\\n'.join(sorted(m.__file__ for n, m in sys.modules.items()"
        " if n.startswith('opticps') and getattr(m, '__file__', None))))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True, env={"PYTHONPATH": str(ROOT / "src")},
    )  # fmt: skip
    loaded = {Path(line).resolve().relative_to(ROOT).as_posix() for line in done.stdout.split()}
    assert loaded == set(e2_score.CODE_IDENTITY_FILES)


def test_a_code_identity_module_that_is_not_loaded_is_refused(monkeypatch):
    monkeypatch.delitem(sys.modules, "opticps.benchmarks.timing")
    with pytest.raises(BenchmarkError, match="module opticps.benchmarks.timing is not loaded"):
        e2_score.loaded_code_files()


def test_the_loaded_modules_must_be_the_files_of_the_repository_being_checked(tmp_path):
    e2_score.verify_loaded_code(ROOT)
    other = copy_code(tmp_path)
    with pytest.raises(BenchmarkError, match="not the code of"):
        e2_score.verify_loaded_code(other)


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
    assert len(e2_score.check_scenarios(doc)) == 6
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
    with pytest.raises(BenchmarkError, match="exactly one|control must be"):
        e2_score.check_scenarios(doc | {"scenarios": two_null})
    for bad in (np.nan, -1.0, "x", True):
        entry = dict(doc["scenarios"][1], dispersion_ps_nm_km=bad)
        with pytest.raises(BenchmarkError):
            e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    for bad in (np.inf, np.nan, 0.0, -1.0, "x"):
        entry = dict(doc["scenarios"][1], noise_factor=bad)
        with pytest.raises(BenchmarkError):
            e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    entry = dict(doc["scenarios"][1], dispersion_ps_nm_km=0.0, noise_through_fibre=True)
    with pytest.raises(BenchmarkError, match="nothing for noise to cross"):
        e2_score.check_scenarios(doc | {"scenarios": [doc["scenarios"][0], entry], "count": 2})
    entry = dict(doc["scenarios"][0], noise_factor=1.5)
    with pytest.raises(BenchmarkError, match="control must be"):
        e2_score.check_scenarios(doc | {"scenarios": [entry], "count": 1})
    entry = dict(doc["scenarios"][1], noise_through_fibre="yes")
    with pytest.raises(BenchmarkError, match="true or false"):
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
    named = "src/opticps/benchmarks/e2_model.py"
    target = copy / named
    target.write_text(target.read_text() + "\n# changed\n")
    with pytest.raises(BenchmarkError, match="e2_model.py"):
        e2_score.verify_code_identity(model, copy)
    target.unlink()
    with pytest.raises(BenchmarkError, match="missing"):
        e2_score.code_identity(copy)
    link = copy / named
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
    result = score(world, norm(world, truth), length_km=10.0)
    assert "D6" in result.survivors and result.best in {"D6", "D6_THRU"}
    assert result.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING
    assert result.claim == "PARTIAL" and result.verdict is None  # 2 km stage: no verdict
    assert result.within_criterion and not result.comparator_within_criterion
    assert result.scenarios["NULL"]["psi"] > 1.0 and result.comparator["psi"] > 1.0
    limits = world["limits"]
    assert (
        result.comparator["metrics"]["M4_log_spectral_distance"]
        > limits["M4_log_spectral_distance"]
    )


def test_amplitude_is_reported_not_tested(world):
    plain = score(world, norm(world, channel(22, dispersion=6.352, length_km=10.0)))
    scaled = score(world, norm(world, channel(22, dispersion=6.352, length_km=10.0, ratio=0.4)))
    assert scaled.outcome == plain.outcome and scaled.survivors == plain.survivors
    assert scaled.gain_ratio == pytest.approx(0.4 * plain.gain_ratio, rel=2e-3)
    for name, value in plain.scenarios["D6"]["metrics"].items():
        assert scaled.scenarios["D6"]["metrics"][name] == pytest.approx(value, abs=2e-3)


def test_a_signal_to_noise_change_is_a_scenario_not_a_failure(world):
    truth = channel(23, noise=0.25 * 2.0)
    result = score(world, norm(world, truth), length_km=2.0)
    assert "N2" in result.survivors and result.outcome != e2_score.OUTCOME_FAIL
    assert result.scenarios["NULL"]["psi"] > result.scenarios["N2"]["psi"]


def test_noise_crossing_the_fibre_is_the_other_bound_and_is_a_scenario(world):
    truth = channel(24, dispersion=6.352, length_km=10.0, noise_through_fibre=True)
    result = score(world, norm(world, truth), length_km=10.0)
    assert "D6_THRU" in result.survivors
    assert result.scenarios["D6_THRU"]["psi"] < result.scenarios["D6"]["psi"]


def test_a_b2b_copy_reads_not_discriminating(world):
    for truth in (channel(1), channel(31)):
        result = score(world, norm(world, truth), length_km=2.0)
        assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
        assert result.comparator_within_criterion and result.claim is None
        assert result.verdict in (
            holdout.Verdict.INCONCLUSIVE,
            holdout.Verdict.UNIDENTIFIABLE_PARAMETER,
        )
        assert "also within every limit" in " ".join(result.notes)


def test_an_unmodelled_low_pass_that_no_scenario_explains_fails(world):
    truth = channel(25, low_pass_hz=16e9)
    result = score(world, norm(world, truth), length_km=10.0)
    assert result.outcome == e2_score.OUTCOME_FAIL and result.verdict is holdout.Verdict.FAILED
    assert result.claim is None  # a 2 km FAIL is a plain FAILED: dispersion hardly acts at 2 km
    assert not result.within_criterion and result.survivors == () and result.carry_forward == ()
    assert min(v["psi"] for v in result.scenarios.values()) > 1.0


def locked(world, measured, carried, **extra):
    return score(world, measured, split=Split.LOCKED_TEST, carried=carried, length_km=10.0, **extra)


def test_locked_test_scores_the_carried_scenarios_with_the_control_and_is_capped(world):
    measured = norm(world, channel(26, dispersion=6.352, length_km=10.0))
    common = {
        "validation_stage": holdout.ValidationStage.NOT_FAILED,
        "sequence_check": holdout.SequenceCheck.NOT_SHARED,
        "state": holdout.HoldoutState.INTACT,
    }
    result = locked(world, measured, ["D6", "D3"], **common)
    assert set(result.scenarios) == {"NULL", "D3", "D6"}
    assert result.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING and result.claim == "PARTIAL"
    # VALIDATED is allowed by the role table here and is still never returned (plan R12.4)
    assert holdout.Verdict.VALIDATED in holdout.allowed_verdicts(Split.LOCKED_TEST, **common)
    assert result.verdict is holdout.Verdict.INCONCLUSIVE
    assert locked(world, measured, ["D6"]).verdict is holdout.Verdict.INCONCLUSIVE
    assert result.survivors and set(result.survivors) <= {"D3", "D6"}


def test_a_burned_file_ends_exploratory_and_a_shared_sequence_does_too(world):
    measured = norm(world, channel(27, dispersion=6.352, length_km=10.0))
    burned = locked(world, measured, ["D6"], state=holdout.HoldoutState.BURNED)
    assert burned.verdict is holdout.Verdict.EXPLORATORY
    assert burned.verdict in holdout.allowed_verdicts(
        Split.LOCKED_TEST, state=holdout.HoldoutState.BURNED
    )
    failing = norm(world, channel(28, low_pass_hz=16e9))
    burned_fail = locked(world, failing, ["D6"], state=holdout.HoldoutState.BURNED)
    assert burned_fail.outcome == e2_score.OUTCOME_FAIL
    assert burned_fail.verdict is holdout.Verdict.EXPLORATORY  # not FAILED: outside the allowed set
    plain_fail = locked(world, failing, ["D6"])
    # at 10 km a FAIL may be the grid (power study): INCONCLUSIVE with its own claim, never FAILED
    assert plain_fail.outcome == e2_score.OUTCOME_FAIL
    assert plain_fail.verdict is holdout.Verdict.INCONCLUSIVE
    assert plain_fail.claim == "NO_SCENARIO_FITS" and "not FAILED" in " ".join(plain_fail.notes)
    shared = holdout.SequenceCheck.SHARED
    assert locked(world, measured, ["D6"], sequence_check=shared).verdict is (
        holdout.Verdict.EXPLORATORY
    )
    assert locked(world, failing, ["D6"], sequence_check=shared).verdict is (
        holdout.Verdict.EXPLORATORY
    )


def test_locked_test_default_denies_missing_or_unknown_carried_scenarios(world):
    measured = norm(world, channel(29, dispersion=6.352, length_km=10.0))
    with pytest.raises(BenchmarkError, match="needs the scenarios carried"):
        locked(world, measured, None)
    with pytest.raises(BenchmarkError, match="needs the scenarios carried"):
        locked(world, measured, [])
    with pytest.raises(BenchmarkError, match="not in the scenario list"):
        locked(world, measured, ["NOPE"])
    with pytest.raises(BenchmarkError, match="not in the scenario list"):
        locked(world, measured, ["D6", "D6", "D6"])
    with pytest.raises(BenchmarkError, match="carries nothing in"):
        score(world, measured, carried=["D6"])


def table_of(**psis):
    return {k: {"psi": v} for k, v in psis.items()}


def test_the_carry_rule_needs_a_margin_and_otherwise_carries_every_survivor():
    margin = e2_score.SELECTION_MARGIN
    assert margin == 0.25
    assert e2_score.carry_rule(table_of(a=1.5, b=2.0)) == ()
    assert e2_score.carry_rule(table_of(a=0.9, b=2.0, c=3.0)) == ("a",)
    assert e2_score.carry_rule(table_of(a=1.0, b=2.0)) == ("a",)  # psi == 1 is within
    assert e2_score.carry_rule(table_of(a=1.0000001, b=0.2)) == ("b",)
    assert e2_score.carry_rule(table_of(a=0.5, b=0.75)) == ("a",)  # exactly the margin wins
    assert e2_score.carry_rule(table_of(a=0.5, b=0.74)) == ("a", "b")
    assert e2_score.carry_rule(table_of(c=0.6, a=0.5, z=3.0, b=0.7)) == ("c", "a", "b")
    assert e2_score.carry_rule(table_of(b=0.5, a=0.5)) == ("b", "a")  # list order, not name order


def test_the_2km_stage_carries_everything_that_survives_when_nothing_wins_clearly(world):
    result = score(world, norm(world, channel(32)), length_km=2.0)
    assert set(result.carry_forward) == set(result.survivors) and len(result.survivors) >= 2
    clear = score(world, norm(world, channel(33, low_pass_hz=16e9)), length_km=2.0)
    assert clear.carry_forward == ()
    locked_result = locked(world, norm(world, channel(34)), ["NULL"])
    assert locked_result.carry_forward == ()  # only the 2 km stage decides what is carried


def test_the_control_alone_within_the_limits_is_not_discriminating(world):
    model, scenarios = world["model"], world["scenarios"]
    prediction = e2_score.predict(model, scenarios[0], 2.0, N)  # exactly the control's prediction
    bad_copy = norm(world, channel(61, low_pass_hz=14e9))
    result = score(world, prediction, bad_copy, length_km=2.0)
    assert "NULL" in result.survivors and not result.comparator_within_criterion
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert "no-fibre control scenario is also within every limit" in " ".join(result.notes)


def test_a_copy_within_the_limits_is_not_discriminating_even_if_the_control_is_outside(world):
    model, scenarios = world["model"], world["scenarios"]
    d6 = next(s for s in scenarios if s.scenario_id == "D6")
    prediction = e2_score.predict(model, d6, 10.0, N)
    tight = {m: v * 0.01 for m, v in world["limits"].items()}
    result = e2_score.score_windows(
        prediction, prediction.copy(), model=model, scenarios=scenarios, limits=tight,
        length_km=10.0, split=Split.VALIDATION,
    )  # fmt: skip
    assert "D6" in result.survivors and result.comparator_within_criterion
    assert result.scenarios["NULL"]["psi"] > 1.0  # the control alone would not excuse it
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert result.notes == ("the B2B copy is also within every limit",)


def test_a_psi_of_exactly_one_is_within_the_criterion(world):
    measured = norm(world, channel(35, dispersion=6.352, length_km=10.0))
    first = score(world, measured, length_km=10.0)
    on_the_line = dict(first.scenarios["D6"]["metrics"])
    result = e2_score.score_windows(
        measured, world["evaluation"], model=world["model"], scenarios=world["scenarios"],
        limits=on_the_line, length_km=10.0, split=Split.VALIDATION,
    )  # fmt: skip
    assert result.scenarios["D6"]["psi"] == 1.0 and "D6" in result.survivors
    copy_line = dict(first.comparator["metrics"])
    result = e2_score.score_windows(
        measured, world["evaluation"], model=world["model"], scenarios=world["scenarios"],
        limits=copy_line, length_km=10.0, split=Split.VALIDATION,
    )  # fmt: skip
    assert result.comparator["psi"] == 1.0 and result.comparator_within_criterion


def test_a_control_with_a_psi_of_exactly_one_still_counts_as_within_the_limits(world):
    model, scenarios = world["model"], world["scenarios"]
    d6 = next(s for s in scenarios if s.scenario_id == "D6")
    prediction = e2_score.predict(model, d6, 10.0, N)  # D6 explains it exactly
    bad_copy = norm(world, channel(64, low_pass_hz=14e9))
    first = score(world, prediction, bad_copy, length_km=10.0)
    on_the_line = dict(first.scenarios["NULL"]["metrics"])
    result = e2_score.score_windows(
        prediction, bad_copy, model=model, scenarios=scenarios, limits=on_the_line,
        length_km=10.0, split=Split.VALIDATION,
    )  # fmt: skip
    assert result.scenarios["NULL"]["psi"] == 1.0 and "D6" in result.survivors
    assert not result.comparator_within_criterion
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING
    assert "no-fibre control scenario is also within every limit" in " ".join(result.notes)


def test_a_fibre_scenario_that_the_control_explains_equally_well_is_not_discriminating(world):
    model, scenarios = world["model"], world["scenarios"]
    d3 = next(s for s in scenarios if s.scenario_id == "D3")
    prediction = e2_score.predict(model, d3, 2.0, N)  # a weak 2 km effect: the control fits too
    bad_copy = norm(world, channel(62, low_pass_hz=14e9))
    result = score(world, prediction, bad_copy, length_km=2.0)
    assert result.best == "D3" and result.scenarios["D3"]["psi"] == pytest.approx(0.0, abs=1e-9)
    assert result.scenarios["NULL"]["psi"] <= 1.0 and not result.comparator_within_criterion
    assert result.outcome == e2_score.OUTCOME_PASS_NOT_DISCRIMINATING


def test_the_best_scenario_has_the_smallest_psi_and_list_order_breaks_ties(world):
    measured = norm(world, channel(63, dispersion=6.352, length_km=10.0))
    result = score(world, measured, length_km=10.0)
    psis = {k: v["psi"] for k, v in result.scenarios.items()}
    assert result.best == min(psis, key=psis.get)
    assert list(result.scenarios) == ["NULL", "D3", "D6", "D6_THRU", "N2", "D6_N2"]


def test_a_not_discriminating_result_is_unidentifiable_when_no_scenario_was_separable(world):
    measured = norm(world, channel(36))
    quiet = score(world, measured, length_km=2.0, identifiable_in_principle=False)
    assert quiet.verdict is holdout.Verdict.UNIDENTIFIABLE_PARAMETER
    loud = score(world, measured, length_km=2.0, identifiable_in_principle=True)
    assert loud.verdict is holdout.Verdict.INCONCLUSIVE


def test_scoring_core_default_denies_nan_missing_and_malformed_inputs(world):
    good = norm(world, channel(37))
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


def test_a_result_carries_one_caveat_per_nuisance_for_fail_and_for_pass(setup):
    report = setup.score().report()
    fail = " ".join(report["caveats_if_fail"])
    for needle in (
        "chirp", "dispersion outside", "SNR change", "low-pass", "symbol statistics", "at 10 km a FAIL",
    ):  # fmt: skip
        assert needle in fail, needle
    assert "amplitude and launch power are NOT a cause" in fail
    passed = " ".join(report["caveats_if_pass"])
    assert "does not validate dispersion" in passed and "VALIDATED is never returned" in passed


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
        assert set(per_scenario) == {"NULL", "D3", "D6", "D6_THRU", "N2", "D6_N2"}
        assert per_scenario["NULL"]["separable"] is False  # the control is never separable
        for entry in per_scenario.values():
            assert set(entry["separation_from_b2b_copy"]) == set(holdout.METRICS)
    assert registered["identifiable_in_principle"]["10"] is True
    # dispersion at 2 km with the same D is weaker than at 10 km
    two = registered["predictions"]["2"]["D6"]["separation_psi"]
    ten = registered["predictions"]["10"]["D6"]["separation_psi"]
    assert ten > two
    assert "results" not in registered


def test_the_control_is_never_separable_whatever_the_limits(world):
    tight = {m: 1e-9 for m in holdout.METRICS}
    registered = e2_score.compute_preregistration(
        world["model"], world["scenarios"], world["evaluation"], tight, (2.0,)
    )
    two = registered["predictions"]["2"]
    assert two["NULL"]["separation_psi"] > 1.0 and two["NULL"]["separable"] is False
    assert all(two[k]["separable"] is True for k in ("D3", "D6", "D6_THRU", "N2", "D6_N2"))
    # identifiable_in_principle asks for a dispersion-only separable scenario (noise factor 1,
    # noise after the fibre): N2 and D6_N2 and D6_THRU do not count
    assert registered["identifiable_in_principle"]["2"] is True
    only_noise = [
        s for s in world["scenarios"] if s.scenario_id in ("NULL", "N2", "D6_N2", "D6_THRU")
    ]
    narrowed = e2_score.compute_preregistration(
        world["model"], tuple(only_noise), world["evaluation"], tight, (2.0,)
    )
    assert narrowed["identifiable_in_principle"]["2"] is False


def test_check_reproduction_refuses_drift_flipped_flags_and_changed_keys(world):
    registered = e2_score.compute_preregistration(
        world["model"], world["scenarios"], world["evaluation"], world["limits"], (2.0,)
    )
    e2_score.check_reproduction(registered, yaml.safe_load(yaml.safe_dump(registered)))
    drifted = yaml.safe_load(yaml.safe_dump(registered))
    drifted["predictions"]["2"]["D6"]["summary"]["std"] *= 1.001
    with pytest.raises(BenchmarkError, match="is .* now"):
        e2_score.check_reproduction(registered, drifted)
    tiny = yaml.safe_load(yaml.safe_dump(registered))
    tiny["predictions"]["2"]["D6"]["summary"]["std"] *= 1 + 1e-9
    e2_score.check_reproduction(registered, tiny)  # inside the stated tolerance
    flipped = yaml.safe_load(yaml.safe_dump(registered))
    flipped["predictions"]["2"]["D6"]["separable"] = not flipped["predictions"]["2"]["D6"][
        "separable"
    ]
    with pytest.raises(BenchmarkError, match="changed"):
        e2_score.check_reproduction(registered, flipped)
    dropped = yaml.safe_load(yaml.safe_dump(registered))
    del dropped["predictions"]["2"]["N2"]
    with pytest.raises(BenchmarkError, match="keys differ"):
        e2_score.check_reproduction(registered, dropped)


# ---------------------------------------------------------------------------- entry point
HOLDOUT_2KM = "50G_PAM4_PD1_2km_Subassembly1.bin"
HOLDOUT_10KM = "50G_PAM4_PD1_10km_Subassembly1.bin"
B2B_NAME = teriphic.B2B_FILENAME
HOLDOUT_NAMES = {HOLDOUT_2KM, HOLDOUT_10KM}
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid",
}  # fmt: skip
CONFIG_TEXT = (ROOT / teriphic.CONFIG_PATH).read_text()


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=os.environ | GIT_ENV,
    )  # fmt: skip
    return done.stdout.strip()


def write_bin(path: Path, samples: np.ndarray, xinc: float = 1.0 / FS) -> None:
    path.write_bytes(keysight_image(samples.astype(np.float32), xinc=xinc))


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class Setup:
    """A git repository holding a frozen criterion, the E2 inputs, code copies, and fixture files."""

    def __init__(
        self,
        world,
        tmp_path: Path,
        monkeypatch,
        *,
        freeze: bool = True,
        two_km=None,
        two_km_xinc=None,
        md5_2km=None,
    ) -> None:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        self.world = world
        self.monkeypatch = monkeypatch
        self.md5_2km = md5_2km
        self.root = tmp_path / "repo"
        self.data = tmp_path / "files"
        self.data.mkdir()
        self.root.mkdir()
        for relative in e2_score.CODE_IDENTITY_FILES:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / relative, self.root / relative)
        self.model_doc = dict(world["model_doc"], code_identity=e2_score.code_identity(self.root))
        self.holdout_2 = self.data / HOLDOUT_2KM
        self.holdout_10 = self.data / HOLDOUT_10KM
        self.b2b = self.data / B2B_NAME
        write_bin(self.b2b, world["b2b"])
        write_bin(
            self.holdout_2,
            channel(41, dispersion=6.352, length_km=2.0) if two_km is None else two_km,
            xinc=1.0 / FS if two_km_xinc is None else two_km_xinc,
        )
        write_bin(self.holdout_10, channel(42, dispersion=6.352, length_km=10.0))
        self.sha = {
            HOLDOUT_2KM: hashlib.sha256(self.holdout_2.read_bytes()).hexdigest(),
            HOLDOUT_10KM: hashlib.sha256(self.holdout_10.read_bytes()).hexdigest(),
        }
        self.write_documents()
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "inputs")
        self.pin = ""
        self.carried: list[str] = []
        self.placeholder = False
        self.patch_loaded_code()
        if freeze:
            self.finish()

    def patch_loaded_code(self) -> None:
        """The modules that run are the repository's copies in these tests (see verify_loaded_code)."""
        mapping = {r: (self.root / r).resolve() for r in e2_score.CODE_IDENTITY_FILES}
        self.monkeypatch.setattr(e2_score, "loaded_code_files", lambda: mapping)

    def comparator(self) -> np.ndarray:
        """The B2B window as the scorer reads it: through the float32 file."""
        stored = self.world["b2b"].astype(np.float32).astype(np.float64)
        return e2_metrics.normalise(
            window(stored, "evaluation"), self.world["c0"], self.world["g0"]
        )

    def config_text(self) -> str:
        """The real register with the three supplied MD5 replaced by those of the fixtures."""
        text = CONFIG_TEXT
        for name, path in (
            (B2B_NAME, self.b2b), (HOLDOUT_2KM, self.holdout_2), (HOLDOUT_10KM, self.holdout_10)
        ):  # fmt: skip
            real = re.search(
                rf"filename: {re.escape(name)}\n.*?md5_supplied: \"([0-9a-f]{{32}})\"", text, re.S
            )
            assert real is not None
            text = text.replace(
                real.group(1),
                self.md5_2km if (self.md5_2km and name == HOLDOUT_2KM) else md5_of(path),
            )
        return text

    def write_documents(self) -> None:
        (self.root / teriphic.CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (self.root / teriphic.CONFIG_PATH).write_text(self.config_text())
        (self.root / e2_score.E2_DIR).mkdir(parents=True, exist_ok=True)
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
            "preregistration_version": e2_score.PREREGISTRATION_VERSION,
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "scenario_list_sha256": hashlib.sha256(scenario_bytes).hexdigest(),
            "scenario_count": len(scenarios),
            "limits": self.world["limits"],
            **registered,
            "results": None,
        }
        (self.root / e2_score.PREREGISTRATION_PATH).write_text(yaml.safe_dump(document))
        (self.root / e2_score.POWER_STUDY_PATH).write_text("power_study_version: 1\n")
        (self.root / e2_score.EVALUATION_SCRIPT).parent.mkdir(exist_ok=True)
        (self.root / e2_score.EVALUATION_SCRIPT).write_text("# evaluation script fixture\n")

    def criterion_document(self) -> dict:
        plan = (self.root / holdout.DEFAULT_PLAN).read_bytes()
        return {
            "criterion_version": 3,
            "plan_sha256": hashlib.sha256(plan).hexdigest(),
            "limits": self.world["limits"],
            "b2b_basis": self.world["basis"],
            "multipliers": dict.fromkeys(holdout.METRICS, MULTIPLIER),
            "estimators": dict(holdout.ESTIMATORS),
        }

    def finish(self) -> None:
        """Freeze, then add the 2 km record and the selection in one later commit (as E2b will).

        A fixture built to be refused (a changed input, a wrong MD5, another role) cannot make a
        2 km run; it gets a placeholder record that no 10 km run accepts, and `placeholder` says so.
        """
        self.freeze()
        try:
            record = self.two_km_record()
        except BenchmarkError:
            self.placeholder = True
            self.select(ids=["D6"], record="{}\n")
        else:
            self.select(record=record)

    def two_km_record(self, **extra) -> str:
        """The 2 km run's report as the evaluation script prints it (stdout, with its newline)."""
        return self.score(self.holdout_2, **extra).report_json() + "\n"

    def select(
        self, ids=None, rule=None, stage: str = "2km", record=None, sha=None, extra=None
    ) -> None:
        """Commit the 2 km record and `selected_scenario.yaml` together, in one commit.

        By default the record is a real 2 km run on the fixture and the ids are its carry_forward.
        """
        text = self.two_km_record() if record is None else record
        if ids is None:
            ids = json.loads(text)["carry_forward"]
        ids = list(ids)
        selection = {
            "scenario_ids": ids,
            "rule": rule or ("single" if len(ids) == 1 else "all_survivors"),
            "selected_at_stage": stage,
            "two_km_result_sha256": sha or hashlib.sha256(text.encode()).hexdigest(),
        } | (extra or {})
        (self.root / e2_score.TWO_KM_RESULT_PATH).write_bytes(text.encode())
        (self.root / e2_score.SELECTED_PATH).write_text(yaml.safe_dump(selection))
        git(self.root, "add", "-A")
        git(
            self.root, "commit", "-q", "-m", f"select {time.time_ns()}"
        )  # never the same commit twice
        self.carried = ids

    def freeze(self) -> None:
        path = self.root / holdout.CRITERION_PATH
        path.write_text(yaml.safe_dump(self.criterion_document()))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "freeze")
        self.pin = git(self.root, "rev-parse", "HEAD")

    def score(self, which=None, **extra):
        target = which or self.holdout_2
        arguments = {
            "b2b_path": self.b2b, "repo_root": self.root, "holdout_sha256": self.sha,
            "expected_freeze_commit": self.pin or "0" * 40,
        }  # fmt: skip
        if target == self.holdout_10:
            arguments["validation_stage"] = holdout.ValidationStage.NOT_FAILED
        return e2_score.score_holdout(target, **(arguments | extra))

    def commit_all(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)


@pytest.fixture
def setup(world, tmp_path, monkeypatch):
    return Setup(world, tmp_path, monkeypatch)


@pytest.fixture
def unfrozen(world, tmp_path, monkeypatch):
    return Setup(world, tmp_path, monkeypatch, freeze=False)


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


def watch_holdout(monkeypatch) -> list[str]:
    """Record every hash or open of a holdout file; the B2B comparator is allowed to be read."""
    events: list[str] = []
    real_hash = e2_score.verify_local_asset
    real_open = e2_score.ExternalCapture.open_keysight_bin

    def hash_spy(path, *args, **kwargs):
        if Path(path).name in HOLDOUT_NAMES:
            events.append(f"hash {Path(path).name}")
        return real_hash(path, *args, **kwargs)

    def open_spy(path, *args, **kwargs):
        if Path(path).name in HOLDOUT_NAMES:
            events.append(f"open {Path(path).name}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(e2_score, "verify_local_asset", hash_spy)
    monkeypatch.setattr(e2_score.ExternalCapture, "open_keysight_bin", open_spy)
    return events


def test_the_scorer_runs_end_to_end_on_a_frozen_fixture_and_reports_no_error_rate(setup):
    assert not setup.placeholder  # the honest fixture makes a real 2 km record
    result = setup.score()
    report = result.report()
    assert report["filename"] == HOLDOUT_2KM and report["length_km"] == 2.0
    assert report["split"] == "VALIDATION" and report["hashes_verified"] is True
    assert report["criterion_commit"] == setup.pin
    assert report["scenarios_scored"] == 6 and report["reference_sequence"] == (
        "REFERENCE_SEQUENCE_MISSING"
    )
    assert report["fibre_knowledge"]["fibre_type"] == "UNKNOWN"
    assert "MODEL GAP" in report["fibre_knowledge"]["chirp"]
    assert any("CHIRP" in gap for gap in report["model_gaps"])
    assert report["amplitude_ratio_vs_b2b"] > 0
    assert report["outcome"] in {
        e2_score.OUTCOME_FAIL,
        e2_score.OUTCOME_PASS_DISCRIMINATING,
        e2_score.OUTCOME_PASS_NOT_DISCRIMINATING,
    }
    assert not re.search(r"\b(ber|ser)\b|post_fec|serial", repr(report).lower())
    ten = setup.score(setup.holdout_10)
    assert ten.report()["split"] == "LOCKED_TEST" and ten.carry_forward == ()
    assert set(ten.scenarios) == set(setup.carried) | {"NULL"} and setup.carried
    assert ten.verdict != "VALIDATED"


def test_every_refusal_before_the_holdout_comes_before_any_hash_or_open_of_it(setup, monkeypatch):
    events = watch_holdout(monkeypatch)
    setup.score()
    assert events == [f"hash {HOLDOUT_2KM}", f"open {HOLDOUT_2KM}"]  # hash first, then the reader
    # the comparator and the reproduction check come before the holdout is touched at all
    order: list[str] = []
    real_check = e2_score.check_reproduction
    real_hash = e2_score.verify_local_asset
    real_gate = e2_score.teriphic.gate_sample_read

    def spy_check(*a, **k):
        order.append("reproduction")
        return real_check(*a, **k)

    def spy_hash(path, *a, **k):
        order.append(f"hash {Path(path).name}")
        return real_hash(path, *a, **k)

    def spy_gate(path, *a, **k):
        order.append(f"gate {Path(path).name}")
        return real_gate(path, *a, **k)

    monkeypatch.setattr(e2_score, "check_reproduction", spy_check)
    monkeypatch.setattr(e2_score, "verify_local_asset", spy_hash)
    monkeypatch.setattr(e2_score.teriphic, "gate_sample_read", spy_gate)
    setup.score()
    assert order == [f"gate {B2B_NAME}", "reproduction", f"hash {HOLDOUT_2KM}"]
    # plan Revision 13: the stage refusal (item 5) and a record refusal (item 6) come before the
    # B2B gate, the reproduction check and any hash or open of the 10 km file
    order.clear()
    events.clear()
    with pytest.raises(holdout.StageRefused, match="2 km stage FAILED"):
        setup.score(setup.holdout_10, validation_stage=holdout.ValidationStage.FAILED)
    assert order == [] and events == []
    selected = setup.root / e2_score.SELECTED_PATH
    document = yaml.safe_load(selected.read_text())
    document["two_km_result_sha256"] = "0" * 64
    selected.write_text(yaml.safe_dump(document))
    git(setup.root, "commit", "-q", "-am", "another hash")  # also a second commit of the file
    with pytest.raises(holdout.StageRefused, match="selected scenario"):
        setup.score(setup.holdout_10)
    assert order == [] and events == []


def test_a_carried_id_that_is_not_listed_and_a_drifted_prediction_are_refused_unread(
    world, tmp_path, monkeypatch
):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.freeze()
    unfrozen.select(ids=("NOPE",))
    events = watch_holdout(monkeypatch)
    with pytest.raises(BenchmarkError, match="an id is not in the scenario list"):
        unfrozen.score(unfrozen.holdout_10)
    assert events == []


def test_a_drifted_preregistered_value_is_refused_before_the_holdout_is_read(
    world, tmp_path, monkeypatch
):
    def drift(d):
        d["predictions"]["2"]["D6"]["summary"]["std"] *= 1.01
        return d

    unfrozen = pre_freeze_prereg(world, tmp_path, monkeypatch, drift)
    events = watch_holdout(monkeypatch)
    with pytest.raises(BenchmarkError, match="pre-registered predictions: .*std"):
        unfrozen.score()
    assert events == []


def test_no_frozen_criterion_refuses_before_any_file_is_touched(unfrozen, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score()
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score(unfrozen.holdout_10)
    # even a holdout path that does not exist: the refusal comes first
    with pytest.raises(BenchmarkError, match="no frozen criterion"):
        unfrozen.score(unfrozen.data / HOLDOUT_2KM.upper().replace(".BIN", ".bin"))


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
    setup.commit_all("loosen")
    with pytest.raises(BenchmarkError, match="changed after the first commit"):
        setup.score()  # altered and committed: the loosened limit is not a freeze
    path.write_text(original)
    setup.commit_all("restore")
    with pytest.raises(BenchmarkError, match="changed after the first commit"):
        setup.score()  # restoring does not undo the change in history


def test_a_stale_criterion_after_a_plan_change_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    plan = setup.root / holdout.DEFAULT_PLAN
    plan.write_text(plan.read_text() + "a later change\n")
    with pytest.raises(BenchmarkError, match="modified since HEAD"):
        setup.score()
    setup.commit_all("plan changed")
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
    with pytest.raises(BenchmarkError, match="selected_scenario|not committed|cannot be read"):
        setup.score(setup.holdout_10)


def test_the_10km_stage_needs_the_2km_stage_declared(setup, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="2 km stage is done"):
        e2_score.score_holdout(
            setup.holdout_10, b2b_path=setup.b2b, repo_root=setup.root, holdout_sha256=setup.sha,
            expected_freeze_commit=setup.pin,
        )  # fmt: skip


def test_a_holdout_whose_hash_mismatches_is_refused_and_never_opened(setup, monkeypatch):
    events = watch_holdout(monkeypatch)
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
    assert not any(e.startswith("open") for e in events)  # hashed, never opened


def test_an_md5_mismatch_alone_is_refused_even_with_a_matching_sha(world, tmp_path, monkeypatch):
    s = Setup(world, tmp_path, monkeypatch, md5_2km="1" * 32)  # the register says another MD5
    events = watch_holdout(monkeypatch)
    with pytest.raises(BenchmarkError, match="does not match the recorded"):
        s.score()  # the SHA-256 is right, the MD5 is not
    assert not any(e.startswith("open") for e in events)


def test_a_register_md5_change_after_the_freeze_is_refused_by_the_bind(setup):
    text = (
        (setup.root / teriphic.CONFIG_PATH).read_text().replace(md5_of(setup.holdout_2), "1" * 32)
    )
    (setup.root / teriphic.CONFIG_PATH).write_text(text)
    setup.commit_all("md5")
    with pytest.raises(BenchmarkError, match="changed since the freeze"):
        setup.score()


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


def role_attack(world, tmp_path, monkeypatch, old, new, name):
    """A register that gives a holdout another role, frozen with the freeze (attacker's freeze)."""
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    path = unfrozen.root / teriphic.CONFIG_PATH
    text = path.read_text()
    block = text[text.index(f"filename: {name}") :]
    changed = block.replace(f"split: {old}", f"split: {new}", 1)
    path.write_text(text.replace(block, changed))
    unfrozen.finish()
    return unfrozen


def test_the_10km_file_cannot_be_given_the_validation_role(world, tmp_path, monkeypatch):
    attacked = role_attack(world, tmp_path, monkeypatch, "LOCKED_TEST", "VALIDATION", HOLDOUT_10KM)
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="the frozen code fixes LOCKED_TEST"):
        attacked.score(attacked.holdout_10)


def test_the_2km_file_cannot_be_given_the_locked_test_role_so_it_never_gives_validated(
    world, tmp_path, monkeypatch
):
    attacked = role_attack(world, tmp_path, monkeypatch, "VALIDATION", "LOCKED_TEST", HOLDOUT_2KM)
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="the frozen code fixes VALIDATION"):
        attacked.score(attacked.holdout_2, validation_stage=holdout.ValidationStage.NOT_FAILED)


def test_the_role_register_changed_after_the_freeze_is_refused(setup, monkeypatch):
    path = setup.root / teriphic.CONFIG_PATH
    path.write_text(path.read_text().replace("split: LOCKED_TEST", "split: VALIDATION", 1))
    setup.commit_all("move the 10 km role")
    forbid_reads(monkeypatch)
    with pytest.raises(
        BenchmarkError,
        match="teriphic_pd1_pam4.yaml: changed since the freeze|the frozen code fixes LOCKED_TEST",
    ):
        setup.score(setup.holdout_10)
    # with the register injected (an honest one) the change of the file is still refused by the bind
    honest = load_source_config(ROOT / teriphic.CONFIG_PATH)
    with pytest.raises(BenchmarkError, match="teriphic_pd1_pam4.yaml: changed since the freeze"):
        setup.score(setup.holdout_10, source=honest)


def test_roles_are_fixed_by_name_in_frozen_code():
    assert e2_score.ROLE_BY_NAME == {
        HOLDOUT_2KM: Split.VALIDATION,
        HOLDOUT_10KM: Split.LOCKED_TEST,
    }


def test_a_changed_code_file_is_refused(setup, monkeypatch):
    forbid_reads(monkeypatch)
    target = setup.root / e2_score.CODE_IDENTITY_FILES[0]
    target.write_text(target.read_text() + "\n# tweak\n")
    with pytest.raises(BenchmarkError, match="modified since HEAD"):
        setup.score()


def test_a_code_file_that_differs_from_the_identity_table_is_refused(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    target = unfrozen.root / e2_score.CODE_IDENTITY_FILES[0]
    target.write_text(target.read_text() + "\n# tweak before the freeze\n")
    unfrozen.finish()
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="code identity"):
        unfrozen.score()


def test_the_running_code_must_be_the_code_of_the_repository(setup, monkeypatch, tmp_path):
    other = {r: (tmp_path / "elsewhere" / r).resolve() for r in e2_score.CODE_IDENTITY_FILES}
    monkeypatch.setattr(e2_score, "loaded_code_files", lambda: other)
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="not the code of"):
        setup.score()


def pre_freeze_prereg(world, tmp_path, monkeypatch, change):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    path = unfrozen.root / e2_score.PREREGISTRATION_PATH
    document = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump(change(document)))
    unfrozen.finish()
    return unfrozen


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d | {"results": {"2": {"M1": 0.1}}}, "result column is filled"),
        (lambda d: d | {"model_sha256": "0" * 64}, "not tied"),
        (lambda d: d | {"scenario_list_sha256": "0" * 64}, "not tied"),
        (lambda d: d | {"preregistration_version": 1}, "not tied"),
        (lambda d: d | {"scenario_count": 9}, "scenario count"),
        (
            lambda d: d | {"limits": dict(d["limits"], M1_level_spacing=9.0)},
            "differs from the frozen",
        ),
        (lambda d: d | {"limits": {"M1_level_spacing": 1.0}}, "limits are missing"),
    ],
)
def test_preregistration_must_be_tied_to_the_model_and_scenarios_and_hold_no_result(
    world, tmp_path, monkeypatch, change, message
):
    unfrozen = pre_freeze_prereg(world, tmp_path, monkeypatch, change)
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match=message):
        unfrozen.score()


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
    with pytest.raises(BenchmarkError, match="changed since the freeze|differ from the input"):
        setup.score()


def retie(setup):
    """Re-tie the pre-registration to the current model and scenario list, as an attacker would."""
    path = setup.root / e2_score.PREREGISTRATION_PATH
    document = yaml.safe_load(path.read_text())
    for key, target in (
        ("model_sha256", e2_score.MODEL_PATH),
        ("scenario_list_sha256", e2_score.SCENARIO_PATH),
    ):
        document[key] = hashlib.sha256((setup.root / target).read_bytes()).hexdigest()
    path.write_text(yaml.safe_dump(document))


def test_a_model_replaced_together_with_its_registration_after_the_freeze_is_refused(
    setup, monkeypatch
):
    model = setup.root / e2_score.MODEL_PATH
    document = yaml.safe_load(model.read_text())
    document["noise_sigma"] *= 1.5
    model.write_text(yaml.safe_dump(document, sort_keys=False))
    retie(setup)
    setup.commit_all("new model and registration")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="b2b_model.yaml: changed since the freeze commit"):
        setup.score()


def test_a_scenario_list_replaced_after_the_freeze_is_refused(setup, monkeypatch):
    path = setup.root / e2_score.SCENARIO_PATH
    document = yaml.safe_load(path.read_text())
    document["scenarios"][1]["dispersion_ps_nm_km"] = 1.0
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    retie(setup)
    setup.commit_all("new scenarios")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="changed since the freeze commit"):
        setup.score()


@pytest.mark.parametrize(
    ("target", "name"),
    [
        (e2_score.PREREGISTRATION_PATH, "preregistered_predictions.yaml"),
        (e2_score.POWER_STUDY_PATH, "power_study.yaml"),
        (e2_score.EVALUATION_SCRIPT, "score_teriphic_e2.py"),
    ],
)
def test_a_data_file_or_the_script_replaced_after_the_freeze_is_refused(
    setup, monkeypatch, target, name
):
    path = setup.root / target
    path.write_text(path.read_text() + "\n# changed\n")
    setup.commit_all("changed")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match=f"{name}: changed since the freeze"):
        setup.score(setup.holdout_10)


def test_code_and_identity_table_replaced_together_after_the_freeze_is_refused(setup, monkeypatch):
    code = setup.root / e2_score.CODE_IDENTITY_FILES[0]
    code.write_text(code.read_text() + "\n# a post-freeze change\n")
    model = setup.root / e2_score.MODEL_PATH
    document = yaml.safe_load(model.read_text())
    document["code_identity"] = e2_score.code_identity(setup.root)
    model.write_text(yaml.safe_dump(document, sort_keys=False))
    retie(setup)
    setup.commit_all("new code, table and registration")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="changed since the freeze commit"):
        setup.score()


@pytest.mark.parametrize("index", range(len(e2_score.CODE_IDENTITY_FILES)))
def test_each_code_identity_file_changed_alone_after_the_freeze_is_refused(
    setup, monkeypatch, index
):
    relative = e2_score.CODE_IDENTITY_FILES[index]
    code = setup.root / relative
    code.write_text(code.read_text() + "\n# a post-freeze change\n")
    setup.commit_all("code only")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match=f"{Path(relative).name}: changed since the freeze"):
        setup.score()


def test_a_file_missing_at_the_freeze_commit_is_refused(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    git(unfrozen.root, "rm", "-q", "-f", str(e2_score.POWER_STUDY_PATH))
    unfrozen.freeze()
    (unfrozen.root / e2_score.POWER_STUDY_PATH).write_text("power_study_version: 1\n")
    unfrozen.commit_all("late power study")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="did not exist at the freeze commit"):
        unfrozen.score()


# ---- the freeze pin and the first-parent rule
def test_the_freeze_commit_must_be_the_pinned_one(setup, monkeypatch):
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="is not the pinned"):
        setup.score(expected_freeze_commit="0" * 40)  # well formed, wrong commit
    for bad in ("abc", "", setup.pin.upper(), setup.pin[:12], setup.pin + "0", 5):
        with pytest.raises(BenchmarkError, match="must be a full lower-case 40-digit commit id"):
            setup.score(expected_freeze_commit=bad)
    with pytest.raises(TypeError):
        e2_score.score_holdout(setup.holdout_2, b2b_path=setup.b2b, repo_root=setup.root)


def test_the_script_cannot_run_without_a_pin(setup):
    script = load_script()
    with pytest.raises(SystemExit):
        script.main([str(setup.holdout_2), "--b2b", str(setup.b2b), "--repo", str(setup.root)])


def side_branch_attack(world, tmp_path, monkeypatch):
    """The review's repro: a side commit holds the same criterion bytes and relaxed code; HEAD is
    the side branch after merging the real freeze with `-X ours`. Returns (setup, real, side)."""
    s = Setup(world, tmp_path, monkeypatch, freeze=False)
    base = git(s.root, "rev-parse", "HEAD")
    git(s.root, "checkout", "-q", "-b", "side")
    (s.root / holdout.CRITERION_PATH).write_text(yaml.safe_dump(s.criterion_document()))
    code = s.root / "src/opticps/benchmarks/e2_score.py"
    code.write_text(code.read_text() + "\n# relaxed on the side branch\n")
    s.commit_all("side criterion with changed code")
    side = git(s.root, "rev-parse", "HEAD")
    git(s.root, "checkout", "-q", "-b", "main2", base)
    s.freeze()
    real = s.pin
    git(s.root, "checkout", "-q", "side")
    git(s.root, "merge", "-q", "--no-edit", "-X", "ours", "main2")
    return s, real, side


def test_a_side_commit_with_the_same_criterion_cannot_become_the_freeze(
    world, tmp_path, monkeypatch
):
    s, real, side = side_branch_attack(world, tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="pinned|first on the first-parent|first commit"):
        s.score(
            expected_freeze_commit=real
        )  # the owner's pin refuses it, whichever commit is found


def test_a_pin_taken_from_the_attackers_own_commit_passes_the_pin_check_which_is_the_limit(
    world, tmp_path, monkeypatch
):
    """Documented limit: the pin protects only if it was recorded outside the repository."""
    s, real, side = side_branch_attack(world, tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    try:
        s.score(expected_freeze_commit=side)
    except BenchmarkError as error:
        assert "pinned" not in str(error)  # it may stop later, never at the pin


def git_at(root: Path, date: str, *args: str) -> str:
    env = os.environ | GIT_ENV | {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=env,
    )  # fmt: skip
    return done.stdout.strip()


def test_first_parent_resolution_ignores_an_older_side_commit_and_takes_the_oldest_main_commit(
    tmp_path,
):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path / "r"
    root.mkdir()
    git_at(root, "2020-01-01T00:00:00", "init", "-q")
    (root / "base").write_text("b")
    git_at(root, "2020-01-01T00:00:00", "add", "-A")
    git_at(root, "2020-01-01T00:00:00", "commit", "-q", "-m", "base")
    git_at(root, "2020-01-02T00:00:00", "checkout", "-q", "-b", "side")
    path = root / holdout.CRITERION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("limits: 1\n")
    git_at(root, "2020-01-02T00:00:00", "add", "-A")
    git_at(root, "2020-01-02T00:00:00", "commit", "-q", "-m", "side criterion (older date)")
    git_at(root, "2021-01-01T00:00:00", "checkout", "-q", "-b", "main2", "HEAD~1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("limits: 1\n")
    git_at(root, "2021-01-01T00:00:00", "add", "-A")
    git_at(root, "2021-01-01T00:00:00", "commit", "-q", "-m", "main criterion (newer date)")
    first_on_main = git_at(root, "2021-01-01T00:00:00", "rev-parse", "HEAD")
    git_at(root, "2021-01-02T00:00:00", "merge", "-q", "--no-edit", "-X", "ours", "side")
    path.write_text("limits: 2\n")
    git_at(root, "2021-01-03T00:00:00", "add", "-A")
    git_at(root, "2021-01-03T00:00:00", "commit", "-q", "-m", "later change")
    # the side commit is older and reachable, the later change is newest: only the oldest commit
    # on the first-parent line counts
    assert e2_score.first_parent_freeze(root) == first_on_main
    older = git_at(root, "2020-01-02T00:00:00", "rev-parse", "side")
    assert older != first_on_main
    # a pin equal to the commit the guard might find, but not first on the first-parent line
    found = types.SimpleNamespace(commit=older)
    with pytest.raises(BenchmarkError, match="not the first on the first-parent history"):
        e2_score.require_freeze_pin(root, found, older)
    e2_score.require_freeze_pin(root, types.SimpleNamespace(commit=first_on_main), first_on_main)


def test_first_parent_resolution_takes_the_merge_not_the_merged_in_side_commit(tmp_path):
    """The criterion first reaches main by a merge. Git's default history simplification follows
    only the side parent (the merge is identical to it), so a log without `--first-parent` names
    the side commit; the first-parent line names the merge. Removing `--first-parent` lets a
    merged side commit become the freeze."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path / "r"
    root.mkdir()
    git_at(root, "2020-01-01T00:00:00", "init", "-q")
    (root / "base").write_text("b")
    git_at(root, "2020-01-01T00:00:00", "add", "-A")
    git_at(root, "2020-01-01T00:00:00", "commit", "-q", "-m", "base")
    main = git_at(root, "2020-01-01T00:00:00", "rev-parse", "--abbrev-ref", "HEAD")
    git_at(root, "2020-01-02T00:00:00", "checkout", "-q", "-b", "side")
    path = root / holdout.CRITERION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("limits: 1\n")
    git_at(root, "2020-01-02T00:00:00", "add", "-A")
    git_at(root, "2020-01-02T00:00:00", "commit", "-q", "-m", "side criterion")
    side = git_at(root, "2020-01-02T00:00:00", "rev-parse", "HEAD")
    git_at(root, "2020-01-03T00:00:00", "checkout", "-q", main)
    (root / "other").write_text("o")
    git_at(root, "2020-01-03T00:00:00", "add", "-A")
    git_at(root, "2020-01-03T00:00:00", "commit", "-q", "-m", "main work without the criterion")
    git_at(root, "2020-01-04T00:00:00", "merge", "-q", "--no-ff", "--no-edit", "side")
    merge = git_at(root, "2020-01-04T00:00:00", "rev-parse", "HEAD")
    assert merge != side
    criterion = holdout.CRITERION_PATH.as_posix()
    plain = git_at(root, "2020-01-04T00:00:00", "log", "--reverse", "--format=%H", "--", criterion)
    assert plain.split()[0] == side  # without --first-parent the side commit would be the freeze
    assert e2_score.first_parent_freeze(root) == merge
    # the pin names the side commit and the loader found it: the first-parent check refuses it
    with pytest.raises(BenchmarkError, match="not the first on the first-parent history"):
        e2_score.require_freeze_pin(root, types.SimpleNamespace(commit=side), side)
    e2_score.require_freeze_pin(root, types.SimpleNamespace(commit=merge), merge)


def test_first_parent_resolution_names_the_first_commit_on_the_main_line(setup):
    assert e2_score.first_parent_freeze(setup.root) == setup.pin
    other = setup.root.parent / "empty"
    other.mkdir()
    git(other, "init", "-q")
    (other / "x").write_text("x")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "x")
    with pytest.raises(BenchmarkError, match="no commit on the first-parent history"):
        e2_score.first_parent_freeze(other)


def test_a_moved_criterion_path_resets_the_binding_and_only_the_pin_catches_it(setup, monkeypatch):
    """The documented limit: a path move is an ordinary commit and makes a new freeze commit."""
    moved = Path("docs/benchmarks/TERIPHIC_CRITERION_MOVED.yaml")
    document = setup.criterion_document()
    document["limits"] = {k: v * 10 for k, v in document["limits"].items()}
    document["multipliers"] = {k: v * 10 for k, v in document["multipliers"].items()}
    (setup.root / moved).write_text(yaml.safe_dump(document))
    setup.commit_all("move the criterion path with looser limits")
    new_freeze = git(setup.root, "rev-parse", "HEAD")
    monkeypatch.setattr(holdout, "CRITERION_PATH", moved)
    monkeypatch.setattr(e2_score, "CRITERION_PATH", moved)
    with pytest.raises(BenchmarkError) as raised:
        setup.score(expected_freeze_commit=setup.pin)
    assert "pinned" in str(raised.value) and new_freeze[:12] in str(raised.value)
    # with the attacker's own commit as the pin the pin check passes and only later checks speak
    with pytest.raises(BenchmarkError) as later:
        setup.score(expected_freeze_commit=new_freeze)
    assert "pinned" not in str(later.value)


# ---- the selected scenario
def test_the_selected_scenario_is_added_once_after_the_freeze_and_never_changed(
    world, tmp_path, monkeypatch
):
    s = Setup(world, tmp_path, monkeypatch)
    s.score(s.holdout_10)  # added once, unchanged: accepted
    record = (s.root / e2_score.TWO_KM_RESULT_PATH).read_text()
    path = s.root / e2_score.SELECTED_PATH
    path.write_text(path.read_text() + "# changed\n")
    s.commit_all("changed")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="added once, never changed, found 2"):
        s.score(s.holdout_10)
    git(s.root, "rm", "-q", str(e2_score.SELECTED_PATH))
    s.commit_all("deleted")
    s.select(record=record)  # the same record bytes: only the selection is added again
    with pytest.raises(BenchmarkError, match="added once, never changed, found 4"):
        s.score(s.holdout_10)


def test_the_same_selected_bytes_on_two_branches_are_two_additions(world, tmp_path, monkeypatch):
    s = Setup(world, tmp_path, monkeypatch, freeze=False)
    s.freeze()
    git(s.root, "branch", "side")
    s.select()
    git(s.root, "checkout", "-q", "side")
    s.select()
    git(s.root, "checkout", "-q", "-")
    git(s.root, "merge", "-q", "--no-edit", "side")  # identical bytes: the merge is clean
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="added once, never changed, found [23]"):
        s.score(s.holdout_10)


def test_a_selected_scenario_present_at_the_freeze_is_refused(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.select(ids=["D6"], record="{}\n")  # before the freeze: no 2 km run is possible
    unfrozen.freeze()
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="already present at the freeze commit"):
        unfrozen.score(unfrozen.holdout_10)


def test_a_selected_scenario_not_descended_from_the_freeze_is_refused(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    git(unfrozen.root, "branch", "side")
    unfrozen.freeze()
    git(unfrozen.root, "checkout", "-q", "side")
    unfrozen.select(ids=["D6"], record="{}\n")  # forked before the freeze: no 2 km run there
    git(unfrozen.root, "checkout", "-q", "-")
    git(unfrozen.root, "merge", "-q", "--no-edit", "side")
    forbid_reads(monkeypatch)
    with pytest.raises(
        BenchmarkError, match="not added after the freeze commit|added once, never changed"
    ):
        unfrozen.score(unfrozen.holdout_10)


def test_a_selected_scenario_renamed_in_from_a_draft_is_refused(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.freeze()
    record = unfrozen.two_km_record()
    draft = unfrozen.root / "docs/benchmarks/teriphic_e2/draft_selection.yaml"
    ids = json.loads(record)["carry_forward"]
    draft.write_text(
        yaml.safe_dump(
            {
                "scenario_ids": ids,
                "rule": "all_survivors",
                "selected_at_stage": "2km",
                "two_km_result_sha256": hashlib.sha256(record.encode()).hexdigest(),
            }
        )  # fmt: skip
    )
    unfrozen.commit_all("draft")
    git(unfrozen.root, "mv", str(draft.relative_to(unfrozen.root)), str(e2_score.SELECTED_PATH))
    (unfrozen.root / e2_score.TWO_KM_RESULT_PATH).write_text(record)
    unfrozen.commit_all("rename in, with the record")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="must be a new file in its commit"):
        unfrozen.score(unfrozen.holdout_10)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({"scenario_ids": 5, "rule": "single", "selected_at_stage": "2km"}, "non-empty list"),
        ({"scenario_ids": [], "rule": "single", "selected_at_stage": "2km"}, "non-empty list"),
        ({"scenario_ids": [5], "rule": "single", "selected_at_stage": "2km"}, "non-empty list"),
        (
            {"scenario_ids": ["D6", "D6"], "rule": "all_survivors", "selected_at_stage": "2km"},
            "unique",
        ),
        (
            {"scenario_ids": ["D6", "D3"], "rule": "single", "selected_at_stage": "2km"},
            "exactly one",
        ),
        ({"scenario_ids": ["D6"], "rule": "pick", "selected_at_stage": "2km"}, "rule must be"),
        (
            {"scenario_ids": ["D6"], "rule": "single", "selected_at_stage": "banana"},
            "must be '2km'",
        ),
        ({"scenario_ids": ["D6"], "rule": "single"}, "exactly the keys"),
        (
            {"scenario_ids": ["D6"], "rule": "single", "selected_at_stage": "2km", "x": 1},
            "exactly the keys",
        ),
    ],
)
def test_a_malformed_selected_scenario_is_refused(world, tmp_path, monkeypatch, content, message):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.freeze()
    record = unfrozen.two_km_record()
    content = content | {"two_km_result_sha256": hashlib.sha256(record.encode()).hexdigest()}
    (unfrozen.root / e2_score.TWO_KM_RESULT_PATH).write_text(record)
    (unfrozen.root / e2_score.SELECTED_PATH).write_text(yaml.safe_dump(content))
    unfrozen.commit_all("selected")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match=message):
        unfrozen.score(unfrozen.holdout_10)


def test_a_duplicate_key_in_the_selected_scenario_is_a_benchmark_error(
    world, tmp_path, monkeypatch
):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.freeze()
    record = unfrozen.two_km_record()
    (unfrozen.root / e2_score.TWO_KM_RESULT_PATH).write_text(record)
    (unfrozen.root / e2_score.SELECTED_PATH).write_text(
        "scenario_ids: [D6]\nrule: single\nrule: single\nselected_at_stage: 2km\n"
        f"two_km_result_sha256: {hashlib.sha256(record.encode()).hexdigest()}\n"
    )
    unfrozen.commit_all("duplicate key")
    forbid_reads(monkeypatch)
    with pytest.raises(BenchmarkError, match="cannot be read as strict YAML"):
        unfrozen.score(unfrozen.holdout_10)


def test_all_survivors_may_carry_several_scenarios(world, tmp_path, monkeypatch):
    unfrozen = Setup(world, tmp_path, monkeypatch, freeze=False)
    unfrozen.freeze()
    unfrozen.select()  # the fixture's 2 km run carries every survivor
    assert len(unfrozen.carried) >= 2
    result = unfrozen.score(unfrozen.holdout_10)
    assert set(result.scenarios) == set(unfrozen.carried) | {"NULL"}


# ---- the two-stage contract (plan Revision 13): the 10 km run is tied to the committed 2 km record
def edited_record(s, change) -> str:
    """A real 2 km record of the fixture, changed by `change`, written the way the script writes."""
    document = json.loads(s.two_km_record())
    change(document)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def refused_unread(s, monkeypatch, message, **extra):
    """The 10 km run is refused by the two-stage contract with nothing of a holdout hashed or opened."""
    events = watch_holdout(monkeypatch)
    with pytest.raises(holdout.StageRefused, match=message):
        s.score(s.holdout_10, **extra)
    assert events == []


def frozen_only(world, tmp_path, monkeypatch, **options):
    s = Setup(world, tmp_path, monkeypatch, freeze=False, **options)
    s.freeze()
    return s


@pytest.mark.parametrize(
    ("stage", "message"),
    [
        (holdout.ValidationStage.FAILED, "the 2 km stage FAILED: nothing is carried"),
        (holdout.ValidationStage.NOT_DONE, "before the 2 km stage is done"),
        (None, "before the 2 km stage is done"),
    ],
)
def test_the_10km_file_is_refused_when_the_2km_stage_is_declared_failed_or_undeclared(
    setup, monkeypatch, stage, message
):
    refused_unread(setup, monkeypatch, message, validation_stage=stage)


@pytest.mark.parametrize(
    ("options", "says"),
    [
        ({"low_pass_hz": 16e9}, "FAIL"),  # a genuine 2 km FAIL
        ({"two_km_xinc": 1.0 / 2e11}, "BLOCKED"),  # a genuine BLOCKED
    ],
)
def test_the_10km_file_is_refused_when_the_committed_2km_record_says_fail(
    world, tmp_path, monkeypatch, options, says
):
    # the fixture is built here, not at collection, so a mutant of the model code cannot break it
    two_km = channel(41, low_pass_hz=options.get("low_pass_hz"))
    s = frozen_only(
        world, tmp_path, monkeypatch, two_km=two_km, two_km_xinc=options.get("two_km_xinc")
    )
    record = s.two_km_record()
    assert json.loads(record)["outcome"] == says and json.loads(record)["carry_forward"] == []
    s.select(ids=["D6"], record=record)  # declared NOT_FAILED by `score`, the record says otherwise
    refused_unread(s, monkeypatch, f"the 2 km record says {says}")


def test_the_10km_file_is_refused_without_a_committed_2km_record(world, tmp_path, monkeypatch):
    s = frozen_only(world, tmp_path, monkeypatch)
    record = s.two_km_record()
    selection = {
        "scenario_ids": json.loads(record)["carry_forward"], "rule": "all_survivors",
        "selected_at_stage": "2km",
        "two_km_result_sha256": hashlib.sha256(record.encode()).hexdigest(),
    }  # fmt: skip
    (s.root / e2_score.SELECTED_PATH).write_text(yaml.safe_dump(selection))
    s.commit_all("a selection typed from memory, no record")
    events = watch_holdout(monkeypatch)
    with pytest.raises(BenchmarkError, match="two_km_result.json: not committed"):
        s.score(s.holdout_10)
    (s.root / e2_score.TWO_KM_RESULT_PATH).write_text(record)  # present, not committed
    with pytest.raises(BenchmarkError, match="two_km_result.json: not committed"):
        s.score(s.holdout_10)
    assert events == []
    assert "two_km_result" in holdout.REQUIRED_INPUTS[Split.LOCKED_TEST]


@pytest.mark.parametrize("which", ["zeros", "other_record"])
def test_the_record_hash_in_the_selection_must_match_the_committed_record(
    world, tmp_path, monkeypatch, which
):
    s = frozen_only(world, tmp_path, monkeypatch)
    record = s.two_km_record()
    sha = "0" * 64 if which == "zeros" else hashlib.sha256((record + " ").encode()).hexdigest()
    s.select(record=record, sha=sha)
    refused_unread(s, monkeypatch, "two_km_result_sha256 is not the committed record's")


@pytest.mark.parametrize("change", ["subset", "permutation"])
def test_the_carried_ids_must_equal_the_records_carry_forward_in_order(
    world, tmp_path, monkeypatch, change
):
    s = frozen_only(world, tmp_path, monkeypatch)
    record = s.two_km_record()
    carried = json.loads(record)["carry_forward"]
    assert len(carried) >= 3
    ids = carried[:-1] if change == "subset" else carried[::-1]
    s.select(ids=ids, record=record)
    refused_unread(s, monkeypatch, "scenario_ids are not the record's carry_forward")


def test_the_carried_ids_must_be_the_carry_rule_of_the_recorded_table(world, tmp_path, monkeypatch):
    s = frozen_only(world, tmp_path, monkeypatch)
    # the ids and the record's carry_forward are edited together; the psi table is not
    record = edited_record(s, lambda d: d.update(carry_forward=["D6"]))
    assert json.loads(record)["scenarios"]["D6"]["psi"] <= 1.0  # D6 did survive at 2 km
    s.select(ids=["D6"], record=record)
    refused_unread(s, monkeypatch, "not the carry rule of the recorded psi table")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(filename=HOLDOUT_10KM), "does not name the registered 2 km file"),
        (lambda d: d.update(split="LOCKED_TEST"), "not a VALIDATION result at 2 km"),
        (lambda d: d.update(length_km=10.0), "not a VALIDATION result at 2 km"),
        (lambda d: d.update(criterion_commit="0" * 40), "not scored at the pinned freeze"),
        (lambda d: d.update(hashes_verified=False), "hashes were not verified"),
        (
            lambda d: d["limits"].update(M1_level_spacing=d["limits"]["M1_level_spacing"] * 2),
            "limit M1_level_spacing differs from the frozen",
        ),
        (lambda d: d.update(scenarios_scored=5), "does not score every listed scenario"),
        (lambda d: d["scenarios"].pop("N2"), "does not score every listed scenario"),
        (lambda d: d.update(report_version=1), "not a report of version 2"),
        (lambda d: d["scenarios"]["N2"].update(psi="0.5"), "psi of N2 is not a finite number"),
    ],
)
def test_the_2km_record_must_name_the_2km_file_at_the_pinned_freeze(
    world, tmp_path, monkeypatch, change, message
):
    s = frozen_only(world, tmp_path, monkeypatch)
    s.select(record=edited_record(s, change))  # one field at a time; the hash is re-tied
    refused_unread(s, monkeypatch, message)


def test_a_record_that_is_not_strict_json_is_refused(world, tmp_path, monkeypatch):
    s = frozen_only(world, tmp_path, monkeypatch)
    text = s.two_km_record()
    duplicated = text.replace(
        '{\n  "amplitude_ratio_vs_b2b"', '{\n  "split": "x",\n  "amplitude_ratio_vs_b2b"', 1
    )
    assert duplicated != text
    s.select(ids=json.loads(text)["carry_forward"], record=duplicated)
    refused_unread(s, monkeypatch, "cannot be read as strict JSON")


def test_the_selection_and_the_record_are_added_as_new_files_in_one_commit(
    world, tmp_path, monkeypatch
):
    # two commits: the record first, the selection later
    s = frozen_only(world, tmp_path, monkeypatch)
    record = s.two_km_record()
    (s.root / e2_score.TWO_KM_RESULT_PATH).write_text(record)
    s.commit_all("record alone")
    ids = json.loads(record)["carry_forward"]
    selection = {
        "scenario_ids": ids, "rule": "all_survivors", "selected_at_stage": "2km",
        "two_km_result_sha256": hashlib.sha256(record.encode()).hexdigest(),
    }  # fmt: skip
    (s.root / e2_score.SELECTED_PATH).write_text(yaml.safe_dump(selection))
    s.commit_all("selection later")
    refused_unread(s, monkeypatch, "must be added together in one commit")


def test_a_record_renamed_in_or_edited_later_is_refused(world, tmp_path, monkeypatch):
    s = frozen_only(world, tmp_path, monkeypatch)
    record = s.two_km_record()
    draft = s.root / e2_score.E2_DIR / "draft_record.json"
    draft.write_text(record)
    s.commit_all("draft record")
    git(s.root, "mv", str(draft.relative_to(s.root)), str(e2_score.TWO_KM_RESULT_PATH))
    ids = json.loads(record)["carry_forward"]
    (s.root / e2_score.SELECTED_PATH).write_text(
        yaml.safe_dump(
            {
                "scenario_ids": ids,
                "rule": "all_survivors",
                "selected_at_stage": "2km",
                "two_km_result_sha256": hashlib.sha256(record.encode()).hexdigest(),
            }
        )  # fmt: skip
    )
    s.commit_all("rename the record in, add the selection")
    refused_unread(s, monkeypatch, "2 km record: must be a new file in its commit")


@pytest.mark.parametrize("which", ["record", "selection"])
def test_a_later_edit_of_the_record_or_the_selection_is_refused(
    world, tmp_path, monkeypatch, which
):
    s = Setup(world, tmp_path, monkeypatch)
    s.score(s.holdout_10)  # added together once: accepted
    path = s.root / (e2_score.TWO_KM_RESULT_PATH if which == "record" else e2_score.SELECTED_PATH)
    path.write_text(path.read_text() + "\n")
    s.commit_all("a later edit")
    name = "2 km record" if which == "record" else "selected scenario"
    refused_unread(s, monkeypatch, f"{name}: added once, never changed, found 2")


def test_the_records_head_commit_lies_between_freeze_and_selection_with_bound_files_unchanged(
    world, tmp_path, monkeypatch
):
    s = frozen_only(world, tmp_path, monkeypatch)
    before_freeze = git(s.root, "rev-parse", "HEAD~1")
    # a bound file changed after the freeze, the 2 km run made there, then the change undone
    study = s.root / e2_score.POWER_STUDY_PATH
    study.write_text("power_study_version: 1\n# changed after the freeze\n")
    s.commit_all("bound file changed")
    changed_at = git(s.root, "rev-parse", "HEAD")
    study.write_text("power_study_version: 1\n")
    s.commit_all("bound file restored")
    git(s.root, "branch", "elsewhere", changed_at)
    git(s.root, "checkout", "-q", "elsewhere")
    (s.root / "unrelated.txt").write_text("x")
    s.commit_all("off the main line")
    off_line = git(s.root, "rev-parse", "HEAD")
    git(s.root, "checkout", "-q", "-")
    cases = [
        (before_freeze, "not between the freeze and the selection commit"),
        (off_line, "not between the freeze and the selection commit"),
        (changed_at, "power_study.yaml: changed since the freeze commit .at the 2 km run's head"),
        ("abc", "head_commit is not a full commit id"),
    ]
    for head, message in cases:
        branch = f"case_{head[:6]}"
        git(s.root, "checkout", "-q", "-b", branch)
        s.select(record=edited_record(s, lambda d, h=head: d.update(head_commit=h)))
        refused_unread(s, monkeypatch, message)
        git(s.root, "checkout", "-q", "-")


def test_a_shared_sequence_forces_exploratory_at_both_lengths(world, tmp_path, monkeypatch):
    shared = holdout.SequenceCheck.SHARED
    failing = score(world, norm(world, channel(28, low_pass_hz=16e9)), length_km=2.0)
    assert failing.outcome == e2_score.OUTCOME_FAIL and failing.verdict is holdout.Verdict.FAILED
    two_shared = score(
        world, norm(world, channel(28, low_pass_hz=16e9)), length_km=2.0, sequence_check=shared
    )
    assert two_shared.outcome == e2_score.OUTCOME_FAIL
    assert two_shared.verdict is holdout.Verdict.EXPLORATORY
    measured = norm(world, channel(26, dispersion=6.352, length_km=10.0))
    ten = locked(world, measured, ["D6", "D3"], validation_stage=holdout.ValidationStage.NOT_FAILED)
    assert ten.outcome == e2_score.OUTCOME_PASS_DISCRIMINATING
    ten_shared = locked(
        world, measured, ["D6", "D3"], validation_stage=holdout.ValidationStage.NOT_FAILED,
        sequence_check=shared,
    )  # fmt: skip
    assert ten_shared.verdict is holdout.Verdict.EXPLORATORY
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        assert holdout.allowed_verdicts(split, sequence_check=shared) == {
            holdout.Verdict.EXPLORATORY,
            holdout.Verdict.BLOCKED,
        }
    # a BLOCKED result stays BLOCKED
    blocked = Setup(world, tmp_path, monkeypatch, two_km=channel(41), two_km_xinc=1.0 / 2e11)
    result = blocked.score(sequence_check=shared)
    assert result.outcome == e2_score.OUTCOME_BLOCKED and result.verdict == "BLOCKED"


def test_an_uncarried_control_within_limits_is_not_a_10km_survivor(world):
    model, scenarios = world["model"], world["scenarios"]
    control = e2_score.predict(model, scenarios[0], 10.0, N)  # exactly the control's prediction
    result = locked(world, control, ["D6"])
    assert result.scenarios["NULL"]["psi"] == pytest.approx(0.0, abs=1e-9)
    assert result.scenarios["D6"]["psi"] > 1.0
    assert result.survivors == () and "NULL" in result.scenarios
    assert result.outcome == e2_score.OUTCOME_FAIL and result.claim == "NO_SCENARIO_FITS"
    assert result.verdict is holdout.Verdict.INCONCLUSIVE


def test_the_report_records_declarations_record_window_and_summary(world, tmp_path, monkeypatch):
    s = Setup(world, tmp_path, monkeypatch)
    two = s.score().report()
    assert two["report_version"] == 2 and two["two_km_record"] is None
    assert two["declarations"] == {"validation_stage": None, "sequence_check": None, "state": None}
    assert "operator declarations, not established" in two["declarations_note"]
    assert "NOT_SHARED cannot be declared here" in two["declarations_note"]
    assert two["window"] == {"start": 2 * N, "samples": N, "sample_rate_hz": pytest.approx(FS)}
    assert two["summary"].startswith("2 km: outcome ") and two["outcome"] in two["summary"]
    assert "the verdict is capped at INCONCLUSIVE by design" in two["summary"]
    assert "amplitude ratio vs B2B" in two["summary"]
    ten = s.score(
        s.holdout_10,
        sequence_check=holdout.SequenceCheck.NOT_RUN,
        state=holdout.HoldoutState.INTACT,
    ).report()
    assert ten["declarations"] == {
        "validation_stage": "NOT_FAILED", "sequence_check": "NOT_RUN", "state": "INTACT",
    }  # fmt: skip
    committed = (s.root / e2_score.TWO_KM_RESULT_PATH).read_bytes()
    selection_commit = git(
        s.root, "log", "-1", "--format=%H", "--", str(e2_score.TWO_KM_RESULT_PATH)
    )
    assert ten["two_km_record"] == {
        "path": e2_score.TWO_KM_RESULT_PATH.as_posix(),
        "sha256": hashlib.sha256(committed).hexdigest(),
        "commit": selection_commit,
    }
    assert ten["summary"].startswith("10 km: outcome ")
    for scenario in ten["survivors"]:
        dispersion = next(x for x in world["scenarios"] if x.scenario_id == scenario)
        assert f"{dispersion.dispersion_ps_nm_km:g}" in ten["summary"]
    assert not any("note only" in n for n in two["notes"])  # amplitude near 1


def test_an_amplitude_ratio_outside_half_to_double_adds_a_note_and_nothing_else(
    world, tmp_path, monkeypatch
):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    quiet = Setup(world, tmp_path / "a", monkeypatch, two_km=channel(41, ratio=0.3))
    report = quiet.score().report()
    assert report["amplitude_ratio_vs_b2b"] < 0.5
    assert any(n.startswith("note only, not a verdict rule") for n in report["notes"])
    normal = Setup(world, tmp_path / "b", monkeypatch, two_km=channel(41))
    plain = normal.score().report()
    assert (report["outcome"], report["verdict"]) == (plain["outcome"], plain["verdict"])


def test_the_2km_report_written_by_the_script_is_a_valid_record_for_the_10km_stage(
    world, tmp_path, monkeypatch, capsys
):
    s = frozen_only(world, tmp_path, monkeypatch)
    for name, sha in s.sha.items():
        monkeypatch.setitem(teriphic.HOLDOUT_SHA256, name, sha)
    code, out, err = run_script(s, s.holdout_2, capsys)
    assert code == 0, err
    two = json.loads(out)
    s.select(record=out)  # the script's stdout, byte for byte; ids are its carry_forward
    assert s.carried == two["carry_forward"] and s.carried
    code, out10, err = run_script(s, s.holdout_10, capsys, "--stage", "not-failed")
    assert code == 0, err
    ten = json.loads(out10)
    assert ten["two_km_record"]["sha256"] == hashlib.sha256(out.encode()).hexdigest()
    assert set(ten["scenarios"]) == set(two["carry_forward"]) | {"NULL"}
    assert ten["verdict"] != "VALIDATED"


def test_the_10km_scorer_uses_the_10km_length(setup):
    result = setup.score(setup.holdout_10)
    window10 = norm(setup.world, channel(42, dispersion=6.352, length_km=10.0))
    again = score(
        setup.world,
        window10,
        setup.comparator(),
        length_km=10.0,
        split=Split.LOCKED_TEST,
        carried=list(setup.carried),
    )
    assert "D6" in setup.carried
    for key in ("D6", "NULL"):
        assert result.scenarios[key]["psi"] == pytest.approx(again.scenarios[key]["psi"], rel=1e-3)
    wrong = score(
        setup.world,
        window10,
        setup.comparator(),
        length_km=2.0,
        split=Split.LOCKED_TEST,
        carried=["D6"],
    )
    assert wrong.scenarios["D6"]["psi"] != pytest.approx(result.scenarios["D6"]["psi"], rel=1e-2)


def test_a_header_with_another_sample_rate_is_blocked(world, tmp_path, monkeypatch):
    s = Setup(world, tmp_path, monkeypatch, two_km=channel(41), two_km_xinc=1.0 / 2e11)
    result = s.score()
    assert result.outcome == e2_score.OUTCOME_BLOCKED and result.verdict == "BLOCKED"
    assert "sample rate" in " ".join(result.notes) and result.scenarios == {}


def test_a_record_shorter_than_the_window_is_blocked(world, tmp_path, monkeypatch):
    s = Setup(world, tmp_path, monkeypatch, two_km=channel(41, n=N))
    short = s.score()
    assert short.outcome == e2_score.OUTCOME_BLOCKED and "shorter" in " ".join(short.notes)


def test_a_nan_in_the_holdout_window_is_refused_not_scored(world, tmp_path, monkeypatch):
    samples = channel(43, dispersion=6.352, length_km=2.0)
    samples[2 * N + 500] = np.nan
    s = Setup(world, tmp_path, monkeypatch, two_km=samples)
    with pytest.raises(BenchmarkError, match="non-finite"):
        s.score()


def test_the_b2b_comparator_must_be_the_b2b_capture(setup):
    wrong = setup.data / "other_b2b.bin"
    write_bin(wrong, channel(77))
    with pytest.raises(BenchmarkError, match="not the B2B capture"):
        setup.score(b2b_path=wrong)


# ---- the frozen evaluation script, end to end through the fixture
def load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "score_script", ROOT / "scripts/score_teriphic_e2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(s, target, capsys, *extra, pin=None):
    script = load_script()
    code = script.main(
        [str(target), "--b2b", str(s.b2b), "--repo", str(s.root),
         "--freeze-commit", pin or s.pin, *extra]
    )  # fmt: skip
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_frozen_script_reaches_every_allowed_verdict_and_never_validated(
    world, tmp_path, monkeypatch, capsys
):
    s = Setup(world, tmp_path, monkeypatch)
    for name, sha in s.sha.items():
        monkeypatch.setitem(teriphic.HOLDOUT_SHA256, name, sha)
    code, out, _ = run_script(s, s.holdout_2, capsys)
    assert code == 0 and '"split": "VALIDATION"' in out
    two = json.loads(out)
    assert (
        two["verdict"] != "VALIDATED" and two["reference_sequence"] == "REFERENCE_SEQUENCE_MISSING"
    )
    seen = set()
    for extra in (
        (), ("--stage", "failed"), ("--stage", "not-failed"),
        ("--stage", "not-failed", "--sequence-check", "not-run", "--state", "intact"),
        ("--stage", "not-failed", "--sequence-check", "shared"),
        ("--stage", "not-failed", "--state", "burned"),
    ):  # fmt: skip
        code, out, err = run_script(s, s.holdout_10, capsys, *extra)
        if "not-failed" not in extra:
            # the two-stage contract: exit code 3, nothing hashed or opened
            assert code == 3 and "two-stage contract" in err
            assert ("2 km stage FAILED" if "failed" in extra else "2 km stage is done") in err
            continue
        assert code == 0, err
        report = json.loads(out)
        seen.add(report["verdict"])
        assert report["verdict"] != "VALIDATED"
        if "burned" in extra or "shared" in extra:
            assert report["verdict"] == "EXPLORATORY"
    assert seen <= {"INCONCLUSIVE", "EXPLORATORY", "UNIDENTIFIABLE_PARAMETER"}
    assert "EXPLORATORY" in seen and ("INCONCLUSIVE" in seen or "UNIDENTIFIABLE_PARAMETER" in seen)
    code, _, err = run_script(s, s.holdout_2, capsys, pin="1" * 40)
    assert code == 2 and "REFUSED" in err and "pinned" in err


def test_the_script_flags_map_to_the_declared_enums():
    script = load_script()
    assert script.STAGES == {
        "failed": holdout.ValidationStage.FAILED,
        "not-failed": holdout.ValidationStage.NOT_FAILED,
    }
    assert script.SEQUENCE == {
        "not-run": holdout.SequenceCheck.NOT_RUN,
        "shared": holdout.SequenceCheck.SHARED,
    }  # NOT_SHARED cannot be declared with the frozen script (plan Revision 13)
    assert script.STATES == {
        "intact": holdout.HoldoutState.INTACT,
        "burned": holdout.HoldoutState.BURNED,
    }


def test_the_frozen_script_cannot_declare_not_shared(setup, capsys):
    with pytest.raises(SystemExit) as raised:
        run_script(setup, setup.holdout_10, capsys, "--stage", "not-failed", "--sequence-check",
                   "not-shared")  # fmt: skip
    assert raised.value.code == 2
    assert holdout.SequenceCheck.NOT_SHARED.value == "NOT_SHARED"  # the enum member stays


# ---------------------------------------------------------------------------- routing (source scan)
def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            yield name, node.lineno


def test_only_the_scorer_and_the_b2b_adapter_open_captures_in_src():
    readers = {"open_keysight_bin", "open_raw", "read_bin", "read_scope_file", "memmap"}
    callers: dict[str, set[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text())
        found = {name for name, _ in _calls(tree) if name in readers}
        # an alias or a getattr by name escapes a call-name scan: look at names and strings too
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in readers:
                found.add(str(node.value))
            if isinstance(node, ast.Name) and node.id in readers:
                found.add(node.id)
            if isinstance(node, ast.alias) and node.name in readers:
                found.add(node.name)
        if found:
            callers[path.relative_to(ROOT).as_posix()] = found
    allowed = {
        "src/opticps/benchmarks/e2_score.py",  # the one holdout reader
        "src/opticps/benchmarks/teriphic.py",  # B2B adapter and the gated inspect route
        # E2c: the declared 2 km calibration route (2 km only, after the R13 FAIL record; D15 a)
        "src/opticps/benchmarks/e2c_calibration.py",
        "src/opticps/benchmarks/external_capture.py",  # the generic reader itself (memmap)
        "src/opticps/measurement/uxr_import.py",  # generic reader, listed in the known limits
        "src/opticps/measurement/uxr_ingest.py",  # `ingest-uxr`, CLI-gated, listed in the limits
    }
    assert set(callers) <= allowed, {k: v for k, v in callers.items() if k not in allowed}
    assert "src/opticps/benchmarks/e2_score.py" in callers


def test_the_scoring_entry_point_checks_before_it_reads_and_reads_the_holdout_last():
    tree = ast.parse((ROOT / "src/opticps/benchmarks/e2_score.py").read_text())
    function = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "score_holdout"
    )
    order = [name for name, _ in sorted(_calls(function), key=lambda item: item[1])]
    steps = [
        "require_frozen_criterion",
        "require_freeze_pin",
        "verify_loaded_code",
        "bind_to_freeze",
        "verify_code_identity",
        "check_registered_limits",
        "read_two_km_record",
        "gate_sample_read",
        "_read_window",  # the B2B comparator
        "check_reproduction",
        "verify_local_asset",  # the holdout's hashes
    ]
    positions = [order.index(step) for step in steps]
    assert positions == sorted(positions) and len(set(positions)) == len(steps)
    reads = [i for i, name in enumerate(order) if name == "_read_window"]
    assert len(reads) == 2 and reads[0] < order.index("check_reproduction")
    assert reads[1] > order.index("verify_local_asset")  # the holdout window is read last
    assert "open_keysight_bin" not in order and "read" not in order  # only through _read_window
    assert order.index("score_windows") > reads[1]


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
    assert registered["results"] is None and registered["scenario_count"] == len(scenarios) == 123
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


# ---- R13 against the R12 freeze: the science is unchanged (plan Revision 13, item 16 as read)
R12_FREEZE = "04360ec6a44bb6aaa2222cc605ab3979718be50a"
R12_CRITERION = Path("docs/benchmarks/TERIPHIC_CRITERION_R12.yaml")
# The only fields of the three documents that may differ from the R12 freeze: the code identity
# the freeze script regenerates in the model, and the model hash that ties the other two to it.
REGENERATED_FIELDS = {
    "b2b_model.yaml": "code_identity",
    "preregistered_predictions.yaml": "model_sha256",
    "power_study.yaml": "model_sha256",
}
# SHA-256 of each R12-freeze document (git show 04360ec) as sorted JSON, without that field.
R12_SCIENCE_SHA256 = {
    "b2b_model.yaml": "9a76d2b6c688d123e7f55c3a293c9c7fd1adf596d84b409cdecbeecb3d3c20d3",
    "preregistered_predictions.yaml": (
        "9c774622906230fb25991cd376faf8d4c7998dddb59d0a511dc0a75cb235fe9e"
    ),
    "power_study.yaml": "48cf3a9c97054974ac3d72b6f084b009a1a67f5a6a76313013dcf6c50d441ede",
}


def science(data: bytes, name: str) -> dict:
    document = yaml.safe_load(data)
    document.pop(REGENERATED_FIELDS[name])
    return document


def science_sha256(data: bytes, name: str) -> str:
    return hashlib.sha256(json.dumps(science(data, name), sort_keys=True).encode()).hexdigest()


def test_the_committed_e2_documents_hold_the_r12_science_and_are_tied_to_each_other():
    """Fitted values, limits, scenarios, predictions, power study, seeds and windows: as at R12."""
    for name, digest in R12_SCIENCE_SHA256.items():
        data = (ROOT / e2_score.E2_DIR / name).read_bytes()
        assert science_sha256(data, name) == digest, name
    model = hashlib.sha256((ROOT / e2_score.MODEL_PATH).read_bytes()).hexdigest()
    for path in (e2_score.PREREGISTRATION_PATH, e2_score.POWER_STUDY_PATH):
        assert yaml.safe_load((ROOT / path).read_bytes())["model_sha256"] == model


def test_real_r13_documents_equal_the_r12_freeze_except_the_regenerated_fields():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    for name in REGENERATED_FIELDS:
        relative = (e2_score.E2_DIR / name).as_posix()
        then = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{R12_FREEZE}:{relative}"],
            check=True, capture_output=True,
        ).stdout  # fmt: skip
        now = (ROOT / relative).read_bytes()
        assert science(now, name) == science(then, name), name
        assert science_sha256(then, name) == R12_SCIENCE_SHA256[name]
    scenarios = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{R12_FREEZE}:{e2_score.SCENARIO_PATH.as_posix()}"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    assert scenarios == (ROOT / e2_score.SCENARIO_PATH).read_bytes()


def test_real_r13_limits_equal_r12_and_the_plan_hash_differs():
    r12 = yaml.safe_load((ROOT / R12_CRITERION).read_bytes())
    r13 = yaml.safe_load((ROOT / holdout.CRITERION_PATH).read_bytes())
    assert holdout.CRITERION_PATH.name == "TERIPHIC_CRITERION_R13.yaml"
    for key in ("limits", "b2b_basis", "multipliers"):
        assert set(r13[key]) == set(r12[key]) == set(holdout.METRICS)
        for metric in holdout.METRICS:
            assert math.isclose(r13[key][metric], r12[key][metric], rel_tol=1e-9), (key, metric)
    assert r13["estimators"] == r12["estimators"] == dict(holdout.ESTIMATORS)
    assert r13["criterion_version"] == r12["criterion_version"] == 3
    assert r13["plan_sha256"] != r12["plan_sha256"]
    plan = hashlib.sha256((ROOT / holdout.DEFAULT_PLAN).read_bytes()).hexdigest()
    assert r13["plan_sha256"] == plan
