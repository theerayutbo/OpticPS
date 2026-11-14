"""N3d: the one holdout scoring run (plan Amendment 11 J-G).

    python scripts/nanf_holdout.py --workbook PATH --freeze-hash HASH [--report PATH]

`require_freeze` runs first; a missing, stale or uncommitted-artefact record ends the run before the
workbook is opened. Writes the report, prints the verdict and, when the run ends, the rule that the
marker and the report are committed at once (plan Amendment 13 L-D). Run once.
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
    refused = False
    try:
        result = nanf_holdout.run_holdout(args.workbook, args.freeze_hash)
        args.report.write_text(nanf_holdout.build_report(result), encoding="utf-8")
        print(f"verdict: {result.verdict}; report written to {args.report.name}")
    except (nanf_freeze.HoldoutLockedError, nanf_holdout.HoldoutAlreadyReadError) as err:
        refused = True
        print(f"REFUSED: {err}")
        return 1
    finally:
        if not refused:  # the marker was written before the read: the rule holds, whatever ended it
            print(nanf_holdout.MARKER_RULE)
            print(f"git add {nanf_holdout.MARKER_REL} {_relative(args.report)}")
    return 0


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(nanf_freeze.ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
