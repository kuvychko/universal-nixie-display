# Host interface

SCPI-style ASCII commands over the display board's USB serial port, following the
nanovolt-divider's approach. Full SCPI and USBTMC are out of scope for Rev A.
**Draft — spellings are proposals (plan §6).**

## Framing

_Open:_ baud rate, line terminator, maximum line length, response timeout, number formatting,
behaviour on host open (the CH340 resets the ESP32 on open in the divider; verify on this board).
The boot counter and uptime are queryable so a host can detect reboots and restore its display.

## Commands

| Command | Intent |
|---|---|
| `*IDN?` | Instrument identity and firmware version |
| `SYST:ERR?` | Retrieve queued error |
| `DISP:MODE PRESET` / `DISP:MODE REMOTE` | Explicit ownership of the display |
| `DISP:VALUE 12.3456` | Format a numeric value into available digits |
| `DISP:TEXT "FREQUENCY"` | TFT label |
| `DISP:UNIT "Hz"` | TFT units |
| `NIX:RAW "012345"` | Exact digits, including leading zeroes |
| `DEK:HOME` / `DEK:HOME?` | Request homing / query status |
| `DEK:POS 4` | Move to a main-cathode position |
| `DEK:ROT 2` | Rotate at a specified rate; units fixed by protocol |

## Display rules

* Signs and engineering units go on the TFT; IN-14 has no minus sign.
* Overflow is an error, never silently wrapped.
* Stale remote data is marked on the TFT; hold-vs-blank behaviour: _open_.
