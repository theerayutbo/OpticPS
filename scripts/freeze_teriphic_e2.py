"""Build the B2B-only inputs of Gate E2 part a, and later the criterion file (plan Revision 12).

    python scripts/freeze_teriphic_e2.py prepare     # model, scenario list, pre-registration
    python scripts/freeze_teriphic_e2.py criterion   # the criterion file, after the plan is final

`prepare` opens the B2B capture only (through `teriphic.open_b2b`, which gates it) and writes three
files under `docs/benchmarks/teriphic_e2/`: the fitted B2B model with its provenance and code
identity, the scenario list, and the pre-registered predictions. It never opens, hashes or reads
the 2 km or 10 km file and never imports the scoring entry point. `criterion` writes
`docs/benchmarks/TERIPHIC_CRITERION_R12.yaml` from the pre-registered limits and the SHA-256 of the
committed plan; it must be run only after the plan revision is final, and its output is the freeze.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opticps.benchmarks import e2_metrics, e2_model, e2_score, holdout, teriphic  # noqa: E402
from opticps.benchmarks.provenance import Split  # noqa: E402
from opticps.optical_channel.fiber import g652d_dispersion_limits  # noqa: E402

MULTIPLIER = 2.0
LENGTHS_KM = (2.0, 10.0)
WINDOWS = {
    "fit": {"start": 0, "samples": 1 << 23},
    "spread": {"start": 1 << 23, "samples": 1 << 22},
    "evaluation": {"start": 1 << 24, "samples": 1 << 22},
}
SEEDS = {"fit": 20261101, "prediction_symbols": 20261102, "prediction_noise": 20261103}


def dump(path: Path, document: dict[str, Any], header: str) -> bytes:
    text = header + yaml.safe_dump(document, sort_keys=False, default_flow_style=None, width=100)
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


# 0 to 3 in steps of 0.5, 3.25 to 6.25 in steps of 0.25, plus the O-band bound (the notch moves
# faster with D at high D, so the grid is finer there; see the power study)
DISPERSION_GRID = (*(0.5 * k for k in range(7)), *(3.25 + 0.25 * k for k in range(13)))
NOISE_FACTORS = (1.0, 1.5, 2.2)
STUDY_STARTS = (12582912, 20971520, 25165824, 29360128, 33554432)  # B2B windows, no overlap


def scenario_document() -> dict[str, Any]:
    wavelengths = np.arange(1260.0, 1361.0, 1.0)
    bounds = [g652d_dispersion_limits(float(w)) for w in wavelengths]
    d_max = round(max(abs(v) for pair in bounds for v in pair), 3)
    grid = (*DISPERSION_GRID, d_max)
    entries = []
    for factor in NOISE_FACTORS:
        for disp in grid:
            for through in (False, True) if disp > 0 else (False,):
                name = f"D{disp:g}_N{factor:g}" + ("_THRU" if through else "")
                label = f"|D| {disp:g} ps/(nm km), noise x{factor:g}" + (
                    ", noise crosses the fibre" if through else ", noise after the fibre"
                )
                entries.append((name, disp, factor, through, disp == 0.0 and factor == 1.0, label))
    return {
        "scenario_list_version": e2_score.SCENARIO_VERSION,
        "count": len(entries),
        "scenarios": [
            {
                "id": a,
                "dispersion_ps_nm_km": round(b, 3),
                "noise_factor": c,
                "noise_through_fibre": d,
                "null_control": e,
                "label": f,
            }
            for a, b, c, d, e, f in entries
        ],
        "provenance": {
            "status": "ASSUMED_G652D scenarios: hypotheses; the fibre type is UNKNOWN",
            "dispersion": (
                f"The grid is 0 to 3 in steps of 0.5, 3.25 to 6.25 in steps of 0.25 and {d_max}"
                f" ps/(nm km). {d_max} is the largest |D| of"
                " the ITU-T G.652.D limit envelope, 1260 to 1360 nm in 1 nm steps, from"
                " opticps.optical_channel.fiber.g652d_dispersion_limits (Rec. ITU-T G.652 08/2024"
                " Eq. 6-2, 6-3): SPECIFICATION_LIMIT. The other points are a grid refined in steps"
                " after power studies showed that a true D between grid points FAILs at 10 km"
                " (a FAIL dominated by the grid): 1.5, then 0.5, then 0.25 at high D. The sign of"
                " D does not matter for zero chirp."
            ),
            "noise_factor": (
                "Noise standard deviation relative to B2B: 1, 1.5, 2.2. It stands for any SNR"
                " change (loss, re-tuning, launch power: UNKNOWN). The amplitude itself is"
                " removed by the gain-invariant map of plan R12.3 and is reported, not tested."
            ),
            "noise_origin": (
                "noise_through_fibre false: noise added after the fibre; true: the noise crosses"
                " the fibre like the signal. The B2B split is unidentifiable, so both bounds are"
                " scenarios."
            ),
            "wavelength": "UNKNOWN (O-band only); 1310 nm enters only as lambda^2 of the response",
            "chirp": "UNKNOWN; all scenarios assume zero (MODEL GAP: CHIRP)",
        },
    }


def parameters_table() -> dict[str, Any]:
    fitted = "B2B fit window only"
    return {
        "normalisation_c0_g0": {"provenance": "RAW_CAPTURE", "how": f"k-means centroids, {fitted}"},
        "psd_relative": {"provenance": "RAW_CAPTURE", "how": f"Welch estimate (R2.2), {fitted}"},
        "pulse_levels": {"provenance": "INFERRED", "how": f"fitted, {fitted}"},
        "noise_sigma": {"provenance": "INFERRED", "how": f"fitted, {fitted}"},
        "level_probabilities": {"provenance": "INFERRED", "how": "assumed uniform and independent"},
        "fibre_length_km": {"provenance": "PUBLISHED_MEASUREMENT", "how": "file names: 2 and 10"},
        "wavelength_nm": {"provenance": "UNKNOWN", "how": "O-band only"},
        "fibre_type": {"provenance": "UNKNOWN", "how": "not stated in the record"},
        "dispersion": {"provenance": "UNKNOWN", "how": "scenarios bounded by G.652.D limits"},
        "attenuation_and_launch_power": {
            "provenance": "UNKNOWN",
            "how": "amplitude ratio scenario",
        },
        "chirp_alpha": {"provenance": "UNKNOWN", "how": "unidentifiable from B2B; zero assumed"},
        "modulation_depth_and_offset": {"provenance": "UNKNOWN", "how": "not recoverable from B2B"},
        "response_phase": {"provenance": "UNKNOWN", "how": "not identifiable; zero phase assumed"},
        "noise_origin_split": {"provenance": "UNKNOWN", "how": "not separable on B2B"},
    }


def prepare() -> int:
    capture = teriphic.open_b2b()
    try:
        increment = capture.layout.x_increment_s
        if increment is None:
            raise SystemExit("B2B header has no time increment")
        sample_rate = 1.0 / increment
        raw = {k: capture.read(w["start"], w["start"] + w["samples"]) for k, w in WINDOWS.items()}
    finally:
        capture.close()
    centroids, _ = e2_metrics.kmeans_levels(raw["fit"])
    c0, g0 = float(centroids.mean()), float(np.diff(centroids).mean())
    norm = {k: e2_metrics.normalise(v, c0, g0) for k, v in raw.items()}
    model = e2_model.fit_b2b_model(
        norm["fit"], sample_rate_hz=sample_rate, baud_bd=teriphic.BAUD_BD, fit_seed=SEEDS["fit"]
    )
    document: dict[str, Any] = {
        "model_version": e2_score.MODEL_VERSION,
        **model,
        "normalisation": {
            "c0": c0,
            "g0": g0,
            "units": "file units of the B2B capture (normalized)",
        },
        "windows": WINDOWS,
        "seeds": SEEDS,
        "parameters": parameters_table(),
        "model_gaps": list(e2_model.MODEL_GAPS),
        "assumptions": list(e2_model.ASSUMPTIONS),
        "code_identity": e2_score.code_identity(ROOT),
    }
    base = ROOT / e2_score.E2_DIR
    model_bytes = dump(
        ROOT / e2_score.MODEL_PATH,
        document,
        "# B2B model of Gate E2 part a (plan Revision 12). Fitted on the B2B fit window only.\n"
        "# No 2 km or 10 km sample was read to produce it.\n",
    )
    scenario_bytes = dump(
        ROOT / e2_score.SCENARIO_PATH,
        scenario_document(),
        "# Pre-listed fibre scenarios (plan Revision 12). Hypotheses, never ground truth.\n",
    )
    model_doc = e2_score.check_model(yaml.safe_load(model_bytes))
    scenarios = e2_score.check_scenarios(yaml.safe_load(scenario_bytes))
    n = WINDOWS["evaluation"]["samples"]
    null = next(s for s in scenarios if s.null_control)
    surrogate = e2_score.predict(model_doc, null, 0.0, n)
    baud = teriphic.BAUD_BD
    copy_summary = e2_score.window_summary(norm["evaluation"], sample_rate, baud)
    misfit = e2_metrics.metrics_between(
        copy_summary, e2_score.window_summary(surrogate, sample_rate, baud)
    )
    spread = e2_metrics.metrics_between(
        copy_summary, e2_score.window_summary(norm["spread"], sample_rate, baud)
    )
    basis = {m: float(max(misfit[m], spread[m])) for m in holdout.METRICS}
    multipliers = {m: MULTIPLIER for m in holdout.METRICS}
    limits = {m: float(basis[m] * multipliers[m]) for m in holdout.METRICS}
    registered = e2_score.compute_preregistration(
        model_doc, scenarios, norm["evaluation"], limits, LENGTHS_KM
    )
    dump(
        ROOT / e2_score.PREREGISTRATION_PATH,
        {
            "preregistration_version": e2_score.PREREGISTRATION_VERSION,
            "declared": (
                "Computed from the B2B capture and the code alone, before any 2 km or 10 km"
                " sample was read. No result column is filled."
            ),
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "scenario_list_sha256": hashlib.sha256(scenario_bytes).hexdigest(),
            "scenario_count": len(scenarios),
            "lengths_km": list(LENGTHS_KM),
            "reproduction": {
                "rtol": e2_score.REPRODUCTION_RTOL,
                "atol": e2_score.REPRODUCTION_ATOL,
                "meaning": "the scorer recomputes every value below and refuses on a larger drift",
            },
            "b2b_surrogate_misfit": misfit,
            "b2b_window_spread": spread,
            "b2b_basis": basis,
            "multipliers": multipliers,
            "limits": limits,
            **registered,
            "results": None,
        },
        "# Pre-registered predictions (plan Revision 12), B2B and code only. Keep results out.\n",
    )
    print(f"wrote {base}")
    print("misfit", misfit)
    print("spread", spread)
    print("limits", limits)
    print("identifiable", registered["identifiable_in_principle"])
    return 0


LIGHT = 299_792_458.0
LAMBDA = 1310e-9


def cos_filter(x: np.ndarray, fs: float, d_ps: float, length_km: float) -> np.ndarray:
    """The study's own dispersion filter, written here and not shared with e2_model."""
    f = np.fft.rfftfreq(x.size, 1.0 / fs)
    theta = np.pi * LAMBDA**2 * (d_ps * 1e-6) * (length_km * 1e3) * f**2 / LIGHT
    return np.fft.irfft(np.fft.rfft(x) * np.cos(theta), x.size)


