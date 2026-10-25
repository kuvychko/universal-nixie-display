#!/usr/bin/env python3
"""
Host side of the dekatron bring-up firmware (firmware/dekatron-bringup/): one command per call,
so it can be run step by step during Gates 2 and 3.

    uv run --group bench python tools/hv_bringup.py status
    uv run --group bench python tools/hv_bringup.py on 10
    uv run --group bench python tools/hv_bringup.py off
    uv run --group bench python tools/hv_bringup.py log 5 --hz 20 --out characterization/dekatron/<file>.csv
    uv run --group bench python tools/hv_bringup.py discharge
    uv run --group bench python tools/hv_bringup.py guide 1 1
    uv run --group bench python tools/hv_bringup.py step 10 fwd 500 20

Exits non-zero when the firmware answers ERR or reports a FAULT.

SPDX-License-Identifier: MIT
"""

import argparse
import sys
import time

import serial
from serial.tools import list_ports

RP2040_VID = 0x2E8A
DISCHARGE_LIMIT_V = 50.0  # D12: HV below 50 V before anything is touched


def find_port():
    ports = [p.device for p in list_ports.comports() if p.vid == RP2040_VID]
    if len(ports) != 1:
        sys.exit(f"expected one RP2040 serial port, found {ports or 'none'}; use --port")
    return ports[0]


def send(ser, cmd, timeout=2.0):
    """Send one command and return its reply line (plus any FAULT lines that came first)."""
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    lines = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = ser.readline().decode(errors="replace").strip()
        if not raw:
            continue
        lines.append(raw)
        if raw.startswith(("OK", "ERR")):
            return lines
    sys.exit(f"no reply to {cmd!r}: {lines}")


def parse_status(line):
    return dict(f.split("=", 1) for f in line.split()[1:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_on = sub.add_parser("on")
    p_on.add_argument("seconds", type=int)
    sub.add_parser("off")
    sub.add_parser("clear")
    p_guide = sub.add_parser("guide", help="hold a guide on (1) or at rest (0); needs HV on")
    p_guide.add_argument("guide", type=int, choices=(1, 2))
    p_guide.add_argument("on", type=int, choices=(0, 1))
    p_step = sub.add_parser("step", help="step the glow; needs HV on")
    p_step.add_argument("n", type=int)
    p_step.add_argument("dir", choices=("fwd", "rev"))
    p_step.add_argument("phase_us", type=int, help="time between guide transitions")
    p_step.add_argument("hz", type=int, help="steps per second")
    p_log = sub.add_parser("log")
    p_log.add_argument("seconds", type=int)
    p_log.add_argument("--hz", type=int, default=10)
    p_log.add_argument("--out")
    p_dis = sub.add_parser("discharge")
    p_dis.add_argument("--max", type=float, default=60.0, help="give up after this many seconds")
    args = ap.parse_args()

    with serial.Serial(args.port or find_port(), 115200, timeout=0.2) as ser:
        if args.cmd == "log":
            ser.reset_input_buffer()
            ser.write(f"log {args.seconds} {args.hz}\n".encode())
            rows = []
            deadline = time.monotonic() + args.seconds + 3
            while time.monotonic() < deadline:
                raw = ser.readline().decode(errors="replace").strip()
                if raw == "END":
                    break
                if raw.startswith("ERR"):
                    sys.exit(raw)
                if raw.startswith(("OK", "FAULT")):
                    # Messages from the HV loop (timeout, trip) interleave with the data.
                    print(raw, file=sys.stderr)
                elif raw:
                    rows.append(raw)
            text = "\n".join(rows) + "\n"
            if args.out:
                with open(args.out, "w", newline="\n") as f:
                    f.write(text)
                print(f"{len(rows) - 1} rows -> {args.out}")
            else:
                print(text, end="")
            return

        if args.cmd == "discharge":
            # Off first: the timing starts when HV_EN drops.
            for line in send(ser, "off"):
                print(line)
            t0 = time.monotonic()
            while True:
                st = parse_status(send(ser, "status")[-1])
                t = time.monotonic() - t0
                hv = float(st["hv"])
                print(f"{t:5.1f} s  HV_STACK {hv:6.1f} V")
                if hv < DISCHARGE_LIMIT_V:
                    print(f"below {DISCHARGE_LIMIT_V:.0f} V after {t:.1f} s (HV_STACK only; check V_B with the meter)")
                    return
                if t > args.max:
                    sys.exit(f"still {hv:.1f} V after {t:.1f} s")
                time.sleep(0.5)

        cmd = {
            "on": lambda: f"on {args.seconds}",
            "guide": lambda: f"guide {args.guide} {args.on}",
            "step": lambda: f"step {args.n} {args.dir} {args.phase_us} {args.hz}",
        }.get(args.cmd, lambda: args.cmd)()
        lines = send(ser, cmd)
        if args.cmd == "step" and lines[-1].startswith("OK"):
            # Wait for the "OK step done" (or a FAULT / timeout off) that ends the run.
            deadline = time.monotonic() + args.n / args.hz + 3
            while time.monotonic() < deadline:
                raw = ser.readline().decode(errors="replace").strip()
                if raw:
                    lines.append(raw)
                if raw.startswith(("OK step done", "FAULT", "OK timeout")):
                    break
            else:
                lines.append("ERR no 'step done' (HV timed out?)")
        for line in lines:
            print(line)
        if any(l.startswith(("ERR", "FAULT")) for l in lines):
            sys.exit(1)


if __name__ == "__main__":
    main()
