# Passive MAVLink-over-WiFi detection on ESP32 — implementation reference

Scope: an ESP32 (XIAO ESP32-S3 / C3 / C5) in 802.11 promiscuous mode wants to find MAVLink
telemetry inside plaintext UDP/TCP packets on OPEN WiFi networks and extract vehicle identity and
position. Everything below is written against primary sources (MAVLink guide pages, the raw XML,
the generated C headers in `mavlink/c_library_v2`, ESP-IDF headers/docs, vendor docs). Values
that were NOT verifiable from a primary source are explicitly marked `[unverified]`.

Research date: 2026-10-02.

---

## 0. Sources used

MAVLink protocol
- S1 https://mavlink.io/en/guide/serialization.html (frame layouts, flags, CRC coverage, truncation, reordering)
- S2 https://mavlink.io/en/guide/message_signing.html (13-byte signature layout)
- S3 https://mavlink.io/en/guide/mavlink_version.html (0xFE vs 0xFD)
- S4 https://raw.githubusercontent.com/mavlink/c_library_v2/master/checksum.h (exact CRC code)
- S5 https://raw.githubusercontent.com/mavlink/c_library_v2/master/mavlink_types.h (core constants, msg_entry struct)
- S6 https://raw.githubusercontent.com/mavlink/c_library_v2/master/mavlink_helpers.h (parser: STX, incompat check, crc_extra, zero-fill)
- S7 https://raw.githubusercontent.com/mavlink/c_library_v2/master/common/common.h (`MAVLINK_MESSAGE_CRCS` table: msgid, crc_extra, min_len, max_len, flags, target ofs)
- S8 generated headers: `minimal/mavlink_msg_heartbeat.h`, `common/mavlink_msg_sys_status.h`, `mavlink_msg_gps_raw_int.h`,
  `mavlink_msg_attitude.h`, `mavlink_msg_home_position.h`, `mavlink_msg_open_drone_id_{basic_id,location,self_id,system,operator_id,message_pack,arm_status,system_update}.h`
  under https://raw.githubusercontent.com/mavlink/c_library_v2/master/ (struct order + `_mav_put_*` offsets + `_LEN/_MIN_LEN/_CRC`)
  NOTE: `common/mavlink_msg_global_position_int.h` returned HTTP 404 from every mirror tried during this session
  (raw.githubusercontent.com, jsDelivr, github.com/raw, c_library_v1). Its constants come from S7 (`{33, 104, 28, 28, 0, 0, 0}`),
  the XML-derived generator file https://raw.githubusercontent.com/dronefleet/mavlink/master/src/main/java-gen/io/dronefleet/mavlink/common/GlobalPositionInt.java
  (`id = 33, crc = 104`, field positions/sizes) and the mavlink.io field table (units).
- S9 https://raw.githubusercontent.com/mavlink/mavlink/master/message_definitions/v1.0/minimal.xml (MAV_TYPE, MAV_AUTOPILOT, MAV_MODE_FLAG, MAV_STATE, HEARTBEAT XML order)
- S10 https://mavlink.io/en/messages/common.html (field tables with units; page is huge and the fetcher truncates it, so enums were taken from S11)
- S11 XML-derived generator files https://raw.githubusercontent.com/dronefleet/mavlink/master/src/main/java-gen/io/dronefleet/mavlink/common/{MavOdidIdType,MavOdidUaType,MavOdidStatus,MavOdidHeightRef,MavOdidOperatorLocationType,MavOdidArmStatus,MavOdidDescType,MavOdidOperatorIdType,GpsFixType}.java
  cross-checked against ASTM/opendroneid-core-c https://raw.githubusercontent.com/opendroneid/opendroneid-core-c/master/libopendroneid/opendroneid.h (identical numeric values)
- S12 https://mavlink.io/en/services/opendroneid.html (ODID message set, id_or_mac semantics, MESSAGE_PACK)

WiFi bridges / ports
- W1 https://ardupilot.org/copter/docs/common-esp8266-telemetry.html
- W2 https://docs.px4.io/main/en/telemetry/esp8266_wifi_module.html
- W3 mavesp8266 sources: https://raw.githubusercontent.com/dogmaphobic/mavesp8266/master/src/mavesp8266.h, `.../src/mavesp8266_parameters.cpp`, `.../src/mavesp8266_gcs.cpp`, `.../PARAMETERS.md`; ArduPilot fork `https://raw.githubusercontent.com/ArduPilot/mavesp8266/master/src/mavesp8266_parameters.cpp`
- W4 DroneBridge for ESP32: https://raw.githubusercontent.com/DroneBridge/ESP32/master/README.md, https://ardupilot.org/plane/docs/common-esp32-telemetry.html, https://docs.px4.io/main/en/telemetry/esp32_wifi_module.html, wiki https://github.com/DroneBridge/ESP32/wiki/Configuration (via search)
- W5 https://docs.px4.io/main/en/telemetry/telemetry_wifi.html (PX4 broadcasts heartbeat to 255.255.255.255:14550 until a GCS answers)
- W6 https://docs.px4.io/main/en/simulation/ (SITL ports 14550/14540/4560/14580/18570)
- W7 https://docs.px4.io/main/en/peripherals/mavlink_peripherals.html (MAV_X_REMOTE_PRT default 14550, MAV_X_BROADCAST)
- W8 https://ardupilot.org/copter/docs/common-network.html (NET_P1_* ; broadcast if IP 255.255.255.255; default IP 192.168.144.14)
- W9 https://ardupilot.org/dev/docs/sitl-serial-mapping.html (SITL TCP 5760/5762/5763)
- W10 https://ardupilot.org/planner/docs/common-connect-mission-planner-autopilot.html (`udp://127.0.0.1:14550`, `udpcl://192.168.1.255:14550`, TCP option)
- W11 https://ardupilot.org/mavproxy/docs/getting_started/forwarding.html (`--out 127.0.0.1:14550`)
- W12 https://www.expresslrs.org/software/mavlink/ (TX Backpack WiFi AP, password "expresslrs", 10.0.0.1, UDP 14550)
- W13 mLRS wireless bridge: https://raw.githubusercontent.com/olliw42/mLRS/main/esp/mlrs-wireless-bridge/mlrs-wireless-bridge.ino and https://raw.githubusercontent.com/olliw42/mLRS-docu/master/docs/WIRELESS_BRIDGE.md (OPEN AP by default, 192.168.4.55, UDP 14550, TCP 5760)
- W14 https://ardupilot.org/plane/docs/common-cuav-pwlink.html (CUAVWLINKxxxx / cuavwlink, 192.168.4.1, UDP 14550)
- W15 Skydroid H16 Interface Manual V1.0 (PDF) https://discuss.ardupilot.org/uploads/short-url/ubx1oYhnTDStvoPhr3Jy5MamLU2.pdf (hotspot 192.168.43.1, UDP 14550)
- W16 Herelink: https://docs.cubepilot.org/herelink/herelink-user-guides/connect-to-mission-planner.md (UDP 14550 on hotspot, UDPCL 14552 otherwise, "broadcast from the WiFi access point by default")
- W17 SIYI MK15/HM30 user manuals (via search summaries of the official PDFs): UDP 19856 at 192.168.144.12 `[unverified: not read from the PDF directly]`
- W18 Parrot: KTH thesis via search (ANAFI WPA2 + PMF, AR.Drone 2.0 open), support.com / parrotpilots via search (Bebop 2 open by default), PX4 forum (ANAFI USA "MAVLink v1 compatible") `[secondary sources]`
- W19 Betaflight MAVLink: https://betaflight.com/docs/wiki/guides/current/MAVLinkELRS ; INAV: https://raw.githubusercontent.com/iNavFlight/inav/master/docs/Telemetry.md
- W20 DIY ESP8266 bridges: https://blog.quadmeup.com/wifi-telemetry-for-cleanflight-with-ez-gui-and-esp8266/ (ESP8266-transparent-bridge, AP "ESP_xxxxx", 192.168.4.1, TCP 23)
- W21 Yuneec H520: https://yuneecpilots.com/threads/streaming-telemetry-without-a-camera.21829/ (MAVLink over 5 GHz WiFi) `[secondary]`

