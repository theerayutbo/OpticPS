# Brief: v1.2 rework 2 (Dev)

Review of 26453ab returned FAIL. Findings 1-16 mostly closed. Evidence: /private/tmp/claude-501/-Users-theerayut-Documents-Optics/78dc48d1-6a97-4f10-9765-b6fa96f032cb/scratchpad/loki2/ (dr.py, hd.py, outputs). Work in this worktree, branch v1.2-uxr. Same rules as earlier briefs. Do not push. Each fix gets a regression test from the scenario. Guides as text: scratchpad/uxr_dl/uxr.txt and scratchpad/m81_dl/m81.txt.

N1 BLOCKER capture_dsp.py:735-743,300-301. Two preambles with 2 symbols dropped mid-frame: a 2-point fit has zero residual, clock 61 ppm wrong, SER 0.453, reliable True. When the tracking guard rejects a large correction, reliable must clear with a specific warning. Consider using the tracker estimate to expose disagreement. Protocol should recommend 3+ frames. uxr_ingest.py:160-164: widen the mismatch gate, since SER 0.45 escapes 0.75.
N2 BLOCKER uxr_compare.py:68-73, uxr_ingest.py:61-79. Refuse repeated source_sha256 or samples_sha256 across run_ids: one acquisition cannot count as several runs. Note re-exports with different bytes cannot be detected, and say so.
N3 MAJOR uxr_compare.py:66. Compare hashes across training and test, not only capture ids.
N4 MAJOR uxr_import.py:264-274,292-299. Apply the same link, external storage, virtual and size checks to every dataset read, including Frame/TheFrame and FileType.
N5 MAJOR uxr_import.py:184,189-190. Guide p2090 example shows `Waveform Type = 1`. Read the guide's example near p2090 and accept its attribute names and integer forms alongside the help page names; map per the BIN table 1 Normal, 3 Average. Keep other types refused.
N6 MAJOR uxr_compare.py:76-108. Withhold a verdict when sources mix, or symbol rate or other controlled fields differ; keep profiles separate in grouping.
N7 MAJOR output/README_SOUTHAMPTON.md:94, README.md:66. Replace `opticps analyze` for measured captures with the ingest-uxr and compare-uxr path. Check every command in both guides by running it or reading its parser.
N8 MINOR uxr_ingest.py:54-58. All registry shapes fail with a clean error; HDF5 null dataspace too (uxr_import.py:222).
N9 MINOR uxr_ingest.py:35. Default registry resolved from repository root or stated explicitly in output.
N10 MINOR uxr_ingest.py:243. Sanitize capture_id for paths.
N11 MINOR uxr_import.py:487-491,523-533. Reject negative BIN sizes; do not silently relabel channels; handle or refuse multi-segment BIN.
N12 MINOR uxr_import.py:366-453. CSV Type=versus and Segments>1 refused by default; point mismatch is an error.
N13 MINOR uxr_import.py:197. Reject non-integer NumPoints; max_samples configurable through read_scope_file and CLI.
Optional: name the remedy in the 1e-9 probability validation error (renormalise realised probabilities or use design values).

Done means: pytest, ruff check, format check, mypy, license audit pass; no waveform file changed. Commit, ending with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update the handoff. Reply: per-finding status, test count, tip SHA, done or blocked. No file contents.
