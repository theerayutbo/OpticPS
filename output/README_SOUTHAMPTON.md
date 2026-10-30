# OpticPS laboratory guide for Southampton

Status: every file here is synthetic. Playback on an M8199B has **not** been verified. Nothing here is a measurement. Please tell the project owner once a real instrument test succeeds, so this line can change.

## Read this first

Under a fixed peak-to-peak drive, which is how these files are scaled, simulations and Wiegart et al. (arXiv:2005.12428) both predict that PS70 and PS80 will perform **worse** than Uniform. They put more symbols on the inner levels. The optimum under this constraint puts more on the outer levels. `PAM4_Adaptive` and `waveforms/benchmark/PAM4_Fixed_Outer70.csv` do that. Please measure the benchmark too: without it the comparison cannot separate "shaping does not help" from "this distribution was the wrong one".

## What is in the package

```
output/keysight_m8199b/
  adaptive_selection.json          how the Adaptive distribution was chosen
  A_initial_8GBd/  B_highspeed_56GBd/
    waveforms/PAM4_Uniform.csv     PAM4_Fixed_PS70.csv
    waveforms/PAM4_Fixed_PS80.csv  PAM4_Adaptive.csv
    waveforms/benchmark/PAM4_Fixed_Outer70.csv
    references/<waveform>/         symbols, information bits, metadata
    experiment_manifest.csv        one row per waveform
    validation_results.csv         checks run on these files
    checksums.sha256
```

| Profile | AWG rate | Baud | Samples/symbol | Symbols | Samples | Loop duration | Loop rate |
|---|---|---|---|---|---|---|---|
| A_initial_8GBd | 224 GSa/s | 8 GBaud | 28 | 32,768 | 917,504 | 4.096 µs | 244.14 kHz |
| B_highspeed_56GBd | 224 GSa/s | 56 GBaud | 4 | 65,536 | 262,144 | 1.170 µs | 854.49 kHz |

These are starting points, not proof that the optical link supports either speed. Start with Profile A.

| Waveform | P(-3) | P(-1) | P(+1) | P(+3) | Bits/symbol carried |
|---|---|---|---|---|---|
| Uniform | 0.25 | 0.25 | 0.25 | 0.25 | 2.000 |
| Fixed PS70 | 0.15 | 0.35 | 0.35 | 0.15 | 1.867 |
| Fixed PS80 | 0.10 | 0.40 | 0.40 | 0.10 | 1.706 |
| Adaptive | 0.375 | 0.125 | 0.125 | 0.375 | 1.797 |
| Outer70 (benchmark) | 0.35 | 0.15 | 0.15 | 0.35 | 1.867 |

The Adaptive distribution is **simulation-optimized**: chosen on simulated AWGN training data at the point where Uniform reaches 1.0 bit/symbol. It has not been adapted to your link.

Frame layout, the same for all waveforms: symbols 0 to 511 preamble (m-sequence at the outer levels, DC balanced), 512 to 1023 common training, then payload in 1024-symbol blocks. Shaped payloads use CCDM with a composition rounded to integers; the realised probabilities are in the manifest. **No FEC is implemented**, and this is not PAS.

## Before you start: confirm these

Nothing below can be assumed from this repository. Write the answers in the experiment log.

