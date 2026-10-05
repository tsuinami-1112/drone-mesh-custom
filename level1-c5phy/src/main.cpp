/*
 * =============================================================================
 * Level 1 station v3 - XIAO ESP32-C5 as the 5.8 GHz analog FPV receiver
 *
 * Four patch antennas on an SP4T switch feed the C5's own 5 GHz Wi-Fi radio,
 * optionally through one 20 dB LNA + band-pass filter. The PHY is held
 * receive-only on each FPV channel in turn; raw I/Q from the modem's
 * diagnostic bus is captured in 16 KiB windows through PARLIO and measured for
 * power and FM coherence on every sector. The strongest sector and its two
 * neighbours give an amplitude-comparison bearing (relative to the box's face
 * N; the mapper rotates it by the station heading). The strongest hits get a
 * software video check: FM-demodulate eight windows and look for horizontal
 * sync repeating at the PAL or NTSC line period.
 *
 * Output:
 *   USB Serial          full JSON records for mesh-mapper.py, a boot line, a
 *                       heartbeat every 60 s, and the bench console
 *   Serial1 D4 TX / D5 RX   one Meshtastic text message per report (<= 191 B)
 *                       to a Heltec V3, the same pins as every station tier
 *
 * Bench console (Enter-terminated, on USB):
 *   ?            status           h R3 | h 5732   hold a channel
 *   s 0..3       sector           g 30 | g a      fixed / automatic gain
 *   v            video check on the held channel   x   resume scanning
 *   t 100 | t 1  drive the switch control lines directly while holding (stage 6 truth
 *                table); a V1V2V3 pattern or a number 0..7, kept until s or x
 *   STATUS / WATCHDOG_RESET   answered with a heartbeat (mesh-mapper.py sends it)
 *
 * All signal processing is in demod.c / bearing.c / report.c, which are plain
 * C and unit-tested on a desktop (cd test/host && make).
 * =============================================================================
 */
#if !defined(ARDUINO_ARCH_ESP32)
#error "This firmware targets the Seeed XIAO ESP32-C5"
#endif

#include <Arduino.h>
#include <HardwareSerial.h>
#include <esp_mac.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <math.h>
#include <string.h>
#include <stdarg.h>
#include <ctype.h>
#include <esp_log.h>

#include "config.h"
#include "fpv_channels.h"
#include "demod.h"
#include "bearing.h"
#include "report.h"
#include "c5phy_rf.h"
#include "iq_capture.h"
#include "sector_switch.h"
#include "switch_bits.h"

// =============================================================================
// Identity and state
// =============================================================================
static char s_node_id[24] = "0000";

enum Mode { MODE_SCAN, MODE_HOLD };
static Mode     s_mode = MODE_SCAN;
static bool     s_rf_ok = false;
static int      s_hold_ch = -1;         // channel index held by the bench console
static int      s_hold_sector = 0;
static int      s_hold_gain = -1;       // -1 = automatic
static bool     s_switch_raw = false;   // bench 't': the control lines hold a raw pattern, not s_hold_sector
static int      s_gain = GAIN_MAX;      // PHY gain index currently applied

static uint32_t s_sweeps = 0, s_tune_fail = 0, s_video_seen = 0, s_bus_stuck = 0, s_alias_drop = 0;
static uint32_t s_usb_drop = 0, s_mesh_drop = 0;
static unsigned s_seq = 0;
static float    s_nf_level_min = 1e9f;  // quietest sector level this sweep
static float    s_nf_dbm = RSSI_CAL_DBM_AT_NOISE + RSSI_CAL_OFFSET_DB - RF_FRONTEND_GAIN_DB;
static uint32_t s_last_hb_usb = 0, s_last_hb_mesh = 0;
static uint32_t s_led_off_at = 0;
static const float s_az[SECTOR_COUNT] = SECTOR_AZIMUTH_DEG;

struct SectorMeasure {
    int   windows;
    float level_db, level_min, level_max;
    int   gain, q_phase, cfo_khz;
    float p_mean, clip_pct;
    int   mod, noise;
};
struct ChannelResult {
    bool tuned, hit;
    int  best;
    SectorMeasure sec[SECTOR_COUNT];
};
static ChannelResult s_results[48];
static uint32_t      s_last_mesh_report[48];

// =============================================================================
// Level and calibration
// =============================================================================
static float level_from(const IqMetrics& m, int gain)
{
    float p = m.p_mean > 0.05f ? m.p_mean : 0.05f;
    return (float)(GAIN_MAX - gain) + 10.0f * log10f(p / RF_NOISE_POWER);
}
static float dbm_from_level(float level_db)
{
    return RSSI_CAL_DBM_AT_NOISE + level_db * RSSI_CAL_SLOPE + RSSI_CAL_OFFSET_DB - RF_FRONTEND_GAIN_DB;
}
static float threshold_dbm() { return dbm_from_level(DETECT_LEVEL_DB); }

static void set_gain(int g)
{
    if (g < GAIN_MIN) g = GAIN_MIN;
    if (g > GAIN_MAX) g = GAIN_MAX;
    if (g != s_gain) { s_gain = g; rf_set_gain((uint8_t)g); }
}

