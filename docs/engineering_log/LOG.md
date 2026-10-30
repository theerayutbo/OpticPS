# Engineering log (append-only)

## 2026-10-30 | Phase 0 (pre-build, backfilled) | commit: none yet

Goal: understand the task and check the science before writing code.

Actions and results:
- Inspected `~/Documents/Optics`: only `2005.12428v2.pdf` and `.omc/`. `~/Documents/Optic` does not exist.
- Toolchain: Python 3.14.3 system, uv 0.11.1, Python 3.11 available. No pandoc, LaTeX, LibreOffice or poppler. `gh` logged in as `theerayutbo`; repo `OpticPS` absent. No global git identity.
- Background repo licences via GitHub API: OptiCommPy GPL-3.0; Probabilistic_Constellation_Shaping none; PAM4Receiver NOASSERTION; OpticalSimulation MIT. Their code was not opened.
- Read Wiegart et al. in full (text extracted with pypdf). It shows the optimum under fixed Vpp/ER is outer-heavy, the inverse of the requested PS70/PS80.
- Ran `scripts/prebuild_rate_check.py` (Gauss-Hermite, 80 nodes). Result in FINDINGS F-001.
- Rough CCDM cost: exact multinomial for n=65536 has 123268 bits; 65536 rank-walk steps took 1.32 s in CPython.
- Fable design review (independent recomputation by trapezoid integration, literature and licence check). Confirmed F-001; verdicts in DECISIONS. It ran before the M8199B was confirmed, so its 40 GSa/s objection does not apply.
- User decisions: copyright holder Theerayut Boonkird; project root `~/Documents/Optics`.
- M8199B update received. Profile arithmetic checked: 917504 = 1792×512; 262144 = 512×512; both ≤ 1048576.
- Keysight checks: see VERIFICATION.md and FAILURES X-001.

Next: Phase 1 scaffold.

## 2026-10-30 | Phases 1-3 | commit: this commit

Goal: scaffold, licence audit, modulation, shaping, CCDM, rates.

Commands: `uv sync`; `uv run python scripts/license_audit.py`; `uv run --no-dev --isolated python scripts/license_audit.py`; `uv run pytest tests/test_core.py`.

Results:
- Licence audit: 33 packages with dev, 21 runtime, 0 flagged. `pathspec` is MPL-2.0, dev-only. SBOM at docs/sbom.cdx.json from the runtime set.
- tests/test_core.py: 51 passed in 52.74 s.
- Rates and CCDM table (deterministic, no seed needed):

```
uniform PSNR@1bpcu smd 13.692 bmd 13.854
outer70 gain smd 0.727 bmd 0.627
P0*(bmd@design) (0.36999999999999983, 1.0681240902412985)
10 (0.4949999999999998, 0.7918700134411034)
12 (0.43249999999999983, 0.9308287423932722)
14 (0.3624999999999998, 1.102138587773097)
16 (0.31999999999999984, 1.304936247499706)
18 (0.28749999999999987, 1.526939978972587)
20 (0.2674999999999999, 1.7391117267457326)
22 (0.2574999999999999, 1.8962855262190836)
24 (0.2524999999999999, 1.9750371390623886)
64 PS70 (10, 22, 22, 10) 112 rate 1.75000 loss 0.14604
64 PS80 (6, 26, 26, 6) 100 rate 1.56250 loss 0.13371
256 PS70 (38, 90, 90, 38) 468 rate 1.82812 loss 0.04931
256 PS80 (26, 102, 102, 26) 431 rate 1.68359 loss 0.04454
1024 PS70 (154, 358, 358, 154) 1912 rate 1.86719 loss 0.01506
1024 PS80 (102, 410, 410, 102) 1747 rate 1.70605 loss 0.01431
4096 PS70 (614, 1434, 1434, 614) 7687 rate 1.87671 loss 0.00434
4096 PS80 (410, 1638, 1638, 410) 7037 rate 1.71802 loss 0.00430
65536 PS70 (9830, 22938, 22938, 9830) 123267 rate 1.88091 loss 0.00037
65536 PS80 (6554, 26214, 26214, 6554) 112826 rate 1.72159 loss 0.00036
```

Surprises: none; gains matched the paper within test tolerance on the first run.

Next: Phase 4, M8199B export and validator.

## 2026-10-30 | Correction to the Phases 1-3 entry

"Surprises: none" was wrong. Two planning figures were corrected by the computed results:
- At the declared design point (13.854 dB, uniform R_BMD = 1.0), P0* for BMD is about 0.37, not 0.40. The value 0.40 belongs to the lower PSNR at which the optimized distribution itself reaches 1.0 bpcu.
- PS70 rate loss at n=1024 is 0.015 b/sym, not 0.014.

## 2026-10-30 | Phase 4 M8199B export | commit: this commit

