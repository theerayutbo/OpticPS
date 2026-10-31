# Roadmap v2 status

Owner roadmap: `OpticPS_Claude_Code_Roadmap_v2.md` (untracked, not committed). Plan: `docs/orchestration/opticps-v2/PLAN.md`. Last updated 2026-10-31 (C4, generic adaptive selection, constraints, acquisition guard).

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
| `uv run pytest -o addopts="-q -rN"` on the baseline source (run with `--ignore=tests/test_pam4_anchor.py`, since `src/` is unchanged) | `368 passed in 212.10s (0:03:32)`. The first baseline run used default `-q`, which hides the summary; its progress output was 368 dots, no F, s, x or E |
| `uv run ruff check src tests scripts/license_audit.py` | All checks passed |
| `uv run ruff format --check src tests` | 53 files already formatted |
| `uv run mypy` | Success: no issues found in 44 source files |
| `uv run python scripts/license_audit.py` | 34 installed packages, 0 flagged; SBOM identical to committed |

Default `addopts = "-q"` plus `-q` suppresses the summary line, so the counts above use `-o addopts="-q -rN"`.

### After C1

| Command | Result |
|---|---|
| `uv run pytest -o addopts="-q -rN"` | `381 passed in 214.32s` after the review fixes (377 after the first C1 commit) |
| Byte anchor (`tests/test_pam4_anchor.py`, marker `slow`, runs in default pytest) | first version 9 passed in about 5.4 s; after review fixes 13 passed in 5.9 s. No file mismatched; the exclusion table `EXCLUDED` is empty |
| Lint, format, mypy | pass with the new test file |

### After C2

| Command | Result |
|---|---|
| `uv run pytest -o addopts="-q -rN"` | `493 passed in 238.89s` after the C2 review fixes (383 after the C1 fix commit, plus 110 in `tests/test_mpam_rates.py`; 469 before the review fixes); anchor included and green |
| Quadrature | equal sigma: 120 nodes are 1.9e-8 to 4.1e-8 from the 320-node value at 8-30 dB, so the 1e-9 requirement fails; default nodes are 240 for M = 2, 8, 16 (within 4.2e-10 of 320 nodes, 3.9e-10 of independent integrators, 8-30 dB, 3 PMFs) and 120 for M = 4. Unequal sigma: per-level Gauss-Hermite is unreliable (M = 4 at 120 nodes 2.0e-4 at spread 4, 6.3e-3 at 9); M != 4 now uses a common-grid Gauss-Legendre integrator (1.0e-13 vs `quad_vec`, 8-30 dB, spreads 2-64, 10 ms per call at M = 16); M = 4 stays legacy and warns above spread 3.0. See ALGORITHM_PROVENANCE |
| Lint, format, mypy | pass |

### After C4

| Command | Result |
|---|---|
| `uv run pytest -o addopts="-q -rN"` | `698 passed in 485.64s` after the C4 fix round (678 after the first C4 commit, 604 before C4: +4 in `tests/test_mpam_rates.py`; `tests/test_mpam_adaptive.py` 48 tests (3 slow), `tests/test_constraints.py` 26, `tests/test_leakage.py` 16); anchor included and green |
| Optimiser | M = 8, 16: all 11 starts agree to 6.3e-13 bit and 2.7e-7 in q (SMD and BMD, 22 dB and 28 dB); 11 of 11 endpoints feasible over M = 8 8 to 18 dB and M = 16 10 to 22 dB with the floor 1/n; runtime per call M = 16 13 to 15 s (unequal sigma) or 20 to 22 s (equal sigma), M = 8 about 3 s (note: `docs/notes/mpam_adaptive_constraints.md`) |
| Lint, format, mypy | pass |

## Byte anchor

Regenerates both profiles into a pytest temporary directory with `generate_all` (the function behind `opticps generate`) from the untouched `configs/m8199b_profiles.yaml` at full training size (400,000 samples, grid step 0.005). Compared with committed `output/keysight_m8199b/`:

