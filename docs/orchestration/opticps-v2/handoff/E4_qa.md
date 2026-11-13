verified_sha: 0e2564e
# E4 review (Loki). Round 1 at ce0501c: FAIL (2 MAJOR, 2 MINOR, 4 OBSERVATION). Round 2 at 65b53bd: FAIL (1 MAJOR, 1 MINOR, 3 OBSERVATION). Round 3 at 0e2564e: PASS (0 MAJOR, 1 MINOR, 1 OBSERVATION)

Reviewed `git diff 3b4e531..ce0501c` in a clean clone (13 files, all `A`, no existing file edited, no E2-bound or E3 file touched). `opticps.__file__` resolved inside the clone. Nothing fixed or committed; clone restored, `git status --short` empty.

## Results
- `tests/test_benchmark_e4.py` 36 passed; `test_benchmark_e3.py` 131 passed; `test_benchmark_e2_freeze.py` 5 passed; `test_benchmark_provenance.py` **1 failed, 366 passed, 1 skipped**. `ruff check src tests scripts` clean; `mypy` no issues in 73 files.
- Every sampled number traces: T-2KM psi 1.5013018 and M1 0.0272266/0.0181353 (`teriphic_e2/two_km_result.json` l.56-57, 1203-1211; outcome FAIL, verdict FAILED, claim null, survivors [], 123 scored); B2B M1..M4 (`preregistered_predictions.yaml` l.11-12); T-E2C-A2 0.140582, FIT_INVALID, AC4 (`teriphic_e2c/law_model_v2.yaml` l.58, 71, 83-84); T-PRBS 0.013839, 8128, INFERRED_REFERENCE (`teriphic_prbs/b2b_sequence_candidate.yaml` l.25, 31, 74); E2 PARTIAL, H1 refuted, 10 km unspent for H3, BER/SER missing (`E2_CLOSING_RECORD.md` l.1-27); W1-W5 values and R4 nulls (`E3_WIEGART_RAN.md` l.38, 51-56, 91-92, and fresh `wiegart_rows()`/`ran_rows()` output). T-10KM all values null.
- 10 km: hashed at E1a on 2026-11-01, before the R13 freeze (`SOURCE_REGISTER.md` l.48-73: "hashed and nothing else"). "10 km hashed only, no sample read" is accurate. No E4 path names it; figure script under an `open` audit hook opened in the repo only `configs/benchmarks/ran_2025_g652d.yaml` and `teriphic_e2/two_km_result.json` (plus sources, fonts); 0 opens under `data/external` or of any `.bin`.
- Figures regenerated into scratch: all four byte-equal to the committed PNGs. Viewed each: no DIGITIZED series; Wiegart shows our curves plus the three running-text points only; Ran shows only the analytical curves; TERIPHIC carries the CC BY 4.0 attribution. Register l.40 and l.152 do record CC-BY-4.0 (verified) with public redistribution of derived data allowed with attribution.
- Over-claims: none found. E2 is PARTIAL throughout; W1-W3 framed as agreement with an analytic AWGN result; no Southampton or hardware claim; 10 km never described as read or scored; Ran not reproduced; PRBS row says inference and proxy, not a BER. 6-word overlap of report, REPRODUCE, matrix and E4 modules with the local Wiegart manuscript: 0. No Ran XLSX present anywhere outside the forbidden directory; no absolute path, user name, token or serial in the diff; no TODO, skip, xfail or stub.
- REPRODUCE section 1: `--check` (exit 0, "matches the code (23 rows)", 32 s), `--write` (git diff empty), `--table` (contained verbatim in the report), figures (4 PNGs, 27 to 62 kB), both print snippets, and all seven `--help` commands (exit 0) behave as stated.

