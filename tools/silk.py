"""Place the reference designators on the silkscreen clear of pads, other silk and the board edge.

Run with KiCad's Python on the finished board (last step of the PCB chain; it only moves text):

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/silk.py hardware/dekatron/dekatron.kicad_pcb

Each reference is tried at positions around its footprint's courtyard (all four sides, sliding
along each side, stepping away from it), upright or at 90 degrees, at 1.0 or 0.8 mm text
height. A candidate must stay off every pad (mask opening plus margin), every silkscreen graphic,
the references already placed, and the board edge and holes; positions that also keep off other
parts' courtyards (so the text is not hidden under a part) win. The most constrained parts go
first. A reference with no legal spot is hidden on the silkscreen (it stays on the Fab layer)
and listed.
"""
import math
import sys

import pcbnew

MM = pcbnew.FromMM
PAD_CLR = MM(0.15)        # text to pad copper: covers the mask expansion plus registration
SILK_CLR = MM(0.12)       # text to other silkscreen
EDGE_CLR = MM(0.5)        # text to the board edge
SIZES = (1.0, 0.8)        # text heights, mm (0.8 = the board's minimum); stroke 15 % of height
GAPS = [0.1 + 0.2 * k for k in range(10)]          # distance off the courtyard, mm
SLIDES = [0.0, -0.4, 0.4, -0.8, 0.8, -1.2, 1.2, -1.8, 1.8, -2.5, 2.5]   # along the side, mm


def body_box(fp):
    """Courtyard box, or the footprint's pad and graphics box when it has no courtyard."""
    side = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    bbs = [g.GetBoundingBox() for g in fp.GraphicalItems() if g.GetLayer() == side]
    if not bbs:
        bbs = [p.GetBoundingBox() for p in fp.Pads()] or [pcbnew.BOX2I(fp.GetPosition(), pcbnew.VECTOR2I(0, 0))]
    x0, y0 = min(bb.GetLeft() for bb in bbs), min(bb.GetTop() for bb in bbs)
    x1, y1 = max(bb.GetRight() for bb in bbs), max(bb.GetBottom() for bb in bbs)
    return pcbnew.BOX2I(pcbnew.VECTOR2I(x0, y0), pcbnew.VECTOR2I(x1 - x0, y1 - y0))


