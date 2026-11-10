# REWRITE Dev handoff (history rewrite of main..v1.3-mpam before the public push)

Date 2026-11-10. Full account and the old -> new id map: `docs/orchestration/opticps-v2/HISTORY_REWRITE.md`.
No offending text is written here; commits, paths and lines only.

## Result
- Rewritten tip before the one documentation commit (HISTORY_REWRITE.md and this handoff): `d76b730bb5cae5b6d4a470f02a6d37bfa98127a9` (after the content rewrite and a second `--mailmap` step that mapped the 7 local-hostname author/committer emails to the noreply address; 0 hostname emails remain). A third pass removed two short quoted article fragments; a later commit adds `docs/benchmarks/teriphic_e2/NOTICE.md` and updates the id map; old tip `138569239e656e3a10d8fb7378dff36d84ba1b13` (kept as `refs/backup/pre-rewrite-v1.3-mpam`, local only).
- `main` `a2eb969` unchanged. 82 commits above main; 65 have new ids (21 changed in content, 44 only by ancestry); the first 17 are identical.
- Tip tree identical to the old tip tree (`git diff` empty).

## Hits before and after (checked on all blobs of every commit, on messages, and on `git log -p`)
| class | before | after |
|---|---|---|
| Instrument serial (12eb480, 5713ed5, b7f4ac0; `docs/benchmarks/MISSING_PARAMETERS.md` line 110) | 3 commits, 3 blob versions, 1 path | 0 (plain, hex and base64 forms; messages 0) |
| Ran article text (hash-window detector, 7-word windows; `configs/benchmarks/ran_2025_g652d.yaml`, `docs/benchmarks/SOURCE_REGISTER.md`, `tests/test_benchmark_provenance.py`) | 18 commits, 6 blob versions, 3 paths, 193 windows | 0 |
| Commit messages (serial or article windows) | 0 | 0 |

Residual by design: bibliographic strings, cited numeric facts and phrases shorter than 7 words stay (for example the printed fibre-type string, a short quoted phrase about pre-emphasis in `SOURCE_REGISTER.md`, a short detector-bandwidth phrase of the TERIPHIC record).

## Content audit of branch additions (main..v1.3-mpam, all text, no blob over 300 KB)
| item | result |
|---|---|
| Ran article | text removed from history (above); tip register and config carry bibliographic strings and cited numbers only |
| Ran source-data XLSX | not present; only its file name and the "licence unverified" status are written; no values copied |
| Wiegart (IEEE) | bibliographic and licence note only; no figure, digitised or re-plotted point |
| IEEE Hong JLT article | citations only; fibre records are own wording with locator notes; no text or figure |
| D1889 (Southampton, CC BY 4.0) | attribution block present in `docs/NANF_SOURCES_AND_PROVENANCE.md` and `reports/NANF_Benchmark_Report.md` (creators, title, DOI, licence, changes); workbook not committed (`data/external/` ignored) |
| TERIPHIC (Zenodo 7886498, CC BY 4.0) | creators, title, DOI and licence in `docs/benchmarks/SOURCE_REGISTER.md` and the config; derived statistics only (`docs/benchmarks/teriphic_e2/*`, 276 KB largest), no capture; there is no TERIPHIC attribution line in README or CITATION.cff, which the owner may want to add |
| Credentials, tokens | none (only test strings and the word "token") |
| Personal data | only git author lines (the 7 local-hostname emails were mapped to the noreply address); no other email, phone, IP, home path in added lines |
| Private Southampton data | none; only the public dataset citation |
| OptiCommPy | not touched |

## Gates at the rewritten tip (fresh clone, data absent, `-o addopts="-rN"`, 34 per-file shards)
- pytest: 2136 collected, 2127 passed, 9 skipped, 0 failed. Skips are data-absent and platform skips already present.
- `ruff check .` passed; `ruff format --check .` 201 files already formatted; `mypy` no issues in 63 source files.
- `scripts/license_audit.py`: 34 packages, flagged 0.
- Anchor test `tests/test_pam4_anchor.py`: 15 passed.
- Failures caused by changed ids: none. Nothing in `src`, `tests` or `scripts` holds a commit id of the branch; the pinned SHA-256 values hash file contents, not commits, and the affected files are not among the pinned ones.

## E2 freeze
The R12 freeze commit `8a81907` is now `04360ec6a44bb6aaa2222cc605ab3979718be50a` (R10 `d520ff7` -> `dbd549f2c74f58edd862e60334c6ba33f33e8c97`, R11 `007b8b2` -> `ec1ac97cbf4fe3785a5e968450db3989a2bcd9eb`). Checked at the new tip with the real guard code: `first_parent_freeze` returns `79467d8`, `require_frozen_criterion` issues the criterion with that commit, `bind_to_freeze` passes, `require_freeze_pin` accepts the new id and refuses the old one. No re-freeze is needed (content and first-parent position are unchanged), but the pin that the owner holds outside the repository must be replaced by the new id before E2b. Ids written inside plans, handoffs and `CHECKPOINT.md` are old ids by design; read them through the map.

## Notes for the push (Aria)
- The clone's `origin` URL is the local checkout path; set it to the GitHub URL before pushing. `origin/v1.3-mpam` was deleted from the clone so the old tip is reachable only through `refs/backup/pre-rewrite-v1.3-mpam`.
- Push only `v1.3-mpam`. Do not use `--mirror`, `--all` or push `refs/backup/*`.
- The main checkout was not changed.
