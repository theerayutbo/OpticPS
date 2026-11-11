# E2c power-study design (Fable, 2026-11-11): before any R14 freeze and before any use of 10 km
Basis: `two_km_result.json` (476642bc, freeze R13 ce0ee73), `E2b_2km_{dev,qa}.md`, `b2b_model.yaml`, plan R12.2 to R12.4 and R13.1 to R13.4,
`power_study.yaml`, `e2_{model,metrics,score}.py`, `holdout.py`, `teriphic.py`, SOURCE_REGISTER. 10 km not read, hashed, opened or linked (stat unchanged).
## 0. What the 2 km record says (facts used; the R13.1 reading stands)
The FAIL is a level effect, not bandwidth or amplitude: the copy fails M1 (0.0298 against a B2B spread 0.0029); the control's M4 (0.72) is
inside its limit (1.22); M1 falls with the model noise factor (0.039, 0.028, 0.021 at x1, x1.5, x2.2) while M3 rises (0.044, 0.130, 0.220):
the 2 km gaps look to k-means like a noisier B2B, the tails do not. Amplitude ratio 0.832 (-0.80 dB). All below is a new hypothesis, H2.
## 1. Mechanism: decisions D1 to D5
D1. Candidate kept: a static memoryless receiver-side law on the photocurrent, on the whole received waveform before the receiver noise,
    y = f(A s(t) + n_opt) + n_rx, f(v) = v + b v^2 + a v^3 in B2B gap units, A the received amplitude (1 at B2B, 0.832 at 2 km, a scenario
    at 10 km). Seat: PD saturation or the scope front end (PD arrays into a real-time scope; no TIA named). Reason: the only candidate
    whose strength depends on received amplitude, so it predicts a third pattern from two. Parameters: p_TX (four TX levels, two free
    after the gain-invariant map), a, b, sigma_rx, sigma_opt. Two gap patterns (four numbers): p_TX and one law term are pinned with one
    check left; a and b together are exactly determined and the check moves to M2 to M4 at 2 km (the law also bends transitions and
    tails). Not pinned by two points: the shape beyond the cubic; so shape is a scenario family, polynomial (a, b) and tanh (scale,
    offset), collapsed by D11.
D2. Rejected as calibratable: a modulator sine transfer (TX side, fibre invariant, absorbed by the four free levels, predicts no B2B to 2 km
    change); a square-law or field dispersion term (acts and is identifiable at 10 km only, R13.1 item 1): a MODEL GAP, a nuisance truth (T5).
D3. Sign. A concave f releases at lower amplitude: at 2 km the top gap, or both outer gaps, widen relative to the mean; the noise-factor
    trend of section 0 is consistent with that. Step 0 (D7) measures the signed change; the opposite sign refutes D1.
D4. Extrapolation. The even term's pattern effect scales as A, the odd term's as A^2; first order, the 10 km shift from B2B at A 0.45 is 2.6
    to 3.2 times the 2 km shift (0.03 to 0.04): 0.08 to 0.12 gap units against an M1 limit of 0.018, and 0.05 to 0.08 from the 2 km pattern.
    The 10 km photocurrent range is a lower sub-range of B2B's (benign for saturation, not for a code clip or ADC non-linearity; Step 0 screens for a clip). Estimates, replaced by the study.
D5. Amplitude at 10 km without reading 10 km: same launch power, G.652.D loss 0.30 to 0.40 dB/km at 1310 nm, connectors absorbing the
    rest of the 0.80 dB seen at 2 km, gives A_10 in 0.40 to 0.48 (0.832^5 = 0.400, all-fibre bound). Launch power is UNKNOWN, so the family
    is A in {0.35, 0.45, 0.55, 0.65, 0.75, 0.85}, step 0.1 (half-step pattern error under half an M1 limit by D4); A = 1 is excluded, there
    law and no law coincide. The measured 10 km gain g_10 is used only as an applicability gate (outside 0.30 to 0.90: NOT APPLICABLE,
    no verdict) and is reported beside the survivors' A; it never fits a, b, p_TX or sigma. Testable in principle (band about one limit,
    wrong models three or more away); whether noise at A 0.45 blunts it is what the study measures (D12, D14).
