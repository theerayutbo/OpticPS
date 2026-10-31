# N1 Dev handoff (NANF workstream, fibre profiles and propagation; Dev, Opus 5.5 session)
Status: COMPLETE. Gate: 1169 passed (full run), anchor green, ruff check/format, mypy, license_audit 0 flagged. Local only on v1.3-mpam. Step 1 commit 8f8fc7a (plan Amendment 2) precedes all code.
No fit, scoring, paper-curve simulation, push, merge, tag, hardware. Fig.4, Fig.6, Fig.8 values and holdout series unread.

## Plan (step 1)
- Amendment 2 appended (previous pin 92b20966...ce5c0; new pin in tests/test_nanf_benchmark.py). Closes N0_qa2 1 to 8 and 13.
- C1 cases (B1), C5 1630/1640 nm excluded (B2), A2 d vs own no-fibre output + B2B gate + all-rate rule (B3), A1.7 ranges (B4), A5 repair (B5), SNR definition (B6).
- Guard survivors (item 9) closed; mutants M1 to M8 each killed (see test file comments and final report).

## Code
- fiber.py: ProvenanceCategory (8), ParameterProvenance, ProfileValue, WavelengthTable, FiberProfile, SensitivityScenario, resolve_profile, load_fiber_config. G.652.D code untouched.
- link.py: profile_link_config, propagate_profile_field, transmit_profile, PowerProtocol, group_delay_s, beta2_s2_per_m. validated transmit/dispersive_field untouched.
- configs/fibers/: HONG, ALTUNA x2, WANG, ITU-G652D-REFERENCE (maps to g652d_preset).

## Decisions to check
- Unknown never defaults: raise, or a labelled SensitivityScenario that may fill unknowns only.
- Scalar validity = stated range, else measurement wavelength only, else unrestricted. Hong D is stated for 1550 nm only.
- Omitted slope = second-order only (recorded). Given slope, even 0.0, adds full beta3 (existing rule).
- Hong S 0.004 is `derived` (Sources section 6). Connector loss left unknown (the ~2 dB covers connectorisation).
- Altuna/Wang: user-assumed, "stated in owner brief, not read from paper"; no paper read. No Altuna geometry values were supplied, none stored.
- No CLI added (none for fibres exists; not trivial).

## Physics checks
- First null (model, small-signal tone, square law): 29.386, 27.970, 80.158 GHz vs 29.39, 27.97, 80.2.
- beta2(17 ps/nm/km, 1550) = -21.68 ps^2/km. Group delay NANF 4.76 km = 15.926 us [corrected in fix round: 15.925 us (15.92528), see Fix round]; saving at 5 km 7.759 us (Sources said ~7.8).

## Honest limits
- No NANF attenuation known; Hong D is one assumed value; the guard cross-check of a digest corrupted in both test and doc needs data/external present.

## Fix round (N1 QA, 12 findings; the text above is not rewritten)
- 1 MAJOR: D(lambda) = D_ref + S (lambda - reference_wavelength_nm), also under requested extrapolation (no clamp); `extrapolated` truthful; D with no stated wavelength raises; validity tested for every used parameter. Own literals 12.4 (1590) and 14.2 (1620, extrapolated).
- 2: scenario values obey the known-value minima (losses >= 0, group index >= 1, length > 0).
- 3: label carried by `LinkConfig.sensitivity_scenario` -> `transmit` metadata; `propagate_profile_field` now returns `ProfileField(field, record)` (profile API only); scenario records have `not_a_benchmark_result: true`.
- 4: table units enforced (dB/km, ps/(nm km)); measured/published-* need a real citation (>= 8 chars, a non-placeholder word). Table-beats-scalar conflict left as disclosed.
- 5: matched-ROP refuses NaN/inf and > 10 dBm (sanity limit, scenario-free, before resolve); -5 dBm Hong limit is not the bound.
- 6: Wang YAML and validity section 6 read "separate record; sample identity unknown"; test extended.
- 7: group delay 15.925 us (15.92528); test abs=1e-5; the 15.926 in this file is annotated, not rewritten.
- 8: plan Amendment 3 (previous pin ec0f325a, new pin in test_nanf_benchmark.py): C1 rule for 1e-2, 1e-3, 6e-3, 0; B5.3-N note; no tolerance changed; prefix hash test for text before "## Amendment 2" (92b20966) and before "## Amendment 3".
- 9: test that fails if the Tx filter is dropped from `launch_mean_per_watt` (mutant run: killed); validity doc notes N2 must not double count scenario `connector_loss_db` with the ~2 dB pigtail figure.
- 10 to 12: observations covered by items 8 and 9. G.652.D paths, anchor, goldens untouched. No fit, no Fig.4/6/8 values read.

## Fix round 2 (N1 QA2, 2 MAJOR + 5 MINOR + obs 10; owner decision: fix the dispersion anchor)
- 1, 2 MAJOR: D(lambda) = D_stated + S (lambda - lambda_stated), lambda_stated = D's `measurement_wavelength_nm`, for a profile S and a scenario S alike. `reference_wavelength_nm` is the carrier only and anchors nothing (an unknown one changes nothing). Range-only D plus S raises; without S, D holds only at its stated wavelength or range. Wrong 15.4 test removed. Own literals: D 10 at 1550, S 0.06: 10.0 (1550), 12.4 (1590) for reference 1500, 1550, 1560, 1310; scenario S 12.4; Wang 1560 extrapolated with scenario S 5.02, `extrapolated` truthful. Resolved record gains `dispersion_anchor_nm`.
- 3: D, S and attenuation with no stated wavelength are refused at resolve. Shipped profiles pass honestly, no filler. The test helper no longer sets a hidden D wavelength; each call states it.
- 4: table against known scalar (rel 1e-6) must agree, else `precedence` (table or scalar, real citation, provenance, recorded in `sources`); S against the local D-table slope (1e-3 + 10%) refused, a scenario can never override. Rule written in NANF_MODEL_VALIDITY.md section 5. New optional YAML key `precedence`.
- 5: citation form check: placeholder and filler words extended, digits-only and repeated-character text refused, any script accepted (min 6 non-space, 4 distinct characters); still described as form only.
- 6: profile route refuses base `extra_attenuation_db` NaN, inf, negative (G.652.D `LinkConfig` untouched); matched laser power above 1 W (`MAX_MATCHED_LASER_POWER_W`) refused.
- 7: `transmit` keeps `profile_id`, `sources`, `extrapolated` via three new `LinkConfig` fields (None or empty on G.652.D, record unchanged). `not_a_benchmark_result` for any scenario-filled or extrapolated value. Base label kept, a different label raises, blank raises.
- Obs 10 gaps covered: reference-unknown (now: changes nothing), string-protocol bound, citation length boundary, negative D table.
- Mutants (15 run, all killed by the NANF tests): reference as anchor, held D under scenario S, measurement wavelength ignored, range-only D with S, attenuation unbounded, S unbounded, table conflict ignored, slope-vs-table dropped, benchmark flag scenario-only, base attenuation unchecked, base label replaced, laser bound removed, transmit drops extrapolated, citation length 5, Latin-only citation.
- No change to Altuna/Wang/Hong YAML (the reference note "nominal only" is now true by code). Anchor, G.652.D paths, goldens, CHECKPOINT.md, benchmarks, FIT_HOLDOUT_PLAN.md untouched. No Fig.4/6/8 or holdout read.
