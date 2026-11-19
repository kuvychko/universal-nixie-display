// Nixie board bring-up firmware: switches the HV module's 12 V (NIX12_EN) for Gates 2 and 4,
// shifts and reads back HV5622 frames for Gate 3, lights tubes for Gate 5 and probes the ES100
// for Gate 6. Pins and scaling: docs/hardware.md "Nixie board electrical design".
// SPDX-License-Identifier: MIT

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Wire.h>

static const uint8_t PIN_NIX12_EN = 0;  // Q102 base -> Q101 gate; R104 holds it off in reset
static const uint8_t PIN_SPARE = 1;     // NIX_SPARE, hardware pull-down; read only
static const uint8_t PIN_MAIN_SDA = 2;  // main bus (I2C1 target in the product): left as inputs
static const uint8_t PIN_MAIN_SCL = 3;
static const uint8_t PIN_WWVB_SDA = 4;  // I2C0, ES100 only (10k pull-ups on the carrier)
static const uint8_t PIN_WWVB_SCL = 5;
static const uint8_t PIN_WWVB_EN = 6;   // R308 10k pull-down: ES100 in shutdown in reset
static const uint8_t PIN_WWVB_IRQ = 7;  // R307 10k pull-up, active low
static const uint8_t PIN_BL = 8;        // DRV_BL via U302; R301 / R310 pull-downs: dark in reset
static const uint8_t PIN_LE = 9;        // DRV_LE via U302: high loads the latches
static const uint8_t PIN_CLK = 10;      // DRV_CLK via U302: the HV5622 shifts on the falling edge
static const uint8_t PIN_DATA = 11;     // DRV_DATA via U302
static const uint8_t PIN_DOUT = 12;     // U203 DATA OUT through R314 / R315 (2.43-3.39 V high)
static const uint8_t PIN_ENC_A = 13;    // PEC11R filter, 10k pull-ups
static const uint8_t PIN_ENC_B = 14;
static const uint8_t PIN_ENC_SW = 15;
static const uint8_t PIN_LED = 16;      // module WS2812
static const uint8_t PIN_HV_SENSE = 26; // NIX_HV_SENSE: 1M / 12k, ratio 84.3
static const uint8_t PIN_SW12_SENSE = 27; // NIX12_SENSE: +12V_SW through 100k / 12k

static const float ADC_VREF = 3.3f;
static const float HV_SCALE = 1012.0f / 12.0f;
static const float SW12_SCALE = 112.0f / 12.0f;

// HV cut-off: NIX12_EN dropped above 200 V (user, 2026-11-06; HV5622 outputs 220 V maximum).
// The threshold can be lowered for the Gate 4 test and returns to 200 V at every reset.
static const float HV_TRIP_MAX = 200.0f;
static const float HV_TRIP_MIN = 20.0f;

// Switched 12 V check: the soft start delays the rail by 34-57 ms and ramps it in 5.5-7.3 ms
// (simulation, hardware.md), so it is checked from 200 ms after NIX12_EN. 10.8 V is 12 V - 10 %,
// the dekatron board's VIN window and the HV5622's VDD minimum.
static const uint32_t SW12_SETTLE_MS = 200;
static const float SW12_MIN = 10.8f;

static const uint32_t ON_DEFAULT_S = 10;
static const uint32_t ON_MAX_S = 3600; // long enough for the Gate 5b warm-up run
static const uint32_t WDT_MS = 500;

// Driver chain: U201 -> U202 -> U203, 96 bits. Each falling CLK edge moves DATA IN into bit 1
// (HVOUT1); DATA OUT is bit 32 (HV5622 DS20005854A, Table 3-2). The first bit sent ends at U203
// HVOUT32, the last at U201 HVOUT1. A 2 us half period (250 kHz) leaves U302's 300-600 ns
// propagation and the readback divider's settling well inside each half (<= 1 MHz, hardware.md).
static const uint32_t HALF_US = 2;
static const int CHIPS = 3;

