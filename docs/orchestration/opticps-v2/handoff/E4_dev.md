# E4 Dev handoff (Sonnet), work tree at 3b4e531

## Files touched (all new; no existing file edited, no E2-bound file, no E3 numerics)
- `src/opticps/benchmarks/e4_matrix.py`, `e4_figures.py`; `scripts/build_evidence_matrix.py`, `scripts/make_benchmark_figures.py`
- `docs/benchmarks/EVIDENCE_MATRIX.yaml` (23 rows), `BENCHMARK_REPORT.md`, `REPRODUCE.md`, `figures/*.png` (4, 26 to 62 kB)
- `tests/test_benchmark_e4.py` (36 tests)
- Read for facts: SOURCE_REGISTER, MISSING_PARAMETERS, E2_CLOSING_RECORD, E3_WIEGART_RAN, teriphic_e2 (`two_km_result.json`, `preregistered_predictions.yaml`, NOTICE), teriphic_e2c/law_model_v2.yaml, teriphic_prbs, CHECKPOINT tail, e3_*/published_points/comparison modules. Not read: Dev/Loki E*_qa handoffs (CHECKPOINT carried the verdicts), the brief beyond E4 text.

## Decisions
- Matrix format YAML under `docs/benchmarks/`: nested path lists and nulls, rewritten by a script, round-trips floats exactly. CSV would flatten the path list.
- Wiegart and Ran rows are built from `wiegart_rows()` / `ran_rows()` (status, values, deviation, tolerance straight from `ComparisonResult`); a test rebuilds them (20 s) and compares. TERIPHIC rows are read from committed records only; nothing under `data/external/` is opened, no fit or score re-run, no 10 km path anywhere.
- Statuses: the comparison layer's four, plus record words `FAILED`, `UNSPENT`, `FIT_INVALID`, `INFERRED_REFERENCE`, `REFERENCE_SEQUENCE_MISSING`, plus `CALIBRATION` (my word, for training-partition numbers: no pass or fail claim). Orchestrator may rename it.
- Evidence label of a row = label of our value; `source_label` of the published number. `SIMULATED` for our analytic values, `EXTERNAL RAW CAPTURE` for numbers derived from a capture, `UNKNOWN` where there is no value. No row is `DIGITIZED`; validator forbids it.
- Legend label form `<LABEL>` or `<LABEL> | detail`, exactly one legal word; `Panel` refuses anything else at draw time.
- TERIPHIC figure committed: the register records CC-BY-4.0 (verified, record level) and "public redistribution of derived data allowed with attribution"; the figure uses only the committed 2 km scoring record (derived statistics, no samples), carries the attribution line, and the script opens no capture.
- Existing CLI help left unchanged (docstring help is accurate for all six scripts and `opticps benchmark inspect-format`); no new entry point needed beyond the two new scripts.

## Results
- Matrix 23 rows: T-B2B-M1..M4 CALIBRATION, T-E2C-A2 FIT_INVALID, T-2KM FAILED (best psi 1.5013, 0 of 123), T-10KM UNSPENT (all values null), T-BER REFERENCE_SEQUENCE_MISSING, T-PRBS-B2B INFERRED_REFERENCE (0.013839); W1 W2 W3 W5 MATCH (dev +0.0028, -0.0003, -0.0032 dB), W4a W4b W6..W9 NOT COMPARABLE; R1 R2 R4 NOT COMPARABLE (R1, R2 MODEL GAP: CHIRP), R3 BLOCKED.
- Times on the loaded machine: `build_evidence_matrix.py --write` 25 s, figures 26 s, `tests/test_benchmark_e4.py` 53 s.
- pytest: e4 36 passed (45 s), e3 131 passed (34 s), provenance 368 passed (117 s), e2_freeze 5 passed (6 s). `ruff check src tests scripts` clean, `ruff format --check` clean on touched files, `mypy` 73 files no issues.

## Not done
- No fibre-sensitivity figure, no measured-vs-predicted overlay, no B2B/2 km/10 km capture-metric figure (would read captures again; 10 km forbidden).
- No per-row code version or output hash in the matrix (the commit identifies the code).
- `build_evidence_matrix.py --check` is not in a test (it recomputes the 20 s E3 rows a second time); the in-process equality test covers the same comparison.
- No full suite run; no TERIPHIC command from REPRODUCE section 2 was run.

## Open risks
- The 2 km figure and matrix rows rely on the register's wording for derived-data redistribution; owner may prefer to drop the PNG.
- `CALIBRATION` status is a new word. The B2B misfit rows are the pre-registered misfit values; their exact window is the one named in the pre-registration, not restated here.
- `CHECKPOINT.md` shows as modified in the work tree before and during this task; not touched or staged by Dev.
