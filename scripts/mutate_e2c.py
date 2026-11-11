"""Mutation check of the E2c power-study code (design D18).

Each mutant is one or more text replacements in the E2c modules or the study script, applied to a
scratch copy of the files `tests/test_benchmark_e2c.py` needs (a fresh `git init` copy, as in
`mutate_e2.py`). Tests named `test_real_` read the committed history and are deselected. A mutant is
"killed" when a test fails (pytest exit code 1); exit codes of 2 or more are BROKEN, never killed. The
unmutated copy must pass first.

    python scripts/mutate_e2c.py [-j JOBS] [--check]
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
MODEL = "src/opticps/benchmarks/e2c_model.py"
STUDY = "src/opticps/benchmarks/e2c_study.py"
ROUTE = "src/opticps/benchmarks/e2c_calibration.py"
SCRIPT = "scripts/power_study_e2c.py"

Mutant = tuple[str, str, list[tuple[str, str]]]
MUTANTS: list[Mutant] = [
    (
        "law_not_applied",
        MODEL,
        [("    y = spec.law.checked_apply(spec.amplitude * v)\n", "    y = spec.amplitude * v\n")],
    ),
    (
        "controls_omitted",
        STUDY,
        [
            (
                '"outcome": outcome_of(len(law_survivors), len(control_survivors)),',
                '"outcome": outcome_of(len(law_survivors), 0),',
            )
        ],
    ),
    (
        "rule_threshold_relaxed",
        STUDY,
        [("R1_MIN_PASSES = 4  # of 5 windows", "R1_MIN_PASSES = 3  # of 5 windows")],
    ),
    (
        "evaluation_window_used_in_fit",
        SCRIPT,
        [
            (
                'e2_score.window_summary(data["b2b"]["fit"], fs, baud), 1.0, "B2B fit window"',
                'e2_score.window_summary(data["b2b"]["evaluation"], fs, baud), 1.0, "B2B fit window"',
            )
        ],
    ),
    (
        "ten_km_name_not_refused",
        ROUTE,
        [
            ("    if given == teriphic.fold_name(TEN_KM_NAME):", "    if False:"),
            ("    if target == teriphic.fold_name(TEN_KM_NAME):", "    if False:"),
        ],
    ),
    (
        "spread_term_dropped",
        STUDY,
        [
            (
                "return {m: MULTIPLIER * max(float(basis[m]), float(spread[m])) for m in METRICS}",
                "return {m: MULTIPLIER * float(basis[m]) for m in METRICS}",
            )
        ],
    ),
    # amendment A2: one mutant per acceptance check, the nested invariant and the optimum choice
    (
        "a2_ac1_nested_check_dropped",
        MODEL,
        [('            "holds": all(ac1_lines.values()),', '            "holds": True,')],
    ),
    (
        "a2_ac1_identity_base_dropped",
        MODEL,
        [
            (
                '"min(poly_b0, poly_a0) <= identity": nested_min <= obj["identity"] + A2_NESTED_TOL,',
                '"min(poly_b0, poly_a0) <= identity": True,',
            )
        ],
    ),
    (
        "a2_ac1_tanh_identity_dropped",
        MODEL,
        [
            (
                '"tanh <= identity": obj["tanh"] <= obj["identity"] + A2_NESTED_TOL,',
                '"tanh <= identity": True,',
            )
        ],
    ),
    ("a2_ac2_best_of_all_check_dropped", MODEL, [('"holds": obj[p] == lowest}', '"holds": True}')]),
    (
        "a2_optimum_not_the_best_run",
        MODEL,
        [('        if float(record["objective"]) < float(best["objective"]):', "        if True:")],
    ),
    (
        "a2_ac3_stationarity_relaxed",
        MODEL,
        [("A2_STATIONARY_GAIN = 1e-4  # AC3", "A2_STATIONARY_GAIN = 1e-3  # AC3")],
    ),
    (
        "a2_ac4_one_basin_enough",
        MODEL,
        [("A2_BASIN_MIN_STARTS = 2  # AC4", "A2_BASIN_MIN_STARTS = 1  # AC4")],
    ),
    (
        "a2_nested_invariant_dropped",
        MODEL,
        [
            (
                "        if name in objectives and poly > float(objectives[name]) + tol:",
                "        if False:",
            )
        ],
    ),
    (
        "a2_r6_without_invariant",
        SCRIPT,
        [
            (
                '    e2c_model.require_nested({p: float(f["objective"]) for p, f in fits.items()})\n',
                "",
            )
        ],
    ),
    (
        "a2_screen_not_selected_by_objective",
        MODEL,
        [
            (
                '    ranked = sorted(screens, key=lambda r: (float(r["objective"]), int(r["start"])))',
                '    ranked = sorted(screens, key=lambda r: int(r["start"]))',
            )
        ],
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
        shutil.copy(ROOT / SCRIPT, work / SCRIPT)
        (work / "tests").mkdir()
        for name in ("test_benchmark_e2c.py", "test_benchmark_external_capture.py"):
            shutil.copy(ROOT / "tests" / name, work / "tests")
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        if mutant is not None:
            _, name, pairs = mutant
            target = work / name
            text = target.read_text()
            for old, new in pairs:
                if text.count(old) != 1:
                    return f"INVALID ({text.count(old)} matches)"
                text = text.replace(old, new)
            target.write_text(text)
        git = ["git", "-C", str(work)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PYTHONPATH"] = str(work / "src")
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-x", "-p", "no:cacheprovider",
             "-k", "not test_real_", "tests/test_benchmark_e2c.py"],
            cwd=work, env=env, capture_output=True, text=True,
        )  # fmt: skip
        if mutant is None:
            return "passed" if done.returncode == 0 else "FAILED\n" + done.stdout[-1500:]
        return {0: "SURVIVED", 1: "killed"}.get(done.returncode, "BROKEN")


def check_texts() -> int:
    bad = 0
    for label, name, pairs in MUTANTS:
        text = (ROOT / name).read_text()
        for old, _ in pairs:
            if text.count(old) != 1:
                print(f"INVALID ({text.count(old)} matches) {label}")
                bad += 1
    print(f"{len(MUTANTS)} mutants, {bad} invalid")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=3)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check_texts()
    baseline = run(None)
    print(f"{baseline:9} unmutated copy", flush=True)
    if baseline != "passed":
        return 1
    killed = 0
    with ThreadPoolExecutor(args.j) as pool:
        for mutant, status in zip(MUTANTS, pool.map(run, MUTANTS), strict=True):
            print(f"{status:10} {mutant[0]}", flush=True)
            killed += status == "killed"
    print(f"{len(MUTANTS)} applied: {killed} killed, {len(MUTANTS) - killed} not killed")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
