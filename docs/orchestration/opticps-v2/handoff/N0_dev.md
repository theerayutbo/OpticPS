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

## Fix round (after N0_qa FAIL, 4 MAJOR + MINOR; Dev, Opus 5.5)
Commits: 843d223 (plan Amendment 1 + new pin), then the docs/test/handoff commit. Local only. No fit, simulation, scoring; Fig.4, Fig.6, Fig.8 values and all holdout series stayed unread (read only: Fig.1 numerical curves, Fig.11 formula text, paper prose).
- Plan (findings 1, 2, 3): Amendment 1, previous SHA c4771dc1...bef22 recorded, new pin 92b20966...ce5c0. Chirp = unknown nuisance, `UNIDENTIFIABLE_PARAMETER`, never fitted; pre-registered zero-chirp null SSMF 29.39 GHz (4.53 km), 27.97 GHz (5 km), NANF 80.2 GHz (none in band); C6 expected to FAIL (about 5.4 GHz above the measured 24), tolerance not widened. B2B-copy comparator and `NOT DISCRIMINATING` rule for C1, C2, C5-NANF. C1 to C8 defined (log-BER interpolation, censored crossing bounds, penalty statistic). Calibration drops ROP above -5 dBm and BER=0/<1e-5. C6 on Fig.8 column C, 5-subcarrier median, window 20.0 to 32.8125 GHz, spike rule from the 70 GSa/s sub-multiples.
- Finding 11: Fig.8 below -5 dB count withdrawn from Sources and disclosed in plan A0. Disclosure also covers the C164 exposure and zero counts.
- Sources (4, 6 to 12): Fig.11 cells are `=-Inf` formulas (C163 to C187), likely unloaded subcarriers (inference); mismatch 1 corrected (workbook uses n as group index, no Corning data cited); mismatches 7 (Fig.1 panels) and 8 (four-way null disagreement) added; rows 4 to 14; CD curve and slope tagged; required ROP and 5/11/14 dB tagged `measured` (results the source reports; `derived` is for our own computations); May 2020 readme vs DataCite 2021-05, no session count; Fig.5 ROP also B2B; attribution uses the registered title, DataCite URL recorded as unread, facts-versus-expression added; section 7 "separate record".
- Test (5): content-based guard over tracked files (SHA-256 of PDF, zip, xlsx, readme, size-capped) plus rejection of tracked CSV/XLSX under docs/ or data paths; negative tests with renamed copies; mutant check (renamed xlsx tracked as docs/benchmark_table.xlsx fails the suite). Passes with data/external absent.
- Not fixed, by design: observations 13 and 14 (structural absence of NANF above -6.67 dBm; D one design value; vocabulary-line test) are recorded, not acted on.
- Gate: 1107 passed in the shared checkout (includes the parallel E0 fix work; NANF test file 10, was 7); anchor green; ruff check, ruff format --check, mypy clean.
