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

A status is either one the comparison layer returns or a word taken from the underlying record
(`FAILED`, `FIT_INVALID`, `INFERRED_REFERENCE`, `REFERENCE_SEQUENCE_MISSING`; `UNSPENT` is the
records' lowercase "unspent" written as a status). `CALIBRATION` is this module's own word for a
number from the training partition: it carries no pass or fail claim.

Evidence label rule, applied here and in `e4_figures` through one function, `label_from_kinds`:
every row declares `evidence_kinds`, the kinds of evidence its reported value is computed from
(`model`, `capture`, `published`; empty when it reports no number). A value computed from captures
only is `EXTERNAL RAW CAPTURE`; from a model only, `SIMULATED`; a model compared with a capture,
`SIMULATED vs EXTERNAL RAW CAPTURE` (the only two-word label); an empty declaration is `UNKNOWN`.
The validator refuses a row whose label differs from its declaration.

Every row also carries `code_version`, `output_hash` and `uncertainty`. `output_hash` is the
SHA-256 of a canonical serialisation of the row's reported values (floats to 6 significant
digits), so it does not depend on the platform or on file bytes. `code_version` is what the source
record itself states about the code that produced the value, or the package version for rows
the E3 modules compute (`--check` proves the matrix equals the code at the commit that holds
it); otherwise null with a reason. `uncertainty` is a bound only where a committed record states
one; otherwise null with a reason. Nothing is estimated here.

Authored independently for this repository.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from opticps import __version__
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
# A statistic that compares a simulated scenario with a capture names both (rule in the docstring).
COMBINED_LABEL = "SIMULATED vs EXTERNAL RAW CAPTURE"
ROW_LABELS = (*LEGAL_LABELS, COMBINED_LABEL)
EVIDENCE_KINDS = ("capture", "model", "published")


