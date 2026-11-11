#!/usr/bin/env python3
"""
Bootstrap PCB generator for the Nixie board (Phase 2 layout, first pass). Run with KiCad's Python:
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/gen_nixie_pcb.py
Writes hardware/nixie/nixie.kicad_pcb (unrouted) and nixie.kicad_dru, the same way as gen_pcb.py
does for the dekatron board:
  * board outline, four M3 corner holes (user, 2026-11-06) and a pair at the middle of the long
    edges against flexing (user, 2026-11-10);
  * six IN-14s on B.Cu along the front edge (y = 0), equal 24 mm pitch: 19 mm glass + 5 mm gap
    (user, 2026-11-06, "universal display", no HH MM SS grouping); tube 1 at the viewer's left;
  * the three HV5622s behind their tube pairs; the RP2040-Zero right of tube 6 (USB-C outward) on
    a long, shallow board (user, 2026-11-10); the 12 V switch and the level shifter in the gaps
    between the drivers; harness wire pads along the back edge with cable-tie holes (D14), the HV
    module output and the HV monitor at the left edge;
  * the remaining parts by the constructive placer of gen_pcb.py;
  * GND pours on both layers over the whole board.
Clearances come from the net classes in nixie.kicad_pro (NCATH 0.25 mm, NHV 1.25 mm; hardware.md
"Clearance rules"), so Freerouting reads them from the exported DSN.
Once the board is edited in KiCad the .kicad_pcb is the source of truth.

Viewing note: side A (F.Cu, all parts but the tubes) faces down in the enclosure. KiCad's top view
looks at side A, i.e. from below; with the front edge at the top of the screen (y = 0) the viewer's
left is at small x, so tube 1 is N1 at the left.
"""
import csv
import math
import os
import subprocess
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware", "nixie")
BOARD = os.path.join(HW, "nixie.kicad_pcb")
KICAD_CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
SHARE = os.environ.get("KICAD_FOOTPRINTS", r"C:\Program Files\KiCad\10.0\share\kicad\footprints")
PROJ_LIB = os.path.join(HW, "lib", "nixie.pretty")

OX, OY = 50.0, 50.0           # board origin on the KiCad sheet
W, H = 164.0, 53.0            # long and shallow (user, 2026-11-10): the RP2040-Zero moves right of
                              # tube 6, the logic into the gaps between the drivers; was 150 x 70
BAND_Y = H - 3.0              # harness wire pads along the back edge

TUBE_PITCH = 24.0             # 19 mm glass + 5 mm (user, 2026-11-06)
TUBE_Y = 12.0                 # tube centre from the front edge: proposal (glass radius 9.5 + 2.5 mm)
TUBE_X0 = 15.0                # first tube clear of the corner hole
CHIP_Y = 25.0                 # HV5622 centre: between its two tubes, just behind the lead rings
TUBE_ROT = 0                  # after Flip(): anode (pin 1) toward the back, front toward the front edge (checked by pad coordinates)

DRU = """(version 1)
# Net-class clearances live in nixie.kicad_pro (NCATH 0.25 mm, NHV 1.25 mm, Default 0.2 mm; KiCad
# applies the larger value between two classes). Here: fab minima, and the IN-14 footprint's own
# pads, 1.156 mm apart (square anode pad to the decimal-point pads), below NHV.
(rule "Fab minimum (PCBWay standard, ordered at 6/6 mil)"
  (constraint track_width (min 0.1524mm))
  (constraint hole_size (min 0.2mm))
  (constraint annular_width (min 0.15mm)))
(rule "IN-14 own pads (hardware.md Clearance rules)"
  (condition "A.Type == 'Pad' && B.Type == 'Pad' && A.memberOfFootprint('N?') && B.memberOfFootprint('N?')")
  (constraint clearance (min 1.15mm)))
"""

# --------------------------------------------------------------------------------------
# Regions (x0, y0, x1, y1) in board mm, origin top-left, front edge at y = 0
# --------------------------------------------------------------------------------------
REG = {
    "TUBE":  (0, 0, W, 40),            # decimal-point resistors, between and behind tubes
    "DRV":   (14, 29, 138, 40),        # HV5622 bypass
    "HVMON": (0, 22, 22, H),           # HV module output, divider, clamp: left end
    "PWR":   (22, 22, 71, H),          # 12 V switch: gap between U201 and U202, band behind
    "LOGIC": (86, 22, 112, H),         # level shifter, 12 V logic rail: gap between U202 and U203, band
    "MCU":   (145, 7, W, H),           # RP2040-Zero support, encoder filter, ES100 pulls: right end
    "ENC":   (76, 39, 130, H),         # encoder filter by its harness pads (J301)
    "BAND":  (0, 39, W, H),            # 5 V harness landing, by the back-edge wire pads
}

