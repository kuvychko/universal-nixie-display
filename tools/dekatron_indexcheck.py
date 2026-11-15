#!/usr/bin/env python3
"""
Dekatron periodic index check and skip recovery bench test, driven through the controller
firmware 0.2 (firmware/dekatron/) over its USB console. It switches HV on itself: run it only with
the board set up and hands clear. Ctrl+C or any error switches HV off at once.

    uv run --group bench python tools/dekatron_indexcheck.py                    # all scenes, 3 min each
    uv run --group bench python tools/dekatron_indexcheck.py --scenes drop,blind
    uv run --group bench python tools/dekatron_indexcheck.py --minutes 1 --open 2000 --interval 10000

Scenes:
  wedge    wedge 5.00-8.00 at 2000 steps/s, clear of K1 and 3 steps from it: no cheap moment,
           so only the hard-limit trip checks the count
  eye      magic eye centred opposite K1 (5), streamed at 25 Hz, never opening onto K1; its
           bookends come within 1 step of K1 when open, so trips should be the cheap kind
  rotate1  rotate at 1 step/s (a seconds display): a trip after most steps; watch for flicker
  hold     moveto 5, then hold: one trip, then none (a held glow cannot lose count)
  drop     the wedge, then a step the tube is never given (inject drop): caught within one
           interval, re-homed, the wedge resumes, skips +1, last_skip +/-1; no fault
  blind    a wedge over K1 (9.00-2.00), then the index blinded for 10 s (inject blind): the re-home fails three
           times and the controller goes dark with index_lost, nothing latched; LIGHT homes again

Each scene appends one row to characterization/dekatron/<date>_index_check.csv (counter deltas
over the scene). Flicker is judged by eye and on video; note it in the matching .md.

SPDX-License-Identifier: MIT
"""

import argparse
import csv
import datetime
import math
import pathlib
import sys
import time

import serial

from hv_bringup import find_port, parse_status, send

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPDATE_HZ = 25
MAX_RATE = 2000
COUNTERS = ["trips", "mismatch", "idx_late", "skips", "sense_misses", "recovery_failures", "home_fail"]
SCENES = ["wedge", "eye", "rotate1", "hold", "drop", "blind"]


