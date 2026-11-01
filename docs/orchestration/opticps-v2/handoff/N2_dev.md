# N2 Dev handoff (first part): N2a minors, importer, Fig.1 and Fig.5 benchmarks
Base 638dc3a. N2a commits e8048ed, 4c81691 (separate, first). N2 proper is the commit after. No push, merge, tag.
Foreign changes in tree (not mine, untouched): CHECKPOINT.md modified, 5 untracked roadmap/brief files at repo root.

## N2a (N1 minors 1-6, 9, 10)
- Boolean flag replaces the "declared over table" text match; scenario S never overrides a table (also off a declared scalar D).
- Scenario D with any S in force needs `SensitivityScenario.dispersion_wavelength_nm`, else OutOfValidityRangeError (Altuna route).
- Measurement wavelength outside its own validity range refused at construction; `transmit_profile` keeps the base label; extreme loss gives the stated ValueError.
- 14 survivors killed (tests/test_nanf_n2a.py). `python scripts/mutate_nanf.py`: 45 mutants over the 5 NANF test files, 45 killed.
- Citation floor: documented as a form floor (admits "asdfgh", "abc123", "Table 2"); not chased.

## N2
- `measurement/nanf_import.py`: stdlib zip+XML, SHA-256 first (NOT_COMPARABLE), default-deny schema (FORMAT_UNKNOWN), no values in errors, -Inf formula cells -> -inf+flag, BER 0 / <1e-5 -> NaN+flag, holdout withheld unless include_holdout=True, holdout repr hides values. No new dependency.
- `measurement/nanf_benchmark.py` + `reports/NANF_Benchmark_Report.md` (label, CC BY attribution, evidence tags).
- Fig.1 (plan: cross-check, allowed): nulls 27.970/29.386/80.158 GHz vs pre-registered 27.97/29.39/80.2: within 0.3 GHz (A1.3, PASS). Bandwidth, fading, latency match workbook to input rounding; no other tolerance predeclared, no other pass claimed.
- Fig.5 (plan: calibration input, allowed): loss 6.45-8.33 dB, min at 1610 nm; distributed loss left UNKNOWN (not separable from ~2 dB, ~0.1 dB); no extrapolation; no double count.

## Disclosures
- Slip: I printed per-series censored/non-finite counts of all 69 series incl. holdout once (counts only). Nothing depends on it; plan unchanged (pin intact).
- Importer test caught Fig.6 B2B wrongly tagged calibration (plan: holdout); fixed before commit.
- Tags follow owner instruction (BER/SNR/ROP published-experimental); Sources doc would call results `measured`. [CORRECTED in the fix round: BER, SNR, capacity, Fig.5 loss are `measured`; ROP columns stay `published-experimental`.]
- Observation: 6 of 19 SSMF ROPs in Fig.5 are 0.01-0.02 dB above the -5 dBm cap; paper prose "NANF >60 GHz" disagrees with its workbook (min 49.8 GHz). [WITHDRAWN in the fix round: the paper sentence concerns the ~60 nm window and agrees with the workbook there.]

## N3 dependencies (details: report section 5)
DFE-RLS (T/2, 17/7, 0.998; split/training unknown) does not exist; Tx chain (SRRC 0.1 at 70 sps, decimate 40/50/56), oversampled link, 80 GSa/s scope + T/2 match filter; electrical SNR-ceiling noise; B6 SNR/BER/C1 rule; 6-parameter fit, identifiability, freeze hash; D(lambda) from Fig.1 table; chirp field only for the sweep.

## Checks
pytest 1513 passed; anchor green; ruff check, format --check, mypy clean; license_audit 34 pkgs, 0 flagged.

## Fix round (Gate N2 review, 2026-11-01)
Items per the orchestrator's decisions; no fit, no holdout value printed or compared, no push, merge or tag.
- 1: false ">60 GHz disagrees" withdrawn (report, this file, LOG, annotated not erased); workbook agrees in the ~60 nm window.
- 2: distributed-loss bound stated per wavelength: 1.355 dB/km at 1610 nm, 1.75 at 1460 nm (code text, new function, tests).
- 3: report says counts were printed once, values were not; carried into plan Amendment 4, D0.
- 4: importer tags `measured` (BER, SNR, capacity, Fig.5 loss), ROP columns `published-experimental`; docs and tests aligned.
- 5: plan Amendment 4 (pin changed): A3/C5 resolved (D1), assumptions with labels (D2), B2B-copy, d, C3 (D3), grid multiple of 20 (D4), `above_rop_cap` flag on B2B points above -5 dBm (D5, implemented), holdout tied to freeze hash at N3 (D6, requirement only). Report N3 list completed.
- 6: corrupt deflate, bad CRC, lying size now raise `NanfImportError` (no raw zlib or BadZipFile).
- 7: 9 survivors killed by new tests and added to `scripts/mutate_nanf.py`; null tolerance test runs on the synthetic route.
- 8: `inlineStr` outside the layout refused; the "not a number" error is raised outside the handler, so no cause or context holds the cell text.
- 10: report states the SSMF 28 GHz exclusion (0.40 dB).
- Not touched: ROADMAP_STATUS.md (carries uncommitted foreign edits; its 1513 is superseded by the full run below). [Annotation 2026-11-01, Gate N3 step 1: no full run follows in this file; the clean-pin count is 1535 passed, 6 skipped (N2_qa2.md), now recorded in ROADMAP_STATUS.]
