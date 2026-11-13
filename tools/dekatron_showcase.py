#!/usr/bin/env python3
"""
Dekatron showcase for filming, driven through the controller firmware (firmware/dekatron/) over
its USB console. It switches HV on itself: run it only with the board set up and hands clear.

    uv run --group bench python tools/dekatron_showcase.py                 # all scenes, ~1.5 min; magic eye first
    uv run --group bench python tools/dekatron_showcase.py --list
    uv run --group bench python tools/dekatron_showcase.py --scenes tuning,vu --countdown 0

It waits --countdown seconds (time to start recording), lights the tube, runs the scenes with a
short hold between them and prints a timestamped scene log for editing. Ctrl+C or any error
switches HV off at once; the console is handed back to I2C at the end.

Orientation (docs/hardware.md): K1 = position 0 at 1 o'clock, positions clockwise, 36 degrees
apart, so cathode 9 is near 12 o'clock: the default centre of the magic eye.

SPDX-License-Identifier: MIT
"""

import argparse
import math
import random
import sys
import time

import serial

from hv_bringup import find_port, parse_status, send

UPDATE_HZ = 25  # streamed wedge updates; 20/s was tested on board 1 (bringup step 4)
MAX_RATE = 2000  # firmware step limit, steps/s


class Show:
    def __init__(self, ser, eye_centre, seed):
        self.ser = ser
        self.eye = eye_centre
        self.rng = random.Random(seed)
        self.t0 = time.monotonic()

    def cmd(self, line):
        r = send(self.ser, line)[-1]
        if r == "ERR state" and self.recover():
            r = send(self.ser, line)[-1]
        if not r.startswith("OK"):
            sys.exit(f"{line!r}: {r}")
        return r

    def recover(self):
        """After an index mismatch the controller stops the effect and re-homes; wait for it."""
        end = time.monotonic() + 5
        while time.monotonic() < end:
            d = parse_status(send(self.ser, "status")[-1])
            if d["power"] != "lit":
                return False
            if d["valid"] == "1":
                kind = "glow off count" if d["rehome_offset"] not in ("0", "-1") else "sense miss"
                self.stamp(f"  re-homed after index mismatch ({kind}: offset {d['rehome_offset']}, "
                           f"ndx_raw {d['miss_ndx_raw']}, expected {d['miss_expected']}, mode {d['miss_mode']})")
                return True
            time.sleep(0.05)
        return False

    def status(self):
        return parse_status(self.cmd("status"))

    def stamp(self, text):
        t = time.monotonic() - self.t0
        print(f"{int(t // 60):02d}:{t % 60:04.1f}  {text}", flush=True)

    def stream(self, seconds, fn):
        """Call fn(t) at UPDATE_HZ for `seconds`; fn returns a console command."""
        start = time.monotonic()
        n = 0
        while True:
            t = time.monotonic() - start
            if t >= seconds:
                return
            self.cmd(fn(t))
            n += 1
            delay = start + n / UPDATE_HZ - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def wait_idle(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.status()["mode"] == "idle":
                return
            time.sleep(0.1)

    def eye_cmd(self, level):
        """Eye opening 0..1 -> centred wedge from one cathode to the whole ring."""
        level = min(1.0, max(0.0, level))
        return f"wedgec {self.eye} {0.5 + 4.5 * level:.2f} {MAX_RATE}"

    # ---- scenes ----
    def strike(self):
        """Strike and home: HV on, the glow finds K1."""
        self.cmd("light")
        end = time.monotonic() + 13
        while time.monotonic() < end:
            d = self.status()
            if d["power"] != "striking":
                break
            time.sleep(0.1)
        if d["power"] != "lit" or d["valid"] != "1":
            sys.exit(f"did not light and home: {d}")
        time.sleep(1)

    def count(self):
        """Counting: one cathode at a time, then a steady rotation."""
        for _ in range(10):
            self.cmd("move 1")
            time.sleep(0.45)
        self.cmd("rotate 4")
        time.sleep(3)
        self.cmd("stop")

    def spin(self):
        """Spin: ramp to 2000 steps/s and back to where it started."""
        self.cmd("spin 20 2000 1200 20")
        self.wait_idle(15)
        time.sleep(1)

    def pendulum(self):
        """Pendulum: a sine swing about the eye centre."""
        self.cmd(f"moveto {self.eye}")
        self.wait_idle(3)
        self.cmd(f"swing {self.eye} 3 1600")
        time.sleep(6.4)
        self.cmd("stop")

    def scanner(self):
        """Scanner: the glow bounces between two bookends, slowly enough to follow."""
        lo = (self.eye - 3) % 10
        self.cmd(f"wedge {lo} {(lo + 7) % 10} 30")
        time.sleep(6)
        self.cmd(f"wedge {lo} {(lo + 7) % 10} 120")
        time.sleep(3)

    def solid(self):
        """Wedge: a bounce at 2000 steps/s looks like a lit sector; its bookends slide in and out."""
        lo = (self.eye - 3) % 10
        self.cmd(f"wedge {lo} {(lo + 7) % 10} {MAX_RATE}")
        time.sleep(3)
        # bookends slide: the sector narrows to the eye centre and widens again
        self.stream(5, lambda t: f"wedge {(lo + 3 * (1 - math.cos(math.pi * t / 2.5)) / 2) % 10:.2f} "
                                 f"{(lo + 7 - 3 * (1 - math.cos(math.pi * t / 2.5)) / 2) % 10:.2f} {MAX_RATE}")

    def tuning(self):
        """Magic eye, tuning: the dial sweeps past stations and locks on the strongest."""
        stations = [(1.1, 0.55), (2.9, 0.35), (5.0, 1.0)]  # dial position (s), strength

        def level(t):
            dial = min(t, 5.0)  # sweep, then stay on the last station
            s = sum(a * math.exp(-((dial - c) / 0.3) ** 2) for c, a in stations)
            return 0.04 + 0.92 * s + 0.03 * math.sin(37 * t) * (dial < 5.0)

        self.cmd(self.eye_cmd(0))
        time.sleep(0.5)
        self.stream(7.5, lambda t: self.eye_cmd(level(t)))

    def vu(self):
        """Magic eye, level meter: a music-like envelope, fast attack and slow release."""
        state = {"lvl": 0.0, "next": 0.0}
        beat = 60 / 112  # 112 bpm

        def level(t):
            if t >= state["next"]:
                state["lvl"] = max(state["lvl"], self.rng.uniform(0.55, 1.0))
                state["next"] += beat / self.rng.choice((1, 2, 2, 4))
            state["lvl"] *= 0.86
            return state["lvl"] + self.rng.uniform(0, 0.06)

        self.stream(9, lambda t: self.eye_cmd(level(t)))

    def gauge(self):
        """Gauge: a progress bar from K1, filling smoothly with fractional cathodes."""
        self.cmd("gauge 0")
        time.sleep(0.8)
        self.stream(6, lambda t: f"gauge {round(1000 * (1 - math.cos(math.pi * t / 6)) / 2)}")
        time.sleep(1.5)
        self.stream(2, lambda t: f"gauge {round(1000 * (1 - t / 2))}")

    def comet(self):
        """Comet: a short sector orbiting the ring, speeding up."""
        speed = {"pos": 0.0, "last": 0.0}

        def step(t):
            v = 1.5 + 2.5 * t  # cathodes per second
            speed["pos"] += v * (t - speed["last"])
            speed["last"] = t
            a = speed["pos"] % 10
            return f"wedge {a:.2f} {(a + 2.5) % 10:.2f} {MAX_RATE}"

        self.stream(7, step)

    def finale(self):
        """Finale: the whole ring lights, then the eye closes to a single glow and goes dark."""
        self.cmd(self.eye_cmd(1))
        time.sleep(2)
        self.stream(3, lambda t: self.eye_cmd((1 + math.cos(math.pi * t / 3)) / 2))
        self.cmd(self.eye_cmd(0))
        time.sleep(1.5)
        self.cmd("dark")


# Most striking first: most viewers see only the first 30 s (eye, eye, comet by ~0:30).
SCENES = ["strike", "tuning", "vu", "comet", "solid", "gauge", "spin", "scanner", "pendulum", "count",
          "finale"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--scenes", help="comma-separated, in order (default: all); strike is always first")
    ap.add_argument("--list", action="store_true", help="list the scenes and exit")
    ap.add_argument("--countdown", type=int, default=5, help="seconds before HV on, to start recording")
    ap.add_argument("--gap", type=float, default=1.5, help="hold between scenes, s")
    ap.add_argument("--eye-centre", type=int, default=9, choices=range(10), help="default 9, near 12 o'clock")
    ap.add_argument("--seed", type=int, default=7, help="level-meter randomness, for repeatable takes")
    args = ap.parse_args()

    if args.list:
        for name in SCENES:
            print(f"{name:9} {getattr(Show, name).__doc__}")
        return
    names = args.scenes.split(",") if args.scenes else SCENES
    bad = [n for n in names if n not in SCENES]
    if bad:
        sys.exit(f"unknown scene(s) {bad}; --list")
    if names[0] != "strike":
        names = ["strike"] + [n for n in names if n != "strike"]

    with serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser:
        show = Show(ser, args.eye_centre, args.seed)
        try:
            show.cmd("local")
            d = show.status()
            if d["fault"] != "none":
                sys.exit(f"fault latched: {d['fault']}; send 'clear' after checking the board")
            for i in range(args.countdown, 0, -1):
                print(f"HV on in {i}...", flush=True)
                time.sleep(1)
            show.t0 = time.monotonic()
            for n, name in enumerate(names):
                show.stamp(f"{name}: {getattr(Show, name).__doc__}")
                getattr(show, name)()
                if name != "finale" and n < len(names) - 1:
                    show.cmd("stop")
                    time.sleep(args.gap)
            d = show.status()
            show.stamp(f"done; index {d['idx_obs']}/{d['idx_exp']} seen, mismatches {d['mismatch']}, "
                       f"late {d['idx_late']} (first sample {d['late_ndx_raw']})")
        finally:
            try:
                send(ser, "dark")
                send(ser, "remote")
            except SystemExit:
                print("could not confirm dark: check the board", file=sys.stderr)


if __name__ == "__main__":
    main()
