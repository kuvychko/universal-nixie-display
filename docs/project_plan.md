# Universal Nixie and Dekatron Display — Project Plan

Revision 0.3 · 2026-10-05 · Planning baseline, not a released electrical design

## 1. Purpose and scope

Build a programmable desktop display with six IN-14 Nixies, one A101 dekatron, a 2.8-inch ESP32 touchscreen module, and a front-panel rotary encoder. It should be enjoyable as a standalone object and useful as an output device for a computer, Raspberry Pi, or experiment. The enclosure is matte PLA, fabricated as replaceable printed parts, with a separate tilt base.

Use the existing nanovolt-divider project as the structural and software reference. Prioritize independently working modules and quick physical iteration. The first deliverable is one complete, independently testable dekatron controller/PSU board. Develop it in three stages: (1) design for 12 VDC input, (2) create and simulate the complete schematics, and (3) create the PCB. Power conversion, tube drive, index sensing and RP2040 interfaces belong to this same board. Bring up its sections sequentially on the finished PCB; no separate converter prototype PCB is planned.

Terminology: interpret “12DAC” as 12 VDC. “CYS” refers here to the user's existing 2.8-inch ESP32 display board (the divider repository calls it a Cheap Yellow Display/CYD). Confirm exact board revision and pinout rather than relying on this nickname. Assume the available controller modules are RP2040-Zero boards; confirm before footprint selection.

## 2. Agreed baseline

- Six IN-14 tubes in one equally spaced row above the enclosure; two spare tubes retained.
- One A101 mounted horizontally at the right, its end facing the viewer; an existing socket is available.
- Landscape TFT on the front left, rotary encoder with push action on the right.
- External isolated 12 VDC adapter powers the instrument. USB-C provides the host data/programming connection; USB-only operation need not power the tubes.
- Main application, touchscreen, encoder behavior, presets, and host protocol live on the ESP32 display board.
- Three additional board assemblies: Nixie controller/mounting board, dekatron controller/PSU board, and purchased Nixie HV module. The display board is a fourth physical board; RP2040-Zero modules are daughterboards on the controllers if used.
- Internal I2C at 3.3 V logic, with the ESP32 as master and distinct controller addresses.
- Rev A retains the purchased Nixie supply. A shared custom converter is outside initial scope.
- One sensed reference cathode for the dekatron. Homing between irregular animation cycles restores the position estimate.

## 3. Module responsibilities

| Assembly | Responsibilities | Independent operation |
|---|---|---|
| ESP32 display board | UI, encoder, presets, time source, SCPI-style host interface, coordinated display frames | UI and protocol work against simulated controller status |
| Dekatron controller/PSU | 12 V input, local low-voltage conversion, HV conversion and bias, guide drivers, index sensing, local timing | RP2040 USB console and built-in diagnostics with no ESP32 or Nixies connected |
| Nixie controller/mount | Six tubes, six K155ID1 drivers, current limiting, decimal-point switches, blanking, digital control | Local diagnostic sequence or USB console with purchased HV module |
| Purchased Nixie PSU | 12 V to approximately 170–180 V | Dummy-load characterization before integration |

Recommended initial controller arrangement: one RP2040-Zero per custom controller board. The Nixie board may use shift registers or expanders behind its MCU to obtain enough outputs. Six statically driven BCD decoders alone require 24 signals; do not assume all required signals fit directly on a Zero module. Static tube drive is the initial preference; multiplexing is not required.

The local MCUs are peripheral controllers, not competing application brains. They own time-sensitive sequences and hardware state; the ESP32 owns what the instrument should display.

## 4. Power architecture and electrical decisions

Distribute 12 V to the purchased Nixie PSU and custom dekatron board. Provision a suitably sized 5 V buck on the dekatron/power board for the display and logic, with an optional output connector so the module still runs independently. Select capacity after totaling ESP32/TFT, RP2040, K155ID1, and converter loads. Use local regulation/decoupling as required by each module.

The integrated dekatron board accepts 12 VDC and includes an approximately 450 V supply, subject to the requirements of the complete tube-drive circuit. Choose its topology explicitly: a direct boost, boost plus multiplier, or flyback are candidates rather than settled decisions. The reference AD01A uses a 5 V input and approximately 140 V boost stage followed by a tripler; its circuit cannot be fed unchanged from 12 V. A 12-to-5 V stage followed by the reference architecture remains a comparison option. Final setpoint and bias-network values must be reconciled with the selected tube-drive circuit before integration. The earlier 420 V reference output is not interchangeable with 450 V without review.

