#!/usr/bin/env python3
"""
Generator for the Nixie controller/mount KiCad project (Phase 1B draft).

Writes into hardware/nixie/:
  nixie.kicad_pro             project file (written once; KiCad owns it afterwards)
  nixie.kicad_sch             root sheet
  power.kicad_sch             harness landings, Nixie HV module 12 V switch, HV monitor
  logic.kicad_sch             RP2040-Zero, CD40109B level shifter, 12 V logic rail, encoder / RTC / ES100
  tubes.kicad_sch             3 x HV5622 (two tubes each), 6 x (IN-14, anode resistor, two DP resistors)
  sym-lib-table / fp-lib-table
  lib/nixie.kicad_sym         project symbols (HV5622, IN-14, RP2040-Zero)
  lib/nixie.pretty/RP2040-Zero_Castellated.kicad_mod   (IN-14.kicad_mod is maintained by hand)
  bom.csv

Reuses the core of tools/gen_schematics.py (parser, symbol loading, Sheet). Drawing style (2026-11-10,
for readability): small analog circuits are drawn with real wires (Sheet.place / w, junctions by
Sheet.finish); module and driver pins end in short stubs with horizontal net labels; every named
net keeps its label, so the netlist (and the routed board) is unchanged by layout edits. Values not yet sourced are written as OPEN
("_open_"); they come from the Nixie HV module measurements (docs/hardware.md, "Nixie board
electrical design").

Usage:  python tools/gen_nixie_schematics.py [--kicad-share "C:/Program Files/KiCad/10.0/share/kicad"]
"""
from __future__ import annotations

import argparse
import json
import os
import textwrap
import uuid

import gen_schematics as gs
from gen_schematics import F, find, find_all, parse, q, unq

ROOT = gs.ROOT
HW = os.path.join(ROOT, "hardware", "nixie")
PROJECT = "nixie"

# The shared Sheet code reads these module globals: point them at this project.
gs.PROJECT = PROJECT
gs.NS = uuid.UUID("7c41d2a8-5e9b-4c3f-8a6d-1f2e3b4c5d6e")
# Design-time part numbers (2026-11-07), applied to every symbol like the dekatron board's frozen
# BOM: the exact MPNs already ordered for the dekatron board (hardware/dekatron/Cart_Oct08_0432PM.xls)
# wherever the Nixie part has the same value, rating and footprint, plus the Nixie-only parts.
# Not listed: kit resistors (generic 1206, by value), _open_ values, part numbers still to be picked
# at ordering, wire pads and test pads. Replace with the Nixie order once it is placed.
NIXIE_PARTS = [
    ("Yageo", "CC1206JPX7R9BB104", "C103 C104 C201 C202 C203 C302 C303 C304"),  # 0.1 uF 50 V X7R 1206
    ("KYOCERA AVX", "F911C106MAAAJ6", "C101 C301"),                         # 10 uF 16 V tantalum, case A
    ("KYOCERA AVX", "12063C103JAT2A", "C308 C309 C310"),                    # 0.01 uF 1206 (dekatron C117)
    ("Taiwan Semiconductor", "BAT54S RFG", "D101"),
    ("Infineon", "IPD50P04P4L11ATMA2", "Q101"),
    ("Yageo", "HHV-50FT-52-1M", "R105"),
    ("Panasonic", "ERJ-8ENF1202V", "R106"),                                 # 12k 1 % 1206
    ("Vishay", "MRS25000C1202FRP00", "R210 R220 R230 R240 R250 R260"),     # 12k MRS25 anode (Nixie order)
    ("Microchip", "HV5622PG-G", "U201 U202 U203"),
    ("Waveshare", "RP2040-Zero", "U301"),
    ("Texas Instruments", "CD40109BNSRE4", "U302"),
]
gs.ORDERED = {ref: (mfr, mpn) for mfr, mpn, refs in NIXIE_PARTS for ref in refs.split()}
gs.ROOT_UUID = ROOT_UUID = gs.U("sheet:root")
U = gs.U
POWER_UUID = U("sheet:power")
LOGIC_UUID = U("sheet:logic")
TUBES_UUID = U("sheet:tubes")

OPEN = "_open_"
TUBES = 6

FP_R = gs.FP_R
FP_C = gs.FP_C
FP_TANT_A = gs.FP_TANT_A
FP_SOT23 = gs.FP_SOT23
FP_TP = gs.FP_TP
FP_AX0207 = gs.FP_AX0207
FP_AX0411 = gs.FP_AX0411
FP_WIRE1 = gs.FP_WIRE1
FP_WIRE2 = gs.FP_WIRE2
FP_WIRE4 = gs.FP_WIRE4
FP_WIRE6 = gs.FP_WIRE6
FP_SOP16_NS = "Package_SO:SO-16_5.3x10.2mm_P1.27mm"   # TI NS0016A SOP: 5.2-5.4 mm body, 7.4-8.2 mm span
FP_PQFP44 = "Package_QFP:Microchip_PQFP-44_10x10mm_P0.8mm"   # HV5622PG-G, 10 x 10 mm body, no exposed pad
FP_SOD123 = gs.FP_SOD123
FP_IN14 = "nixie:IN-14"
FP_ZERO = "nixie:RP2040-Zero_Castellated"


# --------------------------------------------------------------------------------------
# Project symbols
# --------------------------------------------------------------------------------------

_pin, _sprop = gs._pin, gs._sprop

# HV5622 (Microchip DS20005854A, 44-lead PQFP, Table 2-1): pins 1-22 = HVOUT22..HVOUT1,
# 23 DATA OUT, 24-26 NC, 27 POL, 28 CLK, 29 VSS, 30 VDD, 31 LE, 32 DATA IN, 33 BL, 34 NC,
# 35-44 = HVOUT32..HVOUT23. Truth table (Table 3-2): BL low with POL high = all outputs off;
# LE high loads the latches from the shift register; data shifts on the falling CLK edge.
HV5622_OUT = {k: str(23 - k) if k <= 22 else str(67 - k) for k in range(1, 33)}


