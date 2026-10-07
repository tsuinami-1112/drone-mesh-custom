/* FPV channel table (the 5.8 GHz analog bands, the scan points for digital
 * links, 2.4 GHz under DUAL_BAND) and the ESP32-C5 Wi-Fi bootstrap centres.
 * Plain C, shared with the host tests. */
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char     band;      /* 'R','A','B','E','F' analog; 'X' gap, 'D' 5.1 GHz, 'L' Lowband, 'G' 2.4 GHz */
    uint8_t  number;    /* 1..8 */
    uint16_t freq_mhz;
} FpvChannel;

/* Number of channels in the scan plan: R A B E F (40) + X1 X2 + D1..D3 + L4..L8
 * = 50 by default; +3 with LOWBAND 2 (L1..L3), +5 with DUAL_BAND (G1..G5). */
int fpv_channel_count(void);
const FpvChannel* fpv_channel(int index);
/* "R3", "r3", "5732" -> index, or -1. */
int fpv_find(const char* name);
/* Channel nearest to a frequency. */
int fpv_nearest(int freq_mhz);
/* 2 or 5. */
int fpv_freq_band_ghz(int freq_mhz);
/* Band of a plan channel, 0 for an index outside the plan. */
int fpv_channel_band_ghz(int index);
/* "2.4G" or "5.8G" for basic_id. All of 5 GHz keeps "5.8G": the existing strings and fixtures. */
const char* fpv_band_prefix(int freq_mhz);
/* Nearest public Wi-Fi centre of the target's band the closed PHY can be
 * parked on first. Returns 0 if freq is outside the C5's tuning windows. */
int fpv_wifi_bootstrap(int freq_mhz, uint8_t* wifi_channel, uint16_t* centre_mhz);
/* The rank-th nearest centre of the target's band (0 = nearest); 0 when rank
 * is out of range or freq outside the window. rf_tune walks the ranks when a
 * regulatory table refuses the nearest one. */
int fpv_wifi_bootstrap_rank(int freq_mhz, int rank, uint8_t* wifi_channel, uint16_t* centre_mhz);
/* Highest public 5 GHz centre: a tuned frequency above it relies on phy_set_freq
 * pulling the synthesizer past the last Wi-Fi channel. */
int fpv_wifi_top_centre_mhz(void);

#ifdef __cplusplus
}
#endif
