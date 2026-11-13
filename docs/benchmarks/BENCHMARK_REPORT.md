# External benchmark report (gate E4)

This report closes the external-benchmark workstream (gates E0 to E3) with what was attempted,
what was obtained, what failed and what is blocked. Every number below is a value recorded in a
committed file; the evidence matrix `docs/benchmarks/EVIDENCE_MATRIX.yaml` (23 rows, one per point)
carries the same numbers with status, evidence label and evidence paths, and
`tests/test_benchmark_e4.py` rebuilds its Wiegart and Ran rows from the code. Commands to
regenerate everything are in `docs/benchmarks/REPRODUCE.md`.

## Summary of results

* **TERIPHIC 2 km holdout: FAILED.** It was scored once under the frozen criterion: 0 of 123
  scenarios passed, best ratio psi 1.5013 (pass needs psi <= 1), binding metric M1 level spacing
  0.02723 against a limit of 0.01814 (`docs/benchmarks/teriphic_e2/two_km_result.json`, outcome FAIL,
  verdict FAILED, claim none).
* **Gate E2 is PARTIAL** (`docs/benchmarks/E2_CLOSING_RECORD.md`): pre-registration and power study
  done, 2 km FAILED, H1 (the B2B-calibrated small-signal surrogate transfers) refuted at 2 km, the
  E2c law-model calibration ended `FIT_INVALID` (acceptance check AC4, one basin).
* **TERIPHIC 10 km is `UNSPENT` and unread.** It is reserved once for a differently designed
  hypothesis that does not exist yet; no result exists for it.
* **TERIPHIC BER and SER stay `REFERENCE_SEQUENCE_MISSING`.** A B2B-only search found a periodic
  pattern of 8128 symbols (`INFERRED_REFERENCE`, mismatch proxy 0.013839); it is an inference, not
  a source-stated sequence, and no BER was computed.
* **Wiegart rows W1 to W3 agree with the numbers the paper states in its running text within
  0.01 dB** (deviations +0.0028, -0.0003 and -0.0032 dB), and the qualitative ordering W5 is
  reproduced. This is agreement of our information-theoretic AWGN computation with the paper's own
  analytic result. It is not experimental validation, and it says nothing about the paper's
  measured experiments (W9) or about any hardware.
* **Wiegart W4a, W4b are NOT COMPARABLE** (the paper states no decoder metric for P_X(0) = 0.4);
  W6, W7 (figure values, licence unverified), W8 and W9 are NOT COMPARABLE as well.
* **Ran headline results (R1, R2) are NOT COMPARABLE with `MODEL GAP: CHIRP`.** The Ran BER points
  (R3) are `BLOCKED`: the Source Data spreadsheet was not obtained. R4 is an analytical chirp-free
  null frequency with no published counterpart (NOT COMPARABLE).
* Nothing here is a validation on any laboratory hardware, and none of it is a validation on
  Southampton hardware: no such measurement was used. The OpticPS adaptive shaping policy is not
  validated by any of these sources (uniform PAM4 data, analytic AWGN checks).

## What was attempted and obtained

| Gate | Attempted | Obtained |
|---|---|---|
| E0 | Source register, missing-parameter matrix, rights review | `SOURCE_REGISTER.md`, `MISSING_PARAMETERS.md`; one licence conflict recorded (Ran article CC BY-NC-ND against MIT) |
| E1 | Verify the format of the TERIPHIC captures | B2B format verified by byte-level evidence; 2 km and 10 km hashed only |
| E2 | B2B calibration, frozen 2 km and 10 km prediction, one scoring | 2 km scored once: FAILED; E2c recalibration FIT_INVALID; closed PARTIAL |
| E3 | Wiegart analytic comparison, Ran subcases | W1 to W3 and W5 agree with text numbers; every other row NOT COMPARABLE or BLOCKED |
| E4 | Evidence matrix, report, reproduction, figures | this report and its files |

### TERIPHIC

Calibration partition: the back-to-back capture only (E2 part a; fit window the first 8,388,608
samples, spread and evaluation windows later in the same file, `teriphic_e2/b2b_model.yaml`). The
holdout was the 2 km capture, scored once. After that FAIL, E2c used the B2B and the 2 km fit windows
for a joint law-model calibration, so the 2 km capture is calibration data from E2c on and is no
longer a holdout; that calibration ended `FIT_INVALID` and its result stands as a record, not as a
fitted model (`teriphic_e2c/law_model_v2.yaml`, `a2_endpoint_decomposition.md`). Fibre type,
wavelength, dispersion, launch power and chirp are `UNKNOWN`; the 123 scenarios assume G.652.D
(`ASSUMED_G652D`) and zero chirp as explicit model scenarios, not facts about the fibre. The publisher
questions sent by the owner are unanswered (`E2_CLOSING_RECORD.md`); nothing was back-filled.

