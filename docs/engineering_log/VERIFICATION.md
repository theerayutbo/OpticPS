# External fact verification

Status values: verified = read in the primary source; summary = read through a search or fetch summary; user-supplied = stated by the user, source not read.

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
| CSV header `DataOut1`, one column, range ±1 | M8100 Programming Guide pp129-133 | Text extraction | verified (1 to 7 columns allowed; mandatory header row; normalized floats -1.0 to +1.0) |
| Sample count multiple of 512 | Not found in the M8100 Programming Guide | Text extraction | user-supplied, kept as a safe rule |
| Max 1,048,576 samples | Not found in the M8100 Programming Guide | Text extraction | user-supplied |
| `:TRACe:IMPort 'identifier', <segment_id>, <file_name>, <file_format>` | M8100 Programming Guide pp129-130 | Text extraction | verified (BIN8, TXT, CSV; segment id 1 only; M8199A and M8199B) |
| AC-coupled, nominally 50 ohm output | User; `:OUTPut:COUPling` lists M8198A and M8199A only (p97) | Text extraction | user-supplied, not confirmed for M8199B |
| Min/max query `:SOURce:VOLTage:AMPLitude? 'identifier', <MIN/MAX>` | M8100 Programming Guide p57 | Text extraction | verified syntax; identifier form in the example is 'M2.DataOut' |
| `:DISK:SAVE:WAVeform <source>,"<file_name>"[,<format>[,<header>]]`, formats BIN CSV INTernal TSV TXT H5 H5INt MATlab | UXR Programmer's Guide p598 | Text extraction | verified |
| H5 stores floats (actual vertical values); H5INt stores integers (value * Y increment + Y origin) | UXR Programmer's Guide p598 | Text extraction | verified |
| HDF5 example, NumSegments = 0 for a normal capture | UXR Programmer's Guide p2090 | Text extraction | verified |
| CSV/TSV header fields Revision to Data | UXR Programmer's Guide pp2091-2092 | Text extraction | verified field list; separator and spelling in a real file unverified |
| BIN layout: cookie AG, version 10, 4-byte signed ints, 12/140/12-byte headers, units 0 to 6 | UXR Programmer's Guide pp2093-2098 (C structs, pack(4)) | Text extraction | verified against the guide; no real file tested |
| UXR model suffix, bandwidth, memory | None | Not available | unconfirmed; not stated anywhere |

Hardware playback: NOT verified. Requires confirmation from the Southampton operator.

Wiegart et al. figures: read directly from the supplied arXiv PDF.
