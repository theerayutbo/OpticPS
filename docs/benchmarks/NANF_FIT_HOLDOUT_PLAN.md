# Fit and holdout plan: Hong et al. 2021 NANF vs SSMF (declared before any data cell is read)

Declared 2026-10-31 at Gate N0 of the NANF workstream. The SHA-256 of this file is pinned in
`tests/test_nanf_benchmark.py`. A change after the fact fails that test. An amendment is a new dated
section at the end of this file plus a new pin; the earlier text stays in Git history. This plan is
separate from `FIT_HOLDOUT_PLAN.md` (TERIPHIC) and does not amend it.

Source: Y. Hong et al., "Hollow-core NANF for High-speed Short-reach Transmission in the S+C+L-bands",
J. Lightwave Technol. 39(19), 6167-6174, 2021, DOI 10.1109/JLT.2021.3097278. Dataset DOI
10.5258/SOTON/D1889 (workbook with one sheet per figure). Details are in
`docs/NANF_SOURCES_AND_PROVENANCE.md`.

## 0. State of knowledge when this plan was written (honest limits)

1. All figures come from one paper, one laboratory, one transmitter and receiver, one measurement
   campaign (May 2020 per the dataset readme). This is a single experiment, not a replicated one.
2. The paper PDF (an author manuscript) was read in full before this plan: setup, parameters, prose
   results and figure captions. This includes prose numbers that bear on the criteria below: required
   ROP of about -12, -11, -10 dBm at 80, 100, 112 Gb/s; an SSMF SNR penalty of about 5, 11, 14 dB; an
   SSMF spectral null near 24 GHz; capacities of about 138.09 Gb/s (NANF) and 112.52 Gb/s (SSMF) at
   -7 dBm; and a 4QAM-OFDM threshold crossing near -10 dBm. The criteria are therefore blind to the
   workbook cells but not to the paper's prose.
3. The workbook structure was inventoried before this plan: sheet names, header cells, dimensions,
   merged ranges, and per-column counts of numeric, blank and text cells. No numeric cell value was
   printed or looked at. From the counts it is already known that in Fig. 4 the NANF series have 6
   points per curve against 11 for B2B and SSMF, that the NANF series in Fig. 9 and Fig. 12 have 6
   points against 8, and that the SSMF column of Fig. 11 holds spreadsheet error cells (formula
   results shown as errors in a cached-value read). No header carries a unit string.
4. The tolerances in section 4 are the plan author's engineering judgement. They are not derived from
   a noise estimate, because the dataset has no repeats and no stated error-count depth.
5. No fit, simulation or comparison has been run at the time of writing.

## 1. Unit of analysis and independence

A point on a curve is not an independent observation. Every point shares the transmitter, receiver,
equaliser configuration, session and fibre sample of its curve. The independent units are
(fibre sample, transceiver, session):

| Unit | Count in this dataset | Basis |
|---|---|---|
| NANF sample | 1 (one spliced spool, a ~3.4 km piece plus a ~1.4 km piece) | paper Sec. III-A |
| SSMF sample | 1 (a ~4 km spool plus a ~0.5 km spool) | paper Sec. III-A |
| Transmitter and receiver | 1 pair | paper Fig. 2 |
| Session | 1 stated (May 2020) | dataset readme |
| Repeat captures per point | not stated | unknown |

A dataset earns the label `VALIDATION` only if it has at least 3 independent fibre samples in the
class being validated, plus either at least 2 sessions or documented repeat captures that bound the
run-to-run spread, plus a stated capture size or error-count depth. This dataset has 1 and 1 and no
stated repeats. Its label is therefore fixed in advance, by structure and not by any outcome:

**`LITERATURE BENCHMARK / CALIBRATION ONLY`**

The split in section 2 is still declared, so that the same discipline is applied and the later
numbers mean something as a consistency check. A pass against it is reported as "consistent with one
published experiment", never as validation, and never as evidence about other spools or labs.

## 2. Calibration set versus locked holdout

The workbook sheet names are those of the paper's figures. Fig. 6 is split by series, not by sheet.