Verified format of the B2B file: Keysight BIN v10 container, one waveform, float32 little-endian,
40,959,993 samples at a header time increment of 1/2.048 THz, scale `normalized` (not volts, not
power). The record's "256 Gbaud" sampling remains an unconfirmed reading (256 GSa/s).

### Wiegart 2021

Our computation: fixed-peak PAM4, symmetric PMF family, AWGN, rates by symbol-metric and bit-metric
decoding (Gray label), peak SNR 9 / sigma^2. Two independent rate routes agree to below 5e-5 dB on
the compared gains. The tolerance of 0.01 dB was written in the same commit as the computed rows
(disclosed in `E3_WIEGART_RAN.md`). Our optima for P_X(0) are 0.3982 (SMD) and 0.3958 (BMD); the paper
prints 0.4 without a decoder metric, so no match is claimed. Locations refer to the numbering of
the arXiv author manuscript held locally; whether the journal numbering is identical was not checked.

### Ran 2025

Only the cited numeric facts were used: the wavelength (1271 nm), the measured dispersion
(-3.99 ps/(nm km)), the link lengths (5 km and 10 km) with their lane rates, and the FEC
thresholds. No chirp model was built because the cited facts do not give the chirp
parameter, bias, drive, rate definitions, BER definition or power (`e3_ran.CHIRP_MODEL_MISSING`).
The analytical chirp-free first nulls are 68.20 GHz (5 km) and 48.22 GHz (10 km); the real link is
chirped, so these are not a prediction of the experiment.

## Final table

| Source | Asset availability and verified format | Rights status | Implemented pipeline | Calibration partition | Holdout result | Limitations | Evidence paths |
|---|---|---|---|---|---|---|---|
| TERIPHIC | Three PD1 PAM4 files (B2B, 2 km, 10 km) downloaded with owner approval; MD5 equal to the record's for all three. B2B format verified (Keysight BIN v10, float32 little-endian, `normalized`); 2 km format not assessed separately; 10 km hashed only, no sample read | CC-BY-4.0, record level, verified in the Zenodo JSON; derived statistics redistributable with attribution; captures stay in ignored `data/external/` | Keysight BIN reader and statistics, B2B surrogate model, frozen criterion and holdout scorer, E2c law model, B2B pattern search | B2B only (E2 part a); E2c later calibrated on B2B and 2 km, `FIT_INVALID` | 2 km FAILED (0 of 123 scenarios, best psi 1.5013); E2 PARTIAL; 10 km UNSPENT and unread | Fibre type, wavelength, launch power, chirp UNKNOWN (MODEL GAP: CHIRP); no BER or SER (`REFERENCE_SEQUENCE_MISSING`); `normalized` scale only; publisher questions unanswered | `docs/benchmarks/SOURCE_REGISTER.md`, `docs/benchmarks/E2_CLOSING_RECORD.md`, `docs/benchmarks/teriphic_e2/two_km_result.json`, `docs/benchmarks/teriphic_e2c/law_model_v2.yaml`, `docs/benchmarks/EVIDENCE_MATRIX.yaml` |
| Wiegart 2021 | Author manuscript PDF held locally, ignored by git; no data file; numbers read from running text only | LICENSE/REUSE TERMS UNVERIFIED: no figure, digitised or re-plotted value, equation image or copied sentence in the repository | `src/opticps/benchmarks/e3_wiegart.py` with `published_points.py` and `comparison.py` | None: analytic check, no parameter fitted | W1 to W3 agree with text numbers within 0.01 dB; W5 ordering reproduced; W4a, W4b, W6 to W9 NOT COMPARABLE | Agreement with an analytic AWGN result, not experimental validation; Gray label is our reading; tolerance committed with the rows; manuscript numbering only | `docs/benchmarks/E3_WIEGART_RAN.md`, `src/opticps/benchmarks/e3_wiegart.py`, `configs/benchmarks/wiegart_2021_peak_pam4.yaml`, `docs/benchmarks/EVIDENCE_MATRIX.yaml` |
| Ran 2025 | Source Data spreadsheet not obtained and not downloaded; no file format verified; only cited facts used | Article CC BY-NC-ND 4.0, incompatible with MIT (bibliographic strings and cited numbers only); Source Data licence UNVERIFIED | `src/opticps/benchmarks/e3_ran.py`: analytical chirp-free small-signal response only | None | R1, R2 NOT COMPARABLE (MODEL GAP: CHIRP); R3 BLOCKED (Source Data not obtained); R4 analytical, no published counterpart | No chirp model; BER definition, gross or net rate, power and drive unknown; no measured point plotted | `docs/benchmarks/E3_WIEGART_RAN.md`, `src/opticps/benchmarks/e3_ran.py`, `configs/benchmarks/ran_2025_g652d.yaml`, `docs/benchmarks/EVIDENCE_MATRIX.yaml` |