802.11 / IP / ESP-IDF
- E1 https://www.rfc-editor.org/rfc/rfc1042 (LLC/SNAP for IP: DSAP/SSAP 0xAA, ctrl 0x03, OUI 0, EtherType 0x0800; 8 bytes)
- E2 https://en.wikipedia.org/wiki/IEEE_802.11 and https://en.wikipedia.org/wiki/802.11_frame_types (FC bit layout, address table, header field sizes, FCS)
  (authoritative text is IEEE 802.11-2020 §9.2.4 / Table 9-30 — not fetchable without IEEE login)
- E3 https://raw.githubusercontent.com/espressif/esp-idf/master/components/esp_wifi/include/esp_wifi_types_generic.h (wifi_promiscuous_pkt_type_t, filter masks)
- E4 https://raw.githubusercontent.com/espressif/esp-idf/master/components/esp_wifi/include/local/esp_wifi_types_native.h (wifi_pkt_rx_ctrl_t for ESP32/S2/S3/C2/C3, wifi_promiscuous_pkt_t)
- E5 https://raw.githubusercontent.com/espressif/esp-idf/master/components/esp_wifi/include/esp_wifi_he_types.h (esp_wifi_rxctrl_t used on HE targets C5/C6/C61)
- E6 https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/wifi-driver/wifi-modes.html ("Wi-Fi Sniffer Mode")
- E7 https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_wifi.html (esp_wifi_set_promiscuous*, default filter note)

---

## 1. MAVLink frame layouts

### 1.1 MAVLink 1 (STX 0xFE) — S1, S3, S5

| byte | field | notes |
|---|---|---|
| 0 | `magic` = **0xFE** | `MAVLINK_STX_MAVLINK1` |
| 1 | `len` | payload length 0..255 (v1 payloads are never truncated) |
| 2 | `seq` | 0..255 |
| 3 | `sysid` | 1..255 |
| 4 | `compid` | 1..255 |
| 5 | `msgid` | 8-bit; v1 can only carry msgid 0..255 (so no ODID messages) |
| 6..5+len | payload | |
| 6+len, 7+len | `checksum` | uint16 **little-endian** (low byte first), CRC-16/MCRF4XX incl. CRC_EXTRA |

Min frame 8 bytes, max 263. `MAVLINK_CORE_HEADER_MAVLINK1_LEN 5`.

### 1.2 MAVLink 2 (STX 0xFD) — S1, S2, S5

| byte | field | notes |
|---|---|---|
| 0 | `magic` = **0xFD** | |
| 1 | `len` | payload length 0..255 AFTER zero-truncation |
| 2 | `incompat_flags` | bit0 = `MAVLINK_IFLAG_SIGNED 0x01` → 13-byte signature appended. "A MAVLink implementation must discard a packet if it does not understand any flag" (S1). Current c_library_v2 defines `MAVLINK_IFLAG_MASK 0x07` (bits 1,2 reserved for header-extension experiments, see `MAVLINK_MAX_EXT_HEADER_BYTES` in S5). **Sniffer rule: if `incompat_flags & ~0x01` → drop.** |
| 3 | `compat_flags` | may be ignored |
| 4 | `seq` | |
| 5 | `sysid` | |
| 6 | `compid` | |
| 7,8,9 | `msgid` | **24-bit little-endian**: `msgid = b[7] | b[8]<<8 | b[9]<<16` ("low, middle, high bytes") |
| 10..9+len | payload | |
| 10+len, 11+len | `checksum` | uint16 LE, CRC-16/MCRF4XX over bytes 1..9+len then CRC_EXTRA |
| 12+len .. 24+len | `signature[13]` | only if `incompat_flags & 0x01` |

Constants (S5): `MAVLINK_CORE_HEADER_LEN 9`, `MAVLINK_NUM_HEADER_BYTES 10`, `MAVLINK_NUM_CHECKSUM_BYTES 2`,
`MAVLINK_NUM_NON_PAYLOAD_BYTES 12`, `MAVLINK_SIGNATURE_BLOCK_LEN 13`, `MAVLINK_MAX_PAYLOAD_LEN 255`,
max packet = 255+12+13 = **280** bytes (S1), min 12.

Signature block (S2): `link_id` (1 byte) | `timestamp` (6 bytes LE, 10 µs units since 2015-01-01 GMT) | `signature` (6 bytes = first 48 bits of SHA-256(secret_key + header + payload + CRC + link_id + timestamp)).
The CRC does **not** cover the signature ("The CRC covers the whole message, excluding magic byte and the signature (if present)", S1).
A sniffer can't verify signatures (no key) — just skip the 13 bytes; signed frames still have a valid CRC.

### 1.3 Payload truncation (MAVLink 2 only) — S1, S6

- Sender MUST strip trailing 0x00 bytes of the serialized payload; "The first byte of the payload is never truncated, even if the payload consists entirely of zeros." So `len` may be anything from 1 to the message's max length.
- Receiver MUST zero-fill. c_library_v2 does exactly: `memset(&payload[packet_idx], 0, fill_len - packet_idx)` with `fill_len = min(e->max_msg_len, 255)` (S6).
- Validity window: accept `1 <= len <= max_len` (c_library_v2 only checks `min_msg_len/max_msg_len` when `MAVLINK_CHECK_MESSAGE_LENGTH` is defined; a sniffer should simply reject `len > max_len`, zero-fill, then decode fixed offsets).
- Practical consequence: e.g. `OPEN_DRONE_ID_SYSTEM_UPDATE` with `target_system=target_component=0` arrives with `len=16`, not 18; HEARTBEAT with `custom_mode=0` still has `len=9` because `mavlink_version=3` is the last byte.

### 1.4 Field reordering (why wire order differs from XML) — S1

Fields are sorted by size, descending (8-byte, 4-byte, 2-byte, 1-byte; stable within equal sizes); **MAVLink-2 extension fields are appended in XML order, after the sorted base fields, and are excluded from CRC_EXTRA**. The wire orders in §3 are taken from the generated C structs/`_mav_put_*` offsets, so no reordering needs to be done by hand.

### 1.5 Minimal parser logic (v1 + v2, UDP datagram = one or more complete frames)

```c
// returns bytes consumed (0 = need resync/scan forward)
static size_t mav_try_frame(const uint8_t *b, size_t n, mav_frame_t *out)
{
    if (n < 8) return 0;
    uint8_t stx = b[0];
    size_t hdr, len, msgid, sig = 0;
    if (stx == 0xFD) {
        if (n < 12) return 0;
        len = b[1];
        uint8_t iflags = b[2];
        if (iflags & ~0x01u) return 0;          // unknown incompat flag -> discard (S1)
        if (iflags & 0x01u) sig = 13;
        msgid = b[7] | (b[8] << 8) | ((uint32_t)b[9] << 16);
        hdr = 10;
    } else if (stx == 0xFE) {
        len = b[1]; msgid = b[5]; hdr = 6;
    } else return 0;
    size_t total = hdr + len + 2 + sig;
    if (n < total) return 0;
    const mav_entry_t *e = mav_lookup(msgid);     // table in §3
    if (!e || len > e->max_len) return 0;
    uint16_t crc = 0xFFFF;
    for (size_t i = 1; i < hdr + len; i++) crc = crc_accumulate(b[i], crc);
    crc = crc_accumulate(e->crc_extra, crc);
    if (crc != (uint16_t)(b[hdr+len] | (b[hdr+len+1] << 8))) return 0;
    memset(out->payload, 0, sizeof out->payload);
    memcpy(out->payload, &b[hdr], len);          // zero-filled to max_len
    out->sysid = (stx == 0xFD) ? b[5] : b[3];
    out->compid = (stx == 0xFD) ? b[6] : b[4];
    out->msgid = msgid;
    return total;
}
```
Scan a UDP payload with `for (off=0; off<n;) { c = mav_try_frame(b+off, n-off, &f); off += c ? c : 1; }`.
For TCP (5760) the stream is not datagram-aligned: keep a small per-flow carry-over buffer (≤280 bytes) or accept losing straddling frames.

