# Nixie module — fabrication outputs

Generated 2026-11-11 from `hardware/nixie/nixie.kicad_pcb` (KiCad 10.0.5) as committed together
with this README revision (164 × 53 mm layout with two mid-edge M3 holes; HV5622 chain readback
to the RP2040 and switched 12 V sense added), byte for byte;
**not yet ordered**. Plain RS-274X Gerbers (no X2 attributes) and separate plated and unplated
Excellon drill files.

To order, zip the ten files from `nixie-F_Cu.gtl` to `nixie-NPTH.drl` in the table below and
upload the zip (zips are git-ignored).

| File | Content |
|---|---|
| `nixie-F_Cu.gtl`, `nixie-B_Cu.gbl` | Copper, side A (top, all parts but the tubes) / side B (tubes) |
| `nixie-F_Mask.gts`, `nixie-B_Mask.gbs` | Solder mask, top / bottom |
| `nixie-F_Silkscreen.gto`, `nixie-B_Silkscreen.gbo` | Silkscreen (mask openings subtracted); the bottom one carries the tube outlines |
| `nixie-F_Paste.gtp` | Top paste: needed only if a stencil is ordered (no SMD parts on side B) |
| `nixie-Edge_Cuts.gm1` | Board outline |
| `nixie-PTH.drl`, `nixie-NPTH.drl` | Excellon, mm: plated (649 holes) and unplated (20 holes: 14 × 1.6 mm cable-tie and 6 × 3.2 mm mounting holes) |
| `nixie-PTH-drl_map.pdf`, `nixie-NPTH-drl_map.pdf`, `nixie-drill_report.txt`, `nixie-job.gbrjob` | Drill maps, drill summary and Gerber job file (not uploaded) |

## Order settings

| Setting | Value |
|---|---|
| Layers | 2 |
| Size | 164 × 53 mm |
| Material / thickness | FR-4, 1.6 mm |
| Copper | 1 oz outer |
| Min track / spacing | 6 / 6 mil ordered; the board's minimum track is 0.16 mm and minimum spacing 0.2 mm (cathode nets 0.25 mm, HV nets 1.25 mm by the design rules; the IN-14 footprint's own pads 1.156 mm) |
| Min hole | 0.30 mm (signal vias 0.6 / 0.3 mm); GND stitching vias 0.7 / 0.35 mm, cathode and HV vias 0.8 / 0.4 mm |
| Surface finish | ENIG recommended (flat pads for the 0.8 mm-pitch PQFP-44 HV5622s); lead-free HASL also works |
| Solder mask / silkscreen | Any colour. The board takes no clearance credit for solder mask |

The board meets PCBWay's published standard capabilities
(https://www.pcbway.com/capabilities.html, as checked 2026-10-08 for the dekatron board):
- 0.1 mm minimum track and spacing;
- 0.15 mm minimum drill, with an extra charge only below 0.2 mm;
- 0.15 mm minimum annular ring (here the thinnest is 0.15 mm, at the vias; pads 0.3 mm and up);
- legend text at least 0.8 mm high with a 0.15 mm stroke (here 0.8-1.0 mm text, 0.15 mm stroke).

At generation: KiCad DRC at all severities 0 violations, 0 unconnected pads, 0 footprint errors,
with schematic parity; every reference is on the silkscreen except R306 and R314 (no free spot; on
the Fab layer). These files are committed byte-exact; do not edit them by hand —
regenerate from the board (`docs/development.md`).
