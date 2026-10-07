#!/usr/bin/env python3
"""
Bootstrap PCB generator for the dekatron controller/PSU (Phase 1C). Run with KiCad's Python:

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/gen_pcb.py

Writes hardware/dekatron/dekatron.kicad_pcb (unrouted) and dekatron.kicad_dru:
  * board outline, four M3 mounting holes;
  * every schematic footprint, with pad nets from the exported netlist (ratsnest shows at once);
  * anchor parts placed by hand (edges, module, ICs, power devices, tripler column); the remaining
    parts by a constructive placer: each goes to the free spot nearest the centroid of the pads it
    shares nets with, inside its functional region, with its courtyard inflated by its net class's
    clearance so HV parts keep their distance;
  * GND pours on both layers over the low-voltage regions only; a no-via rule area under the
    RP2040-Zero (its underside carries pads);
  * .kicad_dru clearance rules between the D13 net classes (OSH Park 2-layer, 6/6 mil base).

Like the nanovolt-divider generator this is a bootstrap: once the board is edited in KiCad the
.kicad_pcb is the source of truth.
"""
import csv
import math
import os
import subprocess
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware", "dekatron")
BOARD = os.path.join(HW, "dekatron.kicad_pcb")
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
SHARE = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
PROJ_LIB = os.path.join(HW, "lib", "dekatron.pretty")

OX, OY = 50.0, 50.0           # board origin on the KiCad sheet
W, H = 120.0, 100.0           # second-pass outline; shrink after routing

# --------------------------------------------------------------------------------------
# Net classes (docs/hardware.md D13): clearance to any other class, mm
# --------------------------------------------------------------------------------------
CLASS_CLR = {"HV": 3.0, "VB": 1.5, "HVSTR": 1.5, "BIAS": 0.8, "Default": 0.2}


def net_class(name):
    import fnmatch
    pats = [("HV", "HV"), ("HV", "*HV_STACK"), ("HV", "*TRP_P1"), ("HV", "*TRP_N2"), ("HV", "*TRP_P2"),
            ("HV", "*ANODE"), ("VB", "*/V_B"), ("VB", "*/V_BT"), ("VB", "V_B_BIAS"), ("VB", "*/SW"),
            ("VB", "*/TRP_PUMP"), ("HVSTR", "*/STR_*"), ("BIAS", "*/GPLUS"), ("BIAS", "*/RTN"),
            ("BIAS", "*/TUBE_*"), ("BIAS", "*/NDX_C")]
    for c, p in pats:
        if fnmatch.fnmatchcase(name, p):
            return c
    return "Default"


DRU = """(version 1)
# Clearances between the D13 net classes (docs/hardware.md). The board is uncoated: no credit for
# solder mask. The project's net classes carry only the 0.2 mm base clearance; these pair rules set
# the rest (later rules take precedence when several match).
(rule "BIAS to logic"
  (condition "(A.NetClass == 'BIAS' && B.NetClass == 'Default') || (B.NetClass == 'BIAS' && A.NetClass == 'Default')")
  (constraint clearance (min 0.8mm)))
(rule "BIAS to BIAS"
  (condition "A.NetClass == 'BIAS' && B.NetClass == 'BIAS'")
  (constraint clearance (min 0.8mm)))
(rule "VB / HVSTR to anything below HV"
  (condition "(A.NetClass == 'VB' || A.NetClass == 'HVSTR') && B.NetClass != 'HV'")
  (constraint clearance (min 1.5mm)))
(rule "HV to bias and logic"
  (condition "A.NetClass == 'HV' && (B.NetClass == 'Default' || B.NetClass == 'BIAS')")
  (constraint clearance (min 3.0mm)))
(rule "HV to HV, VB, HVSTR (adjacent tripler / string nodes, <= ~300 V apart)"
  (condition "A.NetClass == 'HV' && (B.NetClass == 'HV' || B.NetClass == 'VB' || B.NetClass == 'HVSTR')")
  (constraint clearance (min 1.5mm)))
(rule "HV edge clearance"
  (condition "A.NetClass == 'HV'")
  (constraint edge_clearance (min 3.0mm)))
(rule "OSH Park minimum"
  (constraint track_width (min 0.1524mm))
  (constraint hole_size (min 0.33mm))
  (constraint annular_width (min 0.1778mm)))
"""

