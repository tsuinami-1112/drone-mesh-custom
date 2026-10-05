/* Desktop tests for the level1-c5phy signal processing and report code.
 *
 * Synthetic 4-bit I/Q at 40 MS/s exercises exactly the code that runs on the
 * XIAO ESP32-C5: noise, a bare carrier, an off-channel carrier, FM video with
 * PAL and NTSC line timing, the bearing arithmetic and the two JSON records.
 * JSON lines are printed with a JSON_USB / JSON_MESH tag for check_json.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "demod.h"
#include "bearing.h"
#include "report.h"
#include "fpv_channels.h"
#include "switch_bits.h"

#define FS 40.0e6
#define N  16384
#define PI 3.14159265358979323846

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static unsigned g_seed = 12345u;
static double urand(void) { g_seed = g_seed * 1664525u + 1013904223u; return (g_seed >> 8) / 16777216.0; }
static double nrand(void) { double u1 = urand() + 1e-12, u2 = urand(); return sqrt(-2.0 * log(u1)) * cos(2 * PI * u2); }

/* Hardware model: the modem's 10-bit sample truncated to bits 9..6 (what the
 * four lanes per component carry). With three lanes per component the bit-6
 * lane is not wired and that PARLIO line reads whatever its unassigned matrix
 * input gives: the test puts random bits there so the suite proves demod.c
 * masks them off. */
static int g_lane_bits = 4;
static uint8_t pack(double i, double q)
{
    long ii = (long)floor(i), qq = (long)floor(q);
    if (ii > 7) ii = 7; if (ii < -8) ii = -8;
    if (qq > 7) qq = 7; if (qq < -8) qq = -8;
    uint8_t b = (uint8_t)(((ii & 0xF) << 4) | (qq & 0xF));
    if (g_lane_bits == 3) {
        g_seed = g_seed * 1664525u + 1013904223u;
        b = (uint8_t)((b & 0xEE) | ((g_seed >> 20) & 0x11));   /* unwired lanes: junk */
    }
    return b;
}

static void gen_noise(uint8_t* buf, int n, double sigma)
{
    for (int k = 0; k < n; k++) buf[k] = pack(sigma * nrand(), sigma * nrand());
}

static void gen_cw(uint8_t* buf, int n, double f_hz, double amp, double sigma)
{
    double ph = 2 * PI * urand();
    for (int k = 0; k < n; k++) {
        ph += 2 * PI * f_hz / FS;
        buf[k] = pack(amp * cos(ph) + sigma * nrand(), amp * sin(ph) + sigma * nrand());
    }
}

/* Composite video in IRE for a time within a line, with a per-line picture. */
static double video_ire(double t_us, double line_us, int line)
{
    if (t_us < 1.5) return 0;                               /* front porch */
    if (t_us < 6.2) return -40;                             /* sync tip 4.7 us */
    if (t_us < 10.9) return 0;                              /* back porch */
    double a = (t_us - 10.9) / (line_us - 10.9);            /* 0..1 across the active line */
    double v = 35 + 30 * sin(2 * PI * (3 * a + 0.1 * line)) + 15 * ((int)(a * 7 + line) % 2);
    return v < 0 ? 0 : v;
}

/* FM video: deviation 4 MHz per 100 IRE (sync -1.6 MHz, white +4 MHz),
 * polarity +1 = higher luminance at higher frequency. */
static void gen_fm_video(uint8_t* buf, int n, double line_samples, double cfo_hz, double amp,
                         double sigma, int polarity)
{
    double line_us = line_samples / FS * 1e6;
    double ph = 2 * PI * urand();
    double t0 = urand() * line_samples;                     /* random start phase in the line */
    for (int k = 0; k < n; k++) {
        double s = t0 + k;
        int line = (int)(s / line_samples);
        double t_us = fmod(s, line_samples) / FS * 1e6;
        double ire = video_ire(t_us, line_us, line);
        double f = cfo_hz + polarity * ire / 100.0 * 4.0e6;
        ph += 2 * PI * f / FS;
        buf[k] = pack(amp * cos(ph) + sigma * nrand(), amp * sin(ph) + sigma * nrand());
    }
}

