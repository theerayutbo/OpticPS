# Findings for the paper

All findings below are SIMULATED or calculated. No measurements exist yet.

## F-001 Inner-heavy shaping loses under fixed peak
- Claim: on a peak-limited AWGN channel, inner-heavy symmetric PAM4 is below uniform across 10 to 26 dB PSNR. The optimum is outer-heavy at low PSNR and uniform from about 22 to 24 dB.
- Numbers at PSNR 14 dB, SMD: Uniform 1.035, PS70 0.869, PS80 0.745, Outer70 1.101 bit/use.
- Script: `scripts/prebuild_rate_check.py`, deterministic quadrature. Independently recomputed by Fable with trapezoid integration.
- Agreement with Wiegart et al.: 0.83 dB SMD and 0.71 dB BMD optimum gain; 0.63 dB fixed BMD gain.
- Confidence: high for the model. Not a statement about the Southampton link.

## F-002 Finite-block matcher and equal-baud net rates
- Simulated/calculated, seed 42. Source: `output/keysight_m8199b/*/experiment_manifest.csv`.
- At equal baud, shaping lowers net payload rate. Profile A: Uniform 15.50 Gbit/s; PS70 and Outer70 14.47; PS80 13.22; Adaptive 13.93.
- PS70 and Outer70 are rate matched by construction.

## F-003 Simulated link comparison (not experimental)
- Source: `results/synthetic/demo_results.json`, config e39084adac9d, seed 42.
- Near 1 bit/symbol, inner-heavy loses and outer-heavy gains against Uniform; see LOG entry for intervals. Intervals reflect noise only, for one payload and one generic link.
- With peak unconstrained, PS70 beats Uniform for 4 to 11.5 dB SNR; 4 dB is the edge of the computed range.
