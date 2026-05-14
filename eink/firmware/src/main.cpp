#include <Arduino.h>
#include <ArduinoJson.h>
#include <qrcode.h>
#include <heltec-eink-modules.h>

// ---------------------------------------------------------------------------
// Display — declared without parentheses (avoids function-prototype ambiguity)
// ---------------------------------------------------------------------------

LCMEN2R13EFC1 display;

// Layout constants — landscape: 250 × 122 px
static const int W         = 250;
static const int H         = 122;

// QR code: version 3 = 29×29 modules, scale 2 → 58×58 px
static const int QR_VER    = 3;
static const int QR_SCALE  = 2;
static const int QR_PX     = 29 * QR_SCALE;           // 58
static const int QR_X      = 4;
static const int QR_Y      = (H - QR_PX) / 2;         // 32 — vertically centred
static const int SPLIT_X   = QR_X + QR_PX + 4;        // 66 — divider x
static const int CONTENT_X = SPLIT_X + 4;             // 70 — text left margin

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

enum class DisplayState { SPLASH, SETUP, OPERATIONAL };
static DisplayState g_state = DisplayState::SPLASH;

struct Payload {
    char mode[32];
    char status[16];
    char ip[24];
    char ssid[32];
    char password[64];
    char detail[64];
    char uptime[16];
    int  fps;
};

static Payload g_payload  = {};
static char    g_last_ip[24] = {};

// ---------------------------------------------------------------------------
// Serial line reader
// ---------------------------------------------------------------------------

static char   g_buf[512];
static size_t g_buf_len = 0;

bool read_line() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n') {
            g_buf[g_buf_len] = '\0';
            g_buf_len = 0;
            return true;
        }
        if (g_buf_len < sizeof(g_buf) - 1)
            g_buf[g_buf_len++] = c;
    }
    return false;
}

bool parse_payload(const char* json_str, Payload& out) {
    JsonDocument doc;
    if (deserializeJson(doc, json_str) != DeserializationError::Ok) return false;
    strlcpy(out.mode,     doc["mode"]     | "", sizeof(out.mode));
    strlcpy(out.status,   doc["status"]   | "", sizeof(out.status));
    strlcpy(out.ip,       doc["ip"]       | "", sizeof(out.ip));
    strlcpy(out.ssid,     doc["ssid"]     | "", sizeof(out.ssid));
    strlcpy(out.password, doc["password"] | "", sizeof(out.password));
    strlcpy(out.detail,   doc["detail"]   | "", sizeof(out.detail));
    strlcpy(out.uptime,   doc["uptime"]   | "", sizeof(out.uptime));
    out.fps = doc["fps"] | 0;
    return true;
}

// ---------------------------------------------------------------------------
// Drawing helpers
// ---------------------------------------------------------------------------

// Render a QR code for `url` into the fixed left-column zone.
static void draw_qr(const char* url) {
    uint8_t qr_buf[qrcode_getBufferSize(QR_VER)];
    QRCode  qr;
    qrcode_initText(&qr, qr_buf, QR_VER, ECC_LOW, url);
    // Fill zone white first so partial refreshes start clean
    display.fillRect(QR_X, QR_Y, QR_PX, QR_PX, WHITE);
    for (int row = 0; row < qr.size; row++) {
        for (int col = 0; col < qr.size; col++) {
            if (qrcode_getModule(&qr, col, row))
                display.fillRect(QR_X + col * QR_SCALE, QR_Y + row * QR_SCALE,
                                 QR_SCALE, QR_SCALE, BLACK);
        }
    }
}

// Full-width horizontal rule.
static void hline(int y) {
    display.drawLine(0, y, W - 1, y, BLACK);
}

// Vertical divider between QR column and content column.
static void vline() {
    display.drawLine(SPLIT_X, 0, SPLIT_X, H - 1, BLACK);
}

// Left-aligned text in the content zone.
static void text(int x, int y, uint8_t sz, const char* str) {
    display.setTextSize(sz);
    display.setTextColor(BLACK, WHITE);
    display.setCursor(x, y);
    display.print(str);
}

// Content-zone shorthand (left margin applied).
static void ctext(int y, uint8_t sz, const char* str) {
    text(CONTENT_X, y, sz, str);
}

// ---------------------------------------------------------------------------
// Render functions
// ---------------------------------------------------------------------------

