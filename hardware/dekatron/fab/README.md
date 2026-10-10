# Dekatron controller/PSU — fabrication outputs

The files ordered from PCBWay on 2026-10-09: generated from `hardware/dekatron/dekatron.kicad_pcb`
(KiCad 10.0.5) at commit f4fd414, byte for byte. Plain RS-274X Gerbers (no X2 attributes) and
separate plated and unplated Excellon drill files.

To order, zip the ten files from `dekatron-F_Cu.gtl` to `dekatron-NPTH.drl` in the table below and
upload the zip (zips are git-ignored).

| File | Content |
|---|---|
| `dekatron-F_Cu.gtl`, `dekatron-B_Cu.gbl` | Copper, top / bottom |
| `dekatron-F_Mask.gts`, `dekatron-B_Mask.gbs` | Solder mask, top / bottom |
| `dekatron-F_Silkscreen.gto`, `dekatron-B_Silkscreen.gbo` | Silkscreen (mask openings subtracted; the bottom one is empty) |
| `dekatron-F_Paste.gtp` | Top paste: needed only if a stencil is ordered |
| `dekatron-Edge_Cuts.gm1` | Board outline |
| `dekatron-PTH.drl`, `dekatron-NPTH.drl` | Excellon, mm: plated (463 holes) and unplated (16 holes: 1.6 mm cable-tie and 3.2 mm mounting holes) |
| `dekatron-PTH-drl_map.pdf`, `dekatron-NPTH-drl_map.pdf`, `dekatron-drill_report.txt`, `dekatron-job.gbrjob` | Drill maps, drill summary and Gerber job file (not uploaded) |

## Order settings

| Setting | Value |
|---|---|
| Layers | 2 |
| Size | 100 × 85 mm |
| Material / thickness | FR-4, 1.6 mm |
| Copper | 1 oz outer |
| Min track / spacing | 6 / 6 mil ordered; the board's minimum is 0.2 mm / 0.2 mm (high-voltage nets are spaced 0.8-3.0 mm by the design rules) |
| Min hole | 0.30 mm (U106 thermal vias); routing vias 0.35 mm drill / 0.7 mm pad |
| Surface finish | ENIG recommended (flat pads for the 0.65 mm-pitch HTSSOP U106); lead-free HASL also works |
| Solder mask / silkscreen | Any colour. The board takes no clearance credit for solder mask |

The board meets PCBWay's published standard capabilities
(https://www.pcbway.com/capabilities.html, checked 2026-10-08):
- 0.1 mm minimum track and spacing;
- 0.15 mm minimum drill, with an extra charge only below 0.2 mm;
- 0.15 mm minimum annular ring (here the thinnest is 0.15 mm, at U106's 0.6 / 0.3 mm thermal vias; routing vias 0.175 mm);
- legend text at least 0.8 mm high with a 0.15 mm stroke (here 0.8-1.0 mm text, 0.15 mm stroke).

Footprint outlines on the silkscreen are the KiCad library's 0.12 mm lines.

At generation: DRC 0 unconnected, 0 clearance, 0 silkscreen, 0 schematic parity; two expected
findings (U106 differs from its library footprint: added 0.3 mm thermal vias; R111 GND pad has a
one-spoke thermal to the front pour, still connected). These files are committed byte-exact; do
not edit them by hand — regenerate from the board (`docs/development.md`).
