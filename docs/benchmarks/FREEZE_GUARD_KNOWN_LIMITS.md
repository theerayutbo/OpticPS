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

Holdout reading (plan R6.2 and R7.4, `handoff/E1_qa.md` findings 1 and 5, `handoff/E1_qa2.md` finding 1).
The claim, exact: every CLI route that takes a path is gated, and library code is not. Gated means that
before any decode `teriphic.gate_sample_read` runs on the file (or on every file under a folder argument):
registered name of the resolved path (symbolic links followed, case- and Unicode-normal), any file under
`data/external/` other than the B2B file, and the MD5 and SHA-256 of the whole file against the recorded
holdout hashes. The list is `ROUTES` in `src/opticps/cli/main.py`, it is derived from the call graph of each
handler, and a test walks the parser so that a new path option fails until it is gated or listed with a
reason. Where the register YAML is missing (an installed copy), the CLI falls back to the holdout names and
the recorded SHA-256 only. Not covered, listed and not chased:

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

Waveform checks of a file the user supplies (plan R7.5): `opticps benchmark inspect-format --file` runs the
block pass over the whole record (every block of 65,536 samples, same checks, spike test against a robust
scale taken from the record). It screens for corruption, not for format: a ramp, NRZ and a 16-level
waveform pass it, and it makes no four-level claim. Its thresholds were set on the B2B file only, so a lab
capture with a very different but legitimate waveform may be refused (default-deny), and one that passes is
not thereby a verified capture. It never runs on a holdout here.
