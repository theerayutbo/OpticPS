# Brief N3b-2b (Dev): fix round, C5 links and holdout runner. Amendment 13. No fit run, no holdout read.

Repository: OpticPS, branch `v1.3-mpam`. Start from the tip named in the dispatch message (the tip
left by N3b-2a, which added Amendment 12 and reworked the fit side; do not touch `nanf_fit.py`,
`scripts/nanf_fit.py` or the fit tests). Read first, in this order:
1. `docs/orchestration/opticps-v2/handoff/N3b_qa.md` (the verdict; findings 3, 4, 5, 9 and section G
   are yours).
2. Plan `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md`: the section 2 table (the Fig.1 row), rules 1, 3
   and 7, section 4 (C5 row and decision rule), A2 (B2B-copy and d), A3 (C5 definition), B2, B3.2,
   B3.3, D1, D3.1, F4.2, F4.6, G4, G5, G-C, Amendment 11 J-E and J-G, Amendment 12.
3. `src/opticps/measurement/nanf_holdout.py`, `scripts/nanf_holdout.py`, `nanf_chain.py` (the
   declared sets and the link check in `run_point`), `nanf_scoring.py` (`score_c2`, `score_c5`,
   `b2b_copy`, `overall_verdict`, the RateScores type), `nanf_benchmark.py` (`d_table_from_workbook`).

## Why
Every file the holdout run uses is inside the code identity of the freeze record. Amendment 11 left
C5 "open" (links at other wavelengths not declared). Declaring them after the freeze would relock
the record, so C5 would be lost for good, yet C5 is a primary criterion. It must be settled in plan
and code now, before the fit starts.

## Decision (orchestrator, on the reviewer's section G and plan B2; implement exactly)
- The dispersion of each C5 link at each wavelength comes from the paper's own Fig.1(a) curve of
  that fibre. Plan B2 already treats those curves as the dispersion source of C5 (it drops 1630 and
  1640 nm because they end at 1625 nm), and rule 3 says fibre properties are set from the paper or a
  standard before the run and never fitted. Fig.1 stays in the cross-check partition; it is not
  holdout and its importer role does not change.
- Amendment 13 widens the Fig.1 row from "used only to check" to: also a fibre input for the C5
  links, set from the paper, never fitted. It must also say the consequence: for those links the
  Fig.1(a) dispersion cross-check is then not independent evidence.
- Rule 7 forbids committing workbook values. So the declaration is a RECIPE in `nanf_chain.py`:
  the links are built at run time from the workbook whose SHA-256 the importer pins. For each of the
  17 wavelengths 1460 to 1620 nm in 10 nm steps: NANF 4.76 km, SSMF 4.53 km, with D at that
  wavelength from the Fig.1(a) table (use the existing `WavelengthTable` rule, no extrapolation;
  state the rule in the amendment), every other link property as in the 1550 nm declared links
  unless the existing model already makes it wavelength dependent (say which), plus a back-to-back
  link per wavelength. ROP per wavelength from the Fig.5 column (A3, D1); loss zero at matched power
  (F4.6). Point index = the index of the wavelength on the 19-point grid. 1630 and 1640 nm are not
  simulated and are reported as not simulated (B2 allows, does not require, the unscored extra).
- `run_point` must refuse a link that the recipe did not produce from the hash-verified workbook,
  exactly as it refuses an undeclared link today. For every input that exists today its behaviour
  is unchanged (all current tests and mutants stay green).

## Hard limits
1. No fit run on real data. No holdout read, never `include_holdout=True` outside code paths that
   tests drive with synthetic workbooks. Open nothing under `data/external/`; tests and you never
   open the real workbook. Use synthetic tables and stub chains.
2. No freeze record, artefact, evaluation log or marker under `docs/benchmarks/`.
3. The plan is append-only. Add **Amendment 13** at the end, change no earlier byte; keep the
   current pin as `PLAN_SHA256_AMENDMENT12`, move `PLAN_SHA256`, add a test for Amendment 13. Commit
   the amendment FIRST, alone with the pin move and its test.