GROUP = {}
for refs, g in (
    ("N1 N2 N3 N4 N5 N6 R210 R211 R212 R220 R221 R222 R230 R231 R232 R240 R241 R242 R250 R251 R252 "
     "R260 R261 R262", "TUBE"),
    ("U201 U202 U203 C201 C202 C203", "DRV"),
    ("J104 R105 R106 D101 C103 TP103", "HVMON"),
    ("J102 J103 Q101 Q102 R101 R102 R103 R104 C102 TP101 TP102", "PWR"),
    ("U302 C303 C304 C305 R301 R309 R310 D301", "LOGIC"),
    ("R302 R303 R304 R311 R312 R313 C308 C309 C310", "ENC"),
    ("U301 C301 C302 R305 R306 R307 R308 R314 R315 R107 R108 C104 "
     "TP301 TP302 TP303 TP304 TP305", "MCU"),
    ("J101 J301 J302 J303 C101 TP104 TP105 TP306 TP307 TP308 TP309 TP310", "BAND"),
):
    for r in refs.split():
        GROUP[r] = g

# Anchors: ref -> (x, y, rotation degrees, side). Footprint origins in board coordinates.
ANCHOR = {}
for k in range(6):
    tx = TUBE_X0 + k * TUBE_PITCH
    ANCHOR[f"N{k + 1}"] = (tx, TUBE_Y, TUBE_ROT, "B")
    # anode resistor upright behind its tube (side A is free there: the glass is on side B): pad 2
    # (anode) clear of the tube courtyard, pad 1 (NIX_HV) 10.16 mm further back
    ANCHOR[f"R2{k + 1}0"] = (tx, CHIP_Y + 8.0, 90, "F")
# HV5622 between its two tubes. Rotation 270: the bottom side (HVOUT1-11, tube a) faces left toward
# tube a, the left side (HVOUT12-22, tube b) faces the tubes, the top (HVOUT23-24, tube b's points)
# faces right toward tube b, the logic side faces the back.
for k in range(3):
    ANCHOR[f"U{201 + k}"] = (TUBE_X0 + TUBE_PITCH / 2 + 2 * k * TUBE_PITCH, CHIP_Y, 270, "F")
ANCHOR.update({
    # RP2040-Zero right of tube 6 and toward the back (user, 2026-11-10), USB-C at the right edge,
    # clear of the back-right corner hole
    "U301": (W - 12.5, 31.5, 270, "F"),
    "U302": (99.0, 28.5, 0, "F"),           # level shifter between U202 and U203
    "TP302": (146.0, 8.0, 0, "F"),          # NIX12_SENSE pad: the placer left it at the right edge,
                                             # no room for its reference (2026-11-11)
    "Q101": (50.0, 29.0, 0, "F"),           # 12 V switch between U201 and U202
    # harness wire pads (pad 1 at the origin, pads along +x at 4.8 mm), back edge, either side of
    # the middle hole H6
    "J102": (24.0, BAND_Y, 0, "F"),         # 12V_IN
    "J103": (34.0, BAND_Y, 0, "F"),         # 12V_MODULE
    "J101": (45.0, BAND_Y, 0, "F"),         # NIX_LV
    "J301": (82.0, BAND_Y, 0, "F"),         # ENCODER
    "J302": (102.0, BAND_Y, 0, "F"),        # RTC
    "J303": (122.0, BAND_Y, 0, "F"),        # WWVB
    # HV module output on the left edge, pads downward (rotation 270: +x -> +y)
    "J104": (3.0, 30.0, 270, "F"),
    "R105": (20.0, 39.0, 180, "F"),          # HV divider top (DIN0411, 15.24 mm), lying behind the HV
                                             # landing: NIX_HV pad (1) on the right, next to R210's
})

def tie_for(ref, x, y, rot, n):
    """Cable-tie anchor 4.5 mm inboard of a wire-pad row, centred on it."""
    L = 4.8 * (n - 1)
    if rot == 0:
        return (x + L / 2, y - 4.5, "x")
    return (x + 4.5, y + L / 2, "y")

NPADS = {"J101": 6, "J102": 2, "J103": 2, "J104": 2, "J301": 4, "J302": 4, "J303": 6}
TIES = {r: tie_for(r, *ANCHOR[r][:3], NPADS[r]) for r in NPADS}