## Findings
1. MAJOR (regression, licence guard). `test_no_removed_article_sentence_remains_in_committed_text` fails at the tip: `BENCHMARK_REPORT.md` l.75 "(1271 nm, -3.99 ps/(nm km), ..." hits removed Ran-article window `54f5c9cb676f` ("1271 nm 3 99 ps nm km"). The content is a cited fact, but the committed guard is red, and the handoff's "provenance 368 passed" cannot have been run on this report. Reword the line (e.g. the order used in `E3_WIEGART_RAN.md`). Repro: `pytest -o addopts= tests/test_benchmark_provenance.py -k removed_article_sentence`.
2. MAJOR (evidence label). `teriphic_two_km_ratios.png` labels both series `SIMULATED`, and the report figure table (l.134) repeats it. The "B2B copy" series is the B2B capture's evaluation window scored against the 2 km capture (`FIT_HOLDOUT_PLAN.md` l.937): no simulation at all. The matrix labels the same psi `EXTERNAL RAW CAPTURE` (T-2KM). The figure contradicts the matrix and mislabels capture-derived statistics. Repro: `grep -n "SIMULATED |" src/opticps/benchmarks/e4_figures.py`, compare with `EVIDENCE_MATRIX.yaml` row T-2KM.
3. MINOR (test gap). `test_figure_set_matches_the_committed_images` compares file names only. My mutant M8 (relabel a TERIPHIC series in `e4_figures.py`) survived the whole E4 file (36 passed), so committed PNGs can drift from the code. Repro: change one label string, run `tests/test_benchmark_e4.py`.
4. MINOR (scope). Roadmap E4 item 1 asks each matrix row for code version, output hash and uncertainty. Code version and hash are disclosed as not done; uncertainty is not mentioned anywhere. The report says a fibre-model sensitivity figure needs the captures read again, but `two_km_result.json` holds the metrics and psi for all 123 D/N scenarios, so one could be drawn from the committed record. Needs an owner decision or a corrected justification.
5. OBSERVATION. `CALIBRATION` is the Dev's own word (disclosed) and `UNSPENT` is the records' lowercase "unspent" turned into a status; the report's "other statuses are the words of the underlying record" is loose for `UNSPENT`. Neither softens a failure: the B2B rows are pre-registered basis values, not scored outcomes. `INFERRED_REFERENCE`, `REFERENCE_SEQUENCE_MISSING`, `FIT_INVALID` and `FAILED` are the records' exact words.
6. OBSERVATION. T-10KM conditions read "no audit hook opened the file", which makes no sense as written. The record (`E2b_2km_qa.md`) says an audit hook saw 0 opens of the 10 km file. Reword.
7. OBSERVATION. REPRODUCE section 2 lists `inspect-format --metadata-only` among the commands that need `data/external/` and says they were not run without it. It runs without the directory (exit 0, "metadata only: the file was not opened").
8. OBSERVATION (stated gaps). `--check` not being in a test is acceptable: the in-process equality test does the same comparison (mutant M1 killed). The B2B rows not restating their window is acceptable because the pre-registration states it. The B2B/2/10 km metric figure is correctly omitted (10 km forbidden). Only the items in finding 4 are roadmap requirements.

## Mutants (E4 test file, clone restored after each)
Applied 8, killed 7: W1 value (equality test), T-2KM status (record test), missing evidence path, illegal label VALIDATED, removed legend label (Panel refuses at draw time), W4a turned to MATCH in report table, column dropped from header. Survived 1: M8 (finding 3).

## Not checked
Full suite (orchestrator runs it). TERIPHIC commands of REPRODUCE section 2 (need captures; not run). Whether the JLT numbering equals the manuscript's. Ran article text: not opened (no copy used); only checked that no Ran XLSX exists.

