#include "switch_bits.h"
#include <ctype.h>
#include <string.h>

int switch_parse_bits(const char* arg, int pins, uint32_t* bits)
{
    if (!arg || pins < 1 || pins > 31) return -1;
    size_t len = strlen(arg);
    if (len == 0) return -1;

    if (len == (size_t)pins && strspn(arg, "01") == len) {
        uint32_t b = 0;
        for (int i = 0; i < pins; i++)
            if (arg[i] == '1') b |= 1u << i;
        *bits = b;
        return 0;
    }

    const char* p = arg;
    unsigned base = 10;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { base = 16; p += 2; }
    else if (p[0] == '0' && p[1] != '\0') return -1;           /* leading zero: octal in strtoul, refused */
    if (!*p) return -1;
    uint32_t v = 0;
    const uint32_t max = (1u << pins) - 1u;
    for (; *p; p++) {
        int d;
        if (isdigit((unsigned char)*p)) d = *p - '0';
        else if (base == 16 && isxdigit((unsigned char)*p)) d = tolower((unsigned char)*p) - 'a' + 10;
        else return -1;
        if ((uint32_t)d > max || v > (max - (uint32_t)d) / base) return -1;   /* past 2^pins - 1 */
        v = v * base + (uint32_t)d;
    }
    *bits = v;
    return 0;
}

void switch_format_bits(char* out, size_t cap, uint32_t bits, int pins)
{
    if (!out || cap == 0) return;
    size_t n = 0;
    for (int i = 0; i < pins && n + 1 < cap; i++) out[n++] = (bits >> i) & 1u ? '1' : '0';
    out[n] = 0;
}
