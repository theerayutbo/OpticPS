# Decision records

## D-001 Keep PS70/PS80, add an outer-heavy benchmark
Context: F-001 shows the requested distributions are expected to lose under fixed Vpp.
Choice: generate the four requested files unchanged and add `benchmark/PAM4_Fixed_Outer70.csv`.
Why: the user asked for those files, and comparing against the literature optimum makes the result interpretable.
Overturned by: measurements showing level-dependent impairments that favour inner-heavy distributions.

## D-002 Adaptive searches the whole symmetric family
Choice: P0 in (0, 0.5), covering λ<0 and λ>0.
Why: λ≥0 alone excludes the known optimum and would bias the result.
Evidence: Fable: P0* is never below 0.25 in the peak-limited AWGN model.

## D-003 Declared adaptive design point
Choice: the PSNR at which uniform reaches R_BMD = 1.0 bpcu. Report the complete P0*(PSNR) curve.
Why: no measured SNR exists. Label: simulation-optimized.
Overturned by: Southampton training captures.

## D-004 Exact enumerative CCDM, n=1024
Choice: exact ranking of the constant-composition set. 1024-symbol blocks.
Why: exact and reversible; rate loss 0.014 b/sym for PS70; enough blocks for block statistics.
Limitation: one symbol error destroys a block; no FEC exists.

## D-005 Total symbol count fixed by profile
Choice: preamble 512 + training 512 + payload blocks. A 32768, B 65536.
Why: M8199B sample counts must match the expected figures.

## D-006 Data-independent full scale
Choice: full scale = 3·Σ|g|, shared across files of a profile and pulse shape.
Why: nothing clips, and level-to-volts is common, so fixed-Vpp comparison holds.

## D-007 No FEC, no PAS label
Choice: pluggable interface only. Primary metrics are SER, label BER, R_SMD, R_BMD.
Why: a toy code would add a false claim; the AIRs already price the overheads.

## D-008 Fixed nine-decimal CSV
Choice: `%.9f`, canonical samples are the rounded values.
Why: exact readback, deterministic hashes, consistent decimal format, smaller files than `%.17g`.

## D-009 Project root and identity
Choice: `~/Documents/Optics` by user decision; repo-local noreply git identity.
Why: the folder is the user's answer; no global identity exists and the account email must not be published.
