# Enclosure and printed parts

## Organisation

* **One folder per assembly.** `dekatron-bench-test/` is the bench fixture below. The Phase 4
  display enclosure ([project plan](../docs/project_plan.md): tube deck, shell, cradle, tilt
  base) will get its own folders.
* **Each part comes in three files with one base name:** `.SLDPRT` (SOLIDWORKS source), `.STEP`
  (for other CAD) and `.3MF` (print-ready). This follows nanovolt-divider.
* **Names are `<part>-v<N>`.** Bump N when a part changes in a way that matters for fit or
  printing, and replace the old files. Git history keeps the old versions.
* **Each assembly's table** lists its parts, quantities, hardware, any print-setting exceptions
  and the status (designed, printed, fitted).

Default print settings unless a table says otherwise: PLA, 0.4 mm nozzle, 0.20 mm QUALITY
profile, 15 % gyroid infill.

Printed plastic is not HV insulation. Clearances live on the boards and in rated wire; a printed
part only keeps fingers away (plan §4).

## `dekatron-bench-test/`: A101 bench test fixture

A clamshell around the 30 × 70 mm perf board of the
[optional A101 bench test](../docs/bringup.md#optional-a101-bench-test). The parts to hold the
A101 socket and shroud the tube come next.

| Part | Files | Qty | Status |
|---|---|---|---|
| Clamshell base | `clamshell-base-v0` | 1 | Printed and fitted (2026-10-10) |
| Clamshell top | `clamshell-top-v0` | 1 | Printed and fitted (2026-10-10) |
| A101 socket holder | — | 1 | Being designed |
| Tube shroud | — | 1 | Being designed |

Hardware: 2 × M2 × 6 mm machine screws and 2 × M2 × 4 × 3.2 mm knurled brass threaded inserts.
