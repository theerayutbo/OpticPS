# N3a close, Dev (review 4 items), base d58ddce
Source behaviour unchanged. No fit, no freeze, nothing under data/external/ opened by me, no holdout value read.

## Files touched
- tests/test_nanf_n3a_review2.py: 3 new tests (1 plain, 1 with 2 parameters)
- tests/test_nanf_n3a_real_lock_loss.py: new, 1 test
- tests/test_nanf_benchmark.py: pin moved, Amendment 10 test added
- scripts/mutate_nanf.py: 2 mutants added
- docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md: Amendment 10 appended (additions only)

## What each new test proves
- test_a_back_to_back_point_at_another_wavelength_is_not_a_calibration_point: B2B (no fibre) at 1460 nm offered with calibration=True is refused ("back-to-back"); the 1550 nm point is accepted. Kills `r.link != LinkSpec()` -> `r.link.profile is not None`.
- test_calibration_is_refused_while_a_broken_record_exists[garbage, dangling_symlink]: FREEZE_RECORD_PATH is monkeypatched to a tmp path (the real path is never written); calibration is refused both ways. Kills `freeze_record_present()` -> `FREEZE_RECORD_PATH.is_file()` (the dangling symlink case).
- test_the_real_equaliser_loses_lock_on_the_pinned_chain_and_the_run_is_marked_invalid: run_point at 80 Gb/s, -30 dBm, default full-size chain, real RLS, nothing stubbed (about 20 s): outcome lost, result None, reason "trace cap acted ...", lost_report line, curve_arrays marks it invalid (valid False, n_lost 1, BER and SNR NaN).
- test_plan_text_before_amendment_10_is_unchanged_and_amendment_10_states_residual_a: the text before the new heading hashes to the Amendment 9 pin; the residual is stated as a limit.

## Plan Amendment 10 (H-F item 6, residual (a)), pin
New plan SHA-256: d350fe85b125c7a5d726c8456f89fed182532188e6a22ce59b44b935f5f159c6 (previous 2ad3c7af...422301f5, kept as PLAN_SHA256_AMENDMENT9).
Pinned only in tests/test_nanf_benchmark.py (PLAN_SHA256). The old prefix 2ad3c7af also stays in handoff N3a_dev4.md and N3a_qa4.md; those are past records, left as written.
Prefix check: the bytes of the old plan are a byte-for-byte prefix of the new plan. No tolerance, threshold, label, split or criterion touched.

## Mutants (scripts/mutate_nanf.py, run at the tip of the mutant list)
328 applied, 328 killed, 0 survived, 0 broken (326 before + the 2 new). The two new ones also killed in isolation. The real lock-loss test is not in the mutate TESTS tuple (20 s per run), so the mutate run did not include it.

## Gates (run at the tip before this handoff commit; the handoff adds only a doc)
- pytest -o addopts= -q tests/test_nanf*.py: 582 passed in 463.14s (0:07:43). Note: the data tests ran here, not skipped, because this tree has data/external; the tests read it, I did not.
- mutate_nanf.py: 328 of 328 killed (mutants run before the lock-loss test commit; script and sources unchanged since)
- ruff check src tests scripts: All checks passed!
- ruff format --check src tests scripts: 130 files already formatted
- mypy: Success: no issues found in 73 source files

## Open items
- None from the four review items. Lock-loss: one real point (-30 dBm, 80 G) is covered; a real lock loss by RlsInstabilityError (rather than the trace cap) is not driven.
