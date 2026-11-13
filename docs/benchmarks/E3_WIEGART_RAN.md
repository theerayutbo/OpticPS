# Gate E3: independent published numerical and analytical curves (Wiegart, Ran)

Code: `src/opticps/benchmarks/{published_points,comparison,e3_wiegart,e3_ran}.py`.
Tests: `tests/test_benchmark_e3.py` (it also checks that the statuses in the tables below are the ones the code computes).
Configs: `configs/benchmarks/wiegart_2021_peak_pam4.yaml` (technical fields now filled, with locations), `configs/benchmarks/ran_2025_g652d.yaml` (unchanged apart from a note).

## Rules this gate worked under

* Wiegart et al. (JLT 39(2), 400-405, 2021, DOI 10.1109/JLT.2020.3029371): reuse terms **UNVERIFIED**. No figure, no digitised or re-plotted point, no copied equation image and no copied or closely paraphrased sentence is in this repository. Numbers below are values the author manuscript states in its running text; a published point cannot be built from a figure (`ReadFrom` has no figure member). Where a figure would be needed the row says `NOT COMPARABLE: FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED)` and names the figure and axes.
* Ran et al. (Nat. Commun. 16, 6268, 2025, DOI 10.1038/s41467-025-61408-7): article CC BY-NC-ND 4.0, incompatible with this MIT repository. Only bibliographic strings and cited numeric facts (wavelength, measured dispersion, the two link lengths and lane rates, FEC thresholds) are used. Nothing of the article was read again for this gate.
* Locations for Wiegart refer to the numbering of the author manuscript `2005.12428v2.pdf` (local file, ignored by git, SHA-256 starts `3a49c2f8`). Whether the JLT numbering is identical was not checked.
* No parameter was adjusted to improve agreement. Tolerances were written into `e3_wiegart.py` before any deviation was computed and are pinned by a test.

## Part 1. Wiegart: fixed-peak constrained PAM4

### What is computed and how it maps to the paper

Our notation: transmit levels a_i = i (i = 0..3, unit spacing), PMF pi, channel Y = X + N, N Gaussian with variance s^2, so the peak SNR is rho = 9 / s^2 and s = 3 * 10^(-rho_dB/20). The peak (the largest level) is fixed for every PMF, which is the paper's equal peak-to-peak drive.

| Item | Paper (manuscript location) | Ours |
|---|---|---|
| Channel and noise | linear AWGN model, real zero-mean Gaussian noise of variance sigma^2 in the electrical domain (Sec. II, Eq. 3) | the same, N ~ Normal(0, s^2) |
| Peak SNR | max{X}^2 / sigma^2 = 9 / sigma^2 (Eq. 4) | rho = 9 / s^2; test: `test_psnr_definition_is_max_x_squared_over_sigma_squared` |
| Alphabet, constraint | X in {0,1,2,3}, a peak power constraint with equal spacing (Sec. II) | fixed peak 3; no average-power constraint is applied |
| Distribution family | symmetric about the mean, one free parameter P_X(0) in [0, 0.5], P_X(3) = P_X(0), P_X(1) = P_X(2) = (1 - 2 P_X(0)) / 2 (Sec. II, after Eq. 5) | `symmetric_pmf(p)`; p = 0.5 is on-off keying, p = 0.25 uniform |
| Symbol-metric rate | R_SMD = I(X;Y) (Eq. 6) | R_S = I(X;Y), bits per channel use |
| Bit-metric rate | R_BMD = [H(X) - sum_k H(B_k given Y)]^+ (Eq. 7), two-bit binary reflected Gray label | R_B with b(x) = x XOR (x >> 1): 0 to 00, 1 to 01, 2 to 11, 3 to 10. The paper names the code but prints no table; this is the standard four-point code and is our reading |
| Fixed experimental PMF | (0.35, 0.15, 0.15, 0.35) (Sec. II and Fig. 4b caption text) | `FIXED_PMF` |
| Real or simulated | Eq. 3 results are numerical (information-theoretic); Sec. III results are measured, with a 5-tap (back-to-back) or 11-tap (fibre) FFE and an estimated rate | the compared rows are numerical only; measured rows are refused |

