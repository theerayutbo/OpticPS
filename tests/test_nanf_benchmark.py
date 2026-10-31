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
# Pin after Amendment 1 (commit 843d223); replaced at Amendment 2 (Gate N1), then at Amendment 3
# (N1 fix round).
PLAN_SHA256_AMENDMENT1 = "92b20966c409958729946f31243216b49fe796d7b9f4ac22f33f30c854dce5c0"
PLAN_SHA256_AMENDMENT2 = "ec0f325a118fcc8162e21de2b6acf1662b6d3ea6db14bfed0c3a507ff2827aa5"
PLAN_SHA256 = "0a3897ad0b22acca7710faf61acc40d97f846c6829eb6fc26e1ece3f7ff4f2c4"

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
