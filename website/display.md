# The display

The finished instrument: six IN-14 Nixies showing digits, one A101 dekatron showing a moving
glow, a 2.8" touchscreen and a rotary encoder for local control, and a USB serial port for a
computer to send numbers to it.

!!! info "Not built yet"
    This page describes the plan. Features move here from the plan as they are demonstrated on
    the real hardware, with photographs; nothing below is claimed to work yet.

The first planned modes are a clock, a timer and stopwatch, and a demonstration and self-test
mode (digits, decimal points, and the dekatron's glow rotating, swinging like a pendulum and
finding its index). In remote mode a computer, Raspberry Pi or experiment drives the display with
simple text commands over USB.

The touchscreen decides **what** is shown. Two small controller boards, one for the dekatron and
one for the Nixies, decide **how**: they generate the pulses and switching the tubes need, so that
the timing never depends on the user interface. See the
[architecture](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/architecture.md) for the full picture.
