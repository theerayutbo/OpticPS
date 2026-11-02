# Freeze guard: known limits

The promise (plan R3.1): the guard catches accidents and casual re-tuning by ordinary commits. It
does not stop deliberate tampering by someone who controls the repository, and it gives no date
proof. Only an external timestamp can. By owner decision (Revision 4) the routes below are listed,
not chased in further fix rounds. Sources: plan R3.4, `handoff/E0_qa.md` to `E0_qa4.md`.

Not refused, deliberate or outside the tool:

- Rewriting history: amend, rebase, filter, a new clone, an amended first commit.
- Grafts or replace objects (the tool turns replace refs off and refuses `.git/info/grafts`, but a
  rewritten object store is not seen).
- A hostile `.git/config` or hook that makes `git` run another program.
- Commit dates and authors typed by whoever commits (backdating); the tool returns them as stated.
- A criterion first written at the fixed path after a draft elsewhere: the freeze is that commit.
- A criterion committed on a branch forked before the freeze and never merged, evaluated on that
  branch (the freeze is not in its history).
- Editing `CRITERION_PATH` in the source to another path (the plan says this needs a revision).
- Statistics computed outside the tool.
- Stage declarations (`validation_stage`, `sequence_check`, `state`) and the existence of input
  files are the caller's word; the order in which inputs were committed is not checked.
- `b2b_basis` cannot be recomputed by the tool; limit equals basis times multiplier holds
  arithmetically only. Estimator ids label estimators, they do not verify code.
- `FrozenCriterion` can be forged in-process with `object.__new__`, and equally through `__dict__`
  or a hand-made pickle (`handoff/E0_qa3.md` finding 9; item b of `handoff/E0_qa5.md`).
- A symbolic link at a parent directory of the criterion (`handoff/E0_qa5.md` item a, also present at
  fc22f41, not a regression): `git mv docs/benchmarks docs/b2`, a criterion with a looser limit,
  `ln -s b2 docs/benchmarks`, one commit, and the guard passes with that commit. The symlink check
  tests the last path component only, so "a symbolic link is refused" and "any other path is ignored"
  hold for the file itself, not for its parents. Listed, not chased.

Holdout reading (plan R6.2, R7.4 and R8, `handoff/E1_qa.md` findings 1 and 5, `handoff/E1_qa2.md`
finding 1, `handoff/E1_qa3.md` finding 1). The claim, exact and no wider: **only paths typed as CLI
options are gated.** Before any decode `teriphic.gate_sample_read` runs on such a file (or on every file
found by walking such a folder): registered name of the resolved path (symbolic links followed, case-
and Unicode-normal), any file under `data/external/` other than the B2B file, and the MD5 and SHA-256 of
the whole file against the recorded holdout hashes. The list of options is `ROUTES` in
`src/opticps/cli/main.py`, and a test walks the parser so that a new path option fails until it is gated
or listed with a reason. Where the register YAML is missing (an installed copy), the CLI falls back to the
holdout names, `data/external` and the recorded SHA-256 only. The owner chose this narrower claim after
three review rounds found that the wider one ("every route") would not close: a gated option can lead to
a path that is not gated. Not gated, listed and not chased:

