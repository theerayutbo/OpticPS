# E2c power study: study plan (committed before the `fit` step runs)

Status: pre-registration of a power study. Not a criterion, not a freeze, not a stage contract. It decides only
whether the owner may design an R14 freeze that spends the 10 km TERIPHIC file (`WORTH_SPENDING_10KM`) or whether
E2 closes at PARTIAL with the 10 km file unspent (`CLOSE_PARTIAL`).

- Design: `docs/orchestration/opticps-v2/questions/E2c_power_study_fable.md` (Fable, 2026-11-11), commit `99ce4f5`,
  SHA-256 `b5679638cec690ba0d17918a0b03220525e2f8980608256f9a74e0fcd8dbf59e`. Sections 0 to 4 and 6 (D1 to D15, D19)
  are copied verbatim below; D14, D15 and D19 are the binding text. D16 to D18 (code, documents, tests) are in the design.
- R13 freeze `ce0ee732af1111c67d94943ad985469dea8c8389`; 2 km record `docs/benchmarks/teriphic_e2/two_km_result.json`,
  SHA-256 `476642bc79cbc5b8634499fb8361bef0bf28d6e546a146d46232124cd765d9c5`, outcome FAIL.
- The 10 km file `50G_PAM4_PD1_10km_Subassembly1.bin` is not read, hashed, opened or linked by anything in E2c. Only its
  access time is recorded (metadata, before and after), as the design's checklist asks.
- Every E2c output records the SHA-256 of this file and the commit that added it.

## Decision on D12 (Aria, coordinator), recorded before any fit

The per-scenario model-spread term of D12 (`spread_m(A, noise)`, the two-seed reproducibility of the model's own
prediction) is approved FOR THIS STUDY ONLY, because it uses model-only quantities. It is a STRUCTURAL CHANGE to the
R10/R13 limit formula (basis times 2.0). It is NOT settled for R14: it needs explicit owner approval before any R14
freeze may use it. The study reports how often the spread term binds, so the owner can judge it.

## Verdict names

The design names the positive verdict `WORTH_10KM`; the coordinator's order names it `WORTH_SPENDING_10KM`. The output
uses `WORTH_SPENDING_10KM` (same meaning: the owner may design R14; it is not a freeze). The negative verdict is
`CLOSE_PARTIAL`, always with the stop condition (S1 to S4) and the failed line.

## Decision rule and stop conditions, fixed here (summary of D14 and D19; the verbatim text below binds)

- Step 0 viable (D7, D6 ii), else S1.
- R6: the fitted polynomial law model has psi <= 1 under the frozen R13 limits on the B2B evaluation window (A 1) and
  on the 2 km evaluation window (A 0.832), else S2.
- S3: at A 0.45, every kept law prediction is at psi > 1 (E2c limits of that cell) from both controls' predictions at
  the same (D, noise), else S3 fires.
- R1 power: each of the six T1 gating configurations (2 km windows, A 0.45, D in {0, 4.5, 6.352}, noise RX and OPT)
  ends `PASS, DISCRIMINATING` in at least 4 of its 5 windows, else S4.
- R2 false pass: each of the eight T2 and T3 configurations at A 0.45 (D in {0, 4.5}, noise RX and OPT) ends
  `PASS, DISCRIMINATING` in at most 1 of its 5 windows, and at most 4 of the 40 pooled, else S4.
- `WORTH_SPENDING_10KM` iff Step 0 viable, R6, S3, R1 and R2 all hold. Anything else: `CLOSE_PARTIAL`.
- Order of evaluation and stopping: step0 (S1 stops), fit (S2 stops), predict (S3 stops), power (S4). A stop ends the
  run at that step: later steps are not run, and `decide` records the first condition that fired.
- No grid, limit, seed, truth family, threshold or rule is changed after any table is seen. A design flaw found
  mid-run stops the study and is reported; it is not patched.

## Implementation declarations, fixed before any step runs

These make the design executable. Where the design is silent, the choice is stated here, before Step 0.

