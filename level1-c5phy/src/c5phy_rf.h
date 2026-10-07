/* The ESP32-C5 Wi-Fi PHY as a receive-only 5.8 GHz (and, with DUAL_BAND, 2.4 GHz)
 * I/Q front end. */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

/* Bring the Wi-Fi driver up in station mode, 5 GHz only (auto band under
 * DUAL_BAND), no power save, BW40, promiscuous with an empty filter, the five
 * MAC transmit queues hardware-disabled, packet AGC off, gain forced, the
 * diagnostic I/Q bus routed to the lane pads and the modem front end un-gated
 * so it samples continuously. On failure rf_last_call() names the call that failed. */
esp_err_t   rf_start(void);
/* Park the closed PHY on the nearest public centre of the target's band, then
 * move the synthesizer to the exact FPV MHz; re-arm the diagnostic stream and
 * re-assert AGC-off / bandwidth / gain. ESP_ERR_NOT_SUPPORTED when the
 * frequency needs phy_set_freq and this core does not export it, or lies
 * outside the tuning windows. */
esp_err_t   rf_tune(uint16_t freq_mhz);
uint8_t     rf_band_ghz(void);                 /* 2 or 5: the band the synthesizer is on (5, the parked band, before rf_start) */
void        rf_set_gain(uint8_t gain_idx);     /* PHY RX gain index, 2..62 */
uint8_t     rf_gain(void);
void        rf_set_bw40(bool bw40);
bool        rf_bw40(void);
const char* rf_last_call(void);
uint8_t     rf_wifi_channel(void);             /* bootstrap centre in use */
uint16_t    rf_freq_mhz(void);                 /* frequency the synthesizer was asked for */
bool        rf_has_phy_set_freq(void);
bool        rf_started(void);
