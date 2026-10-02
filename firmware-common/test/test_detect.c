/*
 * Host unit tests for the shared detection library.
 *
 * Synthetic frames are built with the Open Drone ID encoders (so the decode
 * path is checked end to end), with the documented DJI DroneID layout and
 * with MAVLink test vectors whose checksums were computed independently from
 * the reference implementation.
 *
 * JSON lines are printed with a "JSON" / "JSON_MESH" tag and validated by
 * check_json.py.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "detect.h"
#include "odid_wifi.h"

static int fails = 0;
#define CHECK(cond) do { if (!(cond)) { fails++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define CHECK_STR(a, b) do { if (strcmp((a), (b)) != 0) { fails++; fprintf(stderr, "FAIL %s:%d: '%s' != '%s'\n", __FILE__, __LINE__, (a), (b)); } } while (0)
#define NEAR(a, b, eps) (fabs((double)(a) - (double)(b)) < (eps))

static const uint8_t MAC_DJI[6]   = { 0x60, 0x60, 0x1F, 0x11, 0x22, 0x33 };
static const uint8_t MAC_OTHER[6] = { 0x00, 0x11, 0x22, 0x33, 0x44, 0x55 };

static void print_json(const char *tag, const DetectRecord *r, size_t cap)
{
  char buf[1024];
  if (cap > sizeof(buf)) cap = sizeof(buf);
  int n = detect_build_json(buf, cap, r, "A1B2");
  CHECK(n > 0);
  CHECK(n > 0 && (size_t)n < cap);
  if (n > 0) printf("%s %s\n", tag, buf);
}

static void put_le16(uint8_t *p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }
static void put_le32(uint8_t *p, int32_t v)
{
  uint32_t u = (uint32_t)v;
  p[0] = u & 0xFF; p[1] = (u >> 8) & 0xFF; p[2] = (u >> 16) & 0xFF; p[3] = (u >> 24) & 0xFF;
}
static void put_be16(uint8_t *p, uint16_t v) { p[0] = v >> 8; p[1] = v & 0xFF; }

/* ------------------------------------------------------------------------ */
/* Open Drone ID                                                             */
/* ------------------------------------------------------------------------ */

static void make_uas(ODID_UAS_Data *u)
{
  odid_initUasData(u);
  u->BasicID[0].UAType = ODID_UATYPE_HELICOPTER_OR_MULTIROTOR;
  u->BasicID[0].IDType = ODID_IDTYPE_SERIAL_NUMBER;
  strcpy(u->BasicID[0].UASID, "1581F5FHB229F00202DR");
  u->BasicIDValid[0] = 1;
  u->BasicID[1].UAType = ODID_UATYPE_HELICOPTER_OR_MULTIROTOR;
  u->BasicID[1].IDType = ODID_IDTYPE_CAA_REGISTRATION_ID;
  strcpy(u->BasicID[1].UASID, "JU123456789");
  u->BasicIDValid[1] = 1;

  u->Location.Status = ODID_STATUS_AIRBORNE;
  u->Location.Direction = 123.0f;
  u->Location.SpeedHorizontal = 12.5f;
  u->Location.SpeedVertical = 1.0f;
  u->Location.Latitude = 51.507351;
  u->Location.Longitude = -0.127758;
  u->Location.AltitudeBaro = 100.0f;
  u->Location.AltitudeGeo = 120.0f;
  u->Location.HeightType = ODID_HEIGHT_REF_OVER_TAKEOFF;
  u->Location.Height = 80.0f;
  u->Location.HorizAccuracy = ODID_HOR_ACC_3_METER;
  u->Location.VertAccuracy = ODID_VER_ACC_3_METER;
  u->Location.BaroAccuracy = ODID_VER_ACC_3_METER;
  u->Location.SpeedAccuracy = ODID_SPEED_ACC_1_METERS_PER_SECOND;
  u->Location.TSAccuracy = ODID_TIME_ACC_0_1_SECOND;
  u->Location.TimeStamp = 1234.5f;
  u->LocationValid = 1;

  u->System.OperatorLocationType = ODID_OPERATOR_LOCATION_TYPE_LIVE_GNSS;
  u->System.ClassificationType = ODID_CLASSIFICATION_TYPE_EU;
  u->System.OperatorLatitude = 51.5;
  u->System.OperatorLongitude = -0.12;
  u->System.AreaCount = 1;
  u->System.AreaRadius = 0;
  u->System.AreaCeiling = -1000.0f;
  u->System.AreaFloor = -1000.0f;
  u->System.CategoryEU = ODID_CATEGORY_EU_OPEN;
  u->System.ClassEU = ODID_CLASS_EU_CLASS_1;
  u->System.OperatorAltitudeGeo = 20.0f;
  u->System.Timestamp = 123456;
  u->SystemValid = 1;

  u->OperatorID.OperatorIdType = ODID_OPERATOR_ID;
  strcpy(u->OperatorID.OperatorId, "FIN87astrdge12k8");
  u->OperatorIDValid = 1;

  u->SelfID.DescType = ODID_DESC_TYPE_TEXT;
  strcpy(u->SelfID.Desc, "Survey flight");
  u->SelfIDValid = 1;
}

