"""Build the research report as Markdown and PDF from saved results."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from opticps.reporting.facts import all_facts, verdict
from opticps.visualization.figures import all_figures

REFERENCES = [
    "T. Wiegart et al., Probabilistically shaped 4-PAM for short-reach IM/DD links with a peak "
    "power constraint, J. Lightw. Technol. 39(2):400-405, 2021. doi:10.1109/JLT.2020.3029371",
    "P. Schulte and G. Boecherer, Constant composition distribution matching, IEEE Trans. Inf. "
    "Theory 62(1):430-434, 2016. doi:10.1109/TIT.2015.2499181",
    "G. Boecherer, F. Steiner, P. Schulte, Bandwidth efficient and rate-matched low-density "
    "parity-check coded modulation, IEEE Trans. Commun. 63(12):4651-4665, 2015. "
    "doi:10.1109/TCOMM.2015.2494016",
    "G. Boecherer, P. Schulte, F. Steiner, Probabilistic shaping and forward error correction "
    "for fiber-optic communication systems, J. Lightw. Technol. 37(2):230-244, 2019. "
    "doi:10.1109/JLT.2019.2895770",
    "T. M. Cover, Enumerative source encoding, IEEE Trans. Inf. Theory 19(1):73-77, 1973. "
    "doi:10.1109/TIT.1973.1054929",
    "J. G. Smith, The information capacity of amplitude- and variance-constrained scalar "
    "Gaussian channels, Inf. Control 18(3):203-219, 1971.",
    "D. M. Arnold et al., Simulation-based computation of information rates for channels with "
    "memory, IEEE Trans. Inf. Theory 52(8):3498-3508, 2006. doi:10.1109/TIT.2006.878110",
    "Z. He, T. Bo, H. Kim, Probabilistically shaped coded modulation for IM/DD system, Opt. "
    "Express 27(9):12126, 2019. doi:10.1364/OE.27.012126",
    "J. Wang and K. Petermann, Small signal analysis for dispersive optical fiber communication "
    "systems, J. Lightw. Technol. 10(1):96-100, 1992. doi:10.1109/50.108743",
    "E. L. Wooten et al., A review of lithium niobate modulators for fiber-optic communications "
    "systems, IEEE J. Sel. Topics Quantum Electron. 6(1):69-82, 2000. "
    "doi:10.1109/2944.826874",
    "F. Gray, Pulse code communication, U.S. Patent 2,632,058, 1953.",
    "B. Efron, Bootstrap methods: another look at the jackknife, Ann. Stat. 7(1):1-26, 1979. "
    "doi:10.1214/aos/1176344552",
    "H. R. Kuensch, The jackknife and the bootstrap for general stationary observations, Ann. "
    "Stat. 17(3):1217-1241, 1989. doi:10.1214/aos/1176347265",
    "C. J. Clopper and E. S. Pearson, The use of confidence or fiducial limits illustrated in "
    "the case of the binomial, Biometrika 26(4):404-413, 1934. doi:10.1093/biomet/26.4.404",
]


def _scientific(value: float) -> str:
    return "0" if value == 0 else f"{value:.2e}"


def _table(rows: list[list[str]]) -> str:
    head = "| " + " | ".join(rows[0]) + " |"
    rule = "|" + "---|" * len(rows[0])
    body = ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join([head, rule, *body])


def _performance_table(section: dict[str, Any]) -> str:
    rows = [["Waveform", "R_BMD (bit/sym)", "Achievable rate (Gbit/s)", "SER", "BER", "Errors"]]
    for row in section["table"]:
        rows.append(
            [
                row["label"],
                f"{row['r_bmd']:.3f} [{row['r_bmd_ci95'][0]:.3f}, {row['r_bmd_ci95'][1]:.3f}]",
                f"{row['air_gbps']:.2f}",
                _scientific(row["ser"]),
                _scientific(row["ber"]),
                str(row["symbol_errors"]),
            ]
        )
    return _table(rows)


def _power_table(section: dict[str, Any]) -> str:
    rows = [["Waveform", "Launch (dBm)", "Received (dBm)", "OMA (dBm)", "ER (dB)"]]
    for row in section["table"]:
        rows.append(
            [
                row["label"],
                f"{row['launch_dbm']:.3f}",
                f"{row['received_dbm']:.3f}",
                f"{row['oma_dbm']:.3f}",
                f"{row['er_db']:.3f}",
            ]
        )
    return _table(rows)


def _comparison_lines(section: dict[str, Any]) -> str:
    lines = []
    for label, item in section["versus_uniform"].items():
        lines.append(
            f"- {label} versus Uniform: {verdict(item['mean'], item['ci95'], 'bit/symbol')}."
        )
    return "\n".join(lines)


def _adaptive_table(results: dict[str, Any]) -> str:
    rows = [["Attenuation", "Selected P(+-3)", "vs Uniform", "vs Outer70", "vs PS70"]]
    for point in results["adaptive_held_out"]:
        difference = point["paired_difference"]
        cells = [
            f"{difference[k]['mean']:+.3f} [{difference[k]['ci95'][0]:+.3f}, "
            f"{difference[k]['ci95'][1]:+.3f}]"
            for k in ("Uniform", "Outer70", "PS70")
        ]
        rows.append([f"{point['attenuation_db']} dB", f"{point['selected_p_outer']:.3f}", *cells])
    return _table(rows)


def _adaptive_conclusion(results: dict[str, Any]) -> str:
    resolved_gain = 0
    resolved_loss = 0
    unresolved = 0
    for point in results["adaptive_held_out"]:
        low, high = point["paired_difference"]["Outer70"]["ci95"]
        resolved_gain += low > 0
        resolved_loss += high < 0
        unresolved += low <= 0 <= high
    return (
        f"Against the fixed Outer70 distribution, point-by-point adaptation gained at "
        f"{resolved_gain}, lost at {resolved_loss}, and was unresolved at {unresolved} of "
        f"{len(results['adaptive_held_out'])} operating points."
    )


def _protocol_b(results: dict[str, Any]) -> str:
    protocol = results["protocol_b"]
    match = protocol["match"]
    if not match["feasible"]:
        return f"Marked infeasible: {match['reason']}."
    rows = [["Attenuation", "Configuration", "Baud (GBaud)", "SER", "R_BMD", "Achievable (Gbit/s)"]]
    for point in protocol["points"]:
        for label in ("Uniform at matched baud", "PS70 (inner)", "Outer70"):
            item = point[label]
            rows.append(
                [
                    f"{point['attenuation_db']} dB",
                    label,
                    f"{item['symbol_rate_Bd'] / 1e9:.4f}",
                    _scientific(item["ser"]),
                    f"{item['r_bmd']:.3f}",
                    f"{item['air_gbps']:.2f}",
                ]
            )
    return (
        f"Target net rate: {protocol['target_net_bps'] / 1e9:.4f} Gbit/s, computed as baud times "
        f"matcher bits per symbol. {match['reason']}. PS70 and Outer70 are matched by "
        "construction. This excludes FEC and so is not a coded throughput.\n\n" + _table(rows)
    )


def markdown(results: dict[str, Any], figures: str, fiber: str = "") -> str:
    """Return the report text. fiber is an optional fiber model subsection."""
    facts = all_facts(results)
    gain = facts["gain"]
    a = facts["a"]
    b = facts["b"]
    rates = facts["rates_14db"]
    exported = results["adaptive_export"]
    never = (
        "stayed at or below Uniform at every PSNR computed"
        if facts["inner_never_wins"]
        else "exceeded Uniform at some PSNR"
    )
    a_runs = results["profile_A"]["back_to_back"]["Uniform"][0]["runs"]
    wins = facts["average_power_inner_wins_db"]
    low_edge, high_edge = facts["average_power_range_db"]
    if wins:
        limit = (
            " The lower end is the edge of the computed range, not a crossover."
            if wins[0] == low_edge
            else ""
        )
        average_text = (
            f"With peak unconstrained and noise scaled to average electrical power, PS70 exceeds "
            f"Uniform between {wins[0]:g} and {wins[-1]:g} dB SNR, within the computed "
            f"{low_edge:g} to {high_edge:g} dB range.{limit} Above that, its lower entropy limits it."
        )
    else:
        average_text = "With peak unconstrained, PS70 did not exceed Uniform in the computed range."
    sections = f"""# OpticPS Research Report

