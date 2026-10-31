# UXR capture comparison

Data sources: simulated. 4 test and 0 training captures; training captures are never scored.

## Captures

- mock-PAM4_Adaptive-r1 (A_initial_8GBd PAM4_Adaptive, run r1): SER 11 errors in 126976 symbols, rate 8.66e-05 (95% interval 4.32e-05 to 0.000155); 4 frames repeat the same 31744 payload symbols; 4 frames analysed, 0 lost.
- mock-PAM4_Fixed_PS70-r1 (A_initial_8GBd PAM4_Fixed_PS70, run r1): SER 10 errors in 126976 symbols, rate 7.88e-05 (95% interval 3.78e-05 to 0.000145); 4 frames repeat the same 31744 payload symbols; 4 frames analysed, 0 lost.
- mock-PAM4_Fixed_PS80-r1 (A_initial_8GBd PAM4_Fixed_PS80, run r1): SER 12 errors in 126976 symbols, rate 9.45e-05 (95% interval 4.88e-05 to 0.000165); 4 frames repeat the same 31744 payload symbols; 4 frames analysed, 0 lost.
- mock-PAM4_Uniform-r1 (A_initial_8GBd PAM4_Uniform, run r1): SER 12 errors in 126976 symbols, rate 9.45e-05 (95% interval 4.88e-05 to 0.000165); 4 frames repeat the same 31744 payload symbols; 4 frames analysed, 0 lost.

## Paired comparisons (R_BMD), one per condition

Captures share a condition when profile matches and attenuation and fiber length agree within 0.1 dB and 0.001 km (values are rounded to these before grouping).

- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Adaptive vs PAM4_Fixed_PS70: insufficient paired runs (need 5), 1 runs.
- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Adaptive vs PAM4_Fixed_PS80: insufficient paired runs (need 5), 1 runs.
- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Adaptive vs PAM4_Uniform: insufficient paired runs (need 5), 1 runs.
- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Fixed_PS70 vs PAM4_Fixed_PS80: insufficient paired runs (need 5), 1 runs.
- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Fixed_PS70 vs PAM4_Uniform: insufficient paired runs (need 5), 1 runs.
- A_initial_8GBd, attenuation 18.4 dB, fiber 0 km: PAM4_Fixed_PS80 vs PAM4_Uniform: insufficient paired runs (need 5), 1 runs.

## Fairness audit (all test captures)

| Variable | Role | Status | Range |
|---|---|---|---|
| Symbol rate | set-point | controlled | 8e+09 to 8e+09 |
| Capture sample rate | set-point | controlled | 8e+10 to 8e+10 |
| AWG sample rate | set-point | controlled | 2.24e+11 to 2.24e+11 |
| Electrical amplitude | set-point | controlled | 2 to 2 |
| Optical launch power | measured | reported | 2.98939 to 2.98978 |
| Optical received power | measured | controlled | -15.4106 to -15.4102 |
| Optical modulation amplitude | measured | reported | 4.72564 to 4.72696 |
| Extinction ratio | measured | reported | 8.37097 to 8.37209 |
| Fiber length | set-point | controlled | 0 to 0 |
| Attenuation | set-point | controlled | 18.4 to 18.4 |
| Receiver bandwidth | set-point | controlled | 8e+09 to 8e+09 |

Frames repeat the same payload, so pooled symbols are not independent data. A lower error rate or symbol energy is not a throughput gain.
