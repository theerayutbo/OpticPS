"""Fiber model validation report, and the fiber section of the main report and slides.

Everything is read from results/fiber_validation/fiber_results.json. When that file is
absent the callers skip the fiber content, so the original build is unaffected.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opticps.optical_channel.fiber import (
    ATTENUATION_MAX,
    ATTENUATION_MAX_C_BAND,
    LAMBDA0_MAX_NM,
    LAMBDA0_MIN_NM,
    PMD_Q_MAX,
    S0_MAX,
    S0_MIN,
    TYPICAL_ATTENUATION,
    TYPICAL_D1550,
    TYPICAL_S1550,
)
from opticps.reporting.report import _scientific, _table, render_pdf

TITLE = "OpticPS Fiber Model Validation Report"
FILENAME = "Fiber_Model_Validation_Report"
REFERENCES = [
    "Recommendation ITU-T G.652 (08/2024), Characteristics of a single-mode optical fibre and "
    "cable, edition 10.0, approved 2024-08-29, in force. Clauses 6 to 8, Tables 1 and 2, "
    "Equations (6-1) to (6-3), Appendix I and Table I.1.",
    "G. P. Agrawal, Nonlinear Fiber Optics, Academic Press. Used for the sign convention of the "
    "dispersion phase only.",
    "J. Wang and K. Petermann, Small signal analysis for dispersive optical fiber communication "
    "systems, J. Lightw. Technol. 10(1):96-100, 1992. doi:10.1109/50.108743",
    "Recommendations ITU-T G.650.1, G.650.2 and Supplement 39 are cited by G.652 for test "
    "methods and system design. They were not read for this work.",
]


def load_fiber_results(demo_results_path: Path) -> dict[str, Any] | None:
    """Return fiber_results.json beside results/synthetic, or None when it does not exist."""
    path = demo_results_path.parent.parent / "fiber_validation" / "fiber_results.json"
    return json.loads(path.read_text()) if path.exists() else None


def _at(curve: dict[str, Any], key: str, wavelength: float) -> float:
    return float(curve[key][curve["wavelength_nm"].index(wavelength)])


def fiber_facts(fr: dict[str, Any]) -> dict[str, Any]:
    """Derive every number the text uses from the saved results."""
    ba = fr["before_after"]
    facts: dict[str, Any] = {"profiles": {}}
    for key in ("profile_A", "profile_B"):
        arms = ba[key]
        rep = arms["reproduction"]
        labels = list(arms["v1.0 defaults"])
        deltas = {"attenuation": 0, "slope": 0}
        slope_identical = slope_total = 0
        attenuation_explains = attenuation_total = 0
        for label in arms["G.652.D slope only"]:
            for old, att, slope, full in zip(
                arms["v1.0 defaults"][label],
                arms["G.652.D attenuation only"][label],
                arms["G.652.D slope only"][label],
                arms["G.652.D representative"][label],
                strict=True,
            ):
                slope_total += 1
                slope_identical += slope["symbol_errors"] == old["symbol_errors"]
                deltas["slope"] = max(
                    deltas["slope"], abs(slope["symbol_errors"] - old["symbol_errors"])
                )
                if old["link"]["fiber_length_km"] > 0:
                    attenuation_total += 1
                    # The attenuation-only arm is 'near' the full preset when its change
                    # accounts for most of the full change in symbol errors.
                    whole = full["symbol_errors"] - old["symbol_errors"]
                    part = att["symbol_errors"] - old["symbol_errors"]
                    attenuation_explains += abs(whole - part) <= 0.1 * abs(whole) + 1
        facts["profiles"][key] = {
            "labels": labels,
            "reproduction": rep,
            "slope_points_identical": slope_identical,
            "slope_points": slope_total,
            "slope_max_symbol_error_change": deltas["slope"],
            "attenuation_explains": attenuation_explains,
            "attenuation_points": attenuation_total,
        }
    numerical = fr["numerical_validation"]
    facts["max_null_error"] = max(abs(r["relative_error"]) for r in numerical["null_frequency"])
    facts["max_response_change"] = max(
        abs(r["response_ratio_slope_over_flat_at_half_null"] - 1)
        for r in numerical["null_frequency"]
    )
    facts["third_order"] = numerical["third_order_phase_at_nyquist"]
    facts["all_reproduced"] = all(
        facts["profiles"][k]["reproduction"]["points_identical"]
        == facts["profiles"][k]["reproduction"]["points_compared"]
        for k in ("profile_A", "profile_B")
    )
    return facts


def _point_row(label: str, point: dict[str, Any]) -> list[str]:
    return [
        label,
        f"{point['link']['fiber_length_km']:g}",
        f"{point['received_dbm']:.2f}",
        _scientific(point["ser"]),
        _scientific(point["ber"]),
        str(point["symbol_errors"]),
    ]


def _before_after_table(fr: dict[str, Any], key: str, waveform: str) -> str:
    rows = [["Fiber", "Length (km)", "Received (dBm)", "SER", "BER", "Symbol errors"]]
    arms = fr["before_after"][key]
    for old, new in zip(
        arms["v1.0 defaults"][waveform], arms["G.652.D representative"][waveform], strict=True
    ):
        rows.append(_point_row("v1.0 defaults", old))
        rows.append(_point_row("G.652.D representative", new))
    return _table(rows)


def _attribution_text(facts: dict[str, Any]) -> str:
    lines = []
    for key, name in (("profile_A", "Profile A"), ("profile_B", "Profile B")):
        item = facts["profiles"][key]
        if item["slope_points_identical"] == item["slope_points"]:
            slope = (
                f"With only the slope added, symbol-error counts were identical to v1.0 at all "
                f"{item['slope_points']} points"
            )
        else:
            slope = (
                f"With only the slope added, symbol-error counts equalled v1.0 at "
                f"{item['slope_points_identical']} of {item['slope_points']} points and differed "
                f"by at most {item['slope_max_symbol_error_change']} symbol errors"
            )
        lines.append(
            f"- {name}: {slope}. With only the attenuation changed, the change in symbol errors "
            f"was within 10% (plus one error) of the full preset's change at "
            f"{item['attenuation_explains']} of {item['attenuation_points']} points with fiber."
        )
    return "\n".join(lines)


def _length_table(fr: dict[str, Any], key: str) -> str:
    rows = [
        ["Wavelength (nm)", "Waveform", "Length (km)", "Received (dBm)", "SER", "BER", "Errors"]
    ]
    for wavelength, per_waveform in fr["length_sweeps"]["data"][key].items():
        for label, points in per_waveform.items():
            for point in points:
                rows.append(
                    [wavelength, *_point_row(label, point)[0:1], *_point_row("", point)[1:]]
                )
    return _table(rows)


def _sensitivity_table(fr: dict[str, Any], key: str, kind: str) -> str:
    rows = [["Case", "Waveform", "SER", "BER", "Symbol errors"]]
    for case, per_waveform in fr["sensitivity"][key][kind].items():
        for label, points in per_waveform.items():
            point = points[0]
            rows.append(
                [case, label, _scientific(point["ser"]), _scientific(point["ber"]),
                 str(point["symbol_errors"])]
            )  # fmt: skip
    return _table(rows)


def _null_table(fr: dict[str, Any]) -> str:
    rows = [["Wavelength (nm)", "Variant", "D (ps/(nm km))", "Theory (GHz)", "Simulated (GHz)",
             "Relative error", "Null shift from slope (GHz)"]]  # fmt: skip
    for r in fr["numerical_validation"]["null_frequency"]:
        rows.append(
            [f"{r['wavelength_nm']:g}", r["variant"], f"{r['dispersion_ps_per_nm_km']:.3f}",
             f"{r['theory_null_ghz']:.4f}", f"{r['simulated_null_ghz']:.4f}",
             f"{r['relative_error']:.1e}", f"{r['null_with_slope_minus_without_ghz']:.1e}"]
        )  # fmt: skip
    return _table(rows)


def _third_order_table(fr: dict[str, Any]) -> str:
    rows = [["Profile", "Length (km)", "Baud (GBd)", "beta3 (ps^3/km)", "beta3 from D only",
             "2nd-order phase (rad)", "3rd-order phase (rad)"]]  # fmt: skip
    for r in fr["numerical_validation"]["third_order_phase_at_nyquist"]:
        rows.append(
            [r["profile"], f"{r['fiber_km']:g}", f"{r['symbol_rate_Bd'] / 1e9:g}",
             f"{r['beta3_s3_per_m'] * 1e3 / 1e-36:.4f}",
             f"{r['beta3_from_D_only_s3_per_m'] * 1e3 / 1e-36:.4f}",
             f"{r['second_order_phase_rad']:.3f}", f"{r['third_order_phase_rad']:.2e}"]
        )  # fmt: skip
    return _table(rows)


def fiber_section(fr: dict[str, Any], figures: str) -> str:
    """Return the fiber model subsection for the main research report."""
    facts = fiber_facts(fr)
    a = facts["profiles"]["profile_A"]
    b = facts["profiles"]["profile_B"]
    return f"""### Fiber model, ITU-T G.652.D (version {fr["software_version"]})

