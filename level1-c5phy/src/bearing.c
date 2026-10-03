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
    memset(r, 0, sizeof(*r));
    if (n < 2) return;
    int k = 0;
    for (int i = 1; i < n; i++) if (level_db[i] > level_db[k]) k = i;
    int right = (k + 1) % n;             /* clockwise neighbour */
    int left = (k + n - 1) % n;          /* counter-clockwise neighbour */
    float diff = level_db[right] - level_db[left];
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
    float nb = level_db[right] > level_db[left] ? level_db[right] : level_db[left];
    if (level_db[k] - nb < 3.0f) sigma += 8.0f;
    r->sigma_deg = sigma;
}
