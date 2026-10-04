#include "demod.h"
#include <math.h>
#include <string.h>
#include <stdlib.h>

#define DEMOD_PI 3.14159265358979323846

/* Phase step from sample a to sample b, 256 units per turn (int8: -180..+179 deg). */
static int8_t  s_step_lut[65536];
static uint8_t s_pwr_lut[256];
static int8_t  s_val_lut[16];          /* nibble -> I or Q value under the lane mode */
static int8_t  s_steps[DEMOD_MAX_SAMPLES];
static int     s_ready;
static int     s_bits = 4;
static int     s_full_pos = 7, s_full_neg = -8;   /* full-scale codes: clipping */
static uint8_t s_data_mask = 0xFF;                /* byte bits that carry wired lanes */

int demod_lane_bits(void) { return s_bits; }
int demod_decode_nibble(unsigned nib) { return s_val_lut[nib & 0xFu]; }

#define BOX        32           /* 0.8 us box average on the discriminator */
#define BOX_SHIFT  5
#define Q_POWER_MIN 8           /* a sample counts for coherence only above this power */
#define COH_LIMIT  32           /* 45 deg in LUT units */
#define MOD_STD_DEG 4.0f        /* box-averaged step std above this = FM deviation present */

void demod_init_bits(int bits)
{
    if (s_ready && bits == s_bits) return;
    s_bits = (bits == 3) ? 3 : 4;
    for (unsigned n = 0; n < 16; n++) {
        if (s_bits == 4) {
            s_val_lut[n] = (int8_t)demod_nib(n);                 /* -8..7 */
        } else {
            /* Bit 0 is an unwired lane: ignore it and read the midpoint of the
             * two 4-bit codes that share the upper three bits -> -7,-5,..,7. */
            s_val_lut[n] = (int8_t)(demod_nib(n & 0xEu) + 1);
        }
    }
    s_full_pos = 7;
    s_full_neg = (s_bits == 4) ? -8 : -7;
    s_data_mask = (s_bits == 4) ? 0xFF : 0xEE;
    for (unsigned b = 0; b < 256; b++) {
        int i = s_val_lut[b >> 4], q = s_val_lut[b & 0xF];
        s_pwr_lut[b] = (uint8_t)(i * i + q * q);        /* max 128 */
    }
    for (unsigned a = 0; a < 256; a++) {
        int i0 = s_val_lut[a >> 4], q0 = s_val_lut[a & 0xF];
        for (unsigned b = 0; b < 256; b++) {
            int i1 = s_val_lut[b >> 4], q1 = s_val_lut[b & 0xF];
            int dot = i0 * i1 + q0 * q1;
            int cross = i0 * q1 - q0 * i1;              /* arg(s1 * conj(s0)) */
            float ang = atan2f((float)cross, (float)dot);
            long v = lrintf(ang * (128.0f / (float)DEMOD_PI));
            if (v > 127) v = 127;
            if (v < -128) v = -128;
            s_step_lut[(a << 8) | b] = (int8_t)v;
        }
    }
    s_ready = 1;
}

