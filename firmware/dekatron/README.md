# Dekatron controller firmware

RP2040-Zero firmware for the dekatron controller/PSU in the finished display. It owns the A101's
timing and hardware state: HV, stepping, homing, position tracking and tube care. The ESP32 decides
what is shown and sends commands over I2C ([architecture](../../docs/architecture.md#ownership)).
**Version 0.1: motion tested with HV over the USB console** (2026-11-13, bring-up step 4). The
I2C path, hold limit and fault paths are not tested yet (Phase 1D, bring-up steps 4-5). The board
bring-up tool is separate: [`firmware/dekatron-bringup/`](../dekatron-bringup/README.md).

Toolchain: arduino-pico on PlatformIO, pinned to the same platform commit as the bring-up firmware
(decided 2026-11-12, [development.md](../../docs/development.md#toolchains)).

> [!WARNING]
> High voltage (~450-545 V). Read the [README safety section](../../README.md#safety-read-this-first).

Every parameter is in [`src/board.h`](src/board.h) with its source: the datasheet, the board 1
measurements or the user's decisions of 2026-11-12.

## Build and flash

```
pio run -d firmware/dekatron
```

Hold BOOT while plugging USB (or send `local` then `bootsel` on the console), then copy
`.pio/build/rp2040zero/firmware.uf2` to the RPI-RP2 drive. `pio ... -t upload` needs picotool's
WinUSB driver (Zadig) on Windows. Protocol definitions shared with the ESP32:
[`firmware/common/dekatron_protocol.h`](../common/dekatron_protocol.h).

## Step timing envelope

Decided by the user, 2026-11-12, from the board 1 speed sweep
([log](../../characterization/dekatron/2026-11-12_speed_sweep.md)). **Outside the datasheet**,
which gives a 200 µs minimum phase and 1000 Hz maximum rate; chosen for faster spins and wedges.

| Parameter | Value | Margin against the measurement |
|---|---|---|
| Guide phase | **100 µs** (each guide low 200 µs) | Clean from 50 µs up; steps lost at 30 µs |
| Maximum rate | **2000 steps/s** | Clean up to 3000 steps/s (highest tried) at 50-75 µs phase |
| Minimum rest (period − 3 × phase) | **200 µs**, which is what 2000 steps/s leaves at 100 µs phase | Clean from 108 µs; miscounts at 33-50 µs |
| Index sample | 100 µs after the second guide releases (proposed) | NDX valid from 30-40 µs after release |

Homing keeps the plan's 200 steps/s target (plan §5). Measured on one board, one warm tube at
453 V; re-check on each new board and tube (bring-up step 3a).

## Capabilities

### Motion

| Operation | Does |
|---|---|
| `HOME` | Steps toward K1 and checks the index only at a settled phase. It confirms K1 before setting position 0 and `position_valid`. A timeout is a fault, never a fabricated position (plan §5) |
| `MOVE_TO k` | Goes to main cathode k (0-9). Shortest path by default, or a forced direction |
| `MOVE_RELATIVE ±n` | Adds n steps to the step queue (below) |
| `ROTATE r` | Continuous rotation at a signed rate r, in 0.01 steps/s, so a seconds display (1 step/s) is exact. 0 stops |
| `STOP` | Stops at a main cathode: the step in progress always finishes, and the queue and any animation are cleared |
| Ramp | Optional acceleration limit on rate changes, so a fast spin starts and stops smoothly |

Every motion command needs the tube lit and the position valid, except `HOME`. A command the
current state cannot run is rejected with an error code, never queued silently.

### Step queue

For event-driven demos (Collatz, Kaprekar, primes, Monte Carlo walk; plan §6), the ESP32 sends
±n as events happen. The controller adds them to a signed accumulator and plays it out at a capped
rate, so no event is lost while the tube is still moving. An add that would overflow the
accumulator is rejected with an error. Status reports the queue depth so the ESP32 can pace
itself. The queue holds up to ±32767 steps and plays out at the move rate (`SET_MOTION`,
default 200 steps/s, the plan's homing rate), which `MOVE_TO` also uses.

### Local animations

The ESP32 selects an effect and its parameters; the RP2040 times every step. Each effect ends by
returning to the commanded position, or runs until `STOP`.

| Effect | Parameters |
|---|---|
| `SWING` (pendulum) | Centre, amplitude (1-5), period. Follows a sine, so it slows at the turning points |
| `BOUNCE` | Between two cathodes at a constant rate |
| `SPIN` | Start rate, end rate, acceleration, number of turns; then back to where it started |

### Wedge, magic eye and gauge

The glow bounces between two bookends. Fast enough, the whole sector between them looks lit, like
the shadow of a magic eye tube; slowly, the glow is seen travelling between them. The sweep rate
(1-2000 steps/s) chooses the look (user, 2026-11-13). At 2000 steps/s a five-cathode wedge
(8 steps per sweep and back, 4.4 ms with the bookend dwells) repeats about 230 times a
second.

* **Coordinates:** 0.01 cathode; cathode k spans k.00-k.99, so `WEDGE(2.00, 6.00)` lights
  cathodes 2-5 fully. Bookends between whole cathodes light the end cathodes partly.
* **Two forms** (user, 2026-11-13): `WEDGE(a, b, rate)`, clockwise from bookend a to bookend b,
  across K1 if needed, a = b being the whole ring; and `WEDGE_CENTRED(centre, half_width, rate)`,
  symmetric about a cathode, opening and closing like a magic eye. `GAUGE(value)` is
  `WEDGE(0, value)` at 2000 steps/s.
* **Updates in place** (user, 2026-11-13): sent again while a wedge runs, the new bookends take
  effect at the next step; the sweep carries on in its direction, walking in if the glow is
  outside the new wedge. The ESP32 can stream a level (e.g. 20 updates/s) without hiccups.
* **Even brightness:** a step spends 3 × 100 µs on the guides, so a cathode glows for the step
  gap minus that. Interior cathodes are passed twice per sweep cycle; a bookend is visited once and
  dwells for its share of two passes. A bookend share too small for the 500 µs minimum step period
  is shown by visiting it on that fraction of cycles (error diffusion); the sweep turns at its
  neighbour on the others. A wedge only two cathodes wide cannot skip either end, so there the
  minimum period limits small shares (0.7/0.3 at 2000 steps/s shows about 0.7/0.4).
* A wedge narrower than one cathode cell is a held glow on that cathode, under the hold limit.
* The index is checked on every step, so a wedge that covers K1 is checked on each pass.
* `BOUNCE` stays the plain version: whole cathodes, one constant interval, the ends dimmer.

### Position integrity

* Expected vs. observed index on every K1 pass during motion. A mismatch (an index where none is
  expected, or a missing one) clears `position_valid`, increments a mismatch counter and schedules
  a re-home at the next idle boundary. Single-index tracking cannot see every missed step between
  K1 visits (plan §5).
* Re-home after a dark period, a controller reset or a detected inconsistency. Periodic homing can
  sit on an animation boundary.
* After switch-on two cathodes may glow. Homing steps the tube and confirms a single, consistent
  index before it trusts the position (hardware.md, A101 operating point).

### Tube care (plan §5)

The controller enforces this itself, whatever the ESP32 asks for.

* It tracks the time the glow has spent at the current position and the recent step rate, and
  reports both in status.
* **Hold limit: 30 min, then dark** (user, 2026-11-12), with `dark_reason = hold_limit`. It counts
  the time on one cathode, and also running slower than one step per 100 s (the datasheet's
  0.01 Hz, allowed for ≤ 1 h): gaps longer than 100 s add up until a shorter one comes.
* **Slow running is tracked, the ESP32 schedules the exercise** (user, 2026-11-12). Time lit at
  ≤ 1 step/s (≤ 10 steps in the last 10 s) adds to `slow_run_s` and sets `exercise due`.
  `EXERCISE` runs the datasheet's training, 20 min at 200 steps/s (≥ 100 Hz), returns to the
  position it started from and clears the total; a stopped exercise does not.

### Power states

| State | Meaning |
|---|---|
| `DARK` | HV_EN low, guides at rest. The default at boot, when idle, on any fault, and whenever there is nothing to show |
| `STRIKING` | HV on and stepping at the homing rate until a consistent index. The window is 10 s, twice the datasheet's 5 s readiness in darkness; then a strike-timeout fault and `DARK` |
| `LIT` | Glow confirmed. Motion commands accepted once homed |

* `LIGHT` / `DARK` commands. Relighting always strikes and re-homes: the position is never carried
  across a dark period.
* No idle timeout (user, 2026-11-12): a held value is covered by the hold limit, and the ESP32
  decides when the tube has nothing to show.
* **Master-loss timeout: 5 s** (user, 2026-11-12). If there is no I2C traffic (read or write) for
  5 s, the controller goes `DARK` and sets the master-loss flag until the next `LIGHT`, so the tube
  never holds a glow unattended. It does not apply while the USB console owns the controller;
  `remote` restarts the 5 s.

### Faults

Latched until cleared; any fault drops HV and returns the guides to rest.

| Fault | Source |
|---|---|
| `vin` | VIN_SENSE outside 10.8-13.2 V while on, or before turning on (as in the bring-up firmware) |
| `en_low` | EN/UVLO node read low on GP8 while on: OVP comparator tripped, or the JP101 inhibit fitted |
| `hv_low` | PGOOD low for ≥ 100 ms while lit, or never high within the strike window: the LM5156's own regulation flag, not an ADC threshold |
| `strike_timeout` | PGOOD came up but no consistent index within the 10 s strike window |
| `index_timeout` | `HOME` found no consistent index within 50 steps (5 turns, retries included) |
| watchdog reset (500 ms) | Status flag and boot counter. Core 1 feeds the watchdog only while core 0 is alive. GP6's pull-down holds HV off during reset |

### Telemetry (status)

HV, VIN, RTN, NDX level, PGOOD, power state, fault, position, `position_valid`, busy/homing,
expected vs. observed index crossings, homing failure and mismatch counters, queue depth, active
effect, dwell at the current position, recent step rate, slow-running total, uptime, boot
counter, watchdog-reset flag, firmware and protocol version. ADC readings use the 3.3 V rail as reference and are indicative
only (as in the bring-up firmware).

### Interfaces

* **I2C target** on I2C1, GP2 (SDA) and GP3 (SCL); contract in
  [i2c_protocol.md](../../docs/i2c_protocol.md#dekatron-controller). The receive callback only
  copies a command into a queue. Nothing tube-related runs inside it.
* **USB console** (below) for standalone diagnostics without the ESP32. Ownership is explicit:
  I2C owns the controller at boot, `local` takes over (I2C commands then get `not_owner`, and
  status shows the owner), and `remote` hands it back. `PING` and status reads work for either.
* **UART debug** on GP0/GP1 (test pads): not used yet.
* **LED** (GP16): dim red while HV_EN is high, blinking red with a fault latched, dim blue when
  dark under console ownership, off otherwise.
* **Reboot to BOOTSEL** by command, refused unless HV is off, so the unit can be reflashed inside
  the enclosure without reaching the button.

### Timing engine

* A PIO program ([`src/stepper.cpp`](src/stepper.cpp)) on GP4/GP5 plays each step's four guide
  transitions at 1 µs resolution, so the guide timing does not jitter with I2C or USB traffic.
  GP4 and GP5 are adjacent for this reason (hardware.md pin table).
* **Core 1** ([`src/controller.cpp`](src/controller.cpp)) owns HV_EN, the guides and the ADC, and
  runs one loop: commands, safety, the index sample 100 µs after release, telemetry, the next
  step, the status snapshot. Commands are applied only between steps.
* **Core 0** ([`src/main.cpp`](src/main.cpp)) runs the I2C target, the USB console and the LED.
  The I2C callbacks only frame a command into a queue or copy the status snapshot.

## Console

USB serial, one command per line; replies `OK`, `ERR <error>`, or the status line.

| Command | Op |
|---|---|
| `status` | Status line: every field of the I2C status block, plus the last NDX sample |
| `local` / `remote` | Take ownership from I2C / hand it back |
| `ping`, `light`, `dark`, `home`, `stop`, `exercise`, `clear`, `bootsel` | As the ops |
| `moveto <k> [fwd\|rev]` | `MOVE_TO` |
| `move <n>` | `MOVE_RELATIVE` |
| `rotate <steps/s>` | `ROTATE`, decimals allowed |
| `motion <move_rate> <accel>` | `SET_MOTION` |
| `swing <centre> <amp> <period_ms>` | `SWING` |
| `bounce <a> <b> <rate>` | `BOUNCE` |
| `spin <start> <end> <accel> <turns>` | `SPIN` |
| `wedge <a> <b> <rate>` | `WEDGE`, bookends in cathodes with decimals: `wedge 2.3 5.7 2000` |
| `wedgec <centre> <half_width> <rate>` | `WEDGE_CENTRED`, half-width in cathodes: `wedgec 4 1.5 2000` |
| `gauge <0-1000>` | `GAUGE` |

### Out of scope

* Brightness control: tube current is set by the anode resistors.
* More index channels: the nine other cathodes have links for later sensing (hardware.md D9);
  the firmware assumes K1 only.
