"""Write or check the evidence matrix of the external benchmark (gate E4).

python scripts/build_evidence_matrix.py --write   # rewrite docs/benchmarks/EVIDENCE_MATRIX.yaml
python scripts/build_evidence_matrix.py --check   # exit 1 if the file differs from the code
python scripts/build_evidence_matrix.py --table   # print the status table the report embeds

The Wiegart and Ran rows are computed by the E3 modules (about 20 s). The TERIPHIC rows are read
from committed records; no capture under data/external/ is opened and no fit or holdout is re-run.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opticps.benchmarks.e4_matrix import (
    MATRIX_PATH,
    build_matrix,
    dump_matrix,
    render_status_table,
    validate_matrix,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write or check the evidence matrix of the external benchmark (gate E4). "
        "Wiegart and Ran rows are computed by the E3 modules (about 20 s); TERIPHIC rows are "
        "read from committed records. No capture under data/external/ is opened and no fit or "
        "holdout is re-run."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite the matrix file from the code")
    mode.add_argument(
        "--check", action="store_true", help="exit 1 if the matrix file differs from the code"
    )
    mode.add_argument(
        "--table", action="store_true", help="print the status table the report embeds"
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: .)")
    args = parser.parse_args(argv)
    rows = build_matrix(args.root)
    validate_matrix(rows, args.root)
    if args.table:
        print(render_status_table(rows))
        return 0
    text = dump_matrix(rows)
    target = args.root / MATRIX_PATH
    if args.write:
        target.write_text(text, encoding="utf-8")
        print(f"wrote {MATRIX_PATH} ({len(rows)} rows)")
        return 0
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        print(f"{MATRIX_PATH} differs from the code; run with --write", file=sys.stderr)
        return 1
    print(f"{MATRIX_PATH} matches the code ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
