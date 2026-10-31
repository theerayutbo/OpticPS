# External fact verification

Status values: verified = read in the primary source; summary = read through a search or fetch summary; user-supplied = stated by the user, source not read; reconstructed = recovered from a garbled extraction and checked by another route; unconfirmed = not yet known.

| Fact | Source | How read | Status |
|---|---|---|---|
| Sample rate 200 to 256 GSa/s | M8199B data sheet, p9, read directly | Text extraction | verified |
| 1024 kSa waveform memory per channel | M8199B data sheet, p9, read directly | Text extraction | verified; decimal or binary k not stated |
| 8-bit DAC | M8199B data sheet, p9, read directly | Text extraction | verified |
| Up to 2 Vpp differential at 160 GBaud | M8199B data sheet asset page | WebFetch summary | summary |
| Nominal 3 dB bandwidth 75 GHz incl. sinc roll-off | M8100 Getting Started Guide | Text extraction | verified |
| Data outputs: 1.0 mm, Data Out and complement | Getting Started Guide, Table 18 | Text extraction | verified |
| Controlled by M8070B version 9.5 and above | Getting Started Guide | Text extraction | verified |
| Works with M8008A clock module, quarter-rate Clk In | Getting Started Guide | Text extraction | verified |
| ESD caution; toggling sample rate mitigates alignment issues | Getting Started Guide | Text extraction | verified |
| Unused output disabled in M8070B or terminated with 50 ohm | Getting Started Guide (M8100 series section) | Text extraction | verified |
| CSV header `DataOut1`, one column, range ±1 | M8100 Programming Guide pp129-133 | Text extraction | verified (1 to 7 columns allowed; mandatory header row; normalized floats -1.0 to +1.0) |
| Sample count multiple of 512 | M8199B data sheet, p9, read directly; absent from the Programming Guide | Text extraction | verified |
| Max 1,048,576 samples | M8199B data sheet, p9, read directly, as 1024 kSa | Text extraction | verified if k is 1024 |
| `:TRACe:IMPort 'identifier', <segment_id>, <file_name>, <file_format>` | M8100 Programming Guide pp129-130 | Text extraction | verified (BIN8, TXT, CSV; segment id 1 only; M8199A and M8199B) |
| AC-coupled, 50 ohm nominal | M8199B data sheet, p9, read directly | Text extraction | verified |
| Min/max query `:SOURce:VOLTage:AMPLitude? 'identifier', <MIN/MAX>` | M8100 Programming Guide p57 | Text extraction | verified syntax; identifier form in the example is 'M2.DataOut' |
| `:DISK:SAVE:WAVeform <source>,"<file_name>"[,<format>[,<header>]]`, formats BIN CSV INTernal TSV TXT H5 H5INt MATlab | UXR Programmer's Guide p598 | Text extraction | verified |
| H5 stores floats (actual vertical values); H5INt stores integers (value * Y increment + Y origin) | UXR Programmer's Guide p598 | Text extraction | verified |
| HDF5 example, NumSegments = 0 for a normal capture | UXR Programmer's Guide p2090 | Text extraction | verified |
| CSV/TSV header fields Revision to Data | UXR Programmer's Guide pp2091-2092 | Text extraction | verified field list; separator and spelling in a real file unverified |
| BIN layout: cookie AG, version 10, 4-byte signed ints, 12/140/12-byte headers, units 0 to 6 | UXR Programmer's Guide pp2093-2098 (C structs, pack(4)) | Text extraction | verified against the guide; no real file tested |
| UXR model suffix, bandwidth, memory | None | Not available | unconfirmed; not stated anywhere |
| G.652.D attenuation, dispersion, PMD, fibre and cable attributes (Table 2); Note 1 (not for short cables), Note 2 (1260 nm extension, +0.07 dB/km) | Rec. ITU-T G.652 (08/2024), edition 10.0 | Text extraction, read | verified |
| Dispersion bounds Eq. (6-3), 8.625 + 0.052(lambda - 1460) to 12.472 + 0.068(lambda - 1460) | Rec. ITU-T G.652 (08/2024) | Text extraction, read | verified |
| Dispersion bounds Eq. (6-2a,b,c), 1260 to 1460 nm | Rec. ITU-T G.652 (08/2024) | Garbled extraction; signs reconstructed, confirmed by continuity with Eq. (6-3) at 1460 nm | reconstructed |
| Table I.1 typical link values: 0.5 dB/km (1260 to 1360 nm), 0.275 (1530 to 1565), 0.35 (1565 to 1625), D1550 17, S1550 0.056 | Rec. ITU-T G.652 (08/2024) | Text extraction, read | verified |
| Status of Rec. ITU-T G.652 (08/2024) as in force | ITU-T recommendation page (https://www.itu.int/rec/T-REC-G.652), read 2026-10-30 | Web page, not the PDF | verified (page) |
| Table I.1 is a link value; why 0.5 dB/km at 1310 nm exceeds the 0.40 dB/km cable limit | Rec. ITU-T G.652 (08/2024), Appendix I (link attenuation is affected by splices, passive components, installation) | The reason is an inference, not stated | inference |
| Southampton fiber type and length | Project owner | Not stated | unconfirmed |

Hardware playback: NOT verified. Requires confirmation from the Southampton operator.

Wiegart et al. figures: read directly from the supplied arXiv PDF.
