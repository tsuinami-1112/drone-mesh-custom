<p align="center">
  <img src="docs/img/level1-rooftop.svg" width="768" alt="Pixel art of a lonely rooftop at night, ringed by walls of lit apartment towers with a green Meshtastic neon sign. A tiny Clawd in a black hoodie works at a laptop beside a mast of patch antennas wired to solar panels, with mesh links running to masts on distant roofs, while a hooded figure smokes on the roof's edge. When the laptop's map lights up with red dots, the smoker flicks away his cigarette and ducks into cover as two drones sweep searchlights across the rooftops, their pings flying to the antennas. Then he lights another cigarette and sits back down.">
</p>

<h1 align="center">drone-sentinel · level 1</h1>

<p align="center">
  Detection stations for drones that broadcast nothing detectable but their video link:<br>
  5.8&nbsp;GHz analog FM, or a digital link (DJI O3/O4, Walksnail, HDZero, OpenIPC-style) at 5.8&nbsp;GHz<br>
  and, with the dual-band build, at 2.4&nbsp;GHz.<br>
  A XIAO ESP32-C5 is the receiver, four patch antennas on an RF switch give a compass bearing,<br>
  and two stations' bearings cross into a position on the mapper.
</p>

<p align="center">
  <a href="#hardware">Hardware</a> ·
  <a href="#wiring">Wiring</a> ·
  <a href="#antenna-sectors-how-the-switch-lines-cycle">Antenna sectors</a> ·
  <a href="#software-setup">Software setup</a> ·
  <a href="#station-setup-location-heading-and-antennas">Station setup</a> ·
  <a href="#flashing">Flashing</a> ·
  <a href="#mesh-home-station-and-mapper">Mesh and mapper</a> ·
  <a href="#bring-up-checklist">Bring-up</a> ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

