import json
import re
from pathlib import Path

import numpy as np
import pytest
from pptx import Presentation
from pypdf import PdfReader

from opticps.cli.main import build_parser, main
from opticps.reporting.facts import all_facts, verdict
from opticps.reporting.report import build_report, markdown
from opticps.reporting.slides import build_slides

RESULTS = Path("results/synthetic/demo_results.json")
needs_results = pytest.mark.skipif(not RESULTS.exists(), reason="run opticps simulate first")


def test_verdict_does_not_overclaim():
    assert verdict(0.1, (0.05, 0.2), "b").startswith("higher")
    assert verdict(-0.1, (-0.2, -0.05), "b").startswith("lower")
    assert verdict(0.01, (-0.02, 0.05), "b").startswith("not resolved")


def test_cli_exposes_all_commands():
    text = build_parser().format_help()
    for name in "validate generate simulate ingest analyze compare report slides demo".split():
        assert name in text
    with pytest.raises(SystemExit):
        main(["--version"])


def test_compare_fails_clearly_without_analysis(tmp_path, capsys):
    assert main(["compare", "--results", str(tmp_path)]) == 1
    assert "analyze first" in capsys.readouterr().err


def test_engineering_log_is_complete():
    root = Path("docs/engineering_log")
    for name in "README STATUS LOG DECISIONS FINDINGS FAILURES VERIFICATION REPRODUCE".split():
        assert (root / f"{name}.md").read_text().strip()
    assert re.search(r"Last commit: [0-9a-f]{7}", (root / "STATUS.md").read_text())


def test_public_text_keeps_status_claims_honest():
    guide = Path("output/README_SOUTHAMPTON.md").read_text()
    assert "has **not** been verified" in guide
    assert "Do not estimate it" in guide
    assert "No SCPI is sent" in Path("docs/KEYSIGHT_SETUP.md").read_text()


@needs_results
def test_report_and_slides_build_with_banner(tmp_path):
    pdf = build_report(RESULTS, tmp_path)
    reader = PdfReader(pdf)
    text = " ".join(page.extract_text() for page in reader.pages)
    assert "SIMULATION RESULTS ONLY" in text
    assert "17. References" in text and "18. Reproducibility appendix" in text
    pptx = build_slides(RESULTS, tmp_path)
    deck = Presentation(pptx)
    assert 12 <= len(deck.slides) <= 18
    pptx_words = set()
    for slide in deck.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                pptx_words |= set(shape.text_frame.text.split())
    slide_pdf = PdfReader(tmp_path / "OpticPS_Research_Presentation.pdf")
    assert len(slide_pdf.pages) == len(deck.slides)
    pdf_words = set(" ".join(p.extract_text() for p in slide_pdf.pages).split())
    assert len(pptx_words - pdf_words) / len(pptx_words) < 0.02


@needs_results
def test_every_table_value_comes_from_results():
    results = json.loads(RESULTS.read_text())
    facts = all_facts(results)
    text = markdown(results, "figures")
    for row in facts["a"]["table"]:
        assert f"{row['r_bmd']:.3f}" in text
    assert results["config_sha256"] in text


@needs_results
def test_results_are_marked_simulated_and_ser_is_sane():
    results = json.loads(RESULTS.read_text())
    assert results["data_source"] == "simulated"
    for points in results["profile_A"]["back_to_back"].values():
        rates = [p["r_bmd"] for p in points]
        assert all(0 <= r <= 2.0 for r in rates)
        assert rates[0] > rates[-1]
        assert np.all(np.diff([p["received_dbm"] for p in points]) < 0)
