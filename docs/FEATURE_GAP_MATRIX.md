# Feature gap matrix (Gate 0, roadmap v2 section D)

Baseline: `a2eb969` on `main`, work branch `v1.3-mpam`, package version 1.2.0. Every status below comes from reading this repository only. Nothing was changed to produce it. Statuses: EXISTS, PARTIAL, MISSING, BLOCKED (needs data or hardware not available). All existing evidence is simulated or mock; no laboratory capture has been seen.

## Stage 1: adaptive M-PAM core

Rows changed by C5 (frame, export, validator, profiles) carry `(C5)`; the other rows are the Gate 0 statement and were updated by the slice that closed them only where marked in `docs/ROADMAP_STATUS.md`.

### 1.1 Generalisation

| Feature | Status | Evidence and gap |
|---|---|---|
| Generalise modulation, shaping, rates, adaptive, transmitter, receiver, measurement, CLI, reporting | PARTIAL | modulation and MB are generic; everything else is bound to 4 levels (site table below) |
| PAM levels, Gray labels, bit mapping for M = 2, 4, 8, 16 | EXISTS (C5) | `modulation/pam.py` `SUPPORTED_ORDERS`, `pam_levels`, `gray_labels`, `label_bits`, `indices_to_bits`, `bits_to_indices` (all `order=4` default) and frozen `ModulationSpec`; `tests/test_mpam_frame_rx.py` |
| Uniform PMF | EXISTS | `shaping/distributions.py:18` (4-tuple); `maxwell_boltzmann(0)` for any M |
| Symmetric MB family, positive and negative shaping parameters | PARTIAL | `shaping/distributions.py:45` takes `order` and any sign of lambda; no entropy-matched constructor; sign ambiguity only resolved for M=4 |
| Arbitrary validated PMFs | PARTIAL | `validate_probabilities(p, order)` is generic (`shaping/distributions.py`); `gaussian_rates` and CCDM accept a PMF but rates hard-code 4 symbols |
| General symmetric per-pair PMF optimisation; one-parameter vs higher-dimensional, local/global stated | MISSING | only `symmetric_pam4(p_outer)` (`shaping/distributions.py:52`) on a 1-D grid (`optimization/adaptive.py:100`); no optimality claim recorded |
| Gray labelling, symbol probabilities vs labelled bit priors | PARTIAL | Gray labels generic; bit-prior handling in `rates.py` is 2 bits (`:54`) |
| Stable serialisable versioned config, deterministic seeds | EXISTS for M-PAM (C5) | `configs/mpam_profiles.yaml`, `config_schema_version: 2`, loader `transmitter/mpam_config.py` refuses unknown versions and keys; PAM4 keeps `configs/m8199b_profiles.yaml` unversioned on purpose (`experiment_id` hashes the file text, so it is not edited; its SHA-256 is pinned in `tests/test_mpam_config.py`) |

### 1.2 Rates and CCDM

| Feature | Status | Evidence and gap |
|---|---|---|
| H(X), SMD/MI, BMD/GMI under non-uniform priors | PARTIAL | `optimization/rates.py:39` `gaussian_rates`, written for 4 symbols and 2 bits; Hermite-Gauss 120 nodes (`:20`) |
| Stable log-sum-exp arithmetic | MISSING | direct `np.exp` likelihood ratio (`rates.py:51`) |
| Defined channel likelihoods | EXISTS | per-symbol Gaussian, documented in the module docstring |
| Physical rate bounds enforced | PARTIAL | `bmd` silently clipped at 0 (`rates.py:58`), raw value not exposed |
| Monte Carlo / quadrature uncertainty quantified | MISSING | |
| Exact reversible CCDM | EXISTS | `distribution_matching/ccdm.py:104,131` encode/decode, exact integers; alphabet-generic code; M=8/16 round-trip and timing not tested |
| Composition rounding | PARTIAL | `quantize_composition` (`ccdm.py:35`) is largest-remainder with symmetric tie handling; may split mirrored pairs when M>=8 |
| Decoder invalid-block behaviour | EXISTS | `CompositionError` (`ccdm.py:27`), `RankOverflowError` (`:31`); imported in `tests/test_core.py:5` |
| Finite-block rate loss | EXISTS | `rate_loss` property (`ccdm.py:100`); `tests/test_core.py:110,119` (PAM4 PMFs only) |
| Bit-to-symbol round trip M=2/4/8/16 | EXISTS (C5) | direct uniform at M = 2, 8, 16 and CCDM at M = 8, 16 in `tests/test_mpam_frame_rx.py`; M = 4 in `tests/test_core.py` |
| CCDM time/memory per M and block size | MISSING | no measurement; no performance test (`perf_counter`/timing absent from tests) |
| `fixed_peak`, `fixed_average_optical_power`, `fixed_OMA`, `equal_realized_user_rate` as separate protocols | MISSING | no `optimization/constraints.py`; equal-rate search for PAM4 in `measurement/compare.py:112` |
| Feasibility and physical normalisation; `INFEASIBLE` with reasons | EXISTS (C4, C5) | `optimization/constraints.py` (`Feasibility`); `transmitter/mpam_config.py` `check_frame_fit` reports an M8199B-infeasible frame and `generate_mpam_all` writes nothing then; M8199B `Profile.check()` raises |
| Training-selected adaptive vs best-fixed predeclared before test; held-out test | PARTIAL | `optimization/adaptive.py` selects from training; `assert_disjoint`/`DataLeakageError` (`:27`) is id-only; best-fixed is the manual PS70/PS80/Outer70 set |
| Store all candidates, constraints, matcher overhead, seeds, objective values | PARTIAL | `Selection.to_dict` and `adaptive_selection.json` (the `candidates` list holds all 90 candidates); no constraints, no matcher overhead |
| Optimiser multistart logs, local/global statement | MISSING | |