An Open-Source Framework for Probabilistic Shaping in Optical Communications

**{results["banner"]}**

Software version {results["software_version"]}. Configuration SHA-256 {results["config_sha256"]}. Seed {results["seed"]}.

## 1. Executive summary

OpticPS generates Keysight M8199B candidate waveforms for Uniform, Fixed-shaped and Adaptive-shaped PAM4, and simulates, receives and compares them. Hardware playback has not been verified, and no fiber measurement exists.

The main finding is a warning about the requested distributions. Under a fixed drive swing, which is the natural constraint for an unamplified Mach-Zehnder link, PS70 and PS80 place more symbols on inner levels and {never}. Wiegart et al. [1] show the optimum under this constraint is outer-heavy, and this work reproduces that result. At a PSNR of 14 dB the calculated SMD rates are Uniform {rates["Uniform"]:.3f}, PS70 {rates["PS70"]:.3f}, PS80 {rates["PS80"]:.3f}, Outer70 {rates["Outer70"]:.3f} bit/symbol.

In simulated back-to-back transmission at Profile A, near {a["received_dbm"]:.1f} dBm received power:

{_comparison_lines(a)}

The exported Adaptive waveform is simulation-optimized, not adapted to any measurement.

## 2. Research objectives and hypotheses

Objective: compare the three schemes fairly, separating physical constraints from information-theoretic ones.