def low_pass(x: np.ndarray, fs: float, fc: float) -> np.ndarray:
    """An unmodelled Gaussian low-pass with its -3 dB power point at `fc`."""
    f = np.fft.rfftfreq(x.size, 1.0 / fs)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-0.5 * np.log(2.0) * (f / fc) ** 2), x.size)


def extra_noise(x: np.ndarray, fs: float, level: float, seed: int) -> np.ndarray:
    f = np.fft.rfftfreq(x.size, 1.0 / fs)
    white = np.random.default_rng(seed).normal(size=x.size)
    shaped = np.fft.irfft(np.fft.rfft(white) * np.exp(-((f / 40e9) ** 2)), x.size)
    return x + level * shaped / shaped.std()


def power() -> int:
    """Pre-registered power study on pseudo-captures made from real B2B (plan R12.4).

    Reads only B2B windows disjoint from the fit, spread and evaluation windows, builds pseudo
    captures with the filters above, and runs the frozen two-stage procedure on each. No holdout.
    """
    model_bytes = (ROOT / e2_score.MODEL_PATH).read_bytes()
    model = e2_score.check_model(yaml.safe_load(model_bytes))
    scenarios = e2_score.check_scenarios(
        yaml.safe_load((ROOT / e2_score.SCENARIO_PATH).read_bytes())
    )
    registration = yaml.safe_load((ROOT / e2_score.PREREGISTRATION_PATH).read_bytes())
    limits = registration["limits"]
    fs = float(model["sample_rate_hz"])
    n = int(model["windows"]["evaluation"]["samples"])
    norm = model["normalisation"]
    capture = teriphic.open_b2b()
    try:
        sources = [
            e2_metrics.normalise(capture.read(s, s + n), norm["c0"], norm["g0"])
            for s in STUDY_STARTS
        ]
        w = model["windows"]["evaluation"]
        copy = e2_metrics.normalise(
            capture.read(w["start"], w["start"] + n), norm["c0"], norm["g0"]
        )
    finally:
        capture.close()
    summaries = e2_score.prediction_summaries(model, scenarios, LENGTHS_KM)
    scenario_by_id = {s.scenario_id: s for s in scenarios}
    ident = registration["identifiable_in_principle"]

    def synthetic(d: float, length: float, seed: int) -> np.ndarray:
        scenario = e2_score.Scenario("study", d, 1.0, False, False, "study")
        shifted = dict(
            model,
            seeds={**model["seeds"], "prediction_symbols": seed, "prediction_noise": seed + 1},
        )
        return e2_score.predict(shifted, scenario, length, n)

    cases: dict[str, Any] = {}
    for d in (0.0, 2.2, 3.4, 3.85, 4.1, 4.5, 4.9, 5.2, 5.45, 5.7, 6.352, 9.0):
        cases[f"B2B filtered, D={d:g}"] = lambda x, L, k, d=d: cos_filter(x, fs, d, L) if d else x
    for fc in (32e9, 34e9, 36e9):
        cases[f"B2B, D=0 plus unmodelled low-pass {fc / 1e9:g} GHz"] = lambda x, L, k, fc=fc: (
            low_pass(x, fs, fc)
        )
    cases["B2B, D=0, amplitude x0.95"] = lambda x, L, k: 0.95 * x
    cases["B2B, D=0, amplitude x1.05"] = lambda x, L, k: 1.05 * x
    cases["B2B filtered D=4.5, extra noise 0.3 gap"] = lambda x, L, k: extra_noise(
        cos_filter(x, fs, 4.5, L), fs, 0.3, 100 + k
    )
    cases["surrogate, D=2.2, noise after fibre"] = lambda x, L, k: synthetic(2.2, L, 7000 + k)
    cases["surrogate, D=4.5, noise after fibre"] = lambda x, L, k: synthetic(4.5, L, 7100 + k)
    table: dict[str, Any] = {}
    for name, make in cases.items():
        rows = []
        for k, source in enumerate(sources):
            two = e2_score.score_windows(
                make(source, 2.0, k), copy, model=model, scenarios=scenarios, limits=limits,
                length_km=2.0, split=Split.VALIDATION, identifiable_in_principle=ident["2"],
                summaries=summaries,
            )  # fmt: skip
            all_ids = [sc.scenario_id for sc in scenarios]
            alone = e2_score.score_windows(
                make(source, 10.0, k), copy, model=model, scenarios=scenarios, limits=limits,
                length_km=10.0, split=Split.LOCKED_TEST, carried=all_ids,
                identifiable_in_principle=ident["10"], summaries=summaries,
            )  # fmt: skip
            if two.carry_forward:
                ten = e2_score.score_windows(
                    make(source, 10.0, k), copy, model=model, scenarios=scenarios, limits=limits,
                    length_km=10.0, split=Split.LOCKED_TEST, carried=list(two.carry_forward),
                    identifiable_in_principle=ident["10"], summaries=summaries,
                )  # fmt: skip
                ten_outcome, ten_surv = ten.outcome, list(ten.survivors)
                ten_verdict = ten.verdict.value if ten.verdict else "none"
            else:
                ten_outcome, ten_surv, ten_verdict = "NOT RUN (2 km FAIL)", [], "none"
            rows.append(
                {
                    "two_km": two.outcome,
                    "two_km_carry": len(two.carry_forward),
                    "two_km_rule": "single" if len(two.carry_forward) == 1 else "all_survivors",
                    "ten_km": ten_outcome,
                    "ten_km_alone": alone.outcome,
                    "ten_km_verdict": ten_verdict,
                    "ten_km_survivors": ten_surv,
                }
            )

        def tally(key: str, rows: list[dict[str, Any]] = rows) -> dict[str, int]:
            out: dict[str, int] = {}
            for r in rows:
                out[r[key]] = out.get(r[key], 0) + 1
            return out

        table[name] = {
            "windows": len(rows),
            "two_km": tally("two_km"),
            "two_km_mean_carried": float(np.mean([r["two_km_carry"] for r in rows])),
            "two_km_single_carried": sum(r["two_km_rule"] == "single" for r in rows),
            "ten_km": tally("ten_km"),
            "ten_km_if_2km_were_bypassed": tally("ten_km_alone"),
            "ten_km_verdict": tally("ten_km_verdict"),
            "ten_km_mean_survivors": float(np.mean([len(r["ten_km_survivors"]) for r in rows])),
            "ten_km_survivor_dispersions": sorted(
                {scenario_by_id[i].dispersion_ps_nm_km for r in rows for i in r["ten_km_survivors"]}
            ),
        }
        print(name, table[name], flush=True)
    dump(
        ROOT / e2_score.POWER_STUDY_PATH,
        {
            "power_study_version": 1,
            "declared": (
                "Pseudo-captures made from B2B windows that are not the fit, spread or evaluation"
                " window, with this script's own filters, run through the frozen two-stage"
                " procedure. No 2 km or 10 km sample was read. A limit was not changed after seeing"
                " this table; where a case fails to separate, the verdict is capped instead."
            ),
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "study_window_starts": list(STUDY_STARTS),
            "selection_margin_psi": e2_score.SELECTION_MARGIN,
            "cases": table,
        },
        "# Power study (plan Revision 12, R12.4), B2B only.\n",
    )
    return 0


def criterion() -> int:
    registration = yaml.safe_load((ROOT / e2_score.PREREGISTRATION_PATH).read_bytes())
    plan = (ROOT / holdout.DEFAULT_PLAN).read_bytes()
    document = {
        "criterion_version": holdout.CRITERION_VERSION,
        "plan_sha256": hashlib.sha256(plan).hexdigest(),
        "limits": registration["limits"],
        "b2b_basis": registration["b2b_basis"],
        "multipliers": registration["multipliers"],
        "estimators": dict(holdout.ESTIMATORS),
    }
    dump(
        ROOT / holdout.CRITERION_PATH,
        document,
        "# Frozen criterion for TERIPHIC PD1 PAM4 (plan Revision 12). The commit that first holds\n"
        "# this file is the freeze. Limits are b2b_basis times multipliers, from B2B only.\n",
    )
    print(f"wrote {ROOT / holdout.CRITERION_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "power", "criterion"))
    args = parser.parse_args()
    return {"prepare": prepare, "power": power, "criterion": criterion}[args.step]()


if __name__ == "__main__":
    sys.exit(main())
