// Core 1: the dekatron's hardware state (HV, guides, ADC, index), motion, tube care and faults.
// Core 0 hands it commands through a queue and reads a status snapshot; nothing else is shared.
// SPDX-License-Identifier: MIT
#pragma once

#include <stdint.h>

#include "dekatron_protocol.h"

enum Source : uint8_t { SRC_I2C = 0, SRC_USB = 1 };

struct Command {
    uint8_t src;     // Source
    uint8_t op;      // dek::Op
    uint8_t err;     // dek::Error found while framing (processed as a rejected write)
    uint8_t len;
    uint8_t data[8];
};

struct Reply {
    uint8_t seq;
    uint8_t err;
};

// Extra telemetry for the USB console, not part of the I2C status block.
struct Diag {
    uint16_t ndx_raw;     // last index sample, ADC counts
    uint16_t pio_ok;      // stepper PIO claimed
    // Last index mismatch: what the sample read, whether K1 was expected, the mode it broke, and
    // where the dead-reckoned count stood when the re-home found K1 (0: the glow was where it
    // was counted, so the sensing missed; otherwise steps were lost or gained). -1: none yet.
    uint16_t miss_ndx_raw;
    uint16_t late_ndx_raw; // first sample of the last late index (count in Status.idx_late)
    int8_t miss_expected;
    int8_t miss_mode;
    int8_t rehome_offset;
    // Periodic index check: steps and time since the last K1 that matched the count, and the
    // largest of each since boot (while lit with a valid position).
    uint16_t index_open_ms;  // from here a trip waits for a cheap moment
    uint16_t index_check_ms; // hard limit; 0 = off
    uint32_t unchecked_steps;
    uint32_t unchecked_ms;
    uint32_t max_unchecked_steps;
    uint32_t max_unchecked_ms;
    int32_t drop_detect_ms; // injected drop -> mismatch, ms; -1 none yet
    int32_t recovery_ms;    // last mismatch -> effect resumed, ms; -1 none yet
};

void controllerBegin(uint16_t bootCount, bool watchdogReset); // core 1 setup
void controllerLoop();                                       // core 1 loop

// Core 0 side (also callable from the I2C IRQ):
void controllerInitQueues(); // before either core uses them
bool controllerPost(const Command &c);
bool controllerReply(Reply *r);
void controllerSnapshot(dek::Status *s, Diag *d);
Command frameCommand(uint8_t src, const uint8_t *buf, int n);

extern volatile uint32_t g_lastI2cMs;  // any I2C traffic (core 0 IRQ)
extern volatile uint32_t g_core0BeatMs; // core 0 alive
