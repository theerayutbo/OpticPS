# Brief N3b (Dev): pre-register the NANF fit, build the N3 drivers. No fit run, no holdout read.

Repository: OpticPS, branch `v1.3-mpam`. Start from the tip named in the dispatch message.
Read first: `docs/orchestration/opticps-v2/handoff/N3_scout.md` (69 lines, the map of N3),
then the plan `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md` sections the scout cites (sec 2, sec 4, A4,
B3, B4, F4, F8, G4, G5, G9, G-A to G-E, H-A to H-Z, Amendment 10), then the signatures in
`src/opticps/measurement/nanf_{chain,scoring,freeze,import}.py`.

## Why this unit exists
N3 is: fit six parameters on the back-to-back calibration series, freeze, read the holdout once,
score, report. The plan does not state the optimiser, its start point, seeds, budget, stop rule or how
the residual vector becomes one cost. Those choices must be written down and committed BEFORE the
first fit run, or the fit can be tuned by rerunning. And every source file the holdout run uses is
inside the code identity of the freeze record, so all of it must be final and reviewed BEFORE the
freeze. This unit does both. The fit itself (N3c) and the holdout (N3d) are later units.

## Hard limits
1. Do not run the fit on real data. Do not call `run_point` or `simulate_point` on the real
   calibration series except in tests that already exist. New tests use a stub chain or tiny synthetic
   inputs and must not open the real workbook.
2. Do not read any holdout series. Never pass `include_holdout=True`. Do not create a freeze record
   or a calibration artefact under `docs/benchmarks/`. Do not open anything under `data/external/`
   yourself; nothing in this unit needs it.
3. The plan is append-only. Add Amendment 11 at the end; change no earlier byte. Move the pin in
   `tests/test_nanf_benchmark.py` the way Amendment 10 did (keep the old pin as
   `PLAN_SHA256_AMENDMENT10`, add a test for Amendment 11).
4. Do not change the behaviour of existing functions in `nanf_chain.py`, `nanf_scoring.py`,
   `nanf_freeze.py`, `nanf_import.py`. Filling the three declared sets is allowed (see D2). If you
   think an existing function is wrong, stop and report; do not fix it here.
5. Do not touch any file bound by an earlier gate: `docs/benchmarks/FIT_HOLDOUT_PLAN.md`,
   `docs/benchmarks/teriphic_*`, `holdout.py`, `e2_*.py`, `e3_*.py`, `rates.py`, `published_points.py`,
   `comparison.py`, `E3_WIEGART_RAN.md`, `SOURCE_REGISTER.md`, `e4_*.py`.
6. Clean room: no third-party simulator code, no web access needed. No copied article sentences; the
   licence guard `tests/test_benchmark_provenance.py` scans every committed text file, handoffs
   included. Cite the plan by section, do not quote article text.
7. Local commits only, explicit paths in `git add`, author
   `git -c user.email=12473766+theerayutbo@users.noreply.github.com commit`. No push. Never commit the
   owner files in the repository root (`CLAUDE_CODE_BENCHMARK_START.txt`, `OpticPS_*.md`).