### 1.3 Export and metrics

| Feature | Status | Evidence and gap |
|---|---|---|
| Export Uniform, Inner, Outer, Adaptive, best-fixed for M=4/8/16 with labels, manifests, references, checksums | PARTIAL (C5: M = 2, 8, 16 exist) | `transmitter/export.py` `generate_mpam_all` writes PAM{M}_Uniform, Fixed_Inner/Outer_H{centibits}, Adaptive, BestFixed (PAM2: Uniform only) with manifest schema v2, stream keys and an evidence label; PAM4 stays on `generate_all` with its 40 columns; no CLI command yet (C7). Gate 0 text follows: | M=4 only (`transmitter/export.py:32-33,159-167`); references and checksums exist (`:262`, `:309`); manifest `:35,305` PAM4 schema; no best-fixed entry |
| M8199B export offline only, CSV/sample/memory/granularity checks | EXISTS | `instruments/m8199b.py` Profile checks; the 512-sample granularity is confirmed by the data sheet p. 9; the 1,048,576-sample limit is verified only if "1024 kSa" means k = 1024 (the sheet does not say; exported files are safe either way); see `engineering_log/VERIFICATION.md` |
| Protocol A (matched baud, controlled settings) | EXISTS | profiles in `configs/m8199b_profiles.yaml`; equal-baud comparison in `measurement/compare.py` |
| Protocol B (matched realised user rate incl. overhead) | PARTIAL (C5) | profiles (112 Gb/s nominal, sps 2/4/6/8) and the rate-equalisation report with head overhead per order exist (`mpam_config.rate_equalisation`, `optimization/constraints.py`); `measurement/compare.py:112` is still the PAM4 search (C7) |
| Drive Vpp, RMS, optical power, OMA, ER, fibre, bandwidth recorded separately | PARTIAL | some in manifest and `optical_channel/link.py`; OMA and ER fields absent from manifest |

### Stage 1 tests and exit gate

| Feature | Status | Evidence and gap |
|---|---|---|
| Analytical / noiseless rate limiting cases, independent references | MISSING | planned `test_mpam_rates.py` |
| Symmetry, normalisation, invalid-PMF failures | PARTIAL | PAM4 in `tests/test_core.py` |
| Mapping/CCDM round trip M=2/4/8/16 | PARTIAL | see 1.2 |
| Finite-block loss tests | EXISTS | `tests/test_core.py:110,119` |
| Optimiser reproducibility, multistart logs | MISSING | |
| Leakage rejection | PARTIAL | `tests/test_export.py` imports `DataLeakageError`; ingest registry rejects content duplicates (`measurement/uxr_ingest.py:141-153`) |
| PAM4 legacy regression, no silent golden change | EXISTS | `tests/test_export.py` (reduced size) and `tests/test_pam4_anchor.py` (full size, added in C1) |
| CLI `generate -> validate -> simulate -> report` for 4/8/16 | PARTIAL | exists for M=4 (`cli/main.py`) |
| Monte Carlo convergence | MISSING | |
| Shaped BER vs information-bit BER | PARTIAL | label BER and info bits for PAM4 (`receiver/dsp.py:197`); not separated for M>4 |
| Documented negative/infeasible case | EXISTS (C4, C5) | PAM16 high PSNR (direct uniform wins), PS80 at M = 4 INFEASIBLE for equal rate, a 40000-symbol 8 GBd PAM16 frame INFEASIBLE (`tests/test_mpam_frame_rx.py`) |
| PAM6 follow-on | MISSING | out of Stage 1 scope by the roadmap |