// HV_MAP (tools/gen_nixie_schematics.py, table in hardware.md): HVOUT number per element, the
// same on every chip. Index 0-9 = digits K0-K9, 10 = left point, 11 = right point.
// Side a = the chip's left tube (odd tube number), b = its right tube.
static const uint8_t MAP_A[12] = {12, 7, 8, 10, 11, 13, 14, 16, 17, 15, 6, 9};
static const uint8_t MAP_B[12] = {28, 23, 20, 18, 19, 21, 22, 24, 25, 27, 26, 29};
static const char ELEMENT_NAMES[] = "0123456789LR";

// ES100 (data sheet v0.97): address 0x32, device ID register 0x0D = 0x10; wakeup 1.0 ms typ.
// after EN rises (no maximum given), so the probe waits 100 ms.
static const uint8_t ES100_ADDR = 0x32;
static const uint8_t ES100_REG_ID = 0x0D;
static const uint8_t ES100_ID = 0x10;
static const uint32_t ES100_WAKE_MS = 100;

static Adafruit_NeoPixel led(1, PIN_LED, NEO_GRB + NEO_KHZ800);

static bool hvOn = false;
static uint32_t onAtMs = 0;
static uint32_t onForMs = 0;
static float peakHv = 0.0f;
static float hvTrip = HV_TRIP_MAX;
static const char *fault = "none";

static uint32_t shifted[CHIPS];   // last frame shifted in (what the next readback must return)
static uint32_t latched[CHIPS];   // last frame latched to the outputs
static bool knownShifted = false; // shifted[] is valid (a frame has gone through since boot)
static bool chainOk = false;      // readback has confirmed the chain since boot

static uint8_t blDuty = 0;        // 0 = blanked, 255 = on, between = PWM
static uint32_t pwmHz = 20000;    // reference design's 20 kHz (hardware.md, Dimming); set at bring-up

static bool cycling = false;
static uint32_t cycleMs = 0;
static uint32_t cycleNextMs = 0;
static int cycleEl = 0;

static bool logging = false;
static uint32_t logEndMs = 0;
static uint32_t logPeriodMs = 0;
static uint32_t logNextMs = 0;

static bool wireStarted = false;

static char line[96];
static size_t lineLen = 0;

static float adcVolts(uint8_t pin, int samples)
{
    uint32_t sum = 0;
    for (int i = 0; i < samples; i++) {
        sum += analogRead(pin);
    }
    return (float)sum / samples * ADC_VREF / 4095.0f;
}

static float readHv() { return adcVolts(PIN_HV_SENSE, 4) * HV_SCALE; }
static float readSw12() { return adcVolts(PIN_SW12_SENSE, 4) * SW12_SCALE; }

static void setLed()
{
    led.setPixelColor(0, hvOn ? led.Color(8, 0, 0) : 0);
    led.show();
}

// ---- blanking and PWM ---------------------------------------------------------------------------

static void blWrite(uint8_t duty)
{
    if (duty == 0 || duty == 255) {
        pinMode(PIN_BL, OUTPUT); // takes the pin back from the PWM slice
        digitalWrite(PIN_BL, duty ? HIGH : LOW);
    } else {
        analogWriteFreq(pwmHz);
        analogWriteRange(255);
        analogWrite(PIN_BL, duty);
    }
    blDuty = duty;
}

// ---- HV and faults --------------------------------------------------------------------------------

static void hvOff()
{
    digitalWrite(PIN_NIX12_EN, LOW);
    hvOn = false;
    setLed();
}

static void trip(const char *why)
{
    hvOff();
    blWrite(0);
    cycling = false;
    fault = why;
    Serial.printf("FAULT %s hv=%.1f peak=%.1f sw12=%.2f\n", why, readHv(), peakHv, readSw12());
}

// HV cut-off, whatever NIX12_EN's state: above the threshold the switch is opened and the fault
// latched. Called from loop() and from the commands that block it (chain, es100).
static void hvGuard()
{
    float hv = readHv();
    if (hvOn && hv > peakHv) {
        peakHv = hv;
    }
    if (hv > hvTrip && strcmp(fault, "none") == 0) {
        trip("hv_over");
    }
}

