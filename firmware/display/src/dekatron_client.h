// I2C client for the dekatron controller (contract: docs/i2c_protocol.md, definitions:
// firmware/common/dekatron_protocol.h). The ESP32 is the sole master.
//
// Every write is confirmed: the client reads status before and after, and the command's result is
// the controller's last_error once cmd_seq has moved on. poll() reads status on a fixed period,
// which keeps the controller's master-loss timer fed while the tube is lit.
// SPDX-License-Identifier: MIT
#pragma once

#include <stdint.h>

#include "dekatron_protocol.h"

namespace dekc {

// Results beyond dek::Error, for the bus itself.
static const int R_BUS = -1;     // no ACK, short read, or a status block that is not a dekatron's
static const int R_TIMEOUT = -2; // written, but cmd_seq did not move within CONFIRM_MS

struct Stats {
    uint32_t reads, read_errors;   // status reads, and those that failed
    uint32_t writes, write_errors; // command writes, and those not ACKed
    uint32_t bad_status;           // read fine, but protocol/module/length wrong
    uint32_t confirm_timeouts;
};

void begin();
void poll();                            // call from loop(); reads status every POLL_MS when enabled
void setPolling(bool on);               // off: a bench test of master loss
bool polling();

bool readStatus(dek::Status *s);        // fresh read, validated
bool lastStatus(dek::Status *s);        // the latest good read; false if none yet
int command(uint8_t op, const uint8_t *payload, uint8_t len); // dek::Error, R_BUS or R_TIMEOUT
int raw(const uint8_t *frame, uint8_t n); // any bytes, confirmed the same way (error tests)
Stats stats();
const char *resultName(int r);

} // namespace dekc
