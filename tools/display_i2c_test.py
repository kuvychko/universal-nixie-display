#!/usr/bin/env python3
"""
I2C path bench test (bring-up step 4): the CYD (firmware/display/) drives the dekatron controller
(firmware/dekatron/, 0.2) over the DISP harness, through the CYD's SCPI host interface. The
controller's own USB console is used alongside, for ownership and the inject bench hooks.

It switches HV on itself: run it only with the board set up and hands clear. Ctrl+C or any error
switches HV off at once, over both paths.

    uv run --group bench python tools/display_i2c_test.py                     # all tests, 10 min soak
    uv run --group bench python tools/display_i2c_test.py --tests errors,master_loss
    uv run --group bench python tools/display_i2c_test.py --soak 1 --cyd COM10 --dek COM9

Tests:
  identity     *IDN?, protocol 2, firmware 0.2, owner i2c
  errors       each error code over I2C: bad_op, bad_len, range, state, not_owner (console 'local'),
               and the console-only INJECT refused over I2C
  motion       light and home, moves, step queue, rotate, wedge, streamed eye and gauge, all confirmed
  master_loss  polling paused 4 s: stays lit; paused 6.5 s: dark, master_loss; LIGHT clears it
  recovery     a step dropped on the console ('inject drop'): skips +1 and last_skip in the I2C status,
               the wedge resumes, nothing latched
  soak         the eye streamed at 25 Hz for --soak minutes, every update confirmed

One row per test is appended to characterization/dekatron/<date>_i2c_path.csv.

SPDX-License-Identifier: MIT
"""

import argparse
import csv
import datetime
import math
import os
import pathlib
import sys
import time

import serial
from serial.tools import list_ports

from hv_bringup import RP2040_VID, find_port, parse_status
from hv_bringup import send as dek_send

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ["identity", "errors", "motion", "master_loss", "recovery", "soak"]
UPDATE_HZ = 25


def find_cyd():
    ports = [p.device for p in list_ports.comports() if p.vid and p.vid != RP2040_VID]
    if len(ports) != 1:
        sys.exit(f"expected one CYD serial port, found {ports or 'none'}; use --cyd")
    return ports[0]


class Cyd:
    """SCPI over the CYD's USB serial port (opened without toggling the auto-reset lines)."""

    def __init__(self, port):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 115200
        self.ser.timeout = 0.5
        # As nanovolt-divider tools/scpi.py: on Windows released/released does not reset the ESP32.
        asserted = os.name == "posix"
        self.ser.dtr = asserted
        self.ser.rts = asserted
        self.ser.open()
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def query(self, cmd, timeout=2.0):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = self.ser.readline().decode(errors="replace").strip()
            if line and not line.startswith("#"):
                return line
        raise TimeoutError(f"no reply to {cmd!r}")

    def do(self, cmd):
        """Run a command; return '' if it was accepted, else the first queued error."""
        r = self.query(f"{cmd};SYST:ERR?")
        if r.startswith("0,"):
            return ""
        while not self.query("SYST:ERR?").startswith("0,"):
            pass
        return r

    def must(self, cmd):
        e = self.do(cmd)
        if e:
            raise RuntimeError(f"{cmd!r}: {e}")

    def stat(self):
        return dict(f.split("=", 1) for f in self.query("DEK:STAT?").split())

    def i2c(self):
        return {k: int(v) for k, v in (f.split("=", 1) for f in self.query("DIAG:I2C?").split())}


