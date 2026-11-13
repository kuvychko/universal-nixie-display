// Dekatron controller/PSU bring-up firmware: switches HV_EN for Gate 2, drives the guides for
// Gate 3 and reports the HV converter's and tube drive's state. Pins and scaling: docs/hardware.md "RP2040-Zero pin assignment".
// SPDX-License-Identifier: MIT

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <hardware/adc.h>

static const uint8_t PIN_GUIDE1 = 4;     // G1 driver base (D8); R_BE holds it off in reset
static const uint8_t PIN_GUIDE2 = 5;     // G2 driver base
static const uint8_t PIN_HV_EN = 6;      // LM5156 EN/UVLO through R109; R110 pull-down (D7)
static const uint8_t PIN_PGOOD = 7;      // LM5156 PGOOD, 10k pull-up to 3V3
static const uint8_t PIN_EN_NODE = 8;    // OVP_TRIP: reads the EN/UVLO node through R112
static const uint8_t PIN_VIN_SENSE = 27; // 100k / 12k
static const uint8_t PIN_HV_SENSE = 28;  // 2.7M / (7.87k + 6.2k): HV / 192.9
static const uint8_t PIN_NDX = 26;       // index level shifter output: 2.67-2.95 V with the glow on K1
static const uint8_t PIN_RTN_SENSE = 29; // 200k / 10k: RTN / 21
static const uint8_t PIN_LED = 16;       // module WS2812

static const float ADC_VREF = 3.3f;
static const float VIN_SCALE = 112.0f / 12.0f;
static const float HV_SCALE = 192.9f;
static const float RTN_SCALE = 21.0f;
static const float NDX_HIGH_V = 2.0f; // RP2040 V_IH min at IOVDD 3.3 V (datasheet Table 625)

// 12 V +/-10 %: 10.8 V is the simulated -10 % corner (hv_500.cir); the upper bound is the
// user's choice (2026-10-24).
static const float VIN_MIN = 10.8f;
static const float VIN_MAX = 13.2f;

static const uint32_t ON_DEFAULT_S = 10;
static const uint32_t ON_MAX_S = 300;
static const uint32_t EN_BLANK_MS = 2;   // EN node settles after HV_EN rises
static const uint32_t WDT_MS = 500;

// Step limits: plan section 5 budgets <= 200 steps/s. The phase limits are only sanity bounds;
// the phase used is chosen at the bench (D8).
static const uint32_t STEP_RATE_MAX = 200;
static const uint32_t PHASE_US_MIN = 50;
static const uint32_t PHASE_US_MAX = 2000;

// Speed-sweep experiment (sweep command): test bounds for finding where the tube loses counts,
// deliberately beyond the datasheet's 1 kHz and 200 us. Not operating limits. The phase floor is
// about the guide rise time (10-21 us, hardware.md D8); the rest floor leaves time to sample NDX.
static const uint32_t SWEEP_N_MIN = 10;
static const uint32_t SWEEP_N_MAX = 20000;
static const uint32_t SWEEP_HZ_MAX = 5000;
static const uint32_t SWEEP_PHASE_MIN = 10;
static const uint32_t SWEEP_REST_MIN = 20;
static const uint32_t SWEEP_HITS_MAX = 4096;
static const uint32_t SWEEP_HITS_PER_LINE = 32;

static Adafruit_NeoPixel led(1, PIN_LED, NEO_GRB + NEO_KHZ800);

static bool hvOn = false;
static uint32_t onAtMs = 0;
static uint32_t onForMs = 0;
static float peakHv = 0.0f;
static const char *fault = "none";

static bool logging = false;
static uint32_t logEndMs = 0;
static uint32_t logPeriodMs = 0;
static uint32_t logNextMs = 0;

// Stepping: one step is G1 on -> G2 on -> G1 off -> G2 off (fwd; G2 first for rev), each
// transition phaseUs apart, so each guide is low for 2 x phaseUs and a step takes 3 x phaseUs.
static uint32_t stepsLeft = 0;
static bool stepFwd = true;
static uint32_t phaseUs = 0;
static uint32_t stepPeriodUs = 0;
static uint32_t stepNextUs = 0;
static bool ndxPending = false;
static uint32_t stepsDone = 0;
static uint32_t ndxHits = 0;

