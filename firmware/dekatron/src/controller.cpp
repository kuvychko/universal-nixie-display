// Core 1: hardware state, motion, index checking, tube care and faults. Spec: ../README.md.
// Everything that touches HV_EN, the guides or the ADC runs here, from one busy loop:
//   commands -> safety -> index sample (in flight) -> telemetry -> next step -> status snapshot.
// SPDX-License-Identifier: MIT

#include "controller.h"

#include <Arduino.h>
#include <hardware/adc.h>
#include <hardware/gpio.h>
#include <math.h>
#include <pico/sync.h>
#include <pico/util/queue.h>

#include "board.h"
#include "stepper.h"

using namespace dek;

volatile uint32_t g_lastI2cMs = 0;
volatile uint32_t g_core0BeatMs = 0;

static queue_t cmdQueue;
static queue_t replyQueue;
static critical_section_t statusLock;
static Status shared;
static Diag sharedDiag;

// ---- state (core 1 only) ----
static uint16_t bootCount;
static bool wdtReset;
static uint8_t cmdSeq, lastError;
static uint8_t owner = OWN_I2C;
static uint8_t power = PWR_DARK;
static uint8_t fault = F_NONE;
static uint8_t darkReason = DR_BOOT;
static bool masterLoss;
static bool pioOk;
static uint32_t bootselAtMs;

static uint64_t hvOnUs;
static bool pgoodSeen;
static bool pgoodLowTiming;
static uint64_t pgoodLowSinceUs;

static int32_t absPos;  // unwrapped steps; K1 at multiples of 10 once homed
static bool posValid;

static bool inFlight;
static uint64_t stepStartUs;
static uint64_t lastStepUs; // start of the last step
static uint16_t ndxRaw;

static uint8_t mode = M_IDLE;
static int32_t queuePending;
static uint16_t moveRate = MOVE_RATE_DEFAULT;
static uint16_t accel;
static float rate, targetRate, acc; // steps/s, signed
static uint64_t lastTickUs;

// home
static bool homeConfirming;
static uint16_t homeSteps, homeConfirm;
// swing
static int32_t swingCentre;
static uint8_t swingAmp;
static uint32_t swingPeriodMs;
static uint64_t swingT0;
// sweep (arc, gauge, bounce)
static int32_t sweepLo, sweepHi;
static int8_t sweepDir;
static uint32_t sweepIntervalUs, sweepLoDwellUs, sweepHiDwellUs;
// spin / exercise
static int32_t spinStepsLeft;
static uint16_t spinAccel;
static uint64_t exerciseEndUs;
static uint8_t returnPos;

// tube care
static uint64_t verySlowUs;
static uint64_t slowRunUs;
static uint16_t rateBins[10]; // steps per second; MAX_RATE 2000 fits
static uint32_t rateSec;

// telemetry
static float hvV, vinV, rtnV;
static uint8_t adcNext;
static uint64_t nextAdcUs;
static uint64_t nextSnapUs;

static uint16_t idxExpected, idxObserved, homeFailures, idxMismatches;

// ---- helpers ----
static uint8_t posMod() { return (uint8_t)(((absPos % 10) + 10) % 10); }

static int32_t shortest(uint8_t from, uint8_t to)
{
    int32_t d = ((int32_t)to - from + 10) % 10;
    return d > 5 ? d - 10 : d;
}

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

static float adcVolts(uint8_t pin)
{
    adc_select_input(pin - 26);
    return adc_read() * ADC_VREF / 4095.0f;
}

static uint32_t stepsLast10s()
{
    uint32_t s = 0;
    for (uint16_t b : rateBins) {
        s += b;
    }
    return s;
}

static void setIdle()
{
    mode = M_IDLE;
    queuePending = 0;
    rate = targetRate = acc = 0;
}

static void goDark(uint8_t why)
{
    gpio_put(pin::HV_EN, 0);
    if (pioOk) {
        stepperRest();
    }
    inFlight = false;
    power = PWR_DARK;
    posValid = false;
    darkReason = why;
    setIdle();
}

static void setFault(uint8_t f)
{
    fault = f;
    goDark(DR_FAULT);
}

static void startHome()
{
    mode = M_HOME;
    posValid = false;
    homeConfirming = false;
    homeSteps = homeConfirm = 0;
}

