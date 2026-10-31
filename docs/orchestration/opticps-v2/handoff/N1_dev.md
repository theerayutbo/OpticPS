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
- beta2(17 ps/nm/km, 1550) = -21.68 ps^2/km. Group delay NANF 4.76 km = 15.926 us; saving at 5 km 7.759 us (Sources said ~7.8).

## Honest limits
- No NANF attenuation known; Hong D is one assumed value; the guard cross-check of a digest corrupted in both test and doc needs data/external present.