static void check_full_odid(const DetectRecord *r)
{
  CHECK_STR(r->uas_id, "1581F5FHB229F00202DR");
  CHECK(r->id_type == ODID_IDTYPE_SERIAL_NUMBER);
  CHECK_STR(r->uas_id2, "JU123456789");
  CHECK(r->id_type2 == ODID_IDTYPE_CAA_REGISTRATION_ID);
  CHECK((r->has & DET_HAS_UATYPE) && r->ua_type == ODID_UATYPE_HELICOPTER_OR_MULTIROTOR);
  CHECK(NEAR(r->lat, 51.507351, 1e-5));
  CHECK(NEAR(r->lon, -0.127758, 1e-5));
  CHECK((r->has & DET_HAS_ALT) && r->alt_m == 120);
  CHECK((r->has & DET_HAS_HEIGHT) && r->height_m == 80);
  CHECK((r->has & DET_HAS_SPEED) && r->speed_mps == 13);
  CHECK((r->has & DET_HAS_HEADING) && r->heading_deg == 123);
  CHECK((r->has & DET_HAS_STATUS) && r->status == ODID_STATUS_AIRBORNE);
  CHECK(NEAR(r->pilot_lat, 51.5, 1e-5));
  CHECK(NEAR(r->pilot_lon, -0.12, 1e-5));
  CHECK((r->has & DET_HAS_EU) && r->eu_cat == ODID_CATEGORY_EU_OPEN && r->eu_class == ODID_CLASS_EU_CLASS_1);
  CHECK_STR(r->op_id, "FIN87astrdge12k8");
  CHECK_STR(r->desc, "Survey flight");
}

static void test_odid_wifi(void)
{
  ODID_UAS_Data u;
  uint8_t frame[512];
  DetectRecord r;
  make_uas(&u);

  /* Beacon with the ASD-STAN vendor IE, as built by the reference encoder */
  const char *ssid = "RID-1581F5FHB229F00202DR";
  int n = odid_wifi_build_message_pack_beacon_frame(&u, (char *)MAC_DJI, ssid, strlen(ssid),
                                                    100, 7, frame, sizeof(frame));
  CHECK(n > 0);
  /* append a fake FCS like the sniffer delivers on ESP32-S3 */
  memcpy(frame + n, "\xde\xad\xbe\xef", 4);
  CHECK(detect_wifi_mgmt(frame, n + 4, -55, 6, &r));
  CHECK(r.src == DET_SRC_ODID_BEACON);
  CHECK(memcmp(r.mac, MAC_DJI, 6) == 0);
  CHECK(r.rssi == -55 && r.channel == 6);
  CHECK(r.ssid[0] == '\0');          /* SSID of a Remote ID beacon is not re-sent */
  check_full_odid(&r);
  print_json("JSON", &r, 1024);
  print_json("JSON_MESH", &r, 230);

  /* The same frame without the FCS parses identically */
  CHECK(detect_wifi_mgmt(frame, n, -55, 6, &r));
  CHECK(r.src == DET_SRC_ODID_BEACON);

  /* NAN action frame */
  n = odid_wifi_build_message_pack_nan_action_frame(&u, (char *)MAC_DJI, 3, frame, sizeof(frame));
  CHECK(n > 0);
  CHECK(detect_wifi_mgmt(frame, n, -61, 6, &r));
  CHECK(r.src == DET_SRC_ODID_NAN);
  CHECK(memcmp(r.mac, MAC_DJI, 6) == 0);
  check_full_odid(&r);
  print_json("JSON", &r, 1024);

  /* A truncated frame must be rejected, never read out of bounds */
  CHECK(!detect_wifi_mgmt(frame, 40, -61, 6, &r));
  CHECK(!detect_wifi_mgmt(frame, 10, -61, 6, &r));
}

static int ble_ad_with_odid(uint8_t *ad, const uint8_t *msgs, int msgs_len)
{
  int p = 0;
  ad[p++] = 2; ad[p++] = 0x01; ad[p++] = 0x06;              /* Flags */
  ad[p++] = (uint8_t)(1 + 4 + msgs_len);                    /* len = type + data */
  ad[p++] = 0x16;                                           /* Service Data 16-bit UUID */
  ad[p++] = 0xFA; ad[p++] = 0xFF;                           /* 0xFFFA */
  ad[p++] = 0x0D;                                           /* ASTM application code */
  ad[p++] = 0x2A;                                           /* message counter */
  memcpy(ad + p, msgs, msgs_len);
  p += msgs_len;
  return p;
}

