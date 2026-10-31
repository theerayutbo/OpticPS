# Generic adaptive selection and constraints (C4)

Scope: `optimization/adaptive.py` (generic path), `optimization/constraints.py`. Evidence labels: simulated. Nothing here is measured.

## What the optimiser claims

Every optimum is an optimum over the constrained set q_j in [1/n, 1/2] (n the block length), not over the whole simplex. The lower bound 1/n is a decision that neither PLAN nor the roadmap states (they give no bound; see docs/ROADMAP_STATUS.md). It is the smallest probability that can quantise to a nonzero count. An earlier floor of 1/(4n) put the optimum at a probability that quantises to a zero count, so every endpoint was infeasible over most of the sweep and selection fell back to a Maxwell-Boltzmann grid. The selection reports the pairs at the floor (`parameters["floor_active_pairs"]`, and in the claim text). Reproduced at this commit by setting the floor back to 1/(4n): 0 of 11 endpoints feasible in each of 9 runs (M = 8 SMD 8 to 18 dB in 2 dB steps; M = 16 SMD 10 and 22 dB, BMD 22 dB).

| Metric | Claim in code | Why |
|---|---|---|
| SMD | continuous optimum is global for the unquantised SMD objective over the constrained set, on this channel estimate | I(X;Y) is concave in P at a fixed channel; P is linear in the pair probabilities q; the set q_j >= 1/n, sum q_j = 1/2 is convex, so concavity holds on it |
| BMD | continuous optimum is the best of N = 11 starts | R_BMD is not shown concave; every start is logged (start q, final q, objective, iterations, status) |
| both | the selected PMF is the argmax of the exact quantised objective over the logged candidates | the matcher loss is a staircase in P, so the fit is on the continuous rate and the exact objective is re-evaluated at every endpoint, uniform and an MB grid |

No claim is made that the selected PMF maximises the staircase. On the four simulated channels below all 11 starts end within 6.3e-13 bit of each other and 2.7e-7 in q (SMD and BMD, measured at this commit).

The uniform candidate is the direct (unshaped) mapping: at M a power of two it maps bits straight onto labels (`frame.py` `direct_uniform`) and pays no matcher loss, so its objective is its rate. The candidates, `evaluate_menu`, `fixed_menu`, `best_fixed` and every gain below charge uniform 0. The legacy `select_distribution` (the committed v1.x PAM4 result) is not changed and still charges its uniform member the CCDM loss (0.0146484375 bit at n = 1024, which is 2 - 2033/1024). This is a known limitation of that committed result and is left in place because the legacy output is pinned byte for byte.

## Optimal PMFs (equal-sigma peak-limited AWGN, block 1024, seed 7)

q lists P(+-x_j), inner pair first. "cont" is the continuous optimum, "sel" the selected candidate, "uniform" the direct uniform at zero matcher loss, "best shaped" the best non-uniform quantised candidate. Objective = rate minus matcher loss, bit per symbol.

| M | PSNR | metric | cont q | cont rate | selected | sel objective | uniform | best shaped | shaped - uniform |
|---|---|---|---|---|---|---|---|---|---|
| 8 | 22 dB | SMD | 0.1043 0.1269 0.0678 0.2010 | 1.99584 | mb_outer_H288 endpoint | 1.96391 | 1.95468 | 1.96391 | +0.00923 |
| 8 | 22 dB | BMD | 0.1101 0.1108 0.0853 0.1939 | 1.97325 | mb_outer_H288 endpoint | 1.94119 | 1.93579 | 1.94119 | +0.00539 |
| 16 | 28 dB | SMD | 0.0575 0.0586 0.0558 0.0617 0.0497 0.0738 0.0267 0.1163 | 2.81203 | uniform | 2.78194 | 2.78194 | 2.75057 | -0.03137 |
| 16 | 28 dB | BMD | 0.0576 0.0578 0.0575 0.0568 0.0607 0.0559 0.0443 0.1094 | 2.77795 | uniform | 2.75102 | 2.75102 | 2.71668 | -0.03434 |

