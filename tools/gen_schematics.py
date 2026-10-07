#!/usr/bin/env python3
"""
Bootstrap generator for the dekatron controller/PSU KiCad project (Phase 1B).

Writes into hardware/dekatron/:
  dekatron.kicad_pro          project file (written once; KiCad owns it afterwards)
  dekatron.kicad_sch          root sheet
  power.kicad_sch             12 V input, 5 V buck, ideal diodes, 10 V gate drive, HV converter
  sym-lib-table / fp-lib-table
  lib/dekatron.kicad_sym      project symbols (TLV3011)

Connectivity style: every pin gets a short wire stub that ends in a net label, a power symbol or a
no-connect flag, so the netlist is exactly the `nets` dictionaries below. Nets shared with other
sheets use global labels. Stock symbols are copied from the KiCad installation; UUIDs are derived
deterministically, so re-running gives stable output.

The core (s-expression parser, symbol loading, Sheet primitives) follows nanovolt-divider's
tools/gen_schematics.py (same author, MIT).

Design values come from docs/hardware.md ("Power sheet (Phase 1B)").

Usage:  python tools/gen_schematics.py [--kicad-share "C:/Program Files/KiCad/10.0/share/kicad"]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware", "dekatron")
PROJECT = "dekatron"
NS = uuid.UUID("2b9f6c1e-3d4a-4f7b-9c2e-5a1d8e7f6b30")

SCH_VERSION = "20260306"
GEN_VERSION = "10.0"


def U(key: str) -> str:
    return str(uuid.uuid5(NS, key))


ROOT_UUID = U("sheet:root")
POWER_UUID = U("sheet:power")
TUBE_UUID = U("sheet:tube")
MCU_UUID = U("sheet:mcu")

# --------------------------------------------------------------------------------------
# Design parameters that are still open (see docs/hardware.md)
# --------------------------------------------------------------------------------------

# HV boost inductor: from the user's 6 x 8 mm radial kit (100 uH +/-10 %, rated 0.71 A, DCR 0.35 ohm).
# The current limit is lowered to fit (0.22 ohm -> 0.42-0.49 A) and the frequency raised to 150 kHz
# to keep the DCM power margin (docs/hardware.md, "Kit inductor").
# Buck inductor: kit 15 uH, rated 1.31 A (peak ~0.83 A at the 0.63 A load estimate + 0.40 A p-p ripple).
L_HV = dict(value="100uH", fp="Inductor_THT:L_Radial_D6.0mm_P4.00mm", mpn="(kit, 6 x 8 mm radial)", mfr="",
            note="Rated 0.71 A, DCR 0.35 ohm, 4 mm pitch")
L_BUCK = dict(value="15uH", fp="Inductor_THT:L_Radial_D6.0mm_P4.00mm", mpn="(kit, 6 x 8 mm radial)", mfr="",
              note="Rated 1.31 A; limits the 5 V rail to ~1.3 A")
R_SENSE = "0.22"      # HV boost current limit 0.42-0.49 A (kit inductor rated 0.71 A)
R_T = "147k"          # ~150 kHz

# --------------------------------------------------------------------------------------
# Minimal s-expression parser / serializer (from nanovolt-divider)
# --------------------------------------------------------------------------------------


def parse(text: str):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                j += 1
            tokens.append(text[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            tokens.append(text[i:j])
            i = j
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(t)
    assert len(stack) == 1 and len(stack[0]) == 1, "unbalanced s-expression"
    return stack[0][0]


def dump(node, depth=0) -> str:
    ind = "\t" * depth
    if isinstance(node, str):
        return ind + node
    if not node:
        return ind + "()"
    if all(isinstance(x, str) for x in node):
        return ind + "(" + " ".join(node) + ")"
    out = [ind + "(" + node[0]]
    inline = []
    rest = node[1:]
    k = 0
    while k < len(rest) and isinstance(rest[k], str):
        inline.append(rest[k])
        k += 1
    if inline:
        out[0] += " " + " ".join(inline)
    for child in rest[k:]:
        out.append(dump(child, depth + 1))
    out.append(ind + ")")
    return "\n".join(out)


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def unq(s: str) -> str:
    return s[1:-1] if s.startswith('"') else s


def find(node, head):
    for c in node[1:]:
        if isinstance(c, list) and c and c[0] == head:
            return c
    return None


def find_all(node, head):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def prop(node, name):
    for p in find_all(node, "property"):
        if unq(p[1]) == name:
            return p
    return None


class SymbolLib:
    def __init__(self, share_dir: str):
        self.share = os.path.join(share_dir, "symbols")
        self._cache: dict[str, str] = {}
        self.defs: dict[str, list] = {}

    def _libtext(self, lib):
        if lib not in self._cache:
            with open(os.path.join(self.share, lib + ".kicad_sym"), encoding="utf8") as f:
                self._cache[lib] = f.read()
        return self._cache[lib]

    def _raw(self, lib, name) -> list:
        s = self._libtext(lib)
        key = '\n\t(symbol "%s"' % name
        i = s.find(key)
        if i < 0:
            raise KeyError(f"{lib}:{name}")
        depth = 0
        j = i + 1
        while True:
            c = s[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == '"':
                j += 1
                while s[j] != '"':
                    if s[j] == "\\":
                        j += 1
                    j += 1
            j += 1
        return parse(s[i + 1:j + 1])

    def get(self, lib, name) -> list:
        full = f"{lib}:{name}"
        if full in self.defs:
            return self.defs[full]
        sym = self._raw(lib, name)
        ext = find(sym, "extends")
        if ext:
            parent = self._raw(lib, unq(ext[1]))
            flat = [x for x in parent if not (isinstance(x, list) and x and x[0] == "property")]
            props = find_all(sym, "property")
            parent_props = {unq(p[1]): p for p in find_all(parent, "property")}
            merged, seen = [], set()
            for p in props:
                merged.append(p)
                seen.add(unq(p[1]))
            for pn, p in parent_props.items():
                if pn not in seen:
                    merged.append(p)
            head = [flat[0], flat[1]]
            body = flat[2:]
            pre = [x for x in body if not (isinstance(x, list) and x and x[0] == "symbol")]
            subs = [x for x in body if isinstance(x, list) and x and x[0] == "symbol"]
            pname, cname = unq(ext[1]), name
            for sub in subs:
                sub[1] = q(unq(sub[1]).replace(pname + "_", cname + "_", 1))
            sym = head + pre + merged + subs
        sym[1] = q(full)
        self.defs[full] = sym
        return sym

    def pins(self, full) -> list[dict]:
        sym = self.defs[full]
        out = []
        for sub in find_all(sym, "symbol"):
            m = re.match(r".*_(\d+)_(\d+)$", unq(sub[1]))
            unit = int(m.group(1))
            for p in find_all(sub, "pin"):
                at = find(p, "at")
                out.append(dict(
                    unit=unit, type=p[1], x=float(at[1]), y=float(at[2]), angle=float(at[3]),
                    length=float(find(p, "length")[1]), name=unq(find(p, "name")[1]),
                    number=unq(find(p, "number")[1])))
        return out


# --------------------------------------------------------------------------------------
# Project symbols
# --------------------------------------------------------------------------------------

FONT = "(effects (font (size 1.27 1.27)))"


def _pin(ptype, x, y, angle, name, number, length=2.54):
    return (f'(pin {ptype} line (at {x} {y} {angle}) (length {length}) '
            f'(name {q(name)} {FONT}) (number {q(number)} {FONT}))')


def _sprop(name, value, x, y, hide=False):
    h = " (hide yes)" if hide else ""
    return f'(property {q(name)} {q(value)} (at {x} {y} 0){h} (effects (font (size 1.27 1.27))))'


def tlv3011_symbol_text() -> str:
    """TI TLV3011 (DBV, SOT-23-6): comparator with 1.242 V reference, open-drain output.
    Pinout from datasheet SBOS300C, Pin Functions: 1 OUT, 2 V-, 3 IN+, 4 IN-, 5 REF, 6 V+."""
    pins = [
        _pin("open_collector", 10.16, 0, 180, "OUT", "1"),
        _pin("power_in", 0, -7.62, 90, "V-", "2"),
        _pin("input", -10.16, 2.54, 0, "IN+", "3"),
        _pin("input", -10.16, -2.54, 0, "IN-", "4"),
        _pin("output", -10.16, -5.08, 0, "REF", "5"),
        _pin("power_in", 0, 7.62, 270, "V+", "6"),
    ]
    return f'''(symbol "TLV3011" (exclude_from_sim no) (in_bom yes) (on_board yes)
	{_sprop("Reference", "U", 3.81, 6.35)}
	{_sprop("Value", "TLV3011", 3.81, -6.35)}
	{_sprop("Footprint", "Package_TO_SOT_SMD:SOT-23-6", 0, 0, True)}
	{_sprop("Datasheet", "https://www.ti.com/lit/gpn/tlv3011", 0, 0, True)}
	{_sprop("Description", "Nanopower comparator with 1.242 V reference, open-drain output, SOT-23-6", 0, 0, True)}
	(symbol "TLV3011_0_1"
		(polyline (pts (xy -7.62 5.08) (xy -7.62 -7.62) (xy 7.62 -1.27) (xy 7.62 1.27) (xy -7.62 5.08))
			(stroke (width 0.254) (type default)) (fill (type background)))
	)
	(symbol "TLV3011_1_1"
		{" ".join(pins)}
	)
	(embedded_fonts no)
)'''


# RP2040-Zero (Waveshare), soldered by its castellated edge pads.
# Pin order follows Waveshare's top-view pinout (wiki "RP2040-Zero-details-7"): USB at the top;
# left column top to bottom 5V, GND, 3V3, GP29, GP28, GP27, GP26, GP15, GP14; bottom row left to
# right GP13..GP9; right column top to bottom GP0..GP8. Geometry from Waveshare's STEP model
# (RP2040_Zero_stp.zip): 2.54 mm pitch, side columns 15.24 mm apart, bottom row level with the
# lowest side pads; board 18 x 23.5 mm. Symbol/pad numbering runs counter-clockwise from 5V.
ZERO_LEFT = ["5V", "GND", "3V3", "GP29", "GP28", "GP27", "GP26", "GP15", "GP14"]
ZERO_BOTTOM = ["GP13", "GP12", "GP11", "GP10", "GP9"]
ZERO_RIGHT_UP = ["GP8", "GP7", "GP6", "GP5", "GP4", "GP3", "GP2", "GP1", "GP0"]
ZERO_PINS = ZERO_LEFT + ZERO_BOTTOM + ZERO_RIGHT_UP          # pad numbers 1..23


def rp2040_zero_symbol_text() -> str:
    pins = []
    for i, name in enumerate(ZERO_PINS, start=1):
        if name == "5V":
            t = "power_in"
        elif name == "3V3":
            t = "power_out"
        elif name == "GND":
            t = "power_in"
        else:
            t = "bidirectional"
        # 5.08 mm pin pitch: global labels on adjacent pins would overlap at 2.54 mm
        if i <= 9:                       # left side, top to bottom
            x, y, a = -15.24, 20.32 - (i - 1) * 5.08, 0
        elif i <= 14:                    # bottom, left to right
            x, y, a = -10.16 + (i - 10) * 5.08, -30.48, 90    # below the side pins' names
        else:                            # right side, bottom to top
            x, y, a = 15.24, -20.32 + (i - 15) * 5.08, 180
        pins.append(_pin(t, x, y, a, name, str(i)))
    return f'''(symbol "RP2040-Zero" (exclude_from_sim no) (in_bom yes) (on_board yes)
	{_sprop("Reference", "U", -12.7, 24.13)}
	{_sprop("Value", "RP2040-Zero", 2.54, 24.13)}
	{_sprop("Footprint", "dekatron:RP2040-Zero_Castellated", 0, 0, True)}
	{_sprop("Datasheet", "https://www.waveshare.com/wiki/RP2040-Zero", 0, 0, True)}
	{_sprop("Description", "Waveshare RP2040-Zero module, soldered by its 23 castellated edge pads", 0, 0, True)}
	(symbol "RP2040-Zero_0_1"
		(rectangle (start -12.7 22.86) (end 12.7 -27.94) (stroke (width 0.254) (type default)) (fill (type background)))
	)
	(symbol "RP2040-Zero_1_1"
		{" ".join(pins)}
	)
	(embedded_fonts no)
)'''


def rp2040_zero_footprint_text() -> str:
    """Carrier footprint: one SMD pad under each castellation, extended ~1.4 mm past the module edge
    so an iron reaches the joint. Origin at the centre of the pad pattern; USB toward -y."""
    pads = []
    for i, name in enumerate(ZERO_PINS, start=1):
        if i <= 9:
            cx, cy, w, h = -8.82, -10.16 + (i - 1) * 2.54, 3.2, 1.5
        elif i <= 14:
            cx, cy, w, h = -5.08 + (i - 10) * 2.54, 11.36, 1.5, 3.2
        else:
            cx, cy, w, h = 8.82, 10.16 - (i - 15) * 2.54, 3.2, 1.5
        pads.append(f'\t(pad "{i}" smd roundrect (at {cx} {round(cy, 3)}) (size {w} {h}) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.15))')
    fab = [(-9.0, -11.96, 9.0, -11.96), (9.0, -11.96, 9.0, 11.54), (9.0, 11.54, -9.0, 11.54), (-9.0, 11.54, -9.0, -11.96)]
    lines = "\n".join(f'\t(fp_line (start {a} {b}) (end {c} {d}) (stroke (width 0.1) (type default)) (layer "F.Fab"))' for a, b, c, d in fab)
    crt = [(-10.7, -12.5, 10.7, -12.5), (10.7, -12.5, 10.7, 13.2), (10.7, 13.2, -10.7, 13.2), (-10.7, 13.2, -10.7, -12.5)]
    clines = "\n".join(f'\t(fp_line (start {a} {b}) (end {c} {d}) (stroke (width 0.05) (type default)) (layer "F.CrtYd"))' for a, b, c, d in crt)
    silk = [(-6.8, -12.2, 6.8, -12.2)]
    slines = "\n".join(f'\t(fp_line (start {a} {b}) (end {c} {d}) (stroke (width 0.12) (type default)) (layer "F.SilkS"))' for a, b, c, d in silk)
    return f'''(footprint "RP2040-Zero_Castellated" (version 20260206) (generator "dekatron-gen") (layer "F.Cu")
	(descr "Waveshare RP2040-Zero soldered by its castellated edge pads; pads extend ~1.4 mm past the module edge for hand soldering. Geometry from Waveshare STEP model; verify with a 1:1 print against the module before ordering.")
	(tags "RP2040 Zero castellated module")
	(property "Reference" "REF**" (at 0 -14 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
	(property "Value" "RP2040-Zero" (at 0 14.5 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(fp_text user "USB" (at 0 -10.5 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(fp_text user "no exposed copper under the module (bottom pads GP17-GP25)" (at 0 0 90) (layer "Cmts.User") (effects (font (size 0.6 0.6) (thickness 0.1))))
{lines}
{clines}
{slines}
{chr(10).join(pads)}
	(embedded_fonts no)
)
'''


def project_symbol_lib_text() -> str:
    return ('(kicad_symbol_lib (version 20251024) (generator "dekatron-gen") (generator_version "10.0")\n'
            + tlv3011_symbol_text() + "\n" + rp2040_zero_symbol_text() + "\n)\n")


# --------------------------------------------------------------------------------------
# Schematic builder
# --------------------------------------------------------------------------------------


def xf(px, py, x, y, angle, mirror=None):
    """Library-space point (y up) to schematic space (y down) for a placed symbol."""
    dx, dy = px, -py
    if mirror == "y":
        dx = -dx
    if mirror == "x":
        dy = -dy
    a = int(angle) % 360
    if a == 90:
        dx, dy = dy, -dx
    elif a == 180:
        dx, dy = -dx, -dy
    elif a == 270:
        dx, dy = -dy, dx
    return round(x + dx, 4), round(y + dy, 4)


def fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


GRID = 2.54


def snap(v):
    """Snap a placement coordinate to the 2.54 mm connection grid."""
    return round(round(v / GRID) * GRID, 4)
POWER_NETS = {"GND": "GND", "+5V": "+5V", "+3V3": "+3V3"}


@dataclass
class Sheet:
    name: str
    file: str
    uuid: str
    paper: str
    lib: SymbolLib
    path: str
    global_nets: set = field(default_factory=set)
    items: list = field(default_factory=list)
    used: dict = field(default_factory=dict)
    placed: list = field(default_factory=list)
    title: str = ""
    _n: int = 0
    _pwr: int = 0
    _pts: list = field(default_factory=list)

    def key(self, k):
        self._n += 1
        return U(f"{self.file}:{k}:{self._n}")

    def wire(self, x1, y1, x2, y2):
        self.items.append(f'(wire (pts (xy {fmt(x1)} {fmt(y1)}) (xy {fmt(x2)} {fmt(y2)})) (stroke (width 0) (type default)) (uuid "{self.key("wire")}"))')

    def noconn(self, x, y):
        self.items.append(f'(no_connect (at {fmt(x)} {fmt(y)}) (uuid "{self.key("nc")}"))')

    def label(self, name, x, y, angle=0):
        j = "left bottom" if angle in (0, 90) else "right bottom"
        self.items.append(f'(label {q(name)} (at {fmt(x)} {fmt(y)} {angle}) (effects (font (size 1.27 1.27)) (justify {j})) (uuid "{self.key("lbl")}"))')

    def glabel(self, name, x, y, angle=0, shape="passive"):
        j = "left" if angle in (0, 90) else "right"
        self.items.append(
            f'(global_label {q(name)} (shape {shape}) (at {fmt(x)} {fmt(y)} {angle}) (fields_autoplaced yes) '
            f'(effects (font (size 1.27 1.27)) (justify {j})) (uuid "{self.key("gl")}") '
            f'(property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {fmt(x)} {fmt(y)} 0) (effects (font (size 1.27 1.27)) (hide yes))))')

    def text(self, s, x, y, size=1.27):
        self.items.append(f'(text {q(s)} (exclude_from_sim no) (at {fmt(x)} {fmt(y)} 0) (effects (font (size {size} {size})) (justify left bottom)) (uuid "{self.key("txt")}"))')

    def symbol(self, lib_id, x, y, ref, value, angle=0, mirror=None, unit=1, footprint=None,
               fields=None, dnp=False, hide_ref=False, horizontal=False, multipin=False, textpos=None):
        # no snapping here: power symbols sit on stub tips, which follow the 1.27 mm pin offsets
        lib, name = lib_id.split(":", 1)
        sym = self.lib.get(lib, name)
        self.used[lib_id] = sym

        def libprop(n):
            p = prop(sym, n)
            return unq(p[2]) if p else ""

        fp = footprint if footprint is not None else libprop("Footprint")
        ds = libprop("Datasheet")
        desc = libprop("Description")
        m = f" (mirror {mirror})" if mirror else ""
        sym_uuid = self.key("sym:" + ref)
        if not ref.startswith("#"):
            self.placed.append(dict(ref=ref, lib_id=lib_id, value=value, footprint=fp, dnp=dnp,
                                    fields=dict(fields or {})))
        d = "yes" if dnp else "no"
        lines = [f'(symbol (lib_id {q(lib_id)}) (at {fmt(x)} {fmt(y)} {angle}){m} (unit {unit}) (body_style 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes) (dnp {d}) (uuid "{sym_uuid}")']
        # reference / value text: beside the body, or above / below it for horizontal two-pin parts
        if textpos:
            rx, ry, vx, vy, just = x + textpos[0], y + textpos[1], x + textpos[0], y + textpos[1] + 1.6, "left"
        elif horizontal:
            rx, ry, vx, vy, just = x, y - 3.0, x, y + 4.0, "center"
        elif multipin and int(angle) % 180 == 90:
            # rotated transistor: pins point left, right and down, so the free side is above
            rx, ry, vx, vy, just = x, y - 7.0, x, y - 5.4, "center"
        else:
            # KiCad also rotates the justification with the symbol: compensate per angle
            just = "right" if int(angle) % 360 == 90 else "left"
            rx, ry, vx, vy = x + 3.2, y - 1.0, x + 3.2, y + 1.6

        def P(n, v, px, py, hide=False):
            h = " (hide yes)" if hide else ""
            jj = just if n in ("Reference", "Value") else "left"
            js = "" if jj == "center" else f" (justify {jj})"     # centred is KiCad's default: no token
            # KiCad rotates field text with the symbol: counter-rotate so text always reads horizontally
            fa = int(angle) % 180
            lines.append(f'  (property {q(n)} {q(v)} (at {fmt(px)} {fmt(py)} {fa}){h} (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)){js}))')

        P("Reference", ref, rx, ry, hide=hide_ref or ref.startswith("#"))
        P("Value", value, vx, vy, hide=ref.startswith("#PWR"))
        P("Footprint", fp, x, y, hide=True)
        P("Datasheet", ds, x, y, hide=True)
        P("Description", desc, x, y, hide=True)
        for k, v in (fields or {}).items():
            P(k, v, x, y, hide=True)
        for p in self.lib.pins(lib_id):
            if p["unit"] in (0, unit):
                lines.append(f'  (pin {q(p["number"])} (uuid "{self.key("pin")}"))')
        lines.append(f'  (instances (project {q(PROJECT)} (path {q(self.path)} (reference {q(ref)}) (unit {unit}))))')
        lines.append(")")
        self.items.append("\n".join(lines))

    def power(self, kind, x, y, angle=0):
        self._pwr += 1
        ref = f"#PWR{self.name.upper()}{self._pwr:03d}"
        self.symbol(f"power:{kind}", x, y, ref, kind, angle=angle)

    def flag(self, net, x, y):
        """PWR_FLAG on a net that is driven from off-sheet or through passive parts (ERC)."""
        x, y = snap(x), snap(y)
        self._pwr += 1
        self.symbol("power:PWR_FLAG", x, y, f"#FLG{self.name.upper()}{self._pwr:03d}", "PWR_FLAG")
        self.wire(x, y, x, y + GRID)
        self.terminate(net, x, y + GRID, 0, GRID)

    def part(self, lib_id, ref, value, x, y, nets, angle=0, mirror=None, footprint=None,
             fields=None, dnp=False, stub=GRID, textpos=None):
        """Place a symbol; terminate every pin with a stub + net label / power symbol / no-connect.

        nets maps pin number (or unique pin name) to a net name. "NC" places a no-connect flag.
        Every pin must be mapped, except pins of type no_connect."""
        lib, name = lib_id.split(":", 1)
        self.lib.get(lib, name)
        x, y = snap(x), snap(y)
        pins = [p for p in self.lib.pins(lib_id) if p["unit"] in (0, 1)]
        ends = [xf(p["x"], p["y"], x, y, angle, mirror) for p in pins]
        horizontal = len(pins) == 2 and abs(ends[0][1] - ends[1][1]) < 0.01
        self.symbol(lib_id, x, y, ref, value, angle=angle, mirror=mirror, footprint=footprint,
                    fields=fields, dnp=dnp, horizontal=horizontal, multipin=len(pins) == 3, textpos=textpos)
        seen = set()
        for p in pins:
            if (p["x"], p["y"]) in seen:          # stacked pins (e.g. exposed pad) share one stub
                continue
            net = nets.get(p["number"], nets.get(p["name"]))
            if net is None:
                if p["type"] == "no_connect":
                    continue
                raise KeyError(f"{ref} ({lib_id}): pin {p['number']} '{p['name']}' has no net")
            seen.add((p["x"], p["y"]))
            ex, ey = xf(p["x"], p["y"], x, y, angle, mirror)
            if net == "NC":
                self.noconn(ex, ey)
                continue
            a = math.radians(p["angle"])
            ox, oy = -math.cos(a), -math.sin(a)          # outward, library space
            tx, ty = xf(p["x"] + stub * ox, p["y"] + stub * oy, x, y, angle, mirror)
            self.wire(ex, ey, tx, ty)
            ddx, ddy = round(tx - ex, 3), round(ty - ey, 3)
            self.terminate(net, tx, ty, ddx, ddy)

    def terminate(self, net, x, y, dx, dy):
        """End a stub pointing along (dx, dy) in schematic space with the net's marker."""
        if dx > 0:
            lang, pang = 0, 90
        elif dx < 0:
            lang, pang = 180, 270
        elif dy < 0:
            lang, pang = 90, 180
        else:
            lang, pang = 270, 0
        if net in POWER_NETS:
            kind = POWER_NETS[net]
            if kind == "GND":
                self.power("GND", x, y, angle=pang)
            else:                                       # supply symbols point away from the stub
                self.power(kind, x, y, angle=(pang + 180) % 360)
        elif net in self.global_nets:
            self.glabel(net, x, y, angle=lang)
        else:
            self.label(net, x, y, angle=lang)

    def sheet(self, name, file, sheet_uuid, x, y, w, h, page="2"):
        lines = [f'(sheet (at {fmt(x)} {fmt(y)}) (size {fmt(w)} {fmt(h)}) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
                 '  (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000))',
                 f'  (uuid "{sheet_uuid}")',
                 f'  (property "Sheetname" {q(name)} (at {fmt(x)} {fmt(y - 0.7116)} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)) (justify left bottom)))',
                 f'  (property "Sheetfile" {q(file)} (at {fmt(x)} {fmt(y + h + 0.5846)} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)) (justify left top)))',
                 f'  (instances (project {q(PROJECT)} (path {q("/" + ROOT_UUID)} (page {q(page)}))))',
                 ")"]
        self.items.append("\n".join(lines))

    # ---- drawing API: real wires (readable schematics) ------------------------------------
    # place() returns pin coordinates; w() draws wires between explicit points; finish() adds a
    # junction wherever three or more wire ends / pins meet. Wires must only meet at their ends.
    def place(self, lib_id, ref, value, x, y, angle=0, mirror=None, footprint=None, fields=None,
              dnp=False, textpos=None):
        lib, name = lib_id.split(":", 1)
        self.lib.get(lib, name)
        pins = [p for p in self.lib.pins(lib_id) if p["unit"] in (0, 1)]
        ends = [xf(p["x"], p["y"], x, y, angle, mirror) for p in pins]
        horizontal = len(pins) == 2 and abs(ends[0][1] - ends[1][1]) < 0.01
        self.symbol(lib_id, x, y, ref, value, angle=angle, mirror=mirror, footprint=footprint, fields=fields,
                    dnp=dnp, horizontal=horizontal, multipin=len(pins) == 3, textpos=textpos)
        pm = {}
        for p, e in zip(pins, ends):
            pm[p["number"]] = e
            if p["name"]:
                pm[p["name"]] = e
            self._pts.append(e)
        return pm

    def w(self, *pts):
        pts = [(round(a, 4), round(b, 4)) for a, b in pts]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            assert a[0] == b[0] or a[1] == b[1], f"wire not orthogonal: {a} -> {b}"
            self.wire(a[0], a[1], b[0], b[1])
            self._pts += [a, b]

    def gnd(self, pt):
        self.power("GND", pt[0], pt[1], angle=0)
        self._pts.append((round(pt[0], 4), round(pt[1], 4)))

    def pwr(self, kind, pt):
        """Supply symbol (arrow up) or GND (down) at a wire end."""
        self.power(kind, pt[0], pt[1], angle=0)
        self._pts.append((round(pt[0], 4), round(pt[1], 4)))

    def stub(self, pt, net, dx, dy):
        """Short wire from a pin, ended by the net's marker (label, global label or power symbol)."""
        end = (pt[0] + dx, pt[1] + dy)
        self.w(pt, end)
        self.terminate(net, end[0], end[1], dx, dy)

    def pflag(self, pt, textpos=None):
        """PWR_FLAG sitting on a wire point (body above)."""
        self._pwr += 1
        self.symbol("power:PWR_FLAG", pt[0], pt[1], f"#FLG{self.name.upper()}{self._pwr:03d}", "PWR_FLAG",
                    textpos=textpos)
        self._pts.append((round(pt[0], 4), round(pt[1], 4)))

    def nl(self, name, pt, angle=0):
        """Local net label anchored on an existing wire end / node."""
        self.label(name, pt[0], pt[1], angle)

    def gl(self, name, pt, angle=0, shape="passive"):
        self.glabel(name, pt[0], pt[1], angle=angle, shape=shape)

    def finish(self):
        from collections import Counter
        c = Counter(self._pts)
        for (x, y), n in sorted(c.items()):
            if n >= 3:
                self.junction(x, y)

    def junction(self, x, y):
        self.items.append(f'(junction (at {fmt(x)} {fmt(y)}) (diameter 0) (color 0 0 0 0) (uuid "{self.key("junc")}"))')

    def render(self, is_root=False) -> str:
        libs = "\n".join(dump(s, 2) for _, s in sorted(self.used.items()))
        tb = ""
        if self.title:
            tb = (f'\n\t(title_block (title {q(self.title)}) (rev "Rev A draft") (company "universal-nixie-display (open hardware)") '
                  f'(comment 1 "Generated by tools/gen_schematics.py; values per docs/hardware.md"))')
        body = "\n".join("\t" + it.replace("\n", "\n\t") for it in self.items)
        si = '\n\t(sheet_instances (path "/" (page "1")))' if is_root else ""
        return (f'(kicad_sch (version {SCH_VERSION}) (generator "dekatron-gen") (generator_version "{GEN_VERSION}")\n'
                f'\t(uuid "{self.uuid}")\n\t(paper {q(self.paper)}){tb}\n\t(lib_symbols\n{libs}\n\t)\n{body}{si}\n\t(embedded_fonts no)\n)\n')


