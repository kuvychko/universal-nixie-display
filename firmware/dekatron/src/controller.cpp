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
static uint32_t stepSampleAtUs, stepRecheckAtUs, stepPeriodUs; // the step in flight's timing
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
// sweep (bounce)
static int32_t sweepLo, sweepHi;
static int8_t sweepDir;
static uint32_t sweepIntervalUs, sweepLoDwellUs, sweepHiDwellUs;
// spin / exercise
static int32_t spinStepsLeft;
static uint16_t spinAccel;
static uint64_t exerciseEndUs;
static uint8_t returnPos;
// wedge (wedge, centred wedge, gauge)
static int32_t wedgeLo, wedgeHi;      // absolute positions of the bookend cathodes
static uint8_t wedgeLoPct, wedgeHiPct; // share of each bookend cathode inside the wedge, 1-100
static uint32_t wedgeIntervalUs;
static int8_t wedgeDir;
static float wedgeAccLo, wedgeAccHi;   // fractional visits owed to a bookend below the minimum dwell
static uint32_t stepSeq;               // increments on every step
static uint32_t wedgePlanSeq;          // stepSeq the plan below was made for
static bool wedgePlanValid;
static int8_t wedgePlanDir;
static uint32_t wedgePlanGapUs;

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
static uint16_t missNdxRaw;
static uint16_t idxLate, lateNdxRaw; // first sample disagreed, the recheck agreed
static int8_t missExpected = -1, missMode = -1, rehomeOffset = -1;
static bool rehoming; // the current home follows a mismatch: report the count's offset
static uint8_t homeAttempts;

// periodic index check: a short trip to K1 when the count has gone unconfirmed too long
static uint16_t indexCheckMs = INDEX_CHECK_MS_DEFAULT;
static uint16_t indexOpenMs = INDEX_CHECK_OPEN_MS_DEFAULT;
static uint32_t uncheckedSteps;   // every step since the last K1 that matched the count
static uint32_t uncheckedOwnSteps; // the same without trip steps: only these arm a trip
static uint64_t uncheckedSinceUs; // first own step after the last check
static uint32_t maxUncheckedSteps;
static uint64_t maxUncheckedUs;
static uint16_t tripCount;
static bool tripActive, tripOutbound;
static int32_t tripHome; // absPos the trip returns to
static uint64_t dwellFromUs; // start of the last non-trip step: tube care ignores trips
static int32_t wedgeStartC = -1, wedgeEndC = -1; // last wedge bookends, 0.01 cathode, for update size

// skip recovery: re-home, then resume what was showing
enum ResumeKind : uint8_t { R_NONE, R_QUEUE, R_CMD, R_EXERCISE };
static bool recovering;
static uint8_t resumeKind;
static Command resumeCmd;
static uint8_t resumeAt;   // R_QUEUE: ring position the queue counts from (the count's view)
static int32_t resumeQueue; // R_QUEUE: steps still to play from there
static Command lastEffectCmd; // the command behind the running wedge/swing/bounce/rotate
static uint64_t mismatchAtUs;
static uint16_t skips, senseMisses, recoveryFailures;
static int8_t lastSkip;
static int32_t recoveryMs = -1;

// bench hooks (USB console only)
static bool dropPending;
static uint64_t dropAtUs;
static int32_t dropDetectMs = -1;
static uint64_t blindUntilUs;

// ---- helpers ----
static uint8_t ringOf(int32_t p) { return (uint8_t)(((p % 10) + 10) % 10); }
static uint8_t posMod() { return ringOf(absPos); }

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
    tripActive = false;
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
    recovering = false;
    resumeKind = R_NONE;
    setIdle();
}

// ---- periodic index check ----
static void noteUnchecked(uint64_t now)
{
    if (!posValid || power != PWR_LIT) {
        return;
    }
    if (uncheckedSteps > maxUncheckedSteps) {
        maxUncheckedSteps = uncheckedSteps;
    }
    if (uncheckedOwnSteps && now > uncheckedSinceUs && now - uncheckedSinceUs > maxUncheckedUs) {
        maxUncheckedUs = now - uncheckedSinceUs;
    }
}

static void markChecked(uint64_t now)
{
    noteUnchecked(now);
    uncheckedSteps = uncheckedOwnSteps = 0;
    uncheckedSinceUs = now;
}

