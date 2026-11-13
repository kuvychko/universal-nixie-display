// PIO guide driver: plays one step's four guide transitions on GP4/GP5 with 1 us resolution.
// SPDX-License-Identifier: MIT
#pragma once

#include <stdint.h>

bool stepperInit();        // claims a PIO state machine; guides at rest. false if no PIO free
void stepperStart(int dir); // +1 fwd (G1 first), -1 rev (G2 first); takes 3 x PHASE_US
void stepperRest();        // abort any step in progress, both guides at rest
