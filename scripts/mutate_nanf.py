"""Mutation check of the NANF fibre-profile guards (Gate N2a).

Each mutant is one text replacement in `optical_channel/fiber.py` or `link.py`, applied to a scratch
copy of the files the NANF tests need. The NANF test files run against that copy; a mutant is
"killed" when a test fails (pytest exit code 1). A survivor means a guard has no test that notices
its removal. A mutant that breaks collection (exit code 2 or more) is reported BROKEN, never
killed, and the unmutated copy must pass first. The exit code is 0 only when every listed mutant is
killed.

    python scripts/mutate_nanf.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a hand-written sample of the guards (the 14 gaps of the third N1 review and the N2a
guards). It proves nothing about mutants that are not in it. The label says what the mutant does.
"""

# SPDX-License-Identifier: MIT
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
M = "src/opticps/measurement/nanf_import.py"
F = "src/opticps/optical_channel/fiber.py"
L = "src/opticps/optical_channel/link.py"
TESTS = (
    "tests/test_nanf_profiles.py",
    "tests/test_nanf_propagation.py",
    "tests/test_nanf_n2a.py",
    "tests/test_nanf_import.py",
    "tests/nanf_workbook_fixture.py",
    "tests/test_nanf_benchmark.py",
)
# (label, file, old text, new text); `old` must occur exactly once.
MUTANTS: list[tuple[str, str, str, str]] = [
    # the 14 gaps of the third N1 review (finding 6)
    ("rel tol 1e-2", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-2"),
    ("rel tol 1e-5", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-5"),
    ("rel tol 1e-7", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-7"),
    ("slope abs tol 1e-2", F, "_SLOPE_TOLERANCE_ABS = 1e-3", "_SLOPE_TOLERANCE_ABS = 1e-2"),
    ("slope abs tol 0", F, "_SLOPE_TOLERANCE_ABS = 1e-3", "_SLOPE_TOLERANCE_ABS = 0.0"),
    ("slope rel tol 0.5", F, "_SLOPE_TOLERANCE_REL = 0.1", "_SLOPE_TOLERANCE_REL = 0.5"),
    ("slope rel tol 0", F, "_SLOPE_TOLERANCE_REL = 0.1", "_SLOPE_TOLERANCE_REL = 0.0"),
    (
        "scenario S uses a precedence",
        F,
        "decl = None if slope_from_scenario else profile.precedence.get(name)",
        "decl = profile.precedence.get(name)",
    ),
    ("slope_at left side", F, 'wavelength_nm, side="right"', 'wavelength_nm, side="left"'),
    (
        "slope_at no left clip",
        F,
        'wavelength_nm, side="right"), 1, len(wl) - 1',
        'wavelength_nm, side="right"), 0, len(wl) - 1',
    ),
    (
        "outside-span conflict branch removed",
        F,
        "            if scalar_extrapolated:\n                # the scalar does not hold here",
        "            if False:\n                # the scalar does not hold here",
    ),
    (
        "raw scalar compared before placing D",
        F,
        "if not math.isclose(value, tab, rel_tol=_AGREEMENT_REL_TOL, abs_tol=1e-12):",
        "if not math.isclose(pv.value, tab, rel_tol=_AGREEMENT_REL_TOL, abs_tol=1e-12):",
    ),
    (
        "sentinel: slope None skip removed",
        F,
        "if table is None or slope is None or scalar_d_declared_over_table:",
        "if table is None or scalar_d_declared_over_table:",
    ),
    (
        "laser cap applied to fixed launch",
        L,
        "    result = transmit(normalized, sample_rate, config, rng)\n"
        "    record = resolved.to_record()",
        "    if config.laser_power_w > MAX_MATCHED_LASER_POWER_W:\n"
        '        raise ValueError("cap")\n'
        "    result = transmit(normalized, sample_rate, config, rng)\n"
        "    record = resolved.to_record()",
    ),
    (
        "citation distinct 3",
        F,
        "len(set(compact.casefold())) < 4",
        "len(set(compact.casefold())) < 3",
    ),
    ("citation floor 5", F, "if len(compact) < 6 or", "if len(compact) < 5 or"),
    ("citation floor 7", F, "if len(compact) < 6 or", "if len(compact) < 7 or"),
    (
        "precedence needs no real citation",
        F,
        "        if not is_real_citation(self.provenance.citation):\n"
        '            raise FiberProfileError("a precedence declaration needs a real citation")',
        "        if False:\n"
        '            raise FiberProfileError("a precedence declaration needs a real citation")',
    ),
    (
        "precedence of unknown provenance",
        F,
        "        if self.provenance.category is ProvenanceCategory.UNKNOWN:\n"
        '            raise FiberProfileError("a precedence declaration needs a stated provenance")',
        "        if False:\n"
        '            raise FiberProfileError("a precedence declaration needs a stated provenance")',
    ),
    # N2 importer guards
    ("importer: hash not checked", M, "if digest != expected_sha256:", "if False:"),
    (
        "importer: hidden sheet accepted",
        M,
        'if any(s[2] != "visible" for s in sheets):',
        "if False:",
    ),
    ("importer: DOCTYPE accepted", M, 'b"<!doctype" in lowered or ', "False or "),
    ("importer: zero BER not censored", M, "if value == 0.0:", "if False:"),
    ("importer: censor floor 0", M, "elif value < BER_CENSOR_FLOOR:", "elif value < 0.0:"),
    ("importer: BER above 1 accepted", M, "if not 0.0 <= value <= 1.0:", "if False:"),
    (
        "importer: unordered axis accepted",
        M,
        "if any(b <= a for a, b in zip(axis, axis[1:], strict=False)):",
        "if False:",
    ),
    ("importer: any formula accepted", M, 'cell.formula != "-Inf"', "False"),
    ("importer: Fig.6 B2B read as calibration", M, "b2b_role if link", "_CAL if link"),
    (
        "importer: holdout returned by default",
        M,
        "include_holdout or s.role is not DataRole.HOLDOUT",
        "True",
    ),
    (
        "importer: repr shows values",
        M,
        'f"{self.provenance.value}, {shown})"',
        'f"{self.provenance.value}, {shown}, {self.y})"',
    ),
    ("importer: missing cells accepted", M, "        if missing:", "        if False:"),
    (
        "importer: negative loss accepted",
        M,
        'elif s.quantity in ("link_loss", "capacity", "latency") and value < 0.0:',
        "elif False:",
    ),
    (
        "importer: dimension not checked",
        M,
        'if dim is None or dim.get("ref") != layout.dimension:',
        "if False:",
    ),
    (
        "importer: merged ranges not checked",
        M,
        "if sorted(merges) != sorted(layout.merges):",
        "if False:",
    ),
    (
        "importer: sheet list not checked",
        M,
        "if [s[0] for s in sheets] != list(EXPECTED_SHEETS):",
        "if False:",
    ),
    ("importer: non-finite number accepted", M, "if not math.isfinite(value):", "if False:"),
    # N2a guards
    (
        "declared-over-table flag never set",
        F,
        "                    d_declared_over_table = True\n",
        "                    pass\n",
    ),
    (
        "scenario S placing a scalar D may override a table",
        F,
        '                if name == "dispersion_ps_per_nm_km" and slope_from_scenario:\n'
        "                    raise FiberProfileError(",
        '                if False and name == "dispersion_ps_per_nm_km":\n'
        "                    raise FiberProfileError(",
    ),
    (
        "scenario D with S and no wavelength accepted",
        F,
        "                    if anchor_nm is None:\n"
        "                        raise OutOfValidityRangeError(\n"
        '                            "the scenario D states',
        "                    if False:\n"
        "                        raise OutOfValidityRangeError(\n"
        '                            "the scenario D states',
    ),
    (
        "scenario D not moved by S",
        F,
        "out[name] = values[name] + slope_value * (wavelength_nm - anchor_nm)",
        "out[name] = values[name]",
    ),
    (
        "scenario wavelength without a D accepted",
        F,
        '            if "dispersion_ps_per_nm_km" not in self.values:',
        "            if False:",
    ),
    (
        "measurement wavelength outside own range accepted",
        F,
        "if wl is not None and not low - tol <= wl <= high + tol:",
        "if False:",
    ),
    (
        "measurement wavelength range edge refused",
        F,
        "if wl is not None and not low - tol <= wl <= high + tol:",
        "if wl is not None and not low < wl < high:",
    ),
    (
        "base label dropped from the link record",
        L,
        '        record["sensitivity_scenario"] = config.sensitivity_scenario\n'
        '        record["not_a_benchmark_result"] = True\n',
        "        pass\n",
    ),
    (
        "ZeroDivisionError at extreme loss",
        L,
        "laser_w = target_w / transmission if transmission > 0 else math.inf",
        "laser_w = target_w / transmission",
    ),
]


def run(mutant: tuple[str, str, str, str] | None) -> str:
    """killed, SURVIVED, BROKEN or INVALID; None runs the unmutated copy."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for folder in ("configs", "docs", "reports"):
            shutil.copytree(ROOT / folder, work / folder, ignore=shutil.ignore_patterns("*.pyc"))
        (work / "tests").mkdir()
        shutil.copy(ROOT / "tests/nanf_profile_helpers.py", work / "tests")
        for test in TESTS:
            shutil.copy(ROOT / test, work / "tests")
        if mutant is not None:
            _, rel, old, new = mutant
            path = work / rel
            text = path.read_text()
            if text.count(old) != 1:
                return "INVALID"
            path.write_text(text.replace(old, new))
        git = ["git", "-C", str(work)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        env = {**os.environ, "PYTHONPATH": str(work / "src")}
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=-rN",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
                "tests",
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )
    if done.returncode == 0:
        return "ok" if mutant is None else "SURVIVED"
    return "killed" if done.returncode == 1 else "BROKEN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument("-k", default="")
    args = parser.parse_args()
    baseline = run(None)
    print(f"{baseline:9} unmutated copy", flush=True)
    if baseline != "ok":
        return 2
    chosen = [m for m in MUTANTS if args.k in m[0]]
    with ThreadPoolExecutor(max_workers=args.j) as pool:
        outcomes = list(pool.map(run, chosen))
    for (label, rel, _, _), outcome in zip(chosen, outcomes, strict=True):
        print(f"{outcome:9} {Path(rel).name}: {label}", flush=True)
    bad = [o for o in outcomes if o != "killed"]
    print(f"{len(chosen) - len(bad)} of {len(chosen)} killed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
