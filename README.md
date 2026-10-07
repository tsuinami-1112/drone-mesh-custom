<p align="center">
  <img src="docs/img/standalone-workbench.svg" width="768" alt="Pixel art of a dark makerspace: a laptop running the mapper on a workbench crowded with electronics, next to a window with half-drawn blinds. Outside, drones sweep searchlights over a cyberpunk city while their blips drift slowly across the laptop's map.">
</p>

# Drone Sentinel - standalone mapper (experimental)

> Placeholder README for an experimental branch. This branch holds only the
> mapper and what it needs. The detection stations, their firmware and the full
> documentation are on
> [`level2-main`](https://github.com/tsuinami-1112/drone-sentinel/tree/level2-main)
> (level 2) and [`level1`](https://github.com/tsuinami-1112/drone-sentinel/tree/level1).

## What it does

`mesh-mapper.py` puts the drones your detection stations report on a live web
map. On this branch it can read a **Meshtastic radio directly**, over USB or
WiFi, so the base needs no ESP32 home station: a Heltec V4 running stock
Meshtastic is all the mapper needs.

- **Reads every current station message:** level 2 node mode JSON detections,
  level 1 bearing reports (analog and digital video links) and heartbeats (two
  or more stations' bearings cross into a position), and the standalone
  detectors' `Drone:` / `Pilot:` / `Possible drone` text alerts.
- **Handles how Meshtastic carries them:** it re-joins lines the radio split
  across packets, drops repeat reports of the same drone from several stations
  (as the ESP32 home node does), and counts a packet heard by two radios once.
- **Reports station health:** `GET /api/meshtastic` lists every node the radio
  knows, with last-heard time, signal, and battery and power telemetry.
- **Only listens:** the mapper never transmits into the mesh.
- **Keeps working the old way:** an ESP32 home station or a detector on USB
  still works alongside or instead of a radio, and so do offline maps, ADS-B,
  geofences, webhooks and the exports.

Status: tested end to end against a simulated radio, not yet on hardware.

## Set it up

**1. The base radio.** Flash a Heltec V4 with Meshtastic
([flasher.meshtastic.org](https://flasher.meshtastic.org/)), then set its
region and the same private primary channel as your field stations. Its serial
module can stay off. To reach it over WiFi instead of USB:

```bash
pip3 install meshtastic
meshtastic --set lora.region EU_868          # your region: US, EU_868, ANZ, ...
meshtastic --set network.wifi_enabled true --set network.wifi_ssid <ssid> --set network.wifi_psk <password>
```

On the ESP32, WiFi replaces Bluetooth. The radio's screen shows its IP address.

**2. Install the mapper** (Python 3.9+):

```bash
git clone -b standalone-mapper-meshtastic https://github.com/tsuinami-1112/drone-sentinel
cd drone-sentinel
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. Run it** with your radio, then open `http://localhost:5000` (or the
machine's IP from another device):

```bash
python3 mesh-mapper.py --mesh /dev/ttyACM0          # USB (Windows: COM7, macOS: /dev/cu.usbmodem...)
python3 mesh-mapper.py --mesh tcp:192.168.1.50      # WiFi (port 4403)
```

The radio is saved to `meshtastic_config.json` and reconnects on the next
start, so later starts need no `--mesh`. On Linux your user must be in the
`dialout` group to open a USB radio. While the mapper holds a radio's USB
port, the Meshtastic CLI and app can't use that port.

**4. Level 1 stations, if you have any:** a station flashed with its position
and heading (the level 1 firmware's "Station setup (map)" task, see the
[`level1` README](https://github.com/tsuinami-1112/drone-sentinel/tree/level1#station-location-and-heading))
places itself on the map, marked **auto**, within 10 minutes over the mesh. For
any other, set its position and heading once in the map's LEVEL 1 STATIONS
panel. Their bearings then cross into positions. A position saved in the panel
overrides the flashed one on this mapper; clear both position fields and press
SAVE to go back to it.

**On a Raspberry Pi**, the installer does steps 2-3 and starts the mapper on
every boot:

```bash
wget https://raw.githubusercontent.com/tsuinami-1112/drone-sentinel/standalone-mapper-meshtastic/RPI/install_rpi.py
python3 install_rpi.py --branch standalone-mapper-meshtastic
```

Then save your radio once, as described in the
[reference](docs/REFERENCE.md#raspberry-pi-installer).

## Try it without a radio

```bash
python3 mapper_test/fake_meshtastic_radio.py --tcp 4403 --demo &
python3 mesh-mapper.py --mesh tcp:127.0.0.1:4403
```

The fake radio plays a demo mesh: a Remote ID drone, a standalone detector and
two level 1 stations flashed with their positions, which place themselves on
the map. `python3 mapper_test/test_mesh_direct.py` checks every message format
end to end.

## Options

| Flag | Default | What it does |
|---|---|---|
| `--mesh PORT_OR_HOST` | - | Read a Meshtastic radio (repeatable, up to 4): `/dev/ttyACM0`, `COM7`, `tcp:HOST[:PORT]` |
| `--mesh-channel N` | 0 | Channel index the stations send on |
| `--mesh-dedup-ms MS` | 500 | Drop repeat reports of the same drone within this window (0 = off) |
| `--web-port PORT` | 5000 | Port for the web UI |
| `--headless` | off | No web interface |
| `--no-auto-start` | off | Don't reconnect saved ports and radios (`--mesh` still applies) |
| `--debug` | off | Verbose logging |

Message formats, the API, offline maps and ADS-B are in
[`docs/REFERENCE.md`](docs/REFERENCE.md).

## License

MIT.
