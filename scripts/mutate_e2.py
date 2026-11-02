"""Mutation check of the Gate E2 part a code (estimators, surrogate, scorer entry point).

Each mutant is one text replacement in `src/opticps/benchmarks/e2_*.py`, applied to a scratch copy
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
# (label, file, old, new, reason a surviving mutant is harmless, or None); `old` occurs exactly once.
Mutant = tuple[str, str, str, str, str | None]
MUTANTS: list[Mutant] = [
    # --- estimators (e2_metrics)
    ("km_tolerance_loose", EM, "KMEANS_TOLERANCE = 1e-9", "KMEANS_TOLERANCE = 1e-1", None),
    ("km_one_iteration", EM, "KMEANS_MAX_ITERATIONS = 200", "KMEANS_MAX_ITERATIONS = 1", None),
    ("km_empty_cluster_allowed", EM, "        if (counts <= 0).any():", "        if False:", None),
    ("km_flat_window_allowed", EM, "    if not spread > 0.0:", "    if False:", None),
    (
        "gaps_order_unchecked",
        EM,
        "    if gaps.shape != (3,) or not (gaps > 0).all():",
        "    if gaps.shape != (3,):",
        None,
    ),
    (
        "m1_sum_not_max",
        EM,
        "return float(np.max(np.abs(np.asarray(gaps_m) - np.asarray(gaps_p))))",
        "return float(np.sum(np.abs(np.asarray(gaps_m) - np.asarray(gaps_p))))",
        None,
    ),
    (
        "quantile_lower_index_only",
        EM,
        "ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower])",
        "ordered[lower]",
        None,
    ),
    (
        "quantile_h_uses_n",
        EM,
        "    h = (ordered.size - 1) * p\n",
        "    h = ordered.size * p\n    h = np.minimum(h, ordered.size - 1)\n",
        None,
    ),
    (
        "quantile_range_unchecked",
        EM,
        "    if not ((p >= 0.0).all() and (p <= 1.0).all()):",
        "    if False:",
        None,
    ),
    (
        "m2_probabilities_no_half",
        EM,
        "    return (np.arange(W1_POINTS, dtype=np.float64) + 0.5) / W1_POINTS",
        "    return np.arange(W1_POINTS, dtype=np.float64) / (W1_POINTS - 1)",
        None,
    ),
    ("m2_points_1024", EM, "W1_POINTS = 65536", "W1_POINTS = 1024", None),
    (
        "m2_max_not_mean",
        EM,
        "np.mean(np.abs(measured.quantile_u - predicted.quantile_u))",
        "np.max(np.abs(measured.quantile_u - predicted.quantile_u))",
        None,
    ),
    (
        "m2_standalone_max",
        EM,
        "    return float(np.mean(np.abs(q_m - q_p)))",
        "    return float(np.max(np.abs(q_m - q_p)))",
        None,
    ),
    (
        "m3_drops_99_point",
        EM,
        "QUANTILE_POINTS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)",
        "QUANTILE_POINTS = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95)",
        None,
    ),
    (
        "m3_mean_not_max",
        EM,
        "float(np.max(np.abs(measured.quantile_p - predicted.quantile_p)))",
        "float(np.mean(np.abs(measured.quantile_p - predicted.quantile_p)))",
        None,
    ),
    (
        "m3_standalone_mean",
        EM,
        "    return float(np.max(np.abs(q_m - q_p)))",
        "    return float(np.mean(np.abs(q_m - q_p)))",
        None,
    ),
    (
        "m4_band_twice_baud",
        EM,
        "mask: NDArray[np.bool_] = frequency <= baud_bd * (1.0 + 1e-9)",
        "mask: NDArray[np.bool_] = frequency <= 2.0 * baud_bd",
        None,
    ),
    (
        "m4_band_excludes_baud",
        EM,
        "mask: NDArray[np.bool_] = frequency <= baud_bd * (1.0 + 1e-9)",
        "mask: NDArray[np.bool_] = frequency < baud_bd * (1.0 - 1e-9)",
        None,
    ),
    (
        "m4_factor_20",
        EM,
        "ratio_db = 10.0 * np.log10(p_m / p_p)",
        "ratio_db = 20.0 * np.log10(p_m / p_p)",
        None,
    ),
    (
        "m4_mean_abs_not_rms",
        EM,
        "value = float(np.sqrt(np.mean(ratio_db**2)))",
        "value = float(np.mean(np.abs(ratio_db)))",
        None,
    ),
    (
        "m4_positive_unchecked",
        EM,
        "if p_m.shape != p_p.shape or not ((p_m > 0).all() and (p_p > 0).all()):",
        "if p_m.shape != p_p.shape:",
        None,
    ),
    ("m4_min_bins_unchecked", EM, "    if int(mask.sum()) < 8:", "    if False:", None),
    ("welch_overlap_1024", EM, "WELCH_OVERLAP = 2048", "WELCH_OVERLAP = 1024", None),
    ("welch_no_detrend", EM, 'detrend="constant",', "detrend=False,", None),
    ("welch_rectangular_window", EM, 'window="hann",', 'window="boxcar",', None),
    ("welch_segment_2048", EM, "WELCH_SEGMENT = 4096", "WELCH_SEGMENT = 2048", None),
    ("window_nonfinite_allowed", EM, "    if not np.isfinite(array).all():", "    if False:", None),
    ("window_minimum_ignored", EM, "    if array.size < minimum:", "    if False:", None),
    ("window_ndim_ignored", EM, "    if array.ndim != 1:", "    if False:", None),
    ("normalise_scale_unchecked", EM, "or g0 <= 0:", "or False:", None),
    (
        "normalise_multiplies",
        EM,
        "return (np.asarray(x, dtype=np.float64) - c0) / g0",
        "return (np.asarray(x, dtype=np.float64) - c0) * g0",
        None,
    ),
    (
        "summary_density_unbanded",
        EM,
        "        density[band_bins(frequency, baud_bd)],",
        "        density,",
        None,
    ),
    # --- surrogate (e2_model)
    (
        "dispersion_linear_in_f",
        MO,
        "* frequency_hz**2 / SPEED_OF_LIGHT_M_S",
        "* frequency_hz / SPEED_OF_LIGHT_M_S",
        None,
    ),
    (
        "dispersion_wavelength_1550",
        MO,
        "NOMINAL_WAVELENGTH_NM = 1310.0",
        "NOMINAL_WAVELENGTH_NM = 1550.0",
        None,
    ),
    ("dispersion_negative_length_allowed", MO, "    if length_km < 0:", "    if False:", None),
    (
        "dispersion_nonfinite_allowed",
        MO,
        "        if not math.isfinite(value):",
        "        if False:",
        None,
    ),
    (
        "dispersion_unit_wrong",
        MO,
        "d_si = dispersion_ps_nm_km * 1e-6",
        "d_si = dispersion_ps_nm_km * 1e-3",
        None,
    ),
    (
        "loss_20_not_10",
        MO,
        "10.0 ** (-attenuation_db_per_km * length_km / 10.0)",
        "10.0 ** (-attenuation_db_per_km * length_km / 20.0)",
        None,
    ),
    (
        "loss_negative_attenuation_allowed",
        MO,
        "math.isfinite(attenuation_db_per_km) and attenuation_db_per_km >= 0",
        "math.isfinite(attenuation_db_per_km)",
        None,
    ),
    (
        "ratio_tolerance_ignored",
        MO,
        "if abs(float(fraction) - value) > 1e-9 * value or fraction < 4:",
        "if fraction < 4:",
        None,
    ),
    (
        "ratio_minimum_ignored",
        MO,
        "if abs(float(fraction) - value) > 1e-9 * value or fraction < 4:",
        "if abs(float(fraction) - value) > 1e-9 * value:",
        None,
    ),
    (
        "pulse_unnormalised",
        MO,
        "    return build(response) / scale",
        "    return build(response)",
        None,
    ),
    (
        "pulse_odd_allowed",
        MO,
        "if pulse_samples < 64 or pulse_samples % 2:",
        "if pulse_samples < 64:",
        None,
    ),
    (
        "pulse_dispersion_ignored",
        MO,
        "    return build(response) / scale",
        "    return build(np.ones_like(magnitude)) / scale",
        None,
    ),
    (
        "fractional_delay_wrong_sign",
        MO,
        "phase = np.exp(-2j * np.pi * np.fft.rfftfreq(n) * fraction)",
        "phase = np.exp(2j * np.pi * np.fft.rfftfreq(n) * fraction)",
        None,
    ),
    (
        "noise_spread_unscaled",
        MO,
        "np.asarray(noise * (sigma / spread), dtype=np.float64)",
        "np.asarray(noise, dtype=np.float64)",
        None,
    ),
    (
        "noise_negative_sigma_allowed",
        MO,
        "if not (math.isfinite(sigma) and sigma >= 0):",
        "if not math.isfinite(sigma):",
        None,
    ),
    (
        "noise_shape_flat",
        MO,
        "    shape = np.interp(freq, grid, magnitude)",
        "    shape = np.ones_like(freq)",
        None,
    ),
    (
        "synth_fraction_denominator",
        MO,
        "shifted = fractional_pulse(base, fraction / classes)",
        "shifted = fractional_pulse(base, fraction / (classes + 1))",
        None,
    ),
    (
        "synth_amplitude_ratio_unused",
        MO,
        "out = amplitude_ratio * crop + (",
        "out = crop + (",
        None,
    ),
    (
        "synth_noise_ignores_signal_flag",
        MO,
        "(amplitude_ratio * noise if noise_follows_signal else noise)",
        "noise",
        None,
    ),
    (
        "synth_noise_always_follows",
        MO,
        "(amplitude_ratio * noise if noise_follows_signal else noise)",
        "(amplitude_ratio * noise)",
        None,
    ),
    ("synth_probabilities_unchecked", MO, "if (probabilities < 0).any():", "if False:", None),
    (
        "synth_short_window_allowed",
        MO,
        "if type(n_samples) is not int or n_samples < 1024:",
        "if type(n_samples) is not int:",
        None,
    ),
    (
        "synth_dispersion_ignored",
        MO,
        "        dispersion_ps_nm_km=dispersion_ps_nm_km,\n        length_km=length_km,\n        pulse_samples=pulse_length,",
        "        dispersion_ps_nm_km=0.0,\n        length_km=length_km,\n        pulse_samples=pulse_length,",
        None,
    ),
    (
        "fit_uniform_probabilities_changed",
        MO,
        '"level_probabilities": [0.25, 0.25, 0.25, 0.25],',
        '"level_probabilities": [0.4, 0.2, 0.2, 0.2],',
        None,
    ),
    (
        "fit_level_update_wrong_sign",
        MO,
        "levels = levels + (target_centroids - kmeans_levels(y)[0])",
        "levels = levels - (target_centroids - kmeans_levels(y)[0])",
        None,
    ),
    # --- scorer (e2_score)
    (
        "scenario_null_count_unchecked",
        SC,
        "    if sum(s.null_control for s in scenarios) != 1:",
        "    if False:",
        None,
    ),
    (
        "scenario_duplicate_allowed",
        SC,
        "        if identifier in {s.scenario_id for s in scenarios}:",
        "        if False:",
        None,
    ),
    (
        "scenario_count_unchecked",
        SC,
        '    if body["count"] != len(entries) or type(body["count"]) is not int:',
        "    if False:",
        None,
    ),
    (
        "scenario_flag_untyped",
        SC,
        "            if type(entry[flag]) is not bool:",
        "            if False:",
        None,
    ),
    (
        "model_nonfinite_list_allowed",
        SC,
        "            if not math.isfinite(float(item)):",
        "            if False:",
        None,
    ),
    (
        "identity_check_skipped",
        SC,
        "    changed = sorted(p for p in actual if actual[p] != recorded[p])",
        "    changed = []",
        None,
    ),
    (
        "identity_symlink_allowed",
        SC,
        "        if path.is_symlink() or not path.is_file():",
        "        if not path.is_file():",
        None,
    ),
    ("exceedance_min_not_max", SC, "    return max(ratios)", "    return min(ratios)", None),
    (
        "exceedance_nan_allowed",
        SC,
        "        if not math.isfinite(value) or value < 0:",
        "        if False:",
        None,
    ),
    (
        "select_worst_not_best",
        SC,
        'selected = min(table, key=lambda key: (table[key]["psi"], list(table).index(key)))',
        'selected = max(table, key=lambda key: (table[key]["psi"], -list(table).index(key)))',
        None,
    ),
    (
        "select_ties_to_later",
        SC,
        'selected = min(table, key=lambda key: (table[key]["psi"], list(table).index(key)))',
        'selected = min(table, key=lambda key: (table[key]["psi"], -list(table).index(key)))',
        "unpinned: no fixture produces an exact tie of two psi values",
    ),
    ("model_always_ok", SC, 'model_ok = bool(chosen_entry["psi"] <= 1.0)', "model_ok = True", None),
    ("copy_always_ok", SC, "copy_ok = bool(copy_psi <= 1.0)", "copy_ok = True", None),
    ("copy_never_ok", SC, "copy_ok = bool(copy_psi <= 1.0)", "copy_ok = False", None),
    (
        "null_control_rule_dropped",
        SC,
        '    elif copy_ok or chosen_entry["null_control"] or table[null_id]["psi"] <= 1.0:',
        '    elif copy_ok or table[null_id]["psi"] <= 1.0:',
        "equivalent: a chosen control inside the limits already implies the control psi is at most 1",
    ),
    (
        "null_also_passes_rule_dropped",
        SC,
        '    elif copy_ok or chosen_entry["null_control"] or table[null_id]["psi"] <= 1.0:',
        '    elif copy_ok or chosen_entry["null_control"]:',
        None,
    ),
    (
        "copy_rule_dropped",
        SC,
        '    elif copy_ok or chosen_entry["null_control"] or table[null_id]["psi"] <= 1.0:',
        '    elif chosen_entry["null_control"] or table[null_id]["psi"] <= 1.0:',
        None,
    ),
    (
        "fail_verdict_inconclusive",
        SC,
        "        verdict = Verdict.FAILED",
        "        verdict = Verdict.INCONCLUSIVE",
        None,
    ),
    (
        "validation_stage_verdict_set",
        SC,
        "        verdict = None  # plan R.5: within criterion at the selection stage, no verdict",
        "        verdict = Verdict.VALIDATED",
        None,
    ),
    (
        "validated_without_permission",
        SC,
        "verdict = Verdict.VALIDATED if Verdict.VALIDATED in allowed else Verdict.INCONCLUSIVE",
        "verdict = Verdict.VALIDATED",
        "equivalent: the later clamp to allowed_verdicts returns the same verdict",
    ),
    (
        "unidentifiable_swapped",
        SC,
        "Verdict.INCONCLUSIVE if identifiable_in_principle else Verdict.UNIDENTIFIABLE_PARAMETER",
        "Verdict.UNIDENTIFIABLE_PARAMETER if identifiable_in_principle else Verdict.INCONCLUSIVE",
        None,
    ),
    (
        "verdict_not_clamped_to_allowed",
        SC,
        "    if verdict is not None and verdict not in allowed:",
        "    if False:",
        "defensive: allowed_verdicts always contains the verdicts this function assigns",
    ),
    (
        "control_not_scored_in_locked_test",
        SC,
        "        scored = (*chosen, *controls)  # the no-fibre control is scored too, as a reference",
        "        scored = tuple(chosen)",
        None,
    ),
    (
        "locked_test_without_scenario_allowed",
        SC,
        '        if fixed_scenario is None:\n            raise BenchmarkError("the locked test needs the scenario chosen at the 2 km stage")',
        "        if fixed_scenario is None:\n            fixed_scenario = scenarios[0].scenario_id",
        None,
    ),
    (
        "two_km_may_fix_a_scenario",
        SC,
        '        if fixed_scenario is not None:\n            raise BenchmarkError("the 2 km stage selects its own scenario; none may be fixed")',
        "        if fixed_scenario is not None:\n            pass",
        None,
    ),
    (
        "role_unchecked",
        SC,
        '    if split not in HOLDOUT_SPLITS:\n        raise BenchmarkError(f"{split.value} is not a holdout role")',
        '    if False:\n        raise BenchmarkError(f"{split.value} is not a holdout role")',
        None,
    ),
    (
        "window_size_unchecked",
        SC,
        "    if measured.size != n_samples or comparator.size != n_samples:",
        "    if False:",
        None,
    ),
    (
        "limit_positivity_unchecked",
        SC,
        '        _positive(limits[name], f"limit {name}")',
        "        pass",
        None,
    ),
    ("limit_keys_unchecked", SC, "    if set(limits) != set(METRICS):", "    if False:", None),
    (
        "separable_ignores_control",
        SC,
        '"separable": bool(psi > 1.0) and not scenario.null_control,',
        '"separable": bool(psi > 1.0),',
        None,
    ),
    (
        "separable_never",
        SC,
        '"separable": bool(psi > 1.0) and not scenario.null_control,',
        '"separable": False,',
        None,
    ),
    (
        "reproduction_tolerance_loose",
        SC,
        "REPRODUCTION_RTOL = 1e-6",
        "REPRODUCTION_RTOL = 1e-1",
        None,
    ),
    ("reproduction_keys_unchecked", SC, "    if set(a) != set(b):", "    if False:", None),
    (
        "reproduction_flag_flip_allowed",
        SC,
        "            if x is not y:",
        "            if False:",
        None,
    ),
    (
        "registered_limits_loose",
        SC,
        "if not math.isclose(float(recorded[name]), limits[name], rel_tol=1e-9):",
        "if not math.isclose(float(recorded[name]), limits[name], rel_tol=1.0):",
        None,
    ),
    (
        "registered_count_unchecked",
        SC,
        '    if len(scenarios) != int(registration.get("scenario_count", -1)):',
        "    if False:",
        None,
    ),
    (
        "holdout_role_unchecked",
        SC,
        "asset.split in HOLDOUT_SPLITS:\n            return asset",
        "True:\n            return asset",
        None,
    ),
    (
        "length_of_2km_wrong",
        SC,
        '"50G_PAM4_PD1_2km_Subassembly1.bin": 2.0,',
        '"50G_PAM4_PD1_2km_Subassembly1.bin": 3.0,',
        None,
    ),
    (
        "guard_after_a_hash",
        SC,
        "    asset = _holdout_asset(holdout_path, source)\n",
        "    asset = _holdout_asset(holdout_path, source)\n    verify_local_asset(holdout_path, None)\n",
        None,
    ),
    (
        "guard_after_b2b_gate",
        SC,
        "    asset = _holdout_asset(holdout_path, source)\n",
        "    asset = _holdout_asset(holdout_path, source)\n    teriphic.gate_sample_read(b2b_path, source)\n",
        None,
    ),
    ("guard_inputs_empty", SC, "        inputs=_inputs(asset, root),", "        inputs={},", None),
    (
        "guard_stage_dropped",
        SC,
        "        validation_stage=validation_stage,\n    )\n    if frozen is None:",
        "    )\n    if frozen is None:",
        None,
    ),
    (
        "model_hash_not_compared",
        SC,
        "    if sha256_of(model_bytes) != frozen.inputs[model_key]:",
        "    if False:",
        "covered: bind_to_freeze compares the same bytes with the freeze commit first",
    ),
    (
        "scenario_hash_not_compared",
        SC,
        '        and sha256_of(scenario_bytes) != frozen.inputs["scenario_list"]',
        "        and False",
        "covered: bind_to_freeze compares the same bytes with the freeze commit first",
    ),
    (
        "registration_untied_model",
        SC,
        '        or registration.get("model_sha256") != sha256_of(model_bytes)\n',
        "",
        None,
    ),
    (
        "registration_untied_scenarios",
        SC,
        '        or registration.get("scenario_list_sha256") != sha256_of(scenario_bytes)\n',
        "",
        None,
    ),
    (
        "registration_result_allowed",
        SC,
        '    if registration.get("results") is not None:',
        "    if False:",
        None,
    ),
    (
        "identity_not_verified",
        SC,
        "    verify_code_identity(model, root)\n    limits = {name",
        "    limits = {name",
        None,
    ),
    (
        "md5_not_required",
        SC,
        "if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:",
        "if checksum.sha256_local != expected_sha:",
        None,
    ),
    (
        "sha_not_required",
        SC,
        "if checksum.md5_state is not Md5State.VERIFIED or checksum.sha256_local != expected_sha:",
        "if checksum.md5_state is not Md5State.VERIFIED:",
        None,
    ),
    ("sha_missing_allowed", SC, "    if expected_sha is None:", "    if False:", None),
    ("b2b_md5_not_required", SC, "    if not gate.is_b2b:", "    if False:", None),
    ("sample_rate_tolerance_loose", SC, "SAMPLE_RATE_RTOL = 1e-6", "SAMPLE_RATE_RTOL = 1.0", None),
    (
        "short_record_not_blocked",
        SC,
        "            if capture.count < start + count:",
        "            if False:",
        None,
    ),
    (
        "increment_missing_not_blocked",
        SC,
        "            if increment is None or not math.isclose(",
        "            if not math.isclose(",
        "defensive: the header parse refuses a missing or implausible time increment before this check",
    ),
    # --- binding to the freeze commit (review finding)
    ("bind_call_removed", SC, "    bind_to_freeze(root, frozen)\n", "", None),
    (
        "bind_ancestor_unchecked",
        SC,
        '    if _git(root, "merge-base", "--is-ancestor", frozen.commit, "HEAD").returncode != 0:',
        "    if False:",
        "defensive: the guard already follows the history of the freeze commit from HEAD",
    ),
    ("bind_missing_at_freeze_allowed", SC, "        if then is None:", "        if False:", None),
    ("bind_change_allowed", SC, "        if then != now:", "        if False:", None),
    (
        "bind_skips_registration",
        SC,
        "    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        "    paths = (MODEL_PATH, SCENARIO_PATH, EVALUATION_SCRIPT)",
        None,
    ),
    (
        "bind_skips_model",
        SC,
        "    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        "    paths = (SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        None,
    ),
    (
        "bind_skips_scenarios",
        SC,
        "    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        "    paths = (MODEL_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        None,
    ),
    (
        "bind_skips_script",
        SC,
        "    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH, EVALUATION_SCRIPT)",
        "    paths = (MODEL_PATH, SCENARIO_PATH, PREREGISTRATION_PATH)",
        None,
    ),
    (
        "bind_skips_code",
        SC,
        "    for relative in (*paths, *map(Path, CODE_IDENTITY_FILES)):",
        "    for relative in paths:",
        None,
    ),
    (
        "selected_present_at_freeze_allowed",
        SC,
        "    if _blob(root, frozen.commit, relative) is not None:",
        "    if False:",
        None,
    ),
    (
        "selected_many_commits_allowed",
        SC,
        "    if len(commits) != 1:",
        "    if len(commits) < 1:",
        None,
    ),
    (
        "selected_not_after_freeze_allowed",
        SC,
        "        added == frozen.commit\n        or _git(",
        "        False\n        and _git(",
        "defensive: a side-branch addition shows up as a second log entry first (found 2)",
    ),
    (
        "selected_change_allowed",
        SC,
        "    if _blob(root, added, relative) != now:",
        "    if False:",
        "defensive: a changed file is a second log entry first (found 2)",
    ),
    (
        "selected_id_type_unchecked",
        SC,
        '    if not isinstance(chosen["scenario_id"], str):',
        "    if False:",
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
            target.write_text(text.replace(old, new))
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
