"""Mutation check of the Gate E2 part a code (estimators, surrogate, scorer entry point).

Each mutant is one text replacement in `src/opticps/benchmarks/e2_*.py`, `holdout.py` or (one
mutant) a committed E2 document, applied to a scratch copy
of the repository files the E2 test file needs. The copy is a git repository (`git init`,
`git add`), so freeze related tests do not give false kills. The tests whose names start with
`test_real_` read the committed freeze or the B2B capture and are deselected: a changed code file
would fail the committed code identity and kill every mutant for the wrong reason. The test file
runs against the copy; a mutant is "killed" when a test fails (pytest exit code 1). A mutant that
breaks collection (2 or more) is BROKEN, never killed, and the unmutated copy must pass first. A
mutant listed with a reason is a harmless unpinned survivor, not an equivalent mutant: it is run,
reported, and not counted against the exit code.

    python scripts/mutate_e2.py [-j JOBS] [-k LABEL_SUBSTRING] [--check]

`--check` only verifies that every `old` text occurs exactly once. The list is a sample of the
guards written by hand; it proves nothing about mutants that are not in it.
"""

# SPDX-License-Identifier: MIT
# ruff: noqa: E501  (each mutant is one long line: its text is the point)
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM = "src/opticps/benchmarks/e2_metrics.py"
MO = "src/opticps/benchmarks/e2_model.py"
SC = "src/opticps/benchmarks/e2_score.py"
HO = "src/opticps/benchmarks/holdout.py"
MODEL_DOC = "docs/benchmarks/teriphic_e2/b2b_model.yaml"
# A mutant of the model document re-ties the model hash in these, as a consistent edit would.
REHASH = {
    MODEL_DOC: (
        "docs/benchmarks/teriphic_e2/preregistered_predictions.yaml",
        "docs/benchmarks/teriphic_e2/power_study.yaml",
    )
}
# (label, file, old, new, reason a surviving mutant is harmless, or None); `old` occurs exactly once.
Mutant = tuple[str, str, str, str, str | None]
MUTANTS: list[Mutant] = [
    (
        "km_tolerance_loose",
        "src/opticps/benchmarks/e2_metrics.py",
        "KMEANS_TOLERANCE = 1e-9",
        "KMEANS_TOLERANCE = 1e-1",
        None,
    ),
    (
        "km_one_iteration",
        "src/opticps/benchmarks/e2_metrics.py",
        "KMEANS_MAX_ITERATIONS = 200",
        "KMEANS_MAX_ITERATIONS = 1",
        None,
    ),
    (
        "km_empty_cluster_allowed",
        "src/opticps/benchmarks/e2_metrics.py",
        "        if (counts <= 0).any():",
        "        if False:",
        None,
    ),
    (
        "km_flat_window_allowed",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if not spread > 0.0:",
        "    if False:",
        None,
    ),
    (
        "gaps_order_unchecked",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if gaps.shape != (3,) or not (gaps > 0).all():",
        "    if gaps.shape != (3,):",
        None,
    ),
    (
        "m1_sum_not_max",
        "src/opticps/benchmarks/e2_metrics.py",
        "return float(np.max(np.abs(np.asarray(gaps_m) - np.asarray(gaps_p))))",
        "return float(np.sum(np.abs(np.asarray(gaps_m) - np.asarray(gaps_p))))",
        None,
    ),
    (
        "quantile_lower_index_only",
        "src/opticps/benchmarks/e2_metrics.py",
        "ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower])",
        "ordered[lower]",
        None,
    ),
    (
        "quantile_h_uses_n",
        "src/opticps/benchmarks/e2_metrics.py",
        "    h = (ordered.size - 1) * p\n",
        "    h = ordered.size * p\n    h = np.minimum(h, ordered.size - 1)\n",
        None,
    ),
    (
        "quantile_range_unchecked",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if not ((p >= 0.0).all() and (p <= 1.0).all()):",
        "    if False:",
        None,
    ),
    (
        "m2_probabilities_no_half",
        "src/opticps/benchmarks/e2_metrics.py",
        "    return (np.arange(W1_POINTS, dtype=np.float64) + 0.5) / W1_POINTS",
        "    return np.arange(W1_POINTS, dtype=np.float64) / (W1_POINTS - 1)",
        None,
    ),
    (
        "m2_points_1024",
        "src/opticps/benchmarks/e2_metrics.py",
        "W1_POINTS = 65536",
        "W1_POINTS = 1024",
        None,
    ),
    (
        "m2_max_not_mean",
        "src/opticps/benchmarks/e2_metrics.py",
        "np.mean(np.abs(measured.quantile_u - predicted.quantile_u))",
        "np.max(np.abs(measured.quantile_u - predicted.quantile_u))",
        None,
    ),
    (
        "m2_standalone_max",
        "src/opticps/benchmarks/e2_metrics.py",
        "    return float(np.mean(np.abs(q_m - q_p)))",
        "    return float(np.max(np.abs(q_m - q_p)))",
        None,
    ),
    (
        "m3_drops_99_point",
        "src/opticps/benchmarks/e2_metrics.py",
        "QUANTILE_POINTS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)",
        "QUANTILE_POINTS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95)",
        None,
    ),
    (
        "m3_mean_not_max",
        "src/opticps/benchmarks/e2_metrics.py",
        "float(np.max(np.abs(measured.quantile_p - predicted.quantile_p)))",
        "float(np.mean(np.abs(measured.quantile_p - predicted.quantile_p)))",
        None,
    ),
    (
        "m3_standalone_mean",
        "src/opticps/benchmarks/e2_metrics.py",
        "    return float(np.max(np.abs(q_m - q_p)))",
        "    return float(np.mean(np.abs(q_m - q_p)))",
        None,
    ),
    (
        "m4_band_twice_baud",
        "src/opticps/benchmarks/e2_metrics.py",
        "mask: NDArray[np.bool_] = frequency <= baud_bd * (1.0 + 1e-9)",
        "mask: NDArray[np.bool_] = frequency <= 2.0 * baud_bd",
        None,
    ),
    (
        "m4_band_excludes_baud",
        "src/opticps/benchmarks/e2_metrics.py",
        "mask: NDArray[np.bool_] = frequency <= baud_bd * (1.0 + 1e-9)",
        "mask: NDArray[np.bool_] = frequency < baud_bd * (1.0 - 1e-9)",
        None,
    ),
    (
        "m4_factor_20",
        "src/opticps/benchmarks/e2_metrics.py",
        "ratio_db = 10.0 * np.log10(p_m / p_p)",
        "ratio_db = 20.0 * np.log10(p_m / p_p)",
        None,
    ),
    (
        "m4_mean_abs_not_rms",
        "src/opticps/benchmarks/e2_metrics.py",
        "value = float(np.sqrt(np.mean(ratio_db**2)))",
        "value = float(np.mean(np.abs(ratio_db)))",
        None,
    ),
    (
        "m4_positive_unchecked",
        "src/opticps/benchmarks/e2_metrics.py",
        "if p_m.shape != p_p.shape or not ((p_m > 0).all() and (p_p > 0).all()):",
        "if p_m.shape != p_p.shape:",
        None,
    ),
    (
        "m4_min_bins_unchecked",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if int(mask.sum()) < 8:",
        "    if False:",
        None,
    ),
    (
        "welch_overlap_1024",
        "src/opticps/benchmarks/e2_metrics.py",
        "WELCH_OVERLAP = 2048",
        "WELCH_OVERLAP = 1024",
        None,
    ),
    (
        "welch_no_detrend",
        "src/opticps/benchmarks/e2_metrics.py",
        'detrend="constant",',
        "detrend=False,",
        None,
    ),
    (
        "welch_rectangular_window",
        "src/opticps/benchmarks/e2_metrics.py",
        'window="hann",',
        'window="boxcar",',
        None,
    ),
    (
        "welch_segment_2048",
        "src/opticps/benchmarks/e2_metrics.py",
        "WELCH_SEGMENT = 4096",
        "WELCH_SEGMENT = 2048",
        None,
    ),
    (
        "window_nonfinite_allowed",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if not np.isfinite(array).all():",
        "    if False:",
        None,
    ),
    (
        "window_minimum_ignored",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if array.size < minimum:",
        "    if False:",
        None,
    ),
    (
        "window_ndim_ignored",
        "src/opticps/benchmarks/e2_metrics.py",
        "    if array.ndim != 1:",
        "    if False:",
        None,
    ),
    (
        "normalise_scale_unchecked",
        "src/opticps/benchmarks/e2_metrics.py",
        "or g0 <= 0:",
        "or False:",
        None,
    ),
    (
        "normalise_multiplies",
        "src/opticps/benchmarks/e2_metrics.py",
        "return (np.asarray(x, dtype=np.float64) - c0) / g0",
        "return (np.asarray(x, dtype=np.float64) - c0) * g0",
        None,
    ),
    (
        "summary_density_unbanded",
        "src/opticps/benchmarks/e2_metrics.py",
        "        density[keep],\n        frequency[keep],",
        "        density,\n        frequency[keep],",
        None,
    ),
    (
        "dispersion_linear_in_f",
        "src/opticps/benchmarks/e2_model.py",
        "* frequency_hz**2 / SPEED_OF_LIGHT_M_S",
        "* frequency_hz / SPEED_OF_LIGHT_M_S",
        None,
    ),
    (
        "dispersion_wavelength_1550",
        "src/opticps/benchmarks/e2_model.py",
        "NOMINAL_WAVELENGTH_NM = 1310.0",
        "NOMINAL_WAVELENGTH_NM = 1550.0",
        None,
    ),
    (
        "dispersion_negative_length_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "    if length_km < 0:",
        "    if False:",
        None,
    ),
    (
        "dispersion_nonfinite_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "        if not math.isfinite(value):",
        "        if False:",
        None,
    ),
    (
        "dispersion_unit_wrong",
        "src/opticps/benchmarks/e2_model.py",
        "d_si = dispersion_ps_nm_km * 1e-6",
        "d_si = dispersion_ps_nm_km * 1e-3",
        None,
    ),
    (
        "loss_20_not_10",
        "src/opticps/benchmarks/e2_model.py",
        "10.0 ** (-attenuation_db_per_km * length_km / 10.0)",
        "10.0 ** (-attenuation_db_per_km * length_km / 20.0)",
        None,
    ),
    (
        "loss_negative_attenuation_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "math.isfinite(attenuation_db_per_km) and attenuation_db_per_km >= 0",
        "math.isfinite(attenuation_db_per_km)",
        None,
    ),
    (
        "ratio_tolerance_ignored",
        "src/opticps/benchmarks/e2_model.py",
        "if abs(float(fraction) - value) > 1e-9 * value or fraction < 4:",
        "if fraction < 4:",
        None,
    ),
    (
        "ratio_minimum_ignored",
        "src/opticps/benchmarks/e2_model.py",
        "if abs(float(fraction) - value) > 1e-9 * value or fraction < 4:",
        "if abs(float(fraction) - value) > 1e-9 * value:",
        None,
    ),
    (
        "pulse_unnormalised",
        "src/opticps/benchmarks/e2_model.py",
        "    return build(response) / scale",
        "    return build(response)",
        None,
    ),
    (
        "pulse_odd_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "if pulse_samples < 64 or pulse_samples % 2:",
        "if pulse_samples < 64:",
        None,
    ),
    (
        "pulse_dispersion_ignored",
        "src/opticps/benchmarks/e2_model.py",
        "    return build(response) / scale",
        "    return build(np.ones_like(magnitude)) / scale",
        None,
    ),
    (
        "fractional_delay_wrong_sign",
        "src/opticps/benchmarks/e2_model.py",
        "phase = np.exp(-2j * np.pi * np.fft.rfftfreq(n) * fraction)",
        "phase = np.exp(2j * np.pi * np.fft.rfftfreq(n) * fraction)",
        None,
    ),
    (
        "noise_spread_unscaled",
        "src/opticps/benchmarks/e2_model.py",
        "np.asarray(noise * (sigma / spread), dtype=np.float64)",
        "np.asarray(noise, dtype=np.float64)",
        None,
    ),
    (
        "noise_negative_sigma_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "if not (math.isfinite(sigma) and sigma >= 0):",
        "if not math.isfinite(sigma):",
        None,
    ),
    (
        "noise_shape_flat",
        "src/opticps/benchmarks/e2_model.py",
        "    shape = np.interp(freq, grid, magnitude)",
        "    shape = np.ones_like(freq)",
        None,
    ),
    (
        "synth_fraction_denominator",
        "src/opticps/benchmarks/e2_model.py",
        "shifted = fractional_pulse(base, fraction / classes)",
        "shifted = fractional_pulse(base, fraction / (classes + 1))",
        None,
    ),
    (
        "synth_amplitude_ratio_unused",
        "src/opticps/benchmarks/e2_model.py",
        "out = amplitude_ratio * crop + (",
        "out = crop + (",
        None,
    ),
    (
        "synth_noise_ignores_signal_flag",
        "src/opticps/benchmarks/e2_model.py",
        "(amplitude_ratio * noise if noise_follows_signal else noise)",
        "noise",
        None,
    ),
    (
        "synth_noise_always_follows",
        "src/opticps/benchmarks/e2_model.py",
        "(amplitude_ratio * noise if noise_follows_signal else noise)",
        "(amplitude_ratio * noise)",
        None,
    ),
    (
        "synth_probabilities_unchecked",
        "src/opticps/benchmarks/e2_model.py",
        "if (probabilities < 0).any():",
        "if False:",
        None,
    ),
    (
        "synth_short_window_allowed",
        "src/opticps/benchmarks/e2_model.py",
        "if type(n_samples) is not int or n_samples < 1024:",
        "if type(n_samples) is not int:",
        None,
    ),
    (
        "synth_dispersion_ignored",
        "src/opticps/benchmarks/e2_model.py",
        "        dispersion_ps_nm_km=dispersion_ps_nm_km,\n        length_km=length_km,\n        pulse_samples=pulse_length,",
        "        dispersion_ps_nm_km=0.0,\n        length_km=length_km,\n        pulse_samples=pulse_length,",
        None,
    ),
    (
        "fit_uniform_probabilities_changed",
        "src/opticps/benchmarks/e2_model.py",
        '"level_probabilities": [0.25, 0.25, 0.25, 0.25],',
        '"level_probabilities": [0.4, 0.2, 0.2, 0.2],',
        None,
    ),
    (
        "fit_level_update_wrong_sign",
        "src/opticps/benchmarks/e2_model.py",
        "levels = levels + (target_centroids - kmeans_levels(y)[0])",
        "levels = levels - (target_centroids - kmeans_levels(y)[0])",
        None,
    ),
    (
        "scenario_null_count_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "    if sum(s.null_control for s in scenarios) != 1:",
        "    if False:",
        None,
    ),
    (
        "scenario_duplicate_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if identifier in {s.scenario_id for s in scenarios}:",
        "        if False:",
        None,
    ),
    (
        "scenario_count_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if body["count"] != len(entries) or type(body["count"]) is not int:',
        "    if False:",
        None,
    ),
    (
        "scenario_flag_untyped",
        "src/opticps/benchmarks/e2_score.py",
        "            if type(entry[flag]) is not bool:",
        "            if False:",
        None,
    ),
    (
        "model_nonfinite_list_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "            if not math.isfinite(float(item)):",
        "            if False:",
        None,
    ),
    (
        "identity_check_skipped",
        "src/opticps/benchmarks/e2_score.py",
        "    changed = sorted(p for p in actual if actual[p] != recorded[p])",
        "    changed = []",
        None,
    ),
    (
        "identity_symlink_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if path.is_symlink() or not path.is_file():",
        "        if not path.is_file():",
        None,
    ),
    (
        "exceedance_min_not_max",
        "src/opticps/benchmarks/e2_score.py",
        "    return max(ratios)",
        "    return min(ratios)",
        None,
    ),
    (
        "exceedance_nan_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if not math.isfinite(value) or value < 0:",
        "        if False:",
        None,
    ),
    (
        "copy_always_ok",
        "src/opticps/benchmarks/e2_score.py",
        "copy_ok = bool(copy_psi <= 1.0)",
        "copy_ok = True",
        None,
    ),
    (
        "copy_never_ok",
        "src/opticps/benchmarks/e2_score.py",
        "copy_ok = bool(copy_psi <= 1.0)",
        "copy_ok = False",
        None,
    ),
    (
        "fail_verdict_inconclusive",
        "src/opticps/benchmarks/e2_score.py",
        "        verdict = Verdict.FAILED",
        "        verdict = Verdict.INCONCLUSIVE",
        None,
    ),
    (
        "validation_stage_verdict_set",
        "src/opticps/benchmarks/e2_score.py",
        "        verdict = None  # plan R.5: within criterion at the selection stage, no verdict",
        "        verdict = Verdict.VALIDATED",
        None,
    ),
    (
        "unidentifiable_swapped",
        "src/opticps/benchmarks/e2_score.py",
        "Verdict.INCONCLUSIVE if identifiable_in_principle else Verdict.UNIDENTIFIABLE_PARAMETER",
        "Verdict.UNIDENTIFIABLE_PARAMETER if identifiable_in_principle else Verdict.INCONCLUSIVE",
        None,
    ),
    (
        "role_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if split not in HOLDOUT_SPLITS:\n        raise BenchmarkError(f"{split.value} is not a holdout role")',
        '    if False:\n        raise BenchmarkError(f"{split.value} is not a holdout role")',
        None,
    ),
    (
        "window_size_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "    if measured.size != n_samples or comparator.size != n_samples:",
        "    if False:",
        None,
    ),
    (
        "limit_positivity_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '        _positive(limits[name], f"limit {name}")',
        "        pass",
        None,
    ),
    (
        "limit_keys_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "    if set(limits) != set(METRICS):",
        "    if False:",
        None,
    ),
    (
        "separable_ignores_control",
        "src/opticps/benchmarks/e2_score.py",
        '"separable": bool(psi > 1.0) and not scenario.null_control,',
        '"separable": bool(psi > 1.0),',
        None,
    ),
    (
        "separable_never",
        "src/opticps/benchmarks/e2_score.py",
        '"separable": bool(psi > 1.0) and not scenario.null_control,',
        '"separable": False,',
        None,
    ),
    (
        "reproduction_tolerance_loose",
        "src/opticps/benchmarks/e2_score.py",
        "REPRODUCTION_RTOL = 1e-6",
        "REPRODUCTION_RTOL = 1e-1",
        None,
    ),
    (
        "reproduction_keys_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "    if set(a) != set(b):",
        "    if False:",
        None,
    ),
    (
        "reproduction_flag_flip_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "            if x is not y:",
        "            if False:",
        None,
    ),
    (
        "registered_limits_loose",
        "src/opticps/benchmarks/e2_score.py",
        "if not math.isclose(float(recorded[name]), limits[name], rel_tol=1e-9):",
        "if not math.isclose(float(recorded[name]), limits[name], rel_tol=1.0):",
        None,
    ),
    (
        "registered_count_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if len(scenarios) != int(registration.get("scenario_count", -1)):',
        "    if False:",
        None,
    ),
    (
        "length_of_2km_wrong",
        "src/opticps/benchmarks/e2_score.py",
        '"50G_PAM4_PD1_2km_Subassembly1.bin": 2.0,',
        '"50G_PAM4_PD1_2km_Subassembly1.bin": 3.0,',
        None,
    ),
    (
        "guard_after_a_hash",
        "src/opticps/benchmarks/e2_score.py",
        "    asset = _holdout_asset(holdout_path, source)\n",
        "    asset = _holdout_asset(holdout_path, source)\n    verify_local_asset(holdout_path, None)\n",
        None,
    ),
    (
        "guard_after_b2b_gate",
        "src/opticps/benchmarks/e2_score.py",
        "    asset = _holdout_asset(holdout_path, source)\n",
        "    asset = _holdout_asset(holdout_path, source)\n    teriphic.gate_sample_read(b2b_path, source)\n",
        None,
    ),
    (
        "guard_inputs_empty",
        "src/opticps/benchmarks/e2_score.py",
        "        inputs=_inputs(asset, root),",
        "        inputs={},",
        None,
    ),
    (
        "guard_stage_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "        validation_stage=validation_stage,\n    )\n    if frozen is None:",
        "    )\n    if frozen is None:",
        None,
    ),
    (
        "model_hash_not_compared",
        "src/opticps/benchmarks/e2_score.py",
        "    if sha256_of(model_bytes) != frozen.inputs[model_key]:",
        "    if False:",
        "covered: bind_to_freeze compares the same bytes with the freeze commit first",
    ),
    (
        "scenario_hash_not_compared",
        "src/opticps/benchmarks/e2_score.py",
        '        and sha256_of(scenario_bytes) != frozen.inputs["scenario_list"]',
        "        and False",
        "covered: bind_to_freeze compares the same bytes with the freeze commit first",
    ),
    (
        "registration_untied_model",
        "src/opticps/benchmarks/e2_score.py",
        '        or registration.get("model_sha256") != sha256_of(model_bytes)\n',
        "",
        None,
    ),
    (
        "registration_untied_scenarios",
        "src/opticps/benchmarks/e2_score.py",
        '        or registration.get("scenario_list_sha256") != sha256_of(scenario_bytes)\n',
        "",
        None,
    ),
    (
        "registration_result_allowed",
        "src/opticps/benchmarks/e2_score.py",
        '    if registration.get("results") is not None:',
        "    if False:",
        None,
    ),
    (
        "identity_not_verified",
        "src/opticps/benchmarks/e2_score.py",
        "    verify_code_identity(model, root)\n    limits = {name",
        "    limits = {name",
        None,
    ),
    (
        "md5_not_required",
        "src/opticps/benchmarks/e2_score.py",
        "if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:",
        "if checksum.sha256_local != expected_sha:",
        None,
    ),
    (
        "sha_not_required",
        "src/opticps/benchmarks/e2_score.py",
        "if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:",
        "if checksum.md5_state is not Md5State.VERIFIED:",
        None,
    ),
    (
        "sha_missing_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "    if expected_sha is None:",
        "    if False:",
        None,
    ),
    (
        "b2b_md5_not_required",
        "src/opticps/benchmarks/e2_score.py",
        "    if not gate.is_b2b:",
        "    if False:",
        None,
    ),
    (
        "sample_rate_tolerance_loose",
        "src/opticps/benchmarks/e2_score.py",
        "SAMPLE_RATE_RTOL = 1e-6",
        "SAMPLE_RATE_RTOL = 1.0",
        None,
    ),
    (
        "bind_call_removed",
        "src/opticps/benchmarks/e2_score.py",
        "    bind_to_freeze(root, frozen)\n",
        "",
        None,
    ),
    (
        "bind_ancestor_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if _git(root, "merge-base", "--is-ancestor", frozen.commit, revision).returncode != 0:',
        "    if False:",
        "defensive: the guard already follows the history of the freeze commit from HEAD",
    ),
    (
        "bind_missing_at_freeze_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if then is None:",
        "        if False:",
        None,
    ),
    (
        "bind_change_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if then != now:",
        "        if False:",
        None,
    ),
    (
        "bind_skips_code",
        "src/opticps/benchmarks/e2_score.py",
        "    for relative in (*paths, *map(Path, CODE_IDENTITY_FILES)):",
        "    for relative in paths:",
        None,
    ),
    (
        "selected_present_at_freeze_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "    if _blob(root, frozen.commit, relative) is not None:",
        "    if False:",
        None,
    ),
    (
        "selected_many_commits_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "    if len(commits) != 1:",
        "    if len(commits) < 1:",
        None,
    ),
    (
        "selected_not_after_freeze_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        added == frozen.commit\n        or _git(",
        "        False\n        and _git(",
        "defensive: a side-branch addition shows up as a second log entry first (found 2)",
    ),
    (
        "selected_change_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "    if _blob(root, added, relative) != now:",
        "    if False:",
        "defensive: a changed file is a second log entry first (found 2)",
    ),
    (
        "renorm_centre_not_removed",
        "src/opticps/benchmarks/e2_metrics.py",
        "return (values - centre) / gap, centre, gap",
        "return values / gap, centre, gap",
        None,
    ),
    (
        "renorm_gap_is_max",
        "src/opticps/benchmarks/e2_metrics.py",
        "gap = float(np.diff(centroids).mean())",
        "gap = float(np.diff(centroids).max())",
        None,
    ),
    (
        "renorm_small_window_allowed",
        "src/opticps/benchmarks/e2_metrics.py",
        "minimum=KMEANS_K * 16)\n    centroids, _ = kmeans_levels(values)",
        "minimum=1)\n    centroids, _ = kmeans_levels(values)",
        "defensive: kmeans_levels refuses a short window with its own minimum",
    ),
    (
        "noise_through_fibre_ignored",
        "src/opticps/benchmarks/e2_model.py",
        "    if noise_through_fibre:\n",
        "    if False:\n",
        None,
    ),
    (
        "noise_through_fibre_always",
        "src/opticps/benchmarks/e2_model.py",
        "    if noise_through_fibre:\n",
        "    if True:\n",
        None,
    ),
    (
        "scenario_noise_factor_zero_allowed",
        "src/opticps/benchmarks/e2_score.py",
        '_positive(entry["noise_factor"], f"{identifier} noise factor")',
        '_non_negative(entry["noise_factor"], f"{identifier} noise factor")',
        None,
    ),
    (
        "scenario_through_without_dispersion_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if scenario.noise_through_fibre and scenario.dispersion_ps_nm_km == 0.0:",
        "        if False:",
        None,
    ),
    (
        "scenario_control_shape_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "        if scenario.null_control and (",
        "        if False and (",
        None,
    ),
    (
        "loaded_code_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "        if origin != (root / relative).resolve():",
        "        if False:",
        None,
    ),
    (
        "loaded_module_missing_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if origin is None:",
        "        if False:",
        None,
    ),
    (
        "carry_margin_strict",
        "src/opticps/benchmarks/e2_score.py",
        "survivors[0][0] + SELECTION_MARGIN <= survivors[1][0]",
        "survivors[0][0] + SELECTION_MARGIN < survivors[1][0]",
        None,
    ),
    (
        "carry_margin_zero",
        "src/opticps/benchmarks/e2_score.py",
        "SELECTION_MARGIN = 0.25",
        "SELECTION_MARGIN = 0.0",
        None,
    ),
    (
        "carry_single_survivor_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "if len(survivors) == 1 or ",
        "if ",
        None,
    ),
    (
        "carry_order_by_psi",
        "src/opticps/benchmarks/e2_score.py",
        "tuple(k for _, _, k in sorted(survivors, key=lambda item: item[1]))",
        "tuple(k for _, _, k in survivors)",
        None,
    ),
    (
        "carry_never_single",
        "src/opticps/benchmarks/e2_score.py",
        "if len(survivors) == 1 or survivors[0][0] + SELECTION_MARGIN <= survivors[1][0]:",
        "if False:",
        None,
    ),
    (
        "survivor_strict_within",
        "src/opticps/benchmarks/e2_score.py",
        'survivors = tuple(i for i in judged if table[i]["psi"] <= 1.0)',
        'survivors = tuple(i for i in judged if table[i]["psi"] < 1.0)',
        None,
    ),
    (
        "copy_strict_within",
        "src/opticps/benchmarks/e2_score.py",
        "copy_ok = bool(copy_psi <= 1.0)",
        "copy_ok = bool(copy_psi < 1.0)",
        None,
    ),
    (
        "null_strict_within",
        "src/opticps/benchmarks/e2_score.py",
        'null_ok = bool(table[null_id]["psi"] <= 1.0)',
        'null_ok = bool(table[null_id]["psi"] < 1.0)',
        None,
    ),
    (
        "null_rule_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "elif copy_ok or null_ok or not fibre_survivors:",
        "elif copy_ok or not fibre_survivors:",
        None,
    ),
    (
        "only_control_rule_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "elif copy_ok or null_ok or not fibre_survivors:",
        "elif copy_ok or null_ok:",
        "equivalent: with a survivor set that holds only the control, null_ok is already true",
    ),
    (
        "copy_rule_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "elif copy_ok or null_ok or not fibre_survivors:",
        "elif null_ok or not fibre_survivors:",
        None,
    ),
    (
        "verdict_validated_when_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        verdict = Verdict.INCONCLUSIVE  # capped: PARTIAL claim, never VALIDATED (R12.4)",
        "        verdict = Verdict.VALIDATED",
        None,
    ),
    (
        "verdict_clamp_blocked_first",
        "src/opticps/benchmarks/e2_score.py",
        "verdict = Verdict.EXPLORATORY if Verdict.EXPLORATORY in allowed else Verdict.BLOCKED",
        "verdict = Verdict.BLOCKED",
        None,
    ),
    (
        "verdict_clamp_removed",
        "src/opticps/benchmarks/e2_score.py",
        "    if verdict is not None and verdict not in allowed:",
        "    if False:",
        None,
    ),
    (
        "claim_not_partial",
        "src/opticps/benchmarks/e2_score.py",
        "        claim = CLAIM_PARTIAL",
        "        claim = None",
        None,
    ),
    (
        "control_not_scored_in_locked_test",
        "src/opticps/benchmarks/e2_score.py",
        "scored_ids = [i for i in ids if i in set(carried) or i == null_id]",
        "scored_ids = [i for i in ids if i in set(carried)]",
        None,
    ),
    (
        "locked_test_without_carried_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if not carried:\n",
        "        if False:\n",
        None,
    ),
    (
        "carried_unknown_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "        if len(set(carried)) != len(carried) or any(c not in ids for c in carried):",
        "        if False:",
        None,
    ),
    (
        "two_km_may_carry_in",
        "src/opticps/benchmarks/e2_score.py",
        "        if carried is not None:\n",
        "        if False:\n",
        None,
    ),
    (
        "gain_ratio_unit",
        "src/opticps/benchmarks/e2_score.py",
        "    measured_n, _, gain = renormalise(measured)",
        "    measured_n, _, gain = renormalise(measured)\n    gain = 1.0",
        None,
    ),
    (
        "measured_not_renormalised",
        "src/opticps/benchmarks/e2_score.py",
        "    measured_summary = summarise_window(measured_n, fs, baud)",
        "    measured_summary = summarise_window(measured, fs, baud)",
        None,
    ),
    (
        "identifiable_counts_noise_scenarios",
        "src/opticps/benchmarks/e2_score.py",
        "            if s.noise_factor == 1.0 and not s.noise_through_fibre and not s.null_control",
        "            if not s.null_control",
        None,
    ),
    (
        "role_by_name_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "        if ROLE_BY_NAME.get(asset.filename) is not asset.split:",
        "        if False:",
        None,
    ),
    (
        "first_parent_dropped",
        "src/opticps/benchmarks/e2_score.py",
        'root, "log", "--first-parent", "--reverse", "--format=%H", "--", CRITERION_PATH.as_posix()',
        'root, "log", "--reverse", "--format=%H", "--", CRITERION_PATH.as_posix()',
        None,
    ),
    (
        "first_parent_takes_last",
        "src/opticps/benchmarks/e2_score.py",
        "    return commits[0]\n\n\ndef require_freeze_pin",
        "    return commits[-1]\n\n\ndef require_freeze_pin",
        None,
    ),
    (
        "pin_format_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        "    if not isinstance(expected, str) or not _SHA1.fullmatch(expected):",
        "    if False:",
        None,
    ),
    (
        "pin_comparison_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "    if frozen.commit != expected:",
        "    if False:",
        None,
    ),
    (
        "pin_first_parent_comparison_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "    if first_parent_freeze(root) != frozen.commit:",
        "    if False:",
        None,
    ),
    (
        "pin_not_checked",
        "src/opticps/benchmarks/e2_score.py",
        "    require_freeze_pin(root, frozen, expected_freeze_commit)\n",
        "",
        None,
    ),
    (
        "loaded_code_not_verified",
        "src/opticps/benchmarks/e2_score.py",
        "    verify_loaded_code(root)\n",
        "",
        None,
    ),
    (
        "selected_rename_allowed",
        "src/opticps/benchmarks/e2_score.py",
        '    if f"A\\t{relative}" not in status.splitlines():',
        "    if False:",
        None,
    ),
    (
        "selected_stage_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if chosen["selected_at_stage"] != "2km":',
        "    if False:",
        None,
    ),
    (
        "selected_rule_unchecked",
        "src/opticps/benchmarks/e2_score.py",
        '    if chosen["rule"] not in ("single", "all_survivors"):',
        "    if False:",
        None,
    ),
    (
        "selected_ids_not_listed_allowed",
        "src/opticps/benchmarks/e2_score.py",
        "    if not set(ids) <= set(order):",
        "    if False:",
        None,
    ),
    (
        "selected_single_with_many_allowed",
        "src/opticps/benchmarks/e2_score.py",
        '    if (chosen["rule"] == "single") != (len(ids) == 1):',
        "    if False:",
        None,
    ),
    (
        "selected_full_history_dropped",
        "src/opticps/benchmarks/e2_score.py",
        'log = _git_ok(root, "log", "--full-history", "--format=%H", "--", relative)',
        'log = _git_ok(root, "log", "--format=%H", "--", relative)',
        None,
    ),
    (
        "holdout_hashed_before_reproduction",
        "src/opticps/benchmarks/e2_score.py",
        "    summaries = prediction_summaries(model, scenarios, (2.0, 10.0))\n",
        "    verify_local_asset(holdout_path, None)\n    summaries = prediction_summaries(model, scenarios, (2.0, 10.0))\n",
        None,
    ),
    (
        "holdout_hashed_before_selected_ids",
        "src/opticps/benchmarks/e2_score.py",
        "    carried: list[str] | None = None\n",
        "    verify_local_asset(holdout_path, None)\n    carried: list[str] | None = None\n",
        None,
    ),
    (
        "length_of_10km_is_2km",
        "src/opticps/benchmarks/e2_score.py",
        '"50G_PAM4_PD1_10km_Subassembly1.bin": 10.0,',
        '"50G_PAM4_PD1_10km_Subassembly1.bin": 2.0,',
        None,
    ),
    (
        "b2b_header_not_blocked",
        "src/opticps/benchmarks/e2_score.py",
        '    comparator, _ = _read_window(b2b_path, gate.checksum, model, "B2B")\n    if isinstance(comparator, str):\n',
        '    comparator, _ = _read_window(b2b_path, gate.checksum, model, "B2B")\n    if False:\n',
        "defensive: a B2B header that differs from the model would fail the reproduction check",
    ),
    (
        "carry_strict_within",
        "src/opticps/benchmarks/e2_score.py",
        'if v["psi"] <= 1.0\n',
        'if v["psi"] < 1.0\n',
        None,
    ),
    (
        "bind_skips_model",
        "src/opticps/benchmarks/e2_score.py",
        "        MODEL_PATH,\n        SCENARIO_PATH,\n        PREREGISTRATION_PATH,",
        "        SCENARIO_PATH,\n        PREREGISTRATION_PATH,",
        None,
    ),
    (
        "bind_skips_scenarios",
        "src/opticps/benchmarks/e2_score.py",
        "        SCENARIO_PATH,\n        PREREGISTRATION_PATH,",
        "        PREREGISTRATION_PATH,",
        "redundant: the bound registration carries the scenario-list hash, so a replaced list is caught on the registration first",
    ),
    (
        "bind_skips_registration",
        "src/opticps/benchmarks/e2_score.py",
        "        PREREGISTRATION_PATH,\n        POWER_STUDY_PATH,",
        "        POWER_STUDY_PATH,",
        None,
    ),
    (
        "bind_skips_script",
        "src/opticps/benchmarks/e2_score.py",
        "        POWER_STUDY_PATH,\n        EVALUATION_SCRIPT,\n        teriphic.CONFIG_PATH,",
        "        POWER_STUDY_PATH,\n        teriphic.CONFIG_PATH,",
        None,
    ),
    (
        "bind_skips_power_study",
        "src/opticps/benchmarks/e2_score.py",
        "        POWER_STUDY_PATH,\n        EVALUATION_SCRIPT,\n        teriphic.CONFIG_PATH,",
        "        EVALUATION_SCRIPT,\n        teriphic.CONFIG_PATH,",
        None,
    ),
    (
        "bind_skips_config",
        "src/opticps/benchmarks/e2_score.py",
        "        EVALUATION_SCRIPT,\n        teriphic.CONFIG_PATH,\n    )",
        "        EVALUATION_SCRIPT,\n    )",
        None,
    ),
    (
        "locked_fail_is_failed",
        "src/opticps/benchmarks/e2_score.py",
        "        verdict = Verdict.FAILED if split is Split.VALIDATION else Verdict.INCONCLUSIVE",
        "        verdict = Verdict.FAILED",
        None,
    ),
    (
        "locked_fail_is_inconclusive_at_2km_too",
        "src/opticps/benchmarks/e2_score.py",
        "        verdict = Verdict.FAILED if split is Split.VALIDATION else Verdict.INCONCLUSIVE",
        "        verdict = Verdict.INCONCLUSIVE",
        None,
    ),
    (
        "locked_fail_claim_missing",
        "src/opticps/benchmarks/e2_score.py",
        "            claim = CLAIM_NO_SCENARIO_FITS\n",
        "            claim = None\n",
        None,
    ),
    (
        "locked_fail_split_test_dropped",
        "src/opticps/benchmarks/e2_score.py",
        "        if split is Split.LOCKED_TEST:\n            claim = CLAIM_NO_SCENARIO_FITS",
        "        if True:\n            claim = CLAIM_NO_SCENARIO_FITS",
        None,
    ),
    (
        "judged_includes_uncarried_control",
        SC,
        "    judged = [i for i in table if split is Split.VALIDATION or i in set(carried or ())]",
        "    judged = list(table)",
        None,
    ),
    (
        "stage_failed_accepted_at_10km",
        HO,
        "    if asset.split is Split.LOCKED_TEST and validation_stage is not ValidationStage.NOT_FAILED:",
        "    if asset.split is Split.LOCKED_TEST and validation_stage not in (ValidationStage.NOT_FAILED, ValidationStage.FAILED):",
        None,
    ),
    (
        "stage_undeclared_accepted_at_10km",
        HO,
        "    if asset.split is Split.LOCKED_TEST and validation_stage is not ValidationStage.NOT_FAILED:",
        "    if asset.split is Split.LOCKED_TEST and validation_stage is ValidationStage.FAILED:",
        None,
    ),
    (
        "shared_does_not_force_exploratory",
        HO,
        "        if state is HoldoutState.BURNED or sequence_check is SequenceCheck.SHARED:",
        "        if state is HoldoutState.BURNED:",
        None,
    ),
    (
        "shared_does_not_force_exploratory_at_2km",
        HO,
        "        if sequence_check is SequenceCheck.SHARED:\n            return frozenset({Verdict.EXPLORATORY, Verdict.BLOCKED})\n        return open_verdicts",
        "        return open_verdicts",
        None,
    ),
    (
        "record_hash_not_checked",
        SC,
        '    if chosen["two_km_result_sha256"] != digest:',
        "    if False:",
        None,
    ),
    (
        "carry_forward_not_compared",
        SC,
        '    if record.get("carry_forward") != ids:',
        "    if False:",
        None,
    ),
    (
        "carry_rule_not_recomputed_from_record",
        SC,
        "    if carry_rule(psi_table) != tuple(ids):",
        "    if False:",
        None,
    ),
    (
        "record_outcome_fail_accepted",
        SC,
        '    if record.get("outcome") in (OUTCOME_FAIL, OUTCOME_BLOCKED) or record.get("verdict") in (',
        '    if record.get("outcome") in () and record.get("verdict") in (',
        None,
    ),
    (
        "record_filename_not_checked",
        SC,
        '    if record.get("filename") != _two_km_name():',
        "    if False:",
        None,
    ),
    (
        "selection_and_record_may_differ_in_commit",
        SC,
        "    if selected_at != record_at:",
        "    if False:",
        None,
    ),
    (
        "declarations_not_reported",
        SC,
        '            "declarations": dict(self.declarations),',
        '            "declarations": {},',
        None,
    ),
    (
        "record_split_or_length_not_checked",
        SC,
        '    if record.get("split") != Split.VALIDATION.value or record.get("length_km") != 2.0:',
        "    if False:",
        None,
    ),
    (
        "record_criterion_commit_not_checked",
        SC,
        '    if record.get("criterion_commit") != frozen.commit:',
        "    if False:",
        None,
    ),
    (
        "record_hashes_verified_not_checked",
        SC,
        '    if record.get("hashes_verified") is not True:',
        "    if False:",
        None,
    ),
    (
        "record_limits_not_compared",
        SC,
        "            or not math.isclose(float(value), float(limits[name]), rel_tol=1e-9)",
        "            or False",
        None,
    ),
    (
        "record_version_not_checked",
        SC,
        '    if not isinstance(record, dict) or record.get("report_version") != REPORT_VERSION:',
        "    if not isinstance(record, dict):",
        None,
    ),
    (
        "record_head_not_between",
        SC,
        '        or _git(root, "merge-base", "--is-ancestor", head, selected_at).returncode != 0',
        "        or False",
        None,
    ),
    (
        "record_head_bind_skipped",
        SC,
        "        bind_to_freeze(root, frozen, revision=head)",
        "        pass",
        None,
    ),
    (
        "record_carried_psi_not_checked",
        SC,
        '    if any(psi_table[i]["psi"] > 1.0 for i in ids):',
        "    if False:",
        "redundant: the recomputed carry rule returns only survivors (psi <= 1), so a carried id above 1 fails the carry-rule check first",
    ),
    (
        "summary_drops_the_cap",
        SC,
        '        " INCONCLUSIVE by design."',
        '        " by design."',
        None,
    ),
    (
        "two_km_record_not_reported",
        SC,
        '            "two_km_record": None if self.two_km_record is None else dict(self.two_km_record),',
        '            "two_km_record": None,',
        None,
    ),
    (
        "fitted_value_changed_with_hashes_consistent",
        MODEL_DOC,
        "\nnoise_sigma: 0.24",
        "\nnoise_sigma: 0.25",
        None,
    ),
]


