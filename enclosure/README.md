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

Default print settings unless a table says otherwise: PLA on the Prusa, 0.4 mm nozzle, 0.20 mm
QUALITY profile, 15 % gyroid infill.

Printed plastic is not HV insulation. Clearances live on the boards and in rated wire; a printed
part only keeps fingers away (plan §4).

## `dekatron-bench-test/`: A101 bench test fixture

A clamshell around the 30 × 70 mm perf board of the
[optional A101 bench test](../docs/bringup.md#optional-a101-bench-test), a housing for the A101
socket and a shroud over the tube.

| Part | Files | Qty | Status |
|---|---|---|---|
| Clamshell base | `clamshell-base-v0` | 1 | Printed and fitted (2026-10-10) |
| Clamshell top | `clamshell-top-v0` | 1 | Printed and fitted (2026-10-10) |
| A101 socket housing | `socket-housing-v0` | 1 | Printed and fitted (2026-10-11), black matte PLA. Shaped for the original PL30-2p socket |
| Tube shroud | `tube-shroud-v0` | 1 | Printed and fitted (2026-10-11), black matte PLA |

Hardware: 2 × M2 × 6 mm machine screws and 2 × M2 × 4 × 3.2 mm knurled brass threaded inserts
(clamshell). Hardware for the socket housing and shroud: to be added.

**The socket is the hard part to source.** The housing is built around the original A101 socket
(PL30-2p, ПЛ30-2п), which is very rare: A101 tubes sell on eBay at reasonable prices, but no
sockets could be found (2026-10-11). To reproduce this fixture, plan on a different socket or a
custom one, and redesign the housing to suit. A promising start, not yet tried here: a
[3D-printable PL30-2p socket for the A-101 / A-102](https://www.printables.com/model/1337925-dekatron-nixie-tube-socket-pl30-2p-for-a-101-a-102) on Printables. As above, the plastic
is not HV insulation: the anode pin's clearance to its neighbours must come from air gap and
rated wire.
