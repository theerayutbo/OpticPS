# Missing-data matrix, dependency map and importer audit (Stage 3A, gate E0)

Legend: K = known (provenance in `SOURCE_REGISTER.md` and the configs), U = unknown (null with
provenance UNKNOWN), I = inferred by us (not stated by the source), n/a = not applicable.
Read status of each external fact is in `SOURCE_REGISTER.md` (`verified` = raw record text read, `summary` = fetch-tool summary); this matrix gives only K, U and I. Nothing was read from a raw capture.

## 1. Missing-data matrix

| Parameter | 1 TERIPHIC PD (PD1, PAM4) | 2 TERIPHIC EML | 3 Ran 2025 | 4 Wiegart 2021 |
|---|---|---|---|---|
| Raw file format (dtype, endianness, header, scaling) | **U** (`.bin`, nothing documented) | **U** | n/a (Source Data XLSX schema U, file not fetched) | n/a |
| Transmitted reference sequence | **U** (none documented) | **U** | U (publication: BER only) | n/a (analytic) |
| Wavelength | **U** (O-band only) | U (O-band) | K 1271 nm | n/a |
| Fibre type | **U** | U | K "G652.D" (spelling as printed) | n/a |
| Fibre length | K 0, 2, 10 km (file names) | K 0, 2, 10 km | K 5 km, 10 km | n/a |
| Fibre dispersion, loss | U | U | K dispersion -3.99 ps/(nm km); loss U | n/a |
| Baud | K 50 GBd | K 50 GBd | U per lane in the text read (rates only) | n/a |
| Sample rate and unit | I 256 GSa/s (record says "256 Gbaud sample rate") | I (same wording) | n/a | n/a |
| Modulation order | K PAM4 (title, names) | K PAM4 | K PAM-4 | K 4-PAM |
| Vertical calibration (volts, mV, dBm, normalised) | **U** | **U** | U | n/a |
| Oscilloscope model, bandwidth, ENOB | U | U (detector "more than 70 GHz 3-dB bandwidth", scope U) | U | n/a |
| Transmitter model | U (COTS laser + COTS MZM, models unnamed; Vpi, bias, swing U) | n/a (EML: DFB + EAM + SOA, drive U) | K silicon MZM with controlled chirp; chirp parameters U | n/a |
| Detector | K TERIPHIC InP PD1, Subassembly 1; responsivity, bandwidth U | K one commercial PD, "more than 70 GHz 3-dB bandwidth" | U | n/a |
| Launch and received optical power | U | U | U per figure | n/a |
| Receiver DSP / filtering of shipped samples | U | partly K (50 GHz digital LPF applied; whether shipped samples are filtered U) | K 155-tap FFE (RLS), optional MLSD | n/a |
| BER definition, FEC threshold | n/a | n/a | thresholds K (2.4e-2, 3.8e-3); BER definition U | n/a |
| Gross vs net rate | n/a | n/a | **U** | n/a |
| Acquisition time, repeat structure | U (one file per length) | K repeated runs `v1..v3` at different time indices | n/a | n/a |
| Distribution family, noise definition, AIR definition | n/a | n/a | n/a | U (not read in E0) |
| Source-data licence | n/a | n/a | **UNVERIFIED** | n/a |
| Article licence | none identified | none identified | CC BY-NC-ND 4.0 | UNVERIFIED |
| Local file present, hash verified | files present and hashed by the orchestrator 2026-10-31 (values in SOURCE_REGISTER.md); not verified by repository code until E1 runs `verify_local_asset`; unread | no | n/a | arXiv PDF in repo, hash recorded |

## 2. Dependency map: what can and cannot be reproduced

