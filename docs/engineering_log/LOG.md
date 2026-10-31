# Engineering log (append-only)

## 2026-10-30 | Phase 0 (pre-build, backfilled) | commit: none yet

Goal: understand the task and check the science before writing code.

Actions and results:
- Inspected `~/Documents/Optics`: only `2005.12428v2.pdf` and `.omc/`. `~/Documents/Optic` does not exist.
- Toolchain: Python 3.14.3 system, uv 0.11.1, Python 3.11 available. No pandoc, LaTeX, LibreOffice or poppler. `gh` logged in as `theerayutbo`; repo `OpticPS` absent. No global git identity.
- Background repo licences via GitHub API: OptiCommPy GPL-3.0; Probabilistic_Constellation_Shaping none; PAM4Receiver NOASSERTION; OpticalSimulation MIT. Their code was not opened.
- Read Wiegart et al. in full (text extracted with pypdf). It shows the optimum under fixed Vpp/ER is outer-heavy, the inverse of the requested PS70/PS80.
- Ran `scripts/prebuild_rate_check.py` (Gauss-Hermite, 80 nodes). Result in FINDINGS F-001.
- Rough CCDM cost: exact multinomial for n=65536 has 123268 bits; 65536 rank-walk steps took 1.32 s in CPython.
- Fable design review (independent recomputation by trapezoid integration, literature and licence check). Confirmed F-001; verdicts in DECISIONS. It ran before the M8199B was confirmed, so its 40 GSa/s objection does not apply.
- User decisions: copyright holder Theerayut Boonkird; project root `~/Documents/Optics`.
- M8199B update received. Profile arithmetic checked: 917504 = 1792×512; 262144 = 512×512; both ≤ 1048576.
- Keysight checks: see VERIFICATION.md and FAILURES X-001.

Next: Phase 1 scaffold.

## 2026-10-30 | Phases 1-3 | commit: this commit

Goal: scaffold, licence audit, modulation, shaping, CCDM, rates.

Commands: `uv sync`; `uv run python scripts/license_audit.py`; `uv run --no-dev --isolated python scripts/license_audit.py`; `uv run pytest tests/test_core.py`.

Results:
- Licence audit: 33 packages with dev, 21 runtime, 0 flagged. `pathspec` is MPL-2.0, dev-only. SBOM at docs/sbom.cdx.json from the runtime set.
- tests/test_core.py: 51 passed in 52.74 s.
- Rates and CCDM table (deterministic, no seed needed):

```
uniform PSNR@1bpcu smd 13.692 bmd 13.854
outer70 gain smd 0.727 bmd 0.627
P0*(bmd@design) (0.36999999999999983, 1.0681240902412985)
10 (0.4949999999999998, 0.7918700134411034)
12 (0.43249999999999983, 0.9308287423932722)
14 (0.3624999999999998, 1.102138587773097)
16 (0.31999999999999984, 1.304936247499706)
18 (0.28749999999999987, 1.526939978972587)
20 (0.2674999999999999, 1.7391117267457326)
22 (0.2574999999999999, 1.8962855262190836)
24 (0.2524999999999999, 1.9750371390623886)
64 PS70 (10, 22, 22, 10) 112 rate 1.75000 loss 0.14604
64 PS80 (6, 26, 26, 6) 100 rate 1.56250 loss 0.13371
256 PS70 (38, 90, 90, 38) 468 rate 1.82812 loss 0.04931
256 PS80 (26, 102, 102, 26) 431 rate 1.68359 loss 0.04454
1024 PS70 (154, 358, 358, 154) 1912 rate 1.86719 loss 0.01506
1024 PS80 (102, 410, 410, 102) 1747 rate 1.70605 loss 0.01431
4096 PS70 (614, 1434, 1434, 614) 7687 rate 1.87671 loss 0.00434
4096 PS80 (410, 1638, 1638, 410) 7037 rate 1.71802 loss 0.00430
65536 PS70 (9830, 22938, 22938, 9830) 123267 rate 1.88091 loss 0.00037
65536 PS80 (6554, 26214, 26214, 6554) 112826 rate 1.72159 loss 0.00036
```

Surprises: none; gains matched the paper within test tolerance on the first run.

Next: Phase 4, M8199B export and validator.

## 2026-10-30 | Correction to the Phases 1-3 entry

