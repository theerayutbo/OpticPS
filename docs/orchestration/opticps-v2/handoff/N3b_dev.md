# N3b Dev handoff: pre-register the NANF fit, build the N3 drivers (no fit run, no holdout read)
Start tip aedcd28. No fit on real data, no holdout read, no freeze record or artefact, `data/external/` not opened by me.
Standing exception: the NANF test gate includes the three default-read tests of G-E.5 (they skip without the data).

## Commits (in order)
1. Amendment 11 plus the pin move and its test (alone, first). Plan text above it unchanged.
2. Declared sets in `nanf_chain.py`; `nanf_fit.py`; stub chain; fit tests.
3. `nanf_holdout.py` (freeze writer, runner, report); `nanf_freeze.py` ENTRY_MODULES gains the runner; tests.
4. Scripts `nanf_fit.py`, `nanf_freeze.py`, `nanf_holdout.py` (thin).
5. Guard tests and the N3b mutants. 6. This handoff.

## Amendment 11 choices
- Cost: sum of squares of the B4.2 vector (24 SNR terms, log10 BER over 0.5 on uncensored cells); zero-error sim BER as 1/N_b; lost lock gives +inf.
- Optimiser: prior (1) + seeded Latin hypercube (24, SeedSequence [20261101, 4101]) + damped Gauss-Newton with forward-difference Jacobian and Broyden updates (45); at most 70 evaluations.
- Departure from the brief: Nelder-Mead needed 87-148 evaluations (none within 70) on a synthetic case; the chosen search met its tolerances in 7 of 12 synthetic cases. Reason in J-B.7. Reviewer may overrule.
- Converged = accepted step <= 0.02 in u and cost gain <= 2 percent before the budget ends; a stall or the budget gives CALIBRATION NOT CONVERGED, no artefact, owner.
- One run: JSONL log with header (plan, code, seed, budget); another header is refused; same header resumes by replay.

## Stopped on (owner ruling needed before N3c)
- Fig.6 links (C5): D(wavelength) tables are Fig.1(a) workbook values, not read. Only the two 1550 nm links are declared. C5 is `NOT RUN (links not declared)`; the verdict is then failed or `INCOMPLETE`, never consistent (J-E.4).
- Calibration grid -12 + k dB, k=0..7 is read from "11 points from -12 to -2"; the fit refuses if the real axis differs.
- Holdout indices 0..18 from the stated counts 6, 11, 19.
- ENTRY_MODULES edit in `nanf_freeze.py` (a constant, no function changed) so the runner is in the identity.
- Whole-list mutant rerun not completed: it ran over 3 h and was stopped. Old mutants untouched; their code has no change except the filled sets.

## Gates
- NANF tests (`tests/test_nanf*.py`): 651 passed (new: 33 fit, 35 holdout).
- Mutants (N3b list): 60 of 60 killed (fit 28, holdout 28, freeze 1, chain 3); one fit mutant (`np.clip` in `call`) declared equivalent and removed. The 4 older importer mutants matching "holdout" also killed. Full-list rerun not completed (see above).
- ruff check and ruff format --check: clean. mypy: no issues in 75 files.
- Provenance test file: see final message.
Tip SHA: see final message (this file is the last commit).