> [!WARNING]
> **Bench prototype.** The firmware builds (both variants, on every push) and
> its signal processing passes the desktop tests, but none of it has run on
> hardware yet. The receiver drives the C5's Wi-Fi PHY through undocumented
> calls that [C5VRX](https://github.com/KonradIT/C5VRX) proved on ESP-IDF 6.0;
> this branch re-implements them on Arduino core 3.3 / ESP-IDF 5.5. The
> [bring-up checklist](#bring-up-checklist) is the acceptance path.

---

## How it works

<details>
<summary>Expand</summary>

```
 4 × directional patch antennas, one per box face (N E S W)
   5.8 GHz patches, or dual-band 2.4 + 5.8 GHz patches (dual-band build)
        │  equal-length coax
        ▼
 SP4T RF switch  ◄── V1 V2 V3 ── XIAO D8 D9 D7
        │  RF common
        ▼
 [ LNA + band-pass filter, optional, single-band only ]
        │  u.FL
        ▼
 XIAO ESP32-C5: Wi-Fi PHY held receive-only → raw I/Q → power, FM coherence,
                envelope, symbol-period autocorrelations, PAL/NTSC check, bearing
        │  UART on D4/D5, 115200
        ▼
 Heltec V4 (Meshtastic) ~~ LoRa mesh ~~► home station ──USB──► mesh-mapper.py
```

1. For each of the 50 channels of the scan plan the station tunes the C5's
   radio to the exact frequency and holds it receive-only. The plan is the 40
   analog FPV channels (bands R, A, B, E, F), the two gap points X1 5675 and
   X2 5715 MHz, D1–D3 at 5190/5210/5230 MHz (DJI O4's CE band) and Lowband
   L4–L8 at 5473–5621 MHz. The dual-band build adds G1–G5 at 2402–2482 MHz,
   55 channels.
2. It steps the RF switch through the four patches (N → E → S → W), captures a
   410 µs window of raw I/Q on each (up to three once the first comes within
   3 dB of the threshold), and measures power, FM coherence and the envelope's
   variance (`cv2`).
3. **Analog gate.** A channel is an analog hit when the strongest patch is
   ≥ 8 dB above the noise reference, ≥ 40 % FM-coherent and has a constant
   envelope (`cv2` ≤ 0.5: FM video reads 0.02–0.3, a digital link about 1). The
   strongest patch and its two neighbours give a bearing by amplitude
   comparison. A strong constant-envelope carrier sitting ≥ 3 MHz off a table
   channel (a VTX between channels) gets one retune onto its centroid and a
   second measurement there (pull-in, two per sweep).
4. **Digital path.** A channel whose strongest patch stays ≥ 8 dB above the
   noise reference on all three windows, within 6 dB of each other, with a
   noise-like envelope (`cv2` 0.5–1.5) but fails the analog gate is a wideband
   candidate. After the sweep the two strongest get a confirmation pass of 8
   windows 5 ms apart. Lag autocorrelations of the samples name the system:
   `lte` (66.7 µs symbols: DJI OcuSync, O3, O4), `dot11` (3.2 µs symbols:
   Wi-Fi-based links such as OpenIPC/wfb-ng) or `wb` (neither), with a
   bandwidth bucket (10/20/30/40 MHz), the centre frequency and the duty
   cycle. A link on for ≥ 75 % of the windows goes out as `"type":"wideband"`
   with a bearing from one window per patch in the order N E S W W S E N.
5. The strongest analog hits get a software video check: FM-demodulate and look
   for horizontal sync at the PAL (15 625 Hz) or NTSC (15 734 Hz) line rate.
6. Every report, analog or wideband, goes out as JSON over USB, and
   (rate-limited, ≤ 191 bytes) over the Meshtastic mesh. The mapper rotates each
   bearing by the station's true-north heading, draws it as a ray, and
   intersects rays from two or more stations into a position fix. For a digital
   link it also names the system (DJI O4, Walksnail, HDZero, 802.11 video
   link, Wi-Fi traffic, …) from its own classification table and the report's
   centre frequency, bandwidth and class.

A station gives a **bearing, never a position**. A position needs at least two
stations that hear the same transmitter.

| Where | What |
|---|---|
| [`level1-c5phy/`](level1-c5phy/) | Station firmware for the Seeed XIAO ESP32-C5 (PlatformIO) and its desktop tests. [Its README](level1-c5phy/README.md) has the full serial contract |
| [`docs/Level1-Detection-Internals.md`](docs/Level1-Detection-Internals.md) | How the station decides, for whoever maintains the code: the per-window metrics, the analog gate, the wideband path and its thresholds, pull-in, the channel plan, dual band, the antenna model, report keys, what the tests prove |
| [`docs/Level1-Bench-Data-Plan.md`](docs/Level1-Bench-Data-Plan.md) | The bench campaign's working memory: which stage measures which constant, document or mapper row, the decision rule for each outcome, what goes back to the user, the log. Raw records go to [`docs/bench/`](docs/bench/) |
| [`docs/Level1-Bench-Run-Order.md`](docs/Level1-Bench-Run-Order.md) | In which order to run the bench stages and why: every assumption the firmware leans on, ranked by how likely it is wrong today (what the desk already settled, what only the bench can), and the first sessions written out for helpers, with record sheets and stop rules |
| [`docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`](docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf) | Full BOM, block diagram, power budget and the stage 0–8 bench procedure with record sheets ([HTML](docs/Level1-Station-v3-C5PHY-Bench-Guide.html)) |
| [`level2-main`](../../tree/level2-main) branch | Everything a level 1 station shares with the rest of the network: the mapper (`mesh-mapper.py`, with level 1 bearing support for analog and digital links), the home-station firmware (`node-mode-dualcore`, `home_node`), the Heltec V4 Meshtastic setup, the Raspberry Pi installer and a level 1 station simulator. Also the level 2 detectors (Remote ID, DJI DroneID, MAVLink, fingerprints) |

This branch holds only the level 1 station. See
[Mesh, home station and mapper](#mesh-home-station-and-mapper) for what to take
from `level2-main`.

</details>

---

## Hardware

<details>
<summary>Expand</summary>

Per station. Prices and the full list (enclosure, solar, passives) are in the
[bench guide](docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf), sheet 5.

| Qty | Part | Notes |
|---|---|---|
| 1 | **Seeed XIAO ESP32-C5** | The receiver and MCU. Only its U.FL antenna port carries RF; the stock antenna comes off once the switch goes in |
| 4 | **Directional patch antenna**, 5.8 GHz, 7–9 dBi typical, SMA | One per box face. Any directional patch does; **enter its gain in [Station setup](#station-setup-location-heading-and-antennas)**: the sector beamwidth and the bearing constant are derived from it. Buy one batch and never mix types: the bearing compares their levels |
| 4 | **Dual-band directional patch antenna**, 2.4–2.5 and 5.6–5.95 GHz, 6–9 dBi, SMA, identical (dual-band variant) | Instead of the 5.8 GHz patches, for a station built from `seeed_xiao_esp32c5_dualband`. Enter both gains in Station setup (defaults 8 dBi at 5.8 GHz, 6 dBi at 2.4 GHz). See [Single-band or dual-band?](#single-band-or-dual-band) |
| 1 | **SP4T RF switch** covering 5.6–6.0 GHz (2.4–6.0 GHz for dual-band), 3.3 V control | **PE42442** recommended, see [switch choice](#switch-choice). Start on an evaluation board |
| 4 | u.FL–SMA pigtail, equal length, ≤ 15 cm | Patches to the switch. Equal length keeps the sector losses equal |
| 1–2 | u.FL–u.FL pigtail, ≤ 5 cm | Switch common to the XIAO (two with the LNA) |
| 1 | 5.8 GHz LNA + band-pass filter, ~20 dB (optional; **single-band stations only**) | Between the switch and the XIAO. Fit it if stage 5 shows the station is deafer than an RX5808 station, or if it sits near a 5 GHz access point. The filter would blind the 2.4 GHz plan of a dual-band station |
| 1 | Wideband LNA 2.4–6 GHz, no filter (optional; dual-band variant) | The dual-band station's LNA, if stage 5 shows it needs one. Without a filter it also amplifies every 2.4 GHz access point in view |
| 1 | **Heltec WiFi LoRa 32 V4** + LoRa antenna | Meshtastic radio. Buy your region's band (863–928 MHz for EU868 / US915 / ...) and the standard OLED model: the TFT model uses GPIO47/48, the two pins the station talks to, for its touchscreen |
| 3 | 2 kΩ resistor | Series resistors on the three switch control lines |
| — | 100 nF ×2, 10 µF, 1000 µF low-ESR | Switch and LNA decoupling, Heltec TX bursts |
| — | Power | 5 V rail, ≈ 1.0 W average per station (≈ 1.3 W with the LNA), but **≈ 0.9 A peaks** while the V4 transmits (750 mA at 27 dBm): the 5 V supply needs **≥ 1.5 A**. The bench guide sizes a 20 W panel and a 50 Wh battery |

For the bench you also want a 5.8 GHz VTX with an NTSC and a PAL camera, a
step attenuator, and for stage 8 whatever digital kit you have (an
OpenIPC/wfb-ng link, HDZero, DJI O4 with goggles, Walksnail). Sheet 10 of the
bench guide says what each piece of kit is used for, stage by stage, and holds
the filter-skirt record that sets `WB_ANALOG_OWN_MHZ`.

### Single-band or dual-band?

<details>
<summary>Expand</summary>

Two build environments, one firmware. The choice is made by the antennas.

| | `seeed_xiao_esp32c5` (single-band) | `seeed_xiao_esp32c5_dualband` |
|---|---|---|
| Antennas | 4 × 5.8 GHz patches | 4 × dual-band 2.4 + 5.8 GHz patches |
| Front end | optional 5.8 GHz LNA + band-pass filter | optional wideband LNA, no filter |
| Sweep | 50 channels, 5190–5945 MHz: analog FPV, DJI O3/O4 (5.8 GHz and the 5.1 GHz CE band), Walksnail, HDZero, 5 GHz Wi-Fi-based links | the same plus G1–G5, 2402–2482 MHz: DJI OcuSync 2 / DJI FPV at 2.4 GHz, 2.4 GHz Wi-Fi-based links |
| Sweep time | ≈ 2.5 s | ≈ 2.8 s |
| Clutter | 5 GHz access points on the Wi-Fi channels the plan crosses | every 2.4 GHz access point, phone and hotspot in view. Idle traffic is bursty and falls out (`cv2` > 1.5 in the sweep, or duty < 75 % in the confirmation pass); a busy one is reported as `dot11`, and the mapper labels it Wi-Fi traffic while its duty stays under 90 % |
| Calibration | `RF_NOISE_POWER`, `RSSI_CAL_*`, antenna gain | the same, plus the `_24` set and the 2.4 GHz gain, measured on a G channel |
| Boot line / heartbeat | `"bands":"5.8"` | `"bands":"2.4+5.8"`, `"channels":55`; the USB heartbeat adds `nf_dbm_24` |
| Proven on hardware | nothing yet | nothing yet, and the I/Q bus at BW40 on 2.4 GHz is one more unknown: C5VRX used 5 GHz only |

2.4 GHz is detection **with a bearing** only when the antennas are dual-band.
A 5.8 GHz patch still picks something up at 2.4 GHz, but through whatever
out-of-band response it has, with no usable sector pattern: build dual-band
only with dual-band patches. Likewise D1–D3 and L4–L8 lie under the 5.6–5.95
GHz band of a typical 5.8 GHz patch; the station hears them with whatever
gain the patches have there.

</details>

### Switch choice

<details>
<summary>Expand</summary>

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

</details>

</details>

---

## Wiring

<details>
<summary>Expand</summary>

### XIAO ESP32-C5 pins

<details>
<summary>Expand</summary>

Every pin used is a top-side castellation; nothing is on the underside. Wire by
the **D-labels** printed on the board. The pins are the same for both build
variants.

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

</details>

### RF chain

<details>
<summary>Expand</summary>

```
 Patch N ─┐                                      (optional, single-band)
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
  the bearing constant is unaffected. A dual-band station takes a wideband LNA
  without the band-pass filter, or none.
- On a bare PE42442 (not an eval board), tie VSS_EXT (pin 20) to ground so the
  internal negative supply runs, and keep the RF pins at 0 V DC.
- Mount the patches on the four vertical faces at 0/90/180/270°, tilted 10–15°
  up. Point face N at true north if you can, and note the heading you actually
  got either way.

</details>

### Heltec and power

<details>
<summary>Expand</summary>

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

</details>

</details>

---

## Antenna sectors: how the switch lines cycle

<details>
<summary>Expand</summary>

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

<details>
<summary>Expand</summary>

For every channel, on every sweep, the station does this:

```
tune channel ─ 8 ms ─► sector 0 N ─► sector 1 E ─► sector 2 S ─► sector 3 W ─► next channel
                       │
                       └─ drive D8/D9/D7 to the sector's pattern, wait 200 µs, capture 1 window
                          (quiet channel) or up to 3 (0.4 ms each, plus retakes if the gain steps down)
```

- That is four switch changes per channel and 200 per sweep (220 dual-band).
  A 50-channel sweep takes about 2.5 s (55 channels about 2.8 s), and sweeps
  repeat back to back.
- After each sweep, the two strongest analog hits get a video check: the
  station retunes to that channel, parks the switch on the hit's **strongest**
  sector, and takes 8 windows 5 ms apart. The two strongest wideband
  candidates get a confirmation pass the same way, followed by one window per
  sector in the order N E S W W S E N at the same gain (eight more switch
  changes), from which their bearing is taken.
- At boot all three lines go low, then sector 0 (N) is selected.
- While a channel is held on the bench console (`h`), `s 0`–`s 3` parks the
  switch on one sector and re-asserts it with every bench line (twice a second),
  and `t 100` etc. puts a raw pattern on the lines that stays until `s` or `x`.
  Every bench and status line shows what is on the lines as `"switch":"100"`.

</details>

### Line states for each sector (default table)

<details>
<summary>Expand</summary>

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

</details>

### What that selects on a PE42442

<details>
<summary>Expand</summary>

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

</details>

### Skyworks SKY13322-375LF

<details>
<summary>Expand</summary>

This part has four control lines and wants exactly one of them high (J1 = V1
only, J2 = V2 only, J3 = V3 only, J4 = V4 only; the datasheet calls any other
state undefined). Three GPIOs can't drive that directly. One way that keeps the
firmware as it is: D8 → V1, D9 → V2, D7 → V3, and a 3-input NOR of the same
three lines (e.g. a 74LVC1G27 powered from 3V3) → V4. Then build with:

```ini
    -DSECTOR_SWITCH_TABLE='{0x1,0x2,0x4,0x0}'   ; N=J1 (V1) E=J2 (V2) S=J3 (V3) W=J4 (all low, NOR high)
```

</details>

### Any other switch

<details>
<summary>Expand</summary>

Look up its truth table and fill in `SECTOR_SWITCH_TABLE` so that:

1. **The four entries go round the box clockwise** (seen from above): N, E, S, W.
   The bearing takes sector `k+1` as the clockwise neighbour and `k−1` as the
   counter-clockwise one (`bearing = az[k] + K·(P[k+1] − P[k−1])`, with K from
   [the antenna gain](#the-bearing-constant-and-your-antennas)). If E and W
   are swapped, a transmitter just east of north reads just west of north.
2. Every entry selects exactly one valid path. Bit 0 → D8, bit 1 → D9, bit 2 → D7.
3. If your faces aren't at 0/90/180/270°, set `SECTOR_AZIMUTH_DEG` to match.

The `sectors` array in every detection line is always in index order:
`[N, E, S, W]`.

</details>

### Checking the mapping on the bench

<details>
<summary>Expand</summary>

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

</details>

### The bearing constant and your antennas

<details>
<summary>Expand</summary>

The bearing is `az[k] + K·(P[k+1] − P[k−1])`: the strongest sector's axis plus
K degrees for every dB the clockwise neighbour is louder than the
counter-clockwise one. K depends on how fast the patches' pattern falls off,
so the firmware derives it from the gain you enter in Station setup:

- **Beamwidth from gain:** `√(32400 / 10^(dBi/10))`. 8 dBi → 72°, 6 dBi → 90°,
  9.5 dBi → 60°. If the datasheet's −3 dB beamwidth differs, enter it as
  `custom_antenna_beamwidth_deg` and it is used instead.
- **K from beamwidth:** `2.5 × beamwidth² / 4320` degrees per dB; 72° → 3.0°/dB.
  A Gaussian main lobe alone would give `beamwidth² / 4320`; real patches are
  gentler 45–135° off axis, hence the measured scale `BEARING_K_SCALE` 2.5.
- **Sigma from beamwidth:** 10° × beamwidth / 72 as the base; a wideband
  report adds 5° (coarser levels on a noise-like signal) and 0.2° for every
  percent its duty cycle is under 100.

What the station uses is printed in the boot line and the heartbeat as
`antenna_dbi`, `beamwidth_deg` and `bearing_k`. The dual-band build does the
same for the 2.4 GHz side from `custom_antenna_dbi_24` (default 6 dBi → 90° →
4.7°/dB).

**Anchoring K** is bench stage 6: a VTX at 30 m, the box rotated in 15° steps,
the bearing error against the derived K gives the measured K. Record it in one
of two places:

- `custom_bearing_k = 3.2` in that station's environment in `stations.ini`
  (becomes `BEARING_K_DEG_PER_DB`, overrides the derivation for that station
  only), or
- `-DBEARING_K_SCALE=2.7` in `platformio.ini`'s `build_flags`, set to
  2.5 × measured K / derived K, for every station with that antenna family.
  One rotation per family is enough; the gain entered per station then does
  the rest.

> [!NOTE]
> Under 60° of beamwidth (above about 9.5 dBi) four sectors 90° apart leave
> holes at the sector boundaries: a transmitter on a boundary is weak on both
> neighbours and the bearing clamps at ±45° from the nearer axis. The build
> prints a warning when a station's values get there. Wide patches with modest
> gain are the better bearing antennas.

The antenna gain does **not** enter the dBm calibration: `rssi_dbm` is the
level at the XIAO's U.FL, and stage 5's `RSSI_CAL_*` constants stay valid when
the patches change.

</details>

</details>

---

## Software setup

<details>
<summary>Expand</summary>

### 1. Install the tools (once)

<details>
<summary>Expand</summary>

- [VS Code](https://code.visualstudio.com/) with the **PlatformIO IDE** extension,
  or the PlatformIO CLI on its own: `pip install platformio`.
- PlatformIO Core **6.2.0 or newer, running on Python 3.10 or newer**
  (`pio system info` shows both): the pinned pioarduino platform refuses older
  cores, and its setup script exits on an older Python. `pio upgrade` moves an
  existing install to 6.2.0 only when its Python is 3.9 or newer; the PlatformIO
  IDE's bundled Python can be older, and then `pio upgrade` stops at 6.1.x. In
  that case give Core a current Python of its own and use that `pio`:
  ```
  py -3.12 -m venv "$env:USERPROFILE\pio-core"        # Windows; python3.12 -m venv ~/pio-core elsewhere
  & "$env:USERPROFILE\pio-core\Scripts\python.exe" -m pip install "platformio==6.2.0"
  & "$env:USERPROFILE\pio-core\Scripts\pio.exe" --version
  ```
  and put that `Scripts` folder in front of the old one in `PATH` (`Get-Command
  pio` must name it). The first build then prints "Python version mismatch …
  Recreating penv" and rebuilds `~/.platformio/penv` for the new Python; the
  PlatformIO IDE extension loses its copy of Core in that folder, so on a
  machine that also uses VS Code switch to the pioarduino IDE extension or
  turn off the extension's built-in Python.
- [Git](https://git-scm.com/downloads).
- Linux only: USB serial access, then log out and back in.
  ```bash
  sudo apt install python3-venv
  curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules \
    | sudo tee /etc/udev/rules.d/99-platformio-udev.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  sudo usermod -a -G dialout $USER
  ```

</details>

### 2. Get the code

<details>
<summary>Expand</summary>

```bash
git clone -b level1 https://github.com/tsuinami-1112/drone-sentinel
cd drone-sentinel/level1-c5phy
```

In VS Code, **File → Open Folder…** and open `level1-c5phy` itself (PlatformIO
only activates in a folder with a `platformio.ini`). The first open downloads the
pioarduino ESP32 platform and toolchain, several hundred MB; let it finish.

</details>

### 3. Settings

<details>
<summary>Expand</summary>

**Two generic environments** in `platformio.ini`: `seeed_xiao_esp32c5` (5.8 GHz
patches) and `seeed_xiao_esp32c5_dualband`, which extends it with
`-DDUAL_BAND=1` (dual-band patches, 2.4 GHz swept too). Every deployed station
extends one of the two.

**Per station:** the node id, position, heading and antennas. Each station gets
its own environment in `stations.ini`, written by the Station setup task; see
[Station setup](#station-setup-location-heading-and-antennas). There's nothing
to edit for them here.

| Setting (stations.ini) | Default | What it does |
|---|---|---|
| `extends` | `env:seeed_xiao_esp32c5` | `env:seeed_xiao_esp32c5_dualband` for a station with dual-band patches |
| `custom_node_id` | MAC-derived (`A1B2`) | Becomes `NODE_ID`: the station's key in the mapper and in every report |
| `custom_station_lat`, `custom_station_lon` | none | Become `STATION_LAT`/`STATION_LON`: sent in the heartbeat, so every mapper places the station |
| `custom_station_heading` | `0` | Becomes `STATION_HEADING_DEG`: true-north heading of face N. Sent in the heartbeat, **not** applied to `bearing_deg`; the mapper rotates the bearings by it |
| `custom_antenna_dbi` | `8` | Becomes `ANTENNA_GAIN_DBI` (0–20): gain of the patches. The sector beamwidth and the bearing constant are derived from it, see [The bearing constant and your antennas](#the-bearing-constant-and-your-antennas) |
| `custom_antenna_beamwidth_deg` | derived | Becomes `ANTENNA_BEAMWIDTH_DEG` (20–180): the datasheet's −3 dB beamwidth, when it differs from the derived one |
| `custom_bearing_k` | derived | Becomes `BEARING_K_DEG_PER_DB` (0.5–20): the K measured at stage 6 for this station |
| `custom_antenna_dbi_24`, `custom_antenna_beamwidth_deg_24`, `custom_bearing_k_24` | `6`, derived, derived | The same for the 2.4 GHz side of dual-band patches. Ignored, with a build warning, unless the environment extends `seeed_xiao_esp32c5_dualband` |

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
| `RF_COUNTRY_CC` | `"US"` | If the heartbeat shows `tune_fail` > 0, check this first |
| `SECTOR_SWITCH_TABLE` | `{0x0,0x1,0x2,0x3}` | See [Antenna sectors](#antenna-sectors-how-the-switch-lines-cycle) |
| `RF_FRONTEND_GAIN_DB` | `0` | Leave at 0 and calibrate with the LNA in place. Set 20 only to carry a calibration taken without the LNA over to a station that has one |
| `RSSI_CAL_*`, `DETECT_LEVEL_DB`, `RF_NOISE_POWER` | uncalibrated | From bench stages 1 and 5 |
| `RF_NOISE_POWER_24`, `RSSI_CAL_DBM_AT_NOISE_24`, `RSSI_CAL_SLOPE_24`, `RSSI_CAL_OFFSET_DB_24`, `RF_FRONTEND_GAIN_DB_24` | as the 5.8 GHz ones | Dual-band build only: the same calibration for the 2.4 GHz plan, taken on a G channel |
| `BEARING_K_SCALE` | `2.5` | Measured K / Gaussian-lobe K, once per antenna family from stage 6 |
| `DUAL_BAND` | `0` | `1` adds G1–G5 (2402–2482 MHz), auto band mode and the `_24` calibration. Set by the `seeed_xiao_esp32c5_dualband` environment, not by hand |
| `SCAN_5G1` | `1` | D1–D3 at 5190/5210/5230 MHz, three 40 MHz views over DJI O4's CE band. `0` drops them |
| `LOWBAND` | `1` | `1` = L4–L8 (5473–5621 MHz), `0` = none, `2` = L1–L8: L1–L3 sit 64–138 MHz under Wi-Fi channel 100 and also need `-DC5PHY_MAX_BOOTSTRAP_OFFSET_MHZ=140`, a pull the bench has not proven |
| `GAP_CHANNELS` | `1` | X1 5675 and X2 5715 MHz, the two holes of the table that no pull-in reaches from a neighbour |
| `WIDEBAND` | `1` | The digital path. `0` builds a station that reports analog carriers only |
| `PULLIN` | `1` | One retune onto an off-channel analog carrier (`PULLIN_MIN_KHZ` 3000 = 3 MHz off, at most 2 per sweep). `0` turns it off |
| `ANALOG_CV2_MAX` | `0.5` | The third part of the analog gate: envelope variance / mean² at most this. FM video 0.02–0.3, OFDM about 1 |
| `GAIN_STEP` | `3` | Gain index steps (about 1 dB each) while a window clips. A 6 dB step dropped a carrier just above threshold under the coherence power gate |
| `WB_*` | see `config.h` | The wideband thresholds: candidate envelope `cv2` 0.5–1.5 and level spread ≤ 6 dB, 8 confirmation windows 5 ms apart, duty ≥ 75 %, class edges `r128` ≥ 0.10 (`dot11`) and `r2667` ≥ 0.03 with `r128` < 0.05 (`lte`), fold within 25 MHz, 2 passes per sweep, +5° sigma. Explained in [Level 1 detection internals](docs/Level1-Detection-Internals.md) |
| `C5PHY_MAX_MHZ` | `5945` | `5885` drops R8/E6/E7/E8 if stage 2 shows the synthesizer can't reach them |

</details>

</details>

---

<a name="station-location-and-heading"></a>

## Station setup: location, heading and antennas

<details>
<summary>Expand</summary>

A station only measures a bearing relative to its own face N. To draw that
bearing on the map and cross it with other stations' bearings, the mapper needs
two things for every station, and the firmware needs a third to turn sector
levels into degrees:

| What | Why | Example |
|---|---|---|
| **Position** | Where the station's bearing ray starts | `33.494200, -111.926100` |
| **Heading of face N** | Turns "32° from face N" into a compass bearing. True north, degrees clockwise | `15` |
| **Antennas** | Variant (5.8 GHz or dual-band patches) and gain in dBi: the sector beamwidth and the bearing constant are derived from the gain | `8` (and `6` at 2.4 GHz) |

The heading matters more than the position. A position 20 m off moves a ray by
at most 20 m, but a heading 5° off swings it by about 87 m at 1 km and 175 m at
2 km.

### Give every station a NODE_ID

<details>
<summary>Expand</summary>

The `NODE_ID` is the station's name in every report, and the key every mapper
stores its position against. Pick a short one (`RX01`, `NORTH2`: letters, digits,
`_` and `-`, up to 23 characters) and write it on the box. Short matters,
because it rides in every 191-byte mesh line.

Without one, the firmware uses 4 hex digits of the XIAO's MAC address. Avoid that
for a fleet, for two reasons:

- swapping the XIAO gives the station a new id, so it shows up as a new,
  unplaced station;
- two boards can end up with the same id (about 2 % odds across 50 stations).

</details>

### Recommended: flash it with Station setup

<details>
<summary>Expand</summary>

Flash the position, heading and antennas into the station, and every mapper
that hears it places it by itself. Nothing has to be entered on any mapper.

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
5. **Pick the antennas.** **5.8 GHz patches only** (the default) or **dual-band
   2.4 + 5.8 GHz patches**, which makes the station a dual-band build. Enter
   the datasheet gain as **Antenna gain (dBi)** (default 8) and, for dual-band,
   **2.4 GHz gain (dBi)** (default 6). The beamwidth fields are optional: leave
   them empty unless the datasheet's −3 dB beamwidth differs from the derived
   one (8 dBi → 72°, 6 dBi → 90°). The page warns under 60°.
6. **Save.** The station is written to `level1-c5phy/stations.ini` as its own
   build environment, e.g. `[env:RX01]`, and the task ends.
7. **Flash that station.** Refresh PROJECT TASKS (the ↻ button at the top of the
   PlatformIO sidebar, or reload the window); `RX01` is now its own entry. Run
   **RX01 → Platform → Erase Flash**, then **RX01 → General → Upload**. From a
   terminal: `pio run -e RX01 -t erase && pio run -e RX01 -t upload`.
8. **Check the boot line** in the serial monitor:
   `{"info":"c5phy v3 station ready","node_id":"RX01",…,"heading":15,"lat":33.494200,"lon":-111.926100,…,"bands":"5.8","antenna_dbi":8.0,"beamwidth_deg":72,"bearing_k":2.97,…}`.

The station now sends its position in its heartbeat: on every USB heartbeat, and
over the mesh on the first three after boot, then every 10 minutes (the 191-byte
mesh line has no room for it every time). A mapper that starts later picks it up
within 10 minutes. In the LEVEL 1 STATIONS panel the station appears placed, with
**auto** next to its position and heading. This needs the current mapper from
`level2-main`.

About `stations.ini`:

- It holds one environment per station: `extends` (which of the two generic
  environments), `custom_node_id`, `custom_station_lat/lon/heading`,
  `custom_antenna_dbi` and the optional `custom_antenna_beamwidth_deg` /
  `custom_bearing_k`, each with a `_24` twin on a dual-band station. Station
  setup writes it; you can also edit it by hand.
  [`stations.example.ini`](level1-c5phy/stations.example.ini) shows the format,
  including a dual-band station.
- The values are checked at build time. A wrong one stops the build with a
  plain message: a lone latitude, 95° north, a space in the node id, a gain of
  25 dBi. A `_24` option on a single-band environment is ignored with a
  warning, and a beamwidth under 60° gets one too.
- It records where your stations are, so it is **not committed** (it's in
  `.gitignore`). Keep your own backup, or share it privately with whoever
  flashes stations.

</details>

### Getting good numbers

<details>
<summary>Expand</summary>

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
- **Antenna gain:** the datasheet figure, in dBi (not dBd: add 2.15 to a dBd
  figure). When in doubt, a stage 6 rotation measures the bearing constant
  directly and `custom_bearing_k` overrides whatever the gain derived.
- **Check it:** put a VTX at a known spot and see that the station's ray passes
  through it. If it misses by a constant angle, correct the heading by that
  angle.

</details>

### Without flashing: the mapper panel

<details>
<summary>Expand</summary>

For a station flashed without a location, or for a quick test, set it in the
mapper's **LEVEL 1 STATIONS** panel:

- type the latitude and longitude, or press **PLACE** and click the map, or
  **HERE** (this browser's location), then **SAVE**;
- type the heading in the same row.

This is stored only in that mapper's `stations.json`. With several mappers,
repeat it on each one, or copy `stations.json` between them (a mapper reads it
when it starts). The antennas have no mapper-side fallback: the bearing
constant is applied in the station, so a station flashed from the generic
environment runs with the 8 dBi defaults.

</details>

### Which value a mapper uses

<details>
<summary>Expand</summary>

| Situation | Position the mapper uses |
|---|---|
| Station flashed with a position, nothing saved in this mapper | The flashed one, marked **auto** |
| A position saved by hand in this mapper | The hand-set one, even after the station is reflashed |
| Both position fields cleared in the panel, then **SAVE** | Back to the flashed one |
| Not flashed and not set | None: the station's bearings are not drawn or used |

The heading works the same way, except that clearing it doesn't bring the
flashed one back. To return a station fully to its flashed values, press **DEL**
in the panel; it registers again from its next heartbeat.

</details>

### Moving or replacing a station

<details>
<summary>Expand</summary>

- **Moved:**
  1. Run Station setup, pick the station, move the pin (and the heading),
     Save, then reflash it.
  2. Mappers follow by themselves, unless someone set its position by hand on a
     mapper. Clear it there.
- **Replacing the XIAO:** flash the new board from the same environment. It
  comes up with the same `NODE_ID`, position, heading and antenna settings, and
  the mappers notice nothing.
- **Replacing the patches:** run Station setup, pick the station, change the
  antenna variant or gain, Save, reflash. A measured `custom_bearing_k` belongs
  to the old patches: clear it, or measure again.

</details>

</details>

---

## Flashing

<details>
<summary>Expand</summary>

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

`seeed_xiao_esp32c5` is the generic single-band build, with no node id or
location: use it on the bench. `seeed_xiao_esp32c5_dualband` is the same build
with `-DDUAL_BAND=1`, for a bench with dual-band patches: put it in place of
`seeed_xiao_esp32c5` in each of the three lines
(`pio run -e seeed_xiao_esp32c5_dualband -t erase`, …). For a station you
deploy, run the same steps under its own environment (e.g. **RX01**, or
`pio run -e RX01 -t erase` …), created by
[Station setup](#station-setup-location-heading-and-antennas); it extends one
of the two generic environments.

- Use a USB-C **data** cable. A charge-only cable never shows a port.
- If the board won't connect: hold **BOOT**, tap **RESET**, release **BOOT**, and
  run the task again. Press RESET when the upload finishes.
- With several boards plugged in, unplug the others or add
  `upload_port = /dev/ttyACM0` (`COM5`, `/dev/cu.usbmodem101`, …) to the
  environment.
- Close the monitor before starting the mapper: only one program can hold the port.

On a good boot the first line is:

```json
{"info":"c5phy v3 station ready","node_id":"RX01","receiver":"c5phy","hw":"v3","channels":50,"sectors":4,"heading":15,"lat":33.494200,"lon":-111.926100,"fe_gain_db":0.0,"threshold_dbm":-87.0,"threshold_level_db":8.0,"q_min":40,"peak_pick":1,"video":1,"bw40":1,"gain_max":62,"window_us":409,"iq_lane_bits":3,"bands":"5.8","antenna_dbi":8.0,"beamwidth_deg":72,"bearing_k":2.97,"wideband":1,"pullin":1,"gain_step":3,"mesh_uart":"D4 TX / D5 RX 115200","phy_set_freq":true,"rf":true}
```

(`lat`/`lon` appear only on a station flashed with its position. A dual-band
station reads `"channels":55` and `"bands":"2.4+5.8"`; `antenna_dbi`,
`beamwidth_deg` and `bearing_k` are always the 5.8 GHz patches'.)

`"rf":true` means the PHY is held receive-only and the I/Q reader is running.
`"rf":false` comes after an `{"info":"error","stage":...,"call":...,"err":...}`
line naming the call that failed. A heartbeat follows about 10 s after boot,
then every 60 s.

### Desktop tests

<details>
<summary>Expand</summary>

The signal processing (`demod.c`, `bearing.c`, `report.c`, `fpv_channels.c`) is
plain C and is tested on a PC with synthetic I/Q: FM video, LTE-like and
802.11-like OFDM, single-carrier QPSK and noise, through the same gain loop as
the firmware. It needs `gcc`, `make` and `python3`:

```bash
cd level1-c5phy/test/host && make           # ends with "ALL TESTS PASSED" and "check_json: ... OK", twice
```

The suite runs twice, once with the default plan and once as the dual-band
build with the full Lowband (`-DDUAL_BAND=1 -DLOWBAND=2`), and `check_json.py`
parses every JSON line both runs emit.

</details>

### Continuous integration

<details>
<summary>Expand</summary>

The same tests and both firmware builds run on GitHub on every push to `level1`
and every pull request that touches `level1-c5phy/`
([`.github/workflows/firmware.yml`](.github/workflows/firmware.yml)). Nothing is
published: a deployed station is flashed from its own environment. The merged
images of the two generic environments are kept as workflow artifacts for 14
days, for a quick bench flash of a build without per-station settings.

</details>

</details>

---

## Mesh, home station and mapper

<details>
<summary>Expand</summary>

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
| Home station | [Build a station](../../tree/level2-main#build-a-station) and [Build and flash the firmware](../../tree/level2-main#build-and-flash-the-firmware): `node-mode-dualcore`, environment `home_node` | Use the current `level2-main` build. It passes `"type":"analog_fm"` and `"type":"wideband"` lines straight through. Older builds put a second station's report of the same emitter through their duplicate filter, which drops exactly the report a position fix needs; builds before the digital work do that to every `wideband` line |
| Mapper | [Quick Start](../../tree/level2-main#quick-start): `mesh-mapper.py`, also the Raspberry Pi installer | Has the level 1 support for both report types: the LEVEL 1 STATIONS panel, bearing rays, multi-station position fixes. For a digital link it names the system (DJI O3, DJI O4, DJI OcuSync 2, Walksnail Avatar / DJI FPV V1, HDZero, 802.11 video link, Wi-Fi traffic, or unknown digital) with a confidence, by matching the report's `fc_mhz`, `bw_mhz`, `cls` and `duty` against its `WIDEBAND_SYSTEMS` table. That table lives in the mapper, not in the firmware; [`docs/REFERENCE.md`](../../blob/level2-main/docs/REFERENCE.md#digital-video-links-typewideband) on `level2-main` documents it |
| Standalone mapper | [`standalone-mapper-meshtastic`](../../tree/standalone-mapper-meshtastic) branch | The Meshtastic-only mapper without a home station: the same level 1 support, both report types, the same classification table |
| Simulator | [`mapper_test/level1_bearing_sim.py`](../../blob/level2-main/mapper_test/level1_bearing_sim.py) | Two or three simulated level 1 stations and one drone, for trying the mapper without hardware; `--wideband` makes the drone a DJI O4-like digital link on R4 |

Over the mesh the station sends each emitter (one per table channel, analog or
digital) at most once per 8 s (the first report of a new emitter goes at once)
and a heartbeat every 120 s.

### Commissioning a station in the mapper

<details>
<summary>Expand</summary>

Open the mapper (`http://localhost:5000`) and pick the serial port: the home
station's XIAO, or on the bench a level 1 station's XIAO directly. Then:

1. Each station registers itself from its first heartbeat and appears in the
   **LEVEL 1 STATIONS** panel, under its `NODE_ID`.
2. A station flashed with its location appears placed, marked **auto**. For any
   other station, set its position and heading in the panel. Both are covered in
   [Station setup](#station-setup-location-heading-and-antennas).
3. Bearings show as rays from the station with a ±σ wedge. When two or more
   placed stations report the same emitter within 30 s and their rays cross at
   more than 8°, the mapper puts a position fix with an error circle where they
   meet. A digital link's track also carries the system name and its
   confidence in the identification panel.

A wrong heading rotates every ray from that station, so check it with a VTX at a
known spot before trusting fixes.

</details>

</details>

---

## Bring-up checklist

<details>
<summary>Expand</summary>

Condensed from the bench guide, which has the record sheets. Stages 0–5 run on a
bare XIAO with its stock antenna; the switch comes in at stage 6, a digital
video kit at stage 8. Don't move on until a stage passes.

| Stage | Do | Pass |
|---|---|---|
| 0 Flash and boot | Erase, upload, monitor. `?` twice, 60 s apart | `"rf":true`; `captures` climbing, `cap_err` 0 |
| 1 Receiver alive | No VTX: `h A1`. Then key a VTX on A1 a few metres away. Dual-band: the same on `h G3` | Quiet: `level_db` ≈ 0 ± 2, `p_mean` ≈ 2, `q_phase` < 15, `cv2` ≈ 1, `stuck` 0. Keyed: `level_db` up ≥ 30 dB, `q_phase` ≥ 50, `cv2` ≤ 0.3, `cfo_khz` within ±2000. On G3 the same, which also proves the I/Q bus at BW40 on 2.4 GHz |
| 2 Channel coverage | `x`, wait for a heartbeat. Then `h E4`, `h E8`, `h D1`, `h L4` (dual-band: `h G1`, `h G5`) | `tune_fail` 0, `channels` 50 (55 dual-band); E8 hears a VTX on E8 but not one on E5; D1 and L4 hold without a tune error. The D and L points are Wi-Fi bands where a VTX may not be keyed in most countries: a 5 GHz access point on Wi-Fi channel 36 (5180 MHz) is the test signal for D1 |
| 3 Selectivity | VTX on R3, scanning. Then hold the channel nearest a live 5 GHz AP, then let the station scan past it | One R3 report (B1/F1 folded in), nothing > 40 MHz away; the AP raises `level_db` but `q_phase` stays < 40, and it produces no `wideband` report either (`cv2` > 1.5 or duty < 75). A saturated AP (a long file copy) is reported as `dot11` with `duty` ≥ 90: expected, it is a real emitter |
| 4 Video | NTSC camera: hold its channel, `v`. Then PAL. Then camera unplugged | ≥ 3/8 windows read `NTSC` 15 734 Hz / `PAL` 15 625 Hz; unplugged gives `present:0` |
| 5 Sensitivity | VTX through a step attenuator; record `level_db`, `q_phase` and `cv2` against input; compare with an RX5808 station. Then the filter skirt: VTX on R4 at `level_db` 35–40, hold the channels 11–31 MHz off it (bench guide sheet 10) | ~1 dB per dB over ~60 dB; `q_phase` ≥ 40 and `cv2` ≤ 0.5 all the way down to the threshold; set the `RSSI_CAL_*` constants and `DETECT_LEVEL_DB` (dual-band: the `_24` set on a G channel). Skirt: the largest offset where `level_db` ≥ 8 with `cv2` 0.5–1.5, plus 5 MHz, is the `WB_ANALOG_OWN_MHZ` the station needs (firmware: 30) |
| 6 Switch and pattern | [Map the sectors](#checking-the-mapping-on-the-bench), mount the patches, VTX at 30 m, rotate the box in 15° steps | Each `s n` follows its patch; the bearing error against the derived K (boot line `bearing_k`, 2.97 for 8 dBi) gives the measured K: record it as `custom_bearing_k` for the station and as `BEARING_K_SCALE` (2.5 × measured / derived) for the antenna family |
| 7 Field | Two stations 300–500 m apart, positions and headings set; walk a VTX over 10 marked points; 72 h on solar | The 90 % circle contains the true position on ≥ 9/10; heartbeat gap never > 5 min |
| 8 Digital | Per kit you have (OpenIPC/wfb-ng, HDZero, DJI O4 with goggles, Walksnail): `h` its channel, `w` a few times; then `x` with the mapper open; then rotate the box in 15° steps as in stage 6 | `w` reads `duty` ≥ 75 and a `cls` that fits (`dot11` with `r128` ≥ 0.10 and `scan_lag` 128 for OpenIPC; `lte` with `r2667` ≥ 0.03 and `scan_lag` 2665–2669 for DJI; HDZero and Walksnail unknown, record what they read), `bw_mhz` and `fc_mhz` matching the kit's setting; one `wideband` report per sweep, and the mapper names the system; bearing error within ±σ at 0/15/30/45°, giving the digital K |

### Bench console

<details>
<summary>Expand</summary>

Type into the serial monitor, Enter-terminated.

| Command | Effect |
|---|---|
| `?` | Status line (adds `band`, `wb_seen`, `pullin`) |
| `h R3` / `h 5732` / `h D1` / `h G3` | Hold a channel by name or MHz (`G` channels on a dual-band build); prints an `{"info":"bench",...}` line twice a second with `level_db`, `q_phase`, `cv2`, `cfo_khz` |
| `s 0` … `s 3` | Park the switch on sector N / E / S / W (while holding) |
| `g 30` / `g a` | Fixed gain index (2–62) / automatic |
| `v` | Video check on the held channel and sector, all eight windows listed |
| `w` | Wideband check on the held channel and sector: the 8-window confirmation pass, then a lag scan 40–3200 of the last window (about 2 s). Prints `{"info":"wideband",...}` with `cls`, `conf`, `bw_mhz`, `fc_mhz`, `duty`, `cv2`, `r1`, `r4`, `r128`, `r512`, `r2667`, `scan_lag`, `scan_r` |
| `t 100` / `t 1` | Put a raw pattern on the switch lines while holding (V1V2V3 = D8 D9 D7, or a number 0–7); stays until `s` or `x`, see [the bench check](#checking-the-mapping-on-the-bench) |
| `b 0` / `b 1` | Analog filter BW20 (+3 dB SNR) / BW40 (full video) |
| `x` | Resume scanning |

</details>

</details>

---

## Serial output

<details>
<summary>Expand</summary>

One JSON object per line on USB at 115200. Abbreviated:

```json
{"type":"analog_fm","mac":"AF:00:52:03:16:64","freq_mhz":5732,"band":"R","ch":3,"rssi":-68,"sectors":[-68.1,-74.4,-91.0,-85.2],"sector":0,"bearing_deg":32,"bearing_sigma_deg":15,"video":"NTSC","fp":"NTSC/15736/5734","node_id":"RX01","seq":42,...}
{"type":"wideband","mac":"DF:00:52:04:16:89","freq_mhz":5769,"fc_mhz":5768.5,"band":"R","ch":4,"rssi":-66,"cls":"lte","conf":"high","bw_mhz":10,"duty":100,"cv2":0.98,"r1":0.85,"r128":0.009,"r512":0.007,"r2667":0.056,"span_mhz":0,"sectors":[-66.3,-72.8,-90.1,-84.0],"sector":0,"bearing_deg":20,"bearing_sigma_deg":16,"fp":"lte/10/5768.5","node_id":"RX01","seq":43,...}
{"heartbeat":true,"node_id":"RX01","receiver":"c5phy","channels":50,"heading":0,"bands":"5.8","antenna_dbi":8.0,"beamwidth_deg":72,"bearing_k":2.97,"wb_seen":2,"pullin":1,"tune_fail":0,"cap_err":0,"bus_stuck":0,"sweeps":1830,"nf_dbm":-98,...}
```

- `mac` is derived from the channel (`AF` = analog FM, `DF` = digital FPV, then
  band, channel, MHz), so every station hearing the same carrier reports the
  same key. A digital link is keyed to the table channel it was strongest on;
  its estimated centre is `fc_mhz` and `fp` is `class/bandwidth/centre`.
- `bearing_deg` is relative to face N; `sectors` is in `[N, E, S, W]` order;
  `sector` is the strongest one.
- `cls` is `lte`, `dot11` or `wb`; `conf` is `high`, `med` or `low`; `duty` is
  the percent of confirmation windows the link was on; `r1`…`r2667` are the
  lag autocorrelations the class came from.
- The mesh copy is cut down to ≤ 191 bytes. For a wideband report that keeps
  identity, bearing, `cls`, `fc_mhz`, `bw_mhz` and `duty`, then whatever still
  fits:
  ```json
  {"type":"wideband","mac":"DF:00:52:04:16:89","node_id":"RX01","freq_mhz":5769,"rssi":-66,"bearing_deg":20,"bearing_sigma_deg":16,"cls":"lte","fc_mhz":5768.5,"bw_mhz":10,"duty":100,"sector":0}
  ```
- The mesh heartbeat carries `wb_seen` next to `video_seen`; the USB one also
  has `nf_dbm_24` on a dual-band station.

The full contract (every field, the mesh line, the heartbeat) is in
[`level1-c5phy/README.md`](level1-c5phy/README.md#serial-contract).

</details>

---

## Troubleshooting

<details>
<summary>Expand</summary>

| Symptom | Likely cause |
|---|---|
| Upload can't find the board | Charge-only cable; use BOOT + RESET; close any open monitor |
| `"rf":false` at boot | The `{"info":"error"}` line before it names the call. A missing undocumented PHY symbol means a platform/libphy mismatch; `-DC5PHY_STRONG_PHY_SYMBOLS=1` turns that into a link error |
| Receiver deaf after a reflash | Flashed without the erase. Erase, then upload |
| `stuck` 1, `bus_stuck` climbing | Something touches an I/Q lane pad (D0 D1 D2 D3 D6 D10), or the diagnostic bus isn't streaming. Trust the flag, not `p_mean` |
| `level_db` rises but `q_phase` doesn't | Off-channel carrier (check `cfo_khz`; from 3 MHz off the station pulls it in by itself and `pullin` counts the attempts), a digital link (`cv2` about 1: look for a `wideband` report), or a lane-order problem |
| `tune_fail` > 0 | `RF_COUNTRY_CC` doesn't allow those channels; set the deployment country, erase, reflash |
| `tune_fail` climbs after the update | The D, L and G channels park the radio on Wi-Fi channels 36–48, 100–128 and 1–13 first, which the country table must allow. Set the deployment country; or drop the points you don't need with `-DSCAN_5G1=0` and/or `-DLOWBAND=0` |
| Hits or `wideband` reports on R8/E6/E7/E8 that mirror E5 | The synthesizer doesn't reach above 5885 MHz (`alias_drop` counts the mirrors it caught, analog and digital). Build with `-DC5PHY_MAX_MHZ=5885` |
| A `wideband` report 21–30 MHz from a strong analog carrier, same bearing, `cls` `dot11`, `fc_mhz` far off | The channel filter's skirt turning the FM carrier into a noise-like image. Fixed in this build: an analog carrier owns the wideband candidates within `WB_ANALOG_OWN_MHZ` (30 MHz) of it. A station on older firmware: update |
| An analog hit disappears just above threshold | Fixed in this build: `GAIN_STEP` is 3 (a 6 dB step put a carrier just above threshold under the coherence power gate). A station still carrying `-DGAIN_STEP=6` in its flags: remove it |
| `wideband` reports from a Wi-Fi access point | A saturated link (`cls` `dot11`, `duty` ≥ 90) is a real emitter, and an 802.11 video link looks the same to the station; the mapper separates them by duty (under 90 = Wi-Fi traffic) and the 5 MHz Wi-Fi grid. Idle traffic never gets that far (`cv2` > 1.5 or duty < 75). Check the mapper's label first; raising `WB_DUTY_MIN` trades real links for quiet |
| Bearings on digital links wander | TDD links are off between bursts: the station already interleaves the sectors (N E S W W S E N) and widens σ by 5° plus 0.2° per percent of duty under 100. Check `duty` in the report; a `wb` class with low duty is the weakest vote |
| Dual-band station hears nothing at 2.4 GHz | 5.8 GHz patches or a 5.8 GHz band-pass filter in the chain; the station's environment doesn't extend `seeed_xiao_esp32c5_dualband` (boot line `"bands":"5.8"`, `"channels":50`); or the I/Q bus doesn't stream at BW40 on 2.4 GHz, which the bench has not proven (`h G3`: `stuck`, `cap_err`) |
| Bearings off by a constant 90°/180°/270° | Sector table and cabling don't match (see [Antenna sectors](#antenna-sectors-how-the-switch-lines-cycle)), or the heading in the mapper is wrong |
| Bearings off by a constant factor, growing with the offset from the sector axis | The bearing constant doesn't fit the patches: wrong gain entered, or the antenna family needs its own `BEARING_K_SCALE` from a stage 6 rotation (see [The bearing constant and your antennas](#the-bearing-constant-and-your-antennas)) |
| A VTX moving clockwise reads counter-clockwise | E and W cables swapped |
| No reports over the mesh | Heltec serial settings (pins, TEXTMSG, 115200), power saving on, D4/D5 crossed the wrong way, or no common ground |
| Station never appears in the mapper | Home station or mapper older than the current `level2-main`, or no heartbeat reaching the mapper |
| Digital links reach the mapper as plain detections without a ray, or not at all | Mapper or home station older than the current `level2-main`: the `"type":"wideband"` pass-through and the system labels came with the digital work |
| Reports arrive but no position fix | Station positions not set, only one station hears it, or the rays are within 8° of parallel |
| A flashed station shows "position not set" | The mapper is older than the current `level2-main`; the station was flashed from `seeed_xiao_esp32c5` rather than its own environment (check the boot line for `lat`); or, over the mesh only, wait up to 10 min for a heartbeat that carries the position |
| A mapper ignores a station's new position after reflashing | Its position was saved by hand on that mapper. Clear both position fields and SAVE (see [which value wins](#which-value-a-mapper-uses)) |
| Station setup shows no map | No internet for the map tiles: type or paste the coordinates and the heading; everything else works |
| A new station's environment isn't in PROJECT TASKS | Refresh PROJECT TASKS (↻ at the top of the PlatformIO sidebar) or reload the window |
| Build stops with `station settings: …` | A value in `stations.ini` is wrong; the message names it |
| Build prints `antenna beamwidth ~55 deg: four sectors 90 deg apart leave holes` | The gain entered (or the beamwidth) is high for a four-sector box; above about 9.5 dBi the sector boundaries go blind. A warning, not an error |
| Host tests stop with `make: cc: Not a directory`, `cc: command not found` or `gcc: command not found` | No C compiler in that shell (a fresh WSL or Linux install). `sudo apt install build-essential python3`, then `make -C level1-c5phy/test/host` again. The "Not a directory" wording is WSL's Windows PATH entries getting in the way of the lookup, not a path problem in the repo |
| `IncompatiblePlatform: Development platform 'espressif32' is not compatible with PlatformIO Core v6.1.x and depends on PlatformIO Core >=6.2.0` (the platform installs, then is removed again) | PlatformIO Core older than 6.2.0, usually the IDE's bundled core. `pio upgrade` (check with `pio --version`), then build again; the platform re-installs by itself. If `pio upgrade` stops at 6.1.x, the Python under it is older than 3.9: install Core into a venv of a current Python as described under [Install the tools](#1-install-the-tools-once) |
| Build stops with `Failed to install Python dependencies into penv`, exit code `3221225622` (`0xC0000096`), on Windows | A VPN or security product injects a Winsock LSP into `uv.exe`, the installer pioarduino's `penv_setup.py` runs to fill its Python environment (Astrill's `ASProxy64.dll` does this). Root fix, from an elevated PowerShell: `Set-ProcessMitigation -Name uv.exe -Enable DisableExtensionPoints` (a non-elevated shell reports `C0000022` for every setting), or uninstall the vendor's LSP (Astrill's client has an LSP Uninstall entry under Help) and restart. Detour: with `%USERPROFILE%\.platformio\penv\Scripts\python.exe -m pip install`, install the packages `penv_setup.py` lists (its `python_deps` table), then build with `PLATFORMIO_OFFLINE=1` set, which skips the dependency step; if the build then stops at `Failed to install esptool from …\tool-esptoolpy`, `pip install -e` that folder with the same `python.exe` and build again |
| The build keeps an older pioarduino platform (the `platform.json` under `~/.platformio/platforms` says a version other than 55.03.312), or an override such as `PLATFORMIO_OFFLINE=1` does nothing | PlatformIO never re-downloads a platform it installed from a URL, so a `stable` URL keeps whatever it fetched first. `platformio.ini` pins release 55.03.312-1 (the same content as `stable` on 2026-10-08), which installs fresh beside the old copy on the next build; to force it by hand, delete the `espressif32*` folder under `~/.platformio/platforms` and build again |

</details>

---

## Repository layout

<details>
<summary>Expand</summary>

```
.github/workflows/firmware.yml      CI: the host tests and both firmware builds on every push to level1 and every pull request
                                    that touches level1-c5phy/; the two generic images kept 14 days as workflow artifacts
.github/dependabot.yml              keeps the workflow's SHA-pinned actions current
level1-c5phy/                       Level 1 station firmware (PlatformIO, envs seeed_xiao_esp32c5 and seeed_xiao_esp32c5_dualband)
  platformio.ini                    the two generic builds, shared flags (country, calibration); the dual-band one adds -DDUAL_BAND=1
  stations.example.ini              format of stations.ini: one environment per station, extending either build (stations.ini itself is not committed)
  tools/station.py                  custom_* station options (id, position, heading, antennas) -> defines; the "Station setup (map)" task
  tools/station_setup.html          the map page Station setup opens
  include/config.h                  every tunable: pins, switch table, channel plan flags, antenna model, analog gate, wideband and pull-in thresholds, per-band calibration
  src/main.cpp                      sweep, sector measurement, analog gate, pull-in, wideband confirmation and bearing, video check, reports, bench console
  src/sector_switch.cpp             drives the SP4T control lines from SECTOR_SWITCH_TABLE
  src/c5phy_rf.cpp                  Wi-Fi PHY receive-only bring-up and tuning (C5VRX port); band mode for DUAL_BAND
  src/iq_capture.cpp                PARLIO RX, one 16 KiB I/Q window at a time
  src/demod.c, bearing.c            I/Q metrics (level, coherence, envelope, centroid), lag autocorrelations, FM discriminator, PAL/NTSC search; bearing and sigma
  src/report.c, fpv_channels.c      USB and mesh JSON for analog, wideband and heartbeat lines; the channel table (50 by default, 55 dual-band) and the Wi-Fi bootstrap centres
  test/host/                        desktop tests: make (the suite in the default and the dual-band configuration)
docs/Level1-Detection-Internals.md  how the station decides: metrics, analog gate, wideband path, pull-in, channel plan, dual band, antenna model, keys, tests
docs/Level1-Station-v3-C5PHY-Bench-Guide.{pdf,html}   hardware, BOM, power, bench stages 0-8
docs/img/                           README header art and the script that draws it; retired art in archive/
```

That is the whole branch. The mapper, the home-station firmware, the Raspberry
Pi installer and the level 2 detectors are on
[`level2-main`](../../tree/level2-main).

</details>

---

## Acknowledgments

<details>
<summary>Expand</summary>

- **"Alik"** - UAV operator, 93rd OMBr "Black Ravens", AFU 🇺🇦
- **"Ivan"** - ex-UAV operator, 427th Unmanned Aerial Brigade "Rarog", AFU 🇺🇦
- **Meshtastic** - the mesh firmware the stations relay over

</details>