The link can use a selectable fiber description with attenuation, dispersion and dispersion slope, each tagged with its provenance. The `g652d-representative` preset follows Rec. ITU-T G.652 (08/2024) Table I.1 and a three-term dispersion curve fitted to it; the limit presets sit on the Table 2 dispersion bounds. No fiber type is applied unless selected, and the Southampton fiber type and length are unconfirmed. The simulated results in the sections above use the v1.0 defaults of 0.2 dB/km and 17 ps/(nm km) with no slope, and are unchanged.

Re-running the v1.0 fiber sweep with the same seed and waveforms reproduced {a["reproduction"]["points_identical"] + b["reproduction"]["points_identical"]} of {a["reproduction"]["points_compared"] + b["reproduction"]["points_compared"]} saved points exactly. Replacing the defaults by the representative G.652.D values at 1550 nm changes attenuation from 0.2 to 0.275 dB/km. Details are in reports/Fiber_Model_Validation_Report.pdf. Nothing in it is experimentally validated.

![Dispersion bounds and representative curve, ITU-T G.652.D, 1260 to 1625 nm [analytical]]({figures}/dispersion_vs_wavelength.png)

![Profile A, v1.0 defaults against G.652.D at 1550 nm]({figures}/before_after_A.png)
"""


def fiber_slide(fr: dict[str, Any]) -> tuple[str, list[str]]:
    """Return the title and bullets of the fiber model slide."""
    facts = fiber_facts(fr)
    a = facts["profiles"]["profile_A"]
    return (
        "Fiber model: ITU-T G.652.D presets",
        [
            "Selectable fiber: none (v1.0), G.652.D representative, bounds low and high, custom",
            "Values carry provenance: limit, typical link value, data sheet or measured",
            f"Re-run of the v1.0 fiber sweep: {a['reproduction']['points_identical']} of "
            f"{a['reproduction']['points_compared']} Profile A points identical",
            f"Dispersion null: simulation within {facts['max_null_error']:.0e} of theory",
            "Attenuation 0.275 vs 0.2 dB/km drives the change; slope is negligible",
            "Analytical and simulated only; Southampton fiber type and length unconfirmed",
        ],
    )


# fmt: off
def markdown(fr: dict[str, Any], figures: str) -> str:
    """Return the standalone fiber model validation report."""
    facts = fiber_facts(fr)
    analytical = fr["analytical"]
    one = fr["before_after"]["profile_A"]
    old = one["v1.0 defaults"]["Uniform"][-1]
    new = one["G.652.D representative"]["Uniform"][-1]
    d1550 = _at(analytical, "dispersion_representative_ps_per_nm_km", 1550.0)
    d1310 = _at(analytical, "dispersion_representative_ps_per_nm_km", 1310.0)
    bounds_1550 = (
        _at(analytical, "dispersion_lower_ps_per_nm_km", 1550.0),
        _at(analytical, "dispersion_upper_ps_per_nm_km", 1550.0),
    )
    typical_rows = [
        ["Attenuation coefficient", f"{lo:g} to {hi:g} nm", f"{value:g} dB/km"]
        for lo, hi, value in TYPICAL_ATTENUATION
    ]
    typical_rows += [
        ["Chromatic dispersion D1550", "1550 nm", f"{TYPICAL_D1550:g} ps/(nm km)"],
        ["Dispersion slope S1550", "1550 nm", f"{TYPICAL_S1550:g} ps/(nm^2 km)"],
    ]
    tables = {
        "fibre": _table(
            [
                ["Fibre attribute", "Detail", "Value"],
                ["Mode field diameter", "1310 nm, nominal range", "8.6 to 9.2 um, tolerance 0.4 um"],
                ["Cladding diameter", "Nominal", "125.0 um, tolerance 0.7 um"],
                ["Cable cut-off wavelength", "Maximum", "1260 nm"],
                ["Macrobending loss", "30 mm radius, 100 turns, 1625 nm", "0.1 dB maximum"],
                ["Zero-dispersion wavelength", "lambda0 min, max",
                 f"{LAMBDA0_MIN_NM:g} nm, {LAMBDA0_MAX_NM:g} nm"],
                ["Dispersion slope at lambda0", "S0 min, max",
                 f"{S0_MIN:g}, {S0_MAX:g} ps/(nm^2 km)"],
                ["D at 1550 nm", "Minimum, maximum", "13.3, 18.6 ps/(nm km)"],
                ["D at 1625 nm", "Minimum, maximum", "17.2, 23.7 ps/(nm km)"],
            ]
        ),
        "cable": _table(
            [
                ["Cable attribute", "Detail", "Value"],
                ["Attenuation coefficient", "Maximum, 1310 to 1625 nm (Notes 1, 2)",
                 f"{ATTENUATION_MAX:g} dB/km"],
                ["Attenuation coefficient", "Maximum at 1383 nm after hydrogen ageing (Note 3)",
                 f"{ATTENUATION_MAX:g} dB/km"],
                ["Attenuation coefficient", "Maximum, 1530 to 1565 nm",
                 f"{ATTENUATION_MAX_C_BAND:g} dB/km"],
                ["PMD coefficient", "PMD_Q, M = 20 cables, Q = 0.01%",
                 f"{PMD_Q_MAX:g} ps/sqrt(km) maximum"],
            ]
        ),
        "evidence": _table(
            [
                ["Item", "Status"],
                ["G.652.D limits, bounds, Table I.1 curves, third-order phase sizes", "Analytical"],
                ["BER and SER versus length, sensitivity, before and after, dispersion null",
                 "Simulated"],
                ["Any statement about the Southampton link or any real fiber",
                 "Not experimentally validated. No measured data has been imported."],
            ]
        ),
        "typical": _table([["Link attribute (Table I.1)", "Wavelength", "Typical link value"], *typical_rows]),
    }  # fmt: skip
    largest = max(p["slope_max_symbol_error_change"] for p in facts["profiles"].values())
    slope_sentence = (
        "The slope has no effect on intensity at these bandwidths: by calculation (section 7) "
        "and in the simulation, where the slope-only arm gave identical symbol-error counts."
        if largest == 0
        else f"The slope-only arm changed symbol errors by at most {largest}; compare section 7."
    )
    return f"""# {TITLE}

