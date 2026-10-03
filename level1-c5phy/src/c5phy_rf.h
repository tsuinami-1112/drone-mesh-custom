/* The ESP32-C5 Wi-Fi PHY as a receive-only 5.8 GHz analog FM front end. */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

/* Bring the Wi-Fi driver up in station mode, 5 GHz only, no power save, BW40,
 * promiscuous with an empty filter, the five MAC transmit queues hardware-
 * disabled, packet AGC off, gain forced, the diagnostic I/Q bus routed to the
 * lane pads and the modem front end un-gated so it samples continuously.
 * On failure rf_last_call() names the call that failed. */
esp_err_t   rf_start(void);
/* Park the closed PHY on the nearest public 5 GHz centre, then move the
 * synthesizer to the exact FPV MHz; re-arm the diagnostic stream and
 * re-assert AGC-off / bandwidth / gain. ESP_ERR_NOT_SUPPORTED when the
 * frequency needs phy_set_freq and this core does not export it. */
esp_err_t   rf_tune(uint16_t freq_mhz);
void        rf_set_gain(uint8_t gain_idx);     /* PHY RX gain index, 2..62 */
uint8_t     rf_gain(void);
void        rf_set_bw40(bool bw40);
bool        rf_bw40(void);
const char* rf_last_call(void);
uint8_t     rf_wifi_channel(void);             /* bootstrap centre in use */
uint16_t    rf_freq_mhz(void);                 /* frequency the synthesizer was asked for */
bool        rf_has_phy_set_freq(void);
bool        rf_started(void);
