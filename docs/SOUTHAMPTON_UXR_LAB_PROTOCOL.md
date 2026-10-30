# Southampton UXR capture protocol

Status: the importers and the capture analysis were tested only on **synthetic** files written by the test suite. No real UXR export has been seen. Nothing here is a measurement.

## What is known and what is not

- The receiver is a Keysight Infiniium **UXR Series** oscilloscope sampling at 256 GSa/s. **The exact model suffix is unconfirmed.** Record whatever the instrument reports (`*IDN?`, UXR Programmer's Guide p263). This repository states no bandwidth and no memory figure for it.
- The file layouts follow the UXR Programmer's Guide (page numbers below are the guide's). They are checked against that text and against synthetic files only. The CSV separator and key spelling in a real file, and the BIN layout on a real file, remain unverified.
- **Please send Theerayut one small real H5 export and one small real CSV export** (a few thousand samples is enough, from any signal) before the first real campaign. The importers will be checked against them. Until then treat any import as provisional.

## What the analysis needs from a capture

The AWG loops one frame, so a capture is several repeats of the same frame, usually starting and ending part-way through one. The analysis finds each full frame by its preamble, estimates the real symbol rate from the spacing of the preambles, follows the sampling instant across each frame with its own symbol decisions, and fits gain, offset and equalizer on the preamble and training symbols only.

- Capture at least **3 full frames**. The clock is fitted to the spacing of the preambles, and a line through only 2 points has no residual, so samples dropped or inserted between 2 preambles shift the clock by tens of ppm without any sign in the fit (2 symbols in a 32,768-symbol frame is 61 ppm). With 3 or more the residual exposes that. With 2 frames the tool also compares the fit with its own timing tracking inside the frame, and when they disagree by more than 10 ppm it clears the reliable flag, marks the clock low confidence and warns. With one full frame the clock rests on one preamble and is then refined by decision-directed tracking over the frame (medium confidence at best, with a stated standard error). That works only as well as the signal allows: the result carries a warning, and the reliable flag is cleared if tracking does not hold.
- One frame lasts 4.096 us (Profile A, 8 GBaud, 32,768 symbols) or 1.170 us (Profile B, 56 GBaud, 65,536 symbols). Choose the record length to cover more than 3 frames plus a margin; read the limits from the instrument.
- At 256 GSa/s Profile A gives 32 samples per symbol and **Profile B gives 4.57**. The analysis needs at least 2 samples per symbol; more is better. Do not expect 8 samples per symbol at 56 GBaud.
- The capture sample rate need not be a multiple of the baud rate, and the scope and AWG clocks need not agree. This was tested on synthetic captures with a non-integer samples-per-symbol ratio and clock offsets up to a few hundred ppm; nothing is claimed beyond that.

## 1. Capture

1. Load one waveform on the M8199B and loop it (the OpticPS lab guide, `output/README_SOUTHAMPTON.md`, covers the transmitter side).
2. Set the scope, trigger and acquire a single record that spans more than 3 frames.
3. Keep every setting below identical across waveforms that you intend to compare.
4. Take several records per waveform (different runs, each a new acquisition: the same file or samples under two run ids are refused; at least 5 per waveform for a paired comparison). Do not average away the noise unless you record that you did.

## 2. Export

