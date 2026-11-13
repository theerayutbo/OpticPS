# E3 QA (Loki): Wiegart fixed-peak PAM4, Ran subcase, comparison layer

verified_sha: 265331e (range 784ad2c..265331e, 4 commits), reviewed in a fresh clone; `opticps.__file__` resolved inside the clone.
**Verdict: FAIL** (one MAJOR, narrow rework; everything else holds).

## Findings
1. MAJOR, W4a/W4b over-claim. The manuscript (Sec. III) states P_X(0) = 0.4 without a decoding metric, but `e3_wiegart._p0_row` builds the published point with `rate_definition=RATE_SMD` / `RATE_BMD`, i.e. it fills an unstated source condition, which `published_points.py` itself forbids. Repro: same point with `rate_definition=None` gives `NOT COMPARABLE: rate_definition is null on the published side`. The tolerance 0.05 also cannot separate the optimum from the paper's own fixed PMF at 0.35, which the paper contrasts with 0.4: model value 0.35 gives MISMATCH only through floating-point rounding (deviation -0.05000000000000002), and 0.351 would be a MATCH. Rework: report W4 as NOT COMPARABLE (metric not stated) with both values shown as information, or as an explicitly metric-agnostic row with a tolerance that excludes 0.35. Then correct the report, the handoff and `test_wiegart_row_statuses`.
2. MINOR, location. The report says the fixed PMF (0.35, 0.15, 0.15, 0.35) is in "Sec. II and Fig. 4b caption text". The Fig. 4b caption has no numbers; the PMF is in the Sec. II running text (and in the figure's tick labels).
3. MINOR, Gray caveat incomplete. The paper names a "binary reflected Gray code"; for 2 bits every Gray labelling gives identical BMD rates (I checked a swapped Gray map: identical numbers). A natural-binary labelling would give a BMD gain of 2.27 dB (MISMATCH). So the reading is forced by the paper, and the label choice decides MATCH versus MISMATCH. The report should say both.
4. MINOR, near-verbatim clauses. The W5 source text "operation range of on-off keying is larger for BMD than for SMD" (`e3_wiegart.py` and the report) is the manuscript's Sec. II clause with OOK spelled out. `TOL_P0_WHY` paraphrases the "close to the optimal distribution for a wide range" clause. Both are short, but the repository rule allows none; reword them.
5. MINOR, test gap. Mutant M5 (MATCH window doubled to 2 x tolerance) survives, because no test puts a deviation between tolerance and 2 x tolerance.
6. OBSERVATION. The tolerances first appear in the same commit as the computed rows (4c9861a), so "fixed before deviations" cannot be shown from history. The Dev discloses this, and the values (0.01 dB; rounding bound) are reasonable.
7. OBSERVATION. `compare` does not compare the evidence label: a MEASURED published point matches an ANALYTICAL model point. `wavelength_nm=0` is accepted. Neither affects any E3 row.

## Source check (manuscript text, extracted locally; SHA-256 3a49c2f8... confirmed)
0.83 dB SMD, 0.71 dB BMD, 0.63 dB fixed-PMF BMD, all at 1.0 bpcu: Sec. II running text after Fig. 2 (OK). Fig. 2b's annotation prints 0.84 dB for SMD (not used; the report's last-digit caveat covers it). P_X(0) = 0.4 at 1 bpcu for the dispersion-less model, metric unstated: Sec. III (OK). Wider OOK range for BMD than for SMD: Sec. II after Fig. 1 (OK). Config fields checked against the manuscript: Eq. 3 AWGN in the electrical domain, Eq. 4 PSNR = 9/sigma^2, symmetric family after Eq. 5, Eq. 6/7, 1550 nm, D = 17, 5/11-tap FFE, 45 GHz PD, equal peak-to-peak drive (all OK). The arXiv-versus-JLT numbering caveat is stated in the report.