# M3, non-plated: four corners, plus a pair at the middle of the long edges against flexing (user,
# 2026-11-10), at x = 75 between tubes 3 and 4 (the middle of the tube row)
HOLES = ((4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4), (75, 4), (75, H - 4))

# F-side keep-outs: the tube lead rings (pads on both sides), so the placer leaves them clear
KEEPOUT = [(TUBE_X0 + k * TUBE_PITCH - 7.0, TUBE_Y - 7.0, TUBE_X0 + k * TUBE_PITCH + 7.0, TUBE_Y + 7.0)
           for k in range(6)]
# HV lane behind the drivers (y 35-39): NIX_HV runs from the module landing past every anode
# resistor's back pad (y 33) with 1.25 mm clearance; the placer keeps parts out of it
KEEPOUT.append((14, 35, 137, 39))


# Net classes (hardware.md "Clearance rules"; same values as project_json() in
# gen_nixie_schematics.py). pcbnew.SaveBoard() rewrites nixie.kicad_pro from the board's own net
# settings, so they are set here on the board, or the save would drop them.
#   name: (clearance, track width, via diameter, via drill), mm
NETCLASSES = {"Default": (0.2, 0.25, 0.6, 0.3), "NHV": (1.25, 0.3, 0.8, 0.4), "NCATH": (0.25, 0.3, 0.8, 0.4)}
NETCLASS_PATTERNS = [("NIX_HV", "NHV"), ("*_ANODE", "NHV"), ("*T?_K?", "NCATH"), ("*DP_K", "NCATH"),
                     ("*DP_D", "NCATH")]


def apply_netclasses(b):
    ns = b.GetDesignSettings().m_NetSettings
    for name, (clr, tw, vd, vdr) in NETCLASSES.items():
        nc = ns.GetDefaultNetclass() if name == "Default" else pcbnew.NETCLASS(name)
        nc.SetClearance(pcbnew.FromMM(clr))
        nc.SetTrackWidth(pcbnew.FromMM(tw))
        nc.SetViaDiameter(pcbnew.FromMM(vd))
        nc.SetViaDrill(pcbnew.FromMM(vdr))
        if name != "Default":
            ns.SetNetclass(name, nc)
    ns.ClearNetclassPatternAssignments()
    for pat, name in NETCLASS_PATTERNS:
        ns.SetNetclassPatternAssignment(pat, name)
    ns.ClearAllCaches()
    b.SynchronizeNetsAndNetClasses(True)


def net_class(name):
    import fnmatch
    for c, p in (("NHV", "NIX_HV"), ("NHV", "*_ANODE"), ("NCATH", "*T?_K?"), ("NCATH", "*DP_K"),
                 ("NCATH", "*DP_D")):
        if fnmatch.fnmatchcase(name.lstrip("/"), p) or fnmatch.fnmatchcase(name, p):
            return c
    return "Default"


def export_netlist(path):
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", path,
                    os.path.join(HW, "nixie.kicad_sch")], check=True, capture_output=True)


def parse_netlist(path):
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
    path = PROJ_LIB if lib == "nixie" else os.path.join(SHARE, lib + ".pretty")
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


SKIP_NETS = {"GND", "+5V", "+3V3", "+12V_LOGIC"}     # too many pins to steer placement