static uint16_t sweepHits[SWEEP_HITS_MAX];

static char line[64];
static size_t lineLen = 0;

static float adcVolts(uint8_t pin, int samples)
{
    uint32_t sum = 0;
    for (int i = 0; i < samples; i++) {
        sum += analogRead(pin);
    }
    return (float)sum / samples * ADC_VREF / 4095.0f;
}

static float readVin() { return adcVolts(PIN_VIN_SENSE, 8) * VIN_SCALE; }
static float readHv() { return adcVolts(PIN_HV_SENSE, 8) * HV_SCALE; }
static float readRtn() { return adcVolts(PIN_RTN_SENSE, 8) * RTN_SCALE; }
static float readNdx() { return adcVolts(PIN_NDX, 4); }

static void guidesRest()
{
    digitalWrite(PIN_GUIDE1, LOW);
    digitalWrite(PIN_GUIDE2, LOW);
    stepsLeft = 0;
    ndxPending = false;
}

static void setLed(bool on)
{
    led.setPixelColor(0, on ? led.Color(8, 0, 0) : 0);
    led.show();
}

static void hvOff()
{
    digitalWrite(PIN_HV_EN, LOW);
    hvOn = false;
    guidesRest();
    setLed(false);
}

static void trip(const char *why)
{
    hvOff();
    fault = why;
    Serial.printf("FAULT %s hv=%.1f peak=%.1f\n", why, readHv(), peakHv);
}

static void printStatus()
{
    float left = hvOn ? (onForMs - (millis() - onAtMs)) / 1000.0f : 0.0f;
    Serial.printf("OK t_ms=%lu vin=%.2f hv=%.1f peak=%.1f pgood=%d en_node=%d hv_en=%d fault=%s left=%.1f "
                  "rtn=%.1f ndx=%.2f g1=%d g2=%d steps_left=%lu steps_done=%lu ndx_hits=%lu\n",
                  (unsigned long)millis(), readVin(), readHv(), peakHv, digitalRead(PIN_PGOOD),
                  digitalRead(PIN_EN_NODE), hvOn ? 1 : 0, fault, left, readRtn(), readNdx(),
                  digitalRead(PIN_GUIDE1), digitalRead(PIN_GUIDE2), (unsigned long)stepsLeft,
                  (unsigned long)stepsDone, (unsigned long)ndxHits);
}

static void cmdOn(const char *arg)
{
    uint32_t s = ON_DEFAULT_S;
    if (*arg) {
        s = strtoul(arg, nullptr, 10);
    }
    if (s == 0 || s > ON_MAX_S) {
        Serial.printf("ERR seconds 1-%lu\n", (unsigned long)ON_MAX_S);
        return;
    }
    if (strcmp(fault, "none") != 0) {
        Serial.printf("ERR fault %s (clear first)\n", fault);
        return;
    }
    float vin = readVin();
    if (vin < VIN_MIN || vin > VIN_MAX) {
        Serial.printf("ERR vin %.2f outside %.1f-%.1f\n", vin, VIN_MIN, VIN_MAX);
        return;
    }
    peakHv = 0.0f;
    onAtMs = millis();
    onForMs = s * 1000;
    hvOn = true;
    setLed(true);
    digitalWrite(PIN_HV_EN, HIGH);
    Serial.printf("OK on %lu s\n", (unsigned long)s);
}

static void cmdGuide(const char *arg)
{
    char *end;
    uint32_t g = strtoul(arg, &end, 10);
    uint32_t on = strtoul(end, nullptr, 10);
    if ((g != 1 && g != 2) || on > 1) {
        Serial.println("ERR guide <1|2> <0|1>");
        return;
    }
    if (on && !hvOn) {
        Serial.println("ERR hv off");
        return;
    }
    if (stepsLeft || ndxPending) {
        Serial.println("ERR stepping");
        return;
    }
    // GPIO high turns the driver on: the guide is pulled from G+ to ~0 V.
    digitalWrite(g == 1 ? PIN_GUIDE1 : PIN_GUIDE2, on ? HIGH : LOW);
    Serial.printf("OK guide %lu %s\n", (unsigned long)g, on ? "on" : "rest");
}