def run(mutant: Mutant | None) -> str:
    """killed, SURVIVED, BROKEN or INVALID; None runs the unmutated copy."""
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for folder in ("configs/benchmarks", "docs/benchmarks"):
            shutil.copytree(ROOT / folder, work / folder)
        (work / "scripts").mkdir()
        for name in ("freeze_teriphic_e2.py", "score_teriphic_e2.py"):
            shutil.copy(ROOT / "scripts" / name, work / "scripts" / name)
        (work / "tests").mkdir()
        for name in ("test_benchmark_e2.py", "test_benchmark_external_capture.py"):
            shutil.copy(ROOT / "tests" / name, work / "tests")
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        if mutant is not None:
            _, name, old, new, _ = mutant
            target = work / name
            text = target.read_text()
            if text.count(old) != 1:
                return f"INVALID ({text.count(old)} matches)"
            before = hashlib.sha256(target.read_bytes()).hexdigest()
            target.write_text(text.replace(old, new))
            after = hashlib.sha256(target.read_bytes()).hexdigest()
            for tied in REHASH.get(name, ()):
                document = work / tied
                tied_text = document.read_text()
                if tied_text.count(before) != 1:
                    return "INVALID (model hash not found once in a tied document)"
                document.write_text(tied_text.replace(before, after))
        git = ["git", "-C", str(work)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        env = {**os.environ, "PYTHONPATH": str(work / "src")}
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-x", "-p", "no:cacheprovider",
             "-k", "not test_real_", "tests/test_benchmark_e2.py"],
            cwd=work, env=env, capture_output=True, text=True,
        )  # fmt: skip
        if mutant is None:
            return "passed" if done.returncode == 0 else "FAILED\n" + done.stdout[-1500:]
        return {0: "SURVIVED", 1: "killed"}.get(done.returncode, "BROKEN")


