# /// script
# dependencies = ["numpy", "scipy", "pillow"]
# ///
"""Bootstrap router for the dekatron controller/PSU (adapted from nanovolt-divider's route_pcb.py).

A* on a 0.1 mm grid, two layers, 45-degree moves with turn penalties; clearance from Euclidean
distance transforms of the copper already placed, **per net class** (docs/hardware.md D13):

    HV to anything 3.0 mm, HV to another HV net 1.5 mm, VB / HVSTR 1.5 mm, BIAS 0.8 mm, else 0.2 mm;
    board edge 3.0 mm for HV, 0.5 mm otherwise.

Nets are routed one at a time in ORDER (power loops, HV switching path, tripler, strings, signals,
GND last); there is no rip-up, so a failed net means changing the order or the placement rather
than loosening a rule. GND pads inside the GND pour regions count as connected to the pour.

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  hardware/dekatron/dekatron.kicad_pcb build/geom.json
    uv run tools/route_pcb.py build/geom.json build/routes.json [promote.json]
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/dekatron/dekatron.kicad_pcb build/routes.json
"""
import fnmatch
import heapq
import json
import math
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

G = 0.1
MARG = 0.075        # raster error on the 0.1 mm grid reaches ~0.07 mm (DRC found 0.15 mm gaps at 0.05)
MARG_FINE = 0.08    # on the LM5156 pins, where the real gap is 0.30 mm against a 0.2 mm rule
VIA_MARG = 0.12     # vias: raster error of the drilled circle against diagonal tracks (DRC found 0.161 mm)
VIA_D = 0.7
VIA_DRILL = 0.35    # as pcb_io.py
TRK_MARG = 0.05     # extra margin against other nets' tracks: a thin diagonal's raster sits ~0.05 mm inside
                    # its real edge (DRC: a 1 mm VIN_PROT end 0.153 mm from a 0.25 mm PGOOD diagonal). Not
                    # for the LM5156 pin nets, whose escapes it walls in (PGOOD then fails)
PAD_MARG = 0.03     # extra margin against other nets' pads: a pad's raster can sit a cell inside its real
                    # outline, so a diagonal track grazing a pad corner came out 0.175-0.1875 mm (rule 0.2)
HOLE_GAP = 0.25     # drilled hole to drilled hole (board setup); vias keep it from every plated hole too
VIA_COST = 2.0
TURN = (0.0, 0.12, 0.5)
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
INF = float("inf")
HOLE = 0.4

# ---- policy --------------------------------------------------------------------------------
CLASS_CLR = {"HV": 3.0, "VB": 1.5, "HVSTR": 1.5, "BIAS": 0.8, "Default": 0.2}
CLASS_PATTERNS = [("HV", "HV"), ("HV", "*HV_STACK"), ("HV", "*TRP_P1"), ("HV", "*TRP_N2"), ("HV", "*TRP_P2"),
                  ("HV", "*ANODE"), ("VB", "*/V_B"), ("VB", "*/V_BT"), ("VB", "V_B_BIAS"), ("VB", "*/SW"),
                  ("VB", "*/TRP_PUMP"), ("HVSTR", "*/STR_*"), ("BIAS", "*/GPLUS"), ("BIAS", "*/RTN"),
                  ("BIAS", "*/TUBE_*"), ("BIAS", "*/NDX_C")]
CLASSES = list(CLASS_CLR)


def net_class(n):
    for c, p in CLASS_PATTERNS:
        if fnmatch.fnmatchcase(n, p):
            return c
    return "Default"


def pair_clr(a, b):
    """D13: adjacent tripler / string nodes differ by <= ~300 V, so HV to HV, VB or HVSTR is 1.5 mm;
    HV to bias or logic nets (up to ~450 V) is 3.0 mm."""
    hv_near = {"HV", "VB", "HVSTR"}
    if (a == "HV" and b in hv_near) or (b == "HV" and a in hv_near):
        return 1.5
    return max(CLASS_CLR[a], CLASS_CLR[b])


WIDTH = {"+12V_RAW": 1.0, "/power/+12V_FUSED": 1.0, "VIN_PROT": 1.0, "+12V_NIX": 0.8, "/power/12V_HV": 0.6,
         "/power/BUCK_SW": 0.5, "/power/5V_BUCK": 0.8, "+5V": 0.6, "5V_DISP": 0.5, "5V_MCU": 0.5, "5V_NIX": 0.5,
         "/power/SW": 0.6, "/power/Q102_S": 0.6, "GND": 0.5}


