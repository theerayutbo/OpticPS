"""Gate N0 (NANF workstream): plan pin, provenance vocabulary, checksum record, no third-party data.

Offline. These tests need no external data; when `data/external/nanf_hong2021/` is present they also
check the file hashes, and they pass without it.
"""

import dataclasses
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from nanf_workbook_fixture import build_cells, make_workbook
from opticps.measurement import nanf_benchmark as nb
from opticps.measurement.nanf_import import (
    DataRole,
    NanfWorkbook,
    read_nanf_workbook,
    series_key,
)
from opticps.optical_channel.fiber import (
    FiberProfileError,
    OutOfValidityRangeError,
    load_fiber_config,
    resolve_profile,
)

PLAN = Path("docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md")
SOURCES = Path("docs/NANF_SOURCES_AND_PROVENANCE.md")
DATA_DIR = Path("data/external/nanf_hong2021")

# Original pin (2026-10-31, commit 9a891c9), set before any workbook value was read. Amendment 1
# (N0 fix round) is recorded in the plan; it supersedes this pin with the one below. A deliberate
# amendment must change the current pin and add a dated section to the plan.
PLAN_SHA256_ORIGINAL = "c4771dc125c3daeaf28b429de2f31f3ca25a5d3645a6f59e1d8dd9b9bf0bef22"
# Pin after Amendment 1 (commit 843d223); replaced at Amendment 2 (Gate N1), then at Amendment 3
# (N1 fix round), then at Amendment 4 (N2 fix round), then at Amendment 5 (Gate N3 step 1), then at
# Amendment 6 (N3 part a fix round), then at Amendment 7 (lost-lock runs), then at Amendment 8 (second review), then at Amendment 9 (closing review), then at Amendment 10 (fourth review), then at Amendment 11 (N3 part b).
PLAN_SHA256_AMENDMENT1 = "92b20966c409958729946f31243216b49fe796d7b9f4ac22f33f30c854dce5c0"
PLAN_SHA256_AMENDMENT2 = "ec0f325a118fcc8162e21de2b6acf1662b6d3ea6db14bfed0c3a507ff2827aa5"
PLAN_SHA256_AMENDMENT3 = "0a3897ad0b22acca7710faf61acc40d97f846c6829eb6fc26e1ece3f7ff4f2c4"
PLAN_SHA256_AMENDMENT4 = "bc85d32c0fa3264034bfeb87872950ed2a8e7a4105b53b84c7b6256c10d17dbe"
PLAN_SHA256_AMENDMENT5 = "c5da4067f6c58cf4d9ddc9372cad79dd0e63e4f74d70374e8a0241cd1e06dcff"
PLAN_SHA256_AMENDMENT6 = "2127d883702715a3432cb8d25ed2f5a970a8910b46368ad2ed50cb8905f60905"
PLAN_SHA256_AMENDMENT7 = "34a06373755c25167453da35225ab7b01dbc48af373344706e7bb000f736c623"
PLAN_SHA256_AMENDMENT8 = "2f56696f0398bd5bbd8f306bde536657bb380f4b886929e63d605e0cbcabf4c6"
PLAN_SHA256_AMENDMENT9 = "2ad3c7af660d836cb4d31238a6658b2dff9623d858ef415a9999e776422301f5"
PLAN_SHA256_AMENDMENT10 = "d350fe85b125c7a5d726c8456f89fed182532188e6a22ce59b44b935f5f159c6"
PLAN_SHA256 = "3ed57c6ea77f094e29a39d2e2bbd304cd5585eb5a2742983e99c22c47988514d"

PROVENANCE_VOCABULARY = (
    "measured",
    "published-experimental",
    "published-numerical-assumption",
    "derived",
    "representative-literature",
    "user-assumed",
    "fitted-training-only",
    "unknown",
)

# Owner-supplied checksums of the retrieved objects.
ZIP_SHA256 = "f35c083e75abc123a971f398ab50dd46b3a3d9df8763a1da9bda2d3914c02bc9"
ZIP_MD5 = "75df7a27e2125be5c5d852f03d36ff1a"
PDF_SHA256 = "b5296da062134da666da5cc105e9ede804d735f6c19f6d7e65d1f9b3435de3cf"
XLSX_SHA256 = "0753aeadd215e894e46de6cb7ac10df4c9edf32386ffdc37871381d80cc19cc0"
README_SHA256 = "a782d1877e268f3274fd835835428ee570c5caea5f5ea158201543aebce473f4"
# Content-based guard: no tracked file may be byte-identical to a third-party object, whatever its name.
THIRD_PARTY_SHA256 = frozenset({PDF_SHA256, ZIP_SHA256, XLSX_SHA256, README_SHA256})
MAX_GUARDED_BYTES = 5_000_000  # the four objects are all below 1 MB; larger files cannot match
TABLE_SUFFIXES = (".csv", ".tsv", ".xlsx", ".xls")
GUARDED_DIRS = ("docs", "data", "tests", "configs")
EXPECTED_FILES = {
    "FINAL_VERSION.pdf": ("sha256", PDF_SHA256),
    "dataset_JLT_NANF_vs_SMF.zip": ("sha256", ZIP_SHA256),
    "extracted/dataset_JLT_NANF_vs_SMF.xlsx": ("sha256", XLSX_SHA256),
    "extracted/readme_JLT_NANF_vs_SMF.txt": ("sha256", README_SHA256),
}
# Sizes recorded in the Sources document (zip members); the other two are checked by digest only.
EXPECTED_SIZES = {
    "extracted/dataset_JLT_NANF_vs_SMF.xlsx": 45_202,
    "extracted/readme_JLT_NANF_vs_SMF.txt": 2_407,
}
# SHA-256 of the first PREFIX_BYTES of each object: catches a copy with bytes appended.
PREFIX_BYTES = 2048
PREFIX_SHA256 = frozenset(
    {
        "994a9c79686a763a31ea5c3a25a184cc1a88e088be70bdcb41e3fb5e85cc8949",
        "1caac21bb1c826f5091af29db299e74a4ad939eea728307e18e5f52013f52e7d",
        "37a0d46d4308aed3728aebb34a530116224b271c77b779b57c8723fa0c3854ca",
        "64dedf11b36af5b1fc7ba784677a0bab1a47232678de1b59c3851dae701df235",
    }
)
LABEL = "LITERATURE BENCHMARK / CALIBRATION ONLY"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mismatched_present_files(directory: Path) -> list[str]:
    """Names of expected files that exist in `directory` with a wrong SHA-256 (missing is fine)."""
    bad = []
    for name, (_, digest) in EXPECTED_FILES.items():
        path = directory / name
        if path.is_file() and sha256_of(path) != digest:
            bad.append(name)
    return bad


