/*
 * detect_odid.c - Open Drone ID (ASTM F3411 / ASD-STAN EN 4709-002) adapters:
 *   - ODID_UAS_Data -> DetectRecord, every message type
 *   - BLE advertising payload -> DetectRecord (BLE 4 legacy single messages
 *     and BLE 5 Long Range message packs), plus BLE-name fingerprints
 */
#include <string.h>
#include <math.h>
#include "detect.h"

/* The ODID scratch structure is ~1 KB (16 authentication pages); keep it off
 * the radio callbacks' stacks. One per caller task, see detect.h. */
static ODID_UAS_Data s_uas_ble;

static bool coord_valid(double lat, double lon)
{
  return (lat != 0.0 || lon != 0.0) && fabs(lat) <= 90.0 && fabs(lon) <= 180.0;
}

void detect_fill_from_odid(DetectRecord *r, const ODID_UAS_Data *u)
{
  int n_ids = 0;
  for (int i = 0; i < ODID_BASIC_ID_MAX_MESSAGES; i++) {
    if (!u->BasicIDValid[i] || u->BasicID[i].UASID[0] == '\0') continue;
    if (n_ids == 0) {
      detect_sanitize(r->uas_id, sizeof(r->uas_id), u->BasicID[i].UASID, ODID_ID_SIZE);
      r->id_type = (uint8_t)u->BasicID[i].IDType;
      if (u->BasicID[i].UAType != ODID_UATYPE_NONE) {
        r->ua_type = (uint8_t)u->BasicID[i].UAType;
        r->has |= DET_HAS_UATYPE;
      }
    } else if (n_ids == 1) {
      detect_sanitize(r->uas_id2, sizeof(r->uas_id2), u->BasicID[i].UASID, ODID_ID_SIZE);
      r->id_type2 = (uint8_t)u->BasicID[i].IDType;
    }
    n_ids++;
  }

  if (u->LocationValid) {
    const ODID_Location_data *l = &u->Location;
    if (coord_valid(l->Latitude, l->Longitude)) { r->lat = l->Latitude; r->lon = l->Longitude; }
    /* -1000 m is the "invalid / unknown" sentinel for every altitude field */
    if (l->AltitudeGeo > -999.0f)       { r->alt_m = (int32_t)lroundf(l->AltitudeGeo);  r->has |= DET_HAS_ALT; }
    else if (l->AltitudeBaro > -999.0f) { r->alt_m = (int32_t)lroundf(l->AltitudeBaro); r->has |= DET_HAS_ALT; }
    if (l->Height > -999.0f)            { r->height_m = (int32_t)lroundf(l->Height);    r->has |= DET_HAS_HEIGHT; }
    if (l->SpeedHorizontal >= 0.0f && l->SpeedHorizontal < (float)INV_SPEED_H) {
      r->speed_mps = (int16_t)lroundf(l->SpeedHorizontal); r->has |= DET_HAS_SPEED;
    }
    if (l->Direction >= 0.0f && l->Direction < 360.0f) {
      r->heading_deg = (int16_t)lroundf(l->Direction) % 360; r->has |= DET_HAS_HEADING;
    }
    r->status = (uint8_t)l->Status;
    r->has |= DET_HAS_STATUS;
  }

  if (u->SystemValid) {
    const ODID_System_data *s = &u->System;
    if (coord_valid(s->OperatorLatitude, s->OperatorLongitude)) {
      r->pilot_lat = s->OperatorLatitude; r->pilot_lon = s->OperatorLongitude;
    }
    if (s->ClassificationType == ODID_CLASSIFICATION_TYPE_EU) {
      r->eu_cat = (uint8_t)s->CategoryEU;
      r->eu_class = (uint8_t)s->ClassEU;
      r->has |= DET_HAS_EU;
    }
  }

  if (u->OperatorIDValid && u->OperatorID.OperatorId[0])
    detect_sanitize(r->op_id, sizeof(r->op_id), u->OperatorID.OperatorId, ODID_ID_SIZE);

  if (u->SelfIDValid && u->SelfID.Desc[0])
    detect_sanitize(r->desc, sizeof(r->desc), u->SelfID.Desc, ODID_STR_SIZE);
}

/* Decode one ODID service-data payload: either a single 25-byte message
 * (BLE 4) or a Message Pack (BLE 5). `m` points at the first message byte,
 * `ml` is the bytes available. */
static bool odid_decode_ble_messages(const uint8_t *m, int ml, ODID_UAS_Data *uas)
{
  if (ml < ODID_MESSAGE_SIZE) return false;
  odid_initUasData(uas);

  if (decodeMessageType(m[0]) == ODID_MESSAGETYPE_PACKED) {
    /* 3-byte pack header + n * 25 bytes must all be present */
    uint8_t single = m[1], count = m[2];
    if (single != ODID_MESSAGE_SIZE || count < 1 || count > ODID_PACK_MAX_MESSAGES) return false;
    if (3 + count * ODID_MESSAGE_SIZE > ml) return false;
    return decodeMessagePack(uas, (ODID_MessagePack_encoded *)m) == ODID_SUCCESS;
  }
  return decodeOpenDroneID(uas, (uint8_t *)m) != ODID_MESSAGETYPE_INVALID;
}

bool detect_ble_adv(const uint8_t addr[6], const uint8_t *ad, int len, int rssi,
                    bool extended, DetectRecord *out)
{
  char name[33] = "";
  bool odid_found = false;
  int company = -1;          /* Bluetooth SIG company ID from manufacturer data */

  detect_record_init(out);
  memcpy(out->mac, addr, 6);
  out->rssi = (int8_t)rssi;

  int i = 0;
  while (i + 1 < len) {
    int l = ad[i];                 /* length of type byte + data */
    if (l == 0) break;
    if (i + 1 + l > len) break;
    uint8_t type = ad[i + 1];
    const uint8_t *d = &ad[i + 2];
    int dl = l - 1;

    /* Service Data, 16-bit UUID 0xFFFA (ASTM Remote ID), application code 0x0D */
    if (type == 0x16 && dl >= 4 + ODID_MESSAGE_SIZE &&
        d[0] == 0xFA && d[1] == 0xFF && d[2] == 0x0D) {
      /* d[3] is the message counter */
      if (!odid_found && odid_decode_ble_messages(d + 4, dl - 4, &s_uas_ble)) {
        detect_fill_from_odid(out, &s_uas_ble);
        out->src = extended ? DET_SRC_ODID_BLE5 : DET_SRC_ODID_BLE4;
        odid_found = true;
      }
    } else if ((type == 0x08 || type == 0x09) && dl > 0) {   /* shortened / complete local name */
      detect_sanitize(name, sizeof(name), (const char *)d, (size_t)dl);
    } else if (type == 0xFF && dl >= 2) {                       /* manufacturer specific data */
      company = d[0] | (d[1] << 8);
    }
    i += 1 + l;
  }

  if (odid_found) return true;

  /* A recognised device name beats a bare company ID (which for DJI and
   * Parrot also covers cameras and headphones). */
  if ((name[0] && detect_fingerprint_ble_name(name, out)) ||
      (company >= 0 && detect_fingerprint_ble_company((uint16_t)company, out))) {
    out->src = DET_SRC_BLE_FP;
    if (name[0]) detect_sanitize(out->ssid, sizeof(out->ssid), name, strlen(name));
    return true;
  }
  return false;
}
