"""Validation of the fiber model against Rec. ITU-T G.652 (08/2024). Never experimental.

Three kinds of result are kept apart, and every figure says which it is:
analytical (evaluated from the Recommendation's equations and tables), simulated
(Monte Carlo through the link and receiver) and experimental (none exists).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from opticps import __version__
from opticps.measurement.demo import Waveform, sweep, waveforms
from opticps.optical_channel.fiber import (
    SOURCE_G652,
    ValueSource,
    g652d_attenuation_limit,
    g652d_dispersion_limits,
    g652d_preset,
    typical_attenuation,
    within_g652d_limits,
)
from opticps.optical_channel.link import (
    SPEED_OF_LIGHT,
    LinkConfig,
    beta3_s3_per_m,
    cd_null_frequency_hz,
    dispersive_field,
)
from opticps.transmitter.frame import build_frame

BANNER = (
    "SIMULATION AND SPECIFICATION ANALYSIS ONLY: NO MEASURED FIBER DATA. "
    "NOTHING HERE IS EXPERIMENTALLY VALIDATED."
)
PROFILES = ("profile_A", "profile_B")
PROFILE_TAG = {"profile_A": 10, "profile_B": 11}  # the demo's tags; its fiber sweep adds 10
COMPARED_FIELDS = (
    "ser",
    "ber",
    "symbol_errors",
    "bit_errors",
    "symbols",
    "r_bmd",
    "r_smd",
    "snr_db",
    "received_dbm",
    "launch_dbm",
)
COLORS = {"1550": "#1f4e79", "1310": "#c0504d"}
LABEL_STYLE = {"Uniform": "-", "Outer70": "--"}


def _describe(extra: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe description of the link settings of one sweep point."""
    link = LinkConfig(**extra)
    return {
        "extra_attenuation_db": link.extra_attenuation_db,
        "fiber_length_km": link.fiber_length_km,
        "fiber_type": link.fiber.fiber_type if link.fiber else "none (v1.0 defaults)",
        "wavelength_nm": link.wavelength_m * 1e9,
        "attenuation_db_per_km": link.attenuation_db_per_km,
        "dispersion_ps_per_nm_km": link.dispersion_ps_per_nm_km,
        "dispersion_slope_ps_per_nm2_km": link.dispersion_slope_ps_per_nm2_km,
    }


def _run(
    waves: list[Waveform],
    frames: dict[str, Any],
    demo: dict[str, Any],
    profile_key: str,
    extra_attenuation_db: float,
    lengths: list[float],
    fiber_settings: dict[str, Any],
    tag: int,
    runs: int | None = None,
) -> dict[str, Any]:
    """Run demo.sweep over fiber lengths with one set of fiber settings."""
    cfg = demo if runs is None else {**demo, "runs": runs}
    links = [
        {"extra_attenuation_db": float(extra_attenuation_db), "fiber_length_km": float(x)}
        | fiber_settings
        for x in lengths
    ]
    result = sweep(waves, frames, cfg, demo[profile_key], links, tag)
    for points in result.values():
        for point, extra in zip(points, links, strict=True):
            point["link"] = _describe(extra)
    return result


def analytical_curves(start: float, stop: float, step: float) -> dict[str, Any]:
    """Evaluate bounds and the representative curve over the G.652.D band."""
    wavelengths = [float(x) for x in np.arange(start, stop + step / 2, step)]
    rep = [g652d_preset(w) for w in wavelengths]
    bounds = [g652d_dispersion_limits(w) for w in wavelengths]
    return {
        "label": "analytical",
        "source": SOURCE_G652,
        "wavelength_nm": wavelengths,
        "attenuation_limit_db_per_km": [g652d_attenuation_limit(w) for w in wavelengths],
        "attenuation_typical_link_db_per_km": [typical_attenuation(w) for w in wavelengths],
        "dispersion_lower_ps_per_nm_km": [b[0] for b in bounds],
        "dispersion_upper_ps_per_nm_km": [b[1] for b in bounds],
        "dispersion_representative_ps_per_nm_km": [p.dispersion_ps_per_nm_km for p in rep],
        "slope_representative_ps_per_nm2_km": [p.dispersion_slope_ps_per_nm2_km for p in rep],
        "representative_within_limits": all(
            all(within_g652d_limits(replace(p, attenuation_db_per_km=0.0)).values()) for p in rep
        ),
        "typical_attenuation_exceeds_limit_at_nm": [
            w
            for w, p in zip(wavelengths, rep, strict=True)
            if not within_g652d_limits(p)["attenuation"]
        ][:1],
    }