# Nets on the LM5156's 0.65 mm-pitch pins: a 0.3 mm escape between 0.4 mm pads has 0.30 mm of real
# clearance, but on the 0.1 mm raster the halo (0.2 + 0.15 + MARG) equals the measured distance and
# the escape reads as blocked; 0.25 mm clears it (fab minimum 0.152 mm)
FINE = {"/power/LM5156_GATE", "/power/LM5156_CS", "/power/LM5156_COMP", "/power/LM5156_FB", "/power/LM5156_SS",
        "/power/LM5156_RT", "/power/VDRV", "PGOOD", "/power/HV_EN_PIN"}


def width(net):
    if net in FINE:
        return 0.25
    if net in WIDTH:
        return WIDTH[net]
    c = net_class(net)
    return 0.4 if c in ("HV", "VB", "HVSTR") else 0.3


# fine-pitch parts whose signal pins get a reserved escape stub (mm), and the stub width
FANOUT = {"U106": 1.0}
FANOUT_SKIP = {("U106", "8")}     # COMP leaves its end pin sideways to C118; a stub there pockets VDRV (pin 9)
STUB_W = 0.25
# Fixed pad-to-pad ties laid before routing, under a package body where no other net can reach. The
# LM66100s' CE (pin 3) joins VOUT (pin 6, the opposite corner): routed around the package it walled in
# GND (pin 2) and ST (pin 5, to GND), so it runs under the body instead: from pin 3 in to the body
# centreline, along it, and out to pin 6 (0.33 mm from pins 2 and 5). (ref, from pin, to pin, across pin
# pair that sets the centreline)
BRIDGES = [(u, "3", "6", ("2", "5")) for u in ("U102", "U103", "U104")]
# Fixed GND escapes: a short track straight out of the pad to a via 0.65 mm past its outer end (0.45 mm
# from the neighbouring pads), into the bottom pour. At 0.65 mm pitch the top pour cannot reach a
# middle pin between its neighbours, and the routed neighbours closed the outer end (LM66100 GND pin 2
# and ST pin 5 ended up on pour islands).
GND_ESCAPES = [(u, n) for u in ("U102", "U103", "U104") for n in ("2", "5")] + [
    ("D301", "1")]   # BAT54S below U301: its GND pin sat in a walled-in pour pocket (GND repair could not reach it)
GND_ESCAPE_GAP = 0.65
BRIDGE_W = 0.2       # 0.225 mm from pins 2 and 5 (0.25 would sit exactly on the 0.2 mm rule)

FIRST = ["+12V_RAW", "/power/+12V_FUSED", "VIN_PROT", "/power/BUCK_SW", "/power/5V_BUCK", "/power/BUCK_BOOT",
         "+5V", "5V_MCU", "5V_NIX", "5V_DISP",      # long 5 V feeds before the board fills up
         "/power/12V_HV", "/power/SW", "/power/Q102_S", "/power/LM5156_GATE", "/power/Q102_G", "/power/LM5156_CS",
         "/power/V_B", "/power/TRP_PUMP", "/power/TRP_P1", "/power/TRP_P2", "/power/V_BT", "/power/TRP_N2",
         "/power/HV_STACK", "HV", "/tube/ANODE", "V_B_BIAS", "/tube/GPLUS", "/tube/RTN", "+5V", "VDRV"]


PROMOTE = []        # nets that failed in an earlier pass: routed first (tools/route_loop.sh)
REPAIR = False      # --repair PREV.json: keep PREV's copper and re-route GND against the real fill
NODE_LIMIT = [1_500_000]   # A* expansions per connection; the GND repair gets more (long detours)


def order(nets):
    # the LM5156's fine-pitch pins first: any earlier net running past the pin tips seals them in
    # (12V_HV along the left row, HV_EN_PIN along the right row did exactly that)
    # EN last: its pin is top-left but its parts sit below-right, so on the top layer it can only cross
    # the whole row; routed last it must take a via
    # top row: RT / SS / FB (short, straight up to their parts), COMP (a 2 mm hop sideways from end pin 8
    # to C118), then VDRV, whose pin 9 sits between FB and COMP and must go around both
    fine = [n for n in ("/power/LM5156_GATE", "/power/LM5156_CS", "/power/LM5156_RT", "/power/LM5156_SS",
                        "/power/LM5156_FB", "/power/LM5156_COMP", "/power/VDRV", "PGOOD",
                        "/power/HV_EN_PIN") if n in nets]
    first = fine + [n for n in FIRST if n in nets and n not in fine]
    promoted = [n for n in PROMOTE if n in nets and n not in fine]       # after the LM5156 group
    first = fine + promoted + [n for n in first if n not in promoted and n not in fine]
    hv = sorted(n for n in nets if n not in first and net_class(n) != "Default")
    rest = sorted(n for n in nets if n not in first and n not in hv and n != "GND")
    out = []
    for n in first + hv + rest + (["GND"] if "GND" in nets else []):
        if n not in out:                          # each net exactly once (a repeat re-routed +5V over itself)
            out.append(n)
    return out