I1. Laws. Polynomial `f(v) = v + b v^2 + a v^3`. Tanh `f(v) = (tanh(k v + o) - tanh(o)) / (k (1 - tanh(o)^2))`
    (identity at k -> 0; f(0) = 0, f'(0) = 1; k is used as |k|). v is in B2B gap units (I2). A law is used only where
    f' > 0 on every sample it is applied to; otherwise the fit objective is 1e9 and a synthesis or inversion refuses.
    Inversion: Newton from u = x, at most 60 iterations, refused unless max |f(u) - x| <= 1e-9.
I2. TX levels and the gap unit. p_TX = g_ref * centre([-1.5, q1, q2, 1.5]) with q1, q2 free (two free levels after the
    gain-invariant map), centre() removing the mean, and g_ref = (L4 - L1) / 3 of the R13 pulse levels of
    `teriphic_e2/b2b_model.yaml` (so v = 1 is one R13 pulse-level gap, about one B2B gap at the output). Start q1, q2 at
    the R13 levels mapped the same way.
I3. Synthesis. The noiseless pulse train is `e2_model.synthesize(model, sigma=0)` with the R13 B2B Welch pulse spectrum
    and levels p_TX, dispersion D over L km (L = 0 at B2B and 2 km, L = 10 for scenarios). Then
    v = A (s_D + n_opt), y = f(v) + n_rx. n_opt is B2B-shaped Gaussian noise of standard deviation sigma_opt, filtered by
    the same dispersion response; n_rx is B2B-shaped noise sigma_rx added after the law. Noise generators:
    `e2_model.shaped_noise` with integer seeds derived as `SeedSequence([seed, stream]).generate_state(1)` (stream 1 =
    n_opt, stream 2 = n_rx), so one declared seed gives two independent noises. Every window is compared through the
    gain-invariant map (`e2_score.window_summary`).
I4. Noise bounds (D10). RX: the fitted split (sigma_opt optical, sigma_rx receiver). OPT: all fitted noise optical,
    sigma_opt' = sqrt(sigma_opt^2 + sigma_rx^2), sigma_rx' = 0.
I5. Fit (D9). Nelder-Mead minimising the sum over the B2B fit window (A 1) and the 2 km fit window (A 0.832) of the R13
    objective M1 + M2 + M3 + 0.05 M4 between the window's gain-invariant summary (whole fit window, 8388608 samples)
    and that of a synthetic window of 1048576 samples (symbols seed 20261111, noise seed 20261111 streams 1 and 2), RX
    split. Parameters: (q1, q2, a, b, sigma_rx, sigma_opt) and the profiles b = 0, a = 0, both free (THE polynomial,
    the model of record), tanh (k, o in place of a, b). Start: q from R13, a = b = 0, k = 0.05, o = 0, sigma_rx =
    sigma_opt = R13 noise_sigma / sqrt(2). Initial simplex steps: q 0.02, a 0.01, b 0.01, k 0.1, o 0.05, sigma 0.03.
    maxfev 600, xatol 1e-4, fatol 1e-6. The 2 km amplitude is A = 0.832 as the design states (not refitted).
I6. R6. psi of the polynomial model (RX split, D 0, prediction seeds, 4194304 samples) against each evaluation window,
    under the frozen R13 limits. Tanh's R6 psi is reported only.
I7. Controls (D10). C-B2B: the R13 model of `teriphic_e2/b2b_model.yaml` unchanged (levels, noise, spectrum), source
    amplitude 1. C-2KM: the frozen R13 fitting procedure `e2_model.fit_b2b_model` re-run unchanged on the 2 km fit
    window (B2B-normalised, fit seed 20261111); its levels, noise and spectrum come from that window; its source amplitude
    is the 2 km fit window's own mean gap. Read: "levels refitted on the 2 km fit window" is this procedure; it gives the
    control its own 2 km spectrum, which can only help the control (conservative for S3 and R2). Controls have no law.
    At scenario amplitude A the control signal is scaled by A / (source amplitude); its noise sigma_c is split as the
    law: RX bound sigma_c sqrt(phi) optical (scaled, through the fibre) and sigma_c sqrt(1 - phi) receiver (after the
    fibre, unscaled), phi = sigma_opt^2 / (sigma_opt^2 + sigma_rx^2) of the polynomial fit; OPT bound all optical.
    Controls share the prediction seeds. The design's "504 law, 1008 controls" if D11 keeps both shapes: controls carry
    no law, so they do not depend on the shape; 504 control predictions are scored in either case.
I8. Seeds. Prediction symbols 20261112, prediction noise 20261113 (streams 1, 2). Model-spread second draw: symbols
    20261115, noise 20261115 (streams 1, 2). Pseudo-capture noise: `e2_model.shaped_noise` seed 20261114 + window index
    (0 to 4). Fit 20261111 (I5, I7).
I9. Limits (D12). basis_m = max(misfit B2B evaluation, misfit 2 km evaluation, B2B spread, 2 km spread). Misfit: the
    polynomial model of I6. Spread: evaluation window against spread window of the same file (both gain-invariant).
    spread_m(A, noise) = metrics between the polynomial prediction at D 0 with the prediction seeds and with the second
    draw (I8), at that A and noise bound. Limit_m(A, noise) = 2.0 x max(basis_m, spread_m(A, noise)). psi as R13.
    Controls are scored under the limits of their own (A, noise) cell.
I10. Step 0 (D7, D6 ii). Windows: B2B and 2 km evaluation (16777216), spread (8388608), the five study windows; fit
    windows (0) for the code step and the clip screen. Per window: centroids (B2B-normalised), signed gap pattern (the
    three gaps of the gain-invariant window minus 1), cluster shares, per-cluster standard deviation in gap units, raw
    gain (mean gap in B2B-normalised units), window std in gap units, extreme counts. Clip: the window maximum or minimum
    repeated in more than 0.1 % of its samples. Code step (raw file values, fit windows): distinct sorted values, the
    smallest positive difference; a grid is observable iff there are at most 65536 distinct values and every positive
    difference is an integer multiple of the smallest within 0.01; a step change is a relative difference above 1 %
    between two observable steps; otherwise "not observable" (no stop). Viable iff (V1) the 2 km gap change, max over
    the three gaps of |gap_2km_eval - gap_B2B_eval| (gain-invariant), exceeds 3 x the B2B spread of M1 (B2B evaluation
    against B2B spread window); (V2) D3 sign: the top gap widens at 2 km relative to the mean, delta g3 > 0 (this covers
    "the top gap, or both outer gaps"; delta g3 <= 0 is the opposite sign and refutes D1); (V3) no clip in any examined
    window of either file; (V4) no code-step change.
I11. Truths (D13), all 4194304 samples from the five study windows (B2B-normalised), source amplitude A_src = 1 for
    B2B windows and 0.832 for 2 km windows. Law truths: u = f^-1(x) / A_src with the fitted polynomial, then the fibre
    (T1: the cosine response at L = 10 km over the whole waveform, the study's own filter), then v = A u, then f(v)
    (T4: the polynomial with a and b both times 2 or times 0.5). No-law truths (T2 from B2B, T3 from 2 km windows):
    v = A cos-filtered(x / A_src), no law. RX bound: add B2B-shaped noise of standard deviation
    sigma_rx sqrt(max(0, 1 - (A / A_src)^2)) (fitted sigma_rx) after everything else; OPT: add nothing.
    T5: as T1 with the cosine replaced by a large-signal field model on u: optical power P = 1 + m u with m set so the
    outer centroids of u have a power ratio of 6 dB (extinction ratio), field sqrt(max(P, 0)), dispersion phase
    exp(-j pi lambda^2 D L f^2 / c) (1310 nm), square law, back to u units by (P' - 1) / m. T6: T1 then a zero-phase
    Butterworth-4 magnitude 1 / sqrt(1 + (f / 45 GHz)^8) after the law, before the RX noise. T7: T1 at A 0.30 and 0.60.
    Configurations (48): T1 2 km D {0, 4.5, 5.2, 6.352} x A 0.45 x {RX, OPT} (8); T1 2 km D 4.5 x A {0.65, 0.85} x
    {RX, OPT} (4); T1 B2B D 4.5 x A 0.45 x {RX, OPT} (2); T2 and T3 D {0, 4.5} x A {0.45, 0.65, 0.85} x {RX, OPT} (24);
    T4 x2 and x0.5, D 4.5, A 0.45, OPT (2); T5 D {4.5, 6.352}, A 0.45, OPT (2); T6 D 4.5, A 0.45, {RX, OPT} (2);
    T7 A {0.30, 0.60}, D 4.5, {RX, OPT} (4). R1 gates on the six T1 2 km configurations of D14 only; D 5.2, the B2B
    source and T4 to T7 are reported, not gating.
I12. Outcomes (D10, as R13). For one capture: law survivors are the law scenarios (252, or 504 if D11 keeps tanh) with
    psi <= 1; control survivors the 504 control scenarios with psi <= 1. FAIL if no law survivor; PASS, NOT
    DISCRIMINATING if a law survivor and a control survivor; PASS, DISCRIMINATING if a law survivor and no control
    survivor. Survivors' D and A are reported as sets.
I13. D11 collapse: tanh predictions at A 0.45 for every (D, noise) (42); collapse iff psi(polynomial, tanh) <= 0.5
    under the E2c limits of that cell for all 42. S3 is evaluated for every kept shape.
I14. R3 reach: A* = the largest A in (0.45, 0.65, 0.85) at which, at D 4.5, the T1 2 km configurations (both noises)
    meet the R1 count (>= 4 of 5) and the T2 and T3 configurations (both noises) meet the R2 per-configuration count
    (<= 1 of 5) and their pooled count is <= 2 of 20 (the 4-of-40 pool, 10 %, scaled to the four configurations at
    that A). Reported, never gating.

---

# Verbatim from the design (sections 0 to 4: D1 to D15)

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

# Verbatim from the design (section 6: D19)

## 6. Stop conditions: decision D19 ("do not spend 10 km; close E2 at PARTIAL")
D19. S1 Step 0 not viable (wrong sign, a clip, a code-step change, or a 2 km change within 3 B2B spreads). S2 the fitted law does not bring
     both evaluation windows within the R13 limits (R6). S3 the law predictions at A 0.45 are not separable from a control by construction.
     S4 R1 fails under either noise bound, or R2 fails. Any stop is recorded as `decision: CLOSE_PARTIAL` with the failed line, committed and
     reviewed; the 10 km file stays unread for a future, differently designed hypothesis. Closing text: "H1 refuted at 2 km (R13, FAILED); H2
     formed post hoc; the power study could not make a 10 km test that discriminates; claim PARTIAL; 10 km unspent." WORTH_10KM only
     entitles the owner to design R14; it is not a freeze.

---

# Declarations D15, repeated in every E2c output

D15 (a) to (f) above are reproduced in `step0_diagnostics.yaml`, `law_model.yaml` and `power_study_e2c.yaml` under
`declarations`. BER and SER stay REFERENCE_SEQUENCE_MISSING. VALIDATED is never returned.

---

# Amendment A1 (2026-11-11), committed before Step 0 and before any fit

Found on fixtures only (the test channel of `tests/test_benchmark_e2c.py`, no capture read, no study step run): a
single Nelder-Mead run of I5 stops at a collapsed simplex far from a known truth even when the truth has objective 0
(known a = b = -0.04: one run ends at a -0.036, b -0.034, objective 0.020; three restarts from the best point reach
a -0.0404, b -0.0399, objective 0.0013). I5 is amended for the optimiser only: after the first run, up to 3 restarts,
each from the best point so far with a fresh initial simplex of the same steps and maxfev 600, stopping when a run
improves the objective by less than 1e-4. Every run's objective is recorded. Nothing else changes: not the objective,
parameters, profiles, starts, windows, seeds, limits, truths, thresholds or the decision rule.