// 0 not due, 1 in the band (trip at a cheap moment), 2 at the limit (trip now).
static int checkDue(uint64_t now)
{
    if (indexCheckMs == 0 || tripActive || recovering || !posValid || power != PWR_LIT || mode == M_HOME ||
        uncheckedOwnSteps == 0 || posMod() == 0 || now < uncheckedSinceUs) {
        return 0;
    }
    uint64_t t = now - uncheckedSinceUs, limit = indexCheckMs * 1000ull;
    return t >= limit ? 2 : t >= indexOpenMs * 1000ull ? 1 : 0;
}

static bool nearK1() { return abs(shortest(posMod(), 0)) <= CHEAP_TRIP_STEPS; }

static int32_t ringDistC(int32_t a, int32_t b)
{
    int32_t d = abs(a - b) % 1000;
    return d > 500 ? 1000 - d : d;
}

static void startTrip()
{
    tripActive = true;
    tripOutbound = true;
    tripHome = absPos;
}

// Next trip step, or 0 when back where it started (the trip is then over).
static int tripStep()
{
    if (tripOutbound && posMod() == 0) {
        tripOutbound = false; // the arrival's index sample confirmed K1 (or recovery took over)
    }
    if (tripOutbound) {
        return shortest(posMod(), 0) > 0 ? 1 : -1;
    }
    if (absPos == tripHome) {
        tripActive = false;
        tripCount++;
        return 0;
    }
    return tripHome > absPos ? 1 : -1;
}

static void setFault(uint8_t f)
{
    fault = f;
    goDark(DR_FAULT);
}

