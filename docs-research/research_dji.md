# DJI proprietary WiFi "DroneID" + DJI/Ryze fingerprinting — receiver-side reference

Scope: what an 802.11 promiscuous-mode receiver (ESP32-S3) can decode from DJI
WiFi-link aircraft, how to fingerprint DJI/Ryze devices by OUI and SSID, and how
DJI's current ASTM F3411 Remote ID differs. Receive/decode only.

Research date: 2026-10-02. Confidence tags: [P] primary source quoted/verified,
[S] secondary, [U] unverified / inferred.

---------------------------------------------------------------------------

## 0. Sources

K1  Kismet `dot11_parsers/dot11_ie_221_dji_droneid.h` (master) — accessors, state
    bit masks, scaling constants, product_type table.
    https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h
K2  Kismet `dot11_parsers/dot11_ie_221_dji_droneid.cc` — parse(), incl. the
    commented-out v1/v2 extended decode.
    https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.cc
K3  Kismet `kaitai_definitions_disabled/dot11_ie_221_dji_droneid.ksy` — original
    Kaitai spec (credits Freek van Tienen + Jan Dumon).
    https://github.com/kismetwireless/kismet/blob/master/kaitai_definitions_disabled/dot11_ie_221_dji_droneid.ksy
K4  Kismet `conf/kismet_uav.conf` — uav_match OUI/SSID rules.
    https://github.com/kismetwireless/kismet/blob/master/conf/kismet_uav.conf
K5  Kismet `phy_uav_drone.cc` — how flight_reg fields map to uav.device.
    https://github.com/kismetwireless/kismet/blob/master/phy_uav_drone.cc
K6  Kismet API docs "UAV drones" https://www.kismetwireless.net/docs/api/uav_drone/
D13 Department 13, "Anatomy of DJI's Drone Identification Implementation",
    white paper, 16 Nov 2017 (PDF mirror)
    https://greyarrows.s3.dualstack.eu-west-2.amazonaws.com/original/1X/fdef57879aabefb67e7f8bc07f086dce558f1a28.pdf
BEN C. Bender, "DJI drone IDs are not encrypted" (pre-print, 2022)
    https://arxiv.org/pdf/2207.10795 — Fig. 3 (ath6kl beacon-builder snippet),
    Figs. 8-10 (license / flight-info v1 / v2), Table IV (model codes).
FWT o-gs/dji-firmware-tools `symbols/wm100_0306_v03.02.43.20_20170920.pro.map`
    (Spark FW symbol map: strings `aSetDroneidSLen`, `aGetDroneIdFail`,
    `aSetUuidS`, `aSetUserPrivFai`) https://github.com/o-gs/dji-firmware-tools
DJ1 DJI "FAQs about FAA Remote ID Compliance"
    https://support.dji.com/help/content?customId=en-us03400007747&spaceId=34&re=US&lang=en
DJ2 DJI Agras "User Guide for FAA Remote ID Compliance"
    https://ag.dji.com/newsroom/ag-news-faa-remote-id-compliance
DJ3 DJI Enterprise Insights "Navigating Remote ID Compliance for Drone
    Operations in the EU"
    https://enterprise-insights.dji.com/blog/navigating-remote-id-compliance-for-drone-operations-in-the-eu
DJ4 DroneDJ, 20 Dec 2017, "DJI's new firmware updates introduces Aeroscope
    voluntary flight identification options"
    https://dronedj.com/2017/12/20/dji-firmware-introduces-aeroscope/
SKY SkySafe blog, "Drone Manufacturers Fail FAA Remote ID Requirements"
    https://blog.skysafe.io/drone-manufacturers-fail-faa-remote-id-requirements
ODI opendroneid/receiver-android issues #93 (Air 2S), #94, #99 (Mavic 3E
    beacon hex dump) https://github.com/opendroneid/receiver-android/issues/99
ORE isaacbentley/orecchino-esp32 README (ESP32 RID receiver notes)
    https://github.com/isaacbentley/orecchino-esp32
MAC maclookup.app vendor page + API (mirrors IEEE MA-L registry)
    https://maclookup.app/vendors/sz-dji-technology-co-ltd ,
    https://api.maclookup.app/v2/macs/<prefix> ; api.macvendors.com
P3M DJI Phantom 3 Standard User Manual v1.4
    https://dl.djicdn.com/downloads/phantom_3_standard/en/Phantom_3_Standard_User_Manual_v1.4_en_0112.pdf
RYZ Ryze Tello SDK 2.0 / RoboMaster TT SDK 3.0 user guides
    https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf
    https://dl.djicdn.com/downloads/RoboMaster+TT/Tello_SDK_3.0_User_Guide_en.pdf