4. `nanf_scoring.py`, `nanf_import.py`, `nanf_freeze.py`: no behaviour change. `nanf_chain.py`: only
   the recipe and the link check as decided above. If an existing function looks wrong, stop and
   report.
5. No file bound by an earlier gate: `docs/benchmarks/FIT_HOLDOUT_PLAN.md`, `docs/benchmarks/teriphic_*`,
   `holdout.py`, `e2_*.py`, `e3_*.py`, `rates.py`, `published_points.py`, `comparison.py`,
   `E3_WIEGART_RAN.md`, `SOURCE_REGISTER.md`, `e4_*.py`.
6. Clean room, no web access, no copied article sentences (the licence guard scans handoffs too).
7. Local commits only, explicit paths in `git add`, author
   `git -c user.email=12473766+theerayutbo@users.noreply.github.com commit`. No push. Never commit the
   owner files in the repository root.

## STOP and report (do not decide yourself) if
- the importer metadata or committed text leaves more than one candidate Fig.1(a) curve for a fibre,
  or does not say which Fig.5 column gives the ROP of a link, or which Fig.6 series is which link;
- a wavelength of the 17 cannot be simulated without changing an existing function beyond the
  link check;
- the plan gives two readings of how C5 enters the verdict.
Never settle such a point by looking at holdout values.

## Deliverables
B1. **Amendment 13** (first commit): the Fig.1 row and its consequence; the recipe; C5 scoring per
   rate and link with `score_c5`, the NANF part also scored for the B2B copy with d (A2); the
   verdict through `overall_verdict` (finding 4); the B2B-copy C2 scored by the same rules with
   `score_c2` (finding 5); the marker rule (finding 9): the marker and the report are committed
   straight after the run, and what that rule can and cannot stop; what replaces J-E.4 and the
   `NOT RUN (links not declared)` wording of J-G; a closing list of what stands unchanged.
B2. **Recipe and link check** in `nanf_chain.py`, with tests on synthetic tables (a link from the
   recipe passes; a link with another D, length or wavelength is refused; 1630, 1640 and any other
   wavelength are refused; the 1550 nm links behave as before).
B3. **Holdout runner** `nanf_holdout.py` and `scripts/nanf_holdout.py`: builds the C5 links from the
   read, runs the 17 wavelengths for the three links at each rate, scores with `score_c5`; builds
   the RateScores and calls `overall_verdict` with the real C5 status (B3.2, B3.3: a gate-poor rate
   and NOT DISCRIMINATING must show as the plan says, weak rates named); applies `score_c2` to the
   B2B copy (max error check and pass included); lists lost points; the script prints the marker
   commit rule when it ends. The report keeps the required "not fully blind" sentence, the label
   LITERATURE BENCHMARK / CALIBRATION ONLY, and never claims validation.
B4. **Tests** on stub chain and synthetic workbook for all of B3, including: a gate-poor rate with d
   above tolerance does not print a pass; NOT DISCRIMINATING appears with its rates; a lost C5 point
   flows as the plan's H rules say; C5 never reads "consistent" when a point is missing.
B5. **Mutants** for each new guard in `scripts/mutate_nanf.py`; run the holdout-side and chain-side
   mutants with `-k`; the orchestrator runs the whole list in a clean clone afterwards. Report
   killed over applied, name any survivor.
B6. **Handoff** `docs/orchestration/opticps-v2/handoff/N3b2b_dev.md`, at most 40 lines, no absolute
   paths, no quoted article text: files touched, the Amendment 13 choices one line each, the point
   count of the holdout run after this change, test counts, mutant totals, gates, anything you
   stopped on, tip SHA.

## Gates you run
`.venv/bin/python -m pytest tests/test_nanf*.py -o addopts= -q`, `tests/test_benchmark_provenance.py`,
the mutants named in B5, `ruff check`, `ruff format --check`, mypy. A failing gate is reported with
its output, never skipped or marked expected-fail. No placeholder tests, no TODO stubs.

## Return to the orchestrator
Only: tip SHA, commits (count and hashes), files touched, the Amendment 13 choices (five lines),
gate totals, `done` or `blocked` with one line why.
