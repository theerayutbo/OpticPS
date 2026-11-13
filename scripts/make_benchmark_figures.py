"""Regenerate the benchmark figures of gate E4 from repository code and committed records.

python scripts/make_benchmark_figures.py [--out DIR] [--only NAME ...]

Writes one PNG per figure. Every plotted series carries one legend label from PUBLISHED DATA,
EXTERNAL RAW CAPTURE, SIMULATED, DIGITIZED, UNKNOWN, or the two-word SIMULATED vs EXTERNAL RAW
CAPTURE for a simulated scenario compared with a capture. The hash of each figure's specification
is written into the PNG (text chunk OpticPS-figure-spec-sha256). Wiegart and Ran figures hold
only our own computed curves and numbers stated in running text; no DIGITIZED series exists. The
TERIPHIC figures are drawn from the committed 2 km scoring record; no capture under data/external/
is opened.
Needs no data/external/. About 25 s.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from pathlib import Path

from opticps.benchmarks.e4_figures import BUILDERS, FIGURE_DIR, save_figures


def main(argv: list[str] | None = None) -> int:
    names = [b.__name__ for b in BUILDERS]
    parser = argparse.ArgumentParser(
        description="Regenerate the benchmark figures of gate E4 from repository code and "
        "committed records. Needs no data/external/. Every series has one legend label from "
        "PUBLISHED DATA, EXTERNAL RAW CAPTURE, SIMULATED, DIGITIZED, UNKNOWN, or SIMULATED vs "
        "EXTERNAL RAW CAPTURE."
    )
    parser.add_argument(
        "--out", type=Path, default=FIGURE_DIR, help=f"output directory (default: {FIGURE_DIR})"
    )
    parser.add_argument(
        "--only", nargs="+", choices=names, help="build only these figures (default: all)"
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: .)")
    args = parser.parse_args(argv)
    specs = [b(args.root) for b in BUILDERS if args.only is None or b.__name__ in args.only]
    for path in save_figures(specs, args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
