"""Byte anchor: regenerating the committed M8199B packages must reproduce them.

This pins the v1.2 PAM4 behaviour before any M-PAM generalisation. It uses the
untouched configs/m8199b_profiles.yaml at full training size, because the
adaptive PMF depends on the training size and grid step. Output goes to a
temporary directory, never into the repository.
"""

import json
import math
from pathlib import Path

import pytest

from opticps.transmitter.export import generate_all, sha256_file

CONFIG = Path("configs/m8199b_profiles.yaml")
COMMITTED = Path("output/keysight_m8199b")
PROFILES = ("A_initial_8GBd", "B_highspeed_56GBd")

# Files hashed against checksums.sha256. Metadata JSON is compared separately
# (generator key removed), so it is excluded from the hash comparison.
HASHED_SUFFIXES = ("_symbols.csv", "_info_bits.txt")

# Explicit exclusions: relative path -> reason. Empty means every file matches.
EXCLUDED: dict[str, str] = {}

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("anchor") / "keysight_m8199b"
    generate_all(CONFIG, root)
    return root


def _committed_checksums(profile: str) -> dict[str, str]:
    entries = {}
    for line in (COMMITTED / profile / "checksums.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        entries[name] = digest
    return entries


def _hashed(name: str) -> bool:
    return name.startswith("waveforms/") or name.endswith(HASHED_SUFFIXES)


def _strip_generator(path: Path) -> dict:
    data = json.loads(path.read_text())
    del data["generator"]
    return data


def _assert_close(actual, expected, path="") -> None:
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in expected:
            _assert_close(actual[key], expected[key], f"{path}/{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _assert_close(a, e, f"{path}[{index}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=0.0), path
    else:
        assert type(actual) is type(expected), path
        assert actual == expected, path


@pytest.mark.parametrize("profile", PROFILES)
def test_hashed_files_match_committed_checksums(regenerated, profile):
    committed = _committed_checksums(profile)
    names = [name for name in committed if _hashed(name) and name not in EXCLUDED]
    assert len(names) >= 14  # 5 waveforms and 5 x 2 reference files
    mismatched = [
        name for name in names if sha256_file(regenerated / profile / name) != committed[name]
    ]
    assert mismatched == []


@pytest.mark.parametrize("profile", PROFILES)
def test_committed_files_match_committed_checksums(profile):
    """A byte flip in output/ must fail, independent of regeneration."""
    committed = _committed_checksums(profile)
    names = [name for name in committed if _hashed(name) and name not in EXCLUDED]
    assert len(names) >= 14
    names.append("experiment_manifest.csv")
    mismatched = [
        name for name in names if sha256_file(COMMITTED / profile / name) != committed[name]
    ]
    assert mismatched == []


@pytest.mark.parametrize("profile", PROFILES)
def test_checksum_listing_matches_excluding_metadata(regenerated, profile):
    """Same entries and digests, minus metadata lines (those embed the version)."""

    def lines(path: Path) -> list[str]:
        return [line for line in path.read_text().splitlines() if "_metadata.json" not in line]

    new = lines(regenerated / profile / "checksums.sha256")
    old = lines(COMMITTED / profile / "checksums.sha256")
    assert len(old) == 16  # 5 waveforms, 10 reference files, manifest
    assert new == old


@pytest.mark.parametrize("profile", PROFILES)
def test_no_files_added_or_missing(regenerated, profile):
    def listing(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}

    # validation_results.csv is written by `opticps validate`, not by generate_all.
    expected = listing(COMMITTED / profile) - {"validation_results.csv"}
    assert listing(regenerated / profile) == expected


@pytest.mark.parametrize("profile", PROFILES)
def test_experiment_manifest_byte_equal(regenerated, profile):
    new = (regenerated / profile / "experiment_manifest.csv").read_bytes()
    old = (COMMITTED / profile / "experiment_manifest.csv").read_bytes()
    assert new == old


@pytest.mark.parametrize("profile", PROFILES)
def test_metadata_equal_without_generator(regenerated, profile):
    paths = sorted((COMMITTED / profile / "references").glob("*/*_metadata.json"))
    assert len(paths) == 5
    for old in paths:
        new = regenerated / old.relative_to(COMMITTED)
        _assert_close(_strip_generator(new), _strip_generator(old), old.name)


def test_adaptive_selection_numerically_equal(regenerated):
    new = json.loads((regenerated / "adaptive_selection.json").read_text())
    old = json.loads((COMMITTED / "adaptive_selection.json").read_text())
    _assert_close(new, old)
    assert math.isfinite(new["design_psnr_db"])
