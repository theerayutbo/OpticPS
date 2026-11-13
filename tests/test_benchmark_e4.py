"""Gate E4: evidence matrix, figures, report and reproduction checks.

Nothing here needs `data/external/`, and nothing opens a capture.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from opticps.benchmarks import e4_matrix as m
from opticps.benchmarks.e4_figures import (
    BUILDERS,
    FIGURE_DIR,
    Panel,
    build_figures,
    check_series_label,
    save_figures,
)
from opticps.benchmarks.provenance import BenchmarkError

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/benchmarks/BENCHMARK_REPORT.md"
REPRODUCE = ROOT / "docs/benchmarks/REPRODUCE.md"
EXPECTED_IDS = [
    "T-B2B-M1",
    "T-B2B-M2",
    "T-B2B-M3",
    "T-B2B-M4",
    "T-E2C-A2",
    "T-2KM",
    "T-10KM",
    "T-BER",
    "T-PRBS-B2B",
    "W1",
    "W2",
    "W3",
    "W4a",
    "W4b",
    "W5",
    "W6",
    "W7",
    "W8",
    "W9",
    "R1",
    "R2",
    "R3",
    "R4",
]


@pytest.fixture(scope="module")
def committed() -> list[dict[str, Any]]:
    return m.load_matrix(ROOT / m.MATRIX_PATH)


@pytest.fixture(scope="module")
def by_id(committed: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in committed}


@pytest.fixture(scope="module")
def good_row(committed: list[dict[str, Any]]) -> dict[str, Any]:
    return committed[0]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def _rows_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)


# ----------------------------------------------------------------------------- matrix schema
def test_matrix_has_one_row_per_point_in_order(committed: list[dict[str, Any]]) -> None:
    assert [r["id"] for r in committed] == EXPECTED_IDS


def test_committed_matrix_is_valid(committed: list[dict[str, Any]]) -> None:
    m.validate_matrix(committed, ROOT)


def test_every_row_has_legal_status_label_and_existing_paths(
    committed: list[dict[str, Any]],
) -> None:
    for row in committed:
        assert row["status"] in m.LEGAL_STATUSES
        assert row["evidence_label"] in m.LEGAL_LABELS
        assert row["source_label"] is None or row["source_label"] in m.LEGAL_LABELS
        assert row["evidence_paths"]
        for rel in row["evidence_paths"]:
            assert (ROOT / rel).exists(), (row["id"], rel)


def test_no_row_is_digitized_and_none_reads_data_external_or_the_ten_km_capture(
    committed: list[dict[str, Any]],
) -> None:
    for row in committed:
        assert "DIGITIZED" not in (row["evidence_label"], row["source_label"])
        for rel in row["evidence_paths"]:
            assert not rel.startswith("data/")
            assert "10km" not in rel.lower().replace("_", "")


def test_wiegart_and_ran_rows_equal_what_the_modules_return(
    committed: list[dict[str, Any]],
) -> None:
    built = {r["id"]: r for r in m.e3_module_rows(ROOT)}
    stored = {r["id"]: r for r in committed if r["id"][0] in "WR"}
    assert set(built) == set(stored)
    assert len(built) == 14
    for key, row in built.items():
        assert _rows_equal(row, stored[key]), key


def test_teriphic_rows_equal_the_committed_records(committed: list[dict[str, Any]]) -> None:
    built = {r["id"]: r for r in m.teriphic_rows(ROOT)}
    stored = {r["id"]: r for r in committed if r["id"][0] == "T"}
    assert set(built) == set(stored)
    for key, row in built.items():
        assert _rows_equal(row, stored[key]), key


def test_rendered_file_equals_the_committed_file(committed: list[dict[str, Any]]) -> None:
    assert m.dump_matrix(committed) == (ROOT / m.MATRIX_PATH).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- recorded values
def test_statuses_of_record(by_id: dict[str, dict[str, Any]]) -> None:
    status = {k: v["status"] for k, v in by_id.items()}
    assert status["T-2KM"] == "FAILED"
    assert status["T-10KM"] == "UNSPENT"
    assert status["T-BER"] == "REFERENCE_SEQUENCE_MISSING"
    assert status["T-E2C-A2"] == "FIT_INVALID"
    for key in ("W1", "W2", "W3", "W5"):
        assert status[key] == "MATCH"
    for key in ("W4a", "W4b", "W6", "W7", "W8", "W9", "R1", "R2", "R4"):
        assert status[key] == "NOT COMPARABLE"
    assert status["R3"] == "BLOCKED"
    assert "MODEL GAP: CHIRP" in by_id["R1"]["reason"]
    assert "MODEL GAP: CHIRP" in by_id["R2"]["reason"]


def test_ten_km_row_holds_no_value(by_id: dict[str, dict[str, Any]]) -> None:
    row = by_id["T-10KM"]
    for key in ("our_value", "source_value", "deviation", "tolerance", "unit"):
        assert row[key] is None
    assert row["evidence_label"] == "UNKNOWN"


def test_wiegart_gain_rows_stay_inside_the_declared_tolerance(
    by_id: dict[str, dict[str, Any]],
) -> None:
    for key in ("W1", "W2", "W3"):
        row = by_id[key]
        assert row["tolerance"] == 0.01
        assert abs(row["deviation"]) <= 0.01
        assert row["source_label"] == "PUBLISHED DATA"
        assert row["evidence_label"] == "SIMULATED"


def test_refused_rows_carry_no_deviation(by_id: dict[str, dict[str, Any]]) -> None:
    for row in by_id.values():
        if row["status"] != "MATCH":
            assert row["deviation"] is None, row["id"]


def test_two_km_psi_is_the_worst_metric_over_limit_in_the_record(
    by_id: dict[str, dict[str, Any]],
) -> None:
    record = json.loads((ROOT / "docs/benchmarks/teriphic_e2/two_km_result.json").read_text())
    best = record["scenarios"][record["best_scenario"]]["metrics"]
    worst = max(best[k] / record["limits"][k] for k in best)
    assert by_id["T-2KM"]["our_value"] == pytest.approx(worst, rel=1e-9)
    assert by_id["T-2KM"]["our_value"] > 1.0
    assert record["survivors"] == []
    assert record["outcome"] == "FAIL" and record["verdict"] == "FAILED"


# ----------------------------------------------------------------------------- negative tests
def _bad(row: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out = copy.deepcopy(row)
    out.update(changes)
    return out


def test_unknown_status_is_rejected(good_row: dict[str, Any]) -> None:
    with pytest.raises(BenchmarkError, match="status"):
        m.validate_row(_bad(good_row, status="VALIDATED"), ROOT)
    with pytest.raises(BenchmarkError, match="status"):
        m.validate_row(_bad(good_row, status="match"), ROOT)


def test_unknown_or_digitized_label_is_rejected(good_row: dict[str, Any]) -> None:
    with pytest.raises(BenchmarkError, match="evidence_label"):
        m.validate_row(_bad(good_row, evidence_label="MEASURED"), ROOT)
    with pytest.raises(BenchmarkError, match="not allowed"):
        m.validate_row(_bad(good_row, evidence_label="DIGITIZED"), ROOT)
    with pytest.raises(BenchmarkError, match="source_label"):
        m.validate_row(_bad(good_row, source_label="figure"), ROOT)


def test_missing_empty_or_unsafe_paths_are_rejected(good_row: dict[str, Any]) -> None:
    for paths in (
        [],
        None,
        ["docs/benchmarks/NO_SUCH_FILE.md"],
        ["/etc/hosts"],
        ["../OpticPS/pyproject.toml"],
        ["data/external/teriphic"],
    ):
        with pytest.raises(BenchmarkError):
            m.validate_row(_bad(good_row, evidence_paths=paths), ROOT)


def test_bad_numbers_fields_and_duplicates_are_rejected(good_row: dict[str, Any]) -> None:
    with pytest.raises(BenchmarkError, match="finite"):
        m.validate_row(_bad(good_row, our_value=float("nan")), ROOT)
    with pytest.raises(BenchmarkError, match="finite"):
        m.validate_row(_bad(good_row, our_value=True), ROOT)
    incomplete = copy.deepcopy(good_row)
    del incomplete["reason"]
    with pytest.raises(BenchmarkError, match="schema"):
        m.validate_row(incomplete, ROOT)
    with pytest.raises(BenchmarkError, match="duplicate"):
        m.validate_matrix([good_row, copy.deepcopy(good_row)], ROOT)
    with pytest.raises(BenchmarkError):
        m.validate_row(_bad(good_row, reason="  "), ROOT)


def test_match_without_our_value_is_rejected(good_row: dict[str, Any]) -> None:
    with pytest.raises(BenchmarkError, match="MATCH"):
        m.validate_row(_bad(good_row, status="MATCH", our_value=None), ROOT)


# ----------------------------------------------------------------------------- figures
@pytest.fixture(scope="module")
def specs() -> list[Any]:
    return build_figures(ROOT)


def test_figure_set_matches_the_committed_images(specs: list[Any]) -> None:
    names = sorted(s.name for s in specs)
    assert len(names) == len(BUILDERS) == 4
    committed = sorted(p.stem for p in (ROOT / FIGURE_DIR).glob("*.png"))
    assert committed == names


def test_every_series_has_exactly_one_legal_label(specs: list[Any]) -> None:
    for spec in specs:
        assert spec.panels
        for panel in spec.panels:
            assert panel.labels, spec.name
            handles, legend_labels = panel.ax.get_legend_handles_labels()
            assert sorted(legend_labels) == sorted(panel.labels), spec.name
            assert len(handles) == len(panel.labels)
            for label in panel.labels:
                check_series_label(label)
            assert all(not ln.get_label().startswith("_") for ln in panel.ax.get_lines())
            bar_patches = sum(len(c) for c in panel.ax.containers)
            assert len(panel.ax.patches) == bar_patches, spec.name


def test_no_digitized_series_and_no_measured_point_for_wiegart_or_ran(specs: list[Any]) -> None:
    for spec in specs:
        for panel in spec.panels:
            assert not any(label.startswith("DIGITIZED") for label in panel.labels)
            if spec.name.startswith("ran_"):
                assert all(label.startswith("SIMULATED") for label in panel.labels)
                assert not panel.ax.collections
            if spec.name.startswith("wiegart_"):
                assert all(
                    label.split(" | ")[0] in ("SIMULATED", "PUBLISHED DATA")
                    for label in panel.labels
                )


def test_wiegart_published_points_are_the_three_running_text_numbers(specs: list[Any]) -> None:
    spec = next(s for s in specs if s.name == "wiegart_gain_check")
    panel = spec.panels[0]
    published = [c for c in panel.ax.collections if c.get_label().startswith("PUBLISHED DATA")]
    assert len(published) == 1
    ys = sorted(float(y) for y in published[0].get_offsets()[:, 1])
    assert ys == [0.63, 0.71, 0.83]


def test_saved_images_are_small_png(specs: list[Any], tmp_path: Path) -> None:
    for path in save_figures(specs, tmp_path):
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert path.stat().st_size < 300_000
    for path in (ROOT / FIGURE_DIR).glob("*.png"):
        assert path.stat().st_size < 300_000


def test_unlabelled_or_illegal_series_are_rejected() -> None:
    fig_specs = build_figures(ROOT)
    panel = Panel(fig_specs[0].panels[0].ax, forbidden=("DIGITIZED",))
    for label in (None, "", "  ", "series 1", "_nolegend_", "simulated", "MEASURED | x"):
        with pytest.raises(BenchmarkError):
            panel.line([0, 1], [0, 1], label)  # type: ignore[arg-type]
    with pytest.raises(BenchmarkError, match="exactly one"):
        panel.line([0, 1], [0, 1], "SIMULATED | PUBLISHED DATA")
    with pytest.raises(BenchmarkError, match="not allowed"):
        panel.line([0, 1], [0, 1], "DIGITIZED | paper curve")
    with pytest.raises(BenchmarkError, match="not allowed"):
        panel.points([0], [0], "DIGITIZED")
    assert check_series_label("DIGITIZED | x") == "DIGITIZED"  # legal word; figures forbid it


# ----------------------------------------------------------------------------- report
HEADER = (
    "| Source | Asset availability and verified format | Rights status | Implemented pipeline "
    "| Calibration partition | Holdout result | Limitations | Evidence paths |"
)


def _final_rows(text: str) -> dict[str, str]:
    lines = text.splitlines()
    start = lines.index(HEADER)
    rows = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows[line.split("|")[1].strip()] = line
    return rows


def test_report_has_the_eight_column_table_with_three_rows() -> None:
    text = REPORT.read_text(encoding="utf-8")
    rows = _final_rows(text)
    assert list(rows) == ["TERIPHIC", "Wiegart 2021", "Ran 2025"]
    for line in rows.values():
        assert len(line.strip().strip("|").split("|")) == 8


def test_report_states_the_required_facts() -> None:
    text = REPORT.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    for phrase in (
        "2 km holdout: FAILED",
        "Gate E2 is PARTIAL",
        "10 km is `UNSPENT` and unread",
        "within 0.01 dB",
        "not experimental validation",
        "W4a, W4b are NOT COMPARABLE",
        "NOT COMPARABLE with `MODEL GAP: CHIRP`",
        "(R3) are `BLOCKED`",
    ):
        assert phrase in flat, phrase


def test_report_status_table_is_the_matrix_and_no_refused_row_says_match(
    committed: list[dict[str, Any]],
) -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert m.render_status_table(committed) in text
    table = {
        cells[0]: cells[1]
        for cells in (
            [c.strip() for c in line.strip().strip("|").split("|")]
            for line in text.splitlines()
            if re.match(r"\| (T-|W\d|R\d)", line)
        )
    }
    assert set(table) == set(EXPECTED_IDS)
    for row in committed:
        assert table[row["id"]] == row["status"]
        if row["status"] != "MATCH":
            assert table[row["id"]] != "MATCH"
    rows = _final_rows(text)
    for source in ("TERIPHIC", "Ran 2025"):
        assert not re.search(r"(?<![A-Z_])MATCH\b", rows[source]), source


def test_every_repo_path_named_in_the_docs_exists() -> None:
    pattern = re.compile(r"`((?:docs|src|configs|scripts|tests)/[A-Za-z0-9_./-]+)`")
    for doc in (REPORT, REPRODUCE):
        for rel in pattern.findall(doc.read_text(encoding="utf-8")):
            rel = rel.rstrip(".")
            if rel.endswith("/"):
                assert (ROOT / rel).is_dir(), (doc.name, rel)
            else:
                assert (ROOT / rel).exists(), (doc.name, rel)


def test_no_hardware_validation_claim_and_no_local_identity() -> None:
    files = [
        REPORT,
        REPRODUCE,
        ROOT / m.MATRIX_PATH,
        ROOT / "src/opticps/benchmarks/e4_matrix.py",
        ROOT / "src/opticps/benchmarks/e4_figures.py",
        ROOT / "scripts/build_evidence_matrix.py",
        ROOT / "scripts/make_benchmark_figures.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text and "theerayut" not in text, path
        assert not re.search(r"\b(TODO|FIXME|HACK|XXX)\b", text), path
    flat = " ".join(REPORT.read_text(encoding="utf-8").split())
    for sentence in re.findall(r"[^.]*Southampton[^.]*\.", flat):
        assert " no " in sentence or "not" in sentence, sentence
    assert "validated on" not in flat.lower()


# ----------------------------------------------------------------------------- CLI help
COMMANDS = {
    "scripts/build_evidence_matrix.py": [],
    "scripts/make_benchmark_figures.py": [],
    "scripts/freeze_teriphic_e2.py": [],
    "scripts/score_teriphic_e2.py": [],
    "scripts/power_study_e2c.py": [],
    "scripts/prbs_search_b2b.py": [],
    "opticps benchmark inspect-format": ["-m", "opticps.cli.main", "benchmark", "inspect-format"],
}


def test_every_documented_command_is_in_the_help_list() -> None:
    text = REPRODUCE.read_text(encoding="utf-8")
    for name in re.findall(r"\.venv/bin/python (scripts/[a-z0-9_]+\.py)", text):
        assert name in COMMANDS, name
    assert "-m opticps.cli.main benchmark inspect-format" in text
    for name in COMMANDS:
        if name.startswith("scripts/"):
            assert name in text, name


@pytest.mark.parametrize("name", list(COMMANDS))
def test_help_exits_zero_and_is_not_empty(name: str) -> None:
    args = COMMANDS[name] or [name]
    done = subprocess.run(
        [sys.executable, *args, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "usage" in done.stdout.lower()
    assert len(done.stdout.split()) > 15
