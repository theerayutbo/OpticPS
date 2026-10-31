# Roadmap v2 status

Owner roadmap: `OpticPS_Claude_Code_Roadmap_v2.md` (untracked, not committed). Plan: `docs/orchestration/opticps-v2/PLAN.md`. Last updated 2026-10-31 (C5, M-PAM frame, export, validator, profiles config).

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

### After C5

| Command | Result |
|---|---|
| `uv run pytest -o addopts="-q -rN"` | `768 passed in 526.47s` (698 before C5a; C5a adds 9: 5 in `tests/test_constraints.py` (counting parametrised cases), 2 in `tests/test_leakage.py`, 2 in `tests/test_mpam_adaptive.py`; C5 adds `tests/test_mpam_frame_rx.py` 54 (1 slow) and `tests/test_mpam_config.py` 7); anchor included and green, no anchor test edited |
| Frame lengths (symbols, sps, samples; head / payload) | Protocol A, 8 GBd, sps 28: 32768 symbols, 917504 samples for M = 2, 4, 8, 16 (head 1024, 1024, 2048, 3072). Protocol A, 56 GBd, sps 4: 65536, 262144 (same heads). Protocol B, 224 GSa/s: M = 2 sps 2 131072 symbols 262144 samples; M = 4 sps 4 65536, 262144; M = 8 sps 6 43008, 258048 (112 / 3 GBd); M = 16 sps 8 32768, 262144. All multiples of 512, below 1,048,576; all FEASIBLE under `check_frame_fit` |
| Training length at M = 16 (160 per level) | Simulated with `estimate_channel`: relative standard deviation of the per-level sigma estimate 5.64 % (theory 1 / sqrt(2 (N - 1)) = 5.61 %); the 95 % half width is 11.1 %. At the 512-symbol head (32 per level) it would be 12.6 %. M = 8 (192 per level) 5.09 %, M = 4 (128) 6.26 % |
| Lint, format, mypy | pass |

PLAN's "sigma deviates about +-5.6 %" for the PAM16 head is a one-sigma figure, not a bound: the measured relative standard deviation is 5.64 % and 95 % of the estimates fall within +-11 %. The head length stands (160 per level), the wording is corrected here.

### C5 fix round (after the independent review)

| Item | Result |
|---|---|
| `uv run pytest -o addopts="-rN -q"` | `853 passed in 547.11s` (768 before the fix round; +85: tests/test_mpam_config.py 7 to 31, tests/test_mpam_frame_rx.py 54 to 115); anchor green, no anchor or golden test edited |
| Committed PAM4 packages under the stricter validator | 215 checks each (was 139), 0 failed; the CLI exits 0 on a copy |
| 45 M = 2 / 8 / 16 waveforms regenerated in a temporary folder (not committed) and validated | 3 profiles x M = 2, 8, 16: 53 checks (M = 2), 365 (M = 8), 363 (M = 16) each package, 0 failed |
| Mutants | 41 mutants of the new code (the ten survivors of the review plus the new guards) re-applied; each fails a test (list in `handoff/C5_dev.md`) |

Net uniform rates of Protocol B (112 Gb/s is a nominal label; head 1024 / 1024 / 2048 / 3072 symbols are not payload): M = 2 111.125, M = 4 110.25, M = 8 106.67, M = 16 101.5 Gb/s.

Realised-rate equalisation per member, Protocol B, reported never applied (`rate_equalisation_common_target` in the metadata is the right column; Protocol A holds the symbol rate and has no common target):

