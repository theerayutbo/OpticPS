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

Refused (closed routes, for reference): edit, revert or delete and re-add of the criterion;
a changed plan after the freeze; rename into the fixed path (20 % similarity); a merge from a side
branch with another limit (full history); a symbolic link at the criterion, plan or an input;
shallow or partial clone; criterion at another path counted as the freeze; a `-s ours` merge that
keeps the real limit (refused too, conservatively, because a second distinct criterion signature
exists in the full history; `handoff/E0_qa5.md` item c).
