# Changelog

## Unreleased (v1.2.0 UXR)
Scope export import (HDF5, CSV, BIN, layouts from the UXR Programmer's Guide), a linear non-periodic capture analysis with preamble-based frame finding, symbol-clock estimation and decision-directed timing tracking across a frame, lost-frame accounting, `opticps ingest-uxr` and `opticps compare-uxr` (paired comparison, fairness audit, report), a content-hash leakage registry, `optical_received_power_dBm` may be null (not measured), and the Southampton UXR protocol. `analyze` refuses measured captures. Tested on synthetic files only; no real UXR export has been seen. Transmitter waveforms are unchanged.

## 1.1.0 (2026-10-30)
Selectable fiber model based on Rec. ITU-T G.652 (08/2024): `none`, G.652.D representative, dispersion-bound presets and custom, with value provenance. `LinkConfig` gains `dispersion_slope_ps_per_nm2_km` (third-order term, beta3) and `fiber`; without them the link is numerically identical to 1.0.0. The four fiber fields default to unset, an unset slope is the 1.0.0 second-order model, and a field that conflicts with `fiber` raises. Each fiber value, including the slope, has its own provenance tag. `cd_null_frequency_hz` returns infinity for zero dispersion or length. Optional `fiber` metadata in the capture schema. New `opticps fiber-validate`, `configs/fiber_validation.yaml`, `results/fiber_validation/`, `reports/Fiber_Model_Validation_Report`, and a fiber section and slide in the report and deck. Version metadata in waveform packages was not regenerated; waveform CSV files are unchanged. No measured data; nothing experimentally validated.

Known low-severity issues in 1.1.0: capture `fiber` length accepts NaN; wavelength has no provenance tag; the no-fiber `LinkConfig` path does not range-check raw values; mock captures omit fiber metadata; a fiber preset with no length silently means 0 km.

## 1.0.0 (2026-10-30)
First release. M8199B waveform packages for two profiles, exact CCDM, IM/DD link simulation, receiver DSP, capture ingest, fair comparison tools, simulated demonstration, report and slides. No measured data. M8199B playback not verified.