void iq_metrics(const uint8_t* buf, int n, IqMetrics* m)
{
    memset(m, 0, sizeof(*m));
    if (!s_ready) demod_init_bits(s_bits);
    if (n < 2) return;
    if (n > DEMOD_MAX_SAMPLES) n = DEMOD_MAX_SAMPLES;

    /* Integer accumulators: the C5 has a single-precision FPU only and a
     * 16 K-sample window must take ~2 ms, not 30. Ranges: p <= 128, so
     * p_sum < 2^21, p_sq < 2^29; |dot|,|cross| <= 128, so their sums < 2^21. */
    int32_t p_sum = 0, dot_sum = 0, cross_sum = 0;
    int64_t p_sq = 0;
    int32_t clip = 0, coh = 0;
    unsigned first = buf[0] & s_data_mask;
    int stuck = 1;
    for (int k = 0; k < n; k++) {
        unsigned b = buf[k];
        if ((b & s_data_mask) != first) stuck = 0;
        int i = s_val_lut[b >> 4], q = s_val_lut[b & 0xF];
        int p = s_pwr_lut[b];
        p_sum += p;
        p_sq += (int64_t)p * p;
        if (i >= s_full_pos || i <= s_full_neg || q >= s_full_pos || q <= s_full_neg) clip++;
        if (k > 0) {
            unsigned a = buf[k - 1];
            int i0 = s_val_lut[a >> 4], q0 = s_val_lut[a & 0xF];
            dot_sum += i0 * i + q0 * q;
            cross_sum += i0 * q - q0 * i;
            int st = s_step_lut[(a << 8) | b];
            s_steps[k] = (int8_t)st;
            if (p >= Q_POWER_MIN && s_pwr_lut[a] >= Q_POWER_MIN && st >= -COH_LIMIT && st <= COH_LIMIT)
                coh++;
        }
    }
    s_steps[0] = s_steps[1];

    float pm = (float)p_sum / (float)n;
    m->p_mean = pm;
    m->clip_pct = 100.0f * (float)clip / (float)n;
    m->q_phase_pct = 100.0f * (float)coh / (float)(n - 1);
    m->cfo_khz = atan2f((float)cross_sum, (float)dot_sum) / (2.0f * (float)DEMOD_PI)
               * (float)DEMOD_SAMPLE_RATE_HZ / 1000.0f;
    float var = (float)((double)p_sq / n) - pm * pm;
    m->env_cv2 = pm > 0 ? var / (pm * pm) : 0.0f;

    /* Box-averaged discriminator: noise averages down by sqrt(BOX), a video
     * swing (sync, blanking, picture) does not. */
    int32_t acc = 0;                    /* sum of BOX int8 steps: |acc| <= 4096 */
    int64_t s_sum = 0, s_sq = 0;
    int32_t cnt = 0;
    for (int k = 0; k < n; k++) {
        acc += s_steps[k];
        if (k >= BOX) acc -= s_steps[k - BOX];
        if (k >= BOX - 1) {
            s_sum += acc;
            s_sq += (int64_t)acc * acc;
            cnt++;
        }
    }
    if (cnt > 1) {
        float ms = (float)((double)s_sum / cnt), v = (float)((double)s_sq / cnt) - ms * ms;
        m->step_std_deg = sqrtf(v > 0 ? v : 0) / BOX * (360.0f / 256.0f);
    }
    m->noise = m->env_cv2 > 0.5f;
    m->mod = m->step_std_deg > MOD_STD_DEG;
    m->stuck = stuck;
}

/* ---- video line structure ------------------------------------------------- */

#define W_MIN    128     /* 3.2 us sync-shaped pulse */
#define W_MAX    288     /* 7.2 us */
#define W_IDEAL  188     /* 4.7 us */
#define PAL_PERIOD  2560.0f   /* 64.0 us */
#define NTSC_PERIOD 2542.2f   /* 63.56 us */
#define PERIOD_TOL  0.025f
#define MAX_PULSES  24
#define MIN_SWING   4

typedef struct {
    int score, pulses, periods, polarity;
    float period;
    const char* std;
} Candidate;

static int percentile(const int* hist, int total, int pct)
{
    long target = (long)total * pct / 100;
    long acc = 0;
    for (int i = 0; i < 256; i++) {
        acc += hist[i];
        if (acc >= target) return i - 128;
    }
    return 127;
}

static void evaluate_polarity(int n, int thr, int polarity, Candidate* c)
{
    int starts[MAX_PULSES], widths[MAX_PULSES], np = 0;
    int32_t acc = 0;
    int run = 0, run_start = 0;
    for (int k = 0; k < n; k++) {
        acc += s_steps[k];
        if (k >= BOX) acc -= s_steps[k - BOX];
        if (k < BOX - 1) continue;
        int v = (int)(acc / BOX);
        int in = polarity < 0 ? (v < thr) : (v > thr);
        if (in) {
            if (run == 0) run_start = k;
            run++;
        } else if (run) {
            if (run >= W_MIN && run <= W_MAX && run_start > BOX - 1 && np < MAX_PULSES) {
                starts[np] = run_start;
                widths[np] = run;
                np++;
            }
            run = 0;
        }
    }
    memset(c, 0, sizeof(*c));
    c->polarity = polarity;
    c->std = "none";
    c->pulses = np;
    if (np < 3) return;

    /* Longest run of consecutive periods near a video line period. */
    int best_len = 0, best_end = 0;
    int len = 0;
    for (int i = 1; i < np; i++) {
        float p = (float)(starts[i] - starts[i - 1]);
        float mid = 0.5f * (PAL_PERIOD + NTSC_PERIOD);
        if (fabsf(p - mid) <= mid * PERIOD_TOL) {
            len++;
            if (len > best_len) { best_len = len; best_end = i; }
        } else {
            len = 0;
        }
    }
    if (best_len < 1) return;
    int first = best_end - best_len;          /* index of the first pulse of the run */
    float period = (float)(starts[best_end] - starts[first]) / best_len;
    float wsum = 0;
    for (int i = first; i <= best_end; i++) wsum += (float)widths[i];
    float wmean = wsum / (best_len + 1);

    float d_pal = fabsf(period - PAL_PERIOD), d_ntsc = fabsf(period - NTSC_PERIOD);
    float d = d_pal < d_ntsc ? d_pal : d_ntsc;
    c->std = d_pal < d_ntsc ? "PAL" : "NTSC";
    float ws = 40.0f * (1.0f - fabsf(wmean - W_IDEAL) / 100.0f);
    float ps = 60.0f * (1.0f - d / 30.0f);
    if (ws < 0) ws = 0;
    if (ps < 0) ps = 0;
    c->score = (int)(ws + ps + 0.5f);
    c->periods = best_len;
    c->period = period;
}