### Stage 1: PAM4-bound sites (file:line, grep of this checkout)

| File | Lines | What is fixed to PAM4 |
|---|---|---|
| `optimization/rates.py` | 5-6 docstring, 22 `_UNIPOLAR = arange(4)`, 27 `3.0 /` in sigma, 41 `validate_probabilities(p, 4)`, 46 `label_bits(4)`, 54 `range(2)` bits, 63 `np.full(4,...)`, 78 symmetric PAM4 search |
| `optimization/adaptive.py` | 1 docstring, 46-52 `range(4)` per-level fit, 66-68 `integers(0, 4)`/`pam_levels(4)`, 75 `p_outer`, 100-119 one-parameter grid, 133 design rate |
| `shaping/distributions.py` | 18-21 `UNIFORM/PS70/PS80/OUTER70` 4-tuples, 52-63 `symmetric_pam4`, `lambda_of_symmetric_pam4` (`/ 8.0`) |
| `modulation/pam.py` | generalised in C5: `ModulationSpec`, all functions take `order` |
| `transmitter/frame.py` | generalised in C5: preamble on {0, M - 1}, per-order training, `m * length` bits, `Frame.order`; the payload RNG name hash is kept (PAM4 names unchanged) |
| `transmitter/export.py` | PAM4 path unchanged (names, `MANIFEST_COLUMNS`, 40 columns; `full_scale` and `synthesize` take the order, PAM4 values identical). C5 adds the M-PAM generator (`generate_mpam_all`, schema v2). Still PAM4-only: `waveform_definitions`, `generate_profile`, `generate_all` (`+/-3` metadata, `PAM4` modulation, `p_outer` use) |
| `receiver/dsp.py` | 54, 94, 112, 128, 171, 280 `pam_levels(4)`; 158-159 `range(4)`; 208 `label_bits(4)`; 228 `2 * sent.size` |
| `receiver/capture_dsp.py` | 265, 278, 399, 508 `pam_levels(4)`; 635, 650 `2 *` bits; 729, 844 `zeros/minlength 4`; 854 `range(4)` |
| `measurement/validate_export.py` | generalised in C5: both manifest schemas, levels, head, preamble and training per order, default-deny; `LEVELS` and `EXPECTED_TARGETS` remain as the PAM4 tables |
| `measurement/capture.py` | 155 `validate_probabilities(..., 4)`; 235 `indices_to_bits` default |
| `measurement/uxr_ingest.py` | 185 priors matched to manifest probabilities (no M assumption seen, but manifest schema is PAM4) |
| `measurement/demo.py` | 61-65 waveform names, 72-73 `np.full(4, 0.25)`/`minlength=4`, 78 `pam_levels(4)` and `/ 3.0`, 145-152 `arange(4)`, 168-172 `p_outer`, 203 `pam_levels(4)` |
| `measurement/compare.py` | 112 uniform PAM4 rate search, 271 `p_outer` |
| `measurement/fiber_validation.py` | 334 `waveforms(selected["p_outer"])` |
| `reporting/report.py` | 133 `selected_p_outer`, 218 and 250 PAM4 and `9 / sigma^2` text, 264 `p_outer` |
| `reporting/uxr_report.py` | 41-45 waveform table, 197 `arange(4)`, 201 "PAM4 level" |
| `reporting/slides.py` | 66, 78, 92, 191 PAM4 text and `p_outer` |
| `visualization/figures.py` | 114 `p_outer`, 190-198 `range(4)` and tick labels `-3..+3` |
| `cli/main.py` | 39 prints `P(+-3)` |

## Stage 2: IM/DD front end, receiver, uncertainty

### 2.1 Impairment models (off by default)

