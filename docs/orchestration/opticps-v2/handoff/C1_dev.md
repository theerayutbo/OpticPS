# C1 Dev handoff (Gate 0 + byte anchor), updated after Loki FAIL

Base a2eb969, branch v1.3-mpam. Two local commits (C1, then review fixes). Nothing pushed, merged or tagged.

## Counts
- Baseline a2eb969: 368 passed in 212.10 s (-o addopts="-q -rN", anchor file ignored). ruff, format (53 files), mypy (44 files) clean. Python 3.11.15, numpy 2.4.6.
- After fixes: 381 passed in 214.32 s. Anchor: 13 tests, about 5.9 s, no mismatches, EXCLUDED empty.
- license_audit: 34 packages, 0 flagged, SBOM unchanged.

## Review fixes
1. FEATURE_GAP_MATRIX rewritten to walk roadmap section D bullet by bullet; 1,048,576 caveat kept (verified only if k is 1024).
2. CLEAN_ROOM section 2: rule plus evidence limit. 3. Section 1 quotes the old wording; standards cited separately via ALGORITHM_PROVENANCE.
4. Anchor re-hashes committed files and compares regenerated checksums.sha256 minus metadata lines. 5. Metadata numerics at rel 1e-12, ints and strings exact.
6. DEPENDENCY_EXCEPTIONS: installed vs uv.lock done; all 34 match the lock Python < 3.12 branch; colorama lock-only (win32); numpy/scipy/contourpy differ only on the >= 3.12 branch; pathspec licence is classifier text.
7. Citations fixed (rates.py:20,27,39,51; export.py:35,125,203; frame.py:70; demo.py pam_levels(4)). 8. ROADMAP_STATUS checkboxes, measured baseline time.

## Notes for Loki
- Matrix statuses are from reading code. Anchor run on macOS only.
- Correction: assert_disjoint is id-only, but the UXR ingest registry rejects content duplicates (uxr_ingest.py:141-153); matrix and observations now say so.
