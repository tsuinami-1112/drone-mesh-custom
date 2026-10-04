# Drone Mesh Mapper - Reference

The detail that used to live in the main README. For the hardware, wiring,
flashing and getting the mapper running, start with the
[README](../README.md); come here for the rest.

- [Detection coverage](#detection-coverage)
- [Firmware variants and build options](#firmware-variants-and-build-options)
- [Mapper features](#mapper-features)
- [Raspberry Pi installer](#raspberry-pi-installer)
- [Offline maps](#offline-maps)
- [ADS-B air traffic](#ads-b-air-traffic)
- [API reference](#api-reference)
- [Performance](#performance)
- [More troubleshooting](#more-troubleshooting)
- [Project layout](#project-layout)

---

## Detection coverage

Everything below is passive and runs on the stock XIAO ESP32 radios, no extra
hardware:

| Layer | How | What you get |
|---|---|---|
| **Remote ID** - Open Drone ID per ASTM F3411 and ASD-STAN EN 4709-002 | BLE 4 legacy adverts, **BLE 5 Long Range** extended adverts, WiFi NAN action frames, WiFi Beacon vendor IEs | Serial number **and** registration ID (both Basic IDs), position, altitude, height, speed, heading, operator position, **Operator ID**, EU category/class, Self ID text, UA type |
| **DJI DroneID** (proprietary) | Beacon vendor IE of WiFi-link DJI aircraft (Spark, Mavic Pro WiFi mode, Mavic Air, Mavic Mini / Mini SE) | Serial, position, home point, pilot phone position, model. Broadcast worldwide, independent of Remote ID rules |
| **MAVLink** telemetry | UDP/TCP inside 802.11 data frames on **open** WiFi (ArduPilot / PX4 bridges, SITL, companion boards) | Position, altitude, heading, armed state, vehicle type, autopilot, and any OPEN_DRONE_ID_* messages on the link |
| **Fingerprints** (heuristic) | SSID patterns, IEEE MAC prefixes (24/28/36-bit), BLE names and company IDs | "Possible drone" for aircraft and controllers that broadcast nothing: DJI/Ryze, Parrot, Skydio, Autel, Yuneec, Hubsan, Holy Stone, Potensic, Snaptain, Ruko, FIMI, PowerVision, HOVERAir, Walkera, toy quads, FPV goggles, telemetry bridges. Confidence-tagged, rate-limited, never with a position |

The WiFi sniffer spends most of its time on channel 6 (the Remote ID channel)
and makes short excursions across channels 1-13 to catch access points that
sit elsewhere. Full details, the JSON schema and the limits are in
[`firmware-common/README.md`](../firmware-common/README.md).

### Outside the United States

The mapper decodes what the aircraft broadcasts and never consults a national
registry, so it works the same in every country. The identity section of a
drone's popup shows what matters where you are:

| Region | What is broadcast | What the UI shows |
|---|---|---|
| **EU / EEA, Switzerland, Norway** (EN 4709-002 direct remote ID, classes C1-C3, C5, C6) | serial number, **Operator Registration Number** (`FIN87astrdge12k8`, the 3 secret characters are never broadcast), EU category and class, operator position; BLE 4, BLE 5 Long Range, NAN or Beacon | `OPERATOR ID`, `SERIAL NUMBER`, `EU CATEGORY` (Open C1 ...) |
| **United Kingdom** (mandatory from 2026) | `GBR-OP-...` operator ID + serial | `OPERATOR ID`, `SERIAL NUMBER` |
| **Japan** (since June 2022) | registration `JU...` as Basic ID type 2 **plus** the serial as type 1, authentication, BLE 5 LR / Beacon / NAN | `REGISTRATION ID` and `SERIAL NUMBER` side by side |
| **USA** | serial or session ID, operator position | `SERIAL NUMBER` / `SESSION ID` |
| **China** | proprietary GB 42590 / GB 46750 formats, not decoded; DJI aircraft still show through DJI DroneID and fingerprints | `DJI DroneID`, `WiFi fingerprint` |
| **Everywhere** | WiFi-link DJI aircraft, toy and FPV quads, telemetry bridges | DJI DroneID and fingerprint entries (dashed amber in the list) |

Fingerprint hits are heuristics: a DJI MAC prefix is also an Osmo camera, and
a phone that once joined a Tello keeps probing for it. They are shown with
their confidence and without a position so they cannot be mistaken for a
decoded Remote ID track.

---

## Firmware variants and build options

The README covers the recommended XIAO ESP32-S3 builds. Every variant builds
with PlatformIO and shares one detection library (`firmware-common/detect`)
that PlatformIO pulls in through `lib_extra_dirs`:

| Path | Target | Notes |
|---|---|---|
| `node-mode-dualcore/` | ESP32-S3 dual-core | Remote node + home dedup node (`pio run -e remote_node` / `-e home_node`) |
| `remoteid-mesh-dualcore/` | ESP32-S3 / ESP32-C6 | BLE + WiFi concurrent detection, mesh relay |
| `remoteid-mesh/` | ESP32-C3 / ESP32-S3 | WiFi-only original variant, GPIO6/7 pinout |
| `remoteid-c5-5g/` | ESP32-C5 (+ S3 fallback) | Dual band: 2.4 GHz plus the UNII-3 5GHz Remote ID channels (149-165) |

```bash
cd remoteid-mesh-dualcore
pio run -e seeed_xiao_esp32s3 -t upload

# parsers are unit-tested on the host, no board needed
cd ../firmware-common/test && make
```

The BLE variants use `h2zero/NimBLE-Arduino` with extended advertising enabled
(`-D CONFIG_BT_NIMBLE_EXT_ADV=1`): the core's built-in BLE library cannot scan
the coded PHY, and BLE 5 Long Range is what most European and Japanese
add-on Remote ID modules transmit.

### Detection knobs

Add to the environment's `build_flags` in `platformio.ini`:

| Flag | Default | Effect |
|---|---|---|
| `-DDETECT_WIFI_HOP=0` | hopping on | Stay on channel 6 only: maximum Remote ID duty cycle, no DJI WiFi-link / toy-drone / bridge access points on other channels |
| `-DDETECT_HOME_DWELL_MS=700` | 700 | Time on channel 6 between excursions |
| `-DDETECT_AWAY_DWELL_MS=250` | 250 | Time on each other channel |
| `-DDETECT_MAVLINK=0` | on | Do not capture data frames (MAVLink on open WiFi) |
| `-DDETECT_FINGERPRINT=0` | on | Drop heuristic hits (devices without Remote ID) |

`remoteid-c5-5g` uses shorter dwell defaults (400 / 120 ms); each
`platformio.ini` lists its own.

### UART pins by variant

Every variant talks to the mesh radio at 115200 baud. Wire by GPIO number;
the XIAO D-labels differ from board to board:

| Firmware | UART GPIOs | XIAO ESP32-S3 | XIAO ESP32-C3 |
|---|---|---|---|
| `node-mode-dualcore`, `remoteid-mesh-dualcore`, `remoteid-c5-5g` | TX GPIO5, RX GPIO6 | TX D4, RX D5 | - |
| `remoteid-mesh` | TX GPIO6, RX GPIO7 | TX D5, RX D8 | TX D4, RX D5 |

On the XIAO ESP32-C6 and ESP32-C5, GPIO5 and GPIO6 are not among the
D0-D10 edge pins. Check Seeed's pinout for those boards before wiring.

### Prebuilt binaries

The images under `flasher/` and `firmware/` predate the detection expansion
and are no longer maintained (the web flasher has been retired). They only
decode US-style Remote ID on channel 6. Build from source as the README
describes.

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

```bash
wget https://raw.githubusercontent.com/colonelpanichacks/drone-mesh-mapper/main/RPI/install_rpi.py
python3 install_rpi.py --branch main          # stable
python3 install_rpi.py --branch Dev           # latest
```

Optional flags: `--install-dir /opt/mesh-mapper`, `--no-cron`, `--force`.

> `RPI/install_rpi.py` still downloads `mesh-mapper.py` from the upstream
> `colonelpanichacks/drone-mesh-mapper` repository, not from this one, so it
> installs the upstream mapper without this repository's changes. Until it is
> pointed here, use the manual install in the README.

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

#### 3. From the CLI - `tools/cache_tiles.py`

> `tools/cache_tiles.py` is documented upstream but is **not included in this
> repository**. Until it is added, use the UI panel above (the same cache job,
> through `POST /api/cache_tiles`) or drop in a prebuilt file.

```bash
# Single area, single source
python tools/cache_tiles.py \
    --bbox -122.6 37.6 -122.3 37.9 \
    --zoom 0 16 \
    --source esriWorldImagery \
    --out tiles/bay_area.mbtiles

# Globe baseline, every source (8 mbtiles files)
python tools/cache_tiles.py --preset world --source all --out tiles/

# Multi-source for one bbox (writes one mbtiles per source)
python tools/cache_tiles.py --preset world \
    --source esriWorldImagery,cartoDarkMatter,openTopoMap \
    --out tiles/

# Just count tiles, don't fetch
python tools/cache_tiles.py --preset world --source all --out tiles/ --dry-run
```

| Preset | bbox | zooms | tiles/source |
|---|---|---|---|
| `world` | global | 0-6 | ~5,500 |
| `world-z5` | global | 0-5 | ~1,400 |
| `world-z8` | global | 0-8 | ~88,000 |

The CLI is **resumable** - re-running skips tiles already in the MBTiles. Polite to free providers (50ms between fetches by default; tunable with `--rate`).

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

Two raster mbtiles + one vector overview, totaling ~1 GB. With the UI panel:
a **WORLD BASELINE** at z0-6 on CartoDB Dark Matter, then Esri World Imagery
over your area of operations at z8-16 and OpenTopoMap over the same box at
z8-14. The CLI equivalent (once `tools/cache_tiles.py` is available):

```bash
# 1. Globe-wide cyberpunk baseline (UI matches)
python tools/cache_tiles.py --preset world --source cartoDarkMatter --out tiles/

# 2. Satellite imagery for your AO
python tools/cache_tiles.py \
    --bbox -120.0 37.5 -119.0 38.5 \
    --zoom 8 16 \
    --source esriWorldImagery \
    --out tiles/op_zone_sat.mbtiles

# 3. Topo for terrain context
python tools/cache_tiles.py \
    --bbox -120.0 37.5 -119.0 38.5 \
    --zoom 8 14 \
    --source openTopoMap \
    --out tiles/op_zone_topo.mbtiles
```

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
drone-mesh-custom/
|-- mesh-mapper.py              # Flask + SocketIO server, all UI inline
|-- requirements.txt
|-- docs/
|   `-- REFERENCE.md            # This file
|-- static/                     # Vendored UI assets (offline-capable)
|   |-- leaflet/                # Leaflet 1.9.4
|   |-- maplibre/               # MapLibre GL 4.7.1 + leaflet plugin
|   |-- socketio/               # Socket.IO client
|   |-- fonts/                  # Orbitron TTF + @font-face CSS
|   `-- styles/                 # MapLibre vector styles
|-- tiles/                      # MBTiles files (created on first run, auto-discovered)
|-- RPI/                        # Raspberry Pi installer scripts (fetch the upstream mapper)
|-- firmware-common/            # Shared detection library + host unit tests
|   |-- detect/                 #   Open Drone ID, DJI DroneID, MAVLink, fingerprints
|   `-- test/                   #   make -> builds with gcc and runs synthetic-frame tests
|-- node-mode-dualcore/         # ESP32-S3 remote node + home node firmware
|-- remoteid-mesh-dualcore/     # ESP32-S3 / C6 BLE+WiFi firmware
|-- remoteid-mesh/              # WiFi-only firmware (C3 / S3)
|-- remoteid-c5-5g/             # ESP32-C5 dual-band firmware
|-- mapper_test/                # Mapper test scripts
|-- firmware/                   # Legacy prebuilt binaries (predate the detection expansion)
`-- flasher/                    # Retired web flasher and its legacy images
```
