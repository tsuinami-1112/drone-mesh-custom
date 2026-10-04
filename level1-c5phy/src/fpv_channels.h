/* 5.8 GHz analog FPV channel table and the ESP32-C5 5 GHz bootstrap centres.
 * Plain C, shared with the host tests. */
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char     band;      /* 'R','A','B','E','F','L' */
    uint8_t  number;    /* 1..8 */
    uint16_t freq_mhz;
} FpvChannel;

/* Number of channels in the scan plan (40, or 48 with LOWBAND). */
int fpv_channel_count(void);
const FpvChannel* fpv_channel(int index);
/* "R3", "r3", "5732" -> index, or -1. */
int fpv_find(const char* name);
/* Channel nearest to a frequency. */
int fpv_nearest(int freq_mhz);
/* Nearest public 5 GHz Wi-Fi centre the closed PHY can be parked on first.
 * Returns 0 if freq is outside the C5's 5 GHz window. */
int fpv_wifi_bootstrap(int freq_mhz, uint8_t* wifi_channel, uint16_t* centre_mhz);
/* The rank-th nearest centre (0 = nearest); 0 when rank is out of range or
 * freq outside the window. rf_tune walks the ranks when a regulatory table
 * refuses the nearest one. */
int fpv_wifi_bootstrap_rank(int freq_mhz, int rank, uint8_t* wifi_channel, uint16_t* centre_mhz);
/* Highest public centre: a tuned frequency above it relies on phy_set_freq
 * pulling the synthesizer past the last Wi-Fi channel. */
int fpv_wifi_top_centre_mhz(void);

#ifdef __cplusplus
}
#endif
