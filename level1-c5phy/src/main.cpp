/*
 * =============================================================================
 * Level 1 station v3 - XIAO ESP32-C5 as the 5.8 GHz FPV receiver
 *
 * Four patch antennas on an SP4T switch feed the C5's own 5 GHz Wi-Fi radio,
 * optionally through one 20 dB LNA + band-pass filter. The PHY is held
 * receive-only on each FPV channel in turn; raw I/Q from the modem's
 * diagnostic bus is captured in 16 KiB windows through PARLIO and measured for
 * power, FM coherence and envelope on every sector. The strongest sector and
 * its two neighbours give an amplitude-comparison bearing (relative to the
 * box's face N; the mapper rotates it by the station heading). An analog hit
 * (coherent, constant envelope) gets a software video check: FM-demodulate
 * eight windows and look for horizontal sync repeating at the PAL or NTSC line
 * period. A channel that stays above threshold with a noise-like envelope is a
 * digital video link candidate: eight more windows confirm it is continuous,
 * lag autocorrelations name the system (802.11 / LTE-like) and interleaved
 * sector windows give its bearing ("type":"wideband"). A strong carrier
 * between table channels is pulled in once onto its centroid. With DUAL_BAND
 * the 2.4 GHz plan G1-G5 is swept too (dual-band patches, no 5.8 GHz filter).
 *
 * Output:
 *   USB Serial          full JSON records for mesh-mapper.py, a boot line, a
 *                       heartbeat every 60 s, and the bench console
 *   Serial1 D4 TX / D5 RX   one Meshtastic text message per report (<= 191 B)
 *                       to a Heltec V4, the same pins as every station tier
 *
 * Bench console (Enter-terminated, on USB):
 *   ?            status           h R3 | h 5732   hold a channel
 *   s 0..3       sector           g 30 | g a      fixed / automatic gain
 *   v            video check on the held channel and sector
 *   w            wideband check on the held channel and sector: confirmation
 *                pass, lag features and a coarse lag scan (~2 s)
 *   b 0 | b 1    analog filter BW20 / BW40        x   resume scanning
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
#include "sweep_decide.h"

// Surveyed position (optional, from STATION_LAT / STATION_LON: see config.h)
#if defined(STATION_LAT) != defined(STATION_LON)
#error "Set both STATION_LAT and STATION_LON, or neither (Station setup writes both)"
#endif
#if defined(STATION_LAT)
static_assert(STATION_LAT >= -90.0 && STATION_LAT <= 90.0, "STATION_LAT must be -90..90 degrees");
static_assert(STATION_LON >= -180.0 && STATION_LON <= 180.0, "STATION_LON must be -180..180 degrees");
#define STATION_HAS_POS 1
#else
#define STATION_HAS_POS 0
#endif
static_assert(STATION_POS_EVERY >= 1, "STATION_POS_EVERY must be 1 or more");
static_assert(MAX_CHANNELS >= 40 + 2 + 3 + 8 + 5, "MAX_CHANNELS must hold the plan with every variant on");

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

static uint32_t s_sweeps = 0, s_tune_fail = 0, s_video_seen = 0, s_wb_seen = 0, s_pullin = 0, s_bus_stuck = 0, s_alias_drop = 0;
static uint32_t s_usb_drop = 0, s_mesh_drop = 0;
static unsigned s_seq = 0;
static uint32_t s_last_hb_usb = 0, s_last_hb_mesh = 0;
static uint32_t s_mesh_hb = 0;          // mesh heartbeats sent: the position rides on some of them
static uint32_t s_led_off_at = 0;
static const float s_az[SECTOR_COUNT] = SECTOR_AZIMUTH_DEG;
static const char* const s_bands = DUAL_BAND ? "2.4+5.8" : "5.8";

/* Per-band calibration and antenna model, filled once in setup() from the
 * config.h constants: [0] the 5 GHz patches, [1] the 2.4 GHz side (DUAL_BAND). */
struct BandCal {
    float noise_power, cal_dbm_at_noise, slope, offset_db, fe_gain_db;
    float antenna_dbi, beamwidth_deg, bearing_k, sigma_base;
};
static BandCal  s_cal[2];
static float    s_nf_level_min[2] = { 1e9f, 1e9f };   // quietest sector level this sweep, per band
static float    s_nf_dbm[2];

struct SectorMeasure {
    int   windows;
    float level_db, level_min, level_max;
    int   gain, q_phase, cfo_khz;
    float cv2;                          // envelope variance / mean^2, median over the windows
    float p_mean, clip_pct;
    int   mod, noise;
};
struct ChannelResult {
    bool tuned, hit, wb;                // hit: analog; wb: wideband candidate (strongest sector)
    int  best;
    SectorMeasure sec[SECTOR_COUNT];
};
static ChannelResult s_results[MAX_CHANNELS];
static uint32_t      s_last_mesh_report[MAX_CHANNELS];

// =============================================================================
// Level and calibration
// =============================================================================
static int band_idx(int freq_mhz) { return DUAL_BAND && fpv_freq_band_ghz(freq_mhz) == 2 ? 1 : 0; }
static const BandCal& cal_for(int freq_mhz) { return s_cal[band_idx(freq_mhz)]; }

/* Antenna -> bearing constants. A Gaussian main lobe is G(phi) = -12 (phi/bw)^2 dB;
 * for four sectors 90 deg apart the neighbour difference is 4320 phi / bw^2 dB, so
 * phi = bw^2 / 4320 per dB. Real patches are gentler 45-135 deg off axis, hence
 * BEARING_K_SCALE (2.5 reproduces the stage 6 K of 3.0 deg/dB at 72 deg). */
