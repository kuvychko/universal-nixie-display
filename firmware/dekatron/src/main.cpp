// Dekatron controller firmware. Spec: ../README.md; I2C contract: docs/i2c_protocol.md.
// Core 0 (this file): boot counter, I2C target, USB console, LED. It never touches HV_EN, the
// guides or the ADC: core 1 (controller.cpp) owns them and runs every tube sequence.
// SPDX-License-Identifier: MIT

#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <EEPROM.h>
#include <Wire.h>
#include <hardware/watchdog.h>

#include "board.h"
#include "controller.h"

using namespace dek;

static Adafruit_NeoPixel led(1, pin::LED, NEO_GRB + NEO_KHZ800);
static volatile bool ready = false;
static uint16_t bootCount;
static bool watchdogReset;

static char line[80];
static size_t lineLen;

struct Persist {
    uint32_t magic;
    uint16_t boots;
};
static const uint32_t PERSIST_MAGIC = 0x44454B31; // "DEK1"

static void countBoot()
{
    EEPROM.begin(256);
    Persist p;
    EEPROM.get(0, p);
    if (p.magic != PERSIST_MAGIC) {
        p = {PERSIST_MAGIC, 0};
    }
    p.boots++;
    EEPROM.put(0, p);
    EEPROM.commit();
    bootCount = p.boots;
}

// ---- I2C target (IRQ context: frame and queue only) ----
static void onI2cReceive(int n)
{
    uint8_t buf[16];
    int k = 0;
    while (Wire1.available()) {
        int b = Wire1.read();
        if (k < (int)sizeof(buf)) {
            buf[k] = (uint8_t)b;
        }
        k++;
    }
    g_lastI2cMs = millis();
    if (k == 0) {
        return; // address probe
    }
    controllerPost(frameCommand(SRC_I2C, buf, k > (int)sizeof(buf) ? (int)sizeof(buf) + 1 : k));
}

static void onI2cRequest()
{
    g_lastI2cMs = millis();
    Status s;
    controllerSnapshot(&s, nullptr);
    Wire1.write((const uint8_t *)&s, sizeof(s));
}

// ---- USB console ----
static const char *errName(uint8_t e)
{
    static const char *names[] = {"ok", "bad_op", "bad_len", "range", "state", "not_owner", "queue_full", "vin"};
    return e < sizeof(names) / sizeof(names[0]) ? names[e] : "?";
}

static const char *faultName(uint8_t f)
{
    static const char *names[] = {"none", "vin", "en_low", "hv_low", "strike_timeout", "index_timeout"};
    return f < sizeof(names) / sizeof(names[0]) ? names[f] : "?";
}

static void printStatus()
{
    Status s;
    Diag d;
    controllerSnapshot(&s, &d);
    static const char *pw[] = {"dark", "striking", "lit"};
    static const char *dr[] = {"boot", "command", "fault", "master_loss", "hold_limit"};
    static const char *md[] = {"idle", "home", "queue", "rotate", "swing", "bounce", "spin", "wedge", "exercise"};
    Serial.printf("OK t_ms=%lu boots=%u fw=%u.%u owner=%s power=%s fault=%s dark_reason=%s pos=%u valid=%d "
                  "mode=%s queue=%d hv=%.1f vin=%.1f rtn=%.1f pgood=%d hv_en=%d ndx_raw=%u idx_exp=%u idx_obs=%u "
                  "home_fail=%u mismatch=%u dwell_ms=%lu rate=%.1f slow_run_s=%lu exercise_due=%d master_loss=%d "
                  "seq=%u err=%s wdt_reset=%d pio=%u idx_late=%u late_ndx_raw=%u miss_ndx_raw=%u miss_expected=%d miss_mode=%d rehome_offset=%d\n",
                  (unsigned long)s.uptime_ms, s.boot_count, s.firmware >> 8, s.firmware & 0xFF,
                  s.owner == OWN_USB ? "usb" : "i2c", s.power < 3 ? pw[s.power] : "?", faultName(s.fault),
                  s.dark_reason < 5 ? dr[s.dark_reason] : "?", s.position, (s.flags & FL_POSITION_VALID) ? 1 : 0,
                  s.mode < 9 ? md[s.mode] : "?", s.queue, s.hv_dv / 10.0f, s.vin_dv / 10.0f, s.rtn_dv / 10.0f,
                  (s.flags & FL_PGOOD) ? 1 : 0, (s.flags & FL_HV_EN) ? 1 : 0, d.ndx_raw, s.idx_expected,
                  s.idx_observed, s.home_failures, s.idx_mismatches, (unsigned long)s.dwell_ms, s.rate_dsps / 10.0f,
                  (unsigned long)s.slow_run_s, (s.flags & FL_EXERCISE_DUE) ? 1 : 0,
                  (s.flags & FL_MASTER_LOSS) ? 1 : 0, s.cmd_seq, errName(s.last_error),
                  (s.flags & FL_WATCHDOG_RESET) ? 1 : 0, d.pio_ok, d.idx_late, d.late_ndx_raw, d.miss_ndx_raw, d.miss_expected, d.miss_mode,
                  d.rehome_offset);
}