static void cmdStep(const char *arg)
{
    char dir[8] = "";
    unsigned long n = 0, ph = 0, hz = 0;
    if (sscanf(arg, "%lu %7s %lu %lu", &n, dir, &ph, &hz) != 4 ||
        (strcmp(dir, "fwd") != 0 && strcmp(dir, "rev") != 0) || n == 0 || hz == 0 ||
        hz > STEP_RATE_MAX || ph < PHASE_US_MIN || ph > PHASE_US_MAX) {
        Serial.printf("ERR step <n> <fwd|rev> <phase_us %lu-%lu> <hz 1-%lu>\n", (unsigned long)PHASE_US_MIN,
                      (unsigned long)PHASE_US_MAX, (unsigned long)STEP_RATE_MAX);
        return;
    }
    if (3 * ph >= 1000000UL / hz) {
        Serial.println("ERR 3 x phase_us must fit in one step period");
        return;
    }
    if (!hvOn) {
        Serial.println("ERR hv off");
        return;
    }
    guidesRest();
    stepFwd = strcmp(dir, "fwd") == 0;
    phaseUs = ph;
    stepPeriodUs = 1000000UL / hz;
    stepNextUs = micros();
    stepsDone = 0;
    ndxHits = 0;
    stepsLeft = n;
    Serial.printf("OK step %lu %s %lu us %lu Hz\n", n, dir, ph, hz);
}

// One step, blocking for 3 x phaseUs (<= 6 ms, well inside the watchdog).
static void stepOnce()
{
    uint8_t first = stepFwd ? PIN_GUIDE1 : PIN_GUIDE2;
    uint8_t second = stepFwd ? PIN_GUIDE2 : PIN_GUIDE1;
    digitalWrite(first, HIGH);
    delayMicroseconds(phaseUs);
    digitalWrite(second, HIGH);
    delayMicroseconds(phaseUs);
    digitalWrite(first, LOW);
    delayMicroseconds(phaseUs);
    digitalWrite(second, LOW);
}

static uint32_t maxU32(uint32_t a, uint32_t b) { return a > b ? a : b; }

// Busy-wait until time_us_32() reaches t, feeding the watchdog (a 1 Hz sweep waits 1 s).
// Returns how late the wait ended, in us (0 if t was still ahead when called).
static uint32_t waitUntil(uint32_t t)
{
    int32_t late = (int32_t)(time_us_32() - t);
    if (late > 0) {
        return (uint32_t)late;
    }
    while ((int32_t)(time_us_32() - t) < 0) {
        rp2040.wdt_reset();
    }
    return 0;
}