# --------------------------------------------------------------------------------------
# Footprints and part data
# --------------------------------------------------------------------------------------

FP_R = "Resistor_SMD:R_1206_3216Metric"
FP_C = "Capacitor_SMD:C_1206_3216Metric"
FP_C1210 = "Capacitor_SMD:C_1210_3225Metric"
FP_FILM = "Capacitor_THT:C_Rect_L18.0mm_W7.0mm_P15.00mm_FKS3_FKP3"   # confirm against the chosen 0.47 uF 400 V part
FP_ELEC = "Capacitor_SMD:CP_Elec_8x10.5"
FP_DPAK = "Package_TO_SOT_SMD:TO-252-2"     # pad 1 G, pad 2 (tab) D, pad 3 S
FP_SMA = "Diode_SMD:D_SMA"
FP_SMB = "Diode_SMD:D_SMB"
FP_SOD123 = "Diode_SMD:D_SOD-123"
FP_F1206 = "Fuse:Fuse_1206_3216Metric"
FP_F1812 = "Fuse:Fuse_1812_4532Metric"
FP_TP = "TestPoint:TestPoint_THTPad_D1.5mm_Drill0.7mm"
FP_HVLINK = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"   # wire link, 7.62 mm pitch
FP_WIRE2 = "Connector_Wire:SolderWire-0.5sqmm_1x02_P4.8mm_D0.9mm_OD2.3mm"   # strain relief: cable-tie anchor on the PCB (D14)
FP_HDR2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"


