# N0 Dev handoff (NANF workstream, source and schema gate; Dev, Opus 5.5 session)
Status: COMPLETE. Base 94a3ec9. Commits: 9a891c9 (plan, first), then the N0 docs/test commit, then this handoff. Tip SHA: in the final report. Local only.
Gate: 912 passed (905 + 7 new in tests/test_nanf_benchmark.py); anchor 15 passed; ruff check, ruff format --check, mypy clean. No dependency, src, config, golden, waveform, CHECKPOINT.md or E0 file touched except the three status docs as instructed.

## What changed
- docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md (sha256 c4771dc1...bef22, pinned in the test; committed before any workbook value check).
- docs/NANF_SOURCES_AND_PROVENANCE.md (checksums, licences, attribution text, figure-to-sheet map, schema, value checks, per-parameter provenance, mismatches, secondary sources).
- tests/test_nanf_benchmark.py (plan pin, label, closed provenance vocabulary, checksums, DOIs, no tracked third-party files; passes without data/external).
- Entries in ROADMAP_STATUS.md, ALGORITHM_PROVENANCE.md, engineering_log/LOG.md.

## Facts the reviewer should check
- PDF is an author manuscript (Word 2016, placeholders), not the published version.
- Brief mismatch: "group index" (paper: effective refractive index). Notes: 3.4+1.4=4.8 vs ~4.76 km; gross/net unstated (derived gross); (17,7) split unstated.
- Dataset: NANF 6/11 ROP points (Fig.4), 6/8 (Figs. 9, 12); Fig.11 SSMF 24 error cells (22.15 to 25.43 GHz); zero BERs at 80 Gb/s; no unit strings; Fig.1 in um, Figs. 5/6 in nm.
- Label fixed by structure: LITERATURE BENCHMARK / CALIBRATION ONLY (1 NANF spool, 1 SSMF spool, 1 session).
- Licence: dataset CC BY 4.0 per DataCite only (readme blank, landing page 403/unread); paper IEEE terms. Nothing third-party in Git.
- Secondary sources are Crossref metadata only; Altuna and CLEO both mention 11.1 km, so a shared spool cannot be excluded. "No shared spool" is not asserted.

## Honest limits
- Paper prose (ROP thresholds, 5/11/14 dB penalty, 138.09/112.52 Gb/s) was read before the plan; only workbook cells were blind. Tolerances are judgement.
- Plan C6 cites Fig.11 for the SSMF null, but its cells there are errors; score on Fig.8 (no amendment made).

## Review focus
- Plan section 2 split and section 4 criteria; sequence (plan commit 9a891c9 precedes the value checks).
- Whether the closed vocabulary should be merged with the E0 Provenance enum later.

## Next (not started)
N1 only after review PASS and owner go-ahead.