static void returnTo(uint8_t k)
{
    setIdle();
    mode = M_QUEUE;
    queuePending = shortest(posMod(), k);
}

static void startSweep(int32_t lo, int32_t hi, uint32_t intervalUs, uint32_t loDwellUs, uint32_t hiDwellUs, uint8_t m)
{
    setIdle();
    mode = m;
    sweepLo = lo;
    sweepHi = hi;
    sweepDir = 1;
    sweepIntervalUs = intervalUs;
    sweepLoDwellUs = loDwellUs;
    sweepHiDwellUs = hiDwellUs;
}

// Arc of len cathodes from start: every cathode gets two intervals per sweep cycle (interior: one
// each way; ends: a double dwell), the far end scaled by weight/255.
static void startArc(uint8_t start, uint8_t len, uint16_t sweep, uint8_t weight)
{
    int32_t lo = absPos + shortest(posMod(), start);
    uint32_t iv = 1000000UL / sweep;
    uint32_t hiDwell = (uint32_t)((2ull * iv * weight) / 255);
    if (hiDwell < MIN_PERIOD_US) {
        hiDwell = MIN_PERIOD_US;
    }
    startSweep(lo, lo + len - 1, iv, 2 * iv, hiDwell, M_ARC);
}

static void startRotate(float r, uint8_t m)
{
    uint8_t keep = mode == m ? 1 : 0;
    if (!keep) {
        setIdle();
        lastTickUs = time_us_64();
    }
    mode = m;
    targetRate = r;
    if (accel == 0) {
        rate = r;
    }
}

// ---- commands ----
static uint8_t needMotion()
{
    if (power != PWR_LIT || !posValid) {
        return E_STATE;
    }
    return E_OK;
}