def F(function, mpn="", mfr="", rating=""):
    d = {"Function": function}
    if mpn:
        d["MPN"] = mpn
    if mfr:
        d["Manufacturer"] = mfr
    if rating:
        d["Rating"] = rating
    return d


# --------------------------------------------------------------------------------------
# power.kicad_sch
# --------------------------------------------------------------------------------------

POWER_GLOBALS = {"VIN_PROT", "+12V_NIX", "5V_DISP", "5V_MCU", "5V_NIX", "HV_EN", "PGOOD", "OVP_TRIP",
                 "HV_SENSE", "HV", "V_B_BIAS"}


def build_power(lib: SymbolLib) -> Sheet:
    sh = Sheet("power", "power.kicad_sch", U("file:power"), "A2", lib, f"/{ROOT_UUID}/{POWER_UUID}",
               global_nets=POWER_GLOBALS, title="Power: 12 V input, 5 V, gate drive, HV converter")
    R, C, CP, L = "Device:R", "Device:C", "Device:C_Polarized", "Device:L"
    D, DZ = "Device:D", "Device:D_Zener"
    TP = "Connector:TestPoint"

    def note(head, detail, x, y):
        sh.text(head, x, y, 2.0)
        sh.text(detail, x, y + 4.32, 1.27)

    # two-pin parts placed by their first pin: v* = vertical (pin 1 on top), h* = horizontal (pin 1 left)
    def v2(lib_id, ref, val, x, y1, fields, fp, dnp=False):
        return sh.place(lib_id, ref, val, x, y1 + 3.81, footprint=fp, fields=fields, dnp=dnp)

    ABOVE = (1.27, -5.6)          # ref / value text above a rail for test points and flags

    def h2(lib_id, ref, val, x1, y, fields, fp):
        return sh.place(lib_id, ref, val, x1 + 3.81, y, angle=90, footprint=fp, fields=fields)

    def vR(ref, val, x, y1, fn, rating="", dnp=False):
        return v2(R, ref, val, x, y1, F(fn, rating=rating), FP_R, dnp)

    def hR(ref, val, x1, y, fn, rating=""):
        return h2(R, ref, val, x1, y, F(fn, rating=rating), FP_R)

    def vC(ref, val, x, y1, fn, rating="", fp=FP_C):
        return v2(C, ref, val, x, y1, F(fn, rating=rating), fp)

    def link(ref, x1, y, fn, hv=False):
        return h2(R, ref, "LINK" if hv else "0", x1, y,
                  F(fn + (" (wire link, desolder to open)" if hv else " (0 ohm, remove to open)")),
                  FP_HVLINK if hv else FP_R)

    def down_gnd(pt, dy=2.54):
        sh.w(pt, (pt[0], pt[1] + dy))
        sh.gnd((pt[0], pt[1] + dy))

    def tp(ref, net, pt, textpos=ABOVE):
        sh.place(TP, ref, net, pt[0], pt[1], footprint=FP_TP, fields=F(f"Test point {net}"), textpos=textpos)


    # ==== 12 V INPUT (D4) ===========================================================================
    note("12 V INPUT (D4)", "Fuse, reverse-polarity P-MOSFET (gate clamped by D101), TVS, bulk; fused branch to the Nixie module",
         15.24, 25.4)
    Y = 50.8
    j1 = sh.place("Connector_Generic:Conn_01x02", "J101", "PWR_IN", 17.78, Y, mirror="y", footprint=FP_WIRE2,
                  fields=F("Harness landing PWR_IN: +12V_IN from panel switch / barrel jack; GND"), textpos=(-5.08, -5.6))
    sh.w(j1["2"], (25.4, Y + 2.54), (25.4, Y + 7.62))
    sh.gnd((25.4, Y + 7.62))
    f1 = h2("Device:Fuse", "F101", "2A Slo-Blo", 40.64, Y,
            F("Input fuse", "0468002.NRHF", "Littelfuse", "2 A, 63 V, I2t 0.506 A2s"), FP_F1206)
    sh.w(j1["1"], (27.94, Y), f1["1"])
    sh.nl("+12V_RAW", (27.94, Y))
    q1 = sh.place("Transistor_FET:Q_PMOS_GDS", "Q101", "AOD4185", 73.66, Y + 2.54, angle=90, footprint=FP_DPAK,
                  fields=F("Reverse-polarity protection", "AOD4185", "Alpha & Omega", "-40 V, 115 A pulsed"))
    sh.w(f1["2"], (53.34, Y), q1["D"])
    sh.nl("+12V_FUSED", (53.34, Y))
    # VIN_PROT rail: Q101 source -> clamps and bulk -> buck input
    XD1, XD2, XC1, XC2, XTP, XF2, XFL, XGL = 88.9, 104.14, 119.38, 134.62, 147.32, 157.48, 165.1, 180.34
    XB = 35.56                                      # buck block offset against the first layout
    rail = [q1["S"][0], XD1, XD2, XC1, XC2, XTP, XF2, XFL, XGL, 198.12, 213.36, 223.52, 241.3]
    sh.w(*[(x, Y) for x in rail])
    sh.pflag((XFL, Y), textpos=ABOVE)
    sh.w((XGL, Y), (XGL, Y - 5.08))
    sh.gl("VIN_PROT", (XGL, Y - 5.08), 90)
    dz = sh.place(DZ, "D101", "BZT52C10", XD1, Y + 7.62, angle=270, footprint=FP_SOD123,
                  fields=F("Q101 gate-source clamp, -10 V", "BZT52C10"))
    sh.w((XD1, Y), dz["K"])
    GQ = (q1["G"][0], Y + 12.7)
    sh.w(dz["A"], (XD1, GQ[1]), (78.74, GQ[1]), GQ)
    sh.nl("Q101_G", (78.74, GQ[1]))
    sh.w(q1["G"], GQ)
    r = vR("R101", "10k", GQ[0], GQ[1], "Reverse-polarity MOSFET gate pull-down")
    down_gnd(r["2"])
    tv = sh.place(DZ, "D102", "SMBJ15A", XD2, Y + 7.62, angle=270, footprint=FP_SMB,
                  fields=F("Input TVS, unidirectional", "SMBJ15A", "Littelfuse", "15 V standoff, 24.4 V clamp"))
    sh.w((XD2, Y), tv["K"])
    down_gnd(tv["A"])
    c = v2(CP, "C101", "100uF 35V", XC1, Y + 3.81, F("Input bulk, damps hot-plug ringing", "EEE-FK1V101P", "Panasonic",
                                                    "35 V, 160 mohm ESR"), FP_ELEC)
    sh.w((XC1, Y), c["1"])
    down_gnd(c["2"])
    c = vC("C102", "0.1uF", XC2, Y + 3.81, "Input HF bypass", "50 V X7R")
    sh.w((XC2, Y), c["1"])
    down_gnd(c["2"])
    tp("TP101", "VIN_PROT", (XTP, Y))
    pf = v2("Device:Polyfuse", "F102", "0.75A", XF2, Y + 6.35,
            F("Nixie HV module branch fuse", "1812L075/33DR", "Littelfuse", "0.75 A hold, 33 V"), FP_F1812)
    sh.w((XF2, Y), pf["1"])
    N12 = (XF2, Y + 20.32)
    sh.w(pf["2"], N12)
    j2 = sh.place("Connector_Generic:Conn_01x02", "J102", "NIX_12V", XF2 + 10.16, N12[1], footprint=FP_WIRE2,
                  fields=F("Harness landing NIX_12V to the purchased Nixie HV module"))
    sh.w(N12, j2["1"])
    sh.w(j2["2"], (XF2 + 2.54, N12[1] + 2.54), (XF2 + 2.54, N12[1] + 7.62))
    sh.gnd((XF2 + 2.54, N12[1] + 7.62))
    sh.w(N12, (XF2 - 10.16, N12[1]))
    sh.gl("+12V_NIX", (XF2 - 10.16, N12[1]), 180)
    tp("TP102", "GND", (XF2 + 25.4, N12[1] + 5.08), textpos=(1.27, -4.0))
    down_gnd((XF2 + 25.4, N12[1] + 5.08))
    sh.flag("GND", XF2 + 35.56, N12[1] + 2.54)

    # ==== 5 V BUCK ==================================================================================
    note("5 V BUCK", "TPS54202, TI reference design (SLVSD26C Fig. 7-1); 100k / 13.7k -> 4.95 V; UVLO 511k / 105k",
         195.58, 25.4)
    for ref, val, x, fn, rating, fp in (("C103", "10uF 35V", 198.12, "Buck input", "35 V X7R", FP_C1210),
                                        ("C104", "0.1uF", 213.36, "Buck input HF", "50 V X7R", FP_C)):
        c = vC(ref, val, x, Y, fn, rating, fp)
        down_gnd(c["2"])
    u = sh.place("Regulator_Switching:TPS54202DDC", "U101", "TPS54202", 251.46, Y + 2.54, textpos=(-10.16, -9.0),
                 fields=F("5 V buck regulator", "TPS54202DDCR", "Texas Instruments", "4.5-28 V, 2 A"))
    ra = vR("R102", "511k", 223.52, Y, "Buck EN UVLO, upper")
    rb = vR("R103", "105k", 223.52, ra["2"][1], "Buck EN UVLO, lower")
    down_gnd(rb["2"])
    sh.w(u["EN"], (238.76, u["EN"][1]), (238.76, ra["2"][1]), ra["2"])
    sh.nl("BUCK_EN", (238.76, ra["2"][1]), 270)
    down_gnd(u["GND"])
    YBT = Y - 10.16
    cb = h2(C, "C105", "0.1uF", 276.86, YBT, F("Buck bootstrap", rating="25 V X7R"), FP_C)
    sh.w(u["BOOT"], (264.16, Y), (264.16, YBT), cb["1"])
    sh.nl("BUCK_BOOT", (264.16, YBT))
    SWB = (289.56, u["SW"][1])
    sh.w(cb["2"], (289.56, YBT), SWB)
    lb = h2(L, "L101", L_BUCK["value"], 294.64, SWB[1], F("Buck inductor", L_BUCK["mpn"], L_BUCK["mfr"], L_BUCK["note"]),
            L_BUCK["fp"])
    sh.w(u["SW"], (271.78, SWB[1]), SWB, lb["1"])
    sh.nl("BUCK_SW", (271.78, SWB[1]))
    Y5 = SWB[1]
    XR4 = 353.06
    sh.w(lb["2"], (307.34, Y5), (322.58, Y5), (337.82, Y5), (XR4, Y5), (368.3, Y5))
    sh.nl("5V_BUCK", (307.34, Y5))
    for ref, x in (("C106", 322.58), ("C107", 337.82)):
        c = vC(ref, "22uF 25V", x, Y5, "Buck output", "25 V X7R", FP_C1210)
        down_gnd(c["2"])
    r4 = vR("R104", "49.9", XR4, Y5, "Buck loop-injection resistor")
    FBT = (XR4, r4["2"][1] + 2.54)
    sh.w(r4["2"], FBT)
    r5 = vR("R105", "100k", XR4, FBT[1], "Buck feedback, upper")
    c8 = vC("C108", "75pF", XR4 + 12.7, FBT[1], "Buck feed-forward", "50 V C0G")
    sh.w(FBT, (XR4 + 5.08, FBT[1]), c8["1"])
    sh.nl("BUCK_FBT", (XR4 + 5.08, FBT[1]))
    FBN = (XR4, r5["2"][1] + 2.54)
    sh.w(r5["2"], FBN)
    sh.w(c8["2"], (XR4 + 12.7, FBN[1]), FBN)
    r6 = vR("R106", "13.7k", XR4, FBN[1], "Buck feedback, lower (4.95 V)", "1 %")
    down_gnd(r6["2"])
    sh.w(u["FB"], (266.7, u["FB"][1]), (266.7, FBN[1]), (325.12, FBN[1]), FBN)
    sh.nl("BUCK_FB", (325.12, FBN[1]))
    lk = link("LK2", 368.3, Y5, "D11 link L2: buck output to board 5 V")
    sh.w(lk["2"], (383.54, Y5), (396.24, Y5), (408.94, Y5))
    tp("TP103", "+5V", (383.54, Y5))
    sh.pflag((396.24, Y5), textpos=ABOVE)
    sh.pwr("+5V", (408.94, Y5))

    # ==== IDEAL DIODES (D6) =========================================================================
    note("IDEAL DIODES (D6)", "One LM66100 per external 5 V feed; CE grounded = always on", 15.24, 91.44)
    Y = 104.14
    sh.pwr("+5V", (20.32, Y))
    rail = [20.32]
    for i, (ref, out, cref) in enumerate((("U102", "5V_DISP", "C109"), ("U103", "5V_MCU", "C110"), ("U104", "5V_NIX", "C111"))):
        xx = 50.8 + i * 55.88
        u = sh.place("Power_Management:LM66100DCK", ref, "LM66100", xx, Y + 12.7, textpos=(-6.35, -8.0),
                     fields=F(f"Ideal diode, {out} feed", "LM66100DCKR", "Texas Instruments", "1.5 A, reverse blocking"))
        c = vC(cref, "0.1uF", xx - 25.4, Y, f"{ref} input bypass", "50 V X7R")
        down_gnd(c["2"])
        sh.w((xx - 12.7, Y), (xx - 12.7, u["VIN"][1]), u["VIN"])
        sh.w(u["~{CE}"], (xx - 10.16, u["~{CE}"][1]), (xx - 10.16, u["GND"][1] + 2.54))
        sh.gnd((xx - 10.16, u["GND"][1] + 2.54))
        down_gnd(u["GND"])
        sh.noconn(*u["ST"])
        sh.w(u["VOUT"], (xx + 15.24, u["VOUT"][1]))
        sh.gl(out, (xx + 15.24, u["VOUT"][1]), 0)
        rail += [xx - 25.4, xx - 12.7]
    sh.w(*[(x, Y) for x in rail])

    # ==== 10 V GATE DRIVE ===========================================================================
    note("10 V GATE DRIVE", "LP2951 feeds LM5156 BIAS = VCC (2.97-16 V mode); 143k / 20.0k -> 10.07 V", 198.12, 91.44)
    Y = 109.22
    sh.gl("VIN_PROT", (193.04, Y), 180)
    lk = link("LK1", 198.12, Y, "D11 link L1: 12 V to the HV section")
    sh.w((193.04, Y), lk["1"])
    u = sh.place("Regulator_Linear:LP2951-3.3_SOIC", "U105", "LP2951 (adj. 10 V)", 251.46, Y + 7.62, textpos=(-10.16, -14.0),
                 fields=F("Gate-drive LDO, adjustable, 10.07 V", "LP2951ACDR2G", "onsemi", "30 V in, 100 mA"))
    sh.w(lk["2"], (208.28, Y), (218.44, Y), (226.06, Y), u["IN"])
    sh.nl("12V_HV", (208.28, Y))
    sh.pflag((218.44, Y), textpos=ABOVE)
    c = vC("C112", "1uF 35V", 226.06, Y, "LDO input", "35 V X7R")
    down_gnd(c["2"])
    sh.w(u["SHUTDOWN"], (238.76, u["SHUTDOWN"][1]), (238.76, u["GND"][1] + 2.54))
    sh.gnd((238.76, u["GND"][1] + 2.54))
    down_gnd(u["GND"])
    for pin in ("SENSE", "~{ERROR}", "VTAP"):
        sh.noconn(*u[pin])
    sh.w(u["OUT"], (269.24, Y), (274.32, Y), (287.02, Y), (297.18, Y), (304.8, Y))
    sh.nl("VDRV", (304.8, Y))
    r7 = vR("R107", "143k", 274.32, Y, "LDO feedback, upper", "1 %")
    FB = (274.32, u["FEEDBACK"][1])
    sh.w(r7["2"], FB)
    r8 = vR("R108", "20.0k", 274.32, FB[1], "LDO feedback, lower", "1 %")
    down_gnd(r8["2"])
    sh.w(u["FEEDBACK"], (266.7, FB[1]), FB)
    sh.nl("LDO_FB", (266.7, FB[1]))
    c = vC("C113", "2.2uF", 287.02, Y, "LDO output", "25 V X7R")
    down_gnd(c["2"])
    tp("TP104", "VDRV", (297.18, Y), textpos=(1.27, -6.4))

    # ==== HV BOOST (D2) =============================================================================
    note("HV BOOST (D2, Phase 1B)", "LM5156H, ~150 kHz DCM, 10 V gate drive, feedback from HV (tripler sheet area), "
         "CS filter against the pump surge; kit 100 uH inductor", 15.24, 152.4)
    M = sh.place("Regulator_Switching:LM5156HPWP", "U106", "LM5156H", 165.1, 200.66, textpos=(-12.7, -17.0),
                 fields=F("HV boost controller", "LM5156HPWPR", "Texas Instruments", "HTSSOP-14 exposed pad"))
    # BIAS = VCC = VDRV, DITHOFF tied high (dither off)
    sh.w(M["BIAS"], (147.32, M["BIAS"][1]))
    sh.w(M["VCC"], (147.32, M["VCC"][1]), (147.32, M["BIAS"][1]), (147.32, 182.88))
    sh.w((147.32, 182.88), (127.0, 182.88), (116.84, 182.88), (109.22, 182.88))
    sh.nl("VDRV", (109.22, 182.88), 180)
    for ref, val, x, fn, rating in (("C114", "1uF", 116.84, "LM5156 BIAS/VCC bypass", "25 V X7R"),
                                    ("C115", "0.1uF", 127.0, "LM5156 BIAS/VCC HF", "50 V X7R")):
        c = vC(ref, val, x, 182.88, fn, rating)
        down_gnd(c["2"])
    sh.stub(M["DITHOFF"], "VDRV", -2.54, 0)
    # EN/UVLO node: HV_EN through R109, pull-down, inhibit jumper, read-back to GP8, OVP comparators (wired-OR)
    YE = M["EN/UVLO/SYNC"][1]
    rr = hR("R109", "10k", 91.44, YE, "HV_EN series resistor")
    sh.w(M["EN/UVLO/SYNC"], (129.54, YE), (121.92, YE), (114.3, YE), (106.68, YE), rr["2"])
    sh.nl("HV_EN_PIN", (129.54, YE))
    sh.w(rr["1"], (86.36, YE))
    sh.gl("HV_EN", (86.36, YE), 180)
    r = vR("R110", "100k", 121.92, YE + 3.81, "EN/UVLO pull-down: HV off by default (D7)")
    sh.w((121.92, YE), r["1"])
    down_gnd(r["2"])
    r = sh.place(R, "R112", "0", 114.3, YE + 7.62, footprint=FP_R,
                 fields=F("EN/UVLO node read back by the RP2040 (OVP_TRIP, GP8)"))
    sh.w((114.3, YE), r["1"])
    sh.w(r["2"], (114.3, YE + 17.78))
    sh.gl("OVP_TRIP", (114.3, YE + 17.78), 270)
    jp = sh.place("Connector_Generic:Conn_01x02", "JP101", "HV_INHIBIT", 101.6, YE + 27.94, mirror="y", footprint=FP_HDR2,
                  fields=F("HV inhibit jumper (D11): shunt fitted holds EN/UVLO low"), textpos=(-17.78, -1.0))
    sh.w((106.68, YE), jp["1"])
    sh.w(jp["2"], (109.22, jp["2"][1]), (109.22, jp["2"][1] + 5.08))
    sh.gnd((109.22, jp["2"][1] + 5.08))
    YR = M["RT"][1]
    r = vR("R111", R_T, 137.16, YR + 2.54, "Switching frequency (147k = ~150 kHz)")
    sh.w(M["RT"], (139.7, YR), (137.16, YR), r["1"])
    sh.nl("LM5156_RT", (139.7, YR))
    down_gnd(r["2"])
    down_gnd(M["AGND"])
    down_gnd(M["PGND"])
    # PGOOD open drain, pulled up to 3V3
    XR = M["GATE"][0]
    sh.w(M["PGOOD"], (182.88, M["PGOOD"][1]), (182.88, 185.42), (190.5, 185.42), (198.12, 185.42))
    sh.gl("PGOOD", (198.12, 185.42), 0)
    r = vR("R114", "10k", 190.5, 185.42 - 7.62, "PGOOD pull-up")
    sh.w(r["1"], (190.5, 175.26))
    sh.pwr("+3V3", (190.5, 175.26))
    sh.stub(M["CS"], "LM5156_CS", 5.08, 0)
    sh.stub(M["FB"], "LM5156_FB", 5.08, 0)
    # compensation and soft-start
    YC = M["COMP"][1]
    r13 = vR("R113", "10k", 200.66, YC, "Compensation R")
    c18 = vC("C118", "100pF", 213.36, YC, "Compensation HF", "50 V C0G")
    sh.w(M["COMP"], (180.34, YC), (200.66, YC), c18["1"])
    sh.nl("LM5156_COMP", (180.34, YC))
    c17 = vC("C117", "10nF", 200.66, r13["2"][1] + 5.08, "Compensation C", "25 V X7R")
    sh.w(r13["2"], (200.66, r13["2"][1] + 2.54), c17["1"])
    sh.nl("COMP_RC", (200.66, r13["2"][1] + 2.54))
    down_gnd(c17["2"])
    down_gnd(c18["2"])
    YS = M["SS"][1]
    c16 = vC("C116", "47nF", 190.5, YS + 2.54, "Soft-start", "25 V X7R")
    sh.w(M["SS"], (180.34, YS), (190.5, YS), c16["1"])
    sh.nl("LM5156_SS", (180.34, YS))
    down_gnd(c16["2"])
    # gate drive and switch
    q = sh.place("Transistor_FET:Q_NMOS_GDS", "Q102", "AOD5N40", 231.14, M["GATE"][1], footprint=FP_DPAK,
                 fields=F("HV boost switch", "AOD5N40", "Alpha & Omega", "400 V, 1.6 ohm at 10 V"))
    rg = hR("R115", "2.2", 198.12, M["GATE"][1], "Gate resistor")
    sh.w(M["GATE"], (185.42, M["GATE"][1]), rg["1"])
    sh.nl("LM5156_GATE", (185.42, M["GATE"][1]))
    r16 = vR("R116", "100k", 218.44, M["GATE"][1], "Gate pull-down (unpowered state)")
    sh.w(rg["2"], (208.28, M["GATE"][1]), r16["1"], q["G"])
    sh.nl("Q102_G", (208.28, M["GATE"][1]))
    down_gnd(r16["2"])
    QS = (q["S"][0], q["S"][1] + 5.08)
    sh.w(q["S"], QS)
    r17 = vR("R117", R_SENSE, QS[0], QS[1] + 2.54, "Current sense (0.42-0.49 A limit)", "1 %, >= 0.25 W")
    sh.w(QS, r17["1"])
    down_gnd(r17["2"])
    tp("TP107", "GND", (226.06, r17["2"][1]), textpos=(1.27, -4.0))
    down_gnd((226.06, r17["2"][1]))
    r18 = hR("R118", "100", 246.38, QS[1], "CS filter R")
    sh.w(QS, (236.22, QS[1]), r18["1"])
    sh.nl("Q102_S", (236.22, QS[1]))
    c19 = vC("C119", "470pF", 259.08, QS[1], "CS filter C (pump surge)", "50 V C0G")
    sh.w(r18["2"], (259.08, QS[1]), (266.7, QS[1]))
    sh.nl("LM5156_CS", (266.7, QS[1]))
    down_gnd(c19["2"])
    # inductor, boost diode, V_b
    Y = 167.64
    lh = h2(L, "L102", L_HV["value"], 220.98, Y, F("HV boost inductor", L_HV["mpn"], L_HV["mfr"], L_HV["note"]), L_HV["fp"])
    sh.w((190.5 - 2.54, Y), (195.58, Y), (208.28, Y), lh["1"])
    sh.nl("12V_HV", (190.5 - 2.54, Y), 180)
    for ref, val, x, fn, rating, fp in (("C120", "10uF 35V", 195.58, "Boost input", "35 V X7R", FP_C1210),
                                        ("C121", "0.1uF", 208.28, "Boost input HF", "50 V X7R", FP_C)):
        c = vC(ref, val, x, Y, fn, rating, fp)
        down_gnd(c["2"])
    SW = (q["D"][0], Y)
    sh.w(q["D"], SW)
    sh.w(SW, (SW[0], Y - 5.08))
    tp("TP105", "SW", (SW[0], Y - 5.08), textpos=(1.27, -3.0))
    d = sh.place(D, "D103", "ES1J", 246.38, Y, angle=180, footprint=FP_SMA,
                 fields=F("Boost diode", "ES1J", "onsemi", "600 V, 1 A, 35 ns"))
    sh.w(lh["2"], SW, (238.76, Y), d["A"])
    sh.nl("SW", (238.76, Y))
    XV1, XTV, XVO, XL5 = 276.86, 287.02, 297.18, 304.8
    vb = [256.54, 261.62, XV1, XTV, XVO, XL5]
    sh.w(d["K"], *[(x, Y) for x in vb])
    sh.nl("V_B", (261.62, Y))
    c = v2(C, "C122", "0.47uF 400V", 256.54, Y + 3.81, F("Tripler stack C1 (V_b)", rating="400 V PET film"), FP_FILM)
    sh.w((256.54, Y), c["1"])
    down_gnd(c["2"])
    ra = vR("R119", "1.2M", XV1, Y, "V_b bleeder 1/2")
    rb = vR("R120", "1.2M", XV1, ra["2"][1] + 5.08, "V_b bleeder 2/2")
    sh.w(ra["2"], (XV1, ra["2"][1] + 2.54), rb["1"])
    sh.nl("STR_VBB", (XV1, ra["2"][1] + 2.54))
    down_gnd(rb["2"])
    tp("TP106", "V_B", (XTV, Y))
    lk = link("LK5", XL5, Y, "D11 link L5: V_b to the G+/RTN regulators", hv=True)
    sh.w(lk["2"], (XL5 + 15.24, Y))
    sh.gl("V_B_BIAS", (XL5 + 15.24, Y), 0)
    # V_b overvoltage: 2 x 1.0M / 12.4k -> TLV3011 (~202 V), wired-OR on EN/UVLO
    ra = vR("R141", "1.0M", XVO, Y, "V_b OVP string 1/2 (<= 100 V per part)")
    rb = vR("R142", "1.0M", XVO, ra["2"][1] + 5.08, "V_b OVP string 2/2")
    sh.w(ra["2"], (XVO, ra["2"][1] + 2.54), rb["1"])
    sh.nl("STR_VO1", (XVO, ra["2"][1] + 2.54))
    VS = (XVO, rb["2"][1] + 2.54)
    sh.w(rb["2"], VS)
    r = vR("R143", "12.4k", XVO, VS[1], "V_b OVP divider, lower (trip ~202 V)", "1 %")
    down_gnd(r["2"])

    def comparator(ref, x, y, sense_pt, cap_x, sense, refnet, cref, cpre, fn):
        u = sh.place("dekatron:TLV3011", ref, "TLV3011", x, y, textpos=(3.0, -10.5),
                     fields=F(fn, "TLV3011AIDBVR", "Texas Instruments", "1.242 V ref"))
        c = vC(cref, "1nF", cap_x, sense_pt[1], f"{cpre} sense filter", "50 V C0G")
        sh.w(sense_pt, (cap_x, sense_pt[1]), (cap_x + 2.54, sense_pt[1]), u["IN-"])
        sh.nl(sense, (cap_x + 2.54, sense_pt[1]))
        down_gnd(c["2"])
        xt = u["IN+"][0] - 2.54                      # REF tied to IN+ (crosses IN- without connecting)
        sh.w(u["IN+"], (xt, u["IN+"][1]), (xt, u["REF"][1]), u["REF"])
        sh.nl(refnet, (xt, u["IN+"][1]), 90)
        sh.w(u["V+"], (x, u["V+"][1] - 2.54))
        sh.pwr("+5V", (x, u["V+"][1] - 2.54))
        down_gnd(u["V-"])
        sh.w(u["OUT"], (u["OUT"][0] + 7.62, y))
        sh.nl("HV_EN_PIN", (u["OUT"][0] + 7.62, y))
        return u

    comparator("U108", 340.36, VS[1] - 2.54, VS, 307.34, "VB_OVP_SENSE", "VB_OVP_REF", "C129", "V_b OVP",
               "V_b OVP comparator (open drain, wired-OR on EN/UVLO)")
    c = vC("C130", "0.1uF", 373.38, 177.8, "U108 bypass", "50 V X7R")
    sh.w(c["1"], (373.38, 175.26))
    sh.pwr("+5V", (373.38, 175.26))
    down_gnd(c["2"])

    # ==== TRIPLER, BLEEDER, FEEDBACK, MONITOR, OVP ==================================================
    note("TRIPLER (series-stack Cockcroft-Walton)", "Every capacitor and diode sees <= V_b; 47 ohm pump surge resistor;\n"
         "LK3 isolates the DC column for fault finding (never powered open)", 15.24, 233.68)
    YT, YB, YM = 251.46, 276.86, 264.16
    lk = link("LK3", 22.86, YT, "D11 link L3: V_b to the tripler DC column (fault isolation; never powered open)", hv=True)
    sh.w((17.78, YT), lk["1"])
    sh.nl("V_B", (17.78, YT), 180)
    rp = hR("R121", "47", 22.86, YB, "Pump surge resistor")
    sh.w((17.78, YB), rp["1"])
    sh.nl("SW", (17.78, YB), 180)
    film = F("", rating="400 V PET film")
    caps = {}
    for ref, x, y, fn in (("C125", 72.39, YT, "Tripler stack C2"), ("C126", 113.03, YT, "Tripler stack C3"),
                          ("C123", 46.99, YB, "Tripler pump CP1"), ("C124", 87.63, YB, "Tripler pump CP2")):
        caps[ref] = h2(C, ref, "0.47uF 400V", x, y, dict(film, Function=fn), FP_FILM)
    taps = {}
    for ref, x, k_top in (("D104", 63.5, False), ("D105", 83.82, True), ("D106", 104.14, False), ("D107", 124.46, True)):
        d = sh.place(D, ref, "ES1J", x, YM, angle=270 if k_top else 90, footprint=FP_SMA,
                     fields=F("Tripler diode", "ES1J", "onsemi", "600 V, 1 A, 35 ns"))
        top, bot = (d["K"], d["A"]) if k_top else (d["A"], d["K"])
        sh.w((x, YT), top)
        sh.w(bot, (x, YB))
    BUS = [144.78, 170.18, 195.58, 220.98, 246.38, 256.54, 266.7]
    sh.w(lk["2"], (33.02, YT), (63.5, YT), caps["C125"]["1"])
    sh.nl("V_BT", (33.02, YT))
    sh.w(caps["C125"]["2"], (83.82, YT), (88.9, YT), (104.14, YT), caps["C126"]["1"])
    sh.nl("TRP_N2", (88.9, YT))
    sh.w(caps["C126"]["2"], (124.46, YT), (127.0, YT), *[(x, YT) for x in BUS])
    sh.nl("HV_STACK", (127.0, YT))
    sh.w(rp["2"], (33.02, YB), caps["C123"]["1"])
    sh.nl("TRP_PUMP", (33.02, YB))
    sh.w(caps["C123"]["2"], (63.5, YB), (66.04, YB), (83.82, YB), caps["C124"]["1"])
    sh.nl("TRP_P1", (66.04, YB))
    sh.w(caps["C124"]["2"], (104.14, YB), (106.68, YB), (124.46, YB))
    sh.nl("TRP_P2", (106.68, YB))

    def string(x, refs, val, mids, fn, dnp=False, suffix=""):
        """Vertical resistor string hanging from the HV_STACK bus; returns the bottom pin."""
        y1 = YT + 5.08
        sh.w((x, YT), (x, y1))
        last = None
        for k, ref in enumerate(refs):
            rr = vR(ref, val, x, y1, f"{fn} {k + 1}/{len(refs)}{suffix}", dnp=dnp)
            if last is not None:
                sh.w(last, (x, last[1] + 2.54), rr["1"])
                sh.nl(mids[k - 1], (x, last[1] + 2.54))
            last = rr["2"]
            y1 = rr["2"][1] + 5.08
        return last

    def tap(bottom, x, lower_ref, lower_val, fn, rating="1 %"):
        node = (x, bottom[1] + 2.54)
        sh.w(bottom, node)
        r = vR(lower_ref, lower_val, x, node[1], fn, rating)
        down_gnd(r["2"])
        return node

    note("HV STRINGS (D2, D3, D12)", "Bleeder, feedback, monitor and OVP strings, each part <= 150 V; always connected",
         139.7, 233.68)
    b = string(144.78, ["R122", "R123", "R124", "R125"], "1.2M", ["STR_BL1", "STR_BL2", "STR_BL3"], "HV bleeder",
               suffix=" (<= 150 V per part)")
    down_gnd(b)
    b = string(170.18, ["R126", "R127", "R128", "R129"], "1.1M", ["STR_FB1", "STR_FB2", "STR_FB3"], "HV feedback string")
    n = tap(b, 170.18, "R130", "9.76k", "HV feedback, lower (451.8 V; 8.87k for 500 V)")
    sh.w(n, (175.26, n[1]))
    sh.nl("LM5156_FB", (175.26, n[1]))
    b = string(195.58, ["R131", "R132", "R133", "R134"], "2.2M", ["STR_MN1", "STR_MN2", "STR_MN3"], "HV monitor string")
    n = tap(b, 195.58, "R135", "47k", "HV monitor, lower (2.39 V at 450 V)")
    sh.w(n, (200.66, n[1]))
    sh.gl("HV_SENSE", (200.66, n[1]), 0)
    b = string(220.98, [f"R{145 + k}" for k in range(6)], "150k", [f"STR_DH{k}" for k in range(1, 6)],
               "HV dummy load", dnp=True, suffix=" (bring-up only, LK4 open)")
    down_gnd(b)
    b = string(246.38, ["R136", "R137", "R138", "R139"], "2.2M", ["STR_OV1", "STR_OV2", "STR_OV3"], "OVP string")
    n = tap(b, 246.38, "R140", "20.0k", "OVP divider, lower (trip ~548 V)")
    comparator("U107", 292.1, n[1] - 2.54, n, 259.08, "OVP_SENSE", "OVP_REF", "C127", "OVP",
               "Independent OVP comparator (open drain)")
    c = vC("C128", "0.1uF", 325.12, 295.91, "U107 bypass", "50 V X7R")
    sh.w(c["1"], (325.12, 292.1))
    sh.pwr("+5V", (325.12, 292.1))
    down_gnd(c["2"])
    tp("TP108", "HV_STACK", (256.54, YT), textpos=(1.27, -6.4))
    lk = link("LK4", 266.7, YT, "D11 link L4: tripler output to the anode string", hv=True)
    sh.w(lk["2"], (281.94, YT))
    sh.gl("HV", (281.94, YT), 0)
    sh.finish()
    return sh


    # ---- Row 4: tripler, bleeder, feedback ------------------------------------------------------
    y = 290
    note("TRIPLER (series-stack CW): every capacitor and diode sees <= V_b; 47 ohm pump surge resistor", 20, y - 40)
    link("LK3", 30, y - 20, "V_B", "V_BT", "D11 link L3: V_b to the tripler DC column (fault isolation; never powered open)", hv=True)
    r("R121", "47", 30, y + 5, "SW", "TRP_PUMP", "Pump surge resistor", angle=H)
    sh.part(C, "C123", "0.47uF 400V", 60, y + 5, {"1": "TRP_PUMP", "2": "TRP_P1"}, angle=H, footprint=FP_FILM,
            fields=F("Tripler pump CP1", rating="400 V PET film"))
    sh.part(C, "C124", "0.47uF 400V", 95, y + 5, {"1": "TRP_P1", "2": "TRP_P2"}, angle=H, footprint=FP_FILM,
            fields=F("Tripler pump CP2", rating="400 V PET film"))
    sh.part(C, "C125", "0.47uF 400V", 60, y - 25, {"1": "V_BT", "2": "TRP_N2"}, angle=H, footprint=FP_FILM,
            fields=F("Tripler stack C2", rating="400 V PET film"))
    sh.part(C, "C126", "0.47uF 400V", 95, y - 25, {"1": "TRP_N2", "2": "HV_STACK"}, angle=H, footprint=FP_FILM,
            fields=F("Tripler stack C3", rating="400 V PET film"))
    for i, (ref, a, k) in enumerate((("D104", "V_BT", "TRP_P1"), ("D105", "TRP_P1", "TRP_N2"),
                                     ("D106", "TRP_N2", "TRP_P2"), ("D107", "TRP_P2", "HV_STACK"))):
        sh.part(D, ref, "ES1J", 125 + i * 18, y - 10, {"K": k, "A": a}, angle=90, footprint=FP_SMA,
                fields=F("Tripler diode", "ES1J", "onsemi", "600 V, 1 A, 35 ns"))
    # Bleeder 4 x 1.2M and feedback divider 4 x 1.1M + 9.76k, both always connected (D12, D2)
    chain = [("R122", "HV_STACK", "STR_BL1"), ("R123", "STR_BL1", "STR_BL2"), ("R124", "STR_BL2", "STR_BL3"), ("R125", "STR_BL3", "GND")]
    for i, (ref, a, b) in enumerate(chain):
        r(ref, "1.2M", 210 + i * 14, y - 10, a, b, f"HV bleeder {i + 1}/4 (<= 150 V per part)")
    chain = [("R126", "HV_STACK", "STR_FB1"), ("R127", "STR_FB1", "STR_FB2"), ("R128", "STR_FB2", "STR_FB3"), ("R129", "STR_FB3", "LM5156_FB")]
    for i, (ref, a, b) in enumerate(chain):
        r(ref, "1.1M", 275 + i * 14, y - 10, a, b, f"HV feedback string {i + 1}/4")
    r("R130", "9.76k", 335, y - 10, "LM5156_FB", "GND", "HV feedback, lower (451.8 V; 8.87k for 500 V)", rating="1 %")
    link("LK4", 360, y - 20, "HV_STACK", "HV", "D11 link L4: tripler output to the anode string", hv=True)
    tp("TP108", "HV_STACK", 385, y - 10)

    # ---- Row 5: HV monitor, independent OVP, dummy loads ----------------------------------------
    y = 370
    note("HV MONITOR (HV_SENSE, GP28), INDEPENDENT OVP on HV (~548 V) and on V_b (~202 V): both pull EN/UVLO low", 20, y - 40)
    chain = [("R131", "HV_STACK", "STR_MN1"), ("R132", "STR_MN1", "STR_MN2"), ("R133", "STR_MN2", "STR_MN3"), ("R134", "STR_MN3", "HV_SENSE")]
    for i, (ref, a, b) in enumerate(chain):
        r(ref, "2.2M", 25 + i * 14, y - 10, a, b, f"HV monitor string {i + 1}/4")
    r("R135", "47k", 85, y - 10, "HV_SENSE", "GND", "HV monitor, lower (2.39 V at 450 V)", rating="1 %")
    chain = [("R136", "HV_STACK", "STR_OV1"), ("R137", "STR_OV1", "STR_OV2"), ("R138", "STR_OV2", "STR_OV3"), ("R139", "STR_OV3", "OVP_SENSE")]
    for i, (ref, a, b) in enumerate(chain):
        r(ref, "2.2M", 110 + i * 14, y - 10, a, b, f"OVP string {i + 1}/4")
    r("R140", "20.0k", 170, y - 10, "OVP_SENSE", "GND", "OVP divider, lower (trip ~548 V)", rating="1 %")
    c("C127", "1nF", 182, y - 10, "OVP_SENSE", "GND", "OVP sense filter", rating="50 V C0G")
    sh.part("dekatron:TLV3011", "U107", "TLV3011", 215, y - 10,
            {"1": "HV_EN_PIN", "2": "GND", "3": "OVP_REF", "4": "OVP_SENSE", "5": "OVP_REF", "6": "+5V"},
            fields=F("Independent OVP comparator (open drain)", "TLV3011AIDBVR", "Texas Instruments", "1.242 V ref"))
    c("C128", "0.1uF", 240, y - 10, "+5V", "GND", "U107 bypass", rating="50 V X7R")
    # V_b overvoltage (review fix): with feedback from HV, an open tripler part lets V_b run away
    # unseen by the HV OVP. A second TLV3011 trips at ~202 V (2 x 1.0M / 12.4k) on the same EN node.
    r("R141", "1.0M", 255, y - 10, "V_B", "STR_VO1", "V_b OVP string 1/2 (<= 100 V per part)")
    r("R142", "1.0M", 269, y - 10, "STR_VO1", "VB_OVP_SENSE", "V_b OVP string 2/2")
    r("R143", "12.4k", 283, y - 10, "VB_OVP_SENSE", "GND", "V_b OVP divider, lower (trip ~202 V)", rating="1 %")
    c("C129", "1nF", 295, y - 10, "VB_OVP_SENSE", "GND", "V_b OVP sense filter", rating="50 V C0G")
    sh.part("dekatron:TLV3011", "U108", "TLV3011", 325, y - 10,
            {"1": "HV_EN_PIN", "2": "GND", "3": "VB_OVP_REF", "4": "VB_OVP_SENSE", "5": "VB_OVP_REF", "6": "+5V"},
            fields=F("V_b OVP comparator (open drain, wired-OR on EN/UVLO)", "TLV3011AIDBVR", "Texas Instruments", "1.242 V ref"))
    c("C130", "0.1uF", 350, y - 10, "+5V", "GND", "U108 bypass", rating="50 V X7R")
    # HV dummy load for bring-up step 2 (DNP): 6 x 150k (0.5 mA at 450 V), fitted with LK4 open
    for i in range(6):
        a = "HV_STACK" if i == 0 else f"STR_DH{i}"
        b = "GND" if i == 5 else f"STR_DH{i + 1}"
        r(f"R{145 + i}", "150k", 375 + i * 14, y - 10, a, b, f"HV dummy load {i + 1}/6 (bring-up only, LK4 open)", dnp=True)
    return sh


