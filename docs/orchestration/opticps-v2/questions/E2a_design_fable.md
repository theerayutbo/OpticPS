# E2a design decision (Fable, 2026-11-11) for the R13 freeze
Basis: `handoff/E2a_qa.md`, `E2a_qa2.md`, `E2a_dev.md`; plan R2.4, R2.5, R12; `FREEZE_GUARD_KNOWN_LIMITS.md`; `power_study.yaml`;
`e2_score.py`, `holdout.py`, `scripts/score_teriphic_e2.py` at 4a9222d. Freeze 04360ec. No holdout read, hashed or header-parsed: R13 is legitimate.

## A. Score E2: yes, two stages, pre-registered stop rule, no discretion between stages
1. What each outcome tells us (fixed before any read; goes into R13 as the interpretation table). 2 km FAIL: the surrogate does
   not transfer within 2x its own B2B misfit; the study excludes dispersion as the cause (D 0 to 9 all pass at 2 km), so a
   nuisance is present (receiver or export filter, SNR change beyond 2.2x, large-signal, sequence statistics); FAILED; 10 km
   refused by code and kept unspent; high value, a clean negative. 2 km PASS, NOT DISCRIMINATING (the study's outcome for every
   D): transfer holds, about 80 scenarios carried, UNIDENTIFIABLE_PARAMETER; first external evidence of transfer; unlocks 10 km.
   10 km PASS, NOT DISCRIMINATING: consistent with |D| <= about 2 ps/(nm km) (O-band near zero dispersion); INCONCLUSIVE; a
   consistency with G.652.D, no dispersion claim. 10 km PASS, DISCRIMINATING: a set of D fits where the no-fibre control does
   not; PARTIAL, INCONCLUSIVE, confounded by a mild low-pass (the cap). 10 km FAIL: no scenario fits; not separable among a grid
   miss (20 to 60 percent of D above 3), large-signal, chirp, a filter; low value, the price of spending 10 km.
2. Why not hold 10 km for a better model: a large-signal or chirp model cannot be fitted from B2B (`e2_model` docstring) nor from
   2 km (dispersion hardly acts there); its parameters are identifiable only from 10 km, which spends it anyway, so holding has
   little option value. After E2b the burned 10 km file may be used, labelled EXPLORATORY, to fit such a model. Honest trajectory.
3. The 10 km verdict is INCONCLUSIVE in every scored case by design; the information is in `outcome`, `claim` and the survivors'
   dispersions. The report gets a `summary` line (item 7); every publication states the ceiling PARTIAL.
4. Stop rule, pre-registered: 10 km is run iff the committed 2 km record's outcome is not FAIL. No other condition. R12.0 row 7
   ("until the owner decides") is superseded by this rule.

