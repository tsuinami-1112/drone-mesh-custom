# Drone WiFi/BLE fingerprints and international Remote ID regimes

Research reference for drone-mesh-5plus (ESP32 WiFi-promiscuous + BLE nodes, LoRa relay, Python map server).
Compiled 2026-10-02 from web sources; nothing in the repository was modified.

Confidence legend used throughout:

- **IEEE-verified** – prefix looked up individually in the IEEE registry mirror (maclookup.app API / vendor page, which mirrors MA-L/MA-M/MA-S from standards-oui.ieee.org).
- **Vendor-documented** – appears in a vendor manual, FCC filing or official support page.
- **Community** – reported by open-source detectors (Kismet `kismet_uav.conf`, friendorfoe, intercept, Fieldwatch/BlueWatch) or forums; not independently verified here.
- **Debunked** – circulated in community lists but IEEE lookup shows a different owner.

Block-size notation: `XX:XX:XX` = MA-L (/24). `XX:XX:XX:X` = MA-M (/28, first 7 hex digits). `XX:XX:XX:XX:X` = MA-S or IAB (/36). A detector must mask to the right length; a bare /24 match on an MA-M/MA-S parent (e.g. `70:B3:D5` = IEEE Registration Authority) is meaningless.

---

## PART 1 – WiFi / BLE fingerprints of drones and controllers

### 1a. IEEE MAC prefixes (OUI / MA-M / MA-S) registered to drone makers

#### DJI family (all MA-L, all IEEE-verified)

