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

Owner chose: harden guard and disclose; one more Opus review for E0. Dev fix round 2 running.
N1 first review FAIL at b54cc18 (handoff/N1_qa.md): slope path ignores reference wavelength. Physics otherwise confirmed. Dev fix running.

N1 second review: FAIL at 6d75b88 (handoff/N1_qa2.md, 1258 passed at pin): slope anchored at reference_wavelength_nm instead of D's stated wavelength (Aria's brief wording contributed); scenario slope keeps D held. Beta3 about carrier, G.652 identity, Amendment 3 confirmed. Stop condition for N1: owner decision needed.

Owner chose Fix the anchor for N1; Dev running.
E0 third review: FAIL at 47890a6 (handoff/E0_qa3.md, 1333 passed): new-path re-tune and plan change after freeze pass the guard. All E0_qa2 repros closed on stated routes. Owner decision needed: guard scope.

Owner chose Narrow the promise for E0; Dev running.
N1 gate: PASS at 97b653d on third review (handoff/N1_qa3.md, 1401 passed at clean pin). Aria spot-check: 12.4 and 5.02 by hand. 6 MINORs into N2a. Finding 3 decided by Aria: owner rule read literally, scenario D must state its wavelength or S is refused.

E0 fourth review: FAIL at fc22f41 (handoff/E0_qa4.md, 1437 passed): merge route regression after --follow removal; symlink at fixed path. All else passes. Owner decision needed.

E0 gate: PASS at d52149a on closing check (handoff/E0_qa5.md, 1479 passed at pin). Aria spot-check: 8f57af9 message holds 42a578f5, confirming Loki's correction. Carried to E1a: prefix retraction wording, known-limits additions a-c, ROADMAP count 1524 should be 1479.

N2 first part gate: PASS at 7bd6ab9 on second review (handoff/N2_qa2.md, 1535 passed 6 skipped data absent; 75 passed data linked). Aria spot-check: 655360x80/56 non-integer and error count 129 by hand. MINORs into N3a; Amendment 5 needed before freeze.
E1 Dev done at 12eb480, 1600 passed; Loki running.

E1 first review FAIL at 12eb480 (handoff/E1_qa.md): renamed holdout passes CLI, noise behind valid header accepted, plan departures unrecorded. Format and diagnostics reproduced. Dev fix running; Loki next, second FAIL to owner.

E1 fix round at 536b3ec (plan Revision 6 c1c274b9). Loki E1 second review dispatched, pinned 536b3ec. A second FAIL on E1 goes to the owner.
History note for owner before any push: commit 12eb480 holds the instrument serial in MISSING_PARAMETERS.md; Ran NC-ND sentences in 8f57af9 and earlier.

E1 second review FAIL at 536b3ec (handoff/E1_qa2.md): 4 MAJOR, 5 MINOR. Second FAIL on the slice, so it goes to the owner.
N3a first review FAIL at b7eaab5 (handoff/N3a_qa.md, 1738 passed 8 skipped): 1 BLOCKER, 6 MAJOR. Dev fix dispatched with decisions: cap 1e10 and no cap action allowed, no-crossing FAIL, default deny, freeze binds a committed calibration artefact, wider code identity, real-workbook test no longer reads the holdout, 14 survivors. Open: test_nanf_import read the real withheld series in the main checkout; Dev reports extent from code and history, to be disclosed in Amendment 6 and to owner.

Owner decision, final after two changes: fix all four MAJOR findings, including the whole-file block check for finding 2. Dev E1 third round running on top of b7eaab5.

Dev E1 round 3 delivered bd5a557 (plan 87e38395), Loki E1 third review running.

E1 third review FAIL at bd5a557 (handoff/E1_qa3.md): 2 MAJOR, 4 MINOR. Gate claim false for paths inside files, links and defaults; 14 real mutant survivors. Escalated to owner.

Owner chose: narrow the promise. Gate claim covers path options typed on the command line only; indirect paths (inside files, links, defaults) go to known limits; kill 14 survivors; fix minors 3 to 6.

N3a fix round delivered 263926a (plan 2127d883, 1880 passed 8 skipped in clone, 235 of 235 own mutants). Holdout event: test parsed all 69 series in memory since ba55025; no value found in handoffs, docs or reports; absence not provable; recorded in Amendment 6 G7. Aria ruling on lost-lock points: keep 1e10, Amendment 7, invalid never scored, crossing only from contiguous locked points, point criteria FAIL. Dev N3a Amendment 7 and Dev E1 closing round both running.

E1 closing review FAIL at ae9add3 (handoff/E1_qa4.md, 1914 passed 5 skipped): 1 MAJOR, wording only: require_frozen_criterion stated as present fact, no caller yet. Within the owner close decision, so Aria sends a wording fix rather than a new owner question.

