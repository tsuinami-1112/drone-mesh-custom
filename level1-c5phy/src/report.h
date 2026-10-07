/* JSON lines for mesh-mapper.py (USB, full record) and for the Heltec's
 * Meshtastic serial module (one TEXTMSG, fields added in priority order only
 * while they fit). Plain C, tested on the desktop. */
#pragma once
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char* node_id;
    const char* receiver;     /* "c5phy" */
    const char* hw;           /* "v3" */
    char band; int ch; int freq_mhz;
    float rssi_dbm, rssi_min_dbm, rssi_max_dbm; int rssi_n;
    float level_db; int gain; int q_phase; int cfo_khz;
    const char* carrier;      /* "fm" or "cw" */
    const float* sectors_dbm; int sector_count; int sector;
    int bearing_deg; int bearing_sigma_deg;
    int heading;              /* installer's STATION_HEADING_DEG, reported as station_heading */
    int freq_peak;
    const char* video;        /* "NTSC", "PAL" or "none" */
    int sync_hz, field_hz, sync_q, sync_score, video_windows;
    unsigned seq;
} DetectionReport;

/* A digital video link ("type":"wideband"): a bearing on a noise-like carrier
 * confirmed over WB_WINDOWS, with its coarse class and the raw features. */
typedef struct {
    const char* node_id; const char* receiver; const char* hw;
    char band; int ch; int freq_mhz;        /* the table channel the emitter was folded to (the tracking key) */
    float fc_mhz;                           /* estimated centre = freq_mhz + cfo/1000 */
    int   cfo_khz;
    float rssi_dbm, rssi_min_dbm, rssi_max_dbm; int rssi_n;
    float level_db; int gain; int q_phase;
    const char* cls;                        /* "lte" | "dot11" | "wb" */
    const char* conf;                       /* "high" | "med" | "low" */
    int   bw_mhz;                           /* bucket 10 | 20 | 30 | 40 */
    int   duty_pct;
    float cv2, r1, r128, r512, r2667;
    int   span_mhz;                         /* width of the footprint across table channels this sweep */
    const float* sectors_dbm; int sector_count; int sector;
    int   bearing_deg, bearing_sigma_deg, heading;
    unsigned seq;
} WidebandReport;

typedef struct {
    const char* node_id;
    const char* receiver;
    const char* hw;
    int scanning, channels, sectors, heading;
    int has_pos;              /* 1: add "lat"/"lon" after "heading" (STATION_LAT/LON) */
    double lat, lon;
    float threshold_dbm, threshold_level_db;
    int video_seen, gain_max, bw40;
    float fe_gain_db;
    const char* bands;        /* "5.8" or "2.4+5.8" (NULL reads "5.8") */
    float antenna_dbi; int beamwidth_deg; float bearing_k;   /* the 5 GHz patches' BandCal */
    int wb_seen; unsigned pullin;
    unsigned tune_fail, cap_err, bus_stuck, alias_drop, sweeps, usb_drop, mesh_drop;
    float nf_dbm, temp_c;
    float nf_dbm_24; int has_nf_24;   /* DUAL_BAND: the 2.4 GHz floor, USB line only, right after nf_dbm */
    unsigned uptime_s, seq;
} HeartbeatReport;

/* "AF:00:52:03:16:64" - the emitter's tracking key, the same on every station
 * that hears the same channel ('AF' = analog FM, then band, channel, MHz). */
void report_mac(char out[18], char band, int ch, int freq_mhz);
/* "DF:00:52:04:16:89" - the same key for a digital link ('DF' = digital FPV). */
void report_wb_mac(char out[18], char band, int ch, int freq_mhz);
/* "5.8G-R3-5732MHz", "2.4G-G3-2442MHz" */
void report_basic_id(char* out, size_t cap, char band, int ch, int freq_mhz);
/* "NTSC/15736/5734", or "fm/5734" / "cw/5734" without video */
void report_fp(char* out, size_t cap, const char* video, int sync_hz, const char* carrier, int freq_peak);
/* "lte/10/5768.5": class, bandwidth bucket, estimated centre */
void report_wb_fp(char* out, size_t cap, const char* cls, int bw_mhz, float fc_mhz);
/* 10-bit RX5808-style value synthesised from dBm for consumers of the v2 contract */
int report_rssi_raw(float dbm);

/* Return the length written (0 on a buffer too small for the mandatory fields).
 * full = 1: USB record, every field; full = 0: mesh record by priority. */
int report_detection_json(char* out, size_t cap, const DetectionReport* r, int full);
int report_wideband_json(char* out, size_t cap, const WidebandReport* r, int full);
int report_heartbeat_json(char* out, size_t cap, const HeartbeatReport* h, int full);

#ifdef __cplusplus
}
#endif
