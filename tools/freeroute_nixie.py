#!/usr/bin/env python3
"""Route the Nixie board with Freerouting (user-installed, v2.5.0). Run with KiCad's Python:

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/freeroute_nixie.py [passes] [--hv-from BOARD]

--hv-from BOARD copies NIX_HV's tracks and vias from BOARD (a copy of an earlier routing with the same
HV pad positions) into the board as locked copper before routing; the DSN exports them as protected
wiring, so Freerouting routes everything else around a known-good HV path (2026-11-11: left to
itself it took 280-390 mm with 2-4 vias where the 2026-11-10 routing had 193 mm and none).

1. exports hardware/nixie/nixie.kicad_pcb to build/nixie.dsn (net-class clearances and widths come
   from nixie.kicad_pro: NCATH 0.25 mm, NHV 1.25 mm);
2. runs Freerouting headless on it (build/nixie.ses, log in build/freerouting.log);
3. imports the session into the board, refills the zones, saves with LF line endings;
4. runs KiCad DRC (report in build/nixie_drc.rpt) and prints its summary.
The board file is rewritten in place; run tools/gen_nixie_pcb.py first for a clean placement.
Set FREEROUTING to the executable if it is not in the default per-user install location.
"""
import os
import re
import subprocess
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "hardware", "nixie", "nixie.kicad_pcb")
BUILD = os.path.join(ROOT, "build")
FREEROUTING = os.environ.get("FREEROUTING",
                             os.path.join(os.environ.get("LOCALAPPDATA", ""), "freerouting", "freerouting.exe"))
KICAD_CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
TARGET_R = 3.0               # mm: targeted GND stitching via within this of its pad or signal via
CLEARANCE_MARGIN_UM = 20     # added to every DSN clearance: Freerouting rounding (2-3 um) and widening its neck-downs to 0.16 mm (25 left a net unrouted)


