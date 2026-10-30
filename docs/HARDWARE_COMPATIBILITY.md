# Hardware compatibility

Transmitter: Keysight M8199B, confirmed by the project owner. Receiver: a Keysight Infiniium UXR Series oscilloscope sampling at 256 GSa/s; the exact model suffix is unconfirmed. **Hardware playback has not been verified.**

## Transmitter (M8199B)

Statuses use the M8100 Series Programming Guide (M8100-91B50, March 2026), read as extracted text, page numbers are the guide's.

| Item | Value used | Status |
|---|---|---|
| Sample rate | 200 to 256 GSa/s | Keysight data sheet page, through a fetch summary |
| Waveform memory | 1 MSa per channel; 1,048,576 enforced | Summary; exact figure per owner's notes. Not found in the Programming Guide |
| DAC | 8 bit | Keysight product page, through a search summary |
| Connectors | 1.0 mm, differential Data Out | Getting Started Guide, read |
| Software | M8070B 9.5 or later plus driver | Getting Started Guide, read |
| CSV first row `DataOut1` | Enforced | **Confirmed**, Programming Guide pp129-133: the first row is a mandatory header whose names are combinations of DataOut1 to DataOut4, SyncMrkA, SyncMrkB, SampleMrk; a file has 1 to 7 columns |
| Range -1 to +1 | Enforced | **Confirmed**, pp131 and 133: normalized floats -1.0 to +1.0; scientific notation accepted |
| `:TRAC:IMP` command | Documented, never sent | **Confirmed**, p129-130: `:TRACe:IMPort 'identifier', <segment_id>, <file_name>, <file_format>`; formats BIN8, TXT, CSV; only segment id 1 is supported; applies to M8199A and M8199B |
| Multiple of 512 samples | Enforced | Not found in the Programming Guide (the granularity query on p125 applies to M8198A only). Remains from the owner's notes; kept as a safe rule |
| Maximum 1,048,576 samples | Enforced | Not found in the guide. Remains from the owner's notes |
| AC-coupled, 50 ohm | Documented | Not confirmed. `:OUTPut:COUPling` lists M8198A and M8199A only (p97). Remains from the owner's notes |

Operator check for output limits (guide p57): `:SOURce:VOLTage:AMPLitude? 'identifier', MAX` returns the maximum, and `MIN` the minimum. The guide's own example uses the identifier `'M2.DataOut'`; its command pages write `'M1.DataOut1'` (p37), where M1 or M2 is the module slot. Check which identifier your unit accepts, and read the limits before loading any waveform. OpticPS sends no SCPI.

## Receiver (Keysight Infiniium UXR Series)

| Item | Value used | Status |
|---|---|---|
| Model | UXR Series, exact suffix unconfirmed | Project owner; record what the instrument reports (`*IDN?`, UXR Programmer's Guide p263) |
| Sample rate | 256 GSa/s | Project owner. The file's own increment is always used for analysis |
| Export formats | HDF5, CSV, BIN | `:DISK:SAVE:WAVeform` formats BIN, CSV, INTernal, TSV, TXT, H5, H5INt, MATlab (UXR Programmer's Guide p598). H5 holds floats that are actual vertical values; H5INt holds integers needing the Y increment and Y origin |
| HDF5, CSV and BIN file layouts | As documented | UXR Programmer's Guide pp2090-2098 (HDF5 example, CSV/TSV header, BIN header and C structs). Importers are tested on synthetic files only; no real export has been seen |

No bandwidth or memory figure is stated here: none has been confirmed for the unit at Southampton.

At 256 GSa/s, Profile A (8 GBaud) gives 32 samples per symbol and Profile B (56 GBaud) gives 4.57.

DAC code mapping is unverified. `dac_quantize` in `src/opticps/transmitter/export.py` is a simulation assumption.

Options that could change the valid sample rate or memory are unknown until the Southampton unit's configuration is confirmed.

The code holds no live driver. `MockM8199BAdapter` is the only adapter, and it requires explicit confirmation even for a simulated output enable.
