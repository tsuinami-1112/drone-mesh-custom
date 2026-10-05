<p align="center">
  <img src="docs/img/level1-rooftop.svg" width="768" alt="Pixel art of a lonely rooftop at night, ringed by walls of lit apartment towers. A tiny Clawd in a black hoodie works at a laptop beside a mast of patch antennas wired to solar panels, with mesh links running to masts on distant roofs, while a hooded figure smokes on the roof's edge. When the laptop's map lights up with red dots, the smoker flicks away his cigarette and ducks into cover as two drones buzz past, their pings flying to the antennas. Then he lights another cigarette and sits back down.">
</p>

<h1 align="center">drone-mesh-custom · level 1</h1>

<p align="center">
  Detection stations for drones that broadcast nothing detectable but their 5.8&nbsp;GHz analog video link.<br>
  A XIAO ESP32-C5 is the receiver, four patch antennas on an RF switch give a compass bearing,<br>
  and two stations' bearings cross into a position on the mapper.
</p>

<p align="center">
  <a href="#hardware">Hardware</a> ·
  <a href="#wiring">Wiring</a> ·
  <a href="#antenna-sectors-how-the-switch-lines-cycle">Antenna sectors</a> ·
  <a href="#software-setup">Software setup</a> ·
  <a href="#station-location-and-heading">Station location</a> ·
  <a href="#flashing">Flashing</a> ·
  <a href="#mesh-home-station-and-mapper">Mesh and mapper</a> ·
  <a href="#bring-up-checklist">Bring-up</a> ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