## 2. The settings alternative: decision D6
D6. "Different instrument settings per session" is handled three ways. (i) Its one testable member is a truth family, T3: the 2 km pattern
    frozen and carried to 10 km. (ii) Step 0 looks for direct evidence: the quantisation step of the file values (smallest positive difference
    of sorted distinct values, both fit windows); a different step evidences a changed vertical setting and stops the study (S1); no code grid
    (the 2.048 THz axis is interpolated) is "not observable". (iii) The rest caps the claim: a 10 km PASS is "consistent with the law, not
    separable from a settings change that coincides with its prediction"; PARTIAL at most.
## 3. Protocol: decisions D7 to D14 (fixed here, before any run)
D7. Step 0, before any fit (2 km read as calibration, declared): on the B2B and 2 km evaluation and five study windows: centroids, signed
    gap pattern, cluster shares, per-cluster std, raw gain, window std in gap units, code step, extreme-value counts (clip screen: a repeated
    extreme over 0.1 % of samples). Viable iff the 2 km gap change exceeds 3 B2B spreads (known: 0.03 against 0.003), D3 sign, no clip, no code-step change.
D8. Windows and seeds. B2B as R13 (fit 0 for 8388608; spread 8388608, evaluation 16777216, 4194304 each); 2 km mirrors it exactly (its
    evaluation window is the one E2b read). Study windows, truth sources in both files: starts 12582912, 20971520, 25165824, 29360128,
    33554432; none overlaps fit, spread or evaluation. New seeds: fit 20261111, prediction symbols 20261112, prediction noise 20261113,
    pseudo-capture noise 20261114 plus window index, model-spread second seed 20261115. Fit windows fit, evaluation windows give misfit,
    spread windows give spread, study windows make truths; nothing else is read.
D9. Fit: joint Nelder-Mead on (p_TX, a, b, sigma_rx, sigma_opt) minimising R13's objective (M1+M2+M3+0.05 M4) summed over the B2B fit
    window at A 1 and the 2 km fit window at A 0.832 with D 0 (R12.4 reading 2). Pulse spectrum: B2B Welch as R13 (holds the law's harmonics
    at A 1; declared second order). Uniform independent symbols, zero chirp, zero phase: unchanged gaps. Profiles: b fixed 0, a fixed 0,
    both free, tanh. Rule R6: the fitted model's psi on the B2B and the 2 km evaluation windows is at most 1 under the R13 limits (it must
    explain what it was built to explain), else stop S2.
D10. Scenarios at 10 km: the R13 dispersion grid (21 values, 0 to 6.352) x A (six) x two coherent noise bounds, RX (receiver noise after
     fibre and law, unscaled by A) and OPT (optical noise scaled by A, through the fibre, before the law): 252 law scenarios. Controls, the
     competing hypotheses with the same freedom over the same D x A x noise: C-B2B (R13 levels, no law) and C-2KM (levels refitted on the 2 km
     fit window, no law): 504. Outcomes as R13: FAIL (no law survivor); PASS, NOT DISCRIMINATING (a control survives); PASS, DISCRIMINATING
     (a law survivor, no control survivor). Survivors' D and A are reported as a set, never claimed.
D11. Shape collapse: if polynomial and tanh predictions at A 0.45 differ by psi at most 0.5 under the E2c limits for every (D, noise), the
     polynomial alone is frozen; otherwise both families are scenarios (504 law, 1008 controls) and the study proceeds.
D12. Metrics and limits. M1 to M4 and their estimator ids unchanged. Limit_m(A, noise) = 2.0 x max(basis_m, spread_m(A, noise)): basis_m =
     max(misfit on B2B evaluation, misfit on 2 km evaluation, B2B spread, 2 km spread), the R10 formula with the second calibration point
     added; spread_m(A, noise) = the two-seed reproducibility of the model's own prediction at D 0 in that cell (a limit below the model's own
     reproducibility cannot be met; computed from the model alone). Multiplier, psi and the gain-invariant map unchanged; nothing from 10 km
     enters; the study reports how often the spread term binds.