static uint8_t execute(const Command &c)
{
    if (c.err) {
        return c.err;
    }
    if (c.op == OP_OWNER_LOCAL || c.op == OP_OWNER_REMOTE) {
        if (c.src != SRC_USB) {
            return E_BAD_OP;
        }
        owner = c.op == OP_OWNER_LOCAL ? OWN_USB : OWN_I2C;
        g_lastI2cMs = millis(); // grace period before master-loss applies again
        return E_OK;
    }
    if (c.op == OP_PING) {
        return E_OK;
    }
    if ((c.src == SRC_I2C) != (owner == OWN_I2C)) {
        return E_NOT_OWNER;
    }
    const uint8_t *d = c.data;
    uint8_t e;
    switch (c.op) {
    case OP_LIGHT:
        if (fault != F_NONE) {
            return E_STATE;
        }
        if (power != PWR_DARK) {
            return E_OK;
        }
        if (vinV < VIN_MIN || vinV > VIN_MAX) {
            return E_VIN;
        }
        if (!pioOk) {
            return E_STATE;
        }
        masterLoss = false;
        pgoodSeen = false;
        pgoodLowTiming = false;
        hvOnUs = time_us_64();
        power = PWR_STRIKING;
        gpio_put(pin::HV_EN, 1);
        startHome();
        return E_OK;
    case OP_DARK:
        goDark(DR_COMMAND);
        return E_OK;
    case OP_HOME:
        if (power != PWR_LIT) {
            return E_STATE;
        }
        setIdle();
        startHome();
        return E_OK;
    case OP_MOVE_TO: {
        if (d[0] > 9 || d[1] > 2) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        int32_t n = shortest(posMod(), d[0]);
        if (d[1] == 1) {
            n = ((int32_t)d[0] - posMod() + 10) % 10;
        } else if (d[1] == 2) {
            n = -(((int32_t)posMod() - d[0] + 10) % 10);
        }
        setIdle();
        mode = M_QUEUE;
        queuePending = n;
        return E_OK;
    }
    case OP_MOVE_RELATIVE: {
        int16_t n = (int16_t)rd16(d);
        if ((e = needMotion())) {
            return e;
        }
        int32_t base = mode == M_QUEUE ? queuePending : 0;
        if (base + n > QUEUE_MAX || base + n < -QUEUE_MAX) {
            return E_QUEUE_FULL;
        }
        if (mode != M_QUEUE) {
            setIdle();
            mode = M_QUEUE;
        }
        queuePending = base + n;
        return E_OK;
    }
    case OP_ROTATE: {
        int32_t r = (int32_t)rd32(d);
        if (r > (int32_t)MAX_RATE * 100 || r < -(int32_t)MAX_RATE * 100) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        startRotate(r / 100.0f, M_ROTATE);
        return E_OK;
    }
    case OP_STOP:
        if (mode != M_HOME) {
            setIdle();
        }
        return E_OK;
    case OP_SET_MOTION: {
        uint16_t mr = rd16(d), a = rd16(d + 2);
        if (mr == 0 || mr > MAX_RATE) {
            return E_RANGE;
        }
        moveRate = mr;
        accel = a;
        return E_OK;
    }
    case OP_SWING: {
        uint16_t period = rd16(d + 2);
        if (d[0] > 9 || d[1] < 1 || d[1] > 5 || period < 100 || period > 60000) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        setIdle();
        mode = M_SWING;
        swingCentre = absPos + shortest(posMod(), d[0]);
        swingAmp = d[1];
        swingPeriodMs = period;
        swingT0 = time_us_64();
        return E_OK;
    }
    case OP_BOUNCE: {
        uint16_t r = rd16(d + 2);
        if (d[0] > 9 || d[1] > 9 || d[0] == d[1] || r == 0 || r > MAX_RATE) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        int32_t lo = absPos + shortest(posMod(), d[0]);
        uint32_t iv = 1000000UL / r;
        startSweep(lo, lo + ((d[1] - d[0] + 10) % 10), iv, iv, iv, M_BOUNCE);
        return E_OK;
    }
    case OP_SPIN: {
        uint16_t s0 = rd16(d), s1 = rd16(d + 2), a = rd16(d + 4);
        uint8_t turns = d[6];
        if (s0 > MAX_RATE || s1 == 0 || s1 > MAX_RATE || turns == 0) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        returnPos = posMod();
        setIdle();
        mode = M_SPIN;
        lastTickUs = time_us_64();
        rate = s0;
        targetRate = s1;
        spinAccel = a;
        spinStepsLeft = 10 * (int32_t)turns;
        return E_OK;
    }
    case OP_ARC: {
        uint16_t sweep = rd16(d + 2);
        if (d[0] > 9 || d[1] < 1 || d[1] > 10 || sweep == 0 || sweep > MAX_RATE) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        startArc(d[0], d[1], sweep, d[4]);
        return E_OK;
    }
    case OP_GAUGE: {
        uint16_t v = rd16(d);
        if (v > 1000) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        uint8_t full = v / 100, frac = v % 100;
        uint8_t len = full + (frac ? 1 : 0);
        if (len < 1) {
            len = 1;
        }
        startArc(0, len, MAX_RATE, frac ? (uint8_t)(frac * 255 / 100) : 255);
        return E_OK;
    }
    case OP_EXERCISE:
        if ((e = needMotion())) {
            return e;
        }
        returnPos = posMod();
        startRotate((float)EXERCISE_RATE, M_EXERCISE);
        rate = EXERCISE_RATE;
        exerciseEndUs = time_us_64() + EXERCISE_US;
        return E_OK;
    case OP_CLEAR_FAULT:
        fault = F_NONE;
        return E_OK;
    case OP_BOOTSEL:
        if (power != PWR_DARK) {
            return E_STATE;
        }
        bootselAtMs = millis() + 100; // let core 0 print the reply first
        return E_OK;
    default:
        return E_BAD_OP;
    }
}

// ---- stepping ----
static void startStep(int dir, uint64_t now)
{
    uint64_t gap = now - lastStepUs;
    verySlowUs = gap >= VERY_SLOW_GAP_US ? verySlowUs + gap : 0;
    stepperStart(dir);
    absPos += dir;
    stepStartUs = lastStepUs = now;
    inFlight = true;
    rateBins[rateSec % 10]++;
    if (mode == M_QUEUE) {
        queuePending -= dir;
    } else if (mode == M_SPIN || mode == M_ROTATE || mode == M_EXERCISE) {
        acc -= dir;
        if (mode == M_SPIN) {
            spinStepsLeft--;
        }
    }
}