The compared quantity is the **PSNR gain in dB**: PSNR a uniform 4-PAM needs to reach the target rate minus the PSNR the shaped PMF needs for the same rate, same peak, same noise.

### Independent computation (provenance)

* Primary: OpticPS `opticps.optimization.rates.achievable_rates` and `psnr_for_rate` (Gauss-Hermite quadrature over the posterior form). The one-parameter line search over p (`best_symmetric`) is new code.
* Second method, written separately from the differential-entropy form: `rates_by_grid` computes R_S = h(Y) - h(N) by trapezoid integration of the Gaussian-mixture density, and R_B from the bit posteriors on the same grid. It shares no code with the primary route. Agreement with the OpticPS rates is within 1e-7 bit over five PMFs and four PSNRs (tests).
* Closed forms and limits pinned in the tests: noise-free limit gives H(X); low-SNR limit gives Var(X) / (2 s^2 ln 2); on-off keying agrees with a third method, 1 - E[log2(1 + exp(LLR))] with LLR = g z - g^2 / 2, g = 3/s (`quad`, to 1e-8), and there R_B = R_S exactly because the two outer labels differ in one bit; R_B never exceeds R_S; uniform 4-PAM saturates at 2 bit; an unconstrained search over the whole PMF simplex at 12.9 dB ends symmetric (p0 = p3 and p1 = p2 within 2e-3).
* Measured agreement of the two routes on the gains below: 1.4e-5 dB (SMD, best symmetric) and 4.4e-5 dB (BMD, best symmetric), 6.6e-7 dB and 2.1e-5 dB for the fixed PMF (SMD, BMD); the tests allow 2e-4 dB.

### Tolerances (fixed before the deviations were computed)

* Gains in dB: **0.01 dB**. The paper prints two decimals (rounding alone is 0.005 dB); a further 0.005 dB allows for the line-search resolution and rate estimator it does not report. Our two methods agree far below this.
* Optimal P_X(0): **0.05**. One printed decimal (rounding 0.05), and the paper itself says the nearby fixed PMF performs close to optimal over a wide range, so the optimum is flat and cannot be resolved finer than the printed digit.

### Matched-comparison table, Wiegart

Target rate 1.0 bit per channel use unless stated. "Dev" is ours minus the paper's.

| Row | Source location | Source quantity and conditions | Our quantity and conditions | Value (ours) | Dev | Tol | Status |
|---|---|---|---|---|---|---|---|
| W1 | Sec. II, text after Fig. 2 | PSNR gain of optimal PS over uniform 4-PAM, SMD, peak constraint, 1.0 bpcu: 0.83 dB | same, best symmetric PMF found by line search (p = 0.3982); uniform needs 13.6916 dB, shaped 12.8589 dB | 0.8328 dB | +0.0028 | 0.01 | MATCH |
| W2 | Sec. II, text after Fig. 2 | same with BMD: 0.71 dB | same, best symmetric PMF (p = 0.3958); uniform 13.8538 dB, shaped 13.1441 dB | 0.7097 dB | -0.0003 | 0.01 | MATCH |
| W3 | Sec. II, text after Fig. 2 | gain of the fixed PMF (0.35, 0.15, 0.15, 0.35), BMD, 1.0 bpcu: 0.63 dB | same PMF, same metric; fixed PMF needs 13.2270 dB | 0.6268 dB | -0.0032 | 0.01 | MATCH |
| W4a | Sec. III, text on the dispersion-less optimum | optimal P_X(0) for the AWGN model at 1 bpcu: 0.4 (metric not stated) | SMD: least PSNR for 1.0 bpcu over p | 0.3982 | -0.0018 | 0.05 | MATCH |
| W4b | Sec. III, same text | same value, metric not stated | BMD | 0.3958 | -0.0041 | 0.05 | MATCH |
| W5 | Sec. II, text after Fig. 1 (qualitative) | the PSNR range where on-off keying is the optimal PMF is wider for BMD than for SMD | on-off keying stops being optimal at 10.70 dB (SMD) and 12.05 dB (BMD), 0.05 dB grid | ordering reproduced | n/a | n/a (ordering) | MATCH |
| W6 | Fig. 1 | optimal P_X(0) against PSNR, SMD and BMD curves | not computed against the source | n/a | n/a | n/a | NOT COMPARABLE: FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED). Needed: Fig. 1, x: PSNR [dB], y: P_X(0), both curves |
| W7 | Fig. 2a, 2b | rate curves and the dB and bit gap annotations on them | not computed against the source | n/a | n/a | n/a | NOT COMPARABLE: FIGURE VALUES NOT REDISTRIBUTABLE (LICENCE UNVERIFIED). Needed: Fig. 2a (BMD) and 2b (SMD), x: PSNR [dB], y: rate [bit/channel use], curves and annotations |
| W8 | Sec. II, text on the coded simulation | gain at a frame error rate of 1e-3 for a protograph LDPC code with PAS and CCDM | not computed | n/a | n/a | n/a | NOT COMPARABLE |
| W9 | Sec. III, experiments at 16 GBd | measured gains in attenuation (dB), in rate (bit) and in reach (km), with a short FFE | not computed | n/a | n/a | n/a | NOT COMPARABLE |