static void test_lut(void)
{
    /* (5,-5) -> (5,5) is a +90 degree step whose values exist in both lane modes */
    uint8_t two[2] = { pack(5, -5), pack(5, 5) };
    IqMetrics m;
    iq_metrics(two, 2, &m);
    CHECK(fabs(m.cfo_khz - 10000.0) < 1.0, "90 deg/sample should read as +10 MHz, got %.1f kHz", m.cfo_khz);
    CHECK(demod_nib(0x8) == -8 && demod_nib(0x7) == 7 && demod_nib(0xF) == -1, "nibble decode");
    if (demod_lane_bits() == 4) {
        CHECK(demod_decode_nibble(0x7) == 7 && demod_decode_nibble(0x8) == -8 && demod_decode_nibble(0x0) == 0, "4-bit decode");
    } else {
        /* bit 0 ignored, midpoint of the merged pair: 0x6/0x7 -> 7, 0x8/0x9 -> -7, 0x0/0x1 -> 1, 0xE/0xF -> -1 */
        CHECK(demod_decode_nibble(0x6) == 7 && demod_decode_nibble(0x7) == 7, "3-bit decode top");
        CHECK(demod_decode_nibble(0x8) == -7 && demod_decode_nibble(0x9) == -7, "3-bit decode bottom");
        CHECK(demod_decode_nibble(0x0) == 1 && demod_decode_nibble(0xF) == -1, "3-bit decode zero");
    }
}

static void test_noise(void)
{
    static uint8_t buf[N];
    gen_noise(buf, N, 1.0);
    IqMetrics m;
    iq_metrics(buf, N, &m);
    printf("noise: p_mean=%.2f q=%.1f%% clip=%.2f%% cv2=%.2f step_std=%.1f noise=%d mod=%d\n",
           m.p_mean, m.q_phase_pct, m.clip_pct, m.env_cv2, m.step_std_deg, m.noise, m.mod);
    /* sigma = 1 LSB: truncation to 4 bits (floor) adds E[u^2] = 1/3 per component,
     * 2.67 for I^2+Q^2; the 3-lane midpoint decode, whose codes are never 0,
     * reads about 2.75. C5VRX measured 2.0 on hardware, and the bench measures
     * RF_NOISE_POWER (stage 1); these pin the decode, not the board. */
    CHECK(fabs(m.p_mean - (demod_lane_bits() == 4 ? 2.67 : 2.75)) < 0.15, "noise p_mean %.2f (%d lanes)", m.p_mean, demod_lane_bits());
    CHECK(m.mod == 0, "noise is not a modulated carrier (mod %d)", m.mod);
    CHECK(m.stuck == 0, "noise must not read as a stuck bus");
    CHECK(m.q_phase_pct < 10, "noise q_phase %.1f", m.q_phase_pct);
    CHECK(m.noise == 1, "noise flag");
    VideoResult v;
    video_window(buf, N, &v);
    CHECK(!v.present, "noise must not read as video (score %d periods %d)", v.score, v.periods);

    /* A dead bus: every sample identical. In 3-lane mode it reads p_mean 2.0,
     * exactly the noise reference, so the flag is what tells the bench. */
    memset(buf, 0x00, N);
    iq_metrics(buf, N, &m);
    CHECK(m.stuck == 1, "all-zero bus must read as stuck (p_mean %.2f)", m.p_mean);
    if (demod_lane_bits() == 3) {
        CHECK(fabs(m.p_mean - 2.0) < 0.01, "a dead bus reads the noise reference in 3-lane mode (%.2f)", m.p_mean);
        for (int k = 0; k < N; k++) { g_seed = g_seed * 1664525u + 1013904223u; buf[k] = (uint8_t)((g_seed >> 20) & 0x11); }
        iq_metrics(buf, N, &m);
        CHECK(m.stuck == 1, "junk on the unwired lanes only must still read as stuck");
    }
    memset(buf, 0xFF, N);
    iq_metrics(buf, N, &m);
    CHECK(m.stuck == 1, "all-ones bus must read as stuck");
}

