verified_sha: 784ad2c
# N3 part a, fourth independent QA (Loki, 2026-11-13). VERDICT: PASS (0 BLOCKER, 0 MAJOR, 1 MINOR, 4 OBSERVATION)
Fresh clone at 784ad2c, `opticps.__file__` in the clone, `data/external/` absent. NANF commits after the round 3 pin 6b4939b: only 0c674c9 and a2e8c0c (`git log 6b4939b..784ad2c -- '*nanf*' plan`). Synthetic probes only; no fit, no freeze, no holdout value read. Probe file: scratchpad loki_n3a_r4/probe/test_loki4.py.
## Round 3 findings (repros run at 784ad2c)
1. MAJOR calibration flag: CLOSED. Repro (a) retuned NANF result, index 77: calibration refused ("back-to-back"), also when the NANF point is declared; record present: calibration refused for any input. (b) record deleted: NANF result refused both ways. (c) hash None, "a"*64, upper-case, padded, stale plan, forged self-consistent record, deleted record: scoring refused. Also refused: flag values 1, "yes", [0]; B2B at 1460 nm; NaN ROP; garbage and dangling-symlink records; another working directory (paths come from `__file__`). Accepted only by owner tamper: `dataclasses.replace` of hash or link fields, monkeypatched `freeze_record_present` or `DECLARED_CALIBRATION_POINTS`.
2. Grafts in linked worktree: CLOSED. `--git-common-dir` with `--path-format=absolute`; test builds the review's repro; my mutant dropping the absolute format is killed. Git env is sanitised.
3. Rank-deficient eigenvalues: CLOSED. Duplicate columns and rank-1 J give min eigenvalue 0.0, flags 1 and 5, artefact check accepts; -2x tolerance refused.
4. `b2b_gate` rop optional: CLOSED. `rop` is required keyword-only (TypeError without); 13-point repro FAIL.
5. `run_point` cap-only check: CLOSED. config, forgetting, training length, cap 1e10(1+1e-15), noise=1, diagnostic=0 all raise NotScorableError before the run with the cap stubbed to act; pinned explicit equaliser still gives a lost outcome.
## New findings
1. MINOR, the wavelength half of the calibration B2B check has no test. Mutant `r.link != LinkSpec()` -> `r.link.profile is not None` SURVIVES the NANF tests. At the tip it is correct (probe 1.4: B2B at 1460 nm refused), and Fig.6 B2B is holdout, so add a negative test before the fit.
2. OBSERVATION, the calibration refusal with a broken record is untested: mutant `freeze_record_present()` -> `FREEZE_RECORD_PATH.is_file()` SURVIVES. Correct at the tip (probes 1.14, 1.15), and `simulate_point` refuses every run while such a record exists.
3. OBSERVATION, residual (a) is not in the H-F text (repro: probe 1.11, a pre-freeze retuned NANF result stamped with the public record hash is scored; 1.7, a NANF result relabelled B2B passes calibration).
4. OBSERVATION, the lost-lock tests now stub the RLS (lost_lock, review2); no test runs a real pinned-chain lock loss. Acceptable for cost.
5. OBSERVATION, my survivors L5 (non-finite eigenvalue clause; residuals are already checked finite) and L6 (b2b_gate length check; `_scored` refuses unequal lengths, checked) are equivalent.
## Residuals
(a) Acceptable as a documented residual: score functions take bare arrays by design (G-C), so forging a PointResult adds no path a hand-built array lacks; the holdout guard is `require_freeze` on the read. It must be added to the H-F list at the next amendment, before the fit.
(b) Acceptable, and stated in H-A ("Stated limit"): only declared Fig.4 B2B points at 1550 nm, no record; pre-freeze the vector is free anyway; today the declared set is empty, so calibration=True always refuses.
## Plan
Amendment 9 is append-only (numstat 103/0; the 6b4939b plan hashes to 2f56696f...cbcabf4c6; new SHA-256 2ad3c7af...422301f5). H-A to H-E match the code. No tolerance, threshold, label or split changed; H-A, H-D and H-E tighten. H-C admits a legal B4.5 freeze and flags those parameters, so it cannot favour a result.
## Mutants
`mutate_nanf.py` list covers every round 4 path (calibration guard, nonpinned_reasons, common-dir grafts, eigenvalue floor, required rop); 326/326 is the orchestrator's count, not rerun. Mine: 10 applied, 6 killed, 4 survived (2 real test gaps: findings 1 and 2; 2 equivalent). Clone restored after each.
## Gates
`pytest -o addopts= -rs tests/test_nanf_*.py`: 573 passed, 4 skipped in 344.33s (all four: data/external/nanf_hong2021 is absent). ruff check src tests scripts: All checks passed; ruff format --check: 119 files already formatted; mypy: no issues in 67 source files.
Diff scan: no skip/xfail/TODO/placeholder (only `# fmt: skip` and a stubbed equaliser), no absolute local paths, numbers are synthetic or fibre constants, no holdout value.
## Not checked
Full suite (orchestrator evidence at later tips); data-present tests; `mutate_nanf.py` rerun; forged commit-graph files as an ancestry tamper (owner class, like grafts); a real full-size pinned run.
