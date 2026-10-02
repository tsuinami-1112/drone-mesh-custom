# Drone Mesh Mapper - Node Mode

**colonelpanichacks**

Two firmwares for the Seeed XIAO ESP32S3 paired with a Heltec V3 running Meshtastic. Remote nodes detect drones. Home node receives detections from the mesh and feeds them to [mesh-mapper.py](https://github.com/colonelpanichacks/drone-mesh-mapper).

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                        REMOTE NODE (field)                      │
  │  XIAO ESP32S3 ──UART──> Heltec V3 (Meshtastic) ──LoRa──>      │
  │  WiFi + BLE drone       GPIO5 TX -> Heltec RX                  │
  │  detection               GPIO6 RX <- Heltec TX                 │
  │  Remote ID (BLE4, BLE5 Long Range, NAN, Beacon),               │
  │  DJI DroneID, MAVLink, WiFi/BLE fingerprints                   │
  └─────────────────────────────────────────────────────────────────┘
                                  │
                           LoRa Mesh Network
                          (multiple hops OK)
                                  │
  ┌─────────────────────────────────────────────────────────────────┐
  │                        HOME NODE (base)                         │
  │  Heltec V3 (Meshtastic) ──UART──> XIAO ESP32S3 ──USB──>       │
  │  receives mesh data       GPIO6 RX <- Heltec TX    computer    │
  │                           GPIO5 TX -> Heltec RX    running     │
  │  NO detection.            dedup engine             mesh-mapper  │
  │  Just a smart bridge.                                           │
  └─────────────────────────────────────────────────────────────────┘
```

## The Multi-Node Problem

When you deploy 5 remote nodes and a drone flies overhead, all 5 nodes detect the same drone and send JSON over the mesh. Without dedup, `mesh-mapper.py` would see 5 duplicate detections for 1 drone.

### How We Solve It

**Remote nodes** tag every detection with a unique `node_id` derived from their ESP32 hardware MAC:

```json
{"mac":"aa:bb:cc:dd:ee:ff","rssi":-62,"node_id":"A1B2","drone_lat":52.520008,"drone_long":13.404954,"drone_altitude":120,"pilot_lat":52.518,"pilot_long":13.4,"basic_id":"1581F5FHB229F00202DR","op_id":"DEU87astrdge12k8","id_type":1,"src":"odid_bcn","ua_type":2,"eu_cat":1,"eu_class":2}
```

**Home node** runs a dedup engine keyed on drone MAC address:

- **First detection** for a new drone MAC: **forwarded instantly** (zero delay)
- **Duplicates** from other nodes within **500ms**: **dropped** (same detection event from different nodes)
- **After 500ms**: next detection goes through (drone moved, new position data)
- **Result**: near real-time tracking, no multi-node spam

Remote nodes send Remote ID / DJI / MAVLink detections as fast as they happen with no artificial rate limiting; heuristic fingerprint hits are limited to one per device per 30 s. Meshtastic handles its own channel queuing. The 500ms dedup window at the home node is tight enough to squash the burst of multi-node duplicates while letting every new position update flow through.

---

## Hardware

### Per Node (Remote or Home)

| Component | Purpose |
|---|---|
| **Seeed XIAO ESP32S3** | Detection (remote) or bridge (home) |
| **Heltec WiFi LoRa 32 V3** | Meshtastic mesh radio |
| **3 wires** | TX, RX, GND between XIAO and Heltec |

### Wiring

```
XIAO ESP32S3          Heltec V3
─────────────         ──────────
GPIO5 (TX)  ───────>  RX
GPIO6 (RX)  <───────  TX
GND         ────────  GND
```

Same wiring for both remote and home nodes. Only the firmware differs.

---

## Building & Flashing

Requires [PlatformIO](https://platformio.org/). The protocol parsers come from
the shared library in `../firmware-common/detect` (referenced through
`lib_extra_dirs`), and BLE comes from `h2zero/NimBLE-Arduino` so that BLE 5
Long Range Remote ID is received. Both are fetched automatically.

### Build Both

```bash
pio run
```

### Flash Remote Node (detection board)

```bash
pio run -e remote_node -t upload
```

### Flash Home Node (receiving bridge)

```bash
pio run -e home_node -t upload
```

### Monitor Serial Output

```bash
pio run -e remote_node -t monitor
pio run -e home_node -t monitor
```

### Detection knobs (add to `build_flags` of `remote_node`)

| Flag | Default | Effect |
|---|---|---|
| `-DDETECT_WIFI_HOP=0` | hopping on | Stay on channel 6 only: maximum Remote ID duty cycle, no DJI WiFi-link / toy-drone / bridge access points on other channels |
| `-DDETECT_HOME_DWELL_MS=700` | 700 | Time on channel 6 between excursions |
| `-DDETECT_AWAY_DWELL_MS=250` | 250 | Time on each other channel |
| `-DDETECT_MAVLINK=0` | on | Do not capture data frames (MAVLink on open WiFi) |
| `-DDETECT_FINGERPRINT=0` | on | Drop heuristic hits (devices without Remote ID) |

### Test the parsers on your computer

```bash
cd ../firmware-common/test && make
```

---

## Firmware Details

### Remote Node (`main_remote.cpp`)

Dual-core drone detection firmware.

- **Core 0**: WiFi promiscuous mode. Open Drone ID NAN action frames and beacon vendor IEs, DJI DroneID beacon IEs, MAVLink telemetry in unencrypted data frames, SSID / MAC-prefix fingerprints. Hops across 2.4 GHz channels, weighted to channel 6.
- **Core 1**: BLE scanning (NimBLE, passive, duplicates on). Open Drone ID over BLE 4 legacy adverts **and** BLE 5 Long Range extended adverts (message packs), plus BLE name / company-ID fingerprints.
- Every Open Drone ID message type is decoded: both Basic IDs, Location, System (operator position, EU class), Operator ID, Self ID.
- Sends JSON to USB Serial (local monitoring) and UART Serial1 (Heltec V3 mesh). The mesh line is budgeted to one Meshtastic packet; USB gets the full record.
- Each detection tagged with unique `node_id` for home node dedup
- LED blinks on each detection
- Heartbeat every 60s

### Home Node (`main_home.cpp`)

Lean mesh-to-USB bridge with dedup. No detection.

- Reads JSON lines from Heltec V3 over UART
- Deduplicates by drone MAC (500ms window, first-in wins)
- Forwards clean data to USB Serial for `mesh-mapper.py`
- Non-JSON lines (Meshtastic debug) forwarded with `[MESH]` prefix
- Host commands (`WATCHDOG_RESET`, `STATUS`) answered locally; nothing from USB is ever forwarded to the mesh
- Heartbeat every 30s with active drone count
- Stats every 60s (received/forwarded/suppressed counts)
- Stale dedup entries auto-cleared after 30s
- LED blinks on each forwarded message

---

## JSON Format

All drone detections use this JSON format (one per line). Fields are omitted
when the value is unknown.

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "rssi": -62,
  "node_id": "A1B2",
  "drone_lat": 52.520008,
  "drone_long": 13.404954,
  "drone_altitude": 120,
  "pilot_lat": 52.518,
  "pilot_long": 13.4,
  "basic_id": "1581F5FHB229F00202DR",
  "op_id": "DEU87astrdge12k8",
  "id_type": 1,
  "src": "odid_bcn",
  "ua_type": 2,
  "eu_cat": 1,
  "eu_class": 2,
  "height": 80,
  "speed": 13,
  "heading": 123
}
```

| Field | Description |
|---|---|
| `mac` | Drone's (or controller's) broadcast MAC address, the tracking key |
| `rssi` | Signal strength at detecting node |
| `node_id` | Which remote node detected it (4-char hex from ESP32 MAC) |
| `drone_lat` / `drone_long` | Drone GPS position |
| `drone_altitude` | Altitude in metres (geodetic / MSL) |
| `pilot_lat` / `pilot_long` | Operator / pilot phone position |
| `basic_id` | Remote ID UAS ID #1 (serial number, or a national registration ID where that is what is broadcast) |
| `op_id` | Operator ID: the EU / UK registration number |
| `id_type` | 1 serial, 2 CAA registration, 3 UTM UUID, 4 session ID |
| `src` | `odid_ble`, `odid_ble5`, `odid_nan`, `odid_bcn`, `dji`, `mavlink`, `wifi`, `ble` |
| `vendor` / `model` / `ssid` / `conf` / `role` | Manufacturer, model, network name, confidence and device role for DJI DroneID and fingerprint hits |
| `ua_type`, `eu_cat`, `eu_class`, `basic_id2`, `id_type2`, `height`, `speed`, `heading`, `status`, `ch`, `desc`, `home_lat`/`home_long`, `sysid`/`mavtype`/`autopilot`/`armed` | See `../firmware-common/README.md` |

