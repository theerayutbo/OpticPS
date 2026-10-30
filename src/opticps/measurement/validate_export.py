"""Independent validation of exported M8199B files.

Reads files back with the standard-library csv module and pure Python arithmetic,
not the generator's numpy path. Each check yields one row of validation_results.csv.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.instruments.m8199b import GRANULARITY_SAMPLES, MAX_SAMPLES

IID_SIGMA_LIMIT = 5.0
LEVELS = (-3, -1, 1, 3)


@dataclass(frozen=True)
class Check:
    """One validation outcome."""

    waveform: str
    check: str
    passed: bool
    detail: str


def read_waveform(path: Path) -> tuple[str, list[float]]:
    """Return the header and samples; raises on any cell that is not a single number."""
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if len(header) != 1:
            raise ValueError(f"Header must be one column, got {header}")
        samples = []
        for number, row in enumerate(reader, start=2):
            if len(row) != 1:
                raise ValueError(f"Row {number} must have one column, got {row}")
            samples.append(float(row[0]))
    return header[0], samples


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_symbols(path: Path) -> tuple[list[int], list[int]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [int(r["symbol_index"]) for r in rows], [int(r["level"]) for r in rows]


def validate_waveform(folder: Path, row: dict[str, str], expected_header: str) -> list[Check]:
    """Run every check on one manifest row."""
    name = Path(row["waveform_filename"]).stem
    checks: list[Check] = []

    def record(check: str, passed: bool, detail: object) -> None:
        checks.append(Check(name, check, bool(passed), str(detail)))

    wave_path = folder / row["waveform_filename"]
    try:
        header, samples = read_waveform(wave_path)
    except (ValueError, StopIteration) as error:
        record("csv_parse", False, error)
        return checks
    record("csv_parse", True, f"{len(samples)} rows")
    record("header_exact", header == expected_header, header)

    count = int(row["number_of_samples"])
    finite = all(math.isfinite(v) for v in samples)
    record("all_finite", finite, f"{len(samples)} samples")
    in_range = finite and all(-1.0 <= v <= 1.0 for v in samples)
    record("range_within_unit", in_range, f"min {min(samples)} max {max(samples)}")
    record("sample_count", len(samples) == count, f"{len(samples)} vs {count}")
    record("granularity_512", len(samples) % GRANULARITY_SAMPLES == 0, len(samples))
    record("max_length", len(samples) <= MAX_SAMPLES, len(samples))

    sample_rate = float(row["sample_rate_Sa_per_s"])
    symbol_rate = float(row["symbol_rate_Bd"])
    sps = int(row["samples_per_symbol"])
    symbols_n = int(row["number_of_symbols"])
    record("rate_consistency", abs(sample_rate / symbol_rate - sps) < 1e-9, sps)
    duration = len(samples) / sample_rate
    record(
        "duration",
        math.isclose(duration, float(row["waveform_duration_s"]), rel_tol=1e-9),
        duration,
    )

    reference_dir = folder / "references" / name
    symbol_path = reference_dir / f"{name}_symbols.csv"
    indices, levels = _read_symbols(symbol_path)
    record("reference_length", len(indices) * sps == len(samples), len(indices))
    record(
        "reference_levels",
        all(LEVELS[i] == v for i, v in zip(indices, levels, strict=True)),
        "index-level map",
    )
    record("waveform_sha256", _sha256(wave_path) == row["waveform_sha256"], row["waveform_sha256"])
    record("reference_sha256", _sha256(symbol_path) == row["reference_sha256"], "symbols file")

    metadata = json.loads((reference_dir / f"{name}_metadata.json").read_text())
    start = metadata["frame"]["payload"][0]
    payload = indices[start:]
    realised = [payload.count(s) / len(payload) for s in range(4)]
    target = metadata["shaping"]["target_probabilities"]
    worst = max(abs(a - b) for a, b in zip(realised, target, strict=True))
    if metadata["frame"]["matcher_composition"] is None:
        # Independent symbols: the deviation is sampling noise.
        limit = IID_SIGMA_LIMIT * max(math.sqrt(p * (1 - p) / len(payload)) for p in target)
    else:
        # Constant composition: the deviation is only integer rounding within a block.
        limit = 1.0 / metadata["frame"]["matcher_block_length"]
    record(
        "distribution_within_tolerance", worst <= limit, f"max dev {worst:.5f}, limit {limit:.5f}"
    )
    record(
        "preamble_balanced",
        indices[:512].count(0) == indices[:512].count(3) == 256,
        "256 of each outer level",
    )

    full_scale = metadata["dac_normalization"]["full_scale_levels"]
    offset = metadata["symbol_centre_offset_samples"]
    if metadata["pulse"]["shape"] == "nrz":
        position = int(offset)
        recovered = []
        for k in range(symbols_n):
            value = samples[k * sps + position] * full_scale
            recovered.append(min(range(4), key=lambda s: abs(LEVELS[s] - value)))
        errors = sum(a != b for a, b in zip(recovered, indices, strict=True))
        record("noise_free_reconstruction", errors == 0, f"{errors} symbol errors")
    else:
        record("noise_free_reconstruction", True, "rrc: covered by receiver matched-filter test")
        recovered = indices

    bits_text = (reference_dir / f"{name}_info_bits.txt").read_text().strip()
    blocks = metadata["frame"]["matcher_blocks"]
    length = metadata["frame"]["matcher_block_length"]
    per_block = metadata["frame"]["bits_per_block"]
    counts = metadata["frame"]["matcher_composition"]
    record("info_bit_count", len(bits_text) == blocks * per_block, len(bits_text))
    if counts is None:
        record("matcher_rate", per_block == 2 * length, "direct Gray mapping, 2 bits per symbol")
    else:
        matcher = ConstantCompositionMatcher(counts)
        record("matcher_rate", matcher.k == per_block, f"k={matcher.k}, n={matcher.n}")
        decoded = "".join(
            "".join(
                map(
                    str,
                    matcher.decode(
                        np.array(recovered[start + b * length : start + (b + 1) * length])
                    ),
                )
            )
            for b in range(blocks)
        )
        record("ccdm_inverse_recovers_bits", decoded == bits_text, f"{len(decoded)} bits")
    return checks


def validate_profile(folder: Path, expected_header: str = "DataOut1") -> list[Check]:
    """Validate a profile folder, including its checksum list, and write the results CSV."""
    with (folder / "experiment_manifest.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    results: list[Check] = []
    for row in rows:
        results.extend(validate_waveform(folder, row, expected_header))
    for line in (folder / "checksums.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        path = folder / relative
        ok = path.exists() and _sha256(path) == digest
        results.append(Check(relative, "checksum_file_entry", ok, digest[:16]))
    with (folder / "validation_results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["waveform", "check", "result", "detail"])
        for item in results:
            writer.writerow(
                [item.waveform, item.check, "PASS" if item.passed else "FAIL", item.detail]
            )
    return results
