# NANF benchmark: sources, licences, schema and provenance (Gate N0)

Written 2026-10-31. Scope: Hong et al. 2021 (NANF versus SSMF, IM/DD). Nothing here is a fit or a
simulation. Third-party data, the PDF and figures are not in Git. Parameter facts below are small
and carry their provenance. Companion plan: `docs/benchmarks/NANF_FIT_HOLDOUT_PLAN.md`.

Provenance vocabulary (a parameter or claim carries exactly one of these tags, written in square
brackets after the word prov, as in the tables below):
`measured`, `published-experimental`, `published-numerical-assumption`, `derived`,
`representative-literature`, `user-assumed`, `fitted-training-only`, `unknown`.
`measured` means a quantity the source reports as measured in its own experiment and that we read
from its text or data. `published-experimental` is a setting or description of the experiment. Both
are only as reliable as the source: a tag records how the value became known, not that it is true.

## 1. Objects, identifiers and retrieval

| Object | Identifier | Local file (ignored by Git) | SHA-256 | MD5 |
|---|---|---|---|---|
| Paper (author manuscript, see 1.1) | DOI 10.1109/JLT.2021.3097278 | `data/external/nanf_hong2021/FINAL_VERSION.pdf` | `b5296da062134da666da5cc105e9ede804d735f6c19f6d7e65d1f9b3435de3cf` | not recorded |
| Dataset archive | DOI 10.5258/SOTON/D1889 | `.../dataset_JLT_NANF_vs_SMF.zip` | `f35c083e75abc123a971f398ab50dd46b3a3d9df8763a1da9bda2d3914c02bc9` | `75df7a27e2125be5c5d852f03d36ff1a` |
| Workbook (zip member) | same | `.../extracted/dataset_JLT_NANF_vs_SMF.xlsx` | `0753aeadd215e894e46de6cb7ac10df4c9edf32386ffdc37871381d80cc19cc0` | not recorded |
| Readme (zip member) | same | `.../extracted/readme_JLT_NANF_vs_SMF.txt` | `a782d1877e268f3274fd835835428ee570c5caea5f5ea158201543aebce473f4` | not recorded |

Checks run in N0: SHA-256 and MD5 of the zip and SHA-256 of the PDF equal the owner-supplied values.
The two extracted files are byte-identical (SHA-256) to the two members of the zip, which holds only
those two members (45,202 and 2,407 bytes). Retrieval date: the files were supplied by the owner and
carry local modification times of 2026-10-31 (16:44 to 16:48); the original download date and URL are
not known to this gate. Zip member timestamps are 2021-07-13. The dataset readme gives the file date
as July 2021 and the data collection date as May 2020, University of Southampton, UK.

### 1.1 Which version of the paper is this

The PDF is a Word-produced author manuscript, not the published version. Evidence from the file:
Microsoft Word 2016 as producer, creation date 2021-07-12, a placeholder paper-identification line on
every page, "Manuscript was received XX xx, 2021", "Digital Object Identifier: XXXXXX", and a
document-subject field reading "IEEE Transactions on Magnetics" (a template leftover). It has 8
pages and the same author list, title and figure numbering as the published article (volume 39,
issue 19, pages 6167 to 6174 per Crossref). Whether numbers in the published version differ from this
manuscript is unknown. Any value used downstream is tagged to this manuscript, not to the published
version.

## 2. Licence and use, per object

Checked 2026-10-31. This is a record of what was read, not legal advice.

| Object | What was read | Status | Private use | Redistribution |
|---|---|---|---|---|
| Dataset D1889 | DataCite `rightsList` for the DOI (queried again in N0): "Creative Commons Attribution 4.0 International", SPDX `cc-by-4.0`. The readme `Licence:` field is blank. The repository landing page was not read (HTTP 403 to the fetcher). University page: default CC BY on open data. | CC BY 4.0 at the DOI-registry record only. Readme blank. Landing page unread. | Yes | CC BY 4.0 allows sharing and adaptation with attribution and an indication of changes. This project still keeps the data out of Git (owner rule, N0), because the readme is silent and the landing page was not read. |
| Paper | Crossref lists the IEEE licence for the version of record and the accepted manuscript. No Creative Commons licence. | Restricted (IEEE terms) | Reading and private analysis only | No. No PDF, figure, table or long quotation in Git or in reports. Small parameter facts with a citation only. |
| Secondary sources (Section 7) | Crossref metadata only. Licence recorded where present. | See Section 7 | Metadata only | Not read, not redistributed |

Attribution text required by CC BY 4.0 if any dataset-derived content is ever shared (title, author,
source, licence link, and an indication of changes):

