# Safety

!!! danger "This project uses dangerous voltages"
    The dekatron runs from about 450 V DC and the Nixies from about 170-180 V DC. A shock at these
    voltages can cause serious injury or death, and capacitors can hold a charge after the power
    is off. If you build, test or copy anything from this project, you do so **entirely at your
    own risk**. Work on it only if you understand high-voltage circuits and know what you are
    doing. Everything here is provided as is, without warranty of any kind.

This site explains how the tubes work; it is not a substitute for experience with high voltage.
The circuits shown are real and were really powered, by someone who knew the risks and took
precautions.

## The bench test

The [bench circuit](how-it-works/dekatron.md#the-circuit-on-the-bench) on the dekatron page is
the most exposed part of the project: open wiring on a perf board, the anode at up to 450 V and
every other wire at 50-106 V, none of them at ground. If you try anything like it:

- **One hand.** While anything is powered, keep one hand away from the circuit, for example in a
  pocket. Press buttons by their insulated caps.
- **Limit the current.** Use a bench supply with an adjustable current limit, set to a few
  milliamps (2-3 mA for this test).
- **Power off to touch.** Make and change connections only with the supply off and its output
  discharged; measure before you touch anything.
- **Rated equipment.** Use meters, probes and leads rated for the voltage. Clip leads on before
  powering up rather than holding probes on live nodes.
- **Not alone, not tired.** Work with someone nearby, and stop when you are not concentrating.

## The finished display

On the boards, discharge paths, clearances and probe ratings are design requirements, not
afterthoughts. Printed plastic parts keep fingers away; they are not high-voltage insulation.
The detailed precautions for each step are in the
[bring-up procedures](https://github.com/kuvychko/universal-nixie-display/blob/main/docs/bringup.md).
