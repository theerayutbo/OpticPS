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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.instruments.m8199b import GRANULARITY_SAMPLES, MAX_SAMPLES
from opticps.transmitter.export import MANIFEST_COLUMNS, MANIFEST_COLUMNS_V2
from opticps.transmitter.pulse import rrc_frequency_response

IID_SIGMA_LIMIT = 5.0
LEVELS = (-3, -1, 1, 3)  # PAM4; see levels_of for any order
KNOWN_ORDERS = (2, 4, 8, 16)
EVIDENCE_LABELS = ("simulated", "mock", "measured", "analytical")
CONSTRAINT_PROTOCOLS = (
    "fixed_peak",
    "fixed_average_optical_power",
    "fixed_OMA",
    "equal_realized_user_rate",
)
# The generator writes synthetic files only. A package whose `source` says so must carry the
# evidence label "simulated"; a measured, mock or analytical claim on it is a mislabel.
SYNTHETIC_SOURCE = "simulated/synthetic waveform; no measurement"
# Frame head, written out here and not read from the generator: 511-chip m-sequence plus one
# balance symbol on the outer levels, then training symbols balanced over the levels. The head
# is a multiple of 1024 symbols.
PREAMBLE_SYMBOLS = 512
TRAINING_SYMBOLS = {2: 512, 4: 512, 8: 1536, 16: 2560}
DAC_HALF_STEPS = 2**7 - 1  # 8-bit mid-tread map assumed by the generator; a diagnostic only
# Waveform scale tolerance, from the DAC step. One DAC code is 1 / DAC_HALF_STEPS of full scale;
# a sample that is off by more than half a code would be played as another code, so a deviation
# of more than half a code from level / full_scale is a scale error. The files are written to
# 9 decimals (error below 1e-9), so half a code (1/254 = 3.9e-3 of full scale) is a loose bound:
# it is the largest tolerance with a physical meaning, not a statement of the writer's accuracy.
SCALE_TOLERANCE = 0.5 / DAC_HALF_STEPS
# Protocol definitions (plan): A uses these symbol rates at any order; B is the 112 Gb/s label.
PROTOCOL_A_BAUD = (8.0e9, 56.0e9)
PROTOCOL_B_NOMINAL_BPS = 112.0e9
# The pinned best-fixed menu, held here so a consistently mislabelled package cannot pass:
# Maxwell-Boltzmann PMFs of entropy log2 M - 0.12 and log2 M - 0.28 bit, inner and outer side.
PINNED_DEFICITS = (0.12, 0.28)
# Requested targets, held here so a consistently mislabelled package cannot pass.
EXPECTED_TARGETS = {
    "PAM4_Uniform": (0.25, 0.25, 0.25, 0.25),
    "PAM4_Fixed_PS70": (0.15, 0.35, 0.35, 0.15),
    "PAM4_Fixed_PS80": (0.10, 0.40, 0.40, 0.10),
    "PAM4_Fixed_Outer70": (0.35, 0.15, 0.15, 0.35),
}
V1_NAMES = ("PAM4_Uniform", "PAM4_Fixed_PS70", "PAM4_Fixed_PS80", "PAM4_Adaptive",
            "PAM4_Fixed_Outer70")  # fmt: skip


@dataclass(frozen=True)
class Check:
    """One validation outcome."""

    waveform: str
    check: str
    passed: bool
    detail: str


Record = Callable[[str, bool, object], None]


def levels_of(order: int) -> tuple[int, ...]:
    """The odd-integer levels of PAM-M, lowest first: 2 i - (M - 1)."""
    return tuple(2 * i - (order - 1) for i in range(order))


def _entropy(p: list[float]) -> float:
    return -sum(x * math.log2(x) for x in p if x > 0)


def _mb_pmf(order: int, sign: int, entropy: float) -> list[float]:
    """Maxwell-Boltzmann PMF p_i proportional to exp(-sign * mu * x_i^2) of the given entropy.

    Written here from the definition (bisection on mu), not read from the generator.
    """
    levels = levels_of(order)

    def pmf(mu: float) -> list[float]:
        exponent = [-sign * mu * x * x for x in levels]
        top = max(exponent)
        weights = [math.exp(e - top) for e in exponent]
        total = sum(weights)
        return [w / total for w in weights]

    low, high = 0.0, 2.0
    for _ in range(200):
        mid = (low + high) / 2
        if _entropy(pmf(mid)) > entropy:
            low = mid
        else:
            high = mid
    return pmf((low + high) / 2)


