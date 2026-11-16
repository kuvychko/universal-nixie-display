// Display firmware (ESP32-2432S028R): the instrument's I2C master. Spec: ../README.md.
// Version 0.1 is the I2C path only: the dekatron client, status polling and the SCPI host
// interface over USB serial. No UI yet; the backlight and RGB LED are held off.
// SPDX-License-Identifier: MIT

#include <Arduino.h>

#include "dekatron_client.h"
#include "pins.h"
#include "scpi.h"

namespace {

char g_line[256];
size_t g_lineLen = 0;
bool g_lineOverflow = false;

void pollSerial()
{
    while (Serial.available()) {
        const char ch = Serial.read();
        if (ch == '\n' || ch == '\r') {
            if (g_lineOverflow) {
                scpi::pushError(-112, "Program mnemonic too long;line over 255 chars");
            } else if (g_lineLen) {
                g_line[g_lineLen] = '\0';
                scpi::execute(g_line, Serial);
            }
            g_lineLen = 0;
            g_lineOverflow = false;
        } else if (g_lineLen < sizeof(g_line) - 1) {
            g_line[g_lineLen++] = ch;
        } else {
            g_lineOverflow = true;
        }
    }
}

} // namespace

void setup()
{
    pinMode(pins::TFT_BL, OUTPUT);
    digitalWrite(pins::TFT_BL, LOW);
    for (int p : {pins::LED_R, pins::LED_G, pins::LED_B}) {
        pinMode(p, OUTPUT);
        digitalWrite(p, HIGH); // active low: off
    }
    Serial.begin(115200);
    dekc::begin();
    Serial.printf("# universal-nixie-display %s\n# ready\n", DISP_FW_VERSION);
}

void loop()
{
    pollSerial();
    dekc::poll();
}
