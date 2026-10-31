"""Gate N0 (NANF workstream): plan pin, provenance vocabulary, checksum record, no third-party data.

Offline. These tests need no external data; when `data/external/nanf_hong2021/` is present they also
check the file hashes, and they pass without it.
"""

import hashlib
import re
import subprocess
from pathlib import Path

PLAN = Path("docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md")
SOURCES = Path("docs/NANF_SOURCES_AND_PROVENANCE.md")
DATA_DIR = Path("data/external/nanf_hong2021")

# Original pin (2026-10-31, commit 9a891c9), set before any workbook value was read. Amendment 1
# (N0 fix round) is recorded in the plan; it supersedes this pin with the one below. A deliberate
# amendment must change the current pin and add a dated section to the plan.
PLAN_SHA256_ORIGINAL = "c4771dc125c3daeaf28b429de2f31f3ca25a5d3645a6f59e1d8dd9b9bf0bef22"
PLAN_SHA256 = "92b20966c409958729946f31243216b49fe796d7b9f4ac22f33f30c854dce5c0"

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
EXPECTED_FILES = {
    "FINAL_VERSION.pdf": ("sha256", PDF_SHA256),
    "dataset_JLT_NANF_vs_SMF.zip": ("sha256", ZIP_SHA256),
}
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


def test_sources_record_owner_checksums_and_label() -> None:
    text = SOURCES.read_text()
    for digest in (ZIP_SHA256, ZIP_MD5, PDF_SHA256):
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


def test_no_third_party_nanf_files_are_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert not [p for p in tracked if p.startswith("data/external/")]
    assert not [p for p in tracked if p.endswith((".xlsx", ".zip")) and "nanf" in p.lower()]
    assert not [p for p in tracked if p.endswith("FINAL_VERSION.pdf")]
