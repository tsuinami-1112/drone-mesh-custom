/* Desktop tests for the level1-c5phy signal processing and report code.
 *
 * Synthetic 4-bit I/Q at 40 MS/s exercises exactly the code that runs on the
 * XIAO ESP32-C5: noise, a bare carrier, an off-channel carrier, FM video with
 * PAL and NTSC line timing, the digital video waveforms the wideband path has
 * to tell apart (LTE-like and 802.11-like OFDM, single-carrier QPSK), the
 * bearing arithmetic and the JSON records. JSON lines are printed with a
 * JSON_USB / JSON_MESH tag for check_json.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <complex.h>
#include "demod.h"
#include "bearing.h"
#include "report.h"
#include "fpv_channels.h"
#include "switch_bits.h"
#include "sweep_decide.h"

#define FS 40.0e6
#define N  16384
#define PI 3.14159265358979323846

/* Build variants under test: the Makefile runs the suite with the defaults and
 * again with -DDUAL_BAND=1 -DLOWBAND=2. */
#ifndef DUAL_BAND
#define DUAL_BAND 0
#endif
#ifndef LOWBAND
#define LOWBAND 1
#endif

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

/* The modulated waveforms are built at unit amplitude in g_wave and quantised
 * by quant(), so a window can be retaken at a lower gain the way the firmware's
 * gain loop does without drawing a new waveform. */
static double complex g_wave[N];

/* buf = pack(amp * wave + sigma * noise): the receiver's gain and its noise floor. */
static void quant(uint8_t* buf, int n, double amp, double sigma)
{
    for (int k = 0; k < n; k++)
        buf[k] = pack(amp * creal(g_wave[k]) + sigma * nrand(), amp * cimag(g_wave[k]) + sigma * nrand());
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
        g_wave[k] = cos(ph) + sin(ph) * I;
    }
    quant(buf, n, amp, sigma);
}

/* CP-OFDM in continuous time: subcarriers f[] (Hz), a fresh random QPSK symbol
 * per subcarrier per OFDM symbol of tu_s + tcp_s, advanced sample by sample
 * with one complex rotation per subcarrier; on_us / off_us > 0 gates it into
 * bursts (Wi-Fi traffic). Unit power. */
static void gen_ofdm(uint8_t* buf, int n, const double* f, int nsc, double tu_s, double tcp_s,
                     double on_us, double off_us, double amp, double sigma)
{
    static double complex p[2048], w[2048];
    double tsym = tu_s + tcp_s;
    double t0 = urand() * tsym;                             /* random symbol phase */
    double t_off = urand() * (on_us + off_us);              /* random burst phase */
    for (int m = 0; m < nsc; m++) w[m] = cexp(I * 2 * PI * f[m] / FS);
    int cur = -1;
    for (int k = 0; k < n; k++) {
        double t = k / FS + t0;
        int s = (int)(t / tsym);
        if (s != cur) {                                     /* new symbol: new data, phased to its own start */
            cur = s;
            double tau = t - s * tsym - tcp_s;
            for (int m = 0; m < nsc; m++) {
                double complex x = (urand() < 0.5 ? 1 : -1) + (urand() < 0.5 ? 1 : -1) * I;
                p[m] = x * cexp(I * 2 * PI * f[m] * tau);
            }
        }
        double complex v = 0;
        for (int m = 0; m < nsc; m++) { v += p[m]; p[m] *= w[m]; }
        if (off_us > 0 && fmod(t * 1e6 + t_off, on_us + off_us) >= on_us) v = 0;
        g_wave[k] = v / sqrt(2.0 * nsc);
    }
    quant(buf, n, amp, sigma);
}

/* Single-carrier QPSK at rs symbols/s through a raised-cosine pulse (alpha 0.35,
 * +/-8 symbols), offset foff Hz. Unit power. */
static void gen_sc(uint8_t* buf, int n, double rs, double foff, double amp, double sigma)
{
    static double complex a[8192];
    double T = 1 / rs;
    int nsym = (int)(n / FS * rs) + 40;
    for (int s = 0; s < nsym; s++) a[s] = (urand() < 0.5 ? 1 : -1) + (urand() < 0.5 ? 1 : -1) * I;
    for (int k = 0; k < n; k++) {
        double t = k / FS + 20 * T;
        int c = (int)(t / T);
        double complex v = 0;
        for (int s = c - 8; s <= c + 8; s++) {
            if (s < 0 || s >= nsym) continue;
            double x = (t - s * T) / T;
            double h = fabs(x) < 1e-9 ? 1 : sin(PI * x) / (PI * x);
            double d = 1 - 4 * 0.35 * 0.35 * x * x;
            h *= fabs(d) < 1e-6 ? PI / 4 : cos(PI * 0.35 * x) / d;
            v += a[s] * h;
        }
        g_wave[k] = v * cexp(I * 2 * PI * foff * k / FS) / sqrt(2.0);
    }
    quant(buf, n, amp, sigma);
}

/* The waveforms of SPEC section 11, +0.5 MHz off the tuned frequency. */
enum { WF_FM, WF_LTE, WF_DOT11, WF_DOT11_BURST, WF_DOT11_40, WF_SC, WF_COUNT };
static const char* const k_wf_names[WF_COUNT] = {
    "FM video", "LTE-like 9 MHz", "802.11-like 20 MHz", "802.11-like 20 MHz bursty", "802.11-like 40 MHz", "SC QPSK 10 Msym/s",
};

