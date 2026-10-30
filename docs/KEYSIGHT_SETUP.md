# Keysight setup

The operator steps are in `output/README_SOUTHAMPTON.md`, protocol steps 1 to 6. Verification status is in `docs/HARDWARE_COMPATIBILITY.md`.

To add a new profile, add an entry in `configs/m8199b_profiles.yaml`. The ratio of sample rate to baud must be an integer, and the sample count must be a multiple of 512.

| Check before loading | Where |
|---|---|
| Maximum voltage | Instrument data sheet and M8070B |
| Modulator input limit | Modulator data sheet |
| Waveform memory and segment granularity | Programming Guide |
| Sample rate | M8070B readback |

No SCPI is sent by OpticPS. Add a real driver only from official documentation for the confirmed model, and keep output enabling manual.
