/*
 * c5phy_rf.cpp - the C5's Wi-Fi PHY held receive-only as the analog FM front end.
 *
 * Re-implements, on the Arduino core 3.3 / ESP-IDF 5.5 toolchain the fleet
 * builds with, the receiver bring-up that the C5VRX project proved on hardware
 * with ESP-IDF 6.0 (github.com/KonradIT/C5VRX, main/rf.c). The register
 * addresses are the C5's MAC and modem blocks and do not move between IDF
 * versions; the PHY entry points are undocumented symbols of the closed
 * libphy. They are declared weak so the firmware always links: a core that
 * does not export one of them boots with "rf":false and an error line naming
 * the missing call, instead of a link error nobody in the field can read.
 * Build with -DC5PHY_STRONG_PHY_SYMBOLS=1 to turn that into a link error.
 */
#include "c5phy_rf.h"
#include "config.h"
#include "fpv_channels.h"

#include <string.h>
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_rom_gpio.h"
#include "driver/gpio.h"
#include "soc/gpio_sig_map.h"

#if C5PHY_STRONG_PHY_SYMBOLS
#define PHY_SYM
#else
#define PHY_SYM __attribute__((weak))
#endif
extern "C" {
void phy_disable_agc(void) PHY_SYM;
void phy_rfagc_disable(void) PHY_SYM;
void phy_wifi_fbw_sel(uint32_t val) PHY_SYM;
void phy_force_rx_gain(bool enable, uint8_t gain_idx) PHY_SYM;
void phy_set_freq(uint16_t freq_mhz, int offset) PHY_SYM;
void phy_chip_set_chan_offset(int offset_khz) PHY_SYM;
void phy_track_pll_deinit(void) PHY_SYM;
int  lmac_stop_hw_txq(void) PHY_SYM;
}

/* ---- C5 MAC / modem registers (C5VRX, proven on hardware) ------------------- */
#define REG32(a)         (*(volatile uint32_t*)(uintptr_t)(a))
#define MAC_TXQ0_CONF    0x600a4d6cu
#define MAC_TXQ_STRIDE   0x10u
#define MAC_TXQ_ENABLE   0x80000000u
#define MAC_TXQ_COUNT    5u
#define DUMP_CTRL        0x600a9004u
#define DUMP_PTR_MODE    0x600a9008u
#define DUMP_FORMAT      0x600a9018u
#define FE_PATH          0x600a20b4u
#define FE_ENABLE        0x600a0800u
#define SOURCE_CTRL      0x600a08ccu
#define SOURCE_MUX       0x600a70b8u
#define MODEM_CLOCK      0x600a9c04u
#define CTRL_ENABLE      0x80000000u
#define CTRL_DUMP_FIRST  0x00020000u
#define TX_START_SELECT  0x00060000u
#define SELECTOR_MASK    0x01fe0000u
#define HP_SRAM_USAGE    0x60095004u

static const int     k_lanes[IQ_LANE_COUNT] = IQ_LANE_GPIOS;
static const uint8_t k_diag[IQ_LANE_COUNT]  = IQ_LANE_DIAG;

static const char* s_last_call = "";
static bool        s_started = false;
static bool        s_bw40 = BW40 != 0;
static uint8_t     s_gain = GAIN_MAX;
static uint8_t     s_wifi_ch = 0;
static uint16_t    s_freq_mhz = 0;

#define TRY(call) do { esp_err_t _e = (call); if (_e != ESP_OK) { s_last_call = #call; return _e; } } while (0)

static inline void fence(void) { __asm__ __volatile__("fence iorw, iorw" ::: "memory"); }

/* Hardware-disable the five LMAC transmit queues: the radio can no longer transmit. */
static esp_err_t lock_rx_only(void)
{
    if (lmac_stop_hw_txq) (void)lmac_stop_hw_txq();
    for (unsigned q = 0; q < MAC_TXQ_COUNT; ++q)
        REG32(MAC_TXQ0_CONF - q * MAC_TXQ_STRIDE) &= ~MAC_TXQ_ENABLE;
    fence();
    for (unsigned q = 0; q < MAC_TXQ_COUNT; ++q)
        if (REG32(MAC_TXQ0_CONF - q * MAC_TXQ_STRIDE) & MAC_TXQ_ENABLE) { s_last_call = "lock_rx_only"; return ESP_ERR_INVALID_STATE; }
    return ESP_OK;
}

/* Drive MODEM_DIAG bits 6..9 (Q) and 16..19 (I) out through the lane pads,
 * where PARLIO RX reads them back. Pads must be INPUT_OUTPUT with nothing
 * connected; gpio_config() comes first because it reconnects the pad to the
 * plain GPIO output signal, which the diag signal then replaces. */
