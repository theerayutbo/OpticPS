"""Mutation check of the Gate E1 guards (second review fix round).

Each mutant is one text replacement in `src/opticps`, applied to a scratch copy of the repository
files the E1 test file needs. The copy is a git repository (`git init`, `git add`) so that freeze
related tests do not give false kills, and `data/external` is absent so the tests marked
`real_b2b` skip. The test file runs against the copy; a mutant is "killed" when a test fails
(pytest exit code 1). A mutant that breaks collection (2 or more) is BROKEN, never killed, and the
unmutated copy must pass first. A mutant listed with a reason is an equivalent mutant: it is run,
reported, and not counted against the exit code.

    python scripts/mutate_e1.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a sample of the guards written by hand; it proves nothing about mutants that are not in
it. The first seven labels are the survivors of the second independent review, with the mutation
written here (the review's own texts are not in the repository).
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
EC = "src/opticps/benchmarks/external_capture.py"
TE = "src/opticps/benchmarks/teriphic.py"
CS = "src/opticps/benchmarks/capture_stats.py"
CLI = "src/opticps/cli/main.py"
# (label, file, old, new, reason this mutant is equivalent or None); `old` occurs exactly once.
Mutant = tuple[str, str, str, str, str | None]
MUTANTS: list[Mutant] = [
    # --- survivors of the second review
    ("fullscan_scale_true", EC, "                peak <= SCALE_ABS_MAX,\n", "                True,\n", None),
    ("phys_first_slice_only", EC, "return n, (0, (self.count - n) // 2, self.count - n)", "return n, (0,)", None),
    ("phys_report_only_first", EC, "if not check.passed or index == 0:", "if index == 0:", None),
    ("tone_min_zero", TE, "TONE_MIN_STRENGTH = 0.02", "TONE_MIN_STRENGTH = 0.0", None),
    ("scale_max_1e12", EC, "SCALE_ABS_MAX = 1e6", "SCALE_ABS_MAX = 1e12", None),
    ("h136_const", TE, "points_136 = rest // 4", "points_136 = 40_960_000", None),
    ("native_constant_lines_frequency", CS, '"measured_frequency_hz": k * record_sample_rate_hz + offset_hz,', '"measured_frequency_hz": k * record_sample_rate_hz,', None),
    ("native_constant_lines_multiples", CS, "lines = [k for k in (1, 2) if", "lines = [k for k in (1,) if", None),
    ("native_constant_lines_height", CS, "10.0 * math.log10(float(power[peak]) / floor)", "30.0", None),
    # --- decision 1: CLI gate
    ("cli_gate_call_removed", CLI, "        gate_user_files(args)\n    except BenchmarkError", "        pass\n    except BenchmarkError", None),
    ("cli_gate_never_selects", CLI, "        if how == GATE\n", "        if False\n", None),
    ("cli_gate_ignores_folders", CLI, "    return sorted(p for p in path.rglob(\"*\") if p.is_file()) if path.is_dir() else []", "    return []", None),
    ("cli_gate_ingest_uxr_input_unlisted", CLI, '        "input": GATE,  # read_scope_file decodes the samples', '        "input": "no read: nothing",  # read_scope_file decodes the samples', None),
    ("cli_gate_register_never_found", TE, "        if candidate.is_file():\n            return load_config(candidate)", "        if False:\n            return load_config(candidate)", None),
    ("cli_gate_fallback_sha_removed", TE, "        if checksum.sha256_local == sha:", "        if False:", None),
    ("cli_gate_fallback_name_removed", TE, "    if fold_name(name) in holdout_names or (", "    if False or (", None),
    ("cli_metadata_gate_removed", CLI, "        teriphic.gate_sample_read(args.metadata, source)  # a holdout is refused before read_text\n", "", None),
    ("cli_gate_validate_output_skip", CLI, "        and not (args.command == \"validate\" and dest == \"output\" and args.captures)\n", "", "gates one more folder (cost only); no refusal is lost"),
    ("in_external_case_sensitive", TE, "    parts = [fold_name(part) for part in path.resolve().parts]", "    parts = list(path.resolve().parts)", None),
    ("fold_name_no_casefold", TE, 'normalize("NFD", unicodedata.normalize("NFD", name).casefold())', 'normalize("NFD", unicodedata.normalize("NFD", name))', None),
    ("fold_name_no_normalisation", TE, 'unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())', "name.casefold()", None),
    ("name_lookup_case_sensitive", TE, "    asset = by_name.get(fold_name(name))", "    asset = by_name.get(name)", None),
    # --- minors: sidecar
    ("sidecar_dtype_type_unchecked", EC, '        if type(document["dtype"]) is not str:', "        if False:", None),
    ("sidecar_scale_type_unchecked", EC, '        if "scale" in document and type(document["scale"]) is not str:', "        if False:", None),
    ("sidecar_unicode_error_quoted", EC, "        except UnicodeDecodeError:  # its message would quote a byte value of the file\n            raise format_unknown(f\"{path.name}: sidecar is not UTF-8 text\") from None\n", "", None),
    ("sidecar_value_echoed", EC, 'else f"a JSON {type(document).__name__}, not an object"', "else document", None),
    # --- minor 9: upsampling criterion
    ("upsample_ratio_unchecked", TE, "    return ratio >= UPSAMPLE_PERIOD_MIN and excess, detail", "    return excess, detail", None),
    ("upsample_controls_unchecked", TE, "    return ratio >= UPSAMPLE_PERIOD_MIN and excess, detail", "    return ratio >= UPSAMPLE_PERIOD_MIN, detail", None),
    ("upsample_control_multiple_zero", TE, "UPSAMPLE_CONTROL_MULTIPLE = 3.0", "UPSAMPLE_CONTROL_MULTIPLE = 0.0", None),
    ("upsample_period_min_one", TE, "UPSAMPLE_PERIOD_MIN = 1.02", "UPSAMPLE_PERIOD_MIN = 1.0", None),
    ("rate_chain_always_reads", TE, "    if native.get(\"status\") == \"tested\" and not seen:", "    if False:", None),
    # --- decision 2: block pass
    ("inspect_uses_no_coverage", TE, "            coverage.passed,\n            coverage.checks,", "            True,\n            coverage.checks,", None),
    ("block_remainder_not_folded", EC, "        edges.pop()\n", "        pass\n", None),
    ("block_remainder_always_folded", EC, "if len(edges) > 1 and self.count - edges[-1] < MIN_BLOCK_SAMPLES:", "if len(edges) > 1:", None),
    ("block_checked_is_count", EC, "    checked = sum(int(r[\"size\"]) for r in rows)", "    checked = count", None),
    ("block_passed_ignores_coverage", EC, "return self.blocks_failed == 0 and self.samples_checked == self.samples_total", "return self.blocks_failed == 0", None),
    ("block_first_failed_none", EC, "        min(bad_starts) if bad_starts else None,", "        None,", None),
    ("block_finite_removed", EC, '            failed["finite"].append((at, f"{int(r[\'nonfinite\'])} non-finite values"))\n            continue', "            continue", None),
    ("block_scale_absolute_peak", EC, "if r[\"peak\"] > SCALE_ABS_MAX or r[\"std\"] < SCALE_STD_MIN:", "if r[\"peak\"] > SCALE_ABS_MAX:", None),
    ("block_spike_removed", EC, "            if ratio > BLOCK_SPIKE_MAX:", "            if False:", None),
    ("block_spike_limit_huge", EC, "BLOCK_SPIKE_MAX = 8.0", "BLOCK_SPIKE_MAX = 1e9", None),
    ("block_spread_low_removed", EC, "if not BLOCK_SPREAD_MIN <= spread <= BLOCK_SPREAD_MAX:", "if not spread <= BLOCK_SPREAD_MAX:", None),
    ("block_spread_high_removed", EC, "if not BLOCK_SPREAD_MIN <= spread <= BLOCK_SPREAD_MAX:", "if not BLOCK_SPREAD_MIN <= spread:", None),
    ("block_smooth_removed", EC, "        if r[\"lag1\"] < BLOCK_LAG1_MIN:", "        if False:", None),
    ("block_band_removed", EC, "        if r[\"band_db\"] > BLOCK_BAND_DB_MAX:", "        if False:", None),
    ("block_continuous_removed", EC, "        if r[\"jump\"] > BLOCK_JUMP_MAX:", "        if False:", None),
    ("block_clipped_removed", EC, "        if r[\"rail\"] > BLOCK_RAIL_MAX:", "        if False:", None),
    ("block_distinct_removed", EC, "        if r[\"distinct\"] < BLOCK_DISTINCT_MIN:", "        if False:", None),
    ("block_scale_from_max", EC, "scale = float(np.median(sigmas)) if sigmas else 0.0", "scale = float(max(sigmas)) if sigmas else 0.0", None),
    ("block_sigma_unscaled", EC, "sigma=1.4826 * float(np.median(deviation)),", "sigma=float(np.median(deviation)),", None),
    ("block_max_dev_zero", EC, "max_dev=float(deviation.max()),", "max_dev=0.0,", None),
    ("block_row_rail_zero", EC, "rail=float(((x == x.max()).sum() + (x == x.min()).sum()) / x.size),", "rail=0.0,", None),
    ("block_size_minimum_zero", EC, "MIN_BLOCK_SAMPLES = 4096", "MIN_BLOCK_SAMPLES = 16", None),
    ("block_changed_file_unchecked", EC, "        rows: list[dict[str, float]] = []\n        self.assert_unchanged()", "        rows: list[dict[str, float]] = []", None),
]  # fmt: skip


def run(mutant: Mutant | None) -> str:
    """killed, SURVIVED, BROKEN or INVALID; None runs the unmutated copy."""
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for folder in ("configs/benchmarks", "docs/benchmarks"):
            shutil.copytree(ROOT / folder, work / folder)
        (work / "tests").mkdir()
        shutil.copy(ROOT / "tests/test_benchmark_external_capture.py", work / "tests")
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
             "tests/test_benchmark_external_capture.py"],
            cwd=work, env=env, capture_output=True, text=True,
        )  # fmt: skip
        if mutant is None:
            return "passed" if done.returncode == 0 else "FAILED\n" + done.stdout[-1500:]
        return {0: "SURVIVED", 1: "killed"}.get(done.returncode, "BROKEN")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument("-k", default="")
    args = parser.parse_args()
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
                shown = "equivalent"
            print(f"{shown:10} {label}" + (f"  ({reason})" if reason else ""), flush=True)
            key = shown if shown in ("killed", "SURVIVED", "BROKEN", "equivalent") else "INVALID"
            counts[key] = counts.get(key, 0) + 1
            if key not in ("killed", "equivalent"):
                unexpected += 1
    print(
        f"{len(chosen)} applied: {counts.get('killed', 0)} killed, {counts.get('SURVIVED', 0)}"
        f" survived, {counts.get('equivalent', 0)} equivalent, {counts.get('BROKEN', 0)} broken, "
        f"{counts.get('INVALID', 0)} invalid"
    )
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
