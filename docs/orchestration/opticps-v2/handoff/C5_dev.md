# C5 Dev handoff (Dev, Sonnet 5.5 session)
base: aed1a5c. Commits: C5a (19a96a4, C4 leftovers) then C5. Branch v1.3-mpam, local only. Tip SHA: see the final report.
Gate: 768 passed (698 before; C5a +9, C5 +61). Anchor green, no anchor test edited. ruff check, ruff format --check, mypy clean. No dependency change.

## What changed
- C5a: FixedOMA true INACTIVE reason (outer pair unused), swing 0 in grid, refined maximum (4.6154 V at M=16 FEASIBLE, +1e-6 INFEASIBLE); mutants killed (range tol, lower-edge tol, _assert_unique, floor_active_selected_pairs); selected_on says "split label declared"; endpoints named optimised_from:<start>; _argmax_menu honours in_bounds; note: post hoc g=1.8, BMD start disagreement, rate(P) vs counts/n 2.5e-4, PAM16 45 dB 0.101 single vs 0.0615 multistart.
- C5: ModulationSpec + order=4 defaults (pam.py); Frame.order last, head 512+{512,512,1536,2560}, direct uniform log2 M bits (frame.py); configs/mpam_profiles.yaml v2 + loader mpam_config.py; generate_mpam_all (M=2,8,16; schema v2, stream keys, evidence); validate_export default-deny, both schemas.
- Pinned baseline: fixed_menu raises BaselineOverrideError for other deficits (exploratory=True gives a never-reportable menu); best_fixed(menu=...) sets reportable=False for any non-pinned menu.

## Frame lengths (symbols x sps = samples), all FEASIBLE
A 8 GBd: 32768 x 28 = 917504 (M=2,4,8,16; head 1024,1024,2048,3072). A 56 GBd: 65536 x 4 = 262144.
B 112 Gb/s: M=2 131072x2; M=4 65536x4; M=8 43008x6=258048; M=16 32768x8=262144 (all 262144 except M=8).
## Findings
- Training at M=16 (160/level): sigma-hat relative sd 5.64% (theory 5.61%) is 1 sigma; 95% half width 11.1%. Plan wording corrected in ROADMAP_STATUS.
- Equal-rate: PS80 class INFEASIBLE only at M=4 (+17.2%). M=8 H272 +11.6/+11.5%, M=16 H372 +9.3%: FEASIBLE (reported, never applied).
- BMD starts disagree on the sweep at 4 points (4.6e-2 M=8 14 dB; M=16 14/20/22 dB 1.7e-3/1.7e-2/4.9e-2); SMD never (<=1.3e-12).
## Decisions to check (ROADMAP_STATUS deviations 8-10)
Protocol B symbol counts and design rates (1.5 b at M=8, 2.0 at M=16) are my choices; PAM2 exports Uniform only; PAM4 stays on generate_all.
## Not done (by scope)
CLI, receiver (C6), demo/compare/uxr/report consumers (C7). A fresh M=16 generation takes about 40 s.
Files: src/opticps/{modulation/pam.py,transmitter/{frame,export,mpam_config}.py,measurement/validate_export.py,optimization/{adaptive,constraints}.py}, configs/mpam_profiles.yaml, tests/test_mpam_{frame_rx,config}.py.

## Fix round (after QA FAIL, 2 MAJOR)
Gate: 853 passed in 547.11s (768 before; +24 test_mpam_config, +61 test_mpam_frame_rx), anchor green, no golden/anchor test edited. ruff check, ruff format --check, mypy clean. 45 M=2/8/16 waveforms regenerated in a temp folder (not committed): 9 packages, 0 failed (53 / 365 / 363 checks at M = 2 / 8 / 16). Committed PAM4 packages: 215 checks each, 0 failed.
1 reportable: `BestFixed.reportable` defaults False; `export.require_reportable_baseline` refuses (BaselineOverrideError, nothing written) a flag False, wrong order, non-pinned member or other PMF; manifest column `reportable`; validator fails a required row that is not true and checks BestFixed `member=`.
2 evidence: YAML key removed and refused; generator hard-codes `simulated`; validator `evidence_matches_source` (row, metadata, source string; v1 too).
3 docs: ROADMAP_STATUS dev. 10, LOG, ALGORITHM_PROVENANCE. Same-order: only PS80 at M=4 INFEASIBLE (+17.23 %). Common target 110.25 Gb/s: H272 258.4/258.1, H372 265.8 GSa/s INFEASIBLE (table written by code; also `rate_equalisation_common_target` in metadata, Protocol B only). Net uniform 111.125, 110.25, 106.67, 101.5 Gb/s.
4 validator pins the menu itself (MB bisection, agrees with fixed_menu to 1e-9); names, BestFixed member, Adaptive symmetry checked.
5 default-deny: header-only, zero rows, missing/duplicate rows (`manifest_rows_complete`), empty/incomplete/malformed checksums (`checksum_list_complete`), missing files (no crash); CLI exit 1 on no folders or zero checks. `manifest_schema(columns, [])` is now None (test changed).
6 recomputed vs manifest: realised, entropy, payload bits, matcher rate/loss (+ block composition), nominal/net rate, protocol, constraint protocol, peak/rms, full scale; preamble m-sequence order; scale tolerance = half a DAC code = 0.5/127 of full scale (3.94e-3), below which the 8-bit code is unchanged.
7 loader strict at every level (exact keys, enums for constraint_protocol and metric, numeric types); `orders`/`protocols` validated before mkdir.
8 mutants: 41 applied to the new code on a scratch copy, each re-applied and failing a test. The review's ten: column order, realised=target, loss 0, nominal 2xbaud, _is_uniform False, errors=0, head True, startswith, fit-512, quantiser. The two "near equivalent" were not equivalent: fit-512 is reachable with a block length that is not a multiple of 512 (1124 symbols, block 100: 2248 samples); the quantisers differ at ties (uniform PAM8 at n=10: (2,1,1,1,1,1,1,2) against (2,2,1,1,1,1,1,1)); tests added for both. Three mutants survived the first pass (metadata-only evidence, orders check, CLI zero checks): tests added, rerun killed.
9 FEATURE_GAP_MATRIX export row repaired.
11 Adaptive and BestFixed report their own `rate_equalisation` (and common target); `rate_equalisation` direct-uniform test is now exact (1e-12), consistent with `_is_uniform`.