static void test_cw(void)
{
    static uint8_t buf[N];
    gen_cw(buf, N, 1.0e6, 4.5, 0.5);
    IqMetrics m;
    iq_metrics(buf, N, &m);
    printf("cw +1MHz: p_mean=%.1f q=%.1f%% cfo=%.0f kHz cv2=%.3f step_std=%.1f noise=%d mod=%d\n",
           m.p_mean, m.q_phase_pct, m.cfo_khz, m.env_cv2, m.step_std_deg, m.noise, m.mod);
    CHECK(m.q_phase_pct > 80, "cw q_phase %.1f", m.q_phase_pct);
    CHECK(fabs(m.cfo_khz - 1000) < 60, "cw cfo %.0f", m.cfo_khz);
    CHECK(m.noise == 0, "cw noise flag");
    CHECK(m.mod == 0, "cw mod flag (step_std %.1f)", m.step_std_deg);
    VideoResult v;
    video_window(buf, N, &v);
    CHECK(!v.present, "cw must not read as video");

    gen_cw(buf, N, 10.0e6, 4.5, 0.5);
    iq_metrics(buf, N, &m);
    printf("cw +10MHz: q=%.1f%% cfo=%.0f kHz\n", m.q_phase_pct, m.cfo_khz);
    CHECK(m.q_phase_pct < 20, "off-channel carrier must not be coherent: %.1f", m.q_phase_pct);

    gen_cw(buf, N, -3.0e6, 9.0, 0.3);     /* strong: clipping */
    iq_metrics(buf, N, &m);
    printf("cw strong: clip=%.1f%% p_mean=%.1f\n", m.clip_pct, m.p_mean);
    CHECK(m.clip_pct > 3.0, "strong carrier should clip");
}

static void test_video(const char* name, double line_samples, int expect_hz, double amp, double sigma, int polarity, int strict)
{
    static uint8_t buf[N];
    VideoResult r[8];
    IqMetrics m;
    for (int w = 0; w < 8; w++) {
        gen_fm_video(buf, N, line_samples, 1.84e6, amp, sigma, polarity);
        if (w == 0) {
            iq_metrics(buf, N, &m);
            printf("%s: p_mean=%.1f q=%.1f%% cfo=%.0f kHz step_std=%.1f noise=%d mod=%d\n",
                   name, m.p_mean, m.q_phase_pct, m.cfo_khz, m.step_std_deg, m.noise, m.mod);
        }
        video_window(buf, N, &r[w]);
        printf("  w%d: present=%d std=%s period=%.1f line_hz=%.0f score=%d pulses=%d periods=%d swing=%d pol=%+d\n",
               w, r[w].present, r[w].std, r[w].line_period, r[w].line_hz, r[w].score, r[w].pulses, r[w].periods, r[w].swing, r[w].polarity);
    }
    VideoVerdict v;
    video_verdict(r, 8, 3, &v);
    printf("  verdict: present=%d std=%s sync_hz=%d field_hz=%d sync_q=%d score=%d\n",
           v.present, v.std, v.sync_hz, v.field_hz, v.sync_q, v.sync_score);
    if (strict) {
        CHECK(m.q_phase_pct >= 40, "%s coherence %.1f", name, m.q_phase_pct);
        CHECK(m.mod == 1, "%s mod flag", name);
        CHECK(v.present, "%s verdict present", name);
        CHECK(strcmp(v.std, name) == 0, "%s std read as %s", name, v.std);
        CHECK(abs(v.sync_hz - expect_hz) <= 15, "%s sync_hz %d", name, v.sync_hz);
        CHECK(v.sync_q >= 50, "%s sync_q %d", name, v.sync_q);
    }
}

