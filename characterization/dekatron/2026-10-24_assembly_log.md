# Dekatron controller/PSU — assembly log, board 1

Working copy of [assembly.md](../../hardware/dekatron/assembly.md) as of 2026-10-24, filled in
during the build. The checklist itself is maintained there; this file records what was done and
measured on this board.

> [!WARNING]
> High voltage (~450 V), at your own risk. Read the [README safety section](../../README.md#safety-read-this-first)
> before powering stage 2 or 3.

The board is populated one section at a time, with the [bring-up](../../docs/bringup.md#dekatron-controllerpsu-phase-1d)
step for that section run before the next one is soldered. A fault then shows up while the
section is still small and easy to probe. Within each stage the order is fine-pitch ICs, then
small passives batched by part, then discretes, then large SMD, then through-hole. To build the
whole board at once, do the stages back to back and keep the links as each gate states.

Every part comes from [`bom.csv`](../../hardware/dekatron/bom.csv). Each line below is one reel or bag: value, part
number, package, references. Rules:

* **Batch by part number, not by value.** C201 (0.1 µF **100 V**) and C202 (1 µF **100 V**)
  look like the 50 V / 25 V parts of the same value; the 2.2M, 2.7M, 200k, 220k and 330k
  HHV/MRS parts are through-hole and must not be replaced with 1206 parts of the same value.
* **Same package, different part:** BAT54S, MMBTA42 and MMBTA92 are all SOT-23; BZT52C10, the
  39 V and the 51 V zeners are all SOD-123; TPS54302 and TLV3011 are both SOT-23-6. Open one bag at
  a time and check the marking.
* **Kit resistors** (no part number in the BOM) are batched by value. R204 needs 1 %; use the kit
  10k for it only if the kit is 1 %.
* **Links follow the bring-up, not the size order:** LK1, LK2, LK4 and LK5 are fitted at the gate
  that says so; LK15 is not fitted (only when GP12 is used, see [hardware.md](../../docs/hardware.md#test-provisions-d11)).
* Test points (`TP…`) are bare plated pads; nothing to fit.
* Clean the flux after each stage (IPA). The board takes no clearance credit for solder mask or
  coating, so flux left on the HV side is a leakage path.

Record readings in the blanks, then copy the verdict into the Result column of
[bringup.md](../../docs/bringup.md#dekatron-controllerpsu-phase-1d) and the raw data into
`characterization/dekatron/` as dated files.

## Before starting

- [x] Bring-up step 0 done: harness continuity, tube removed ([bringup.md](../../docs/bringup.md#dekatron-controllerpsu-phase-1d))
- [x] Tools: microscope, solder paste, hot air or hot plate, flux, IPA, ESD mat and strap
- [x] All parts on hand and checked against `bom.csv`, including the off-board HHV-50 1M dummy load (`HHV-50FT-52-1M`) and a shunt for JP101
- [x] Bare board inspected: no visible shorts or damage, silkscreen legible
- [x] Assembly map: front silkscreen and solder mask printed at 2:1, each part marked with a
  highlighter as it is fitted. Very helpful for finding parts and seeing what is left in a stage

## Stage 0 — U106 on the bare board

U106 (LM5156H, HTSSOP-14 with exposed pad) goes on first: hot air would disturb parts already
fitted around it, and on the bare board it can be re-flowed from the back through its thermal vias.

- [x] U106 — LM5156H, `LM5156HPWPR`, HTSSOP-14-EP: paste, pin 1 aligned, reflowed
  (2026-10-21: small amount of paste, heated from the back until the paste melted at the leads,
  every lead touched up with the iron)

**Gate 0**

- [x] No bridges between pins (microscope)
- [x] Exposed pad (pin 15): reflowed from the back until the paste melted at the leads. It can't be
  checked with a meter: pins 5, 6 and the pad all sit on GND
- [x] No pin shorted to its neighbours (meter, pin to pin). Bare board, flux not yet removed:
  3-4 0.5 MΩ, 4-5 1.5 MΩ, 5-6 0 Ω (both GND, expected), 6-7 20 MΩ, 11-12 1.3 MΩ, 7-8 9 MΩ
  (not neighbours); 1-2, 2-3, 8-9, 9-10, 10-11, 12-13, 13-14 open. Pin 6 to GND: continuity
- [x] Flux cleaned

## Stage 1 — input, 5 V buck, ideal diodes, MCU

Input protection and fuses, the 5 V buck, the three ideal-diode feeds, the HV-enable network (so
the HV-off default is in place as soon as the MCU is fitted) and the whole MCU sheet.

ICs

- [x] TPS54302, `TPS54302DDCR`, SOT-23-6: U101
- [x] LM66100, `LM66100DCKR`, SC-70-6: U102, U103, U104

Capacitors, 1206

- [x] 0.1 µF 50 V X7R, `CC1206JPX7R9BB104`: C102, C104, C105, C109, C110, C111, C302, C303, C305 (9)
- [x] 10 nF X7R, `12063C103JAT2A`: C304
- [x] 75 pF C0G, `12065A750JAT2A`: C108

Resistors, 1206

- [x] 10k (kit): R101, R109, R114 (3)
- [x] 100k (kit): R105, R110, R301 (3)
- [x] 4.7k (kit): R303, R304 (2)
- [x] 0 Ω (kit): R112 — **leave LK2 open**: same 0 Ω part, fitted at Gate 1 after the buck check
- [x] 511k, `RT1206FRE07511KL`: R102
- [x] 105k, `CR1206-FX-1053ELF`: R103
- [x] 49.9 Ω, `RCC120649R9FKEA`: R104
- [x] 13.7k, `CR1206-FX-1372ELF`: R106
- [x] 12k, `ERJ-8ENF1202V`: R302

Discretes

- [x] BAT54S, `BAT54S RFG`, SOT-23: D301, D302, D303, D304 (4)
- [x] BZT52C10, SOD-123: D101 (cathode band)
- [x] SMBJ15A, SMB: D102 (cathode band)
- [x] IPD50P04P4L-11, `IPD50P04P4L11ATMA2`, TO-252: Q101

Large SMD

- [x] 10 µF 35 V, `CC1210KKX7RGBB106`, 1210: C103
- [x] 22 µF 25 V, `MBAST32MSB7226KPNA18`, 1210: C106, C107 (2)
- [x] 2 A Slo-Blo fuse, `0468002.NRHF`, 1206: F101
- [x] 0.75 A PTC, `1812L075/33DR`, 1812: F102
- [x] 10 µF tantalum, `F911C106MAAAJ6`, 3216-18: C301 (**polarized**, + to 5V_MCU)

MCU module

- [x] RP2040-Zero: U301, USB toward the board edge, castellations centred on their pads, every pad soldered and inspected.
  Parts on the module's underside hold it about 0.8 mm off the board: too much for a plain solder
  bridge. Tack two opposite corners, check the module sits level, then stand a cut-off 1/4 W
  resistor lead in each castellation, solder it to the board pad and the castellation, and trim it
  flush. Check each joint with a meter, castellation to its board trace

Tall SMD and through-hole

- [x] 100 µF 35 V electrolytic, `EEE-FK1V101XP`: C101 (**polarized**)
- [x] 15 µH radial (kit): L101
- [x] 2-pin header: JP101, **shunt fitted**

Harness

- [x] PWR_IN: J101 (harness or bench leads)
- [x] Optional now, needed by step 4: DISP, J301

**Gate 1 — bring-up step 1** (acceptance: rails in tolerance, no back-feed from USB)

- [x] Flux cleaned
- [x] Links: LK1 open (no 12 V to the HV converter until Gate 2), LK2 open (fitted below, after the
  buck check); R112 fitted (a 0 Ω resistor, not a link); JP101 shunt fitted
- [x] Unpowered, to GND (not a short): VIN_PROT (TP101) 0.16 MΩ, +5V (TP103) > 2 MΩ, 5V_MCU (TP310) > 2 MΩ, +3V3 (TP309) 1.2 MΩ
- [x] Bench 12 V, current limit set low: 50 mA. When powering the board, voltage is raised in steps of 1V to avoid over current trip due to capacitors charging.
- [x] VIN_PROT (TP101) 12.00 V; input current 1 mA
- [x] Buck output on LK2's buck-side pad, unloaded 4.98 V (design 4.95 V, R105 / R106)
- [x] Power off, **fit LK2**: 0 Ω (kit), 1206
- [x] +5V (TP103) 4.98 V; 5V_MCU (TP310) 4.98 V; +3V3 (TP309) 3.31 V; 5V_DISP (J301 pin 1) 4.98 V; input current 6 mA
- [x] JP101 shunt lifted briefly: HV_EN_PIN (JP101 pin 1) at 0 V (R110 pull-down), then refitted
- [x] 12 V off, USB to the RP2040-Zero: +5V (TP103) 0.04 V and VIN_PROT (TP101) 0.04 V stay near 0 (no back-feed)
- [x] RP2040-Zero enumerates over USB (BOOTSEL)
- [x] 12 V and USB together: rails as above, but 12 V feed current is down to 1 mA
- [x] Result copied into bringup.md step 1

## Stage 2 — HV boost, tripler, OVP

Gate-drive LDO, LM5156H support parts, boost switch and inductor, tripler, HV feedback and the two
OVP comparators. Leave LK1, LK4 and LK5 open.

ICs

- [x] TLV3011, `TLV3011AIDBVR`, SOT-23-6: U107, U108 (2)
- [x] LP2951, `LP2951ACDR2G`, SOIC-8: U105

Capacitors, 1206

- [x] 0.1 µF 50 V X7R, `CC1206JPX7R9BB104`: C115, C121, C128, C130 (4)
- [x] 1 µF X7R, `1206DC105MAT2A`: C112, C114 (2)
- [x] 2.2 µF X7R, `CS1206KKX7R8BB225`: C113
- [x] 47 nF X7R, `CC1206KRX7R8BB473`: C116
- [x] 10 nF X7R, `12063C103JAT2A`: C117
- [x] 100 pF C0G, `C1206C101K5GAC7210`: C118
- [x] 470 pF C0G, `1206B471K500CT`: C119
- [x] 1 nF C0G, `1206N102K501CT`: C127, C129 (2)

Resistors, 1206 and 0805

- [x] 10k (kit): R113
- [x] 100k (kit): R116
- [x] 100 Ω (kit): R118
- [x] 47 Ω (kit): R121
- [x] 2.2 Ω (kit): R115
- [x] 0.22 Ω, `RNCL1206FTR220`: R117
- [x] 143k, `CR1206-FX-1433ELF`: R107
- [x] 20.0k, `RK73H2BLTD2002F`: R108
- [x] 147k, `CRCW1206147KFKTA`: R111
- [x] 7.87k, `ERJ-8ENF7871V`: R135
- [x] 6.2k, `CRCW12066K20FKEAC`: R140
- [x] 13.7k, `CR1206-FX-1372ELF`: R143
- [x] 3.0k, `292-3.0K-RC`, **0805**: R130, R144 (2)

Discretes

- [x] ES1J, SMA: D103, D104, D105, D106, D107 (5, cathode band)
- [x] IPD70R1K4P7S, `IPD70R1K4P7SAUMA1`, TO-252: Q102 (applied paste and reflowed with hot air)

Large SMD

- [x] 10 µF 35 V, `CC1210KKX7RGBB106`, 1210: C120

Through-hole

- [x] Wire link: LK3 (**fitted now and never powered open**)
- [x] 2.2M HHV-25, `HHV-25FT-52-2M2`: R119, R141 (2)
- [x] 2.7M HHV-25, `HHV-25FR-52-2M7`: R126, R131 (2)
- [x] 100 µH radial (kit): L102
- [x] 0.47 µF 400 V film, `MKS4G034704F00MSSD`: C122, C123, C124, C125, C126 (5)
- [x] LK1 0R link (1206 kit)
- [x] LK3 wire link (through hole) 
- [x] 1M resistor between TP107 and TP108 (temporary load)


**Gate 2 — bring-up step 2** (acceptance and limits: [bringup.md step 2](../../docs/bringup.md#dekatron-controllerpsu-phase-1d))

Safety first:

- [ ] Rated HV probes; one hand; nothing touched while powered
- [ ] Discharge check before every touch: V_B (TP106) and HV_STACK (TP108) below 50 V (design target: below 50 V within 10 s, [D12](../../docs/hardware.md#discharge-d12)); discharge time ___ s
- [ ] A way to drive HV_EN (GP6) high and low on purpose: the [bring-up firmware](../../firmware/dekatron-bringup/README.md) flashed, driven with `tools/hv_bringup.py`. Without it, GP6's reset pull-down keeps HV off

Setup:

- [ ] Flux cleaned, HV side especially
- [ ] LK3 fitted, LK4 open, LK5 open
- [ ] Dummy load HHV-50 1M soldered across TP108 (HV_STACK) and TP107 (GND), off-board
- [ ] **Fit LK1**: 0 Ω (kit), 1206
- [ ] Unpowered, to GND (not a short): VDRV (TP104) ___ Ω, V_B (TP106) ___ Ω, HV_STACK (TP108) ___ Ω

HV inhibited (JP101 shunt fitted):

- [ ] VDRV (TP104) ___ V (design 10.07 V, R107 / R108); input current ___ mA
- [ ] SW (TP105): no switching

HV on (shunt removed for the run only, refitted after):

- [ ] HV_STACK ___ V (design 451.0 V with R130 + R144 = 2 × 3.0k); V_B ___ V
- [ ] Ripple ___; startup overshoot ___; power-up inductor current ___
- [ ] Load response ___; temperature ___; input power ___
- [ ] OVP: with HV inhibited, lift R126 (the feedback string's top), release the inhibit, record the trip ___ V (design 543.7 V); restore R126
- [ ] Power off, discharge checked, dummy load removed
- [ ] Result copied into bringup.md step 2

## Stage 3 — tube drive

G+ / RTN regulators, guide drivers, index level shifter and the anode resistors.

Capacitors, 1206

- [ ] 0.1 µF **100 V** X7R, `AC1206KKX7R0BB104`: C201
- [ ] 1 µF **100 V** X7R, `C1206C105M1RACAUTO`: C202
- [ ] 1 nF C0G, `1206N102K501CT`: C204

Resistors, 1206

- [ ] 10k (kit): R206, R209 (2)
- [ ] 10k 1 %: R204
- [ ] 47k (kit): R207, R210 (2)
- [ ] 470k (kit): R205, R208 (2)
- [ ] 220k (kit), **1206**: R211 (not R212)
- [ ] 13k, `CR1206-FX-1302ELF`: R214

Discretes

- [ ] MMBTA42 (NPN), SOT-23: Q201, Q202 (2)
- [ ] MMBTA92 (PNP), SOT-23: Q203
- [ ] 39 V zener, `MMSZ5259BH RHG`, SOD-123: D201 (cathode band)
- [ ] 51 V zener, `MMSZ5262BT1G`, SOD-123: D202 (cathode band)

Through-hole

- [ ] 40.2k MRS25, `MRS25000C4022FCT00`: R201
- [ ] 200k HHV-25, `HHV-25FR-52-200K`: R202
- [ ] 220k HHV-25, `HHV-25FR-52-220K`: R212
- [ ] 330k HHV-50, `HHV-50FR-52-330K`: R215, R216 (2)
- [ ] Wire links LK4, LK5: **not yet**, see gate

**Gate 3 — bring-up step 3** (acceptance: guide waveforms and index signal at 3.3 V as designed)

- [ ] Flux cleaned
- [ ] Discharge checked; **fit LK5** (wire link); LK4 still open, no tube
- [ ] HV on: RTN (TP202) ___ V (D202, 51 V), G+ (TP201) ___ V (D201, 39 V above RTN); RTN_SENSE ___ V
- [ ] Guides at rest (RP2040 in reset): G1 (TP203) and G2 (TP204) at G+
- [ ] Guide pulses driven from the RP2040: G1 / G2 waveforms ___
- [ ] Power off, discharge checked; **fit LK4** (wire link)
- [ ] TUBE harness soldered: J201 (anode, alone, ≥ 3 mm from other pads), J202 (G1, G2, K1, RTN)
- [ ] Tube fitted; HV on: tube strikes, NDX (TP205) ___ V with the glow on K1, ~0 V elsewhere
- [ ] Result copied into bringup.md step 3

## After the board

- [ ] Steps 4 (firmware motion) and 5 (homing characterization) per [bringup.md](../../docs/bringup.md#dekatron-controllerpsu-phase-1d)
- [ ] Phase 2, with the Nixie module: NIX_12V harness (J102) and NIX_LV harness (J302)
- [ ] Final flux clean and inspection before the board goes into the enclosure
