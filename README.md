# universal-nixie-display

A programmable desktop display: six IN-14 Nixie tubes in a row, one A101 dekatron, a 2.8" ESP32
touchscreen and a rotary encoder, in a matte PLA enclosure on a tilt base. It is meant to be an
enjoyable object on its own (clock, timer, demo) and a numeric output device for a computer,
Raspberry Pi or experiment, driven over USB serial with a small SCPI-style command set.

## Status

**Phase 1A — design for 12 VDC (dekatron controller/PSU board).** Nothing is built yet. The
planning baseline is [docs/project_plan.md](docs/project_plan.md); the open Phase 1A decisions are
tracked in [docs/hardware.md](docs/hardware.md#dekatron-controllerpsu).

| Phase | Deliverable | State |
|---|---|---|
| 1A | Dekatron board architecture and power budget for 12 VDC input | **In progress** |
| 1B | Hierarchical schematics and simulation evidence | Not started |
| 1C | Dekatron controller/PSU PCB, BOM, fab files | Not started |
| 1D | Sectional bring-up and standalone firmware | Not started |
| 2 | Nixie PSU qualification and six-tube controller/mount | Not started |
| 3 | ESP32 UI, encoder, I2C master, USB host commands | Not started |
| 4 | Enclosure | Not started |
| 5 | Rev A release | Not started |

## Architecture

```
 12 VDC adapter ──┬──────────────► purchased Nixie HV module (~170-180 V) ──► Nixie controller/mount
                  │                                                           (6× IN-14, 6× K155ID1, RP2040-Zero)
                  └──► dekatron controller/PSU ──► A101 (HV, bias, guide drive, index sense, RP2040-Zero)
                         │ 5 V buck out
                         ▼
                   ESP32 2.8" display board ◄── USB-C to host (SCPI-style serial)
                   (UI, encoder, presets, I2C master)
                         │ I2C, 3.3 V
                         └──► dekatron controller, Nixie controller
```

The ESP32 owns *what* is displayed; the RP2040 controllers own time-sensitive sequences and
hardware state. See [docs/architecture.md](docs/architecture.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/project_plan.md](docs/project_plan.md) | Planning baseline: scope, decisions, phases and acceptance gates |
| [docs/architecture.md](docs/architecture.md) | Power distribution, board boundaries, ownership |
| [docs/hardware.md](docs/hardware.md) | Electrical design, open decisions, harness tables |
| [docs/i2c_protocol.md](docs/i2c_protocol.md) | Versioned controller command/status contracts |
| [docs/host_interface.md](docs/host_interface.md) | USB serial / SCPI-style host contract |
| [docs/bringup.md](docs/bringup.md) | Module bring-up procedures and acceptance results |
| [docs/development.md](docs/development.md) | Toolchains, KiCad workflow, generated-file policy |
| [docs/references.md](docs/references.md) | Datasheets, source designs, attribution and reuse terms |

## Repository layout

| Path | Contents |
|---|---|
| `hardware/dekatron/` | Dekatron controller/PSU KiCad project; `simulation/` holds supply and drive/sense models |
| `hardware/nixie/` | Nixie controller/mount KiCad project |
| `hardware/power/` | Purchased Nixie PSU specification and system power harness |
| `hardware/lib/` | Shared symbols and footprints |
| `firmware/display/` | ESP32 main application (PlatformIO) |
| `firmware/dekatron/` | RP2040 dekatron controller and standalone diagnostics |
| `firmware/nixie/` | RP2040 Nixie controller |
| `firmware/common/` | Shared protocol definitions |
| `enclosure/` | SOLIDWORKS source, STEP, 3MF |
| `tools/` | Serial client, bring-up scripts |
| `characterization/` | Dated measurements (supply, homing, thermal, reliability) |
| `tests/` | Host protocol/formatting tests, hardware test scripts |

## Safety

This project generates roughly 170-180 V (Nixies) and roughly 450 V (dekatron) DC from a 12 V
adapter. Those voltages can injure. Discharge paths, clearances and probe ratings are design
requirements here, not afterthoughts; see the project plan §4.

## Licence

Hardware, enclosure and documentation: CERN-OHL-P v2. Firmware, tools and tests: MIT. See
[LICENSE](LICENSE).
