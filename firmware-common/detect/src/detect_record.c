/*
 * detect_record.c - DetectRecord lifecycle, merge, JSON output, throttle.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "detect.h"

/* ------------------------------------------------------------------------ */
/* Labels                                                                    */
/* ------------------------------------------------------------------------ */

void detect_record_init(DetectRecord *r)
{
  memset(r, 0, sizeof(*r));
}

const char *detect_source_str(uint8_t src)
{
  switch (src) {
    case DET_SRC_ODID_BLE4:   return "odid_ble";
    case DET_SRC_ODID_BLE5:   return "odid_ble5";
    case DET_SRC_ODID_NAN:    return "odid_nan";
    case DET_SRC_ODID_BEACON: return "odid_bcn";
    case DET_SRC_DJI:         return "dji";
    case DET_SRC_MAVLINK:     return "mavlink";
    case DET_SRC_WIFI_FP:     return "wifi";
    case DET_SRC_BLE_FP:      return "ble";
    default:                  return "";
  }
}

const char *detect_conf_str(uint8_t conf)
{
  switch (conf) {
    case DET_CONF_LOW:  return "low";
    case DET_CONF_MED:  return "med";
    case DET_CONF_HIGH: return "high";
    default:            return "";
  }
}

const char *detect_role_str(uint8_t role)
{
  switch (role) {
    case DET_ROLE_AIRCRAFT:   return "aircraft";
    case DET_ROLE_CONTROLLER: return "controller";
    case DET_ROLE_ACCESSORY:  return "accessory";
    default:                  return "";
  }
}

bool detect_is_heuristic(uint8_t src)
{
  return src == DET_SRC_WIFI_FP || src == DET_SRC_BLE_FP;
}

/* ------------------------------------------------------------------------ */
/* Strings                                                                   */
/* ------------------------------------------------------------------------ */

int detect_sanitize(char *dst, size_t dstsize, const char *src, size_t srclen)
{
  size_t n = 0;
  if (dstsize == 0) return 0;
  for (size_t i = 0; i < srclen && src[i] != '\0' && n + 1 < dstsize; i++) {
    unsigned char c = (unsigned char)src[i];
    if (c >= 0x20 && c <= 0x7E && c != '"' && c != '\\')
      dst[n++] = (char)c;
  }
  dst[n] = '\0';
  return (int)n;
}

static void copy_if_set(char *dst, size_t dstsize, const char *src)
{
  if (src[0]) {
    strncpy(dst, src, dstsize - 1);
    dst[dstsize - 1] = '\0';
  }
}

/* ------------------------------------------------------------------------ */
/* Merge                                                                     */
/* ------------------------------------------------------------------------ */

void detect_record_merge(DetectRecord *into, const DetectRecord *from)
{
  bool into_decoded = into->src != DET_SRC_NONE && !detect_is_heuristic(into->src);

  into->rssi = from->rssi;
  if (from->channel) into->channel = from->channel;
  into->last_seen = from->last_seen;

  /* A fingerprint seen after a decoded protocol must not hide the fact
   * that the aircraft was positively identified. */
  if (!(into_decoded && detect_is_heuristic(from->src))) {
    if (from->src)  into->src  = from->src;
    into->conf = from->conf;
    if (from->role) into->role = from->role;
  }

  if (from->lat != 0.0 || from->lon != 0.0)             { into->lat = from->lat; into->lon = from->lon; }
  if (from->pilot_lat != 0.0 || from->pilot_lon != 0.0) { into->pilot_lat = from->pilot_lat; into->pilot_lon = from->pilot_lon; }
  if (from->home_lat != 0.0 || from->home_lon != 0.0)   { into->home_lat = from->home_lat; into->home_lon = from->home_lon; }

  if (from->has & DET_HAS_ALT)     { into->alt_m = from->alt_m;             into->has |= DET_HAS_ALT; }
  if (from->has & DET_HAS_HEIGHT)  { into->height_m = from->height_m;       into->has |= DET_HAS_HEIGHT; }
  if (from->has & DET_HAS_SPEED)   { into->speed_mps = from->speed_mps;     into->has |= DET_HAS_SPEED; }
  if (from->has & DET_HAS_HEADING) { into->heading_deg = from->heading_deg; into->has |= DET_HAS_HEADING; }
  if (from->has & DET_HAS_STATUS)  { into->status = from->status;           into->has |= DET_HAS_STATUS; }
  if (from->has & DET_HAS_UATYPE)  { into->ua_type = from->ua_type;         into->has |= DET_HAS_UATYPE; }
  if (from->has & DET_HAS_EU)      { into->eu_cat = from->eu_cat; into->eu_class = from->eu_class; into->has |= DET_HAS_EU; }
  if (from->has & DET_HAS_MAV) {
    into->mav_sysid = from->mav_sysid; into->mav_type = from->mav_type;
    into->mav_autopilot = from->mav_autopilot; into->mav_armed = from->mav_armed;
    into->has |= DET_HAS_MAV;
  }

  if (from->uas_id[0])  { copy_if_set(into->uas_id, sizeof(into->uas_id), from->uas_id);   into->id_type = from->id_type; }
  if (from->uas_id2[0]) { copy_if_set(into->uas_id2, sizeof(into->uas_id2), from->uas_id2); into->id_type2 = from->id_type2; }
  copy_if_set(into->op_id,  sizeof(into->op_id),  from->op_id);
  copy_if_set(into->desc,   sizeof(into->desc),   from->desc);
  copy_if_set(into->vendor, sizeof(into->vendor), from->vendor);
  copy_if_set(into->model,  sizeof(into->model),  from->model);
  copy_if_set(into->ssid,   sizeof(into->ssid),   from->ssid);
}