def import_ses(b, path, skip=()):
    """Add the wires and vias of a Freerouting session to board b.

    pcbnew.ImportSpecctraSES() returns False on Freerouting 2.5.0 sessions in KiCad 10.0.5 (no
    message), so the session is read here: resolution `um 10` (0.1 um units), Specctra y up, i.e.
    KiCad position = (x, -y). Via padstacks are named `Via[0-1]_<dia>:<drill>_um`.
    """
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location("gs", os.path.join(ROOT, "tools", "gen_schematics.py"))
    gs = importlib.util.module_from_spec(spec)
    sys.modules["gs"] = gs
    spec.loader.exec_module(gs)
    t = gs.parse(open(path, encoding="utf-8").read())
    routes = gs.find(t, "routes")
    res = gs.find(routes, "resolution")
    unit = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4}[res[1]] / float(res[2])   # mm per count
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    nets = {n.GetNetname(): n for n in b.GetNetsByName().values()}

    def pos(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(float(x) * unit), pcbnew.FromMM(-float(y) * unit))

    n_tracks = n_vias = 0
    for net in gs.find_all(gs.find(routes, "network_out"), "net"):
        if gs.unq(net[1]) in skip:
            continue
        ni = nets[gs.unq(net[1])]
        for w in gs.find_all(net, "wire"):
            p = gs.find(w, "path")
            layer, width, xy = layers[gs.unq(p[1])], float(p[2]) * unit, p[3:]
            pts = [pos(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]
            for a, c in zip(pts, pts[1:]):
                tr = pcbnew.PCB_TRACK(b)
                tr.SetStart(a)
                tr.SetEnd(c)
                tr.SetWidth(pcbnew.FromMM(width))
                tr.SetLayer(layer)
                tr.SetNet(ni)
                b.Add(tr)
                n_tracks += 1
        for v in gs.find_all(net, "via"):
            m = re.search(r"_(\d+):(\d+)_um", gs.unq(v[1]))
            via = pcbnew.PCB_VIA(b)
            via.SetPosition(pos(v[2], v[3]))
            via.SetWidth(pcbnew.F_Cu, pcbnew.FromMM(int(m.group(1)) / 1000))
            via.SetDrill(pcbnew.FromMM(int(m.group(2)) / 1000))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(ni)
            b.Add(via)
            n_vias += 1
    return n_tracks, n_vias


def targeted_stitch(b, pcb_io):
    """GND vias where the return current needs them: within TARGET_R of each SMD GND pad (bypass
    caps, IC ground pins) and of each Default-class signal via (the return changes layer with the
    signal; NCATH and NHV carry DC or slowly multiplexed current).
    A target that already has a GND via within its radius is skipped. A candidate must sit with a
    pcb_io.STITCH_RING circle inside both GND fills and pcb_io.STITCH_HOLE from every hole."""
    import math
    fills = {z.GetLayer(): z.GetFilledPolysList(z.GetLayer()) for z in b.Zones()
             if not z.GetIsRuleArea() and z.GetNetname() == "GND"}
    if len(fills) < 2:
        return 0
    keep_out = [z.Outline() for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    P = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))  # noqa: E731
    xy = lambda p: (pcbnew.ToMM(p.x), pcbnew.ToMM(p.y))  # noqa: E731
    holes, gnd_vias, targets = [], [], []
    ns = b.GetDesignSettings().m_NetSettings
    for v in b.GetTracks():
        if v.Type() == pcbnew.PCB_VIA_T:
            holes.append(xy(v.GetPosition()))
            if v.GetNetname() == "GND":
                gnd_vias.append(xy(v.GetPosition()))
            elif ns.GetEffectiveNetClass(v.GetNetname()).GetName() == "Default":   # not DC HV/cathodes
                targets.append(xy(v.GetPosition()))
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetDrillSize().x > 0:
                holes.append(xy(pad.GetPosition()))
            elif pad.GetNetname() == "GND":
                targets.insert(0, xy(pad.GetPosition()))
    ring = [(pcb_io.STITCH_RING * math.cos(k * math.pi / 4), pcb_io.STITCH_RING * math.sin(k * math.pi / 4))
            for k in range(8)] + [(0, 0)]
    gnd = b.FindNet("GND")
    n = 0
    for tx, ty in targets:
        if any(math.hypot(tx - gx, ty - gy) <= TARGET_R for gx, gy in gnd_vias):
            continue
        for r in (0.9, 1.2, 1.5, 2.0, 2.5, TARGET_R):
            cand = [(tx + r * math.cos(k * math.pi / 8), ty + r * math.sin(k * math.pi / 8)) for k in range(16)]
            ok = [(x, y) for x, y in cand
                  if all(f.Contains(P(x + dx, y + dy)) for f in fills.values() for dx, dy in ring)
                  and not any(k.Contains(P(x, y)) for k in keep_out)
                  and all(math.hypot(x - hx, y - hy) >= pcb_io.STITCH_HOLE for hx, hy in holes)]
            if ok:
                x, y = ok[0]
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(P(x, y))
                v.SetWidth(pcbnew.FromMM(pcb_io.VIA_D))
                v.SetDrill(pcbnew.FromMM(pcb_io.VIA_DRILL))
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(gnd)
                b.Add(v)
                holes.append((x, y))
                gnd_vias.append((x, y))
                n += 1
                break
    return n


def save(b):
    pcbnew.SaveBoard(BOARD, b)
    raw = open(BOARD, "rb").read()
    open(BOARD, "wb").write(raw.replace(b"\r\n", b"\n"))


def drc():
    rpt = os.path.join(BUILD, "nixie_drc.rpt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--severity-error", "--schematic-parity", "-o", rpt, BOARD],
                   capture_output=True, check=False)
    return rpt


def copy_net(b, src_path, net):
    """Copy one net's tracks and vias from board src_path into b, locked."""
    src = pcbnew.LoadBoard(src_path)
    ni = b.FindNet(net)
    n = 0
    for t in src.GetTracks():
        if t.GetNetname() != net:
            continue
        c = t.Duplicate()
        c.SetParent(b)
        c.SetNet(ni)
        c.SetLocked(True)
        b.Add(c)
        n += 1
    return n


