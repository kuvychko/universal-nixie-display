# Dekatron step-rate and guide-phase limits, board 1 (2026-11-12)

Where does the A101 start to lose counts on the controller/PSU board, as a function of step rate
and guide phase? Board 1 after its Gate 3 reworks, the A101 in its socket housing, bring-up
firmware `sweep` command ([firmware/dekatron-bringup](../../firmware/dekatron-bringup/README.md)),
host script [`tools/dekatron_speed.py`](../../tools/dekatron_speed.py).

Raw data: [2026-11-12_speed_sweep.csv](2026-11-12_speed_sweep.csv) (303 runs),
[2026-11-12_ndx_latency.csv](2026-11-12_ndx_latency.csv) (15 runs).

## Method

* One step = G1 on → G2 on → G1 off → G2 off, each transition one *phase* apart (G2 first for
  rev); each guide is low for 2 × phase. *Rest* = step period − 3 × phase.
* Each run: home to K1 at 20 steps/s (500 µs phase), then a burst of 1000 steps on an absolute
  timetable, NDX sampled once per step 10 µs before the next step (latency runs: at a set delay
  after G2 releases). Afterwards single steps at 20 steps/s, continuing in the same direction,
  until K1: the **net position error**.
* Two checks per run: the gaps between index hits (10 = clean, 11 = a lost step, 9 = an extra
  step, a multiple of 10 = an index sample missed with the count right), and the net error. A run
  is clean only if both show no error. Three repeats per point; a phase stops after two
  consecutive failing rates.
* Grid: phase 500, 300, 200, 150, 100, 75, 50, 30, 20 µs × 200-3000 steps/s, both directions,
  limited to rest ≥ 20 µs.
* Conditions: HV 452.0-453.1 V before and after every burst, PGOOD high throughout (no low
  sample in any run), VIN 11.9 V, RTN 50.3-50.4 V, room temperature, tube already warm.
* Firmware timing: guide edges on time (slip 0 µs, the odd 5-7 µs); a step's first edge up to
  32 µs late when the previous step's sample-and-check work (14-42 µs) did not fit in the time
  left after the sample. That only lengthens the rest.

## K1 latency

10 steps/s, 500 µs phase, NDX sampled at a set delay after G2 releases; 100 steps per point.

| Sample delay after G2 release | K1 hits |
|---|---|
| 0, 5, 10, 20, 30 µs | 0/10 |
| 40, 50, 60, 80, 100, 150, 200, 300, 500, 1000 µs | 10/10 |

NDX crosses the 2.0 V threshold **30-40 µs after G2 releases** at 453 V. This includes the glow's
transfer to K1 and the 12 µs index filter (hardware.md D9); the run does not separate them. Every
latency run's net position error was 0: the steps happened even when the index read 0. Gate 3's
miss at 60 µs (2026-10-25) was with HV at ≈ 415 V, before the reworks; whether HV explains the
difference is not tested.

## Rate × phase grid

Clean = all 3 runs × 1000 steps without error. Rates beyond a phase's last column do not fit
(rest < 20 µs).

| Phase | Clean up to (fwd / rev) | First failure | Rest at the failure |
|---|---|---|---|
| 500 µs | 500 / 500 steps/s (highest that fits) | none | — |
| 300 µs | 1000 / 1000 (highest tried that fits) | none | — |
| 200 µs | 1500 / 1500 (highest tried that fits) | none | — |
| 150 µs | 1500 / 1500 | 2000 steps/s: fwd 2 of 3 runs, rev 3 of 3 | 50 µs |
| 100 µs | 2000 / 2000 | 3000 steps/s: fwd 3 of 3, rev 2 of 3 | 33 µs |
| 75 µs | 3000 / 3000 (highest tried) | none | — |
| 50 µs | 3000 / 3000 (highest tried) | none | — |
| 30 µs | sporadic at every rate | fwd 200: 2 of 3 runs (1 step lost each); rev 300: 3 of 3 (3-9 lost) | ≥ 1.3 ms |
| 20 µs | none | 200 steps/s, every run: 39-299 steps lost per 1000 | ≥ 3.3 ms |

Two separate limits show:

1. **Short phases lose steps at any rate.** At 30 µs, 1-9 steps per 1000 were lost (the glow
   fell behind), regardless of rest. At 20 µs the glow mostly stayed where it was through the
   pulses: long runs of consecutive index hits while it sat on K1. Every phase from 50 µs up
   was clean at all its rates. **Phase floor: between 30 and 50 µs.**
2. **Short rests miscount when the phase is long enough.** The failures at 150 µs/2000 steps/s
   (rest 50 µs) and 100 µs/3000 steps/s (rest 33 µs) are mostly *extra* steps: net errors of
   −2 to −4, the glow ahead of the count. Clean runs had rests of 108 µs (75 µs at 3000 steps/s)
   and above. **Rest limit: between about 50 and 108 µs**, near the 30-40 µs K1 latency
   plus margin; not narrowed further.

Fastest clean point: 3000 steps/s (the highest rate tried) at 50 and 75 µs phase. That is three
times the datasheet's 1000 Hz and well under its 200 µs minimum phase.

## Limits of this result

* Three runs of 1000 steps per point: a clean point means no error in 3000 steps, not zero
  error. Plan §9's 1000-trial homing characterisation is separate (bring-up step 5).
* One board, one tube, warm, 453 V, one day. Not tested: cold tube, other HV setpoints, rates
  above 3000 steps/s, rests between 50 and 108 µs, sustained running.
* When the index sample fell before the glow reached K1 (rest ≤ 50 µs), only the net error
  checked motion, and it cannot see a lost and an extra step that cancel, or errors that sum
  to a multiple of 10.
