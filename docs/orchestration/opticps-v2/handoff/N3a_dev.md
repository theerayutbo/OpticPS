# N3 part a, Dev handoff (2026-11-01)
Branch v1.3-mpam. Step 1 commit b7f4ac0 (plan Amendment 5). Step 2 commit: see git log. No push, merge, tag, fit, holdout read, or freeze.

## Plan
- Amendment 5 pin is in `tests/test_nanf_benchmark.py` (`PLAN_SHA256`), previous pin bc85d32c in `PLAN_SHA256_AMENDMENT4`.
- Grid: N must be a multiple of lcm(4,5,7)=140; capture 655200 symbols, 8192 training, 647008 scored, 1 294 016 bits. At BER 1e-4 that is 129.4 bit errors (the old "65" was wrong).

## Built
- `receiver/dfe.py`: RLS DFE (17 FF at T/2, 7 FB, lambda 0.998, delta 1e-2), FFE-only mode, generic levels and rates; exact-symmetric update, trace cap, Cholesky health check.
- `measurement/nanf_chain.py`: `simulate_point`, `first_null_ghz` (tone mode), exact resampling, sample-count arithmetic, B4 parameter table.
- `measurement/nanf_scoring.py`: C1 (rule C1-R), C2 to C8, B2B-copy, d, B2B gate, verdict, identifiability check (A1.7/B4).
- `measurement/nanf_freeze.py`: `HOLDOUT_LOCKED` guard in `read_nanf_workbook(include_holdout=True, freeze_hash=...)`. No record exists at `docs/benchmarks/NANF_FREEZE_RECORD.json`.
- Existing tests in `test_nanf_import.py` now unlock the holdout through a temp record (fixture), nothing else changed in them.

## Validation values (synthetic)
- Noise-free ISI channels: DFE output SNR 143 to 175 dB, zero decision errors. At a Nyquist null, 27 dB: DFE SER 0 and 26.9 dB, 17-tap FFE SER 0.18 and 9.6 dB.
- AWGN, Gray PAM4 vs Q expressions: z = -0.77, -1.53, 1.87 (slicer, 4e5 symbols); one-tap RLS within 4 sigma.
- Tone-mode nulls within 0.3 GHz of closed form (29.39, 27.97, 80.2 GHz).
- One full point: about 14 s (RLS loop about 12 s, analogue chain about 1.5 s), 3 rates x 3 links x 11 ROPs is about 25 min.

## For the reviewer
1. Trace cap acts continuously (band-limited T/2 input): constant-trace RLS, not a plain lambda 0.998. BER moved 3% between caps 1e4 and 1e8. F6 says only "cap on trace(P)". Decide if a plan note is needed.
2. F7.2 left a published point against a simulated bound open; code follows B1.3 (fail). Interpretation, not stated in F7.
3. C4: simulated zero-error counts as a miss always (default deny).
4. `NotImplementedError` mutant is equivalent (subclass of RuntimeError); code names RuntimeError only.
5. Another agent edits `src/opticps/benchmarks`, `CHECKPOINT.md`; not touched. A repo-wide `ruff check` fails on their `teriphic.py` line length if still present.
6. Gates: full pytest 1746 collected; 1742 passed in the full run before 4 last tests (all pass); anchor 15; ruff check, ruff format --check, mypy clean; license_audit 34 packages, 0 flagged; mutate_nanf 147 of 147 killed, unmutated copy ok.

## Fix round (2026-11-01, after handoff/N3a_qa.md)
- Plan Amendment 6 added (append-only, 0 lines removed; previous pin c5da4067...dcff, new pin in `tests/test_nanf_benchmark.py`). Made before any fit, freeze or holdout scoring; evidence is the review's synthetic repros.
- 1 Trace cap pinned at 1e10 (`PINNED_P_TRACE_CAP`); a run where it acts raises or is unscorable (`require_scorable`); no scoring route to change it. Review points reproduced exactly (errors cap 1e4 / 1e10 / none: 4639/5144/5144, 141/173/173, 75/81/81, 72203/80298/80298). OPEN: 22 of 108 synthetic mid-vector runs (ROP -16..-5) lose lock at BER 0.23+ (cap acts or P loses positive definiteness); not checked against the real ROP axes. Owner decision needed.
- 2 No-crossing rule is B1.3 (FAIL); 3 default deny (kind `invalid`, `InvalidDataError`); 4 freeze binds a committed artefact (path, SHA-256, commit ancestor of HEAD, vector, partition); 5 code identity from parsed imports (18 files) and `simulate_point` obeys the record; 6 real workbook unlocked only by the record at the committed path.
- 6 Fixture event: the real-workbook test parsed all 69 series (48 holdout) in process on every run with the data present since ba55025; asserted counts, sheet names, lengths, finite x, flag counts; no y value; nothing printed on pass. Test replaced; disclosed in G7. I ran nothing that opens the workbook.
- 7 Mutants: the 14 survivors and the guards of 1 to 6 added to `scripts/mutate_nanf.py`; behaviour tests in `tests/test_nanf_n3a_fix.py` (known-answer matched filter, timing, draw order, filters, DAC).
- 8 Minors fixed (F2 string, C4, NaN ROP, C3(b), truthy verdicts, `Crossing`, C5 1700 nm, C7 240, `b2b_copy`); np.clip declared; sweep estimate in G9: 336 points, about 90 min one core.
- Gate results: see the final report of the round (pytest count, mutants).
