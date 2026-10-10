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
  * .kicad_dru clearance rules between the D13 net classes (PCBWay 2-layer, 6/6 mil base).

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
W, H = 100.0, 85.0            # third pass (0207 HV resistors, 4-wire tube harness); shrink after routing

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
(rule "Fab minimum (PCBWay standard, ordered at 6/6 mil)"
  (constraint track_width (min 0.1524mm))
  (constraint hole_size (min 0.2mm))
  (constraint annular_width (min 0.15mm)))
"""

# --------------------------------------------------------------------------------------
# Regions (x0, y0, x1, y1) in board mm, origin top-left
# --------------------------------------------------------------------------------------
# regions are a rectangle or a list of rectangles (a part must fit inside one of them)
REG = {
    "IN":    (6, 6, 44, 24),
    "BUCK":  (8, 22, 40, 42),
    "MCU":   (0, 42, 40, 85),
    "CTRL":  (40, 0, 60, 36),
    "DIV":   (59, 0, 77, 11.6),
    "EN":    (40, 8, 46, 36),        # LM5156 EN/UVLO parts beside pin 14 (left of the chip)      # low-voltage ends of the HV dividers and the OVP comparators
    "SW":    (40, 36, 64, 57),
    "HV":    (60, 10, 100, 80),
    "TUBE":  [(40, 58, 72, 85), (60, 74, 86, 85), (40, 52, 47.5, 58)],     # second strip: under the anode resistors
}

GROUP = {}
for refs, g in (
    ("J101 F101 Q101 R101 D101 D102 C101 C102 TP101 TP102 F102 J102", "IN"),
    ("U101 C103 C104 R102 R103 C105 L101 C106 C107 R104 R105 C108 R106 LK2 TP103 U102 U103 U104 C109 C110 C111 J302", "BUCK"),
    ("R109 R110 R112 JP101", "EN"),
    ("LK1 C112 U105 R107 R108 C113 TP104 U106 C114 C115 R111 C116 R113 C117 C118 R114 R115 R116 "
     "R143 C129 C128 C130", "CTRL"),
    ("R126 R131 R130 R144 R135 R140 C127 U107 U108", "DIV"),
    ("Q102 R117 R118 C119 C120 C121 L102 D103 TP105 TP107 TP106 LK5 R119 R141", "SW"),
    ("R121 C122 C123 C124 C125 C126 D104 D105 D106 D107 LK3 LK4 TP108 R215 R216 J201", "HV"),
    ("R201 D201 D202 C201 C202 R202 R204 TP201 TP202 TP206 R205 R206 R207 R208 R209 R210 Q201 Q202 TP203 "
     "TP204 Q203 R211 R212 R214 C204 TP205 J202", "TUBE"),
    ("U301 C301 C302 TP301 TP302 TP303 TP304 TP305 TP306 TP307 TP308 TP309 TP310 TP311 R301 R302 D301 D302 D303 "
     "D304 C303 C304 C305 R303 R304 TP312 TP313 J301 LK15", "MCU"),
):
    for r in refs.split():
        GROUP[r] = g

# Anchors: ref -> (x, y, rotation degrees). Footprint origins, board coordinates.
# Harness landings are plain wire-pad rows along an edge; a cable-tie anchor sits 4.5 mm inboard (TIES).
ANCHOR = {
    "J101": (12.0, 3.0, 0), "J102": (24.0, 3.0, 0),                   # top edge
    "J302": (3.0, 13.0, 270),                                         # left edge, pads run downward:
    # 5V_NIX on top (its ideal diode U104 beside it), SDA / SCL / spare toward the module
    "J301": (26.0, 82.0, 0), "J202": (66.0, 82.0, 0),                 # bottom edge
    "J201": (95.5, 70.5, 0),                                          # anode: right edge, >= 3 mm (HV)
    "U301": (13.5, 58.0, 90),                                         # RP2040-Zero, USB-C at the left edge
    # the module's power pins (1 5V_MCU, 2 GND, 3 3V3) are on its bottom row: its ideal diode and bulk
    # cap sit just below them rather than up with the other ideal diodes
    "U103": (9.0, 72.5, 0), "C301": (3.6, 72.5, 90),
    "U102": (21.0, 75.0, 0),       # 5V_DISP ideal diode beside J301 pin 1
    "R301": (15.935, 75.225, 0),   # 0.6 mm left of where the placer put it: room for U102's GND escape via
    "C108": (15.96, 25.55, 0),     # 0.6 mm right of where the placer put it: room for U104's GND escape via
    "C303": (14.4, 71.1, 270),     # VIN_SENSE reservoir: GND pad down, toward the open pour (a sealed GND pocket otherwise)
    "D301": (18.45, 71.05, 180),   # GND pin toward the open pour (a sealed pocket below the module otherwise)
    "JP101": (38.6, 26.0, 0),      # HV inhibit header, beside the EN parts
    "R110": (44.4, 31.0, 90),      # EN/UVLO pull-down
    "R112": (42.5, 20.4, 0),       # EN/UVLO read-back to OVP_TRIP
    "R109": (42.0, 31.4, 90),      # HV_EN series resistor
    "Q101": (20.0, 15.0, 0), "C101": (35.0, 15.0, 90),
    "D102": (14.5, 21.5, 0), "U101": (16.0, 29.0, 180),   # 180: SW (pin 2) faces L101 "L101": (26.0, 29.0, 0),
    "U105": (43.5, 5.0, 0), "U106": (49.0, 16.5, 90),
    "L102": (43.4, 39.6, 0), "Q102": (52.0, 47.0, 0), "D103": (60.5, 54.5, 0),
    # tripler column: film capacitors (origin = pad 1, pad 2 at +15 mm; rotation 180 puts pad 2 at -15 mm),
    # oriented so shared nodes face each other: N2 on the left (C126, C125), P1 on the right (C125/C124)
    "C126": (66.0, 15.2, 0),       # pad 1 N2 left, pad 2 HV_STACK right; 0.2 down clears R131 (8 mm body)
    "C125": (81.0, 24.0, 180),     # pad 1 V_BT right, pad 2 N2 left
    "C124": (81.0, 33.0, 180),     # pad 1 P1 right, pad 2 P2 left
    "C123": (66.0, 42.0, 0),       # pad 1 PUMP left, pad 2 P1 right
    "C122": (66.0, 51.0, 0),       # pad 1 V_B left (boost diode D103), pad 2 GND right
    # tripler diodes beside their nodes (SMA: pad 1 = cathode at -2 mm; rotation 90 puts it below, 270 above)
    "D107": (85.5, 19.5, 270),     # P2 -> HV_STACK: cathode up toward HV_STACK (81, 15)
    "D104": (85.5, 28.5, 90),      # V_BT (81, 24) -> P1 (81, 33): cathode down
    "D105": (85.5, 37.5, 270),     # P1 -> N2: anode at the P1 pads, cathode routed to N2 on the left
    "D106": (62.0, 28.5, 90),      # N2 (66, 24) -> P2 (66, 33): cathode down
    # HV dividers along the top edge: HV_STACK pad (pad 1) on the right, low-voltage pad 10.16 mm left
    "R126": (86.0, 4.8, 180),      # feedback
    "R131": (86.0, 9.4, 180),      # monitor / OVP
    "R135": (72.2, 9.4, 180),      # monitor / OVP middle: pad 1 HV_SENSE (74.46) beside R131's low pad
    "R140": (68.6, 7.2, 90),       # monitor / OVP lower: pad 1 OVP_SENSE (69.3, 8.66)
    # anode string below the column: HV in at the right, R215 -> R216 -> J201
    "R215": (88.0, 64.5, 180),     # pad 1 HV right, pad 2 STR_A1 at 72.76
    "R216": (72.76, 70.5, 0),      # pad 1 STR_A1, pad 2 ANODE at 88.0 -> J201
    "LK4": (93.0, 22.0, 90),       # pad 1 HV_STACK (93, 22), pad 2 HV (93, 14.38)
    # V_b legs flat under C122: pad 1 V_B on the right, pad 2 (low end) on the left toward the pour / U108
    "R141": (76.66, 57.4, 180),    # V_b OVP divider top: pad 2 VB_OVP_SENSE
    "R119": (76.66, 60.9, 180),    # V_b bleeder: pad 2 GND
    # V_b -> V_B_BIAS link and the G+ / RTN feed, between the switch area and the tube area
    "LK5": (62.5, 58.0, 180),      # pad 1 V_B (62, 57.5) by D103, pad 2 V_B_BIAS (54.38, 57.5)
    "R201": (54.38, 61.0, 270),    # pad 1 V_B_BIAS, pad 2 GPLUS 10.16 mm below
    "TP106": (92.5, 55.0, 0),      # V_B, beside LK3's V_B pad
    "R121": (61.8, 42.0, 0),       # pump surge resistor: pad 1 SW (60.5) toward Q102, pad 2 PUMP by C123
    # LM5156 neighbourhood (U106 rotated 90: top row 14 EN, 13 PGOOD, 12 RT, 11 SS, 10 FB, 9 VDRV, 8 COMP
    # left to right at y 13.64; bottom row 1 VDRV, 2 NC, 3 VDRV, 4 GATE, 5/6 GND, 7 CS at y 19.36)
    "C116": (49.0, 8.4, 90),       # SS: pad 1 (49.0, 9.86) straight above pin 11
    "R111": (45.4, 9.2, 180),      # RT: pad 1 (46.86, 9.2) up-left of pin 12; EN / PGOOD pass beneath it
    "C118": (54.5, 14.0, 0),       # COMP HF cap: pad 1 (53.04, 14.0), reached from the side of end pin 8
    "R113": (54.5, 16.4, 0),       # COMP R: pad 1 (53.04, 16.4), pad 2 COMP_RC (55.96, 16.4)
    "C115": (46.4, 24.4, 270),     # VDRV bypass under pins 1 / 3: pad 1 (46.4, 22.94)
    "C114": (44.0, 24.4, 270),
    "TP204": (56.0, 74.0, 0),      # TUBE_G2, between R201 and D202 (no room left for the placer)
    "R207": (46.6, 60.5, 90),      # G1 base pull-down
    "TP203": (60.5, 61.2, 0),      # TUBE_G1, under LK5 (>= 1.5 mm from its V_B pad)
    "TP206": (70.0, 74.8, 0),      # GND, beside the J202 tie (>= 1.5 mm from STR_A1)
}

# Cable-tie anchors: (x, y, axis) two NPTH holes 4 mm apart, centred on the landing, inboard of it.
TIES = {"J101": (14.4, 7.5, "x"), "J102": (26.4, 7.5, "x"), "J302": (7.5, 25.0, "y"),
        "J301": (35.6, 77.5, "x"), "J202": (73.2, 77.5, "x"), "J201": (95.5, 76.5, "x")}

HOLES = ((4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4))     # M3, non-plated, corners

# Placement keep-outs (x0, y0, x1, y1): fan-out room around the LM5156's 0.65 mm-pitch pins, so the
# placer cannot park a passive across the escape paths (routing failed on GATE / FB / RT / SS / VDRV /
# PGOOD when C116 sat 3 mm right of the right-hand pins)
# U106 is rotated 90 degrees: the signal row (EN, PGOOD, RT, SS, FB, VDRV, COMP) faces up toward the
# comparators and the HV divider, the drive row (VDRV, GATE, CS) faces down toward Q102
KEEPOUT = [(45.6, 10.4, 52.4, 13.0), (45.6, 20.0, 52.4, 22.4)]

# Resistor chains placed explicitly: (refs, (x0, y0), (dx, dy), rotation)
CHAINS = []


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
        fields = {}
        fl = gs.find(c, "fields")
        for f in (gs.find_all(fl, "field") if fl else []):
            name = gs.unq(gs.find(f, "name")[1])
            if name != "Footprint" and len(f) > 2:
                fields[name] = gs.unq(f[2])
        comps[ref] = dict(value=gs.unq(gs.find(c, "value")[1]), footprint=gs.unq(gs.find(c, "footprint")[1]),
                          fields=fields)
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
    if isinstance(reg, list):
        return any(inside(r, g) for g in reg)
    return r[0] >= reg[0] and r[1] >= reg[1] and r[2] <= reg[2] and r[3] <= reg[3]


def centre(reg):
    g = reg[0] if isinstance(reg, list) else reg
    return (g[0] + g[2]) / 2, (g[1] + g[3]) / 2, g


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

    # courtyard inflation per side while placing: half the class clearance plus margin for HV parts;
    # BIAS and logic parts rely on their courtyards (the router enforces the copper clearances)
    INFL = {"HV": 1.65, "VB": 0.9, "HVSTR": 0.9, "BIAS": 0.3, "Default": 0.2}

    def infl_of(ref):
        cls = [net_class(n) for (r, _), n in pin_net.items() if r == ref]
        return max([INFL[c] for c in cls] + [0.2])

    def make(ref):
        c = comps[ref]
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetExcludedFromBOM(False)             # some library footprints (solder-wire pads) default to excluded
        for k, v in c["fields"].items():         # Function / MPN / Manufacturer / Rating, as on the symbol
            fp.SetField(k, v)
            fp.GetField(k).SetVisible(False)
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

    # explicit chains
    for refs, (x0, y0), (dx, dy), rot in CHAINS:
        for i, ref in enumerate(refs):
            fp = make(ref)
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(P(x0 + i * dx, y0 + i * dy))
            commit(ref, fp)

    # cable-tie anchors: two NPTH holes per landing
    for ref, (x, y, axis) in TIES.items():
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(f"TIE_{ref}")
        fp.SetValue("cable tie")
        fp.Reference().SetVisible(False)
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
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
    for i, (x, y) in enumerate(HOLES):
        fp = load_fp("MountingHole:MountingHole_3.2mm_M3")
        fp.SetReference(f"H{i + 1}")
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        fp.SetPosition(P(x, y))
        b.Add(fp)
        occ.append((f"H{i + 1}", (x - 3.6, y - 3.6, x + 3.6, y + 3.6)))

    for k in KEEPOUT:
        occ.append(("KEEPOUT", k))

    # LM5156 exposed pad: six 0.3 mm GND vias (the library's ThermalVias variant uses 0.2 mm, below OSH
    # Park's minimum drill); they also let the pad be reflowed from the back. Added as pads of U106, so
    # pcb_io.py apply (which replaces every track and via) leaves them in place.
    ux, uy, _ = ANCHOR["U106"]
    tv = fps["U106"]
    for k, (dx, dy) in enumerate(((-1.6, -0.9), (0, -0.9), (1.6, -0.9), (-1.6, 0.9), (0, 0.9), (1.6, 0.9))):
        pad = pcbnew.PAD(tv)
        pad.SetNumber("15")                      # the exposed pad's number: GND
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.F_Cu, pcbnew.VECTOR2I(pcbnew.FromMM(0.6), pcbnew.FromMM(0.6)))
        pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.3), pcbnew.FromMM(0.3)))
        pad.SetLayerSet(pad.PTHMask())
        tv.Add(pad)
        pad.SetPosition(P(ux + dx, uy + dy))
        pad.SetNet(nets["GND"])

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
            tx, ty, _ = centre(reg)
        rects = reg if isinstance(reg, list) else [reg]
        if not any(g[0] + 2 <= tx <= g[2] - 2 and g[1] + 2 <= ty <= g[3] - 2 for g in rects):
            g = rects[0]
            tx = min(max(tx, g[0] + 2), g[2] - 2)
            ty = min(max(ty, g[1] + 2), g[3] - 2)
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
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)   # API-made zones otherwise keep islands
        b.Add(z)

    # GND pours over the low-voltage regions only (input, buck, MCU, controller); none in HV/SW/tube
    lv = [(0.5, 0.5), (77, 0.5), (77, 11.6), (59, 11.6), (59, 36), (40, 36), (40, 58), (70, 58), (70, 74), (84, 74), (84, 84.5),
          (0.5, 84.5)]
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
    for x, y in ((1.5, 47.0), (25.5, 47.0), (25.5, 69.0), (1.5, 69.0)):
        ol.Append(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))
    b.Add(ra)

    ds = b.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    pcbnew.SaveBoard(BOARD, b)
    raw = open(BOARD, "rb").read()
    open(BOARD, "wb").write(raw.replace(b"\r\n", b"\n"))
    open(os.path.join(HW, "dekatron.kicad_dru"), "w", newline="\n").write(DRU)
    print(f"placed {len(fps)} parts; failed: {failed}")
    for ref in ("J101", "J102", "J201", "J202", "J301", "J302", "U301"):
        xs = [pcbnew.ToMM(p.GetPosition().x) - OX for p in fps[ref].Pads() if p.GetNumber()]
        ys = [pcbnew.ToMM(p.GetPosition().y) - OY for p in fps[ref].Pads() if p.GetNumber()]
        rr = court_rect(fps[ref], 0)
        print(f"  {ref}: pads x {min(xs):.1f}..{max(xs):.1f} y {min(ys):.1f}..{max(ys):.1f}; courtyard "
              f"x {rr[0]:.1f}..{rr[2]:.1f} y {rr[1]:.1f}..{rr[3]:.1f}")
    print("wrote", os.path.relpath(BOARD, ROOT))


if __name__ == "__main__":
    main()
