# Hardware compatibility

Transmitter: Keysight M8199B, confirmed by the project owner. Receiver: unknown. **Hardware playback has not been verified.**

| Item | Value used | Status |
|---|---|---|
| Sample rate | 200 to 256 GSa/s | Keysight data sheet page, through a fetch summary |
| Waveform memory | 1 MSa per channel; 1,048,576 enforced | Summary; exact figure per owner's notes |
| DAC | 8 bit | Keysight product page, through a search summary |
| Connectors | 1.0 mm, differential Data Out | Getting Started Guide, read |
| Software | M8070B 9.5 or later plus driver | Getting Started Guide, read |
| CSV first row `DataOut1` | Enforced | Owner's notes; Programming Guide not read |
| Range -1 to +1 | Enforced | Owner's notes; not read |
| Multiple of 512 samples | Enforced | Owner's notes; not read |
| `:TRAC:IMP` command | Documented, never sent | Owner's notes; not read |
| AC-coupled, 50 ohm | Documented | Owner's notes; not read |

To close: obtain M8100 Series Programming Guide M8100-91B50 and check each "not read" row. See `docs/engineering_log/VERIFICATION.md`.

DAC code mapping is unverified. `dac_quantize` in `src/opticps/transmitter/export.py` is a simulation assumption.

Options that could change the valid sample rate or memory are unknown until the Southampton unit's configuration is confirmed.

The code holds no live driver. `MockM8199BAdapter` is the only adapter, and it requires explicit confirmation even for a simulated output enable.
