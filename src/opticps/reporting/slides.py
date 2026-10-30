"""Build the presentation from one slide model, as editable PPTX and as PDF."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from opticps.reporting.facts import all_facts, verdict
from opticps.reporting.fiber_report import fiber_slide as fiber_slide_text
from opticps.reporting.fiber_report import load_fiber_results
from opticps.reporting.report import _fonts
from opticps.visualization.figures import all_figures

WIDTH_IN, HEIGHT_IN = 13.333, 7.5
BLUE = (0x1F, 0x4E, 0x79)
RED = (0xA0, 0x20, 0x20)
SHORT_BANNER = "SIMULATION ONLY: no Southampton measurements imported"


@dataclass(frozen=True)
class Slide:
    """One slide. The same object feeds both renderers."""

    title: str
    bullets: list[str] = field(default_factory=list)
    image: str | None = None
    simulated: bool = False


def deck(
    results: dict[str, Any],
    figures: Path,
    fiber: dict[str, Any] | None = None,
    fiber_figures: Path | None = None,
) -> list[Slide]:
    """Return slides, built from saved results only. A fiber slide is added if fiber is given."""
    facts = all_facts(results)
    a = facts["a"]
    b = facts["b"]
    rates = facts["rates_14db"]
    exported = results["adaptive_export"]
    fig = lambda name: str(figures / name)  # noqa: E731

    def versus(section: dict[str, Any]) -> list[str]:
        return [
            f"{label} vs Uniform: {verdict(item['mean'], item['ci95'], 'b/sym')}"
            for label, item in section["versus_uniform"].items()
        ]

    adaptive = []
    for point in results["adaptive_held_out"]:
        item = point["paired_difference"]["Outer70"]
        adaptive.append(
            f"{point['attenuation_db']} dB: chose P(±3) = {point['selected_p_outer']:.2f}; "
            f"vs Outer70 {verdict(item['mean'], item['ci95'], 'b/sym')}"
        )
    fiber_slide = []
    if fiber is not None and fiber_figures is not None:
        title, bullets = fiber_slide_text(fiber)
        fiber_slide = [Slide(title, bullets, str(fiber_figures / "before_after_A.png"), True)]
    return [
        Slide(
            "OpticPS: An Open-Source Framework for Probabilistic Shaping in Optical Communications",
            [
                "Research collaboration between researchers at Manchester and Southampton",
                "Uniform, Fixed and Adaptive Shaped PAM4 for IM/DD: technical discussion deck",
                results["banner"],
            ],
        ),
        Slide(
            "Problem statement",
            [
                "Does shaping improve an unamplified IM/DD link, and under which constraint?",
                "Baud rate, entropy, net rate and optical power are separate quantities",
                "A fair comparison must control them explicitly",
                "Lower BER at equal baud is not more throughput",
            ],
        ),
        Slide(
            "PAM4 fundamentals",
            [
                "Levels -3, -1, +1, +3 with Gray labels 00, 01, 11, 10",
                "Uniform carries 2 bit/symbol",
                "Fixed drive swing fixes level spacing, so noise margin stays the same",
                "Electrical energy is not optical power",
            ],
            fig("symbol_histograms.png"),
            True,
        ),
        Slide(
            "Probabilistic shaping and the peak constraint",
            [
                "Under an average-power limit, inner-heavy input helps",
                "A modulator's extinction ratio imposes a peak limit",
                "Then optimal input is outer-heavy (Wiegart et al., 2021)",
                f"14 dB, SMD: Uniform {rates['Uniform']:.3f}, PS70 {rates['PS70']:.3f}, "
                f"PS80 {rates['PS80']:.3f}, Outer70 {rates['Outer70']:.3f}",
            ],
            fig("rate_vs_psnr.png"),
            True,
        ),
        Slide(
            "Maxwell-Boltzmann family",
            [
                "P(x) = exp(-λx²) / Z",
                "λ = 0 uniform; λ > 0 inner-heavy; λ < 0 outer-heavy",
                "PS70 and PS80 have λ > 0",
                "Optimum moves to uniform as PSNR rises",
            ],
            fig("optimal_p0.png"),
            True,
        ),
        Slide(
            "CCDM architecture",
            [
                "Exact enumerative implementation, 1024-symbol blocks",
                "Rate loss: 0.015 bit/symbol for PS70",
                "One symbol error destroys a block",
                "No FEC, so this is not PAS",
            ],
            fig("ccdm_rate_loss.png"),
            True,
        ),
        Slide(
            "System architecture",
            [
                "Bits → CCDM → Gray levels → frame → NRZ or RRC → M8199B CSV",
                "Link simulation or a real capture",
                "Sync → calibrate → FFE → MD or MAP → metrics",
                "Fitting uses preamble and training only",
            ],
        ),
        Slide(
            "Keysight M8199B waveform package",
            [
                "Profile A: 224 GSa/s, 8 GBaud, 28 sps, 917,504 samples",
                "Profile B: 224 GSa/s, 56 GBaud, 4 sps, 262,144 samples",
                "Header DataOut1, within ±1, multiples of 512",
                "CSV rules from owner's notes; playback unverified",
            ],
            fig("waveform_excerpts.png"),
            True,
        ),
        Slide(
            "Receiver DSP",
            [
                "Software sync with polarity and phase search",
                "15-tap FFE trained on known symbols",
                "MAP: argmax p(y|x) P(x), with likelihoods from training",
                "Metrics: SER, label BER, R_SMD, R_BMD",
            ],
            fig("eye_diagrams.png"),
            True,
        ),
        Slide(
            "Experimental fairness",
            [
                "Protocol A: equal baud, equal drive swing",
                "Protocol B: equal net rate, with any baud change reported",
                "Vpp, RMS, launch, received power, OMA, ER recorded separately",
                "Paired runs; bootstrap over runs, not samples",
            ],
        ),
        Slide(
            f"Baseline comparison, Profile A near {a['received_dbm']:.1f} dBm",
            versus(a),
            fig("air_vs_rx_A.png"),
            True,
        ),
        Slide(
            f"Profile B near {b['received_dbm']:.1f} dBm",
            versus(b),
            fig("air_vs_rx_B.png"),
            True,
        ),
        Slide(
            "Adaptive shaping on held-out runs",
            [
                f"Exported file: P(±3) = {exported['p_outer']:.3f}, simulation-optimized",
                *adaptive,
            ],
            fig("adaptive_vs_fixed.png"),
            True,
        ),
        *fiber_slide,
        Slide(
            "Key findings and limitations",
            [
                "PS70 and PS80 are expected to lose at fixed swing",
                "Outer-heavy is the candidate to measure",
                "No FEC: rates are achievable bounds",
                "Model parameters are generic; compression and AC effects need measurement",
            ],
            simulated=True,
        ),
        Slide(
            "Southampton next steps",
            [
                "Confirm receiver model and modulator limits",
                "Verify CSV import on the M8199B",
                "First run: Profile A, Uniform and Outer70, back-to-back",
                "Separate training and held-out captures, 5+ repeats",
                "Then regenerate this analysis from measurements",
            ],
        ),
    ]


def write_pptx(slides: list[Slide], path: Path) -> None:
    """Write an editable PowerPoint file."""
    presentation = Presentation()
    presentation.slide_width = Inches(WIDTH_IN)
    presentation.slide_height = Inches(HEIGHT_IN)
    layout = presentation.slide_layouts[6]
    for model in slides:
        slide = presentation.slides.add_slide(layout)
        title = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.9))
        title.text_frame.word_wrap = True
        run = title.text_frame.paragraphs[0].add_run()
        run.text = model.title
        run.font.size = Pt(30)
        run.font.bold = True
        run.font.color.rgb = RGBColor(*BLUE)
        text_width = 5.6 if model.image else 12.3
        box = slide.shapes.add_textbox(Inches(0.5), Inches(1.45), Inches(text_width), Inches(5.2))
        frame = box.text_frame
        frame.word_wrap = True
        for index, bullet in enumerate(model.bullets):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            line = paragraph.add_run()
            line.text = f"• {bullet}"
            line.font.size = Pt(19 if len(model.bullets) < 5 else 17)
            paragraph.space_after = Pt(11)
        if model.image:
            picture = slide.shapes.add_picture(model.image, Inches(6.3), Inches(1.55))
            scale = min(Inches(6.6) / picture.width, Inches(5.2) / picture.height)
            picture.width = int(picture.width * scale)
            picture.height = int(picture.height * scale)
        if model.simulated:
            note = slide.shapes.add_textbox(Inches(0.5), Inches(6.9), Inches(12.3), Inches(0.4))
            flag = note.text_frame.paragraphs[0].add_run()
            flag.text = SHORT_BANNER
            flag.font.size = Pt(12)
            flag.font.bold = True
            flag.font.color.rgb = RGBColor(*RED)
    presentation.save(str(path))


def write_pdf(slides: list[Slide], path: Path) -> None:
    """Write the same slides as a PDF, rendered directly rather than converted."""
    _fonts()
    width, height = WIDTH_IN * 72, HEIGHT_IN * 72
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    pdf.setTitle("OpticPS Research Presentation")
    blue = colors.Color(*[c / 255 for c in BLUE])
    red = colors.Color(*[c / 255 for c in RED])
    for model in slides:
        title_style = ParagraphStyle("t", fontName="DejaVu-Bold", fontSize=25, leading=30,
                                     textColor=blue)  # fmt: skip
        title = Paragraph(model.title, title_style)
        _, used = title.wrap(width - 72, 80)
        title.drawOn(pdf, 36, height - 25 - used)
        text_width = (5.6 if model.image else 12.3) * 72
        size = 16 if len(model.bullets) < 5 else 14.5
        style = ParagraphStyle("b", fontName="DejaVu", fontSize=size, leading=size * 1.3)
        y = height - 110
        for bullet in model.bullets:
            paragraph = Paragraph(f"• {bullet}", style)
            _, used = paragraph.wrap(text_width, 300)
            paragraph.drawOn(pdf, 36, y - used)
            y -= used + 11
        if model.image:
            reader = ImageReader(model.image)
            w, h = reader.getSize()
            scale = min(6.6 * 72 / w, 5.2 * 72 / h)
            shown, shown_h = w * scale, h * scale
            pdf.drawImage(model.image, 6.3 * 72, height - 112 - shown_h, shown, shown_h)
        if model.simulated:
            pdf.setFont("DejaVu-Bold", 11)
            pdf.setFillColor(red)
            pdf.drawString(36, 25, SHORT_BANNER)
            pdf.setFillColor(colors.black)
        pdf.showPage()
    pdf.save()


def build_slides(results_path: Path, out_dir: Path) -> Path:
    """Build both files. Returns the PPTX path."""
    results = json.loads(results_path.read_text())
    figure_dir = results_path.parent / "figures"
    if not list(figure_dir.glob("*.png")):
        all_figures(results_path, figure_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fiber = load_fiber_results(results_path)
    fiber_dir = results_path.parent.parent / "fiber_validation" / "figures"
    slides = deck(results, figure_dir, fiber, fiber_dir)
    pptx_path = out_dir / "OpticPS_Research_Presentation.pptx"
    write_pptx(slides, pptx_path)
    write_pdf(slides, out_dir / "OpticPS_Research_Presentation.pdf")
    return pptx_path