static void gen_waveform(int kind, uint8_t* buf, int n, double amp, double sigma)
{
    static double f[2048];
    const double foff = 0.5e6;
    int nsc = 0;
    switch (kind) {
    case WF_FM:                                             /* NTSC line timing, picture polarity +1 */
        gen_fm_video(buf, n, 2542.2, foff, amp, sigma, +1);
        break;
    case WF_LTE:                                            /* 600 x 15 kHz = 9 MHz, Tu 66.67 us, CP 4.69 us */
        for (int m = 0; m < 600; m++) f[nsc++] = foff + (m - 299.5) * 15e3;
        gen_ofdm(buf, n, f, nsc, 1 / 15e3, 4.69e-6, 0, 0, amp, sigma);
        break;
    case WF_DOT11:                                          /* 52 x 312.5 kHz, Tu 3.2 us, CP 0.8 us */
    case WF_DOT11_BURST:                                    /* the same, 300 us on / 700 us off */
        for (int m = -26; m <= 26; m++) if (m) f[nsc++] = foff + m * 312.5e3;
        gen_ofdm(buf, n, f, nsc, 3.2e-6, 0.8e-6, kind == WF_DOT11_BURST ? 300 : 0, kind == WF_DOT11_BURST ? 700 : 0, amp, sigma);
        break;
    case WF_DOT11_40:                                       /* m = -58..58, |m| > 1 */
        for (int m = -58; m <= 58; m++) if (abs(m) > 1) f[nsc++] = foff + m * 312.5e3;
        gen_ofdm(buf, n, f, nsc, 3.2e-6, 0.8e-6, 0, 0, amp, sigma);
        break;
    case WF_SC:
        gen_sc(buf, n, 10e6, foff, amp, sigma);
        break;
    }
}

/* The firmware's gain loop on the waveform just generated: step the gain down
 * (GAIN_STEP 3 dB) and retake while more than CLIP_MAX_PCT of the samples clip.
 * buf holds the window at amp / sigma on entry; returns the back-off in dB and
 * the metrics of the window kept. */
