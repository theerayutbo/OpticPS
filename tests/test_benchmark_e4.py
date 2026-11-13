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

from opticps import __version__
from opticps.benchmarks import e4_matrix as m
from opticps.benchmarks.e4_figures import (
    BUILDERS,
    FIGURE_DIR,
    SPEC_KEY,
    Panel,
    build_figures,
    check_series_label,
    read_png_text,
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
        assert row["evidence_label"] in m.ROW_LABELS
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


def test_evidence_label_rule(by_id: dict[str, dict[str, Any]]) -> None:
    """Captures only: EXTERNAL RAW CAPTURE. Simulated scenario against a capture: both words."""
    assert m.COMBINED_LABEL == "SIMULATED vs EXTERNAL RAW CAPTURE"
    assert m.ROW_LABELS == (*m.LEGAL_LABELS, m.COMBINED_LABEL)
    assert by_id["T-2KM"]["evidence_label"] == m.COMBINED_LABEL
    for key in ("T-B2B-M1", "T-B2B-M2", "T-B2B-M3", "T-B2B-M4", "T-E2C-A2", "T-PRBS-B2B"):
        assert by_id[key]["evidence_label"] == "EXTERNAL RAW CAPTURE", key
    for row in by_id.values():
        if row["id"][0] in "WR":
            assert row["evidence_label"] in ("SIMULATED", "UNKNOWN"), row["id"]


# ----------------------------------------------------------------------------- provenance fields
def test_every_row_carries_code_version_output_hash_and_uncertainty(
    committed: list[dict[str, Any]],
) -> None:
    for row in committed:
        assert re.fullmatch(r"[0-9a-f]{64}", row["output_hash"]), row["id"]
        assert row["output_hash"] == m.output_hash(row), row["id"]
        for name in ("code_version", "uncertainty"):
            assert set(row[name]) == {"value", "unit", "basis"}, (row["id"], name)
            assert row[name]["basis"].strip()
            if row[name]["value"] is None:
                assert row[name]["unit"] is None
                assert row[name]["basis"].startswith("null:"), (row["id"], name)


def test_code_version_is_what_the_record_states_or_the_package_version(
    by_id: dict[str, dict[str, Any]],
) -> None:
    two_km = json.loads((ROOT / "docs/benchmarks/teriphic_e2/two_km_result.json").read_text())
    assert by_id["T-2KM"]["code_version"]["value"] == two_km["head_commit"]
    for key, row in by_id.items():
        value = row["code_version"]["value"]
        if key[0] in "WR":
            assert value == f"opticps {__version__}", key
            assert "--check" in row["code_version"]["basis"]
        if value is not None and key[0] == "T":
            assert re.fullmatch(r"[0-9a-f]{40}", value), key
    for key in ("T-B2B-M1", "T-10KM", "T-BER"):
        assert by_id[key]["code_version"]["value"] is None


def test_uncertainty_is_only_a_bound_a_record_states(by_id: dict[str, dict[str, Any]]) -> None:
    prereg = m._load_yaml(ROOT, m._PREREG)
    for key, name in (("T-B2B-M1", "M1_level_spacing"), ("T-B2B-M4", "M4_log_spectral_distance")):
        assert by_id[key]["uncertainty"]["value"] == prereg["b2b_window_spread"][name]
        assert "not a confidence interval" in by_id[key]["uncertainty"]["basis"]
    stated = [k for k, v in by_id.items() if v["uncertainty"]["value"] is not None]
    assert sorted(stated) == ["T-B2B-M1", "T-B2B-M2", "T-B2B-M3", "T-B2B-M4"]


def test_output_hash_is_canonical_and_tracks_every_reported_value(
    good_row: dict[str, Any],
) -> None:
    again = copy.deepcopy(good_row)
    again["our_value"] = good_row["our_value"] * (1 + 1e-9)  # below 6 significant digits
    assert m.output_hash(again) == good_row["output_hash"]
    for name, value in (
        ("our_value", good_row["our_value"] * 1.001),
        ("status", "MISMATCH"),
        ("evidence_label", "SIMULATED"),
        ("unit", "other"),
        ("id", "X"),
    ):
        changed = copy.deepcopy(good_row)
        changed[name] = value
        assert m.output_hash(changed) != good_row["output_hash"], name


def test_a_hand_edited_value_or_provenance_is_rejected(good_row: dict[str, Any]) -> None:
    with pytest.raises(BenchmarkError, match="output_hash"):
        m.validate_row(_bad(good_row, our_value=good_row["our_value"] * 1.5), ROOT)
    with pytest.raises(BenchmarkError, match="output_hash"):
        m.validate_row(_bad(good_row, output_hash="0" * 64), ROOT)
    with pytest.raises(BenchmarkError, match="code_version"):
        m.validate_row(_bad(good_row, code_version="abc"), ROOT)
    with pytest.raises(BenchmarkError, match="uncertainty"):
        m.validate_row(_bad(good_row, uncertainty={"value": 1.0}), ROOT)
    with pytest.raises(BenchmarkError, match="unit"):
        m.validate_row(_bad(good_row, uncertainty={"value": 1.0, "unit": None, "basis": "x"}), ROOT)
    with pytest.raises(BenchmarkError, match="legal"):
        m.validate_row(_bad(good_row, evidence_label="SIMULATED vs PUBLISHED DATA"), ROOT)
    with pytest.raises(BenchmarkError, match="not allowed"):
        m.validate_row(_bad(good_row, evidence_label="DIGITIZED"), ROOT)


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
    assert len(names) == len(BUILDERS) == 5
    committed = sorted(p.stem for p in (ROOT / FIGURE_DIR).glob("*.png"))
    assert committed == names


def test_committed_images_carry_the_hash_of_the_current_specification(specs: list[Any]) -> None:
    """Binds each committed PNG to the code's labels and plotted numbers without pixel equality."""
    for spec in specs:
        text = read_png_text(ROOT / FIGURE_DIR / f"{spec.name}.png")
        assert text.get(SPEC_KEY) == spec.specification_hash(), spec.name


def test_saved_png_carries_the_specification_hash(specs: list[Any], tmp_path: Path) -> None:
    for spec, path in zip(specs, save_figures(specs, tmp_path), strict=True):
        assert read_png_text(path)[SPEC_KEY] == spec.specification_hash()


def test_specification_changes_with_a_label_a_number_or_the_title(specs: list[Any]) -> None:
    spec = next(s for s in specs if s.name == "teriphic_two_km_ratios")
    base = spec.specification_hash()
    series = spec.panels[0].series[1]
    old_label, old_y = series.label, list(series.y)
    series.label = "SIMULATED | B2B copy vs 2 km capture"
    assert spec.specification_hash() != base
    series.label = old_label
    series.y[0] = "9.9"
    assert spec.specification_hash() != base
    series.y[:] = old_y
    assert spec.specification_hash() == base
    spec.panels[0].ax.set_title("other")
    assert spec.specification_hash() != base


def test_every_series_label_agrees_with_the_matrix_cell_it_stands_for(
    specs: list[Any], by_id: dict[str, dict[str, Any]]
) -> None:
    bound = 0
    for spec in specs:
        for panel in spec.panels:
            for series in panel.series:
                for row_id, name in series.matrix_refs:
                    assert by_id[row_id][name] == series.evidence_label, (spec.name, row_id, name)
                    bound += 1
    assert bound == 3 + 3 + 2 + 1  # W1-W3 ours, W1-W3 text, R4 twice, T-2KM once


def test_teriphic_series_follow_the_evidence_label_rule(specs: list[Any]) -> None:
    labels = {
        s.name: [series.evidence_label for p in s.panels for series in p.series] for s in specs
    }
    assert labels["teriphic_two_km_ratios"] == [m.COMBINED_LABEL, "EXTERNAL RAW CAPTURE"]
    fibre = labels["teriphic_fibre_sensitivity"]
    assert fibre.count(m.COMBINED_LABEL) == 6 and fibre[-1] == "EXTERNAL RAW CAPTURE"
    assert len(fibre) == 7


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


def test_fibre_sensitivity_covers_all_scenarios_and_shows_the_failure(specs: list[Any]) -> None:
    spec = next(s for s in specs if s.name == "teriphic_fibre_sensitivity")
    panel = spec.panels[0]
    record = json.loads((ROOT / "docs/benchmarks/teriphic_e2/two_km_result.json").read_text())
    scenario_lines = [ln for ln in panel.ax.get_lines() if ln.get_label().startswith("SIMULATED")]
    assert sum(len(ln.get_xdata()) for ln in scenario_lines) == record["scenarios_scored"] == 123
    assert min(float(v) for ln in scenario_lines for v in ln.get_ydata()) > 1.0
    assert "PARTIAL/FAILED" in panel.ax.get_title() and "not a fit" in panel.ax.get_title()
    assert record["survivors"] == []


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
    combined = "SIMULATED vs EXTERNAL RAW CAPTURE | best scenario"
    assert check_series_label(combined) == m.COMBINED_LABEL
    assert check_series_label("EXTERNAL RAW CAPTURE | B2B copy") == "EXTERNAL RAW CAPTURE"
    for bad in (
        "SIMULATED vs PUBLISHED DATA | x",
        "EXTERNAL RAW CAPTURE vs SIMULATED | x",
        "SIMULATED vs EXTERNAL RAW CAPTURE | UNKNOWN",
        "SIMULATED vs EXTERNAL RAW CAPTURE vs DIGITIZED",
    ):
        with pytest.raises(BenchmarkError):
            check_series_label(bad)
    with pytest.raises(BenchmarkError, match="not allowed"):
        check_series_label("DIGITIZED | x", ("DIGITIZED",))


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


def test_report_figure_table_carries_each_figures_evidence_labels(specs: list[Any]) -> None:
    text = REPORT.read_text(encoding="utf-8")
    rows = {
        re.search(r"`([a-z_]+)\.png`", line).group(1): line  # type: ignore[union-attr]
        for line in text.splitlines()
        if re.match(r"\| `[a-z_]+\.png` ", line)
    }
    assert sorted(rows) == sorted(s.name for s in specs)
    for spec in specs:
        heads = {series.evidence_label for p in spec.panels for series in p.series}
        for head in heads:
            assert head in rows[spec.name], (spec.name, head)
        # a combined label may not be reduced to its SIMULATED half in the table
        if m.COMBINED_LABEL in heads:
            assert "SIMULATED vs EXTERNAL RAW CAPTURE" in rows[spec.name]


def test_report_and_reproduce_state_the_corrected_facts() -> None:
    flat = " ".join(REPORT.read_text(encoding="utf-8").split())
    assert "need captures to be read again" not in flat
    assert "the words of the underlying record" not in flat
    assert "`CALIBRATION` is this report's own word" in flat
    assert 'the records\' lowercase "unspent"' in flat
    assert "scored against the holdout" in flat and "FIT_HOLDOUT_PLAN.md` line 937" in flat
    assert "no aligned prediction passed" in flat and "must not be read" in flat
    assert "PARTIAL/FAILED" in flat and "not a fit" in flat
    assert "--check" in flat and "whichever commit holds it" in flat
    repro = REPRODUCE.read_text(encoding="utf-8")
    meta = repro.index("inspect-format --metadata-only")
    assert meta < repro.index("## 2. What needs")
    assert "exit 0" in repro[meta : meta + 400]
    section2 = repro[repro.index("## 2. What needs") : repro.index("## 3.")]
    assert "--metadata-only`) |" not in section2  # no table row of section 2 lists it


def test_ten_km_row_states_what_the_record_says() -> None:
    row = {r["id"]: r for r in m.load_matrix(ROOT / m.MATRIX_PATH)}["T-10KM"]
    assert "no audit hook opened the file" not in row["conditions"]
    assert "audit hook recorded 0 opens or spawns of the 10 km file" in row["conditions"]
    record = (ROOT / "docs/orchestration/opticps-v2/handoff/E2b_2km_qa.md").read_text()
    assert "The hook recorded 0 opens or spawns of the 10 km" in record


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
