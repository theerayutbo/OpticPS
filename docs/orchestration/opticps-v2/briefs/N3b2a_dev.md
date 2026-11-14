# Brief N3b-2a (Dev): fix round, fit side. Amendment 12. No fit run, no holdout read.

Repository: OpticPS, branch `v1.3-mpam`. Start from the tip named in the dispatch message (e9c5260).
This is the fix round after the reviewer's FAIL on N3b. Read first, in this order:
1. `docs/orchestration/opticps-v2/handoff/N3b_qa.md` (the verdict; findings 1, 2, 6, 7, 8, 11, 12 are yours).
2. Plan `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md`, Amendment 11 (starts near line 1245), J-A to J-D.
3. `src/opticps/measurement/nanf_fit.py`, `scripts/nanf_fit.py`, `tests/nanf_fit_stub.py`,
   `tests/test_nanf_n3b_fit.py`.
A later unit (N3b-2b) handles the C5 links and the holdout runner (findings 3, 4, 5, 9). Do not
touch `nanf_holdout.py`, `scripts/nanf_holdout.py`, `DECLARED_LINKS` or the holdout tests.

## Hard limits (unchanged from N3b)
1. Do not run the fit on real data. No call of `run_point` or `simulate_point` on the real
   calibration series. New tests and the study use the stub chain or synthetic inputs only and never
   open the real workbook. Open nothing under `data/external/`.
2. No holdout read, never `include_holdout=True`. No freeze record, artefact, evaluation log or marker
   under `docs/benchmarks/`.
3. The plan is append-only. Add **Amendment 12** at the end, change no earlier byte. Keep the current
   pin as `PLAN_SHA256_AMENDMENT11`, move `PLAN_SHA256`, add a test for Amendment 12 (same pattern as
   Amendments 10 and 11). Commit the amendment FIRST, alone with the pin move and its test.
4. Existing behaviour of `nanf_chain.py`, `nanf_scoring.py`, `nanf_import.py` does not change. In
   `nanf_freeze.py` only the change named in A2.5 is allowed. If you need more, stop and report.
5. No file bound by an earlier gate: `docs/benchmarks/FIT_HOLDOUT_PLAN.md`, `docs/benchmarks/teriphic_*`,
   `holdout.py`, `e2_*.py`, `e3_*.py`, `rates.py`, `published_points.py`, `comparison.py`,
   `E3_WIEGART_RAN.md`, `SOURCE_REGISTER.md`, `e4_*.py`.
6. Clean room: no third-party simulator code, no web access. A library routine from a dependency
   already in `uv.lock` (for example SciPy) may be called; do not copy its code. No copied article
   sentences; the licence guard scans every committed text file, handoffs included.
7. Local commits only, explicit paths in `git add`, author
   `git -c user.email=12473766+theerayutbo@users.noreply.github.com commit`. No push. Never commit the
   owner files in the repository root (`CLAUDE_CODE_BENCHMARK_START.txt`, `OpticPS_*.md`).

## What was wrong (finding 1, the blocker)
The search stops and reports `converged` when one accepted step under a secant (Broyden) Jacobian is
short and gains little. A stale Jacobian gives short steps far from a minimum, so a stall reads as
convergence (reviewer: 8 of 12 stub targets "converged" 18x to 529x above the known minimum).

## Required semantics of `converged` (decided by the orchestrator; implement exactly)
Let c(x) be the cost, x_s the selected vector (lowest finite cost in the whole log, ties by order,
as Amendment 11 already says). `converged` is true only if all of the following hold:
- S1. A full forward-difference Jacobian (all six columns) was evaluated AT a vector x_t. Its six
  evaluations are in the log and in the budget. A secant-updated Jacobian never counts.
- S2. From that fresh Jacobian, the bounded damped step at the smallest damping predicts a relative
  cost decrease of at most tau (first-order test, bounds respected: a coordinate on a bound whose
  step would leave the box is held).
- S3. The cost at that step was actually evaluated (one evaluation, in the log and the budget) and
  does not beat c(x_t) by more than tau relative.
- S4. Nothing in the whole log beats c(x_t) by more than tau relative. So c(x_s) >= (1 - tau) c(x_t).
  If a probe or trial point beats x_t by more than tau, the search moves there and goes on.
Anything else ends as not converged: `CALIBRATION NOT CONVERGED`, no artefact, to the owner
(unchanged). Between fresh Jacobians, secant updates are allowed to save evaluations, but when the
stop test looks met under a secant Jacobian the code refreshes the Jacobian there and tests again.
You choose tau, the difference step h (in the unit box), the damping schedule and the budget split.
Choose them ONLY from the stub study below. The total budget is a hard cap you state, **at most 160
cost evaluations** including the design, every Jacobian column, every trial and the final
re-evaluation of A2.3; pick the smallest that the study supports and say why.
The text of the amendment must determine the algorithm completely: either your own steps written so
that a second implementer gets the same evaluation sequence, or a named library routine with every
option stated (its version is pinned by `uv.lock`), plus S1 to S4 done by your own code and not by the
library's stop flag. Text and code must agree (finding 6: today they differ on the damping ladder
and on when a refresh happens).

