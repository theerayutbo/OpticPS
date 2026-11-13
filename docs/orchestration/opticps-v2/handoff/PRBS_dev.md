# PRBS search, Dev handoff (2026-11-13)
Branch v1.3-mpam. No push, no CHECKPOINT.md edit, no R13-bound, STUDY_PLAN or E2c file edited. 10 km file never read, hashed, opened or linked (see deviation 1).

## Commits
- b5cdbcf Fable's E2 next-paths advice committed by name.
- 7be7172 Part A: `teriphic_e2/E2_CLOSING_RECORD.md` (E2 closed PARTIAL; questions recorded as sent, no answer claimed).
- e06ea5f Part B pre-registration `teriphic_e2/prbs_search_prereg.md` (P1 to P7), before any search code read data.
- ce51f36 Pre-registration amendment A1 (still no capture read; thresholds untouched, see below).
- 13bbf49 `src/opticps/benchmarks/prbs_search.py`, `scripts/prbs_search_b2b.py`, `scripts/mutate_prbs.py`, `tests/test_benchmark_prbs_search.py`.
- 1a936b0 the one run: `b2b_sequence_candidate.yaml` and `prbs_search_result.md`.

## Result (one run, 22 s)
INFERRED_REFERENCE (B2B only). Periodic pattern, period 8128 symbols (autocorrelation 0.980); no LFSR (best syndrome about 0.49 of 96 candidates; BM found none), so the periodic candidate entered (P4).
Mismatch 0.013839 vs independent estimate 0.016205 (limit 0.03241); 99.2 % of mismatches in lowest-20 % margin; lag-P violation 0.0211; all others >= 0.491.
BER and SER remain REFERENCE_SEQUENCE_MISSING; `require_reference_for_ber` untouched. The pattern is not stored.

## Amendment A1 (found on synthetic PRBS15 fixtures, before any capture read)
The first draft made P6 (c) unsatisfiable for a clean true PRBS. (1) Lane syndrome is the max of the two lanes, not the mean (a wrong map sharing one lane scored 0.25). (2) Reciprocal generators removed (not in Fable's list; PRBS7-reciprocal/swapped scored 0.25 on true PRBS7). (3) "Every other candidate" excludes equivalent descriptions of the same sequence (a serial PRBS satisfies its own lane test, a squared polynomial, a BM multiple): recurrence satisfied exactly (< 0.01) by the winner's regenerated sequence. Thresholds untouched.

## Known properties of Fable's thresholds (not changed)
P6 (b) (90 % in lowest 20 % margin) fails the true pattern at about 4 % Gaussian-noise errors (test `noise_near_threshold`); P6 (a) is fragile at very low error rates. On the real data (a) and (b) passed.

## Deviations
1. An early `ls -la` and `find` of `data/external/teriphic` listed directory metadata of all three files, the 10 km one included (name, size, mtime). Nothing was opened, hashed or read. atime unchanged by listing.
2. The `INFERRED_CANDIDATE` name of the advice became `INFERRED_REFERENCE (B2B only)` as instructed; output file name `b2b_sequence_candidate.yaml` as in P7.
3. A1 above. Lane delay (0 to 64) is reported only for lane winners; none applied.
4. The 3 percent symbol-error fixture of P7 is not a passing fixture under (b); the positive fixture uses 0.3 percent errors, the 3.9 percent one asserts rejection.

## Gates
Fresh clone of the gated tip, B2B symlinked only: see the report (appended below).