FOR Forums: forum.dji.com thread-146483 ("Mavic AIR doesn't emmit WIFI SSID",
    shows "MavicAir-" SSID), forum.phantomhelp.com Spark RC reset
    ("Spark-RC-XXXXXX", pwd 12341234), mavicpilots.com threads on Mavic Mini
    WiFi, forum.phantomhelp.com/t/about-remoteid-it-depend-on-country-to-broadcast/9960
THD thermaldrones.de "Setting up Remote ID on DJI drones"
    https://thermaldrones.de/en/newsknowledge/setting-up-remote-id-on-dji-drones/

Not reachable from this session (403/404/JS): mavicpilots threads, MDPI
Sensors 23(17):7650, DJI forum threads, AerixRF PR #44 brief. Nothing below
depends on them.

---------------------------------------------------------------------------

## 1. DJI DroneID vendor-specific IE — byte layout

### 1.1 Where it lives, how it is built

* Carried as an IEEE 802.11 **vendor-specific IE (element ID 0xDD / 221)** in
  **beacon** management frames of the aircraft's WiFi AP. [P: K3 doc, D13, BEN]
* Decompiled `ath6kl_usb.ko` beacon builder (BEN Fig. 3, quoting D13's
  disassembly) [P]:

      bcnbuf[0] = 0xDD;
      *(WORD*)&bcnbuf[2] = 0x3726;   // LE -> bytes 26 37
      *(WORD*)&bcnbuf[4] = 0x5812;   // LE -> bytes 12 58
      *(WORD*)&bcnbuf[6] = 0x1362;   // LE -> bytes 62 13
      memcpy(&bcnbuf[8], flight_info, flight_info_len);
      bcnbuf[1] = flight_info_len + 6;
      ath6kl_wmi_set_appie_cmd(..., bcnbuf, bcnbuf[1] + 2);

  So the IE is: `DD | len | 26 37 12 | 58 62 13 | flight_info...`
  with `len = flight_info_len + 6`.

* **OUI = 26:37:12.** Note 0x26 has the locally-administered bit (0x02) set, so
  this OUI is not and never will be in the IEEE registry — match it literally.
  Kismet stores it as `vendor_oui() = 0x263712` (K1) and in the Kaitai file as
  the LE dword `0x12372600` (K3). [P]
* Kismet reads the 3 bytes after the OUI as `vendor_type`, `unk1`, `unk2`
  (observed 0x58, 0x62, 0x13) and does **not** validate them — it dispatches on
  the 4th byte, `subcommand`. [P: K1/K2] Recommended: match OUI only, read
  subcommand at payload offset 3, treat 58 62 13 as informational. [U whether
  these ever vary across firmware]
