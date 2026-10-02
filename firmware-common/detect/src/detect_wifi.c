/*
 * detect_wifi.c - 802.11 frame parsing.
 *
 *   detect_wifi_mgmt(): beacons / probe responses / probe requests / NAN
 *     action frames -> Open Drone ID, DJI DroneID, SSID & OUI fingerprints
 *   detect_wifi_data(): unencrypted data frames -> LLC/SNAP -> IPv4 ->
 *     UDP/TCP -> MAVLink
 *
 * Frame layout reminders (payload[0] is the Frame Control byte):
 *   fc0 bits 2-3 type (0 mgmt, 2 data), bits 4-7 subtype
 *   fc1 0x01 ToDS, 0x02 FromDS, 0x04 MoreFrag, 0x40 Protected, 0x80 Order
 *   mgmt header 24 bytes: FC(2) Dur(2) A1(6) A2(6) A3(6) Seq(2); beacon and
 *   probe response then carry 12 fixed bytes before the IEs, a probe request
 *   starts its IEs right after the header.
 */
#include <string.h>
#include "detect.h"
#include "odid_wifi.h"

static ODID_UAS_Data s_uas_wifi;

static const uint8_t NAN_DEST[6]   = { 0x51, 0x6F, 0x9A, 0x01, 0x00, 0x00 };
static const uint8_t OUI_ASD_STAN[3] = { 0xFA, 0x0B, 0xBC };   /* ASTM / ASD-STAN Remote ID */
static const uint8_t OUI_PARROT[3]   = { 0x90, 0x3A, 0xE6 };   /* early Parrot Remote ID beacons */
static const uint8_t OUI_DJI_IE[3]   = { 0x26, 0x37, 0x12 };   /* DJI DroneID (not an IEEE OUI) */
static const uint8_t SNAP_IPV4[8]    = { 0xAA, 0xAA, 0x03, 0x00, 0x00, 0x00, 0x08, 0x00 };

static inline uint16_t be16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }

/* ------------------------------------------------------------------------ */
/* Management frames                                                         */
/* ------------------------------------------------------------------------ */

bool detect_wifi_mgmt(const uint8_t *f, int n, int rssi, uint8_t channel, DetectRecord *out)
{
  if (n < 24) return false;
  uint8_t fc0 = f[0];
  if ((fc0 & 0x03) != 0) return false;          /* protocol version must be 0 */
  if (((fc0 >> 2) & 0x03) != 0) return false;   /* management frames only */
  uint8_t subtype = fc0 >> 4;
  const uint8_t *sa = f + 10;                   /* transmitter / source address */

  /* ---- NAN action frame (Remote ID over WiFi Aware) ---- */
  if (subtype == 0x0D) {
    if (memcmp(f + 4, NAN_DEST, 6) != 0) return false;
    char mac_scratch[6];
    /* Zero first: a frame missing a message type must not inherit stale
     * fields from the previous frame. */
    memset(&s_uas_wifi, 0, sizeof(s_uas_wifi));
    if (odid_wifi_receive_message_pack_nan_action_frame(&s_uas_wifi, mac_scratch,
                                                        (uint8_t *)f, (size_t)n) != 0)
      return false;
    detect_record_init(out);
    memcpy(out->mac, sa, 6);
    out->rssi = (int8_t)rssi;
    out->channel = channel;
    detect_fill_from_odid(out, &s_uas_wifi);
    out->src = DET_SRC_ODID_NAN;
    return true;
  }

  int off;
  if (subtype == 0x08 || subtype == 0x05) off = 36;      /* beacon, probe response */
  else if (subtype == 0x04)               off = 24;      /* probe request */
  else return false;

  char ssid[DETECT_SSID_LEN + 1] = "";
  bool got = false;

  while (off + 2 <= n) {
    int id = f[off], l = f[off + 1];
    if (off + 2 + l > n) break;                 /* truncated IE (or we hit the FCS) */
    const uint8_t *d = f + off + 2;

    if (id == 0x00 && l <= DETECT_SSID_LEN) {
      detect_sanitize(ssid, sizeof(ssid), (const char *)d, (size_t)l);
    } else if (id == 0xDD && l >= 4 && !got) {
      if (memcmp(d, OUI_ASD_STAN, 3) == 0 || memcmp(d, OUI_PARROT, 3) == 0) {
        /* [oui 3][type 1][message counter 1][message pack ...] */
        if (l > 5 + 3) {
          memset(&s_uas_wifi, 0, sizeof(s_uas_wifi));
          if (odid_message_process_pack(&s_uas_wifi, (uint8_t *)d + 5, (size_t)(l - 5)) > 0) {
            detect_record_init(out);
            memcpy(out->mac, sa, 6);
            detect_fill_from_odid(out, &s_uas_wifi);
            out->src = DET_SRC_ODID_BEACON;
            got = true;
          }
        }
      } else if (memcmp(d, OUI_DJI_IE, 3) == 0) {
        if (detect_dji_ie(d, l, out)) {
          memcpy(out->mac, sa, 6);
          got = true;
        }
      }
    }
    off += 2 + l;
  }

  if (got) {
    out->rssi = (int8_t)rssi;
    out->channel = channel;
    /* The network name is only worth its airtime when it adds identity:
     * for DJI DroneID it names the aircraft (Spark-XXXXXX); a Remote ID
     * beacon's SSID just repeats the serial. */
    if (out->src == DET_SRC_DJI && ssid[0])
      detect_sanitize(out->ssid, sizeof(out->ssid), ssid, strlen(ssid));
    return true;
  }

  /* ---- no protocol decoded: fingerprint the network ---- */
  detect_record_init(out);
  memcpy(out->mac, sa, 6);
  out->rssi = (int8_t)rssi;
  out->channel = channel;

  if (subtype == 0x04) {
    /* Probe request: a phone or controller looking for a drone's AP. The
     * device probing is not the aircraft, so this is only a weak hint. */
    if (ssid[0] && detect_fingerprint_ssid(ssid, out)) {
      out->src = DET_SRC_WIFI_FP;
      out->conf = DET_CONF_LOW;
      out->role = DET_ROLE_CONTROLLER;
      detect_sanitize(out->ssid, sizeof(out->ssid), ssid, strlen(ssid));
      return true;
    }
    return false;
  }

  if (ssid[0] && detect_fingerprint_ssid(ssid, out)) {
    out->src = DET_SRC_WIFI_FP;
    detect_sanitize(out->ssid, sizeof(out->ssid), ssid, strlen(ssid));
    return true;
  }
  if (detect_fingerprint_oui(sa, out)) {
    out->src = DET_SRC_WIFI_FP;
    if (ssid[0]) detect_sanitize(out->ssid, sizeof(out->ssid), ssid, strlen(ssid));
    return true;
  }
  return false;
}

