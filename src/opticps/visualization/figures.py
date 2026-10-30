"""Figures drawn only from saved results and exported waveforms."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from opticps.measurement.demo import nrz_wave, realised, waveforms
from opticps.measurement.validate_export import read_waveform
from opticps.optical_channel.link import LinkConfig, transmit
from opticps.transmitter.frame import build_frame

COLORS = {
    "Uniform": "#1f4e79",
    "PS70 (inner)": "#c0504d",
    "PS80 (inner)": "#e39a3b",
    "Adaptive": "#2e7d32",
    "Outer70": "#6a4c93",
    "PS70": "#c0504d",
    "PS80": "#e39a3b",
}
STAMP = "SIMULATED"


def _finish(fig: Any, ax: Any, path: Path, legend: bool = True) -> None:
    if legend:
        ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.99, 0.01, STAMP, ha="right", va="bottom", fontsize=7, color="#888888")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _axes() -> tuple[Any, Any]:
    return plt.subplots(figsize=(5.6, 3.4))


def _sweep_plot(
    points: dict[str, list[dict[str, Any]]],
    x_of: Any,
    y: str,
    path: Path,
    xlabel: str,
    ylabel: str,
    log: bool = False,
    band: str | None = None,
) -> None:
    fig, ax = _axes()
    for label, series in points.items():
        xs = [x_of(p) for p in series]
        if log:
            # Points with too few errors are shown only as hollow upper bounds.
            good = [p[y] if p["symbol_errors"] >= 10 else np.nan for p in series]
            ax.semilogy(xs, good, "-o", ms=3, color=COLORS[label], label=label)
            bounds = [(x, p[f"{y}_ci95"][1]) for x, p in zip(xs, series, strict=True)
                      if p["symbol_errors"] < 10]  # fmt: skip
            if bounds:
                ax.semilogy(*zip(*bounds, strict=True), "v", ms=4, mfc="none", color=COLORS[label])
        else:
            values = [p[y] for p in series]
            ax.plot(xs, values, "-o", ms=3, color=COLORS[label], label=label)
            if band:
                low = [p[band][0] for p in series]
                high = [p[band][1] for p in series]
                ax.fill_between(xs, low, high, color=COLORS[label], alpha=0.18)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    _finish(fig, ax, path)


def theory_figures(r: dict[str, Any], out: Path) -> None:
    """Rate curves, optimum distribution, entropy and matcher loss."""
    t = r["theory"]
    psnr = t["psnr_db"]

    fig, ax = _axes()
    for name, curve in t["rate_curves"].items():
        ax.plot(psnr, curve["bmd"], color=COLORS[name], label=name)
    ax.plot(psnr, t["optimal_rate_bmd"], "k--", lw=1, label="Best symmetric")
    ax.set_xlabel("PSNR (dB), fixed peak")
    ax.set_ylabel("R_BMD (bit/symbol)")
    _finish(fig, ax, out / "rate_vs_psnr.png")

    fig, ax = _axes()
    ax.plot(psnr, t["optimal_p0_bmd"], color=COLORS["Adaptive"])
    ax.axhline(0.25, color="#888888", lw=1, ls=":")
    ax.axhline(0.15, color=COLORS["PS70"], lw=1, ls=":")
    ax.text(27.8, 0.255, "uniform", ha="right", fontsize=8)
    ax.text(27.8, 0.155, "PS70", ha="right", fontsize=8)
    ax.set_xlabel("PSNR (dB), fixed peak")
    ax.set_ylabel("Optimal P(-3) = P(+3)")
    _finish(fig, ax, out / "optimal_p0.png", legend=False)

    fig, ax = _axes()
    for name, values in t["average_power_smd"].items():
        ax.plot(t["average_power_snr_db"], values, color=COLORS[name], label=name)
    ax.set_xlabel("Average-power SNR (dB), peak unconstrained")
    ax.set_ylabel("R_SMD (bit/symbol)")
    _finish(fig, ax, out / "rate_vs_average_snr.png")

    fig, ax = _axes()
    gmi = t["gmi_vs_p0"]
    for psnr_key, values in gmi["psnr"].items():
        ax.plot(gmi["p_outer"], values, label=f"{float(psnr_key):g} dB")
    ax.axvline(0.25, color="#888888", lw=1, ls=":")
    ax.set_xlabel("P(-3) = P(+3)")
    ax.set_ylabel("GMI, R_BMD (bit/symbol)")
    _finish(fig, ax, out / "gmi_vs_p0.png")

    fig, ax = _axes()
    entropy = t["entropy_vs_lambda"]
    ax.plot(entropy["lambda"], entropy["entropy"], color=COLORS["Uniform"])
    ax.set_xlabel("Shaping parameter lambda")
    ax.set_ylabel("Entropy (bit/symbol)")
    _finish(fig, ax, out / "entropy_vs_lambda.png", legend=False)

    fig, ax = _axes()
    loss = t["rate_loss"]
    for name in ("PS70", "PS80"):
        ax.loglog(loss["n"], loss[name], "-o", ms=3, color=COLORS[name], label=name)
    ax.set_xlabel("CCDM block length n (symbols)")
    ax.set_ylabel("Rate loss (bit/symbol)")
    _finish(fig, ax, out / "ccdm_rate_loss.png")


def performance_figures(r: dict[str, Any], out: Path) -> None:
    """Monte Carlo curves from the demo results."""
    received = lambda p: p["received_dbm"]  # noqa: E731
    length = lambda p: p["link"].get("fiber_length_km", 0.0)  # noqa: E731
    awgn = r["awgn"]
    psnr_lookup = dict(enumerate(awgn["psnr_db"]))
    curves = {
        k: [dict(p, psnr=psnr_lookup[i]) for i, p in enumerate(v)]
        for k, v in awgn["curves"].items()
    }
    _sweep_plot(curves, lambda p: p["snr_db"], "ber", out / "ber_vs_snr.png",
                "Estimated SNR (dB)", "Gray label BER", log=True)  # fmt: skip
    _sweep_plot(curves, lambda p: p["psnr"], "r_bmd", out / "awgn_monte_carlo_rate.png",
                "PSNR (dB)", "Estimated R_BMD (bit/symbol)", band="r_bmd_ci95")  # fmt: skip
    for key, tag in (("profile_A", "A"), ("profile_B", "B")):
        b2b = r[key]["back_to_back"]
        rate = r[key]["symbol_rate_Bd"] / 1e9
        _sweep_plot(b2b, received, "ber", out / f"ber_vs_rx_{tag}.png",
                    "Received optical power (dBm)", "Gray label BER", log=True)  # fmt: skip
        _sweep_plot(b2b, received, "ser", out / f"ser_vs_rx_{tag}.png",
                    "Received optical power (dBm)", "SER", log=True)  # fmt: skip
        _sweep_plot(b2b, received, "r_bmd", out / f"air_vs_rx_{tag}.png",
                    "Received optical power (dBm)", "Estimated R_BMD (bit/symbol)",
                    band="r_bmd_ci95")  # fmt: skip
        throughput = {k: [dict(p, air=p["r_bmd"] * rate) for p in v] for k, v in b2b.items()}
        _sweep_plot(throughput, received, "air", out / f"throughput_vs_rx_{tag}.png",
                    "Received optical power (dBm)",
                    "Achievable rate, ideal FEC (Gbit/s)")  # fmt: skip
        _sweep_plot(r[key]["fiber"], length, "ber", out / f"ber_vs_fiber_{tag}.png",
                    "Fiber length (km)", "Gray label BER", log=True)  # fmt: skip

    fig, ax = _axes()
    points = r["adaptive_held_out"]
    width = 0.2
    for i, other in enumerate(("Uniform", "Outer70", "PS70")):
        means = [p["paired_difference"][other]["mean"] for p in points]
        low = [
            m - p["paired_difference"][other]["ci95"][0] for m, p in zip(means, points, strict=True)
        ]
        high = [
            p["paired_difference"][other]["ci95"][1] - m for m, p in zip(means, points, strict=True)
        ]
        ax.bar(np.arange(len(points)) + i * width, means, width, yerr=[low, high],
               color=COLORS[other], label=f"vs {other}", capsize=2)  # fmt: skip
    ax.set_xticks(np.arange(len(points)) + width)
    ax.set_xticklabels([f"{p['attenuation_db']} dB" for p in points])
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("Attenuation (held-out runs)")
    ax.set_ylabel("Point-adaptive gain in R_BMD (bit/symbol)")
    _finish(fig, ax, out / "adaptive_vs_fixed.png")


def waveform_figures(r: dict[str, Any], out: Path, seed: int = 42) -> None:
    """Histograms, eye diagrams and a waveform excerpt from real frames and CSVs."""
    wave_set = waveforms(r["adaptive_export"]["p_outer"])
    frames = {
        w.name: build_frame(w.name, w.probabilities, 32768, seed, 1024, w.direct) for w in wave_set
    }
    fig, axes = plt.subplots(1, 5, figsize=(9.5, 2.3), sharey=True)
    for ax, w in zip(axes, wave_set, strict=True):
        ax.bar(range(4), realised(frames[w.name]), color=COLORS[w.label])
        ax.set_xticks(range(4), ["-3", "-1", "+1", "+3"], fontsize=7)
        ax.set_title(w.label, fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Probability (payload)")
    fig.tight_layout()
    fig.savefig(out / "symbol_histograms.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(5, 1, figsize=(6.4, 5.6), sharex=True)
    root = Path("output/keysight_m8199b/A_initial_8GBd/waveforms")
    for ax, w in zip(axes, wave_set, strict=True):
        folder = root / "benchmark" if w.name.endswith("Outer70") else root
        _, samples = read_waveform(folder / f"{w.name}.csv")
        start = 2048 * 28
        ax.plot(np.array(samples[start : start + 56 * 28]), color=COLORS[w.label], lw=0.9)
        ax.set_ylim(-1.15, 1.15)
        ax.set_ylabel(w.label, fontsize=7)
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xlabel("Sample index from payload start (224 GSa/s)")
    fig.tight_layout()
    fig.savefig(out / "waveform_excerpts.png", dpi=200)
    plt.close(fig)

    link = LinkConfig(
        extra_attenuation_db=21.0, transmitter_bandwidth_hz=12e9, receiver_bandwidth_hz=8e9
    )
    fig, axes = plt.subplots(1, 3, figsize=(9.5, 2.8), sharey=True)
    for ax, w in zip(axes, [wave_set[0], wave_set[1], wave_set[4]], strict=True):
        wave = nrz_wave(frames[w.name], 16)
        result = transmit(wave, 128e9, link, np.random.default_rng(seed))
        current = result.current_a * 1e6
        for k in range(1100, 2300):
            ax.plot(current[k * 16 - 8 : k * 16 + 24], color=COLORS[w.label], alpha=0.03, lw=0.5)
        ax.set_title(f"{w.label}", fontsize=9)
        ax.set_xlabel("Samples (16 per symbol)")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Photocurrent (uA)")
    fig.text(
        0.99, 0.01, f"{STAMP} link, 21 dB attenuation", ha="right", fontsize=7, color="#888888"
    )
    fig.tight_layout()
    fig.savefig(out / "eye_diagrams.png", dpi=200)
    plt.close(fig)


def all_figures(results_path: Path, out: Path) -> list[Path]:
    """Render every figure from one results file."""
    results = json.loads(results_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    theory_figures(results, out)
    performance_figures(results, out)
    waveform_figures(results, out)
    return sorted(out.glob("*.png"))
