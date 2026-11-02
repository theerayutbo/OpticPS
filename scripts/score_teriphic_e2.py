"""Evaluation script of Gate E2 (plan Revision 12): score one TERIPHIC holdout, JSON on stdout.

    python scripts/score_teriphic_e2.py HOLDOUT.bin --b2b B2B.bin --freeze-commit SHA \
        [--stage failed|not-failed] [--sequence-check not-run|shared|not-shared] \
        [--state intact|burned]

A thin wrapper of `opticps.benchmarks.e2_score.score_holdout`, which refuses unless the frozen
criterion, the plan and the inputs are committed and unchanged. `--freeze-commit` is required: it is
the freeze commit id the owner recorded outside the repository (a pin on the same machine checks
against ordinary commits and is not date proof). The three declarations map to the arguments of
`holdout.allowed_verdicts`; without them the result can be FAILED, INCONCLUSIVE,
UNIDENTIFIABLE_PARAMETER or BLOCKED. Plan R12.4 caps every positive result at the claim PARTIAL, so
VALIDATED is never printed whatever is declared; EXPLORATORY is reachable with
`--sequence-check shared` or `--state burned`. The shared-sequence check itself is not implemented
here, so `not-shared` cannot be established by this script and the declaration is the operator's.
Gate E2 part a does not run it on a holdout; that is E2b. It prints no BER or SER: the reference
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
from opticps.benchmarks.holdout import (  # noqa: E402
    HoldoutState,
    SequenceCheck,
    ValidationStage,
)
from opticps.benchmarks.provenance import BenchmarkError  # noqa: E402

STAGES = {"failed": ValidationStage.FAILED, "not-failed": ValidationStage.NOT_FAILED}
SEQUENCE = {
    "not-run": SequenceCheck.NOT_RUN,
    "shared": SequenceCheck.SHARED,
    "not-shared": SequenceCheck.NOT_SHARED,
}
STATES = {"intact": HoldoutState.INTACT, "burned": HoldoutState.BURNED}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("--b2b", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=sorted(STAGES), default=None)
    parser.add_argument("--sequence-check", choices=sorted(SEQUENCE), default=None)
    parser.add_argument("--state", choices=sorted(STATES), default=None)
    args = parser.parse_args(argv)
    try:
        result = score_holdout(
            args.holdout,
            b2b_path=args.b2b,
            expected_freeze_commit=args.freeze_commit,
            repo_root=args.repo,
            validation_stage=STAGES.get(args.stage or ""),
            sequence_check=SEQUENCE.get(args.sequence_check or ""),
            state=STATES.get(args.state or ""),
        )
    except BenchmarkError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result.report(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