D13. Truth families, five windows each, pseudo-captures from real windows as R12.4 (law inverted at the source amplitude, rescaled,
     cosine-filtered at 10 km, law re-applied at A; RX adds shaped noise so the receiver noise returns to sigma_rx, OPT adds none). T1 correct
     law, from 2 km windows: D {0, 4.5, 5.2, 6.352} x A 0.45 x {RX, OPT}, plus A {0.65, 0.85} at D 4.5, plus from B2B windows at D 4.5,
     A 0.45. T2 B2B pattern persists (no law), from B2B windows: D {0, 4.5} x A {0.45, 0.65, 0.85} x both noises. T3 2 km pattern persists,
     from 2 km windows: the T2 grid. Non-gating, reported: T4 law x2 and x0.5 (D 4.5, A 0.45, OPT); T5 square-law field dispersion, ER 6 dB
     as the R13.3 reproduction (D 4.5, 6.352; A 0.45; OPT); T6 Butterworth-4 45 GHz on T1 (D 4.5, A 0.45); T7 A 0.30 and 0.60 off the grid
     (D 4.5). 48 configurations, 240 captures; the prediction set is made once (768 syntheses, about 2 h).
D14. Decision rule. R1 power: every T1 gating configuration (A 0.45; D 0, 4.5, 6.352; each noise bound) ends PASS, DISCRIMINATING in at
     least 4 of 5 windows; D 5.2 is reported (the inherited off-grid caveat, R13.3 item 11). R2 false pass: every T2 and T3 configuration
     at A 0.45 ends PASS, DISCRIMINATING in at most 1 of 5 windows, and at most 4 of the 40 pooled. R3 reach: A* = the largest tested A
     (0.45, 0.65, 0.85) at which R1 and R2 hold at D 4.5; reported, pre-registered for R14 as "g_10 above A*: law NOT DISCRIMINATING by
     construction". S3 analytic separability, before any truth: at A 0.45 every law prediction has psi above 1 from both controls'
     predictions at the same (D, noise). WORTH_10KM iff Step 0 viable, R6, S3, R1 and R2 hold; anything else CLOSE_PARTIAL. No grid,
     limit, seed, family or threshold changes after any table is seen.
## 4. Declarations: decision D15 (verbatim in STUDY_PLAN.md and in every E2c output)
D15. (a) The 2 km file was read under R13 (one window) and is read in full in E2c; it is calibration data from now on and never again a
     holdout; its VALIDATION role in `ROLE_BY_NAME` and the config stays until R14 rebinds it (this phase edits no bound file). (b) R13's
     2 km FAIL stands as the result of the pre-registered test of H1 (the B2B-calibrated small-signal surrogate transfers); H1 is refuted
     at 2 km and no 10 km result can rehabilitate it. (c) H2 (D1) is a different hypothesis, formed after seeing 2 km; tested at most once,
     on 10 km, under an R14 freeze; if H2 fails, no third hypothesis gets a fresh holdout from this dataset. (d) Ceiling: VALIDATED is never
     returned; a 10 km PASS, DISCRIMINATING is PARTIAL, INCONCLUSIVE, confounded by a coincident settings change, a mild low-pass, chirp,
     wavelength, fibre type and the grid; the law's seat stays unidentified. (e) BER and SER stay REFERENCE_SEQUENCE_MISSING. (f) Limits,
     scenarios and rule use B2B and 2 km only; the 10 km file is not touched.
## 5. Deliverables and tests: decisions D16 to D18
D16. Code, new files only: `src/opticps/benchmarks/e2c_model.py` (law, inverse, synthesis via `e2_model.synthesize(sigma=0)` plus its own
     noises, joint fit); `e2c_calibration.py` (the declared 2 km route: opens only the registered 2 km name, verifies its SHA-256 against
     `teriphic.HOLDOUT_SHA256`, requires the committed R13 record with outcome FAIL as precondition, refuses the registered 10 km name and
     any other `data/external` path before any open, hashes no other file); `e2c_study.py` (scenarios, controls, limits, truths, outcomes,
     the D14 rule as pure functions); `scripts/power_study_e2c.py`, steps `step0`, `fit`, `predict`, `power`, `decide`. Not edited: the 12
     code-identity files, `scripts/score_teriphic_e2.py`, `FIT_HOLDOUT_PLAN.md` (hash pinned by R13), the R13 criterion,
     `configs/benchmarks/teriphic_pd1_pam4.yaml`, everything in `teriphic_e2/`. Append-only: `FREEZE_GUARD_KNOWN_LIMITS.md`.
