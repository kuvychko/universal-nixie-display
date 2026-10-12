# universal-nixie-display

A programmable desktop display: six IN-14 Nixie tubes in a row, one A101 dekatron, a 2.8" ESP32
touchscreen and a rotary encoder, in a matte PLA enclosure on a tilt base. It is meant to be an
enjoyable object on its own (clock, timer, demo) and a numeric output device for a computer,
Raspberry Pi or experiment, driven over USB serial with a small SCPI-style command set.

## Status

**Phase 1C — dekatron controller/PSU boards ordered** (PCBWay, 2026-10-09; parts ordered
2026-10-08). Schematics, simulations, PCB and fab files are done; nothing is built yet. The
planning baseline is [docs/project_plan.md](docs/project_plan.md); the design decisions and
open items are tracked in [docs/hardware.md](docs/hardware.md#dekatron-controllerpsu).

| Phase | Deliverable | State |
|---|---|---|
| 1A | Dekatron board architecture and power budget for 12 VDC input | Done |
| 1B | Hierarchical schematics and simulation evidence | Done (open simulation items in `docs/hardware.md`) |
| 1C | Dekatron controller/PSU PCB, BOM, fab files | **Boards and parts ordered** |
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
| [docs/companion_site.md](docs/companion_site.md) | Plan for the public companion website (`website/`) |

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
| `enclosure/` | Printed parts, one folder per assembly (SOLIDWORKS source, STEP, 3MF); index and print settings in its README |
| `tools/` | Serial client, bring-up scripts |
| `characterization/` | Dated measurements (supply, homing, thermal, reliability) |
| `tests/` | Host protocol/formatting tests, hardware test scripts |
| `website/` | Companion site source (MkDocs Material; `mkdocs.yml` at the root) |

## Safety: read this first

> [!WARNING]
> **This project uses dangerous voltages.** The dekatron runs from about 450 V DC and the Nixies
> from about 170-180 V DC. A shock at these voltages can cause serious injury or death, and
> capacitors can hold a charge after the power is off. If you build, test or copy anything here,
> you do so **entirely at your own risk**. Work on it only if you understand high-voltage
> circuits and know what you are doing. The designs and documents are provided as is, without
> warranty of any kind (see [LICENSE](LICENSE)).

The **A101 bench test** ([docs/bringup.md](docs/bringup.md#optional-a101-bench-test)) is the most
exposed part of the project: open wiring on a perf board, the anode at up to 450 V and every other
wire at 50-106 V, none of them at ground. If you try it:

* **One hand.** While anything is powered, keep one hand away from the circuit, for example in a
  pocket. Operate buttons by their insulated caps.
* **Limit the current.** Use a bench supply with an adjustable current limit, set to a few
  milliamps (2-3 mA for the bench test).
* **Power off to touch.** Make and change connections only with the supply off and its output
  discharged; measure before you touch anything.
* **Rated equipment.** Use meters, probes and leads rated for the voltage. Clip leads on before
  powering up rather than holding probes on live nodes.
* **Not alone, not tired.** Work with someone nearby, and stop when you are not concentrating.

On the boards, discharge paths, clearances and probe ratings are design requirements, not
afterthoughts (project plan §4). Printed plastic parts keep fingers away; they are not
high-voltage insulation.

## Acknowledgements

The dekatron controller/PSU boards are being made by [PCBWay](https://www.pcbway.com/), who are
sponsoring their fabrication. Ordering was easy and smooth: upload the Gerber zip from
[`hardware/dekatron/fab/`](hardware/dekatron/fab/), pick the options and go. What stands out is
how much information their website gives, from exactly what you are ordering to where your order
is in production. There is even a full walk-through of how a board is made, step by step:
[PCB manufacturing process](https://www.pcbway.com/pcb-service.html). Beyond bare boards they
also make SMD stencils and offer assembly, CNC machining and 3D printing.

The boards are in production as this is written (October 2026), so there is nothing to say yet
about how they turn out; that will follow when they arrive and are brought up. Thank you, PCBWay,
for supporting an open-source hardware project.

## Licence

Hardware, enclosure and documentation: CERN-OHL-P v2. Firmware, tools and tests: MIT. See
[LICENSE](LICENSE).
