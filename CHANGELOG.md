# Changelog

## Unreleased (v1.2 UXR)
Scope export import (HDF5, CSV, BIN, layouts from the UXR Programmer's Guide), a linear non-periodic capture analysis with preamble-based frame finding, symbol-clock estimation and decision-directed timing tracking across a frame, lost-frame accounting, `opticps ingest-uxr` and `opticps compare-uxr` (paired comparison, fairness audit, report), a content-hash leakage registry, `optical_received_power_dBm` may be null (not measured), and the Southampton UXR protocol. `analyze` refuses measured captures. Tested on synthetic files only; no real UXR export has been seen. Transmitter waveforms are unchanged.

## 1.0.0 (2026-10-30)
First release. M8199B waveform packages for two profiles, exact CCDM, IM/DD link simulation, receiver DSP, capture ingest, fair comparison tools, simulated demonstration, report and slides. No measured data. M8199B playback not verified.
