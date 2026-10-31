# Fit and holdout plan: TERIPHIC PD1 PAM4 (declared before any sample is seen)

Declared 2026-10-31 at Gate E0 (Stage 3A, roadmap v2.1 section L2, step 4). The SHA-256 of this
file is pinned in `tests/test_benchmark_provenance.py` and in `configs/benchmarks/teriphic_pd1_pam4.yaml`, so
an edit after the fact is visible as a failing test. Amendments are new dated sections at the
end of this file together with a new pin; the earlier text stays in Git history.

## 0. State of knowledge when this plan was written

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
   launch power and bias, is unknown; if they were re-tuned between lengths, a frozen single
   normalisation can fail for reasons unrelated to the model (this is reported as limited
   evaluation, not as a model failure).
3. Leakage checks use acquisition group, file name and (once computed locally) SHA-256. A
   file may appear in exactly one role. Two files with equal hashes are one acquisition.
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

**2 km (first declared validation).** Not opened for amplitude statistics until the B2B model
and the list of fibre scenarios are frozen in a committed file. Allowed: select among a finite,
pre-listed set of scenarios (for example "no dispersion", "assumed G.652.D at a stated
wavelength", each with stated parameters), and report. At most the pre-listed scenarios are
tried; the number of scenarios is recorded and counted in the report. After selection, the
choice is frozen and committed.

**10 km (locked test).** One evaluation. Its amplitude statistics are not computed until a
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
- Numeric pass/fail tolerances depend on the B2B noise floor and are not known now. They will
  be written in a separate dated addendum with its own SHA-256 before any 2 km statistic is
  computed. Until then no result can be called validated.

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
`INCONCLUSIVE`, `UNIDENTIFIABLE_PARAMETER`, `BLOCKED` (data, format or licence). Negative and
inconclusive results are reported with the same prominence. The result concerns signal statistics
of one detector and one subassembly; it is not a validation of adaptive shaping or of the
Southampton hardware.