- SHA-256 of every `waveforms/**/*.csv`, `references/*/*_symbols.csv` and `*_info_bits.txt` against that profile's `checksums.sha256`.
- `experiment_manifest.csv` byte-equal.
- `*_metadata.json` equal after deleting the `generator` key (the version string there is expected to change); floats at relative 1e-12, strings and ints exact.
- `adaptive_selection.json` numerically equal at relative 1e-12.
- Committed files re-hashed against the committed `checksums.sha256` (a byte flip in `output/` fails); regenerated `checksums.sha256` equal to committed, metadata lines excluded.
- File set equal, ignoring `validation_results.csv`, which `opticps validate` writes and `generate_all` does not.

Result: all equal. The anchor is a valid baseline for Stage 1 on this platform (macOS, Python 3.11.15, numpy 2.4.6, scipy 1.17.1). It was not run on Linux here; CI runs the full suite on ubuntu and macos.

## Stage checklist

Statuses follow PLAN.md. Nothing here exceeds step 3, `SYNTHETIC END-TO-END VERIFIED`, of the claims ladder. Matrix detail: `docs/FEATURE_GAP_MATRIX.md`. A checked box means done and evidenced; an unchecked box carries its status.

- [x] Gate 0 audit (C1), done in this commit and in the fix commit after the first review; independent review of the fix pending. Evidence: this file, `docs/FEATURE_GAP_MATRIX.md`, `docs/DEPENDENCY_EXCEPTIONS.md`, `docs/CLEAN_ROOM_DECLARATION.md`, `tests/test_pam4_anchor.py`.
- [ ] Stage 1 adaptive M-PAM: IN PROGRESS. PAM4-bound sites: `docs/FEATURE_GAP_MATRIX.md`.
  - [x] C1 Gate 0 and anchor.
  - [x] C2 `optimization/rates.py` generic in M (SMD, BMD, `bmd_raw`, order-aware PSNR, average SNR) with `tests/test_mpam_rates.py`; PAM4 values bit-identical, anchor green. Independent review pending.
  - [x] C3 `shaping/distributions.py` pair family (`symmetric_from_pairs`, `pairs_of`, `mb_for_entropy`; lam > 0 inner-heavy), `distribution_matching/ccdm.py` `quantize_symmetric_composition` (equal to legacy at M=4 wherever legacy does not split a pair; legacy untouched), `symmetric_rate_loss`, `InvalidSymbolError`, `scripts/profile_ccdm.py` and `docs/notes/ccdm_profile.md` (M=16, n=1024: 9.3 ms encode, 9.9 ms decode, threshold 1 s not exceeded), `tests/test_mpam_shaping.py`. Independent review pending.
  - [x] C4 `optimization/adaptive.py` generic in M (`estimate_channel`, `simulate_training_capture` with `order`; `optimise_symmetric` for M = 4, 8, 16 over the pair simplex with bounds [1/n, 1/2]; SMD multistart agreement check, BMD best of 11 starts, every start and candidate logged; exact quantised objective evaluated after the continuous fit; `fixed_menu`, `best_fixed` (takes training `Acquisition`s, checked), `oracle_not_a_baseline`; `AcquisitionId`, `assert_independent`, `simulate_acquisitions`, `select_on_acquisitions`; `Selection` gains `order, family, parameters, starts, claim`, legacy serialisation unchanged), `optimization/constraints.py` (`FixedPeak`, `FixedAverageOpticalPower`, `FixedOMA`, `EqualRealizedUserRate`, `Feasibility`), rates.py minors (separate commit C4a), `tests/test_mpam_adaptive.py`, `tests/test_constraints.py`, `tests/test_leakage.py`, `docs/notes/mpam_adaptive_constraints.md`. Anchor green. Independent review (Loki) FAIL at 2b9e1fe; fixed in the fix round (see Deviations 6 and 7, and the tracked lines below); re-review pending.
  - [ ] C5 to C8: NOT STARTED.
