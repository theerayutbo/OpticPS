# E2c power study (Dev): CLOSE_PARTIAL at S2, stopped at the fit; a design flaw is reported, not patched

## What ran (branch v1.3-mpam, from b48dc1a)
- 99ce4f5 design committed; 70fc599 STUDY_PLAN.md + NOTICE.md (rule, stops, I1-I14, the D12 note) BEFORE any step;
  44b1b02 amendment A1 (Nelder-Mead restarts, optimiser only; found on fixtures before any study step); f0f079d code;
  25d4db3 step0; then law_model.yaml; b142b9e power_study_e2c.yaml. Plan SHA-256 at decide: 570ce1a6...
- `python scripts/power_study_e2c.py step0` (27 s), `fit --workers 4` (40 min), `predict` (refused: exit 3, S2),
  `decide`. `power` was not run. Data: B2B via teriphic.open_b2b, 2 km via e2c_calibration.open_two_km only.
- Access times (stat metadata only). Before: 10 km 2026-10-31T16:30:05, 2 km 2026-11-11T18:08:49, B2B 17:51:57.
  After: 10 km 2026-10-31T16:30:05 (unchanged), 2 km 19:31:35, B2B 19:31:33. The 10 km file was not read,
  hashed, opened or linked.

## Results
- Step 0 viable: 2 km gap change [-0.0244, -0.0054, +0.0298] against 3 B2B spreads 0.0087; top gap widens (D3);
  no clip; code step "not observable" (B2B grid 1.732e-6 observable, 2 km off-grid 0.107: recorded, no stop by I10).
- Fit (objective; law): poly_b0 0.1911 (a 0.0038); poly_a0 0.1908 (b -0.0013); poly 0.1930 (a 0.0016, b 0.0020);
  tanh 0.1548 (k 0.099, o 0.404). C-2KM fitted (amplitude 0.831). phi (optical share) 0.067.
- R6 (R13 limits): poly B2B psi 0.517, 2 km psi 1.489 (M1 0.0270 vs 0.0181): FAILS. tanh: 0.791 and 0.530.
- Decision rule applied mechanically: decision CLOSE_PARTIAL, stop S2, failed line R6. S3, R1, R2 not reached.

## Power table
Not computed: S2 stops the study before the predictions (D19). No power or false-pass rate exists for any family.

## Design flaw (stop and report, not patched)
The S2 stop is most likely an optimiser artefact, not a refutation of H2: (1) the full polynomial's objective
is above both of its nested profiles, impossible at an optimum; (2) it ended near its start (a, b ~ 0.002), i.e.
the B2B-only surrogate; (3) the tanh profile of the same hypothesis reaches 0.155 and passes R6 on both windows,
with an even term about b = -0.038. Plan I6 made the polynomial the model of record and tanh report-only, so the
rule cannot use that. Not done: refit, other starts, switching the model of record, predictions. Any re-run needs
a new pre-registration approved by the owner (Aria), and it would be a fit chosen after seeing this result.

## Deviations
- Amendment A1 (restarts) before Step 0, from fixtures only. Verdict string WORTH_SPENDING_10KM (design: WORTH_10KM).
- Interpretations fixed before step0 in plan I1-I14 (noise bounds, C-2KM = the R13 fit procedure with its own
  2 km spectrum, controls not doubled for tanh, T5/T6 models, R3 pooled 2 of 20). D12 spread term: approved by
  Aria for this study only; a structural change needing owner approval before any R14 freeze.

## D15 declarations (in every E2c output)
(a) 2 km is calibration data from now on, never again a holdout; its VALIDATION role stays until R14 rebinds it.
(b) R13's 2 km FAIL stands; H1 is refuted at 2 km. (c) H2 is post hoc; tested at most once on 10 km under R14.
(d) VALIDATED is never returned; a 10 km pass would be PARTIAL. (e) BER/SER REFERENCE_SEQUENCE_MISSING.
(f) Limits, scenarios and rule use B2B and 2 km only; the 10 km file is not touched.
Closing text: "H1 refuted at 2 km (R13, FAILED); H2 formed post hoc; the power study could not make a 10 km test
that discriminates; claim PARTIAL; 10 km unspent."

## Tests and gates
tests/test_benchmark_e2c.py 26 passed; mutate_e2c.py 6 of 6 killed. Clone gates at 1abfb35 (B2B and 2 km linked only):
ruff, format, mypy (66 files), license audit (34, 0 flagged), anchor 15 passed; pytest 2192 passed, 5 skipped,
2 failed: (1) the E2 source scan needed e2c_calibration.py on its reader allowlist (fixed in the next commit,
re-run passed); (2) test_benchmark_e2_freeze::test_the_10km_stage_is_not_frozen_yet... already fails at b48dc1a
(stale since E2b committed two_km_result.json); not touched, needs an owner decision.
