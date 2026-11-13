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

Address: **0x20** (7-bit; user, 2026-11-12). Behaviour behind each operation:
[firmware/dekatron/README.md](../firmware/dekatron/README.md). Definitions shared with the ESP32:
[`firmware/common/dekatron_protocol.h`](../firmware/common/dekatron_protocol.h), which is the
reference when this table and the header disagree.

**Framing (protocol version 1, draft until the ESP32 side runs against it).** A write is
`[op][len][payload…]`: `len` is the payload length in bytes and must equal the op's fixed length,
or the write is rejected (`bad_len`). An empty write is an address probe. A read returns the
status block from offset 0; the master may read fewer bytes. Multi-byte fields are little-endian.
Every processed write increments `cmd_seq` and sets `last_error` (0 when accepted), so the master
confirms each command by polling. Any I2C traffic, read or write, resets the master-loss timer.

| Op | Code | Payload | Notes |
|---|---|---|---|
| `PING` | 0x01 | — | No effect beyond the master-loss timer; accepted from either owner |
| `LIGHT` | 0x02 | — | HV on, strike, home. Refused with a fault latched (`state`) or VIN outside 10.8-13.2 V (`vin`) |
| `DARK` | 0x03 | — | HV off, position invalid |
| `HOME` | 0x04 | — | Needs `LIT` |
| `MOVE_TO` | 0x05 | `k` u8 (0-9), `dir` u8 (0 shortest, 1 fwd, 2 rev) | |
| `MOVE_RELATIVE` | 0x06 | `n` i16 | Added to the step queue; beyond ±32767 rejected (`queue_full`) |
| `ROTATE` | 0x07 | `rate` i32, 0.01 steps/s, signed, ≤ ±200000 | 0 stops |
| `STOP` | 0x08 | — | Finishes the current step; clears queue and effect. Homing continues |
| `SET_MOTION` | 0x09 | `move_rate` u16 steps/s (1-2000, default 200), `accel` u16 steps/s² (0 = none) | Queue and `MOVE_TO` play-out rate; `ROTATE` ramp |
| `SWING` | 0x0A | `centre` u8, `amplitude` u8 (1-5), `period` u16 ms (100-60000) | Sinusoidal pendulum, until `STOP` |
| `BOUNCE` | 0x0B | `a` u8, `b` u8 (≠ a), `rate` u16 steps/s | Forward from a to b and back, until `STOP` |
| `SPIN` | 0x0C | `start` u16, `end` u16 steps/s, `accel` u16 steps/s², `turns` u8 (1-255) | Then back to the starting position |
| `ARC` | 0x0D | `start` u8, `length` u8 (1-10), `sweep` u16 steps/s, `end_weight` u8 | POV arc, until `STOP` |
| `GAUGE` | 0x0E | `value` u16 (0-1000 = 0-10 cathodes) | Arc from position 0 |
| `EXERCISE` | 0x0F | — | 20 min at 200 steps/s, then back; clears the slow-running total |
| `CLEAR_FAULT` | 0x10 | — | |
| `BOOTSEL` | 0x11 | — | Reboot to the USB bootloader; refused unless dark |

Errors: 0 ok, 1 `bad_op`, 2 `bad_len`, 3 `range` (never clamped), 4 `state`, 5 `not_owner` (the
USB console has taken over with `local`), 6 `queue_full`, 7 `vin`. Motion ops need `LIT` and a
valid position.

Status block (45 bytes):

| Offset | Field | Type | Meaning |
|---|---|---|---|
| 0 | `protocol` | u8 | 1 |
| 1 | `module` | u8 | 0x44 (`D`) |
| 2 | `firmware` | u16 | major << 8 \| minor |
| 4 | `boot_count` | u16 | Increments every boot (flash) |
| 6 | `uptime_ms` | u32 | |
| 10 | `cmd_seq` | u8 | Processed writes, wrapping |
| 11 | `last_error` | u8 | Error of the last processed write |
| 12 | `owner` | u8 | 0 I2C, 1 USB console |
| 13 | `power` | u8 | 0 dark, 1 striking, 2 lit |
| 14 | `fault` | u8 | 0 none, 1 vin, 2 en_low, 3 hv_low, 4 strike_timeout, 5 index_timeout; latched |
| 15 | `dark_reason` | u8 | 0 boot, 1 command, 2 fault, 3 master_loss, 4 hold_limit |
| 16 | `flags` | u8 | bit 0 position valid, 1 busy, 2 PGOOD, 3 HV_EN, 4 master loss, 5 exercise due, 6 watchdog reset |
| 17 | `position` | u8 | 0-9, 0 = K1 (index) |
| 18 | `mode` | u8 | 0 idle, 1 home, 2 queue, 3 rotate, 4 swing, 5 bounce, 6 spin, 7 arc/gauge, 8 exercise |
| 19 | `queue` | i16 | Pending queued steps |
| 21 | `idx_expected` | u16 | K1 arrivals expected while the position was valid, wrapping |
| 23 | `idx_observed` | u16 | K1 arrivals seen while the position was valid, wrapping |
| 25 | `home_failures` | u16 | Inconsistent index patterns while homing, wrapping |
| 27 | `idx_mismatches` | u16 | Index disagreed with the count, wrapping |
| 29 | `dwell_ms` | u32 | Time on the current cathode |
| 33 | `rate_dsps` | u16 | Steps in the last 10 s (= 0.1 steps/s) |
| 35 | `slow_run_s` | u32 | Slow running since the last complete `EXERCISE` |
| 39 | `hv_dv` | u16 | HV_SENSE, 0.1 V |
| 41 | `vin_dv` | u16 | VIN_SENSE, 0.1 V |
| 43 | `rtn_dv` | u16 | RTN_SENSE, 0.1 V |

A homing timeout returns a fault, never a fabricated position.

## Nixie controller

Address: **0x21** (proposed with the dekatron's 0x20, 2026-11-12).

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