static void test_odid_ble(void)
{
  ODID_UAS_Data u;
  DetectRecord r;
  uint8_t ad[256];
  const uint8_t addr[6] = { 0xC0, 0x11, 0x22, 0x33, 0x44, 0x55 };
  make_uas(&u);

  /* BLE 4 legacy: one Basic ID message */
  ODID_BasicID_encoded bid;
  CHECK(encodeBasicIDMessage(&bid, &u.BasicID[0]) == ODID_SUCCESS);
  int n = ble_ad_with_odid(ad, (const uint8_t *)&bid, ODID_MESSAGE_SIZE);
  CHECK(ad[3] == 0x1E);                                     /* the standard's AD length */
  CHECK(detect_ble_adv(addr, ad, n, -70, false, &r));
  CHECK(r.src == DET_SRC_ODID_BLE4);
  CHECK(memcmp(r.mac, addr, 6) == 0);
  CHECK_STR(r.uas_id, "1581F5FHB229F00202DR");
  CHECK(r.lat == 0.0 && r.lon == 0.0);
  print_json("JSON", &r, 1024);

  /* BLE 4 legacy: one Location message */
  ODID_Location_encoded loc;
  CHECK(encodeLocationMessage(&loc, &u.Location) == ODID_SUCCESS);
  n = ble_ad_with_odid(ad, (const uint8_t *)&loc, ODID_MESSAGE_SIZE);
  CHECK(detect_ble_adv(addr, ad, n, -70, false, &r));
  CHECK(r.src == DET_SRC_ODID_BLE4);
  CHECK(NEAR(r.lat, 51.507351, 1e-5));
  CHECK(r.uas_id[0] == '\0');

  /* BLE 4 legacy: Operator ID message (the EU registration number) */
  ODID_OperatorID_encoded opid;
  CHECK(encodeOperatorIDMessage(&opid, &u.OperatorID) == ODID_SUCCESS);
  n = ble_ad_with_odid(ad, (const uint8_t *)&opid, ODID_MESSAGE_SIZE);
  CHECK(detect_ble_adv(addr, ad, n, -70, false, &r));
  CHECK_STR(r.op_id, "FIN87astrdge12k8");

  /* BLE 5 Long Range: a Message Pack with every message type */
  ODID_MessagePack_data pd;
  odid_initMessagePackData(&pd);
  pd.SingleMessageSize = ODID_MESSAGE_SIZE;
  pd.MsgPackSize = 0;
  CHECK(encodeBasicIDMessage(&pd.Messages[pd.MsgPackSize++].basicId, &u.BasicID[0]) == ODID_SUCCESS);
  CHECK(encodeBasicIDMessage(&pd.Messages[pd.MsgPackSize++].basicId, &u.BasicID[1]) == ODID_SUCCESS);
  CHECK(encodeLocationMessage(&pd.Messages[pd.MsgPackSize++].location, &u.Location) == ODID_SUCCESS);
  CHECK(encodeSelfIDMessage(&pd.Messages[pd.MsgPackSize++].selfId, &u.SelfID) == ODID_SUCCESS);
  CHECK(encodeSystemMessage(&pd.Messages[pd.MsgPackSize++].system, &u.System) == ODID_SUCCESS);
  CHECK(encodeOperatorIDMessage(&pd.Messages[pd.MsgPackSize++].operatorId, &u.OperatorID) == ODID_SUCCESS);
  ODID_MessagePack_encoded pe;
  CHECK(encodeMessagePack(&pe, &pd) == ODID_SUCCESS);
  int pack_len = 3 + pd.MsgPackSize * ODID_MESSAGE_SIZE;
  n = ble_ad_with_odid(ad, (const uint8_t *)&pe, pack_len);
  CHECK(detect_ble_adv(addr, ad, n, -88, true, &r));
  CHECK(r.src == DET_SRC_ODID_BLE5);
  check_full_odid(&r);
  print_json("JSON", &r, 1024);
  print_json("JSON_MESH", &r, 230);

  /* Same pack reported as a legacy advert is labelled BLE 4 */
  CHECK(detect_ble_adv(addr, ad, n, -88, false, &r));
  CHECK(r.src == DET_SRC_ODID_BLE4);

  /* A pack whose advertised size exceeds the data must be rejected */
  CHECK(!detect_ble_adv(addr, ad, n - 30, -88, true, &r));

  /* Not Remote ID: a BLE name that fingerprints a controller */
  uint8_t ad2[32];
  int p = 0;
  ad2[p++] = 2; ad2[p++] = 0x01; ad2[p++] = 0x06;
  const char *name = "DJI RC-N1 Pro";
  ad2[p++] = (uint8_t)(1 + strlen(name)); ad2[p++] = 0x09;
  memcpy(ad2 + p, name, strlen(name)); p += (int)strlen(name);
  CHECK(detect_ble_adv(addr, ad2, p, -50, false, &r));
  CHECK(r.src == DET_SRC_BLE_FP);
  CHECK_STR(r.vendor, "DJI");
  CHECK(r.role == DET_ROLE_CONTROLLER);
  CHECK_STR(r.ssid, "DJI RC-N1 Pro");
  print_json("JSON", &r, 1024);

  /* Unrelated advert */
  const char *name2 = "Galaxy Buds";
  p = 3;
  ad2[p++] = (uint8_t)(1 + strlen(name2)); ad2[p++] = 0x09;
  memcpy(ad2 + p, name2, strlen(name2)); p += (int)strlen(name2);
  CHECK(!detect_ble_adv(addr, ad2, p, -50, false, &r));
}

/* ------------------------------------------------------------------------ */
/* 802.11 beacon / probe builder                                             */
/* ------------------------------------------------------------------------ */

