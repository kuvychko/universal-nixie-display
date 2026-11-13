// PIO guide driver. One step is two FIFO words: the phase delay count, then four 2-bit pin
// patterns (bit 0 = G1 on GP4, bit 1 = G2 on GP5), shifted out one per phase:
//   fwd: G1 | G1+G2 | G2 | rest     rev: G2 | G1+G2 | G1 | rest
// The state machine runs at 1 MHz (one instruction per us). Each phase is out(1) + mov(1) +
// a jmp x-- loop of X+1 cycles, so out-to-out = X + 3 us.
// SPDX-License-Identifier: MIT

#include "stepper.h"

#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/pio.h>
#include <hardware/pio_instructions.h>

#include "board.h"

static PIO pio;
static uint sm;
static uint offset;

static const uint32_t PATTERN_FWD = 0b00101101; // 01, 11, 10, 00 from the LSB
static const uint32_t PATTERN_REV = 0b00011110; // 10, 11, 01, 00
static const uint32_t PHASE_COUNT = PHASE_US - 3;

static uint16_t program[13];

static void build()
{
    program[0] = pio_encode_pull(false, true); // delay count
    program[1] = pio_encode_mov(pio_y, pio_osr);
    program[2] = pio_encode_pull(false, true); // patterns
    for (int k = 0; k < 3; k++) {
        uint base = 3 + 3 * k;
        program[base] = pio_encode_out(pio_pins, 2);
        program[base + 1] = pio_encode_mov(pio_x, pio_y);
        program[base + 2] = pio_encode_jmp_x_dec(base + 2); // relocated by pio_add_program
    }
    program[12] = pio_encode_out(pio_pins, 2); // rest
}

bool stepperInit()
{
    build();
    static const pio_program_t prog = {program, 13, -1};
    PIO candidates[2] = {pio1, pio0};
    for (PIO p : candidates) {
        if (!pio_can_add_program(p, &prog)) {
            continue;
        }
        int s = pio_claim_unused_sm(p, false);
        if (s < 0) {
            continue;
        }
        pio = p;
        sm = (uint)s;
        offset = pio_add_program(p, &prog);
        break;
    }
    if (pio == nullptr) {
        return false;
    }
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, offset, offset + 12);
    sm_config_set_out_pins(&c, pin::GUIDE1, 2);
    sm_config_set_out_shift(&c, true, false, 32); // shift right, no autopull
    sm_config_set_clkdiv(&c, (float)clock_get_hz(clk_sys) / 1e6f);
    pio_sm_set_pins_with_mask(pio, sm, 0, (1u << pin::GUIDE1) | (1u << pin::GUIDE2));
    pio_sm_set_consecutive_pindirs(pio, sm, pin::GUIDE1, 2, true);
    pio_gpio_init(pio, pin::GUIDE1);
    pio_gpio_init(pio, pin::GUIDE2);
    pio_sm_init(pio, sm, offset, &c);
    pio_sm_set_enabled(pio, sm, true);
    return true;
}

void stepperStart(int dir)
{
    pio_sm_put(pio, sm, PHASE_COUNT);
    pio_sm_put(pio, sm, dir > 0 ? PATTERN_FWD : PATTERN_REV);
}

void stepperRest()
{
    pio_sm_set_enabled(pio, sm, false);
    pio_sm_clear_fifos(pio, sm);
    pio_sm_restart(pio, sm);
    pio_sm_set_pins_with_mask(pio, sm, 0, (1u << pin::GUIDE1) | (1u << pin::GUIDE2));
    pio_sm_exec(pio, sm, pio_encode_jmp(offset));
    pio_sm_set_enabled(pio, sm, true);
}
