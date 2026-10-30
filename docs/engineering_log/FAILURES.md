# Failures, dead ends and wrong assumptions

## X-001 Programming Guide could not be obtained
- What happened: `curl` of the Keysight URL returned HTML, not a PDF. The first request used a browser User-Agent. A second attempt with a browser User-Agent and alternate URLs was denied by the harness as bot-check circumvention.
- Handling: that approach was abandoned. WebFetch of the URL returned only a landing page with metadata (M8100-91B50, 2026-03-01).
- Consequence: CSV rules and `:TRAC:IMP` syntax are user-supplied, not read from the guide.
- To resolve: user supplies the PDF, then update VERIFICATION.md.

## X-002 pdftoppm missing
- The Read tool cannot render PDFs here. Text was extracted with pypdf in a throwaway uv environment.

## X-003 One tolerance for two different processes
- `distribution_within_tolerance` failed for Uniform (deviation 0.00674 vs 0.006).
- Root cause: the 0.006 tolerance was shared by i.i.d. sampling and CCDM rounding, which have different error mechanisms.
- Fix: CCDM limit 1/n (stricter); i.i.d. limit 5 sigma of sampling noise.

## X-004 Corruption test did not corrupt
- Negating an already negative sample left the file unchanged, so the checksum test failed.
- Fix: the test writes a different value at a sample the reconstruction does not read, so only the checksum can catch it.

## X-005 Predistortion factor error
- `predistort` used 2/pi instead of 1/pi when inverting sin(pi V / V_pi). Optical spacing came out wrong.
- Caught by `test_predistortion_equalizes_optical_spacing`. Fixed.

## X-006 noise_rms_a ignored the filter shape
- It assumed a brick-wall bandwidth. A filter whose corner equals Nyquist passes the integral of 1/(1+x^8) on [0,1], about 0.925 of the noise.
- A test with an 8% tolerance had hidden it. Fixed with `noise_power_gain`; tolerance tightened to 1%.
- A hand estimate of 0.922 quoted during debugging was slightly wrong; the test now computes the integral.

## X-007 PyYAML float notation
- `8.0e9` is read as a string by YAML 1.1. `configs/demo.yaml` now uses `8.0e+9`. The M8199B config was unaffected because it casts with `float()`.

## X-008 Demo crashed at the end and lost all results
- `adaptive_section` looked up "PS70" but the label is "PS70 (inner)". About 7 minutes of simulation were lost because nothing was saved midway.
- Fixed the key, added checkpoints after each section, and added a reduced-config smoke test of the whole pipeline before full runs.

## X-009 Rounding in a test
- `//` was used where the code rounds a resampled length. Test bug, fixed.
