# Bring-up

Section-by-section procedures and acceptance results. Raw measurements go in
`characterization/<module>/` as dated files; this document records the procedure and the verdict.

## Dekatron controller/PSU (Phase 1D)

One PCB, brought up in order. Keep MCU outputs in defined states during power tests. Any external
bench-HV connection must not back-feed the onboard converter. Use rated probes for HV.

| Step | Section | Acceptance | Result |
|---|---|---|---|
| 0 | Socket harness, unpowered, tube inserted | Continuity from each board signal to the intended socket pin, per [hardware.md A101 pinout](hardware.md#a101-pinout): anode 8, index K1 13, G1 5, G2 10, the nine RTN cathodes. Socket pin numbering is easy to mirror (top vs. underside view) | — |
| 1 | 12 V input, 5 V and 3.3 V rails | Rails in tolerance, no back-feed from USB | — |
| 2 | HV converter on rated dummy loads, tube section isolated by links | Output, ripple, startup overshoot, load response, temperature, input power, discharge time recorded within limits defined in 1B | — |
| 3 | Bias/guide drive and index sensing | Guide waveforms and index signal at 3.3 V as designed | — |
| 4 | Firmware motion | Homes, steps both ways, holds positions, reports faults | — |
| 5 | Homing characterization | All 10 positions × both directions; ≥1000 home/reposition trials; latency distribution; timeout fault exercised; warm, supply-cycling and USB-attach cases | — |

## Nixie subsystem (Phase 2)

Purchased PSU at no load and ~15-20 mA, plus startup/blanking load steps: voltage,
ripple/overshoot, audible noise, temperature. Then all digits and decimal points, default-dark
startup, full-load stability.
