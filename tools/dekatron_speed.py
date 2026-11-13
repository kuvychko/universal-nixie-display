#!/usr/bin/env python3
"""
Dekatron speed-sweep experiment: at what step rate and guide phase does the A101 start to lose
counts on this board? Runs the bring-up firmware's `sweep` burst (firmware/dekatron-bringup/)
over a phase x rate grid, both directions, and checks each run two ways:

* the gaps between index hits: 10 = clean, 11 = one lost step, 9 = one extra, 20 = an index
  sample missed (sensing, not motion); a glow stuck on K1 shows as gaps of 1;
* a slow verify afterwards (single steps at 20 Hz until K1), which gives the net position error.

It switches HV on itself: run it only with the board set up and hands clear. HV is refreshed with
a short timeout before each run, so it drops on its own if the script dies; Ctrl+C or any error
switches it off at once.

    uv run --group bench python tools/dekatron_speed.py                     # full grid
    uv run --group bench python tools/dekatron_speed.py --phases 200,100 --rates 500,1000,2000
    uv run --group bench python tools/dekatron_speed.py --latency           # K1 settle time
    uv run --group bench python tools/dekatron_speed.py --selftest          # analysis only, no board

Rows are appended to the CSV as each run finishes (default
characterization/dekatron/<date>_speed_sweep.csv, or _ndx_latency.csv), so an interrupted
sweep keeps its data.

SPDX-License-Identifier: MIT
"""

import argparse
import csv
import datetime
import pathlib
import sys
import time

import serial
from dekatron_demo import Demo
from hv_bringup import find_port, send

CATHODES = 10
REST_MIN_US = 20  # the firmware's SWEEP_REST_MIN
HV_REFRESH_S = 60
VERIFY_MAX_STEPS = CATHODES + 2
DEFAULT_PHASES = (500, 300, 200, 150, 100, 75, 50, 30, 20)
DEFAULT_RATES = (200, 300, 500, 700, 1000, 1500, 2000, 3000)
LATENCY_SAMPLES = (0, 5, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 500, 1000)

FIELDS = (
    "time", "mode", "dir", "phase_us", "hz", "rest_us", "sample_us", "n", "done", "stop", "hits",
    "expected_hits", "bad_gaps", "lost", "extra", "ambiguous", "ndx_missed", "verify_err", "ok",
    "slip_max_us", "start_late_us", "work_max_us", "hv_pre", "hv_post", "pgood_low",
)


def wrap(d):
    """Signed position difference in -4..5 cathodes."""
    d %= CATHODES
    return d - CATHODES if d > CATHODES // 2 else d


def analyse_hits(hits, n):
    """
    Gap analysis of a sweep that started on K1. Each gap's distance from the nearest multiple of
    10 is a step error: positive = steps lost (the glow fell behind), negative = extra steps.
    A gap that is a multiple of 10 other than 10 itself means index samples were missed while the
    count stayed right. An error of exactly 5 is ambiguous.
    """
    r = dict(bad_gaps=0, lost=0, extra=0, ambiguous=0, ndx_missed=0)
    prev = 0
    for h in hits:
        g, prev = h - prev, h
        if g == CATHODES:
            continue
        r["bad_gaps"] += 1
        k = round(g / CATHODES)
        err = g - CATHODES * k
        if abs(err) == CATHODES // 2:
            r["ambiguous"] += 1
        elif err > 0:
            r["lost"] += err
        elif err < 0:
            r["extra"] -= err
        r["ndx_missed"] += max(0, k - 1)
    # Fewer than 10 steps after the last hit is normal. A longer tail shows missed samples or lost
    # steps; the slow verify tells them apart, so it counts as index-missed here.
    tail = n - prev
    if tail >= CATHODES:
        r["bad_gaps"] += 1
        r["ndx_missed"] += tail // CATHODES
    return r


