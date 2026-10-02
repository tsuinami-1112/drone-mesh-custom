/*
 * detect_mavlink.c - MAVLink v1 / v2 frames sniffed from an open WiFi
 * network (ArduPilot / PX4 WiFi telemetry bridges, SITL, companion boards).
 *
 * Only the messages that identify or position an aircraft are decoded:
 *   HEARTBEAT (0), GPS_RAW_INT (24), GLOBAL_POSITION_INT (33),
 *   HOME_POSITION (242) and the Remote ID set OPEN_DRONE_ID_BASIC_ID (12900),
 *   LOCATION (12901), SELF_ID (12903), SYSTEM (12904), OPERATOR_ID (12905),
 *   MESSAGE_PACK (12915).
 *
 * Every frame is validated with the X.25 CRC including the per-message
 * CRC_EXTRA byte, so random bytes that happen to start with 0xFD/0xFE are
 * rejected. Constants are taken from mavlink/c_library_v2 (common.h
 * MAVLINK_MESSAGE_CRCS and the generated message headers). MAVLink 2
 * payloads arrive zero-truncated and are zero-filled before decoding.
 */
#include <string.h>
#include <math.h>
#include "detect.h"

#define MAV_STX_V1 0xFE
#define MAV_STX_V2 0xFD
#define MAV_IFLAG_SIGNED 0x01
#define MAV_SIGNATURE_LEN 13

enum {
  MSG_HEARTBEAT = 0,
  MSG_GPS_RAW_INT = 24,
  MSG_GLOBAL_POSITION_INT = 33,
  MSG_HOME_POSITION = 242,
  MSG_ODID_BASIC_ID = 12900,
  MSG_ODID_LOCATION = 12901,
  MSG_ODID_SELF_ID = 12903,
  MSG_ODID_SYSTEM = 12904,
  MSG_ODID_OPERATOR_ID = 12905,
  MSG_ODID_MESSAGE_PACK = 12915,
};

typedef struct { uint32_t msgid; uint8_t crc_extra; uint8_t max_len; } mav_entry_t;

static const mav_entry_t MAV_ENTRIES[] = {
  { MSG_HEARTBEAT,           50,   9 },
  { MSG_GPS_RAW_INT,         24,  52 },
  { MSG_GLOBAL_POSITION_INT, 104, 28 },
  { MSG_HOME_POSITION,       104, 60 },
  { MSG_ODID_BASIC_ID,       114, 44 },
  { MSG_ODID_LOCATION,       254, 59 },
  { MSG_ODID_SELF_ID,        249, 46 },
  { MSG_ODID_SYSTEM,         77,  54 },
  { MSG_ODID_OPERATOR_ID,    49,  43 },
  { MSG_ODID_MESSAGE_PACK,   94,  249 },
};

static const mav_entry_t *mav_lookup(uint32_t msgid)
{
  for (size_t i = 0; i < sizeof(MAV_ENTRIES) / sizeof(MAV_ENTRIES[0]); i++)
    if (MAV_ENTRIES[i].msgid == msgid) return &MAV_ENTRIES[i];
  return NULL;
}

/* CRC-16/MCRF4XX exactly as mavlink/c_library_v2 checksum.h */
static inline void crc_accumulate(uint8_t data, uint16_t *crc)
{
  uint8_t tmp = data ^ (uint8_t)(*crc & 0xFF);
  tmp ^= (uint8_t)(tmp << 4);
  *crc = (uint16_t)((*crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4));
}

uint16_t detect_mavlink_crc(const uint8_t *buf, int len, uint8_t crc_extra)
{
  uint16_t crc = 0xFFFF;
  for (int i = 0; i < len; i++) crc_accumulate(buf[i], &crc);
  crc_accumulate(crc_extra, &crc);
  return crc;
}

