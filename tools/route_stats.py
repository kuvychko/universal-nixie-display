#!/usr/bin/env python3
"""Routing statistics for a board, per net class: track length (mm) by layer and via count.
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/route_stats.py hardware/nixie/nixie.kicad_pcb
"""
import collections
import sys

import pcbnew


def main(path):
    b = pcbnew.LoadBoard(path)
    ns = b.GetDesignSettings().m_NetSettings
    length = collections.defaultdict(float)
    vias = collections.Counter()
    for t in b.GetTracks():
        cls = ns.GetEffectiveNetClass(t.GetNetname()).GetName()
        if t.Type() == pcbnew.PCB_VIA_T:
            vias[cls] += 1
        else:
            length[(cls, t.GetLayerName())] += pcbnew.ToMM(t.GetLength())
    for cls in sorted({c for c, _ in length} | set(vias)):
        f, bk = length[(cls, "F.Cu")], length[(cls, "B.Cu")]
        print(f"{cls:8s} F.Cu {f:7.0f} mm  B.Cu {bk:7.0f} mm  total {f + bk:7.0f} mm  vias {vias[cls]}")


if __name__ == "__main__":
    main(sys.argv[1])