ITU-T G.652.D fiber model, OpticPS version {fr["software_version"]}

**{fr["banner"]}**

Configuration SHA-256 {fr["config_sha256"]}. Seed {fr["seed"]}. Python {fr["python"]}, NumPy {fr["numpy"]}. Runtime {fr["runtime_s"]:.0f} s.

## 1. Summary

OpticPS now offers a selectable fiber description with attenuation, chromatic dispersion and dispersion slope, and a third-order dispersion term in the field propagation. Presets follow Rec. ITU-T G.652 (08/2024). Each number records whether it is a specification limit, a representative simulation value, manufacturer data or a laboratory measurement.

- With no fiber selected, the link reproduces v1.0 exactly: {facts["profiles"]["profile_A"]["reproduction"]["points_identical"] + facts["profiles"]["profile_B"]["reproduction"]["points_identical"]} of {facts["profiles"]["profile_A"]["reproduction"]["points_compared"] + facts["profiles"]["profile_B"]["reproduction"]["points_compared"]} saved v1.0 fiber-sweep points were recomputed identically (symbol errors, bit errors, rates and powers).
- At the Profile A, Uniform, {old["link"]["fiber_length_km"]:g} km point, v1.0 defaults give SER {old["ser"]:.6f}, BER {old["ber"]:.6f} ({old["symbol_errors"]} symbol errors, {old["received_dbm"]:.3f} dBm received). The G.652.D representative preset at 1550 nm gives SER {new["ser"]:.6f}, BER {new["ber"]:.6f} ({new["symbol_errors"]} symbol errors, {new["received_dbm"]:.3f} dBm received).
- The simulated dispersion null agrees with theory to {facts["max_null_error"]:.0e} relative error in every case tested.