def check_texts() -> int:
    bad = 0
    for label, name, old, _, _ in MUTANTS:
        count = (ROOT / name).read_text().count(old)
        if count != 1:
            print(f"INVALID ({count} matches) {label}")
            bad += 1
    print(f"{len(MUTANTS)} mutants, {bad} invalid")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument("-k", default="")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check_texts()
    baseline = run(None)
    print(f"{baseline:9} unmutated copy", flush=True)
    if baseline != "passed":
        return 1
    chosen = [m for m in MUTANTS if args.k in m[0]]
    counts: dict[str, int] = {}
    unexpected = 0
    with ThreadPoolExecutor(args.j) as pool:
        for mutant, status in zip(chosen, pool.map(run, chosen), strict=True):
            label, _, _, _, reason = mutant
            shown = status
            if status == "SURVIVED" and reason:
                shown = "harmless"
            print(f"{shown:10} {label}" + (f"  ({reason})" if reason else ""), flush=True)
            key = shown if shown in ("killed", "SURVIVED", "BROKEN", "harmless") else "INVALID"
            counts[key] = counts.get(key, 0) + 1
            if key not in ("killed", "harmless"):
                unexpected += 1
    print(
        f"{len(chosen)} applied: {counts.get('killed', 0)} killed, {counts.get('SURVIVED', 0)}"
        f" survived, {counts.get('harmless', 0)} harmless, {counts.get('BROKEN', 0)} broken, "
        f"{counts.get('INVALID', 0)} invalid"
    )
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
