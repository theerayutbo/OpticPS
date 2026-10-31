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

## Fix round (2026-10-31, after Loki FAIL on 94a3ec9; findings in handoff/E0_qa.md)
Commits: 8f57af9 plan Revision 1 (pin 42a578f5...d358a, previous 6bf4238a...1254a), then code+configs+docs, then this handoff. Tip SHA in the final report. Gate: full pytest 1105 passed (includes N0's tests; E0 file 52 -> 244), anchor 15, ruff check and format clean, mypy 50 files clean, license_audit 34 packages 0 flagged.
Findings (QA numbering): 1 duplicate keys refused (custom SafeLoader, merge keys flattened first), both repros tested. 2 typed validation in the constructors. 3 "COTS laser source". 4 NC section in the register, LicenseRecord derivatives and commercial_use, the gate fails for Ran. 5 and 6 plan Revision 1 and holdout.py. 7 local hashes are not init fields, only verify_local_asset sets them. 8 leakage on file name, supplied MD5, local hashes and case-normalised group, called by SourceRecord and so by the loader. 9 register discrepancies 1, 3, 4, the scope sentence and the EML 0 NRZ fact. 10 RECORD_LEVEL rename, facts re-read raw and raised to verified only where read. 11 schema holes. 12 mutants below. 13 deferred to E1 (MISSING_PARAMETERS.md section 3). 14 tautology replaced by: load_mpam_config refuses all three benchmark configs. Local hashes of the three files are in SOURCE_REGISTER (orchestrator-reported, never opened here). E1 will run verify_local_asset on them.
Deviations to know: holdout.py is new (the enforcement the plan names); it adds no ErrorCode (the eight stay); the commit-order of a holdout statistic cannot be seen by the tool, so E2 must test that its entry point calls require_frozen_criterion first. "Gate ignores status" is redundant by construction (UNVERIFIED cannot hold a grant) and is killed by forcing the status past the constructor. The one equivalent mutant found (same hash, other role) was removed by comparing the group only, since a group has one role. Re-read facts: Zenodo 7886498/7886228, DataCite, Crossref x2, Europe PMC XML; Zenodo 'v1' was a tool artefact; Ran 2.4e-2 and 3.8e-3 sit in the Simulation results section; fibre is printed "G652.D".
Mutants (each applied on a scratch copy and run against tests/test_benchmark_provenance.py): 185 applied, 185 killed, 0 survived. All 12 earlier survivors are among them (baud_bd and dispersion drops, LEAKAGE code on hash branch, list/dict value, proxy, copy, gate status, gate permission, source_id mismatch, size positive, hex length, blank text).
- MEASURED_FIELDS drops one name x14: baud_bd, calibration, detector, dispersion_ps_per_nm_km, fec_threshold, fibre_length_km, fibre_type, modulation_order, raw_format, reference_sequence, sample_rate_hz, transmitter_type, wavelength_band, wavelength_nm
- overlap x11: group not case-normalised; local MD5 identity dropped; group-role check removed; file name not case-normalised; local SHA-256 identity dropped; LEAKAGE code removed on identity (hash) branch; file name identity dropped; identity compared on role only (group difference ignored); LEAKAGE code removed on group branch; supplied MD5 identity dropped; identity match never raises
- SourceRecord x13: source_id mismatch check removed; asset type check removed; plan_sha256 hex length 64 -> 63; overlap check not called; licences list kept (aliasing); retrieved date not parsed; source parameters unchecked (SIMULATED/typing); duplicate filename check removed; assets list kept (aliasing); empty licences allowed; duplicate licence scope check removed; licence type check removed; kind unchecked
- parameters x7: unknown name allowed; field typing skipped; record type unchecked; proxy removed; SIMULATED check removed; copy removed; NOT_COMPARABLE code removed
- AssetRecord x9: size type unchecked; group check removed; missing-field check removed; checksum type unchecked; source_id allow-list removed; size positive check removed; split type unchecked; size bool allowed; filename allow-list removed
- allow-list x5: id regex allows slash; group part check weakened; '..' check removed; doi regex check removed; filename regex allows slash
- text x4: control-character check removed; NUL (ord 0) allowed; DEL allowed; blank check removed
- hex x3: uppercase allowed; non-str unchecked; length unchecked
- ParameterValue x11: value with UNKNOWN allowed; non-finite accepted; unit text unchecked; source_ref not needed; placeholder strings accepted; provenance type unchecked; bool accepted; 'null' alone accepted; null needs UNKNOWN removed; list accepted; read_how unchecked
- field x21: non-negative rule removed; baud unit changed; dispersion unit changed; modulation float accepted; text field may have a unit; numeric string accepted; non-negative rejects zero; baud positivity lost; modulation order 3 allowed; modulation order set unchecked; unknown value skipped check removed; positive rule removed; unit consistency removed; wavelength positivity lost; modulation order 32 allowed; modulation unit allowed; positive rule allows zero; sample rate unit not Hz; length may be negative; modulation order 2 refused; text field may be a number
- licence x12: UNVERIFIED may grant; RESTRICTED allows commercial; read_how unchecked; UNVERIFIED checks only public; RESTRICTED allows derivatives; note type unchecked; scope unchecked; RESTRICTED may grant; status type unchecked; RECORD_LEVEL needs id removed; RESTRICTED allows private ALLOWED; permission types unchecked
- gate x7: commercial ignored; license_for returns first licence; derivatives ignored; status ignored; derivatives skips redistribution check; permission ignored; LICENSE_UNVERIFIED code removed (commercial)
- checksum x7: MISMATCH never reported; local MD5 typeable; SUPPLIED reported as ABSENT; local SHA-256 typeable; supplied MD5 unchecked; VERIFIED whenever local present; supplied MD5 length 32 -> 31
- verify x8: MD5 not fed; supplied MD5 dropped; SHA-256 not fed; local SHA-256 not stored; only first chunk hashed; local MD5 not stored; missing file not SOURCE_MISSING; directory accepted
- loader x21: duplicate keys allowed; version 1.0 accepted; non-mapping allowed; enum errors unwrapped; commercial_use not read; missing licences code removed; merge keys not flattened; version True accepted; licence list type unchecked; missing file not SOURCE_MISSING; size passed as 1; unhashable key unchecked; unknown keys allowed; assets list type unchecked; YAML errors unwrapped; asset source_id not from source; strict loader not used; missing keys allowed; parameters mapping unchecked; derivatives not read; require_local_asset never raises
- holdout x23: VALIDATION not a holdout; metric set unchecked; limit positivity unchecked; uncommitted accepted; commit not returned; any split passes; missing criterion file accepted; limit bool accepted; limit zero accepted; no-commit accepted; limits writable; nothing is checked; plan hash not compared; limit type unchecked; version unchecked; outside repo accepted; file hash wrong; LOCKED_TEST not a holdout; key set unchecked; limit finiteness unchecked; version float accepted; strict YAML replaced by safe_load; metric M4 removed
- verdicts x5: VALIDATION may be VALIDATED; reserved may be VALIDATED; failed validation ignored; LOCKED_TEST never VALIDATED; B2B may be VALIDATED
- ber x4: code removed (unknown); unknown reference accepted; inferred reference accepted; code removed (inferred)
