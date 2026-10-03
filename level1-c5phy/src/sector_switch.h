/* SP4T (or SPDT tree) antenna switch on the configured control lines. */
#pragma once
#include <stdint.h>

void switch_init(void);
void switch_select(int sector);        /* 0..SECTOR_COUNT-1, waits SWITCH_SETTLE_US */
void switch_set_raw(uint32_t bits);    /* bench: drive the control lines directly */
int  switch_current(void);
const char* switch_sector_name(int sector);