## Recomputation (own code: trapezoid h(Y)-h(N) and bit posteriors, Brent root, bounded line search)
| quantity | Loki | Dev | paper |
|---|---|---|---|
| SMD gain, best symmetric | 0.8328 dB (uni 13.6917, shaped 12.8589) | 0.8328 | 0.83 |
| BMD gain, best symmetric | 0.7097 dB (13.8538 / 13.1441) | 0.7097 | 0.71 |
| BMD gain, fixed PMF | 0.6268 dB (fixed 13.2270) | 0.6268 | 0.63 |
| optimal P_X(0) SMD / BMD | 0.3981 / 0.3959 | 0.3982 / 0.3958 | 0.4 |
| OOK stops being optimal SMD / BMD | 10.70 / 12.05 dB | 10.70 / 12.05 | ordering only |
| Ran chirp-free nulls 5 km / 10 km | 68.20, 118.12, 152.50 / 48.22, 83.53, 107.83 GHz | same | none |
| Ran -3 dB 5 km / 10 km | 48.22 / 34.10 GHz (cos^2 = 0.5 checked) | same | none |
Gain is defined as in the paper: the PSNR uniform 4-PAM needs minus the PSNR the shaped PMF needs, at the same rate and the same peak. No unstated parameter was tuned (the only free choices are the label, which the paper fixes, and the line-search range).

## Other checks
Ran: the report says plainly that the subcase is not a reproduction and not a prediction. The MODEL GAP list is honest (nothing on it is held in the config). No 1550 nm default: the functions have no defaults, and `1550` appears only in tests. Licence: no figure, digitised value or equation image, and no absolute paths, hosts, tokens, serials or e-mails in the diff (grepped). Ran content is limited to bibliographic strings and cited facts. Freeze: the diff touches no E2-bound file. Compare probes: unit and rate strings differing in case or spacing, NaN values, tolerances of 0, negative, NaN or inf, and `read_from="figure"` are all refused or raise. No skips, TODOs or stubs in the new files. The tests include independent checks (closed forms, limits, a second and a third method, a time-domain simulation), not only self-pinning.
Mutants (9): killed M1 unit check removed, M2 one-side null accepted, M3 numeric rel_tol 0.5, M4 zero tolerance allowed, M6 natural labels in the grid method, M7 PSNR /10, M8 null index k+1, M9 not-applicable-but-set ignored. Survived: M5 (finding 5).
Tests I ran (clone, foreground): `test_benchmark_e3.py` + `test_benchmark_provenance.py` + `test_benchmark_e2_freeze.py`: exit 0, about 481 passed, 1 skipped (TERIPHIC files absent; counted from the progress lines because the summary line was cut off). Orchestrator full suite at 265331e: 4 shards, all exit=0, 2332 passed, 9 skipped (data/external absent), per its report (the shard logs end with exit=0 and have no summary line).
Not checked: `tests/test_pam4_anchor.py` (not run); JLT version of the paper; the Ran article text (not re-read, by rule); data/external contents (not opened, by rule).

## Round 2 at 9d89382

verified_sha: 9d89382 (fix commits ec40b2d, 9d89382 on top of 265331e; `opticps.__file__` resolved inside the review clone).
**Verdict: PASS.** The round-1 MAJOR finding is resolved. Two MINOR wording leftovers and two observations remain; none blocks the gate.
Scripts and logs for this round are in the reviewer scratchpad under `loki_e3/round2/` (r2_probe, r2_label, r2_ngram, r2_mutants, r2_targeted, r2_anchor).