def pinned_menu(order: int) -> dict[str, list[float]]:
    """The pinned best-fixed menu of an order, by name (M = 4 is the legacy table)."""
    if order == 4:
        return {name: list(p) for name, p in EXPECTED_TARGETS.items()}
    menu = {f"PAM{order}_Uniform": [1.0 / order] * order}
    top = math.log2(order)
    for sign, label in ((1, "Inner"), (-1, "Outer")):
        for deficit in PINNED_DEFICITS:
            menu[f"PAM{order}_Fixed_{label}_H{round(100 * (top - deficit))}"] = _mb_pmf(
                order, sign, top - deficit
            )
    return menu


def expected_names(schema: int, order: int) -> list[str]:
    """The waveform names a complete package of this schema and order holds."""
    if schema == 1:
        return list(V1_NAMES)
    if order == 2:
        return ["PAM2_Uniform"]
    return [*pinned_menu(order), f"PAM{order}_Adaptive", f"PAM{order}_BestFixed"]


def expected_preamble(order: int) -> list[int]:
    """The 512 preamble symbol indices: the 511-chip m-sequence x^9 + x^5 + 1 on indices
    0 and M - 1 (Fibonacci LFSR, all-ones start, output the last cell), then the balance symbol.
    """
    state = [1] * 9
    chips = []
    for _ in range(511):
        chips.append(state[8])
        state = [state[8] ^ state[4], *state[:8]]
    chips.append(0 if 2 * sum(chips) > len(chips) else 1)
    return [(order - 1) * c for c in chips]


def manifest_schema(fieldnames: list[str] | None, rows: list[dict[str, str]]) -> int | None:
    """Return the manifest schema (1 or 2), or None if it is not exactly a known one.

    Default-deny: version 1 is the original 40 columns and no version column; version 2 needs
    the exact v2 column list and every row to say "2". Either needs at least one row: a
    header-only manifest is not a package. Anything else, including a version this code has
    not seen, is None.
    """
    if fieldnames is None or not rows:
        return None
    if fieldnames == MANIFEST_COLUMNS:
        return 1
    if fieldnames == MANIFEST_COLUMNS_V2 and all(r["manifest_schema_version"] == "2" for r in rows):
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


def _close(a: float, b: float, absolute: float = 0.0, relative: float = 0.0) -> bool:
    return abs(a - b) <= absolute + relative * max(abs(a), abs(b))


def _all_close(a: list[float], b: list[float], absolute: float) -> bool:
    """Same length and every pair within `absolute`."""
    return len(a) == len(b) and all(_close(x, y, absolute) for x, y in zip(a, b, strict=True))


def _full_scale_expected(order: int, sps: int, pulse: dict[str, object]) -> float:
    """(M - 1) times the pulse peak factor: 1 for NRZ, else the generator's own factor."""
    if pulse["shape"] == "nrz":
        return float(order - 1)
    from opticps.transmitter.pulse import PulseConfig, peak_factor

    return (order - 1) * peak_factor(sps, PulseConfig(**pulse))  # type: ignore[arg-type]