// ---- driver chain ---------------------------------------------------------------------------------

// Shift a 96-bit frame (out[c] bit n-1 = U20(1+c) HVOUTn), read the previous one back from
// DATA OUT into back[], and pulse LE if latch. DATA changes with the rising CLK edge; the HV5622
// samples it on the falling edge, a half period later. DATA OUT is read just before each falling
// edge, when it holds bit 32 of the last chip: the oldest bit of the previous frame.
static void shiftFrame(const uint32_t out[CHIPS], uint32_t back[CHIPS], bool latch)
{
    const uint32_t mask = (1u << PIN_CLK) | (1u << PIN_DATA);
    for (int c = 0; c < CHIPS; c++) {
        back[c] = 0;
    }
    for (int c = CHIPS - 1; c >= 0; c--) {
        for (int n = 32; n >= 1; n--) {
            uint32_t bit = (out[c] >> (n - 1)) & 1u;
            gpio_put_masked(mask, (1u << PIN_CLK) | (bit << PIN_DATA));
            busy_wait_us_32(HALF_US);
            if (gpio_get(PIN_DOUT)) {
                back[c] |= 1u << (n - 1);
            }
            gpio_put(PIN_CLK, 0);
            busy_wait_us_32(HALF_US);
        }
    }
    gpio_put(PIN_DATA, 0);
    if (latch) {
        gpio_put(PIN_LE, 1);
        busy_wait_us_32(HALF_US);
        gpio_put(PIN_LE, 0);
        busy_wait_us_32(HALF_US);
    }
}

static bool frameEq(const uint32_t a[CHIPS], const uint32_t b[CHIPS])
{
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2];
}

static void printFrame(const char *label, const uint32_t f[CHIPS])
{
    Serial.printf(" %s=%08lx,%08lx,%08lx", label, (unsigned long)f[0], (unsigned long)f[1], (unsigned long)f[2]);
}

// Shift and latch a frame, checking the readback against the frame shifted before it. On a
// mismatch the tubes are blanked and BL stays locked until "blank" passes again.
static bool showFrame(const uint32_t f[CHIPS])
{
    uint32_t back[CHIPS];
    shiftFrame(f, back, true);
    bool ok = !knownShifted || frameEq(back, shifted);
    bool checked = knownShifted;
    if (checked && !ok) {
        chainOk = false;
        blWrite(0);
        cycling = false;
        Serial.print("FAULT readback");
        printFrame("expected", shifted);
        printFrame("got", back);
        Serial.println(" (BL low; run blank)");
    }
    memcpy(shifted, f, sizeof shifted);
    memcpy(latched, f, sizeof latched);
    knownShifted = true;
    return ok;
}

// Blank frame with a chain check: a test pattern is shifted (not latched), then the blank frame
// is shifted and latched, and its readback must return the pattern. With the 12 V logic rail
// absent DATA OUT reads low and the check fails.
static bool blankFrame()
{
    static const uint32_t pattern[CHIPS] = {0xA5C3F00Fu, 0x5A3C0FF0u, 0x0F1E2D3Cu};
    static const uint32_t zero[CHIPS] = {0, 0, 0};
    uint32_t back[CHIPS];
    shiftFrame(pattern, back, false);
    shiftFrame(zero, back, true);
    chainOk = frameEq(back, pattern);
    memcpy(shifted, zero, sizeof shifted);
    memcpy(latched, zero, sizeof latched);
    knownShifted = true;
    if (!chainOk) {
        blWrite(0);
        Serial.print("ERR chain");
        printFrame("expected", pattern);
        printFrame("got", back);
        Serial.println(" (blank frame latched; BL locked low)");
    }
    return chainOk;
}

static void setBit(uint32_t f[CHIPS], int chip, int hvout) { f[chip] |= 1u << (hvout - 1); }