def expected_verify_steps(n):
    """Steps to K1, continuing in the sweep's direction, after n clean steps from K1."""
    return (CATHODES - n % CATHODES) % CATHODES


def read_sweep(ser, timeout_s):
    """Read from the 'OK sweep done' line to END; return (fields, hits)."""
    deadline = time.monotonic() + timeout_s
    done, hits = None, []
    while time.monotonic() < deadline:
        raw = ser.readline().decode(errors="replace").strip()
        if not raw:
            continue
        if raw.startswith("FAULT"):
            print(raw, file=sys.stderr)
        elif raw.startswith("OK sweep done"):
            done = dict(f.split("=", 1) for f in raw.split()[3:])
        elif raw.startswith("HITS "):
            hits += [int(x) for x in raw[5:].split(",") if x]
        elif raw == "END":
            if done is None:
                sys.exit("END without 'sweep done'")
            return done, hits
    sys.exit("sweep did not finish in time")


class Sweeper:
    def __init__(self, ser, writer, fh, n):
        self.demo = Demo(ser)
        self.ser = ser
        self.writer = writer
        self.fh = fh
        self.n = n

    def refresh_hv(self, need_s):
        self.demo.cmd(f"on {max(HV_REFRESH_S, int(need_s) + 10)}")

    def verify(self, fwd):
        """Single steps at 20 Hz until K1; returns the number of steps, or None if none seen."""
        for s in range(VERIFY_MAX_STEPS + 1):
            time.sleep(0.02)
            if self.demo.at_k1():
                return s
            self.demo.step(1, fwd=fwd, hz=20)
        return None

    def run(self, mode, fwd, phase, hz, sample=None, n=None):
        n = n or self.n
        period = 1_000_000 // hz
        rest = period - 3 * phase
        run_s = n * period / 1e6
        self.refresh_hv(run_s)
        self.demo.pos = None
        self.demo.home()  # always forward, at 20 Hz; leaves the glow on K1
        time.sleep(0.05)
        cmd = f"sweep {n} {'fwd' if fwd else 'rev'} {phase} {hz}" + ("" if sample is None else f" {sample}")
        reply = send(self.ser, cmd)
        if not reply[-1].startswith("OK sweep"):
            sys.exit(f"{cmd!r}: {reply}")
        res, hits = read_sweep(self.ser, run_s + 10)
        done = int(res["done"])
        a = analyse_hits(hits, done)
        steps = self.verify(fwd) if res["stop"] == "done" else None
        verify_err = None if steps is None else wrap(steps - expected_verify_steps(done))
        motion_ok = (res["stop"] == "done" and steps is not None and verify_err == 0 and a["lost"] == 0
                     and a["extra"] == 0 and a["ambiguous"] == 0)
        row = dict(
            time=datetime.datetime.now().isoformat(timespec="seconds"), mode=mode,
            dir="fwd" if fwd else "rev", phase_us=phase, hz=hz, rest_us=rest,
            sample_us=rest - 10 if sample is None else sample, n=n, done=done, stop=res["stop"],
            hits=int(res["hits"]), expected_hits=done // CATHODES, **a,
            verify_err="none" if verify_err is None else verify_err, ok=int(motion_ok),
            slip_max_us=res["slip_max_us"], start_late_us=res["start_late_us"],
            work_max_us=res["work_max_us"], hv_pre=res["hv_pre"], hv_post=res["hv_post"],
            pgood_low=res["pgood_low"],
        )
        self.writer.writerow(row)
        self.fh.flush()
        print(f"{row['dir']} phase {phase:4d} us {hz:5d} Hz rest {rest:6d} us sample {row['sample_us']:5d} us: hits {row['hits']}/"
              f"{row['expected_hits']} lost {a['lost']} extra {a['extra']} ndx_missed {a['ndx_missed']} "
              f"verify {row['verify_err']} slip {row['slip_max_us']}/{row['start_late_us']} us work {row['work_max_us']} us -> {'ok' if motion_ok else 'FAIL'}")
        if res["stop"] != "done":
            sys.exit(f"sweep stopped: {res['stop']}")
        if steps is None:
            sys.exit("no index within a turn after the sweep: glow lost? HV off")
        return motion_ok

    def grid(self, phases, rates, repeats):
        summary = {}
        for fwd in (True, False):
            for phase in phases:
                fails = 0
                best = None
                for hz in rates:
                    if 1_000_000 // hz < 3 * phase + REST_MIN_US:
                        break
                    results = [self.run("grid", fwd, phase, hz) for _ in range(repeats)]  # every repeat runs
                    ok = all(results)
                    if ok:
                        best, fails = hz, 0
                    else:
                        fails += 1
                        if fails >= 2:
                            break
                summary[("fwd" if fwd else "rev", phase)] = best
        print("\nHighest rate with every repeat clean (of the rates tried):")
        for (d, phase), best in summary.items():
            print(f"  {d} phase {phase:4d} us: {best if best else 'none'} Hz")

    def latency(self, samples, n):
        print("NDX latency: fraction of K1 arrivals seen vs. sample delay after the guide release")
        for s in samples:
            self.run("latency", True, 500, 10, sample=s, n=n)


