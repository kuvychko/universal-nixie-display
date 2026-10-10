# Universal Nixie Display

Six IN-14 Nixie tubes in a row, one A101 dekatron and a small touchscreen, in a desktop
enclosure. It is a clock, a timer and a toy on its own, and a numeric display for a computer or an
experiment over USB.

**How can a glow in a gas-filled tube display a number, or remember and count one?**

The two kinds of tube answer that question in opposite ways. A **Nixie** is stateless: it lights
whichever numeral its driver selects, and forgets it the moment the drive changes. A **dekatron**
is stateful: a spot of glow sits on one of ten cathodes, and pulses move it one place round the
ring, forwards or backwards. The position of the glow *is* the number, and the tube holds it by
itself between pulses. One tube shows a number; the other remembers one.

## Two ways in

**[Explore the display](display.md).** What the finished instrument does, its controls and its
modes, as they become real.

**[Understand the tubes](how-it-works/dekatron.md).** Start with the dekatron: the bench circuit
that drives it, an interactive ring you can step through, why only one glow can exist, how it
moves and how fast, why the tube is a memory, and a short history. Then
[the Nixie](how-it-works/nixie.md).

!!! info "Status"
    The display is under construction. The dekatron controller and power-supply boards are
    designed and ordered, and the A101 dekatron has been bench-tested: it strikes, holds its glow
    and steps reliably in both directions. Photographs and video of the working tube will appear
    here. The Nixie side comes next. See [Build and investigate](build.md).