// Speed-sweep experiment: n steps as one blocking burst on an absolute timetable, NDX sampled
// once per step sample_us after the second guide releases. Reports the step numbers (1-based,
// position after that step) at which NDX read high, so the host can find lost or extra steps from
// the gaps between index hits. Any received byte aborts; safety checks run every step.
static void cmdSweep(const char *arg)
{
    char dir[8] = "";
    unsigned long n = 0, ph = 0, hz = 0, sample = 0;
    int got = sscanf(arg, "%lu %7s %lu %lu %lu", &n, dir, &ph, &hz, &sample);
    if (got < 4 || (strcmp(dir, "fwd") != 0 && strcmp(dir, "rev") != 0) || n < SWEEP_N_MIN ||
        n > SWEEP_N_MAX || hz == 0 || hz > SWEEP_HZ_MAX || ph < SWEEP_PHASE_MIN || ph > PHASE_US_MAX) {
        Serial.printf("ERR sweep <n %lu-%lu> <fwd|rev> <phase_us %lu-%lu> <hz 1-%lu> [sample_us]\n",
                      (unsigned long)SWEEP_N_MIN, (unsigned long)SWEEP_N_MAX, (unsigned long)SWEEP_PHASE_MIN,
                      (unsigned long)PHASE_US_MAX, (unsigned long)SWEEP_HZ_MAX);
        return;
    }
    uint32_t period = 1000000UL / hz;
    if (period < 3 * ph + SWEEP_REST_MIN) {
        Serial.printf("ERR rest %ld us < %lu (period %lu - 3 x phase)\n", (long)period - (long)(3 * ph),
                      (unsigned long)SWEEP_REST_MIN, (unsigned long)period);
        return;
    }
    uint32_t rest = period - 3 * ph;
    if (got < 5) {
        sample = rest - 10; // just before the next step, as the step command reads it
    } else if (sample >= rest) {
        Serial.printf("ERR sample_us must be < rest %lu\n", (unsigned long)rest);
        return;
    }
    if (!hvOn) {
        Serial.println("ERR hv off");
        return;
    }
    if (stepsLeft || ndxPending) {
        Serial.println("ERR stepping");
        return;
    }
    uint32_t runMs = (uint32_t)(((uint64_t)n * period) / 1000) + 100;
    uint32_t leftMs = onForMs - (millis() - onAtMs);
    if (runMs > leftMs) {
        Serial.printf("ERR run %lu ms > hv time left %lu ms\n", (unsigned long)runMs, (unsigned long)leftMs);
        return;
    }

    guidesRest();
    uint8_t first = strcmp(dir, "fwd") == 0 ? PIN_GUIDE1 : PIN_GUIDE2;
    uint8_t second = first == PIN_GUIDE1 ? PIN_GUIDE2 : PIN_GUIDE1;
    float hvPre = readHv();
    Serial.printf("OK sweep %lu %s %lu us %lu Hz rest %lu us sample %lu us\n", n, dir, ph, hz,
                  (unsigned long)rest, sample);
    Serial.flush();

    uint32_t hits = 0;
    bool overflow = false;
    uint32_t slipMax = 0;   // lateness of guide edges and NDX samples within a step
    uint32_t startLate = 0; // lateness of a step's first edge: the previous step's work overran
    uint32_t workMax = 0;   // NDX sample plus per-step checks, us: the rest time this needs
    uint32_t pgoodLow = 0;
    // The hot loop uses the SDK directly (gpio_put/gpio_get/adc_read): digitalWrite, analogRead and
    // Serial.available() cost enough per step to slip the timetable by 46 us at 100 Hz (board 1,
    // 2026-11-12). setup()'s analogRead() calls have already set the ADC pins up.
    const uint32_t ndxHighRaw = (uint32_t)(NDX_HIGH_V / ADC_VREF * 4095.0f);
    const uint32_t vinMinRaw = (uint32_t)(VIN_MIN / VIN_SCALE / ADC_VREF * 4095.0f);
    const uint32_t vinMaxRaw = (uint32_t)(VIN_MAX / VIN_SCALE / ADC_VREF * 4095.0f);
    adc_select_input(PIN_NDX - 26);
    uint32_t done = 0;
    const char *stop = "done";
    uint32_t t = time_us_32() + 1000;
    while (done < n) {
        startLate = maxU32(startLate, waitUntil(t));
        gpio_put(first, 1);
        uint32_t slip = waitUntil(t + ph);
        gpio_put(second, 1);
        slip = maxU32(slip, waitUntil(t + 2 * ph));
        gpio_put(first, 0);
        slip = maxU32(slip, waitUntil(t + 3 * ph));
        gpio_put(second, 0);
        done++;
        slip = maxU32(slip, waitUntil(t + 3 * ph + sample));
        uint32_t workStart = time_us_32();
        // ADC, not a digital read: analogRead() has turned off GP26's digital input buffer.
        if (adc_read() > ndxHighRaw) {
            if (hits < SWEEP_HITS_MAX) {
                sweepHits[hits] = (uint16_t)done;
            } else {
                overflow = true;
            }
            hits++;
        }
        slipMax = maxU32(slipMax, slip);
        t += period;

        if (!gpio_get(PIN_PGOOD)) {
            pgoodLow++;
        }
        if (!gpio_get(PIN_EN_NODE)) {
            adc_select_input(PIN_HV_SENSE - 26); // trip() prints HV via analogRead()
            trip("en_low");
            stop = "fault";
            break;
        }
        if ((done & 0x3F) == 0) {
            // Every 64 steps: VIN, the HV timer and the serial abort.
            adc_select_input(PIN_VIN_SENSE - 26);
            uint32_t vinRaw = adc_read();
            adc_select_input(PIN_NDX - 26);
            if (vinRaw < vinMinRaw || vinRaw > vinMaxRaw) {
                adc_select_input(PIN_HV_SENSE - 26); // trip() prints HV via analogRead()
                trip("vin");
                stop = "fault";
                break;
            }
            if (millis() - onAtMs >= onForMs) {
                hvOff();
                Serial.println("OK timeout off");
                stop = "timeout";
                break;
            }
            if (Serial.available()) {
                stop = "abort"; // the byte is left for the command parser: an empty line turns HV off
                break;
            }
        }
        workMax = maxU32(workMax, time_us_32() - workStart);
    }
    guidesRest();
    // analogRead() caches the mux (_lastADCMux) and skips adc_select_input() for the pin it read
    // last: hvPre's HV_SENSE. Put the mux back there, or the next HV reads return NDX x 192.9
    // (hv_post 549.6 V with the glow on K1, board 1, 2026-11-12).
    adc_select_input(PIN_HV_SENSE - 26);
    float hvPost = readHv();

    Serial.printf("OK sweep done n=%lu done=%lu stop=%s hits=%lu overflow=%d slip_max_us=%lu start_late_us=%lu "
                  "work_max_us=%lu hv_pre=%.1f hv_post=%.1f pgood_low=%lu\n",
                  n, (unsigned long)done, stop, (unsigned long)hits, overflow ? 1 : 0, (unsigned long)slipMax,
                  (unsigned long)startLate, (unsigned long)workMax, hvPre, hvPost, (unsigned long)pgoodLow);
    uint32_t stored = min(hits, SWEEP_HITS_MAX);
    for (uint32_t i = 0; i < stored; i += SWEEP_HITS_PER_LINE) {
        Serial.print("HITS ");
        for (uint32_t j = i; j < min(stored, i + SWEEP_HITS_PER_LINE); j++) {
            Serial.printf(j == i ? "%u" : ",%u", sweepHits[j]);
        }
        Serial.println();
    }
    Serial.println("END");
}

