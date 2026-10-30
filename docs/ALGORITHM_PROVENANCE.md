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