---

## Project Structure

```
node-mode/
├── platformio.ini        # Two build environments: remote_node, home_node
├── src/
│   ├── main_remote.cpp   # Remote node - WiFi+BLE detection + mesh send
│   └── main_home.cpp     # Home node - UART bridge + dedup engine
├── .gitignore
└── README.md
../firmware-common/detect # Shared parsers: Open Drone ID, DJI DroneID, MAVLink, fingerprints
```

---

## Heltec V3 Meshtastic Setup

The Heltec V3 boards run stock [Meshtastic firmware](https://meshtastic.org/). Enable the **Serial Module** in Meshtastic settings:

1. Flash Meshtastic to both Heltec V3 boards
2. Enable Serial Module: `meshtastic --set serial.enabled true`
3. Set Serial Mode to **TEXTMSG**: `meshtastic --set serial.mode TEXTMSG`
4. Set baud rate to **115200**: `meshtastic --set serial.baud BAUD_115200`
5. Set the serial pins to match wiring (RX/TX pins the Heltec uses to talk to the XIAO)

Both Heltec boards should be on the same Meshtastic channel/encryption key.

---

## Usage with mesh-mapper.py

1. Flash **remote node** firmware to field XIAO boards
2. Flash **home node** firmware to the base XIAO board
3. Set up Meshtastic on all Heltec V3 boards (same channel)
4. Wire each XIAO to its Heltec V3 (TX, RX, GND)
5. Plug the home XIAO into the computer running mesh-mapper.py via USB
6. Run: `python3 mesh-mapper.py`
7. mesh-mapper.py auto-detects the USB serial port and starts mapping

---

## License

MIT
