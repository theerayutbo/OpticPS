# E4 Dev handoff (Sonnet), work tree at 3b4e531

## Files touched (all new; no existing file edited, no E2-bound file, no E3 numerics)
- `src/opticps/benchmarks/e4_matrix.py`, `e4_figures.py`; `scripts/build_evidence_matrix.py`, `scripts/make_benchmark_figures.py`
- `docs/benchmarks/EVIDENCE_MATRIX.yaml` (23 rows), `BENCHMARK_REPORT.md`, `REPRODUCE.md`, `figures/*.png` (4, 26 to 62 kB; now 5)
- `tests/test_benchmark_e4.py` (36 tests; now 51)
- Read for facts: SOURCE_REGISTER, MISSING_PARAMETERS, E2_CLOSING_RECORD, E3_WIEGART_RAN, teriphic_e2 (`two_km_result.json`, `preregistered_predictions.yaml`, NOTICE), teriphic_e2c/law_model_v2.yaml, teriphic_prbs, CHECKPOINT tail, e3_*/published_points/comparison modules. Not read: Dev/Loki E*_qa handoffs (CHECKPOINT carried the verdicts), the brief beyond E4 text.

## Decisions
- Matrix format YAML under `docs/benchmarks/`: nested path lists and nulls, rewritten by a script, round-trips floats exactly. CSV would flatten the path list.
- Wiegart and Ran rows are built from `wiegart_rows()` / `ran_rows()` (status, values, deviation, tolerance straight from `ComparisonResult`); a test rebuilds them (20 s) and compares. TERIPHIC rows are read from committed records only; nothing under `data/external/` is opened, no fit or score re-run, no 10 km path anywhere.
- Statuses: the comparison layer's four, plus record words `FAILED`, `UNSPENT`, `FIT_INVALID`, `INFERRED_REFERENCE`, `REFERENCE_SEQUENCE_MISSING`, plus `CALIBRATION` (my word, for training-partition numbers: no pass or fail claim). Orchestrator may rename it.
- [SUPERSEDED for T-2KM and the figure legends, see fix round] Evidence label of a row = label of our value; `source_label` of the published number. `SIMULATED` for our analytic values, `EXTERNAL RAW CAPTURE` for numbers derived from a capture, `UNKNOWN` where there is no value. No row is `DIGITIZED`; validator forbids it.
- [SUPERSEDED: the combined label `SIMULATED vs EXTERNAL RAW CAPTURE` is also legal] Legend label form `<LABEL>` or `<LABEL> | detail`, exactly one legal word; `Panel` refuses anything else at draw time.
- TERIPHIC figure committed: the register records CC-BY-4.0 (verified, record level) and "public redistribution of derived data allowed with attribution"; the figure uses only the committed 2 km scoring record (derived statistics, no samples), carries the attribution line, and the script opens no capture.
- Existing CLI help left unchanged (docstring help is accurate for all six scripts and `opticps benchmark inspect-format`); no new entry point needed beyond the two new scripts.

## Results (first attempt; superseded where marked)
- Matrix 23 rows: T-B2B-M1..M4 CALIBRATION, T-E2C-A2 FIT_INVALID, T-2KM FAILED (best psi 1.5013, 0 of 123), T-10KM UNSPENT (all values null), T-BER REFERENCE_SEQUENCE_MISSING, T-PRBS-B2B INFERRED_REFERENCE (0.013839); W1 W2 W3 W5 MATCH (dev +0.0028, -0.0003, -0.0032 dB), W4a W4b W6..W9 NOT COMPARABLE; R1 R2 R4 NOT COMPARABLE (R1, R2 MODEL GAP: CHIRP), R3 BLOCKED.
- Times on the loaded machine: `build_evidence_matrix.py --write` 25 s, figures 26 s, `tests/test_benchmark_e4.py` 53 s.
- [SUPERSEDED by the fix round below: the provenance line was not true at ce0501c, where 1 test failed] pytest: e4 36 passed (45 s), e3 131 passed (34 s), provenance 368 passed (117 s), e2_freeze 5 passed (6 s). `ruff check src tests scripts` clean, `ruff format --check` clean on touched files, `mypy` 73 files no issues.