"Surprises: none" was wrong. Two planning figures were corrected by the computed results:
- At the declared design point (13.854 dB, uniform R_BMD = 1.0), P0* for BMD is about 0.37, not 0.40. The value 0.40 belongs to the lower PSNR at which the optimized distribution itself reaches 1.0 bpcu.
- PS70 rate loss at n=1024 is 0.015 b/sym, not 0.014.

## 2026-10-30 | Phase 4 M8199B export | commit: this commit

Goal: real waveform files, references, manifest, independent validator.

Commands: `uv run pytest tests/test_export.py`; generation through `generate_all(configs/m8199b_profiles.yaml, output/keysight_m8199b)`; `validate_profile` per profile.

Results (seed 42):
- Tests: 23 passed. Generation 11.5 s. Validation: 115 of 115 checks passed for each profile.
- Adaptive selection: P0=0.375, lambda=-0.13733, objective 1.0541 bit/use, on simulated AWGN training at PSNR 13.854 dB. Outer-heavy, as theory predicts. Label: simulation-optimized.
- Profile A net payload rates: Uniform 15.50, PS70 14.47, PS80 13.22, Adaptive 13.93, Outer70 14.47 Gbit/s. Shaping lowers net rate at equal baud.
- Common scale 0.333333333; all peaks 1.0. RMS: Uniform 0.7499, PS70 0.6203, PS80 0.5439, Adaptive 0.8819, Outer70 0.8564.
- Uniform mean 2.8e-4; CCDM waveforms mean below 1e-18.
- Sizes: Profile A CSV about 11.5 MB each; output/ total 76 MB; no file over GitHub's 100 MB limit.

Failures: FAILURES X-003, X-004.

Next: Phases 5-8, receiver, channel, statistics, ingest.

## 2026-10-30 | Phases 5-8 | commit: this commit

Goal: receiver, link, statistics, ingest, mock receiver, protocols, CLI, docs.

Commands: `uv run pytest tests/test_core.py tests/test_rx_channel.py tests/test_export.py tests/test_ingest.py`; `uv run ruff check`; `uv run mypy`.

Results: 129 tests passed; mypy clean on 36 source files. Gates covered: analytic PAM4 SER inside the 99.9% interval; MAP beats minimum distance for shaped input; GMI within 0.03 of analytic; sync at random offset and inverted polarity; CD null at 19.2 GHz for 10 km; shot variance within 1%; thermal slope 2 dB/dB; 200 fuzzed metadata cases rejected; end-to-end through the mock receiver.

Note: the plan's GMI gate was 0.01 bit. The test uses 0.03 with six frames; this is looser than planned and is recorded here so it is not mistaken for the plan's gate.

Failures: X-005 to X-009.

Next: full demo run, report, slides, independent review.

## 2026-10-30 | Correction to the Phases 5-8 entry

The GMI test was tightened back to the planned 0.01 bit and passes for Uniform, PS70 and Outer70.

## 2026-10-30 | Phase 9-10 v1.0 review and final run | commit: this commit

Reviews:
- Grok, read-only: returned no findings (stopped after its opening sentence, exit 0). Not counted as a review.
- Sonnet Loki: PASS, no blockers, 11 minor findings. It recomputed the 14 dB rates by scipy quad, and one report row from results.
- Fable was used once, for the pre-build design review. By user instruction it is not used as a worker afterwards. The plan's Fable review of Phase 10 was replaced.

Changes from review: Uniform priors no longer come from the payload; paired comparisons need 5 runs; `target_is_requested` check with independent targets; RRC reconstruction is actually tested; preamble correlation is reported; the "held-out" and interval wording in the report is corrected; slide picture bounds; the 4 dB statement.

Final simulated results, seed 42, config e39084adac9d, version 1.0.0, runtime 288 s, 8 runs:
- Profile A near -22.01 dBm, R_BMD versus Uniform: PS70 -0.150 [-0.151,-0.147], PS80 -0.267 [-0.270,-0.264], Adaptive +0.036 [0.033,0.039], Outer70 +0.041 [0.037,0.045].
- Profile B near -19.01 dBm: PS70 -0.141, PS80 -0.236, Adaptive +0.093 [0.090,0.097], Outer70 +0.081 [0.078,0.084].
- Point adaptation versus Outer70: +0.018 at 26 dB; unresolved +0.001 [-0.001,0.003] at 25 dB; +0.107 at 21 dB, where it selects uniform.
- Validation: 119 of 119 per profile. Waveform CSVs byte-identical before and after review changes.

## 2026-10-30 | Official guides obtained

