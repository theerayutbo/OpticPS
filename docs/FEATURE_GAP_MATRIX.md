# Feature gap matrix (Gate 0, roadmap v2 section D)

Baseline: `a2eb969` on `main`, work branch `v1.3-mpam`, package version 1.2.0. Every status below comes from reading this repository only. Nothing was changed to produce it. Statuses: EXISTS, PARTIAL, MISSING, BLOCKED (needs data or hardware not available). All existing evidence is simulated or mock; no laboratory capture has been seen.

## Stage 1: adaptive M-PAM core

| Feature | Status | Evidence and gap |
|---|---|---|
| PAM levels, Gray labels, bit mapping for M = 2, 4, 8, 16 | EXISTS | `modulation/pam.py:9` `SUPPORTED_ORDERS`, `:18 :24 :31`; `indices_to_bits` and `bits_to_indices` default `order=4` (`:38`, `:44`) |
| Maxwell-Boltzmann family, any M | PARTIAL | `shaping/distributions.py:45` takes `order`; only one sign of lambda is tied to M=4 entropy equivalence; no entropy-matched constructor |
| Symmetric per-pair PMF (higher-dimensional) | MISSING | only `symmetric_pam4(p_outer)` (`shaping/distributions.py:52`), one parameter |
| PMF validation for any M | EXISTS | `validate_probabilities(p, order)` is generic; callers pass 4 |
| H(X), SMD, BMD under non-uniform priors | PARTIAL | `optimization/rates.py:36` `gaussian_rates` is written for 4 symbols and 2 bits; Hermite-Gauss 120 nodes, no log-sum-exp |
| Rate bounds enforced, Monte Carlo/quadrature uncertainty | PARTIAL | `bmd` clipped at 0 silently (`rates.py:58`); no quadrature error estimate |
| Exact reversible CCDM | EXISTS | `distribution_matching/ccdm.py`; alphabet-generic code; M=8/16 round-trip and timing untested |
| Composition rounding preserving symmetry at M>=8 | MISSING | `quantize_composition` (`ccdm.py:35`) is largest-remainder, can split mirrored pairs when M>=8 |
| Constrained search protocols (`fixed_peak`, `fixed_average_optical_power`, `fixed_OMA`, `equal_realized_user_rate`) | MISSING | no `optimization/constraints.py`; equal-rate search for PAM4 only in `measurement/compare.py:112` |
| `INFEASIBLE` with reasons | PARTIAL | M8199B profile checks raise (`instruments/m8199b.py`); no optimiser-level INFEASIBLE |
| Training-selected adaptive vs predeclared best-fixed, held-out test | PARTIAL | `optimization/adaptive.py` selects on training only and has `assert_disjoint`/`DataLeakageError`; best-fixed is the manual PS70/PS80/Outer70 set; no stored candidate table |
| Optimiser multistart log, global/local claim | MISSING | one-dimensional grid in `adaptive.py:100` |
| Export Uniform, Inner, Outer, Adaptive, best-fixed for M=4/8/16 | PARTIAL | M=4 only (`transmitter/export.py:32-33,159-167`); no best-fixed entry |
| Manifest, references, checksums | EXISTS | `export.py:46`, `:262`, `:309`; PAM4 schema, 40 columns |
| M8199B offline-only export constraints | EXISTS | `instruments/m8199b.py` Profile checks; granularity 512 and 1,048,576 limit not in the M8100 guide, see `engineering_log/VERIFICATION.md` |
| Protocol A (matched baud) | EXISTS | profiles A 8 GBd and B 56 GBd in `configs/m8199b_profiles.yaml` |
| Protocol B (matched realised user rate incl. overhead) | PARTIAL | PAM4 rate search `measurement/compare.py:112`; no preamble/training/matcher accounting across M |
| Drive Vpp, RMS, OMA, ER recorded separately | PARTIAL | partly in manifest; OMA and ER fields absent |
| PAM4 legacy regression | EXISTS | `tests/test_export.py` (reduced training size); full-size byte anchor added in C1: `tests/test_pam4_anchor.py` |
| Gray bit-flip, closed-form SER, embedding tests | MISSING | planned in PLAN.md as `test_mpam_rates.py` |
| Shaped BER vs information-bit BER | PARTIAL | label BER and info bits both present for PAM4 (`receiver/dsp.py:197`); not separated for M>4 |
| Documented negative/infeasible case | MISSING | |
| M-PAM config schema with versioning | MISSING | `configs/m8199b_profiles.yaml` has no schema version; `experiment_id` hashes the file, so it must not be edited |

### Stage 1: PAM4-bound sites (file:line, grep of this checkout)