## Status of every point

Generated from the matrix (`python scripts/build_evidence_matrix.py --table`); a test compares this
table with the matrix.

| Row | Status | Evidence label |
|---|---|---|
| T-B2B-M1 | CALIBRATION | EXTERNAL RAW CAPTURE |
| T-B2B-M2 | CALIBRATION | EXTERNAL RAW CAPTURE |
| T-B2B-M3 | CALIBRATION | EXTERNAL RAW CAPTURE |
| T-B2B-M4 | CALIBRATION | EXTERNAL RAW CAPTURE |
| T-E2C-A2 | FIT_INVALID | EXTERNAL RAW CAPTURE |
| T-2KM | FAILED | SIMULATED vs EXTERNAL RAW CAPTURE |
| T-10KM | UNSPENT | UNKNOWN |
| T-BER | REFERENCE_SEQUENCE_MISSING | UNKNOWN |
| T-PRBS-B2B | INFERRED_REFERENCE | EXTERNAL RAW CAPTURE |
| W1 | MATCH | SIMULATED |
| W2 | MATCH | SIMULATED |
| W3 | MATCH | SIMULATED |
| W4a | NOT COMPARABLE | SIMULATED |
| W4b | NOT COMPARABLE | SIMULATED |
| W5 | MATCH | SIMULATED |
| W6 | NOT COMPARABLE | UNKNOWN |
| W7 | NOT COMPARABLE | UNKNOWN |
| W8 | NOT COMPARABLE | UNKNOWN |
| W9 | NOT COMPARABLE | UNKNOWN |
| R1 | NOT COMPARABLE | UNKNOWN |
| R2 | NOT COMPARABLE | UNKNOWN |
| R3 | BLOCKED | UNKNOWN |
| R4 | NOT COMPARABLE | SIMULATED |

`CALIBRATION` is this report's own word for a training-partition number: it carries no pass or fail
claim. `UNSPENT` is the records' lowercase "unspent" (`E2_CLOSING_RECORD.md`) written as a status.
`FAILED`, `FIT_INVALID`, `INFERRED_REFERENCE` and `REFERENCE_SEQUENCE_MISSING` are the records'
exact words; `MATCH`, `NOT COMPARABLE`, `BLOCKED` come from the comparison layer.

### Evidence label rule

Only the five legend words `PUBLISHED DATA`, `EXTERNAL RAW CAPTURE`, `SIMULATED`, `DIGITIZED`,
`UNKNOWN` are used, in one rule for the matrix, the figure legends and the table below:

* a statistic computed from captures only carries `EXTERNAL RAW CAPTURE`;
* a statistic that compares a simulated scenario with a capture names both, written
  `SIMULATED vs EXTERNAL RAW CAPTURE` (the only combined label; the matrix and the figure checks
  accept it and nothing else beyond the five words).

Applied to TERIPHIC: row `T-2KM` and the "best of 123 scenarios" series are the psi of the best of
123 simulated fibre scenarios scored against the 2 km capture, so they carry
`SIMULATED vs EXTERNAL RAW CAPTURE`. The "B2B copy" series is the B2B capture's evaluation window
scored against the 2 km capture with the same four metrics and limits (the comparator of
`docs/benchmarks/FIT_HOLDOUT_PLAN.md` line 937, "The B2B evaluation window, normalised as above,
scored against the holdout"; recorded as `b2b_copy` in `docs/benchmarks/teriphic_e2/two_km_result.json`).
No simulation is involved, so it carries `EXTERNAL RAW CAPTURE`. The B2B misfit rows, the E2c row and
the pattern-search row are statistics of captures only and carry `EXTERNAL RAW CAPTURE`. The first
version of the figure labelled both series `SIMULATED`; that was wrong for the copy and is
corrected here.

### Code version, output hash and uncertainty

Every matrix row carries three further fields.

* `output_hash`: SHA-256 of a canonical serialisation of the row's reported values (id, our and
  source value, unit, deviation, tolerance, status, labels; floats to 6 significant digits), so it
  does not depend on the platform or on file bytes. The validator recomputes it, so a hand-edited
  value is refused.