class Bench:
    def __init__(self, cyd, dek):
        self.cyd = cyd
        self.dek = dek

    def console(self, line):
        r = dek_send(self.dek, line)[-1]
        if not r.startswith("OK"):
            raise RuntimeError(f"controller console {line!r}: {r}")
        return r

    def light(self):
        d = self.cyd.stat()
        if d["power"] == "lit" and d["valid"] == "1":
            return d
        self.cyd.must("DEK:LIGHT")
        end = time.monotonic() + 13
        while time.monotonic() < end:
            d = self.cyd.stat()
            if d["power"] == "lit" and d["valid"] == "1":
                return d
            time.sleep(0.1)
        raise RuntimeError(f"did not light and home: {d}")

    def settle(self, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            d = self.cyd.stat()
            if d["mode"] == "idle":
                return d
            time.sleep(0.05)
        return d

    def stream(self, seconds, fn):
        """Send fn(t) at UPDATE_HZ; returns (updates, errors)."""
        start, n, errors = time.monotonic(), 0, []
        while (t := time.monotonic() - start) < seconds:
            e = self.cyd.do(fn(t))
            if e:
                errors.append(e)
            n += 1
            delay = start + n / UPDATE_HZ - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        return n, errors

    # ---- tests: each returns (passed, details) ----
    def identity(self, args):
        idn = self.cyd.query("*IDN?")
        d = self.cyd.stat()
        ok = idn.startswith("UND,") and d["protocol"] == "2" and d["fw"] == "0.2" and d["owner"] == "i2c"
        return ok, f"{idn}; controller protocol {d['protocol']} fw {d['fw']} owner {d['owner']} boots {d['boots']}"

    def errors(self, args):
        self.cyd.must("DEK:DARK")
        cases = [("0100", "ok"),          # PING
                 ("FF00", "bad_op"),      # unknown op
                 ("050100", "bad_len"),   # MOVE_TO with one payload byte
                 ("05020C00", "range"),   # MOVE_TO cathode 12
                 ("0D06F4012003D007", "state"),  # WEDGE 5.00-8.00 while dark
                 ("820101", "bad_op")]    # INJECT is console-only
        got = [(f, want, self.cyd.query(f'DIAG:DEK:RAW? "{f}"')) for f, want in cases]
        self.console("local")
        try:
            got.append(("0100 (console local)", "ok", self.cyd.query('DIAG:DEK:RAW? "0100"')))
            got.append(("0400 (console local)", "not_owner", self.cyd.query('DIAG:DEK:RAW? "0400"')))
        finally:
            self.console("remote")
        bad = [f"{f}: {r} (want {w})" for f, w, r in got if r != w]
        return not bad, "; ".join(bad) or f"{len(got)} frames, every result as expected"

    def motion(self, args):
        errs = []
        m0 = int(self.light()["mismatch"])
        for cmd, want in [("DEK:POS 4", 4), ("DEK:POS 7,REV", 7), ("DEK:STEP -3", 4), ("DEK:STEP 12", 6),
                          ("DEK:POS 0,FWD", 0)]:
            self.cyd.must(cmd)
            d = self.settle()
            if d["pos"] != str(want):
                errs.append(f"{cmd}: pos {d['pos']}, want {want}")
        self.cyd.must("DEK:ROT 200")
        time.sleep(2)
        self.cyd.must("DEK:STOP")
        self.cyd.must("DEK:WEDGE 2,6")
        time.sleep(2)
        n1, e1 = self.stream(8, lambda t: f"DEK:EYE 9,{0.5 + 4.5 * (1 - math.cos(math.pi * t / 2)) / 2:.2f}")
        n2, e2 = self.stream(5, lambda t: f"DEK:GAUGE {10 * (1 - math.cos(math.pi * t / 5)) / 2:.2f}")
        self.cyd.must("DEK:STOP")
        errs += e1 + e2
        d = self.cyd.stat()
        ok = not errs and int(d["mismatch"]) == m0 and d["fault"] == "none" and d["power"] == "lit"
        return ok, (f"5 moves, rotate, wedge, {n1} eye + {n2} gauge updates; errors {len(errs)}"
                    + (f": {errs[:3]}" if errs else "") + f"; index {d['idx_obs']}/{d['idx_exp']}, "
                    f"mismatches {d['mismatch']}")

    def master_loss(self, args):
        self.light()
        self.cyd.must("DIAG:DEK:POLL OFF")
        try:
            time.sleep(4)
        finally:
            self.cyd.must("DIAG:DEK:POLL ON")
        short = self.cyd.stat()
        self.cyd.must("DIAG:DEK:POLL OFF")
        t0 = time.monotonic()
        try:
            time.sleep(6.5)
        finally:
            self.cyd.must("DIAG:DEK:POLL ON")
        long = self.cyd.stat()
        self.light()
        after = self.cyd.stat()
        ok = (short["power"] == "lit" and long["power"] == "dark" and long["dark_reason"] == "master_loss"
              and long["master_loss"] == "1" and after["master_loss"] == "0" and after["power"] == "lit")
        return ok, (f"4 s silent: {short['power']}; {time.monotonic() - t0:.1f} s silent: {long['power']} "
                    f"({long['dark_reason']}, master_loss {long['master_loss']}); relit: master_loss "
                    f"{after['master_loss']}")

    def recovery(self, args):
        self.light()
        self.cyd.must("DEK:WEDGE 5,8")
        time.sleep(2)
        before = self.cyd.stat()
        self.console("inject drop")
        t0 = time.monotonic()
        d = before
        while time.monotonic() - t0 < 70:
            d = self.cyd.stat()
            if d["skips"] != before["skips"] and d["recovering"] == "0":
                break
            time.sleep(0.2)
        time.sleep(0.5)
        d = self.cyd.stat()
        ok = (int(d["skips"]) == int(before["skips"]) + 1 and d["last_skip"] in ("1", "-1")
              and d["mode"] == "wedge" and d["fault"] == "none" and d["power"] == "lit")
        self.cyd.must("DEK:STOP")
        return ok, (f"seen over I2C after {time.monotonic() - t0:.1f} s: skips {before['skips']} -> "
                    f"{d['skips']}, last_skip {d['last_skip']}, mode {d['mode']}, fault {d['fault']}")

    def soak(self, args):
        self.light()
        b_i2c, b = self.cyd.i2c(), self.cyd.stat()
        n, errs = self.stream(args.soak * 60,
                              lambda t: f"DEK:EYE 5,{0.5 + 3.9 * (1 - math.cos(2 * math.pi * t / 4)) / 2:.2f}")
        self.cyd.must("DEK:STOP")
        a_i2c, a = self.cyd.i2c(), self.cyd.stat()
        delta = {k: a_i2c[k] - b_i2c[k] for k in a_i2c if k != "poll"}
        bus = sum(delta[k] for k in ("read_err", "write_err", "bad_status", "confirm_timeout"))
        mism = int(a["mismatch"]) - int(b["mismatch"])
        ok = not errs and bus == 0 and mism == 0 and a["power"] == "lit"
        return ok, (f"{n} eye updates in {args.soak:g} min, errors {len(errs)}; I2C {delta['reads']} reads, "
                    f"{delta['writes']} writes, bus errors {bus}; mismatches {mism}, trips "
                    f"{int(a['trips']) - int(b['trips'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cyd", help="CYD serial port (default: the one non-RP2040 port)")
    ap.add_argument("--dek", help="dekatron controller console port")
    ap.add_argument("--tests", help=f"comma-separated, in order (default: all): {','.join(TESTS)}")
    ap.add_argument("--soak", type=float, default=10, help="soak length, min")
    ap.add_argument("--csv", type=pathlib.Path)
    args = ap.parse_args()

    names = args.tests.split(",") if args.tests else TESTS
    bad = [n for n in names if n not in TESTS]
    if bad:
        sys.exit(f"unknown test(s) {bad}")
    out = args.csv or ROOT / "characterization/dekatron" / f"{datetime.date.today()}_i2c_path.csv"
    new = not out.exists()

    cyd = Cyd(args.cyd or find_cyd())
    with serial.Serial(args.dek or find_port(), 115200, timeout=0.2) as dek, \
            out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "test", "passed", "details"], lineterminator="\n")
        if new:
            w.writeheader()
        b = Bench(cyd, dek)
        failed = 0
        try:
            d = parse_status(b.console("status"))
            if d["fault"] != "none":
                sys.exit(f"fault latched: {d['fault']}; send 'clear' after checking the board")
            if d["owner"] != "i2c":
                b.console("remote")
            for name in names:
                print(f"{datetime.datetime.now():%H:%M:%S}  {name} ...", flush=True)
                try:
                    ok, details = getattr(b, name)(args)
                except (RuntimeError, TimeoutError) as e:
                    ok, details = False, f"aborted: {e}"
                failed += not ok
                print(f"    {'PASS' if ok else 'FAIL'}  {details}", flush=True)
                w.writerow({"time": datetime.datetime.now().isoformat(timespec="seconds"), "test": name,
                            "passed": int(ok), "details": details})
                f.flush()
        finally:
            for fn in (lambda: cyd.query("DIAG:DEK:POLL ON;DEK:DARK;SYST:ERR?"), lambda: dek_send(dek, "dark"),
                       lambda: dek_send(dek, "remote")):
                try:
                    fn()
                except (SystemExit, TimeoutError, serial.SerialException):
                    print("could not confirm dark on one path: check the board", file=sys.stderr)
            cyd.close()
    print(f"{len(names) - failed}/{len(names)} passed; rows appended to {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