static void put16(uint8_t *p, uint32_t v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; }
static void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }

static void send(const uint8_t *frame, int n)
{
    Reply r;
    while (controllerReply(&r)) {
    }
    if (!controllerPost(frameCommand(SRC_USB, frame, n))) {
        Serial.println("ERR busy");
        return;
    }
    uint32_t t0 = millis();
    while ((uint32_t)(millis() - t0) < 200) {
        if (controllerReply(&r)) {
            if (r.err == E_OK) {
                Serial.println("OK");
            } else {
                Serial.printf("ERR %s\n", errName(r.err));
            }
            return;
        }
        g_core0BeatMs = millis();
    }
    Serial.println("ERR no reply");
}

static const char *HELP =
    "OK status | local | remote | ping | light | dark | home | moveto <k> [fwd|rev] | move <n> | "
    "rotate <steps/s> | stop | motion <move_rate> <accel> | swing <centre> <amp> <period_ms> | "
    "bounce <a> <b> <rate> | spin <start> <end> <accel> <turns> | wedge <a> <b> <rate> | "
    "wedgec <centre> <half_width> <rate> | "
    "gauge <0-1000> | exercise | clear | bootsel | help";

static void handleLine(char *cmd)
{
    char *argv[6] = {};
    int argc = 0;
    for (char *t = strtok(cmd, " "); t && argc < 6; t = strtok(nullptr, " ")) {
        argv[argc++] = t;
    }
    if (argc == 0) {
        return;
    }
    const char *c = argv[0];
    auto num = [&](int i) { return i < argc ? strtol(argv[i], nullptr, 10) : 0L; };
    // Cathodes with decimals as 0.01 cathode; out-of-range values stay out of range for the controller.
    auto centi = [&](int i) { return i < argc ? (uint16_t)lroundf(fminf(fmaxf(strtof(argv[i], nullptr) * 100, 0), 65535)) : 0; };
    uint8_t f[10] = {};
    auto simple = [&](uint8_t op) { f[0] = op; f[1] = 0; send(f, 2); };

    if (!strcmp(c, "status")) {
        printStatus();
    } else if (!strcmp(c, "help")) {
        Serial.println(HELP);
    } else if (!strcmp(c, "local")) {
        simple(OP_OWNER_LOCAL);
    } else if (!strcmp(c, "remote")) {
        simple(OP_OWNER_REMOTE);
    } else if (!strcmp(c, "ping")) {
        simple(OP_PING);
    } else if (!strcmp(c, "light")) {
        simple(OP_LIGHT);
    } else if (!strcmp(c, "dark")) {
        simple(OP_DARK);
    } else if (!strcmp(c, "home")) {
        simple(OP_HOME);
    } else if (!strcmp(c, "stop")) {
        simple(OP_STOP);
    } else if (!strcmp(c, "exercise")) {
        simple(OP_EXERCISE);
    } else if (!strcmp(c, "clear")) {
        simple(OP_CLEAR_FAULT);
    } else if (!strcmp(c, "bootsel")) {
        simple(OP_BOOTSEL);
    } else if (!strcmp(c, "moveto") && argc >= 2) {
        uint8_t dir = argc < 3 ? 0 : !strcmp(argv[2], "fwd") ? 1 : !strcmp(argv[2], "rev") ? 2 : 3;
        f[0] = OP_MOVE_TO; f[1] = 2; f[2] = (uint8_t)num(1); f[3] = dir;
        send(f, 4);
    } else if (!strcmp(c, "move") && argc >= 2) {
        long n = num(1);
        if (n > 32767 || n < -32768) {
            Serial.println("ERR range");
            return;
        }
        f[0] = OP_MOVE_RELATIVE; f[1] = 2; put16(f + 2, (uint16_t)(int16_t)n);
        send(f, 4);
    } else if (!strcmp(c, "rotate") && argc >= 2) {
        f[0] = OP_ROTATE; f[1] = 4; put32(f + 2, (uint32_t)(int32_t)lroundf(strtof(argv[1], nullptr) * 100));
        send(f, 6);
    } else if (!strcmp(c, "motion") && argc >= 3) {
        f[0] = OP_SET_MOTION; f[1] = 4; put16(f + 2, num(1)); put16(f + 4, num(2));
        send(f, 6);
    } else if (!strcmp(c, "swing") && argc >= 4) {
        f[0] = OP_SWING; f[1] = 4; f[2] = num(1); f[3] = num(2); put16(f + 4, num(3));
        send(f, 6);
    } else if (!strcmp(c, "bounce") && argc >= 4) {
        f[0] = OP_BOUNCE; f[1] = 4; f[2] = num(1); f[3] = num(2); put16(f + 4, num(3));
        send(f, 6);
    } else if (!strcmp(c, "spin") && argc >= 5) {
        f[0] = OP_SPIN; f[1] = 7; put16(f + 2, num(1)); put16(f + 4, num(2)); put16(f + 6, num(3)); f[8] = num(4);
        send(f, 9);
    } else if (!strcmp(c, "wedge") && argc >= 4) {
        // Bookends in cathodes, decimals allowed: "wedge 2.3 5.7 2000"
        f[0] = OP_WEDGE; f[1] = 6; put16(f + 2, centi(1)); put16(f + 4, centi(2)); put16(f + 6, num(3));
        send(f, 8);
    } else if (!strcmp(c, "wedgec") && argc >= 4) {
        f[0] = OP_WEDGE_CENTRED; f[1] = 5; f[2] = num(1); put16(f + 3, centi(2)); put16(f + 5, num(3));
        send(f, 7);
    } else if (!strcmp(c, "gauge") && argc >= 2) {
        f[0] = OP_GAUGE; f[1] = 2; put16(f + 2, num(1));
        send(f, 4);
    } else {
        Serial.printf("ERR unknown %s (help)\n", c);
    }
}