At M = 8, 22 dB the best fixed member is the direct uniform (not Outer_H288, which an uncorrected comparison named), so the adaptive gain over best fixed is +0.00923 (SMD) and +0.00539 (BMD). At M = 16, 28 dB the adaptive selection IS the direct uniform: shaped candidates lose 0.031 and 0.034 bit to it. The continuous optimum is above uniform in rate (2.81203 against 2.78194 SMD), but no quantised composition keeps that gain at n = 1024. The floor is not active at any of these four optima.

The optimum is outer-heavy but not Maxwell-Boltzmann: it is not monotone in |x| at M = 8 and 16. The PMFs are those of these channels, not a general result. With fitted (sampled) channels the optimum follows the estimation noise in the level means and sigmas.

## Endpoints over the sweep (the floor 1/n)

Equal-sigma peak-limited AWGN, n = 1024, seed 7, 11 starts. With the floor 1/n all 11 endpoints were feasible at every point of M = 8 8 to 18 dB and M = 16 10 to 22 dB, SMD and BMD (12 + 14 = 26 runs). "Fallback" is the best MB-grid candidate, which is what selection was reduced to when no endpoint was feasible. "Selected" is the objective of the selected candidate; the uniform at zero loss is given for reference.

| M | metric | dB | selected | fallback | uniform | floor active at pair(s) |
|---|---|---|---|---|---|---|
| 8 | SMD | 8 | 0.6249 | 0.5655 | 0.3710 | 0 1 2 |
| 8 | SMD | 12 | 0.9166 | 0.8887 | 0.7037 | 1 2 |
| 8 | SMD | 16 | 1.2936 | 1.2260 | 1.1521 | 2 |
| 8 | SMD | 18 | 1.5000 | 1.4445 | 1.4066 | 2 |
| 8 | BMD | 8 | 0.6103 | 0.4947 | 0.3094 | 1 |
| 8 | BMD | 16 | 1.2652 | 1.1545 | 1.0610 | 1 2 |
| 8 | BMD | 18 | 1.4651 | 1.3805 | 1.3333 | 1 |
| 16 | SMD | 10 | 0.7661 | 0.6718 | 0.4763 | 0 to 6 |
| 16 | SMD | 16 | 1.2826 | 1.1653 | 1.0879 | 0 2 3 4 5 6 |
| 16 | SMD | 22 | 1.9554 | 1.8692 | 1.8884 | 2 5 6 |
| 16 | BMD | 10 | 0.7276 | 0.5451 | 0.3969 | 1 2 3 5 |
| 16 | BMD | 22 | 1.8949 | 1.7615 | 1.7694 | 1 2 5 6 |

The floor is active at the continuous optimum at low and moderate PSNR: the unconstrained optimum would give some levels less than one symbol per block, i.e. leave them unused. The result there is an optimum of the constrained set, not of the simplex. The M = 8 16 dB BMD point (1.2652 against 1.1545) and its pair indices are asserted in `tests/test_mpam_adaptive.py`.

## Negative case: PAM16 at high PSNR

PAM16, 36, 40 and 45 dB, sigma wobble 0.02, SMD, n = 1024: the direct uniform is selected (L1 distance 0 from uniform). The unquantised gain of the continuous optimum over uniform is 2.1e-4, 1.5e-7 and 0 bit. Every non-uniform candidate is a quantised composition and pays a matcher loss of 0.0526 to 0.0622 bit (19, 19 and 18 feasible shaped candidates), so the best of them is 0.062, 0.062 and 0.101 bit below the uniform. What is measured is therefore: shaping gains almost nothing here, and any shaped composition at n = 1024 costs about 0.05 bit that the direct uniform does not pay. (An earlier text said "matcher loss exceeds the continuous gain", with a uniform that was itself charged a matcher loss; that comparison does not hold as written.)

## Runtime (Intel i5-8259U, Python 3.11.15, numpy 2.4.6)

One `optimise_symmetric` call with the full 11 starts, 1024-symbol block, measured at this commit: M = 8 about 3 s; M = 16 13.7 s (SMD, 1265 rate evaluations) and 14.9 s (BMD, 1391) with the common grid on an unequal-sigma channel (sigma wobble 0.02), 20 to 22 s on the equal-sigma M = 16 28 dB channel above (Gauss-Hermite, 240 nodes, is slower than the grid at M = 16). A single start at M = 16 takes about 1.3 s. The default test suite keeps one M = 16 test to a single start; the full M = 16 runs are marked slow.