## B. The two-stage contract (R13)
5. Refusal after a 2 km FAIL. `require_frozen_criterion` (holdout.py) accepts for LOCKED_TEST `validation_stage` NOT_FAILED only;
   FAILED, NOT_DONE and None are refused before any hash or open ("the 2 km stage FAILED: nothing is carried, the 10 km file stays
   unspent, plan R12.3"). Independently, `e2_score` refuses when the committed 2 km record (item 6) has `outcome` FAIL or BLOCKED
   or `verdict` FAILED or BLOCKED, whatever is declared.
6. Binding the carried set to the recorded 2 km result. New constant `TWO_KM_RESULT_PATH = docs/benchmarks/teriphic_e2/
   two_km_result.json`: the verbatim stdout of the frozen script's 2 km run. `selected_scenario.yaml` keys become exactly
   {scenario_ids, rule, selected_at_stage, two_km_result_sha256}. `REQUIRED_INPUTS[LOCKED_TEST]` gains `two_km_result` (so the
   guard commits and hashes it). `read_two_km_record(root, frozen, scenarios, limits)` replaces `read_selected_scenarios`; refuses unless:
   a. neither file existed at the freeze; each has exactly one commit in `--full-history`; it is the SAME commit (the selection
      commit), a descendant of the freeze; both `A` in that commit (no rename); bytes unchanged since;
   b. SHA-256 of the record's committed bytes equals `two_km_result_sha256`;
   c. record `filename` is the registered 2 km name, `split` VALIDATION, `length_km` 2.0, `criterion_commit` equals `frozen.commit`
      (the pin), `hashes_verified` true, outcome and verdict as in item 5;
   d. record `head_commit` is the freeze or a descendant of it and an ancestor of the selection commit, and every `bind_to_freeze`
      path at `head_commit` equals its freeze bytes (give `bind_to_freeze` a revision parameter);
   e. `scenarios_scored` equals the scenario count, record `scenarios` keys equal all ids, record `limits` equal the frozen (1e-9);
   f. `carry_forward` equals `scenario_ids` in order; `carry_rule(record["scenarios"])` recomputed from the recorded psi table
      equals `tuple(scenario_ids)`; `rule` is `single` iff one id; every carried id has psi <= 1 there.
   The 2 km file is NOT re-read at 10 km time (one holdout per process; the read-order test stays). The record is bound by bytes
   and consistency; a psi table edited to match hand-picked ids is tampering under the R3.1 promise (restate in known limits).
   Recomputing the carry rule from the table makes the 10 km stage independent of float differences between machines.
7. JSON report, both stages: `report_version: 2`; `declarations: {validation_stage, sequence_check, state}` (strings or null) with
   `declarations_note` "operator declarations, not established by this script; the shared-sequence check is not implemented, so
   NOT_SHARED cannot be declared here"; `two_km_record: {path, sha256, commit}` at 10 km, null at 2 km; `window: {start, samples,
   sample_rate_hz}`; `summary`: one sentence from outcome, claim, the survivors' dispersions, the amplitude ratio and "the verdict
   is capped at INCONCLUSIVE by design"; a note (never a verdict rule) when the amplitude ratio is outside 0.5 to 2.
8. Shared sequence. `allowed_verdicts`: SHARED (not BURNED) returns {EXPLORATORY, BLOCKED} for VALIDATION and LOCKED_TEST, so the
   existing clamp forces EXPLORATORY at either length (R2.4 read literally). The script offers `--sequence-check {not-run, shared}`
   only; `not-shared` leaves the script (the enum member stays). Script docstring, R12.0 row 7 and the R12.3 parenthetical are
   corrected by R13 text (addendum, nothing edited).
9. Low-pass margin at 2 km: no strengthening. The limit basis is the model's own B2B misfit (M4 0.609 against a spread of 0.081),
   so a low-pass whose effect on M1 to M4 is below that misfit lies inside the model's own error and cannot be rejected on B2B
   evidence without failing B2B itself; the cap already carries this. R13 records: a Butterworth-4 at 45 GHz FAILed 2 km at
   psi 1.019 (reviewer, B2B window 12582912, not part of the study); a milder one passes. The measured boundary, not a limit change.
10. Unchanged: limits, basis, multiplier 2.0, estimators, margin 0.25, carry rule, gain-invariant map, model, scenario list,
    pre-registration, power study. Claim constant renamed `NO_GRID_SCENARIO_FITS` to `NO_SCENARIO_FITS` (the old name asserts a
    cause the study cannot separate); its note lists the causes of item 1.

## C. Wording, exact
11. The 40 percent (FAIL_CAVEATS[2]; R12.3 and R12.4 reading 4 stay, R13 corrects): "the study brackets the fraction of true D
    above 3 ps/(nm km) that no grid scenario fits between about 20 and 60 percent (a D within 0.05 of a grid point passed, one
    0.10 away failed; the boundary between was not resolved), small-signal only".
12. Small-signal, new FAIL caveat and R13 text: "every pseudo-capture of the study has the model's own small-signal cosine form; a
    large-signal (square-law, ER about 6 dB) pseudo-capture of real B2B FAILed at 10 km even on-grid at D=4.5 (psi 1.26; reviewer
    reproduction, window 12582912, not part of the pre-registered study). A 10 km FAIL does not separate a grid miss from
    large-signal operation, chirp or a filter."
13. R12 limits, in R13 and the next `E2a_dev.md` round: "The R12 limit values differ from R11 (M1 0.02659 to 0.01814, M2 0.03456 to
    0.06000, M3 0.08985 to 0.13066, M4 1.2292 to 1.2179) because the metric map became the gain-invariant map (R12.2) and misfit
    and spread were recomputed under it; the formula basis x 2.0 and the multiplier are unchanged. 'Limits were not changed' meant
    only: not moved after seeing the power study. R13 limits equal R12 to 1e-9 (test)."
14. External timestamp. CHECKPOINT line 94: replace "GitHub push time is the first external timestamp for it" with "GitHub holds
    server-side records of the push (not stored in git); evidence in `docs/orchestration/opticps-v2/evidence/`". Capture now,
    inside the 90-day window: `gh api repos/theerayutbo/OpticPS/events --paginate`, keep the PushEvent(s) containing 879a15f and
    4a9222d as `evidence/push_events_2026-11.json`. For R13: push the freeze, `gh release create e2-freeze-r13` with the freeze SHA
    and criterion SHA-256 in the notes, store `gh api repos/theerayutbo/OpticPS/releases/tags/e2-freeze-r13` (`created_at`, `id`)
    as `evidence/release_e2_freeze_r13.json`. Server-set `created_at` is third-party evidence of "no later than"; it proves neither
    authorship nor "no earlier than". Say exactly that.

## D. R13: what changes, what does not, tests, mutants
15. Must change: `holdout.py` (`CRITERION_PATH` to `TERIPHIC_CRITERION_R13.yaml`, `REQUIRED_INPUTS`, items 5, 8); `e2_score.py`
    (items 6, 7, 10, 11, 12; `judged` is correct and stays, only its test was missing); `scripts/score_teriphic_e2.py` (docstring,
    item 8, exit code 3 for a stage or record refusal); the R13 criterion (limits, basis, multipliers, estimators, version 3
    unchanged; new `plan_sha256`); plan Revision 13 addendum, 0 lines removed (items 1 to 14, the record contract, the promise
    restated, "no holdout read"); the `plan_sha256` pin in `configs/benchmarks/teriphic_pd1_pam4.yaml` and
    `tests/test_benchmark_provenance.py`; `FREEZE_GUARD_KNOWN_LIMITS.md` (record binding and its limit); `E2a_dev.md` (item 13).
16. Must not change: `b2b_model.yaml`, `scenario_list.yaml`, `preregistered_predictions.yaml`, `power_study.yaml` (hashes stay),
    `e2_model.py`, `e2_metrics.py`, limits, `SELECTION_MARGIN`, carry rule, map, windows and seeds, `ROLE_BY_NAME`, `LENGTH_KM`. No
    scenario, metric or threshold added. `score_holdout` runs on fixtures only.
17. Order: commit code, tests, docs, plan (compute the plan hash); commit the criterion file alone on `v1.3-mpam` first-parent (the
    freeze); pin outside the repo; push; release evidence (item 14); independent review; E2b. Before E2b, record any wavelength or
    modulator statement from the Zenodo record or TERIPHIC paper in the plan as a SOURCE, for interpretation only; scenarios unchanged.
18. Tests to add in `tests/test_benchmark_e2.py` (fixtures only, repo naming style). Negative: `..._10km_file_is_refused_when_the_
    2km_stage_is_declared_failed_or_undeclared` (FAILED, NOT_DONE, None; 0 hash or open events); `..._refused_when_the_committed_
    2km_record_says_fail` (declared not-failed); `..._refused_without_a_committed_2km_record`; `..._record_hash_in_the_selection_
    must_match_the_committed_record`; `..._carried_ids_must_equal_the_records_carry_forward_in_order` (differ; permutation);
    `..._carried_ids_must_be_the_carry_rule_of_the_recorded_table` (ids and carry_forward edited, table not); `..._2km_record_must_
    name_the_2km_file_at_the_pinned_freeze` (filename, split, criterion_commit, limits, scenarios_scored, one at a time);
    `..._selection_and_the_record_are_added_as_new_files_in_one_commit` (two commits; rename-in; later edit of either);
    `..._records_head_commit_lies_between_freeze_and_selection_with_bound_files_unchanged`; `..._shared_sequence_forces_
    exploratory_at_both_lengths` (2 km FAIL+SHARED and 10 km P,D+SHARED give EXPLORATORY; BLOCKED stays); `..._frozen_script_
    cannot_declare_not_shared` (SystemExit 2); `..._uncarried_control_within_limits_is_not_a_10km_survivor` (FAIL,
    NO_SCENARIO_FITS, control absent). Positive: `..._report_records_declarations_record_window_and_summary`; `..._2km_report_
    written_by_the_script_is_a_valid_record_for_the_10km_stage` (in-process: 2 km on a fixture, record and selection committed,
    10 km on a fixture passes the binding); `test_real_r13_limits_equal_r12_and_the_plan_hash_differs`. Extend `test_every_refusal_
    before_the_holdout_comes_before_any_hash_or_open_of_it` with items 5 and 6; rename `..._and_a_shared_sequence_may_too` to
    `_does_too` and assert it; update `test_the_frozen_script_reaches_every_allowed_verdict_and_never_validated`.
19. Mutants for `scripts/mutate_e2.py` (add `holdout.py` to the mutable files): `judged_includes_uncarried_control` (`judged =
    list(table)`); `stage_failed_accepted_at_10km`; `shared_does_not_force_exploratory`; `record_hash_not_checked`;
    `carry_forward_not_compared`; `carry_rule_not_recomputed_from_record`; `record_outcome_fail_accepted`;
    `record_filename_not_checked`; `selection_and_record_may_differ_in_commit`; `declarations_not_reported`. All killed; none harmless.

## E. Missed by the reviewer
20. Nothing made the operator commit the 2 km report at all; `selected_scenario.yaml` could be typed from memory. Item 6 binds it
    and item 6 also puts the record in `REQUIRED_INPUTS`, without which the guard neither commits nor hashes it.
21. The report omits which window was read and the sample-rate check; `window` (item 7) makes a result reproducible.
22. The 2 km run can be executed twice (look, then commit). Code cannot prevent it; the output is deterministic so the record is
    unaffected; the plan says once and this stays procedural under the promise. State it in R13.
