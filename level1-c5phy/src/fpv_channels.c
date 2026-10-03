#include "fpv_channels.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#ifndef LOWBAND
#define LOWBAND 0
#endif

static const FpvChannel k_channels[] = {
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
#if LOWBAND
    {'L',1,5362},{'L',2,5399},{'L',3,5436},{'L',4,5473},{'L',5,5510},{'L',6,5547},{'L',7,5584},{'L',8,5621},
#endif
};

int fpv_channel_count(void) { return (int)(sizeof(k_channels) / sizeof(k_channels[0])); }

const FpvChannel* fpv_channel(int index)
{
    if (index < 0 || index >= fpv_channel_count()) return NULL;
    return &k_channels[index];
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

/* Public ESP-IDF 5 GHz centres (UNII-2C/3 and the 5.9 GHz extension). The
 * closed PHY is placed on the nearest one with esp_wifi_set_channel, then
 * phy_set_freq moves it to the exact FPV MHz. Band A channels A1/A2/A3/A4/A5/A6/A7
 * sit exactly on 173/169/165/161/157/153/149 and need no undocumented call. */
typedef struct { uint8_t ch; uint16_t mhz; } Wifi5Centre;
static const Wifi5Centre k_centres[] = {
    {132,5660},{136,5680},{140,5700},{144,5720},{149,5745},{153,5765},
    {157,5785},{161,5805},{165,5825},{169,5845},{173,5865},{177,5885},
};
#define C5_5G_MIN_MHZ 5180
#define C5_5G_MAX_MHZ 5945   /* E8; the bench proves how far above 5885 the synthesizer follows */

int fpv_wifi_bootstrap(int freq_mhz, uint8_t* wifi_channel, uint16_t* centre_mhz)
{
    if (freq_mhz < C5_5G_MIN_MHZ || freq_mhz > C5_5G_MAX_MHZ) return 0;
    int best = 0, best_d = 1 << 30;
    for (unsigned i = 0; i < sizeof(k_centres) / sizeof(k_centres[0]); i++) {
        int d = abs((int)k_centres[i].mhz - freq_mhz);
        if (d < best_d) { best_d = d; best = (int)i; }
    }
    if (wifi_channel) *wifi_channel = k_centres[best].ch;
    if (centre_mhz) *centre_mhz = k_centres[best].mhz;
    return 1;
}