D17. Documents in `docs/benchmarks/teriphic_e2c/`: `STUDY_PLAN.md` (D1 to D15 and D19, committed before `fit` runs; its SHA-256 and commit
     recorded in every output), `step0_diagnostics.yaml`, `law_model.yaml` (fitted values, windows, seeds, profiles, code identity of the new
     modules), `power_study_e2c.yaml` (per-configuration counts, limits, spread-term statistics, A*, the rule evaluated line by line,
     `decision`), `NOTICE.md` (attribution pointer). Each artefact is written once by its step; a re-run that changes bytes gets a new version
     suffix, never an edit in place, so an R14 freeze can bind them as inputs. No criterion file, no `CRITERION_PATH` change, no R14 scenario
     list, no stage contract: R14 decides those after the owner reads the table. Handoff `handoff/E2c_dev.md` (commands, hashes, access
     times of all three files, compute time); review `E2c_qa.md` by the other model.
D18. Tests in `tests/test_benchmark_e2c.py`, fixtures only: the law is identity at zero and monotone on the fit range; the inverse recovers
     the input; known coefficients are recovered by the joint fit on synthetic windows; the fit reads fit windows only (offset audit); the
     calibration route refuses the 10 km name before any open (open and spawn hook, 0 events), opens only the registered 2 km file with its
     hash, and needs the committed R13 record saying FAIL; limits take the larger of basis and model spread times two; a control survivor
     makes a pass NOT DISCRIMINATING; controls span the whole D x A grid; the decision rule as pre-registered (4/5 passes, 3/5 fails, pooled
     5 of 40 fails); truths come from study windows only; no R13-bound file changed (`bind_to_freeze` at HEAD against ce0ee73 plus the plan
     hash). Mutants, new `scripts/mutate_e2c.py`: `law_not_applied`, `controls_omitted`, `rule_threshold_relaxed`,
     `evaluation_window_used_in_fit`, `ten_km_name_not_refused`, `spread_term_dropped`; all killed.
## 6. Stop conditions: decision D19 ("do not spend 10 km; close E2 at PARTIAL")
D19. S1 Step 0 not viable (wrong sign, a clip, a code-step change, or a 2 km change within 3 B2B spreads). S2 the fitted law does not bring
     both evaluation windows within the R13 limits (R6). S3 the law predictions at A 0.45 are not separable from a control by construction.
     S4 R1 fails under either noise bound, or R2 fails. Any stop is recorded as `decision: CLOSE_PARTIAL` with the failed line, committed and
     reviewed; the 10 km file stays unread for a future, differently designed hypothesis. Closing text: "H1 refuted at 2 km (R13, FAILED); H2
     formed post hoc; the power study could not make a 10 km test that discriminates; claim PARTIAL; 10 km unspent." WORTH_10KM only
     entitles the owner to design R14; it is not a freeze.
## Implementation checklist (in order)
1. Commit `teriphic_e2c/STUDY_PLAN.md` and `NOTICE.md` first (D14, D15, D19 verbatim). 2. `e2c_calibration.py` and its refusal tests under
   the open hook; record the 10 km access time before and after. 3. `step0`; commit `step0_diagnostics.yaml`; apply D7 and D6(ii); stop on S1.
   4. `e2c_model.py`, fit, profiles (D9); R6; commit `law_model.yaml`. 5. `predict` in the background (D10, D12 spread cells); S3, D11; record
   the frozen shape set. 6. `power` in the background (D13). 7. `decide`: the D14 lines into `power_study_e2c.yaml`, committed once. 8. Known-
   limits paragraph, handoff, review with the hook replayed and every hash recomputed. 9. The owner reads the table and decides on R14.