def main(path):
    b = pcbnew.LoadBoard(path)
    fps = list(b.GetFootprints())
    edge = b.GetBoardEdgesBoundingBox()
    inner = pcbnew.BOX2I(pcbnew.VECTOR2I(edge.GetX() + EDGE_CLR, edge.GetY() + EDGE_CLR),
                         pcbnew.VECTOR2I(edge.GetWidth() - 2 * EDGE_CLR, edge.GetHeight() - 2 * EDGE_CLR))

    def side_of(fp):
        return (pcbnew.B_SilkS, pcbnew.B_Cu, pcbnew.B_CrtYd) if fp.IsFlipped() else \
               (pcbnew.F_SilkS, pcbnew.F_Cu, pcbnew.F_CrtYd)

    yard_of = {fp.GetReference(): body_box(fp) for fp in fps}

    # fixed obstacles per side: pad copper, footprint silk graphics, board silk, courtyards
    obst = {}
    for silk, cu, crt in ((pcbnew.F_SilkS, pcbnew.F_Cu, pcbnew.F_CrtYd), (pcbnew.B_SilkS, pcbnew.B_Cu, pcbnew.B_CrtYd)):
        pads, graphics, yards = [], [], []
        for fp in fps:
            for p in fp.Pads():
                if p.IsOnLayer(cu) or p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    lay = cu if p.IsOnLayer(cu) else pcbnew.Edge_Cuts
                    pads.append((p.GetEffectiveShape(lay), p.GetBoundingBox(), fp))
            for g in fp.GraphicalItems():
                if g.GetLayer() == silk:
                    graphics.append((g.GetEffectiveShape(silk), g.GetBoundingBox(), fp))
            if fp.IsFlipped() == (silk == pcbnew.B_SilkS):
                yards.append((yard_of[fp.GetReference()], fp))
        for d in b.GetDrawings():
            if d.GetLayer() == silk:
                graphics.append((d.GetEffectiveShape(silk), d.GetBoundingBox(), None))
        obst[silk] = dict(pads=pads, graphics=graphics, yards=yards, texts=[])
    def hits(shape, bb, items, clr):
        big = pcbnew.BOX2I(bb.GetPosition(), bb.GetSize())
        big.Inflate(clr)
        return any(ib.Intersects(big) and shape.Collide(s, clr) for s, ib, _ in items)

    def legal(fp, ref, strict):
        silk, _, _ = side_of(fp)
        o = obst[silk]
        bb = ref.GetBoundingBox()
        if not inner.Contains(bb.GetOrigin()) or not inner.Contains(bb.GetEnd()):
            return False
        shape = ref.GetEffectiveShape(silk)
        if hits(shape, bb, o["pads"], PAD_CLR) or hits(shape, bb, o["graphics"], SILK_CLR) \
                or hits(shape, bb, o["texts"], SILK_CLR):
            return False
        if strict:      # not under another part's body
            return not any(fb.Intersects(bb) and f is not fp for fb, f in o["yards"])
        return True

    def candidates(fp):
        box = yard_of[fp.GetReference()]
        cx, cy = box.GetCenter().x, box.GetCenter().y
        hw, hh = box.GetWidth() / 2, box.GetHeight() / 2
        for gap in GAPS:
            for sl in SLIDES:
                g, s = MM(gap), MM(sl)
                yield 0, (cx + s, cy - hh - g), "N"      # above / below: upright text
                yield 0, (cx + s, cy + hh + g), "S"
                yield 90, (cx - hw - g, cy + s), "W"     # left / right: rotated text
                yield 90, (cx + hw + g, cy + s), "E"
                yield 0, (cx - hw - g, cy + s), "W"
                yield 0, (cx + hw + g, cy + s), "E"

    def place_at(ref, ang, pos, where, h):
        ref.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
        ref.SetTextSize(pcbnew.VECTOR2I(MM(h), MM(h)))
        ref.SetTextThickness(MM(max(0.12, 0.15 * h)))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        ref.SetTextPos(pcbnew.VECTOR2I(int(pos[0]), int(pos[1])))
        bb = ref.GetBoundingBox()        # push the text box clear of the side it sits on
        x, y = pos
        if where == "N":
            y -= bb.GetHeight() / 2
        elif where == "S":
            y += bb.GetHeight() / 2
        elif where == "W":
            x -= bb.GetWidth() / 2
        else:
            x += bb.GetWidth() / 2
        ref.SetTextPos(pcbnew.VECTOR2I(int(x), int(y)))

    def search(fp, ref, count_only=False):
        n = 0
        for strict in (True, False):
            for h in SIZES:
                for ang, pos, where in candidates(fp):
                    place_at(ref, ang, pos, where, h)
                    if legal(fp, ref, strict):
                        if not count_only:
                            return True
                        n += 1
                        if n >= 40:
                            return n
        return n if count_only else False

    todo = []
    hidden = []
    for fp in fps:
        ref = fp.Reference()
        if fp.GetReference().startswith("H"):        # mounting holes: no designator needed
            ref.SetVisible(False)
            continue
        if not ref.IsVisible() or fp.IsBoardOnly():
            continue
        todo.append(fp)

    # most constrained first: count legal spots with no other text placed yet
    saved = {fp.GetReference(): (fp.Reference().GetTextPos(), fp.Reference().GetTextAngle(),
                                 fp.Reference().GetTextSize(), fp.Reference().GetTextThickness()) for fp in todo}
    room = {fp.GetReference(): search(fp, fp.Reference(), count_only=True) for fp in todo}
    todo.sort(key=lambda fp: room[fp.GetReference()])
    small = []
    for fp in todo:
        ref = fp.Reference()
        if search(fp, ref):
            silk = side_of(fp)[0]
            obst[silk]["texts"].append((ref.GetEffectiveShape(silk), ref.GetBoundingBox(), fp))
            if ref.GetTextHeight() < MM(SIZES[0]) - 1:
                small.append(fp.GetReference())
        else:
            pos, ang, size, th = saved[fp.GetReference()]
            ref.SetTextPos(pos)
            ref.SetTextAngle(ang)
            ref.SetTextSize(size)
            ref.SetTextThickness(th)
            ref.SetVisible(False)
            hidden.append(fp.GetReference())
    b.Save(path)
    print(f"{len(todo) - len(hidden)} references placed ({len(small)} reduced: {' '.join(sorted(small))})")
    print(f"hidden (no legal spot; still on Fab): {' '.join(sorted(hidden)) or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1])