| Member (Protocol B) | Bits per block | Same-order target | Common target 110.25 Gb/s |
|---|---|---|---|
| PAM4_Uniform | 2048 | +0.00 % FEASIBLE | 224.0 GSa/s FEASIBLE |
| PAM4_Fixed_PS70 | 1912 | +7.11 % FEASIBLE | 239.9 GSa/s FEASIBLE |
| PAM4_Fixed_PS80 | 1747 | +17.23 % INFEASIBLE | 262.6 GSa/s INFEASIBLE |
| PAM4_Fixed_Outer70 | 1912 | +7.11 % FEASIBLE | 239.9 GSa/s FEASIBLE |
| PAM8_Uniform | 3072 | +0.00 % FEASIBLE | 231.5 GSa/s FEASIBLE |
| PAM8_Fixed_Inner_H288 | 2917 | +5.31 % FEASIBLE | 243.8 GSa/s FEASIBLE |
| PAM8_Fixed_Inner_H272 | 2753 | +11.59 % FEASIBLE | 258.4 GSa/s INFEASIBLE |
| PAM8_Fixed_Outer_H288 | 2918 | +5.28 % FEASIBLE | 243.7 GSa/s FEASIBLE |
| PAM8_Fixed_Outer_H272 | 2756 | +11.47 % FEASIBLE | 258.1 GSa/s INFEASIBLE |
| PAM16_Uniform | 4096 | +0.00 % FEASIBLE | 243.3 GSa/s FEASIBLE |
| PAM16_Fixed_Inner_H388 | 3912 | +4.70 % FEASIBLE | 254.8 GSa/s FEASIBLE |
| PAM16_Fixed_Inner_H372 | 3749 | +9.26 % FEASIBLE | 265.8 GSa/s INFEASIBLE |
| PAM16_Fixed_Outer_H388 | 3911 | +4.73 % FEASIBLE | 254.8 GSa/s FEASIBLE |
| PAM16_Fixed_Outer_H372 | 3749 | +9.26 % FEASIBLE | 265.8 GSa/s INFEASIBLE |

## Roadmap v2.1 delta (Stage 3A, gate E0, written 2026-10-31)

Documents compared (both untracked, never committed; the hashes are the record):

| File | SHA-256 |
|---|---|
| `OpticPS_Claude_Code_Roadmap_v2.md` | `c9896ffcb86572a993710e737a315d32df1e4ae3bb549eff86bc49d469847368` (equals the baseline record above) |
| `OpticPS_Master_Roadmap_v2.1.md` | `e81cb2c80c53006d5045ebbe53586531a3df193b8e5e04def9ca30e1549d5938` |
| `OpticPS_External_Benchmark_Claude_Code_Brief.md` | `15cdf18b626869a7af0b57b625222ecd2a08595e6bbbb1b549a9ec2de2d18848` |

Method: `diff` of the two files. v2.1 differs from v2 in 9 hunks and removes only 5 lines (title, status line, "Supersedes", the sequencing sentence, the J2 assignment sentence). Everything else is addition. Sections A, B, C, stage definitions 0 to 8 other than the new Stage 3A, E, G, H, I (one added row), J1, J3 and K are byte-identical.

| Change in v2.1 | Effect on gated or planned Stage 1 to 3 work |
|---|---|
| New Stage 3A (external published-dataset benchmark) and milestone row M3E (depends on M0 + M3 offline; M1/M2 where relevant) | New work only. No Stage 1 to 3 exit gate text changed. Stage 3 exit gate (synthetic campaign, real import `BLOCKED: REAL UXR EXPORT REQUIRED`) is unchanged. |
| New section L (gates E0 to E4, error codes, L4 tests) | New package `src/opticps/benchmarks/` and `configs/benchmarks/`; tests are additive. L4 "no changed historic PAM4 outputs" repeats A2 and the byte anchor. |
| Sequencing sentence: M3E source registration and fixtures start in parallel with M3 | Scheduling only. |
| File table row `src/opticps/benchmarks/` | Additive. |
| J2 prompt: "complete the source/provenance inventory plus test fixtures for Stage 3A / Section L" | Additive; "Do not bulk-download external datasets without authorization". |
| "Supersedes" now names v2 and calls v2.1 the single master roadmap | Documents that cite "Roadmap v2" (this file, `PLAN.md`, the C1 to C5 handoffs) now cite the superseded file. Their content and the recorded v2 hash stay correct for the gates passed under it. |
| Section B list of allowed references | Unchanged in v2.1 (Wiegart DOI was already there). |

