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

<img src="../website/assets/dekatron-bench-test.jpg" alt="The assembled A101 bench fixture: the tube in its black socket housing and shroud, wired to the white clamshell with two pushbuttons on top, and the red and black HV leads" height="260"> <img src="../website/assets/dekatron-bench-test-exploded.jpg" alt="The fixture taken apart: socket housing with its brass inserts, the PL30-2p socket with its wiring, the A101 tube, the shroud, and the opened clamshell showing the perf board with its resistors and pushbuttons" height="260">

<img src="../website/assets/dekatron-bench-test-no-shroud.jpg" alt="The tube seated in its socket on the housing, the socket's metal bracket held by two screws, with the shroud set beside it" height="260">

*Assembled; taken apart (socket housing, socket, A101, shroud, clamshell base with the perf board
and clamshell top); and with the shroud off, showing the socket bracket on the housing. Photographed
2026-10-18, tube unlit.*

Hardware, all knurled brass threaded inserts set into the printed parts and machine screws into
them:

| Where | Inserts | Screws |
|---|---|---|
| Clamshell top to base | 2 × M2 × 4 × 3.2 mm | 2 × M2 × 6 mm |
| Shroud to socket housing (top face) | 4 × M2 × 6 × 3.2 mm | 4 × M2 × 12 mm |
| Socket bracket to socket housing | 2 × M3 × 6 × 4.2 mm | 2 × M3 × 6 mm |
| Socket housing side faces: mounting points for the display enclosure later, unused here | 4 × M3 × 6 × 4.2 mm | — |

Assembly: set the inserts, screw the socket's bracket to the housing (M3 × 6), seat the tube, then
fit the shroud over it (M2 × 12).

The shroud is there so the pins stay covered even if the tube is partly pulled out of its socket,
and for the look: one colour, smooth lines, no visible hardware. PLA is fine next to the tube
because a dekatron dissipates very little: about 42 mW on the bench (147 V maintaining at 288 µA,
[bench results](../docs/bringup.md#optional-a101-bench-test)).

**The socket is the hard part to source.** The housing is built around the original A101 socket
(PL30-2p, ПЛ30-2п), which is very rare: A101 tubes sell on eBay at reasonable prices, but no
sockets could be found (2026-10-11). To reproduce this fixture, plan on a different socket or a
custom one, and redesign the housing to suit. A promising start, not yet tried here: a
[3D-printable PL30-2p socket for the A-101 / A-102](https://www.printables.com/model/1337925-dekatron-nixie-tube-socket-pl30-2p-for-a-101-a-102) on Printables. As above, the plastic
is not HV insulation: the anode pin's clearance to its neighbours must come from air gap and
rated wire.