M8100 Programming Guide (146 pages) and UXR Programmer's Guide (2156 pages) were fetched with a plain curl client, no altered User-Agent, from Keysight's public www.keysight.com/nz/ asset URLs, which served the PDFs directly. Text was extracted locally. The PDFs are not committed.

Result: the exported waveform CSV format is confirmed against pp129-133: mandatory first row DataOut1, normalized floats within -1 to +1, `:TRAC:IMP` syntax, segment id 1. Not found in that guide: 512-sample granularity, 1,048,576 maximum, M8199B AC coupling. Playback remains unverified. The rows in VERIFICATION.md and HARDWARE_COMPATIBILITY.md are updated on branch v1.2-uxr.

## 2026-10-30 | v1.1 G.652 gate

Dev: Sonnet. Loki: Opus. First review FAIL at 8a3b425 (two provenance and override defects; physics and standard numbers passed). Second review PASS at cd443f9 with 7 low findings, recorded in CHANGELOG.

Results: v1.0 fiber sweep reproduced 45 of 45 points on the default path. Before/after at Profile A, Uniform, 40 km, seed 42: v1.0 SER 0.5901, R_BMD 0.196, -27.01 dBm; G.652.D representative SER 0.6739, R_BMD 0.042, -30.01 dBm. The difference comes from attenuation, 0.275 versus 0.2 dB/km, over 40 km. The beta3 term changes at most 8 symbol errors. Waveform CSV tree identical to v1.0.0. All simulated; nothing here is experimentally validated.

## 2026-10-31 | v1.2 UXR gate

Dev: Sonnet. Loki: Opus. Reviews: 44ce954 FAIL; 26453ab FAIL; e1d7a9b FAIL; 5e6db48 FAIL; 1c821ca PASS; ca83b24 PASS; 870d3cd PASS.

What each review found mattered: silent loss of frames; one acquisition counted as five runs; hostile HDF5 metadata; guards blocking every real run; a confident verdict from wrong references; and no matched filter in the capture chain (about 2 dB SNR loss). The last was found by asking why mock and simulated SER differed.

Results (synthetic only): 368 tests pass. Waveform CSV tree identical to main. Mock versus simulated SER at 18.4 dB, Uniform: 1.5e-3 before the filter, 9.5e-5 after, simulated 2.4e-5; the remaining gap is not fully explained.

Orchestrator errors: the UXR brief omitted the required receiver-analysis report, found only at the final check. The merge state in rework 1's brief was wrong and was corrected by message.

Crew deviations: the final text-only fixes at 2b8eaad were made by the orchestrator, checked by machine gates, not by a Loki, to save tokens. Grok could not be used: auto-approve launch was denied by the harness, and a read-only run returned no findings. A Dev spawn repeated its report on a timer and was stopped.

Accepted limitation: sample loss below about 1 symbol, synchronous with the frame period on one waveform in every run, may not be detected.

## 2026-10-31 | M8199B data sheet read

Obtained from a direct Keysight link supplied by the user. Page 9 confirms 512-sample granularity, 1024 kSa per channel, AC coupling, 50 ohm nominal, 8-bit DAC, 200 to 256 GSa/s. Page 12 Figure 8 is a typical ENOB curve; its axis spans 4 to 6.5 bits, curve values were not extracted from text. "1024 kSa" does not say whether k is 1000 or 1024; exported files are safe under both.

## 2026-10-31 | v1.3-mpam C1 (Gate 0)

Dev: Sonnet. Baseline a2eb969: 368 tests passed (counted from the progress dots, the summary line is hidden by addopts), ruff check and format clean, mypy clean, Python 3.11.15, numpy 2.4.6.

Added `tests/test_pam4_anchor.py` (slow marker, runs in default pytest, writes to a temp dir): regenerates both M8199B profiles from the untouched config at full training size. All checksummed files, manifests and metadata (without `generator`) matched the committed output; adaptive_selection.json matched at rel 1e-12. 9 tests, about 5.4 s. Full run after C1: 377 passed in 232.75 s.

Docs: ROADMAP_STATUS, FEATURE_GAP_MATRIX, DEPENDENCY_EXCEPTIONS; CLEAN_ROOM_DECLARATION rewritten to separate the original process from later comparison-discussion exposure and to state what cannot be claimed. License audit: 34 packages, 0 flagged, SBOM unchanged. No code under `src/` changed. Not yet reviewed by Loki.

## 2026-10-31 | v1.3-mpam C1 review fixes

