#include "sector_switch.h"
#include "config.h"
#include <Arduino.h>

static const int      k_pins[SWITCH_PIN_COUNT] = SWITCH_PINS;
static const uint32_t k_table[SECTOR_COUNT]    = SECTOR_SWITCH_TABLE;
static const char*    k_names[SECTOR_COUNT]    = SECTOR_NAMES;
static int s_current = -1;
static uint32_t s_bits = 0;              /* what the control lines are driving now */

void switch_init(void)
{
    for (int i = 0; i < SWITCH_PIN_COUNT; i++) {
        pinMode(k_pins[i], OUTPUT);
        digitalWrite(k_pins[i], LOW);
    }
    switch_select(0);
}

void switch_set_raw(uint32_t bits)
{
    for (int i = 0; i < SWITCH_PIN_COUNT; i++)
        digitalWrite(k_pins[i], (bits >> i) & 1u ? HIGH : LOW);
    s_bits = bits & ((1u << SWITCH_PIN_COUNT) - 1u);
    s_current = -1;
    delayMicroseconds(SWITCH_SETTLE_US);
}

void switch_select(int sector)
{
    if (sector < 0 || sector >= SECTOR_COUNT) return;
    if (sector == s_current) return;
    for (int i = 0; i < SWITCH_PIN_COUNT; i++)
        digitalWrite(k_pins[i], (k_table[sector] >> i) & 1u ? HIGH : LOW);
    s_bits = k_table[sector] & ((1u << SWITCH_PIN_COUNT) - 1u);
    s_current = sector;
    delayMicroseconds(SWITCH_SETTLE_US);
}

int switch_current(void) { return s_current; }

uint32_t switch_bits(void) { return s_bits; }

uint32_t switch_sector_bits(int sector)
{
    return (sector >= 0 && sector < SECTOR_COUNT) ? k_table[sector] & ((1u << SWITCH_PIN_COUNT) - 1u) : 0;
}

const char* switch_sector_name(int sector)
{
    return (sector >= 0 && sector < SECTOR_COUNT) ? k_names[sector] : "?";
}
