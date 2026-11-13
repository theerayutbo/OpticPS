# E2 closing record: PARTIAL (2026-11-13)

This record closes the H2 study of Gate E2 at PARTIAL. It is a new file, kept outside
`teriphic_e2/` because a test treats that whole folder as R13-bound. It edits no R13-bound file,
no E2c output and not `STUDY_PLAN.md`. The advice it follows is
`docs/orchestration/opticps-v2/questions/E2_next_paths_fable.md`, section 5. The owner chose that path.

## What the record says

1. **H1 was refuted at 2 km.** The R13 scoring of the 2 km capture recorded FAIL
   (`two_km_result.json`, verdict FAILED). H1 (the B2B-calibrated small-signal surrogate transfers) is
   refuted at 2 km, and no 10 km result can rehabilitate it.
2. **H2's calibration stopped before the power computation.**
   - The v1 stop condition S2 was an optimiser stall (`handoff/E2c_qa.md`, finding 1), not a result
     about the law.
   - Amendment A2 reached an objective of 0.14058 with acceptance checks AC1 to AC3 holding. It failed
     AC4: one basin. Start 10 sits 0.0010072 above the optimum and trades B2B M1 for 2 km M1
     (`teriphic_e2c/a2_endpoint_decomposition.md`).
   - AC4 is not loosened after the fact. `law_model_v2.yaml` stays `FIT_INVALID`, R6 was not computed
     and the v1 verdict of record, `CLOSE_PARTIAL` at S2, stands.
3. **The Step 0 code grid is evidence of a per-session vertical setting.** It meets S1 under the
   plan's own step definition in D6 (ii). The I10 reading under-read it. The consequence stays as D15
   (d) states it: the law's seat is unidentified.
4. **The claim is PARTIAL.**
   - The 10 km file is unspent. It is reserved once, for a differently designed hypothesis H3 (D19),
     with its own pre-registration and power study. It is not available to H2 or to a re-tuned H2.
   - BER and SER stay `REFERENCE_SEQUENCE_MISSING`.
   - This closes the H2 study, not the dataset.
5. **Publisher questions.** The eight questions in section 2 of the advice document (transmitted
   pattern and mapping; wavelength and launch power per length; modulator bias, drive and DAC or BPG
   model; photodiode bias and any TIA or amplifier; oscilloscope model, bandwidth, sample rate and any
   export interpolation; vertical range, offset and attenuation per capture; whether B2B, 2 km and
   10 km were one session and in what order; fibre type and the 10 km spool) are recorded as sent
   by the owner. No answer has been received or is claimed here. None may be assumed or back-filled
   into A2.

The stale 10 km not-frozen test was replaced earlier (commit 2e87b9e).

## Next

E3 (analytic curves; Ran subcases only, MODEL GAP: CHIRP), E4 (evidence matrix, BENCHMARK_REPORT,
REPRODUCE) and NANF N3b. In parallel, a B2B-only characterisation of the transmitted pattern
(plan R.2, `teriphic_prbs/prbs_search_prereg.md`) that cannot produce a BER reference.