static void finishStep()
{
    inFlight = false;
    adc_select_input(pin::NDX - 26);
    ndxRaw = adc_read();
    bool hit = ndxRaw > NDX_HIGH_RAW;

    if (mode == M_HOME) {
        homeSteps++;
        if (!homeConfirming) {
            if (hit) {
                homeConfirming = true;
                homeConfirm = 0;
            }
        } else {
            homeConfirm++;
            if (hit && homeConfirm == 10) {
                // K1 again after exactly one turn and not in between: one glow, consistent index.
                absPos = 0;
                posValid = true;
                setIdle();
                if (power == PWR_STRIKING) {
                    power = PWR_LIT;
                    verySlowUs = 0;
                }
                return;
            }
            if (hit || homeConfirm >= 10) {
                homeFailures++;
                homeConfirming = hit; // an early hit is the new candidate
                homeConfirm = 0;
            }
        }
        if (power == PWR_LIT && homeSteps >= HOME_MAX_STEPS) {
            setFault(F_INDEX_TIMEOUT);
        }
        return;
    }
    if (posValid) {
        bool expected = posMod() == 0;
        idxExpected += expected;
        idxObserved += hit;
        if (hit != expected) {
            idxMismatches++;
            posValid = false; // re-homed at the next idle boundary
        }
    }
}

// Next step direction for the current mode, or 0; *gapUs is the minimum time since the last step.
static int decide(uint64_t now, uint32_t *gapUs)
{
    *gapUs = MIN_PERIOD_US;
    switch (mode) {
    case M_HOME:
        *gapUs = 1000000UL / HOME_RATE;
        return 1;
    case M_QUEUE:
        if (queuePending == 0) {
            setIdle();
            return 0;
        }
        *gapUs = 1000000UL / moveRate;
        return queuePending > 0 ? 1 : -1;
    case M_ROTATE:
    case M_SPIN:
    case M_EXERCISE: {
        float dt = (now - lastTickUs) / 1e6f;
        lastTickUs = now;
        uint16_t a = mode == M_SPIN ? spinAccel : mode == M_ROTATE ? accel : 0;
        if (rate != targetRate) {
            float step = a ? a * dt : fabsf(targetRate - rate);
            rate = rate < targetRate ? fminf(rate + step, targetRate) : fmaxf(rate - step, targetRate);
        }
        acc = fmaxf(-2.0f, fminf(2.0f, acc + rate * dt));
        if (mode == M_SPIN && spinStepsLeft <= 0) {
            returnTo(returnPos);
            return 0;
        }
        if (mode == M_EXERCISE && now >= exerciseEndUs) {
            slowRunUs = 0; // complete: the datasheet's training period has run
            returnTo(returnPos);
            return 0;
        }
        return acc >= 1.0f ? 1 : acc <= -1.0f ? -1 : 0;
    }
    case M_SWING: {
        float t = (now - swingT0) / 1000.0f;
        float target = swingCentre + swingAmp * sinf(2.0f * (float)M_PI * t / swingPeriodMs);
        int32_t d = lroundf(target) - absPos;
        return d > 0 ? 1 : d < 0 ? -1 : 0;
    }
    case M_ARC:
    case M_BOUNCE: {
        if (absPos < sweepLo || absPos > sweepHi) {
            *gapUs = sweepIntervalUs;
            return absPos < sweepLo ? 1 : -1;
        }
        if (sweepLo == sweepHi) {
            return 0;
        }
        if (absPos == sweepHi) {
            sweepDir = -1;
            *gapUs = sweepHiDwellUs;
        } else if (absPos == sweepLo) {
            sweepDir = 1;
            *gapUs = sweepLoDwellUs;
        } else {
            *gapUs = sweepIntervalUs;
        }
        return sweepDir;
    }
    default:
        return 0;
    }
}

// ---- safety and tube care ----
static void safety(uint64_t now)
{
    bool hvEn = gpio_get_out_level(pin::HV_EN);
    if (!hvEn) {
        return;
    }
    if (now - hvOnUs >= EN_BLANK_US && !gpio_get(pin::EN_NODE)) {
        setFault(F_EN_LOW);
        return;
    }
    if (vinV < VIN_MIN || vinV > VIN_MAX) {
        setFault(F_VIN);
        return;
    }
    bool pg = gpio_get(pin::PGOOD);
    pgoodSeen |= pg;
    if (power == PWR_STRIKING && now - hvOnUs > STRIKE_TIMEOUT_MS * 1000ull) {
        setFault(pgoodSeen ? F_STRIKE_TIMEOUT : F_HV_LOW);
        return;
    }
    if (power == PWR_LIT) {
        if (pg) {
            pgoodLowTiming = false;
        } else if (!pgoodLowTiming) {
            pgoodLowTiming = true;
            pgoodLowSinceUs = now;
        } else if (now - pgoodLowSinceUs >= PGOOD_LOW_MS * 1000ull) {
            setFault(F_HV_LOW);
            return;
        }
        uint64_t dwell = now - lastStepUs;
        uint64_t hold = verySlowUs + (dwell >= VERY_SLOW_GAP_US ? dwell : 0);
        if (hold >= HOLD_LIMIT_US) {
            goDark(DR_HOLD_LIMIT);
            return;
        }
    }
    if (owner == OWN_I2C && (uint32_t)(millis() - g_lastI2cMs) > MASTER_LOSS_MS) {
        masterLoss = true;
        goDark(DR_MASTER_LOSS);
    }
}

