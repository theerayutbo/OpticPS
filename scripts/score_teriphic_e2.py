"""Evaluation script of Gate E2 (plan Revision 10): score one TERIPHIC holdout, JSON on stdout.

    python scripts/score_teriphic_e2.py HOLDOUT.bin --b2b B2B.bin [--stage not-failed|failed]

This is a thin wrapper of `opticps.benchmarks.e2_score.score_holdout`, which refuses unless the
frozen criterion, the plan and the inputs are committed and unchanged. Gate E2 part a does not run
it on a holdout; that is E2b, after independent review. It prints no BER or SER: the reference
sequence is missing (REFERENCE_SEQUENCE_MISSING).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opticps.benchmarks.e2_score import score_holdout  # noqa: E402
from opticps.benchmarks.holdout import ValidationStage  # noqa: E402
from opticps.benchmarks.provenance import BenchmarkError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("--b2b", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=("failed", "not-failed"), default=None)
    args = parser.parse_args()
    stage = {"failed": ValidationStage.FAILED, "not-failed": ValidationStage.NOT_FAILED}.get(
        args.stage or ""
    )
    try:
        result = score_holdout(
            args.holdout, b2b_path=args.b2b, repo_root=args.repo, validation_stage=stage
        )
    except BenchmarkError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result.report(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