/* ------------------------------------------------------------------------ */
/* JSON                                                                      */
/* ------------------------------------------------------------------------ */

typedef struct {
  char  *buf;
  size_t cap;      /* total capacity incl. NUL */
  size_t len;
  bool   failed;   /* mandatory field did not fit */
} jw_t;

/* Coordinate text at full 6-decimal precision with trailing zeros removed:
 * "34.050000" -> "34.05" is the same number in fewer LoRa bytes. */
static void fmt_coord(char *out, size_t outsize, double v)
{
  int n = snprintf(out, outsize, "%.6f", v);
  if (n <= 0 || (size_t)n >= outsize) return;
  int e = n - 1;
  while (e > 0 && out[e] == '0') e--;
  if (e > 0 && out[e] == '.') e--;
  out[e + 1] = '\0';
}

/* Append `s` if it fits together with the closing brace; otherwise leave the
 * buffer untouched and report false. */
static bool jw_try(jw_t *w, const char *s)
{
  size_t l = strlen(s);
  if (w->len + l + 1 >= w->cap) return false;   /* +1 for the final '}' */
  memcpy(w->buf + w->len, s, l);
  w->len += l;
  w->buf[w->len] = '\0';
  return true;
}

static bool jw_str(jw_t *w, const char *key, const char *val)
{
  char tmp[96];
  snprintf(tmp, sizeof(tmp), ",\"%s\":\"%s\"", key, val);
  return jw_try(w, tmp);
}

static bool jw_int(jw_t *w, const char *key, long val)
{
  char tmp[48];
  snprintf(tmp, sizeof(tmp), ",\"%s\":%ld", key, val);
  return jw_try(w, tmp);
}

static bool jw_int2(jw_t *w, const char *k1, long v1, const char *k2, long v2)
{
  char tmp[64];
  snprintf(tmp, sizeof(tmp), ",\"%s\":%ld,\"%s\":%ld", k1, v1, k2, v2);
  return jw_try(w, tmp);
}

static bool jw_coord2(jw_t *w, const char *k1, double v1, const char *k2, double v2)
{
  char a[24], b[24], tmp[96];
  fmt_coord(a, sizeof(a), v1);
  fmt_coord(b, sizeof(b), v2);
  snprintf(tmp, sizeof(tmp), ",\"%s\":%s,\"%s\":%s", k1, a, k2, b);
  return jw_try(w, tmp);
}

#define MUST(expr) do { if (!(expr)) w.failed = true; } while (0)

