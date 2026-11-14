# Brief N3b-2 (Loki): independent review of the N3b fix round. Tip 0d8abb1.

Repository: OpticPS, branch `v1.3-mpam`. Range under review: aedcd28..0d8abb1 (12 local commits; the
fix round is e9c5260..0d8abb1: c8c6d8c, f99bae8, 22b82da by fix unit 2a; f29734c, 23413bd, 0d8abb1 by
fix unit 2b). Your earlier verdict on e9c5260 was FAIL: `docs/orchestration/opticps-v2/handoff/N3b_qa.md`
(13 numbered findings and section G). This is the re-review. A second FAIL goes to the owner, so
separate clearly what blocks the fit from what is a note.

You verify; you fix nothing, commit nothing, and edit no file except your verdict. Re-derive from the
code and the plan. The Dev handoffs (`handoff/N3b2a_dev.md`, `handoff/N3b2b_dev.md`) and the briefs
(`briefs/N3b2a_dev.md`, `briefs/N3b2b_dev.md`) say what was asked and claimed; they are not evidence.

## Hard limits on you
- Work in your own clean clone at 0d8abb1 inside the scratchpad named in the dispatch message, with
  `PYTHONPATH=<clone>/src` and the repository's `.venv/bin/python`. Do not run anything that writes
  into the main work tree. `pyproject.toml` sets `addopts = "-q"`: pass `-o addopts=`. No xdist.
- Open, read, hash or list nothing under `data/external/`. Run no fit on real data. Read no holdout
  series. No web access. Use stub chains and synthetic inputs for every repro.
- The licence guard scans your verdict too: never quote article text or any flagged text; cite file
  and line. No absolute paths in the verdict.
- The orchestrator runs the whole mutant list in a separate clean clone at the same tip. Do not run
  the whole list. Run targeted mutants with `-k` where you need one, and judge by hand whether at
  least five of the new mutants (fit side and holdout side) test a real guard.

## Part 1: the 13 findings and section G
For each numbered finding of `handoff/N3b_qa.md`: CLOSED, PARTLY or OPEN, with file and line, and for
any finding that had a repro, rerun the repro at 0d8abb1 (finding 1 above all: the stub targets that
read `converged` far above the known minimum).

## Part 2: new work, fit side (Amendment 12, plan near line 1378)
1. `converged` must need S1 to S4 as `briefs/N3b2a_dev.md` states them, done by the project's own
   code; the library's stop flag must not decide it. Check text against code.
2. Try to break it: build your own stub targets beyond the committed study (two basins, a flat
   valley, a minimum on a box edge, a BER quantised to error counts, a noisy cost) and report how many
   read `converged` with a selected cost above the known minimum by more than the stated margin.
3. Does the amendment text determine the search completely (every option of the named library
   routine, the design, the seed, the difference step, the budget of 140 and what counts in it,
   including the final re-evaluation)? Is the budget enforced as a hard cap of at most 160?
4. The evaluation log: header binds the fit module and the fit script; replay recomputes the cost
   from recorded residuals; a lost point means +inf exactly; the final fresh re-evaluation must match
   bit for bit; a truncated last line is refused; the log SHA-256 is in the artefact checks; the change
   in `nanf_freeze.py` is the smallest that does this and every N3a test is green.
5. Points the orchestrator flags for your judgement:
   a. the stub offset moved from 0.1 to 0.5 dB: does any test get weaker?
   b. K-G changes a range-edge report width from 1e-9 to 0.01, which the brief did not ask for: is
      it only a report width, does it contradict an earlier rule, does it change any decision?
   c. two N3a test support files were edited for the new log-hash key: was any N3a assertion
      weakened or removed?
   d. one mutant is counted killed by a timeout: is that a real kill?
   e. an equivalent-mutant claim (the finite-residual check on replay) led to a guard being removed:
      is the claim right?
   f. the committed study ends 14 of 28 cases not converged: is the certificate sound but needlessly
      strict, and does the amendment say plainly what a not-converged run means and where it goes?

## Part 3: new work, C5 links and holdout runner (Amendment 13, the last section of the plan)
1. The Fig.1 row is widened to a fibre input of the C5 links. Check it against rules 1, 3 and 7 and
   B2, that the consequence is stated, and that no workbook value is committed anywhere (code,
   tests, handoffs, plan).
2. `declare_c5_links`: needs the pinned workbook hash; 17 wavelengths, three links each; D by the
   existing table rule with no extrapolation; 1630 and 1640 nm refused. Is "D at the wavelength, no
   slope applied" physically consistent with how the 1550 nm declared links are modelled, and does
   the recipe link at 1550 nm agree with or differ from the declared 1550 nm link (which one does
   each criterion use)?
3. The link check: `run_point` and `simulate_point` must refuse any link the recipe did not
   produce. The registry is module state: can a caller or a test fill it without a verified
   workbook, and what happens in worker processes when points run in parallel (is the registry
   empty there, and does that refuse valid links or admit invalid ones)?
4. Dev's readings, each to be checked against the plan text; say if the plan allows a second
   reading (the brief told the Dev to stop in that case):
   a. the C5 d is reported but does not enter the verdict (A2 and B3.3 read as naming C1 and C2 only);
   b. the back-to-back run at each wavelength doubles as the no-fibre run;
   c. the ROP of the back-to-back link comes from the NANF ROP column; no cap on ROP;
   d. the holdout count is 237 (84 + 153) while G9 states 336: is this a contradiction with earlier
      text or a different count of the same runs?
5. Verdict path with stub chain and synthetic workbook: only `overall_verdict` decides; a gate-poor
   rate with d above tolerance never prints a pass; NOT DISCRIMINATING shows with its rates; a lost C5
   point fails that link and never reads consistent; the B2B-copy C2 goes through `score_c2` with
   its max check; lost points are listed.
6. Marker rule: stated in the amendment with its limits, printed by the script. Report text keeps
   the required "not fully blind" sentence and the label LITERATURE BENCHMARK / CALIBRATION ONLY, and
   never claims validation.

## Part 4: limits and gates
- Both amendments are append-only (hash the plan prefix at each earlier length against the pins in
  `tests/test_nanf_benchmark.py`), each amendment commit holds only the plan and its test.
- No freeze record, artefact, evaluation log or marker exists. No test opens the real workbook or
  passes `include_holdout=True` on real data. No earlier-gate file changed in the range
  (`docs/benchmarks/FIT_HOLDOUT_PLAN.md`, `docs/benchmarks/teriphic_*`, `holdout.py`, `e2_*.py`,
  `e3_*.py`, `rates.py`, `published_points.py`, `comparison.py`, `E3_WIEGART_RAN.md`,
  `SOURCE_REGISTER.md`, `e4_*.py`). No skipped, expected-fail or placeholder test was added.
- Run in your clone: `tests/test_nanf*.py`, `tests/test_benchmark_provenance.py`, `ruff check`,
  `ruff format --check`, mypy. Report the counts.

## Verdict
Write `docs/orchestration/opticps-v2/handoff/N3b2_qa.md` in the MAIN repository (not the clone), at
most 70 lines: `verified_sha: 0d8abb1`, PASS or FAIL, the table of the 13 findings (one line each),
then numbered new findings with severity (BLOCKER, MAJOR, MINOR, OBSERVATION), file and line, and a
one-line repro. PASS means: no BLOCKER and no MAJOR, the fit (N3c) may start from this tip. State
which MINOR items, if any, must be fixed before the freeze because they touch files inside the code
identity (a later edit there relocks the holdout).

Return to the orchestrator only: PASS or FAIL, the counts by severity, the numbered findings in one
line each, the gate counts, verified_sha.
