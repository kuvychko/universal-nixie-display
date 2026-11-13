# Internal I2C protocol

Versioned command/status contracts between the ESP32 (sole master) and the controllers.
**Draft — addresses and byte layouts must be assigned here before independent firmware work.**

## Bus

* 3.3 V logic, 100 kHz initially, short internal wiring.
* One pull-up arrangement for the whole bus: location and value _open_.
* Connector pinout by signal name, keyed, with ground; no HV on the connector.
* Third-party devices: the DS3231 RTC (ZS-042 module), address _open_ until checked against its
  data sheet. The ES100 WWVB receiver (0x32) is **not** on this bus: its data sheet asks for a
  dedicated one, so the Nixie controller runs it privately. Both are optional modules.

## Rules common to all controllers

* Every controller reports a protocol version and module identity.
* Explicit payload lengths, bounded buffers, documented valid ranges; out-of-range requests are
  rejected with an error code, never clamped silently.
* Commands are brief and nonblocking: long operations (e.g. HOME) start work and return; completion
  is observed by polling status.
* No tube sequences run inside I2C interrupt callbacks.
* Status includes boot counter/uptime so the master can detect a controller reset.

## Dekatron controller

Address: _open_. Behaviour behind each operation:
[firmware/dekatron/README.md](../firmware/dekatron/README.md).

**Draft framing (2026-11-12, not frozen).** A write is `[op][len][payload…]`: `len` is the payload
length in bytes and must match the op's fixed length, or the write is rejected. A read returns the
status block below. Multi-byte fields are little-endian. Every accepted write increments
`cmd_seq`, and a rejected one sets `last_error`, so the master can confirm each command by
polling. Op codes and field widths are placeholders until the firmware is written against them.

| Op | Payload | Notes |
|---|---|---|
| `LIGHT` | — | HV on, strike, home. Completion seen in status |
| `DARK` | — | HV off, position invalid |
| `HOME` | — | Needs `LIT` |
| `MOVE_TO` | `k` u8 (0-9), `dir` u8 (0 shortest, 1 fwd, 2 rev) | |
| `MOVE_RELATIVE` | `n` i16 | Added to the step queue; overflow rejected |
| `ROTATE` | `rate` i32, 0.01 steps/s, signed | 0 stops |
| `STOP` | — | Finishes the current step; clears queue and effect |
| `SET_RAMP` | `accel` u16, steps/s² (0 = none) | |
| `EFFECT` | `id` u8, parameters (fixed per id) | `SWING`, `BOUNCE`, `SPIN` |
| `ARC` | `start` u8, `length` u8, `sweep` u16 steps/s, `end_weight` u8 | Rejected above validated limits |
| `GAUGE` | `value` u16 (0-1000 = 0-10 cathodes) | |
| `CLEAR_FAULT` | — | |
| `PING` | — | Resets the master-loss timer without other effect (any valid write also does) |

Status block: protocol version, module id, firmware version, boot counter, uptime, reset reason;
`cmd_seq`, `last_error`; owner (I2C or USB console); power state (`DARK`/`STRIKING`/`LIT`), fault
code, master-loss flag; `position`, `position_valid`, busy/homing, active effect; expected and
observed index crossings, homing failures, index mismatches; queue depth; dwell at the current
position, recent step rate; HV, VIN, RTN (0.1 V units) and PGOOD. A homing timeout returns a
fault, never a fabricated position.

## Nixie controller

Address: _open_.

Frames are staged then applied together. A frame holds six digit/blank values and decimal-point
state, plus a brightness level (the Nixie RP2040 dims by PWM on the HV5622 blanking line). Status reports pending/active frame and
faults.

The front-panel rotary encoder is on this board (decision 2026-10-06). Its RP2040 decodes the
quadrature and debounces the button, and status exposes a cumulative signed detent count (wrapping
counter; the ESP32 takes differences) and button press/release events with a pending-event count.
The ESP32 polls it and owns what the encoder means.

WWVB (2026-10-26): status reports whether a receiver is present (ES100 device ID found). The
ESP32 asks the Nixie controller to start a reception (full frame or tracking) and polls status
for the outcome: busy, success/failure, the received UTC date and time with the IRQ- second
boundary, DST and leap-second flags, next DST transition. The ESP32 sets the time; the controller
never does. Byte layout _open_.
