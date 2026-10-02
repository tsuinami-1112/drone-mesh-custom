/*
 * detect_dji.c - DJI proprietary "DroneID" vendor-specific IE (beacons of
 * WiFi-link DJI aircraft: Spark, Mavic Pro in WiFi mode, Mavic Air, Mavic
 * Mini / Mini SE). This is what DJI AeroScope reads; it is broadcast in every
 * country regardless of Remote ID rules, but only once the motors are running.
 *
 * Layout (from the Kismet dot11_ie_221_dji_droneid parser, Department 13's
 * "Anatomy of DJI's Drone Identification Implementation" and Bender 2022):
 *
 *   DD len | 26 37 12 | 58 62 13 | sub | record
 *            OUI        unchecked   0x10 flight info / 0x11 flight purpose
 *
 *   0x10 record, version 1 (offsets from the record start, little-endian):
 *     0  u8  version        1   u16 seq        3  u16 state_info (bits below)
 *     5  char[16] serial    21  s32 raw_lon    25 s32 raw_lat   (deg = raw / 174533.0)
 *     29 s16 altitude       31  s16 height     33/35/37 s16 vN / vE / vUp
 *     39/41/43 s16 pitch / roll / yaw (centi-degrees)
 *     45 s32 home_lon       49  s32 home_lat   53 u8 product_type
 *     54 u8 uuid_len        55  uuid[20]
 *   0x10 record, version 2: same through raw_lat, then
 *     29 s16 height (dm)    31  s16 altitude   33/35/37 vN / vE / vUp
 *     39 s16 yaw            41  u64 gps_time (ms)
 *     49 s32 app_lat        53  s32 app_lon   (pilot's phone)
 *     57 s32 home_lon       61  s32 home_lat   65 u8 product_type  66 u8 uuid_len  67 uuid
 *   0x11 record: char[16] serial, u8 drone_id_len, char[10] drone_id,
 *     u8 purpose_len, purpose...
 *
 *   state_info: 0x01 serial valid, 0x02 private mode DISABLED, 0x04 home set,
 *     0x08 uuid set, 0x10 motors on, 0x20 in air, 0x40 gps valid,
 *     0x80 altitude valid, 0x100 height valid, 0x200 horizontal velocity
 *     valid, 0x400 vertical velocity valid, 0x800 pitch/roll/yaw valid
 *
 * A firmware bug truncates the record to 76 bytes, so a version-2 UUID is
 * mostly missing. Every read below is bounded by the IE length. Altitude and
 * velocity units for version 1 are not documented reliably (Kismet itself
 * only trusts the fields through raw_lat), so only yaw (heading) and the
 * version-2 height are exported as numbers.
 */
#include <string.h>
#include <math.h>
#include <stdio.h>
#include "detect.h"

#define DJI_RAD_E7_PER_DEG 174533.0

