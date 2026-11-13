"""N3c: write the freeze record of a committed calibration artefact (plan G4, F8).

    python scripts/nanf_freeze.py [ARTIFACT_PATH]

Refuses if a record exists, if the work tree differs from HEAD in the code identity, the plan or the
artefact, or if the artefact is not committed at HEAD. Commit the record before any holdout read.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse

from opticps.measurement import nanf_freeze, nanf_holdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifact", nargs="?", default="docs/benchmarks/NANF_CALIBRATION_RESULT.json"
    )
    args = parser.parse_args()
    try:
        record = nanf_holdout.write_freeze_record(args.artifact)
    except (nanf_holdout.FreezeRefusedError, nanf_freeze.HoldoutLockedError) as err:
        print(f"REFUSED: {err}")
        return 1
    print(f"wrote the freeze record; freeze hash {record['freeze_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
