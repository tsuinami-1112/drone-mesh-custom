#include "report.h"
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <math.h>

typedef struct {
    char*  out;
    size_t cap;
    int    len;
    int    fields;
} Json;

static void json_begin(Json* j, char* out, size_t cap)
{
    j->out = out; j->cap = cap; j->len = 0; j->fields = 0;
    if (cap > 2) { out[0] = '{'; out[1] = 0; j->len = 1; }
}

/* Append one "key":value if it still fits with room for the closing brace. */
static int json_add(Json* j, const char* fmt, ...)
{
    char tmp[160];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n <= 0 || n >= (int)sizeof(tmp)) return 0;
    int need = n + (j->fields ? 1 : 0);
    if ((size_t)(j->len + need + 2) > j->cap) return 0;    /* +'}' +NUL */
    if (j->fields) j->out[j->len++] = ',';
    memcpy(j->out + j->len, tmp, (size_t)n);
    j->len += n;
    j->out[j->len] = 0;
    j->fields++;
    return 1;
}

static int json_end(Json* j)
{
    if ((size_t)(j->len + 2) > j->cap) return 0;
    j->out[j->len++] = '}';
    j->out[j->len] = 0;
    return j->len;
}

void report_mac(char out[18], char band, int ch, int freq_mhz)
{
    snprintf(out, 18, "AF:00:%02X:%02X:%02X:%02X", (unsigned)(unsigned char)band, (unsigned)ch & 0xFF,
             ((unsigned)freq_mhz >> 8) & 0xFF, (unsigned)freq_mhz & 0xFF);
}

void report_basic_id(char* out, size_t cap, char band, int ch, int freq_mhz)
{
    snprintf(out, cap, "5.8G-%c%d-%dMHz", band, ch, freq_mhz);
}

void report_fp(char* out, size_t cap, const char* video, int sync_hz, const char* carrier, int freq_peak)
{
    if (video && strcmp(video, "none") != 0 && sync_hz > 0)
        snprintf(out, cap, "%s/%d/%d", video, sync_hz, freq_peak);
    else
        snprintf(out, cap, "%s/%d", carrier ? carrier : "fm", freq_peak);
}

int report_rssi_raw(float dbm)
{
    float v = (dbm + 110.0f) / 80.0f * 1023.0f;    /* -110 dBm -> 0, -30 dBm -> 1023 */
    if (v < 0) v = 0;
    if (v > 1023) v = 1023;
    return (int)(v + 0.5f);
}

static void sectors_text(char* buf, size_t cap, const float* s, int n)
{
    int len = 0;
    len += snprintf(buf + len, cap - len, "[");
    for (int i = 0; i < n && (size_t)len < cap; i++)
        len += snprintf(buf + len, cap - len, "%s%.1f", i ? "," : "", (double)s[i]);
    if ((size_t)len < cap) snprintf(buf + len, cap - len, "]");
}

