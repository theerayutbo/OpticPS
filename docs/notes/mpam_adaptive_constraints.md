# Generic adaptive selection and constraints (C4)

Scope: `optimization/adaptive.py` (generic path), `optimization/constraints.py`. Evidence labels: simulated. Nothing here is measured.

## What the optimiser claims

| Metric | Claim in code | Why |
|---|---|---|
| SMD | continuous optimum is global for the unquantised SMD objective, on this channel estimate | I(X;Y) is concave in P at a fixed channel; P is linear in the pair probabilities q; the box is convex |
| BMD | continuous optimum is the best of N = 11 starts | R_BMD is not shown concave; every start is logged (start q, final q, objective, iterations, status) |
| both | the selected PMF is the argmax of the exact quantised objective over the logged candidates | the matcher loss is a staircase in P, so the fit is on the continuous rate and the exact objective is re-evaluated at every endpoint, uniform and an MB grid |

No claim is made that the selected PMF maximises the staircase. On the simulated channels below all 11 starts end within 5e-13 bit of each other and 3e-7 in q, for SMD and BMD.

## Optimal PMFs (equal-sigma peak-limited AWGN, block 1024, seed 7)

q lists P(+-x_j), inner pair first. "cont" is the continuous optimum, "sel" the selected quantised candidate; objective = rate minus matcher loss, bit per symbol.

| M | PSNR | metric | cont q | cont rate | sel objective | uniform objective |
|---|---|---|---|---|---|---|
| 8 | 22 dB | SMD | 0.1043 0.1269 0.0678 0.2010 | 1.99584 | 1.96391 | 1.92245 |
| 8 | 22 dB | BMD | 0.1101 0.1108 0.0853 0.1939 | 1.97325 | 1.94119 | 1.90357 |
| 16 | 28 dB | SMD | 0.0575 0.0586 0.0558 0.0617 0.0497 0.0738 0.0267 0.1163 | 2.81203 | 2.75057 | 2.72042 |
| 16 | 28 dB | BMD | 0.0576 0.0578 0.0575 0.0568 0.0607 0.0559 0.0443 0.1094 | 2.77795 | 2.71668 | 2.68950 |

The optimum is outer-heavy but not Maxwell-Boltzmann: it is not monotone in |x| at M = 8 and 16. The PMFs are those of these channels, not a general result. With fitted (sampled) channels the optimum follows the estimation noise in the level means and sigmas.

## Runtime (Intel i5-8259U, Python 3.11.15, numpy 2.4.6)

One `optimise_symmetric` call with the full 11 starts, 1024-symbol block: M = 4 0.4 s; M = 8 1.8 to 3.0 s; M = 16 12.9 to 14.7 s with the common grid (unequal sigma), 20.7 to 23.0 s on exactly equal sigma (Gauss-Hermite, 240 nodes, is slower than the grid at M = 16). About 1300 to 1400 rate evaluations at M = 16. A single start at M = 16 takes about 1.3 s. The default test suite keeps M = 16 to a single start; the full M = 16 run is marked slow.

## Constraints, from the repository MZM model

At quadrature and a symmetric PMF the mean launched power is L P_laser / 2 whatever the PMF, so a fixed average-optical-power constraint is INACTIVE: it does not discriminate between symmetric PMFs. Off quadrature, or for an asymmetric PMF, it is active, and meeting it needs a laser-power change, reported in `adjustments` and never applied; it is FEASIBLE only if the protocol declared it (and within a declared limit). Fixed OMA equals fixed peak while the outer levels are used; it differs when they carry no mass, and then restoring OMA needs a larger swing ((M-1)/(M-3) for the outermost pair unused). Equal realised user rate adjusts the sample rate at fixed samples per symbol within 200 to 256 GSa/s; PS80 PAM4 against a uniform PAM4 target needs +16.4 %, above +14.3 %, so it is INFEASIBLE; PS70 needs +6.3 %.

## What this note does not say

Inner-heavy Maxwell-Boltzmann is not the average-optical-power optimum. The average-power constraint is a first-moment constraint on optical power; inner-heavy MB comes from an electrical second moment E[x^2] and, in this repository's models, wins only through mechanisms that favour inner levels (here a synthetic sine-compressed outer spacing at M = 8). At quadrature the constraint is inactive for the inner-heavy winner and for uniform alike, so it does not explain the win. The tests allow either outcome and assume no winner: in the sine-compressed M = 8 channel (sigma 0.8, g = 1.55) the best inner-heavy menu member beats uniform by 0.025 bit, and at fixed-peak AWGN (M = 8, 22 dB) the inner-heavy members lose by 0.178 and 0.340 bit (outer H288 wins by 0.007); at M = 4, 14 dB the outer-heavy member wins.