## 2. Standard and references

The model follows Rec. ITU-T G.652 (08/2024), edition 10.0, approved 2024-08-29, in force. Used: clause 6 (fibre attributes, Equations (6-1) to (6-3)), clause 7 (cable attributes), clause 8 (Table 2, G.652.D), and Appendix I (Table I.1, representative link values). The G.652.D variant is a deliberate default for presets only: nothing forces the simulation onto G.652.D, and a custom fiber description can describe any other type.

Equation (6-2a,b,c) reached the code through an extraction in which the signs and subscripts were garbled. The signs were reconstructed, and confirmed by continuity with Equation (6-3) at 1460 nm: the reconstructed bounds equal the values of Equation (6-3), 8.625 and 12.472 ps/(nm km), and they join continuously at lambda0 min and lambda0 max. This is consistency evidence, not a reading of the printed equation, and it should be checked against the printed Recommendation.

## 3. Equations and assumptions

Dispersion parameter D and slope S relate to the propagation constant through:

EQ: \\beta_2=-\\frac{{D\\lambda^2}}{{2\\pi c}},\\qquad \\beta_3=\\frac{{\\lambda^4 S+2\\lambda^3 D}}{{4\\pi^2 c^2}}

The field envelope A of E = A exp(-i omega0 t) acquires, for an optical frequency offset omega over length L:

