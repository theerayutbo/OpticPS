"""Measure CCDM encode and decode time per block and peak memory.

Usage: uv run python scripts/profile_ccdm.py [--out docs/notes/ccdm_profile.md]

Uses the exact enumerative matcher on the entropy-matched inner-heavy Maxwell-Boltzmann
PMF (0.12 bit below log2 M for M >= 4; uniform for M = 2) with a symmetric composition.
Time is the median of REPEATS blocks after one warm-up; peak memory is the tracemalloc
peak of one encode or one decode (Python allocations, big integers included, not numpy
buffers' process RSS). Tests never depend on these numbers.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import math
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.shaping.distributions import mb_for_entropy

SEED = 20261031
ORDERS = (2, 4, 8, 16)
LENGTHS = (256, 1024, 4096)
REPEATS = 5
STOP_SECONDS = 1.0  # stop-and-report threshold, M=16 at n=1024


def machine() -> str:
    cpu = platform.processor() or platform.machine()
    try:
        import subprocess

        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            cpu = out.stdout.strip()
    except (OSError, ValueError):
        pass
    return f"{platform.system()} {platform.release()} {platform.machine()}, {cpu}"


def timed(func, *args) -> tuple[float, object]:
    start = time.perf_counter()
    result = func(*args)
    return time.perf_counter() - start, result


def peak_kib(func, *args) -> float:
    tracemalloc.start()
    try:
        func(*args)
        return tracemalloc.get_traced_memory()[1] / 1024
    finally:
        tracemalloc.stop()


def profile(order: int, n: int, rng: np.random.Generator) -> dict[str, float]:
    p = np.full(order, 1 / order) if order == 2 else mb_for_entropy(math.log2(order) - 0.12, order)
    matcher = ConstantCompositionMatcher.from_symmetric_probabilities(p, n)
    blocks = [rng.integers(0, 2, matcher.k).astype(np.int8) for _ in range(REPEATS + 1)]
    symbols = [matcher.encode(b) for b in blocks]  # warm-up pass and decode inputs
    enc = [timed(matcher.encode, b)[0] for b in blocks[1:]]
    dec = []
    for b, s in zip(blocks[1:], symbols[1:], strict=True):
        seconds, bits = timed(matcher.decode, s)
        if not np.array_equal(bits, b):
            raise RuntimeError(f"round trip failed at M={order}, n={n}")
        dec.append(seconds)
    return {
        "k": matcher.k,
        "rate": matcher.rate,
        "enc_ms": 1e3 * statistics.median(enc),
        "dec_ms": 1e3 * statistics.median(dec),
        "enc_kib": peak_kib(matcher.encode, blocks[1]),
        "dec_kib": peak_kib(matcher.decode, symbols[1]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/notes/ccdm_profile.md"))
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    rows = []
    for order in ORDERS:
        for n in LENGTHS:
            rows.append((order, n, profile(order, n, rng)))
            print(order, n, rows[-1][2], flush=True)
    worst = next(r["enc_ms"] for o, n, r in rows if o == 16 and n == 1024)
    worst_dec = next(r["dec_ms"] for o, n, r in rows if o == 16 and n == 1024)
    breached = max(worst, worst_dec) / 1e3 > STOP_SECONDS
    lines = [
        "# CCDM profile (measured)",
        "",
        f"- Machine: {machine()}",
        f"- Python {sys.version.split()[0]}, numpy {np.__version__}",
        f"- Seed {SEED}; random input bits; median of {REPEATS} blocks after one warm-up",
        "- Matcher: exact enumerative, symmetric composition, entropy-matched inner-heavy MB "
        "(H = log2 M - 0.12 bit; uniform at M = 2)",
        "- Memory: tracemalloc peak of one call (Python-level allocations)",
        f"- Threshold: {STOP_SECONDS:g} s per block at n = 1024, M = 16: "
        + ("EXCEEDED" if breached else "not exceeded"),
        "",
        "| M | n | k bits | rate | encode ms | decode ms | encode peak KiB | decode peak KiB |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for order, n, r in rows:
        lines.append(
            f"| {order} | {n} | {r['k']:.0f} | {r['rate']:.4f} | {r['enc_ms']:.1f} | "
            f"{r['dec_ms']:.1f} | {r['enc_kib']:.0f} | {r['dec_kib']:.0f} |"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 1 if breached else 0


if __name__ == "__main__":
    raise SystemExit(main())
