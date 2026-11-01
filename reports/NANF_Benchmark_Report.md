# LITERATURE BENCHMARK / CALIBRATION ONLY: NANF versus SSMF, Gate N2 (first part)

Written 2026-10-31. Plan: `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md` (unchanged in this gate; pin in
`tests/test_nanf_benchmark.py`). This report makes no claim of experimental validation of any fibre,
of the propagation model, or of the receiver. Nothing was fitted. Nothing in the holdout set was
compared with a model. Two blocks were run: Benchmark A recomputes the paper's own numerical model (Fig. 1),
and Benchmark C reads the Fig. 5 link-loss and ROP columns.

## 1. Source, licence and attribution

The data come from a local copy of the dataset workbook below, read at an explicit path with the
SHA-256 checked first (`0753aead...19cc0`, the value recorded in `docs/NANF_SOURCES_AND_PROVENANCE.md`).
No value, figure or table of the workbook or of the paper is stored in Git; this report holds numbers
computed here and a few small facts, each with its source.

> Hong, Y., Bradley, T. D., Taengnoi, N., Bottrill, K. R. H., Hayes, J. R., Jasion, G. T., Poletti,
> F., Petropoulos, P., and Richardson, D. J. (2021). Hollow-core NANF for High-speed Short-reach
> Transmission in the S+C+L-bands [Dataset]. University of Southampton.
> https://doi.org/10.5258/SOTON/D1889. Licensed under CC BY 4.0
> (https://creativecommons.org/licenses/by/4.0/). Changes: summarised and compared against
> simulation by OpticPS; values may be reformatted.

Paper: Y. Hong et al., J. Lightwave Technol. 39(19), 6167-6174, 2021, DOI 10.1109/JLT.2021.3097278
(read here as an author manuscript; IEEE terms; no part of it is reproduced). The dataset licence
rests on the DOI-registry record (the readme field is blank, the landing page was not read).

## 2. What the plan allows, and what was touched

| Data | Plan role | Used here |
|---|---|---|
| Fig. 1 (numerical curves) | cross-check only, "not a measurement" (section 2) | read and compared with our recomputation |
| Fig. 5 (ROP columns, NANF link loss) | calibration inputs (section 2) | read; summarised |
| Fig. 4 B2B | calibration | not read in this gate |
| Fig. 4 NANF and SSMF, Fig. 6, Figs. 7 to 12 | locked holdout | parsed by the importer's schema check only; no value looked at, compared or plotted; per-series counts of censored and non-finite cells were printed once (see the disclosure below), values were not |

The evidence labels below follow the vocabulary of the Sources document, and the importer tags each
series the same way: the Fig. 1 curves are `published-numerical-assumption` (the paper's own model,
not a measurement); BER, SNR, capacity and the Fig. 5 link loss are `measured` (results the paper
reports); the ROP columns of Fig. 5 stay `published-experimental` (they are settings or operating
points, never a result); everything computed here is `derived`. The first version of this gate tagged
every experimental series `published-experimental`; that is corrected here and in the importer.

Disclosure (holdout discipline). While checking the importer against the real workbook, the schema check was
followed once by a print of the per-series count of censored (zero or below 1e-5) BER points and of
non-finite cells, for all 69 series including the holdout. Counts only, no value (the values were not printed); the same class of
summary as the counts already disclosed in plan A0 and B0.2, but new information for some series
(for example Fig. 6 SSMF at 80 Gb/s has censored points; Fig. 7 and Fig. 10 have some; the print also covered Fig. 4 SSMF and Figs. 9 and 12). No threshold, tolerance
or code path depends on it. It is entered in the plan's "what was seen" record by Amendment 4. Also, the paper PDF was reread for the axis
labels of Figs. 1 and 5 and the DSP description (Section III).

## 3. Benchmark A: Fig. 1 recomputed with our propagation code

Model: the chirp-free intensity-modulated field sqrt(1 + m cos(2 pi f t)) is sent through
`propagate_profile_field` (all-pass dispersion from D at 1550 nm, 5 km, loss excluded as the paper does) and
square-law detected; the response is the output tone amplitude over the input one, `20 log10 |H|`.
The paper's numerical assumptions are `published-numerical-assumption`: D of 15.95, 4.50, 2.04 ps/(nm km) for
SSMF, NZ-DSF and NANF at 1550 nm; group indices 1.4682, 1.4693, 1.003; length 5 km. The wavelength sweep
uses the paper's own D(lambda) curves of Fig. 1(a) as a runtime table (never committed). This is the paper's own
model recomputed, not a validation of any fibre.

Convention. The fading unit of the workbook is dB with no header unit. A 20 log10 reading of the
response agrees with it at the NANF 35 GHz point (the other reading, 10 log10, gives half the dB values); the
convention was identified by that comparison and then fixed. D, L and n were not adjusted.

Tolerances. The plan predeclares exactly one for this block: the simulator's zero-chirp first null must lie
within 0.3 GHz of the pre-registered arithmetic (A1.3). The other lines have no predeclared tolerance, so the
numbers are reported and no pass is claimed.

| Quantity | Simulated here (`derived`) | Reference | Difference | Status |
|---|---|---|---|---|
| First null, SSMF 5 km (GHz) | 27.970 | pre-registered 27.97 | 0.000 | PASS (A1.3, tolerance 0.3 GHz) |
| First null, SSMF 4.53 km | 29.386 | pre-registered 29.39 | 0.004 | PASS (A1.3) |
| First null, NANF 4.76 km | 80.158 | pre-registered 80.2 | 0.042 | PASS (A1.3) |
| First null, NZ-DSF 5 km | 52.659 | closed form, same formula | none declared | reported only |
| First null, NANF 5 km | 78.210 | workbook: none inside 0 to 35 GHz | n/a | reported only |
| Workbook fading minimum, SSMF | 28 GHz on a 1 GHz grid | simulated null 27.97 | within the 1 GHz grid | reported only |
| Fading profile, stated D: max abs difference (dB); 36 points for NZ-DSF and NANF, 35 for SSMF (the 28 GHz point lies in the null and is excluded by the -25 dB rule: model -49.55 dB, workbook -49.95 dB, 0.40 dB apart) | SSMF 0.0117, NZ-DSF 4.7e-6, NANF 0.0016 | workbook Fig. 1(c) | as in column 2 | reported only |
| Same with the workbook's own D at 1550 nm (dB) | SSMF 5.3e-6, NZ-DSF 4.7e-6, NANF 6.8e-6 | workbook Fig. 1(c) | as in column 2 | reported only |
| D at 1550 nm, stated against the workbook curve | 15.95, 4.50, 2.04 | 15.9485, 4.50, 2.03641 | 0.0015, 0, 0.0036 | the stated values are rounded; explains the line above |
| 3-dB bandwidth at 1550 nm (GHz) | SSMF 19.764, NZ-DSF 37.207, NANF 55.310 | workbook 19.765, 37.208, 55.31 | at most 0.001 | reported only |
| 3-dB bandwidth over 46 wavelengths, 1.400 to 1.625 um: max abs difference (GHz) | SSMF 0.00098, NZ-DSF 0.0064, NANF 0.00093 | workbook Fig. 1(b) | max relative 6e-5 | reported only |
| Latency n L / c, 21 lengths: max abs difference (us) | at most 5e-6 | workbook Fig. 1(d) | | reported only |
| Latency saving at 5 km (SSMF minus NANF) | 7.7587 us, 31.7% | paper prose "about 8 us"; workbook 7.7587 us | 0.24 us from the rounded prose | reported only |

Against the paper's prose (no tolerance, not scored). The prose first null "about 25 GHz at 5 km" is 3 GHz below the
27.97 GHz that both our arithmetic and the workbook give (Sources, mismatch 8; the gap is unexplained and
chirp is a hypothesis only). The prose "NANF bandwidth above 60 GHz" (Sec. II, p. 3) is a statement about the
window of about 60 nm in which the NZ-DSF is broader than the NANF, not about the whole band, and it agrees with the
workbook there: at the grid wavelengths where the NZ-DSF exceeds the NANF (1445 to 1500 nm) the NANF 3-dB bandwidth is
69.77 down to 60.55 GHz, and over 1430 to 1490 nm it is 73.67 down to 61.84 GHz. (Over the whole band the workbook NANF
bandwidth runs from 49.76 to 86.14 GHz, and our recomputation gives 49.755 GHz as the band minimum; the paper's sentence
makes no claim about that.) An earlier version of this report charged a mismatch to the paper here; it was a mistake of
this report, withdrawn. "More than twice the SSMF bandwidth across the range": the smallest
ratio is 2.529 simulated and 2.529 in the workbook. NZ-DSF wider than NANF: at the grid wavelengths from 1445 to
1500 nm, simulated and in the workbook alike (the paper says a window of about 60 nm around 1460 nm).

What this shows: our dispersion and latency arithmetic reproduces the paper's own numerical model to the
precision of its rounded inputs. It says nothing about any fibre or about the measurements.

## 4. Benchmark C: Fig. 5, assembled-link loss

Plan status: the Fig. 5 ROP columns and the NANF loss column are calibration inputs (section 2), so reading
them is allowed. No holdout is needed for this block.

| Item | Value (`derived` from the 19 points) | Paper statement |
|---|---|---|
| Points, span | 19, 1460 to 1640 nm | 19 wavelengths, laser 1460 to 1640 nm |
| NANF link loss, minimum | 6.45 dB at 1610 nm | 6.45 dB at 1610 nm |
| NANF link loss, maximum | 8.33 dB at 1460 nm | 6.45 to 8.33 dB |
| ROP at the NANF link (and B2B) | -12.96 to -6.24 dBm | maximum available ROP |
| ROP at the SSMF link | -9.85 to -4.98 dBm; 6 of 19 points lie 0.01 to 0.02 dB above -5 dBm | "capped at -5 dBm" |
| Upper bound on distributed loss | at most 1.355 dB/km at 1610 nm (total at the minimum, 6.45 dB, over about 4.76 km, lumped loss at least 0); at 1460 nm the bound is 1.75 dB/km (8.33 dB over about 4.76 km); in general total(lambda) / L, and L is itself approximate | none |

Separation of distributed and lumped loss: not separable from these data, so the distributed
attenuation stays unknown. The column is the insertion loss of the assembled link (two NANF pieces, their
splice and the SSMF pigtails). The paper says it includes "around 2 dB" of pigtail and splice loss and "around
0.1 dB" for the NANF-NANF splice: both approximate, with no uncertainty, no method and no stated wavelength
dependence. Subtracting them would turn two rounded prose numbers into a per-kilometre loss and a
spectrum. The NANF profile (`configs/fibers/NANF-HONG-2021-4P76KM.yaml`) keeps its attenuation unknown, its
pigtail value of about 2 dB, and the total is never added to it, so the pigtail is not counted twice.
`link_loss_at` returns the total as one number, linear inside 1460 to 1640 nm and refusing any other
wavelength (no extrapolation). Because the benchmark runs use the matched-received-power protocol (the ROP of
Fig. 5 sets the received power), the loss does not enter a simulated waveform at all.

## 5. Dependency report for N3 (Fig. 4 and Fig. 6 simulation; not implemented here)

Exists: SRRC shaping on a periodic grid and band-limited periodic resampling
(`transmitter/pulse.py`: `shape`, `resample_periodic`); the Mach-Zehnder law, thermal and shot noise, receiver low-pass and
the fixed-launch and matched-received-power protocols (`optical_channel/link.py`); a symbol-spaced FFE
(`receiver/dsp.py`); the profile propagation of N1; this importer. Missing:

1. DFE. T/2-spaced feed-forward plus symbol-spaced feedback, (17, 7) taps, RLS with forgetting factor 0.998. None exists
   (roadmap S2-2 not started). The split of 17 and 7, the training length, the initialisation and the
   decision-directed switch are `unknown` in the paper and must be declared before the freeze hash.
2. Tx signal chain at the stated rates. PAM4 mapping; SRRC with roll-off 0.1 at 70 samples per symbol,
   then decimation by 40, 50 or 56 (what the paper describes), giving 1.75, 1.40 and 1.25 samples per symbol at the
   70 GSa/s AWG. `shape` does this on a periodic grid: the symbol count must be a multiple of 4 for 1.75 and 1.25 samples per symbol and of 5 for 1.40 (a multiple of 8 is wrong for 1.40: 8 x 1.4 = 11.2); a multiple of 20 serves all three rates, and `resample_periodic` rounds silently, so N3 must assert an integer sample count.
3. Analogue chain on a finer grid. The 70 GSa/s waveform cannot carry the square-law product, so the link must run
   at an oversampled rate (for example 280 GSa/s through `resample_periodic`), with the Tx bandwidth, the
   MZM and the Rx bandwidth as parameters (4th-order Butterworth per plan B4).
4. Scope. 80 GSa/s sampling (ratio 2/7 from 280 GSa/s), resampling to 2 samples per symbol, and the match filter at T/2.
5. Receiver noise. Thermal and shot noise exist; the additive white "electrical SNR ceiling" ahead of the equaliser (plan B4) does not.
6. Metrics. SNR per plan B6 (after the equaliser, before the decision, over all scored symbols), BER by error counting
   with censoring below 1e-5, and the C1 crossing rule of A3, B1 and C1-R. A BER floor of 1e-5 needs about 1e7
   symbols for 100 errors; the RLS loop is per-sample, so cost and seed policy must be set first.
7. Fit machinery. At most 6 parameters (B4 table) by least squares on the B2B calibration points of A4, the Gauss-Newton
   information matrix and the flag rule of B4, the B2B fit-quality gate of B3.2, the parameter freeze and its hash. None exists.
8. D(lambda) for the sweep. NANF and SSMF at the 17 wavelengths 1460 to 1620 nm: `d_table_from_workbook` gives the
   paper's own curves (`published-numerical-assumption`), valid 1400 to 1625 nm. The G.652.D preset is the alternative for SSMF. The NANF
   attenuation stays unknown, which the matched protocol makes irrelevant.
9. Chirp. No transmitter chirp parameter exists. The primary run is at zero chirp (A1.2); the sensitivity sweep of A1.5
   needs one, for example a phase term (alpha / 2) ln P(t) on the launched field, labelled a sensitivity.

10. Declared assumptions, one label each (plan Amendment 4, D2): DAC resolution, RIN, the symbol sequence,
    the capture length and the responsivity are not stated by the paper. Amendment 4 declares each as `user-assumed`;
    the code default of 0.8 A/W for `responsivity_a_per_w` must not be taken silently (it is degenerate with the
    thermal-noise density), so the N3 configuration passes it explicitly.
11. Scoring logic of the plan that has no code yet: the B2B-copy comparator, the discriminating measure d, and the C3
    penalty and BER test. Amendment 4, D3, specifies them; N3 implements them as written.
12. The Fig. 5 / C5 conflict (6 SSMF points above -5 dBm) is settled by Amendment 4, D1: C5 scores all 17 wavelengths of B2.
13. Fig. 4 points above -5 dBm: the importer now returns them with `NanfSeries.above_rop_cap`; N3 must drop those points
    from the fit and from scoring (A4). The three B2B points per curve above the cap are excluded.
14. `read_nanf_workbook(include_holdout=True)` is an honour-system flag and `expected_sha256` is caller-set. At N3 the
    holdout read must be tied to proof of the freeze hash (Amendment 4); not implemented in this gate.
15. OFDM (C6 to C8, Figs. 7 to 12) lies outside the scope of this N3 list: no DMT or OFDM transmitter, loading algorithm
    or per-subcarrier SNR path is described here.

Smallest original implementation: (a) `receiver/dfe.py`, a standard exponentially-weighted RLS DFE derived from
the normal equations, with the unknown choices as declared arguments; (b) `measurement/nanf_chain.py`, one function
that maps symbols to the Tx waveform, runs the link at the oversampled rate, the scope and the match filter, and returns
equaliser output, SNR and BER; (c) a six-parameter fit and identifiability module that follows B4 literally.
Chirp is a separate optional field of `LinkConfig`, added only for the sweep. No existing G.652.D path changes.

## 6. Limits

One paper, one laboratory, one NANF spool and one SSMF spool: the label stands whatever any later score says. The
PDF is an author manuscript, so quoted prose may differ from the published version. The Fig. 1 block recomputes
the paper's own rounded model, so agreement shows consistent arithmetic and nothing more. The Fig. 5 loss is a total and is not separated.

## 7. Reproduce

`PYTHONPATH=src python -c "from opticps.measurement.nanf_import import read_nanf_workbook; from opticps.measurement.nanf_benchmark import fig1_report, link_loss_summary; w = read_nanf_workbook('data/external/nanf_hong2021/extracted/dataset_JLT_NANF_vs_SMF.xlsx'); print(fig1_report(w)); print(link_loss_summary(w))"`
(the default read withholds every holdout series). The block below is checked against a recomputation by
`tests/test_nanf_benchmark.py` when the workbook is present.

```json
{
  "first_null_ghz_5km": {"SSMF": 27.970, "NZ-DSF": 52.659, "NANF": 78.210},
  "bandwidth_3db_at_1550_ghz": {"SSMF": 19.764, "NZ-DSF": 37.207, "NANF": 55.310},
  "latency_saving_5km_us": 7.7587,
  "fading_max_abs_diff_db_stated_d": {"SSMF": 0.011669, "NZ-DSF": 4.7e-06, "NANF": 0.001567},
  "link_loss_db": [6.45, 8.33],
  "link_loss_min_wavelength_nm": 1610.0
}
```