int report_detection_json(char* out, size_t cap, const DetectionReport* r, int full)
{
    char mac[18], basic[32], fp[32], sectors[64];
    report_mac(mac, r->band, r->ch, r->freq_mhz);
    report_basic_id(basic, sizeof(basic), r->band, r->ch, r->freq_mhz);
    report_fp(fp, sizeof(fp), r->video, r->sync_hz, r->carrier, r->freq_peak);
    int rssi = (int)lrintf(r->rssi_dbm);
    int has_video = r->video && strcmp(r->video, "none") != 0;

    Json j;
    json_begin(&j, out, cap);
    if (full) {
        sectors_text(sectors, sizeof(sectors), r->sectors_dbm, r->sector_count);
        json_add(&j, "\"type\":\"analog_fm\"");
        json_add(&j, "\"receiver\":\"%s\"", r->receiver);
        json_add(&j, "\"hw\":\"%s\"", r->hw);
        json_add(&j, "\"mac\":\"%s\"", mac);
        json_add(&j, "\"freq_mhz\":%d", r->freq_mhz);
        json_add(&j, "\"band\":\"%c\"", r->band);
        json_add(&j, "\"ch\":%d", r->ch);
        json_add(&j, "\"rssi\":%d", rssi);
        json_add(&j, "\"rssi_dbm\":%.1f", (double)r->rssi_dbm);
        json_add(&j, "\"rssi_raw\":%d", report_rssi_raw(r->rssi_dbm));
        json_add(&j, "\"rssi_min\":%d", (int)lrintf(r->rssi_min_dbm));
        json_add(&j, "\"rssi_max\":%d", (int)lrintf(r->rssi_max_dbm));
        json_add(&j, "\"rssi_n\":%d", r->rssi_n);
        json_add(&j, "\"level_db\":%.1f", (double)r->level_db);
        json_add(&j, "\"gain\":%d", r->gain);
        json_add(&j, "\"q_phase\":%d", r->q_phase);
        json_add(&j, "\"cfo_khz\":%d", r->cfo_khz);
        json_add(&j, "\"carrier\":\"%s\"", r->carrier);
        json_add(&j, "\"sectors\":%s", sectors);
        json_add(&j, "\"sector\":%d", r->sector);
        json_add(&j, "\"bearing_deg\":%d", r->bearing_deg);
        json_add(&j, "\"bearing_sigma_deg\":%d", r->bearing_sigma_deg);
        json_add(&j, "\"heading\":%d", r->heading);
        json_add(&j, "\"freq_peak\":%d", r->freq_peak);
        json_add(&j, "\"video\":\"%s\"", r->video);
        if (has_video) {
            json_add(&j, "\"sync_hz\":%d", r->sync_hz);
            json_add(&j, "\"field_hz\":%d", r->field_hz);
        }
        if (r->video_windows > 0) {
            json_add(&j, "\"sync_q\":%d", r->sync_q);
            json_add(&j, "\"sync_score\":%d", r->sync_score);
            json_add(&j, "\"video_windows\":%d", r->video_windows);
        }
        json_add(&j, "\"fp\":\"%s\"", fp);
        json_add(&j, "\"basic_id\":\"%s\"", basic);
        json_add(&j, "\"node_id\":\"%s\"", r->node_id);
        json_add(&j, "\"seq\":%u", r->seq);
        return json_end(&j);
    }
    /* Mesh: the mapper derives basic_id and the mac from band/ch/freq when
     * they are missing, so identity and bearing come first. */
    if (!json_add(&j, "\"type\":\"analog_fm\"")) return 0;
    if (!json_add(&j, "\"mac\":\"%s\"", mac)) return 0;
    if (!json_add(&j, "\"node_id\":\"%s\"", r->node_id)) return 0;
    if (!json_add(&j, "\"freq_mhz\":%d", r->freq_mhz)) return 0;
    json_add(&j, "\"band\":\"%c\"", r->band);
    json_add(&j, "\"ch\":%d", r->ch);
    json_add(&j, "\"rssi\":%d", rssi);
    json_add(&j, "\"bearing_deg\":%d", r->bearing_deg);
    json_add(&j, "\"bearing_sigma_deg\":%d", r->bearing_sigma_deg);
    json_add(&j, "\"video\":\"%s\"", r->video);
    json_add(&j, "\"fp\":\"%s\"", fp);
    json_add(&j, "\"sector\":%d", r->sector);
    json_add(&j, "\"rssi_dbm\":%.1f", (double)r->rssi_dbm);
    json_add(&j, "\"basic_id\":\"%s\"", basic);
    json_add(&j, "\"seq\":%u", r->seq);
    return json_end(&j);
}

int report_heartbeat_json(char* out, size_t cap, const HeartbeatReport* h, int full)
{
    Json j;
    json_begin(&j, out, cap);
    if (!json_add(&j, "\"heartbeat\":true")) return 0;
    if (!json_add(&j, "\"node_id\":\"%s\"", h->node_id)) return 0;
    if (!json_add(&j, "\"receiver\":\"%s\"", h->receiver)) return 0;
    if (full) {
        json_add(&j, "\"hw\":\"%s\"", h->hw);
        json_add(&j, "\"scanning\":%s", h->scanning ? "true" : "false");
        json_add(&j, "\"channels\":%d", h->channels);
        json_add(&j, "\"sectors\":%d", h->sectors);
        json_add(&j, "\"heading\":%d", h->heading);
        json_add(&j, "\"threshold_dbm\":%.1f", (double)h->threshold_dbm);
        json_add(&j, "\"threshold_level_db\":%.1f", (double)h->threshold_level_db);
        json_add(&j, "\"video_seen\":%d", h->video_seen);
        json_add(&j, "\"gain_max\":%d", h->gain_max);
        json_add(&j, "\"bw40\":%d", h->bw40);
        json_add(&j, "\"fe_gain_db\":%.1f", (double)h->fe_gain_db);
        json_add(&j, "\"tune_fail\":%u", h->tune_fail);
        json_add(&j, "\"cap_err\":%u", h->cap_err);
        json_add(&j, "\"sweeps\":%u", h->sweeps);
        json_add(&j, "\"usb_drop\":%u", h->usb_drop);
        json_add(&j, "\"mesh_drop\":%u", h->mesh_drop);
        json_add(&j, "\"nf_dbm\":%.0f", (double)h->nf_dbm);
        json_add(&j, "\"temp_c\":%.1f", (double)h->temp_c);
        json_add(&j, "\"uptime_s\":%u", h->uptime_s);
        json_add(&j, "\"seq\":%u", h->seq);
        return json_end(&j);
    }
    json_add(&j, "\"hw\":\"%s\"", h->hw);
    json_add(&j, "\"heading\":%d", h->heading);
    json_add(&j, "\"scanning\":%s", h->scanning ? "true" : "false");
    json_add(&j, "\"sweeps\":%u", h->sweeps);
    json_add(&j, "\"video_seen\":%d", h->video_seen);
    json_add(&j, "\"nf_dbm\":%.0f", (double)h->nf_dbm);
    json_add(&j, "\"temp_c\":%.1f", (double)h->temp_c);
    json_add(&j, "\"uptime_s\":%u", h->uptime_s);
    json_add(&j, "\"tune_fail\":%u", h->tune_fail);
    json_add(&j, "\"cap_err\":%u", h->cap_err);
    return json_end(&j);
}
