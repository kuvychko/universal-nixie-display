#!/usr/bin/env python3
"""
Dekatron demo loop for filming, driven through the bring-up firmware (firmware/dekatron-bringup/).
It switches HV on itself: run it only with the board set up and hands clear.

    uv run --group bench python tools/dekatron_demo.py              # loop until Ctrl+C
    uv run --group bench python tools/dekatron_demo.py --loops 3

One loop (~18 s): home to K1, hold, slow clockwise, slow anticlockwise, faster, very fast,
oscillate, back to K1. HV is refreshed with a short timeout every loop, so it drops on its own
within HV_REFRESH_S if the script dies; Ctrl+C or any error switches it off at once.

SPDX-License-Identifier: MIT
"""

import argparse
import sys
import time

import serial

from hv_bringup import find_port, parse_status, send

PHASE_US = 500  # guide phase used for all of Gate 3's stepping runs
CATHODES = 10  # one index hit per 10 steps at Gate 3
NDX_HIGH_V = 2.0  # RP2040 V_IH min, as in the firmware
HV_REFRESH_S = 30


class Demo:
    def __init__(self, ser):
        self.ser = ser
        self.pos = None  # steps clockwise from K1, mod CATHODES; None until homed

    def cmd(self, line):
        reply = send(self.ser, line)
        if reply[-1].startswith("ERR") or any(l.startswith("FAULT") for l in reply):
            sys.exit(f"{line!r}: {reply}")
        return reply[-1]

    def step(self, n, fwd=True, hz=10):
        if n <= 0:
            return
        self.cmd(f"step {n} {'fwd' if fwd else 'rev'} {PHASE_US} {hz}")
        deadline = time.monotonic() + n / hz + 3
        while time.monotonic() < deadline:
            raw = self.ser.readline().decode(errors="replace").strip()
            if raw.startswith("OK step done"):
                if self.pos is not None:
                    self.pos = (self.pos + (n if fwd else -n)) % CATHODES
                return
            if raw.startswith(("FAULT", "OK timeout")):
                sys.exit(raw)
        sys.exit("no 'step done'")

    def at_k1(self):
        return float(parse_status(self.cmd("status"))["ndx"]) >= NDX_HIGH_V

    def home(self):
        """Step to K1: by count when the position is known and confirmed, else one step at a time."""
        if self.pos is not None:
            back = self.pos if self.pos <= CATHODES // 2 else self.pos - CATHODES
            self.step(abs(back), fwd=back < 0, hz=20)
            time.sleep(0.02)
            if self.at_k1():
                self.pos = 0
                return
            print("lost count, re-homing", file=sys.stderr)
        self.pos = None
        for _ in range(CATHODES + 2):
            time.sleep(0.02)
            if self.at_k1():
                self.pos = 0
                return
            self.step(1, hz=20)
        sys.exit("no index after a full turn")

    def hold(self, s):
        time.sleep(s)

    def oscillate(self, swings, amplitude, hz):
        self.step(amplitude // 2, fwd=False, hz=hz)
        for _ in range(swings):
            self.step(amplitude, fwd=True, hz=hz)
            self.step(amplitude, fwd=False, hz=hz)
        self.step(amplitude // 2, fwd=True, hz=hz)

    def loop(self):
        self.cmd(f"on {HV_REFRESH_S}")
        self.home()
        self.hold(3.0)  # stationary on K1
        self.step(15, fwd=True, hz=5)  # slow clockwise, 1.5 turns in 3 s
        self.hold(0.5)
        self.step(15, fwd=False, hz=5)  # slow anticlockwise
        self.hold(0.5)
        for hz, n in ((10, 10), (20, 20), (40, 40)):  # speeding up, 1 s each
            self.step(n, fwd=True, hz=hz)
        self.step(600, fwd=True, hz=200)  # very fast: 20 turns/s for 3 s
        self.hold(0.5)
        self.oscillate(swings=6, amplitude=4, hz=20)  # +-2 cathodes, ~2.5 s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--loops", type=int, default=0, help="0 = until Ctrl+C")
    args = ap.parse_args()

    with serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser:
        demo = Demo(ser)
        try:
            n = 0
            while args.loops == 0 or n < args.loops:
                t0 = time.monotonic()
                demo.loop()
                n += 1
                print(f"loop {n}: {time.monotonic() - t0:.1f} s")
        except KeyboardInterrupt:
            pass
        finally:
            print(send(ser, "off")[-1])


if __name__ == "__main__":
    main()
