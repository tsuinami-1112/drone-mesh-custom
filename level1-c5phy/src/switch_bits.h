/* RF switch control-line patterns for the bench console. Plain C, shared with
 * the host tests. Bit i drives SWITCH_PINS[i]: with the default pins bit 0 is
 * D8 (V1), bit 1 is D9 (V2) and bit 2 is D7 (V3). */
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Parse the argument of the bench `t` command. Returns 0 and sets *bits, or -1.
 *   exactly `pins` characters of 0/1: the lines in SWITCH_PINS order, first
 *     character = bit 0. This is the V1V2V3 notation of config.h and the bench
 *     guide: "100" = V1 high = bits 0x1, "110" = V1 and V2 high = 0x3.
 *   anything else: a number, decimal or 0x hex, 0 .. 2^pins - 1.
 * A number out of range, a sign, octal or trailing characters are refused, so
 * nothing is silently truncated to the low bits. */
int switch_parse_bits(const char* arg, int pins, uint32_t* bits);

/* bits -> "100" (pins characters, first = bit 0) */
void switch_format_bits(char* out, size_t cap, uint32_t bits, int pins);

#ifdef __cplusplus
}
#endif