- Paths found inside files, links to folders inside folders, paths built at run time and defaults. Each route below
  was run by the third review on a holdout-named fixture of random bytes with 0x88 at byte 4. None decodes
  samples as numbers through these routes, per that review. **They do read whole files, and an error
  message can echo one header byte (the review saw byte 4 as 0x88); this is a read of file bytes that
  the plan's "hash only, no header read" (R5.2) does not allow, and it is not prevented here.**
  - a path inside a YAML: `fiber-validate --config f.yaml` with `demo_config: <path>` (read and parsed,
    `fiber_validation.py` line 330) or `demo_results: <path>` (line 332); the parse or decode error
    quotes a byte;
  - a path inside a manifest: `validate --output R` opens an absolute `waveform_filename` found in
    `R/<profile>/experiment_manifest.csv` and the decode error is written into
    `validation_results.csv`; `uxr-report` joins the same way in `_transmitted_excerpt`, and takes
    `waveform_root / item["profile"]` from the results JSON (read only, not run);
  - a symbolic link to a folder inside a folder (a link to a file inside a typed folder is gated: the
    gate resolves it): `validate --output R` with `R/p` a link (the walk by
    `rglob` does not enter it, the profile walk does) and `analyze` with a linked profile folder;
  - a path built at run time: `analyze --output R --profile ../outside` reads outside `R`; `ingest-uxr`
    joins the same way (read only, not run);
  - derived and default paths: `slides --results a/b` reads `a/fiber_validation/fiber_results.json`
    (`report` shares `load_fiber_results`, read only); `demo` reads `DEFAULT_CONFIG` relative to the
    working directory; the default `ingest-uxr` registry path.
  Holdout integrity for scoring does not rest on these gates. It rests on `require_frozen_criterion`,
  which now has a caller (plan R10.1, replacing the E2 obligation of R9.1): the scoring entry point
  `opticps.benchmarks.e2_score.score_holdout` calls it before it hashes, opens or reads anything of a
  2 km or 10 km file, and refuses otherwise. It is the only code in `src` that reads a holdout. Tests
  keep that so (a scan of `src` for the readers, and the order of the calls inside `score_holdout`),
  and `scripts/mutate_e2.py` mutates it. This binds that entry point only: code that calls the generic
  readers below directly, statistics computed outside it, and the other routes listed here are
  unchanged and fall under the promise. The code identity of E2 (R10.4) is a list of file hashes, not
  a proof about the interpreter or libraries.
- `ExternalCapture.open_keysight_bin`, `ExternalCapture.open_raw` and `opticps.measurement.uxr_import.read_bin`
  are generic readers. Called directly on a holdout path (by code, not through the CLI or the adapter) they
  open it; the plan's promise is procedural there. A reviewer's fixture with a holdout name confirmed it
  (`read_bin` returns 16,384 samples, `open_keysight_bin` opens).
- Time of check to time of use: a symbolic link to a decoy of equal size and equal modification time,
  retargeted to a holdout after the gate hashed it, is read by the reader (a reviewer injected the swap).
  It needs a racing process that someone controls, so it is deliberate only and falls under the promise
  above. `Checksum.still_current` compares size and modification time, which is not a proof, and
  `verify_b2b_format` re-opens the path after the gate.
- The gate compares recorded hashes, so a holdout altered by a single byte is not recognised by hash; its
  registered name still is. A holdout copied under another name AND altered is not recognised at all.
- `verify_local_asset` reads every byte of a holdout through a digest (that is the allowed operation).

Refused (closed routes, for reference): edit, revert or delete and re-add of the criterion;
a changed plan after the freeze; rename into the fixed path (20 % similarity); a merge from a side
branch with another limit (full history); a symbolic link at the criterion, plan or an input;
shallow or partial clone; criterion at another path counted as the freeze; a `-s ours` merge that
keeps the real limit (refused too, conservatively, because a second distinct criterion signature
exists in the full history; `handoff/E0_qa5.md` item c).

Waveform checks of a file the user supplies (plan R7.5 and R8): `opticps benchmark inspect-format --file`
runs the block pass over the whole record (every block of 65,536 samples, same checks, spike test against a
robust scale taken from the record). It screens for gross corruption, not for format, and it makes no
four-level claim: a ramp, NRZ and a 16-level waveform pass it. What it misses is listed in plan R8.3 (a flat
run or a short noise burst inside a block, a spike under 8 times the record scale, a block at gain 0.55 to
1.9, an inverted, reversed or replaced block, a replacement by a slow sine of similar spread). Its thresholds
were set on the B2B file only, so a lab capture with a very different but legitimate waveform may be refused
(default-deny), and one that passes is not thereby a verified capture. It never runs on a holdout here. A
file that is overwritten or grows while the pass runs is reported after the pass (the file is checked
again at the end). A file that shrinks while the pass runs ends the process with a bus error (SIGBUS)
and no message: it fails closed, because no result is printed, but it is not reported (plan R9.2).