// Boot splash — "PITWALL / WAITING FOR HOST..."
void render_splash() {
    display.clearMemory();

    // "PITWALL" — textSize(3): 18px/char advance, 24px tall
    // 7 chars × 18 = 126px wide; centred in 250px: x = 62
    text((W - 7 * 6 * 3) / 2, 36, 3, "PITWALL");

    hline(68);

    // "WAITING FOR HOST..." — textSize(1): 6px/char
    // 19 chars × 6 = 114px; centred: x = 68
    text((W - 19 * 6) / 2, 78, 1, "WAITING FOR HOST...");

    display.update();
}

// AP provisioning screen — QR + WiFi join instructions.
void render_setup(const Payload& p) {
    display.clearMemory();

    // Left column: QR code for the captive portal IP
    char url[48];
    snprintf(url, sizeof(url), "http://%s", p.ip);
    draw_qr(url);
    vline();

    // Right column
    ctext(6,  2, "SETUP");
    hline(27);

    ctext(34, 1, "WIFI:");
    ctext(46, 2, p.ssid);      // "PITWALL" = 7 chars × 12px = 84px — fits

    hline(73);

    ctext(80, 1, "OPEN:");
    ctext(92, 1, url);          // "http://192.168.4.1" = 108px — fits

    hline(107);
    ctext(112, 1, p.detail);    // "Connect to configure WiFi"

    display.update();
}

// Normal operational screen — QR + mode/stats.
// full == true:  IP changed or first operational frame → full refresh
// full == false: routine heartbeat update → partial refresh
void render_operational(const Payload& p, bool full) {
    display.clearMemory();

    // Left column: QR code for the web UI
    char url[48];
    snprintf(url, sizeof(url), "http://%s", p.ip);
    draw_qr(url);
    vline();

    // Right column

    // Mode name — large
    ctext(6, 2, p.mode);        // e.g. "F1 LIVE" — 7 chars × 12 = 84px
    hline(27);

    // Detail — truncated to 28 chars so it fits at textSize(1) in 180px
    char detail[29];
    strlcpy(detail, p.detail, sizeof(detail));
    ctext(34, 1, detail);

    // IP address
    ctext(48, 1, p.ip);
    hline(63);

    // Stats: FPS + uptime
    char stats[40];
    snprintf(stats, sizeof(stats), "%dfps  %s", p.fps, p.uptime);
    ctext(70, 1, stats);

    // Status dot — small filled square when ok
    if (strcmp(p.status, "ok") == 0) {
        display.fillRect(CONTENT_X, 84, 6, 6, BLACK);
        text(CONTENT_X + 10, 84, 1, "OK");
    }

    // Partial refresh for heartbeat updates; full refresh on IP change / first frame.
    // display.update() currently does a full refresh for all cases.
    // Replace with display.update(PARTIAL) once confirmed on hardware.
    (void)full;
    display.update();
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    Serial.println("[boot] serial ready");

    Serial.println("[display] calling landscape()");
    display.landscape();
    Serial.println("[display] landscape() done");

    Serial.println("[display] rendering splash");
    render_splash();
    Serial.println("[display] splash done");
}

void loop() {
    if (!read_line()) return;

    Serial.print("[serial] received: ");
    Serial.println(g_buf);

    Payload next = {};
    if (!parse_payload(g_buf, next)) {
        Serial.println("[parse] ERROR: JSON parse failed");
        return;
    }
    Serial.print("[parse] mode="); Serial.print(next.mode);
    Serial.print(" ip=");          Serial.print(next.ip);
    Serial.print(" status=");      Serial.println(next.status);

    bool ip_changed = strcmp(next.ip, g_last_ip) != 0;
    if (ip_changed) {
        Serial.print("[state] IP changed: ");
        Serial.print(g_last_ip); Serial.print(" -> "); Serial.println(next.ip);
    }
    strlcpy(g_last_ip, next.ip, sizeof(g_last_ip));

    if (strcmp(next.mode, "setup") == 0) {
        g_state   = DisplayState::SETUP;
        g_payload = next;
        Serial.println("[display] rendering setup screen");
        render_setup(g_payload);
        Serial.println("[display] setup screen done");
    } else {
        bool was_operational = (g_state == DisplayState::OPERATIONAL);
        bool full = !was_operational || ip_changed;
        g_state   = DisplayState::OPERATIONAL;
        g_payload = next;
        Serial.print("[display] rendering operational (full=");
        Serial.print(full ? "true" : "false");
        Serial.println(")");
        render_operational(g_payload, full);
        Serial.println("[display] operational done");
    }
}
