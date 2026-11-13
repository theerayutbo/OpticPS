# Benchmark source register (Stage 3A, gate E0)

Retrieval date of all metadata below: 2026-10-31. Repository state: branch `v1.3-mpam`, base HEAD
`8129eca` (E0 commits on top; this register was corrected in the E0 fix round). E0 and the fix round
downloaded nothing and opened nothing under `data/external/`: no dataset file, no source-data XLSX, no
PDF asset. Clean room kept: no optical-simulator source, notebook, package or code-containing page
was opened; no code link on any page was followed.

## How facts were read (status vocabulary of `docs/engineering_log/VERIFICATION.md`)

| Label | Meaning here |
|---|---|
| verified | the raw text of the primary record was read by us on 2026-10-31 (JSON or XML fetched with `curl` from metadata endpoints; never a `/files/` endpoint, never a dataset or PDF asset). Raw reads in the fix round: Zenodo API records 7886498 and 7886228, DataCite JSON of 7886498, Crossref JSON of the Ran and Wiegart DOIs, Europe PMC full-text XML of PMC12234763. |
| summary | read through the WebFetch tool (model-written summary of a page); not raised to `verified` unless a raw read above covers the same statement |
| user-supplied | stated in the owner's brief or roadmap, source not read (`brief` below) |
| unconfirmed | not read; unknown |

Pages that could not be read: `nature.com` article page (cookie-handshake redirect loop, not
worked around), `pmc.ncbi.nlm.nih.gov` (reCAPTCHA page), `ieeexplore.ieee.org` (empty).
Bibliographic data for these came from Crossref and the Europe PMC copy of the full text
(`PMC12234763`); the fix round re-read both as raw JSON and XML, so the statements they carry are
`verified` as statements of those records. The Europe PMC XML is a copy of the paper's text, not
the publisher page, and it holds no figure data. Statements in the sections below that were not
covered by a raw read keep the label `summary`; the E0 first pass used a fetch tool whose output
was a summary, and calling that the strongest reachable status was wrong, because the raw JSON and
XML were one `curl` away.

## Source 1. TERIPHIC photodiode arrays (Dataset A, P0)

