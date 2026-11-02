# E1 QA, fifth review (Loki, diff-only closing check)
verified_sha: 1e1e90af364cec8a559d29aa8ee2982b70e775a1
verdict: PASS (0 BLOCKER, 0 MAJOR, 0 MINOR, 2 OBSERVATION).

Item 1, holds: finding 1 (R9.1, known limits, E1_dev), finding 2 (R9.2, known limits), finding 3 (mutant and one-block test added), finding 4 (R9.3, known limits). `require_frozen_criterion` has no call in `src` or `scripts`: only its definition, its own docstrings and one string in `scripts/mutate_benchmarks.py`. Nothing in `src` imports `holdout`.
Item 2, holds: plan SHA-256 9e7b51ad...ef24 recomputed at the pin, previous pin 37487f3b...f058 recomputed at ae9add3 and at 9778ce8, 35 added, 0 removed, new pin equal in test and YAML.
Item 3, holds: the promise is word for word in the plan and in `holdout.py` at both commits; known limits differs only in the lower-case first "the"; the test constant matches.
Item 4, holds: clean detached worktree, .venv 3.11.15, `opticps.__file__` in the worktree, B2B alone linked, `-o addopts="-rN"`, one run: `568 passed, 1 skipped in 217.24s (0:03:37)`, rc 0. Equal to Dev's count. The skipped test was not identified. Sample bytes came from B2B only.
Mutant `recheck_only_multi_block` applied by hand: `test_post_loop_recheck_also_covers_a_record_of_one_block` fails with "DID NOT RAISE BenchmarkError", `1 failed, 185 deselected`, rc 1. Killed by the named assertion. Restored: worktree status empty, same test `1 passed`, rc 0. `scripts/mutate_e1.py` was not rerun end to end.
My first run script stopped after the base step on a zsh globbing error in its own echo line. Tests were unaffected; the clean check and the mutant were then run by hand. Worktree removed.

## OBSERVATION
1. "No scorer exists" (R9.1, known limits, E1_dev) is true of the TERIPHIC holdout only. `src/opticps/measurement/nanf_scoring.py` is a scorer for NANF; it has no holdout reference and reads no files.
2. The `holdout.py` docstring still says in the present tense that a VALIDATION or LOCKED_TEST asset "is not evaluated unless" the criterion passes. Outside this scope and unchanged in this round.