Loki FAILed C1 (docs only). Fixed in a second commit: gap matrix now walks every roadmap section D bullet; clean-room section 2 states the rule and the evidence limit instead of "not used"; anchor also re-hashes the committed files and compares regenerated checksums.sha256 (metadata lines excluded), metadata floats at rel 1e-12; lockfile comparison recorded (installed set equals the uv.lock Python < 3.12 branch; colorama is win32-only); citations corrected. Baseline timed: 368 passed in 212.10 s. After fixes: 381 passed in 214.32 s; ruff, format, mypy clean.


## 2026-10-31 | v1.3-mpam C2 (PAM-M rates)

Dev: Sonnet. Base de1fc73. First commit carries the C1 minors (anchor rehashes committed metadata, compares checksum entry names without the metadata filter, checks regenerated metadata digests; four matrix rows). Anchor now 15 tests; 383 passed.

`rates.py` is generic in M: `noise_sigma_from_psnr_db(psnr, order)`, `gaussian_rates`/`achievable_rates`/`psnr_for_rate` with `order` and `nodes`, `bmd_raw` (unclipped) beside the clipped `bmd`, `average_snr`. PAM4 uses the original kernel line for line; the other orders use log-sum-exp. PAM4 values equal the pre-change ones exactly (pinned in tests, anchor green).

Findings: (1) GH120 versus GH200 is not below 1e-9: 120 nodes are 1.9e-8 (M=16), 3.7e-8 (M=8), 2.6e-8 (M=2) and 4.1e-8 (M=4) from a 280-node value over PSNR 8-30 dB; 200 nodes 1.5e-9; 240 nodes 4.2e-10 against 320 and 6.7e-10 against an independent trapezoid. GH120 versus a 2^15-point trapezoid at M=16 is below 1.2e-8, well inside 1e-6. Not weakened: default nodes are 240 for M != 4, 120 for M=4. numpy hermgauss overflows beyond about 400 nodes (now an error). (2) The PSNR bracket [-10, 45] dB covers M=16 uniform targets 0.5 to 3.99 bits for SMD and BMD; widening is applied only for M != 4, and only for targets within about 1e-8 of H. (3) bmd_raw is negative for nonuniform PMFs at 0 dB: M=8 -0.039, M=16 -0.083 (exp(-0.2 x^2)), M=4 [0.2,0.3,0.1,0.4] negative. (4) PAM4 on PAM16 indices {0,5,10,15}: SMD equal to 1e-9, BMD lower (Gray labels differ). (5) M=8 inner-heavy loses to uniform at fixed peak: at 22 dB SMD 1.955 uniform versus 1.774 at lambda 0.1; 2 bits needs 23.5 dB versus 22.3 dB.

86 new tests in `tests/test_mpam_rates.py`; full run 469 passed in 223.75 s; ruff, format, mypy clean. Not yet reviewed by Loki.

## 2026-10-31 | v1.3-mpam C2 review fixes

Loki FAILed C2 on tests and wording; rate values were right. Fixed in a new commit: (1) independent integrator with hand-written Gray tables at M=8 and 16, plus a test that the package labels equal those tables; (2) unequal per-level sigma tested against that integrator at M=4/8/16 and direct versus log kernel at M=4; (3) bmd_raw is the GMI at s=1 of q = prod P(b_k|y)/P_X(x), not of prod P(b_k|y) (M=8, exp(-0.1x^2), 20 dB: 1.43647 versus 1.40726), docstring and provenance corrected and both identities tested; (4) PAM4 fallback test with p=[1e-320, .5, .25, .25-1e-320]; (5) non-finite rates raise ValueError instead of bmd=0 from max(0, nan); PAM4 finite results unchanged; (6) numbers corrected.

Unequal-sigma disagreement (Loki saw 3e-8 to 1.5e-7): it is quadrature error, not a kernel bug. Gauss-Hermite error grows with the sigma spread: ratio 0.7-1.4 gives 1e-7 to 2e-7 at 120 nodes, 2e-9 at 240, 5e-10 at 320; ratio 0.5-2 gives 2e-6 to 1.5e-5, 4e-8 to 2e-7, 7e-9 to 2e-8. Likely because nodes are centred per level with that level's sigma while the integrand contains other widths. The 1e-9 convergence claim holds for equal sigma only. Tolerance for unequal sigma tests: 1e-6 at default nodes, 1e-8 at 320 nodes. Comparisons below 1e-7 across orders must fix nodes on both sides.