- M8199B options, module identifier and channel count.
- Whether the output really is AC-coupled and 50 Ω, and the maximum output voltage. The project owner's notes say AC-coupled, nominally 50 Ω. The Programming Guide's `:OUTPut:COUPling` entry lists M8198A and M8199A only (p97), so this is not confirmed for the M8199B. Read the voltage limits from the unit before loading: `:SOURce:VOLTage:AMPLitude? 'identifier', MAX` and `MIN` (M8100 Programming Guide p57; the guide's example identifier is `'M2.DataOut'`, other pages write `'M1.DataOut1'`, so check which one your unit accepts). OpticPS sends no SCPI.
- Modulator V_pi, maximum RF input, bandwidth, connector, and bias method.
- Whether the amplifier, if any, can damage the modulator at any AWG setting.
- CSV format, against the M8100 Series Programming Guide (M8100-91B50, March 2026), now read. Confirmed there: the mandatory first row naming the column (`DataOut1`), normalized values from -1.0 to +1.0 (scientific notation accepted), and `:TRACe:IMPort 'identifier', <segment_id>, <file_name>, <file_format>` with formats BIN8, TXT or CSV and segment id 1 only (pp129-133). Not found in the guide and still from the project owner's notes: the 512-sample multiple and the 1,048,576-sample maximum. Both are kept as safe rules.
- Receiver: a Keysight Infiniium UXR Series oscilloscope at 256 GSa/s, exact model suffix unconfirmed. Record what the instrument reports, its bandwidth setting and the export format. See `docs/SOUTHAMPTON_UXR_LAB_PROTOCOL.md`.

## Protocol

**1. Module and clock.** Use M8070B (version 9.5 or later per the Getting Started Guide) with the M8199B driver package and the M8008A clock module. Wear a grounded wrist strap: Keysight warns that ESD on the module or chassis can disturb channel timing alignment, which toggling the sample rate can clear.

**2. File selection and import.** Copy the CSV onto the Keysight host, then in M8070B or by SCPI:

```
:TRAC:IMP 'M2.DataOut1', 1, "C:\OpticPS\PAM4_Uniform.csv", CSV
```

`M2` is only an example: use your module identifier. The path must exist on the Keysight host. Set the sample rate and segment size first, and check them afterwards. Files start with the header `DataOut1`; to use the second output, regenerate with `data_out: DataOut2`. Verify `sha256` of the file on the host against `checksums.sha256`.

**3. Sample rate.** Read back 224 GSa/s. The waveform cannot tell you if this is wrong: a wrong rate simply gives a wrong baud.

**4. Electrical connection and termination.** Output off. Data outputs are 1.0 mm connectors: use matching, undamaged connectors and a torque wrench as Keysight specifies. Disable an unused output in M8070B or terminate it with 50 Ω. The output is differential: decide explicitly whether you use one side or both, and record it.

**5. Electrical check.** Connect to a suitable scope or attenuator, **not** the modulator. Start at a low amplitude. CSV values are normalized: ±1 maps to whatever amplitude the instrument is set to, and this does not imply any voltage. Confirm four levels, the preamble pattern, and the loop rate from the table. Check that the waveform seam shows no glitch. Record Vpp and RMS.

**6. Modulator, bias, power.** Never assume the modulator accepts the AWG maximum output. Check limits, then connect with output off, raise amplitude gradually. Bias through a separate DC port or bias tee: AC coupling blocks the mean, so nothing in the CSV sets the bias. Find quadrature and record the bias voltage. Keep the **same AWG amplitude for all waveforms**: this is the condition being compared. Measure launch power, OMA and extinction ratio for each waveform. Do not rescale waveforms to equalize electrical RMS: they differ by design. Values are in the `waveform_rms` column of each manifest (Profile B: Uniform 0.750, PS70 0.620, PS80 0.544, Adaptive 0.882, Outer70 0.856, in normalized units).

**AC coupling and low-frequency content.** CCDM waveforms have zero mean over the frame; Uniform has a small nonzero mean, listed in the `waveform_mean` column. The loop rate (244 kHz or 854 kHz) falls within the band of many coupling networks, so watch for baseline wander, and note any bias tee or amplifier corner frequency.

**7. Back-to-back.** Sweep a VOA, about 8 points around where Uniform is near 1 bit/symbol. Each point is a condition (profile, attenuation setting, fiber length) with its own sidecar `attenuation_dB`, and `compare-uxr` gives one verdict per condition: run ids need only be unique within a condition, so the same `r1` to `r5` can be used at every point. At each point, capture all waveforms, at least 5 paired runs each, and measure received optical power for every capture (it is reported with its spread; see step 12).

**8. Fiber.** Repeat at each fiber length. Keep launch power fixed. Record the fiber type, length and loss. At 56 GBaud, simulated chromatic dispersion degrades performance noticeably within a few kilometres; see the report.

**9. Capture.** Capture at least 3 full frames, at no less than twice the baud rate, ideally more. Take at least 5 repeated captures per condition, each a new acquisition (paired comparisons below 5 runs are refused, and one acquisition ingested twice is refused), in interleaved order (U, PS70, PS80, A, O, U, ...) so drift does not bias one waveform. Capture a **separate** set for training, and mark it. Save the scope's own export (HDF5 preferred; CSV and BIN also work; see `docs/SOUTHAMPTON_UXR_LAB_PROTOCOL.md`), plus a JSON sidecar. Copy `data/templates/capture_template.json`. Fields that must be filled in (the file is rejected otherwise) are the receiver model, capture sample rate, symbol rate, receiver bandwidth, fiber length, attenuation, timestamp, and `related_transmit_experiment_id` from the manifest. The key `optical_received_power_dBm` must be present, but `null` means not measured. Use `"split": "training"` or `"test"`, and `"data_source": "measured"`. Leave an optional value null if you did not measure it. Do not estimate it. Scope captures go through `opticps ingest-uxr` and `opticps compare-uxr`; `opticps analyze` refuses measured captures. Store data under `data/private/southampton/`, which git ignores.

**10. Synchronization.** Automatic: the software finds the preamble, polarity and sampling phase using the reference files.

**11. Analysis.**

Run `ingest-uxr` once per capture (training and test), with one shared registry, then compare:

```bash
uv run opticps ingest-uxr --input data/private/southampton/run1.h5 --sidecar data/private/southampton/run1.json --profile A_initial_8GBd --results results/uxr
uv run opticps compare-uxr --results results/uxr
uv run opticps uxr-report --results results/uxr
```

The comparison groups captures by condition (profile, `attenuation_dB`, `fiber_length_km`), pairs waveforms by run id inside a condition, and prints one verdict per pair and condition.

Capture at least 3 full frames: a clock fitted through only 2 preambles cannot show that samples were dropped between them, and the result is then marked unreliable. This yields SER, Gray label BER, estimated R_SMD and R_BMD, and SNR per capture, in `results/uxr/` (`capture_metrics.csv`, `analysis_summary.json`, `uxr_report.md`). Post-matcher BER is diagnostic only: one symbol error ruins a 1024-symbol block, and there is no FEC.

**12. Comparison and report.** Two modes:

- Equal baud: the same symbol rate for all. Shaped waveforms carry fewer bits, so report that plainly.
- Equal net rate: compare Outer70 with PS70 directly (same rate by construction). To match Uniform, lower its baud: `match_uniform_rate` in `src/opticps/measurement/compare.py` gives the sample rate.

Fairness is printed by `opticps compare-uxr` and written to `uxr_report.md`. Set-points are what you dial in and must match between the captures of a pair for a verdict: symbol rate, AWG sample rate, electrical amplitude, fiber length, attenuation setting, receiver bandwidth and capture sample rate. Launch power, OMA and extinction ratio are measured outcomes that differ between waveforms at a fixed drive by design: they are reported and never block a verdict. Received power is reported with its spread and blocks a verdict, with a warning, only when the spread within a condition exceeds a tolerance (0.5 dB; change it with `--power-tolerance-db`). A set-point that is not recorded in some or all captures gives a verdict with an explicit "not recorded: X" caveat, so fill it in or state it in the paper. A verdict is also withheld when data sources mix. Captures flagged `reference_mismatch_suspected` stay counted and listed in the report, and the verdict of any pair that uses one is withheld. Do not claim a throughput gain from lower BER or lower symbol energy.

`opticps uxr-report --results results/uxr` turns the `ingest-uxr` and `compare-uxr` outputs into a PDF and Markdown receiver-analysis report in `reports/` (waveform excerpts, recovered symbol distribution, eye diagram, BER and SER with intervals, signal quality, acquisition settings, comparison with the simulation, and the set-point audit). Run it after `compare-uxr`. Its header states the data source of the captures; a report with any simulated capture is marked `MOCK/SIMULATED CAPTURES: NOT LABORATORY MEASUREMENTS`. Physical measurement uncertainty is printed as not recorded unless the sidecar's `calibration` field gives it. The automatic research report and slides (`opticps report`) still draw on simulated results only. Send `results/uxr/` to the project owner, and keep raw captures private until the owners approve release.

## Regenerate everything

```bash
git clone https://github.com/theerayutbo/OpticPS.git && cd OpticPS
uv sync
uv run opticps generate     # waveforms and validation
uv run opticps validate
```

Edit `configs/m8199b_profiles.yaml` to change sample rate, baud, symbols, pulse (NRZ or RRC), or output. The generator refuses rates outside 200 to 256 GSa/s, sample counts that are not a multiple of 512, and more than 1,048,576 samples. Hashes reproduce for the same config and seed on the same software versions.

## Experiment log

Copy `data/templates/experiment_log_template.md` for each session.
