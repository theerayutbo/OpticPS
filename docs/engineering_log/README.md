# Engineering log

Purpose: raw material for a paper, and a cold resume by another session.

## Resume in this order
1. `STATUS.md`: where work stopped, the last commit, what is next, blockers.
2. `DECISIONS.md`: why the design is what it is. Do not reverse a decision without a new record.
3. `FINDINGS.md`: scientific results and their traceability.
4. `FAILURES.md`: what already failed. Do not repeat it.
5. `VERIFICATION.md`: which external facts are verified and which are not.
6. `LOG.md`: full chronology, when detail is needed.
7. `REPRODUCE.md`: commands from a clean clone to every artifact.

## Rules
- Written as work happens. A phase gate does not pass until its entry is committed.
- `LOG.md` is append-only. Corrections are new entries pointing at the old one.
- Real outputs only. Every numeric result names its seed, config hash or script.
- Every result is labelled simulated or measured. There are no measurements yet.
- No credentials, personal email addresses or private Southampton data: this folder is public.
- AI assistance is attributed, so it can be disclosed accurately in a paper.
