// SPDX-License-Identifier: MIT
#include "dekatron_client.h"

#include <Arduino.h>
#include <Wire.h>
#include <string.h>

#include "pins.h"

namespace dekc {

namespace {

// Status every 100 ms: well inside the controller's 5 s master-loss timeout, and fresh enough for
// a UI. A command is applied between steps (<= 0.5 ms), so 50 ms to confirm is generous.
constexpr uint32_t POLL_MS = 100;
constexpr uint32_t CONFIRM_MS = 50;
constexpr uint32_t CONFIRM_STEP_US = 1000;

dek::Status g_last;
bool g_haveLast = false;
bool g_polling = true;
uint32_t g_nextPollMs = 0;
Stats g_stats = {};

bool readOnce(dek::Status *s)
{
    g_stats.reads++;
    size_t n = Wire.requestFrom(dek::I2C_ADDRESS, sizeof(dek::Status));
    if (n != sizeof(dek::Status)) {
        while (Wire.available()) {
            Wire.read();
        }
        g_stats.read_errors++;
        return false;
    }
    uint8_t buf[sizeof(dek::Status)];
    for (size_t i = 0; i < n; i++) {
        buf[i] = (uint8_t)Wire.read();
    }
    memcpy(s, buf, sizeof(buf));
    if (s->protocol != dek::PROTOCOL_VERSION || s->module != dek::MODULE_ID) {
        g_stats.bad_status++;
        return false;
    }
    g_last = *s;
    g_haveLast = true;
    return true;
}

int writeConfirmed(const uint8_t *frame, uint8_t n)
{
    dek::Status s;
    if (!readOnce(&s)) {
        return R_BUS;
    }
    uint8_t seq0 = s.cmd_seq;
    g_stats.writes++;
    Wire.beginTransmission(dek::I2C_ADDRESS);
    Wire.write(frame, n);
    if (Wire.endTransmission() != 0) {
        g_stats.write_errors++;
        return R_BUS;
    }
    uint32_t t0 = millis();
    while (millis() - t0 < CONFIRM_MS) {
        delayMicroseconds(CONFIRM_STEP_US);
        if (readOnce(&s) && s.cmd_seq != seq0) {
            return s.last_error;
        }
    }
    g_stats.confirm_timeouts++;
    return R_TIMEOUT;
}

} // namespace

void begin()
{
    // SCL is also the microSD clock: hold the card deselected with its command line idle, so the
    // I2C clock is never taken for card traffic (as nanovolt-divider).
    pinMode(pins::SD_CS, OUTPUT);
    digitalWrite(pins::SD_CS, HIGH);
    pinMode(pins::SD_MOSI, OUTPUT);
    digitalWrite(pins::SD_MOSI, HIGH);
    Wire.begin(pins::I2C_SDA, pins::I2C_SCL, 100000); // docs/i2c_protocol.md: 100 kHz to start
    Wire.setTimeOut(20);
}

void poll()
{
    if (!g_polling || (int32_t)(millis() - g_nextPollMs) < 0) {
        return;
    }
    g_nextPollMs = millis() + POLL_MS;
    dek::Status s;
    readOnce(&s);
}

void setPolling(bool on) { g_polling = on; }
bool polling() { return g_polling; }

bool readStatus(dek::Status *s) { return readOnce(s); }

bool lastStatus(dek::Status *s)
{
    if (g_haveLast) {
        *s = g_last;
    }
    return g_haveLast;
}

int command(uint8_t op, const uint8_t *payload, uint8_t len)
{
    uint8_t frame[2 + 16];
    if (len > 16) {
        return dek::E_BAD_LEN;
    }
    frame[0] = op;
    frame[1] = len;
    memcpy(frame + 2, payload, len);
    return writeConfirmed(frame, 2 + len);
}

int raw(const uint8_t *frame, uint8_t n) { return writeConfirmed(frame, n); }

Stats stats() { return g_stats; }

const char *resultName(int r)
{
    static const char *names[] = {"ok", "bad_op", "bad_len", "range", "state", "not_owner", "queue_full", "vin"};
    if (r == R_BUS) {
        return "bus";
    }
    if (r == R_TIMEOUT) {
        return "timeout";
    }
    return r >= 0 && r < (int)(sizeof(names) / sizeof(names[0])) ? names[r] : "?";
}

} // namespace dekc
