# B2B transmitted-pattern search: pre-registration (2026-11-13)

Committed before any search code reads data. Characterisation only (plan R.2). Source of P1 to P7:
`docs/orchestration/opticps-v2/questions/E2_next_paths_fable.md`, section 7. The thresholds in P6 are
Fable's and are not revisited after the run. One run, one commit of its output.

## Scope and rules

- Data: the B2B capture only. The 2 km and 10 km files are not used, opened, hashed or linked; their
  names are refused before any open. No seeds exist: every step is deterministic.
- The recovered sequence is never stored. The output holds the generator, the mapping, the seed
  state with its position, and statistics.
- BER and SER stay `REFERENCE_SEQUENCE_MISSING` whatever the outcome. `require_reference_for_ber` is not
  changed and keeps refusing an inferred sequence. No R13-bound file, `STUDY_PLAN.md` or E2c output is edited.
- A design flaw found after the data are read stops the work and is reported. A threshold is never relaxed.

## Design (fixed here)

P1 Windows. Identification: samples 0 to 8388607. Verification: sample 8388608 to the end. Samples
   are normalised with `c0`, `g0` of `teriphic_e2/b2b_model.yaml`. Symbols are those whose centre falls in a window.

P2 Period scan, no decisions. Autocorrelation of the mean-removed waveform by FFT (zero padded to 2^26),
   biased estimator, lags 100 to 500000 symbols. Report the smallest lag L (a local maximum within one
   symbol) with r(L)/r(0) >= 0.5 as period P = round(L / spp), or "none", with the largest r found.

P3 Timing and decisions. spp0 = fs / baud = 40.96 samples. The squared, mean-removed waveform of the
   identification window is demodulated at 1/spp0 in blocks of 32768 samples; the unwrapped block
   phases (weight |c_k|) are fitted by a straight line, which gives one line frequency (spp) and phase
   for the whole file, held. Symbol instants are the line peaks plus one offset o, chosen on the
   identification window from 0 to spp in steps of 0.25 sample as the minimiser of the summed squared
   distance of the centre samples to the R13 centroids. Centre samples: linear interpolation.
   Decision: nearest R13 centroid (`b2b_centroids_normalised`: -1.51119, -0.47298, 0.49536, 1.48881);
   thresholds are their midpoints; margin = distance to the nearest threshold in gap units.
   Independent decision-error estimate: a 4-component Gaussian mixture (100 EM iterations, started at
   the decided-cluster shares, means, standard deviations) on the identification-window centre
   samples; estimate = sum over levels of share x sum over adjacent thresholds of Q(|t - mean| / sigma).
   Reported only: the RMS residual (in symbols) of the verification-window block line phases against the
   held line.

P4 Candidates and syndrome test. Generators, as lag sets of a[m] = XOR a[m-l]: PRBS7 {7,6}, PRBS9
   {9,5}, PRBS11 {11,9}, PRBS13 {13,12,2,1} (also the PRBS13Q bit source), PRBS15 {15,14}, PRBS20
   {20,3}, PRBS23 {23,18}, PRBS31 {31,28} (A1.2: no reciprocals). PRBS31Q uses the
   PRBS31 bit source and SSPRQ is covered by P2. Mappings of symbol to (hi, lo) bits: Gray 00,01,11,10;
   natural 00,01,10,11; swapped 00,10,01,11; each with normal or inverted level order (s -> 3-s): 6 maps.
   Modes: serial (hi, lo interleaved, one LFSR) and lanes (hi and lo each a separate stream of the same
   generator; the lane syndrome is the larger of the two (A1.1) and is independent of the lane delay; the delay
   0 to 64 is reported if the two regenerated lanes are exact shifts of each other). Syndrome = fraction
   of positions violating the recurrence. Every candidate is scored on both windows and the whole table
   is reported. The periodic candidate of P5 enters only if no LFSR or BM candidate has an
   identification-window syndrome below 0.1; its syndrome is the fraction of verification symbols that
   differ from the symbol P earlier.

P5 Open search. Berlekamp-Massey over GF(2) on 8 disjoint 64-symbol (128-bit) stretches of the
   identification window chosen greedily by largest minimum margin, per serial map. A connection
   polynomial of linear complexity at most 31 that is identical in at least 3 stretches is added to P4 as
   a candidate. If P2 found a period P <= 68266 with no LFSR candidate, the sequence is estimated by
   per-position majority vote (ties to the smaller symbol) over the identification window.

P6 Verification, on the verification window, for the candidate with the lowest identification-window
   syndrome. State: the n-bit seed (n = largest lag) is read from each of the 16 disjoint stretches with
   the largest minimum margin in the identification window, regenerated both ways over that window, and
   the seed with the fewest symbol mismatches there is kept (ties to the earliest); then regenerated
   over the verification window. Verified iff (a) mismatch rate of regenerated against decided symbols
   <= 2 x the P3 estimate and <= 0.1; (b) at least 90 % of the mismatched symbols lie in the lowest
   20 % of the verification-window margin distribution (no mismatches: holds, and is reported); (c) its
   verification-window syndrome < 0.1 and the syndrome of every other candidate > 0.4. Two candidates
   passing (a) to (c) is NOT_UNIQUE (a failure).

P7 Output `docs/benchmarks/teriphic_e2/b2b_sequence_candidate.yaml`. Status `INFERRED_REFERENCE (B2B only)`
   if verified, otherwise `REFERENCE_SEQUENCE_NOT_RECOVERED` (the P2 scan, the P4 table and the failing
   conditions, nothing else). Provenance of a recovered pattern is INFERRED. The proxy has its own name,
   `symbol_mismatch_vs_inferred_sequence`; it is not a BER.

## Amendment A1 (2026-11-13), committed before any search code read the B2B capture

Found while testing the code on synthetic PRBS15 streams (no capture read). Thresholds are untouched.
The first draft above made P6 (c) unsatisfiable for a clean true PRBS, for structural reasons:

- A1.1 The lane syndrome is the larger of the hi and lo lane syndromes, not their mean. With the mean, a
  wrong mapping that shares one lane with the truth scored 0.25.
- A1.2 Reciprocal generators are removed from the candidate list (Fable's list has none; with them,
  "PRBS7-reciprocal, swapped, serial" scored 0.25 on a true PRBS7 Gray stream). Berlekamp-Massey (P5)
  still finds a recurrence in any convention up to complexity 31.
- A1.3 "Every other candidate" in P6 (c) excludes candidates that describe the same symbol sequence: a
  candidate whose recurrence the winner's own regenerated sequence satisfies (syndrome < 0.01 on the
  whole record, under that candidate's mapping and mode) is an equivalent description, because a serial
  PRBS also satisfies its own lane test, a squared polynomial, and a Berlekamp-Massey multiple. They are
  listed under `equivalent_descriptions` and are not counted against uniqueness. Two inequivalent
  candidates below 0.1 is still NOT_UNIQUE.
