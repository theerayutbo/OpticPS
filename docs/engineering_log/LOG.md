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
