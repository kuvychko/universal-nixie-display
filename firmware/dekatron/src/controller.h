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
