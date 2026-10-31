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