| Prefix | Registrant (exact IEEE name) | Registered | Notes / also used by |
|---|---|---|---|
| 60:60:1F | SZ DJI TECHNOLOGY CO.,LTD | 2013-03-11 | Oldest; Phantom 3, Spark, Mavic Pro/Air, Tello (Ryze uses DJI silicon: Kismet matches `^TELLO.*` on 60:60:1F), Osmo gimbals, Goggles. **Shared with non-aircraft DJI products -> "possible"** unless SSID/BLE confirms. |
| 34:D2:62 | SZ DJI TECHNOLOGY CO.,LTD | 2019-08-13 | Mavic Mini / Mini 2 era, RC-N1, Osmo Pocket/Action. Shared. |
| 48:1C:B9 | SZ DJI TECHNOLOGY CO.,LTD | 2022-05-07 | Mini 3/Mavic 3 era, DJI RC, Goggles 2. Shared. |
| E4:7A:2C | SZ DJI TECHNOLOGY CO.,LTD | 2023-10-19 | Shared. |
| 58:B8:58 | SZ DJI TECHNOLOGY CO.,LTD | 2024-07-26 | Shared. |
| 04:A8:5A | SZ DJI TECHNOLOGY CO.,LTD | 2025-01-09 | Shared. |
| 8C:58:23 | SZ DJI TECHNOLOGY CO.,LTD | 2025-05-27 | Shared. |
| 0C:9A:E6 | SZ DJI TECHNOLOGY CO.,LTD | 2025-08-14 | Shared. |
| 88:29:85 | SZ DJI TECHNOLOGY CO.,LTD | 2025-10-29 | Shared. |
| 4C:43:F6 | SZ DJI TECHNOLOGY CO.,LTD | 2025-12-01 | Shared. |
| 9C:5A:8A | DJI BAIWANG TECHNOLOGY CO LTD | 2024-12-30 | DJI subsidiary (Baiwang = DJI's Shenzhen manufacturing arm); products not identified. Label "DJI (possible)". |
| EC:72:F7 | DJI BAIWANG TECHNOLOGY CO LTD | 2026-03-06 | Same. |
| F8:40:68 | SZ DJI Ronin Technology Co., Ltd. | 2026-04-03 | **Gimbals/cine (Ronin, Osmo Pro?)** – almost certainly non-aircraft -> "accessory". |
| 20:1F:55 | DJI Osmo Technology Co., Ltd. | 2026-05-13 | **Osmo handhelds/cameras** -> "accessory". |

Sources: maclookup.app vendor page `https://maclookup.app/vendors/sz-dji-technology-co-ltd` (10 prefixes) and per-prefix API `https://api.maclookup.app/v2/macs/<prefix>` for the four subsidiary prefixes; Kismet `conf/kismet_uav.conf` for the 60:60:1F model matches. The DJI subsidiary prefixes were first seen in the friendorfoe `wifi_oui_database.c` community list and then IEEE-verified here.

Not registered: **Ryze Tech** has no IEEE prefix (maclookup "No results for vendor name: ryze tech"); Tello/RMTT units carry DJI 60:60:1F.

#### Parrot (all MA-L, IEEE-verified)

| Prefix | Registrant | Registered | Notes |
|---|---|---|---|
| 00:12:1C | PARROT SA | 2004-08-14 | Pre-drone era: Bluetooth car kits, Zik headphones, Parrot Flower Power. **Low drone prior**; needs SSID. |
| 00:26:7E | PARROT SA | 2010-01-05 | AR.Drone 1.0/2.0 (Kismet `^ardrone[^2].*` / `^ardrone2.*`); also consumer audio. |
| 90:03:B7 | PARROT SA | 2011-11-13 | AR.Drone 2.0 (Kismet). Also Zik 2.0 headphones. |
| A0:14:3D | PARROT SA | 2013-07-29 | Bebop, Bebop 2, Jumping Sumo, SkyController (Kismet). Also Zik 3, Parrot Pot. |
| 90:3A:E6 | PARROT SA | 2016-04-27 | Bebop 2 (Kismet), Disco, ANAFI generation. Mostly drones (Parrot exited consumer audio 2017). |

Source: `https://maclookup.app/vendors/parrot-sa`; Kismet uav_match lines. Parrot stopped non-drone products in 2017, so 90:3A:E6 is the "cleanest" prefix; the two oldest prefixes are heavily shared with audio products.

#### Other manufacturers with IEEE registrations (all IEEE-verified via API / vendor page)

| Prefix (mask) | Registrant (exact IEEE name) | Type | Registered | Product family / notes |
|---|---|---|---|---|
| 38:1D:14 | Skydio Inc. (114 Hazel Ave, Redwood City CA) | MA-L | 2019-07-02 | Skydio 2/2+/X2/X10 aircraft, controllers, Beacon, Dock. Only Skydio prefix. |
| EC:5B:CD:E (/28) | Autel Robotics USA LLC (Bothell WA) | MA-M | 2024-05-17 | Only Autel Robotics registration found. Older EVO/EVO II hardware predates it and uses module OUIs. **"Autel Intelligent Technology Corp., Ltd"** (the automotive-diagnostics parent) is a different registrant; do not label it as drone. SkySafe (Feb 2024) also observed a **fixed MAC across all Autel RID beacons**. |
| E0:B6:F5:8 (/28) | Yuneec International（China）Co.，Ltd | MA-M | 2016-02-05 | Typhoon H / H520 / Mantis era. Only Yuneec registration. |
| 98:AA:FC:7 (/28) | Shenzhen Hubsan Technology Co.，LTD. | MA-M | 2017-01-07 | Zino / H501A WiFi era. Only Hubsan registration. |
| 84:83:19 | Hangzhou Zero Zero Technology Co., Ltd. | MA-L | 2016-03-01 | Hover Camera Passport / HOVERAir X1 (Zero Zero Robotics). |
| C8:63:14:4 (/28) | Shenzhen Zero Zero Infinity Technology Co.，Ltd. | MA-M | 2019-01-23 | Zero Zero Robotics (second legal entity). |
| 6C:DF:FB:E (/28) | Beijing Fimi Technology Co., Ltd. | MA-M | 2019-07-02 | FIMI X8 SE/Mini/Tele. Older FIMI/Xiaomi Mi Drone units use **Xiaomi** OUIs (e.g. 9C:99:A0 = Xiaomi Communications Co Ltd, 2016) which are **unusable** – see Xiaomi below. |
| 54:7D:40 | Powervision Tech Inc. (Weihai, Shandong) | MA-L | 2021-08-10 | PowerEgg X, PowerDolphin/PowerRay (water robots) -> label "possible". |
| B0:30:C8 | Teal Drones, Inc. (Holladay UT) | MA-L | 2020-06-06 | Teal 2 / Golden Eagle (Red Cat subsidiary). |
| EC:71:5E | Freefly Systems Inc | MA-L | 2026-03-31 | Astro/Alta aircraft and Movi gimbals -> "possible". |
| A8:B0:28 | CubePilot Pty Ltd | MA-L | 2023-01-19 | Herelink air/ground units, Cube autopilots, Here GNSS. **Herelink ground unit is a controller** (Android hotspot). "Hex Technology Limited" has no separate registration. |
| AC:86:D1:7 (/28) | Quantum-Systems GmbH | MA-M | 2024-07-09 | Trinity / Vector / Twister. |
| E8:B4:70:C (/28) | Anduril Industries (Irvine CA) | MA-M | 2020-02-21 | Ghost / Altius (military). |
| 14:DD:48 | Shield AI | MA-L | 2025-12-18 | V-BAT / Nova. Note: "Shield Inc." 98:FC:84:A is a **Taipei** company, not Shield AI (debunk). |
| 74:B8:0F | Zipline International Inc. | MA-L | 2023-04-20 | Delivery UAS. |
| 00:1A:F9 | AeroVIronment (AV Inc) | MA-L | 2007-01-06 | Raven/Puma era (military). |
| 00:50:C2:C3:5, 00:50:C2:FD:4 (/36 IAB); 70:B3:D5:7A:D, 70:B3:D5:86:5, 70:B3:D5:B3:B, 70:B3:D5:D3:6, 70:B3:D5:DD:2 (/36 MA-S) | Insitu, Inc | IAB / MA-S | 2011–2019 | ScanEagle/Integrator ground segments. Parent /24s (00:50:C2, 70:B3:D5) belong to the IEEE RA – match 36 bits only. |
| 70:B3:D5:48:2 (/36) | Aeryon Labs Inc | MA-S | 2016-11-29 | SkyRanger (now Teledyne FLIR). |
| 28:F5:37:D (/28) | Skyrockettoys LLC | MA-M | 2017-07-23 | Sky Viper toy drones (Skyrocket). |
| 9C:4B:6B | iFlight Technology Company Limited | MA-L | 2024-12-27 | FPV components (Blitz VTX/ELRS, Defender) -> "accessory/FPV". |
| F0:55:82 | Arashi Vision Inc. (Insta360) | MA-L | 2025-10-21 | **Cameras, not drones** -> "accessory". Older Insta360 use module OUIs. |
| 04:41:69, 04:57:47, 24:74:F7, AC:04:AA, D4:32:60, D4:D9:19, D8:96:85, F4:DD:9E | GoPro | MA-L | 2011–2024 | HERO cameras; Karma drone/controller (2016-18) sat in this space -> "accessory/possible". Source: `https://maclookup.app/vendors/gopro`. |

#### Xiaomi (mark as UNUSABLE for drone attribution)

- Xiaomi Communications Co Ltd: **238** MA-L prefixes; Beijing Xiaomi Mobile Software Co., Ltd: **74**; Beijing Xiaomi Electronics Co., Ltd.: **20** (maclookup vendor pages). These are phones, routers, scooters, IoT. Mi Drone 4K / early FIMI used e.g. 9C:99:A0 (Xiaomi Communications). Only an SSID/BLE-name match may promote a Xiaomi MAC to "possible drone".

#### Vendors with NO IEEE registration found (use SSID/BLE patterns only)

Checked by vendor-page slug and web search on maclookup.app (which mirrors IEEE MA-L/MA-M/MA-S/IAB/CID): Ryze, Walkera, Syma, JJRC, UDI/Udirc, Cheerson, MJX, SJRC, Eachine/Banggood, Holy Stone, Potensic, Snaptain, Ruko, Wingsland, XK, Skydroid, SIYI, Hex Technology, Holybro, Hobbywing, FrSky, Flysky, Horizon Hobby/Spektrum, Fat Shark, Skyzone, RunCam, Caddx/Walksnail, Team BlackSheep, Wingtra, senseFly, Flyability, Microdrones, Volocopter, Wing Aviation, Auterion, Draganfly, Vantage Robotics, Blue Vigil, Spin Master/Air Hogs, Percepto, Matternet, Ehang, XAG, Zerotech, 3D Robotics (Solo's "SoloLink" AP in Kismet is 8A:DC:96 – a locally-administered address, not an OUI). Toy/hobby brands buy WiFi modules, so their BSSIDs fall under module makers (next table) or are randomised.

#### WiFi-module OUIs that toy drones ride on (Kismet pairs them with SSID regexes; **never match on OUI alone**)

| Prefix | IEEE registrant (verified) | Seen on (Kismet uav_match) |
|---|---|---|
| 58:04:54 | ICOMM HK LIMITED | Syma `^FPV_WIFI__[0-9A-F]{4}$` |
| 4C:0F:C7 | Earda Technologies co Ltd | Propel Sky Rider, 360-L Flight, Attop YD-UFO |
| 24:72:60 | IOTTECH Corp | Propel Sky Rider Night Hawk `^Sky Rider Vox-.*` |
| E0:B9:4D, EC:3D:FD, 28:F3:66, 08:EA:40 | SHENZHEN BILIAN ELECTRONIC CO.，LTD (LB-Link) | Propel HD Video Drone, 360 Flight, Attop YD-UFO, XBM-720P |
| 00:7E:56 | China Dragon Technology Limited | Attop YD-UFO |
| B0:41:1D | ITTIM Technologies | Attop YD-UFO |
| E8:AB:FA | Shenzhen Reecam Tech.Ltd. | Attop YD-UFO (also IP cameras) |
| 90:97:D5 | Espressif Inc. | XBM-720P (ESP32/8266 toy FPV modules; also every ESP IoT device) |

#### Community OUIs that are WRONG (debunked by IEEE lookup) – do not import

From `smittix/intercept data/patterns.py` DRONE_OUI_PREFIXES: E0:DB:55 = Dell Inc.; C8:6C:87 = Zyxel; 8C:F5:A3 = Samsung Electro-Mechanics; D8:E0:E1 = Samsung Electronics; F8:0F:6F = Cisco; 70:D7:11 and 98:3A:56 = unassigned. Also "A0:14:3D = DJI" there is wrong (it is Parrot).

#### Non-IEEE vendor identifiers carried inside 802.11 beacons (highest-value fingerprints for non-RID aircraft)

| Identifier | Meaning | Source |
|---|---|---|
| IE 221 vendor-specific, OUI **26:37:12**, sub-command 0x10 (telemetry) / 0x11 (flight info) | **DJI DroneID over WiFi** – emitted by WiFi-link DJI aircraft (Spark, Mavic Air, Mavic Mini, Mini 2/SE, Tello-class, Phantom 3 Standard) alternating every ~200 ms. 0x10 carries 16-byte serial, drone lat/lon, altitude/height, velocities, pitch/roll/yaw, **home lat/lon**, product_type, UUID, (V2) GPS time + **app/pilot lat/lon**. 0x11 carries serial, 10-byte "drone ID" and purpose text. 26:37:12 is NOT in the IEEE registry (API returns found=false). | Kismet `dot11_parsers/dot11_ie_221_dji_droneid.h` (vendor_oui 0x263712), `kaitai_definitions_disabled/dot11_ie_221_dji_droneid.ksy`; RUB-SysSec DroneSecurity; AerixRF research briefs. |
| IE 221 vendor-specific, OUI **FA:0B:BC**, type **0x0D** | ASTM F3411 / ASD-STAN **Open Drone ID WiFi Beacon** message pack (what the project already decodes). | opendroneid-core-c README; transmitter-linux `wifi_beacon.c`. |
| BLE AD type 0x16 Service Data, UUID **0xFFFA**, app code **0x0D** | Open Drone ID over BT4 legacy and BT5 Long Range (extended advertising, LE Coded PHY). | opendroneid-core-c README. |
| DJI OcuSync DroneID (2.4/5.8 GHz proprietary OFDM, not WiFi) | Carries serial, position, home, pilot position; needs SDR – out of scope for ESP32. | RUB-SysSec DroneSecurity (NDSS 2023). |

### 1b. WiFi SSID patterns

Role: A = aircraft AP, C = controller / ground unit AP, X = accessory (camera, gimbal, goggles). Confidence: H = vendor manual/Kismet, M = multiple forum reports, L = single/unclear report or inferred.

| Regex (case-sensitive unless `(?i)`) | Vendor / model | Role | Conf. | Source |
|---|---|---|---|---|
| `^Phantom3_` | DJI Phantom 3 Standard/4K | A | H | Kismet |
| `^Mavic-[0-9A-F]{6}$`, `^Mavic_` | DJI Mavic Pro (RC WiFi mode) | A/C | H | Kismet |
| `^Spark-(?!RC-)` | DJI Spark aircraft | A | H | Kismet |
| `^Spark-RC-` | DJI Spark remote | C | H | Kismet |
| `^DJI-MAVIC3` | DJI Mavic 3 (QuickTransfer) | A | H | Kismet |
| `^DJI-MINI3-Pro-` | DJI Mini 3 Pro (QuickTransfer) | A | H | Kismet |
| `^DJI[-_ ]` (generic), e.g. `DJI-MINI2-`, `DJI-AIR2S-`, `DJI NEO…`, `DJI-FPV-` | DJI Mini 2/SE, Air 2S, Neo, Flip, Avata, FPV goggles (QuickTransfer / phone-control hotspots) | A/X | M | friendorfoe, intercept, DJI Fly connection guides (Neo shows as "DJI NE…"); exact suffixes vary |
| `^Mavic Mini-`, `^MAVIC-MINI-`, `^Mini-`, `^Air-` | DJI Mavic Mini / Mini SE | A | L | intercept list |
| `^TELLO-`, `^TELLO` | Ryze Tello (DJI OUI 60:60:1F) | A | H | Kismet `^TELLO.*` |
| `^RMTT-` | Ryze/DJI RoboMaster Tello Talent | A | M | community (requested by task; not Kismet) |
| `^OSMO_`, `^OsmoPocket`, `^OsmoAction`, `^Ronin` | DJI handheld gimbals/cameras | X | H/L | Kismet `^OSMO_.*`; others community |
| `^ardrone2`, `^ardrone(?!2)` | Parrot AR.Drone 2.0 / 1.0 | A | H | Kismet |
| `^BebopDrone`, `^Bebop2` | Parrot Bebop / Bebop 2 | A | H | Kismet |
| `^JumpingSumo-` | Parrot Jumping Sumo (ground robot) | – | H | Kismet |
| `^SkyController` | Parrot SkyController 1/2/3 | C | H | Kismet |
| `^ANAFI-`, `^AnafiUSA-`, `^ANAFI Ai` | Parrot ANAFI / ANAFI USA / Ai | A | H/M | Parrot ANAFI USA user guide ("AnafiUSA-X######"), Parrot developer docs ("ANAFI-xxxxxx") |
| `^Disco-` | Parrot Disco | A | M | community/ARSDK naming |
| `^Mambo_`, `^Swing_` | Parrot Mambo FPV / Swing (WiFi variants) | A | H | pyparrot docs ("Mambo_number") |
| `^Skydio` (e.g. `Skydio-XXXX`, `Skydio###`) | Skydio 2/2+ aircraft (Beacon shows "Connected to Skydio-XXXX") | A | H | Skydio support, Beacon FCC user guide |
| `(?i)^autel`, `^EVO[- _]`, `^Lite\+`, `^Nano` | Autel EVO/Lite/Nano image-transfer WiFi (password 12345678) | A | L | intercept list, autelpilots forum (no SSID quoted) |
| `^default-ssid$` | Autel **Remote ID WiFi beacon** (misconfigured SSID, fixed MAC) | A | M | SkySafe Feb-2024 compliance study |
| `^Breeze_` | Yuneec Breeze | A | H | yuneecpilots ("Breeze_xxxxxx", last 6 MAC digits) |
| `^CGO3_`, `^CGOE10T_`, `^CGO3P` | Yuneec CGO3/CGO3+ camera (Typhoon Q500/H) | A (camera on aircraft) | M | yuneecpilots |
| `^Mantis_`, `^MantisQ_` | Yuneec Mantis Q/G | A | H | Mantis Q manual / forum |
| `(?i)^hubsan[ _-]`, `^HUBSAN_H501A_`, `^Hubsan[ _]Zino_` | Hubsan H501A, Zino, Zino 2 | A | H | H501A manual, Hubsan forum/tutorial |
| `^HolyStoneFPV[-_]`, `^HolyStone-`, `(?i)^HS[0-9]{3}` | Holy Stone (HS110/HS120D/HS165/HS210/HS510/HS710…) | A | H/M | Holy Stone manuals, h120d-protocol repo |
| `^Potensic`, `^Potensic D_`, `^Dreamer 1_` | Potensic D-series / Dreamer | A | H | Potensic manuals (FCC 2AYUO-A21) |
| `(?i)^snaptain-` (e.g. `Snaptain-S5C-`, `Snaptain-Ex0-`, `SNAPTAIN-A15-`) | Snaptain | A | H | Snaptain manuals |
| `(?i)^ruko[-_]` (e.g. `RUKO-F11-…-5G`, `Ruko-F11PRO-`, `Ruko_F11_Mini_5G-`, `RUKO-GIM-`) | Ruko F11 family | A | H | Ruko manuals |
| `^SJRC-`, `^SJ-F11`, `^SJ F` | SJRC F11/F22/Z5 (same ODM as Ruko F11) | A | M | SJRC manual summaries |
| `^FIMI`, `^Xiaomi_FIMI`, `^X8`, `^amba_boss$` | FIMI X8 SE/Mini/Tele ("amba_boss" is the Ambarella default in firmware dumps) | A | L | FIMI forum, FimiX8-SDFG |
| `^MiDrone_` | Xiaomi Mi Drone 4K | A | M | manuals/community |
| `^EggX_` | PowerVision PowerEgg X | A | H | PowerEgg X user manual |
| `^HoverX1_`, `^Hover` | Zero Zero HOVERAir X1 (also BLE pairing) | A | H | HOVERAir quick-start / support |
| `^Vitus-Air-` | Walkera Vitus aircraft | A | H | Walkera FAQ |
| `^Vitus-Ground-`, `^WK-GRD-` | Walkera Vitus ground unit / WK-V8 controller | C | H | Walkera FAQ, FCC S29WK-V8 |
| `^WINGSLANDs6_air_` | Wingsland S6 | A | H | S6 user manual |
| `^FPV_WIFI__[0-9A-F]{4}$`, `^FPV WIFI` | Syma X5SW/X8PRO class (ICOMM module) | A | H | Kismet, Syma manuals |
| `^SYMA` | newer Syma (Syma Fly app) | A | L | intercept list |
| `^JJRC-` | JJRC H-series | A | M | Amazon Q&A/forums |
| `^udirc-` | UDI RC U818A/U845 | A | H | UDI manuals |
| `^CX-10W-`, `^CX-10WD_` | Cheerson CX-10W/WD | A | M | reviews/manuals |
| `^Bugs`, `^MJX` | MJX Bugs 4W/5W/B2W | A | M | MJX manual ("find Bugs in WiFi list") |
| `^SoloLink_` | 3DR Solo controller link | C | H | Kismet |
| `^Propel Sky Rider$`, `^Sky Rider Vox-`, `^Propel HD Video Drone$`, `^360(-L)? Flight-` | Propel / Sky Rider toys | A | H | Kismet |
| `^YD[_-]UFO[_-]`, `^YD-1080-UFO-` | Attop / E58 clones ("UFO" family) | A | H | Kismet, E58 reviews |
| `^XBM-720P-`, `^WiFi-720P-`, `^WI-FI 720P`, `^WI-FI UFO`, `^WiFi_UFO`, `^Wi-?Fi_[0-9A-F]{6}$` | Eachine E58/E88/E99 and generic Shantou toy drones (JY UFO / WiFi UFO apps) | A | M | Kismet, Gadgeteer E58 review, Visuo XS809 manual, E88/E99 guides |
| `^KY-` | KY601/KY-series (KY FPV app) | A | M | forum |
| `(?i)^(SG90[0-9]|ZLRC|GD89|LS-|F11|E88|E99|XS809)` | ZLL SG906, Global Drone GD89, LS-MIN/XT6, Visuo XS809 etc. | A | L | brand naming only – **collect real captures before enabling** |
| `(?i)(drone|quadcopter|uav|fpv)` | generic catch-all | ? | L | community lists – high false-positive rate, use for "possible" only |
| `^HDZero$` | HDZero goggles WiFi AP (password "divimath"), also HDZero BoxPro | X | H | HDZero goggle manual / docs.hd-zero.com |
| Walksnail Goggles X WiFi (2.4 GHz, password 12345678; SSID not documented) | Caddx/Walksnail | X | L | Oscar Liang review, Caddx firmware notes |
| DJI Goggles 2/Integra/3 (WiFi 802.11ac + BLE 5.x; SSID shown in DJI Fly) | DJI | X | L | DJI specs |
| Fat Shark / Skyzone goggles | – | X | – | no WiFi/BLE radios in mainstream models; nothing to fingerprint |
| `^RunCam`, `^Peanut`, `^Caddx` | RunCam/Caddx WiFi cameras | X | L | product naming |
| `^GP[0-9]{8}$`, `^GoProHero` | GoPro cameras (Karma era) | X | H | GoPro support |
| `^RID[-_ ]?[0-9A-Z]{4,}`, `^ODID[-_ ]`, `^OpenDroneID`, `^RemoteID` | Remote-ID add-on beacons (ArduRemoteID, hobby modules) – already RID, but SSID helps identify module type | A | M | friendorfoe regex, ArduRemoteID defaults |

### 1c. Bluetooth LE

#### Bluetooth SIG Company Identifiers (manufacturer-specific data, AD type 0xFF)

Verified against two independent mirrors of the SIG `company_identifiers.yaml` (bluekitchen/btstack `bluetooth_company_id.h`, GoogleChrome/samples datalist, SAR_BT_Scan generated 2025-09-02, finitelabs/control4-esphome). Ascending coverage to 0x0B1C plus descending coverage to 0x07FF = full table.

| Company ID | Name in SIG registry | Use |
|---|---|---|
| **0x08AA** (2218) | SZ DJI TECHNOLOGY CO.,LTD | All DJI BLE radios (aircraft QuickTransfer/phone-control, RC-N1/N2/RC/RC Pro, Goggles 2/3, Osmo, OM, Mic, RoboMaster). Fieldwatch/BlueWatch decode the first u16 LE of the payload as a **model id**: Osmo cameras 0x0006–0x0022; aircraft e.g. Mavic 3 = 0x0070, Neo 2 = 0x007E. Treat bare 0x08AA as "DJI device (possible)". |
| **0x0043** (67) | PARROT AUTOMOTIVE SAS (formerly Parrot SA) | Parrot minidrones (Rolling Spider, Airborne, Mambo, Swing) advertise with this ID; also Parrot audio/car kits -> combine with name prefix. |
| **0x09F3** (2547) | Beijing Zero Zero Infinity Technology Co.,Ltd. | HOVERAir X1/X1 Pro BLE pairing. |
| 0x038F (911) | Xiaomi Inc. | Phones/IoT; **unusable** (intercept mislabels it "Tile"). |
| none | Autel Robotics, Skydio, Yuneec, Hubsan, Ryze, GoPro-drone, Insta360, Walkera, PowerVision, Skydroid, CubePilot, SIYI, Fat Shark, Horizon/Spektrum, FrSky, Dronetag, uAvionix | Not present under those names; use device-name patterns or ODID 0xFFFA instead. |

#### BLE device-name patterns (Complete/Shortened Local Name)

| Pattern | Device | Role | Conf. | Source |
|---|---|---|---|---|
| `^RS_`, `^Mars_`, `^Travis_`, `^Maclane_`, `^Swat_`, `^Blaze_`, `^NewZ_`, `^Orak_`, `^Mambo_`, `^Swing_` | Parrot Rolling Spider, Airborne Cargo/Night, Hydrofoil, Mambo, Swing (BLE-controlled minidrones) | A | H | gobot minidrone docs, pyparrot ("Complete Local Name = Mambo_<numbers>"), Paparazzi wiki ("RS_...") |
| `^Skydio` | Skydio aircraft/Beacon/controller in setup mode | A/C | M | Fieldwatch/BlueWatch catalog |
| `^Autel` | Autel aircraft/Smart Controller pairing | A/C | M | Fieldwatch/BlueWatch |
| `^Hover`, `^HOVERAir` | Zero Zero HOVERAir X1 (pairs via BLE, WiFi "HoverX1_xxxx") | A | H | HOVERAir support + Fieldwatch |
| `^ANAFI`, `^Bebop` | Parrot ANAFI/Bebop BLE (prefix-only to avoid Parrot audio) | A | M | BlueWatch |
| DJI names: `^DJI`, `^Mini`, `^Mavic`, `^Air`, `^Avata`, `^Neo`, `^Flip`, `^Goggles`, `^RC`, `^OsmoPocket`, `^OsmoAction`, `^OM[ 0-9]` | DJI aircraft (QuickTransfer), RC-N1/N2/RC/RC Pro, Goggles 2/Integra/3, Osmo | A/C/X | L | DJI documents BLE 4.2–5.2 radios but not advertised names; **capture before enabling**. Prefer company ID 0x08AA + model id. |
| `^Hubsan`, `^Zino` | Hubsan controllers/aircraft | A/C | L | no public captures found |
| ODID service data UUID 0xFFFA | Any Remote-ID transmitter (already decoded by the project) | A | H | opendroneid-core-c |

### Detector guidance derived from the above

1. Exact OUI hit on a drone-only registrant (Skydio, Hubsan /28, Yuneec /28, Zero Zero, FIMI /28, Teal, Autel /28, Quantum, Skyrocket /28, DroneID 26:37:12 IE) -> "drone (fingerprint, no RID)".
2. OUI hit on a mixed registrant (DJI ×10, Parrot ×5, PowerVision, Freefly, CubePilot, GoPro, DJI Ronin/Osmo) -> "possible"; promote to "drone" when an SSID/BLE-name regex above also matches, demote to "accessory" on OSMO/Ronin/GP SSIDs.
3. SSID regex hit on a module OUI (Bilian, ICOMM, Earda, Espressif…) -> "toy drone (fingerprint)"; OUI alone -> ignore.
4. Xiaomi OUI or 0x038F alone -> ignore.
5. Many 2020+ aircraft and all phones use randomised MACs on the station side; only AP/beacon BSSIDs and BLE public addresses are reliable.

---

## PART 2 – International Remote ID regimes and the identifiers to surface

### 2.0 Open Drone ID enums (opendroneid-core-c `libopendroneid/opendroneid.h`, master)

```
ODID_MESSAGE_SIZE = 25, ODID_ID_SIZE = 20, ODID_STR_SIZE = 23, ODID_BASIC_ID_MAX_MESSAGES = 2

ODID_messagetype_t: BASIC_ID=0, LOCATION=1, AUTH=2, SELF_ID=3, SYSTEM=4, OPERATOR_ID=5, PACKED=0xF, INVALID=0xFF
ODID_idtype_t:      NONE=0, SERIAL_NUMBER=1, CAA_REGISTRATION_ID=2, UTM_ASSIGNED_UUID=3, SPECIFIC_SESSION_ID=4
ODID_uatype_t:      NONE=0, AEROPLANE=1, HELICOPTER_OR_MULTIROTOR=2, GYROPLANE=3, HYBRID_LIFT=4, ORNITHOPTER=5,
                    GLIDER=6, KITE=7, FREE_BALLOON=8, CAPTIVE_BALLOON=9, AIRSHIP=10, FREE_FALL_PARACHUTE=11,
                    ROCKET=12, TETHERED_POWERED_AIRCRAFT=13, GROUND_OBSTACLE=14, OTHER=15
ODID_status_t:      UNDECLARED=0, GROUND=1, AIRBORNE=2, EMERGENCY=3, REMOTE_ID_SYSTEM_FAILURE=4
ODID_Height_reference_t: OVER_TAKEOFF=0, OVER_GROUND=1
ODID_operatorIdType_t:   ODID_OPERATOR_ID=0        (only defined value; CAA-assigned operator registration)
ODID_authtype_t:    NONE=0, UAS_ID_SIGNATURE=1, OPERATOR_ID_SIGNATURE=2, MESSAGE_SET_SIGNATURE=3,
                    NETWORK_REMOTE_ID=4, SPECIFIC_AUTHENTICATION=5
ODID_desctype_t:    TEXT=0, EMERGENCY=1, EXTENDED_STATUS=2
ODID_operator_location_type_t: TAKEOFF=0, LIVE_GNSS=1, FIXED=2
ODID_classification_type_t:    UNDECLARED=0, EU=1
ODID_category_EU_t: UNDECLARED=0, OPEN=1, SPECIFIC=2, CERTIFIED=3
ODID_class_EU_t:    UNDECLARED=0, CLASS_0=1, CLASS_1=2, CLASS_2=3, CLASS_3=4, CLASS_4=5, CLASS_5=6, CLASS_6=7
ODID_Horizontal_accuracy_t: UNKNOWN=0, 10NM=1, 4NM=2, 2NM=3, 1NM=4, 0_5NM=5, 0_3NM=6, 0_1NM=7, 0_05NM=8,
                    30_METER=9, 10_METER=10, 3_METER=11, 1_METER=12
ODID_Vertical_accuracy_t:   UNKNOWN=0, 150_METER=1, 45_METER=2, 25_METER=3, 10_METER=4, 3_METER=5, 1_METER=6

ODID_System_data: OperatorLocationType, ClassificationType, OperatorLatitude, OperatorLongitude, AreaCount,
                  AreaRadius, AreaCeiling, AreaFloor, CategoryEU, ClassEU, OperatorAltitudeGeo, Timestamp
```

UI label hints: ClassEU value N maps to "C(N-1)" (CLASS_0=1 -> "C0"); CategoryEU -> Open/Specific/Certified; ClassificationType 0 means CategoryEU/ClassEU are meaningless (US/Japan transmitters).

Regional mandatory-message matrix (opendroneid-core-c README):

| Requirement | FAA (USA) | ASD-STAN (EU) | Japan |
|---|---|---|---|
| Serial number (IDType 1) | Mandatory (or Session ID 4; add-ons may not use Session ID) | Mandatory | Mandatory |
| Registration / CAA ID (IDType 2) | Optional | Optional (operator ID goes in Operator ID message instead) | **Mandatory** (second Basic ID message) |
| Authentication | Optional | Optional | **Mandatory** |
| Operator location | Mandatory (take-off OK for add-ons) | Mandatory (take-off OK for add-ons) | Optional |
| Primary transports | BT4+BT5 or WiFi Beacon | BT4+BT5 or WiFi Beacon (NAN optional) | BT5 Long Range + WiFi Beacon/NAN (BT4 optional) |

Transport encodings (README / F3411): BT4 legacy ADV with Service Data UUID 0xFFFA, app code 0x0D; BT5 Long Range = extended advertising on LE Coded PHY (S8) with same payload (**original ESP32 cannot receive Coded PHY; ESP32-C3/S3/C6 can – relevant for EU/Japan coverage**); WiFi NAN service discovery frames; WiFi Beacon vendor IE OUI FA:0B:BC type 0x0D carrying a message pack.

### 2.1 European Union / EASA (also Switzerland, Norway, Iceland, Liechtenstein)

- **Legal basis**: Regulation (EU) 2019/945 as amended by 2020/1058 – Part 6 "Requirements for a direct remote identification add-on" and the class-mark Parts (C1, C2, C3 must have DRI; C5/C6 for Specific category; **C0 and C4 exempt**); Regulation 2019/947 Art. 14 (operator registration). Standard: **ASD-STAN prEN 4709-002** "Direct Remote Identification" (Oct 2021, Corrigendum Feb 2023), aligned with ASTM F3411 v1.1 / F3411-22a.
- **Transports**: Bluetooth 4 legacy, Bluetooth 5 Long Range, Wi-Fi NAN, Wi-Fi Beacon. DJI's EU DRI (Mini 4 Pro C1, Air 3, Mavic 3 family, M30/M350/M3E) uses Wi-Fi Beacon; most EU add-ons (Dronetag, dronescout, Bluemark) use BT4+BT5 LR.
- **Part 6 data set (verbatim intent)**: UAS operator registration number *and verification code* (only broadcast if the add-on's consistency check passed – in practice only the 16-char public part is broadcast), serial number per ANSI/CTA-2063-A-2019, time stamp, position, height above surface/take-off, route course (clockwise from true north), ground speed, remote-pilot position or take-off point, emergency status; "open and documented transmission protocol".
- **Operator Registration Number (ORN)**: 16 public characters = ISO 3166-1 alpha-3 country code (upper case, e.g. `FIN`, `CHE`, `NOR`, `DEU`) + 12 random lower-case alphanumerics + 1 checksum char, then `-` + **3 secret characters** that are never broadcast, e.g. `FIN87astrdge12k8-xyz`. Checksum is **Luhn mod 36** over the public random part + secret part (prEN 4709-002; Dronavia; DJI forum). A receiver can therefore only validate the *format* (`^[A-Z]{3}[a-z0-9]{12}[a-z0-9]$`), not the checksum. Unconfigured drones broadcast NULL/empty.
- **ODID fields**: BasicID[0] IDType=1 (serial of UA, or of the add-on); Operator ID message with OperatorIdType=0 carrying the 16-char ORN; System message ClassificationType=1 (EU), CategoryEU, ClassEU (C0–C6); Location message incl. operator location type; Auth optional; Self-ID optional.
- **Dates**: class-mark labels required for new drones since 1 Jan 2023; since 1 Jan 2024 "legacy" (unmarked) drones ≥250 g are confined to A3 and need a DRI add-on only when a geo-zone or Specific-category authorisation demands it.
- **Switzerland**: EU rules applied from 1 Jan 2023; operator numbers `CHE` + 12 + checksum + 3 secret; network RID service (SUSI / U-space) also transmits the ORN. **Norway**: EU rules since 1 Jan 2021 via EEA; example from Luftfartstilsynet `NOR87astrdge12k-xyz`; registration at flydrone.no.
- Sources: aviation.bot rendering of EASA Easy Access Rules Part 6; EASA FAQ; Dronetag "Remote ID explained" / "Dronetag usage in EU"; Dronavia (Luhn mod 36); unmannedairspace.info on ASD-STAN publication; DJI Enterprise EU RID blog; bazl.admin.ch; luftfartstilsynet.no.

### 2.2 United Kingdom (CAA)

- **Registration IDs**: Operator ID current format **`GBR-OP-XXXXXXXXXXXX`** (12 alphanumerics after the prefix; introduced Oct 2021), legacy **`OP-XXXXXXXX`**; Flyer ID current **`GBR-RP-XXXXXXXXXXXX`**, legacy **`FLY-…`** (FPV UK FAQ, CAA). Operator ID must be on the aircraft in ≥3 mm capitals.
- **Thresholds from 1 Jan 2026**: Flyer ID from 100 g; Operator ID from 100 g if camera-equipped (250 g otherwise) up to 25 kg.
- **Remote ID**: mandatory from **1 Jan 2026** for UK class-marked **UK1/UK2/UK3** (and UK5/UK6 Specific); from **1 Jan 2028** for legacy/unmarked aircraft and UK0/UK4 with camera (100 g+). EU C-class labels recognised until 31 Dec 2027. UK class marks UK0 (<250 g) … UK6 mirror EU C0–C6.
- **What is broadcast**: CAA says the Remote ID "transmits the identity and location of your drone"; CAA issues each registered operator a "Remote ID" value via the registration portal (appears to be the Operator ID string entered into the aircraft); industry summaries (Heliguy, FPV UK) list Operator ID, aircraft serial, aircraft position/height and pilot position – i.e. the EU DRI data set. Technical standard not named in CAA consumer pages; expect ASD-STAN EN 4709-002 behaviour (Operator ID message carries `GBR-OP-…`; validate `^GBR-OP-[A-Z0-9]{12}$`).
- Sources: caa.co.uk Drone Code points 30–35; FPV UK "Class Marks and Remote ID" and Operator-ID FAQs; dronedj 2026-01-01; heliguy.

### 2.3 Japan (MLIT)

- Broadcast Remote ID mandatory since **20 June 2022** for registered UAS (registration from 100 g); aircraft registered by 19 June 2022 were grandfathered; alternatives: DIPS flight-plan notification within a declared area, tethered, etc.
- **Registration ID** (DIPS-REG): `JU` + 10 alphanumerics = 12 characters, e.g. `JU12345ABCDE` (MLIT handbook, apollomaniacs). Must be displayed on the airframe.
- **Transports**: Bluetooth 5 Long Range (mandatory option), Wi-Fi Beacon or Wi-Fi NAN; BT4 legacy optional. Update ≥1 Hz, target ≥300 m (MLIT "Requirements for remote ID devices").
- **ODID fields**: **two Basic ID messages** – IDType 1 (manufacturer serial) and IDType 2 (`JU…` registration ID); Location; **Authentication mandatory**: AuthType 3 (Message Set Signature), page count 0, length 17, 32-bit timestamp since 2019-01-01 UTC, signature with a key obtained at registration (opendroneid-core-c README "Japan" section; MLIT PDF 001582250 via secondary summaries). Operator ID / System EU fields not used.
- UI: label `JU` IDs as "Japan registration (MLIT)"; flag AuthType 3 as "JP signature".

### 2.4 Australia (CASA)

- No Remote ID mandate as of 2025. Discussion paper July 2023; Aviation White Paper commits to a Policy Impact Analysis (drones.gov.au "Remote Identification" page); industry reporting in mid-2025 points to scoping for ~2027 for sub-2 kg. Registration: all commercial RPA; recreational registration for >250 g reported as phased in 2024–25 (verify current status on casa.gov.au). No broadcast identifier format exists yet; FAA/EU-standard RID from imported DJI aircraft will appear as IDType 1 serials with no operator ID.

### 2.5 Canada (Transport Canada)

- Registration certificate number `C-` + alphanumeric string (e.g. `C-1234567`; sources differ on length) must be marked on RPAS 250 g–25 kg. No Remote ID requirement today. **NPA 2026-005** proposes RID for 250 g–150 kg (broadcast via Wi-Fi/Bluetooth or network), performance-based, with CBO phases 2028–2029 and full implementation ~2030 (tc.canada.ca summary). Treat `C-…` strings in Operator ID/Self-ID as "Canada registration (informal)".

### 2.6 India (DGCA / Digital Sky)

- Drone Rules 2021: registration on Digital Sky yields a **UIN (Unique Identification Number)** linked to airframe, flight-controller and GCS serials; format reported as `UA-XXXXXXX` (community guides; verify on digitalsky.dgca.gov.in). **NPNT** (No-Permission-No-Takeoff) from the 2018 CAR / RPAS guidance is a *network* permission-artefact scheme, not a broadcast RID; no ASTM/ASD-STAN broadcast mandate. Surface `UA-` strings as "India UIN (unverified)".

### 2.7 China (CAAC / SAMR)

- **Real-name registration** since 2017 (UOM platform uom.caac.gov.cn, from 2024 covering ≥250 g and all non-micro). Registration mark = **`UAS` + 8 alphanumerics (11 chars)** plus QR code (MH/T 3030-2023 data-interface standard; CAAC 2017 rules).
- **GB 42590-2023** "Safety requirements for civil UAS" – mandatory national standard, RID clauses early-implemented from **1 Jan 2024** (with the Interim Regulations on UA Flight Management), full standard from **1 June 2024**. Light/small UAS must (a) report identity to the integrated supervision platform over the network and (b) **broadcast identification over Wi-Fi or Bluetooth** during flight (Annex A). Broadcast messages are 25 bytes with a header byte (type in bits 7-4, protocol version bits 3-0 = 0x1) – i.e. ODID-shaped; test labs cite Wi-Fi beacon and BLE compliance testing. Identity data: product unique identification code / serial, real-name registration code, position, altitude, speed, operator position, timestamp (163.com interpretation; references GB/T 38909-2020). A newer **GB 46750-2025** RID standard is described by the OmniRID project as field-compatible with ASTM F3411. Expect `UAS########` in an IDType 2 or Operator ID slot; verify with captures.

### 2.8 Brazil (ANAC / DECEA)

- SISANT registration code **`PR-XXXXXXXXX`** (recreational) / **`PP-XXXXXXXXX`** (non-recreational), 9 characters, affixed to the airframe; RBAC-E 94 / RBAC 100 and DECEA ICA 100-40 contain **no Remote ID requirement** (ANAC FAQ; irlenmenezes.com.br 2026). Surface `PR-`/`PP-` as "Brazil SISANT".

### 2.9 United Arab Emirates (GCAA; DCAA for Dubai)

- Registration mandatory for all UAS (any weight) via GCAA "My Drone Hub" (DCAA for Dubai); CAR Part VIII Subpart 10 / CAR-UAS, CAR-UAR Issue 04 (3 Sep 2025). Secondary sources state that since 2022–2024 registered drones must broadcast ID and position through a UAE Remote ID framework using GCAA-approved modules (Bluetooth or Wi-Fi) carrying registration ID, position, altitude and operator ID; OEM RID (DJI, Autel) is accepted. **Low confidence** – the GCAA PDFs were not machine-readable here; confirm the technical standard (likely ASTM F3411) and the registration-number format before labelling.

### 2.10 South Korea (MOLIT)

- Registration for >250 g via Drone One-Stop; identification number must be affixed. **No Remote ID requirement** as of 2025; K-Drone UTM trials and policy discussion suggest a future mandate (>250 g). No identifier format to surface yet.

### 2.11 Singapore (CAAS) – included because it is the newest mandate

- **Broadcast Remote ID (B-RID) mandatory from 1 Dec 2025 for all UA > 250 g**, except operators with an Operator Permit using the FlyItSafe app, or indoor/enclosed flights. CAAS "adopting EU technical standards" (i.e. ASD-STAN EN 4709-002 Bluetooth/Wi-Fi); AC 101-2A(2). 6,300 free modules issued; penalties up to S$10,000 and/or 6 months. Expect EU-style frames with Singapore registration label in Operator ID.

### 2.12 United States (reference, already implemented)

- 14 CFR Part 89 since 16 Sep 2023 (enforcement from 16 Mar 2024). Standard RID aircraft: BasicID IDType 1 serial (ANSI/CTA-2063-A: 4-char ICAO manufacturer code + 1 length char + up to 15 chars, letters O and I excluded) or IDType 4 Session ID; broadcast modules: serial only + take-off location. Manufacturer codes observed by SkySafe: DJI `1581F`, Skydio `1668B`, Autel `1748C`, Parrot should be `1588E` (43 % used non-compliant `PI040…`), Dronetag `15996F`. DJI Mini 3 / Mini 4 Pro were found not transmitting RID in default configuration (Feb 2024).

### 2.13 Field-to-label mapping for the UI

| Field | How to label |
|---|---|
| BasicID[0] / BasicID[1] | Show both; Japan sends serial + `JU…`; US sends serial or Session ID; EU sends serial only. |
| IDType 1 | "Serial (ANSI/CTA-2063-A)" – first 4 chars = manufacturer code (DJI 1581F…, Skydio 1668B…, Autel 1748C…). Validate charset `[0-9A-HJ-NP-Z]`. |
| IDType 2 | "CAA registration" – pattern hints: `^JU[0-9A-Z]{10}$` Japan; `^UAS[0-9A-Z]{8}$` China; `^C-` Canada (informal); `^UA-` India (informal). |
| IDType 3 | "UTM UUID" (rare). |
| IDType 4 | "Session ID (US privacy)". |
| Operator ID message (OperatorIdType 0) | EU/UK/SG/CH/NO operator number: `^[A-Z]{3}[a-z0-9]{13}$` -> country = first 3 letters; UK `^GBR-OP-`; US pilots sometimes enter FAA registration `FA…`. |
| System.ClassificationType | 0 = not EU; 1 = EU -> show CategoryEU (Open/Specific/Certified) and ClassEU (C0–C6). |
| System.OperatorLocationType | 0 take-off, 1 live GNSS, 2 fixed. |
| Auth | AuthType 3 + 2019 epoch -> "Japan signature"; AuthType 5 -> "specific authentication method". |
| Self-ID DescType | 0 text (free text, often operator phone/mission), 1 emergency, 2 extended status. |

---

## Sources (every entry above cites one of these)

IEEE / MAC registries and mirrors
- IEEE RA OUI registry (authoritative): https://standards-oui.ieee.org/
- maclookup.app (IEEE+Wireshark mirror) vendor pages: `/vendors/sz-dji-technology-co-ltd`, `/vendors/parrot-sa`, `/vendors/skydio-inc`, `/vendors/gopro`, `/vendors/shenzhen-hubsan-technology-co-ltd`, `/vendors/yuneec-international-china-co-ltd`, `/vendors/autel-robotics-usa-llc`, `/vendors/shenzhen-zero-zero-infinity-technology-co-ltd`, `/vendors/powervision-tech-inc`, `/vendors/beijing-fimi-technology-co-ltd`, `/vendors/teal-drones-inc`, `/vendors/freefly-systems-inc`, `/vendors/cubepilot-pty-ltd`, `/vendors/quantum-systems-gmbh`, `/vendors/anduril-industries`, `/vendors/shield-inc`, `/vendors/zipline-international-inc`, `/vendors/aerovironment-av-inc`, `/vendors/insitu-inc`, `/vendors/aeryon-labs-inc`, `/vendors/skyrockettoys-llc`, `/vendors/iflight-technology-company-limited`, `/vendors/arashi-vision-inc`, `/vendors/xiaomi-communications-co-ltd`, `/vendors/beijing-xiaomi-mobile-software-co-ltd`, `/vendors/beijing-xiaomi-electronics-co-ltd`; API `https://api.maclookup.app/v2/macs/<prefix>` for every prefix in the tables (including the debunked ones and 26:37:12).
- Wireshark manuf: https://www.wireshark.org/download/automated/data/manuf (too large to fetch through the tool; maclookup mirrors it).
- Kismet UAV config: https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf ; DJI DroneID parser: https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h and `kaitai_definitions_disabled/dot11_ie_221_dji_droneid.ksy`.
- Community lists cross-checked: lnxgod/friendorfoe `backend/app/services/drone_signature_reference.py` and `esp32/scanner/main/detection/wifi_oui_database.c`; smittix/intercept `data/patterns.py` (contains wrong OUIs – see debunked list); colonelpanichacks/oui-spy-unified-blue README; PolarPatch/BlueWatch `bluewatch/classifier.py`; OffGridPete/Fieldwatch `CatalogDecodes.kt`/`DefaultCatalog.kt`.

Bluetooth SIG company identifiers
- https://www.bluetooth.com/specifications/assigned-numbers/ (YAML on bitbucket.org/bluetooth-SIG/public); mirrors: bluekitchen/btstack `src/bluetooth_company_id.h` (0x08AA DJI, 0x09F3 Beijing Zero Zero Infinity, 0x038F Xiaomi Inc), GoogleChrome/samples datalist, Grupa-Ratownictwa-PCK-Poznan/SAR_BT_Scan `bt_manufacturer_ids.py`, finitelabs/control4-esphome `company_identifiers.lua`, NordicSemiconductor/bluetooth-numbers-database (0x0043 Parrot Automotive SAS).

Vendor manuals / support pages (SSIDs, BLE names)
- Parrot ANAFI USA user guide (parrot.com), Parrot developer Wi-Fi setup docs, pyparrot quick-start, gobot minidrone platform docs, Paparazzi wiki Ap.parrot_minidrone.
- Skydio support (Getting started with Skydio 2/2+), Skydio Beacon user guide (FCC 2ATQRSBEC1V1).
- Yuneec Mantis Q manual (B&H lit file), yuneecpilots.com threads (Breeze, CGO3).
- Hubsan H501A manual (B&H), forum.hubsan.com, Hubsan Zino connect tutorial PDF.
- Holy Stone HS210/HS710 manuals, zturner1/h120d-protocol.
- Potensic Dreamer manuals (manualslib, FCC 2AYUO-A21), droneblog Potensic connect guide.
- Snaptain S5C manual (manuals.plus), Ruko F11 manuals (manualslib/manuals.plus), SJRC F22 S2 manual.
- Walkera Vitus FAQ (walkera.com), FCC S29WK-V8 operation guide.
- PowerVision PowerEgg X user manual (adorama/manualslib).
- HOVERAir X1 quick-start and WiFi troubleshooting (hoverair.com / support.hoverair.com).
- Wingsland S6 user manual (conrad.com).
- UDI U818A WiFi operation manual, Cheerson CX-10W reviews, MJX Bugs manuals, JJRC Amazon Q&A, Eachine E58 review (the-gadgeteer), Visuo XS809HW manual, E88/E99 guides.
- HDZero Goggle user manual / docs.hd-zero.com; Oscar Liang Walksnail Goggles X review; DJI Goggles 2/3 specs; DJI QuickTransfer FAQ; DJI RC-N1/RC/RC Pro manuals; FIMI forum (amba_boss).
- SkySafe, "Drone Manufacturers Fail FAA Remote ID Requirements" (Feb 2024): https://blog.skysafe.io/drone-manufacturers-fail-faa-remote-id-requirements

Remote ID standards and regulators
- opendroneid-core-c README and `libopendroneid/opendroneid.h`: https://github.com/opendroneid/opendroneid-core-c ; MAVLink Open Drone ID page: https://mavlink.io/en/services/opendroneid.html
- EASA Easy Access Rules for UAS (Part 6 via https://aviation.bot/EASA/UNMANNED-AIRCRAFT-SYSTEMS-JUL-2024/...); EASA FAQ https://www.easa.europa.eu/en/the-agency/faqs/drones-uas ; ASD-STAN prEN 4709-002 (stan-shop.org item 75040; intro PDF cms.stan-shop.org); Dronetag help centre (Remote ID explained; Dronetag usage in EU); Dronavia "Remote Identification in Europe" (Luhn mod 36); DJI Enterprise EU RID blog; Estonian Transport Administration operator registration page.
- UK: caa.co.uk Drone Code (Operator ID points 30–35); FPV UK FAQs (GBR-OP-/GBR-RP- formats, class marks & RID); dronedj 2026-01-01; heliguy 2026 rules.
- Japan: MLIT "Requirements for remote ID devices and applications" https://www.mlit.go.jp/koku/content/001582250.pdf ; MLIT handbook (en) 2022; apollomaniacs remote-ID how-to.
- Australia: drones.gov.au Remote Identification; casa.gov.au news.
- Canada: tc.canada.ca NPA 2026-005 summary; TC drone registration guides.
- India: Drone Rules 2021 summaries (legal500, diligencecertification, mavdrones).
- China: GB 42590-2023 (chinesestandard.net / codeofchina); 163.com interpretation; CSDN GB42590 message-format post; CUAV C-RID page; CAAC real-name registration rules 2017; MH/T 3030-2023 (UAS+8 format); OmniRID issue #46 (GB 46750-2025).
- Brazil: ANAC drones FAQ; irlenmenezes.com.br Remote ID / SISANT 2026.
- UAE: GCAA CAR-UAR Issue 04 (PDF), gulfnews/uaeexperthub summaries, droneshop.ae 2025 guide.
- South Korea: drone-laws.com, ts2.tech 2025 overview.
- Singapore: CAAS newsroom (1 Dec 2025 B-RID), Rajah & Tann viewpoint, unmannedairspace.info.
- Switzerland/Norway: bazl.admin.ch registration; susi.swiss network RID; luftfartstilsynet.no registration (NOR example).
- ANSI/CTA-2063-A: webstore.ansi.org preview; CubePilot manufacturer-code thread; IETF draft-wiethuechter-drip-uas-sn-dns.
