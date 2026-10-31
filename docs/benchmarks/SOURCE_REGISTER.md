# Benchmark source register (Stage 3A, gate E0)

Retrieval date of all metadata below: 2026-10-31. Repository state: branch `v1.3-mpam`, base HEAD
`8129eca` (E0 commits on top). Nothing was downloaded: no dataset file, no source-data XLSX, no PDF
asset. Clean room kept: no optical-simulator source, notebook, package or code-containing page was
opened; no code link on any page was followed.

## How facts were read (status vocabulary of `docs/engineering_log/VERIFICATION.md`)

| Label | Meaning here |
|---|---|
| verified | read in the primary source by us. **No fact below has this status**: the fetch tool returns a model-written summary of a page, never the raw page, so the strongest status reachable in E0 is `summary`. |
| summary | read through the WebFetch tool on the primary page or the Zenodo JSON record (summary-level; where two independent fetches agree this is said) |
| user-supplied | stated in the owner's brief or roadmap, source not read (`brief` below) |
| unconfirmed | not read; unknown |

Pages that could not be read: `nature.com` article page (cookie-handshake redirect loop, not
worked around), `pmc.ncbi.nlm.nih.gov` (reCAPTCHA page), `ieeexplore.ieee.org` (empty).
Bibliographic data for these came from Crossref and the Europe PMC copy of the full text
(`PMC12234763`), both summary status.

## Source 1. TERIPHIC photodiode arrays (Dataset A, P0)

| Item | Value | Read as |
|---|---|---|
| Title | Experimental characterization of TERIPHIC 4-fold and 8-fold InP photodiode arrays - Detection of 50Gbaud signals with NRZ and PAM-4 modulation formats | summary (JSON record and HTML page agree) |
| Creators | Panos Groumas, Efstathios Andrianopoulos, Christos Tsokos (ICCS). Contributors: David De Felipe, Norbert Keil, Patrick Runge (Fraunhofer HHI); Paraskevas Bakopoulos (NVIDIA) | summary (JSON) |
| DOI / URL | `10.5281/zenodo.7886498`; https://zenodo.org/records/7886498; concept DOI `10.5281/zenodo.7886497` | summary |
| Dataset version | JSON: "Revision 2" (latest version of concept 7886497). HTML page: "Version v1". Published 2023-05-02, modified 2023-05-03 (HTML). **Two version labels disagree; the exact version is UNCONFIRMED.** Re-read before any download. | summary |
| Funding | EC H2020 TERIPHIC, GA 825502 | summary |
| Files | 28 (14 NRZ, 14 PAM4), 4.6 GB total, every file 163,840,136 bytes (JSON) / "163.8 MB" (HTML) | summary |
| Target MD5 (supplied by the record) | B2B `d7bd6d48bc020a138f4f129bc2ba7312`; 2 km `d9e3c533394c53c3575491558ffc35b1`; 10 km `3d8774b068deaf50f37892b38953dfd6` (PD1, Subassembly 1, PAM4). JSON and HTML lists agree for all 28 files. | summary, two fetches agree |
| Local SHA-256 / MD5 verified | **none computed.** MD5 state is `supplied`, not `verified`. | - |
| Data licence | CC-BY-4.0, record-level, Access "Open" (JSON); HTML page "CC BY 4.0". No separate licence file or terms for individual files inspected. Private research use: allowed. Public redistribution of derived data: allowed with attribution, subject to the record-level reading above. | summary |
| Article licence | none: the record is a dataset; no associated article was identified. `LICENSE/REUSE TERMS UNVERIFIED` for any article | unconfirmed |
| Description wording | O-band; commercial (COTS) laser source and COTS Mach-Zehnder modulator, models not named; NRZ and PAM-4 at 50 Gbaud; two subassemblies (4 and 8 InP photodiodes); "The generated photocurrents were sampled by a real-time oscilloscope with a 256 Gbaud sample rate"; lengths B2B, 2 km, 10 km | summary |
| Instrument parameters stated | symbol rate 50 GBd; sampling "256 Gbaud sample rate" (unit wording wrong; read by us as 256 GSa/s, label INFERRED, nominal 5.12 samples/symbol). Not stated: oscilloscope model, bandwidth, ENOB, vertical scale, laser wavelength or power, modulator model or Vpi, fibre type, launch power, PRBS or pattern, pulse shaping, DAC/AWG | summary |
| Data fields | File name template per record: `Symbol rate#Modulation formats#PDn#Transmission length#version#Subassemblyn.bin`. Actual PD-array names have no `version` token, and PAM4 files for PD4 to PD8 (Subassembly 2) carry no length token. No description of file contents: no dtype, header, endianness, scaling, units, channel count or sample count | summary |
| Sizes | 163,840,136 bytes each = 163,840,000 + 136 (arithmetic on the listed size only; a 136-byte constant is a hypothesis for E1, not a finding) | summary + arithmetic |
| Missing | raw format, reference bit/symbol sequence, wavelength, fibre type and dispersion, vertical calibration, device responses, oscilloscope settings, acquisition timestamps | - |