def _modulation(config: LinkConfig, k: int, fs: float, n: int, depth: float) -> float:
    """Return the relative small-signal intensity modulation at bin k after the fiber."""
    f = k * fs / n
    t = np.arange(n) / fs
    field = np.sqrt(1 + depth * np.cos(2 * np.pi * f * t)) + 0j
    out = dispersive_field(field, fs, config)
    return float(np.abs(np.fft.rfft(np.abs(out) ** 2)[k]) * 2 / n / depth)


def simulated_null_hz(config: LinkConfig, n: int, depth: float) -> tuple[float, float]:
    """Find the first null of the simulated intensity response; return (null, resolution).

    The sample rate is a non-integer multiple of the theoretical null, so the theory value is
    not a grid point. The response is |cos|-shaped, so the null is located between the two
    grid points either side of the minimum by intersecting the two straight sides.
    """
    theory = cd_null_frequency_hz(config)
    fs = 16.4 * theory
    centre = theory * n / fs
    coarse = np.unique(np.round(np.linspace(0.6, 1.4, 161) * centre).astype(int))
    values = [_modulation(config, int(k), fs, n, depth) for k in coarse]
    best = int(coarse[int(np.argmin(values))])
    step = int(np.max(np.diff(coarse)))
    fine = range(max(2, best - step), best + step + 1)
    k_best = min(fine, key=lambda k: _modulation(config, k, fs, n, depth))
    left = _modulation(config, k_best - 1, fs, n, depth)
    right = _modulation(config, k_best + 1, fs, n, depth)
    return (k_best + (left - right) / (left + right)) * fs / n, fs / n


def numerical_validation(cfg: dict[str, Any], demo: dict[str, Any]) -> dict[str, Any]:
    """Compare the simulated dispersion null with theory, and size the slope effect."""
    settings = cfg["numerical"]
    n, depth, length = settings["samples"], settings["modulation_depth"], settings["fiber_km"]
    rows = []
    cases = [(w, "representative") for w in cfg["wavelengths_nm"]]
    cases += [(1550, "limit-low"), (1550, "limit-high")]
    for wavelength, variant in cases:
        fiber = g652d_preset(float(wavelength), variant)
        full = LinkConfig(fiber=fiber, fiber_length_km=float(length))
        flat = LinkConfig(
            wavelength_m=full.wavelength_m,
            dispersion_ps_per_nm_km=fiber.dispersion_ps_per_nm_km,
            fiber_length_km=float(length),
        )
        theory = cd_null_frequency_hz(full)
        simulated, resolution = simulated_null_hz(full, n, depth)
        simulated_flat, _ = simulated_null_hz(flat, n, depth)
        fs, half = 16.4 * theory, int(n / 32.8)
        with_slope = _modulation(full, half, fs, n, depth)
        without = _modulation(flat, half, fs, n, depth)
        rows.append(
            {
                "wavelength_nm": float(wavelength),
                "variant": variant,
                "fiber_km": float(length),
                "dispersion_ps_per_nm_km": fiber.dispersion_ps_per_nm_km,
                "theory_null_ghz": theory / 1e9,
                "simulated_null_ghz": simulated / 1e9,
                "relative_error": (simulated - theory) / theory,
                "grid_resolution_relative": resolution / theory,
                "null_with_slope_minus_without_ghz": (simulated - simulated_flat) / 1e9,
                "response_ratio_slope_over_flat_at_half_null": with_slope / without,
            }
        )
    third_order = []
    rep = g652d_preset(1550.0)
    for key in PROFILES:
        rate = demo[key]["symbol_rate_Bd"]
        length_km = float(max(cfg["length_sweep"][key]["fiber_km"]))
        omega = np.pi * rate  # Nyquist angular frequency, 2 pi (baud / 2)
        d = rep.dispersion_ps_per_nm_km * 1e-6
        s = rep.dispersion_slope_ps_per_nm2_km * 1e3
        beta2 = -d * 1550e-9**2 / (2 * np.pi * SPEED_OF_LIGHT)
        beta3 = beta3_s3_per_m(1550e-9, d, s)
        beta3_d_only = beta3_s3_per_m(1550e-9, d, 0.0)
        third_order.append(
            {
                "profile": key,
                "fiber_km": length_km,
                "symbol_rate_Bd": rate,
                "beta2_s2_per_m": beta2,
                "beta3_s3_per_m": beta3,
                "beta3_from_D_only_s3_per_m": beta3_d_only,
                "second_order_phase_rad": abs(0.5 * beta2 * length_km * 1e3 * omega**2),
                "third_order_phase_rad": beta3 * length_km * 1e3 * omega**3 / 6,
            }
        )
    return {
        "label": "simulated (small-signal tone through dispersive_field) against analytical",
        "method": "Intensity-modulation response of a DSB tone, first null by scan; "
        "theory f = sqrt(c / (2 lambda^2 |D| L)).",
        "samples": n,
        "modulation_depth": depth,
        "null_frequency": rows,
        "third_order_phase_at_nyquist": third_order,
    }