| Capability | Needs | Status for Source 1 | Status for other sources |
|---|---|---|---|
| Read the file as an array | verified raw format | **BLOCKED: FORMAT_UNKNOWN** until E1 evidence; the Keysight parser must not be used on a guess | Source 3: XLSX schema unknown, file not fetched |
| Descriptive waveform statistics (histograms, quantiles, PSD, eye structure) | format, then an assumed-normalised scale | possible after format is verified, labelled `normalized`; absolute volts/dBm not possible (calibration U) | n/a |
| Timing and clock recovery at 5.12 samples/symbol | sample rate and baud confirmed | nominal 256 GSa/s / 50 GBd = 5.12 only if the INFERRED unit is confirmed; clock recovery uses measured timing, never rounded | n/a |
| Measured BER, exact SER | transmitted reference sequence | **NOT POSSIBLE**: `REFERENCE_SEQUENCE_MISSING`; decision-error proxies only, with different names | Source 3: only the published BER values can be analysed, as publication data |
| B2B characterisation | format, scale convention | possible only as a lumped TX+RX fit; transmitter and receiver responses not separable | n/a |
| 2 km and 10 km prediction | dispersion at the laser wavelength, fibre type, loss | wavelength and fibre type U: only explicit scenarios (`ASSUMED_G652D` at an assumed wavelength) with sensitivity, never ground truth; possibly `UNIDENTIFIABLE_PARAMETER` | n/a |
| G.652.D at 1271 nm preset | wavelength-aware dispersion model | n/a | Source 3: wavelength and dispersion K; OpticPS default is 1550 nm and must not be reused |
| Ran headline rates (4x256, 4x200) | chirp model, drive, power, DSP, rate definition | n/a | **MODEL_GAP: CHIRP**; gross/net U; headline rates not reproducible; subcases only |
| Ran published points | Source Data XLSX with usable licence | n/a | file not fetched, licence UNVERIFIED: analysis of numbers as publication data only after rights review |
| Wiegart analytic curves | the paper's equations (E3) | n/a | possible from independent derivation; comparison with digitised figures needs the label `FIGURE-DIGITIZED / APPROXIMATE` and a rights review before publishing |
| Public release of derived data | licence | TERIPHIC derived statistics allowed under CC-BY with attribution; captures themselves stay out of Git | Ran data and Wiegart figures: not until resolved |
| Validation of the adaptive shaping policy | shaped transmission | **NOT POSSIBLE** from uniform PAM4 data | not provided by any source |

What cannot be reproduced from any of the four sources in E0: a measured BER from raw samples, an
absolute calibration, the Ran headline rates, and any statement about Southampton hardware.

## 3. Importer audit (existing UXR importers vs unknown-format external captures)

Read: `src/opticps/measurement/uxr_import.py` (`read_scope_file`, `read_bin`, `read_hdf5`,
`read_csv`), `uxr_ingest.py::ingest_uxr`, `capture.py::validate_metadata`. No code was changed.

Finding: **an unknown-format external `.bin` is not mis-accepted by the Keysight parser, with one
stated residual.**

1. `read_scope_file` chooses the parser from the file **suffix** only (`.h5`, `.hdf5`, `.csv`,
   `.bin`). A TERIPHIC `.bin` therefore reaches `read_bin`. The suffix itself is no evidence of
   format, as the brief says.
2. `read_bin` then demands, from the bytes: cookie `AG`, version `10`, the file-size field equal to
   the actual length, at least one waveform, a 140-byte waveform header, a supported waveform type,
   exactly one buffer, a 12-byte data header, buffer type 1 (float32), width 4, and buffer size
   equal to 4 x points. Arbitrary samples, zeros, a
   truncated header and a right cookie with a wrong size all raise `UxrImportError`.
   `tests/test_benchmark_provenance.py::test_teriphic_named_fake_bin_is_rejected_by_the_keysight_parser`
   proves this for seven independently made files that only carry a TERIPHIC file name.
3. Residual: the parser would accept a file that truly is a Keysight BIN with those fields, whatever
   its name. Whether the TERIPHIC files are Keysight exports is **not stated by the record**; that
   is why E1 must test byte-level hypotheses on B2B and must not reuse `read_bin` by assumption.
   A file size of 163,840,136 = 163,840,000 + 136 bytes (record metadata only) is a hypothesis for
   a fixed header, not evidence: size alone cannot tell it from a Keysight single-waveform file
   (164 header bytes plus float32 samples also gives an integer sample count).
   Smaller residual (review finding 13; **closed in E1a, 2026-11-01**: `read_bin` now refuses any
   bytes after the last waveform, test `test_bin_trailing_bytes_after_the_last_waveform_are_rejected`;
   the paragraph describes the state before the fix): `read_bin` checks the size field
   against the file length but does not check that the last waveform ends exactly at the end of
   the file, so trailing bytes after a valid structure pass. The E0 reviewer reproduced it: a
   valid header declaring 100 samples followed by 400,000 further bytes of samples is accepted and
   returns the first 100. That contradicts the module's "ambiguous content raises" contract. Not
   changed in E0 or in its fix round (no existing module is touched). **E1 must block it, with a
   test, before any `.bin` path is used on a capture**; it is not reachable by a TERIPHIC file
   unless that file starts with the Keysight cookie `AG10`.
4. `ingest_uxr` additionally requires a sidecar passing `validate_metadata` and a
   `related_transmit_experiment_id` that exists in an OpticPS transmit manifest, so an external
   capture without both is refused even if a parser accepted its samples. The HDF5 reader needs a
   valid Keysight-style `/Waveforms` layout and the CSV reader a documented header or numeric table.
5. Not a defect but a limit: all UXR paths are `UNVERIFIED AGAINST REAL FILES` (VERIFICATION.md),
   and `read_bin`'s docstring says no real file has been tested. External captures need a separate
   `ExternalCapture` adapter (E1) with its own `FORMAT_UNKNOWN` failure.