static void cmdLog(const char *arg)
{
    char *end;
    uint32_t s = strtoul(arg, &end, 10);
    uint32_t hz = strtoul(end, nullptr, 10);
    if (hz == 0) {
        hz = 10;
    }
    if (s == 0 || s > ON_MAX_S || hz > 100) {
        Serial.println("ERR log <1-300 s> [1-100 Hz]");
        return;
    }
    Serial.println("t_ms,vin,hv,pgood,en_node,hv_en,rtn,ndx");
    logging = true;
    logPeriodMs = 1000 / hz;
    logNextMs = millis();
    logEndMs = logNextMs + s * 1000;
}

static void handleLine(char *cmd)
{
    char *arg = strchr(cmd, ' ');
    if (arg) {
        *arg++ = '\0';
    } else {
        arg = cmd + strlen(cmd);
    }
    if (logging) {
        logging = false;
        Serial.println("END");
    }
    if (strcmp(cmd, "on") == 0) {
        cmdOn(arg);
    } else if (strcmp(cmd, "off") == 0 || *cmd == '\0') {
        hvOff();
        Serial.println("OK off");
    } else if (strcmp(cmd, "status") == 0) {
        printStatus();
    } else if (strcmp(cmd, "clear") == 0) {
        fault = "none";
        peakHv = 0.0f;
        Serial.println("OK clear");
    } else if (strcmp(cmd, "guide") == 0) {
        cmdGuide(arg);
    } else if (strcmp(cmd, "step") == 0) {
        cmdStep(arg);
    } else if (strcmp(cmd, "sweep") == 0) {
        cmdSweep(arg);
    } else if (strcmp(cmd, "log") == 0) {
        cmdLog(arg);
    } else if (strcmp(cmd, "help") == 0) {
        Serial.println("OK on [s] | off | status | clear | guide <1|2> <0|1> | step <n> <fwd|rev> <phase_us> <hz> | "
                       "sweep <n> <fwd|rev> <phase_us> <hz> [sample_us] | log <s> [hz] | help");
    } else {
        Serial.printf("ERR unknown %s\n", cmd);
    }
}

