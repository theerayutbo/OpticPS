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
- R_BMD = [H(X) - sum_{k=1..m} H(B_k|Y)]^+, m = log2 M, Gray labels, exact bit posteriors; Boecherer et al. 2015 (the AIR row above). Its unclipped value is returned as `bmd_raw` and can be negative; `bmd` is the explicit clip. Without the clip, H(X) - sum_k H(B_k|Y) is the GMI at s = 1 of the metric q(x,y) = prod_k P(b_k|y) / P_X(x) (the denominator sum_x' P_X(x') q(x',y) is then 1). It is not the GMI at s = 1 of q = prod_k P(b_k|y): for M = 8, exp(-0.1 x^2), 20 dB the two are 1.43647 and 1.40726 (tested). The GMI also maximises over s >= 0, which is not done, so the code keeps the name R_BMD.
- Expectations over Gaussian noise: Gauss-Hermite quadrature (log-sum-exp posteriors). Default 120 nodes for M = 4 (unchanged, bit-identical), 240 otherwise. With equal sigma, 120 nodes are 1.9e-8 to 4.1e-8 from a 320-node value over 8-30 dB (M = 4 worst), and 240 nodes are within 4.2e-10 of 320 nodes and 6.7e-10 of an independent trapezoid integrator. With unequal per-level sigma convergence is slower, so the 1e-9 claim is for equal sigma only: for sigma ratios 0.7-1.4, 120 nodes are 1e-7 to 2e-7 off, 240 nodes 2e-9, 320 nodes 5e-10; for ratios 0.5-2.0, 120 nodes 2e-6 to 1.5e-5, 240 nodes 4e-8 to 2e-7, 320 nodes 7e-9 to 2e-8. Most likely cause (consistent with the scaling with the sigma spread, not proven): the nodes for level i are centred on mu_i with scale sigma_i, while the integrand contains Gaussians of other widths, so the log-posterior is no longer smooth on the node scale. Comparisons finer than 1e-7 across orders must fix `nodes` on both sides. Legacy PAM4 callers with unequal sigma (the adaptive channel estimate) keep 120 nodes and their results.

Tests: `tests/test_mpam_rates.py` checks closed-form SER 2(1-1/M)Q(1/(2 sigma)) by Monte Carlo (M = 2, 8, 16; PAM2 at 12 dB = 0.0233; a 6 dB error is detected), binary-AWGN capacity by `scipy.integrate.quad`, PAM2 and PAM4 embeddings in larger alphabets, trapezoid integrators with hand-written Gray tables at M = 8 and 16 (equal and unequal sigma), the bounds 0 <= SMD <= H <= log2 M and BMD <= SMD, and exact PAM4 values pinned at de1fc73.

## Symmetric shaping family and symmetric CCDM quantiser (v1.3-mpam C3)

Derived independently from the definitions; no other simulator was consulted.

- Pair family: q_j = P(+-x_j), j = 1..M/2, inner pair first, sum q_j = 1/2, so P is symmetric and E[x] = 0. `symmetric_from_pairs` and `pairs_of` are exact inverses; `pairs_of` rejects asymmetric PMFs.
- Maxwell-Boltzmann sign convention (unchanged from the repo): P(x) proportional to exp(-lam x^2), lam > 0 inner-heavy, lam < 0 outer-heavy (PS70 has lam = +ln(0.35/0.15)/8 > 0). `mb_for_entropy(H, M, sign)` solves H(MB(sign * mu)) = H for mu >= 0 with Brent's method; dH/dlam = -lam Var(x^2), so H falls monotonically in |lam|. Reachable range 1 < H <= log2 M for M >= 4 (lam -> +-inf leaves two levels, 1 bit, never attained); M = 2 only H = 1. Out of range raises ValueError.
- MB(+lam) and MB(-lam) have equal entropy only at M = 4 (two pair weights, a two-point law swaps under lam -> -lam). Measured at lam = 0.2: M = 8 gives 1.708 versus 1.074 bits, so the entropy match is done per side; tested at M = 8 and 16.
- Symmetric quantiser: quantise the lower half (outermost first, 2q scaled to n/2 symbols) with the existing largest-remainder rule and mirror. n must be even. Total is exactly n and pairs are never split. The legacy `quantize_composition` is untouched and can split a pair on tied remainders (uniform PAM4, n = 6 gives (2, 2, 1, 1); the symmetric rule gives (2, 1, 1, 2)).
- M = 4 equivalence: over all even n in 2..2048 and 101 PMFs (PS70, PS80, Outer70, uniform, 97 p_outer values from 0.01 to 0.49), the two rules differ in 3330 of 103424 cases and every difference is a case where the legacy composition is asymmetric or raises (no difference where the legacy result is symmetric). At n = 32, 64, 128, 256, 512, 1000, 1024, 2048, 4096, 16384 (tested) and 65536 (checked by hand), which cover the config block length 1024 and the demo sweep, they are identical on every one of the 101 PMFs. Legacy paths were therefore not switched.
- Finite-block loss: R = floor(log2 W)/n with W the type class size; `symmetric_rate_loss` = H(p) - R = [H(p) - H(counts/n)] + [H(counts/n) - log2(W)/n] + [log2(W)/n - R]. Checked against a log-gamma evaluation of W.
- Decode failures: a block with the wrong composition raises `CompositionError`, a symbol outside the alphabet or of non-integer dtype raises `InvalidSymbolError` (a `CompositionError`), a block of the right composition ranked at or above 2^k raises `RankOverflowError`. `try_decode` returns a typed failure, never bits. Profile: `docs/notes/ccdm_profile.md`.
