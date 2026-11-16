// SPDX-License-Identifier: MIT
#include "scpi.h"

#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "dekatron_client.h"

namespace scpi {

namespace {

// ---------------------------------------------------------------- error queue

constexpr int QUEUE_LEN = 10;
struct QueuedError {
    int code;
    char text[72];
};
QueuedError g_queue[QUEUE_LEN];
int g_queueN = 0;

void fail(int code, const char *text) { pushError(code, text); }

// ---------------------------------------------------------------- parsing (as nanovolt-divider)

constexpr int MAX_PARAMS = 8;
constexpr int MAX_NODES = 5;

struct Ctx {
    const char *params[MAX_PARAMS];
    int nparams;
    String resp;
};

typedef void (*Handler)(Ctx &);

struct Command {
    const char *pattern; // nodes separated by ':', optional nodes in [brackets]; '?' = query form
    Handler fn;
};

// True if `tok` is the long form or the short form (the leading upper-case letters) of `node`.
bool nodeMatch(const char *node, size_t nodeLen, const char *tok, size_t tokLen)
{
    size_t shortLen = 0;
    while (shortLen < nodeLen && !islower((unsigned char)node[shortLen])) {
        shortLen++;
    }
    if (tokLen != nodeLen && tokLen != shortLen) {
        return false;
    }
    return strncasecmp(node, tok, tokLen) == 0;
}

struct Node {
    const char *s;
    size_t len;
    bool optional;
};

int splitPattern(const char *p, Node *nodes)
{
    int n = 0;
    while (*p && n < MAX_NODES) {
        const char *end = strchr(p, ':');
        size_t len = end ? size_t(end - p) : strlen(p);
        Node &nd = nodes[n++];
        nd.optional = p[0] == '[';
        nd.s = nd.optional ? p + 1 : p;
        nd.len = nd.optional ? len - 2 : len;
        if (!end) {
            break;
        }
        p = end + 1;
    }
    return n;
}

bool matchFrom(const Node *pat, int np, int pi, const Node *hdr, int nh, int hi)
{
    if (pi == np) {
        return hi == nh;
    }
    if (pat[pi].optional && matchFrom(pat, np, pi + 1, hdr, nh, hi)) {
        return true;
    }
    return hi < nh && nodeMatch(pat[pi].s, pat[pi].len, hdr[hi].s, hdr[hi].len) &&
           matchFrom(pat, np, pi + 1, hdr, nh, hi + 1);
}

bool headerMatch(const char *pattern, const char *header, size_t headerLen)
{
    const size_t plen = strlen(pattern);
    const bool pq = pattern[plen - 1] == '?';
    const bool hq = headerLen && header[headerLen - 1] == '?';
    if (pq != hq) {
        return false;
    }
    if (hq) {
        headerLen--;
    }
    if (pattern[0] == '*') {
        return headerLen == plen - pq && strncasecmp(pattern, header, headerLen) == 0;
    }
    char pbuf[48];
    strlcpy(pbuf, pattern, sizeof(pbuf));
    if (pq) {
        pbuf[plen - 1] = '\0';
    }
    Node pat[MAX_NODES], hdr[MAX_NODES];
    const int np = splitPattern(pbuf, pat);
    if (headerLen && header[0] == ':') {
        header++, headerLen--;
    }
    int nh = 0;
    const char *p = header, *end = header + headerLen;
    while (p < end && nh < MAX_NODES) {
        const char *c = (const char *)memchr(p, ':', end - p);
        const char *e = c ? c : end;
        hdr[nh++] = {p, size_t(e - p), false};
        p = e + 1;
    }
    return matchFrom(pat, np, 0, hdr, nh, 0);
}

bool paramIs(const char *param, const char *keyword) { return nodeMatch(keyword, strlen(keyword), param, strlen(param)); }

bool parseDouble(const char *p, double &v)
{
    char *end;
    v = strtod(p, &end);
    return end != p && *end == '\0' && isfinite(v);
}

bool needParams(Ctx &c, int lo, int hi)
{
    if (c.nparams >= lo && c.nparams <= hi) {
        return true;
    }
    fail(c.nparams < lo ? -109 : -108, c.nparams < lo ? "Missing parameter" : "Parameter not allowed");
    return false;
}

// A number that must fit the field it is sent in. Out of range for the field is a local error;
// within the field, the controller judges the documented range (never clamped, either side).
bool num(Ctx &c, int i, double scale, double lo, double hi, long &out)
{
    double v;
    if (!parseDouble(c.params[i], v)) {
        fail(-104, "Data type error");
        return false;
    }
    v = round(v * scale);
    if (v < lo || v > hi) {
        fail(-222, "Data out of range");
        return false;
    }
    out = (long)v;
    return true;
}

int splitQuoted(char *s, char sep, char **out, int max)
{
    int n = 0;
    bool quoted = false;
    out[n++] = s;
    for (char *p = s; *p; p++) {
        if (*p == '"') {
            quoted = !quoted;
        } else if (*p == sep && !quoted) {
            *p = '\0';
            if (n == max) {
                return -1;
            }
            out[n++] = p + 1;
        }
    }
    return n;
}

char *trim(char *s)
{
    while (isspace((unsigned char)*s)) {
        s++;
    }
    char *e = s + strlen(s);
    while (e > s && isspace((unsigned char)e[-1])) {
        *--e = '\0';
    }
    return s;
}

void put16(uint8_t *p, long v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; }
void put32(uint8_t *p, long v) { put16(p, v); put16(p + 2, v >> 16); }

// ---------------------------------------------------------------- dekatron

void report(int r)
{
    char b[72];
    if (r == dek::E_OK) {
        return;
    }
    if (r == dekc::R_BUS || r == dekc::R_TIMEOUT) {
        snprintf(b, sizeof(b), "Hardware error;dekatron %s", r == dekc::R_BUS ? "I2C" : "no confirmation");
        fail(-240, b);
    } else {
        snprintf(b, sizeof(b), "Execution error;dekatron %s", dekc::resultName(r));
        fail(-200, b);
    }
}

void send(uint8_t op, const uint8_t *payload = nullptr, uint8_t len = 0) { report(dekc::command(op, payload, len)); }

void dekSimple(Ctx &c, uint8_t op)
{
    if (needParams(c, 0, 0)) {
        send(op);
    }
}
void dekPing(Ctx &c) { dekSimple(c, dek::OP_PING); }
void dekLight(Ctx &c) { dekSimple(c, dek::OP_LIGHT); }
void dekDark(Ctx &c) { dekSimple(c, dek::OP_DARK); }
void dekHome(Ctx &c) { dekSimple(c, dek::OP_HOME); }
void dekStop(Ctx &c) { dekSimple(c, dek::OP_STOP); }
void dekClear(Ctx &c) { dekSimple(c, dek::OP_CLEAR_FAULT); }
void dekExercise(Ctx &c) { dekSimple(c, dek::OP_EXERCISE); }

// DEK:POS k[,SHORt|FWD|REV]
void dekPos(Ctx &c)
{
    long k;
    if (!needParams(c, 1, 2) || !num(c, 0, 1, 0, 255, k)) {
        return;
    }
    uint8_t d[2] = {(uint8_t)k, 0};
    if (c.nparams == 2) {
        if (paramIs(c.params[1], "FWD")) {
            d[1] = 1;
        } else if (paramIs(c.params[1], "REV")) {
            d[1] = 2;
        } else if (!paramIs(c.params[1], "SHORt")) {
            return fail(-224, "Illegal parameter value");
        }
    }
    send(dek::OP_MOVE_TO, d, 2);
}

// DEK:STEP n
void dekStep(Ctx &c)
{
    long n;
    if (!needParams(c, 1, 1) || !num(c, 0, 1, -32768, 32767, n)) {
        return;
    }
    uint8_t d[2];
    put16(d, n);
    send(dek::OP_MOVE_RELATIVE, d, 2);
}

// DEK:ROT steps_per_s (decimals: 0.01 steps/s)
void dekRot(Ctx &c)
{
    long r;
    if (!needParams(c, 1, 1) || !num(c, 0, 100, -2147483648.0, 2147483647.0, r)) {
        return;
    }
    uint8_t d[4];
    put32(d, r);
    send(dek::OP_ROTATE, d, 4);
}

// DEK:MOTion move_rate,accel
void dekMotion(Ctx &c)
{
    long r, a;
    if (!needParams(c, 2, 2) || !num(c, 0, 1, 0, 65535, r) || !num(c, 1, 1, 0, 65535, a)) {
        return;
    }
    uint8_t d[4];
    put16(d, r);
    put16(d + 2, a);
    send(dek::OP_SET_MOTION, d, 4);
}

// DEK:EFF SWING,centre,amp,period_s | BOUNCE,a,b,rate | SPIN,start,end,accel,turns
void dekEffect(Ctx &c)
{
    if (c.nparams < 1) {
        return fail(-109, "Missing parameter");
    }
    long a, b, r, t;
    uint8_t d[8];
    if (paramIs(c.params[0], "SWING")) {
        if (!needParams(c, 4, 4) || !num(c, 1, 1, 0, 255, a) || !num(c, 2, 1, 0, 255, b) ||
            !num(c, 3, 1000, 0, 65535, r)) {
            return;
        }
        d[0] = a, d[1] = b;
        put16(d + 2, r);
        send(dek::OP_SWING, d, 4);
    } else if (paramIs(c.params[0], "BOUNCE")) {
        if (!needParams(c, 4, 4) || !num(c, 1, 1, 0, 255, a) || !num(c, 2, 1, 0, 255, b) ||
            !num(c, 3, 1, 0, 65535, r)) {
            return;
        }
        d[0] = a, d[1] = b;
        put16(d + 2, r);
        send(dek::OP_BOUNCE, d, 4);
    } else if (paramIs(c.params[0], "SPIN")) {
        if (!needParams(c, 5, 5) || !num(c, 1, 1, 0, 65535, a) || !num(c, 2, 1, 0, 65535, b) ||
            !num(c, 3, 1, 0, 65535, r) || !num(c, 4, 1, 0, 255, t)) {
            return;
        }
        put16(d, a);
        put16(d + 2, b);
        put16(d + 4, r);
        d[6] = t;
        send(dek::OP_SPIN, d, 7);
    } else {
        fail(-224, "Illegal parameter value");
    }
}

constexpr long DEFAULT_RATE = 2000; // wedge/eye sweep rate when not given: the solid look

// DEK:WEDGE a,b[,rate], bookends in cathodes (0.01 resolution)
void dekWedge(Ctx &c)
{
    long a, b, r = DEFAULT_RATE;
    if (!needParams(c, 2, 3) || !num(c, 0, 100, 0, 65535, a) || !num(c, 1, 100, 0, 65535, b) ||
        (c.nparams == 3 && !num(c, 2, 1, 0, 65535, r))) {
        return;
    }
    uint8_t d[6];
    put16(d, a);
    put16(d + 2, b);
    put16(d + 4, r);
    send(dek::OP_WEDGE, d, 6);
}

// DEK:EYE centre,half_width[,rate]: centred wedge, half-width in cathodes
void dekEye(Ctx &c)
{
    long k, h, r = DEFAULT_RATE;
    if (!needParams(c, 2, 3) || !num(c, 0, 1, 0, 255, k) || !num(c, 1, 100, 0, 65535, h) ||
        (c.nparams == 3 && !num(c, 2, 1, 0, 65535, r))) {
        return;
    }
    uint8_t d[5];
    d[0] = k;
    put16(d + 1, h);
    put16(d + 3, r);
    send(dek::OP_WEDGE_CENTRED, d, 5);
}

// DEK:GAUGE value, in cathodes (0-10)
void dekGauge(Ctx &c)
{
    long v;
    if (!needParams(c, 1, 1) || !num(c, 0, 100, 0, 65535, v)) {
        return;
    }
    uint8_t d[2];
    put16(d, v);
    send(dek::OP_GAUGE, d, 2);
}

// DEK:IDXcheck open_ms,limit_ms
void dekIndexCheck(Ctx &c)
{
    long o, l;
    if (!needParams(c, 2, 2) || !num(c, 0, 1, 0, 65535, o) || !num(c, 1, 1, 0, 65535, l)) {
        return;
    }
    uint8_t d[4];
    put16(d, o);
    put16(d + 2, l);
    send(dek::OP_SET_INDEX_CHECK, d, 4);
}

// DEK:STAT? -> key=value fields, named as on the controller's own console where they exist.
void dekStat(Ctx &c)
{
    dek::Status s;
    if (!dekc::readStatus(&s)) {
        return report(dekc::R_BUS);
    }
    static const char *pw[] = {"dark", "striking", "lit"};
    static const char *dr[] = {"boot", "command", "fault", "master_loss", "hold_limit", "index_lost"};
    static const char *md[] = {"idle", "home", "queue", "rotate", "swing", "bounce", "spin", "wedge", "exercise"};
    static const char *fl[] = {"none", "vin", "en_low", "hv_low", "strike_timeout", "index_timeout"};
    char b[640];
    snprintf(b, sizeof(b),
             "protocol=%u fw=%u.%u boots=%u t_ms=%lu seq=%u err=%s owner=%s power=%s fault=%s dark_reason=%s "
             "pos=%u valid=%d mode=%s queue=%d busy=%d pgood=%d hv_en=%d master_loss=%d exercise_due=%d "
             "wdt_reset=%d recovering=%d idx_exp=%u idx_obs=%u home_fail=%u mismatch=%u dwell_ms=%lu rate=%.1f "
             "slow_run_s=%lu hv=%.1f vin=%.1f rtn=%.1f skips=%u sense_misses=%u idx_late=%u "
             "recovery_failures=%u last_skip=%d trips=%u",
             s.protocol, s.firmware >> 8, s.firmware & 0xFF, s.boot_count, (unsigned long)s.uptime_ms, s.cmd_seq,
             dekc::resultName(s.last_error), s.owner == dek::OWN_USB ? "usb" : "i2c", s.power < 3 ? pw[s.power] : "?",
             s.fault < 6 ? fl[s.fault] : "?", s.dark_reason < 6 ? dr[s.dark_reason] : "?", s.position,
             (s.flags & dek::FL_POSITION_VALID) ? 1 : 0, s.mode < 9 ? md[s.mode] : "?", s.queue,
             (s.flags & dek::FL_BUSY) ? 1 : 0, (s.flags & dek::FL_PGOOD) ? 1 : 0, (s.flags & dek::FL_HV_EN) ? 1 : 0,
             (s.flags & dek::FL_MASTER_LOSS) ? 1 : 0, (s.flags & dek::FL_EXERCISE_DUE) ? 1 : 0,
             (s.flags & dek::FL_WATCHDOG_RESET) ? 1 : 0, (s.flags & dek::FL_RECOVERING) ? 1 : 0, s.idx_expected,
             s.idx_observed, s.home_failures, s.idx_mismatches, (unsigned long)s.dwell_ms, s.rate_dsps / 10.0f,
             (unsigned long)s.slow_run_s, s.hv_dv / 10.0f, s.vin_dv / 10.0f, s.rtn_dv / 10.0f, s.skips,
             s.sense_misses, s.idx_late, s.recovery_failures, s.last_skip, s.trips);
    c.resp = b;
}

// ---------------------------------------------------------------- diagnostics

// DIAG:I2C? -> bus counters since boot
void diagI2c(Ctx &c)
{
    dekc::Stats s = dekc::stats();
    char b[160];
    snprintf(b, sizeof(b), "reads=%lu read_err=%lu writes=%lu write_err=%lu bad_status=%lu confirm_timeout=%lu poll=%d",
             (unsigned long)s.reads, (unsigned long)s.read_errors, (unsigned long)s.writes,
             (unsigned long)s.write_errors, (unsigned long)s.bad_status, (unsigned long)s.confirm_timeouts,
             dekc::polling() ? 1 : 0);
    c.resp = b;
}

// DIAG:DEK:RAW? "hex" -> the controller's verdict on an arbitrary frame (error-path tests)
void diagRaw(Ctx &c)
{
    if (!needParams(c, 1, 1)) {
        return;
    }
    const char *h = c.params[0];
    size_t n = strlen(h);
    uint8_t f[18];
    if (n == 0 || n % 2 || n / 2 > sizeof(f)) {
        return fail(-224, "Illegal parameter value");
    }
    for (size_t i = 0; i < n / 2; i++) {
        char two[3] = {h[2 * i], h[2 * i + 1], 0};
        char *end;
        f[i] = (uint8_t)strtoul(two, &end, 16);
        if (*end) {
            return fail(-224, "Illegal parameter value");
        }
    }
    c.resp = dekc::resultName(dekc::raw(f, n / 2));
}

// DIAG:DEK:POLL ON|OFF: off stops the status polling, to test the controller's master loss.
void diagPoll(Ctx &c)
{
    if (!needParams(c, 1, 1)) {
        return;
    }
    if (paramIs(c.params[0], "ON") || !strcmp(c.params[0], "1")) {
        dekc::setPolling(true);
    } else if (paramIs(c.params[0], "OFF") || !strcmp(c.params[0], "0")) {
        dekc::setPolling(false);
    } else {
        fail(-224, "Illegal parameter value");
    }
}
void diagPollQ(Ctx &c) { c.resp = dekc::polling() ? "1" : "0"; }

// ---------------------------------------------------------------- system

void idn(Ctx &c)
{
    char b[80];
    snprintf(b, sizeof(b), "UND,Universal Nixie Display,%012llX,%s", ESP.getEfuseMac(), DISP_FW_VERSION);
    c.resp = b;
}

void systErr(Ctx &c)
{
    if (g_queueN == 0) {
        c.resp = "0,\"No error\"";
        return;
    }
    char b[96];
    snprintf(b, sizeof(b), "%d,\"%s\"", g_queue[0].code, g_queue[0].text);
    c.resp = b;
    memmove(g_queue, g_queue + 1, sizeof(g_queue[0]) * (g_queueN - 1));
    g_queueN--;
}

const Command COMMANDS[] = {
    {"*IDN?", idn},
    {"SYSTem:ERRor:[NEXT]?", systErr},
    {"DEKatron:PING", dekPing},
    {"DEKatron:LIGHt", dekLight},
    {"DEKatron:DARK", dekDark},
    {"DEKatron:HOME", dekHome},
    {"DEKatron:STOP", dekStop},
    {"DEKatron:CLEar", dekClear},
    {"DEKatron:EXERcise", dekExercise},
    {"DEKatron:POSition", dekPos},
    {"DEKatron:STEP", dekStep},
    {"DEKatron:ROTate", dekRot},
    {"DEKatron:MOTion", dekMotion},
    {"DEKatron:EFFect", dekEffect},
    {"DEKatron:WEDGe", dekWedge},
    {"DEKatron:EYE", dekEye},
    {"DEKatron:GAUGe", dekGauge},
    {"DEKatron:IDXcheck", dekIndexCheck},
    {"DEKatron:STATus?", dekStat},
    {"DIAGnostic:I2C?", diagI2c},
    {"DIAGnostic:DEKatron:RAW?", diagRaw},
    {"DIAGnostic:DEKatron:POLL", diagPoll},
    {"DIAGnostic:DEKatron:POLL?", diagPollQ},
};

void executeOne(char *cmd, String &resp)
{
    cmd = trim(cmd);
    if (!*cmd) {
        return;
    }
    size_t hlen = strcspn(cmd, " \t");
    char *args = cmd + hlen;
    if (*args) {
        *args++ = '\0';
    }
    Ctx c;
    c.nparams = 0;
    args = trim(args);
    if (*args) {
        char *parts[MAX_PARAMS];
        c.nparams = splitQuoted(args, ',', parts, MAX_PARAMS);
        if (c.nparams < 0) {
            return fail(-108, "Parameter not allowed;too many");
        }
        for (int i = 0; i < c.nparams; i++) {
            char *p = trim(parts[i]);
            size_t n = strlen(p);
            if (n >= 2 && p[0] == '"' && p[n - 1] == '"') {
                p[n - 1] = '\0', p++;
            }
            c.params[i] = p;
        }
    }
    for (const Command &def : COMMANDS) {
        if (!headerMatch(def.pattern, cmd, strlen(cmd))) {
            continue;
        }
        def.fn(c);
        if (c.resp.length()) {
            if (resp.length()) {
                resp += ';';
            }
            resp += c.resp;
        }
        return;
    }
    fail(-113, "Undefined header");
}

} // namespace

void execute(const char *line, Print &out)
{
    char buf[256];
    strlcpy(buf, line, sizeof(buf));
    char *cmds[8];
    const int n = splitQuoted(buf, ';', cmds, 8);
    if (n < 0) {
        return fail(-100, "Command error;too many commands in one line");
    }
    String resp;
    for (int i = 0; i < n; i++) {
        executeOne(cmds[i], resp);
    }
    if (resp.length()) {
        out.print(resp);
        out.print('\n');
    }
}

void pushError(int code, const char *text)
{
    if (g_queueN == QUEUE_LEN) {
        g_queue[QUEUE_LEN - 1].code = -350;
        strlcpy(g_queue[QUEUE_LEN - 1].text, "Queue overflow", sizeof(g_queue[0].text));
        return;
    }
    g_queue[g_queueN].code = code;
    strlcpy(g_queue[g_queueN].text, text, sizeof(g_queue[g_queueN].text));
    g_queueN++;
}

} // namespace scpi