* `flight_info` is written by the `dji_network` daemon on the aircraft into a
  sysfs hook (`dji_ie`) of the Atheros driver; it is **empty until the motors
  have been started** (D13 Fig. 11 "Drone ID checking for motors being started
  before broadcast"; "Normally, the flight_info is null, and would not be
  populated until the drone's motors have started"). [P: D13]
* Due to a `memcpy()` bug found by Freek van Tienen the flight_info is
  **truncated to 76 bytes** → IE `len` = 82 = 0x52. [P: D13 p.10, BEN §II.B
  "76-byte remote identification packet"]
* The two subcommand packets are **sent alternately, one every 200 ms**
  (D13 p.12: "These packets will be sent down the Wi-Fi link, every 200ms in an
  alternating fashion"). [P]

### 1.2 IE payload prefix (offsets from first byte after the IE length byte)

| off | size | field        | value / notes                                   |
|-----|------|--------------|-------------------------------------------------|
| 0   | 3    | OUI          | 26 37 12                                        |
| 3   | 1    | vendor_type  | 0x58 observed (Kismet `vendor_type`, unchecked) |
| 4   | 1    | unk1         | 0x62 observed                                   |
| 5   | 1    | unk2         | 0x13 observed                                   |
| 6   | 1    | subcommand   | 0x10 = flight registration/telemetry, 0x11 = flight purpose |
| 7.. | n    | record       | see 1.3 / 1.4 / 1.5 (record offset r = 7)       |

### 1.3 Subcommand 0x10 — flight_reg_info, **version 1** (Kismet K2/K3) [P]

All multi-byte integers little-endian. Offsets `r+N` are relative to the first
record byte (payload offset 7). "IE off" = offset from first byte after the IE
length byte.

| r+   | IE off | size | type  | field          | scaling / meaning |
|------|--------|------|-------|----------------|-------------------|
| 0    | 7      | 1    | u1    | version        | 1 (this layout) or 2 (see 1.4) |
| 1    | 8      | 2    | u2le  | seq            | packet sequence counter |
| 3    | 10     | 2    | u2le  | state_info     | bitfield, see 1.6 |
| 5    | 12     | 16   | ASCII | serialnumber   | 16 bytes, NUL-padded (`strz`), aircraft S/N |
| 21   | 28     | 4    | s4le  | raw_lon        | degrees = raw / 174533.0  (raw = radians x 1e7; 1e7/57.29578 = 174532.9) |
| 25   | 32     | 4    | s4le  | raw_lat        | degrees = raw / 174533.0 |
| 29   | 36     | 2    | s2le  | altitude       | Kismet exposes raw int16. Unit [U]; Kismet comment on v2: "altitude is height since takeoff" |
| 31   | 38     | 2    | s2le  | height         | raw int16; Kismet v2 comment: "Height is from barometric actual height" |
| 33   | 40     | 2    | s2le  | v_north        | raw int16 (unit [U]; likely cm/s or dm/s — Kismet leaves raw) |
| 35   | 42     | 2    | s2le  | v_east         | raw int16 |
| 37   | 44     | 2    | s2le  | v_up           | raw int16 |
| 39   | 46     | 2    | s2le  | raw_pitch      | Kismet: `pitch = (raw/100.0)/57.296` → i.e. raw is centi-degrees; raw/100 = degrees, further /57.296 gives radians |
| 41   | 48     | 2    | s2le  | raw_roll       | same |
| 43   | 50     | 2    | s2le  | raw_yaw        | same |
| 45   | 52     | 4    | s4le  | raw_home_lon   | degrees = raw / 174533.0 |
| 49   | 56     | 4    | s4le  | raw_home_lat   | degrees = raw / 174533.0 |
| 53   | 60     | 1    | u1    | product_type   | model code, table 1.7 |
| 54   | 61     | 1    | u1    | uuid_len       | length of UUID actually filled |
| 55   | 62     | 20   | bytes | uuid           | Kaitai: fixed `size: 20`; Kismet .cc reads `uuid_len` bytes; BEN calls it an "18-character string identifier that ties the UAV to a DJI user account" |

Record length through uuid_len = 55; + subcommand byte = 56; + 20-byte UUID =
76 → exactly the 76-byte truncated flight_info. IE `len` 0x52 = 82.

Kismet's shipping parser (K2) only trusts `version, seq, state_info,
serialnumber, raw_lon, raw_lat` ("None of the decodes seem proper and there is
no way to validate any of the additional data, including if height/altitude is
swapped"). Everything after raw_lat above is from Kismet's commented-out v1
branch + the Kaitai file; treat as best-effort. [P that this is what Kismet
has; U on field semantics past raw_lat]

### 1.4 Subcommand 0x10 — **version 2** (Kismet K2 commented `case 2`, BEN Fig. 10) [P/U]

Same header through `raw_lat` (r+0..r+28), then:

| r+   | size | type  | field         | notes |
|------|------|-------|---------------|-------|
| 29   | 2    | s2le  | height        | Kismet: `read_s2le() / 10` ("barometric actual height") |
| 31   | 2    | s2le  | altitude      | "height since takeoff" |
| 33   | 2    | s2le  | v_north       | |
| 35   | 2    | s2le  | v_east        | |
| 37   | 2    | s2le  | v_up          | |
| 39   | 2    | s2le  | raw_yaw       | **no pitch/roll in v2** (BEN: "there are no pitch angles or roll angles — only yaw") |
| 41   | 8    | u8le  | gps_time      | BEN: "pilot GPS clock ... milliseconds since epoch (1 Jan 1970)" (phone/app GPS time) |
| 49   | 4    | s4le  | raw_app_lat   | pilot/phone latitude, /174533.0  (**lat before lon** here) |
| 53   | 4    | s4le  | raw_app_lon   | pilot/phone longitude, /174533.0 |
| 57   | 4    | s4le  | raw_home_lon  | /174533.0 |
| 61   | 4    | s4le  | raw_home_lat  | /174533.0 |
| 65   | 1    | u1    | product_type  | table 1.7 |
| 66   | 1    | u1    | uuid_len      | |
| 67   | ≤20  | bytes | uuid          | |

v2 record through uuid_len is 67 bytes (+1 subcommand = 68), so in a 76-byte
truncated flight_info only 8 UUID bytes fit; later firmware may send longer
IEs. **Always bound every read by the IE length byte.** BEN's figures are
schematic (every field drawn as "2 bytes"); field *order* above follows Kismet's
code, which agrees with BEN's order. Kismet (K5) copies `app_lat/app_lon` into
the uav.device "app location" and `home_lat/home_lon` into "home location".

BEN's OcuSync captures label these the same way (packet types 0x1001 = flight
info v1, 0x1002 = v2, 0x11 = license) — the OcuSync DroneID payload is the same
record family carried over a different radio.

### 1.5 Subcommand 0x11 — flight_purpose ("license" packet) (K2/K3, BEN Fig. 8) [P]

| r+ | size   | type  | field          | notes |
|----|--------|-------|----------------|-------|
| 0  | 16     | ASCII | serialnumber   | NUL-padded |
| 16 | 1      | u1    | drone_id_len   | |
| 17 | 10     | ASCII | drone_id       | fixed 10-byte slot; use `substr(0, drone_id_len)` (Kismet). User-entered "Drone ID"/registration string from DJI GO 4 |
| 27 | 1      | u1    | purpose_len    | Kismet: "DJI also mis-transmits this due to a sw bug" |
| 28 | rest   | ASCII | purpose        | Kismet: read to end of IE then `substr(0, purpose_len)`; nominally ~100 bytes but truncated by the 76-byte bug (max 47 bytes reach the air) |

Kaitai (K3) types `len`/`purpose_len` as `u8` which is a Kaitai typo for u1
(Kismet .cc reads `read_u1()`).

### 1.6 state_info bitfield (u16le at r+3) (K1 `.h`, K3 `.ksy`) [P]

| bit mask | Kismet accessor               | meaning (Kaitai doc in quotes) |
|----------|-------------------------------|--------------------------------|
| 0x0001   | state_serial_valid()          | "Serial is valid" |
| 0x0002   | .ksy: state_user_private_disabled; .h: `state_user_privacy_enabled() = (state & 0x02) == 0` | "private mode disabled (set to 1)" → bit **clear** = user privacy/private mode ON |
| 0x0004   | state_homepoint_set()         | "firmware unclear; could be conflated with uuid bit" |
| 0x0008   | state_uuid_set()              | "firmware unclear; could be conflated with homepoint bit" |
| 0x0010   | state_motor_on()              | motors on |
| 0x0020   | state_in_air()                | in air |
| 0x0040   | state_gps_valid()             | "Guessed; GPS fields may be valid?" |
| 0x0080   | state_alt_valid()             | "Guessed; Altitude GPS record valid?" |
| 0x0100   | state_height_valid()          | "Guessed; Height-over-ground valid?" |
| 0x0200   | state_horiz_valid()           | "Guessed; Horizontal velocity valid?" |
| 0x0400   | state_vup_valid()             | "Guessed; V_up velocity valid?" |
| 0x0800   | state_pitchroll_valid()       | "Guessed; pitch/roll/yaw valid?" |
| 0x1000+  | —                             | undocumented |

D13 (p.15) describes the flight-controller "private mode" options that drive
these bits/fields: (1) disable sending state information, (2) disable sending
home location, (3) hide drone ID in the flight-purpose packet, (4) send a "fake"
instead of the real serial number. DJ4 (Dec 2017): DJI GO 4 gained a "remote
identification" menu with opt-in "UUID" and "Identification & Flight
Information"; "By default, the settings in the app are set to not broadcast any
information" (refers to the voluntary UUID/purpose fields; telemetry + serial
beaconing itself was on). Practical consequence: expect many frames with
serial_valid=0 / all-zero or placeholder serial, uuid_len=0, home=0.

### 1.7 product_type codes (K1 `product_type_str()` verbatim strings, merged with BEN Table IV "AeroScope ID") [P]

| code | model (Kismet string / BEN)      | code | model |
|------|----------------------------------|------|-------|
| 1    | Inspire 1 (Kismet typo "Instpire 1") | 36 | Phantom 4 Pro V2.0 |
| 2,3  | Phantom 3 Series (BEN: 2 = P3, 3 = P3 Pro) | 38 | MG1P |
| 4    | Phantom 3 Std                    | 40   | MG1P-RTK (Kismet typo "MV1P-RTK") |
| 5    | M100                             | 41   | Mavic 2 |
| 6    | ACEONE                           | 44   | M200 V2 Series |
| 7    | WKM                              | 51   | Mavic 2 Enterprise |
| 8    | NAZA                             | 53   | Mavic Mini |
| 9    | A2                               | 58   | Mavic Air 2 |
| 10   | A3                               | 59   | P4M (P4 Multispectral) |
| 11   | Phantom 4                        | 60   | M300 RTK |
| 12   | MG1                              | 61   | DJI FPV |
| 14   | M600                             | 63   | Mini 2 |
| 15   | Phantom 3 4K                     | 64   | AGRAS T10 |
| 16   | Mavic Pro                        | 65   | AGRAS T30 |
| 17   | Inspire 2                        | 66   | Air 2S |
| 18   | Phantom 4 Pro                    | 67   | M30 (BEN only) |
| 20   | N2                               | 68   | Mavic 3 |
| 21   | Spark                            | 69   | Mavic 2 Enterprise Advanced |
| 23   | M600 Pro                         | 70   | Mini SE |
| 24   | Mavic Air                        | 73   | Mini 3 Pro (BEN only) |
| 25   | M200                             | 240  | Yuneec H480 (BEN only; non-DJI) |
| 26   | Phantom 4 Series                 |      | |
| 27   | Phantom 4 Adv                    |      | |
| 28   | M210                             |      | |
| 30   | M210RTK                          |      | |
| 31   | A3_AG                            |      | |
| 32   | MG2                              |      | |
| 34   | MG1A                             |      | |
| 35   | Phantom 4 RTK                    |      | |

Unknown → Kismet prints `Unknown (N)`. Only codes for WiFi-link aircraft (4?,
15?, 16, 21, 24, 53, 70) can realistically appear in a WiFi beacon; the rest
appear in OcuSync DroneID bursts (SDR only).

### 1.8 Suggested validation (receiver side)

* IE len ≥ 7 + 29 (through raw_lat) before touching telemetry; v2 needs ≥ 7+67.
* Serial: 16 printable ASCII or NULs; `state & 0x01` should be set.
* lat/lon: nonzero and |lat| ≤ 90, |lon| ≤ 180 after /174533.0; honour
  `state & 0x40`.
* Treat `58 62 13` as soft check only.
* Correlate the 0x10 and 0x11 packets by the BSSID (same AP) and serial.

---------------------------------------------------------------------------

## 2. Which DJI aircraft emit DroneID in 802.11 beacons

Background: DJI link types are Enhanced WiFi (802.11-based), Lightbridge and
OcuSync (proprietary OFDM, LTE-like, 10 MHz, Zadoff-Chu sync; center freqs
2399.5–2474.5 / 5741.5–5831.5 MHz per BEN Table II). DroneID exists on all
three, but **only the WiFi variant is a standard 802.11 beacon IE** that a WiFi
chip can receive. OcuSync/Lightbridge DroneID needs an SDR (proto17/dji_droneid,
RUB-SysSec DroneSecurity, ANTSDR firmware). [P: BEN, D13 p.18]

| aircraft (DJI model code) | link | 26:37:12 beacon? | who transmits | SSID seen | evidence |
|---|---|---|---|---|---|
| **Mavic Pro / Platinum** (WM220) in **WiFi mode** | 802.11 AP on aircraft | **Yes** | aircraft | `Mavic-XXXXXX` (Kismet regex `^Mavic-[0-9A-F]{6}$`), also `Mavic_` | D13: "Currently, two DJI products include Wi-Fi: the Mavic and the Spark... DJI implemented the Drone ID features on Mavic in mid-July, 2017"; DJ4: RID firmware "starting with the Mavic Pro". In RC/OcuSync mode: not receivable. [P] |
| **Spark** (WM100) | Enhanced WiFi; aircraft is AP, RC is client+AP | **Yes** | aircraft (flight_info lives in aircraft's `dji_network`/ath6kl) | aircraft `Spark-XXXXXX`; RC `Spark-RC-XXXXXX` (pwd 12341234) | D13 (ath6kl_usb.ko in "DJI Mavic and Spark"); FWT: Spark FW 03.02.43.20 (2017-09-20) symbol map contains `aSetDroneidSLen`, `aGetDroneIdFail`, `aSetUuidS`, `aSetUserPrivFai` → DroneID set/get + user-privacy commands present. [P] |
| **Mavic Air (1)** (U11X) | Enhanced WiFi, aircraft AP | **Yes** [P/S] | aircraft | `MavicAir-XXXXXX` (forum) | BEN: "Enhanced Wi-Fi protocol is used by older DJI Spark and Mavic Air models"; product_type 24 exists. |
| **Mavic Mini (1)** (MT1SS5) | Enhanced WiFi | **Yes, but** see note | aircraft | RC↔aircraft link reportedly hides SSID (mavicpilots) | product_type 53; BEN caught a Mavic Mini *license* packet (0x11) with his receiver; Mini SE (same radio family) shown in cleartext by K. Finisterre (BEN §I). Whether the Enhanced-WiFi link beacons are standard 20 MHz beacons an ESP32 can demodulate is **[U]** — BEN claims DJI Enhanced-WiFi beacons use **5 MHz bandwidth** needing quarter-rate Atheros cards, but his WiFi PoC "was not able to be tested against any DJI or Parrot drones", while Kismet decoded Spark/Mavic beacons with ordinary cards in 2017. Expect: phone-direct WiFi mode = standard; RC link = possibly not. |
| **Mini SE** | Enhanced WiFi | **Yes** (cleartext DroneID over Enhanced WiFi, Finisterre/The Verge Apr 2022, cited by BEN) | aircraft | — | product_type 70. Same bandwidth caveat. [S] |
| **Phantom 3 Standard / 4K / SE** | 2.4 GHz WiFi video downlink from the **RC's range extender** (AP); 5.8 GHz proprietary control | **Unverified / probably no** | RC extender is the AP (`PHANTOM3_XXXXXX`, P3M) | `PHANTOM3_XXXXXX` | Kismet matches P3 Std by SSID only (`^Phantom3_.*`, OUI 60:60:1F), no IE. product_type 4/15 exist for AeroScope but no WiFi-IE capture found. [U] |
| **Ryze Tello / Tello EDU / RoboMaster TT** | plain 802.11 AP on aircraft (DJI/Intel module) | **No evidence** | aircraft | `TELLO-XXXXXX`, `RMTT-XXXXXX` (RYZ) | Kismet SSID-only rule `^TELLO.*`. MAC OUI 60:60:1F (DJI). [S] |
| Mavic 2 / Mavic Air 2 / Mini 2 / Air 2S / Mavic 3 / Mini 3/4 Pro / Air 3 / FPV / Avata / Phantom 4 / Inspire / Matrice | OcuSync 2/3/4 (Lightbridge for P4/Inspire 1) | **No** (DroneID is inside OcuSync bursts) | — | WiFi-visible only as QuickTransfer hotspots (`DJI-MAVIC3…`, `DJI-MINI3-Pro-…`) and ASTM RID beacons (`RID-…`, §5) | BEN; Kismet uav.conf. |

Additional operational facts: the 26:37:12 IE appears only after motors start
(D13); 0x10/0x11 alternate every 200 ms (D13); the aircraft, not the RC, builds
the IE (D13 Figs. 12-13: `dji_network` → `/sys` `dji_ie` → `ath6kl_wmi_set_appie_cmd`).
For Spark the RC's own `Spark-RC-…` AP is a separate 802.11 interface; expect
the DroneID IE on the aircraft BSSID. [P/U for RC-side absence]

---------------------------------------------------------------------------

## 3. IEEE OUIs registered to DJI (and Ryze)

Verified 2026-10-02 via maclookup.app vendor page + per-prefix API (IEEE MA-L
mirror); 60:60:1F and E4:7A:2C additionally confirmed by api.macvendors.com.
Direct fetch of standards-oui.ieee.org / Wireshark `manuf` was not possible
(files too large for the fetch tool) — all ten rows carry identical registrant
text, which is the IEEE string. [P via mirror]

Registrant on all rows: **"SZ DJI TECHNOLOGY CO.,LTD"**, DJI Sky City, No55
Xianyuan Road, Nanshan District, Shenzhen Guangdong 518057, CN. All MA-L (/24).

| OUI       | MA-L registered / last updated | notes |
|-----------|-------------------------------|-------|
| 60:60:1F  | 2013-03-11 (upd. 2023-10-19)  | the classic one: Spark, Mavic, Phantom 3, Tello, Osmo; also seen as BSSID of ASTM RID beacons (`60:60:1f:02:d4:f9`, Mavic 3E, ODI #99) |
| 34:D2:62  | 2019-08-13                    | listed by BEN as DJI "vendor tag" |
| 48:1C:B9  | 2022-05-07                    | listed by BEN |
| E4:7A:2C  | 2023-10-19                    | |
| 58:B8:58  | 2024-07-26                    | |
| 04:A8:5A  | 2025-01-09                    | |
| 8C:58:23  | 2025-05-27                    | |
| 0C:9A:E6  | 2025-08-14                    | |
| 88:29:85  | 2025-10-29                    | |
| 4C:43:F6  | 2025-12-01                    | |

* **Ryze Tech (Shenzhen Ryze Technology Co., Ltd.)**: no OUI found in any
  lookup; Tello MACs use **60:60:1F** (multiple Tello/SDK write-ups report
  `60:60:1F:xx` on Tello). Treat Ryze = DJI OUI + `TELLO-`/`RMTT-` SSID. [S]
* The DroneID IE OUI **26:37:12 is not an IEEE OUI** (locally-administered bit
  set) and must be matched literally in the IE, not against MAC addresses.
* Caveat: RID beacons / QuickTransfer hotspots on new aircraft may use
  randomized or different OUIs; the 60:60:1F capture in ODI #99 shows at least
  Mavic 3 Enterprise used a DJI OUI for RID.

---------------------------------------------------------------------------

## 4. DJI / Ryze SSID patterns

Kismet `kismet_uav.conf` rules (verbatim regexes, all with
`mac=60:60:1F:00:00:00/FF:FF:FF:00:00:00`, default = both MAC **and** SSID must
match) [P: K4]:

    dji_phantom   model="Phantom 3 Standard" ssid="^Phantom3_.*"
    dji_mavic     model="Mavic"              ssid="^Mavic_.*"
    dji_m1p       model="Mavic 1 Pro"        ssid="^Mavic-[0-9A-F]{6}$"
    dji_mavic_3   model="Mavic 3"            ssid="^DJI-MAVIC3.*"
    dji_mini3_pro model="Mini3 Pro"          ssid="^DJI-MINI3-Pro-.*"
    dji_spark     model="Spark"              ssid="^Spark-(?!RC-).*"
    dji_spark_rc  model="Spark RC"           ssid="^Spark-RC-.*"
    dji_tello     model="Tello"              ssid="^TELLO.*"
    dji_osmo      model="Osmo"               ssid="^OSMO_.*"

Consolidated table for a labeller (use **case-insensitive** matching; DJI
manuals print `PHANTOM3_` upper-case while Kismet uses `Phantom3_`):

| SSID pattern | device | side / role | DroneID IE expected? | source |
|---|---|---|---|---|
| `Mavic-XXXXXX` (6 hex) / `Mavic_…` | Mavic Pro/Platinum in WiFi mode | aircraft AP | yes | K4 |
| `MavicAir-XXXXXX` | Mavic Air (1) | aircraft AP | yes | FOR (forum.dji.com 146483) |
| `Spark-XXXXXX` (not `Spark-RC-`) | Spark | aircraft AP | yes | K4 |
| `Spark-RC-XXXXXX` | Spark remote controller | RC AP (phone side) | no (RC) | K4, FOR |
| `PHANTOM3_XXXXXX` | Phantom 3 Standard/4K/SE | RC range-extender AP | unverified/no | P3M, K4 |
| `TELLO-XXXXXX` | Ryze Tello / Tello EDU | aircraft AP | no | RYZ, K4 |
| `RMTT-XXXXXX` | RoboMaster TT (Tello Talent w/ expansion kit) | aircraft AP | no | RYZ |
| `DJI-MAVIC3…` | Mavic 3 family QuickTransfer WiFi | aircraft hotspot (file transfer) | no (OcuSync aircraft) | K4 |
| `DJI-MINI3-Pro-…` | Mini 3 Pro QuickTransfer | aircraft hotspot | no | K4 |
| `RID-<20 alnum>` e.g. `RID-1581F5FHB229F00202DR` | any current DJI aircraft with built-in Remote ID | aircraft RID beacon (ASTM F3411 IE, OUI FA:0B:BC) | no — route to ODID parser | DJ1, DJ2, DJ3, ORE |
| `OSMO`, `OSMO_…`, `Osmo Pocket…`, `OsmoAction…` | Osmo gimbals/cameras (default pwd 12341234) | camera/gimbal, not aircraft | no | K4, FOR |
| `DJI RC…` / RC hotspot | DJI RC / RC-N1 remote hotspot | RC | no | FOR (forum.dji.com 282641) [U exact format] |
| `Mavic Mini` link | Mavic Mini / Mini SE RC↔aircraft Enhanced WiFi | aircraft | yes (but SSID reportedly not broadcast) | FOR mavicpilots [U] |

Labelling rule of thumb: `*-RC-*`, `DJI RC`, `OSMO*`, `Ronin*` → "DJI
controller/accessory"; `Mavic-`, `MavicAir-`, `Spark-` (non-RC), `TELLO-`,
`RMTT-`, `DJI-MAVIC3`, `DJI-MINI3` → "DJI aircraft (WiFi link)"; `RID-` →
"ASTM Remote ID beacon" (parse the FA:0B:BC IE instead). Any 60:60:1F / other
DJI-OUI BSSID with no SSID match → "DJI device (unknown role)".

---------------------------------------------------------------------------

## 5. How DJI implements ASTM F3411 / Open Drone ID today

**Transport.** WiFi **Beacon** only; no Bluetooth 4/5 and no NAN observed.
DJ1/DJ2: verify by scanning WLAN networks for a name "prefixed with 'RID-'
followed by a 20-digit alphanumeric Remote ID serial number"; SKY: "DJI
implemented WiFi Beacon-based Remote ID broadcasts in their standard Remote ID
drones"; ODI #93 (Nov 2022): Air 2S firmware "added RID support through WiFi
Beacon"; ODI #99: Mavic 3 Enterprise captured as `transportType=Beacon`.
Channel: 2.4 GHz **channel 6** (the ASTM "social channel"; ORE states DJI uses
"WiFi beacon vendor IE on channel 6"; SKY-spy/orecchino receivers park on ch 6
and hear DJI). [P for Beacon; S for ch 6]

**Frame content** (ODI #99 hex dump, Mavic 3E, BSSID `60:60:1f:02:d4:f9`,
msgVersion 2) [P]:

    F1 | F2 19 03 | 02 12 "1581F5FHB229F00202DR" ... | 12 ... | 42 ...
    ^counter  ^Message Pack (type 0xF, proto v2), 0x19=25-byte msgs, 3 msgs
              ^Basic ID: IDtype=1 (Serial), UAtype=2 (Helicopter/Multirotor)
                                            ^Location (0x1)      ^System (0x4)

→ DJI sends a **Message Pack** of three messages: **Basic ID (ID type 1 =
CTA-2063-A serial, UA type 2)**, **Location**, **System** (operator location
type 1 = dynamic/take-off, classification 0 in US). No Self-ID, no Operator ID,
no Auth in US captures. Serial = 20-char `1581F…` (DJ2: the "20-digit format
(prefixed 1581F)" equals the flight-controller S/N on newer models; older
Agras T30 use a 14-digit RID serial that differs from the FC serial).

**Broadcast conditions (geofenced).** DJ1/DJ2: RID is broadcast only when
(1) the aircraft has built-in RID, (2) it is "within airspace of the United
States", (3) "the drone's motors began to spin". Firmware notes added Japan
("Added support for Japanese RID requirements"); outside enabled regions the
aircraft sends nothing (FOR phantomhelp: "Remote ID will not broadcast when
outside of the US"). Mini 3 / Mini 4 Pro: RID only with Intelligent Flight
Battery Plus (>250 g config); SKY: both "stopped transmitting Remote ID entirely
in their default configuration" (Feb 2024). Mini 3 Pro: always. [P]

**EU / Operator ID.** DJ3/THD: DJI's EU Remote ID transmits "Drone Operator
Registration Number, Drone Identification Number, Geographical Position, route
course and speed of the Drone, Geographical Position of the Pilot, Time Stamp,
Drone emergency status". The ORN (incl. 3-char PIN) is entered in DJI Fly /
DJI Pilot 2 → GEO Zone map → **RID** button → "User registration number", and
"will automatically synchronize to your aircraft". So in the EU the pack should
also carry an **Operator ID message (type 5, operator ID type 0)** — stated by
DJI, **not independently captured in this research** [S]. EU-RID-capable DJI
models per DJ3: Mini 4 Pro (**with C1 certification**), Air 3, Mavic 3 Pro/Cine,
Mavic 3 Classic, Mavic 3/Cine; Enterprise M30/M30T (+Dock), M350, M3E/T/M.
Forum consensus: Mini 3 Pro (no class mark) does **not** broadcast EU RID. [S]

**Quirks for a receiver.**
* SKY: inconsistent use of **home vs app (pilot) location** in the System
  message and inconsistent **HAE vs MSL altitude**, varying by firmware.
* Serial in `RID-` SSID should equal Basic-ID serial (ORE flags mismatches).
* ODI #99 payload shows the pack repeated ~every second with alternating
  counter byte (F1 → 00 …).
* ORE (2026 firmware note, [U]): DJI co-locates China **GB 46750-2025** RID in
  the same vendor IE as ASTM.
* Proprietary DroneID (26:37:12 on WiFi aircraft; OcuSync bursts on everything
  else) continues **in parallel and worldwide** regardless of RID geofencing —
  it is what AeroScope reads.

---------------------------------------------------------------------------

## 6. Implementation checklist (ESP32-S3 promiscuous RX)

1. In the beacon IE walk, add: `id==0xDD && len>=7 && oui==26 37 12` →
   `dji_droneid_parse(payload+3, len-3)`. Keep the existing `FA:0B:BC/0x0D`
   (ASTM) path untouched.
2. `subcmd = payload[3]`; 0x10 → read version; v1 per §1.3, v2 per §1.4; stop
   at `len`. 0x11 → §1.5 with `min(purpose_len, remaining)`.
3. Emit: serial (16), lat/lon (/174533.0), alt/height raw, vN/vE/vU raw,
   yaw(/100 °), home lat/lon, app lat/lon (v2), product_type + name, uuid,
   state bits (motor_on, in_air, gps_valid, serial_valid, privacy).
4. Fingerprint layer: BSSID OUI ∈ {§3 list} and/or SSID ∈ {§4 regexes,
   case-insensitive} → label aircraft / RC / camera; `RID-` → ASTM.
5. Channel plan: DJI WiFi aircraft APs sit on any 2.4 (or 5 GHz for Mavic Air /
   Spark 5.8) channel, so keep hopping; ASTM RID from DJI is on ch 6.
6. Expect no DroneID IE until motors spin; expect privacy-blanked serials.