## Not done
- [SUPERSEDED: the fibre-sensitivity figure is now built from the committed JSON] No fibre-sensitivity figure, no measured-vs-predicted overlay, no B2B/2 km/10 km capture-metric figure (would read captures again; 10 km forbidden). [The "would read captures again" reason was wrong for the sensitivity figure; it holds for the 10 km capture only.]
- [SUPERSEDED: every row now has code_version, output_hash, uncertainty] No per-row code version or output hash in the matrix (the commit identifies the code).
- `build_evidence_matrix.py --check` is not in a test (it recomputes the 20 s E3 rows a second time); the in-process equality test covers the same comparison.
- No full suite run; no TERIPHIC command from REPRODUCE section 2 was run.

## Open risks
- The 2 km figure and matrix rows rely on the register's wording for derived-data redistribution; owner may prefer to drop the PNG.
- `CALIBRATION` status is a new word. The B2B misfit rows are the pre-registered misfit values; their exact window is the one named in the pre-registration, not restated here.
- `CHECKPOINT.md` shows as modified in the work tree before and during this task; not touched or staged by Dev.

## Fix round at 3229d94 (gates run there; the next commit changes only this file)
Changes per finding (reviewer verdict `E4_qa.md`, tip ce0501c):
1. Licence guard: `BENCHMARK_REPORT.md` Ran cited-facts sentence reordered (wavelength, dispersion, lengths, FEC) as in `E3_WIEGART_RAN.md`; guard, hash list and other tests untouched.
2. Labels: one rule (captures only = `EXTERNAL RAW CAPTURE`; simulated scenario vs capture = `SIMULATED vs EXTERNAL RAW CAPTURE`, the one combined label, added to `e4_matrix.ROW_LABELS` and validated). T-2KM and the "best of 123" series carry the combined label; the B2B copy series is `EXTERNAL RAW CAPTURE` (plan `FIT_HOLDOUT_PLAN.md` line 937, record `two_km_result.json` `b2b_copy`). Report explains it.
3. Binding: `FigureSpec.specification()` (title, series labels, evidence labels, SHA-256 of numbers to 5 digits) hashed into PNG text chunk `OpticPS-figure-spec-sha256`; tests compare chunk with code, check series labels against matrix cells, and reject a changed label. Hand mutant (copy series relabelled `SIMULATED`): 3 failed, 48 passed; file restored, `git diff --stat` empty.
4. Matrix: `code_version`, `output_hash` (SHA-256 of canonical values, 6 digits, recomputed by the validator), `uncertainty` on all 23 rows. code_version: record-stated `head_commit` for T-2KM, T-E2C-A2, T-PRBS-B2B; `opticps 1.2.0` for the 14 W/R rows (`--check` proves matrix = code at the holding commit); null for T-B2B-M1..4, T-10KM, T-BER (4+2 = 6 rows, with reason). uncertainty: record `b2b_window_spread` on 4 B2B rows (spread, not a CI); null with reason on the other 19. New figure `teriphic_fibre_sensitivity.png` from `two_km_result.json` and `scenario_list.yaml`, PARTIAL/FAILED in the title, CC BY 4.0 line. Overlay and B2B/2 km/10 km metric figure stay not made (no aligned prediction passed; 10 km unspent and unread).
5. Wording: T-10KM audit-hook sentence, status-word sentence (`CALIBRATION` is the report's word, `UNSPENT` the records' lowercase "unspent"), `inspect-format --metadata-only` moved to the section that needs no `data/external/` after running it (exit 0).
Commits: 9624a45, c0383a3, 38acabd, 3229d94 (REPRODUCE count, handoff section), then one commit adding the gate lines. No file under `data/external/` was opened, listed or hashed; no frozen or earlier-gate file changed.
Gate lines: all run at 3229d94: provenance whole file `368 passed in 112.92s`; e4+e3+e2_freeze `187 passed in 77.76s` (51+131+5); `build_evidence_matrix.py --check` `matches the code (23 rows)`; figures regenerated to a scratch dir, all 5 spec hashes equal to the committed PNGs; `ruff check src tests scripts` all passed; `ruff format --check` on touched files clean; `mypy` no issues in 73 files. `git diff --stat ce0501c..HEAD` lists only the E4 files and this handoff.
Not done: full suite (orchestrator); TERIPHIC commands of REPRODUCE section 2 (need captures); no new uncertainty was estimated, so 19 rows stay null by design; matrix hash fixes 6 digits, a platform that differs beyond that would fail `--check`, not seen.