| File | Lines | What is fixed to PAM4 |
|---|---|---|
| `optimization/rates.py` | 5-6 docstring, 22 `_UNIPOLAR = arange(4)`, 28 `3.0 /` in sigma, 41 `validate_probabilities(p, 4)`, 46 `label_bits(4)`, 54 `range(2)` bits, 63 `np.full(4,...)`, 78 symmetric PAM4 search |
| `optimization/adaptive.py` | 1 docstring, 46-52 `range(4)` per-level fit, 66-68 `integers(0, 4)`/`pam_levels(4)`, 75 `p_outer`, 100-119 one-parameter grid, 133 design rate |
| `shaping/distributions.py` | 18-21 `UNIFORM/PS70/PS80/OUTER70` 4-tuples, 52-63 `symmetric_pam4`, `lambda_of_symmetric_pam4` (`/ 8.0`) |
| `modulation/pam.py` | 38, 44 default `order=4` |
| `transmitter/frame.py` | 33-37 preamble on indices {0,3} (`* 3`), 43 training `arange(4)`, `// 4`, 84 docstring, 95-97 `2 * length` bits |
| `transmitter/export.py` | 32-33 names, 97 `3.0 *` full scale, 102 and 136 `pam_levels(4)`, 159-167 waveform table, 201 `minlength=4`, 204 `target[0]`, 234 `+/-3` preamble note, 272 `"modulation": "PAM4"`, 290 `2 * symbol_rate` |
| `receiver/dsp.py` | 54, 94, 112, 128, 171, 280 `pam_levels(4)`; 158-159 `range(4)`; 208 `label_bits(4)`; 228 `2 * sent.size` |
| `receiver/capture_dsp.py` | 265, 278, 399, 508 `pam_levels(4)`; 635, 650 `2 *` bits; 729, 844 `zeros/minlength 4`; 854 `range(4)` |
| `measurement/validate_export.py` | 24 `LEVELS = (-3,-1,1,3)`, 27-30 PMF table, 122 and 149-156 `range(4)`, 167 `2 * length` |
| `measurement/capture.py` | 155 `validate_probabilities(..., 4)`; 235 `indices_to_bits` default |
| `measurement/uxr_ingest.py` | 185 priors matched to manifest probabilities (no M assumption seen, but manifest schema is PAM4) |
| `measurement/demo.py` | 61-65 waveform names, 72 `np.full(4, 0.25)`, 78 `/ 3.0`, 145-152 `arange(4)`, 168-172 `p_outer` |
| `measurement/compare.py` | 112 uniform PAM4 rate search, 271 `p_outer` |
| `measurement/fiber_validation.py` | 334 `waveforms(selected["p_outer"])` |
| `reporting/report.py` | 133 `selected_p_outer`, 218 and 250 PAM4 and `9 / sigma^2` text, 264 `p_outer` |
| `reporting/uxr_report.py` | 41-45 waveform table, 197 `arange(4)`, 201 "PAM4 level" |
| `reporting/slides.py` | 66, 78, 92, 191 PAM4 text and `p_outer` |
| `visualization/figures.py` | 114 `p_outer`, 190-198 `range(4)` and tick labels `-3..+3` |
| `cli/main.py` | 39 prints `P(+-3)` |

## Stage 2: IM/DD front end, receiver, uncertainty

| Feature | Status | Evidence and gap |
|---|---|---|
| DAC quantisation | PARTIAL | `export.py:127` `dac_quantize`, export only; not a simulation impairment |
| ADC quantisation, clipping, ENOB noise, jitter, clock offset, driver compression, AC coupling | MISSING | none in `optical_channel/` or `receiver/`; ENOB curve known only as a figure in the data sheet |
| Finite Tx/Rx bandwidth | EXISTS | `optical_channel/link.py:75-76` receiver and optional transmitter bandwidth, Butterworth magnitude (`:151`) |
| RIN, MZM bias drift | MISSING | |
| Sine-law MZM, extinction, insertion loss, linear fibre, G.652.D | EXISTS | `optical_channel/link.py`, `fiber.py`, `docs/engineering_log` v1.1 gate |
| Custom Hollow-Core/NANF parameters | MISSING | no documented values in repo; not to be invented |
| Sync, preamble, calibration, MAP for all M | PARTIAL | PAM4 only (`receiver/dsp.py`); MAP present |
| FFE | EXISTS | `receiver/dsp.py:102,119` |
| DFE | MISSING | |
| Soft bit LLR with priors | MISSING | `log_likelihoods` (`dsp.py:163`) is symbol-level |
| Confusion matrix, eye, EVM, SER, BER, AIR, uncertainty | PARTIAL | SER, BER, BMD/SMD, Clopper-Pearson and bootstrap (`statistics/intervals.py`) exist; per-level confusion, eye, EVM missing |
| Impairment-off equals old outputs | MISSING | no impairments to switch |

## Stage 3: campaign engine and UXR intake

