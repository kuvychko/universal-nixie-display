// Dekatron controller/PSU bring-up firmware: switches HV_EN for Gate 2, drives the guides for
// Gate 3 and reports the HV converter's and tube drive's state. Pins and scaling: docs/hardware.md "RP2040-Zero pin assignment".
// SPDX-License-Identifier: MIT

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

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
    } else if (strcmp(cmd, "log") == 0) {
        cmdLog(arg);
    } else if (strcmp(cmd, "help") == 0) {
        Serial.println("OK on [s] | off | status | clear | guide <1|2> <0|1> | step <n> <fwd|rev> <phase_us> <hz> | "
                       "log <s> [hz] | help");
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
