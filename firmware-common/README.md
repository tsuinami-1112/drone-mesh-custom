# firmware-common - shared detection library

Every firmware variant in this repository (`node-mode-dualcore`,
`remoteid-mesh-dualcore`, `remoteid-c5-5g`, `remoteid-mesh`) does its protocol
parsing through the one library in `detect/`. The mains are reduced to radio
set-up, aggregation and serial I/O, and the parsers are plain C with no
Arduino or ESP-IDF dependency, so the exact code that runs on the XIAO ESP32
boards is compiled and unit-tested on a desktop:

```bash
cd firmware-common/test
make            # builds with gcc, runs the synthetic-frame tests, validates the JSON
```

PlatformIO picks the library up through `lib_extra_dirs = ../firmware-common`
in each variant's `platformio.ini`.

## What it detects

| Layer | Transport | What is decoded |
|---|---|---|
| **Open Drone ID** (ASTM F3411, ASD-STAN EN 4709-002) | BLE 4 legacy adverts | one 25-byte message per advert |
| | BLE 5 Long Range extended adverts (coded PHY) | Message Pack, up to 9 messages. Needs NimBLE with `CONFIG_BT_NIMBLE_EXT_ADV=1`; what EU and Japanese add-on modules transmit |
| | WiFi NAN action frames | Message Pack |
| | WiFi Beacon vendor IE (OUI `FA:0B:BC`, legacy `90:3A:E6`) | Message Pack |
| | *all of the above* | **both** Basic IDs (serial number and, where broadcast, a national registration ID), Location, System (operator position, EU category/class), **Operator ID** (the EU/UK registration number), Self ID text |
| **DJI DroneID** (proprietary) | WiFi Beacon vendor IE `26:37:12` | serial, aircraft position, home point, pilot-phone position (record v2), heading, model code; emitted by WiFi-link DJI aircraft (Spark, Mavic Pro WiFi mode, Mavic Air, Mavic Mini / Mini SE) worldwide, independent of Remote ID rules |
| **MAVLink** v1/v2 | UDP or TCP in 802.11 data frames on **open** WiFi | HEARTBEAT (type, autopilot, armed), GLOBAL_POSITION_INT, GPS_RAW_INT, HOME_POSITION and the OPEN_DRONE_ID_* set; every frame is CRC-checked incl. CRC_EXTRA |
| **Fingerprints** (heuristic) | WiFi beacons / probe responses / probe requests, BLE adverts | SSID patterns of drone and controller access points (DJI/Ryze, Parrot, Skydio, Autel, Yuneec, Hubsan, Holy Stone, Potensic, Snaptain, Ruko, FIMI, PowerVision, HOVERAir, Walkera, toy quads, FPV goggles, MAVLink WiFi bridges), IEEE MAC prefixes with 24/28/36-bit masking, BLE device names and Bluetooth SIG company IDs |

Heuristic hits never carry a position. They are rate-limited per device
(default one report per 30 s) and tagged with a confidence:

| `conf` | meaning |
|---|---|
| `high` | SSID pattern that only a specific aircraft uses |
| `med` | controller / accessory / telemetry-bridge SSID, drone-only MAC registrant |
| `low` | vendor MAC prefix shared with cameras and headphones, a phone probing for a drone network |

## Detection JSON

One line per detection, consumed by `mesh-mapper.py`. Fields are omitted when
unknown. `detect_build_json()` writes the mandatory fields first and then adds
optional fields in priority order **only while they fit the buffer**, so a
230-byte buffer (one Meshtastic text message) always yields complete JSON and a
768-byte buffer (USB) carries everything.

| Field | Type | Meaning |
|---|---|---|
| `mac` | string | aircraft (or controller) radio MAC, the tracking key |
| `rssi` | int | dBm at the detecting node |
| `node_id` | string | 4-hex-char remote node ID (node mode only) |
| `drone_lat`, `drone_long` | float | aircraft position (degrees), absent when unknown |
| `drone_altitude` | int | geodetic (WGS84) or MSL altitude, metres |
| `pilot_lat`, `pilot_long` | float | operator / pilot phone position |
| `basic_id` | string | Remote ID UAS ID #1 |
| `op_id` | string | **Operator ID** - the EU / UK / Swiss / Norwegian registration number |
| `id_type` | int | 1 serial number (ANSI/CTA-2063-A), 2 CAA registration ID, 3 UTM UUID, 4 session ID |
| `src` | string | `odid_ble`, `odid_ble5`, `odid_nan`, `odid_bcn`, `dji`, `mavlink`, `wifi` (fingerprint), `ble` (fingerprint) |
| `vendor`, `model` | string | manufacturer and model from DJI DroneID or a fingerprint rule |
| `conf` | string | `high` / `med` / `low`, heuristics only |
| `role` | string | `aircraft` / `controller` / `accessory`, heuristics and DJI |
| `ua_type` | int | Open Drone ID UA type (2 = helicopter or multirotor ...) |
| `eu_cat`, `eu_class` | int | EU category (1 open, 2 specific, 3 certified) and class (1 = C0 ... 7 = C6) |
| `basic_id2`, `id_type2` | string, int | second Basic ID, e.g. Japan's `JU` registration next to the serial |
| `height` | int | height above take-off / ground, metres |
| `speed` | int | horizontal speed, m/s |
| `heading` | int | degrees |
| `status` | int | 1 ground, 2 airborne, 3 emergency, 4 Remote ID system failure |
| `ch` | int | WiFi channel of the frame (36+ is 5 GHz) |
| `desc` | string | Self ID text, or the DJI user-entered "Drone ID" |
| `ssid` | string | network or BLE name behind a fingerprint / DJI hit |
| `home_lat`, `home_long` | float | take-off / home point (DJI, MAVLink) |
| `sysid`, `mavtype`, `autopilot`, `armed` | int | MAVLink system ID, MAV_TYPE, MAV_AUTOPILOT (3 ArduPilot, 12 PX4), armed flag |