Goal: real waveform files, references, manifest, independent validator.

Commands: `uv run pytest tests/test_export.py`; generation through `generate_all(configs/m8199b_profiles.yaml, output/keysight_m8199b)`; `validate_profile` per profile.

Results (seed 42):
- Tests: 23 passed. Generation 11.5 s. Validation: 115 of 115 checks passed for each profile.
- Adaptive selection: P0=0.375, lambda=-0.13733, objective 1.0541 bit/use, on simulated AWGN training at PSNR 13.854 dB. Outer-heavy, as theory predicts. Label: simulation-optimized.
- Profile A net payload rates: Uniform 15.50, PS70 14.47, PS80 13.22, Adaptive 13.93, Outer70 14.47 Gbit/s. Shaping lowers net rate at equal baud.
- Common scale 0.333333333; all peaks 1.0. RMS: Uniform 0.7499, PS70 0.6203, PS80 0.5439, Adaptive 0.8819, Outer70 0.8564.
- Uniform mean 2.8e-4; CCDM waveforms mean below 1e-18.
- Sizes: Profile A CSV about 11.5 MB each; output/ total 76 MB; no file over GitHub's 100 MB limit.

Failures: FAILURES X-003, X-004.

Next: Phases 5-8, receiver, channel, statistics, ingest.

## 2026-10-30 | Phases 5-8 | commit: this commit

Goal: receiver, link, statistics, ingest, mock receiver, protocols, CLI, docs.

Commands: `uv run pytest tests/test_core.py tests/test_rx_channel.py tests/test_export.py tests/test_ingest.py`; `uv run ruff check`; `uv run mypy`.

Results: 129 tests passed; mypy clean on 36 source files. Gates covered: analytic PAM4 SER inside the 99.9% interval; MAP beats minimum distance for shaped input; GMI within 0.03 of analytic; sync at random offset and inverted polarity; CD null at 19.2 GHz for 10 km; shot variance within 1%; thermal slope 2 dB/dB; 200 fuzzed metadata cases rejected; end-to-end through the mock receiver.

Note: the plan's GMI gate was 0.01 bit. The test uses 0.03 with six frames; this is looser than planned and is recorded here so it is not mistaken for the plan's gate.

Failures: X-005 to X-009.

Next: full demo run, report, slides, independent review.

## 2026-10-30 | Correction to the Phases 5-8 entry

The GMI test was tightened back to the planned 0.01 bit and passes for Uniform, PS70 and Outer70.

## 2026-10-30 | Phase 9-10 v1.0 review and final run | commit: this commit

Reviews:
- Grok, read-only: returned no findings (stopped after its opening sentence, exit 0). Not counted as a review.
- Sonnet Loki: PASS, no blockers, 11 minor findings. It recomputed the 14 dB rates by scipy quad, and one report row from results.
- Fable was used once, for the pre-build design review. By user instruction it is not used as a worker afterwards. The plan's Fable review of Phase 10 was replaced.

Changes from review: Uniform priors no longer come from the payload; paired comparisons need 5 runs; `target_is_requested` check with independent targets; RRC reconstruction is actually tested; preamble correlation is reported; the "held-out" and interval wording in the report is corrected; slide picture bounds; the 4 dB statement.

Final simulated results, seed 42, config e39084adac9d, version 1.0.0, runtime 288 s, 8 runs:
- Profile A near -22.01 dBm, R_BMD versus Uniform: PS70 -0.150 [-0.151,-0.147], PS80 -0.267 [-0.270,-0.264], Adaptive +0.036 [0.033,0.039], Outer70 +0.041 [0.037,0.045].
- Profile B near -19.01 dBm: PS70 -0.141, PS80 -0.236, Adaptive +0.093 [0.090,0.097], Outer70 +0.081 [0.078,0.084].
- Point adaptation versus Outer70: +0.018 at 26 dB; unresolved +0.001 [-0.001,0.003] at 25 dB; +0.107 at 21 dB, where it selects uniform.
- Validation: 119 of 119 per profile. Waveform CSVs byte-identical before and after review changes.

## 2026-10-30 | Official guides obtained

M8100 Programming Guide (146 pages) and UXR Programmer's Guide (2156 pages) were fetched with a plain curl client, no altered User-Agent, from Keysight's public www.keysight.com/nz/ asset URLs, which served the PDFs directly. Text was extracted locally. The PDFs are not committed.

Result: the exported waveform CSV format is confirmed against pp129-133: mandatory first row DataOut1, normalized floats within -1 to +1, `:TRAC:IMP` syntax, segment id 1. Not found in that guide: 512-sample granularity, 1,048,576 maximum, M8199B AC coupling. Playback remains unverified. The rows in VERIFICATION.md and HARDWARE_COMPATIBILITY.md are updated on branch v1.2-uxr.
