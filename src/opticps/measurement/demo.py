"""Reproducible simulated demonstration. Results here are never experimental."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import hashlib
import json
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from opticps import __version__
from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.measurement.compare import match_uniform_rate
from opticps.modulation.pam import pam_levels
from opticps.optical_channel.link import LinkConfig, transmit, watt_to_dbm
from opticps.optimization.adaptive import assert_disjoint, select_distribution
from opticps.optimization.rates import (
    achievable_rates,
    gaussian_rates,
    noise_sigma_from_psnr_db,
    optimal_outer_probability,
    psnr_for_rate,
)
from opticps.receiver.dsp import CaptureResult, process_capture
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    entropy_bits,
    maxwell_boltzmann,
    symmetric_pam4,
)
from opticps.statistics.intervals import bootstrap_interval, clopper_pearson
from opticps.statistics.intervals import paired_difference_interval as paired
from opticps.transmitter.frame import Frame, build_frame

BANNER = "SIMULATION RESULTS ONLY — NO SOUTHAMPTON MEASUREMENTS HAVE BEEN IMPORTED."


@dataclass(frozen=True)
class Waveform:
    """One compared waveform."""

    name: str
    label: str
    probabilities: tuple[float, ...]
    direct: bool = False


def waveforms(adaptive_p0: float) -> list[Waveform]:
    """Return the compared set, using the exported adaptive distribution."""
    return [
        Waveform("PAM4_Uniform", "Uniform", UNIFORM, True),
        Waveform("PAM4_Fixed_PS70", "PS70 (inner)", PS70),
        Waveform("PAM4_Fixed_PS80", "PS80 (inner)", PS80),
        Waveform("PAM4_Adaptive", "Adaptive", tuple(symmetric_pam4(adaptive_p0).tolist())),
        Waveform("PAM4_Fixed_Outer70", "Outer70", OUTER70),
    ]


def realised(frame: Frame) -> np.ndarray:
    """Return receiver priors: the design for direct Uniform, else the known composition."""
    if frame.matcher_counts is None:
        return np.full(4, 0.25)
    return np.bincount(frame.payload_indices, minlength=4) / frame.payload_indices.size


def nrz_wave(frame: Frame, oversampling: int) -> np.ndarray:
    """Return the normalized drive waveform on the simulation grid."""
    return np.repeat(pam_levels(4)[frame.indices] / 3.0, oversampling)


def run_link(
    frame: Frame, symbol_rate: float, link: LinkConfig, seed: int, oversampling: int, taps: int
) -> tuple[CaptureResult, Any]:
    """Simulate one capture and run the full receiver."""
    fs = symbol_rate * oversampling
    result = transmit(nrz_wave(frame, oversampling), fs, link, np.random.default_rng(seed))
    return (
        process_capture(result.current_a, fs, symbol_rate, frame, realised(frame), taps=taps),
        result,
    )


def summarize(runs: list[CaptureResult], rng: np.random.Generator) -> dict[str, Any]:
    """Pool error counts and bootstrap rates over independent runs."""
    symbols = sum(r.map.symbols for r in runs)
    bits = sum(r.map.bits for r in runs)
    symbol_errors = sum(r.map.symbol_errors for r in runs)
    bit_errors = sum(r.map.bit_errors for r in runs)
    md_errors = sum(r.minimum_distance.symbol_errors for r in runs)
    r_bmd = [r.map.r_bmd for r in runs]
    r_smd = [r.map.r_smd for r in runs]
    blocks = [b for r in runs for b in r.map.block_error_symbols]

    def mean_of(sample: Any) -> float:
        return float(np.mean(sample))

    return {
        "runs": len(runs),
        "symbols": symbols,
        "symbol_errors": symbol_errors,
        "ser": symbol_errors / symbols,
        "ser_ci95": clopper_pearson(symbol_errors, symbols),
        "ser_minimum_distance": md_errors / symbols,
        "bits": bits,
        "bit_errors": bit_errors,
        "ber": bit_errors / bits,
        "ber_ci95": clopper_pearson(bit_errors, bits),
        "enough_errors": symbol_errors >= 100,
        "r_smd": mean_of(r_smd),
        "r_smd_ci95": bootstrap_interval(r_smd, mean_of, rng, 1000),
        "r_bmd": mean_of(r_bmd),
        "r_bmd_ci95": bootstrap_interval(r_bmd, mean_of, rng, 1000),
        "r_bmd_runs": r_bmd,
        "snr_db": mean_of([r.map.snr_db for r in runs]),
        "block_failure_fraction": sum(b > 0 for b in blocks) / len(blocks),
    }


def theory_section(selected_p0: float) -> dict[str, Any]:
    """Compute deterministic rate curves."""
    psnr = np.arange(8.0, 28.01, 0.5)
    table = {"Uniform": UNIFORM, "PS70": PS70, "PS80": PS80, "Outer70": OUTER70}
    table["Adaptive"] = tuple(symmetric_pam4(selected_p0).tolist())
    curves = {
        name: {
            "smd": [achievable_rates(p, x).smd for x in psnr],
            "bmd": [achievable_rates(p, x).bmd for x in psnr],
        }
        for name, p in table.items()
    }
    p_star = [optimal_outer_probability(x, "bmd") for x in psnr]
    # Average-power view with no peak limit: noise set by symbol energy, not peak swing.
    snr_db = np.arange(4.0, 24.01, 0.5)
    average = {}
    means = np.arange(4, dtype=float)
    for name, p in table.items():
        centred = means - 1.5
        energy = float(np.asarray(p) @ centred**2)
        rates = []
        for snr in snr_db:
            sigma = np.sqrt(energy / 10 ** (snr / 10))
            rates.append(gaussian_rates(p, means, np.full(4, sigma)).smd)
        average[name] = rates
    outers = np.arange(0.05, 0.4951, 0.01)
    by_p0 = {
        str(x): [achievable_rates(symmetric_pam4(q), x).bmd for q in outers]
        for x in (12.0, 14.0, 16.0, 20.0)
    }
    lambdas = np.linspace(-0.35, 0.35, 57)
    block_lengths = [32, 64, 128, 256, 512, 1024, 2048, 4096, 16384, 65536]
    return {
        "psnr_db": psnr.tolist(),
        "rate_curves": curves,
        "optimal_p0_bmd": [a for a, _ in p_star],
        "optimal_rate_bmd": [b for _, b in p_star],
        "average_power_snr_db": snr_db.tolist(),
        "average_power_smd": average,
        "gmi_vs_p0": {"p_outer": outers.tolist(), "psnr": by_p0},
        "entropy_vs_lambda": {
            "lambda": lambdas.tolist(),
            "entropy": [entropy_bits(maxwell_boltzmann(x)) for x in lambdas],
            "p_outer": [float(maxwell_boltzmann(x)[0]) for x in lambdas],
        },
        "rate_loss": {
            "n": block_lengths,
            **{
                name: [
                    ConstantCompositionMatcher.from_probabilities(p, n).rate_loss
                    for n in block_lengths
                ]
                for name, p in (("PS70", PS70), ("PS80", PS80))
            },
        },
        "gain_at_1bpcu": {
            "uniform_smd_psnr_db": psnr_for_rate(UNIFORM, 1.0, "smd"),
            "uniform_bmd_psnr_db": psnr_for_rate(UNIFORM, 1.0, "bmd"),
            "outer70_smd_gain_db": psnr_for_rate(UNIFORM, 1.0, "smd")
            - psnr_for_rate(OUTER70, 1.0, "smd"),
            "outer70_bmd_gain_db": psnr_for_rate(UNIFORM, 1.0, "bmd")
            - psnr_for_rate(OUTER70, 1.0, "bmd"),
        },
    }


def awgn_section(
    wave_set: list[Waveform], frames: dict[str, Frame], psnrs: list[float], runs: int, seed: int
) -> dict[str, Any]:
    """Monte Carlo through the receiver chain on a peak-limited AWGN channel."""
    rng = np.random.default_rng([seed, 1])
    out: dict[str, Any] = {"psnr_db": psnrs, "curves": {}}
    for w in wave_set:
        frame = frames[w.name]
        levels = pam_levels(4)[frame.indices]
        points = []
        for psnr in psnrs:
            sigma = 2 * noise_sigma_from_psnr_db(psnr)
            results = []
            for _ in range(runs):
                noise = rng.normal(0.0, sigma, levels.size)
                results.append(
                    process_capture(
                        np.repeat(levels + noise, 8), 64e9, 8e9, frame, realised(frame), taps=1
                    )
                )
            point = summarize(results, rng)
            point["analytic_r_bmd"] = achievable_rates(w.probabilities, psnr).bmd
            points.append(point)
        out["curves"][w.label] = points
    return out


def link_for(cfg: dict[str, Any], profile: dict[str, Any], **extra: Any) -> LinkConfig:
    """Build a link from the demo configuration."""
    return LinkConfig(
        **cfg["link_defaults"],
        transmitter_bandwidth_hz=profile["transmitter_bandwidth_hz"],
        receiver_bandwidth_hz=profile["receiver_bandwidth_hz"],
        **extra,
    )


def _point_seed(*parts: int) -> int:
    """Return a stable seed; the same point and run share noise across waveforms."""
    return int(np.random.SeedSequence(parts).generate_state(1)[0])


def sweep(
    wave_set: list[Waveform],
    frames: dict[str, Frame],
    cfg: dict[str, Any],
    profile: dict[str, Any],
    links: list[dict[str, Any]],
    seed_tag: int,
) -> dict[str, Any]:
    """Sweep link settings. All waveforms at one point share a noise seed list (paired)."""
    rng = np.random.default_rng([cfg["seed"], seed_tag])
    out: dict[str, Any] = {}
    for w in wave_set:
        points = []
        for point_index, extra in enumerate(links):
            link = link_for(cfg, profile, **extra)
            captures = []
            powers = []
            for run in range(cfg["runs"]):
                capture, physical = run_link(
                    frames[w.name],
                    profile["symbol_rate_Bd"],
                    link,
                    _point_seed(cfg["seed"], seed_tag, point_index, run),
                    cfg["symbol_oversampling"],
                    cfg["equalizer_taps"],
                )
                captures.append(capture)
                powers.append(physical)
            point = summarize(captures, rng)
            first = powers[0]
            point.update(
                {
                    "link": extra,
                    "launch_dbm": watt_to_dbm(first.launch_power_w),
                    "received_dbm": watt_to_dbm(first.received_power_w),
                    "oma_dbm": watt_to_dbm(first.oma_launch_w),
                    "er_db": first.extinction_ratio_db,
                    "noise_rms_a": first.noise_rms_a,
                }
            )
            points.append(point)
        out[w.label] = points
    return out


def adaptive_section(
    wave_set: list[Waveform],
    frames: dict[str, Frame],
    cfg: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fit on training runs, then compare on held-out runs at each operating point."""
    rate = profile["symbol_rate_Bd"]
    oversampling = cfg["symbol_oversampling"]
    taps = cfg["equalizer_taps"]
    rng = np.random.default_rng([cfg["seed"], 77])
    out = []
    uniform = frames["PAM4_Uniform"]
    for point, attenuation in enumerate(cfg["adaptive_operating_attenuation_db"]):
        link = link_for(cfg, profile, extra_attenuation_db=float(attenuation))
        training_seeds = [1000 + 100 * point + k for k in range(4)]
        test_seeds = [5000 + 100 * point + k for k in range(cfg["runs"])]
        assert_disjoint(map(str, training_seeds), map(str, test_seeds))
        indices, values = [], []
        for seed in training_seeds:
            capture, _ = run_link(uniform, rate, link, seed, oversampling, taps)
            indices.append(uniform.indices)
            values.append(capture.symbols)
        selection = select_distribution(
            np.concatenate(indices),
            np.concatenate(values),
            source=f"simulated training at {attenuation} dB",
            block_length=1024,
            grid_step=0.01,
        )
        tuned = build_frame("adapt", selection.probabilities, profile["symbols"], cfg["seed"])
        rates: dict[str, list[float]] = {}
        contenders = {"Point-adaptive": tuned, **{w.label: frames[w.name] for w in wave_set}}
        for label, frame in contenders.items():
            rates[label] = [
                run_link(frame, rate, link, s, oversampling, taps)[0].map.r_bmd for s in test_seeds
            ]
        diffs = {}
        for key, label in (
            ("Uniform", "Uniform"),
            ("Outer70", "Outer70"),
            ("PS70", "PS70 (inner)"),
        ):
            mean, interval = paired(rates["Point-adaptive"], rates[label], rng)
            diffs[key] = {"mean": mean, "ci95": interval}
        out.append(
            {
                "attenuation_db": attenuation,
                "selected_p_outer": selection.p_outer,
                "selected_lambda": selection.lambda_value,
                "estimated_channel": selection.channel.__dict__,
                "candidates_evaluated": len(selection.candidates),
                "training_seeds": training_seeds,
                "test_seeds": test_seeds,
                "mean_r_bmd": {k: float(np.mean(v)) for k, v in rates.items()},
                "paired_difference": diffs,
            }
        )
    return out