| Role | Data | Reason |
|---|---|---|
| Calibration (the only data a Tx/Rx fit may see) | Fig. 4, B2B series only: BER and SNR versus ROP at 1550 nm, 80, 100 and 112 Gb/s | Owner rule: B2B estimates transmitter and receiver properties. |
| Calibration inputs (settings, not outcomes) | Fig. 5 ROP columns and NANF loss column | Operating point and link-budget input. They are set or measured quantities, not performance results. |
| Locked holdout | Fig. 4 NANF and SSMF series (all rates, BER and SNR) | Fibre cases are held out. |
| Locked holdout | Fig. 6, all series including B2B (BER and SNR versus wavelength, S+C+L) | The B2B wavelength dependence is not calibrated. Predicting it is a holdout check. |
| Locked holdout | Fig. 7, 8, 9, 10, 11, 12 (all OFDM sheets, both fibres) | OFDM was not used for calibration. |
| Excluded from scoring | Fig. 4 points with ROP above -5 dBm (the paper's shaded TIA-overload region) | The paper states these are spurious. |
| Cross-check only, no fit | Fig. 1 (the paper's own numerical curves) | Not a measurement. Used only to check that our dispersion and latency arithmetic reproduces the paper's stated assumptions. |

Rules:

1. Before any fit, the calibration list is the section above. Any series not named there is holdout.
2. The holdout is read only by the scoring step, after the Tx/Rx parameter vector is frozen and
   hashed. No holdout series is plotted, summarised or compared before that hash exists.
3. Fibre parameters are not fitted. Length, dispersion value, dispersion slope source, refractive
   index, splice and connector loss and link loss are set from the paper or a standard, with a
   provenance label per `docs/NANF_SOURCES_AND_PROVENANCE.md`, before the run. They are not changed
   after a result is seen. No per-fibre retuning: NANF and SSMF share the one frozen Tx/Rx vector.
4. At most 6 free Tx/Rx parameters. The calibration has 3 curves (one per rate), each with a few
   effective degrees of freedom, so more would be unconstrained.
5. A leave-one-rate-out check inside B2B (fit on two rates, predict the third) is reported as a
   diagnostic only. It changes nothing.
6. Any unknown that the model needs (modulator bias, extinction ratio, laser power, PD and TIA noise,
   AWG and DSO analogue bandwidth, DAC resolution) enters as a Tx/Rx fit parameter or a labelled
   assumption. It is never taken from a vendor datasheet presented as a measurement.
7. Data stay under `data/external/` (ignored by Git). Series values, digitised figures and plots of
   them are not committed. Reports carry summary metrics and the file hashes only.

## 3. Quantities scored

For PAM4 (Fig. 4, 6): SNR in dB, BER on a log10 scale, and the ROP at which BER crosses 3.8e-3
(interpolated on the published points). For OFDM (Fig. 7 to 12): average SNR, BER, SNR-profile null
frequency, and maximum capacity at the 3.8e-3 threshold. BER points below 1e-5 are censored, because
the dataset gives no error-count depth. A censored point is scored only as "predicted BER below 1e-4".

## 4. Predeclared numeric criteria

Each is evaluated per rate (PAM4) and reported separately. "Error" is simulated minus published.

| ID | Criterion | Pass threshold |
|---|---|---|
| C1 | NANF ROP at BER = 3.8e-3 (Fig. 4) | absolute error at most 1.0 dB at each of the three rates |
| C2 | NANF SNR versus ROP, ROP at most -5 dBm (Fig. 4) | mean absolute error at most 1.5 dB per rate and no single point beyond 3.0 dB |
| C3 | SSMF versus NANF SNR penalty (Fig. 4) | SSMF stays above BER 3.8e-3 at every scored ROP at every rate, and the penalty is within 3.0 dB of the paper's stated 5, 11, 14 dB |
| C4 | BER (Fig. 4, uncensored points) | absolute error in log10 BER at most 0.5 per point for at least 80% of points |
| C5 | Wavelength sweep (Fig. 6) | NANF SNR mean absolute error at most 2.0 dB per rate; SSMF SNR mean absolute error at most 3.0 dB per rate; B2B SNR mean absolute error at most 2.0 dB |
| C6 | SSMF first spectral null (Fig. 8, 11) | absolute error at most 2.0 GHz |
| C7 | OFDM capacity at -7 dBm (Fig. 12) | NANF and SSMF capacities each within 10 Gb/s, and the NANF-to-SSMF ratio within 0.10 of the published ratio |
| C8 | Uniform OFDM (Fig. 7, 9) | NANF average SNR mean absolute error at most 2.0 dB; SSMF at most 3.0 dB |

Decision rule. The primary set is C1, C2, C3, C5. The model is reported as "consistent with this
one experiment" only if every primary criterion passes at every rate. Otherwise the result is
reported as failed, with the criteria that failed, and the model is not retuned to pass. Secondary
criteria C4, C6, C7, C8 are reported pass or fail and never averaged into the primary verdict. No
criterion is dropped, relaxed or added after a number is seen, except by a dated amendment with a
new pin written before the scoring run it affects.

## 5. What this plan does not claim

- It does not claim the criteria are well calibrated against measurement noise. They are
  judgement-based (section 0, item 4).
- It does not make this dataset a validation set. The label in section 1 stands whatever the scores.
- It does not authorise redistribution of the data. Licence handling is in
  `docs/NANF_SOURCES_AND_PROVENANCE.md`.

## Amendment 1 (2026-10-31, N0 fix round after independent review)

Previous SHA-256 of this file, pinned until now (original text, commit 9a891c9):
`c4771dc125c3daeaf28b429de2f31f3ca25a5d3645a6f59e1d8dd9b9bf0bef22`. The new pin is in
`tests/test_nanf_benchmark.py`. Where this amendment and sections 2 to 4 differ, this amendment
governs; the original text stays above for the record. This amendment is written before any scoring
run. No fit, simulation or model comparison has run.

### A0. What had been seen when this amendment was written

- The review text exposed one holdout cell, Fig.11 SSMF C164, in a raw-XML excerpt. Its value was not
  used and is not an input to anything below.
- Counts only, no values compared to any model: BER cells equal to zero, BER cells below 1e-5, BER cells
  outside (0, 1]; and (Gate N0, Sources section 5, now withdrawn from that document) the number of Fig.8
  SSMF SNR cells below -5 dB (13). That last count is a summary of a locked holdout series made before the
  freeze hash, which rule 2 forbids in spirit. It is disclosed here and removed from the Sources
  document; no threshold below depends on it.
- The paper text, including the SSMF null "~25 GHz" at 5 km (p.2), "around 24 GHz" measured (p.6) and the
  clock-leakage sentence on p.6, which gives no spike frequency.
- For this amendment: the numerical curves of Fig.1 only (a cross-check class, not a measurement): CD near
  1550 nm, the latency columns, and the minimum of the SSMF fading column; and the structure (formula text)
  of the Fig.11 error cells. Fig.4, Fig.6, Fig.8 values and every other holdout series stayed unread.

### A1. Chirp is an unknown nuisance (amends rule 6)

Rule 6 gains: transmitter chirp (the modulator chirp parameter; any value, sign or model) is an unknown
nuisance parameter, tag `unknown`. The paper states no chirp value (searched; none found).

1. Chirp has no effect in B2B, so the calibration set cannot constrain it. It is classed
   `UNIDENTIFIABLE_PARAMETER` from calibration and is never fitted on holdout, on any fibre, rate or sheet.
   It is not one of the at most 6 free Tx/Rx parameters.
2. The primary result is computed at zero chirp. Every SSMF-dependent criterion (C3, the SSMF parts of
   C5, C6, C7, C8, and the SSMF series of C4) is scored at zero chirp.
3. Pre-registered zero-chirp expectation, from the standard small-signal intensity-modulation response
   (first null at f = sqrt(c / (2 lambda^2 D L))), lambda 1550 nm, D from the paper (15.95 SSMF,
   2.04 NANF ps/(nm km)). It is arithmetic on the paper's own assumed values, not a fit, and is reported
   whatever the simulation returns:

   | Case | First null at zero chirp |
   |---|---|
   | SSMF, L = 4.53 km (the experiment) | 29.39 GHz |
   | SSMF, L = 5 km (the paper's numerical case) | 27.97 GHz (workbook Fig.1 fading curve, 1 GHz grid: 28 GHz) |
   | NANF, L = 4.76 km | 80.2 GHz, no null inside the 32.8125 GHz band |

   The simulator's own zero-chirp null is reported beside these values. A disagreement above 0.3 GHz
   (about two subcarrier spacings of 0.1367 GHz) is treated as a simulator defect to be examined before
   scoring, not as a result.
4. The published null is about 24 GHz (Fig.8, p.6) and the paper's own calculation is about 25 GHz at 5 km
   (p.2). The pre-registered zero-chirp value is about 5.4 GHz above the measured null, against C6's
   tolerance of 2.0 GHz. C6 is therefore expected to FAIL at zero chirp. It is reported as FAIL with the
   number. The C6 tolerance is not widened because of this known gap, and no other criterion is relaxed.
5. A gap beyond tolerance is reported as a mismatch. It may be attributed to chirp only as a hypothesis.
   A chirp sensitivity sweep (alpha from -1.0 to +1.0 in steps of 0.25; a span chosen by the plan author,
   not by any source) may be run and reported. It is labelled "sensitivity sweep, not a fit" in the report;
   it does not select a value and nothing is scored from it. Arithmetic note: reaching 24 GHz at 4.53 km
   with zero chirp needs D of about 23.9 ps/(nm km), 50% above the assumed 15.95; the actual spool D is
   unmeasured, so this does not exclude a different D either.
6. A chirp value may enter the primary run only if a source states one for this setup. It is then cited
   (source, page), tagged `published-experimental`, and fixed before scoring.
7. Identifiability check (all Tx/Rx parameters, before the freeze hash). At the calibration optimum,
   compute the Gauss-Newton information matrix of the calibration residuals, each parameter scaled by its
   allowed range. A parameter whose scaled direction has an eigenvalue below 1e-3 of the largest is
   flagged `UNIDENTIFIABLE_PARAMETER`, frozen at a declared prior value, and counted out of the free
   parameters. The report lists the flags before any holdout is read.

### A2. Null model: copying the B2B curve is a named comparator

"B2B-copy" predicts the NANF series by the published B2B series of the same rate, at the same ROP
(linear interpolation of SNR in dB and of log10 BER against ROP, no extrapolation). It is a model with no
fibre. Paper p.4 and p.5 call the NANF penalty-free against B2B, and B2B and NANF share the apparatus, so
the B2B-copy is expected to be close.

- For C1 and C2, and the NANF part of C5, both the fibre model and B2B-copy are scored with the same
  metric and tolerance. Let d be the difference between the two predictions in that criterion's own
  metric (C1: absolute difference of the two crossings; C2 and C5: mean absolute difference of the two
  SNR predictions at the scored points).
- If d is at most the declared tolerance of the criterion (C1 1.0 dB, C2 1.5 dB, C5 NANF 2.0 dB), the
  criterion cannot tell the fibre model from a B2B copy. A pass there reads
  `PASS, NOT DISCRIMINATING`, never "agreement" or "consistent". A fail stays a fail.
- The overall verdict "consistent with this one experiment" additionally requires C1 and C2 to be
  discriminating. If all primary criteria pass but C1 or C2 are not discriminating, the verdict reads
  "primary criteria pass; NANF criteria NOT DISCRIMINATING", and the SSMF criteria (C3, C5 SSMF) are the
  only fibre evidence. Shared apparatus is thus handled per criterion, not only by the label.

### A3. Precise definitions (replace the loose wording of sections 3 and 4)

General: ROPs scored are those at most -5 dBm. Simulated curves are sampled at exactly the published
ROP or wavelength points and processed by the same rule as the published ones. BER is handled as log10.
A published BER of zero, or below 1e-5, is censored (no error-count depth is known). A censored point is
scored only as "predicted BER below 1e-4"; it never enters an interpolation or an average of log10 BER.
SNR is as the paper reports it (receiver-DSP SNR in dB; its exact definition is not stated in the source,
so any definitional difference is a mismatch and is reported, not tuned away).

- C1, crossing. For each rate, order the published NANF BER points by ROP, keep those uncensored and
  scored. The crossing is the ROP at which log10 BER, linearly interpolated against ROP in dBm between two
  adjacent points that bracket log10(3.8e-3), equals log10(3.8e-3); the bracket must go from above to
  below the threshold with rising ROP. Unbracketed cases are never extrapolated. If the first scored
  point is already below the threshold, the crossing is reported as a left-censored bound
  "at or below that ROP"; if no scored point is below it, as a right-censored bound. This includes the
  80 Gb/s curve, whose crossing the paper puts near the -12 dBm edge of the axis. A bound is scored
  one-sidedly: it passes if the simulated crossing, found by the same rule, lies on the right side of the
  bound within the 1.0 dB tolerance. A rate scored only on a bound is flagged, and cannot count as
  discriminating under A2. The primary decision needs a result at every rate; a bound result counts as a
  pass or fail of the bound.
- C2. At each scored published NANF ROP point (uncensored; SNR cells are never censored), error =
  simulated SNR minus published SNR in dB. Pass: mean of the absolute errors at most 1.5 dB per rate and
  no single absolute error above 3.0 dB.
- C3, penalty. At each published NANF ROP at most -5 dBm that lies inside the SSMF ROP range, penalty =
  NANF SNR minus SSMF SNR in dB, the SSMF SNR linearly interpolated in dB against ROP, no extrapolation.
  The penalty of a rate is the mean over those ROPs. The simulated penalty uses the same ROPs and rule.
  Pass: the simulated penalty is within 3.0 dB of the paper's stated value (5, 11, 14 dB; the paper gives
  no ROP for these and calls them "around"), and the simulated SSMF BER exceeds 3.8e-3 at every scored
  SSMF ROP point of that rate. The workbook penalty, by the same rule, is reported next to the prose value.
- C4. Per rate, the uncensored scored BER points of NANF and SSMF pooled: absolute error of log10 BER at
  most 0.5 for at least 80% of points. Censored points are scored by the general rule and are reported,
  not counted in the 80%.
- C5. For each wavelength of the 19 published points, simulated minus published SNR in dB, with ROP and
  loss taken from Fig.5 (the `ROP@NANF` column also sets the B2B ROP, paper p.5; the SSMF ROP is capped
  at -5 dBm). Mean absolute error per rate and link against the stated thresholds. Points whose ROP lies
  outside the calibrated ROP range are included in the criterion and also reported separately.
- C7. Capacity at ROP -7 dBm: the loading algorithm is fixed and committed before scoring (its identity is
  not tunable); capacity is bits loaded times 70 GSa/s / 512 summed over the 240 data subcarriers, under
  BER at most 3.8e-3. Ratio = NANF capacity over SSMF capacity.
- C8. Fig.7 and Fig.9: for each fibre, mean absolute error of simulated minus published average SNR in dB
  over that fibre's published points.

### A4. Calibration uses the scoring exclusions

- Calibration points with ROP above -5 dBm (B2B at -4, -3, -2 dBm) are excluded from the fit, as they are
  from scoring. The earlier calibration row, which kept them, is replaced by this rule.
- BER = 0 cells have no count basis. They are censored and excluded from the BER part of the fit. The same
  holds for BER below 1e-5. Rule: the BER residual (log10 BER) is formed from uncensored cells only; the
  fitted model's prediction at a censored cell is reported as a diagnostic (below 1e-4 expected), never as
  an objective term. This selection by value can bias BER-based estimates toward higher error rates; SNR
  cells are not censored and carry the rest of the information.

### A5. C6 moves to Fig.8 (replaces C6 sources "Fig. 8, 11")

- Data: workbook sheet `Fig.8`, column A (frequency, GHz, 240 values, 0.13672 to 32.8125), column C
  (header `240sub-SMF-OFDM`, SSMF SNR profile, uniform 16QAM-DDO-OFDM, ROP -7 dBm). Fig.11 is not used for
  C6: its 24 cells around the null are formulas, most likely unloaded subcarriers (inference).
- Null estimator (applied identically to the published column and to the simulated 240-subcarrier
  profile): (i) the running median of the SNR profile over 5 consecutive subcarriers (centred; the
  median is formed over the whole profile before the window is applied); (ii) restrict to frequencies
  from 20.0 to 32.8125 GHz; (iii) the null frequency is where that median is lowest, the lowest frequency
  on ties. If the minimum falls on a window edge, the result is "no interior null in window" and C6
  fails with that reason.
- AWG clock-leakage spikes (paper p.6; the paper gives no frequency). Exclusion is by rule, from
  paper-stated quantities only: (a) the median over 5 subcarriers removes any feature at most 2
  subcarriers wide (about 0.27 GHz), which is how a clock tone appears on this grid; (b) the window starts
  at 20.0 GHz, above the sub-multiples of the paper-stated 70 GSa/s sample rate that fall in the band
  (17.5 GHz and 8.75 GHz; 35 GHz lies above it), and below the published null near 24 GHz; (c) the
  window is not narrowed or moved after the data are read. If the published estimate lands within
  0.5 GHz of a sub-multiple of 70 GHz divided by 2^k, the report says "estimator ambiguous" and does not
  change the rule; a rule change would need a further dated amendment and the C6 result would be labelled
  post-hoc.
- Pass: absolute difference of the two null frequencies at most 2.0 GHz (unchanged). The pre-registered
  zero-chirp expectation of A1 applies; C6 is expected to fail at zero chirp.
- Reading the Fig.8 column happens only in the scoring step, after the freeze hash (rule 2).

### A6. Unchanged

The label stays **`LITERATURE BENCHMARK / CALIBRATION ONLY`**. Fibre parameters are not fitted; no
per-fibre retuning; at most 6 free Tx/Rx parameters; holdout read only by the scoring step after the
freeze hash. Tolerances are judgement, not noise-derived. No criterion is dropped, relaxed or added after
a number is seen except by a further dated amendment with a new pin.

## Amendment 2 (2026-10-31, N1 gate, closing items 1 to 8 and 13 of the second N0 review)

Previous SHA-256 of this file, pinned until now (Amendment 1, commit 843d223):
`92b20966c409958729946f31243216b49fe796d7b9f4ac22f33f30c854dce5c0`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; the original text before
"## Amendment 1" still hashes to the original pin, and a test checks that). Where this amendment and anything
above differ, this amendment governs. It is written before any scoring run. No fit, simulation of the paper's
curves or model comparison has run. Fig.4, Fig.6 and Fig.8 values and every holdout series stayed unread.

### B0. Corrections to what the earlier sections say

1. Sessions. Section 1, row "Session | 1 stated (May 2020)", is superseded. The dataset readme gives a data
   collection date (May 2020; DataCite says 2021-05). The number of sessions is not stated by any source, so it
   is unknown, not 1. The label `LITERATURE BENCHMARK / CALIBRATION ONLY` does not depend on it: it is fixed
   by the count of independent fibre samples (1 NANF, 1 SSMF), which is below 3.
2. What was seen, extended (completes A0). Besides the items in A0, the Gate N0 value checks produced these
   summaries of locked holdout structure before any freeze hash: the number of ROP points per Fig.4 curve
   (NANF 6, B2B and SSMF 11); the numbers of Fig.9 and Fig.12 points (NANF 6, SSMF 8); the numbers of BER cells
   equal to zero in Fig.4 (NANF 1, B2B 3), Fig.6 (NANF 12 and B2B 12 of 19) and Fig.10 (one per fibre); the
   positions of the 24 error cells in the Fig.11 SSMF column (22.15 to 25.43 GHz). These are counts of presence
   and of a coarse value class, not model comparisons, and no tolerance depends on them except that the C1
   censoring rules below were written knowing that zero BERs exist at 80 Gb/s. They are treated like the Fig.8
   count of A0: disclosed, kept in the Sources document (all are structure), and not used to choose any
   number. This replaces the earlier uneven handling (Fig.8 count withdrawn, Fig.4 and Fig.6 counts kept).
3. The C6 window. The window 20.0 to 32.8125 GHz (A5) was set knowing three things: the paper's "around 24 GHz",
   the zero-chirp expectation of 29.39 GHz, and the Fig.11 unloaded band 22.15 to 25.43 GHz (Sources section 5).
   The Fig.11 band was not in A0. It is disclosed now. Both sides of the comparison use the same estimator,
   29.39 GHz is inside the window, and A5(c) forbids moving it, so the expected bias is small, but the window
   is not blind to the answer.
4. Pre-registration is blind for the simulator only. The expected nulls of A1.3 are arithmetic on the paper's
   assumed D and L, written before any simulation. They are not blind predictions of the measurement: the
   measured null near 24 GHz was already known. A consequence that is stated now: a chirp factor alpha of about
   0.58 would put the zero-chirp-corrected null near 24 GHz at 4.53 km, and the sweep of A1.5 includes
   alpha = 0.5 (about 24.7 GHz). That sweep value matching the measurement is not evidence for chirp, no alpha is
   chosen from it, and the alpha that would reach 24 GHz is not to be used as an input anywhere (primary run,
   any other sheet, any other fibre). C3 and C5 for SSMF are scored at zero chirp (A1.2) and are likely
   to carry the same gap.

### B1. C1, remaining cases (extends A3, C1)

Let the scored published NANF BER points of one rate be ordered by ROP. A point is above, below or
censored (zero or below 1e-5, which is known to lie below 3.8e-3 but is not an interpolation node).

1. Selection among brackets. A bracket is a pair of adjacent uncensored scored points whose log10 BER values
   straddle log10(3.8e-3) going from above to below with rising ROP. If there are several, the crossing is
   the last one (highest ROP): the ROP from which BER stays below the limit at every later uncensored point.
   If the curve ends above the threshold, there is no downward bracket after the last upward one and the
   result is right-censored. The same rule is applied to the simulated curve.
2. Zeros after a falling curve. If no uncensored bracket exists but an uncensored point above the threshold
   is followed by a censored point, the crossing is an interval [ROP of the last uncensored point above,
   ROP of the first censored point]. Example: BER 1e-2, 5e-3, 0, 0 gives the interval from the second to the
   third ROP. A censored point before any uncensored point above the threshold gives a left-censored bound at
   that ROP as in A3.
3. Tolerance on a bound or interval. The tolerance of 1.0 dB widens the accepted region on the wrong side only
   for a bound, and on both ends for an interval. Left-censored bound "at or below r0": pass if the simulated
   crossing x satisfies x <= r0 + 1.0 (any x far below r0 also passes: the bound is one-sided). Right-censored
   bound "above r0": pass if x >= r0 - 1.0. Interval [lo, hi]: pass if lo - 1.0 <= x <= hi + 1.0. A wrong-side
   miss of up to 1.0 dB therefore passes; a larger one fails. A simulated curve with no crossing in the scored
   ROP range fails for a rate with a bracket, and for a bound it passes or fails by the same inequalities
   applied to its first or last scored ROP. Any rate scored on a bound or interval is not discriminating (A2).
4. This section was written without testing whether Fig.4 contains the zero-after-falling case.

### B2. C5 at 1630 and 1640 nm

The Fig.5 and Fig.6 wavelength grid has 19 points from 1460 to 1640 nm in 10 nm steps. The only dispersion
curves of the paper (Fig.1(a)) end at 1625 nm, and the ITU-T G.652 bounds also end at 1625 nm. The dispersion at
1630 and 1640 nm is therefore unsupported for both the NANF and the SSMF. Rule: those two points are excluded
from C5 for all three links, with no extrapolation of D, S, loss or any other property. C5 is scored on the 17
points from 1460 to 1620 nm. The B2B SNR at all 19 points may be reported as an unscored extra. The exclusion
is declared before the run and counts as part of the criterion, not as a relaxation. The propagation model
refuses (N1) a wavelength outside the validity range of any property it needs, unless an extrapolation is
requested explicitly, and a scored run does not request it.

### B3. A2, d, redefined, and a B2B fit-quality gate

1. d compares the model's NANF prediction with the model's own no-fibre output: same frozen Tx/Rx vector, same
   ROP points, no fibre and no link loss other than the ROP setting. The published B2B series stays a reported
   comparator (B2B-copy, as in A2) but d is no longer computed against it. Metrics as in A2.
2. B2B fit-quality gate. Per rate, on the calibration points (A4), after the fit: mean absolute error of the
   model's B2B SNR against the published B2B SNR at most 1.0 dB, no point beyond 2.0 dB, and the model's B2B
   ROP at BER 3.8e-3, found by the C1 rule, within 0.5 dB of the published one (a bound is judged by B1.3
   with 0.5 dB). The numbers are the plan author's judgement, fixed now. A rate that fails the gate is labelled
   `B2B CALIBRATION POOR`; its NANF criteria C1, C2 and C5 (NANF) are then reported but cannot read
   "discriminating" or "consistent".
3. All-rate requirement. C1 and C2 must be discriminating at every one of the three rates (80, 100,
   112 Gb/s) for the verdict "consistent with this one experiment". Otherwise the verdict is the A2 wording
   "primary criteria pass; NANF criteria NOT DISCRIMINATING", naming the rates. A pass on C1 or C2 at a rate
   where d is within tolerance is `PASS, NOT DISCRIMINATING` as before. A fail stays a fail.

### B4. A1.7, identifiability check, made executable

1. Parameter vector. The free Tx/Rx parameters are these six, and no others (fewer may be used, never more):

   | Name | Meaning | Allowed range | Prior if flagged (midpoint) |
   |---|---|---|---|
   | tx_bandwidth_ghz | analogue bandwidth of AWG, driver and modulator chain (4th-order Butterworth) | 10 to 60 | 35 |
   | rx_bandwidth_ghz | analogue bandwidth of photodiode, TIA and scope chain (4th-order Butterworth) | 10 to 60 | 35 |
   | thermal_noise_pa_per_rthz | input-referred thermal noise density | 5 to 60 | 32.5 |
   | modulation_depth | drive swing divided by V_pi | 0.2 to 1.0 | 0.6 |
   | bias_fraction | modulator bias as a fraction of V_pi | 0.4 to 0.6 | 0.5 |
   | electrical_snr_ceiling_db | additive white noise ahead of the equaliser, as an SNR cap | 15 to 35 | 25 |

   Chirp is not in this list (A1.1). The ranges are the plan author's judgement and were chosen before any fit.
   A fit that reaches a range edge is reported as such, and the range is not widened.
2. Scaling and information matrix. Each parameter is scaled to u = (value - low)/(high - low). The residual
   vector holds the SNR residuals in dB and the log10 BER residuals divided by 0.5, over the calibration
   points of A4. J is the Jacobian at the optimum with respect to u (finite differences, step 1e-3 in u), and
   the information matrix is J^T J.
3. Mapping to a flagged parameter. Eigenvalues are sorted ascending. For each eigenvalue below 1e-3 of the
   largest, in ascending order, the parameter with the largest absolute component in that eigenvector among
   those not yet flagged is flagged (ties: the lowest in the table above). One parameter is flagged per such
   eigenvalue, so the number of flags equals the number of low eigenvalues.
4. No refit after a flag. A flagged parameter is set to its prior in the table, and no other parameter is
   refitted. The vector so formed is the one that is hashed. The calibration residuals at that vector are
   reported, and the B2B fit-quality gate of B3.2 is evaluated at that vector; a harmful flag therefore shows
   as a gate failure and is not repaired. The check runs once, before the freeze hash, on calibration data only.
5. If the information matrix is singular to machine precision, every direction below the threshold is flagged
   by rule 3 and the report says so.

### B5. A5, null estimator, repaired

1. The reported statement "estimator ambiguous" could not fire as written (an interior value in the window
   is at least 2.19 GHz from 17.5 and 35 GHz). It is removed and replaced by the check in rule 3.
2. The spike assumptions are assumptions, not paper-stated facts. The paper gives the AWG rate 70 GSa/s and
   mentions clock leakage; it gives no spike frequency. Assumed: a clock-related tone sits at 70/k GHz for
   an integer k from 2 to 8 (35, 23.33, 17.5, 14, 11.67, 10, 8.75 GHz), and it occupies at most 2 subcarriers
   (0.27 GHz). Neither is known. A spike elsewhere would not be recognised by this rule.
3. Check that can fire: if the published null estimate, or the simulated one, lies within 0.5 GHz of a value
   70/k inside the window (here only 23.33 GHz), the report says `POSSIBLE CLOCK-SPIKE COINCIDENCE`. The
   rule, the window and the pass criterion are not changed by it; it only qualifies how the C6 number is read.
4. Median at the profile ends. For subcarrier i (1 to 240) the median is over indices max(1, i-2) to
   min(240, i+2), so it uses 3 values at the first and last subcarrier and 4 at the second and second last.
   The window edge at 32.8125 GHz is the last subcarrier, so a minimum there is "no interior null in window"
   as in A5(iii).

### B6. Simulator SNR definition (fixed before the freeze hash)

For C2, C3, C5 and the PAM4 SNR of Fig.4 and Fig.6: after the equaliser, SNR (dB) = 10 log10( mean |s|^2 /
mean |s_hat - s|^2 ), both means over all scored symbols of the capture, s the transmitted PAM4 symbol (levels
-3, -1, 1, 3 scaled alike), s_hat the equaliser output before the decision. For OFDM (C6 profile, C8, C7): the
per-subcarrier SNR_k (dB) = 10 log10( E|X_k|^2 / E|X_hat_k - X_k|^2 ) over the symbols of the capture, and the
"average SNR" of C8 is the arithmetic mean of the SNR_k in dB over the loaded subcarriers. The mean of linear
SNR is reported beside it as an unscored extra. The source's own definition is not stated; any difference is a
mismatch and is not tuned away. These definitions are committed with the freeze hash.

### B7. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning", the 6-parameter cap, the criteria
thresholds of section 4 and A3 (apart from the cases defined above), and the rule that no criterion is dropped,
relaxed or added after a number is seen except by a dated amendment with a new pin.

## Amendment 3 (2026-10-31, N1 fix round, closing the C1 residual and noting B5.3)

Previous SHA-256 of this file, pinned until now (Amendment 2):
`ec0f325a118fcc8162e21de2b6acf1662b6d3ea6db14bfed0c3a507ff2827aa5`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; the text before
"## Amendment 2" still hashes to the Amendment 1 pin `92b20966...ce5c0`, and a test checks that in addition to the
prefix test for the original text). Where this amendment and anything above differ, this amendment governs. It is
written before any scoring run; no fit or simulation of the paper's curves has run, and Fig.4, Fig.6 and Fig.8
values and every holdout series stayed unread. No criterion's tolerance or threshold is changed.

