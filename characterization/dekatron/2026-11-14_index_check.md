# Dekatron periodic index check and skip recovery, board 1 (2026-11-14)

Does the controller firmware 0.2 keep the count confirmed without the glow ever having to pass
K1? Does it catch a lost step, recover without latching, and stay pleasant to look at? Board 1,
the A101 in its socket housing. Controller firmware 0.2 ([firmware/dekatron](../../firmware/dekatron/README.md)),
driven over the USB console by [`tools/dekatron_indexcheck.py`](../../tools/dekatron_indexcheck.py).
Raw data: [2026-11-14_index_check.csv](2026-11-14_index_check.csv) (one row per scene, counter
changes over the scene).

## What is tested

* **Periodic index check.** If the count has gone unconfirmed for long enough, the glow takes a
  short trip to K1 and back. The final setting is a band, 5-60 s (below).
* **Skip recovery.** A mismatch re-homes at once, resumes what was showing and counts the event
  (`skips`, `sense_misses`, `last_skip` in the I2C status). Nothing latches. A re-home that fails
  3 times goes dark with `index_lost`, and `LIGHT` works again.
* Two bench hooks, on the console only:
  * `inject drop` counts a step the tube is never given.
  * `inject blind` reads the index as dark for 10 s.

## Tuning the trip on the tube (watched by eye)

| Trip timing | Interval | What was seen |
|---|---|---|
| 2000 steps/s, 100 µs phase | 1 s, natural boundaries from 0.5 s | About 2 trips/s in the wedge and eye: a plainly visible "heartbeat" (the early window opened at half the interval, which doubled the rate; fixed) |
| 3000 steps/s, 50 µs phase (the speed sweep's fastest clean point) | 5 s, natural boundaries from 4.5 s | One trip per ~5 s; each one still visible as a streak across the dark cathodes between the wedge and K1 |
| 3000 steps/s, 50 µs phase | **band 5-60 s**: from 5 s only at a cheap moment, at 60 s whatever is showing | Final setting (user, 2026-11-14). The run below uses it |

A cheap moment is one of these:
* The glow is within 2 steps of K1 and about to step away from it. The trip then lights only a
  cathode or two beside the lit part. A glow stepping toward K1 gets there by itself.
* A queue ends there.
* A streamed wedge or eye update moves the bookends by a cathode or more.

The user's reasoning: this is a display, so it should look pleasant. A rare skip that stays on
show for up to a minute is the better trade.

The trips across the dark part of the ring were visible at 1 s and at 5 s. The user went ahead to
the full run after watching the band's smoke pass, but no video verdict on the band is recorded
yet.

## Full run (band 5-60 s), 18:41-18:55

Conditions: board lit and homed before each scene, wedge rates 2000 steps/s.

| Scene | Length | Trips | Mismatches | Late index | Longest unchecked | Result |
|---|---|---|---|---|---|---|
| `wedge 5.00 8.00 2000`: clear of K1, never within 2 steps | 180 s | 3 | 0 | 0 | 60.0 s, 98974 steps | One trip per 60 s limit, as designed |
| Eye centred on 5, half-width 0.5-4.4 streamed at 25 Hz | 180 s | 30 | 0 | 0 | ≤ 9 s (smoke pass) | All trips cheap: a 1-step hop as the eye opens to cathodes 1 and 9 |
| `rotate 1` (a seconds display) | 180 s | 0 | 0 | 0 | 9 s, 10 steps (smoke pass) | Confirmed on its own every turn |
| `moveto 5`, then hold | 180 s | 1 | 0 | 0 | — | One trip after the move, then left alone |
| Drop: the wedge, then `inject drop` | 61 s | 0 | 1 | 0 | — | **Pass**: caught 58.0 s after the drop (limit 60 s), re-homed and wedge resumed in 100 ms, `skips` +1, `last_skip` −1, no fault |
| Blind: wedge 9.00-2.00 over K1, then `inject blind` | 13 s | 0 | 1 | 0 | — | **Pass**: 3 re-home attempts, dark with `index_lost`, `recovery_failures` +1, fault none; `LIGHT` homed again |

"Longest unchecked" is kept since boot, so the CSV repeats the wedge's 60 s in later rows. The
eye and rotate values come from the smoke pass at 18:30, in which each ran first.

* **No unintended mismatch, late index or skip.** From the wedge's 98974 steps per 60 s, the wedge and
  eye scenes took several hundred thousand steps. Most of them were at 2000 steps/s, and the trips
  were at 3000 steps/s.
* **The drop was caught inside the limit.** It came about 2 s into a 60 s stretch that had
  already started, so it was found 58 s later. A count error stands for at most one limit.
* **Recovery takes 100 ms.** That is the spin to K1 and a confirmed turn at 200 steps/s, before the
  effect carries on. It is visible, and only ever follows a real mismatch.

## Limits of this result

* One board, one warm tube, one session. No skip occurred naturally, so recovery is only shown
  with injected faults. The injected drop is a step the tube never got: lost-step behaviour, not
  an extra step.
* The final band has no visibility verdict yet, by eye or on video. Neither has a cheap trip
  (1-2 cathodes next to the lit sector).
* Errors that cancel between two checks remain invisible. With a 60 s limit they can build up for
  up to a minute.