// =============================================================================
// Output: USB never blocks, mesh lines are paced
// =============================================================================
/* A line goes out whole or not at all: a record whose terminator did not fit
 * would glue the next record onto the same line. */
static void usb_println(const char* s)
{
    static char line[USB_JSON_MAX + 2];
    size_t n = strlen(s);
    if (n > USB_JSON_MAX) n = USB_JSON_MAX;
    memcpy(line, s, n);
    line[n++] = '\r';
    line[n++] = '\n';
    if (Serial.availableForWrite() < (int)n) { s_usb_drop++; return; }
    if (Serial.write((const uint8_t*)line, n) < n) s_usb_drop++;
}

static void usb_printf(const char* fmt, ...)
{
    char buf[USB_JSON_MAX];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    usb_println(buf);
}

#define MESH_QUEUE_DEPTH 4
static char     s_mesh_q[MESH_QUEUE_DEPTH][MESH_JSON_MAX + 1];
static int      s_mesh_head = 0, s_mesh_count = 0;
static uint32_t s_mesh_last_send = 0;

static void mesh_enqueue(const char* line)
{
    if (s_mesh_count == MESH_QUEUE_DEPTH) {        // drop the oldest: a fresh report is worth more
        s_mesh_head = (s_mesh_head + 1) % MESH_QUEUE_DEPTH;
        s_mesh_count--;
        s_mesh_drop++;
    }
    int slot = (s_mesh_head + s_mesh_count) % MESH_QUEUE_DEPTH;
    strlcpy(s_mesh_q[slot], line, sizeof(s_mesh_q[slot]));
    s_mesh_count++;
}

static void mesh_drain()
{
    if (s_mesh_count == 0) return;
    uint32_t now = millis();
    if (now - s_mesh_last_send < MESH_LINE_GAP_MS) return;
    const char* msg = s_mesh_q[s_mesh_head];
    int len = (int)strlen(msg);
    if (Serial1.availableForWrite() >= len + 2) {
        Serial1.println(msg);
        s_mesh_last_send = now;
        s_mesh_head = (s_mesh_head + 1) % MESH_QUEUE_DEPTH;
        s_mesh_count--;
    }
}

static void led_blink(uint32_t ms)
{
    digitalWrite(PIN_STATUS_LED, LOW);              // XIAO user LED is active low
    s_led_off_at = millis() + ms;
}
static void led_service()
{
    if (s_led_off_at && (int32_t)(millis() - s_led_off_at) >= 0) {
        digitalWrite(PIN_STATUS_LED, HIGH);
        s_led_off_at = 0;
    }
}

// =============================================================================
// Measurement
// =============================================================================
static bool capture_metrics(IqMetrics* m, uint8_t** raw)
{
    uint8_t* buf = nullptr;
    if (iq_capture_window(&buf, 20) != ESP_OK) return false;
    iq_metrics(buf, IQ_WINDOW_BYTES, m);
    if (m->stuck) s_bus_stuck++;          // the diag bus is not streaming: every sample identical
    if (raw) *raw = buf;
    return true;
}

/* One window at start_gain; when allow_step, step the gain down while the
 * window clips (strong carriers stay unclipped, weak ones keep full gain). */
static bool measure_window(int start_gain, bool allow_step, IqMetrics* m, int* gain_out)
{
    int g = start_gain;
    const int max_steps = (GAIN_MAX - GAIN_MIN) / GAIN_STEP + 2;
    for (int attempt = 0; attempt < max_steps; attempt++) {
        set_gain(g);
        if (!capture_metrics(m, nullptr)) return false;
        if (allow_step && m->clip_pct > CLIP_MAX_PCT && g > GAIN_MIN) { g -= GAIN_STEP; continue; }
        break;
    }
    *gain_out = s_gain;
    return true;
}

static int median3(int a, int b, int c)
{
    if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
    if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
    return c;
}

/* measure_sector: select the patch, start at full gain, take up to
 * WINDOWS_PER_SECTOR windows (one on a quiet channel). level = minimum over
 * the windows (a Wi-Fi burst raises one window, not all), q = median. */
