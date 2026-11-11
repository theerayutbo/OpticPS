# Fit and holdout plan: TERIPHIC PD1 PAM4 (declared before any sample is seen)

Declared 2026-10-31 at Gate E0 (Stage 3A, roadmap v2.1 section L2, step 4). The SHA-256 of this
file is pinned in `tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`, so
an edit after the fact is visible as a failing test. Amendments are new dated sections at the
end of this file together with a new pin; the earlier text stays in Git history. **Revision 1
(2026-10-31, at the end of this file) amends this plan after review.** ~~Every clause it
supersedes is struck through in place and marked "Revision 1"~~ [Revision 2: that sentence was
not true, see R2.1; from Revision 2 on, every change to earlier text is struck through and
marked, or listed in R2.1 with its diff reference]. **Revision 2 (2026-10-31, at the end of this
file) amends the plan after the second review.** The numeric
criterion is not an amendment but a required input file whose schema and freezing rule
Revision 1 fixes (section R.4), which removes the earlier conflict between "amendments are
sections here" and "a separate addendum" in section 3.

## 0. State of knowledge when this plan was written

(Revision 1 updates the hashing statement below, see R.1.)

- No sample byte of any TERIPHIC capture has been opened, hashed, plotted or summarised by the
  E0 work. Only record metadata (Zenodo JSON and record page, read through a fetch tool) was read.
- At the time of writing, `data/external/teriphic/` (ignored by Git) holds a file of exactly
  the listed size for B2B and a partial 2 km file that an external `curl` process was still
  writing. Neither was created by E0, and E0 did not read them. They do not change this plan.
  ~~Checksums, format and content are therefore all still unknown to the plan author.~~
  [Revision 2: checksums are known since R.1, as hashes reported by the orchestrator; format and
  content are still unknown.]
- The raw format, wavelength, fibre type, transmitted reference sequence and calibration units
  are unknown (see MISSING_PARAMETERS.md). The plan has to hold under those unknowns.

## 1. Unit of analysis and grouping

Files in scope (Zenodo 10.5281/zenodo.7886498, PD1, Subassembly 1, PAM4, 50 GBd):

| Role | File | Acquisition group |
|---|---|---|
| Characterisation (fit) | `50G_PAM4_PD1_B2B_Subassembly1.bin` | `7886498/SA1/PD1/B2B` |
| First declared validation | `50G_PAM4_PD1_2km_Subassembly1.bin` | `7886498/SA1/PD1/2km` |
| Locked out-of-length test | `50G_PAM4_PD1_10km_Subassembly1.bin` | `7886498/SA1/PD1/10km` |

Grouping rules, applied by any later code:

1. One file is one acquisition. The record has one PD1 PAM4 file per length, so there are no
   repeats inside a length and no estimate of run-to-run spread from this source.
2. All three share one transmitter, one detector (PD1) and one subassembly. The split is
   therefore by fibre length only. It is not an independent-apparatus split and must never be
   described as one. Whether the three captures were taken in one session, with the same
   launch power and bias, is unknown. ~~If they were re-tuned between lengths, a frozen single
   normalisation can fail for reasons unrelated to the model (this is reported as limited
   evaluation, not as a model failure).~~ [Withdrawn by Revision 1, R.5: no source can show
   re-tuning, so it cannot change a FAILED into a softer label. The report may state the
   confound next to the verdict.]
3. Leakage checks use acquisition group, file name and (once computed locally) SHA-256. A
   file may appear in exactly one role. Two files with equal hashes are one acquisition.
   [Revision 1, R.6: the code now also checks the supplied MD5, normalises group and file
   name case, and the loader calls the check.]
4. EML dataset (10.5281/zenodo.7886228): the record states that `v1`, `v2`, `v3` are repeated
   runs with the same operating parameters at different time indices. They are time-indexed
   repeats of one condition, not independent conditions. Group key is (EML, length); all
   versions of one group go to the same role, never split across fit and test. The EML set is
   out of the MZM model domain and is not part of this fit or holdout.
5. Other detectors (PD2, PD3), NRZ files and Subassembly 2 are not touched by this plan. PD2 and PD3
   PAM4 B2B/2 km/10 km are reserved as a later out-of-device test, to be opened only after the
   10 km result is recorded, and never used for tuning.

## 2. Roles and what each may be used for

**B2B (characterisation).** The only file whose amplitude statistics may be used to choose
model structure, fit parameters, fix a single normalisation (gain and offset), set the
noise-model family and set receiver DSP settings. If E1 splits the file in time, the first half
is fit and the second half is a within-B2B consistency check, as contiguous blocks with a gap of
at least one symbol-pattern length once that length is known. If the transmitted pattern is a
short repeating sequence (unknown), a time split is not independent and is reported as such.
[Revision 1, R.2 adds the cross-length consequence of a repeating sequence.]