## Deliverables
A1. **Amendment 12** (first commit). Sections, each short:
   - corrects J-A (finding 7): say plainly that a simulated BER below 1e-5, censored for scoring by
     A3/F2, still enters the fit term when the published cell is uncensored, and give the reason. If
     you find the code should instead follow A3/F2, stop and report; do not change it silently.
   - replaces J-B.3 to J-B.5 and J-B.7: the optimiser as above, the budget, S1 to S4.
   - the stub study: what is committed, how it is rerun, its result in numbers (stub only).
   - completes J-D (finding 2, 12): the items of A2 below, the commit rule for the log, the stated
     limit (the guards stop accidents and silent drift, not a person who edits residuals or deletes an
     uncommitted log), and that a truncated last log line is a permanent refusal (fail closed).
   - the fit script's read (finding 11): either read only the Fig.4 back-to-back series if the
     importer already offers that without a behaviour change, or name the default read as an
     exception of the G-E.5 class.
   - a closing list of what stands unchanged from Amendment 11 and earlier (as H-Z and J did).
A2. **Code** in `nanf_fit.py` and `scripts/nanf_fit.py`:
   1. The optimiser and `converged` as above.
   2. Log header binds the fit code: add the SHA-256 of `nanf_fit.py` and of `scripts/nanf_fit.py`
      (the freeze identity rightly leaves them out; the header must not). A header that differs in
      any field is refused.
   3. Replay does not trust a recorded cost: recompute it from the recorded residuals, require
      +inf exactly when lost points are recorded, refuse on any mismatch. After the search ends and
      before any artefact is built, evaluate the selected vector once more, fresh, and require the
      same cost bit for bit; otherwise refuse.
   4. The log is written at a path under `docs/benchmarks/` that the amendment names, and is
      committed in the same commit as the artefact (process rule, stated in the amendment and
      printed by the script when it ends).
   5. The SHA-256 of the evaluation log goes into the artefact `checks`. If `calibration_artifact`
      or its validator in `nanf_freeze.py` needs a change for that, make the smallest one, state it in
      the amendment (it extends G4/G-D), keep every N3a test green. If it needs more than the builder,
      its validator and their tests, stop and report.
A3. **Stub study**, committed and rerunnable (a script under `scripts/` or a test module, your
   choice; fast, stub chain only): at least 12 synthetic targets with a known attainable minimum,
   each in two variants (continuous BER, and BER quantised to error counts). For each: budget used,
   converged or not, final selected cost, known minimum, ratio. A test asserts **zero false
   convergence**: no case with `converged` true whose selected cost exceeds the known minimum by more
   than a margin you state and justify. If a converged case is a true local minimum above the global
   one, show it is stationary by an independent fine check and list it apart; say in the amendment
   what `converged` does and does not claim. Report the fraction not converged honestly; do not tune
   the targets to hide it. If you cannot reach zero false convergence within 160, stop and report.
A4. **Tests**: finding 8 (a wrong axis with the same count, for example a shift of -0.5 dB on a 1 dB
   grid; a single lost point gives +inf); a stall is never `converged`; S1 to S4 each have a case;
   header mismatch refused (edited fit module hash); edited recorded cost refused on replay; final
   re-evaluation mismatch refused; resume equals an uninterrupted run byte for byte; serial equals
   six-process parallel; truncated last line refused.
A5. **Mutants** for every new guard in `scripts/mutate_nanf.py`. Also make that script print each
   outcome as it completes (keep the final summary line and exit codes). Run only the fit-side
   mutants with `-k`; the orchestrator runs the whole list in a clean clone afterwards. Report
   killed over applied, and name any survivor.
A6. **Handoff** `docs/orchestration/opticps-v2/handoff/N3b2a_dev.md`, at most 40 lines, no absolute
   paths, no quoted article text: files touched, the Amendment 12 choices one line each (tau, h,
   budget and split, margin), the study table totals, test counts, mutant totals, gates, anything you
   stopped on, tip SHA.

## Gates you run
`.venv/bin/python -m pytest tests/test_nanf*.py -o addopts= -q`, `tests/test_benchmark_provenance.py`,
the fit-side mutants, `ruff check`, `ruff format --check`, mypy. A failing gate is reported with its
output, never skipped or marked expected-fail. No placeholder tests, no TODO stubs.

## Return to the orchestrator
Only: tip SHA, commits (count and hashes), files touched, the Amendment 12 choices (five lines), the
study totals (cases, converged, false convergence count, worst ratio), gate totals, `done` or
`blocked` with one line why.
