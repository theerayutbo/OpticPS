# OpticPS

Research framework comparing **Uniform**, **Fixed-shaped** and **Adaptive-shaped** PAM4 on intensity-modulation/direct-detection optical links, with waveform packages for the Keysight M8199B.

> **Status: simulation only.** No Southampton measurements have been imported. M8199B playback has not been verified. The M8199B file rules come from the project owner's notes of the M8100 Programming Guide, and have not been checked against the guide itself. See `docs/HARDWARE_COMPATIBILITY.md`.

## Key result so far

Under a fixed drive swing, the natural constraint on an unamplified Mach-Zehnder link, the optimal symmetric PAM4 is **outer-heavy** (Wiegart et al., JLT 2021). The requested PS70 and PS80 distributions are inner-heavy, and are predicted to perform **worse than Uniform**. They are generated as requested. The Adaptive file and a benchmark `PAM4_Fixed_Outer70.csv` carry the outer-heavy alternative so the experiment can tell the two apart.

## Scientific features

- PAM2/4/8/16, Gray labelling, Maxwell-Boltzmann and arbitrary distributions
- Exact, reversible CCDM by enumerative ranking; finite-block rate loss
- NRZ and RRC periodic pulse shaping, with data-independent common scaling
- IM/DD link: sine-law MZM, fiber loss, chromatic dispersion, thermal and shot noise, ADC
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
uv run opticps demo        # all of the above
```

## Keysight workflow

Waveforms are in `output/keysight_m8199b/<profile>/waveforms/`, with settings in `experiment_manifest.csv`.

| Profile | AWG | Baud | sps | Symbols | Samples |
|---|---|---|---|---|---|
| A_initial_8GBd | 224 GSa/s | 8 GBaud | 28 | 32,768 | 917,504 |
| B_highspeed_56GBd | 224 GSa/s | 56 GBaud | 4 | 65,536 | 262,144 |

These are starting points, not proof the optical link supports either speed. OpticPS never connects to an instrument and never enables an output. Operating steps are in `output/README_SOUTHAMPTON.md`.

## Southampton data import

Save captures as `received_time_s,received_voltage_v` plus a JSON sidecar (`data/templates/capture_template.json`) under `data/private/southampton/`, which git ignores.

```bash
uv run opticps ingest  --input data/private/southampton/
uv run opticps analyze --input data/private/southampton/ --profile A_initial_8GBd
uv run opticps compare
```

The receiver model is unknown, so the format is receiver-agnostic.

## Reports and slides

`reports/OpticPS_Research_Report.pdf`, `slides/OpticPS_Research_Presentation.pptx`, and a PDF of the slides. All are built from `results/synthetic/demo_results.json`.

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
- M8199B rules not independently verified; playback unverified; receiver unknown
- Driver compression, AC coupling and baseline wander are not modelled
- Conclusions from one channel do not generalize
