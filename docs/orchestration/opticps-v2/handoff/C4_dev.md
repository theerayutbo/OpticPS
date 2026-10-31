# C4 Dev handoff (generic adaptive, constraints, acquisition guard)

Base 5a851dd, branch v1.3-mpam. Two local commits: C4a (rates.py minors), C4. Nothing pushed/merged/tagged. Roadmap files, CHECKPOINT.md, output/, results/, configs/m8199b_profiles.yaml untouched.

## Files
- C4a: src/opticps/optimization/rates.py (spread over P>0, order-aware warning), tests/test_mpam_rates.py (+4).
- C4: src/opticps/optimization/adaptive.py, constraints.py (new); tests/test_mpam_adaptive.py (32), test_constraints.py (24), test_leakage.py (14); docs/notes/mpam_adaptive_constraints.md; ALGORITHM_PROVENANCE, ROADMAP_STATUS (C3 deviation 5), engineering LOG.

## Decisions to check
- Bounds q_j in [1/(4n), 1/2] read with n = block length (not M/2); M/2 clipped the M=4 optimum at <= 12 dB.
- Legacy Selection.to_dict returns exactly the legacy keys (anchor compares key sets); new fields only for family symmetric_pairs.
- Generic path requires even block length (symmetric quantiser). Exactly equal sigma uses "auto", else common_grid.
- BMD is fitted as smooth bmd_raw, reported clipped. Exact quantised objective re-evaluated at 11 endpoints, uniform, 20 MB grid points; argmax of logged in-bounds feasible candidates. Claims limited as specified.
- Best-fixed menu is a function (fixed_menu), not yet read from config; configs/mpam_profiles.yaml arrives in C5.
- assert_independent compares ids regardless of source (as uxr_ingest). Within-set duplicates also rejected.
- Constraint flags allow_laser_adjustment, allow_drive_rescale, allow_sample_rate_adjustment default False; undeclared adjustments give INFEASIBLE with the needed value listed, never applied.

## Results
- M=8, 22 dB SMD cont q (inner first) 0.1043 0.1269 0.0678 0.2010; BMD 0.1101 0.1108 0.0853 0.1939.
- M=16, 28 dB SMD 0.0575 0.0586 0.0558 0.0617 0.0497 0.0738 0.0267 0.1163; BMD 0.0576 0.0578 0.0575 0.0568 0.0607 0.0559 0.0443 0.1094.
- 11 starts agree to 6e-13 bit and 3e-7 in q. Runtime M=16 13-23 s per call, M=8 2-3 s (i5-8259U).
- 678 passed (604 before); new files about 20 s excluding the slow M=16 run. ruff, format, mypy clean; anchor green.
- M=4 compressed outer spacing alone never made inner-heavy win; it does at M=8 (+0.025 bit).

## Fix round (after Loki FAIL at 2b9e1fe)
Results: 698 passed (anchor green), ruff check, ruff format --check, mypy clean. Numbers below are from code run at this tip; details in docs/notes/mpam_adaptive_constraints.md. Lines above that disagree (bound 1/(4n), "6e-13", "+0.025 bit") are superseded.
1. Floor: bounds [1/n, 1/2] (n >= M). 11/11 endpoints feasible in all 26 sweep runs (M=8 8-18 dB, M=16 10-22 dB, SMD and BMD); with 1/(4n) re-applied 0/11 in 9 re-run points. M=8 16 dB BMD 1.2652 vs MB-grid fallback 1.1545. Claims say "over the constrained set", floor-active pairs reported. Recorded as decision in ROADMAP_STATUS (deviation 6).
2. Uniform direct, zero loss, new family only; legacy select_distribution unchanged (anchor green), limitation disclosed (deviation 7). M=8 22 dB: SMD sel 1.96391 vs uniform 1.95468 (+0.00923), BMD +0.00539; best fixed is the uniform. M=16 28 dB: selection IS the uniform (SMD 2.78194, BMD 2.75102); best shaped -0.03137 / -0.03434. Rate equalisation PS80 +17.2 %, PS70 +7.1 % (verified). Sine M=8 g=1.55 sigma=0.8: -0.0075. Scan 8x8: no inner win for g<=pi/2; test channel is now g=1.8 sigma=0.8 (+0.075), found by scan. PAM16 negative case restated (shaped loss 0.0526-0.0622 vs gain <=2.1e-4).
3. Hash recomputed in assert_independent and select_on_acquisitions (QA repro tested); truncation limit documented; false docstring sentence replaced.
4. best_fixed takes training Acquisitions; selected_on is built from checked ones; channel input rejected; negative tests.
5. FixedOMA: first rising branch, 0.9202 V for half OMA (fold-over 7.0798 V not reported), true reason text, unreachable target quotes reachable max. Also range edge tolerance 1e-9 in EqualRealizedUserRate (256 GSa/s edge failed on float rounding).
6. SMD single-start claim says "unquantised" and the channel caveat; "starts disagree" branch tested (sabotaged start).
7. Mutants agreement tol 1e9, clipped bmd fit, ignored in_bounds each fail a test (checked by mutating).
8. M=4: scan 64 channels x 2 metrics; inner never wins g<=2.2; wins at g=2.6 sigma 2.0/3.0 (0.0122/0.0543 BMD vs direct uniform; Loki's case was 0.026 vs CCDM uniform). Tested.
10. 5e-13 -> 6.3e-13 bit, 2.7e-7 in q. ROADMAP_STATUS tracks C5 (pin menu and deficits, no run-time override) and C7 (assert_disjoint id-only; migrate compare, uxr_compare, demo).
Also corrected: docs/ALGORITHM_PROVENANCE.md, docs/engineering_log/LOG.md (entries annotated, fix-round entry added).