static inline int16_t le16s(const uint8_t *p) { return (int16_t)(p[0] | (p[1] << 8)); }
static inline uint16_t le16u(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline int32_t le32s(const uint8_t *p)
{
  return (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}

const char *detect_dji_product_name(uint8_t code)
{
  switch (code) {
    case 1:  return "Inspire 1";
    case 2:  return "Phantom 3";
    case 3:  return "Phantom 3 Pro";
    case 4:  return "Phantom 3 Std";
    case 5:  return "M100";
    case 11: return "Phantom 4";
    case 12: return "MG1";
    case 14: return "M600";
    case 15: return "Phantom 3 4K";
    case 16: return "Mavic Pro";
    case 17: return "Inspire 2";
    case 18: return "Phantom 4 Pro";
    case 21: return "Spark";
    case 23: return "M600 Pro";
    case 24: return "Mavic Air";
    case 25: return "M200";
    case 26: return "Phantom 4 Series";
    case 27: return "Phantom 4 Adv";
    case 28: return "M210";
    case 30: return "M210 RTK";
    case 35: return "Phantom 4 RTK";
    case 36: return "Phantom 4 Pro V2";
    case 38: return "MG1P";
    case 40: return "MG1P-RTK";
    case 41: return "Mavic 2";
    case 44: return "M200 V2";
    case 51: return "Mavic 2 Enterprise";
    case 53: return "Mavic Mini";
    case 58: return "Mavic Air 2";
    case 59: return "P4 Multispectral";
    case 60: return "M300 RTK";
    case 61: return "DJI FPV";
    case 63: return "Mini 2";
    case 64: return "Agras T10";
    case 65: return "Agras T30";
    case 66: return "Air 2S";
    case 67: return "M30";
    case 68: return "Mavic 3";
    case 69: return "Mavic 2 Ent. Advanced";
    case 70: return "Mini SE";
    case 73: return "Mini 3 Pro";
    default: return NULL;
  }
}

static bool set_coord(int32_t raw_lat, int32_t raw_lon, double *lat, double *lon)
{
  if (raw_lat == 0 && raw_lon == 0) return false;
  double la = raw_lat / DJI_RAD_E7_PER_DEG, lo = raw_lon / DJI_RAD_E7_PER_DEG;
  if (fabs(la) > 90.0 || fabs(lo) > 180.0) return false;
  *lat = la;
  *lon = lo;
  return true;
}

static void set_model(DetectRecord *out, uint8_t code)
{
  const char *name = detect_dji_product_name(code);
  if (name) snprintf(out->model, sizeof(out->model), "%s", name);
  else if (code) snprintf(out->model, sizeof(out->model), "type %u", (unsigned)code);
}

static void set_heading_from_yaw(DetectRecord *out, int16_t yaw_cdeg)
{
  long deg = lround(yaw_cdeg / 100.0);
  deg %= 360;
  if (deg < 0) deg += 360;
  out->heading_deg = (int16_t)deg;
  out->has |= DET_HAS_HEADING;
}

bool detect_dji_ie(const uint8_t *d, int l, DetectRecord *out)
{
  if (l < 7 + 29) return false;                               /* through raw_lat */
  if (!(d[0] == 0x26 && d[1] == 0x37 && d[2] == 0x12)) return false;
  uint8_t sub = d[6];
  const uint8_t *r = d + 7;
  int rl = l - 7;

  detect_record_init(out);
  snprintf(out->vendor, sizeof(out->vendor), "DJI");
  out->src = DET_SRC_DJI;
  out->conf = DET_CONF_HIGH;
  out->role = DET_ROLE_AIRCRAFT;

  if (sub == 0x10) {
    uint8_t version = r[0];
    uint16_t state = le16u(r + 3);

    if (state & 0x0001)
      detect_sanitize(out->uas_id, sizeof(out->uas_id), (const char *)(r + 5), 16);
    if (out->uas_id[0]) out->id_type = ODID_IDTYPE_SERIAL_NUMBER;

    set_coord(le32s(r + 25), le32s(r + 21), &out->lat, &out->lon);

    if (version == 1 && rl >= 55) {
      if (state & 0x0800) set_heading_from_yaw(out, le16s(r + 43));
      set_coord(le32s(r + 49), le32s(r + 45), &out->home_lat, &out->home_lon);
      set_model(out, r[53]);
    } else if (version == 2 && rl >= 67) {
      if (state & 0x0100) { out->height_m = le16s(r + 29) / 10; out->has |= DET_HAS_HEIGHT; }
      if (state & 0x0800) set_heading_from_yaw(out, le16s(r + 39));
      set_coord(le32s(r + 49), le32s(r + 53), &out->pilot_lat, &out->pilot_lon);
      set_coord(le32s(r + 61), le32s(r + 57), &out->home_lat, &out->home_lon);
      set_model(out, r[65]);
    }

    if (state & 0x0020)      out->status = ODID_STATUS_AIRBORNE;
    else if (state & 0x0010) out->status = ODID_STATUS_GROUND;
    else                     out->status = ODID_STATUS_UNDECLARED;
    out->has |= DET_HAS_STATUS;
    return true;
  }

  if (sub == 0x11) {
    if (rl < 28) return false;
    detect_sanitize(out->uas_id, sizeof(out->uas_id), (const char *)r, 16);
    if (out->uas_id[0]) out->id_type = ODID_IDTYPE_SERIAL_NUMBER;
    /* The user-entered "Drone ID" (registration-style text from DJI GO 4) */
    int id_len = r[16];
    if (id_len > 10) id_len = 10;
    if (id_len > 0) detect_sanitize(out->desc, sizeof(out->desc), (const char *)(r + 17), (size_t)id_len);
    return true;
  }

  return false;
}