# --------------------------------------------------------------------------------------
# Regions (x0, y0, x1, y1) in board mm, origin top-left
# --------------------------------------------------------------------------------------
REG = {
    "IN":    (1, 7, 45, 37),
    "BUCK":  (8, 37, 45, 60),
    "MCU":   (1, 60, 49, 93),
    "CTRL":  (40, 16, 79, 40),
    "SW":    (45, 40, 80, 60),
    "HV":    (80, 1, 119, 75),
    "TUBE":  (49, 60, 89, 92),
    "HARN":  (82, 75, 119, 92),
}

GROUP = {}
for refs, g in (
    ("J101 F101 Q101 R101 D101 D102 C101 C102 TP101 TP102 F102 J102", "IN"),
    ("U101 C103 C104 R102 R103 C105 L101 C106 C107 R104 R105 C108 R106 LK2 TP103 U102 U103 U104 C109 C110 C111 J302", "BUCK"),
    ("LK1 C112 U105 R107 R108 C113 TP104 U106 C114 C115 R109 R110 JP101 R111 R112 C116 R113 C117 C118 R114 R115 R116 "
     "U107 C128 R140 C127 U108 C130 R143 C129 R130 R135", "CTRL"),
    ("Q102 R117 R118 C119 C120 C121 L102 D103 TP105 TP107 TP106 LK5 R119 R120 R141 R142", "SW"),
    ("R121 C122 C123 C124 C125 C126 D104 D105 D106 D107 R122 R123 R124 R125 R126 R127 R128 R129 R131 R132 R133 R134 "
     "R136 R137 R138 R139 LK3 LK4 TP108 R145 R146 R147 R148 R149 R150 R215 R216 R217 J201", "HV"),
    ("R201 R218 D201 D202 C201 C202 R202 R203 R204 TP201 TP202 TP206 R205 R206 R207 R208 R209 R210 Q201 Q202 TP203 "
     "TP204 Q203 R211 R212 R213 R214 C204 TP205 J202", "TUBE"),
    ("J203 LK6 LK7 LK8 LK9 LK10 LK11 LK12 LK13 LK14", "HARN"),
    ("U301 C301 C302 TP301 TP302 TP303 TP304 TP305 TP306 TP307 TP308 TP309 TP310 TP311 R301 R302 D301 D302 D303 "
     "D304 C303 C304 C305 R303 R304 TP312 TP313 J301 LK15", "MCU"),
):
    for r in refs.split():
        GROUP[r] = g

# Anchors: ref -> (x, y, rotation degrees). Footprint origins, board coordinates.
# Harness landings are plain wire-pad rows along an edge; a cable-tie anchor sits 4.5 mm inboard (TIES).
ANCHOR = {
    "J101": (9.5, 3.0, 0), "J102": (21.5, 3.0, 0),                    # top edge
    "J302": (3.0, 58.0, 90),                                          # left edge (pads run upward)
    "J301": (28.0, 97.0, 0), "J202": (52.0, 97.0, 0),                 # bottom edge
    "J203": (82.0, 97.0, 0),
    "J201": (115.5, 66.0, 0),                                         # anode: right side, >= 4.2 mm from edge (HV)
    # RP2040-Zero, USB-C at the left board edge
    "U301": (13.5, 74.0, 90),
    # input power devices
    "Q101": (24.0, 22.0, 0), "C101": (38.0, 22.0, 90),
    # 5 V buck
    "U101": (17.0, 47.0, 0), "L101": (29.0, 47.0, 0),
    # controller cluster: LDO top-left of the controller, LM5156 centre
    "U105": (48.0, 10.0, 0), "U106": (60.0, 27.0, 0),
    # switch
    "L102": (51.0, 46.0, 0), "Q102": (68.0, 47.0, 0), "D103": (77.5, 54.0, 180),
    # tripler: film capacitors (origin = pad 1, pad 2 at +15 mm; rotation 180 puts pad 2 at -15 mm), oriented
    # so shared nodes face each other: N2 on the left (C126, C125), P1 on the right (C124, C123)
    "C126": (83.0, 22.0, 0),       # pad 1 N2 left, pad 2 HV_STACK right
    "C125": (98.0, 31.0, 180),     # pad 1 V_BT right, pad 2 N2 left
    "C124": (98.0, 40.0, 180),     # pad 1 P1 right, pad 2 P2 left
    "C123": (83.0, 49.0, 0),       # pad 1 PUMP left, pad 2 P1 right
    "C122": (83.0, 58.0, 0),       # pad 1 V_B left, pad 2 GND right
    # tripler diodes beside their nodes (SMA: pad 1 = cathode at -2 mm; rotation 90 puts it below, 270 above)
    "D107": (101.5, 26.5, 270),    # P2 -> HV_STACK: cathode up toward HV_STACK (98, 22)
    "D104": (101.5, 35.5, 90),     # V_BT (98, 31) -> P1 (98, 40): cathode down
    "D105": (101.5, 44.5, 270),    # P1 -> N2: anode at the P1 pads, cathode routed to N2 on the left
    "D106": (79.0, 35.5, 90),      # N2 (83, 31) -> P2 (83, 40): cathode down
    "LK3": (104.0, 58.0, 90),      # V_B -> V_BT
}

