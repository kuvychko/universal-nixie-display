# Dekatron board simulation

ngspice benches for the dekatron controller/PSU (Phase 1B). Workflow and tool versions:
[docs/development.md](../../../docs/development.md#simulation).

## Running

Run from this directory, so ngspice picks up `.spiceinit` (PSpice compatibility for vendor models):

```
python prepare_models.py                                   # once, after fetching vendor models
"C:/Simulators/Qucs-S/bin/ngspice_con.exe" -b <bench>.cir
```

## Vendor models

Vendor models are copyrighted with no redistribution grant, so `models/vendor/` is git-ignored.
To reproduce, download and unzip them into the paths below, then run `prepare_models.py`, which
writes ngspice-compatible copies (`*.ngspice.lib`) without editing the originals.

| Path | Model | Source |
|---|---|---|
| `models/vendor/ti/snvmbv9h.zip` → `LM5156-Q1_PSPICE_TRANS/` | Unencrypted LM5156-Q1 PSpice Transient Model, rev. H (model "Final 1.00", 09 Dec 2019) | https://www.ti.com/product/LM5156H |
| `models/vendor/ti/snvmc69a.zip` → `LM5156-Q1_PSPICE_AVG/` | Unencrypted LM5156x-Q1 PSpice Average Model, rev. A | https://www.ti.com/product/LM5156H |
| `models/vendor/ti/slvmbj5c.zip` → `TPS54202_PSPICE_TRANS/` | TPS54202 transient model (listed by TI as unencrypted, but the library body is Cadence-encrypted: **not usable in ngspice**) | https://www.ti.com/product/TPS54202 |

Model notes (from TI's header, plus what we found):

* Modelled: UVLO/SYNC, OVP, UVP, PGOOD, overcurrent and hiccup (`LM51561=1` selects the
  LM51561 hiccup behaviour), maximum duty cycle. **Not modelled:** temperature, dithering.
* The model is for the LM5156-Q1; the LM5156H shares the controller core but has a different
  temperature grade and package.
* ngspice rejects `.IC` cards inside its subcircuits; `prepare_models.py` comments them out.
* The DC operating point does not converge (singular matrices in the behavioural blocks), so
  transient benches start from rest with `uic`, which matches a real power-up.
* **Maximum time step ≤ 5 ns.** The model's start-up logic clocks a flip-flop with a 20 ns edge
  pulse, and the PWM path uses 22.5 ns clock pulses and 5 ns dead times. With a 50 ns step limit
  ngspice steps over the start-up pulse: `OTP_DONE` never sets, soft-start stays at 0 V and the
  controller never switches, with no error message. Use `.tran 5n <tstop> 0 5n uic`.
* Run benches with output to a file (`> bench.log`), not through a pipe: piped output appears only
  at the end and makes a slow run look hung.
* **Relaxed tolerances** (`.options reltol=0.003 abstol=1n vntol=10u chgtol=1e-13 itl4=50`) are
  needed once the tripler is present: with defaults the solver stalls at light-load mode changes
  (pulse skipping resuming), reported at nodes inside the model's driver.
* **Initial conditions:** set node voltages with `.ic` *and* run with `uic`. Without `uic` the
  operating point fails and its fallback discards the `.ic` values; per-capacitor `IC=` is not
  honoured around a series stack; and the internal node of a C + ESR subcircuit needs its own
  `.ic` (e.g. `v(xcp1.m)`), or every capacitor starts discharged.
* **Tube model:** behavioural (`BLATCH`/`BTUBE`). Hard-edged elements (a hysteretic `SW`, a
  conditional latch) stall the solver. Strike is judged on V(hv, rtn), the dark-tube anode
  voltage; judging it on the anode itself is circular and lets a small pre-strike current hold
  the anode just below the strike voltage. The 380 V strike voltage is an assumption.
* **Pump surge and parasitics:** without ESR on the tripler capacitors the switch / pump-capacitor
  / diode loop has no impedance and the solver fails; ESL is omitted because nH parasitics ring
  faster than a 5 ns step resolves.

## Benches

| Bench | Purpose | Status |
|---|---|---|
| `lm5156_smoke.cir` | Model runs in ngspice and regulates a 12 V → 150 V boost; illustrative values | **Passes** (2026-10-06) |
| `hv_warm.cir` | Draft power sheet, steady state with HV feedback; stack precharged so regulation arrives in ~1 ms | **Passes**; results in [hardware.md](../../../docs/hardware.md#simulation-results) |
| `hv_discharge.cir` | Passive discharge from 450 V (no controller; seconds to run); three cases via `alterparam`: both HV dividers, feedback divider open, monitor / OVP divider open (no dedicated bleeder since the 0207 rework) | **Passes**: HV < 50 V in 1.10 s, 2.03 s and 2.03 s (target 10 s; 2.7M divider tops, 2026-10-07; 4.7M tops: 1.94 / 3.93 / 3.47 s) |
| `fault_fbopen.cir` | Feedback divider open: FB at 0 V, converter at its current limit; shared monitor / OVP divider with C304 on the `HV_SENSE` tap (long run) | Ramp from 450 V (8 ms, `fault_fbopen_*_ramp.log`): ~7 V/ms, HV 506 V at 8 ms; tap lag 15.8 V of HV with 100 nF on `HV_SENSE`, 1.6 V with 10 nF, **so C304 became 10 nF**. From 540 V, tube lit: HV peaks at 546.9 V (OVP tap 1.228 V vs 1.242 V); the model stops converging at 3.5 ms. **Corrected by the dark-tube bench:** that was the comparator model's soft 200 /V edge clamping EN, not the converter levelling off |
| `fault_fbopen_dark.cir` | Same fault from 540 V with the tube dark; comparator edge `KCMP` 20000 /V (near-ideal; 200 /V reproduces the soft clamp) | **Passes** (2.7M / 7.87k / 6.19k divider, trip 544.6 V): OVP trips at 545.8 V (tap lag 1.2 V), HV peak 546.0 V, then bursts at 543.5-545.4 V; V_b ≤ 185.9 V (V_b OVP 200.7 V), switch node ≤ 186.8 V. Earlier dividers: 553.4 V (4.64M / 10.5k), 550.3 V (4.7M / 10.7k). No latch: firmware must drop `HV_EN` |
| `hv_500.cir` | 500 V setting (2.7M / 5.49k feedback, 330k + 470k anode) on the current design, warm start, 12 ms; cases nom (12 V), low (10.8 V in, limit −7 %, 90 µH), dump (tube out at 8 ms) | **Passes:** HV 492.5-492.8 V (setpoint 492.8 V), tube 366 µA; inductor peak 0.33-0.34 A vs 0.43-0.46 A limit (out of current limit); peaks: HV 496.4 V, V_b 169.9 V, switch node 171 V, CS ≤ 0.10 V. Tube-out overshoot 0.5 V (first run, 499 V setting; dump case not rerun) |
| `hv_startup.cir` | Cold start from 0 V, 40 ms (long run, ~30 min: start it in the background) | **Passes** with the kit inductor (90 µH, 0.22 Ω, 147k): strike at 18.5 ms, HV 449.9 V at 40 ms; 0.775 A power-up inrush at 10 µs, before switching |
| `fault_d5open.cir` | Review fault test: top tripler diode open from the developed state, both OVP comparators modelled as smooth sinks on EN/UVLO (20 ms, long run) | **Passes** (V_b OVP 2.2M / 13.7k, trip 200.7 V; rerun 2026-10-07): V_b ≤ 198.4 V, switch node ≤ 199.3 V, PGOOD low (first run, 2.0M / 12.4k: V_b ≤ 199.3 V, trip 201.6 V) |
| `tube_section.cir` | G+/RTN regulator, guide drivers, index sense with a scheduled glow; `.param` V_b corners and an open-zener fault (seconds to run) | **Passes** (2 × 20k feed): RTN 51.1-51.4 V in all cases, 51 V zener ≥ 0.87 mA, NDX 2.89-2.90 V on K1, clamps hold at 3.43 V in the fault |
| `input_protect.cir` | 12 V hot-plug and reverse polarity; `.param` selects cable, bulk capacitor and polarity | **Passes** with the AOD4185: rail ≤ 12.5 V, inrush 52.5 A, fuse I²t 0.088 A²s; reversal blocked. Re-run for the IPD50P04P4L-11 (`Rd=0.0055 Rs=0.002`, 2 µH / 0.02 Ω lead): 52.5 A, 12.6 V, 0.089 A²s, V_GS −9.97 to +0.14 V |

`lm5156_smoke.cir` results (100 µH, 100 kHz, 0.15 Ω sense, 1 µF output, 34 kΩ load = 4.4 mA, 10 nF
soft-start; generic MOSFET and diode models):

| Measure | Result |
|---|---|
| V_b, 8.5-9 ms | 150.02 V (setpoint 150.0 V), 0.16 V p-p ripple |
| PGOOD | High |
| Start-up | 95 % of setpoint at 4.84 ms; current-limited (0.677 A peak) until 5.63 ms, about 500 consecutive cycles |
| Steady state | DCM, 0.37 A inductor peak, 100 kHz |
| Run time | Under 10 min for 9 ms at a 5 ns step (not timed precisely) |

Not meaningful here: efficiency (input and output power agree within ~2 %; idealised device
models) and the tripler, which is not in this bench.

Finding for the variant choice (D2): the LM51561H hiccups after 64 consecutive current-limited
cycles, and this start-up stays in current limit for ~500. Start-up is energy-limited (each cycle
delivers ½·L·I_pk² ≈ 23 µJ while the output and, later, the tripler capacitors charge). The LM51561H
would need a much slower soft-start or a smaller output capacitance; otherwise fit the LM5156H.