| Item | Value | Read as |
|---|---|---|
| Title | Experimental characterization of TERIPHIC 4-fold and 8-fold InP photodiode arrays - Detection of 50Gbaud signals with NRZ and PAM-4 modulation formats | verified (Zenodo API JSON) |
| Creators | Panos Groumas, Efstathios Andrianopoulos, Christos Tsokos (ICCS). Contributors: David De Felipe, Norbert Keil, Patrick Runge (Fraunhofer HHI); Paraskevas Bakopoulos (NVIDIA) | verified (JSON) |
| DOI / URL | `10.5281/zenodo.7886498`; https://zenodo.org/records/7886498; concept DOI `10.5281/zenodo.7886497` | verified (JSON) |
| Dataset version | The raw record has no version label: Zenodo `revision` is 2 (a record counter), `metadata.version` is absent and the DataCite `version` is `null`. Published 2023-05-02, modified 2023-05-03 (JSON `created`, `modified`). The "v1" the first-pass fetch tool reported is not in the JSON or DataCite and was an artefact of the tool's summary (see discrepancy 1). | verified (JSON, DataCite) |
| Funding | EC H2020 TERIPHIC, GA 825502 | verified (JSON `grants`) |
| Files | 28 (14 NRZ, 14 PAM4), 4,587,523,808 bytes in total (sum of the listed sizes), every file 163,840,136 bytes | verified (JSON `files`) |
| Target MD5 (supplied by the record) | B2B `d7bd6d48bc020a138f4f129bc2ba7312`; 2 km `d9e3c533394c53c3575491558ffc35b1`; 10 km `3d8774b068deaf50f37892b38953dfd6` (PD1, Subassembly 1, PAM4). | verified (JSON `files[].checksum`) |
| Local hashes | see "Local hashes" below: reported by the orchestrator, not computed by E0 or the fix round. | orchestrator report |
| Data licence | CC-BY-4.0, record-level: JSON `license.id` is `cc-by-4.0`, `access_right` is `open`; DataCite `rightsList` gives `cc-by-4.0` (SPDX). No separate licence file or terms for individual files inspected, hence status `RECORD_LEVEL`. Private research use: allowed. Public redistribution of derived data: allowed with attribution. | verified (JSON, DataCite) |
| Article licence | none: the record is a dataset; no associated article was identified. `LICENSE/REUSE TERMS UNVERIFIED` for any article | unconfirmed |
| Description wording | The record names "a commercially available off-the-shelf (COTS) laser source", a COTS Mach-Zehnder modulator and the TERIPHIC PD arrays; models are not named, and the word "CW" does not appear. It names NRZ and PAM-4 formats at 50 Gbaud, two subassemblies (four and eight InP photodiodes), a real-time oscilloscope sampling at "256 Gbaud" (sic), lengths B2B (0 km), 2 km and 10 km, and the O-band. | verified (JSON `metadata.description`) |
| Instrument parameters stated | symbol rate 50 GBd; sampling given as "256 Gbaud" (unit wording wrong; read by us as 256 GSa/s, label INFERRED, nominal 5.12 samples/symbol). In the record's words the data are "actually the samples extracted from the oscilloscope", so the files are scope output, not transmitter data. Not stated: oscilloscope model, bandwidth, ENOB, vertical scale, laser wavelength or power, modulator model or Vpi, fibre type, launch power, PRBS or pattern, pulse shaping, DAC/AWG | verified (JSON description; absences are absences in that text) |
| Data fields | File name template per record: "Symbol rate#Modulation formats#PDn#Transmission length#version#Subassemblyn.bin". Actual PD-array names have no `version` token, and PAM4 files for PD4 to PD8 (Subassembly 2) carry no length token (file list). The description gives no content description: no dtype, header, endianness, scaling, units, channel count or sample count | verified (JSON) |
| Sizes | 163,840,136 bytes each = 163,840,000 + 136 (arithmetic on the listed size only; a 136-byte constant is a hypothesis for E1, not a finding) | verified (JSON) + arithmetic |
| Missing | raw format, reference bit/symbol sequence, wavelength, fibre type and dispersion, vertical calibration, device responses, oscilloscope settings, acquisition timestamps | - |

### Local hashes (orchestrator report, re-verified by E1a with `verify_local_asset`, 2026-11-01)

The three target files were downloaded with the owner's approval and first hashed by the orchestrator
(2026-10-31). On 2026-11-01 E1a ran `verify_local_asset` on each file (streaming MD5 and SHA-256, whole
file, no sample value read or kept) and compared the result with the MD5 supplied by the record and
with the orchestrator's SHA-256. All three agree: **MD5 state `verified`** (local MD5 equal to the
supplied MD5), local size 163,840,136 bytes each, SHA-256 equal to the orchestrator's value. The
checksum object is rebuilt at run time (the schema cannot hold a typed-in local hash), so the
committed configs still carry the supplied MD5; the `verified` state is the result of that run and is
asserted by `tests/test_benchmark_provenance.py::test_local_hashes_match_the_register` whenever
the files are present (skipped otherwise). A `verified` state describes the bytes hashed then; it goes
stale if the file changes (`Checksum.still_current`).

| File | Group | MD5 (local, verified = supplied) | SHA-256 (local, equal to orchestrator) |
|---|---|---|---|
| `50G_PAM4_PD1_B2B_Subassembly1.bin` | `7886498/SA1/PD1/B2B` | `d7bd6d48bc020a138f4f129bc2ba7312` | `b9c5968ae4cac4ea53b6bbda62c7255b3ecfa2ff530985c1e4ae0f4e55b9e0b2` |
| `50G_PAM4_PD1_2km_Subassembly1.bin` | `7886498/SA1/PD1/2km` | `d9e3c533394c53c3575491558ffc35b1` | `22fc7bb592681ed6135b5be28a28b1f124344924316b4333508823f7674266d3` |
| `50G_PAM4_PD1_10km_Subassembly1.bin` | `7886498/SA1/PD1/10km` | `3d8774b068deaf50f37892b38953dfd6` | `053bf8c9ba8df00063f5d686508833dc18685ec320d7e373b1877947e15b118b` |