Keep the A101 bias, guide drive, and sensing topology together. Translate its original approximately 5 V index output to 3.3 V and check guide-driver input current at 3.3 V. Verify the socket pinout against the tube drawing: the reference webpage contains inconsistent textual pin numbers for the index cathode.

Before PCB layout, resolve:

- 12 V input protection, current budget, power switch, HV enable defaults, and rail test points.
- USB VBUS isolation or power selection for both normal ESP32 use and standalone RP2040 debugging. Prevent parallel USB/external supplies from feeding one another; inspect the actual boards' schematics. USB-C denotes a connector, not an assumption of USB-PD or native USB support.
- 5 V K155ID1 supply and verified logic compatibility; decimal points require separate HV switching channels. Evaluate global or per-tube anode blanking rather than assuming all out-of-range BCD codes safely blank every driver.
- Default-dark Nixie startup and a defined dekatron startup state while MCUs reset or are being flashed.
- Rated resistors/capacitors/connectors, adequate PCB spacing, inaccessible HV nodes, and discharge paths. Record measured discharge time; printed plastic is not a substitute for PCB clearances.
- Probe ratings for HV measurements and ground-referenced test connections.

Keep HV wiring physically separate from I2C and the TFT harness. Provide strain relief. No mains wiring is planned inside the enclosure.

## 5. Dekatron behavior and homing

Provide HOME, MOVE_RELATIVE, MOVE_TO, ROTATE, STOP, and STATUS operations. Home by stepping toward the reference, checking the index only at an appropriate settled phase, and confirming it before setting the position counter. A timeout must return a fault, never a fabricated position.

Initial design target: 200 complete main-cathode steps/s during homing, with roughly 50 ms for a ten-step sweep. Aim for home plus reposition in under 100 ms for an already-lit tube. These are calculated targets pending bench validation, not guaranteed timings. Treat cold-start ignition separately.

Track position_valid, homing/busy state, expected versus observed index crossings, and homing failures. Re-home after rail interruption, controller reset, or detected position inconsistency. Periodic homing can be part of an animation boundary. Single-index tracking does not guarantee detection of every missed step between index visits.

Support ten main-cathode positions first. Guide-position effects can be added later. Provide accessible cathode links/test locations if easy, but do not populate ten sensing channels in Rev A.

## 6. Interfaces and software

### Internal I2C

Use one documented, versioned command/status contract per controller. Start at 100 kHz on short internal wiring, with one deliberate pull-up arrangement to 3.3 V. Define connector pinouts by signal name, keyed orientation, ground, and voltage. Keep HV off these connectors.

Commands should be brief and nonblocking: HOME starts work and returns; status polling reports completion. Use bounded buffers, explicit payload lengths, valid ranges, a protocol version, module identity, and error/status codes. Long tube sequences must not execute inside I2C interrupt callbacks.

Stage complete Nixie frames and apply them together to avoid partly updated numbers. A frame contains six digit/blank values and decimal-point state, with brightness controls only after the chosen hardware supports them. Include status for pending/active frame and faults. Addresses and byte layouts are assigned in the interface document before independent firmware development.

### External host interface

Use a small SCPI-style ASCII command set over the display board's USB serial connection, following the divider's approach. A full SCPI implementation or USBTMC is unnecessary for Rev A. The command spellings below are proposals:

| Command | Intent |
|---|---|
| `*IDN?` | Instrument identity and firmware version |
| `SYST:ERR?` | Retrieve queued error |
| `DISP:MODE PRESET` / `DISP:MODE REMOTE` | Explicit ownership of the display |
| `DISP:VALUE 12.3456` | Format a numeric value into available digits |
| `DISP:TEXT "FREQUENCY"` | TFT label |
| `DISP:UNIT "Hz"` | TFT units |
| `NIX:RAW "012345"` | Exact digits, including leading zeroes |
| `DEK:HOME` / `DEK:HOME?` | Request homing / query status |
| `DEK:POS 4` | Move to a main-cathode position |
| `DEK:ROT 2` | Rotate at a specified rate; units fixed by protocol |

