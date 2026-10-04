# <div align="center">**Drone Mesh Mapper**</div>

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![ESP32](https://img.shields.io/badge/ESP32-Compatible-green.svg)](https://www.espressif.com/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-red.svg)](https://flask.palletsprojects.com/)

**Real-time drone Remote ID detection · Meshtastic LoRa relay · live web map · fully offline-capable**

[Hardware](#hardware-options) ·
[Flashing](#build-and-flash-the-firmware) ·
[Quick Start](#quick-start) ·
[Features](#features) ·
[Reference](docs/REFERENCE.md)

<img src="eye.png" alt="Drone Detection Eye" style="width:50%; height:25%;">

</div>

---

## Overview

A solar-powered, 24-7 drone detection network communicating over a private mesh. Intended for around-the-clock area protection and privacy.

Developed in partnership with our friends in the Armed Forces of Ukraine. Special thanks to:

"Alik", 93rd OMBr

"Ivan", 427th Unmanned Aerial Brigade

ESP32 detection stations pick up drone broadcasts (Open Drone ID per ASTM
F3411 and ASD-STAN EN 4709-002 over BLE and WiFi, DJI DroneID, MAVLink, and
WiFi/BLE fingerprints), relay them over a Meshtastic LoRa mesh, and a Flask
web app draws them on a live map. Works in any country: it decodes what the
drone broadcasts and never depends on a national registry. Persistent
multi-session tracking, KML/CSV/GeoJSON export, and a self-contained offline
mode.

```
 FIELD STATION                                         HOME STATION
 XIAO ESP32-S3 --UART--> Heltec V4 ~~ LoRa mesh ~~> Heltec V4 --UART--> XIAO ESP32-S3 --USB--> mesh-mapper.py
 WiFi + BLE detection    (Meshtastic)   (multi-hop)   (Meshtastic)        dedup bridge          live web map
```

Level 1 stations (bearing-only detection of 5.8 GHz analog video links) are
developed on the [`level1`](../../tree/level1) branch.

---

## Hardware Options

### What you need per station

| Part | Notes |
|---|---|
| **Seeed XIAO ESP32-S3** | The detector (field station) or the mesh-to-USB bridge (home station) |
| **Heltec WiFi LoRa 32 V4** | Meshtastic mesh radio. Buy the band your region uses (863-928 MHz for EU868 / US915 / AU915 / ...) and the standard OLED model: the TFT model uses GPIO47/48 for its touchscreen |
| LoRa antenna | Usually ships with the Heltec. Fit it **before** powering the board: the V4 transmits up to 28 dBm |
| 4 jumper wires | Plus pin headers if your boards came without them |
| USB-C data cables | One per board for flashing; charge-only cables won't enumerate |
| Power | USB-C supply or power bank into the Heltec, or a 1S LiPo on its battery connector |

### Station types

| Station | Firmware | Where it goes |
|---|---|---|
| **Field station** | `node-mode-dualcore`, env `remote_node` | Out in the field. Detects drones and sends each detection over the mesh, tagged with its own `node_id` |
| **Home station** | `node-mode-dualcore`, env `home_node` | Plugged into the computer running `mesh-mapper.py`. Receives the mesh, drops duplicate reports of the same drone from several field stations, and forwards the rest over USB |
| **Standalone detector** | `remoteid-mesh-dualcore`, env `seeed_xiao_esp32s3` | Plugged straight into the mapper's computer. Also posts short text alerts with map links to the mesh, which any Meshtastic app can read but the mapper doesn't plot |

A typical deployment is several field stations and one home station. The
hardware and the wiring are the same for every station type. Only the firmware
and the power arrangement differ.

### Build a station

<details open>
<summary><b>Wiring: XIAO ESP32-S3 ↔ Heltec V4</b></summary>

```
 XIAO ESP32-S3                       Heltec WiFi LoRa 32 V4
 +----------------+                  +---------------------------+
 | D4 / GPIO5  TX |----------------->| 47   (Meshtastic RX pin)  |
 | D5 / GPIO6  RX |<-----------------| 48   (Meshtastic TX pin)  |
 | GND            |------------------| GND                       |
 | 3V3            |------------------| 3V3  (field station only) |
 +----------------+                  +---------------------------+
```

| Wire | XIAO ESP32-S3 | Heltec V4 pin | Carries |
|---|---|---|---|
| 1 | D4 (GPIO5, UART TX) | **47** | Detections from the XIAO to the mesh |
| 2 | D5 (GPIO6, UART RX) | **48** | Mesh traffic to the XIAO (what the home station bridges) |
| 3 | GND | GND | Common ground: always connect it |
| 4 | 3V3 | 3V3 | Heltec powers the XIAO. **Field station only** |

Pins 47 and 48 sit side by side on the header that carries 5V and Ve, the same
header as the 19/20 pins the V3 wiring used.

</details>

1. **Flash both boards first** ([firmware](#build-and-flash-the-firmware) on
   the XIAO, [Meshtastic](#set-up-the-heltec-v4-meshtastic) on the Heltec),
   while nothing is wired between them.
2. Screw the LoRa antenna onto the Heltec.
3. Solder headers or wires and make the connections in the table. Keep the
   wires short (under 20 cm) and cross TX to RX as shown.
4. Power it:
   - **Field station:** connect all four wires and power the Heltec only (USB-C
     or LiPo). The XIAO runs from the Heltec's 3V3 pin. Use 3V3, not Ve:
     Ve is a switched rail (GPIO36) that Meshtastic turns off when the board
     sleeps.
   - **Home station or standalone detector:** connect wires 1-3 only. Plug
     the XIAO into the mapper computer and give the Heltec its own USB power. The V4 draws up to
     ~750 mA when it transmits at full power, too much to run it from the
     XIAO, and leaving wire 4 off keeps the two boards' regulators apart.
5. If you reflash the XIAO of a field station later, unplug wire 4 before you
   connect its USB cable.

### Set up the Heltec V4 (Meshtastic)

Flash stock Meshtastic with the official [Meshtastic Web Flasher](https://flasher.meshtastic.org/)
(Chrome or Edge, device **Heltec V4**). If the browser doesn't see the board,
hold the **PRG** button while plugging it in. If you'd rather use PlatformIO,
Meshtastic's firmware is a PlatformIO project too: clone
`meshtastic/firmware` with `--recursive`, open it in VS Code and run Upload
under `env:heltec-v4`.

Then configure the region and the serial module, either in the Meshtastic app
(**Settings → Module Configuration → Serial**: enabled, RX 47, TX 48,
115200 baud, mode TEXTMSG) or with the Python CLI while the Heltec is on USB:

```bash
pip3 install meshtastic
meshtastic --set lora.region EU_868     # your region: US, EU_868, ANZ, JP, KR, ...
meshtastic --set serial.enabled true --set serial.mode TEXTMSG \
           --set serial.baud BAUD_115200 --set serial.rxd 47 --set serial.txd 48
```

`serial.rxd` is the pin the Heltec listens on (wired to the XIAO's TX) and
`serial.txd` the pin it sends on.

Do this on every Heltec, field and home, and put them all on the same primary
channel. TEXTMSG sends every line on the primary channel. Give that channel
your own name and key, otherwise detections go out on the public default
mesh. The [Meshtastic channel docs](https://meshtastic.org/docs/configuration/radio/channels/)
cover copying a channel URL between radios.

> **Coming from a Heltec V3?** The V3 setup used `serial.rxd 19` /
> `serial.txd 20`. On the V4, GPIO19/20 are the USB-C data lines: the V4
> drops the V3's USB-to-serial chip and uses the ESP32-S3's native USB.
> GPIO38-42 now serve the GNSS connector and GPIO2/7/46 drive the new 28 dBm
> amplifier. Move the two signal wires to 47/48 and set `serial.rxd 47`,
> `serial.txd 48`. The XIAO side and its firmware don't change.

---

## Build and Flash the Firmware

The firmware is built and flashed with PlatformIO in VS Code. The steps below
flash a XIAO ESP32-S3. Other boards and variants are in the
[reference](docs/REFERENCE.md#firmware-variants-and-build-options).

**1. Install the tools (once)**

1. Install [VS Code](https://code.visualstudio.com/) and [Git](https://git-scm.com/downloads).
2. In VS Code, open Extensions (`Ctrl+Shift+X`, macOS `Cmd+Shift+X`), search
   for **PlatformIO IDE** and click Install. Wait for it to finish installing
   PlatformIO Core and reload the window when asked. A PlatformIO (ant-head)
   icon appears in the left sidebar.
3. Linux only: PlatformIO needs `python3-venv`, and your user needs access to
   USB serial ports. Log out and back in afterwards:
   ```bash
   sudo apt install python3-venv
   curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules \
     | sudo tee /etc/udev/rules.d/99-platformio-udev.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   sudo usermod -a -G dialout $USER
   ```

**2. Get the code**

```bash
git clone https://github.com/tsuinami-1112/drone-mesh-custom
```

Or in VS Code: Command Palette (`Ctrl+Shift+P`) → **Git: Clone**. Keep the
clone intact: each firmware folder pulls the shared detection library from
`../firmware-common`, so a firmware folder copied out of the repo won't build.

**3. Open the firmware folder**

**File → Open Folder…** and pick the folder for your station type, not the
repository root. PlatformIO only activates in a folder that contains a
`platformio.ini`.

| Station | Open this folder | Environment |
|---|---|---|
| Field station | `node-mode-dualcore` | `remote_node` |
| Home station | `node-mode-dualcore` | `home_node` |
| Standalone detector | `remoteid-mesh-dualcore` | `seeed_xiao_esp32s3` |

The first time a folder opens, PlatformIO downloads the ESP32 platform and
toolchain (several hundred MB). Let it finish before going on.

**4. Build**

Click the PlatformIO icon, then **PROJECT TASKS → *your environment* →
General → Build**. The first build also fetches NimBLE-Arduino and takes a few
minutes. It ends with `SUCCESS`.

> Always run Build, Upload and Monitor from under the environment's name, or
> pick the environment in the status-bar switcher first. The **Default** tasks
> and the status-bar buttons act on every environment in the folder. In
> `node-mode-dualcore`, a default Upload flashes `remote_node` and then
> `home_node` onto the same board, so it ends up as a home station.

**5. Upload**

Connect the XIAO with a USB-C data cable and run **General → Upload** under
the same environment. PlatformIO finds the port, flashes, and resets the
board.

If it can't find or connect to the board, put the XIAO into bootloader mode:
hold **B** (BOOT), press and release **R** (RESET), release **B**. Then run
Upload again and press **R** when it finishes. With several boards plugged
in, unplug the others or add `upload_port = <port>` to the environment in
`platformio.ini` (`COM5`, `/dev/ttyACM0`, `/dev/cu.usbmodem101`, ...).

**6. Check it**

Run **General → Monitor** (115200 baud) and press **R** on the XIAO. The boot
banner lists the enabled detection layers, and a heartbeat follows every 60 s
on a field station (30 s on a home station). Close the monitor before starting
the mapper: only one program can hold the serial port.

<details>
<summary>Same thing from the command line</summary>

Open a PlatformIO terminal (**PlatformIO → Quick Access → Miscellaneous →
PlatformIO Core CLI**) and run:

```bash
cd node-mode-dualcore
pio run -e remote_node -t upload     # or -e home_node
pio device monitor -b 115200
```

</details>

Detection knobs (stay on channel 6, drop fingerprints, dwell times) go in the
environment's `build_flags`. See the
[reference](docs/REFERENCE.md#detection-knobs).

---

## Quick Start

On the computer the home station (or a standalone detector) is plugged into:

```bash
git clone https://github.com/tsuinami-1112/drone-mesh-custom
cd drone-mesh-custom
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 mesh-mapper.py
```

The virtual environment keeps the packages away from the system Python, which
recent Raspberry Pi OS and Debian releases protect. If `venv` is missing,
`sudo apt install python3-venv`. The Pi auto-start installer still fetches
the upstream mapper; see the [reference](docs/REFERENCE.md#raspberry-pi-installer).

Open `http://localhost:5000` (or the machine's IP from another device) and
pick the XIAO's serial port. Saved ports reconnect automatically on the next
start.

| Flag | Default | What it does |
|---|---|---|
| `--web-port PORT` | 5000 | Port for the web UI |
| `--headless` | off | No web interface (server-only) |
| `--debug` | off | Verbose logging |
| `--port-interval SEC` | 10 | USB port re-scan cadence |
| `--no-auto-start` | off | Don't auto-connect to saved ports |

---

## Features

- **Detection** on the stock XIAO radios, no extra hardware: Remote ID over
  BLE 4, BLE 5 Long Range, WiFi NAN and Beacon (both Basic IDs, Operator ID,
  EU class, operator position), DJI DroneID, MAVLink on open WiFi, and
  confidence-tagged fingerprints of drones that broadcast nothing.
  [Coverage and per-country details](docs/REFERENCE.md#detection-coverage)
- **Live map**: drone and pilot positions, flight paths that survive
  restarts, aliases, webhooks, and CSV / KML / GeoJSON export
- **Multi-station mesh**: field stations tag every report with a `node_id`,
  and the home station de-duplicates the same drone heard by several of them
- **Offline maps**: UI assets vendored, MBTiles raster and vector basemaps,
  area caching and region presets. `tiles/` starts empty, so cache your area
  before you lose the connection. [Offline maps](docs/REFERENCE.md#offline-maps)
- **ADS-B overlay** from network feeds or a local SDR (dump1090 / readsb /
  Beast TCP). [ADS-B](docs/REFERENCE.md#ads-b-air-traffic)
- **REST + WebSocket API**. [API reference](docs/REFERENCE.md#api-reference)

---

## Troubleshooting

### XIAO not detected / won't flash
```bash
ls -la /dev/tty* | grep -E 'USB|ACM'
dmesg | grep tty
```
Try another cable (charge-only cables are common), then bootloader mode: hold
B, tap R, release B. On Linux, check the udev rules and `dialout` group from
the flashing steps.

### No drone detections
- Confirm the firmware is running (Monitor). The boot banner lists the enabled layers
- Check the Heltec's serial module: enabled, TEXTMSG, 115200, **RX 47 / TX 48** on a V4
- Check the wiring crosses over: XIAO D4 to Heltec 47, XIAO D5 to Heltec 48, plus GND
- Check all Heltecs share the same primary channel and key
- Remote ID lives on WiFi channel 6. The node hops away from it briefly to find other access points; build with `-DDETECT_WIFI_HOP=0` to stay on channel 6 if you only care about Remote ID
- A BLE 5 Long Range-only module can take a few seconds to be heard: the controller alternates between the 1M and coded PHY, and the WiFi sniffer shares the radio
- Many drones broadcast no Remote ID at all. Those show up, if at all, as dashed amber "possible drone" fingerprint entries without a position
- DJI aircraft only broadcast Remote ID with the motors running and only in regions where DJI has enabled it; the proprietary DJI DroneID beacon exists only on WiFi-link models

More (web UI, tile caching, vector layers) in the
[reference](docs/REFERENCE.md#more-troubleshooting).

---

## Documentation

| Document | What's in it |
|---|---|
| [`docs/REFERENCE.md`](docs/REFERENCE.md) | Detection coverage, firmware variants and build knobs, offline maps, ADS-B, API, performance, project layout |
| [`firmware-common/README.md`](firmware-common/README.md) | The shared detection library: protocols, JSON schema, limits |
| [`node-mode-dualcore/README.md`](node-mode-dualcore/README.md) | Field/home node firmware internals and the dedup engine |

---

## License

MIT.

## Acknowledgments

- **"Alik"** - UAV operator, 93rd OMBr "Black Ravens", AFU 🇺🇦
- **"Ivan"** - ex-UAV operator, 427th Unmanned Aerial Brigade "Rarog", AFU 🇺🇦
- **Cemaxecuter** / **alphafox02** - original RID firmware
- **colonelpanichacks** - the upstream [drone-mesh-mapper](https://github.com/colonelpanichacks/drone-mesh-mapper) this project is built on
- **Luke Switzer** - firmware contributions
- **OpenDroneID** community - protocol & specs (Apache 2.0)
- **Kismet** - the DJI DroneID beacon dissector this project's decoder follows
- **MAVLink** project - message definitions and CRC_EXTRA tables
- **h2zero / NimBLE-Arduino** - BLE 5 extended advertising on the ESP32
- **Meshtastic** - the mesh firmware the stations relay over
- **OpenStreetMap**, **Esri**, **CARTO**, **OpenTopoMap** - tile providers
- **MapLibre GL** + **Leaflet** + **Nominatim** - open mapping stack
- **ADS-B receivers** - built on the shoulders of [dump1090](https://github.com/MalcolmRobb/dump1090) (Malcolm Robb / mutability), [readsb](https://github.com/wiedehopf/readsb) + [tar1090](https://github.com/wiedehopf/tar1090) (wiedehopf), and [pyModeS](https://github.com/junzis/pyModeS) (junzis) for Mode-S/CPR decode. The Beast TCP path uses pyModeS directly; the JSON path is compatible with all of the above. Network sources: [adsb.lol](https://adsb.lol), [adsb.fi](https://adsb.fi), [airplanes.live](https://airplanes.live), [OpenSky](https://opensky-network.org), [ADSBexchange](https://adsbexchange.com).

---

<div align="center">

If this project helped you, give it a star.

</div>