static void test_bearing(void)
{
    const float az[4] = { 0, 90, 180, 270 };
    BearingResult b;
    float a[4] = { 20, 14, 2, 8 };          /* N strongest, E over W -> east of north */
    bearing_estimate(a, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    printf("bearing A: sector=%d bearing=%.1f sigma=%.1f\n", b.sector, b.bearing_deg, b.sigma_deg);
    CHECK(b.sector == 0 && b.bearing_deg > 0 && b.bearing_deg <= 45, "bearing A %.1f", b.bearing_deg);
    CHECK(fabs(b.bearing_deg - 18.0f) < 0.01, "bearing A value %.2f", b.bearing_deg);
    float c[4] = { 5, 30, 12, 1 };          /* E strongest, S over N -> 90 + 3*(12-5) = 111 */
    bearing_estimate(c, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 1 && fabs(b.bearing_deg - 111.0f) < 0.01, "bearing B %.2f", b.bearing_deg);
    float d[4] = { 12, 1, 3, 25 };          /* W strongest, N over S -> 270 + 3*(12-3) = 297 */
    bearing_estimate(d, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 3 && fabs(b.bearing_deg - 297.0f) < 0.01, "bearing C %.2f", b.bearing_deg);
    float e[4] = { 25, 2, 3, 12 };          /* N strongest, W over E -> 0 + 3*(2-12) = -30 -> 330 */
    bearing_estimate(e, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 0 && fabs(b.bearing_deg - 330.0f) < 0.01, "bearing D %.2f", b.bearing_deg);
    float f[4] = { 25, 2, 3, 24 };          /* on the N/W boundary: sigma grows */
    bearing_estimate(f, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sigma_deg > 15, "boundary sigma %.1f", b.sigma_deg);
    float g[4] = { 9, 2, 3, 1 };            /* just above threshold: noisier */
    bearing_estimate(g, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sigma_deg > 13 && b.sigma_deg < 20, "weak sigma %.1f", b.sigma_deg);
    float h[4] = { 40, 39, 0, 0 };          /* clamp at +/-45 from the axis */
    bearing_estimate(h, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(fabs(b.bearing_deg - 45.0f) < 0.01, "clamp %.1f", b.bearing_deg);
    /* A neighbour whose capture failed: no offset, wide sigma, instead of a
     * confident bearing thrown to the clamp by a sentinel level. */
    float m1[4] = { 20, 14, 2, 8 };
    int ok1[4] = { 1, 0, 1, 1 };
    bearing_estimate_masked(m1, ok1, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 0 && fabs(b.bearing_deg - 0.0f) < 0.01 && b.sigma_deg > 25, "masked neighbour: %.1f deg sigma %.1f", b.bearing_deg, b.sigma_deg);
    int ok2[4] = { 0, 1, 1, 1 };            /* the strongest sector itself missing: next best is used */
    bearing_estimate_masked(m1, ok2, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 1, "masked strongest -> sector %d", b.sector);
    bearing_estimate_masked(m1, NULL, az, 4, 3.0f, 45.0f, 10.0f, 8.0f, &b);
    CHECK(b.sector == 0 && fabs(b.bearing_deg - 18.0f) < 0.01, "NULL mask = all valid");
}

static void test_channels(void)
{
    CHECK(fpv_channel_count() == 40, "40 channels, got %d", fpv_channel_count());
    int r3 = fpv_find("R3");
    CHECK(r3 >= 0 && fpv_channel(r3)->freq_mhz == 5732, "R3");
    CHECK(fpv_find("5732") == r3 && fpv_find("r3") == r3, "find by MHz / lower case");
    CHECK(fpv_find("Z9") < 0 && fpv_find("") < 0, "unknown channel");
    CHECK(fpv_nearest(5734) == r3 || fpv_channel(fpv_nearest(5734))->freq_mhz == 5733, "nearest");
    uint8_t ch; uint16_t mhz;
    CHECK(fpv_wifi_bootstrap(5732, &ch, &mhz) && ch == 144 && mhz == 5720, "bootstrap R3 -> ch144");
    CHECK(fpv_wifi_bootstrap(5865, &ch, &mhz) && ch == 173 && mhz == 5865, "bootstrap A1 exact");
    CHECK(!fpv_wifi_bootstrap(5100, &ch, &mhz), "out of window");
    CHECK(fpv_wifi_bootstrap_rank(5865, 1, &ch, &mhz) && (ch == 169 || ch == 177), "second nearest centre for A1 (%d)", ch);
    CHECK(fpv_wifi_bootstrap_rank(5865, 11, &ch, &mhz) && ch == 132, "farthest centre");
    CHECK(!fpv_wifi_bootstrap_rank(5865, 12, &ch, &mhz), "rank past the table");
    CHECK(fpv_wifi_top_centre_mhz() == 5885, "top centre 5885");
}

/* The bench `t` argument: V1V2V3 patterns (first character = bit 0 = D8) or a
 * number 0..7. The old strtoul(base 0) read "100" as decimal 100 (only D7 high
 * after masking) and "010" as octal 8 (nothing high). */
static void test_switch_bits(void)
{
    uint32_t b = 99;
    CHECK(switch_parse_bits("100", 3, &b) == 0 && b == 0x1, "100 = V1 only (got %u)", b);
    CHECK(switch_parse_bits("010", 3, &b) == 0 && b == 0x2, "010 = V2 only (got %u)", b);
    CHECK(switch_parse_bits("001", 3, &b) == 0 && b == 0x4, "001 = V3 only (got %u)", b);
    CHECK(switch_parse_bits("110", 3, &b) == 0 && b == 0x3, "110 = V1 V2 (got %u)", b);
    CHECK(switch_parse_bits("000", 3, &b) == 0 && b == 0x0, "000");
    CHECK(switch_parse_bits("111", 3, &b) == 0 && b == 0x7, "111");
    CHECK(switch_parse_bits("0", 3, &b) == 0 && b == 0, "number 0");
    CHECK(switch_parse_bits("1", 3, &b) == 0 && b == 1, "number 1");
    CHECK(switch_parse_bits("5", 3, &b) == 0 && b == 5, "number 5");
    CHECK(switch_parse_bits("7", 3, &b) == 0 && b == 7, "number 7");
    CHECK(switch_parse_bits("0x3", 3, &b) == 0 && b == 3, "hex 0x3");
    CHECK(switch_parse_bits("0X7", 3, &b) == 0 && b == 7, "hex 0X7");
    CHECK(switch_parse_bits("8", 3, &b) != 0, "8 out of range");
    CHECK(switch_parse_bits("10", 3, &b) != 0, "10 out of range, not truncated");
    CHECK(switch_parse_bits("1000", 3, &b) != 0, "four digits refused");
    CHECK(switch_parse_bits("0x8", 3, &b) != 0, "hex out of range");
    CHECK(switch_parse_bits("0xf", 3, &b) != 0, "hex digit past the range");
    CHECK(switch_parse_bits("07", 3, &b) != 0, "octal refused");
    CHECK(switch_parse_bits("-1", 3, &b) != 0, "sign refused");
    CHECK(switch_parse_bits("1a", 3, &b) != 0, "trailing characters refused");
    CHECK(switch_parse_bits("0x", 3, &b) != 0 && switch_parse_bits("", 3, &b) != 0, "empty");
    CHECK(switch_parse_bits("10", 2, &b) == 0 && b == 0x1, "two-line pattern");
    CHECK(switch_parse_bits("4294967296", 31, &b) != 0, "no overflow");
    char s[8];
    switch_format_bits(s, sizeof s, 0x1, 3); CHECK(strcmp(s, "100") == 0, "format 0x1 -> 100 (%s)", s);
    switch_format_bits(s, sizeof s, 0x3, 3); CHECK(strcmp(s, "110") == 0, "format 0x3 -> 110 (%s)", s);
    switch_format_bits(s, sizeof s, 0x4, 3); CHECK(strcmp(s, "001") == 0, "format 0x4 -> 001 (%s)", s);
    switch_format_bits(s, 3, 0x7, 3);        CHECK(strcmp(s, "11") == 0, "format truncates to the buffer (%s)", s);
    for (uint32_t v = 0; v < 8; v++) {
        uint32_t back = 99;
        switch_format_bits(s, sizeof s, v, 3);
        CHECK(switch_parse_bits(s, 3, &back) == 0 && back == v, "round trip %u -> %s -> %u", v, s, back);
    }
    printf("switch bits: 100->0x1 010->0x2 001->0x4 110->0x3, 0..7 and 0x0..0x7 accepted, out-of-range/octal refused\n");
}

static void test_report(void)
{
    char mac[18], basic[32], fp[32];
    report_mac(mac, 'R', 3, 5732);
    CHECK(strcmp(mac, "AF:00:52:03:16:64") == 0, "mac %s", mac);
    report_basic_id(basic, sizeof(basic), 'R', 3, 5732);
    CHECK(strcmp(basic, "5.8G-R3-5732MHz") == 0, "basic_id %s", basic);
    report_fp(fp, sizeof(fp), "NTSC", 15736, "fm", 5734);
    CHECK(strcmp(fp, "NTSC/15736/5734") == 0, "fp %s", fp);
    report_fp(fp, sizeof(fp), "none", 0, "cw", 5734);
    CHECK(strcmp(fp, "cw/5734") == 0, "fp none %s", fp);
    CHECK(report_rssi_raw(-110) == 0 && report_rssi_raw(-30) == 1023 && report_rssi_raw(-68.1f) == 536, "rssi_raw %d", report_rssi_raw(-68.1f));

    float sectors[4] = { -68.1f, -74.4f, -91.0f, -85.2f };
    DetectionReport r = {
        .node_id = "RX01", .receiver = "c5phy", .hw = "v3",
        .band = 'R', .ch = 3, .freq_mhz = 5732,
        .rssi_dbm = -68.1f, .rssi_min_dbm = -70.0f, .rssi_max_dbm = -66.2f, .rssi_n = 3,
        .level_db = 26.9f, .gain = 50, .q_phase = 71, .cfo_khz = 1840, .carrier = "fm",
        .sectors_dbm = sectors, .sector_count = 4, .sector = 0,
        .bearing_deg = 32, .bearing_sigma_deg = 15, .heading = 0,
        .freq_peak = 5734, .video = "NTSC", .sync_hz = 15736, .field_hz = 60,
        .sync_q = 88, .sync_score = 91, .video_windows = 8, .seq = 42,
    };
    char usb[640], mesh[192];
    int n1 = report_detection_json(usb, sizeof(usb), &r, 1);
    int n2 = report_detection_json(mesh, sizeof(mesh), &r, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n1 > 0 && n1 == (int)strlen(usb), "usb json length");
    CHECK(n2 > 0 && n2 <= 191, "mesh json %d bytes", n2);
    CHECK(strstr(mesh, "\"fp\":\"NTSC/15736/5734\"") != NULL, "mesh carries fp");
    CHECK(strstr(mesh, "\"bearing_deg\":32") != NULL, "mesh carries bearing");
    CHECK(strstr(usb, "\"sectors\":[-68.1,-74.4,-91.0,-85.2]") != NULL, "usb sectors");

    /* A long node id must still give a complete, parseable mesh line. */
    r.node_id = "STATION-NORTH-TOWER-01";
    r.video = "none";
    n2 = report_detection_json(mesh, sizeof(mesh), &r, 0);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n2 > 0 && n2 <= 191 && mesh[n2 - 1] == '}', "mesh json with long node id");

    /* Too small a buffer fails cleanly instead of emitting a fragment. */
    char tiny[40];
    CHECK(report_detection_json(tiny, sizeof(tiny), &r, 0) == 0, "tiny buffer");

    HeartbeatReport h = {
        .node_id = "RX01", .receiver = "c5phy", .hw = "v3", .scanning = 1, .channels = 40, .sectors = 4,
        .heading = 0, .threshold_dbm = -87.0f, .threshold_level_db = 8.0f, .video_seen = 7, .gain_max = 62,
        .bw40 = 1, .fe_gain_db = 0, .tune_fail = 0, .cap_err = 0, .sweeps = 1830, .usb_drop = 0, .mesh_drop = 0,
        .nf_dbm = -98, .temp_c = 41.2f, .uptime_s = 3600, .seq = 42,
    };
    int n3 = report_heartbeat_json(usb, sizeof(usb), &h, 1);
    int n4 = report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n3 > 0 && n4 > 0 && n4 <= 191, "heartbeat json");
}

