# Dekatron controller/PSU — proposed changes for a rev 2

> [!NOTE]
> **No rev 2 is planned.** This project stays on the board as fabricated (commit f4fd414), with
> the reworks below fitted by hand. The list is for anyone who builds the board again or adapts
> the design: these are the changes bring-up of board 1 says are worth making. None of them has
> been laid out or tested as a new board.

## HV converter: current sense and layout

Board 1 as built regulated at 452 V with the tube out, but with the tube lit it sagged to about
415 V with COMP at its clamp. The cycles ended early at about 0.29 A, below the 0.42-0.49 A
current limit, because pickup at U106 pin 7 (CS) added to the sense ramp and reached the 100 mV
threshold first. Measured at the pin: +400 mV spikes at turn-on, dips to −300 mV after turn-off.
Full story in the [assembly log](../../characterization/dekatron/2026-10-24_assembly_log.md) and
[hardware.md](../../docs/hardware.md#hv-boost-stage) ("Board 1: HV short with the tube lit").

1. **Filter the CS signal at the pin.** The 100 Ω + 470 pF filter (R118, C119) sits near the
   inductor, about 20 mm of trace away from U106 pin 7, so the trace picks up the switching field
   after the filter. Place the filter capacitor right at pin 7, returned to AGND at the
   adjacent pin 6, with R118 close to it. On board 1 a 470 pF tacked across pins 7 and 5/6 alone
   raised HV from 415 to 430.6 V.
2. **Kelvin-sense the current.** Run the CS trace and its return as a pair from R117's pads, and
   bring R117's ground end back close to U106 (it is about 36 mm away on board 1). Measured 0 Ω
   from pin 6 to R117's ground, so the problem is the loop's inductance, not its resistance.
3. **Move or shield the inductor.** L102 is an unshielded radial drum next to R118/C119. Keep the
   CS parts and trace well away from it, or use a shielded part with the same ratings.
4. **Tighten the power layout.** Keep the switching loop (input capacitor, L102, Q102, R117, D103)
   small and away from the controller's analog pins (CS, COMP, FB, RT).
5. **Start from board 1's reworked values, then check them on the new layout.** With all three
   reworks fitted, board 1 holds 452.7 V with the tube lit, PGOOD high, COMP 1.94 V (off its
   2.5-2.8 V clamp), 0.82 W in:
   - sense resistor **0.18 Ω** (0.22 Ω with 1 Ω across it); current limit 0.52-0.59 A, inside
     the kit inductor's 0.71 A rating
   - R_T **112k** (147k with 470k across it), 199 kHz measured
   - 470 pF at the CS pin (item 1)

   With better filtering and layout the original 0.22 Ω and 147k may be enough; that is _open_
   until measured. The 0.18 Ω change made the biggest single difference on board 1.

## Links

6. **Drop LK4** (tripler output to the anode resistor string). The anode string ends at the
   off-board tube, so leaving the tube unplugged isolates the tube section just as well; on the
   board the link is only an extra length of HV trace.
