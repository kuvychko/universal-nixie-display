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

- [x] Rated HV probes; one hand; nothing touched while powered
- [ ] Discharge check before every touch: V_B (TP106) and HV_STACK (TP108) below 50 V (design target: below 50 V within 10 s, [D12](../../docs/hardware.md#discharge-d12)); discharge time 0.67 s
  (HV_STACK from 452.6 V, 1M load fitted, 100 Hz log `2026-10-24_gate2_discharge.csv`; < 300 V
  70 ms, < 100 V 0.43 s, < 20 V 1.0 s). V_B discharge not measured: **deferred**
- [x] A way to drive HV_EN (GP6) high and low on purpose: the [bring-up firmware](../../firmware/dekatron-bringup/README.md) flashed, driven with `tools/hv_bringup.py`. Without it, GP6's reset pull-down keeps HV off

Setup:

- [x] Flux cleaned, HV side especially
- [x] LK3 fitted, LK4 open, LK5 open
- [x] Dummy load HHV-50 1M soldered across TP108 (HV_STACK) and TP107 (GND), off-board
- [x] **Fit LK1**: 0 Ω (kit), 1206
- [x] Unpowered, to GND (not a short): VDRV (TP104) 0.16 MΩ, V_B (TP106) 1.8 MΩ, HV_STACK (TP108) 0.84 MΩ.
  TP108 was expected at 0.58 MΩ (1M load ‖ 2.706M feedback string ‖ 2.714M sense string), so both
  strings were checked by injecting 12 V into TP108 (board unpowered, USB only): HV_SENSE read
  13.1 V on the RP2040 (≈ 11.9 V less its 1.2 V zero offset), FB at R130 pad 1 26.6 mV (calculated
  26.6 mV). Both strings intact; the 0.84 MΩ was the meter

HV inhibited (JP101 shunt fitted):

- [x] VDRV (TP104) 10.05 V (design 10.07 V, R107 / R108); input current 1 mA (USB also connected)
- [x] SW (TP105): no switching, 12.00 V DC (VIN through L102). HV_STACK on HV_SENSE 11.4 V, the
  same pass-through; PGOOD low. `on 5` with the shunt fitted: firmware latched `en_low`, peak HV
  12.0 V, so the inhibit holds

HV on (shunt removed for the run only, refitted after):

- [x] HV_STACK 449 V on the meter (design 451.0 V with R130 + R144 = 2 × 3.0k); V_B 152 V. Board
  HV_SENSE read 452.4-452.7 V (≈ 3-4 V high); PGOOD high; VIN 11.94 V. Raw:
  `2026-10-24_gate2_run1.csv` (10 s, 20 Hz). One 600.8 V peak sample on the 120 s run, most
  likely probe pickup on HV_SENSE: the OVP (543.7 V) did not trip and the EN node stayed high
- [ ] **Deferred** (user, 2026-10-24): ripple, startup overshoot (board ADC peak 458-459 V, scope
  not used), power-up inductor current
- [ ] **Deferred** (user, 2026-10-24): load response, temperature. Done: input power 0.45 W (11.94 V × 38 mA, USB also
  connected; 1 mA of it with HV off). Load ≈ 0.35 W (449 V into 1M ‖ 2.706M ‖ 2.714M):
  ≈ 79 % including the VDRV LDO
- [x] Done at the start of Gate 3, before LK5 was fitted, so the trip voltage stayed off the
  Stage 3 parts. OVP: R126 (the feedback string's top) removed rather than lifted, JP101 shunt off,
  1M load fitted, VIN 11.94 V, `on 5`. HV still rising at 532 V 0.2 s after `on`; the OVP pulled
  EN low and the firmware latched `en_low`, HV off. Trip: board peak **549.4 V**, ≈ 545-546 V
  allowing for the ≈ 3-4 V high reading (design 543.7 V, simulated 545.1 V). R126 refitted; `on 5`
  regulated again: board HV_SENSE 451.4-454.8 V, PGOOD high (peak 476.3 V since `on`, higher than
  the 458-459 V at Gate 2; VIN read 8.49 V just before, the supply still rising, scope not used)
- [x] Power off, discharge checked, JP101 shunt refitted; dummy load **kept** until the OVP test
- [ ] The deferred items above (ripple, startup overshoot, inductor current, load response,
  temperature, V_B discharge) are not pursued with the 1M load: user decision 2026-10-25, judged
  not important enough. Load response and temperature are more meaningful with the tube lit.
  1M dummy load removed (discharge checked first) ___
- [x] Result copied into bringup.md step 2 (partial)

## Stage 3 — tube drive

G+ / RTN regulators, guide drivers, index level shifter and the anode resistors.

Capacitors, 1206

- [x] 0.1 µF **100 V** X7R, `AC1206KKX7R0BB104`: C201
- [x] 1 µF **100 V** X7R, `C1206C105M1RACAUTO`: C202
- [x] 1 nF C0G, `1206N102K501CT`: C204

Resistors, 1206

- [x] 10k (kit): R206, R209 (2)
- [x] 10k 1 %: R204
- [x] 47k (kit): R207, R210 (2)
- [x] 470k (kit): R205, R208 (2)
- [x] 220k (kit), **1206**: R211 (not R212)
- [x] 13k, `CR1206-FX-1302ELF`: R214

Discretes

- [x] MMBTA42 (NPN), SOT-23: Q201, Q202 (2)
- [x] MMBTA92 (PNP), SOT-23: Q203
- [x] 39 V zener, `MMSZ5259BH RHG`, SOD-123: D201 (cathode band)
- [x] 51 V zener, `MMSZ5262BT1G`, SOD-123: D202 (cathode band)

Through-hole

- [x] 40.2k MRS25, `MRS25000C4022FCT00`: R201
- [x] 200k HHV-25, `HHV-25FR-52-200K`: R202
- [x] 220k HHV-25, `HHV-25FR-52-220K`: R212
- [x] 330k HHV-50, `HHV-50FR-52-330K`: R215, R216 (2)
- [x] Wire link LK5 ONLY

**Gate 3 — bring-up step 3** (acceptance: guide waveforms and index signal at 3.3 V as designed)

- [x] Flux cleaned
- [x] Discharge checked; **fit LK5** (wire link); LK4 still open, no tube
- [x] HV on: RTN (TP202) **49 V** to TP107 (D202, 51 V ±5 %); board RTN_SENSE 50.1 V, HV 452 V
  (board), PGOOD high. G+ (TP201) **89.3 V** to TP107, 40.3 V above RTN (D201, 39 V ±5 %). A first
  reading of 61 V was a meter range error; unpowered, TP201-TP202 read open / 0.2 MΩ by polarity
  and TP201-TP107 open (> 2 MΩ), so no leakage path
- [x] Guides at rest (firmware idle, HV on): G1 (TP203) **85.4 V**, G2 (TP204) **85.5 V** to TP107,
  i.e. G+ less the 10 MΩ meter's load through the 470k pull-up (≈ 4.0 V, calculated). Driven on
  (`guide 1 1`, `guide 2 1`): **0 V** each; back to rest after. With 12 V on and HV off the guides
  follow the pass-through, ≈ 11 V. HV cannot be on with the RP2040 in reset (HV_EN pull-down),
  so the reset case is checked unpowered from HV: RESET held, Q201 / Q202 base ≈ 0 V ___
- [ ] Guide pulses driven from the RP2040: G1 / G2 waveforms ___. **Deferred** (user,
  2026-10-25): scope measurements later; on to the tube
- [ ] Power off, discharge checked; **fit LK4** (wire link)
- [ ] TUBE harness soldered: J201 (anode, alone, ≥ 3 mm from other pads), J202 (G1, G2, K1, RTN)
- [ ] Tube fitted, before HV (12 V on, HV off): RTN (TP202) 2.9 V (0.1-0.2 V before the tube),
  G1 (TP203) 4.3 V, G2 (TP204) 10.5 V, G+ (TP201) 10.99 V, NDX 0.0 V. G1 leaks ≈ 14 µA into
  RTN. Unplugging G1 at the board restores TP203 to 10.5 V; removing the tube clears it. **Bare
  tube: pin 5 (G1) to pin 9 (K4) 96 kΩ**, not adjacent pins, so most likely inside the tube
  (2026-10-25). The 2026-10-09 bench test stepped reliably, so the leak is probably new
- [ ] Tube fitted; HV on: tube strikes, NDX (TP205) ___ V with the glow on K1, ~0 V elsewhere.
  2026-10-25, three 20 s runs: tube strikes and glows. Board NDX **2.83 V** on the third run with the
  glow on K1 (design 2.81 V at RTN 50 V), 0.01 V on the first two. G1 rest (TP203) **57.2 V**, 7 V
  above RTN (G1-K4 leak; design ≈ 89 V). **HV out of regulation:** board HV_SENSE 412-422 V,
  PGOOD low (452 V, PGOOD high without the tube, LK5 fitted). Input **56 mA** at 11.93 V
  (0.67 W; 38 mA / 0.45 W at Gate 2 with the 1M load)
- Stepping, `on 60`, `step 1 fwd 500 10` (phase 500 µs, 10 steps/s): glow steps clockwise; 10
  steps move round cleanly by eye. Single steps with a `status` read after each: NDX **2.83 V** at
  one position in 12 (step 9), 0.01-0.02 V elsewhere. The firmware's hit counter read NDX 60 µs
  after the guides released and missed K1; moved to one step period after each step
- **G1 leak cleared** after these HV runs, tube and wiring untouched: with 12 V on and HV off, RTN
  0.1 V (was 3.1 V) and G1 (TP203) **11.0 V** (was 4.3 V). Burned clear or intermittent; recheck
  pin 5-9 on the bare tube later. Under HV, G1 at rest (TP203) **89 V** = G+
- **Stepping with index count** (phase 500 µs; HV 415-417 V board, PGOOD low): 10 fwd at 10/s
  `ndx_hits=1`; 10 rev at 10/s `1`; 100 fwd at 100/s `10`; 200 fwd and 200 rev at 200/s `20` each.
  Every run exact. (The counter first read 0: `analogRead()` turns off GP26's digital input
  buffer, so it now compares an ADC reading with 2.0 V, the RP2040's V_IH min)
- [ ] HV shortfall with the tube lit: scope on Q102 source (R117 high side), HV ≈ 415 V. Waveform
  "pretty ugly"; the scope's counter read 380 kHz, most likely the DCM ringing rather than the
  switching period (design ≈ 150 kHz, R111 147k). Period, ramp peak and burst pattern ___; R111 in
  circuit ___ (paused, user, 2026-10-25)
- Gate (Q102 pin 1), HV ≈ 420 V, tube lit: clean square wave, **152 kHz** (design ≈ 150 kHz, so
  R111 is right); on-time **1.7-3.0 µs, varying** (≈ 3.8 µs expected at the 0.42-0.49 A current
  limit with 100 µH at 11.9 V, calculated). Cycles end early: suspect the pump surge through Q102
  and R117 reaching the 100 mV CS threshold (see hardware.md "Pump surge"). Unpowered: R121 47.5 Ω,
  R118 100 Ω, C119 fitted, R117 **0.2 Ω** after nulling the 0.6 Ω leads (0.22 Ω part)
- CS (top of C119) vs gate, HV ≈ 415 V, tube lit (1× probes, long ground leads): on-time
  **≈ 2.9-3.1 µs**, the same each cycle (the earlier 1.7 µs was the cursor readout, not a cycle).
  CS ramp ≈ 27 mV/µs (26 mV/µs calculated for 100 µH, 0.22 Ω, 11.9 V), starts at ≈ 0 (DCM), no
  leading-edge spike or pedestal; gate falls at CS **≈ 60-65 mV** (≈ 0.29 A), below the 93 mV
  minimum current-limit threshold. Ringing of ±250 mV follows turn-off. **Pump surge ruled out**
- HV log at 100 Hz for 8 s, tube lit: **415.0 V, σ 0.3 V**, no slow oscillation. COMP (U106 pin 8)
  **2.82 V** on the meter, at the max COMP clamp (2.5-2.8 V, datasheet). So the error amp is
  saturated and the PWM comparator caps the peak at ≈ 0.29 A before the current limit:
  0.5 × 100 µH × 0.29² A² × 152 kHz ≈ 0.64 W, matching the 0.67 W input. The ≈ 1.2 W design
  capacity assumed the 0.42-0.49 A current limit sets the peak. PGOOD low is the 90 %/95 %
  hysteresis (406/428 V, datasheet). Fix _open_ (simulate first)
- 12 V input with HV off, USB plugged: **1 mA**, so nearly all of the 0.67 W goes to the HV
  converter. `hv_fsw.cir` (as built, 450 V setting, tube lit) regulates at 450.9 V with a 0.28 A
  peak (CS 61 mV), COMP 1.69 V, 0.60 W into the power stage: about the same peak and power as
  the board, which reaches only 415 V with COMP at its clamp
- Gate persistence (1 µs/div): on-time **smeared over 1.9-3.2 µs**, so the cycles end at a
  varying point, not a fixed threshold
- CS at C119 pin 1, 10× probe, triggered on the gate falling edge: a flat **≈ +2 V pulse for
  ≈ 350 ns** right after turn-off (the inductor's reset interval). Tip moved to C119 pin 2 (GND),
  ground lead unchanged: same shape, ≈ 5× smaller. So ≈ 0.4 V is pickup in the probe loop and
  ≈ 1.7 V is across C119 on the board (CS abs max 0.3 V). Layout: C119 and R118 sit next to L102
  (unshielded radial drum), ≈ 20 mm of CS trace from U106 pin 7; R117's ground end is ≈ 36 mm
  from U106. The voltage at U106 pin 7 itself is not yet measured
- **Working hypothesis:** noise coupled into the CS path (L102's field into the R118/C119 loop,
  the long unfiltered trace to pin 7, ground offset between R117 and U106) trips the PWM or
  current-limit comparator early, at varying points. That caps the peak near 0.29 A with COMP
  at its clamp. The TI model has none of these parasitics, so it regulates with headroom
- **Next troubleshooting steps** (HV protocol throughout: probes placed with HV off and
  discharged, hands clear while on):
  - [ ] HV off: tack a short fine wire to the CS trace at U106 pin 7. CH2 (10×) on the wire,
    ground at C118's GND end (≈ 3 mm from U106). Trigger on the gate falling edge: tip on the
    wire ___, then tip on the ground point with the lead unchanged (probe-loop share) ___
  - [ ] Same point at 50 mV/div with persistence: spikes during the on-time at the pin ___;
    do the short cycles end on a spike? ___
  - [ ] If spikes line up with an asynchronous source: CH2 on the 5 V buck's switch node,
    trigger on the gate falling edge, look for coincidence ___
  - [ ] Optional cross-checks: U106 pins 5 and 6 to R117's GND end, unpowered (≈ 0 Ω) ___;
    COMP and CS peak with the tube out (LK5 fitted, regulating) vs the model's 1.69 V for
    0.28 A ___; tube current from the anode-resistor drop (HV-rated meter) vs 381 µA modelled ___
- **Next steps (fix, decided from the pin-7 capture; none chosen yet):**
  - [ ] Filter at the pin: a kit 470 pF (C119's design value) across U106 pins 7 (CS) and
    6 (AGND), the adjacent pin. Re-measure on-time spread, COMP and HV
  - [ ] Reduce the field: shielded inductor, or L102 turned or moved; layout change for board 2
    (CS filter at the pin, Kelvin sense from R117's pads, R117 ground close to U106)
  - [ ] Headroom regardless: 220k piggybacked on R111 (≈ 252 kHz, datasheet Eq. 5); rerun
    `hv_fsw.cir` at 88.1k first (the run failed to converge at 0.47 ms, node g1)
  - [ ] Record the outcome in hardware.md (capacity figure, kit inductor) and bringup.md step 3
- [x] Result copied into bringup.md step 3 (partial)

## After the board

- [ ] Steps 4 (firmware motion) and 5 (homing characterization) per [bringup.md](../../docs/bringup.md#dekatron-controllerpsu-phase-1d)
- [ ] Phase 2, with the Nixie module: NIX_12V harness (J102) and NIX_LV harness (J302)
- [ ] Final flux clean and inspection before the board goes into the enclosure
