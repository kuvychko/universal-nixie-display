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
    uv run tools/route_pcb.py build/geom.json build/routes.json
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
MARG = 0.05
VIA_D = 0.7
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
         "/power/BUCK_SW": 0.8, "/power/5V_BUCK": 0.8, "+5V": 0.6, "5V_DISP": 0.5, "5V_MCU": 0.5, "5V_NIX": 0.5,
         "/power/SW": 0.6, "/power/Q102_S": 0.6, "GND": 0.5}


def width(net):
    if net in WIDTH:
        return WIDTH[net]
    c = net_class(net)
    return 0.4 if c in ("HV", "VB", "HVSTR") else 0.3


FIRST = ["+12V_RAW", "/power/+12V_FUSED", "VIN_PROT", "/power/BUCK_SW", "/power/5V_BUCK", "/power/BUCK_BOOT",
         "/power/12V_HV", "/power/SW", "/power/Q102_S", "/power/LM5156_GATE", "/power/Q102_G", "/power/LM5156_CS",
         "/power/V_B", "/power/TRP_PUMP", "/power/TRP_P1", "/power/TRP_P2", "/power/V_BT", "/power/TRP_N2",
         "/power/HV_STACK", "HV", "/tube/ANODE", "V_B_BIAS", "/tube/GPLUS", "/tube/RTN", "+5V", "VDRV"]


def order(nets):
    first = [n for n in FIRST if n in nets]
    hv = sorted(n for n in nets if n not in first and net_class(n) != "Default")
    rest = sorted(n for n in nets if n not in first and n not in hv and n != "GND")
    return first + hv + rest + (["GND"] if "GND" in nets else [])


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
        self.pads = {}
        for p in geom["pads"]:
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
        self.pour = np.zeros((R.NY, R.NX), bool)
        for z in geom["zones"]:
            if z["net"] == "GND":
                img = R.blank()
                R.poly(ImageDraw.Draw(img), z["poly"])
                self.pour |= R.arr(img)
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
        if n > 4_000_000:
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
    geom = json.load(open(sys.argv[1]))
    B = Board(geom)
    NX, NY = B.NX, B.NY
    failed = []
    t0 = time.time()
    for net in order(list(B.pads)):
        w = width(net)
        nid = B.nid(net)
        mycls = B.cls[nid]
        items = [[m if m is not None else np.zeros((NY, NX), bool) for m in pd["mask"]] for pd in B.pads[net]]
        if net == "GND":
            items.append([B.pour, B.pour])        # the GND pour on both layers counts as one item
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

        def blocked():
            res, vb = [], np.zeros((NY, NX), bool)
            cls_arr = np.array(B.cls + ["Default"])
            for L in (0, 1):
                own = B.own[L]
                other = (own >= 0) & (own != nid)
                blk = np.zeros((NY, NX), bool)
                vbl = np.zeros((NY, NX), bool)
                oc = np.where(other, own, len(B.cls))
                ocls = cls_arr[oc]
                for c in CLASSES:
                    m = other & (ocls == c)
                    if not m.any():
                        continue
                    d = ndimage.distance_transform_edt(~m) * G
                    clr = pair_clr(mycls, c)
                    blk |= d < clr + w / 2 + MARG
                    vbl |= d < clr + VIA_D / 2 + MARG
                e_clr = 3.0 if mycls == "HV" else 0.5
                blk |= B.d_edge < e_clr + w / 2 + MARG
                blk |= B.d_hole < HOLE + w / 2 + MARG
                # never block the net's own copper: a route must be able to start inside its own pad
                # and leave along the pin axis (fine-pitch pads are otherwise fully covered by the
                # neighbours' clearance halo)
                blk &= ~(own == nid)
                res.append(blk)
                vb |= vbl
            vb |= B.d_edge < (3.0 if mycls == "HV" else 0.5) + VIA_D / 2 + MARG
            vb |= B.d_hole < HOLE + VIA_D / 2 + MARG
            vb |= res[0] | res[1]
            return res, vb

        guard = 0
        while len({find(a) for a in range(len(items))}) > 1 and guard < 80:
            guard += 1
            blk, vblk = blocked()
            roots = {}
            for a in range(len(items)):
                roots.setdefault(find(a), []).append(a)
            start_root = find(0)
            src_m = [np.logical_or.reduce([items[a][L] for a in roots[start_root]]) for L in (0, 1)]
            dsrc = ndimage.distance_transform_edt(~(src_m[0] | src_m[1]))
            best_r, best_d = None, INF
            for r, mem in roots.items():
                if r == start_root:
                    continue
                mm = np.logical_or.reduce([items[a][0] | items[a][1] for a in mem])
                dd = dsrc[mm].min()
                if dd < best_d:
                    best_d, best_r = dd, r
            tgt_m = [np.logical_or.reduce([items[a][L] for a in roots[best_r]]) for L in (0, 1)]
            tgt = [tgt_m[L] & ~blk[L] for L in (0, 1)]
            srcs = [(L, j, i) for L in (0, 1) for (j, i) in cells(src_m[L] & ~blk[L])]
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
                print(f"  {net}: FAILED between components")
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

    json.dump({"tracks": B.tracks, "vias": B.vias, "failed": failed}, open(sys.argv[2], "w"))
    print("failed:", failed)


if __name__ == "__main__":
    main()
