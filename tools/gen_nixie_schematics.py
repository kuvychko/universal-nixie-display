#!/usr/bin/env python3
"""
Generator for the Nixie controller/mount KiCad project (Phase 1B draft).

Writes into hardware/nixie/:
  nixie.kicad_pro             project file (written once; KiCad owns it afterwards)
  nixie.kicad_sch             root sheet
  power.kicad_sch             harness landings, Nixie HV module 12 V switch, HV monitor
  logic.kicad_sch             RP2040-Zero, 74HCT595 chain, encoder / RTC / ES100 landings
  tubes.kicad_sch             6 x (K155ID1, IN-14, anode resistor, two decimal-point drivers)
  sym-lib-table / fp-lib-table
  lib/nixie.kicad_sym         project symbols (K155ID1, IN-14, RP2040-Zero, Q_PMOS_GSD)
  lib/nixie.pretty/RP2040-Zero_Castellated.kicad_mod   (IN-14.kicad_mod is maintained by hand)
  bom.csv

Reuses the core of tools/gen_schematics.py (parser, symbol loading, Sheet). Connectivity style:
every pin gets a short stub ending in a net label, power symbol or no-connect (Sheet.part), so the
netlist is exactly the `nets` dictionaries below. Values not yet sourced are written as OPEN
("_open_"); they come from the Nixie HV module measurements (docs/hardware.md, "Nixie board
electrical design").

Usage:  python tools/gen_nixie_schematics.py [--kicad-share "C:/Program Files/KiCad/10.0/share/kicad"]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import uuid

import gen_schematics as gs
from gen_schematics import F, find, find_all, parse, q, unq

ROOT = gs.ROOT
HW = os.path.join(ROOT, "hardware", "nixie")
PROJECT = "nixie"

# The shared Sheet code reads these module globals: point them at this project.
gs.PROJECT = PROJECT
gs.NS = uuid.UUID("7c41d2a8-5e9b-4c3f-8a6d-1f2e3b4c5d6e")
gs.ORDERED = {}                     # no frozen BOM yet
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
FP_WIRE1 = gs.FP_WIRE1
FP_WIRE2 = gs.FP_WIRE2
FP_WIRE4 = gs.FP_WIRE4
FP_WIRE6 = gs.FP_WIRE6
FP_SOIC16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
# K155ID1 body (238.16-1/-2) has a 2.5 mm metric pitch; the 2.54 mm DIP footprint takes it (0.28 mm
# accumulated over 8 pins, absorbed by the leads)
FP_DIP16 = "Package_DIP:DIP-16_W7.62mm"
FP_IN14 = "nixie:IN-14"
FP_ZERO = "nixie:RP2040-Zero_Castellated"


# --------------------------------------------------------------------------------------
# Project symbols
# --------------------------------------------------------------------------------------

_pin, _sprop = gs._pin, gs._sprop

# K155ID1 (= SN74141), from the chipdip data sheet (docs/datasheets/k155id1/): inputs X1 (weight 1)
# pin 3, X2 pin 6, X3 pin 7, X4 pin 4; +U pin 5, common pin 12; outputs per the graphic symbol:
# 0-16, 1-15, 2-8, 3-9, 4-13, 5-14, 6-11, 7-10, 8-1, 9-2 (the text list repeats "V5" at pin 11:
# a typo, the symbol shows 6). Codes 10-15 light no output.
K155_OUT = {"0": "16", "1": "15", "2": "8", "3": "9", "4": "13", "5": "14", "6": "11", "7": "10",
            "8": "1", "9": "2"}
K155_IN = [("X1", "3"), ("X2", "6"), ("X3", "7"), ("X4", "4")]


def k155id1_symbol_text() -> str:
    pins = [_pin("input", -10.16, 7.62 - i * 5.08, 0, name, num) for i, (name, num) in enumerate(K155_IN)]
    pins += [_pin("open_collector", 10.16, 11.43 - int(d) * 2.54, 180, d, num) for d, num in K155_OUT.items()]
    pins += [_pin("power_in", 0, 17.78, 270, "VCC", "5"), _pin("power_in", 0, -17.78, 90, "GND", "12")]
    return f'''(symbol "K155ID1" (exclude_from_sim no) (in_bom yes) (on_board yes)
	{_sprop("Reference", "U", 2.54, 16.51)}
	{_sprop("Value", "K155ID1", 2.54, -16.51)}
	{_sprop("Footprint", FP_DIP16, 0, 0, True)}
	{_sprop("Datasheet", "docs/datasheets/k155id1/k155id1_chipdip.pdf", 0, 0, True)}
	{_sprop("Description", "BCD to decimal Nixie driver, 60 V open-collector outputs (SN74141 equivalent), DIP-16", 0, 0, True)}
	(symbol "K155ID1_0_1"
		(rectangle (start -7.62 15.24) (end 7.62 -15.24) (stroke (width 0.254) (type default)) (fill (type background)))
	)
	(symbol "K155ID1_1_1"
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


def pmos_gsd_symbol(lib: gs.SymbolLib) -> list:
    """Device:Q_PMOS with SOT-23 pad numbers (1 G, 2 S, 3 D). Check against the chosen FET."""
    sym = copy.deepcopy(lib.get("Device", "Q_PMOS"))
    sym[1] = q("Q_PMOS_GSD")
    for sub in find_all(sym, "symbol"):
        sub[1] = q(unq(sub[1]).replace("Q_PMOS_", "Q_PMOS_GSD_", 1))
        for p in find_all(sub, "pin"):
            num = find(p, "number")
            num[1] = q({"G": "1", "S": "2", "D": "3"}[unq(num[1])])
    for p in find_all(sym, "property"):
        if unq(p[1]) == "Footprint":
            p[2] = q(FP_SOT23)
        elif unq(p[1]) == "Description":
            p[2] = q("P-MOSFET, SOT-23 pinout 1 G, 2 S, 3 D")
    return sym


def project_symbol_lib_text(lib: gs.SymbolLib) -> str:
    return ('(kicad_symbol_lib (version 20251024) (generator "nixie-gen") (generator_version "10.0")\n'
            + k155id1_symbol_text() + "\n" + in14_symbol_text() + "\n" + zero_symbol_text() + "\n"
            + gs.dump(pmos_gsd_symbol(lib), 1) + "\n)\n")


# --------------------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------------------

class Sheet(gs.Sheet):
    def render(self, is_root=False) -> str:
        return (super().render(is_root).replace('(generator "dekatron-gen")', '(generator "nixie-gen")')
                .replace("tools/gen_schematics.py", "tools/gen_nixie_schematics.py"))


R, C, CP, TP = "Device:R", "Device:C", "Device:C_Polarized", "Connector:TestPoint"
NPN = "Transistor_BJT:Q_NPN_BEC"


def note(sh, head, detail, x, y):
    sh.text(head, x, y, 2.0)
    sh.text(detail, x, y + 4.32, 1.27)


def tp(sh, ref, net, x, y):
    sh.part(TP, ref, net, x, y, {"1": net}, footprint=FP_TP, fields=F(f"Test point {net}"))


POWER_GLOBALS = {"SDA", "SCL", "NIX_SPARE", "NIX12_EN", "NIX_HV", "NIX_HV_SENSE", "+12V_IN"}


def build_power(lib) -> Sheet:
    sh = Sheet("power", "power.kicad_sch", U("file:power"), "A3", lib, f"/{ROOT_UUID}/{POWER_UUID}",
               global_nets=POWER_GLOBALS, title="Power: harness landings, Nixie HV module 12 V switch, HV monitor")

    note(sh, "HARNESS LANDINGS (D14, soldered)", "NIX_LV and NIX_12V from the dekatron board; the module's "
         "12 V input and HV output", 20.32, 22.86)
    sh.part("Connector_Generic:Conn_01x06", "J101", "NIX_LV", 45.72, 58.42,
            {"1": "+5V", "2": "GND", "3": "SDA", "4": "SCL", "5": "GND", "6": "NIX_SPARE"}, footprint=FP_WIRE6,
            fields=F("Harness NIX_LV from the dekatron board (its J302; 5 V behind its ideal diode U104)"))
    sh.part("Connector_Generic:Conn_01x02", "J102", "12V_IN", 45.72, 93.98, {"1": "+12V_IN", "2": "GND"},
            footprint=FP_WIRE2, fields=F("12 V from the dekatron board's NIX_12V (J102, behind its PTC)"))
    sh.part("Connector_Generic:Conn_01x02", "J103", "12V_MODULE", 45.72, 114.3, {"1": "+12V_SW", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Switched 12 V to the Nixie HV module input"))
    sh.part("Connector_Generic:Conn_01x02", "J104", "HV_MODULE", 45.72, 134.62, {"1": "NIX_HV", "2": "GND"},
            footprint=FP_WIRE2, fields=F("Nixie HV module output (~170 V) and its return"))
    sh.flag("+5V", 25.4, 160.02)
    sh.flag("GND", 35.56, 160.02)
    sh.flag("+12V_IN", 45.72, 160.02)
    sh.flag("NIX_HV", 55.88, 160.02)
    sh.part(CP, "C101", OPEN, 76.2, 63.5, {"1": "+5V", "2": "GND"}, footprint=FP_TANT_A,
            fields=F("+5V bulk at the harness landing (value open)"))

    note(sh, "NIXIE HV MODULE 12 V SWITCH", "High side, off by default (R101 holds Q101 off; R104 holds Q102 off in "
         "reset). Values open until the module is measured", 106.68, 22.86)
    sh.part("nixie:Q_PMOS_GSD", "Q101", OPEN, 152.4, 63.5, {"1": "NIX12_G", "2": "+12V_IN", "3": "+12V_SW"},
            footprint=FP_SOT23, fields=F("Nixie module 12 V high-side switch (part open: V_DS, I_D, pulsed rating)"))
    sh.part(R, "R101", OPEN, 127.0, 58.42, {"1": "+12V_IN", "2": "NIX12_G"}, footprint=FP_R,
            fields=F("Q101 gate pull-up: off by default"))
    sh.part(C, "C102", OPEN, 114.3, 58.42, {"1": "+12V_IN", "2": "NIX12_G"}, footprint=FP_C,
            fields=F("Q101 gate-source: soft turn-on with R102 (inrush into the module)"))
    sh.part(R, "R102", OPEN, 127.0, 93.98, {"1": "NIX12_G", "2": "NIX12_D"}, footprint=FP_R,
            fields=F("Q101 gate series: sets the turn-on ramp with C102"))
    sh.part(NPN, "Q102", "MMBT3904", 152.4, 99.06, {"1": "NIX12_B", "2": "GND", "3": "NIX12_D"},
            footprint=FP_SOT23, fields=F("Level shifter for Q101's gate", "MMBT3904", rating="40 V NPN"))
    sh.part(R, "R103", "10k", 127.0, 124.46, {"1": "NIX12_EN", "2": "NIX12_B"}, footprint=FP_R,
            fields=F("Q102 base (as D8: 3.3 V drive)"))
    sh.part(R, "R104", "47k", 114.3, 124.46, {"1": "NIX12_B", "2": "GND"}, footprint=FP_R,
            fields=F("Q102 base pull-down: switch off while the RP2040 is in reset (D7)"))

    note(sh, "NIXIE HV MONITOR", "Divider to ADC0; ratio open until the module's maximum output is known. "
         "BAT54S clamp and reservoir as the dekatron ADC inputs", 248.92, 22.86)
    sh.part(R, "R105", OPEN, 269.24, 55.88, {"1": "NIX_HV", "2": "NIX_HV_SENSE"}, footprint=FP_AX0207,
            fields=F("HV monitor divider, upper (HV-rated, leaded)"))
    sh.part(R, "R106", OPEN, 269.24, 99.06, {"1": "NIX_HV_SENSE", "2": "GND"}, footprint=FP_R,
            fields=F("HV monitor divider, lower"))
    sh.part("Diode:BAT54S", "D101", "BAT54S", 302.26, 71.12, {"1": "GND", "2": "+3V3", "3": "NIX_HV_SENSE"},
            fields=F("NIX_HV_SENSE clamp to 3V3 / GND", "BAT54S", rating="30 V Schottky pair"))
    sh.part(C, "C103", "100nF", 330.2, 86.36, {"1": "NIX_HV_SENSE", "2": "GND"}, footprint=FP_C,
            fields=F("NIX_HV_SENSE ADC sampling reservoir (as the dekatron ADC inputs)", rating="25 V X7R"))

    note(sh, "TEST PADS", "Supplies and the switched 12 V", 218.44, 132.08)
    for i, net in enumerate(("+12V_IN", "+12V_SW", "NIX_HV", "+5V", "GND")):
        tp(sh, f"TP{101 + i}", net, 223.52 + i * 17.78, 152.4)
    return sh


LOGIC_GLOBALS = {"SDA", "SCL", "NIX_SPARE", "NIX12_EN", "NIX_HV_SENSE"} | {
    f"T{n}_{s}" for n in range(1, TUBES + 1) for s in ("X1", "X2", "X3", "X4", "LDP", "RDP")}

# Shift-register bit map: U302-U304 carry the BCD lines (two tubes each), U305-U306 the decimal
# points; U306 QE-QH spare. Firmware owns the mapping (frames are latched whole).
SR_OUTS = ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"]
SR_BITS = [[f"T{t}_X{b}" for t in (1, 2) for b in range(1, 5)],
           [f"T{t}_X{b}" for t in (3, 4) for b in range(1, 5)],
           [f"T{t}_X{b}" for t in (5, 6) for b in range(1, 5)],
           [f"T{t}_{d}" for t in (1, 2, 3, 4) for d in ("LDP", "RDP")],
           [f"T{t}_{d}" for t in (5, 6) for d in ("LDP", "RDP")] + ["NC"] * 4]


def build_logic(lib) -> Sheet:
    sh = Sheet("logic", "logic.kicad_sch", U("file:logic"), "A2", lib, f"/{ROOT_UUID}/{LOGIC_UUID}",
               global_nets=LOGIC_GLOBALS, title="Logic: RP2040-Zero, 74HCT595 chain, encoder / RTC / ES100 landings")

    note(sh, "RP2040-Zero (pin map: docs/hardware.md)", "Castellated, soldered by its edge pads; powered from "
         "+5V (NIX_LV)", 20.32, 22.86)
    nets = {"5V": "+5V", "GND": "GND", "3V3": "+3V3",
            "GP0": "NIX12_EN", "GP1": "NIX_SPARE", "GP2": "SDA", "GP3": "SCL", "GP4": "WWVB_SDA",
            "GP5": "WWVB_SCL", "GP6": "WWVB_EN", "GP7": "WWVB_IRQ", "GP8": "SR_OE", "GP9": "SR_LATCH",
            "GP10": "SR_CLK", "GP11": "SR_DATA", "GP12": "GP12", "GP13": "ENC_A", "GP14": "ENC_B",
            "GP15": "ENC_SW", "GP26": "NIX_HV_SENSE", "GP27": "GP27", "GP28": "GP28", "GP29": "GP29"}
    sh.part("nixie:RP2040-Zero", "U301", "RP2040-Zero", 101.6, 86.36, nets, textpos=(-12.7, -27.5),
            footprint=FP_ZERO, fields=F("Nixie controller MCU", "RP2040-Zero", "Waveshare", "headerless, castellated"))
    sh.part(CP, "C301", "10uF", 30.48, 58.42, {"1": "+5V", "2": "GND"}, footprint=FP_TANT_A,
            fields=F("+5V bulk at the module (as dekatron C301)", rating="16 V tantalum"))
    sh.part(C, "C302", "0.1uF", 45.72, 58.42, {"1": "+3V3", "2": "GND"}, footprint=FP_C,
            fields=F("3V3 bypass (as dekatron C302)", rating="50 V X7R"))
    note(sh, "TEST PADS", "Spare GPIOs, 3V3, shift-register lines", 20.32, 165.1)
    for i, net in enumerate(("GP12", "GP27", "GP28", "GP29", "+3V3", "SR_DATA", "SR_CLK", "SR_LATCH", "SR_OE")):
        tp(sh, f"TP{301 + i}", net, 25.4 + i * 15.24, 182.88)

    note(sh, "SHIFT REGISTERS: 5 x 74HCT595 at 5 V", "HCT: 2.0 V input threshold takes 3.3 V logic; outputs "
         "drive the K155ID1 TTL inputs. OE pulled up to 3V3 (outputs off in reset; K155ID1 inputs then float "
         "high = code 15 = dark)", 172.72, 22.86)
    sh.part(R, "R301", "10k", 182.88, 50.8, {"1": "+3V3", "2": "SR_OE"}, footprint=FP_R,
                fields=F("SR_OE pull-up: outputs off in reset; 10k against the RP2040's reset pull-down"))
    for k in range(5):
        ref = f"U{302 + k}"
        nets = {"VCC": "+5V", "GND": "GND", "~{SRCLR}": "+5V", "SRCLK": "SR_CLK", "RCLK": "SR_LATCH",
                "~{OE}": "SR_OE", "SER": "SR_DATA" if k == 0 else f"SR_Q{k}",
                "QH'": f"SR_Q{k + 1}" if k < 4 else "NC"}
        for o, net in zip(SR_OUTS, SR_BITS[k]):
            nets[o] = net
        x = 215.9 + k * 63.5
        sh.part("74xx:74HCT595", ref, "74HCT595", x, 81.28, nets, footprint=FP_SOIC16,
                fields=F(f"Shift register {k + 1} of 5", "74HCT595", rating="SOIC-16"))
        sh.part(C, f"C{303 + k}", "0.1uF", x - 20.32, 116.84, {"1": "+5V", "2": "GND"}, footprint=FP_C,
                fields=F(f"{ref} bypass", rating="50 V X7R"))

    note(sh, "ENCODER (front panel, harness)", "Panel-mount encoder wired to J301; pull-ups and debounce "
         "RC values open", 172.72, 139.7)
    sh.part("Connector_Generic:Conn_01x04", "J301", "ENCODER", 187.96, 172.72,
            {"1": "ENC_A", "2": "ENC_B", "3": "ENC_SW", "4": "GND"}, footprint=FP_WIRE4,
            fields=F("Harness to the panel-mount encoder: A, B, switch, common"))
    for i, net in enumerate(("ENC_A", "ENC_B", "ENC_SW")):
        x = 215.9 + i * 25.4
        sh.part(R, f"R{302 + i}", OPEN, x, 165.1, {"1": "+3V3", "2": net}, footprint=FP_R,
                fields=F(f"{net} pull-up"))
        sh.part(C, f"C{308 + i}", OPEN, x + 10.16, 180.34, {"1": net, "2": "GND"}, footprint=FP_C,
                fields=F(f"{net} debounce"))

    note(sh, "TIME MODULES (optional, harnesses)", "RTC (ZS-042) on the main bus; ES100 on its private bus. "
         "Pull resistors here so an unplugged module leaves defined levels", 297.18, 139.7)
    sh.part("Connector_Generic:Conn_01x04", "J302", "RTC", 309.88, 172.72,
            {"1": "+3V3", "2": "GND", "3": "SDA", "4": "SCL"}, footprint=FP_WIRE4,
            fields=F("Harness to the DS3231 module (ZS-042): jacks on its header by silk name"))
    sh.part("Connector_Generic:Conn_01x06", "J303", "WWVB", 360.68, 172.72,
            {"1": "+3V3", "2": "GND", "3": "WWVB_SDA", "4": "WWVB_SCL", "5": "WWVB_EN", "6": "WWVB_IRQ"},
            footprint=FP_WIRE6, fields=F("Harness to the ES100 carrier: jacks on its header by silk name"))
    for i, (net, up, func) in enumerate((("WWVB_SDA", True, "pull-up (unless on the carrier)"),
                                         ("WWVB_SCL", True, "pull-up (unless on the carrier)"),
                                         ("WWVB_IRQ", True, "pull-up (IRQ- is active low)"),
                                         ("WWVB_EN", False, "pull-down: ES100 in shutdown when unplugged or in reset"))):
        x = 391.16 + i * 15.24
        sh.part(R, f"R{305 + i}", OPEN, x, 165.1, {"1": "+3V3" if up else net, "2": net if up else "GND"},
                footprint=FP_R, fields=F(f"{net} {func}"))
    return sh


TUBES_GLOBALS = {"NIX_HV"} | {f"T{n}_{s}" for n in range(1, TUBES + 1) for s in ("X1", "X2", "X3", "X4", "LDP", "RDP")}


def build_tubes(lib) -> Sheet:
    sh = Sheet("tubes", "tubes.kicad_sch", U("file:tubes"), "A2", lib, f"/{ROOT_UUID}/{TUBES_UUID}",
               global_nets=TUBES_GLOBALS, title="Tubes: K155ID1 drivers, IN-14s, anode resistors, decimal points")
    note(sh, "SIX TUBE CHANNELS", "Tube 1 at the left as seen by the viewer. Anode resistor and decimal-point "
         "series resistors open until the Nixie module's output is measured (R = (V_HV - 145 V) / I)", 20.32, 22.86)
    for n in range(1, TUBES + 1):
        x0 = 20.32 + (n - 1) % 3 * 190.5          # 3 x 2 grid, tube 1 top left
        y0 = (n - 1) // 3 * 167.64
        note(sh, f"TUBE {n}", "", x0, y0 + 40.64)
        # nets keyed by pin number: the digit names "0"-"9" collide with pin numbers
        sh.part("nixie:K155ID1", f"U{200 + n}", "K155ID1", x0 + 25.4, y0 + 86.36,
                {**{num: f"T{n}_{name}" for name, num in K155_IN},
                 **{num: f"T{n}_K{d}" for d, num in K155_OUT.items()}, "5": "+5V", "12": "GND"},
                     footprint=FP_DIP16, fields=F(f"Tube {n} BCD decoder", "K155ID1", rating="DIP-16, 60 V outputs"))
        sh.part(C, f"C{200 + n}", "0.1uF", x0 + 7.62, y0 + 127.0, {"1": "+5V", "2": "GND"}, footprint=FP_C,
                fields=F(f"U{200 + n} bypass", rating="50 V X7R"))
        sh.part("nixie:IN-14", f"N{n}", "IN-14", x0 + 76.2, y0 + 86.36,
                {"1": f"T{n}_ANODE", "2": f"T{n}_LDP_K", "13": f"T{n}_RDP_K", "12": f"T{n}_K0",
                 **{str(d + 2): f"T{n}_K{d}" for d in range(1, 10)}},
                footprint=FP_IN14, fields=F(f"Tube {n}", "IN-14"))
        sh.part(R, f"R{200 + 10 * n}", OPEN, x0 + 99.06, y0 + 50.8, {"1": "NIX_HV", "2": f"T{n}_ANODE"},
                footprint=FP_AX0207, fields=F(f"Tube {n} anode resistor (value and rating open)"))
        for j, dp in enumerate(("LDP", "RDP")):
            y = y0 + 144.78 + j * 33.02
            base = 200 + 10 * n + 1 + 3 * j
            sh.part(NPN, f"Q{200 + 2 * n - 1 + j}", "MMBTA42", x0 + 76.2, y,
                    {"1": f"T{n}_{dp}_B", "2": "GND", "3": f"T{n}_{dp}_C"}, footprint=FP_SOT23,
                    fields=F(f"Tube {n} {dp} driver", "MMBTA42", rating="300 V NPN"))
            sh.part(R, f"R{base}", "10k", x0 + 50.8, y + 5.08, {"1": f"T{n}_{dp}", "2": f"T{n}_{dp}_B"},
                    footprint=FP_R, fields=F(f"Tube {n} {dp} base (as D8)"))
            sh.part(R, f"R{base + 1}", "47k", x0 + 63.5, y + 15.24, {"1": f"T{n}_{dp}_B", "2": "GND"},
                    footprint=FP_R, fields=F(f"Tube {n} {dp} base pull-down: point off with the 595 outputs off (D8)"))
            sh.part(R, f"R{base + 2}", OPEN, x0 + 99.06, y - 15.24, {"1": f"T{n}_{dp}_C", "2": f"T{n}_{dp}_K"},
                    footprint=FP_R, fields=F(f"Tube {n} {dp} series resistor (data sheet: point <= 0.3 mA)"))
    return sh


def build_root(lib) -> Sheet:
    sh = Sheet("root", f"{PROJECT}.kicad_sch", ROOT_UUID, "A4", lib, "/", title="Nixie controller / mount")
    sh.sheet("power", "power.kicad_sch", POWER_UUID, 40, 40, 60, 30, page="2")
    sh.sheet("logic", "logic.kicad_sch", LOGIC_UUID, 120, 40, 60, 30, page="3")
    sh.sheet("tubes", "tubes.kicad_sch", TUBES_UUID, 200, 40, 60, 30, page="4")
    sh.text("Sheets: power, logic, tubes. Inter-sheet nets are global labels. Values marked _open_ wait "
            "for the Nixie HV module measurements (docs/hardware.md).", 40, 100, 2)
    return sh


# --------------------------------------------------------------------------------------
# Project file, tables
# --------------------------------------------------------------------------------------


def project_json() -> str:
    def nc(name):
        return {"name": name, "clearance": 0.2, "track_width": 0.3, "via_diameter": 0.8, "via_drill": 0.4,
                "priority": 0, "bus_width": 12, "line_style": 0, "wire_width": 6}
    pro = {
        "board": {"design_settings": {"defaults": {}, "rule_severities": {}}, "layer_presets": [], "viewports": []},
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3},
        # Nixie HV classes; clearances open (placeholders), set before layout
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
                 "priority": 2147483647, "bus_width": 12, "line_style": 0, "wire_width": 6},
                nc("NHV"), nc("NCATH")],
            "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None,
            "netclass_patterns": [
                {"netclass": "NHV", "pattern": "NIX_HV"},
                {"netclass": "NHV", "pattern": "*_ANODE"},
                {"netclass": "NCATH", "pattern": "*T?_K?"},
                {"netclass": "NCATH", "pattern": "*DP_K"},
                {"netclass": "NCATH", "pattern": "*DP_C"},
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
