# OpticPS

**OpticPS: An Open-Source Framework for Probabilistic Shaping in Optical Communications**

OpticPS stands for Optical Probabilistic Shaping. The name is not limited to PAM4: PAM8, PAM16 and coherent systems are possible future extensions.

This release compares **Uniform**, **Fixed-shaped** and **Adaptive-shaped** PAM4 on intensity-modulation/direct-detection optical links, with waveform packages for the Keysight M8199B.

> **Status: simulation only.** No Southampton measurements have been imported. M8199B playback has not been verified. The M8199B CSV header, range and import command are confirmed against the M8100 Programming Guide; the 512-sample multiple, the memory maximum and AC coupling are not found in it and remain from the project owner's notes. See `docs/HARDWARE_COMPATIBILITY.md`.

## Key result so far

Under a fixed drive swing, the natural constraint on an unamplified Mach-Zehnder link, the optimal symmetric PAM4 is **outer-heavy** (Wiegart et al., JLT 2021). The requested PS70 and PS80 distributions are inner-heavy, and are predicted to perform **worse than Uniform**. They are generated as requested. The Adaptive file and a benchmark `PAM4_Fixed_Outer70.csv` carry the outer-heavy alternative so the experiment can tell the two apart.

## Scientific features

- PAM2/4/8/16, Gray labelling, Maxwell-Boltzmann and arbitrary distributions
- Exact, reversible CCDM by enumerative ranking; finite-block rate loss
- NRZ and RRC periodic pulse shaping, with data-independent common scaling
- IM/DD link: sine-law MZM, fiber loss, chromatic dispersion with optional slope, thermal and shot noise, ADC
- Selectable fiber model (1.1): `none` (v1.0 defaults), ITU-T G.652.D representative and bound presets, custom; each value tagged with its provenance
- Receiver: sync, polarity and phase recovery, calibration, FFE (LS, LMS), MD and MAP detection, GMI estimation
- Adaptive selection from training data with a leakage guard
- Protocol A (equal baud), Protocol B (equal net rate), fairness audit, run-level bootstrap

**Not included:** FEC, so nothing here is PAS and rates are achievable bounds, not coded throughput.

## Installation

