# E2c advice (Fable, 2026-11-11): after CLOSE_PARTIAL at S2. Read-only; nothing edited; 10 km not touched.
Basis: `teriphic_e2c/{STUDY_PLAN.md (A1), step0_diagnostics.yaml, law_model.yaml, power_study_e2c.yaml}`, `handoff/E2c_dev.md`,
`teriphic_e2/two_km_result.json`, `e2c_model.fit_law`, `tests/test_benchmark_e2_freeze.py`, `holdout.require_frozen_criterion`. Numbers below
that are mine: the tanh optimum's cubic Taylor equivalent is a -0.0018, b -0.0379 (b = -k tanh(o), a = -k^2(1 - 3 tanh^2 o)/3).

## 1. Close or re-run: the S2 stop is an artefact, a re-run is legitimate, and I still advise closing (section 2 is why)
The defect is outcome-blind: a full model with an objective (0.1930) above both nested profiles (0.1911, 0.1908) is impossible at an optimum,
and would be flagged with tanh deleted from the table. A1's restarts stopped on their own 1e-4 rule (poly runs 0.19359, 0.19296, 0.19296):
the same simplex, from the same point, re-converges to the same stall; the tanh-equivalent point (b -0.038) is four simplex steps from the
poly start and was never visited. So S2 did not fire on the data. Re-running under a pre-registered amendment that fixes only the search is
standard protocol-deviation practice, not a fork: a fork inflates a positive claim, and nothing here touches the claim's arbiter (10 km).
The honest residue is one asymmetry: we would re-run only because the stall was noticed, and it was noticed loudly because tanh passed.
That residue is disclosed, not argued away. The verdict of record for v1 stays `CLOSE_PARTIAL, S2`; a v2 never overwrites it.
A2 MAY change: the optimiser's starts, initial simplex steps, screening and acceptance (section 3); output files get a `_v2` suffix.
A2 MAY NOT change: the model of record (poly stays), the objective, parameters, profiles, windows, fit seed 20261111, fit_samples, the
R13 limits, R6 (psi <= 1), S3, R1 (4 of 5), R2 (<= 1 of 5, <= 4 of 40), D11's 0.5, D12, truth families, D or A grids, verdict names.
Tanh must not become the model of record. A "lowest verified objective" rule is R6-blind but would be written in the one world where it
rescues the verdict, and D1 gave tanh the scenario-family role (D11), not a calibration fallback. If the corrected poly fails R6, E2 closes
at S2 for real and tanh stays report-only; this is said in A2 before the run. Disclosure: A2 appended to STUDY_PLAN.md in its own commit
before any v2 step (SHA in every v2 output); `law_model_v2.yaml` carries `amendments: [A1, A2]` and `prior: v1 CLOSE_PARTIAL S2, optimiser
stall`; the known-limits paragraph, the handoff and the closing text say A2 was written after v1 was seen and what it did and did not change;
the Sonnet reviewer's true optimum is recorded in `E2c_qa.md` as evidence and is NOT used as a v2 start (starts are a deterministic grid).

