"""N3c: run the one calibration fit of plan Amendment 11 on the Fig.4 B2B series.

    python scripts/nanf_fit.py --workbook PATH [--log PATH] [--artifact PATH] [--workers N]

Reads the workbook WITHOUT the holdout, runs `nanf_fit.fit` (a second run is refused, a log of the
same run is resumed) and, only if the fit converged and every check ran, writes the bytes of the
calibration artefact. Prints the status and summary numbers, never a series value. Exit code 0 only
for `CALIBRATED`.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from pathlib import Path

from opticps.measurement import nanf_fit, nanf_freeze
from opticps.measurement.nanf_import import read_nanf_workbook

DEFAULT_ARTIFACT = nanf_freeze.ROOT / "docs/benchmarks/NANF_CALIBRATION_RESULT.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--log", type=Path, default=nanf_fit.DEFAULT_LOG_PATH)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.artifact.exists():
        print(f"REFUSED: {args.artifact.name} exists already; one calibration only")
        return 2
    data = nanf_fit.calibration_data(read_nanf_workbook(args.workbook))
    with nanf_fit.CalibrationObjective(data, workers=args.workers) as objective:
        out = nanf_fit.fit(
            objective,
            log_path=args.log,
            plan_sha256=nanf_freeze.plan_sha256(),
            code_identity=nanf_freeze.code_identity(),
        )
    print(f"{out.status}: {out.n_evaluations} evaluations, {out.log.n_worst_case} lost-lock")
    for line in out.lines:
        print(line)
    if out.artefact is None:
        return 1
    assert out.chosen is not None and out.identifiability is not None
    print(f"cost {out.chosen.objective:.6g}; flagged {list(out.identifiability.flagged) or 'none'}")
    print(f"at range edge: {list(out.at_range_edge) or 'none'}")
    for rate, gate in out.gates.items():
        print(f"B2B gate {rate} Gb/s: {gate.label or 'ok'}")
    for line in out.censored_diagnostic:
        print(f"diagnostic: {line}")
    args.artifact.write_bytes(out.artefact)
    print(f"wrote {args.artifact.name}; commit it, then run scripts/nanf_freeze.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