def hv5622_symbol_text() -> str:
    pins = [_pin("open_collector", 12.7, 40.64 - (k - 1) * 2.54, 180, f"HVOUT{k}", num)
            for k, num in HV5622_OUT.items()]
    pins += [_pin("output", 12.7, -43.18, 180, "DOUT", "23")]
    pins += [_pin("input", -12.7, 10.16 - i * 5.08, 0, name, num)
             for i, (name, num) in enumerate((("DIN", "32"), ("CLK", "28"), ("~{LE}", "31"), ("~{BL}", "33"),
                                               ("~{POL}", "27")))]
    pins += [_pin("no_connect", -12.7, -20.32 - i * 2.54, 0, "NC", num) for i, num in enumerate(("24", "25", "26", "34"))]
    pins += [_pin("power_in", 0, 48.26, 270, "VDD", "30"), _pin("power_in", 0, -50.8, 90, "VSS", "29")]
    return f'''(symbol "HV5622" (exclude_from_sim no) (in_bom yes) (on_board yes)
	{_sprop("Reference", "U", 2.54, 46.99)}
	{_sprop("Value", "HV5622", 2.54, -49.53)}
	{_sprop("Footprint", FP_PQFP44, 0, 0, True)}
	{_sprop("Datasheet", "docs/datasheets/hv5622.pdf", 0, 0, True)}
	{_sprop("Description", "32-channel serial-to-parallel converter, 220 V open-drain outputs, latches, VDD 12 V, 44-lead PQFP", 0, 0, True)}
	(symbol "HV5622_0_1"
		(rectangle (start -10.16 45.72) (end 10.16 -48.26) (stroke (width 0.254) (type default)) (fill (type background)))
	)
	(symbol "HV5622_1_1"
		{" ".join(pins)}
	)
	(embedded_fonts no)
)'''


# IN-14, tube-tester.com pinout (bottom view): 1 anode, 2 left decimal point, 3-11 digits 1-9,
# 12 digit 0, 13 right decimal point
IN14_CATHODES = [("LDP", "2"), ("0", "12")] + [(str(d), str(d + 2)) for d in range(1, 10)] + [("RDP", "13")]


def in14_symbol_text() -> str:
    pins = [_pin("passive", 0, 20.32, 270, "A", "1")]
    pins += [_pin("passive", -10.16, 13.97 - i * 2.54, 0, name, num) for i, (name, num) in enumerate(IN14_CATHODES)]
    return f'''(symbol "IN-14" (exclude_from_sim no) (in_bom yes) (on_board yes)
	{_sprop("Reference", "N", 3.81, 19.05)}
	{_sprop("Value", "IN-14", 3.81, -19.05)}
	{_sprop("Footprint", FP_IN14, 0, 0, True)}
	{_sprop("Datasheet", "https://www.tube-tester.com/sites/nixie/data/in-14/in-14.htm", 0, 0, True)}
	{_sprop("Description", "IN-14 Nixie tube, digits 0-9, left and right decimal points, 13 wire leads", 0, 0, True)}
	(symbol "IN-14_0_1"
		(rectangle (start -7.62 17.78) (end 7.62 -17.78) (stroke (width 0.254) (type default)) (fill (type background)))
	)
	(symbol "IN-14_1_1"
		{" ".join(pins)}
	)
	(embedded_fonts no)
)'''


def zero_symbol_text() -> str:
    return gs.rp2040_zero_symbol_text().replace("dekatron:RP2040-Zero_Castellated", FP_ZERO)


def project_symbol_lib_text(lib: gs.SymbolLib) -> str:
    return ('(kicad_symbol_lib (version 20251024) (generator "nixie-gen") (generator_version "10.0")\n'
            + hv5622_symbol_text() + "\n" + in14_symbol_text() + "\n" + zero_symbol_text() + "\n)\n")


# --------------------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------------------

class Sheet(gs.Sheet):
    def render(self, is_root=False) -> str:
        return (super().render(is_root).replace('(generator "dekatron-gen")', '(generator "nixie-gen")')
                .replace("tools/gen_schematics.py", "tools/gen_nixie_schematics.py"))


R, C, CP, TP = "Device:R", "Device:C", "Device:C_Polarized", "Connector:TestPoint"
NPN = "Transistor_BJT:Q_NPN_BEC"
DZ = "Device:D_Zener"


CHAR_W = 1.1            # mm per character of 1.27 mm schematic text (conservative), for wrapping notes


def note(sh, head, detail, x, y, width=95.0):
    """Section heading plus its explanation, wrapped to `width` mm so neighbouring notes never
    run into each other."""
    sh.text(head, x, y, 2.0)
    if detail:
        body = "\n".join(textwrap.wrap(detail, int(width / CHAR_W)))
        sh.items.append(f'(text {q(body)} (exclude_from_sim no) (at {gs.fmt(x)} {gs.fmt(y + 1.27)} 0) '
                        f'(effects (font (size 1.27 1.27)) (justify left top)) (uuid "{sh.key("txt")}"))')


def mark(sh, pt, net, side="R"):
    """End a wire at pt with the net's marker: GND / supply symbol, or a horizontal (global) label
    whose text runs to the right ("R") or left ("L") of pt."""
    if net == "GND":
        sh.gnd(pt)
    elif net in gs.POWER_NETS:
        sh.pwr(net, pt)
    elif net in sh.global_nets:
        sh.gl(net, pt, 0 if side == "R" else 180)
    else:
        sh.nl(net, pt, 0 if side == "R" else 180)


def lead(sh, pt, net, dx, dy, side=None):
    """Wire from pt by (dx, dy), then the net's marker. Labels always read horizontally."""
    end = (round(pt[0] + dx, 4), round(pt[1] + dy, 4))
    sh.w(pt, end)
    mark(sh, end, net, side or ("L" if dx < 0 else "R"))
    return end