**2 km (first declared validation).** Not opened for any statistic (Revision 1, R.2: not only
amplitude) until the B2B model
and the list of fibre scenarios are frozen in a committed file. Allowed: select among a finite,
pre-listed set of scenarios (for example "no dispersion", "assumed G.652.D at a stated
wavelength", each with stated parameters), and report. At most the pre-listed scenarios are
tried; the number of scenarios is recorded and counted in the report. After selection, the
choice is frozen and committed.

**10 km (locked test).** One evaluation. Its statistics (Revision 1, R.2: every statistic, not
only amplitude) are not computed until a
commit contains the frozen parameters, the selected scenario and the evaluation script, and the
commit SHA is written to the report. If anything is changed after the 10 km result is seen, the
10 km file is burned for confirmatory purposes and the report says `EXPLORATORY` for it.

**Format hypotheses.** Byte-level format tests (dtype, endianness, header, length) are
developed on B2B only. The accepted hypothesis is then applied unchanged to 2 km and 10 km. If it fails
there, the outcome is `FORMAT_UNKNOWN` for that file; the hypothesis is not re-tuned on it.

## 3. Quantities compared, and what is not compared

- Compared (only once units and format allow): normalised level-structure and amplitude
  histogram statistics, quantiles, amplitude spectrum shape, per-length change in normalised
  level spacing. All labelled `normalized`; none is optical power, dBm or calibrated volts.
- Not computed: BER, SER or post-FEC BER, because no transmitted reference is documented
  (`REFERENCE_SEQUENCE_MISSING`). Any decision-error proxy carries a different field name.
- ~~Numeric pass/fail tolerances depend on the B2B noise floor and are not known now. They will
  be written in a separate dated addendum with its own SHA-256 before any 2 km statistic is
  computed. Until then no result can be called validated.~~ [Superseded by Revision 1, R.4:
  the metrics are named now; the numbers are frozen in a committed criterion file that a tool
  checks before any holdout evaluation.]

## 4. Identifiability caveat

B2B observes one lumped response: transmit electronics, modulator, receiver photodiode,
oscilloscope front end and any digital filtering together. Without a calibrated amplitude scale,
a known transmit waveform or a reference sequence:

- transmitter and receiver bandwidth cannot be separated; a different split gives the same B2B
  waveform statistics;
- thermal, relative-intensity and scope noise cannot be separated from one amplitude noise
  figure;
- absolute gain, offset and modulator operating point are confounded with the arbitrary scale;
- the optical wavelength is unknown (O-band only), so the dispersion that 2 km and 10 km add
  cannot be computed, and near the zero-dispersion wavelength it may be negligible.

Consequence, declared in advance: if the predicted change between B2B and a length is smaller than the
B2B parameter uncertainty under every listed fibre scenario, or if two parameter sets that fit B2B equally
well predict different results at 2 km, that comparison is `UNIDENTIFIABLE_PARAMETER`. The report then
states a limited evaluation (bounded prediction envelope, not a fitted success). A
convolution response or noise model is never called unique when several devices could produce it.

## 5. Outcomes

Each length ends as one of: `VALIDATED` (~~against the later addendum criterion~~ [Revision 2: against the frozen criterion
file of R.4 and R2.3, and only under the conditions of R2.5]), `FAILED`,
`INCONCLUSIVE`, `UNIDENTIFIABLE_PARAMETER`, `BLOCKED` (data, format or licence).
[Revision 1, R.5: `VALIDATED` is available for 10 km only; 2 km cannot end VALIDATED.] Negative and
inconclusive results are reported with the same prominence. The result concerns signal statistics
of one detector and one subassembly; it is not a validation of adaptive shaping or of the
Southampton hardware.

## Revision 1 (2026-10-31): amendment after the E0 independent review

Previous version: SHA-256 `6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a`
(the text at commit 8900748 as pinned in E0). New version: the pin in
`tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`
(a file cannot contain its own hash; ~~the same value is in the commit message~~ [Revision 4: false, no commit message holds it]).

Reason: the E0 review (`docs/orchestration/opticps-v2/handoff/E0_qa.md`, findings 5 and 6, on
commit 94a3ec9) showed that the plan did not cover one transmitted sequence shared across
lengths, locked only "amplitude statistics", deferred the numeric criterion without a tool that
enforces the deferral, and contained a clause that turns a failure into a softer label without
evidence. This revision is made before E1 reads B2B, so the plan is still declared before any
sample is interpreted.

### R.1 State of knowledge at this revision (truthful)

- By the orchestrator's report, the three target files were downloaded with the owner's approval
  and hashed (MD5 and SHA-256, whole file streamed) on 2026-10-31; the values are in
  `docs/benchmarks/SOURCE_REGISTER.md`. Hashing passes every byte through a digest; **no
  sample of any TERIPHIC capture has been read, decoded, plotted or summarised ~~by anyone~~
  [Revision 2: according to the orchestrator's record and the Dev logs; the plan cannot know
  what else a person did]: the files have only been hashed.** The Dev who wrote this revision did not open `data/external/`.
- Section 0 above said no sample had been hashed; that statement is superseded by this one. It
  changes nothing else: format, wavelength, fibre type, reference sequence and calibration remain
  unknown.

### R.2 Shared transmit sequence across lengths

The record does not say whether B2B, 2 km and 10 km carry the same transmitted sequence; one
repeating sequence may be used for all three. If so, the three waveforms are not independent in
the transmitted data, and a pattern-specific effect or a sequence learned from B2B carries into
2 km and 10 km. Therefore, until the relevant freeze (the criterion commit for 2 km, the
evaluation commit for 10 km):

- pattern correlation, timing or clock recovery, sequence extraction, run-length or pattern
  statistics and any alignment of one length with another are **barred on 2 km and 10 km**, as
  is any statistic computed on them, not only amplitude statistics;
- on B2B the same operations are allowed for characterisation, but any bit or symbol sequence
  recovered from B2B is an **inferred candidate** (`Provenance.INFERRED`), never a reference for
  BER: BER stays `REFERENCE_SEQUENCE_MISSING` unless a source states the sequence
  (`holdout.require_reference_for_ber` refuses an inferred, simulated or digitised sequence);
- if a recovered B2B sequence is later found in 2 km or 10 km, that is reported as a finding on
  independence, and the affected holdout is marked `EXPLORATORY` for that statistic.

### R.3 What the locks cover

The lock on 2 km and 10 km covers **every** statistic: amplitude, spectral, timing, pattern,
and cross-length. The only operations allowed on a holdout before its freeze are the ones
needed to hash the file and to read it with the format hypothesis accepted on B2B (header,
length and dtype checks that touch no sample value).

### R.4 Metrics named now; how the numeric criterion is frozen

Metrics (each computed on normalised amplitude, using the single B2B-frozen normalisation;
none is optical power, dBm or volts):

- ~~M1 level spacing: the three gaps between adjacent PAM4 level centroids, divided by the B2B
  mean gap, and the change per length of that vector.~~ [Revision 2: M1 was a vector with no
  norm, no measured-versus-predicted form and no pass rule; it is defined in R2.2.]
- M2 amplitude histogram distance: Wasserstein-1 distance between measured and predicted
  distributions of normalised sample amplitude.
- M3 quantile error: largest absolute difference of normalised amplitude at the 1, 5, 25, 50,
  75, 95 and 99 % quantiles.
- M4 spectrum shape: log-spectral distance between measured and predicted normalised power
  spectral density over 0 to the baud rate.

Level centroids come from clustering and are labelled inferred (no transmitted reference). The
numeric limit of each metric is a number computed from **B2B data only** (for example the
spread between the two B2B halves, or the width of the B2B parameter-uncertainty envelope) with
a stated multiplier. All limits go into `docs/benchmarks/TERIPHIC_CRITERION.yaml`, which carries
the hash of this plan in a `plan_sha256` key. That file must be **committed before any 2 km
statistic is computed**; ~~the commit date is the freeze date~~ [Revision 2: a commit date is
whatever its author set and can be forged; see R2.3 for what the freeze proves and what it does
not].

Enforcement: `src/opticps/benchmarks/holdout.py::require_frozen_criterion(asset, ~~criterion_path~~ [Revision 3: not a parameter, the path is the fixed constant `CRITERION_PATH`])`
refuses (raises `BenchmarkError`) any evaluation of a `VALIDATION` or `LOCKED_TEST` asset when the
criterion file is absent, incomplete (a metric missing, not finite or not positive), refers to
another plan hash, or is not committed and unmodified in Git. ~~It returns the commit that froze
it, which a report must carry.~~ [Revision 2: it returns the first commit that held the limits,
as the history of the local repository states it; see R2.3.] Every holdout evaluation entry point added in E2 must call it
before computing anything; E2 adds a test that its entry point does. At the time of this
revision no holdout evaluation code exists, and the criterion file does not exist, so every
holdout evaluation is refused. The tool cannot see statistics computed outside it; that part is
procedure, which is why this plan bars the operations in R.2 and R.3.

### R.5 Verdicts

- Options stay `VALIDATED`, `FAILED`, `INCONCLUSIVE`, `UNIDENTIFIABLE_PARAMETER`, `BLOCKED`.
- 2 km is used to **select among the pre-listed fibre scenarios**. A result used for selection
  is biased in its own favour, so **2 km cannot by itself be VALIDATED**; the 2 km verdicts are
  `FAILED`, `INCONCLUSIVE`, `UNIDENTIFIABLE_PARAMETER` or `BLOCKED`. A 2 km result inside the
  frozen criterion is reported as "within criterion at the selection stage" without a verdict.
  Only the single 10 km evaluation, with the scenario already frozen, can end `VALIDATED`, and
  only if 2 km did not end `FAILED` (`holdout.allowed_verdicts` encodes this).
- The sentence of section 1, rule 2 that turned a failure after possible re-tuning into a
  "limited evaluation" is withdrawn. A failure against the frozen criterion is `FAILED`; the
  report may add that the cause is not attributable to the model alone, but may not change the
  label. `UNIDENTIFIABLE_PARAMETER` (section 4) stays: it rests on stated evidence (prediction
  change smaller than the B2B uncertainty, or two B2B-equivalent parameter sets predicting
  different results).

### R.6 Leakage check

The loader now calls `assert_no_split_overlap`. It compares acquisition group, file name,
supplied MD5 and locally computed hashes, after normalising case. The same value of any of
them in two roles, or under two groups, is `LEAKAGE_DETECTED`.

## Revision 2 (2026-10-31): amendment after the second E0 independent review

Previous version: SHA-256 `42a578f5c3e9d28d1fad69800416faa2330510c37007a7c56c7bc940d42d358a`
(Revision 1, commit 8f57af9; the first version, `6bf4238a...`, is commit 8900748). New version: the
pin in `tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`
(a file cannot contain its own hash; ~~the same value is in the commit message~~ [Revision 4: false, no commit message holds it]).

Reason: the second E0 review (`docs/orchestration/opticps-v2/handoff/E0_qa2.md`, findings 1 to 3)
showed that the freeze check of Revision 1 passed a re-committed or amended criterion and a
backdated commit, that a claim of this plan about struck-through text was false, that metric M1
had no norm or pass rule, that estimators were not frozen and that the criterion schema had no
field for the stated multiplier. `handoff/E0_qa.md`, cited in Revision 1, was not tracked at
that revision; it was committed later (ba367cc). Still before E1: no sample of any capture has
been read.

### R2.1 What was edited in place, and what happened to the struck-through claim

The header of Revision 1 said every superseded clause was struck through. That was false.
Revision 1 struck through two clauses (the re-tuning sentence of section 1 rule 2, and the numeric-tolerance bullet of section 3). It
changed other earlier text in place, without strike-through: it added sentences to the header,
a pointer line to section 0, a bracket to section 1 rule 3 and to the B2B paragraph and to
section 5, and it **rewrote** two sentences of section 2. The original wording of those two was:
"Not opened for amplitude statistics until the B2B model and the list of fibre scenarios are
frozen in a committed file" (2 km) and "Its amplitude statistics are not computed until a commit
contains the frozen parameters, the selected scenario and the evaluation script" (10 km). The full
change is `git diff 8900748 8f57af9 -- docs/benchmarks/FIT_HOLDOUT_PLAN.md`.
Revision 2 edits earlier text in these places, each struck through and marked in the text: the
header sentence above, the "Checksums, format and content" sentence of section 0, the addendum
wording in section 5, the claim in R.1 about who read samples, the M1 bullet, the sentence that
made the commit date the freeze date and the description of what the tool returns in R.4. The diff of this
revision is `git log -p --follow -- docs/benchmarks/FIT_HOLDOUT_PLAN.md` (the commit that
adds this section).

### R2.2 Metrics defined, estimators frozen

All estimators below are frozen by this revision. ~~A change needs a new revision that is
committed before the criterion file is.~~ [Revision 3: nothing checks that order, and the tool does
not claim to; what it does check is in R3.2.]

- Normalisation: one affine map, fixed on B2B and applied unchanged to every length: x_norm =
  (x - c0) / g0, where c0 is the mean of the four B2B level centroids and g0 the mean of the
  three adjacent B2B gaps. B2B therefore has mean gap 1 by construction.
- Level centroids (inferred, no transmitted reference exists): one-dimensional k-means with k = 4,
  Lloyd iterations, initial centroids at the 12.5, 37.5, 62.5 and 87.5 % quantiles, stop when the
  largest centroid move is below 1e-9 times the sample standard deviation or after 200 iterations,
  centroids sorted ascending.
- Quantiles: linear interpolation between order statistics (Hyndman-Fan type 7, the NumPy default).
- M1 level spacing: let g(m) be the vector of the three adjacent gaps between the centroids of the
  measured normalised samples of one length, and g(p) the same for the predicted normalised
  samples, each from the estimator above. M1 = max over i of |g(m)_i - g(p)_i|, the L-infinity
  norm, dimensionless (units of the B2B mean gap). The measured change of g per length against
  B2B is reported as information and does not enter the pass rule.
- M2: Wasserstein-1 distance between the measured and predicted amplitude distributions, computed
  as the mean over N = 65536 equally spaced probabilities u = (j - 0.5)/N of |Q_m(u) - Q_p(u)|,
  with Q the quantile function above.
- M3: the maximum over p in {0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99} of |Q_m(p) - Q_p(p)|.
- M4: Welch power spectral density of the normalised samples: Hann window (periodic), segments of
  4096 samples, 50 % overlap, constant detrend, density scaling, one-sided; the log-spectral
  distance is the square root of the mean over the bins with frequency up to the baud rate of
  (10 log10(P_m/P_p))^2, in dB. It needs the sample rate; if that stays unknown the metric is not
  computed and the length is BLOCKED.
- Pass rule: a length is within the criterion if and only if **all four** metrics are less than or
  equal to their frozen limits (non-strict). One metric above its limit is a failure against the
  criterion.

### R2.3 The criterion file, and what its freeze proves

~~Schema (`criterion_version: 2`), exactly these keys: `plan_sha256`, `limits`, `b2b_basis` and
`multipliers`.~~ [Revision 3: `criterion_version: 3` adds the key `estimators`, see R3.2.] For each metric `b2b_basis` is the number computed from B2B data only, `multipliers`
is the stated multiplier, and the limit must equal their product (relative tolerance 1e-9), so a
limit cannot hide an unstated factor.

`holdout.require_frozen_criterion` refuses an evaluation of 2 km or 10 km unless all of these hold:

1. the plan, the criterion and the other inputs the plan names are committed, and their bytes in
   the working tree equal their bytes at `HEAD` (bytes are compared, not `git status`, so
   `--assume-unchanged` and `--skip-worktree` cannot hide a change; an uncommitted plan is
   refused); the limits returned are read from the `HEAD` bytes, never from a working file;
2. the criterion has the schema above, and its `plan_sha256` is the hash of the committed plan;
3. ~~the first commit of the followed history of the file that holds non-null `limits` is the
   freeze commit, and **no later commit changed the limits**: a re-commit with other limits is
   refused;~~ [Revision 3: no history is followed across paths, see R3.2.]
4. the inputs for 2 km are `b2b_model` and `scenario_list`; for 10 km `frozen_parameters`,
   `selected_scenario` and `evaluation_script`, and the 2 km stage must be done;
5. `RESERVED` and `UNASSIGNED` assets (PD2 and PD3, section 1 rule 5) are refused;
6. a shallow clone is refused, because its first commit is not visible.

What this does **not** prove, stated plainly:

- Git history can be rewritten locally. The tool proves consistency with the history present in
  this local repository, and nothing about how that history came to be. A re-commit that changes
  the limits is refused. An amended or rewritten first commit leaves no trace in the repository
  and is **undetectable**.
- The commit date is reported as Git states it (author date and committer date, both returned).
  Both can be set to any value by whoever commits; a backdated freeze commit passes. The date is
  not evidence.
- Only a timestamp the author does not control proves when the criterion existed, for example the
  freeze commit pushed to a remote that the owner does not control. Pushing is an owner action;
  this revision did not push and the tool cannot check it.
- The tool cannot see statistics computed outside it (procedure, R.2 and R.3).
- ~~A first commit that holds wrong limits cannot be corrected; that needs a new plan revision and
  a new criterion file name.~~ [Revision 3: the path is fixed, so there is no new file name to
  use. A wrong first commit cannot be corrected by the tool; the owner would have to change the
  path constant in a new plan revision.]
- `FrozenCriterion` can be built only by the checker as far as Python allows (the constructor,
  `replace`, `copy` and `pickle` refuse); code that calls `object.__new__` can still forge one.

### R2.4 Sequences driving a prediction, and the shared-sequence check

R.2 covers the data. It also covers **predictions**: a prediction for 2 km or 10 km must not be
driven by a sequence recovered from B2B, or from any capture. Allowed drivers are a sequence a
source states, a synthetic sequence whose seed is in the committed frozen parameters, or the
level probabilities alone. A prediction driven by a B2B-recovered sequence is a replay of that
sequence; it may be reported only as `EXPLORATORY` for that statistic and does not count towards
`VALIDATED`.

Before `VALIDATED` can be written for 10 km, a **shared-sequence check** must be run and
recorded: after the evaluation commit exists, test whether a sequence recovered from B2B occurs in
the 2 km or 10 km data, by a method committed in the evaluation script. Its result is
`NOT_SHARED`, `SHARED` or `NOT_RUN` (`holdout.SequenceCheck`). Only `NOT_SHARED` allows
`VALIDATED`; `SHARED` marks the affected statistics `EXPLORATORY`.

### R2.5 Verdicts (extends R.5)

`EXPLORATORY` is a label, not a confirmatory verdict. `holdout.allowed_verdicts` has no permissive
default: for 10 km it offers `VALIDATED` only when the file is intact, 2 km was done and did not
end `FAILED`, and the shared-sequence check found `NOT_SHARED`; a missing state offers none. A
10 km file that was burned (anything changed after its result was seen, section 2) can end only
`EXPLORATORY` or `BLOCKED`. 2 km still cannot end `VALIDATED`.

## Revision 3 (2026-10-31): the freeze guard is narrowed after the third E0 review

Previous version: SHA-256 `45d9088cd21248d5828552bdaec0215c54c4a0334086dfbd7a4ea1003c5dec11`
(Revision 2, commit 0424e9c; Revision 1 is `42a578f5...` at 8f57af9, the first version `6bf4238a...`
at 8900748). New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml` (a file cannot contain its own hash; ~~the 8-digit
prefix is in the commit message, and~~ [Revision 4: false, no commit message holds the prefix; the
same claim in R.1 and Revision 2 is also struck] the full value is in the test file).

Reason, truthfully. The freeze guard was reopened by three independent reviews in a row
(`handoff/E0_qa.md`, `E0_qa2.md`, `E0_qa3.md`). Each fix round closed the routes the review had
found and the next review found others: a re-commit with other limits, an amended or backdated
commit and index flags (second review); a re-tuned limit under a new file name, a plan changed
after the freeze, hostile repository-local Git settings, an unchecked stage declaration and licence
spellings (third review). Adding checks to a local history check does not end that series, because
nothing local can prove what happened before the commit. The owner therefore decided to narrow
what the guard promises and to simplify it rather than extend it. Still before E1: no numeric limit
is set and no criterion file exists; no sample of any capture has been read, according to the
orchestrator's record and the Dev logs.

### R3.1 The promise

The guard catches accidents and casual re-tuning by ordinary commits. It does not stop deliberate tampering by someone who controls the repository, and it gives no date proof. Only an external timestamp can.

The same text is in the docstring of `holdout.py`. Any wording elsewhere that claims more is
superseded by this paragraph.

### R3.2 What the guard does now

- The criterion has **one fixed path**, `docs/benchmarks/TERIPHIC_CRITERION.yaml` relative to the
  repository root (`holdout.CRITERION_PATH`); it is not a parameter. A file at any other path is
  ignored and cannot satisfy the guard. No rename is followed. The freeze commit is the first
  commit that holds the criterion at that path; a draft kept under another name is not a criterion.
  A history in which the path was renamed in (Git's similarity threshold set to 20 %) is refused.
- The criterion is compared as a whole between commits, with number types: `plan_sha256`, `limits`,
  `b2b_basis`, `multipliers` and `estimators`. Any later commit that changes any of them, deletes the
  file or restores it, is refused. A plan changed after the freeze, with `plan_sha256` re-tied, is
  therefore refused while a frozen criterion exists.
- `criterion_version: 3` adds the key `estimators`, which must name exactly the four estimator ids
  of R2.2 (`holdout.ESTIMATORS`). The ids label the estimators of R2.2; they do not verify code.
- R2.2 said a change of estimators needs a revision committed before the criterion. That order is
  **not checked** and the sentence is struck through above. Plan text and criterion are tied by
  `plan_sha256` only.
- Git is run with `--no-replace-objects`, `log.showSignature=false` and `log.showRoot=true`. A
  shallow clone, a partial clone and a repository with `.git/info/grafts` are refused.
- `b2b_basis` is a number the tool cannot recompute: "a limit cannot hide an unstated factor"
  holds arithmetically only.

### R3.3 What is declared by the caller

`validation_stage`, `sequence_check`, `state` and the existence of the input files are the
caller's declarations. The tool checks that the input files are committed, unchanged and not
empty, and that the declared combination is allowed. It does not establish that the 2 km stage or the
shared-sequence check was done, or in what order the files were committed. R.2 says a shared
sequence marks "the affected holdout" `EXPLORATORY`; `allowed_verdicts` now offers `EXPLORATORY` for
2 km with a `SHARED` check as well as for 10 km.

### R3.4 Routes that remain, under the promise

Rewriting history (amend, rebase, filter, a new clone), a commit date or author typed by whoever
commits, a hostile `.git/config` or hook that makes `git` start another program, a criterion first
written at the fixed path after a draft elsewhere, a criterion committed on a branch forked before
the freeze and never merged (evaluated on that branch the freeze is not in its history; Revision 4),
and statistics computed outside the tool. None
of these is chased further. The only date proof is an external timestamp of the freeze commit, which
is an owner action this revision did not take.

### R3.5 Earlier text edited in place by this revision

Struck through and marked above: the `criterion_path` parameter in R.4, the "committed before the
criterion" sentence of R2.2, the schema sentence, item 3 and the "wrong first commit" bullet of
R2.3. `git diff 0424e9c -- docs/benchmarks/FIT_HOLDOUT_PLAN.md` shows the whole change.

## Revision 4 (2026-10-31): merge routes and symbolic links closed, later routes listed not chased

Previous version: SHA-256 `dd2f800050a18b4da52369e4f62c9ef15fb8043bd2efc5f947b529e7b1e81535`
(Revision 3, commit 8b84914; earlier: `45d9088c...` at 0424e9c, `42a578f5...` at 8f57af9,
`6bf4238a...` at 8900748). New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`.

Reason, truthfully. The fourth review (`handoff/E0_qa4.md`) found two routes the guard did not
refuse, and Revision 3 contained a false statement.

- Finding 1: `git log -- path` simplified history, so a merge identical to one parent hid the other
  parent's commits. A side branch forked before the freeze, with another limit, could be merged
  (add/add with `checkout --theirs`; `-X ours` with a fast-forward; `-s ours` with a re-add) and the
  guard passed the side limit. Fixed: the history is read with `--full-history`, so a second
  distinct criterion signature anywhere in the reachable history of the path is refused.
- Finding 2: a symbolic link at the fixed path moved the history read to another path. Fixed: a
  symbolic link at the criterion path, the plan path or any named input is refused, in the working
  tree and in Git (mode 120000).
- Finding 4: Revision 3 said the 8-digit prefix of the plan hash is in the commit message. That was
  false (Revision 2 and R.1 said the same). The sentence is struck above; the full value is in the
  test and the config only.
- Finding 3 (a branch forked before the freeze and never merged) is named in R3.4 above.
- `docs/ALGORITHM_PROVENANCE.md` now states the promise (it was stale at Revision 2).

Decision of the owner: further routes round the guard are not chased in another fix round. They
go on a list of known limits, `docs/benchmarks/FIT_HOLDOUT_PLAN.md` R3.4 and
`docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md`. The promise (R3.1) is unchanged.

## Revision 5 (2026-11-01): retraction corrected, E1 procedure declared before B2B is read

Previous version: SHA-256 `b638aa1a6e0c65368c110817ccdbacc7ab4e317ef0e9d5013cdcb2e1b0e38bce`
(Revision 4, commit d52149a; earlier: `dd2f8000...` at 8b84914, `45d9088c...` at 0424e9c,
`42a578f5...` at 8f57af9, `6bf4238a...` at 8900748). New version: the pin in
`tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an
addendum: no earlier line is edited, and the strike-through notes of Revision 4 stay where they are,
corrected here. Reason: the fifth review (`handoff/E0_qa5.md`, finding 4) found that Revision 4
overcorrected.

### R5.1 The prefix retraction, corrected

Checked against `git log -1 --format=%B` of each commit:

- Revision 1 (R.1). The claim "the same value is in the commit message" was **true**: the message of
  8f57af9 holds the full SHA-256 `42a578f5c3e9d28d1fad69800416faa2330510c37007a7c56c7bc940d42d358a`.
  The Revision 4 note "false, no commit message holds it" is wrong for this revision.
- Revision 2. The message of 0424e9c holds the 8-digit prefix `45d9088c`, not the full value. The
  Revision 2 sentence was therefore partly true (prefix only), and the Revision 4 note "false" overstates;
  so does the Finding 4 bullet of Revision 4, which says the same of Revision 2 and R.1.
- Revision 3. No commit message holds `dd2f8000...` (neither the prefix nor the full value), so the
  Revision 4 note is right there: the Revision 3 sentence that the prefix is in the commit message was false.

Nothing here affects what the freeze guard checks; the pins in the test and the config are the record.

### R5.2 What Gate E1 will do on the captures, declared before any sample byte is read

State of knowledge now: the three files are present locally and have been hashed (orchestrator, and
by E1a with `verify_local_asset`); no sample of any file has been read, decoded, plotted or summarised
by the E1 Dev. E1 reads sample bytes **only** of `50G_PAM4_PD1_B2B_Subassembly1.bin`. On the 2 km and
10 km files E1 runs `verify_local_asset` (hashes) and nothing else: no header read, no size-based
decode, no statistic, no pattern analysis (R.3 is unchanged, and stricter than the one operation it
would allow). If a format check ever needs a holdout header, E1 stops and reports.

Format hypotheses are independent and byte-level: sample dtype (8, 16, 32, 64-bit signed and unsigned
integers; 32 and 64-bit floats), byte order, a leading header of 0 or of the size remainder (file size
minus the largest whole number of samples), and the Keysight BIN cookie test. A hypothesis is judged
by physical checks fixed now: finite values; a sample distribution with the level structure of a PAM4
waveform (four clusters, none empty) and not that of an unrelated byte stream; a power spectral
density that is smooth and rolls off within the 128 GHz Nyquist band for the claimed 256 GSa/s, with
content near 50 GHz consistent with 50 GBd; no value pinned at a rail beyond a small fraction of
samples; and wrong-dtype and wrong-endianness readings of the same bytes failing at least one check.
Acceptance rule: the sample layout is called supported only if exactly one hypothesis passes every
check and each wrong-endianness or wrong-dtype alternative fails one; a header that stays unexplained is
recorded as unexplained. Otherwise the status stays `FORMAT_UNKNOWN` (`BLOCKED: FORMAT_UNVERIFIED`) and
the report states what the exporter must supply. A plausible picture is not evidence. The scale stays
`normalized`: no volts, no optical power, unless a document says otherwise. The sample rate stays
INFERRED (the record says "256 Gbaud"); timing uses 256/50 = 5.12 samples per symbol as a nominal
ratio and nothing is rounded to 5.

## Revision 6 (2026-11-01): R5.2 departures recorded, holdout route rule, M4 rate stated

Previous version: SHA-256 `7b7f93dd20506d617ddc5245166c55cf44e605dbc23789a6644e2a2e16ec3185`
(Revision 5, commit 57643ca; Revision 4 `b638aa1a...`). New version: the pin in
`tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an
addendum: no earlier line is edited. Reason: the Gate E1 review (`handoff/E1_qa.md`, finding 3a) found
that E1 departed from R5.2, a pinned plan whose checks were "fixed now", and that the departures stood
only as notes in `MISSING_PARAMETERS.md` section 4 (or nowhere). A departure from a pinned plan is stated
in a dated section with a new pin, so it is stated here, as the reviewer listed it.

### R6.1 Departures from R5.2, each stated as it happened

1. **Nyquist roll-off check.** R5.2: "rolls off within the 128 GHz Nyquist band for the claimed
   256 GSa/s". E1 ran it on the header axis. The header time increment of the B2B file is 1/2.048 THz,
   so the stored stream has a 1.024 THz Nyquist band and its content ends near 80 GHz; under 256 GSa/s as
   the stored rate a 50 GBd signal would not fit. Disclosed in `MISSING_PARAMETERS.md` section 4 and
   nowhere in the plan until now.
2. **Samples per symbol in the timing code.** R5.2: "timing uses 256/50 = 5.12 samples per symbol as a
   nominal ratio". E1 timing uses **40.96 samples per symbol of the stored stream** (2.048 THz / 50 GBd),
   measured by a symbol tone at 50.000189 GHz (+3.8 ppm). 5.12 stays only as the nominal ratio of the
   record's inferred rate (`record_samples_per_symbol_nominal`); no code applies it to the stored stream.
   This was not disclosed as a departure; it is one. Nothing is rounded to 5 or to 41.
3. **A `continuous` check was added** to the physical checks (99.9th percentile of the first difference
   at most 1.5 standard deviations). R5.2 does not list it. E1 is one commit (12eb480); the repository does
   not record whether the check was written before or after the first B2B sample read, so it is treated as
   possibly post hoc. Effect on the verdict, reproduced in the fix round on B2B bytes only: without
   `continuous`, without the structure check and without the later scale check, 11 of the 84 hypotheses pass
   the remaining physical checks (`<f4@136`, `<f4@164`, `>f4@167` and the 4-byte integer readings); applying
   the level-structure check to each of them, as R5.2 words it, leaves `<f4@136` and `<f4@164` (four
   histogram peaks) and rejects the rest (two peaks for the integers, six for `>f4@167`). The same two survive
   with `continuous` and the survivor-only level check, and structure separates them. The check is
   outcome-neutral for the format.
4. **Level and tone checks were applied to the survivor, not to every hypothesis.** R5.2 judges each
   hypothesis by all its checks including the four-cluster level structure and the 50 GHz content. E1 applies
   the physical checks to every hypothesis, requires exactly one survivor, and applies the four-level and
   symbol-tone checks to that survivor (a wrong survivor would fail them: they are in `verify_b2b_format`
   with negative tests). Outcome-neutral for the format, by the reproduction in item 3.
5. **R2.2 metric M4 needs the sample rate, and it is stated now, before any freeze.** M4 (Welch distance,
   bins up to the baud rate) uses the **stored-stream rate read from the header, 1 / x_increment =
   2.048 THz for B2B**, as its frequency axis; 4096-sample segments therefore resolve 500 MHz and hold
   about 100 bins up to 50 GBd. The record's inferred 256 GSa/s is **not** used for M4. A length whose own header
   gives another increment, or none, is BLOCKED for M4, not converted. This changes no earlier line of R2.2.

### R6.2 Holdout route rule (what "hash only" means in code)

Every sample-reading route, including `opticps benchmark inspect-format --file <any path>`, passes one
gate first (`teriphic.gate_sample_read`): the registered file name of the resolved path (symbolic links
followed), any file under `data/external/` that is not the B2B file, and the MD5 and SHA-256 of the whole
file against the recorded holdout hashes, before any header or sample byte is returned. The file is hashed
for this (cost accepted). A renamed or copied holdout is refused by its hash whatever it is called. A file
that is neither a holdout nor registered is then checked on its own merits: structure and physical checks
are reported separately and a well-formed header alone is never "accepted". `ExternalCapture.open_*`,
`read_bin` and other generic readers called directly are not gated; that is a known limit
(`FREEZE_GUARD_KNOWN_LIMITS.md`), the plan's promise being procedural there.

## Revision 7 (2026-11-01): more R5.2 departures recorded, CLI route claim made exact, whole-record block pass

Previous version: SHA-256 `c1c274b99557d752a612770f4a20d707247ee474bf953adff2a44e87249eb225`
(Revision 6, commit 536b3ec; Revision 5 `7b7f93dd...`). New version: the pin in
`tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an
addendum: 0 lines are removed or edited from earlier text. Reason: the second Gate E1 review
(`handoff/E1_qa2.md`, findings 1 to 4). Everything below that was run on file bytes was run on
`50G_PAM4_PD1_B2B_Subassembly1.bin` only; the 2 km and 10 km files were not read.

### R7.1 The 64-bit integers declared in R5.2 are not in the code

R5.2 declares "8, 16, 32 and 64-bit signed and unsigned integers; 32 and 64-bit floats". The code's
`_ALLOWED_DTYPES` has 14 types and no 64-bit integer, so it evaluates 84 hypotheses (14 types x 6 offsets:
0, 136, 164, 165, 166, 167), not the declared set; Revision 6 did not say so. Not changed in code; recorded
here. Reproduced in this round on B2B bytes by calling `evaluate_hypotheses` with `<i8`, `>i8`, `<u8`, `>u8`
at the same six offsets (24 more readings): all 24 fail at least `plausible_scale` and `continuous`; eight of
them (`<i8` and `<u8` at 0, 136 and 164; `>i8` and `>u8` at 167) pass every other physical check
(finite, bounded, smooth, band-limited, not clipped, non-degenerate), with magnitudes near 5e18 to 1.4e19
file units; all eight show two histogram peaks (`level_structure`, every 8th value of the whole record), not
four, so the four-level structure R5.2 asks for rejects them too. The B2B result is unchanged by adding the
declared types (the same single survivor `<f4@164`). That was run after B2B bytes were seen, as was every
check in this revision; the departure itself dates from E1 (12eb480) and the repository cannot show whether
it was a decision made before or after the first B2B read.

### R7.2 `matches_declared_structure` changes the acceptance rule

R5.2: the layout is supported "only if exactly one hypothesis passes every check". On B2B two hypotheses,
`<f4@136` and `<f4@164`, pass every physical check (28 bytes are seven four-byte samples, which no statistic
separates; checked again this round: leaving out any other single check still leaves the same two or the
same one, so no other check decides between them). Under the literal rule the B2B result would be ambiguous,
that is `FORMAT_UNKNOWN`. E1 added a check, `matches_declared_structure` (the hypothesis equals the dtype and
offset that the parsed Keysight header declares), which leaves `<f4@164` as the only survivor and the result
`SUPPORTED_BY_EVIDENCE`. This is a change to the acceptance rule, **not** outcome-neutral: the verdict on
B2B depends on it. R5.2 lists "the Keysight BIN cookie test" among the hypotheses; reading that sentence as
covering the whole structural parse is possible but the plan does not say it, so this revision does not rely
on it. The E1 handoff describes the 136-byte reading as "rejected by structure only (statistics cannot tell,
7 samples)", which is how a result seen on B2B reads; the repository cannot show when the check was written,
so it is treated as added after B2B bytes were seen. The same rule applies unchanged to any later file.

### R7.3 Other additions and one correction, each with its effect on B2B

Added by E1 and not listed in R5.2 (R5.2 names finite values, four-cluster level structure, a smooth rolling-off
PSD, no value pinned at a rail, and wrong readings failing): offsets 164 to 167 (the declared offset plus one to
three bytes); `bounded` (largest deviation from the median at most 20 standard deviations); lag-1 `smooth`
(autocorrelation at least 0.5); `non_degenerate` (at least 16 distinct values); `plausible_scale` (largest
magnitude at most 1e6 and spread at least 1e-12 file units, added in the fix round after `handoff/E1_qa.md`,
that is after B2B bytes were seen); `continuous` is R6.1 item 3. Effect, reproduced this round on B2B for the
84 hypotheses: leaving out any one of `continuous`, `bounded`, `smooth`, `non_degenerate`, `plausible_scale`,
`not_clipped` or `band_limited` (with `matches_declared_structure` kept) leaves the single survivor `<f4@164`;
restricting the offsets to 0, 136 and 164 leaves the same survivor, so 165 to 167 are neutral on B2B. Leaving
out `matches_declared_structure` alone leaves two (`<f4@136`, `<f4@164`), see R7.2. Leaving out
`matches_declared_structure`, `plausible_scale` and `continuous` together leaves 11 (as R6.1 item 3); leaving
out these three plus `bounded`, `smooth` and `non_degenerate` leaves 15. The four-cluster check is still
applied to the survivor only (R6.1 item 4); this round did not show that all six removals together would be
neutral under a per-hypothesis level check, so the checks are recorded as additions of E1, each neutral alone.
The thresholds of these checks (0.5, 20, 16, 1e6, 1e-12, 1.5) were chosen by E1 with B2B bytes seen.

### R7.4 CLI route rule, exact claim

Revision 6 said "Every sample-reading route ... passes one gate first". The second review found
`opticps ingest-uxr --input <file>` decoding all samples of a holdout-named fixture before any gate. The claim
is now: **every CLI route that takes a path is gated; library code is not.** `src/opticps/cli/main.py`
holds `ROUTES`, built by reading each handler and its call graph rather than option names. A path option is
"gate": `main` runs `teriphic.gate_sample_read` (name of the resolved path, `data/external`, MD5 and
SHA-256 of the whole file against the recorded holdout hashes) on the file, or on every file under a folder
argument, before the handler starts; "handler": the handler gates it itself; or "no read" with the reason.
The routes that can reach file contents of a user-supplied path, by command and option:
`generate` (--config, --output); `validate` (--captures, --output); `simulate` (--config, --output);
`fiber-validate` (--config, --output); `ingest` (--input); `ingest-uxr` (--input, --sidecar, --registry,
--output); `compare-uxr` (--results); `uxr-report` (--results, --simulation, --output); `analyze` (--input,
--output); `compare` (--results); `report` (--results); `slides` (--results); `demo` (--output, --results);
`benchmark inspect-format` (--file, and --metadata before the sidecar is read; `--metadata-only` opens
nothing). Options listed "no read" (written only, or unused by the handler) are in `ROUTES` with the reason.
A test walks the parser and fails on a path option that is neither in `ROUTES` nor refused, and a second test
runs each gated route on holdout fixtures by name, by injected SHA-256 and by injected MD5, with the readers
forbidden. Files that are not holdouts behave as before; the cost is one hash pass over each file named. When
the register YAML cannot be found (an installed copy), the CLI falls back to the registered holdout names,
`data/external` and the recorded SHA-256, which is narrower. `read_bin`, `ExternalCapture.open_keysight_bin`,
`ExternalCapture.open_raw` and the other library readers stay generic and stay in the known limits, as does
the time-of-check to time-of-use swap (deliberate only, under the promise). `data/external` and the holdout
names are now compared case-insensitively and Unicode-normalised, as this file system does.

### R7.5 Whole-record block pass for files the user supplies (not B2B-verification, not a holdout route)

The non-B2B file inspection no longer rests on three slices (2.6 % of a B2B-sized file). It streams the whole
record in fixed blocks of 65,536 samples (a remainder under 4,096 samples is folded into the last block), one
block in memory at a time, and every block passes the same checks: finite; magnitude (largest at most 1e6,
spread at least 1e-12 file units); largest deviation from the block median at most 8 times a robust scale
taken from the record (the median over blocks of 1.4826 x MAD; not an absolute limit); block robust spread
between 0.5 and 2 times that record scale; lag-1 autocorrelation at least 0.5; top 40 % of the spectrum at
least 20 dB below the peak; 99.9th percentile of the first difference at most 1.5 standard deviations; at most
0.1 % of samples at the extremes; at least 16 distinct values. The output states blocks checked, blocks
failed, coverage as a percentage computed from the samples in checked blocks over the record, and what was
tested; it says that the pass makes no four-level claim (a ramp, NRZ and a 16-level waveform pass it, tested)
and it no longer prints a bare "physical pass". It never runs on a holdout here (the gate comes first).
Thresholds on B2B (625 blocks, none failed, coverage 100 %; record scale 0.00844 file units), with the
margin:

| quantity | B2B worst block | limit | margin |
| --- | --- | --- | --- |
| lag-1 autocorrelation (minimum) | 0.99903 | 0.5 | 0.5 |
| top-band level over peak (maximum) | -94.96 dB | -20 dB | 75 dB |
| 99.9th percentile of the first difference over std (maximum) | 0.131 | 1.5 | 11.5 x |
| samples at the extremes (maximum) | 7.6e-5 | 1e-3 | 13 x |
| distinct values (minimum) | 16,243 | 16 | 1,000 x |
| largest deviation over record scale (maximum) | 2.50 | 8 | 3.2 x |
| block spread over record scale | 0.963 to 1.090 | 0.5 to 2 | 1.9 x low side, 1.8 x high side |
| largest magnitude (maximum) | 0.0204 | 1e6 | file units |

The first five limits are those of the earlier waveform checks (R7.3 says when they were set); 8, 0.5, 2 and the
block size were chosen in this round after the B2B block statistics were seen, each with the margin above, and
with no other file used. Cost on B2B (this machine): the pass takes 3.1 s (4.6 s under `tracemalloc`) after
the 0.9 s hash and open; peak Python heap 4.7 MB; peak resident set of the process 196 MB, which is the mapped
file pages the system can drop (the process was at 27 MB before the pass). Limits of the pass: a legitimate
capture that differs strongly from B2B (burst traffic, a long idle gap) can be refused, and a capture that
passes is not thereby a verified capture.

## Revision 8 (2026-11-01): the route claim narrowed, limits of the block pass, two corrections

Previous version: SHA-256 `87e3839513df645930d026a0eef78360058881563b1cb85a3f5d1726aed4bb80`
(Revision 7). New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. Reason: the third Gate E1 review (`handoff/E1_qa3.md`, findings 1 to 6). Anything run on file
bytes here was run on `50G_PAM4_PD1_B2B_Subassembly1.bin` only.

### R8.1 The route claim, narrowed by the owner

Revision 6 (R6.2) said that every sample-reading route passes one gate first, and Revision 7 (R7.4) said
that every CLI route that takes a path is gated. Both statements are replaced by this one: **only paths
typed as CLI options are gated.** The owner chose this narrower claim after three review rounds showed that
the wider claim would not close: a gated option can name or lead to another path. These are not gated, and
no gate is added for them: paths found inside files (a YAML such as `demo_config` and `demo_results` in a
fiber-validation config, a manifest's `waveform_filename`, a sidecar, the leakage registry); links inside
folders; paths built at run time (a profile name joined to a folder, `--profile ../outside`); derived and
default paths (`slides --results` reading the fiber results file, `demo` reading its default config, the
default registry path). Library code is not gated either (unchanged). Where the earlier wording of R6.2 or
R7.4 says more, this section replaces it; no earlier line is edited. `ROUTES` in `src/opticps/cli/main.py`,
the module docstrings and `FREEZE_GUARD_KNOWN_LIMITS.md` now carry the narrower wording, and each route the
review ran is listed there concretely. The review found that none of these routes decodes samples as
numbers, but they read whole files and an error message can echo a header byte (byte 4, 0x88 on the
review's fixture); that is stated in the known limits and not softened. R5.2 allows hash only for the
holdouts, with no header read; on those routes that is not enforced by the code. Holdout integrity for
scoring rests on `require_frozen_criterion` at E2, not on these gates.

### R8.2 A file that changes during the block pass

The R7.5 block pass checked the file once before the loop. It now checks again after the loop, so an
overwrite of a block that was already scanned (size or modification time changed) is reported and the
result is refused. A change that keeps size and modification time is not seen; that is a deliberate-only
route under the promise.

### R8.3 What the block pass misses

R7.5 says the pass screens for corruption. Built from 2^22 B2B samples by the third review, these pass it:
a flat run of 20,000 samples inside one block (31 % of the block); a flat run of 40,000 samples straddling two
blocks; a white-noise burst of 200 samples inside a block and one of 400 straddling two, both at one standard
deviation; a single spike of 7.9 times the record scale (3.3 times the record peak, under the limit of 8);
one block at gain 0.55 or 1.9 (inside the limits 0.5 and 2); a block inverted, reversed or replaced by another
block; 60 % of the blocks replaced by a slow sine of similar spread. More than half the blocks at a gain above
2 do fail, because the record scale follows the median, so poisoning the scale buys no more than the factor of
2 limit. A record of one block has only its own scale (spike and spread compare with itself; the block count
of 1 is printed). The pass is a screen for gross corruption and nothing more.

### R8.4 Correction to the R7.2 parenthetical

R7.2 says that leaving out any other single check "still leaves the same two or the same one". That is inexact
when `matches_declared_structure` is also dropped. Reproduced on B2B this round (84 hypotheses): with
`matches_declared_structure` dropped, also leaving out `continuous` leaves 3, `non_degenerate` 4 and `finite`
16 survivors; leaving out `band_limited`, `bounded`, `not_clipped`, `plausible_scale` or `smooth` leaves the
same 2. With `matches_declared_structure` kept, leaving out any one other check leaves the single survivor
`<f4@164`. The sentence that no other check decides between `<f4@136` and `<f4@164` holds, and the R7.3
statement (that check kept: one survivor) is unchanged.

### R8.5 Two thresholds set after B2B was seen

`UPSAMPLE_PERIOD_MIN` (1.02) and `UPSAMPLE_CONTROL_MULTIPLE` (3.0), the pass criterion of the labelled
integer-upsampling reading (R7.3 and the minor 9 fix of the second round), were chosen after B2B bytes had been
seen (B2B period-8 ratio 1.118 against controls of 1.0002 and 1.0001), together with a fixture upsampled
eight-fold by windowed-sinc interpolation (1.066) and one without upsampling (1.003 against controls of
1.006). Revision 7 did not say so. They affect only the wording of the labelled reading and never the format
status.

## Revision 9 (2026-11-02): an E2 obligation stated as one, a shrinking file, link wording

Previous version: SHA-256 `37487f3b59cd69ceed8344aeb605d3625322fdaaafbce850702e4f9bd96af058`
(Revision 8). New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. Reason: the closing Gate E1 review (`handoff/E1_qa4.md`). No code changed in this revision.

### R9.1 `require_frozen_criterion` is an E2 obligation, not a present guard

R8.1 says that holdout integrity for scoring "rests on `require_frozen_criterion` at E2". That reads as a
fact about today. It is not one: the function exists and refuses when it is called, but it has no caller in
`src` or `scripts`, no scorer exists for it to guard, and nothing in the code makes a future scorer call it.
Today it refuses nothing. The corrected statement: it is an E2 obligation. E2's scoring entry point must call
`require_frozen_criterion` before it computes any holdout statistic, and until E2 nothing enforces that.
`FREEZE_GUARD_KNOWN_LIMITS.md` and `handoff/E1_dev.md` carry the same correction.

### R9.2 A file that shrinks during the block pass

R8.2 says that a change during the block pass is reported. That holds for an overwrite and for growth. A file
that shrinks while the pass runs ends the process with a bus error (SIGBUS) and no message, because the
mapped pages are gone; the review reproduced it with a truncation injected during the pass. It fails closed,
since no pass is printed, but it is not reported. No code change; the words are corrected here and in the
known limits.

### R9.3 Links inside folders

R8.1 lists "links inside folders" as not gated. Narrower and exact: a link to a file inside a typed folder is
gated (the gate resolves it, so a holdout reached through a file link is refused); a link to a folder inside a
typed folder escapes, because the walk does not enter it. R8.1 under-claimed here, in the safe direction.

### R9.4 One-block records

The re-check after the loop (R8.2) is also tested on a record of one block, where the earlier test used
several blocks.

## Revision 10 (2026-11-02): Gate E2 part a, the scoring entry point, the model, the frozen criterion

Previous version: SHA-256 `9e7b51adade3a3ecdc4ca855f5f919747b1aab27ca8e2f857884fb1345feef24` (Revision 9, commit 1e1e90a; earlier pins are listed in the
tests). New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. Reason: Gate E2 part a builds everything needed to score the holdouts up to and
including the frozen criterion. The criterion file `docs/benchmarks/TERIPHIC_CRITERION.yaml` is
committed after this revision, in the next commit; the commit that first holds it is the freeze
(R2.3, R3.2).

### R10.0 State of knowledge

No sample, header, size-based decode or statistic of the 2 km or 10 km file was read, hashed or
produced in this gate: the Dev ran no code on either file. Everything below was computed from the
B2B capture (`50G_PAM4_PD1_B2B_Subassembly1.bin`, characterisation role) and from code. The B2B
windows used are named in R10.3. The scorer was written and tested on synthetic fixtures; it has
never run on a holdout. That is E2b, after independent review of this part.

### R10.1 The scoring entry point: R9.1 now has a caller

`opticps.benchmarks.e2_score.score_holdout` is the scoring entry point. It is the only code in `src`
that reads a sample of a holdout. In this order, refusing at the first failure (every refusal is a
`BenchmarkError`):

1. the registered name of the resolved path must be the 2 km or 10 km asset (nothing is opened);
2. `require_frozen_criterion`, with the inputs of `holdout.REQUIRED_INPUTS` (2 km: `b2b_model`,
   `scenario_list`; 10 km: `frozen_parameters`, `selected_scenario`, `evaluation_script`, and the 2 km
   stage declared). This precedes every hash, header read and statistic;
3. the committed model, scenario list and pre-registration are read from `HEAD` bytes, agree with the
   hashes the guard computed and with each other, hold no filled result column, carry the frozen
   limits, and the working code equals the code identity of R10.4;
4. the holdout's MD5 (against the register) and SHA-256 (against `teriphic.HOLDOUT_SHA256`) are
   verified at read time on the whole file; a mismatch refuses before the file is opened;
5. only then the header and the fixed window are read, through `ExternalCapture`, with the B2B
   comparator read through the existing gate (`gate_sample_read`, B2B by MD5).

A source scan test keeps the claim: the readers (`open_keysight_bin`, `open_raw`, `read_bin`,
`read_scope_file`) are called in `src` only by `e2_score.py`, `teriphic.py` (the B2B adapter and the
gated inspection route), `uxr_import.py` and `uxr_ingest.py` (the CLI-gated UXR route); inside
`score_holdout` the guard call precedes every reader, hash and gate call. `holdout.py` is unchanged.
`FREEZE_GUARD_KNOWN_LIMITS.md` now says the guard has a caller and still says what that does not
cover: code that calls the generic readers directly, statistics computed outside the entry point, and
the routes it lists. The promise of R3.1 is unchanged and is not widened.

### R10.2 The model, and what it predicts

OpticPS predicts what the 2 km and 10 km captures should show from B2B-calibrated quantities and an
IM/DD chain with fibre, using only metrics that need no transmitted bits (`e2_model.py`). It is a
seeded surrogate: independent symbols drawn with stated level probabilities, a zero-phase lumped pulse
whose magnitude is the square root of the B2B Welch spectrum, four level values and one noise standard
deviation fitted on B2B, then (by scenario) the small-signal dispersion response
`cos(pi * lambda^2 * D * L * f^2 / c)` of a chirp-free modulator, an amplitude ratio at the receiver,
and noise either unscaled (receiver dominated) or scaled with the signal. It is never driven by a
sequence recovered from B2B (R2.4): the drivers are the seeds and the level probabilities.

Parameters, with provenance. Fitted on the B2B fit window only (`RAW_CAPTURE` statistics or `INFERRED`
fits): the affine normalisation (`c0` = -0.00018433985085895875, `g0` = 0.006999456322514625 in file units), the
spectrum shape (2049 bins), the four pulse levels [-1.680156, -0.480633, 0.593506, 1.679634] and the
noise standard deviation 0.241526 (normalised units; the fit is a 5-parameter
Nelder-Mead polish of M1 + M2 + M3 + 0.05 M4 against the fit window, seed 20261101).
Fibre length is `PUBLISHED_MEASUREMENT` (the file names: 2 and 10 km). Declared, not fitted:
level probabilities uniform and symbols independent (the record states neither).

Declared UNKNOWN, never tuned on a holdout: wavelength (O-band only; 1310 nm enters only as lambda
squared of the dispersion response), fibre type, dispersion, fibre loss and launch power, modulator
chirp, modulation depth and optical offset, the phase of the lumped TX and RX response, the split of
B2B noise into signal-borne and receiver noise. Dispersion enters as a finite list of scenarios
bounded by the ITU-T G.652.D limit envelope for 1260 to 1360 nm (the largest |D| of
`optical_channel.fiber.g652d_dispersion_limits` is 6.352 ps/(nm km), `SPECIFICATION_LIMIT`; the
sign does not matter for zero chirp), each labelled `ASSUMED_G652D`, never ground truth. Loss enters
as 0 dB/km (received amplitude equal to B2B, an assumption: launch power and any re-tuning between
lengths are unknown) or the G.652 Table I.1 typical link value 0.5 dB/km (representative, not
measured on this fibre). Chirp and launch power are not identifiable from B2B: chirp is set to zero in
every scenario and recorded as `MODEL GAP: CHIRP` (a FAIL does not refute fibre dispersion, and a PASS
does not validate the chirp-free assumption); launch power is carried only through the amplitude
scenario. The surrogate is also small-signal (`MODEL GAP: LARGE_SIGNAL`), zero-phase (`PHASE`) and
puts the noise origin in a scenario (`NOISE_ORIGIN`). No timing or jitter metric is chosen: timing
operations on the holdouts are barred before the freeze (R.2, R.3) and B2B does not identify jitter
separately from the lumped response. BER and SER stay `REFERENCE_SEQUENCE_MISSING`;
`estimated_decision_error_proxy` is not computed here and is not a BER.

### R10.3 The frozen criterion

Metrics. The four metrics are those of R2.2, unchanged, now implemented in `e2_metrics.py`
(estimator ids `holdout.ESTIMATORS`). Choices that R2.2 left open, fixed here: quantiles by one sort
and linear interpolation `h = (n - 1) p` (Hyndman-Fan type 7); k-means by sorted partition with the
R2.2 start and stop, an empty cluster refused; M4 by `scipy.signal.welch` with the R2.2 arguments,
bins `f <= 50 GHz` (101 bins, DC bin included), frequency axis from the header time increment,
`1 / 4.8828125e-13 s = 2.048 THz` (R6.1 item 5; a length whose header gives another increment is
`BLOCKED`); a non-finite value, a window under 32768 samples, a non-positive spectral bin or a
degenerate level estimate is refused, never scored.

Why each can fail and why it separates the fibre model from a copy of B2B (measured against the
pre-registered separations below, which are computed from B2B only):

- M1, level spacing (L-infinity norm of the change of the three centroid gaps, in B2B gap units):
  moves with the received amplitude (a loss scenario shrinks every gap) and, weakly, with
  dispersion-induced level compression. A B2B copy has gap change zero by construction.
- M2, amplitude Wasserstein-1: moves with amplitude scale and with ISI spread. A B2B copy keeps the B2B
  distribution, so it fails when the true distribution moved.
- M3, quantile error at 1, 5, 25, 50, 75, 95, 99 %: sensitive to tails, hence to scale and to
  ISI-induced tail change; a copy cannot follow either.
- M4, log-spectral distance up to the baud rate: the only metric that sees a dispersion notch or
  low-pass (a null near 37 GHz at 10 km for the largest |D|); also moves with amplitude by a uniform dB
  offset. A B2B copy has the B2B spectrum.

Windows (indices into the stored stream of 40,959,993 samples, end exclusive, 2.048 THz stored rate,
40.96 samples per symbol): fit [0, 8,388,608); spread [8,388,608, 12,582,912); evaluation
[16,777,216, 20,971,520), 4,194,304 samples = 102,400 symbols. The measured holdout window and the
B2B comparator window are the evaluation window. Seeds: fit 20261101, prediction symbols
20261102, prediction noise 20261103 (the same for every scenario
and length, so scenarios differ only by their channel).

Normalisation: x_norm = (x - c0) / g0 with the values above, applied unchanged to every length. No
length is rescaled on its own.

Thresholds. For each metric, `b2b_basis` = the larger of (a) the metric between the real B2B evaluation
window and the surrogate's no-fibre prediction of the same size (the model's misfit on B2B) and (b)
the metric between the real B2B spread window and the real B2B evaluation window (B2B internal
spread). Multiplier 2.0 for all four. Limit = basis times multiplier (checked by the guard to 1e-9).
These numbers are in the criterion file and below:

| Metric | (a) surrogate misfit | (b) B2B spread | basis | multiplier | limit |
|---|---|---|---|---|---|
| M1 | 0.0132928 | 0.00556163 | 0.0132928 | 2 | 0.0265857 |
| M2 | 0.01728 | 0.00272728 | 0.01728 | 2 | 0.0345599 |
| M3 | 0.044923 | 0.00841582 | 0.044923 | 2 | 0.0898461 |
| M4 | 0.614603 | 0.0805081 | 0.614603 | 2 | 1.22921 |

A window is within the criterion if and only if all four metrics are less than or equal to their
limits (R2.2). psi = the largest ratio of a metric to its limit; within the criterion means psi <= 1.

Scenarios (9, counted; `scenario_list.yaml`): |D| in {0, 3.176, 6.352} ps/(nm km) crossed with
amplitude {matched (0 dB/km), 0.5 dB/km with receiver noise, 0.5 dB/km with signal-borne noise}. The
scenario with D = 0 and matched amplitude is the no-fibre control. At 2 km the scorer scores all nine
and chooses the one with the smallest psi (ties go to the earlier in the list); that choice is the
2 km stage's selection and is written to `selected_scenario.yaml` by E2b, never by this gate. At 10 km
only that scenario and the control are scored.

Comparator, the B2B copy. The B2B evaluation window, normalised as above, scored against the holdout with
the same four metrics and the same limits.

Outcome, per length. FAIL if the chosen scenario is outside the criterion. Otherwise
`PASS, NOT DISCRIMINATING` if the B2B copy is also within the criterion, or the chosen scenario is the
control, or the control is also within the criterion; otherwise `PASS, DISCRIMINATING`. The result of
a model that cannot beat the copy is therefore never a bare PASS. Verdicts (`holdout.Verdict`):
FAIL gives FAILED; `PASS, NOT DISCRIMINATING` gives UNIDENTIFIABLE_PARAMETER when no scenario was
separable from the copy for that length in advance (R10.5) and INCONCLUSIVE otherwise;
`PASS, DISCRIMINATING` at 2 km gives no verdict ("within criterion at the selection stage", R.5) and at
10 km gives VALIDATED only if `allowed_verdicts` offers it for the declared stage, shared-sequence
check and file state, INCONCLUSIVE otherwise. A header sample rate that differs from the model's, or
a record shorter than the window, gives BLOCKED.

### R10.4 Code identity (narrow, as the guard's estimator ids are)

The code identity of E2 is the SHA-256 of these files as committed at the freeze:

- `src/opticps/benchmarks/e2_metrics.py` `3089b5f844339b177f26bdb00b82396f2aca36f042e7dcdf66995ebb42719608`
- `src/opticps/benchmarks/e2_model.py` `3280f591800437de21a546c471240a6d1e7fa3b503e4179a20a55cd732bbcdd0`
- `src/opticps/benchmarks/e2_score.py` `7f71324f5330a09cd5a7668bb27961b700ff5da4f8b162bdaba7aa795a94c720`
- `src/opticps/benchmarks/holdout.py` `11afae5ab55787751947361f27dcd29fb8f52a0510d5a8c1adbb7abdc0c77542`
- `src/opticps/benchmarks/external_capture.py` `7b64d0b8e4672319e478ddd0d6f0dc65b6fb2f4b2599a8263b63b675a34044b3`
- `src/opticps/benchmarks/teriphic.py` `8b1765030f8289fa8f40db66878e9d3554fecab2b99bf4921895b2f8e77adeee`
- `src/opticps/benchmarks/provenance.py` `65a58540920cfabfcdef1c4f9934c1886b0ba752dfb50428ba2bcdf639976b6d`

The scorer refuses when the working bytes of any of them differ from the table recorded in
`b2b_model.yaml` (a file the guard hashes). That is all it covers: not the Python interpreter, NumPy,
SciPy, the operating system or any module not listed, and not the tests or scripts. Estimator ids still
label estimators and do not verify code (module docstring of `holdout.py`). The only guard against
library or platform drift is the reproduction tolerance of R10.5. The data files of the freeze are
`docs/benchmarks/teriphic_e2/b2b_model.yaml` `0ca7db7349c909f7566ae4d7534ffae0076722f41595790f17888d953cbf70bb`,
`scenario_list.yaml` `bbacd37e100b7339c2ad6b43ee01b600ade9ab0d5d2164f967b903e8140ae986` and `preregistered_predictions.yaml`
`1c8cd7f022974b9743e175def34f30841139e922bee2a017fb1826357bab04b7`. A change to any listed file after the freeze needs a
new revision and a new criterion, which the guard refuses to accept as the same freeze.

### R10.5 Pre-registered predictions

`docs/benchmarks/teriphic_e2/preregistered_predictions.yaml` holds, for each length (2 and 10 km) and
scenario, the predicted level centroids, gaps, shares, standard deviation, the seven quantiles of M3
and the spectrum in ten 5 GHz bands relative to its peak, and the four metrics between that prediction
and the B2B copy (the separation). It was committed before any holdout read, from B2B and code alone;
its `results` key is null and no result column exists. The scorer recomputes every value and refuses
when one drifts by more than a relative 1e-6 (absolute 1e-9). Separation, with psi against the limits
above (separable means psi > 1 and not the control):

| Length | Scenario | M1 | M2 | M3 | M4 (dB) | psi | separable | predicted gaps |
|---|---|---|---|---|---|---|---|---|
| 2 km | D0_MATCHED | 0.0133 | 0.0173 | 0.0449 | 0.615 | 0.500 | no | 1.051, 0.976, 0.986 |
| 2 km | DHALF_MATCHED | 0.0116 | 0.0171 | 0.0448 | 0.613 | 0.499 | no | 1.049, 0.974, 0.985 |
| 2 km | DMAX_MATCHED | 0.0084 | 0.0166 | 0.0446 | 0.733 | 0.596 | no | 1.044, 0.969, 0.980 |
| 2 km | D0_LOSS_RX_NOISE | 0.1959 | 0.1805 | 0.3588 | 1.882 | 7.368 | yes | 0.842, 0.776, 0.798 |
| 2 km | DHALF_LOSS_RX_NOISE | 0.1971 | 0.1808 | 0.3609 | 1.946 | 7.415 | yes | 0.840, 0.775, 0.796 |
| 2 km | DMAX_LOSS_RX_NOISE | 0.2007 | 0.1817 | 0.3663 | 2.168 | 7.551 | yes | 0.837, 0.772, 0.793 |
| 2 km | D0_LOSS_SIGNAL_NOISE | 0.2054 | 0.1882 | 0.4274 | 2.006 | 7.726 | yes | 0.835, 0.775, 0.783 |
| 2 km | DHALF_LOSS_SIGNAL_NOISE | 0.2066 | 0.1885 | 0.4295 | 2.072 | 7.772 | yes | 0.833, 0.774, 0.782 |
| 2 km | DMAX_LOSS_SIGNAL_NOISE | 0.2100 | 0.1894 | 0.4354 | 2.303 | 7.899 | yes | 0.830, 0.770, 0.779 |
| 10 km | D0_MATCHED | 0.0133 | 0.0173 | 0.0449 | 0.615 | 0.500 | no | 1.051, 0.976, 0.986 |
| 10 km | DHALF_MATCHED | 0.0294 | 0.0220 | 0.0474 | 3.600 | 2.928 | yes | 1.019, 0.943, 0.959 |
| 10 km | DMAX_MATCHED | 0.0641 | 0.0456 | 0.0876 | 5.086 | 4.138 | yes | 0.978, 0.902, 0.934 |
| 10 km | D0_LOSS_RX_NOISE | 0.6273 | 0.5786 | 1.1370 | 8.305 | 23.594 | yes | 0.410, 0.371, 0.403 |
| 10 km | DHALF_LOSS_RX_NOISE | 0.6324 | 0.5817 | 1.1475 | 9.471 | 23.788 | yes | 0.405, 0.367, 0.398 |
| 10 km | DMAX_LOSS_RX_NOISE | 0.6373 | 0.5899 | 1.1584 | 9.993 | 23.972 | yes | 0.400, 0.360, 0.393 |
| 10 km | D0_LOSS_SIGNAL_NOISE | 0.7052 | 0.6263 | 1.3933 | 9.930 | 26.526 | yes | 0.332, 0.308, 0.312 |
| 10 km | DHALF_LOSS_SIGNAL_NOISE | 0.7151 | 0.6296 | 1.4046 | 12.351 | 26.899 | yes | 0.322, 0.298, 0.303 |
| 10 km | DMAX_LOSS_SIGNAL_NOISE | 0.7283 | 0.6400 | 1.3947 | 13.767 | 27.396 | yes | 0.309, 0.285, 0.296 |

What this says before any data is seen. At 2 km no matched-amplitude scenario is separable from the B2B
copy (psi 0.50 to 0.60), so a 2 km capture whose amplitude equals B2B reads `PASS, NOT DISCRIMINATING`
whatever its dispersion, if it passes at all; only a received-amplitude change makes 2 km separable.
At 10 km the matched-amplitude dispersion scenarios are separable through M4 (psi 2.93 for half the
|D| bound, 4.14 for the bound). The criterion can therefore fail, and can pass without discriminating.
It says nothing about the true fibre.

### R10.6 What is not done here

E2a does not run the scorer on a holdout, does not create `selected_scenario.yaml`, does not run the
shared-sequence check, and does not compute any BER, SER or proxy. E2b, after independent review of
this part, runs the 2 km stage (selection among the nine scenarios, no VALIDATED), then writes
`selected_scenario.yaml`, commits it, and only then the single 10 km evaluation. A change after a
result is seen burns the file (section 2). The generic readers stay ungated (known limits).

## Revision 11 (2026-11-02): the freeze is bound to its inputs; the first freeze is superseded

Previous version: SHA-256 `1bd5bbad62efbc92f8a54e67e0e08de208a1d455247a512a592e196f7a8a4f3e` (Revision 10, commit 1b496d2; Revision 9 is `9e7b51ad...`). New
version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. Reason: an automated security review of Gate E2 part a found that the freeze of Revision
10 was not bound to its inputs.

### R11.1 The finding, verified

`require_frozen_criterion` proves that the criterion, the plan and the named inputs are committed and
equal to `HEAD`. It does not prove they are what existed at the freeze commit. After the freeze, a
model, its pre-registration (which is not a guard input), the code-identity table inside the model
and the listed code files could be replaced together, each commit consistent with the others, and the
scorer would accept them: its checks compared the model with the guard's hash of the same current
bytes, the registration with the current model, and the code with the table inside the current model.
Reproduced by tests added in this revision (model and registration replaced together; code, table and
registration replaced together). The `selected_scenario` file, which is added after the freeze by
design, had no rule at all. Both parts apply.

### R11.2 The fix

`e2_score.bind_to_freeze` reads each of these files at `frozen.commit` and requires its bytes to equal
the committed bytes at `HEAD`: `b2b_model.yaml`, `scenario_list.yaml`,
`preregistered_predictions.yaml`, `scripts/score_teriphic_e2.py` and every file of
`CODE_IDENTITY_FILES`. A file that did not exist at the freeze commit is refused, and the freeze commit
must be an ancestor of `HEAD`. It runs straight after `require_frozen_criterion`, before any hash or
read. `e2_score.read_selected_scenario` requires `selected_scenario.yaml` to be absent at the freeze
commit, to be touched by exactly one commit in the full history (so it is added once and never
changed, deleted or re-added), that commit to descend from the freeze commit, and the committed
bytes to equal that commit's bytes. Negative tests cover each case (model plus registration, scenario
list, registration, code plus table plus registration, code alone, evaluation script, a file missing at
the freeze, selected scenario changed, deleted and re-added, present at the freeze, added on a side
branch, wrong type); `scripts/mutate_e2.py` has mutants for each branch. The bytes compared are in the
local Git history: this inherits the promise of R3.1 and does not widen it (history rewriting,
backdating and the other routes of the known limits are unchanged).

### R11.3 The first freeze is superseded

The criterion committed at `docs/benchmarks/TERIPHIC_CRITERION.yaml` in commit d520ff7 froze Revision
10 and a scorer without R11.2. Git history cannot be rewritten here, and the guard refuses any change of
a criterion at its path (R3.2). `holdout.CRITERION_PATH` is therefore changed to
`docs/benchmarks/TERIPHIC_CRITERION_R11.yaml` (the one edit to `holdout.py`; R3.2 allows a new path only
by a plan revision, and this is it). The file at the old path stays in the repository as a record, is
ignored by the guard (a file at any other path is not a criterion), and must not be used. Revision 10
stands for everything else: metrics, windows, seeds, scenarios, thresholds, comparator, outcome rules and
the pre-registered values are unchanged (the limits are the same numbers; the model was refitted by
the same deterministic procedure and gave the same values). Only the code-identity table and the data
hashes of R10.4 are replaced by these. The criterion at the new path is committed in the commit after
this revision; the commit that first holds it is the freeze. R10.1 says `holdout.py` is unchanged;
that sentence is superseded by R11.3.

Code identity (SHA-256 of the files as committed at the new freeze; the scorer refuses any difference,
and R11.2 additionally compares them with the freeze commit):

- `src/opticps/benchmarks/e2_metrics.py` `3089b5f844339b177f26bdb00b82396f2aca36f042e7dcdf66995ebb42719608`
- `src/opticps/benchmarks/e2_model.py` `3280f591800437de21a546c471240a6d1e7fa3b503e4179a20a55cd732bbcdd0`
- `src/opticps/benchmarks/e2_score.py` `ccd13e6279b1a67a3c606edee6a2cc832283f3482289685ab4d07547c4113f8d`
- `src/opticps/benchmarks/holdout.py` `986a475b357af71648b22db89ad6873c4459677614608c3d325ad5ddd9860964`
- `src/opticps/benchmarks/external_capture.py` `7b64d0b8e4672319e478ddd0d6f0dc65b6fb2f4b2599a8263b63b675a34044b3`
- `src/opticps/benchmarks/teriphic.py` `8b1765030f8289fa8f40db66878e9d3554fecab2b99bf4921895b2f8e77adeee`
- `src/opticps/benchmarks/provenance.py` `65a58540920cfabfcdef1c4f9934c1886b0ba752dfb50428ba2bcdf639976b6d`

Data files: `b2b_model.yaml` `ed142aacb59721b149bc24b884edd906974ff253068bf3d6db75e1814e5129ab`, `scenario_list.yaml`
`bbacd37e100b7339c2ad6b43ee01b600ade9ab0d5d2164f967b903e8140ae986`, `preregistered_predictions.yaml` `31132e9c0d5cfcb50dcbe8a2685ae538e1183657ebd85cbada97594b6f2d4a3d`.

### R11.4 Still true

No 2 km or 10 km sample, header or hash was read or produced at any point of Gate E2 part a; the scorer
has never run on a holdout. The tests of R11.2 use synthetic repositories only.

## Revision 12 (2026-11-02): R11 reviewed, failed and never scored; criterion redesigned after a power study; new freeze

Previous version: SHA-256 `554fd2b624878eee7d0599d323ab8a4788e7bdf22d8cb6200fab5ea6df887d4d` (Revision 11, commit 9976d3b; Revision 10 is `1bd5bbad...` at 1b496d2).
New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. The criterion file is committed in the commit after this revision, at
`docs/benchmarks/TERIPHIC_CRITERION_R12.yaml`; the commit that first holds it is the freeze.

### R12.0 What happened to R10 and R11

Revision 10 (freeze d520ff7) was superseded by Revision 11 (freeze 007b8b2) after a security finding.
The independent review of Revision 11 (`docs/orchestration/opticps-v2/handoff/E2a_qa.md`, verified at
df7fdc1) returned **FAIL**: 2 BLOCKER, 5 MAJOR, 4 MINOR and 1 OBSERVATION. Revision 11 was reviewed,
failed and **never scored**: no 2 km or 10 km sample, header or hash was read or produced by any
code at any point, before or after that review. Its criterion file (`TERIPHIC_CRITERION_R11.yaml`)
and the first one (`TERIPHIC_CRITERION.yaml`) stay in the repository as records, are ignored by the
guard (another path is not a criterion) and must not be used. Since no holdout has been read, a new
revision and a new freeze are legitimate. The findings and their fixes:

| # | Finding (review) | Fix | Test |
|---|---|---|---|
| 1 | a side commit with the same criterion bytes became "the freeze" | `expected_freeze_commit` is a required argument of `score_holdout` and the script; compared with the commit found, and with the first commit on the first-parent history, before any hash, header or sample read | `test_the_freeze_commit_must_be_the_pinned_one`, `test_a_side_commit_with_the_same_criterion_cannot_become_the_freeze`, `test_first_parent_resolution_names_the_first_commit_on_the_main_line` |
| 2 | the role register was unbound: 10 km as VALIDATION, 2 km as LOCKED_TEST | the register is bound to its bytes at the freeze; the role of each file is fixed by name in code (`ROLE_BY_NAME`) | `test_the_10km_file_cannot_be_given_the_validation_role`, `test_the_2km_file_cannot_be_given_the_locked_test_role_so_it_never_gives_validated`, `test_the_role_register_changed_after_the_freeze_is_refused` |
| 3, 4 | 2 km selection arbitrary and decisive; thresholds neither too wide nor too narrow for nuisance | redesign, R12.2 to R12.4 | `test_the_carry_rule_needs_a_margin_and_otherwise_carries_every_survivor` and the scoring tests |
| 5 | unknown scenario id and prediction drift refused after the holdout was read | the comparator is read and the predictions recomputed, and the ids checked, before the holdout is hashed or opened | `test_every_refusal_before_the_holdout_comes_before_any_hash_or_open_of_it`, `test_a_carried_id_that_is_not_listed_and_a_drifted_prediction_are_refused_unread` |
| 6 | a burned 10 km returned INCONCLUSIVE, outside `allowed_verdicts`; false mutant reason | a verdict outside the allowed set becomes EXPLORATORY (BLOCKED if that is not allowed) | `test_a_burned_file_ends_exploratory_and_a_shared_sequence_may_too` |
| 7 | the frozen script could never supply `sequence_check` or `state` | the script has `--sequence-check` and `--state`; VALIDATED is never returned (R12.4), so the declarations only reach EXPLORATORY; `not-shared` cannot be established by the script and the 10 km run stays unspent until the owner decides | `test_the_frozen_script_reaches_every_allowed_verdict_and_never_validated` |
| 8 | a path move resets the binding | stated as a known limit; the external pin catches it | `test_a_moved_criterion_path_resets_the_binding_and_only_the_pin_catches_it` |
| 9 | surviving mutants | tests for each (psi equal to 1 on both tests, the 10 km length, `--full-history`) | `test_a_psi_of_exactly_one_is_within_the_criterion`, `test_the_10km_scorer_uses_the_10km_length`, `test_the_same_selected_bytes_on_two_branches_are_two_additions` |
| 10 | `--repo` ran changed code against a clean tree; unlisted modules imported | the code identity is the import closure (12 files, a test recomputes it) and the running modules must be the files of the repository | `test_the_code_identity_is_the_import_closure_of_the_scoring_entry_point`, `test_the_running_code_must_be_the_code_of_the_repository` |
| 11 | duplicate key raised a YAML error; stage `banana`; rename-in | `BenchmarkError`; `selected_at_stage` must be `2km`; the file must be a new file in its commit | `test_a_duplicate_key_in_the_selected_scenario_is_a_benchmark_error`, `test_a_malformed_selected_scenario_is_refused`, `test_a_selected_scenario_renamed_in_from_a_draft_is_refused` |
| 12 | 2 km identifiability true through loss only; test header said Gaussian-smoothed | `identifiable_in_principle` asks for a dispersion-only separable scenario; the test header is corrected | `test_the_control_is_never_separable_whatever_the_limits` |

The pin, restated plainly: the owner records the freeze commit id outside the repository before E2b,
and passes it on every run. A pin held on the same machine as the repository checks against ordinary
commits; it is not date proof. The promise of R3.1 is unchanged and not widened. `holdout.py` changes
in one line, `CRITERION_PATH`, as R3.2 requires for a new path.

### R12.1 Why the criterion of R10 could not stand

The review's cases, run on pseudo-captures made from real B2B (R12.4), showed: the 2 km choice among
matched-amplitude scenarios was noise (pairwise psi 0.09 to 0.38 against a limit of 1) and then fixed
the only 10 km hypothesis; a 5 percent amplitude error already failed M1 at 2 km, and launch power and
any re-tuning are unknown, so a FAIL would mostly report amplitude; the dispersion grid was too coarse
(a first study with a step of 1.5 ps/(nm km) FAILed a true D of 5.2 at 10 km, a second with a step of 0.5 FAILed it again, and a
first exploration whose noise always stayed after the fibre FAILed every D from 4.5 up, because the
B2B-filtered pseudo-captures carry the noise through the fibre). None of these was tuned away by moving
a limit: the structure changed, and what could not be made to separate is capped (R12.4).

### R12.2 What changes

1. **Gain-invariant map instead of one normalisation.** Every window (measured, predicted, B2B copy)
   goes through the same map x -> (x - c) / g from its own four k-means centroids (c their mean, g the
   mean gap), after the B2B-fixed affine map. The amplitude ratio g (relative to B2B) is **reported,
   not tested**: launch power and loss are UNKNOWN, and a result that fails on amplitude says nothing
   about the model. This supersedes the one-normalisation rule of R2.2 for the criterion (the estimators
   M1 to M4 are unchanged); it does not hide loss, because the ratio is printed with every result.
2. **Scenarios** (`scenario_list.yaml`, 123, counted): dispersion |D| in 0 to 3 ps/(nm km) in steps
   of 0.5, 3.25 to 6.25 in steps of 0.25 and the G.652.D O-band bound 6.352 (SPECIFICATION_LIMIT, from `g652d_dispersion_limits`),
   crossed with a noise factor 1, 1.5, 2.2 (any SNR change: UNKNOWN loss, launch power, re-tuning) and,
   for D > 0, with the noise after the fibre or crossing it (the two bounds of the unidentifiable
   noise origin). D = 0 with factor 1 is the no-fibre control. Chirp is zero (MODEL GAP: CHIRP).
3. **Limits** (R12.3) keep the formula of R10.3: basis = the larger of the model's misfit on B2B and the
   B2B spread (both now gain-invariant), times 2.0. The multiplier is not changed after seeing the
   power study.

### R12.3 The two-stage procedure, pre-stated

- **2 km (selection stage).** All 123 scenarios scored; survivors = scenarios with psi <= 1. Carry
  rule: if there is no survivor the stage is `FAIL` and nothing is carried (10 km is not run); a single
  scenario is carried alone only if it is the only survivor or wins by a psi margin of 0.25 over the
  next survivor; otherwise **all survivors** are carried (rule `all_survivors`). A 2 km `FAIL` is
  reported FAILED: dispersion hardly acts at 2 km, so no grid or dispersion effect can cause it. `selected_scenario.yaml`
  lists the carried ids, the rule and `2km`, and is added once after the freeze (R11.2).
- **10 km (locked test).** Only the carried scenarios and the control are scored. Survivors = carried
  scenarios with psi <= 1. Outcome: `FAIL` if none, reported **INCONCLUSIVE with the claim
  `NO_GRID_SCENARIO_FITS`, never FAILED** (the power table: a true D above 3 ps/(nm km) that lies
  between grid points FAILs, about 40 percent of such D); `PASS, NOT DISCRIMINATING` if the B2B copy or the
  control is also within every limit or only the control survives; otherwise `PASS, DISCRIMINATING`.
  Multiplicity: k carried scenarios give k chances; this is accounted for by the cap below and by the
  false-pass rates of the power table, not by a corrected threshold.
- **Cap.** A `PASS, DISCRIMINATING` carries the claim `PARTIAL` and the verdict INCONCLUSIVE. `VALIDATED`
  is never returned, at either length, whatever is declared. Reasons, from the study: with the 2 km gate
  bypassed an unmodelled low-pass is accepted by dispersion scenarios at 10 km (last column), wavelength
  and chirp are unknown so dispersion cannot be predicted before the capture, and selecting among
  123 scenarios on the capture is a fit, so a pass is a consistency statement about a set.
  `PASS, NOT DISCRIMINATING` gives UNIDENTIFIABLE_PARAMETER when no dispersion-only scenario was separable
  from the copy for that length in advance (true at 2 km), INCONCLUSIVE otherwise; a 2 km FAIL gives
  FAILED; a verdict outside `allowed_verdicts` (a burned file, a shared sequence) becomes EXPLORATORY.

Limits (from B2B only):

| Metric | (a) surrogate misfit | (b) B2B spread | basis | multiplier | limit |
|---|---|---|---|---|---|
| M1 | 0.00906767 | 0.00290499 | 0.00906767 | 2 | 0.0181353 |
| M2 | 0.0300007 | 0.00131942 | 0.0300007 | 2 | 0.0600013 |
| M3 | 0.0653318 | 0.00422885 | 0.0653318 | 2 | 0.130664 |
| M4 | 0.608961 | 0.0806479 | 0.608961 | 2 | 1.21792 |

### R12.4 Power study (pre-registered; `power_study.yaml`, hash below)

Pseudo-captures were made from five real B2B windows that are not the fit, spread or evaluation window,
with the study script's own filters (not `e2_model`): a cosine dispersion filter over the whole waveform
(so the noise crosses the fibre), a Gaussian low-pass with its -3 dB power point at 32, 34 or 36 GHz, a
gain of 0.95 or 1.05, extra band-limited noise of 0.3 gap, and surrogate-made captures (noise after the
fibre, other seeds). Each was run through the frozen two-stage procedure at 2 km and then at 10 km with
the carried set. Counts are over 5 windows (P,ND = PASS, NOT DISCRIMINATING; P,D = PASS, DISCRIMINATING).

| Case | 2 km outcome | scenarios carried | 10 km outcome | 10 km verdict | dispersions of the 10 km survivors | 10 km if the 2 km gate were bypassed |
|---|---|---|---|---|---|---|
| B2B filtered, D=0 | P,ND 5 | 82 | P,ND 5 | INCONCLUSIVE 5 | 0, 0.5, 1, 1.5, 2 | P,ND 5 |
| B2B filtered, D=2.2 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 1.5, 2, 2.5, 3 | P,D 5 |
| B2B filtered, D=3.4 | P,ND 5 | 82 | FAIL 5 | INCONCLUSIVE 5 | none | FAIL 5 |
| B2B filtered, D=3.85 | P,ND 5 | 82 | FAIL 5 | INCONCLUSIVE 5 | none | FAIL 5 |
| B2B filtered, D=4.1 | P,ND 5 | 82 | FAIL 5 | INCONCLUSIVE 5 | none | FAIL 5 |
| B2B filtered, D=4.5 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 4.5 | P,D 5 |
| B2B filtered, D=4.9 | P,ND 5 | 82 | FAIL 5 | INCONCLUSIVE 5 | none | FAIL 5 |
| B2B filtered, D=5.2 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 5.25 | P,D 5 |
| B2B filtered, D=5.45 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 5.5 | P,D 5 |
| B2B filtered, D=5.7 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 5.75 | P,D 5 |
| B2B filtered, D=6.352 | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 6.25, 6.352 | P,D 5 |
| B2B filtered, D=9 | P,ND 5 | 78 | FAIL 5 | INCONCLUSIVE 5 | none | FAIL 5 |
| B2B, D=0 plus unmodelled low-pass 32 GHz | FAIL 5 | 0 | not run 5 | none 5 | none | P,D 5 |
| B2B, D=0 plus unmodelled low-pass 34 GHz | FAIL 5 | 0 | not run 5 | none 5 | none | P,D 5 |
| B2B, D=0 plus unmodelled low-pass 36 GHz | FAIL 5 | 0 | not run 5 | none 5 | none | P,D 5 |
| B2B, D=0, amplitude x0.95 | P,ND 5 | 82 | P,ND 5 | INCONCLUSIVE 5 | 0, 0.5, 1, 1.5, 2 | P,ND 5 |
| B2B, D=0, amplitude x1.05 | P,ND 5 | 82 | P,ND 5 | INCONCLUSIVE 5 | 0, 0.5, 1, 1.5, 2 | P,ND 5 |
| B2B filtered D=4.5, extra noise 0.3 gap | FAIL 5 | 0 | not run 5 | none 5 | none | P,D 5 |
| surrogate, D=2.2, noise after fibre | P,ND 5 | 78 | P,D 5 | INCONCLUSIVE 5 | 1, 1.5, 2, 2.5, 3 | P,D 5 |
| surrogate, D=4.5, noise after fibre | P,ND 5 | 82 | P,D 5 | INCONCLUSIVE 5 | 4.25, 4.5, 4.75 | P,D 5 |

Reading, fixed here:

1. Amplitude: a gain of 0.95 or 1.05 gives the same outcome and survivors as no change (the gain-invariant map); amplitude is not a failure cause.
2. 2 km: every true D from 0 to 9 gives `PASS, NOT DISCRIMINATING` with nearly every scenario carried (a single scenario is never carried: 0 of 100 windows), so at 2 km the carry rule is a pass-through and dispersion is not identifiable. What the 2 km stage does is gate: an unmodelled low-pass (32, 34, 36 GHz) and 0.3 gap of extra noise FAIL 5/5.
3. 10 km, true D = 0: `PASS, NOT DISCRIMINATING` with survivors from 0 to 2.0 ps/(nm km): a dispersion up to about 2 cannot be told from none. At D = 2.2 the survivors are 1.5 to 3.0 (a width of about +-0.75).
4. 10 km, D above 3: the survivors are the single grid point within 0.05 of the truth (4.5, 5.25, 5.5, 5.75; 6.25 and 6.352 for the bound), a resolution of about +-0.075. True D of 3.4, 3.85, 4.1 and 4.9, which lie 0.1 or more from a grid point, FAIL 5/5. About 40 percent of true D above 3 (the part of a 0.25 step farther than 0.075 from a grid point) would therefore end with no survivor. A 10 km FAIL is thus reported INCONCLUSIVE with the claim `NO_GRID_SCENARIO_FITS`; D = 9 FAILs 5/5, as it should.
5. False pass: with the 2 km gate bypassed (last column) the unmodelled low-pass cases and the extra-noise case pass at 10 km as `PASS, DISCRIMINATING` 5/5. The gate stops the low-pass cases (they FAIL at 2 km) but a milder one was not tested, so a pass is capped at PARTIAL and VALIDATED is not offered.
6. Model-consistent truth (surrogate, noise after the fibre) gives `PASS, DISCRIMINATING` 5/5 with the true D among the survivors (D = 4.5: 4.25 to 4.75). Real-B2B pseudo-captures filter the noise too, which is the other noise-origin bound; both bounds are scenarios.
7. Not tuned: the grid was refined from a step of 1.5 to 0.5 to 0.25 above 3 after the first two studies FAILed true D between grid points; limits, multiplier (2.0), margin (0.25) and the noise factors were not changed. The first two tables are not kept; this one is final.


FAIL caveats, one per nuisance (a FAIL says no scenario of the family fits; it does not say the fibre model
is wrong): chirp (the dispersion response changes shape; MODEL GAP: CHIRP); a true dispersion outside
0 to 6.352 ps/(nm km) or off the grid by more than the study shows (D = 9 FAILs by construction); an
SNR change beyond factor 2.2 or a noise colour unlike B2B; an unmodelled low-pass, reflection or filter
(2 km FAILs for 32 to 36 GHz); a non-uniform or correlated symbol sequence; the large-signal regime (not
modelled); a different export filter or interpolation. Amplitude and launch power are not a FAIL cause
(reported, x0.95 and x1.05 are unchanged). PASS caveats: a PASS never validates dispersion (the low-pass
cases pass at 10 km); it does not establish the chirp-free assumption; the surviving dispersions are a
fit to the capture and are reported as a set; wavelength and fibre type remain UNKNOWN.

### R12.5 Code identity (narrow) and data

The code identity is the import closure of the scoring entry point, 12 files (SHA-256 as committed at the
freeze; the scorer refuses any difference, and R11.2 compares them with the freeze commit; the running
modules must be these files):

- `src/opticps/__init__.py` `73b18c2f2f411e59a48662c13f0b61689edcd899f0b925ba4f6b7e344f1ddf82`
- `src/opticps/benchmarks/__init__.py` `7930ad4cc12b9c9fd25aae774d7865c25ade13cb52650b6eec2d3ed85b944989`
- `src/opticps/benchmarks/capture_stats.py` `9a2a9be15cceaf0c07fd9a8549e9a6824dbe212a96f5d556fd56696b8c476683`
- `src/opticps/benchmarks/catalog.py` `069896ef92e6e2f9271192f423861808480e91c65dc118119d2e9cf5161ed194`
- `src/opticps/benchmarks/e2_metrics.py` `64ba6abe5fcc0291149c759b28ca1fc9eb26b017dfad5c6dd35a569af0f44bde`
- `src/opticps/benchmarks/e2_model.py` `f512d29b9ea096d26e6f8093c04607a246d6e483d0b3b345a1af0a8d87d0d853`
- `src/opticps/benchmarks/e2_score.py` `6a8fb0cf3970446bc8f032e4cdf9f88974a445f3badb89b73407b20628edee0b`
- `src/opticps/benchmarks/external_capture.py` `7b64d0b8e4672319e478ddd0d6f0dc65b6fb2f4b2599a8263b63b675a34044b3`
- `src/opticps/benchmarks/holdout.py` `de1bd71d77e3de2b868fd08d9dd14510f558a35d76c156bffe0393d195f4f8a4`
- `src/opticps/benchmarks/provenance.py` `65a58540920cfabfcdef1c4f9934c1886b0ba752dfb50428ba2bcdf639976b6d`
- `src/opticps/benchmarks/teriphic.py` `8b1765030f8289fa8f40db66878e9d3554fecab2b99bf4921895b2f8e77adeee`
- `src/opticps/benchmarks/timing.py` `26ea7bcd3ee5416a2cfbf8a4b403217210219d31af1b8fa1d872689204db61be`

Not covered, as in R10.4: the interpreter, NumPy, SciPy, BLAS, the platform, the tests and the scripts
other than the evaluation script (which the freeze binds). Data files: `b2b_model.yaml` `efbb4a3d7b95724af4adc03af2fd5a4ec3db47c4908630146e75c5714b2ef58c`,
`scenario_list.yaml` `528600b5e695325835dd649e0a5a50027a24aceb31240ef138c5428282354c99`, `preregistered_predictions.yaml`
`54013bb430af4ff447261a2d645ad666e5823edc71200281205199008959a8f4`, `power_study.yaml` `64606e484dcc911c3fa99490c0ab0f9b1dddf43dfc326d2452a148062e3a4389`. The pre-registered
values (`predictions`, with the separation of each scenario from the B2B copy) are recomputed by the
scorer at 1e-6 relative; that recomputation also exercises the B2B read path. Examples from it: the
control and every |D| <= 1 scenario are not separable from the copy at 2 km (psi 0.50 for the control);
at 10 km the |D| = 3 scenario with factor 1 has psi 2.50 and |D| = 6.352 has psi 3.92.

### R12.6 Not done

Nothing was scored on a holdout. E2b, after independent review of this revision: the owner records the
freeze commit outside the repository; the 2 km run produces the carried set; `selected_scenario.yaml`
is added in one commit; the 10 km run is then the only one. The shared-sequence check is not
implemented, so `not-shared` is a declaration by the operator, and nothing in this gate can return
VALIDATED. BER and SER stay REFERENCE_SEQUENCE_MISSING.

## Revision 13 (2026-11-11): R12 reviewed, failed and never scored; the 10 km run is tied to the committed 2 km result; new freeze

Previous version: SHA-256 `7b02c1938823173cd94e27c29ee5ae3067cdc225b7589c873bdecfa212d8898b` (Revision 12, freeze commit 04360ec6a44bb6aaa2222cc605ab3979718be50a after the history rewrite of `docs/orchestration/opticps-v2/HISTORY_REWRITE.md`; Revision 11 is `554fd2b6...`).
New version: the pin in `tests/test_benchmark_provenance.py` and in
`configs/benchmarks/teriphic_pd1_pam4.yaml`. This is an addendum: 0 lines are removed or edited from
earlier text. Where earlier text is wrong it is corrected here, by reference, and stays as written. The
criterion file is committed in the commit after this revision, alone, at
`docs/benchmarks/TERIPHIC_CRITERION_R13.yaml`; the commit that first holds it on the first-parent
history of `v1.3-mpam` is the freeze. Basis: the design decision
`docs/orchestration/opticps-v2/questions/E2a_design_fable.md` (items cited as D1 to D22) and the
coordinator's reading of its item 16 (R13.4).

### R13.0 What happened to R12

The independent re-review of Revision 12 (`docs/orchestration/opticps-v2/handoff/E2a_qa2.md`, verified
at 4a9222d, freeze 04360ec) returned **FAIL**: 1 MAJOR, 2 MINOR and 3 OBSERVATION; all 12 earlier
findings were fixed. Revision 12 was reviewed, failed and **never scored**: no 2 km or 10 km sample,
header or hash was read or produced by any code at any point, before or after that review, and none
was read, hashed, header-parsed, plotted or linked to write this revision. Its criterion file
(`TERIPHIC_CRITERION_R12.yaml`) stays in the repository as a record with `TERIPHIC_CRITERION.yaml` and
`TERIPHIC_CRITERION_R11.yaml`, is ignored by the guard (another path is not a criterion) and must not
be used. Since no holdout has been read, a new revision and a new freeze are legitimate. The findings
and their fixes:

| # | Finding (re-review) | Fix | Test |
|---|---|---|---|
| 1 | MAJOR: the 10 km run was not tied to the 2 km result; `--stage failed` was scored; the carried ids were checked for format only; the report held no declarations | R13.2: LOCKED_TEST needs `validation_stage` NOT_FAILED; the committed 2 km record is bound to the selection and checked; the report holds the declarations | `test_the_10km_file_is_refused_when_the_2km_stage_is_declared_failed_or_undeclared`, `test_the_10km_file_is_refused_when_the_committed_2km_record_says_fail`, `test_the_10km_file_is_refused_without_a_committed_2km_record`, `test_the_record_hash_in_the_selection_must_match_the_committed_record`, `test_the_carried_ids_must_equal_the_records_carry_forward_in_order`, `test_the_carried_ids_must_be_the_carry_rule_of_the_recorded_table`, `test_the_2km_record_must_name_the_2km_file_at_the_pinned_freeze`, `test_the_selection_and_the_record_are_added_as_new_files_in_one_commit`, `test_the_records_head_commit_lies_between_freeze_and_selection_with_bound_files_unchanged`, `test_the_report_records_declarations_record_window_and_summary`, `test_the_2km_report_written_by_the_script_is_a_valid_record_for_the_10km_stage` |
| 2 | MINOR: `--sequence-check shared` never gave EXPLORATORY; three texts said it did; "not-shared" was only the operator's word | R13.2 item 8: SHARED gives {EXPLORATORY, BLOCKED} at both lengths; the script offers `not-run` and `shared` only; the declarations are in the report | `test_a_shared_sequence_forces_exploratory_at_both_lengths`, `test_a_burned_file_ends_exploratory_and_a_shared_sequence_does_too`, `test_the_frozen_script_cannot_declare_not_shared` |
| 3 | MINOR: the mutant `judged = list(table)` survived (an uncarried control counted as a 10 km survivor) | `judged` was correct and stays; the test was missing | `test_an_uncarried_control_within_limits_is_not_a_10km_survivor`; mutant `judged_includes_uncarried_control` |
| 4 | OBSERVATION (science): low-pass boundary, off-grid and large-signal reproductions; the 40 percent wording went beyond the study | R13.3: wording corrected, a new FAIL caveat, the claim renamed | `test_a_result_carries_one_caveat_per_nuisance_for_fail_and_for_pass` |
| 5 | OBSERVATION: R12 limit values differ from R11 | R13.3, correction of the R12 sentence | `test_real_r13_limits_equal_r12_and_the_plan_hash_differs` |
| 6 | OBSERVATION: "the first external timestamp" was not stored anywhere | R13.5 | none (procedure) |

R12.0 row 7 says the declarations "only reach EXPLORATORY", that `not-shared` cannot be established by
the script, and that the 10 km run "stays unspent until the owner decides". The first two are
corrected by R13.2 item 8 (EXPLORATORY is now reached by `shared` too, and `not-shared` is no longer
offered); the third is superseded by the stop rule of R13.1 item 4. The R12.3 parenthetical "(10 km is
not run)" is now enforced in code (R13.2 item 5) instead of stated.

### R13.1 What each outcome tells us, fixed before any read (D1 to D4)

| Stage and outcome | What it says | Verdict | Next |
|---|---|---|---|
| 2 km FAIL | the surrogate does not transfer within 2x its own B2B misfit; the study excludes dispersion as the cause (D 0 to 9 all pass at 2 km), so a nuisance is present (receiver or export filter, SNR change beyond 2.2x, large-signal, sequence statistics) | FAILED | 10 km refused by code and kept unspent; high value, a clean negative |
| 2 km PASS, NOT DISCRIMINATING (the study's outcome for every D) | transfer holds, about 80 scenarios carried | UNIDENTIFIABLE_PARAMETER | first external evidence of transfer; unlocks 10 km |
| 10 km PASS, NOT DISCRIMINATING | consistent with \|D\| <= about 2 ps/(nm km) (O-band near zero dispersion) | INCONCLUSIVE | a consistency with G.652.D, no dispersion claim |
| 10 km PASS, DISCRIMINATING | a set of D fits where the no-fibre control does not | INCONCLUSIVE, claim PARTIAL | confounded by a mild low-pass (the cap) |
| 10 km FAIL | no scenario fits; not separable among a grid miss (20 to 60 percent of D above 3), large-signal, chirp, a filter | INCONCLUSIVE, claim `NO_SCENARIO_FITS` | low value, the price of spending 10 km |

1. Why the 10 km file is not held for a better model (D2): a large-signal or chirp model cannot be
   fitted from B2B (`e2_model` docstring) nor from 2 km (dispersion hardly acts there); its parameters
   are identifiable only from 10 km, which spends it anyway, so holding it has little option value.
   After E2b the burned 10 km file may be used, labelled EXPLORATORY, to fit such a model.
2. The 10 km verdict is INCONCLUSIVE in every scored case by design (D3); the information is in
   `outcome`, `claim` and the survivors' dispersions. The report carries a `summary` line, and every
   publication states the ceiling PARTIAL.
3. **Stop rule, pre-registered (D4): the 10 km run is made if and only if the committed 2 km record's
   outcome is not FAIL. No other condition.** R12.0 row 7 ("until the owner decides") is superseded by
   this rule.

### R13.2 The two-stage contract (D5 to D8)

5. **Refusal after a 2 km FAIL.** `require_frozen_criterion` accepts LOCKED_TEST only with
   `validation_stage` NOT_FAILED; FAILED, NOT_DONE and None are refused (`holdout.StageRefused`) before
   any input is hashed and before the holdout is hashed or opened ("the 2 km stage FAILED: nothing is
   carried, the 10 km file stays unspent, plan R12.3"). Independently, `e2_score` refuses when the
   committed 2 km record has `outcome` FAIL or BLOCKED or `verdict` FAILED or BLOCKED, whatever is
   declared.
6. **The carried set is bound to the recorded 2 km result.** `e2_score.TWO_KM_RESULT_PATH` is
   `docs/benchmarks/teriphic_e2/two_km_result.json`: the verbatim stdout of the frozen script's 2 km
   run. `selected_scenario.yaml` has exactly the keys `scenario_ids`, `rule`, `selected_at_stage` and
   `two_km_result_sha256`. `REQUIRED_INPUTS[LOCKED_TEST]` gains `two_km_result`, so the guard requires
   it committed, unchanged and not empty, and hashes it. `read_two_km_record(root, frozen, scenarios,
   limits)` replaces `read_selected_scenarios` and refuses unless:
   a. neither file existed at the freeze; each has exactly one commit in `--full-history`; it is the
      same commit (the selection commit), a descendant of the freeze; both are new files (`A`, no
      rename) in that commit; their bytes are unchanged since;
   b. the SHA-256 of the record's committed bytes equals `two_km_result_sha256`;
   c. the record is a report of version 2 with `filename` the registered 2 km name, `split`
      VALIDATION, `length_km` 2.0, `criterion_commit` equal to `frozen.commit` (the pin),
      `hashes_verified` true, and outcome and verdict as in item 5;
   d. the record's `head_commit` is the freeze or a descendant of it and an ancestor of the selection
      commit, and every `bind_to_freeze` path at `head_commit` equals its freeze bytes
      (`bind_to_freeze` has a `revision` parameter for this);
   e. `scenarios_scored` equals the scenario count, the record's `scenarios` keys are all the ids,
      and its `limits` equal the frozen ones (1e-9 relative);
   f. `carry_forward` equals `scenario_ids` in order; the carry rule recomputed from the recorded psi
      table, taken in the order of the scenario list as the 2 km run scored it, equals the ids; `rule`
      is `single` if and only if one id is carried; every carried id has psi <= 1 there.
   The 2 km file is not re-read at 10 km time (one holdout per process; the read-order test stays).
   The record is bound by bytes and consistency; a psi table edited to match hand-picked ids is
   tampering under the promise of R3.1 (restated in the known limits). Recomputing the carry rule from
   the recorded table makes the 10 km stage independent of float differences between machines. All
   of these checks run before the B2B comparator is read and before the holdout is hashed or opened.
7. **The JSON report, both stages**: `report_version: 2`; `declarations: {validation_stage,
   sequence_check, state}` (strings or null) with `declarations_note` "operator declarations, not
   established by this script; the shared-sequence check is not implemented, so NOT_SHARED cannot be
   declared here"; `two_km_record: {path, sha256, commit}` at 10 km, null at 2 km; `window: {start,
   samples, sample_rate_hz}` (the evaluation window read and the header's sample rate); `summary`: one
   sentence from the outcome, the claim, the survivors' dispersions and the amplitude ratio, ending
   "the verdict is capped at INCONCLUSIVE by design"; and a note, never a verdict rule, when the
   amplitude ratio is outside 0.5 to 2.
8. **Shared sequence.** `allowed_verdicts` with `sequence_check` SHARED (as with BURNED) returns
   {EXPLORATORY, BLOCKED} for VALIDATION and for LOCKED_TEST, so the existing clamp forces EXPLORATORY
   at either length (R2.4 read literally); a BLOCKED result stays BLOCKED. The script offers
   `--sequence-check {not-run, shared}` only; `not-shared` is gone from the script (the enum member
   stays). The script docstring is corrected in code; R12.0 row 7 and the R12.3 parenthetical are
   corrected by this text. The script exits 3 for a refusal by the two-stage contract (the declared
   stage or the record), 2 for any other refusal.

### R13.3 Science: what changes in words, what does not change (D9 to D13)

9. **Low-pass margin at 2 km: no strengthening.** The limit basis is the model's own B2B misfit (M4
   0.609 against a spread of 0.081), so a low-pass whose effect on M1 to M4 is below that misfit lies
   inside the model's own error and cannot be rejected on B2B evidence without failing B2B itself; the
   cap already carries this. Recorded: a Butterworth-4 low-pass at 45 GHz FAILed 2 km at psi 1.019
   (reviewer, B2B window 12582912, not part of the study); a milder one passes. This is the measured
   boundary, not a limit change.
10. **Unchanged:** limits, basis, multiplier 2.0, estimators, margin 0.25, carry rule, gain-invariant
    map, model, scenario list, pre-registration, power study, windows, seeds, `ROLE_BY_NAME`,
    `LENGTH_KM`. No scenario, metric or threshold is added. The claim constant is renamed from
    `NO_GRID_SCENARIO_FITS` to `NO_SCENARIO_FITS` (the old name asserts a cause the study cannot
    separate); its note lists the causes of R13.1.
11. **The 40 percent, corrected.** The third FAIL caveat, R12.3 and R12.4 reading 4 stay as written and
    are corrected here: the study brackets the fraction of true D above 3 ps/(nm km) that no grid
    scenario fits between about 20 and 60 percent (a D within 0.05 of a grid point passed, one 0.10
    away failed; the boundary between was not resolved), small-signal only.
12. **Small-signal, a new FAIL caveat:** every pseudo-capture of the study has the model's own
    small-signal cosine form; a large-signal (square-law, ER about 6 dB) pseudo-capture of real B2B
    FAILed at 10 km even on-grid at D=4.5 (psi 1.26; reviewer reproduction, window 12582912, not part of
    the pre-registered study). A 10 km FAIL does not separate a grid miss from large-signal operation,
    chirp or a filter.
13. **The R12 limit values, corrected.** The R12 limit values differ from R11 (M1 0.02659 to 0.01814,
    M2 0.03456 to 0.06000, M3 0.08985 to 0.13066, M4 1.2292 to 1.2179) because the metric map became the
    gain-invariant map (R12.2) and misfit and spread were recomputed under it; the formula basis x 2.0
    and the multiplier are unchanged. "Limits were not changed" (R12.4 reading 7, the R12 handoff)
    meant only: not moved after seeing the power study. R13 limits equal R12 to 1e-9 (test
    `test_real_r13_limits_equal_r12_and_the_plan_hash_differs`).

### R13.4 How "must not change" is read for the three E2 documents

D16 says `b2b_model.yaml`, `preregistered_predictions.yaml` and `power_study.yaml` must not change.
Taken byte for byte this cannot be done together with D15: the model holds the code identity of the
import closure (R12.5), which changes when `holdout.py` and `e2_score.py` change, and the other two hold
the model's SHA-256. The coordinator's decision, following the R12 precedent the reviewer accepted
(`E2a_qa.md`, "First freeze": the model differed only in two identity hashes, the registration only in
`model_sha256`): the **scientific content** of the three documents must not change, that is fitted
values, limits, scenarios, predictions, power-study results, seeds and windows. Allowed and nothing
else: the `code_identity` table of `b2b_model.yaml`, regenerated by `scripts/freeze_teriphic_e2.py
prepare` (B2B only), and the resulting `model_sha256` line of the other two. `scenario_list.yaml` is
byte-identical. Evidence: `test_real_r13_documents_equal_the_r12_freeze_except_the_regenerated_fields`
compares each document with its bytes at the R12 freeze (`git show 04360ec`) after removing only that
field, and `test_the_committed_e2_documents_hold_the_r12_science_and_are_tied_to_each_other` holds the
digest of that content; the mutant `fitted_value_changed_with_hashes_consistent` (a fitted value
changed, the model hash re-tied in both documents) is killed by it.

### R13.5 External timestamp (D14, as decided by the coordinator)

No release is made: the owner has not approved one. The timestamp procedure is push events plus the
external pin. The coordinator holds outside the repository, in
`~/.claude/orchestration/opticps-v2-evidence/github_events_2026-11-11.json` (SHA-256
`2f10d05305182d0cd80161d20fe3cfb1f18f8f1522707efc8e9b91f1104b4ae6`, not committed), a capture of the
GitHub events API with a PushEvent at 2026-11-10T13:01:16Z for `refs/heads/v1.3-mpam`, head
`c93524109f451856b97bd893b178499cf9dd472d`, from which the R12 freeze 04360ec is reachable. It says only
that the commit existed on GitHub by that time, given GitHub's records. GitHub holds server-side
records of a push; they are not stored in git. A server-set time is third-party evidence of "no later
than"; it proves neither authorship nor "no earlier than". For R13 the same applies: the coordinator
records the freeze commit in the external pin file, pushes, and captures the PushEvent that contains
the R13 freeze. The wording "GitHub push time is the first external timestamp" (CHECKPOINT) is
corrected to: GitHub holds server-side records of the push (not stored in git); evidence is kept
outside the repository as stated here.

### R13.6 Missed by the reviewer, now stated (D20 to D22)

- Nothing made the operator commit the 2 km report at all; `selected_scenario.yaml` could be typed
  from memory. R13.2 item 6 binds it, and puts the record in `REQUIRED_INPUTS`, without which the guard
  would neither require it committed nor hash it.
- The report omitted which window was read and the sample-rate check; `window` makes a result
  reproducible.
- **The 2 km run can be executed twice** (look, then commit). Code cannot prevent it; the output is
  deterministic, so the record is unaffected. The plan says once; this stays procedural only, under
  the promise.

### R13.7 The promise, restated and not widened

The guard catches accidents and casual re-tuning by ordinary commits. It does not stop deliberate tampering by someone who controls the repository, and it gives no date proof. Only an external timestamp can.

The two-stage binding of R13.2 is to bytes in the local history and inherits this promise; the new
limits are listed in `docs/benchmarks/FREEZE_GUARD_KNOWN_LIMITS.md`.

### R13.8 Code identity (narrow) and data

The code identity is the same import closure of 12 files (SHA-256 as committed at the freeze; the
scorer refuses any difference, and R11.2 compares them with the freeze commit):

- `src/opticps/__init__.py` `73b18c2f2f411e59a48662c13f0b61689edcd899f0b925ba4f6b7e344f1ddf82`
- `src/opticps/benchmarks/__init__.py` `7930ad4cc12b9c9fd25aae774d7865c25ade13cb52650b6eec2d3ed85b944989`
- `src/opticps/benchmarks/capture_stats.py` `9a2a9be15cceaf0c07fd9a8549e9a6824dbe212a96f5d556fd56696b8c476683`
- `src/opticps/benchmarks/catalog.py` `069896ef92e6e2f9271192f423861808480e91c65dc118119d2e9cf5161ed194`
- `src/opticps/benchmarks/e2_metrics.py` `64ba6abe5fcc0291149c759b28ca1fc9eb26b017dfad5c6dd35a569af0f44bde`
- `src/opticps/benchmarks/e2_model.py` `f512d29b9ea096d26e6f8093c04607a246d6e483d0b3b345a1af0a8d87d0d853`
- `src/opticps/benchmarks/e2_score.py` `e6e2ba920b109752295cd9f1dec2dc7d4aaad4d78a7fb2bd3c28f24e78bb2e5b`
- `src/opticps/benchmarks/external_capture.py` `7b64d0b8e4672319e478ddd0d6f0dc65b6fb2f4b2599a8263b63b675a34044b3`
- `src/opticps/benchmarks/holdout.py` `1df38b3b025f1f1fc258cbd1e1c90de30ce67b6f7ed334b6f2d39cf823da6dea`
- `src/opticps/benchmarks/provenance.py` `65a58540920cfabfcdef1c4f9934c1886b0ba752dfb50428ba2bcdf639976b6d`
- `src/opticps/benchmarks/teriphic.py` `8b1765030f8289fa8f40db66878e9d3554fecab2b99bf4921895b2f8e77adeee`
- `src/opticps/benchmarks/timing.py` `26ea7bcd3ee5416a2cfbf8a4b403217210219d31af1b8fa1d872689204db61be`

Data files: `b2b_model.yaml` `6c57d4aa8e231639e866283cfdb5d7b0cfeed1cf08748a9502d5bbe27126ab55`, `scenario_list.yaml` `528600b5e695325835dd649e0a5a50027a24aceb31240ef138c5428282354c99`, `preregistered_predictions.yaml` `03210916fa4bc7558094b843996494bd126f38b0c2df0c16f93bbf43cddff6e5`, `power_study.yaml` `aeb48a5ac8882d6d2e926dcb0fd1b9176727f52663513b3ee45ae1e576990749`. Unchanged in value from R12 (R13.4).

### R13.9 Not done

Nothing was scored on a holdout, and no `two_km_result.json` or `selected_scenario.yaml` exists; they
come only from the real 2 km run in E2b. `score_holdout` ran on fixtures only. Before E2b: the
independent review of this revision; the coordinator records the R13 freeze outside the repository
and captures its push event (R13.5); any wavelength or modulator statement of the Zenodo record or
the TERIPHIC paper is recorded in the plan as a SOURCE, for interpretation only, with the scenarios
unchanged. E2b: the 2 km run, its stdout committed as the record with the selection in one commit,
then the 10 km run if and only if the record's outcome is not FAIL (R13.1). BER and SER stay
REFERENCE_SEQUENCE_MISSING.