def test_plan_hash_is_pinned() -> None:
    assert sha256_of(PLAN) == PLAN_SHA256


def test_original_plan_section_is_unchanged_by_amendments() -> None:
    # Append-only: the text before "## Amendment 1" (plus one trailing newline in place of the blank
    # separator line) is exactly the original file, so a later edit of sections 0 to 5 is caught even
    # if the current pin is moved with it.
    prefix = PLAN.read_bytes().split(b"## Amendment 1")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_ORIGINAL


def test_plan_text_before_amendment_2_is_unchanged_by_later_amendments() -> None:
    # Amendment 1 and everything before it: hashes to the Amendment 1 pin.
    prefix = PLAN.read_bytes().split(b"## Amendment 2")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT1


def test_plan_text_before_amendment_3_is_unchanged_and_amendment_3_records_the_previous_pin() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 3")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT2
    text = raw.decode()
    assert text.index("## Amendment 3") > text.index("## Amendment 2")
    amendment = text.split("## Amendment 3")[1]
    assert PLAN_SHA256_AMENDMENT2 in amendment and PLAN_SHA256 not in text
    assert "1e-2, 1e-3, 6e-3, 0" in amendment and "[r3, r4]" in amendment
    assert "2026-10-31" in text.split("## Amendment 3")[1].splitlines()[0]
    # B5.3 qualification only: no tolerance restated or moved
    assert "set knowing" in amendment and "23.33" in amendment and "0.67" in amendment
    assert "no criterion changes" in amendment


