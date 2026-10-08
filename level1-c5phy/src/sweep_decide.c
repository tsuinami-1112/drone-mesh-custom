#include "sweep_decide.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

static int absdiff(int a, int b) { return a > b ? a - b : b - a; }

/* Insertion sort of channel indices, strongest first; stable, so equal levels
 * keep table order. */
static void sort_by_level(const SweepChannel* ch, int* idx, int n)
{
    for (int i = 1; i < n; i++) {
        int k = idx[i], j = i - 1;
        while (j >= 0 && ch[idx[j]].level_db < ch[k].level_db) {
            idx[j + 1] = idx[j];
            j--;
        }
        idx[j + 1] = k;
    }
}

static int clamp_n(int n) { return n > SWEEP_MAX_CHANNELS ? SWEEP_MAX_CHANNELS : (n < 0 ? 0 : n); }

void sweep_analog(const SweepChannel* ch, int n, const SweepRules* r, SweepAnalog* out)
{
    memset(out, 0, sizeof(*out));
    n = clamp_n(n);
    for (int i = 0; i < n; i++) if (ch[i].hit) out->hits[out->nh++] = i;
    sort_by_level(ch, out->hits, out->nh);

    /* PEAK_PICK: the same carrier shows on the channels that overlap it (R3
     * 5732, B1 5733, F1 5740); keep the strongest, drop the rest. */
    if (r->peak_pick) {
        for (int i = 0; i < out->nh; i++) {
            if (out->drop[i]) continue;
            for (int j = i + 1; j < out->nh; j++)
                if (!out->drop[j] && absdiff(ch[out->hits[i]].freq_mhz, ch[out->hits[j]].freq_mhz) <= r->peak_pick_mhz)
                    out->drop[j] = 1;
        }
    }
    /* ALIAS_GUARD: a synthesizer that did not follow phy_set_freq past the last
     * public centre leaves the receiver at that centre while the firmware
     * believes it is 20-60 MHz higher: a carrier near the centre then shows up
     * again, at the same level, on every channel above it. Drop such a mirror
     * image. A 5 GHz thing: every 2.4 GHz channel sits under the top centre. */
    if (r->alias_guard) {
        for (int i = 0; i < out->nh; i++) {
            if (out->drop[i]) continue;
            const SweepChannel* ci = &ch[out->hits[i]];
            if (ci->freq_mhz <= r->top_centre_mhz) continue;
            for (int j = 0; j < out->nh; j++) {
                if (j == i || out->drop[j]) continue;
                const SweepChannel* cj = &ch[out->hits[j]];
                if (absdiff(cj->freq_mhz, r->top_centre_mhz) > r->alias_near_mhz) continue;   /* a carrier the parked receiver sees */
                if (fabsf(ci->level_db - cj->level_db) <= r->alias_level_db) { out->drop[i] = 1; out->alias_dropped++; break; }
            }
        }
    }
}

/* Is there an analog hit (reported or dropped: a folded hit is the same
 * carrier, a mirror stands where the firmware believes it is) within mhz? */
static int near_analog(const SweepChannel* ch, const SweepAnalog* an, int freq_mhz, int mhz)
{
    for (int h = 0; h < an->nh; h++)
        if (absdiff(ch[an->hits[h]].freq_mhz, freq_mhz) <= mhz) return 1;
    return 0;
}

int sweep_pullin(const SweepChannel* ch, const int* targets, int n, const SweepAnalog* an,
                 const SweepRules* r, int* out)
{
    int cand[SWEEP_MAX_CHANNELS], nc = 0, nt = 0;
    n = clamp_n(n);
    for (int i = 0; i < n; i++) if (targets[i] > 0) cand[nc++] = i;
    sort_by_level(ch, cand, nc);
    int cap = r->pullin_max > SWEEP_MAX_PASSES ? SWEEP_MAX_PASSES : r->pullin_max;
    for (int k = 0; k < nc && nt < cap; k++) {
        int target = targets[cand[k]];
        int owned = near_analog(ch, an, target, r->peak_pick_mhz);
        for (int t = 0; t < nt && !owned; t++) owned = absdiff(out[t], target) <= r->peak_pick_mhz;
        if (owned) continue;
        out[nt++] = target;
    }
    return nt;
}