static double gain_loop(uint8_t* buf, int n, double amp, double sigma, IqMetrics* m)
{
    double back = 0;
    for (;;) {
        iq_metrics(buf, n, m);
        if (m->clip_pct <= 3.0f || back >= 60) return back;
        back += 3;
        double s = pow(10, -back / 20.0);
        quant(buf, n, s * amp, s * sigma);
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
    int expect = 50;                                        /* R A B E F + X1 X2 + D1..D3 + L4..L8 */
    if (DUAL_BAND) expect += 5;                             /* G1..G5 */
    if (LOWBAND >= 2) expect += 3;                          /* L1..L3 */
    CHECK(fpv_channel_count() == expect, "%d channels, got %d", expect, fpv_channel_count());
    /* R, A, B, E, F first in table order, the additions after F8 */
    int order_ok = 1;
    for (int i = 0; i < 40; i++) {
        const FpvChannel* c = fpv_channel(i);
        if (!c || c->band != "RABEF"[i / 8] || c->number != i % 8 + 1) order_ok = 0;
    }
    CHECK(order_ok, "R A B E F first");
    CHECK(fpv_channel(40)->band == 'X' && fpv_channel(42)->band == 'D' && fpv_channel(45)->band == 'L', "X, D, L after F8");
    CHECK(fpv_channel(fpv_channel_count() - 1)->band == (DUAL_BAND ? 'G' : 'L'), "last channel");
    int r3 = fpv_find("R3");
    CHECK(r3 >= 0 && fpv_channel(r3)->freq_mhz == 5732, "R3");
    CHECK(fpv_find("5732") == r3 && fpv_find("r3") == r3, "find by MHz / lower case");
    CHECK(fpv_find("Z9") < 0 && fpv_find("") < 0, "unknown channel");
    CHECK(fpv_nearest(5734) == r3 || fpv_channel(fpv_nearest(5734))->freq_mhz == 5733, "nearest");
    int d1 = fpv_find("D1"), x2 = fpv_find("X2"), l4 = fpv_find("L4"), l1 = fpv_find("L1"), g3 = fpv_find("G3");
    CHECK(d1 >= 0 && fpv_channel(d1)->freq_mhz == 5190, "D1");
    CHECK(x2 >= 0 && fpv_channel(x2)->freq_mhz == 5715, "X2");
    CHECK(l4 >= 0 && fpv_channel(l4)->freq_mhz == 5473, "L4");
    CHECK((l1 >= 0) == (LOWBAND >= 2), "L1 only with LOWBAND 2 (%d)", l1);
    CHECK((g3 >= 0) == (DUAL_BAND != 0) && (g3 < 0 || fpv_channel(g3)->freq_mhz == 2442), "G3 only with DUAL_BAND (%d)", g3);
    CHECK(fpv_freq_band_ghz(5190) == 5 && fpv_freq_band_ghz(2442) == 2, "band of a frequency");
    CHECK(fpv_channel_band_ghz(r3) == 5 && fpv_channel_band_ghz(d1) == 5 && fpv_channel_band_ghz(-1) == 0, "band of a channel");
    if (g3 >= 0) CHECK(fpv_channel_band_ghz(g3) == 2, "G3 is 2.4 GHz");
    CHECK(strcmp(fpv_band_prefix(5732), "5.8G") == 0 && strcmp(fpv_band_prefix(5190), "5.8G") == 0
          && strcmp(fpv_band_prefix(2442), "2.4G") == 0, "band prefix");

    uint8_t ch; uint16_t mhz;
    CHECK(fpv_wifi_bootstrap(5732, &ch, &mhz) && ch == 144 && mhz == 5720, "bootstrap R3 -> ch144");
    CHECK(fpv_wifi_bootstrap(5865, &ch, &mhz) && ch == 173 && mhz == 5865, "bootstrap A1 exact");
    CHECK(fpv_wifi_bootstrap(5190, &ch, &mhz) && ch == 36 && mhz == 5180, "bootstrap D1 -> ch36");
    CHECK(fpv_wifi_bootstrap(5473, &ch, &mhz) && ch == 100 && mhz == 5500, "bootstrap L4 -> ch100");
    /* 2.4 GHz centres sit 5 MHz apart: G3 2442 is channel 7 itself, G1 2402 ten under channel 1 */
    CHECK(fpv_wifi_bootstrap(2442, &ch, &mhz) && ch == 7 && mhz == 2442, "bootstrap G3 -> ch7 (%d)", ch);
    CHECK(fpv_wifi_bootstrap(2402, &ch, &mhz) && ch == 1 && mhz == 2412, "bootstrap G1 -> ch1");
    CHECK(fpv_wifi_bootstrap_rank(2442, 1, &ch, &mhz) && (ch == 6 || ch == 8), "second nearest centre for G3 (%d)", ch);
    CHECK(!fpv_wifi_bootstrap(5100, &ch, &mhz) && !fpv_wifi_bootstrap(2340, &ch, &mhz) && !fpv_wifi_bootstrap(2540, &ch, &mhz), "out of window");
    CHECK(fpv_wifi_bootstrap_rank(5865, 1, &ch, &mhz) && (ch == 169 || ch == 177), "second nearest centre for A1 (%d)", ch);
    CHECK(fpv_wifi_bootstrap_rank(5865, 11, &ch, &mhz) && ch == 132, "farthest UNII-2C/3 centre");
    CHECK(fpv_wifi_bootstrap_rank(5865, 23, &ch, &mhz) && ch == 36, "farthest centre");
    CHECK(!fpv_wifi_bootstrap_rank(5865, 24, &ch, &mhz), "rank past the table");
    /* a 2.4 GHz target never parks on a 5 GHz centre, nor the other way round */
    int cross = 0, n24 = 0, n5 = 0;
    for (int rank = 0; fpv_wifi_bootstrap_rank(2442, rank, &ch, &mhz); rank++) { n24++; if (mhz > 3000) cross = 1; }
    for (int rank = 0; fpv_wifi_bootstrap_rank(5732, rank, &ch, &mhz); rank++) { n5++; if (mhz < 3000) cross = 1; }
    CHECK(!cross && n24 == 13 && n5 == 24, "band-aware ranking: %d 2.4 GHz and %d 5 GHz centres", n24, n5);
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
        .node_id = "RX01", .receiver = "c5phy", .hw = "v3", .scanning = 1, .channels = fpv_channel_count(), .sectors = 4,
        .heading = 0, .threshold_dbm = -87.0f, .threshold_level_db = 8.0f, .video_seen = 7, .gain_max = 62,
        .bw40 = 1, .fe_gain_db = 0, .bands = "5.8", .antenna_dbi = 8.0f, .beamwidth_deg = 72, .bearing_k = 3.0f,
        .wb_seen = 2, .pullin = 1, .tune_fail = 0, .cap_err = 0, .sweeps = 1830, .usb_drop = 0, .mesh_drop = 0,
        .nf_dbm = -98, .temp_c = 41.2f, .uptime_s = 3600, .seq = 42,
    };
    int n3 = report_heartbeat_json(usb, sizeof(usb), &h, 1);
    int n4 = report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n3 > 0 && n4 > 0 && n4 <= 191, "heartbeat json");
    CHECK(!strstr(usb, "\"lat\"") && !strstr(mesh, "\"lat\""), "no position unless the station has one");
    /* Antenna model and wideband counters: after fe_gain_db in the USB line, wb_seen after video_seen in the mesh line. */
    CHECK(strstr(usb, "\"fe_gain_db\":0.0,\"bands\":\"5.8\",\"antenna_dbi\":8.0,\"beamwidth_deg\":72,\"bearing_k\":3.00,\"wb_seen\":2,\"pullin\":1,\"tune_fail\":0,"),
          "usb heartbeat antenna and wideband fields in order");
    CHECK(strstr(mesh, "\"video_seen\":7,\"wb_seen\":2,\"nf_dbm\":-98,"), "mesh heartbeat wb_seen after video_seen");

    /* Flashed position (STATION_LAT / STATION_LON): both fields, 6 decimals, right
     * after the heading, in the USB line and in the mesh line; in the mesh line it
     * outranks the tail, even for a long NODE_ID and a month of counters. */
    char usb_nopos[640], mesh_nopos[192];
    strcpy(usb_nopos, usb); strcpy(mesh_nopos, mesh);
    h.has_pos = 1; h.lat = 33.4942; h.lon = -111.9261;
    int n5 = report_heartbeat_json(usb, sizeof(usb), &h, 1);
    int n6 = report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n5 > 0 && strstr(usb, "\"heading\":0,\"lat\":33.494200,\"lon\":-111.926100,"), "usb heartbeat position");
    CHECK(n6 > 0 && n6 <= 191 && strstr(mesh, "\"heading\":0,\"lat\":33.494200,\"lon\":-111.926100,"), "mesh heartbeat position (%d)", n6);
    h.node_id = "STATION-NORTH-TOWER-01"; h.lat = -89.999999; h.lon = -179.999999;
    h.sweeps = 1296000; h.uptime_s = 2592000; h.video_seen = 1234; h.cap_err = 12; h.alias_drop = 3;
    int n7 = report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n7 > 0 && n7 <= 191 && strstr(mesh, "\"lat\":-89.999999,\"lon\":-179.999999"), "mesh position survives a long node id (%d)", n7);
    h.has_pos = 0; h.node_id = "RX01"; h.lat = h.lon = 0;
    h.sweeps = 1830; h.uptime_s = 3600; h.video_seen = 7; h.cap_err = 0; h.alias_drop = 0;
    report_heartbeat_json(usb, sizeof(usb), &h, 1);
    report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    CHECK(strcmp(usb, usb_nopos) == 0 && strcmp(mesh, mesh_nopos) == 0, "without a position the lines are unchanged");

    /* DUAL_BAND: the 2.4 GHz noise floor rides on the USB heartbeat only, right after nf_dbm. */
    h.has_nf_24 = 1; h.nf_dbm_24 = -96;
    int n8 = report_heartbeat_json(usb, sizeof(usb), &h, 1);
    int n9 = report_heartbeat_json(mesh, sizeof(mesh), &h, 0);
    printf("JSON_USB %s\n", usb);
    CHECK(n8 > 0 && strstr(usb, "\"nf_dbm\":-98,\"nf_dbm_24\":-96,\"temp_c\":41.2,"), "usb heartbeat nf_dbm_24 after nf_dbm");
    CHECK(n9 > 0 && n9 <= 191 && !strstr(mesh, "nf_dbm_24"), "mesh heartbeat carries no nf_dbm_24");
}