void setup()
{
    // HV off and guides at rest before anything else; the reset pull-downs held them until now.
    digitalWrite(PIN_HV_EN, LOW);
    pinMode(PIN_HV_EN, OUTPUT);
    digitalWrite(PIN_GUIDE1, LOW);
    digitalWrite(PIN_GUIDE2, LOW);
    pinMode(PIN_GUIDE1, OUTPUT);
    pinMode(PIN_GUIDE2, OUTPUT);
    pinMode(PIN_PGOOD, INPUT);
    pinMode(PIN_EN_NODE, INPUT); // no pull-down: it would load EN/UVLO (Phase 1B review item 4)
    analogReadResolution(12);
    // The first read of each ADC pin sets it up and comes back low (VIN 8.5 V for 11.9 V on
    // board 1); discard it so the first status is right.
    readVin();
    readHv();
    readRtn();
    readNdx();
    led.begin();
    setLed(false);
    Serial.begin(115200);
    rp2040.wdt_begin(WDT_MS);
}

void loop()
{
    rp2040.wdt_reset();

    if (hvOn) {
        float hv = analogRead(PIN_HV_SENSE) * ADC_VREF / 4095.0f * HV_SCALE;
        if (hv > peakHv) {
            peakHv = hv;
        }
        uint32_t onMs = millis() - onAtMs;
        if (onMs >= onForMs) {
            hvOff();
            Serial.println("OK timeout off");
        } else if (onMs >= EN_BLANK_MS && digitalRead(PIN_EN_NODE) == LOW) {
            // An OVP comparator, or the JP101 shunt, holds EN low. Latch rather than let the
            // converter cycle at the trip point (Phase 1B review item 5).
            trip("en_low");
        } else if ((onMs & 0x3F) == 0) {
            float vin = readVin();
            if (vin < VIN_MIN || vin > VIN_MAX) {
                trip("vin");
            }
        }
    }

    if (ndxPending && (int32_t)(micros() - stepNextUs) >= 0) {
        // Read the index one step period after the step, just before the next one: 60 us after
        // the guides release (D9's filter settling) was too early for the glow to reach K1
        // (board 1, 2026-10-25). Read through the ADC: analogRead() turns off GP26's digital
        // input buffer, so digitalRead() would always return low.
        ndxPending = false;
        if (adcVolts(PIN_NDX, 1) > NDX_HIGH_V) {
            ndxHits++;
        }
        if (stepsLeft == 0) {
            Serial.printf("OK step done %lu ndx_hits=%lu\n", (unsigned long)stepsDone, (unsigned long)ndxHits);
        }
    } else if (!ndxPending && stepsLeft && (int32_t)(micros() - stepNextUs) >= 0) {
        stepNextUs += stepPeriodUs;
        stepOnce();
        stepsDone++;
        stepsLeft--;
        ndxPending = true;
    }

    if (logging) {
        uint32_t now = millis();
        if ((int32_t)(now - logEndMs) >= 0) {
            logging = false;
            Serial.println("END");
        } else if ((int32_t)(now - logNextMs) >= 0) {
            logNextMs += logPeriodMs;
            Serial.printf("%lu,%.2f,%.1f,%d,%d,%d,%.1f,%.2f\n", (unsigned long)now, readVin(), readHv(),
                          digitalRead(PIN_PGOOD), digitalRead(PIN_EN_NODE), hvOn ? 1 : 0, readRtn(),
                          readNdx());
        }
    }

    while (Serial.available()) {
        int c = Serial.read();
        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            line[lineLen] = '\0';
            handleLine(line);
            lineLen = 0;
        } else if (lineLen < sizeof(line) - 1) {
            line[lineLen++] = (char)c;
        }
    }
}
