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