### Local state found (not created by E0)

`data/external/teriphic/` (ignored by Git; `.gitignore` rule added in E0) contained, while this
register was written, `50G_PAM4_PD1_B2B_Subassembly1.bin` at 163,840,136 bytes (equals the listed size)
and `50G_PAM4_PD1_2km_Subassembly1.bin` growing from 18,718,720 bytes, written by a `curl`
process (PID 2517, started 16:28 local, from the Zenodo files URL) that is not part of E0. E0 did not
start, stop, open, hash or read either file. They are not "downloaded and verified"; their MD5 is
unchecked and the 2 km file is incomplete until that process ends. The brief and the owner's
instruction forbid downloads in this gate: whoever started the transfer should confirm
authorisation for 3 x 163.8 MB.

## Source 2. TERIPHIC quad InP EML array (Dataset B, P1, out of MZM model domain)

| Item | Value | Read as |
|---|---|---|
| Title | Experimental characterization of TERIPHIC quad InP EML array - Generation and transmission of 50Gbaud signals with NRZ and PAM-4 modulation formats (JSON title paraphrased by the tool; exact title wording UNCONFIRMED) | summary (JSON only) |
| Creators | Groumas, Andrianopoulos, Tsokos (ICCS). Contributors: De Felipe, Troppenz, Keil, Moehrle (HHI), Bakopoulos (NVIDIA) | summary |
| DOI / URL | `10.5281/zenodo.7886228`; https://zenodo.org/records/7886228; concept DOI `10.5281/zenodo.7886227` | summary |
| Version | "Record revision 4"; published 2023-05-02, modified 2023-05-03. HTML page not fetched. | summary |
| Licence | CC-BY-4.0, Open (JSON). Same caveats as Source 1. | summary |
| Files | 17 PAM4 `.bin`: 16 of 40,960,136 bytes and `50G_PAM4_EML2_B2B_v1.bin` of 163,840,136 bytes (MD5 `ae7df638705bd83a0d369b2b86e93f00`). Full MD5 list is in the JSON record; not copied here. | summary |
| Description | quad EML (each DFB + EAM + SOA); three of four EMLs used (EML2, EML3, EML4 appear in names); 0 km, 2 km, 10 km; single commercial photodetector "over 70 GHz bandwidth" (whether this is 3 dB electrical is not stated in what was read); oscilloscope "256 Gbaud" sampling; digital 50 GHz low-pass filter applied "to improve SNR"; `v1`, `v2`, `v3` in names are repeated runs with the same operating parameters at different time indices | summary |
| Local hashes | none | - |
| Missing | same list as Source 1, plus EML bias and drive, filter details, whether the shipped samples are filtered | - |

## Source 3. Ran et al., Nature Communications 16, 6268 (2025) (Publication C, P1)