static void measure_sector(int sector, SectorMeasure* sm, int fixed_gain)
{
    memset(sm, 0, sizeof(*sm));
    switch_select(sector);
    float levels[WINDOWS_PER_SECTOR];
    int   qs[WINDOWS_PER_SECTOR], cfos[WINDOWS_PER_SECTOR];
    int   n = 0, gain = fixed_gain >= 0 ? fixed_gain : GAIN_MAX;
    IqMetrics m = {};
    for (int w = 0; w < WINDOWS_PER_SECTOR; w++) {
        int g = gain;
        if (!measure_window(gain, fixed_gain < 0, &m, &g)) break;
        gain = g;
        levels[n] = level_from(m, g);
        qs[n] = (int)(m.q_phase_pct + 0.5f);
        cfos[n] = (int)lrintf(m.cfo_khz);
        n++;
        if (w == 0 && levels[0] < DETECT_LEVEL_DB - QUIET_MARGIN_DB) break;   // quiet: one window is enough
    }
    if (n == 0) return;
    sm->windows = n;
    sm->level_db = sm->level_min = sm->level_max = levels[0];
    for (int i = 1; i < n; i++) {
        if (levels[i] < sm->level_min) sm->level_min = levels[i];
        if (levels[i] > sm->level_max) sm->level_max = levels[i];
    }
    sm->level_db = sm->level_min;
    sm->q_phase = n == 3 ? median3(qs[0], qs[1], qs[2]) : (n == 2 ? (qs[0] + qs[1]) / 2 : qs[0]);
    sm->cfo_khz = n == 3 ? median3(cfos[0], cfos[1], cfos[2]) : cfos[n - 1];
    sm->gain = gain;
    sm->p_mean = m.p_mean;
    sm->clip_pct = m.clip_pct;
    sm->mod = m.mod;
    sm->noise = m.noise;
    if (sm->level_db < s_nf_level_min) s_nf_level_min = sm->level_db;
}

/* scan_channel: tune, measure the four sectors, decide the hit. A hit needs
 * the level AND the FM coherence on the strongest sector: a carrier 10 MHz
 * off steps 90 degrees per sample and never counts as coherent, so a
 * neighbour inside the 40 MHz filter raises the level but is not a hit. */
static void scan_channel(int idx, ChannelResult* r)
{
    memset(r, 0, sizeof(*r));
    const FpvChannel* c = fpv_channel(idx);
    if (rf_tune(c->freq_mhz) != ESP_OK) { s_tune_fail++; return; }
    r->tuned = true;
    delay(TUNE_SETTLE_MS);
    for (int s = 0; s < SECTOR_COUNT; s++) measure_sector(s, &r->sec[s], -1);
    r->best = 0;
    for (int s = 1; s < SECTOR_COUNT; s++)
        if (r->sec[s].windows && (!r->sec[r->best].windows || r->sec[s].level_db > r->sec[r->best].level_db)) r->best = s;
    const SectorMeasure& b = r->sec[r->best];
    r->hit = b.windows > 0 && b.level_db >= DETECT_LEVEL_DB && b.q_phase >= Q_MIN;
}

/* Video check: hold the channel and the sector, demodulate VIDEO_WINDOWS
 * windows VIDEO_WINDOW_GAP_MS apart and look for the PAL / NTSC line period. */
static void video_check(int idx, int sector, int gain, VideoVerdict* v, int* cfo_khz, VideoResult* windows_out)
{
    VideoResult vr[VIDEO_WINDOWS];
    int n = 0;
    float cfo_sum = 0;
    memset(v, 0, sizeof(*v));
    strcpy(v->std, "none");
    const FpvChannel* c = fpv_channel(idx);
    if (rf_freq_mhz() != c->freq_mhz) {
        if (rf_tune(c->freq_mhz) != ESP_OK) { s_tune_fail++; return; }
        delay(TUNE_SETTLE_MS);
    }
    switch_select(sector);
    set_gain(gain);
    for (int w = 0; w < VIDEO_WINDOWS; w++) {
        uint8_t* buf = nullptr;
        IqMetrics m;
        if (capture_metrics(&m, &buf)) {
            video_window(buf, IQ_WINDOW_BYTES, &vr[n]);
            cfo_sum += m.cfo_khz;
            n++;
        }
        delay(VIDEO_WINDOW_GAP_MS);
    }
    video_verdict(vr, n, VIDEO_MIN_WINDOWS, v);
    if (n) *cfo_khz = (int)lrintf(cfo_sum / n);
    if (windows_out) memcpy(windows_out, vr, sizeof(vr));
}

