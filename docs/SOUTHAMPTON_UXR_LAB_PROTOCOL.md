# Southampton UXR capture protocol

Status: the importers and the capture analysis were tested only on **synthetic** files written by the test suite. No real UXR export has been seen. Nothing here is a measurement.

## What is not known

- **Exact UXR model suffix: unconfirmed.** Record whatever the instrument reports. This repository assumes nothing about it.
- **The UXR Programmer's Guide (9018-07723) could not be read.** No SCPI is provided and none is sent by OpticPS. Use the instrument front panel or the vendor's own documentation for the steps below.
- The HDF5 field layout comes from Keysight's Infiniium "HDF5 Schema" help page. The CSV header layout and the BIN integer widths could not be confirmed.
- **Please send Theerayut one small real H5 export and one small real CSV export** (a few thousand samples is enough, from any signal) before the first real campaign. The importers will be checked against them. Until then treat any import as provisional.

## What the analysis needs from a capture

The AWG loops one frame, so a capture is several repeats of the same frame, usually starting and ending part-way through one. The analysis finds each full frame by its preamble, estimates the real symbol rate from the spacing of the preambles, and fits gain, offset and equalizer on the preamble and training symbols only.

- Capture at least **2 full frames**, so the clock can be estimated from frame spacing. With one full frame the clock is estimated from the preamble and training only and the result is marked low confidence.
- One frame lasts 4.096 us (Profile A, 8 GBaud, 32,768 symbols) or 1.170 us (Profile B, 56 GBaud, 65,536 symbols). Choose the record length to cover more than 2 frames plus a margin; the instrument limits are for you to read from its own data sheet.
- Record roughly 8 or more samples per symbol if the instrument allows, and never fewer than 2.
- The captured sample rate need not be a multiple of the baud rate, and the scope and AWG clocks need not agree. Both are handled.

## 1. Capture

1. Load one waveform on the M8199B and loop it (the OpticPS lab guide, `output/README_SOUTHAMPTON.md`, covers the transmitter side).
2. Set the scope, trigger and acquire a single record that spans more than 2 frames.
3. Keep every setting below identical across waveforms that you intend to compare.
4. Take several records per waveform (different runs). Do not average away the noise unless you record that you did.

## 2. Export

- **Preferred: HDF5 (.h5).** Use the All Data option. Record whether the save dialog wrote **integers or floats**: the importer scales integers with the file's own increment and offset, and treats floats as already in volts. Both rules are inferences that have not been verified; the importer records which one it used.
- CSV is accepted in two shapes only: a time column plus a voltage column, or a single voltage column with an `XInc` header row (or `--x-increment-s` on the command line). Do not export transmitter-style `DataOut` files; they are rejected.
- BIN is accepted only with `--accept-unverified-bin`, because the field widths are assumed. Prefer HDF5.
- Multi-segment (segmented memory) exports must have a segment selected; they are rejected otherwise.
- Only the Volt and Second units are accepted.

## 3. Acquisition settings to record

Write these in the experiment log and in the sidecar notes. Leave a value null if you did not measure it; do not estimate it.

- Scope model, serial number and firmware, the channel, and the date.
- Sample rate and record length as set on the instrument.
- Vertical scale, offset and input termination; whether the input saturated at any point.
- Bandwidth limit or filter in use, and any averaging or interpolation.
- Trigger source and level, and whether the acquisition was single-shot.
- Whether the file holds integers or floats.
- Receiver, photodiode and amplifier models; optical received power, fiber length and attenuation.

## 4. Sidecar

Copy `data/templates/capture_template.json`. The schema is the existing one in `src/opticps/measurement/capture.py`. Fill in:

- `related_transmit_experiment_id` from the transmitter `experiment_manifest.csv`. This is how the capture is matched to the exact transmitted symbols.
- `split`: `training` or `test`. Never use the same capture, or the same file, in both. The tool refuses.
- `symbol_probabilities` from the manifest, `symbol_rate_Bd` (the nominal rate you set on the AWG), and `data_source: measured`.
- `capture_sample_rate_Sa_per_s`: what you set. It is only cross-checked against the file; the value measured from the file is always used, and a disagreement above 1% stops the import.

## 5. Import and analyze

```
opticps ingest-uxr --input data/private/southampton/run1.h5 --channel 1 \
  --sidecar data/private/southampton/run1.json --profile A_initial_8GBd \
  --results results/uxr
```

Add `--accept-unverified-bin` for BIN and `--x-increment-s VALUE` for a one-column CSV. If the sidecar has no `split`, pass `--split`. The reference frames are read from `output/keysight_m8199b` (override with `--output`).

The command prints the clock offset in ppm and its confidence, the number of preambles found and complete frames, and the error counts. It writes `<capture_id>_analysis.json`, and for test captures also `<capture_id>_frames.csv` and `<capture_id>_eye.npz`.

## 6. Reading the result

- Zero errors are reported as, for example, "0 errors in 12288 symbols, 95% upper bound 0.000244". That is a bound on the error rate, not a measured rate of zero.
- The intervals assume independent errors. Frames repeat the same payload, so symbols pooled across frames are not independent data; the capture-level bootstrap is shown when there are at least 2 frames.
- MI and GMI estimates are flagged unreliable when any level has fewer than 100 test symbols.
- Training captures are fitted but never scored as test.

## 7. Reports

Run `opticps analyze` over a folder of the NPZ or CSV captures in the older format for the paired comparison and fairness audit, and keep the `ingest-uxr` JSON files with the experiment log. A direct bridge from `ingest-uxr` results to the paired-comparison report is not yet implemented.

## Send back

`*_analysis.json`, `*_frames.csv`, the experiment log with the settings above, and the one small real H5 and CSV export requested at the top.