static void updateLed()
{
    static uint32_t next;
    static uint32_t last = 0xFFFFFFFF;
    if ((int32_t)(millis() - next) < 0) {
        return;
    }
    next = millis() + 100;
    Status s;
    controllerSnapshot(&s, nullptr);
    uint32_t color = 0;
    if (s.fault != F_NONE) {
        color = (millis() / 500) % 2 ? led.Color(16, 0, 0) : 0; // blinking: fault latched
    } else if (s.flags & FL_HV_EN) {
        color = led.Color(8, 0, 0); // dim red: HV on (as the bring-up firmware)
    } else if (s.owner == OWN_USB) {
        color = led.Color(0, 0, 4); // dim blue: console owns it, dark
    }
    if (color != last) {
        led.setPixelColor(0, color);
        led.show();
        last = color;
    }
}

void setup()
{
    watchdogReset = watchdog_enable_caused_reboot();
    countBoot();
    controllerInitQueues();
    led.begin();
    led.setPixelColor(0, 0);
    led.show();
    Serial.begin(115200);
    Wire1.setSDA(pin::SDA);
    Wire1.setSCL(pin::SCL);
    Wire1.begin(I2C_ADDRESS);
    Wire1.onReceive(onI2cReceive);
    Wire1.onRequest(onI2cRequest);
    g_core0BeatMs = millis();
    g_lastI2cMs = millis();
    ready = true;
    rp2040.wdt_begin(WDT_MS);
}

void loop()
{
    g_core0BeatMs = millis();
    updateLed();
    while (Serial.available()) {
        int c = Serial.read();
        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            line[lineLen] = '\0';
            handleLine(line);
            lineLen = 0;
        } else if (lineLen < sizeof(line) - 1) {
            line[lineLen++] = (char)c;
        }
    }
}

void setup1()
{
    while (!ready) {
        tight_loop_contents();
    }
    controllerBegin(bootCount, watchdogReset);
}

void loop1() { controllerLoop(); }
