# Brief: v1.2 rework 3 (Dev)

Review of e1d7a9b returned FAIL: guards now block real use. Probes: /private/tmp/claude-501/-Users-theerayut-Documents-Optics/78dc48d1-6a97-4f10-9765-b6fa96f032cb/scratchpad/loki3/ (e2e.py, cmp.py, n23.py, n1.py, fp.py, wb.py, misc.py and outputs). Work in this worktree, branch v1.2-uxr. Do not push.

First: merge `main` (v1.1.0 is released there) into this branch, resolving conflicts. In v1.1 `LinkConfig` fields may be None, so read `effective_*` properties; this branch's code must follow. Set version 1.2.0 in pyproject.toml, `__init__.py`, CITATION.cff; CHANGELOG entry. Do not regenerate waveform packages; CSVs stay byte-identical.

Design decisions, from the orchestrator, implement as stated:
- R1 BLOCKER uxr_compare.py:177-183, compare.py:44. Split audit into set-points and measured outcomes. Set-points must match for a verdict: symbol rate, AWG sample rate, electrical amplitude, fiber length, attenuation setting, receiver bandwidth, capture sample rate. Measured per-waveform quantities (launch power, OMA, extinction ratio) are reported, never gate: they differ by design at fixed drive. Received power is reported with its spread, and gates only beyond a configurable tolerance, default 0.5 dB, with a warning in the output. A step-6 sidecar set must reach a verdict in a test.
- R2 MAJOR uxr_compare.py:33. One rule: a set-point absent from all or part of the runs gives a verdict labelled with an explicit "not recorded: X" caveat, never better treatment for missing than for partial data. Fix the "differ" wording.
- R3 BLOCKER uxr_compare.py:112-115. Group comparisons by condition: profile, attenuation setting, fiber length, then waveform and run_id. One verdict per condition; the same run id at different conditions is valid. Test: 2-point sweep gives one verdict per point. Update README step 7 and 11.
- R4 BLOCKER capture_dsp.py:815-821, :55. Tracker residual is not a clock failure when spacing is high confidence. With 3+ consistent frames, the spacing clock stands; a large tracker residual becomes an informational note, and reliable stays True. Keep the dispute check for 1 or 2 frames. The 30 GHz, 4.4 frame case must give reliable for all seeds at sigma 0.33 to 1.2 with a correct SER; keep N1 tests passing.
- R5 MAJOR uxr_ingest.py:43-44,217-221. Replace the SER/SNR gate with a test from known data that does not select on payload outcome: use the training block, whose symbols are known, comparing training SER/decision agreement against payload. A wrong reference yields good training but random payload. Flag only a large excess of payload SER over training-predicted SER. Never exclude flagged captures silently: they stay in, counted and flagged. Test at sigma 1.3 and 1.5 with the wrong-reference scenario still caught.
- R6 uxr_import.py:206: clean error on inf or nan units. R7 uxr_ingest.py:50: non-object sidecar, clean error. R8 uxr_import.py:172: bound metadata bytes. R9 uxr_compare.py:97: result without sidecar is an error or a counted warning, never silently dropped. Polish: `/Frame` stored as a dataset gives model unknown with a note, not refusal.

Add one end-to-end test following output/README_SOUTHAMPTON.md: a two-point sweep, 5 paired runs, Uniform and PS70, with realistic per-waveform power readings, at 30 GHz, yielding two verdicts.

Done means: pytest, ruff check, format check, mypy, license audit pass; waveform CSV tree identical to main; fiber reproduction test still passes. Commit, ending with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update the handoff. Reply: per-finding status, test count, tip SHA, done or blocked. No file contents.
