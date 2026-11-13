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