## Deliverables
D1. **Amendment 11** (commit it first, alone with the pin move and its test). It must state:
   - the cost: how the B4.2 residual vector (SNR dB residuals and log10 BER residuals over 0.5, on the
     A4 points) becomes one number. Default: sum of squares. A lost-lock vector costs +inf (H4).
   - the optimiser, fully deterministic: start point = the B4 priors; a seeded space-filling design in
     the B4 box; a bounded derivative-free local search from the best design point; the exact seed;
     the stop tolerances; a hard budget of **at most 70 cost evaluations in total** (prior, design and
     local search together). Propose the split; a split near 1 + 24 + 45 is expected. If you believe a
     different deterministic scheme is better within 70 evaluations, state it and why.
   - what `converged` means for this optimiser (the stop tolerances met before the budget ends) and
     what happens if it is not met: N3 stops with `CALIBRATION NOT CONVERGED` and goes to the owner.
     No second optimiser, no wider ranges, no extra budget without a new amendment.
   - the selected vector is the lowest finite cost in the whole evaluation log (`select_best`); ties
     broken by evaluation order. Range-edge results are reported, ranges are never widened.
   - one run only: the fit driver refuses to start if an evaluation log from an earlier run exists,
     unless it is a resume of the same run (same plan hash, same code identity, same seed); a resume
     replays the log and continues, it never restarts.
   - the declared sets of D2 and the rule used for holdout point indices.
   - the full H-Z list restated (the reviewer's MINOR on Amendment 10: include "A3 and B1 to B3" and
     "the rules of Amendments 7 and 8 except as corrected").
   - which of C6 to C8 are simulated. The OFDM chain does not exist (F9). Do not build it here. State
     that C6 to C8 are reported `NOT BUILT` unless the plan forces otherwise; if the plan forces it,
     stop and report.
D2. **Declared sets** in `nanf_chain.py`: `DECLARED_CALIBRATION_POINTS`, `DECLARED_LINKS`,
   `DECLARED_POINT_INDICES`. Calibration points come from the calibration series (legal to know).
   For holdout series, declare point indices only from counts and axes that the committed plan or
   committed importer metadata already state (G9, G-B, G-A). If a count or axis is not already in
   committed text, STOP and report which one; do not read it from the workbook.
D3. **Calibration objective and fit driver** (new module under `src/opticps/measurement/`, plus
   `scripts/nanf_fit.py`): builds the residual vector from the Fig.4 back-to-back series, runs the
   Amendment 11 optimiser through `evaluate`, writes the evaluation log as it goes, then runs
   `check_chosen_fit`, `identifiability_check` (once), `b2b_gate` per rate, and builds the artefact
   bytes with `calibration_artifact`. Point evaluations may run in up to 6 processes; the result must
   be identical to the serial result (test this with the stub chain).
D4. **Freeze script** `scripts/nanf_freeze.py`: calls `build_freeze_record`, writes the record file,
   refuses if the artefact is not committed at HEAD or the work tree is dirty in any identity path.
D5. **Holdout runner and report writer** (module plus `scripts/nanf_holdout.py`): `require_freeze`
   first, one read with `include_holdout=True` and the freeze hash, simulate with `run_point` and
   `curve_arrays`, score C1 to C5, `overall_verdict`, the B2B-copy comparator, lost points listed, and a
   report that contains the exact sentence the test at `tests/test_nanf_benchmark.py` (search
   "not fully blind") requires, the label LITERATURE BENCHMARK / CALIBRATION ONLY, and never the word
   "validation" as a claim. The runner writes a marker when the holdout has been read and refuses a
   second scoring run that would follow any change of parameters.
D6. **Tests** for D3 to D5 on a stub chain and synthetic series: determinism (same seed, same log),
   budget cap enforced, +inf for lost lock, not-converged path, resume replays and does not restart,
   refusal to start a second run, serial equals parallel, freeze script refusals, holdout runner
   refuses without a record, report wording. Add mutants for each new guard to
   `scripts/mutate_nanf.py` and run the whole list; report killed over applied.
D7. **Handoff** `docs/orchestration/opticps-v2/handoff/N3b_dev.md`, at most 40 lines, no absolute
   paths: files touched, the Amendment 11 choices in one line each, test counts, mutant totals, gates
   (NANF tests, `ruff check`, `ruff format --check`, mypy), anything you stopped on, tip SHA.

## Gates you run
`.venv/bin/python -m pytest tests/test_nanf*.py -o addopts= -q`, the mutant list,
`tests/test_benchmark_provenance.py`, ruff check, ruff format --check, mypy. A failing gate is
reported with its output, never skipped or marked expected-fail. No placeholder tests, no TODO stubs.

## Return to the orchestrator
Only: tip SHA, commits (count and hashes), files touched, the Amendment 11 choices (five lines),
gate totals, `done` or `blocked` with one line why.