| Feature | Status | Evidence and gap |
|---|---|---|
| DAC quantisation | PARTIAL | `transmitter/export.py:125` `dac_quantize`, export only (code map unverified); not a channel impairment |
| ADC quantisation, clipping | MISSING | |
| Finite ENOB-equivalent noise | MISSING | the data sheet gives ENOB only as a figure (`engineering_log/LOG.md` 2026-10-31) |
| Finite analog Tx/Rx bandwidth | EXISTS | `optical_channel/link.py:75-76`, Butterworth magnitude `:151` |
| Sampling-clock offset | PARTIAL | estimated and bounded at receive (`receiver/capture_dsp.py:42,352`, 2000 ppm limit); not an injectable impairment |
| Jitter | MISSING | |
| Driver compression | MISSING | |
| AC coupling, baseline wander | MISSING | AC coupling is a data-sheet fact, not modelled |
| Laser RIN | MISSING | |
| MZM bias drift | MISSING | |
| MZM electrical / electro-optical frequency response | MISSING | only the static sine law (`link.py:137` `mzm_intensity`); a Tx bandwidth filter exists (`link.py:76`) |
| Chirp (only if independently specified) | MISSING | not specified, so not to be added without a source |
| Units and injection points documented | PARTIAL | `LinkConfig` fields in `link.py`; nothing for absent impairments |
| Sine-law MZM, extinction, insertion loss | EXISTS | `optical_channel/link.py` |
| Linear fibre dispersion and loss, G.652.D options | EXISTS | `optical_channel/fiber.py`, v1.1 gate in `engineering_log/LOG.md` |
| Custom Hollow-Core/NANF parameters | MISSING | no documented values in the repo; not to be invented |
| Kerr/SSFM (conditional backlog) | MISSING | documented as backlog only |

### 2.2 Receiver and soft metrics

| Feature | Status | Evidence and gap |
|---|---|---|
| Synchronisation, preamble | PARTIAL | `receiver/dsp.py:52`, `capture_dsp.py` (PAM4 only) |
| Timing recovery | EXISTS | `capture_dsp.py:271` `_locate_timing`, `:484` `_track_timing` (PAM4 only) |
| Non-integer samples per symbol, actual sample rate | EXISTS | `capture_dsp.py:166` `resample_linear`, spline timing; `dsp.py:24` `resample_to_symbols` |
| Level calibration | PARTIAL | `receiver/dsp.py:92`, 4 levels |
| Prior-aware MAP for all M | PARTIAL | `receiver/dsp.py:174` `detect_map`, M=4 |
| FFE, training-only fit | EXISTS | `receiver/dsp.py:102,119` |
| DFE with training-only fit and independent test scores | MISSING | |
| Soft bit LLR with correct priors | MISSING | `log_likelihoods` (`dsp.py:163`) is symbol-level |
| Equaliser stability / condition guards, no payload-label leakage | PARTIAL | tap-count and rate checks (`capture_dsp.py:700-704`); training uses preamble/head only; no condition-number guard |
| Per-level confusion matrix | MISSING | level histogram only (`capture_dsp.py:729,844`) |
| Eye / level separation | PARTIAL | eye traces (`capture_dsp.py:45,148`) |
| EVM | MISSING | |
| SER, uncoded label BER, AIR/BMD | EXISTS | `receiver/dsp.py:197,219` (M=4) |
| Uncertainty (binomial, bootstrap, paired) | EXISTS | `statistics/intervals.py:13,26,45` |
| Per-frame receiver diagnostics | PARTIAL | frame results in `capture_dsp.py` |
| MLSE / Volterra (only with demonstrated ISI case) | MISSING | none demonstrated |
| Short or noisy captures fail safely | PARTIAL | `ValueError` and `CaptureRejected` paths (`capture_dsp.py:283,352,693-738`; `measurement/capture.py:79`); not tested per M, no PASS/WARN/REJECT |
| Stage 2 gate: impairment-off equals previous outputs | MISSING | no impairments yet |
| Stage 2 gate: monotonic ensemble trends under noise/jitter sweeps | MISSING | |
| Stage 2 gate: all M orders run in DSP | MISSING | |

## Stage 3: campaign engine and UXR intake

