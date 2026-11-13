# B2B pattern search: result note (2026-11-13)

One run of `scripts/prbs_search_b2b.py` on the B2B capture only, under `prbs_search_prereg.md` (with
amendment A1, committed before any capture was read). Output: `b2b_sequence_candidate.yaml`. Run at
commit 13bbf49. The 2 km and 10 km files were not used, opened, hashed or linked. No threshold was changed.

**Status: `INFERRED_REFERENCE (B2B only)`, provenance INFERRED.** BER and SER stay
`REFERENCE_SEQUENCE_MISSING`; `require_reference_for_ber` is unchanged and still refuses an inferred sequence.

- The B2B pattern is **periodic, not a standard PRBS.** P2: autocorrelation 0.980 at lag 332922 samples,
  period P = 8128 symbols (16256 bits).
- No LFSR candidate passed. The best of 8 generators x 6 maps x 2 modes had an identification-window
  syndrome of about 0.49, and Berlekamp-Massey found no recurrence of complexity 31 or less. By P4 the
  periodic candidate entered, with the pattern a per-position majority vote on the identification window.
- P6, verification window (795202 symbols): mismatch of the repeated pattern against the decided
  symbols 0.013839 (limit: 2 x the independent estimate 0.016205 = 0.03241, and 0.1); 99.2 % of the
  mismatches (10919 of 11005) in the lowest 20 % of margins (limit 90 %); the period-P violation rate
  is 0.0211 (limit 0.1), and every one of the 96 LFSR candidates is 0.491 or higher (limit 0.4).
- Timing held over the verification window: 0.0107 symbol RMS line-phase residual (reported only).
- Mapping and level order are not identified. A periodic vote needs neither, so the note makes no claim about them.

What this does and does not say. It says the decided B2B symbols repeat with period 8128 to within the
decision-error rate, so the transmitted sequence is a repeating pattern of that length (for example an
AWG memory) and is not any of the tested PRBS. It does not give the bits, a bit mapping or a source
statement, and the pattern is not stored in the repository. The proxy is
`symbol_mismatch_vs_inferred_sequence` (about 1.4 %), not a BER.

Consequence under plan R.2 and R2.4, stated without having looked: if the same pattern is carried by the
2 km or 10 km files, which is likely for one source but unchecked, that holdout ends EXPLORATORY or
BLOCKED. A source-stated pattern would need the publisher's answer (question 1).