static int build_mgmt(uint8_t *f, uint8_t fc0, const uint8_t *sa, const char *ssid,
                      const uint8_t *vendor_ie, int vendor_len)
{
  memset(f, 0, 512);
  f[0] = fc0;
  memset(f + 4, 0xFF, 6);
  memcpy(f + 10, sa, 6);
  memcpy(f + 16, sa, 6);
  int p = 24;
  if (fc0 == 0x80 || fc0 == 0x50) { p += 12; f[32] = 0x64; }   /* timestamp, interval, capability */
  if (ssid) {
    size_t sl = strlen(ssid);
    f[p++] = 0x00; f[p++] = (uint8_t)sl; memcpy(f + p, ssid, sl); p += (int)sl;
  }
  f[p++] = 0x01; f[p++] = 0x01; f[p++] = 0x8C;                 /* supported rates */
  if (vendor_ie) {
    f[p++] = 0xDD; f[p++] = (uint8_t)vendor_len; memcpy(f + p, vendor_ie, vendor_len); p += vendor_len;
  }
  memcpy(f + p, "\xde\xad\xbe\xef", 4);                        /* FCS */
  return p + 4;
}

/* ------------------------------------------------------------------------ */
/* DJI DroneID                                                               */
/* ------------------------------------------------------------------------ */

static int build_dji_ie(uint8_t *ie, int version)
{
  /* 26 37 12 | 58 62 13 | 0x10 | record (75 bytes incl. uuid) -> 82 bytes */
  memset(ie, 0, 96);
  ie[0] = 0x26; ie[1] = 0x37; ie[2] = 0x12;
  ie[3] = 0x58; ie[4] = 0x62; ie[5] = 0x13;
  ie[6] = 0x10;
  uint8_t *r = ie + 7;
  r[0] = (uint8_t)version;
  put_le16(r + 1, 0x0102);
  memcpy(r + 5, "0K1DFBK00A1234", 14);
  int32_t lat = (int32_t)lround(34.0522 * 174533.0);
  int32_t lon = (int32_t)lround(-118.2437 * 174533.0);
  put_le32(r + 21, lon);
  put_le32(r + 25, lat);
  if (version == 1) {
    put_le16(r + 3, 0x0001 | 0x0004 | 0x0010 | 0x0020 | 0x0040 | 0x0800);
    put_le16(r + 43, 9000);                            /* yaw 90.00 deg */
    put_le32(r + 45, lon + 1745);                      /* home ~0.01 deg east */
    put_le32(r + 49, lat);
    r[53] = 21;                                        /* Spark */
    r[54] = 0;
  } else {
    put_le16(r + 3, 0x0001 | 0x0010 | 0x0020 | 0x0040 | 0x0100 | 0x0800);
    put_le16(r + 29, 456);                             /* height 45.6 m */
    put_le16(r + 39, (uint16_t)(int16_t)-4500);        /* yaw -45.00 deg -> 315 */
    put_le32(r + 49, lat + 1745);                      /* pilot phone (lat first in v2) */
    put_le32(r + 53, lon);
    put_le32(r + 57, lon - 1745);                      /* home lon */
    put_le32(r + 61, lat - 1745);                      /* home lat */
    r[65] = 53;                                        /* Mavic Mini */
    r[66] = 0;
  }
  return 82;
}

static void test_dji(void)
{
  uint8_t ie[96], frame[512];
  DetectRecord r;

  int l = build_dji_ie(ie, 1);
  CHECK(detect_dji_ie(ie, l, &r));
  CHECK(r.src == DET_SRC_DJI);
  CHECK_STR(r.vendor, "DJI");
  CHECK_STR(r.model, "Spark");
  CHECK_STR(r.uas_id, "0K1DFBK00A1234");
  CHECK(r.id_type == ODID_IDTYPE_SERIAL_NUMBER);
  CHECK(NEAR(r.lat, 34.0522, 1e-5));
  CHECK(NEAR(r.lon, -118.2437, 1e-5));
  CHECK((r.has & DET_HAS_HEADING) && r.heading_deg == 90);
  CHECK(NEAR(r.home_lat, 34.0522, 1e-5));
  CHECK(NEAR(r.home_lon, -118.2337, 1e-4));
  CHECK((r.has & DET_HAS_STATUS) && r.status == ODID_STATUS_AIRBORNE);
  CHECK(r.pilot_lat == 0.0);
  CHECK(!(r.has & DET_HAS_HEIGHT));                    /* v1 units are not trusted */

  /* inside a beacon, with the aircraft's SSID */
  int n = build_mgmt(frame, 0x80, MAC_DJI, "Spark-ABC123", ie, l);
  CHECK(detect_wifi_mgmt(frame, n, -48, 11, &r));
  CHECK(r.src == DET_SRC_DJI);
  CHECK(memcmp(r.mac, MAC_DJI, 6) == 0);
  CHECK_STR(r.ssid, "Spark-ABC123");
  CHECK_STR(r.model, "Spark");
  CHECK(r.channel == 11);
  print_json("JSON", &r, 1024);
  print_json("JSON_MESH", &r, 230);

  /* version 2 record: pilot phone position and height */
  l = build_dji_ie(ie, 2);
  CHECK(detect_dji_ie(ie, l, &r));
  CHECK_STR(r.model, "Mavic Mini");
  CHECK(NEAR(r.lat, 34.0522, 1e-5));
  CHECK((r.has & DET_HAS_HEIGHT) && r.height_m == 45);
  CHECK((r.has & DET_HAS_HEADING) && r.heading_deg == 315);
  CHECK(NEAR(r.pilot_lat, 34.0622, 1e-4));
  CHECK(NEAR(r.pilot_lon, -118.2437, 1e-5));
  CHECK(NEAR(r.home_lat, 34.0422, 1e-4));
  CHECK(NEAR(r.home_lon, -118.2537, 1e-4));

  /* too short for telemetry: rejected rather than misread */
  CHECK(!detect_dji_ie(ie, 20, &r));

  /* flight-purpose record (0x11) carries the serial and the user's Drone ID */
  memset(ie, 0, sizeof(ie));
  ie[0] = 0x26; ie[1] = 0x37; ie[2] = 0x12; ie[3] = 0x58; ie[4] = 0x62; ie[5] = 0x13; ie[6] = 0x11;
  memcpy(ie + 7, "0K1DFBK00A1234", 14);
  ie[7 + 16] = 6;
  memcpy(ie + 7 + 17, "REG123", 6);
  ie[7 + 27] = 0;
  CHECK(detect_dji_ie(ie, 7 + 28 + 10, &r));
  CHECK_STR(r.uas_id, "0K1DFBK00A1234");
  CHECK_STR(r.desc, "REG123");
}

