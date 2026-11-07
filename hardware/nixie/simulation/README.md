# Nixie board simulation

ngspice benches for the Nixie controller/mount board (Phase 1B). Same workflow as the dekatron
benches ([../../dekatron/simulation/README.md](../../dekatron/simulation/README.md)). Run from this
directory so ngspice picks up `.spiceinit`:

```
"C:/Simulators/Qucs-S/bin/ngspice_con.exe" -b nix12_switch.cir > nix12_switch.log
```

| Bench | Purpose | Result |
|---|---|---|
| `nix12_switch.cir` | Q101 high-side switch into the purchased HV module (measured 470 µF input, 7.2 W start-up plateau) with the 12 V rail live: rail dip, PTC current, Q101 power and energy at turn-on and turn-off. Case A: C102 gate-source only (1 µF, 3.3 µF); case B: gate-drain Miller capacitor (100 nF, 150 nF) plus 3.3 µF gate-source. Q101 threshold swept −2.0 / −2.5 / −3.0 V | **Chosen: A, 3.3 µF** (47k / 47k): ramp 5.5-7.3 ms, PTC peak 1.6-1.9 A, rail ≥ 11.63 V, Q101 ≤ 6.4 W and 35-38 mJ. Full table and reasoning: [docs/hardware.md](../../../docs/hardware.md), Nixie HV module 12 V switch |

The module's start threshold is not measured: the bench uses 8 V and holds the 7.2 W start-up
draw for the whole run (worst case). Below 8 V the modelled module draws nothing, so after
turn-off its capacitor stays near 8 V; the real module's idle draw would discharge it.
