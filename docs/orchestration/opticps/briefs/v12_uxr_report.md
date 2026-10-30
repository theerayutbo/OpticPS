# Brief: v1.2 receiver-analysis report (Dev)

Final review of 1c821ca passed, but one user requirement was never delivered. Work in this worktree, branch v1.2-uxr. Do not push. No background monitors. Stay in scope.

## Requirement
Add `opticps uxr-report --results DIR [--output-dir reports] [--simulation results/synthetic/demo_results.json]`, in new `src/opticps/reporting/uxr_report.py`, building a PDF and Markdown from ingest-uxr and compare-uxr outputs, reusing helpers in reporting/report.py. For each waveform present among Uniform, Fixed PS70, Fixed PS80, Adaptive, plus Outer70 if present:
- transmitted and received waveform excerpts (the transmitted one from the exported CSV, the received one from saved analysis data; save an excerpt during ingest if absent);
- recovered symbol distribution against the target;
- eye diagram, from the saved `_eye.npz`;
- BER and SER with intervals, using the existing zero-error wording;
- signal quality: SNR, level means and spreads, R_SMD and R_BMD with `rate_estimate_reliable`;
- receiver acquisition configuration: model, measured sample rate, estimated symbol rate, clock offset ppm, frames found and lost, bandwidth, source format;
- simulation-versus-measurement comparison: match on waveform and profile, nearest received power in the simulation; state the power difference, or "no comparable simulated point";
- explicit uncertainty: statistical intervals, and physical measurement uncertainty as "not recorded" unless the sidecar gives it. Keep these two apart.
Also list the comparison verdicts, withheld reasons, flagged captures and set-point audit.

Label rule: the report header states the data_source of the captures. If any capture is simulated, print prominently "MOCK/SIMULATED CAPTURES: NOT LABORATORY MEASUREMENTS". Never call simulated data measured. Each figure carries the data source.

Generate `reports/UXR_Receiver_Analysis_Example.pdf` and `.md` from mock-receiver captures, committed as a clearly labelled example: small, under 3 MB, four PAM4 variants. Do not modify any other report.

## Also fix
- F2 uxr_compare.py:284: when wrong-reference captures are excluded for unreliability, the pair's reason names the reference flag, not only "insufficient paired runs".
- F3 output/README_SOUTHAMPTON.md:102 and uxr_ingest.py:230: flagged captures stay counted and listed, and their pair's verdict is withheld. Update the sentence "Automatic reports currently draw on simulated results" to name `opticps uxr-report`, and add the command to the guide and protocol.
- F4 uxr_import.py:363: variable-length string at /Frame/TheFrame gives UxrImportError.
- Known limitation, add to CHANGELOG 1.2.0, protocol: sample loss below about 1 symbol, synchronous with the frame period on one waveform in every run, may not be detected. Physically implausible, not impossible. Add receiver side items: no real UXR export has been imported.

## Tests
Report built from mock captures: contains the mock banner, each section, each figure file, a zero-error case wording, a withheld verdict, no simulation point available. A measured-labelled set does not print the mock banner, and a mixed set does. Page rendering not required in tests.

## Done means
Complete foreground full pytest, ruff check, format check, mypy, license audit pass; waveform CSV tree identical to main. Commit, ending with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update the handoff. Reply once: files, test count, report size, tip SHA. No file contents.