- [ ] Tracked for C5: pin the best-fixed menu and entropy deficits in `configs/mpam_profiles.yaml` and forbid a run-time override for reported baselines. `fixed_menu(order, entropy_deficits)` and the `menu=` argument of `evaluate_menu`/`best_fixed` can change the baseline at run time today.
- [ ] Tracked for C7: PLAN describes `assert_disjoint` as checking content; it is id-only. Migrate `compare`, `uxr_compare` and `demo` callers to `assert_independent` (`AcquisitionId` with content hash), which recomputes the digest of an `Acquisition`.
- [ ] Stage 2 IM/DD impairments, receiver: NOT STARTED.
- [ ] Stage 3 campaign engine, UXR intake: NOT STARTED; real-file import `BLOCKED: REAL UXR EXPORT REQUIRED`.
- [ ] Stage 4 calibrated channel: PARTIAL / BLOCKED (laboratory validation needs real captures). A per-level Gaussian `ChannelEstimate` exists in `optimization/adaptive.py` (generic in M since C4).
- [ ] Stage 5 causal adaptive feedback: NOT STARTED.
- [ ] Stage 6 FEC, PAS: NOT STARTED; name it `FEC-assisted shaped M-PAM` unless PAS is proven.
- [ ] Stage 7 hardware-in-the-loop: NOT STARTED; `BLOCKED: HARDWARE CONFIGURATION REQUIRED`.
- [ ] Stage 8 dashboard, publication: NOT STARTED.

Stopping point for this run: end of S2-3 (PLAN.md).

## Deviations from Roadmap v2

1. Stage 4 is P0/P1 and M5 depends on a synthetic M4. A policy judged on the project's own model can show correctness and overhead accounting, not benefit.
2. M3 is described as depending only on M0. For M-PAM intake it also needs the frame and export work in C5 and C6.
3. The Stage 5 latency budget is an assumption, to be treated as an experimental design parameter, not a hardware fact.
4. The clean-room rule can only mean not searching for or recalling third-party code on purpose. It cannot certify the model's training data. See `docs/CLEAN_ROOM_DECLARATION.md`.
5. C3 process deviation: the independent review (Loki, Opus) returned FAIL twice on C3. The code was found correct; both rounds were about documentation statements that were false (M = 4 equivalence n lists, silent-misdecode statistics, error-hierarchy wording). Aria continued to C4 without waiting for a third review because the findings were documentation-only and involved no design decision, and informed the owner. C3 is therefore not review-PASS at the time C4 starts; its second fix commit is 5a851dd.

6. C4 decision, stated in neither PLAN nor the roadmap: the generic optimiser's pair probabilities are bounded below by q_j >= 1/n (n the block length), upper bound 1/2. 1/n is the smallest probability that quantises to a nonzero count, so an optimum at the floor is representable. A first floor of 1/(4n) was unrepresentable (11 of 11 endpoints infeasible over most of the sweep, selection fell back to a Maxwell-Boltzmann grid). Every optimum is therefore an optimum over the constrained set, and selections report where the floor is active.
7. C4 uniform baseline: at M a power of two the uniform PMF is the direct mapping (`frame.py` `direct_uniform`) and pays no matcher loss; the generic path charges it 0 everywhere. The committed v1.x PAM4 selection (`select_distribution`, `adaptive_selection.json`) still charges its uniform member the CCDM loss (0.0146484375 bit at n = 1024) and is left unchanged because it is pinned byte for byte by the anchor. That is a known limitation of the committed v1.x result: inside that selection the uniform member (p_outer = 0.25) carries a CCDM loss the repository's direct-uniform waveform does not pay, so any adaptive-over-uniform margin read from its candidate list is overstated by that loss.

Other differences, from PLAN.md: work is on `v1.3-mpam` with local commits only (no push, merge or tag); `ruff format --check` passed at baseline, so no separate format commit is needed; the roadmap files stay untracked.

## Open items

- Opus review of C1.
- Anchor not yet run on Linux.
