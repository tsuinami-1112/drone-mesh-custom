# Standalone Mapper - Reference

Details for the standalone mapper branch. To get it running, start with the
[README](../README.md). The station hardware, the firmware and the full
project documentation live on the
[`level2-main`](https://github.com/tsuinami-1112/drone-sentinel/tree/level2-main) branch.

- [Mapper features](#mapper-features)
- [Raspberry Pi installer](#raspberry-pi-installer)
- [Direct Meshtastic radio input](#direct-meshtastic-radio-input)
- [Level 1 stations](#level-1-stations)
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
   `--branch standalone-mapper-meshtastic`; without `--branch` it
   installs the default branch, `level2-main`
2. creates a Python virtual environment in `~/mesh-mapper/.venv` and installs
   `requirements.txt` into it
3. adds an `@reboot` cron job for your user that starts the mapper from that
   environment

```bash
wget https://raw.githubusercontent.com/tsuinami-1112/drone-sentinel/standalone-mapper-meshtastic/RPI/install_rpi.py
python3 install_rpi.py --branch standalone-mapper-meshtastic
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
  Description=Drone Sentinel mapper
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
| JSON (node mode detection, level 1 `analog_fm` / `wideband` report or heartbeat) | handled exactly as a serial line from the home node | as sent |
| `Drone: <mac> RSSI:<n> [ID:<id>] [OP:<id>] [maps link]`, or the C5's `Drone[<band>]: ...` | detection with MAC, RSSI, IDs, position and `rf_band` | `mesh_text` |
| `Pilot: <maps link>` | the same sender's last `Drone:` record (within 10 s) with the pilot added | `mesh_text` |
| `Possible drone (<what>) <mac> RSSI:<n>` | fingerprint entry, `vendor` = `<what>` | `fingerprint` |
| anything else | counted as `unparsed`, ignored | - |

Text alerts don't say whether a hit came over WiFi or BLE, hence the two new
`src` values. The UI labels them and styles `fingerprint` like the other
heuristic hits.

**Dedup.** As on the home node, the first report of a MAC wins and repeats
inside `--mesh-dedup-ms` (500 ms) are dropped. Level 1 `analog_fm` and
`wideband` reports always pass, because each station's bearing is its own
observation. The same packet heard through two radios (same sender and packet
id) is processed once.
Only `--mesh-channel` (default 0, the channel serial modules send on) is read.

**Level 1 stations.** A heartbeat registers its station in the LEVEL 1
STATIONS panel. A station flashed with its position and heading
([Station setup](https://github.com/tsuinami-1112/drone-sentinel/tree/level1#station-location-and-heading))
sends them in its heartbeat, and the mapper places it there, marked **auto**.
Over the mesh only some heartbeats carry the position (the first three after
boot, then one every 10 minutes), so a mapper started later places the station
within 10 minutes; heartbeat fields a shorter mesh heartbeat leaves out keep
their last value. A position saved in the panel, including one saved before
this mapper knew flashed positions, overrides the flashed one on this mapper;
clear both position fields and press SAVE to go back to it. A heading saved in
the panel stays until the station is deleted (DEL), after which it registers
again from its next heartbeat.

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
Remote ID drone, a standalone detector and two level 1 stations flashed with
their positions, which the mapper places from their heartbeats (`--mapper URL`
places them by hand through the API instead), hearing an analog carrier and a
DJI O4-like digital link. `mapper_test/test_mesh_direct.py` runs the real
mapper against it over both transports and checks every message format (level
1 heartbeats and wideband reports as the firmware builds them, flashed
position included), the dedup, both bearing fixes and the system label,
telemetry, a TCP drop and reconnect, and that the mapper never transmits.

---

## Level 1 stations

A level 1 station (the
[`level1`](https://github.com/tsuinami-1112/drone-sentinel/tree/level1)
branch: a XIAO ESP32-C5 as a 5.8 GHz receiver behind four patch antennas on
an RF switch) finds a drone by its FPV video link and reports a **compass
bearing**, never a position. The mapper holds each station's position and the
heading of its face N (the LEVEL 1 STATIONS panel, or flashed into the station
with the level 1 Station setup task and sent in its heartbeat), rotates the
bearing, draws it as a ray from the station and, when two or more placed
stations report the same emitter within 30 s, intersects the rays into a
position fix with an error radius. The fix then behaves like any other
position (markers, paths, geofences, CSV, KML, webhooks). A station registers
itself from its first heartbeat; only its position has to be set. Reports
arrive like every other detection: over USB, `POST /api/detections`, or as
mesh text read straight off a radio, whose dedup lets both level 1 types
through (each station's bearing is needed).

### Analog video (`"type":"analog_fm"`)

```json
{"type":"analog_fm","mac":"AF:00:52:03:16:64","freq_mhz":5732,"band":"R","ch":3,
 "rssi":-68,"bearing_deg":32,"bearing_sigma_deg":15,"video":"NTSC",
 "fp":"NTSC/15736/5734","node_id":"RX01"}
```

The MAC is synthesised from the channel (`AF:00:` + band letter, channel
number, frequency), so every station that hears the carrier reports the same
one. Reports within 10 MHz of a live analog track are the same emitter (the
R3 5732 / B1 5733 / F1 5740 cluster spans 8 MHz).

### Digital video links (`"type":"wideband"`)

A channel that stays above threshold with a noise-like envelope - an OFDM
link rather than an FM carrier - is confirmed over eight windows and reported
as

```json
{"type":"wideband","mac":"DF:00:52:04:16:89","freq_mhz":5769,"fc_mhz":5768.5,"band":"R","ch":4,
 "rssi":-61,"rssi_dbm":-61.4,"level_db":28.0,"cls":"lte","conf":"high","bw_mhz":10,"duty":95,
 "cv2":0.98,"r1":0.85,"r128":0.010,"r512":0.012,"r2667":0.056,"span_mhz":0,
 "bearing_deg":32,"bearing_sigma_deg":21,"fp":"lte/10/5768.5","basic_id":"5.8G-R4-5769MHz",
 "node_id":"RX01"}
```

| Field | Meaning |
|---|---|
| `mac` | `DF:00:` + band letter, channel number, frequency of the table channel the station folded the emitter to: the tracking key |
| `freq_mhz`, `band`, `ch` | that table channel |
| `fc_mhz` | estimated centre of the link: channel + spectral centroid |
| `cls` | coarse waveform class: `lte` (66.7 µs symbols: DJI OcuSync, O3, O4), `dot11` (802.11 OFDM, 3.2 µs symbols), `wb` (neither feature above its floor) |
| `conf` | the station's confidence in `cls`: `high`, `med` or `low` |
| `bw_mhz` | bandwidth bucket from the lag-1 autocorrelation: 10, 20, 30 or 40 |
| `duty` | percent of the confirmation windows the link was on; a report needs 75 |
| `cv2`, `r1`, `r128`, `r512`, `r2667` | the raw features: envelope variance / mean², lag autocorrelations \|R(L)\| / R(0) |
| `span_mhz` | width of the footprint across table channels in that sweep, 0 when it fit one |
| `bearing_deg`, `bearing_sigma_deg` | as for analog; the sigma carries an extra 5° plus 0.2° per percent of duty missing |
| `fp`, `basic_id` | `cls/bw/fc`, and `5.8G-R4-5769MHz` (`2.4G-G3-2442MHz` on a dual-band station) |

The other fields (`rssi*`, `level_db`, `gain`, `q_phase`, `cfo_khz`,
`sectors`, `sector`, `station_heading`, `seq`) mean what they mean in an
analog report. The mesh copy is cut at 191 bytes: `type`, `mac`, `node_id`
and `freq_mhz` must fit, then `rssi`, `bearing_deg`, `bearing_sigma_deg`,
`cls`, `fc_mhz`, `bw_mhz`, `duty`, `conf`, `fp`, `sector` and `seq` are tried
one by one in that order and each kept only if it still fits (a short field
can make it after a longer one did not). With a four-character node id `conf`
and `fp` are already out, and whether `sector` or `seq` fits turns on the
digit counts. The mapper fills `fc_mhz`, `bw_mhz`, `cls`, `duty` and `conf`
that a copy dropped from the track's last report, so the system label does
not come and go with the budget; `fp` is carried over like the other identity
fields, `band` and `ch` (never on the mesh line) come from the track when it
has them, a missing `basic_id` is synthesised from `freq_mhz`
(`5.8G-5769MHz`), and `sector` and `seq` stay missing.
`mapper_test/fake_meshtastic_radio.py` builds that line (`l1_mesh_wideband`)
for the demo mesh and the end-to-end test.

A report posted by hand is held to what the firmware emits: `bw_mhz` 10-60,
`duty` 0-100 and `span_mhz` 0-1000 (clamped), `cls` and `conf` from the lists
above (anything else is dropped), `fp` and `basic_id` as `[A-Za-z0-9/._:-]`
up to 40 characters, and the features rounded to the precision of the USB
line.

**Merging.** A digital link is wider than the channel grid, so two stations
can key the same emitter to different `DF:` MACs. A wideband report merges
onto the live wideband track whose centre is within `max(bw, bw') / 2 + 5 MHz`
of its own; it never merges onto an analog track, nor an analog report onto a
digital one.

**Naming the system.** The mapper matches `fc_mhz`, `bw_mhz`, `cls` and
`duty` against the `WIDEBAND_SYSTEMS` table in `mesh-mapper.py` and writes
`system` and `system_conf` into the detection (the popup's IDENTIFICATION
section, the detection list, the CSV). A row matches when the centre is
within 2 MHz of one of its channels (or inside a band it owns), the bandwidth
bucket is one of the row's or the next one up or down the 10 / 20 / 30 / 40 /
60 ladder (a copy without `bw_mhz` counts as one step off), and the class
agrees where the row states one; the two 802.11 rows also need `duty`. A row
whose class agrees outranks one that takes any, a listed centre outranks a
band, an exact bucket a neighbouring one, the nearer centre the farther; among
equals the first row wins.

| System | Centres (MHz) and buckets | Class | Best match |
|---|---|---|---|
| DJI O4 | 5794.5 (40, 60); 5768.5, 5789.5, 5814.5 (20, 10); 5170-5250 any width (CE) | `lte` (expected, unverified) | med |
| DJI O3 | 5794.5 (40); 5768.5, 5804.5, 5839.5 (20, 10) | `lte` (expected, unverified) | med |
| DJI OcuSync 2 | 5756.5, 5776.5, 5796.5 (10); 2399.5, 2414.5, 2429.5, 2444.5, 2459.5 (10) | `lte` | high |
| Walksnail Avatar / DJI FPV V1 | 5660, 5695, 5735, 5770, 5805, 5839, 5878, 5914 (20); 5695, 5770, 5839, 5878 also (40) | any | high |
| HDZero | 5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917 (30 = the 27 MHz mode, 20 = the 17 MHz narrow one) | any | high |
| 802.11 video link (wfb-ng / OpenIPC-like) | a centre within 2 MHz of the 5 MHz Wi-Fi grid, `duty` ≥ 90 | `dot11` | med |
| Wi-Fi traffic | `duty` < 90 | `dot11` | low |
| unknown digital | nothing above matched | | low |

`system_conf` is the row's best match, lowered to `med` when the centre is
more than 1 MHz off or the bucket a step off, when only a band matched, or
when a second system matched equally well (5768.5 is an O3 and an O4 channel;
5769.5 is as close to HDZero's 5769 as to Walksnail's 5770), and never above
the station's own `conf` (a mesh copy that dropped `conf` counts as `med`). To
add a system, put a row where its likelihood ranks it (among equal matches the
first row wins): `system`, `centres` (`{MHz: (buckets)}`), optional `bands`
(`((low, high),)`), `cls`, `duty_min` / `duty_max`, `grid_mhz`, `quality`.

### Boot line and heartbeat

The station's console prints a boot line (`{"info":"c5phy v3 station ready",...}`, which the
mapper logs at debug level and otherwise ignores) and a heartbeat every 60 s
on USB and every 120 s over the mesh
(`{"heartbeat":true,"node_id":..,"receiver":"c5phy",..}`), from which the
mapper registers the station and fills its popup. Added with the wideband
firmware:

| Field | Where | Meaning |
|---|---|---|
| `bands` | boot line, USB heartbeat | `"5.8"`, or `"2.4+5.8"` for the dual-band build |
| `antenna_dbi` | boot line, USB heartbeat | patch gain the station was flashed with (Station setup) |
| `beamwidth_deg` | boot line, USB heartbeat | 3 dB beamwidth, derived from the gain unless overridden (8 dBi → 72°) |
| `bearing_k` | boot line, USB heartbeat | degrees of bearing per dB of neighbour-sector difference (8 dBi → 3.0) |
| `wideband`, `pullin`, `gain_step` | boot line | the build's `WIDEBAND` and `PULLIN` switches and its `GAIN_STEP` |
| `wb_seen` | USB heartbeat (after `bearing_k`), mesh heartbeat (after `video_seen`) | digital links confirmed since boot |
| `pullin` | USB heartbeat | off-channel analog carriers retuned onto and re-measured since boot |
| `nf_dbm_24` | USB heartbeat, dual-band build only | 2.4 GHz noise floor (`nf_dbm` stays the 5 GHz one) |

The mapper keeps `bands` (`5.8` or `2.4+5.8`; anything else is dropped),
`antenna_dbi`, `beamwidth_deg`, `bearing_k`, `wb_seen` and `pullin` with the
station's other heartbeat fields (`status` in `GET /api/stations`, and the
station popup's **video seen** "N analog / M digital", **pull-ins**, **plan**
and **antenna** rows); `nf_dbm_24` it does not keep.

`mapper_test/level1_bearing_sim.py` fakes two or three stations and one
drone through the HTTP API, analog by default and a DJI O4-like link with
`--wideband`.

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

### Level 1 stations
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/stations` | Stations (position, heading, `position_auto` / `heading_auto` while they follow what the station reports, its last reported `rep_lat` / `rep_lon`) and their last heartbeat |
| `POST` | `/api/stations` | Add or update a station: `{node_id, name, lat, lon, heading_deg}`. `lat`/`lon` set its position by hand; both empty (`""` or `null`) go back to the position the station reports (unplaced if it has reported none); left out, the position stays as it is. `heading_deg` sets the heading by hand |
| `DELETE` | `/api/stations/<node_id>` | Remove a station; a running one registers again from its next heartbeat |
| `GET` | `/api/bearings` | Recent bearing reports, per emitter MAC (`AF:` analog, `DF:` digital video link) and station |

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
`detections`, `paths`, `serial_status`, `aliases`, `cumulative_log`, `stations`

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
drone-sentinel/  (standalone-mapper-meshtastic)
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
    |-- level1_bearing_sim.py      # Level 1 bearing stations (analog, or --wideband) over the HTTP API
    `-- mapper_test.py             # Simulated Remote ID drones over the HTTP API
```
