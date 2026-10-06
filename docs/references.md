# References

Sources establish starting points. Public access does not grant a licence: check reuse terms
before copying circuit artwork or code, and record the outcome in the table.

## Design sources

| Source | Used for | Reuse terms |
|---|---|---|
| [nanovolt-divider](https://github.com/kuvychko/nanovolt-divider) | Repo structure, CYD pin map, SCPI parser and UI patterns, host handling | Own project: CERN-OHL-P v2 / MIT |
| [Dekatron shield kit (threeneurons)](https://threeneurons.wordpress.com/arduino/dekatron-shield-kit/) | Reference A101 power/drive/index design (AD01/AD01A: 5 V in, ~140 V boost + tripler). Schematic `ad01_sch.gif`, BOM `ad01_bom.gif`, hook-up table `dek_hk.gif` (local copies in `docs/datasheets/ad01/`) | "M. Moorrees © April 2017"; no licence stated. Used for operating values and topology only; artwork and code are not copied |

## Tube and module data

| Item | Link | Notes |
|---|---|---|
| A101 dekatron | [tube-tester.com](https://www.tube-tester.com/sites/nixie/datdekat/A101/A101.htm) | Data and original drawing links; verify socket pinout against the drawing |
| IN-14 Nixie | [tube-tester.com](https://www.tube-tester.com/sites/nixie/data/in-14/in-14.htm) | |
| Nixie HV module | [Amazon B09D94N3MX](https://www.amazon.com/dp/B09D94N3MX) | Qualify the delivered version |

## Datasheets

Stored locally in `docs/datasheets/` (git-ignored). List each one here with its source URL and
revision as it is used.

| File | Part | Source | Revision |
|---|---|---|---|
| `lm3478.pdf` | LM3478 boost controller | https://www.ti.com/lit/gpn/lm3478 | SNVS085Y, Jan 2026 |
| `lm5156h.pdf` | LM5156H / LM51561H boost controller | https://www.ti.com/lit/gpn/lm5156h | SNVSBV2, Sep 2020 |
| `uc3843.pdf` | UCx84x PWM controllers | https://www.ti.com/lit/ds/symlink/uc3843.pdf | SLUS223H, Oct 2024 |
| `ad01/*.gif` | AD01 dekatron shield schematic, BOM, hook-up | threeneurons (see above) | April 2017 |

Simulation models to fetch for Phase 1B (TI product pages; may need a TI login): **Unencrypted
LM5156-Q1 PSpice Transient Model (rev. H)** from https://www.ti.com/product/LM5156H; for the
alternate, the LM3478 Unencrypted PSpice Transient Model (rev. B).
