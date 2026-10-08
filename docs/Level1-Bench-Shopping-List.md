# Level 1 station v3 — bench and station shopping list

What to buy for the bench campaign and the station, in the order the sessions
of `docs/Level1-Bench-Run-Order.md` need it. The bench guide's sheet 10 ("Bench
kit — what each piece is for") refers to the tiers below. Written 2026-10-08
from a list another session drafted, reviewed against the firmware's wideband
path, the Data Plan's stage 8 rules and the products' current listings. Two
constraints from the user shape Tier 1: no goggles unless unavoidable, and no
large purchases. Prices are approximate USD in October 2026, marked ≈; search
phrases are generic terms for AliExpress-style marketplaces, not listings.
Specs move: check the maker's page before ordering.

## Tier 0 — buy now (sessions B to G, stages 0–7)

| Item | What matters | Pick (≈ USD) | Search |
|---|---|---|---|
| Analog 5.8 GHz VTX | Full 40 or 48 channels, so E4 (5645) and E8 (5945) exist: session B's edge test needs them, and 37-channel "US" units (AKK X2, FXT Ares) drop E4, E7 and E8. Pit mode and a 25 mW setting. Any antenna connector: MMCX or u.FL with an adapter is fine. 5 V input preferred, so a USB power bank runs it outdoors in session D | **SpeedyBee TX800** ≈ 25: 48 channels over six bands (the sixth is the L band the `LOWBAND` plan scans), PIT / 25 / 200 / 400 / 800 mW, 3.7–5.5 V in, 5 V / 250 mA out for the camera, MMCX-to-SMA adapter in the box. Ships locked to 25 mW with some channels hidden: do the 10 s unlock press before session B. One shop lists it as discontinued, others stock it. Fallbacks: **Eachine TX805** ≈ 15–20 (40 channels, pit mode, an LED panel shows band, channel and power, MMCX pigtail to SMA in the box, needs 7–24 V: a 2S–3S LiPo or a 12 V adapter); **TBS Unify Pro32 Nano** ≈ 30–35 (5 V, u.FL, pit mode, no L band, needs a u.FL–SMA pigtail) | '5.8GHz analog VTX 48CH pit mode' |
| FPV camera | NTSC and PAL switchable from its own OSD, so one camera covers session B now and stage 4's NTSC and PAL runs later (the Data Plan's "one NTSC and one PAL camera" is met by switching it) | **Caddx Ratel 2** ≈ 25–30: the menu board is in the kit; 5–40 V in. The RunCam Phoenix 2 is as good but its OSD key board is sold separately | 'FPV camera NTSC PAL switchable' |
| Attenuation | B1c needs `clip` 0.0 at gain 62, which 25 mW indoors never reaches by distance alone; stage 5's level record and the skirt record use the same set | Fixed SMA attenuators, DC–6 GHz, 2 W: **10, 20 and 30 dB**, plus two SMA female–female barrels, ≈ 20–30 in all (add 3 and 6 dB for 3 dB steps). A rotary step attenuator rated to 6 GHz costs 150 and up and is not needed; the common 0–90 dB rotary units stop at 2.4 GHz and are useless here | 'SMA fixed attenuator 6GHz 2W 30dB' |
| u.FL–SMA pigtail | Stage 5's attenuator chain into the XIAO and session D's patch. The station needs four of equal length ≤ 15 cm; one now | ≈ 3 | 'u.FL IPEX to SMA female pigtail' |
| VTX power | TX800: a USB power bank and a USB-A to bare-wire lead, ≈ 5. TX805: a 2S–3S LiPo with an XT30/XT60 lead, or a 12 V adapter | | |
| 5 GHz Wi-Fi router + laptop | Probably owned. Session C's idle and loaded access point (an AP on Wi-Fi 36 for D1, then under iperf or a long file copy): idle Wi-Fi must never be reported, a saturated link reads `dot11` with `duty` ≥ 90. This is the free source of the 802.11 class; a video stream over it is the bursty negative control | Any dual-band router that can be forced onto 5 GHz channels 36 and 149–165 | — |

Nothing in Tier 1 stands in for the analog VTX: session B passes on FM-carrier
features (`q_phase` ≥ 50, `cv2` < 0.3, `mod` 1, a steady `cfo_khz`) and every
digital kit is noise-like on exactly those, by design.

## Tier 1 — stage 8 (session H), in purchase order under the constraints