def main():
    netfile = os.path.join(ROOT, "build", "nixie.net")
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
    INFL = {"NHV": 0.8, "NCATH": 0.2, "Default": 0.2}

    def infl_of(ref):
        cls = [net_class(n) for (r, _), n in pin_net.items() if r == ref]
        return max([INFL[c] for c in cls] + [0.2])

    def make(ref):
        c = comps[ref]
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetExcludedFromBOM(False)
        for k, v in c["fields"].items():
            fp.SetField(k, v)
            fp.GetField(k).SetVisible(False)
        for pad in fp.Pads():
            n = pin_net.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(nets[n])
        return fp

    def commit(ref, fp, rect=None, added=False):
        if not added:
            b.Add(fp)
        fps[ref] = fp
        occ.append((ref, rect or court_rect(fp, infl_of(ref))))
        for pad in fp.Pads():
            n = pin_net.get((ref, pad.GetNumber()))
            if n and n not in SKIP_NETS:
                placed_pads.setdefault(n, []).append((pcbnew.ToMM(pad.GetPosition().x) - OX,
                                                      pcbnew.ToMM(pad.GetPosition().y) - OY))

    for ref, (x, y, rot, side) in ANCHOR.items():
        fp = make(ref)
        fp.SetPosition(P(x, y))
        if side == "B":
            b.Add(fp)                          # Flip needs the board (layer mapping)
            fp.Flip(P(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        commit(ref, fp, rect=(x - 7.0, y - 7.0, x + 7.0, y + 7.0) if side == "B" else None,
               added=side == "B")

    # HV5622 bypass caps right at each chip's VDD pin (30), outside the logic-side pin row
    for k in range(3):
        u = fps[f"U{201 + k}"]
        vdd = next(p for p in u.Pads() if p.GetNumber() == "30").GetPosition()
        vx, vy = pcbnew.ToMM(vdd.x) - OX, pcbnew.ToMM(vdd.y) - OY
        fp = make(f"C{201 + k}")
        fp.SetOrientationDegrees(90)
        fp.SetPosition(P(vx - 2.0, vy + 3.8))     # 2 mm left: clear of the RP2040-Zero by U203
        commit(f"C{201 + k}", fp)

    for ref, (x, y, axis) in TIES.items():
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(f"TIE_{ref}")
        fp.SetValue("cable tie")
        fp.Reference().SetVisible(False)
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        for d in (-2.0, 2.0):
            pad = pcbnew.PAD(fp)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            pad.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_CIRCLE)
            sz = pcbnew.FromMM(1.6)
            pad.SetSize(pcbnew.F_Cu, pcbnew.VECTOR2I(sz, sz))
            pad.SetDrillSize(pcbnew.VECTOR2I(sz, sz))
            pad.SetLayerSet(pad.UnplatedHoleMask())
            pad.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(d), 0) if axis == "x"
                                      else pcbnew.VECTOR2I(0, pcbnew.FromMM(d)))
            fp.Add(pad)
        fp.SetPosition(P(x, y))
        b.Add(fp)
        occ.append((f"TIE_{ref}", (x - 3.5, y - 1.5, x + 3.5, y + 1.5) if axis == "x"
                    else (x - 1.5, y - 3.5, x + 1.5, y + 3.5)))

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

    def rule_area(name, pts):
        """Copper keep-out for tracks and vias (exported to Freerouting as a keepout)."""
        ra = pcbnew.ZONE(b)
        ra.SetIsRuleArea(True)
        ra.SetDoNotAllowVias(True)
        ra.SetDoNotAllowTracks(True)
        ra.SetDoNotAllowZoneFills(True)
        ra.SetDoNotAllowPads(False)
        ra.SetDoNotAllowFootprints(False)
        ra.SetLayerSet(pcbnew.LSET.AllCuMask())
        ra.SetZoneName(name)
        ol = ra.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))
        b.Add(ra)

    # cable-tie holes and mounting holes are NPTH in board-only footprints, which the DSN export
    # does not carry as obstacles: keep tracks and vias off them explicitly
    for ref, (x, y, axis) in TIES.items():
        for d in (-2.0, 2.0):
            hx, hy = (x + d, y) if axis == "x" else (x, y + d)
            rule_area(f"keepout_tie_{ref}", [(hx - 1.3, hy - 1.3), (hx + 1.3, hy - 1.3), (hx + 1.3, hy + 1.3),
                                             (hx - 1.3, hy + 1.3)])
    for i, (x, y) in enumerate(HOLES):
        rule_area(f"keepout_H{i + 1}", [(x - 3.4, y - 3.4), (x + 3.4, y - 3.4), (x + 3.4, y + 3.4), (x - 3.4, y + 3.4)])
    # board-edge band: KiCad's 0.5 mm copper-to-edge default
    e = 0.6
    for nm, r in (("top", (0, 0, W, e)), ("bottom", (0, H - e, W, H)), ("left", (0, 0, e, H)),
                  ("right", (W - e, 0, W, H))):
        rule_area(f"keepout_edge_{nm}", [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])])

    def conn_count(ref):
        return sum(1 for (r, _), n in pin_net.items() if r == ref and n in placed_pads)
    todo = [r for r in comps if r not in fps]
    failed = []
    while todo:
        # the two pockets between the drivers first: the band behind them is shared
        todo.sort(key=lambda r: (GROUP[r] not in ("PWR", "LOGIC"), -conn_count(r)))
        ref = todo.pop(0)
        reg = REG[GROUP[ref]]
        tgt = [pt for (r, _), n in pin_net.items() if r == ref and n in placed_pads for pt in placed_pads[n]]
        if tgt:
            tx = sum(p[0] for p in tgt) / len(tgt)
            ty = sum(p[1] for p in tgt) / len(tgt)
        else:
            tx, ty = (reg[0] + reg[2]) / 2, (reg[1] + reg[3]) / 2
        tx = min(max(tx, reg[0] + 2), reg[2] - 2)
        ty = min(max(ty, reg[1] + 2), reg[3] - 2)
        fp = make(ref)
        best = None
        step = 0.5
        for ring in range(0, 200):
            cands = [(0, 0)] if ring == 0 else (
                [(i, -ring) for i in range(-ring, ring + 1)] + [(i, ring) for i in range(-ring, ring + 1)] +
                [(-ring, i) for i in range(-ring, ring + 1)] + [(ring, i) for i in range(-ring, ring + 1)])
            for dx, dy in cands:
                x, y = tx + dx * step, ty + dy * step
                for rot in (0, 90):
                    fp.SetOrientationDegrees(rot)
                    fp.SetPosition(P(x, y))
                    rr = court_rect(fp, infl_of(ref))
                    if not inside(court_rect(fp, 0), reg) or any(overlap(rr, o) for _, o in occ):
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
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        b.Add(z)

    # GND pours over the whole board, both layers (2026-11-07): KiCad keeps the larger of the zone
    # and net-class clearance, so cathodes stay 0.25 mm and HV 1.25 mm from the pour
    lv = [(0.5, 0.5), (W - 0.5, 0.5), (W - 0.5, H - 0.5), (0.5, H - 0.5)]
    zone("GND", pcbnew.B_Cu, lv, "GND_B")
    zone("GND", pcbnew.F_Cu, lv, "GND_F")

    # no vias / no pour under the RP2040-Zero (pads on its underside)
    ux, uy = ANCHOR["U301"][:2]
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
    for x, y in ((ux - 11.0, uy - 8.0), (ux + 11.0, uy - 8.0), (ux + 11.0, uy + 8.0), (ux - 11.0, uy + 8.0)):
        ol.Append(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))
    b.Add(ra)

    # no pour inside the tube lead rings: the hand-soldered leads keep their own spacing, and the
    # pour would only leave slivers between the cathode fan-out tracks there. Radius: lead circle
    # 5.5 mm + pad 0.7 mm + 1.3 mm. Tracks and vias stay allowed, so nothing reaches the DSN.
    for k in range(6):
        cx, cy = TUBE_X0 + k * TUBE_PITCH, TUBE_Y
        ta = pcbnew.ZONE(b)
        ta.SetIsRuleArea(True)
        ta.SetDoNotAllowZoneFills(True)
        for allow in (ta.SetDoNotAllowVias, ta.SetDoNotAllowTracks, ta.SetDoNotAllowPads,
                      ta.SetDoNotAllowFootprints):
            allow(False)
        ta.SetLayerSet(pcbnew.LSET.AllCuMask())
        ta.SetZoneName(f"no_pour_N{k + 1}")
        ol = ta.Outline()
        ol.NewOutline()
        for i in range(32):
            a = 2 * math.pi * i / 32
            ol.Append(pcbnew.FromMM(cx + 7.5 * math.cos(a) + OX), pcbnew.FromMM(cy + 7.5 * math.sin(a) + OY))
        b.Add(ta)

    b.GetDesignSettings().SetCopperLayerCount(2)
    # DRC minimum track width: the fab's 0.1524 mm, rounded up to the 0.16 mm that
    # freeroute_nixie.py widens Freerouting's neck-downs to (KiCad's default is 0.2 mm)
    b.GetDesignSettings().m_TrackMinWidth = pcbnew.FromMM(0.16)
    apply_netclasses(b)
    ns = b.GetDesignSettings().m_NetSettings
    for n in ("/tubes/T1_K1", "/tubes/T6_RDP_D", "NIX_HV", "/tubes/T3_ANODE", "GND"):
        nc = ns.GetEffectiveNetClass(n)
        print(f"  {n}: {nc.GetName()} clearance {pcbnew.ToMM(nc.GetClearance())} width "
              f"{pcbnew.ToMM(nc.GetTrackWidth())}")
    pcbnew.SaveBoard(BOARD, b)
    raw = open(BOARD, "rb").read()
    open(BOARD, "wb").write(raw.replace(b"\r\n", b"\n"))
    open(os.path.join(HW, "nixie.kicad_dru"), "w", newline="\n").write(DRU)
    print(f"placed {len(fps)} parts; failed: {failed}")
    print("wrote", os.path.relpath(BOARD, ROOT))


if __name__ == "__main__":
    main()