# ---- raster helpers --------------------------------------------------------------------------
class Raster:
    def __init__(self, bw, bh):
        self.NX, self.NY = int(round(bw / G)) + 1, int(round(bh / G)) + 1

    def blank(self):
        return Image.new("1", (self.NX, self.NY), 0)

    @staticmethod
    def arr(img):
        return np.array(img, dtype=bool)

    @staticmethod
    def poly(dr, pts):
        dr.polygon([(x / G, y / G) for x, y in pts], fill=1, outline=1)

    @staticmethod
    def circle(dr, x, y, r):
        dr.ellipse([(x - r) / G, (y - r) / G, (x + r) / G, (y + r) / G], fill=1, outline=1)

    def seg(self, dr, a, b, w):
        (x1, y1), (x2, y2) = a, b
        r = w / 2
        L = math.hypot(x2 - x1, y2 - y1)
        if L > 1e-9:
            nx, ny = -(y2 - y1) / L * r, (x2 - x1) / L * r
            self.poly(dr, [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
        for x, y in (a, b):
            self.circle(dr, x, y, r)


class Board:
    def __init__(self, geom):
        xs = [p for e in geom["edges"] for p in (e["start"][0], e["end"][0])]
        ys = [p for e in geom["edges"] for p in (e["start"][1], e["end"][1])]
        self.W, self.H = max(xs), max(ys)
        self.R = R = Raster(self.W, self.H)
        self.NX, self.NY = R.NX, R.NY
        self.net_id, self.names, self.cls = {}, [], []
        self.own = [np.full((R.NY, R.NX), -1, np.int32) for _ in range(2)]
        edge = np.ones((R.NY, R.NX), bool)
        edge[1:-1, 1:-1] = False
        self.d_edge = ndimage.distance_transform_edt(~edge) * G
        hole = np.zeros((R.NY, R.NX), bool)
        phole = np.zeros((R.NY, R.NX), bool)                 # every drilled hole, plated or not
        self.padcell = np.zeros((R.NY, R.NX), bool)
        self.pads = {}
        for p in geom["pads"]:
            if p["drill"] > 0:
                img = R.blank()
                R.circle(ImageDraw.Draw(img), p["pos"][0], p["pos"][1], p["drill"] / 2)
                phole |= R.arr(img)
            if not p["net"]:
                if p["drill"] > 0:
                    img = R.blank()
                    R.circle(ImageDraw.Draw(img), p["pos"][0], p["pos"][1], p["drill"] / 2)
                    hole |= R.arr(img)
                if not p["poly"]:
                    continue
            L = 0 if p["layer"] == "F" else 1
            img = R.blank()
            dr = ImageDraw.Draw(img)
            for pp in p["poly"]:
                R.poly(dr, pp)
            m = R.arr(img)
            nid = self.nid(p["net"] or f"__nc_{p['ref']}_{p['num']}")
            self.own[L][m & (self.own[L] == -1)] = nid
            self.padcell |= m
            if not p["net"]:
                continue
            key = (p["ref"], p["num"])
            lst = self.pads.setdefault(p["net"], [])
            ent = next((q for q in lst if q["key"] == key), None)
            if ent is None:
                ent = {"key": key, "pos": p["pos"], "mask": [None, None]}
                lst.append(ent)
            ent["mask"][L] = m
        self.d_hole = ndimage.distance_transform_edt(~hole) * G
        self.d_phole = ndimage.distance_transform_edt(~phole) * G
        self.novia = np.zeros((R.NY, R.NX), bool)       # rule areas without vias (under the RP2040-Zero)
        for poly in geom.get("novia", []):
            img = R.blank()
            R.poly(ImageDraw.Draw(img), poly)
            self.novia |= R.arr(img)
        # escape corridors: a stub straight out of each signal pin of a fine-pitch part, owned by the
        # pin's net, so no other net can run along the pin tips and seal the row
        self.stubs = {}
        self.near_fine = np.zeros((R.NY, R.NX), bool)
        for ref, length in FANOUT.items():
            mine = [p for p in geom["pads"] if p["ref"] == ref and p["num"] and p["layer"] == "F" and p["poly"]]
            sig = [p for p in mine if p["net"] and p["net"] != "GND" and p["drill"] == 0
                   and not p["net"].startswith("unconnected")      # an NC pin needs no corridor
                   and (ref, p["num"]) not in FANOUT_SKIP]
            if not sig:
                continue
            cx = sum(p["pos"][0] for p in mine) / len(mine)
            cy = sum(p["pos"][1] for p in mine) / len(mine)
            for p in sig:
                xs = [q[0] for poly in p["poly"] for q in poly]
                ys = [q[1] for poly in p["poly"] for q in poly]
                dx, dy = p["pos"][0] - cx, p["pos"][1] - cy
                if abs(dx) > abs(dy):            # pins on the left / right edge
                    sx = 1 if dx > 0 else -1
                    tip = (max(xs) if sx > 0 else min(xs), p["pos"][1])
                    end = (tip[0] + sx * length, tip[1])
                else:                            # pins on the top / bottom edge
                    sy = 1 if dy > 0 else -1
                    tip = (p["pos"][0], max(ys) if sy > 0 else min(ys))
                    end = (tip[0], tip[1] + sy * length)
                img = R.blank()
                R.seg(ImageDraw.Draw(img), tip, end, STUB_W)
                m = R.arr(img)
                nid = self.nid(p["net"])
                self.own[0][m & (self.own[0] == -1)] = nid
                self.stubs.setdefault(p["net"], []).append(((tip, end), m))
                self.near_fine |= m
            for p in mine:
                for poly in p["poly"]:
                    img = R.blank()
                    R.poly(ImageDraw.Draw(img), poly)
                    self.near_fine |= R.arr(img)
        self.near_fine = ndimage.binary_dilation(self.near_fine, iterations=4)     # 0.4 mm around them
        self.pour = np.zeros((R.NY, R.NX), bool)
        for z in geom["zones"]:
            if z["net"] == "GND":
                img = R.blank()
                R.poly(ImageDraw.Draw(img), z["poly"])
                self.pour |= R.arr(img)
        # GND repair (--repair): the real main fill fragment per layer, not the zone outline
        self.fill = [np.zeros((R.NY, R.NX), bool), np.zeros((R.NY, R.NX), bool)]
        for f in geom.get("gndfill", []):
            img = R.blank()
            dr = ImageDraw.Draw(img)
            dr.polygon([(x / G, y / G) for x, y in f["outline"]], fill=1)
            for hole in f["holes"]:
                dr.polygon([(x / G, y / G) for x, y in hole], fill=0)
            self.fill[0 if f["layer"] == "F" else 1] |= ndimage.binary_erosion(R.arr(img), iterations=2)
        self.tracks, self.vias = [], []

    def nid(self, name):
        if name not in self.net_id:
            self.net_id[name] = len(self.names)
            self.names.append(name)
            self.cls.append(net_class(name) if not name.startswith("__nc") else "Default")
        return self.net_id[name]

    def add_track(self, net, L, w, pts):
        img = self.R.blank()
        dr = ImageDraw.Draw(img)
        for a, b in zip(pts, pts[1:]):
            self.R.seg(dr, a, b, w)
        m = self.R.arr(img)
        nid = self.nid(net)
        self.own[L][m & (self.own[L] == -1)] = nid
        self.tracks.append((net, L, w, [tuple(map(float, p)) for p in pts]))
        return m

    def add_via(self, net, x, y):
        for n, vx, vy in self.vias:              # reuse a same-net via on (almost) the same spot
            if n == net and math.hypot(vx - x, vy - y) < 0.3:
                img = self.R.blank()
                self.R.circle(ImageDraw.Draw(img), vx, vy, VIA_D / 2)
                return self.R.arr(img)
        img = self.R.blank()
        self.R.circle(ImageDraw.Draw(img), x, y, VIA_D / 2)
        m = self.R.arr(img)
        nid = self.nid(net)
        for L in (0, 1):
            self.own[L][m & (self.own[L] == -1)] = nid
        self.vias.append((net, float(x), float(y)))
        return m


def cells(mask):
    j, i = np.nonzero(mask)
    return list(zip(j.tolist(), i.tolist()))


def astar(B, srcs, tgt, blk, vblk, hxy):
    NX, NY = B.NX, B.NY
    tx, ty = hxy
    ti, tj = tx / G, ty / G

    def h(i, j):
        dx, dy = abs(i - ti), abs(j - tj)
        return (max(dx, dy) + 0.4142 * min(dx, dy)) * G

    best, parent, openh = {}, {}, []
    for (L, j, i) in srcs:
        s = (L, j, i, 8)
        best[s] = 0.0
        heapq.heappush(openh, (h(i, j), 0.0, s))
    n = 0
    while openh:
        f, gc, s = heapq.heappop(openh)
        if gc > best.get(s, INF):
            continue
        L, j, i, d = s
        n += 1
        if n > NODE_LIMIT[0]:
            return None
        if tgt[L][j, i]:
            path = [s]
            while s in parent:
                s = parent[s]
                path.append(s)
            return [(p[0], p[1], p[2]) for p in reversed(path)]
        bl = blk[L]
        for k, (di, dj) in enumerate(DIRS):
            if d != 8:
                t = (k - d) % 8
                t = min(t, 8 - t)
                if t > 2:
                    continue
                tc = TURN[t]
            else:
                tc = 0.0
            ni, nj = i + di, j + dj
            if ni < 0 or nj < 0 or ni >= NX or nj >= NY or bl[nj, ni]:
                continue
            diag = di != 0 and dj != 0
            if diag and (bl[j, ni] or bl[nj, i]):
                continue
            ng = gc + (1.41421 if diag else 1.0) * G * (1.0 if L == 0 else 1.15) + tc
            ns = (L, nj, ni, k)
            if ng < best.get(ns, INF):
                best[ns] = ng
                parent[ns] = s
                heapq.heappush(openh, (ng + h(ni, nj), ng, ns))
        if not vblk[j, i]:
            ns = (1 - L, j, i, 8)
            ng = gc + VIA_COST
            if ng < best.get(ns, INF):
                best[ns] = ng
                parent[ns] = s
                heapq.heappush(openh, (ng + h(i, j), ng, ns))
    return None


def path_to_items(path):
    polys, vias = [], []
    cur = [path[0]]
    for p in path[1:]:
        if p[0] != cur[-1][0]:
            if len(cur) > 1:
                polys.append(cur)
            vias.append((p[2] * G, p[1] * G))
            cur = [p]
        else:
            cur.append(p)
    if len(cur) > 1:
        polys.append(cur)
    out = []
    for poly in polys:
        pts = [(poly[0][2], poly[0][1])]
        for a, b, c in zip(poly, poly[1:], poly[2:]):
            if (b[2] - a[2], b[1] - a[1]) != (c[2] - b[2], c[1] - b[1]):
                pts.append((b[2], b[1]))
        pts.append((poly[-1][2], poly[-1][1]))
        out.append((poly[0][0], [(round(i * G, 3), round(j * G, 3)) for i, j in pts]))
    return out, vias


def snap_ends(polys, own_tracks):
    for end in (0, -1):
        if not polys:
            return
        L, pts = polys[end]
        px, py = pts[end]
        best = None
        for _, tl, tw, tpts in own_tracks:
            if tl != L:
                continue
            for (ax, ay), (bx, by) in zip(tpts, tpts[1:]):
                dx, dy = bx - ax, by - ay
                ll = dx * dx + dy * dy
                t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
                qx, qy = ax + t * dx, ay + t * dy
                d = math.hypot(px - qx, py - qy)
                if d <= tw / 2 + G and (best is None or d < best[0]):
                    best = (d, (round(qx, 4), round(qy, 4)))
        if best and best[0] > 1e-3:
            if end == 0:
                pts.insert(0, best[1])
            else:
                pts.append(best[1])


def main():
    global REPAIR
    geom = json.load(open(sys.argv[1]))
    args = sys.argv[3:]
    prev = None
    if "--repair" in args:
        k = args.index("--repair")
        prev = json.load(open(args[k + 1]))
        REPAIR = True
        NODE_LIMIT[0] = 6_000_000
        del args[k:k + 2]
    if args:
        PROMOTE[:] = json.load(open(args[0]))
    B = Board(geom)
    NX, NY = B.NX, B.NY
    failed = []
    t0 = time.time()
    nets_to_route = order(list(B.pads))
    bridge_m = {}
    if REPAIR:
        for n, L, w, pts in prev["tracks"]:
            B.add_track(n, L, w, [tuple(p) for p in pts])
        for n, x, y in prev["vias"]:
            B.add_via(n, x, y)
        B.stubs = {}                              # the stubs are already in PREV's tracks
        nets_to_route = ["GND"]
    else:
        pos = {(q["ref"], q["num"]): q for q in geom["pads"] if q["layer"] in ("F", "*")}
        for ref, n1, n2, (c1, c2) in BRIDGES:
            p1, p2 = pos[(ref, n1)], pos[(ref, n2)]
            assert p1["net"] == p2["net"], (ref, p1["net"], p2["net"])
            a1, a2 = pos[(ref, c1)]["pos"], pos[(ref, c2)]["pos"]
            ux, uy = (a2[0] - a1[0]) / 2, (a2[1] - a1[1]) / 2        # half-way across the body
            q1, q2 = p1["pos"], p2["pos"]
            m = B.add_track(p1["net"], 0, BRIDGE_W, [tuple(q1), (q1[0] + ux, q1[1] + uy),
                                                     (q2[0] - ux, q2[1] - uy), tuple(q2)])
            bridge_m.setdefault(p1["net"], []).append([m, np.zeros_like(m)])   # its net's copper, like a stub
        others = [q["poly"] for q in geom["pads"] if q["net"] != "GND" and q["layer"] in ("F", "*")]

        def escape_gap(p, q, polys):
            """Closest approach of point p (q None) or segment p-q to the outlines of the other nets' pads."""
            def sd(a, b, c):
                ux, uy = c[0] - b[0], c[1] - b[1]
                ll = ux * ux + uy * uy
                t = 0.0 if ll == 0 else max(0.0, min(1.0, ((a[0] - b[0]) * ux + (a[1] - b[1]) * uy) / ll))
                return math.hypot(a[0] - b[0] - t * ux, a[1] - b[1] - t * uy)
            best = 1e9
            for pl in polys:
                for poly in pl:
                    edges = list(zip(poly, poly[1:] + poly[:1]))
                    if q is None:
                        best = min(best, min(sd(p, e0, e1) for e0, e1 in edges))
                    else:   # segment to polygon: closest of the endpoint/edge combinations (no crossings here)
                        best = min(best, min(min(sd(e0, p, q), sd(p, e0, e1), sd(q, e0, e1)) for e0, e1 in edges))
            return best

        novia_k = ndimage.binary_dilation(B.novia, iterations=int(round((VIA_D / 2 + MARG) / G)))
        for ref, n in GND_ESCAPES:
            pd = pos[(ref, n)]
            assert pd["net"] == "GND", (ref, n, pd["net"])
            mine = [q["pos"] for (r2, _), q in pos.items() if r2 == ref]
            cx, cy = sum(x for x, _ in mine) / len(mine), sum(y for _, y in mine) / len(mine)
            (px, py), poly = pd["pos"], pd["poly"][0]
            dx, dy = px - cx, py - cy
            ln = math.hypot(dx, dy)
            dx, dy = dx / ln, dy / ln
            reach = max((x - px) * dx + (y - py) * dy for x, y in poly)       # pad centre to outer end
            ex, ey = px + dx * reach, py + dy * reach
            for ang in (0, 30, -30, 45, -45, 60, -60):     # straight out first, then angled past a neighbour
                c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                rx, ry = dx * c - dy * s_, dx * s_ + dy * c
                vx, vy = round(ex + rx * GND_ESCAPE_GAP, 4), round(ey + ry * GND_ESCAPE_GAP, 4)
                if (not novia_k[int(round(vy / G)), int(round(vx / G))]      # not under the RP2040-Zero
                        and escape_gap((vx, vy), None, others) >= VIA_D / 2 + 0.3
                        and escape_gap((px, py), (vx, vy), others) >= STUB_W / 2 + 0.2):
                    break
            else:
                raise SystemExit(f"no clear GND escape for {ref} pin {n}")
            mt = B.add_track("GND", 0, STUB_W, [(px, py), (vx, vy)])
            mv = B.add_via("GND", round(vx, 4), round(vy, 4))
            bridge_m.setdefault("GND", []).append([mt | mv, mv])
    for net in nets_to_route:
        w = 0.3 if REPAIR else width(net)     # repair links squeeze between vias into walled-in pour pockets
        nid = B.nid(net)
        mycls = B.cls[nid]
        items = [[m if m is not None else np.zeros((NY, NX), bool) for m in pd["mask"]] for pd in B.pads[net]]
        # bridges and escapes count as the net's copper (items) but not as places a route may start from:
        # that exemption let a 5V_DISP route leave the bridge 0.187 mm from U102's GND pad
        stub_m = [m for _, m in B.stubs.get(net, [])]
        items += [list(m) for m in bridge_m.get(net, [])]
        # the exemption covers the pads' interior only (one cell in): a centreline on a pad's edge puts half
        # the track outside it, next to the neighbouring pin (DRC: GATE 0.125 mm from pin 3)
        own_pads = [ndimage.binary_erosion(np.logical_or.reduce([it[0] for it in items] + stub_m
                                                                + [np.zeros((NY, NX), bool)])),
                    ndimage.binary_erosion(np.logical_or.reduce([it[1] for it in items] + [np.zeros((NY, NX), bool)]))]
        root_item = 0
        if net == "GND" and REPAIR:
            root_item = len(items)                               # grow from the real main pour
            items.append([B.fill[0], B.fill[1]])                 # the real, stitched main pour
            for t in [t for t in B.tracks if t[0] == "GND"]:
                m = np.zeros((NY, NX), bool)
                img = B.R.blank()
                for a, b2 in zip(t[3], t[3][1:]):
                    B.R.seg(ImageDraw.Draw(img), a, b2, t[2])
                m = B.R.arr(img)
                items.append([m, np.zeros((NY, NX), bool)] if t[1] == 0 else [np.zeros((NY, NX), bool), m])
            for n, x, y in [v for v in B.vias if v[0] == "GND"]:
                img = B.R.blank()
                B.R.circle(ImageDraw.Draw(img), x, y, VIA_D / 2)
                m = B.R.arr(img)
                items.append([m, m])
        elif net == "GND":
            items.append([np.zeros((NY, NX), bool), B.pour])   # bottom pour only: top pads stitch down
        for (tip, end), m in B.stubs.get(net, []):
            items.append([m, np.zeros((NY, NX), bool)])      # the stub is part of its pad's net
            B.tracks.append((net, 0, STUB_W, [tip, end]))
        parent = list(range(len(items)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        lab = [ndimage.label(np.logical_or.reduce([it[L] for it in items]))[0] for L in (0, 1)]
        for L in (0, 1):
            for a, it in enumerate(items):
                if it[L].any():
                    ls = set(np.unique(lab[L][it[L]]).tolist()) - {0}
                    for bb, it2 in enumerate(items[:a]):
                        if it2[L].any() and ls & set(np.unique(lab[L][it2[L]]).tolist()):
                            parent[find(a)] = find(bb)

        marg = MARG_FINE if net in FINE else MARG

        def blocked():
            res, vb = [], np.zeros((NY, NX), bool)
            cls_arr = np.array(B.cls + ["Default"])
            for L in (0, 1):
                own = B.own[L]
                other = (own >= 0) & (own != nid)
                blk = np.zeros((NY, NX), bool)
                vbl = np.zeros((NY, NX), bool)
                hard = np.zeros((NY, NX), bool)           # exact pad clearance, kept inside own pads too
                oc = np.where(other, own, len(B.cls))
                ocls = cls_arr[oc]
                for c in CLASSES:
                    m = other & (ocls == c)
                    if not m.any():
                        continue
                    d = ndimage.distance_transform_edt(~m) * G
                    clr = pair_clr(mycls, c)
                    lim = clr + w / 2 + MARG
                    if marg != MARG:                       # fine-pitch nets: the tight margin near the pins only
                        lim = np.where(B.near_fine, clr + w / 2 + marg, lim)
                    blk |= d < lim
                    mp = m & B.padcell                     # other nets' pads: a little more (PAD_MARG)
                    if mp.any():
                        dp = ndimage.distance_transform_edt(~mp) * G
                        blk |= dp < lim + PAD_MARG
                        hard |= dp < clr + w / 2
                    mt = m & ~B.padcell                    # other nets' tracks: TRK_MARG, except the LM5156 group
                    if net not in FINE and mt.any():
                        blk |= ndimage.distance_transform_edt(~mt) * G < lim + TRK_MARG
                    vbl |= d < clr + VIA_D / 2 + VIA_MARG
                e_clr = 3.0 if mycls == "HV" else 0.5
                blk |= B.d_edge < e_clr + w / 2 + MARG
                blk |= B.d_hole < HOLE + w / 2 + MARG
                # never block the net's own pads and escape stubs: a route must be able to start inside
                # its own pad and leave along the pin axis (fine-pitch pads are otherwise covered by the
                # neighbours' halo). Its own tracks stay subject to the halo: a 0.6 mm track centred on
                # the edge of an earlier one would spill into the neighbours' clearance.
                blk &= ~own_pads[L]
                # ...but not where the track's own width would reach a neighbour pad: a 0.5 mm 5V_DISP
                # start on the edge of U102 pin 3 came out 0.187 mm from GND pin 2
                blk |= own_pads[L] & hard
                res.append(blk)
                vb |= vbl
            vb |= B.d_edge < (3.0 if mycls == "HV" else 0.5) + VIA_D / 2 + MARG
            vb |= B.d_hole < HOLE + VIA_D / 2 + MARG
            vb |= B.d_phole < HOLE_GAP + VIA_DRILL / 2 + MARG   # plated holes too (a via 0.21 mm from U106's)
            vb |= ndimage.binary_dilation(B.novia, iterations=int(round((VIA_D / 2 + MARG) / G)))
            vb |= res[0] | res[1]
            return res, vb

        guard = 0
        skip = set()                              # repair: groups that could not be reached (reported)
        while len({find(a) for a in range(len(items))} - skip) > 1 and guard < 80:
            guard += 1
            blk, vblk = blocked()
            roots = {}
            for a in range(len(items)):
                roots.setdefault(find(a), []).append(a)
            start_root = find(root_item)
            src_m = [np.logical_or.reduce([items[a][L] for a in roots[start_root]]) for L in (0, 1)]
            dsrc = ndimage.distance_transform_edt(~(src_m[0] | src_m[1]))
            best_r, best_d = None, INF
            for r, mem in roots.items():
                if r == start_root or r in skip:
                    continue
                mm = np.logical_or.reduce([items[a][0] | items[a][1] for a in mem])
                dd = dsrc[mm].min()
                if dd < best_d:
                    best_d, best_r = dd, r
            tgt_m = [np.logical_or.reduce([items[a][L] for a in roots[best_r]]) for L in (0, 1)]
            # start and end one cell inside the copper: rasters are slightly fat, so a route ending on an
            # item's edge can merely touch it in real copper (DRC: via grazing C108, BUCK_FB unconnected)
            def inner(m):
                e = ndimage.binary_erosion(m)
                return e if e.any() else m
            tgt = [inner(tgt_m[L]) & ~blk[L] for L in (0, 1)]
            srcs = [(L, j, i) for L in (0, 1) for (j, i) in cells(inner(src_m[L]) & ~blk[L])]
            if len(srcs) > 60000:                 # a huge source (the pour): seed from its part nearest the target
                tj, ti = np.nonzero(tgt[0] | tgt[1])
                cx, cy = ti.mean(), tj.mean()
                srcs.sort(key=lambda s: (s[2] - cx) ** 2 + (s[1] - cy) ** 2)
                srcs = srcs[:20000]
            if not srcs or not (tgt[0].any() or tgt[1].any()):
                print(f"  {net}: no free source/target cells")
                failed.append(net)
                break
            tj, ti = np.nonzero(tgt[0] | tgt[1])
            hxy = (ti.mean() * G, tj.mean() * G)
            path = astar(B, srcs, tgt, blk, vblk, hxy)
            if path is None:
                def where(mem):
                    jj, ii = np.nonzero(np.logical_or.reduce([items[a][0] | items[a][1] for a in mem]))
                    return f"({ii.mean() * G:.1f}, {jj.mean() * G:.1f})"
                print(f"  {net}: FAILED between components: {where(roots[start_root])} -> {where(roots[best_r])}; "
                      f"{len(roots)} groups left")
                if REPAIR:                        # report it and try the remaining groups
                    skip.add(best_r)
                    if net not in failed:
                        failed.append(net)
                    continue
                failed.append(net)
                break
            polys, vias = path_to_items(path)
            snap_ends(polys, [t for t in B.tracks if t[0] == net])
            new = [np.zeros((NY, NX), bool), np.zeros((NY, NX), bool)]
            for L, pts in polys:
                new[L] |= B.add_track(net, L, w, pts)
            for (x, y) in vias:
                m = B.add_via(net, x, y)
                new[0] |= m
                new[1] |= m
            items.append(new)
            parent.append(len(parent))
            parent[find(len(items) - 1)] = find(start_root)
            parent[find(best_r)] = find(start_root)
        print(f"{net:28s} {mycls:7s} w={w} {'FAIL' if net in failed else 'ok'}  t={time.time() - t0:.1f}s", flush=True)

    # escape stubs: drop the unused ones, trim the rest back to their farthest junction
    def seg_d(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ll = dx * dx + dy * dy
        t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)

    def reach(net, end):
        """How far along a stub (from the pad) its net's routes join it: track ends and vias that touch
        the stub away from the pad. 0 = unused (a route that starts at the pad itself needs no stub)."""
        tip = STUB_KEYS[(net, end)][0]
        ln = math.hypot(end[0] - tip[0], end[1] - tip[1])
        best = 0.0

        def along(q, r):
            if seg_d(q, tip, end) < r:
                t = ((q[0] - tip[0]) * (end[0] - tip[0]) + (q[1] - tip[1]) * (end[1] - tip[1])) / ln
                return min(max(t, 0.0), ln)
            return 0.0
        for n, Ly, w, pts in B.tracks:
            if n == net and Ly == 0 and (tuple(pts[0]), tuple(pts[-1])) != (tuple(tip), tuple(end)):
                for q in (pts[0], pts[-1]):
                    best = max(best, along(q, w / 2 + STUB_W / 2))
        for n, x, y in B.vias:
            if n == net:
                best = max(best, along((x, y), VIA_D / 2))
        return best if best > 0.02 else 0.0
    STUB_KEYS = {(net, end): (tip, end) for net, lst in B.stubs.items() for (tip, end), _ in lst}
    keep = []
    for t in B.tracks:
        n, L, w, pts = t
        if (n, tuple(pts[-1])) in STUB_KEYS and tuple(pts[0]) == STUB_KEYS[(n, tuple(pts[-1]))][0]:
            tip, end = tuple(pts[0]), tuple(pts[-1])
            r = reach(n, end)
            if r == 0.0:
                continue                          # unused: drop
            f = min(1.0, r / math.hypot(end[0] - tip[0], end[1] - tip[1]))
            t = (n, L, w, [tip, (round(tip[0] + f * (end[0] - tip[0]), 4),
                                 round(tip[1] + f * (end[1] - tip[1]), 4))])     # trim to the farthest junction
        keep.append(t)
    B.tracks = keep
    json.dump({"tracks": B.tracks, "vias": B.vias, "failed": failed}, open(sys.argv[2], "w"))
    print("failed:", failed)


if __name__ == "__main__":
    main()
