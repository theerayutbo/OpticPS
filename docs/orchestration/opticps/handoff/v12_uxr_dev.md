# Handoff: v1.2 UXR (Dev), branch v1.2-uxr, rework 1

Not accepted; awaiting independent re-review. All fixtures are synthetic; no real UXR file was seen. The official guides (read as text, not committed) replaced earlier inferences.

## Files
- New: `src/opticps/measurement/uxr_compare.py`. Heavily changed: `receiver/capture_dsp.py`, `measurement/uxr_import.py`, `measurement/uxr_ingest.py`, `tests/test_uxr.py`.
- Edited: `cli/main.py` (`compare-uxr`, `--registry/--segment/--allow-waveform-type`, clean errors for uxr commands and `analyze`), `measurement/compare.py` (`analyze` refuses measured captures), `measurement/capture.py` (`optical_received_power_dBm` present but nullable), `tests/test_ingest.py`, `data/templates/capture_template.json`, docs (protocol, HARDWARE_COMPATIBILITY, VERIFICATION, STATUS, README, CHANGELOG), `output/README_SOUTHAMPTON.md` text only. Merge of main committed first (dfe7bfa); version stays 1.0.0.

## Rework findings (1 to 16)
1 tracking: early-late statistic on blocks of payload decisions, slope calibrated on training, line fit, one sequential pass then 2 refits. 2 `compare-uxr` plus `analyze` refusal. 3 lost frames counted, worst case stated. 4 content-hash registry (`--registry`, written after success). 5 training reports no payload value. 6 distinct symbols. 7 irregular spacing falls back; warning is true. 8 `--segment`, `--allow-waveform-type`. 9 units parsed. 10 manifest priors and symbol-rate gate, `reference_mismatch_suspected`. 11 length guard, no 1e-30 path, clean CLI errors. 12 full pytest after merge. 13 protocol overclaims removed (Profile B is 4.57 sps). 14 zero-error capture-level stats. 15 HDF5 links, external, virtual, shape and maximum checks. 16 NumSegments 0 is real (guide p2090); SavedInterpFactor warning.
Coordinator additions: null received power (A); UXR receiver docs and M8100 guide statuses (B); BIN strict validation replaces the unverified flag; HDF5 scaling cited to p598; CSV header fields parsed; manual SCPI table with pages.

## Results (this machine)
- Single frame, Profile B, sigma 0.33, 20 seeds, clocks -150 to +200 ppm: SER mean 6.5e-4, min 4.0e-4, max 8.8e-4. Multi-frame, same setup: 6.5e-4. Clock error at most 0.07 ppm.
- Counts and tip SHA: see the final reply.

## Limitations and open risks
- Tracking is decision-directed and needs band-limited edges. With unfiltered rectangular pulses the statistic is noisy; the result is then discarded or flagged unreliable. The 0.5-sample residual limit and the 10 ppm cap on corrections to a spacing-fitted clock are judgement values.
- A frame with a damaged but findable preamble is analysed and shows its errors; only frames with no preamble peak are "lost".
- The leakage registry cannot see other registries, re-exports or re-acquisitions (the protocol says so).
- CSV separator and spelling, BIN on a real file, and HDF5 attribute names against a real file are unverified. Manifest realised probabilities can sum to 1.000001; the gate accepts 1e-5.
- `reporting/report.py` placeholder text still says "receiver yet to be identified"; reports were not regenerated.