> Hong, Y., Bradley, T. D., Taengnoi, N., Bottrill, K. R. H., Hayes, J. R., Jasion, G. T., Poletti,
> F., Petropoulos, P., and Richardson, D. J. (2021). Dataset for "Hollow-core NANF for High-speed
> Short-reach Transmission in the S+C+L-bands". University of Southampton.
> https://doi.org/10.5258/SOTON/D1889. Licensed under CC BY 4.0
> (https://creativecommons.org/licenses/by/4.0/). Changes: summarised and compared against
> simulation by OpticPS; values may be reformatted.

The DataCite creator list gives "Bottrill, Kyle"; the paper and readme give "Kyle R. H. Bottrill".
The longer published form is used above.

## 3. Figure-to-sheet mapping

The readme lists data for Figs. 1, 4 to 12. Figs. 2 and 3 are diagrams (setup and DSP block
diagram) and have no sheet. Workbook labels differ from the paper: `SMF` means SSMF; `OFDM` is the
uniformly-loaded DDO-OFDM (Figs. 8, 9); `DMT` is the adaptively-loaded DDO-OFDM (Figs. 10 to 12).

| Sheet | Paper figure | Content (paper caption) |
|---|---|---|
| Fig.1 | Fig. 1 | Numerical: (a) CD, (b) 3-dB bandwidth at 5 km, (c) CD power-fading profile at 5 km and 1550 nm, (d) latency at 1550 nm |
| Fig.4 | Fig. 4 | BER and SNR versus ROP at 1550 nm, 80/100/112 Gb/s, SSMF, B2B, NANF |
| Fig.5 | Fig. 5 | ROP used per link versus wavelength; measured NANF link loss |
| Fig.6 | Fig. 6 | BER and SNR versus wavelength, S+C+L, 80/100/112 Gb/s, three links |
| Fig.7 | Fig. 7 | Uniform 16QAM DDO-OFDM, BER and average SNR versus data subcarriers, ROP -7 dBm |
| Fig.8 | Fig. 8 | SNR profile, 240 subcarriers, uniform, NANF and SSMF |
| Fig.9 | Fig. 9 | 65.625 Gb/s 4QAM DDO-OFDM, BER and SNR versus ROP |
| Fig.10 | Fig. 10 | Adaptive DDO-OFDM, BER versus data subcarriers |
| Fig.11 | Fig. 11 | Adaptive DDO-OFDM, SNR profile, 240 subcarriers |
| Fig.12 | Fig. 12 | Maximum capacity and corresponding BER versus ROP |

## 4. Schema report (structure; N0 step B)

Workbook: 10 sheets, all visible, no charts or images, no hidden sheets. Every sheet is a plain table.
No header or other cell carries a unit string. Units below are inferred from the paper's axes
(`derived`). Row 1 is a title in the multi-block sheets (Fig.1, 4, 6), merged across four columns.

| Sheet | Dimension | Axis column(s) | Series (header cells) | Points per series |
|---|---|---|---|---|
| Fig.1 | A1:V49 | wavelength (A, G), frequency (M), fibre length (S) | (a) NANF, SSMF, NZ-DSF; (b) SMF@5km, NZ-DSF@5km, NANF@5km; (c) NANF, SMF, NZ-DSF; (d) SSMF, NZ-DSF, NANF | 46, 46, 36, 21 |
| Fig.4 | A1:N30 | ROP (A, F, K), repeated per BER and SNR block | per rate (80, 100, 112): NANF, B2B, SMF; BER block rows 4 to 16, SNR block rows 20 to 30 | B2B and SMF 11; NANF 6 |
| Fig.5 | A1:D20 | wavelength | ROP@NANF, ROP@SSMF, NANF loss | 19 |
| Fig.6 | A1:N45 | wavelength (A, F, K) | per rate: NANF, B2B, SMF; BER block rows 4 to 22, SNR block rows 27 to 45 | 19 |
| Fig.7 | A1:E9 | subcarrier number | SMF-BER, NANF-BER, SMF-Average SNR, NANF-Average SNR | 8 |
| Fig.8 | A1:C241 | frequency | 240sub-NANF-OFDM, 240sub-SMF-OFDM | 240 |
| Fig.9 | A1:E9 | ROP | SMF-OFDM-BER, NANF-OFDM-BER, SMF-OFDM-SNR, NANF-OFDM-SNR | SMF 8; NANF 6 |
| Fig.10 | A1:C9 | subcarrier number | SMF-DMT-BER, NANF-DMT-BER | 8 |
| Fig.11 | A1:C241 | frequency | 240sub-NANF-DMT, 240sub-SMF-DMT | NANF 240; SMF 216 numeric |
| Fig.12 | A1:E9 | ROP | SMF-DMT Capacity, NANF-DMT Capacity, SMF-DMT BER, NANF-DMT BER | SMF 8; NANF 6 |

Inferred units (`derived`): Fig.1 wavelength in micrometres (axis 1.4 to 1.625, matching the paper's
axis), Fig.1 frequency in GHz and length in km; Figs. 5, 6 wavelength in nm; ROP in dBm; SNR in dB;
BER linear; loss in dB; capacity in Gb/s; OFDM frequency in GHz. The unit change between Fig.1
(micrometres) and Figs. 5, 6 (nm) is a trap for any reader that assumes one unit for all sheets.
Series counts: Fig.4 and Fig.6 each have 18 series (3 rates by 3 links by BER and SNR), Fig.1 12, Fig.5
3, Fig.7 4, Fig.8 2, Fig.9 4, Fig.10 2, Fig.11 2, Fig.12 4 (all excluding the axis columns).

## 5. Value checks (N0 step D, run after the plan was committed)

Run after commit 9a891c9 of the plan. No fit, no simulation, no comparison with the paper's prose
numbers. Performance cells were tested only for presence, type and a coarse range class.

- Presence and type: apart from the Fig.11 error cells below, no text cell sits in a numeric position.
  Axis columns are numeric and strictly monotonic in every block. A series cell is numeric only where
  its axis cell is present.
- Fig.4 NANF has 6 ROP points per curve (axis from -12 dBm to -6.67 dBm, including fractional
  -8.34 and -6.67), against 11 for B2B and SSMF (axis -12 to -2 dBm). Three B2B and SSMF points
  (-4, -3, -2 dBm) lie beyond the paper's -5 dBm receiver limit and are excluded from scoring by the plan.
- Fig.9 and Fig.12 NANF have 6 of 8 points (ROP -12 to -7 dBm). The -6 and -5 dBm rows are blank.
- Fig.11, SSMF column: 24 of 240 cells hold a cached error (`#NAME?`) from 24 formula cells. They sit
  between 22.15 and 25.43 GHz, the region of the SSMF spectral null. Of the 25 text cells in the
  column, one is the header. Consequence for the plan: the SSMF null in criterion C6 can be scored
  on Fig.8 (240 numeric) but not on Fig.11. Unusable cells are treated as missing, never as a number.
- BER of exactly 0 (an error-free capture) occurs at 80 Gb/s: Fig.4 NANF 1 and B2B 3 points; Fig.6
  NANF 12 and B2B 12 of 19 points; Fig.10 one point per fibre. These cannot be put on a log scale and
  are censored under plan section 3. The error-count depth behind a zero is not stated. All other BER
  cells are in (0, 1]. No negative, infinite or non-numeric BER or SNR cell was found.
- Fig.8 SSMF SNR has 13 cells below -5 dB (the nulls). The paper's own axis runs to -20 dB.
- Fig.8 and Fig.11 frequency axes run 0.13672 to 32.8125 in 240 equal steps. 0.13672 is
  70/512 to the printed precision, which is consistent with the 70 GSa/s AWG and a 512-point IFFT
  [prov: derived]. This is a check on the axis only.
- Fig.5, Fig.6: 19 wavelength points from 1460 to 1640 nm; the figure's printed ticks span 1470 to
  1620 nm. The laser range in the paper is 1460 to 1640 nm.
- Naming trap: `SMF` in headers is the paper's SSMF; Fig.1 series order differs between blocks.

## 6. Per-parameter provenance (from the PDF manuscript)

| Parameter | Value | Tag | Note |
|---|---|---|---|
| NANF spool length | ~4.76 km, two matched NANFs arc-fusion spliced | `[prov: published-experimental]` | pieces ~3.4 km (#1) and ~1.4 km (#2) sum to 4.8 km; the "~" covers the 0.04 km gap |
| NANF #1 / #2 geometry | core 36.4 / 34.6 um, membrane 0.55 / 0.50 um (averages) | `[prov: published-experimental]` | paper cites its ref. [32] |
| NANF-NANF splice loss | ~0.1 dB | `[prov: published-experimental]` | "around" |
| Connectorisation (SSMF pigtails) | multiple splices, ~2 dB total | `[prov: published-experimental]` | method not stated; included in the link loss below |
| NANF link loss | 6.45 to 8.33 dB over S+C+L, minimum 6.45 dB at 1610 nm | `[prov: measured]` | includes the ~2 dB; the paper text; Fig. 5 data in the workbook |
| SSMF length | ~4.53 km: spools ~4 km and ~0.5 km | `[prov: published-experimental]` | |
| CD at 1550 nm, 5 km simulation | SSMF 15.95, NZ-DSF 4.50, NANF 2.04 ps/(nm km) | `[prov: published-numerical-assumption]` | "assumed"; SSMF and NZ-DSF are mean values of the ITU G.652 and G.655 ranges; the NANF value has no stated source beyond the design in the paper's ref. [32] |
| CD slope | not given | `[prov: unknown]` | needed by any wavelength-dependent run (Fig. 6) |
| Refractive index for latency | SSMF 1.4682 (Corning SMF28e), NZ-DSF 1.4693 (Corning LEAF), NANF 1.003 (ref. [2]) | `[prov: published-numerical-assumption]` | the paper says "(effective) refractive indices"; see mismatch 1 |
| Latency saving at 5 km | ~8 us, ~30% | `[prov: derived]` | recomputed here: (1.4682 - 1.003) x 5 km / c = 7.8 us; 1 - 1.003/1.4682 = 31.7% |
| Modulation | Nyquist PAM4 at 80, 100, 112 Gb/s | `[prov: published-experimental]` | |
| PAM4 symbol rate | 40, 50, 56 GBd | `[prov: derived]` | 70x up-sample then 40/50/56x down-sample to a 70 GSa/s AWG gives 70 x Rs / D = 70 GSa/s |
| PAM4 rate meaning | 2 bits x symbol rate, so a gross line rate before FEC | `[prov: derived]` | the paper does not say gross or net; the 7% FEC figure is used only as a BER threshold |
| Samples per symbol at the AWG | 1.75, 1.40, 1.25 | `[prov: derived]` | 70 GSa/s divided by the symbol rate |
| Pulse shape | square-root raised cosine, roll-off 0.1 | `[prov: published-experimental]` | |
| AWG | 70 GSa/s | `[prov: published-experimental]` | model, resolution, analogue bandwidth: `unknown` |
| Oscilloscope (DSO) | 80 GSa/s | `[prov: published-experimental]` | model, bandwidth: `unknown` (the paper says the DSO cut-off limits subcarriers to 240) |
| Equaliser | T/2-spaced (17,7)-tap DFE, RLS, forgetting factor 0.998 | `[prov: published-experimental]` | which of 17 and 7 is feed-forward is not stated: `unknown`; training length, initialisation, decision-directed operation: `unknown` |
| BER threshold | 3.8e-3, called the 7% FEC limit | `[prov: published-experimental]` | |
| Required ROP at BER below 3.8e-3 | about -12, -11, -10 dBm at 80, 100, 112 Gb/s, for B2B and NANF | `[prov: published-experimental]` | "around"; SSMF never reaches the limit |
| Receiver limit | upper ROP limit -5 dBm | `[prov: published-experimental]` | imposed because the PD transimpedance amplifier input range degrades results above it |
| SSMF extra SNR penalty | about 5, 11, 14 dB at 80, 100, 112 Gb/s | `[prov: published-experimental]` | prose estimate |
| DDO-OFDM | 512-point IFFT, cyclic prefix 1/16 symbol, 240 data subcarriers = 32.8125 GHz | `[prov: published-experimental]` | |
| OFDM rates | 54.6875 to 131.25 Gb/s (16QAM), 65.625 Gb/s (4QAM, 240 sub) | `[prov: derived]` | rate = subcarriers x bits x (70 GSa/s / 512); the cyclic-prefix overhead is not subtracted |
| Laser, MZM, driver, PD, attenuator | tunable laser 1460 to 1640 nm; no launch power, V-pi, bias, extinction ratio, PD or TIA data | `[prov: unknown]` | only the laser range is stated |
| Captured symbols, repeats, error-count depth | not stated | `[prov: unknown]` | blocks any noise estimate |
| Any value we fit to B2B later | | `[prov: fitted-training-only]` | never reported as a source value; none exists at N0 |
| Tx/Rx values taken from a datasheet or paper other than this one | | `[prov: representative-literature]` | none used at N0 |
| Values the owner or a later gate chooses | | `[prov: user-assumed]` | none at N0 |

## 7. Secondary sources (Crossref metadata only; no full text read)

Each is a separate sample. No data, spool or result of one is pooled with another or with Hong et
al. Metadata cannot show that two papers did not use the same physical fibre, so this register does not
assert "no shared spool". It adopts the stricter rule that each stays separate and unpooled. One
overlap is visible: Altuna et al. and the CLEO abstract each report an 11.1 km hollow-core span, so
those two may share a spool and must never be treated as independent samples. Authors are as given in
the Crossref author lists.

| Source | DOI | Published authors | What the metadata says | Crossref licence |
|---|---|---|---|---|
| Altuna et al. 2024, Laser & Photonics Reviews 18(8), 2400157 | 10.1002/lpor.202400157 | Rubén Altuna, Yongmin Jung, Periklis Petropoulos, Carmen Vázquez | Power over fibre and analog radio over fibre in single-mode, multicore and hollow-core fibres. Hollow-core spans of 3.1 km and 11.1 km are mentioned. The fibre design is called hollow-core, not NANF, in the abstract. | CC BY 4.0 (version of record) |
| Wang et al. 2025, Chinese Optics Letters 23(2), 020604 | 10.3788/COL202523.020604 | Chen Wang, Jianyu Long, Bohan Sang, Bowen Zhu, Peng Li, Kaihui Wang, Wen Zhou, Lei Shen, Jianjun Yu | Broadband hollow-core NANF transmission with optimal carrier phase estimation for probabilistic shaping. No abstract in the record. | none listed |
| CLEO 2025 abstract SS135_4 | 10.1364/CLEO_SI.2025.SS135_4 | Suttikarn Wantee, Kyle R.H. Bottrill, Douglas McCulloch, Hao Liu, Nura Adamu, Yang Hong, Gregory T. Jasion, Hesham Sakr, John R. Hayes, Francesco Poletti, Periklis Petropoulos | "High Linearity 108Gbit/s PAM8 Transmission over 11.1km of Nested Antiresonant Nodeless Fiber"; abstract mentions 108 Gbit/s PAM8 over about 10 km | none listed |

The brief calls the second source "Wang et al." and the third "the CLEO 2025 abstract"; the first
author of the third is Suttikarn Wantee. Treat all three as `representative-literature` at most, and
only for a later cross-check, never for calibration.

## 8. Mismatches between the owner brief and the PDF

Checked claim by claim against the manuscript text. Claims not listed here matched.

1. Index terminology. The brief says "group index" for 1.4682 (SSMF) and 1.003 (NANF). The paper says
   "(effective) refractive indices" and does not use the words group index. The values match; the label
   does not. Whether those numbers are group or phase indices is not stated by the paper, and Corning
   datasheet values were not checked. Keep the paper's label and tag
   `published-numerical-assumption`.
2. Length arithmetic. 3.4 km plus 1.4 km is 4.8 km, not 4.76 km. The paper gives ~4.76 km for the
   spliced spool and "~" for both pieces, so this is rounding, not an error. Use 4.76 km for the NANF
   total and do not reconstruct it from the pieces.
3. Gross versus net. The brief leaves it open. The paper does not say. Derived result: the three rates
   are exactly 2 bits per symbol times 40, 50, 56 GBd, so they are gross line rates; FEC overhead is
   not subtracted.
4. Equaliser tap split. The brief writes "(17,7)-tap". The paper writes the same and does not say which
   number is feed-forward. Treat the split as `unknown`.
5. Splice and pigtail loss. The brief writes "splice/pigtail ~2 dB". The paper separates ~0.1 dB for the
   NANF-NANF splice and "around 2 dB" for the multiple splices that connectorise the two ends through
   SSMF pigtails. Do not apply the 2 dB to the NANF-NANF splice.
6. Document version. The brief treats the PDF as the paper. It is an author manuscript with template
   placeholders (Section 1.1), so it may differ from the published article.

Matched without difference: length ~4.76 km with ~3.4 + ~1.4 pieces; SSMF ~4.53 km (~4 + ~0.5);
D at 1550 nm of 15.95, 4.50, 2.04 ps/(nm km) as assumed values; link loss 6.45 to 8.33 dB; ~2 dB splice
loss; 80/100/112 Gb/s PAM4; AWG 70 GSa/s; scope 80 GSa/s; SRRC Nyquist shaping; T/2-spaced (17,7)-tap
RLS-DFE with forgetting factor 0.998; ROP about -12, -11, -10 dBm at BER below 3.8e-3 (B2B and NANF);
receiver limit -5 dBm (an imposed upper limit due to the TIA input range).

## 9. Honest limits

Single paper, single setup, single session. One NANF spool and one SSMF spool, so the dataset label is
`LITERATURE BENCHMARK / CALIBRATION ONLY` (plan section 1). The workbook structure and the paper were
read before the plan; no numeric cell was read before it. The licence of the dataset rests on the
DOI-registry record; the readme is blank and the landing page was not read.
