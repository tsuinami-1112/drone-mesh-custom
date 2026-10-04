# Standalone Mapper - Reference

Details for the standalone mapper branch. To get it running, start with the
[README](../README.md). The station hardware, the firmware and the full
project documentation live on the
[`level2-main`](https://github.com/tsuinami-1112/drone-mesh-custom/tree/level2-main) branch.

- [Mapper features](#mapper-features)
- [Raspberry Pi installer](#raspberry-pi-installer)
- [Direct Meshtastic radio input](#direct-meshtastic-radio-input)
- [Offline maps](#offline-maps)
- [ADS-B air traffic](#ads-b-air-traffic)
- [API reference](#api-reference)
- [Performance](#performance)
- [More troubleshooting](#more-troubleshooting)
- [Project layout](#project-layout)

---

## Mapper features

### Real-time mapping
- Live drone + pilot positions, broadcast rings, custom markers
- Flight-path tracking with persistent session state across restarts
- Multiple ESP32 receivers simultaneously
- Cyberpunk lime/magenta UI (Orbitron font, neon glow)

### Data management
- Detection history with timestamps + RSSI
- Identity fields (UAS IDs, operator ID, make/model, source) carried forward across position-only frames and persisted to CSV
- Device aliases (friendly names per MAC)
- Export to CSV, KML (Google Earth), GeoJSON
- Cumulative long-term log

### ESP32 integration
- USB serial auto-discovery + saved-port restore
- Real-time connection health
- Send diagnostic commands to connected nodes

### Web interface
- WebSocket-driven live updates
- Mobile responsive
- Map / detection list / status panels in one view

### External
- Webhook callbacks on detection transitions
- Service worker tile cache for the live UI

### Offline basemaps
- 8 raster tile sources, vendored Leaflet + MapLibre GL
- One-click world baseline, region presets, place search
- Drop-in MBTiles import (raster or vector)
- Page loads with **zero internet** once tiles are cached

### ADS-B overlay
- 6 sources: adsb.lol, adsb.fi, airplanes.live, OpenSky, ADSBexchange, plus **native Beast TCP** (HackRF / RTL-SDR / AirSpy / SDRplay via dump1090 / readsb / tar1090 / PiAware)
- Live aircraft markers, heading-rotated triangles, altitude-banded colors
- Aircraft trails per ICAO (60-point history)
- Click any aircraft for callsign / ICAO / altitude / speed / heading / vertical rate / squawk
- Polite to providers - bbox-only mode, configurable interval, exponential backoff on errors

---

## Raspberry Pi installer

`RPI/install_rpi.py` sets the mapper up on the computer the base radio plugs
into (a Raspberry Pi running Raspberry Pi OS, or any Debian-based Linux) and
makes it start on every boot. It:

1. downloads a branch of this repository from GitHub and unpacks it into
   `~/mesh-mapper`. For the standalone mapper, pass
   `--branch claude/standalone-mapper-meshtastic`; without `--branch` it
   installs the default branch, `level2-main`
2. creates a Python virtual environment in `~/mesh-mapper/.venv` and installs
   `requirements.txt` into it
3. adds an `@reboot` cron job for your user that starts the mapper from that
   environment

```bash
wget https://raw.githubusercontent.com/tsuinami-1112/drone-mesh-custom/claude/standalone-mapper-meshtastic/RPI/install_rpi.py
python3 install_rpi.py --branch claude/standalone-mapper-meshtastic
```

Run it as your normal user, not with `sudo`: the files and the cron job belong
to whoever runs it. That user needs to be in the `dialout` group to open the
radio's (or an ESP32's) serial port. The installer warns you if it isn't; fix it with
`sudo usermod -a -G dialout $USER` and log in again. If the installer reports
that `venv` is missing, run `sudo apt install python3-venv` and run the
installer again.

| Flag | Default | What it does |
|---|---|---|
| `--install-dir DIR` | `~/mesh-mapper` | Where to install |
| `--branch NAME` | `level2-main` | Install from another branch of this repository |
| `--no-cron` | off | Don't add the boot-time cron job |
| `--force` | off | Update an existing install without asking |

The boot job starts the mapper with no options, so it uses the radios saved in
`meshtastic_config.json`. Save yours once, either by running the mapper by hand
with `--mesh` (stop it with Ctrl+C afterwards) or through the API while it
runs:

```bash
cd ~/mesh-mapper && .venv/bin/python mesh-mapper.py --mesh /dev/ttyACM0
curl -X POST -H 'Content-Type: application/json' \
     -d '{"links": ["tcp:192.168.1.50"]}' http://localhost:5000/api/meshtastic
```

Then open `http://<the Pi's IP>:5000` from another device. The mapper logs to
`~/mesh-mapper/mapper.log`.

- **Update:** run the installer again. It replaces the program files and
  keeps your detections, settings and cached map tiles. Then restart the
  mapper (or reboot) so the new version is loaded.
- **Restart after a crash:** the cron job only starts the mapper at boot. To
  have it restarted whenever it exits, install with `--no-cron` and add a
  systemd service instead (replace `pi` with your user), then
  `sudo systemctl enable --now mesh-mapper`:

  ```ini
  # /etc/systemd/system/mesh-mapper.service
  [Unit]
  Description=Drone Mesh Mapper
  After=network.target

  [Service]
  User=pi
  WorkingDirectory=/home/pi/mesh-mapper
  ExecStart=/home/pi/mesh-mapper/.venv/bin/python mesh-mapper.py
  Restart=always
  RestartSec=5

  [Install]
  WantedBy=multi-user.target
  ```
- **Remove:** `crontab -e`, delete the `mesh-mapper.py` line, then delete
  `~/mesh-mapper`.

Not on a Debian-based system, or prefer to see each step? The manual install
in the [README](../README.md#set-it-up) does the same thing by hand.

---

## Direct Meshtastic radio input

`mesh-mapper.py --mesh PORT_OR_HOST` connects to a Meshtastic radio through
the official `meshtastic` Python package (`SerialInterface` on USB,
`TCPInterface` on WiFi, port 4403) and reads the text messages the field
stations' serial modules send. It replaces the ESP32 home node, whose only
job was to turn the radio's GPIO serial output into USB lines: a Heltec's USB
port speaks Meshtastic's protobuf client API instead, and
`override_console_serial_port` does not work in TEXTMSG mode.

**What arrives.** In TEXTMSG mode a serial module sends whatever its XIAO
wrote as a TEXT_MESSAGE_APP packet: the raw bytes with their `\r\n`, cut at
233 bytes or at a 250 ms pause. The mapper re-joins each sender's text and
splits it on newlines. A held piece older than 15 s is dropped, and text that
can't be the start of a station line (chat from a phone) is handed on at once.

**How each line is read:**

| Line | Becomes | `src` |
|---|---|---|
| JSON (node mode detection, level 1 `analog_fm` report or heartbeat) | handled exactly as a serial line from the home node | as sent |
| `Drone: <mac> RSSI:<n> [ID:<id>] [OP:<id>] [maps link]`, or the C5's `Drone[<band>]: ...` | detection with MAC, RSSI, IDs, position and `rf_band` | `mesh_text` |
| `Pilot: <maps link>` | the same sender's last `Drone:` record (within 10 s) with the pilot added | `mesh_text` |
| `Possible drone (<what>) <mac> RSSI:<n>` | fingerprint entry, `vendor` = `<what>` | `fingerprint` |
| anything else | counted as `unparsed`, ignored | - |

Text alerts don't say whether a hit came over WiFi or BLE, hence the two new
`src` values. The UI labels them and styles `fingerprint` like the other
heuristic hits.

**Dedup.** As on the home node, the first report of a MAC wins and repeats
inside `--mesh-dedup-ms` (500 ms) are dropped. Level 1 `analog_fm` reports
always pass, because each station's bearing is its own observation. The same
packet heard through two radios (same sender and packet id) is processed once.
Only `--mesh-channel` (default 0, the channel serial modules send on) is read.

**Added fields** on each detection: `mesh_from` (the sending radio's node id,
e.g. `!a1b2c3d4`), `mesh_snr`, `mesh_rssi`, `mesh_hops`. `source_port` reads
`mesh radio <port or host> <node id>`.

**Connection handling.** Each radio has a thread that connects, waits for the
radio's config, and reconnects with backoff (2 s doubling to 60 s) after a
lost connection. The library itself re-dials a dropped TCP socket. A serial
port given to `--mesh` is never opened by the ESP32 serial reader. The radios
show in the USB status list as `mesh radio ...`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/meshtastic` | Links (connected, radio, error, counters) and every node the radios know: last heard, SNR, hops, battery, voltage, channel and airtime use, power telemetry |
| `POST` | `/api/meshtastic` | `{"links": ["/dev/ttyACM0", "tcp:192.168.1.50"]}` replaces the radios (max 4) and saves them; `[]` clears |

**Testing without a radio.** `mapper_test/fake_meshtastic_radio.py` speaks
enough of the radio side of the protocol for the library to connect over a
pseudo-terminal (`--pty`) or TCP (`--tcp PORT`). `--demo` loops a mesh with a
Remote ID drone, two level 1 stations and a standalone detector (`--mapper
URL` places the level 1 stations). `mapper_test/test_mesh_direct.py` runs the
real mapper against it over both transports and checks every message format,
the dedup, telemetry, a TCP drop and reconnect, and that the mapper never
transmits.

---

## Offline maps

The mapper is built to run with no internet. Everything the UI needs - Leaflet, MapLibre GL, Socket.IO, the Orbitron font - is vendored under `static/` and served off local disk, never a CDN. Map tiles live in `tiles/` as standard MBTiles files. The server serves them, the browser renders them, and you fly.

> **The tiles caveat.** `tiles/` is **empty on a fresh clone** (the mapper creates it on first run), and the eight built-in basemaps listed below are online sources. So out of the box the interface is offline-capable but the basemap is not: with no connection and no cached `.mbtiles` you get a working map on a blank background - markers, tracks, pilot positions and geofences all draw correctly, because they come from your own detections rather than the basemap. **Cache your area while you still have a connection** and the map is genuinely self-contained in the field. The ways to populate `tiles/` are below.

### How it works in 30 seconds

```
+------------------+    /tiles/<name>/{z}/{x}/{y}.png    +------------------+
|   Leaflet (UI)   | <----------------------------------- |  Flask backend   |
+------------------+                                      |  + SQLite reader |
         |                                                +--------+---------+
         | XYZ tile request                                        |
         |                                                         v
         |                                                 tiles/area.mbtiles
         |                                                 (one row per tile)
```

Tiles are stored in MBTiles format (SQLite, one row per `(z, x, y, blob)`). The Flask `/tiles/<name>/<z>/<x>/<y>.<ext>` route flips XYZ to TMS and serves bytes. PBF vector tiles get `Content-Encoding: gzip` set so MapLibre decodes them transparently.

### The 8 built-in raster sources

| Dropdown name | Best for | Server | Max zoom | Bulk-cache OK? |
|---|---|---|---|---|
| **Esri World Imagery** | Satellite / actual ground | server.arcgisonline.com | 19 | yes |
| **Esri World Topo** | Hillshade + roads | server.arcgisonline.com | 19 | yes |
| **Esri Dark Gray** | Minimal dark canvas | server.arcgisonline.com | 16 | yes |
| **CartoDB Dark Matter** | Cyberpunk dashboards (matches UI) | basemaps.cartocdn.com | 20 | yes |
| **CartoDB Positron** | Light minimal - drone tracks pop | basemaps.cartocdn.com | 20 | yes |
| **OSM Standard** | Classic streets reference | tile.openstreetmap.org | 19 | NO - TOS forbids |
| **OSM Humanitarian** | Amenities, water, terrain emphasized | tile.openstreetmap.fr | 20 | low volume only |
| **OpenTopoMap** | Backcountry / contours / trails | tile.opentopomap.org | 17 | low volume only |

Mind each provider's TOS yourself - **the cacher does not enforce it**. OpenStreetMap's main tile server forbids bulk download, but picking OSM Standard with a wide bbox will still try. Use Esri/Carto for big jobs.

### Ways to populate `tiles/`

#### 1. From the live map UI - Cache This Area

Open the **CACHE THIS AREA** panel in the sidebar:

```
PLACE SEARCH         type "Yosemite National Park", click result, bbox auto-fills
REGION PRESETS       pick from California / PNW / Continental US / 12 more
Source / Name / zMin / zMax    manual control
~ N tiles (~M MB)    live estimate while you adjust
START CACHE          kicks off a job, progress bar in sidebar
WORLD BASELINE       one-click globe overview at z0-6 (~80 MB) or z0-8 (~1.3 GB)
IMPORT MBTILES       paste URL or upload file
```

#### 2. Region Presets (one-click)

Built-in operational areas. Selecting one pans + auto-fills the cache name:

| Preset | bbox |
|---|---|
| California | [-125, 32, -114, 42] |
| Pacific Northwest (OR/WA) | [-125, 42, -117, 49] |
| Eastern Sierra | [-120, 37, -117, 40] |
| Continental US | [-125, 24.5, -66.9, 49.4] |
| New England | [-74, 40, -66, 47.5] |
| Appalachian Trail corridor | [-85, 30, -76, 39] |
| Florida / Texas / Hawaii / Alaska | ... |
| United Kingdom & Ireland, Europe (whole), Benelux, Germany, France, Spain & Portugal, Italy, Poland, Nordics, Switzerland & Alps, Turkey | ... |
| Japan, South Korea, Taiwan, Singapore, India | ... |
| Australia (south-east), New Zealand | ... |
| Canada (Ontario & Quebec / British Columbia), Mexico, Brazil (south-east), Argentina & Chile | ... |
| South Africa, United Arab Emirates | ... |

Add more by editing the `<select id="regionPreset">` block in `mesh-mapper.py`.

#### 3. From a script - the cache API

There is no separate command-line cacher in this repository. The UI panel
starts its jobs through the mapper's HTTP API, and you can call that directly
while the mapper is running, for example from a headless Pi:

```bash
# Esri imagery over a box [west, south, east, north], zoom 0-16, into tiles/bay_area.mbtiles
curl -X POST http://localhost:5000/api/cache_tiles \
     -H 'Content-Type: application/json' \
     -d '{"name": "bay_area", "source": "esriWorldImagery",
          "bbox": [-122.6, 37.6, -122.3, 37.9], "zmin": 0, "zmax": 16}'

curl http://localhost:5000/api/cache_jobs          # progress of every job
```

`source` is one of `esriWorldImagery`, `esriWorldTopo`, `esriDarkGray`,
`cartoDarkMatter`, `cartoPositron`, `osmStandard`, `osmHumanitarian`,
`openTopoMap`. A job is limited to 2 million tiles and refused if the disk
doesn't have room. Re-running a job into the same name skips tiles it
already has.

#### 4. Drop in a prebuilt file

Anything in standard MBTiles format works. Just copy it into `tiles/` and refresh.

| Source | Type | Notes |
|---|---|---|
| https://data.maptiler.com/downloads/ | raster + vector | Free tier with signup |
| https://openmaptiles.com/downloads/ | vector | Some free samples; commercial planet |
| Self-built with `tilemaker` | raster/vector | Geofabrik OSM extract to tiles |
| OpenMapTiles Docker pipeline | vector | https://github.com/openmaptiles/openmaptiles |

### Vector tile support (OpenMapTiles schema)

Drop a vector `.mbtiles` (format: pbf) in `tiles/` and it appears tagged **[V]** in the dropdown. Renders through MapLibre GL using the bundled cyberpunk style at [`static/styles/default-dark.json`](../static/styles/default-dark.json).

```
[R] my_satellite (240 MB)    raster, served by Leaflet
[V] world_vector (52 MB)     vector, rendered by MapLibre GL
```

**Caveat**: the default style ships **without text labels** because glyph PBFs are bulky. Drop OpenMapTiles glyphs into `static/glyphs/<fontstack>/<range>.pbf` and add a `"glyphs"` key to the style JSON to enable place names.

### Recommended "hit the woods" loadout

About 1 GB in total. In the **CACHE THIS AREA** panel:

1. **WORLD BASELINE** at z0-6 on CartoDB Dark Matter (matches the UI)
2. Esri World Imagery over your area of operations at z8-16
3. OpenTopoMap over the same box at z8-14, for terrain

Then pull the ethernet, refresh the page, switch the basemap dropdown - page renders entirely from disk.

### Place search

Powered by [Nominatim](https://nominatim.openstreetmap.org/). Type a place name, get bbox results in the panel, click to apply. Respects Nominatim TOS (one req/sec max, meaningful User-Agent, results cached locally).

> Place search **requires internet** at search time. Cache the area first, then go offline. Region presets are 100% offline.

---

## ADS-B air traffic

Optional layer overlaying live aircraft on top of the drone RID feed. Six sources, ranging from zero-setup to "I have a HackRF in the woods":

### Network sources (no setup, just internet)

| Source | Free | Key | Notes |
|---|---|---|---|
| **adsb.lol** | yes | no | Default; community-run, generous limits |
| **adsb.fi** | yes | no | Alternate provider, same JSON shape |
| **airplanes.live** | yes | no | Another community feed |
| **OpenSky Network** | yes | optional auth | Anonymous tier ~100 req/day, auth raises it |
| **ADS-B Exchange** | paid | RapidAPI key | Bring your own key |

### Local SDR sources (HackRF, RTL-SDR, AirSpy, SDRplay)

| Source | How |
|---|---|
| **Local SDR (JSON)** | Polls `dump1090` / `readsb` / `tar1090` / `PiAware` HTTP JSON. URL presets included for each common setup. Path of least resistance if you already have any running. |
| **Beast TCP (native)** | Direct TCP connect to a raw Mode-S Beast feed (default port 30005). Decodes in-process via [pyModeS](https://github.com/junzis/pyModeS). Requires `pip install pyModeS`. Eliminates the need for a separate web frontend. |

### Quick paths

```bash
# Easiest: pick adsb.lol in the dropdown, hit SAVE - done

# HackRF / RTL-SDR + dump1090 (JSON path)
sudo apt install dump1090-fa
# UI: pick "Local SDR · HackRF" preset → SAVE

# HackRF / RTL-SDR + Beast (native, no web frontend)
pip install pyModeS
dump1090-fa --net --net-bo-port 30005 --device-type hackrf
# UI: source = "Beast TCP raw feed", host=localhost, port=30005 → SAVE
```

### Behavior
- Heading-rotated triangle markers, altitude-banded colors (red <1k → violet 35k+ ft)
- Aircraft trails: 60-point polyline history per ICAO, color matches current altitude
- Stale aircraft (>60 sec since last seen) auto-evicted
- Polite: configurable poll interval (2-120 sec), bbox-restricted queries, exponential backoff on upstream errors
- Config persisted to `adsb_config.json`; auto-resumes on restart

---

## API reference

### Detections
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Main web interface |
| `GET` | `/api/detections` | Current active drone detections |
| `POST` | `/api/detections` | Submit new detection data |
| `GET` | `/api/detections_history` | Historical detection data (GeoJSON) |
| `GET` | `/api/paths` | Flight path data for visualization |
| `POST` | `/api/reactivate/<mac>` | Reactivate inactive drone detection |

### Device management
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/aliases` | Get device aliases |
| `POST` | `/api/set_alias` | Set friendly name for device |
| `POST` | `/api/clear_alias/<mac>` | Remove device alias |
| `GET` | `/api/ports` | Available serial ports |
| `GET` | `/api/serial_status` | ESP32 connection status |
| `GET` | `/api/selected_ports` | Currently configured ports |

### Webhooks
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/set_webhook_url` | Configure webhook endpoint |
| `GET` | `/api/get_webhook_url` | Get current webhook URL |
| `POST` | `/api/webhook_popup` | Webhook notification handler |

### ADS-B air traffic
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/adsb/sources` | List sources + dump1090 URL presets |
| `GET` | `/api/adsb/config` | Current config (credentials masked) |
| `POST` | `/api/adsb/config` | Update config (`enabled`, `source`, `interval`, `bbox`, source-specific fields) |
| `GET` | `/api/adsb/aircraft` | Current aircraft snapshot |

WebSocket event: `adsb` - pushed every poll cycle when enabled.

### Offline tiles & maps
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/tiles/<name>/<z>/<x>/<y>.<ext>` | Serve a tile from `<name>.mbtiles` (png/jpg/webp/pbf) |
| `GET` | `/styles/<name>.json` | Auto-generated MapLibre style JSON for a vector layer |
| `GET` | `/api/offline_layers` | List discovered MBTiles + format / kind / size / zoom range |
| `DELETE` | `/api/offline_layers/<name>` | Delete a cached layer |
| `POST` | `/api/cache_tiles` | Start a tile cache job (`{name, source, bbox, zmin, zmax}`) |
| `GET` | `/api/cache_jobs` | List all cache jobs |
| `GET` | `/api/cache_jobs/<id>` | Job progress + status |
| `POST` | `/api/cache_jobs/<id>/cancel` | Request cancel |
| `POST` | `/api/import_mbtiles` | Import via JSON `{name, url}` (download) or multipart upload |
| `GET` | `/api/import_jobs/<id>` | Import progress |
| `POST` | `/api/import_jobs/<id>/cancel` | Cancel import |
| `GET` | `/api/geocode?q=<query>` | Nominatim place search proxy (cached + rate-limited) |

### Data export
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/download/csv` | Current detections (CSV) |
| `GET` | `/download/kml` | Current detections (KML) |
| `GET` | `/download/aliases` | Device aliases |
| `GET` | `/download/cumulative_detections.csv` | Full history (CSV) |
| `GET` | `/download/cumulative.kml` | Full history (KML) |

### System
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/diagnostics` | System health and performance |
| `POST` | `/api/debug_mode` | Toggle debug logging |
| `POST` | `/api/send_command` | Send command to ESP32 devices |
| `GET` / `POST` | `/api/meshtastic` | Directly read Meshtastic radios: status, nodes, configuration ([details](#direct-meshtastic-radio-input)) |
| `GET` / `POST` | `/select_ports` | Port selection interface |

### WebSocket events
Pushed to connected clients in real time:
`detections`, `paths`, `serial_status`, `aliases`, `cumulative_log`

---

## Performance

| Metric | Value |
|---|---|
| Detection latency | < 500ms |
| Concurrent drones | 50+ simultaneous |
| Memory (mapper) | < 100 MB typical |
| Per-detection storage | ~1 KB |
| Detections/min | 1000+ |
| Vendored UI assets | ~1.1 MB total (Leaflet + MapLibre + Socket.IO + Orbitron) |
| Tile cache rate | ~20 tiles/sec (50ms throttle, polite) |

---

## More troubleshooting

### Web interface won't load
```bash
netstat -tlnp | grep :5000     # is the server up?
tail -f mapper.log             # what's it saying?
```

### Tile cache job stuck
- Check `/api/cache_jobs/<id>` for `errors` count - likely upstream rate-limiting
- OSM main server will silently throttle; use Esri/Carto for bulk

### Vector layer renders blank / weird
- Default style targets the OpenMapTiles schema; other schemas (Tilezen, Protomaps) need a custom style JSON
- Check the browser console - MapLibre logs unknown layer-source mismatches there
- Verify the mbtiles `metadata.format` is `pbf`

### Offline mode shows online tiles
- Pick a layer tagged `[R]` or `[V]` in the basemap dropdown - those are the offline ones
- The 8 named sources (Esri / Carto / OSM / etc.) are **online** layers; their dropdown labels do not have the `[R]`/`[V]` prefix

---

## Project layout

```
drone-mesh-custom/  (claude/standalone-mapper-meshtastic)
|-- mesh-mapper.py              # Flask + SocketIO server, all UI inline, Meshtastic radio input
|-- requirements.txt            # includes meshtastic, for --mesh
|-- docs/
|   `-- REFERENCE.md            # This file
|-- static/                     # Vendored UI assets (offline-capable)
|   |-- leaflet/                # Leaflet 1.9.4
|   |-- leaflet-draw/           # Geofence drawing
|   |-- maplibre/               # MapLibre GL 4.7.1 + leaflet plugin
|   |-- socketio/               # Socket.IO client
|   |-- fonts/                  # Orbitron TTF + @font-face CSS
|   `-- styles/                 # MapLibre vector styles
|-- tiles/                      # MBTiles files (created on first run, auto-discovered)
|-- RPI/
|   `-- install_rpi.py          # Raspberry Pi installer + boot-time start
`-- mapper_test/
    |-- fake_meshtastic_radio.py   # Fake radio (USB pty or TCP) with a demo mesh
    |-- test_mesh_direct.py        # End-to-end test of the direct radio input
    |-- level1_bearing_sim.py      # Level 1 bearing stations over the HTTP API
    `-- mapper_test.py             # Simulated Remote ID drones over the HTTP API
```
