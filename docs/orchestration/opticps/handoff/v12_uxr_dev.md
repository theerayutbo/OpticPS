# Handoff: v1.2 UXR (Dev), branch v1.2-uxr

Not accepted; awaiting independent review. All fixtures are synthetic; no real UXR file was seen.

## Files
- New: `src/opticps/measurement/uxr_import.py` (HDF5/CSV/BIN), `src/opticps/receiver/capture_dsp.py`, `src/opticps/measurement/uxr_ingest.py`, `tests/test_uxr.py`, `docs/SOUTHAMPTON_UXR_LAB_PROTOCOL.md`
- Edited: `src/opticps/cli/main.py` (`ingest-uxr` added, others untouched), `pyproject.toml` + `uv.lock` (h5py, BSD-3-Clause, mypy override), `docs/sbom.cdx.json`, THIRD_PARTY_LICENSES, DEPENDENCY_AUDIT, CHANGELOG
- Unchanged: `output/`, `configs/`, `dsp.py`, `capture.py`, `compare.py`

## Results (this machine)
- `tests/test_uxr.py`: 36 tests, all pass. Full suite: 169 passed, 3 skipped, 1 failed.
- The failure is `test_reporting.py::test_engineering_log_is_complete`: committed `docs/engineering_log/STATUS.md` has no commit hash. Not caused by this branch; not touched.
- ruff check, ruff format --check, mypy clean; license audit 34 packages, 0 flagged; `git diff --stat output/` empty.
- Clock offset (ppm error): 4 frames at +100/-60 ppm and 50 ppm: <= 0.02; noisy 7-frame capture: 0.05; single frame: <= 0.5. Tests assert < 1 (multi-frame) and < 5 (single frame).
- 50 ppm uncompensated (32768-symbol frame): 31,941 errors of 63,488 vs 0 compensated.
- SER at sigma 0.5: 1016 errors in 28,672 vs analytic 0.0341, inside the 99.9% Clopper-Pearson interval.

## Design notes
- Linear processing: FIR (only if ratio > 1.05) + cubic spline to 8 sps; normalized linear preamble correlation; sub-sample peak by fine search; two passes (nominal rate, then estimated rate).
- Clock from regression of preamble spacing (>=3 frames: high, with stderr; 2: medium); 1 preamble: preamble-to-training spacing, low.
- One sampling phase per capture chosen on preamble+training FFE error (centre of the plateau). Calibration, FFE, likelihood fitted per frame on preamble+training only; guard symbols give real neighbours at frame edges.
- `compensate_clock=False` is a diagnostic switch (used by one test).
- Zero errors: `ser`/`ber` are None; reports say "0 errors in N symbols, 95% upper bound X" (one-sided).

## Limitations and open risks
- Interpretation: `split` already required by `validate_metadata`, so I kept that and added an `--split` fallback; no default. Training captures are fitted/diagnosed, never scored; the same capture id or file under both splits raises DataLeakageError (index in results dir).
- HDF5 scaling rules, segment layout, BIN widths, BIN "X Origin" meaning, and CSV header handling are unverified inferences; HDF5 attributes are read from the channel group only; BIN channel = waveform position.
- Single-frame clock is low confidence; long frames with one preamble can drift. Looped playback with period exactly one frame is assumed. Frames repeat the payload, so pooled errors are not independent. Synthetic NRZ edges ring through the anti-alias FIR; real bandlimited data should not.
- `ingest-uxr` output is not yet wired into `analyze_directory` paired comparisons.