- H1: under fixed peak swing, inner-heavy distributions lose to Uniform at every operating point. Supported in this model.
- H2: an outer-heavy distribution beats Uniform near 1 bit/symbol. To be tested experimentally.
- H3: adaptation adds value over one good fixed distribution. Tested in simulation in section 12.

## 3. Background and related work

Probabilistic shaping with PAS [3] gained wide use in coherent systems under an average power constraint. IM/DD differs because the signal is non-negative. He et al. [8] reported receiver-sensitivity gains with exponential-like PAM distributions, but noted a launch power penalty at equal extinction ratio. Wiegart et al. [1] add a peak constraint from modulator extinction, and show optimal symmetric, outer-heavy input. Peak-limited channels favour discrete inputs with mass near the boundary [6].

## 4. Theoretical foundation

Maxwell-Boltzmann probabilities:

EQ: P(x_i)=\\frac{{e^{{-\\lambda |x_i|^2}}}}{{Z}},\\quad x_i\\in\\{{-3,-1,+1,+3\\}}

Here lambda = 0 is uniform; lambda > 0 is inner-heavy; lambda < 0 is outer-heavy. Rates follow [1, 3]:

EQ: R_{{\\mathrm{{SMD}}}}=I(X;Y),\\quad R_{{\\mathrm{{BMD}}}}=\\left[H(X)-\\sum_k H(B_k|Y)\\right]^+

PSNR is 9 / sigma squared on the alphabet {{0, 1, 2, 3}}, as in [1]. MAP detection uses:

EQ: \\hat{{x}}=\\arg\\max_x\\ p(y|x)\\,P(x)

Reproduction of [1]: Uniform reaches 1 bit/symbol at {gain["uniform_smd_psnr_db"]:.2f} dB (SMD) and {gain["uniform_bmd_psnr_db"]:.2f} dB (BMD). Outer70 gains {gain["outer70_smd_gain_db"]:.2f} dB and {gain["outer70_bmd_gain_db"]:.2f} dB. The paper gives 0.63 dB for the same BMD case. The rates quoted in section 1 are SMD; the figure below plots BMD.

![Rate versus PSNR at fixed peak]({figures}/rate_vs_psnr.png)

![Optimal outer probability versus PSNR]({figures}/optimal_p0.png)

## 5. Probabilistic shaping methodology

Shaped symbols come from a reversible matcher, not independent sampling. Fixed shaping uses the requested PS70 and PS80, plus the literature benchmark Outer70. The adaptive search spans the whole symmetric family, covering positive and negative lambda, because limiting it to positive lambda would exclude the known optimum.

