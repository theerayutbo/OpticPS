# C3 Dev handoff (pair family, symmetric CCDM, profiling)

Base 2522755, branch v1.3-mpam. One local commit. Nothing pushed, merged, tagged. rates.py, test_mpam_rates.py, roadmap files, CHECKPOINT.md untouched.

## Files
- src/opticps/shaping/distributions.py: symmetric_from_pairs, pairs_of, mb_for_entropy (brentq), docstring states sign.
- src/opticps/distribution_matching/ccdm.py: quantize_symmetric_composition, symmetric_rate_loss, from_symmetric_probabilities, target_rate_loss, InvalidSymbolError. quantize_composition unchanged.
- tests/test_mpam_shaping.py (64 tests), scripts/profile_ccdm.py, docs/notes/ccdm_profile.md
- ALGORITHM_PROVENANCE, ROADMAP_STATUS, LOG.md entries.

## Findings
- Sign convention: P ~ exp(-lam x^2); lam > 0 inner-heavy (already the repo's; PS70 lam > 0). sign=+1 inner, -1 outer.
- MB(+lam) vs MB(-lam) entropy equal at M=4 only: M=8, lam 0.2: 1.708 vs 1.074 bits. Tested.
- Reachable MB entropy: 1 < H <= log2 M (M>=4); M=2 only 1.
- M=4 equality: holds at n = 32..16384 and 65536 on all 101 legacy PMFs (config n=1024 included). Not unconditional: legacy rule splits a pair on tied remainders (uniform n=6 -> (2,2,1,1)). Even n 2..2048 x 101 PMFs: 3330/103424 differ, all where legacy is asymmetric or raises. Legacy paths not switched.
- Decode: wrong composition -> CompositionError; right composition rank >= 2^k -> RankOverflowError; try_decode already existed. Gap fixed: negative symbol raised a raw numpy error, float block raised TypeError; now InvalidSymbolError (subclass of CompositionError).

## Profile (i5-8259U, Py 3.11.15, numpy 2.4.6, seed 20261031) M=16 enc/dec ms: n=256 0.8/0.7; 1024 9.3/9.9; 4096 129/135. Threshold 1 s not approached. Full table in docs/notes/ccdm_profile.md.

## Counts
Before 493 passed; after 557 passed in 250.05 s (anchor green). ruff check, ruff format --check, mypy clean.