def selftest():
    clean = list(range(10, 101, 10))
    assert analyse_hits(clean, 100) == dict(bad_gaps=0, lost=0, extra=0, ambiguous=0, ndx_missed=0)
    lost1 = [10, 20, 31, 41, 51]  # one step lost between 20 and 31
    assert analyse_hits(lost1, 55)["lost"] == 1
    extra1 = [10, 19, 29, 39]
    assert analyse_hits(extra1, 40)["extra"] == 1
    missed = [10, 30, 40]  # sample at 20 missed, count right
    r = analyse_hits(missed, 40)
    assert r["lost"] == 0 and r["extra"] == 0 and r["ndx_missed"] == 1, r
    stuck = [10, 11, 12, 22]  # glow held on K1 for two extra steps
    assert analyse_hits(stuck, 25)["lost"] == 2
    tail = [10, 20]  # nothing for the last 15 steps
    assert analyse_hits(tail, 35)["ndx_missed"] == 1
    assert wrap(11) == 1 and wrap(9) == -1 and wrap(5) == 5 and wrap(6) == -4
    assert expected_verify_steps(1000) == 0 and expected_verify_steps(1003) == 7
    print("selftest ok")


def ints(s):
    return tuple(int(x) for x in s.split(","))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--phases", type=ints, default=DEFAULT_PHASES, help="guide phases, us (comma list)")
    ap.add_argument("--rates", type=ints, default=DEFAULT_RATES, help="step rates, Hz (comma list, ascending)")
    ap.add_argument("--n", type=int, default=1000, help="steps per sweep run")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--latency", action="store_true", help="measure the K1 settle time instead of the grid")
    ap.add_argument("--latency-n", type=int, default=100, help="steps per latency point (10 Hz)")
    ap.add_argument("--out", help="CSV path")
    ap.add_argument("--selftest", action="store_true", help="check the gap analysis and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    root = pathlib.Path(__file__).resolve().parent.parent
    suffix = "ndx_latency" if args.latency else "speed_sweep"
    out = pathlib.Path(args.out) if args.out else (
        root / "characterization" / "dekatron" / f"{datetime.date.today().isoformat()}_{suffix}.csv")
    new = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as fh, \
            serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        if new:
            writer.writeheader()
        sw = Sweeper(ser, writer, fh, args.n)
        try:
            if args.latency:
                sw.latency(LATENCY_SAMPLES, args.latency_n)
            else:
                sw.grid(args.phases, args.rates, args.repeats)
        except KeyboardInterrupt:
            pass
        finally:
            print(send(ser, "off")[-1])
            print(f"data: {out}")


if __name__ == "__main__":
    main()
