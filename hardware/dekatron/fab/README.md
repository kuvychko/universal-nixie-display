# Dekatron controller/PSU — fabrication outputs

Generated from `hardware/dekatron/dekatron.kicad_pcb` (KiCad 10.0.5) at the commit that adds
this folder. Target: OSH Park 2-layer (1.6 mm FR-4, 1 oz copper, ENIG). Board 100 × 85 mm.

To order, zip the nine files from `dekatron-F_Cu.gtl` to `dekatron.drl` in the table below
and upload the zip (zips are git-ignored).

| File | Content |
|---|---|
| `dekatron-F_Cu.gtl`, `dekatron-B_Cu.gbl` | Copper, top / bottom |
| `dekatron-F_Mask.gts`, `dekatron-B_Mask.gbs` | Solder mask, top / bottom |
| `dekatron-F_Silkscreen.gto`, `dekatron-B_Silkscreen.gbo` | Silkscreen (mask openings subtracted; the bottom one is empty) |
| `dekatron-F_Paste.gtp` | Top paste, for a stencil; the fab ignores it |
| `dekatron-Edge_Cuts.gm1` | Board outline |
| `dekatron.drl` | Excellon, mm, plated and unplated holes in one file |
| `dekatron-job.gbrjob`, `dekatron-drill_report.txt` | Gerber job file and drill summary (not uploaded) |

Holes: smallest 0.30 mm (U106 thermal vias; routing vias 0.35 mm), above OSH Park's 0.254 mm.
Unplated: 1.6 mm harness cable-tie holes, 3.2 mm mounting holes.

At generation: DRC 0 unconnected, 0 clearance, 0 silkscreen, 0 schematic parity; two expected
findings (U106 differs from its library footprint: added 0.3 mm thermal vias; R111 GND pad has a
one-spoke thermal to the front pour, still connected). Regenerated 2026-10-08 for the frozen
BOM (Mouser order `hardware/dekatron/Cart_Oct08_0432PM.xls`): TPS54302 buck (pin-compatible with
the TPS54202), IPD70R1K4P7S HV switch (same DPAK), F91 tantalum C301 (EIA 3216-18 polarised
footprint), E24 feedback dividers (2 × 3.0k 0805 R130/R144, 6.2k R140), WIMA MKS4 film capacitors
(18 × 8 mm footprint) and the 6.3 × 7.7 mm C101, then a full re-route; regenerated again the same
day with the 0.8 mm references at a 0.15 mm stroke (PCBWay's minimum), copper unchanged. Earlier
sets the same day and 2026-10-07 were not ordered. The PCBWay set of the same board is in
`pcbway/`. See
`docs/development.md` for the regeneration commands. These files are committed byte-exact; do
not edit them by hand — regenerate from the board.
