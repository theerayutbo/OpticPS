verified_sha: 0d8abb1
# N3b-2 QA (Loki): re-review of the N3b fix round, range e9c5260..0d8abb1 (fix units 2a and 2b)
VERDICT: PASS. BLOCKER 0, MAJOR 0, MINOR 5, OBSERVATION 4. The fit (N3c) may start from this tip.
Every repro ran in a scratch clone on stub chains and synthetic inputs. No real data was read. No fit ran on real data. No record, artefact, log or marker was made.

## Earlier findings (handoff/N3b_qa.md)
| # | Status | Evidence |
|---|---|---|
| 1 BLOCKER stall read as converged | CLOSED | `converged` needs S1 to S4 in project code, and the library's status is never read (`nanf_fit.py:457-479`). Repro rerun on 24 stub targets of my own, including the stub at its old offset of 0.1: 5 converged, 0 above the margin, worst 1.016 |
| 2 MAJOR log does not bind the fit | CLOSED | The header has the module and script SHA and the library versions (`nanf_fit.py:520-529,588-595`). Replay recomputes the cost (`:602-613`). The selected vector is evaluated fresh (`:637`). The log SHA is in the checks (`:670`). Repro (b): edited cost of eval 28 refused. Consistent edit of design point 20: refused |
| 3 MAJOR C5 open past the freeze | CLOSED | Recipe `nanf_chain.py:575-597`, link check `:737-739`, runner `nanf_holdout.py:323` |
| 4 MINOR verdict bypass | CLOSED | `verdict_of` calls only `overall_verdict` (`nanf_holdout.py` verdict_of). Gate-poor, NOT DISCRIMINATING and lost-C5 tests pass |
| 5 MINOR B2B-copy C2 | CLOSED | `score_c2` is applied to the bracketed ROPs with the max check, and the unbracketed ROPs are listed (`nanf_holdout.py` score_holdout) |
| 6 MINOR damping text vs code | CLOSED | Ladder and refresh now agree with K-B.4 to K-B.6. One new divisor mismatch: see new item 4 |
| 7 MINOR J-A vs A3/F2 | CLOSED | K-A (plan 1389-1396) |
| 8 MINOR two guards with no test | CLOSED | Reran L17 (count-only grid): killed by the -0.5 dB shift. Reran L2 (single lost point not +inf): killed |
| 9 MINOR marker not bound to git | CLOSED | Process rule in L-D (plan 1608-1618). The script prints it, and not after a refusal |
| 10 OBS curve_arrays | STANDS | Unchanged and still harmless |
| 11 OBS default read | CLOSED | Named in K-F |
| 12 OBS cut last line | PARTLY | A line cut inside its text is refused. A line that lost only its newline is not refused: see new item 3 |
| 13 OBS np.clip mutant equivalent | STANDS | |