// =============================================================================
// Reporting
// =============================================================================
static void report_hit(int idx, bool do_video)
{
    ChannelResult& r = s_results[idx];
    const FpvChannel* c = fpv_channel(idx);
    const SectorMeasure& b = r.sec[r.best];

    float levels[SECTOR_COUNT], dbm[SECTOR_COUNT];
    int valid[SECTOR_COUNT];
    for (int s = 0; s < SECTOR_COUNT; s++) {
        valid[s] = r.sec[s].windows > 0;
        /* a sector whose capture failed is reported at the sweep's noise floor, not at a
         * fantasy -30 dB that would throw the bearing to the clamp */
        levels[s] = valid[s] ? r.sec[s].level_db : (s_nf_level_min < 1e8f ? s_nf_level_min : 0.0f);
        dbm[s] = dbm_from_level(levels[s]);
    }
    BearingResult br;
    bearing_estimate_masked(levels, valid, s_az, SECTOR_COUNT, BEARING_K_DEG_PER_DB, BEARING_MAX_OFFSET_DEG,
                            BEARING_SIGMA_BASE_DEG, DETECT_LEVEL_DB, &br);

    VideoVerdict vv = {};
    strcpy(vv.std, "none");
    int cfo = b.cfo_khz;
    if (do_video && VIDEO_CHECK) {
        video_check(idx, r.best, b.gain, &vv, &cfo, nullptr);
        if (vv.present) s_video_seen++;
    }

    DetectionReport d = {};
    d.node_id = s_node_id;
    d.receiver = FIRMWARE_RECEIVER;
    d.hw = FIRMWARE_HW;
    d.band = c->band;
    d.ch = c->number;
    d.freq_mhz = c->freq_mhz;
    d.rssi_dbm = dbm_from_level(b.level_db);
    d.rssi_min_dbm = dbm_from_level(b.level_min);
    d.rssi_max_dbm = dbm_from_level(b.level_max);
    d.rssi_n = b.windows;
    d.level_db = b.level_db;
    d.gain = b.gain;
    d.q_phase = b.q_phase;
    d.cfo_khz = cfo;
    d.carrier = b.mod ? "fm" : "cw";
    d.sectors_dbm = dbm;
    d.sector_count = SECTOR_COUNT;
    d.sector = br.sector;
    d.bearing_deg = (int)lrintf(br.bearing_deg) % 360;
    d.bearing_sigma_deg = (int)lrintf(br.sigma_deg);
    d.heading = STATION_HEADING_DEG;
    d.freq_peak = c->freq_mhz + (int)lrintf(cfo / 1000.0f);
    d.video = vv.present ? vv.std : "none";
    d.sync_hz = vv.sync_hz;
    d.field_hz = vv.field_hz;
    d.sync_q = vv.sync_q;
    d.sync_score = vv.sync_score;
    d.video_windows = vv.windows;
    d.seq = ++s_seq;

    char usb[USB_JSON_MAX];
    if (report_detection_json(usb, sizeof(usb), &d, 1) > 0) usb_println(usb);

    uint32_t now = millis();
    if (s_last_mesh_report[idx] == 0 || now - s_last_mesh_report[idx] >= MESH_REPORT_INTERVAL_MS) {
        char mesh[MESH_JSON_MAX + 1];
        if (report_detection_json(mesh, sizeof(mesh), &d, 0) > 0) {
            mesh_enqueue(mesh);
            s_last_mesh_report[idx] = now ? now : 1;
        }
    }
    led_blink(40);
}

static void send_heartbeat(bool usb, bool mesh)
{
    HeartbeatReport h = {};
    h.node_id = s_node_id;
    h.receiver = FIRMWARE_RECEIVER;
    h.hw = FIRMWARE_HW;
    h.scanning = s_rf_ok && s_mode == MODE_SCAN;
    h.channels = fpv_channel_count();
    h.sectors = SECTOR_COUNT;
    h.heading = STATION_HEADING_DEG;
    h.threshold_dbm = threshold_dbm();
    h.threshold_level_db = DETECT_LEVEL_DB;
    h.video_seen = (int)s_video_seen;
    h.gain_max = GAIN_MAX;
    h.bw40 = rf_bw40() ? 1 : 0;
    h.fe_gain_db = RF_FRONTEND_GAIN_DB;
    h.tune_fail = s_tune_fail;
    h.cap_err = iq_capture_errors();
    h.bus_stuck = s_bus_stuck;
    h.alias_drop = s_alias_drop;
    h.sweeps = s_sweeps;
    h.usb_drop = s_usb_drop;
    h.mesh_drop = s_mesh_drop;
    h.nf_dbm = s_nf_dbm;
#if SOC_TEMP_SENSOR_SUPPORTED
    h.temp_c = temperatureRead();
#else
    h.temp_c = 0;
#endif
    h.uptime_s = millis() / 1000;
    h.seq = s_seq;
    char buf[USB_JSON_MAX];
    if (usb && report_heartbeat_json(buf, sizeof(buf), &h, 1) > 0) usb_println(buf);
    if (mesh && report_heartbeat_json(buf, MESH_JSON_MAX + 1, &h, 0) > 0) mesh_enqueue(buf);
}

static void print_ready_line()
{
    usb_printf("{\"info\":\"c5phy v3 station ready\",\"node_id\":\"%s\",\"receiver\":\"%s\",\"hw\":\"%s\","
               "\"channels\":%d,\"sectors\":%d,\"heading\":%d,\"fe_gain_db\":%.1f,"
               "\"threshold_dbm\":%.1f,\"threshold_level_db\":%.1f,\"q_min\":%d,\"peak_pick\":%d,"
               "\"video\":%d,\"bw40\":%d,\"gain_max\":%d,\"window_us\":%d,\"iq_lane_bits\":%d,"
               "\"mesh_uart\":\"D4 TX / D5 RX 115200\",\"phy_set_freq\":%s,\"rf\":%s}",
               s_node_id, FIRMWARE_RECEIVER, FIRMWARE_HW, fpv_channel_count(), SECTOR_COUNT, STATION_HEADING_DEG,
               (double)RF_FRONTEND_GAIN_DB, (double)threshold_dbm(), (double)DETECT_LEVEL_DB, Q_MIN, PEAK_PICK,
               VIDEO_CHECK, rf_bw40() ? 1 : 0, GAIN_MAX, (int)(IQ_WINDOW_BYTES * 1000000ULL / IQ_SAMPLE_RATE_HZ),
               demod_lane_bits(), rf_has_phy_set_freq() ? "true" : "false", s_rf_ok ? "true" : "false");
}