| Item | Value | Read as |
|---|---|---|
| Title | A 4x256 Gbps silicon transmitter with on-chip adaptive dispersion compensation | summary (Crossref and Europe PMC agree) |
| Authors | Shihuan Ran, Yu Guo, Yuanbin Liu, Ting Miao, Yangbo Wu, Yang Qin, Yuyao Guo, Liangjun Lu, Yixiao Zhu, Yu Li, Qunbi Zhuge, Jianping Chen, Linjie Zhou (corresponding: Yu Li, Qunbi Zhuge) | summary |
| Journal | Nature Communications, volume 16, article number 6268, published 2025-07-07; received 2024-11-08, accepted 2025-06-18 | summary |
| DOI / URL | `10.1038/s41467-025-61408-7`; https://www.nature.com/articles/s41467-025-61408-7; PMC12234763; PMID 40624056 | summary |
| Correction | change-history note (dated "8/11/2025", format ambiguous): symbols of Eq. (6) were amended in HTML and PDF. Equations must be read from the corrected version. | summary |
| Article licence | CC BY-NC-ND 4.0 (Crossref and Europe PMC), (c) The Author(s) 2025. Attribution, non-commercial, no derivatives: figures may be shared verbatim, **modified or re-plotted figures are not covered**. | summary |
| Source Data | Supplementary list: Supplementary information (MOESM1 PDF), Peer Review file (MOESM2 PDF), Source data `41467_2025_61408_MOESM3_ESM.xlsx`. Data availability text: "[article text removed: CC BY-NC-ND]." Code: upon request. | summary |
| **Source-data licence** | **LICENSE/REUSE TERMS UNVERIFIED.** No licence for the XLSX appears in the text read. Do not assume it follows the article licence. File not fetched; size, hash, sheet names and columns unknown. | unconfirmed |
| Instrument and link parameters | wavelength 1271 nm; measured fibre dispersion -3.99 ps/(nm km) at 1271 nm; standard single-mode fibre named G.652.D in captions and text; PAM-4; 4 x 256 Gb/s over 5 km, 4 x 200 Gb/s over 10 km (the 200 Gb/s case is shown for MZM-1 in the main text, the other three in Supplementary Information); 155-tap FFE, RLS update, optionally with MLSD; no transmit pre-emphasis; FEC thresholds quoted 2.4e-2 (20 % SD-FEC) and 3.8e-3 (6.7 % HD-FEC) | summary |
| Not found in the text read | BER definition; whether 256 and 200 Gb/s are gross or net (table heading "Single-lane bit rate x Fiber length x |Dispersion|"); optical power and drive swing per figure; link loss. The last 12,873 characters of the full text were read only for data, code and licence statements. | summary |
| Missing | Source Data schema, figure-to-sheet mapping, actual launch power and swing, chirp parameters, laser and driver details | - |

## Source 4. Wiegart et al., JLT 39(2), 400-405 (2021) (Publication D, P0 mathematical check)

| Item | Value | Read as |
|---|---|---|
| Title | Probabilistically Shaped 4-PAM for Short-Reach IM/DD Links With a Peak Power Constraint | summary (Crossref) |
| Authors (order) | Thomas Wiegart, Francesco Da Ros, Metodi Plamenov Yankov, Fabian Steiner, Simone Gaiarin, Richard D. Wesel | summary (Crossref) |
| Journal | Journal of Lightwave Technology, vol. 39, issue 2, pp. 400-405, published 2021-01-15 | summary (Crossref) |
| DOI / URL | `10.1109/JLT.2020.3029371`; resolves to https://ieeexplore.ieee.org/document/9216555/ (redirect read; page empty to the tool) | summary |
| Author manuscript | `2005.12428v2.pdf` is in the repository root (ignored by `*.pdf`; SHA-256 `3a49c2f87a3a04b52892bc66c9f264f2dc432c354aedb9f8eb04650f1815d0ad`). `docs/engineering_log/LOG.md` (Phase 0) records a full read of it. E0 did not re-read it and does not take any technical field from it. Whether that arXiv ID is the author-accepted manuscript of the JLT paper is from the earlier log, not re-checked. | local file |
| Licence | **LICENSE/REUSE TERMS UNVERIFIED.** IEEE publisher copyright; Crossref lists only IEEE licence links (VoR and author manuscript, no open licence). arXiv licence of v2 not read. Digitised figures or re-plotted data from the figures are not cleared for public redistribution. | summary |
| Technical fields (constraint, signal labeling, distribution family, AIR, noise definition, real vs simulated) | Not read in E0. Title states 4-PAM and a peak power constraint. All others `null`/UNKNOWN in the config. To be read in E3. | - |

