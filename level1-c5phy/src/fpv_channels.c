#include "fpv_channels.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* Build variants, defaults as in config.h (the host build does not include it). */
#ifndef DUAL_BAND
#define DUAL_BAND 0
#endif
#ifndef SCAN_5G1
#define SCAN_5G1 1
#endif
#ifndef LOWBAND
#define LOWBAND 1
#endif
#ifndef GAP_CHANNELS
#define GAP_CHANNELS 1
#endif
/* Top of the 5 GHz window. C5VRX proved tuning up to the last public centre
 * (5885); R8 5917 and E6/E7/E8 5905-5945 need phy_set_freq to pull the
 * synthesizer 20-60 MHz past it, which bench stage 2 (h E8) proves or
 * disproves. Until then run_sweep's alias guard drops a hit above 5885 that
 * merely mirrors a carrier at the last centre; -DC5PHY_MAX_MHZ=5885 removes
 * those channels from the plan altogether. */
#ifndef C5PHY_MAX_MHZ
#define C5PHY_MAX_MHZ 5945
#endif

/* The tuning windows: lowest public centre minus / highest plus the 60 MHz
 * phy_set_freq pull (C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ). */
#define C5_5G_MIN_MHZ  5120
#define C5_24G_MIN_MHZ 2352
#define C5_24G_MAX_MHZ 2532

static const FpvChannel k_channels_all[] = {
    /* RaceBand */
    {'R',1,5658},{'R',2,5695},{'R',3,5732},{'R',4,5769},{'R',5,5806},{'R',6,5843},{'R',7,5880},{'R',8,5917},
    /* Boscam A */
    {'A',1,5865},{'A',2,5845},{'A',3,5825},{'A',4,5805},{'A',5,5785},{'A',6,5765},{'A',7,5745},{'A',8,5725},
    /* Boscam B */
    {'B',1,5733},{'B',2,5752},{'B',3,5771},{'B',4,5790},{'B',5,5809},{'B',6,5828},{'B',7,5847},{'B',8,5866},
    /* Boscam E */
    {'E',1,5705},{'E',2,5685},{'E',3,5665},{'E',4,5645},{'E',5,5885},{'E',6,5905},{'E',7,5925},{'E',8,5945},
    /* FatShark / Airwave */
    {'F',1,5740},{'F',2,5760},{'F',3,5780},{'F',4,5800},{'F',5,5820},{'F',6,5840},{'F',7,5860},{'F',8,5880},
#if GAP_CHANNELS
    /* The two 20 MHz holes of the analog table (E3 5665 / E2 5685, E1 5705 / A8
     * 5725): a carrier there is a table channel with a key of its own rather
     * than a pull-in keyed to a neighbour */
    {'X',1,5675},{'X',2,5715},
#endif
#if SCAN_5G1
    /* Three 40 MHz views over DJI O4's CE band 5170-5250 */
    {'D',1,5190},{'D',2,5210},{'D',3,5230},
#endif
#if LOWBAND >= 2
    /* L1-L3 sit 64-138 MHz under Wi-Fi 100: rf_tune refuses them unless C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ is raised to 140 */
    {'L',1,5362},{'L',2,5399},{'L',3,5436},
#endif
#if LOWBAND
    /* Lowband, reachable from Wi-Fi 100-124 */
    {'L',4,5473},{'L',5,5510},{'L',6,5547},{'L',7,5584},{'L',8,5621},
#endif
#if DUAL_BAND
    /* 2.4 GHz digital links (OcuSync 2, Wi-Fi links): five 20 MHz steps across the ISM band */
    {'G',1,2402},{'G',2,2422},{'G',3,2442},{'G',4,2462},{'G',5,2482},
#endif
};

/* The scan plan: every table channel inside its band's tuning window, in table order. */
static FpvChannel k_channels[sizeof(k_channels_all) / sizeof(k_channels_all[0])];
static int k_channel_count = -1;

int fpv_freq_band_ghz(int freq_mhz) { return freq_mhz < 3000 ? 2 : 5; }

const char* fpv_band_prefix(int freq_mhz) { return fpv_freq_band_ghz(freq_mhz) == 2 ? "2.4G" : "5.8G"; }

static int in_window(int freq_mhz)
{
    if (fpv_freq_band_ghz(freq_mhz) == 2) return freq_mhz >= C5_24G_MIN_MHZ && freq_mhz <= C5_24G_MAX_MHZ;
    return freq_mhz >= C5_5G_MIN_MHZ && freq_mhz <= C5PHY_MAX_MHZ;
}

static void build_plan(void)
{
    if (k_channel_count >= 0) return;
    int n = 0;
    for (unsigned i = 0; i < sizeof(k_channels_all) / sizeof(k_channels_all[0]); i++)
        if (in_window(k_channels_all[i].freq_mhz)) k_channels[n++] = k_channels_all[i];
    k_channel_count = n;
}