def reproduction_check(
    stored: dict[str, Any], rerun: dict[str, Any], profile_key: str
) -> dict[str, Any]:
    """Compare a re-run of the v1.0 fiber sweep with the saved v1.0 results, point by point."""
    total = same = 0
    mismatches = []
    for label, points in rerun.items():
        for old, new in zip(stored[profile_key]["fiber"][label], points, strict=True):
            total += 1
            equal = all(old[f] == new[f] for f in COMPARED_FIELDS)
            same += equal
            if not equal:
                mismatches.append(
                    {"waveform": label, "fiber_km": new["link"]["fiber_length_km"]}
                    | {f: [old[f], new[f]] for f in COMPARED_FIELDS if old[f] != new[f]}
                )
    return {"points_compared": total, "points_identical": same, "mismatches": mismatches}


def before_after(
    cfg: dict[str, Any],
    demo: dict[str, Any],
    stored: dict[str, Any],
    wave_set: list[Waveform],
    frames: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run v1.0 defaults and the 1550 nm G.652.D preset on the demo's own fiber sweep."""
    rep = g652d_preset(1550.0)
    arms = {
        "G.652.D attenuation only": {"attenuation_db_per_km": rep.attenuation_db_per_km},
        "G.652.D slope only": {
            "dispersion_slope_ps_per_nm2_km": rep.dispersion_slope_ps_per_nm2_km
        },
    }
    keep = set(cfg["before_after"]["attribution_waveforms"])
    reduced = [w for w in wave_set if w.name in keep]
    out: dict[str, Any] = {
        "label": "simulated",
        "design": "Same configs/demo.yaml, seed, runs, waveforms, frames and per-point noise "
        "seeds as the v1.0 fiber sweep; only the fiber description differs.",
        "preset": rep.to_metadata(),
    }
    for key in PROFILES:
        lengths = demo[key]["fiber_km"]
        extra = demo[key]["fiber_extra_attenuation_db"]
        tag = PROFILE_TAG[key] + 10
        v10 = _run(wave_set, frames[key], demo, key, extra, lengths, {}, tag)
        full = _run(wave_set, frames[key], demo, key, extra, lengths, {"fiber": rep}, tag)
        record: dict[str, Any] = {
            "reproduction": reproduction_check(stored, v10, key),
            "v1.0 defaults": v10,
            "G.652.D representative": full,
        }
        for name, settings in arms.items():
            record[name] = _run(reduced, frames[key], demo, key, extra, lengths, settings, tag)
        out[key] = record
    return out


def run_fiber_validation(config_path: Path, selection_path: Path, out_dir: Path) -> dict[str, Any]:
    """Run every analytical and simulated check and save fiber_results.json and figures."""
    raw = config_path.read_bytes()
    cfg = yaml.safe_load(raw)
    demo_raw = Path(cfg["demo_config"]).read_bytes()
    demo = yaml.safe_load(demo_raw)
    stored = json.loads(Path(cfg["demo_results"]).read_text())
    selected = json.loads(selection_path.read_text())
    wave_set = waveforms(selected["p_outer"])
    seed = demo["seed"]
    start = time.time()
    frames = {
        key: {
            w.name: build_frame(w.name, w.probabilities, demo[key]["symbols"], seed, 1024, w.direct)
            for w in wave_set
        }
        for key in PROFILES
    }
    results: dict[str, Any] = {
        "banner": BANNER,
        "data_source": "simulated",
        "experimentally_validated": False,
        "standard": SOURCE_G652,
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "demo_config_sha256": hashlib.sha256(demo_raw).hexdigest(),
        "software_version": __version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "seed": seed,
        "analytical": analytical_curves(
            cfg["curves"]["start_nm"], cfg["curves"]["stop_nm"], cfg["curves"]["step_nm"]
        ),
    }
    chosen = set(cfg["length_sweep"]["waveforms"])
    pair = [w for w in wave_set if w.name in chosen]
    sweeps: dict[str, Any] = {}
    for key in PROFILES:
        spec = cfg["length_sweep"][key]
        sweeps[key] = {}
        for wavelength in cfg["wavelengths_nm"]:
            fiber = g652d_preset(float(wavelength))
            sweeps[key][str(wavelength)] = _run(
                pair,
                frames[key],
                demo,
                key,
                spec["extra_attenuation_db"],
                spec["fiber_km"],
                {"fiber": fiber},
                PROFILE_TAG[key] + 30,
                cfg["length_sweep"]["runs"],
            )
    results["length_sweeps"] = {
        "label": "simulated",
        "fiber": "G.652.D representative",
        "runs": cfg["length_sweep"]["runs"],
        "extra_attenuation_db": {
            k: cfg["length_sweep"][k]["extra_attenuation_db"] for k in PROFILES
        },
        "data": sweeps,
    }

    rep = g652d_preset(1550.0)
    low, high = g652d_preset(1550.0, "limit-low"), g652d_preset(1550.0, "limit-high")
    d_variants = {
        "D at lower bound": replace(
            rep,
            dispersion_ps_per_nm_km=low.dispersion_ps_per_nm_km,
            dispersion_slope_ps_per_nm2_km=low.dispersion_slope_ps_per_nm2_km,
            dispersion_source=ValueSource.SPECIFICATION_LIMIT,
        ),
        "D representative": rep,
        "D at upper bound": replace(
            rep,
            dispersion_ps_per_nm_km=high.dispersion_ps_per_nm_km,
            dispersion_slope_ps_per_nm2_km=high.dispersion_slope_ps_per_nm2_km,
            dispersion_source=ValueSource.SPECIFICATION_LIMIT,
        ),
    }
    sens_chosen = set(cfg["sensitivity"]["waveforms"])
    sens_waves = [w for w in wave_set if w.name in sens_chosen]
    sens_runs = cfg["sensitivity"]["runs"]
    sensitivity: dict[str, Any] = {
        "label": "simulated",
        "wavelength_nm": 1550.0,
        "runs": sens_runs,
        "dispersion_bounds_ps_per_nm_km": [
            low.dispersion_ps_per_nm_km,
            high.dispersion_ps_per_nm_km,
        ],
    }
    for key in PROFILES:
        spec = cfg["sensitivity"][key]
        args = (
            sens_waves,
            frames[key],
            demo,
            key,
            spec["extra_attenuation_db"],
            [spec["fiber_km"]],
        )
        tag = PROFILE_TAG[key] + 40
        sensitivity[key] = {
            "extra_attenuation_db": spec["extra_attenuation_db"],
            "fiber_km": spec["fiber_km"],
            "dispersion": {
                name: _run(*args, {"fiber": fiber}, tag, sens_runs)
                for name, fiber in d_variants.items()
            },
            "attenuation": {
                f"{a:g} dB/km": _run(
                    *args,
                    {
                        "fiber": replace(
                            rep,
                            attenuation_db_per_km=a,
                            attenuation_source=ValueSource.REPRESENTATIVE,
                        )
                    },
                    tag,
                    sens_runs,
                )
                for a in cfg["sensitivity"]["attenuation_db_per_km"]
            },
        }
    results["sensitivity"] = sensitivity
    results["before_after"] = before_after(cfg, demo, stored, wave_set, frames)
    results["numerical_validation"] = numerical_validation(cfg, demo)
    results["assumptions"] = [
        "Single polarization, no PMD, no nonlinearity, no amplifier or laser noise (link.py).",
        "Attenuation limits are for cable; Table 2 Note 1 excludes short cables such as jumpers.",
        "Table I.1 typical link values are not cable limits; 0.5 dB/km at 1310 nm exceeds the "
        "Table 2 limit because it includes splices and connectors.",
        "The representative dispersion curve is a three-term fit through Table I.1 D and S at "
        "1550 nm, a model choice and not a stated value.",
        "Southampton's fiber type and length are unconfirmed.",
    ]
    results["runtime_s"] = time.time() - start
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fiber_results.json").write_text(json.dumps(results, indent=1, default=float) + "\n")
    fiber_figures(results, out_dir / "figures")
    return results


def _save(fig: Any, ax: Any, path: Path, stamp: str, legend: bool = True) -> None:
    if legend:
        ax.legend(frameon=False, fontsize=7)
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.99, 0.01, stamp, ha="right", va="bottom", fontsize=7, color="#888888")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _error_series(
    ax: Any, xs: list[float], points: list[dict[str, Any]], key: str, **style: Any
) -> None:
    """Plot an error rate; points with fewer than 10 symbol errors become hollow upper bounds."""
    good = [p[key] if p["symbol_errors"] >= 10 else np.nan for p in points]
    ax.semilogy(xs, good, marker="o", ms=3, **style)
    bounds = [
        (x, p[f"{key}_ci95"][1]) for x, p in zip(xs, points, strict=True) if p["symbol_errors"] < 10
    ]
    if bounds:
        ax.semilogy(*zip(*bounds, strict=True), "v", ms=4, mfc="none", color=style["color"])


