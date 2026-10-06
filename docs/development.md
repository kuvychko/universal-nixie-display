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
