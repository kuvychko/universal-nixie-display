// Dekatron controller I2C protocol: shared by the controller (RP2040) and the display (ESP32).
// Contract: docs/i2c_protocol.md (draft, not frozen). Both ends are little-endian.
// SPDX-License-Identifier: MIT
#pragma once

#include <stdint.h>

namespace dek {

static const uint8_t I2C_ADDRESS = 0x20; // user decision 2026-11-12; the Nixie controller is 0x21
static const uint8_t PROTOCOL_VERSION = 1;
static const uint8_t MODULE_ID = 0x44; // 'D'

// Write: [op][len][payload...], len = payload bytes, fixed per op (opLength()).
enum Op : uint8_t {
    OP_PING = 0x01,          // -
    OP_LIGHT = 0x02,         // -                         HV on, strike, home
    OP_DARK = 0x03,          // -                         HV off
    OP_HOME = 0x04,          // -
    OP_MOVE_TO = 0x05,       // k u8 (0-9), dir u8 (0 shortest, 1 fwd, 2 rev)
    OP_MOVE_RELATIVE = 0x06, // n i16                     added to the step queue
    OP_ROTATE = 0x07,        // rate i32, 0.01 steps/s    0 stops
    OP_STOP = 0x08,          // -
    OP_SET_MOTION = 0x09,    // move_rate u16 steps/s (1-2000), accel u16 steps/s^2 (0 = none)
    OP_SWING = 0x0A,         // centre u8, amplitude u8 (1-5), period u16 ms (100-60000)
    OP_BOUNCE = 0x0B,        // a u8, b u8 (forward from a to b and back), rate u16 steps/s
    OP_SPIN = 0x0C,          // start u16, end u16 steps/s, accel u16 steps/s^2, turns u8 (1-255)
    OP_ARC = 0x0D,           // start u8, length u8 (1-10), sweep u16 steps/s, end_weight u8
    OP_GAUGE = 0x0E,         // value u16 (0-1000 = 0-10 cathodes)
    OP_EXERCISE = 0x0F,      // -                         20 min at >= 100 steps/s, then back
    OP_CLEAR_FAULT = 0x10,   // -
    OP_BOOTSEL = 0x11,       // -                         reboot to the USB bootloader (dark only)
    // USB console only:
    OP_OWNER_LOCAL = 0x80,
    OP_OWNER_REMOTE = 0x81,
};

inline int opLength(uint8_t op)
{
    switch (op) {
    case OP_PING: case OP_LIGHT: case OP_DARK: case OP_HOME: case OP_STOP: case OP_EXERCISE:
    case OP_CLEAR_FAULT: case OP_BOOTSEL: case OP_OWNER_LOCAL: case OP_OWNER_REMOTE:
        return 0;
    case OP_MOVE_TO: case OP_MOVE_RELATIVE: case OP_GAUGE:
        return 2;
    case OP_ROTATE: case OP_SET_MOTION: case OP_SWING: case OP_BOUNCE:
        return 4;
    case OP_ARC:
        return 5;
    case OP_SPIN:
        return 7;
    default:
        return -1;
    }
}

enum Error : uint8_t {
    E_OK = 0,
    E_BAD_OP = 1,     // unknown op
    E_BAD_LEN = 2,    // frame or payload length wrong
    E_RANGE = 3,      // a value outside its documented range; never clamped
    E_STATE = 4,      // not possible now: dark, not homed, fault latched, HV not off...
    E_NOT_OWNER = 5,  // the other interface owns the controller
    E_QUEUE_FULL = 6, // step queue would overflow
    E_VIN = 7,        // LIGHT refused: VIN outside its window
};

enum Power : uint8_t { PWR_DARK = 0, PWR_STRIKING = 1, PWR_LIT = 2 };

enum Fault : uint8_t {
    F_NONE = 0,
    F_VIN = 1,            // VIN left 10.8-13.2 V while HV on
    F_EN_LOW = 2,         // EN/UVLO read low: OVP comparator or JP101 inhibit
    F_HV_LOW = 3,         // PGOOD low while lit, or never high while striking
    F_STRIKE_TIMEOUT = 4, // no glow confirmed within the strike window
    F_INDEX_TIMEOUT = 5,  // HOME found no consistent index within its step budget
};

enum DarkReason : uint8_t {
    DR_BOOT = 0, DR_COMMAND = 1, DR_FAULT = 2, DR_MASTER_LOSS = 3, DR_HOLD_LIMIT = 4,
};

enum Owner : uint8_t { OWN_I2C = 0, OWN_USB = 1 };

enum Mode : uint8_t {
    M_IDLE = 0, M_HOME = 1, M_QUEUE = 2, M_ROTATE = 3, M_SWING = 4, M_BOUNCE = 5, M_SPIN = 6,
    M_ARC = 7, M_EXERCISE = 8,
};

enum Flag : uint8_t {
    FL_POSITION_VALID = 1 << 0,
    FL_BUSY = 1 << 1,          // mode != idle
    FL_PGOOD = 1 << 2,
    FL_HV_EN = 1 << 3,
    FL_MASTER_LOSS = 1 << 4,   // went dark on master loss; clears on the next LIGHT
    FL_EXERCISE_DUE = 1 << 5,  // slow running (<= 1 step/s) since the last complete EXERCISE
    FL_WATCHDOG_RESET = 1 << 6,
};

// Read: the master reads up to sizeof(Status) bytes from offset 0.
struct __attribute__((packed)) Status {
    uint8_t protocol;        // PROTOCOL_VERSION
    uint8_t module;          // MODULE_ID
    uint16_t firmware;       // major << 8 | minor
    uint16_t boot_count;     // increments every boot (flash)
    uint32_t uptime_ms;
    uint8_t cmd_seq;         // increments on every processed write, accepted or not
    uint8_t last_error;      // Error of the last processed write
    uint8_t owner;           // Owner
    uint8_t power;           // Power
    uint8_t fault;           // Fault, latched until CLEAR_FAULT
    uint8_t dark_reason;     // DarkReason of the last time it went dark
    uint8_t flags;           // Flag bits
    uint8_t position;        // 0-9, 0 = K1 (index); meaningful with FL_POSITION_VALID
    uint8_t mode;            // Mode
    int16_t queue;           // pending queued steps, signed
    uint16_t idx_expected;   // K1 arrivals expected while the position was valid (wrapping)
    uint16_t idx_observed;   // K1 arrivals seen while the position was valid (wrapping)
    uint16_t home_failures;  // inconsistent index patterns during homing (wrapping)
    uint16_t idx_mismatches; // index disagreed with the count (wrapping)
    uint32_t dwell_ms;       // time on the current cathode
    uint16_t rate_dsps;      // steps in the last 10 s, as 0.1 steps/s
    uint32_t slow_run_s;     // slow running since the last complete EXERCISE
    uint16_t hv_dv;          // HV_SENSE, 0.1 V (indicative: 3.3 V ADC reference)
    uint16_t vin_dv;         // VIN_SENSE, 0.1 V
    uint16_t rtn_dv;         // RTN_SENSE, 0.1 V
};
static_assert(sizeof(Status) == 45, "Status layout changed: update docs/i2c_protocol.md");

} // namespace dek
