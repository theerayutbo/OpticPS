# Changelog

## 1.1.0 (2026-10-30)
Selectable fiber model based on Rec. ITU-T G.652 (08/2024): `none`, G.652.D representative, dispersion-bound presets and custom, with value provenance. `LinkConfig` gains `dispersion_slope_ps_per_nm2_km` (third-order term, beta3) and `fiber`; without them the link is numerically identical to 1.0.0. `cd_null_frequency_hz` returns infinity for zero dispersion or length. Optional `fiber` metadata in the capture schema. New `opticps fiber-validate`, `configs/fiber_validation.yaml`, `results/fiber_validation/`, `reports/Fiber_Model_Validation_Report`, and a fiber section and slide in the report and deck. Version metadata in waveform packages was not regenerated; waveform CSV files are unchanged. No measured data; nothing experimentally validated.

## 1.0.0 (2026-10-30)
First release. M8199B waveform packages for two profiles, exact CCDM, IM/DD link simulation, receiver DSP, capture ingest, fair comparison tools, simulated demonstration, report and slides. No measured data. M8199B playback not verified.