Reasons for W8 and W9, stated by the code: W8 is a coded frame-error quantity, not an information rate, and the code construction is not fully specified. W9 is measured, the electrical PSNR at the receiver (the compared axis), the baud rate per point and the loss budget are not stated, and the fibre results include chromatic dispersion, which the AWGN model leaves out. Nothing was adjusted to make W9 comparable.

Other facts for the owner: the same theory also gives a rate gain at fixed PSNR; the paper annotates it on Fig. 2a and 2b only, so it is not compared (W7). The existing test `tests/test_core.py::test_rates_reproduce_wiegart_gains` uses a looser 0.03 dB window; this gate does not rely on it.

### Honest reading

All five numerical rows agree within the pre-declared tolerance. This is agreement of the information-theoretic AWGN model with the paper's own numbers. It does not validate any hardware, it does not say anything about the measured experiments (W9), and it is not evidence that OpticPS's adaptive policy achieves a measured shaping gain.

## Part 2. Ran: what can and cannot be said

### Source Data spreadsheet

Names under `data/external/` were listed (names only; no file opened): `nanf_hong2021`, `teriphic`. No file named like the Source Data (`41467_2025_61408_MOESM3_ESM.xlsx`) is present. Status:
`BLOCKED: SOURCE DATA XLSX NOT OBTAINED (LICENCE/REUSE TERMS UNVERIFIED)`. Nothing was downloaded. The schema, the figure association and the operating conditions per point therefore remain unknown.

### Chirped MZM / complex-field model

Decision, from the cited facts in the config and the register only: **`MODEL GAP: CHIRP`**. The cited facts give the wavelength (1271 nm), the measured dispersion (-3.99 ps/(nm km)), the link lengths (5 km and 10 km) with their lane rates, the receiver equaliser tap count, and the FEC thresholds. They do not give, so no chirp model was built:

chirp parameter of the silicon MZM (value and sign); bias point; drive swing, Vpi and driver bandwidth; MZM electro-optic bandwidth; symbol rate per lane; gross versus net meaning of the 256 and 200 Gb/s rates; BER definition; launch and received power and link loss; photodiode responsivity, receiver bandwidth and noise; laser intensity noise and linewidth; receiver sampling and equaliser training beyond the tap count; MLSD memory length; settings of the on-chip dispersion compensation; and the Source Data itself. The list is `e3_ran.CHIRP_MODEL_MISSING`.

### Analytical subcase (label ANALYTICAL; our derivation)

This is **not** a reproduction of the headline data rates, and the real link is chirped, so these null positions are **not** a prediction of the experiment.

Derivation (our notation): for a chirp-free intensity modulation with a small tone at f, the two optical sidebands acquire the phase phi(f) = beta2 L (2 pi f)^2 / 2 with beta2 = -D lambda^2 / (2 pi c), and square-law detection gives the tone amplitude |cos phi(f)|. Hence H(f) = |cos(pi D L lambda^2 f^2 / c)|, nulls at f_k = sqrt(c (2k + 1) / (2 |D| L lambda^2)), and the -3 dB electrical-power point at f_0 / sqrt(2). Inputs are the cited values only, wavelength and dispersion read from the Ran config, no 1550 nm default anywhere (the functions have no default for wavelength, dispersion or length; a test checks this).

