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

## Round: first_parent_dropped mutant (post history rewrite; freeze 04360ec6a44bb6aaa2222cc605ab3979718be50a)
- The mutant (drop `--first-parent` in `first_parent_freeze`) survived because the existing tests built history where the merge was TREESAME to the first parent, so git's default simplification pruned the side commit anyway and both log forms agreed.
- Added `test_first_parent_resolution_takes_the_merge_not_the_merged_in_side_commit` in tests/test_benchmark_e2.py (real git in tmp_path): the criterion reaches main only by merging a side branch. Without `--first-parent` the log names the side commit; `first_parent_freeze` must name the merge; `require_freeze_pin` refuses a pin naming the side commit.
- Tests only. No freeze-bound file and no source file changed. Results are in the Dev report.

## Round: R13 after the re-review FAIL (E2a_qa2.md); design by Fable, implemented by Dev (Opus)
Basis: `questions/E2a_design_fable.md` (committed by name), the coordinator's decisions on item 16 (scientific content unchanged; only `code_identity` and the resulting `model_sha256` lines regenerated) and item 14 (no release, no push, no CHECKPOINT edit; push events plus the external pin). R12 (freeze 04360ec) was reviewed, failed and never scored. Freeze now: ce0ee732af1111c67d94943ad985469dea8c8389 (`TERIPHIC_CRITERION_R13.yaml`, SHA-256 ba78a6a3...), plan Revision 13 (SHA-256 73884278...). Local only, not pushed. SHAs and counts are in the Dev report.
Rule kept: no 2 km or 10 km sample, header or hash was read, plotted or linked; `score_holdout` ran on fixtures only. B2B only (`freeze_teriphic_e2.py prepare` to regenerate the code identity). No `two_km_result.json` or `selected_scenario.yaml` exists.
## Findings and fixes
- 1 MAJOR, 10 km not tied to 2 km: LOCKED_TEST needs `--stage not-failed` (FAILED, NOT_DONE, None refused as `StageRefused`, exit 3, before any hash or open); `read_two_km_record` binds the carried set to the committed `two_km_result.json` (the verbatim stdout of the 2 km run) through `two_km_result_sha256` in the selection, with every check of plan R13.2 item 6; a record that says FAIL or BLOCKED is refused whatever is declared; `two_km_result` is a required input; report version 2 with `declarations`, `two_km_record`, `window`, `summary`.
- 2 MINOR, shared sequence: SHARED gives {EXPLORATORY, BLOCKED} at both lengths; the script offers `not-run|shared` only.
- 3 MINOR, `judged = list(table)`: test added; the mutant is in `mutate_e2.py` and is killed. `mutate_e2.py -j 7` end to end after the last code edit: 191 applied, 181 killed, 0 survived, 10 harmless, 0 broken, 0 invalid.
- 4 to 6: wording corrected (20 to 60 percent bracket, small-signal caveat, claim `NO_SCENARIO_FITS`), timestamp procedure in R13.5.
## R12 limits (design item 13)
The R12 limit values differ from R11 (M1 0.02659 to 0.01814, M2 0.03456 to 0.06000, M3 0.08985 to 0.13066, M4 1.2292 to 1.2179) because the metric map became the gain-invariant map (R12.2) and misfit and spread were recomputed under it; the formula basis x 2.0 and the multiplier are unchanged. 'Limits were not changed' meant only: not moved after seeing the power study. R13 limits equal R12 to 1e-9 (test).
## Reviewer: check
- The record is bound by bytes and consistency, not provenance: an edited psi table with a re-tied hash passes (known limits, tampering under the promise).
- The 2 km run can be executed twice; procedural only.
- `bind_to_freeze` at the record's head commit uses committed blobs; a selection commit that is a merge is refused (diff-tree shows no `A`), conservatively.
- A missing record is refused by the guard's input check (exit 2), not by the stage contract (exit 3).
## Open for the coordinator
- Record the R13 freeze commit outside the repository, push, capture the PushEvent (R13.5); correct the CHECKPOINT wording; before E2b record any wavelength or modulator statement as a SOURCE.
## Not done: E2b. BER and SER stay REFERENCE_SEQUENCE_MISSING.