static void test_wideband_report(void)
{
    char mac[18], fp[32], basic[32];
    report_wb_mac(mac, 'R', 4, 5769);
    CHECK(strcmp(mac, "DF:00:52:04:16:89") == 0, "wb mac %s", mac);
    report_wb_fp(fp, sizeof(fp), "lte", 10, 5768.5f);
    CHECK(strcmp(fp, "lte/10/5768.5") == 0, "wb fp %s", fp);
    report_basic_id(basic, sizeof(basic), 'R', 4, 5769);
    CHECK(strcmp(basic, "5.8G-R4-5769MHz") == 0, "wb basic_id %s", basic);
    report_basic_id(basic, sizeof(basic), 'D', 1, 5190);
    CHECK(strcmp(basic, "5.8G-D1-5190MHz") == 0, "5.1 GHz keeps the 5.8G prefix: %s", basic);
    report_basic_id(basic, sizeof(basic), 'G', 3, 2442);
    CHECK(strcmp(basic, "2.4G-G3-2442MHz") == 0, "2.4 GHz basic_id %s", basic);

    /* A DJI-like 10 MHz link on R4, confirmed over 8 windows */
    float sectors[4] = { -66.3f, -72.8f, -90.1f, -84.0f };
    WidebandReport r = {
        .node_id = "RX01", .receiver = "c5phy", .hw = "v3",
        .band = 'R', .ch = 4, .freq_mhz = 5769, .fc_mhz = 5768.5f, .cfo_khz = -480,
        .rssi_dbm = -66.3f, .rssi_min_dbm = -67.9f, .rssi_max_dbm = -65.1f, .rssi_n = 8,
        .level_db = 28.7f, .gain = 44, .q_phase = 41,
        .cls = "lte", .conf = "high", .bw_mhz = 10, .duty_pct = 100,
        .cv2 = 0.98f, .r1 = 0.85f, .r128 = 0.009f, .r512 = 0.007f, .r2667 = 0.056f, .span_mhz = 0,
        .sectors_dbm = sectors, .sector_count = 4, .sector = 0,
        .bearing_deg = 20, .bearing_sigma_deg = 16, .heading = 0, .seq = 43,
    };
    char usb[768], mesh[192];
    int n1 = report_wideband_json(usb, sizeof(usb), &r, 1);
    int n2 = report_wideband_json(mesh, sizeof(mesh), &r, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n1 > 0 && n1 == (int)strlen(usb) && n1 < 640, "wb usb json length %d", n1);
    CHECK(strstr(usb, "{\"type\":\"wideband\",\"receiver\":\"c5phy\",\"hw\":\"v3\",\"mac\":\"DF:00:52:04:16:89\",\"freq_mhz\":5769,\"fc_mhz\":5768.5,\"band\":\"R\",\"ch\":4,"
                      "\"rssi\":-66,\"rssi_dbm\":-66.3,\"rssi_raw\":559,\"rssi_min\":-68,\"rssi_max\":-65,\"rssi_n\":8,\"level_db\":28.7,\"gain\":44,\"q_phase\":41,\"cfo_khz\":-480,"),
          "wb usb identity and level fields in order");
    CHECK(strstr(usb, "\"cls\":\"lte\",\"conf\":\"high\",\"bw_mhz\":10,\"duty\":100,\"cv2\":0.98,\"r1\":0.85,\"r128\":0.009,\"r512\":0.007,\"r2667\":0.056,\"span_mhz\":0,"
                      "\"sectors\":[-66.3,-72.8,-90.1,-84.0],\"sector\":0,\"bearing_deg\":20,\"bearing_sigma_deg\":16,\"station_heading\":0,"),
          "wb usb class, feature and bearing fields in order");
    CHECK(strstr(usb, "\"fp\":\"lte/10/5768.5\",\"basic_id\":\"5.8G-R4-5769MHz\",\"node_id\":\"RX01\",\"seq\":43}"), "wb usb tail");
    CHECK(n2 > 0 && n2 <= 191 && mesh[n2 - 1] == '}', "wb mesh json %d bytes", n2);
    CHECK(strstr(mesh, "{\"type\":\"wideband\",\"mac\":\"DF:00:52:04:16:89\",\"node_id\":\"RX01\",\"freq_mhz\":5769,\"rssi\":-66,\"bearing_deg\":20,\"bearing_sigma_deg\":16,"
                       "\"cls\":\"lte\",\"fc_mhz\":5768.5,\"bw_mhz\":10,\"duty\":100,"),
          "wb mesh identity, bearing and class first");

    /* A long node id: the tail gives way, what names the system stays. */
    r.node_id = "STATION-NORTH-TOWER-01";
    n2 = report_wideband_json(mesh, sizeof(mesh), &r, 0);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n2 > 0 && n2 <= 191 && mesh[n2 - 1] == '}', "wb mesh json with long node id (%d)", n2);
    CHECK(strstr(mesh, "\"bearing_sigma_deg\":16,\"cls\":\"lte\",\"fc_mhz\":5768.5"), "wb mesh keeps class and centre with a long node id");
    char tiny[40];
    CHECK(report_wideband_json(tiny, sizeof(tiny), &r, 0) == 0, "wb tiny buffer");

    /* A 2.4 GHz channel (DUAL_BAND): the key and basic_id say so, the record is the same. */
    r.node_id = "RX01"; r.band = 'G'; r.ch = 3; r.freq_mhz = 2442; r.fc_mhz = 2444.5f; r.cfo_khz = 2500;
    r.cls = "dot11"; r.conf = "med"; r.bw_mhz = 20; r.duty_pct = 80; r.span_mhz = 20; r.seq = 44;
    n1 = report_wideband_json(usb, sizeof(usb), &r, 1);
    n2 = report_wideband_json(mesh, sizeof(mesh), &r, 0);
    printf("JSON_USB %s\n", usb);
    printf("JSON_MESH %s\n", mesh);
    CHECK(n1 > 0 && strstr(usb, "\"mac\":\"DF:00:47:03:09:8A\"") && strstr(usb, "\"fp\":\"dot11/20/2444.5\",\"basic_id\":\"2.4G-G3-2442MHz\""), "2.4 GHz wb usb");
    CHECK(n2 > 0 && n2 <= 191 && strstr(mesh, "\"mac\":\"DF:00:47:03:09:8A\"") && strstr(mesh, "\"cls\":\"dot11\",\"fc_mhz\":2444.5,\"bw_mhz\":20,\"duty\":80"), "2.4 GHz wb mesh");
}