static esp_err_t route_modem_iq(void)
{
    uint64_t mask = 0;
    for (int i = 0; i < IQ_LANE_COUNT; i++) mask |= 1ULL << k_lanes[i];
    gpio_config_t cfg = {};
    cfg.pin_bit_mask = mask;
    cfg.mode = GPIO_MODE_INPUT_OUTPUT;
    cfg.pull_up_en = GPIO_PULLUP_DISABLE;
    cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    cfg.intr_type = GPIO_INTR_DISABLE;
    TRY(gpio_config(&cfg));
    for (int i = 0; i < IQ_LANE_COUNT; i++)
        esp_rom_gpio_connect_out_signal((gpio_num_t)k_lanes[i], MODEM_DIAG0_IDX + k_diag[i], false, false);
    fence();
    return ESP_OK;
}

/* Un-gate the modem clocks and arm the dump engine in pre-trigger circular
 * mode so the front end streams I/Q onto MODEM_DIAG continuously, Wi-Fi
 * packets or not (C5VRX "golden" configuration). */
static void enable_continuous_modem(void)
{
    REG32(HP_SRAM_USAGE) = (REG32(HP_SRAM_USAGE) & 0xfffef0ffu) | 0x00010000u;
    REG32(SOURCE_CTRL) &= 0xff87ffffu;
    REG32(SOURCE_MUX) = (REG32(SOURCE_MUX) & 0xfffffff8u) | 1u;
    REG32(MODEM_CLOCK) = UINT32_MAX;
    REG32(FE_ENABLE) |= 4u;
    REG32(FE_PATH) &= ~1u;

    uint32_t v = REG32(DUMP_FORMAT);
    v = (v & 0xff03ffffu) | 0x006c0000u;
    REG32(DUMP_FORMAT) = v;
    v = (REG32(DUMP_FORMAT) & 0xfffc0fffu) | 0x0001a000u;
    REG32(DUMP_FORMAT) = v;
    v = (REG32(DUMP_FORMAT) & 0xfffff03fu) | 0x00000640u;
    REG32(DUMP_FORMAT) = v;
    v = (REG32(DUMP_FORMAT) & 0xffffffc0u) | 0x18u;
    REG32(DUMP_FORMAT) = v | 0x01000000u;

    REG32(DUMP_PTR_MODE) = (REG32(DUMP_PTR_MODE) & ~SELECTOR_MASK) | TX_START_SELECT;

    uint32_t ctrl = REG32(DUMP_CTRL);
    ctrl &= ~(CTRL_ENABLE | 0x00080000u | 0x00040000u);
    ctrl |= CTRL_DUMP_FIRST;
    ctrl = (ctrl & ~0x0001ffffu) | 16384u;
    REG32(DUMP_CTRL) = ctrl;
    fence();
    REG32(DUMP_CTRL) = ctrl | CTRL_ENABLE;
    fence();
}

/* Re-assert the analog-FM contract: the closed PHY touches these on every retune. */
static void assert_analog_contract(void)
{
    phy_disable_agc();
    phy_rfagc_disable();
    phy_wifi_fbw_sel(s_bw40 ? 1u : 0u);
    phy_force_rx_gain(true, s_gain);
}

static esp_err_t init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        if ((err = nvs_flash_erase()) == ESP_OK) err = nvs_flash_init();
    }
    return err;
}

esp_err_t rf_start(void)
{
    s_started = false;
    /* The calls the receiver cannot work without. */
    if (!phy_disable_agc)    { s_last_call = "phy_disable_agc (not exported by libphy)"; return ESP_ERR_NOT_FOUND; }
    if (!phy_rfagc_disable)  { s_last_call = "phy_rfagc_disable (not exported by libphy)"; return ESP_ERR_NOT_FOUND; }
    if (!phy_wifi_fbw_sel)   { s_last_call = "phy_wifi_fbw_sel (not exported by libphy)"; return ESP_ERR_NOT_FOUND; }
    if (!phy_force_rx_gain)  { s_last_call = "phy_force_rx_gain (not exported by libphy)"; return ESP_ERR_NOT_FOUND; }

    TRY(init_nvs());
    esp_err_t e = esp_netif_init();
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) { s_last_call = "esp_netif_init"; return e; }
    e = esp_event_loop_create_default();
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) { s_last_call = "esp_event_loop_create_default"; return e; }

    /* sta_disconnected_pm must be off: the default disconnected-station power
     * management periodically shuts RF/PHY/BB down and the diag bus with it. */
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    cfg.sta_disconnected_pm = false;
    TRY(esp_wifi_init(&cfg));
    TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    TRY(esp_wifi_set_mode(WIFI_MODE_STA));
    TRY(esp_wifi_start());
    e = esp_wifi_set_country_code(RF_COUNTRY_CC, false);
    if (e != ESP_OK) { s_last_call = "esp_wifi_set_country_code"; return e; }