| Feature | Status | Evidence and gap |
|---|---|---|
| Declarative `ExperimentPlan` / YAML schema | MISSING | |
| Randomised, seeded run orders, blocking, run sheet, checklist, manifest | MISSING | |
| Deduplicate impossible combinations; `INFEASIBLE` equipment combinations | PARTIAL | `Profile.check()` only |
| Sample-size estimate or `POWER ANALYSIS NOT POSSIBLE` | MISSING | |
| Five-paired-runs floor per condition | PARTIAL | the comparator enforces it (`measurement/compare.py:52,211`, `MIN_PAIRED_RUNS = 5`); no campaign engine plans or schedules the runs |
| HDF5/CSV/BIN UXR import, strict parsing, units | PARTIAL | `measurement/uxr_import.py`: HDF5 and CSV; no BIN; `UNVERIFIED AGAINST REAL FILES` |
| Actual sample rate and non-integer samples/symbol in intake | EXISTS | `capture_dsp.py:166`, see 2.2 |
| Immutable intake, SHA-256, source/condition id, timestamps, split, instrument identity | PARTIAL | `measurement/uxr_ingest.py:398-449` stores source and sample hashes; registry keeps split and `recorded_utc`; instrument identity and operator log not complete |
| Reject cross-split reuse of an acquisition | PARTIAL | content-hash and id rejection in the ingest registry (`uxr_ingest.py:141-153`); `adaptive.assert_disjoint` is id-only |
| Re-export detection | PARTIAL | same content under a new name is caught by `samples_sha256`; a re-export with different samples is not detected, and the limit is disclosed in the error text (`uxr_ingest.py:147-149`) |
| Frame/preamble timing, coverage and count validation | EXISTS | `capture_dsp.py` frame gates |
| Capture quality `PASS`/`WARN`/`REJECT` with reasons | PARTIAL | rejection with reasons (`capture.py:79`); no WARN level |
| Comparator by true condition, missing set-point caveats, paired uncertainty | EXISTS | `measurement/compare.py:64`, `uxr_compare.py` |
| Calibration/systematic uncertainty labels | MISSING | |
| Zero-error confidence upper bounds | EXISTS | `statistics/intervals.py:13` (Clopper-Pearson); used at `measurement/uxr_ingest.py:299` |
| New results location, never overwrite, never relabel mock as measured | PARTIAL | mock banner `reporting/uxr_report.py:36`; `visualization/figures.py:30` `STAMP = "SIMULATED"`; no single evidence-label type, no `analytical` |
| Real UXR import validation | BLOCKED | `BLOCKED: REAL UXR EXPORT REQUIRED` |

## Stage 4: calibrated channel model

| Feature | Status | Evidence and gap |
|---|---|---|
| `ChannelEstimate` with measured/assumed/standard provenance | PARTIAL | per-level Gaussian `ChannelEstimate` (`optimization/adaptive.py:35`); no provenance, covariance or `CALIBRATION FAILED` |
| Gain/offset, noise per level from calibration only | PARTIAL | `optimization/adaptive.py:46`, `receiver/dsp.py:154` (4 levels) |
| Effective Tx/Rx response, MZM bias/ER, attenuation/dispersion, timing/jitter, nonlinearity identification | MISSING | |
| Fit configuration, bounds, residuals, identifiability diagnostics | MISSING | |
| Held-out prediction, predeclared split and loss | MISSING | |
| Epistemic vs repeat-run vs instrument/systematic uncertainty split | MISSING | |
| One-at-a-time sensitivity, bounded sweeps, bootstrap propagation | PARTIAL | `bootstrap_interval` exists (`statistics/intervals.py:26`); `results/fiber_validation/figures/sensitivity.png` is a fibre sensitivity study, not a channel-model one |
| Standard G.652.D kept distinct from measured fibre | EXISTS | v1.1 gate; `docs/ALGORITHM_PROVENANCE.md` |
| Uncalibrated model reproduced exactly when no calibration requested | EXISTS | by construction (no calibration path); anchor protects PAM4 outputs |
| Laboratory digital-twin validation | BLOCKED | needs real paired captures; otherwise `SIMULATION-VALIDATED ONLY` |

## Stage 5: causal adaptive feedback engine

| Feature | Status | Evidence and gap |
|---|---|---|
| Deterministic `AdaptivePolicy` using only past/present observations | MISSING | |
| Baseline policies (Uniform, Fixed, best-fixed, periodic re-opt, hysteretic) | MISSING | |
| Chronological train/validation/test separation | MISSING | |
| Overhead charged: estimation, feedback, handshake, switching, training, compute | MISSING | latency budgets would be assumptions |
| Net realised information per elapsed second | MISSING | |
| Channel replay simulator (steps, drift, fades, mismatch, delayed/failed feedback) | MISSING | |
| State, action, cost, time logging | MISSING | |
| Validity windows, minimum evidence, hysteresis, rollback, bounded actuation, safe fallback | MISSING | |
| No live instrument commands | EXISTS | no instrument write path; `import_command` only builds a string and `MockM8199BAdapter.enable_output` is a mock (`instruments/m8199b.py:64,82`) |
| No future leakage; held-out runs not used for action selection | MISSING | no policy to test; training/test id check is `assert_disjoint` only |