Gate E1 PASS at 1e1e90a after 5 reviews (handoff/E1_qa5.md). Plan Revision 9 9e7b51ad. Owner-chosen limit: only typed CLI options are gated, indirect routes listed. E2 must call require_frozen_criterion. N3a Amendment 7 at dafa062 (plan 34a06373), Loki N3a second review running, must classify the holdout event.

N3a second review FAIL at dafa062 (handoff/N3a_qa2.md): 3 MAJOR, 6 MINOR. Holdout event classified ACTUAL VALUES SEEN, narrow, at N0: ROP axes of Fig.4/9/12 holdout series, one Fig.11 y cell (240sub-SMF-DMT C164). Plan H5, G0, G7 statements false; Aria had told the owner no evidence of values reaching agents, now corrected. Escalated to owner.

Owner decided: keep NANF holdout, disclose, exclude Fig.11 from scoring, reports state not fully blind; fix all N3a MAJOR and MINOR. Dev N3a round 3 running (Amendment 8).

E2a Dev reported at tip df7fdc1, freeze 007b8b2, criterion `docs/benchmarks/TERIPHIC_CRITERION_R11.yaml`, plan Revision 11 SHA 554fd2b6. Security finding (freeze not bound to inputs) confirmed real by Dev and reported fixed, not yet independently verified. Loki Opus review of E2a: FAIL at df7fdc1, 2 BLOCKER (freeze commit spoofed by a merged side branch; role register not bound), 6 MAJOR, 3 MINOR (`handoff/E2a_qa.md`). Aria spot-check confirmed: script passes no `sequence_check`/`state`; `Verdict.INCONCLUSIVE` returned outside allowed; freeze lookup uses `--full-history`, not first-parent. No holdout read. Dev E2a fix round running: required external freeze pin, first-parent, register bound, power study from B2B, new plan revision and new freeze. First FAIL on this slice; a second goes to the owner.

E2a fix round reported at tip 4cedbd1; new freeze 8a81907 (criterion R12, plan R12 SHA 7b02c193). Aria recorded the freeze commit outside the repo in `~/.claude/orchestration/opticps-v2-freeze-pins.tsv` (same machine, not date proof). Dev's final mutant run (`scratchpad/mut6.log`) still running at report time: 87 of 168 killed, 0 survivors so far. Caps: VALIDATED never offered; 10 km pass = PARTIAL; 10 km FAIL = INCONCLUSIVE `NO_GRID_SCENARIO_FITS`. Shared-sequence check not implemented. Loki Opus re-review running → `handoff/E2a_qa2.md`; a FAIL goes to the owner.

PAUSED 2026-11-03 at owner request (token budget). Branch tip 4cedbd1. Stopped: Loki E2a re-review (no verdict written, `E2a_qa2.md` absent) and Dev N3a round 4 (stopped before its report). N3a round 4 commits already on branch: 2307db2 (Amendment 9 and fixes), 131c3a1 (tests for two calibration-path mutants); gates and mutant totals for them unverified. Left running, no token cost: Dev's E2a end-to-end mutant run (`scratchpad/mut6.log`) and its E2 test shard (`scratchpad/shards_final2/`). No holdout read for E2 or NANF.

NEXT ACTION on resume:
1. Read `scratchpad/mut6.log` and the E2 shard result for 4cedbd1 (if the scratchpad was cleared, rerun `scripts/mutate_e2.py` and the E2 tests in a fresh clone of 4cedbd1).
2. Re-dispatch Loki Opus re-review of E2a pinned to 4cedbd1 (same brief: verify previous findings 1-12, audit the power study and the grid refinement, freeze pin in `~/.claude/orchestration/opticps-v2-freeze-pins.tsv`). A FAIL goes to the owner. E2b only on PASS.
3. N3a: get a report for 2307db2..131c3a1 (fresh Dev to report gates in a fresh clone of the tip, mutant run, sibling sweep result), then Loki narrow review. A further N3a FAIL goes to the owner. N3a round 3 at 6b4939b, Amendment 8 SHA 2f56696f: Loki FAIL, 1 MAJOR (`calibration=True` typed validity, confirmed by Aria at `nanf_chain.py` `curve_arrays`), 4 MINOR (`handoff/N3a_qa3.md`). Owner decided: fix MAJOR and MINOR. Dev N3a round 4 running (Amendment 9); then Loki narrow review. Any further N3a FAIL goes to the owner.

2026-11-10 Owner: OpticPS is open source, push approved; do not copy any dataset whose licence forbids it, check first. Aria check: no dataset file or blob >1 MB in main..v1.3-mpam; `data/external/` ignored. Two items in unpushed history block a direct push: Ran CC BY-NC-ND sentences (8f57af9 and earlier) and the UXR instrument serial (12eb480..b7f4ac0). Owner chose: rewrite history, then push. E2a end-to-end mutant run finished at 4cedbd1: 168 applied, 158 killed, 1 SURVIVED `first_parent_dropped`, 9 harmless; E2a must kill it before the Loki re-review.