- **Preferred: HDF5 (.h5).** The save command has two HDF5 formats (p598): `H5` saves **floats**, which are actual vertical values; `H5INt` saves **integers**, which need `value * Y increment + Y origin`. The importer follows exactly this and records the rule it used in `scaling_rule`. Record which one you chose.
- For a segmented acquisition choose what is saved with `:DISK:SEGMented` (p600) and, if the file is segmented, pass `--segment N` (0-based). A file reporting `NumSegments` 0 is read as one non-segmented capture (the guide's own HDF5 example, p2090, shows 0).
- The waveform type is read from `WaveformType` (help page) or `Waveform Type` (the guide's example, p2090), as a name or as the guide's integer code (1 Normal, 3 Average; the BIN table, p2094). A type other than NORMAL or AVERAGE is refused unless you pass `--allow-waveform-type TYPE`. `--max-samples N` raises or lowers the HDF5 limit on values read (default 500,000,000), and `NumPoints` must be a whole number. A `SavedInterpFactor` other than 0 or 1 raises a warning, because the meaning of the time increment under interpolation is unverified.
- CSV: a header `Type` of normal, raw or average is accepted; interpolate and versus (an XY plot) are refused unless allowed with `--allow-waveform-type`. A header `Segments` above 1 is always refused (save one segment, or use HDF5 with `--segment`), and a header `Points` that differs from the number of data rows is an error. The guide lists the header fields (Revision, Type, Start, Points, Count or Segments, XDispRange, XDispOrg, XInc, XOrg, XUnits, YDispRange, YDispOrg, YInc, YOrg, YUnits, Frame, Date, Time, Max bandwidth, Min bandwidth, Time Tags, Data) with the data after `Data` (pp2091-2092). The importer reads that header when present, and also accepts a time column plus a voltage column, or a single voltage column with `XInc` in the header (or `--x-increment-s`). Units in column titles such as `(mV)` or `(ns)` are scaled; an unknown unit is refused. Files with more than two data columns (multi-source) are refused. Do not export transmitter-style `DataOut` files; they are rejected.
- BIN: the channel comes from the waveform label (`Channel N`). A file with several waveforms needs exactly one labelled with the requested `--channel`, and repeated labels (segments) are refused; a single waveform whose label names another channel is refused instead of being relabelled, and an unlabelled one is read as the requested channel with a note. Negative point or buffer sizes are refused. Read strictly against the documented layout (pp2093-2098): cookie `AG`, version `10`, signed 4-byte integers, 4-byte floats, 8-byte doubles, header sizes 12, 140 and 12 bytes, Volt and Second units, waveform type Normal or Average, float buffers. Any deviation is refused. No real BIN file has been tested.
- HDF5 files are treated as untrusted input. For every dataset that is read (the waveform, `Frame/TheFrame` and `FileType`), soft and external links, external storage, virtual datasets and a null dataspace are refused, and metadata datasets are limited to 1,024 values. The waveform shape is checked against `NumPoints x NumSegments` and a maximum before any data is read.
- Only the Volt and Second units are accepted.

## 3. Acquisition settings to record

Write these in the experiment log and in the sidecar notes. Leave a value null if you did not measure it; do not estimate it.

- Scope model, serial number and firmware, the channel, and the date.
- Sample rate and record length as set on the instrument.
- Vertical scale, offset and input termination; whether the input saturated at any point.
- Bandwidth limit or filter in use, and any averaging or interpolation.
- Trigger source and level, and whether the acquisition was single-shot.
- Whether the file holds integers (`H5INt`) or floats (`H5`).
- Receiver, photodiode and amplifier models; optical received power, fiber length and attenuation.

## 4. Sidecar

Copy `data/templates/capture_template.json`. The schema is the existing one in `src/opticps/measurement/capture.py`, and the template's `_help` block lists what must be filled in. These cannot be null: `related_transmit_experiment_id`, `receiver_instrument_model`, `capture_timestamp`, `capture_sample_rate_Sa_per_s`, `symbol_rate_Bd`, `receiver_bandwidth_Hz`, `fiber_length_km`, `attenuation_dB`, `symbol_probabilities`, `split`, `data_source` and `units`. `optical_received_power_dBm` must be present, and `null` means not measured (the fairness audit then shows "not recorded"). Fill in:

- `related_transmit_experiment_id` from the transmitter `experiment_manifest.csv`. This is how the capture is matched to the exact transmitted symbols.
- `split`: `training` or `test`.
- `symbol_probabilities` from the manifest and `symbol_rate_Bd` (the nominal rate you set on the AWG). Both are **checked against the manifest**, and a mismatch stops the import. The `realised_probability_*` columns are rounded to six places and can sum to 1.000001, which the validator refuses; use the `probability_*` columns or renormalise (a difference up to 1e-5 is accepted).
- `data_source: measured`.
- `capture_sample_rate_Sa_per_s`: what you set. It is only cross-checked against the file; the value measured from the file is always used, and a disagreement above 1% stops the import.

## 5. Import and analyze

```
opticps ingest-uxr --input data/private/southampton/run1.h5 --channel 1 \
  --sidecar data/private/southampton/run1.json --profile A_initial_8GBd \
  --results results/uxr --registry data/private/uxr_registry.json
```

The `capture_id` becomes part of the output file names, so it must be 1 to 128 letters, digits, dots, underscores or hyphens, starting with a letter or digit; anything else is refused before anything is written.

Add `--x-increment-s VALUE` for a one-column CSV, `--segment N` for a segmented HDF5 file, and `--allow-waveform-type TYPE` for another waveform type. If the sidecar has no `split`, pass `--split`. The reference frames are read from `output/keysight_m8199b` (override with `--output`). Errors print as `error: ...` with exit code 1.

**Never run scope captures through `opticps analyze`.** That path assumes one exact period, and it refuses measured captures. Use `ingest-uxr` for each capture and `compare-uxr` for the result.

The command prints the clock offset in ppm and its confidence, the frames analysed against the frames expected and lost, and the error counts. It writes `<capture_id>_analysis.json`, and for test captures also `<capture_id>_frames.csv` and `<capture_id>_eye.npz`.

### What the leakage guard does and does not do

Training and test must be different acquisitions. The tool keeps a registry of the SHA-256 of every ingested file and of its decoded samples, with its split and run id. The default is `data/private/uxr_registry.json` under the repository root (found by walking up from the current directory to `pyproject.toml`), so it does not depend on where you run the command; `--registry` overrides it, and the path used is printed and recorded in `<capture_id>_analysis.json`. It refuses a capture whose id or content is already registered under the other split, and also the same content under a second capture id, because that would count one acquisition as several runs. A registry that is not valid, or has the wrong shape, stops the ingest with an error. Entries are written only after an ingest has succeeded.

It guarantees only this: the same bytes, the same decoded samples, or the same capture id are never used as both training and test, and one acquisition is never counted as two captures, **in runs that share the same registry file**. It cannot see runs that use a different registry, the same acquisition exported again in another format or at another precision, or a re-acquisition of the same waveform. Use one registry for the whole campaign, keep it with the data, and treat the guard as a safety net for mistakes, not a proof of independence.

## 6. Reading the result

- Zero errors are reported as, for example, "0 errors in 12288 symbols, 95% upper bound 0.000244". That is a bound on the error rate, not a measured rate of zero. No BER of 0 is ever written.
- Frames repeat the same payload. Pooled symbols are therefore not independent data: the report states how many distinct payload symbols the frames repeat and gives a bound counting each distinct symbol once, and level counts for MI and GMI are per frame, not frames times symbols.
- A frame whose preamble cannot be found is **lost, not dropped**. The output gives `frames_expected`, `frames_analyzed` and `frames_lost`, a warning, and an error range that states the exclusion with a worst case counting every lost symbol as an error. The reliable flag is false when frames are lost.
- Irregular frame spacing (a gap or dropped samples) is reported. The spacing fit is then not used, the clock comes from the strongest frame (low confidence), lost frames cannot be counted, and the reliable flag is false.
- MI and GMI estimates are flagged unreliable when any level has fewer than 100 distinct test symbols, when frames are lost, or when timing tracking does not hold.
- Two disagreeing clock estimates (frame spacing against timing tracking inside the frame, more than 10 ppm apart) clear the reliable flag for 1 or 2 frames, mark the clock low confidence and name both values in the warning. With 3 or more regularly spaced preambles the spacing fit has a residual that would reveal dropped samples, so it stands: a large tracker residual or disagreement is then only a note and the flag stays true.
- Reference check, from the known training block and never from SNR: a payload minimum-distance error rate far above what the equalised training block predicts (more than 0.10 above its 99% upper bound), or a training block itself decided near chance, gives a `reference_mismatch_suspected` warning (wrong reference, or symbols dropped after the head). The capture is not deleted: it stays counted and listed as flagged in `compare-uxr`, but any pair that uses a flagged capture has its verdict withheld, with the capture named. Why the training limit exists: within one profile every reference shares one training block, so a wrong reference leaves the training block good and is caught by the excess test; the limit (training SER 0.6 or more, 0.8 of the random-guess rate) covers a corrupted or unrelated capture at very low SNR. A training SER of about 0.53 to 0.60 is a remaining blind window of that limit, far below the operating region.
- Training captures are fitted but never scored: no value derived from the payload (error rates, SNR, rates, histogram, eye) is reported for them.

## 7. Comparison and report

After ingesting all test captures into one results folder:

```
opticps compare-uxr --results results/uxr
```

This reads the capture-level results, runs the fairness audit, and compares waveforms in pairs on R_BMD with a bootstrap interval, using the same minimum number of paired runs (5) and the same verdict wording as the simulated comparison. Captures are grouped by condition (profile, `attenuation_dB` rounded to 0.1 dB, `fiber_length_km` rounded to 0.001 km; the resolution is recorded in the summary and report, and a waveform alone in a condition is listed as such) and waveforms are paired by run id inside a condition, so a sweep gives one verdict per point and the same run ids may repeat at every point. Captures whose rate estimate is unreliable are excluded and listed. Result files without a sidecar are not compared; they are counted in a warning. It refuses results where one file hash or decoded-sample hash appears under two captures (one acquisition counted as several runs) or in both training and test; as with the registry, a re-export with different bytes cannot be detected. Set-points (symbol rate, AWG and capture sample rates, electrical amplitude, fiber length, attenuation, receiver bandwidth) must match inside a pair, otherwise the verdict is withheld with the reason in the report. Launch power, OMA and extinction ratio differ between waveforms at a fixed drive by design: they are reported and never gate. Received power is reported with its spread and gates only beyond `--power-tolerance-db` (default 0.5), with a warning. A set-point not recorded in all or some captures gives a verdict with a "not recorded: X" caveat. A verdict is also withheld when data sources mix (measured and simulated). It writes `capture_metrics.csv`, `analysis_summary.json` and `uxr_report.md` into the results folder, and `opticps compare --results results/uxr` prints the same audit and comparisons.

## 8. Manual SCPI reference (no code; OpticPS sends nothing)

Every command below is from the UXR Programmer's Guide; pages are the guide's. Run them yourself from a terminal or the instrument's remote interface, after checking each against the guide for your firmware.

| Purpose | Command | Page |
|---|---|---|
| Identify the unit; record model and serial | `*IDN?` | 263 |
| Read or set the analog sample rate | `:ACQuire:SRATe:ANALog?` and `:ACQuire:SRATe:ANALog AUTO`, `MAX` or a rate | 359 |
| Set the memory depth | `:ACQuire:POINts:ANALog AUTO`, `MAX` or a points value | 345 |
| One acquisition at the next trigger | `:SINGle` | 316 |
| Acquire named channels, then stop | `:DIGitize CHANnel1` | 302 |
| Choose which segments are saved | `:DISK:SEGMented ALL` or `CURRent` | 600 |
| Save a channel | `:DISK:SAVE:WAVeform CHANnel1,"<path>\name",H5` (or `H5INt`, `CSV`, `BIN`; for CSV a final `,ON` adds the header) | 598 |
| Select the source for a preamble | `:WAVeform:SOURce CHANnel1` | 1666 |
| Number of points | `:WAVeform:POINts?` | 1655 |
| Read the preamble | `:WAVeform:PREamble?` | 1656 |

The preamble is a comma-separated list: format, type, points, count, X increment, X origin, X reference, Y increment, Y origin, Y reference, coupling, X display range, X display origin, Y display range, Y display origin, date, time, frame model and serial (`MODEL#:SERIAL#`), acquisition mode, completion, X units, Y units, max and min bandwidth limit, and optionally a segment count (pp1656-1658). Save the preamble text with the experiment log: the X increment is the value the importer uses, so it is a useful cross-check against the file. The save command writes on the oscilloscope's disk; copy the file from there. `:WAVeform:VIEW` (p1669) decides how much data is saved (p598 note).

## Send back

`*_analysis.json`, `*_frames.csv`, `uxr_report.md`, the registry file, the experiment log with the settings above and the preamble text, and the one small real H5 and CSV export requested at the top.
