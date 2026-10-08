# level1-c5phy - Level 1 station v3 firmware (XIAO ESP32-C5)

The XIAO ESP32-C5's own 5 GHz Wi-Fi radio as the FPV receiver: 5.8 GHz analog
FM video links and the digital video links that replaced them (DJI O3 / O4 /
OcuSync, Walksnail, HDZero, 802.11-based links such as OpenIPC / wfb-ng).
Four patch antennas on an SP4T RF switch (optionally through one 20 dB LNA +
band-pass filter) feed the XIAO's U.FL; the firmware holds the PHY
receive-only on each channel of its plan, captures raw I/Q from the modem's
diagnostic bus through PARLIO, measures power, FM coherence and the envelope
per sector, checks the strongest analog hits for a PAL/NTSC line structure,
confirms channels that stay above threshold with a noise-like envelope over
eight more windows as digital links (`"type":"wideband"`, with a waveform class
and a bandwidth bucket) and reports a compass bearing for both kinds.
Hardware, wiring and the bench procedure: `../docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`.
How the station decides, gate by gate, with every threshold and the reason
for it: [`../docs/Level1-Detection-Internals.md`](../docs/Level1-Detection-Internals.md).

Two build environments share the code:

| Environment | Antennas | Plan | Notes |
|---|---|---|---|
| `seeed_xiao_esp32c5` | four 5.8 GHz patches, optional 5.8 GHz LNA + band-pass filter | R A B E F, X1 X2, D1-D3, L4-L8 (50 channels) | the generic bench build |
| `seeed_xiao_esp32c5_dualband` | four dual-band 2.4 + 5.8 GHz patches, no band-pass filter, LNA (if any) wideband | the same plus G1-G5 at 2.4 GHz (55 channels) | `extends` the first and adds `-DDUAL_BAND=1`: PHY in auto band mode, BW40 on both bands, the `*_24` calibration and antenna constants of `config.h` on 2.4 GHz, `nf_dbm_24` in the USB heartbeat, `"bands":"2.4+5.8"` in the boot line |

