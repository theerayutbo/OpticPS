# C4 QA second review (Loki): PASS, with MINORs
verified_sha: d9ba0161a1234238c1fd9cba03116012afce03fe (branch tip, child of 2b9e1fe; detached worktree, imports confirmed there, since removed)
Gate: 698 passed incl. anchor (698 collected, ran to 100 % under -x; summary line hidden because I also passed -q); ruff check, ruff format --check, mypy clean. Clean room kept.

## A. Prior findings: all closed
1. Floor: re-applying 1/(4n) gives 0/11 endpoints, M=8 16 dB BMD 1.1545; at 1/n 11/11, 1.2652. All 26 sweep runs 11/11, and every note table row and floor pair list matches.
2. Uniform direct: own Simpson integrator and exact multinomial reproduce M=8 22 dB SMD 1.95468, shaped 1.96391, +0.00923; BMD +0.00539; M=16 28 dB SMD -0.03137; BMD -0.03434. Evaluated at realised counts/n the deltas move under 1e-5.
3. Hash: renamed capture with made-up hash and hash of other bytes both refused, in assert_independent and select_on_acquisitions.
4. best_fixed: test split and bare channel refused. 5. FixedOMA 0.9202 V; factors 3, 1.4, 15/13 exact. 6. Claim strings correct at multistart_check=False.
7. Prior survivors agreement tol 1e9, clipped bmd fit, ignored in_bounds all now killed. 8. M=4 own scan: no win for g<=2.2; g=2.6 sigma 2, 3: 0.0122, 0.0543 BMD. 9-10. 6.3e-13 bit and 2.7e-7 q hold (measured 6.2e-13, 2.7e-7); PAM16 gain and loss numbers hold.

## B. New code: confirmed sound
- Floor: 135000 fuzzed q at M=4, 8, 16, n=M to 65536, at and 1e-10 under the floor: no zero count, sum always n. n=M and n=M+2 run; n<M refused. Sweeps n=64 to 2048: 11/11 feasible everywhere.
- SMD KKT with own divergences, all floor-active channels: free pairs equal, floor pairs below (margin 4e-5 to 0.27), so "global over the constrained set" is true. Selected beats the MB fallback at all 26 points.
- Direct: tolerance 1e-12 harmless; a PMF 2e-12 off uniform that merely quantises to uniform pays CCDM (conservative). select_distribution unchanged, 0.0146484375 confirmed; committed selection p_outer=.375 still beats direct uniform (+0.0534, was +0.0681), so no README or report statement changes.
- PS80 1747 bits +17.2 %, PS70 1912 bits +7.1 %, own enumeration. g=1.8 sigma=.8 +0.075 BMD, outer -0.27, win counts 5, 7, 2: reproduced. Means monotone there, fold-over only in levels past the peak: physics text right.
- Hash bypasses: mutation, subclass, byte order, bad hash in held-out all caught. Old LOG entries annotated, not silently rewritten.

## Findings (no BLOCKER or MAJOR)
1. MINOR: FixedOMA false reason. Outer pair unused, target_oma_w equal to current OMA: INACTIVE, "the extreme levels are in use". Same class as prior 5. Repro: p=[0,.5,.5,0], FixedOMA(target_oma_w=oma_w(cfg,p)).
2. MINOR: FixedOMA false INFEASIBLE, two edges. (a) Target under OMA at the first grid point: values[0]>=0 so no crossing; 1e-4 x OMA says no swing reaches it, quoting a larger reachable OMA (the grid omits swing 0). (b) M=16 outer unused, target = analytic peak at 4.6154 V: INFEASIBLE, peak falls between grid points, no tolerance. M=4, 8 peaks sit on the grid and pass.
3. MINOR: 5 of 27 new mutants survive (non-slow tests; BASELINE control green; first run discarded, harness fault). range tol 1e-3 and lower-edge tol removed: tolerance has no outside-edge negative test (1e-9 itself is not a bug: 256.000000128 GSa/s FEASIBLE, 256.000000384 INFEASIBLE, under 1 ppb, but far above float rounding). drop _assert_unique in _training_channel: duplicates untested through best_fixed. floor_active_selected_pairs untested (differs from continuous at M=16 n=256 22 dB: [2,5,6] vs []). crossing[-1] is equivalent (one upward crossing). 22 killed.
4. MINOR: note says g=1.8 sigma=.8 was "found by the scan, not chosen for a claim". Selection is disclosed, but it was picked after the scan, a test pins it, and sigma .8 is that g row's maximum; the 0.075 is BMD only (SMD +0.0508), metric implied.

## Observations
5. BMD starts really disagree on the sweep: 5e-2 bit M=8 14 dB, 5e-2 M=16 22 dB, 2e-2 M=16 20 dB, 2e-3 M=16 14 dB (q gap .1-.2). "Best of N" stays honest and the agreement claim is scoped to 22/28 dB, but the sweep table is silent, and M=16 22 dB BMD is in it.
6. Objective is rate(P) - loss, not rate(counts/n): gap reaches 2.5e-4 bit at floor-active BMD (M=8 n=512 12 dB), not the 7e-6 reported before; no sign change seen.
7. Split label is declared: a test capture relabelled training with its true hash passes best_fixed, and select_on_acquisitions if omitted from held_out. Docstring states this; selected_on still reads "split ... checked". One edited index on test received also passes (documented class). Float indices truncate in content_digest (1.4 hashes as 1) and digest has no field boundary: no leak found. optimise_symmetric and evaluate_menu still take a bare channel, with no training label; BestFixed can be built directly.
8. "mb_outer_H288 endpoint" is an optimised endpoint started there (q .1043 .1269 .0678 .2010), not the H288 menu PMF (.0750 .0891 .1256 .2104); all 11 share one composition, the name is a tie-break at 1e-13.
9. PAM16 "0.101 bit" at 45 dB is single-start; full multistart gives 0.0615. Note does not say which.
10. frame.py direct_uniform is hardcoded to 2 bits per symbol; "as frame.py does" at M=8, 16 is a C5 promise. _argmax_menu ignores in_bounds, so a menu entry with q<1/n is selectable. Deviation 7 covers committed output; compare.py still calls select_distribution on training captures, so the charged uniform can affect future selection when the margin is under 0.0146.
Process: one stray copy of adaptive.py went to /tmp/x, an existing empty directory, and was removed; nothing overwritten.
