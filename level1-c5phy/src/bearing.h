/* Amplitude-comparison bearing from the four sector levels. Plain C. */
#pragma once
#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int   sector;        /* strongest sector */
    float bearing_deg;   /* 0..360, relative to the box's face N (sector 0 axis) */
    float sigma_deg;     /* 1-sigma estimate, grows near a sector boundary and near the threshold */
    float peak_db;       /* level of the strongest sector */
} BearingResult;

/* level_db[n] per sector, az_deg[n] the sector axes in degrees clockwise from
 * face N. bearing = az[k] + k_deg_per_db * (P[k+1] - P[k-1]), clamped to
 * +/-max_offset_deg from the axis of the strongest sector k. threshold_db is
 * the detection threshold, used only to scale the noise term of sigma. */
void bearing_estimate(const float* level_db, const float* az_deg, int n,
                      float k_deg_per_db, float max_offset_deg, float sigma_base_deg,
                      float threshold_db, BearingResult* r);

float bearing_wrap360(float deg);

#ifdef __cplusplus
}
#endif
