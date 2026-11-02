# E2a Dev handoff (Stage 3A, scoring entry point, model, frozen criterion; Dev)
base 43402f7. Commits: c0b7886, 1b496d2, d520ff7 (first freeze, SUPERSEDED), 5b504b7, 9976d3b, 007b8b2 (freeze). Local only. Tip and counts in the report.
Rule kept: no 2 km or 10 km sample, header or hash read by any code run here. B2B read for fit only.
## What exists
- e2_score.score_holdout: only holdout reader in src. Order: registered name, require_frozen_criterion, bind_to_freeze, committed docs + code identity, MD5 and SHA-256 at read time, then header and window. Tests scan src for the readers and the call order.
- e2_metrics (M1 to M4 of R2.2), e2_model (zero-phase B2B surrogate, small-signal cos dispersion, seeded), scripts/freeze_teriphic_e2.py, score_teriphic_e2.py, mutate_e2.py.
- docs/benchmarks/teriphic_e2: model fitted on B2B, 9 scenarios, pre-registered predictions (results null). Plan Revision 10 (definition) and 11 (binding).
## Security finding (coordinator): verified REAL, fixed
- After the first freeze, model, registration, identity table and code could be replaced together and still pass. selected_scenario had no rule.
- Fix: bind_to_freeze compares model, scenarios, registration, eval script, code files with their bytes at the freeze commit; selected_scenario must be added by exactly one later commit, never changed.
- d520ff7 cannot be amended, so CRITERION_PATH is now TERIPHIC_CRITERION_R11.yaml (holdout.py, one line, plan R11.3). The old file stays as a record and is ignored by the guard. Same limits.
## Unknown, declared (never tuned): wavelength, fibre type, dispersion, loss, launch power, chirp (MODEL GAP), modulation depth, response phase, noise origin. Scenarios are ASSUMED_G652D.
## Reviewer: check
- 2 km: no matched-amplitude dispersion scenario is separable from the B2B copy (psi 0.50 to 0.60); 10 km is (2.93, 4.14). Results can read PASS, NOT DISCRIMINATING.
- Surrogate misfit sets the limits (basis = max(misfit, spread), x2); is that too lenient? M4 misfit 0.61 dB vs spread 0.08 dB.
- Fixture truth uses the surrogate's own pulse generator (fibre, loss, noise are independent code). Independence is partial.
- Prereg reproduction tolerance 1e-6 relative; platform drift is the only guard against library change.
- Intermediate commits are not all green (plan pin tests move with the plan commit).
## Not done: E2b (2 km stage, selected_scenario.yaml, shared-sequence check, 10 km). BER and SER stay REFERENCE_SEQUENCE_MISSING.
