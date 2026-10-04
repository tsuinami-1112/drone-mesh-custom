# <div align="center">**Drone Mesh Mapper**</div>

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![ESP32](https://img.shields.io/badge/ESP32-Compatible-green.svg)](https://www.espressif.com/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-red.svg)](https://flask.palletsprojects.com/)

**Solar-powered drone detection stations · Meshtastic LoRa mesh · live web map · runs unattended, 24/7, offline**

[Hardware](#hardware-options) ·
[Solar](#solar-integration) ·
[Flashing](#build-and-flash-the-firmware) ·
[Quick Start](#quick-start) ·
[Reference](docs/REFERENCE.md)

<img src="eye.png" alt="Drone Detection Eye" style="width:50%; height:25%;">

</div>

---

| **Level 1** · [`level1`](../../tree/level1) branch (in bench testing) | **Level 2** · [`level2-main`](../../tree/level2-main) branch (this one) |
|---|---|
| Finds drones by their **5.8 GHz analog FPV video link**, including drones that broadcast nothing else | Finds drones by what they **broadcast**: Remote ID (BLE + WiFi), DJI DroneID, MAVLink, WiFi/BLE fingerprints |
| XIAO ESP32-C5 and four patch antennas: each station measures a **compass bearing** to the transmitter | XIAO ESP32-S3 **decodes** the broadcast: position, altitude, serial / operator ID, pilot position |
| A position needs **two or more stations** whose bearings cross | A position from **one station**, whenever the drone broadcasts it |

**Mixed deployments work.** Level 1 and level 2 stations use the same Heltec
V4 radio, wiring and Meshtastic settings, share one mesh channel and one home
station, and `mesh-mapper.py` on this branch puts both on the same map: Remote
ID tracks alongside level 1 bearing rays and the position fixes where they
cross. Set each level 1 station's position and heading once in the mapper's
LEVEL 1 STATIONS panel.

---

## Overview

A solar-powered, 24-7 drone detection network communicating over a private mesh. Intended for around-the-clock area protection and privacy.

Developed in partnership with our friends in the Armed Forces of Ukraine. Special thanks to:

"Alik", 93rd OMBr

"Ivan", 427th Unmanned Aerial Brigade

Field stations on poles and rooftops run on solar and listen around the clock
for drone broadcasts (Open Drone ID per ASTM F3411 and ASD-STAN EN 4709-002
over BLE and WiFi, DJI DroneID, MAVLink, and WiFi/BLE fingerprints). They relay
what they hear over a Meshtastic LoRa mesh to a home station, where
`mesh-mapper.py` puts every drone and pilot on a live map. Nothing depends on
the internet, a cellular link or a national registry: the stations decode what
the drone broadcasts, the mesh carries it, and the mapper runs offline.

```
 FIELD STATIONS (solar, unattended)                    HOME STATION (base)
 XIAO ESP32-S3 --UART--> Heltec V4 ~~ LoRa mesh ~~> Heltec V4 --UART--> XIAO ESP32-S3 --USB--> mesh-mapper.py
 WiFi + BLE detection    (Meshtastic)   (multi-hop)   (Meshtastic)        dedup bridge          live web map
 panel + MPPT + LiFePO4                                mains, or its own solar system
```

---

## Hardware Options

### What you need per station

| Part | Notes |
|---|---|
| **Seeed XIAO ESP32-S3** | The detector (field station) or the mesh-to-USB bridge (home station) |
| **Heltec WiFi LoRa 32 V4** | Meshtastic mesh radio. Buy the band your region uses (863-928 MHz for EU868 / US915 / AU915 / ...) and the standard OLED model: the TFT model uses GPIO47/48 for its touchscreen |
| LoRa antenna | Usually ships with the Heltec. Fit it **before** powering the board: the V4 transmits up to 28 dBm. Outdoors, use a proper 868/915 MHz antenna mounted as high as you can |
| 2.4 GHz antenna | Ships with the XIAO (U.FL). Outdoors, an SMA antenna on a U.FL pigtail through the enclosure wall |
| 4 jumper wires | Plus pin headers if your boards came without them |
| USB-C data cables | One per board for flashing; charge-only cables won't enumerate |
| Power | Field stations: a solar system, see [Solar integration](#solar-integration). Home station: USB from the mapper computer and a USB supply |
| Enclosure | IP65 or better, pale colour, cable glands and a membrane vent; antennas outside the box |

### Optional amplifiers

| Amplifier | Status | Goes between | What it does |
|---|---|---|---|
| [**2.4 GHz LNA**, 20 dB, SAW filter, one-way](https://www.aliexpress.com/item/1005010776583002.html) | **Recommended** for field stations | 2.4 GHz antenna → XIAO U.FL | Lifts weak BLE and WiFi broadcasts before the XIAO's own receiver adds its noise, so stations hear Remote ID from farther out. The SAW filter keeps the LoRa transmitter, cellular and other out-of-band signals from overloading it |
| [**800-1000 MHz 1 W bidirectional amplifier**](https://www.aliexpress.com/item/1005009625219917.html) | Optional | Heltec LoRa U.FL ↔ LoRa antenna | Adds receive gain and up to 1 W transmit for long mesh links. Most useful when the antenna is on a mast at the end of a long cable: mount the amplifier at the antenna |

**2.4 GHz LNA.** Wire it antenna → `IN`, `OUT` → XIAO U.FL, and mount it at
the antenna end of any cable run so it amplifies before the cable loss. Power
it from the station's 5 V rail. It only passes signal one way, which is safe
here because the detection firmware never transmits on 2.4 GHz: WiFi sits in
promiscuous receive and BLE scans passively. Don't fit it to a XIAO running
anything that connects to WiFi or advertises over BLE. Expect a few dB of real
sensitivity rather than the full 20 dB (more if it makes up for cable loss),
which still adds meaningful range.

**1 W LoRa amplifier.** Before you connect it, lower the Heltec's transmit
power to the input level the amplifier's listing specifies:

```bash
meshtastic --set lora.tx_power 10     # use your amplifier's rated input; the V4's default 28 dBm overdrives these
```

Then wire Heltec LoRa U.FL → pigtail → the amplifier's radio port, and the
amplifier's antenna port → antenna. It switches between transmit and receive
by itself. Never power it without the antenna attached. With the 28 dBm V4 it
adds only about 2 dB of transmit power and the V4 already has its own receive
amplifier, so it earns its place by making up for a long feeder, or on the 21
dBm V4 variants.

### Station types

| Station | Firmware | Where it goes |
|---|---|---|
| **Field station** | `node-mode-dualcore`, env `remote_node` | On a pole or roof, on solar, unattended. Detects drones and sends each detection over the mesh, tagged with its own `node_id` |
| **Home station** | `node-mode-dualcore`, env `home_node` | Plugged into the computer running `mesh-mapper.py`. Receives the mesh, drops duplicate reports of the same drone from several field stations, and forwards the rest over USB |
| **Standalone detector** | `remoteid-mesh-dualcore`, env `seeed_xiao_esp32s3` | Plugged straight into the mapper's computer. Also posts short text alerts with map links to the mesh, which any Meshtastic app can read; a mapper [reading a radio directly](#reading-a-mesh-radio-directly-experimental) plots them too |
| **Radio-only home station** (experimental) | None on the XIAO side: just a Heltec V4 running stock Meshtastic | On the mapper computer's USB, or on WiFi. `mesh-mapper.py --mesh` reads it directly, with no XIAO. See [Reading a mesh radio directly](#reading-a-mesh-radio-directly-experimental) |

A typical deployment is several field stations and one home station. A bare
Heltec V4 on a hilltop, with no XIAO and the `ROUTER` role, extends the mesh
where field stations can't hear each other.

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

<details open>
<summary><b>Field station: power and RF</b></summary>

```
 solar panel --> MPPT controller <--> 12 V LiFePO4 battery
                      | load output (low-voltage disconnect)
                      +--------------------------------> 1 W LoRa amp (if it takes 12 V)
                      +--> 12 V -> 5 V buck --+--> Heltec V4 (USB-C or 5V pin) --3V3--> XIAO ESP32-S3
                                              +--> 2.4 GHz LNA

 2.4 GHz antenna --> LNA IN | LNA OUT --> XIAO U.FL
 LoRa antenna <--> amp ANT  | amp RADIO <--> Heltec LoRa U.FL
```

</details>

1. **Flash both boards first** ([firmware](#build-and-flash-the-firmware) on
   the XIAO, [Meshtastic](#set-up-the-heltec-v4-meshtastic) on the Heltec),
   while nothing is wired between them.
2. Fit the antennas (and amplifiers, if used) before anything is powered.
3. Solder headers or wires and make the connections in the table. Keep the
   wires short (under 20 cm) and cross TX to RX as shown.
4. Power it:
   - **Field station:** connect all four wires and feed the Heltec from the
     solar system's 5 V rail, through its USB-C port or its 5V pin, never both
     at once. The XIAO runs from the Heltec's 3V3 pin. Use 3V3, not Ve: Ve is
     a switched rail (GPIO36) that Meshtastic turns off when the board sleeps.
   - **Home station or standalone detector:** connect wires 1-3 only. Plug
     the XIAO into the mapper computer and give the Heltec its own USB power.
     The V4 draws up to ~750 mA when it transmits at full power, too much to
     run it from the XIAO, and leaving wire 4 off keeps the two boards'
     regulators apart.
5. Mount the box with the LoRa antenna as high as you can (height matters more
   than anything else for mesh range) and the 2.4 GHz antenna about 1 m away
   from it, so the LoRa transmitter doesn't swamp the 2.4 GHz LNA.
6. If you reflash the XIAO of a field station later, unplug wire 4 before you
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

For a station that will run unattended:

```bash
meshtastic --set power.is_power_saving false   # power saving switches the serial port off
meshtastic --set bluetooth.enabled false       # once configured: saves power, nothing to pair with on a pole
```

Keep the `CLIENT` role on every radio with a XIAO attached. Before you switch
Bluetooth off, set up [remote administration](https://meshtastic.org/docs/configuration/remote-admin/)
so you can still change settings over the mesh.

> **Coming from a Heltec V3?** The V3 setup used `serial.rxd 19` /
> `serial.txd 20`. On the V4, GPIO19/20 are the USB-C data lines: the V4
> drops the V3's USB-to-serial chip and uses the ESP32-S3's native USB.
> GPIO38-42 now serve the GNSS connector and GPIO2/7/46 drive the new 28 dBm
> amplifier. Move the two signal wires to 47/48 and set `serial.rxd 47`,
> `serial.txd 48`. The XIAO side and its firmware don't change.

---

## Solar Integration

Field stations are meant to run for months without a visit. That means sizing
the solar system for the worst month of the year, not the average, and
choosing parts that bring the station back by themselves after a flat battery.

### Power budget

What each part draws from the 5 V rail:

| Part | Receiving | Transmitting | Basis |
|---|---|---|---|
| XIAO ESP32-S3 detector | 120 mA | - | WiFi + BLE scanning nonstop: ESP32-S3 WiFi receive is 95-100 mA, plus the CPU working |
| Heltec V4 running Meshtastic | 75 mA | 750 mA at 27 dBm | Heltec V4 datasheet |
| 2.4 GHz LNA | 50 mA | - | Budget figure: modules of this type draw 15-50 mA |
| 1 W LoRa amplifier | 60 mA | ~600 mA at 1 W out | Budget figure. While it drives the amp at low power the Heltec itself drops to ~330 mA |

What a whole field station uses, assuming the radio transmits 5 % of the time
(relaying other stations, detections, Meshtastic's own telemetry):

| Configuration | Average | Added by the amplifiers | Peak | Per day at the load | Per day from the battery |
|---|---|---|---|---|---|
| **Base:** XIAO + Heltec V4 | 230 mA · 1.15 W | - | 0.9 A | 27.5 Wh | 35 Wh |
| **+ 2.4 GHz LNA** (recommended) | 280 mA · 1.4 W | +0.25 W · +6 Wh/day | 0.9 A | 33.5 Wh | 42 Wh |
| **+ 1 W LoRa amplifier** | 300 mA · 1.5 W | +0.35 W · +8 Wh/day | 1.05 A | 36 Wh | 44 Wh |
| **+ both** | 350 mA · 1.75 W | +0.6 W · +14 Wh/day | 1.1 A | 42 Wh | 51 Wh |

"From the battery" adds the 12 V → 5 V converter (88 % efficient) and ~0.15 W
for the charge controller itself. A quiet mesh (1 % transmit) takes the base
station down to 1.0 W, and a busy one (10 %) up to 1.3 W; with both amplifiers
the range is 1.55-1.95 W. The amplifier figures are planning numbers: put a USB
power meter on your own modules and adjust.

### Sizing the panel and battery

**Battery:** 3 days of autonomy with no sun at all.

| Configuration | Battery needed | Recommended |
|---|---|---|
| Base | 153 Wh | 12.8 V LiFePO4, 12 Ah minimum |
| + 2.4 GHz LNA, + 1 W amp, or both | 184-225 Wh | **12.8 V LiFePO4, 20 Ah (256 Wh)**, which covers every configuration |

**Panel:** sized on the sun hours of your worst month (December north of the
equator, June south of it). Look your site up on
[PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/en/). As a rough guide, northern
European winters give under 1.5 h, temperate winters 2-3 h, desert and
subtropical winters 4 h or more.

| Worst-month sun hours | Base or + 2.4 GHz LNA | + 1 W amp, or both |
|---|---|---|
| 4 h or more | 20 W | 30 W |
| 3 h | 30 W | 30 W |
| 2 h | 50 W | 50 W |
| under 2 h | 100 W and a 30 Ah battery | 100 W and a 30 Ah battery |

Tilt the panel at about your latitude + 15° facing the equator (favours
winter), and keep it clear of shade from 9 am to 3 pm.

<details>
<summary>The arithmetic behind the tables</summary>

- Daily energy from the battery: `E = (load W ÷ 0.88 + 0.15 W) × 24 h`
- Battery: `E × 3 days ÷ (0.8 usable × 0.85 cold derating)`
- Panel: `E × 1.25 ÷ (sun hours × 0.75)`, where 0.75 covers heat, dirt, angle
  and charging losses, and 1.25 refills the battery after a dull spell while
  still running the station

Swap in your own numbers if you change the transmit duty, the amplifiers or the
autonomy target.

</details>

### Recommended power system

A 12 V system built from standard solar parts:

| Part | Pick | Why |
|---|---|---|
| Panel | 12 V nominal (about 18 V at max power), sized from the table | Matches any 12 V MPPT controller |
| Charge controller | MPPT with a LiFePO4 profile and a **load output with low-voltage disconnect and auto-reconnect**, such as the Victron SmartSolar 75/10 or EPever Tracer 1206AN | The load output is what restarts the station on its own after a flat battery. MPPT harvests about a quarter more than PWM from the same panel |
| Battery | 12.8 V LiFePO4 with a BMS that blocks charging below 0 °C | Lasts thousands of daily cycles where Li-ion lasts hundreds, tolerates heat, and is safe in a sealed box |
| 5 V supply | 12 V → 5 V buck converter rated 3 A or more | Feeds the Heltec (and through it the XIAO) and the 2.4 GHz LNA |
| 1 W amplifier supply | Straight from the load output, if the amplifier takes 12 V | Skips the converter losses |

Set the controller's load disconnect above the BMS cut-off (around 12.0 V) and
its reconnect well above it (around 13.0 V). The controller then switches the
station off before the BMS has to, and back on once the panel has put some
charge back.

For the base configuration in a sunny climate, a 1S board with a regulated 5 V
output (as the level 1 guide uses) also works, if that output is rated 1.5 A
or more. Three days of autonomy then takes about eight 32700 LiFePO4 cells
(6 Ah each), which is why a 12 V pack is the simpler choice beyond the base
station.

**Avoid:**
- **Power banks.** Most switch off when the load is light and can't charge and
  supply at the same time reliably.
- **The Heltec V4's own solar and battery connectors.** Its charger is rated
  around 500 mA, enough for a low-power Meshtastic node but not for a
  1.1-1.8 W detection station running all day and night.

### Running unattended

- **Recovery after an outage.** Every part boots straight back into work
  without a button press: the XIAO firmware starts scanning, Meshtastic
  rejoins the mesh, and the controller's load output reconnects. Run the
  mapper as a service so the home end recovers too
  ([Quick Start](#quick-start)).
- **Battery health over the mesh.** Wire an INA219, INA226 or INA3221 current
  sensor into the battery lead, connect it to the Heltec's I2C port (header
  pins 3 = SCL, 4 = SDA, plus 3V3 and GND) and enable
  `meshtastic --set telemetry.power_measurement_enabled true`. Every station
  then reports its battery voltage and current over the mesh, readable in the
  Meshtastic app.
- **Heat and cold.** A box in full sun runs far above air temperature. Pick a
  pale enclosure, shade it if you can, and fit a membrane vent. LiFePO4 must
  not be charged below 0 °C, so in cold climates pick a battery whose BMS
  blocks it (or a self-heating pack).
- **Weather.** Cable glands, drip loops on every cable, self-amalgamating tape
  over outdoor RF connectors, and a grounded mast.

---

## Build and Flash the Firmware

The firmware is built and flashed with PlatformIO in VS Code. The steps below
flash a XIAO ESP32-S3. Other boards and variants are in the
[reference](docs/REFERENCE.md#firmware-variants-and-build-options).

There is no web flasher for this firmware. The `flasher/` folder is a retired
page whose images predate the current detection code, so build from source as
below.

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
`sudo apt install python3-venv`. On a Raspberry Pi, the
[installer](docs/REFERENCE.md#raspberry-pi-installer) does all of this and
starts the mapper on boot:

```bash
wget https://raw.githubusercontent.com/tsuinami-1112/drone-mesh-custom/HEAD/RPI/install_rpi.py
python3 install_rpi.py
```

Open `http://localhost:5000` (or the machine's IP from another device) and
pick the XIAO's serial port. Saved ports reconnect automatically on the next
start.

For a home station that has to come back by itself after a power cut, run the
mapper as a systemd service. Replace `pi` and the paths with your user and
clone location; the user needs to be in the `dialout` group for the serial
port:

```ini
# /etc/systemd/system/mesh-mapper.service
[Unit]
Description=Drone Mesh Mapper
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/drone-mesh-custom
ExecStart=/home/pi/drone-mesh-custom/.venv/bin/python mesh-mapper.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now mesh-mapper
```

| Flag | Default | What it does |
|---|---|---|
| `--web-port PORT` | 5000 | Port for the web UI |
| `--headless` | off | No web interface (server-only) |
| `--debug` | off | Verbose logging |
| `--port-interval SEC` | 10 | USB port re-scan cadence |
| `--no-auto-start` | off | Don't auto-connect to saved ports |
| `--mesh PORT_OR_HOST` | - | Read a Meshtastic radio directly (repeatable): `/dev/ttyACM0`, `COM7` or `tcp:192.168.1.50` |
| `--mesh-channel N` | 0 | Channel index the stations send on |
| `--mesh-dedup-ms MS` | 500 | Drop repeat reports of the same drone within this window, as the ESP32 home node does |

### Reading a mesh radio directly (experimental)

The mapper can talk to a Meshtastic radio itself, so the home station needs no
XIAO: plug a Heltec V4 running stock Meshtastic into the mapper computer, or
put it on WiFi.

```bash
python3 mesh-mapper.py --mesh /dev/ttyACM0          # USB (Windows: COM7, macOS: /dev/cu.usbmodem...)
python3 mesh-mapper.py --mesh tcp:192.168.1.50      # a radio on WiFi (port 4403)
```

- **The radio** needs only the region and your private channel. Its serial
  module can stay off, because there is no XIAO on it. For WiFi:
  `meshtastic --set network.wifi_enabled true --set network.wifi_ssid <ssid> --set network.wifi_psk <password>`
  (on the ESP32, WiFi replaces Bluetooth).
- **Field stations don't change.** The mapper reads the same messages the
  ESP32 home node does: node mode JSON, level 1 bearings and heartbeats, and
  the standalone firmwares' `Drone:` / `Pilot:` / `Possible drone` text
  alerts. It joins lines the radio split across packets and drops repeat
  reports of the same drone like the home node.
- **It only listens.** The mapper never sends anything into the mesh. While it
  holds the radio's USB port, the Meshtastic CLI and app can't use that port;
  use WiFi, or stop the mapper first.
- **Station health:** `GET /api/meshtastic` lists every node the radio knows,
  with last-heard time, SNR, and battery and power telemetry (the current
  sensor from [Running unattended](#running-unattended) shows up here).
- The radios are saved to `meshtastic_config.json` and reconnect on the next
  start. Change them later with
  `POST /api/meshtastic {"links": ["/dev/ttyACM0"]}`.
- **No hardware?** `mapper_test/fake_meshtastic_radio.py --tcp 4403 --demo`
  plays a demo mesh to `--mesh tcp:127.0.0.1:4403`, and
  `mapper_test/test_mesh_direct.py` checks every message format end to end.
  Details are in the [reference](docs/REFERENCE.md#direct-meshtastic-radio-input).

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
  and the home station de-duplicates the same drone heard by several of them.
  Level 1 bearing stations share the same mesh and map
- **Built to run unattended**: stations boot straight into scanning, the
  home node's watchdog reboots it if it ever wedges, and the mapper restores
  its serial ports, tracks and settings on restart
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

### A station drops off the mesh at night or in winter
- That's the controller's low-voltage disconnect doing its job: the battery ran flat. It reconnects by itself once the panel recharges it
- Re-check the panel size against your worst month and the battery against 3 days of autonomy ([Solar integration](#solar-integration))
- Fit a current sensor and power telemetry so you see the battery voltage trend before it happens

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