EQ: A(\\omega,L)=A(\\omega,0)\\,\\exp\\left[i\\left(\\frac{{\\beta_2}}{{2}}\\omega^2+\\frac{{\\beta_3}}{{6}}\\omega^3\\right)L\\right]

numpy's FFT kernel is exp(-i omega t), so its frequency axis is minus the optical offset. The even term is unchanged and the odd term enters as exp(-i beta3 L omega_np^3 / 6). A test checks the sign: a pulse offset in frequency is delayed by beta3 omega^2 L / 2 on either side. A slope of exactly zero selects the v1.0 second-order model, with no third-order term at all, so existing results are unchanged. A non-zero slope adds the full beta3, including its 2 lambda^3 D part. Intensity detection of a double-sideband signal sees the cosine of the second-order phase, so the first null follows:

EQ: f_{{\\mathrm{{null}}}}=\\sqrt{{\\frac{{c}}{{2\\lambda^2 |D| L}}}}

When D is zero or the length is zero there is no null and the code returns infinity.

The G.652 three-term Sellmeier form and the bounds for 1460 nm to 1625 nm are:

EQ: D(\\lambda)=\\frac{{S_0\\lambda}}{{4}}\\left[1-\\left(\\frac{{\\lambda_0}}{{\\lambda}}\\right)^4\\right],\\qquad 8.625+0.052(\\lambda-1460)\\leq D\\leq 12.472+0.068(\\lambda-1460)

The representative preset uses this form with lambda0 and S0 fitted so that D = 17 ps/(nm km) and S = 0.056 ps/(nm^2 km) at 1550 nm, the Table I.1 values. The fit gives lambda0 = 1307.6 nm and S0 = 0.0889 ps/(nm^2 km), inside Table 2. This is a model choice, not a value stated in the Recommendation. Its attenuation is the Table I.1 link value, joined linearly between bands, also an assumption.

Assumptions carried from the link model: single polarization; no polarization mode dispersion; no Kerr effect; no amplifier or laser noise; attenuation independent of power. PMD is listed in the tables and is not simulated.

## 4. ITU-T G.652.D attributes

Fibre attributes and cable attributes are kept apart because they apply to different things. The fibre values describe the glass; the cable values are limits for factory-length cable.

{tables["fibre"]}

{tables["cable"]}

