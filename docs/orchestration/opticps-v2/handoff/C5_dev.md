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
