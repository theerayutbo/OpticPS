"""Mutation check of the benchmark guards (gate E0, fix round 2).

Each mutant is one text replacement in `src/opticps/benchmarks`, applied to a scratch copy of the
repository files the E0 test needs; the test file runs against that copy and the mutant is
"killed" when it fails. A survivor means a guard has no test that notices its removal.

    python scripts/mutate_benchmarks.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a sample of the guards added in fix round 2, written by hand; it proves nothing
about mutants that are not in it. Needs `git` (the tests build throwaway repositories).
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
H, P, C = "holdout.py", "provenance.py", "catalog.py"
# (file, old text, new text); `old` must occur exactly once. Equivalent mutants found and left out:
# `if signature is not None` -> True (a later commit overwrites the baseline), setting
# GIT_NO_REPLACE_OBJECTS to "0" (Git reads the variable by presence) and dropping the final
# limits re-check (it repeats what the history loop already established).
MUTANTS: list[tuple[str, str, str]] = [
    (H, "if working != committed:", "if False:"),
    (H, "elif signature != baseline:", "elif False:"),
    (H, "    entries.reverse()\n", ""),
    (H, '"--format=@@%H %cI %aI"', '"--format=@@%H %aI %cI"'),
    (H, "            if signature is not None:\n", "            if True:\n"),
    (H, '== b"true"', '== b"false"'),
    (H, 'if not k.startswith("GIT_")}', "if True}"),
    (H, 'environment["GIT_NO_REPLACE_OBJECTS"] = "1"', "pass"),
    (H, '        "--follow",\n', ""),
    (H, "    if asset.split not in HOLDOUT_SPLITS:", "    if False:"),
    (H, "    if set(supplied) != set(required):", "    if False:"),
    (
        H,
        "asset.split is Split.LOCKED_TEST and not (",
        "asset.split is Split.LOCKED_TEST and False and not (",
    ),
    (H, 'if document["plan_sha256"] != plan_hash:', "if False:"),
    (H, "        if not math.isclose(", "        if False and not math.isclose("),
    (H, "if state is HoldoutState.BURNED:", "if False:"),
    (H, "if sequence_check is SequenceCheck.SHARED:", "if False:"),
    (H, "state is HoldoutState.INTACT\n", "True\n"),
    (H, "and validation_stage is ValidationStage.NOT_FAILED", "and True"),
    (H, "and sequence_check is SequenceCheck.NOT_SHARED", "and True"),
    (H, "        if mint is not _MINT:", "        if False:"),
    (
        H,
        '        raise TypeError("FrozenCriterion cannot be copied or pickled")',
        "        return (int, ())",
    ),
    (H, "    except OverflowError:", "    except ZeroDivisionError:"),
    (H, "limits=MappingProxyType(limits),", "limits=limits,"),
    (
        H,
        "    if asset.split is Split.CHARACTERISATION:\n        return None\n",
        "    if True:\n        return None\n",
    ),
    (P, '"tbd", "tba", "todo", "unspecified"', '"x1", "x2", "x3", "x4"'),
    (P, 'squeezed = "".join(text.split()).casefold()', "squeezed = text.strip().casefold()"),
    (P, '"sample_rate_hz": (1e6, 1e13)', '"sample_rate_hz": (1.0, 1e13)'),
    (P, 'if "NC" in tokens and self.commercial_use in _GRANTING:', "if False:"),
    (P, 'if "ND" in tokens and self.derivatives in _GRANTING:', "if False:"),
    (P, 'family = "MD5" if kind.endswith("MD5") else kind', "family = kind"),
    (
        P,
        "@dataclass(frozen=True, slots=True)\nclass Checksum:",
        "@dataclass(frozen=True)\nclass Checksum:",
    ),
    (
        P,
        'raise TypeError("a Checksum is not pickled or copied',
        "return (Checksum, ()) #",
    ),
    (P, "status.st_mtime_ns == self.mtime_ns_local", "True"),
    (P, 'path.open("rb")', 'path.open("r+b")'),
    (P, "while chunk := handle.read(_CHUNK):", "while chunk := handle.read():"),
    (P, 'object.__setattr__(checksum, "size_local", status.st_size)\n', ""),
    (
        C,
        "    except (UnicodeDecodeError, OSError) as error:",
        "    except ZeroDivisionError as error:",
    ),
]


def run(index: int, mutant: tuple[str, str, str], keep: Path) -> tuple[int, str]:
    name, old, new = mutant
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for folder in ("configs/benchmarks", "docs/benchmarks"):
            shutil.copytree(ROOT / folder, work / folder)
        (work / "tests").mkdir()
        shutil.copy(ROOT / "tests/test_benchmark_provenance.py", work / "tests")
        for extra in ("tests/conftest.py",):
            if (ROOT / extra).exists():
                shutil.copy(ROOT / extra, work / extra)
        target = work / "src/opticps/benchmarks" / name
        text = target.read_text()
        if text.count(old) != 1:
            return index, f"INVALID ({text.count(old)} matches)"
        target.write_text(text.replace(old, new))
        git = ["git", "-C", str(work)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        env = {**os.environ, "PYTHONPATH": str(work / "src")}
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-x", "-p", "no:cacheprovider",
             "tests/test_benchmark_provenance.py"],
            cwd=work, env=env, capture_output=True, text=True,
        )  # fmt: skip
        return index, "killed" if done.returncode != 0 else "SURVIVED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument("-k", default="")
    args = parser.parse_args()
    chosen = [(i, m) for i, m in enumerate(MUTANTS) if args.k in m[1] + m[2]]
    survivors = 0
    with ThreadPoolExecutor(args.j) as pool:
        for index, status in pool.map(lambda im: run(im[0], im[1], ROOT), chosen):
            file, old, _ = MUTANTS[index]
            print(f"{status:9} {file}: {old.strip()[:70]!r}", flush=True)
            survivors += status != "killed"
    print(f"{len(chosen)} applied, {survivors} survived or invalid")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
