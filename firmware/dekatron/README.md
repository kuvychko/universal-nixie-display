# Dekatron controller firmware

RP2040-Zero firmware for the dekatron controller/PSU in the finished display. It owns the A101's
timing and hardware state: HV, stepping, homing, position tracking and tube care. The ESP32 decides
what is shown and sends commands over I2C ([architecture](../../docs/architecture.md#ownership)).
**Specification, not yet implemented** (Phase 1D, bring-up steps 4-5). The board bring-up tool is
separate: [`firmware/dekatron-bringup/`](../dekatron-bringup/README.md).

Toolchain: arduino-pico on PlatformIO, pinned to the same platform commit as the bring-up firmware
(decided 2026-11-12, [development.md](../../docs/development.md#toolchains)).

> [!WARNING]
> High voltage (~450-545 V). Read the [README safety section](../../README.md#safety-read-this-first).

Numbers marked `_open_` are firmware parameters still to be set: from the datasheet limits with
margin, or from bench measurements. None is to be guessed.

## Step timing envelope

Decided by the user, 2026-11-12, from the board 1 speed sweep
([log](../../characterization/dekatron/2026-11-12_speed_sweep.md)). **Outside the datasheet**,
which gives a 200 µs minimum phase and 1000 Hz maximum rate; chosen for faster spins and arcs.

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
itself. Queue limit and play-out rate: `_open_`.

### Local animations

The ESP32 selects an effect and its parameters; the RP2040 times every step. Each effect ends by
returning to the commanded position, or runs until `STOP`.

| Effect | Parameters |
|---|---|
| `SWING` (pendulum) | Centre, amplitude, period; optional slowing at the turning points |
| `BOUNCE` | Between two cathodes at a constant rate |
| `SPIN` | Start rate, end rate, acceleration, number of turns or duration |

### POV arc and gauge

Sweeping back and forth across a span of cathodes fast enough makes the whole span look lit: an
arc, or a bar-graph gauge on the ring. `ARC(start, length, sweep rate)` and `GAUGE(value)` take a
dwell weighting that sets how bright the end cathode looks, so a gauge can show fractions of a
cathode. Requests above the step timing envelope (2000 steps/s) are rejected. At that rate a
five-cathode arc (10 steps per sweep and back) repeats 200 times a second. Index checks run only
while the arc covers K1, so a re-home is scheduled when the arc ends.

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
* Before a static hold reaches the datasheet's 1 hour limit, it exercises the tube and returns to
  the commanded position, or it goes dark. Hold limit and exercise schedule: `_open_`.
* Slow modes (≤ 1 Hz, e.g. a seconds display) count as slow running, so they schedule the
  datasheet's exercise at ≥ 100 Hz. Exercise length and timing: `_open_`, within the datasheet.

### Power states

| State | Meaning |
|---|---|
| `DARK` | HV_EN low, guides at rest. The default at boot, when idle, on any fault, and whenever there is nothing to show |
| `STRIKING` | HV on and waiting for the glow: at least 5 s allowed in darkness (datasheet). Ends in a home that confirms a single glow; if none appears, a strike-timeout fault and `DARK` |
| `LIT` | Glow confirmed. Motion commands accepted once homed |

* `LIGHT` / `DARK` commands. Relighting always strikes and re-homes: the position is never carried
  across a dark period.
* Idle timeout: lit with nothing commanded for N s → `DARK`. N: `_open_`.
* **Master-loss timeout:** if the ESP32 sends no I2C traffic for N s, the controller goes `DARK`
  and sets a status flag, so the tube never holds a glow unattended. This timeout is suspended
  while the USB console owns the controller. N: `_open_`.

### Faults

Latched until cleared; any fault drops HV and returns the guides to rest.

| Fault | Source |
|---|---|
| `vin` | VIN_SENSE outside 10.8-13.2 V while on, or before turning on (as in the bring-up firmware) |
| `en_low` | EN/UVLO node read low on GP8 while on: OVP comparator tripped, or the JP101 inhibit fitted |
| `hv_low` | HV_SENSE below a threshold while lit (converter not regulating). Threshold: `_open_` |
| `strike_timeout` | No glow confirmed within the strike window |
| `index_timeout` | `HOME` saw no index within its step budget |
| watchdog reset | Reported via reset reason and boot counter. GP6's pull-down holds HV off during reset |

### Telemetry (status)

HV, VIN, RTN, NDX level, PGOOD, power state, fault, position, `position_valid`, busy/homing,
expected vs. observed index crossings, homing failure and mismatch counters, queue depth, active
effect, dwell at the current position, recent step rate, uptime, boot counter, reset reason,
firmware and protocol version. ADC readings use the 3.3 V rail as reference and are indicative
only (as in the bring-up firmware).

### Interfaces

* **I2C target** on I2C1, GP2 (SDA) and GP3 (SCL); contract in
  [i2c_protocol.md](../../docs/i2c_protocol.md#dekatron-controller). The receive callback only
  copies a command into a queue. Nothing tube-related runs inside it.
* **USB console:** the same operations as text commands, plus the bring-up firmware's `status`
  and `log`, for standalone diagnostics without the ESP32. Ownership is explicit: `local` takes
  over from I2C (I2C commands are then rejected with a busy code, and status shows the owner),
  and `remote` hands it back.
* **UART debug** on GP0/GP1 (test pads), which keeps working while USB enumerates.
* **LED** (GP16): power state and faults at a glance.
* **Reboot to BOOTSEL** by command, refused unless HV is off, so the unit can be reflashed inside
  the enclosure without reaching the button.

### Timing engine (design intent)

* A PIO program on GP4/GP5 plays each step's four guide transitions from FIFO words (direction,
  phase), so step timing does not jitter with I2C or USB traffic. GP4 and GP5 are adjacent for
  this reason (hardware.md pin table).
* The index is sampled at a PIO-timed point after the guides release, at the delay in the step
  timing envelope above.
* The motion scheduler (queue, ramps, effects, tube care) runs on core 1 or from a hardware alarm.
  Core 0 runs I2C, USB and safety monitoring.
* Operating guide phase and maximum step rate: the step timing envelope above.

### Out of scope

* Brightness control: tube current is set by the anode resistors.
* More index channels: the nine other cathodes have links for later sensing (hardware.md D9);
  the firmware assumes K1 only.
