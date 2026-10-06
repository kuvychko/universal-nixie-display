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

## Benches

| Bench | Purpose | Status |
|---|---|---|
| `lm5156_smoke.cir` | Model runs in ngspice and regulates a 12 V → 150 V boost; illustrative values | **Passes** (2026-10-06) |

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
