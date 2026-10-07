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

### PCB (Phase 1C): placement and scripted routing

100 × 85 mm, 2 layers, OSH Park rules (6 mil trace/space, 10 mil drill, 5 mil annular ring; the
D13 class rules in `dekatron.kicad_dru`). The board is generated, so re-run the whole chain after
a schematic change (the board script reads the exported netlist):

```
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/gen_pcb.py             # place, write .kicad_pcb + .kicad_dru
cp hardware/dekatron/dekatron.kicad_pcb build/placed.kicad_pcb
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump hardware/dekatron/dekatron.kicad_pcb build/geom.json
sh tools/route_loop.sh 10                                                 # route; failed nets go first next pass
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/dekatron/dekatron.kicad_pcb build/routes.json
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump hardware/dekatron/dekatron.kicad_pcb build/geom_filled.json
uv run tools/route_pcb.py build/geom_filled.json build/routes_gnd.json --repair build/routes.json
cp build/placed.kicad_pcb hardware/dekatron/dekatron.kicad_pcb
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/dekatron/dekatron.kicad_pcb build/routes_gnd.json
```

About 35 minutes on this machine (the routing loop is ~4 min per pass; this board converged on
pass 8). What the pieces do:

* `gen_pcb.py` places by hand where it matters (`ANCHOR`: edges, connectors, the tripler ladder,
  the HV dividers and anode resistors, the LM5156 and its neighbours, the RP2040-Zero and its
  power parts) and constructively for the rest, inside per-group regions. `KEEPOUT` reserves
  fan-out room around the LM5156; the LM5156 is rotated 90° so its signal row faces the
  comparators and the HV divider and its drive row faces Q102. Its exposed pad gets six 0.3 mm
  vias as extra pads (the library's thermal-via variant uses 0.2 mm, below OSH Park's minimum),
  which is why DRC reports U106 as differing from the library.
* `route_pcb.py` is a two-layer A* router on a 0.1 mm grid with the D13 class clearances. It has
  no rip-up, so order is the lever: the LM5156's fine-pitch nets first, in an order that keeps
  each pin's escape open; each LM5156 signal pin gets a reserved 1 mm escape stub; failed nets
  are promoted in the next pass (`route_loop.sh`). Raster margins: 0.075 mm (tracks), 0.12 mm
  (vias), 0.08 mm within 0.4 mm of the LM5156 pins. The GND pour counts as connected copper on
  the bottom layer only, so a top-side GND pad gets a stitching via.
* `pcb_io.py apply` writes the tracks, fills the pours and adds GND stitching vias on a 2.5 mm
  grid wherever both pours have solid copper; the `--repair` pass then re-routes GND against
  the real main fill, so pour islands that only touch a pad get connected.

### DRC baseline (2026-10-07)

`kicad-cli pcb drc --severity-all --schematic-parity hardware/dekatron/dekatron.kicad_pcb`:
**0 unconnected, 0 clearance, 0 schematic parity.** Remaining: 184 silkscreen warnings
(reference text over pads or overlapping, clipped by the fab; tidy before ordering), the
expected U106 library mismatch (thermal vias above), and an occasional starved-thermal warning.

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
