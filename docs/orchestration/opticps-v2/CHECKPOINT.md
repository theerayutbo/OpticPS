# Aria checkpoint, roadmap v2 run

Branch v1.3-mpam from a2eb969. Plan: PLAN.md (approved by owner 2026-10-31). Roadmap: OpticPS_Claude_Code_Roadmap_v2.md, untracked.
Dev Sonnet, Loki Opus. No Fable workers. No push.

C1 gate: PASS at de1fc73 after one FAIL (Loki verdict, 381 passed, Aria spot-check anchor rerun). Minors carried into C2: metadata lines in anchor checksum, 3 matrix statements, 1 citation.

C2 gate: PASS at e3502e5 on third review (owner chose common-grid integrator + guard after second FAIL). Minors for C4: spread over p>0; warning text at M!=4; pin panel order and +-12 sd; adaptive.py must force common_grid for measured M=4 channels.
C3: Loki FAIL twice, code correct, doc statements false. Aria continued without asking; no design decision; to be logged as deviation.

C3 gate: PASS at 5a851dd on third review (604 passed, ccdm AST unchanged from e65d1a9, mutation not rerun). OBS: try_decode broad catch may relabel internal errors, RuntimeError from __array__ propagates; non-blocking.

C4 first review: FAIL at 2b9e1fe (handoff/C4_qa.md): 3 MAJOR (bound floor unreachable; uniform wrongly charged CCDM loss; content hash trusted), 5 MINOR. Optimum values independently confirmed. Decisions: floor q>=1/n; uniform at power-of-two M is direct with zero matcher loss; hash recomputed from samples.

C4 gate: PASS at d9ba016 on second review (handoff/C4_qa2.md). Aria spot-check: full pytest 698 passed. MINORs 1-4 and observations 5-10 carried into C5a.

C5 first review: FAIL at 908dd0c (handoff/C5_qa.md): reportable flag not enforced on export; evidence label free in YAML. 7 MINORs. Arithmetic and byte identity confirmed. Decisions: export refuses non-reportable in required roles; generator hard-codes simulated.

Owner request 2026-10-31: implement Stage 3A gates E0-E4 per OpticPS_Master_Roadmap_v2.1.md and OpticPS_External_Benchmark_Claude_Code_Brief.md (untracked). No download of large datasets without owner permission. Order decision (Aria): C5 gate continues; Dev E0 runs meanwhile on disjoint paths; Stage 3A E0-E4 run next; C6-C8, Stage 3, Stage 2 resume after. Roadmap v2.1 delta on Stage 1 audited in E0.

Owner approved download of the 3 TERIPHIC PD1 Subassembly1 PAM4 files 2026-10-31. Saved read-only under data/external/teriphic/ (git-excluded via .git/info/exclude; E0 adds .gitignore). 163840136 bytes each; MD5 match brief values. SHA-256: B2B b9c5968a..., 2km 22fc7bb5..., 10km 053bf8c9.... Format unverified, not parsed. Holdout rule: do not inspect 2 km or 10 km contents before the frozen B2B stage.

Owner request 2026-10-31: NANF brief, gates N0-N4, source Hong et al. JLT 39(19) 6167-6174. Owner supplied FINAL_VERSION.pdf and dataset_JLT_NANF_vs_SMF.zip; moved read-only to data/external/nanf_hong2021/ (ignored). Zip SHA-256 f35c083e..., MD5 75df7a27...; PDF SHA-256 b5296da0.... Zip holds xlsx 45202 B and readme 2407 B; integrity OK, no path traversal; xlsx NOT opened so N3 partition can be declared first.
Rights: dataset CC BY 4.0 per DataCite rightsList for 10.5258/SOTON/D1889 (readme Licence field blank; eprints page 403 to fetcher, not read). Paper: IEEE copyright per Crossref (vor and am); PDF is Word-produced, version unconfirmed, keep out of repo. Attribution required. Raw xlsx stays out of Git until owner decides; CC BY would permit redistribution with attribution, but policy here keeps external data outside.
C5 gate: PASS at 8129eca on second review (handoff/C5_qa2.md, 853 passed). Aria spot-check: net rates by hand 111.125, 106.67 Gb/s. 9 MINORs carried into C6a; finding 1 (BestFixed name not compared with argmax) is closest to MAJOR and must be fixed first.

E0 Dev done at 94a3ec9, 905 passed. The curl Dev flagged was Aria's, owner-approved, no action needed. E0 docs say MD5 supplied: update to locally verified in E1.

E0 first review: FAIL at 94a3ec9 (handoff/E0_qa.md): 5 MAJOR (duplicate YAML keys, no value validation, CW claim, NC conflict, shared-sequence leakage). Plan must be amended before E1 reads B2B.

N0 gate: PASS at ee74d05 on second review (handoff/N0_qa2.md, 1107 passed). Aria spot-check: first-null 29.4 GHz by hand. 9 MINORs; items 2-7 need Amendment 2 and new pin before N1 scoring.

E0 second review: FAIL at eba060a (handoff/E0_qa2.md, 1105 passed): MAJOR: require_frozen_criterion passes re-commit, amend, backdate, assume-unchanged. Plus 6 MINOR incl. verbatim NC-ND sentences committed locally. Repros 1-12 and 14 closed. Stop condition reached for E0: owner decision needed. E1 and E2 held.

NEXT ACTION: await owner decision on E0; Dev N1 running (Amendment 2 first). Then E1, N2, N3, E2-E4, C6a minors, C6-C8, Stage 3, Stage 2.