### C1-R. C1, the case of an upward point after a bracket (replaces the gloss of B1.1)

The gloss of B1.1, "the ROP from which BER stays below the limit at every later uncensored point", is wrong for a
curve such as BER 1e-2, 1e-3, 6e-3, 0 (points 1 to 4 by rising ROP: above, below, above, censored). A downward
bracket exists (1 to 2) and B1.2 does not apply as written, but the curve is above the limit at point 3. The rule
is now, for the scored points of one rate ordered by ROP, with P the last uncensored point:

1. If P is below the threshold: the crossing is the interpolation in the last downward bracket (highest ROP) of two
   adjacent uncensored points, as in B1.1. If there is no downward bracket, A3 applies (left-censored bound at the
   first scored ROP).
2. If P is above the threshold: any earlier downward bracket is not used. If a censored point follows P, the
   crossing is the interval [ROP of P, ROP of the first censored point after P] (B1.2 extended to curves that fell
   earlier). If no censored point follows P, it is a right-censored bound "above the ROP of P". B1.3 scores both.
3. The same rule is applied to the simulated curve.

Worked cases, ROPs r1 to r4 rising: 1e-2, 1e-3, 6e-3, 0 gives the interval [r3, r4]; 1e-2, 1e-3, 6e-3, 5e-3 gives
"above r4"; 1e-2, 1e-3, 6e-3, 1e-3 gives the interpolated crossing between r3 and r4; 1e-2, 1e-3, 0, 0 gives the
crossing between r1 and r2; 1e-2, 5e-3, 0, 0 gives the interval [r2, r3] (unchanged from B1.2). This amendment was
written without testing whether Fig.4 contains any of these cases.

### B5.3-N. The 0.5 GHz threshold of B5.3

The threshold of 0.5 GHz in B5.3 was set knowing the paper's "around 24 GHz". A published null of 24.0 GHz misses
23.33 GHz by 0.67 GHz, so the flag `POSSIBLE CLOCK-SPIKE COINCIDENCE` would not fire for it. This qualifies how the
flag is read only; the threshold is not moved and no criterion changes.

## Amendment 4 (2026-11-01, N2 fix round after the independent review of Gate N2)

Previous SHA-256 of this file, pinned until now (Amendment 3, commit 6d75b88):
`0a3897ad0b22acca7710faf61acc40d97f846c6829eb6fc26e1ece3f7ff4f2c4`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; the text before the
Amendment 3 heading still hashes to the Amendment 2 pin `ec0f325a...7aa5`, and a test checks that, and now also that
the text before this heading hashes to the previous pin). Where this amendment and anything above differ, this
amendment governs. It is written before any scoring run; no fit and no simulation of the paper's curves has run,
and no Fig.4, Fig.6 or Fig.8 value, and no holdout value, has been printed or compared with a model. No tolerance or
threshold of section 4, A3 or B1 to B3 is changed.

