# Architecture

Power distribution, board boundaries and ownership. Derived from
[project_plan.md](project_plan.md) §2-4; update this file when a decision there changes.

## Physical assemblies

| # | Assembly | Source | MCU | Independent operation |
|---|---|---|---|---|
| 1 | ESP32-2432S028R display board ("CYD", 2.8" ILI9341, landscape) | Purchased, existing (same as nanovolt-divider) | ESP32 | UI and protocol against simulated controller status |
| 2 | Dekatron controller/PSU | Custom PCB (first deliverable) | RP2040-Zero daughterboard | USB console and built-in diagnostics, no ESP32 or Nixies |
| 3 | Nixie controller/mount, with the front-panel rotary encoder | Custom PCB | RP2040-Zero daughterboard | Local diagnostic sequence or USB console with purchased HV module |
| 4 | Nixie HV module | Purchased | — | Dummy-load characterization |

Exact board revisions are recorded in [hardware.md](hardware.md#board-revisions) once confirmed.

## Power distribution

| Rail | Source | Consumers | Notes |
|---|---|---|---|
| 12 V | External isolated adapter | Nixie HV module, dekatron board | Input protection and switch: open (hardware.md) |
| ~450 V nominal | Dekatron board HV converter | A101 anode/bias network, bleeder | Topology open: direct boost, boost + multiplier, or flyback |
| ~170-180 V | Purchased Nixie module | IN-14 anodes, DP switches | Qualified in Phase 2 |
| 5 V | Buck on dekatron board | ESP32 display, K155ID1s, RP2040s | Capacity set by the power budget; optional output connector |
| 3.3 V | Local regulators | Logic, I2C | Per module |

USB-C on the display board carries host data/programming. USB alone need not light the tubes.
USB VBUS must never back-feed the 12 V-derived 5 V rail or vice versa (open item).

## Ownership

* **ESP32** decides what is displayed: modes, presets, touch/encoder meaning, host commands, frame
  composition, time source. It is the only I2C master. It reads the encoder as a count and button
  events from the Nixie controller over I2C.
* **RP2040 controllers** are peripherals: they own time-sensitive sequences (dekatron stepping,
  homing, frame application) and hardware state, and report status. They never decide content.
* Every input path (preset, touch, encoder, host) produces the same display frame through one
  application path.
* Local vs. host ownership of the display is explicit (`DISP:MODE PRESET|REMOTE`).

## Signal boundaries

* Internal I2C at 3.3 V, 100 kHz to start, one deliberate pull-up arrangement. Contracts in
  [i2c_protocol.md](i2c_protocol.md).
* HV never shares a connector with I2C or the TFT harness; HV wiring is routed separately with
  strain relief.
* No mains wiring inside the enclosure.