---

## 2. Checksum — CRC-16/MCRF4XX ("X.25") + CRC_EXTRA

Exact code from `c_library_v2/checksum.h` (S4):

```c
#define X25_INIT_CRC 0xffff
#define X25_VALIDATE_CRC 0xf0b8

static inline void crc_accumulate(uint8_t data, uint16_t *crcAccum)
{
        uint8_t tmp;
        tmp = data ^ (uint8_t)(*crcAccum & 0xff);
        tmp ^= (tmp << 4);
        *crcAccum = (*crcAccum >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4);
}

static inline uint16_t crc_calculate(const uint8_t *pBuffer, uint16_t length)
{
        uint16_t crcTmp = X25_INIT_CRC;
        while (length--) crc_accumulate(*pBuffer++, &crcTmp);
        return crcTmp;
}
```
Properties: poly 0x1021 reflected (0x8408), init 0xFFFF, refin/refout, no final XOR. Running the code above over ASCII `"123456789"` gives **0x6F91** (computed in this session; this is the published CRC-16/MCRF4XX check value).

Coverage (S1, S6): all bytes from `len` (byte 1) through the last payload byte — i.e. everything after STX, excluding checksum and signature — then one extra `crc_accumulate(CRC_EXTRA)`. Compare against the LE uint16 that follows the payload. CRC_EXTRA is the low byte of the CRC over "message name + type and name of each field (wire order, array length appended)", extension fields excluded (S1); never recompute it, use the table in §3.

Test vectors (built with the code above; v2 truncation applied):
```
v2 HEARTBEAT  sysid1/compid1 seq0, custom_mode=0 type=2 autopilot=3 base_mode=0x81 status=4 ver=3
  fd 09 00 00 00 01 01 00 00 00 | 00 00 00 00 02 03 81 04 03 | 9f e6
v1 HEARTBEAT  same payload
  fe 09 00 01 01 00 | 00 00 00 00 02 03 81 04 03 | 05 25
v2 GLOBAL_POSITION_INT seq1, t=1000 lat=473977420 lon=85455940 alt=488000 rel=10000 v=0 hdg=9000
  fd 1c 00 00 01 01 01 21 00 00 | e8 03 00 00 4c 52 40 1c 44 f4 17 05 40 72 07 00 10 27 00 00 00 00 00 00 00 00 28 23 | 81 7e
```

---

## 3. Message table

### 3.1 CRC_EXTRA / length table (S7 `MAVLINK_MESSAGE_CRCS`, confirmed per-header in S8)

Entry format `{msgid, crc_extra, min_len, max_len, flags, target_system_ofs, target_component_ofs}`; `flags=3` means the message carries target_system/target_component at the given payload offsets (`MAV_MSG_ENTRY_FLAG_HAVE_TARGET_SYSTEM|COMPONENT`).

| msgid | name | CRC_EXTRA | min_len (v1 len / v2 base) | max_len (v2 with extensions) | flags, tgt ofs |
|---|---|---|---|---|---|
| 0 | HEARTBEAT | **50** | 9 | 9 | 0 |
| 1 | SYS_STATUS | **124** | 31 | 43 | 0 |
| 24 | GPS_RAW_INT | **24** | 30 | 52 | 0 |
| 30 | ATTITUDE | **39** | 28 | 28 | 0 |
| 33 | GLOBAL_POSITION_INT | **104** | 28 | 28 | 0 |
| 242 | HOME_POSITION | **104** | 52 | 60 | 0 |
| 12900 | OPEN_DRONE_ID_BASIC_ID | **114** | 44 | 44 | 3, sys@0 comp@1 |
| 12901 | OPEN_DRONE_ID_LOCATION | **254** | 59 | 59 | 3, sys@30 comp@31 |
| 12903 | OPEN_DRONE_ID_SELF_ID | **249** | 46 | 46 | 3, sys@0 comp@1 |
| 12904 | OPEN_DRONE_ID_SYSTEM | **77** | 54 | 54 | 3, sys@28 comp@29 |
| 12905 | OPEN_DRONE_ID_OPERATOR_ID | **49** | 43 | 43 | 3, sys@0 comp@1 |
| 12915 | OPEN_DRONE_ID_MESSAGE_PACK | **94** | 249 | 249 | 3, sys@0 comp@1 |
| 12918 | OPEN_DRONE_ID_ARM_STATUS | **139** | 51 | 51 | 0 |
| 12919 | OPEN_DRONE_ID_SYSTEM_UPDATE | **7** | 18 | 18 | 3, sys@16 comp@17 |

C table:
```c
typedef struct { uint32_t msgid; uint8_t crc_extra, min_len, max_len; } mav_entry_t;
static const mav_entry_t MAV_ENTRIES[] = {
  {0,50,9,9}, {1,124,31,43}, {24,24,30,52}, {30,39,28,28}, {33,104,28,28}, {242,104,52,60},
  {12900,114,44,44}, {12901,254,59,59}, {12903,249,46,46}, {12904,77,54,54}, {12905,49,43,43},
  {12915,94,249,249}, {12918,139,51,51}, {12919,7,18,18},
};
```
Messages with msgid > 255 only exist in MAVLink 2 frames.

### 3.2 Wire layouts (offsets are payload byte offsets, all multi-byte fields little-endian)

**HEARTBEAT (0)** — len 9, CRC 50 (S8 minimal/mavlink_msg_heartbeat.h; XML order is type, autopilot, base_mode, custom_mode, system_status, mavlink_version — S9)
```
@0  uint32 custom_mode      autopilot-specific flight mode bitfield
@4  uint8  type             MAV_TYPE (see 3.3)
@5  uint8  autopilot        MAV_AUTOPILOT (see 3.4)
@6  uint8  base_mode        MAV_MODE_FLAG bitmap: 0x80 SAFETY_ARMED, 0x40 MANUAL_INPUT, 0x20 HIL, 0x10 STABILIZE, 0x08 GUIDED, 0x04 AUTO, 0x02 TEST, 0x01 CUSTOM_MODE_ENABLED
@7  uint8  system_status    MAV_STATE: 0 UNINIT 1 BOOT 2 CALIBRATING 3 STANDBY 4 ACTIVE 5 CRITICAL 6 EMERGENCY 7 POWEROFF 8 FLIGHT_TERMINATION
@8  uint8  mavlink_version  always 3 (generated code writes the literal 3)
```

