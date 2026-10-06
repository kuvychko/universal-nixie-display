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


def project_symbol_lib_text() -> str:
    return ('(kicad_symbol_lib (version 20251024) (generator "dekatron-gen") (generator_version "10.0")\n'
            + tlv3011_symbol_text() + "\n)\n")


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
               fields=None, dnp=False, hide_ref=False, horizontal=False, multipin=False):
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
        if horizontal:
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
             fields=None, dnp=False, stub=GRID):
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
                    fields=fields, dnp=dnp, horizontal=horizontal, multipin=len(pins) == 3)
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
FP_WIRE2 = "Connector_Wire:SolderWire-0.5sqmm_1x02_P4.8mm_D0.9mm_OD2.3mm_Relief"
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
    H = 90    # horizontal two-pin parts: pin 1 left

    def r(ref, val, x, y, a, b, fn, angle=0, dnp=False, fp=FP_R, rating=""):
        sh.part(R, ref, val, x, y, {"1": a, "2": b}, angle=angle, footprint=fp, fields=F(fn, rating=rating), dnp=dnp)

    def c(ref, val, x, y, a, b, fn, fp=FP_C, rating="", angle=0, mpn="", mfr=""):
        sh.part(C, ref, val, x, y, {"1": a, "2": b}, angle=angle, footprint=fp, fields=F(fn, mpn, mfr, rating))

    def tp(ref, net, x, y):
        sh.part(TP, ref, net, x, y, {"1": net}, footprint=FP_TP, fields=F(f"Test point {net}"))

    def link(ref, x, y, a, b, fn, hv=False):
        sh.part(R, ref, "LINK" if hv else "0", x, y, {"1": a, "2": b}, angle=H,
                footprint=FP_HVLINK if hv else FP_R,
                fields=F(fn + (" (wire link, desolder to open)" if hv else " (0 ohm, remove to open)")))

    def note(s, x, y):
        sh.text(s, x, y, 1.8)

    # ---- Row 1: 12 V input protection -----------------------------------------------------
    y = 45
    note("12 V INPUT (D4): fuse, reverse-polarity P-MOSFET, TVS, bulk; Nixie module branch", 20, 22)
    sh.part("Connector_Generic:Conn_01x02", "J101", "PWR_IN", 30, y, {"1": "+12V_RAW", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Harness landing PWR_IN: +12V_IN from panel switch / barrel jack; GND"))
    sh.part("Device:Fuse", "F101", "2A Slo-Blo", 55, y, {"1": "+12V_RAW", "2": "+12V_FUSED"}, angle=H,
            footprint=FP_F1206, fields=F("Input fuse", "0468002.NRHF", "Littelfuse", "2 A, 63 V, I2t 0.506 A2s"))
    sh.part("Transistor_FET:Q_PMOS_GDS", "Q101", "AOD4185", 85, y, {"1": "Q101_G", "2": "+12V_FUSED", "3": "VIN_PROT"},
            angle=90, footprint=FP_DPAK, fields=F("Reverse-polarity protection", "AOD4185", "Alpha & Omega", "-40 V, 115 A pulsed"))
    r("R101", "10k", 110, y + 10, "Q101_G", "GND", "Reverse-polarity MOSFET gate pull-down")
    sh.part(DZ, "D101", "BZT52C10", 130, y, {"1": "VIN_PROT", "2": "Q101_G"}, angle=270, footprint=FP_SOD123,
            fields=F("Q101 gate-source clamp, -10 V", "BZT52C10"))
    sh.part(DZ, "D102", "SMBJ15A", 150, y, {"1": "VIN_PROT", "2": "GND"}, angle=270, footprint=FP_SMB,
            fields=F("Input TVS, unidirectional", "SMBJ15A", "Littelfuse", "15 V standoff, 24.4 V clamp"))
    sh.part(CP, "C101", "100uF 35V", 170, y, {"1": "VIN_PROT", "2": "GND"}, footprint=FP_ELEC,
            fields=F("Input bulk, damps hot-plug ringing", "EEE-FK1V101P", "Panasonic", "35 V, 160 mohm ESR"))
    c("C102", "0.1uF", 185, y, "VIN_PROT", "GND", "Input HF bypass", rating="50 V X7R")
    tp("TP101", "VIN_PROT", 200, y)
    sh.part("Device:Polyfuse", "F102", "0.75A", 238, y, {"1": "VIN_PROT", "2": "+12V_NIX"}, angle=H, footprint=FP_F1812,
            fields=F("Nixie HV module branch fuse", "1812L075/33DR", "Littelfuse", "0.75 A hold, 33 V"))
    sh.part("Connector_Generic:Conn_01x02", "J102", "NIX_12V", 282, y, {"1": "+12V_NIX", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Harness landing NIX_12V to the purchased Nixie HV module"))
    tp("TP102", "GND", 300, y)
    sh.flag("VIN_PROT", 200, y + 25)
    sh.flag("GND", 215, y + 25)

    # ---- Row 1 right: 5 V buck --------------------------------------------------------------
    x0 = 320
    note("5 V BUCK: TPS54202, TI reference design (SLVSD26C Fig. 7-1); 100k/13.7k -> 4.95 V", x0 - 20, 22)
    c("C103", "10uF 35V", x0 - 10, y, "VIN_PROT", "GND", "Buck input", fp=FP_C1210, rating="35 V X7R")
    c("C104", "0.1uF", x0, y, "VIN_PROT", "GND", "Buck input HF", rating="50 V X7R")
    r("R102", "511k", x0 + 10, y - 2, "VIN_PROT", "BUCK_EN", "Buck EN UVLO, upper")
    r("R103", "105k", x0 + 10, y + 18, "BUCK_EN", "GND", "Buck EN UVLO, lower")
    sh.part("Regulator_Switching:TPS54202DDC", "U101", "TPS54202", x0 + 40, y,
            {"1": "GND", "2": "BUCK_SW", "3": "VIN_PROT", "4": "BUCK_FB", "5": "BUCK_EN", "6": "BUCK_BOOT"},
            fields=F("5 V buck regulator", "TPS54202DDCR", "Texas Instruments", "4.5-28 V, 2 A"))
    c("C105", "0.1uF", x0 + 70, y - 12, "BUCK_BOOT", "BUCK_SW", "Buck bootstrap", angle=H, rating="25 V X7R")
    sh.part(L, "L101", L_BUCK["value"], x0 + 80, y + 8, {"1": "BUCK_SW", "2": "5V_BUCK"}, angle=H, footprint=L_BUCK["fp"],
            fields=F("Buck inductor", L_BUCK["mpn"], L_BUCK["mfr"], L_BUCK["note"]))
    c("C106", "22uF 25V", x0 + 100, y + 18, "5V_BUCK", "GND", "Buck output", fp=FP_C1210, rating="25 V X7R")
    c("C107", "22uF 25V", x0 + 110, y + 18, "5V_BUCK", "GND", "Buck output", fp=FP_C1210, rating="25 V X7R")
    r("R104", "49.9", x0 + 120, y - 2, "5V_BUCK", "BUCK_FBT", "Buck loop-injection resistor")
    r("R105", "100k", x0 + 135, y - 2, "BUCK_FBT", "BUCK_FB", "Buck feedback, upper")
    c("C108", "75pF", x0 + 145, y - 2, "BUCK_FBT", "BUCK_FB", "Buck feed-forward", rating="50 V C0G")
    r("R106", "13.7k", x0 + 135, y + 20, "BUCK_FB", "GND", "Buck feedback, lower (4.95 V)", rating="1 %")
    link("LK2", x0 + 160, y + 8, "5V_BUCK", "+5V", "D11 link L2: buck output to board 5 V")
    tp("TP103", "+5V", x0 + 175, y + 8)
    sh.flag("+5V", x0 + 185, y + 25)

    # ---- Row 2: ideal diodes, gate-drive LDO --------------------------------------------------
    y = 120
    note("IDEAL DIODES (D6): one LM66100 per external 5 V feed; CE grounded = always on", 20, y - 30)
    for i, (ref, out, cref) in enumerate((("U102", "5V_DISP", "C109"), ("U103", "5V_MCU", "C110"), ("U104", "5V_NIX", "C111"))):
        xx = 40 + i * 50
        sh.part("Power_Management:LM66100DCK", ref, "LM66100", xx, y,
                {"1": "+5V", "2": "GND", "3": "GND", "5": "NC", "6": out},
                fields=F(f"Ideal diode, {out} feed", "LM66100DCKR", "Texas Instruments", "1.5 A, reverse blocking"))
        c(cref, "0.1uF", xx - 15, y + 15, "+5V", "GND", f"{ref} input bypass", rating="50 V X7R")

    x0 = 230
    note("10 V GATE DRIVE: LP2951 feeds LM5156 BIAS = VCC (2.97-16 V mode); 143k/20.0k -> 10.07 V", x0 - 20, y - 30)
    link("LK1", x0 - 10, y - 12, "VIN_PROT", "12V_HV", "D11 link L1: 12 V to the HV section")
    c("C112", "1uF 35V", x0 + 2, y + 10, "12V_HV", "GND", "LDO input", rating="35 V X7R")
    sh.part("Regulator_Linear:LP2951-3.3_SOIC", "U105", "LP2951 (adj. 10 V)", x0 + 30, y,
            {"1": "VDRV", "2": "NC", "3": "GND", "4": "GND", "5": "NC", "6": "NC", "7": "LDO_FB", "8": "12V_HV"},
            fields=F("Gate-drive LDO, adjustable, 10.07 V", "LP2951ACDR2G", "onsemi", "30 V in, 100 mA"))
    r("R107", "143k", x0 + 60, y - 4, "VDRV", "LDO_FB", "LDO feedback, upper", rating="1 %")
    r("R108", "20.0k", x0 + 60, y + 16, "LDO_FB", "GND", "LDO feedback, lower", rating="1 %")
    c("C113", "2.2uF", x0 + 75, y + 6, "VDRV", "GND", "LDO output", rating="25 V X7R")
    tp("TP104", "VDRV", x0 + 90, y + 6)
    sh.flag("12V_HV", x0 - 10, y + 25)

    # ---- Row 3: HV boost (LM5156) ----------------------------------------------------------
    y = 205
    note("HV BOOST (D2, Phase 1B): LM5156H, ~150 kHz DCM, feedback from HV, CS filter, 10 V drive; kit 100 uH inductor", 20, y - 40)
    c("C114", "1uF", 25, y, "VDRV", "GND", "LM5156 BIAS/VCC bypass", rating="25 V X7R")
    c("C115", "0.1uF", 35, y, "VDRV", "GND", "LM5156 BIAS/VCC HF", rating="50 V X7R")
    r("R109", "10k", 55, y - 18, "HV_EN", "HV_EN_PIN", "HV_EN series resistor", angle=H)
    r("R110", "100k", 55, y + 8, "HV_EN_PIN", "GND", "EN/UVLO pull-down: HV off by default (D7)")
    sh.part("Connector_Generic:Conn_01x02", "JP101", "HV_INHIBIT", 70, y + 25, {"1": "HV_EN_PIN", "2": "GND"},
            footprint=FP_HDR2, fields=F("HV inhibit jumper (D11): shunt fitted holds EN/UVLO low"))
    r("R111", R_T, 70, y - 2, "LM5156_RT", "GND", "Switching frequency (147k = ~150 kHz)")
    sh.part("Regulator_Switching:LM5156HPWP", "U106", "LM5156H", 120, y,
            {"1": "VDRV", "3": "VDRV", "4": "LM5156_GATE", "5": "GND", "6": "GND", "15": "GND",
             "7": "LM5156_CS", "8": "LM5156_COMP", "9": "VDRV", "10": "LM5156_FB", "11": "LM5156_SS",
             "12": "LM5156_RT", "13": "PGOOD", "14": "HV_EN_PIN"},
            fields=F("HV boost controller", "LM5156HPWPR", "Texas Instruments", "HTSSOP-14 exposed pad"))
    sh.part(R, "R112", "0", 95, y + 16, {"1": "HV_EN_PIN", "2": "OVP_TRIP"}, footprint=FP_R,
            fields=F("EN/UVLO node read back by the RP2040 (OVP_TRIP, GP8)"))
    c("C116", "47nF", 160, y + 20, "LM5156_SS", "GND", "Soft-start", rating="25 V X7R")
    r("R113", "10k", 170, y + 4, "LM5156_COMP", "COMP_RC", "Compensation R")
    c("C117", "10nF", 170, y + 30, "COMP_RC", "GND", "Compensation C", rating="25 V X7R")
    c("C118", "100pF", 180, y + 12, "LM5156_COMP", "GND", "Compensation HF", rating="50 V C0G")
    r("R114", "10k", 190, y - 12, "+3V3", "PGOOD", "PGOOD pull-up")
    r("R115", "2.2", 200, y - 24, "LM5156_GATE", "Q102_G", "Gate resistor", angle=H)
    r("R116", "100k", 218, y - 10, "Q102_G", "GND", "Gate pull-down (unpowered state)")
    sh.part("Transistor_FET:Q_NMOS_GDS", "Q102", "AOD5N40", 242, y - 24, {"1": "Q102_G", "2": "SW", "3": "Q102_S"},
            footprint=FP_DPAK, fields=F("HV boost switch", "AOD5N40", "Alpha & Omega", "400 V, 1.6 ohm at 10 V"))
    r("R117", R_SENSE, 258, y - 4, "Q102_S", "GND", "Current sense (0.42-0.49 A limit)", rating="1 %, >= 0.25 W")
    r("R118", "100", 280, y - 4, "Q102_S", "LM5156_CS", "CS filter R", angle=H)
    c("C119", "470pF", 300, y + 6, "LM5156_CS", "GND", "CS filter C (pump surge)", rating="50 V C0G")
    c("C120", "10uF 35V", 300, y - 34, "12V_HV", "GND", "Boost input", fp=FP_C1210, rating="35 V X7R")
    c("C121", "0.1uF", 315, y - 34, "12V_HV", "GND", "Boost input HF", rating="50 V X7R")
    sh.part(L, "L102", L_HV["value"], 340, y - 34, {"1": "12V_HV", "2": "SW"}, angle=H, footprint=L_HV["fp"],
            fields=F("HV boost inductor", L_HV["mpn"], L_HV["mfr"], L_HV["note"]))
    sh.part(D, "D103", "ES1J", 372, y - 34, {"K": "V_B", "A": "SW"}, angle=180, footprint=FP_SMA,
            fields=F("Boost diode", "ES1J", "onsemi", "600 V, 1 A, 35 ns"))
    sh.part(C, "C122", "0.47uF 400V", 395, y - 20, {"1": "V_B", "2": "GND"}, footprint=FP_FILM,
            fields=F("Tripler stack C1 (V_b)", rating="400 V PET film"))
    r("R119", "1.2M", 412, y - 24, "V_B", "STR_VBB", "V_b bleeder 1/2")
    r("R120", "1.2M", 412, y - 4, "STR_VBB", "GND", "V_b bleeder 2/2")
    tp("TP105", "SW", 340, y - 8)
    tp("TP106", "V_B", 428, y - 20)
    tp("TP107", "GND", 352, y - 8)
    link("LK5", 450, y - 24, "V_B", "V_B_BIAS", "D11 link L5: V_b to the G+/RTN regulators", hv=True)


    # ---- Row 4: tripler, bleeder, feedback ------------------------------------------------------
    y = 290
    note("TRIPLER (series-stack CW): every capacitor and diode sees <= V_b; 47 ohm pump surge resistor", 20, y - 40)
    link("LK3", 30, y - 20, "V_B", "V_BT", "D11 link L3: V_b to the tripler DC column", hv=True)
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
    note("HV MONITOR (HV_SENSE, GP28) and INDEPENDENT OVP (TLV3011, trips at ~548 V, pulls EN/UVLO low)", 20, y - 40)
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
    # Dummy loads for bring-up step 2 (DNP): V_b 4 x 8.2k (32.8k, 4.6 mA at 150 V); HV 6 x 150k (0.5 mA at 450 V)
    for i in range(4):
        a = "V_B" if i == 0 else f"STR_DV{i}"
        b = "GND" if i == 3 else f"STR_DV{i + 1}"
        r(f"R{141 + i}", "8.2k", 270 + i * 14, y - 10, a, b, f"V_b dummy load {i + 1}/4 (bring-up only)", dnp=True)
    for i in range(6):
        a = "HV_STACK" if i == 0 else f"STR_DH{i}"
        b = "GND" if i == 5 else f"STR_DH{i + 1}"
        r(f"R{145 + i}", "150k", 330 + i * 14, y - 10, a, b, f"HV dummy load {i + 1}/6 (bring-up only)", dnp=True)
    return sh


# --------------------------------------------------------------------------------------
# tube.kicad_sch
# --------------------------------------------------------------------------------------

TUBE_GLOBALS = {"HV", "V_B_BIAS", "GUIDE1", "GUIDE2", "NDX", "RTN_SENSE"}
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"            # MMBTA42 / MMBTA92: 1 B, 2 E, 3 C (Nexperia)
FP_WIRE1 = "Connector_Wire:SolderWire-0.5sqmm_1x01_D0.9mm_OD2.3mm_Relief"
FP_WIRE6 = "Connector_Wire:SolderWire-0.5sqmm_1x06_P4.8mm_D0.9mm_OD2.3mm_Relief"


def build_tube(lib: SymbolLib) -> Sheet:
    sh = Sheet("tube", "tube.kicad_sch", U("file:tube"), "A3", lib, f"/{ROOT_UUID}/{TUBE_UUID}",
               global_nets=TUBE_GLOBALS, title="Tube: G+ / RTN bias, guide drivers, index sense, anode, harness")
    R, C, DZ, TP = "Device:R", "Device:C", "Device:D_Zener", "Connector:TestPoint"
    H = 90

    def r(ref, val, x, y, a, b, fn, angle=0, rating=""):
        sh.part(R, ref, val, x, y, {"1": a, "2": b}, angle=angle, footprint=FP_R, fields=F(fn, rating=rating))

    def c(ref, val, x, y, a, b, fn, rating=""):
        sh.part(C, ref, val, x, y, {"1": a, "2": b}, footprint=FP_C, fields=F(fn, rating=rating))

    def tp(ref, net, x, y):
        sh.part(TP, ref, net, x, y, {"1": net}, footprint=FP_TP, fields=F(f"Test point {net}"))

    def note(t, x, y):
        sh.text(t, x, y, 1.8)

    # ---- Row 1: G+ / RTN zener regulator (D1, D8) ------------------------------------------
    y = 45
    note("BIAS (D1, D8): RTN = 51 V zener (sinks tube current), G+ = RTN + 39 V = 90 V; feed 56k from V_b", 20, 22)
    r("R201", "56k", 30, y, "V_B_BIAS", "GPLUS", "G+ / RTN feed (1.2 mA at V_b 157 V)")
    sh.part(DZ, "D201", "39V", 55, y, {"1": "GPLUS", "2": "RTN"}, angle=270, footprint=FP_SOD123,
            fields=F("G+ above RTN: guide bias 39 V", "MMSZ5259B", "onsemi", "39 V, 500 mW"))
    sh.part(DZ, "D202", "51V", 80, y, {"1": "RTN", "2": "GND"}, angle=270, footprint=FP_SOD123,
            fields=F("RTN shunt regulator: sinks tube current", "MMSZ5262B", "onsemi", "51 V, 500 mW"))
    c("C201", "0.1uF 100V", 105, y, "GPLUS", "RTN", "G+ to RTN bypass", rating="100 V X7R")
    c("C202", "1uF 100V", 125, y, "RTN", "GND", "RTN bypass: absorbs tube and guide current steps", rating="100 V X7R")
    r("R202", "100k", 150, y - 16, "RTN", "STR_RS1", "RTN_SENSE divider 1/2")
    r("R203", "100k", 150, y + 16, "STR_RS1", "RTN_SENSE", "RTN_SENSE divider 2/2")
    r("R204", "10k", 165, y + 16, "RTN_SENSE", "GND", "RTN_SENSE divider, lower (2.43 V at 51 V)", rating="1 %")
    tp("TP201", "GPLUS", 190, y)
    tp("TP202", "RTN", 205, y)
    tp("TP206", "GND", 220, y)

    # ---- Row 2: guide drivers (D8) -----------------------------------------------------------
    y = 115
    note("GUIDE DRIVERS (D8): MMBTA42 pulls the guide from G+ to ~0 V; 47k base pull-down keeps guides at rest in reset", 20, y - 30)
    for i, (n, gx) in enumerate(((1, 30), (2, 130))):
        g = f"TUBE_G{n}"
        b = f"G{n}_B"
        r(f"R{205 + 3 * i}", "470k", gx, y - 12, "GPLUS", g, f"Guide {n} pull-up to G+ (<= 90 V)")
        sh.part("Transistor_BJT:Q_NPN_BEC", f"Q{201 + i}", "MMBTA42", gx + 20, y, {"1": b, "2": "GND", "3": g},
                footprint=FP_SOT23, fields=F(f"Guide {n} driver", "MMBTA42", "Nexperia", "300 V NPN"))
        r(f"R{206 + 3 * i}", "10k", gx + 5, y + 20, f"GUIDE{n}", b, f"Guide {n} base resistor (0.24 mA from 3.3 V)", angle=H)
        r(f"R{207 + 3 * i}", "47k", gx + 35, y + 22, b, "GND", f"Guide {n} base pull-down (reset = at rest)")
        tp(f"TP{203 + i}", g, gx + 50, y)

    # ---- Row 3: index sense (D9) --------------------------------------------------------------
    y = 185
    note("INDEX SENSE (D9): MMBTA92 level shifter from K1 (pin 13); 220k / 13k -> 2.73-3.01 V; clamp at the RP2040", 20, y - 30)
    sh.part("Transistor_BJT:Q_PNP_BEC", "Q203", "MMBTA92", 55, y, {"1": "RTN", "2": "TUBE_K1", "3": "NDX_C"},
            footprint=FP_SOT23, fields=F("Index level shifter", "MMBTA92", "Nexperia", "300 V PNP"))
    r("R211", "220k", 30, y - 5, "TUBE_K1", "RTN", "Holds K1 at RTN when not lit")
    r("R212", "110k", 80, y - 16, "NDX_C", "STR_NX1", "Index divider top 1/2 (167 V fault: 84 V per part)")
    r("R213", "110k", 80, y + 16, "STR_NX1", "NDX", "Index divider top 2/2")
    r("R214", "13k", 100, y + 16, "NDX", "GND", "Index divider, lower", rating="1 %")
    c("C204", "1nF", 115, y + 16, "NDX", "GND", "Index filter (tau 12 us)", rating="50 V C0G")
    tp("TP205", "NDX", 135, y + 16)

    # ---- Row 4: anode string, cathode links, harness (D1, D11, D14) -----------------------------
    y = 255
    note("ANODE STRING 3 x 220k (D1; 3 x 270k for 500 V), CATHODE LINKS LK6-LK14 (D11), TUBE HARNESS (D14, soldered)", 20, y - 35)
    for i, (ref, a, b) in enumerate((("R215", "HV", "STR_A1"), ("R216", "STR_A1", "STR_A2"), ("R217", "STR_A2", "ANODE"))):
        r(ref, "220k", 30 + i * 18, y - 10, a, b, f"Anode resistor {i + 1}/3 (<= 100 V per part)")
    sh.part("Connector_Generic:Conn_01x01", "J201", "TUBE_ANODE", 95, y - 10, {"1": "ANODE"}, footprint=FP_WIRE1,
            fields=F("Tube harness: anode (pin 8), 600 V wire, kept >= 3 mm from other pads"))
    cathodes = ["TUBE_K0"] + [f"TUBE_K{k}" for k in range(2, 10)]
    for i, k in enumerate(cathodes):
        sh.part(R, f"LK{6 + i}", "0", 130 + i * 15, y - 10, {"1": k, "2": "RTN"}, footprint=FP_R,
                fields=F(f"D11 cathode link: {k[5:]} to RTN (0 ohm, remove to isolate)"))
    sh.part("Connector_Generic:Conn_01x06", "J202", "TUBE_A", 290, y - 30,
            {"1": "TUBE_G1", "2": "TUBE_G2", "3": "TUBE_K1", "4": "TUBE_K0", "5": "TUBE_K2", "6": "TUBE_K3"},
            footprint=FP_WIRE6, fields=F("Tube harness: G1 (5), G2 (10), K1 index (13), K0 (1), K2 (12), K3 (11)"))
    sh.part("Connector_Generic:Conn_01x06", "J203", "TUBE_B", 290, y + 5,
            {"1": "TUBE_K4", "2": "TUBE_K5", "3": "TUBE_K6", "4": "TUBE_K7", "5": "TUBE_K8", "6": "TUBE_K9"},
            footprint=FP_WIRE6, fields=F("Tube harness: K4 (9), K5 (7), K6 (6), K7 (4), K8 (3), K9 (2)"))
    return sh


def build_root(lib: SymbolLib) -> Sheet:
    sh = Sheet("root", f"{PROJECT}.kicad_sch", ROOT_UUID, "A4", lib, "/", title="Dekatron controller / PSU")
    sh.sheet("power", "power.kicad_sch", POWER_UUID, 40, 40, 60, 30, page="2")
    sh.sheet("tube", "tube.kicad_sch", TUBE_UUID, 120, 40, 60, 30, page="3")
    sh.text("Sheets: power, tube. The mcu sheet follows in Phase 1B.", 40, 100, 2)
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
        # Net classes from docs/hardware.md D13 (clearance to any other class); pair rules go in
        # a .kicad_dru with the PCB.
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
                 "priority": 2147483647, "bus_width": 12, "line_style": 0, "wire_width": 6},
                nc("HV", 3.0), nc("VB", 1.5), nc("HVSTR", 1.5), nc("BIAS", 0.8)],
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
                {"netclass": "VB", "pattern": "*SW"},
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
        "sheets": [[ROOT_UUID, "Root"], [POWER_UUID, "power"], [TUBE_UUID, "tube"]],
        "text_variables": {},
    }
    return json.dumps(pro, indent=2) + "\n"


SYM_TABLE = f'''(sym_lib_table
  (version 7)
  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{PROJECT}.kicad_sym")(options "")(descr "Project-local symbols"))
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
    root = build_root(lib)

    write_once(os.path.join(HW, f"{PROJECT}.kicad_pro"), project_json())
    write(os.path.join(HW, f"{PROJECT}.kicad_sch"), root.render(is_root=True))
    write(os.path.join(HW, "power.kicad_sch"), power.render())
    write(os.path.join(HW, "tube.kicad_sch"), tube.render())
    write(os.path.join(HW, "sym-lib-table"), SYM_TABLE)
    write(os.path.join(HW, "lib", f"{PROJECT}.kicad_sym"), project_symbol_lib_text())
    write_bom(os.path.join(HW, "bom.csv"), [power, tube])


if __name__ == "__main__":
    main()