## New findings
1. MINOR. The certificate is sound but strict, and a NOT CONVERGED outcome on the real chain is likely. Cause: a forward difference at an interior SNR maximum gives a bias, so S2 sees a slope that is not there (`nanf_fit.py:368-394,442-455`, plan K-B.5/6). Evidence: on my 24 stub targets, 5 converged, and the stub at its original offset of 0.1 ends at 1.030 with no convergence. That explains the 0.1 to 0.5 change (5a). On noisy targets, 0 of 16 converged. The plan says plainly what a not-converged run means (K-B.8, K-D). Nothing is wrong or unprotected. The owner should know this before N3c, and any change needs an amendment before the fit. Repro: loki p1_finding1.py, p2_adversarial.py noisy.
2. MINOR. Only a calibrated run has a commit rule for the log (plan K-E.4, `scripts/nanf_fit.py:45`). The log of a NOT CONVERGED run (item 1) may stay uncommitted. A fresh clone or a deleted log then allows a silent second run (K-E.6). Fix: the N3c brief requires committing the log whatever the status, and the script prints that. These files are outside the identity.
3. MINOR. A log whose last line lost only its newline is accepted (`nanf_fit.py:532-547`). The resume appends onto the same line and still ends CALIBRATED with an artefact. The log whose hash that artefact records then cannot be read again ("not a resume"). Repro p2_log.py (a): the first resume is CALIBRATED with a log that differs from the reference, and the second resume is refused. Fix before the fit: refuse a file that does not end with a newline.
4. MINOR. Text and code differ on the difference step. K-B.5 (plan 1416) divides by d_i = 0.01. The code divides by the float difference v_i - x_i (`nanf_fit.py:454`). A second implementer would get other Jacobian bits and so another evaluation sequence. Fix the code or the wording before the fit (fit module, outside the identity).
5. MINOR, must be closed BEFORE THE FREEZE. The C5 recipe has never run on the real Fig.1(a) curves. Nothing committed shows that their knots reach down to 1460 nm (plan 360 gives only the 1625 nm end). The recipe refuses extrapolation (`nanf_chain.py:591`), so a short curve raises at the holdout read, after the marker. A fix to `nanf_chain.py` then relocks the record. Close: before the freeze, call `declare_c5_links` once on the default non-holdout read (Fig.1 is in the calibration partition, rule 1/G6) and record that it built 51 links. Print counts only.
6. OBSERVATION. At 1550 nm the C5 recipe takes D from the Fig.1(a) curve, while C1 to C3 use the stated D of J-E.3 (`nanf_chain.py:548-551` vs `:590-594`). L-B.2 settles the C5 choice but does not say that the two links differ. Physically the two are consistent: one D at the carrier and no slope in both, and the model uses the wavelength only to place D.
7. OBSERVATION. The freeze writer neither checks the log hash against the committed log nor includes the log in its dirty-path list (`nanf_holdout.py:121`). Process only, as K-E.5 allows. If a check is wanted, add it before the freeze (identity).
8. OBSERVATION. `fit(budget=...)` has no upper bound, and the validator has none either. The script uses the default of 140, the header binds the budget, and the search is cut at budget minus 1 (`nanf_fit.py:418,626`).
9. OBSERVATION. The recipe registry is per-process state. The holdout runner is serial and in-process (`nanf_holdout.py:316-323`), so the registry is filled where the runs happen. A future spawn-based pool would hit a KeyError in `declared_link`, which fails closed and never admits a link. A caller can fill the registry only through a private name or a hand-built workbook object (L-B.8, class of H-F).

## Part 2 and 3 judgements
- Breaking `converged`: 88 cases of my own (two basins, a straight flat valley, a hard flat valley, a curved valley, Rosenbrock, box edges, correlated box edges, quantised BER, frozen noise and the 24 stub targets). 48 converged and 0 converged above the 10 percent margin; the worst converged ratio was 1.056. The text determines the search except for item 4. The cap is 139 + 1 (`nanf_fit.py:59-60,626`), below 160.
- 5a: no test got weaker. The minimum stays at the target, and the calibrated-path tests need a converging stub. 5b: K-G changes a report width only. B4.1 (plan 398) still holds and no decision changes. 5c: the two N3a files only gained the key; no assertion was removed. 5d: the timeout kill is real. Without the stall rule, memoised rounds loop forever and never touch the budget. 5e: the equivalence holds. A NaN or inf residual makes the recomputed sum NaN or inf, which differs from any finite recorded cost, and inf with residuals is refused at `nanf_fit.py:608`. The guard's removal is sound. 5f: see item 1.
- Fig.1 row (L-A): the rules 1/3/7/B2 consequence is stated. No workbook value appears in the range: the stubs are made up, and -4.99/-4.98 were already in D1. 4a: one reading (A2 plan 207-208, B3.3 379). 4b: consistent with B3.1/D3.2 (same vector, ROP, index; the B2B run does not use the wavelength). 4c: A3 245 sets the B2B ROP from ROP@NANF, and D1 509 says no cap or rounding. 4d: G9 (921-924) is a cost estimate over all 11 ROPs with separate no-fibre runs. 237 counts the scored points with reuse. That is a different count, not a contradiction. Marker rule and report texts: present, and no claim of validation.
- Part 4: the plan up to e89957b, c8c6d8c and f29734c is a byte prefix of the tip. The pins 3ed57c6e, f89c3f21 and 3651a118 match. Each amendment commit holds only the plan and `tests/test_nanf_benchmark.py`. No earlier-gate file changed. No record, artefact, log or marker exists. No skip, xfail or placeholder was added.

## Gates (clone at 0d8abb1, data absent)
- tests/test_nanf*.py: 725 passed, 4 skipped (data). Provenance guard: 367 passed, 1 skipped.
- ruff check: clean. ruff format --check: 271 files clean. mypy: no issues in 75 files.
- Targeted mutants, killed 7 of 7: L17 and L2 (finding 8), and new guards S4 dropped, replay trusts the cost, re-evaluation reuses memo, C5 check accepts any link, and C5 discriminating at a poor gate. Each tests a real guard. L2 is killed by the ValueError that was the earlier stated behaviour.