# --------------------------------------------------------------------------------------
# tube.kicad_sch
# --------------------------------------------------------------------------------------

TUBE_GLOBALS = {"HV", "V_B_BIAS", "GUIDE1", "GUIDE2", "NDX", "RTN_SENSE"}
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"            # MMBTA42 / MMBTA92: 1 B, 2 E, 3 C (Nexperia)
FP_WIRE1 = "Connector_Wire:SolderWire-0.5sqmm_1x01_D0.9mm_OD2.3mm"
FP_WIRE6 = "Connector_Wire:SolderWire-0.5sqmm_1x06_P4.8mm_D0.9mm_OD2.3mm"
FP_WIRE4 = "Connector_Wire:SolderWire-0.5sqmm_1x04_P4.8mm_D0.9mm_OD2.3mm"


def build_tube(lib: SymbolLib) -> Sheet:
    sh = Sheet("tube", "tube.kicad_sch", U("file:tube"), "A3", lib, f"/{ROOT_UUID}/{TUBE_UUID}",
               global_nets=TUBE_GLOBALS, title="Tube: G+ / RTN bias, guide drivers, index sense, anode, harness")
    R, C, DZ, TP = "Device:R", "Device:C", "Device:D_Zener", "Connector:TestPoint"
    g = 2.54

    def note(head, detail, x, y):
        sh.text(head, x, y, 2.0)
        sh.text(detail, x, y + 4.32, 1.27)

    # ---- bias regulator: V_B_BIAS -> 2 x 20k -> G+ -> 39 V zener -> RTN -> 51 V zener -> GND ---------
    note("BIAS REGULATOR (D1, D8)", "RTN = 51 V zener (sinks the tube current); G+ = RTN + 39 V = 90 V", 15.24, 25.4)
    X = 40.64
    r1 = sh.place(R, "R201", "20k", X, 45.72, footprint=FP_R, fields=F("G+ / RTN feed 1/2 (2 x 20k: 1.5-2.1 mA)"))
    r2 = sh.place(R, "R218", "20k", X, 58.42, footprint=FP_R, fields=F("G+ / RTN feed 2/2 (<= 93 mW per part at V_b 175 V)"))
    sh.w(r1["1"], (X, 38.1))
    sh.gl("V_B_BIAS", (X, 38.1), 90)
    sh.w(r1["2"], r2["1"])
    sh.nl("STR_GF1", (X, 52.07))
    sh.w((X, 49.53), (X, 52.07), (X, 54.61))
    GP = (X, 66.04)
    sh.w(r2["2"], GP)
    d1 = sh.place(DZ, "D201", "39V", X, 76.2, angle=270, footprint=FP_SOD123,
                  fields=F("G+ above RTN: guide bias 39 V", "MMSZ5259B", "onsemi", "39 V, 500 mW"))
    sh.w(GP, d1["K"])
    RT = (X, 86.36)
    sh.w(d1["A"], RT)
    d2 = sh.place(DZ, "D202", "51V", X, 96.52, angle=270, footprint=FP_SOD123,
                  fields=F("RTN shunt regulator: sinks tube current", "MMSZ5262B", "onsemi", "51 V, 500 mW"))
    sh.w(RT, d2["K"])
    sh.w(d2["A"], (X, 104.14))
    sh.gnd((X, 104.14))
    c1 = sh.place(C, "C201", "0.1uF 100V", 55.88, 76.2, footprint=FP_C, fields=F("G+ to RTN bypass", rating="100 V X7R"))
    c2 = sh.place(C, "C202", "1uF 100V", 55.88, 96.52, footprint=FP_C,
                  fields=F("RTN bypass: absorbs tube and guide current steps", rating="100 V X7R"))
    tp1 = sh.place(TP, "TP201", "GPLUS", 48.26, 66.04, footprint=FP_TP, fields=F("Test point GPLUS"))
    tp2 = sh.place(TP, "TP202", "RTN", 48.26, 86.36, footprint=FP_TP, fields=F("Test point RTN"))
    sh.w(GP, (48.26, 66.04), (55.88, 66.04))
    sh.w((55.88, 66.04), c1["1"])
    sh.w(c1["2"], (55.88, 86.36))
    sh.w(RT, (48.26, 86.36), (55.88, 86.36))
    sh.w((55.88, 86.36), c2["1"])
    sh.w(c2["2"], (55.88, 104.14))
    sh.gnd((55.88, 104.14))
    sh.nl("GPLUS", (76.2, 66.04))
    sh.nl("RTN", (63.5, 86.36))
    # RTN_SENSE divider (2 x 100k / 10k) to the ADC
    sh.w(RT, (25.4, 86.36))
    a = sh.place(R, "R202", "100k", 25.4, 96.52, footprint=FP_R, fields=F("RTN_SENSE divider 1/2"))
    b = sh.place(R, "R203", "100k", 25.4, 109.22, footprint=FP_R, fields=F("RTN_SENSE divider 2/2"))
    c = sh.place(R, "R204", "10k", 25.4, 127.0, footprint=FP_R, fields=F("RTN_SENSE divider, lower (2.43 V at 51 V)", rating="1 %"))
    sh.w((25.4, 86.36), a["1"])
    sh.w(a["2"], b["1"])
    sh.nl("STR_RS1", (25.4, 102.87))
    sh.w((25.4, 100.33), (25.4, 102.87), (25.4, 105.41))
    NS = (25.4, 116.84)
    sh.w(b["2"], NS, c["1"])
    sh.w(NS, (15.24, 116.84))
    sh.gl("RTN_SENSE", (15.24, 116.84), 180)
    sh.w(c["2"], (25.4, 134.62))
    sh.gnd((25.4, 134.62))
    tpg = sh.place(TP, "TP206", "GND", 66.04, 106.68, footprint=FP_TP, fields=F("Test point GND"))
    sh.w((66.04, 106.68), (66.04, 109.22))
    sh.gnd((66.04, 109.22))
    # G+ bus to the guide drivers, RTN branch down to the index sense
    sh.w((55.88, 66.04), (121.92, 66.04), (172.72, 66.04))
    sh.w((55.88, 86.36), (71.12, 86.36))

    # ---- guide drivers: pull-up to G+, MMBTA42 pulls the guide to ~0 V -------------------------------
    note("GUIDE DRIVERS (D8)", "MMBTA42 pulls a guide from G+ to ~0 V; 47k base pull-down = guides at rest in reset", 96.52, 25.4)
    for n, xc in ((1, 121.92), (2, 172.72)):
        pu = sh.place(R, f"R{205 + 3 * (n - 1)}", "470k", xc, 76.2, footprint=FP_R, fields=F(f"Guide {n} pull-up to G+ (<= 90 V)"))
        q = sh.place("Transistor_BJT:Q_NPN_BEC", f"Q{200 + n}", "MMBTA42", xc - g, 96.52, footprint=FP_SOT23,
                     fields=F(f"Guide {n} driver", "MMBTA42", "Nexperia", "300 V NPN"))
        rb = sh.place(R, f"R{206 + 3 * (n - 1)}", "10k", xc - 17.78, 96.52, angle=90, footprint=FP_R,
                      fields=F(f"Guide {n} base resistor (0.24 mA from 3.3 V)"))
        rd = sh.place(R, f"R{207 + 3 * (n - 1)}", "47k", xc - 10.16, 106.68, footprint=FP_R,
                      fields=F(f"Guide {n} base pull-down (reset = at rest)"))
        tp = sh.place(TP, f"TP{202 + n}", f"TUBE_G{n}", xc + 15.24, 86.36, footprint=FP_TP, fields=F(f"Test point TUBE_G{n}"))
        sh.w((xc, 66.04), pu["1"])
        node = (xc, 86.36)
        sh.w(pu["2"], node, q["C"])
        sh.w(node, (xc + 15.24, 86.36))
        sh.nl(f"TUBE_G{n}", (xc + 2.54, 86.36))
        sh.w(q["E"], (xc, 105.41))
        sh.gnd((xc, 105.41))
        bn = (xc - 10.16, 96.52)
        sh.w(rb["2"], bn, q["B"])
        sh.w(bn, rd["1"])
        sh.nl(f"G{n}_B", (xc - 12.7, 96.52))
        sh.w(rd["2"], (xc - 10.16, 114.3))
        sh.gnd((xc - 10.16, 114.3))
        sh.w(rb["1"], (xc - 25.4, 96.52))
        sh.gl(f"GUIDE{n}", (xc - 25.4, 96.52), 180)

    # ---- index sense: K1 lifts the MMBTA92 emitter above RTN; collector into the divider ----------
    note("INDEX SENSE (D9)", "MMBTA92 level shifter from K1 (pin 13); 220k / 13k -> ~2.9 V at NDX; clamp at the RP2040", 15.24, 142.24)
    q = sh.place("Transistor_BJT:Q_PNP_BEC", "Q203", "MMBTA92", 83.82, 167.64, mirror="x", footprint=FP_SOT23,
                 fields=F("Index level shifter", "MMBTA92", "Nexperia", "300 V PNP"))
    # RTN from the regulator down to the base
    sh.w((71.12, 86.36), (71.12, 154.94), (71.12, 167.64), q["B"])
    rk = sh.place(R, "R211", "220k", 78.74, 154.94, angle=270, footprint=FP_R, fields=F("Holds K1 at RTN when not lit"))
    K1 = (q["E"][0], 154.94)
    sh.w(q["E"], K1, rk["1"])
    sh.w(rk["2"], (71.12, 154.94))
    sh.w(K1, (q["E"][0], 149.86), (96.52, 149.86))
    sh.nl("TUBE_K1", (96.52, 149.86))
    c1x = q["C"][0]
    r12 = sh.place(R, "R212", "110k", c1x, 180.34, footprint=FP_R, fields=F("Index divider top 1/2 (167 V fault: 84 V per part)"))
    r13 = sh.place(R, "R213", "110k", c1x, 193.04, footprint=FP_R, fields=F("Index divider top 2/2"))
    sh.w(q["C"], (c1x, 173.99), r12["1"])
    sh.nl("NDX_C", (c1x, 173.99))
    sh.w(r12["2"], (c1x, 186.69), r13["1"])
    sh.nl("STR_NX1", (c1x, 186.69))
    ND = (c1x, 200.66)
    sh.w(r13["2"], ND)
    r14 = sh.place(R, "R214", "13k", c1x, 210.82, footprint=FP_R, fields=F("Index divider, lower", rating="1 %"))
    c4 = sh.place(C, "C204", "1nF", c1x + 12.7, 210.82, footprint=FP_C, fields=F("Index filter (tau 12 us)", rating="50 V C0G"))
    sh.w(ND, r14["1"])
    sh.w(ND, (c1x + 12.7, 200.66), c4["1"])
    sh.w(r14["2"], (c1x, 218.44))
    sh.gnd((c1x, 218.44))
    sh.w(c4["2"], (c1x + 12.7, 218.44))
    sh.gnd((c1x + 12.7, 218.44))
    tp5 = sh.place(TP, "TP205", "NDX", c1x + 20.32, 200.66, footprint=FP_TP, fields=F("Test point NDX"))
    sh.w((c1x + 12.7, 200.66), (c1x + 20.32, 200.66), (c1x + 27.94, 200.66))
    sh.gl("NDX", (c1x + 27.94, 200.66), 0)

    # ---- anode string and tube harness -------------------------------------------------------------
    note("ANODE STRING (D1)", "3 x 220k (3 x 270k for the 500 V setting), <= 100 V per part", 152.4, 142.24)
    note("TUBE HARNESS (D14)", "Wires soldered to board and socket; cathodes tied at the socket", 205.74, 76.2)
    xs = [167.64, 182.88, 198.12]
    rs = [sh.place(R, ref, "220k", x, 160.02, angle=90, footprint=FP_R,
                   fields=F(f"Anode resistor {k + 1}/3 (<= 100 V per part)")) for k, (ref, x) in enumerate(zip(("R215", "R216", "R217"), xs))]
    sh.w((157.48, 160.02), rs[0]["1"])
    sh.gl("HV", (157.48, 160.02), 180)
    sh.w(rs[0]["2"], rs[1]["1"])
    sh.w(rs[1]["2"], rs[2]["1"])
    sh.nl("STR_A1", (rs[0]["2"][0] + 1.27, 160.02))
    sh.nl("STR_A2", (rs[1]["2"][0] + 1.27, 160.02))
    j1 = sh.place("Connector_Generic:Conn_01x01", "J201", "TUBE_ANODE", 223.52, 160.02, footprint=FP_WIRE1,
                  fields=F("Tube harness: anode (pin 8), 600 V wire, kept >= 3 mm from other pads"))
    sh.w(rs[2]["2"], (208.28, 160.02), j1["1"])
    sh.nl("ANODE", (208.28, 160.02))
    jh = sh.place("Connector_Generic:Conn_01x04", "J202", "TUBE", 248.92, 96.52, footprint=FP_WIRE4,
                  fields=F("Tube harness: G1 (pin 5), G2 (10), K1 index (13), RTN = K0, K2-K9 tied at the socket"))
    for pin, name in (("1", "TUBE_G1"), ("2", "TUBE_G2"), ("3", "TUBE_K1"), ("4", "RTN")):
        e = jh[pin]
        sh.w(e, (e[0] - 10.16, e[1]))
        sh.nl(name, (e[0] - 10.16, e[1]), 180)
    sh.text("A101 socket: anode 8, G1 5, G2 10, K1 13;\nK0, K2-K9 (pins 1-4, 6, 7, 9, 11, 12) tied together onto RTN",
            205.74, 111.76, 1.27)
    sh.finish()
    return sh