Hashing reads every byte through a digest and no sample value. For the 2 km and 10 km holdout files
that is the only operation E1 performs (plan R5.2).

### Format verification of the B2B file (Gate E1, 2026-11-01; B2B only)

Sample bytes were read from `50G_PAM4_PD1_B2B_Subassembly1.bin` only. The 2 km and 10 km files were
hashed and nothing else (plan R5.2). Result, evidence and caveats are in
`docs/benchmarks/MISSING_PARAMETERS.md` section 4: Keysight BIN v10, one waveform, float32 little-endian
samples at byte 164, 40,959,993 samples, time increment 1/2.048 THz (symbol tone at 50.00019 GHz,
40.96 samples per symbol), `normalized` scale. The record's "256 Gbaud sample rate" stays INFERRED as
256 GSa/s (5.12 samples per symbol nominally); it is eight times lower than the file's own time axis and
is not the rate of the stored stream. The committed configs are unchanged: the record documents no
format, so `raw_format` and `calibration` stay UNKNOWN there, and the finding is a statement about the
local file (`SUPPORTED_BY_EVIDENCE`, not a documented format). The format of the other two files is
`NOT_ASSESSED_HOLDOUT`.

## Source 2. TERIPHIC quad InP EML array (Dataset B, P1, out of MZM model domain)

| Item | Value | Read as |
|---|---|---|
| Title | Experimental characterization of TERIPHIC quad InP EML array - Generation and transmission of 50Gbaud signals with NRZ and PAM-4 modulation formats | verified (JSON) |
| Creators | Groumas, Andrianopoulos, Tsokos (ICCS). Contributors: De Felipe, Troppenz, Keil, Moehrle (HHI), Bakopoulos (NVIDIA) | verified (JSON) |
| DOI / URL | `10.5281/zenodo.7886228`; https://zenodo.org/records/7886228; concept DOI `10.5281/zenodo.7886227` | verified (JSON) |
| Version | Zenodo `revision` 4 (a record counter); no version label in the metadata; published 2023-05-02, modified 2023-05-03. | verified (JSON) |
| Licence | CC-BY-4.0, `access_right` open (JSON `license.id` `cc-by-4.0`). Same caveats as Source 1; status `RECORD_LEVEL`. | verified (JSON) |
| Files | 17 files, all PAM4 `.bin` and **0 NRZ** although the title and the brief say "NRZ and PAM-4": 16 of 40,960,136 bytes and `50G_PAM4_EML2_B2B_v1.bin` of 163,840,136 bytes (MD5 `ae7df638705bd83a0d369b2b86e93f00`); 819,202,312 bytes in total. Full MD5 list is in the JSON record; not copied here. | verified (JSON `files`) |
| Description | quad EML (each a DFB laser, an electroabsorption modulator and a semiconductor optical amplifier); three of the four EMLs were characterised in turn (names carry EML2, EML3, EML4); lengths 0, 2 and 10 km; one commercial photodetector described as having "more than 70 GHz 3-dB bandwidth" (the record misspells "available"); oscilloscope sampling given as "256 Gbaud"; a digitally applied low-pass filter of 50 GHz 3-dB cut-off, stated to improve signal-to-noise ratio; versions v1 to v3 are repeats with the same operating parameters at different time indices | verified (JSON description) |
| Local hashes | none | - |
| Missing | same list as Source 1, plus EML bias and drive, filter details, whether the shipped samples are filtered | - |

## Source 3. Ran et al., Nature Communications 16, 6268 (2025) (Publication C, P1)

