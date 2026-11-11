"""Evaluation script of Gate E2 (plan Revision 13): score one TERIPHIC holdout, JSON on stdout.

    python scripts/score_teriphic_e2.py HOLDOUT.bin --b2b B2B.bin --freeze-commit SHA \
        [--stage failed|not-failed] [--sequence-check not-run|shared] [--state intact|burned]

A thin wrapper of `opticps.benchmarks.e2_score.score_holdout`, which refuses unless the frozen
criterion, the plan and the inputs are committed and unchanged. `--freeze-commit` is required: it is
the freeze commit id the owner recorded outside the repository (a pin on the same machine checks
against ordinary commits and is not date proof).

Two stages (plan Revision 13). The 2 km run prints the report that E2b commits, byte for byte, as
`docs/benchmarks/teriphic_e2/two_km_result.json`, together with `selected_scenario.yaml` (its ids
are the report's `carry_forward`, its `two_km_result_sha256` the SHA-256 of the report) in one
commit. The 10 km run is refused unless `--stage not-failed` is given and that committed record
does not say FAIL or BLOCKED; the 10 km file then stays unspent. `--stage failed` is refused.

The declarations map to the arguments of `holdout.allowed_verdicts` and are printed in the report
under `declarations`; they are the operator's word. Plan R12.4 caps every positive result at the
claim PARTIAL, so VALIDATED is never printed whatever is declared. `--sequence-check shared` or
`--state burned` gives EXPLORATORY (or BLOCKED) at either length. The shared-sequence check itself
is not implemented here, so NOT_SHARED cannot be declared with this script (plan Revision 13
corrects the R12 text that said otherwise). It prints no BER or SER: the reference sequence is
missing (REFERENCE_SEQUENCE_MISSING). Exit codes: 0 a report, 2 a refusal, 3 a refusal by the
two-stage contract (the 2 km stage or the committed 2 km record).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opticps.benchmarks.e2_score import score_holdout  # noqa: E402
from opticps.benchmarks.holdout import (  # noqa: E402
    HoldoutState,
    SequenceCheck,
    StageRefused,
    ValidationStage,
)
from opticps.benchmarks.provenance import BenchmarkError  # noqa: E402

STAGES = {"failed": ValidationStage.FAILED, "not-failed": ValidationStage.NOT_FAILED}
# NOT_SHARED stays an enum member but cannot be declared here: the check is not implemented.
SEQUENCE = {"not-run": SequenceCheck.NOT_RUN, "shared": SequenceCheck.SHARED}
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
    except StageRefused as error:
        print(f"REFUSED (two-stage contract): {error}", file=sys.stderr)
        return 3
    except BenchmarkError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print(result.report_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