* `code_version`: for the TERIPHIC rows computed in earlier gates, the commit that the source record
  itself states (`head_commit` of `two_km_result.json`, of `law_model_v2.yaml`, of
  `b2b_sequence_candidate.yaml`); a commit cannot name the file that holds it, so no commit of this
  gate is written. The B2B misfit rows (the pre-registration states a model hash, no commit), `T-10KM`
  and `T-BER` carry `null` with the reason. For the Wiegart and Ran rows, which the E3 modules
  compute, it is the package version `opticps 1.2.0`;
  `python scripts/build_evidence_matrix.py --check` proves the matrix equals the code at whichever
  commit holds it.
* `uncertainty`: a bound only where a committed record states one. The four B2B rows carry the
  record's `b2b_window_spread` of the same metric (a spread over B2B windows, not a confidence
  interval). All other rows carry `null` and the reason (the record states none, or no value
  exists). No uncertainty was estimated for this report.

## Figures

`scripts/make_benchmark_figures.py` regenerates all five; every plotted series has one legend label
following the rule above, written as `<LABEL> | detail`. No series is `DIGITIZED`. Each PNG holds
a SHA-256 of its specification (series labels, evidence labels, title and the plotted numbers to
5 significant digits) in the text chunk `OpticPS-figure-spec-sha256`; a test compares it with the
code, so a relabelled series or a changed number fails without any pixel comparison.

| File (`docs/benchmarks/figures/`) | Content | Series |
|---|---|---|
| `wiegart_gain_check.png` | W1 to W3: our gains and the numbers in the paper's running text, single points | SIMULATED, PUBLISHED DATA |
| `wiegart_required_psnr.png` | our own required peak SNR against target rate, uniform and best symmetric PMF | SIMULATED |
| `ran_chirp_free_response.png` | analytical chirp-free response at 5 and 10 km, no measured point | SIMULATED |
| `teriphic_two_km_ratios.png` | 2 km metrics over their limits, from the committed scoring record; outcome FAILED | SIMULATED vs EXTERNAL RAW CAPTURE (best of 123 scenarios), EXTERNAL RAW CAPTURE (B2B copy) |
| `teriphic_fibre_sensitivity.png` | psi of all 123 assumed fibre scenarios against assumed dispersion, from the committed scoring record and scenario list; titled PARTIAL/FAILED, 0 of 123 passed, not a fit | SIMULATED vs EXTERNAL RAW CAPTURE (six scenario families), EXTERNAL RAW CAPTURE (B2B copy) |

Rights decision for the TERIPHIC figure: `SOURCE_REGISTER.md` records CC-BY-4.0 for the dataset at
record level (verified in the Zenodo JSON and DataCite) and records public redistribution of derived
data as allowed with attribution; its caution about vendoring applies to captures. The figure is
drawn only from the committed 2 km scoring record and its scenario list (statistics derived from the
captures, no samples) and carries the attribution line, so it is committed; the same holds for the
fibre-sensitivity figure. No capture is opened by the figure
script and the 10 km capture is not plotted. The Wiegart figures hold only our own curves and
numbers from the running text; the Ran figure holds only the analytical curve.

## Not done, blocked

* TERIPHIC 10 km: not run, not read. `UNSPENT`.
* Measured BER, exact SER: `REFERENCE_SEQUENCE_MISSING`.
* Ran Source Data comparison (R3): `BLOCKED: SOURCE DATA XLSX NOT OBTAINED (LICENCE/REUSE TERMS
  UNVERIFIED)`.
* Chirped-modulator model: `MODEL GAP: CHIRP`.
* Wiegart figure values (W6, W7): not compared, licence unverified; nothing digitised.
* Measured-versus-predicted overlay: not made, because no aligned prediction passed (0 of 123
  scenarios within the criterion at 2 km) and the 10 km capture is unspent and must not be read.
* B2B, 2 km and 10 km capture-metric figure: not made, because the 10 km capture is unspent and
  must not be read; the 2 km and B2B numbers appear in `teriphic_two_km_ratios.png`.
* The fibre-sensitivity figure from the roadmap exists as `teriphic_fibre_sensitivity.png`, built
  from the committed record only; it is a view of a failed holdout, not a fit.
* Uncertainty: `null` for every row but the four B2B rows, because no committed record states one.
