"""Mutation check of the benchmark guards (gate E0, fix round 3).

Each mutant is one text replacement in `src/opticps/benchmarks`, applied to a scratch copy of the
repository files the E0 test needs; the test file runs against that copy and the mutant is
"killed" when a test fails (pytest exit code 1). A survivor means a guard has no test that
notices its removal. A mutant that breaks collection (exit code 2 or more) is reported BROKEN,
never killed, and the unmutated copy must pass first. The exit code is 0 only when every listed
mutant is killed.

    python scripts/mutate_benchmarks.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a sample of the guards, written by hand; it proves nothing about mutants that are not
in it. Needs `git` (the tests build throwaway repositories).
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
# (file, old text, new text); `old` must occur exactly once. Equivalent mutants found and left out
# (no test can tell them from the original): dropping the final `_signature(criterion_bytes) !=
# baseline` re-check (the history loop has compared the HEAD blob already), the `None` guard of
# `Checksum.still_current` (comparing a size with None is False anyway), `--topo-order` (the order
# of the commits that touch one path is the same), a smaller `timeout`, `fstat` for `stat`,
# `log.showRoot=true` (since no `--name-only` is used it changes no output we read) and the type
# name in `_typed` (the repr already differs for 1, 1.0, True and "1").
MUTANTS: list[tuple[str, str, str]] = [
    (H, "if working != committed:", "if False:"),
    (H, "elif signature != baseline:", "elif False:"),
    (H, "else None\n        if baseline is None:", "else baseline\n        if baseline is None:"),
    (H, "    return entries[::-1]", "    return entries"),
    (H, '"--format=%H %cI %aI"', '"--format=%H %aI %cI"'),
    (H, 'if shallow == "true":', "if False:"),
    (H, "if (root / grafts).exists():", "if False:"),
    (H, 'extensions.partialclone").returncode == 0:', 'extensions.partialclone").returncode == 9:'),
    (H, 'if not k.startswith("GIT_")}', "if True}"),
    (H, '"git", "--no-replace-objects", "-C"', '"git", "-C"'),
    (H, '"log.showSignature=false"', '"log.showSignature=true"'),
    (H, "    if done.returncode != 0:", "    if False:"),
    (
        H,
        '    if _git(root, "rev-parse", "--verify", "--quiet", spec).returncode != 0:',
        "    if False:",
    ),
    (H, "        _refuse_rename_in(repo_root, commit, relative)\n", ""),
    (H, 'if line.startswith("R") and line.split("\\t")[-1] == relative:', "if False:"),
    (H, '"--find-renames=20%"', '"--find-renames=100%"'),
    (H, "        if not input_bytes:", "        if False:"),
    (H, "    if asset.split not in HOLDOUT_SPLITS:", "    if False:"),
    (H, "    if set(supplied) != set(required):", "    if False:"),
    (
        H,
        "asset.split is Split.LOCKED_TEST and not (",
        "asset.split is Split.LOCKED_TEST and False and not (",
    ),
    (H, 'if document["plan_sha256"] != plan_hash:', "if False:"),
    (H, 'if document["estimators"] != dict(ESTIMATORS):', "if False:"),
    (H, "        if not math.isclose(", "        if False and not math.isclose("),
    (H, "rel_tol=_LIMIT_RELATIVE_TOLERANCE", "rel_tol=0.1"),
    (H, "    return _typed(document)", '    return _typed(document["limits"])'),
    (H, "if state is HoldoutState.BURNED:", "if False:"),
    (
        H,
        "if sequence_check is SequenceCheck.SHARED:\n            verdicts",
        "if False:\n            verdicts",
    ),
    (
        H,
        "if sequence_check is SequenceCheck.SHARED:\n            return",
        "if False:\n            return",
    ),
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
    (P, '"tbd", "tba", "tbc"', '"x1", "x2", "x3"'),
    (
        P,
        '.casefold()\n    return (squeezed.rstrip(".!") or squeezed)',
        ".casefold()\n    return (squeezed)",
    ),
    (P, 'squeezed = "".join(text.split()).casefold()', "squeezed = text.strip().casefold()"),
    (P, 'and value.strip().casefold() != "none":', 'and value.strip().casefold() != "zzz":'),
    (P, "if is_placeholder(value) and name not in _NONE_IS_AN_ANSWER:", "if False:"),
    (P, '"sample_rate_hz": (1e6, 1e13)', '"sample_rate_hz": (1.0, 1e13)'),
    (P, '"dispersion_ps_per_nm_km": (-1e4, 1e4),', '"dispersion_ps_per_nm_km": (-1e300, 1e300),'),
    (P, 'if "NC" in terms and self.commercial_use in _GRANTING:', "if False:"),
    (P, 'if "ND" in terms and self.derivatives in _GRANTING:', "if False:"),
    (P, 'if t in ("NC", "ND")}', 'if t in ("zz",)}'),
    (P, 'r"(?:cc)?by((?:nc|nd|sa)+)"', 'r"(?:cc)?by((?:sa)+)"'),
    (P, 'if "noncommercial" in flat:', "if False:"),
    (P, 'if "noderivative" in flat:', "if False:"),
    (P, "if not known and any(", "if False and any("),
    (P, "[0-9]{2}(?:[a-z]{2})?", "[0-9]{2}"),
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
    (P, "status.st_size == self.size_local and", "True and"),
    (P, 'path.open("rb")', 'path.open("r+b")'),
    (P, "while chunk := handle.read(_CHUNK):", "while chunk := handle.read():"),
    (P, '    object.__setattr__(checksum, "size_local", status.st_size)\n', ""),
    (
        C,
        "    except (UnicodeDecodeError, OSError) as error:",
        "    except ZeroDivisionError as error:",
    ),
]


def run(mutant: tuple[str, str, str] | None) -> str:
    """killed, SURVIVED, BROKEN (not a test failure) or INVALID; None runs the unmutated copy."""
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
        if mutant is not None:
            name, old, new = mutant
            target = work / "src/opticps/benchmarks" / name
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
             "tests/test_benchmark_provenance.py"],
            cwd=work, env=env, capture_output=True, text=True,
        )  # fmt: skip
        if mutant is None:
            return "passed" if done.returncode == 0 else "FAILED"
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
    chosen = [m for m in MUTANTS if args.k in m[1] + m[2]]
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(args.j) as pool:
        for (file, old, _), status in zip(chosen, pool.map(run, chosen), strict=True):
            print(f"{status:9} {file}: {old.strip()[:70]!r}", flush=True)
            key = status if status in ("killed", "SURVIVED", "BROKEN") else "INVALID"
            counts[key] = counts.get(key, 0) + 1
    print(
        f"{len(chosen)} applied: {counts.get('killed', 0)} killed, {counts.get('SURVIVED', 0)}"
        f" survived, {counts.get('BROKEN', 0)} broken, {counts.get('INVALID', 0)} invalid"
    )
    return 0 if counts.get("killed", 0) == len(chosen) else 1


if __name__ == "__main__":
    raise SystemExit(main())