> [!WARNING]
> **Bench prototype.** The firmware builds and its signal processing passes the
> desktop tests, but none of it has run on hardware yet. The receiver drives the
> C5's Wi-Fi PHY through undocumented calls that
> [C5VRX](https://github.com/KonradIT/C5VRX) proved on ESP-IDF 6.0; this branch
> re-implements them on Arduino core 3.3 / ESP-IDF 5.5. The
> [bring-up checklist](#bring-up-checklist) is the acceptance path.

---

## How it works

```
 4 × 5.8 GHz patch antennas, one per box face (N E S W)
        │  equal-length coax
        ▼
 SP4T RF switch  ◄── V1 V2 V3 ── XIAO D8 D9 D7
        │  RF common
        ▼
 [ LNA + band-pass filter, optional ]
        │  u.FL
        ▼
 XIAO ESP32-C5: Wi-Fi PHY held receive-only → raw I/Q → power, FM coherence,
                PAL/NTSC check, bearing
        │  UART on D4/D5, 115200
        ▼
 Heltec V4 (Meshtastic) ~~ LoRa mesh ~~► home station ──USB──► mesh-mapper.py
```

1. For each of 40 FPV channels the station tunes the C5's 5 GHz radio to the
   exact channel frequency and holds it receive-only.
2. It steps the RF switch through the four patches (N → E → S → W), captures a
   410 µs window of raw I/Q on each, and measures power and FM coherence.
3. A channel is a hit when the strongest patch is ≥ 8 dB above the noise
   reference and ≥ 40 % FM-coherent. The strongest patch and its two neighbours
   give a bearing by amplitude comparison.
4. The strongest hits get a software video check: FM-demodulate and look for
   horizontal sync at the PAL (15 625 Hz) or NTSC (15 734 Hz) line rate.
5. Every hit goes out as JSON over USB, and (rate-limited, ≤ 191 bytes) over the
   Meshtastic mesh. The mapper rotates each bearing by the station's true-north
   heading, draws it as a ray, and intersects rays from two or more stations into
   a position fix.

A station gives a **bearing, never a position**. A position needs at least two
stations that hear the same transmitter.

| Where | What |
|---|---|
| [`level1-c5phy/`](level1-c5phy/) | Station firmware for the Seeed XIAO ESP32-C5 (PlatformIO) and its desktop tests. [Its README](level1-c5phy/README.md) has the full serial contract |
| [`docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`](docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf) | Full BOM, block diagram, power budget and the stage 0–7 bench procedure with record sheets ([HTML](docs/Level1-Station-v3-C5PHY-Bench-Guide.html)) |
| [`level2-main`](../../tree/level2-main) branch | Everything a level 1 station shares with the rest of the network: the mapper (`mesh-mapper.py`, with level 1 bearing support), the home-station firmware (`node-mode-dualcore`, `home_node`), the Heltec V4 Meshtastic setup, the Raspberry Pi installer and a level 1 station simulator. Also the level 2 detectors (Remote ID, DJI DroneID, MAVLink, fingerprints) |

This branch holds only the level 1 station. See
[Mesh, home station and mapper](#mesh-home-station-and-mapper) for what to take
from `level2-main`.

---

## Hardware

Per station. Prices and the full list (enclosure, solar, passives) are in the
[bench guide](docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf), sheet 5.

| Qty | Part | Notes |
|---|---|---|
| 1 | **Seeed XIAO ESP32-C5** | The receiver and MCU. Only its U.FL antenna port carries RF; the stock antenna comes off once the switch goes in |
| 4 | **5.8 GHz patch antenna**, ~8 dBi, ~70° beam, SMA | One per box face. Buy one batch and never mix types: the bearing compares their levels |
| 1 | **SP4T RF switch** covering 5.6–6.0 GHz, 3.3 V control | **PE42442** recommended, see [switch choice](#switch-choice). Start on an evaluation board |
| 4 | u.FL–SMA pigtail, equal length, ≤ 15 cm | Patches to the switch. Equal length keeps the sector losses equal |
| 1–2 | u.FL–u.FL pigtail, ≤ 5 cm | Switch common to the XIAO (two with the LNA) |
| 1 | 5.8 GHz LNA + band-pass filter, ~20 dB (optional) | Between the switch and the XIAO. Fit it if stage 5 shows the station is deafer than an RX5808 station, or if it sits near a 5 GHz access point |
| 1 | **Heltec WiFi LoRa 32 V4** + LoRa antenna | Meshtastic radio. Buy your region's band (863–928 MHz for EU868 / US915 / ...) and the standard OLED model: the TFT model uses GPIO47/48, the two pins the station talks to, for its touchscreen |
| 3 | 2 kΩ resistor | Series resistors on the three switch control lines |
| — | 100 nF ×2, 10 µF, 1000 µF low-ESR | Switch and LNA decoupling, Heltec TX bursts |
| — | Power | 5 V rail, ≈ 1.0 W average per station (≈ 1.3 W with the LNA), but **≈ 0.9 A peaks** while the V4 transmits (750 mA at 27 dBm): the 5 V supply needs **≥ 1.5 A**. The bench guide sizes a 20 W panel and a 50 Wh battery |

For the bench you also want a 5.8 GHz VTX with an NTSC and a PAL camera, and a
step attenuator.

### Switch choice

The firmware drives three control lines. Datasheet figures near 6 GHz:

| | PE42442 (pSemi) | SKY13322-375LF (Skyworks) |
|---|---|---|
| Control | 2 or 3 lines, decoded on chip | **4 lines, one-hot** (V1–V4, exactly one high) |
| Works with the default firmware | Yes, directly | Only with external logic ([below](#skyworks-sky13322-375lf)) |
| Logic levels | VIH 1.17–3.6 V, so 3.3 V GPIO is fine | High 1.8–5 V, low ≤ 0.2 V |
| Supply | VDD 2.3–5.5 V (XIAO 3V3), VSS_EXT to GND | None (control-powered) |
| Insertion loss | 1.9 dB typ at 6 GHz | 2.0 dB typ at 4–6 GHz |
| Isolation, common to an off port | 27 min / 32 typ dB at 6 GHz | 18 dB typ at 4–6 GHz |

Expect about 2 dB of switch loss at 5.8 GHz with either part. The PE42442's
higher isolation also means
less of the strongest patch leaks into the other sectors.

---

## Wiring

### XIAO ESP32-C5 pins

Every pin used is a top-side castellation; nothing is on the underside. Wire by
the **D-labels** printed on the board.

| Function | XIAO pin | C5 GPIO | Goes to | Notes |
|---|---|---|---|---|
| Switch **V1** | **D8** | 8 | switch V1 | via 2 kΩ |
| Switch **V2** | **D9** | 9 | switch V2 | via 2 kΩ |
| Switch **V3** | **D7** | 12 | switch V3 | via 2 kΩ. Stays low with the default table (see below) |
| UART TX | **D4** | 23 | Heltec V4 **GPIO47** (Meshtastic RX) | 115200 8N1 |
| UART RX | **D5** | 24 | Heltec V4 **GPIO48** (Meshtastic TX) | |
| I/Q lanes Q7 Q8 Q9 | D0 D1 D2 | 1 0 25 | **nothing** | must float, see below |
| I/Q lanes I7 I8 I9 | D3 D10 D6 | 7 10 11 | **nothing** | must float, see below |
| 5V | 5V | — | 5 V rail | |
| 3V3 | 3V3 | — | switch VDD (and the LNA if it is a 3.3 V module) | 100 nF at the switch |
| GND | GND | — | single star ground with the Heltec, switch and LNA | |
| U.FL | — | — | switch common (or LNA out) | ≤ 5 cm |

```
                         ┌───── USB-C ─────┐
   (leave open) Q7 ── D0 │●               ●│ 5V  ── 5 V rail
   (leave open) Q8 ── D1 │●               ●│ GND ── star ground
   (leave open) Q9 ── D2 │●     XIAO      ●│ 3V3 ── switch VDD (+100 nF)
   (leave open) I7 ── D3 │●   ESP32-C5    ●│ D10 ── I8 (leave open)
   Heltec 47  ◄────── D4 │●               ●│ D9  ── 2 kΩ ── switch V2
   Heltec 48  ──────► D5 │●               ●│ D8  ── 2 kΩ ── switch V1
   (leave open) I9 ── D6 │●               ●│ D7  ── 2 kΩ ── switch V3
                         └─────────────────┘
```

> [!CAUTION]
> **The six I/Q lane pads (D0, D1, D2, D3, D6, D10) must stay unconnected.** The
> radio's diagnostic bus drives each bit out through its pad and the firmware
> reads it back from the same pad, so any load corrupts the samples: no resistor,
> no probe, no PCB trace, and no breadboard or socket that touches those pins.

> [!IMPORTANT]
> **D4/D5 are not the pins marked TX/RX on the XIAO's pinout card.** The Arduino
> variant's `TX`/`RX` are D6/D7 (GPIO11/12), which this station uses as an I/Q
> lane and switch V3. The Heltec goes on **D4 (TX) and D5 (RX)**, the same two
> pins every station tier in this repo uses (the card labels them SDA/SCL).

### RF chain

```
 Patch N ─┐                                      (optional)
 Patch E ─┤ equal-length coax  ┌──────────────┐   ┌───────────┐
 Patch S ─┼───────────────────►│ RF1..RF4  RFC│──►│ LNA + BPF │──► XIAO U.FL
 Patch W ─┘     ≤ 15 cm each   │     SP4T     │   └───────────┘
                               └──▲───▲───▲───┘   (or RFC straight to the U.FL)
                                 V1  V2  V3
                                 D8  D9  D7   (each through 2 kΩ)
```

Which patch goes on which RF port is **not** simply "N on RF1". It depends on the
switch part and the firmware's sector table. With the PE42442 and the stock
firmware, N goes on RF4. See the [next section](#antenna-sectors-how-the-switch-lines-cycle).

- The LNA sits after the switch, so all four sectors share one gain path and
  the bearing constant is unaffected.
- On a bare PE42442 (not an eval board), tie VSS_EXT (pin 20) to ground so the
  internal negative supply runs, and keep the RF pins at 0 V DC.
- Mount the patches on the four vertical faces at 0/90/180/270°, tilted 10–15°
  up. Point face N at true north if you can, and note the heading you actually
  got either way.

### Heltec and power

| From | To | Notes |
|---|---|---|
| XIAO D4 (TX) | Heltec V4 GPIO**47** | Meshtastic `serial.rxd 47` |
| XIAO D5 (RX) | Heltec V4 GPIO**48** | Meshtastic `serial.txd 48` |
| XIAO GND | Heltec GND | Always connected |
| 5 V rail | XIAO 5V and Heltec 5V | Heltec through its 5V pin **or** USB-C, never both. 1000 µF low-ESR at the Heltec |
| XIAO 3V3 | Switch VDD | 100 nF at the switch |
| 3V3 or 5 V | LNA VCC (optional) | Whichever the module needs; 100 nF + 10 µF at the module |

GPIO47 and GPIO48 sit side by side on the V4 header that carries 5V and Ve.
The Heltec runs stock Meshtastic with the serial module on those pins: TEXTMSG,
115200, `serial.rxd 47`, `serial.txd 48` (full setup on
[`level2-main`](../../tree/level2-main#set-up-the-heltec-v4-meshtastic)).
Fit the LoRa antenna before the Heltec is powered: the V4 transmits at up to
28 dBm. It draws about 75 mA receiving and 750 mA while transmitting, so the
5 V rail has to deliver ≈ 0.9 A peaks for the whole station (≈ 1.0 A with the
LNA). A charger with a 1 A output is marginal; use one rated 1.5 A or more.

Before plugging USB into an installed station's XIAO, take its 5V pin off the
rail (or switch the rail off) so the USB port and the rail don't feed each other.

---

## Antenna sectors: how the switch lines cycle

This section decides whether bearings come out right, so here it is in full.

**The firmware has no idea where north is.** It knows four sector indices, 0–3,
named `N`, `E`, `S`, `W`, and for each one a bit pattern that it drives onto D8,
D9 and D7. Whatever patch the switch connects for **sector 0's pattern is "N"** to
the station. Every `bearing_deg` it reports is measured clockwise from that
patch's boresight (face N). True north only comes in through the heading you
give the mapper.

All of this is in [`include/config.h`](level1-c5phy/include/config.h):

```c
#define SWITCH_PINS          { 8, 9, 12 }                      // bit 0 = GPIO8 = D8 (V1), bit 1 = GPIO9 = D9 (V2), bit 2 = GPIO12 = D7 (V3)
#define SECTOR_SWITCH_TABLE  { 0x0, 0x1, 0x2, 0x3 }            // pattern for sector 0 N, 1 E, 2 S, 3 W
#define SECTOR_AZIMUTH_DEG   { 0.0f, 90.0f, 180.0f, 270.0f }   // sector axes, clockwise from face N
```

### Cycle order and timing

For every channel, on every sweep, the station does this:

```
tune channel ─ 8 ms ─► sector 0 N ─► sector 1 E ─► sector 2 S ─► sector 3 W ─► next channel
                       │
                       └─ drive D8/D9/D7 to the sector's pattern, wait 200 µs, capture 1 window
                          (quiet channel) or up to 3 (0.4 ms each, plus retakes if the gain steps down)
```

- That is four switch changes per channel and 160 per sweep. A 40-channel sweep
  takes about 2 s, and sweeps repeat back to back.
- After each sweep, the two strongest hits get a video check: the station
  retunes to that channel, parks the switch on the hit's **strongest** sector,
  and takes 8 windows 5 ms apart.
- At boot all three lines go low, then sector 0 (N) is selected.
- While a channel is held on the bench console (`h`), `s 0`–`s 3` parks the
  switch on one sector and re-asserts it with every bench line (twice a second),
  and `t 100` etc. puts a raw pattern on the lines that stays until `s` or `x`.
  Every bench and status line shows what is on the lines as `"switch":"100"`.

### Line states for each sector (default table)

The table value is a bit field: bit 0 is D8, bit 1 is D9, bit 2 is D7.

| Sector | Index | Axis (from face N) | Table value | D8 · V1 | D9 · V2 | D7 · V3 | Written V1V2V3 |
|---|---|---|---|---|---|---|---|
| **N** | 0 | 0° | `0x0` | LOW | LOW | LOW | `000` |
| **E** | 1 | 90° | `0x1` | **HIGH** | LOW | LOW | `100` |
| **S** | 2 | 180° | `0x2` | LOW | **HIGH** | LOW | `010` |
| **W** | 3 | 270° | `0x3` | **HIGH** | **HIGH** | LOW | `110` |

Mind the notation. `config.h` and the bench guide write patterns V1 first
(`000 100 010 110`), which puts bit 0 on the **left**: the reverse of how the hex
value reads in binary. `0x1` is binary `001` but is written `100` in V1V2V3
order. Both mean "D8 high, the rest low".

With the default table **D7 (V3) never goes high**. It is spare on a 2-line part.

### What that selects on a PE42442

From the PE42442 datasheet, Tables 5 and 6:

| V3 | V2 | V1 | Path |
|---|---|---|---|
| 0 | 0 | 1 | RFC–RF1 |
| 0 | 1 | 0 | RFC–RF2 |
| 0 | 1 | 1 | RFC–RF3 |
| 0 or 1 | 0 | 0 | RFC–RF4 |
| 1 | 0 | 1 | all off |
| 1 | 1 | 0 | all off |
| 1 | 1 | 1 | all off |

All lines low is **RF4**, not RF1. So with the stock firmware:

| Sector the station reports | Lines (D8 D9 D7) | PE42442 port | **Cable to that port** |
|---|---|---|---|
| N (0) | L L L | RF4 | the patch on face **N** |
| E (1) | H L L | RF1 | the patch on face **E** |
| S (2) | L H L | RF2 | the patch on face **S** |
| W (3) | H H L | RF3 | the patch on face **W** |

This fills in the bench guide's stage 6 truth table for the PE42442
(`000 → RF4, 100 → RF1, 010 → RF2, 110 → RF3`). Confirm it on the bench as
described [below](#checking-the-mapping-on-the-bench).

D7 can go to V3 (3-pin control), or you can ground V3 and leave D7 unconnected
(2-pin control). The default table keeps V3 low, so both behave the same.

**If you'd rather cable N to RF1**, build with the table rotated one step:

```ini
build_flags =
    ...
    -DSECTOR_SWITCH_TABLE='{0x1,0x2,0x3,0x0}'   ; N=RF1 E=RF2 S=RF3 W=RF4 on a PE42442
```

Recommendation: keep the stock table, cable N → RF4, E → RF1, S → RF2,
W → RF3, and label each pigtail. If a station in a fleet ends up cabled
RF1 = N but built without the flag, each patch carries the name of the face one
step clockwise of it, and **every bearing that station reports is 90° too far
clockwise**. Nothing in the output flags that, so one convention everywhere is
safer.

### Skyworks SKY13322-375LF

This part has four control lines and wants exactly one of them high (J1 = V1
only, J2 = V2 only, J3 = V3 only, J4 = V4 only; the datasheet calls any other
state undefined). Three GPIOs can't drive that directly. One way that keeps the
firmware as it is: D8 → V1, D9 → V2, D7 → V3, and a 3-input NOR of the same
three lines (e.g. a 74LVC1G27 powered from 3V3) → V4. Then build with:

```ini
    -DSECTOR_SWITCH_TABLE='{0x1,0x2,0x4,0x0}'   ; N=J1 (V1) E=J2 (V2) S=J3 (V3) W=J4 (all low, NOR high)
```

### Any other switch

Look up its truth table and fill in `SECTOR_SWITCH_TABLE` so that:

1. **The four entries go round the box clockwise** (seen from above): N, E, S, W.
   The bearing takes sector `k+1` as the clockwise neighbour and `k−1` as the
   counter-clockwise one (`bearing = az[k] + K·(P[k+1] − P[k−1])`). If E and W
   are swapped, a transmitter just east of north reads just west of north.
2. Every entry selects exactly one valid path. Bit 0 → D8, bit 1 → D9, bit 2 → D7.
3. If your faces aren't at 0/90/180/270°, set `SECTOR_AZIMUTH_DEG` to match.

The `sectors` array in every detection line is always in index order:
`[N, E, S, W]`.

### Checking the mapping on the bench

This is bench stage 6. `t` maps the switch itself, whatever the firmware's
table says, and `s` then confirms the table.

1. Switch (eval board) common → XIAO U.FL, one patch on **one** RF port, the
   others terminated or open. Control lines from D8/D9/D7 through 2 kΩ.
2. Key a VTX a few metres away, say on A1 (5865 MHz). On the console:
   `h A1`.
3. **Truth table:** type `t 000`, `t 100`, `t 010`, `t 110` (V1V2V3 order, D8
   first), waiting for a couple of bench lines each. Each pattern stays on the
   lines until you send another, `s` or `x`, and the bench lines show it as
   `"switch":"100"` with `"sector":-1`. The pattern whose `level_db` jumps by
   tens of dB selects the port the patch is on. Write it down, move the patch
   to the next port, repeat. On a PE42442 expect `000` → RF4, `100` → RF1,
   `010` → RF2, `110` → RF3.
4. **Sector table:** with the patches cabled as planned, `s 0` … `s 3` should
   light up the N, E, S, W patch in turn. The reply echoes the pattern each
   sector drives (`"pattern":"100"`).
5. With all four patches on the box: `x` to resume scanning, and walk the VTX
   round the box clockwise. The detection lines' `"sector"` should go
   0 → 1 → 2 → 3 and `bearing_deg` should climb with it.

> [!NOTE]
> `t` takes the pattern as three 0/1 characters in pin order (`t 100` = D8 high,
> `t 001` = D7 high), or a number 0–7 (`t 1` = D8, `t 2` = D9, `t 4` = D7;
> `t 0x3` works too). Anything else, such as `t 8` or `t 07`, is refused rather
> than cut down to three bits. It needs a held channel: while the station is
> scanning it answers with an error, because the sweep re-selects every sector.

---

## Software setup

### 1. Install the tools (once)

- [VS Code](https://code.visualstudio.com/) with the **PlatformIO IDE** extension,
  or the PlatformIO CLI on its own: `pip install platformio`.
- [Git](https://git-scm.com/downloads).
- Linux only: USB serial access, then log out and back in.
  ```bash
  sudo apt install python3-venv
  curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules \
    | sudo tee /etc/udev/rules.d/99-platformio-udev.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  sudo usermod -a -G dialout $USER
  ```

### 2. Get the code

```bash
git clone -b level1 https://github.com/tsuinami-1112/drone-mesh-custom
cd drone-mesh-custom/level1-c5phy
```

In VS Code, **File → Open Folder…** and open `level1-c5phy` itself (PlatformIO
only activates in a folder with a `platformio.ini`). The first open downloads the
pioarduino ESP32 platform and toolchain, several hundred MB; let it finish.

### 3. Settings

**Per station:** the node id, position and heading. Each station gets its own
environment in `stations.ini`, written by the Station setup task; see
[Station location and heading](#station-location-and-heading). There's nothing
to edit for them here.

**Shared by every station:** everything else is in
[`include/config.h`](level1-c5phy/include/config.h) and can be overridden in
`platformio.ini`'s `build_flags`. The station environments inherit those flags.

```ini
build_flags =
    -std=gnu++17
    -DCORE_DEBUG_LEVEL=0
    -DRF_COUNTRY_CC='"US"'          ; regulatory table used for tuning: the deployment country
    ; -DSECTOR_SWITCH_TABLE='{0x0,0x1,0x2,0x3}'   ; only if your switch or cabling needs it (see above)
```

| Setting | Default | What it does |
|---|---|---|
| `custom_node_id` (stations.ini) | MAC-derived (`A1B2`) | Becomes `NODE_ID`: the station's key in the mapper and in every report |
| `custom_station_lat`, `custom_station_lon` (stations.ini) | none | Become `STATION_LAT`/`STATION_LON`: sent in the heartbeat, so every mapper places the station |
| `custom_station_heading` (stations.ini) | `0` | Becomes `STATION_HEADING_DEG`: true-north heading of face N. Sent in the heartbeat, **not** applied to `bearing_deg`; the mapper rotates the bearings by it |
| `RF_COUNTRY_CC` | `"US"` | If the heartbeat shows `tune_fail` > 0, check this first |
| `SECTOR_SWITCH_TABLE` | `{0x0,0x1,0x2,0x3}` | See [Antenna sectors](#antenna-sectors-how-the-switch-lines-cycle) |
| `RF_FRONTEND_GAIN_DB` | `0` | Leave at 0 and calibrate with the LNA in place. Set 20 only to carry a calibration taken without the LNA over to a station that has one |
| `RSSI_CAL_*`, `BEARING_K_DEG_PER_DB`, `DETECT_LEVEL_DB`, `RF_NOISE_POWER` | uncalibrated | From bench stages 1, 5 and 6 |
| `C5PHY_MAX_MHZ` | `5945` | `5885` drops R8/E6/E7/E8 if stage 2 shows the synthesizer can't reach them |

---

## Station location and heading

A station only measures a bearing relative to its own face N. To draw that
bearing on the map and cross it with other stations' bearings, the mapper needs
two things for every station:

| What | Why | Example |
|---|---|---|
| **Position** | Where the station's bearing ray starts | `33.494200, -111.926100` |
| **Heading of face N** | Turns "32° from face N" into a compass bearing. True north, degrees clockwise | `15` |

The heading matters more than the position. A position 20 m off moves a ray by
at most 20 m, but a heading 5° off swings it by about 87 m at 1 km and 175 m at
2 km.

### Give every station a NODE_ID

The `NODE_ID` is the station's name in every report, and the key every mapper
stores its position against. Pick a short one (`RX01`, `NORTH2`: letters, digits,
`_` and `-`, up to 23 characters) and write it on the box. Short matters,
because it rides in every 191-byte mesh line.

Without one, the firmware uses 4 hex digits of the XIAO's MAC address. Avoid that
for a fleet, for two reasons:

- swapping the XIAO gives the station a new id, so it shows up as a new,
  unplaced station;
- two boards can end up with the same id (about 2 % odds across 50 stations).

### Recommended: flash it with Station setup

Flash the position and heading into the station, and every mapper that hears it
places it by itself. Nothing has to be entered on any mapper.

1. **Open Station setup.** In VS Code: PlatformIO sidebar → **PROJECT TASKS →
   seeed_xiao_esp32c5 → Custom → Station setup (map)**. From a terminal:
   `pio run -e seeed_xiao_esp32c5 -t station_setup`. A page with a map opens in
   your browser; if it doesn't, the terminal prints its address.
2. **Enter the node id,** or pick an existing station from the list to change it.
3. **Set the position.** Use one of:
   - click where the station stands on the map (drag the pin to adjust);
   - paste coordinates, e.g. copied from Google Maps;
   - **Use my location** while standing at the station.
4. **Set the heading.** Switch to **Face N direction** and click a point that the
   N patch faces. The **Satellite** layer (top right) helps line it up with a road
   or roof edge. Or type the heading.
5. **Save.** The station is written to `level1-c5phy/stations.ini` as its own
   build environment, e.g. `[env:RX01]`, and the task ends.
6. **Flash that station.** Refresh PROJECT TASKS (the ↻ button at the top of the
   PlatformIO sidebar, or reload the window); `RX01` is now its own entry. Run
   **RX01 → Platform → Erase Flash**, then **RX01 → General → Upload**. From a
   terminal: `pio run -e RX01 -t erase && pio run -e RX01 -t upload`.
7. **Check the boot line** in the serial monitor:
   `{"info":"c5phy v3 station ready","node_id":"RX01",…,"heading":15,"lat":33.494200,"lon":-111.926100,…}`.

The station now sends its position in its heartbeat: on every USB heartbeat, and
over the mesh on the first three after boot, then every 10 minutes (the 191-byte
mesh line has no room for it every time). A mapper that starts later picks it up
within 10 minutes. In the LEVEL 1 STATIONS panel the station appears placed, with
**auto** next to its position and heading. This needs the current mapper from
`level2-main`.

About `stations.ini`:

- It holds one environment per station. Station setup writes it; you can also
  edit it by hand. [`stations.example.ini`](level1-c5phy/stations.example.ini)
  shows the format.
- The values are checked at build time. A wrong one stops the build with a
  plain message: a lone latitude, 95° north, a space in the node id.
- It records where your stations are, so it is **not committed** (it's in
  `.gitignore`). Keep your own backup, or share it privately with whoever
  flashes stations.

### Getting good numbers

- **Position:** a click on the satellite layer, the location of a phone or laptop
  at the station (the page shows its accuracy), or a GPS reading. A few metres is
  plenty.
- **Heading from the map:** click a point straight out from face N, lining it up
  with something visible on the satellite layer.
- **Heading from a compass:**
  - stand behind the box, sight along the axis of the N patch, and read the
    bearing, away from metal and the solar panel;
  - a compass reads *magnetic* north, so add your local magnetic declination
    (east is positive). For example, compass 5° + declination 10° E = heading
    15°. NOAA's [declination calculator](https://www.ngdc.noaa.gov/geomag/calculators/magcalc.shtml)
    gives it for any place.
- **Check it:** put a VTX at a known spot and see that the station's ray passes
  through it. If it misses by a constant angle, correct the heading by that
  angle.

### Without flashing: the mapper panel

For a station flashed without a location, or for a quick test, set it in the
mapper's **LEVEL 1 STATIONS** panel:

- type the latitude and longitude, or press **PLACE** and click the map, or
  **HERE** (this browser's location), then **SAVE**;
- type the heading in the same row.

This is stored only in that mapper's `stations.json`. With several mappers,
repeat it on each one, or copy `stations.json` between them (a mapper reads it
when it starts).

### Which value a mapper uses

| Situation | Position the mapper uses |
|---|---|
| Station flashed with a position, nothing saved in this mapper | The flashed one, marked **auto** |
| A position saved by hand in this mapper | The hand-set one, even after the station is reflashed |
| Both position fields cleared in the panel, then **SAVE** | Back to the flashed one |
| Not flashed and not set | None: the station's bearings are not drawn or used |

The heading works the same way, except that clearing it doesn't bring the
flashed one back. To return a station fully to its flashed values, press **DEL**
in the panel; it registers again from its next heartbeat.

### Moving or replacing a station

- **Moved:**
  1. Run Station setup, pick the station, move the pin (and the heading),
     Save, then reflash it.
  2. Mappers follow by themselves, unless someone set its position by hand on a
     mapper. Clear it there.
- **Replacing the XIAO:** flash the new board from the same environment. It
  comes up with the same `NODE_ID`, position and heading, and the mappers
  notice nothing.

---

## Flashing

There is no prebuilt binary or web flasher for level 1. Build from source.

**Every flash starts with a full erase.** Stale PHY calibration data in flash left
C5VRX's receiver deaf after reflashing; the erase clears it.

From the `level1-c5phy` folder:

```bash
pio run -e seeed_xiao_esp32c5 -t erase      # 1. full chip erase
pio run -e seeed_xiao_esp32c5 -t upload     # 2. build and flash
pio run -e seeed_xiao_esp32c5 -t monitor    # 3. serial console, 115200
```

In VS Code: PlatformIO sidebar → **PROJECT TASKS → seeed_xiao_esp32c5** →
**Platform → Erase Flash**, then **General → Upload**, then **General → Monitor**.

`seeed_xiao_esp32c5` is the generic build, with no node id or location: use it on
the bench. For a station you deploy, run the same steps under its own
environment (e.g. **RX01**, or `pio run -e RX01 -t erase` …), created by
[Station setup](#station-location-and-heading).

- Use a USB-C **data** cable. A charge-only cable never shows a port.
- If the board won't connect: hold **BOOT**, tap **RESET**, release **BOOT**, and
  run the task again. Press RESET when the upload finishes.
- With several boards plugged in, unplug the others or add
  `upload_port = /dev/ttyACM0` (`COM5`, `/dev/cu.usbmodem101`, …) to the
  environment.
- Close the monitor before starting the mapper: only one program can hold the port.

On a good boot the first line is:

```json
{"info":"c5phy v3 station ready","node_id":"RX01","receiver":"c5phy","hw":"v3","channels":40,"sectors":4,"heading":15,"lat":33.494200,"lon":-111.926100,...,"phy_set_freq":true,"rf":true}
```

(`lat`/`lon` appear only on a station flashed with its position.)

`"rf":true` means the PHY is held receive-only and the I/Q reader is running.
`"rf":false` comes after an `{"info":"error","stage":...,"call":...,"err":...}`
line naming the call that failed. A heartbeat follows about 10 s after boot,
then every 60 s.

### Desktop tests

The signal processing (`demod.c`, `bearing.c`, `report.c`, `fpv_channels.c`) is
plain C and is tested on a PC with synthetic I/Q. It needs `gcc`, `make` and
`python3`:

```bash
cd level1-c5phy/test/host && make           # ends with "ALL TESTS PASSED" and "check_json: ... OK"
```

---

## Mesh, home station and mapper

The mesh radios, the home station and the mapper are shared with the level 2
stations, so they live on [`level2-main`](../../tree/level2-main) and are built and set up from
there.

```
 level 1 station ─UART─► Heltec V4 ~~ LoRa mesh ~~► Heltec V4 ─UART─► home station XIAO ─USB─► mesh-mapper.py
 (this branch)                                                        (level2-main, home_node)   (level2-main)

 on the bench:   level 1 station XIAO ─USB──────────────────────────────────────────────────► mesh-mapper.py
```

| Part | On `level2-main` | Level 1 notes |
|---|---|---|
| Meshtastic on every Heltec V4, field and home | [Set up the Heltec V4 (Meshtastic)](../../tree/level2-main#set-up-the-heltec-v4-meshtastic) | The same settings as a level 2 station: TEXTMSG, 115200, RX 47 / TX 48, power saving off, your own primary channel. Name each station's node after its `NODE_ID` (`meshtastic --set-owner RX01`) |
| Home station | [Build a station](../../tree/level2-main#build-a-station) and [Build and flash the firmware](../../tree/level2-main#build-and-flash-the-firmware): `node-mode-dualcore`, environment `home_node` | Use the current `level2-main` build. It passes `"type":"analog_fm"` lines straight through; older home-node builds' duplicate filter drops a second station's report of the same emitter, which is exactly the report a position fix needs |
| Mapper | [Quick Start](../../tree/level2-main#quick-start): `mesh-mapper.py`, also the Raspberry Pi installer | Has the level 1 support: the LEVEL 1 STATIONS panel, bearing rays, multi-station position fixes |
| Simulator | [`mapper_test/level1_bearing_sim.py`](../../blob/level2-main/mapper_test/level1_bearing_sim.py) | Two or three simulated level 1 stations and one drone, for trying the mapper without hardware |

Over the mesh the station sends each emitter at most once per 8 s (the first
report of a new emitter goes at once) and a heartbeat every 120 s.

### Commissioning a station in the mapper

Open the mapper (`http://localhost:5000`) and pick the serial port: the home
station's XIAO, or on the bench a level 1 station's XIAO directly. Then:

1. Each station registers itself from its first heartbeat and appears in the
   **LEVEL 1 STATIONS** panel, under its `NODE_ID`.
2. A station flashed with its location appears placed, marked **auto**. For any
   other station, set its position and heading in the panel. Both are covered in
   [Station location and heading](#station-location-and-heading).
3. Bearings show as rays from the station with a ±σ wedge. When two or more
   placed stations report the same emitter within 30 s and their rays cross at
   more than 8°, the mapper puts a position fix with an error circle where they
   meet.

A wrong heading rotates every ray from that station, so check it with a VTX at a
known spot before trusting fixes.

---

## Bring-up checklist

Condensed from the bench guide, which has the record sheets. Stages 0–5 run on a
bare XIAO with its stock antenna; the switch comes in at stage 6. Don't move on
until a stage passes.

| Stage | Do | Pass |
|---|---|---|
| 0 Flash and boot | Erase, upload, monitor. `?` twice, 60 s apart | `"rf":true`; `captures` climbing, `cap_err` 0 |
| 1 Receiver alive | No VTX: `h A1`. Then key a VTX on A1 a few metres away | Quiet: `level_db` ≈ 0 ± 2, `p_mean` ≈ 2, `q_phase` < 15, `stuck` 0. Keyed: `level_db` up ≥ 30 dB, `q_phase` ≥ 50, `cfo_khz` within ±2000 |
| 2 Channel coverage | `x`, wait for a heartbeat. Then `h E4` and `h E8` | `tune_fail` 0, `channels` 40; E8 hears a VTX on E8 but not one on E5 |
| 3 Selectivity | VTX on R3, scanning. Then hold the channel nearest a live 5 GHz AP | One R3 report (B1/F1 folded in), nothing > 40 MHz away; the AP raises `level_db` but `q_phase` stays < 40 |
| 4 Video | NTSC camera: hold its channel, `v`. Then PAL. Then camera unplugged | ≥ 3/8 windows read `NTSC` 15 734 Hz / `PAL` 15 625 Hz; unplugged gives `present:0` |
| 5 Sensitivity | VTX through a step attenuator; record `level_db` against input; compare with an RX5808 station | ~1 dB per dB over ~60 dB; set the `RSSI_CAL_*` constants and `DETECT_LEVEL_DB` |
| 6 Switch and pattern | [Map the sectors](#checking-the-mapping-on-the-bench), mount the patches, VTX at 30 m, rotate the box in 15° steps | Each `s n` follows its patch; derive `BEARING_K_DEG_PER_DB` (default 3.0) |
| 7 Field | Two stations 300–500 m apart, positions and headings set; walk a VTX over 10 marked points; 72 h on solar | The 90 % circle contains the true position on ≥ 9/10; heartbeat gap never > 5 min |

### Bench console

Type into the serial monitor, Enter-terminated.

| Command | Effect |
|---|---|
| `?` | Status line |
| `h R3` / `h 5732` | Hold a channel; prints an `{"info":"bench",...}` line twice a second |
| `s 0` … `s 3` | Park the switch on sector N / E / S / W (while holding) |
| `g 30` / `g a` | Fixed gain index (2–62) / automatic |
| `v` | Video check on the held channel and sector, all eight windows listed |
| `t 100` / `t 1` | Put a raw pattern on the switch lines while holding (V1V2V3 = D8 D9 D7, or a number 0–7); stays until `s` or `x`, see [the bench check](#checking-the-mapping-on-the-bench) |
| `b 0` / `b 1` | Analog filter BW20 (+3 dB SNR) / BW40 (full video) |
| `x` | Resume scanning |

---

## Serial output

One JSON object per line on USB at 115200. Abbreviated:

```json
{"type":"analog_fm","mac":"AF:00:52:03:16:64","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"sectors":[-68.1,-74.4,-91.0,-85.2],"sector":0,"bearing_deg":32,"bearing_sigma_deg":15,"video":"NTSC","fp":"NTSC/15736/5734","node_id":"RX01","seq":42,...}
{"heartbeat":true,"node_id":"RX01","receiver":"c5phy","heading":0,"sweeps":1830,"tune_fail":0,"cap_err":0,"bus_stuck":0,"nf_dbm":-98,...}
```

- `mac` is derived from the channel (`AF` = analog FM, band, channel, MHz), so
  every station hearing the same carrier reports the same key.
- `bearing_deg` is relative to face N; `sectors` is in `[N, E, S, W]` order;
  `sector` is the strongest one.
- The mesh copy is cut down to ≤ 191 bytes.

The full contract (every field, the mesh line, the heartbeat) is in
[`level1-c5phy/README.md`](level1-c5phy/README.md#serial-contract).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Upload can't find the board | Charge-only cable; use BOOT + RESET; close any open monitor |
| `"rf":false` at boot | The `{"info":"error"}` line before it names the call. A missing undocumented PHY symbol means a platform/libphy mismatch; `-DC5PHY_STRONG_PHY_SYMBOLS=1` turns that into a link error |
| Receiver deaf after a reflash | Flashed without the erase. Erase, then upload |
| `stuck` 1, `bus_stuck` climbing | Something touches an I/Q lane pad (D0 D1 D2 D3 D6 D10), or the diagnostic bus isn't streaming. Trust the flag, not `p_mean` |
| `level_db` rises but `q_phase` doesn't | Off-channel carrier (check `cfo_khz`), or a lane-order problem |
| `tune_fail` > 0 | `RF_COUNTRY_CC` doesn't allow those channels; set the deployment country, erase, reflash |
| Hits on R8/E6/E7/E8 that mirror E5 | The synthesizer doesn't reach above 5885 MHz (`alias_drop` counts the mirrors it caught). Build with `-DC5PHY_MAX_MHZ=5885` |
| Bearings off by a constant 90°/180°/270° | Sector table and cabling don't match (see [Antenna sectors](#antenna-sectors-how-the-switch-lines-cycle)), or the heading in the mapper is wrong |
| A VTX moving clockwise reads counter-clockwise | E and W cables swapped |
| No reports over the mesh | Heltec serial settings (pins, TEXTMSG, 115200), power saving on, D4/D5 crossed the wrong way, or no common ground |
| Station never appears in the mapper | Home station or mapper older than the current `level2-main`, or no heartbeat reaching the mapper |
| Reports arrive but no position fix | Station positions not set, only one station hears it, or the rays are within 8° of parallel |
| A flashed station shows "position not set" | The mapper is older than the current `level2-main`; the station was flashed from `seeed_xiao_esp32c5` rather than its own environment (check the boot line for `lat`); or, over the mesh only, wait up to 10 min for a heartbeat that carries the position |
| A mapper ignores a station's new position after reflashing | Its position was saved by hand on that mapper. Clear both position fields and SAVE (see [which value wins](#which-value-a-mapper-uses)) |
| Station setup shows no map | No internet for the map tiles: type or paste the coordinates and the heading; everything else works |
| A new station's environment isn't in PROJECT TASKS | Refresh PROJECT TASKS (↻ at the top of the PlatformIO sidebar) or reload the window |
| Build stops with `station settings: …` | A value in `stations.ini` is wrong; the message names it |

---

## Repository layout

```
level1-c5phy/                       Level 1 station firmware (PlatformIO, env seeed_xiao_esp32c5)
  platformio.ini                    the generic build, shared flags (country, calibration)
  stations.example.ini              format of stations.ini: one environment per station (stations.ini itself is not committed)
  tools/station.py                  custom_* station options -> defines; the "Station setup (map)" task
  tools/station_setup.html          the map page Station setup opens
  include/config.h                  every tunable: pins, switch table, thresholds, calibration
  src/main.cpp                      sweep, sector measurement, video check, reports, bench console
  src/sector_switch.cpp             drives the SP4T control lines from SECTOR_SWITCH_TABLE
  src/c5phy_rf.cpp                  Wi-Fi PHY receive-only bring-up and tuning (C5VRX port)
  src/iq_capture.cpp                PARLIO RX, one 16 KiB I/Q window at a time
  src/demod.c, bearing.c            I/Q metrics, FM discriminator, PAL/NTSC search; bearing and sigma
  src/report.c, fpv_channels.c      USB and mesh JSON; the 40-channel table
  test/host/                        desktop tests: make
docs/Level1-Station-v3-C5PHY-Bench-Guide.{pdf,html}   hardware, BOM, power, bench stages 0-7
docs/img/                           README header art and the script that draws it; retired art in archive/
```

That is the whole branch. The mapper, the home-station firmware, the Raspberry
Pi installer and the level 2 detectors are on
[`level2-main`](../../tree/level2-main).