void sweep_wideband(const SweepChannel* ch, int n, const SweepAnalog* an, const int* owner_mhz, int n_owners,
                    const SweepRules* r, SweepWideband* out)
{
    int wbs[SWEEP_MAX_CHANNELS], nw = 0;
    uint8_t drop[SWEEP_MAX_CHANNELS];
    int fold[SWEEP_MAX_CHANNELS];           /* position of the stronger candidate this one folded into, -1 = survivor */
    memset(out, 0, sizeof(*out));
    memset(drop, 0, sizeof(drop));
    n = clamp_n(n);
    for (int i = 0; i < n; i++) if (ch[i].wb) wbs[nw++] = i;
    sort_by_level(ch, wbs, nw);

    /* The analog mirror test again: a digital link near the top centre shows
     * up on every channel above it when the synthesizer is parked, and the
     * fold reaches 25 MHz of it, not 60. The reference is a candidate or an
     * analog hit within alias_near_mhz of the centre. */
    if (r->alias_guard) {
        for (int i = 0; i < nw; i++) {
            const SweepChannel* ci = &ch[wbs[i]];
            if (ci->freq_mhz <= r->top_centre_mhz) continue;
            int mirror = 0;
            for (int j = 0; j < nw && !mirror; j++) {
                if (j == i || drop[j]) continue;
                const SweepChannel* cj = &ch[wbs[j]];
                if (absdiff(cj->freq_mhz, r->top_centre_mhz) > r->alias_near_mhz) continue;
                mirror = fabsf(ci->level_db - cj->level_db) <= r->alias_level_db;
            }
            for (int h = 0; h < an->nh && !mirror; h++) {
                const SweepChannel* cj = &ch[an->hits[h]];
                if (absdiff(cj->freq_mhz, r->top_centre_mhz) > r->alias_near_mhz) continue;
                mirror = fabsf(ci->level_db - cj->level_db) <= r->alias_level_db;
            }
            if (mirror) { drop[i] = 1; out->alias_dropped++; }
        }
    }
    /* Fold: a digital link 10-40 MHz wide shows on every table channel it
     * overlaps; the weaker ones within wb_fold_mhz are the strongest one's. */
    for (int i = 0; i < nw; i++) fold[i] = -1;
    for (int i = 0; i < nw; i++) {
        if (drop[i] || fold[i] >= 0) continue;
        for (int j = i + 1; j < nw; j++)
            if (!drop[j] && fold[j] < 0 && absdiff(ch[wbs[i]].freq_mhz, ch[wbs[j]].freq_mhz) <= r->wb_fold_mhz) fold[j] = i;
    }
    /* Survivors: an analog carrier within wb_own_mhz owns the candidate (its
     * sidebands and its filter-skirt image are not a second emitter). */
    int cap = r->wb_max > SWEEP_MAX_PASSES ? SWEEP_MAX_PASSES : r->wb_max;
    for (int i = 0; i < nw && out->n < cap; i++) {
        if (drop[i] || fold[i] >= 0) continue;
        const int fi = ch[wbs[i]].freq_mhz;
        int owned = near_analog(ch, an, fi, r->wb_own_mhz);
        for (int o = 0; o < n_owners && !owned; o++) owned = absdiff(owner_mhz[o], fi) <= r->wb_own_mhz;
        if (owned) { out->owned++; continue; }
        int lo = fi, hi = fi;
        for (int j = i + 1; j < nw; j++) {
            if (fold[j] != i) continue;
            int fj = ch[wbs[j]].freq_mhz;
            if (fj < lo) lo = fj;
            if (fj > hi) hi = fj;
        }
        out->idx[out->n] = wbs[i];
        out->span_mhz[out->n] = hi - lo;
        out->n++;
    }
}
