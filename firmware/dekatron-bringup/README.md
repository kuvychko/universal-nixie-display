# Dekatron bring-up firmware

Gate 2 tool for the dekatron controller/PSU ([assembly checklist](../../hardware/dekatron/assembly.md)):
switches `HV_EN` (GP6) on purpose and reports the HV converter's state. It is **not** the dekatron
firmware (that goes in `firmware/dekatron/`; its toolchain is still open, see
[development.md](../../docs/development.md)).

> [!WARNING]
> High voltage (~450-545 V). Read the [README safety section](../../README.md#safety-read-this-first).
> The JP101 shunt is the hardware inhibit; this firmware never replaces it.

## Safety behaviour

* HV_EN is driven low first thing at boot; HV never comes on without an `on` command.
* `on` is refused unless VIN_SENSE reads 10.8-13.2 V (12 V ±10 %) and no fault is latched.
* Every `on` has an auto-off timeout: 10 s by default, 300 s at most.
* While on: VIN leaving the window, or the EN/UVLO node read low on GP8 (`OVP_TRIP`), turns HV off
  and **latches** a fault until `clear`. EN low means an OVP comparator tripped, or the JP101 shunt
  is fitted: with the shunt fitted, `on` latches `en_low` after 2 ms, which confirms the inhibit.
* The hardware watchdog (500 ms) resets the RP2040 if the loop hangs; GP6's reset pull-down then
  holds HV off.
* GP8 has no pull-down (it would load EN/UVLO). The module LED glows dim red while HV_EN is high.

HV_SENSE and VIN_SENSE readings use the 3.3 V rail as ADC reference: indicative only, the meter
and HV probe are the reference. HV_SENSE sees HV_STACK only, not V_B.

## Build and flash

```
pio run -d firmware/dekatron-bringup
```

Hold BOOT on the RP2040-Zero while plugging USB, then
`pio run -d firmware/dekatron-bringup -t upload` (or copy `.pio/build/rp2040zero/firmware.uf2` to
the RPI-RP2 drive).

## Commands

USB serial, 115200, one line per command; replies start with `OK` or `ERR`, faults with `FAULT`.

| Command | Does |
|---|---|
| `on [s]` | HV_EN high for s seconds (default 10, max 300) |
| `off` (or an empty line) | HV_EN low |
| `status` | `t_ms vin hv peak pgood en_node hv_en fault left`; `peak` is the highest HV sampled since the last `on` |
| `clear` | Clear a latched fault and the peak |
| `log <s> [hz]` | CSV `t_ms,vin,hv,pgood,en_node,hv_en` for s seconds (default 10 Hz, max 100), then `END` |
| `help` | List the commands |

From the PC, [`tools/hv_bringup.py`](../../tools/hv_bringup.py) wraps each command in one call
(`uv run --group bench python tools/hv_bringup.py status`) and adds `discharge`: HV off, then
HV_STACK every 0.5 s until it is below 50 V, with the elapsed time.
