# Dekatron soak at the operating point, and the guide-overlap sweep, board 1 (2026-11-15)

Two follow-ups to the [speed sweeps](2026-11-15_speed_sweep.md), same board, tube and session
(HV 452.3-454.5 V throughout, PGOOD high, tube warm).

## Soak: one hour at the operating point

Controller firmware 0.2, `rotate 2000` for 30 min, then `rotate -2000` for 30 min: 100 µs phase,
index checked on every step 100 µs after release, recheck at 170 µs. Script:
[`tools/dekatron_soak.py`](../../tools/dekatron_soak.py); data:
[2026-11-15_soak.csv](2026-11-15_soak.csv) (a row every 10 s, counters since the start;
`idx_exp`/`idx_obs` are 16-bit and wrap, so unwrap mod 65536 before summing).

| | |
|---|---|
| Index crossings checked | 710,471 expected, 710,466 observed: about 7.1 million steps |
| `skips` (count wrong) | **0** |
| `sense_misses` | 5 (1 fwd, 4 rev): index expected, both samples low (`miss_ndx_raw` 97-134 of 4095); re-home found `rehome_offset` 0 each time, recovery 100 ms |
| `idx_late` | 27: low at 100 µs, high at the 170 µs recheck |
| `recovery_failures`, `home_fail`, `trips`, faults | 0 |

A 1-minute dry run before it (not in the CSV) also had one sense miss in about 11,800 checks.
No count error in an hour. The misses and late indexes are the index sensing at its 100 µs
sample, not the glow: about 1 in 140,000 checks missed outright, 1 in 26,000 late.

## Guide overlap

Bring-up firmware with a new `sweepo` command (each guide alone for `solo` µs, with `overlap` µs
of both on between them; negative = a gap with neither on; the sweep loop now writes guide
patterns with `gpio_put_masked`, so at zero overlap one guide releases as the other switches on).
`tools/dekatron_speed.py --overlaps`; data: [2026-11-15_overlap.csv](2026-11-15_overlap.csv)
(102 runs, 3 per direction per point; note `--overlaps=-30,...` with `=` for negative lists).

At the operating point, 100 µs solo, 2000 steps/s (rest = period − 2 × solo − |overlap|):

| Overlap | Rest | Clean runs | |
|---|---|---|---|
| 100 µs (the normal sequence) | 200 µs | 6 of 6 | |
| 75, 50, 30, 20, 10, 5 µs | 225-295 µs | 6 of 6 each | |
| 0 µs | 300 µs | 6 of 6 | |
| gap 10, 20 µs | 290, 280 µs | 6 of 6 each | |
| gap 30 µs | 270 µs | 0 of 6 | 1 index hit of 100 expected; net −3 to +1; not characterised |
| gap 50, 75, 100 µs | 250-200 µs | 0 of 6 each | index high every step (1000 of 100): the glow fell back to its cathode and never moved; net 0 (1000 lost = 100 turns) |

Two-phase steps (zero overlap) at 50 µs solo:

| Rate | Rest | Clean runs |
|---|---|---|
| 3000 steps/s | 233 µs | 6 of 6 |
| 4000 steps/s | 150 µs | 6 of 6 |
| 5000 steps/s (firmware ceiling) | 100 µs | 6 of 6 |

* **The overlap is not needed on this tube at this setting.** The handover tolerates up to 20 µs
  with neither guide on; somewhere between 20 and 30 µs it fails, and from 50 µs the glow returns
  to the cathode it left.
* **Two phases are faster.** A step without overlap takes two phases, not three, so at 50 µs the
  rest at 5000 steps/s is 100 µs instead of 50 µs; clean, where the three-phase step lost 9-14
  steps per 1000. The two-phase ceiling is above 5000 steps/s and was not reached.
* Not changed: the controller keeps the three-phase step at 100 µs / 2000 steps/s.
