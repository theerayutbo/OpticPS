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