The exported Adaptive distribution uses P(+-3) = {exported["p_outer"]:.3f}, lambda = {exported["lambda_value"]:.4f}, chosen at the design point where Uniform reaches R_BMD = 1.0 ({exported["design_psnr_db"]:.3f} dB). Near error-free operating points the same search returns nearly uniform input and shaping gain vanishes.

![Entropy versus lambda]({figures}/entropy_vs_lambda.png)

![GMI versus outer probability]({figures}/gmi_vs_p0.png)

![Realised symbol probabilities]({figures}/symbol_histograms.png)

## 6. Distribution matching

CCDM [2] is implemented as an exact enumerative code [5]: the lexicographic rank of a multiset permutation, using exact integers, with k = floor(log2(multinomial)). Blocks are 1024 symbols. Compositions are rounded to integers, so targets are approached, not met exactly: PS70 becomes 154/358/358/154 of 1024.

One symbol error makes a block undecodable or wrong, and no FEC is implemented. Post-matcher BER is thus diagnostic only. This system is not PAS.

![CCDM rate loss versus block length]({figures}/ccdm_rate_loss.png)

## 7. Experimental setup

PLACEHOLDER: no Southampton experiment has been run. The intended setup is M8199B, driver as required, Mach-Zehnder modulator, VOA and fiber, photodiode, and a receiver yet to be identified. Complete this section from the experiment log. The procedure is in output/README_SOUTHAMPTON.md.

## 8. Keysight waveform generation

Files follow the rules in docs/HARDWARE_COMPATIBILITY.md: first row DataOut1, one column, values within -1 to +1, sample count a multiple of 512. The rules came from the project owner's notes of the Programming Guide, which could not be read directly. Profile A is 224 GSa/s, 8 GBaud, 917,504 samples. Profile B is 224 GSa/s, 56 GBaud, 262,144 samples. All waveforms in a group share one data-independent full scale, so levels map to the same voltages.

![Waveform excerpts from the exported Profile A files]({figures}/waveform_excerpts.png)

## 9. Optical channel model

The simulation uses a sine-law modulator with finite extinction, fiber attenuation, chromatic dispersion as an all-pass phase, square-law detection, thermal noise, level-dependent shot noise and receiver filtering. It omits laser noise, Kerr effects, and amplifiers. Electrical symbol energy is not treated as optical power: all optical values come from the field. For a symmetric drive at quadrature, mean power and OMA are equal across distributions; bias error and compression break this.

{fiber}

## 10. Receiver DSP

Resampling, matched filter, circular preamble correlation with polarity detection, phase search, preamble calibration, a 15-tap FFE, and detection. All fitting uses preamble and training symbols only. Metrics are SER, Gray label BER, and R_SMD and R_BMD estimated with the training-fitted channel law.

## 11. Fair comparison methodology

Protocol A holds baud, alphabet, drive swing and link fixed. Protocol B matches net rate. Launch power, received power, OMA, extinction ratio, electrical swing and RMS are recorded separately. The simulated values at the Profile A reference point are:

{_power_table(a)}

Noise seeds are shared across waveforms at each point, making runs paired. Rates near the top of a sweep reflect the entropy ceiling, not better detection.

## 12. Uniform versus fixed versus adaptive results

All values are simulated, mean of {a_runs} runs with bootstrap intervals over runs. Rates are achievable with ideal coding, not delivered throughput.

### Profile A, 8 GBaud, near {a["received_dbm"]:.1f} dBm

{_performance_table(a)}

{_comparison_lines(a)}

### Profile B, 56 GBaud, near {b["received_dbm"]:.1f} dBm

{_performance_table(b)}

{_comparison_lines(b)}

![BER versus estimated SNR]({figures}/ber_vs_snr.png)

![BER versus received power, Profile A]({figures}/ber_vs_rx_A.png)

![SER versus received power, Profile A]({figures}/ser_vs_rx_A.png)

![R_BMD versus received power, Profile A]({figures}/air_vs_rx_A.png)

![Achievable rate versus received power, Profile A]({figures}/throughput_vs_rx_A.png)

![R_BMD versus received power, Profile B]({figures}/air_vs_rx_B.png)