def main():
    args = sys.argv[1:]
    hv_from = None
    if "--hv-from" in args:
        i = args.index("--hv-from")
        hv_from = args[i + 1]
        del args[i:i + 2]
    passes = args[0] if args else "40"
    os.makedirs(BUILD, exist_ok=True)
    dsn, ses = os.path.join(BUILD, "nixie.dsn"), os.path.join(BUILD, "nixie.ses")
    b = pcbnew.LoadBoard(BOARD)
    for t in list(b.GetTracks()):          # start from an unrouted board
        b.Remove(t)
    if hv_from:
        print(f"kept NIX_HV from {hv_from}: {copy_net(b, hv_from, 'NIX_HV')} tracks/vias, locked")
    # GND pours: Freerouting treats an exported zone as a plane that connects everything on it, which
    # left islands after the fill. Route GND as tracks instead and put the pours back afterwards.
    # Fill-only rule areas (no pour in the tube lead rings) leave too: the DSN export turns every rule
    # area into a full keepout, which would shut the router out of the rings.
    pours = [z for z in b.Zones() if not z.GetIsRuleArea()
             or not (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias())]
    for z in pours:
        b.Remove(z)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        raise SystemExit("DSN export failed")
    txt = open(dsn, encoding="utf-8").read()
    # (the IN-14's own pads, 1.156 mm apart, then show as fixed pin-to-pin violations in the log)
    txt = re.sub(r"\(clearance (\d+)\)", lambda m: "(clearance %d)" % (int(m.group(1)) + CLEARANCE_MARGIN_UM), txt)
    # Freerouting spaces vias of every net class by the structure (Default) clearance; NCATH needs more
    txt = txt.replace("(clearance 50 (type smd_smd))", "(clearance 50 (type smd_smd))\n      "
                      "(clearance %d (type via_via))" % (250 + CLEARANCE_MARGIN_UM), 1)
    open(dsn, "w", encoding="utf-8").write(txt)
    if os.path.exists(ses):
        os.remove(ses)
    with open(os.path.join(BUILD, "freerouting.log"), "w") as log:
        subprocess.run([FREEROUTING, "--gui.enabled=false", "-de", dsn, "-do", ses, "-mp", passes],
                       stdout=log, stderr=subprocess.STDOUT, check=False)
    if not os.path.exists(ses):
        raise SystemExit("Freerouting wrote no session; see build/freerouting.log")
    print("imported %d track segments, %d vias" % import_ses(b, ses, ("NIX_HV",) if hv_from else ()))
    # Freerouting necks tracks down at some pads (0.125-0.15 mm), below the 0.1524 mm fab minimum
    narrow = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetWidth() < pcbnew.FromMM(0.16)]
    for t in narrow:
        t.SetWidth(pcbnew.FromMM(0.16))
    print(f"widened {len(narrow)} neck-down segments to 0.16 mm")
    for z in pours:
        b.Add(z)
    # First fill keeps every island: with island removal the stitcher only sees fragments a GND pad
    # or track already reaches, and the vias that would join the rest are never placed (2026-11-11:
    # 82 vias instead of ~300 after a re-route). Islands still unjoined after stitching go below.
    gnd_pours = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "GND"]
    for z in gnd_pours:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    # GND stitching (user, 2026-11-07: 2.5 mm grid plus strategic placement): first a via beside
    # every SMD GND pad and every signal via, then pcb_io.stitch's 2.5 mm grid (as on the dekatron
    # board, 0.7/0.35 mm vias) wherever both pours have solid copper; none in the lead rings
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import pcb_io
    nt = targeted_stitch(b, pcb_io)
    ns = pcb_io.stitch(b, lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x + pcb_io.OX), pcbnew.FromMM(y + pcb_io.OY)))
    print(f"{nt} targeted + {ns} grid GND stitching vias")
    ns += nt
    for z in gnd_pours:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    # a via that only joined two floating islands is left on bare board once they are removed;
    # drop it and refill until stable (dropping one can orphan another pair)
    dropped = 0
    while True:
        fills = [z.GetFilledPolysList(z.GetLayer()) for z in gnd_pours]
        stray = [v for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"
                 and not all(f.Contains(v.GetPosition()) for f in fills)]
        if not stray:
            break
        for v in stray:
            b.Remove(v)
        dropped += len(stray)
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    print(f"{ns - dropped} GND stitching vias kept ({dropped} dropped on unjoined islands)")
    save(b)
    rpt = drc()
    # pads whose second thermal spoke is blocked by a routed track (KiCad wants two): connect solid
    starved = re.findall(r"\[starved_thermal\].*\n.*\n.*\n.*pad (\S+) \[GND\] of (\S+)",
                         open(rpt, encoding="utf-8").read(), re.IGNORECASE)
    if starved:
        for num, ref in starved:
            for pad in b.FindFootprintByReference(ref).Pads():
                if pad.GetNumber() == num:
                    pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        print("solid GND connection:", ", ".join(f"{r}.{n}" for n, r in starved))
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        save(b)
        rpt = drc()
    tail = [l for l in open(rpt, encoding="utf-8") if l.startswith("**")]
    print("".join(tail))


if __name__ == "__main__":
    main()
