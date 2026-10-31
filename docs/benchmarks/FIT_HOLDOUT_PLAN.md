# Fit and holdout plan: TERIPHIC PD1 PAM4 (declared before any sample is seen)

Declared 2026-10-31 at Gate E0 (Stage 3A, roadmap v2.1 section L2, step 4). The SHA-256 of this
file is pinned in `tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`, so
an edit after the fact is visible as a failing test. Amendments are new dated sections at the
end of this file together with a new pin; the earlier text stays in Git history. **Revision 1
(2026-10-31, at the end of this file) amends this plan after review.** Every clause it
supersedes is struck through in place (`~~like this~~`) and marked "Revision 1"; the numeric
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
  Checksums, format and content are therefore all still unknown to the plan author.
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

Each length ends as one of: `VALIDATED` (against the later addendum criterion), `FAILED`,
`INCONCLUSIVE`, `UNIDENTIFIABLE_PARAMETER`, `BLOCKED` (data, format or licence).
[Revision 1, R.5: `VALIDATED` is available for 10 km only; 2 km cannot end VALIDATED.] Negative and
inconclusive results are reported with the same prominence. The result concerns signal statistics
of one detector and one subassembly; it is not a validation of adaptive shaping or of the
Southampton hardware.

## Revision 1 (2026-10-31): amendment after the E0 independent review

Previous version: SHA-256 `6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a`
(the text at commit 8900748 as pinned in E0). New version: the pin in
`tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`
(a file cannot contain its own hash; the same value is in the commit message).

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
  sample of any TERIPHIC capture has been read, decoded, plotted or summarised by anyone: the
  files have only been hashed.** The Dev who wrote this revision did not open `data/external/`.
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

- M1 level spacing: the three gaps between adjacent PAM4 level centroids, divided by the B2B
  mean gap, and the change per length of that vector.
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
statistic is computed**; the commit date is the freeze date.

Enforcement: `src/opticps/benchmarks/holdout.py::require_frozen_criterion(asset, criterion_path)`
refuses (raises `BenchmarkError`) any evaluation of a `VALIDATION` or `LOCKED_TEST` asset when the
criterion file is absent, incomplete (a metric missing, not finite or not positive), refers to
another plan hash, or is not committed and unmodified in Git. It returns the commit that froze
it, which a report must carry. Every holdout evaluation entry point added in E2 must call it
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
