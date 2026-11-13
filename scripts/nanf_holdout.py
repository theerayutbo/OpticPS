"""N3d: the one holdout scoring run (plan Amendment 11 J-G).

    python scripts/nanf_holdout.py --workbook PATH --freeze-hash HASH [--report PATH]

`require_freeze` runs first; a missing, stale or uncommitted-artefact record ends the run before the
workbook is opened. Writes the report; prints the verdict. Run once.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from pathlib import Path

from opticps.measurement import nanf_freeze, nanf_holdout

DEFAULT_REPORT = nanf_freeze.ROOT / "reports/NANF_Holdout_Report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--freeze-hash", required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    try:
        result = nanf_holdout.run_holdout(args.workbook, args.freeze_hash)
    except (nanf_freeze.HoldoutLockedError, nanf_holdout.HoldoutAlreadyReadError) as err:
        print(f"REFUSED: {err}")
        return 1
    args.report.write_text(nanf_holdout.build_report(result), encoding="utf-8")
    print(f"verdict: {result.verdict}; report written to {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
