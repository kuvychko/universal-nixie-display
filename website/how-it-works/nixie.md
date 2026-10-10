# How a Nixie shows a digit

**Where are all the other digits when one is glowing?**

An IN-14 Nixie holds ten numeral-shaped cathodes, 0 to 9, stacked one behind another inside a
gas-filled glass tube with a common anode, plus small decimal-point cathodes. The driver
connects one numeral to the return path, and the gas glows in a thin sheath around that numeral's
shape. The others stay where they are, as fine dark wire in front of and behind it; the glow is
bright enough that the eye reads past them. The numeral is not a hot filament: it is a cold
cathode wrapped in glowing gas.

Unlike a [dekatron](dekatron.md), a Nixie stores nothing. The digit is chosen from outside, by a
driver chip, and lasts only as long as that driver keeps selecting it.

| Property | Nixie | Dekatron |
|---|---|---|
| Visible state | Selected numeral shape | Position of the glow |
| Selection | External digit driver | Ordered pulses that pass the discharge between electrodes |
| Role | Displays an externally selected digit | Holds a powered count and moves it up or down |
| Stores a value | No: the driver holds the digit | Yes, while powered: the glow position is the value |

!!! info "Coming in Phase 2"
    An interactive numeral stack (pick a digit and see its layer light, front and side views)
    arrives with the Nixie hardware, once the IN-14's real stack order has been checked against a
    tube.