The receiver bring-up re-implements, on the fleet's Arduino core 3.3 /
ESP-IDF 5.5 toolchain, what [C5VRX](https://github.com/KonradIT/C5VRX) proved on
hardware with ESP-IDF 6.0. **Nothing in this directory has run on hardware
yet**; the bench guide's stages 0-8 are the acceptance path. The host tests and
both builds run in CI on every push (`.github/workflows/firmware.yml`).

## Build and flash

```bash
pio run -e seeed_xiao_esp32c5 -t erase      # every flash starts with a full erase
pio run -e seeed_xiao_esp32c5 -t upload
pio run -e seeed_xiao_esp32c5 -t monitor    # 115200
```

A station with dual-band patches: the same three commands with
`-e seeed_xiao_esp32c5_dualband`.

Those are the generic bench builds. A deployed station is flashed from its own
environment in `stations.ini` (`pio run -e RX01 -t erase`, `... -t upload`),
which `extends` one of the two and sets `NODE_ID`, `STATION_LAT`/`STATION_LON`,
`STATION_HEADING_DEG` and the antenna constants from its `custom_*` options:

| `stations.ini` option | Define | Checked |
|---|---|---|
| `custom_node_id` | `NODE_ID` | letters, digits, `_` `-` `.` `:`, up to 23 |
| `custom_station_lat`, `custom_station_lon` | `STATION_LAT`, `STATION_LON` | both or neither, -90..90 / -180..180 |
| `custom_station_heading` | `STATION_HEADING_DEG` | 0..360 |
| `custom_antenna_dbi` | `ANTENNA_GAIN_DBI` | 0..20 (default 8) |
| `custom_antenna_beamwidth_deg` | `ANTENNA_BEAMWIDTH_DEG` | 20..180; empty = derived from the gain |
| `custom_bearing_k` | `BEARING_K_DEG_PER_DB` | 0.5..20; empty = derived from the beamwidth |
| `custom_antenna_dbi_24`, `custom_antenna_beamwidth_deg_24`, `custom_bearing_k_24` | `ANTENNA_GAIN_DBI_24`, `ANTENNA_BEAMWIDTH_DEG_24`, `BEARING_K_DEG_PER_DB_24` | the same ranges (default 6 dBi); only on an environment that extends the dual-band one, ignored with a warning otherwise |

`tools/station.py` checks them at build time, refuses a value set twice (by an
option and by `-D`), warns when the beamwidth it derives is under 60 deg (four
sectors 90 deg apart leave holes at the boundaries), and provides the
"Station setup (map)" task that writes the file
(`pio run -e seeed_xiao_esp32c5 -t station_setup`): position, heading and the
antennas (5.8 GHz patches only, or dual-band patches, which picks the
environment the station extends). See the main README's Station setup section
and `stations.example.ini`.

Boot mode if the board will not connect: hold BOOT, tap RESET, release BOOT.

## Pins (XIAO ESP32-C5, GPIO numbers of the Arduino variant)

Unchanged by the digital-link work: the dual-band build uses the same pins,
switch and wiring. Everything is on the top-side castellations; no underside
pad is used.

| Function | XIAO pin | GPIO | Notes |
|---|---|---|---|
| UART TX to Heltec RX | D4 | 23 | 115200, the same pins as every station tier |
| UART RX from Heltec TX | D5 | 24 | |
| Switch V1 / V2 / V3 | D8 / D9 / D7 | 8 / 9 / 12 | 2 kOhm series; `SECTOR_SWITCH_TABLE` from the stage 6 truth table. Which line states mean N/E/S/W, and which port that is on a PE42442 (N = RF4): [antenna sectors](../README.md#antenna-sectors-how-the-switch-lines-cycle) |
| I/Q lane pads Q7 Q8 Q9 | D0 D1 D2 | 1 0 25 | **must stay unconnected**: each MODEM_DIAG bit is driven out through the pad and read back from it |
| I/Q lane pads I7 I8 I9 | D3 D10 D6 | 7 10 11 | same rule |
| user LED | on board | 27 | blinks on every report |

### Channel plan

The default scan plan has 50 channels, in this order:

| Letters | Channels | Flag | Why they are scanned |
|---|---|---|---|
| R A B E F | the 40 analog FPV channels, 5645-5945 MHz | always | analog video; the digital systems' channel grids sit on the same points (HDZero on R, Walksnail near R) |
| X1 X2 | 5675, 5715 | `GAP_CHANNELS` (1) | the two 20 MHz holes of the analog table, so a carrier there gets a table key of its own |
| D1 D2 D3 | 5190, 5210, 5230 | `SCAN_5G1` (1) | three 40 MHz views over DJI O4's CE band 5170-5250 |
| L4-L8 | 5473-5621, 37 MHz apart | `LOWBAND` (1) | Lowband, reachable from the public Wi-Fi centres 100-124 |
| L1-L3 | 5362, 5399, 5436 | `LOWBAND=2` | sit 64-138 MHz under Wi-Fi 100: `rf_tune` refuses them unless `C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ` is raised from 60 to 140, a pull nothing has proven |
| G1-G5 | 2402-2482, 20 MHz apart | `DUAL_BAND=1` (the dual-band environment) | OcuSync 2 and Wi-Fi-based links at 2.4 GHz; dual-band patches only |

`-DSCAN_5G1=0`, `-DLOWBAND=0` and `-DGAP_CHANNELS=0` take their points out
again. The plan is 55 channels on the dual-band build, 58 with everything on;
`MAX_CHANNELS` (64) bounds the per-channel arrays. Four analog channels (R8,
E6, E7, E8 at 5905-5945 MHz) sit above the last public 5 GHz centre and rely on
`phy_set_freq` pulling the synthesizer up to 60 MHz past it, which bench stage 2
proves; the same pull is what reaches the top digital channels, HDZero R8 at
5917 MHz and Walksnail's 5914 MHz. A hit, or a wideband candidate, up there
that merely mirrors a carrier at 5885 is dropped (`alias_drop` in the heartbeat
counts both); `-DC5PHY_MAX_MHZ=5885` removes those channels from the plan.

The eleven top-side GPIOs cannot hold the eight I/Q lanes C5VRX uses next to
the D4/D5 UART and the switch lines, so this station wires six: bits 9..7 of
Q and I, the sign and two magnitude bits. The firmware reads the missing bit
6 as the midpoint of the two codes it would have separated (`IQ_LANE_BITS 3`
in `config.h`), so the level, coherence and video code are unchanged. The
desktop tests print the price: referenced to its own measured noise floor,
the six-lane decode tracks the eight-lane one within 0.2 dB and a few
percent of coherence at every amplitude, with identical video detection at
and above the hit threshold and a few lost video windows well below it. The
floor itself reads a little higher (the decode never returns 0), so measure
`RF_NOISE_POWER` on the bench in the lane mode you build. A dead I/Q bus shows
every sample identical; the firmware flags that as `stuck` in the bench line
and counts `bus_stuck` in the heartbeat (an all-zero stuck pattern also reads
exactly 2.0, the noise reference, so the flag is what to trust).
`-DIQ_LANE_BITS=4` restores the C5VRX lane set, which needs the underside
GPIO2-5 pads.

## Serial contract

The detection, wideband and heartbeat lines below are the host tests' output
(`cd test/host && make` prints them as `JSON_USB` / `JSON_MESH` and
`check_json.py` validates them); the boot line is the firmware's format with
the defaults filled in.

USB, boot:

```json
{"info":"c5phy v3 station ready","node_id":"A1B2","receiver":"c5phy","hw":"v3","channels":50,"sectors":4,"heading":0,"fe_gain_db":0.0,"threshold_dbm":-87.0,"threshold_level_db":8.0,"q_min":40,"peak_pick":1,"video":1,"bw40":1,"gain_max":62,"window_us":409,"iq_lane_bits":3,"bands":"5.8","antenna_dbi":8.0,"beamwidth_deg":72,"bearing_k":2.97,"wideband":1,"pullin":1,"gain_step":3,"mesh_uart":"D4 TX / D5 RX 115200","phy_set_freq":true,"rf":true}
```

A station flashed with its position adds `"lat"` and `"lon"` right after
`heading`. The fields added with the digital-link work: `bands` (`"5.8"`, or
`"2.4+5.8"` on the dual-band build), `antenna_dbi`, `beamwidth_deg` and
`bearing_k` (the 5.8 GHz patches as flashed: gain, the beamwidth derived from
it unless overridden, degrees of bearing per dB of neighbour-sector
difference), `wideband` and `pullin` (the build's `WIDEBAND` / `PULLIN`
switches) and `gain_step` (`GAIN_STEP`, 3). `"channels"` counts the plan:
50, 55 on the dual-band build.

`"rf":false` is preceded by `{"info":"error","stage":...,"call":...,"err":...}`
naming the call that failed (a missing undocumented PHY symbol included).

### Analog video link

USB, one line per hit per sweep (`rssi` is dBm like every other station tier;
`rssi_raw` is the 10-bit RX5808-style value of the v2 contract; `bearing_deg`
is relative to the box's face N and the mapper rotates it by the station
heading). Unchanged by the digital-link work:

```json
{"type":"analog_fm","receiver":"c5phy","hw":"v3","mac":"AF:00:52:03:16:64","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"rssi_dbm":-68.1,"rssi_raw":536,"rssi_min":-70,"rssi_max":-66,"rssi_n":3,"level_db":26.9,"gain":50,"q_phase":71,"cfo_khz":1840,"carrier":"fm","sectors":[-68.1,-74.4,-91.0,-85.2],"sector":0,"bearing_deg":32,"bearing_sigma_deg":15,"station_heading":0,"freq_peak":5734,"video":"NTSC","sync_hz":15736,"field_hz":60,"sync_q":88,"sync_score":91,"video_windows":8,"fp":"NTSC/15736/5734","basic_id":"5.8G-R3-5732MHz","node_id":"RX01","seq":42}
```

An analog hit now needs three things on the strongest sector: `level_db` >=
8 dB over the noise reference, `q_phase` >= 40 % FM coherence, and a constant
envelope (`cv2` <= 0.5; the bench line shows `cv2`, the report does not). A
carrier pulled in from between two table channels (`PULLIN`) is reported on the
nearest table channel with `freq_peak` at the carrier and `cfo_khz` relative to
`freq_mhz`, like any other hit.

Mesh (Serial1 to the Heltec, <= 191 bytes, at most one per emitter per
`MESH_REPORT_INTERVAL_MS`):

```json
{"type":"analog_fm","mac":"AF:00:52:03:16:64","node_id":"RX01","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"bearing_deg":32,"bearing_sigma_deg":15,"video":"NTSC","fp":"NTSC/15736/5734"}
```

### Digital video link

USB, one line per confirmed link per sweep:

```json
{"type":"wideband","receiver":"c5phy","hw":"v3","mac":"DF:00:52:04:16:89","freq_mhz":5769,"fc_mhz":5768.5,"band":"R","ch":4,"rssi":-66,"rssi_dbm":-66.3,"rssi_raw":559,"rssi_min":-68,"rssi_max":-65,"rssi_n":8,"level_db":28.7,"gain":44,"q_phase":41,"cfo_khz":-480,"cls":"lte","conf":"high","bw_mhz":10,"duty":100,"cv2":0.98,"r1":0.85,"r128":0.009,"r512":0.007,"r2667":0.056,"span_mhz":0,"sectors":[-66.3,-72.8,-90.1,-84.0],"sector":0,"bearing_deg":20,"bearing_sigma_deg":16,"station_heading":0,"fp":"lte/10/5768.5","basic_id":"5.8G-R4-5769MHz","node_id":"RX01","seq":43}
```

| Field | Meaning |
|---|---|
| `mac` | `DF:00:` + band letter, channel number and MHz of the table channel the link was folded to: the tracking key (`DF` = digital FPV, next to `AF` = analog FM) |
| `freq_mhz`, `band`, `ch` | that table channel |
| `fc_mhz` | estimated centre of the link: `freq_mhz` + `cfo_khz` / 1000, the spectral centroid averaged over the confirmation pass |
| `rssi`, `rssi_dbm`, `rssi_raw`, `rssi_min`, `rssi_max`, `rssi_n` | as for analog, over the confirmation pass: `rssi_dbm` from the mean level of the "on" windows, min / max over all of them, `rssi_n` the windows captured (8) |
| `level_db`, `gain`, `q_phase`, `cfo_khz` | as for analog; `q_phase` is the mean coherence of the on windows (model: LTE-like ~40, 802.11 20 MHz ~30, 802.11 40 MHz under 10) |
| `cls` | coarse waveform class from the lag autocorrelations: `lte` (`r2667` >= 0.03 and `r128` < 0.05: 66.7 us symbols, DJI OcuSync / O3 / O4), `dot11` (`r128` >= 0.10: 802.11 OFDM, 3.2 us symbols), `wb` (neither) |
| `conf` | `high`: `duty` >= 90 and the deciding feature at or above its high mark (`r128` 0.15, `r2667` 0.04); `med`: a named class with `duty` >= 75; `low`: class `wb` |
| `bw_mhz` | bandwidth bucket 10 / 20 / 30 / 40 from the lag-1 autocorrelation (scaled back by the window's S+N over S before the bucket): >= 0.78 -> 10, >= 0.52 -> 20, >= 0.30 -> 30, else 40 |
| `duty` | percent of the 8 confirmation windows within 6 dB of the loudest one; a report needs >= 75 |
| `cv2` | envelope variance / mean^2, mean of the on windows (~1 on OFDM) |
| `r1`, `r128`, `r512`, `r2667` | the raw features, \|R(L)\| / R(0) of the decoded window at lags 1, 128 (3.2 us), 512 (12.8 us, 11ax) and 2665..2669 (66.7 us, the best of the five), mean of the on windows; their noise floor is ~0.01 |
| `span_mhz` | width of the link's footprint across the table channels of that sweep (max - min MHz of the candidates folded into this one); 0 when it showed on one channel |
| `sectors`, `sector`, `bearing_deg`, `bearing_sigma_deg`, `station_heading` | as for analog; the sector levels come from one window per sector in the order N E S W W S E N at the pass's gain (the maximum per sector), and the sigma carries 5 deg more than an analog bearing plus 0.2 deg per percent of `duty` under 100 |
| `fp` | `cls/bw_mhz/fc_mhz` |
| `basic_id` | `5.8G-R4-5769MHz`; a 2.4 GHz channel reads `2.4G-G3-2442MHz` (all of 5 GHz keeps `5.8G`, D1 included) |
| `node_id`, `seq`, `receiver`, `hw` | as for analog; `seq` is shared with the analog reports |

Mesh (<= 191 bytes, the same pacing as analog, keyed by the table channel).
`type`, `mac`, `node_id` and `freq_mhz` always; then `rssi`, `bearing_deg`,
`bearing_sigma_deg`, `cls`, `fc_mhz`, `bw_mhz`, `duty`, `conf`, `fp`, `sector`,
`seq`, each added only if it still fits, so a short field can follow a dropped
longer one. With a 4-character node id the line ends at `duty` plus `sector`;
with a 22-character one at `bw_mhz`:

```json
{"type":"wideband","mac":"DF:00:52:04:16:89","node_id":"RX01","freq_mhz":5769,"rssi":-66,"bearing_deg":20,"bearing_sigma_deg":16,"cls":"lte","fc_mhz":5768.5,"bw_mhz":10,"duty":100,"sector":0}
{"type":"wideband","mac":"DF:00:52:04:16:89","node_id":"STATION-NORTH-TOWER-01","freq_mhz":5769,"rssi":-66,"bearing_deg":20,"bearing_sigma_deg":16,"cls":"lte","fc_mhz":5768.5,"bw_mhz":10}
```

The mapper names the system (DJI O4, HDZero, Wi-Fi traffic, ...) from `fc_mhz`,
`bw_mhz`, `cls` and `duty`; that table lives in the mapper, see
[level2-main's REFERENCE.md](https://github.com/tsuinami-1112/drone-sentinel/blob/level2-main/docs/REFERENCE.md).

### Heartbeat

Every 60 s on USB (120 s on the mesh) with `"heartbeat":true`:

```json
{"heartbeat":true,"node_id":"RX01","receiver":"c5phy","hw":"v3","scanning":true,"channels":50,"sectors":4,"heading":0,"threshold_dbm":-87.0,"threshold_level_db":8.0,"video_seen":7,"gain_max":62,"bw40":1,"fe_gain_db":0.0,"bands":"5.8","antenna_dbi":8.0,"beamwidth_deg":72,"bearing_k":3.00,"wb_seen":2,"pullin":1,"tune_fail":0,"cap_err":0,"bus_stuck":0,"alias_drop":0,"sweeps":1830,"usb_drop":0,"mesh_drop":0,"nf_dbm":-98,"temp_c":41.2,"uptime_s":3600,"seq":42}
{"heartbeat":true,"node_id":"RX01","receiver":"c5phy","hw":"v3","heading":0,"scanning":true,"sweeps":1830,"video_seen":7,"wb_seen":2,"nf_dbm":-98,"temp_c":41.2,"uptime_s":3600,"tune_fail":0}
```

Added with the digital-link work: `bands`, `antenna_dbi`, `beamwidth_deg` and
`bearing_k` (as in the boot line; the test fixture sets `bearing_k` 3.00 by
hand, the defaults print 2.97) after `fe_gain_db`, then `wb_seen` (digital
links confirmed since boot) and `pullin` (off-channel carriers retuned onto and
re-measured since boot). The dual-band build adds `nf_dbm_24`, the 2.4 GHz
noise floor, right after `nf_dbm` (which stays the 5 GHz one) on the USB line
only. The mesh heartbeat carries `wb_seen` right after `video_seen`; the rest of
its tail (`nf_dbm`, `temp_c`, `uptime_s`, `tune_fail`, `cap_err`, `bus_stuck`,
`alias_drop`) goes in as far as the 191 bytes allow. A station built with
`STATION_LAT`/`STATION_LON` adds `"lat"` and `"lon"` (6 decimals) right after
`heading`: in every USB heartbeat, and in the mesh heartbeat on the first three
after boot and then every `STATION_POS_EVERY`-th (5, i.e. 10 min). On those
mesh heartbeats the position outranks the tail, so `uptime_s`, `temp_c` and the
counters may drop out of that line. The mapper registers a station from its
first heartbeat and places it at the reported position until one is set by hand.
`NODE_ID` may use letters, digits and `_ - . :`; anything else is dropped from
it, and an empty result falls back to the MAC-derived id. `heading` in the
heartbeat and `station_heading` in the detection line are the installer's note
of the face-N heading; the drone's own course is never known to a level 1
station.

### Keys

The `mac` is derived from the channel, so every station that hears the same
carrier reports the same tracking key and the mapper can intersect their
bearings: `AF:00:` + band letter + channel number + MHz (two bytes) for an
analog carrier, `DF:00:` + the same for a digital link (`'R'` = `52`, channel
4 = `04`, 5769 = `16:89`). A digital link is wider than the channel grid, so two
stations can fold it to neighbouring table channels and different `DF:` keys;
the mapper merges wideband tracks whose centres `fc_mhz` lie within half a
bandwidth plus 5 MHz of each other.

## Layout

```
include/config.h      every tunable: pins, switch table, thresholds, calibration, the antenna model, the build variants
src/main.cpp          sweep, sector measurement, analog gate, video check, wideband confirmation, pull-in, reports, bench console
src/sweep_decide.c    the sweep's decisions: analog order and fold, the mirror test above 5885, pull-in picks,
                      wideband fold, span and ownership by an analog carrier (WB_ANALOG_OWN_MHZ)            (plain C)
src/c5phy_rf.cpp      Wi-Fi PHY receive-only bring-up and tuning (C5VRX port); auto band mode under DUAL_BAND
src/iq_capture.cpp    PARLIO RX, one 16 KiB I/Q window at a time
src/sector_switch.cpp SP4T control lines
src/demod.c           I/Q metrics, FM discriminator, PAL/NTSC line-period search,
                      lag autocorrelations and the bench lag scan (iq_lag_features, iq_lag_scan)  (plain C)
src/bearing.c         amplitude-comparison bearing and its sigma                                   (plain C)
src/report.c          USB and mesh JSON, budgeted byte for byte: analog, wideband
                      (report_wideband_json, report_wb_mac, report_wb_fp), heartbeat               (plain C)
src/fpv_channels.c    the 50-channel plan and its variants, the band of a frequency
                      (fpv_freq_band_ghz, fpv_band_prefix), the bootstrap centres of both bands    (plain C)
tools/station.py      custom_* station options -> defines (identity, position, antennas); the Station setup task
test/host/            gcc tests of the plain-C files with synthetic 4-bit I/Q, run twice
                      (default plan, and -DDUAL_BAND=1 -DLOWBAND=2): make
```

## Bench console (USB, Enter-terminated)

| Command | Effect |
|---|---|
| `?` | status line: mode, held channel, `freq_mhz`, `wifi_ch`, `band` (2 or 5), sector and switch pattern, gain, `bw40`, the capture and error counters, `video_seen`, `wb_seen`, `pullin`, `nf_dbm`, heap, uptime |
| `h R3` / `h 5732` / `h D1` / `h G3` | hold a channel (`G` channels on the dual-band build); prints a `{"info":"bench",...}` line twice a second with `level_db`, `q_phase`, `cv2`, `cfo_khz`, `clip`, `mod`, `noise`, `stuck`, `step_std` |
| `s 0..3` | sector while holding |
| `g 30` / `g a` | fixed gain index / automatic (step down 3 on clipping) |
| `v` | video check on the held channel and sector, all eight windows listed |
| `w` | wideband check on the held channel and sector: the confirmation pass (8 windows) and a coarse lag scan of the last window, about 2 s. Prints `{"info":"wideband","ch":"R4","freq_mhz":5769,"level_db":29.0,"duty":100,"cls":"lte","conf":"high","bw_mhz":10,"fc_mhz":5769.5,"cv2":0.97,"r1":0.85,"r4":0.10,"r128":0.008,"r512":0.007,"r2667":0.043,"scan_lag":2666,"scan_r":0.058}` (numbers from the host test's LTE-like waveform). `scan_lag` is the lag with the largest autocorrelation in 40..3200: 128 on 802.11, 2665..2669 on an LTE-like link on most presses (the CP peak is about three sigma over the scan's own noise on one window). On an FM carrier it prints `dot11`: FM's `r128` is ~0.1, which is why the sweep only classes channels that failed the analog gate |
| `x` | resume scanning |
| `t 100` / `t 1` | while holding: drive the switch control lines with a raw pattern (stage 6 truth table) and keep it until `s` or `x`. Three 0/1 characters in V1V2V3 = D8 D9 D7 order, or a number 0..7 (`0x` hex allowed); anything else is refused. Bench and status lines show it as `"switch":"100"`, `"sector":-1`; `v` and `w` run on it. Refused while scanning |
| `b 0` / `b 1` | analog filter BW20 / BW40 |

`STATUS` or `WATCHDOG_RESET` on a line of its own is answered with a USB
heartbeat (mesh-mapper.py sends it). Anything else prints the help line.