### D0. What had been seen (adds to A0 and B0.2)

During Gate N2, after the importer's schema check, the per-series counts of censored BER points (zero, or below 1e-5)
and of non-finite cells were printed once for all 69 series, including the locked holdout (Fig.4 NANF and SSMF, Fig.6,
Figs.7 to 12). Counts only: no value was printed, none is recorded here, and no tolerance, rule or code path of this
plan depends on them. They are disclosed in the same class as the counts of B0.2. Also read in N2, as allowed by
section 2: the Fig.1 cross-check curves and the Fig.5 ROP and loss columns (summary metrics are in
`reports/NANF_Benchmark_Report.md`); the paper PDF was reread for axis labels and the DSP description.

### D1. A3 against C5, the 6 SSMF points above -5 dBm (resolves a conflict)

A3 says "ROPs scored are those at most -5 dBm"; C5 and B2 score "each wavelength" of the 17. In Fig.5 six SSMF operating
points lie 0.01 to 0.02 dB above -5 dBm (1490, 1500, 1540, 1590, 1600 and 1610 nm; -4.98 or -4.99 dBm), all inside the
17. The rule is: the -5 dBm cut of A3 applies to the ROP axis of Fig.4 (points above it are the paper's TIA-overload
region). C5 is a wavelength sweep whose ROP is an operating point taken from the Fig.5 column, which the paper itself
sets as "capped at -5 dBm"; the excess is at the rounding of the published column. C5 therefore scores all 17
wavelengths including those six points, with no ROP exclusion, and the six are reported separately as
"ROP above the cap by at most 0.02 dB". Nothing is moved or rounded: the simulated ROP is the published one.

### D2. Unknowns of the simulation, each declared with a label (adds to rule 6 and B4)

None of these is one of the at most 6 free parameters of B4 (the table there stays as it is). Each is fixed here, labelled
`user-assumed` (plan-author choice; not from the paper, not from a datasheet, not a measurement), and is not changed
after a result is seen except by a further dated amendment.

| Item | Declared value | Label | Note |
|---|---|---|---|
| DAC resolution | 8 bit, uniform quantiser, full scale at the signal peak | `user-assumed` | the paper states the AWG rate (70 GSa/s) but not the resolution |
| RIN | not modelled (zero) | `user-assumed` | any intensity noise is absorbed by `electrical_snr_ceiling_db` |
| Symbol sequence | independent uniform PAM4 symbols from one fixed pseudo-random generator seed, 20261101, the same sequence at every rate and every point (no per-point reseed) | `user-assumed` | the paper does not state the pattern |
| Capture length | 655360 symbols (20 x 32768) per point, the first 8192 of which are equaliser training and are not scored | `user-assumed` | the paper states no capture size; 655360 gives about 65 errors at BER 1e-4, so a simulated BER below 1e-4 is reported as "below 1e-4 (at most 65 errors)" |
| Responsivity | 0.8 A/W, passed explicitly in the configuration of every run | `user-assumed` | the code default must not be used silently; responsivity is degenerate with the thermal-noise density (a free parameter), so it is fixed and not fitted |

Still `unknown` and to be declared before the freeze hash, as the N2 report says: the split of the (17, 7) DFE taps,
the DFE initialisation and decision-directed switch, and the DFE training schedule beyond the 8192 symbols above.

### D3. Scoring logic that had no precise text (adds to A2, B3 and A3)

1. B2B-copy comparator. For a rate, the copy predicts the NANF curve by the published B2B series of the same rate:
   SNR in dB and log10 BER linearly interpolated against ROP, no extrapolation, only uncensored B2B points as BER
   nodes, only B2B ROPs at most -5 dBm (A4). Scoring of the copy uses the same metric and tolerance as the model: for C1
   the crossing by the C1-R rule applied to the copy values at the scored NANF ROPs; for C2 the errors of the copy SNR
   against the published NANF SNR at the scored NANF ROPs; for the NANF part of C5 the errors of the published
   Fig.6 B2B SNR at the same wavelengths (a holdout series: read only by the scoring step, after the freeze hash, as
   rule 2 requires; the copy is then the published B2B SNR itself, with no interpolation). A NANF ROP with no B2B
   bracket is not scored for the copy and is reported. The copy is a reported comparator and never enters d.
2. d (B3.1), exactly. d compares the model's NANF prediction with the model's own no-fibre output: same frozen Tx/Rx
   vector, same ROP points, same scored points. C1: d is the absolute difference of the two crossings, each found by
   C1-R; if either crossing is a bound or an interval, d is undefined and the rate is not discriminating (B1.3).
   C2: d is the mean absolute difference between the two predicted SNR values at the scored NANF ROPs. C5 NANF: d is
   the mean absolute difference over the 17 wavelengths of the model's NANF SNR and its no-fibre SNR at the ROP of
   Fig.5. Discriminating means d strictly greater than the tolerance of that criterion (1.0, 1.5, 2.0 dB); d at most
   the tolerance reads `PASS, NOT DISCRIMINATING` on a pass.
3. C3, exactly (A3). Per rate: the ROP set is the published NANF ROPs at most -5 dBm that lie inside the SSMF ROP range,
   with no extrapolation; if the set is empty C3 fails with the reason "no overlap". Penalty = mean over the set of
   (NANF SNR minus SSMF SNR in dB, SSMF interpolated in dB). The simulated penalty is formed by the same rule from the
   simulated SNR values. Pass needs both: (a) |simulated penalty minus the paper's stated 5, 11 or 14 dB| at most 3.0 dB
   (inclusive); (b) the simulated SSMF BER is above 3.8e-3 at every published SSMF ROP at most -5 dBm of that rate
   (error-counted BER; a point with zero errors reads "below 1/N" and fails (b)). The comparison is with the stated
   prose value, not the workbook penalty, which is reported beside it. C3 is scored at zero chirp (A1.2).

### D4. The sample grid (corrects the N2 report's "multiple of 8")

At 70 GSa/s the PAM4 rates 80, 100 and 112 Gb/s are 40, 50 and 56 GBd, giving 1.75, 1.40 and 1.25 samples per symbol. A
periodic grid needs an integer number of samples: the symbol count must be a multiple of 4 (1.75 and 1.25) and of 5
(1.40). A multiple of 8 is wrong for 1.40 (8 x 1.4 = 11.2); a multiple of 20 works for all three, and the declared
capture length (D2) is one. `resample_periodic` rounds silently, so N3 asserts an integer sample count and refuses
otherwise.

### D5. Fig.4 points above -5 dBm are flagged on return

The importer now exposes `NanfSeries.above_rop_cap`, True where a Fig.4 ROP is above -5.0 dBm (exactly -5.0 is scored).
The B2B series carry such points (excluded from the fit and from scoring by A4). The fit and scoring code drops flagged
points and must not rely on the caller remembering to. The flag is derived from the ROP axis, not from any BER or SNR value.

### D6. The holdout read is tied to the freeze hash (requirement; implemented in N3)

`read_nanf_workbook(include_holdout=True)` is a bare flag and `expected_sha256` is set by the caller; that is acceptable
only because no freeze exists and the only real-data use is a schema test that prints nothing. At N3, before any
holdout value is returned, the read must take proof of the freeze hash (the hashed Tx/Rx vector, the code identity and
this plan's pin, recorded in a committed freeze record; compare `FrozenCriterion` in `src/opticps/benchmarks/holdout.py`)
and refuse without it. A bare `include_holdout=True` is then an error. Until N3 it is a requirement, not a mechanism.

### D7. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning",
the 6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, and the rule that no criterion is
dropped, relaxed or added after a number is seen except by a dated amendment with a new pin. OFDM (C6 to C8) is outside
the scope of this amendment.

## Amendment 5 (2026-11-01, Gate N3 part a, step 1: grid, counts, declared simulation assumptions)

Previous SHA-256 of this file, pinned until now (Amendment 4, commit 7bd6ab9):
`bc85d32c0fa3264034bfeb87872950ed2a8e7a4105b53b84c7b6256c10d17dbe`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; the text before the
Amendment 4 heading still hashes to the Amendment 3 pin `0a3897ad...f2c4`, and a test checks that, and now also that
the text before this heading hashes to the previous pin). Where this amendment and anything above differ, this
amendment governs. It is written before any scoring run and before any fit: no fit, no simulation of the paper's
curves and no model comparison has run, and no Fig.4, Fig.6 or Fig.8 value and no holdout value has been printed or
compared with a model. No tolerance or threshold of section 4, A3 or B1 to B3 is changed.

### F0. What had been seen (adds to A0, B0.2 and D0)

In this gate the paper PDF (prose, not the workbook) was reread for the DSP chain of Sec. III-B: the SRRC roll-off is
0.1; the PAM4 signal is 70 times up-sampled, filtered, then 40, 50 or 56 times down-sampled for the 70 GSa/s AWG; the
receiver re-samples, match-filters and uses a T/2-spaced (17,7)-tap DFE with RLS and forgetting factor 0.998, then
counts errors. The prose gives no tap split, no training length, no initialisation, no symbol pattern, no capture
length, no DAC resolution and no scope timing phase. No workbook cell was read in this step.

### F1. The sample grid (corrects D4 and the capture length of D2)

D4 says a multiple of 20 serves all three rates. That holds at 70 GSa/s only. The simulated chain also runs on a
280 GSa/s analogue grid and samples at 80 GSa/s (F4), and the symbol count N must make every sample count an integer
(no rounding). Samples per symbol are fs / Rs, so N x fs / Rs must be an integer:

| Rate | Rs (GBd) | 70 GSa/s (AWG) | 280 GSa/s (analogue) | 80 GSa/s (scope) | 2 sps after resampling |
|---|---|---|---|---|---|
| 80 Gb/s | 40 | 7N/4 | 7N | 2N | 2N (ratio 1) |
| 100 Gb/s | 50 | 7N/5 | 28N/5 | 8N/5 | 2N (ratio 5/4) |
| 112 Gb/s | 56 | 5N/4 | 5N | 10N/7 | 2N (ratio 7/5) |

The denominators are 4 and 5 (at 70 GSa/s), 5 (at 280), and 5 and 7 (at 80); the 280-to-80 ratio 2/7 gives
(28N/5) x 2/7 = 8N/5 and 5N x 2/7 = 10N/7 (needs 7 divides N at 56 GBd). So N must be a multiple of
lcm(4, 5, 7) = 140. The earlier length 655360 = 20 x 32768 is not (655360 x 10/7 = 936228.57). The capture length of D2
is replaced by 655200 symbols = 140 x 4680 per point; the first 8192 are equaliser training and are not scored, so
647008 symbols and N_b = 2 x 647008 = 1 294 016 bits are scored. The chain refuses (raises) any N that is not a
multiple of 140, and any resampling whose output length is not an exact integer.

### F2. Error counts, and the unit of N (corrects D2 and D3.3)

N is a number of PAM4 symbols; N_b = 2 x (N - 8192) is the number of scored bits (Gray mapping, 2 bits per symbol).
BER = bit errors / N_b. The D2 sentence "655360 gives about 65 errors at BER 1e-4" was wrong. At BER 1e-4 the scored
bits give 1 294 016 x 1e-4 = 129.4 bit errors; with Gray mapping nearly every symbol error is a single bit error, so
that is also about 129 symbol errors (SER about 2e-4). 65 would be the number at BER 5e-5. The report string
"below 1e-4 (at most 65 errors)" is replaced by "below 1e-4"; a simulated point with zero bit errors reads
"below 1/N_b" (N_b = 1 294 016, that is below 7.7e-7); for the simulated BER a point below 1e-5 is censored by the
same rule as a published one (A3). "Below 1/N" of D3.3 means below 1/N_b. About 1e7 bits (5e6 symbols) are needed
for 100 bit errors at BER 1e-5; the N2 report's "1e7 symbols" is corrected.

### F3. RIN (corrects the note of D2)

D2 says any intensity noise is absorbed by `electrical_snr_ceiling_db`. That overstates. A ROP-independent additive
white ceiling has the shape of a RIN-limited SNR (which is also independent of received power), but it does not absorb
noise that scales with the signal or with the dispersion: level-dependent intensity noise at the modulator, and the
phase-to-intensity conversion of laser phase noise by chromatic dispersion in the SSMF. Neither is modelled, so the
simulated SSMF SNR is biased optimistically (direction known, size unknown); RIN stays zero, `user-assumed`.