#if CONFIG_SOC_WIFI_SUPPORT_5G
    TRY(esp_wifi_set_band_mode(WIFI_BAND_MODE_5G_ONLY));
#else
    s_last_call = "no 5 GHz support in this core";
    return ESP_ERR_NOT_SUPPORTED;
#endif
    TRY(esp_wifi_set_ps(WIFI_PS_NONE));

    wifi_protocols_t protocols = {};
    protocols.ghz_2g = WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N | WIFI_PROTOCOL_11AX;
    protocols.ghz_5g = WIFI_PROTOCOL_11A | WIFI_PROTOCOL_11N;
    TRY(esp_wifi_set_protocols(WIFI_IF_STA, &protocols));

    /* BW40 on 5 GHz is a hardware requirement for the diag bus I/Q (C5VRX: no
     * BW20 fallback). The analog filter is chosen separately with phy_wifi_fbw_sel. */
    wifi_bandwidths_t bandwidths = {};
    bandwidths.ghz_2g = WIFI_BW20;
    bandwidths.ghz_5g = WIFI_BW40;
    TRY(esp_wifi_set_bandwidths(WIFI_IF_STA, &bandwidths));

    /* Park on 149 (5745 MHz, A7): allowed by every 5 GHz regulatory table,
     * unlike 173 which some tables refuse. The scan tunes from here. */
    TRY(esp_wifi_set_channel(149, WIFI_SECOND_CHAN_NONE));
    s_wifi_ch = 149;
    s_freq_mhz = 5745;

    /* Promiscuous with an empty filter keeps the RX path alive without the MAC
     * buffering packets or raising interrupts. */
    TRY(esp_wifi_set_promiscuous(true));
    wifi_promiscuous_filter_t filter = {};
    filter.filter_mask = 0;
    (void)esp_wifi_set_promiscuous_filter(&filter);

    TRY(lock_rx_only());

    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    TRY(esp_wifi_get_channel(&primary, &secondary));
    if (primary != 149) { s_last_call = "esp_wifi_get_channel (verify 149)"; return ESP_ERR_INVALID_STATE; }

    TRY(route_modem_iq());
    enable_continuous_modem();
    assert_analog_contract();
    if (phy_track_pll_deinit) phy_track_pll_deinit();   /* no PLL/RX recalibration mid-capture */

    s_started = true;
    return ESP_OK;
}

esp_err_t rf_tune(uint16_t freq_mhz)
{
    if (!s_started) { s_last_call = "rf_tune before rf_start"; return ESP_ERR_INVALID_STATE; }
    uint8_t ch = 0;
    uint16_t centre = 0;
    if (!fpv_wifi_bootstrap(freq_mhz, &ch, &centre)) { s_last_call = "outside the C5 5 GHz window"; return ESP_ERR_NOT_SUPPORTED; }
    if (freq_mhz != centre && !phy_set_freq) { s_last_call = "phy_set_freq (not exported by libphy)"; return ESP_ERR_NOT_SUPPORTED; }

    /* Supported public centre first; the regulatory table may refuse it. */
    esp_err_t e = esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
    if (e != ESP_OK) { s_last_call = "esp_wifi_set_channel (regulatory table)"; return e; }
    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    e = esp_wifi_get_channel(&primary, &secondary);
    if (e != ESP_OK || primary != ch) { s_last_call = "esp_wifi_get_channel (verify)"; return e != ESP_OK ? e : ESP_ERR_INVALID_STATE; }

    if (freq_mhz != centre) phy_set_freq(freq_mhz, 0);
    enable_continuous_modem();
    assert_analog_contract();
    s_wifi_ch = ch;
    s_freq_mhz = freq_mhz;
    return ESP_OK;
}

void rf_set_gain(uint8_t gain_idx)
{
    s_gain = gain_idx;
    if (s_started && phy_force_rx_gain) phy_force_rx_gain(true, gain_idx);
}

uint8_t rf_gain(void) { return s_gain; }

void rf_set_bw40(bool bw40)
{
    s_bw40 = bw40;
    if (s_started && phy_wifi_fbw_sel) phy_wifi_fbw_sel(bw40 ? 1u : 0u);
}

bool        rf_bw40(void)             { return s_bw40; }
const char* rf_last_call(void)        { return s_last_call; }
uint8_t     rf_wifi_channel(void)     { return s_wifi_ch; }
uint16_t    rf_freq_mhz(void)         { return s_freq_mhz; }
bool        rf_has_phy_set_freq(void) { return phy_set_freq != nullptr; }
bool        rf_started(void)          { return s_started; }