# --------------------------------------------------------------------------------------
# mcu.kicad_sch
# --------------------------------------------------------------------------------------

MCU_GLOBALS = {"5V_DISP", "5V_MCU", "5V_NIX", "HV_EN", "PGOOD", "OVP_TRIP", "HV_SENSE", "GUIDE1",
               "GUIDE2", "NDX", "RTN_SENSE", "VIN_PROT"}
FP_WIRE5 = "Connector_Wire:SolderWire-0.5sqmm_1x05_P4.8mm_D0.9mm_OD2.3mm"


def build_mcu(lib: SymbolLib) -> Sheet:
    sh = Sheet("mcu", "mcu.kicad_sch", U("file:mcu"), "A3", lib, f"/{ROOT_UUID}/{MCU_UUID}",
               global_nets=MCU_GLOBALS, title="MCU: RP2040-Zero, ADC conditioning, I2C, harness landings")
    R, C, TP = "Device:R", "Device:C", "Connector:TestPoint"

    def note(head, detail, x, y):
        sh.text(head, x, y, 2.0)
        sh.text(detail, x, y + 4.32, 1.27)

    def tp(ref, net, x, y):
        sh.part(TP, ref, net, x, y, {"1": net}, footprint=FP_TP, fields=F(f"Test point {net}"))

    # ---- RP2040-Zero: pin stubs carry the signal names ---------------------------------------------
    note("RP2040-Zero (pin map: docs/hardware.md)", "Castellated, soldered by its edge pads; USB-C at the board edge", 15.24, 22.86)
    nets = {"5V": "5V_MCU", "GND": "GND", "3V3": "+3V3",
            "GP0": "UART_TX", "GP1": "UART_RX", "GP2": "SDA", "GP3": "SCL", "GP4": "GUIDE1", "GP5": "GUIDE2",
            "GP6": "HV_EN", "GP7": "PGOOD", "GP8": "OVP_TRIP", "GP9": "GP9", "GP10": "GP10", "GP11": "GP11",
            "GP12": "GP12", "GP13": "GP13", "GP14": "GP14", "GP15": "GP15",
            "GP26": "NDX", "GP27": "VIN_SENSE", "GP28": "HV_SENSE", "GP29": "RTN_SENSE"}
    sh.part("dekatron:RP2040-Zero", "U301", "RP2040-Zero", 106.68, 81.28, nets, textpos=(-12.7, -27.5),
            fields=F("Dekatron controller MCU", "RP2040-Zero", "Waveshare", "headerless, castellated"))
    # supply decoupling at the module
    for ref, val, x, kind, fn, rating in (("C301", "10uF", 33.02, "5V_MCU", "5V_MCU bulk at the module", "16 V X7R"),
                                          ("C302", "0.1uF", 48.26, "+3V3", "3V3 bypass", "50 V X7R")):
        cp = sh.place(C, ref, val, x, 53.34, footprint=FP_C, fields=F(fn, rating=rating))
        sh.w(cp["1"], (x, 45.72))
        if kind == "+3V3":
            sh.pwr("+3V3", (x, 45.72))
        else:
            sh.gl(kind, (x, 45.72), 90)
        sh.w(cp["2"], (x, 60.96))
        sh.gnd((x, 60.96))
    note("TEST PADS", "Debug UART, spare GPIOs, supplies", 160.02, 35.56)
    for i, (ref, net) in enumerate((("TP301", "UART_TX"), ("TP302", "UART_RX"), ("TP303", "GP9"), ("TP304", "GP10"),
                                    ("TP305", "GP11"), ("TP306", "GP13"), ("TP307", "GP14"), ("TP308", "GP15"),
                                    ("TP309", "+3V3"), ("TP310", "5V_MCU"), ("TP311", "GND"))):
        tp(ref, net, 162.56 + (i % 6) * 15.24, 50.8 + (i // 6) * 25.4)

    # ---- ADC conditioning: input -> node -> BAT54S clamp (GND / 3V3) + reservoir capacitor -----------
    note("ADC INPUTS", "BAT54S clamp to 3V3 / GND and a local reservoir capacitor at every input "
         "(NDX keeps its 1 nF on the tube sheet)", 15.24, 137.16)
    yb, yn = 160.02, 175.26
    for i, (net, cap) in enumerate((("VIN_SENSE", "100nF"), ("HV_SENSE", "100nF"), ("RTN_SENSE", "100nF"), ("NDX", None))):
        xc = 55.88 + i * 50.8
        d = sh.place("Diode:BAT54S", f"D{301 + i}", "BAT54S", xc, yb, textpos=(-4, -6),
                     fields=F(f"{net} clamp to 3V3 / GND", "BAT54S", rating="30 V Schottky pair"))
        sh.w(d["A"], (d["A"][0], yb + 5.08))
        sh.gnd((d["A"][0], yb + 5.08))
        sh.w(d["K"], (d["K"][0], yb - 5.08))
        sh.pwr("+3V3", (d["K"][0], yb - 5.08))
        N = (xc, yn)
        sh.w(d["COM"], N)
        if cap:
            cp = sh.place(C, f"C{303 + i}", cap, xc, 182.88, footprint=FP_C,
                          fields=F(f"{net} ADC sampling reservoir", rating="25 V X7R"))
            sh.w(N, cp["1"])
            sh.w(cp["2"], (xc, 190.5))
            sh.gnd((xc, 190.5))
        if net == "VIN_SENSE":
            M = (xc - 10.16, yn)
            r1 = sh.place(R, "R301", "100k", xc - 20.32, yn, angle=90, footprint=FP_R,
                          fields=F("VIN_SENSE divider, upper (1.29 V at 12 V)"))
            r2 = sh.place(R, "R302", "12k", M[0], 182.88, footprint=FP_R,
                          fields=F("VIN_SENSE divider, lower (2.57 V at 24 V)", rating="1 %"))
            sh.w(r1["2"], M, (xc - 5.08, yn), N)
            sh.nl("VIN_SENSE", (xc - 5.08, yn))
            sh.w(M, r2["1"])
            sh.w(r2["2"], (M[0], 190.5))
            sh.gnd((M[0], 190.5))
            sh.w(r1["1"], (xc - 30.48, yn))
            sh.gl("VIN_PROT", (xc - 30.48, yn), 180)
        else:
            sh.w(N, (xc - 15.24, yn))
            sh.gl(net, (xc - 15.24, yn), 180)

    # ---- I2C pull-ups ------------------------------------------------------------------------------
    note("I2C (target, 100 kHz)", "The bus pull-ups for the whole instrument live here (the display module has none)", 15.24, 215.9)
    ys, yc, yt = 248.92, 256.54, 228.6
    rsda = sh.place(R, "R303", "4.7k", 55.88, 236.22, footprint=FP_R, fields=F("SDA pull-up"))
    rscl = sh.place(R, "R304", "4.7k", 40.64, 236.22, footprint=FP_R, fields=F("SCL pull-up"))
    sh.w(rscl["1"], (40.64, yt), (55.88, yt), rsda["1"])
    sh.pwr("+3V3", (40.64, yt))
    sh.w(rsda["2"], (55.88, ys), (71.12, ys), (88.9, ys))
    sh.w(rscl["2"], (40.64, yc), (76.2, yc), (88.9, yc))
    sh.place(TP, "TP312", "SDA", 71.12, ys, footprint=FP_TP, fields=F("Test point SDA"))
    sh.place(TP, "TP313", "SCL", 76.2, yc, footprint=FP_TP, fields=F("Test point SCL"))
    sh.nl("SDA", (88.9, ys))
    sh.nl("SCL", (88.9, yc))

    # ---- Harness landings --------------------------------------------------------------------------
    note("HARNESS LANDINGS (D14, soldered)", "DISP to the ESP32 display module, NIX_LV to the Nixie controller", 132.08, 215.9)
    j1 = sh.place("Connector_Generic:Conn_01x05", "J301", "DISP", 157.48, ys, footprint=FP_WIRE5,
                  fields=F("Harness DISP: 5V (P1 5V), GND (P1 GND), GND (3V3-plug GND), SCL (IO18), SDA (IO27)"))
    for pin, net in (("1", "5V_DISP"), ("4", "SCL"), ("5", "SDA")):
        sh.stub(j1[pin], net, -5.08, 0)
    xg = j1["2"][0] - 7.62                          # both GND wires join, one GND symbol clear of the labels
    sh.w(j1["2"], (xg, j1["2"][1]), (xg, j1["3"][1]))
    sh.w(j1["3"], (xg, j1["3"][1]))
    sh.stub((xg, j1["3"][1]), "GND", -5.08, 0)
    j2 = sh.place("Connector_Generic:Conn_01x06", "J302", "NIX_LV", 223.52, ys, footprint=FP_WIRE6,
                  fields=F("Harness NIX_LV to the Nixie controller board"))
    for pin, net in (("1", "5V_NIX"), ("2", "GND"), ("3", "SDA"), ("4", "SCL"), ("5", "GND")):
        sh.stub(j2[pin], net, -12.7 if net == "GND" else -5.08, 0)
    lk = sh.place(R, "LK15", "0", 190.5, j2["6"][1], angle=90, footprint=FP_R,
                  fields=F("GP12 to the NIX_LV spare wire (0 ohm, fit when used)"))
    sh.w(lk["2"], (196.85, j2["6"][1]), j2["6"])
    sh.nl("NIX_SPARE", (196.85, j2["6"][1]))
    sh.w(lk["1"], (180.34, j2["6"][1]))
    sh.nl("GP12", (180.34, j2["6"][1]), 180)
    sh.finish()
    return sh


def build_root(lib: SymbolLib) -> Sheet:
    sh = Sheet("root", f"{PROJECT}.kicad_sch", ROOT_UUID, "A4", lib, "/", title="Dekatron controller / PSU")
    sh.sheet("power", "power.kicad_sch", POWER_UUID, 40, 40, 60, 30, page="2")
    sh.sheet("tube", "tube.kicad_sch", TUBE_UUID, 120, 40, 60, 30, page="3")
    sh.sheet("mcu", "mcu.kicad_sch", MCU_UUID, 200, 40, 60, 30, page="4")
    sh.text("Sheets: power, tube, mcu. Inter-sheet nets are global labels.", 40, 100, 2)
    return sh


# --------------------------------------------------------------------------------------
# Project file, tables, BOM
# --------------------------------------------------------------------------------------


def project_json() -> str:
    def nc(name, clearance):
        return {"name": name, "clearance": clearance, "track_width": 0.3, "via_diameter": 0.8, "via_drill": 0.4,
                "priority": 0, "bus_width": 12, "line_style": 0, "wire_width": 6}
    pro = {
        "board": {"design_settings": {"defaults": {}, "rule_severities": {}}, "layer_presets": [], "viewports": []},
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3},
        # Net classes from docs/hardware.md D13; the clearances between classes are pair rules in
        # dekatron.kicad_dru (written by tools/gen_pcb.py).
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
                 "priority": 2147483647, "bus_width": 12, "line_style": 0, "wire_width": 6},
                # base clearance only: the pairwise class rules live in dekatron.kicad_dru (D13)
                nc("HV", 0.2), nc("VB", 0.2), nc("HVSTR", 0.2), nc("BIAS", 0.2)],
            "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
            "netclass_patterns": [
                {"netclass": "HV", "pattern": "HV"},
                {"netclass": "HV", "pattern": "*HV_STACK"},
                {"netclass": "HV", "pattern": "*TRP_P1"},
                {"netclass": "HV", "pattern": "*TRP_N2"},
                {"netclass": "HV", "pattern": "*TRP_P2"},
                {"netclass": "VB", "pattern": "*V_B"},
                {"netclass": "VB", "pattern": "*V_BT"},
                {"netclass": "VB", "pattern": "V_B_BIAS"},
                {"netclass": "VB", "pattern": "*/SW"},
                {"netclass": "VB", "pattern": "*TRP_PUMP"},
                {"netclass": "HV", "pattern": "*ANODE"},
                {"netclass": "HVSTR", "pattern": "*STR_*"},
                {"netclass": "BIAS", "pattern": "*GPLUS"},
                {"netclass": "BIAS", "pattern": "*RTN"},
                {"netclass": "BIAS", "pattern": "*TUBE_*"},
                {"netclass": "BIAS", "pattern": "*NDX_C"},
            ]},
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[ROOT_UUID, "Root"], [POWER_UUID, "power"], [TUBE_UUID, "tube"], [MCU_UUID, "mcu"]],
        "text_variables": {},
    }
    return json.dumps(pro, indent=2) + "\n"