### F4. Declared items of the simulation (adds to D2; each `user-assumed`, none is a free parameter of B4)

1. Symbol generator: `numpy.random.default_rng(20261101).integers(0, 4, size=N)` (PCG64), the index of the PAM4
   level (-3, -1, 1, 3), the same sequence at every rate, link and point.
2. Noise seed policy: at every point a separate PCG64 generator, `numpy.random.default_rng(numpy.random.SeedSequence(
   [20261101, 7919, Rs_in_GBd, point_index]))`, where `point_index` is the integer index of the point on the published
   axis. Standard-normal arrays are drawn in this order: shot noise, thermal noise (both on the 280 GSa/s grid), then
   the ceiling noise (on the 80 GSa/s grid). The stream does not depend on the link, so B2B, NANF, SSMF and the
   no-fibre run of d share the same standard-normal draws at one point (common random numbers).
3. Analogue oversampled grid: 280 GSa/s (4 x 70, 3.5 x 80); Tx and Rx filters are the 4th-order Butterworth magnitude
   response of the existing `lowpass` (zero phase, no group-delay distortion), at the bandwidth parameters of B4.
4. AWG: ideal band-limited reconstruction of the 8-bit quantised 70 GSa/s waveform (zero spectral padding to 280 GSa/s,
   no sinc roll-off, no clock leakage); the analogue bandwidth of AWG, driver and modulator is `tx_bandwidth_ghz`.
5. Modulator: the existing sine-law MZM; peak-to-peak drive = `modulation_depth` x V_pi; bias = `bias_fraction` x V_pi;
   extinction 30 dB (repository default). Not predistorted. Zero chirp (A1).
6. Power protocol: matched received power (the mean received power equals the ROP of the point); responsivity 0.8 A/W
   (D2); shot noise on; thermal noise white with `thermal_noise_pa_per_rthz`, added before the Rx filter.
7. Scope: ideal band-limited resampling 280 to 80 GSa/s (brick-wall at 40 GHz, no aliasing); no scope quantisation
   or jitter; the scope clock phase is zero (timing phase below). `electrical_snr_ceiling_db`: white Gaussian noise at
   the 80 GSa/s scope output of variance P_ac / 10^(ceiling/10), P_ac the variance of the noise-free scope waveform.
8. Receiver front end: resample (exact rational) to 2 samples per symbol, remove the mean, scale to unit mean square
   (the equaliser learns the gain), zero-phase SRRC matched filter (roll-off 0.1) at 2 samples per symbol.
9. Timing phase: zero. Symbol k is centred at sample 2k of the 2-sps grid; there is no clock recovery and no offset.
   Fractional-symbol timing is left to the T/2 feed-forward taps.

### F5. D1 wording (replaces one phrase; the rule is unchanged)

D1 says the six SSMF points above -5 dBm are "at the rounding of the published column". The column has 0.01 dB
resolution and the points are 0.01 to 0.02 dB above -5 dBm, so this is scatter of the published operating point about
the stated cap, not rounding. The phrase is withdrawn; C5 still scores all 17 wavelengths and reports the six apart.

### F6. DFE unknowns, declared (the (17,7) taps, RLS and 0.998 are the paper's; everything below is `user-assumed`)

| Item | Declared value |
|---|---|
| Tap split of (17,7) | 17 feed-forward taps at T/2 spacing and 7 feedback taps at symbol spacing |
| Feed-forward cursor | 8 taps before and 8 after the symbol instant (cursor index 8 of 0 to 16) |
| Algorithm | exponentially weighted RLS, forgetting factor 0.998, decisions fed back |
| Training | the first 8192 symbols, known data in the desired signal and in the feedback taps |
| Switch | after 8192 symbols the desired signal and the feedback are the slicer decisions (levels -3, -1, 1, 3; thresholds -2, 0, 2); adaptation continues to the end of the capture; no freeze |
| Initialisation | all taps zero; inverse correlation matrix P(0) = I / delta |
| delta | 1e-2 (input scaled to unit mean square, F4.8) |
| Stability | rank-one update in a form that keeps P exactly symmetric, an explicit symmetrisation, and a cap on trace(P); neither changes the result when P stays bounded |

### F7. Scoring definitions completed (adds to D3; none changes a tolerance)

1. A published or simulated BER is censored if it is not finite or below 1e-5 (A3); a simulated zero-error count is
   censored.
2. C1 with a bound or interval on either side (completes B1.3). Each result is a region of the ROP axis: a crossing is a
   point; "at or below r0" is (-inf, r0]; "above r0" is [r0, inf); an interval is [lo, hi]. The published region is
   widened by 1.0 dB on each finite side. A simulated point must lie in it. A simulated bound is read at its first (left)
   or last (right) scored ROP, as B1.3 says. A simulated interval passes if any part of it lies in the widened published
   region. A bound or interval on either side is never discriminating.
3. C4 with a simulated zero-error point against an uncensored published BER of at least 1e-5: the simulated BER is below
   1/N_b = 7.7e-7, so the log10 difference exceeds 1.1 and the point counts as outside 0.5. A published censored point is
   scored only as "simulated BER below 1e-4" (A3) and is not counted in the 80%.
4. C7 loading algorithm (A3 requires it fixed before scoring): bit loading only, no power loading, the same for both
   fibres. For subcarrier SNR_k, the number of bits is the largest of 2, 4, 6, 8 (square QAM of order 4, 16, 64, 256) for
   which the Gray bit-error approximation (4 / log2 M) (1 - 1 / sqrt(M)) Q(sqrt(3 gamma / (M - 1))) is at most 3.8e-3 at
   gamma = 10^(SNR_k/10), else 0. The paper's loading adds power loading; the difference is a known mismatch and is not
   tuned. Capacity is sum(bits_k) x 70 GSa/s / 512 over the 240 subcarriers, as in A3.
5. C5 scores wavelengths 1460 to 1620 nm (B2); 1630 and 1640 nm are reported apart and never scored.

### F8. The holdout read and the freeze record (the mechanism of D6)

The freeze record is the JSON file `docs/benchmarks/NANF_FREEZE_RECORD.json`; it does not exist at this amendment and
nothing is frozen by it. Its fields: `plan_sha256` (the pin of this file at freeze time), `code_identity` (SHA-256 of the
lines `path NUL sha256(file)` for the files `src/opticps/receiver/dfe.py`, `src/opticps/measurement/nanf_chain.py`,
`src/opticps/measurement/nanf_scoring.py` and `src/opticps/measurement/nanf_freeze.py`, in that order), `parameters`
(exactly the six names of B4, each inside its allowed range), `unidentifiable` (the names flagged by B4, a subset),
and `freeze_hash` (SHA-256 of the canonical JSON of the other four fields: sorted keys, separators "," and ":", UTF-8).
`read_nanf_workbook(include_holdout=True)` needs the caller's `freeze_hash` and refuses with `HOLDOUT_LOCKED` unless the
record exists at that path, its stored hash equals the hash recomputed from its fields and the caller's value, its
`plan_sha256` equals the SHA-256 of the plan file read now, its `code_identity` equals the code identity computed now, and
its parameters are valid. A bare `include_holdout=True` is an error. That the record file is committed to Git before
the read is a process requirement, not checked by code.

### F9. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning",
the 6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, and the rule that no criterion is
dropped, relaxed or added after a number is seen except by a dated amendment with a new pin. OFDM transmitters and
the OFDM simulation chain are not implemented; only the scoring arithmetic of C6 to C8 is.

## Amendment 6 (2026-11-01, Gate N3 part a fix round after the independent review of N3 part a)

Previous SHA-256 of this file, pinned until now (Amendment 5, commit bd5a557):
`c5da4067f6c58cf4d9ddc9372cad79dd0e63e4f74d70374e8a0241cd1e06dcff`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; this amendment adds lines and
removes none, and a test checks that the text before this heading hashes to the previous pin). Where this amendment and
anything above differ, this amendment governs. It was made before any calibration and before any holdout scoring: no
fit has run, no freeze record exists, no calibration artefact exists, and no Fig.4, Fig.6 or Fig.8 value and no holdout
value was used for any change below. The synthetic evidence for each change comes from the first review of N3 part a
(`handoff/N3a_qa.md`, findings 1 to 11, with its repro scripts on synthetic data and the mid-point B4 vector), reproduced
in this round on the same synthetic chain; where this round added a measurement of its own it is labelled. No tolerance or
threshold of section 4, A3 or B1 to B3 is changed, the label **`LITERATURE BENCHMARK / CALIBRATION ONLY`** stays, C6 stays
pre-registered as an expected FAIL at 2.0 GHz, and chirp stays unfitted (A1).

### G0. What had been seen (adds to A0, B0.2, D0 and F0)

Nothing from the workbook beyond the disclosures already recorded. One event of the same class as D0 is disclosed in G7:
a test that parsed the withheld series in process on every full run in a checkout holding the data. No holdout value is
known to have been printed or recorded; G7 gives the evidence and its limits.

### G1. The trace cap of the RLS is pinned at 1e10 (replaces the Stability row of F6)

F6 said "a cap on trace(P); neither changes the result when P stays bounded". That is wrong for the cap that was coded
(1e4), and the sentence is replaced. Evidence (review finding 1, reproduced here with identical error counts; synthetic,
mid-point vector, 1 294 016 scored bits):

| Point | errors, cap 1e4 | errors, cap 1e10 | errors, no cap (1e300) | largest trace(P), uncapped |
|---|---|---|---|---|
| 100 Gb/s B2B, -9 dBm | 4639 (BER 3.585e-3) | 5144 (3.975e-3) | 5144 | 2.77e8 |
| 112 Gb/s NANF, -7 dBm | 141 (1.09e-4) | 173 (1.34e-4) | 173 | 3.90e8 |
| 112 Gb/s SSMF, -5 dBm | 75 (5.8e-5) | 81 (6.3e-5) | 81 | 7.91e8 |
| 80 Gb/s B2B, -12 dBm | 72203 (5.58e-2) | 80298 (6.21e-2) | 80298 | 1.81e8 |

At cap 1e4 the cap acted on 653 447 to 653 520 of 655 200 symbols; at 1e10 and with no cap it never acted. The caps 1e10
to 1e300 give identical decisions. The effect on the outcome is real: at 100 Gb/s B2B -9 dBm the BER is 3.585e-3 at cap
1e4 and 3.975e-3 without a cap, on opposite sides of the threshold 3.8e-3. The rule now is:

1. `p_trace_cap` is fixed at 1e10 (`PINNED_P_TRACE_CAP`), the default of the equaliser, so the equaliser that runs is the
   plain exponentially weighted RLS with forgetting factor 0.998. At every run that held lock in the synthetic sweep of
   G1.4 the largest trace(P) was 1.1e8 to 8.3e8 (mid-point vector; 1.2e9 at most at the corners of the B4 box).
2. A run in which the cap acts (`n_trace_caps > 0`) is invalid. `simulate_point` raises `TraceCapActedError` for it; a
   diagnostic run (below) is marked and can never score. A result is `scorable` only for the declared chain: default chain
   configuration, default equaliser with the pinned cap, noise on, the cap never acted, not a diagnostic run. Scoring takes
   points through `require_scorable`, which refuses anything else. There is no route to raise or lower the cap in a scoring
   run: a different cap, equaliser or configuration is accepted only for a diagnostic result that cannot score.
3. Tests: the real chain at 100 Gb/s B2B -9 dBm with cap 1e10 against no cap (same decisions, same errors, 0 caps, and
   the first scorable, the second not); a run whose cap acts cannot score; a lowered pin makes the pinned run raise.
4. Measured in this round (synthetic, mid-point vector, 3 rates x 3 links x ROP -16 to -5 dBm in 1 dB steps, cap 1e300):
   86 of 108 runs held lock with 0 caps and trace(P) below 8.3e8. 22 runs did not: the decisions collapse (BER 0.23 to
   0.48, SNR near 0 dB where measured) and trace(P) grows past 1e10, so at the pinned cap the cap acts in 12 of them
   (32 608 to 514 537 times) and P loses positive definiteness (`RlsInstabilityError`) in the other 10; with no cap
   (1e300) the same 22 runs also fail. All 22 lie at least 3 dB below the 3.8e-3 crossing of their own curve, at the noise-limited end where that curve is
   above BER 0.05. The corner of the B4 box with 10 GHz bandwidths, modulation depth 0.2 and a 15 dB ceiling lost lock at 17
   of 18 points, even at -5 dBm. At 1460, 1500, 1580 and 1620 nm, -5 dBm, all 24 runs (NANF and SSMF, 3 rates) held lock
   with 0 caps (trace(P) at most 8.3e8). Such a run is an invalid evaluation: it is not scored, never substituted, and in a
   calibration it is an invalid evaluation of that vector. This amendment does not decide how a criterion that needs such a
   point is read, because it was not checked whether any published ROP axis contains one (no workbook axis was read); that
   is reported to the owner before the freeze.