/* ------------------------------------------------------------------------ */
/* MAVLink                                                                   */
/* ------------------------------------------------------------------------ */

/* Vectors computed independently with the reference checksum.h code */
static const uint8_t MAV_V2_HEARTBEAT[] = {
  0xfd, 0x09, 0x00, 0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x02, 0x03, 0x81, 0x04, 0x03,
  0x9f, 0xe6 };
static const uint8_t MAV_V1_HEARTBEAT[] = {
  0xfe, 0x09, 0x00, 0x01, 0x01, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x02, 0x03, 0x81, 0x04, 0x03,
  0x05, 0x25 };
static const uint8_t MAV_V2_GLOBAL_POSITION_INT[] = {
  0xfd, 0x1c, 0x00, 0x00, 0x01, 0x01, 0x01, 0x21, 0x00, 0x00,
  0xe8, 0x03, 0x00, 0x00, 0x4c, 0x52, 0x40, 0x1c, 0x44, 0xf4, 0x17, 0x05, 0x40, 0x72, 0x07, 0x00,
  0x10, 0x27, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x28, 0x23,
  0x81, 0x7e };

/* Build a MAVLink 2 frame with this library's CRC (for messages without a vector) */
static int build_mav2(uint8_t *out, uint32_t msgid, uint8_t crc_extra, uint8_t sysid,
                      const uint8_t *payload, int len)
{
  out[0] = 0xFD; out[1] = (uint8_t)len; out[2] = 0; out[3] = 0; out[4] = 0;
  out[5] = sysid; out[6] = 1;
  out[7] = msgid & 0xFF; out[8] = (msgid >> 8) & 0xFF; out[9] = (msgid >> 16) & 0xFF;
  memcpy(out + 10, payload, len);
  uint16_t crc = detect_mavlink_crc(out + 1, 9 + len, crc_extra);
  out[10 + len] = crc & 0xFF;
  out[11 + len] = crc >> 8;
  return 12 + len;
}

/* 802.11 QoS data frame (From-DS) carrying IPv4/UDP or TCP from a bridge AP */
static int build_data_frame(uint8_t *f, bool tcp, bool protected_bit, const uint8_t *sa,
                            const uint8_t *payload, int plen)
{
  memset(f, 0, 600);
  f[0] = 0x88;                                  /* data, QoS data subtype */
  f[1] = protected_bit ? 0x42 : 0x02;           /* From-DS (+ Protected) */
  memset(f + 4, 0xFF, 6);                       /* DA broadcast */
  memcpy(f + 10, sa, 6);                        /* BSSID */
  memcpy(f + 16, sa, 6);                        /* SA */
  int p = 26;                                   /* 24 + QoS control */
  memcpy(f + p, "\xAA\xAA\x03\x00\x00\x00\x08\x00", 8); p += 8;
  uint8_t *ip = f + p;
  int l4len = tcp ? 20 : 8;
  ip[0] = 0x45;
  put_be16(ip + 2, (uint16_t)(20 + l4len + plen));
  put_be16(ip + 4, 0x1234);
  put_be16(ip + 6, 0x4000);                     /* DF, no fragment */
  ip[8] = 64;
  ip[9] = tcp ? 6 : 17;
  memcpy(ip + 12, "\xC0\xA8\x04\x01", 4);
  memcpy(ip + 16, "\xC0\xA8\x04\xFF", 4);
  p += 20;
  uint8_t *l4 = f + p;
  put_be16(l4, tcp ? 5760 : 14550);
  put_be16(l4 + 2, tcp ? 5760 : 14550);
  if (tcp) { l4[12] = 0x50; }                   /* data offset 5 */
  else     { put_be16(l4 + 4, (uint16_t)(8 + plen)); }
  p += l4len;
  memcpy(f + p, payload, plen); p += plen;
  memcpy(f + p, "\xde\xad\xbe\xef", 4);         /* FCS */
  return p + 4;
}