SYM_TABLE = f'''(sym_lib_table
  (version 7)
  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{PROJECT}.kicad_sym")(options "")(descr "Project-local symbols"))
)
'''

FP_TABLE = f'''(fp_lib_table
  (version 7)
  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{PROJECT}.pretty")(options "")(descr "Project-local footprints"))
)
'''


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8", newline="\n") as f:
        f.write(text)
    print("wrote", os.path.relpath(path, ROOT))


def write_once(path, text):
    if os.path.exists(path):
        print("kept  ", os.path.relpath(path, ROOT), "(exists; KiCad owns it)")
        return
    write(path, text)


def write_bom(path, sheets):
    rows = []
    for sh in sheets:
        for p in sh.placed:
            f = p["fields"]
            rows.append([p["ref"], p["value"], f.get("Function", ""), f.get("Manufacturer", ""), f.get("MPN", ""),
                         f.get("Rating", ""), p["footprint"], "DNP" if p["dnp"] else ""])
    rows.sort(key=lambda r: (re.sub(r"\d+", "", r[0]), int(re.sub(r"\D", "", r[0]) or 0)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Reference", "Value", "Function", "Manufacturer", "MPN", "Rating", "Footprint", "Fit"])
        w.writerows(rows)
    print("wrote", os.path.relpath(path, ROOT), f"({len(rows)} parts)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-share", default=r"C:\Program Files\KiCad\10.0\share\kicad")
    args = ap.parse_args()

    lib = SymbolLib(args.kicad_share)
    proj = parse(project_symbol_lib_text())
    for s in find_all(proj, "symbol"):
        name = unq(s[1])
        s[1] = q(f"{PROJECT}:{name}")
        lib.defs[f"{PROJECT}:{name}"] = s

    power = build_power(lib)
    tube = build_tube(lib)
    mcu = build_mcu(lib)
    root = build_root(lib)

    write_once(os.path.join(HW, f"{PROJECT}.kicad_pro"), project_json())
    write(os.path.join(HW, f"{PROJECT}.kicad_sch"), root.render(is_root=True))
    write(os.path.join(HW, "power.kicad_sch"), power.render())
    write(os.path.join(HW, "tube.kicad_sch"), tube.render())
    write(os.path.join(HW, "mcu.kicad_sch"), mcu.render())
    write(os.path.join(HW, "fp-lib-table"), FP_TABLE)
    write(os.path.join(HW, "lib", f"{PROJECT}.pretty", "RP2040-Zero_Castellated.kicad_mod"), rp2040_zero_footprint_text())
    write(os.path.join(HW, "sym-lib-table"), SYM_TABLE)
    write(os.path.join(HW, "lib", f"{PROJECT}.kicad_sym"), project_symbol_lib_text())
    write_bom(os.path.join(HW, "bom.csv"), [power, tube, mcu])


if __name__ == "__main__":
    main()