## 2. The code grid: it is evidence of a changed vertical setting, and under the design's own definition it is S1
Step 0: B2B fit window 21161 distinct values, step 1.732e-6, largest off-grid 0.009 (observable); 2 km 25319 distinct values, smallest step
1.172e-6, largest off-grid 0.107 ("not observable" under I10's 1 % tolerance). Two independent statistics agree: the step ratio is 0.676 and,
with the 2 km signal 0.832 times B2B's, a 0.676 step predicts 1.23 times the distinct values; observed 1.20. An off-grid residual of 0.107 is
what float32 rounding gives at this step (ULP/step 0.20): the 2 km file is on a grid, finer and less regular, not off any grid. Reading: the
vertical scale or the export scaling differed between sessions; this is exactly what D6 (ii) was written to catch. D6 (ii) defines the step
as the smallest positive difference, so by the design's text S1 fired at Step 0, before any fit; I10's observability test (a reasonable guard
against a spurious smallest difference) under-read it. The mechanical verdict stays S2 because I10 was the executable rule; the record should
say both. Closing on S1-by-design is the conservative direction, and declining to spend a holdout is never a forking path.
Does it make 10 km uninformative? One-sided, not void. D1's seat is "PD saturation or the scope front end": a PD law is setting-invariant and
stays testable; a front-end law changes with the range, and the 10 km capture was most likely re-ranged again (signal about 0.45). So a FAIL
no longer separates "law wrong" from "settings changed again"; a PASS, DISCRIMINATING is mild evidence (band about one limit; likelihood
ratio of order 3 to 10) for a setting-invariant seat; the D15 (d) ceiling, PARTIAL and confounded, is now evidenced rather than hypothetical.
Two legitimate ways to sharpen it, neither a data fork: (a) dataset metadata (Zenodo 7886498 README, or the authors) stating per-capture
vertical settings; (b) an R14 line that reads the 10 km code step as a pre-registered covariate, reported, never gating.

## 3. If re-running: Amendment A2, minimal
Optimiser only, in `e2c_model.fit_law` plus the driver. (1) Starts: poly, a in {-0.03, 0, 0.03} x b in {-0.05, 0, 0.05} plus the two nested
optima (11); poly_b0 a in {-0.03, 0, 0.03}; poly_a0 b in {-0.05, 0, 0.05}; tanh o in {-0.4, 0, 0.4} at k 0.1; one identity-law base
(q, sigmas only). The grid is set by D4's scale (a 0.03 gap-unit shift needs |b| about 0.04), not by any v1 value. (2) Steps: a 0.02, b 0.03,
others as I5. (3) Screen each start at maxfev 200; the best two per profile get the full A1 restart sequence. (4) Acceptance, all result-blind,
any failure = "fit INVALID, S2 not evaluable" (neither CLOSE_PARTIAL by R6 nor WORTH): obj(poly) <= min(obj(poly_b0), obj(poly_a0)) <=
obj(identity) and obj(tanh) <= obj(identity), within 1e-6; the reported optimum is the minimum over every start and restart; a final fresh-
simplex restart from it improves by < 1e-4; at least two distinct starts end within 1e-3 of it. The nested check becomes a permanent test.
(5) R6 as I6 on the corrected poly; then predict, power, decide unchanged. If R6 fails: CLOSE_PARTIAL at S2, final; no third optimiser, no
model switch. Cost: about 21 screens plus 8 full runs, about 3 to 4 h wall on 4 workers; predict about 2 h; power about 1 h.

## 4. The stale test (`test_the_10km_stage_is_not_frozen_yet_and_no_result_exists`; the file is not identity-bound)
Only one assertion is stale: `not TWO_KM_RESULT_PATH.exists()`. Minimal change: rename to `..._is_refused_after_the_2km_fail_and_no_10km_
result_exists`; replace that line with: the record exists, its bytes equal HEAD, `outcome == "FAIL"` and `carry_forward == []`; keep
`SELECTED_PATH` absent, `registered["results"] is None`, and the existing NOT_FAILED raise (selected_scenario missing); add
`pytest.raises(holdout.StageRefused, match="2 km stage FAILED")` for `validation_stage=ValidationStage.FAILED`; add `assert not list((ROOT /
"docs/benchmarks/teriphic_e2").glob("*10km*"))`. It then protects what is true: the 10 km stage is refused on both declared stages, nothing is
carried, and no 10 km result or selection exists. One commit, touching only the test; not part of A2.

## 5. D12 for any R14
Keep the basis extension (2 km evaluation misfit in `basis_m`): it is the R10 formula with the second calibration point and needs no defence.
Keep the model-spread term only if a completed power study shows it binds in at least one gating cell, and then with a pre-declared seed set
(the max over three pairs; one pair is a noisy estimate), and with a NOT APPLICABLE rule: if spread_m > 2 basis_m in a cell, that cell has no
power and says so, rather than widening the limit until nothing can fail. Why keep it at all: at A 0.45 the k-means M1 can jump between seeds,
making false FAILs of the law and false survivors of the controls; the term is model-only (no 10 km leakage) and symmetric for law and
controls, so by itself it cannot manufacture a DISCRIMINATING pass. If no power study is completed, there is no R14 and the term lapses.

## 6. Recommendation
Close E2 at PARTIAL now, with a corrected record: the S2 stop was an optimiser stall (state the nested-objective violation, the reviewer's
true optimum and tanh's R6 as evidence that H2's calibration is not refuted at 2 km), and the substantive reason to stop is Step 0's code-grid
evidence of a per-session settings change, S1 under D6 (ii)'s own step definition; replace the closing text's "could not make a 10 km test
that discriminates" with "was stopped before the power computation" so it stays true. Cost: 1 to 2 h, roughly 80 to 120k tokens (closing
text, known-limits amendment, the test fix, one review). The A2 re-run is legitimate and fully specified above, but under the evidenced
confound it buys a power table with a PARTIAL ceiling for roughly 0.5 to 0.7M tokens and 1 to 2 days, plus about 0.5M more and a day if R14
follows; take it only if the owner wants the power table as a methods result, or if dataset metadata first shows the vertical setting did not
change. The 10 km capture stays unspent for a hypothesis designed around the settings confound.