def validate_waveform(
    folder: Path, row: dict[str, str], expected_header: str, schema: int = 1
) -> list[Check]:
    """Run every check on one manifest row (schema 1: PAM4; schema 2: any known order)."""
    name = Path(row["waveform_filename"]).stem
    checks: list[Check] = []

    def record(check: str, passed: bool, detail: object) -> None:
        checks.append(Check(name, check, bool(passed), str(detail)))

    try:
        order = 4 if schema == 1 else int(row["modulation_order"])
    except ValueError:
        record("modulation_order_known", False, f"order {row['modulation_order']!r}")
        return checks
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
        role = row["role"]
        flag = row["reportable"]
        record(
            "reportable",
            flag in ("true", "false") and (role != "required" or flag == "true"),
            f"role {role}, reportable {flag}",
        )

    wave_path = folder / row["waveform_filename"]
    try:
        header, samples = read_waveform(wave_path)
    except (ValueError, StopIteration, OSError) as error:
        record("csv_parse", False, error)
        return checks
    record("csv_parse", True, f"{len(samples)} rows")
    record("header_exact", header == expected_header, header)

    count = int(row["number_of_samples"])
    finite = all(math.isfinite(v) for v in samples)
    record("all_finite", finite, f"{len(samples)} samples")
    in_range = finite and all(-1.0 <= v <= 1.0 for v in samples)
    record(
        "range_within_unit",
        in_range,
        f"min {min(samples, default=0)} max {max(samples, default=0)}",
    )
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
    try:
        indices, levels = _read_symbols(symbol_path)
        metadata = json.loads((reference_dir / f"{name}_metadata.json").read_text())
        bits_text = (reference_dir / f"{name}_info_bits.txt").read_text().strip()
    except (OSError, ValueError, KeyError) as error:
        record("reference_files_readable", False, error)
        return checks
    record("reference_length", len(indices) * sps == len(samples), len(indices))
    record("number_of_symbols_match", symbols_n == len(indices), f"{symbols_n} vs {len(indices)}")
    record(
        "reference_levels",
        len(indices) == len(levels)
        and all(
            0 <= i < order and levels_table[i] == v for i, v in zip(indices, levels, strict=True)
        ),
        f"index-level map of PAM{order}",
    )
    record("waveform_sha256", _sha256(wave_path) == row["waveform_sha256"], row["waveform_sha256"])
    record("reference_sha256", _sha256(symbol_path) == row["reference_sha256"], "symbols file")

    try:
        _check_against_files(
            record, row, schema, order, name, samples, indices, metadata, bits_text, sps
        )
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as error:
        record("metadata_readable", False, f"{type(error).__name__}: {error}")
    return checks


