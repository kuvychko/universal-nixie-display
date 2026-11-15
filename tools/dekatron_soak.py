#!/usr/bin/env python3
"""
Dekatron soak test at the controller's operating point, driven through firmware 0.2
(firmware/dekatron/) over its USB console: continuous rotation at 2000 steps/s with the
production timing (100 us phase, index checked on every step 100 us after release), half the
time forward and half in reverse. It switches HV on itself: run it only with the board set up and
hands clear. Ctrl+C or any error sends DARK at once.

    uv run --group bench python tools/dekatron_soak.py                 # 60 min, 30 each way
    uv run --group bench python tools/dekatron_soak.py --minutes 2     # quick check

Every --every seconds it appends one row to characterization/dekatron/<date>_soak.csv: elapsed
time, direction, HV and VIN, and the controller's counters since the start (index crossings
expected and observed, mismatch, idx_late, skips, sense_misses, recovery_failures, home_fail,
trips), so an interrupted soak keeps its data. It stops early if the tube goes dark or a fault
latches.

SPDX-License-Identifier: MIT
"""

import argparse
import csv
import datetime
import pathlib
import sys
import time

import serial

from hv_bringup import find_port, parse_status, send

ROOT = pathlib.Path(__file__).resolve().parent.parent
RATE = 2000
COUNTERS = ["idx_exp", "idx_obs", "mismatch", "idx_late", "skips", "sense_misses", "recovery_failures",
            "home_fail", "trips"]
DIAG = ["last_skip", "miss_ndx_raw", "miss_expected", "miss_mode", "rehome_offset", "recovery_ms", "late_ndx_raw"]
FIELDS = ["time", "elapsed_s", "dir", "power", "mode", "fault", "hv", "vin", *COUNTERS, *DIAG]


class Console:
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
        self.cmd("light")
        end = time.monotonic() + 13
        while time.monotonic() < end:
            d = self.status()
            if d["power"] == "lit" and d["valid"] == "1":
                return
            time.sleep(0.1)
        sys.exit(f"did not light and home: {d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--minutes", type=float, default=60, help="total, split evenly between directions")
    ap.add_argument("--every", type=float, default=10, help="status row interval, s")
    ap.add_argument("--csv", type=pathlib.Path)
    args = ap.parse_args()

    out = args.csv or ROOT / "characterization/dekatron" / f"{datetime.date.today()}_soak.csv"
    new = not out.exists()
    with serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser, \
            out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        c = Console(ser)
        try:
            c.cmd("local")
            d = c.status()
            if d["fw"] != "0.2":
                sys.exit(f"needs controller firmware 0.2, found {d['fw']}")
            if d["fault"] != "none":
                sys.exit(f"fault latched: {d['fault']}; send 'clear' after checking the board")
            c.light()
            base = c.status()
            t0 = time.monotonic()
            half = args.minutes * 60 / 2
            prev = 0
            for sign, name in ((1, "fwd"), (-1, "rev")):
                c.cmd(f"rotate {sign * RATE}")
                print(f"{datetime.datetime.now():%H:%M:%S}  rotate {sign * RATE} steps/s for {half:.0f} s", flush=True)
                end = time.monotonic() + half
                while True:
                    time.sleep(min(args.every, max(0.0, end - time.monotonic())))
                    d = c.status()
                    row = {k: int(d[k]) - int(base[k]) for k in COUNTERS}
                    row.update(time=datetime.datetime.now().isoformat(timespec="seconds"),
                               elapsed_s=round(time.monotonic() - t0), dir=name, power=d["power"], mode=d["mode"],
                               fault=d["fault"], hv=d["hv"], vin=d["vin"], **{k: d[k] for k in DIAG})
                    w.writerow(row)
                    f.flush()
                    print(f"  {row['elapsed_s']:5d} s {name} hv {row['hv']}  "
                          + " ".join(f"{k} {row[k]}" for k in COUNTERS), flush=True)
                    if row["mismatch"] != prev:
                        prev = row["mismatch"]
                        print("    last miss: " + " ".join(f"{k} {d[k]}" for k in DIAG), flush=True)
                    if d["power"] != "lit" or d["fault"] != "none":
                        sys.exit(f"stopped: power {d['power']} ({d['dark_reason']}), fault {d['fault']}")
                    if time.monotonic() >= end:
                        break
                c.cmd("stop")
        finally:
            try:
                send(ser, "dark")
                send(ser, "remote")
            except SystemExit:
                print("could not confirm dark: check the board", file=sys.stderr)
    print(f"rows appended to {out}")


if __name__ == "__main__":
    main()