## Stage 6: FEC, coding, PAS

| Feature | Status | Evidence and gap |
|---|---|---|
| FEC interface: encoder, soft decoder, parity checks, failure reporting | MISSING | |
| LDPC profile and parity-matrix asset audit | MISSING | no parity matrices in the repo |
| Chain: bits, matching, coding, symbols, LLRs, decoding, bits | MISSING | CCDM exists alone |
| Rate accounting: payload, matcher loss, overhead, parity | PARTIAL | `rate_loss` (`ccdm.py:100`), `bits_per_block` in the frame; no parity |
| Post-FEC BER/FER | MISSING | needs an actual decoder |
| PAS claim | MISSING | CCDM plus LDPC must be named `FEC-assisted shaped M-PAM` until PAS is proven |
| AIR/GMI/NGMI separate from delivered throughput | PARTIAL | BMD/SMD are labelled as rates; no delivered-throughput figure |

## Stage 7: hardware-in-the-loop

| Feature | Status | Evidence and gap |
|---|---|---|
| Capability-negotiated instrument interfaces | MISSING | |
| `MockAWG` | PARTIAL | `MockM8199BAdapter` (`instruments/m8199b.py:72`) |
| `MockScope` | PARTIAL | `instruments/mock_receiver.py:22,29` |
| `RecordedCapture` | MISSING | |
| `DryRunPlan` | MISSING | |
| Read-only real adapters; plan/load/arm/output_enable split | MISSING | no SCPI is sent (`docs/KEYSIGHT_SETUP.md`) |
| Preflight: granularity, memory, rate, amplitude/impedance | PARTIAL | `Profile.check()` (`m8199b.py:52`); amplitude and impedance not checked |
| Trigger/clock alignment, loss budget, device safety | MISSING | |
| Instrument identity, options, bandwidth | BLOCKED | `BLOCKED: HARDWARE CONFIGURATION REQUIRED`; UXR model suffix unconfirmed |
| Operator capture workflow tied to immutable data | PARTIAL | UXR ingest registry |
| Live control, measured campaign | BLOCKED | needs explicit external permission |

## Stage 8: dashboard, reproducibility, publication

| Feature | Status | Evidence and gap |
|---|---|---|
| Offline read-only dashboard | MISSING | |
| Provenance footer, simulated vs measured marking, cross-filtering, exports | PARTIAL | provenance text in reports; no filtering |
| CI, type checks, tests | EXISTS | `.github/workflows/ci.yml` (ubuntu and macOS, ruff, mypy, pytest) |
| SPDX / dependency / SBOM audit | EXISTS | `scripts/license_audit.py`, `docs/sbom.cdx.json` (licence strings only, no hashes) |
| Deterministic smoke configs | PARTIAL | `configs/demo.yaml` |
| Cross-platform reproducibility | PARTIAL | CI runs two OSes, but the byte anchor has only been run on macOS here |
| Numerical performance budgets | MISSING | no timing tests |
| Failure-mode documentation | PARTIAL | `docs/engineering_log/FAILURES.md` |
| Independent software validation, paper-ready results matrix | MISSING | |
| Software-paper vs experimental-paper claims separation | MISSING | |
| Experimental validation | BLOCKED | needs a measured campaign and lab records |

## Security and reproducibility observations (not changed in Gate 0)

- The configured seed (42) feeds the training capture (`optimization/adaptive.py:65`) and the payload generators (`transmitter/frame.py:68`, with a name hash); the PLAN records this shared seed as a risk, and stream keys are not recorded in manifests.
- Payload RNG is keyed by `crc32` of the waveform name (`transmitter/frame.py:68`), so renaming a PAM4 waveform changes its bytes. PAM4 names must stay.
- `experiment_id` hashes the YAML file text, so editing `configs/m8199b_profiles.yaml` changes identifiers.
- `optimization/adaptive.py:27` `assert_disjoint` compares ids only. The UXR ingest registry does reject identical content under a different id (`measurement/uxr_ingest.py:141-153`).
- HDF5 and CSV ingest were hardened in v1.2 (see engineering log); a grep of `src` and `scripts` found no `pickle`, `eval`, `exec`, `yaml.load`, `subprocess` or `shell=True`; the one NumPy load uses `allow_pickle=False` (`measurement/capture.py:175`). This was a grep, not an exhaustive security review.