Gate check: **no passed or planned Stage 1 to 3 gate (C1 to C5, M-PAM, byte anchor, profiles) is invalidated by v2.1.** No existing API, golden, committed waveform, result or `configs/m8199b_profiles.yaml` was touched by E0.

Points to carry, none a gate failure:
- Stage 3's UXR importers stay `UNVERIFIED AGAINST REAL FILES`; the E0 importer audit (docs/benchmarks/MISSING_PARAMETERS.md) shows an unknown-format `.bin` is rejected by `read_bin`, so external TERIPHIC captures need their own adapter (E1) rather than the UXR path.
- The brief says "where there is tension, apply the stricter rule" and tells the executor not to download without authorisation. A transfer of two TERIPHIC files into `data/external/teriphic/` was found running at E0 time, started outside E0 (see SOURCE_REGISTER.md). Authorisation for it is the owner's to confirm.
- v2.1 L2/E0 says "Record actual repository HEAD and current tests": E0 baseline below.

### Gate E0 record

| Item | Value |
|---|---|
| Base HEAD at E0 start | `8129eca77e71ea712c20c124e7a75bad4b32bac8` (`v1.3-mpam`; tracked tree clean except the pre-existing `docs/orchestration/opticps-v2/CHECKPOINT.md` edit, which E0 did not touch) |
| E0 deliverables | `docs/benchmarks/{SOURCE_REGISTER,MISSING_PARAMETERS,FIT_HOLDOUT_PLAN}.md`, `src/opticps/benchmarks/{provenance,catalog}.py`, `configs/benchmarks/*.yaml`, `tests/test_benchmark_provenance.py`, `.gitignore` rule `data/external/` |
| Plan hash | `6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a`, committed before any other E0 file (commit 8900748) |
| Baseline and final test counts | `853 passed` at 8129eca (`-o addopts="-q -rN"`, 23 min under load); `905 passed` with E0 (+52, all in `tests/test_benchmark_provenance.py`); anchor 15 passed; ruff check, ruff format --check, mypy clean; `scripts/license_audit.py` 34 packages, 0 flagged (no dependency change) |
| Downloads, push, merge, tag, hardware | none by E0 |
| E0 fix rounds 1 to 3 (PENDING REVIEW, the third fix round has not been reviewed) | Plan Revision 3 pin `dd2f800050a18b4da52369e4f62c9ef15fb8043bd2efc5f947b529e7b1e81535` (previous `45d9088c...`, Revision 1 `42a578f5...`, original `6bf4238a...`); the freeze guard promises only accidents and casual re-tuning, no tamper-proofing, no date proof (plan R3.1). Final counts at the round 3 commit: `1437 passed` in the shared checkout (includes N1 tests; `tests/test_benchmark_provenance.py` 355 tests), anchor 15 passed, ruff check, ruff format --check, mypy clean, `license_audit.py` 34 packages 0 flagged, `scripts/mutate_benchmarks.py` 60 applied, 60 killed. Earlier pins and the `905 passed` above are those of the first E0 commit. |

### Gate N0 record (NANF workstream, 2026-10-31)

