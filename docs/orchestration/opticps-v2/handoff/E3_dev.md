# E3 Dev handoff (Wiegart fixed-peak PAM4, Ran subcase, comparison layer)

Base 784ad2c. Commits c8e08fd, 4c9861a, 2ba2244, plus this handoff (tip SHA in the Aria report).

## Files
- New: `src/opticps/benchmarks/{published_points,comparison,e3_wiegart,e3_ran}.py`, `tests/test_benchmark_e3.py`, `docs/benchmarks/E3_WIEGART_RAN.md`.
- Edited: `configs/benchmarks/wiegart_2021_peak_pam4.yaml` (technical fields filled with arXiv v2 locations; baud, fibre length, reference sequence stay null), `configs/benchmarks/ran_2025_g652d.yaml` (note + null fibre_length), `docs/benchmarks/{MISSING_PARAMETERS,SOURCE_REGISTER}.md` (one cell each).
- Not touched: E2 freeze files, `rates.py`, anything under `data/external/` except a name listing.

## Decisions
- Compared quantity: PSNR gain (dB) of the best symmetric PMF over uniform at equal peak and 1.0 bpcu (SMD and BMD), plus the P_X(0) optimum. Tolerances 0.01 dB and 0.05 were written into `e3_wiegart.py` before any deviation was computed; a test pins them.
- Primary route reuses OpticPS rates; a second, separately written grid/differential-entropy route and a third (OOK LLR integral) check it. Gray label table is our reading of "binary reflected Gray" (paper prints none).
- `compare` refuses (NOT COMPARABLE, reason named) on quantity, unit (no conversion), rate definition, constraint, wavelength, length, baud, BER definition, FEC threshold, DSP stage, drive, or a null on either side; N/A conditions must be declared and then be null on both sides. A figure-read value cannot construct a `PublishedPoint`.
- Ran: Source Data XLSX absent (names listed only) -> BLOCKED; verdict MODEL GAP: CHIRP with 14 missing items; ANALYTICAL chirp-free nulls from 1271 nm and -3.99 ps/(nm km) (read from the config; no function default).

## Results
- Wiegart (ours vs text): W1 SMD gain 0.8328 vs 0.83 dB, W2 BMD 0.7097 vs 0.71, W3 fixed PMF BMD 0.6268 vs 0.63, W4 P_X(0) 0.3982 (SMD) and 0.3958 (BMD) vs 0.4: all MATCH. W5 qualitative OOK-range ordering MATCH (10.70 dB SMD, 12.05 dB BMD). W6, W7 (Fig. 1, 2a, 2b) NOT COMPARABLE: figure values. W8 (LDPC FER), W9 (measured) NOT COMPARABLE. No MISMATCH.
- Methods agree to 1.4e-5 dB (SMD) and 4.4e-5 dB (BMD) on the gains.
- Ran: R1, R2 headline rates NOT COMPARABLE (MODEL GAP: CHIRP); R3 BLOCKED (XLSX); R4 first null 68.20 GHz (5 km), 48.22 GHz (10 km), -3 dB 48.22 / 34.10 GHz, NOT COMPARABLE (no published counterpart, chirped link). Time-domain simulation agrees with |cos| to 2e-3.
- Tests: new file 108 passed. Full-suite, ruff, mypy totals are in the Aria report.

## Open risks
- Reviewer should check my reading of the BMD label order and that "PX(0)" is the outer probability (paper Sec. II).
- W4 metric unstated in the paper; both reported. Paper values are rounded (tolerance is rounding-bound).
- Locations are arXiv v2 numbering, JLT numbering unchecked. The tolerance declaration is by file order in a single working session, not by an external timestamp.
- Concurrent report-only clone created `handoff/N3a_dev4.md` here; left untracked.

## Fix round (reviewer FAIL: 1 MAJOR, 4 MINOR)
1. MAJOR W4a/W4b: the published point for P_X(0) = 0.4 now has `rate_definition=None`; `compare` refuses it (`NOT COMPARABLE: rate_definition is null on the published side`). The 0.05 tolerance and its text are removed; `compare` still needs a tolerance argument, so the refused rows pass `TOL_P0_UNUSED = 0.01` (never used to accept or reject; documented). Both optima (0.3982 SMD, 0.3958 BMD) shown as information only. Tests: rows refused for that reason; no W4-style row can be MATCH with a null rate definition (five model values, both metrics). Earlier summary "W4 MATCH" in Results above is superseded.
2. MINOR location: the fixed PMF is in the Sec. II running text after Fig. 2 (checked in the manuscript; the figure tick labels repeat it, the Fig. 4b caption does not). Corrected in code and report.
3. MINOR Gray caveat: report limitations now say the paper names Gray, all two-bit Gray labellings give identical BMD rates, a natural binary label gives 2.16 dB for the Gray-optimal PMF (computed, not hard-coded) so W2/W3 would be MISMATCH. Test computes it and two other Gray labellings.
4. MINOR licence: W5 source text rewritten neutrally; the `TOL_P0_WHY` clause is gone with the tolerance. A 4-gram overlap scan of my touched files against the manuscript text finds only numbers, notation and short technical terms (the config's pre-existing field texts and the paper title are bibliographic, untouched).
5. MINOR boundary: closed window documented (`|dev| <= tol` is MATCH); tests with exact binary fractions at the edge, inside, 1.125x, 1.5x and 2x tolerance, both signs.
6. Hardening: wavelength and baud rate must be positive and finite, fibre length not negative and finite (tests for both point classes). `ComparisonResult` carries `published_evidence` and `model_evidence`; one test; report limitations say MATCH against a measurement is agreement, not validation. Disclosed that tolerances share a commit with the computed rows.

New statuses: W1 MATCH, W2 MATCH, W3 MATCH, W4a NOT COMPARABLE, W4b NOT COMPARABLE, W5 MATCH, W6 to W9 NOT COMPARABLE; R1, R2 NOT COMPARABLE, R3 BLOCKED, R4 NOT COMPARABLE (unchanged). Numbers of W1-W3, W5, Ran untouched.
Tests: `test_benchmark_e3.py` 131 collected; e3 + provenance + e2_freeze together 504 passed, 0 failed. ruff check, ruff format --check (touched files), mypy: clean. Full suite not run (orchestrator).