static void band_cal_init(BandCal* c, float noise_power, float cal_dbm_at_noise, float slope, float offset_db,
                          float fe_gain_db, float antenna_dbi, float beamwidth_deg, float bearing_k)
{
    c->noise_power = noise_power;
    c->cal_dbm_at_noise = cal_dbm_at_noise;
    c->slope = slope;
    c->offset_db = offset_db;
    c->fe_gain_db = fe_gain_db;
    c->antenna_dbi = antenna_dbi;
    c->beamwidth_deg = beamwidth_deg > 0.0f ? beamwidth_deg : sqrtf(32400.0f / powf(10.0f, antenna_dbi / 10.0f));
    c->bearing_k = bearing_k > 0.0f ? bearing_k : BEARING_K_SCALE * c->beamwidth_deg * c->beamwidth_deg / 4320.0f;
    c->sigma_base = BEARING_SIGMA_BASE_DEG * c->beamwidth_deg / 72.0f;
}

static float level_from(const IqMetrics& m, int gain, const BandCal& c)
{
    float p = m.p_mean > 0.05f ? m.p_mean : 0.05f;
    return (float)(GAIN_MAX - gain) + 10.0f * log10f(p / c.noise_power);
}
static float dbm_from_level(float level_db, const BandCal& c)
{
    return c.cal_dbm_at_noise + level_db * c.slope + c.offset_db - c.fe_gain_db;
}
static float threshold_dbm(const BandCal& c) { return dbm_from_level(DETECT_LEVEL_DB, c); }

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

/* One mesh line per emitter (table channel) per MESH_REPORT_INTERVAL_MS; the
 * first one at once. The zero slot means "never", so a send at millis() 0
 * is stamped 1. */