int fpv_channel_count(void) { build_plan(); return k_channel_count; }

const FpvChannel* fpv_channel(int index)
{
    build_plan();
    if (index < 0 || index >= k_channel_count) return NULL;
    return &k_channels[index];
}

int fpv_channel_band_ghz(int index)
{
    const FpvChannel* c = fpv_channel(index);
    return c ? fpv_freq_band_ghz(c->freq_mhz) : 0;
}

int fpv_find(const char* name)
{
    if (!name || !*name) return -1;
    if (isdigit((unsigned char)name[0])) {
        int mhz = atoi(name);
        for (int i = 0; i < fpv_channel_count(); i++)
            if (k_channels[i].freq_mhz == mhz) return i;
        return -1;
    }
    char b = (char)toupper((unsigned char)name[0]);
    int n = atoi(name + 1);
    for (int i = 0; i < fpv_channel_count(); i++)
        if (k_channels[i].band == b && k_channels[i].number == n) return i;
    return -1;
}

int fpv_nearest(int freq_mhz)
{
    int best = -1, best_d = 1 << 30;
    for (int i = 0; i < fpv_channel_count(); i++) {
        int d = abs((int)k_channels[i].freq_mhz - freq_mhz);
        if (d < best_d) { best_d = d; best = i; }
    }
    return best;
}

/* Public ESP-IDF centres. The closed PHY is placed on the nearest one of the
 * target's band with esp_wifi_set_channel, then phy_set_freq moves it to the
 * exact MHz. 5 GHz: UNII-1 (36-48, under DJI O4's CE band), UNII-2C (100-128,
 * under Lowband), UNII-2C/3 and the 5.9 GHz extension. Band A channels
 * A1/A2/A3/A4/A5/A6/A7 sit exactly on 173/169/165/161/157/153/149 and need
 * no undocumented call. 2.4 GHz: channels 1-13 (DUAL_BAND). */
typedef struct { uint8_t ch; uint16_t mhz; } WifiCentre;
static const WifiCentre k_centres_5g[] = {
    {36,5180},{40,5200},{44,5220},{48,5240},
    {100,5500},{104,5520},{108,5540},{112,5560},{116,5580},{120,5600},{124,5620},{128,5640},
    {132,5660},{136,5680},{140,5700},{144,5720},{149,5745},{153,5765},
    {157,5785},{161,5805},{165,5825},{169,5845},{173,5865},{177,5885},
};
static const WifiCentre k_centres_24g[] = {
    {1,2412},{2,2417},{3,2422},{4,2427},{5,2432},{6,2437},{7,2442},
    {8,2447},{9,2452},{10,2457},{11,2462},{12,2467},{13,2472},
};
#define N_CENTRES_5G  ((int)(sizeof(k_centres_5g) / sizeof(k_centres_5g[0])))
#define N_CENTRES_24G ((int)(sizeof(k_centres_24g) / sizeof(k_centres_24g[0])))

/* The alias guard is a 5 GHz thing: the last 5 GHz centre. */
int fpv_wifi_top_centre_mhz(void) { return k_centres_5g[N_CENTRES_5G - 1].mhz; }

int fpv_wifi_bootstrap_rank(int freq_mhz, int rank, uint8_t* wifi_channel, uint16_t* centre_mhz)
{
    if (!in_window(freq_mhz)) return 0;
    /* only the target's band is ranked: a 2.4 GHz tune never parks on a 5 GHz centre */
    const WifiCentre* c = fpv_freq_band_ghz(freq_mhz) == 2 ? k_centres_24g : k_centres_5g;
    const int nc = fpv_freq_band_ghz(freq_mhz) == 2 ? N_CENTRES_24G : N_CENTRES_5G;
    if (rank < 0 || rank >= nc) return 0;
    /* rank-th smallest distance (ties broken by table order) */
    int order[N_CENTRES_5G > N_CENTRES_24G ? N_CENTRES_5G : N_CENTRES_24G];
    for (int i = 0; i < nc; i++) order[i] = i;
    for (int i = 1; i < nc; i++) {
        int k = order[i], j = i - 1;
        while (j >= 0 && abs((int)c[order[j]].mhz - freq_mhz) > abs((int)c[k].mhz - freq_mhz)) {
            order[j + 1] = order[j];
            j--;
        }
        order[j + 1] = k;
    }
    if (wifi_channel) *wifi_channel = c[order[rank]].ch;
    if (centre_mhz) *centre_mhz = c[order[rank]].mhz;
    return 1;
}

int fpv_wifi_bootstrap(int freq_mhz, uint8_t* wifi_channel, uint16_t* centre_mhz)
{
    return fpv_wifi_bootstrap_rank(freq_mhz, 0, wifi_channel, centre_mhz);
}