static void tubeCare(uint64_t now, uint64_t dtUs)
{
    uint32_t sec = (uint32_t)(now / 1000000ull);
    while (rateSec != sec) {
        rateSec++;
        rateBins[rateSec % 10] = 0;
        if (sec - rateSec > 10) {
            rateSec = sec - 10;
        }
    }
    if (power == PWR_LIT && stepsLast10s() <= SLOW_STEPS_10S) {
        slowRunUs += dtUs;
    }
}

static void telemetry(uint64_t now)
{
    if (now < nextAdcUs) {
        return;
    }
    nextAdcUs = now + 2000;
    static const float alpha = 0.25f;
    switch (adcNext++ % 3) {
    case 0: vinV += alpha * (adcVolts(pin::VIN) * VIN_SCALE - vinV); break;
    case 1: hvV += alpha * (adcVolts(pin::HV) * HV_SCALE - hvV); break;
    default: rtnV += alpha * (adcVolts(pin::RTN) * RTN_SCALE - rtnV); break;
    }
}

static void snapshot(uint64_t now)
{
    Status s = {};
    s.protocol = PROTOCOL_VERSION;
    s.module = MODULE_ID;
    s.firmware = FIRMWARE_VERSION;
    s.boot_count = bootCount;
    s.uptime_ms = (uint32_t)(now / 1000);
    s.cmd_seq = cmdSeq;
    s.last_error = lastError;
    s.owner = owner;
    s.power = power;
    s.fault = fault;
    s.dark_reason = darkReason;
    s.flags = (posValid ? FL_POSITION_VALID : 0) | (mode != M_IDLE ? FL_BUSY : 0) |
              (gpio_get(pin::PGOOD) ? FL_PGOOD : 0) | (gpio_get_out_level(pin::HV_EN) ? FL_HV_EN : 0) |
              (masterLoss ? FL_MASTER_LOSS : 0) | (slowRunUs >= 1000000 ? FL_EXERCISE_DUE : 0) |
              (wdtReset ? FL_WATCHDOG_RESET : 0);
    s.position = posMod();
    s.mode = mode;
    s.queue = (int16_t)(queuePending > 32767 ? 32767 : queuePending < -32767 ? -32767 : queuePending);
    s.idx_expected = idxExpected;
    s.idx_observed = idxObserved;
    s.home_failures = homeFailures;
    s.idx_mismatches = idxMismatches;
    s.dwell_ms = power == PWR_DARK ? 0 : (uint32_t)((now - lastStepUs) / 1000);
    s.rate_dsps = (uint16_t)stepsLast10s(); // steps per 10 s = 0.1 steps/s
    s.slow_run_s = (uint32_t)(slowRunUs / 1000000ull);
    s.hv_dv = (uint16_t)(fmaxf(hvV, 0) * 10 + 0.5f);
    s.vin_dv = (uint16_t)(fmaxf(vinV, 0) * 10 + 0.5f);
    s.rtn_dv = (uint16_t)(fmaxf(rtnV, 0) * 10 + 0.5f);
    critical_section_enter_blocking(&statusLock);
    shared = s;
    sharedDiag.ndx_raw = ndxRaw;
    sharedDiag.pio_ok = pioOk;
    critical_section_exit(&statusLock);
}

// ---- public ----
void controllerInitQueues()
{
    queue_init(&cmdQueue, sizeof(Command), 16);
    queue_init(&replyQueue, sizeof(Reply), 16);
    critical_section_init(&statusLock);
}

