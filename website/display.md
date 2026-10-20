# The display

The finished instrument: six IN-14 Nixies showing digits, one A101 dekatron showing a moving
glow, a 2.8" touchscreen and a rotary encoder for local control, and a USB serial port for a
computer to send numbers to it.

!!! info "Not built yet"
    This page describes the plan. Features move here from the plan as they are demonstrated on
    the real hardware, with photographs; nothing below is claimed to work yet.

![Proposed front view, not to scale: on top of the enclosure, six IN-14 Nixies in a row and, at the right end of the row, the A101 dekatron held horizontally, end-on; on the front, the touchscreen at the left and the rotary encoder to its right; the enclosure on a tilt base](assets/display-layout.svg){ .figure-plate }

*The proposed arrangement, not to scale. The enclosure is not designed yet, so positions and
proportions will change.*

The first planned modes are a clock, a timer and stopwatch, and a demonstration and self-test
mode (digits, decimal points, and the dekatron's glow rotating, swinging like a pendulum and
finding its index). In remote mode a computer, Raspberry Pi or experiment drives the display with
simple text commands over USB.

The touchscreen decides **what** is shown. Two small controller boards, one for the dekatron and
one for the Nixies, decide **how**: they generate the pulses and switching the tubes need, so that
the timing never depends on the user interface. See the
[architecture](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/architecture.md) for the full picture.

## What "universal" means

The Nixies show a number; the dekatron shows motion or a count; the touchscreen carries what the
tubes cannot, such as a label, units, a minus sign or a small history plot. Any program that can
write to a serial port can use all three. Some of the uses the plan has in mind:

- **An experiment's readout.** A script reads an instrument and sends the value; the Nixies show
  it, the touchscreen its name and units.
- **A computer-controlled counter.** Events counted on a computer (a Geiger counter's clicks, say)
  step the dekatron one place each, while the Nixies keep the running total.
- **Progress you can watch.** A long computation or a timer drives the dekatron's glow round the
  ring as it advances, with the time left on the Nixies.

These are plans, not demonstrations: they will appear here with photographs as they work.
