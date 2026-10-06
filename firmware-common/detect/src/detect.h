/*
 * detect.h - shared passive drone-detection library for the Drone Sentinel
 *            ESP32 nodes.
 *
 * Pure C: no Arduino or ESP-IDF dependency, so the same code compiles and is
 * unit-tested on a desktop (see ../../test). The ESP32 mains hand raw 802.11
 * frames and BLE advertisements in, get a DetectRecord back, merge it into
 * their per-aircraft slot and serialise it with detect_build_json() for USB
 * and the LoRa mesh.
 *
 * Coverage - all passive, nothing added to the XIAO ESP32 boards:
 *
 *   Open Drone ID (ASTM F3411 / ASD-STAN EN 4709-002 "direct remote ID")
 *     - BLE 4 legacy advertisements (one 25-byte message per advert)
 *     - BLE 5 Long Range extended advertisements (Message Pack, up to 9 msgs)
 *     - WiFi NAN (Neighbor Awareness Networking) action frames
 *     - WiFi Beacon vendor-specific IE (OUI FA:0B:BC, and 90:3A:E6 as used by
 *       early Parrot firmware)
 *     Every message type is decoded: both Basic IDs (e.g. serial number AND a
 *     national registration ID), Location, System (operator position, EU
 *     class/category), Operator ID (the EU/UK registration number) and
 *     Self ID (free text), not just the US-centric subset.
 *
 *   DJI proprietary "DroneID" vendor IE (OUI 26:37:12) in the beacons of
 *   WiFi-link DJI aircraft (Spark, Mavic Pro in WiFi mode, Mavic Air, Mavic
 *   Mini / Mini SE): serial, aircraft position, home point, pilot phone
 *   position (v2), model code. Broadcast worldwide, independent of Remote ID.
 *
 *   MAVLink v1/v2 telemetry on OPEN (unencrypted) WiFi: UDP or TCP inside
 *   802.11 data frames. HEARTBEAT, GLOBAL_POSITION_INT, GPS_RAW_INT,
 *   HOME_POSITION and the OPEN_DRONE_ID_* message set. Encrypted (WPA2)
 *   networks cannot be decoded; those are caught by the fingerprint layer.
 *
 *   WiFi / BLE fingerprints for aircraft and controllers that broadcast no
 *   Remote ID at all: SSID patterns of drone access points (DJI, Ryze, Parrot,
 *   Autel, Hubsan, toy quads, FPV goggles, MAVLink WiFi bridges ...), vendor
 *   MAC prefixes (IEEE OUIs) and BLE device names. These are heuristics and
 *   are reported with a confidence level and never with a position.
 *
 * Thread-safety: detect_wifi_mgmt()/detect_wifi_data() share one static
 * Open Drone ID scratch structure and detect_ble_adv() another, so each of
 * the two groups must be called from a single task (the WiFi promiscuous
 * callback and the BLE scan callback respectively), which is how the mains
 * use them.
 */
#ifndef DETECT_H
#define DETECT_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "opendroneid.h"

