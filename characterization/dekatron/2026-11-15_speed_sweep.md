# Dekatron speed sweep follow-up: 3000-5000 steps/s, board 1 (2026-11-15)

Extends the [2026-11-12 sweep](2026-11-12_speed_sweep.md), which stopped at 3000 steps/s with
50 and 75 µs phase still clean. Same board, tube, bring-up firmware (unchanged since 6079a85),
host script and method; 5000 steps/s is the firmware's `SWEEP_HZ_MAX`. Production firmware 0.2
was swapped out for the run and reflashed afterwards.

    uv run --group bench python tools/dekatron_speed.py --phases 75,50,40 --rates 3000,4000,5000

Raw data: [2026-11-15_speed_sweep.csv](2026-11-15_speed_sweep.csv) (48 runs, 14:26).
HV 452.6-454.1 V before and after every burst, PGOOD high throughout, tube warm.

## Results

Three runs of 1000 steps per direction; rest = period − 3 × phase.

| Phase | Rate | Rest | Failed runs (fwd + rev) | Notes |
|---|---|---|---|---|
| 75 µs | 3000 | 108 µs | 0 of 6 | repeat of 11-12: clean again |
| 75 µs | 4000 | 25 µs | 6 of 6 | index blind (sample 15 µs); net −2, −2, −2, −2, −3, +4 |
| 50 µs | 3000 | 183 µs | 0 of 6 | repeat of 11-12: clean again |
| 50 µs | 4000 | 100 µs | 0 of 6 | **fastest clean point** |
| 50 µs | 5000 | 50 µs | 6 of 6 | gaps: 14, 11, 12, 11, 10, 9 lost; net 4, 1, 2, 1, 0, −1 |
| 40 µs | 3000 | 213 µs | 2 of 6 (rev) | gaps 1 lost each; net +2, +1 |
| 40 µs | 4000 | 130 µs | 0 of 6 | |
| 40 µs | 5000 | 80 µs | 1 of 6 (rev) | 1 step lost |

* **Fastest clean point: 4000 steps/s at 50 µs phase** (rest 100 µs), four times the
  datasheet's 1 kHz.
* At 5000 steps/s the two limits meet: 50 µs phase leaves only 50 µs of rest (miscounts, as at
  150 µs/2000 and 100 µs/3000 on 11-12), and 40 µs phase, which leaves 80 µs, is at the pulse
  floor: one or two lost steps at 80 and 213 µs of rest alike, rev only. **Phase floor: 40 µs is
  marginal, 50 µs clean.**
* At 50 µs/5000 the index sample (40 µs after release) still saw K1, so the gap check is valid.
  The net error equals the lost steps mod 10 in every run; one run (10 lost) reads 0 on the net
  error alone.
* The rest limit stays between about 50 and 67 µs; no new point narrows it.

Operating point unchanged (100 µs phase, ≤ 2000 steps/s). The `board.h` comment calling 3000
steps/s at 50 µs "the fastest clean point" predates this run.
