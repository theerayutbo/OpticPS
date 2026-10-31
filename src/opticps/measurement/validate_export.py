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
from opticps.transmitter.export import MANIFEST_COLUMNS, MANIFEST_COLUMNS_V2
from opticps.transmitter.pulse import rrc_frequency_response

IID_SIGMA_LIMIT = 5.0
LEVELS = (-3, -1, 1, 3)  # PAM4; see levels_of for any order
KNOWN_ORDERS = (2, 4, 8, 16)
EVIDENCE_LABELS = ("simulated", "mock", "measured", "analytical")
# Frame head, written out here and not read from the generator: 511-chip m-sequence plus one
# balance symbol on the outer levels, then training symbols balanced over the levels. The head
# is a multiple of 1024 symbols.
PREAMBLE_SYMBOLS = 512
TRAINING_SYMBOLS = {2: 512, 4: 512, 8: 1536, 16: 2560}
DAC_HALF_STEPS = 2**7 - 1  # 8-bit mid-tread map assumed by the generator; a diagnostic only
# Requested targets, held here so a consistently mislabelled package cannot pass.
EXPECTED_TARGETS = {
    "PAM4_Uniform": (0.25, 0.25, 0.25, 0.25),
    "PAM4_Fixed_PS70": (0.15, 0.35, 0.35, 0.15),
    "PAM4_Fixed_PS80": (0.10, 0.40, 0.40, 0.10),
    "PAM4_Fixed_Outer70": (0.35, 0.15, 0.15, 0.35),
}


@dataclass(frozen=True)
class Check:
    """One validation outcome."""

    waveform: str
    check: str
    passed: bool
    detail: str


def levels_of(order: int) -> tuple[int, ...]:
    """The odd-integer levels of PAM-M, lowest first: 2 i - (M - 1)."""
    return tuple(2 * i - (order - 1) for i in range(order))


def manifest_schema(fieldnames: list[str] | None, rows: list[dict[str, str]]) -> int | None:
    """Return the manifest schema (1 or 2), or None if it is not exactly a known one.

    Default-deny: version 1 is the original 40 columns and no version column; version 2 needs
    the exact v2 column list and every row to say "2". Anything else, including a version
    this code has not seen, is None.
    """
    if fieldnames is None:
        return None
    if fieldnames == MANIFEST_COLUMNS:
        return 1
    if (
        fieldnames == MANIFEST_COLUMNS_V2
        and rows
        and all(r["manifest_schema_version"] == "2" for r in rows)
    ):
        return 2
    return None


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


