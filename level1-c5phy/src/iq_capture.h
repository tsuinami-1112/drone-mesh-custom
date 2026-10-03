/* One-shot 16 KiB I/Q windows from the modem's diagnostic bus through PARLIO RX. */
#pragma once
#include <stdint.h>
#include "esp_err.h"

esp_err_t      iq_capture_init(void);
/* Capture IQ_WINDOW_BYTES into the internal DMA buffer. On success *out points
 * at the samples (valid until the next capture). */
esp_err_t      iq_capture_window(uint8_t** out, uint32_t timeout_ms);
uint32_t       iq_capture_count(void);
uint32_t       iq_capture_errors(void);
const char*    iq_capture_last_error(void);
