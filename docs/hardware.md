# Hardware

Electrical design, open decisions and harness tables. Values here are design records: an entry is
only filled in once it has a source (datasheet, measurement, simulation or explicit decision).

## Board revisions

Record the exact revision of every purchased module before footprints or pin maps depend on it.

| Item | Assumed | Confirmed revision / evidence |
|---|---|---|
| ESP32 display board | ESP32-2432S028R family (as in nanovolt-divider) | **Confirmed** (user, 2026-10-05): same module as nanovolt-divider — ESP32, CH340 USB serial, 320×240 ILI9341, XPT2046-type resistive touch, microSD. See [Display harness](#display-harness) |
| Controller MCU | RP2040-Zero (Waveshare) | **Confirmed** (user, 2026-10-05): RP2040-Zero, headerless. Mount by its castellated edge pads soldered directly to the carrier (no header stack height); footprint must also leave the USB-C connector and BOOT/RESET buttons reachable |
| A101 socket | Existing socket on hand | **Confirmed** (user, 2026-10-06): stock socket for the A-101; pin numbering per the tube. Mounting dimensions: enclosure phase |
| Nixie HV module | Amazon B09D94N3MX | _open_ — qualify delivered version |
| 12 V adapter | Isolated 12 VDC | Connector **confirmed** (user, 2026-10-05): 2.1 mm barrel plug into a chassis-mounted jack the user already has; jack wired to the board. Adapter not yet bought: rating to be specified generously from the power budget (D5). Assume centre-positive, but D4 must survive reversed polarity |

## Dekatron controller/PSU

First deliverable. One KiCad project in `hardware/dekatron/` with hierarchical sheets:
**power** (12 V input, 5 V/3.3 V, HV converter), **tube** (bias, guide drivers, index sense),
**mcu** (RP2040-Zero, USB, I2C, links/test points).

### Phase 1A decision register

Exit criterion (plan §9): voltage/current requirements, logic levels, USB power paths, socket
pinout and sectional test provisions defined.

| ID | Decision | Status | Notes / inputs needed |
|---|---|---|---|
| D1 | A101 operating point: anode supply, anode resistor, tube current, guide bias and pulse amplitude | **Decided** 2026-10-05 | HV rated for 500 V, set to 450 V at first bring-up; see [A101 operating point](#a101-operating-point-d1) |
| D2 | HV converter topology (direct boost / boost + multiplier / flyback / 12→5 V + AD01A-style) | **Proposed** | Boost to HV/3 plus Cockcroft-Walton tripler, LM5156H controller; see [HV converter](#hv-converter-d2) |
| D3 | HV output current budget (tube + bias + bleeder) and margin | **Proposed** | 1 mA at HV, about 4.4 mA at the boost node; see [HV load budget](#hv-load-budget-d3) |
| D4 | 12 V input protection: reverse polarity, fuse/PTC, TVS, inrush | **Proposed** | Barrel adapters of either polarity exist, so reverse-polarity protection is mandatory. Input arrives by wire from the chassis jack, not a board-mounted jack |
| D5 | 5 V buck capacity | **Proposed** | ≈ 0.63 A peak estimate, buck rated 2 A; 12 V adapter 2 A; see [Power budget](#power-budget) |
| D6 | USB power paths: VBUS isolation/selection for ESP32 USB and standalone RP2040 debug | **Decided** 2026-10-06 | Ideal diode on every external 5 V feed (one design block); no reliance on a USB isolator; see [USB power paths](#usb-power-paths-d6) |
| D7 | HV enable default and defined tube state while the RP2040 is in reset/BOOTSEL | **Proposed** (HV part) | LM5156H EN/UVLO pulled down; the RP2040 `HV_EN` drives it directly; see [Controller IC](#controller-ic). Guide drivers: base pull-downs so reset = guides at rest. RP2040 GPIO reset state confirmed (pulled-down inputs) |
| D8 | Guide driver circuit and its input current at 3.3 V | **Proposed** | MMBTA42 low-side switch per guide; 0.24 mA from the RP2040; see [Guide drivers](#guide-drivers-d8) |
| D9 | Index sense: threshold, level translation to 3.3 V, protection | **Proposed** | MMBTA92 level shifter, 220k/13k divider, Schottky clamp; 2.67-2.95 V out; see [Index sense](#index-sense-d9) |
| D10 | A101 socket pinout, verified against the tube drawing | **Decided** 2026-10-06 | User's tube is an A-101 in a stock socket for this tube (RSH30 base / PL30-2p socket), so the socket follows the tube pinout in [A101 pinout](#a101-pinout). Wiring check before first HV: [bringup.md](bringup.md) |
| D11 | Sectional test provisions: removable links, test points, dummy-load landing | **Proposed** | Links L1-L14, HV inhibit jumper, dummy-load footprints, test-point list; see [Test provisions](#test-provisions-d11) |
| D12 | Discharge path and target discharge time | **Proposed** | Always-connected 4.8 MΩ bleeder; target < 50 V within 10 s without firmware; C_eff ≤ 0.87 µF; see [Discharge](#discharge-d12) |
| D13 | Clearance/creepage rules for ~450 V, component voltage ratings | **Proposed** | Four net classes, `HV` ≥ 3.0 mm; 1206 strings ≤ 150 V per part; see [Clearance and ratings](#clearance-and-ratings-d13) |
| D14 | Connectors: 12 V in, 5 V out, I2C, programming access | **Decided** 2026-10-06 (approach) | Harness wires solder directly to board pads; connectors only at the far end where a module needs one. Dekatron harness soldered at both ends. See [Harness landings](#harness-landings-d14) |

### A101 operating point (D1)

**Tube data** (tube-tester.com A101 page; see [references.md](references.md)):

| Parameter | Value |
|---|---|
| Operating (supply) voltage | 425 V min, 450 V typ |
| Maintaining voltage | 130-170 V |
| Anode/cathode current | 300-450 µA, 400 µA typ |
| Guide bias (guides vs. main cathodes) | +36 to +44 V |
| Guide pulse | −150 Vp |
| Output (index) voltage | 20 V, with 33 kΩ cathode resistor typ |
| Max counting speed | 1 kHz |
| Base / socket | RSH30 (РШ30) / PL30-2p (ПЛ30-2п), 13 pins |

**Reference circuit** (AD01 Dekatron Shield, M. Moorrees 2017, schematic and BOM images):
MC34063 driving paralleled 2N5551 from 5 V to 140 V, a BAV21 tripler to ~420 V (unloaded
maximum), anode resistor 470 kΩ. A divider from 140 V (33k / 47k / 47k) makes **G+ ≈ 104 V**
and **RTN ≈ 52 V**: the main cathodes return to RTN, not ground. Each guide is pulled up to G+
through 470 kΩ and pulled to ~0 V by an MPSA42 (10 kΩ base resistor). Index K1 drives the emitter
of an MPSA92 PNP whose base sits at RTN; its collector feeds 220k / 22k to the logic input.

Consequences, computed from those values:

* **Elevated cathodes are what let ground-referenced NPN switches drive the guides.** Guide rest =
  G+ − RTN ≈ +52 V (datasheet +36-44 V); guide pulled to 0 V = −RTN ≈ −52 V. That is a third
  of the datasheet's −150 Vp pulse; the reference demonstrates it transfers the glow. We keep
  the scheme and treat the reduced pulse as a known deviation to confirm at bring-up.
* **The divider is not stiff.** The tube's ~0.4 mA flows *into* RTN, whose Thevenin resistance is
  29.6 kΩ, so lighting the tube moves RTN from 51.8 to 63.7 V and G+ from 103.6 to 108.5 V.
  Bias and pulse depend on whether the tube is lit. **Proposed:** derive RTN with a shunt element
  (zener or TL431 + HV transistor) that sinks the tube current, and G+ as RTN + 40 V from a
  supply that can source the guide pull-up current.
* **Reference anode current runs high.** (420 − 52 − V_m)/470k = 422-507 µA for V_m = 130-170 V
  with RTN unloaded; the 420 V figure is the unloaded maximum, which loading pulls down.
* **Index output at 3.3 V.** The PNP collector saturates near RTN, so the input sees
  RTN × R16/(R15 + R16): 4.6 V with 22k. With R15 = 220k, R16 = 13k gives 2.8 V at RTN = 50 V
  (RP2040 V_IH = 2.0 V) and 3.1 V at 55 V. Add a clamp to 3V3; the 220k limits fault current.
* **Guide drive at 3.3 V works.** 10 kΩ base resistors give (3.3 − 0.7)/10k = 0.26 mA base
  current. The collector carries the 470k pull-up current (~0.2 mA) plus the glow current while the
  glow sits on that guide (~0.4 mA), so forced beta ≈ 2.3: saturated with wide margin.

**Proposal:**

| Parameter | Proposed | Basis |
|---|---|---|
| RTN (main-cathode return) | +50 V, regulated | Reference ≈ 52 V, made load-independent |
| G+ (guide rest) | RTN + 40 V = +90 V | Centre of datasheet bias range |
| Guide pulse | Guide switched to ~0 V: −50 V vs. cathodes | Reference practice; datasheet says −150 Vp |
| Anode supply HV | **Option A:** 450 V to ground (400 V above RTN); **Option B:** 500 V to ground (450 V above RTN) | See below |
| Anode resistor | A: 660 kΩ (3 × 220k); B: 810 kΩ (3 × 270k) | Keeps 300-450 µA across V_m 130-170 V and HV ±5 % |
| Tube current | A: 314-443 µA (379 typ); B: 315-426 µA (≈ 370 typ) | Within datasheet 300-450 µA |
| Step rate | ≤ 200 steps/s for homing (plan §5) | Datasheet limit 1 kHz |

The datasheet supply figure (425 min / 450 typ) is referred to the cathodes. With cathodes at
+50 V, Option A gives the tube 400 V, below the datasheet minimum but more than the reference's
≤ 368 V, which works. Option B meets the datasheet typical. Anode resistor dissipation is ~0.1 W
in either case.

**Decision (user, 2026-10-05):** rate every HV component, clearance and the converter for
Option B (500 V), and set the regulator for Option A (450 V) at first bring-up. Raise the setpoint
only if striking or glow transfer is marginal. The setpoint is fixed by the feedback resistor, and
the anode resistor is paired with it. It is a string of three 1206 parts (see
[Component conventions](#component-conventions)): **3 × 220k = 660 kΩ at 450 V** (314-443 µA,
≤ 83 V per part) and **3 × 270k = 810 kΩ at 500 V** (315-426 µA, ≤ 100 V per part), both within
300-450 µA over V_m 130-170 V and HV ±5 %.

### HV converter (D2)

| Candidate | Assessment |
|---|---|
| Direct boost 12 → 450 V | Conversion ratio 37.5: duty ≈ 97 % in continuous mode, switch rated > 500 V plus ringing. Rejected |
| **Boost 12 → HV/3, CW tripler** | Duty ≈ 92 %, workable (the same class as common 12 → 170 V Nixie supplies). Switch sees only ~150-167 V. The boost node also supplies G+ and RTN directly, as in the reference. **Proposed** |
| Flyback 12 → 450 V | One magnetic, but a custom or scarce transformer, and G+/RTN would be derived from 450 V dissipatively. Not worth it at < 1 W |
| 12 → 5 V buck + reference AD01 circuit | Proven, but its 160 V 2N5551 switches cap the tripler at ~420 V, below the decided 450-500 V. Fallback only |

Proposed structure, to be refined and simulated in Phase 1B:

* Boost stage, **feedback taken from HV** (changed in Phase 1B). Regulating V_b, as the reference
  does, left HV at 442 V with a dark tube: the controller idles once V_b is satisfied while the
  bleeders drain the stack top, and the stack runs ~8 V per stage short of 3 × V_b. With HV
  feedback V_b floats to ~157 V for 450 V. The RP2040 also measures HV for diagnostics.
* Switch: an external MOSFET rated ≥ 250 V, driven from 12 V (the 5 V-input reason the reference
  used bipolar switches does not apply here).
* Controller IC: **TI LM5156H** proposed; see [Controller IC](#controller-ic).
* Multiplier diodes and capacitors rated for the 500 V case with margin (e.g. ≥ 600 V diodes,
  since the 250 V BAV21 used in the reference has too little margin at V_b = 167 V).

### Controller IC

Requirements: runs from the protected 12 V input; drives an external low-side MOSFET; has a
shutdown input that can be made to default **off** whenever the RP2040 is in reset, unpowered or
being flashed (D7); cycle-by-cycle current limit; actively produced; a package that can be hand-
soldered; and a simulation model that runs in ngspice (Phase 1B).

| Candidate | Status | Supply | Shutdown | Model | Verdict |
|---|---|---|---|---|---|
| MAX1771 | Not recommended for new designs (ADI) | 2-16.5 V | SHDN pin | None found | Rejected: lifecycle |
| LT3757 | Active | 2.9-40 V | SHDN/UVLO pin | Encrypted LTspice only; ngspice cannot run encrypted models | Rejected: no usable model |
| MC34063 + gate driver | Active | 3-40 V | None | Generic | Rejected: no shutdown, two parts, voltage-mode |
| UC3843 / UCC28C43 | Active | UVLO 8.4 V on / 7.6 V off; UC3843 recommended **12-28 V** | None: gate VCC or pull COMP low | Unencrypted PSpice transient (UCCx8C43) | Rejected: 12 V input minus protection drop is below the recommended minimum |
| LM3478 | Active | 2.97-40 V | FA/SD: **high** = off, abs max 7 V | Unencrypted PSpice transient (rev. B) | Alternate: default-off needs a clamped pull-up from 12 V plus an inverter; 325-600 ns minimum on-time |
| **LM5156H** (LM51561H) | Active (datasheet SNVSBV2, 2020) | 2.97-16 V with BIAS = VCC; 3.5-60 V otherwise | EN/UVLO: **low** = off, rated to V_BIAS | Unencrypted LM5156-Q1 PSpice transient (rev. H) | **Proposed** (user suggestion, 2026-10-06) |

Why the LM5156H: the enable pin is active-high and rated to the full input, so a pull-down resistor
alone makes HV default off and the RP2040 drives it directly. Its light-load behaviour is better
(minimum on-time ~180 ns at 100 kHz, with documented pulse skipping), and it adds a ±1 %
reference, a ±7 % current limit, adjustable soft-start and a PGOOD output. The LM51561H is the
same part with hiccup-mode overload protection, on the same footprint.

Datasheet values that constrain the design (LM5156H, SNVSBV2):

| Parameter | Value | Design consequence |
|---|---|---|
| FB reference | 1.00 V ±1 % | Sets V_b through the feedback divider |
| Switching frequency | 100 kHz-2.2 MHz set by RT (220 kΩ → 100 kHz) | Run near the low end: DCM at our light load, lower switching loss at 150 V |
| Maximum duty cycle | 93 % typ, 90 % min at 100 kHz (85 % at 2.2 MHz) | CCM at full load would need 93 %, so the boost **must operate in DCM**. At the 4.4 mA design load DCM needs D ≈ 0.33 (100 µH, 100 kHz, illustrative values). Verify at startup and low input |
| Minimum on-time | ~180 ns at 100 kHz (Fig. 8-12); 50 ns at 2.2 MHz | Even 0.5 mA load needs ~1.1 µs on-time: margin |
| Gate drive (VCC) | 6.85 V typ (6.5-7.0 V) | MOSFET must be specified at V_GS ≤ 6 V, rated ≥ 250 V |
| Current-limit threshold | 100 mV ±7 % (CS abs max 0.3 V) | Sense resistor sets the cycle-by-cycle limit |
| EN/UVLO | On above 0.52 V (0.4-0.7 V); switching above UVLO 1.5 V; abs max V_BIAS + 0.3 V; must not float | Pull-down resistor plus direct RP2040 drive (3.3 V > 1.575 V max) |
| Shutdown current | 2.6 µA typ at 12 V | |
| OVP | FB above 110 % of V_REF | Tracks FB, so it does **not** cover an open feedback divider |
| PGOOD | Open drain, low when FB < 90 % of V_REF; abs max 18 V | Pull up to 3V3 and read on an RP2040 input |
| Package | HTSSOP-14 (PWP), 0.65 mm pitch, exposed pad to AGND | **Accepted** (user, 2026-10-06): hand assembly with solder paste under a microscope, at the limit of the user's skill. Footprint: paste-reduced exposed-pad aperture, thermal vias to the bottom ground plane so the pad can also be reflowed from the back, and generous fanout so reworking it is practical |

**Shutdown (D7), proposed scheme:** a pull-down resistor on EN/UVLO and the RP2040's `HV_EN` output
drives it through a series resistor. Unpowered, in reset or in BOOTSEL, the pin is low and the
converter is off. No line UVLO divider: a divider from 12 V would turn the converter on without
the RP2040. The RP2040 measures the 12 V input itself and withholds `HV_EN` when it is low.

**Independent overvoltage shutdown, proposed:** if the top resistor of the feedback divider fails
open, FB falls to 0 and the converter runs to its current limit with no voltage limit. A second,
independent divider from **HV** (the regulated quantity since Phase 1B) drives the TLV3011
comparator, which pulls EN/UVLO low above roughly 110 % of the 500 V setting (550 V). The RP2040 also measures HV and can drop `HV_EN`,
but that does not replace a hardware limit.

**Variant choice (LM5156H vs LM51561H):** hiccup mode limits stress during a sustained HV short
(a probe slip or arc), but may also trip while the tripler capacitors charge at startup. Simulate
startup in 1B with the slowest soft-start that is acceptable; decide the population option from
that. Both fit the same footprint.

### HV load budget (D3)

| Load | At HV (450 V) | Basis |
|---|---|---|
| Tube via anode resistor | ≤ 0.43 mA | D1 worst case |
| Bleeder 4.7 MΩ | 96 µA (106 µA at 500 V) | Discharge 450 → 50 V in 5-10 s for 0.5-1 µF effective output capacitance; measure in 1D (D12) |
| HV monitor divider 8.85 MΩ | 51 µA | `HV_SENSE`, see [RP2040-Zero pin assignment](#rp2040-zero-pin-assignment) |
| Feedback divider 4.41 MΩ | 102 µA | Feedback moved to HV in Phase 1B |
| OVP divider (4 parts, ~9 MΩ) | ~50 µA | Independent OVP on HV |
| **Total / design value** | ≈ 0.73 mA / **1 mA** | ~1.4× margin |

| Load at boost node V_b | Current | Basis |
|---|---|---|
| Tripler, reflected | 3 mA | 3 × 1 mA design value |
| Guide pull-ups, both conducting | 0.38 mA | 2 × 90 V / 470 kΩ |
| G+ / RTN regulator feeds | 1 mA | Allowance, refine in 1B |
| **Total** | **≈ 4.4 mA, 0.66 W at 150 V (0.73 W at 167 V)** | |

At an assumed 75 % efficiency that is ~75-80 mA from 12 V. The HV section is a small part of the
12 V budget; the 5 V rail and the Nixie module dominate (D5).

### Guide drivers (D8)

One identical channel per guide (G1, G2):

```
G+ (90 V) ──[R_PU 470k]──┬──────────── guide pin (G1 = pin 5, G2 = pin 10)
                         │
                         C
 GUIDE_n ──[R_B 10k]──┬──B  Q: MMBTA42 (NPN, 300 V, SOT-23)
 (RP2040)             │  E
                  [R_BE 47k]│
                      │  │
                     GND GND
```

| Item | Value | Basis |
|---|---|---|
| Rest | Guide at G+ = RTN + 40 V (D1) | Transistor off |
| Pulse | Guide pulled to V_CE(sat) ≈ 0 V, i.e. −50 V vs. the cathodes | Reference practice (D1) |
| Collector current, on | 0.62 mA: 0.19 mA pull-up + ≤ 0.43 mA glow current while the glow sits on the guide | D1 worst-case tube current |
| Base current | 0.24 mA from 3.3 V: (3.3 − 0.75)/10k minus 0.75/47k | Forced β ≈ 2.6 against h_FE ≥ 25 at 1 mA (Nexperia MMBTA42): deep saturation |
| RP2040 load | 0.24 mA per pin | Trivial |
| Voltage stress | V_CE ≤ G+ = 90 V | MMBTA42 V_CEO 300 V |
| Release (rise) | τ = 470k × (C_re ≤ 3 pF + electrode and wiring) ≈ 5-9 µs for 10-20 pF; 10-90 % in 10-21 µs | Small against the 5 ms step period at 200 steps/s |
| Reset state | R_BE holds Q off: both guides at rest while the RP2040 is unpowered, in reset or in BOOTSEL | D7 |

* **Why the glow moves on.** While the glow sits on a guide, its current flows through Q to ground.
  When Q releases, the guide can only rise through 470 kΩ; 0.4 mA through 470 kΩ would need
  188 V, more than G+, so the glow cannot stay and transfers to the next main cathode.
* **RTN must not depend on tube current.** While the glow is on a guide, the tube current bypasses
  RTN entirely. The RTN shunt regulator therefore needs its own bias feed, sized so it stays in
  regulation with zero tube current (the 1 mA allowance in D3). Simulate this in 1B.
* **Step sequence** (one main-cathode step clockwise; reverse the order for the other direction):
  G1 on → G2 on → G1 off → G2 off, all from rest. Phase durations are firmware parameters, set at
  bring-up within the 200 steps/s budget; the datasheet limit is 1 kHz counting.
* **Resistor voltage ratings.** The 470 kΩ pull-up sees up to 90 V, within a 1206 part's rating
  (see [Component conventions](#component-conventions)).

### Index sense (D9)

```
RTN (50 V) ──┬───────────────[R_E 220k]──┐
             │                           │
             B   Q: MMBTA92 (PNP, 300 V) E ──── K1 (pin 13, index cathode)
                                         C
                                         │
                                   [R15 220k]
                                         │
 NDX (RP2040, ADC-capable pin) ──────────┼──[C 1 nF]── GND
                                         ├──[R16 13k]── GND
                                         └──|>|── 3V3   (Schottky clamp)
```

| Item | Value | Basis |
|---|---|---|
| Glow on K1 | K1 rises to RTN + V_EB; Q saturates; collector ≈ RTN + 0.4 V | Reference circuit topology |
| Output high | (RTN + 0.4) × 13k / 233k = **2.67 / 2.81 / 2.95 V** at RTN = 47.5 / 50 / 52.5 V (±5 % zener) | RP2040 V_IH = 2.0 V min at IOVDD 3.3 V (datasheet Table 625) |
| Output low | 0 V: R_E holds K1 at RTN, Q off, R16 pulls down | |
| Current split, glow on K1 | 0.22 mA through the divider, the rest of the ~0.4 mA via the base into RTN | RTN regulator sinks it (D8 note) |
| Fault: RTN regulator fails to V_b (167 V) | Unclamped output 9.3 V; the clamp conducts 0.74 mA through R15 into 3V3 | Clamp is mandatory. R15 is a 2 × 110k string for the 167 V fault |
| Filter | 1 nF with 12.3 kΩ Thevenin: τ = 12 µs | Sample ≥ 60 µs (5τ) after both guides return to rest (plan §5: check index only at a settled phase) |
| Reset/unpowered | Q is driven by the tube only; with the RP2040 unpowered the clamp to an unpowered 3V3 rail limits the pin | Check the RP2040's unpowered-pin limits in 1B |

* **Use an ADC-capable pin** (RP2040 GPIO26-29). Firmware normally reads it digitally (Schmitt
  input), and the analog level is available for diagnostics, e.g. a weak or intermittent glow.
* The other nine cathodes return to RTN directly. Per plan §5, each is broken out through a link or
  test pad so more sensing channels can be added later without a respin.

### Test provisions (D11)

Plan §9 brings the board up section by section on the final PCB, so each section can be cut off.
Links are **0 Ω 1206** on low-voltage nets and **wire-link footprints at ≥ 7.62 mm pitch** on HV
nets (desolder to open; the open gap then meets the HV clearance rule).

| Link | Opens | Used in bring-up step |
|---|---|---|
| L1 | Protected 12 V → HV boost (BIAS and inductor) | 1: low-voltage rails without the converter |
| L2 | 5 V buck output → board 5 V loads and external feeds | 1: check the buck unloaded |
| L3 | V_b → tripler input | 2: boost stage alone on a dummy load at V_b |
| L4 | Tripler output (after the bleeder) → anode resistor string | 2: HV on a dummy load, tube section isolated |
| L5 | V_b → G+ / RTN regulators | 3: bias rails brought up separately |
| L6-L14 | Each RTN cathode (K0, K2-K9) → RTN | Plan §5 cathode access; also isolates single cathodes |
| JP_HVINH | 2-pin header: shunt fitted = EN/UVLO held low | Any time: HV cannot start, whatever the firmware does |

* **Dummy-load footprints**, unpopulated in normal use: a 1206 string at V_b (about 34 kΩ for
  4.4 mA) and one at HV (4-6 parts for 0.5-1 mA at 450-500 V, ≤ 150 V per part). Populated for
  step 2, removed afterwards.
* **Test points**: `VIN_PROT`, `5V`, `3V3`, `VCC` (LM5156), `SW` (switch node, with an adjacent
  ground for a short scope-ground spring), `V_B`, `HV` (`HV`-class clearance, silkscreen warning),
  `G+`, `RTN`, `G1`, `G2`, `NDX`, `HV_EN`, `PGOOD`, and a `GND` point at each section. HV test
  points are for bring-up with rated probes only; in the enclosure all HV nodes are inaccessible
  (plan §4).

### Discharge (D12)

* **Bleeder:** 4.8 MΩ (4 × 1.2M, ≤ 150 V per part) directly across the tripler output, upstream
  of link L4, so it stays connected whatever is isolated. It is never switched, so discharge needs
  no firmware.
* **V_b node:** discharged by the always-connected 1.51 MΩ feedback divider (D2). G+ and RTN
  discharge through their regulators and feeds.
* **Target:** every node **below 50 V within 10 s** after `HV_EN` falls or 12 V is lost, by the
  passive path alone.
* **Capacitance budget:** τ = 4.8 MΩ × C_eff, so 550 V (OVP trip) → 50 V in 10 s requires
  **C_eff ≤ 0.87 µF** as seen from the HV node. The tripler and output capacitors are sized in 1B
  against this; if they exceed it, lower the bleeder (raising its current in D3) rather than relax
  the target.
* **Measured in 1D** (plan §9): discharge curve from 450 V and from the 500 V setting.
* Optional, decide in 1B: a neon indicator across HV through its own string, which glows while HV
  is present without firmware. It costs about 0.3 mA of HV load.

### Clearance and ratings (D13)

**The board is uncoated:** no credit is taken for solder mask or conformal coating, so rules use
the IPC-2221B **B2** column (external conductors, uncoated, sea level to 3050 m). 301-500 V row:
2.5 mm, plus 0.005 mm per volt above 500 V (Altium and Viox IPC-2221B calculators).

| Net class | Members | Design maximum | IPC-2221B B2 | Rule (to any other class) |
|---|---|---|---|---|
| `HV` | Tripler stage nodes, HV output, bleeder and monitor string tops, anode string, tube anode | 550 V (OVP trip, 110 % of the 500 V rating) | 2.75 mm | **3.0 mm** |
| `VB` | V_b, switch node | 200 V (≈ 195 V at the 550 V OVP trip with HV feedback) | 1.25 mm (151-300 V row, *verify*) | **1.5 mm** |
| `BIAS` | G+, RTN, guides, cathodes, index high side | 100 V | 0.6 mm (51-100 V row, *verify*) | **0.8 mm** |
| `LV` | 12 V and below | 25 V (TVS clamp) | 0.1 mm | Fab minimum |

* *Verify*: these rows were not legible in the sources consulted. Check them against the IPC-2221B
  table before freezing the KiCad rules; the rules above already carry margin.
* **Inside series strings** adjacent nodes differ by ≤ 150 V, so string-internal nets get their
  own net class at the 1.5 mm rule. A 1206 footprint's pad gap (≈ 1.8-1.9 mm; check the chosen
  footprint) satisfies it. The 3.0 mm `HV` rule applies between a string and anything else.
* Implemented as KiCad net classes plus custom rules (`.kicad_dru`), recorded in development.md.
* **Component ratings:** every part rated ≥ 1.5 × its maximum simulated voltage at OVP trip.
  Multiplier diodes ≥ 600 V (D2). Capacitor ratings follow from the 1B tripler simulation (a
  capacitor across the full HV needs a 630 V part or a series pair). Resistors: series strings,
  ≤ 150 V per part ([Component conventions](#component-conventions)).
* **Wire:** harness conductors that carry HV are 600 V-insulated (e.g. UL1015).

### Harness landings (D14)

**Decision (user, 2026-10-06):** wires solder directly to the board, with connectors only at the far
end where a module needs one. The dekatron harness is soldered at both ends, to the board and to
the socket. This saves space and avoids connector voltage ratings; it follows nanovolt-divider's
display harness. The tube itself still plugs into its socket, so a tube can be swapped.

| Landing | Wires | Far end |
|---|---|---|
| `PWR_IN` | `+12V_IN`, `GND` | Panel switch, then the chassis barrel jack |
| `NIX_12V` | `+12V_NIX`, `GND` (after its resettable fuse) | Purchased Nixie HV module input |
| `DISP` | `5V_DISP`, `GND` (power), `GND` (I2C), `SCL`, `SDA` | The display module's UART/power plug (5V, GND) and SPI plug (IO18 = SCL, IO27 = SDA), plus the 3V3 plug's GND ([Display harness](#display-harness)) |
| `NIX_LV` | `5V_NIX`, `GND`, `SDA`, `SCL`, `GND`, spare (e.g. global blank) | Nixie controller board (Phase 2) |
| `TUBE` | Anode, G1, G2, K1 (index), K0, K2-K9: 13 wires | A101 socket, soldered |
| `JP_HVINH` | 2.54 mm header + shunt (a bench jumper, not a harness) | — |
| — | RP2040-Zero programming: its own USB-C, BOOT and RESET at the board edge; no SWD on its edge pads | — |

Rules for every landing:

* **Silkscreen signal names at every pad, never only numbers.** nanovolt-divider's numbered silk
  did not match its module and invited a reversed 5 V.
* **Strain relief at the board:** each harness passes through a relief hole (wire through a
  larger hole, then back to its pad) or a cable-tie slot before it reaches its pads, so pulling the
  harness never loads a solder joint. Same at the socket end of `TUBE`.
* **Pads sized for the wire:** plated through-holes sized for the chosen gauge; power pads
  (`PWR_IN`, `NIX_12V`) larger than signal pads.
* **Grouping:** each landing is one contiguous group, in harness order, matching the module's pin
  order where the far end is a module plug.
* **`TUBE` spacing:** the anode pad sits apart from the other twelve by at least the 3.0 mm `HV`
  rule, with its own silkscreen HV mark. Anode wire is 600 V-insulated (e.g. UL1015); the other
  tube wires carry ≤ 100 V but use the same wire for simplicity. The anode resistor string stays
  on the board, so the harness only carries current-limited HV (≤ 0.7 mA into a short).
* **Cathode links:** all nine RTN cathodes are wired separately, so links L6-L14 stay on the board
  (plan §5).
* **Verification:** a wrong pad replaces a wrong socket as the risk, so every harness gets an
  unpowered continuity check against this table before first power ([bringup.md](bringup.md),
  step 0).
* With this board unpowered, the I2C bus idles low through the pull-ups to an unpowered rail.
  Firmware on both sides treats a missing peer as absent without hanging (plan Phase 3 exit
  criterion).

### RP2040-Zero pin assignment

Only the castellated edge pads are used: **GP0-GP15 and GP26-GP29** (20 GPIOs; Waveshare
schematic, header P1). GP17-GP25 exist only as pads under the module, which a headerless module
soldered by its edges cannot reliably reach. GP16 drives the module's WS2812 LED, which firmware
keeps dim or off (D5).

| Pin | Signal | Dir | Function | Notes |
|---|---|---|---|---|
| GP0 | `UART_TX` | out | UART0 TX | Test pad: debug console that keeps working while USB is busy flashing or enumerating |
| GP1 | `UART_RX` | in | UART0 RX | Test pad |
| GP2 | `SDA` | bidir | I2C1 SDA (target) | To `DISP` and `NIX_LV`; 4.7 kΩ pull-up to this board's 3V3 |
| GP3 | `SCL` | bidir | I2C1 SCL (target) | Same |
| GP4 | `GUIDE1` | out | PIO | G1 driver base (D8) |
| GP5 | `GUIDE2` | out | PIO | G2 driver base (D8); adjacent to GP4 so one PIO program drives both |
| GP6 | `HV_EN` | out | GPIO | LM5156 EN/UVLO through its series resistor; external pull-down (D7) |
| GP7 | `PGOOD` | in | GPIO | LM5156 PGOOD, open drain, 10 kΩ pull-up to 3V3 |
| GP8 | `OVP_TRIP` | in | GPIO | Independent OVP comparator output, so firmware can report why HV dropped (D2) |
| GP12 | `NIX_SPARE` | — | GPIO | To the `NIX_LV` spare wire through a 0 Ω link (e.g. global blank) |
| GP9-GP11, GP13-GP15 | — | — | spare | Broken out to test pads. (GP9-GP11 were the encoder fallback; the encoder moved to the Nixie board) |
| GP16 | `LED` | out | WS2812 | On the module |
| GP26 | `NDX` | in | ADC0 / Schmitt input | Index (D9); digital read normally, analog level for diagnostics |
| GP27 | `VIN_SENSE` | in | ADC1 | Protected 12 V: 100k / 12k → 1.29 V at 12 V, 2.57 V at the 24 V TVS clamp |
| GP28 | `HV_SENSE` | in | ADC2 | HV: 4 × 2.2M / 47k → 2.39 V at 450 V, 2.92 V at 550 V (OVP); 137 V per part at 550 V |
| GP29 | `RTN_SENSE` | in | ADC3 | RTN: 2 × 100k / 10k → 2.38 V at 50 V, 2.86 V at 60 V |

Facts this relies on, from the RP2040 datasheet:

* **Reset state** (Table 341, PADS_BANK0): every GPIO resets as an input with the pull-down
  enabled (PDE = 1, PUE = 0, IE = 1, Schmitt on). The board does not rely on this: `HV_EN` and the
  guide bases have external resistors that hold the safe state while the
  module is unpowered.
* **Input thresholds at IOVDD = 3.3 V** (Table 625): V_IH 2.0 V min, V_IL 0.8 V max, 0.2 V
  hysteresis with Schmitt enabled. The index output's worst case, 2.67 V (D9), clears V_IH by
  0.67 V.
* **ADC reference:** the Zero feeds ADC_VREF from its 3.3 V LDO through 200 Ω (Waveshare
  schematic), so readings are ratiometric to that rail, good to a few percent. That is enough
  for diagnostics; nothing here regulates from ADC readings.

Rules for the analog inputs:

* Every ADC input whose source can exceed 3.3 V in a fault (`NDX`, `HV_SENSE`, `RTN_SENSE`,
  `VIN_SENSE`) gets a Schottky clamp to 3V3. For example, an open `RTN_SENSE` bottom resistor
  would otherwise present 7.95 V with RTN failed to V_b.
* Each ADC input gets a local capacitor (~100 nF; 1 nF on `NDX`, which needs speed, D9) so the
  ADC's sampling charge comes from the capacitor, not from the high-impedance divider.
* Firmware disables the digital input buffer on ADC pins that are read only as analog
  (`VIN_SENSE`, `HV_SENSE`, `RTN_SENSE`).
* The HV monitor string is always connected and adds 51 µA at 450 V to the HV load (D3 total
  becomes ≈ 0.58 mA, within the 1 mA design value). It also discharges HV, but the D12 budget
  counts only the bleeder.

### A101 pinout

| Pin | Electrode | Role here |
|---|---|---|
| 1 | K0 | Main cathode → RTN |
| 2 | K9 | Main cathode → RTN |
| 3 | K8 | Main cathode → RTN |
| 4 | K7 | Main cathode → RTN |
| 5 | G1 | Guide 1 |
| 6 | K6 | Main cathode → RTN |
| 7 | K5 | Main cathode → RTN |
| 8 | Anode | Via anode resistor to HV |
| 9 | K4 | Main cathode → RTN |
| 10 | G2 | Guide 2 |
| 11 | K3 | Main cathode → RTN |
| 12 | K2 | Main cathode → RTN |
| 13 | K1 | **Index** (sensed) |

Applies to the user's stock A-101 socket (D10). Sources: tube-tester.com pin list, and the AD01 "Dekatron Hook-up" table (A101: anode 8, index 13,
RTN 1-4, 6, 7, 9, 11, 12, G1 5, G2 10). They agree. The AD01 page text once calls the index
"pin 12", contradicting both. Plan §5 asks for accessible cathode links: break out each RTN pin
through a link or test pad rather than tying them together under the socket.

### 12 V input protection (D4)

The input arrives by wire from the chassis barrel jack and carries everything: this board, and
12 V onward to the purchased Nixie HV module. In order from the input connector:

| Element | Proposal | Reason |
|---|---|---|
| Power switch | Panel switch in series with the +12 V wire between jack and board, rated ≥ 3 A DC | Plan §4. Placement decided with the enclosure |
| Fuse | 2 A slow-blow on the board input | Input is ≈ 0.75 A estimated (below); slow-blow survives bulk-capacitor inrush |
| Reverse polarity | P-channel MOSFET, gate to ground through a resistor with a gate-source zener | Adapters of either polarity exist. A Schottky would waste ~0.3 W at 0.75 A |
| TVS | SMBJ15A-class (15 V standoff) after the MOSFET | Clamps hot-plug ringing. Every 12 V consumer must be rated above the clamp voltage (~24 V): LM5156 BIAS (65 V abs max) and the 5 V buck (choose ≥ 28 V input) |
| Bulk capacitance | Electrolytic, ~100 µF, plus local ceramics | Damps the LC ringing that ceramic-only input capacitance causes when a live adapter is plugged in |
| Nixie module branch | Separate resettable fuse (~0.75 A hold) on the 12 V output to the Nixie module | A fault in the purchased module must not blow the main fuse or reach this board's input |
| Input monitoring | Divider from protected 12 V to an RP2040 ADC (`VIN_SENSE`) | Firmware withholds `HV_EN` while 12 V is low or absent (D7) |

### Power budget

Estimates for sizing; each has its basis, and measurement replaces it in 1D.

| Load | Rail | Peak estimate | Basis |
|---|---|---|---|
| ESP32 display board | 5 V | 350 mA | ~115 mA measured with backlight at 100 % (mischianti.org CYD page); ESP32 Wi-Fi transmit adds up to ~240 mA if Wi-Fi is enabled. **Measure on the actual board** |
| RP2040-Zero, dekatron board | 5 V | 50 mA | RP2040 plus its on-board WS2812 LED, which firmware keeps dim or off |
| RP2040-Zero, Nixie board | 5 V | 50 mA | Same |
| K155ID1 × 6 | 5 V | 150 mA | ≤ 25 mA each as SN74141 equivalent; **confirm K155ID1 data** |
| Nixie board expanders, dekatron logic | 5 V | 30 mA | Allowance |
| **5 V total** | | **≈ 630 mA** | Buck rated **2 A** (> 3× margin, covers Wi-Fi bursts and estimate error) |
| 5 V buck input | 12 V | 0.31 A | 630 mA × 5 V / 85 % |
| HV converter | 12 V | 0.08 A | D3 at 75 % efficiency |
| Purchased Nixie HV module | 12 V | 0.36 A | 20 mA × 170 V / 80 % assumed module efficiency; qualify in Phase 2 |
| **12 V total** | | **≈ 0.75 A** | Adapter: **12 V, 2 A regulated**, 2.1 mm centre-positive (still protected against reversal) |

5 V buck (nominal setpoint **4.9 V**, see D6): a 12 V → 5 V synchronous buck IC rated 2 A with ≥ 28 V input rating, chosen in 1B
(e.g. TPS54202-class in SOT-23-6, which is easy to hand-solder). Its output feeds this board's
logic and the two external 5 V feeds below.

### USB power paths (D6)

Both 5 V modules have their own USB connector, and both are plugged into a computer at some
point (ESP32 host interface; RP2040 flashing and debug). What their schematics show:

**ESP32-2432S028R** (original V0.1 schematic, `docs/datasheets/cyd/ESP32-2432S028-MCU.jpg`):

* USB VBUS → **1N5819W Schottky** (D1) → module 5V net. The host is protected from back-feed.
* P1 `VIN` → **AO3401 P-MOSFET** (Q1, gate grounded) → module 5V net. This is reverse-polarity
  protection, not reverse blocking: once its body diode conducts, the MOSFET turns on and passes
  current **both ways**.
* Consequence: with USB plugged in and this board unpowered, the module drives ~4.6 V *out* of
  its P1 `VIN` pin into our 5 V rail, trying to power our logic from the computer's USB port.

**RP2040-Zero** (Waveshare `RP2040_Zero.pdf`, `docs/datasheets/rp2040_zero_sch.pdf`):

* USB-C VBUS connects **directly** to `VSYS` (header pin 23, the "5V" pin), which feeds the
  RT9013-33 LDO. **No diode.** (Some summaries online claim diode separation; the schematic shows
  none.)
* Consequence: feeding the Zero's 5V pin from our rail while its USB is plugged in ties our 5 V
  supply to the computer's VBUS.

**Decision (user, 2026-10-06):** every 5 V feed to a module with its own USB goes through a
**reverse-blocking ideal diode**, one reused design block (LM66100-class: 1.5-5.5 V, 1.5 A, reverse-current blocking; verify the datasheet in 1B):

| Feed | Normal (12 V on) | Module USB plugged, 12 V on | Module USB plugged, 12 V off |
|---|---|---|---|
| `5V_DISP` → CYD P1 `VIN` | Board powers CYD | The higher source supplies the CYD 5V net; CYD's D1 protects the host, our ideal diode protects our rail | CYD runs from USB; ideal diode blocks back-feed into our board |
| `5V_MCU` → RP2040-Zero `VSYS` | Board powers Zero | The higher source wins: if VBUS is higher, our diode blocks. If ours is higher, current flows toward the host's VBUS (see residual case below) | Zero runs from USB (standalone debug); our side stays dark |

**Residual case (accepted, mitigated):** the Zero's VBUS and VSYS are one net, so no diode on our
side can stop *our* rail from feeding a host whose VBUS is lower than ours while both are
connected. Mitigation: set the 5 V rail to **4.9 V nominal**, inside the K155ID1 supply range
(4.75-5.25 V) and below a typical host VBUS (5.0-5.1 V), so the host normally wins and our ideal
diode blocks. Verify in 1D by measuring current in the `5V_MCU` feed with the Zero's USB attached.

**No isolator required.** The instrument must be safe and correct with a plain USB cable to the
host. The 12 V adapter is isolated, so connecting a host adds one ground reference and no ground
loop. A USB isolator is a test-bench accessory only (user, 2026-10-06).

Alternatives considered (standard practice for VBUS back-feed): Schottky diode-OR (Raspberry Pi
Pico style; its drop would give the host priority on the Zero feed), power-multiplexer ICs
(TPS2116/TPS2121 class), VBUS-blocking cables, and USB isolators. Ideal diodes everywhere were
chosen for one uniform design block.

A Schottky diode instead of an ideal diode would drop ~0.3-0.4 V. That leaves the CYD's
AMS1117-3.3 (≈ 1.1 V dropout) with little margin, so an ideal diode is preferred for both feeds.

**Cross-domain hazard to design out:** with the Zero powered from USB and 12 V off, RP2040 outputs
can drive into unpowered circuits. LM5156 EN/UVLO has an abs max of V_BIAS + 0.3 V, i.e. 0.3 V
when unpowered. The series resistor on `HV_EN` must limit that current, and firmware must never
assert `HV_EN` without `VIN_SENSE` reading a valid 12 V. Check the same for I2C pull-ups and guide
driver bases in 1B.

Verify on the user's actual module that it matches the V0.1 schematic: with only USB connected,
P1 `VIN` reading ~4.6 V confirms the back-feed path.

## Component conventions

* **Passives are 1206 SMD by default** (user, 2026-10-06): easier hand soldering and more voltage
  margin. Deviate only with a recorded reason (e.g. a part available only in another package).
* **High voltage is handled with series strings of standard 1206 parts** (user, 2026-10-06),
  built from the user's 1206 kit rather than special high-voltage resistors. Design rule:
  **≤ 150 V across any single resistor** (75 % of the typical 200 V standard-1206 rating; the
  kit's own rating is unknown). Values are chosen from E24.
* Lay strings out in a line along the voltage gradient, so the spacing between their ends also
  grows with the voltage (clearance rules: D13).

| Resistor | Voltage across it | String |
|---|---|---|
| Anode resistor (D1) | ≈ 250-300 V while the tube conducts | 3 × 220k (450 V) or 3 × 270k (500 V); ≤ 100 V per part |
| Bleeder (D3) | Full HV, up to 500 V | 4 × 1.2M = 4.8 MΩ; 125 V per part, 94 µA at 450 V |
| HV monitor divider top (D2) | Full HV, up to 500 V | 4 parts, ≤ 125 V each; values in 1B |
| Feedback divider top (V_b, D2) | Up to 167 V | 2 × 750k = 1.5 MΩ; 84 V per part; bottom ≈ 10.1 kΩ sets 150 V |
| Index R15 (D9) | 50 V; 167 V if the RTN regulator fails | 2 × 110k = 220 kΩ; 84 V per part in the fault case |
| Guide pull-ups 470k (D8) | ≤ 90 V | Single part |

## Display harness

The ESP32-2432S028R exposes three 4-pin connectors (signals in the order printed on the module):

| Module connector | Signals |
|---|---|
| UART / power | RXD, TXD, GND, 5V |
| 3V3 | 3.3V, IO35, *(nc)*, GND |
| SPI | IO23 (MOSI), IO19 (MISO), IO18 (SCK), IO27 (CS) |

Carried over from nanovolt-divider (its `docs/hardware.md`, "Display harness"):

| Signal | Module pin | Notes |
|---|---|---|
| +5V | UART / power: **5V** | Here supplied *to* the module by the dekatron board's buck (see D6) |
| GND | UART / power: **GND** | Power return |
| +3V3 | 3V3: **3.3V** | Module's own regulator output |
| GND | 3V3: **GND** | I2C return |
| SDA | SPI: **IO27** | `Wire.begin(/*SDA*/ 27, /*SCL*/ 18)` |
| SCL | SPI: **IO18** | Also the microSD SCK |

* **Land wires by signal name, never by pad number** (the divider's silk numbers did not match the
  module, and a reversed 5 V is one wrong pad away).
* IO35 cannot drive I2C (GPIO34-39 are input-only), and RXD/TXD carry the USB-serial host
  interface, which is why the bus lives on the SPI connector.
* **The module has no pull-ups on IO18/IO27.** The bus pull-up must be on a controller board;
  proposed: on the dekatron board, the one board always present in a standalone build.
* **IO18 is shared with microSD SCK.** Rev A omits microSD (plan §8), so no bus arbitration is
  needed as long as the card's CS (IO5) stays deasserted.

### Encoder

**Decision (user, 2026-10-06):** the rotary encoder mounts on the **Nixie controller board**, not
on the dekatron board. The Nixie board's RP2040 decodes it and reports a cumulative detent count
and button events over I2C ([i2c_protocol.md](i2c_protocol.md#nixie-controller)); the ESP32 owns
their meaning (plan §8). A cumulative count lets the ESP32 poll without losing detents.

The display module's IO19, IO23 and IO35 stay unused (free for later), and microSD stays omitted
(plan §8).

## Power sheet (Phase 1B)

Draft values for the `power` hierarchical sheet: 12 V input, 5 V, and the HV converter. The G+
and RTN regulators belong to the `tube` sheet. Simulation benches live in
`hardware/dekatron/simulation/` ([README](../hardware/dekatron/simulation/README.md)).

### HV boost stage

| Item | Value | Basis |
|---|---|---|
| Controller | LM5156H (D2) | |
| Switching frequency | 100 kHz, R_T = 220 kΩ | Low end: DCM at light load, low switching loss at 150 V |
| Inductor | 100 µH, Bourns SRR1260-101M (I_sat 1.7 A, DCR 180 mΩ max, shielded) | DCM check below |
| Sense resistor | 0.13 Ω → cycle limit 0.71-0.82 A (100 mV ±7 %) | Peak power ½·L·I²·f ≈ 2.2 W in DCM vs. ≈ 0.92 W needed (0.73 W at 167 V, 80 % assumed) |
| DCM margin | t_on + t_off = L·I_pk·(1/V_IN + 1/(V_b − V_IN)) ≈ 6.6 µs < 10 µs at 0.77 A, 10.8 V in | Stays DCM even at the current limit and −10 % input |
| CS filter | 100 Ω + 470 pF (47 ns) | **Required:** see pump surge below |
| MOSFET | **AOS AOD5N40: 400 V**, 1.6 Ω max at V_GS = 10 V, V_th 3.4-4.5 V, Q_g 6.9 nC, DPAK | 2.05× margin at the worst case (below). Chosen over logic-level parts (user, 2026-10-06) |
| Gate drive | **10 V**: LM5156 in BIAS = VCC mode (datasheet: 2.97-16 V), fed by an **LP2951** (30 V max input, 100 mA, 380 mV dropout, adjustable, SOIC-8) from the protected 12 V | Internal VCC (6.85 V) is too low for a 4.5 V-threshold MOSFET. Load ≈ 1 mA (Q_g × f + bias). The LP2951 input rating covers the ≈ 24 V TVS clamp |
| Boost diode | ES1J: 600 V, 1 A, t_rr 35 ns, SMA | |
| Soft-start | C_SS = 47 nF (10 µA → 4.7 ms ramp) | LM5156H (no hiccup); start-up is energy-limited anyway |
| Compensation | 10 kΩ + 10 nF, 100 pF to ground | Smoke-test values; load-step check pending |
| Feedback | **From HV:** 4 × 1.1M / 9.8k → HV = 450 V (1.00 V ref); 500 V option: bottom ≈ 8.82k | Moved from V_b in simulation (see results). ≤ 150 V per part: 137 V each at 550 V |
| V_b bleeder | 2 × 1.2M (2.4 MΩ, 63 µA) | V_b's own discharge path when link L3 separates the boost from the tripler (D11) |

**MOSFET margin: resolved with a 400 V part.** With HV feedback the stack's per-stage shortfall
pushes V_b up: the simulated switch-node peak is 161-163 V at the 450 V setting, and scaling to the
500 V setting during an OVP trip (550 V) gives about 195 V. A 250 V logic-level part would have
had 1.28×, below the 1.5× rule (D13). Logic-level options at ≥ 300 V are small-signal parts: the
Nexperia BSP130 (300 V) is rated 350 mA continuous, 10 Ω max at V_GS 2.4 V, and 83 K/W, which
cannot carry the 0.82 A current limit through a long current-limited start or a shorted output.
Instead the gate drive rises to 10 V, and the **AOD5N40 (400 V) gives 400/195 = 2.05×**.
Simulated (`hv_warm.cir`, 4.0 V threshold model, 10 V drive): HV 449.1 V, tube 378 µA, switch
node 161 V, CS ≤ 0.10 V, the same as the logic-level design.

### Tripler

Series-stack Cockcroft-Walton driven from the switch node: pump capacitors CP1-CP2 in series from
the switch node, DC capacitors C1-C3 stacked from ground, diodes D1-D5 (ES1J). **Every capacitor
and diode sees at most V_b** (≈ 195 V at the 550 V OVP trip with HV feedback), so HV ≈ 3 × V_b
with no part across the full HV.

| Item | Value | Basis |
|---|---|---|
| Capacitors | 0.47 µF, 400 V, PET film, THT (WIMA MKS4 class) | 400 V = 2.05 × 195 V. Film instead of MLCC: no DC-bias capacitance loss, no piezo noise from a pulse-skipping supply. Deviation from the 1206 default, recorded here |
| Diodes | ES1J (600 V) | 3.1× V_b at OVP |
| Pump surge resistor | **47 Ω** between the switch node and CP1 | **Required:** see below |
| Ripple | < 1 V at 0.58 mA (I/(f·C) ≈ 12 mV per stage) | Checked in simulation |

**Pump surge (found in simulation).** At every turn-on the switch node falls and the pump
capacitors recharge from V_b *through the MOSFET and the sense resistor*. Without limiting, the
switch carried a 14 A spike and the CS pin saw 0.99 V even through the RC filter, above its 0.3 V
absolute maximum and ten times the current-limit threshold, so every cycle ended early. A 47 Ω
surge resistor brings the spike to ~1.9 A and the CS pin to ≤ 0.1 V. It costs little: average
pump current is ~1.2 mA. 100 Ω also works but charges the stack about half as fast.

### Simulation results

| Bench | Case | Result |
|---|---|---|
| `hv_discharge.cir` | Stop from 450 V, passive paths only | **Every node < 50 V in 1.47 s** (D12 target 10 s). Settles near 11 V while 12 V is present (input reaches the stack through the inductor and boost diode) |
| `hv_warm.cir` | Steady state, HV feedback, tube lit (stack precharged to 435 V) | **HV 449.2 V, 2.8 V p-p ripple, tube 378 µA** (D1 predicts 379 µA), V_b 156.8 V, PGOOD high |
| `hv_warm.cir`, tube held dark | Steady state with no tube current | **HV 453.3 V, 1.7 V p-p**, V_b 157.9 V, PGOOD high. Load regulation dark → lit 0.9 % |
| `hv_warm.cir`, V_b feedback (superseded) | Same, regulating V_b = 150 V | HV only 442 V with the tube dark: the reason feedback moved to HV |
| `hv_warm.cir` stresses | Peaks over the run | Switch node 161 V; capacitors ≤ 159 V (400 V parts); diode reverse ≤ 149 V (600 V); CS pin ≤ 0.10 V (0.3 V abs max); switch current spike 1.86 A with the 47 Ω pump resistor |
| `hv_startup.cir` | Cold start from 0 V, 40 ms, HV feedback | **Completes** (250 V logic-level MOSFET, 6.85 V drive): tube strikes at 9.7 ms; at 38-40 ms HV 449.9 V, 0.11 V p-p ripple, tube 379 µA, PGOOD high; switch node 163 V, CS ≤ 0.10 V, switch spike 1.87 A. Rerun with the 400 V MOSFET and 10 V drive in progress |

Model limitations: generic MOSFET and diode models (AOD5N40- and ES1J-like), film capacitors as
C + 0.1 Ω ESR (ESL omitted: nH parasitics ring faster than the 5 ns step resolves), and a
behavioural tube whose 380 V strike voltage is an assumption, not tube data. Efficiency is not
measured yet: the 1 ms averaging window falls inside the converter's burst pauses.

### 5 V and input (selected, simulation pending)

| Item | Part | Basis |
|---|---|---|
| Gate-drive LDO | TI LP2951, adjustable, set to 10 V | See HV boost stage |
| 5 V buck | TI TPS54202: 4.5-28 V in, 2 A, 500 kHz, SOT-23-6, Eco-mode; unencrypted PSpice model available | D5; 28 V > TVS clamp |
| Ideal diodes (D6) | TI LM66100: 1.5-5.5 V, 1.5 A, 79 mΩ at 5 V, reverse blocking, SC-70-6 | One block per external 5 V feed |
| OVP comparator | TI TLV3011 (open-drain; 1.242 V reference ±1 %, 1.8-5.5 V supply) from 5 V, sensing HV through its own 4-part string; output pulls EN/UVLO low and drives `OVP_TRIP` | TLV3012 is push-pull and cannot share the EN node |
| Reverse-polarity MOSFET, fuse, PTC, TVS | Part numbers chosen at schematic entry | D4 |

## Nixie controller/mount

Phase 2. Six IN-14 tubes, six K155ID1, current limiting, separate HV switches for decimal points,
blanking. Static drive preferred. Six BCD decoders need 24 signals plus DP and blanking, more than
an RP2040-Zero exposes comfortably: plan shift registers or expanders.

## Harness tables

_Defined in Phase 1A/2._ Every connector: pin, signal name, voltage, direction, keying.
