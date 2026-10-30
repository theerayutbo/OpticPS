"""Receiver-agnostic capture format, strict validation and loading.

A capture is a pair of files: <id>.csv or <id>.npz holding the samples, and <id>.json
holding metadata. The receiver model is unknown, so nothing here is model specific.
Missing calibration is never guessed: unknown optional values stay null.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.optical_channel.fiber import ValueSource
from opticps.shaping.distributions import validate_probabilities
from opticps.transmitter.frame import Frame

SCHEMA_VERSION = "1.0"
SPLITS = ("training", "test")
SOURCES = ("measured", "simulated")
REQUIRED_FIELDS: dict[str, Any] = {
    "schema_version": str,
    "capture_id": str,
    "related_transmit_experiment_id": str,
    "run_id": str,
    "split": str,
    "data_source": str,
    "capture_timestamp": str,
    "receiver_instrument_model": str,
    "transmitter_instrument_model": str,
    "capture_sample_rate_Sa_per_s": (int, float),
    "symbol_rate_Bd": (int, float),
    "receiver_bandwidth_Hz": (int, float),
    "fiber_length_km": (int, float),
    "attenuation_dB": (int, float),
    "optical_received_power_dBm": (int, float),
    "symbol_probabilities": list,
    "units": dict,
}
NULLABLE_REQUIRED = ("optical_received_power_dBm",)  # key must be present; null = not measured
OPTIONAL_FIELDS = (
    "optical_launch_power_dBm",
    "oma_dBm",
    "extinction_ratio_dB",
    "awg_sample_rate_Sa_per_s",
    "electrical_amplitude_Vpp",
    "modulator_parameters",
    "calibration",
    "operator_notes",
    "fiber",
)
FIBER_FIELDS = (
    "fiber_type",
    "wavelength_nm",
    "attenuation_db_per_km",
    "dispersion_ps_per_nm_km",
    "attenuation_source",
    "dispersion_source",
)
# Checked against ValueSource when present; the slope tag is new, so older records may lack it.
FIBER_SOURCE_FIELDS = ("attenuation_source", "dispersion_source", "dispersion_slope_source")


class CaptureValidationError(ValueError):
    """A capture was rejected. The message lists every reason."""


def validate_metadata(metadata: dict[str, Any]) -> None:
    """Raise CaptureValidationError listing every problem found."""
    problems: list[str] = []
    for name, kind in REQUIRED_FIELDS.items():
        if name in NULLABLE_REQUIRED and name in metadata and metadata[name] is None:
            continue  # present and null: explicitly not measured, never guessed
        if name not in metadata or metadata[name] is None:
            problems.append(f"missing field {name}")
        elif not isinstance(metadata[name], kind) or isinstance(metadata[name], bool):
            problems.append(f"field {name} has the wrong type")
    if problems:
        raise CaptureValidationError("; ".join(problems))

    if metadata["schema_version"] != SCHEMA_VERSION:
        problems.append(f"unsupported schema version {metadata['schema_version']}")
    if metadata["split"] not in SPLITS:
        problems.append(f"split must be one of {SPLITS}")
    if metadata["data_source"] not in SOURCES:
        problems.append(f"data_source must be one of {SOURCES}")
    units = metadata["units"]
    if units.get("time") != "s" or units.get("voltage") != "V":
        problems.append(f"unknown physical units {units}; expected time s and voltage V")
    sample_rate = metadata["capture_sample_rate_Sa_per_s"]
    symbol_rate = metadata["symbol_rate_Bd"]
    if sample_rate <= 0 or symbol_rate <= 0:
        problems.append("sample rate and symbol rate must be positive")
    elif sample_rate < 2 * symbol_rate:
        problems.append("capture sample rate is below two samples per symbol")
    if metadata["receiver_bandwidth_Hz"] <= 0:
        problems.append("receiver bandwidth must be positive")
    elif sample_rate > 0 and metadata["receiver_bandwidth_Hz"] > sample_rate:
        problems.append("receiver bandwidth exceeds the sample rate")
    if metadata["fiber_length_km"] < 0 or metadata["attenuation_dB"] < 0:
        problems.append("fiber length and attenuation must be non-negative")
    received = metadata["optical_received_power_dBm"]
    if received is not None and not -80 <= received <= 30:
        problems.append("optical received power is outside a plausible range")
    fiber = metadata.get("fiber")
    if fiber is not None:
        if not isinstance(fiber, dict):
            problems.append("fiber must be an object (see FiberParameters.to_metadata)")
        else:
            problems.extend(f"fiber is missing {k}" for k in FIBER_FIELDS if fiber.get(k) is None)
            allowed = {source.value for source in ValueSource}
            problems.extend(
                f"fiber {k} {fiber[k]!r} is not one of {sorted(allowed)}"
                for k in FIBER_SOURCE_FIELDS
                if fiber.get(k) is not None
                and not (isinstance(fiber[k], str) and fiber[k] in allowed)
            )
            length = fiber.get("fiber_length_km")
            if length is not None and (
                isinstance(length, bool)
                or not isinstance(length, (int, float))
                or abs(length - metadata["fiber_length_km"]) > 1e-9
            ):
                problems.append(
                    f"fiber fiber_length_km {length!r} disagrees with top-level "
                    f"fiber_length_km {metadata['fiber_length_km']}"
                )
    launch = metadata.get("optical_launch_power_dBm")
    if launch is not None and received is not None and launch < received:
        problems.append("received power exceeds launch power")
    try:
        validate_probabilities(metadata["symbol_probabilities"], 4)
    except ValueError as error:
        hint = (
            "; renormalise the realised probabilities (divide by their sum) or use the design "
            "probability_* values from the manifest"
            if "sum to 1" in str(error)
            else ""
        )
        problems.append(f"invalid probabilities: {error}{hint}")
    try:
        datetime.fromisoformat(metadata["capture_timestamp"])
    except ValueError:
        problems.append("capture_timestamp is not ISO 8601")
    if problems:
        raise CaptureValidationError("; ".join(problems))


def read_samples(path: Path, metadata: dict[str, Any]) -> NDArray[np.float64]:
    """Read samples, checking any time axis against the declared sample rate."""
    if path.suffix == ".npz":
        with np.load(path, allow_pickle=False) as data:
            if "received_voltage_v" not in data:
                raise CaptureValidationError("NPZ needs an array named received_voltage_v")
            samples = np.asarray(data["received_voltage_v"], dtype=float)
    elif path.suffix == ".csv":
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            rows = np.array(list(reader), dtype=float)
        if header == ["received_time_s", "received_voltage_v"]:
            spacing = np.diff(rows[:, 0])
            expected = 1 / metadata["capture_sample_rate_Sa_per_s"]
            if spacing.size and np.max(np.abs(spacing - expected)) > 1e-3 * expected:
                raise CaptureValidationError("Time axis disagrees with capture sample rate")
            samples = rows[:, 1]
        elif header == ["sample_index", "received_voltage_v"]:
            if not np.array_equal(rows[:, 0], np.arange(rows.shape[0])):
                raise CaptureValidationError("Sample index is not contiguous from zero")
            samples = rows[:, 1]
        else:
            raise CaptureValidationError(f"Unknown capture columns {header}")
    else:
        raise CaptureValidationError(f"Unsupported capture format {path.suffix}")
    if samples.size == 0 or not np.all(np.isfinite(samples)):
        raise CaptureValidationError("Capture is empty or has non-finite samples")
    return samples


@dataclass(frozen=True)
class Capture:
    """One validated capture."""

    metadata: dict[str, Any]
    samples: NDArray[np.float64]


def load_capture(json_path: Path) -> Capture:
    """Load and validate one capture from its metadata file."""
    metadata = json.loads(json_path.read_text())
    validate_metadata(metadata)
    for suffix in (".csv", ".npz"):
        data_path = json_path.with_suffix(suffix)
        if data_path.exists():
            return Capture(metadata, read_samples(data_path, metadata))
    raise CaptureValidationError(f"No sample file next to {json_path.name}")


def load_reference(folder: Path, name: str) -> Frame:
    """Rebuild the transmitted frame from exported reference files only."""
    from opticps.modulation.pam import indices_to_bits

    metadata = json.loads((folder / f"{name}_metadata.json").read_text())
    with (folder / f"{name}_symbols.csv").open(newline="") as handle:
        indices = np.array([int(r["symbol_index"]) for r in csv.DictReader(handle)], dtype=np.int64)
    text = (folder / f"{name}_info_bits.txt").read_text().strip()
    frame = metadata["frame"]
    composition = frame["matcher_composition"]
    return Frame(
        indices=indices,
        info_bits=np.frombuffer(text.encode(), dtype=np.uint8).astype(np.int8) - ord("0"),
        label_bits=indices_to_bits(indices),
        payload_start=frame["payload"][0],
        block_length=frame["matcher_block_length"],
        n_blocks=frame["matcher_blocks"],
        bits_per_block=frame["bits_per_block"],
        matcher_counts=None if composition is None else tuple(composition),
    )