| Item | Value | Read as |
|---|---|---|
| Title | A 4x256 Gbps silicon transmitter with on-chip adaptive dispersion compensation (Crossref writes the multiplication sign as a character, not "x") | verified (Crossref JSON, Europe PMC XML) |
| Authors | Shihuan Ran, Yu Guo, Yuanbin Liu, Ting Miao, Yangbo Wu, Yang Qin, Yuyao Guo, Liangjun Lu, Yixiao Zhu, Yu Li, Qunbi Zhuge, Jianping Chen, Linjie Zhou (corresponding: Yu Li, Qunbi Zhuge) | verified (Crossref author list; correspondence from the XML) |
| Journal | Nature Communications, volume 16, issue 1, article number 6268, published 2025-07-07; received 2024-11-08, accepted 2025-06-18 | verified (Crossref, Europe PMC XML) |
| DOI / URL | `10.1038/s41467-025-61408-7`; https://www.nature.com/articles/s41467-025-61408-7; PMC12234763; PMID 40624056 | verified for DOI (Crossref); PMC id from the Europe PMC request; PMID and nature.com URL carried from the first pass (summary) |
| Correction | The publisher's change history (date given as 8/11/2025 in the XML, format ambiguous) records a fix to Eq. (6): the first PDF printed wrong symbols, and the HTML and PDF were corrected afterwards. Equations must be read from the corrected version. | verified (XML) |
| Article licence | CC BY-NC-ND 4.0 (Crossref licence URLs `creativecommons.org/licenses/by-nc-nd/4.0` for `vor` and `tdm`; the Europe PMC XML copyright statement). NC bars commercial use and ND bars sharing adapted material derived from the article or parts of it. **Incompatible with MIT publication: see "Licence conflict" below.** | verified (Crossref JSON, XML) |
| Source Data | The supplementary list names a supplementary-information PDF (MOESM1), a peer-review file (MOESM2) and a source-data spreadsheet `41467_2025_61408_MOESM3_ESM.xlsx`. The data-availability section says data are available from the corresponding authors on request, that source data accompany the paper, and that code is available on request. | verified (XML) |
| **Source-data licence** | **LICENSE/REUSE TERMS UNVERIFIED.** The XML names the file and says source data are provided with the paper; no licence for the XLSX appears. Do not assume it follows the article licence. File not fetched; size, hash, sheet names and columns unknown. | verified as an absence in the XML |
| Instrument and link parameters | Facts cited in our own words (DOI above): fibre dispersion of -3.99 ps/(nm km) at 1271 nm, reported as measured (abstract; Experimental results section; further detail in the paper's Supplementary Information 6); the fibre is named G652.D (printed without a dot after the G, in the Experimental results section and an eye-diagram caption); PAM-4; four lanes at 256 Gb/s over 5 km and 200 Gb/s over 10 km; a 155-tap receiver FFE updated by RLS, alone or combined with MLSD (abstract and Experimental results section); no pre-emphasis; FEC thresholds 2.4e-2 (SD-FEC, 20% overhead) and 3.8e-3 (HD-FEC, 6.7% overhead), which the XML mentions only in the Simulation results section. That the 200 Gb/s case is shown for MZM-1 in the main text and the other lanes in Supplementary Information was not re-checked against the raw XML | verified (XML) except the last sentence (summary) |
| Not found in the text read | BER definition and gross-or-net rate: a keyword search of the raw XML finds no occurrence of "gross", "net" or "overhead" and no formal BER definition; table heading "Single-lane bit rate x Fiber length x |Dispersion|"; optical power and drive swing per figure; link loss. A keyword search is weaker than reading every sentence, so these stay UNKNOWN rather than "absent". | verified (XML keyword search) |
| Missing | Source Data schema, figure-to-sheet mapping, actual launch power and swing, chirp parameters, laser and driver details | - |

## Source 4. Wiegart et al., JLT 39(2), 400-405 (2021) (Publication D, P0 mathematical check)

| Item | Value | Read as |
|---|---|---|
| Title | Probabilistically Shaped 4-PAM for Short-Reach IM/DD Links With a Peak Power Constraint | verified (Crossref JSON) |
| Authors (order) | Thomas Wiegart, Francesco Da Ros, Metodi Plamenov Yankov, Fabian Steiner, Simone Gaiarin, Richard D. Wesel | verified (Crossref JSON) |
| Journal | Journal of Lightwave Technology, vol. 39, issue 2, pp. 400-405, published 2021-01-15 | verified (Crossref JSON) |
| DOI / URL | `10.1109/JLT.2020.3029371`; resolves to https://ieeexplore.ieee.org/document/9216555/ (redirect read in the first pass; page empty to the tool) | verified for DOI (Crossref); URL summary |
| Author manuscript | `2005.12428v2.pdf` is in the repository root (ignored by `*.pdf`; SHA-256 `3a49c2f87a3a04b52892bc66c9f264f2dc432c354aedb9f8eb04650f1815d0ad`). `docs/engineering_log/LOG.md` (Phase 0) records a full read of it. E0 did not re-read it and does not take any technical field from it. Whether that arXiv ID is the author-accepted manuscript of the JLT paper is from the earlier log, not re-checked. | local file |
| Licence | **LICENSE/REUSE TERMS UNVERIFIED.** IEEE publisher copyright; Crossref lists only IEEE licence links (`vor` and `am` content versions point to the IEEE licence-information page, two `stm-asf` entries to IEEE policies; no open licence). arXiv licence of v2 not read. Digitised figures or re-plotted data from the figures are not cleared for public redistribution. | verified (Crossref JSON) |
| Technical fields (constraint, signal labeling, distribution family, AIR, noise definition, real vs simulated) | Not read in E0 (title only). Read in gate E3 from the author manuscript and recorded with locations in `configs/benchmarks/wiegart_2021_peak_pam4.yaml`; see `docs/benchmarks/E3_WIEGART_RAN.md`. Baud rate, fibre length and reference sequence stay null. | local file (E3) |

## Discrepancies between the brief/roadmap and what was read

| # | Brief or roadmap says | Read | Effect |
|---|---|---|---|
| 1 | "exact dataset version" implied to be one value | The first-pass summary reported "Revision 2" (JSON) against "v1" (HTML). The raw JSON shows that `revision` is a record counter (2 for Source 1, 4 for Source 2), and that `metadata.version` is absent and the DataCite `version` is `null`. No version label exists in the metadata; the "v1" came from the fetch tool, not from the record | not a discrepancy of the record: an artefact of the first-pass tool. The configs now say "revision counter 2; no version label in metadata" |
| 2 | Source 2: captures "sampled at 256 GSa/s" | record says "256 Gbaud" (same wrong unit as Source 1) | brief silently substituted the unit for Source 2; here both are INFERRED |
| 3 | "CW laser" (brief) | Source 1 states "a commercially available off-the-shelf (COTS) laser source"; neither "CW" nor "continuous" appears in the record | `transmitter_type` is "COTS laser source", as the record says. The first-pass config wrote "commercial CW laser" as PUBLISHED_MEASUREMENT, which the record does not support; corrected in the fix round |
| 4 | Source 2 detector ">70 GHz 3-dB electrical bandwidth" (brief) | the record gives the detector as having "more than 70 GHz 3-dB bandwidth"; only the word "electrical" is absent. The 50 GHz item is a digitally applied low-pass filter with a 3-dB cut-off, stated to improve signal-to-noise ratio | the first pass paraphrased both ("over 70 GHz", "50 GHz low-pass filter") and said "3-dB" was not seen; it is in the record. Keep the record's own short terms. Whether the 70 GHz refers to an electrical bandwidth stays unstated |
| 5 | Ran: "negative G.652-like dispersion example around -3.99 ps/(nm km)" | the paper gives -3.99 ps/(nm km) as the measured fibre dispersion at 1271 nm and names the fibre "G652.D" (printed without the dot after the G) | stronger than the brief: a measured value, labelled PUBLISHED_MEASUREMENT |
| 6 | Ran: "4 x 200 Gb/s over 10 km" | main text shows 200 Gb/s for MZM-1 only; other three lanes in Supplementary Information | only one lane is in the main text |
| 7 | Ran: "Article page advertises ... Source Data XLSX" | the nature.com page was not readable; the listing was confirmed on the Europe PMC copy | same fact, different source |
| 8 | Wiegart: "use publisher paper or author-accepted manuscript" | publisher page unreachable; repo holds arXiv v2 only | AAM status of arXiv v2 unconfirmed |
| 9 | Record "Files ... about 163.8 MB", MD5s | sizes (163,840,136 bytes) and all three MD5 match | no discrepancy |
| 10 | Ran title, journal, volume, article number, DOI, CC BY-NC-ND | match Crossref and Europe PMC | no discrepancy |
| 11 | Wiegart bibliographic data (authors, JLT 39(2), 400-405, DOI) | match Crossref | no discrepancy |
| 12 | v1/v2/v3 are time indices (Source 2) | JSON record states "Same operating parameters but at different time index" | matches the brief |
| 13 | Source 2 is "PAM4/NRZ" (brief, title) | the file list holds 17 PAM4 files and 0 NRZ files (Source 2); the NRZ files are in Source 1 (14 NRZ, 14 PAM4) | no NRZ capture exists in the EML record; do not plan an EML NRZ analysis |
| 14 | Source 1 file contents | the record says the data are "actually the samples extracted from the oscilloscope" | the files are scope output, with the scope's sampling and any scope-side processing unstated |

The record description names an NRZ and PAM-4 set; the brief's three target files exist under the
listed names. Nothing in the roadmap or brief about 1271 nm, FEC thresholds or the correction
note was contradicted.

## Rights summary (article and data kept apart; private use and public redistribution kept apart)

| Source | Part | Licence | Private research use | Public redistribution |
|---|---|---|---|---|
| 1 TERIPHIC PD | data | CC-BY-4.0 (RECORD_LEVEL, verified in raw JSON and DataCite) | allowed | allowed with attribution; a defensible rights review is still required before vendoring any capture (roadmap L0): captures stay in ignored `data/external/` |
| 2 TERIPHIC EML | data | CC-BY-4.0 (RECORD_LEVEL, verified in raw JSON) | allowed | as above |
| 3 Ran | article | CC BY-NC-ND 4.0 (RECORD_LEVEL) | allowed for non-commercial use | **no text or figure of the article enters this MIT repository**; only bibliographic strings and cited numeric facts (see "Licence conflict") |
| 3 Ran | source data XLSX | LICENSE/REUSE TERMS UNVERIFIED | unverified | not allowed until resolved; derived replicas not published |
| 4 Wiegart | article | LICENSE/REUSE TERMS UNVERIFIED | unverified | no figures, digitised or re-plotted points published; original equations and original curves only |

## Licence conflict: CC BY-NC-ND (Ran article) against the MIT repository

The Ran article is under CC BY-NC-ND 4.0. NC restricts commercial use, MIT grants it: anyone
who receives this repository may use everything in it commercially. A file that carries CC BY-NC-ND
material therefore cannot be placed in an MIT repository without breaking the licence of
that material, and the two licences are incompatible for that content. ND adds a second bar: the licence text in the Europe PMC XML denies permission to share adapted
material derived from the article or parts of it.

Rule for this repository, enforced by `LicenseRecord.commercial_use` and `derivatives` and by
`SourceRecord.require_public_redistribution` (which fails for the Ran article):

- Ran article material, figures even verbatim, and any adapted content stay out of the repository.
  That covers re-plotted figures, digitised points, redrawn tables and paraphrased passages that
  follow the article closely.
- Allowed: independently computed results from cleared numeric data, and facts stated as such with
  a citation (for example "the paper reports -3.99 ps/(nm km) at 1271 nm" with the DOI). The
  numbers in `configs/benchmarks/ran_2025_g652d.yaml` are such cited facts.
- What this repository carries from the Ran article is limited to bibliographic strings (title,
  authors, journal, DOI, identifiers), short numeric facts with a citation, the SPDX identifier of
  the licence, and descriptions in our own words. It carries no sentence of the article, and the
  licence statement itself is described, not quoted. `test_no_removed_article_sentence_remains`
  scans the committed text for word windows of the sentences that earlier versions of this
  register quoted; those sentences are still in Git history of this local branch until it is
  rewritten.
- Private research use under the NC terms (reading, comparing against our own numbers) is not
  restricted by this rule and stays outside the repository.
- The Source Data XLSX has its own, unread licence (`LICENSE/REUSE TERMS UNVERIFIED`); it is not
  assumed to follow the article.
- The earlier register text "verbatim only; no re-plotted or modified figures in the MIT repo"
  was narrower than the brief (no figures vendored) and left verbatim figures open; it is
  withdrawn.