void video_window(const uint8_t* buf, int n, VideoResult* r)
{
    memset(r, 0, sizeof(*r));
    strcpy(r->std, "none");
    if (!s_ready) demod_init_bits(s_bits);
    if (n < 4096) return;
    if (n > DEMOD_MAX_SAMPLES) n = DEMOD_MAX_SAMPLES;

    /* Discriminator: phase step between consecutive samples = instantaneous frequency. */
    for (int k = 1; k < n; k++) s_steps[k] = s_step_lut[((unsigned)buf[k - 1] << 8) | buf[k]];
    s_steps[0] = s_steps[1];

    /* Percentiles of the box-averaged discriminator set the sync threshold
     * from the window's own content. */
    int hist[256];
    memset(hist, 0, sizeof(hist));
    int32_t acc = 0;
    int total = 0;
    for (int k = 0; k < n; k++) {
        acc += s_steps[k];
        if (k >= BOX) acc -= s_steps[k - BOX];
        if (k >= BOX - 1) {
            int v = (int)(acc / BOX);
            hist[v + 128]++;
            total++;
        }
    }
    int p5 = percentile(hist, total, 5);
    int p50 = percentile(hist, total, 50);
    int p95 = percentile(hist, total, 95);
    r->swing = p95 - p5;
    if (r->swing < MIN_SWING) return;        /* no FM deviation on this channel */

    /* Sync tips sit at one end of the swing; FPV transmitters are not all the
     * same way round, so try both and keep the better line structure. */
    Candidate lo, hi;
    int thr_lo = p5 + (int)(0.35f * (p50 - p5));
    int thr_hi = p95 - (int)(0.35f * (p95 - p50));
    evaluate_polarity(n, thr_lo, -1, &lo);
    evaluate_polarity(n, thr_hi, +1, &hi);
    Candidate* c = (hi.score > lo.score) ? &hi : &lo;

    r->pulses = c->pulses;
    r->periods = c->periods;
    r->score = c->score;
    r->polarity = c->polarity;
    r->line_period = c->period;
    r->line_hz = c->period > 0 ? (float)(DEMOD_SAMPLE_RATE_HZ / c->period) : 0.0f;
    strncpy(r->std, c->std, sizeof(r->std) - 1);
    r->present = (c->periods >= 2 && c->score >= 70);
    if (!r->present) strcpy(r->std, "none");
}

void video_verdict(const VideoResult* r, int n, int min_windows, VideoVerdict* v)
{
    memset(v, 0, sizeof(*v));
    strcpy(v->std, "none");
    v->windows = n;
    int pal = 0, ntsc = 0;
    for (int i = 0; i < n; i++) {
        if (!r[i].present) continue;
        if (strcmp(r[i].std, "PAL") == 0) pal++; else ntsc++;
    }
    int counted = pal + ntsc;
    if (n > 0) v->sync_q = 100 * counted / n;
    if (counted == 0) return;
    const char* std = pal > ntsc ? "PAL" : "NTSC";
    double hz = 0, sc = 0;
    int k = 0;
    for (int i = 0; i < n; i++) {
        if (!r[i].present || strcmp(r[i].std, std) != 0) continue;
        hz += r[i].line_hz;
        sc += r[i].score;
        k++;
    }
    if (k == 0) return;
    v->sync_hz = (int)(hz / k + 0.5);
    v->sync_score = (int)(sc / k + 0.5);
    v->present = counted >= min_windows;
    if (v->present) {
        strncpy(v->std, std, sizeof(v->std) - 1);
        v->field_hz = pal > ntsc ? 50 : 60;
    }
}