def protocol_b_section(
    frames: dict[str, Frame], cfg: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    """Compare at equal net rate. The rate is R_s * bits per symbol; no FEC exists."""
    rate = profile["symbol_rate_Bd"]
    shaped = frames["PAM4_Fixed_Outer70"]
    target = shaped.distribution_matcher_rate * rate
    match = match_uniform_rate(target, rate, profile["symbols"], 28)
    result: dict[str, Any] = {"target_net_bps": target, "match": match.__dict__, "points": []}
    if not match.feasible or match.uniform_symbol_rate is None:
        return result
    uniform = frames["PAM4_Uniform"]
    for attenuation in cfg["adaptive_operating_attenuation_db"]:
        link = link_for(cfg, profile, extra_attenuation_db=float(attenuation))
        row: dict[str, Any] = {"attenuation_db": attenuation}
        groups = (
            ("Uniform at matched baud", uniform, match.uniform_symbol_rate),
            ("PS70 (inner)", frames["PAM4_Fixed_PS70"], rate),
            ("Outer70", shaped, rate),
        )
        for label, frame, baud in groups:
            runs = [
                run_link(frame, baud, link, 9000 + s, cfg["symbol_oversampling"], 15)[0].map
                for s in range(cfg["runs"])
            ]
            errors = sum(r.symbol_errors for r in runs)
            total = sum(r.symbols for r in runs)
            row[label] = {
                "symbol_rate_Bd": baud,
                "ser": errors / total,
                "ser_ci95": clopper_pearson(errors, total),
                "r_bmd": float(np.mean([r.r_bmd for r in runs])),
                "air_gbps": float(np.mean([r.r_bmd for r in runs])) * baud / 1e9,
            }
        result["points"].append(row)
    return result


def run_demo(config_path: Path, selection_path: Path, out_dir: Path) -> dict[str, Any]:
    """Run everything and save results with the configuration hash."""
    raw = config_path.read_bytes()
    cfg = yaml.safe_load(raw)
    start = time.time()
    selected = json.loads(selection_path.read_text())
    wave_set = waveforms(selected["p_outer"])
    seed = cfg["seed"]
    results: dict[str, Any] = {
        "banner": BANNER,
        "data_source": "simulated",
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "software_version": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "seed": seed,
        "adaptive_export": {
            k: selected[k] for k in ("p_outer", "lambda_value", "objective", "source")
        }
        | {"design_psnr_db": selected["design_psnr_db"]},
        "waveforms": [w.__dict__ for w in wave_set],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = out_dir / "demo_results.partial.json"

    def save_checkpoint() -> None:
        checkpoint.write_text(json.dumps(results, indent=1, default=float) + "\n")

    results["theory"] = theory_section(selected["p_outer"])
    save_checkpoint()
    sets = {}
    for key in ("profile_A", "profile_B"):
        profile = cfg[key]
        frames = {
            w.name: build_frame(w.name, w.probabilities, profile["symbols"], seed, 1024, w.direct)
            for w in wave_set
        }
        sets[key] = frames
    results["awgn"] = awgn_section(
        wave_set, sets["profile_A"], cfg["awgn_psnr_db"], max(4, cfg["runs"] // 2), seed
    )
    save_checkpoint()
    for tag, key in enumerate(("profile_A", "profile_B"), start=10):
        profile = cfg[key]
        links = [{"extra_attenuation_db": float(a)} for a in profile["attenuation_db"]]
        fiber = [
            {
                "extra_attenuation_db": float(profile["fiber_extra_attenuation_db"]),
                "fiber_length_km": float(x),
            }
            for x in profile["fiber_km"]
        ]
        results[key] = {
            "symbol_rate_Bd": profile["symbol_rate_Bd"],
            "back_to_back": sweep(wave_set, sets[key], cfg, profile, links, tag),
            "fiber": sweep(wave_set, sets[key], cfg, profile, fiber, tag + 10),
        }
        save_checkpoint()
    results["adaptive_held_out"] = adaptive_section(
        wave_set, sets["profile_A"], cfg, cfg["profile_A"]
    )
    save_checkpoint()
    results["protocol_b"] = protocol_b_section(sets["profile_A"], cfg, cfg["profile_A"])
    results["runtime_s"] = time.time() - start
    checkpoint.unlink()
    (out_dir / "demo_results.json").write_text(json.dumps(results, indent=1, default=float) + "\n")
    with (out_dir / "demo_points.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "source",
                "profile",
                "sweep",
                "waveform",
                "received_dBm",
                "fiber_km",
                "ser",
                "ber",
                "symbol_errors",
                "r_smd",
                "r_bmd",
                "snr_db",
            ]  # fmt: skip
        )
        for key in ("profile_A", "profile_B"):
            for sweep_name in ("back_to_back", "fiber"):
                for label, points in results[key][sweep_name].items():
                    for p in points:
                        writer.writerow(
                            [
                                "simulated",
                                key,
                                sweep_name,
                                label,
                                f"{p['received_dbm']:.3f}",
                                p["link"].get("fiber_length_km", 0),
                                p["ser"],
                                p["ber"],
                                p["symbol_errors"],
                                p["r_smd"],
                                p["r_bmd"],
                                p["snr_db"],
                            ]  # fmt: skip
                        )
    return results
