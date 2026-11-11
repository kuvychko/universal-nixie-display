# Development

Toolchains, workflow and generated-file policy. Commands run from the repository root.

## Toolchains

| Area | Tool | Notes |
|---|---|---|
| Schematics/PCB | KiCad 10 | One project per board under `hardware/<module>/`; shared library in `hardware/lib/` |
| Simulation | ngspice-45 (shipped with Qucs-S in `C:/Simulators/Qucs-S/bin`); KiCad 10's built-in ngspice for schematic-level checks | Benches and summarised results in `hardware/dekatron/simulation/` |
| ESP32 firmware | PlatformIO, Arduino framework | `firmware/display/`; pin platform and library versions |
| RP2040 firmware | _open_ (PlatformIO arduino-pico or Pico SDK) | `firmware/dekatron/`, `firmware/nixie/`. The Gate 2 bring-up tool `firmware/dekatron-bringup/` uses arduino-pico on PlatformIO; it does not settle this |
| Tools/tests | Python via `uv` | `tools/`, `tests/`; bench tools need `uv run --group bench` |
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
(`hardware/dekatron/bom.csv`) from the values in `docs/hardware.md`. Manufacturer and MPN come from
the frozen `ORDERED_PARTS` table (the 2026-10-08 Mouser order) wherever a reference is listed
there; the generator fails if a listed reference is missing from the sheets. The sheets are drawn as
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

### ERC baseline (all sheets: power, tube, mcu; 2026-10-07)

`kicad-cli sch erc --severity-all hardware/dekatron/dekatron.kicad_sch`: **4 violations, expected:**
`pin_to_pin` power output to power output, the LP2951 output driving the LM5156 VCC pin in
BIAS = VCC mode (intentional, D2); and three `pin_to_pin` open collector to power output, the
unused LM66100 ST pins tied to GND as their datasheet asks (U102-U104, 2026-10-07). Every inter-sheet global label connects.

### Nixie board generator

`tools/gen_nixie_schematics.py` writes `hardware/nixie/` (power, logic and tubes sheets, project
symbols HV5622 / IN-14 / RP2040-Zero, the RP2040-Zero footprint, `bom.csv`). It
imports the dekatron generator's core and points its project globals at the Nixie project. The
sheets use the label-stub style (`Sheet.part`); values not yet sourced are written `_open_`.
`hardware/nixie/lib/nixie.pretty/IN-14.kicad_mod` is maintained by hand.

```
python tools/gen_nixie_schematics.py
kicad-cli sch erc --severity-all --exit-code-violations hardware/nixie/nixie.kicad_sch
```

ERC baseline (2026-10-26): **0 violations.**

### Project footprint

`hardware/dekatron/lib/dekatron.pretty/RP2040-Zero_Castellated.kicad_mod` (generated) carries the
module: pads at Waveshare's castellation positions (from their STEP model), extended ~1.4 mm past
the module edge for hand soldering. Check it with `kicad-cli fp export svg` after changes, and
print it 1:1 against a real module before ordering boards (bring-up step 0).

### PCB (Phase 1C): placement and scripted routing

