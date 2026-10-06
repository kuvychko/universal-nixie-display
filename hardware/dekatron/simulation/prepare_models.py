"""Derive ngspice-compatible copies of the vendor simulation models.

The vendor files in models/vendor/ are git-ignored (no redistribution grant) and are never
edited. This script writes patched copies alongside them, also ignored:

  LM5156-Q1_TRANS.LIB -> LM5156-Q1_TRANS.ngspice.lib
    * `.IC` cards inside subcircuits are commented out: ngspice rejects them (here one names a
      subcircuit pin, which ngspice resolves to a non-existent internal node). All three set
      their node to 0 V at the model's default parameters (COMP = SS*1.5 with SS=0, Qint = VSS,
      RAMP = 0), which the operating point reaches anyway.

Run from this directory:  python prepare_models.py
"""
import io
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
TI = HERE / "models" / "vendor" / "ti"

PATCHES = [
    (TI / "LM5156-Q1_PSPICE_TRANS" / "LM5156-Q1_TRANS.LIB",
     TI / "LM5156-Q1_PSPICE_TRANS" / "LM5156-Q1_TRANS.ngspice.lib"),
]


def patch(text: str) -> tuple[str, int]:
    out, n, depth = [], 0, 0
    for line in text.splitlines():
        card = line.lstrip().lower()
        if card.startswith(".subckt"):
            depth += 1
        elif card.startswith(".ends"):
            depth -= 1
        if depth > 0 and re.match(r"\.ic\b", card):
            out.append("* [ngspice patch] " + line)
            n += 1
        else:
            out.append(line)
    return "\n".join(out) + "\n", n


def main() -> None:
    for src, dst in PATCHES:
        if not src.exists():
            raise SystemExit(f"missing {src}: fetch the vendor models first (see README.md)")
        text = io.open(src, encoding="latin-1").read()
        patched, n = patch(text)
        io.open(dst, "w", encoding="latin-1", newline="\n").write(patched)
        print(f"{dst.name}: {n} .IC card(s) commented out")


if __name__ == "__main__":
    main()
