# E2a Dev handoff (Stage 3A, scoring entry point, model, frozen criterion; Dev), fix round after E2a_qa.md
Review FAIL at df7fdc1. R10 (d520ff7) and R11 (007b8b2) were reviewed, failed or superseded and never scored; both criterion files stay as records. Freeze now: TERIPHIC_CRITERION_R12.yaml, plan Revision 12. Local only. SHAs and counts in the report.
Rule kept: no 2 km or 10 km sample, header or hash read by any code run here; score_holdout ran on fixtures only. B2B windows only (fit, spread, evaluation, five study windows).
## Governance (findings 1, 2, 5, 6, 7, 8, 10, 11)
- expected_freeze_commit is a required argument of score_holdout and the script; compared with the commit found and the first-parent freeze before any read. A path move resets bind_to_freeze: only the external pin catches it (known limits restated, promise verbatim).
- Role register bound to the freeze; roles fixed by name in code. Every refusal (pin, bind, ids, drift) comes before the holdout is hashed or opened; tests record the order.
- Verdicts outside allowed_verdicts become EXPLORATORY; the script has --sequence-check and --state; VALIDATED is never returned. Code identity is the 12-file import closure and the running modules must be the repo's.
## Science (findings 3, 4): redesigned, power study in power_study.yaml
- Gain-invariant map (amplitude reported, not tested); 123 scenarios (D grid, noise factor, noise through the fibre); 2 km carry rule with a 0.25 margin, else all survivors; 10 km FAIL is INCONCLUSIVE (grid), pass is PARTIAL.
- 2 km cannot discriminate dispersion (all D carried); 10 km resolves D only to about 0.075 above 3, so about 40 percent of true D above 3 would end with no survivor. Limits and multiplier were not changed.
## Reviewer: check
- The 10 km grid sensitivity is a real limit, handled by capping, not by a wider limit. Is INCONCLUSIVE for a 10 km FAIL too conservative?
- Fixture truth uses the surrogate's own pulse generator (fibre, gain, noise, low-pass are independent code).
- The shared-sequence check is not implemented: not-shared is the operator's declaration.
## Open for the owner
- Record the R12 freeze commit id outside the repository before E2b; the single 10 km run stays unspent until then. Intermediate commits are not all green.
## Not done: E2b. BER and SER stay REFERENCE_SEQUENCE_MISSING.
