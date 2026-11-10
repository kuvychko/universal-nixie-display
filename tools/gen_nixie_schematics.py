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

Reuses the core of tools/gen_schematics.py (parser, symbol loading, Sheet). Connectivity style:
every pin gets a short stub ending in a net label, power symbol or no-connect (Sheet.part), so the
netlist is exactly the `nets` dictionaries below. Values not yet sourced are written as OPEN
("_open_"); they come from the Nixie HV module measurements (docs/hardware.md, "Nixie board
electrical design").

Usage:  python tools/gen_nixie_schematics.py [--kicad-share "C:/Program Files/KiCad/10.0/share/kicad"]
"""
from __future__ import annotations

import argparse
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
# Design-time part numbers (2026-11-07), applied to every symbol like the dekatron board's frozen
# BOM: the exact MPNs already ordered for the dekatron board (hardware/dekatron/Cart_Oct08_0432PM.xls)
# wherever the Nixie part has the same value, rating and footprint, plus the Nixie-only parts.
# Not listed: kit resistors (generic 1206, by value), _open_ values, part numbers still to be picked
# at ordering, wire pads and test pads. Replace with the Nixie order once it is placed.
NIXIE_PARTS = [
    ("Yageo", "CC1206JPX7R9BB104", "C103 C201 C202 C203 C302 C303 C304"),   # 0.1 uF 50 V X7R 1206
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
    sh.part(CP, "C101", "10uF", 76.2, 63.5, {"1": "+5V", "2": "GND"}, footprint=FP_TANT_A,
            fields=F("+5V bulk at the harness landing (user 2026-11-07: as C301)", rating="16 V tantalum"))

    note(sh, "NIXIE HV MODULE 12 V SWITCH", "High side, off by default (R101 holds Q101 off; R104 holds Q102 off in "
         "reset). Soft start into the module's 470 uF: hardware/nixie/simulation/nix12_switch.cir", 106.68, 22.86)
    sh.part("Transistor_FET:Q_PMOS_GDS", "Q101", "IPD50P04P4L-11", 152.4, 63.5,
            {"1": "NIX12_G", "2": "+12V_SW", "3": "+12V_IN"}, footprint=gs.FP_DPAK,
            fields=F("Nixie module 12 V high-side switch with soft start", "IPD50P04P4L-11", "Infineon",
                     "-40 V, 17.2 mohm max at VGS -4.5 V, VGS +5/-16 V"))
    sh.part(R, "R101", "47k", 127.0, 58.42, {"1": "+12V_IN", "2": "NIX12_G"}, footprint=FP_R,
            fields=F("Q101 gate pull-up: off by default. With R102: VGS -6 V at 12 V, -12 V at the 24 V clamp"))
    sh.part(C, "C102", "3.3uF", 114.3, 58.42, {"1": "+12V_IN", "2": "NIX12_G"}, footprint=FP_C,
            fields=F("Q101 gate-source: soft turn-on with R101/R102; holds Q101 off on hot-plug", rating="25 V X7R"))
    sh.part(R, "R102", "47k", 127.0, 93.98, {"1": "NIX12_G", "2": "NIX12_D"}, footprint=FP_R,
            fields=F("Q101 gate series: sets the turn-on ramp with C102"))
    sh.part(NPN, "Q102", "MMBT3904", 152.4, 99.06, {"1": "NIX12_B", "2": "GND", "3": "NIX12_D"},
            footprint=FP_SOT23, fields=F("Level shifter for Q101's gate", "MMBT3904", rating="40 V NPN"))
    sh.part(R, "R103", "10k", 127.0, 124.46, {"1": "NIX12_EN", "2": "NIX12_B"}, footprint=FP_R,
            fields=F("Q102 base (as D8: 3.3 V drive)"))
    sh.part(R, "R104", "47k", 114.3, 124.46, {"1": "NIX12_B", "2": "GND"}, footprint=FP_R,
            fields=F("Q102 base pull-down: switch off while the RP2040 is in reset (D7)"))

    note(sh, "NIXIE HV MONITOR", "Divider to ADC0: 3.3 V at about 278 V. Also the bleeder (below 30 V in about "
         "2-3 s, measured). BAT54S clamp and reservoir as the dekatron ADC inputs", 248.92, 22.86)
    sh.part(R, "R105", "1M", 269.24, 55.88, {"1": "NIX_HV", "2": "NIX_HV_SENSE"}, footprint=FP_AX0411,
            fields=F("HV monitor divider, upper; bleeder", "HHV-50FT-52-1M", rating="HHV-50: 0.5 W"))
    sh.part(R, "R106", "12k", 269.24, 99.06, {"1": "NIX_HV_SENSE", "2": "GND"}, footprint=FP_R,
            fields=F("HV monitor divider, lower", rating="1 %"))
    sh.part("Diode:BAT54S", "D101", "BAT54S", 302.26, 71.12, {"1": "GND", "2": "+3V3", "3": "NIX_HV_SENSE"},
            fields=F("NIX_HV_SENSE clamp to 3V3 / GND", "BAT54S", rating="30 V Schottky pair"))
    sh.part(C, "C103", "100nF", 330.2, 86.36, {"1": "NIX_HV_SENSE", "2": "GND"}, footprint=FP_C,
            fields=F("NIX_HV_SENSE ADC sampling reservoir (as the dekatron ADC inputs)", rating="50 V X7R"))

    note(sh, "TEST PADS", "Supplies and the switched 12 V", 218.44, 132.08)
    for i, net in enumerate(("+12V_IN", "+12V_SW", "NIX_HV", "+5V", "GND")):
        tp(sh, f"TP{101 + i}", net, 223.52 + i * 17.78, 152.4)
    return sh


DRV = ("DATA", "CLK", "LE", "BL")           # RP2040 -> CD40109B -> HV5622 lines
LOGIC_GLOBALS = {"SDA", "SCL", "NIX_SPARE", "NIX12_EN", "NIX_HV_SENSE", "+12V_IN", "+12V_LOGIC"} | {
    f"DRV12_{s}" for s in DRV}


def build_logic(lib) -> Sheet:
    sh = Sheet("logic", "logic.kicad_sch", U("file:logic"), "A2", lib, f"/{ROOT_UUID}/{LOGIC_UUID}",
               global_nets=LOGIC_GLOBALS,
               title="Logic: RP2040-Zero, level shifter, encoder, time modules")

    note(sh, "RP2040-Zero (pin map: docs/hardware.md)", "Castellated, soldered by its edge pads; powered from "
         "+5V (NIX_LV)", 20.32, 22.86)
    nets = {"5V": "+5V", "GND": "GND", "3V3": "+3V3",
            "GP0": "NIX12_EN", "GP1": "NIX_SPARE", "GP2": "SDA", "GP3": "SCL", "GP4": "WWVB_SDA",
            "GP5": "WWVB_SCL", "GP6": "WWVB_EN", "GP7": "WWVB_IRQ", "GP8": "DRV_BL", "GP9": "DRV_LE",
            "GP10": "DRV_CLK", "GP11": "DRV_DATA", "GP12": "GP12", "GP13": "ENC_A", "GP14": "ENC_B",
            "GP15": "ENC_SW", "GP26": "NIX_HV_SENSE", "GP27": "GP27", "GP28": "GP28", "GP29": "GP29"}
    sh.part("nixie:RP2040-Zero", "U301", "RP2040-Zero", 101.6, 86.36, nets, textpos=(-12.7, -27.5),
            footprint=FP_ZERO, fields=F("Nixie controller MCU", "RP2040-Zero", "Waveshare", "headerless, castellated"))
    sh.part(CP, "C301", "10uF", 30.48, 58.42, {"1": "+5V", "2": "GND"}, footprint=FP_TANT_A,
            fields=F("+5V bulk at the module (as dekatron C301)", rating="16 V tantalum"))
    sh.part(C, "C302", "0.1uF", 45.72, 58.42, {"1": "+3V3", "2": "GND"}, footprint=FP_C,
            fields=F("3V3 bypass (as dekatron C302)", rating="50 V X7R"))
    note(sh, "TEST PADS", "Spare GPIOs, 3V3, 12 V logic, driver lines (3.3 V side)", 20.32, 165.1)
    for i, net in enumerate(("GP12", "GP27", "GP28", "GP29", "+3V3", "+12V_LOGIC", "DRV_DATA", "DRV_CLK",
                             "DRV_LE", "DRV_BL")):
        tp(sh, f"TP{301 + i}", net, 25.4 + i * 15.24, 182.88)

    note(sh, "LEVEL SHIFTER: CD40109B, 3.3 V -> 12 V", "HV5622 inputs need V_IH >= VDD - 2 V. Enables tied to "
         "3V3. DRV_BL pulled down: all tube outputs off while the RP2040 is in reset (BL low, POL high)",
         172.72, 22.86)
    sh.part("Logic_LevelTranslator:CD40109BPW", "U302", "CD40109B", 215.9, 81.28,
            {"1": "+3V3", "16": "+12V_LOGIC", "8": "GND", "2": "+3V3", "7": "+3V3", "9": "+3V3", "15": "+3V3",
             "3": "DRV_DATA", "4": "DRV12_DATA", "6": "DRV_CLK", "5": "DRV12_CLK",
             "10": "DRV_LE", "11": "DRV12_LE", "14": "DRV_BL", "13": "DRV12_BL"},
            footprint=FP_SOP16_NS, fields=F("3.3 V -> 12 V for the HV5622 inputs", "CD40109BNSRE4", "TI",
                                            "VCC/VDD 3-18 V, SOP-16 (NS) 5.3 mm"))
    sh.part(C, "C303", "0.1uF", 195.58, 116.84, {"1": "+12V_LOGIC", "2": "GND"}, footprint=FP_C,
            fields=F("U302 VDD bypass", rating="50 V X7R"))
    sh.part(C, "C304", "0.1uF", 210.82, 116.84, {"1": "+3V3", "2": "GND"}, footprint=FP_C,
            fields=F("U302 VCC bypass", rating="50 V X7R"))
    sh.part(R, "R301", "10k", 241.3, 116.84, {"1": "DRV_BL", "2": "GND"}, footprint=FP_R,
            fields=F("DRV_BL pull-down: tubes blank while the RP2040 is in reset"))
    sh.part(R, "R310", "100k", 256.54, 116.84, {"1": "DRV12_BL", "2": "GND"}, footprint=FP_R,
            fields=F("DRV12_BL pull-down: tubes blank while 3V3 is absent (U302 outputs then high-impedance)"))

    note(sh, "12 V LOGIC RAIL", "HV5622 / CD40109B VDD. HV5622 VDD abs max 15 V, below the 24 V TVS clamp on "
         "the 12 V input: series resistor and 13 V zener (12.35-13.65 V)", 345.44, 22.86)
    sh.part(R, "R309", "470", 355.6, 63.5, {"1": "+12V_IN", "2": "+12V_LOGIC"}, footprint=FP_R,
            fields=F("12 V logic rail series resistor: ~0.2 V at ~0.45 mA average; 0.23 W at the 24 V clamp",
                     rating="1206, 0.25 W"))
    sh.part(DZ, "D301", "MMSZ5243B", 370.84, 81.28, {"1": "+12V_LOGIC", "2": "GND"}, angle=90,
            footprint=FP_SOD123, fields=F("12 V logic rail clamp", "MMSZ5243B", rating="13 V, 500 mW, SOD-123"))
    sh.part(C, "C305", "10uF", 386.08, 81.28, {"1": "+12V_LOGIC", "2": "GND"}, footprint=FP_C,
            fields=F("12 V logic reservoir: shift bursts", rating="25 V X7R"))
    sh.flag("+12V_LOGIC", 401.32, 101.6)

    note(sh, "ENCODER (front panel, harness)", "Bourns PEC11R wired to J301 (user, 2026-11-07). Filter per "
         "its data sheet (Suggested Filter Circuit): 10k pull-up, 10k series, 0.01 uF; the push switch "
         "the same", 172.72, 139.7)
    sh.part("Connector_Generic:Conn_01x04", "J301", "ENCODER", 187.96, 172.72,
            {"1": "ENC_A_RAW", "2": "ENC_B_RAW", "3": "ENC_SW_RAW", "4": "GND"}, footprint=FP_WIRE4,
            fields=F("Harness to the panel-mount encoder (PEC11R): A, B, switch, common C and switch 2"))
    for i, net in enumerate(("ENC_A", "ENC_B", "ENC_SW")):
        x = 215.9 + i * 25.4
        sh.part(R, f"R{302 + i}", "10k", x, 165.1, {"1": "+3V3", "2": net + "_RAW"}, footprint=FP_R,
                fields=F(f"{net} pull-up (PEC11R suggested filter)"))
        sh.part(R, f"R{311 + i}", "10k", x + 7.62, 165.1, {"1": net + "_RAW", "2": net}, footprint=FP_R,
                fields=F(f"{net} series: filter discharge through 10k, not the contact (PEC11R suggested filter)"))
        sh.part(C, f"C{308 + i}", "0.01uF", x + 15.24, 180.34, {"1": net, "2": "GND"}, footprint=FP_C,
                fields=F(f"{net} debounce, 0.1 ms with the series 10k (PEC11R suggested filter)", rating="25 V X7R"))

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


TUBES_GLOBALS = {"NIX_HV", "+12V_LOGIC"} | {f"DRV12_{s}" for s in DRV}
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
    sh = Sheet("tubes", "tubes.kicad_sch", U("file:tubes"), "A2", lib, f"/{ROOT_UUID}/{TUBES_UUID}",
               global_nets=TUBES_GLOBALS, title="Tubes: HV5622 drivers, IN-14s, resistors")
    note(sh, "TUBE DRIVERS: 3 x HV5622 (220 V open drain)", "Tube 1 at the left as seen by the viewer. Chain "
         "U201 -> U202 -> U203, 96 bits latched whole (LE). Outputs assigned from the PCB geometry (HV_MAP in "
         "tools/gen_nixie_schematics.py, table in docs/hardware.md); 1-5 and 30-32 spare. Firmware owns the map", 20.32, 22.86)
    for k in range(CHIPS):
        x0 = 20.32 + k * 190.5
        ta, tb = 2 * k + 1, 2 * k + 2
        nets = {HV5622_OUT[o]: (f"T{ta if HV_MAP[o][0] == 'a' else tb}_{HV_MAP[o][1]}" if o in HV_MAP else "NC")
                for o in range(1, 33)}
        nets.update({"30": "+12V_LOGIC", "29": "GND", "27": "+12V_LOGIC", "28": "DRV12_CLK", "31": "DRV12_LE",
                     "33": "DRV12_BL", "32": "DRV12_DATA" if k == 0 else f"DRV12_D{k}",
                     "23": f"DRV12_D{k + 1}" if k < CHIPS - 1 else "NC"})
        sh.part("nixie:HV5622", f"U{201 + k}", "HV5622", x0 + 30.48, 132.08, nets, footprint=FP_PQFP44,
                fields=F(f"Tube {ta}/{tb} cathode and decimal-point driver", "HV5622PG-G", "Microchip",
                         "220 V outputs, PQFP-44 0.8 mm"))
        sh.part(C, f"C{201 + k}", "0.1uF", x0 + 7.62, 195.58, {"1": "+12V_LOGIC", "2": "GND"}, footprint=FP_C,
                fields=F(f"U{201 + k} VDD bypass", rating="50 V X7R"))
        for j, n in enumerate((ta, tb)):
            y0 = 66.04 + j * 121.92
            note(sh, f"TUBE {n}", "", x0 + 88.9, y0 - 25.4)
            sh.part("nixie:IN-14", f"N{n}", "IN-14", x0 + 132.08, y0 + 20.32,
                    {"1": f"T{n}_ANODE", "2": f"T{n}_LDP_K", "13": f"T{n}_RDP_K", "12": f"T{n}_K0",
                     **{str(d + 2): f"T{n}_K{d}" for d in range(1, 10)}},
                    footprint=FP_IN14, fields=F(f"Tube {n}", "IN-14"))
            sh.part(R, f"R{200 + 10 * n}", "12k", x0 + 160.02, y0 - 10.16, {"1": "NIX_HV", "2": f"T{n}_ANODE"},
                    footprint=FP_AX0207,
                    fields=F(f"Tube {n} anode resistor: (175 V - 145 V) / 2.5 mA, 75 mW",
                             rating="MRS25: 0.6 W, 350 V, 1 %, 50 ppm/K"))
            for i, dp in enumerate(("LDP", "RDP")):
                sh.part(R, f"R{200 + 10 * n + 1 + i}", "150k", x0 + 99.06 + i * 12.7, y0 + 60.96,
                        {"1": f"T{n}_{dp}_D", "2": f"T{n}_{dp}_K"}, footprint=FP_R,
                        fields=F(f"Tube {n} {dp} series resistor: starting value, point <= 0.3 mA; "
                                 "check at bring-up"))
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
