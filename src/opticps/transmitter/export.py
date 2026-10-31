"""Generate M8199B waveform CSVs, reference data, manifests and checksums."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
import zlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from opticps import __version__
from opticps.instruments.m8199b import (
    DAC_BITS,
    DATA_OUTPUTS,
    MAX_SAMPLES,
    M8199BConstraintError,
    Profile,
)
from opticps.modulation.pam import ModulationSpec, pam_levels
from opticps.optimization.adaptive import (
    STREAM_DIRICHLET_STARTS,
    STREAM_SIM_NOISE,
    STREAM_SIM_PAYLOAD,
    AcquisitionId,
    BaselineOverrideError,
    BestFixed,
    Selection,
    design_point_selection,
    select_on_acquisitions,
    simulate_acquisitions,
)
from opticps.optimization.constraints import FeasibilityStatus
from opticps.optimization.rates import psnr_for_rate
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    entropy_bits,
    lambda_of_symmetric_pam4,
)
from opticps.transmitter.frame import TRAINING_STREAM_KEY, Frame, build_frame
from opticps.transmitter.mpam_config import (
    CONFIG_SCHEMA_VERSION,
    MpamConfig,
    MpamProfile,
    check_frame_fit,
    dac_codes_per_level_step,
    load_mpam_config,
    pam4_uniform_rate_bps,
    rate_equalisation,
)
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


def full_scale(sps: int, pulse: PulseConfig, order: int = 4) -> float:
    """Return the data-independent full scale, common to every waveform of a group."""
    return (order - 1) * peak_factor(sps, pulse)


def synthesize(frame: Frame, sps: int, pulse: PulseConfig, decimals: int) -> NDArray[np.float64]:
    """Return canonical normalized samples. Raises rather than clips."""
    levels = pam_levels(frame.order)[frame.indices]
    samples = np.round(shape(levels, sps, pulse) / full_scale(sps, pulse, frame.order), decimals)
    samples = samples + 0.0
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
    levels = pam_levels(frame.order)[frame.indices].astype(int)
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


# ---------------------------------------------------------------------------------------
# M-PAM export (manifest schema v2). PAM4 keeps the v1 path above, byte for byte.
# ---------------------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION = 2
MPAM_ORDERS = (2, 8, 16)  # orders this generator writes; PAM4 uses generate_all
MPAM_PROTOCOLS = ("A", "B")
EVIDENCE = "simulated"  # every file written here is synthetic; the label is not a setting
SYNTHETIC_SOURCE = "simulated/synthetic waveform; no measurement"
MANIFEST_COLUMNS_V2 = [
    "manifest_schema_version", "experiment_id", "role", "reportable", "waveform_filename",
    "data_out", "modulation", "modulation_order", "bits_per_symbol", "protocol", "shaping_mode",
    "shaping_family", "shaping_parameter", "probabilities", "realised_probabilities",
    "entropy_target_bits", "symbol_entropy_bits", "constraint_protocol", "symbol_rate_Bd",
    "sample_rate_Sa_per_s", "samples_per_symbol", "number_of_symbols", "preamble_symbols",
    "training_symbols", "head_symbols", "payload_symbols", "number_of_samples",
    "waveform_duration_s", "distribution_matcher_rate", "distribution_matcher_rate_loss",
    "payload_information_bits", "nominal_information_rate_bps", "actual_net_payload_rate_bps",
    "level_spacing_full_scale", "dac_codes_per_level_step", "pulse_shape", "amplitude_scale",
    "waveform_peak", "waveform_rms", "waveform_papr_db", "waveform_mean", "evidence",
    "random_seed", "payload_stream_key", "training_stream_key", "waveform_sha256",
    "reference_sha256",
]  # fmt: skip


@dataclass(frozen=True)
class MpamWaveform:
    """One waveform of an M-PAM group: its PMF, how it is sent and how it is labelled."""

    name: str
    probabilities: tuple[float, ...]
    mode: str
    family: str
    parameter: str
    direct: bool
    role: str
    reportable: bool = True


@dataclass(frozen=True)
class OrderSelection:
    """Adaptive and best-fixed choices of one order, made on simulated training data only."""

    order: int
    design_psnr_db: float
    adaptive: Selection
    best: BestFixed
    training_ids: list[AcquisitionId]
    record: dict[str, Any]


def _is_uniform(p: object, order: int) -> bool:
    return bool(np.max(np.abs(np.asarray(p, dtype=float) - 1.0 / order)) <= 1e-12)


def select_for_order(config: MpamConfig, order: int) -> OrderSelection:
    """Choose the adaptive PMF and the best-fixed member for one order, on training data only.

    The design PSNR is the one at which the uniform PMF reaches `design_rate_bpcu[order]` under
    the configured metric; the training acquisitions are simulated noise realisations of one
    payload (stream keys are recorded in the returned record). The menu is the pinned one.
    """
    adaptive = config.adaptive
    metric = str(adaptive["metric"])
    rate = float(adaptive["design_rate_bpcu"][order])
    psnr_db = psnr_for_rate(np.full(order, 1.0 / order), rate, metric, order)
    samples = int(adaptive["training_samples"]) * order // 4
    train, _ = simulate_acquisitions(
        psnr_db, order, samples, config.seed, int(adaptive["training_acquisitions"]), 0
    )
    outcome = select_on_acquisitions(
        train,
        [],
        order,
        metric,
        config.block_length,
        config.seed,
        config.reported_fixed_menu(order),
    )
    record = {
        "design_psnr_db": psnr_db,
        "design_rate_bpcu": rate,
        "evidence": EVIDENCE,
        "stream_keys": {
            "simulated_payload": STREAM_SIM_PAYLOAD,
            "simulated_noise": STREAM_SIM_NOISE,
            "dirichlet_starts": STREAM_DIRICHLET_STARTS,
        },
        "seed": config.seed,
        "selection": outcome.selection.to_dict(),
        "best_fixed": outcome.best_fixed.to_dict(),
        "training_ids": [asdict(i) for i in outcome.training_ids],
    }
    return OrderSelection(
        order, psnr_db, outcome.selection, outcome.best_fixed, outcome.training_ids, record
    )


def require_reportable_baseline(config: MpamConfig, choice: OrderSelection, order: int) -> None:
    """Refuse a BestFixed that is not the reportable baseline of the pinned menu.

    Three independent conditions, all needed: the object says `reportable` (it is only set by
    `best_fixed` over the pinned menu), its order is this order, and it names a member of the
    pinned menu with exactly that member's PMF. A hand-built or replaced object, or one chosen
    from another menu, raises `BaselineOverrideError`; nothing is written.
    """
    best = choice.best
    pinned = config.reported_fixed_menu(order)
    problems = []
    if not best.reportable:
        problems.append(f"reportable is False ({best.reportable_reason})")
    if best.order != order or choice.order != order:
        problems.append(f"order {best.order}/{choice.order} is not PAM{order}")
    member = pinned.get(best.name)
    if member is None:
        problems.append(f"member {best.name!r} is not in the pinned menu {list(pinned)}")
    elif len(best.probabilities) != order or (
        max(abs(a - b) for a, b in zip(best.probabilities, member, strict=True)) > 1e-12
    ):
        problems.append(f"the PMF of {best.name!r} differs from the pinned one")
    if problems:
        raise BaselineOverrideError(
            f"PAM{order}_BestFixed is a required waveform and must be a reportable baseline: "
            + "; ".join(problems)
        )


def mpam_waveforms(
    config: MpamConfig, choice: OrderSelection | None, order: int
) -> list[MpamWaveform]:
    """The waveforms of one order: the pinned menu, the adaptive PMF and BestFixed.

    PAM2 has one symmetric PMF, the uniform, so it gets only PAM2_Uniform (choice is None).
    A BestFixed that is not the reportable baseline of the pinned menu is refused
    (`require_reportable_baseline`).
    """
    if choice is None:
        if order != 2:
            raise ValueError("a selection is required for M > 2")
        return [
            MpamWaveform("PAM2_Uniform", (0.5, 0.5), "uniform", "none", "none", True, "required")
        ]
    require_reportable_baseline(config, choice, order)
    top = float(np.log2(order))
    out: list[MpamWaveform] = []
    for name, p in config.reported_fixed_menu(order).items():
        if name.endswith("_Uniform"):
            out.append(MpamWaveform(name, tuple(p), "uniform", "none", "none", True, "required"))
            continue
        inner = "_Inner_" in name
        out.append(
            MpamWaveform(
                name,
                tuple(p),
                "fixed-inner-heavy" if inner else "fixed-outer-heavy",
                "maxwell_boltzmann_entropy_matched",
                f"entropy_deficit_bits={top - entropy_bits(p):.2f}",
                False,
                "required" if inner else "benchmark",
            )
        )
    pairs = [round(float(x), 6) for x in choice.adaptive.parameters["pair_probabilities"]]
    adaptive_p = tuple(choice.adaptive.probabilities)
    out.append(
        MpamWaveform(
            f"PAM{order}_Adaptive",
            adaptive_p,
            "adaptive-simulation-optimized",
            "symmetric_pairs",
            f"pairs={json.dumps(pairs)}",
            _is_uniform(adaptive_p, order),
            "required",
        )
    )
    best_p = tuple(choice.best.probabilities)
    out.append(
        MpamWaveform(
            f"PAM{order}_BestFixed",
            best_p,
            f"best-fixed-selected-on-training:{choice.best.name}",
            "fixed_menu_member",
            f"member={choice.best.name}",
            _is_uniform(best_p, order),
            "required",
        )
    )
    return out


def _json_list(values: Sequence[float]) -> str:
    return json.dumps([round(float(v), 6) for v in values])


def generate_mpam_profile(
    profile: MpamProfile,
    config: MpamConfig,
    choice: OrderSelection | None,
    root: Path,
) -> list[dict[str, Any]]:
    """Write one (profile, order) group of waveforms and return its v2 manifest rows."""
    order = profile.order
    if order not in MPAM_ORDERS:
        raise ValueError(f"generate_mpam_profile writes PAM{MPAM_ORDERS}; PAM4 uses generate_all")
    fit = check_frame_fit(order, profile, config.block_length)
    if fit.status is not FeasibilityStatus.FEASIBLE:
        raise M8199BConstraintError(f"INFEASIBLE: {fit.reason}")
    spec = ModulationSpec(order)
    legacy = profile.to_profile()
    legacy.check()
    folder = root / profile.name
    sps = profile.sps
    scale = full_scale(sps, config.pulse, order)
    step = dac_codes_per_level_step(order, scale)
    waveforms = mpam_waveforms(config, choice, order)
    selection_keys = {} if choice is None else choice.record["stream_keys"]
    # Every waveform's own PMF, shaped or not, against the direct uniform of its order.
    equalisation = {
        r["name"]: r
        for r in rate_equalisation(
            order, {wf.name: wf.probabilities for wf in waveforms}, profile.symbols, sps,
            config.block_length,
        )
    }  # fmt: skip
    # Protocol B matches realised rate: the same PMFs against one target across orders, the PAM4
    # uniform of this protocol. Protocol A fixes the symbol rate instead, so it has no such target.
    common_target = pam4_uniform_rate_bps(config, profile) if profile.protocol == "B" else None
    common = (
        {}
        if common_target is None
        else {
            r["name"]: r
            for r in rate_equalisation(
                order, {wf.name: wf.probabilities for wf in waveforms}, profile.symbols, sps,
                config.block_length, target_bps=common_target,
            )
        }
    )  # fmt: skip
    rows: list[dict[str, Any]] = []
    checksums: dict[str, str] = {}
    for wf in waveforms:
        frame = build_frame(
            wf.name,
            wf.probabilities,
            profile.symbols,
            config.seed,
            config.block_length,
            wf.direct,
            order,
        )
        samples = synthesize(frame, sps, config.pulse, config.decimals)
        relative = (
            f"waveforms/{wf.name}.csv"
            if wf.role == "required"
            else f"waveforms/benchmark/{wf.name}.csv"
        )
        wave_path = folder / relative
        write_waveform_csv(wave_path, samples, config.data_out, config.decimals)
        waveform_hash = sha256_file(wave_path)
        payload = frame.payload_indices
        realised = np.bincount(payload, minlength=order) / payload.size
        target = [float(x) for x in wf.probabilities]
        entropy = entropy_bits(realised)
        entropy_target = entropy_bits(target)
        payload_bits = int(frame.info_bits.size)
        loss = 0.0 if wf.direct else entropy_target - frame.distribution_matcher_rate
        rms = float(np.sqrt(np.mean(samples**2)))
        peak = float(np.abs(samples).max())
        payload_key = zlib.crc32(wf.name.encode())
        experiment_id = f"OPS-{profile.name}-{wf.name}-{config.sha256[:8]}"
        metadata: dict[str, Any] = {
            "experiment_id": experiment_id,
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "generator": {"package": "opticps", "version": __version__},
            "config_sha256": config.sha256,
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "instrument": "Keysight M8199B (hardware playback not verified)",
            "source": SYNTHETIC_SOURCE,
            "evidence": EVIDENCE,
            "modulation": spec.name,
            "modulation_order": order,
            "bits_per_symbol": spec.bits_per_symbol,
            "protocol": profile.protocol,
            "profile": asdict(legacy),
            "samples_per_symbol": sps,
            "number_of_samples": samples.size,
            "waveform_duration_s": legacy.duration_s,
            "random_seed": config.seed,
            "stream_keys": {
                "payload": payload_key,
                "training": TRAINING_STREAM_KEY,
                "selection": selection_keys,
            },
            "pulse": asdict(config.pulse),
            "symbol_centre_offset_samples": symbol_centre_offset(sps, config.pulse),
            "dac_normalization": {
                "convention": "sample = level / full_scale; level in the odd integers "
                f"-{order - 1}..{order - 1}",
                "full_scale_levels": scale,
                "level_spacing_full_scale": 2.0 / scale,
                "dac_bits": DAC_BITS,
                "dac_codes_per_level_step": step,
                "dac_code_map": "assumed uniform mid-tread; the instrument's code map is "
                "unverified",
                "csv_decimals": config.decimals,
                "physical_voltage": "configured on the instrument, not encoded in this file",
            },
            "frame": {
                "preamble": [0, spec.preamble_symbols],
                "training": [spec.preamble_symbols, spec.head_symbols],
                "head_symbols": spec.head_symbols,
                "payload": [frame.payload_start, profile.symbols],
                "preamble_definition": (
                    f"511-chip m-sequence x^9+x^5+1 on symbol indices 0 and {order - 1}, "
                    "plus 1 balance symbol"
                ),
                "training_per_level": spec.training_per_level,
                "matcher_block_length": frame.block_length,
                "matcher_blocks": frame.n_blocks,
                "bits_per_block": frame.bits_per_block,
                "matcher_composition": frame.matcher_counts,
            },
            "shaping": {
                "mode": wf.mode,
                "family": wf.family,
                "parameter": wf.parameter,
                "target_probabilities": target,
                "realised_payload_probabilities": realised.tolist(),
                "entropy_target_bits": entropy_target,
                "payload_entropy_bits": entropy,
                "constraint_protocol": config.constraint_protocol,
                "fec": "none implemented",
                "pas": False,
            },
            "rate_equalisation": equalisation[wf.name],
            "rate_equalisation_common_target": (
                "not applicable: Protocol A holds the symbol rate, not the bit rate"
                if common_target is None
                else {
                    "target": "PAM4 direct uniform of the same protocol, head included",
                    "target_bps": common_target,
                    **common[wf.name],
                }
            ),
            "waveform_sha256": waveform_hash,
        }
        if choice is not None and wf.name.endswith("_Adaptive"):
            metadata["adaptive_selection"] = {
                "label": "simulation-optimized; not adapted to any measurement",
                "source": choice.adaptive.source,
                "objective": choice.adaptive.objective,
                "claim": choice.adaptive.claim,
            }
        if choice is not None and wf.name.endswith("_BestFixed"):
            metadata["best_fixed"] = {
                "member": choice.best.name,
                "selected_on": choice.best.selected_on,
                "reportable": choice.best.reportable,
                "reportable_reason": choice.best.reportable_reason,
            }
        files = _write_references(folder / "references" / wf.name, wf.name, frame, metadata)
        for filename, digest in files.items():
            checksums[f"references/{wf.name}/{filename}"] = digest
        checksums[relative] = waveform_hash
        rows.append(
            {
                "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                "experiment_id": experiment_id,
                "role": wf.role,
                "reportable": str(wf.reportable).lower(),
                "waveform_filename": relative,
                "data_out": config.data_out,
                "modulation": spec.name,
                "modulation_order": order,
                "bits_per_symbol": spec.bits_per_symbol,
                "protocol": profile.protocol,
                "shaping_mode": wf.mode,
                "shaping_family": wf.family,
                "shaping_parameter": wf.parameter,
                "probabilities": _json_list(target),
                "realised_probabilities": _json_list(realised.tolist()),
                "entropy_target_bits": f"{entropy_target:.6f}",
                "symbol_entropy_bits": f"{entropy:.6f}",
                "constraint_protocol": config.constraint_protocol,
                "symbol_rate_Bd": f"{profile.symbol_rate:.0f}",
                "sample_rate_Sa_per_s": f"{profile.sample_rate:.0f}",
                "samples_per_symbol": sps,
                "number_of_symbols": profile.symbols,
                "preamble_symbols": spec.preamble_symbols,
                "training_symbols": spec.training_symbols,
                "head_symbols": spec.head_symbols,
                "payload_symbols": payload.size,
                "number_of_samples": samples.size,
                "waveform_duration_s": f"{legacy.duration_s:.12e}",
                "distribution_matcher_rate": f"{frame.distribution_matcher_rate:.6f}",
                "distribution_matcher_rate_loss": f"{loss:.6f}",
                "payload_information_bits": payload_bits,
                "nominal_information_rate_bps": f"{spec.bits_per_symbol * profile.symbol_rate:.0f}",
                "actual_net_payload_rate_bps": f"{payload_bits / legacy.duration_s:.0f}",
                "level_spacing_full_scale": f"{2.0 / scale:.9f}",
                "dac_codes_per_level_step": f"{step:.6f}",
                "pulse_shape": config.pulse.shape,
                "amplitude_scale": f"{1 / scale:.9f}",
                "waveform_peak": f"{peak:.9f}",
                "waveform_rms": f"{rms:.9f}",
                "waveform_papr_db": f"{20 * np.log10(peak / rms):.4f}",
                "waveform_mean": f"{float(samples.mean()):.3e}",
                "evidence": EVIDENCE,
                "random_seed": config.seed,
                "payload_stream_key": payload_key,
                "training_stream_key": TRAINING_STREAM_KEY,
                "waveform_sha256": waveform_hash,
                "reference_sha256": files[f"{wf.name}_symbols.csv"],
            }
        )
    with (folder / "experiment_manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, MANIFEST_COLUMNS_V2, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    checksums["experiment_manifest.csv"] = sha256_file(folder / "experiment_manifest.csv")
    lines = [f"{digest}  {name}" for name, digest in sorted(checksums.items())]
    (folder / "checksums.sha256").write_text("\n".join(lines) + "\n", newline="\n")
    return rows


def generate_mpam_all(
    config_path: Path,
    root: Path,
    orders: Sequence[int] = MPAM_ORDERS,
    protocols: Sequence[str] = ("A", "B"),
) -> dict[str, list[dict[str, Any]]]:
    """Generate every M-PAM profile of the given orders. Offline; no instrument is contacted.

    All frame-fit checks run first: if any profile is INFEASIBLE nothing is written and
    M8199BConstraintError lists them. The adaptive and best-fixed choices are made once per
    order and written to adaptive_selection_PAM{M}.json.
    """
    bad_orders = [o for o in orders if o not in MPAM_ORDERS]
    bad_protocols = [x for x in protocols if x not in MPAM_PROTOCOLS]
    if not orders or not protocols or bad_orders or bad_protocols:
        raise ValueError(
            f"orders must be a non-empty subset of {MPAM_ORDERS} (PAM4 is written by "
            f"generate_all) and protocols of {MPAM_PROTOCOLS}; got orders {tuple(orders)}, "
            f"protocols {tuple(protocols)}"
        )
    config = load_mpam_config(config_path)
    chosen = [p for p in config.profiles if p.order in orders and p.protocol in protocols]
    bad = [
        fit.reason
        for p in chosen
        if (fit := check_frame_fit(p.order, p, config.block_length)).status
        is not FeasibilityStatus.FEASIBLE
    ]
    if bad:
        raise M8199BConstraintError("INFEASIBLE: " + " | ".join(bad))
    root.mkdir(parents=True, exist_ok=True)
    choices: dict[int, OrderSelection | None] = {}
    for order in sorted({p.order for p in chosen}):
        if order == 2:
            choices[2] = None
            continue
        selected = select_for_order(config, order)
        choices[order] = selected
        (root / f"adaptive_selection_PAM{order}.json").write_text(
            json.dumps(selected.record, indent=2, sort_keys=True) + "\n", newline="\n"
        )
    return {p.name: generate_mpam_profile(p, config, choices[p.order], root) for p in chosen}