Specify framing, terminators, timeouts, formatting, and host-open/reset behavior in docs/host_interface.md. Put signs and engineering units on the TFT unless separate sign hardware is added; IN-14 digits do not provide a minus sign. Never silently wrap overflow. Mark stale remote data on the TFT; choose and document hold/blank behavior. Local actions and host writes must follow a clear ownership rule.

Reuse the divider's serial parser and UI patterns after reviewing their assumptions and licensing. Application logic should produce the same display frame whether input comes from a preset, touch, encoder, or host command.

## 7. Initial modes

Rev A needs a small useful set, not an application platform:

1. Clock, once the time source is available; show an unset-time state before synchronization.
2. Timer/stopwatch controlled by touch and encoder.
3. Demonstration/self-test: digits, decimal points, rotation, pendulum, and homing.
4. Universal remote numeric display with label, units, and optional small history plot.

Mathematical sequences, mains-frequency observatory, Geiger-event display, and solver progress are later presets or host examples. Measurements originate in external instruments; this device initially displays data rather than measuring HV, frequency, or radiation itself.

## 8. Repository structure

The inspected nanovolt-divider repository separates docs/, hardware/, firmware/, enclosure/, tools/, and calibration/. Preserve that organization, split hardware and firmware by module, and use characterization/ for engineering evidence rather than imply metrology calibration is required.

| Path | Contents |
|---|---|
| README.md | Purpose, status, architecture, build order, photographs |
| docs/project_plan.md | This baseline |
| docs/architecture.md | Power distribution, board boundaries, ownership |
| docs/hardware.md | Electrical design and harness tables |
| docs/i2c_protocol.md | Versioned controller contracts |
| docs/host_interface.md | USB serial/SCPI contract and examples |
| docs/bringup.md | Independent module procedures and acceptance results |
| docs/development.md | Build/flash, KiCad workflow, generated-file policy |
| docs/references.md | Datasheets, source schematics, attribution and reuse terms |
| hardware/dekatron/ | One complete KiCad controller/PSU project, hierarchical sheets, BOM and fab outputs |
| hardware/dekatron/simulation/ | Supply and drive/sense models, test benches and simulation results |
| hardware/nixie/ | Separate KiCad project, BOM, fab outputs |
| hardware/power/ | Purchased PSU specification and system power harness |
| hardware/lib/ | Shared project symbols and footprints |
| firmware/display/ | ESP32 main application, PlatformIO project |
| firmware/dekatron/ | RP2040 controller and standalone diagnostics |
| firmware/nixie/ | Nixie controller firmware, if local MCU retained |
| firmware/common/ | Shared protocol definitions only where useful |
| enclosure/ | SOLIDWORKS source, STEP, 3MF, tilt base and tube mounts |
| tools/ | Serial client, bring-up scripts, schematic/PCB tooling if used |
| characterization/ | Dated supply, homing, thermal, and reliability measurements |
| tests/ | Host protocol/formatting tests and useful hardware test scripts |

The divider's current pins.h identifies ESP32-2432S028R, with I2C SDA on GPIO27 and SCL on GPIO18. GPIO18 is also microSD SCK, requiring arbitration in that project. Reuse this mapping only after checking the new module; omit microSD in Rev A unless there is a concrete need. Budget encoder pins early. If convenient GPIOs are unavailable, a local controller may capture/debounce encoder movement and expose a cumulative count plus button events over I2C; the ESP32 still owns their UI meaning. This avoids losing detents through slow raw-pin polling.

The divider's host-interface documentation also records CH340 serial reset-on-open behavior. Reuse its host handling as a starting point, then verify on the actual new board and target host. Keep boot counters/uptime so the host can detect reboots and restore the desired display.

Pin firmware dependencies and record the actual board revisions. Preserve hand-edited design intent if generators are used. Verify third-party design reuse terms before copying published circuit artwork or code; public access does not itself grant a license. No repository is created or modified by this planning document.

## 9. Phased execution and acceptance gates