**SYS_STATUS (1)** — base 31, max 43, CRC 124
```
@0  uint32 onboard_control_sensors_present   MAV_SYS_STATUS_SENSOR bitmap
@4  uint32 onboard_control_sensors_enabled
@8  uint32 onboard_control_sensors_health
@12 uint16 load              [d%]  0..1000 = 0..100.0 % mainloop usage
@14 uint16 voltage_battery   [mV]  UINT16_MAX = not sent
@16 int16  current_battery   [cA]  -1 = not sent (10 mA units)
@18 uint16 drop_rate_comm    [c%]  0..10000
@20 uint16 errors_comm
@22 uint16 errors_count1   @24 errors_count2   @26 errors_count3   @28 errors_count4
@30 int8   battery_remaining [%]  -1 = not sent
-- extensions --
@31 uint32 onboard_control_sensors_present_extended
@35 uint32 onboard_control_sensors_enabled_extended
@39 uint32 onboard_control_sensors_health_extended
```

**GPS_RAW_INT (24)** — base 30, max 52, CRC 24
```
@0  uint64 time_usec          [us]
@8  int32  lat                [degE7]  WGS84 (×1e-7 → deg)
@12 int32  lon                [degE7]
@16 int32  alt                [mm]     MSL, positive up
@20 uint16 eph                HDOP×100, UINT16_MAX unknown
@22 uint16 epv                VDOP×100
@24 uint16 vel                [cm/s]   ground speed, UINT16_MAX unknown
@26 uint16 cog                [cdeg]   course over ground, UINT16_MAX unknown
@28 uint8  fix_type           GPS_FIX_TYPE: 0 NO_GPS 1 NO_FIX 2 2D 3 3D 4 DGPS 5 RTK_FLOAT 6 RTK_FIXED 7 STATIC 8 PPP
@29 uint8  satellites_visible 255 unknown
-- extensions --
@30 int32  alt_ellipsoid [mm]   @34 uint32 h_acc [mm]   @38 uint32 v_acc [mm]
@42 uint32 vel_acc [mm/s]       @46 uint32 hdg_acc [degE5]   @50 uint16 yaw [cdeg] (0 = not available)
```

**ATTITUDE (30)** — len 28, CRC 39
```
@0  uint32 time_boot_ms [ms]
@4  float roll [rad]  @8 float pitch [rad]  @12 float yaw [rad]  (-pi..pi)
@16 float rollspeed [rad/s]  @20 float pitchspeed  @24 float yawspeed
```

**GLOBAL_POSITION_INT (33)** — len 28, CRC 104 (all 4-byte fields precede 2-byte fields, so wire order == XML order; S7/S8-fallback/S10)
```
@0  uint32 time_boot_ms [ms]
@4  int32  lat          [degE7]
@8  int32  lon          [degE7]
@12 int32  alt          [mm]   MSL
@16 int32  relative_alt [mm]   above home
@20 int16  vx [cm/s] north   @22 int16 vy [cm/s] east   @24 int16 vz [cm/s] down
@26 uint16 hdg [cdeg]  0..35999, UINT16_MAX unknown
```
This is the primary "where is the drone" message (ArduPilot/PX4 stream it at 1–10 Hz by default in GCS profiles).

**HOME_POSITION (242)** — base 52, max 60, CRC 104
```
@0  int32 latitude [degE7]   @4 int32 longitude [degE7]   @8 int32 altitude [mm] MSL
@12 float x [m]  @16 float y [m]  @20 float z [m]            (local NED)
@24 float q[4]   (16 bytes)
@40 float approach_x [m]  @44 float approach_y [m]  @48 float approach_z [m]
-- extension --
@52 uint64 time_usec [us]
```
Useful as "operator/launch location" fallback when no ODID SYSTEM message is present.

**OPEN_DRONE_ID_BASIC_ID (12900)** — len 44, CRC 114
```
@0  uint8 target_system   @1 uint8 target_component
@2  uint8 id_or_mac[20]   (only filled by RID *receivers* relaying other aircraft: MAC as ASCII e.g. "3065EC6FC458" — S12; from an autopilot it is zeros)
@22 uint8 id_type   MAV_ODID_ID_TYPE: 0 NONE 1 SERIAL_NUMBER (ANSI/CTA-2063) 2 CAA_REGISTRATION_ID 3 UTM_ASSIGNED_UUID 4 SPECIFIC_SESSION_ID
@23 uint8 ua_type   MAV_ODID_UA_TYPE: 0 NONE 1 AEROPLANE 2 HELICOPTER_OR_MULTIROTOR 3 GYROPLANE 4 HYBRID_LIFT 5 ORNITHOPTER 6 GLIDER 7 KITE 8 FREE_BALLOON 9 CAPTIVE_BALLOON 10 AIRSHIP 11 FREE_FALL_PARACHUTE 12 ROCKET 13 TETHERED_POWERED_AIRCRAFT 14 GROUND_OBSTACLE 15 OTHER
@24 uint8 uas_id[20]  null-padded ASCII (serial) or raw bytes (UUID / session id)
```

**OPEN_DRONE_ID_LOCATION (12901)** — len 59, CRC 254
```
@0  int32  latitude            [degE7]  0 = unknown (both)
@4  int32  longitude           [degE7]
@8  float  altitude_barometric [m]      -1000 = unknown (ref 1013.2 mb)
@12 float  altitude_geodetic   [m]      WGS84, -1000 = unknown
@16 float  height              [m]      above takeoff or ground per height_reference, -1000 unknown
@20 float  timestamp           [s]      seconds after the full UTC hour; 0xFFFF = unknown
@24 uint16 direction           [cdeg]   0..35999; 36100 = unknown
@26 uint16 speed_horizontal    [cm/s]   25500 = unknown, clamp 25425
@28 int16  speed_vertical      [cm/s]   up positive; 6300 = unknown, clamp ±6200
@30 uint8  target_system   @31 uint8 target_component
@32 uint8  id_or_mac[20]
@52 uint8  status              MAV_ODID_STATUS: 0 UNDECLARED 1 GROUND 2 AIRBORNE 3 EMERGENCY 4 REMOTE_ID_SYSTEM_FAILURE
@53 uint8  height_reference    MAV_ODID_HEIGHT_REF: 0 OVER_TAKEOFF 1 OVER_GROUND
@54 uint8  horizontal_accuracy (MAV_ODID_HOR_ACC) @55 vertical_accuracy @56 barometer_accuracy @57 speed_accuracy @58 timestamp_accuracy
```

**OPEN_DRONE_ID_SELF_ID (12903)** — len 46, CRC 249
```
@0 target_system @1 target_component @2 id_or_mac[20]
@22 uint8 description_type  MAV_ODID_DESC_TYPE: 0 TEXT 1 EMERGENCY 2 EXTENDED_STATUS
@23 char  description[23]   null-padded
```

**OPEN_DRONE_ID_SYSTEM (12904)** — len 54, CRC 77
```
@0  int32  operator_latitude     [degE7]  0 = unknown
@4  int32  operator_longitude    [degE7]
@8  float  area_ceiling          [m] WGS84, -1000 unknown
@12 float  area_floor            [m]
@16 float  operator_altitude_geo [m] WGS84, -1000 unknown
@20 uint32 timestamp             [s] since 2019-01-01 00:00:00 UTC (add 1546300800 for Unix time)
@24 uint16 area_count            default 1
@26 uint16 area_radius           [m]
@28 target_system @29 target_component @30 id_or_mac[20]
@50 uint8 operator_location_type MAV_ODID_OPERATOR_LOCATION_TYPE: 0 TAKEOFF 1 LIVE_GNSS 2 FIXED
@51 uint8 classification_type (MAV_ODID_CLASSIFICATION_TYPE: 0 UNDECLARED 1 EU)  @52 category_eu  @53 class_eu
```

**OPEN_DRONE_ID_OPERATOR_ID (12905)** — len 43, CRC 49
```
@0 target_system @1 target_component @2 id_or_mac[20]
@22 uint8 operator_id_type  MAV_ODID_OPERATOR_ID_TYPE: 0 CAA
@23 char  operator_id[20]   null-padded ASCII
```