// =============================================================================
// Sweep
// =============================================================================
static void service_io();

static void run_sweep()
{
    int n = fpv_channel_count();
    s_nf_level_min = 1e9f;
    for (int i = 0; i < n; i++) {
        scan_channel(i, &s_results[i]);
        service_io();
        if (s_mode != MODE_SCAN) return;
    }
    s_sweeps++;
    if (s_nf_level_min < 1e8f) s_nf_dbm = dbm_from_level(s_nf_level_min);

    // Hits, strongest first.
    int hits[48], nh = 0;
    for (int i = 0; i < n; i++) if (s_results[i].hit) hits[nh++] = i;
    for (int i = 1; i < nh; i++) {
        int k = hits[i], j = i - 1;
        while (j >= 0 && s_results[hits[j]].sec[s_results[hits[j]].best].level_db < s_results[k].sec[s_results[k].best].level_db) {
            hits[j + 1] = hits[j];
            j--;
        }
        hits[j + 1] = k;
    }
    // PEAK_PICK: the same carrier shows on the channels that overlap it (R3 5732,
    // B1 5733, F1 5740); keep the strongest, drop the rest.
    bool drop[48] = {};
    if (PEAK_PICK) {
        for (int i = 0; i < nh; i++) {
            if (drop[i]) continue;
            for (int j = i + 1; j < nh; j++)
                if (!drop[j] && abs((int)fpv_channel(hits[i])->freq_mhz - (int)fpv_channel(hits[j])->freq_mhz) <= PEAK_PICK_MHZ) drop[j] = true;
        }
    }
#if ALIAS_GUARD
    // A synthesizer that did not follow phy_set_freq past the last public centre
    // leaves the receiver at that centre while the firmware believes it is 20-60
    // MHz higher: a carrier near the centre then shows up again, at the same
    // level, on every channel above it. Drop such a mirror image.
    const int top = fpv_wifi_top_centre_mhz();
    for (int i = 0; i < nh; i++) {
        if (drop[i]) continue;
        const FpvChannel* ci = fpv_channel(hits[i]);
        if ((int)ci->freq_mhz <= top) continue;
        float li = s_results[hits[i]].sec[s_results[hits[i]].best].level_db;
        for (int j = 0; j < nh; j++) {
            if (j == i || drop[j]) continue;
            const FpvChannel* cj = fpv_channel(hits[j]);
            if (abs((int)cj->freq_mhz - top) > 5) continue;         // a carrier the parked receiver sees
            float lj = s_results[hits[j]].sec[s_results[hits[j]].best].level_db;
            if (fabsf(li - lj) <= 2.0f) { drop[i] = true; s_alias_drop++; break; }
        }
    }
#endif
    int videos = 0;
    for (int i = 0; i < nh; i++) {
        if (drop[i]) continue;
        bool do_video = videos < VIDEO_MAX_PER_SWEEP;
        if (do_video) videos++;
        report_hit(hits[i], do_video);
        service_io();
        if (s_mode != MODE_SCAN) return;   // a bench 'h' arrived: leave the radio where the console put it
    }
}

// =============================================================================
// Bench console
// =============================================================================
static void print_status()
{
    const FpvChannel* c = s_hold_ch >= 0 ? fpv_channel(s_hold_ch) : nullptr;
    char pattern[SWITCH_PIN_COUNT + 1];
    switch_format_bits(pattern, sizeof(pattern), switch_bits(), SWITCH_PIN_COUNT);
    usb_printf("{\"info\":\"status\",\"node_id\":\"%s\",\"mode\":\"%s\",\"rf\":%s,\"rf_error\":\"%s\","
               "\"ch\":\"%c%d\",\"freq_mhz\":%u,\"wifi_ch\":%u,\"sector\":%d,\"switch\":\"%s\",\"switch_raw\":%d,\"gain\":%d,\"gain_mode\":\"%s\",\"bw40\":%d,"
               "\"captures\":%u,\"cap_err\":%u,\"cap_err_last\":\"%s\",\"bus_stuck\":%u,\"alias_drop\":%u,\"tune_fail\":%u,\"sweeps\":%u,\"video_seen\":%u,"
               "\"nf_dbm\":%.0f,\"usb_drop\":%u,\"mesh_drop\":%u,\"mesh_queued\":%d,\"heap\":%u,\"uptime_s\":%u}",
               s_node_id, s_mode == MODE_SCAN ? "scan" : "hold", s_rf_ok ? "true" : "false", s_rf_ok ? "" : rf_last_call(),
               c ? c->band : '-', c ? c->number : 0, rf_freq_mhz(), rf_wifi_channel(),
               s_switch_raw ? -1 : (s_mode == MODE_HOLD ? s_hold_sector : switch_current()), pattern, s_switch_raw ? 1 : 0,
               s_gain, s_hold_gain >= 0 ? "fixed" : "auto",
               rf_bw40() ? 1 : 0, iq_capture_count(), iq_capture_errors(), iq_capture_last_error(), s_bus_stuck, s_alias_drop, s_tune_fail, s_sweeps,
               s_video_seen, (double)s_nf_dbm, s_usb_drop, s_mesh_drop, s_mesh_count,
               (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL), millis() / 1000);
}

