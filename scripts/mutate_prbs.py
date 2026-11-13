"""Mutation check of the B2B pattern-search code (`prbs_search.py`).

Each mutant is one or more text replacements in the module, applied to a scratch copy of what
`tests/test_benchmark_prbs_search.py` needs. A mutant is "killed" when a test fails (pytest exit code
1); exit codes of 2 or more are BROKEN, never killed. The unmutated copy must pass first.

    python scripts/mutate_prbs.py [-j JOBS] [--check]
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
MODULE = "src/opticps/benchmarks/prbs_search.py"
SCRIPT = "scripts/prbs_search_b2b.py"
TEST = "tests/test_benchmark_prbs_search.py"

Mutant = tuple[str, str, list[tuple[str, str]]]
MUTANTS: list[Mutant] = [
    (
        "ten_km_name_not_refused",
        MODULE,
        [
            (
                'for forbidden, label in ((TEN_KM_NAME, "10 km"), (TWO_KM_NAME, "2 km")):',
                'for forbidden, label in ((TWO_KM_NAME, "2 km"),):',
            )
        ],
    ),
    (
        "two_km_name_not_refused",
        MODULE,
        [
            (
                'for forbidden, label in ((TEN_KM_NAME, "10 km"), (TWO_KM_NAME, "2 km")):',
                'for forbidden, label in ((TEN_KM_NAME, "10 km"),):',
            )
        ],
    ),
    ("other_names_accepted", MODULE, [("    if given != b2b or target != b2b:", "    if False:")]),
    (
        "link_target_not_checked",
        MODULE,
        [
            (
                "if teriphic.fold_name(forbidden) in (given, target):",
                "if teriphic.fold_name(forbidden) in (given,):",
            )
        ],
    ),
    ("mismatch_factor_relaxed", MODULE, [("MISMATCH_FACTOR = 2.0", "MISMATCH_FACTOR = 1000.0")]),
    ("mismatch_max_relaxed", MODULE, [("MISMATCH_MAX = 0.1", "MISMATCH_MAX = 1.0")]),
    ("low_margin_share_relaxed", MODULE, [("LOW_MARGIN_SHARE = 0.9", "LOW_MARGIN_SHARE = 0.0")]),
    (
        "low_margin_quantile_widened",
        MODULE,
        [("LOW_MARGIN_QUANTILE = 0.2", "LOW_MARGIN_QUANTILE = 1.0")],
    ),
    (
        "winner_syndrome_relaxed",
        MODULE,
        [("SYNDROME_WINNER_MAX = 0.1", "SYNDROME_WINNER_MAX = 0.5")],
    ),
    ("other_syndrome_relaxed", MODULE, [("SYNDROME_OTHER_MIN = 0.4", "SYNDROME_OTHER_MIN = 0.0")]),
    (
        "uniqueness_dropped_from_verdict",
        MODULE,
        [
            (
                '"verified": bool(a and b and c_winner and c_others),',
                '"verified": bool(a and b and c_winner),',
            )
        ],
    ),
    ("equivalence_off", MODULE, [("EQUIVALENT_SYNDROME = 0.01", "EQUIVALENT_SYNDROME = 0.0")]),
    (
        "lane_syndrome_is_the_mean",
        MODULE,
        [
            (
                "    return max(\n        syndrome(streams.hi[cand.mapping], cand.lags, first, last),\n        syndrome(streams.lo[cand.mapping], cand.lags, first, last),\n    )",
                "    return 0.5 * (\n        syndrome(streams.hi[cand.mapping], cand.lags, first, last)\n        + syndrome(streams.lo[cand.mapping], cand.lags, first, last)\n    )",
            )
        ],
    ),
    (
        "verification_scored_on_identification_window",
        MODULE,
        [
            (
                '"syndrome_verification": candidate_syndrome(cand, streams, id_symbols, total),',
                '"syndrome_verification": candidate_syndrome(cand, streams, 0, id_symbols),',
            )
        ],
    ),
    (
        "mismatch_scored_on_identification_window",
        MODULE,
        [
            (
                "    wrong = regenerated[first:] != symbols[first:]\n    m = margin[first:]",
                "    wrong = regenerated[:first] != symbols[:first]\n    m = margin[:first]",
            )
        ],
    ),
    (
        "polarity_ignored",
        MODULE,
        [('    inverted = name.endswith("-inv")', "    inverted = False")],
    ),
    ("gray_code_wrong", MODULE, [('"gray": (0, 1, 3, 2),', '"gray": (0, 1, 2, 3),')]),
    (
        "thresholds_not_midpoints",
        MODULE,
        [
            (
                "    return np.asarray((c[1:] + c[:-1]) / 2.0, dtype=np.float64)",
                "    return np.asarray(c[1:], dtype=np.float64)",
            )
        ],
    ),
    ("bm_agreement_unreachable", MODULE, [("BM_MIN_AGREE = 3", "BM_MIN_AGREE = 99")]),
    (
        "bm_update_rule_changed",
        MODULE,
        [("        if 2 * length <= i:", "        if 2 * length < i:")],
    ),
    ("period_peak_unreachable", MODULE, [("PERIOD_PEAK = 0.5", "PERIOD_PEAK = 0.99")]),
    (
        "periodic_always_enters",
        MODULE,
        [
            (
                '        and rows[best_id]["syndrome_identification"] >= PERIODIC_ENTRY_SYNDROME',
                "        and True",
            )
        ],
    ),
    (
        "worst_seed_kept",
        MODULE,
        [
            (
                "        if best is None or wrong < best[0]:",
                "        if best is None or wrong > best[0]:",
            )
        ],
    ),
    (
        "syndrome_ignores_later_lags",
        MODULE,
        [
            (
                "    for lag in lags:\n        v ^= seg[n - lag : seg.size - lag]",
                "    for lag in lags[:1]:\n        v ^= seg[n - lag : seg.size - lag]",
            )
        ],
    ),
    (
        "backward_generation_stops_early",
        MODULE,
        [
            (
                "    for j in range(position - lo - 1, -1, -1):",
                "    for j in range(position - lo - 1, 0, -1):",
            )
        ],
    ),
    (
        "always_inferred",
        MODULE,
        [
            (
                '"status": STATUS_INFERRED if verified else STATUS_NOT_RECOVERED,',
                '"status": STATUS_INFERRED,',
            )
        ],
    ),
    (
        "ber_reference_claimed",
        MODULE,
        [('BER_STATUS = "REFERENCE_SEQUENCE_MISSING"', 'BER_STATUS = "KNOWN"')],
    ),
    (
        "identification_window_length_changed",
        MODULE,
        [("ID_SAMPLES = 8_388_608", "ID_SAMPLES = 4_194_304")],
    ),
    (
        "script_ten_km_not_refused",
        SCRIPT,
        [
            (
                '    except BenchmarkError as error:\n        print(f"refused: {error}", file=sys.stderr)\n        return 2',
                "    except BenchmarkError:\n        raise SystemExit(0)",
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
        shutil.copy(ROOT / TEST, work / TEST)
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
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PYTHONPATH"] = str(work / "src")
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-x", "-p", "no:cacheprovider", TEST],
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
