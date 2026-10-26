# Bring-up

Section-by-section procedures and acceptance results. Raw measurements go in
`characterization/<module>/` as dated files; this document records the procedure and the verdict.

## Dekatron controller/PSU (Phase 1D)

One PCB, brought up in order. Keep MCU outputs in defined states during power tests. Any external
bench-HV connection must not back-feed the onboard converter. Use rated probes for HV. The board
is populated section by section, each followed by its bring-up step, using the
[assembly and bring-up checklist](../hardware/dekatron/assembly.md).

| Step | Section | Acceptance | Result |
|---|---|---|---|
| −1 | Before ordering boards | Print the PCB 1:1 and lay a real RP2040-Zero on the U301 footprint: castellations centred on their pads, USB toward the board edge | — |
| 0 | All harnesses, unpowered, tube removed | Continuity from each board pad to its far end per [hardware.md Harness landings](hardware.md#harness-landings-d14); for `TUBE`, to the socket pins per [A101 pinout](hardware.md#a101-pinout): anode 8, index K1 13, G1 5, G2 10, and RTN to each of the nine cathodes tied at the socket (1-4, 6, 7, 9, 11, 12), none of them to K1. Socket numbering is easy to mirror (top vs. underside view). No pad-to-pad shorts, especially anode to anything | **`TUBE` harness works** (2026-10-09): the same harness passed the 0b bench test. K1 to RTN open (2026-10-24, meter, tube removed), which the bench test could not show since it tied them together |
| 0b | Optional: A101 bench test on the harness, before the board ([below](#optional-a101-bench-test)) | Strikes at ≤ 450 V; steps both ways with ~−50 to −65 V guide pulses; glow reaches K1 once per 10 steps | **Tube and harness work** (2026-10-09): strikes at 289 V (reliably at 300 V), steps both ways without missed steps at 386-400 V; see results below |
| 1 | 12 V input, 5 V and 3.3 V rails | Rails in tolerance, no back-feed from USB | **Pass** (2026-10-24, board 1): buck 4.98 V (design 4.95 V), +3V3 3.31 V, 6 mA from 12 V; HV_EN at 0 V with JP101 lifted; USB only: +5V and VIN_PROT 0.04 V. [Log](../characterization/dekatron/2026-10-24_assembly_log.md) |
| 2 | HV converter with the tripler connected, link LK4 open, HV dummy load (Yageo HHV-50 1M, off-board) soldered across TP108 and GND. **Never power the boost with LK3 open** (feedback and OVP sense HV) | Output, ripple, startup overshoot, load response, temperature, input power, discharge time recorded within limits defined in 1B; power-up inductor current; OVP trips (lift the feedback string's top resistor with HV inhibited, then release) | **Partial** (2026-10-24, board 1): regulates at 449 V (design 451.0 V), V_B 152 V, 0.45 W in at 12 V (≈ 79 %), HV_STACK below 50 V in 0.67 s with the 1M load; JP101 and firmware inhibit confirmed; OVP trips at ≈ 545-546 V (board peak 549.4 V, design 543.7 V) and the firmware latches HV off. **Deferred:** ripple, overshoot, inductor current, load response, temperature, V_B discharge. [Log](../characterization/dekatron/2026-10-24_assembly_log.md) |
| 3 | Bias/guide drive and index sensing | Guide waveforms and index signal at 3.3 V as designed | **Partial** (2026-10-25, board 1): RTN 49 V, G+ 89.3 V (40.3 V above RTN); each guide 0 V when driven; tube strikes, NDX 2.83 V with the glow on K1; steps both ways with exact index counts up to 200 steps/s (500 µs phase). With the tube lit HV first sat at ≈ 415 V, PGOOD low, COMP at its clamp: the cycles ended early at ≈ 0.29 A, below the current limit, on noise at the CS pin. Fixed on board 1 (2026-10-26) with 470 pF at U106's CS pin, 470k across R111 (199 kHz) and 1 Ω across R117 (0.18 Ω): **452.7 V, PGOOD high, COMP 1.94 V**, 0.82 W in (see [hardware.md](hardware.md#hv-boost-stage)). **Open:** guide waveforms deferred (scope); reset check of the guide driver bases. A G1-K4 leak inside the tube (96.6 kΩ, bare tube) cleared during the HV runs. [Log](../characterization/dekatron/2026-10-24_assembly_log.md) |
| 4 | Firmware motion | Homes, steps both ways, holds positions, reports faults. Power-up: note whether two cathodes glow at switch-on and that homing clears it. Strike time in a dark enclosure within 5 s. Static-glow protection (plan §5): a held position is exercised or the tube goes dark before the hold limit; idle drops HV | — |
| 5 | Homing characterization | All 10 positions × both directions; ≥1000 home/reposition trials; latency distribution; timeout fault exercised; warm, supply-cycling and USB-attach cases | — |

### Optional: A101 bench test

> [!WARNING]
> High voltage, at your own risk. Read the [README safety section](../README.md#safety-read-this-first)
> before doing this test.

Checks the tube and the soldered `TUBE` harness with a bench HV supply (0-450 V) before the board
exists. It copies the board's drive scheme: main cathodes raised to RTN ≈ 50 V, guides biased
about +40 V above them, and a guide pulled to GND for a pulse of about −50 to −65 V against the
cathodes. The guides swing about 90 V, from their bias to GND: about half to two-thirds of the
original datasheet's 135-200 V control pulse, which is a swing from the bias
([A101 operating point](hardware.md#a101-operating-point-d1)). So this test also answers early
whether the tube transfers its glow with it (plan §9).

```
 HV+ (450 V) ──R_A 680k──────────────────────────── ANODE wire (pin 8)

 HV+ ──R1 330k──┬── G+ (~93-106 V)
                │
                ├──R_G1 470k──┬── G1 wire (pin 5)  ──[S1]── GND
                ├──R_G2 470k──┼── G2 wire (pin 10) ──[S2]── GND
                │
               R2 39k
                │
                ├── RTN (~51-65 V) ─────────────── RTN wire (K0, K2-K9)
                │                       └───────── K1 wire (pin 13, index)
               R3 47k
                │
 HV− ───────────┴── GND
```

S1 and S2 are normally-open pushbuttons. K1 is tied to RTN: on the bench it is just another main
cathode, and the glow is watched by eye.

| Part | Value | Rating |
|---|---|---|
| R_A (anode) | 680k, or 2 × 330k in series | ≥ 400 V total, ≥ 0.25 W |
| R1 | 330k | Sees 320-360 V and 0.3-0.4 W at 400-450 V. Use two in series (e.g. 2 × 160k-180k): most 1/4 W leaded resistors are rated 250-350 V, so a single part (or a parallel pair) is over its voltage rating |
| R2 / R3 | 39k / 47k | 1/4 W |
| R_G1, R_G2 | 470k | 1/4 W (the board's guide pull-ups) |

Expected at 450 V, calculated from these values (the divider is deliberately not stiff, as in the
AD01 reference: the tube current lifts RTN and G+ together):

| Quantity | Unlit | Glow on a main cathode |
|---|---|---|
| RTN | 51 V | ~65 V |
| G+ | 93 V | ~106 V |
| Guide bias (G+ − RTN) | 42 V | ~41 V (datasheet +36 to +44 V) |
| Tube current | — | ~315-375 µA for V_m 130-170 V (datasheet 300-450 µA) |
| Supply current | ~1.1 mA | ~1.4 mA |

Procedure:

1. Build on a terminal strip or perfboard, not a solderless breadboard; keep the anode node clear
   of everything else. Supply current limit about 2-3 mA.
2. **Strike:** ramp the supply slowly to 450 V, no higher. The glow should settle on one cathode
   as a single spot. If it sits on a guide, press and release S1 or S2.
3. **Step:** press S1, press S2 (S1 still held), release S1, release S2: one step. Starting with
   S2 steps the other way. Go round at least once in each direction.
4. **Index:** the glow lands on K1 (pin 13) once per 10 steps. For an electrical reading instead,
   put 33k (the datasheet's index-output resistor) between K1 and RTN: a meter across it reads
   about 11-12 V with the glow on K1 and about 0 V elsewhere.
5. **Operating point:** measure RTN and G+, and the voltage across R_A (÷ 680k = tube current).
   Note the supply voltage at which the tube strikes.

If the glow does not step, a larger R3 (e.g. 68k) raises RTN and with it the pulse amplitude;
that would mean raising RTN on the board too (D8).

The user's build is on a 30 × 70 mm perf board in a printed clamshell
([enclosure/dekatron-bench-test](../enclosure/README.md#dekatron-bench-test-a101-bench-test-fixture)).

<img src="../website/assets/dekatron-bench-test.jpg" alt="The assembled A101 bench fixture: the tube in its printed socket housing and shroud, wired to the white clamshell holding the perf board, with two pushbuttons on top and the HV leads" height="300">

Safety: the anode wire and R_A are at up to 450 V, and every other wire sits at 50-106 V; none is
ground. Switch off and let the supply's output discharge before touching anything; press the
buttons by their insulated caps, one hand only.

Results (2026-10-09, user's bench supply; stepping first at 386 V, measurements at 400 V; voltages
measured from GND). Parts used, all 1/4 W: R_A 2 × 330k in series, R1 2 × 680k in parallel
(340k), R2 33k + 5.1k in series (38.1k), R3 47k. R1's two parts each saw about 320 V, above the
usual 1/4 W rating; see the parts table.

| Quantity | Measured |
|---|---|
| Strike voltage (supply) | **289 V**; strikes reliably at 300 V. Before striking no current flows, so the anode sits at the supply and RTN at the divider's ≈ 33 V (calculated): ≈ 256 V across the tube |
| RTN, glow on a main cathode, 400 V supply | **63 V** (calculated 56 V with the parts used; G+ not measured) |
| Anode (tube pin 8), 400 V supply | **210 V** |
| Maintaining voltage (anode − RTN) | **147 V** (datasheet 130-170 V) |
| Tube current, (400 − 210 V) / R_A | **288 µA** (R_A = 2 × 330k); datasheet 300-450 µA |
| Guide pulse (guide at GND − RTN) | **≈ −63 V** against the cathodes |
| Stepping | **Reliable in both directions, no missed steps seen by eye** (manual stepping is fiddly; no step count or index check recorded). S1 → S2 → release S1 → release S2 moves the glow one cathode; starting with S2 steps the other way. One button alone moves the glow onto that guide, and on release it returns to the cathode it came from, as expected for a two-guide tube |
| Glow on K1 once per 10 steps | **Not recorded** (step 4): the bench test is partially complete |

**So the tube strikes far below the board's supply and steps reliably, by eye, with the guides
swinging about 91 V (calculated) to about −63 V against the cathodes: about half to two-thirds of
the original datasheet's 135-200 V control pulse swing, at a tube current just below the datasheet
minimum.**
The board runs at 450 V with RTN ≈ 50 V: more current (≈ 315-445 µA) and a pulse of about −50 V.
The pulse is the one figure with less margin than on the bench; bring-up step 3 checks stepping
on the board itself, and raising RTN (D8) deepens it if needed.

## Nixie subsystem (Phase 2)

Purchased PSU at no load and ~15-20 mA, plus startup/blanking load steps: voltage,
ripple/overshoot, audible noise, temperature. Then all digits and decimal points, default-dark
startup, full-load stability.