static void startHome()
{
    setIdle();
    mode = M_HOME;
    posValid = false;
    homeConfirming = false;
    homeSteps = homeConfirm = 0;
    homeAttempts = 1;
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

// Wedge over the ring interval [start, start + width) in 0.01 cathode, cathode k spanning
// k.00-k.99. It sweeps back and forth between the bookend cathodes. A running wedge is
// updated in place: the sweep carries on from where the glow is, in the direction it is going.
static void setWedge(int32_t start, int32_t width, uint16_t rate)
{
    bool wasWedge = mode == M_WEDGE;
    start = ((start % 1000) + 1000) % 1000;
    int32_t end = start + width;
    int32_t loCell = start / 100;
    int32_t hiCell = (end + 99) / 100 - 1;
    if (hiCell < loCell) {
        hiCell = loCell;
    }
    uint8_t loPct = (uint8_t)((loCell + 1) * 100 - start);
    uint8_t hiPct = (uint8_t)(end - hiCell * 100);
    if (loCell == hiCell) {
        loPct = hiPct = 100;
    }
    // Place it on the ring copy nearest the glow, so an update never walks the long way round.
    int32_t span = hiCell - loCell;
    int32_t lo = absPos + ((loCell - posMod() + 10) % 10), best = lo;
    int32_t bestDist = INT32_MAX;
    const int32_t cands[] = {lo, lo - 10};
    for (int32_t cand : cands) {
        int32_t dist = absPos < cand ? cand - absPos : absPos > cand + span ? absPos - cand - span : 0;
        if (dist < bestDist) {
            bestDist = dist;
            best = cand;
        }
    }
    if (mode != M_WEDGE) {
        setIdle();
        mode = M_WEDGE;
        wedgeDir = 1;
        wedgeAccLo = wedgeAccHi = 0;
    }
    wedgeLo = best;
    wedgeHi = best + span;
    wedgeLoPct = loPct;
    wedgeHiPct = hiPct;
    wedgeIntervalUs = 1000000UL / rate;
    wedgePlanValid = false;
    // A streamed update that moves the sector a lot hides a trip inside the change.
    int32_t endC = (start + width) % 1000;
    bool big = wedgeStartC >= 0 && ringDistC(start, wedgeStartC) + ringDistC(endC, wedgeEndC) >= CHEAP_UPDATE_CENTI;
    wedgeStartC = start;
    wedgeEndC = endC;
    if (wasWedge && big && checkDue(time_us_64()) >= 1) {
        startTrip();
    }
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
// Internal result: a valid motion command that arrived during a recovery, held until the re-home
// is done (the master sees E_OK).
static const uint8_t E_DEFER = 0xFE;

static uint8_t needMotion()
{
    if (recovering && power == PWR_LIT) {
        return E_DEFER;
    }
    if (power != PWR_LIT || !posValid) {
        return E_STATE;
    }
    return E_OK;
}

static uint8_t executeOp(const Command &c)
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
    if (c.op == OP_INJECT) {
        if (c.src != SRC_USB) {
            return E_BAD_OP;
        }
        if (c.data[0] == 1) {
            dropPending = true;
        } else if (c.data[0] == 2) {
            blindUntilUs = time_us_64() + INJECT_BLIND_US;
        } else {
            return E_RANGE;
        }
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
        rehoming = false; // a strike's home has no count to compare
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
        if (recovering && power == PWR_LIT) {
            return E_DEFER;
        }
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
    case OP_WEDGE: {
        uint16_t a = rd16(d), b = rd16(d + 2), r = rd16(d + 4);
        if (a > 999 || b > 999 || r == 0 || r > MAX_RATE) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        int32_t w = ((int32_t)b - a + 1000) % 1000;
        setWedge(a, w ? w : 1000, r); // equal bookends: the whole ring
        return E_OK;
    }
    case OP_WEDGE_CENTRED: {
        uint16_t h = rd16(d + 1), r = rd16(d + 3);
        if (d[0] > 9 || h > 500 || r == 0 || r > MAX_RATE) {
            return E_RANGE;
        }
        if ((e = needMotion())) {
            return e;
        }
        setWedge(d[0] * 100 + 50 - h, h ? 2 * h : 1, r);
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
        setWedge(0, v ? v : 1, MAX_RATE);
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
    case OP_SET_INDEX_CHECK: {
        uint16_t open = rd16(d), limit = rd16(d + 2);
        if (limit > 60000 || open > limit) {
            return E_RANGE;
        }
        indexOpenMs = open;
        indexCheckMs = limit;
        return E_OK;
    }
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

static bool isEffect(uint8_t op)
{
    return op == OP_WEDGE || op == OP_WEDGE_CENTRED || op == OP_GAUGE || op == OP_SWING || op == OP_BOUNCE ||
           op == OP_ROTATE;
}

// A motion command during a recovery replaces what resumes afterwards; the last one wins.
static uint8_t deferResume(const Command &c)
{
    if (c.op == OP_MOVE_RELATIVE) {
        int32_t n = (int16_t)rd16(c.data);
        if (resumeKind != R_QUEUE) {
            resumeKind = R_QUEUE;
            resumeQueue = 0; // resumeAt: where the count stood at the mismatch
        }
        if (resumeQueue + n > QUEUE_MAX || resumeQueue + n < -QUEUE_MAX) {
            return E_QUEUE_FULL;
        }
        resumeQueue += n;
    } else if (c.op == OP_STOP) {
        resumeKind = R_QUEUE; // hold where the display was meant to be
        resumeQueue = 0;
    } else {
        resumeKind = R_CMD;
        resumeCmd = c;
    }
    return E_OK;
}

static uint8_t execute(const Command &c)
{
    uint8_t e = executeOp(c);
    if (e == E_DEFER) {
        e = deferResume(c);
    }
    if (e == E_OK && isEffect(c.op)) {
        lastEffectCmd = c;
    }
    return e;
}

// ---- stepping ----
// Trip steps (periodic index check) move the glow and are index-checked like any other, but they
// leave the effect, the queue, the step-rate bins and the hold-limit dwell alone, and they do not
// advance stepSeq, so a wedge resumes on the plan it had.
static void startStep(int dir, uint64_t now)
{
    bool drop = false;
    if (!tripActive) {
        uint64_t gap = now - dwellFromUs;
        verySlowUs = gap >= VERY_SLOW_GAP_US ? verySlowUs + gap : 0;
        dwellFromUs = now;
        stepSeq++;
        rateBins[rateSec % 10]++;
        if (uncheckedOwnSteps++ == 0) {
            uncheckedSinceUs = now; // the unchecked clock starts with the first step since the check
        }
        if (mode == M_QUEUE) {
            queuePending -= dir;
        } else if (mode == M_SPIN || mode == M_ROTATE || mode == M_EXERCISE) {
            acc -= dir;
            if (mode == M_SPIN) {
                spinStepsLeft--;
            }
        }
        if (dropPending && posValid && mode != M_HOME) {
            dropPending = false; // bench hook: count a step the tube is never given
            drop = true;
            dropAtUs = now;
        }
    }
    // The next step waits out this one's full period (guides + rest), whichever timing it uses.
    stepPeriodUs = tripActive ? TRIP_PERIOD_US : MIN_PERIOD_US;
    stepSampleAtUs = tripActive ? TRIP_SAMPLE_AT_US : SAMPLE_AT_US;
    stepRecheckAtUs = tripActive ? TRIP_RECHECK_AT_US : RECHECK_AT_US;
    if (!drop) {
        stepperStart(dir, tripActive ? TRIP_PHASE_US : PHASE_US);
    }
    absPos += dir;
    uncheckedSteps++;
    stepStartUs = lastStepUs = now;
    inFlight = true;
}

static uint16_t readNdx()
{
    adc_select_input(pin::NDX - 26);
    uint16_t v = adc_read();
    return time_us_64() < blindUntilUs ? 0 : v; // bench hook: index blinded
}

// A mismatch: remember what was showing, in ring coordinates as the count saw it, and re-home at
// once. The display is not mission critical, so nothing latches: the effect resumes afterwards.
static void beginRecovery(uint64_t now)
{
    noteUnchecked(now);
    resumeAt = tripActive ? ringOf(tripHome) : posMod();
    resumeQueue = 0;
    switch (mode) {
    case M_WEDGE:
    case M_SWING:
    case M_BOUNCE:
    case M_ROTATE:
        resumeKind = R_CMD; // ring coordinates: re-anchors after the home
        resumeCmd = lastEffectCmd;
        break;
    case M_SPIN:
        resumeKind = R_QUEUE; // the rest of the spin is dropped: back to where it started
        resumeAt = returnPos;
        break;
    case M_EXERCISE:
        resumeKind = R_EXERCISE; // same end time, then back to returnPos
        break;
    case M_QUEUE:
        resumeKind = R_QUEUE;
        resumeQueue = queuePending;
        break;
    default:
        resumeKind = R_QUEUE; // a held position: back to it
        break;
    }
    recovering = true;
    rehoming = true;
    rehomeOffset = -1;
    mismatchAtUs = now;
    startHome(); // clears the effect and any trip
}

static void finishRecovery(uint64_t now)
{
    recovering = false;
    if (rehomeOffset == 0) {
        senseMisses++; // the glow was where it was counted
    } else if (rehomeOffset > 0) {
        skips++;
        lastSkip = (int8_t)shortest(0, (uint8_t)rehomeOffset); // count minus truth
    }
    recoveryMs = (int32_t)((now - mismatchAtUs) / 1000);
    uint8_t kind = resumeKind;
    resumeKind = R_NONE;
    if (kind == R_QUEUE) {
        int32_t n = resumeQueue + shortest(0, resumeAt);
        mode = M_QUEUE;
        queuePending = n > QUEUE_MAX ? QUEUE_MAX : n < -QUEUE_MAX ? -QUEUE_MAX : n;
    } else if (kind == R_CMD) {
        Command c = resumeCmd;
        c.src = owner == OWN_I2C ? SRC_I2C : SRC_USB;
        if (execute(c) == E_OK && (c.op == OP_SPIN || c.op == OP_EXERCISE)) {
            returnPos = resumeAt;
        }
    } else if (kind == R_EXERCISE) {
        startRotate((float)EXERCISE_RATE, M_EXERCISE);
        rate = EXERCISE_RATE;
    }
}

static void finishStep()
{
    uint64_t now = time_us_64();
    inFlight = false;
    ndxRaw = readNdx();
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
                if (rehoming) {
                    rehomeOffset = (int8_t)posMod();
                    rehoming = false;
                }
                absPos = 0;
                markChecked(now); // before posValid: the homing steps are not an unchecked stretch
                posValid = true;
                setIdle();
                if (power == PWR_STRIKING) {
                    power = PWR_LIT;
                    verySlowUs = 0;
                }
                if (recovering) {
                    finishRecovery(now);
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
            if (homeAttempts < RECOVERY_ATTEMPTS) {
                homeAttempts++; // try again from here; nothing is latched
                homeSteps = homeConfirm = 0;
                homeConfirming = false;
            } else {
                recoveryFailures++;
                goDark(DR_INDEX_LOST); // the master may LIGHT again: strike and home as usual
            }
        }
        return;
    }
    if (posValid) {
        bool expected = posMod() == 0;
        if (hit != expected) {
            // Recheck just before the earliest next step: a glow that settles on K1 later than
            // the first sample is not a lost step (bench 2026-11-13: 0.29 V at 100 us, the glow
            // on K1 at the re-home). Counted, so the margin stays visible.
            busy_wait_until(from_us_since_boot(stepStartUs + stepRecheckAtUs));
            uint16_t again = readNdx();
            if ((again > NDX_HIGH_RAW) == expected) {
                idxLate++;
                lateNdxRaw = ndxRaw;
                ndxRaw = again;
                hit = expected;
            }
        }
        idxExpected += expected;
        idxObserved += hit;
        if (hit != expected) {
            idxMismatches++;
            missNdxRaw = ndxRaw;
            missExpected = expected;
            missMode = (int8_t)mode;
            if (dropAtUs) {
                dropDetectMs = (int32_t)((now - dropAtUs) / 1000);
                dropAtUs = 0;
            }
            beginRecovery(now);
        } else if (expected) {
            markChecked(now); // K1 where the count said: the count is confirmed
        }
    }
}

// Wedge brightness. A step spends TRANSIT_US on the guides, so a cathode glows for the gap minus
// that. Interior cathodes are passed twice per sweep cycle, glowing 2 * (interval - transit); a
// bookend is visited once, so it dwells for its share of that plus the transit. Below the minimum
// step period a bookend is visited on only some cycles instead (error diffusion), and the sweep
// turns at its neighbour, which then dwells as a full bookend.
static const uint32_t TRANSIT_US = 3 * PHASE_US;

static uint32_t wedgeEndDwell(uint8_t pct)
{
    return TRANSIT_US + (uint32_t)((2ull * (wedgeIntervalUs - TRANSIT_US) * pct) / 100);
}

// Visit the bookend this cycle? Called once per arrival at its neighbour.
static bool wedgeVisit(uint8_t pct, float *accum, bool canSkip)
{
    uint32_t want = wedgeEndDwell(pct);
    if (want >= MIN_PERIOD_US || !canSkip) {
        return true;
    }
    *accum += (float)(want - TRANSIT_US) / (MIN_PERIOD_US - TRANSIT_US);
    if (*accum >= 1.0f) {
        *accum -= 1.0f;
        return true;
    }
    return false;
}

static int decideWedge(uint32_t *gapUs)
{
    uint32_t iv = wedgeIntervalUs;
    if (absPos < wedgeLo || absPos > wedgeHi) {
        *gapUs = iv; // walk in, e.g. after an update moved the wedge
        wedgeDir = absPos < wedgeLo ? 1 : -1;
        return wedgeDir;
    }
    if (wedgeLo == wedgeHi) {
        return 0; // one cathode: a held glow, under the hold limit like any other
    }
    if (wedgePlanValid && wedgePlanSeq == stepSeq) {
        *gapUs = wedgePlanGapUs;
        return wedgePlanDir;
    }
    int8_t dir = wedgeDir;
    uint32_t gap = iv;
    if (absPos == wedgeHi) {
        dir = -1;
        gap = wedgeEndDwell(wedgeHiPct);
    } else if (absPos == wedgeLo) {
        dir = 1;
        gap = wedgeEndDwell(wedgeLoPct);
    } else if (dir > 0 && absPos + 1 == wedgeHi && !wedgeVisit(wedgeHiPct, &wedgeAccHi, true)) {
        dir = -1;
        gap = wedgeEndDwell(100);
    } else if (dir < 0 && absPos - 1 == wedgeLo && !wedgeVisit(wedgeLoPct, &wedgeAccLo, true)) {
        dir = 1;
        gap = wedgeEndDwell(100);
    }
    if (gap < MIN_PERIOD_US) {
        gap = MIN_PERIOD_US;
    }
    wedgeDir = dir;
    wedgePlanSeq = stepSeq;
    wedgePlanValid = true;
    wedgePlanDir = dir;
    wedgePlanGapUs = gap;
    *gapUs = gap;
    return dir;
}

// Next step direction for the current mode, or 0; *gapUs is the minimum time since the last step.
static int decide(uint64_t now, uint32_t *gapUs)
{
    *gapUs = MIN_PERIOD_US;
    if (tripActive) {
        int d = tripStep();
        if (d) {
            *gapUs = TRIP_PERIOD_US; // trip timing, whatever the effect's rate
            return d;
        }
    }
    switch (mode) {
    case M_HOME:
        *gapUs = 1000000UL / HOME_RATE;
        return 1;
    case M_QUEUE:
        if (queuePending == 0) {
            if (checkDue(now) >= 1 && nearK1()) {
                startTrip(); // the end of a queue near K1: a short trip before the hold
                return tripStep();
            }
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
    case M_WEDGE:
        return decideWedge(gapUs);
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
        uint64_t dwell = now - dwellFromUs;
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
              (wdtReset ? FL_WATCHDOG_RESET : 0) | (recovering ? FL_RECOVERING : 0);
    s.position = posMod();
    s.mode = mode;
    s.queue = (int16_t)(queuePending > 32767 ? 32767 : queuePending < -32767 ? -32767 : queuePending);
    s.idx_expected = idxExpected;
    s.idx_observed = idxObserved;
    s.home_failures = homeFailures;
    s.idx_mismatches = idxMismatches;
    s.dwell_ms = power == PWR_DARK ? 0 : (uint32_t)((now - dwellFromUs) / 1000);
    s.rate_dsps = (uint16_t)stepsLast10s(); // steps per 10 s = 0.1 steps/s
    s.slow_run_s = (uint32_t)(slowRunUs / 1000000ull);
    s.hv_dv = (uint16_t)(fmaxf(hvV, 0) * 10 + 0.5f);
    s.vin_dv = (uint16_t)(fmaxf(vinV, 0) * 10 + 0.5f);
    s.rtn_dv = (uint16_t)(fmaxf(rtnV, 0) * 10 + 0.5f);
    s.skips = skips;
    s.sense_misses = senseMisses;
    s.idx_late = idxLate;
    s.recovery_failures = recoveryFailures;
    s.last_skip = lastSkip;
    s.trips = tripCount;
    noteUnchecked(now);
    bool live = posValid && power == PWR_LIT && uncheckedOwnSteps && now >= uncheckedSinceUs;
    critical_section_enter_blocking(&statusLock);
    shared = s;
    sharedDiag.ndx_raw = ndxRaw;
    sharedDiag.pio_ok = pioOk;
    sharedDiag.miss_ndx_raw = missNdxRaw;
    sharedDiag.late_ndx_raw = lateNdxRaw;
    sharedDiag.miss_expected = missExpected;
    sharedDiag.miss_mode = missMode;
    sharedDiag.rehome_offset = rehomeOffset;
    sharedDiag.index_open_ms = indexOpenMs;
    sharedDiag.index_check_ms = indexCheckMs;
    sharedDiag.unchecked_steps = live ? uncheckedSteps : 0;
    sharedDiag.unchecked_ms = live ? (uint32_t)((now - uncheckedSinceUs) / 1000) : 0;
    sharedDiag.max_unchecked_steps = maxUncheckedSteps;
    sharedDiag.max_unchecked_ms = (uint32_t)(maxUncheckedUs / 1000);
    sharedDiag.drop_detect_ms = dropDetectMs;
    sharedDiag.recovery_ms = recoveryMs;
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
    lastStepUs = lastTickUs = dwellFromUs = uncheckedSinceUs = now;
    stepPeriodUs = MIN_PERIOD_US;
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
        if (now - stepStartUs >= stepSampleAtUs) {
            finishStep();
        }
    } else {
        telemetry(now);
        if (power != PWR_DARK && pioOk) {
            if (mode == M_IDLE && power == PWR_LIT && !posValid) {
                startHome(); // safety net: lit without a position always re-homes
            }
            if (checkDue(now) == 2) {
                startTrip(); // overdue: a short trip to K1, whatever is showing
            }
            uint32_t gap;
            int dir = decide(now, &gap);
            if (gap < stepPeriodUs) {
                gap = stepPeriodUs; // the previous step's guides and rest come first
            }
            if (dir && now - lastStepUs >= gap) {
                bool towardK1 = (shortest(posMod(), 0) > 0) == (dir > 0); // gets there by itself
                if (!tripActive && checkDue(now) >= 1 && nearK1() && !towardK1) {
                    // In the band and the glow next to K1: a trip of a step or two, beside the lit
                    // part, instead of a streak across the dark one.
                    startTrip();
                    dir = tripStep();
                }
                if (dir) {
                    startStep(dir, now);
                }
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
