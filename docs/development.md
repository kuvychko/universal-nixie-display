# Development

Toolchains, workflow and generated-file policy. Commands run from the repository root.

## Toolchains

| Area | Tool | Notes |
|---|---|---|
| Schematics/PCB | KiCad 10 | One project per board under `hardware/<module>/`; shared library in `hardware/lib/` |
| Simulation | ngspice-45 (shipped with Qucs-S in `C:/Simulators/Qucs-S/bin`); KiCad 10's built-in ngspice for schematic-level checks | Benches and summarised results in `hardware/dekatron/simulation/` |
| ESP32 firmware | PlatformIO, Arduino framework | `firmware/display/`; pin platform and library versions |
| RP2040 firmware | _open_ (PlatformIO arduino-pico or Pico SDK) | `firmware/dekatron/`, `firmware/nixie/` |
| Tools/tests | Python via `uv` | `tools/`, `tests/` |
| Enclosure | SOLIDWORKS | Commit source plus STEP and 3MF exports |

## KiCad

ERC and DRC from the command line (once the project exists):

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/dekatron/dekatron.kicad_sch
kicad-cli pcb drc --severity-error --severity-warning hardware/dekatron/dekatron.kicad_pcb
```

Record the ERC/DRC baseline here and check that each change does not add to it.

### Generator

`tools/gen_schematics.py` writes the dekatron schematics, the project symbol library and a BOM
(`hardware/dekatron/bom_power.csv`) from the values in `docs/hardware.md`. Every pin ends in a short
stub with a net label, power symbol or no-connect flag, so connectivity is exactly the generator's
net lists. Inter-sheet nets are global labels. It writes `dekatron.kicad_pro` only if it does not
exist (KiCad owns it afterwards; it carries the D13 net classes). Re-run after editing the script:

```
python tools/gen_schematics.py
```

### ERC baseline (power sheet only, 2026-10-06)

`kicad-cli sch erc --severity-all hardware/dekatron/dekatron.kicad_sch`: **9 violations, all
expected:**

* 7 × `isolated_pin_label`: global labels whose other ends are on sheets not yet drawn (`HV_EN`,
  `OVP_TRIP`, `5V_DISP`, `5V_MCU`, `5V_NIX` to mcu; `HV`, `V_B_BIAS` to tube).
* 1 × `power_pin_not_driven`: `+3V3` on the PGOOD pull-up, supplied by the RP2040-Zero (mcu sheet).
* 1 × `pin_to_pin` power output to power output: the LP2951 output drives the LM5156 VCC pin in
  BIAS = VCC mode (intentional, D2).

## Simulation

Benches are plain ngspice netlists (`.cir`) in `hardware/dekatron/simulation/`, so they run in
batch without a GUI and diff cleanly; Qucs-S is used for interactive exploration. Run a bench:

```
"C:/Simulators/Qucs-S/bin/ngspice_con.exe" -b hardware/dekatron/simulation/<bench>.cir
```

Each bench states its model sources and limitations in its header. Commit summarised results
(tables, plots) rather than `.raw` data. A simplified tube model can support circuit analysis but
cannot establish glow transfer, ignition or homing (plan §9).

## Generated-file policy

* `.gitattributes` pins text files to LF, matching KiCad. Released fab files under
  `hardware/<module>/fab/` are byte-exact (`-text`) and are the only Gerbers committed.
* If generator scripts are used, they preserve hand-edited design intent and never overwrite the
  `.kicad_pro` file KiCad owns.
* Vendor datasheets live in `docs/datasheets/`, which is git-ignored; cite them in
  [references.md](references.md).
* Pin firmware dependency versions; record the board revision each build targets.
