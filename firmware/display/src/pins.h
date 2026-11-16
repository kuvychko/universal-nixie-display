// Pin map for the ESP32-2432S028R ("Cheap Yellow Display"). Sources: docs/hardware.md
// ("Display harness"), the module's V0.1 schematic, and nanovolt-divider's pins.h.
// SPDX-License-Identifier: MIT
#pragma once

namespace pins {

// Main I2C bus, on the module's SPI connector: the module has no free IO22, and IO35 is
// input-only. Pull-ups are on the dekatron board (4.7k to its 3V3); the module has none.
constexpr int I2C_SDA = 27;
constexpr int I2C_SCL = 18;

// microSD slot (VSPI). SCK is IO18, shared with SCL: the card is held deselected.
constexpr int SD_MOSI = 23;
constexpr int SD_CS = 5;

// Not used yet: TFT backlight (held off) and the RGB LED (active low, held off).
constexpr int TFT_BL = 21;
constexpr int LED_R = 4;
constexpr int LED_G = 16;
constexpr int LED_B = 17;

} // namespace pins
