/* I/Q metrics, the software video check and the lag features of the wideband
 * (digital video link) path for the C5 PHY receiver.
 *
 * Input is one PARLIO capture: one byte per sample at 40 MS/s, I in the high
 * nibble and Q in the low nibble, each a 4-bit two's complement value (bits
 * 9..6 of the modem's 10-bit sample). Plain C, no Arduino/ESP-IDF dependency,
 * compiled and tested on a desktop by test/host. */
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define DEMOD_SAMPLE_RATE_HZ 40000000.0
#define DEMOD_MAX_SAMPLES    16384

typedef struct {
    float p_mean;        /* mean I^2+Q^2 (noise alone at full gain: ~2.0) */
    float clip_pct;      /* share of samples with I or Q at 4-bit full scale */
    float q_phase_pct;   /* FM coherence: share of samples with power >= 8 and a
                            phase step within +/-45 deg (|offset| <= 5 MHz) */
    float cfo_khz;       /* mean phase step -> carrier offset from the tuned frequency */
    float env_cv2;       /* variance / mean^2 of the sample power: ~1 noise, ~0 carrier */
    float step_std_deg;  /* std of the 0.8 us box-averaged phase step, degrees/sample */
    int   noise;         /* 1 = envelope looks like noise */
    int   mod;           /* 1 = a coherent carrier that is not a bare CW (video swing); 0 on noise */
    int   stuck;         /* 1 = every sample identical on the wired lanes: the I/Q bus is not
                            streaming (a dead bus reads p_mean 2.0 in 3-lane mode, like noise) */
} IqMetrics;

typedef struct {
    int   present;       /* 1 = a repeating line structure was found in this window */
    char  std[5];        /* "PAL", "NTSC" or "none" */
    float line_period;   /* samples */
    float line_hz;
    int   score;         /* 0..100: sync width closeness 0..40 + line period closeness 0..60 */
    int   pulses;        /* sync-shaped pulses (3.2..7.2 us) found */
    int   periods;       /* longest run of consecutive line periods that matched */
    int   swing;         /* p95 - p5 of the discriminator, LUT units (1 unit = 1.4 deg/sample = 156 kHz) */
    int   polarity;      /* -1 sync tips at the low frequency end, +1 at the high end */
} VideoResult;

typedef struct {
    float r1, r4, r128, r512, r2667;   /* |R(L)| / R(0) of the decoded window, 0..1 */
} IqLagFeatures;

typedef struct {
    int  present;        /* >= min_windows windows carried a line structure */
    char std[5];         /* majority standard, "none" when not present */
    int  sync_hz;        /* mean line rate of the windows that counted */
    int  field_hz;       /* nominal 50 / 60 of the standard; a 410 us window never sees a field */
    int  sync_q;         /* percent of windows that counted */
    int  sync_score;     /* mean score of the windows that counted */
    int  windows;
} VideoVerdict;

/* Builds the decode tables and the 64 KiB phase-step lookup table. Call once.
 * bits = 4: all four lanes of each component wired (C5VRX layout).
 * bits = 3: the bit-6 lanes are not wired; each nibble's bit 0 is ignored and
 *           the value is taken as the midpoint of the two codes it merges,
 *           so the scale (and every threshold) stays the same. */
void demod_init_bits(int bits);
/* Decoded I or Q value of one nibble under the current lane mode. */
int  demod_decode_nibble(unsigned nib);
int  demod_lane_bits(void);
void iq_metrics(const uint8_t* buf, int n, IqMetrics* m);
void video_window(const uint8_t* buf, int n, VideoResult* r);
void video_verdict(const VideoResult* r, int n, int min_windows, VideoVerdict* v);
/* Lag autocorrelations of the wideband path: r1 is the bandwidth proxy, r128
 * the 802.11 OFDM symbol (3.2 us), r512 11ax (12.8 us), r2667 LTE-like 66.7 us
 * symbols (DJI OcuSync). Integer one-pass sums per lag over the decoded
 * (lane-mode) values; r2667 = max over lags 2665..2669 (66.7 us is not an
 * integer number of 40 MS/s samples). n <= DEMOD_MAX_SAMPLES. One lag = one
 * pass of 16 K LUT decodes and MACs (~1 ms on the C5): only run on candidates. */
void iq_lag_features(const uint8_t* buf, int n, IqLagFeatures* f);
/* Bench: best |R(L)|/R0 for L in [lag_min, lag_max] (step 1 below 400, step 2
 * above). Returns the lag, writes r. ~1760 passes for 40..3200: seconds. */
int  iq_lag_scan(const uint8_t* buf, int n, int lag_min, int lag_max, float* r_out);

/* Raw 4-bit two's complement nibble -> int (hardware code, no lane mode). */
static inline int demod_nib(unsigned v) { return (int)((v & 0xFu) ^ 8u) - 8; }

#ifdef __cplusplus
}
#endif
