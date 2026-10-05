/* SP4T (or SPDT tree) antenna switch on the configured control lines. */
#pragma once
#include <stdint.h>

void switch_init(void);
void switch_select(int sector);        /* 0..SECTOR_COUNT-1, waits SWITCH_SETTLE_US */
void switch_set_raw(uint32_t bits);    /* bench: drive the control lines directly; the next
                                          switch_select() overrides it */
int  switch_current(void);             /* selected sector, -1 after switch_set_raw() */
uint32_t switch_bits(void);            /* the bits on the control lines now (bit i = SWITCH_PINS[i]) */
uint32_t switch_sector_bits(int sector);   /* SECTOR_SWITCH_TABLE entry, masked to the pins */
const char* switch_sector_name(int sector);
