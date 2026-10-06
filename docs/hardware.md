# Hardware

Electrical design, open decisions and harness tables. Values here are design records: an entry is
only filled in once it has a source (datasheet, measurement, simulation or explicit decision).

## Board revisions

Record the exact revision of every purchased module before footprints or pin maps depend on it.

| Item | Assumed | Confirmed revision / evidence |
|---|---|---|
| ESP32 display board | ESP32-2432S028R family (as in nanovolt-divider) | **Confirmed** (user, 2026-10-05): same module as nanovolt-divider — ESP32, CH340 USB serial, 320×240 ILI9341, XPT2046-type resistive touch, microSD. See [Display harness](#display-harness) |
| Controller MCU | RP2040-Zero (Waveshare) | _open_ — confirm modules on hand and footprint |
| A101 socket | Existing socket on hand | _open_ — dimensions, pin numbering |
| Nixie HV module | Amazon B09D94N3MX | _open_ — qualify delivered version |
| 12 V adapter | Isolated 12 VDC | _open_ — current rating, connector |

## Dekatron controller/PSU

First deliverable. One KiCad project in `hardware/dekatron/` with hierarchical sheets:
**power** (12 V input, 5 V/3.3 V, HV converter), **tube** (bias, guide drivers, index sense),
**mcu** (RP2040-Zero, USB, I2C, links/test points).

### Phase 1A decision register

Exit criterion (plan §9): voltage/current requirements, logic levels, USB power paths, socket
pinout and sectional test provisions defined.

| ID | Decision | Status | Notes / inputs needed |
|---|---|---|---|
| D1 | A101 operating point: anode supply, anode resistor, tube current, guide bias and pulse amplitude | Open | From A101 data and the reference AD01A circuit; 420 V reference ≠ 450 V without review |
| D2 | HV converter topology (direct boost / boost + multiplier / flyback / 12→5 V + AD01A-style) | Open | Compare against D1 load incl. bias network and bleeder; controller IC availability |
| D3 | HV output current budget (tube + bias + bleeder) and margin | Open | Depends on D1 |
| D4 | 12 V input protection: reverse polarity, fuse/PTC, TVS, inrush | Open | |
| D5 | 5 V buck capacity | Open | Sum ESP32/TFT, 2× RP2040, 6× K155ID1, converter control; measure CYD draw |
| D6 | USB power paths: VBUS isolation/selection for ESP32 USB and standalone RP2040 debug | Open | Inspect actual CYD and RP2040-Zero schematics. **Reversed vs. the divider:** there the CYD's 5V pin powered the board from USB; here the board's buck feeds that pin while CH340 USB may also be plugged in. Determine whether the CYD has any diode between VBUS and its 5V header before connecting both |
| D7 | HV enable default and defined tube state while the RP2040 is in reset/BOOTSEL | Open | Hardware pull-downs so reset = HV off / guides idle |
| D8 | Guide driver circuit and its input current at 3.3 V | Open | Reference drive is ~5 V logic |
| D9 | Index sense: threshold, level translation to 3.3 V, protection | Open | One sensed reference cathode in Rev A |
| D10 | A101 socket pinout, verified against the tube drawing | Open | Reference page has inconsistent index-cathode pin text |
| D11 | Sectional test provisions: removable links, test points, dummy-load landing | Open | HV converter must be isolatable from the tube section |
| D12 | Discharge path and target discharge time | Open | Measure in 1D |
| D13 | Clearance/creepage rules for ~450 V, component voltage ratings | Open | Becomes the board's DRC rules |
| D14 | Connectors: 12 V in, 5 V out, I2C, programming access | Open | Keyed, pinout by signal name |

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
