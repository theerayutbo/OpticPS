# E0 Dev handoff (Stage 3A, source inventory; Dev, Opus 5.5 session)
base: 8129eca. Commits: 8900748 (plan + .gitignore, first), 70dc3b2 (register, schema, configs, tests, docs), then the handoff commit. Tip SHA: see the final report. Local only.
Gate: 905 passed (853 baseline at 8129eca + 52 new in tests/test_benchmark_provenance.py); anchor 15 passed; ruff check, ruff format --check, mypy clean; license_audit 34 packages, 0 flagged; no dependency change.

## What changed
- docs/benchmarks/FIT_HOLDOUT_PLAN.md (sha256 6bf4238a...1254a, pinned in the test and the TERIPHIC config; committed before anything else).
- docs/benchmarks/SOURCE_REGISTER.md, MISSING_PARAMETERS.md (matrix, dependency map, importer audit).
- src/opticps/benchmarks/{provenance,catalog}.py; configs/benchmarks/{teriphic_pd1_pam4,ran_2025_g652d,wiegart_2021_peak_pam4}.yaml.
- docs/ROADMAP_STATUS.md (v2.1 delta, hashes), ALGORITHM_PROVENANCE.md, LOG.md, .gitignore (data/external/).
- No existing module, config, golden, waveform or CHECKPOINT.md touched.

## Facts the reviewer should check
- Every external fact is "summary" (WebFetch), none "verified". Unreadable: nature.com, PMC, IEEE pages.
- Discrepancies vs brief: Zenodo version (JSON Revision 2 vs page v1); EML "256 GSa/s" vs record "256 Gbaud"; "CW", "3-dB electrical" not seen; Ran dispersion is a measured value; Ran 200 Gb/s main text only MZM-1.
- Ran Source Data licence and Wiegart licence: LICENSE/REUSE TERMS UNVERIFIED. TERIPHIC data: CC-BY-4.0 (record level).
- Found data/external/teriphic/ being filled by a curl (PID 2517) not started by E0 (B2B full size, 2 km partial). E0 did not open or hash them. Owner should confirm authorisation.
- read_bin rejects 7 TERIPHIC-named fakes (tested). Residual: trailing bytes after a valid structure pass (measured, unchanged).

## Review focus
- schema rules in provenance.py (SIMULATED in measured fields, MD5 state, leakage) and strict loader at every level.
- Plan wording on grouping, locked 10 km, identifiability; numeric criteria deliberately deferred to a hashed addendum.
- Roadmap delta: 9 hunks, 5 lines removed, no gate invalidated.

## Next (not started)
E1 only after owner confirms download authorisation and review PASS: format hypotheses on B2B only.