static void setElement(uint32_t f[CHIPS], int tube, int el)
{
    int chip = (tube - 1) / 2;
    setBit(f, chip, ((tube - 1) % 2 == 0 ? MAP_A : MAP_B)[el]);
}

static int parseElement(char ch)
{
    const char *p = strchr(ELEMENT_NAMES, toupper((unsigned char)ch));
    return (p && ch) ? (int)(p - ELEMENT_NAMES) : -1;
}

// ---- status -----------------------------------------------------------------------------------------

static void printStatus()
{
    float left = hvOn ? (onForMs - (millis() - onAtMs)) / 1000.0f : 0.0f;
    Serial.printf("OK t_ms=%lu hv=%.1f peak=%.1f sw12=%.2f nix12_en=%d fault=%s left=%.1f trip=%.0f "
                  "chain=%d bl=%u pwm_hz=%lu",
                  (unsigned long)millis(), readHv(), peakHv, readSw12(), hvOn ? 1 : 0, fault, left, hvTrip,
                  chainOk ? 1 : 0, blDuty, (unsigned long)pwmHz);
    printFrame("frame", latched);
    Serial.printf(" enc_a=%d enc_b=%d enc_sw=%d wwvb_en=%d wwvb_irq=%d spare=%d\n", digitalRead(PIN_ENC_A),
                  digitalRead(PIN_ENC_B), digitalRead(PIN_ENC_SW), digitalRead(PIN_WWVB_EN),
                  digitalRead(PIN_WWVB_IRQ), digitalRead(PIN_SPARE));
}

// ---- commands -----------------------------------------------------------------------------------------

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
    float hv = readHv();
    if (hv > hvTrip) {
        trip("hv_over");
        return;
    }
    if (!hvOn) {
        peakHv = 0.0f;
        onAtMs = millis();
    }
    onForMs = (millis() - onAtMs) + s * 1000; // "on" while on restarts the timer
    hvOn = true;
    setLed();
    digitalWrite(PIN_NIX12_EN, HIGH);
    Serial.printf("OK on %lu s\n", (unsigned long)s);
}

static void cmdTrip(const char *arg)
{
    if (!*arg) {
        Serial.printf("OK trip %.0f\n", hvTrip);
        return;
    }
    float v = strtof(arg, nullptr);
    if (v < HV_TRIP_MIN || v > HV_TRIP_MAX) {
        Serial.printf("ERR trip %.0f-%.0f V (lower only; 200 V again at reset)\n", HV_TRIP_MIN, HV_TRIP_MAX);
        return;
    }
    hvTrip = v;
    Serial.printf("OK trip %.0f\n", hvTrip);
}

static void cmdBl(const char *arg)
{
    char *end;
    long duty = strtol(arg, &end, 10);
    unsigned long hz = strtoul(end, nullptr, 10);
    if (end == arg || duty < 0 || duty > 255 || (hz && (hz < 100 || hz > 50000))) {
        Serial.println("ERR bl <0-255> [100-50000 Hz]");
        return;
    }
    if (duty > 0 && !chainOk) {
        Serial.println("ERR chain not confirmed (run blank)");
        return;
    }
    if (hz) {
        pwmHz = hz;
    }
    blWrite((uint8_t)duty);
    Serial.printf("OK bl %u %lu Hz\n", blDuty, (unsigned long)pwmHz);
}

static void cmdOut(const char *arg)
{
    unsigned long chip = 0, n = 0;
    if (sscanf(arg, "%lu %lu", &chip, &n) != 2 || chip < 1 || chip > 3 || n < 1 || n > 32) {
        Serial.println("ERR out <chip 1-3> <hvout 1-32>");
        return;
    }
    uint32_t f[CHIPS] = {0, 0, 0};
    setBit(f, (int)chip - 1, (int)n);
    cycling = false;
    if (showFrame(f)) {
        Serial.printf("OK out U%lu HVOUT%lu\n", 200 + chip, n);
    }
}