Ordered by cost per settled question. The one stage 8 result that changes
code if it is wrong is the DJI `lte` class (Data Plan, "Class, DJI O4": a
symbol period other than 66.7 µs renames the feature, a session's work), and
that is reachable at no cost. Keep any analog VTX off, or more than 30 MHz
from the kit's channel, during stage 8 (`WB_ANALOG_OWN_MHZ`).

| # | Kit (≈ USD) | What it settles | Constraints / notes | Search |
|---|---|---|---|---|
| 1 | **Borrowed DJI consumer drone** with OcuSync 3 or 4 (Mini 3, Mini 4, Air 3) and its controller (0) | The `lte` class: `r2667` ≥ 0.03, `r128` < 0.05, `scan_lag` 2665–2669; the mapper's OcuSync rows by class and bucket | Force 5.8 GHz in DJI Fly's transmission settings; the drone links to its controller, no goggles involved. The O4 Air Unit's own centres (5768.5 / 5789.5 / 5794.5 / 5814.5) stay unverified until an air unit is tested; that waits for the pilot-presence work, where goggles become unavoidable, because an air unit transmits only once linked | — |
| 2 | **HDZero kit** (≈ 100): Race V3 VTX (40–50, 25 / 200 mW) + an HDZero camera, Nano Lite or Micro V3 (25–30) + the HDZero keyboard (25) or any Betaflight flight controller | HDZero's waveform: `cls`, bucket (17 MHz narrow mode, 27 MHz mode) and `scan_lag`; "whatever it reads is the result". The one system that might pass the analog gate as `cw`, a design item | One-way broadcast: transmits with no receiver and no goggles, the cheapest digital emitter. Race V3 and Freestyle V2 take MIPI cameras only; an analog camera needs the separate HDZero analog adapter (≈ €45, NTSC only, VTX firmware 1.7.1 or later), which costs more than an HDZero camera. No goggles-side control: channel and power are set by the keyboard (a fragile 1.25 mm connector) or by a flight controller over MSP. Whether the VTX transmits with no camera is unconfirmed: fit the camera | 'HDZero Race V3', 'HDZero Nano Lite camera', 'HDZero keyboard' |
| 3 | **OpenIPC / wfb-ng emitter** (≈ 70–100): an OpenIPC camera board (SSC338Q class) with one RTL8812AU or RTL8812EU adapter, or the turnkey RunCam WiFiLink 2 | The `dot11` class on a real video link (`r128` ≥ 0.10, `scan_lag` 128; 256 would mean a 10 MHz half-clocked mode), `WB_R128_MIN`, the digital K, and the `duty` split between the "802.11 video link" and "Wi-Fi traffic" mapper rows, together with stage 3's loaded access point | wfb-ng video is a one-way broadcast: the emitter runs with no ground station. A second adapter (20–40) and a Linux host with svpcom's patched drivers (the project's tested pair is two ALFA AWUS036ACH, RTL8812AU; RTL8812EU is the cheaper newer chip) only let you watch the video; the Windows bench PC cannot be that host. The level 1 firmware never decodes frames (promiscuous mode with an empty filter only keeps the PHY receiving; the wideband path reads symbol timing from I/Q), so STBC or LDPC support in the C5 is not a level 1 question | 'OpenIPC camera RTL8812AU', 'RunCam WiFiLink 2' |
| 4 | **Walksnail Avatar VTX** (100) + Avatar VRX module (130), deferred | Class and bucket on 5770 / 5839, and 5914 if the synthesizer pull reaches it | The VTX streams only once bound to a VRX or goggles, and the VRX sets the channel. Units ship in SRRC mode (4 channels) and need the region file for the 8-channel FCC grid the mapper rows use. Lowest uncertainty of the four: buy when a VRX is justified | 'Walksnail Avatar VTX', 'Walksnail Avatar VRX' |

Ruled out for now: the DJI O4 Air Unit + Goggles N3 pair (≈ 330), inert
without the goggles; item 1 covers the class, the pair returns with the
pilot-presence work. HDZero goggles, Walksnail goggles and DJI Goggles 3 are
never needed for the bench. A camera that serves both the analog VTX and
HDZero exists (Foxeer Digisight 2 Nano, ≈ 64) but it needs a flight controller
wired in to switch modes and was out of stock at two sellers; a Ratel 2 plus a
Nano Lite is cheaper.

## Tier 2 — the dual-band station variant (when that build reaches the bench)

| Item | Constraints / notes | Search |
|---|---|---|
| 4 × dual-band directional patch or panel antennas, one batch, identical | Directional (not omni, dipole or cloverleaf), covering 2.4–2.5 GHz and 5.6–5.95 GHz, 6–9 dBi, roughly 60–90° beamwidth, SMA (or RP-SMA with adapters, consistently). Linear or circular polarisation both fine if all four match | 'dual band 2.4 5.8 GHz patch antenna directional SMA' |
| Wideband LNA (optional) | 2.4–6 GHz, 15–20 dB gain, 3.3 V or 5 V, SMA in and out, no band-pass filter (a 5.8 GHz filter would block 2.4 GHz). Fit only if a station proves deaf | 'LNA 0.1-6GHz 20dB SMA' |
| 2.4 GHz analog VTX (≈ 20) | The stage 1 source on 2.4 GHz, keyed on G3, and the stage 5 attenuator sweep on a G channel | '2.4GHz analog FPV VTX SMA' |
| Borrowed DJI consumer drone, OcuSync 3 or 4 | The real two-band DJI waveform for the 2.4 GHz block: the same unit as Tier 1 item 1 | — |

## Existing station parts — generic alternatives and their constraints

| Part | Generic alternative and constraints | Search |
|---|---|---|
| 5.8 GHz patch antennas × 4 | Any directional patch or panel covering 5.6–5.95 GHz, 7–9 dBi, about 70° beamwidth, SMA; one batch of four identical units; polarisation free but identical | '5.8GHz patch antenna 8dBi SMA directional' |
| SP4T RF switch | PE42442 (recommended, evaluation board) or any SP4T covering 6 GHz or more with 2- or 3-line decoded control at 3.3 V logic, ≤ 2 dB insertion loss, ≥ 20 dB isolation. A one-hot 4-line part (SKY13322-375LF) works only with the external NOR gate the README describes | 'PE42442 evaluation board', 'SP4T RF switch 6GHz SMA' |
| u.FL–SMA pigtails × 4; u.FL–u.FL | u.FL–SMA: equal length ≤ 15 cm. u.FL–u.FL: ≤ 5 cm. Any brand; equal length matters more than brand | 'u.FL IPEX to SMA female pigtail', 'u.FL to u.FL cable' |
| 5.8 GHz LNA + band-pass filter (optional, single-band stations only) | About 20 dB, 5.6–5.95 GHz pass band, 3.3 V or 5 V. Not for the dual-band variant | '5.8GHz LNA band pass filter SMA' |
| Heltec WiFi LoRa 32 V4 (standard OLED model, your region's band) | No generic substitute: the mesh firmware and pinout depend on it | 'Heltec WiFi LoRa 32 V4' |
| Seeed XIAO ESP32-C5 | No substitute: the receiver trick depends on this exact chip and module | 'Seeed XIAO ESP32-C5' |

## Do not buy

A Raspberry Pi + SDR (ruled out as a station); 1.2 / 1.3 GHz receivers (no
receiver path for them yet); any goggles (DJI Goggles 3, HDZero, Walksnail;
the N3 only with the air unit, later); a 37-channel VTX; a rotary step
attenuator rated below 6 GHz.

## Product pages checked (2026-10-08)

SpeedyBee TX800: <https://oscarliang.com/speedybee-tx800/>,
<https://www.readymaderc.com/products/details/86351-speedybee-tx800-20x20-25-800mw-5-8ghz-vtx-mmcx>.
Eachine TX805: <https://oscarliang.com/eachine-tx805-vtx/>.
TBS Unify Pro32 Nano: <https://www.team-blacksheep.com/products/prod:unifypro32_nano>.
Caddx Ratel 2: <https://www.racedayquads.com/products/caddx-ratel-2-1200tvl-16-9-4-3-ntsc-pal-micro-fpv-camera>.
HDZero Race V3: <https://www.getfpv.com/hdzero-race-v3-digital-hd-video-transmitter.html>;
analog adapter: <https://www.rotorama.com/product/hdzero-adapter>;
keyboard: <https://kiwiquads.co.nz/product/hdzero-keyboard/>.
Walksnail Avatar VRX: <https://caddxfpv.com/blogs/news/walksnail-avatar-vrx-hdmi-digital-fpv-receiver>.
wfb-ng: <https://github.com/svpcom/wfb-ng>; OpenIPC ground station:
<https://docs.openipc.org/use-cases/fpv/wfb-ng/groundstation-ubuntu/>;
RunCam WiFiLink 2: <https://pyrodrone.com/collections/digital-vtx/products/runcam-wifilink-2-hd-1080p-90fps-video-system-based-on-openipc-choose-version>.