def fiber_figures(results: dict[str, Any], out: Path) -> None:
    """Draw every figure from saved results. Each is stamped analytical or simulated."""
    out.mkdir(parents=True, exist_ok=True)
    a = results["analytical"]
    w = a["wavelength_nm"]

    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.step(
        w,
        a["attenuation_limit_db_per_km"],
        where="post",
        color="#1f4e79",
        label="Table 2 cable limit (Note 2 extension assumed flat)",
    )
    ax.plot(
        w,
        a["attenuation_typical_link_db_per_km"],
        color="#c0504d",
        label="Table I.1 typical link value (linear between bands is an assumption)",
    )
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Attenuation (dB/km)")
    ax.set_title("G.652.D attenuation", fontsize=9)
    _save(fig, ax, out / "attenuation_vs_wavelength.png", "ANALYTICAL")

    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.fill_between(
        w,
        a["dispersion_lower_ps_per_nm_km"],
        a["dispersion_upper_ps_per_nm_km"],
        color="#1f4e79",
        alpha=0.18,
        label="Eq. (6-2), (6-3) bounds",
    )
    ax.plot(
        w,
        a["dispersion_representative_ps_per_nm_km"],
        color="#c0504d",
        label="Representative (three-term fit)",
    )
    ax.axhline(0, color="#888888", lw=0.8)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Dispersion D (ps/(nm km))")
    ax.set_title("G.652.D chromatic dispersion", fontsize=9)
    _save(fig, ax, out / "dispersion_vs_wavelength.png", "ANALYTICAL")

    sweeps = results["length_sweeps"]["data"]
    for key, name in (("profile_A", "A"), ("profile_B", "B")):
        fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4))
        for ax, metric in zip(axes, ("ber", "ser"), strict=True):
            for wavelength, per_waveform in sweeps[key].items():
                for label, points in per_waveform.items():
                    xs = [p["link"]["fiber_length_km"] for p in points]
                    _error_series(
                        ax,
                        xs,
                        points,
                        metric,
                        color=COLORS[wavelength],
                        ls=LABEL_STYLE[label],
                        label=f"{label}, {wavelength} nm",
                    )
            ax.set_xlabel("Fiber length (km)")
            ax.set_ylabel(metric.upper())
            ax.grid(alpha=0.25)
        axes[0].legend(frameon=False, fontsize=7)
        axes[0].set_title(f"Profile {name}, G.652.D representative", fontsize=9)
        fig.text(0.99, 0.01, "SIMULATED", ha="right", va="bottom", fontsize=7, color="#888888")
        fig.tight_layout()
        fig.savefig(out / f"ber_ser_vs_length_{name}.png", dpi=200)
        plt.close(fig)

    sens = results["sensitivity"]
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 5.6))
    for row, (key, name) in zip(axes, (("profile_A", "A"), ("profile_B", "B")), strict=True):
        for ax, kind in zip(row, ("dispersion", "attenuation"), strict=True):
            cases = list(sens[key][kind])
            for label, style in (("Uniform", "-"), ("Outer70", "--")):
                points = [sens[key][kind][c][label][0] for c in cases]
                _error_series(
                    ax,
                    list(range(len(cases))),
                    points,
                    "ber",
                    color="#1f4e79",
                    ls=style,
                    label=label,
                )
            ax.set_xticks(range(len(cases)), cases, fontsize=7, rotation=12)
            ax.set_ylabel("BER")
            ax.set_title(f"Profile {name}, {sens[key]['fiber_km']:g} km, {kind}", fontsize=8)
            ax.grid(alpha=0.25)
            ax.legend(frameon=False, fontsize=7)
    fig.text(0.99, 0.01, "SIMULATED", ha="right", va="bottom", fontsize=7, color="#888888")
    fig.tight_layout()
    fig.savefig(out / "sensitivity.png", dpi=200)
    plt.close(fig)

    ba = results["before_after"]
    for key, name in (("profile_A", "A"), ("profile_B", "B")):
        fig, ax = plt.subplots(figsize=(5.6, 3.4))
        for arm, color in (("v1.0 defaults", "#888888"), ("G.652.D representative", "#c0504d")):
            for label, style in (("Uniform", "-"), ("Outer70", "--")):
                points = ba[key][arm][label]
                xs = [p["link"]["fiber_length_km"] for p in points]
                _error_series(ax, xs, points, "ber", color=color, ls=style, label=f"{label}, {arm}")
        ax.set_xlabel("Fiber length (km)")
        ax.set_ylabel("BER")
        ax.set_title(f"Profile {name}: v1.0 defaults vs G.652.D at 1550 nm", fontsize=9)
        _save(fig, ax, out / f"before_after_{name}.png", "SIMULATED")


def one_point(results: dict[str, Any]) -> dict[str, Any]:
    """Return the before/after numbers for Profile A, Uniform, at the longest fiber length."""
    data = results["before_after"]["profile_A"]
    old = data["v1.0 defaults"]["Uniform"][-1]
    new = data["G.652.D representative"]["Uniform"][-1]
    keys = ("ser", "ber", "symbol_errors", "bit_errors", "r_bmd", "received_dbm")
    return {
        "point": "Profile A, Uniform, 40 km",
        "v1.0": {k: old[k] for k in keys},
        "g652d": {k: new[k] for k in keys},
    }


def main(config: Path, selection: Path, out_dir: Path) -> dict[str, Any]:
    """Entry point used by the CLI."""
    return run_fiber_validation(config, selection, out_dir)
