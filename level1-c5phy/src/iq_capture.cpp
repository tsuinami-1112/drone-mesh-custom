/*
 * PARLIO RX reads the MODEM_DIAG lanes at 40 MS/s into one 16 KiB DMA window
 * (409.6 us, 6.4 video lines): one byte per sample, I in the high nibble, Q in
 * the low nibble. In the default IQ_LANE_BITS 3 build only six lanes are wired
 * (bits 9..7 of each): byte bits 0 and 4 belong to unassigned PARLIO lines and
 * demod.c masks them off. Unlike C5VRX this station does not need a
 * gapless stream, so each window is an ordinary one-shot transaction on the
 * stock driver and the CPU looks at it when it is done.
 *
 * Order matters: the PARLIO unit claims the lane GPIOs as inputs when it is
 * created, and c5phy_rf's lane routing then turns them into INPUT_OUTPUT pads
 * driven by the MODEM_DIAG signal. Create the unit first (main.cpp does).
 * A lane set to -1 in IQ_LANE_GPIOS is left unconnected by the driver (it
 * skips negative GPIO numbers) and its bit reads as a constant that demod.c
 * masks off.
 */
#include "iq_capture.h"
#include "config.h"
#include <string.h>
#include "driver/parlio_rx.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static parlio_rx_unit_handle_t      s_rx = nullptr;
static parlio_rx_delimiter_handle_t s_delim = nullptr;
static uint8_t*    s_buf = nullptr;
static uint32_t    s_count = 0, s_errors = 0;
static const char* s_last_err = "";

esp_err_t iq_capture_init(void)
{
    static const int lanes[IQ_LANE_COUNT] = IQ_LANE_GPIOS;

    s_buf = (uint8_t*)heap_caps_aligned_calloc(64, 1, IQ_WINDOW_BYTES, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!s_buf) { s_last_err = "heap_caps_aligned_calloc"; return ESP_ERR_NO_MEM; }

    parlio_rx_unit_config_t cfg = {};
    cfg.trans_queue_depth = 1;
    cfg.max_recv_size     = IQ_WINDOW_BYTES;
    cfg.dma_burst_size    = 32;
    cfg.data_width        = IQ_LANE_COUNT;
    cfg.clk_src           = PARLIO_CLK_SRC_DEFAULT;      /* internal PLL, 40 MHz */
    cfg.ext_clk_freq_hz   = 0;
    cfg.exp_clk_freq_hz   = IQ_SAMPLE_RATE_HZ;
    cfg.clk_in_gpio_num   = GPIO_NUM_NC;
    cfg.clk_out_gpio_num  = GPIO_NUM_NC;
    cfg.valid_gpio_num    = GPIO_NUM_NC;
    for (int i = 0; i < PARLIO_RX_UNIT_MAX_DATA_WIDTH; i++)
        cfg.data_gpio_nums[i] = (i < IQ_LANE_COUNT && lanes[i] >= 0) ? (gpio_num_t)lanes[i] : GPIO_NUM_NC;
    cfg.flags.free_clk    = 1;                           /* sample continuously, nothing gates the clock */
    cfg.flags.clk_gate_en = 0;

    esp_err_t err = parlio_new_rx_unit(&cfg, &s_rx);
    if (err != ESP_OK) { s_last_err = "parlio_new_rx_unit"; return err; }

    parlio_rx_soft_delimiter_config_t d = {};
    d.sample_edge    = PARLIO_SAMPLE_EDGE_POS;           /* proven on hardware by C5VRX */
    d.bit_pack_order = PARLIO_BIT_PACK_ORDER_LSB;        /* byte bit i = data_gpio_nums[i]: Q6..Q9, I6..I9 */
    d.eof_data_len   = IQ_WINDOW_BYTES;
    d.timeout_ticks  = 0;
    err = parlio_new_rx_soft_delimiter(&d, &s_delim);
    if (err != ESP_OK) { s_last_err = "parlio_new_rx_soft_delimiter"; return err; }

    err = parlio_rx_unit_enable(s_rx, true);
    if (err != ESP_OK) { s_last_err = "parlio_rx_unit_enable"; return err; }
    return ESP_OK;
}

esp_err_t iq_capture_window(uint8_t** out, uint32_t timeout_ms)
{
    if (!s_rx || !s_buf) return ESP_ERR_INVALID_STATE;
    parlio_receive_config_t rc = {};
    rc.delimiter = s_delim;
    rc.flags.partial_rx_en = 0;
    rc.flags.indirect_mount = 0;

    esp_err_t err = parlio_rx_soft_delimiter_start_stop(s_rx, s_delim, true);
    const char* where = "parlio_rx_soft_delimiter_start_stop";
    if (err == ESP_OK) {
        err = parlio_rx_unit_receive(s_rx, s_buf, IQ_WINDOW_BYTES, &rc);
        where = "parlio_rx_unit_receive";
    }
    if (err == ESP_OK) {
        err = parlio_rx_unit_wait_all_done(s_rx, (int)timeout_ms);
        where = "parlio_rx_unit_wait_all_done";
    }
    parlio_rx_soft_delimiter_start_stop(s_rx, s_delim, false);

    if (err != ESP_OK) {
        s_errors++;
        s_last_err = where;
        /* A timed-out transaction is still queued: reset the unit's queue. */
        parlio_rx_unit_disable(s_rx);
        parlio_rx_unit_enable(s_rx, true);
        return err;
    }
    /* The window lives in internal SRAM, which the C5 does not cache, and the
     * driver synchronises any cached payload itself; no explicit msync here. */
    s_count++;
    if (out) *out = s_buf;
    return ESP_OK;
}

uint32_t    iq_capture_count(void)      { return s_count; }
uint32_t    iq_capture_errors(void)     { return s_errors; }
const char* iq_capture_last_error(void) { return s_last_err; }
