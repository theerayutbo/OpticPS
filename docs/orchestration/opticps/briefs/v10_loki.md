You are an independent reviewer of OpticPS v1.0 at this repository's working tree. You did not write it. Read-only: do not modify anything. Do not trust the docs: re-derive from code.

Focus on load-bearing science and honesty. Read src/opticps/optimization/rates.py, distribution_matching/ccdm.py, transmitter/export.py, measurement/validate_export.py, receiver/dsp.py, optical_channel/link.py, measurement/demo.py, measurement/compare.py, reporting/facts.py, reporting/report.py.

Hunt for: wrong equations; PSNR or noise-scale mistakes (unipolar spacing 1 versus bipolar spacing 2); priors or MAP errors; R_BMD estimate bias; any payload data leaking into calibration, FFE or likelihood fits; paired-seed mistakes; CI misuse; conclusions in report text stronger than the data; validator checks that cannot fail; claims in README.md or output/README_SOUTHAMPTON.md that the code does not support; anything that could damage hardware.

Output, under 40 lines: verdict PASS or FAIL, then numbered findings, each with severity (blocker, major, minor), file:line, and a concrete failure scenario. Report only what you verified.