# Cable-tie anchors: (x, y, axis) two NPTH holes 4 mm apart, centred on the landing, inboard of it.
TIES = {"J101": (11.9, 7.5, "x"), "J102": (23.9, 7.5, "x"), "J302": (7.5, 46.0, "y"),
        "J301": (37.6, 92.5, "x"), "J202": (64.0, 92.5, "x"), "J203": (94.0, 92.5, "x"), "J201": (111.0, 66.0, "y")}

# Resistor strings placed as vertical chains (rotation 270: pad 1 on top, so each part's lower pad is
# the next part's upper net). (refs, x, y_top, pitch)
CHAINS = [
    # strings with a low-voltage end: horizontal rows along the top edge, HV end (pad 1) on the right,
    # low-voltage end reaching the controller at the left (rotation 180: pad 1 right)
    (["R126", "R127", "R128", "R129"], (100.5, 4.6), (-5.5, 0), 180),     # feedback  -> LM5156 FB
    (["R131", "R132", "R133", "R134"], (100.5, 8.8), (-5.5, 0), 180),     # HV monitor -> HV_SENSE
    (["R136", "R137", "R138", "R139"], (100.5, 13.0), (-5.5, 0), 180),    # HV OVP    -> TLV3011
    # strings ending at GND or the tube: vertical columns on the right (rotation 270: pad 1 on top)
    (["R122", "R123", "R124", "R125"], (108.0, 20.0), (0, 5.5), 270),     # bleeder
    (["R145", "R146", "R147", "R148", "R149", "R150"], (114.0, 20.0), (0, 5.2), 270),   # HV dummy (DNP)
    (["R215", "R216", "R217"], (108.0, 44.0), (0, 5.5), 270),             # anode string -> J201
    # V_b OVP divider top (2 x 1.0M): horizontal, low-voltage end toward U108 in the controller region
    (["R141", "R142"], (76.0, 38.0), (-5.5, 0), 180),
    # V_b bleeder (2 x 1.2M) to GND
    (["R119", "R120"], (79.5, 62.0), (0, 5.5), 270),
    # tube-sheet bias feed (2 x 20k) next to the V_B_BIAS link
    (["R201", "R218"], (84.0, 64.0), (0, 5.5), 270),
]


def export_netlist(path):
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", path,
                    os.path.join(HW, "dekatron.kicad_sch")], check=True, capture_output=True)


def parse_netlist(path):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("gs", os.path.join(ROOT, "tools", "gen_schematics.py"))
    gs = importlib.util.module_from_spec(spec)
    sys.modules["gs"] = gs
    spec.loader.exec_module(gs)
    t = gs.parse(open(path, encoding="utf8").read())
    comps = {}
    for c in gs.find_all(gs.find(t, "components"), "comp"):
        ref = gs.unq(gs.find(c, "ref")[1])
        comps[ref] = dict(value=gs.unq(gs.find(c, "value")[1]), footprint=gs.unq(gs.find(c, "footprint")[1]))
    pin_net = {}
    for n in gs.find_all(gs.find(t, "nets"), "net"):
        name = gs.unq(gs.find(n, "name")[1])
        for x in gs.find_all(n, "node"):
            pin_net[(gs.unq(gs.find(x, "ref")[1]), gs.unq(gs.find(x, "pin")[1]))] = name
    return comps, pin_net