class Bench:
    def __init__(self, ser):
        self.ser = ser

    def cmd(self, line):
        r = send(self.ser, line)[-1]
        if not r.startswith("OK"):
            sys.exit(f"{line!r}: {r}")
        return r

    def status(self):
        return parse_status(self.cmd("status"))

    def light(self):
        d = self.status()
        if d["power"] == "lit" and d["valid"] == "1":
            return
        self.cmd("light")
        end = time.monotonic() + 13
        while time.monotonic() < end:
            d = self.status()
            if d["power"] == "lit" and d["valid"] == "1":
                return
            if d["power"] == "dark":
                break
            time.sleep(0.1)
        sys.exit(f"did not light and home: {d}")

    def wait(self, seconds, poll=None):
        """Sleep, polling status; poll(d) may return True to stop early. Returns the last status."""
        end = time.monotonic() + seconds
        d = self.status()
        while time.monotonic() < end:
            if poll and poll(d):
                return d
            time.sleep(0.2)
            d = self.status()
        return d

    def stream(self, seconds, fn):
        start = time.monotonic()
        n = 0
        while (t := time.monotonic() - start) < seconds:
            self.cmd(fn(t))
            n += 1
            delay = start + n / UPDATE_HZ - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    # ---- scenes: each returns (status at the end, notes) ----
    def wedge(self, secs):
        self.cmd(f"wedge 5.00 8.00 {MAX_RATE}")
        return self.wait(secs), ""

    def eye(self, secs):
        # half-width 0.5-4.4 cathodes about 5: from one cathode to just short of K1 (position 0)
        self.stream(secs, lambda t: f"wedgec 5 {0.5 + 3.9 * (1 - math.cos(2 * math.pi * t / 4)) / 2:.2f} {MAX_RATE}")
        return self.status(), ""

    def rotate1(self, secs):
        self.cmd("rotate 1")
        return self.wait(secs), ""

    def hold(self, secs):
        self.cmd("moveto 5")
        return self.wait(secs), ""

    def drop(self, secs):
        self.cmd(f"wedge 5.00 8.00 {MAX_RATE}")
        time.sleep(2)
        before = self.status()
        self.cmd("inject drop")
        d = self.wait(secs, lambda d: d["mismatch"] != before["mismatch"] and d["recovering"] == "0")
        time.sleep(1)
        d = self.status()
        ok = (d["mismatch"] != before["mismatch"] and d["fault"] == "none" and d["power"] == "lit"
              and d["mode"] == "wedge" and d["last_skip"] in ("1", "-1"))
        return d, (f"{'PASS' if ok else 'FAIL'}: detect {d['drop_detect_ms']} ms (interval "
                   f"{d['idxcheck_ms']} ms), recovery {d['recovery_ms']} ms, last_skip {d['last_skip']}, "
                   f"mode {d['mode']}")

    def blind(self, secs):
        self.cmd(f"wedge 9.00 2.00 {MAX_RATE}")  # passes K1 every sweep: the miss comes at once
        time.sleep(2)
        self.cmd("inject blind")
        t0 = time.monotonic()
        d = self.wait(8, lambda d: d["power"] == "dark")
        ok = d["power"] == "dark" and d["dark_reason"] == "index_lost" and d["fault"] == "none"
        time.sleep(max(0.0, 10.5 - (time.monotonic() - t0)))  # let the blind period end
        self.light()
        return self.status(), (f"{'PASS' if ok else 'FAIL'}: dark_reason {d['dark_reason']}, fault {d['fault']}, "
                               f"relit and homed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--scenes", help=f"comma-separated, in order (default: all): {','.join(SCENES)}")
    ap.add_argument("--minutes", type=float, default=3, help="length of wedge/eye/rotate1/hold, min")
    ap.add_argument("--open", type=int, default=5000, help="index-check band opens, ms (firmware default)")
    ap.add_argument("--interval", type=int, default=60000, help="index-check hard limit, ms (firmware default)")
    ap.add_argument("--csv", type=pathlib.Path)
    args = ap.parse_args()

    names = args.scenes.split(",") if args.scenes else SCENES
    bad = [n for n in names if n not in SCENES]
    if bad:
        sys.exit(f"unknown scene(s) {bad}")
    out = args.csv or ROOT / "characterization/dekatron" / f"{datetime.date.today()}_index_check.csv"
    fields = ["time", "scene", "seconds", "open_ms", "interval_ms", *COUNTERS, "max_unchecked_steps", "max_unchecked_ms",
              "drop_detect_ms", "recovery_ms", "last_skip", "notes"]
    new = not out.exists()

    with serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser, \
            out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if new:
            w.writeheader()
        b = Bench(ser)
        try:
            b.cmd("local")
            d = b.status()
            if d["fw"] != "0.2":
                sys.exit(f"needs controller firmware 0.2, found {d['fw']}")
            if d["fault"] != "none":
                sys.exit(f"fault latched: {d['fault']}; send 'clear' after checking the board")
            b.cmd(f"idxcheck {args.open} {args.interval}")
            for name in names:
                b.light()
                b.cmd("stop")
                secs = args.minutes * 60 if name in ("wedge", "eye", "rotate1", "hold") else args.interval / 1000 + 5
                print(f"{datetime.datetime.now():%H:%M:%S}  {name} ({secs:.0f} s)", flush=True)
                before = b.status()
                t0 = time.monotonic()
                after, notes = getattr(b, name)(secs)
                row = {k: int(after[k]) - int(before[k]) for k in COUNTERS}
                row.update(time=datetime.datetime.now().isoformat(timespec="seconds"), scene=name,
                           seconds=round(time.monotonic() - t0), open_ms=args.open, interval_ms=args.interval,
                           max_unchecked_steps=after["max_unchecked_steps"],
                           max_unchecked_ms=after["max_unchecked_ms"], drop_detect_ms=after["drop_detect_ms"],
                           recovery_ms=after["recovery_ms"], last_skip=after["last_skip"], notes=notes)
                w.writerow(row)
                f.flush()
                print("    " + ", ".join(f"{k} {row[k]}" for k in COUNTERS)
                      + f", max unchecked {row['max_unchecked_steps']} steps / {row['max_unchecked_ms']} ms"
                      + (f"\n    {notes}" if notes else ""), flush=True)
                b.cmd("stop")
        finally:
            try:
                send(ser, "dark")
                send(ser, "remote")
            except SystemExit:
                print("could not confirm dark: check the board", file=sys.stderr)
    print(f"rows appended to {out}")


if __name__ == "__main__":
    main()