**OPEN_DRONE_ID_MESSAGE_PACK (12915)** — len 249, CRC 94
```
@0 target_system @1 target_component @2 id_or_mac[20]
@22 uint8 single_message_size   must be 25 (ODID_MESSAGE_SIZE)
@23 uint8 msg_pack_size         1..9
@24 uint8 messages[225]         concatenated raw ASTM F3411 25-byte messages (same encoding as BT/WiFi Remote ID broadcasts: byte0 = msgtype<<4 | protocol_version) — reuse the existing Remote-ID decoder on each 25-byte slice
```
Because of v2 truncation, a pack with n messages typically arrives with len = 24 + 25·n (trailing zeros stripped); zero-fill to 249 before indexing.

**OPEN_DRONE_ID_ARM_STATUS (12918)** — len 51, CRC 139
```
@0 uint8 status  MAV_ODID_ARM_STATUS: 0 GOOD_TO_ARM 1 PRE_ARM_FAIL_GENERIC
@1 char  error[50]
```

**OPEN_DRONE_ID_SYSTEM_UPDATE (12919)** — len 18, CRC 7
```
@0  int32  operator_latitude [degE7]   @4 int32 operator_longitude [degE7]
@8  float  operator_altitude_geo [m]   @12 uint32 timestamp [s since 2019-01-01]
@16 uint8  target_system   @17 uint8 target_component
```

Who sends the ODID messages (S12): the autopilot streams BASIC_ID/LOCATION/SYSTEM/… **to** the Remote-ID transmitter component (`MAV_TYPE_ODID = 34`, `MAV_COMP_ID_ODID_TXRX_1..3`). Over a WiFi telemetry link you will usually only see them if the RID module is on the same MAVLink network (e.g. ArduPilot forwarding to a GCS, or a DroneCAN/serial RID module whose traffic is routed) — expect GLOBAL_POSITION_INT/GPS_RAW_INT to be far more common than ODID messages in sniffed telemetry.

### 3.3 MAV_TYPE classification (S9, values verified from minimal.xml)

Air vehicles (treat as "UAV"):
```
0 GENERIC (generic MAV; usually a vehicle)   1 FIXED_WING   2 QUADROTOR   3 COAXIAL   4 HELICOPTER
7 AIRSHIP   8 FREE_BALLOON   9 ROCKET   13 HEXAROTOR   14 OCTOROTOR   15 TRICOPTER   16 FLAPPING_WING   17 KITE
19 VTOL_TAILSITTER_DUOROTOR   20 VTOL_TAILSITTER_QUADROTOR   21 VTOL_TILTROTOR   22 VTOL_FIXEDROTOR
23 VTOL_TAILSITTER   24 VTOL_TILTWING   25 VTOL_RESERVED5   28 PARAFOIL   29 DODECAROTOR
35 DECAROTOR   43 GENERIC_MULTIROTOR   47 VTOL_GYRODYNE
```
Non-air vehicles: `10 GROUND_ROVER  11 SURFACE_BOAT  12 SUBMARINE  45 SPACECRAFT_ORBITER  46 GROUND_QUADRUPED`.
Ground/infrastructure/components (NOT a drone, even though they send HEARTBEAT):
```
5 ANTENNA_TRACKER   6 GCS   18 ONBOARD_CONTROLLER   26 GIMBAL   27 ADSB   30 CAMERA   31 CHARGING_STATION
32 FLARM   33 SERVO   34 ODID (Remote-ID module)   36 BATTERY   37 PARACHUTE   38 LOG   39 OSD   40 IMU   41 GPS
42 WINCH   44 ILLUMINATOR   48 GRIPPER   49 RADIO
```
Rule: classify a `sysid` as a UAV when any HEARTBEAT from `compid == 1` (autopilot; conventional `MAV_COMP_ID_AUTOPILOT1 = 1` `[not re-verified here]`) has `type` in the air-vehicle set; `base_mode & 0x80` = armed; `system_status == 4` = ACTIVE (flying/armed). GCS software commonly uses sysid 255 and type 6 `[convention, unverified]`.

### 3.4 MAV_AUTOPILOT (S9)
```
0 GENERIC  1 RESERVED  2 SLUGS  3 ARDUPILOTMEGA (ArduPilot)  4 OPENPILOT  5 GENERIC_WAYPOINTS_ONLY
6 GENERIC_WAYPOINTS_AND_SIMPLE_NAVIGATION_ONLY  7 GENERIC_MISSION_FULL  8 INVALID (non-flight-controller components)
9 PPZ (Paparazzi)  10 UDB  11 FP (FlexiPilot)  12 PX4  13 SMACCMPILOT  14 AUTOQUAD  15 ARMAZILA  16 AEROB  17 ASLUAV
18 SMARTAP  19 AIRRAILS  20 REFLEX  21 FLIX
```
INAV/Betaflight MAVLink output report `MAV_AUTOPILOT_GENERIC` (0) with a multirotor/fixed-wing `type` `[unverified]`.

---

## 4. How MAVLink travels over WiFi in practice

### 4.1 Ports and addressing

| port | proto | role | source |
|---|---|---|---|
| **14550/udp** | UDP | de-facto GCS listen port: QGC autoconnect, Mission Planner "UDP", MAVProxy `--out 127.0.0.1:14550`, mavesp8266 `WIFI_UDP_HPORT`, DroneBridge, PX4 `MAV_X_REMOTE_PRT` default, SITL | W1–W3, W5–W7, W10–W16 |
| 14555/udp | UDP | mavesp8266 local ("client") port — GCS→vehicle direction | W3 (`DEFAULT_UDP_CPORT 14555`) |
| 14540/udp | UDP | PX4 offboard API (MAVSDK/MAVROS); multi-vehicle 14540..14549 | W6 |
| 14551/14552/udp | UDP | MAVProxy second output (14551), Skydroid H16 & Herelink internal relay ports (14551 rx / 14552 tx) | W11, W15, W16 |
| 14580, 18570/udp | UDP | PX4 SITL local ports (containers/VMs) | W6 |
| 19856/udp | UDP | SIYI MK15/HM30 ground unit MAVLink (192.168.144.12) `[unverified]` | W17 |
| 13550..13552/udp | UDP | Skydroid H16 UART1 relay | W15 |
| **5760/tcp** | TCP | ArduPilot SITL SERIAL0, DroneBridge TCP server, mLRS bridge TCP, QGC/MP TCP default | W4, W9, W13 |
| 5762, 5763/tcp | TCP | ArduPilot SITL SERIAL1/2 | W9 |
| 23/tcp, 2323/tcp | TCP | esp-link / ESP8266-transparent-bridge DIY serial bridges (MSP/LTM/MAVLink raw) | W20 |
| 6789/tcp | TCP | "IFFRC_xxxxxxxx" ESP8266 modules (PX4 docs) | W2 |
| 4560/tcp | TCP | PX4 ↔ simulator (not MAVLink telemetry of interest) | W6 |

Broadcast vs unicast (important for a passive sniffer because broadcast frames are easy to catch and are addressed to ff:ff:ff:ff:ff:ff):
- mavesp8266: starts with `_ip[3] = 255` (subnet broadcast, e.g. 192.168.4.255:14550) and switches to unicast to the first GCS it hears; falls back to broadcast after `HEARTBEAT_TIMEOUT` (W3 `mavesp8266_gcs.cpp`).
- PX4 (WiFi/UDP): "broadcasts a heartbeat to port 14550 on 255.255.255.255 until it receives the first heartbeat from a ground control station, at which point it will only send data to this ground control station" (W5); hardware Ethernet/WiFi instances use `MAV_X_BROADCAST` = Never / Always / "Only until a GCS is found" (W7).
- mLRS bridge: broadcast until a GCS registers, then unicast to each client (W13).
- Herelink: "The Mavlink traffic being Broadcast from the WIFI Access Point by default" (W16).
- ArduPilot networking: UDP client broadcasts only when `NET_P1_IP = 255.255.255.255` (W8).
- DroneBridge ESP32: "UDP unicast to all connected devices" (W4) — but encrypted anyway.
- Mission Planner `udpcl://192.168.1.255:14550` example shows GCS→vehicle subnet broadcast (W10).
Consequence: on an open network, expect vehicle→GCS frames to be either broadcast (before a GCS attaches, often continuously for Herelink) or unicast to the GCS; both are visible to a promiscuous sniffer on the right channel.