static void cmdTube(const char *arg)
{
    unsigned long t = 0;
    char el[4] = "";
    int e;
    if (sscanf(arg, "%lu %3s", &t, el) != 2 || t < 1 || t > 6 || el[1] || (e = parseElement(el[0])) < 0) {
        Serial.println("ERR tube <1-6> <0-9|L|R>");
        return;
    }
    uint32_t f[CHIPS] = {0, 0, 0};
    setElement(f, (int)t, e);
    cycling = false;
    if (showFrame(f)) {
        Serial.printf("OK tube %lu %c", t, ELEMENT_NAMES[e]);
        printFrame("frame", f);
        Serial.println();
    }
}

// show <up to 6 chars>: tube 1 first; 0-9 a digit, L / R a point, - dark.
static void cmdShow(const char *arg)
{
    size_t len = strlen(arg);
    if (len == 0 || len > 6) {
        Serial.println("ERR show <1-6 of 0-9 L R ->");
        return;
    }
    uint32_t f[CHIPS] = {0, 0, 0};
    for (size_t i = 0; i < len; i++) {
        if (arg[i] == '-') {
            continue;
        }
        int e = parseElement(arg[i]);
        if (e < 0) {
            Serial.println("ERR show <1-6 of 0-9 L R ->");
            return;
        }
        setElement(f, (int)i + 1, e);
    }
    cycling = false;
    if (showFrame(f)) {
        Serial.printf("OK show %s", arg);
        printFrame("frame", f);
        Serial.println();
    }
}

static void cmdRaw(const char *arg)
{
    unsigned long a = 0, b = 0, c = 0;
    if (sscanf(arg, "%lx %lx %lx", &a, &b, &c) != 3) {
        Serial.println("ERR raw <U201 hex> <U202 hex> <U203 hex> (bit n-1 = HVOUTn)");
        return;
    }
    uint32_t f[CHIPS] = {(uint32_t)a, (uint32_t)b, (uint32_t)c};
    cycling = false;
    if (showFrame(f)) {
        Serial.print("OK raw");
        printFrame("frame", f);
        Serial.println();
    }
}

static void cycleShow()
{
    uint32_t f[CHIPS] = {0, 0, 0};
    for (int t = 1; t <= 6; t++) {
        setElement(f, t, cycleEl);
    }
    if (showFrame(f)) {
        Serial.printf("OK cycle %c\n", ELEMENT_NAMES[cycleEl]);
    }
}

static void cmdCycle(const char *arg)
{
    uint32_t ms = *arg ? strtoul(arg, nullptr, 10) : 1000;
    if (ms < 20 || ms > 10000) {
        Serial.println("ERR cycle [20-10000 ms]");
        return;
    }
    cycleMs = ms;
    cycleEl = 0;
    cycling = true;
    cycleNextMs = millis() + cycleMs;
    cycleShow();
}

// Readback test: patterns shifted without latching (the outputs keep the latched frame); each
// shift must return the pattern before it. Ends by shifting the latched frame back in, so the
// shift register and the latches agree again.
static void cmdChain()
{
    uint32_t back[CHIPS];
    uint32_t prev[CHIPS];
    uint32_t pat[CHIPS];
    uint32_t fails = 0, tests = 0;
    shiftFrame(latched, back, false); // known start; the readback is whatever was there
    memcpy(prev, latched, sizeof prev);
    // 0: all 0, 1: all 1, 2: 0xAA.., 3: 0x55.., 4-99: walking 1, 100-195: walking 0
    for (int k = 0; k < 196; k++) {
        for (int c = 0; c < CHIPS; c++) {
            uint32_t v = k == 0 ? 0 : k == 1 ? 0xFFFFFFFFu : k == 2 ? 0xAAAAAAAAu : k == 3 ? 0x55555555u : 0;
            if (k >= 4) {
                int b = (k - 4) % 96;
                uint32_t one = (b / 32 == c) ? 1u << (b % 32) : 0;
                v = k < 100 ? one : ~one;
            }
            pat[c] = v;
        }
        shiftFrame(pat, back, false);
        tests++;
        if (!frameEq(back, prev)) {
            if (fails < 4) {
                Serial.printf("ERR chain test %d", k);
                printFrame("expected", prev);
                printFrame("got", back);
                Serial.println();
            }
            fails++;
        }
        memcpy(prev, pat, sizeof prev);
        rp2040.wdt_reset();
        hvGuard();
    }
    shiftFrame(latched, back, false);
    tests++;
    if (!frameEq(back, prev)) {
        fails++;
    }
    memcpy(shifted, latched, sizeof shifted);
    knownShifted = true;
    if (fails) {
        chainOk = false;
        blWrite(0);
    }
    Serial.printf("OK chain tests=%lu fails=%lu%s\n", (unsigned long)tests, (unsigned long)fails,
                  fails ? " (BL low; run blank)" : "");
}

