# Brief: v1.2 UXR receiver import and capture DSP (Dev: Grok)

You work in this git worktree on branch `v1.2-uxr`. OpticPS is an MIT, clean-room Python package (src/opticps, uv, Python 3.11). Do not copy code from any external project. Do not push. Do not touch `output/` or `configs/m8199b_profiles.yaml`: transmitter waveforms must stay byte-identical. Do not change behaviour of existing functions other than by adding optional parameters. Match surrounding style: small functions, type hints, one-line docstrings, `# SPDX-License-Identifier: MIT` after the module docstring.

Never invent lab data, Keysight commands or file fields. If something below is not stated, stop and record it as a limitation.

## Read first
`src/opticps/receiver/dsp.py`, `src/opticps/measurement/capture.py`, `src/opticps/measurement/compare.py`, `src/opticps/transmitter/frame.py`, `tests/test_rx_channel.py`.

Key defect to address: `process_capture` treats the capture as one exact period (circular FFT filtering, correlation, wraparound indexing, and a resample length rounded from nominal rates). A real oscilloscope capture is NOT periodic, may hold several or partial frames, and runs on a different clock from the AWG.

## Task 1: new file `src/opticps/measurement/uxr_import.py`
Return a dataclass `ScopeWaveform(samples_v, x_increment_s, x_origin_s, y_units, channel, model, serial, saved_date, source_format, attributes)`. `measured_sample_rate = 1 / x_increment_s`.

**HDF5** (add `h5py` to dependencies; it is BSD-3, confirm in metadata). Layout from Keysight's Infiniium "HDF5 Schema" help page:
- `/FileType/KeysightH5FileType` scalar string; `/Frame/TheFrame` compound strings Model, Serial, Date.
- `/Waveforms` group, attribute `NumWaveforms`; channels are groups `Channel N` holding dataset `Channel NData`.
- Group attributes include `NumPoints`, `XInc`, `XOrg`, `XUnits`, `YInc`, `YOrg`, `YUnits`, `WaveformType`, `SavedInterpFactor`, `NumSegments`, `Start`.
- Inferred, not stated by Keysight: time = XOrg + i * XInc; volts = YOrg + raw * YInc. The save dialog offers integers or floats, and the page does not say how a float dataset relates to YInc/YOrg. So: integer dataset, apply scaling. Float dataset: treat as already in volts, and record `scaling_assumption` in attributes. Mark this as unverified.
- Reject: YUnits other than Volt, XUnits other than Second, NumSegments != 1 unless a segment is selected, XInc <= 0, NumPoints mismatch, WaveformType other than NORMAL or AVERAGE unless allowed, missing channel. Handle bytes or str attributes and scalar or 1-element array attributes.

**CSV.** The Infiniium CSV header layout could NOT be confirmed. Accept only: optional leading rows that are non-numeric, then numeric rows of two columns (time, value) or one column. Two columns: derive XInc from the time axis, requiring uniform spacing within 1e-3 of the step. One column: require XInc from a header row matching `XInc` or an explicit `x_increment_s` argument; never guess. If a header row states a YUnits-like unit other than volts, reject. Do not assume the transmitter CSV layout (a `DataOut1` file must be rejected with a clear message).

**BIN.** Keysight's "BIN File Format" page gives field order but not integer widths. Order: file header: Cookie (2 bytes), Version (2 bytes), File Size (integer), Number of Waveforms (integer). Waveform header: Header Size (int), Waveform Type (int), Number of Waveform Buffers (int), Points (int), Count (int), X Display Range (float), X Display Origin (double), X Increment (double), X Origin (double, page text ambiguous), X Units (int), Y Units (int), Date (16 chars), Time (16 chars), Frame (24 chars), Waveform Label (16 chars), Time Tags (double), Segment Index (uint). Data header: Size (int), Buffer Type (short: 1 = float32 normal), Bytes Per Point (short), Buffer Size (int). Unit codes: 1 Volt, 2 Second. Parse assuming 4-byte little-endian ints and floats, using Header Size fields to advance. Require argument `accept_unverified_bin=True`; otherwise raise explaining it is unverified on real files. Check File Size equals actual size. Reject anything but buffer type 1.