### 4.2 Common bridges / products — defaults

| product | default SSID | default password | security | IP | ports | mode | notes / source |
|---|---|---|---|---|---|---|---|
| mavesp8266 (upstream / PX4 "PixRacer" ESP-01/ESP-07 modules, Holybro) | `PixRacer` | `pixracer` | WPA2-PSK | 192.168.4.1 | UDP 14550 (to GCS), 14555 (local) | AP (`WIFI_MODE 0`), channel 11 | W2, W3 |
| mavesp8266 ArduPilot fork | `ArduPilot` | `ardupilot` | WPA2-PSK | 192.168.4.1 | UDP 14550 / 14555 | AP | W1, W3 (ArduPilot `kDEFAULT_SSID`) |
| DroneBridge for ESP32 | `DroneBridge for ESP32` (README: `DroneBridge ESP32`) | `dronebridge` | WPA2-PSK; "does not support unencrypted networks"; ESP-NOW mode AES-GCM-256 | 192.168.2.1 | UDP 14550, TCP 5760 | AP (also STA, ESP-NOW LR) | W4 |
| CUAV PW-Link | `CUAVWLINKxxxx` | `cuavwlink` | WPA2-PSK | 192.168.4.1 | UDP 14550 | AP | W14 |
| ExpressLRS TX Backpack (MAVLink mode, Betaflight/INAV/ArduPilot over ELRS) | `ExpressLRS TX Backpack XXXXXX` | `expresslrs` | WPA2-PSK | 10.0.0.1 | UDP 14550 | AP or home-WiFi STA | W12, W19 |
| mLRS wireless bridge (ESP8266/ESP32 on TX module) | `mLRS-xxxx AP UDP` / `AP TCP` | **none** (`password = ""` → open AP); UDPSTA mode uses `mLRS-<bindphrase>` | **OPEN by default** | 192.168.4.55 | UDP 14550, TCP 5760 | AP, channel 6 | W13 |
| "IFFRC_xxxxxxxx" ESP8266 modules | `IFFRC_xxxxxxxx` | `12345678` | WPA2-PSK | 192.168.4.1 | TCP 6789 | AP | W2 |
| DIY esp-link / ESP8266-transparent-bridge (Cleanflight/INAV MSP/LTM, "works for MAVLink too") | `ESP_xxxxxx` | user-set (`+++AT AP <ssid> <pw>`); initial AP unconfigured | often **open** until configured `[open-by-default not confirmed from primary doc]` | 192.168.4.1 | TCP 23 | AP | W20 |
| Herelink (ground controller hotspot) | Android hotspot (user-named) | Android hotspot password | WPA2-PSK (Android default) `[inferred]` | 192.168.43.1 | UDP 14550 broadcast on hotspot; UDPCL 14552 | AP | W16 |
| Skydroid H16 (ground unit hotspot) | Android hotspot | Android hotspot password | WPA2-PSK `[inferred]` | 192.168.43.1 | UDP 14550 to client (UART0), 13550 (UART1) | AP | W15 |
| SIYI MK15 / HM30 | ground-unit WiFi / LAN | manual | proprietary air link (encrypted); WiFi WPA2 `[unverified]` | 192.168.144.12 | UDP 19856 `[unverified]` | — | W17 |
| Yuneec H520 / ST16S (PX4) | aircraft 5 GHz AP | pairing | WPA2 `[unverified]` | — | MAVLink over WiFi | — | W21 |
| Parrot AR.Drone 2.0 / Bebop 2 | `ardrone2_xxx` / `Bebop2-xxxxxx` | none | **OPEN by default** (WPA2 optional via FreeFlight) | 192.168.42.1 / 192.168.1.1 | ARSDK (UDP 54321/43210, TCP 44444) — **not MAVLink** | AP | W18 `[secondary]` |
| Parrot ANAFI family | `ANAFI-xxxxxx` | printed key | WPA2 + PMF | 192.168.42.1 | ARSDK; ANAFI USA/Ai advertise "MAVLink v1 compatible" ground API | AP | W18 `[secondary]` |
| PX4 SITL / QGC on a LAN | host's WiFi | host's | whatever the LAN uses | — | UDP 14550 broadcast until GCS found | — | W5, W6 |
| Betaflight | no WiFi of its own; MAVLink only via ELRS backpack (above) | | | | | | W19 |
| INAV | MAVLink telemetry "transmit-only", v1 and v2 supported; WiFi via any serial bridge above | | | | | | W19 |

**Explicit statement:** a promiscuous sniffer can decode the IP/UDP/MAVLink payload **only on open (unencrypted) networks**. Every WPA2/WPA3 data frame has the Protected bit set and the body is CCMP/GCMP ciphertext; ESP-NOW (DroneBridge) is additionally AES-GCM encrypted at the application layer. (Decrypting WPA2-PSK with a known default password would require capturing the EAPOL 4-way handshake and implementing CCMP — out of scope.)

**Estimate of open-network share:** every commercial module in the table ships WPA2-PSK with a public default password; the only open-by-default MAVLink carriers found are the mLRS wireless bridge (AP TCP/UDP modes) and unconfigured DIY ESP8266 bridges, plus users who deliberately clear the AP password. Parrot's open networks carry ARSDK, not MAVLink. Realistically **well under 10 % (likely ~2–5 %) of MAVLink-over-WiFi links are open**, so expect MAVLink-over-WiFi detection to be a bonus channel rather than a primary one. What a sniffer *can* always do on encrypted networks is fingerprint the bridge by BSSID/SSID (e.g. SSID starts with `PixRacer`, `ArduPilot`, `DroneBridge`, `CUAVWLINK`, `ExpressLRS TX Backpack`, `mLRS-`, `ANAFI`, `Bebop2`) and by frame cadence — that is the higher-yield detection signal in practice.

---

## 5. From 802.11 data frame to MAVLink bytes (open network)

### 5.1 ESP-IDF promiscuous API (E3–E7)