def P(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    path = PROJ_LIB if lib == "dekatron" else os.path.join(SHARE, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise KeyError(fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def court_rect(fp, infl):
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
    return (pcbnew.ToMM(bb.GetLeft()) - OX - infl, pcbnew.ToMM(bb.GetTop()) - OY - infl,
            pcbnew.ToMM(bb.GetRight()) - OX + infl, pcbnew.ToMM(bb.GetBottom()) - OY + infl)


def overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def inside(r, reg):
    return r[0] >= reg[0] and r[1] >= reg[1] and r[2] <= reg[2] and r[3] <= reg[3]


SKIP_NETS = {"GND", "+5V", "+3V3", "VIN_PROT"}     # too many pins to steer placement


def main():
    netfile = os.path.join(ROOT, "build", "dekatron.net")
    os.makedirs(os.path.dirname(netfile), exist_ok=True)
    export_netlist(netfile)
    comps, pin_net = parse_netlist(netfile)
    missing = sorted(set(comps) - set(GROUP))
    if missing:
        raise SystemExit(f"parts without a placement group: {missing}")

    b = pcbnew.BOARD()
    nets = {}
    for name in sorted(set(pin_net.values())):
        ni = pcbnew.NETINFO_ITEM(b, name)
        b.Add(ni)
        nets[name] = ni

    fps, occ, placed_pads = {}, [], {}

    def infl_of(ref):
        cls = [net_class(n) for (r, _), n in pin_net.items() if r == ref]
        return max([CLASS_CLR[c] for c in cls] + [0.2]) * 0.5 + 0.15

    def make(ref):
        c = comps[ref]
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for pad in fp.Pads():
            n = pin_net.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(nets[n])
        return fp

    def commit(ref, fp):
        b.Add(fp)
        fps[ref] = fp
        occ.append((ref, court_rect(fp, infl_of(ref))))
        for pad in fp.Pads():
            n = pin_net.get((ref, pad.GetNumber()))
            if n and n not in SKIP_NETS:
                placed_pads.setdefault(n, []).append((pcbnew.ToMM(pad.GetPosition().x) - OX,
                                                      pcbnew.ToMM(pad.GetPosition().y) - OY))

    # anchors
    for ref, (x, y, rot) in ANCHOR.items():
        fp = make(ref)
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(P(x, y))
        commit(ref, fp)

    # cathode links: a horizontal row above the cathode landings
    for i, ref in enumerate(["LK6", "LK7", "LK8", "LK9", "LK10", "LK11", "LK12", "LK13", "LK14"]):
        fp = make(ref)
        fp.SetOrientationDegrees(270)
        fp.SetPosition(P(84.0 + i * 3.0, 86.0))
        commit(ref, fp)

    # explicit chains
    for refs, (x0, y0), (dx, dy), rot in CHAINS:
        for i, ref in enumerate(refs):
            fp = make(ref)
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(P(x0 + i * dx, y0 + i * dy))
            commit(ref, fp)

    # constructive placement, most-connected first
    def conn_count(ref):
        return sum(1 for (r, _), n in pin_net.items() if r == ref and n in placed_pads)
    todo = [r for r in comps if r not in fps]
    failed = []
    while todo:
        todo.sort(key=lambda r: -conn_count(r))
        ref = todo.pop(0)
        reg = REG[GROUP[ref]]
        tgt_pts = [pt for (r, _), n in pin_net.items() if r == ref and n in placed_pads for pt in placed_pads[n]]
        if tgt_pts:
            tx = sum(p[0] for p in tgt_pts) / len(tgt_pts)
            ty = sum(p[1] for p in tgt_pts) / len(tgt_pts)
        else:
            tx, ty = (reg[0] + reg[2]) / 2, (reg[1] + reg[3]) / 2
        tx = min(max(tx, reg[0] + 2), reg[2] - 2)
        ty = min(max(ty, reg[1] + 2), reg[3] - 2)
        fp = make(ref)
        best = None
        step = 0.5
        for ring in range(0, 160):
            cands = []
            if ring == 0:
                cands = [(0, 0)]
            else:
                for i in range(-ring, ring + 1):
                    cands += [(i, -ring), (i, ring), (-ring, i), (ring, i)]
            for dx, dy in cands:
                x, y = tx + dx * step, ty + dy * step
                for rot in (0, 90):
                    fp.SetOrientationDegrees(rot)
                    fp.SetPosition(P(x, y))
                    rr = court_rect(fp, infl_of(ref))
                    if not inside(court_rect(fp, 0), reg):
                        continue
                    if any(overlap(rr, o) for _, o in occ):
                        continue
                    d = math.hypot(x - tx, y - ty)
                    if best is None or d < best[0]:
                        best = (d, x, y, rot)
            if best is not None:
                break
        if best is None:
            failed.append(ref)
            continue
        _, x, y, rot = best
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(P(x, y))
        commit(ref, fp)

    # outline
    for (x1, y1, x2, y2) in ((0, 0, W, 0), (W, 0, W, H), (W, H, 0, H), (0, H, 0, 0)):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(x1, y1))
        s.SetEnd(P(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.1))
        b.Add(s)
    # cable-tie anchors: two NPTH holes per landing
    for ref, (x, y, axis) in TIES.items():
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(f"TIE_{ref}")
        fp.SetValue("cable tie")
        fp.Reference().SetVisible(False)
        for k, d in enumerate((-2.0, 2.0)):
            pad = pcbnew.PAD(fp)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            sz = pcbnew.FromMM(1.6)
            pad.SetSize(pcbnew.F_Cu, pcbnew.VECTOR2I(sz, sz))
            pad.SetDrillSize(pcbnew.VECTOR2I(sz, sz))
            pad.SetLayerSet(pad.UnplatedHoleMask())
            pad.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(d), 0) if axis == "x" else pcbnew.VECTOR2I(0, pcbnew.FromMM(d)))
            fp.Add(pad)
        fp.SetPosition(P(x, y))
        b.Add(fp)
        occ.append((f"TIE_{ref}", (x - 3.5, y - 1.5, x + 3.5, y + 1.5) if axis == "x" else (x - 1.5, y - 3.5, x + 1.5, y + 3.5)))

    # mounting holes (M3, non-plated)
    for i, (x, y) in enumerate(((4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4))):  # corners
        fp = load_fp("MountingHole:MountingHole_3.2mm_M3")
        fp.SetReference(f"H{i + 1}")
        fp.SetPosition(P(x, y))
        b.Add(fp)

    def zone(netname, layer, pts, name):
        z = pcbnew.ZONE(b)
        z.SetLayer(layer)
        z.SetNet(nets[netname])
        z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))
        z.SetLocalClearance(pcbnew.FromMM(0.3))
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        b.Add(z)

    # GND pours over the low-voltage regions only (input, buck, MCU, controller); none in HV/SW/tube
    lv = [(0.5, 0.5), (76, 0.5), (76, 16), (79, 16), (79, 40), (45, 40), (45, 60), (49, 60), (49, 99.5), (0.5, 99.5)]
    zone("GND", pcbnew.B_Cu, lv, "GND_B")
    zone("GND", pcbnew.F_Cu, lv, "GND_F")

    # no vias / no pour under the RP2040-Zero (pads on its underside)
    ra = pcbnew.ZONE(b)
    ra.SetIsRuleArea(True)
    ra.SetDoNotAllowVias(True)
    ra.SetDoNotAllowZoneFills(True)
    ra.SetDoNotAllowTracks(False)
    ra.SetDoNotAllowPads(False)
    ra.SetDoNotAllowFootprints(False)
    ra.SetLayerSet(pcbnew.LSET.AllCuMask())
    ra.SetZoneName("no_vias_under_RP2040")
    ol = ra.Outline()
    ol.NewOutline()
    for x, y in ((1.5, 63.0), (25.5, 63.0), (25.5, 85.0), (1.5, 85.0)):
        ol.Append(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))
    b.Add(ra)

    ds = b.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    pcbnew.SaveBoard(BOARD, b)
    raw = open(BOARD, "rb").read()
    open(BOARD, "wb").write(raw.replace(b"\r\n", b"\n"))
    open(os.path.join(HW, "dekatron.kicad_dru"), "w", newline="\n").write(DRU)
    print(f"placed {len(fps)} parts; failed: {failed}")
    for ref in ("J101", "J102", "J201", "J202", "J203", "J301", "J302", "U301"):
        xs = [pcbnew.ToMM(p.GetPosition().x) - OX for p in fps[ref].Pads() if p.GetNumber()]
        ys = [pcbnew.ToMM(p.GetPosition().y) - OY for p in fps[ref].Pads() if p.GetNumber()]
        rr = court_rect(fps[ref], 0)
        print(f"  {ref}: pads x {min(xs):.1f}..{max(xs):.1f} y {min(ys):.1f}..{max(ys):.1f}; courtyard "
              f"x {rr[0]:.1f}..{rr[2]:.1f} y {rr[1]:.1f}..{rr[3]:.1f}")
    print("wrote", os.path.relpath(BOARD, ROOT))


if __name__ == "__main__":
    main()
