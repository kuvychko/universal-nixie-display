# CLAUDE.md

Six-IN-14 + A101 dekatron display with an ESP32 touchscreen. Planning baseline:
`docs/project_plan.md`. Current phase and open decisions: README "Status" and the Phase 1A
decision register in `docs/hardware.md`.

* Sister project and reference for structure, CYD pin map, SCPI parser, KiCad/PlatformIO
  conventions: `../nanovolt-divider` (https://github.com/kuvychko/nanovolt-divider).
* Never invent electrical values. A value in `docs/hardware.md` needs a source (datasheet,
  simulation, measurement or the user's decision); otherwise leave it `_open_`.
* HV (~450 V dekatron, ~170-180 V Nixie): HV off and tubes dark/idle must be the hardware default
  while any MCU is in reset or being flashed.
* ESP32 owns what is displayed; RP2040 controllers own timing and hardware state. Keep it that way.
* Text files are LF (`.gitattributes`); fab outputs under `hardware/<module>/fab/` are byte-exact.
* Licences: CERN-OHL-P v2 for hardware/docs/enclosure/characterization and site content (`website/`),
  MIT for firmware/tools/tests and site code (`website/javascripts/`).