```c
typedef enum { WIFI_PKT_MGMT, WIFI_PKT_CTRL, WIFI_PKT_DATA, WIFI_PKT_MISC } wifi_promiscuous_pkt_type_t;
// WIFI_PKT_MISC: "Other type, such as MIMO etc. 'buf' argument is wifi_promiscuous_pkt_t but the payload is zero length."
#define WIFI_PROMIS_FILTER_MASK_ALL        (0xFFFFFFFF)
#define WIFI_PROMIS_FILTER_MASK_MGMT       (1)
#define WIFI_PROMIS_FILTER_MASK_CTRL       (1<<1)
#define WIFI_PROMIS_FILTER_MASK_DATA       (1<<2)
#define WIFI_PROMIS_FILTER_MASK_MISC       (1<<3)
#define WIFI_PROMIS_FILTER_MASK_DATA_MPDU  (1<<4)
#define WIFI_PROMIS_FILTER_MASK_DATA_AMPDU (1<<5)
#define WIFI_PROMIS_FILTER_MASK_FCSFAIL    (1<<6)
typedef struct { uint32_t filter_mask; } wifi_promiscuous_filter_t;
typedef struct { wifi_pkt_rx_ctrl_t rx_ctrl; uint8_t payload[0]; } wifi_promiscuous_pkt_t;
//   payload: "Data or management payload. Length of payload is described by rx_ctrl.sig_len."
//   payload[0] is the first byte of the 802.11 MAC header (Frame Control) — there is no radiotap/PLCP prefix.
typedef void (*wifi_promiscuous_cb_t)(void *buf, wifi_promiscuous_pkt_type_t type);
```
- `esp_wifi_set_promiscuous_filter()`: "The default filter is to filter all packets except WIFI_PKT_MISC" (E7); guide: "By default, it will filter all 802.11 data and management frames to the application" (E6). Set it explicitly: `filter_mask = WIFI_PROMIS_FILTER_MASK_DATA | WIFI_PROMIS_FILTER_MASK_MGMT` (keep MGMT if the same sniffer also parses Remote-ID beacons/NAN action frames). Do **not** set `FCSFAIL`.
- Sniffer dumps "802.11 Data frame, including MPDU, AMPDU, and AMSDU"; A-MPDU aggregates are delivered as individual MPDUs, each with its own MAC header (E6: AMPDU listed; the `DATA_MPDU`/`DATA_AMPDU` bits sub-select). MIMO frames come as `WIFI_PKT_MISC` with zero-length payload.
- Works in `WIFI_MODE_NULL/STA/AP/APSTA`; "The callback will be called directly in the Wi-Fi driver task … post an event to the application task in the callback and defer the real work" (E6). Copy at most ~300 bytes (MAC hdr + IP/UDP + 280) into a queue; don't parse in the callback.
- `rx_ctrl` (ESP32/S2/S3/C2/C3, E4): `signed rssi:8` dBm; `unsigned channel:4` "primary channel"; `secondary_channel:4`; `timestamp:32` µs; **`sig_len:12` = "length of packet including Frame Check Sequence(FCS)"**; `rx_state:8` "0: no error; others: error numbers". So on these chips `payload[0 .. sig_len-4)` is the frame and the last 4 bytes are the FCS (CRC-32, do not feed it to the parser). Only accept frames with `rx_state == 0`.
- ESP32-C5/C6/C61 (E5, `CONFIG_SOC_WIFI_HE_SUPPORT` → `wifi_pkt_rx_ctrl_t` is `esp_wifi_rxctrl_t`): `unsigned sig_len:14` "the length of the reception MPDU" and separately `unsigned dump_len:14` "the length of the reception MPDU excluding the FCS", `channel:8`, `second:8`, `rssi:8`, `rx_state:8`, `is_group:1`. Use `dump_len` when available. **Robust approach for all chips: do not rely on FCS semantics at all — bound the parse by the IPv4 `total_length` and UDP `length` fields** (see 5.4).
- Channel: `esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE)` while hopping; on the C5 the 5 GHz band must be selected first (`esp_wifi_set_band_mode()` in IDF ≥ 5.4) `[unverified detail; check your IDF version]`. The common bridges sit on 2.4 GHz channels 1/6/11 (mavesp8266 default ch 11, mLRS ch 6).

### 5.2 802.11 MAC header (E2; IEEE 802.11-2020 §9.2.4)

Frame Control = payload[0..1] (bit numbering of the 16-bit field, transmitted LSB first):
```
fc0 = payload[0]:  bits0-1 protocol version (must be 0) | bits2-3 Type | bits4-7 Subtype
fc1 = payload[1]:  0x01 To-DS | 0x02 From-DS | 0x04 More Frag | 0x08 Retry | 0x10 Pwr Mgmt
                   0x20 More Data | 0x40 Protected Frame | 0x80 +HTC/Order
Type  = (fc0 >> 2) & 3   : 0 mgmt, 1 ctrl, 2 data, 3 ext
Subtype = fc0 >> 4       : data subtypes — 0000 Data, 0100 Null, 1000 QoS Data, 1100 QoS Null (bit3 of subtype = QoS, bit2 = "no body")
```
Header length:
```
24 bytes: FC(2) Duration(2) Addr1(6) Addr2(6) Addr3(6) SeqCtl(2)
+6  if (fc1 & 0x03) == 0x03            (Addr4 present, WDS/4-address)
+2  if (fc0 & 0x80)                    (QoS Control, QoS-data subtypes)
+4  if QoS data && (fc1 & 0x80)        (HT Control; the Order bit means +HTC in QoS data frames)
```
Reject when: `(fc0 & 0x03) != 0` (bad version), type != 2 (data), `(fc0 & 0x40)` (null-data subtype, no body), `(fc1 & 0x40)` (Protected → encrypted, body starts with an 8-byte CCMP/TKIP IV; undecodable), `(fc1 & 0x04)` (fragmented).
A-MSDU: if QoS Control present and `(qos[0] & 0x80)` (A-MSDU Present, bit 7), the body is a sequence of subframes `DA(6) SA(6) Len(2) LLC/SNAP… pad-to-4`; either parse subframes or skip — rare on these bridges.

Address roles (E2, 802.11-2020 Table 9-30):

| To-DS | From-DS | Addr1 | Addr2 | Addr3 | Addr4 | case |
|---|---|---|---|---|---|---|
| 0 | 0 | DA | SA | BSSID | – | IBSS / direct (also ESP-NOW-style, but that is a mgmt action frame) |
| 0 | 1 | DA (RA) | BSSID | SA | – | **AP → station** (bridge in AP mode sending to the GCS laptop/phone) |
| 1 | 0 | BSSID | SA | DA | – | **station → AP** (bridge in STA mode, or GCS → bridge-AP) |
| 1 | 1 | RA | TA | DA | SA | WDS / 4-address |

"Drone MAC" for an open MAVLink frame = the **SA** (original source) of the frame that carries vehicle→GCS MAVLink:
- bridge is the AP (mavesp8266, DroneBridge, CUAV, mLRS, ELRS backpack defaults): frames are From-DS=1 → SA = Addr3 (= BSSID = Addr2 for an ESP softAP); the AP's BSSID is the drone-side radio.
- bridge joined someone's AP (STA mode): bridge→AP frames To-DS=1 → SA = Addr2 (uplink); when the AP relays to the GCS (From-DS=1) the bridge's MAC is Addr3.
- Herelink / Skydroid / SIYI hotspots: the "SA" is the ground controller, not the aircraft — identity comes from the MAVLink sysid and the position from the payload; the aircraft itself is on a proprietary link.
Generic rule: `sa = (fc1&0x03)==0x03 ? Addr4 : (fc1&0x02) ? Addr3 : Addr2`. Also record `bssid = (fc1&0x03)==0 ? Addr3 : (fc1&0x02) ? Addr2 : Addr1` and the RSSI from rx_ctrl.

### 5.3 LLC/SNAP → IPv4 → UDP/TCP (E1, RFC 791/768/793)

Immediately after the MAC header (unencrypted frames only):
```
LLC/SNAP (8 bytes, RFC 1042): AA AA 03 | 00 00 00 | 08 00     (DSAP 0xAA, SSAP 0xAA, UI ctrl 0x03, OUI 0, EtherType 0x0800 = IPv4)
   other EtherTypes: 08 06 ARP, 86 DD IPv6 — ignore
IPv4 (ihl*4 bytes, normally 20): [0] version/IHL (0x45 typical; ihl = b[0]&0x0F, must be >=5)
   [2..3] total_length (BE)   [6..7] flags/frag offset (BE): reject if (v & 0x3FFF) != 0 (MF set or non-zero offset)
   [9] protocol: 17 = UDP, 6 = TCP   [12..15] src IP   [16..19] dst IP
UDP (8 bytes): [0..1] src port (BE) [2..3] dst port (BE) [4..5] length (BE, incl. 8-byte header) [6..7] checksum
TCP (doff*4 bytes): [2..3] dst port; [12] >> 4 = data offset in 32-bit words (>=5); payload follows
```
Offsets of the first MAVLink byte from `payload[0]` for the usual cases (IHL=5, UDP):