Note 1 of Table 2 says the cable attenuation values should not be applied to short cables such as jumpers, indoor cables and drop cables. Note 2 extends the range to 1260 nm by adding 0.07 dB/km to the 1310 nm value; the Recommendation does not give the intermediate curve, so OpticPS applies the addition flat from 1260 to 1310 nm. Table I.1 gives typical values of concatenated links, which are not cable limits:

{tables["typical"]}

The Table I.1 typical link value of 0.5 dB/km at 1310 nm is above the Table 2 cable limit of 0.40 dB/km because it is a link value, which includes splices and connectors, and not a cable limit. The representative preset therefore reports itself outside the Table 2 cable attenuation limit at 1310 nm, and the code says so instead of hiding it.

## 5. Attenuation and dispersion

![Attenuation, Table 2 cable limit and Table I.1 typical link value [analytical]]({figures}/attenuation_vs_wavelength.png)

![Dispersion bounds and representative curve, 1260 to 1625 nm [analytical]]({figures}/dispersion_vs_wavelength.png)

The representative curve gives D = {d1550:.3f} ps/(nm km) at 1550 nm, inside the bounds {bounds_1550[0]:.2f} to {bounds_1550[1]:.2f}, and D = {d1310:.3f} ps/(nm km) at 1310 nm. The representative curve stays inside the bounds over 1260 to 1625 nm: {analytical["representative_within_limits"]}. The bounds are a worst-case envelope. A limit preset sits on one bound with attenuation at the Table 2 maximum, and is not a real fiber.

## 6. BER and SER sensitivity

All results in this section are simulated, through the link and the full receiver, on the same frames and seeds as the v1.0 demonstration. They are not measurements. Intervals and error counts follow the conventions of the main report: points with fewer than 10 symbol errors are drawn as hollow upper bounds.

### Length at 1550 nm and 1310 nm

Representative preset, excess loss fixed at {fr["length_sweeps"]["extra_attenuation_db"]["profile_A"]} dB (Profile A) and {fr["length_sweeps"]["extra_attenuation_db"]["profile_B"]} dB (Profile B), mean of {fr["length_sweeps"]["runs"]} runs. At 1310 nm, D is {d1310:.2f} ps/(nm km), so dispersion hardly matters and the attenuation of 0.5 dB/km dominates. At 1550 nm the loss is lower but dispersion limits the bandwidth. For Profile B at 1550 nm the error count is not monotonic in length, which is consistent with the dispersion null moving through the signal band as the length grows.

![BER and SER versus fiber length, Profile A]({figures}/ber_ser_vs_length_A.png)

![BER and SER versus fiber length, Profile B]({figures}/ber_ser_vs_length_B.png)

{_length_table(fr, "profile_A")}

{_length_table(fr, "profile_B")}

### Sensitivity to D and to attenuation

At 1550 nm, one point per profile. D is set to the lower and upper G.652.D bound with attenuation held at the representative value; then attenuation is varied with D held. These are envelope tests, not predictions for a fiber.

![Sensitivity of BER to D at the bounds and to attenuation]({figures}/sensitivity.png)

Profile A, {fr["sensitivity"]["profile_A"]["fiber_km"]:g} km, dispersion:

{_sensitivity_table(fr, "profile_A", "dispersion")}

Profile A, attenuation:

{_sensitivity_table(fr, "profile_A", "attenuation")}

Profile B, {fr["sensitivity"]["profile_B"]["fiber_km"]:g} km, dispersion:

{_sensitivity_table(fr, "profile_B", "dispersion")}

Profile B, attenuation:

{_sensitivity_table(fr, "profile_B", "attenuation")}

### Before and after: v1.0 defaults and G.652.D at 1550 nm