void controllerBegin(uint16_t boots, bool watchdog)
{
    // HV off and guides at rest first; the external pull-downs held them until now.
    gpio_init(pin::HV_EN);
    gpio_put(pin::HV_EN, 0);
    gpio_set_dir(pin::HV_EN, GPIO_OUT);
    gpio_init(pin::GUIDE1);
    gpio_init(pin::GUIDE2);
    gpio_put(pin::GUIDE1, 0);
    gpio_put(pin::GUIDE2, 0);
    gpio_set_dir(pin::GUIDE1, GPIO_OUT);
    gpio_set_dir(pin::GUIDE2, GPIO_OUT);
    gpio_init(pin::PGOOD);
    gpio_disable_pulls(pin::PGOOD);
    gpio_init(pin::EN_NODE);
    gpio_disable_pulls(pin::EN_NODE); // a pull-down would load EN/UVLO
    pioOk = stepperInit();

    adc_init();
    static const uint8_t adcPins[] = {pin::NDX, pin::VIN, pin::HV, pin::RTN};
    for (uint8_t p : adcPins) {
        adc_gpio_init(p);
    }
    // Seed the filters so the first status and the first LIGHT see real values.
    vinV = adcVolts(pin::VIN) * VIN_SCALE;
    hvV = adcVolts(pin::HV) * HV_SCALE;
    rtnV = adcVolts(pin::RTN) * RTN_SCALE;

    bootCount = boots;
    wdtReset = watchdog;
    uint64_t now = time_us_64();
    lastStepUs = lastTickUs = now;
    rateSec = (uint32_t)(now / 1000000ull);
    snapshot(now);
}

void controllerLoop()
{
    static uint64_t prev = time_us_64();
    uint64_t now = time_us_64();
    uint64_t dt = now - prev;
    prev = now;

    if ((uint32_t)(millis() - g_core0BeatMs) < CORE0_BEAT_MAX_MS) {
        rp2040.wdt_reset();
    }

    Command c;
    while (!inFlight && queue_try_remove(&cmdQueue, &c)) {
        lastError = execute(c);
        cmdSeq++;
        snapshot(now); // status reflects the command before any reply is seen
        if (c.src == SRC_USB) {
            Reply r = {cmdSeq, lastError};
            queue_try_add(&replyQueue, &r);
        }
    }
    if (bootselAtMs && (int32_t)(millis() - bootselAtMs) >= 0 && power == PWR_DARK) {
        rp2040.rebootToBootloader();
    }
    // Commands stamp times (hvOnUs, swingT0, ...) with time_us_64(); re-read the clock so no
    // stamp is later than `now` and no unsigned difference below wraps.
    now = time_us_64();

    safety(now);
    tubeCare(now, dt);

    if (inFlight) {
        if (now - stepStartUs >= SAMPLE_AT_US) {
            finishStep();
        }
    } else {
        telemetry(now);
        if (power != PWR_DARK && pioOk) {
            if (mode == M_IDLE && power == PWR_LIT && !posValid) {
                startHome(); // re-home at the idle boundary after a mismatch
            }
            uint32_t gap;
            int dir = decide(now, &gap);
            if (gap < MIN_PERIOD_US) {
                gap = MIN_PERIOD_US;
            }
            if (dir && now - lastStepUs >= gap) {
                startStep(dir, now);
            }
        }
    }

    if (now >= nextSnapUs) {
        nextSnapUs = now + 1000;
        snapshot(now);
    }
}

bool controllerPost(const Command &c) { return queue_try_add(&cmdQueue, &c); }

bool controllerReply(Reply *r) { return queue_try_remove(&replyQueue, r); }

void controllerSnapshot(Status *s, Diag *d)
{
    critical_section_enter_blocking(&statusLock);
    *s = shared;
    if (d) {
        *d = sharedDiag;
    }
    critical_section_exit(&statusLock);
}

Command frameCommand(uint8_t src, const uint8_t *buf, int n)
{
    Command c = {};
    c.src = src;
    if (n < 2) {
        c.err = E_BAD_LEN;
        return c;
    }
    c.op = buf[0];
    c.len = buf[1];
    int want = opLength(c.op);
    if (want < 0) {
        c.err = E_BAD_OP;
    } else if (c.len != want || n != 2 + c.len || c.len > (int)sizeof(c.data)) {
        c.err = E_BAD_LEN;
    } else {
        memcpy(c.data, buf + 2, c.len);
    }
    return c;
}