static void test_mavlink(void)
{
  DetectRecord r;
  uint8_t stream[256], frame[600];

  /* checksum against the independent vectors */
  CHECK(detect_mavlink_crc(MAV_V2_HEARTBEAT + 1, 9 + 9, 50) == 0xE69F);
  CHECK(detect_mavlink_crc(MAV_V1_HEARTBEAT + 1, 5 + 9, 50) == 0x2505);
  CHECK(detect_mavlink_crc(MAV_V2_GLOBAL_POSITION_INT + 1, 9 + 28, 104) == 0x7E81);

  /* heartbeat + position in one UDP datagram */
  int n = 0;
  memcpy(stream + n, MAV_V2_HEARTBEAT, sizeof(MAV_V2_HEARTBEAT)); n += sizeof(MAV_V2_HEARTBEAT);
  memcpy(stream + n, MAV_V2_GLOBAL_POSITION_INT, sizeof(MAV_V2_GLOBAL_POSITION_INT)); n += sizeof(MAV_V2_GLOBAL_POSITION_INT);

  detect_record_init(&r);
  CHECK(detect_mavlink_bytes(stream, n, &r));
  CHECK((r.has & DET_HAS_MAV) && r.mav_sysid == 1 && r.mav_type == 2 && r.mav_autopilot == 3 && r.mav_armed == 1);
  CHECK(NEAR(r.lat, 47.3977420, 1e-7));
  CHECK(NEAR(r.lon, 8.5455940, 1e-7));
  CHECK((r.has & DET_HAS_ALT) && r.alt_m == 488);
  CHECK((r.has & DET_HAS_HEIGHT) && r.height_m == 10);
  CHECK((r.has & DET_HAS_HEADING) && r.heading_deg == 90);
  CHECK((r.has & DET_HAS_SPEED) && r.speed_mps == 0);

  /* inside an open-network 802.11 data frame (UDP 14550) */
  int fl = build_data_frame(frame, false, false, MAC_OTHER, stream, n);
  CHECK(detect_wifi_data(frame, fl, -66, 11, &r));
  CHECK(r.src == DET_SRC_MAVLINK);
  CHECK(memcmp(r.mac, MAC_OTHER, 6) == 0);
  CHECK(r.rssi == -66 && r.channel == 11);
  CHECK(NEAR(r.lat, 47.3977420, 1e-7));
  print_json("JSON", &r, 1024);
  print_json("JSON_MESH", &r, 230);

  /* TCP (SITL / mLRS style, port 5760) */
  fl = build_data_frame(frame, true, false, MAC_OTHER, stream, n);
  CHECK(detect_wifi_data(frame, fl, -66, 11, &r));
  CHECK(r.src == DET_SRC_MAVLINK && NEAR(r.lon, 8.5455940, 1e-7));

  /* encrypted frame: nothing to decode */
  fl = build_data_frame(frame, false, true, MAC_OTHER, stream, n);
  CHECK(!detect_wifi_data(frame, fl, -66, 11, &r));

  /* MAVLink 1 heartbeat alone is enough to flag a quadrotor */
  detect_record_init(&r);
  CHECK(detect_mavlink_bytes(MAV_V1_HEARTBEAT, sizeof(MAV_V1_HEARTBEAT), &r));
  CHECK(r.mav_type == 2);

  /* a ground station heartbeat (MAV_TYPE_GCS = 6) is not a drone */
  uint8_t hb[9] = { 0, 0, 0, 0, 6, 8, 0, 4, 3 };
  int l = build_mav2(stream, 0, 50, 255, hb, 9);
  detect_record_init(&r);
  CHECK(!detect_mavlink_bytes(stream, l, &r));

  /* corrupted checksum is rejected */
  memcpy(stream, MAV_V2_HEARTBEAT, sizeof(MAV_V2_HEARTBEAT));
  stream[14] = 0x01;                           /* flip the type byte, keep the CRC */
  detect_record_init(&r);
  CHECK(!detect_mavlink_bytes(stream, sizeof(MAV_V2_HEARTBEAT), &r));

  /* OPEN_DRONE_ID_BASIC_ID + OPERATOR_ID + LOCATION forwarded over MAVLink */
  uint8_t bid[44] = { 0 };
  bid[22] = 1; bid[23] = 2; memcpy(bid + 24, "ABC123SERIAL", 12);
  l = build_mav2(stream, 12900, 114, 7, bid, 44);
  uint8_t opid[43] = { 0 };
  memcpy(opid + 23, "GBR-OP-12345", 12);
  l += build_mav2(stream + l, 12905, 49, 7, opid, 43);
  uint8_t loc[59] = { 0 };
  put_le32(loc + 0, 515073510); put_le32(loc + 4, -1277580);
  { float v = 120.0f; memcpy(loc + 12, &v, 4); v = 80.0f; memcpy(loc + 16, &v, 4); }
  put_le16(loc + 24, 12300);                   /* 123.00 deg */
  put_le16(loc + 26, 1250);                    /* 12.5 m/s */
  loc[52] = 2;
  l += build_mav2(stream + l, 12901, 254, 7, loc, 59);
  detect_record_init(&r);
  CHECK(detect_mavlink_bytes(stream, l, &r));
  CHECK_STR(r.uas_id, "ABC123SERIAL");
  CHECK(r.id_type == 1 && r.ua_type == 2);
  CHECK_STR(r.op_id, "GBR-OP-12345");
  CHECK(NEAR(r.lat, 51.507351, 1e-6) && NEAR(r.lon, -0.127758, 1e-6));
  CHECK(r.alt_m == 120 && r.height_m == 80 && r.heading_deg == 123 && r.speed_mps == 13);
  CHECK(r.status == 2);
  print_json("JSON", &r, 1024);
}