| Item | Value |
|---|---|
| Base HEAD at N0 start | `94a3ec9` (`v1.3-mpam`) |
| N0 deliverables | `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md`, `docs/NANF_SOURCES_AND_PROVENANCE.md`, `tests/test_nanf_benchmark.py`, handoff `docs/orchestration/opticps-v2/handoff/N0_dev.md`, entries in this file, `ALGORITHM_PROVENANCE.md`, `engineering_log/LOG.md` |
| Plan hash | original `c4771dc125c3daeaf28b429de2f31f3ca25a5d3645a6f59e1d8dd9b9bf0bef22`, committed (9a891c9) before any workbook value was read; after Amendment 1 (843d223) the pin is `92b20966c409958729946f31243216b49fe796d7b9f4ac22f33f30c854dce5c0` in `tests/test_nanf_benchmark.py` |
| Label | `LITERATURE BENCHMARK / CALIBRATION ONLY` (one NANF spool, one SSMF spool; session count not stated, readme says May 2020) |
| Licence | dataset CC BY 4.0 at the DataCite record only (readme blank, landing page unread); paper under IEEE terms. No third-party data, PDF or figure in Git. |
| Tests | `912 passed` (905 at E0 plus 7 in `tests/test_nanf_benchmark.py`); anchor 15 passed; `ruff check`, `ruff format --check`, `mypy` clean; no dependency change |
| Fit, simulation, push, merge, tag, hardware | none |
| N0 fix round tests | `1107 passed` in the shared checkout (includes the parallel E0 fix work; `tests/test_nanf_benchmark.py` 10 tests, was 7); anchor green (in the default run); ruff check, ruff format --check, mypy clean |
| N0 fix round | review FAIL (4 MAJOR) addressed by plan Amendment 1 (previous pin `c4771dc1...bef22` recorded; current pin in `tests/test_nanf_benchmark.py`), corrected sources doc, content-based third-party guard; see handoff `N0_dev.md` |

### Gate N1 record (NANF workstream, 2026-10-31)

| Item | Value |
|---|---|
| Step 1 | plan Amendment 2 (commit 8f8fc7a): previous pin `92b20966...ce5c0`, new pin `ec0f325a118fcc8162e21de2b6acf1662b6d3ea6db14bfed0c3a507ff2827aa5` in `tests/test_nanf_benchmark.py`; closes N0 review items 1 to 8 and 13; guard survivors of item 9 closed (all four digests pinned and cross-checked against the Sources table, size bound, `.tsv`, `tests/` and `configs/` guarded, prefix match against appended copies, original-section prefix hash) |
| Step 2 deliverables | `FiberProfile` and loader in `optical_channel/fiber.py`; profile propagation in `optical_channel/link.py`; `configs/fibers/*.yaml` (5 files); `tests/test_nanf_profiles.py`, `tests/test_nanf_propagation.py`, `tests/nanf_profile_helpers.py`; `docs/NANF_MODEL_VALIDITY.md`; handoff `handoff/N1_dev.md` |
| Physics check | first null from the propagation model with square-law detection of a small-signal tone: 29.386 GHz (SSMF, 4.53 km, D 15.95), 27.970 GHz (5 km), 80.158 GHz (NANF, 4.76 km, D 2.04), against the pre-registered 29.39, 27.97, 80.2 |
| Unknowns | no NANF attenuation known (N2); Altuna and Wang values are `user-assumed` (owner brief, not read from the papers); the Hong D is one assumed value at 1550 nm |
| G.652.D | unchanged (existing tests and golden values untouched; anchor green) |
| Tests, anchor, lint | see `handoff/N1_dev.md` for the final counts |
| Fit, scoring, simulation of paper curves, push, merge, tag, hardware | none |

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
  - [x] C5a C4 review leftovers (separate commit): `FixedOMA` INACTIVE reason true when the outer pair is unused, swing 0 in the search grid and a refined maximum (target at the analytic peak 4.6154 V is FEASIBLE, just above it INFEASIBLE), mutation-killing tests (range tolerance, lower-edge tolerance, `_assert_unique` in `_training_channel`, `floor_active_selected_pairs`), `selected_on` says the split label is declared, optimised endpoints are named `optimised_from:<start>`, `_argmax_menu` honours `in_bounds`, note corrections (post hoc g = 1.8 channel, BMD start disagreement, rate(P) against rate(counts/n), PAM16 single-start against multistart).
  - [x] C5 `ModulationSpec` (frozen) and `order: int = 4` in `modulation/pam.py`, `transmitter/frame.py` (`Frame.order` last; head 512 + {512, 512, 1536, 2560}, head multiple of 1024, direct uniform at log2 M bits per symbol, PAM4 byte-identical), `configs/mpam_profiles.yaml` (`config_schema_version: 2`, Protocol A 8 / 56 GBd, Protocol B 112 Gb/s) with loader `transmitter/mpam_config.py` (pinned menu, M8199B fit check with INFEASIBLE, rate-equalisation report, DAC step diagnostic), `transmitter/export.py` M-PAM generator (manifest schema v2, stream keys, evidence label; PAM4 path and its 40 columns unchanged), `measurement/validate_export.py` (both schemas, per-order head and level checks, default-deny on unknown schema), `tests/test_mpam_frame_rx.py`, `tests/test_mpam_config.py`. Independent review FAILED (2 MAJOR: `reportable` decorative, free evidence label); fixed in the C5 fix round (see below), re-review pending.
  - [ ] C6 to C8: NOT STARTED.
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