def v2(sh, lib_id, ref, val, x, ytop, fp, fields, **kw):
    """Two-pin part standing upright with pin 1 at (x, ytop); returns (pin 1, pin 2)."""
    pm = sh.place(lib_id, ref, val, x, ytop + 3.81, footprint=fp, fields=fields, **kw)
    return pm["1"], pm["2"]


def h2(sh, lib_id, ref, val, xl, y, fp, fields):
    """Two-pin part lying down with pin 1 at (xl, y), pin 2 to the right; returns (pin 1, pin 2)."""
    pm = sh.place(lib_id, ref, val, xl + 3.81, y, angle=90, footprint=fp, fields=fields)
    return pm["1"], pm["2"]


def by_number(sh, lib_id, x, y, angle=0, mirror=None):
    """Pin positions keyed by pin number only (place() also keys by name, and the IN-14's digit
    names "0"-"9" collide with pin numbers)."""
    return {p["number"]: gs.xf(p["x"], p["y"], x, y, angle, mirror)
            for p in sh.lib.pins(lib_id) if p["unit"] in (0, 1)}


def tp(sh, ref, net, pt, **kw):
    """Test pad sitting on a wire point (pad above the point)."""
    sh.place(TP, ref, net, pt[0], pt[1], footprint=FP_TP, fields=F(f"Test point {net}"), **kw)


def rail(sh, *pts):
    """Wire through a row of points (split at each, so the taps get junctions)."""
    for a, b in zip(pts, pts[1:]):
        sh.w(a, b)


POWER_GLOBALS = {"SDA", "SCL", "NIX_SPARE", "NIX12_EN", "NIX12_SENSE", "NIX_HV", "NIX_HV_SENSE", "+12V_IN"}


