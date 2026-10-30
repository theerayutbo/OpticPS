"""Generate M8199B waveform CSVs, reference data, manifests and checksums."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from opticps import __version__
from opticps.instruments.m8199b import DATA_OUTPUTS, MAX_SAMPLES, Profile
from opticps.modulation.pam import pam_levels
from opticps.optimization.adaptive import Selection, design_point_selection
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    entropy_bits,
    lambda_of_symmetric_pam4,
)
from opticps.transmitter.frame import Frame, build_frame
from opticps.transmitter.pulse import PulseConfig, peak_factor, shape, symbol_centre_offset

REQUIRED_WAVEFORMS = ("PAM4_Uniform", "PAM4_Fixed_PS70", "PAM4_Fixed_PS80", "PAM4_Adaptive")
BENCHMARK_WAVEFORMS = ("PAM4_Fixed_Outer70",)

MANIFEST_COLUMNS = [
    "experiment_id", "role", "waveform_filename", "data_out", "modulation", "shaping_mode",
    "lambda", "probability_minus3", "probability_minus1", "probability_plus1",
    "probability_plus3", "realised_probability_minus3", "realised_probability_minus1",
    "realised_probability_plus1", "realised_probability_plus3", "symbol_rate_Bd",
    "sample_rate_Sa_per_s", "samples_per_symbol", "number_of_symbols", "preamble_symbols",
    "training_symbols", "payload_symbols", "number_of_samples", "waveform_duration_s",
    "symbol_entropy_bits", "distribution_matcher_rate", "distribution_matcher_rate_loss",
    "payload_information_bits", "nominal_information_rate_bps",
    "actual_net_payload_rate_bps", "pulse_shape", "amplitude_scale", "waveform_peak",
    "waveform_rms", "waveform_papr_db", "waveform_mean", "measured_or_simulated_source",
    "random_seed", "waveform_sha256", "reference_sha256",
]  # fmt: skip


@dataclass(frozen=True)
class Settings:
    """Settings shared by all profiles."""

    seed: int
    block_length: int
    pulse: PulseConfig
    data_out: str
    decimals: int
    adaptive: dict[str, Any]


def load_config(path: Path) -> tuple[Settings, list[Profile], str]:
    """Read the profile YAML; returns settings, profiles and the config hash."""
    raw = path.read_bytes()
    config = yaml.safe_load(raw)
    common = config["common"]
    if common["data_out"] not in DATA_OUTPUTS:
        raise ValueError(f"data_out must be one of {DATA_OUTPUTS}")
    settings = Settings(
        seed=int(common["seed"]),
        block_length=int(common["block_length"]),
        pulse=PulseConfig(**common["pulse"]),
        data_out=common["data_out"],
        decimals=int(common["decimals"]),
        adaptive=common["adaptive"],
    )
    profiles = [
        Profile(
            name, float(p["sample_rate_Sa_per_s"]), float(p["symbol_rate_Bd"]), int(p["symbols"])
        )
        for name, p in config["profiles"].items()
    ]
    return settings, profiles, hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def full_scale(sps: int, pulse: PulseConfig) -> float:
    """Return the data-independent full scale, common to every waveform of a group."""
    return 3.0 * peak_factor(sps, pulse)


def synthesize(frame: Frame, sps: int, pulse: PulseConfig, decimals: int) -> NDArray[np.float64]:
    """Return canonical normalized samples. Raises rather than clips."""
    levels = pam_levels(4)[frame.indices]
    samples = np.round(shape(levels, sps, pulse) / full_scale(sps, pulse), decimals) + 0.0
    if not np.all(np.isfinite(samples)):
        raise ValueError("Waveform contains non-finite samples")
    peak = float(np.abs(samples).max())
    if peak > 1.0:
        raise ValueError(f"Waveform peak {peak} exceeds full scale; refusing to clip")
    if samples.size > MAX_SAMPLES:
        raise ValueError(f"{samples.size} samples exceed {MAX_SAMPLES}")
    return samples


def write_waveform_csv(
    path: Path, samples: NDArray[np.float64], data_out: str, decimals: int
) -> None:
    """Write the M8199B CSV: one header row, then one sample per row."""
    if data_out not in DATA_OUTPUTS:
        raise ValueError(f"Unknown data output {data_out!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{value:.{decimals}f}" for value in samples.tolist())
    path.write_text(f"{data_out}\n{body}\n", newline="\n")


def dac_quantize(samples: NDArray[np.float64], bits: int = 8) -> NDArray[np.float64]:
    """Simulate a uniform mid-tread DAC. An assumption: the real code map is unverified."""
    half_steps = 2**bits / 2 - 1
    return np.round(np.clip(samples, -1, 1) * half_steps) / half_steps


def _write_references(
    folder: Path, name: str, frame: Frame, metadata: dict[str, Any]
) -> dict[str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    symbols_path = folder / f"{name}_symbols.csv"
    levels = pam_levels(4)[frame.indices].astype(int)
    rows = "\n".join(
        f"{i},{index},{level:+d}"
        for i, (index, level) in enumerate(
            zip(frame.indices.tolist(), levels.tolist(), strict=False)
        )
    )
    symbols_path.write_text(f"position,symbol_index,level\n{rows}\n", newline="\n")
    bits_path = folder / f"{name}_info_bits.txt"
    bits_path.write_text("".join(map(str, frame.info_bits.tolist())) + "\n", newline="\n")
    checksums = {
        symbols_path.name: sha256_file(symbols_path),
        bits_path.name: sha256_file(bits_path),
    }
    metadata["reference_checksums"] = checksums
    meta_path = folder / f"{name}_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", newline="\n")
    return {**checksums, meta_path.name: sha256_file(meta_path)}


def waveform_definitions(selection: Selection) -> dict[str, dict[str, Any]]:
    """Return the target distribution and label of each waveform."""
    return {
        "PAM4_Uniform": {"p": UNIFORM, "mode": "uniform", "direct": True},
        "PAM4_Fixed_PS70": {"p": PS70, "mode": "fixed-inner-heavy", "direct": False},
        "PAM4_Fixed_PS80": {"p": PS80, "mode": "fixed-inner-heavy", "direct": False},
        "PAM4_Adaptive": {
            "p": tuple(selection.probabilities),
            "mode": "adaptive-simulation-optimized",
            "direct": False,
        },
        "PAM4_Fixed_Outer70": {"p": OUTER70, "mode": "fixed-outer-heavy", "direct": False},
    }


def generate_profile(
    profile: Profile,
    settings: Settings,
    selection: Selection,
    config_hash: str,
    root: Path,
) -> list[dict[str, Any]]:
    """Generate all waveforms of one profile and return manifest rows."""
    profile.check()
    folder = root / profile.name
    sps = profile.sps
    definitions = waveform_definitions(selection)
    rows: list[dict[str, Any]] = []
    checksums: dict[str, str] = {}
    scale = full_scale(sps, settings.pulse)
    for name in REQUIRED_WAVEFORMS + BENCHMARK_WAVEFORMS:
        spec = definitions[name]
        frame = build_frame(
            name, spec["p"], profile.symbols, settings.seed, settings.block_length, spec["direct"]
        )
        samples = synthesize(frame, sps, settings.pulse, settings.decimals)
        role = "required" if name in REQUIRED_WAVEFORMS else "benchmark"
        relative = (
            f"waveforms/{name}.csv" if role == "required" else f"waveforms/benchmark/{name}.csv"
        )
        wave_path = folder / relative
        write_waveform_csv(wave_path, samples, settings.data_out, settings.decimals)
        waveform_hash = sha256_file(wave_path)

        payload = frame.payload_indices
        realised = np.bincount(payload, minlength=4) / payload.size
        target = [float(x) for x in spec["p"]]
        p0 = target[0]
        lam = 0.0 if name == "PAM4_Uniform" else lambda_of_symmetric_pam4(p0)
        entropy = entropy_bits(realised)
        payload_bits = int(frame.info_bits.size)
        rms = float(np.sqrt(np.mean(samples**2)))
        peak = float(np.abs(samples).max())
        experiment_id = f"OPS-{profile.name}-{name}-{config_hash[:8]}"
        metadata: dict[str, Any] = {
            "experiment_id": experiment_id,
            "generator": {"package": "opticps", "version": __version__},
            "config_sha256": config_hash,
            "instrument": "Keysight M8199B (hardware playback not verified)",
            "source": "simulated/synthetic waveform; no measurement",
            "profile": asdict(profile),
            "samples_per_symbol": sps,
            "number_of_samples": samples.size,
            "waveform_duration_s": profile.duration_s,
            "random_seed": settings.seed,
            "pulse": asdict(settings.pulse),
            "symbol_centre_offset_samples": symbol_centre_offset(sps, settings.pulse),
            "dac_normalization": {
                "convention": "sample = level / full_scale; level in {-3,-1,+1,+3}",
                "full_scale_levels": scale,
                "csv_decimals": settings.decimals,
                "physical_voltage": "configured on the instrument, not encoded in this file",
            },
            "frame": {
                "preamble": [0, 512],
                "training": [512, 1024],
                "payload": [frame.payload_start, profile.symbols],
                "preamble_definition": (
                    "511-chip m-sequence x^9+x^5+1 at +/-3, plus 1 balance symbol"
                ),
                "matcher_block_length": frame.block_length,
                "matcher_blocks": frame.n_blocks,
                "bits_per_block": frame.bits_per_block,
                "matcher_composition": frame.matcher_counts,
            },
            "shaping": {
                "mode": spec["mode"],
                "target_probabilities": target,
                "realised_payload_probabilities": realised.tolist(),
                "lambda": lam,
                "shaping_strength_inner_mass": target[1] + target[2],
                "payload_entropy_bits": entropy,
                "fec": "none implemented",
                "pas": False,
            },
            "waveform_sha256": waveform_hash,
        }
        if name == "PAM4_Adaptive":
            metadata["adaptive_selection"] = {
                "label": "simulation-optimized; not adapted to any measurement",
                "source": selection.source,
                "objective": selection.objective,
            }
        files = _write_references(folder / "references" / name, name, frame, metadata)
        reference_hash = files[f"{name}_symbols.csv"]
        for filename, digest in files.items():
            checksums[f"references/{name}/{filename}"] = digest
        checksums[relative] = waveform_hash

        loss = (entropy - frame.distribution_matcher_rate) if not spec["direct"] else 0.0
        rows.append(
            {
                "experiment_id": experiment_id,
                "role": role,
                "waveform_filename": relative,
                "data_out": settings.data_out,
                "modulation": "PAM4",
                "shaping_mode": spec["mode"],
                "lambda": f"{lam:.6f}",
                **dict(zip(MANIFEST_COLUMNS[7:11], (f"{x:.6f}" for x in target), strict=False)),
                **dict(zip(MANIFEST_COLUMNS[11:15], (f"{x:.6f}" for x in realised), strict=False)),
                "symbol_rate_Bd": f"{profile.symbol_rate:.0f}",
                "sample_rate_Sa_per_s": f"{profile.sample_rate:.0f}",
                "samples_per_symbol": sps,
                "number_of_symbols": profile.symbols,
                "preamble_symbols": 512,
                "training_symbols": 512,
                "payload_symbols": payload.size,
                "number_of_samples": samples.size,
                "waveform_duration_s": f"{profile.duration_s:.12e}",
                "symbol_entropy_bits": f"{entropy:.6f}",
                "distribution_matcher_rate": f"{frame.distribution_matcher_rate:.6f}",
                "distribution_matcher_rate_loss": f"{loss:.6f}",
                "payload_information_bits": payload_bits,
                "nominal_information_rate_bps": f"{2 * profile.symbol_rate:.0f}",
                "actual_net_payload_rate_bps": f"{payload_bits / profile.duration_s:.0f}",
                "pulse_shape": settings.pulse.shape,
                "amplitude_scale": f"{1 / scale:.9f}",
                "waveform_peak": f"{peak:.9f}",
                "waveform_rms": f"{rms:.9f}",
                "waveform_papr_db": f"{20 * np.log10(peak / rms):.4f}",
                "waveform_mean": f"{float(samples.mean()):.3e}",
                "measured_or_simulated_source": "simulated",
                "random_seed": settings.seed,
                "waveform_sha256": waveform_hash,
                "reference_sha256": reference_hash,
            }
        )
    with (folder / "experiment_manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    checksums["experiment_manifest.csv"] = sha256_file(folder / "experiment_manifest.csv")
    lines = [f"{digest}  {name}" for name, digest in sorted(checksums.items())]
    (folder / "checksums.sha256").write_text("\n".join(lines) + "\n", newline="\n")
    return rows


def generate_all(config_path: Path, root: Path) -> tuple[Settings, list[Profile], Selection]:
    """Select the adaptive distribution once, then generate every profile."""
    settings, profiles, config_hash = load_config(config_path)
    adaptive = settings.adaptive
    psnr_db, selection = design_point_selection(
        float(adaptive["design_rate_bpcu"]),
        adaptive["metric"],
        int(adaptive["training_samples"]),
        settings.seed,
        settings.block_length,
        float(adaptive["grid_step"]),
    )
    root.mkdir(parents=True, exist_ok=True)
    record = {"design_psnr_db": psnr_db, **selection.to_dict()}
    (root / "adaptive_selection.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", newline="\n"
    )
    for profile in profiles:
        generate_profile(profile, settings, selection, config_hash, root)
    return settings, profiles, selection