static void hold_channel(const char* arg)
{
    int idx = fpv_find(arg);
    if (idx < 0) { usb_printf("{\"info\":\"error\",\"cmd\":\"h\",\"err\":\"unknown channel %s\"}", arg); return; }
    if (!s_rf_ok) { usb_printf("{\"info\":\"error\",\"cmd\":\"h\",\"err\":\"rf not started: %s\"}", rf_last_call()); return; }
    const FpvChannel* c = fpv_channel(idx);
    esp_err_t e = rf_tune(c->freq_mhz);
    if (e != ESP_OK) {
        s_tune_fail++;
        usb_printf("{\"info\":\"error\",\"cmd\":\"h\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"err\":\"tune refused by regulatory table: %s (%s)\"}",
                   c->band, c->number, c->freq_mhz, rf_last_call(), esp_err_to_name(e));
        return;
    }
    s_mode = MODE_HOLD;
    s_hold_ch = idx;
    delay(TUNE_SETTLE_MS);
    usb_printf("{\"info\":\"hold\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"wifi_ch\":%u,\"sector\":%d}",
               c->band, c->number, c->freq_mhz, rf_wifi_channel(), s_switch_raw ? -1 : s_hold_sector);
}

static void bench_video()
{
    if (s_mode != MODE_HOLD || s_hold_ch < 0) { usb_println("{\"info\":\"error\",\"cmd\":\"v\",\"err\":\"hold a channel first (h R3)\"}"); return; }
    VideoVerdict v;
    VideoResult w[VIDEO_WINDOWS];
    int cfo = 0;
    int gain = s_hold_gain >= 0 ? s_hold_gain : s_gain;
    video_check(s_hold_ch, s_switch_raw ? -1 : s_hold_sector, gain, &v, &cfo, w);   // -1: leave a 't' pattern on the lines
    // Eight window records are ~95 bytes each: the verdict goes on one line, the
    // windows on a second one, each bounded (snprintf returns the length it
    // wanted, never past the buffer; n is clamped so the tail stays in range).
    char buf[USB_JSON_MAX];
    snprintf(buf, sizeof(buf), "{\"info\":\"video\",\"present\":%d,\"std\":\"%s\",\"line_hz\":%d,\"field_hz\":%d,\"sync_q\":%d,\"score\":%d,\"cfo_khz\":%d,\"windows\":%d}",
             v.present, v.std, v.sync_hz, v.field_hz, v.sync_q, v.sync_score, cfo, v.windows);
    usb_println(buf);
    int n = snprintf(buf, sizeof(buf), "{\"info\":\"video_windows\",\"windows\":[");
    for (int i = 0; i < v.windows; i++) {
        int k = snprintf(buf + n, sizeof(buf) - n, "%s{\"video\":%d,\"std\":\"%s\",\"line_hz\":%.0f,\"period\":%.1f,\"score\":%d,\"pulses\":%d,\"periods\":%d,\"swing\":%d,\"pol\":%d}",
                         i ? "," : "", w[i].present, w[i].std, (double)w[i].line_hz, (double)w[i].line_period, w[i].score, w[i].pulses, w[i].periods, w[i].swing, w[i].polarity);
        if (k < 0 || n + k > (int)sizeof(buf) - 3) { buf[n] = 0; break; }   // does not fit: stop, keep what is complete
        n += k;
    }
    snprintf(buf + n, sizeof(buf) - n, "]}");
    usb_println(buf);
}

