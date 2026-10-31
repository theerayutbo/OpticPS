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
XLSX_SHA256 = "0753aeadd215e894e46de6cb7ac10df4c9edf32386ffdc37871381d80cc19cc0"
README_SHA256 = "a782d1877e268f3274fd835835428ee570c5caea5f5ea158201543aebce473f4"
# Content-based guard: no tracked file may be byte-identical to a third-party object, whatever its name.
THIRD_PARTY_SHA256 = frozenset({PDF_SHA256, ZIP_SHA256, XLSX_SHA256, README_SHA256})
MAX_GUARDED_BYTES = 5_000_000  # the four objects are all below 1 MB; larger files cannot match
TABLE_SUFFIXES = (".csv", ".xlsx", ".xls")
GUARDED_DIRS = ("docs", "data")
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
    root: Path, paths: list[str], digests: frozenset[str] = THIRD_PARTY_SHA256
) -> list[str]:
    """Paths whose bytes equal a known third-party object, whatever the file is called."""
    hits = []
    for rel in paths:
        path = root / rel
        if path.is_file() and path.stat().st_size <= MAX_GUARDED_BYTES:
            if sha256_of(path) in digests:
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
            copy = tmp_path / ("innocent_" + name.replace(".", "_") + ".dat")
            copy.write_bytes(source.read_bytes())
            assert third_party_by_content(tmp_path, [copy.name]) == [copy.name]
    # an unrelated small file is not flagged
    (tmp_path / "ok.txt").write_text("hello")
    assert third_party_by_content(tmp_path, ["ok.txt"]) == []
    # tables under docs/ or data paths are rejected; generated output/ tables are not
    assert tables_under_guarded_dirs(
        ["docs/nanf_fig4.csv", "data/x/y.XLSX", "output/run/a.csv"]
    ) == [
        "docs/nanf_fig4.csv",
        "data/x/y.XLSX",
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
