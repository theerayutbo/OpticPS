# C1 Dev handoff (Gate 0 + byte anchor)

Base a2eb969, branch v1.3-mpam. Local commit only; nothing pushed, merged or tagged.

## Baseline at a2eb969
- pytest: 368 tests, all passed (368 dots, no F/s/x/E; summary line hidden by addopts -q). Collected total now 377.
- ruff check: pass. ruff format --check: 53 files formatted. mypy: no issues in 44 files.
- Python 3.11.15, numpy 2.4.6, scipy 1.17.1.
- license_audit: 34 packages, 0 flagged; sbom.cdx.json unchanged (not stale, not touched).

## Anchor
- tests/test_pam4_anchor.py, marker slow, 9 tests, module fixture, tmp dir only.
- Uses generate_all (the `opticps generate` path) with untouched configs/m8199b_profiles.yaml at full size.
- Result: all match on unmodified code. No mismatches, EXCLUDED is empty. Runtime about 5.4 s.
- Also checks file set equality, ignoring validation_results.csv (written by `opticps validate`, not by generate).

## Files
- New: tests/test_pam4_anchor.py, docs/ROADMAP_STATUS.md, docs/FEATURE_GAP_MATRIX.md, docs/DEPENDENCY_EXCEPTIONS.md, this file.
- Edited: docs/CLEAN_ROOM_DECLARATION.md (rewritten), docs/DEPENDENCY_AUDIT.md (re-run line), docs/engineering_log/LOG.md, STATUS.md.
- No change under src/, output/, results/, configs/. Roadmap files untracked.

## For Loki
- Check CLEAN_ROOM_DECLARATION wording against the task: no statement about who read the comparison.
- FEATURE_GAP_MATRIX statuses are from reading code, not from running it; spot-check a few file:line cites.
- The pytest count comes from dots plus collect count, not a summary line.
- Anchor was run on macOS only.
- Observation: PAM4 waveform names must stay (payload RNG uses crc32 of the name).
