# Brief: v1.2 rework 1 (Dev)

Independent review of 44ce954 returned FAIL. Probes: /private/tmp/claude-501/-Users-theerayut-Documents-Optics/78dc48d1-6a97-4f10-9765-b6fa96f032cb/scratchpad/loki_probe.py and loki_ingest.py (read-only references; reuse their scenarios as tests). Work in this worktree, branch v1.2-uxr. Same rules as briefs/v12_uxr_dev.md. Do not touch output/. Do not push.

Fix, each with a regression test built from the scenario:
1. HIGH capture_dsp.py:258-264,277. One complete frame: clock from a 512-symbol baseline drifts across the frame. Add timing tracking across the frame, using decision-directed estimates from the capture itself (no reference payload), for instance a linear fit of timing error over the frame after a first pass, iterated. Payload decisions may steer timing, never scoring references. Target: single-frame Profile B at sigma 0.33, 20 seeds, SER close to the multi-frame value. If a residual cannot be solved, set `rate_estimate_reliable=False` with a specific warning.
2. HIGH Wire ingest-uxr results into paired comparison and report generation: a new `opticps compare-uxr --results DIR` or equivalent, using capture-level metrics, the fairness audit, MIN_PAIRED_RUNS, and the same verdict wording. Change the protocol so UXR captures never go through the periodic `analyze` path; make `process_capture`-based `analyze` refuse measured captures, directing to ingest-uxr. Keep simulated mock path working.
3. HIGH capture_dsp.py:216-219,232-237. Frames with a damaged preamble must not vanish. Predict expected frame positions from the clock and count; attempt them, or report them as lost with payload errors handled conservatively: report `frames_expected`, `frames_analyzed`, `frames_lost`, and a warning, and the reported SER range must state the exclusion. Reliable flag false when frames are lost.
4. MEDIUM uxr_ingest.py:42,122. Leakage guard must not depend on results directory. Use content SHA-256 of capture in sidecar-independent registry passed through a shared `--registry` path default under `data/private/`, written only after success. Make the protocol text accurate about what it can and cannot guarantee.
5. MEDIUM uxr_ingest.py:68, capture_dsp.py:471. Training captures must not report payload-derived values.
6. MEDIUM capture_dsp.py:444-445,469-470. Count distinct payload symbols, not frames times symbols. Reliability and rate estimates must reflect that repeated frames repeat the same symbols.
7. MEDIUM capture_dsp.py:252-254. If frame spacing is inconsistent, do not apply that fit: try the fallback or raise; a warning that says "not used" must be true.
8. MEDIUM Add `--segment` and waveform-type options; keep rejecting by default.
9. LOW uxr_import.py:265. Parse units in column titles; mV must scale or be rejected, never labelled V. Unknown units rejected.
10. LOW uxr_ingest.py:123-128. Gate: sidecar priors must match the manifest; symbol rate cross-checked; SER near random with low SNR gives `reference_mismatch_suspected` warning and reliable False.
11. LOW capture_dsp.py:155-156. Length guard with a clear message; remove the 1e-30 false-preamble path; CLI prints clean errors, rc 1.
12. LOW Confirm full pytest passes after merging main (already merged).
13. LOW Protocol lines 18-19: remove overclaims; Profile B at 256 GSa/s is 4.57 samples per symbol, so do not ask for 8.
14. LOW capture_dsp.py:315. Provide capture-level statistics at zero errors too; no BER 0.0 in reported output.

Also:
15. SECURITY uxr_import.py. Treat HDF5 as untrusted: use `get(name, getlink=True)` and reject SoftLink and ExternalLink; reject datasets with external storage or virtual layout; check shape against NumPoints x NumSegments and a configurable maximum before reading data; require NumPoints >= 2. Add tests.
16. OPEN QUESTION NumSegments=0 may be real for non-segmented captures; treat 0 as 1 with a recorded note, since the page does not settle this. SavedInterpFactor other than 0 or 1: add a warning that XInc meaning under interpolation is unverified.

Done means: uv sync, pytest, ruff check, ruff format --check, mypy, license audit pass; `git diff --stat main...HEAD -- output/` shows no waveform change. Commit, ending the message with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update docs/orchestration/opticps/handoff/v12_uxr_dev.md. Reply: per-finding status, test count, single-frame SER across seeds, tip SHA, done or blocked. Do not paste file contents.
