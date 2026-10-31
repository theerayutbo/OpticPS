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