static void startWire()
{
    if (!wireStarted) {
        Wire.setSDA(PIN_WWVB_SDA);
        Wire.setSCL(PIN_WWVB_SCL);
        Wire.setClock(100000); // 100 kHz: R305 / R306 not fitted, carrier 10k only (hardware.md)
        Wire.begin();
        wireStarted = true;
    }
}

// Returns the register value, or -1 if the ES100 did not acknowledge.
static int es100Read(uint8_t reg)
{
    Wire.beginTransmission(ES100_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(true) != 0) {
        return -1;
    }
    if (Wire.requestFrom(ES100_ADDR, (uint8_t)1) != 1) {
        return -1;
    }
    return Wire.read();
}

static void waitMs(uint32_t ms)
{
    uint32_t t0 = millis();
    while (millis() - t0 < ms) {
        rp2040.wdt_reset();
        hvGuard();
    }
}

static void cmdEs100()
{
    startWire();
    digitalWrite(PIN_WWVB_EN, HIGH);
    waitMs(ES100_WAKE_MS);
    int irqOn = digitalRead(PIN_WWVB_IRQ);
    int id = es100Read(ES100_REG_ID);
    digitalWrite(PIN_WWVB_EN, LOW);
    waitMs(10);
    int idOff = es100Read(ES100_REG_ID);
    Serial.printf("OK es100 en1: id=%s%02x%s irq=%d en0: %s\n", id < 0 ? "none" : "0x", id < 0 ? 0 : id,
                  id == ES100_ID ? " (ES100)" : "", irqOn, idOff < 0 ? "no answer (shutdown)" : "answered");
}

static void cmdWen(const char *arg)
{
    if (strcmp(arg, "0") != 0 && strcmp(arg, "1") != 0) {
        Serial.println("ERR wen <0|1>");
        return;
    }
    digitalWrite(PIN_WWVB_EN, arg[0] == '1' ? HIGH : LOW);
    Serial.printf("OK wen %s\n", arg);
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
        Serial.printf("ERR log <1-%lu s> [1-100 Hz]\n", (unsigned long)ON_MAX_S);
        return;
    }
    Serial.println("t_ms,hv,sw12,nix12_en,bl");
    logging = true;
    logPeriodMs = 1000 / hz;
    logNextMs = millis();
    logEndMs = logNextMs + s * 1000;
}

