# Findings for the paper

All findings below are SIMULATED or calculated. No measurements exist yet.

## F-001 Inner-heavy shaping loses under fixed peak
- Claim: on a peak-limited AWGN channel, inner-heavy symmetric PAM4 is below uniform across 10 to 26 dB PSNR. The optimum is outer-heavy at low PSNR and uniform from about 22 to 24 dB.
- Numbers at PSNR 14 dB, SMD: Uniform 1.035, PS70 0.869, PS80 0.745, Outer70 1.101 bit/use.
- Script: `scripts/prebuild_rate_check.py`, deterministic quadrature. Independently recomputed by Fable with trapezoid integration.
- Agreement with Wiegart et al.: 0.83 dB SMD and 0.71 dB BMD optimum gain; 0.63 dB fixed BMD gain.
- Confidence: high for the model. Not a statement about the Southampton link.