int detect_build_json(char *buf, size_t bufsize, const DetectRecord *r, const char *node_id)
{
  jw_t w = { buf, bufsize, 0, false };
  char tmp[64];

  if (bufsize < 48) return -1;

  snprintf(tmp, sizeof(tmp), "{\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"rssi\":%d",
           r->mac[0], r->mac[1], r->mac[2], r->mac[3], r->mac[4], r->mac[5], (int)r->rssi);
  MUST(jw_try(&w, tmp));

  /* --- mandatory: which node saw what, where --- */
  if (node_id && node_id[0])    MUST(jw_str(&w, "node_id", node_id));
  if (r->lat != 0.0 || r->lon != 0.0)
                                MUST(jw_coord2(&w, "drone_lat", r->lat, "drone_long", r->lon));
  if (r->has & DET_HAS_ALT)     MUST(jw_int(&w, "drone_altitude", r->alt_m));
  if (r->pilot_lat != 0.0 || r->pilot_lon != 0.0)
                                MUST(jw_coord2(&w, "pilot_lat", r->pilot_lat, "pilot_long", r->pilot_lon));
  if (r->uas_id[0])             MUST(jw_str(&w, "basic_id", r->uas_id));
  if (w.failed) return -1;

  /* --- optional, in priority order; each is dropped only if it does not fit.
   * A 20-char serial + 16-char operator ID + both positions is ~230 bytes,
   * exactly a Meshtastic text message, so the operator ID (the EU/UK
   * registration) comes first and the source label is the first to go. --- */
  if (r->op_id[0])              jw_str(&w, "op_id", r->op_id);
  if (r->uas_id[0] && r->id_type)
                                jw_int(&w, "id_type", r->id_type);
  if (r->src)                   jw_str(&w, "src", detect_source_str(r->src));
  if (r->vendor[0])             jw_str(&w, "vendor", r->vendor);
  if (r->model[0])              jw_str(&w, "model", r->model);
  if (r->conf)                  jw_str(&w, "conf", detect_conf_str(r->conf));
  if (r->role)                  jw_str(&w, "role", detect_role_str(r->role));
  if ((r->has & DET_HAS_UATYPE) && r->ua_type)
                                jw_int(&w, "ua_type", r->ua_type);
  if (r->has & DET_HAS_EU)      jw_int2(&w, "eu_cat", r->eu_cat, "eu_class", r->eu_class);
  if (r->uas_id2[0]) {
    if (jw_str(&w, "basic_id2", r->uas_id2) && r->id_type2) jw_int(&w, "id_type2", r->id_type2);
  }
  if (r->has & DET_HAS_HEIGHT)  jw_int(&w, "height", r->height_m);
  if (r->has & DET_HAS_SPEED)   jw_int(&w, "speed", r->speed_mps);
  if (r->has & DET_HAS_HEADING) jw_int(&w, "heading", r->heading_deg);
  if ((r->has & DET_HAS_STATUS) && r->status)
                                jw_int(&w, "status", r->status);
  if (r->channel)               jw_int(&w, "ch", r->channel);
  if (r->desc[0])               jw_str(&w, "desc", r->desc);
  if (r->ssid[0])               jw_str(&w, "ssid", r->ssid);
  if (r->home_lat != 0.0 || r->home_lon != 0.0)
                                jw_coord2(&w, "home_lat", r->home_lat, "home_long", r->home_lon);
  if (r->has & DET_HAS_MAV) {
    if (jw_int(&w, "sysid", r->mav_sysid) && jw_int(&w, "mavtype", r->mav_type)
        && jw_int(&w, "autopilot", r->mav_autopilot))
      jw_int(&w, "armed", r->mav_armed);
  }

  /* jw_try always leaves room for this */
  buf[w.len++] = '}';
  buf[w.len] = '\0';
  return (int)w.len;
}

/* ------------------------------------------------------------------------ */
/* Throttle                                                                  */
/* ------------------------------------------------------------------------ */

#define THROTTLE_SLOTS 16

typedef struct {
  uint8_t  mac[6];
  bool     used;
  uint32_t last_ms;
} throttle_slot_t;

static throttle_slot_t s_throttle[THROTTLE_SLOTS];

bool detect_throttle(const uint8_t mac[6], uint32_t now_ms, uint32_t min_interval_ms)
{
  if (min_interval_ms == 0) return true;

  int free_idx = -1, oldest_idx = 0;
  uint32_t oldest_age = 0;
  for (int i = 0; i < THROTTLE_SLOTS; i++) {
    throttle_slot_t *s = &s_throttle[i];
    if (!s->used) { if (free_idx < 0) free_idx = i; continue; }
    if (memcmp(s->mac, mac, 6) == 0) {
      if ((uint32_t)(now_ms - s->last_ms) < min_interval_ms) return false;
      s->last_ms = now_ms;
      return true;
    }
    uint32_t age = (uint32_t)(now_ms - s->last_ms);
    if (age >= oldest_age) { oldest_age = age; oldest_idx = i; }
  }
  throttle_slot_t *s = &s_throttle[free_idx >= 0 ? free_idx : oldest_idx];
  memcpy(s->mac, mac, 6);
  s->used = true;
  s->last_ms = now_ms;
  return true;
}