def test_plan_text_before_amendment_4_is_unchanged_and_amendment_4_records_the_previous_pin() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 4")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT3
    text = raw.decode()
    amendment = text.split("## Amendment 4")[1]
    assert PLAN_SHA256_AMENDMENT3 in amendment and PLAN_SHA256 not in text
    assert "2026-11-01" in amendment.splitlines()[0]
    for needle in (
        "per-series counts of censored BER points",  # the N2 print, in the what-was-seen record
        "no value was printed",
        "the -5 dBm cut of A3 applies to the ROP axis of Fig.4",
        "all 17",
        "`user-assumed`",
        "DAC resolution",
        "RIN",
        "Symbol sequence",
        "Capture length",
        "Responsivity",
        "must not be used silently",
        "B2B-copy comparator",
        "d is undefined",
        "no overlap",
        "multiple of 4",
        "and of 5",
        "8 x 1.4 = 11.2",
        "above_rop_cap",
        "proof of the freeze hash",
        "FrozenCriterion",
        "implemented in N3",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment.split("### D7")[1]


def test_plan_text_before_amendment_5_is_unchanged_and_amendment_5_records_the_previous_pin() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 5")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT4
    text = raw.decode()
    amendment = text.split("## Amendment 5")[1]
    assert PLAN_SHA256_AMENDMENT4 in amendment and PLAN_SHA256 not in text
    assert "2026-11-01" in amendment.splitlines()[0]
    for needle in (
        "lcm(4, 5, 7) = 140",  # the grid, with the arithmetic
        "655360 x 10/7 = 936228.57",
        "655200 symbols = 140 x 4680",
        "647008 symbols",
        "1 294 016",
        "129.4 bit errors",  # the corrected count
        "N is a number of PAM4 symbols",  # the unit of N
    ):
        assert needle in amendment, needle
    for needle in (
        "20261101",  # symbol seed and noise seed policy
        "SeedSequence",
        "280 GSa/s",  # oversampling rate
        "Timing phase: zero",
        "17 feed-forward taps at T/2 spacing and 7 feedback taps",
        "forgetting factor 0.998",
        "8192 symbols",
        "1e-2",  # delta
        "HOLDOUT_LOCKED",
        "A bare `include_holdout=True` is an error",
        "scatter of the published operating point",
        "does not absorb",
    ):
        assert needle in amendment, needle
    # nothing is relaxed
    assert "No tolerance or threshold of section 4, A3 or B1 to B3 is changed" in amendment
    assert LABEL in amendment.split("### F9")[1]


def test_plan_text_before_amendment_6_is_unchanged_and_amendment_6_records_the_previous_pin() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 6")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT5
    text = raw.decode()
    amendment = text.split("## Amendment 6")[1]
    assert PLAN_SHA256_AMENDMENT5 in amendment and PLAN_SHA256 not in text
    assert "2026-11-01" in amendment.splitlines()[0]
    assert text.count("## Amendment 6") == 1
    for needle in (
        "before any calibration and before any holdout scoring",  # when it was made
        "synthetic evidence for each change comes from the first review",
        "`PINNED_P_TRACE_CAP`",  # G1: 1e10, the equaliser is the plain RLS
        "`p_trace_cap` is fixed at 1e10",
        "cannot score",
        "favour of B1.3",  # G2: B1.3 against F7.2
        "published point at -12.4 dBm",
        "Only a finite BER below the\ndeclared floor 1e-5",  # G3
        "invalid data and the criterion FAILs",
        "`calibration_partition_sha256`",  # G4
        "Records inside the repository cannot prove that the\ncalibration was complete before the holdout was first read",
        "only an external timestamp can give a date proof",
        "found by parsing the imports",  # G5
        "`FrozenOverrideError`",
        "committed path",  # G6
        "Disclosed event",  # G7
        "`ba55025`",
        "`np.clip(., -1, 1)`",  # G9
    ):
        assert needle in amendment, needle
    assert LABEL in amendment.split("### G10")[1]
    assert "pre-registered" in amendment.split("### G10")[1] or "expected FAIL" in amendment
    # append-only: the previous plan is a byte-for-byte prefix of this one, so no line was removed
    assert raw.startswith(prefix) and len(raw) > len(prefix)


def test_plan_text_before_amendment_7_is_unchanged_and_amendment_7_records_the_previous_pin() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 7")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT6
    text = raw.decode()
    amendment = text.split("## Amendment 7")[1]
    assert PLAN_SHA256_AMENDMENT6 in amendment and PLAN_SHA256 not in text
    assert "2026-11-02" in amendment.splitlines()[0] and text.count("## Amendment 7") == 1
    for needle in (
        "made before any calibration and before any holdout scoring",
        "is not moved",  # the cap stays pinned at 1e10
        "never silently skipped",  # H1
        "highest contiguous run of locked",  # H2
        "Nothing is interpolated across a lost point",
        "no-crossing\nrule of G2",
        "FAILs if that point is lost",  # H3
        "worst-case objective",  # H4
        "`IdentifiabilityUndefinedError`",
        "no ROP axis of a holdout series\nwas read",  # H5
        "stays unknown until the scoring step",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment and "expected FAIL at 2.0 GHz" in amendment.split("### H6")[1]
    assert raw.startswith(prefix) and len(raw) > len(prefix)  # append-only


def test_plan_text_before_amendment_8_is_unchanged_and_amendment_8_corrects_the_holdout_record() -> (
    None
):
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 8")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT7
    text = raw.decode()
    amendment = text.split("## Amendment 8")[1]
    assert PLAN_SHA256_AMENDMENT7 in amendment and PLAN_SHA256 not in text
    assert "2026-11-02" in amendment.splitlines()[0] and text.count("## Amendment 8") == 1
    for needle in (
        "made before any calibration and before any holdout scoring",
        'H5 said "no ROP axis of a holdout series was read". That is false',
        "ONE y value",  # the Fig.11 cell, without its value
        "not\n  proof of absence",
        "also wrong",  # the earlier statement that no value reached an agent
        "`1541 passed`",  # the main-checkout run that confirms the old test ran
        "The holdout is not fully blind",
        "all Fig.11 series",
        "`EXCLUDED_FROM_SCORING`",
        "removes no criterion, changes no tolerance or threshold",
        "C7 is unchanged",
        "The count of holdout series a freeze unlocks is 46",
        "`DECLARED_LINKS`",
        "`DECLARED_POINT_INDICES`",
        "converged calibration",
        "`.git/info/grafts` is refused",
        "standing exception",
        "`__import__`",
        "`configs/fibers/*.yaml`",
        "`d4a50d6`, `869effc`, `dafa062`",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment and "expected FAIL at 2.0 GHz" in amendment.split("### G-F")[1]
    assert raw.startswith(prefix) and len(raw) > len(prefix)  # append-only
    # the three standing-exception tests exist under the names the plan gives
    for name in (
        "test_the_simulated_zero_chirp_nulls_meet_the_predeclared_tolerance_of_a1_3",
        "test_the_report_numbers_are_current_with_the_recomputation",
        "test_the_default_read_for_the_benchmarks_never_returns_a_holdout_series",
    ):
        assert name in amendment and f"def {name}" in Path(__file__).read_text()


def test_plan_text_before_amendment_9_is_unchanged_and_amendment_9_replaces_typed_flags() -> None:
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 9")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT8
    text = raw.decode()
    amendment = text.split("## Amendment 9")[1]
    assert PLAN_SHA256_AMENDMENT8 in amendment and PLAN_SHA256 not in text
    assert "2026-11-02" in amendment.splitlines()[0] and text.count("## Amendment 9") == 1
    for needle in (
        "made before any calibration and before any holdout scoring",
        "is checked, not trusted",
        "`DECLARED_CALIBRATION_POINTS`",
        "verified now, not at run time",
        "refused while any freeze record is present",
        "--git-common-dir",
        "`EIGENVALUE_ROUNDOFF_RELATIVE`",
        "eps / step = 2.2e-16 / 1e-3",
        "a more negative value cannot come from rounding",
        "`b2b_gate` takes `rop` as a required keyword",
        "refuses, before any run",
        "Sweep for typed arguments",
        "`published=True`",
        "ancestors of the branch tip",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment and "expected FAIL at 2.0 GHz" in amendment.split("### H-Z")[1]
    assert raw.startswith(prefix) and len(raw) > len(prefix)  # append-only


def test_plan_text_before_amendment_10_is_unchanged_and_amendment_10_states_residual_a() -> None:
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 10")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT9
    text = raw.decode()
    amendment = text.split("## Amendment 10")[1]
    assert PLAN_SHA256_AMENDMENT9 in amendment and PLAN_SHA256 not in text
    assert "2026-11-13" in amendment.splitlines()[0] and text.count("## Amendment 10") == 1
    for needle in (
        "`dataclasses.replace`",
        "stamped with the public freeze record hash",
        "relabelled as back-to-back",
        "is a limit, not a repair",
        "`require_freeze` at the read",
        "no source behaviour",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment and "expected FAIL at 2.0 GHz" in amendment.split("### H-Z")[1]
    assert raw.startswith(prefix) and len(raw) > len(prefix)  # append-only


def test_plan_text_before_amendment_11_is_unchanged_and_amendment_11_fixes_the_fit() -> None:
    raw = PLAN.read_bytes()
    prefix = raw.split(b"## Amendment 11")[0]
    assert hashlib.sha256(prefix.rstrip(b"\n") + b"\n").hexdigest() == PLAN_SHA256_AMENDMENT10
    text = raw.decode()
    amendment = text.split("## Amendment 11")[1]
    assert PLAN_SHA256_AMENDMENT10 in amendment and PLAN_SHA256 not in text
    assert "2026-11-13" in amendment.splitlines()[0] and text.count("## Amendment 11") == 1
    for needle in (
        "before any calibration fit and before any holdout scoring",
        "the sum of the squares of that vector, unweighted",
        "costs +infinity",
        "SeedSequence([20261101, 4101])",
        "at most 70 cost evaluations",
        "1 + 24 + at most 45",
        "`converged` means that the stop tolerances were met before the budget ended",
        "`CALIBRATION NOT CONVERGED`",
        "no extra budget without a new amendment",
        "lowest finite cost in the whole log",
        "refuses to start if a log exists",
        "never restarts",
        "`DECLARED_CALIBRATION_POINTS`",
        "`DECLARED_POINT_INDICES`: 0 to 18",
        "`DECLARED_LINKS`",
        "`NOT RUN (links not declared)`",
        "`NOT BUILT`",
        "The holdout is not fully blind",
        "is added to the entry modules of the code identity",
        "Amendments 7 and 8 except as corrected by Amendment 9",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment and "expected FAIL at 2.0 GHz" in amendment.split("### H-Z")[1]
    assert raw.startswith(prefix) and len(raw) > len(prefix)  # append-only


def test_plan_amendment_2_records_previous_pin_and_closes_review_items() -> None:
    text = PLAN.read_text()
    assert "## Amendment 2" in text and PLAN_SHA256_AMENDMENT1 in text
    assert PLAN_SHA256 not in text and len({PLAN_SHA256, PLAN_SHA256_AMENDMENT1}) == 2
    amendment = text.split("## Amendment 2")[1]
    assert text.index("## Amendment 2") > text.index("## Amendment 1")
    for needle in (
        "number of sessions is not stated",
        "last one (highest ROP)",
        "BER 1e-2, 5e-3, 0, 0",
        "x <= r0 + 1.0",
        "excluded",
        "1630 and 1640 nm",
        "no-fibre output",
        "B2B CALIBRATION POOR",
        "every one of the three rates",
        "tx_bandwidth_ghz",
        "No refit after a flag",
        "POSSIBLE CLOCK-SPIKE COINCIDENCE",
        "max(1, i-2)",
        "mean |s|^2",
        "22.15 to 25.43 GHz",
        "blind for the simulator only",
        "is not to be used as an input",
    ):
        assert needle in amendment, needle
    assert LABEL in amendment.split("### B7")[1]


def test_plan_amendment_records_previous_pin_and_key_rules() -> None:
    text = PLAN.read_text()
    assert "## Amendment 1" in text
    assert PLAN_SHA256_ORIGINAL in text  # previous SHA recorded
    assert PLAN_SHA256_ORIGINAL != PLAN_SHA256
    for needle in (
        "UNIDENTIFIABLE_PARAMETER",
        "B2B-copy",
        "NOT DISCRIMINATING",
        "29.39 GHz",
        "left-censored",
        "240sub-SMF-OFDM",
    ):
        assert needle in text, needle
    assert LABEL in text.split("## Amendment 1")[1]


def test_plan_declares_label_and_no_per_fibre_retuning() -> None:
    text = PLAN.read_text()
    assert LABEL in text
    assert "No per-fibre retuning" in text
    assert "B2B" in text and "Locked holdout" in text


def test_provenance_vocabulary_is_closed_and_complete() -> None:
    text = SOURCES.read_text()
    tags = re.findall(r"\[prov: ([^\]]+)\]", text)
    assert tags, "no provenance tags found"
    assert set(tags) <= set(PROVENANCE_VOCABULARY)
    # every label is named in the vocabulary line even when no row uses it
    for label in PROVENANCE_VOCABULARY:
        assert f"`{label}`" in text


def test_all_digests_pinned_and_cross_checked_against_the_sources_table() -> None:
    # Every object has a pinned digest and the digest set equals the 64-hex tokens of the Sources
    # section 1 table, so dropping one from either side, or corrupting one in the test only, fails.
    text = SOURCES.read_text()
    section = text.split("## 1. Objects")[1].split("### 1.1")[0]
    assert set(re.findall(r"\b[0-9a-f]{64}\b", section)) == set(THIRD_PARTY_SHA256)
    assert len(THIRD_PARTY_SHA256) == 4 == len(EXPECTED_FILES)
    assert {d for _, d in EXPECTED_FILES.values()} == set(THIRD_PARTY_SHA256)
    for name, (_, digest) in EXPECTED_FILES.items():
        row = [ln for ln in section.splitlines() if Path(name).name in ln]
        assert row and digest in row[0], name
    assert len(PREFIX_SHA256) == 4
    # With the objects present, the pins are checked against the bytes themselves.
    for name, (_, digest) in EXPECTED_FILES.items():
        path = DATA_DIR / name
        if path.is_file():
            assert sha256_of(path) == digest, name
            assert hashlib.sha256(path.read_bytes()[:PREFIX_BYTES]).hexdigest() in PREFIX_SHA256
    for name, size in EXPECTED_SIZES.items():
        path = DATA_DIR / name
        if path.is_file():
            assert path.stat().st_size == size, name
    flat_sizes = SOURCES.read_text().replace(",", "")
    assert all(str(size) in flat_sizes for size in EXPECTED_SIZES.values())


def test_size_cap_covers_every_known_object() -> None:
    # A cap below an object's size would silently exempt it from the content guard.
    assert MAX_GUARDED_BYTES >= 2 * max(EXPECTED_SIZES.values())
    assert MAX_GUARDED_BYTES >= 1_000_000  # the PDF is 841,267 bytes and the zip 43,135


def test_sources_record_owner_checksums_and_label() -> None:
    text = SOURCES.read_text()
    for digest in (ZIP_SHA256, ZIP_MD5, PDF_SHA256, XLSX_SHA256, README_SHA256):
        assert digest in text
    assert LABEL in text
    assert "10.5258/SOTON/D1889" in text
    assert "10.1109/JLT.2021.3097278" in text


def test_secondary_sources_are_metadata_only_and_never_pooled() -> None:
    text = SOURCES.read_text()
    for doi in (
        "10.1002/lpor.202400157",
        "10.3788/COL202523.020604",
        "10.1364/CLEO_SI.2025.SS135_4",
    ):
        assert doi in text
    flat = " ".join(text.split())
    assert 'does not assert "no shared spool"' in flat


def test_present_files_match_pins_and_absence_is_not_an_error(tmp_path: Path) -> None:
    assert mismatched_present_files(tmp_path) == []
    (tmp_path / "FINAL_VERSION.pdf").write_bytes(b"not the paper")
    assert mismatched_present_files(tmp_path) == ["FINAL_VERSION.pdf"]
    assert mismatched_present_files(DATA_DIR) == []


def tracked_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()


def third_party_by_content(
    root: Path,
    paths: list[str],
    digests: frozenset[str] = THIRD_PARTY_SHA256,
    prefixes: frozenset[str] = PREFIX_SHA256,
) -> list[str]:
    """Paths whose bytes equal a known third-party object, or begin with its first bytes."""
    hits = []
    for rel in paths:
        path = root / rel
        if path.is_file() and path.stat().st_size <= MAX_GUARDED_BYTES:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() in digests:
                hits.append(rel)
            elif len(data) >= PREFIX_BYTES and (
                hashlib.sha256(data[:PREFIX_BYTES]).hexdigest() in prefixes
            ):
                hits.append(rel)
    return hits


def tables_under_guarded_dirs(paths: list[str]) -> list[str]:
    """Tracked CSV/XLSX/XLS files under docs/ or a data path (generated output/ is not guarded)."""
    return [
        p
        for p in paths
        if p.lower().endswith(TABLE_SUFFIXES) and set(Path(p).parts[:-1]) & set(GUARDED_DIRS)
    ]


def test_no_tracked_file_has_third_party_content() -> None:
    tracked = tracked_files()
    assert third_party_by_content(Path("."), tracked) == []
    assert not [p for p in tracked if p.startswith("data/external/")]
    assert tables_under_guarded_dirs(tracked) == []


def test_content_guard_catches_renamed_copies_and_tables(tmp_path: Path) -> None:
    # Negative tests: the guard fires on a byte-identical copy under an innocent name. A stand-in
    # object and its digest are used, so this runs without data/external.
    stand_in = b"stand-in third-party object"
    digests = frozenset({hashlib.sha256(stand_in).hexdigest()})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "benchmark_table.xlsx").write_bytes(stand_in)
    (tmp_path / "hong2021.pdf").write_bytes(stand_in)
    hits = third_party_by_content(tmp_path, ["docs/benchmark_table.xlsx", "hong2021.pdf"], digests)
    assert hits == ["docs/benchmark_table.xlsx", "hong2021.pdf"]
    # the real digests are the ones used by default, and a real present copy is caught too
    for name, source in ((n, DATA_DIR / n) for n in EXPECTED_FILES):
        if source.is_file():
            copy = tmp_path / ("innocent_" + Path(name).name.replace(".", "_") + ".dat")
            copy.write_bytes(source.read_bytes())
            assert third_party_by_content(tmp_path, [copy.name]) == [copy.name]
    # an object with a byte appended (or a different tail) is caught by its prefix
    big = bytes(range(256)) * 16
    prefix_digest = frozenset({hashlib.sha256(big[:PREFIX_BYTES]).hexdigest()})
    (tmp_path / "plus1.xlsx.txt").write_bytes(big + b"\x00")
    (tmp_path / "short.bin").write_bytes(big[:100])
    assert third_party_by_content(
        tmp_path, ["plus1.xlsx.txt", "short.bin"], frozenset(), prefix_digest
    ) == ["plus1.xlsx.txt"]
    # an unrelated small file is not flagged
    (tmp_path / "ok.txt").write_text("hello")
    assert third_party_by_content(tmp_path, ["ok.txt"]) == []
    # tables under docs/ or data paths are rejected; generated output/ tables are not
    assert tables_under_guarded_dirs(
        [
            "docs/nanf_fig4.csv",
            "data/x/y.XLSX",
            "output/run/a.csv",
            "tests/golden/fig4.csv",
            "configs/fibers/curve.tsv",
            "docs/notes/t.TSV",
        ]
    ) == [
        "docs/nanf_fig4.csv",
        "data/x/y.XLSX",
        "tests/golden/fig4.csv",
        "configs/fibers/curve.tsv",
        "docs/notes/t.TSV",
    ]


def test_sources_fix_round_facts_are_recorded() -> None:
    flat = " ".join(SOURCES.read_text().split())
    assert "https://eprints.soton.ac.uk/450180/" in flat
    assert "=-Inf" in flat and "unloaded subcarriers" in flat
    quote = " ".join(
        ln.lstrip("> ") for ln in SOURCES.read_text().splitlines() if ln.startswith(">")
    )
    assert "Hollow-core NANF for High-speed Short-reach Transmission in the S+C+L-bands" in quote
    assert "Dataset for" not in quote
    assert "Facts versus expression" in flat
    assert "latency = n L / c" in flat
    assert "29.39 GHz" in flat and "28 GHz" in flat and "~25 GHz" in flat and "24 GHz" in flat
    assert "Fig.1 panel labels disagree" in flat
    assert "rows 4 to 14" in flat
    assert "May 2020" in flat and "single session" not in flat.lower()
    assert "separate record" in flat


# --- Gate N2: Benchmark A (Fig. 1 recomputed) and Benchmark C (Fig. 5 read) ----------------------
# Fig. 1 is the plan's cross-check class (section 2: "Not a measurement. Used only to check that
# our dispersion and latency arithmetic reproduces the paper's stated assumptions"); Fig. 5 is a
# calibration input. The tests below use closed forms written here and a synthetic workbook; the
# real workbook is opened only for Fig. 1 and Fig. 5 and only by the cross-check tests at the end.

REAL_XLSX = DATA_DIR / "extracted/dataset_JLT_NANF_vs_SMF.xlsx"
REPORT = Path("reports/NANF_Benchmark_Report.md")
C = 299_792_458.0
SLOPES = {"SSMF": 0.060, "NZ-DSF": 0.054, "NANF": 0.004}  # own numbers for the synthetic curves


def build_fig1_cells():
    """A synthetic workbook whose Fig. 1 columns follow the closed forms of the paper's model."""
    cells = build_cells(axis_fn=_axis)
    from opticps.measurement.nanf_import import SHEET_LAYOUTS

    layout = next(layout for layout in SHEET_LAYOUTS if layout.name == "Fig.1")
    for block in layout.blocks:
        for s in block.series:
            fibre = {"SSMF": "SSMF", "SMF": "SSMF", "SMF@5km": "SSMF", "NZ-DSF": "NZ-DSF",
                     "NZ-DSF@5km": "NZ-DSF", "NANF": "NANF", "NANF@5km": "NANF"}[s.header]  # fmt: skip
            d1550, n = nb.PAPER_ASSUMPTIONS[fibre]
            for i in range(s.count):
                x = _axis("Fig.1", block.label, i)
                d_here = d1550 + SLOPES[fibre] * (x * 1000.0 - 1550.0)
                if block.label == "a-CD":
                    y = d_here
                elif block.label == "b-bandwidth":
                    lam = x * 1e-9 * 1000.0
                    x3 = math.acos(10 ** (-3 / 20))
                    y = math.sqrt(x3 * C / (math.pi * lam**2 * abs(d_here * 1e-6) * 5e3)) / 1e9
                elif block.label == "c-fading":
                    lam = 1550e-9
                    arg = math.pi * lam**2 * d1550 * 1e-6 * 5e3 * (x * 1e9) ** 2 / C
                    y = 20 * math.log10(max(abs(math.cos(arg)), 1e-300))
                else:
                    y = n * x * 1e3 / C * 1e6
                cells["Fig.1"][f"{s.letter}{block.first_row + i}"] = ("n", repr(y), None)
    return cells


def _axis(sheet: str, block: str, i: int) -> float:
    if sheet == "Fig.1":
        return {"a-CD": 1.4 + 0.005 * i, "b-bandwidth": 1.4 + 0.005 * i, "c-fading": float(i),
                "d-latency": 1.0 + 0.2 * i}[block]  # fmt: skip
    if sheet == "Fig.5":
        return 1460.0 + 10.0 * i
    return -12.0 + 0.5 * i


@pytest.fixture(scope="module")
def synthetic_workbook(tmp_path_factory):
    path = tmp_path_factory.mktemp("nanf") / "synthetic.xlsx"
    digest = make_workbook(path, build_fig1_cells())
    return read_nanf_workbook(path, expected_sha256=digest)


def test_the_plan_allows_fig1_and_fig5_and_names_what_it_forbids() -> None:
    text = PLAN.read_text()
    assert "Cross-check only, no fit | Fig. 1" in text and "Not a measurement" in text
    assert "Fig. 5 ROP columns and NANF loss column" in text
    assert "Locked holdout | Fig. 4 NANF and SSMF series" in text
    # the benchmark module reads Fig. 1 and Fig. 5 only (no holdout key, no other sheet)
    source = Path(nb.__file__).read_text()
    assert set(re.findall(r'series_key\(\s*"(Fig\.\d+)"', source)) == {"Fig.1", "Fig.5"}
    assert "FIG1_BLOCKS" in source and not re.search(r"Fig\.(4|6|7|8|9|10|11|12)\b", source)


def test_the_tone_response_follows_the_cosine_law_and_ignores_loss() -> None:
    for d, length, f_ghz in (
        (15.95, 5.0, 14.0),
        (15.95, 5.0, 25.0),
        (2.04, 4.76, 60.0),
        (-8.0, 3.0, 30.0),
    ):
        resolved = resolve_profile(
            nb.numerical_profile("SSMF", length_km=length, d_ps_per_nm_km=d), 1550.0
        )
        lam = 1550e-9
        expected = abs(
            math.cos(math.pi * lam**2 * abs(d) * 1e-6 * length * 1e3 * (f_ghz * 1e9) ** 2 / C)
        )
        assert nb.tone_response(resolved, f_ghz * 1e9) == pytest.approx(expected, abs=2e-6)
    # a lossy fibre gives the same normalised response
    lossy = nb.numerical_profile("SSMF", d_ps_per_nm_km=15.95)
    scen = resolve_profile(lossy, 1550.0)
    assert scen.total_loss_db == 0.0  # the paper's simulation excludes fibre loss
    with pytest.raises(ValueError):
        nb.tone_response(scen, 0.0)
    with pytest.raises(ValueError):
        nb.tone_response(scen, float("nan"))


def test_numerical_profile_is_a_loss_free_published_numerical_assumption() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        nb.numerical_profile("SSMF")
    with pytest.raises(ValueError, match="exactly one"):
        nb.numerical_profile("SSMF", d_ps_per_nm_km=1.0, d_table=object())  # type: ignore[arg-type]
    p = nb.numerical_profile("NANF", d_ps_per_nm_km=2.04)
    r = resolve_profile(p, 1550.0)
    assert (r.total_loss_db, r.length_km, r.group_index) == (0.0, 5.0, 1.003)
    assert r.dispersion_ps_per_nm_km == 2.04 and not r.not_a_benchmark_result
    with pytest.raises(OutOfValidityRangeError):
        resolve_profile(p, 1630.0)  # beyond the paper's curves (1.4 to 1.625 um): no extrapolation


def test_first_null_and_bandwidth_match_the_closed_forms() -> None:
    resolved = resolve_profile(nb.numerical_profile("SSMF", d_ps_per_nm_km=15.95), 1550.0)
    f1 = math.sqrt(C / (2 * (1550e-9) ** 2 * 15.95e-6 * 5e3)) / 1e9
    assert nb.first_null_ghz(resolved) == pytest.approx(f1, abs=0.01)
    x3 = math.acos(10 ** (-3 / 20))
    f3 = math.sqrt(x3 * C / (math.pi * (1550e-9) ** 2 * 15.95e-6 * 5e3)) / 1e9
    assert nb.bandwidth_3db_ghz(resolved) == pytest.approx(f3, rel=1e-6)
    zero = resolve_profile(nb.numerical_profile("SSMF", d_ps_per_nm_km=0.0), 1550.0)
    assert math.isinf(nb.bandwidth_3db_ghz(zero)) and math.isinf(nb.first_null_bracket_ghz(zero))
    with pytest.raises(ValueError, match="no interior null"):
        nb.first_null_ghz(resolved, half_window_ghz=0.005, step_ghz=0.01)


def test_the_fig1_report_reproduces_a_synthetic_workbook_built_from_the_closed_forms(
    synthetic_workbook,
) -> None:
    report = nb.fig1_report(synthetic_workbook)
    for fibre, result in report.fading.items():
        assert result.max_abs_diff_db < 1e-3, fibre
        assert result.max_abs_diff_with_workbook_d_db < 1e-3
    assert report.fading["SSMF"].n_excluded_deep == 1  # the 28 GHz bin sits in the null
    for fibre, (_, reld, n) in report.bandwidth.items():
        assert n == 46 and reld < 1e-4, fibre
    for fibre, (absd, _) in report.latency.items():
        assert absd < 1e-9, fibre
    assert all(ok for _, _, ok in report.preregistered_null_check.values())
    assert report.first_null_ghz["SSMF"] == pytest.approx(27.97, abs=0.3)
    assert report.published_null_ghz_grid["NANF"] is None  # no interior minimum inside 35 GHz
    assert report.latency_saving_5km_us[0] == pytest.approx(7.7587, abs=1e-3)
    assert report.latency_saving_5km_fraction == pytest.approx(1 - 1.003 / 1.4682, abs=1e-9)
    assert "20 log10" in report.conventions


def test_the_fig1_report_cannot_run_on_holdout_or_wrong_roles(synthetic_workbook) -> None:
    for key in synthetic_workbook.series:
        assert synthetic_workbook[key].role is not DataRole.HOLDOUT  # default read withholds them
    assert not any("Fig.4" in k or "Fig.6" in k for k in nb.FIG1_BLOCKS)


def fig5_cells(loss=None, rop_nanf=None, rop_ssmf=None):
    cells = build_cells(axis_fn=_axis)
    for i in range(19):
        values = {
            "B": -9.0 + 0.1 * i if rop_nanf is None else rop_nanf[i],
            "C": -7.0 - 0.1 * i if rop_ssmf is None else rop_ssmf[i],
            "D": 8.3 - 0.123 * i if loss is None else loss[i],
        }
        for col, v in values.items():
            cells["Fig.5"][f"{col}{2 + i}"] = ("n", repr(v), None)
    return cells


@pytest.fixture
def fig5_workbook(tmp_path):
    loss = [8.33 if i == 0 else 6.45 + 0.1 * abs(i - 15) for i in range(19)]
    path = tmp_path / "f5.xlsx"
    digest = make_workbook(path, fig5_cells(loss=loss))
    return read_nanf_workbook(path, expected_sha256=digest)


def test_fig5_summary_leaves_the_distributed_loss_unknown(fig5_workbook) -> None:
    s = nb.link_loss_summary(fig5_workbook)
    assert s.n_points == 19 and s.wavelength_range_nm == (1460.0, 1640.0)
    assert (s.loss_min_db, s.loss_min_wavelength_nm) == (6.45, 1610.0)
    assert (s.loss_max_db, s.loss_max_wavelength_nm) == (8.33, 1460.0)
    assert s.distributed_upper_bound_db_per_km == pytest.approx(6.45 / 4.76)  # at 1610 nm only
    assert s.distributed_upper_bound_wavelength_nm == 1610.0
    assert nb.distributed_loss_bound_db_per_km(fig5_workbook, 1610.0) == pytest.approx(
        1.355, abs=1e-3
    )
    assert nb.distributed_loss_bound_db_per_km(fig5_workbook, 1460.0) == pytest.approx(
        1.75, abs=1e-3
    )
    text = nb.DISTRIBUTED_LOSS_NOT_SEPARABLE
    assert "1.355 dB/km" in text and "1610 nm" in text and "1.75 dB/km" in text
    assert "1460 nm" in text and "about 4.76 km" in text
    assert s.distributed_loss == "unknown"
    assert "stays unknown" in nb.DISTRIBUTED_LOSS_NOT_SEPARABLE
    assert (
        "2 dB" in nb.DISTRIBUTED_LOSS_NOT_SEPARABLE
        and "0.1 dB" in nb.DISTRIBUTED_LOSS_NOT_SEPARABLE
    )
    # the Hong profile keeps its attenuation unknown, so no run takes a distributed loss from Fig. 5
    hong = load_fiber_config("configs/fibers/NANF-HONG-2021-4P76KM.yaml")
    assert not hong.attenuation_db_per_km.known and hong.attenuation_db_per_km.value is None
    with pytest.raises(FiberProfileError):
        resolve_profile(hong, 1550.0)


def test_total_link_loss_is_interpolated_inside_the_measured_span_only(fig5_workbook) -> None:
    assert nb.link_loss_at(fig5_workbook, 1460.0) == 8.33
    assert nb.link_loss_at(fig5_workbook, 1610.0) == pytest.approx(6.45)
    assert nb.link_loss_at(fig5_workbook, 1640.0) == pytest.approx(6.45 + 0.1 * 3)
    mid = nb.link_loss_at(fig5_workbook, 1605.0)
    assert mid == pytest.approx(0.5 * (6.45 + 6.55))  # linear between 1600 (6.55) and 1610 (6.45)
    for outside in (1459.9, 1640.1, 1550.0 - 1e3, float("nan"), float("inf")):
        with pytest.raises(OutOfValidityRangeError):
            nb.link_loss_at(fig5_workbook, outside)


def test_the_link_loss_is_one_number_and_never_added_to_the_pigtail(fig5_workbook) -> None:
    hong = load_fiber_config("configs/fibers/NANF-HONG-2021-4P76KM.yaml")
    assert hong.pigtail_loss_db.value == 2.0 and hong.splice_loss_db.value == 0.1
    # the helper returns the total of the whole link; a caller that adds pigtail + loss would count
    # the ~2 dB twice, so the docstring says so and no function here returns a pigtail-adjusted loss
    doc = nb.link_loss_at.__doc__ or ""
    assert "must not be added to the pigtail" in doc and "twice" in doc
    assert not [n for n in dir(nb) if "distributed_from" in n or "net_of_pigtail" in n]


def _with_role(wb, keys, role):
    series = dict(wb.series)
    for key in keys:
        series[key] = dataclasses.replace(wb[key], role=role)
    return NanfWorkbook(wb.sha256, series)


def test_the_fig5_summary_refuses_a_series_that_is_not_a_calibration_input(fig5_workbook) -> None:
    for header in ("ROP@NANF", "ROP@SSMF", "NANF loss"):
        key = series_key("Fig.5", "link", header)
        for role in (DataRole.HOLDOUT, DataRole.CALIBRATION, DataRole.CROSS_CHECK):
            wrong = _with_role(fig5_workbook, [key], role)
            with pytest.raises(ValueError, match="calibration inputs"):
                nb.link_loss_summary(wrong)
    assert nb.link_loss_summary(fig5_workbook).n_points == 19


def test_the_fig1_report_refuses_a_series_that_is_not_the_cross_check_class(
    synthetic_workbook,
) -> None:
    keys = [k for k, v in synthetic_workbook.series.items() if v.sheet == "Fig.1"]
    assert len(keys) == 12
    for role in (DataRole.HOLDOUT, DataRole.CALIBRATION, DataRole.CALIBRATION_INPUT):
        wrong = _with_role(synthetic_workbook, keys, role)
        with pytest.raises(ValueError, match="cross-check class"):
            nb.fig1_report(wrong)
    assert nb.fig1_report(synthetic_workbook)


def test_the_null_tolerance_of_a1_3_is_declared_and_met_without_the_workbook(
    synthetic_workbook,
) -> None:
    # Plan A1.3: 0.3 GHz. The synthetic route needs no data/external, so a loosened constant
    # cannot hide behind a skipped real-workbook test.
    assert nb.NULL_TOLERANCE_GHZ == 0.3
    report = nb.fig1_report(synthetic_workbook)
    assert set(report.preregistered_null_check) == {"SSMF 4.53 km", "SSMF 5 km", "NANF 4.76 km"}
    for label, (sim, expected, ok) in report.preregistered_null_check.items():
        assert ok and abs(sim - expected) <= 0.3, label
        assert expected == nb.PREREGISTERED_NULLS_GHZ[label]


def test_fig5_columns_are_calibration_inputs(fig5_workbook) -> None:
    for header in ("ROP@NANF", "ROP@SSMF", "NANF loss"):
        assert fig5_workbook[series_key("Fig.5", "link", header)].role is DataRole.CALIBRATION_INPUT


# Real workbook: Fig. 1 and Fig. 5 only; skipped when data/external is absent.

REAL = pytest.mark.skipif(not REAL_XLSX.is_file(), reason="data/external/nanf_hong2021 is absent")


@REAL
def test_the_simulated_zero_chirp_nulls_meet_the_predeclared_tolerance_of_a1_3() -> None:
    # Plan A1.3: a disagreement above 0.3 GHz with the pre-registered arithmetic is a simulator
    # defect. This is the only tolerance predeclared for Fig. 1; everything else is reported only.
    report = nb.fig1_report(read_nanf_workbook(REAL_XLSX))
    assert nb.NULL_TOLERANCE_GHZ == 0.3
    for label, (sim, expected, ok) in report.preregistered_null_check.items():
        assert ok and abs(sim - expected) <= 0.3, label


@REAL
def test_the_report_numbers_are_current_with_the_recomputation() -> None:
    text = REPORT.read_text()
    block = re.search(r"```json\n(\{.*?\})\n```", text, re.S)
    assert block, "the report carries a machine-readable block of its computed values"
    recorded = json.loads(block.group(1))
    wb = read_nanf_workbook(REAL_XLSX)
    report = nb.fig1_report(wb)
    assert recorded["first_null_ghz_5km"] == pytest.approx(report.first_null_ghz, rel=1e-3)
    assert recorded["bandwidth_3db_at_1550_ghz"] == pytest.approx(
        {k: v[0] for k, v in report.bandwidth_at_1550_ghz.items()}, rel=1e-3
    )
    assert recorded["latency_saving_5km_us"] == pytest.approx(
        report.latency_saving_5km_us[0], rel=1e-3
    )
    assert recorded["fading_max_abs_diff_db_stated_d"] == pytest.approx(
        {k: v.max_abs_diff_db for k, v in report.fading.items()}, rel=1e-2, abs=1e-6
    )
    summary = nb.link_loss_summary(wb)
    assert recorded["link_loss_db"] == pytest.approx([summary.loss_min_db, summary.loss_max_db])
    assert recorded["link_loss_min_wavelength_nm"] == summary.loss_min_wavelength_nm


@REAL
def test_the_default_read_for_the_benchmarks_never_returns_a_holdout_series() -> None:
    wb = read_nanf_workbook(REAL_XLSX)
    assert {s.role for s in wb.series.values()} <= {
        DataRole.CROSS_CHECK,
        DataRole.CALIBRATION,
        DataRole.CALIBRATION_INPUT,
    }
    assert np.isfinite(nb.link_loss_summary(wb).loss_min_db)


def test_the_report_is_labelled_attributed_and_makes_no_validation_claim() -> None:
    text = REPORT.read_text()
    assert LABEL in text.splitlines()[0] or LABEL in text[:300]
    assert "10.5258/SOTON/D1889" in text and "CC BY 4.0" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text
    assert (
        "not experimental validation" in text.lower()
        or "no claim of experimental validation" in text.lower()
    )
    for evidence in ("published-numerical-assumption", "published-experimental", "derived"):
        assert evidence in text
    assert "Changes:" in text  # CC BY: an indication of changes
    # plan Amendment 8: every N3 report states that the holdout is not fully blind
    assert "The holdout is not fully blind" in text
    # no image, no table copied from a third party: the only data in the report are our computed values
    assert "![" not in text