## API in one screen

```c
#include "detect.h"

DetectRecord rec;
// 802.11 management frame from the promiscuous callback (beacon, probe, NAN action)
if (detect_wifi_mgmt(frame, len, rssi, channel, &rec)) ...
// 802.11 data frame -> MAVLink on an open network
if (detect_wifi_data(frame, len, rssi, channel, &rec)) ...
// BLE advertising payload; extended = BLE 5 extended advertising report
if (detect_ble_adv(addr, ad, ad_len, rssi, extended, &rec)) ...

// per-aircraft slot keeps identity across position-only frames
detect_record_merge(&slot, &rec);
// heuristics: one report per MAC per 30 s
if (detect_is_heuristic(rec.src) && !detect_throttle(rec.mac, millis(), 30000)) skip;
// serialise: 230 bytes for the LoRa mesh, 768 for USB
int n = detect_build_json(buf, sizeof buf, &slot, node_id);
```

`detect_wifi_*` share one static Open Drone ID scratch structure and
`detect_ble_adv` another, so call the WiFi functions from the WiFi task only
and the BLE function from the BLE task only (as the mains do).

## Radio configuration the mains apply

* **WiFi channel plan** - Remote ID lives on 2.4 GHz channel 6 (and 5 GHz
  149 on the C5), so the sniffer spends `DETECT_HOME_DWELL_MS` (700 ms) there,
  then visits one other channel for `DETECT_AWAY_DWELL_MS` (250 ms) and comes
  back. Channels 1-13 are cycled; 12/13 matter in Europe and Japan. DJI
  WiFi-link aircraft, toy-drone access points and telemetry bridges sit on
  whatever channel their AP picked, so without the excursions they are never
  seen. `-DDETECT_WIFI_HOP=0` pins channel 6 for maximum Remote ID duty cycle.
* **Data frames** are captured only for MAVLink (`-DDETECT_MAVLINK=0`
  disables). Encrypted frames are rejected on the Protected bit before any
  parsing, so the cost on a busy channel is small.
* **BLE** is scanned passively (Remote ID is non-connectable) on both the 1M
  and the coded PHY with duplicates reported, because a Remote ID transmitter
  re-uses its address with new data every second. The controller alternates
  PHYs per scan interval, so a BLE 5-only module can take a few seconds to be
  heard; the WiFi sniffer shares the 2.4 GHz radio and adds some loss.
* `-DDETECT_FINGERPRINT=0` drops all heuristic hits at the node.

## Adding a fingerprint rule

`detect/src/detect_fingerprint.c` holds three tables: SSID prefixes (case
insensitive, first match wins, so put `Spark-RC-` before `Spark-`), IEEE MAC
prefixes with their registered length (24 = MA-L, 28 = MA-M, 36 = MA-S; a /24
match on a 28-bit registrant's parent block is meaningless), and BLE names and
company IDs. Give each rule the confidence it deserves as a *drone* indicator,
add a case to `test/test_detect.c`, run `make`.

## Known limits

* MAVLink can only be decoded on open networks; nearly every commercial WiFi
  telemetry bridge ships with WPA2. The bridge still shows up as a fingerprint
  (`ArduPilot`, `PixRacer`, `DroneBridge`, `CUAVWLINK`, `mLRS-` ...).
* DJI DroneID over WiFi exists only on DJI's WiFi-link models and only once the
  motors run; OcuSync aircraft carry it on a proprietary link an SDR is needed
  for. Current DJI aircraft broadcast standard Remote ID (WiFi Beacon) instead,
  which the Open Drone ID layer decodes.
* Fingerprints are heuristics. A DJI MAC prefix is also an Osmo camera; a phone
  that once joined a Tello keeps probing for it. That is why they are
  confidence-tagged and shown separately in the mapper.
* China's GB 42590 / GB 46750 broadcast formats are not decoded.
