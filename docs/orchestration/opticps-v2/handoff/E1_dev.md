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

## Fix round (after handoff/E1_qa.md: 3 MAJOR, minors 4 to 10)
Local only, a new commit (E1 was 12eb480). Tip SHA and counts in the final report. Plan Revision 6 (previous pin 7b7f93dd, new pin in test and config).
- 1: `teriphic.gate_sample_read` is the one gate (resolved name, `data/external`, MD5 and SHA-256 of the whole file vs recorded holdout hashes, file hashed once and the checksum reused); the CLI uses it for every `--file`, with or without `--metadata`; tests inject a fixture hash, a SHA-only hit and a symlink to a holdout name, and forbid any reader call.
- 2: non-B2B route reports `structure pass` and `physical pass` apart, full-file finite and scale scan plus slice checks (new `plausible_scale`); white noise, noise x 1e30, NaN block, smooth x 1e30 all refused; "accepted" is gone.
- 3a: plan R6.1 lists each R5.2 departure (128 GHz check on the header axis, 40.96 vs 5.12, `continuous`, survivor-only level and tone checks, M4 rate = 2.048 THz header axis); I reproduced on B2B that they are outcome-neutral. The repository cannot show whether `continuous` preceded the first B2B read. R6.2 states the holdout route rule; also in FREEZE_GUARD_KNOWN_LIMITS.
- 3b: one test per guard of `verify_b2b_format` (status, four levels, tone ppm, tone strength, survivor mismatch, none or several survivors); mutation run on a scratch copy: 19 of 19 mutants killed (the five named, `bounded`, four `stale` variants, gate, display range, scans, band guards).
- 4: `rate_chain_reading` and `size_hypothesis_136_bytes` computed from the file; `_band_db` refuses an empty or silent band (the 256 GSa/s fixture now returns FORMAT_UNKNOWN without NaN or warning). EXPORTER_QUESTIONS no longer carries a fixed 2.048 THz.
- 5: `read_bin`, `open_keysight_bin`, `open_raw` stay generic and are listed as known limits. 6: `bounded` and `stale` have direct tests (spike, time-only and size-only change, never-hashed checksum).
- 7: x origin reported (-11.755 us); a display range inconsistent with points x increment is now fatal (B2B still passes, 1.7e-7). 8: `capture_stats.native_rate_reading` reproduces on B2B N-1 = 8 x 5,119,999, 5,120,000 native points = 20 us at 256 GSa/s, lines at 256.000 and 512.000 GHz (29 and 27 dB over the median bin), second-difference period 8 (max/min 1.118, controls 1.0002), labelled READING.
- 9: frame string recorded as `frame_model_claim` (UXR0704AP, header claim, not instrument evidence); serial removed from MISSING_PARAMETERS, code output and tests, with a scan test. It stays in the history of 12eb480 (new commits only). 10: `window_samples` docstring and timing module text corrected (10485.76 becomes 10486).
- Python: the checks run on `.venv` (3.11); system 3.14 fails `test_md5_verified_cannot_be_typed` (replace raises TypeError there), unrelated.

## Revision round (after handoff/E1_qa2.md: 4 MAJOR, minors 5 to 9)
Local only, new commits on b7eaab5. Tip SHA, plan pin and counts in the final report. Plan Revision 7 (previous pin c1c274b9...).
- 1: `ROUTES` in cli/main.py lists every path option by reading each handler's call graph; `main` gates files and folder contents with `gate_sample_read` before the handler (ingest-uxr was the hole). Test walks the parser; holdout fixtures by name, SHA-256 and MD5, readers forbidden. Claim: every CLI route gated, library code not.
- 2: non-B2B inspection streams the whole record in 65,536-sample blocks, same checks per block, spike test against a robust record scale; blocks checked, failed and computed coverage printed; no bare "physical pass"; says no four-level claim. Thresholds from B2B only, margins in R7.5.
- 3: R7 records the absent 64-bit integers (reproduced on B2B), `matches_declared_structure` as an acceptance-rule change (not outcome-neutral), offsets 164 to 167, `bounded`, `smooth`, `non_degenerate`, `plausible_scale`, block checks, with what was seen after B2B.
- 4: seven survivors killed by behaviour tests; `scripts/mutate_e1.py` (git-initialised copy) covers them and the new guards; totals in the final report.
- 5: `--metadata` gated and no byte values echoed; swap listed as deliberate only; `_in_external` and names case- and Unicode-normal; list or dict dtype is FORMAT_UNKNOWN; `rate_chain_reading` needs a curvature-period criterion (lines do not separate cases); `ExternalCapture` no longer says "verified".
- Not done: library readers stay ungated (known limit); 64-bit integers recorded, not added to the 84 hypotheses.
