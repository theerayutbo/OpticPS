# N3a round 4, Dev measurement (report-only, INCOMPLETE)
Tip 784ad2c, fresh clone, PYTHONPATH confirmed inside the clone. Round 4 commits: 0c674c9, a2e8c0c. Plan Amendment 9.
Plan SHA-256 (docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md): 2ad3c7af660d836cb4d31238a6658b2dff9623d858ef415a9999e776422301f5 (last heading: Amendment 9).

## Findings of N3a_qa3 (judged from diff and test reading; the new tests were not run separately)
| # | Where addressed | Test | Judgement |
|---|---|---|---|
| 1 MAJOR calibration flag | 0c674c9 src/opticps/measurement/nanf_chain.py curve_arrays (~816-851): refuses calibration=True when freeze_record_present(); needs default link, no record hash, point in DECLARED_CALIBRATION_POINTS (empty); scoring compares hash to load_freeze_record().freeze_hash | tests/test_nanf_n3a_review2.py test_the_calibration_flag_is_checked_not_trusted, test_a_result_must_carry_the_hash_of_the_record_that_verifies_now (both encode the reviewer repros a, b, c) | ADDRESSED by reading; test run not completed |
| 2 grafts in linked worktree | nanf_freeze.py:~367 uses --git-common-dir | test_grafts_are_refused_from_a_linked_worktree_too | ADDRESSED by reading |
| 3 rank-deficiency eigenvalues | nanf_scoring.py EIGENVALUE_ROUNDOFF_RELATIVE=1e-10, floor then refuse beyond | test_a_true_rank_deficiency_..., test_a_truly_negative_eigenvalue_is_still_refused, hand-written artefact test | ADDRESSED by reading |
| 4 b2b_gate rop optional | nanf_scoring.py b2b_gate: rop required keyword | test_the_b2b_gate_takes_a_rop_axis_... | ADDRESSED by reading |
| 5 run_point only checks cap | nanf_chain.py nonpinned_reasons + run_point refuses before run | test_anything_that_makes_a_run_non_pinned_is_refused_before_it_runs | ADDRESSED by reading |
Reviewer repro: the repro is encoded in the tests above; I did not run it separately (not run).

## Sibling sweep (read only)
- nanf_import.read_nanf_workbook include_holdout: guarded by require_freeze (twice). 
- nanf_chain.require_scorable(frozen_hash=): caller-typed, only safe via curve_arrays.
- published=True / valid masks / passed fields in nanf_scoring: unguarded by design, listed as residual in Amendment 9 H-F.
- PointResult rate/rop/point_index/link are plain fields; dataclasses.replace can forge them (the tests do so). Residual, not in H-F text.
- Limit stated in H-A: with the record deleted, any vector at a declared B2B point counts as calibration (set is empty today, so calibration=True is always refused now).

## Gates at 784ad2c in clone
- ruff check: All checks passed. ruff format --check: 233 files already formatted. mypy: no issues, 67 source files.
- Full pytest: NOT COMPLETE. Started, was about 3 percent through when this report was forced; no totals. Not run: NANF targeted tests separately.
- Mutation: scripts/mutate_nanf.py exists. NOT RUN (held back to avoid CPU contention with the suite). No counts, no survivors known.
## Unfinished-code scan
Round 4 test diff grep for skip/xfail/TODO/FIXME/placeholder/NotImplemented: nothing found (grep run on the two commits' test diffs only; src diff read, nothing seen).
## Open risks
Gate totals and mutants are missing; the verdict on the suite is unknown. Clone and partial run: the scratchpad n3a_r4_clone and full.txt.

## Orchestrator addendum, 2026-11-13: the missing gate totals (run by the orchestrator, not the Dev)
All in a fresh clone at 784ad2c with `PYTHONPATH` set to the clone (`opticps.__file__` inside the clone; `data/external/` absent there).
- NANF targeted tests (`tests/test_nanf_*.py`): exit 0, 0 failed, 4 skipped (all four: `data/external/nanf_hong2021 is absent`).
- Mutation (`scripts/mutate_nanf.py -j 3`): unmutated copy ok; 326 mutants applied, 326 killed, 0 survived. Per module: nanf_scoring 92, nanf_chain 81, nanf_freeze 63, nanf_import 41, fiber 25, dfe 16, nanf_benchmark 5, link 3.
- Full suite: no NANF file changed between 784ad2c and 65b53bd (`git diff --stat 784ad2c..65b53bd -- '*nanf*'` is empty). Clean-clone full runs at later tips: 9d89382, 2355 passed, 9 skipped, 0 failed; 65b53bd, 2406 passed, 9 skipped, 0 failed. The file `full.txt` named above is not used as evidence: its total (2341 passed, no skips) matches a run in the work tree with `data/external/` present, not the clone at 784ad2c.
- Still true from the Dev's part: the round 4 findings are "ADDRESSED by reading"; the reviewer's reproductions were not run by the Dev. The reviewer must run them.