static void handle_command(char* line)
{
    while (*line == ' ') line++;
    size_t len = strlen(line);
    while (len && (line[len - 1] == ' ' || line[len - 1] == '\r')) line[--len] = 0;
    if (!len) return;
    if (strcmp(line, "WATCHDOG_RESET") == 0 || strcmp(line, "STATUS") == 0) { send_heartbeat(true, false); return; }

    char cmd = line[0];
    char* arg = line + 1;
    while (*arg == ' ') arg++;
    switch (cmd) {
    case '?': print_status(); break;
    case 'h': case 'H': hold_channel(arg); break;
    case 's': case 'S': {
        char pattern[SWITCH_PIN_COUNT + 1];
        if (!*arg) {
            switch_format_bits(pattern, sizeof(pattern), switch_sector_bits(s_hold_sector), SWITCH_PIN_COUNT);
            usb_printf("{\"info\":\"sector\",\"sector\":%d,\"name\":\"%s\",\"pattern\":\"%s\",\"switch_raw\":%d}",
                       s_hold_sector, switch_sector_name(s_hold_sector), pattern, s_switch_raw ? 1 : 0);
            break;
        }
        char* end = nullptr;
        int s = (int)strtol(arg, &end, 10);
        if (end == arg || s < 0 || s >= SECTOR_COUNT) { usb_println("{\"info\":\"error\",\"cmd\":\"s\",\"err\":\"sector 0..3\"}"); break; }
        s_hold_sector = s;
        s_switch_raw = false;           // back from a 't' pattern to the sector table
        switch_select(s);
        switch_format_bits(pattern, sizeof(pattern), switch_bits(), SWITCH_PIN_COUNT);
        usb_printf("{\"info\":\"sector\",\"sector\":%d,\"name\":\"%s\",\"pattern\":\"%s\"}", s, switch_sector_name(s), pattern);
        break;
    }
    case 'g': case 'G':
        if (*arg == 'a' || *arg == 'A' || !*arg) { s_hold_gain = -1; usb_println("{\"info\":\"gain\",\"mode\":\"auto\"}"); }
        else {
            int g = atoi(arg);
            if (g < GAIN_MIN || g > GAIN_MAX) { usb_printf("{\"info\":\"error\",\"cmd\":\"g\",\"err\":\"gain %d..%d\"}", GAIN_MIN, GAIN_MAX); break; }
            s_hold_gain = g;
            set_gain(g);
            usb_printf("{\"info\":\"gain\",\"mode\":\"fixed\",\"gain\":%d}", g);
        }
        break;
    case 'v': case 'V': bench_video(); break;
    case 'x': case 'X':
        s_mode = MODE_SCAN;
        s_hold_ch = -1;
        s_hold_gain = -1;
        s_switch_raw = false;           // the sweep selects every sector itself
        usb_println("{\"info\":\"scan\",\"scanning\":true}");
        break;
    case 't': case 'T': {
        /* Drive the control lines with a raw pattern and keep it there: the bench
         * line, 'v' and '?' use and report it until 's' or 'x'. While scanning
         * every sector is re-selected at once, so a pattern needs a held channel
         * (or a radio that never started, where nothing else drives the lines). */
        uint32_t bits = 0;
        if (switch_parse_bits(arg, SWITCH_PIN_COUNT, &bits) != 0) {
            usb_printf("{\"info\":\"error\",\"cmd\":\"t\",\"err\":\"t <pattern|number>: %d characters of 0/1 in pin order "
                       "(t 100 = first line high), or 0..%u (t 1, t 0x3)\"}", SWITCH_PIN_COUNT, (1u << SWITCH_PIN_COUNT) - 1u);
            break;
        }
        if (s_rf_ok && s_mode == MODE_SCAN) {
            usb_println("{\"info\":\"error\",\"cmd\":\"t\",\"err\":\"hold a channel first (h R3): the sweep re-selects every sector\"}");
            break;
        }
        s_switch_raw = true;
        switch_set_raw(bits);
        char pattern[SWITCH_PIN_COUNT + 1];
        switch_format_bits(pattern, sizeof(pattern), switch_bits(), SWITCH_PIN_COUNT);
        usb_printf("{\"info\":\"switch\",\"bits\":%u,\"pattern\":\"%s\",\"held\":true}", switch_bits(), pattern);
        break;
    }
    case 'b': case 'B':
        if (*arg == '0' || *arg == '1') rf_set_bw40(*arg == '1');
        else if (*arg) { usb_println("{\"info\":\"error\",\"cmd\":\"b\",\"err\":\"b 0|1\"}"); break; }
        usb_printf("{\"info\":\"bw40\",\"bw40\":%d}", rf_bw40() ? 1 : 0);
        break;
    default:
        usb_println("{\"info\":\"help\",\"cmds\":\"? status | h R3|5732 hold | s 0-3 sector | g 30|a gain | v video | x scan | t 100|t 1 switch lines | b 0|1 bw40\"}");
    }
}

static void console_poll()
{
    static char line[96];
    static size_t pos = 0;
    static bool discard = false;      // an overlong line is dropped whole, tail included
    while (Serial.available()) {
        char ch = (char)Serial.read();
        if (ch == '\n' || ch == '\r') {
            line[pos] = 0;
            if (pos && !discard) handle_command(line);
            pos = 0;
            discard = false;
        } else if (discard) {
            continue;
        } else if (pos < sizeof(line) - 1) {
            line[pos++] = ch;
        } else {
            discard = true;
            pos = 0;
        }
    }
}