def label_from_kinds(kinds: Iterable[str]) -> str:
    """The one place where a declaration of evidence kinds becomes a label."""
    declared = list(kinds)
    unknown = sorted(set(declared) - set(EVIDENCE_KINDS))
    if unknown or len(set(declared)) != len(declared):
        raise BenchmarkError(f"evidence kinds {declared!r} must be unique, from {EVIDENCE_KINDS}")
    chosen = frozenset(declared)
    table = {
        frozenset(): "UNKNOWN",
        frozenset({"capture"}): "EXTERNAL RAW CAPTURE",
        frozenset({"model"}): "SIMULATED",
        frozenset({"published"}): "PUBLISHED DATA",
        frozenset({"model", "capture"}): COMBINED_LABEL,
    }
    if chosen not in table:
        raise BenchmarkError(f"no evidence label for the combination {sorted(chosen)}")
    return table[chosen]


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
    "evidence_kinds",
    "evidence_label",
    "source_label",
    "evidence_paths",
    "code_version",
    "output_hash",
    "uncertainty",
)
HASHED_FIELDS = (
    "id",
    "our_value",
    "source_value",
    "unit",
    "deviation",
    "tolerance",
    "status",
    "evidence_kinds",
    "evidence_label",
    "source_label",
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


def _canonical(value: object) -> object:
    if isinstance(value, float):
        return format(value, ".6g")
    return value


def output_hash(row: dict[str, Any]) -> str:
    """SHA-256 of the row's reported values, serialised canonically (platform independent)."""
    payload = {name: _canonical(row[name]) for name in HASHED_FIELDS}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _stated(value: object, unit: str | None, basis: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "basis": basis}


def _no_bound(basis: str) -> dict[str, Any]:
    return _stated(None, None, basis)


def _row(**fields: Any) -> dict[str, Any]:
    wanted = [name for name in ROW_FIELDS if name not in ("output_hash", "evidence_label")]
    missing = [name for name in wanted if name not in fields]
    if missing:
        raise BenchmarkError(f"row {fields.get('id')!r} lacks fields {missing}")
    row = {name: fields[name] for name in wanted}
    row["evidence_label"] = label_from_kinds(row["evidence_kinds"])
    row["output_hash"] = output_hash(row)
    return {name: row[name] for name in ROW_FIELDS}


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
        evidence_kinds=["model"] if computed else [],
        source_label="PUBLISHED DATA" if published else None,
        evidence_paths=list(paths),
        code_version=(
            _stated(
                f"opticps {__version__}",
                None,
                "package version; scripts/build_evidence_matrix.py --check proves the matrix "
                "equals the code at whichever commit holds it",
            )
            if computed
            else _no_bound("null: this row computes no value, so no code produced one")
        ),
        uncertainty=_no_bound(
            "null: the E3 record states no uncertainty for this row; its tolerance is a "
            "comparison tolerance, not an uncertainty of either value"
        ),
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
_E2_RECORD_PATHS = [
    _PREREG,
    "docs/benchmarks/FIT_HOLDOUT_PLAN.md",
    "docs/benchmarks/teriphic_e2/b2b_model.yaml",
    _E2_NOTICE,
    _REGISTER,
]


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
                    "the pre-registered misfit of the B2B-calibrated surrogate's no-fibre "
                    "prediction against the real B2B evaluation window (plan line 915, model "
                    "versus capture); the "
                    f"2 km criterion limit built from it is {prereg['limits'][key]:.6f}"
                ),
                our_value=float(prereg["b2b_surrogate_misfit"][key]),
                source_value=None,
                unit="normalized (plan R13 metric)",
                deviation=None,
                tolerance=None,
                status="CALIBRATION",
                reason="training partition: no pass or fail claim is made for a calibration number",
                evidence_kinds=["model", "capture"],
                source_label=None,
                evidence_paths=list(_E2_RECORD_PATHS),
                code_version=_no_bound(
                    "null: the pre-registration record states a model hash but no commit or "
                    "code version"
                ),
                uncertainty=_stated(
                    float(prereg["b2b_window_spread"][key]),
                    "normalized (plan R13 metric)",
                    "capture only (no model): b2b_window_spread of this metric in "
                    "preregistered_predictions.yaml, the spread of the real B2B spread window "
                    "against the real B2B evaluation window as the record states it; it is a "
                    "spread, not a confidence interval",
                ),
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
                "data from E2c on and is no longer a holdout; the value is the law model's fit "
                "objective against those capture windows (model versus capture); acceptance check "
                f"{', '.join(law_v2['acceptance']['failed'])} failed (one basin)"
            ),
            our_value=float(law_v2["profiles"]["poly"]["objective"]),
            source_value=None,
            unit="fit objective (E2c plan)",
            deviation=None,
            tolerance=None,
            status="FIT_INVALID",
            reason=str(law_v2["acceptance"]["status"]),
            evidence_kinds=["model", "capture"],
            source_label=None,
            evidence_paths=[
                "docs/benchmarks/teriphic_e2c/law_model_v2.yaml",
                "docs/benchmarks/teriphic_e2c/a2_endpoint_decomposition.md",
                _E2_CLOSING,
                _REGISTER,
            ],
            code_version=_stated(
                str(law_v2["head_commit"]),
                None,
                "head_commit field of law_model_v2.yaml (the commit the record states it was "
                "produced at)",
            ),
            uncertainty=_no_bound("null: the record states no uncertainty for the fit objective"),
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
            evidence_kinds=["model", "capture"],
            source_label=None,
            evidence_paths=[_TWO_KM, _PREREG, _E2_CLOSING, _E2_NOTICE, _REGISTER],
            code_version=_stated(
                str(two_km["head_commit"]),
                None,
                "head_commit field of two_km_result.json (the commit the record states it was "
                "produced at)",
            ),
            uncertainty=_no_bound("null: the record states no uncertainty for psi"),
        )
    )
    rows.append(
        _row(
            id="T-10KM",
            source=_TERIPHIC,
            partition="holdout reserved: 10 km, never read",
            quantity="10 km held-out metrics",
            conditions="stop rule D4 after the 2 km FAIL; reserved once for a differently "
            "designed hypothesis (H3) that does not exist yet; the E2b QA record states that an "
            "audit hook recorded 0 opens or spawns of the 10 km file",
            our_value=None,
            source_value=None,
            unit=None,
            deviation=None,
            tolerance=None,
            status="UNSPENT",
            reason="the 10 km capture is unspent and unread",
            evidence_kinds=[],
            source_label=None,
            evidence_paths=[
                _E2_CLOSING,
                _TWO_KM,
                _REGISTER,
                "docs/orchestration/opticps-v2/handoff/E2b_2km_qa.md",
            ],
            code_version=_no_bound("null: no value was computed for the unspent capture"),
            uncertainty=_no_bound("null: no value exists, so there is nothing to bound"),
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
            evidence_kinds=[],
            source_label=None,
            evidence_paths=[_E2_CLOSING, "docs/benchmarks/MISSING_PARAMETERS.md", _REGISTER],
            code_version=_no_bound("null: no value was computed"),
            uncertainty=_no_bound("null: no value exists, so there is nothing to bound"),
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
            reason="inferred from B2B; BER and SER stay REFERENCE_SEQUENCE_MISSING; the pattern "
            "is inferred from the capture itself and the mismatch is the pattern against the "
            "same capture's verification window, no link model is involved, so the label is "
            "capture only",
            evidence_kinds=["capture"],
            source_label=None,
            evidence_paths=[
                "docs/benchmarks/teriphic_prbs/b2b_sequence_candidate.yaml",
                "docs/benchmarks/teriphic_prbs/prbs_search_result.md",
                _REGISTER,
            ],
            code_version=_stated(
                str(prbs["head_commit"]),
                None,
                "head_commit field of b2b_sequence_candidate.yaml (the commit the record states "
                "it was produced at)",
            ),
            uncertainty=_no_bound("null: the record states no uncertainty for the mismatch rate"),
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


def _validate_provenance(row: dict[str, Any], where: str) -> None:
    version, bound = row["code_version"], row["uncertainty"]
    if not isinstance(version, dict) or set(version) != {"value", "unit", "basis"}:
        raise BenchmarkError(f"{where}: code_version must be a value/unit/basis mapping")
    if version["value"] is not None:
        check_text(version["value"], f"{where} code_version value")
    check_text(version["basis"], f"{where} code_version basis")
    if not isinstance(bound, dict) or set(bound) != {"value", "unit", "basis"}:
        raise BenchmarkError(f"{where}: uncertainty must be a value/unit/basis mapping")
    _check_number(bound["value"], f"{where} uncertainty value")
    check_text(bound["basis"], f"{where} uncertainty basis")
    if bound["value"] is None and bound["unit"] is not None:
        raise BenchmarkError(f"{where}: a null uncertainty carries no unit")
    if bound["value"] is not None and bound["unit"] is None:
        raise BenchmarkError(f"{where}: an uncertainty bound needs a unit")
    if not re.fullmatch(r"[0-9a-f]{64}", str(row["output_hash"])):
        raise BenchmarkError(f"{where}: output_hash must be a SHA-256 hex digest")


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
    if row["evidence_label"] not in ROW_LABELS:
        raise BenchmarkError(f"{where}: evidence_label {row['evidence_label']!r} is not legal")
    if row["source_label"] is not None and row["source_label"] not in ROW_LABELS:
        raise BenchmarkError(f"{where}: source_label {row['source_label']!r} is not legal")
    for label in (row["evidence_label"], row["source_label"]):
        if label is not None and any(word in label for word in FORBIDDEN_LABELS):
            raise BenchmarkError(f"{where}: label {label!r} is not allowed in this repository")
    kinds = row["evidence_kinds"]
    if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
        raise BenchmarkError(f"{where}: evidence_kinds must be a list of strings")
    if row["evidence_label"] != label_from_kinds(kinds):
        raise BenchmarkError(
            f"{where}: evidence_label {row['evidence_label']!r} disagrees with its declared "
            f"evidence_kinds {kinds!r}, which give {label_from_kinds(kinds)!r}"
        )
    if row["our_value"] is not None and not kinds:
        raise BenchmarkError(f"{where}: a reported value needs a declared evidence kind")
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
    _validate_provenance(row, where)
    if row["output_hash"] != output_hash(row):
        raise BenchmarkError(f"{where}: output_hash differs from the row's reported values")


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