| frame type | MAC hdr | + LLC/SNAP | + IPv4 | + UDP | → MAVLink at |
|---|---|---|---|---|---|
| plain Data | 24 | 32 | 52 | 60 | **60** |
| QoS Data | 26 | 34 | 54 | 62 | **62** |
| QoS Data + HT Control | 30 | 38 | 58 | 66 | **66** |
| 4-address QoS Data | 32 | 40 | 60 | 68 | **68** |
(TCP: replace the final +8 by `+doff*4`, normally +20 → 72/74/78/80.)
Always compute these dynamically from the flag bits and IHL/data-offset rather than hard-coding.

Minimum useful frame: 60 + 12 (smallest v2 frame) = 72 bytes before FCS; a v2 HEARTBEAT is 21 bytes of MAVLink → 81-byte frame + 4 FCS.

### 5.4 Walk-down code (C, ESP-IDF callback-side copy, parser-side decode)

```c
#include "esp_wifi.h"
#include "esp_wifi_types.h"

static inline uint16_t be16(const uint8_t *p) { return (uint16_t)(p[0] << 8 | p[1]); }

// returns pointer to L4 payload and its length, or NULL. Sets *is_udp, ports, src ip.
static const uint8_t *wifi_to_l4(const uint8_t *f, size_t n, int *is_udp,
                                 uint16_t *sport, uint16_t *dport, uint32_t *sip, uint32_t *dip,
                                 uint8_t sa[6], uint8_t bssid[6], size_t *l4len)
{
    if (n < 24) return NULL;
    uint8_t fc0 = f[0], fc1 = f[1];
    if ((fc0 & 0x03) != 0) return NULL;                 // version
    if (((fc0 >> 2) & 3) != 2) return NULL;             // not a data frame
    if (fc0 & 0x40) return NULL;                        // null-data subtype
    if (fc1 & 0x40) return NULL;                        // Protected: WPA/WPA2/WPA3 -> undecodable
    if (fc1 & 0x04) return NULL;                        // fragmented
    size_t hdr = 24;
    int ds = fc1 & 0x03;
    if (ds == 3) hdr += 6;
    const uint8_t *qos = NULL;
    if (fc0 & 0x80) { qos = f + hdr; hdr += 2; if (fc1 & 0x80) hdr += 4; }   // QoS, then HT Control
    if (qos && (qos[0] & 0x80)) return NULL;            // A-MSDU: skip (or parse subframes)
    // addresses
    const uint8_t *a1 = f + 4, *a2 = f + 10, *a3 = f + 16, *a4 = f + 24;
    memcpy(sa,    ds == 3 ? a4 : (ds & 2) ? a3 : a2, 6);
    memcpy(bssid, ds == 0 ? a3 : (ds & 2) ? a2 : a1, 6);
    // LLC/SNAP
    static const uint8_t snap_ip[8] = {0xAA,0xAA,0x03,0x00,0x00,0x00,0x08,0x00};
    if (n < hdr + 8 + 20) return NULL;
    if (memcmp(f + hdr, snap_ip, 8) != 0) return NULL;
    const uint8_t *ip = f + hdr + 8;
    size_t ihl = (ip[0] & 0x0F) * 4;
    if ((ip[0] >> 4) != 4 || ihl < 20) return NULL;
    if (be16(ip + 6) & 0x3FFF) return NULL;             // fragment
    size_t iptot = be16(ip + 2);
    if (iptot < ihl || (size_t)(ip - f) + iptot > n) return NULL;   // bound by IP length, ignore FCS
    *sip = (uint32_t)ip[12] << 24 | ip[13] << 16 | ip[14] << 8 | ip[15];
    *dip = (uint32_t)ip[16] << 24 | ip[17] << 16 | ip[18] << 8 | ip[19];
    const uint8_t *l4 = ip + ihl;
    if (ip[9] == 17) {                                  // UDP
        if (iptot < ihl + 8) return NULL;
        size_t ul = be16(l4 + 4);
        if (ul < 8 || ul > iptot - ihl) return NULL;
        *is_udp = 1; *sport = be16(l4); *dport = be16(l4 + 2);
        *l4len = ul - 8; return l4 + 8;
    } else if (ip[9] == 6) {                            // TCP
        size_t doff = (l4[12] >> 4) * 4;
        if (doff < 20 || iptot < ihl + doff) return NULL;
        *is_udp = 0; *sport = be16(l4); *dport = be16(l4 + 2);
        *l4len = iptot - ihl - doff; return l4 + doff;
    }
    return NULL;
}
```
Then run `mav_try_frame()` (§1.5) over the returned buffer. Cheap pre-filter before CRC: `b[0] == 0xFD || b[0] == 0xFE`, and (optionally) UDP port ∈ {14550, 14555, 14540, 14551, 14552, 19856} or TCP port 5760 — but don't require the port, since mavesp8266/mLRS/etc. are user-configurable; the CRC with CRC_EXTRA is a strong enough validator (16-bit CRC + known msgid + len ≤ max_len).

Callback skeleton:
```c
static void sniff_cb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    if (type != WIFI_PKT_DATA) return;
    const wifi_promiscuous_pkt_t *p = (const wifi_promiscuous_pkt_t *)buf;
    if (p->rx_ctrl.rx_state != 0) return;
    size_t n = p->rx_ctrl.sig_len;            // includes FCS on ESP32/S3/C3; IP total_length bounds the parse anyway
    if (n < 72 || n > 400) return;            // 60 + 12 minimum; MAVLink frames are small
    if ((p->payload[1] & 0x40) || ((p->payload[0] >> 2) & 3) != 2) return;  // encrypted / not data: drop early
    // copy header + up to ~340 bytes into a ring buffer / queue with rssi, channel; parse in a task
}
wifi_promiscuous_filter_t flt = { .filter_mask = WIFI_PROMIS_FILTER_MASK_DATA | WIFI_PROMIS_FILTER_MASK_MGMT };
esp_wifi_set_promiscuous_filter(&flt);
esp_wifi_set_promiscuous_rx_cb(sniff_cb);
esp_wifi_set_promiscuous(true);
```

### 5.5 What to extract and report

Per `sysid` (keyed also by SA MAC / BSSID / src IP):
- identity: `sysid`, `compid`, HEARTBEAT `type` (→ UAV class per §3.3), `autopilot` (ArduPilot/PX4/…), armed (`base_mode & 0x80`), `system_status`; SSID/BSSID of the network (from beacons seen on the same channel) for bridge fingerprinting; ODID BASIC_ID `uas_id` / OPERATOR_ID if present.
- position: GLOBAL_POSITION_INT (lat/lon ×1e-7, alt_msl mm, relative_alt mm, hdg cdeg, vx/vy/vz cm/s) preferred; GPS_RAW_INT (fix_type ≥ 2) as fallback; ODID LOCATION if present; HOME_POSITION / ODID SYSTEM for operator/launch point.
- link quality: RSSI/channel from `rx_ctrl`, MAVLink `seq` gaps for loss.
- Discard HEARTBEATs whose `type` is in the ground/component set (GCS=6, ANTENNA_TRACKER=5, ADSB=27, ODID=34, …) when deciding "is this a drone", but keep them to learn the GCS IP/MAC (which tells you which unicast flows to watch).