### G2. No crossing in the common ROP range (resolves B1.3 against F7.2)

B1.3 says a simulated curve with no crossing fails a published rate with a bracket; F7.2 says a simulated bound is read at
its first or last scored ROP. They differ when the published crossing is a point and the simulated curve has no crossing in
the common ROP range (a left or right bound). The rule is: **the criterion FAILs, and this resolves B1.3 against F7.2 in
favour of B1.3.** F7.2's reading of a bound at its first or last ROP applies only where the published side is itself a
bound or an interval. Review repro (finding 2, synthetic): published point at -12.4 dBm, simulated left bound at -13 dBm,
code FAIL, literal F7.2 would PASS (-13 lies in the widened region [-13.4, -11.4]); the repro is now a test, with the
end-to-end curve that produces it.

### G3. Default deny for BER values (corrects F7.1)

F7.1 said a BER is censored if it is "not finite or below 1e-5". That text is replaced. Only a finite BER below the
declared floor 1e-5, zero included, can be censored (a simulated BER comes from an error count, so it is finite and in
[0, 1]). NaN, infinity, a negative value and a BER above 1 are invalid data and the criterion FAILs, for a simulated series
and for the B2B-copy comparator alike, and D3.1 stays honoured (only uncensored B2B points are BER nodes; an unbracketed NANF
ROP is reported and not scored, it is never read as a censored point). One class of NaN is not invalid: the importer's
published series carry NaN where the workbook cell was zero, below 1e-5 or "-Inf", with a flag (N2), and in a published
series NaN is that flagged censored cell; infinity, negative values and values above 1 are invalid there too. In code an
invalid curve gives a crossing of kind `invalid`, which fails against any published crossing; C3, C4, the B2B copy and the other
functions refuse invalid values with an error, so that none can contribute to a pass. Review evidence (finding 3,
synthetic): an all-NaN simulated curve gave a left bound that passed a published left bound, and [1e-1, 5e-3, NaN, NaN] gave an
interval that passed a published point at -10.16.

### G4. The freeze record binds a named calibration artefact (strengthens F8)

The record of F8 gains three fields and the checks below; its seven fields are `plan_sha256`, `code_identity`,
`parameters`, `unidentifiable`, `calibration`, `calibration_partition_sha256` and `freeze_hash`, the last being the
SHA-256 of the canonical JSON of the other six. `calibration` is an object with `path` (a `.json` file under
`docs/benchmarks/`, relative, without `..`), `sha256` (SHA-256 of that file) and `commit` (the 40-digit commit that holds it).
The artefact has exactly the fields `parameters` (the six names of B4, the vector that is hashed), `unidentifiable`,
`fit_result` (`method`, `converged`, `n_evaluations`, `n_calibration_points`, `cost`) and `calibration_partition_sha256`. A
record is refused (`HOLDOUT_LOCKED`) if the artefact is absent, a symbolic link or too large; if its SHA-256 differs from the
record; if it is not tracked by Git or differs from HEAD (uncommitted); if the named commit does not hold exactly those bytes
at that path or is not an ancestor of HEAD; if it holds no fit result, or the default vector with no fit result, or a fit
result that is not valid; if its vector, flags or partition differ from the record; if a flagged parameter is not at its prior
of B4.4 (checked on the record and on the artefact, and when the record is built); if the partition differs from the
importer's calibration partition now (SHA-256 of the sorted lines `key TAB role` of the 21 non-holdout series: Fig.1, Fig.5
and the six B2B series of Fig.4); or if the record is malformed in any way. Malformed includes a 400-digit integer, deep
nesting, wrong types, duplicate keys, extra or missing fields and a size over 65 536 bytes; every one gives
`HOLDOUT_LOCKED`, never a raw `OverflowError` or `RecursionError`. If `git` cannot be run the record is refused.

What this does not prove. The checks make an accidental or casual freeze detectable and a freeze without a calibration
impossible to forge by editing one file. They do not prove order. Records inside the repository cannot prove that the
calibration was complete before the holdout was first read, because commit dates and authors are typed by whoever commits
and history can be rewritten; only an external timestamp can give a date proof. This is the promise of
`docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md` and it is not widened here: the guard catches accidents and casual re-tuning
by ordinary commits, and does not stop deliberate tampering by someone who controls the repository. That the record file is
committed to Git before the holdout read remains a process requirement.

### G5. The code identity is computed from imports; `simulate_point` obeys the record (amends F8)

The `code_identity` of F8 listed four files. It is now the SHA-256 of the lines `path NUL sha256(file)`, in sorted path
order, over every source file reachable by imports from the scoring entry modules (`dfe`, `nanf_chain`, `nanf_scoring`,
`nanf_freeze`, `nanf_import`, `nanf_benchmark`, `link`, `fiber`), found by parsing the imports (function-level and
`TYPE_CHECKING` imports included, and the `__init__.py` of every parent package), not from a hand list; with `pyproject.toml`
and `uv.lock`. The plan file is pinned by `plan_sha256` as before. Editing any of these files after the freeze relocks the
holdout; a test edits each file of the computed set in turn. Review evidence (finding 5, synthetic): changing the Butterworth
order in `link.py` and editing `nanf_import.py` left the old identity unchanged. Dynamic imports (`importlib`) are not followed;
this is a listed limit. After a freeze (any file at the committed record path) `simulate_point` loads and verifies the record
on every call and uses its vector; a different vector, a chain configuration, an equaliser or `noise=False` is refused
(`FrozenOverrideError`); only a diagnostic run, which cannot score, may differ.

### G6. The real workbook is unlocked only by the committed record

`read_nanf_workbook` checks the workbook hash before parsing; when it is the real workbook's recorded SHA-256 the proof is
read from the committed path `docs/benchmarks/NANF_FREEZE_RECORD.json` and from no other, so a record in a temporary directory,
as the synthetic tests use, cannot unlock the real file. The autouse fixture of `tests/test_nanf_import.py` applies to
synthetic workbooks only (its helper refuses the real path), and the test that read the real workbook with
`include_holdout=True` is replaced by a test that the real file refuses with `HOLDOUT_LOCKED` before it is opened, plus a
test that a test-only record cannot unlock a file carrying the real hash. A truthy `include_holdout` that is not `True` is
guarded like `True`. Because the default read of the real workbook parses every sheet in process and then withholds the
holdout series, the test that did the same (G7) is removed and not replaced by a default read of the real file; the layout
facts it checked (counts of series per sheet, flagged cells) remain covered on the synthetic workbook.

### G7. Disclosed event: a test read the withheld series of the real workbook in process

Found by the first review of N3 part a (finding 6) and investigated in this round by reading the code and the Git history
only; the workbook was not opened and no test that opens it was run before the test was replaced.

- Which commits. `test_the_real_workbook_matches_the_recorded_layout_schema_only` was added in `ba55025` (N2) and kept its
  body at `7bd6ab9` (N2 fix round) and `b7f4ac0`: `read_nanf_workbook(REAL, include_holdout=True)`, with the real path
  `data/external/nanf_hong2021/extracted/dataset_JLT_NANF_vs_SMF.xlsx`. It was skipped when that file is absent. At `b7eaab5`
  (N3a) the same call carried `freeze_hash=` the hash of a test-only record that an autouse fixture put on the record
  path, so under N3a it also defeated D6 and F8 for the real file. In a checkout that holds the file (the main checkout of the
  project does; `data/external/` is ignored by Git) every run of that test, therefore every full run of the suite, parsed all
  69 series including the 48 holdout series into process memory. The second review of N2 recorded a run with the workbook
  linked (`handoff/N2_qa2.md`: 75 tests passed, no skip, at `7bd6ab9`); the N2 and N3a development runs in the main checkout
  probably did the same (their handoffs do not say whether the data was linked, so this is not confirmed). This round ran
  nothing of the kind.
- What the test did with the values. It held them as `NanfSeries` tuples and asserted: the workbook SHA-256; 69 series;
  for every series equal lengths of `x`, `y` and flags, a non-empty series and finite `x` (the axis column, ROP, wavelength or
  frequency); the count of series per sheet name (Fig.1 12, Fig.4 18, Fig.5 3, Fig.6 18, Fig.7 4, Fig.8 2, Fig.9 4, Fig.10 2,
  Fig.11 2, Fig.12 4); `n_non_finite` of the Fig.11 `240sub-SMF-DMT` series equal to 24 and the total equal to 24; `n_censored`
  equal to 0 for every non-BER series; then the default read has 21 series and 48 withheld, none with the holdout role. So
  counts, sheet names, lengths, finiteness of axis values and flag counts were asserted; no assertion compared a y value
  (BER or SNR) with anything.
- Could a value have reached output. On a passing run nothing is printed by the test. On a failing assertion, pytest prints
  the operands it rewrites; `all(math.isfinite(v) for v in s.x)` could print an axis value of one series and the dictionary
  comparison prints counts. No failure of this test is recorded: the cache of the last run in the main checkout lists other
  failures and not this test (a cache that holds failures only, so it does not prove that the test ran). I cannot exclude that
  a run in some session, not recorded, failed and printed such a line, and I cannot exclude that a reviewer or agent
  displayed series values interactively; I found no record of either.
- Search for values in records. `handoff/`, `docs/`, `reports/` and the logs under the project were searched for the figure
  names of the holdout sheets, together with numeric tokens, without opening the workbook. The only hits are the counts and
  ranges already disclosed (A0, B0.2, D0, `N0_dev.md`: counts of ROP points per figure and the 22.15 to 25.43 GHz band of the 24
  flagged Fig.11 cells; `N0_qa.md`: one raw cell, Fig.11 C164, shown in passing during N0, disclosed there). No BER or SNR value
  of a holdout series was found in any of them. The search can only find what looks like a figure name next to a number; it is
  not proof of absence.
- Standing of the record. Amendment 4 D6 said "the only real-data use is a schema test that prints nothing". That was accurate
  about printing and silent about the test parsing the withheld series on every full run in a checkout with the data, and
  N3a made it run under a fake proof. The plan's holdout discipline was therefore weaker in practice than stated from `ba55025`
  on. The event is disclosed here whatever its effect; no calibration or score depends on it, none had been made.

### G8. Corrections of review findings 8 to 11

1. F2 report string: a simulated BER from 1e-5 up to but not including 1e-4 (13 to 129 bit errors at 1 294 016 bits) reads
   "below 1e-4"; the number stays in the result for scoring. Zero errors still reads "below 1/N_b" and below 1e-5 stays
   censored. BER exactly 1e-5 is not censored (A3: below 1e-5).
2. C4: a simulated point that is censored (zero errors, or non-zero but below 1e-5, so with no usable magnitude) against an
   uncensored published BER counts as a miss, never within (this declares the case F7.3 left open for non-zero values; it is
   the stricter reading, default deny). A NaN ROP is refused instead of silently dropping a point. A point at exactly -5.0 dBm
   is scored.
3. C3(b): the simulated SSMF BER must lie in [0, 1]; a value of 2.0 is invalid data. The test stays strictly above 3.8e-3.
4. `overall_verdict` accepts only boolean inputs; a truthy string or NaN is refused. `Crossing` is validated (kind, finite
   point, ordered interval, no NaN except `invalid`); a published point at infinity no longer passes anything.
5. C5: only 1630 and 1640 nm may lie outside the 17 wavelengths of B2; any other wavelength above 1620 nm (for example 1700 nm)
   is refused instead of being filed as excluded.
6. C7: `capacity_gbps` requires exactly 240 subcarriers (F7.4).
7. `b2b_copy`: invalid input is refused; an unbracketed NANF ROP is dropped for the copy's C1 (`copy_crossing`), not read as
   a censored point (D3.1).

### G9. Declared items of the chain that F4 did not state

1. `np.clip(., -1, 1)` is applied to the waveform after the band-limited up-sampling from 70 to 280 GSa/s and before the Tx
   filter, because the brick-wall interpolation of the quantised waveform can overshoot full scale. `user-assumed`, not a
   free parameter.
