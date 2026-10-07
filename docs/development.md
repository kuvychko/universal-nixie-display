# Development

Toolchains, workflow and generated-file policy. Commands run from the repository root.

## Toolchains

| Area | Tool | Notes |
|---|---|---|
| Schematics/PCB | KiCad 10 | One project per board under `hardware/<module>/`; shared library in `hardware/lib/` |
| Simulation | ngspice-45 (shipped with Qucs-S in `C:/Simulators/Qucs-S/bin`); KiCad 10's built-in ngspice for schematic-level checks | Benches and summarised results in `hardware/dekatron/simulation/` |
| ESP32 firmware | PlatformIO, Arduino framework | `firmware/display/`; pin platform and library versions |
| RP2040 firmware | _open_ (PlatformIO arduino-pico or Pico SDK) | `firmware/dekatron/`, `firmware/nixie/` |
| Tools/tests | Python via `uv` | `tools/`, `tests/` |
| Enclosure | SOLIDWORKS | Commit source plus STEP and 3MF exports |

## KiCad

ERC and DRC from the command line (once the project exists):

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/dekatron/dekatron.kicad_sch
kicad-cli pcb drc --severity-error --severity-warning hardware/dekatron/dekatron.kicad_pcb
```

Record the ERC/DRC baseline here and check that each change does not add to it.

### Generator

`tools/gen_schematics.py` writes the dekatron schematics, the project symbol library and a BOM
(`hardware/dekatron/bom.csv`) from the values in `docs/hardware.md`. The sheets are drawn as
ordinary schematics: each circuit block is wired, with power and GND symbols. `Sheet.place()`
returns pin coordinates, `Sheet.w()` draws orthogonal wires, and `Sheet.finish()` adds a junction
wherever three or more wire ends or pins meet. Wires only meet at their ends; the one deliberate
crossing (TLV3011 REF tied to IN+, across IN-) has no junction. Local labels name the nets that
the PCB scripts and net classes rely on (`STR_*`, `TRP_*`, `LM5156_*` and so on), and they join
blocks within a sheet, such as the LM5156 FB/CS pins to their dividers. Inter-sheet nets are
global labels, and IC pins that leave their block (the RP2040-Zero, the harness landings) end in
short labelled stubs. When you change a drawing, compare the exported netlist's pin partition
with the previous one: a redraw must not change connectivity. It writes `dekatron.kicad_pro` only if it does not
exist (KiCad owns it afterwards; it carries the D13 net classes). To change the net classes before
anyone edits the project in KiCad, delete it and re-run; afterwards edit it in KiCad. Re-run after editing the script:

```
python tools/gen_schematics.py
```

### ERC baseline (all sheets: power, tube, mcu; 2026-10-06)

`kicad-cli sch erc --severity-all hardware/dekatron/dekatron.kicad_sch`: **1 violation, expected:**
`pin_to_pin` power output to power output, the LP2951 output driving the LM5156 VCC pin in
BIAS = VCC mode (intentional, D2). Every inter-sheet global label connects.

### Project footprint

`hardware/dekatron/lib/dekatron.pretty/RP2040-Zero_Castellated.kicad_mod` (generated) carries the
module: pads at Waveshare's castellation positions (from their STEP model), extended ~1.4 mm past
the module edge for hand soldering. Check it with `kicad-cli fp export svg` after changes, and
print it 1:1 against a real module before ordering boards (bring-up step 0).

## Simulation

Benches are plain ngspice netlists (`.cir`) in `hardware/dekatron/simulation/`, so they run in
batch without a GUI and diff cleanly; Qucs-S is used for interactive exploration. Run a bench:

```
"C:/Simulators/Qucs-S/bin/ngspice_con.exe" -b hardware/dekatron/simulation/<bench>.cir
```

Each bench states its model sources and limitations in its header. Commit summarised results
(tables, plots) rather than `.raw` data. A simplified tube model can support circuit analysis but
cannot establish glow transfer, ignition or homing (plan §9).

## Generated-file policy

* `.gitattributes` pins text files to LF, matching KiCad. Released fab files under
  `hardware/<module>/fab/` are byte-exact (`-text`) and are the only Gerbers committed.
* If generator scripts are used, they preserve hand-edited design intent and never overwrite the
  `.kicad_pro` file KiCad owns.
* Vendor datasheets live in `docs/datasheets/`, which is git-ignored; cite them in
  [references.md](references.md).
* Pin firmware dependency versions; record the board revision each build targets.