/* ------------------------------------------------------------------------ */
/* Fingerprints, throttle, merge, JSON budget                                */
/* ------------------------------------------------------------------------ */

static void test_fingerprints(void)
{
  uint8_t frame[512];
  DetectRecord r;

  int n = build_mgmt(frame, 0x80, MAC_DJI, "TELLO-A1B2C3", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK(r.src == DET_SRC_WIFI_FP);
  CHECK_STR(r.vendor, "Ryze");
  CHECK_STR(r.model, "Tello");
  CHECK(r.conf == DET_CONF_HIGH && r.role == DET_ROLE_AIRCRAFT);
  CHECK_STR(r.ssid, "TELLO-A1B2C3");
  print_json("JSON", &r, 1024);
  print_json("JSON_MESH", &r, 230);

  /* controller SSID ranks above the aircraft prefix it contains */
  n = build_mgmt(frame, 0x80, MAC_DJI, "Spark-RC-9F3A21", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK_STR(r.model, "Spark RC");
  CHECK(r.role == DET_ROLE_CONTROLLER);

  /* a phone probing for a drone AP: weak hint, flagged as controller */
  n = build_mgmt(frame, 0x40, MAC_OTHER, "spark-123456", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK(r.src == DET_SRC_WIFI_FP && r.conf == DET_CONF_LOW && r.role == DET_ROLE_CONTROLLER);
  CHECK_STR(r.vendor, "DJI");

  /* vendor MAC prefix only */
  n = build_mgmt(frame, 0x80, MAC_DJI, "HomeWiFi", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK(r.src == DET_SRC_WIFI_FP && r.conf == DET_CONF_LOW);
  CHECK_STR(r.vendor, "DJI");
  CHECK_STR(r.ssid, "HomeWiFi");

  /* an ordinary network */
  n = build_mgmt(frame, 0x80, MAC_OTHER, "HomeWiFi", NULL, 0);
  CHECK(!detect_wifi_mgmt(frame, n, -40, 1, &r));

  /* 28-bit (MA-M) and 36-bit (MA-S) registrations are masked, not /24 */
  const uint8_t hubsan[6]     = { 0x98, 0xAA, 0xFC, 0x7A, 0x00, 0x01 };
  const uint8_t not_hubsan[6] = { 0x98, 0xAA, 0xFC, 0x8A, 0x00, 0x01 };
  const uint8_t aeryon[6]     = { 0x70, 0xB3, 0xD5, 0x48, 0x2F, 0x01 };
  const uint8_t ieee_ra[6]    = { 0x70, 0xB3, 0xD5, 0x48, 0x3F, 0x01 };
  CHECK(detect_fingerprint_oui(hubsan, &r) && strcmp(r.vendor, "Hubsan") == 0);
  CHECK(!detect_fingerprint_oui(not_hubsan, &r));
  CHECK(detect_fingerprint_oui(aeryon, &r) && strcmp(r.vendor, "Aeryon") == 0);
  CHECK(!detect_fingerprint_oui(ieee_ra, &r));

  /* more makers than DJI: Yuneec Breeze AP, HDZero goggles */
  n = build_mgmt(frame, 0x80, MAC_OTHER, "Breeze_1A2B3C", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r) && strcmp(r.vendor, "Yuneec") == 0 && r.conf == DET_CONF_HIGH);
  n = build_mgmt(frame, 0x80, MAC_OTHER, "HDZero", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r) && r.role == DET_ROLE_ACCESSORY);

  /* BLE manufacturer data: DJI company ID 0x08AA, no name */
  uint8_t ad3[16];
  int q = 0;
  ad3[q++] = 2; ad3[q++] = 0x01; ad3[q++] = 0x06;
  ad3[q++] = 5; ad3[q++] = 0xFF; ad3[q++] = 0xAA; ad3[q++] = 0x08; ad3[q++] = 0x70; ad3[q++] = 0x00;
  const uint8_t addr3[6] = { 0xC2, 0x00, 0x00, 0x00, 0x00, 0x01 };
  CHECK(detect_ble_adv(addr3, ad3, q, -60, false, &r));
  CHECK(r.src == DET_SRC_BLE_FP && strcmp(r.vendor, "DJI") == 0 && r.conf == DET_CONF_LOW);
  /* Apple's company ID is not a drone */
  ad3[5] = 0x4C; ad3[6] = 0x00;
  CHECK(!detect_ble_adv(addr3, ad3, q, -60, false, &r));

  /* a MAVLink bridge AP is an accessory hint even though its traffic is encrypted */
  n = build_mgmt(frame, 0x80, MAC_OTHER, "ArduPilot", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK(r.role == DET_ROLE_ACCESSORY && r.conf == DET_CONF_MED);

  /* hostile SSID cannot break the JSON */
  n = build_mgmt(frame, 0x80, MAC_DJI, "TELLO-\"},\"mac\":\"x\\", NULL, 0);
  CHECK(detect_wifi_mgmt(frame, n, -40, 1, &r));
  CHECK(strchr(r.ssid, '"') == NULL && strchr(r.ssid, '\\') == NULL);
  print_json("JSON", &r, 1024);
}

static void test_throttle_merge_json(void)
{
  const uint8_t m[6] = { 1, 2, 3, 4, 5, 6 };
  CHECK(detect_throttle(m, 1000, 30000));
  CHECK(!detect_throttle(m, 2000, 30000));
  CHECK(!detect_throttle(m, 30999, 30000));
  CHECK(detect_throttle(m, 31001, 30000));
  CHECK(detect_throttle(m, 31002, 0));

  /* merge: a fingerprint seen after Remote ID must not hide the decode */
  ODID_UAS_Data u;
  make_uas(&u);
  DetectRecord slot, fp;
  detect_record_init(&slot);
  memcpy(slot.mac, MAC_DJI, 6);
  detect_fill_from_odid(&slot, &u);
  slot.src = DET_SRC_ODID_BLE4;
  slot.rssi = -70;

  detect_record_init(&fp);
  memcpy(fp.mac, MAC_DJI, 6);
  fp.src = DET_SRC_WIFI_FP; fp.conf = DET_CONF_LOW; fp.rssi = -42; fp.channel = 6;
  strcpy(fp.vendor, "DJI"); strcpy(fp.ssid, "RID-1581F5FHB229F00202DR");
  detect_record_merge(&slot, &fp);
  CHECK(slot.src == DET_SRC_ODID_BLE4);
  CHECK(slot.conf == DET_CONF_NONE);
  CHECK(slot.rssi == -42 && slot.channel == 6);
  CHECK_STR(slot.vendor, "DJI");
  CHECK(NEAR(slot.lat, 51.507351, 1e-5));

  /* merge: a position-only frame keeps the identity */
  DetectRecord pos;
  detect_record_init(&pos);
  memcpy(pos.mac, MAC_DJI, 6);
  pos.src = DET_SRC_ODID_BLE4; pos.lat = 51.6; pos.lon = -0.2; pos.rssi = -60;
  detect_record_merge(&slot, &pos);
  CHECK_STR(slot.uas_id, "1581F5FHB229F00202DR");
  CHECK(NEAR(slot.lat, 51.6, 1e-9));

  /* JSON budget: everything fits generously ... */
  char buf[1024];
  strcpy(slot.model, "Mavic 3 (QuickTransfer)");
  slot.home_lat = 51.4; slot.home_lon = -0.1;
  slot.has |= DET_HAS_MAV; slot.mav_sysid = 1; slot.mav_type = 2; slot.mav_autopilot = 3;
  int n = detect_build_json(buf, sizeof(buf), &slot, "A1B2");
  CHECK(n > 0 && strstr(buf, "\"home_lat\"") && strstr(buf, "\"autopilot\"") && strstr(buf, "\"desc\""));
  printf("JSON %s\n", buf);
  /* ... a Meshtastic-sized buffer drops the low-priority fields but stays valid ... */
  n = detect_build_json(buf, 230, &slot, "A1B2");
  CHECK(n > 0 && n < 230);
  CHECK(strstr(buf, "\"basic_id\"") && strstr(buf, "\"op_id\"") && strstr(buf, "\"node_id\":\"A1B2\""));
  CHECK(strstr(buf, "\"home_lat\"") == NULL);
  printf("JSON_MESH %s\n", buf);
  /* ... and a buffer too small for the mandatory part fails cleanly */
  CHECK(detect_build_json(buf, 100, &slot, "A1B2") == -1);

  /* heuristic-only record: no node id, no position */
  DetectRecord h;
  detect_record_init(&h);
  memcpy(h.mac, MAC_OTHER, 6);
  h.src = DET_SRC_WIFI_FP; h.conf = DET_CONF_MED; h.role = DET_ROLE_ACCESSORY; h.rssi = -80;
  strcpy(h.vendor, "Parrot"); strcpy(h.model, "ANAFI"); strcpy(h.ssid, "ANAFI-123456");
  n = detect_build_json(buf, 230, &h, NULL);
  CHECK(n > 0 && strstr(buf, "\"node_id\"") == NULL && strstr(buf, "\"drone_lat\"") == NULL);
  printf("JSON_MESH %s\n", buf);

  CHECK(detect_sanitize(buf, 8, "abc\"def\\ghi\x01jkl", 15) == 7);   /* "abcdefg" */
  CHECK_STR(buf, "abcdefg");
}

int main(void)
{
  test_odid_wifi();
  test_odid_ble();
  test_dji();
  test_mavlink();
  test_fingerprints();
  test_throttle_merge_json();
  if (fails) { fprintf(stderr, "%d check(s) FAILED\n", fails); return 1; }
  fprintf(stderr, "all checks passed\n");
  return 0;
}
