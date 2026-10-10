# Build and investigate

The design is open: hardware under CERN-OHL-P v2, firmware and tools under MIT. Everything lives
in the [project repository](https://github.com/kuvychko/universal-nixie-display). This site explains; the repository documents.

| Where | What |
|---|---|
| [Project plan](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/project_plan.md) | Scope, phases and acceptance gates |
| [Architecture](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/architecture.md) | Power distribution, boards and who owns what |
| [Hardware design](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/hardware.md) | Electrical design, decisions and their sources |
| [Bring-up and bench results](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/bringup.md) | Test procedures and measurements, including the A101 bench test |
| [Dekatron board](https://github.com/kuvychko/universal-nixie-display/tree/main/hardware/dekatron) | KiCad project, simulations and fabrication files |
| [Enclosure](https://github.com/kuvychko/universal-nixie-display/tree/main/enclosure) | Printed parts and print settings |

!!! danger "High voltage"
    The display generates about 450 V for the dekatron and about 170-180 V for the Nixies. Those
    voltages can injure. The build documents give the precautions where they apply; read them before
    building or probing anything.

!!! info "Status"
    Phase 1 (dekatron controller and power supply) has its boards ordered and its tube
    bench-tested. A full build guide will follow a working, tested instrument.