Python 3.11 or newer, macOS or Linux, with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/theerayutbo/OpticPS.git
cd OpticPS
uv sync
uv run pytest
```

## Quick start

```bash
uv run opticps generate    # M8199B waveforms, references, manifest, validation
uv run opticps validate    # re-check the exported packages
uv run opticps simulate    # simulated comparison, several minutes
uv run opticps report      # PDF and Markdown report
uv run opticps slides      # PowerPoint and PDF slides
uv run opticps demo        # generate, validate, simulate, report and slides (not fiber-validate)
uv run opticps fiber-validate   # G.652.D fiber model validation, results/fiber_validation/; run separately
```

## Keysight workflow

Waveforms are in `output/keysight_m8199b/<profile>/waveforms/`, with settings in `experiment_manifest.csv`.

| Profile | AWG | Baud | sps | Symbols | Samples |
|---|---|---|---|---|---|
| A_initial_8GBd | 224 GSa/s | 8 GBaud | 28 | 32,768 | 917,504 |
| B_highspeed_56GBd | 224 GSa/s | 56 GBaud | 4 | 65,536 | 262,144 |

These are starting points, not proof the optical link supports either speed. OpticPS never connects to an instrument and never enables an output. Operating steps are in `output/README_SOUTHAMPTON.md`.

## Fiber model (1.1)

`LinkConfig(fiber=...)` takes a `FiberParameters` that supplies wavelength, attenuation, dispersion and dispersion slope. Without it, the link uses the v1.0 defaults (0.2 dB/km, 17 ps/(nm km), 1550 nm, no slope) and gives numerically identical results. A fiber field that disagrees with the fiber description raises an error; a slope left unset is the v1.0 second-order model, while 0.0 is a true zero slope. Presets (`opticps.optical_channel.fiber.select_fiber`): `none`, `g652d-representative`, `g652d-limit-low`, `g652d-limit-high`, `custom`. Nothing is applied unless chosen, and the Southampton fiber type and length are unconfirmed.

The presets follow Rec. ITU-T G.652 (08/2024), edition 10.0. Limits are for cable and exclude short cables such as jumpers; Table I.1 typical link values are not limits; the representative dispersion curve is a fit through the Table I.1 values. Measurements override presets through `apply_measurements`, which marks each measured value laboratory-measured (the slope has its own tag), and capture metadata has an optional `fiber` field. PMD is listed and not simulated. Results are analytical or simulated; none is experimentally validated. See `reports/Fiber_Model_Validation_Report.pdf`.

## Southampton data import

The receiver is a Keysight Infiniium UXR Series oscilloscope at 256 GSa/s (exact model suffix unconfirmed). Save each acquisition as an HDF5, CSV or BIN export, plus a JSON sidecar (`data/templates/capture_template.json`) with `"data_source": "measured"`, under `data/private/southampton/`, which git ignores.

A scope record is not one exact period, so measured captures never go through `opticps analyze`; it refuses them. (`opticps ingest`, `opticps analyze` and `opticps compare` handle only the older periodic `received_time_s,received_voltage_v` captures with `data_source` simulated.) Use `ingest-uxr` for each capture and `compare-uxr` for the paired comparison and report:

```bash
uv run opticps ingest-uxr --input data/private/southampton/run1.h5 --sidecar data/private/southampton/run1.json --profile A_initial_8GBd --results results/uxr
uv run opticps compare-uxr --results results/uxr
```

`compare-uxr` groups captures by condition (profile, attenuation setting, fiber length) and gives one verdict per waveform pair and condition. Set-points must match for a verdict; launch power, OMA and extinction ratio are reported, not gated; received power gates only beyond `--power-tolerance-db` (default 0.5).

`ingest-uxr` keeps a leakage registry (default `data/private/uxr_registry.json` under the repository root; the path used is printed, and `--registry` overrides it). Use one registry for the whole campaign. It refuses a capture whose bytes or samples were already used as the other split or under another capture id; a re-export with different bytes cannot be detected. See `docs/SOUTHAMPTON_UXR_LAB_PROTOCOL.md`. The importers are tested on synthetic files only.

## Reports and slides

`reports/OpticPS_Research_Report.pdf`, `slides/OpticPS_Research_Presentation.pptx`, and a PDF of the slides. All are built from `results/synthetic/demo_results.json`. When `results/fiber_validation/fiber_results.json` exists they include a fiber model section and slide. `reports/Fiber_Model_Validation_Report.pdf` and `.md` come from `uv run opticps fiber-validate`.

## Repository structure

```
src/opticps/   package: modulation, shaping, distribution_matching, transmitter,
               optical_channel, receiver, optimization, measurement, instruments,
               statistics, reporting, visualization, cli
configs/       M8199B profiles and demo settings
output/        waveform packages and the Southampton guide
results/       simulated results and figures
reports/ slides/
docs/          hardware status, clean-room, licences, engineering log
tests/         unit, integration and scientific validation tests
```

## Reproducibility

Seeds, configuration hashes and checksums are saved with each output. Dependencies are locked in `uv.lock`. `docs/engineering_log/` records decisions, failures and findings for resuming work or writing a paper.

## License and clean-room method

MIT, copyright Theerayut Boonkird. Algorithms were written independently from published methods (`docs/ALGORITHM_PROVENANCE.md`). The background repositories were not read or used. Dependencies were license-scanned (`docs/DEPENDENCY_AUDIT.md`). This is a description of process, not legal certification, and human legal review has not been done (`docs/CLEAN_ROOM_DECLARATION.md`).

## Research limitations

- Simulation with generic parameters, not the Southampton link
- No FEC; no measured data
- M8199B 512-sample and memory rules not in the Programming Guide; playback unverified; UXR model suffix unconfirmed and no real export seen
- Driver compression, AC coupling and baseline wander are not modelled
- Fiber: single polarization, no PMD, no Kerr effect; G.652.D values are standard limits or representative models, not measurements
- Conclusions from one channel do not generalize