def validate_waveform(
    folder: Path, row: dict[str, str], expected_header: str, schema: int = 1
) -> list[Check]:
    """Run every check on one manifest row (schema 1: PAM4; schema 2: any known order)."""
    name = Path(row["waveform_filename"]).stem
    checks: list[Check] = []

    def record(check: str, passed: bool, detail: object) -> None:
        checks.append(Check(name, check, bool(passed), str(detail)))

    order = 4 if schema == 1 else int(row["modulation_order"])
    if order not in KNOWN_ORDERS:
        record("modulation_order_known", False, f"order {order} not in {KNOWN_ORDERS}")
        return checks
    bits = order.bit_length() - 1
    levels_table = levels_of(order)
    consistent = (
        row["modulation"] == f"PAM{order}"
        and name.startswith(f"PAM{order}_")
        and (schema == 1 or int(row["bits_per_symbol"]) == bits)
    )
    record(
        "modulation_matches_manifest_row",
        consistent,
        f"{row['modulation']}, name {name}, order {order}",
    )
    if schema == 2:
        record("evidence_label", row["evidence"] in EVIDENCE_LABELS, row["evidence"])

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
        all(0 <= i < order and levels_table[i] == v for i, v in zip(indices, levels, strict=True)),
        f"index-level map of PAM{order}",
    )
    record("waveform_sha256", _sha256(wave_path) == row["waveform_sha256"], row["waveform_sha256"])
    record("reference_sha256", _sha256(symbol_path) == row["reference_sha256"], "symbols file")

    metadata = json.loads((reference_dir / f"{name}_metadata.json").read_text())
    if schema == 2:
        record(
            "modulation_order_matches_metadata",
            metadata.get("modulation_order") == order
            and metadata.get("manifest_schema_version") == 2
            and metadata.get("evidence") == row["evidence"],
            f"metadata order {metadata.get('modulation_order')}, row order {order}",
        )
    start = metadata["frame"]["payload"][0]
    payload = indices[start:]
    realised = [payload.count(s) / len(payload) for s in range(order)]
    target = metadata["shaping"]["target_probabilities"]
    record("probability_vector_length", len(target) == order, f"{len(target)} for PAM{order}")
    if len(target) != order:
        return checks
    if schema == 1 and name in EXPECTED_TARGETS:
        record("target_is_requested", tuple(target) == EXPECTED_TARGETS[name], target)
    if schema == 2:
        if name.endswith("_Uniform"):
            record(
                "target_is_requested",
                all(abs(t - 1.0 / order) < 1e-12 for t in target),
                "uniform over the order",
            )
        listed = json.loads(row["probabilities"])
        record(
            "manifest_probabilities_match_metadata",
            len(listed) == order
            and all(abs(a - b) < 1e-6 for a, b in zip(listed, target, strict=False)),
            row["probabilities"],
        )
        entropy = -sum(t * math.log2(t) for t in target if t > 0)
        record(
            "entropy_target_matches_probabilities",
            abs(float(row["entropy_target_bits"]) - entropy) < 1e-5,
            f"{row['entropy_target_bits']} vs {entropy:.6f}",
        )
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
        indices[:512].count(0) == indices[:512].count(order - 1) == 256,
        f"256 of each outer level, indices 0 and {order - 1}",
    )
    training = TRAINING_SYMBOLS[order]
    head = PREAMBLE_SYMBOLS + training
    record(
        "head_multiple_of_1024",
        head % 1024 == 0 and start == head,
        f"head {head}, payload at {start}",
    )
    block = indices[PREAMBLE_SYMBOLS:head]
    record(
        "training_balanced_per_level",
        len(block) == training and all(block.count(k) == training // order for k in range(order)),
        f"{training // order} of each of {order} levels",
    )
    if schema == 2:
        record(
            "head_symbols_manifest",
            int(row["head_symbols"]) == head
            and int(row["preamble_symbols"]) == PREAMBLE_SYMBOLS
            and int(row["training_symbols"]) == training,
            f"{row['head_symbols']} vs {head}",
        )

    full_scale = metadata["dac_normalization"]["full_scale_levels"]
    if schema == 2:
        spacing = float(row["level_spacing_full_scale"])
        step = float(row["dac_codes_per_level_step"])
        record(
            "level_spacing_and_dac_step",
            abs(spacing - 2.0 / full_scale) < 1e-8 and abs(step - spacing * DAC_HALF_STEPS) < 1e-5,
            f"spacing {spacing}, {step} codes per level step",
        )
    offset = metadata["symbol_centre_offset_samples"]
    if metadata["pulse"]["shape"] == "nrz":
        position = int(offset)
        recovered = []
        for k in range(symbols_n):
            value = samples[k * sps + position] * full_scale
            recovered.append(min(range(order), key=lambda s: abs(levels_table[s] - value)))
        errors = sum(a != b for a, b in zip(recovered, indices, strict=True))
        record("noise_free_reconstruction", errors == 0, f"{errors} symbol errors")
    else:
        response = rrc_frequency_response(len(samples), sps, metadata["pulse"]["roll_off"])
        spectrum = np.fft.fft(np.array(samples)) * response
        filtered = np.fft.ifft(spectrum).real[::sps] * full_scale
        recovered = [
            min(range(order), key=lambda s: abs(levels_table[s] - v)) for v in filtered.tolist()
        ]
        errors = sum(a != b for a, b in zip(recovered, indices, strict=True))
        record("noise_free_reconstruction", errors == 0, f"{errors} symbol errors, RRC filtered")

    bits_text = (reference_dir / f"{name}_info_bits.txt").read_text().strip()
    blocks = metadata["frame"]["matcher_blocks"]
    length = metadata["frame"]["matcher_block_length"]
    per_block = metadata["frame"]["bits_per_block"]
    counts = metadata["frame"]["matcher_composition"]
    record("info_bit_count", len(bits_text) == blocks * per_block, len(bits_text))
    if counts is None:
        record(
            "matcher_rate",
            per_block == bits * length,
            f"direct Gray mapping, {bits} bits per symbol",
        )
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
    """Validate a profile folder, including its checksum list, and write the results CSV.

    The manifest schema must be exactly a known one (v1: the 40 PAM4 columns; v2: the M-PAM
    columns). An unknown schema, or a v2 manifest with a wrong column list or version, fails
    with one `manifest_schema_known` check and nothing else is evaluated.
    """
    with (folder / "experiment_manifest.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    schema = manifest_schema(None if fieldnames is None else list(fieldnames), rows)
    results: list[Check] = []
    if schema is None:
        results.append(
            Check(
                "experiment_manifest.csv",
                "manifest_schema_known",
                False,
                f"unknown manifest schema ({0 if fieldnames is None else len(fieldnames)} columns)",
            )
        )
    else:
        for row in rows:
            results.extend(validate_waveform(folder, row, expected_header, schema))
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
