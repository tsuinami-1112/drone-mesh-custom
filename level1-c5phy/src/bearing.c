#include "bearing.h"
#include <math.h>
#include <string.h>

float bearing_wrap360(float deg)
{
    while (deg < 0.0f) deg += 360.0f;
    while (deg >= 360.0f) deg -= 360.0f;
    return deg;
}

void bearing_estimate(const float* level_db, const float* az_deg, int n,
                      float k_deg_per_db, float max_offset_deg, float sigma_base_deg,
                      float threshold_db, BearingResult* r)
{
    bearing_estimate_masked(level_db, NULL, az_deg, n, k_deg_per_db, max_offset_deg, sigma_base_deg, threshold_db, r);
}

void bearing_estimate_masked(const float* level_db, const int* valid, const float* az_deg, int n,
                             float k_deg_per_db, float max_offset_deg, float sigma_base_deg,
                             float threshold_db, BearingResult* r)
{
    memset(r, 0, sizeof(*r));
    if (n < 2) return;
    int k = -1;
    for (int i = 0; i < n; i++) {
        if (valid && !valid[i]) continue;
        if (k < 0 || level_db[i] > level_db[k]) k = i;
    }
    if (k < 0) return;
    int right = (k + 1) % n;             /* clockwise neighbour */
    int left = (k + n - 1) % n;          /* counter-clockwise neighbour */
    int neighbours_ok = !valid || (valid[right] && valid[left]);
    float diff = neighbours_ok ? level_db[right] - level_db[left] : 0.0f;
    float offset = k_deg_per_db * diff;
    if (offset > max_offset_deg) offset = max_offset_deg;
    if (offset < -max_offset_deg) offset = -max_offset_deg;

    r->sector = k;
    r->peak_db = level_db[k];
    r->bearing_deg = bearing_wrap360(az_deg[k] + offset);

    /* Per-sector level noise: ~1 dB well above the threshold, ~3 dB at it.
     * The estimate uses a difference of two levels, hence the sqrt(2). */
    float margin = level_db[k] - threshold_db;
    float noise_db = margin >= 10.0f ? 1.0f : (margin <= 0.0f ? 3.0f : 3.0f - 0.2f * margin);
    float sigma_noise = k_deg_per_db * noise_db * 1.4142f;
    float sigma = sqrtf(sigma_base_deg * sigma_base_deg + sigma_noise * sigma_noise);
    /* On a sector boundary the strongest sector itself is ambiguous. */
    if (neighbours_ok) {
        float nb = level_db[right] > level_db[left] ? level_db[right] : level_db[left];
        if (level_db[k] - nb < 3.0f) sigma += 8.0f;
    } else {
        sigma += max_offset_deg * 0.5f;  /* no neighbour comparison: anywhere in the sector */
    }
    r->sigma_deg = sigma;
}
