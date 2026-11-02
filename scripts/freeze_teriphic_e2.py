"""Build the B2B-only inputs of Gate E2 part a, and later the criterion file (plan Revision 10).

    python scripts/freeze_teriphic_e2.py prepare     # model, scenario list, pre-registration
    python scripts/freeze_teriphic_e2.py criterion   # the criterion file, after the plan is final

`prepare` opens the B2B capture only (through `teriphic.open_b2b`, which gates it) and writes three
files under `docs/benchmarks/teriphic_e2/`: the fitted B2B model with its provenance and code
identity, the scenario list, and the pre-registered predictions. It never opens, hashes or reads
the 2 km or 10 km file and never imports the scoring entry point. `criterion` writes
`docs/benchmarks/TERIPHIC_CRITERION_R11.yaml` from the pre-registered limits and the SHA-256 of the
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
from opticps.optical_channel.fiber import (  # noqa: E402
    g652d_dispersion_limits,
    typical_attenuation,
)

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


def scenario_document() -> dict[str, Any]:
    wavelengths = np.arange(1260.0, 1361.0, 1.0)
    bounds = [g652d_dispersion_limits(float(w)) for w in wavelengths]
    d_max = round(max(abs(v) for pair in bounds for v in pair), 3)
    loss = float(typical_attenuation(1310.0))
    entries = []
    for amp_name, att, borne, amp_label in (
        ("MATCHED", 0.0, False, "received amplitude equal to B2B (assumed)"),
        ("LOSS_RX_NOISE", loss, False, "G.652 typical link loss, receiver-dominated noise"),
        ("LOSS_SIGNAL_NOISE", loss, True, "G.652 typical link loss, signal-borne noise"),
    ):
        for disp_name, disp, disp_label in (
            ("D0", 0.0, "no dispersion"),
            ("DHALF", d_max / 2, "half the O-band G.652.D |D| bound"),
            ("DMAX", d_max, "the O-band G.652.D |D| bound"),
        ):
            entries.append(
                (f"{disp_name}_{amp_name}", disp, att, borne, disp_name == "D0" and att == 0.0,
                 f"{disp_label}; {amp_label}")
            )  # fmt: skip
    return {
        "scenario_list_version": e2_score.SCENARIO_VERSION,
        "count": len(entries),
        "scenarios": [
            {
                "id": a,
                "dispersion_ps_nm_km": round(b, 3),
                "attenuation_db_per_km": c,
                "noise_follows_signal": d,
                "null_control": e,
                "label": f,
            }
            for a, b, c, d, e, f in entries
        ],
        "provenance": {
            "status": "ASSUMED_G652D scenarios: hypotheses; the fibre type is UNKNOWN",
            "dispersion": (
                f"|D| bound {d_max} ps/(nm km) is the largest |D| of the ITU-T G.652.D limit"
                " envelope, 1260 to 1360 nm in 1 nm steps, from opticps.optical_channel.fiber"
                ".g652d_dispersion_limits (Rec. ITU-T G.652 08/2024 Eq. 6-2, 6-3):"
                " SPECIFICATION_LIMIT."
                " The sign of D does not matter for a chirp-free modulator (the response is even)."
            ),
            "attenuation": (
                f"{loss} dB/km is the G.652 Table I.1 typical link value for 1260 to 1360 nm"
                " (representative, not measured on this fibre). 0 means received amplitude equal"
                " to B2B, which is an assumption (launch power and re-tuning are UNKNOWN)."
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
        "# B2B model of Gate E2 part a (plan Revision 10). Fitted on the B2B fit window only.\n"
        "# No 2 km or 10 km sample was read to produce it.\n",
    )
    scenario_bytes = dump(
        ROOT / e2_score.SCENARIO_PATH,
        scenario_document(),
        "# Pre-listed fibre scenarios (plan Revision 10). Hypotheses, never ground truth.\n",
    )
    model_doc = e2_score.check_model(yaml.safe_load(model_bytes))
    scenarios = e2_score.check_scenarios(yaml.safe_load(scenario_bytes))
    n = WINDOWS["evaluation"]["samples"]
    null = next(s for s in scenarios if s.null_control)
    surrogate = e2_score.predict(model_doc, null, 0.0, n)
    misfit = e2_metrics.all_metrics(norm["evaluation"], surrogate, sample_rate, teriphic.BAUD_BD)
    spread = e2_metrics.all_metrics(
        norm["evaluation"], norm["spread"], sample_rate, teriphic.BAUD_BD
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
        "# Pre-registered predictions (plan Revision 10), B2B and code only. Keep results out.\n",
    )
    print(f"wrote {base}")
    print("misfit", misfit)
    print("spread", spread)
    print("limits", limits)
    print("identifiable", registered["identifiable_in_principle"])
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
        "# Frozen criterion for TERIPHIC PD1 PAM4 (plan Revision 10). The commit that first holds\n"
        "# this file is the freeze. Limits are b2b_basis times multipliers, from B2B only.\n",
    )
    print(f"wrote {ROOT / holdout.CRITERION_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "criterion"))
    args = parser.parse_args()
    return prepare() if args.step == "prepare" else criterion()


if __name__ == "__main__":
    sys.exit(main())
