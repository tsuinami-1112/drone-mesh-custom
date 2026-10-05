# level1-c5phy - Level 1 station v3 firmware (XIAO ESP32-C5)

The XIAO ESP32-C5's own 5 GHz Wi-Fi radio as the 5.8 GHz analog FPV receiver.
Four patch antennas on an SP4T RF switch (optionally through one 20 dB LNA +
band-pass filter) feed the XIAO's U.FL; the firmware holds the PHY
receive-only on each FPV channel, captures raw I/Q from the modem's diagnostic
bus through PARLIO, measures power and FM coherence per sector, checks the
strongest hits for a PAL/NTSC line structure and reports a compass bearing.
Hardware, wiring and the bench procedure: `../docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`.

The receiver bring-up re-implements, on the fleet's Arduino core 3.3 /
ESP-IDF 5.5 toolchain, what [C5VRX](https://github.com/KonradIT/C5VRX) proved on
hardware with ESP-IDF 6.0. **Nothing in this directory has run on hardware
yet**; the bench guide's stages 0-7 are the acceptance path.

## Build and flash

```bash
pio run -e seeed_xiao_esp32c5 -t erase      # every flash starts with a full erase
pio run -e seeed_xiao_esp32c5 -t upload
pio run -e seeed_xiao_esp32c5 -t monitor    # 115200
```

Boot mode if the board will not connect: hold BOOT, tap RESET, release BOOT.

## Pins (XIAO ESP32-C5, GPIO numbers of the Arduino variant)

Everything is on the top-side castellations; no underside pad is used.

| Function | XIAO pin | GPIO | Notes |
|---|---|---|---|
| UART TX to Heltec RX | D4 | 23 | 115200, the same pins as every station tier |
| UART RX from Heltec TX | D5 | 24 | |
| Switch V1 / V2 / V3 | D8 / D9 / D7 | 8 / 9 / 12 | 2 kOhm series; `SECTOR_SWITCH_TABLE` from the stage 6 truth table. Which line states mean N/E/S/W, and which port that is on a PE42442 (N = RF4): [antenna sectors](../README.md#antenna-sectors-how-the-switch-lines-cycle) |
| I/Q lane pads Q7 Q8 Q9 | D0 D1 D2 | 1 0 25 | **must stay unconnected**: each MODEM_DIAG bit is driven out through the pad and read back from it |
| I/Q lane pads I7 I8 I9 | D3 D10 D6 | 7 10 11 | same rule |
| user LED | on board | 27 | blinks on every report |

The default scan plan has 40 channels; four of them (R8, E6, E7, E8 at 5905-5945
MHz) sit above the last public 5 GHz centre and rely on `phy_set_freq` pulling
the synthesizer up to 60 MHz past it, which bench stage 2 proves. A hit there
that merely mirrors a carrier at 5885 is dropped (`alias_drop` in the heartbeat);
`-DC5PHY_MAX_MHZ=5885` removes those channels from the plan.

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

USB, boot:

```json
{"info":"c5phy v3 station ready","node_id":"A1B2","receiver":"c5phy","hw":"v3","channels":40,"sectors":4,"heading":0,"fe_gain_db":0.0,"threshold_dbm":-87.0,"threshold_level_db":8.0,"q_min":40,"peak_pick":1,"video":1,"bw40":1,"gain_max":62,"window_us":409,"iq_lane_bits":3,"mesh_uart":"D4 TX / D5 RX 115200","phy_set_freq":true,"rf":true}
```

`"rf":false` is preceded by `{"info":"error","stage":...,"call":...,"err":...}`
naming the call that failed (a missing undocumented PHY symbol included).

USB, one line per hit per sweep (`rssi` is dBm like every other station tier;
`rssi_raw` is the 10-bit RX5808-style value of the v2 contract; `bearing_deg`
is relative to the box's face N and the mapper rotates it by the station
heading):

```json
{"type":"analog_fm","receiver":"c5phy","hw":"v3","mac":"AF:00:52:03:16:64","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"rssi_dbm":-68.1,"rssi_raw":536,"rssi_min":-70,"rssi_max":-66,"rssi_n":3,"level_db":26.9,"gain":50,"q_phase":71,"cfo_khz":1840,"carrier":"fm","sectors":[-68.1,-74.4,-91.0,-85.2],"sector":0,"bearing_deg":32,"bearing_sigma_deg":15,"station_heading":0,"freq_peak":5734,"video":"NTSC","sync_hz":15736,"field_hz":60,"sync_q":88,"sync_score":91,"video_windows":8,"fp":"NTSC/15736/5734","basic_id":"5.8G-R3-5732MHz","node_id":"RX01","seq":42}
```

Mesh (Serial1 to the Heltec, <= 191 bytes, at most one per emitter per
`MESH_REPORT_INTERVAL_MS`):

```json
{"type":"analog_fm","mac":"AF:00:52:03:16:64","node_id":"RX01","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"bearing_deg":32,"bearing_sigma_deg":15,"video":"NTSC","fp":"NTSC/15736/5734"}
```

Heartbeat every 60 s on USB (120 s on the mesh) with `"heartbeat":true`,
`node_id`, `receiver`, `heading`, `sweeps`, `tune_fail`, `cap_err`, `bus_stuck`,
`alias_drop`, `nf_dbm`, `temp_c`, `uptime_s` (the USB copy adds `usb_drop`,
`mesh_drop` and the thresholds). The mapper registers a station from its first
heartbeat. `NODE_ID` may use letters, digits and `_ - . :`; anything else is
dropped from it, and an empty result falls back to the MAC-derived id. `heading` in the heartbeat and `station_heading` in the detection
line are the installer's note of the face-N heading; the drone's own course
is never known to a level 1 station.

The `mac` is derived from the channel (`AF` = analog FM, band, channel, MHz),
so every station that hears the same carrier reports the same tracking key and
the mapper can intersect their bearings.

## Layout

```
include/config.h      every tunable: pins, switch table, thresholds, calibration
src/main.cpp          sweep, sector measurement, video check, reports, bench console
src/c5phy_rf.cpp      Wi-Fi PHY receive-only bring-up and tuning (C5VRX port)
src/iq_capture.cpp    PARLIO RX, one 16 KiB I/Q window at a time
src/sector_switch.cpp SP4T control lines
src/demod.c           I/Q metrics, FM discriminator, PAL/NTSC line-period search   (plain C)
src/bearing.c         amplitude-comparison bearing and its sigma                   (plain C)
src/report.c          USB and mesh JSON, budgeted byte for byte                    (plain C)
src/fpv_channels.c    40-channel table and the 5 GHz bootstrap centres             (plain C)
test/host/            gcc tests of the plain-C files with synthetic 4-bit I/Q: make
```

## Bench console (USB, Enter-terminated)

| Command | Effect |
|---|---|
| `?` | status line |
| `h R3` / `h 5732` | hold a channel; prints a `{"info":"bench",...}` line twice a second |
| `s 0..3` | sector while holding |
| `g 30` / `g a` | fixed gain index / automatic (step down on clipping) |
| `v` | video check on the held channel and sector, all eight windows listed |
| `t 100` / `t 1` | while holding: drive the switch control lines with a raw pattern (stage 6 truth table) and keep it until `s` or `x`. Three 0/1 characters in V1V2V3 = D8 D9 D7 order, or a number 0..7 (`0x` hex allowed); anything else is refused. Bench and status lines show it as `"switch":"100"`, `"sector":-1`; `v` runs on it. Refused while scanning |
| `b 0` / `b 1` | analog filter BW20 / BW40 |
| `x` | resume scanning |
