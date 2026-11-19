# Nixie bring-up firmware

Gate 2-6 tool for the Nixie board ([assembly checklist](../../hardware/nixie/assembly.md)):
switches the HV module's 12 V (`NIX12_EN`, GP0) on purpose, shifts and reads back HV5622 frames,
lights tubes, drives `DRV_BL` and probes the ES100. It is **not** the Nixie controller firmware
(that goes in `firmware/nixie/`).

> [!WARNING]
> High voltage (~175 V). Read the [README safety section](../../README.md#safety-read-this-first).
> The firmware cut-off is not a hardware guarantee; the HV module's glued trimmer is the first
> protection ([hardware.md](../../docs/hardware.md#nixie-board-electrical-design-phase-1a-draft-2026-10-26), HV limit).

## Safety behaviour

* `NIX12_EN` and `DRV_BL` are driven low first thing at boot; the HV module never gets 12 V
  without an `on` command.
* Every `on` has an auto-off timeout: 10 s by default, 3600 s at most (the Gate 5b warm-up run).
  `on` while on restarts the timer.
* **HV cut-off:** `NIX_HV_SENSE` is read on every loop pass. Above the threshold (200 V at every
  reset; user, 2026-11-06), `NIX12_EN` drops, `BL` goes low and the fault **latches** until
  `clear`. It runs whether `NIX12_EN` is on or off. `trip <V>` lowers the threshold for the Gate 4
  test (20-200 V; it cannot be raised above 200 V), so no separate test build is needed.
* **Switched 12 V:** from 200 ms after `on` (the soft start takes 34-57 ms plus a 5.5-7.3 ms ramp
  in simulation), `NIX12_SENSE` below 10.8 V latches `sw12_low`.
* **Tubes dark until the chain is confirmed:** at boot a test pattern is shifted, then a blank
  frame is shifted and latched; its readback on GP12 must return the pattern. Until it does
  (`chain=0`, e.g. with the 12 V logic rail absent) `bl` refuses anything but 0. Every later
  frame is checked the same way against the frame before it; a mismatch blanks the tubes, stops
  `cycle` and locks `BL` until `blank` passes again.
* The hardware watchdog (500 ms) resets the RP2040 if the loop hangs; the reset pull-downs then
  hold the 12 V switch off and `BL` low.
* The module LED glows dim red while `NIX12_EN` is high.

`NIX_HV_SENSE` (ratio 84.3) and `NIX12_SENSE` (ratio 9.33) use the 3.3 V rail as ADC reference:
indicative only; the meter and HV probe are the reference.

## Driver chain

U201 → U202 → U203, 96 bits, bit-banged at 250 kHz (2 µs half period; ≤ 1 MHz through U302).
`DATA` changes with the rising `CLK` edge and the HV5622 samples it on the falling one; `LE` idles
low and is pulsed once per frame. Frames are written as three 32-bit words, U201 first, bit n−1 =
HVOUTn. The first bit sent ends at U203 HVOUT32 (HV5622 data sheet, Table 3-2). `DATA OUT` is
read just before each falling edge, so each frame shifted returns the one before it.

Tube elements use `HV_MAP` ([hardware.md](../../docs/hardware.md#nixie-board-electrical-design-phase-1a-draft-2026-10-26),
from `tools/gen_nixie_schematics.py`): tube 1 is the left tube of U201's pair.

## Build and flash

```
pio run -d firmware/nixie-bringup
```

Hold BOOT on the RP2040-Zero while plugging USB, then
`pio run -d firmware/nixie-bringup -t upload` (or copy `.pio/build/rp2040zero/firmware.uf2` to
the RPI-RP2 drive).

## Commands

USB serial, 115200, one line per command; replies start with `OK` or `ERR`, faults with `FAULT`.

| Command | Does |
|---|---|
| `on [s]` | `NIX12_EN` high for s seconds (default 10, max 3600) |
| `off` (or an empty line) | `NIX12_EN` low; stops `cycle` |
| `status` | `t_ms hv peak sw12 nix12_en fault left trip chain bl pwm_hz frame enc_a enc_b enc_sw wwvb_en wwvb_irq spare`; `peak` is the highest HV since the last `on` |
| `clear` | Clear a latched fault and the peak |
| `trip [V]` | Show, or lower, the HV cut-off threshold (20-200 V; 200 V again at reset) |
| `blank` | Pattern, then blank frame latched, with the readback check; `OK blank chain=1` or `ERR chain …` |
| `chain` | Readback test without changing the outputs: all 0, all 1, 0xAA…, 0x55…, walking 1 and walking 0 over all 96 bits (197 shifts); `OK chain tests= fails=` |
| `bl <0-255> [hz]` | `DRV_BL`: 0 dark, 255 on, between PWM at hz (100-50000, default 20000, the reference design's). Refused while `chain=0` |
| `out <chip> <n>` | One output on: U20*chip* HVOUT*n* (1-3, 1-32), all others off; for the Gate 3 output walk |
| `tube <t> <e>` | One element on: tube 1-6, e = 0-9, L (left point) or R (right point) |
| `show <chars>` | Up to six characters, tube 1 first: 0-9, L, R, or - for dark (e.g. `show 12-4L6`) |
| `raw <h1> <h2> <h3>` | A whole frame as three hex words (U201, U202, U203) |
| `cycle [ms]` | Every tube steps through 0-9, L, R together, ms per element (20-10000, default 1000), until the next command |
| `es100` | `WWVB_EN` high, 100 ms (wakeup 1.0 ms typ.), read register 0x0D at 0x32 (expect 0x10), `WWVB_EN` low, read again (expect no answer). I2C0 at 100 kHz |
| `wen <0\|1>` | Hold `WWVB_EN` |
| `log <s> [hz]` | CSV `t_ms,hv,sw12,nix12_en,bl` for s seconds (default 10 Hz, max 100), then `END` |
| `help` | List the commands |

A command that changes the frame sent while the tubes are lit takes effect at once; `bl` decides
whether anything is visible.
