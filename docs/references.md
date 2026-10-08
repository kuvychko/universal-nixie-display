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
| `mmbta42.pdf` | MMBTA42 NPN 300 V (guide drivers) | https://assets.nexperia.com/documents/data-sheet/MMBTA42.pdf | 12 Oct 2023 |
| `mmbta92.pdf` | MMBTA92 PNP 300 V (index sense) | https://assets.nexperia.com/documents/data-sheet/MMBTA92.pdf | 30 Jun 2023 |
| `bsp130.pdf` | Nexperia BSP130, 300 V logic-level MOSFET (considered, rejected for current rating) | https://assets.nexperia.com/documents/data-sheet/BSP130.pdf | — |
| `aod5n40.pdf` | AOS AOD5N40, 400 V MOSFET (HV boost switch until 2026-10-07; not stocked by Mouser) | https://www.aosmd.com/res/datasheets/AOD5N40.pdf | — |
| (not stored) | Infineon IPD50R1K4CE, 500 V CoolMOS CE (HV boost switch). Official PDF not yet fetched; figures from distributor listings | https://www.infineon.com/part/IPD50R1K4CE | — |
| `ipd50p04p4l-11.pdf` | Infineon IPD50P04P4L-11, −40 V P-channel (reverse-polarity protection) | https://www.infineon.com/assets/row/public/documents/10/49/infineon-ipd50p04p4l-11-datasheet-en.pdf | Rev. 1.1, 2019-07-04 |
| `yageo_hhv.pdf` | Yageo HHV metal glaze high-voltage resistors (HHV-25 1600 V, HHV-50 3500 V; replaced Vishay HVR25 / HVR37) | https://yageogroup.com/content/datasheet/asset/file/YAGEO-HHV_DATASHEET | V.3, 2024-04-03 |
| `tps54202.pdf` | TPS54202 2 A buck (reference design Figure 7-1) | https://www.ti.com/lit/gpn/tps54202 | SLVSD26C, Feb 2026 |
| `rp2040.pdf` | RP2040 datasheet (pad reset state Table 341; IO characteristics Table 625) | https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf | — |
| (not stored) | RP2040-Zero pinout figure (top view) | https://www.waveshare.com/w/upload/1/1f/900px-RP2040-Zero-details-7.jpg | — |
| (not stored) | RP2040-Zero STEP model (castellation geometry) | https://files.waveshare.com/upload/f/f7/RP2040_Zero_stp.zip | 2022-01-08 |
| `mmsz52xx_yangjie.pdf` | MMSZ5221B-5267B zeners (Yangjie): I_ZT 2 mA, Z_ZT, knee I_ZK 0.5 mA | https://static.chipdip.ru/lib/152/DOC001152772.pdf | S-S188 rev 1.0 |
| `rp2040_zero_sch.pdf` | Waveshare RP2040-Zero schematic | https://www.waveshare.com/w/upload/4/4c/RP2040_Zero.pdf | — |
| `cyd/ESP32-2432S028-MCU.jpg`, `-LCM.jpg` | ESP32-2432S028 schematic (vendor original V0.1, 2022-07-15) | https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display (OriginalDocumentation/5-Schematic) | V0.1 |
| `ad01/*.gif` | AD01 dekatron shield schematic, BOM, hook-up | threeneurons (see above) | April 2017 |

Simulation models to fetch for Phase 1B (TI product pages; may need a TI login): **Unencrypted
LM5156-Q1 PSpice Transient Model (rev. H)** from https://www.ti.com/product/LM5156H; for the
alternate, the LM3478 Unencrypted PSpice Transient Model (rev. B).