static bool mesh_report_due(int idx, uint32_t now)
{
    if (idx < 0 || idx >= MAX_CHANNELS) return false;
    return s_last_mesh_report[idx] == 0 || now - s_last_mesh_report[idx] >= MESH_REPORT_INTERVAL_MS;
}
static void mesh_report_sent(int idx, uint32_t now)
{
    if (idx >= 0 && idx < MAX_CHANNELS) s_last_mesh_report[idx] = now ? now : 1;
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
static float median3f(float a, float b, float c)
{
    if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
    if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
    return c;
}

/* measure_sector: select the patch, start at full gain, take up to
 * WINDOWS_PER_SECTOR windows (one on a quiet channel). level = minimum over
 * the windows (a Wi-Fi burst raises one window, not all), q and cv2 = median. */
static void measure_sector(int sector, SectorMeasure* sm, int fixed_gain, int band)
{
    const BandCal& cal = s_cal[band];
    memset(sm, 0, sizeof(*sm));
    switch_select(sector);
    float levels[WINDOWS_PER_SECTOR], cv2s[WINDOWS_PER_SECTOR];
    int   qs[WINDOWS_PER_SECTOR], cfos[WINDOWS_PER_SECTOR];
    int   n = 0, gain = fixed_gain >= 0 ? fixed_gain : GAIN_MAX;
    IqMetrics m = {};
    for (int w = 0; w < WINDOWS_PER_SECTOR; w++) {
        int g = gain;
        if (!measure_window(gain, fixed_gain < 0, &m, &g)) break;
        gain = g;
        levels[n] = level_from(m, g, cal);
        qs[n] = (int)(m.q_phase_pct + 0.5f);
        cfos[n] = (int)lrintf(m.cfo_khz);
        cv2s[n] = m.env_cv2;
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
    sm->cv2 = n == 3 ? median3f(cv2s[0], cv2s[1], cv2s[2]) : (n == 2 ? 0.5f * (cv2s[0] + cv2s[1]) : cv2s[0]);
    sm->gain = gain;
    sm->p_mean = m.p_mean;
    sm->clip_pct = m.clip_pct;
    sm->mod = m.mod;
    sm->noise = m.noise;
    if (sm->level_db < s_nf_level_min[band]) s_nf_level_min[band] = sm->level_db;
}

/* scan_freq: tune to any MHz (a table channel, or a pull-in target), measure
 * the four sectors, decide. An analog hit needs the level AND the FM coherence
 * AND a constant envelope on the strongest sector: a carrier 10 MHz off steps
 * 90 degrees per sample and never counts as coherent, so a neighbour inside
 * the 40 MHz filter raises the level but is not a hit; OFDM reads cv2 ~1. A
 * wideband candidate is the opposite: every window above threshold within
 * WB_LEVEL_SPREAD_DB (continuous over ~1.5 ms) with a noise-like envelope
 * (measure_sector takes all three windows once the first is above threshold
 * - QUIET_MARGIN_DB). */
static void scan_freq(uint16_t mhz, ChannelResult* r)
{
    memset(r, 0, sizeof(*r));
    const int band = band_idx(mhz);
    if (rf_tune(mhz) != ESP_OK) { s_tune_fail++; return; }
    r->tuned = true;
    delay(TUNE_SETTLE_MS);
    for (int s = 0; s < SECTOR_COUNT; s++) measure_sector(s, &r->sec[s], -1, band);
    r->best = 0;
    for (int s = 1; s < SECTOR_COUNT; s++)
        if (r->sec[s].windows && (!r->sec[r->best].windows || r->sec[s].level_db > r->sec[r->best].level_db)) r->best = s;
    const SectorMeasure& b = r->sec[r->best];
    r->hit = b.windows > 0 && b.level_db >= DETECT_LEVEL_DB && b.q_phase >= Q_MIN && b.cv2 <= ANALOG_CV2_MAX;
    r->wb = WIDEBAND && !r->hit && b.windows == WINDOWS_PER_SECTOR && b.level_min >= DETECT_LEVEL_DB &&
            b.level_max - b.level_min <= WB_LEVEL_SPREAD_DB && b.cv2 >= WB_CV2_MIN && b.cv2 <= WB_CV2_MAX;
}

/* Video check: hold the frequency and the sector, demodulate VIDEO_WINDOWS
 * windows VIDEO_WINDOW_GAP_MS apart and look for the PAL / NTSC line period. */
static void video_check(uint16_t mhz, int sector, int gain, VideoVerdict* v, int* cfo_khz, VideoResult* windows_out)
{
    VideoResult vr[VIDEO_WINDOWS];
    int n = 0;
    float cfo_sum = 0;
    memset(v, 0, sizeof(*v));
    strcpy(v->std, "none");
    if (rf_freq_mhz() != mhz) {
        if (rf_tune(mhz) != ESP_OK) { s_tune_fail++; return; }
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

/* Wideband confirmation pass: hold the frequency and the sector at the gain the
 * sweep measured, WB_WINDOWS windows WB_WINDOW_GAP_MS apart, each with the
 * metrics and the lag features (~10 ms per window: nine passes over 16 K
 * samples). A window is "on" within WB_DUTY_DB of the loudest; duty is their
 * share, the features and the centroid are averaged over them. */
struct WbCheck {
    int   windows, on, duty;            // captured, "on", percent on
    float level_db, level_min, level_max;   // mean of the on windows; min / max over all
    int   gain, q_phase, cfo_khz;
    float fc_mhz, cv2;
    IqLagFeatures f;
    const char* cls;                    // "lte" | "dot11" | "wb"
    const char* conf;                   // "high" | "med" | "low"
    int   bw_mhz;                       // 10 | 20 | 30 | 40
    uint8_t* last;                      // the last window, valid until the next capture (bench lag scan)
};

/* Class from the lag features, confidence from the duty and the deciding
 * feature's margin, bandwidth bucket from the one-sample autocorrelation
 * (model: LTE-like 9 MHz 0.85, 802.11 20 MHz 0.67, 40 MHz 0.06). Noise
 * decorrelates at lag 1, so r1 reads S/(S+N) of the waveform's own value
 * (model: LTE-like 0.85 at S/N 30 dB, 0.80 at 12 dB, under the 0.78 edge by
 * 10 dB): the bucket is taken on r1 scaled back by (S+N)/S from level_db,
 * the reported r1 stays the raw feature. */
static void wb_classify(WbCheck* w)
{
    float key = 0.0f, key_high = 1.0f;
    if (w->f.r2667 >= WB_R2667_MIN && w->f.r128 < WB_R128_LTE_MAX) { w->cls = "lte"; key = w->f.r2667; key_high = WB_R2667_HIGH; }
    else if (w->f.r128 >= WB_R128_MIN) { w->cls = "dot11"; key = w->f.r128; key_high = WB_R128_HIGH; }
    else w->cls = "wb";
    bool named = w->cls[0] != 'w';
    w->conf = named && w->duty >= 90 && key >= key_high ? "high" : (named && w->duty >= WB_DUTY_MIN ? "med" : "low");
    float r1 = w->f.r1 * (1.0f + powf(10.0f, -w->level_db / 10.0f));
    if (r1 > 1.0f) r1 = 1.0f;
    w->bw_mhz = r1 >= 0.78f ? 10 : (r1 >= 0.52f ? 20 : (r1 >= 0.30f ? 30 : 40));
}

static bool wideband_check(uint16_t mhz, int sector, int gain, WbCheck* w)
{
    memset(w, 0, sizeof(*w));
    const BandCal& cal = cal_for(mhz);
    if (rf_freq_mhz() != mhz) {
        if (rf_tune(mhz) != ESP_OK) { s_tune_fail++; return false; }
        delay(TUNE_SETTLE_MS);
    }
    switch_select(sector);
    set_gain(gain);
    float levels[WB_WINDOWS], cv2[WB_WINDOWS], cfo[WB_WINDOWS], q[WB_WINDOWS];
    IqLagFeatures lf[WB_WINDOWS];
    int n = 0;
    for (int k = 0; k < WB_WINDOWS; k++) {
        uint8_t* buf = nullptr;
        IqMetrics m;
        if (capture_metrics(&m, &buf)) {
            levels[n] = level_from(m, gain, cal);
            cv2[n] = m.env_cv2;
            cfo[n] = m.cfo_khz;
            q[n] = m.q_phase_pct;
            iq_lag_features(buf, IQ_WINDOW_BYTES, &lf[n]);
            w->last = buf;
            n++;
        }
        delay(WB_WINDOW_GAP_MS);
    }
    if (n == 0) return false;
    w->windows = n;
    w->gain = gain;
    w->level_min = w->level_max = levels[0];
    for (int i = 1; i < n; i++) {
        if (levels[i] < w->level_min) w->level_min = levels[i];
        if (levels[i] > w->level_max) w->level_max = levels[i];
    }
    float lsum = 0, csum = 0, fsum = 0, qsum = 0;
    for (int i = 0; i < n; i++) {
        if (levels[i] < w->level_max - WB_DUTY_DB) continue;
        w->on++;
        lsum += levels[i]; csum += cv2[i]; fsum += cfo[i]; qsum += q[i];
        w->f.r1 += lf[i].r1; w->f.r4 += lf[i].r4; w->f.r128 += lf[i].r128; w->f.r512 += lf[i].r512; w->f.r2667 += lf[i].r2667;
    }
    float inv = 1.0f / (float)w->on;           // on >= 1: the loudest window itself
    w->duty = 100 * w->on / n;
    w->level_db = lsum * inv;
    w->cv2 = csum * inv;
    w->q_phase = (int)lrintf(qsum * inv);
    w->cfo_khz = (int)lrintf(fsum * inv);
    w->fc_mhz = (float)mhz + fsum * inv / 1000.0f;
    w->f.r1 *= inv; w->f.r4 *= inv; w->f.r128 *= inv; w->f.r512 *= inv; w->f.r2667 *= inv;
    wb_classify(w);
    return true;
}

// =============================================================================
// Reporting
// =============================================================================
/* Analog report for a measured ChannelResult. idx is the table channel it is
 * keyed to (identity, mesh pacing); tuned_mhz is where the radio measured it,
 * the channel itself in the sweep and the centroid for a pull-in. videos is
 * the sweep's budget of (slow) video checks, strongest hits first. */
static void report_hit(const ChannelResult& r, int idx, uint16_t tuned_mhz, int* videos)
{
    const FpvChannel* c = fpv_channel(idx);
    const SectorMeasure& b = r.sec[r.best];
    const BandCal& cal = cal_for(tuned_mhz);
    const int band = band_idx(tuned_mhz);

    float levels[SECTOR_COUNT], dbm[SECTOR_COUNT];
    int valid[SECTOR_COUNT];
    for (int s = 0; s < SECTOR_COUNT; s++) {
        valid[s] = r.sec[s].windows > 0;
        /* a sector whose capture failed is reported at the sweep's noise floor, not at a
         * fantasy -30 dB that would throw the bearing to the clamp */
        levels[s] = valid[s] ? r.sec[s].level_db : (s_nf_level_min[band] < 1e8f ? s_nf_level_min[band] : 0.0f);
        dbm[s] = dbm_from_level(levels[s], cal);
    }
    BearingResult br;
    bearing_estimate_masked(levels, valid, s_az, SECTOR_COUNT, cal.bearing_k, BEARING_MAX_OFFSET_DEG,
                            cal.sigma_base, DETECT_LEVEL_DB, &br);

    VideoVerdict vv = {};
    strcpy(vv.std, "none");
    int cfo = b.cfo_khz;
    if (VIDEO_CHECK && *videos < VIDEO_MAX_PER_SWEEP) {
        (*videos)++;
        video_check(tuned_mhz, r.best, b.gain, &vv, &cfo, nullptr);
        if (vv.present) s_video_seen++;
    }
    cfo += ((int)tuned_mhz - c->freq_mhz) * 1000;   // a pull-in measured off its table channel: cfo_khz and
                                                    // freq_peak stay relative to freq_mhz, as in a plain hit

    DetectionReport d = {};
    d.node_id = s_node_id;
    d.receiver = FIRMWARE_RECEIVER;
    d.hw = FIRMWARE_HW;
    d.band = c->band;
    d.ch = c->number;
    d.freq_mhz = c->freq_mhz;
    d.rssi_dbm = dbm_from_level(b.level_db, cal);
    d.rssi_min_dbm = dbm_from_level(b.level_min, cal);
    d.rssi_max_dbm = dbm_from_level(b.level_max, cal);
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
    if (mesh_report_due(idx, now)) {
        char mesh[MESH_JSON_MAX + 1];
        if (report_detection_json(mesh, sizeof(mesh), &d, 0) > 0) {
            mesh_enqueue(mesh);
            mesh_report_sent(idx, now);
        }
    }
    led_blink(40);
}

#if WIDEBAND
/* Wideband report for a sweep candidate: the confirmation pass on its strongest
 * sector, then, if the link is on for WB_DUTY_MIN percent of the windows, one
 * window per sector in the order N E S W W S E N at the same gain (a bursty
 * link changing between sectors cannot masquerade as a bearing), the maximum
 * per sector feeding the bearing with the band's K and a wider sigma: the
 * levels of a noise-like signal at ~3 LSB rms are coarser, and a duty under
 * 100 % adds 0.2 deg per missing percent. span_mhz is the width of the
 * footprint across the table channels folded into this candidate. */
static void report_wideband(int idx, int span_mhz)
{
    const ChannelResult& r = s_results[idx];
    const FpvChannel* c = fpv_channel(idx);
    const SectorMeasure& b = r.sec[r.best];
    const BandCal& cal = cal_for(c->freq_mhz);
    const int band = band_idx(c->freq_mhz);

    WbCheck w;
    if (!wideband_check(c->freq_mhz, r.best, b.gain, &w)) return;
    if (w.duty < WB_DUTY_MIN) return;

    float levels[SECTOR_COUNT] = {}, dbm[SECTOR_COUNT];
    int valid[SECTOR_COUNT] = {};
    for (int k = 0; k < 2 * SECTOR_COUNT; k++) {
        int s = k < SECTOR_COUNT ? k : 2 * SECTOR_COUNT - 1 - k;
        switch_select(s);
        IqMetrics m;
        if (!capture_metrics(&m, nullptr)) continue;
        float l = level_from(m, w.gain, cal);
        if (!valid[s] || l > levels[s]) levels[s] = l;
        valid[s] = 1;
    }
    if (!valid[r.best]) { levels[r.best] = w.level_max; valid[r.best] = 1; }   // the pass just measured it
    for (int s = 0; s < SECTOR_COUNT; s++) {
        if (!valid[s]) levels[s] = s_nf_level_min[band] < 1e8f ? s_nf_level_min[band] : 0.0f;
        dbm[s] = dbm_from_level(levels[s], cal);
    }
    BearingResult br;
    bearing_estimate_masked(levels, valid, s_az, SECTOR_COUNT, cal.bearing_k, BEARING_MAX_OFFSET_DEG,
                            cal.sigma_base + WB_SIGMA_EXTRA_DEG, DETECT_LEVEL_DB, &br);
    float sigma = br.sigma_deg + (float)(100 - w.duty) * 0.2f;
    s_wb_seen++;

    WidebandReport d = {};
    d.node_id = s_node_id;
    d.receiver = FIRMWARE_RECEIVER;
    d.hw = FIRMWARE_HW;
    d.band = c->band;
    d.ch = c->number;
    d.freq_mhz = c->freq_mhz;
    d.fc_mhz = w.fc_mhz;
    d.cfo_khz = w.cfo_khz;
    d.rssi_dbm = dbm_from_level(w.level_db, cal);
    d.rssi_min_dbm = dbm_from_level(w.level_min, cal);
    d.rssi_max_dbm = dbm_from_level(w.level_max, cal);
    d.rssi_n = w.windows;
    d.level_db = w.level_db;
    d.gain = w.gain;
    d.q_phase = w.q_phase;
    d.cls = w.cls;
    d.conf = w.conf;
    d.bw_mhz = w.bw_mhz;
    d.duty_pct = w.duty;
    d.cv2 = w.cv2;
    d.r1 = w.f.r1;
    d.r128 = w.f.r128;
    d.r512 = w.f.r512;
    d.r2667 = w.f.r2667;
    d.span_mhz = span_mhz;
    d.sectors_dbm = dbm;
    d.sector_count = SECTOR_COUNT;
    d.sector = br.sector;
    d.bearing_deg = (int)lrintf(br.bearing_deg) % 360;
    d.bearing_sigma_deg = (int)lrintf(sigma);
    d.heading = STATION_HEADING_DEG;
    d.seq = ++s_seq;

    char usb[USB_JSON_MAX];
    if (report_wideband_json(usb, sizeof(usb), &d, 1) > 0) usb_println(usb);

    uint32_t now = millis();
    if (mesh_report_due(idx, now)) {
        char mesh[MESH_JSON_MAX + 1];
        if (report_wideband_json(mesh, sizeof(mesh), &d, 0) > 0) {
            mesh_enqueue(mesh);
            mesh_report_sent(idx, now);
        }
    }
    led_blink(40);
}
#endif

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
    h.threshold_dbm = threshold_dbm(s_cal[0]);
    h.threshold_level_db = DETECT_LEVEL_DB;
    h.video_seen = (int)s_video_seen;
    h.gain_max = GAIN_MAX;
    h.bw40 = rf_bw40() ? 1 : 0;
    h.fe_gain_db = s_cal[0].fe_gain_db;
    h.bands = s_bands;
    h.antenna_dbi = s_cal[0].antenna_dbi;
    h.beamwidth_deg = (int)lrintf(s_cal[0].beamwidth_deg);
    h.bearing_k = s_cal[0].bearing_k;
    h.wb_seen = (int)s_wb_seen;
    h.pullin = s_pullin;
    h.tune_fail = s_tune_fail;
    h.cap_err = iq_capture_errors();
    h.bus_stuck = s_bus_stuck;
    h.alias_drop = s_alias_drop;
    h.sweeps = s_sweeps;
    h.usb_drop = s_usb_drop;
    h.mesh_drop = s_mesh_drop;
    h.nf_dbm = s_nf_dbm[0];
#if DUAL_BAND
    h.nf_dbm_24 = s_nf_dbm[1];                      // USB line only: the mesh line has no room for a second floor
    h.has_nf_24 = 1;
#endif
#if SOC_TEMP_SENSOR_SUPPORTED
    h.temp_c = temperatureRead();
#else
    h.temp_c = 0;
#endif
    h.uptime_s = millis() / 1000;
    h.seq = s_seq;
    char buf[USB_JSON_MAX];
#if STATION_HAS_POS
    h.lat = STATION_LAT;
    h.lon = STATION_LON;
#endif
    h.has_pos = STATION_HAS_POS;                    // USB: every heartbeat
    if (usb && report_heartbeat_json(buf, sizeof(buf), &h, 1) > 0) usb_println(buf);
    if (mesh) {
        // Mesh: the first 3 after boot, then every STATION_POS_EVERY-th. A mapper keeps
        // the position once it has it, and the 191-byte line has no room for it in every
        // heartbeat without pushing out uptime and temperature.
        h.has_pos = STATION_HAS_POS && (s_mesh_hb < 3 || s_mesh_hb % STATION_POS_EVERY == 0);
        s_mesh_hb++;
        if (report_heartbeat_json(buf, MESH_JSON_MAX + 1, &h, 0) > 0) mesh_enqueue(buf);
    }
}

static void print_ready_line()
{
    char pos[48] = "";
#if STATION_HAS_POS
    snprintf(pos, sizeof(pos), ",\"lat\":%.6f,\"lon\":%.6f", (double)STATION_LAT, (double)STATION_LON);
#endif
    usb_printf("{\"info\":\"c5phy v3 station ready\",\"node_id\":\"%s\",\"receiver\":\"%s\",\"hw\":\"%s\","
               "\"channels\":%d,\"sectors\":%d,\"heading\":%d%s,\"fe_gain_db\":%.1f,"
               "\"threshold_dbm\":%.1f,\"threshold_level_db\":%.1f,\"q_min\":%d,\"peak_pick\":%d,"
               "\"video\":%d,\"bw40\":%d,\"gain_max\":%d,\"window_us\":%d,\"iq_lane_bits\":%d,"
               "\"bands\":\"%s\",\"antenna_dbi\":%.1f,\"beamwidth_deg\":%d,\"bearing_k\":%.2f,"
               "\"wideband\":%d,\"pullin\":%d,\"gain_step\":%d,"
               "\"mesh_uart\":\"D4 TX / D5 RX 115200\",\"phy_set_freq\":%s,\"rf\":%s}",
               s_node_id, FIRMWARE_RECEIVER, FIRMWARE_HW, fpv_channel_count(), SECTOR_COUNT, STATION_HEADING_DEG, pos,
               (double)s_cal[0].fe_gain_db, (double)threshold_dbm(s_cal[0]), (double)DETECT_LEVEL_DB, Q_MIN, PEAK_PICK,
               VIDEO_CHECK, rf_bw40() ? 1 : 0, GAIN_MAX, (int)(IQ_WINDOW_BYTES * 1000000ULL / IQ_SAMPLE_RATE_HZ),
               demod_lane_bits(), s_bands, (double)s_cal[0].antenna_dbi, (int)lrintf(s_cal[0].beamwidth_deg), (double)s_cal[0].bearing_k,
               WIDEBAND, PULLIN, GAIN_STEP,
               rf_has_phy_set_freq() ? "true" : "false", s_rf_ok ? "true" : "false");
}

// =============================================================================
// Sweep
// =============================================================================
static void service_io();

#if PULLIN
/* The centroid an off-channel carrier asks to be pulled in to, or 0: a strong
 * constant-envelope carrier that fails the coherence gate with |cfo| from
 * PULLIN_MIN_KHZ, inside the band's tuning window. */
static int pullin_target(const ChannelResult& r, int freq_mhz)
{
    const SectorMeasure& b = r.sec[r.best];
    if (r.hit || b.windows == 0 || b.level_db < DETECT_LEVEL_DB || b.q_phase >= Q_MIN || b.cv2 > ANALOG_CV2_MAX) return 0;
    if (abs(b.cfo_khz) < PULLIN_MIN_KHZ) return 0;
    int target = freq_mhz + (int)lrintf(b.cfo_khz / 1000.0f);
    return fpv_wifi_bootstrap(target, nullptr, nullptr) ? target : 0;
}
#endif

/* The decision stage of the sweep lives in sweep_decide.c (plain C, host
 * tested): run_sweep fills its view of the channels and acts on its answers. */
static SweepChannel s_sweep_ch[MAX_CHANNELS];
static SweepAnalog  s_sweep_an;
static_assert(MAX_CHANNELS <= SWEEP_MAX_CHANNELS, "sweep_decide.h bounds the per-channel arrays");
static_assert(WB_MAX_PER_SWEEP <= SWEEP_MAX_PASSES && PULLIN_MAX_PER_SWEEP <= SWEEP_MAX_PASSES,
              "sweep_decide.h bounds the passes per sweep");

static SweepRules sweep_rules()
{
    SweepRules r;
    r.peak_pick      = PEAK_PICK;
    r.peak_pick_mhz  = PEAK_PICK_MHZ;
    r.alias_guard    = ALIAS_GUARD;
    r.top_centre_mhz = fpv_wifi_top_centre_mhz();
    r.alias_level_db = ALIAS_LEVEL_DB;
    r.alias_near_mhz = ALIAS_NEAR_MHZ;
    r.pullin_max     = PULLIN_MAX_PER_SWEEP;
    r.wb_fold_mhz    = WB_FOLD_MHZ;
    r.wb_own_mhz     = WB_ANALOG_OWN_MHZ;
    r.wb_max         = WB_MAX_PER_SWEEP;
    return r;
}

static void run_sweep()
{
    int n = fpv_channel_count();
    if (n > MAX_CHANNELS) n = MAX_CHANNELS;         // the plan is 58 at most; the arrays are the bound
    s_nf_level_min[0] = s_nf_level_min[1] = 1e9f;
    for (int i = 0; i < n; i++) {
        scan_freq(fpv_channel(i)->freq_mhz, &s_results[i]);
        service_io();
        if (s_mode != MODE_SCAN) return;
    }
    s_sweeps++;
    for (int b = 0; b < 2; b++)
        if (s_nf_level_min[b] < 1e8f) s_nf_dbm[b] = dbm_from_level(s_nf_level_min[b], s_cal[b]);

    for (int i = 0; i < n; i++) {
        const ChannelResult& r = s_results[i];
        s_sweep_ch[i].freq_mhz = fpv_channel(i)->freq_mhz;
        s_sweep_ch[i].level_db = r.sec[r.best].level_db;
        s_sweep_ch[i].hit = r.hit;
        s_sweep_ch[i].wb = r.wb;
    }
    const SweepRules rules = sweep_rules();

    // Analog hits, strongest first: PEAK_PICK folds the same carrier seen on
    // overlapping channels (R3 5732, B1 5733, F1 5740) into the strongest;
    // ALIAS_GUARD drops the mirror a parked synthesizer shows above the top
    // public centre (see sweep_decide.c).
    sweep_analog(s_sweep_ch, n, &rules, &s_sweep_an);
    s_alias_drop += s_sweep_an.alias_dropped;
    int videos = 0;
    for (int i = 0; i < s_sweep_an.nh; i++) {
        if (s_sweep_an.drop[i]) continue;
        const int idx = s_sweep_an.hits[i];
        report_hit(s_results[idx], idx, fpv_channel(idx)->freq_mhz, &videos);
        service_io();
        if (s_mode != MODE_SCAN) return;   // a bench 'h' arrived: leave the radio where the console put it
    }

    int owners[SWEEP_MAX_PASSES], n_owners = 0;     // analog carriers found off the table this sweep
#if PULLIN
    // Pull-in: a strong constant-envelope carrier between table channels fails
    // the coherence gate on both neighbours; its centroid is in cfo_khz. One
    // retune onto it and the four sectors again; a hit there is reported keyed
    // to the nearest table channel with freq_peak at the centroid, and owns
    // the wideband candidates around it like a table-channel hit.
    int targets[MAX_CHANNELS], tries[SWEEP_MAX_PASSES];
    for (int i = 0; i < n; i++) targets[i] = pullin_target(s_results[i], fpv_channel(i)->freq_mhz);
    const int nt = sweep_pullin(s_sweep_ch, targets, n, &s_sweep_an, &rules, tries);
    for (int t = 0; t < nt; t++) {
        s_pullin++;
        ChannelResult pr;
        scan_freq((uint16_t)tries[t], &pr);
        int key = fpv_nearest(tries[t]);
        if (pr.hit && key >= 0) {
            report_hit(pr, key, (uint16_t)tries[t], &videos);
            owners[n_owners++] = tries[t];
        }
        service_io();
        if (s_mode != MODE_SCAN) return;
    }
#endif

#if WIDEBAND
    // Wideband candidates, strongest first: the mirror test, the fold within
    // WB_FOLD_MHZ (span_mhz keeps the footprint), and an analog carrier within
    // WB_ANALOG_OWN_MHZ owns the candidate: its sidebands, and the image the
    // filter skirt makes of a strong FM carrier, are not a second emitter.
    SweepWideband wb;
    sweep_wideband(s_sweep_ch, n, &s_sweep_an, owners, n_owners, &rules, &wb);
    s_alias_drop += wb.alias_dropped;
    for (int i = 0; i < wb.n; i++) {
        report_wideband(wb.idx[i], wb.span_mhz[i]);
        service_io();
        if (s_mode != MODE_SCAN) return;
    }
#else
    (void)owners; (void)n_owners;
#endif
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
               "\"ch\":\"%c%d\",\"freq_mhz\":%u,\"wifi_ch\":%u,\"band\":%u,\"sector\":%d,\"switch\":\"%s\",\"switch_raw\":%d,\"gain\":%d,\"gain_mode\":\"%s\",\"bw40\":%d,"
               "\"captures\":%u,\"cap_err\":%u,\"cap_err_last\":\"%s\",\"bus_stuck\":%u,\"alias_drop\":%u,\"tune_fail\":%u,\"sweeps\":%u,\"video_seen\":%u,"
               "\"wb_seen\":%u,\"pullin\":%u,\"nf_dbm\":%.0f,\"usb_drop\":%u,\"mesh_drop\":%u,\"mesh_queued\":%d,\"heap\":%u,\"uptime_s\":%u}",
               s_node_id, s_mode == MODE_SCAN ? "scan" : "hold", s_rf_ok ? "true" : "false", s_rf_ok ? "" : rf_last_call(),
               c ? c->band : '-', c ? c->number : 0, rf_freq_mhz(), rf_wifi_channel(), rf_band_ghz(),
               s_switch_raw ? -1 : (s_mode == MODE_HOLD ? s_hold_sector : switch_current()), pattern, s_switch_raw ? 1 : 0,
               s_gain, s_hold_gain >= 0 ? "fixed" : "auto",
               rf_bw40() ? 1 : 0, iq_capture_count(), iq_capture_errors(), iq_capture_last_error(), s_bus_stuck, s_alias_drop, s_tune_fail, s_sweeps,
               s_video_seen, s_wb_seen, s_pullin, (double)s_nf_dbm[0], s_usb_drop, s_mesh_drop, s_mesh_count,
               (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL), (unsigned)(millis() / 1000));
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
        usb_printf("{\"info\":\"error\",\"cmd\":\"h\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"err\":\"tune failed: %s (%s)\"}",
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
    video_check(fpv_channel(s_hold_ch)->freq_mhz, s_switch_raw ? -1 : s_hold_sector, gain, &v, &cfo, w);   // -1: leave a 't' pattern on the lines
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

/* 'w': the confirmation pass on the held channel and sector, then a coarse lag
 * scan of the last window for the symbol period of whatever is there. One
 * 410 us window is enough for the 802.11 peak (0.18, ten sigma over the scan's
 * own noise), not quite for the LTE-like CP peak (0.05 against a noise maximum
 * of ~0.04 over 1760 lags): expect scan_lag in 2665..2669 on most presses, not
 * all. cls comes from the features averaged over the whole pass. */
static void bench_wideband()
{
    if (s_mode != MODE_HOLD || s_hold_ch < 0) { usb_println("{\"info\":\"error\",\"cmd\":\"w\",\"err\":\"hold a channel first (h R3)\"}"); return; }
    const FpvChannel* c = fpv_channel(s_hold_ch);
    int gain = s_hold_gain >= 0 ? s_hold_gain : s_gain;
    WbCheck w;
    if (!wideband_check(c->freq_mhz, s_switch_raw ? -1 : s_hold_sector, gain, &w)) {   // -1: leave a 't' pattern on the lines
        usb_printf("{\"info\":\"error\",\"cmd\":\"w\",\"err\":\"capture: %s\",\"cap_err\":%u}", iq_capture_last_error(), iq_capture_errors());
        return;
    }
    // 40..3200 (step 1 below 400, 2 above) is ~1760 passes, about two seconds. Four
    // stretches with a delay(1) between them keep the idle task fed; the console is
    // not polled in between, since a 'v' would capture over the window being scanned.
    static const int edges[] = { 40, 400, 1200, 2200, 3201 };
    int scan_lag = 0;
    float scan_r = 0.0f;
    for (int k = 0; k + 1 < (int)(sizeof(edges) / sizeof(edges[0])); k++) {
        float r = 0.0f;
        int lag = iq_lag_scan(w.last, IQ_WINDOW_BYTES, edges[k], edges[k + 1] - 1, &r);
        if (r > scan_r) { scan_r = r; scan_lag = lag; }
        delay(1);
    }
    usb_printf("{\"info\":\"wideband\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"level_db\":%.1f,\"duty\":%d,\"cls\":\"%s\",\"conf\":\"%s\",\"bw_mhz\":%d,"
               "\"fc_mhz\":%.1f,\"cv2\":%.2f,\"r1\":%.2f,\"r4\":%.2f,\"r128\":%.3f,\"r512\":%.3f,\"r2667\":%.3f,\"scan_lag\":%d,\"scan_r\":%.3f}",
               c->band, c->number, c->freq_mhz, (double)w.level_db, w.duty, w.cls, w.conf, w.bw_mhz,
               (double)w.fc_mhz, (double)w.cv2, (double)w.f.r1, (double)w.f.r4, (double)w.f.r128, (double)w.f.r512, (double)w.f.r2667,
               scan_lag, (double)scan_r);
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
    case 'w': case 'W': bench_wideband(); break;
    case 'x': case 'X':
        s_mode = MODE_SCAN;
        s_hold_ch = -1;
        s_hold_gain = -1;
        s_switch_raw = false;           // the sweep selects every sector itself
        usb_println("{\"info\":\"scan\",\"scanning\":true}");
        break;
    case 't': case 'T': {
        /* Drive the control lines with a raw pattern and keep it there: the bench
         * line, 'v', 'w' and '?' use and report it until 's' or 'x'. While scanning
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
        usb_println("{\"info\":\"help\",\"cmds\":\"? status | h R3|5732 hold | s 0-3 sector | g 30|a gain | v video | w wideband | x scan | t 100|t 1 switch lines | b 0|1 bw40\"}");
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
    const FpvChannel* c = fpv_channel(s_hold_ch);
    if (rf_freq_mhz() != c->freq_mhz) {          // a video check in flight moved it: back to the held channel
        if (rf_tune(c->freq_mhz) != ESP_OK) { s_tune_fail++; return; }
        delay(TUNE_SETTLE_MS);
    }
    if (!s_switch_raw) switch_select(s_hold_sector);     // a 't' pattern stays until 's' or 'x'
    IqMetrics m;
    int g = s_gain;
    if (!measure_window(s_hold_gain >= 0 ? s_hold_gain : GAIN_MAX, s_hold_gain < 0, &m, &g)) {
        usb_printf("{\"info\":\"bench\",\"err\":\"capture: %s\",\"cap_err\":%u}", iq_capture_last_error(), iq_capture_errors());
        return;
    }
    const BandCal& cal = cal_for(c->freq_mhz);
    float level = level_from(m, g, cal);
    char pattern[SWITCH_PIN_COUNT + 1];
    switch_format_bits(pattern, sizeof(pattern), switch_bits(), SWITCH_PIN_COUNT);
    usb_printf("{\"info\":\"bench\",\"ch\":\"%c%d\",\"freq_mhz\":%u,\"wifi_ch\":%u,\"sector\":%d,\"switch\":\"%s\",\"gain\":%d,"
               "\"level_db\":%.1f,\"rssi_dbm\":%.1f,\"p_mean\":%.2f,\"q_phase\":%.0f,\"cv2\":%.2f,\"clip\":%.1f,\"cfo_khz\":%.0f,"
               "\"mod\":%d,\"noise\":%d,\"stuck\":%d,\"step_std\":%.1f,\"nf_dbm\":%.0f,\"captures\":%u,\"cap_err\":%u}",
               c->band, c->number, c->freq_mhz, rf_wifi_channel(), s_switch_raw ? -1 : s_hold_sector, pattern, g,
               (double)level, (double)dbm_from_level(level, cal), (double)m.p_mean, (double)m.q_phase_pct, (double)m.env_cv2, (double)m.clip_pct,
               (double)m.cfo_khz, m.mod, m.noise, m.stuck, (double)m.step_std_deg, (double)s_nf_dbm[band_idx(c->freq_mhz)],
               iq_capture_count(), iq_capture_errors());
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
    band_cal_init(&s_cal[0], RF_NOISE_POWER, RSSI_CAL_DBM_AT_NOISE, RSSI_CAL_SLOPE, RSSI_CAL_OFFSET_DB, RF_FRONTEND_GAIN_DB,
                  ANTENNA_GAIN_DBI, ANTENNA_BEAMWIDTH_DEG, BEARING_K_DEG_PER_DB);
#if DUAL_BAND
    band_cal_init(&s_cal[1], RF_NOISE_POWER_24, RSSI_CAL_DBM_AT_NOISE_24, RSSI_CAL_SLOPE_24, RSSI_CAL_OFFSET_DB_24, RF_FRONTEND_GAIN_DB_24,
                  ANTENNA_GAIN_DBI_24, ANTENNA_BEAMWIDTH_DEG_24, BEARING_K_DEG_PER_DB_24);
#else
    s_cal[1] = s_cal[0];                            // never selected: band_idx() is 0 without DUAL_BAND
#endif
    for (int b = 0; b < 2; b++) s_nf_dbm[b] = dbm_from_level(0.0f, s_cal[b]);   // the calibration's own floor until a sweep measures it
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
