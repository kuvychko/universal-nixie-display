# Internal I2C protocol

Versioned command/status contracts between the ESP32 (sole master) and the controllers.
**Draft — addresses and byte layouts must be assigned here before independent firmware work.**

## Bus

* 3.3 V logic, 100 kHz initially, short internal wiring.
* One pull-up arrangement for the whole bus: location and value _open_.
* Connector pinout by signal name, keyed, with ground; no HV on the connector.

## Rules common to all controllers

* Every controller reports a protocol version and module identity.
* Explicit payload lengths, bounded buffers, documented valid ranges; out-of-range requests are
  rejected with an error code, never clamped silently.
* Commands are brief and nonblocking: long operations (e.g. HOME) start work and return; completion
  is observed by polling status.
* No tube sequences run inside I2C interrupt callbacks.
* Status includes boot counter/uptime so the master can detect a controller reset.

## Dekatron controller

Address: _open_.

Operations: `HOME`, `MOVE_RELATIVE`, `MOVE_TO`, `ROTATE`, `STOP`, `STATUS`.
Status fields: `position`, `position_valid`, `busy`/`homing`, expected vs. observed index
crossings, homing failure count, fault code. A homing timeout returns a fault, never a fabricated
position.

## Nixie controller

Address: _open_.

Frames are staged then applied together. A frame holds six digit/blank values and decimal-point
state; brightness only once the hardware supports it. Status reports pending/active frame and
faults.

The front-panel rotary encoder is on this board (decision 2026-10-06). Its RP2040 decodes the
quadrature and debounces the button, and status exposes a cumulative signed detent count (wrapping
counter; the ESP32 takes differences) and button press/release events with a pending-event count.
The ESP32 polls it and owns what the encoder means.
