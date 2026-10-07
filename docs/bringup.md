# Bring-up

Section-by-section procedures and acceptance results. Raw measurements go in
`characterization/<module>/` as dated files; this document records the procedure and the verdict.

## Dekatron controller/PSU (Phase 1D)

One PCB, brought up in order. Keep MCU outputs in defined states during power tests. Any external
bench-HV connection must not back-feed the onboard converter. Use rated probes for HV.

| Step | Section | Acceptance | Result |
|---|---|---|---|
| −1 | Before ordering boards | Print the PCB 1:1 and lay a real RP2040-Zero on the U301 footprint: castellations centred on their pads, USB toward the board edge | — |
| 0 | All harnesses, unpowered, tube removed | Continuity from each board pad to its far end per [hardware.md Harness landings](hardware.md#harness-landings-d14); for `TUBE`, to the socket pins per [A101 pinout](hardware.md#a101-pinout): anode 8, index K1 13, G1 5, G2 10, the nine RTN cathodes. Socket numbering is easy to mirror (top vs. underside view). No pad-to-pad shorts, especially anode to anything | — |
| 1 | 12 V input, 5 V and 3.3 V rails | Rails in tolerance, no back-feed from USB | — |
| 2 | HV converter with the tripler connected, link LK4 open, HV dummy load (6 × 150k) fitted. **Never power the boost with LK3 open** (feedback and OVP sense HV) | Output, ripple, startup overshoot, load response, temperature, input power, discharge time recorded within limits defined in 1B; power-up inductor current; OVP trips (lift the feedback string's top resistor with HV inhibited, then release) | — |
| 3 | Bias/guide drive and index sensing | Guide waveforms and index signal at 3.3 V as designed | — |
| 4 | Firmware motion | Homes, steps both ways, holds positions, reports faults | — |
| 5 | Homing characterization | All 10 positions × both directions; ≥1000 home/reposition trials; latency distribution; timeout fault exercised; warm, supply-cycling and USB-attach cases | — |

## Nixie subsystem (Phase 2)

Purchased PSU at no load and ~15-20 mA, plus startup/blanking load steps: voltage,
ripple/overshoot, audible noise, temperature. Then all digits and decimal points, default-dark
startup, full-load stability.
