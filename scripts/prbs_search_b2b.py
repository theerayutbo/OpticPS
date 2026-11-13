"""B2B-only transmitted-pattern search (plan R.2; `teriphic_prbs/prbs_search_prereg.md`).

    python scripts/prbs_search_b2b.py [--data PATH] [--out PATH]

Opens only the registered B2B file (`prbs_search.open_b2b_only`: the 10 km name, the 2 km name and
every other name are refused before any open). Runs P1 to P7 once and writes the result YAML, which
holds the generator, mapping, seed state and statistics and never the sequence. Refuses to overwrite
an existing output. Exit codes: 0 done, 2 refused or a prerequisite missing.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opticps.benchmarks import prbs_search, teriphic  # noqa: E402
from opticps.benchmarks.provenance import BenchmarkError  # noqa: E402

OUT_PATH = ROOT / "docs/benchmarks/teriphic_prbs/b2b_sequence_candidate.yaml"
MODEL_PATH = ROOT / "docs/benchmarks/teriphic_e2/b2b_model.yaml"
PREREG_PATH = ROOT / "docs/benchmarks/teriphic_prbs/prbs_search_prereg.md"
CODE_FILES = (
    "src/opticps/benchmarks/prbs_search.py",
    "scripts/prbs_search_b2b.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=ROOT / teriphic.DEFAULT_ROOT / teriphic.B2B_FILENAME
    )
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    if args.out.exists():
        print(f"refused: {args.out} exists; one run, one output", file=sys.stderr)
        return 2
    model = yaml.safe_load(MODEL_PATH.read_text())
    fs, baud = float(model["sample_rate_hz"]), float(model["baud_bd"])
    c0, g0 = float(model["normalisation"]["c0"]), float(model["normalisation"]["g0"])
    try:
        capture = prbs_search.open_b2b_only(args.data)
    except BenchmarkError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    started = time.time()
    try:
        raw = capture.read(0, capture.count)
        checksum = capture.checksum
        count = capture.count
    finally:
        capture.close()
    x = (raw - c0) / g0
    del raw
    result = prbs_search.run_search(x, fs, baud)
    record: dict[str, Any] = {
        "b2b_sequence_candidate_version": 1,
        "declared": (
            "B2B-only search for the transmitted pattern (plan R.2 characterisation), run once"
            " under"
            " prbs_search_prereg.md (with amendment A1). The 2 km and 10 km files were not used,"
            " opened, hashed or linked. The sequence is not stored."
        ),
        "file": teriphic.B2B_FILENAME,
        "sha256": None if checksum is None else checksum.sha256_local,
        "samples": count,
        "windows": {
            "identification": [0, prbs_search.ID_SAMPLES],
            "verification": [prbs_search.ID_SAMPLES, count],
        },
        "normalisation": {"c0": c0, "g0": g0, "source": "teriphic_e2/b2b_model.yaml (R13)"},
        "head_commit": git_head(),
        "prereg_sha256": sha256(PREREG_PATH),
        "code_identity": {name: sha256(ROOT / name) for name in CODE_FILES},
        "seconds": round(time.time() - started, 1),
        **result,
    }
    args.out.write_text(yaml.safe_dump(record, sort_keys=False, width=100))
    print(f"status: {result['status']}")
    print(f"p2 period: {result['p2_period_scan']['period_symbols']}")
    print(f"p6: {result['p6']['verified']} mismatch {result['p6']['mismatch_rate']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