## Round 2 at 65b53bd
Scope `git diff ce0501c..65b53bd` (5 commits, 13 E4 files). Clean clone, `opticps.__file__` inside it, restored after every mutant, `git status --short` empty. No frozen or earlier-gate file and no test other than `test_benchmark_e4.py` touched (`git diff --name-only 3b4e531..65b53bd` over the frozen list: empty). Records unchanged; every round 1 sample still traces to the same lines.
Runs: e4 51 passed; e3 131 passed; e2_freeze 5 passed; provenance 367 passed, 1 skipped; `test_pam4_anchor.py` 15 passed; `build_evidence_matrix.py --check` exit 0 (23 rows); ruff clean; mypy no issues (73 files); `inspect-format --metadata-only` exit 0.
Resolved:
- R1 finding 1: the guard is green, `tests/test_benchmark_provenance.py` is unchanged, and the Ran line lists cited facts only, in the wording of `E3_WIEGART_RAN.md` l.79.
- R1 finding 2 for T-2KM and both 2 km figure series (copy series = plan l.937, record `b2b_copy`).
- R1 finding 3: M8 killed.
- R1 finding 4, provenance fields: code_version equals `head_commit` of the 2 km record (l.53), `law_model_v2.yaml` (l.11) and the PRBS candidate (l.19), or `__version__` 1.2.0. Recomputed by hand, 5 of 5 output_hash values match the documented form. B2B uncertainty = the record's `b2b_window_spread`, stated as "not a confidence interval". Every null gives a reason.
- R1 finding 4, fibre-sensitivity figure: 123 listed = 123 scored, 0 with psi <= 1, lowest 1.5013, copy 1.6434. The title says PARTIAL/FAILED and "not a fit", and the figure carries the CC BY 4.0 line. Under an `open` audit hook the figure script opened only `two_km_result.json`, `scenario_list.yaml` and the Ran config in the repo; nothing under `data/external` and no `.bin`.
- Observations 5 to 7: T-10KM now cites `E2b_2km_qa.md`; the CALIBRATION/UNSPENT sentence is accurate; REPRODUCE lists `--metadata-only` as needing no data, and it does.
- Figures: all five regenerated byte-identical to the committed PNGs, with equal spec hashes. Viewed all five: legend labels follow the rule, no DIGITIZED series. The combined label names two of the five legend words and separates simulated from measured, so it does not blur them.
Findings:
R2-1. MAJOR (label rule applied inconsistently; R1 finding 2 relocated).
- T-B2B-M1..M4 are the metric between the surrogate's no-fibre prediction and the real B2B evaluation window (`FIT_HOLDOUT_PLAN.md` l.915-916).
- T-E2C-A2 is the law model's fit objective against the B2B and 2 km fit windows (`law_model_v2.yaml` l.1-4).
- Both compare a simulated model with a capture, so under the report's own rule they are `SIMULATED vs EXTERNAL RAW CAPTURE`. They carry `EXTERNAL RAW CAPTURE`, the report says they "are statistics of captures only" (false), and `test_evidence_label_rule` (l.150-151) pins the wrong labels. T-PRBS-B2B (inferred pattern vs the same capture) can stay.
- Repro: `grep -n "statistics of captures only" docs/benchmarks/BENCHMARK_REPORT.md`; plan l.915.
R2-2. MINOR (spec hash does not cover what a reader sees). The hash covers the title, series labels and numbers, but not the footer or annotation text. Each of these mutants survived all 51 tests: N5 (CC BY 4.0 replaced), N6 ("no scenario reaches psi <= 1" turned into "scenarios reach"), N9 ("not a fit" dropped). Repro: edit any of them in `e4_figures.py` and run `tests/test_benchmark_e4.py`.
R2-3. OBSERVATION. `code_version` "opticps 1.2.0" on 14 W/R rows, 7 of which compute nothing, names no commit. This is disclosed and acceptable.
R2-4. OBSERVATION (Dev's rounding risk). `--check` compares the full YAML text with full-precision floats, so float drift on another platform fails it whatever the hash rounding; pytest uses rel 1e-9. The 6- and 5-digit hash rounding adds no risk. Acceptable for CI on one pinned platform.
R2-5. OBSERVATION. The stated reasons for the two figures not made hold: no aligned prediction passed; 10 km is unspent.
Round 2 mutants: 10 applied, 7 killed (M8 relabel, plotted number, matrix label only, PNG from mutated code, PNG text chunk stripped, invented code_version, B2B label plus recomputed hash), 3 survived (R2-2). The spec test cannot pass vacuously: a missing chunk fails (N4).
Not checked in round 2: full suite; the Ran article text (guard only); CI configuration.

## Round 3 at 0e2564e
Scope `git diff 65b53bd..0e2564e` (3 commits). Clean clone, `opticps.__file__` inside it, restored after every mutant, `git status --short` empty. Since 3b4e531 only E4 files changed; records unchanged; round 1 samples unchanged (T-2KM 1.5013, T-E2C-A2 0.140582, PRBS 0.013839, B2B M1, W1-W3).
Runs: e4 56 passed; e3 131 passed; e2_freeze 5 passed; provenance 367 passed, 1 skipped (guard file diff empty since ce0501c); `test_pam4_anchor.py` 15 passed; `--check` exit 0 (23 rows); ruff clean; mypy no issues (73 files).
R2-1 resolved. All 23 declarations checked against the records:
- B2B M1-M4: model vs capture (plan l.915). E2c: model vs capture (`law_model_v2.yaml` l.1-4). T-2KM and the scenario series: model vs capture. All three get the combined label.
- B2B copy series: capture vs capture (plan l.937). PRBS: capture only; the reason is true, because the pattern comes from the B2B identification window, is scored on the verification window, and its normalisation is `RAW_CAPTURE` (`b2b_model.yaml` l.433).
- W1-W5 and R4: model. W4a and W4b report our computed optima, so `SIMULATED` alongside NOT COMPARABLE is honest.
- The 9 rows without a number are `UNKNOWN`.
- The report's rule section, status table and figure table agree with the matrix; the final table carries no labels.
- All 23 output_hash values recomputed by hand: all match.
R2-2 resolved: the hash now covers every drawn text. N5, N6 and N9 are killed (N5 first hit the docstring; re-anchored on the attribution string, killed). The hash is stable across two runs. All five PNGs regenerate byte-identical, with equal spec hashes, and are pixel-identical to the round 2 images I viewed. Under the `open` audit hook: no `data/external` and no `.bin` opened.
R2-3 resolved (7 rows that compute nothing now carry null with a true reason). R2-4 resolved (handoff line superseded and corrected).
Findings:
R3-1. MINOR (guard gap, no current effect).
- A second axes added in `_finish` with an unlabelled line (mutant P5) passes all 56 tests.
- The label check and the hash look only at panel axes, and numeric tick labels are skipped by design.
- No committed figure has such an axes.
- Repro: add `fig.add_axes((0.7,0.7,0.2,0.2)).plot([0,1],[0,1])` in `_finish` and run `tests/test_benchmark_e4.py`.
R3-2. OBSERVATION. `source_label` "PUBLISHED DATA" is set directly in `_module_row`, not through `label_from_kinds`, so "one function makes every label" is loose. The value is correct.
Round 3 mutants: 13 applied, 12 killed, 1 survived (P5).
- Killed: YAML label only; self-consistent wrong PRBS declaration with recomputed hash; kinds changed in code without regenerating; N5; N6; N9; axis label; tick label; legend title; text added after the hash; raw plot bypassing `Panel`; self-consistent wrong series kinds.
- Survived: P5 (R3-1).
Not checked in round 3: full suite; CI configuration; the Ran article text.
