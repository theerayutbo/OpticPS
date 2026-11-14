# N3 scout (read-only). Plan = docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md (PLAN), tip 7945762
No data/external access, no run, no holdout value seen. Later amendment governs; source named per claim.
Code: src/opticps/measurement/nanf_{chain,scoring,freeze,import,benchmark}.py (cited as chain, scoring, ...).

## 1. Steps in order
1. Declare `DECLARED_CALIBRATION_POINTS` (rate, ROP, index) for Fig.4 B2B, scored ROP <= -5 dBm (H-A; A4). Empty today (chain 489).
2. Fit the 6 B4 parameters on B2B only (sec 2 table; A4; B4.1). Lost-lock vectors get +inf, never chosen (H4; `evaluate`, `select_best`).
3. `check_chosen_fit`: no lost point in the calibration grid (H4; scoring 977).
4. B4 identifiability check, once, calibration data only (A1.7, B4.2-5, H-C): flagged params set to prior, no refit; undefined if lost point (H4).
5. B2B fit-quality gate per rate, at the hashed vector (B3.2, H-D; `b2b_gate`, rop required). A failing rate = `B2B CALIBRATION POOR`.
6. Optional diagnostics, change nothing: leave-one-rate-out (rule 5; no code), chirp sweep -1..+1 step 0.25 (A1.5).
7. Write calibration artefact JSON under docs/benchmarks/ (`calibration_artifact`), commit it (G4).
8. `build_freeze_record(artifact_path)` -> docs/benchmarks/NANF_FREEZE_RECORD.json; commit before any holdout read (F8, G4; process rule, not code-checked).
9. Fill `DECLARED_LINKS` and `DECLARED_POINT_INDICES` ("part b", G-C). They are in the code identity, so do it BEFORE step 8, else the record is stale.
10. Holdout read: `read_nanf_workbook(path, include_holdout=True, freeze_hash=...)` (D6, F8, G6). 46 holdout series (G-B). Fig.11 never returned.
11. Simulate holdout points with `run_point`, `curve_arrays`; score C1-C5 (+C6-C8 if built); verdict via `overall_verdict` (sec 4 decision rule, A2, B3.3).
12. Report: lost points listed (H1), B2B-copy comparator (A2, D3.1), C6 expected FAIL (A1.4), exact words "The holdout is not fully blind" (G-A; test_nanf_benchmark.py:310), label LITERATURE BENCHMARK / CALIBRATION ONLY (sec 1).
## 2. Fit definition
- Free (B4.1, chain `B4_PARAMETERS`): tx_bandwidth_ghz 10-60 (prior 35); rx_bandwidth_ghz 10-60 (35); thermal_noise_pa_per_rthz 5-60 (32.5); modulation_depth 0.2-1.0 (0.6); bias_fraction 0.4-0.6 (0.5); electrical_snr_ceiling_db 15-35 (25). 6 params; ranges never widened; range-edge result is reported.
- Fixed: chirp 0 (A1.1-2); responsivity 0.8, DAC 8 bit, RIN 0, extinction 30 dB, 280/70/80 GSa/s, SRRC 0.1, N=655200, 8192 training, DFE (17,7) RLS 0.998, delta 1e-2, trace cap 1e10 (D2, F1, F4, F6, G1). Fibre D, L, loss from paper/standard, not fitted (rule 3). All labelled `user-assumed`.
- Calibration partition (21 series, G4/G-B): Fig.4 B2B BER and SNR at 80/100/112 (6), Fig.1 (12, cross-check), Fig.5 (3, ROP and loss inputs). Fit sees Fig.4 B2B only (sec 2; A4). Points above -5 dBm and censored BER (0 or <1e-5) are excluded from the BER term (A4).
- Objective: residual vector = SNR dB residuals plus log10 BER / 0.5, on A4 points (B4.2). Reduction (sum of squares) is not stated; `fit_result.cost` must be > 0 (G-D).
- Optimiser, starting point, optimiser seeds, budget, stop rule: PLAN SILENT. Only: `converged` true, >= 7 evaluations, 9-33 calibration points, cost > 0 (G-D). Noise seeds are fixed: PCG64 SeedSequence([20261101, 7919, Rs_GBd, point_index]), common random numbers across links (F4.2).
## 3. Freeze
- Record fields (G4): plan_sha256, code_identity, parameters (6 names), unidentifiable, calibration {path, sha256, commit}, calibration_partition_sha256, freeze_hash (SHA-256 of canonical JSON of the other six).
- Artefact fields: parameters, unidentifiable, fit_result {method, converged, n_evaluations, n_calibration_points, cost}, calibration_partition_sha256, checks {chosen_fit_checked true, n_lost_points_in_grid 0, six ascending eigenvalues} (G4, G-D).
- Lives: docs/benchmarks/NANF_FREEZE_RECORD.json (freeze 44; absent now). Writer: `build_freeze_record` returns the dict, writes nothing (freeze 466) and `calibration_artifact` (freeze 256) builds artefact bytes. Checker: `require_freeze` (freeze 606), `load_freeze_record`; `read_nanf_workbook` calls it before opening the file.
- Must be committed first: the artefact (git-tracked, equal to HEAD, commit an ancestor of HEAD, G4) and the record (process rule, F8). Any edit to reachable src, pyproject.toml, uv.lock, configs/fibers/*.yaml or the plan after freezing relocks the holdout (G5, G-E.6).

## 4. Holdout
- Series (sec 2, G-B): Fig.4 NANF and SSMF; Fig.6 all incl. B2B; Figs 7-10 and 12. Fig.11 excluded. Excluded from scoring: Fig.4 ROP > -5 dBm; C5 1630, 1640 nm (B2).
- Metrics: C1 crossing at BER 3.8e-3 (+/-1.0 dB), C2 SNR MAE 1.5 / max 3.0 dB, C3 penalty vs 5/11/14 dB +/-3.0 and SSMF BER > 3.8e-3, C5 17 wavelengths (NANF 2.0, SSMF 3.0, B2B 2.0 dB), secondary C4 (0.5 log10, 80%), C6 (2.0 GHz, expected FAIL), C7 (10 Gb/s, ratio 0.10), C8 (2.0/3.0 dB). Primary = C1, C2, C3, C5 at all 3 rates (sec 4).
- Verdicts exist as three strings only (`overall_verdict`): "failed: ...", "primary criteria pass; NANF criteria NOT DISCRIMINATING (rates ...)", "consistent with this one experiment" (A2, B3.3). The plan has no PASS/PARTIAL/FAILED words. No H-label hypotheses exist: PLAN "H-A..H-G" and "H1..H6" are amendment headings, not hypotheses.
- Wording limits: never "validation"; "consistent with one published experiment" only; "The holdout is not fully blind" in every report (G-A); no retune after a number is seen (sec 4); A2 "PASS, NOT DISCRIMINATING"; SSMF gaps are mismatch, attribution to chirp only as hypothesis (A1.5).

## 5. Exists vs missing
| Piece | Where |
|---|---|
| Chain, `TxRxParameters`, `B4_PARAMETERS` | chain: simulate_point 562, run_point 774, curve_arrays 816 |
| Lost-lock handling, evaluation log | scoring: evaluate 950, select_best 968, check_chosen_fit 977 |
| Identifiability check | scoring: identifiability_check 1005 |
| B2B gate, B2B copy, d | scoring: b2b_gate 785, b2b_copy 706, d_c1/d_snr |
| C1-C8 scoring, verdict | scoring: score_c1..c8, overall_verdict 855 |
| Freeze record build/verify, artefact | freeze: build_freeze_record, calibration_artifact, require_freeze |
| Holdout read gate | import: read_nanf_workbook 674 |
| Calibration objective (residuals from B2B series) | MISSING (only the callback slots in `evaluate`, `identifiability_check`) |
| Optimiser driver, start point, seeds, stop rule | MISSING (and plan silent) |
| Calibration/fit driver script, freeze script, holdout run script | MISSING (scripts/ has only mutate_nanf.py) |
| DECLARED_CALIBRATION_POINTS, DECLARED_LINKS, DECLARED_POINT_INDICES | MISSING content (empty, chain 484-489) |
| Calibration artefact and NANF_FREEZE_RECORD.json | MISSING (none in docs/benchmarks) |
| Link construction for NANF/SSMF from profiles | MISSING driver (LinkSpec exists, chain 277) |
| OFDM transmitter and chain (Figs 7-12, C6-C8 simulation) | MISSING (F9); only scoring arithmetic exists |
| Report writer with the not-fully-blind string | MISSING (test only, reports/NANF_Benchmark_Report.md is N2) |

## 6. Cost (G9, G-E; per call numbers measured on dev machine)
- One point 14-16 s one core; about 40 s when six run at once (about 2.2x speed-up). Lost-lock real run about 20 s (N3a_close_dev), 40 s under load (N3a_close_qa).
- One calibration evaluation = 33 B2B points (G9) about 9 min; but A4 leaves 8 scored ROPs per rate, so 24 points about 6 min (my arithmetic, G9 predates A4 count). Optimiser budget unknown, so fit cost is open.
- B4 check: 12 evaluations about 1.8 h one core (G9).
- Holdout: G9 total 336 points = Fig.4 99 + Fig.6 153 + 84 no-fibre; about 90 min one core, about 40 min with six processes. Includes 33 B2B Fig.4 points that are calibration, so the true new holdout is smaller. OFDM not counted.

## 7. Ambiguities and risks
1. Optimiser, seeds, budget, stop rule, objective reduction not stated (see sec 2). An implementer picks them after seeing only calibration data, which is legal, but record the choice before step 2.
2. Point indices for holdout: `DECLARED_POINT_INDICES` need the index on the published axis (F4.2), so ROP axes of NANF/SSMF/Fig.6 must be read. G-A says axes were already seen and are "experiment design"; reading them through the importer's holdout path before freeze is forbidden (rule 2). Use only Fig.4 B2B/SMF shared axis and Fig.5 wavelength grid, or get an owner ruling.
3. G9 says 33 calibration points per evaluation, A4 and H-D drop ROP > -5 dBm (B2B at -4, -3, -2). Count differs; G-D allows 9-33, so both pass the check.
4. Code identity covers all reachable src, so any driver edit that touches `nanf_chain.py` (declaring links, points) after the artefact commit but before the record relocks nothing yet, but after the record it locks the holdout (G5). Order: declare, fit, artefact, record.
5. Pre-freeze the vector is free and the record is committed by a process rule only (G4, G-D, H-A stated limit, H-F.6): the guard stops accidents, not tampering. `calibration=True` accepts bare B2B only at declared points (H-A).
6. Holdout is already partly seen (G-A: axes, one Fig.11 y cell) and parsed in memory by three tests (G-E.5); default reads of the real workbook parse holdout in process. Do not add tests that read the real file.
7. Lost-lock: points in the noise-limited region fail criteria that need them (H3) and can make C5, C2 fail through H2/H3 without being retuned (H5). Real pinned lock-loss tested only for the trace-cap route (N3a_close_qa obs 3).
8. Open reviewer items: N3a_close_qa MINOR 1 (H-Z of A10 does not restate "A3, B1-B3" and "Amendments 7 and 8"; restate at next amendment); obs 2 (empty record file untested, correct at tip). Residual H-F.6 stands. Plan edit after the record relocks the holdout (F8, G5); a plan change needs an amendment plus a pin move.
