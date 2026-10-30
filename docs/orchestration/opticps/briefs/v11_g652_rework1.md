# Brief: v1.1 rework 1 (Dev)

Review of 8a3b425 returned FAIL. Physics and standard numbers passed. Work in this worktree, branch v1.1-g652. Same rules as briefs/v11_g652_dev.md; waveform CSVs and results/synthetic stay unchanged. Do not push. Each fix gets a regression test where code changes.

1. HIGH fiber.py:252-254. Add a separate slope provenance field. Measuring D must not relabel the slope, and a measured slope must be tagged. Remove the report claim (md:284) that length and laser wavelength enter through apply_measurements, or add them as properly recorded parameters.
2. HIGH link.py:70-78. `LinkConfig(fiber=..., attenuation_db_per_km=...)` and `dataclasses.replace(cfg, attenuation_db_per_km=...)` silently lose values. Raise when a field conflicts with the fiber. Make replace safe too, for instance by storing raw fields and resolving through effective properties.
3. MEDIUM fiber_validation.py:262, report md:249-254. The "slope only" arm is a third-order on/off test: its beta3 includes the D part. Rename and reword it; quote the parts (0.1268 total, 0.0357 from D, ps^3/km).
4. MEDIUM link.py:144. Use slope None = second-order v1.0 path; 0.0 means a true zero slope with beta3 from D. Defaults stay numerically identical to v1.0, proven by rerunning the reproduction check.
5. MEDIUM fiber_report.py:394-398. Print the excess loss in every table, and explain why the 40 km values differ between tables.
6. MEDIUM fiber_report.py:378, md:91. Correct: only the before/after arm is paired with v1.0; length and sensitivity sweeps differ in tags, runs and excess loss.
7. MEDIUM report md:79, fiber_validation.py:422-423. Remove "includes splices and connectors" as stated cause. Quote what Table I.1 says; mark any explanation as inference. Reconcile with md:282, and warn about double counting if excess loss is added.
8. LOW md:95. Disclose same responsivity, V_pi and MZM at both wavelengths as an assumption. Narrow "dispersion limits the bandwidth": Profile A is loss-limited.
9. LOW fiber_validation.py:129. Report the full exceedance range (1260 to 1435.5 nm) of the representative curve, not only [1260].
10. LOW link.py:166. A user-set attenuation must not be recorded as v1.0 defaults or simulation-default.
11. LOW "in force": keep it, sourced to the ITU recommendation page, read 2026-10-30, not the PDF.
12. LOW Main report md:92: fix "sections above" and literal backticks.
13. LOW README.md:48: fix the `opticps demo` statement or include fiber-validate; prefer correcting the text so demo stays unchanged.
14. LOW VERIFICATION.md:23: join the table.
15. LOW Move the attenuation figure legend off the curve; restore "±3 nm" at 1383 nm.
16. LOW Correct the handoff: 8 symbol errors at Outer70, 4 km; null shift 2.2e-9 GHz at 1310 nm.
17. Capture fiber metadata: validate value-source strings, and reject disagreement with top-level `fiber_length_km`.
Also remove the literal words "receiver yet to be identified" from reporting/report.py: receiver is a Keysight Infiniium UXR Series oscilloscope, 256 GSa/s, model suffix unconfirmed. Fiber standard and length remain unconfirmed.

Regenerate fiber results, fiber report, main report and slides. Done means: pytest, ruff check, format check, mypy, license audit pass, reproduction 45/45, CSV hashes unchanged. Commit, ending with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update the handoff. Reply: per-finding status, test count, tip SHA, done or blocked. No file contents.
