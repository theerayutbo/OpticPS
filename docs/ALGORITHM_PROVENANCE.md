# Algorithm provenance

| Component | Source of method |
|---|---|
| Maxwell-Boltzmann shaping, PAS context, R_BMD | Boecherer, Steiner, Schulte, IEEE T-COM 2015, doi:10.1109/TCOMM.2015.2494016 |
| Peak-limited shaping for IM/DD, PSNR definition | Wiegart et al., JLT 2021, doi:10.1109/JLT.2020.3029371 |
| CCDM definition | Schulte, Boecherer, IEEE T-IT 2016, doi:10.1109/TIT.2015.2499181 |
| Enumerative ranking | Cover, IEEE T-IT 1973, doi:10.1109/TIT.1973.1054929 |
| AIR, mismatched decoding | Boecherer et al., JLT 2019, doi:10.1109/JLT.2019.2895770; Arnold et al., IEEE T-IT 2006, doi:10.1109/TIT.2006.878110 |
| Gray code | Gray, US Patent 2,632,058 |
| CD power fading | Wang, Petermann, JLT 1992, doi:10.1109/50.108743 |
| MZM transfer | Wooten et al., IEEE JSTQE 2000, doi:10.1109/2944.826874 |
| Fiber attenuation and dispersion limits, G.652.D tables, Table I.1 representative values | Rec. ITU-T G.652 (08/2024), edition 10.0, Tables 2 and I.1, Eq. (6-1) to (6-3); Eq. (6-2) signs reconstructed and confirmed by continuity with Eq. (6-3) at 1460 nm |
| Three-term Sellmeier dispersion and its derivative | Rec. ITU-T G.652 (08/2024), Eq. (6-1) and Appendix I; the representative-curve fit through D1550 and S1550 is an OpticPS model choice |
| Dispersion phase beta2, beta3 and sign convention | Standard fiber optics (Agrawal, Nonlinear Fiber Optics); beta3 = (lambda^4 S + 2 lambda^3 D) / (4 pi^2 c^2) derived from beta2 = -D lambda^2 / (2 pi c); sign verified against numpy's FFT by a group delay test |
| Bootstrap | Efron 1979, doi:10.1214/aos/1176344552; Kuensch 1989, doi:10.1214/aos/1176347265 |
| Binomial interval | Clopper, Pearson 1934, doi:10.1093/biomet/26.4.404 |

DOIs were confirmed during the design review by Crossref or index lookup, except Smith 1971, which is cited without a DOI.

## PAM-M rates (`optimization/rates.py`, v1.3-mpam C2)

Derived independently from the definitions; no other simulator was consulted. On the unipolar alphabet x_i = i, i = 0..M-1, with noise sigma:

- PSNR = (M-1)^2 / sigma^2, so sigma = (M-1) / 10^(PSNR_dB/20). M = 4 gives 9 / sigma^2 as before. Equal PSNR across M is equal peak-to-peak swing and equal noise. The average SNR E[x^2] / sigma^2 is reported separately (`average_snr`).
- R_SMD = I(X;Y) = H(X) - H(X|Y).
- R_BMD = [H(X) - sum_{k=1..m} H(B_k|Y)]^+, m = log2 M, Gray labels, exact bit posteriors; Boecherer et al. 2015 (the AIR row above). Its unclipped value is returned as `bmd_raw` and can be negative; `bmd` is the explicit clip. It equals the bit-metric GMI evaluated at s = 1 without the clip. The GMI also maximises over s >= 0, which is not done, so the code keeps the name R_BMD.
- Expectations over Gaussian noise: Gauss-Hermite quadrature (log-sum-exp posteriors). Default 120 nodes for M = 4 (unchanged, bit-identical), 240 otherwise, because 120 nodes are about 1e-8 from converged at M = 2, 8, 16.

Tests: `tests/test_mpam_rates.py` checks closed-form SER 2(1-1/M)Q(1/(2 sigma)) by Monte Carlo (M = 2, 8, 16; PAM2 at 12 dB = 0.0233; a 6 dB error is detected), binary-AWGN capacity by `scipy.integrate.quad`, PAM2 and PAM4 embeddings in larger alphabets, a trapezoid integrator at M = 16, the bounds 0 <= SMD <= H <= log2 M and BMD <= SMD, and exact PAM4 values pinned at de1fc73.