8. C5 decision (enforced since the fix round), not in PLAN: the pinned best-fixed menu lives in the YAML and in code (`adaptive.DEFAULT_FIXED_DEFICITS`); the loader refuses a file whose deficits differ, `fixed_menu` raises `BaselineOverrideError` for other deficits unless `exploratory=True` (an `ExploratoryMenu`, never reportable), and `best_fixed(..., menu=...)` returns `reportable=False` for any menu that is not exactly the pinned one. `BestFixed.reportable` has no True default (a hand-built object is not reportable). The export refuses (`BaselineOverrideError`, nothing written) a BestFixed that is not `reportable`, whose order is not the group's, or that is not exactly a member of the pinned menu with that member's PMF (`export.require_reportable_baseline`); the v2 manifest has a `reportable` column and the validator fails a required row that is not `true`, and checks the BestFixed `member=` against the validator's own pinned menu. Reported baselines therefore cannot be changed by an argument, by editing only the YAML, or by passing a replaced selection to the export.
9. C5 decision, not in PLAN: Protocol B frame lengths are chosen here (the plan fixes only sps): 131072, 65536, 43008, 32768 symbols for M = 2, 4, 8, 16, so that every frame is about 260 kSa (258048 to 262144 samples) and payload and head are multiples of 1024. Protocol A uses the v1.2 lengths (32768 and 65536 symbols) for every order. The M-PAM generator writes M = 2, 8, 16 (PAM4 stays on `generate_all`); M = 2 gets PAM2_Uniform only, because its only symmetric PMF is uniform. The design rate of the simulated adaptive / best-fixed selection (1.5 bit per channel use at M = 8, 2.0 at M = 16) is a declared starting point, not derived from a roadmap value.
10. C5 equalisation finding, corrected in the fix round. Two targets, both from code (`mpam_config.rate_equalisation`). (a) SAME-ORDER target (the direct uniform of the same M, head included): the "PS80 class" (entropy deficit 0.28 bit) is INFEASIBLE only at M = 4 (+17.23 %); M = 8 H272 +11.59 % (Inner) / +11.47 % (Outer) and M = 16 H372 +9.26 % are FEASIBLE (inside +14.3 %). "Only PAM4 is INFEASIBLE" is true for this target only. (b) COMMON target, the PAM4 uniform net rate of Protocol B (110.25 Gb/s, the Roadmap's Protocol B matches realised rate including overhead): the same members are INFEASIBLE at M = 8 (H272 258.4 / 258.1 GSa/s) and M = 16 (H372 265.8 GSa/s) too, and PS80 at M = 4 (262.6 GSa/s); only the H288 / H388 / PS70 members and the uniforms stay FEASIBLE (limit 256 GSa/s). The status of every case is in the table below, written by the code, not by hand.

Other differences, from PLAN.md: work is on `v1.3-mpam` with local commits only (no push, merge or tag); `ruff format --check` passed at baseline, so no separate format commit is needed; the roadmap files stay untracked.

## Open items

- Opus review of C1, and of C5 and C5a.
- C5 does not touch `cli/main.py`, `receiver/*`, `measurement/demo.py`, `compare.py`, `uxr_*` or the reports: `opticps generate` still writes PAM4 only and the M-PAM generator is `export.generate_mpam_all` (CLI in C7, receiver in C6).
- Anchor not yet run on Linux.
