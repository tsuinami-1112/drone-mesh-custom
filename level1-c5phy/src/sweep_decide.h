/* The sweep's decision stage: which analog hits are reported, which pull-in
 * targets are tried, which wideband candidates get a confirmation pass.
 * Plain C over the per-channel results so the host tests can drive it;
 * main.cpp measures and reports. */
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define SWEEP_MAX_CHANNELS 64   /* MAX_CHANNELS of config.h */
#define SWEEP_MAX_PASSES    8   /* bound on WB_MAX_PER_SWEEP and PULLIN_MAX_PER_SWEEP */

typedef struct {
    int     freq_mhz;       /* the table channel */
    float   level_db;       /* its strongest sector: the minimum over the sector's windows */
    uint8_t hit;            /* passed the analog gate */
    uint8_t wb;             /* wideband candidate */
} SweepChannel;

typedef struct {
    int   peak_pick;        /* 1: analog hits within peak_pick_mhz of a stronger one are the same carrier */
    int   peak_pick_mhz;    /* also the radius a pull-in target is owned within */
    int   alias_guard;      /* 1: drop what merely mirrors a carrier at the top centre */
    int   top_centre_mhz;   /* the last public 5 GHz centre (fpv_wifi_top_centre_mhz) */
    float alias_level_db;   /* a mirror reads within this of the carrier the parked receiver sees */
    int   alias_near_mhz;   /* ... a carrier within this of the top centre */
    int   pullin_max;       /* pull-in attempts per sweep */
    int   wb_fold_mhz;      /* wideband candidates this close to a stronger one are one emitter */
    int   wb_own_mhz;       /* an analog carrier this close owns a wideband candidate */
    int   wb_max;           /* confirmation passes per sweep */
} SweepRules;

typedef struct {
    int     nh;                             /* analog hits, strongest first */
    int     hits[SWEEP_MAX_CHANNELS];       /* channel indices */
    uint8_t drop[SWEEP_MAX_CHANNELS];       /* folded into a stronger hit, or a mirror: not reported */
    int     alias_dropped;
} SweepAnalog;

typedef struct {
    int n;                                  /* survivors, strongest first */
    int idx[SWEEP_MAX_PASSES];              /* channel indices */
    int span_mhz[SWEEP_MAX_PASSES];         /* footprint: max - min MHz of the channels folded into each */
    int alias_dropped;
    int owned;                              /* candidates an analog carrier owned (not reported) */
} SweepWideband;

/* Analog hits strongest first; a hit within peak_pick_mhz of a stronger one is
 * dropped (the same carrier on overlapping channels), then a hit above the top
 * centre whose level is within alias_level_db of a hit within alias_near_mhz of
 * that centre (the parked synthesizer's mirror). A dropped hit is not reported
 * but still stands for its carrier in the two functions below. */
void sweep_analog(const SweepChannel* ch, int n, const SweepRules* r, SweepAnalog* out);

/* targets[i]: the MHz channel i asks to be pulled in to, 0 for none. Up to
 * r->pullin_max targets to try, strongest channel first, skipping one within
 * peak_pick_mhz of an analog hit (which owns it) or of an earlier pick (both
 * neighbours see the same carrier). Returns how many were written to out[]. */
int sweep_pullin(const SweepChannel* ch, const int* targets, int n, const SweepAnalog* an,
                 const SweepRules* r, int* out);

/* Wideband candidates strongest first. Under alias_guard a candidate above the
 * top centre whose level is within alias_level_db of a candidate or an analog
 * hit within alias_near_mhz of that centre is a mirror and dropped. Candidates
 * within wb_fold_mhz of a stronger one fold into it (span_mhz keeps the
 * footprint). A survivor within wb_own_mhz of an analog hit, dropped or not, or
 * of an owner_mhz[] carrier (the sweep's successful pull-ins) belongs to that
 * carrier: the filter skirt turns a strong FM carrier into a noise-like image
 * 18-24 MHz away (model), not a second emitter. At most r->wb_max survivors. */
void sweep_wideband(const SweepChannel* ch, int n, const SweepAnalog* an, const int* owner_mhz, int n_owners,
                    const SweepRules* r, SweepWideband* out);

#ifdef __cplusplus
}
#endif