/* ---- digital video links ---------------------------------------------------
 * The analog gate (q_phase, env_cv2) and the lag features on the waveforms the
 * wideband path has to tell apart, through the firmware's gain loop at S/N 30
 * and 12 dB. Model numbers in SPEC section 11; thresholds as in config.h. */
#ifndef DETECT_LEVEL_DB
#define DETECT_LEVEL_DB 8.0f
#endif
#ifndef Q_MIN
#define Q_MIN 40
#endif
#ifndef ANALOG_CV2_MAX
#define ANALOG_CV2_MAX 0.5f
#endif
#ifndef WB_R128_MIN
#define WB_R128_MIN 0.10f
#endif
#ifndef WB_R2667_MIN
#define WB_R2667_MIN 0.03f
#endif
#ifndef WB_R128_LTE_MAX
#define WB_R128_LTE_MAX 0.05f
#endif
#ifndef WB_R128_HIGH
#define WB_R128_HIGH 0.15f
#endif
#ifndef WB_R2667_HIGH
#define WB_R2667_HIGH 0.04f
#endif

/* main.cpp's class rule and bandwidth bucket (SPEC section 6); the bucket is
 * taken on r1 scaled back by (S+N)/S, since the noise decorrelates at lag 1 */
static const char* wb_class(const IqLagFeatures* f)
{
    if (f->r2667 >= WB_R2667_MIN && f->r128 < WB_R128_LTE_MAX) return "lte";
    if (f->r128 >= WB_R128_MIN) return "dot11";
    return "wb";
}
static int wb_bucket(float r1, double level_db)
{
    double r = r1 * (1.0 + pow(10, -level_db / 10.0));
    if (r > 1.0) r = 1.0;
    return r >= 0.78 ? 10 : r >= 0.52 ? 20 : r >= 0.30 ? 30 : 40;
}
static double median(double* v, int n)                  /* sorts v */
{
    for (int i = 1; i < n; i++) {
        double x = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
        v[j + 1] = x;
    }
    return (n & 1) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

static void test_wideband(double snr_db)
{
    static uint8_t buf[N];
    const double a0 = sqrt(2.0 * pow(10, snr_db / 10.0));  /* unit-power waveform over the sigma = 1 floor */
    enum { NW = 8 };                                          /* WB_WINDOWS: level = min, q and cv2 = median, features = mean */
    unsigned seed = g_seed;                                   /* own stream: the suites after this one see the same numbers as before */
    g_seed = 7u + (unsigned)snr_db;
    IqMetrics nm;
    IqLagFeatures nf;
    gen_noise(buf, N, 1.0);
    iq_metrics(buf, N, &nm);
    iq_lag_features(buf, N, &nf);
    printf("\nS/N %.0f dB, after the gain loop, %d windows:\n"
           "  %-26s %5s %5s %5s | %5s %5s %5s %5s %5s | class bw scan\n",
           snr_db, NW, "waveform", "level", "q", "cv2", "r1", "r4", "r128", "r512", "r2667");
    printf("  %-26s %5s %5.1f %5.2f | %5.2f %5.2f %5.3f %5.3f %5.3f |\n",
           "noise", "-", nm.q_phase_pct, nm.env_cv2, nf.r1, nf.r4, nf.r128, nf.r512, nf.r2667);
    CHECK(nf.r128 < 0.03 && nf.r2667 < 0.02, "noise lag features r128 %.3f r2667 %.3f", nf.r128, nf.r2667);

    for (int kind = 0; kind < WF_COUNT; kind++) {
        double level = 1e9, q[NW], cv2[NW];
        IqLagFeatures sum = { 0 };
        int scan_lag = 0, hits = 0;
        float scan_r = 0;
        for (int w = 0; w < NW; w++) {
            IqMetrics m;
            IqLagFeatures lf;
            gen_waveform(kind, buf, N, a0, 1.0);
            double back = gain_loop(buf, N, a0, 1.0, &m);
            double lvl = back + 10 * log10(m.p_mean / nm.p_mean);
            if (lvl < level) level = lvl;
            q[w] = m.q_phase_pct;
            cv2[w] = m.env_cv2;
            iq_lag_features(buf, N, &lf);
            sum.r1 += lf.r1 / NW; sum.r4 += lf.r4 / NW; sum.r128 += lf.r128 / NW;
            sum.r512 += lf.r512 / NW; sum.r2667 += lf.r2667 / NW;
            /* The bench scan. The 802.11 symbol peak (0.18) stands ten sigma over
             * the scan's own estimation noise on one 410 us window; the LTE-like
             * CP peak (0.05, 4.7 us of copy in 71 us) about three, and the noise
             * maximum over 1760 lags reaches 0.04, so the bench sees that one on
             * most windows, not all: every window is scanned and counted. */
            if (kind == WF_LTE || (w == 0 && (kind == WF_DOT11 || kind == WF_DOT11_40))) {
                float r;
                int lag = iq_lag_scan(buf, N, 40, 3200, &r);
                if (lag >= 2665 && lag <= 2669) hits++;
                if (w == 0) { scan_lag = lag; scan_r = r; }
            }
        }
        double qm = median(q, NW), cm = median(cv2, NW);
        const char* cls = wb_class(&sum);
        int bw = wb_bucket(sum.r1, level);
        int analog = qm >= Q_MIN && cm <= ANALOG_CV2_MAX;
        printf("  %-26s %5.1f %5.1f %5.2f | %5.2f %5.2f %5.3f %5.3f %5.3f | %-5s %2d %4d (%.3f)",
               k_wf_names[kind], level, qm, cm, sum.r1, sum.r4, sum.r128, sum.r512, sum.r2667, cls, bw, scan_lag, scan_r);
        if (kind == WF_LTE) printf(" %d/%d", hits, NW);
        printf("%s\n", analog ? "  analog gate" : "");
        switch (kind) {
        case WF_FM:
            CHECK(level >= DETECT_LEVEL_DB && analog, "FM video must pass the analog gate: level %.1f q %.1f cv2 %.2f", level, qm, cm);
            CHECK(sum.r2667 < 0.02, "FM r2667 %.3f", sum.r2667);
            break;
        case WF_LTE:
            CHECK(level >= DETECT_LEVEL_DB && !analog, "LTE-like must fail the analog gate: q %.1f cv2 %.2f", qm, cm);
            CHECK(sum.r2667 >= WB_R2667_MIN && sum.r128 < WB_R128_LTE_MAX && strcmp(cls, "lte") == 0, "LTE-like r2667 %.3f r128 %.3f -> %s", sum.r2667, sum.r128, cls);
            CHECK(sum.r2667 >= WB_R2667_HIGH, "LTE-like r2667 %.3f short of conf high (%.3f)", sum.r2667, WB_R2667_HIGH);
            CHECK(sum.r1 >= 0.78 && bw == 10, "LTE-like r1 %.2f -> %d MHz", sum.r1, bw);
            CHECK(hits >= NW / 2, "LTE-like lag scan in 2665..2669 on %d of %d windows (w0: %d, %.3f)", hits, NW, scan_lag, scan_r);
            break;
        case WF_DOT11:
            CHECK(level >= DETECT_LEVEL_DB && !analog, "802.11-like must fail the analog gate: q %.1f cv2 %.2f", qm, cm);
            CHECK(sum.r128 >= WB_R128_MIN && strcmp(cls, "dot11") == 0, "802.11-like r128 %.3f -> %s", sum.r128, cls);
            CHECK(sum.r128 >= WB_R128_HIGH, "802.11-like r128 %.3f short of conf high (%.3f)", sum.r128, WB_R128_HIGH);
            CHECK(sum.r1 >= 0.52 && sum.r1 < 0.78 && bw == 20, "802.11-like r1 %.2f -> %d MHz", sum.r1, bw);
            CHECK(scan_lag == 128, "802.11-like lag scan %d (%.3f)", scan_lag, scan_r);
            break;
        case WF_DOT11_BURST:
            CHECK(!analog, "bursty 802.11-like must fail the analog gate: q %.1f cv2 %.2f", qm, cm);
            break;
        case WF_DOT11_40:
            CHECK(level >= DETECT_LEVEL_DB && !analog, "802.11-like 40 MHz must fail the analog gate: q %.1f cv2 %.2f", qm, cm);
            CHECK(sum.r128 >= WB_R128_MIN && strcmp(cls, "dot11") == 0, "802.11-like 40 MHz r128 %.3f -> %s", sum.r128, cls);
            CHECK(sum.r128 >= WB_R128_HIGH, "802.11-like 40 MHz r128 %.3f short of conf high (%.3f)", sum.r128, WB_R128_HIGH);
            CHECK(sum.r1 < 0.30 && bw == 40, "802.11-like 40 MHz r1 %.2f -> %d MHz", sum.r1, bw);
            CHECK(scan_lag == 128, "802.11-like 40 MHz lag scan %d (%.3f)", scan_lag, scan_r);
            break;
        case WF_SC:
            /* Four samples per symbol through a raised cosine: three phase steps in
             * four are small and the envelope ripple is mild, so a fast single carrier
             * reads as a coherent carrier (q ~50, cv2 ~0.3: SPEC 11) and passes the
             * gate. Printed for the record; what is pinned is that its lag features
             * carry no OFDM symbol, so it could only ever class as "wb". */
            CHECK(sum.r128 < WB_R128_LTE_MAX && sum.r2667 < WB_R2667_MIN && strcmp(cls, "wb") == 0, "SC QPSK r128 %.3f r2667 %.3f -> %s", sum.r128, sum.r2667, cls);
            break;
        }
    }
    g_seed = seed;
}

/* The price of three lanes per component: level above the noise reference and
 * FM coherence of a video carrier, at the real noise floor (sigma = 1 LSB of
 * the 4-bit scale), for both lane modes. Printed for the record; the strict
 * checks above are what gate the build. */
/* ---- The sweep's decision stage (sweep_decide.c) ---------------------------
 * run_sweep measures; these functions decide what is reported. The cases are
 * the real channel plan with hits and candidates placed by name. */
static SweepChannel g_sw[SWEEP_MAX_CHANNELS];
static int g_swn;
static void sw_reset(void)
{
    g_swn = fpv_channel_count();
    for (int i = 0; i < g_swn; i++) {
        g_sw[i].freq_mhz = fpv_channel(i)->freq_mhz;
        g_sw[i].level_db = 0.0f;
        g_sw[i].hit = 0;
        g_sw[i].wb = 0;
    }
}
static int sw_hit(const char* name, float level) { int i = fpv_find(name); if (i >= 0) { g_sw[i].hit = 1; g_sw[i].level_db = level; } return i; }
static int sw_wb(const char* name, float level)  { int i = fpv_find(name); if (i >= 0) { g_sw[i].wb = 1; g_sw[i].level_db = level; } return i; }
/* config.h's defaults: PEAK_PICK 20, ALIAS_GUARD 2 dB / 5 MHz at the top centre, 2 pull-ins,
 * WB_FOLD_MHZ 25, WB_ANALOG_OWN_MHZ as given, 2 passes */
static SweepRules sw_rules(int own_mhz)
{
    SweepRules r = { 1, 20, 1, fpv_wifi_top_centre_mhz(), 2.0f, 5, 2, 25, own_mhz, 2 };
    return r;
}
/* The channels of idx[] (those not dropped, when drop is given) as "R6 R3" */
static void sw_names(const int* idx, const uint8_t* drop, int n, char* out, size_t cap)
{
    out[0] = 0;
    for (int i = 0; i < n; i++) {
        if (drop && drop[i]) continue;
        const FpvChannel* c = fpv_channel(idx[i]);
        char t[12];
        snprintf(t, sizeof t, "%s%c%d", out[0] ? " " : "", c->band, c->number);
        strncat(out, t, cap - strlen(out) - 1);
    }
}

static void test_sweep_decide(void)
{
    SweepRules rules = sw_rules(30);
    SweepAnalog an;
    SweepWideband wb;
    char s[128];
    int picks[SWEEP_MAX_PASSES];

    /* Nothing in the sweep */
    sw_reset();
    sweep_analog(g_sw, g_swn, &rules, &an);
    int targets[SWEEP_MAX_CHANNELS] = {0};
    CHECK(an.nh == 0 && sweep_pullin(g_sw, targets, g_swn, &an, &rules, picks) == 0, "empty sweep: no hits, no pull-ins");
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 0 && wb.owned == 0 && wb.alias_dropped == 0, "empty sweep: no wideband passes");

    /* Analog: strongest first; the R3 / B1 / F1 overlap folds into the strongest, a far hit stays */
    sw_reset(); sw_hit("R3", 20); sw_hit("B1", 18); sw_hit("F1", 15); sw_hit("R6", 25);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sw_names(an.hits, an.drop, an.nh, s, sizeof s);
    CHECK(an.nh == 4 && strcmp(s, "R6 R3") == 0, "analog order and fold: %d hits, reported '%s'", an.nh, s);
    CHECK(an.alias_dropped == 0, "no mirrors in that sweep (%d)", an.alias_dropped);

    /* Analog mirror: R8 reading the E5 carrier within 2 dB is the parked synthesizer's image; 6 dB apart it is a second carrier */
    sw_reset(); sw_hit("E5", 20.0f); sw_hit("R8", 20.8f);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sw_names(an.hits, an.drop, an.nh, s, sizeof s);
    CHECK(strcmp(s, "E5") == 0 && an.alias_dropped == 1, "analog mirror: reported '%s', alias_dropped %d", s, an.alias_dropped);
    sw_reset(); sw_hit("E5", 20.0f); sw_hit("R8", 26.0f);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sw_names(an.hits, an.drop, an.nh, s, sizeof s);
    CHECK(strcmp(s, "R8 E5") == 0 && an.alias_dropped == 0, "two carriers up top: reported '%s' (%d mirrors)", s, an.alias_dropped);
    SweepRules unguarded = rules;
    unguarded.alias_guard = 0;
    sw_reset(); sw_hit("E5", 20.0f); sw_hit("R8", 20.8f);
    sweep_analog(g_sw, g_swn, &unguarded, &an);
    sw_names(an.hits, an.drop, an.nh, s, sizeof s);
    CHECK(strcmp(s, "R8 E5") == 0, "ALIAS_GUARD 0 keeps the mirror: '%s'", s);

    /* Pull-in: strongest channel's target first, the neighbour's copy of it skipped, a target an analog
     * hit owns skipped, two per sweep */
    sw_reset();
    memset(targets, 0, sizeof(targets));
    int d1 = fpv_find("D1"), d2 = fpv_find("D2"), l4 = fpv_find("L4"), l5 = fpv_find("L5"), l7 = fpv_find("L7"), f2 = fpv_find("F2");
    CHECK(d1 >= 0 && d2 >= 0 && l4 >= 0 && l5 >= 0 && l7 >= 0 && f2 >= 0, "pull-in fixture channels");
    g_sw[d1].level_db = 15; targets[d1] = 5200;     /* D1 5190 sees a carrier at +10 MHz ... */
    g_sw[d2].level_db = 14; targets[d2] = 5200;     /* ... D2 5210 the same one at -10 */
    g_sw[l4].level_db = 12; targets[l4] = 5490;
    g_sw[l5].level_db = 10; targets[l5] = 5490;
    g_sw[l7].level_db = 9;  targets[l7] = 5600;     /* a third carrier: over the budget of two */
    g_sw[f2].level_db = 30; targets[f2] = 5755;     /* the strongest ask, but the R4 hit owns 5755 */
    sw_hit("R4", 35);
    sweep_analog(g_sw, g_swn, &rules, &an);
    int np = sweep_pullin(g_sw, targets, g_swn, &an, &rules, picks);
    CHECK(np == 2 && picks[0] == 5200 && picks[1] == 5490, "pull-in picks: %d (%d %d)", np, np > 0 ? picks[0] : 0, np > 1 ? picks[1] : 0);

    /* Wideband fold: one 20 MHz link seen on F3 / A5 / B4 / R5 is keyed to the strongest, span = the footprint */
    sw_reset(); sw_wb("F3", 18); sw_wb("A5", 20); sw_wb("B4", 19); sw_wb("R5", 14);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("A5") && wb.span_mhz[0] == 26,
          "wb fold: n %d idx %d span %d", wb.n, wb.n ? wb.idx[0] : -1, wb.n ? wb.span_mhz[0] : -1);
    CHECK(wb.owned == 0 && wb.alias_dropped == 0, "wb fold: owned %d alias %d", wb.owned, wb.alias_dropped);
    /* a candidate folds into the strongest only: F4 goes with F3, A3 (45 MHz from F3) stands alone */
    sw_reset(); sw_wb("F3", 20); sw_wb("F4", 18); sw_wb("A3", 16);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 2 && wb.idx[0] == fpv_find("F3") && wb.span_mhz[0] == 20 && wb.idx[1] == fpv_find("A3") && wb.span_mhz[1] == 0,
          "wb chain: n %d spans %d %d", wb.n, wb.span_mhz[0], wb.span_mhz[1]);
    /* three separate links: strongest first, two per sweep */
    sw_reset(); sw_wb("R4", 15); sw_wb("R6", 22); sw_wb("L4", 18);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 2 && wb.idx[0] == fpv_find("R6") && wb.idx[1] == fpv_find("L4"), "wb budget: n %d", wb.n);

    /* Ownership: a strong FM carrier on R4 leaves a noise-like image on B4 (+21 MHz) and A7 (-24) through
     * the filter skirt (model). The old 20 MHz radius reported both as digital links; 30 owns them, and
     * the unrelated link on L6 is reported instead. */
    sw_reset(); sw_hit("R4", 35); sw_wb("B4", 12); sw_wb("A7", 11); sw_wb("L6", 9);
    sweep_analog(g_sw, g_swn, &rules, &an);
    SweepRules twenty = sw_rules(20);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &twenty, &wb);
    CHECK(wb.n == 2 && wb.idx[0] == fpv_find("B4") && wb.idx[1] == fpv_find("A7") && wb.owned == 0,
          "20 MHz radius let the skirt images through (n %d owned %d)", wb.n, wb.owned);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("L6") && wb.owned == 2,
          "30 MHz radius owns them and reports the far link (n %d owned %d)", wb.n, wb.owned);
    /* a hit folded into a stronger one still owns: F1 (folded into R3) covers R4 at 29 MHz, R3 itself is 37 away */
    sw_reset(); sw_hit("R3", 30); sw_hit("F1", 29); sw_wb("R4", 12);
    sweep_analog(g_sw, g_swn, &rules, &an);
    CHECK(an.nh == 2 && an.drop[1], "F1 folds into R3");
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 0 && wb.owned == 1, "a folded hit still owns (n %d owned %d)", wb.n, wb.owned);
    /* a pull-in that found a carrier owns like a hit: 5200 covers the candidate on D3 5230 */
    sw_reset(); sw_wb("D3", 12);
    sweep_analog(g_sw, g_swn, &rules, &an);
    int owner = 5200;
    sweep_wideband(g_sw, g_swn, &an, &owner, 1, &rules, &wb);
    CHECK(wb.n == 0 && wb.owned == 1, "pull-in owner: n %d owned %d", wb.n, wb.owned);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("D3"), "no pull-in found: D3 reported (n %d)", wb.n);

    /* Wideband mirror: a digital link at E5 shows again on E6, R8, E7 and E8 at its level when the
     * synthesizer is parked at 5885; the fold only reaches E6, the mirror test the rest */
    sw_reset(); sw_wb("E5", 20.0f); sw_wb("E6", 19.6f); sw_wb("R8", 20.3f); sw_wb("E7", 19.9f); sw_wb("E8", 20.1f);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("E5") && wb.span_mhz[0] == 0 && wb.alias_dropped == 4,
          "wb mirror: n %d idx %d span %d alias %d", wb.n, wb.n ? wb.idx[0] : -1, wb.n ? wb.span_mhz[0] : -1, wb.alias_dropped);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &unguarded, &wb);
    CHECK(wb.n == 2 && wb.alias_dropped == 0, "ALIAS_GUARD 0: the mirrors fold and compete (n %d)", wb.n);
    /* a second link 6 dB under the first is its own: E5, then R8 folding E7 (span 8); E8 is over the budget */
    sw_reset(); sw_wb("E5", 26.0f); sw_wb("R8", 20.3f); sw_wb("E7", 19.9f); sw_wb("E8", 20.1f);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 2 && wb.idx[0] == fpv_find("E5") && wb.idx[1] == fpv_find("R8") && wb.span_mhz[1] == 8 && wb.alias_dropped == 0,
          "two links up top: n %d second idx %d span %d alias %d", wb.n, wb.n > 1 ? wb.idx[1] : -1, wb.n > 1 ? wb.span_mhz[1] : -1, wb.alias_dropped);
    /* E6 at E5's level reads as a mirror rather than folding; the fold would have hidden it anyway (span 0 instead of 20) */
    sw_reset(); sw_wb("E5", 26.0f); sw_wb("E6", 25.5f);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("E5") && wb.alias_dropped == 1, "E6 under E5: n %d alias %d", wb.n, wb.alias_dropped);
    /* the reference can be an analog carrier near the top centre: F8's FM carrier, a candidate on R8 at its
     * level is the mirror, one 4 dB louder on E8 is a link of its own (and 65 MHz from F8: not owned) */
    sw_reset(); sw_hit("F8", 20.0f); sw_wb("R8", 20.5f); sw_wb("E8", 24.0f);
    sweep_analog(g_sw, g_swn, &rules, &an);
    sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
    CHECK(wb.n == 1 && wb.idx[0] == fpv_find("E8") && wb.alias_dropped == 1, "analog reference: n %d alias %d", wb.n, wb.alias_dropped);

    /* 2.4 GHz sits under the top centre: never a mirror (dual-band plan only) */
    if (fpv_find("G3") >= 0) {
        sw_reset(); sw_hit("E5", 20.0f); sw_wb("G3", 20.0f); sw_hit("G1", 20.0f);
        sweep_analog(g_sw, g_swn, &rules, &an);
        sw_names(an.hits, an.drop, an.nh, s, sizeof s);
        CHECK(strcmp(s, "E5 G1") == 0 && an.alias_dropped == 0, "2.4 GHz hit kept: '%s'", s);
        sweep_wideband(g_sw, g_swn, &an, NULL, 0, &rules, &wb);
        CHECK(wb.n == 1 && wb.idx[0] == fpv_find("G3") && wb.alias_dropped == 0, "2.4 GHz candidate kept (n %d)", wb.n);
    }
}

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
    test_wideband(30);
    test_wideband(12);
}

int main(void)
{
    run_suite(4);
    run_suite(3);
    test_bearing();
    test_channels();
    test_sweep_decide();
    test_switch_bits();
    test_report();
    test_wideband_report();
    sensitivity_table();
    printf(g_fail ? "\n%d FAILURE(S)\n" : "\nALL TESTS PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