| Phase | Deliverable | Exit criterion |
|---|---|---|
| 1A — Design for 12 VDC | Complete module architecture and power budget: converter, bias/guide drive, index sensing, RP2040 and interfaces | Voltage/current requirements, logic levels, USB power paths, socket pinout and sectional test provisions defined |
| 1B — Create and simulate schematics | Complete hierarchical schematics and simulation evidence | Supply startup/load/device stresses and drive/sense behavior reviewed; ERC issues resolved or documented; model limitations explicit |
| 1C — Create PCB | One complete dekatron controller/PSU PCB, BOM and manufacturing files | Layout/DRC reviewed; test points, removable links, discharge paths and programming access present |
| 1D — Assemble and bring up | Same PCB tested section by section, then standalone controller firmware | Works from 12 V; supply, guide drive and index sensing verified; homes, steps both ways, holds positions and reports faults |
| 2 — Nixie subsystem | Purchased PSU qualification and six-tube controller/mount | All digits and selected decimal points work; blanking/startup correct; stable full-load operation |
| 3 — Display integration | ESP32 UI, encoder, I2C master, USB host commands | Either module can be absent without hanging UI; presets and remote mode work; errors/stale data visible |
| 4 — Enclosure | Printed tube deck, shell, cradle, service access, tilt base | Comfortable view/control access; protected HV and tube leads; strain relief; acceptable thermal behavior |
| 5 — Rev A release | Build docs, BOMs, manufacturing exports, firmware, host examples | Reproducible build and documented known limitations |

During schematic work, budget converter output current for the tube, bias network and bleeder together. Simulate no-load/full-load behavior, startup, load changes and component stresses, plus guide-driver and index-interface behavior. A simplified tube model can assist circuit analysis but cannot establish reliable glow transfer, ignition or homing. Define electrical acceptance limits before PCB release; approximately 450 V is a nominal target rather than a precision-metrology requirement.

During Phase 1D, validate low-voltage rails first, then isolate the tube section using the designed links and test the HV converter with rated resistor dummy loads. Record output, ripple, startup overshoot, load response, temperature, input power and discharge time. Next connect and verify the bias/guide and sensing sections, then exercise firmware-controlled motion. Keep MCU outputs in defined states during power tests. These are bring-up steps on one PCB, not separate board projects. Any external bench-HV test connection must prevent backfeeding the onboard converter.

Characterize homing from all ten main-cathode positions and both directions. Log at least 1,000 repeated home/reposition trials at the selected operating point, and measure latency distribution and failures. A clean result is practical evidence, not proof of zero error. Exercise deliberate index-timeout faults, warm operation, supply cycling, and USB attachment. Establish pulse timing margins before faster effects.

For Phase 2, test the purchased supply at no load and approximately 15–20 mA, plus startup/blanking load changes. Record voltage, ripple/overshoot with rated probes, audible noise, and temperature. Keep individual tube current within its chosen documented operating conditions.

For the integrated prototype, exercise simultaneous Nixie changes, dekatron motion, TFT activity, and Wi-Fi if enabled. Measure actual enclosure hot spots before accepting PLA placement near converters and resistors. No precision-voltage stability requirement is imposed beyond reliable display operation.

## 10. Immediate next work

1. **Design for 12 VDC input.** Define the complete module architecture and power budget, including HV conversion, logic power, cathode/guide bias, guide drivers, index sensing, RP2040-Zero and USB/I2C interfaces. Confirm the actual module and socket dimensions/pinout. Adapt the demonstrated reference circuit deliberately for the input supply and 3.3 V logic.
2. **Create and simulate the schematics.** Use hierarchical sheets for power conversion, tube drive/sensing and MCU/interfaces. Select components; simulate startup, load changes, device stresses and interface behavior, including tolerances and rating margins. Record model limitations. Resolve schematic/ERC issues and define sectional hardware tests before layout.
3. **Create the PCB.** Lay out one complete controller/PSU board with test points and removable links for independent sectional checks. Review spacing, return paths, heat sources, tube mounting, programming access and fabrication outputs.
4. **Build and bring up the same board.** Test low-voltage power, HV with dummy loads, tube drive/index sensing and firmware in that order. Record results in characterization/dekatron/. Proceed to full-system UI and Nixie work after the standalone module works.

## References

- Existing project and inspected repository layout: https://github.com/kuvychko/nanovolt-divider
- Reference A101 power/drive/index design: https://threeneurons.wordpress.com/arduino/dekatron-shield-kit/
- A101 data and original drawing links: https://www.tube-tester.com/sites/nixie/datdekat/A101/A101.htm
- IN-14 data: https://www.tube-tester.com/sites/nixie/data/in-14/in-14.htm
- Selected Nixie HV module listing (qualify delivered version): https://www.amazon.com/dp/B09D94N3MX

Sources establish starting points. Component values, pin mappings, operating margins, and PCB safety details require schematic review before fabrication.