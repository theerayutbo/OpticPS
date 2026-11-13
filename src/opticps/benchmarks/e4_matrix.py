"""Evidence matrix of the external benchmark (gate E4): one row per point.

The matrix is a YAML file, `docs/benchmarks/EVIDENCE_MATRIX.yaml`, written by
`scripts/build_evidence_matrix.py`. Two row families:

* Wiegart (W1 to W9, W4a and W4b separate) and Ran (R1 to R4) rows are built from the E3
  modules (`wiegart_rows`, `ran_rows`); a test rebuilds them and compares with the file, so the
  file cannot drift from the code.
* TERIPHIC rows are read from records already committed (pre-registration, the 2 km scoring
  record, the E2c A2 law model, the pattern-search result). Nothing here opens `data/external/`
  and nothing re-runs a fit or a holdout score. The 10 km capture is not named by any read path
  in this module; its row is `UNSPENT` with null values.

A status is either one the comparison layer returns or the exact word the underlying record uses
(`FAILED`, `FIT_INVALID`, `INFERRED_REFERENCE`, `REFERENCE_SEQUENCE_MISSING`, `UNSPENT`).
`CALIBRATION` marks a number from the training partition: it carries no pass or fail claim.

Authored independently for this repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import functools
import json
import math
from pathlib import Path
from typing import Any

import yaml

from opticps.benchmarks.comparison import Row
from opticps.benchmarks.provenance import BenchmarkError, check_text

MATRIX_PATH = Path("docs/benchmarks/EVIDENCE_MATRIX.yaml")

LEGAL_STATUSES = (
    "MATCH",
    "MISMATCH",
    "NOT COMPARABLE",
    "BLOCKED",
    "FAILED",
    "UNSPENT",
    "CALIBRATION",
    "FIT_INVALID",
    "INFERRED_REFERENCE",
    "REFERENCE_SEQUENCE_MISSING",
)
LEGAL_LABELS = (
    "PUBLISHED DATA",
    "EXTERNAL RAW CAPTURE",
    "SIMULATED",
    "DIGITIZED",
    "UNKNOWN",
)
# No row of this repository may carry a digitised value (licence of the figures is unverified).
FORBIDDEN_LABELS = ("DIGITIZED",)
ROW_FIELDS = (
    "id",
    "source",
    "partition",
    "quantity",
    "conditions",
    "our_value",
    "source_value",
    "unit",
    "deviation",
    "tolerance",
    "status",
    "reason",
    "evidence_label",
    "source_label",
    "evidence_paths",
)

_TERIPHIC = "TERIPHIC (Zenodo 7886498, PD1 PAM4)"
_WIEGART = "Wiegart 2021 (JLT 39(2) 400-405)"
_RAN = "Ran 2025 (Nat. Commun. 16, 6268)"

_REGISTER = "docs/benchmarks/SOURCE_REGISTER.md"
_E3_DOC = "docs/benchmarks/E3_WIEGART_RAN.md"
_E3_TESTS = "tests/test_benchmark_e3.py"
_WIEGART_PATHS = [
    "src/opticps/benchmarks/e3_wiegart.py",
    "src/opticps/benchmarks/published_points.py",
    "src/opticps/benchmarks/comparison.py",
    "configs/benchmarks/wiegart_2021_peak_pam4.yaml",
    _E3_DOC,
    _E3_TESTS,
    _REGISTER,
]
_RAN_PATHS = [
    "src/opticps/benchmarks/e3_ran.py",
    "src/opticps/benchmarks/comparison.py",
    "configs/benchmarks/ran_2025_g652d.yaml",
    _E3_DOC,
    _E3_TESTS,
    _REGISTER,
]
# Rows whose number or ordering is computed although `ComparisonResult` carries no model value.
_COMPUTED_WITHOUT_VALUE = frozenset({"W5", "R4"})
_SOURCE_TEXT_WITHOUT_VALUE = frozenset({"W5"})


def _row(**fields: Any) -> dict[str, Any]:
    missing = [name for name in ROW_FIELDS if name not in fields]
    if missing:
        raise BenchmarkError(f"row {fields.get('id')!r} lacks fields {missing}")
    return {name: fields[name] for name in ROW_FIELDS}


def _module_row(row: Row, source: str, paths: list[str]) -> dict[str, Any]:
    result = row.result
    computed = result.model_value is not None or row.row_id in _COMPUTED_WITHOUT_VALUE
    published = result.published_value is not None or row.row_id in _SOURCE_TEXT_WITHOUT_VALUE
    return _row(
        id=row.row_id,
        source=source,
        partition="not applicable (analytic check)",
        quantity=row.source_text,
        conditions=f"{row.source_location}. Ours: {row.our_text}",
        our_value=result.model_value,
        source_value=result.published_value,
        unit=result.unit,
        deviation=result.deviation,
        tolerance=result.tolerance,
        status=result.status.value,
        reason=result.reason,
        evidence_label="SIMULATED" if computed else "UNKNOWN",
        source_label="PUBLISHED DATA" if published else None,
        evidence_paths=list(paths),
    )


@functools.lru_cache(maxsize=2)
def _e3_rows(root: Path) -> tuple[tuple[Row, ...], tuple[Row, ...]]:
    from opticps.benchmarks.e3_ran import ran_rows
    from opticps.benchmarks.e3_wiegart import wiegart_rows

    return tuple(wiegart_rows()), tuple(ran_rows(root))


def e3_module_rows(root: Path = Path(".")) -> list[dict[str, Any]]:
    """Wiegart and Ran rows, computed by the E3 modules (about 20 s on a loaded machine)."""
    wiegart, ran = _e3_rows(root.resolve())
    return [_module_row(r, _WIEGART, _WIEGART_PATHS) for r in wiegart] + [
        _module_row(r, _RAN, _RAN_PATHS) for r in ran
    ]


def e3_result_rows(root: Path = Path(".")) -> tuple[list[Row], list[Row]]:
    """The raw E3 `Row` objects (Wiegart, Ran), for the figures."""
    wiegart, ran = _e3_rows(root.resolve())
    return list(wiegart), list(ran)


def _load_yaml(root: Path, rel: str) -> Any:
    with (root / rel).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


_METRIC_NAMES = {
    "M1_level_spacing": "M1 level spacing",
    "M2_wasserstein1_amplitude": "M2 Wasserstein-1 amplitude",
    "M3_quantile_error": "M3 quantile error",
    "M4_log_spectral_distance": "M4 log spectral distance",
}
_TWO_KM = "docs/benchmarks/teriphic_e2/two_km_result.json"
_PREREG = "docs/benchmarks/teriphic_e2/preregistered_predictions.yaml"
_E2_NOTICE = "docs/benchmarks/teriphic_e2/NOTICE.md"
_E2_CLOSING = "docs/benchmarks/E2_CLOSING_RECORD.md"
_E2_RECORD_PATHS = [_PREREG, "docs/benchmarks/teriphic_e2/b2b_model.yaml", _E2_NOTICE, _REGISTER]


def teriphic_rows(root: Path = Path(".")) -> list[dict[str, Any]]:
    """TERIPHIC rows from committed records only. No capture is opened, nothing is re-scored."""
    prereg = _load_yaml(root, _PREREG)
    with (root / _TWO_KM).open(encoding="utf-8") as handle:
        two_km = json.load(handle)
    law_v2 = _load_yaml(root, "docs/benchmarks/teriphic_e2c/law_model_v2.yaml")
    prbs = _load_yaml(root, "docs/benchmarks/teriphic_prbs/b2b_sequence_candidate.yaml")
    rows: list[dict[str, Any]] = []
    for key, name in _METRIC_NAMES.items():
        rows.append(
            _row(
                id=f"T-B2B-{key[:2]}",
                source=_TERIPHIC,
                partition="calibration: B2B only (E2 part a)",
                quantity=f"B2B surrogate misfit, {name}",
                conditions=(
                    "50 GBd PAM4, back-to-back, model fitted on the B2B fit window; the value is "
                    "the pre-registered misfit of the B2B-calibrated surrogate against B2B; the "
                    f"2 km criterion limit built from it is {prereg['limits'][key]:.6f}"
                ),
                our_value=float(prereg["b2b_surrogate_misfit"][key]),
                source_value=None,
                unit="normalized (plan R13 metric)",
                deviation=None,
                tolerance=None,
                status="CALIBRATION",
                reason="training partition: no pass or fail claim is made for a calibration number",
                evidence_label="EXTERNAL RAW CAPTURE",
                source_label=None,
                evidence_paths=list(_E2_RECORD_PATHS),
            )
        )
    rows.append(
        _row(
            id="T-E2C-A2",
            source=_TERIPHIC,
            partition="calibration: B2B and 2 km fit windows (E2c A2, after the 2 km holdout)",
            quantity="E2c law model joint calibration, amendment A2",
            conditions=(
                "joint fit on the B2B and 2 km fit windows; the 2 km capture is calibration "
                "data from E2c on and is no longer a holdout; acceptance check "
                f"{', '.join(law_v2['acceptance']['failed'])} failed (one basin)"
            ),
            our_value=float(law_v2["profiles"]["poly"]["objective"]),
            source_value=None,
            unit="fit objective (E2c plan)",
            deviation=None,
            tolerance=None,
            status="FIT_INVALID",
            reason=str(law_v2["acceptance"]["status"]),
            evidence_label="EXTERNAL RAW CAPTURE",
            source_label=None,
            evidence_paths=[
                "docs/benchmarks/teriphic_e2c/law_model_v2.yaml",
                "docs/benchmarks/teriphic_e2c/a2_endpoint_decomposition.md",
                _E2_CLOSING,
                _REGISTER,
            ],
        )
    )
    rows.append(
        _row(
            id="T-2KM",
            source=_TERIPHIC,
            partition="holdout: 2 km, scored once (E2b stage 1)",
            quantity="worst ratio of the four held-out metrics to their pre-registered limits "
            "(psi, pass needs psi <= 1), best of 123 scenarios",
            conditions=(
                f"50 GBd PAM4, 2 km, fibre type and wavelength UNKNOWN, scenarios ASSUMED_G652D; "
                f"best scenario {two_km['best_scenario']}; scenarios scored "
                f"{two_km['scenarios_scored']}; survivors {len(two_km['survivors'])}; "
                f"amplitude ratio vs B2B {two_km['amplitude_ratio_vs_b2b']:.4f} "
                "(reported, not tested)"
            ),
            our_value=float(two_km["scenarios"][two_km["best_scenario"]]["psi"]),
            source_value=None,
            unit="ratio to criterion limit",
            deviation=None,
            tolerance=1.0,
            status="FAILED",
            reason=f"record outcome {two_km['outcome']}, verdict {two_km['verdict']}, claim none",
            evidence_label="EXTERNAL RAW CAPTURE",
            source_label=None,
            evidence_paths=[_TWO_KM, _PREREG, _E2_CLOSING, _E2_NOTICE, _REGISTER],
        )
    )
    rows.append(
        _row(
            id="T-10KM",
            source=_TERIPHIC,
            partition="holdout reserved: 10 km, never read",
            quantity="10 km held-out metrics",
            conditions="stop rule D4 after the 2 km FAIL; reserved once for a differently "
            "designed hypothesis (H3) that does not exist yet; no audit hook opened the file",
            our_value=None,
            source_value=None,
            unit=None,
            deviation=None,
            tolerance=None,
            status="UNSPENT",
            reason="the 10 km capture is unspent and unread",
            evidence_label="UNKNOWN",
            source_label=None,
            evidence_paths=[_E2_CLOSING, _TWO_KM, _REGISTER],
        )
    )
    rows.append(
        _row(
            id="T-BER",
            source=_TERIPHIC,
            partition="not applicable",
            quantity="measured BER or exact SER",
            conditions="no transmitted reference sequence is documented by the record",
            our_value=None,
            source_value=None,
            unit=None,
            deviation=None,
            tolerance=None,
            status="REFERENCE_SEQUENCE_MISSING",
            reason="BER and SER are refused without a validated reference sequence",
            evidence_label="UNKNOWN",
            source_label=None,
            evidence_paths=[_E2_CLOSING, "docs/benchmarks/MISSING_PARAMETERS.md", _REGISTER],
        )
    )
    rows.append(
        _row(
            id="T-PRBS-B2B",
            source=_TERIPHIC,
            partition="calibration side study: B2B only",
            quantity="symbol mismatch of the repeated inferred pattern on the verification window",
            conditions="B2B only; periodic pattern of 8128 symbols, not a standard PRBS; mapping "
            "and level order not identified; a proxy, not a BER",
            our_value=float(prbs["p6"]["mismatch_rate"]),
            source_value=None,
            unit="fraction of symbols",
            deviation=None,
            tolerance=None,
            status=str(prbs["status"]).split(" ")[0],
            reason="inferred from B2B; BER and SER stay REFERENCE_SEQUENCE_MISSING",
            evidence_label="EXTERNAL RAW CAPTURE",
            source_label=None,
            evidence_paths=[
                "docs/benchmarks/teriphic_prbs/b2b_sequence_candidate.yaml",
                "docs/benchmarks/teriphic_prbs/prbs_search_result.md",
                _REGISTER,
            ],
        )
    )
    return rows


def build_matrix(root: Path = Path(".")) -> list[dict[str, Any]]:
    """The full matrix: TERIPHIC, Wiegart, Ran, in that order."""
    return teriphic_rows(root) + e3_module_rows(root)


def dump_matrix(rows: list[dict[str, Any]]) -> str:
    header = (
        "# Evidence matrix of the external benchmark (gate E4), one row per point.\n"
        "# Written by scripts/build_evidence_matrix.py; tests/test_benchmark_e4.py rebuilds the\n"
        "# Wiegart and Ran rows from the E3 modules and compares. Do not edit by hand.\n"
    )
    return header + yaml.safe_dump(
        {"matrix_version": 1, "rows": rows}, sort_keys=False, allow_unicode=True, width=100
    )


def load_matrix(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return list(data["rows"])


def _check_number(value: object, where: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BenchmarkError(f"{where}: must be a finite number or null, got {value!r}")


def validate_row(row: dict[str, Any], root: Path) -> None:
    """Refuse a row with an unknown status or label, a missing field or a missing path."""
    where = f"row {row.get('id')!r}"
    if set(row) != set(ROW_FIELDS):
        odd = sorted(set(row) ^ set(ROW_FIELDS))
        raise BenchmarkError(f"{where}: fields differ from the schema: {odd}")
    check_text(row["id"], f"{where} id")
    for name in ("source", "partition", "quantity", "conditions", "reason"):
        check_text(row[name], f"{where} {name}")
    if row["status"] not in LEGAL_STATUSES:
        raise BenchmarkError(f"{where}: status {row['status']!r} is not one of {LEGAL_STATUSES}")
    if row["evidence_label"] not in LEGAL_LABELS:
        raise BenchmarkError(f"{where}: evidence_label {row['evidence_label']!r} is not legal")
    if row["source_label"] is not None and row["source_label"] not in LEGAL_LABELS:
        raise BenchmarkError(f"{where}: source_label {row['source_label']!r} is not legal")
    for label in (row["evidence_label"], row["source_label"]):
        if label in FORBIDDEN_LABELS:
            raise BenchmarkError(f"{where}: label {label!r} is not allowed in this repository")
    for name in ("our_value", "source_value", "deviation", "tolerance"):
        _check_number(row[name], f"{where} {name}")
    if row["status"] == "MATCH" and (row["our_value"] is None and row["id"] != "W5"):
        raise BenchmarkError(f"{where}: MATCH without our value")
    paths = row["evidence_paths"]
    if not isinstance(paths, list) or not paths:
        raise BenchmarkError(f"{where}: evidence_paths must be a non-empty list")
    for rel in paths:
        check_text(rel, f"{where} evidence path")
        parts = Path(rel).parts
        if Path(rel).is_absolute() or ".." in parts:
            raise BenchmarkError(f"{where}: evidence path {rel!r} must be relative to the repo")
        if parts[:2] == ("data", "external"):
            raise BenchmarkError(f"{where}: evidence path {rel!r} points into data/external")
        if not (root / rel).exists():
            raise BenchmarkError(f"{where}: evidence path {rel!r} does not exist")


def validate_matrix(rows: list[dict[str, Any]], root: Path = Path(".")) -> None:
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        raise BenchmarkError("duplicate row ids in the evidence matrix")
    for row in rows:
        validate_row(row, root)


def render_status_table(rows: list[dict[str, Any]]) -> str:
    """Markdown table of id, status and evidence label; the report embeds it verbatim."""
    lines = ["| Row | Status | Evidence label |", "|---|---|---|"]
    lines += [f"| {r['id']} | {r['status']} | {r['evidence_label']} |" for r in rows]
    return "\n".join(lines)
