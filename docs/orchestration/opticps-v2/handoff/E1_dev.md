# E1 Dev handoff (Stage 3A, external capture format and receiver QA; Dev, Opus 5.5 session)
base: f4bfeaa. Commits: 57643ca (E1a, separate), then E1 and this handoff. Tip SHA in the final report. Local only.
Gate: full pytest 1600 passed (59 new in test_benchmark_external_capture.py), anchor 15 passed; ruff check, ruff format --check, mypy clean; license_audit 34 packages, 0 flagged; no dependency change.

## E1a (57643ca)
- Plan Revision 5 addendum, pin 7b7f93dd...3185 (previous b638aa1a...). R.1 claim true (8f57af9 holds the full hash), Revision 2 partly (0424e9c holds 45d9088c), Revision 3 false.
- Tests assert dd2f8000 and the Revision 4/5 headings; known limits a, b, c; ROADMAP 1479 at d52149a; read_bin refuses unexplained trailing bytes (test).
- verify_local_asset on all three: MD5 verified (= record), SHA-256 = orchestrator values. Register and a skip-if-absent test updated. Two register needles in the old test changed wording only.

## E1
- external_capture.py (read-only memmap, hash first, header parse, 84 hypotheses), timing.py (exact sps, tone-tracked fractional clock), capture_stats.py (streaming stats, estimated_* names, BER/SER/post-FEC refuse), teriphic.py (B2B only), CLI `opticps benchmark inspect-format` (--allow-download refused, holdout refused, --metadata-only opens nothing).
- tests/test_benchmark_external_capture.py (fixtures built here with own packing and own signal generator).

## Verdict (B2B only): SUPPORTED_BY_EVIDENCE, not documented by the exporter
- Keysight BIN v10, float32 LE, data at byte 164, 40,959,993 samples, scale normalized. 136-byte prefix hypothesis rejected by structure only (statistics cannot tell, 7 samples).
- File time increment 1/2.048 THz (40.96 samples per symbol; symbol tone 50.00019 GHz, +3.8 ppm). Record's 256 "Gbaud" stays INFERRED (5.12 nominal); it is 8x off the stored axis.

## Facts the reviewer should check
- Holdout discipline: test_real_b2b_format_verdict_and_evidence spies on Path.open and np.memmap, only the B2B .bin is touched; 2 km and 10 km were hashed only. Check that no code path reads a holdout header (guard_sample_read, MD5 check in open_b2b).
- Plan R5.2 said "roll off within 128 GHz Nyquist for the claimed 256 GSa/s": the check was run on the header axis; reported as a deviation (MISSING_PARAMETERS section 4).
- The wrong-dtype rejection is by evidence except float32 offset 136 vs 164, and int32/uint32 (rejected by the continuity check I added, not by luck). Is the continuity threshold (1.5 std) defensible?
- Decision-error proxy is circular and labelled; no key in any output contains ber/ser (tested).
- Timing tracker range: 0.16 % clock offset (256-symbol windows); beyond that it refuses.

## Not done, on purpose
- No BER, SER, repeating-sequence search, cross-file alignment; no fit; no config change (raw_format and calibration stay UNKNOWN in the configs); no download; --allow-download not implemented.
- read_bin was run once on B2B as a cross-check: identical samples (not a test, it loads 0.7 GB).

## Exporter must tell us
Vertical calibration and export gain/coupling; native sample rate and any 8x interpolation filter; scope model, bandwidth, ENOB, digital filters; transmitted sequence; wavelength, power, bias, swing.

## Next (not started)
E2 only after review PASS and the plan's freeze steps; the accepted layout is applied to 2 km and 10 km unchanged and only then.