| Length | Accumulated dispersion D L | First null f_0 | Second null | Third null | -3 dB point |
|---|---|---|---|---|---|
| 5 km | -19.95 ps/nm | 68.20 GHz | 118.12 GHz | 152.50 GHz | 48.22 GHz |
| 10 km | -39.90 ps/nm | 48.22 GHz | 83.53 GHz | 107.83 GHz | 34.10 GHz |

Checks: explicit arithmetic in the test; agreement to 1e-12 with the existing link model `cd_null_frequency_hz`; and a second method, a time-domain simulation of a real-valued envelope through the all-pass dispersion of the link model at 1271 nm with square-law detection, whose tone amplitude matches |cos phi| to 2e-3 at five frequencies for both lengths (tests). A 1550 nm default would give a different first null, so the wavelength matters here.

### Matched-comparison table, Ran

| Row | Source location | Source quantity and conditions | Our quantity and conditions | Value (ours) | Dev | Tol | Status |
|---|---|---|---|---|---|---|---|
| R1 | abstract and results, cited fact | PAM4 lane rate 256 Gb/s over 5 km, 1271 nm; rate and BER definitions not stated | not computed: no chirp model | n/a | n/a | n/a | NOT COMPARABLE: MODEL GAP: CHIRP (missing parameters listed above) |
| R2 | abstract and results, cited fact | PAM4 lane rate 200 Gb/s over 10 km, 1271 nm; same | not computed | n/a | n/a | n/a | NOT COMPARABLE: MODEL GAP: CHIRP |
| R3 | Source Data spreadsheet | published BER points against 2.4e-2 (SD-FEC, 20% overhead) and 3.8e-3 (HD-FEC, 6.7%) | not computed | n/a | n/a | n/a | BLOCKED: SOURCE DATA XLSX NOT OBTAINED (LICENCE/REUSE TERMS UNVERIFIED) |
| R4 | none: no published null or fading frequency in the cited facts | no published value | ANALYTICAL chirp-free first null: 68.20 GHz (5 km), 48.22 GHz (10 km) | n/a | n/a | n/a | NOT COMPARABLE: no published counterpart; the real link is chirped |

## Comparison layer

`published_points.py`: `PublishedPoint` (source id, location, quantity, value, unit, rate definition, wavelength, fibre length, constraint peak or average, baud rate, BER definition, FEC threshold, DSP stage, optical or electrical drive, evidence label simulated/mock/measured/analytical, read-from) and `ModelPoint`. `comparison.py`: `compare` refuses with `NOT COMPARABLE` and a reason when quantity, unit, rate definition, constraint, wavelength, fibre length, baud rate, BER definition, FEC threshold, DSP stage or drive differ, or when a field is null on either side (a field that really does not apply must be declared, and then both sides must leave it null). It never converts a unit. The tolerance and its written justification are required arguments. Tests show each refusal (wavelength, unit, rate definition, constraint, null field) and an accepted matched comparison.

## Limitations

* Only numbers stated in running text were used. The figures carry the most informative content (curves, annotated gaps) and are untouched until the owner decides on the reuse terms; no figure was digitised.
* The Gray label table is our reading of "binary reflected Gray code" for four points. The BMD rows depend on it; the SMD rows and on-off keying do not.
* W1 to W4 compare against numbers the paper rounds to two decimals or one decimal; the tolerance reflects that, so these rows cannot distinguish differences below it. The paper's own gain annotation on the figure was not used and may differ from the text value in the last digit.
* The metric for the 0.4 optimum (W4) is not stated; both are reported and both fall inside the tolerance.
* The manuscript is the arXiv v2 author version, which contains leftover draft text; whether the JLT version differs in numbers or numbering was not checked.
* The Ran subcase is chirp-free, small-signal and ignores the fibre slope, the receiver response and all DSP; it is a bound on one mechanism, not a model of the link.
* Numerical agreement with theory does not validate any hardware.