## Constraints, from the repository MZM model

At quadrature and a symmetric PMF the mean launched power is L P_laser / 2 whatever the PMF, so a fixed average-optical-power constraint is INACTIVE: it does not discriminate between symmetric PMFs. Off quadrature, or for an asymmetric PMF, it is active, and meeting it needs a laser-power change, reported in `adjustments` and never applied; it is FEASIBLE only if the protocol declared it (and within a declared limit).

Fixed OMA equals fixed peak while the outer levels are used; it differs when they carry no mass, and then restoring OMA needs a larger swing ((M-1)/(M-3) for the outermost pair unused). A declared target below the current OMA needs a smaller swing: OMA rises with the swing up to a first maximum and then folds over, and the reported swing is the smallest one, on that first rising branch. For uniform PAM4 and a target of half the OMA at 2 V this is 0.9202 V (the fold-over solution of the same equation is 7.0798 V and is not reported). A target above the largest OMA any swing up to 2 V_pi reaches is INFEASIBLE even with the rescale declared, and the reason quotes that largest OMA.

Equal realised user rate adjusts the sample rate at fixed samples per symbol within 200 to 256 GSa/s. The target is the direct uniform (2 bits per symbol, 2048 bits per 1024-symbol block, which is what `direct_uniform` sends). PS80 PAM4 carries 1747 bits per block and needs +17.2 % (above +14.3 %, so INFEASIBLE); PS70 carries 1912 and needs +7.1 %. Against a CCDM-matched uniform (2033 bits per block, not what the repository's uniform sends) these were +16.4 % and +6.3 %, which was the wrong baseline.

## What this note does not say

Inner-heavy Maxwell-Boltzmann is not the average-optical-power optimum. The average-power constraint is a first-moment constraint on optical power; inner-heavy MB comes from an electrical second moment E[x^2] and wins only through mechanisms that favour inner levels. At quadrature the constraint is inactive for an inner-heavy winner and for uniform alike, so it does not explain a win. The tests allow either outcome and assume no winner.

Inner-heavy against the direct uniform, over a declared scan. Channels: quadrature-MZM-like level means m = sin(g a) / sin(g) (M - 1), a = level / (M - 1), equal sigma; g in {0.6, 1.0, 1.3, 1.55, pi/2, 1.8, 2.2, 2.6} and sigma in {0.15, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 3.0} (64 channels per M and metric); block 1024; the `fixed_menu` members (inner-heavy: H288/H272 at M = 8; PS70 and PS80 at M = 4).

- M = 8: at g = 1.55, sigma = 0.8, the best inner-heavy member is 0.0075 bit BELOW the direct uniform. An earlier note said it beat uniform by 0.025 bit; that came from charging the uniform a CCDM loss it does not pay, and it is withdrawn. Over the whole scan (BMD) inner-heavy beats the direct uniform in no channel with g <= pi/2, in 5 of 8 at g = 1.8, 7 of 8 at g = 2.2 and 2 of 8 at g = 2.6. The smallest drive gain at which it wins is 1.8 (means still monotone, outermost spacing compressed to under a tenth of the inner spacing). In that channel (g = 1.8, sigma = 0.8, found by the scan, not chosen for a claim) the best inner-heavy member beats the direct uniform by 0.075 bit and the best outer-heavy member loses 0.27 bit. The test asserts the scan result for each g (no win at or below pi/2; the win list above) and the 0.075 bit margin.
- M = 4 (PS70, PS80), both metrics: inner-heavy never beats the direct uniform for g <= 2.2 in any of the 8 sigmas. It does at g = 2.6, sigma = 2.0 and 3.0 (the overdriven class, means folded over: the outermost mean lies below the next): 0.0122 and 0.0543 bit (BMD). The earlier statement "compressed outer spacing never made inner-heavy win at M = 4" is replaced by exactly this: true over this scan except in the overdriven class, where an earlier counterexample (g = 2.6, sigma = 2) gave 0.026 bit against a CCDM-charged uniform and gives 0.0122 bit against the direct uniform. Other mean shapes were not scanned.
- At fixed-peak AWGN (M = 8, 22 dB) the inner-heavy members lose to the direct uniform; at M = 4, 14 dB the outer-heavy member wins.
