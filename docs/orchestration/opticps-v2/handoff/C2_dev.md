# C2 Dev handoff (PAM-M rates)

Base de1fc73, branch v1.3-mpam. Two local commits (C1 minors, then C2). Nothing pushed, merged, tagged. Roadmap files and CHECKPOINT.md not committed.

## Commit 1 (C1 minors)
- tests/test_pam4_anchor.py: committed rehash includes the 5 metadata files; checksum names compared with no metadata filter (21 entries); regenerated metadata digests checked against regenerated files. 15 tests.
- FEATURE_GAP_MATRIX: re-export (limit disclosed, uxr_ingest.py:147-149), five paired runs PARTIAL (compare.py:52,211), candidates (90 stored), zero-error citation :299.

## Commit 2 (C2)
- src/opticps/optimization/rates.py: generic M (2,4,8,16), `order`/`nodes` args, `Rates` gains `bmd_raw`, `order`, `nodes` (defaults keep old construction valid), `average_snr`, `default_nodes`.
- PAM4 keeps the legacy kernel verbatim (fallback to log-domain only if non-finite); other orders use log-sum-exp.
- tests/test_mpam_rates.py: 86 tests. Spec items all covered; PAM4 pins taken at de1fc73, exact equality.
- Docs: ALGORITHM_PROVENANCE entry, ROADMAP_STATUS (C2 table, checklist), LOG.md entry.

## Counts
- Before: 383 passed (after commit 1). After: 469 passed in 223.75 s, anchor green. ruff check, format, mypy clean.

## Key numbers
- GH120 vs GH200 < 1e-9 FAILS: 120 nodes are 1.9e-8 (M=16), 3.7e-8 (M=8), 2.6e-8 (M=2), 4.1e-8 (M=4) from 280 nodes. 200: 1.5e-9. 240 vs 320: 1.6e-10. Not weakened: defaults are 240 for M!=4, 120 for M=4 (unchanged, byte-identical).
- GH120 vs trapezoid (2^15, +-12 sigma) at M=16, 8-30 dB: < 1.2e-8 (limit 1e-6).
- numpy hermgauss overflows past about 400 nodes; now raises ValueError.
- Bracket [-10,45] suffices for M=16 targets 0.5-3.99; widened only for M!=4 near H (M=4 is exactly H at 45 dB).
- bmd_raw < 0: M=8 -0.039, M=16 -0.083 at 0 dB (exp(-0.2x^2)).
- PAM4 on PAM16 {0,5,10,15}: SMD equal 1e-9; BMD lower by >5e-5 (labels differ).

## Notes for Loki
- Embedding tests fix nodes=240 on both sides, since M=4 default is 120 and rules differ by ~4e-8.
- Mutation check: sigma factor changed to 3 for all M made 41 tests fail.
- Not done by design: optimiser (C4), consumers still call legacy PAM4 signatures.
