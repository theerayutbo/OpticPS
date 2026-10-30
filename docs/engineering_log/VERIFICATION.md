# External fact verification

Status values: verified = read in the primary source; summary = read through a search or fetch summary; user-supplied = stated by the user, source not read; reconstructed = recovered from a garbled extraction and checked by another route; unconfirmed = not yet known.

| Fact | Source | How read | Status |
|---|---|---|---|
| Continuous sample rate 200 to 256 GSa/s | M8199B data sheet asset page | WebFetch summary | summary |
| 1 MSa waveform memory per channel | M8199B data sheet asset page | WebFetch summary | summary |
| 8-bit DAC | M8199B product page | WebSearch summary | summary |
| Up to 2 Vpp differential at 160 GBaud | M8199B data sheet asset page | WebFetch summary | summary |
| Nominal 3 dB bandwidth 75 GHz incl. sinc roll-off | M8100 Getting Started Guide | Text extraction | verified |
| Data outputs: 1.0 mm, Data Out and complement | Getting Started Guide, Table 18 | Text extraction | verified |
| Controlled by M8070B version 9.5 and above | Getting Started Guide | Text extraction | verified |
| Works with M8008A clock module, quarter-rate Clk In | Getting Started Guide | Text extraction | verified |
| ESD caution; toggling sample rate mitigates alignment issues | Getting Started Guide | Text extraction | verified |
| Unused output disabled in M8070B or terminated with 50 ohm | Getting Started Guide (M8100 series section) | Text extraction | verified |
| CSV header `DataOut1`, one column, range ±1 | M8100 Programming Guide, per user | Not read | user-supplied |
| Sample count multiple of 512 | M8100 Programming Guide, per user | Not read | user-supplied |
| Max 1,048,576 samples | M8100 Programming Guide, per user | Not read | user-supplied |
| `:TRAC:IMP 'M2.DataOut1', 1, "path", CSV` | M8100 Programming Guide, per user | Not read | user-supplied |
| AC-coupled, nominally 50 ohm output | User | Not read | user-supplied |

| G.652.D attenuation, dispersion, PMD, fibre and cable attributes (Table 2); Note 1 (not for short cables), Note 2 (1260 nm extension, +0.07 dB/km) | Rec. ITU-T G.652 (08/2024), edition 10.0 | Text extraction, read | verified |
| Dispersion bounds Eq. (6-3), 8.625 + 0.052(lambda - 1460) to 12.472 + 0.068(lambda - 1460) | Rec. ITU-T G.652 (08/2024) | Text extraction, read | verified |
| Dispersion bounds Eq. (6-2a,b,c), 1260 to 1460 nm | Rec. ITU-T G.652 (08/2024) | Garbled extraction; signs reconstructed, confirmed by continuity with Eq. (6-3) at 1460 nm | reconstructed |
| Table I.1 typical link values: 0.5 dB/km (1260 to 1360 nm), 0.275 (1530 to 1565), 0.35 (1565 to 1625), D1550 17, S1550 0.056 | Rec. ITU-T G.652 (08/2024) | Text extraction, read | verified |
| Southampton fiber type and length | Project owner | Not stated | unconfirmed |

Hardware playback: NOT verified. Requires confirmation from the Southampton operator.

Wiegart et al. figures: read directly from the supplied arXiv PDF.