#ifdef __cplusplus
extern "C" {
#endif

#define DETECT_VENDOR_LEN 15
#define DETECT_MODEL_LEN  23
#define DETECT_SSID_LEN   32

/* How the aircraft was seen. Serialised as the JSON "src" field. */
typedef enum DetectSource {
  DET_SRC_NONE = 0,
  DET_SRC_ODID_BLE4,    /* "odid_ble"  Remote ID, BLE 4 legacy advertisement   */
  DET_SRC_ODID_BLE5,    /* "odid_ble5" Remote ID, BLE 5 Long Range ext. advert */
  DET_SRC_ODID_NAN,     /* "odid_nan"  Remote ID, WiFi NAN action frame        */
  DET_SRC_ODID_BEACON,  /* "odid_bcn"  Remote ID, WiFi Beacon vendor IE        */
  DET_SRC_DJI,          /* "dji"       DJI DroneID vendor IE (WiFi beacon)     */
  DET_SRC_MAVLINK,      /* "mavlink"   MAVLink telemetry on an open WiFi net   */
  DET_SRC_WIFI_FP,      /* "wifi"      heuristic: SSID / MAC-prefix match      */
  DET_SRC_BLE_FP,       /* "ble"       heuristic: BLE device-name match        */
} DetectSource;

/* Confidence of a heuristic match. Decoded protocols leave it at NONE. */
typedef enum DetectConf {
  DET_CONF_NONE = 0,
  DET_CONF_LOW,         /* vendor MAC prefix only, or a probe request        */
  DET_CONF_MED,         /* SSID pattern of a controller / accessory / bridge */
  DET_CONF_HIGH,        /* SSID pattern of an aircraft access point          */
} DetectConf;

/* What kind of device a fingerprint points at. */
typedef enum DetectRole {
  DET_ROLE_UNKNOWN = 0,
  DET_ROLE_AIRCRAFT,
  DET_ROLE_CONTROLLER,  /* remote controller, phone probing for a drone AP   */
  DET_ROLE_ACCESSORY,   /* goggles, gimbal camera, telemetry bridge          */
} DetectRole;

/* Which optional numeric fields of a DetectRecord hold a value. */
enum {
  DET_HAS_ALT     = 1 << 0,
  DET_HAS_HEIGHT  = 1 << 1,
  DET_HAS_SPEED   = 1 << 2,
  DET_HAS_HEADING = 1 << 3,
  DET_HAS_STATUS  = 1 << 4,
  DET_HAS_UATYPE  = 1 << 5,
  DET_HAS_EU      = 1 << 6,
  DET_HAS_MAV     = 1 << 7,
};

typedef struct DetectRecord {
  uint8_t  mac[6];
  int8_t   rssi;
  uint8_t  channel;        /* WiFi channel, 0 for BLE / unknown            */
  uint8_t  src;            /* DetectSource                                 */
  uint8_t  conf;           /* DetectConf (heuristics only)                 */
  uint8_t  role;           /* DetectRole (heuristics / DJI)                */
  uint16_t has;            /* DET_HAS_* bits                               */
  uint32_t last_seen;      /* caller's millisecond clock                   */

  double   lat, lon;             /* aircraft; 0/0 = unknown                */
  double   pilot_lat, pilot_lon; /* operator / pilot phone; 0/0 = unknown  */
  double   home_lat, home_lon;   /* take-off / home point; 0/0 = unknown   */
  int32_t  alt_m;          /* geodetic (WGS84) or MSL altitude, metres     */
  int32_t  height_m;       /* above take-off or ground, metres             */
  int16_t  speed_mps;      /* horizontal speed, m/s                        */
  int16_t  heading_deg;    /* 0..359                                       */
  uint8_t  status;         /* ODID_status_t                                */

  char     uas_id[ODID_ID_SIZE + 1];   /* Basic ID #1                      */
  uint8_t  id_type;                    /* ODID_idtype_t of uas_id          */
  char     uas_id2[ODID_ID_SIZE + 1];  /* Basic ID #2 (e.g. registration)  */
  uint8_t  id_type2;
  uint8_t  ua_type;                    /* ODID_uatype_t                    */
  char     op_id[ODID_ID_SIZE + 1];    /* Operator ID (EU/UK registration) */
  char     desc[ODID_STR_SIZE + 1];    /* Self ID text / DJI "Drone ID"    */
  uint8_t  eu_cat, eu_class;           /* ODID_category_EU_t / class_EU_t  */

  char     vendor[DETECT_VENDOR_LEN + 1];
  char     model[DETECT_MODEL_LEN + 1];
  char     ssid[DETECT_SSID_LEN + 1];

  uint8_t  mav_sysid, mav_type, mav_autopilot, mav_armed;
} DetectRecord;

/* ---- lifecycle / labels ------------------------------------------------ */
void        detect_record_init(DetectRecord *r);
const char *detect_source_str(uint8_t src);
const char *detect_conf_str(uint8_t conf);
const char *detect_role_str(uint8_t role);
bool        detect_is_heuristic(uint8_t src);

/* ---- entry points for the radio callbacks ------------------------------ */

/* 802.11 management frame (beacon, probe request/response, action).
 * `len` is the bytes available from frame[0] (= frame control); a trailing
 * FCS is tolerated. Returns true when `out` holds a detection. */
bool detect_wifi_mgmt(const uint8_t *frame, int len, int rssi, uint8_t channel,
                      DetectRecord *out);

/* 802.11 data frame: MAVLink inside UDP/TCP on an unencrypted network.
 * Cheap early rejects (protected bit, non-IPv4) make it safe to call for
 * every data frame the sniffer delivers. */
bool detect_wifi_data(const uint8_t *frame, int len, int rssi, uint8_t channel,
                      DetectRecord *out);

/* BLE advertising payload (sequence of AD structures). `extended` marks a
 * BLE 5 extended advertising report (Long Range / message pack). */
bool detect_ble_adv(const uint8_t addr[6], const uint8_t *ad, int len, int rssi,
                    bool extended, DetectRecord *out);

/* ---- aggregation / output --------------------------------------------- */

/* Copy every field `from` carries into `into` (identity, position, radio
 * metadata). A heuristic source never downgrades a decoded one. */
void detect_record_merge(DetectRecord *into, const DetectRecord *from);

/* One-line JSON for mesh-mapper.py. Mandatory fields are always written;
 * optional fields are added in priority order only while they fit, so the
 * result is always complete JSON that fits `bufsize` (pass ~230 for a
 * Meshtastic text message, something larger for USB). Returns the length,
 * or -1 if even the mandatory part does not fit. */
int  detect_build_json(char *buf, size_t bufsize, const DetectRecord *r,
                       const char *node_id);

/* Per-MAC rate limit for heuristic hits (beacons repeat ~10x per second).
 * Returns true when this MAC has not been passed through within
 * `min_interval_ms`; an interval of 0 always passes. */
bool detect_throttle(const uint8_t mac[6], uint32_t now_ms, uint32_t min_interval_ms);

/* Copy `src` (up to srclen bytes) into dst keeping only characters that are
 * safe inside a JSON string on a LoRa link: printable ASCII minus '"' and
 * '\\'. Always NUL-terminates. Returns the number of characters kept. */
int  detect_sanitize(char *dst, size_t dstsize, const char *src, size_t srclen);

/* ---- building blocks (exposed for the unit tests) ---------------------- */
void        detect_fill_from_odid(DetectRecord *r, const ODID_UAS_Data *uas);
bool        detect_dji_ie(const uint8_t *ie, int ie_len, DetectRecord *out);
const char *detect_dji_product_name(uint8_t code);
bool        detect_mavlink_bytes(const uint8_t *buf, int len, DetectRecord *out);
uint16_t    detect_mavlink_crc(const uint8_t *buf, int len, uint8_t crc_extra);
bool        detect_fingerprint_ssid(const char *ssid, DetectRecord *out);
bool        detect_fingerprint_oui(const uint8_t mac[6], DetectRecord *out);
bool        detect_fingerprint_ble_name(const char *name, DetectRecord *out);
bool        detect_fingerprint_ble_company(uint16_t company, DetectRecord *out);

#ifdef __cplusplus
}
#endif

#endif /* DETECT_H */
