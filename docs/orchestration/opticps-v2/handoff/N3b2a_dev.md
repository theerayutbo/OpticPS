# N3b-2a Dev handoff: fix round, fit side (Amendment 12). Base e9c5260; no fit run, no data read.
Commits: c8c6d8c Amendment 12 and pin move (plan and test only); f99bae8 code, tests, mutants; this handoff.
Not touched: nanf_holdout.py, scripts/nanf_holdout.py, DECLARED_LINKS, holdout tests, nanf_chain/scoring/import.

## Files touched
- plan: Amendment 12 appended (K-A to K-F and H-Z); `tests/test_nanf_benchmark.py`: pin moved, Amendment 12 test
- `src/opticps/measurement/nanf_fit.py`, `scripts/nanf_fit.py`, `scripts/mutate_nanf.py`
- `nanf_freeze.py` (A2.5 only): `CHECKS_KEYS` gains `evaluation_log_sha256`; `_check_checks` wants 64 hex chars
- tests new: `nanf_fit_study.py`, `test_nanf_n3b_fix.py`, `test_nanf_n3b_study.py`; edited: `test_nanf_n3b_fit.py`
- fixtures: `nanf_freeze_support.py` and two dicts in `test_nanf_n3a_review2.py` carry the new key (no assertion changed);
  `nanf_fit_stub.py` offset 0.1 to 0.5 dB (a relative tolerance cannot converge near a zero minimum)

## Amendment 12 choices
- tau 0.05 (S2 to S4); move bound 0.15 in u; difference step 0.01 (forward, backward at the upper edge)
- library: SciPy `least_squares`, trf, ftol=xtol=gtol=0.01, exact solver; its status is never read; S1 to S4 are our code
- budget 140 total (139 search + final re-evaluation); slowest converged case 136; 159 gives the same 14
- false-convergence margin 10 percent (2 tau); worst converged ratio seen 1.018
- also: log header binds fit module, script, numpy and scipy versions; replay recomputes costs; edge report width 0.01

## Stub study (stub chain only; `.venv/bin/python tests/nanf_fit_study.py`)
28 cases (14 targets x continuous/quantised): 14 converged, 14 not (11 stalled at the certificate, 3 budget);
false convergence 0; worst converged ratio 1.018; not-converged cases end within 1.030 of the minimum.
Library off (test does it): certificate alone reads converged in 7 of 28, worst 1.055, none above margin.

## Gates (tip f99bae8 plus this file)
- NANF tests: 693 passed (`tests/test_nanf*.py`); provenance guard: see the report; ruff check and format --check clean; mypy clean
- fit-side mutants, scripts/mutate_nanf.py logic on the three new n3b test files (full list left to the orchestrator):
  53 of 53 killed (51 `fit:` and 2 `freeze:`); the "stall rule dropped" mutant is killed by a hang (timeout), not a failing test
- one declared equivalent: explicit finite-residual check on replay (NaN changes the recomputed cost anyway); removed
- `mutate_nanf.py` now prints each outcome as it ends, keeps the summary line and exit codes, and kills a hung run (30 min)

## Things to know / for the reviewer
- The tested step of S2 is a Levenberg-damped step bounded by 0.15; three variants were tried (Marquardt scaling, a bounded
  least-squares step, this one). Marquardt gave 28 of 28 converged but its certificate alone falsely converged; the bounded
  step almost never converged. This one has no false convergence with or without the library; it converges on half the stub.
- The forward-difference Jacobian is biased where the residual does not vanish, so a real not-converged is likely: it goes to the owner.
- Resume on another machine or SciPy refuses (header binds versions): by design.
- Edge report: the library keeps iterates inside the box, so J-C.1 width 1e-9 became 0.01 (K-G).
- Stopped on: nothing. Findings 3, 4, 5, 9 left for N3b-2b.