| Feature | Status | Evidence and gap |
|---|---|---|
| `ExperimentPlan` schema, randomised run order, run sheet | MISSING | |
| `INFEASIBLE` equipment combinations | PARTIAL | Profile checks only |
| Sample size / `POWER ANALYSIS NOT POSSIBLE` | MISSING | |
| HDF5/CSV/BIN UXR import, strict parsing, units | PARTIAL | `measurement/uxr_import.py`; CSV and HDF5, no BIN; `UNVERIFIED AGAINST REAL FILES` |
| Immutable intake, SHA-256, split, leakage rejection | PARTIAL | `uxr_ingest.py`; `assert_disjoint` in `adaptive.py` rejects by id, not by content hash |
| Capture quality PASS/WARN/REJECT | MISSING | frame gates exist in `capture_dsp.py`, no three-level classification |
| Grouped comparator, paired uncertainty, zero-error upper bounds | PARTIAL | `uxr_compare.py`, `statistics/intervals.py` |
| Evidence label SIMULATED/MOCK/MEASURED on outputs | PARTIAL | `visualization/figures.py:30` `STAMP`, `reporting/uxr_report.py:36` banner; no `analytical` label, not a single mechanism |
| Real UXR import validation | BLOCKED | `BLOCKED: REAL UXR EXPORT REQUIRED`; no real file has been seen |

## Stage 4: calibrated channel model

| Feature | Status | Evidence and gap |
|---|---|---|
| `ChannelEstimate` with provenance, fit from training only | PARTIAL | `optimization/adaptive.py:35` has a per-level Gaussian `ChannelEstimate` (means, sigmas, samples) fitted from training; no measured/assumed/standard provenance, no covariance or CALIBRATION FAILED |
| Per-level mean/sigma fit from training | EXISTS | `optimization/adaptive.py:46`, `receiver/dsp.py:154` (4 levels only) |
| Held-out prediction, sensitivity, bootstrap propagation | MISSING | bootstrap helper exists in `statistics/intervals.py` |
| Laboratory digital-twin validation | BLOCKED | needs real paired captures; otherwise `SIMULATION-VALIDATED ONLY` |

## Stage 5: causal adaptive feedback engine

| Feature | Status | Evidence and gap |
|---|---|---|
| `AdaptivePolicy`, baselines, replay simulator | MISSING | |
| Overhead accounting (estimation, feedback, switching, compute) | MISSING | latency budgets would be assumptions, not facts |
| Safety: hysteresis, rollback, no live commands | MISSING | no instrument write path exists, which is the safe default |

## Stage 6: FEC, coding, PAS

| Feature | Status | Evidence and gap |
|---|---|---|
| FEC encoder, soft decoder, parity assets | MISSING | no parity matrices anywhere in the repo |
| Shaping plus coding chain | MISSING | CCDM exists alone; must be called `FEC-assisted shaped M-PAM`, not PAS |

## Stage 7: hardware-in-the-loop

| Feature | Status | Evidence and gap |
|---|---|---|
| `MockAWG`, mock scope, recorded capture, dry-run plan | PARTIAL | `instruments/m8199b.py` `MockM8199BAdapter`, `instruments/mock_receiver.py` |
| Read-only real adapters, plan/load/arm/enable split | MISSING | `import_command` only builds a command string; no SCPI is sent |
| Preflight (granularity, memory, rate, amplitude) | PARTIAL | `Profile.check()` |
| Real instrument model, options, bandwidth | BLOCKED | `BLOCKED: HARDWARE CONFIGURATION REQUIRED`; UXR model suffix unconfirmed |
| Live control, measured campaign | BLOCKED | out of scope without explicit external permission |

## Stage 8: dashboard and publication package

| Feature | Status | Evidence and gap |
|---|---|---|
| Offline read-only dashboard | MISSING | |
| CI, type checks, SBOM, licence audit | EXISTS | `.github/workflows/ci.yml`, `scripts/license_audit.py`, `docs/sbom.cdx.json` |
| Deterministic smoke configs | PARTIAL | `configs/demo.yaml` |
| Paper-ready results matrix, claims separation | MISSING | |
| Experimental validation | BLOCKED | needs measured campaign |

## Security and reproducibility observations (not changed in Gate 0)

- The configured seed (42) feeds the training capture (`optimization/adaptive.py:65`) and the payload generators (`transmitter/frame.py:68`, with a name hash); the PLAN records this shared seed as a risk, and stream keys are not recorded in manifests.
- Payload RNG is keyed by `crc32` of the waveform name (`transmitter/frame.py:68`), so renaming a PAM4 waveform changes its bytes. PAM4 names must stay.
- `experiment_id` hashes the YAML file text, so editing `configs/m8199b_profiles.yaml` changes identifiers.
- `assert_disjoint` compares ids only; identical content under two names would pass.
- HDF5 and CSV ingest were hardened in v1.2 (see engineering log); a grep of `src` and `scripts` found no `pickle`, `eval`, `exec`, `yaml.load`, `subprocess` or `shell=True`; the one NumPy load uses `allow_pickle=False` (`measurement/capture.py:175`). This was a grep, not an exhaustive security review.
