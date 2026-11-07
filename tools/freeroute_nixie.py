#!/usr/bin/env python3
"""Route the Nixie board with Freerouting (user-installed, v2.5.0). Run with KiCad's Python:

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/freeroute_nixie.py [passes]

1. exports hardware/nixie/nixie.kicad_pcb to build/nixie.dsn (net-class clearances and widths come
   from nixie.kicad_pro: NCATH 0.25 mm, NHV 1.15 mm);
2. runs Freerouting headless on it (build/nixie.ses, log in build/freerouting.log);
3. imports the session into the board, refills the zones, saves with LF line endings;
4. runs KiCad DRC (report in build/nixie_drc.rpt) and prints its summary.
The board file is rewritten in place; run tools/gen_nixie_pcb.py first for a clean placement.
Set FREEROUTING to the executable if it is not in the default per-user install location.
"""
import os
import subprocess
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "hardware", "nixie", "nixie.kicad_pcb")
BUILD = os.path.join(ROOT, "build")
FREEROUTING = os.environ.get("FREEROUTING",
                             os.path.join(os.environ.get("LOCALAPPDATA", ""), "freerouting", "freerouting.exe"))
KICAD_CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
SOLID_GND = [("R310", "2")]   # starved thermal in the DRC of the 2026-11-06 routing


def import_ses(b, path):
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


def main():
    passes = sys.argv[1] if len(sys.argv) > 1 else "40"
    os.makedirs(BUILD, exist_ok=True)
    dsn, ses = os.path.join(BUILD, "nixie.dsn"), os.path.join(BUILD, "nixie.ses")
    b = pcbnew.LoadBoard(BOARD)
    for t in list(b.GetTracks()):          # start from an unrouted board
        b.Remove(t)
    # GND pours: Freerouting treats an exported zone as a plane that connects everything on it, which
    # left islands after the fill. Route GND as tracks instead and put the pours back afterwards.
    pours = [z for z in b.Zones() if not z.GetIsRuleArea()]
    for z in pours:
        b.Remove(z)
    if not pcbnew.ExportSpecctraDSN(b, dsn):
        raise SystemExit("DSN export failed")
    if os.path.exists(ses):
        os.remove(ses)
    with open(os.path.join(BUILD, "freerouting.log"), "w") as log:
        subprocess.run([FREEROUTING, "--gui.enabled=false", "-de", dsn, "-do", ses, "-mp", passes],
                       stdout=log, stderr=subprocess.STDOUT, check=False)
    if not os.path.exists(ses):
        raise SystemExit("Freerouting wrote no session; see build/freerouting.log")
    print("imported %d track segments, %d vias" % import_ses(b, ses))
    # Freerouting necks tracks down at some pads (0.125-0.15 mm), below the 0.1524 mm fab minimum
    narrow = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetWidth() < pcbnew.FromMM(0.16)]
    for t in narrow:
        t.SetWidth(pcbnew.FromMM(0.16))
    print(f"widened {len(narrow)} neck-down segments to 0.16 mm")
    for z in pours:
        b.Add(z)
    # pads whose second thermal spoke is blocked by a routed track (KiCad wants two): connect solid
    for ref, num in SOLID_GND:
        for pad in b.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == num:
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(BOARD, b)
    raw = open(BOARD, "rb").read()
    open(BOARD, "wb").write(raw.replace(b"\r\n", b"\n"))
    rpt = os.path.join(BUILD, "nixie_drc.rpt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--severity-error", "--schematic-parity", "-o", rpt, BOARD],
                   capture_output=True, check=False)
    tail = [l for l in open(rpt, encoding="utf-8") if l.startswith("**")]
    print("".join(tail))


if __name__ == "__main__":
    main()