/* ------------------------------------------------------------------------ */
/* Data frames -> MAVLink                                                    */
/* ------------------------------------------------------------------------ */

bool detect_wifi_data(const uint8_t *f, int n, int rssi, uint8_t channel, DetectRecord *out)
{
  if (n < 24 + 8 + 20 + 8 + 8) return false;    /* MAC + SNAP + IPv4 + UDP + smallest MAVLink */
  uint8_t fc0 = f[0], fc1 = f[1];
  if ((fc0 & 0x03) != 0) return false;          /* version */
  if (((fc0 >> 2) & 0x03) != 2) return false;   /* data frames only */
  if (fc0 & 0x40) return false;                 /* null-data subtype: no body */
  if (fc1 & 0x40) return false;                 /* Protected: WPA/WPA2/WPA3 ciphertext */
  if (fc1 & 0x04) return false;                 /* fragmented */

  int hdr = 24;
  int ds = fc1 & 0x03;
  if (ds == 3) hdr += 6;                        /* 4-address (WDS) */
  const uint8_t *qos = NULL;
  if (fc0 & 0x80) {                             /* QoS data subtypes */
    qos = f + hdr;
    hdr += 2;
    if (fc1 & 0x80) hdr += 4;                   /* +HTC */
  }
  if (hdr + 8 + 20 > n) return false;
  if (qos && (qos[0] & 0x80)) return false;     /* A-MSDU aggregate: skip */

  /* Original source of the frame = the radio on the drone side (or the
   * telemetry bridge / ground unit that carries the aircraft's MAVLink). */
  const uint8_t *a2 = f + 10, *a3 = f + 16, *a4 = f + 24;
  const uint8_t *sa = (ds == 3) ? a4 : (ds & 2) ? a3 : a2;

  if (memcmp(f + hdr, SNAP_IPV4, 8) != 0) return false;
  const uint8_t *ip = f + hdr + 8;
  int ihl = (ip[0] & 0x0F) * 4;
  if ((ip[0] >> 4) != 4 || ihl < 20) return false;
  if (be16(ip + 6) & 0x3FFF) return false;      /* IP fragment */
  int iptot = be16(ip + 2);
  if (iptot < ihl || (int)(ip - f) + iptot > n) return false;

  const uint8_t *l4 = ip + ihl;
  const uint8_t *payload;
  int plen;
  if (ip[9] == 17) {                            /* UDP */
    if (iptot < ihl + 8) return false;
    int ul = be16(l4 + 4);
    if (ul < 8 || ul > iptot - ihl) return false;
    payload = l4 + 8;
    plen = ul - 8;
  } else if (ip[9] == 6) {                      /* TCP */
    if (iptot < ihl + 20) return false;
    int doff = (l4[12] >> 4) * 4;
    if (doff < 20 || iptot < ihl + doff) return false;
    payload = l4 + doff;
    plen = iptot - ihl - doff;
  } else {
    return false;
  }
  if (plen < 8) return false;
  if (payload[0] != 0xFD && payload[0] != 0xFE) return false;   /* cheap MAVLink STX pre-filter */

  detect_record_init(out);
  memcpy(out->mac, sa, 6);
  out->rssi = (int8_t)rssi;
  out->channel = channel;
  if (!detect_mavlink_bytes(payload, plen, out)) return false;
  out->src = DET_SRC_MAVLINK;
  return true;
}
