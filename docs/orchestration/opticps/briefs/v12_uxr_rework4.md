# Brief: v1.2 rework 4 (Dev): small, targeted

Review of 5e6db48: everything passes except below. Work in this worktree, branch v1.2-uxr. Do not push. Do not use background monitors; finish and report once. Change nothing else.

1. BLOCKER uxr_compare.py `_compare_pair`. A reference-mismatch flag only adds a caveat, so a decided verdict comes from wrong references (all 5 Uniform runs wrong gives about 1.87 bit/symbol). Withhold the pair's verdict when any used capture is flagged: add to `reasons`; keep captures counted and listed. Test: all 5 runs of one waveform flagged gives no verdict; one flagged run also withholds.
2. Keep the training SER >= 0.6 rule. Correct its rationale in code and handoff: within one profile all references share one training block, so a wrong reference leaves training good. The rule covers a corrupted or unrelated capture at very low SNR. State the remaining blind window, training SER about 0.53 to 0.60, far below the operating region.
3. MAJOR capture_dsp.py `firm_clock` guard. Equal drops at every frame gap give 61 ppm error with high confidence and reliable True. When firm_clock is set but tracker and spacing disagree by more than the limit AND training or payload symbol agreement is poor (payload SER well above training-predicted SER), clear reliable with a specific warning. A clean 30 GHz capture must stay reliable, including sigma 0.33 to 1.2; add the probe as a test.
4. SECURITY uxr_import.py. In metadata reads, read only the first element rather than `dataset[()]`, and truncate text to a fixed bound. Do not refuse variable-length strings outright: real Keysight files may use them, since the guide's H5 example near pp2085-2090 uses string attributes; check it. Apply `_text` to every string-like element including str and np.str_ when keeping attributes, and cap the number of attributes kept.
5. MINOR `_condition`: round attenuation and fiber length to a documented resolution (0.1 dB, 0.001 km) before grouping, and record it. A waveform alone in a condition is reported as such. `--power-tolerance-db` rejects negative or nan. A string-valued numeric optional gives a clean error. `cmd_compare_uxr` prints withheld results as readable lines, not a raw dict.

Done means: full pytest, ruff check, format check, mypy, license audit pass; waveform CSV tree identical to main. Commit, ending with:

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LkohWxaooDeaQv9km9STQr

Update the handoff. Reply once: per-item status, test count from a complete full-suite run after the last change, tip SHA. No file contents.