2. B6: the simulator SNR has a 0 dB floor at low SNR from the MMSE bias of the equaliser output; it is not tuned away.
3. Cost estimate for all planned figures (measured on the development machine, one core, one full-size point 14 to 16 s;
   about 40 s per point when six run at once, so about 2.2 times faster with six processes): Fig.4, 3 rates x 3 links x 11 ROP,
   99 points; Fig.6, 3 rates x 3 links x 17 wavelengths, 153 points; the no-fibre runs of d, 33 points for C1 and C2 and 51 for
   C5, 84 points; total 336 points, about 90 minutes on one core and about 40 minutes with six processes. One calibration
   evaluation is the 33 B2B points of Fig.4 (about 9 minutes on one core), and the identifiability check of B4 needs 12
   evaluations (about 1.8 hours on one core). OFDM (C6 to C8) is not implemented and is not in these numbers.

### G10. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning", the
6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, C6 pre-registered as an expected FAIL at 2.0
GHz, chirp unfitted, and the rule that no criterion is dropped, relaxed or added after a number is seen except by a dated
amendment with a new pin.

## Amendment 7 (2026-11-02, Gate N3 part a, lost-lock runs: the owner's ruling on G1.4)

Previous SHA-256 of this file, pinned until now (Amendment 6, commit 263926a):
`2127d883702715a3432cb8d25ed2f5a970a8910b46368ad2ed50cb8905f60905`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; this amendment adds lines and
removes none, and a test checks that the text before this heading hashes to the previous pin). Where this amendment and
anything above differ, this amendment governs. It was made before any calibration and before any holdout scoring: no fit
has run, no freeze record or calibration artefact exists, and no workbook ROP axis, Fig.4, Fig.6 or Fig.8 value or holdout
value was read for it. The synthetic evidence is the sweep of G1.4 in Amendment 6. The trace cap stays pinned at 1e10 and
is not moved. No tolerance or threshold is changed; the label **`LITERATURE BENCHMARK / CALIBRATION ONLY`** stays.

### H1. A lost-lock run is invalid, reported, and never silently skipped

A lost-lock run is a run in which the trace cap acted, or `RlsInstabilityError` was raised, or both (G1.4). It is invalid.
It is never scored and never skipped silently: it stays in the sweep as an outcome with its point (rate, link, ROP) and its
reason, and a report lists every such point. In code `run_point` returns it as a lost `PointOutcome` (no result); any other
error still raises; `curve_arrays` keeps it in place, flagged invalid, with NaN as its value (never zero, never a censored
BER); and the scoring functions take that flag as `valid` and ignore the stored value.

### H2. The crossing of C1 from a locked bracket only

With a lost-lock point on the curve, the simulated crossing (C1-R) is computed only from the highest contiguous run of locked
points, and only if that run brackets the threshold 3.8e-3 as a point. Lost points below that run, on the noise-limited side,
do not affect the crossing; the number lost is reported with it. Nothing is interpolated across a lost point. If a lost point
lies above the run, if no locked point exists, or if the locked run has no bracket (it is all above or all below the threshold,
or the bracket would lie across a lost point), the simulated crossing is invalid and the criterion FAILs under the no-crossing
rule of G2. The reason and the count of lost points are carried by the crossing and by the score.

### H3. Criteria that need a specific point

A criterion that needs the value at a specific point FAILs if that point is lost: C2 (SNR errors at scored ROPs),
C3 (the penalty set and the SSMF BER of (b)), C4 (any scored point of the pooled series), C5 (any of the 17 wavelengths), and
the B2B gate on the calibration points. There is no substitution and no interpolation across the lost point, and no partial
credit from the remaining points. The failure carries the number of invalid points. A lost point above -5 dBm is not a scored
point (A3, A4) and does not fail a criterion. The discriminating measure d is undefined for an invalid crossing (`d_c1` gives none) and `d_snr` refuses a lost point.

### H4. Calibration

An objective evaluation that has a lost-lock point at a point the objective needs gets the worst-case objective (+infinity),
is counted and is logged line by line (`EvaluationLog`); it can never be selected (`select_best` skips it, and raises if no
clean evaluation exists). A fit whose chosen vector has lost-lock points in the Fig.4 B2B calibration grid is invalid
(`check_chosen_fit`), so no calibration artefact may be written for it (G4). Identifiability (B4): a residual evaluation at the
optimum or at any finite-difference step of the Jacobian that has a lost-lock point at a needed point makes the check
undefined: no Jacobian is formed, no worst-case value enters J, no parameter is flagged, and the calibration is not frozen
(`IdentifiabilityUndefinedError`, reported with the lost points). It is never repaired by a smaller step or a substitute value
in this plan.

### H5. What is not known

Which published ROP points lie in a lost-lock region is not known and is not decided here: no ROP axis of a holdout series
was read, and Amendment 7 decides nothing from one. It stays unknown until the scoring step, which will report every lost point
by H1. If a criterion then fails only through H2 or H3, the report says so and the failure stands; it is not repaired by a
change of the cap, the equaliser, the grid or any rule of this plan. Cost is as in G9.

### H6. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning", the
6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, the trace cap pin of G1 at 1e10, C6 pre-registered
as an expected FAIL at 2.0 GHz, chirp unfitted, and the rule that no criterion is dropped, relaxed or added after a number is
seen except by a dated amendment with a new pin.

## Amendment 8 (2026-11-02, Gate N3 part a, second review: holdout record corrected, Fig.11 excluded, guards closed)

Previous SHA-256 of this file, pinned until now (Amendment 7, commit d4a50d6):
`34a06373755c25167453da35225ab7b01dbc48af373344706e7bb000f736c623`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; this amendment adds lines and
removes none, and a test checks that the text before this heading hashes to the previous pin). Where this amendment and
anything above differ, this amendment governs. It was made before any calibration and before any holdout scoring: no fit
has run, no freeze record or calibration artefact exists, and no value of any holdout series was read for it. The trace
cap stays pinned at 1e10. The label **`LITERATURE BENCHMARK / CALIBRATION ONLY`** stays, C6 stays pre-registered as an
expected FAIL at 2.0 GHz, and chirp stays unfitted. The evidence is the second independent review of N3 part a
(`handoff/N3a_qa2.md`, findings 1 to 10) and its repro scripts on synthetic data.

### G-A. Correction of the holdout record (corrects G0, G7 and H5; finding 1)

Statements made earlier in this plan were false and are withdrawn:

- H5 said "no ROP axis of a holdout series was read". That is false for the project. G0 said "nothing from the workbook
  beyond the disclosures already recorded" and G7 said the only hits in the records were "counts and ranges already
  disclosed". Those are false too: the search behind them covered `docs/`, `handoff/` and `reports/` and not the agents'
  transcripts, and it was masked (it looked for figure names next to numbers).
- What an agent did see, at Gate N0 (2026-10-31) and not since: the ROP lists (the axis column, rows with a numeric value) of
  the Fig.4 `NANF-80`, `NANF-100` and `NANF-112` BER and SNR series; of Fig.9 `NANF-OFDM-*`; of Fig.12 `NANF-DMT *`; the Fig.4
  SMF ROP list (a column shared with the B2B series, so also legitimate calibration knowledge); the Fig.6 wavelength list; the
  frequency ends of Fig.8 and Fig.11; the per-cell present or absent masks of Fig.4, Fig.9 and Fig.12; and ONE y value, the
  Fig.11 `240sub-SMF-DMT` cell C164, in a raw XML excerpt (agent af0141). That value is not recorded here, was not used and is
  not used by anything in this plan. The review (`N3a_qa2.md`) found no other BER or SNR value of any holdout series in 142
  transcripts, with the limit that its scan masked non-integer numbers and was based on labels and print statements: it is not
  proof of absence, and neither is any search of this project.
- The earlier statement of the orchestrator that no value had reached an agent was also wrong. One y value did, and it is
  recorded here.
- The holdout read by code is also confirmed, not "probable" (G7): the main-checkout run of agent af805d at N2 reports
  `1541 passed` with no skip, so the old real-workbook test did parse all 69 series in process; and N2 agents a5a11b (counts,
  D0), a97d23 and a034b9 (shape checks) called `read_nanf_workbook(..., include_holdout=True)` directly on the real file. No
  failing run of that test appears in any transcript, so that part of G7 stands.
- Consequence for H5: with these axes and the G1.4 sweep, which points of a published curve fall in a lost-lock region is
  computable by anyone who has seen them. It is not computed here and no rule of this plan depends on it, but H5's "not known"
  must be read as "not decided here", not as "nobody could know".

Owner decision (2026-11-02): ROP axes are experiment design, not outcomes. The NANF holdout stays in use, disclosed as above.
It is not fully blind, and every N3 report must say so in the words "The holdout is not fully blind" (a test checks the
report for that string). No criterion is changed by this disclosure.

### G-B. Fig.11 is excluded from scoring

Owner decision (2026-11-02): all Fig.11 series (`240sub-NANF-DMT` and `240sub-SMF-DMT`) are excluded from scoring, because one
of its y cells was seen. In code the importer validates the sheet but never returns a Fig.11 series, with or without a freeze,
and `wb[key]` for a Fig.11 key is refused with the code `EXCLUDED_FROM_SCORING`. Effect on the criteria, exactly:

- No criterion of section 4, A3 or A5 takes its published side from Fig.11. C1 to C5 read Fig.4 and Fig.6; C6 reads Fig.8
  only (A5 moved it, and A5 says Fig.11 is not used); C7 reads the capacities of Fig.12; C8 reads Fig.7 and Fig.9. The only
  text that still names Fig.11 is the C6 cell of the section-4 table, "Fig. 8, 11", which A5 had already replaced.
- Therefore the exclusion removes no criterion, changes no tolerance or threshold, and removes no data that a criterion reads.
  C7 is unchanged. Nothing is chosen to replace Fig.11, and none is needed.
- What it does remove: the Fig.11 facts that were never criteria (its 24 error cells, its unloaded band of 22.15 to 25.43 GHz
  as a possible cross-check). They may still be mentioned as disclosed knowledge and are not used. The calibration partition
  (21 series) is unchanged. The count of holdout series a freeze unlocks is 46, not 48.

### G-C. A scorable result and the way to a score (corrects G1.2; finding 2) and the fibre after a freeze (finding 3)

The sentence of G1.2, "Scoring takes points through `require_scorable`, which refuses anything else", was inexact: only
`run_point` called it, and the `score_*` functions take bare arrays. It is replaced by: scoring arrays are produced only by
`curve_arrays`, which calls `require_scorable` on every non-lost result, so a changed cap, configuration, noise-off or
diagnostic result cannot reach a score through it; `PointOutcome` refuses an unscorable result; and unless
`calibration=True` (the B2B points of the fit before a freeze) every result must have used a verified freeze record, so
deleting the record does not make a vector scorable. The `score_*` functions remain pure functions of arrays and are as safe as
their caller; a caller that builds arrays by hand is outside this guarantee.

After a freeze, "no per-fibre retuning" and F4.2 are enforced as follows. `simulate_point` gives a scorable result only for the
back-to-back link or a link in `DECLARED_LINKS`, and only for a `point_index` in `DECLARED_POINT_INDICES` (both in
`nanf_chain.py`, so part of the code identity). Both are empty until part b declares them, so no run after a freeze is
scorable until then; the flag names this check in its reasons. A different fibre, another wavelength or another noise index
yields `scorable=False`.

### G-D. The freeze record (extends G4; finding 4)

- A fit result is accepted only as evidence of a converged calibration: `converged` true, at least 7 evaluations (one plus the six
  parameters), 9 to 33 calibration points (three rates, three to eleven scored B2B ROPs each) and a cost above zero.
- The artefact must record that the checks ran: `checks.chosen_fit_checked` true, `checks.n_lost_points_in_grid` 0, and the six B4
  eigenvalues, ascending and non-negative; the number of eigenvalues below 1e-3 of the largest (all six if the largest is not
  above zero) must equal the number of flagged parameters (B4.3). `unidentifiable: []` is therefore accepted only if the stored
  eigenvalues support it. This records that `check_chosen_fit` and the B4 check ran; it does not prove it (it is a record).
- A repository with `.git/info/grafts` is refused (`nanf_freeze` now does what the known-limits text says of the tool).
  Replace refs are not honoured (`--no-replace-objects`), and a test makes a replace ref that would otherwise create an ancestor.