## Discrepancies between the brief/roadmap and what was read

| # | Brief or roadmap says | Read | Effect |
|---|---|---|---|
| 1 | "exact dataset version" implied to be one value | Zenodo JSON says Revision 2; HTML page says v1 (Source 1). Source 2: revision 4 | version unconfirmed; recorded both |
| 2 | Source 2: captures "sampled at 256 GSa/s" | record says "256 Gbaud" (same wrong unit as Source 1) | brief silently substituted the unit for Source 2; here both are INFERRED |
| 3 | "CW laser" | record text read says "commercially available off-the-shelf laser source"; "CW" not seen | not recorded as stated; `transmitter_type` omits CW |
| 4 | Source 2 detector ">70 GHz 3-dB electrical bandwidth" | read: "over 70 GHz bandwidth"; "3-dB electrical" not seen | wording not confirmed |
| 5 | Ran: "negative G.652-like dispersion example around -3.99 ps/(nm km)" | the paper gives -3.99 ps/(nm km) as the measured fibre dispersion at 1271 nm, and names the fibre G.652.D | stronger than the brief: a measured value, labelled PUBLISHED_MEASUREMENT |
| 6 | Ran: "4 x 200 Gb/s over 10 km" | main text shows 200 Gb/s for MZM-1 only; other three lanes in Supplementary Information | only one lane is in the main text |
| 7 | Ran: "Article page advertises ... Source Data XLSX" | the nature.com page was not readable; the listing was confirmed on the Europe PMC copy | same fact, different source |
| 8 | Wiegart: "use publisher paper or author-accepted manuscript" | publisher page unreachable; repo holds arXiv v2 only | AAM status of arXiv v2 unconfirmed |
| 9 | Record "Files ... about 163.8 MB", MD5s | sizes (163,840,136 bytes) and all three MD5 match | no discrepancy |
| 10 | Ran title, journal, volume, article number, DOI, CC BY-NC-ND | match Crossref and Europe PMC | no discrepancy |
| 11 | Wiegart bibliographic data (authors, JLT 39(2), 400-405, DOI) | match Crossref | no discrepancy |
| 12 | v1/v2/v3 are time indices (Source 2) | JSON record states repeated runs with the same operating parameters at different time indices | matches the brief |

The record description names an NRZ and PAM-4 set; the brief's three target files exist under the
listed names. Nothing in the roadmap or brief about 1271 nm, FEC thresholds or the correction
note was contradicted.

## Rights summary (article and data kept apart; private use and public redistribution kept apart)

| Source | Part | Licence | Private research use | Public redistribution |
|---|---|---|---|---|
| 1 TERIPHIC PD | data | CC-BY-4.0 (record-level, summary) | allowed | allowed with attribution; a defensible rights review is still required before vendoring any capture (roadmap L0): captures stay in ignored `data/external/` |
| 2 TERIPHIC EML | data | CC-BY-4.0 (record-level, summary) | allowed | as above |
| 3 Ran | article | CC BY-NC-ND 4.0 | allowed | verbatim only; no re-plotted or modified figures in the MIT repo |
| 3 Ran | source data XLSX | LICENSE/REUSE TERMS UNVERIFIED | unverified | not allowed until resolved; derived replicas not published |
| 4 Wiegart | article | LICENSE/REUSE TERMS UNVERIFIED | unverified | no figures, digitised or re-plotted points published; original equations and original curves only |