/* Bench line while holding: the held sector at the held or automatic gain. */
static void hold_service()
{
    static uint32_t last = 0;
    if (!s_rf_ok || s_hold_ch < 0) return;
    if (millis() - last < BENCH_PRINT_MS) return;
    last = millis();
    const FpvChannel* held = fpv_channel(s_hold_ch);
    if (rf_freq_mhz() != held->freq_mhz) {       // a video check in flight moved it: back to the held channel
        if (rf_tune(held->freq_mhz) != ESP_OK) { s_tune_fail++; return; }
        delay(TUNE_SETTLE_MS);
    }
    if (!s_switch_raw) switch_select(s_hold_sector);     // a 't' pattern stays until 's' or 'x'
    IqMetrics m;
    int g = s_gain;
    if (!measure_window(s_hold_gain >= 0 ? s_hold_gain : GAIN_MAX, s_hold_gain < 0, &m, &g)) {
        usb_printf("{\"info\":\"bench\",\"err\":\"capture: %s\",\"cap_err\":%u}", iq_capture_last_error(), iq_capture_errors());
        return;
    }
    float level = level_from(m, g);
    const FpvChannel* c = fpv_channel(s_hold_ch);
    char pattern[SWITCH_PIN_COUNT + 1];
    switch_format_bits(pattern, sizeof(pattern), switch_bits(), SWITCH_PIN_COUNT);
    usb_printf("{\"info\":\"bench\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"wifi_ch\":%u,\"sector\":%d,\"switch\":\"%s\",\"gain\":%d,"
               "\"level_db\":%.1f,\"rssi_dbm\":%.1f,\"p_mean\":%.2f,\"q_phase\":%.0f,\"clip\":%.1f,\"cfo_khz\":%.0f,"
               "\"mod\":%d,\"noise\":%d,\"stuck\":%d,\"step_std\":%.1f,\"nf_dbm\":%.0f,\"captures\":%u,\"cap_err\":%u}",
               c->band, c->number, c->freq_mhz, rf_wifi_channel(), s_switch_raw ? -1 : s_hold_sector, pattern, g,
               (double)level, (double)dbm_from_level(level), (double)m.p_mean, (double)m.q_phase_pct, (double)m.clip_pct,
               (double)m.cfo_khz, m.mod, m.noise, m.stuck, (double)m.step_std_deg, (double)s_nf_dbm, iq_capture_count(), iq_capture_errors());
}

static void service_io()
{
    console_poll();
    mesh_drain();
    led_service();
    uint32_t now = millis();
    if (now - s_last_hb_usb >= HEARTBEAT_USB_S * 1000UL) { s_last_hb_usb = now; send_heartbeat(true, false); }
    if (now - s_last_hb_mesh >= HEARTBEAT_MESH_S * 1000UL) { s_last_hb_mesh = now; send_heartbeat(false, true); }
}

// =============================================================================
// Setup / loop
// =============================================================================
static void make_node_id()
{
    // Id characters only: node_id is written into JSON unescaped and is the
    // station key in the mapper, which accepts the same set.
    size_t n = 0;
    for (const char* p = NODE_ID; *p && n < sizeof(s_node_id) - 1; p++)
        if (isalnum((unsigned char)*p) || *p == '_' || *p == '-' || *p == '.' || *p == ':') s_node_id[n++] = *p;
    s_node_id[n] = 0;
    if (n) return;
    uint8_t mac[6] = {};
    esp_efuse_mac_get_default(mac);
    snprintf(s_node_id, sizeof(s_node_id), "%02X%02X", mac[4], mac[5]);
}

void setup()
{
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, HIGH);

    Serial.setTxBufferSize(4096);
    Serial.begin(115200);
    Serial.setTxTimeoutMs(0);                       // a host that stops reading never stalls the station
    Serial1.setTxBufferSize(1024);
    Serial1.begin(115200, SERIAL_8N1, PIN_MESH_RX, PIN_MESH_TX);
    delay(100);

    make_node_id();
    // IDF's own log lines (a PARLIO timeout prints an ESP_LOGE) go straight to the
    // USB-JTAG FIFO and would interleave with the JSON stream; the station reports
    // the same conditions in its own lines (cap_err, cap_err_last).
    esp_log_level_set("*", ESP_LOG_NONE);
    demod_init_bits(IQ_LANE_BITS);
    switch_init();

    // PARLIO first: it claims the lane pads as inputs, the PHY routing then
    // makes them INPUT_OUTPUT pads driven by the diagnostic bus.
    esp_err_t e = iq_capture_init();
    if (e != ESP_OK) {
        usb_printf("{\"info\":\"error\",\"stage\":\"iq_capture_init\",\"call\":\"%s\",\"err\":\"%s\"}", iq_capture_last_error(), esp_err_to_name(e));
    } else {
        e = rf_start();
        if (e != ESP_OK)
            usb_printf("{\"info\":\"error\",\"stage\":\"rf_start\",\"call\":\"%s\",\"err\":\"%s\"}", rf_last_call(), esp_err_to_name(e));
        else
            s_rf_ok = true;
    }
    if (s_rf_ok) {
        rf_set_gain(GAIN_MAX);
        s_gain = GAIN_MAX;
        rf_set_bw40(BW40 != 0);
    }
    memset(s_last_mesh_report, 0, sizeof(s_last_mesh_report));
    print_ready_line();

    // First heartbeats soon after boot so the mapper registers the station.
    uint32_t now = millis();
    s_last_hb_usb = now - (HEARTBEAT_USB_S - 10) * 1000UL;
    s_last_hb_mesh = now - (HEARTBEAT_MESH_S - 20) * 1000UL;
    led_blink(300);
}

void loop()
{
    service_io();
    if (!s_rf_ok) { delay(50); return; }
    if (s_mode == MODE_SCAN) {
        run_sweep();
    } else {
        hold_service();
        delay(10);
    }
}
