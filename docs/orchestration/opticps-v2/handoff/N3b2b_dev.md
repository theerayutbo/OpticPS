# N3b-2b Dev handoff: fix round, C5 links and holdout runner (Amendment 13). Base 22b82da; no fit run, no data read.
Commits: f29734c Amendment 13 and pin move (plan and its test only); 23413bd code, tests, mutants; this handoff.
Not touched: nanf_fit.py, scripts/nanf_fit.py, fit tests, the stub study, nanf_scoring/import/freeze/benchmark. No real workbook opened.

## Files touched
- plan: Amendment 13 appended (L-A to L-D, L-Z); `tests/test_nanf_benchmark.py`: `PLAN_SHA256_AMENDMENT12`, new pin, Amendment 13 test
- `src/opticps/measurement/nanf_chain.py`: `declare_c5_links`, `declared_link`, `c5_link_key`, `_paper_link(wavelength_nm=...)`, one nested check
- `src/opticps/measurement/nanf_holdout.py`, `scripts/nanf_holdout.py`, `scripts/mutate_nanf.py`
- tests: new `test_nanf_n3b_c5.py` (35); edited `nanf_holdout_stub.py`, `test_nanf_n3b_holdout.py` (C5 data, new verdict wording)

## Amendment 13 choices
- Fig.1 row: "Cross-check, and a fibre input of the C5 links", set from the paper, never fitted; consequence: dispersion vs Fig.1(a) is not independent there
- Recipe: built at the holdout read from the pinned workbook (hash checked); per lambda 1460 to 1620: NANF 4.76, SSMF 4.53, D from Fig.1(a) by
  `WavelengthTable.at` (linear, no extrapolation) as the stated D at lambda, rest as the 1550 nm links, plus `LinkSpec(None, lambda)`; index = k
- C5 per rate and link by `score_c5` (ROP@NANF for NANF and B2B, ROP@SSMF as published); d and copy per D3.1; verdict only by `overall_verdict`
  (c1/c2 discriminating need d above tolerance and a passed gate; b2b_poor from the gate); copy C2 by `score_c2`, unbracketed listed
- Marker rule: marker and report committed at once after the run; script prints it unless refused; what it cannot stop is written (L-D)
- Replaced J-E.4 and `NOT RUN (links not declared)`: C5 is run; `INCOMPLETE: primary criterion C5 not run` withdrawn

## Holdout point count
237 at the stated axes: Fig.4 side 3 x (6 + 8 + 6 + 8) = 84, C5 side 3 x 17 x 3 = 153 (back-to-back run serves as the no-fibre run of d).

## Link check
`simulate_point` keeps its line `spec != LinkSpec() and spec not in DECLARED_LINKS.values()`; a nested test of the recipe registry follows it.
Behaviour for every earlier input is unchanged; the recipe registry is empty until `declare_c5_links` succeeds.

## Gates (tip: 23413bd plus this file)
- `tests/test_nanf*.py`: 729 passed, 0 failed, 0 skipped (383 s, one run at the last code edit); provenance guard, ruff, mypy: see the final report
- mutants (holdout side, chain side, script; selector logic of `mutate_nanf.py`): 73 of 73 killed: 11 new chain C5, 2 old chain
  (link-check line), 4 new script, 56 holdout (old and new; 4 old ones re-targeted: verdict, C2 discriminating, C5, link lookup)
- one survivor found on the first pass (C2 discriminating assumed): fixed by a test where only one of C1 and C2 discriminates, then killed
- equivalent, left out: `_RECIPE_LINKS.clear()` (the key set is fixed, so overwriting gives the same registry)
- existing chain mutants on the link-check line stay valid (the line is unchanged); old mutants on `verdict_text` were replaced, none left stale

## For the reviewer
- `declare_c5_links` trusts the hash the workbook object carries; a hand-built object is outside the guarantee (L-B.8, class of H-F)
- A link at 1630 or 1640 nm cannot even be built (the stated D has a band to 1625 nm); a LinkSpec forced there raises on resolve
- C5 NANF `d` is reported and labelled but is not in the verdict (A2, B3.3 name C1 and C2); stated in L-C.2
- Stopped on: nothing. Importer metadata gave one Fig.1(a) curve per fibre, one ROP column per link, one Fig.6 series per link.