## Task 2: new file `src/opticps/receiver/capture_dsp.py`
`analyze_scope_capture(waveform, symbol_rate_nominal, frame, priors, taps=15, equalizer="ls") -> ScopeAnalysis`, for non-periodic captures:
1. Remove mean; resample to 8 samples per nominal symbol with a linear (non-circular) band-limited or cubic method.
2. Find every full frame by LINEAR correlation with the known preamble, using the known symbols, with polarity detection. Report frames found; raise if none is complete.
3. Estimate the actual symbol rate from the spacing of preamble peaks over the capture (refined sub-sample, e.g. parabolic peak). With one frame only, estimate from fine correlation of preamble and training parts, and report the lower confidence. Report the clock ratio in ppm relative to nominal.
4. For each complete frame, sample at corrected symbol centres by interpolation, search phase with the preamble, then reuse `calibrate`, `train_ffe`/`lms_ffe`, `apply_ffe`, `estimate_likelihood`, `detect_minimum_distance`, `detect_map`, `evaluate`. Fit on preamble and training only. Use ordinary (non-periodic-safe) handling at frame edges.
5. Return per-frame `Metrics`, pooled errors, Clopper-Pearson intervals, capture-level bootstrap via `opticps.statistics.intervals` when there are at least 2 frames, a run-time eye data array, recovered symbol histogram, and `measured_sample_rate`, `estimated_symbol_rate`. Zero errors must be reported as an upper bound such as "0 errors in N symbols, 95% upper bound X", never as BER 0. MI/GMI: flag `rate_estimate_reliable=False` when any level has fewer than 100 test symbols.

## Task 3: CLI and pipeline
Add `opticps ingest-uxr --input FILE --channel 1 --sidecar JSON --profile P [--accept-unverified-bin] [--results DIR]`, keeping existing commands unchanged. The sidecar is the existing capture metadata schema in `capture.py`; add an optional `split`. Reject a mismatch between the sidecar's declared sample rate and the file's measured one above 1 ppm-independent tolerance of 1%; always use the measured value in analysis. The training/test separation in `analyze_directory` must carry over.

## Task 4: `docs/SOUTHAMPTON_UXR_LAB_PROTOCOL.md`
Capture, export (H5 preferred, All Data, record whether integers or floats were saved), acquisition settings to record, sidecar, import, matching to the transmitter reference via `related_transmit_experiment_id`, report generation. State clearly: exact UXR model suffix unconfirmed; UXR Programmer's Guide (9018-07723) could not be read, so no SCPI is provided; ask Southampton to send one small real H5 and CSV export so the importers can be verified. Do not state bandwidth or memory figures. Use "at least 2 full frames" and duration figures 4.096 us and 1.170 us per frame.

## Task 5: tests `tests/test_uxr.py`
Synthetic fixtures written by the test using h5py and struct, built from a real `build_frame` frame through `opticps.optical_channel.link.transmit`:
- HDF5 int and float scaling round trip; every reject case; bytes attributes.
- CSV two-column, one-column with header, `DataOut1` rejected, non-uniform time rejected.
- BIN round trip with flag; refused without flag; wrong file size rejected.
- Capture at non-integer samples per symbol (for example 256 GSa/s at 8 GBaud on a 100 ppm clock offset) with several partial frames, random start, inverted polarity: zero symbol errors at high SNR; estimated clock offset within 5 ppm with several frames; DC offset and gain recovered.
- 50 ppm with no compensation fails or degrades, proving compensation matters.
- SER at moderate noise inside the Clopper-Pearson interval of the analytic value.
- Zero-error reporting phrase test; leakage guard test.
Do not use skip, xfail or stubs. Fixtures are labelled synthetic.

## Done means
`uv sync`, `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy` all pass; `scripts/license_audit.py` passes; `git diff --stat output/` is empty. Commit on `v1.2-uxr` with a clear message.

Write `docs/orchestration/opticps/handoff/v12_uxr_dev.md` (under 40 lines: files, test counts, exact results, limitations, open risks) and commit it. Your final reply: files touched, test count, clock-offset accuracy achieved, tip SHA, done or blocked. Do not paste file contents. Do not declare the work accepted; an independent reviewer will check it.
