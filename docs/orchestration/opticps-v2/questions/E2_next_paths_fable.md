# E2 next paths (Fable, 2026-11-13): legitimate ways to continue after E2c v1 S2 and A2 FIT_INVALID. Read-only; nothing edited.
Basis: `teriphic_e2c/{STUDY_PLAN.md (A1, A2), law_model{,_v2}.yaml, step0_diagnostics.yaml, a2_endpoint_decomposition.md}`, `E2c_{power_study,advice}_fable.md`,
`handoff/E2c_qa.md`, `teriphic_e2/{two_km_result.json, b2b_model.yaml}`, `FIT_HOLDOUT_PLAN.md` (rule 5, R.2, R2.4), `holdout.py`, `SOURCE_REGISTER.md`, Zenodo API JSON of 7886498 re-read today (metadata only). 10 km atime 2026-10-31 16:30:05, unchanged.

## 0. What the rules already say (this decides most of what follows)
R1. D15 (c) bars a third hypothesis only "if H2 fails" on 10 km. H2 was never tested there: v1 stopped at S2 (an optimiser stall, E2c_qa finding 1),
    A2 ended FIT_INVALID at AC4. D19 says the file "stays unread for a future, differently designed hypothesis". So 10 km is unspent and available
    once, to something that is not H2 and not a re-tuned H2. A2 says "no third optimiser"; AC4's 1e-3 cannot be re-tolerated after the decomposition
    was seen (the owner's note says so itself). Any change to the objective, parameters, priors or data is a new calibration, H3, not an A3.
R2. The parent plan already contemplates a recovered sequence. R.2: sequence extraction on B2B is allowed for characterisation; the result is
    `Provenance.INFERRED`, never a BER reference (`require_reference_for_ber` refuses it). R2.4: a 2 km or 10 km prediction driven by a recovered
    sequence is `EXPLORATORY`; allowed drivers are a source-stated sequence, a frozen-seed synthetic sequence, or level probabilities. R.2 and
    `allowed_verdicts` (Revision 13): if the B2B sequence is found in a holdout, that holdout ends `EXPLORATORY` or `BLOCKED` only.
R3. Rule 5 reserves PD2 and PD3 (B2B, 2 km, 10 km) "to be opened only after the 10 km result is recorded, never for tuning"; NRZ files and
    Subassembly 2 are outside the plan. Opening any of them now is a plan revision made after seeing results.

## 1. Path 1: recover the transmitted pattern from B2B only (characterisation; INFERRED; no BER; no 10 km)
What: decide symbols on B2B, test the known pattern families (PRBS 7, 9, 11, 13, 15, 20, 23, 31 bits taken two per symbol; IEEE 802.3 Clause 120
PRBS13Q, PRBS31Q, SSPRQ; a two-lane PRBS with a lane delay) under Gray, natural and swapped-MSB mappings; run Berlekamp-Massey as the open search;
also test for plain periodicity (an AWG pattern of arbitrary content, period P, found by autocorrelation of the raw waveform, no decisions needed).
Legitimacy: R.2 allows exactly this on B2B. It is also prerequisite work: R2.4 requires a shared-sequence check "by a method committed in the
evaluation script" before any 10 km VALIDATED, so the recovery code must exist before any future 10 km evaluation anyway. Respects D15 (e) (BER stays
REFERENCE_SEQUENCE_MISSING; the proxy gets its own name, e.g. `symbol_mismatch_vs_inferred_sequence`, as R.5 asks), D15 (f), A2 (no refit of H2).
Data: B2B only; identify on the fit window (about 204 800 symbols), verify on the rest (about 800 000), declared before the run; 2 km not opened.
Information gain if found: a labelled B2B. Conditional means E[y | symbol], E[y | symbol triple] and a short-memory Volterra fit replace k-means
centroids: the law becomes a direct measurement at A 1 and, if later applied to 2 km, at A 0.832. The A2 two-basin trade (B2B M1 against 2 km M1
through the noise split) is a property of the unlabelled objective and does not exist in a labelled least-squares fit. Also answers whether the R13
M1 FAIL is a true per-level compression or a k-means artefact of transition samples. Gain if not found: the finding "pattern not a standard PRBS, not
periodic within 1e6 symbols" closes the question in the evidence matrix (E4) and the R2.4 check method is still built.
Does it revive 10 km under D15? Decision: the recovered sequence is new INFORMATION (a measurement enabler) that D15 did not contemplate, not a
hypothesis; D15 (e) and (f) are untouched by it. A model that uses it is H3 (D19's "differently designed hypothesis"), with its own pre-registration
and power study on B2B and 2 km, and it may spend 10 km once. But under R2.4 the 10 km prediction must be driven by a frozen-seed synthetic sequence
or level probabilities, never by the recovered one, and if the same PRBS is found at 10 km (near certain for a lab PRBS source) the file ends
EXPLORATORY by R.2 as written. So Path 1 revives characterisation and a well-posed calibration; it does not by itself revive a confirmatory 10 km
test. Relaxing R.2 for a SOURCE-STATED standard pattern (argued: a public PRBS is not "learned" from B2B) is conceivable only as an explicit plan
revision before any H3 freeze, after Path 2 confirms the pattern, with the asymmetry disclosed (written after H2's calibration proved ill-posed).
Cost: about 250 lines plus tests, compute minutes; 150 to 250k tokens, half a day to a day. Stop: section 7's verification passes or fails; one commit.

## 2. Path 2: dataset metadata (read-only) and questions to the publisher
Zenodo 7886498 today: description unchanged, `related_identifiers` null, no pattern, wavelength, power, scope range or timestamps. Worth reading,
metadata and abstracts only: Crossref for the creators (Groumas, Andrianopoulos, Tsokos, ICCS; Runge, HHI) with "TERIPHIC" and "photodiode array",
2022 to 2024 (such papers usually state PRBS order, wavelength, launch power and the scope model, rarely the vertical range); CORDIS GA 825502 for
the data-management deliverable. Record hits in SOURCE_REGISTER with `read_how`. Cost 30 to 60k tokens, 1 to 2 h. Gain: medium for pattern and
wavelength, low for per-capture scope settings. Stop: two search rounds.
Questions to send (one message, the data owners' contact on the record): 1 transmitted pattern (PRBS order or file; bits-to-symbol mapping; one
pattern for all lengths?); 2 laser wavelength and launch power per length; 3 modulator bias point and drive swing, DAC or BPG model; 4 photodiode
bias and whether a TIA or amplifier precedes the scope; 5 oscilloscope model, bandwidth, sample rate and whether the shipped 2.048 THz axis is an
export interpolation (filter?); 6 vertical range, offset and attenuation PER CAPTURE, and whether autoscale was used between lengths; 7 were B2B,
2 km and 10 km one session, in what order, and were PD2/PD3 captured in the same sessions; 8 fibre type and the 10 km spool's dispersion or loss.
Answers to 1 and 6 change the ceiling (D15 (d)); none can be assumed before they arrive, and none may be back-filled into A2.

## 3. Path 3: settings-invariant metrics. No.
The R13 metrics are already scale and offset invariant (centring, gap normalisation, normalised PSD); the 2 km code step 1.17e-6 is 1e-4 of a cluster
width, so quantisation does not touch M1 to M4. The confound is physical (a re-ranged front end may have a different compression and ENOB); no ratio
of gaps or normalised spectrum removes it. The code step is only a witness (a pre-registered covariate, E2c_advice section 2 b), as would be a stated
range from Path 2 question 6. A new invariant test would be H3 with its own pre-registration and power study on B2B and 2 km, buying nothing.

## 4. Path 4: identifiability fix for the law (regularise, reparameterise, add data). H3, not A3.
Any of: labelled least squares (needs Path 1); pinning q from B2B conditional means; a prior on the noise split; refitting on a different objective.
Each changes what is estimated, so it is H3 under D19 (one 10 km shot, after its own power study), never an A3 of H2 (A2: no third optimiser; AC4
stays). Without new information (Path 1 or 2) an H3 refit on the same B2B and 2 km is tuning towards a verdict. Adding data: PD2/PD3 are reserved
by rule 5 until after a 10 km result and NRZ files are outside the plan, so both are post-hoc plan revisions. Not advised now.

## 5. Path 5: close E2 at PARTIAL and redirect
Record, in one commit: H1 refuted at 2 km (R13); H2 calibration stopped before the power computation: v1 S2 was an optimiser stall, A2 reached
0.14058 with AC1 to AC3 holding and failed AC4 (one basin; start 10 is 0.0010 above, trading B2B M1 for 2 km M1); Step 0 code grid is evidence of a
per-session vertical setting (S1 under D6 (ii)'s own step definition, I10 under-read it); claim PARTIAL; 10 km unspent. Stale test already fixed
(2e87b9e). Then E3 (Wiegart analytic curves; Ran subcases only, MODEL GAP: CHIRP), E4 (evidence matrix, BENCHMARK_REPORT, REPRODUCE) and NANF N3b.
Cost 60 to 100k tokens, 1 to 2 h. This closes the H2 study, not the dataset: D19 keeps 10 km for a future hypothesis.

## 6. Ranked recommendation
1. Path 5 now (cheap, true, unblocks E3/E4) with Path 2's questions sent the same day (15 minutes; answers arrive asynchronously).
2. Path 1 as the continuation: it is the only step that produces new information from data we may touch, it is prerequisite R2.4 work, and it
   cannot inflate any claim (INFERRED, no BER, no 10 km, no refit of H2).
3. H3 only if 1 or 2 delivers a labelled B2B or source-stated metadata; then a labelled calibration with its own plan and power study, 10 km once,
   ceiling PARTIAL (or EXPLORATORY if the sequence is shared and R.2 stands). Otherwise 10 km stays unspent; that is a result, not a failure.
Very next step: commit the Path 5 record, send the Path 2 questions, then commit a one-page pre-registration of Path 1 (section 7) before any run.

## 7. Path 1 implementation outline (B2B only; deterministic; no 10 km; the 2 km file not opened)
P1 Read B2B through `e2c_calibration`'s route (hash-checked; the 10 km and 2 km names refused). Windows fixed: identify on samples 0 to 8388607,
   verify on 8388608 to the end. No seeds: every step is deterministic (no random restarts, no random windows).
P2 Period scan without decisions: FFT autocorrelation of the mean-removed waveform (2^26 points) over lags 100 to 500 000 symbols (symbol period
   2048 / 50.00019 samples). A peak above 0.5 of the zero-lag value at lag P is a periodic pattern; report P or "none".
P3 Timing: one symbol phase and rate for the whole file from the squared-signal line, fitted on the identification window and held; centre samples
   by linear interpolation. Decisions: nearest R13 centroid; margin = distance to the nearest threshold in gap units. Report the Gaussian-cluster
   decision-error estimate from the centre-sample sigma before any candidate is scored (the independent estimate used in P6).
P4 Candidate test (needs no error-free window): for each generator g and mapping m (Gray, natural, swapped MSB; one LFSR two bits per symbol, or two
   lanes with lane delay 0 to 64), map decided symbols to bits and count violations of g's recurrence: truth gives about (weight of g) x bit error
   rate, a wrong candidate 0.5. Every candidate is scored and the whole table reported.
P5 Open search: Berlekamp-Massey on several disjoint high-margin stretches of 2 x 64 bits; a linear complexity L identical across at least 3
   stretches and at most 31 is a candidate for P4. If P2 found a period P with no LFSR, estimate the sequence by per-position majority vote.
P6 Verified iff, on the verification window and for exactly ONE candidate (generator or P-periodic sequence, with its mapping and state): (a) the
   regenerated sequence matches the decided symbols with a mismatch rate at most 2 x the P3 estimate and at most 0.1; (b) mismatches sit at low
   margin: at least 90 % of mismatched symbols lie in the lowest 20 % of the margin distribution; (c) the syndrome violation rate on the
   verification window is below 0.1 while every other candidate's is above 0.4 (uniqueness). Two candidates passing (a) to (c) is NOT_UNIQUE.
P7 Output `teriphic_e2/b2b_sequence_candidate.yaml`: status `INFERRED_CANDIDATE` (with generator, mapping, state, period, mismatch rate, margin
   statistics, the full P4 table, windows, code hashes) or `REFERENCE_SEQUENCE_NOT_RECOVERED` (the P2 scan and P4 table, nothing else). In both
   cases `reference_sequence: REFERENCE_SEQUENCE_MISSING` for BER stays, `require_reference_for_ber` is not changed, no 2 km or 10 km file is read,
   and no E2c file is edited. Tests on fixtures: a synthetic PRBS15 Gray PAM4 stream with 3 % symbol errors is recovered uniquely; a random symbol
   stream returns NOT_RECOVERED; the 10 km and 2 km names are refused before any open. One run, one commit; the thresholds above are not revisited.