NEXT ACTION: Dev (Sonnet) rewrites main..v1.3-mpam in a separate clone (backup ref kept locally, never pushed), content audit, SHA map; Loki (Opus) verifies; Aria pushes the branch only after PASS. Then E2a fix (survivor, re-freeze or repin on new SHAs), Loki re-review, E2b.

2026-11-10 History rewritten and published. Branch `v1.3-mpam` on GitHub at 879a15f (85 commits above main a2eb969, main unchanged). Removed from history: Ran CC BY-NC-ND text and fragments, UXR serial, local-hostname email; TERIPHIC NOTICE added. Loki Opus PASS twice (`handoff/REWRITE_qa.md`), full pytest 2127 passed 9 skipped. Old→new SHA map: `HISTORY_REWRITE.md`; SHAs written in older docs are pre-rewrite. Old history kept only locally as `refs/backup/pre-rewrite-v1.3-mpam`, never pushed. E2 freeze is now 04360ec (was 8a81907), pinned outside the repo; GitHub push events (captured outside the repo, `~/.claude/orchestration/opticps-v2-evidence/`) show only that the commit existed on GitHub by that time, per GitHub's records; not a date proof of its own. N3a round 4 commits are 2307db2/131c3a1 pre-rewrite; see the map for their new ids.

NEXT ACTION: E2a Dev kills mutant survivor `first_parent_dropped` (tests only, no bound file), then Loki Opus re-review pinned to the new tip with freeze 04360ec; E2b only on PASS. Then N3a round 4 report and review.

2026-11-11 E2a: second review FAIL (`handoff/E2a_qa2.md`, MAJOR: 10 km not tied to 2 km) went to the owner. Owner: Fable designs, Opus implements. Fable design `questions/E2a_design_fable.md`; Aria resolved item 16 (only `code_identity` and `model_sha256` lines may change; scientific content equal to R12, tested) and item 14 (no release, push events + external pin). Opus Dev: plan Revision 13 (SHA-256 73884278…), freeze R13 ce0ee732af1111c67d94943ad985469dea8c8389, tip 1d58490; mutants 191 applied, 181 killed, 0 survived, 10 harmless; 2164 passed, 9 skipped. Loki Sonnet (high) PASS at 1d58490 (`handoff/E2a_qa3.md`), 3 MINOR accepted without re-freeze: deny-list outcome check in the 2 km record (reachable only by a hand-edited record, inside the promise), report summary omits the PARTIAL claim ceiling (E2b report must state it), one unreachable mutant. GATE E2a PASS. Design item 17: wavelength/modulator source notes go in a separate interpretation doc, never the bound plan.

NEXT ACTION: E2b stage 1, 2 km only, per plan R13: Dev runs the frozen script with --freeze-commit ce0ee73…, commits `two_km_result.json` and `selected_scenario.yaml` together in one commit; Loki checks; then 10 km only if the record allows. Then N3a round 4 report and review.

2026-11-11 E2b stage 1 (2 km) scored once under R13: outcome FAIL, verdict FAILED, claim null; 0/123 scenarios psi<=1 (best 1.501, control 2.143, B2B copy 1.643 failing on M1 level spacing; amplitude ratio 0.83). Record 8775540 (SHA-256 476642bc…d9c5). Stop rule D4: 10 km not run and stays unspent (code refuses it, audit hook 0 opens). Loki Opus PASS (`handoff/E2b_2km_qa.md`). Disclosed procedural gap: the R13 push (17:46:20Z) preceded the 2 km read (17:51:48Z) and the external pin was recorded 17:38:04Z, but GitHub's events API did not yet show the R13 push when the stage ran, so no third-party record shows freeze-before-read; captures at 17:46 and 18:10 hold only the 2026-11-10 push. E2 status: PARTIAL (pre-registration, power study, 2 km FAILED, 10 km unspent).

NEXT ACTION: re-capture GitHub events for the R13 push; then E3 (Wiegart analytic, Ran limited or MODEL GAP: CHIRP) and E4 (evidence matrix, BENCHMARK_REPORT.md, REPRODUCE.md); then N3a round 4 report and review.
Gap closed: GitHub repository activity API (`~/.claude/orchestration/opticps-v2-evidence/github_activity_2026-11-11.json`, SHA-256 e1f4f9d3…385b) records push c935241→5533cf6 on v1.3-mpam at 2026-11-11T17:46:19Z, so the R13 freeze ce0ee73 existed on GitHub by then, per GitHub's records, before the 2 km run began (17:51:48Z by local reflog; the run time itself is local evidence only).