![BER versus fiber length, Profile A]({figures}/ber_vs_fiber_A.png)

![BER versus fiber length, Profile B]({figures}/ber_vs_fiber_B.png)

![Simulated eye diagrams]({figures}/eye_diagrams.png)

### Adaptive versus fixed on held-out runs

Selection used simulated training runs only. Test runs are held out in noise seeds only: the Uniform training frame and the Uniform contender carry the same symbols. Only one parameter is fitted, so any effect should be small. Values are paired differences in R_BMD, bit/symbol.

{_adaptive_table(results)}

{_adaptive_conclusion(results)}

![Adaptive versus fixed]({figures}/adaptive_vs_fixed.png)

### Protocol B

{_protocol_b(results)}

## 13. Statistical analysis

Error rates use Clopper-Pearson intervals [14], which stay valid at low counts but assume independent errors, and so are optimistic under ISI. Rates use a percentile bootstrap over independent runs [12, 13], never over samples. Runs differ only in noise and share one symbol sequence and one link, so these narrow intervals describe noise variation only. They are conditional on this payload and link, and say nothing about variation between experiments. Points with fewer than 10 symbol errors appear in figures only as upper bounds. Physical measurement uncertainty does not apply yet: these are simulations.

## 14. Discussion

The requested PS70 and PS80 trade rate away in this model without gaining margin, since inner levels each have two neighbours while the swing and level spacing stay unchanged. That does not make inner-heavy shaping wrong everywhere. {average_text} Such a gain requires a peak swing that an unamplified modulator link may not provide, as [1, 8] discuss.

An outer-heavy input raises electrical RMS, so a real driver may compress it. Sine compression also narrows outer level spacing, which penalizes outer-heavy input and has not been optimized away here. Measured level spacing will decide this.

At high received power, shaped formats are limited by entropy, so Uniform wins. Shaping is only relevant near its design point. Lower BER at equal baud does not imply more throughput.

## 15. Limitations

- Simulation only; one link model; parameters are generic, not Southampton's.
- No FEC, so reported rates are achievable bounds.
- M8199B rules not independently read; playback unverified; DAC code mapping assumed.
- Finite run count; short frames, particularly Profile A.
- AC coupling, baseline wander, connector and driver effects are not modelled.
- Results at one channel condition do not generalize to others.

## 16. Conclusions and future work

Fixed-peak theory and this simulation agree that inner-heavy shaping is the wrong direction for this link class, and that outer-heavy shaping is the candidate worth measuring. Next: run the Southampton back-to-back test of Uniform against Outer70, identify the receiver, verify M8199B file rules, and add a real FEC only if a coded throughput claim is wanted.

## 17. References

{chr(10).join(f"{i}. {r}" for i, r in enumerate(REFERENCES, 1))}

## 18. Reproducibility appendix