def build_power(lib) -> Sheet:
    sh = Sheet("power", "power.kicad_sch", U("file:power"), "A3", lib, f"/{ROOT_UUID}/{POWER_UUID}",
               global_nets=POWER_GLOBALS, title="Power: harness landings, Nixie HV module 12 V switch, HV monitor")

    # ---- harness landings (left) ------------------------------------------------------------
    note(sh, "HARNESS LANDINGS (D14, soldered)", "NIX_LV and NIX_12V come from the dekatron board; J103 "
         "and J104 go to the Nixie HV module (its 12 V input and its HV output).", 20.32, 22.86, 90)
    sh.part("Connector_Generic:Conn_01x06", "J101", "NIX_LV", 63.5, 50.8,
            {"1": "+5V", "2": "GND", "3": "SDA", "4": "SCL", "5": "GND", "6": "NIX_SPARE"}, footprint=FP_WIRE6,
            fields=F("Harness NIX_LV from the dekatron board (its J302; 5 V behind its ideal diode U104)"))
    sh.part("Connector_Generic:Conn_01x02", "J102", "12V_IN", 63.5, 81.28, {"1": "+12V_IN", "2": "GND"},
            footprint=FP_WIRE2, fields=F("12 V from the dekatron board's NIX_12V (J102, behind its PTC)"))
    sh.part("Connector_Generic:Conn_01x02", "J103", "12V_MODULE", 63.5, 96.52, {"1": "+12V_SW", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Switched 12 V to the Nixie HV module input"))
    sh.part("Connector_Generic:Conn_01x02", "J104", "HV_MODULE", 63.5, 111.76, {"1": "NIX_HV", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Nixie HV module output (~170 V) and its return"))

    note(sh, "+5V BULK, TEST PADS", "At the NIX_LV landing", 20.32, 132.08, 90)
    t, b = v2(sh, CP, "C101", "10uF", 30.48, 152.4, FP_TANT_A,
              F("+5V bulk at the harness landing (user 2026-11-07: as C301)", rating="16 V tantalum"))
    top, bot = (t[0], t[1] - 5.08), (b[0], b[1] + 5.08)
    sh.w(t, top)
    sh.pwr("+5V", top)
    rail(sh, t, (45.72, t[1]), (58.42, t[1]))
    tp(sh, "TP104", "+5V", (45.72, t[1]))
    sh.pflag((58.42, t[1]))
    sh.w(b, bot)
    sh.gnd(bot)
    rail(sh, b, (45.72, b[1]), (58.42, b[1]))
    tp(sh, "TP105", "GND", (45.72, b[1]))
    sh.pflag((58.42, b[1]))

    # ---- 12 V switch (middle) -----------------------------------------------------------------
    note(sh, "NIXIE HV MODULE 12 V SWITCH", "High side, off by default: R101 holds Q101 off, R104 holds Q102 "
         "off while the RP2040 is in reset. C102 with R101 / R102 sets a soft start into the module's "
         "470 uF (hardware/nixie/simulation/nix12_switch.cir).", 132.08, 22.86, 95)
    r0 = 58.42                                            # +12V_IN rail
    mark(sh, (134.62, r0), "+12V_IN", "L")
    rail(sh, (134.62, r0), (142.24, r0), (157.48, r0), (172.72, r0), (185.42, r0), (208.28, r0))
    tp(sh, "TP101", "+12V_IN", (142.24, r0))
    sh.pflag((157.48, r0), textpos=(-3.81, -6.35))
    ct, cb = v2(sh, C, "C102", "3.3uF", 172.72, r0, FP_C,
                F("Q101 gate-source: soft turn-on with R101/R102; holds Q101 off on hot-plug", rating="25 V X7R"))
    rt, rb = v2(sh, R, "R101", "47k", 185.42, r0, FP_R,
                F("Q101 gate pull-up: off by default. With R102: VGS -6 V at 12 V, -12 V at the 24 V clamp"))
    q1 = sh.place("Transistor_FET:Q_PMOS_GDS", "Q101", "IPD50P04P4L-11", 205.74, 71.12, mirror="x",
                  textpos=(5.08, -1.27),
                  footprint=gs.FP_DPAK, fields=F("Nixie module 12 V high-side switch with soft start",
                                                 "IPD50P04P4L-11", "Infineon",
                                                 "-40 V, 17.2 mohm max at VGS -4.5 V, VGS +5/-16 V"))
    g = (185.42, 71.12)                                   # gate node
    sh.w(cb, (172.72, 71.12), g)
    sh.w(rb, g)
    sh.w(g, q1["G"])
    sh.w(q1["S"], (208.28, r0))
    sh.nl("NIX12_G", (190.5, 71.12))
    r2t, r2b = v2(sh, R, "R102", "47k", 185.42, 78.74, FP_R, F("Q101 gate series: sets the turn-on ramp with C102"))
    sh.w(g, r2t)
    q2 = sh.place(NPN, "Q102", "MMBT3904", 182.88, 96.52, footprint=FP_SOT23,
                  fields=F("Level shifter for Q101's gate", "MMBT3904", rating="40 V NPN"))
    sh.w(r2b, q2["C"])
    sh.nl("NIX12_D", (185.42, 88.9))
    sh.gnd(q2["E"])
    bn = (167.64, 96.52)                                  # base node
    sh.w(q2["B"], bn)
    sh.nl("NIX12_B", bn)
    r3l, r3r = h2(sh, R, "R103", "10k", 152.4, 96.52, FP_R, F("Q102 base (as D8: 3.3 V drive)"))
    sh.w(r3r, bn)
    lead(sh, r3l, "NIX12_EN", -2.54, 0)
    r4t, r4b = v2(sh, R, "R104", "47k", 167.64, 101.6, FP_R,
                  F("Q102 base pull-down: switch off while the RP2040 is in reset (D7)"))
    sh.w(bn, r4t)
    sh.gnd(r4b)
    dn = (208.28, 83.82)
    rail(sh, q1["D"], dn, (215.9, 83.82), (236.22, 83.82))
    tp(sh, "TP102", "+12V_SW", (215.9, 83.82))
    mark(sh, (236.22, 83.82), "+12V_SW")

    # ---- switched 12 V sense (below the switch) -------------------------------------------------
    note(sh, "SWITCHED 12 V SENSE", "Divider to ADC1 (GP27), as the dekatron VIN_SENSE: 1.29 V at 12 V, "
         "2.57 V at the 24 V clamp. Tells a switch fault from a module fault when NIX_HV is missing "
         "(user, 2026-11-11).", 132.08, 132.08, 95)
    y0 = 152.4
    mark(sh, (144.78, y0), "+12V_SW", "L")
    st, sb = v2(sh, R, "R107", "100k", 152.4, y0, FP_R, F("+12V_SW sense divider, upper (1.29 V at 12 V)"))
    sh.w((144.78, y0), st)
    n1, n2, n3 = (152.4, sb[1] + 2.54), (165.1, sb[1] + 2.54), (180.34, sb[1] + 2.54)
    sh.w(sb, n1)
    rail(sh, n1, n2, n3)
    mark(sh, n3, "NIX12_SENSE")
    lt, lb = v2(sh, R, "R108", "12k", 152.4, n1[1] + 5.08, FP_R,
                F("+12V_SW sense divider, lower (2.57 V at 24 V)", rating="1 %"))
    sh.w(n1, lt)
    sh.gnd(lb)
    ct, cb = v2(sh, C, "C104", "100nF", 165.1, n1[1] + 5.08, FP_C,
                F("NIX12_SENSE ADC sampling reservoir (as the dekatron ADC inputs)", rating="50 V X7R"))
    sh.w(n2, ct)
    sh.gnd(cb)

    # ---- HV monitor (right) -------------------------------------------------------------------
    note(sh, "NIXIE HV MONITOR", "Divider to ADC0: 3.3 V at about 278 V. R105 is also the bleeder (below "
         "30 V in about 2-3 s, measured). BAT54S clamp and reservoir as on the dekatron ADC inputs.",
         243.84, 22.86, 95)
    hv = 50.8
    mark(sh, (246.38, hv), "NIX_HV", "L")
    rail(sh, (246.38, hv), (251.46, hv), (269.24, hv), (281.94, hv))
    tp(sh, "TP103", "NIX_HV", (251.46, hv))
    sh.pflag((269.24, hv), textpos=(-3.81, -6.35))
    at, ab = v2(sh, R, "R105", "1M", 281.94, hv, FP_AX0411,
                F("HV monitor divider, upper; bleeder", "HHV-50FT-52-1M", rating="HHV-50: 0.5 W"))
    s1, s2, s3 = (281.94, 66.04), (294.64, 66.04), (314.96, 66.04)
    sh.w(ab, s1)
    rail(sh, s1, s2, s3, (327.66, 66.04))
    mark(sh, (327.66, 66.04), "NIX_HV_SENSE")
    lt, lb = v2(sh, R, "R106", "12k", 281.94, 71.12, FP_R, F("HV monitor divider, lower", rating="1 %"))
    sh.w(s1, lt)
    sh.gnd(lb)
    c3t, c3b = v2(sh, C, "C103", "100nF", 294.64, 71.12, FP_C,
                  F("NIX_HV_SENSE ADC sampling reservoir (as the dekatron ADC inputs)", rating="50 V X7R"))
    sh.w(s2, c3t)
    sh.gnd(c3b)
    # rotated only (no mirror): K up to 3V3, A down to GND, COM to the right onto the sense branch
    d1 = sh.place("Diode:BAT54S", "D101", "BAT54S", 309.88, 83.82, angle=90, textpos=(7.62, 2.54),
                  fields=F("NIX_HV_SENSE clamp to 3V3 / GND", "BAT54S", rating="30 V Schottky pair"))
    sh.w(s3, d1["COM"])
    sh.pwr("+3V3", d1["K"])
    sh.gnd(d1["A"])
    sh.finish()
    return sh


DRV = ("DATA", "CLK", "LE", "BL")           # RP2040 -> CD40109B -> HV5622 lines
LOGIC_GLOBALS = {"SDA", "SCL", "NIX_SPARE", "NIX12_EN", "NIX12_SENSE", "NIX_HV_SENSE", "+12V_IN",
                 "+12V_LOGIC", "DRV12_DOUT"} | {f"DRV12_{s}" for s in DRV}


def build_logic(lib) -> Sheet:
    sh = Sheet("logic", "logic.kicad_sch", U("file:logic"), "A3", lib, f"/{ROOT_UUID}/{LOGIC_UUID}",
               global_nets=LOGIC_GLOBALS,
               title="Logic: RP2040-Zero, level shifter, encoder, time modules")

    # ---- RP2040-Zero (top left) ---------------------------------------------------------------
    note(sh, "RP2040-Zero (pin map: docs/hardware.md)", "Castellated, soldered by its edge pads; powered "
         "from +5V (NIX_LV). C301 / C302 at the module.", 20.32, 22.86, 100)
    nets = {"5V": "+5V", "GND": "GND", "3V3": "+3V3",
            "GP0": "NIX12_EN", "GP1": "NIX_SPARE", "GP2": "SDA", "GP3": "SCL", "GP4": "WWVB_SDA",
            "GP5": "WWVB_SCL", "GP6": "WWVB_EN", "GP7": "WWVB_IRQ", "GP8": "DRV_BL", "GP9": "DRV_LE",
            "GP10": "DRV_CLK", "GP11": "DRV_DATA", "GP12": "DRV_DOUT", "GP13": "ENC_A", "GP14": "ENC_B",
            "GP15": "ENC_SW", "GP26": "NIX_HV_SENSE", "GP27": "NIX12_SENSE", "GP28": "GP28", "GP29": "GP29"}
    sh.part("nixie:RP2040-Zero", "U301", "RP2040-Zero", 73.66, 71.12, nets, textpos=(-12.7, -27.5),
            footprint=FP_ZERO, fields=F("Nixie controller MCU", "RP2040-Zero", "Waveshare", "headerless, castellated"))
    sh.part(CP, "C301", "10uF", 106.68, 39.37, {"1": "+5V", "2": "GND"}, footprint=FP_TANT_A,
            fields=F("+5V bulk at the module (as dekatron C301)", rating="16 V tantalum"))
    sh.part(C, "C302", "0.1uF", 119.38, 39.37, {"1": "+3V3", "2": "GND"}, footprint=FP_C,
            fields=F("3V3 bypass (as dekatron C302)", rating="50 V X7R"))

    # ---- level shifter (top middle) -------------------------------------------------------------
    note(sh, "LEVEL SHIFTER: CD40109B, 3.3 V -> 12 V", "HV5622 inputs need V_IH >= VDD - 2 V. Enables tied "
         "to 3V3. DRV_BL pulled down: all tube outputs off while the RP2040 is in reset (BL low, POL "
         "high). R310: the same while 3V3 is absent. Readback: U203 DOUT (DRV12_DOUT) to GP12 (SPI1 RX) through "
         "R314 / R315 (user, 2026-11-11).", 142.24, 22.86, 105)
    u = sh.place("Logic_LevelTranslator:CD40109BPW", "U302", "CD40109B", 193.04, 68.58, footprint=FP_SOP16_NS,
                 textpos=(10.16, 12.7),
                 fields=F("3.3 V -> 12 V for the HV5622 inputs", "CD40109BNSRE4", "TI",
                          "VCC/VDD 3-18 V, SOP-16 (NS) 5.3 mm"))
    for pin, net in (("3", "DRV_DATA"), ("6", "DRV_CLK"), ("10", "DRV_LE"), ("14", "DRV_BL")):
        lead(sh, u[pin], net, -2.54, 0)
    for pin, net in (("4", "DRV12_DATA"), ("5", "DRV12_CLK"), ("11", "DRV12_LE"), ("13", "DRV12_BL")):
        lead(sh, u[pin], net, 2.54, 0)
    bx = 162.56                                          # enables bus, tied to 3V3
    ens = [u[p] for p in ("2", "7", "9", "15")]
    for e in ens:
        sh.w(e, (bx, e[1]))
    rail(sh, *[(bx, e[1]) for e in ens])
    sh.w((bx, ens[0][1]), (bx, ens[0][1] - 2.54))
    sh.pwr("+3V3", (bx, ens[0][1] - 2.54))
    vcc, vdd = u["1"], u["16"]
    sh.w(vcc, (vcc[0], vcc[1] - 2.54))
    sh.pwr("+3V3", (vcc[0], vcc[1] - 2.54))
    sh.w(vdd, (vdd[0], vdd[1] - 5.08))
    lead(sh, (vdd[0], vdd[1] - 5.08), "+12V_LOGIC", 2.54, 0)
    sh.gnd(u["8"])
    c4t, c4b = v2(sh, C, "C304", "0.1uF", 172.72, 96.52, FP_C, F("U302 VCC bypass", rating="50 V X7R"))
    sh.pwr("+3V3", c4t)
    sh.gnd(c4b)
    c3t, c3b = v2(sh, C, "C303", "0.1uF", 187.96, 96.52, FP_C, F("U302 VDD bypass", rating="50 V X7R"))
    lead(sh, c3t, "+12V_LOGIC", 0, -2.54, "R")
    sh.gnd(c3b)
    r1t, r1b = v2(sh, R, "R301", "10k", 220.98, 96.52, FP_R,
                  F("DRV_BL pull-down: tubes blank while the RP2040 is in reset"))
    lead(sh, r1t, "DRV_BL", 0, -2.54, "R")
    sh.gnd(r1b)
    r10t, r10b = v2(sh, R, "R310", "100k", 238.76, 96.52, FP_R,
                    F("DRV12_BL pull-down: tubes blank while 3V3 is absent (U302 outputs then high-impedance)"))
    lead(sh, r10t, "DRV12_BL", 0, -2.54, "R")
    sh.gnd(r10b)
    yd = 114.3                                           # DOUT readback divider, 12 V -> 3.3 V
    mark(sh, (142.24, yd), "DRV12_DOUT", "L")
    dl, dr = h2(sh, R, "R314", "100k", 147.32, yd, FP_R,
                F("DRV12_DOUT readback divider, upper: 2.43-3.39 V at DOUT high (9.8-13.65 V)"))
    sh.w((142.24, yd), dl)
    dn = (162.56, yd)
    rail(sh, dr, dn, (175.26, yd))
    mark(sh, (175.26, yd), "DRV_DOUT")
    d2t, d2b = v2(sh, R, "R315", "33k", 162.56, yd, FP_R,
                  F("DRV12_DOUT readback divider, lower: <= 0.25 V at DOUT low (1 V max)"))
    sh.gnd(d2b)

    # ---- 12 V logic rail (top right) ------------------------------------------------------------
    note(sh, "12 V LOGIC RAIL", "HV5622 / CD40109B VDD. The HV5622's VDD absolute maximum is 15 V, below the "
         "24 V TVS clamp on the 12 V input: series resistor and 13 V zener (12.35-13.65 V).", 274.32, 22.86, 115)
    y = 55.88
    mark(sh, (279.4, y), "+12V_IN", "L")
    r9l, r9r = h2(sh, R, "R309", "470", 284.48, y, FP_R,
                  F("12 V logic rail series resistor: ~0.2 V at ~0.45 mA average; 0.23 W at the 24 V clamp",
                    rating="1206, 0.25 W"))
    sh.w((279.4, y), r9l)
    z, cn, tn, fn, out = (304.8, y), (322.58, y), (337.82, y), (353.06, y), (365.76, y)
    rail(sh, r9r, z, cn, tn, fn, out)
    mark(sh, out, "+12V_LOGIC")
    dz = sh.place(DZ, "D301", "MMSZ5243B", 304.8, 64.77, angle=270, footprint=FP_SOD123,
                  fields=F("12 V logic rail clamp", "MMSZ5243B", rating="13 V, 500 mW, SOD-123"))
    sh.w(z, dz["K"])
    sh.gnd(dz["A"])
    c5t, c5b = v2(sh, C, "C305", "10uF", 322.58, 60.96, FP_C,
                  F("12 V logic reservoir: shift bursts", rating="25 V X7R"))
    sh.w(cn, c5t)
    sh.gnd(c5b)
    tp(sh, "TP306", "+12V_LOGIC", tn)
    sh.pflag(fn, textpos=(-3.81, -6.35))

    # ---- encoder (bottom left) ------------------------------------------------------------------
    note(sh, "ENCODER (front panel, harness)", "Bourns PEC11R wired to J301 (user, 2026-11-07). Filter per "
         "its data sheet (Suggested Filter Circuit): 10k pull-up, 10k series, 0.01 uF; the push switch "
         "the same.", 20.32, 132.08, 105)
    sh.part("Connector_Generic:Conn_01x04", "J301", "ENCODER", 40.64, 165.1,
            {"1": "ENC_A_RAW", "2": "ENC_B_RAW", "3": "ENC_SW_RAW", "4": "GND"}, footprint=FP_WIRE4,
            fields=F("Harness to the panel-mount encoder (PEC11R): A, B, switch, common C and switch 2"))
    for i, net in enumerate(("ENC_A", "ENC_B", "ENC_SW")):
        yr = 165.1 + i * 25.4
        put, pub = v2(sh, R, f"R{302 + i}", "10k", 76.2, yr - 7.62, FP_R,
                      F(f"{net} pull-up (PEC11R suggested filter)"))
        sh.pwr("+3V3", put)
        sl, sr = h2(sh, R, f"R{311 + i}", "10k", 83.82, yr, FP_R,
                    F(f"{net} series: filter discharge through 10k, not the contact (PEC11R suggested filter)"))
        rail(sh, (63.5, yr), pub, sl)
        mark(sh, (63.5, yr), net + "_RAW", "L")
        o = (99.06, yr)
        sh.w(sr, o)
        cct, ccb = v2(sh, C, f"C{308 + i}", "0.01uF", 99.06, yr, FP_C,
                      F(f"{net} debounce, 0.1 ms with the series 10k (PEC11R suggested filter)", rating="25 V X7R"))
        sh.w(o, (109.22, yr))
        mark(sh, (109.22, yr), net)
        sh.gnd(ccb)

    # ---- time modules (bottom middle) -----------------------------------------------------------
    note(sh, "TIME MODULES (optional, harnesses)", "RTC (ZS-042) on the main bus; ES100 on its private bus. "
         "Pull resistors here so an unplugged module leaves defined levels; values chosen at assembly.",
         142.24, 132.08, 110)
    sh.part("Connector_Generic:Conn_01x04", "J302", "RTC", 172.72, 160.02,
            {"1": "+3V3", "2": "GND", "3": "SDA", "4": "SCL"}, footprint=FP_WIRE4, stub=5.08,
            fields=F("Harness to the DS3231 module (ZS-042): jacks on its header by silk name"))
    sh.part("Connector_Generic:Conn_01x06", "J303", "WWVB", 172.72, 193.04,
            {"1": "+3V3", "2": "GND", "3": "WWVB_SDA", "4": "WWVB_SCL", "5": "WWVB_EN", "6": "WWVB_IRQ"},
            footprint=FP_WIRE6, stub=5.08, fields=F("Harness to the ES100 carrier: jacks on its header by silk name"))
    for i, (net, up, func) in enumerate((("WWVB_SDA", True, "pull-up (unless on the carrier)"),
                                         ("WWVB_SCL", True, "pull-up (unless on the carrier)"),
                                         ("WWVB_IRQ", True, "pull-up (IRQ- is active low)"),
                                         ("WWVB_EN", False, "pull-down: ES100 in shutdown when unplugged or in reset"))):
        x = 200.66 + i * 20.32
        pt, pb = v2(sh, R, f"R{305 + i}", OPEN, x, 182.88, FP_R, F(f"{net} {func}"))
        if up:
            sh.pwr("+3V3", pt)
            lead(sh, pb, net, 0, 2.54, "R")
        else:
            lead(sh, pt, net, 0, -2.54, "R")
            sh.gnd(pb)

    # ---- test pads (bottom right) ---------------------------------------------------------------
    note(sh, "TEST PADS", "Readback, 12 V sense, spare GPIOs, 3V3, driver lines (3.3 V side)", 302.26, 132.08, 90)
    for i, net in enumerate(("DRV_DOUT", "NIX12_SENSE", "GP28", "GP29", "+3V3", "DRV_DATA", "DRV_CLK", "DRV_LE", "DRV_BL")):
        x, yy = 309.88 + (i // 5) * 40.64, 152.4 + (i % 5) * 12.7
        ref = f"TP{301 + i + (1 if i >= 5 else 0)}"      # TP306 (+12V_LOGIC) sits on the 12 V logic rail
        tp(sh, ref, net, (x, yy), textpos=(-12.7, -2.54))
        lead(sh, (x, yy), net, 10.16, 0)
    sh.finish()
    return sh


TUBES_GLOBALS = {"NIX_HV", "+12V_LOGIC", "DRV12_DOUT"} | {f"DRV12_{s}" for s in DRV}
CHIPS = 3                                   # HV5622, two tubes each


# HV5622 output -> (tube of the pair, signal), the same for all three chips (2026-11-06). Assigned
# from the PCB geometry: the 24 tube pads sorted by angle as seen from the chip get a run of 24
# adjacent outputs in the same order, the run with the least total distance (outputs follow the
# package perimeter 35..44, 1..22). "a" = the pair's left tube, "b" = the right tube. Firmware owns
# this map (bit n of a chip's 32 = HVOUTn; the chain is U201 -> U202 -> U203).
HV_MAP = {29: ("b", "RDP_D"), 28: ("b", "K0"), 27: ("b", "K9"), 26: ("b", "LDP_D"), 25: ("b", "K8"),
          24: ("b", "K7"), 23: ("b", "K1"), 22: ("b", "K6"), 21: ("b", "K5"), 20: ("b", "K2"),
          19: ("b", "K4"), 18: ("b", "K3"), 17: ("a", "K8"), 16: ("a", "K7"), 15: ("a", "K9"),
          14: ("a", "K6"), 13: ("a", "K5"), 12: ("a", "K0"), 11: ("a", "K4"), 10: ("a", "K3"),
          9: ("a", "RDP_D"), 8: ("a", "K2"), 7: ("a", "K1"), 6: ("a", "LDP_D")}
assert sorted(HV_MAP.values()) == sorted((t, s) for t in "ab" for s in [f"K{d}" for d in range(10)] + ["LDP_D", "RDP_D"])


def build_tubes(lib) -> Sheet:
    sh = Sheet("tubes", "tubes.kicad_sch", U("file:tubes"), "A3", lib, f"/{ROOT_UUID}/{TUBES_UUID}",
               global_nets=TUBES_GLOBALS, title="Tubes: HV5622 drivers, IN-14s, resistors")
    note(sh, "TUBE DRIVERS: 3 x HV5622 (220 V open drain)", "Tube 1 at the left as seen by the viewer. Chain "
         "U201 -> U202 -> U203 (DRV12_D1, DRV12_D2), 96 bits latched whole (LE); U203 DOUT back to the RP2040 "
         "(DRV12_DOUT, readback). Outputs assigned from the "
         "PCB geometry (HV_MAP in tools/gen_nixie_schematics.py, table in docs/hardware.md); HVOUT1-5 and "
         "30-32 spare. Firmware owns the map. Each tube: 12k anode resistor from NIX_HV, 150k in series "
         "with each decimal point.", 20.32, 22.86, 250)
    for k in range(CHIPS):
        x0 = 15.24 + k * 127.0
        ta, tb = 2 * k + 1, 2 * k + 2
        note(sh, f"U{201 + k}: TUBES {ta} AND {tb}", "", x0 + 5.08, 48.26)
        xc, yc = x0 + 43.18, 127.0
        nets = {HV5622_OUT[o]: (f"T{ta if HV_MAP[o][0] == 'a' else tb}_{HV_MAP[o][1]}" if o in HV_MAP else "NC")
                for o in range(1, 33)}
        u = sh.place("nixie:HV5622", f"U{201 + k}", "HV5622", xc, yc, footprint=FP_PQFP44, textpos=(2.54, 52.07),
                     fields=F(f"Tube {ta}/{tb} cathode and decimal-point driver", "HV5622PG-G", "Microchip",
                              "220 V outputs, PQFP-44 0.8 mm"))
        for num, net in nets.items():
            if net == "NC":
                sh.noconn(*u[num])
            else:
                lead(sh, u[num], net, 2.54, 0)
        lead(sh, u["23"], f"DRV12_D{k + 1}" if k < CHIPS - 1 else "DRV12_DOUT", 2.54, 0)
        for num, net in (("32", "DRV12_DATA" if k == 0 else f"DRV12_D{k}"), ("28", "DRV12_CLK"),
                         ("31", "DRV12_LE"), ("33", "DRV12_BL"), ("27", "+12V_LOGIC")):
            lead(sh, u[num], net, -2.54, 0)
        n = (xc, u["30"][1] - 5.08)                       # VDD node: bypass to the left, rail label right
        sh.w(u["30"], n)
        cx = xc - 12.7
        sh.w(n, (cx, n[1]))
        lead(sh, n, "+12V_LOGIC", 5.08, 0)
        bt, bb = v2(sh, C, f"C{201 + k}", "0.1uF", cx, n[1], FP_C, F(f"U{201 + k} VDD bypass", rating="50 V X7R"))
        sh.gnd(bb)
        sh.gnd(u["29"])
        for j, t in enumerate((ta, tb)):
            xt, yt = x0 + 115.57, 88.9 + j * 66.04
            nt = sh.place("nixie:IN-14", f"N{t}", "IN-14", xt, yt, footprint=FP_IN14, fields=F(f"Tube {t}", "IN-14"))
            nt = by_number(sh, "nixie:IN-14", xt, yt)
            for d in range(10):
                lead(sh, nt[str(d + 2) if d else "12"], f"T{t}_K{d}", -2.54, 0)
            for pin, dp in (("2", "LDP"), ("13", "RDP")):
                rl, rr = h2(sh, R, f"R{200 + 10 * t + (1 if dp == 'LDP' else 2)}", "150k", xt - 30.48, nt[pin][1], FP_R,
                            F(f"Tube {t} {dp} series resistor: starting value, point <= 0.3 mA; check at bring-up"))
                sh.w(rr, nt[pin])
                sh.nl(f"T{t}_{dp}_K", rr)
                lead(sh, rl, f"T{t}_{dp}_D", -2.54, 0)
            ay = yt - 25.4                                 # anode resistor row, above the tube
            al, ar = h2(sh, R, f"R{200 + 10 * t}", "12k", xt - 20.32, ay, FP_AX0207,
                        F(f"Tube {t} anode resistor: (175 V - 145 V) / 2.5 mA, 75 mW",
                          rating="MRS25: 0.6 W, 350 V, 1 %, 50 ppm/K"))
            sh.w(ar, (xt, ay), nt["1"])
            sh.nl(f"T{t}_ANODE", ar)
            lead(sh, al, "NIX_HV", -2.54, 0)
    sh.finish()
    return sh


def build_root(lib) -> Sheet:
    sh = Sheet("root", f"{PROJECT}.kicad_sch", ROOT_UUID, "A4", lib, "/", title="Nixie controller / mount")
    sh.sheet("power", "power.kicad_sch", POWER_UUID, 40, 40, 60, 30, page="2")
    sh.sheet("logic", "logic.kicad_sch", LOGIC_UUID, 120, 40, 60, 30, page="3")
    sh.sheet("tubes", "tubes.kicad_sch", TUBES_UUID, 200, 40, 60, 30, page="4")
    sh.text("Sheets: power, logic, tubes. Inter-sheet nets are global labels. Values marked _open_ are "
            "listed in docs/hardware.md (Nixie board electrical design).", 40, 100, 2)
    return sh


# --------------------------------------------------------------------------------------
# Project file, tables
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
        # Nixie HV classes (user, 2026-11-06): clearance = the smallest copper gap already inside the
        # parts each class lands on. NCATH: HV5622 PQFP-44 pads, 0.8 mm pitch - 0.55 mm pad = 0.25 mm.
        # NHV: 1.25 mm, IPC-2221B B2 for 151-300 V (user, 2026-11-07); the IN-14 footprint's own pads
        # (square anode pad to the decimal-point pads, 1.156 mm) get 1.15 mm by a rule in
        # nixie.kicad_dru (gen_nixie_pcb.py).
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
                 "priority": 2147483647, "bus_width": 12, "line_style": 0, "wire_width": 6},
                nc("NHV", 1.25), nc("NCATH", 0.25)],
            "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
            "netclass_patterns": [
                {"netclass": "NHV", "pattern": "NIX_HV"},
                {"netclass": "NHV", "pattern": "*_ANODE"},
                {"netclass": "NCATH", "pattern": "*T?_K?"},
                {"netclass": "NCATH", "pattern": "*DP_K"},
                {"netclass": "NCATH", "pattern": "*DP_D"},
            ]},
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[ROOT_UUID, "Root"], [POWER_UUID, "power"], [LOGIC_UUID, "logic"], [TUBES_UUID, "tubes"]],
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-share", default=r"C:\Program Files\KiCad\10.0\share\kicad")
    args = ap.parse_args()

    lib = gs.SymbolLib(args.kicad_share)
    symlib = project_symbol_lib_text(lib)
    for s in find_all(parse(symlib), "symbol"):
        name = unq(s[1])
        s[1] = q(f"{PROJECT}:{name}")
        lib.defs[f"{PROJECT}:{name}"] = s

    power = build_power(lib)
    logic = build_logic(lib)
    tubes = build_tubes(lib)
    root = build_root(lib)

    gs.write_once(os.path.join(HW, f"{PROJECT}.kicad_pro"), project_json())
    gs.write(os.path.join(HW, f"{PROJECT}.kicad_sch"), root.render(is_root=True))
    gs.write(os.path.join(HW, "power.kicad_sch"), power.render())
    gs.write(os.path.join(HW, "logic.kicad_sch"), logic.render())
    gs.write(os.path.join(HW, "tubes.kicad_sch"), tubes.render())
    gs.write(os.path.join(HW, "fp-lib-table"), FP_TABLE)
    gs.write(os.path.join(HW, "sym-lib-table"), SYM_TABLE)
    gs.write(os.path.join(HW, "lib", f"{PROJECT}.kicad_sym"), symlib)
    gs.write(os.path.join(HW, "lib", f"{PROJECT}.pretty", "RP2040-Zero_Castellated.kicad_mod"),
             gs.rp2040_zero_footprint_text().replace('(generator "dekatron-gen")', '(generator "nixie-gen")'))
    gs.write_bom(os.path.join(HW, "bom.csv"), [power, logic, tubes])


if __name__ == "__main__":
    main()
