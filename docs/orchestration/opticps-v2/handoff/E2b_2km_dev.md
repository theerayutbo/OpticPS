# E2b stage 1, the 2 km holdout run (Dev)

2 km scored once; 10 km not run.

## Identities
- Branch `v1.3-mpam`, run at head `5533cf64f416f5e1386db357852c6362097c3f99` (the record's own `head_commit`).
- Freeze R13 commit `ce0ee732af1111c67d94943ad985469dea8c8389`; criterion `docs/benchmarks/TERIPHIC_CRITERION_R13.yaml`;
  plan Revision 13, SHA-256 `73884278d316b48323685f98ab5c2dd5768aa565a308bd544195ba829161564f`.
- The 10 km file was not read, hashed or opened.

## Dry checks (before any 2 km read)
- A renamed path (`NOPE_2km.bin`): `REFUSED: LEAKAGE_DETECTED: ... is not a registered 2 km or 10 km holdout`, exit 2.
- A wrong pin (forty zeros): `REFUSED: the freeze commit found (ce0ee732af12) is not the pinned 000000000000`, exit 2.

## Command line
```
python3 scripts/score_teriphic_e2.py data/external/teriphic/50G_PAM4_PD1_2km_Subassembly1.bin \
  --b2b data/external/teriphic/50G_PAM4_PD1_B2B_Subassembly1.bin \
  --freeze-commit ce0ee732af1111c67d94943ad985469dea8c8389 --sequence-check not-run
```
Run once, in the foreground, exit 0, about 16 minutes, stderr empty. No code, config, limit or argument was changed.
Stdout was written byte for byte to `docs/benchmarks/teriphic_e2/two_km_result.json`.

Record SHA-256 (stdout and committed file): `476642bc79cbc5b8634499fb8361bef0bf28d6e546a146d46232124cd765d9c5`.
Record commit: the commit that adds `two_km_result.json` (subject "Record the 2 km holdout result of Gate E2b: FAIL, nothing carried").

## Result
- outcome `FAIL`, verdict `FAILED`, claim `null` (none).
- declarations: sequence_check NOT_RUN, state null, validation_stage null. hashes_verified true. window start 16777216, 4194304 samples.
- Report summary line: "2 km: outcome FAIL, claim none, verdict FAILED; dispersions of the survivors none ps/(nm km); amplitude ratio vs B2B 0.8324 (reported, not tested); a positive result is never VALIDATED: the verdict is capped at INCONCLUSIVE by design."

## psi table summary (123 scenarios scored; survivors are psi <= 1)
- Survivors: 0. `carry_forward` is empty.
- Lowest psi: `D6.352_N1.5_THRU` 1.501, then `D6.25_N1.5_THRU` 1.502, `D6.352_N1.5` 1.502, `D6.25_N1.5` 1.504, `D6_N1.5` 1.506. Highest psi 2.15.
- No-fibre control (D0, noise 1) psi 2.143. B2B copy psi 1.643.
- Amplitude ratio vs B2B 0.8324 (reported, not tested). Limits as frozen: M1 0.01814, M2 0.06000, M3 0.13066, M4 1.21792.
- No scenario in the grid passes. (Aria correction after review E2b_2km_qa.md finding 1: an earlier sentence here argued from the best-to-worst psi spread that the misfit is not about dispersion; that spread comes from the noise factor, not dispersion, and the argument was not pre-registered. The pre-registered R13.1 reading above is the only interpretation.)

## Carried scenarios
None. The carry rule found no survivor, so the stage is `FAIL` and nothing is carried (plan R12.3).
`selected_scenario.yaml` was NOT written: `read_two_km_record` requires a non-empty `scenario_ids`, so a selection for a FAIL cannot be valid,
and the plan says a FAIL carries nothing. Only the record was committed.

## Interpretation, quoted from the pre-registered table (plan R13.1, fixed before any read)
| Stage and outcome | What it says | Verdict | Next |
|---|---|---|---|
| 2 km FAIL | "the surrogate does not transfer within 2x its own B2B misfit; the study excludes dispersion as the cause (D 0 to 9 all pass at 2 km), so a nuisance is present (receiver or export filter, SNR change beyond 2.2x, large-signal, sequence statistics)" | FAILED | "10 km refused by code and kept unspent; high value, a clean negative" |

Stop rule D4: "the 10 km run is made if and only if the committed 2 km record's outcome is not FAIL. No other condition."
The record says FAIL, so no 10 km run follows.

## Claim ceiling
No positive claim is made: claim is none. For the record, the pre-registered ceiling on any positive result is PARTIAL (plan R12.4, "Cap"):
`VALIDATED` is never returned at either length, and the report summary line does not show this ceiling, so it is stated here.
A 2 km result cannot end VALIDATED in any case.

## BER and SER
Not printed. They stay `REFERENCE_SEQUENCE_MISSING`.

## Guard check at the new tip
`read_two_km_record` called with the pinned freeze, the committed scenario list and the record's limits refuses with
`StageRefused: selected scenario: added once, never changed, found 0`. That is the expected refusal: there is no selection file, and the
record itself says FAIL, which the same function (and `e2_score`, independently) also refuses ("nothing is carried, the 10 km file stays unspent").
The 10 km path was not exercised and the 10 km file was not touched.

## Anomalies and limits
- The 2 km file was read once (one execution). Aria's approval is needed for any second run, which would be a procedural limit under
  `FREEZE_GUARD_KNOWN_LIMITS.md`.
- The run took about 16 minutes; the tool moved it to the background after 180 s. It was not restarted.