100 × 85 mm, 2 layers, made by PCBWay (ordered at 6/6 mil trace/space; the board's minimum is
0.2 mm track and clearance, 0.3 mm drill, 0.15 mm annular ring; the D13 class rules in
`dekatron.kicad_dru`). The board is generated, so re-run the whole chain after
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
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/silk.py hardware/dekatron/dekatron.kicad_pcb
```

The paths are a Windows KiCad 10 install. Elsewhere, run the scripts with KiCad's own Python
and set `KICAD_CLI` and `KICAD_FOOTPRINTS` for `gen_pcb.py` (or pass `--kicad-share` to
`gen_schematics.py`).

About 35 minutes on this machine (the routing loop is ~4 min per pass; this board converged on
pass 8). What the pieces do:

* `gen_pcb.py` places by hand where it matters (`ANCHOR`: edges, connectors, the tripler ladder,
  the HV dividers and anode resistors, the LM5156 and its neighbours, the RP2040-Zero and its
  power parts) and constructively for the rest, inside per-group regions. `KEEPOUT` reserves
  fan-out room around the LM5156; the LM5156 is rotated 90° so its signal row faces the
  comparators and the HV divider and its drive row faces Q102. Its exposed pad gets six 0.3 mm
  vias as extra pads (the library's thermal-via variant uses 0.2 mm; the board keeps every drill at 0.3 mm or more),
  which is why DRC reports U106 as differing from the library.
* `route_pcb.py` is a two-layer A* router on a 0.1 mm grid with the D13 class clearances. It has
  no rip-up, so order is the lever: the LM5156's fine-pitch nets first, in an order that keeps
  each pin's escape open; each LM5156 signal pin gets a reserved 1 mm escape stub; failed nets
  are promoted in the next pass (`route_loop.sh`). Raster margins: 0.075 mm (tracks), 0.12 mm
  (vias), 0.08 mm within 0.4 mm of the LM5156 pins, plus 0.03 mm against other nets' pads (a
  diagonal track grazing a pad corner came out 0.175 mm against the 0.2 mm rule) and 0.05 mm
  against other nets' tracks for every net outside the LM5156 pin group (a 1 mm VIN_PROT end came
  out 0.153 mm from a 0.25 mm PGOOD diagonal; applied to the pin group too, it walls PGOOD in at
  the pins). `pcb_io.py apply` now and then fails with a pcbnew SWIG `AttributeError`; re-run it
  on a fresh copy of the placed board. Vias also keep
  0.25 mm hole-to-hole from every plated hole, not only the unplated ones. The GND pour counts as
  connected copper on the bottom layer only, so a top-side GND pad gets a stitching via.
* Fixed copper laid before routing (`BRIDGES`, `GND_ESCAPES` in `route_pcb.py`): each LM66100's
  CE-to-VOUT connection runs under the package body (pin 3 in to the centreline, along it, out to
  pin 6; 0.2 mm wide, 0.225 mm from pins 2 and 5), and its GND pin 2 and ST pin 5 each get a short
  track out to a GND via 0.65 mm past the pad (direction searched for 0.3 mm from other pads).
  Routed around the package, CE-to-VOUT walled in the GND pins, and at 0.65 mm pitch the pour
  cannot reach a middle pin. `gen_pcb.py` anchors R301 and C108 0.6 mm clear of two of those
  vias. D301 (BAT54S below the RP2040-Zero) gets one too, and is anchored rotated so its GND pin
  faces the open pour: in the other orientation that pin sat in a pour pocket walled in on both
  layers. Escape vias stay out of the no-via area under the module.
* `pcb_io.py apply` writes the tracks, fills the pours and adds GND stitching vias on a 2.5 mm
  grid wherever both pours have solid copper; the `--repair` pass then re-routes GND against
  the real main fill, so pour islands that only touch a pad get connected. Repair links are
  0.3 mm, not GND's 0.5 mm: a pocket around R116 was only reachable between two vias.
* `silk.py` re-places the reference designators: around each courtyard, clear of pads, silk,
  other references and the board edge, preferring spots not under another part; 1.0 mm text,
  0.8 mm (the board minimum) where it is tight, never under a 0.15 mm stroke (PCBWay's minimum). It only moves text, so it can be re-run on its own.
  Mounting-hole references are hidden; on this board C108, C303, L101 and R214 have no legal
  spot and are labelled on the Fab layer only.

### Nixie PCB: placement and Freerouting

```sh
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/gen_nixie_pcb.py         # place, write nixie.kicad_pcb + .kicad_dru
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/freeroute_nixie.py 100 --hv-from build/old_nixie.kicad_pcb   # DSN -> Freerouting -> SES, zone fill, DRC
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/silk.py hardware/nixie/nixie.kicad_pcb
```

* `gen_nixie_pcb.py` follows `gen_pcb.py`: anchors for the tubes (B.Cu, flipped), anode
  resistors, HV5622s and their bypass caps, the RP2040-Zero, the HV module landing and the harness
  pads; the constructive placer for the rest.
* `freeroute_nixie.py` drives **Freerouting 2.5.0** headless (user install in
  `%LOCALAPPDATA%/freerouting`, own Java runtime; set `FREEROUTING` elsewhere). Clearances come from
  the net classes in `nixie.kicad_pro`, which the DSN export carries; no custom DRC rules are needed
  for routing (the Nixie classes are plain clearances, hardware.md "Clearance rules"); the one
  custom rule in `nixie.kicad_dru` only lets KiCad DRC accept the IN-14's own 1.156 mm pad gaps. Logs and
  intermediate files go to `build/` (ignored).
* KiCad 10.0.5 quirks handled in the scripts: `pcbnew.SaveBoard()` rewrites `nixie.kicad_pro` from
  the board's own net settings, so `gen_nixie_pcb.py` sets the net classes on the board
  (`NETCLASSES`); `pcbnew.ImportSpecctraSES()` returns False on Freerouting 2.5.0 sessions, so
  `freeroute_nixie.py` reads the session itself. GND is routed as tracks (the pours are removed
  for the export and filled afterwards); Freerouting's neck-downs under 0.16 mm are widened to
  0.16 mm, the board's DRC minimum (fab 0.1524 mm). Tie holes, mounting holes and a 0.6 mm edge
  band are keep-out rule areas, since board-only NPTH footprints do not reach the DSN. The DSN
  export turns every rule area into a full keepout, so fill-only rule areas (no pour in the tube
  lead rings) are removed for the export along with the pours.
* Freerouting vs KiCad DRC: its rounding left 2-3 µm clearance slivers, and widening its
  neck-downs to 0.16 mm takes up to 17.5 µm a side, so every DSN clearance gets +20 µm
  (`CLEARANCE_MARGIN_UM`; +10 left slivers, +25 left a GND connection unrouted);
  it spaces vias of every class by the Default clearance, so the DSN gets a `via_via` rule at the
  NCATH clearance. GND pads left with one thermal spoke (KiCad wants two) are read from the DRC
  report and switched to a solid connection, then the zones are refilled.
* `tools/route_stats.py <board>` prints track length per net class and layer, and via counts, to
  compare placements. Freerouting results vary by a few percent between runs of the same input.
* **First routing (2026-11-06):** 150 × 80 mm placement, all nets routed by Freerouting (0
  unrouted, 0 violations), KiCad DRC 0 errors and 0 unconnected pads with schematic parity, after
  `silk.py` (C309, TP104, TP105 references hidden). Moving the HV5622s forward to 25 mm and
  assigning their outputs from the geometry (hardware.md, `HV_MAP`) cut the cathode tracks
  (`NCATH`) from 2444 mm and 73 vias to ≈ 1300 mm and ≈ 57-61 vias. Shrunk to 150 × 70 mm
  (logic block 10 mm forward, 2026-11-07): still 0 errors, 0 unconnected. GND pours then
  extended to the whole board on both layers, except inside the tube lead rings, and stitched
  with targeted vias (`targeted_stitch()`, `TARGET_R` 3 mm around SMD GND pads and signal vias)
  plus `pcb_io.stitch()` (the dekatron board's 2.5 mm grid) after the first fill: ≈ 515 vias,
  0 errors, 0 unconnected. Re-laid out at 164 × 53 mm (2026-11-10, user: RP2040-Zero right of tube 6,
  the 12 V switch and level shifter in the gaps between the drivers, two mid-edge M3 holes). The
  first try at 50 mm deep left `NIX_HV` unrouted (the pocket parts blocked its path past the
  anode resistors); a part-free HV lane behind the drivers (y 35-39) fixed it. Result: `NCATH`
  1383 mm / 58 vias, `NHV` 193 mm / 0 vias, other nets 3033 mm / 378 vias including stitching
  (4461 mm / 668 at 150 × 70); DRC at all severities 0 with schematic parity after `silk.py`
  (R306 reference hidden).
* Readback divider and 12 V sense added (2026-11-11, five parts): left to itself, Freerouting
  then took `NIX_HV` 280-390 mm with 2-4 vias on three runs, whatever the new parts' region. So
  `--hv-from` copies the previous routing's `NIX_HV` copper (same pad positions) in as locked
  tracks, which the DSN exports as `(type fix)` wiring: save the board first
  (`git show HEAD:hardware/nixie/nixie.kicad_pcb > build/old_nixie.kicad_pcb`), then
  `gen_nixie_pcb.py`, then route. The re-route also showed the stitching starved: the first fill
  removed every pour island no GND pad or track reached, so the stitcher never saw them (82 vias).
  The first fill now keeps islands, the stitch runs, the refill removes islands, and vias left on
  bare board are dropped until stable. TP302 is anchored at (146, 8): placed freely it sat at the
  right edge with no room for its reference. Result: `NHV` 193 mm / 0 vias (kept), `NCATH`
  1314 mm / 64 vias, other signal nets 3172 mm / 84 vias, 368 GND vias; DRC at all severities 0
  with schematic parity after `silk.py` (R306, R314 references hidden: Fab layer only).

### Fab outputs

PCBWay Gerbers (plain RS-274X, `--no-x2`) and separate plated / unplated drill files into
`hardware/dekatron/fab/`, then zip the ten files its README lists for upload (the zip is
git-ignored):

```
kicad-cli pcb export gerbers --check-zones --subtract-soldermask --no-x2 -l F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,F.Paste,Edge.Cuts -o hardware/dekatron/fab/ hardware/dekatron/dekatron.kicad_pcb
kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-separate-th --generate-map --map-format pdf --generate-report --report-path hardware/dekatron/fab/dekatron-drill_report.txt -o hardware/dekatron/fab/ hardware/dekatron/dekatron.kicad_pcb
```

The Nixie module the same way: replace `dekatron` by `nixie` in both commands
(`hardware/nixie/fab/`, generated 2026-11-11, not yet ordered).

Regenerate only for a board change that will be ordered; the files are a record of what was sent.

### Readable exports

A schematic PDF and top/bottom 3D renders in `hardware/dekatron/docs/`, linked from the README so
the design can be read without KiCad. Regenerate them whenever the fab outputs are regenerated:

```
kicad-cli sch export pdf -o hardware/dekatron/docs/dekatron-schematic.pdf hardware/dekatron/dekatron.kicad_sch
kicad-cli pcb render --side top --quality high -w 1600 -h 1200 --background opaque -o hardware/dekatron/docs/dekatron-pcb-top.png hardware/dekatron/dekatron.kicad_pcb
kicad-cli pcb render --side bottom --quality high -w 1600 -h 1200 --background opaque -o hardware/dekatron/docs/dekatron-pcb-bottom.png hardware/dekatron/dekatron.kicad_pcb
```

The Nixie board the same way into `hardware/nixie/docs/` (`nixie-schematic.pdf`,
`nixie-pcb-top.png`, `nixie-pcb-bottom.png`), but render at `-w 2000 -h 800 --zoom 2.4` so the
long, narrow board fills the frame.

### DRC baseline (2026-10-08, frozen BOM: TPS54302, IPD70R1K4P7S, tantalum C301, 0805 feedback pair; routing converged on pass 5)

`kicad-cli pcb drc --severity-all --schematic-parity hardware/dekatron/dekatron.kicad_pcb`:
**2 violations, expected:** the U106 library mismatch (thermal vias above) and one
`starved_thermal` (R111 GND pad 2 reaches the front pour with one spoke instead of two; it is
connected). 0 unconnected, 0 clearance, 0 silkscreen, 0 schematic parity. Which pad shows a
starved thermal can change after a re-route.

## Simulation

Benches are plain ngspice netlists (`.cir`) in `hardware/dekatron/simulation/`, so they run in
batch without a GUI and diff cleanly; Qucs-S is used for interactive exploration. Run a bench
from its directory, so ngspice picks up `.spiceinit` (PSpice compatibility for the vendor models;
see the [simulation README](../hardware/dekatron/simulation/README.md#running)):

```
cd hardware/dekatron/simulation
"C:/Simulators/Qucs-S/bin/ngspice_con.exe" -b <bench>.cir
```

Each bench states its model sources and limitations in its header. Commit summarised results
(tables, plots) rather than `.raw` data. A simplified tube model can support circuit analysis but
cannot establish glow transfer, ignition or homing (plan §9).

## Companion site

MkDocs Material, source in `website/`, configuration in `mkdocs.yml`; plan in
[companion_site.md](companion_site.md). Preview, then build and check as CI does:

```
uv run --group docs mkdocs serve
uv run --group docs mkdocs build --strict
uv run python tools/check_site.py
```

The strict build fails on a broken internal link or anchor. `tools/check_site.py` checks the built
HTML for root-relative links (they break under the Pages subpath), missing alt text and missing
images, and lists external links for a manual check. `.github/workflows/site.yml` runs both on
every push; `deploy-site.yml` publishes the site to GitHub Pages on every push to `main` that
touches it (`website/`, `mkdocs.yml`, the lock file or the checker), and can be run by hand.
Engineering documents are linked on GitHub rather than copied into the site.

## Generated-file policy

* `.gitattributes` pins text files to LF, matching KiCad. Released fab files under
  `hardware/<module>/fab/` are byte-exact (`-text`) and are the only Gerbers committed.
* If generator scripts are used, they preserve hand-edited design intent and never overwrite the
  `.kicad_pro` file KiCad owns.
* Vendor datasheets live in `docs/datasheets/`, which is git-ignored; cite them in
  [references.md](references.md).
* Pin firmware dependency versions; record the board revision each build targets.
