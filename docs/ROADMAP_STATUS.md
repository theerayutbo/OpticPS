# Roadmap v2 status

Owner roadmap: `OpticPS_Claude_Code_Roadmap_v2.md` (untracked, not committed). Plan: `docs/orchestration/opticps-v2/PLAN.md`. Last updated 2026-10-31 (C1, Gate 0).

## Baseline (written before any code change)

| Item | Value |
|---|---|
| Baseline HEAD | `a2eb9692f9bafcc10621b9a44cdf94c4976bce36` (a2eb969, "Update hardware status from the M8199B data sheet") |
| Branch | `v1.3-mpam`, created from a2eb969; baseline commit is also the tip of `main` |
| Dirty state at baseline | clean tracked tree; untracked: `OpticPS_Claude_Code_Roadmap.md`, `OpticPS_Claude_Code_Roadmap_v2.md`, `docs/orchestration/opticps-v2/` |
| Roadmap v2 SHA-256 | `c9896ffcb86572a993710e737a315d32df1e4ae3bb549eff86bc49d469847368` |
| Package version | 1.2.0 |
| Python / numpy | 3.11.15 / 2.4.6 (uv-managed environment) |
| Not committed on purpose | both roadmap files (owner's); the SHA-256 above is the record |

### Baseline results at a2eb969

| Command | Result |
|---|---|
| `uv run pytest -q` (default addopts hide the summary line) | 368 tests, all passed: the progress output was 368 dots, no F, s, x or E. `pytest --co` at baseline would list 368 tests (377 now including the 9 anchor tests). Wall time about 5 to 10 minutes while other work ran on the machine |
| `uv run ruff check src tests scripts/license_audit.py` | All checks passed |
| `uv run ruff format --check src tests` | 53 files already formatted |
| `uv run mypy` | Success: no issues found in 44 source files |
| `uv run python scripts/license_audit.py` | 34 installed packages, 0 flagged; SBOM identical to committed |

The pytest count was derived from the dot count and the collected total, not from a summary line, because `addopts = "-q"` plus `-q` suppresses it.

### After C1

| Command | Result |
|---|---|
| `uv run pytest -o addopts="-q -rN"` | `377 passed in 232.75s` |
| Byte anchor (`tests/test_pam4_anchor.py`, marker `slow`, runs in default pytest) | 9 passed in about 5.4 s on the first and second run. No file mismatched; the exclusion table `EXCLUDED` is empty |
| Lint, format, mypy | pass with the new test file |

## Byte anchor

Regenerates both profiles into a pytest temporary directory with `generate_all` (the function behind `opticps generate`) from the untouched `configs/m8199b_profiles.yaml` at full training size (400,000 samples, grid step 0.005). Compared with committed `output/keysight_m8199b/`:

- SHA-256 of every `waveforms/**/*.csv`, `references/*/*_symbols.csv` and `*_info_bits.txt` against that profile's `checksums.sha256`.
- `experiment_manifest.csv` byte-equal.
- `*_metadata.json` equal after deleting the `generator` key (the version string there is expected to change).
- `adaptive_selection.json` numerically equal at relative 1e-12.
- File set equal, ignoring `validation_results.csv`, which `opticps validate` writes and `generate_all` does not.

Result: all equal. The anchor is a valid baseline for Stage 1 on this platform (macOS, Python 3.11.15, numpy 2.4.6, scipy 1.17.1). It was not run on Linux here; CI runs the full suite on ubuntu and macos.

## Stage checklist

Statuses follow PLAN.md. Nothing here exceeds step 3, `SYNTHETIC END-TO-END VERIFIED`, of the claims ladder. Matrix detail: `docs/FEATURE_GAP_MATRIX.md`.

| Stage | Status | Evidence |
|---|---|---|
| Gate 0 audit (C1) | DONE in this commit, pending independent review | this file, `docs/FEATURE_GAP_MATRIX.md`, `docs/DEPENDENCY_EXCEPTIONS.md`, `docs/CLEAN_ROOM_DECLARATION.md`, `tests/test_pam4_anchor.py` |
| Stage 1 adaptive M-PAM | NOT STARTED (C2 to C8) | PAM4-bound sites listed in `docs/FEATURE_GAP_MATRIX.md` |
| Stage 2 IM/DD impairments, receiver | NOT STARTED | |
| Stage 3 campaign engine, UXR intake | NOT STARTED; real-file import `BLOCKED: REAL UXR EXPORT REQUIRED` | |
| Stage 4 calibrated channel | PARTIAL / BLOCKED (laboratory validation needs real captures) | per-level Gaussian `ChannelEstimate` exists in `optimization/adaptive.py` |
| Stage 5 causal adaptive feedback | NOT STARTED | |
| Stage 6 FEC, PAS | NOT STARTED; must be named `FEC-assisted shaped M-PAM` unless PAS is proven | |
| Stage 7 hardware-in-the-loop | NOT STARTED; `BLOCKED: HARDWARE CONFIGURATION REQUIRED` | |
| Stage 8 dashboard, publication | NOT STARTED | |

Stopping point for this run: end of S2-3 (PLAN.md).

## Deviations from Roadmap v2

1. Stage 4 is P0/P1 and M5 depends on a synthetic M4. A policy judged on the project's own model can show correctness and overhead accounting, not benefit.
2. M3 is described as depending only on M0. For M-PAM intake it also needs the frame and export work in C5 and C6.
3. The Stage 5 latency budget is an assumption, to be treated as an experimental design parameter, not a hardware fact.
4. The clean-room rule can only mean not searching for or recalling third-party code on purpose. It cannot certify the model's training data. See `docs/CLEAN_ROOM_DECLARATION.md`.

Other differences, from PLAN.md: work is on `v1.3-mpam` with local commits only (no push, merge or tag); `ruff format --check` passed at baseline, so no separate format commit is needed; the roadmap files stay untracked.

## Open items

- Opus review of C1.
- Anchor not yet run on Linux.
