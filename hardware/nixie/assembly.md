# Nixie controller/mount — assembly and bring-up checklist

> [!WARNING]
> High voltage (~175 V), at your own risk. Read the [README safety section](../../README.md#safety-read-this-first)
> before Stage 4.

The board is populated one section at a time, with the [bring-up](../../docs/bringup.md#nixie-subsystem-phase-2)
step for that section run before the next one is soldered, as on the
[dekatron board](../dekatron/assembly.md). Side A (F.Cu) carries every part except the tubes;
the six IN-14s go on side B last, once everything on side A has passed its gate, because the
board no longer lies flat on side B once they are fitted. Within each stage the order is
fine-pitch ICs, then small passives batched by part, then discretes, then through-hole.

The RTC (ZS-042) and the WWVB receiver (ES100 carrier) are not on the board: they are mounted in
the enclosure and wired to J302 and J303 there (Stage 6), as is the front-panel encoder (J301).
Their on-board pull resistors and filter are fitted earlier, at Stage 3, while side A is still
easy to reach.

Every part comes from [`bom.csv`](bom.csv). Each line below is one reel or bag: value, part
number, package, references. Rules:

* **Batch by part number, not by value.** Three different 12k parts: R106 (`ERJ-8ENF1202V`, 1 %
  1206), R108 (12k 1 % 1206, kit only if the kit is 1 %) and the six MRS25 anode resistors
  (through-hole). Three different 10 µF parts: C101 and C301 are 16 V tantalum (polarized, 5 V
  rail); C305 is 25 V X7R ceramic on the 12 V logic rail and must not be a tantalum.
* **Unmarked 1206 capacitors:** 0.1 µF, 0.01 µF, 3.3 µF and 10 µF all look alike. Open one bag at
  a time.
* **Same package, different part:** Q102 (MMBT3904) and D101 (BAT54S) are both SOT-23; check the
  marking.
* **Kit resistors** (no part number in the BOM) are batched by value. R309 (470 Ω) dissipates
  0.23 W at the 24 V input clamp: use it from the kit only if the kit part is rated ≥ 0.25 W.
* **R305-R308 (ES100 pulls) are `_open_`:** values from the kit, or not fitted, depending on what
  the ES100 carrier already has (decided at "Before starting").
* **Decimal-point resistors:** fit tube 1's pair (R211, R212) first; the other ten follow the value
  chosen at Gate 5a.
* Test points (`TP…`) are bare plated pads; nothing to fit.
* Clean the flux after each stage (IPA). The board takes no clearance credit for solder mask or
  coating, so flux left between the cathode tracks (0.25 mm) or on the HV side is a leakage path.

Record readings in the blanks, then copy the verdict into the Result column of
[bringup.md](../../docs/bringup.md#nixie-subsystem-phase-2) and the raw data into
`characterization/nixie/` as dated files.

## Before starting

- [ ] Bare board inspected: no visible shorts or damage, silkscreen legible
- [ ] Bare board, meter: NIX_HV (TP103) to GND (TP105) open, and to +12V_IN (TP101) open
- [ ] Tools: microscope, flux, solder wick, fine iron tip, hot air (for the PQFP-44s if wanted),
  IPA, ESD mat and strap
- [ ] All parts on hand and checked against `bom.csv` and `order_scratch.csv`, including the 0.1 µF
  taken from the dekatron leftovers (C104)
- [ ] Nixie HV module: trimmer set to **175 V** on the bench and fixed with glue (never toward its
  maximum: it may have no overvoltage protection; [hardware.md](../../docs/hardware.md#nixie-board-electrical-design-phase-1a-draft-2026-10-26), HV limit)
- [ ] ZS-042 (RTC): header pin order and silk names read off the board ___; its I2C pull-ups:
  present? ___ decision (remove, or count in parallel with the dekatron board's 4.7k pair) ___;
  coin-cell charging path (resistor + diode from VCC): present? ___ removed if a CR2032 is used ___
- [ ] ES100 carrier: header pin order and silk names ___; pull-ups on SDA / SCL / IRQ-, and any pull
  on EN, as found ___. Values chosen for R305 (SDA up) ___, R306 (SCL up) ___, R307 (IRQ- up) ___,
  R308 (EN down) ___ (or "not fitted"); record them in [hardware.md](../../docs/hardware.md#time-sources)
- [ ] Tube height above the cover decided (still `_open_` in hardware.md): it sets where the tube
  leads are cut at Stage 5
- [ ] Bring-up firmware for the Nixie RP2040 (to be written, `firmware/nixie-bringup/`, as the
  [dekatron's](../../firmware/dekatron-bringup/README.md)). Needed from Gate 3: `NIX12_EN` low at boot
  and on only by command with an auto-off timeout; `NIX12_EN` dropped above 200 V on `NIX_HV_SENSE`
  (threshold settable in a test build); blank frame shifted and latched before `BL` is released;
  frames shifted at ≤ 1 MHz, data shifted on the falling clock edge, `LE` idle low and pulsed per
  frame; readback compared on GP12; one-output walk; PWM on `DRV_BL`; ADC status; I2C probe of the
  ES100 on I2C0

## Stage 0 — drivers and level shifter on the bare board

The three HV5622s are the board's only fine-pitch parts (PQFP-44, 0.8 mm, no exposed pad). They
go on first, with nothing fitted around them yet. U302 follows.

- [ ] HV5622, `HV5622PG-G`, PQFP-44: U201, U202, U203 (3; no spare ordered): pin 1 aligned, all four
  sides tacked and checked before soldering the rest
- [ ] CD40109B, `CD40109BNSRE4`, SOP-16 (5.3 mm body): U302, pin 1 aligned

**Gate 0**

- [ ] No bridges between pins on any of the four chips (microscope, every side)
- [ ] No pin lifted: each lead wetted to its pad (microscope)
- [ ] Each HV5622: VDD to VSS not shorted (meter)
- [ ] Flux cleaned, especially between the HVOUT pins

## Stage 1 — 5 V, 3.3 V, MCU, blanking pull-downs

The 5 V landing, the RP2040-Zero (its own regulator makes +3V3), U302's 3.3 V bypass and the two
`BL` pull-downs, so the tubes-dark default is in place as soon as the MCU is fitted.

Capacitors

- [ ] 0.1 µF 50 V X7R, `CC1206JPX7R9BB104`, 1206: C302, C304 (2)
- [ ] 10 µF 16 V tantalum, `F911C106MAAAJ6`, 3216-18: C101, C301 (2, **polarized**, + to +5V)

Resistors, 1206

- [ ] 10k (kit): R301 (`DRV_BL` pull-down)
- [ ] 100k (kit): R310 (`DRV12_BL` pull-down)

MCU module

- [ ] RP2040-Zero: U301, USB-C toward the right board edge, castellations centred on their pads.
  As on the dekatron board: tack two opposite corners, check it sits level, then stand a cut-off
  1/4 W resistor lead in each castellation, solder it to the board pad and the castellation, trim
  flush. Check each joint with a meter, castellation to its board trace

Harness

- [ ] NIX_LV: J101 (harness to the dekatron board's J302, or bench leads for now): +5V, GND, SDA,
  SCL, GND, NIX_SPARE, through its cable-tie hole

**Gate 1 — bring-up step 1** (acceptance: rails in tolerance, tubes-dark default in reset)

- [ ] Flux cleaned
- [ ] Unpowered, to GND (not a short): +5V (TP104) ___ Ω, +3V3 (TP305) ___ Ω
- [ ] Bench 5 V on J101, current limit set low: ___ mA
- [ ] +5V (TP104) ___ V; +3V3 (TP305) ___ V; input current ___ mA
- [ ] RP2040-Zero enumerates over USB (BOOTSEL)
- [ ] In BOOTSEL (RP2040 not running code): `DRV_BL` (TP310) ___ V (≈ 0 V, R301)
- [ ] USB only, J101 unpowered: +5V (TP104) ___ V (noted only; on the clock, the dekatron board's
  ideal diode U104 stops this reaching its rail)
- [ ] Result copied into bringup.md step 1

## Stage 2 — 12 V input, 12 V logic rail, module switch

The 12 V landing, the HV5622 / CD40109B logic supply (R309, D301, C305 and the chip bypasses),
the module's 12 V switch with its soft start, and the switched-12 V sense. The module is not
connected yet (J103 and J104 stay empty until Stage 4).

Capacitors, 1206

- [ ] 0.1 µF 50 V X7R, `CC1206JPX7R9BB104`: C104, C201, C202, C203, C303 (5)
- [ ] 3.3 µF 25 V X7R, `CGA5L1X7R1E335K160AC`: C102
- [ ] 10 µF 25 V X7R, `C1206C106K3RAC7210`: C305 (ceramic, not the tantalum)

Resistors, 1206

- [ ] 47k (kit): R101, R102, R104 (3)
- [ ] 10k (kit): R103
- [ ] 100k (kit): R107
- [ ] 12k 1 % (kit if 1 %): R108
- [ ] 470 Ω, ≥ 0.25 W (kit if rated): R309

Discretes

- [ ] MMBT3904, SOT-23: Q102
- [ ] MMSZ5243B (13 V), SOD-123: D301 (cathode band)
- [ ] IPD50P04P4L-11, `IPD50P04P4L11ATMA2`, TO-252: Q101

Harness

- [ ] 12V_IN: J102 (harness to the dekatron board's NIX_12V, or bench leads for now)

**Gate 2 — bring-up step 2** (acceptance: logic rail in range; switch off by default and on only
by command)

- [ ] Flux cleaned
- [ ] Unpowered, to GND (not a short): +12V_IN (TP101) ___ Ω, +12V_SW (TP102) ___ Ω, +12V_LOGIC (TP306) ___ Ω
- [ ] Bench 12 V on J102 (current limit low ___ mA) and 5 V on J101
- [ ] +12V_IN (TP101) ___ V; +12V_LOGIC (TP306) ___ V (design ≈ 0.2 V below +12V_IN: R309 at
  ≈ 0.45 mA; HV5622 VDD range 10.8-13.2 V); 12 V input current ___ mA
- [ ] RP2040 in BOOTSEL: +12V_SW (TP102) ___ V (≈ 0 V: R101 holds Q101 off, R104 holds Q102 off)
- [ ] 12 V applied with 5 V absent: +12V_SW ___ V (≈ 0 V); `DRV12_BL` (at an HV5622 `BL` pin)
  ___ V, held low by R310
- [ ] Bring-up firmware flashed. `NIX12_EN` on, no load: +12V_SW ___ V; NIX12_SENSE (TP302) ___ V
  (design 1.29 V at 12 V) and the firmware's reading ___ V
- [ ] `NIX12_EN` off: +12V_SW falls back toward 0 V
- [ ] Result copied into bringup.md step 2

## Stage 3 — driver logic, readback, encoder filter, time-module pulls (no HV)

Everything left on side A except the HV parts: the readback divider, the encoder filter and the
ES100 pulls. Then the drivers are exercised with the logic rail up and no HV.

Capacitors, 1206

- [ ] 0.01 µF 25 V X7R, `12063C103JAT2A`: C308, C309, C310 (3)

Resistors, 1206

- [ ] 100k (kit): R314
- [ ] 33k (kit): R315
- [ ] 10k (kit): R302, R303, R304, R311, R312, R313 (6, encoder filter)
- [ ] R305-R308 as decided at "Before starting" (or left empty): R305 ___, R306 ___, R307 ___, R308 ___

**Gate 3 — bring-up step 3** (acceptance: frames shift, latch and read back; every output
switches; tubes dark at start-up)

- [ ] Flux cleaned (cathode area especially)
- [ ] 12 V and 5 V on, J104 empty (no HV), tubes not fitted
- [ ] At boot: `DRV_BL` (TP310) low until the firmware has shifted and latched a blank frame
- [ ] TP307 (`DRV_DATA`), TP308 (`DRV_CLK`), TP309 (`DRV_LE`) during a frame (scope): clock ≤ 1 MHz,
  data changes on the rising edge, `LE` pulse after the 96th clock ___
- [ ] Readback: a frame shifted twice returns on GP12 unchanged (several patterns: all 0, all 1,
  walking 1) ___. `DRV_DOUT` (TP301) high ___ V (design 2.43-3.39 V), low ___ V (≤ 0.25 V)
- [ ] Output walk, one output on at a time: a 10k from +3V3 (TP305) to the pad under test reads
  ≈ 0 V when its output is on and ≈ 3.3 V when off (HV5622 off-state leakage ≤ 10 µA). The 60
  digit cathodes at the tube footprint pads; the 12 decimal-point outputs at the HV5622-side pad of
  R2n1 / R2n2 (not fitted yet; find the pad by continuity). Against the HV_MAP table in
  [hardware.md](../../docs/hardware.md#nixie-board-electrical-design-phase-1a-draft-2026-10-26):
  tube 1 ___ 2 ___ 3 ___ 4 ___ 5 ___ 6 ___. A pad that also goes low for a neighbour's output is
  a bridge at the HV5622
- [ ] `BL` low with a frame latched: every pad reads ≈ 3.3 V
- [ ] PWM on `DRV_BL`: TP310 and the HV5622 side follow (scope) ___
- [ ] Encoder filter: ENC_A / ENC_B / ENC_SW at 3.3 V idle; J301 pins 1-3 to pin 4 (GND) shorted
  briefly with a lead: each GPIO goes low ___
- [ ] ES100 lines with nothing on J303: `WWVB_EN` low; `WWVB_IRQ`, `WWVB_SDA`, `WWVB_SCL` high where
  their pulls are fitted ___
- [ ] Result copied into bringup.md step 3

## Stage 4 — HV monitor, anode resistors, HV module (no tubes)

> [!WARNING]
> From here the board carries ~175 V. Rated probes, one hand, nothing touched while powered.

Capacitors, discretes

- [ ] 0.1 µF 50 V X7R, `CC1206JPX7R9BB104`, 1206: C103
- [ ] BAT54S, `BAT54S RFG`, SOT-23: D101

Resistors

- [ ] 12k 1 %, `ERJ-8ENF1202V`, 1206: R106
- [ ] 1M HHV-50, `HHV-50FT-52-1M`, through-hole: R105
- [ ] 12k MRS25, `MRS25000C1202FRP00`, through-hole: R210, R220, R230, R240, R250, R260 (6)
- [ ] Before J104 is wired, unpowered: NIX_HV (TP103) to GND ___ Ω (≈ 1.01 MΩ, R105 + R106)

Harness to the module

- [ ] 12V_MODULE: J103 (+12V_SW, GND) to the module's 12 V input
- [ ] HV_MODULE: J104 (NIX_HV, GND) from the module's output; HV-insulated wire (as the dekatron's
  anode wire, e.g. UL1015)

**Gate 4 — bring-up step 4** (acceptance: HV at the setpoint, monitor agrees with the meter,
firmware cut-off works, HV off by default)

Safety first:

- [ ] Discharge check before every touch: NIX_HV (TP103) below 30 V. R105 (1 MΩ) is the bleeder:
  the module alone fell below 30 V in about 2-3 s through 1 MΩ on the bench
  ([log](../../characterization/nixie/2026-11-01_hv_module.md)); here ___ s
- [ ] Flux cleaned, HV side especially

HV off by default:

- [ ] 12 V and 5 V on, RP2040 in BOOTSEL: NIX_HV ___ V (0 V); +12V_SW ___ V (0 V)
- [ ] RP2040 flashed while 12 V is on: NIX_HV stays at 0 V throughout ___

HV on (bring-up firmware, auto-off set):

- [ ] Switch-on ramp (scope on +12V_SW, the 12 V current through a 1 Ω shunt as on the bench):
  delay after enable ___ ms, 10-90 % ramp ___ ms, current peak ___ A (simulation: 34-57 ms,
  5.5-7.3 ms, 1.6-1.9 A with the dekatron PTC in the path)
- [ ] NIX_HV (TP103, meter) ___ V (175 V set); firmware `NIX_HV_SENSE` ___ V (≈ 2.08 V at 175 V,
  ratio 84.3); NIX12_SENSE ___ V
- [ ] 12 V input current, no tubes ___ mA (bench: 13 mA at 176 V into 1 MΩ)
- [ ] Ripple on TP103 ___; overshoot at switch-on ___
- [ ] Cut-off: test build with the 200 V threshold scaled down below 175 V: `NIX12_EN` drops and
  HV decays ___; threshold restored to 200 V
- [ ] Off: NIX_HV below 30 V in ___ s
- [ ] Result copied into bringup.md step 4

## Stage 5 — tubes

Tubes go on side B with their plastic lead spacers, standing vertical, leads through to side A
and soldered there. Pin 1 (anode, square pad) is at the back; the tube's front (between digits 5
and 6, the arrow in the glass bottom marks pin 1) faces the board's front edge. The footprint was
checked against the spacer on a 1:1 print (2026-11-11). From here, rest the board on standoffs in
its M3 holes, never on the tubes.

- [ ] Optional, before soldering: each tube on the bench from the module at 175 V through a 12k
  anode resistor, each cathode to GND in turn: all digits and points light ___ (the leads cannot
  be unsoldered without shortening them)

**5a — tube 1 and its decimal-point resistors**

- [ ] 150k (kit), 1206: R211, R212 (starting value)
- [ ] N1: spacer fitted, height as decided, orientation checked, leads soldered on side A and trimmed
- [ ] Flux cleaned around the lead ring

**Gate 5a — bring-up step 5**

- [ ] Discharge checked; HV on
- [ ] Strike: each digit 0-9 lights fully at 175 V ___ (IN-14 ignition ≤ 170 V)
- [ ] Digit current: voltage across R210 ___ V with one digit lit (design ≈ 30 V: 2.5 mA,
  (175 − 145) V / 12k; IN-14 ≤ 2.5 mA)
- [ ] Decimal points: voltage across R211 / R212 with the point alone ___ V and with a digit lit
  ___ V. Acceptance ≤ 0.3 mA alone (≤ 45 V across 150k); design ≈ 0.27 mA alone, ≈ 0.09 mA beside
  a digit. Too bright → larger value; dim beside a digit → noted (the shared anode resistor limits it)
- [ ] Value chosen for all twelve ___; recorded in [hardware.md](../../docs/hardware.md#nixie-board-electrical-design-phase-1a-draft-2026-10-26)
- [ ] Result copied into bringup.md step 5

**5b — tubes 2-6**

- [ ] Decimal-point resistors, value from 5a: R221, R222, R231, R232, R241, R242, R251, R252, R261, R262 (10)
- [ ] N2, N3, N4, N5, N6: as N1
- [ ] Flux cleaned around every lead ring

**Gate 5b — bring-up step 6** (acceptance: every digit and point on every tube; dark start-up;
stable at full load)

- [ ] Discharge checked; HV on
- [ ] Every digit and both points on each tube, in the HV_MAP order: tube 1 ___ 2 ___ 3 ___ 4 ___ 5 ___ 6 ___
- [ ] Start-up dark: 12 V applied with the RP2040 in BOOTSEL and with the firmware booting: no
  digit flashes ___
- [ ] Full load, one digit lit on every tube: NIX_HV ___ V; 12 V input current ___ A (budget
  0.39 A; bench 0.329 A at 175 V into the 11 kΩ dummy); module and Q101 temperature after a
  warm-up run of ___ min ___
- [ ] Dimming: PWM on `DRV_BL`, frequency ___ and minimum duty ___ at which every digit still
  ignites without flicker; NIX_HV stays in regulation (`NIX_HV_SENSE`, scope on TP103); no audible
  noise ___. Recorded in hardware.md
- [ ] Result copied into bringup.md step 6

## Stage 6 — encoder, RTC and WWVB harnesses (in the enclosure)

The encoder (front panel), the ZS-042 and the ES100 carrier are mounted in the enclosure and the
harnesses are cut to length there. Board end: wires soldered to J301 / J302 / J303 through their
cable-tie holes. Module end: single-pin female jacks on the module headers, each wire with a
printed label naming its signal; jacks go on **by the module's silk names, never by position**.
J302 and J303 carry only +3V3 and 3.3 V logic.

- [ ] Encoder (PEC11R): J301 pin 1 A, 2 B, 3 switch, 4 GND (to the encoder's common C and switch
  pin 2). Solder the encoder terminals quickly (Bourns: hand soldering not recommended)
- [ ] RTC (ZS-042): J302 pin 1 +3V3, 2 GND, 3 SDA, 4 SCL
- [ ] WWVB (ES100): J303 pin 1 +3V3, 2 GND, 3 WWVB_SDA, 4 WWVB_SCL, 5 WWVB_EN, 6 WWVB_IRQ; supply
  pair (+3V3, GND) twisted; harness routed apart from the HV wiring and the module
- [ ] ES100 antennas: orthogonal to each other and parallel to the floor (AN-005), as far as the
  enclosure allows from the Nixie HV module and the dekatron board's L102

**Gate 6 — bring-up step 7**

- [ ] Unpowered continuity, each wire from its board pad to the named module pin ___; no pad-to-pad
  shorts; +3V3 to GND not a short at each module ___ Ω
- [ ] Encoder: turns count both ways with no missed detents; push switch ___
- [ ] ES100: with `WWVB_EN` high, register 0x0D at address 0x32 reads 0x10 ___; with `WWVB_EN` low,
  no answer (shutdown); `WWVB_IRQ` idles high ___
- [ ] RTC on the main bus (needs an I2C controller and the bus pull-ups: the dekatron board's pair
  over NIX_LV, or the ZS-042's own if kept): it answers at its address ___ (DS3231 address
  `_open_` in hardware.md until its datasheet is in `docs/datasheets/`)
- [ ] Result copied into bringup.md step 7

## After the board

- [ ] With the dekatron board: NIX_LV (J101 ↔ dekatron J302) and NIX_12V (J102 ↔ dekatron J102)
  harness continuity; Nixie RP2040 answers as an I2C target on the main bus; both boards power up
  dark
- [ ] A WWVB reception with both HV supplies off (Phase 3/4)
- [ ] Flashing access in the enclosure: side A faces down, so U301's USB-C and BOOT face into the
  enclosure (service access or a USB extension, Phase 4)
- [ ] Final flux clean and inspection before the board goes into the enclosure
