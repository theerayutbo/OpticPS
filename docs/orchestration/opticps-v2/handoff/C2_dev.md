# C2 Dev handoff (PAM-M rates)

Base de1fc73, branch v1.3-mpam. Two local commits (C1 minors, then C2). Nothing pushed, merged, tagged. Roadmap files and CHECKPOINT.md not committed.

## Commit 1 (C1 minors)
- tests/test_pam4_anchor.py: committed rehash includes the 5 metadata files; checksum names compared with no metadata filter (21 entries); regenerated metadata digests checked against regenerated files. 15 tests.
- FEATURE_GAP_MATRIX: re-export (limit disclosed, uxr_ingest.py:147-149), five paired runs PARTIAL (compare.py:52,211), candidates (90 stored), zero-error citation :299.

## Commit 2 (C2)
- src/opticps/optimization/rates.py: generic M (2,4,8,16), `order`/`nodes` args, `Rates` gains `bmd_raw`, `order`, `nodes` (defaults keep old construction valid), `average_snr`, `default_nodes`.
- PAM4 keeps the legacy kernel verbatim (fallback to log-domain only if non-finite); other orders use log-sum-exp.
- tests/test_mpam_rates.py: 86 tests. Spec items all covered; PAM4 pins taken at de1fc73, exact equality.
- Docs: ALGORITHM_PROVENANCE entry, ROADMAP_STATUS (C2 table, checklist), LOG.md entry.

## Counts
- Before: 383 passed (after commit 1). After: 469 passed in 223.75 s, anchor green. ruff check, format, mypy clean.

## Key numbers
- GH120 vs GH200 < 1e-9 FAILS: 120 nodes are 1.9e-8 (M=16), 3.7e-8 (M=8), 2.6e-8 (M=2), 4.1e-8 (M=4) from 280 nodes. 200: 1.5e-9. 240 vs 320: 1.6e-10. Not weakened: defaults are 240 for M!=4, 120 for M=4 (unchanged, byte-identical).
- GH120 vs trapezoid (2^15, +-12 sigma) at M=16, 8-30 dB: < 1.2e-8 (limit 1e-6).
- numpy hermgauss overflows past about 400 nodes; now raises ValueError.
- Bracket [-10,45] suffices for M=16 targets 0.5-3.99; widened only for M!=4 near H (M=4 is exactly H at 45 dB).
- bmd_raw < 0: M=8 -0.039, M=16 -0.083 at 0 dB (exp(-0.2x^2)).
- PAM4 on PAM16 {0,5,10,15}: SMD equal 1e-9; BMD lower by >5e-5 (labels differ).

## Notes for Loki
- Embedding tests fix nodes=240 on both sides, since M=4 default is 120 and rules differ by ~4e-8.
- Mutation check: sigma factor changed to 3 for all M made 41 tests fail.
- Not done by design: optimiser (C4), consumers still call legacy PAM4 signatures.

## Review fix commit (after Loki FAIL)
- Tests 110 (was 86); full run 493 passed in 238.89 s. Hand-written Gray tables at M=8,16; per-level sigma vs independent integrator; GMI identity (q = prod P(b_k|y)/P_X) and its non-equality for q = prod P(b_k|y); PAM4 fallback test; non-finite rate raises ValueError.
- Unequal-sigma disagreement is Gauss-Hermite error that grows with sigma spread (ratio 0.7-1.4: 1e-7..2e-7 at 120, 2e-9 at 240; ratio 0.5-2: up to 1.5e-5 at 120). Likely cause: nodes centred per level with its own sigma. Docs say the 1e-9 claim is for equal sigma.
- Wording and numbers fixed in rates.py docstring, ALGORITHM_PROVENANCE, LOG, ROADMAP_STATUS.

## Integrator rework (owner decision after two failed reviews), base c51b331
Owner: new integrator plus guard. Nothing pushed, merged or tagged; roadmap files and CHECKPOINT.md not committed; shaping, distribution_matching, output/, results/, configs/m8199b_profiles.yaml untouched.

- rates.py: common-y composite Gauss-Legendre (`_conditional_entropies_common_grid`): edges at mu_i + t sd_i, t = -12..12, every live level, 10 nodes per panel, log-sum-exp, joint-density mass check 1e-9 (ValueError). `gaussian_rates(..., quadrature="auto"|"gauss_hermite"|"common_grid")`, also on `achievable_rates`, `psnr_for_rate`. `Rates.sigma_spread`, `Rates.quadrature` (defaults keep old construction valid). `nodes` with the common grid is rejected (ValueError); the recorded `nodes` is then the y-point count.
- Routing: auto = common grid for M != 4 when max/min > 1 + 1e-12; equal-sigma M != 4 stays GH (bit-identical, tested); M = 4 default always legacy kernel (byte identical, tested against the legacy kernel directly). Forced common grid works at M = 4.
- Warning: GH path with spread > 3.0 emits UserWarning (stacklevel at the caller) naming the measured error from a table. Threshold from measurement: M = 4, 120 nodes, 0-45 dB, 26 patterns: 4.9e-5 at 3.0, 9.2e-5 at 3.3, 1.4e-4 at 3.4 (first above 1e-4); 8-30 dB / 6 patterns crossing is between 3.6 (7.7e-5) and 4 (2.0e-4). 3.0 sits below the crossing. Committed path: spread 1.0050 in all 90 adaptive calls, anchor 15 passed with `-W error::UserWarning`.
- Panel order: self-convergence vs 32 nodes on half-sd panels, worst over M = 2..16, 8-30 dB, six patterns, spreads 2..400: 6 nodes 7.3e-10, 8 5.0e-12, 10 1.0e-13 (chosen), 12 4.0e-15. Means-only panels 3e-3 to 4e-2.
- Accuracy vs `scipy.integrate.quad_vec` (own posteriors, hand-written Gray tables): worst 1.04e-13 over M = 4, 8, 16, spreads 2, 4, 9, 16, 64, 8-30 dB, six patterns (1080 cases). Test tolerance 1e-11.
- Timing, one call, median of 40 (i5-8259U): M = 4 1.6 ms, M = 8 3.6 ms, M = 16 10 ms (990 / 1990 / 3990 y points). GH-240 at M = 16: 15 ms.
- Tests: tests/test_mpam_rates.py 139 (was 110). New: common grid vs adaptive reference (3 orders x 5 spreads), zero-mass levels, mass guard negative test, equal-sigma grid vs GH-320, auto routing and recorded fields, warning above/below threshold (incl. no warning at 2.99 and 1.005, none for common grid, attribution to caller), threshold crossing vs adaptive reference, per-level-sigma default tolerances (M != 4: 1e-11, was 1e-6; M = 4: 2e-8), GMI test with explicitly summed denominators for both metrics and 1.43647 / 1.40726 pinned (5e-6). Mutation checks: SD edge step 6 -> 24 failures; routing disabled -> 12 failures; panel order 3 -> 32 failures.
- Docs: rates.py docstring, ALGORITHM_PROVENANCE (new GH-vs-common-grid table over spread 2/4/9/16/64 for M = 2, 4, 8, 16 at 120 and 240 nodes, PSNR grid, patterns, worst case), LOG entry, ROADMAP_STATUS row. "6.7e-10" corrected: it was a Gauss-Legendre reference at M = 8, 34 dB; measured figure is 3.9e-10 vs independent integrators over 8-30 dB.
- Full run: 586 passed in 264.36 s (557 before, +29 in test_mpam_rates.py); ruff check, ruff format --check, mypy clean (rerun at the final tip, see the report).