/* The price of three lanes per component: level above the noise reference and
 * FM coherence of a video carrier, at the real noise floor (sigma = 1 LSB of
 * the 4-bit scale), for both lane modes. Printed for the record; the strict
 * checks above are what gate the build. */
static void sensitivity_table(void)
{
    static uint8_t buf[N];
    const double amps[] = { 0.7, 1.0, 1.4, 2.0, 2.8, 4.0 };
    enum { NA = sizeof(amps) / sizeof(amps[0]) };
    double row[2][NA][3];
    for (int mode = 0; mode < 2; mode++) {          /* mode outermost: two LUT builds, not twelve */
        g_lane_bits = mode ? 3 : 4;
        demod_init_bits(g_lane_bits);
        for (unsigned a = 0; a < NA; a++) {
            g_seed = 99u;
            gen_noise(buf, N, 1.0);
            IqMetrics nm;
            iq_metrics(buf, N, &nm);
            int present = 0;
            double q = 0, lvl = 0;
            for (int w = 0; w < 8; w++) {
                gen_fm_video(buf, N, 2542.2, 1.84e6, amps[a], 1.0, +1);
                IqMetrics m;
                VideoResult v;
                iq_metrics(buf, N, &m);
                video_window(buf, N, &v);
                q += m.q_phase_pct / 8;
                lvl += 10 * log10(m.p_mean / nm.p_mean) / 8;   /* each mode against its own measured floor */
                present += v.present;
            }
            row[mode][a][0] = lvl; row[mode][a][1] = q; row[mode][a][2] = present;
        }
    }
    printf("\nsensitivity, sigma = 1.0, each decode referenced to its own noise floor:\n"
           "  amplitude | 4 lanes: level_db q_phase video | 3 lanes: level_db q_phase video\n");
    for (unsigned a = 0; a < NA; a++)
        printf("  A=%.1f | %5.1f dB %5.1f%% %d/8 | %5.1f dB %5.1f%% %d/8\n", amps[a],
               row[0][a][0], row[0][a][1], (int)row[0][a][2], row[1][a][0], row[1][a][1], (int)row[1][a][2]);
    g_lane_bits = 4;
    demod_init_bits(4);
}

static void run_suite(int bits)
{
    g_lane_bits = bits;
    demod_init_bits(bits);
    printf("\n===== %d lanes per component =====\n", bits);
    test_lut();
    test_noise();
    test_cw();
    test_video("NTSC", 2542.2, 15734, 4.5, 0.7, +1, 1);
    test_video("PAL", 2560.0, 15625, 4.5, 0.7, +1, 1);
    test_video("NTSC", 2542.2, 15734, 4.5, 0.7, -1, 1);   /* sync at the high end */
    test_video("PAL", 2560.0, 15625, 2.0, 1.0, +1, 0);     /* weak: informational */
}

int main(void)
{
    run_suite(4);
    run_suite(3);
    test_bearing();
    test_channels();
    test_switch_bits();
    test_report();
    sensitivity_table();
    printf(g_fail ? "\n%d FAILURE(S)\n" : "\nALL TESTS PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