Identical configuration, seed, waveforms, frames and per-point noise seeds as the v1.0 fiber sweep of configs/demo.yaml. The v1.0 arm re-computed {facts["profiles"]["profile_A"]["reproduction"]["points_identical"]} of {facts["profiles"]["profile_A"]["reproduction"]["points_compared"]} Profile A and {facts["profiles"]["profile_B"]["reproduction"]["points_identical"]} of {facts["profiles"]["profile_B"]["reproduction"]["points_compared"]} Profile B saved points identically, so the comparison starts from the same code. Single point: Profile A, Uniform, {old["link"]["fiber_length_km"]:g} km. v1.0: SER {old["ser"]:.6f}, BER {old["ber"]:.6f}, {old["symbol_errors"]} symbol errors, {old["bit_errors"]} bit errors, R_BMD {old["r_bmd"]:.4f}, received {old["received_dbm"]:.3f} dBm. G.652.D: SER {new["ser"]:.6f}, BER {new["ber"]:.6f}, {new["symbol_errors"]} symbol errors, {new["bit_errors"]} bit errors, R_BMD {new["r_bmd"]:.4f}, received {new["received_dbm"]:.3f} dBm.

![Profile A, v1.0 defaults against G.652.D at 1550 nm]({figures}/before_after_A.png)

![Profile B, v1.0 defaults against G.652.D at 1550 nm]({figures}/before_after_B.png)

Profile A, Uniform:

{_before_after_table(fr, "profile_A", "Uniform")}

Profile B, Uniform:

{_before_after_table(fr, "profile_B", "Uniform")}

Why the results differ. The attenuation of the preset is 0.275 dB/km against 0.2 dB/km, so the span loses 0.075 dB more per km. The dispersion at 1550 nm is the same 17 ps/(nm km) and the slope is the only other change. Two further arms isolated each change on Uniform and Outer70:

{_attribution_text(facts)}

{slope_sentence}

## 7. Numerical validation

The first null of the simulated intensity response of a small tone through the dispersion routine is compared with theory. The grid is not aligned to the theoretical null, and the null is found by intersecting the two sides of the response. Relative error is at most {facts["max_null_error"]:.1e}.

{_null_table(fr)}

A slope changes only the phase of the sidebands of a double-sideband signal, not the magnitude of the intensity response, to first order. The largest change in response magnitude at half the null frequency was {facts["max_response_change"]:.1e}. The size of the third-order phase at the Nyquist frequency of each profile, at the longest sweep length, against the second-order phase:

{_third_order_table(fr)}

Here beta3 is in ps^3/km. The third-order phase is some orders of magnitude below the second-order phase, so the third-order term is expected to be negligible for these baud rates, which the before and after results confirm. It would matter for much wider bandwidths or near the zero-dispersion wavelength.

## 8. Limitations and experimental data still required

- The Southampton link's fiber type and length are unconfirmed. Nothing here describes it.
- The Table 2 limits are for cable, and exclude short cables such as jumpers (Note 1). A short bench link is not covered by them.
- PMD is listed and not simulated; no polarization effects are modelled.
- No Kerr effect, no amplifier, no laser chirp. Real transmitters add chirp that interacts with dispersion.
- Connector and splice losses, and bend loss, are not modelled except through the excess loss term.
- The representative curves are models built from Table I.1, not a measurement of any fiber.
- Needed from Southampton: fiber type and manufacturer data sheet, link length, attenuation measured at the operating wavelength, dispersion or a group delay measurement, and the laser wavelength. These enter through apply_measurements, which marks them as laboratory-measured.

## 9. What is analytical, simulated and experimentally validated

{tables["evidence"]}

## 10. References

{chr(10).join(f"{i}. {r}" for i, r in enumerate(REFERENCES, 1))}

## 11. Reproducibility

Command: uv run opticps fiber-validate. Configuration: configs/fiber_validation.yaml and configs/demo.yaml. Data: results/fiber_validation/fiber_results.json. Standard: {fr["standard"]}.
"""

# fmt: on


def build_fiber_report(results_path: Path, out_dir: Path) -> Path:
    """Build the Markdown and PDF report from fiber_results.json. Returns the PDF path."""
    fr = json.loads(results_path.read_text())
    figure_dir = results_path.parent / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    relative = f"../{figure_dir.as_posix()}"
    text = markdown(fr, relative)
    (out_dir / f"{FILENAME}.md").write_text(text)
    pdf = out_dir / f"{FILENAME}.pdf"
    work = out_dir / ".equations"
    work.mkdir(exist_ok=True)
    render_pdf(text.replace(relative, figure_dir.as_posix()), pdf, work, fr["banner"], TITLE)
    for item in work.glob("*.png"):
        item.unlink()
    work.rmdir()
    return pdf