static inline int32_t rd_i32(const uint8_t *p)
{
  return (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}
static inline uint16_t rd_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline int16_t  rd_i16(const uint8_t *p) { return (int16_t)rd_u16(p); }
static inline float rd_f32(const uint8_t *p)
{
  uint32_t u = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
  float f;
  memcpy(&f, &u, sizeof(f));
  return f;
}

static bool coord_e7(int32_t lat_e7, int32_t lon_e7, double *lat, double *lon)
{
  if (lat_e7 == 0 && lon_e7 == 0) return false;
  double la = lat_e7 / 1e7, lo = lon_e7 / 1e7;
  if (fabs(la) > 90.0 || fabs(lo) > 180.0) return false;
  *lat = la;
  *lon = lo;
  return true;
}

/* MAV_TYPE values that are flying vehicles (minimal.xml) */
static bool mav_type_is_aircraft(uint8_t t)
{
  switch (t) {
    case 0: case 1: case 2: case 3: case 4: case 7: case 8: case 9:
    case 13: case 14: case 15: case 16: case 17: case 19: case 20: case 21:
    case 22: case 23: case 24: case 25: case 28: case 29: case 35: case 43: case 47:
      return true;
    default:
      return false;
  }
}

/* Parse one frame at b[0..n). Returns bytes consumed, 0 if b does not start
 * a valid frame. On success msgid, sysid and compid are set and `payload`
 * (max_len bytes) holds the zero-filled payload. */
static int mav_try_frame(const uint8_t *b, int n, uint32_t *msgid, uint8_t *sysid,
                         uint8_t *compid, uint8_t *payload, int *plen)
{
  if (n < 8) return 0;
  int hdr, len, sig = 0;
  uint32_t id;
  if (b[0] == MAV_STX_V2) {
    if (n < 12) return 0;
    len = b[1];
    uint8_t iflags = b[2];
    if (iflags & ~MAV_IFLAG_SIGNED) return 0;       /* unknown incompatible flag */
    if (iflags & MAV_IFLAG_SIGNED) sig = MAV_SIGNATURE_LEN;
    id = (uint32_t)b[7] | ((uint32_t)b[8] << 8) | ((uint32_t)b[9] << 16);
    hdr = 10;
  } else if (b[0] == MAV_STX_V1) {
    len = b[1];
    id = b[5];
    hdr = 6;
  } else {
    return 0;
  }
  int total = hdr + len + 2 + sig;
  if (n < total) return 0;
  const mav_entry_t *e = mav_lookup(id);
  if (!e || len > e->max_len) return 0;
  uint16_t crc = detect_mavlink_crc(b + 1, hdr - 1 + len, e->crc_extra);
  uint16_t wire = (uint16_t)(b[hdr + len] | (b[hdr + len + 1] << 8));
  if (crc != wire) return 0;

  memset(payload, 0, 255);
  memcpy(payload, b + hdr, (size_t)len);
  *plen = e->max_len;
  *msgid = id;
  *sysid = (b[0] == MAV_STX_V2) ? b[5] : b[3];
  *compid = (b[0] == MAV_STX_V2) ? b[6] : b[4];
  return total;
}

static void odid_pack_from_mavlink(const uint8_t *p, DetectRecord *out)
{
  /* @22 single_message_size (25), @23 msg_pack_size (1..9), @24 messages[225] */
  if (p[22] != ODID_MESSAGE_SIZE) return;
  int count = p[23];
  if (count < 1 || count > ODID_PACK_MAX_MESSAGES) return;
  /* ~1 KB: keep it off the WiFi task's stack (only that task reaches here) */
  static ODID_UAS_Data uas;
  odid_initUasData(&uas);
  for (int i = 0; i < count; i++)
    decodeOpenDroneID(&uas, (uint8_t *)(p + 24 + i * ODID_MESSAGE_SIZE));
  detect_fill_from_odid(out, &uas);
}

bool detect_mavlink_bytes(const uint8_t *buf, int len, DetectRecord *out)
{
  uint8_t payload[255];
  bool vehicle_seen = false;     /* something only an aircraft would send */
  bool ground_only = false;      /* a heartbeat from a GCS / component */
  int off = 0;

  while (off < len) {
    uint32_t msgid;
    uint8_t sysid, compid;
    int plen;
    int used = mav_try_frame(buf + off, len - off, &msgid, &sysid, &compid, payload, &plen);
    if (used == 0) { off++; continue; }
    off += used;
    const uint8_t *p = payload;

    switch (msgid) {
      case MSG_HEARTBEAT: {
        uint8_t type = p[4], autopilot = p[5], base_mode = p[6];
        if (mav_type_is_aircraft(type)) {
          out->mav_sysid = sysid;
          out->mav_type = type;
          out->mav_autopilot = autopilot;
          out->mav_armed = (base_mode & 0x80) ? 1 : 0;
          out->has |= DET_HAS_MAV;
          vehicle_seen = true;
        } else {
          ground_only = true;
        }
        break;
      }
      case MSG_GLOBAL_POSITION_INT: {
        if (coord_e7(rd_i32(p + 4), rd_i32(p + 8), &out->lat, &out->lon)) vehicle_seen = true;
        out->alt_m = rd_i32(p + 12) / 1000;        out->has |= DET_HAS_ALT;
        out->height_m = rd_i32(p + 16) / 1000;     out->has |= DET_HAS_HEIGHT;
        {
          double vx = rd_i16(p + 20) / 100.0, vy = rd_i16(p + 22) / 100.0;
          out->speed_mps = (int16_t)lround(sqrt(vx * vx + vy * vy));
          out->has |= DET_HAS_SPEED;
        }
        {
          uint16_t hdg = rd_u16(p + 26);
          if (hdg != 0xFFFF) { out->heading_deg = (int16_t)((hdg / 100) % 360); out->has |= DET_HAS_HEADING; }
        }
        if (!(out->has & DET_HAS_MAV)) out->mav_sysid = sysid;
        break;
      }
      case MSG_GPS_RAW_INT: {
        uint8_t fix = p[28];
        if (fix >= 2) {
          /* GLOBAL_POSITION_INT (fused) wins when both are present */
          if (out->lat == 0.0 && out->lon == 0.0 &&
              coord_e7(rd_i32(p + 8), rd_i32(p + 12), &out->lat, &out->lon))
            vehicle_seen = true;
          if (!(out->has & DET_HAS_ALT)) { out->alt_m = rd_i32(p + 16) / 1000; out->has |= DET_HAS_ALT; }
          uint16_t vel = rd_u16(p + 24), cog = rd_u16(p + 26);
          if (!(out->has & DET_HAS_SPEED) && vel != 0xFFFF)   { out->speed_mps = (int16_t)((vel + 50) / 100); out->has |= DET_HAS_SPEED; }
          if (!(out->has & DET_HAS_HEADING) && cog != 0xFFFF) { out->heading_deg = (int16_t)((cog / 100) % 360); out->has |= DET_HAS_HEADING; }
        }
        break;
      }
      case MSG_HOME_POSITION:
        coord_e7(rd_i32(p + 0), rd_i32(p + 4), &out->home_lat, &out->home_lon);
        break;
      case MSG_ODID_BASIC_ID: {
        /* @22 id_type, @23 ua_type, @24 uas_id[20] */
        char id[ODID_ID_SIZE + 1];
        if (detect_sanitize(id, sizeof(id), (const char *)(p + 24), ODID_ID_SIZE) > 0) {
          if (!out->uas_id[0] || out->id_type == p[22]) {
            memcpy(out->uas_id, id, sizeof(id));
            out->id_type = p[22];
          } else if (!out->uas_id2[0]) {
            memcpy(out->uas_id2, id, sizeof(id));
            out->id_type2 = p[22];
          }
          if (p[23]) { out->ua_type = p[23]; out->has |= DET_HAS_UATYPE; }
          vehicle_seen = true;
        }
        break;
      }
      case MSG_ODID_LOCATION: {
        if (coord_e7(rd_i32(p + 0), rd_i32(p + 4), &out->lat, &out->lon)) vehicle_seen = true;
        float alt_geo = rd_f32(p + 12), height = rd_f32(p + 16);
        if (alt_geo > -999.0f) { out->alt_m = (int32_t)lroundf(alt_geo); out->has |= DET_HAS_ALT; }
        if (height > -999.0f)  { out->height_m = (int32_t)lroundf(height); out->has |= DET_HAS_HEIGHT; }
        uint16_t dir = rd_u16(p + 24), hspd = rd_u16(p + 26);
        if (dir < 36000)   { out->heading_deg = (int16_t)(dir / 100); out->has |= DET_HAS_HEADING; }
        if (hspd < 25500)  { out->speed_mps = (int16_t)((hspd + 50) / 100); out->has |= DET_HAS_SPEED; }
        out->status = p[52];
        out->has |= DET_HAS_STATUS;
        break;
      }
      case MSG_ODID_SELF_ID:
        detect_sanitize(out->desc, sizeof(out->desc), (const char *)(p + 23), ODID_STR_SIZE);
        break;
      case MSG_ODID_SYSTEM: {
        coord_e7(rd_i32(p + 0), rd_i32(p + 4), &out->pilot_lat, &out->pilot_lon);
        if (p[51] == ODID_CLASSIFICATION_TYPE_EU) { out->eu_cat = p[52]; out->eu_class = p[53]; out->has |= DET_HAS_EU; }
        break;
      }
      case MSG_ODID_OPERATOR_ID:
        if (detect_sanitize(out->op_id, sizeof(out->op_id), (const char *)(p + 23), ODID_ID_SIZE) > 0)
          vehicle_seen = true;
        break;
      case MSG_ODID_MESSAGE_PACK:
        odid_pack_from_mavlink(p, out);
        if (out->uas_id[0] || out->lat != 0.0 || out->lon != 0.0) vehicle_seen = true;
        break;
      default:
        break;
    }
  }

  (void)ground_only;
  return vehicle_seen;
}