def _check_against_files(
    record: Record,
    row: dict[str, str],
    schema: int,
    order: int,
    name: str,
    samples: list[float],
    indices: list[int],
    metadata: dict[str, Any],
    bits_text: str,
    sps: int,
) -> None:
    """Everything that needs the metadata: recomputed from the files, compared to the row."""
    bits = order.bit_length() - 1
    levels_table = levels_of(order)
    sample_rate = float(row["sample_rate_Sa_per_s"])
    symbol_rate = float(row["symbol_rate_Bd"])
    duration = len(samples) / sample_rate
    if schema == 2:
        record(
            "modulation_order_matches_metadata",
            metadata.get("modulation_order") == order
            and metadata.get("manifest_schema_version") == 2
            and metadata.get("evidence") == row["evidence"],
            f"metadata order {metadata.get('modulation_order')}, row order {order}",
        )
        evidence_row, evidence_meta = row["evidence"], metadata.get("evidence")
    else:
        evidence_row, evidence_meta = row["measured_or_simulated_source"], "simulated"
    record(
        "evidence_matches_source",
        metadata.get("source") == SYNTHETIC_SOURCE
        and evidence_row == "simulated"
        and evidence_meta == "simulated",
        f"source {metadata.get('source')!r}, evidence {evidence_row!r}",
    )

    # The head is fixed by the order; the payload starts after it. Computed here, not trusted.
    training = TRAINING_SYMBOLS[order]
    head = PREAMBLE_SYMBOLS + training
    start = head
    payload = indices[start:]
    realised = [payload.count(s) / len(payload) for s in range(order)]
    target = metadata["shaping"]["target_probabilities"]
    record("probability_vector_length", len(target) == order, f"{len(target)} for PAM{order}")
    if len(target) != order:
        return
    if schema == 1 and name in EXPECTED_TARGETS:
        record("target_is_requested", tuple(target) == EXPECTED_TARGETS[name], target)
    if schema == 2:
        _check_v2_target(record, row, order, name, target, metadata)
    listed_realised = _manifest_realised(row, schema, order)
    record(
        "realised_matches_manifest",
        listed_realised is not None and _all_close(listed_realised, realised, 1e-6),
        f"recomputed from the symbol file: {[round(x, 6) for x in realised]}",
    )
    record(
        "symbol_entropy_matches_realised",
        _close(float(row["symbol_entropy_bits"]), _entropy(realised), 1e-5),
        f"{row['symbol_entropy_bits']} vs {_entropy(realised):.6f}",
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
    record(
        "preamble_is_m_sequence",
        indices[:PREAMBLE_SYMBOLS] == expected_preamble(order),
        "511 chips of x^9+x^5+1 in order, then the balance symbol",
    )
    record(
        "head_multiple_of_1024",
        head % 1024 == 0 and metadata["frame"]["payload"][0] == head,
        f"head {head}, payload at {metadata['frame']['payload'][0]}",
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
    record(
        "payload_symbols_manifest",
        int(row["payload_symbols"]) == len(payload),
        f"{row['payload_symbols']} vs {len(payload)}",
    )

    pulse = metadata["pulse"]
    full_scale = _full_scale_expected(order, sps, pulse)
    record(
        "full_scale_expected",
        _close(float(metadata["dac_normalization"]["full_scale_levels"]), full_scale, 1e-9)
        and _close(float(row["amplitude_scale"]), 1.0 / full_scale, 2e-9),
        f"expected full scale {full_scale:g} level units",
    )
    if schema == 2:
        spacing = float(row["level_spacing_full_scale"])
        step = float(row["dac_codes_per_level_step"])
        record(
            "level_spacing_and_dac_step",
            abs(spacing - 2.0 / full_scale) < 1e-8 and abs(step - spacing * DAC_HALF_STEPS) < 1e-5,
            f"spacing {spacing}, {step} codes per level step",
        )
    peak = max(abs(v) for v in samples)
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    record(
        "waveform_statistics_manifest",
        _close(float(row["waveform_peak"]), peak, 2e-9)
        and _close(float(row["waveform_rms"]), rms, 2e-9),
        f"peak {peak:.9f}, rms {rms:.9f}",
    )
    geometry = sps > 0 and len(indices) * sps == len(samples)
    recovered: list[int] = []
    if not geometry:
        record("noise_free_reconstruction", False, "samples are not symbols x sps")
        record("waveform_scale", False, "samples are not symbols x sps")
    elif pulse["shape"] == "nrz":
        position = int(metadata["symbol_centre_offset_samples"])
        for k in range(len(indices)):
            value = samples[k * sps + position] * full_scale
            recovered.append(min(range(order), key=lambda s: abs(levels_table[s] - value)))
        errors = sum(a != b for a, b in zip(recovered, indices, strict=True))
        record("noise_free_reconstruction", errors == 0, f"{errors} symbol errors")
        worst_scale = max(
            abs(samples[k] - levels_table[indices[k // sps]] / full_scale)
            for k in range(len(samples))
        )
        record(
            "waveform_scale",
            worst_scale <= SCALE_TOLERANCE,
            f"max |sample - level / full scale| {worst_scale:.2e}, "
            f"tolerance half a DAC code {SCALE_TOLERANCE:.2e}",
        )
    else:
        response = rrc_frequency_response(len(samples), sps, pulse["roll_off"])
        spectrum = np.fft.fft(np.array(samples)) * response
        filtered = np.fft.ifft(spectrum).real[::sps] * full_scale
        recovered = [
            min(range(order), key=lambda s: abs(levels_table[s] - v)) for v in filtered.tolist()
        ]
        errors = sum(a != b for a, b in zip(recovered, indices, strict=True))
        record("noise_free_reconstruction", errors == 0, f"{errors} symbol errors, RRC filtered")
        deviation = (
            float(np.max(np.abs(filtered - np.array([levels_table[i] for i in indices]))))
            / full_scale
        )
        record(
            "waveform_scale",
            deviation <= SCALE_TOLERANCE,
            f"max matched-filter deviation {deviation:.2e}, tolerance {SCALE_TOLERANCE:.2e}",
        )

    blocks = metadata["frame"]["matcher_blocks"]
    length = metadata["frame"]["matcher_block_length"]
    per_block = metadata["frame"]["bits_per_block"]
    counts = metadata["frame"]["matcher_composition"]
    record("info_bit_count", len(bits_text) == blocks * per_block, len(bits_text))
    record(
        "payload_information_bits_manifest",
        int(row["payload_information_bits"]) == len(bits_text),
        f"{row['payload_information_bits']} vs {len(bits_text)} bits in the file",
    )
    record(
        "payload_blocks_cover_payload",
        blocks * length == len(payload),
        f"{blocks} blocks of {length} for {len(payload)} payload symbols",
    )
    if counts is None:
        matcher_rate = float(bits)
        record(
            "matcher_rate",
            per_block == bits * length,
            f"direct Gray mapping, {bits} bits per symbol",
        )
        loss = 0.0
    else:
        matcher = ConstantCompositionMatcher(counts)
        matcher_rate = matcher.k / matcher.n
        record("matcher_rate", matcher.k == per_block, f"k={matcher.k}, n={matcher.n}")
        composed = all(
            [payload[b * length : (b + 1) * length].count(s) for s in range(order)] == list(counts)
            for b in range(blocks)
        )
        record("block_composition", composed, f"every block holds the composition {counts}")
        if geometry:
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
        loss = _entropy(list(realised if schema == 1 else target)) - matcher_rate
    record(
        "matcher_rate_manifest",
        _close(float(row["distribution_matcher_rate"]), matcher_rate, 1e-6),
        f"{row['distribution_matcher_rate']} vs {matcher_rate:.6f}",
    )
    record(
        "matcher_loss_manifest",
        _close(float(row["distribution_matcher_rate_loss"]), loss, 1e-5),
        f"{row['distribution_matcher_rate_loss']} vs {loss:.6f}",
    )
    nominal = bits * sample_rate / sps
    net = len(bits_text) / duration
    record(
        "rates_manifest",
        _close(float(row["nominal_information_rate_bps"]), nominal, 0.0, 1e-9)
        and _close(float(row["actual_net_payload_rate_bps"]), net, 0.0, 1e-6),
        f"nominal {nominal:.0f} b/s, net {net:.0f} b/s recomputed",
    )
    if schema == 2:
        protocol = row["protocol"]
        protocol_ok = protocol == metadata.get("protocol") and (
            (protocol == "A" and any(_close(symbol_rate, r, 0.0, 1e-9) for r in PROTOCOL_A_BAUD))
            or (protocol == "B" and _close(nominal, PROTOCOL_B_NOMINAL_BPS, 0.0, 1e-6))
        )
        record(
            "protocol_consistent",
            protocol_ok,
            f"protocol {protocol}, {symbol_rate:g} Bd, nominal {nominal:g} b/s",
        )
        constraint = row["constraint_protocol"]
        record(
            "constraint_protocol_known",
            constraint in CONSTRAINT_PROTOCOLS
            and constraint == metadata["shaping"].get("constraint_protocol"),
            constraint,
        )


def _manifest_realised(row: dict[str, str], schema: int, order: int) -> list[float] | None:
    try:
        if schema == 1:
            return [float(row[c]) for c in MANIFEST_COLUMNS[11:15]]
        listed = json.loads(row["realised_probabilities"])
        return [float(x) for x in listed] if len(listed) == order else None
    except (ValueError, TypeError, KeyError):
        return None


def _check_v2_target(
    record: Record,
    row: dict[str, str],
    order: int,
    name: str,
    target: list[float],
    metadata: dict[str, Any],
) -> None:
    """The PMF of a v2 waveform must be the one its name (or its BestFixed member) requests."""
    menu = pinned_menu(order)
    listed = json.loads(row["probabilities"])
    record(
        "manifest_probabilities_match_metadata",
        _all_close(listed, target, 1e-6) and len(listed) == order,
        row["probabilities"],
    )
    entropy = _entropy(target)
    record(
        "entropy_target_matches_probabilities",
        abs(float(row["entropy_target_bits"]) - entropy) < 1e-5,
        f"{row['entropy_target_bits']} vs {entropy:.6f}",
    )
    if name in menu:
        record(
            "target_is_requested",
            _all_close(target, menu[name], 1e-6),
            f"{name} is the pinned PMF",
        )
    elif name == f"PAM{order}_BestFixed":
        member = row["shaping_parameter"].removeprefix("member=")
        best = metadata.get("best_fixed", {})
        record(
            "target_is_requested",
            row["shaping_parameter"].startswith("member=")
            and member in menu
            and _all_close(target, menu[member], 1e-6)
            and best.get("member") == member
            and best.get("reportable") is True,
            f"BestFixed member {member!r} of the pinned menu {list(menu)}, reportable "
            f"{best.get('reportable')}",
        )
    elif name == f"PAM{order}_Adaptive":
        record(
            "target_is_requested",
            _close(sum(target), 1.0, 1e-6)
            and all(_close(target[i], target[order - 1 - i], 1e-9) for i in range(order)),
            "a symmetric PMF",
        )
    else:
        record("target_is_requested", False, f"{name!r} is not a waveform of the PAM{order} set")


def validate_profile(folder: Path, expected_header: str = "DataOut1") -> list[Check]:
    """Validate a profile folder, including its checksum list, and write the results CSV.

    Default-deny. The manifest schema must be exactly a known one (v1: the 40 PAM4 columns; v2:
    the M-PAM columns) and hold at least one row; otherwise one `manifest_schema_known` check
    fails and nothing else is evaluated. For a known schema the rows must be exactly the
    waveforms of the package (`manifest_rows_complete`) and the checksum list must be present
    and cover every file (`checksum_list_complete`), so an empty list, a missing row or a
    header-only manifest cannot give zero failures.
    """
    results: list[Check] = []
    manifest_path = folder / "experiment_manifest.csv"
    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    if manifest_path.is_file():
        with manifest_path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fieldnames = None if reader.fieldnames is None else list(reader.fieldnames)
    schema = manifest_schema(fieldnames, rows)
    if schema is None:
        reason = (
            "no manifest file"
            if fieldnames is None and not manifest_path.is_file()
            else "no rows"
            if not rows
            else f"{0 if fieldnames is None else len(fieldnames)} columns"
        )
        results.append(
            Check(
                "experiment_manifest.csv",
                "manifest_schema_known",
                False,
                f"unknown manifest schema ({reason})",
            )
        )
    else:
        results.extend(_check_package(folder, rows, schema))
        for row in rows:
            results.extend(validate_waveform(folder, row, expected_header, schema))
        results.extend(_check_checksums(folder, rows))
    with (folder / "validation_results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["waveform", "check", "result", "detail"])
        for item in results:
            writer.writerow(
                [item.waveform, item.check, "PASS" if item.passed else "FAIL", item.detail]
            )
    return results


def _check_package(folder: Path, rows: list[dict[str, str]], schema: int) -> list[Check]:
    """Rows are exactly the waveforms of one order (and one protocol), no more, no fewer."""
    manifest = "experiment_manifest.csv"
    try:
        order = 4 if schema == 1 else int(rows[0]["modulation_order"])
    except ValueError:
        order = 0
    names = [Path(r["waveform_filename"]).stem for r in rows]
    if order not in KNOWN_ORDERS:
        return [Check(manifest, "manifest_rows_complete", False, f"order {order} unknown")]
    expected = expected_names(schema, order)
    single = len({r.get("modulation_order") for r in rows}) == 1 and (
        schema == 1 or len({r["protocol"] for r in rows}) == 1
    )
    ok = sorted(names) == sorted(expected) and single
    missing = sorted(set(expected) - set(names))
    extra = sorted(set(names) - set(expected))
    return [
        Check(
            manifest,
            "manifest_rows_complete",
            ok,
            f"{len(rows)} rows, {len(expected)} expected for PAM{order}; missing {missing}, "
            f"unexpected {extra}",
        )
    ]


def _check_checksums(folder: Path, rows: list[dict[str, str]]) -> list[Check]:
    """The checksum list exists, is not empty, covers every file and every entry matches."""
    results: list[Check] = []
    listing = folder / "checksums.sha256"
    entries: dict[str, str] = {}
    bad_lines = 0
    if listing.is_file():
        for line in listing.read_text().splitlines():
            digest, separator, relative = line.partition("  ")
            if not separator or len(digest) != 64 or not relative:
                bad_lines += 1
                continue
            entries[relative] = digest
    needed = {"experiment_manifest.csv"}
    for row in rows:
        name = Path(row["waveform_filename"]).stem
        needed.add(row["waveform_filename"])
        needed.update(
            f"references/{name}/{name}{suffix}"
            for suffix in ("_symbols.csv", "_info_bits.txt", "_metadata.json")
        )
    missing = sorted(needed - set(entries))
    results.append(
        Check(
            "checksums.sha256",
            "checksum_list_complete",
            bool(entries) and not missing and not bad_lines,
            f"{len(entries)} entries, {bad_lines} malformed lines, missing {missing[:3]}"
            + (" ..." if len(missing) > 3 else ""),
        )
    )
    for relative, digest in entries.items():
        path = folder / relative
        safe = not relative.startswith("/") and ".." not in Path(relative).parts
        ok = safe and path.is_file() and _sha256(path) == digest
        results.append(Check(relative, "checksum_file_entry", ok, digest[:16]))
    return results
