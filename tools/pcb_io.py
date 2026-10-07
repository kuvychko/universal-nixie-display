#!/usr/bin/env python3
"""pcbnew side of tools/route_pcb.py (adapted from nanovolt-divider). Run with KiCad's own Python:

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  BOARD OUT.json
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply BOARD ROUTES.json

dump   writes pads (copper outline, net, layer, drill), Edge.Cuts segments and the GND zone outlines
       in board coordinates (mm from the board's top-left corner).
apply  deletes EVERY track and via on BOARD, adds the routed ones, refills the zones and saves BOARD
       with LF line endings.
"""
import json
import sys

import pcbnew

OX, OY = 50.0, 50.0          # board origin on the KiCad sheet, as in gen_pcb.py
VIA_D, VIA_DRILL = 0.7, 0.35


def mm(v):
    return round(pcbnew.ToMM(v), 4)


def xy(p):
    return [round(mm(p.x) - OX, 4), round(mm(p.y) - OY, 4)]


def dump(board_path, out):
    b = pcbnew.LoadBoard(board_path)
    d = {"pads": [], "edges": [], "zones": [], "novia": [], "gndfill": []}
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not pad.IsOnLayer(layer):
                    continue
                sp = pcbnew.SHAPE_POLY_SET()
                pad.TransformShapeToPolygon(sp, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
                polys = [[xy(sp.Outline(i).CPoint(j)) for j in range(sp.Outline(i).PointCount())]
                         for i in range(sp.OutlineCount())]
                d["pads"].append({"ref": fp.GetReference(), "num": pad.GetNumber(), "net": pad.GetNetname(),
                                  "layer": "F" if layer == pcbnew.F_Cu else "B", "poly": polys,
                                  "pos": xy(pad.GetPosition()), "drill": mm(pad.GetDrillSize().x)})
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                d["pads"].append({"ref": fp.GetReference(), "num": "", "net": "", "layer": "F", "poly": [],
                                  "pos": xy(pad.GetPosition()), "drill": mm(pad.GetDrillSize().x)})
    for dr in b.GetDrawings():
        if dr.GetLayer() == pcbnew.Edge_Cuts:
            d["edges"].append({"start": xy(dr.GetStart()), "end": xy(dr.GetEnd())})
    for z in b.Zones():
        if z.GetIsRuleArea():
            if z.GetDoNotAllowVias():
                ol = z.Outline().Outline(0)
                d["novia"].append([xy(ol.CPoint(i)) for i in range(ol.PointCount())])
            continue
        ol = z.Outline().Outline(0)
        d["zones"].append({"net": z.GetNetname(), "layer": "F" if z.GetLayer() == pcbnew.F_Cu else "B",
                           "poly": [xy(ol.CPoint(i)) for i in range(ol.PointCount())]})
        if z.GetNetname() == "GND" and z.IsFilled():
            fp = z.GetFilledPolysList(z.GetLayer())
            if fp.OutlineCount():
                k = max(range(fp.OutlineCount()), key=lambda i: fp.Outline(i).Area())
                d["gndfill"].append({"layer": "F" if z.GetLayer() == pcbnew.F_Cu else "B",
                                     "outline": [xy(fp.Outline(k).CPoint(i)) for i in range(fp.Outline(k).PointCount())],
                                     "holes": [[xy(fp.Hole(k, h).CPoint(i)) for i in range(fp.Hole(k, h).PointCount())]
                                               for h in range(fp.HoleCount(k))]})
    json.dump(d, open(out, "w"))
    print(f"{len(d['pads'])} pad outlines, {len(d['edges'])} edges, {len(d['zones'])} zones -> {out}")


STITCH_PITCH = 2.5     # mm grid for GND stitching vias
STITCH_RING = 0.4      # a via goes only where a circle this size lies inside both GND fills (via r 0.35)
STITCH_HOLE = 1.0      # minimum distance to any existing hole (vias, PTH pads, NPTH)


def stitch(b, P):
    """Join the top and bottom GND pours with vias wherever both have solid copper: traces cut the
    pours into fragments, and a fragment touching only a pad is otherwise joined by that pad alone."""
    import math
    fills = {}
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.GetNetname() == "GND":
            fills[z.GetLayer()] = z.GetFilledPolysList(z.GetLayer())
    if pcbnew.F_Cu not in fills or pcbnew.B_Cu not in fills:
        return 0
    keep_out = [z.Outline() for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    holes = [(mm(v.GetPosition().x) - OX, mm(v.GetPosition().y) - OY) for v in b.GetTracks()
             if isinstance(v, pcbnew.PCB_VIA)]
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetDrillSize().x > 0:
                holes.append((mm(pad.GetPosition().x) - OX, mm(pad.GetPosition().y) - OY))
    gnd = b.FindNet("GND")
    bb = b.GetBoardEdgesBoundingBox()
    x0, y0 = mm(bb.GetLeft()) - OX, mm(bb.GetTop()) - OY
    x1, y1 = mm(bb.GetRight()) - OX, mm(bb.GetBottom()) - OY
    ring = [(STITCH_RING * math.cos(k * math.pi / 4), STITCH_RING * math.sin(k * math.pi / 4)) for k in range(8)]
    n = 0
    y = y0 + STITCH_PITCH
    while y < y1:
        x = x0 + STITCH_PITCH
        while x < x1:
            ok = all(fills[L].Contains(P(x + dx, y + dy)) for L in fills for dx, dy in ring + [(0, 0)])
            ok = ok and not any(k.Contains(P(x, y)) for k in keep_out)
            ok = ok and all(math.hypot(x - hx, y - hy) >= STITCH_HOLE for hx, hy in holes)
            if ok:
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(P(x, y))
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(gnd)
                b.Add(v)
                holes.append((x, y))
                n += 1
            x += STITCH_PITCH
        y += STITCH_PITCH
    return n


def apply(board_path, routes):
    b = pcbnew.LoadBoard(board_path)
    P = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))  # noqa: E731
    for t in list(b.GetTracks()):
        b.Remove(t)
    nets = {}

    def net_of(name):
        if name not in nets:
            nets[name] = b.FindNet(name)
            if nets[name] is None:
                raise KeyError(f"net {name!r} is not on the board")
        return nets[name]

    r = json.load(open(routes))
    n = 0
    for net, layer, w, pts in r["tracks"]:
        for a, c in zip(pts, pts[1:]):
            if a == c:
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(P(*a))
            t.SetEnd(P(*c))
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(pcbnew.F_Cu if layer == 0 else pcbnew.B_Cu)
            t.SetNet(net_of(net))
            b.Add(t)
            n += 1
    for net, x, y in r["vias"]:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(P(x, y))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net_of(net))
        b.Add(v)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    ns = stitch(b, P)
    if ns:
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(board_path, b)
    raw = open(board_path, "rb").read()
    open(board_path, "wb").write(raw.replace(b"\r\n", b"\n"))
    print(f"{n} track segments, {len(r['vias'])} vias, {ns} GND stitching vias -> {board_path}"
          + (f"   FAILED NETS: {r['failed']}" if r.get("failed") else ""))


if __name__ == "__main__":
    cmd, board, path = sys.argv[1:4]
    {"dump": dump, "apply": apply}[cmd](board, path)
