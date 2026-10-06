# Hardware

Electrical design, open decisions and harness tables. Values here are design records: an entry is
only filled in once it has a source (datasheet, measurement, simulation or explicit decision).

## Board revisions

Record the exact revision of every purchased module before footprints or pin maps depend on it.

| Item | Assumed | Confirmed revision / evidence |
|---|---|---|
| ESP32 display board | ESP32-2432S028R family (as in nanovolt-divider) | **Confirmed** (user, 2026-10-05): same module as nanovolt-divider — ESP32, CH340 USB serial, 320×240 ILI9341, XPT2046-type resistive touch, microSD. See [Display harness](#display-harness) |
| Controller MCU | RP2040-Zero (Waveshare) | **Confirmed** (user, 2026-10-05): RP2040-Zero, headerless. Mount by its castellated edge pads soldered directly to the carrier (no header stack height); footprint must also leave the USB-C connector and BOOT/RESET buttons reachable |
| A101 socket | Existing socket on hand | _open_ — dimensions, pin numbering |
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
| D2 | HV converter topology (direct boost / boost + multiplier / flyback / 12→5 V + AD01A-style) | **Proposed** | Boost to HV/3 plus Cockcroft-Walton tripler; see [HV converter](#hv-converter-d2) |
| D3 | HV output current budget (tube + bias + bleeder) and margin | **Proposed** | 1 mA at HV, about 4.4 mA at the boost node; see [HV load budget](#hv-load-budget-d3) |
| D4 | 12 V input protection: reverse polarity, fuse/PTC, TVS, inrush | Open | Barrel adapters of either polarity exist, so reverse-polarity protection is mandatory. Input arrives by wire from the chassis jack, not a board-mounted jack |
| D5 | 5 V buck capacity | Open | Sum ESP32/TFT, 2× RP2040, 6× K155ID1, converter control; measure CYD draw |
| D6 | USB power paths: VBUS isolation/selection for ESP32 USB and standalone RP2040 debug | Open | Inspect actual CYD and RP2040-Zero schematics. **Reversed vs. the divider:** there the CYD's 5V pin powered the board from USB; here the board's buck feeds that pin while CH340 USB may also be plugged in. Determine whether the CYD has any diode between VBUS and its 5V header before connecting both |
| D7 | HV enable default and defined tube state while the RP2040 is in reset/BOOTSEL | Open | Hardware pull-downs so reset = HV off / guides idle |
| D8 | Guide driver circuit and its input current at 3.3 V | Open | Reference drive is ~5 V logic |
| D9 | Index sense: threshold, level translation to 3.3 V, protection | Open | One sensed reference cathode in Rev A |
| D10 | A101 socket pinout, verified against the tube drawing | Partly resolved | Two independent sources agree (see [Pinout](#a101-pinout)); the reference page's "pin 12" text is the outlier. Still check continuity on the physical socket and a tube |
| D11 | Sectional test provisions: removable links, test points, dummy-load landing | Open | HV converter must be isolatable from the tube section |
| D12 | Discharge path and target discharge time | Open | Measure in 1D |
| D13 | Clearance/creepage rules for ~450 V, component voltage ratings | Open | Becomes the board's DRC rules |
| D14 | Connectors: 12 V in, 5 V out, I2C, programming access | Open | Keyed, pinout by signal name. 12 V in is a wire-to-board connector from the chassis jack; 12 V also onward to the Nixie HV module |

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
| Anode resistor | A: 680 kΩ; B: 820 kΩ, split into two series parts for voltage rating | Keeps 300-450 µA across V_m 130-170 V and HV ±5 % |
| Tube current | A: 305-430 µA (368 typ); B: 311-421 µA (366 typ) | Within datasheet 300-450 µA |
| Step rate | ≤ 200 steps/s for homing (plan §5) | Datasheet limit 1 kHz |

The datasheet supply figure (425 min / 450 typ) is referred to the cathodes. With cathodes at
+50 V, Option A gives the tube 400 V, below the datasheet minimum but more than the reference's
≤ 368 V, which works. Option B meets the datasheet typical. Anode resistor dissipation is ~0.1 W
in either case.

**Decision (user, 2026-10-05):** rate every HV component, clearance and the converter for
Option B (500 V), and set the regulator for Option A (450 V) at first bring-up. Raise the setpoint
only if striking or glow transfer is marginal. The setpoint is fixed by the feedback resistor, and
the anode resistor is paired with it (680 kΩ at 450 V, 820 kΩ at 500 V). Lay the anode resistor
out as two series footprints so either value can be fitted.

### HV converter (D2)

| Candidate | Assessment |
|---|---|
| Direct boost 12 → 450 V | Conversion ratio 37.5: duty ≈ 97 % in continuous mode, switch rated > 500 V plus ringing. Rejected |
| **Boost 12 → HV/3, CW tripler** | Duty ≈ 92 %, workable (the same class as common 12 → 170 V Nixie supplies). Switch sees only ~150-167 V. The boost node also supplies G+ and RTN directly, as in the reference. **Proposed** |
| Flyback 12 → 450 V | One magnetic, but a custom or scarce transformer, and G+/RTN would be derived from 450 V dissipatively. Not worth it at < 1 W |
| 12 → 5 V buck + reference AD01 circuit | Proven, but its 160 V 2N5551 switches cap the tripler at ~420 V, below the decided 450-500 V. Fallback only |

Proposed structure, to be refined and simulated in Phase 1B:

* Boost stage regulated at the **boost node, V_b = HV/3** (150 V for 450 V, 167 V for 500 V),
  as in the reference. Multiplier droop at ~1 mA is small, so regulating V_b sets HV closely
  enough for a tube whose current is set by its anode resistor. The RP2040 measures HV through
  a high-value divider for diagnostics only.
* Switch: an external MOSFET rated ≥ 250 V, driven from 12 V (the 5 V-input reason the reference
  used bipolar switches does not apply here).
* Controller IC: chosen in 1B. Requirements: 12 V supply, external MOSFET drive, an
  enable/shutdown input that defaults **off** when the RP2040 is in reset (D7), and
  current-mode or cycle-by-cycle current limit. Candidates to compare: UC3843 family, MAX1771,
  LT3757, MC34063 + gate driver.
* Multiplier diodes and capacitors rated for the 500 V case with margin (e.g. ≥ 600 V diodes,
  since the 250 V BAV21 used in the reference has too little margin at V_b = 167 V).

### HV load budget (D3)

| Load | At HV (450 V) | Basis |
|---|---|---|
| Tube via anode resistor | ≤ 0.43 mA | D1 worst case |
| Bleeder 4.7 MΩ | 96 µA (106 µA at 500 V) | Discharge 450 → 50 V in 5-10 s for 0.5-1 µF effective output capacitance; measure in 1D (D12) |
| **Total / design value** | 0.53 mA / **1 mA** | ~2× margin |

| Load at boost node V_b | Current | Basis |
|---|---|---|
| Tripler, reflected | 3 mA | 3 × 1 mA design value |
| Guide pull-ups, both conducting | 0.38 mA | 2 × 90 V / 470 kΩ |
| G+ / RTN regulator feeds | 1 mA | Allowance, refine in 1B |
| **Total** | **≈ 4.4 mA, 0.66 W at 150 V (0.73 W at 167 V)** | |

At an assumed 75 % efficiency that is ~75-80 mA from 12 V. The HV section is a small part of the
12 V budget; the 5 V rail and the Nixie module dominate (D5).

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

Sources: tube-tester.com pin list, and the AD01 "Dekatron Hook-up" table (A101: anode 8, index 13,
RTN 1-4, 6, 7, 9, 11, 12, G1 5, G2 10). They agree. The AD01 page text once calls the index
"pin 12", contradicting both. Plan §5 asks for accessible cathode links: break out each RTN pin
through a link or test pad rather than tying them together under the socket.

### Power budget

_To be filled for D3/D5._

| Load | Rail | Typ | Max | Source |
|---|---|---|---|---|

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

### Encoder pins (proposal)

With microSD unused, three GPIOs remain on the harness connectors: **IO19**, **IO23** (SPI
connector) and **IO35** (3V3 connector, input-only, no internal pull-up). That is exactly encoder
A/B plus push button, e.g. A = IO19, B = IO23, button = IO35 with an external pull-up. Interrupt-
or PCNT-driven decoding on IO19/IO23 avoids losing detents. The fallback in plan §8 (a controller
counts the encoder and reports it over I2C) remains available if these pins are needed elsewhere.
Status: _open_ — decide with the enclosure harness.

## Nixie controller/mount

Phase 2. Six IN-14 tubes, six K155ID1, current limiting, separate HV switches for decimal points,
blanking. Static drive preferred. Six BCD decoders need 24 signals plus DP and blanking, more than
an RP2040-Zero exposes comfortably: plan shift registers or expanders.

## Harness tables

_Defined in Phase 1A/2._ Every connector: pin, signal name, voltage, direction, keying.