Command: uv sync, then uv run opticps demo. Data: results/synthetic/demo_results.json. Python {results["python"]}, NumPy {results["numpy"]}. Runtime {results["runtime_s"]:.0f} s. Waveform checksums: output/keysight_m8199b/*/checksums.sha256. Decisions and failures: docs/engineering_log/.
"""
    return sections


def _fonts() -> None:
    root = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("DejaVu", str(root / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(root / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")


def _equation(text: str, path: Path) -> Path:
    fig = plt.figure(figsize=(6.5, 0.5))
    fig.text(0.5, 0.5, f"${text}$", ha="center", va="center", fontsize=13)
    fig.savefig(path, dpi=300, transparent=False)
    plt.close(fig)
    return path


def _inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def render_pdf(
    text: str, path: Path, work: Path, banner: str, title: str = "OpticPS Research Report"
) -> None:
    """Render the supported Markdown subset to PDF.

    A figure caption ending in " [analytical]" is labelled analytical; others, simulated.
    """
    _fonts()
    body = ParagraphStyle("body", fontName="DejaVu", fontSize=9.5, leading=13.5, spaceAfter=6)
    h1 = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=20, leading=25, spaceAfter=10)
    h2 = ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=13, leading=17, spaceBefore=11,
                        spaceAfter=5, textColor=colors.HexColor("#1f4e79"), keepWithNext=1)  # fmt: skip
    h3 = ParagraphStyle("h3", parent=h2, fontSize=10.5, leading=14, spaceBefore=7)
    caption = ParagraphStyle("caption", parent=body, fontSize=8, leading=10, alignment=TA_CENTER,
                             textColor=colors.HexColor("#555555"))  # fmt: skip
    cell = ParagraphStyle("cell", parent=body, fontSize=7.5, leading=9.5, spaceAfter=0)
    story: list[Any] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    equations = 0
    width = A4[0] - 4 * cm
    for block in blocks:
        block = block.strip()
        if block.startswith("# "):
            story.append(Paragraph(_inline(block[2:]), h1))
        elif block.startswith("## "):
            story.append(Paragraph(_inline(block[3:]), h2))
        elif block.startswith("### "):
            story.append(Paragraph(_inline(block[4:]), h3))
        elif block.startswith("EQ: "):
            equations += 1
            image = _equation(block[4:], work / f"eq{equations}.png")
            story.append(Image(str(image), width=13 * cm, height=1 * cm))
        elif block.startswith("!["):
            match = re.match(r"!\[(.*)\]\((.*)\)", block)
            assert match is not None
            reader = ImageReader(match.group(2))
            w, h = reader.getSize()
            shown = min(width, 13 * cm)
            label = match.group(1)
            kind = " (simulated)"
            if label.endswith(" [analytical]"):
                label, kind = label.removesuffix(" [analytical]"), " (analytical)"
            story.append(
                KeepTogether(
                    [
                        Image(match.group(2), width=shown, height=shown * h / w),
                        Paragraph(_inline(label) + kind, caption),
                    ]
                )
            )
        elif block.startswith("|"):
            rows = [
                [c.strip() for c in line.strip("|").split("|")]
                for line in block.splitlines()
                if not set(line) <= set("|-: ")
            ]
            data = [[Paragraph(_inline(c), cell) for c in row] for row in rows]
            table = Table(data, colWidths=[width / len(rows[0])] * len(rows[0]), repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.extend([table, Spacer(1, 7)])
        elif block.startswith("- "):
            items = [ListItem(Paragraph(_inline(x[2:]), body)) for x in block.splitlines()]
            story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12))
        elif re.match(r"^1\. ", block):
            for line in block.splitlines():
                story.append(Paragraph(_inline(line), body))
        else:
            story.append(Paragraph(_inline(block), body))

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("DejaVu-Bold", 7)
        canvas.setFillColor(colors.HexColor("#a02020"))
        canvas.drawCentredString(A4[0] / 2, A4[1] - 1.1 * cm, banner)
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(A4[0] / 2, 1 * cm, str(doc.page))
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
        bottomMargin=1.6 * cm, title=title, author="Theerayut Boonkird",
    )  # fmt: skip
    if story and isinstance(story[-1], PageBreak):
        story.pop()
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def build_report(results_path: Path, out_dir: Path) -> Path:
    """Build figures, Markdown and PDF. Returns the PDF path."""
    from opticps.reporting.fiber_report import fiber_section, load_fiber_results

    results = json.loads(results_path.read_text())
    figure_dir = results_path.parent / "figures"
    all_figures(results_path, figure_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    relative = f"../{figure_dir.as_posix()}"
    fiber_results = load_fiber_results(results_path)
    fiber_dir = results_path.parent.parent / "fiber_validation" / "figures"
    fiber_relative = f"../{fiber_dir.as_posix()}"
    text = markdown(
        results,
        relative,
        fiber_section(fiber_results, fiber_relative) if fiber_results else "",
    )
    (out_dir / "OpticPS_Research_Report.md").write_text(text)
    pdf = out_dir / "OpticPS_Research_Report.pdf"
    equations = out_dir / ".equations"
    equations.mkdir(exist_ok=True)
    pdf_text = text.replace(relative, figure_dir.as_posix())
    render_pdf(
        pdf_text.replace(fiber_relative, fiber_dir.as_posix()), pdf, equations, results["banner"]
    )
    for item in equations.glob("*.png"):
        item.unlink()
    equations.rmdir()
    return pdf