Round-1 findings, re-derived from the code (not from the handoff):
1. Round-1 MAJOR (W4): RESOLVED. I ran `wiegart_rows()`. W4a and W4b are NOT COMPARABLE with "rate_definition is null on the published side", and the published 0.4 point has `rate_definition=None`. I then built the row's own published point and forced the model value to 0.35, 0.40 or 0.3982 with SMD or BMD, at tolerance 0.01, 1 or 1e9: all 18 cases are NOT COMPARABLE. The refusal happens before any deviation is formed, so `TOL_P0_UNUSED` can never decide a result; it is documented as a placeholder, which is honest. Mutant M12 (restore the rate definition) is killed. No W4 MATCH remains in docs/benchmarks or configs/benchmarks (grep), and the report gives both optima as information only.
2. Round-1 finding 2 (fixed PMF location): RESOLVED. "Sec. II running text after Fig. 2" matches the manuscript (the paragraph discussing Figs. 2a/2b).
3. Round-1 finding 3 (Gray caveat): RESOLVED. Both numbers are right, for different PMFs. My recomputation with natural-binary labelling (uniform needs 15.2232 dB): the Gray-optimal PMF p = 0.3959 gives 2.1593 dB; the natural-optimal PMF p = 0.4247 gives 2.2655 dB (my round-1 figure); the fixed PMF gives 1.6676 dB. The report's sentence ("2.16 dB for the Gray-optimal PMF"; W2 and W3 would be MISMATCH) is accurate as written.
4. Round-1 finding 4 (near-verbatim strings): RESOLVED. Both strings are rewritten. A 5-word n-gram scan of every added line in `265331e..9d89382` against the manuscript text finds 0 overlaps. No Ran text was added. The diff has no local paths, hosts or serials.
5. Round-1 finding 5 (boundary): RESOLVED. The closed window (|dev| <= tol is MATCH) is stated the same way in the `comparison.py` docstring and the report, and new tests probe the edge with exact binary fractions.
6. Hardening: RESOLVED. On both point classes, a wavelength or baud rate of 0, negative, NaN or inf is refused, and a fibre length that is negative or inf is refused. Fibre length 0 is accepted (back-to-back). Both evidence labels are carried in the result (M14 killed). The report's limitations state that a MATCH against a measured value is agreement, not validation, and that the tolerances share a commit with the rows.
7. Regression: CLEAN. W1 0.83278, W2 0.70972, W3 0.62683 dB at tolerance 0.01; W5 10.70 / 12.05 dB; R4 68.20 / 48.22 GHz. All identical to 265331e. `git diff --name-only 784ad2c..9d89382` touches no E2-bound file.
8. Sibling sweep: CLEAN. The only `PublishedPoint` builders are the gain rows and the P_X(0) row. Their filled fields (peak constraint, electrical drive, DSP none, SMD or BMD with Gray) are all stated by the manuscript for the Eq. 3 numerical results.

New findings this round:
9. MINOR, stale heading. `docs/benchmarks/E3_WIEGART_RAN.md` line 40 still reads "### Tolerances (fixed before the deviations were computed)", which contradicts the corrected disclosure in line 12 and in the limitations. Repro: `grep -n "fixed before" docs/benchmarks/E3_WIEGART_RAN.md`.
10. MINOR, handoff wording. In `handoff/E3_dev.md`, Results line 17 ("W4 ... all MATCH") and Open risks line 24 ("tolerance is rounding-bound") carry no inline marker. The superseding note appears only in the later fix-round section. That is acceptable for an append-only log but misleading to a reader who stops at Results; an inline "(superseded, see Fix round)" would fix it. Repro: `grep -n "W4" docs/orchestration/opticps-v2/handoff/E3_dev.md`.
11. OBSERVATION. `fec_threshold_ber = 0` is still accepted on both point classes. It affects no E3 row.
12. OBSERVATION. The handoff reports "504 passed" for the three files. My run gives 503 passed and 1 skipped (TERIPHIC files absent), which is consistent.

Mutants (in the clone, reverted after each): 14 applied, 14 killed. M1-M9 are the round-1 set, now including M5 (window doubled), which survived in round 1. The new ones are M10 (`<=` changed to `<`), M11 (tolerance doubled on entry; the first attempt was syntactically invalid, and the valid re-run was killed), M12 (W4 rate definition restored), M13 (positive check removed) and M14 (evidence labels not carried).
Tests (clone, foreground, `-o addopts=`): `test_benchmark_e3.py` + `test_benchmark_provenance.py` + `test_benchmark_e2_freeze.py`: "503 passed, 1 skipped in 224.62s (0:03:44)". `test_pam4_anchor.py`: "15 passed in 31.88s".
Not checked: the full suite at 9d89382 (the orchestrator is running it), ruff and mypy, and the JLT version of the paper.