- Stated limits, unchanged: a record rebuilt after a rewrite of history is unprovable; the record file itself being committed is
  a process rule (G4), and an untracked record is accepted by the code; order, dates and tampering by the owner of the repository
  remain unprovable without an external timestamp. Deleting the record makes a vector unscorable for scoring, as in G-C.

### G-E. Further closures (findings 5 to 10)

1. H3 for points above -5 dBm: a lost point above the cap, or a NANF point outside the C3 ROP set, no longer fails C3 and no
   longer raises; every scored SSMF point and the NANF points of the ROP set are needed. `b2b_gate` takes the ROP axis and drops
   points above -5 dBm; a validity mask without the axis is refused.
2. `run_point` refuses a changed trace cap (`NotScorableError`); it is a refusal, not a lost-lock run. A published curve has no
   lost points, and `valid` with `published=True` is refused.
3. Mutants: the eight survivors of the second review are killed by tests (each with its own mutant in the list), none declared
   equivalent. A single cap action is an invalid run.
4. The wall-clock assertion of the full-size point test is replaced by a check that every stage was timed and that the stage
   times are consistent with the wall clock; timing is not a correctness property.
5. Standing exception (finding 9): three tests of `tests/test_nanf_benchmark.py` do a default read of the real workbook, which
   parses all 69 series in process and returns 21: `test_the_simulated_zero_chirp_nulls_meet_the_predeclared_tolerance_of_a1_3`,
   `test_the_report_numbers_are_current_with_the_recomputation` and
   `test_the_default_read_for_the_benchmarks_never_returns_a_holdout_series`. No assertion or print touches a holdout value, and
   they skip when the data is absent. They are kept as a named standing exception, of the same kind as the event of G7 in that
   the holdout is parsed before a freeze, and narrower in exposure; the owner decision of G-A covers them.
6. Code identity limits (finding 10): the identity follows imports found by parsing; it does not follow `importlib`,
   `__import__`, `importlib.util.spec_from_file_location` or `exec` and `eval` of source, none of which occurs in the reachable
   files today. It now also binds `configs/fibers/*.yaml`, so a fibre profile edit relocks.
7. The handoff cites the commits on the branch (`d4a50d6`, `869effc`, `dafa062`), not the commits of the scratch clone.

### G-F. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning", the
6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, the trace cap pin of G1 at 1e10, the rules of
Amendment 7, C6 pre-registered as an expected FAIL at 2.0 GHz, chirp unfitted, and the rule that no criterion is dropped,
relaxed or added after a number is seen except by a dated amendment with a new pin.

## Amendment 9 (2026-11-02, Gate N3 part a, closing review: typed flags replaced by checks)

Previous SHA-256 of this file, pinned until now (Amendment 8, commit 6d46ecb):
`2f56696f0398bd5bbd8f306bde536657bb380f4b886929e63d605e0cbcabf4c6`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; this amendment adds lines and
removes none, and a test checks that the text before this heading hashes to the previous pin). Where this amendment and
anything above differ, this amendment governs. It was made before any calibration and before any holdout scoring: no fit
has run, no freeze record or calibration artefact exists, and no value of any holdout series was read for it. The trace cap
stays pinned at 1e10; the label **`LITERATURE BENCHMARK / CALIBRATION ONLY`**, C6 as an expected FAIL at 2.0 GHz, and chirp
unfitted stay. The evidence is the closing review (`handoff/N3a_qa3.md`, findings 1 to 9) and its repros on synthetic data.

### H-A. The calibration flag is checked, not trusted (corrects the wording of G-C and G-D; finding 1)

`curve_arrays(outcomes, calibration=True)` took a typed flag as the proof that a result was one of "the B2B points of the fit
before a freeze". It is now a check on both halves:

- Scoring (the default) loads the freeze record that verifies now and requires every result to carry exactly that record's
  hash. No record, a deleted record, a stale record (the plan or the code changed after the run), a hash typed by hand, or a
  hash of another record is refused. "Verified" means verified now, not at run time.
- `calibration=True` is refused while any freeze record is present. Every result must be back-to-back (the default link), run
  without a record, and at a declared calibration point: `DECLARED_CALIBRATION_POINTS`, the (rate, ROP, point index) triples of
  the Fig.4 B2B grid, kept in `nanf_chain.py` (so part of the code identity) and empty until the calibration step declares
  them. An outcome that names another ROP than its result is refused. Results carry their rate, ROP, point index and link for
  this purpose.
- Corrected wording. G-C said that deleting the record does not make a vector scorable, and G-D that deleting it makes a vector
  unscorable; both held only without the flag. They now hold for both paths: with the record deleted, scoring is refused, and
  the calibration path accepts only back-to-back runs at declared calibration points. Stated limit: before a freeze a vector is
  free, so someone who deletes the record can rebuild declared B2B calibration points with any vector and call them
  calibration. Those are Fig.4 B2B points, which no holdout comparison reads (C5's B2B wavelengths are Fig.6, not on that
  grid), and no NANF or SSMF result passes this path. Order and tampering by the owner of the repository stay unprovable
  (G-D).

### H-B. Grafts are read from the common git directory (finding 2)

Git reads `info/grafts` (and the shallow file and replace refs) from the common directory. In a linked worktree the
per-worktree directory is `.git/worktrees/<name>` and holds none of them, so `nanf_freeze` looked in the wrong place. It now asks
`git rev-parse --path-format=absolute --git-common-dir`, and a test builds a linked worktree with a graft in the main
repository's common directory. The only other thing read from the git directory by the code is nothing: replace refs are
switched off by `--no-replace-objects`, and the shallow file is not read (a shallow clone that lacks the named commit is refused
by the commit check, one that has it is not harmed). The statement of G-D, "a repository with `.git/info/grafts` is refused", now
holds in a linked worktree.

### H-C. Rank deficiency at B4.5 (finding 3)

B4.5 expects a singular information matrix, and `eigh` returns round-off-size negative eigenvalues for a truly deficient
J^T J (measured: -2e-15 for two identical columns, -3e-13 for a rank-1 Jacobian), which the artefact check then refused.
The rule: eigenvalues of J^T J that lie within 1e-10 of the largest eigenvalue below zero (`EIGENVALUE_ROUNDOFF_RELATIVE`) are
floored at zero; a more negative value cannot come from rounding and is refused (`ValueError`). Numerical justification: the
finite-difference Jacobian (step 1e-3 in the scaled parameter) carries a relative error of about eps / step = 2.2e-16 / 1e-3 =
2.2e-13 per entry, so J^T J carries about 4.4e-13 of its largest eigenvalue, and `eigh` adds a few eps; 1e-10 is more than 200
times that and five orders below the B4.3 threshold 1e-3, so it cannot turn an identifiable direction into a deficient one. The
artefact check is unchanged: a hand-written negative value is still refused, and the output of the check (floored, ascending) is
what is recorded. Tests on both sides: a rank-1 and a two-identical-column Jacobian are legal and flag five and one
parameters; a value at half the tolerance is floored and one at twice the tolerance is refused.

### H-D. The B2B gate needs the ROP axis (finding 4)

`b2b_gate` takes `rop` as a required keyword. With it optional an unscored point (above -5 dBm) could earn a pass (review
repro: eight scored points at 1.4 dB, five unscored at 0 dB, FAIL with the axis and PASS without). The gate drops points
above -5 dBm (A4) and applies the validity mask to the rest.

### H-E. Anything that makes a run non-pinned is refused first (finding 5; also the class of finding 6 of the second review)

`run_point` refuses, before any run, with `NotScorableError`, every argument that makes the run something other than the
pinned chain: a chain configuration other than the default, an equaliser other than the declared one taken as a whole (the cap,
the forgetting factor, the taps, the delta, the training length, the decision-directed switch, any field), noise off, a
diagnostic run, and any argument it does not know. Previously only the cap was checked, and an illegal run whose cap acted was
returned as a lost-lock outcome and read as a physical event. A lost-lock outcome now means exactly a pinned run that lost lock.
A test parametrises the whole class with the cap forced to act.

### H-F. Sweep for typed arguments that stand in for a check (new in this amendment)

Searched `nanf_chain`, `nanf_scoring`, `nanf_freeze`, `nanf_import` and `dfe` for booleans and typed values that a caller can
set to obtain a trust the code does not verify. Found and fixed: `calibration` (H-A). Found and not changed, with the reason:

1. `published=True` of `c1_crossing`, `is_censored`, `score_c4` and `b2b_copy` turns a NaN into a flagged censored cell. Nothing
   verifies that the array is a published series; a simulated curve passed with it would hide an invalid value. The score
   functions take bare arrays by design (G-C), so this is the same residual as a hand-built array. Remedy for part b: build
   published curves only from `NanfSeries` and pass the importer's flags; not done here because it changes every scoring call.
2. The `valid` masks and the `passed` fields of `RateScores` are values a caller supplies; `curve_arrays` produces masks and the
   score objects produce `passed`, but a caller can type them. Same residual.
3. `Evaluation`, `EvaluationLog` and `EvaluationLostLockError` take the lost points from the caller's objective; the artefact
   `checks` are written by the calibration step and can be typed (review observation 6, G-D). They record, they do not prove.
4. Restrictive flags (`diagnostic`, `noise`, `decision_directed`, `p_trace_cap`) can only make a result unscorable; they are
   checked by value (`nonpinned_reasons`, `unscorable_reasons`) and not by claim.
5. `include_holdout` is guarded (truthy values included) and `frozen_hash` is compared with the record now (H-A).

### H-G. Observations

1. The error text of a refused outcome keeps the reasons (`PointOutcome`), so removing `require_scorable` from `run_point` loses
   nothing but the same text.
2. The handoff cites only commits that are ancestors of the branch tip.
3. Review observations 6 and 9 are left as stated: the artefact checks are a record (G-D); `configs/fibers/*.yml` and nested
   directories are outside the identity, harmless while `DECLARED_LINKS` matches by value, and bound as soon as a link is loaded
   from them.

### H-Z. Unchanged

The label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and holdout split, "no per-fibre retuning", the
6-parameter cap, every tolerance and threshold of section 4, A3 and B1 to B3, the trace cap pin of G1 at 1e10, the rules of
Amendments 7 and 8 except as corrected above, C6 pre-registered as an expected FAIL at 2.0 GHz, chirp unfitted, and the rule
that no criterion is dropped, relaxed or added after a number is seen except by a dated amendment with a new pin.

## Amendment 10 (2026-11-13, Gate N3 part a, fourth review: residual (a) stated)

Previous SHA-256 of this file, pinned until now (Amendment 9, commit 784ad2c):
`2ad3c7af660d836cb4d31238a6658b2dff9623d858ef415a9999e776422301f5`. The new pin is in
`tests/test_nanf_benchmark.py`. The text above this heading is unchanged (append-only; this amendment adds lines and
removes none, and a test checks that the text before this heading hashes to the previous pin). Where this amendment and
anything above differ, this amendment governs. It was made before any calibration and before any holdout scoring: no fit
has run, no freeze record or calibration artefact exists, and no value of any holdout series was read for it. It changes no
tolerance, threshold, label, split or criterion, and no source behaviour. The evidence is the fourth review
(`handoff/N3a_qa4.md`, new finding 3 and residual (a)) and its repros on synthetic data.

### H-F, item 6 (added to the list of stated residuals of H-F)

6. The fields of a `PointResult` can be forged inside the process, for example with `dataclasses.replace`. Two consequences,
   both reproduced on synthetic data: a pre-freeze retuned NANF result stamped with the public freeze record hash is accepted
   by `curve_arrays` for scoring, and a NANF result relabelled as back-to-back (its `link` field replaced) passes the
   calibration check of `curve_arrays(calibration=True)` at a declared calibration point. The code does not detect either. This
   is a limit, not a repair. The score functions take bare arrays by design (G-C), so a forged `PointResult` opens no route
   that a hand-built array does not already open. The guard for the holdout is `require_freeze` at the read of the holdout
   series, not the fields of a result. Someone who edits a result inside the process can also monkeypatch the freeze
   functions or the declared sets; the checks of `curve_arrays` bind an honest caller who types a wrong flag, not an owner who
   tampers.

### H-Z. Unchanged

Everything in H-Z of Amendment 9 stands: the label (**`LITERATURE BENCHMARK / CALIBRATION ONLY`**), the calibration and
holdout split, "no per-fibre retuning", the 6-parameter cap, every tolerance and threshold of section 4, the trace cap pin of
G1 at 1e10, C6 as an expected FAIL at 2.0 GHz, chirp unfitted, and the rule that no criterion is dropped, relaxed or added
after a number is seen except by a dated amendment with a new pin.