static void handleLine(char *cmd)
{
    while (*cmd == ' ') {
        cmd++;
    }
    char *arg = strchr(cmd, ' ');
    if (arg) {
        *arg++ = '\0';
        while (*arg == ' ') {
            arg++;
        }
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
        cycling = false;
        Serial.println("OK off");
    } else if (strcmp(cmd, "status") == 0) {
        printStatus();
    } else if (strcmp(cmd, "clear") == 0) {
        fault = "none";
        peakHv = 0.0f;
        Serial.println("OK clear");
    } else if (strcmp(cmd, "trip") == 0) {
        cmdTrip(arg);
    } else if (strcmp(cmd, "blank") == 0) {
        cycling = false;
        if (blankFrame()) {
            Serial.println("OK blank chain=1");
        }
    } else if (strcmp(cmd, "chain") == 0) {
        cycling = false;
        cmdChain();
    } else if (strcmp(cmd, "bl") == 0) {
        cmdBl(arg);
    } else if (strcmp(cmd, "out") == 0) {
        cmdOut(arg);
    } else if (strcmp(cmd, "tube") == 0) {
        cmdTube(arg);
    } else if (strcmp(cmd, "show") == 0) {
        cmdShow(arg);
    } else if (strcmp(cmd, "raw") == 0) {
        cmdRaw(arg);
    } else if (strcmp(cmd, "cycle") == 0) {
        cmdCycle(arg);
    } else if (strcmp(cmd, "es100") == 0) {
        cmdEs100();
    } else if (strcmp(cmd, "wen") == 0) {
        cmdWen(arg);
    } else if (strcmp(cmd, "log") == 0) {
        cmdLog(arg);
    } else if (strcmp(cmd, "help") == 0) {
        Serial.println("OK on [s] | off | status | clear | trip [V] | blank | chain | bl <0-255> [hz] | "
                       "out <chip> <n> | tube <t> <0-9|L|R> | show <chars> | raw <h1> <h2> <h3> | cycle [ms] | "
                       "es100 | wen <0|1> | log <s> [hz] | help");
    } else {
        Serial.printf("ERR unknown %s\n", cmd);
    }
}

void setup()
{
    // 12 V switch off and tubes blanked before anything else; the reset pull-downs held them
    // until now. LE idles low (latches hold), CLK and DATA low.
    digitalWrite(PIN_NIX12_EN, LOW);
    pinMode(PIN_NIX12_EN, OUTPUT);
    digitalWrite(PIN_BL, LOW);
    pinMode(PIN_BL, OUTPUT);
    digitalWrite(PIN_LE, LOW);
    pinMode(PIN_LE, OUTPUT);
    digitalWrite(PIN_CLK, LOW);
    pinMode(PIN_CLK, OUTPUT);
    digitalWrite(PIN_DATA, LOW);
    pinMode(PIN_DATA, OUTPUT);
    digitalWrite(PIN_WWVB_EN, LOW);
    pinMode(PIN_WWVB_EN, OUTPUT);
    // Inputs without the RP2040's default pulls: each has its own pull on the board, and the
    // main-bus pins must not load SDA / SCL.
    static const uint8_t inputs[] = {PIN_SPARE, PIN_MAIN_SDA, PIN_MAIN_SCL, PIN_WWVB_IRQ,
                                     PIN_DOUT,  PIN_ENC_A,    PIN_ENC_B,    PIN_ENC_SW};
    for (uint8_t p : inputs) {
        pinMode(p, INPUT);
    }
    analogReadResolution(12);
    // The first read of each ADC pin sets it up and comes back low (dekatron board 1): discard it.
    readHv();
    readSw12();
    led.begin();
    setLed();
    Serial.begin(115200);
    rp2040.wdt_begin(WDT_MS);
    // Blank frame latched before BL can be released. With the 12 V logic rail absent the chain
    // check fails and BL stays locked low until "blank" passes.
    blankFrame();
}

void loop()
{
    rp2040.wdt_reset();

    hvGuard();
    if (hvOn) {
        uint32_t onMs = millis() - onAtMs;
        if (onMs >= onForMs) {
            hvOff();
            cycling = false;
            Serial.println("OK timeout off");
        } else if (onMs >= SW12_SETTLE_MS && readSw12() < SW12_MIN) {
            trip("sw12_low");
        }
    }

    if (cycling && (int32_t)(millis() - cycleNextMs) >= 0) {
        cycleNextMs += cycleMs;
        cycleEl = (cycleEl + 1) % 12;
        cycleShow();
    }

    if (logging) {
        uint32_t now = millis();
        if ((int32_t)(now - logEndMs) >= 0) {
            logging = false;
            Serial.println("END");
        } else if ((int32_t)(now - logNextMs) >= 0) {
            logNextMs += logPeriodMs;
            Serial.printf("%lu,%.1f,%.2f,%d,%u\n", (unsigned long)now, readHv(), readSw12(), hvOn ? 1 : 0, blDuty);
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
