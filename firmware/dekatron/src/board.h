// Pins, scaling and timing parameters for the dekatron controller. Sources: docs/hardware.md
// (RP2040-Zero pin assignment, D1, D8, D9), the board 1 speed sweep
// (characterization/dekatron/2026-11-12_speed_sweep.md) and the user's decisions in README.md.
// SPDX-License-Identifier: MIT
#pragma once

#include <stdint.h>

namespace pin {
static const uint8_t SDA = 2;      // I2C1 SDA (target)
static const uint8_t SCL = 3;      // I2C1 SCL
static const uint8_t GUIDE1 = 4;   // G1 driver base (D8); PIO, adjacent to GUIDE2
static const uint8_t GUIDE2 = 5;   // G2 driver base
static const uint8_t HV_EN = 6;    // LM5156 EN/UVLO; external pull-down (D7)
static const uint8_t PGOOD = 7;    // LM5156 PGOOD, 10k pull-up
static const uint8_t EN_NODE = 8;  // OVP_TRIP: the EN/UVLO node; no internal pull (review item 4)
static const uint8_t LED = 16;     // module WS2812
static const uint8_t NDX = 26;     // ADC0: index level shifter, 2.67-2.95 V with the glow on K1
static const uint8_t VIN = 27;     // ADC1: 100k / 12k
static const uint8_t HV = 28;      // ADC2: HV / 192.9
static const uint8_t RTN = 29;     // ADC3: RTN / 21
} // namespace pin

static const float ADC_VREF = 3.3f;
static const float VIN_SCALE = 112.0f / 12.0f;
static const float HV_SCALE = 192.9f;
static const float RTN_SCALE = 21.0f;
static const float NDX_HIGH_V = 2.0f; // RP2040 V_IH min at IOVDD 3.3 V
static const uint16_t NDX_HIGH_RAW = (uint16_t)(NDX_HIGH_V / ADC_VREF * 4095.0f);

// 12 V +/-10 % (as the bring-up firmware): 10.8 V simulated corner, 13.2 V user's choice.
static const float VIN_MIN = 10.8f;
static const float VIN_MAX = 13.2f;

static const uint32_t EN_BLANK_US = 2000; // EN node settles after HV_EN rises (bring-up)
static const uint32_t WDT_MS = 500;
static const uint32_t CORE0_BEAT_MAX_MS = 200; // core 1 stops feeding the watchdog if core 0 stalls

// Step timing envelope (user, 2026-11-12, from the speed sweep; outside the datasheet).
static const uint32_t PHASE_US = 100;
static const uint32_t MAX_RATE = 2000;                 // steps/s
static const uint32_t MIN_PERIOD_US = 1000000 / MAX_RATE; // 500 us: 300 us of guide sequence + 200 us rest
static const uint32_t SAMPLE_US = 100;                 // NDX sample after the second guide releases
static const uint32_t SAMPLE_AT_US = 3 * PHASE_US + SAMPLE_US;
static_assert(SAMPLE_AT_US + 50 <= MIN_PERIOD_US, "index sample must fit before the next step");
// Recheck of a disagreeing index sample, just before the earliest next step (170 us after release).
static const uint32_t RECHECK_AT_US = MIN_PERIOD_US - 30;

// Homing and striking.
static const uint32_t HOME_RATE = 200;         // plan section 5 homing target
static const uint32_t HOME_MAX_STEPS = 50;     // 5 turns incl. confirmation retries, then index_timeout
static const uint32_t STRIKE_TIMEOUT_MS = 10000; // 2 x the datasheet's 5 s readiness in darkness
static const uint32_t PGOOD_LOW_MS = 100;      // PGOOD low this long while lit -> hv_low

// Tube care (plan section 5; datasheet: below 0.01 Hz for <= 1 h; >= 20 min at >= 100 Hz after <= 1 Hz).
static const uint64_t HOLD_LIMIT_US = 30ull * 60 * 1000000; // user, 2026-11-12: then dark
static const uint64_t VERY_SLOW_GAP_US = 100ull * 1000000;  // a gap > 100 s is below 0.01 Hz
static const uint32_t SLOW_STEPS_10S = 10;                  // <= 1 step/s over 10 s is slow running
static const uint32_t EXERCISE_RATE = 200;                  // >= 100 steps/s
static const uint64_t EXERCISE_US = 20ull * 60 * 1000000;   // datasheet: at least 20 min

// Master loss (user, 2026-11-12): no I2C traffic for this long while lit -> dark.
static const uint32_t MASTER_LOSS_MS = 5000;

static const uint16_t MOVE_RATE_DEFAULT = HOME_RATE;
static const int32_t QUEUE_MAX = 32767;

static const uint16_t FIRMWARE_VERSION = 0x0001; // 0.1
