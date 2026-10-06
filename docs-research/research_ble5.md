# BLE 5 Long Range (LE Coded PHY) reception of Open Drone ID on ESP32 — research reference

Research date: 2026-10-02. Target project: `drone-sentinel` (Seeed XIAO ESP32-S3 primary; C3/C5/C6 variants; PlatformIO + pioarduino platform `55.03.312` = arduino-esp32 3.3.12 / ESP-IDF 5.5.5; the C5 env already uses `h2zero/NimBLE-Arduino@^2.1.0`).

No project files were modified. All findings below are cited; where a source could not be read (GitHub issue comment threads are blocked from this session; one ESP32 forum thread is behind a bot-challenge) this is stated explicitly.

---

## 0. Executive summary (decisions that matter)

1. **Over-the-air format is identical on BT4 and BT5.** Both carry one AD structure `len | 0x16 (Service Data 16-bit UUID) | 0xFA 0xFF (UUID 0xFFFA, little-endian) | 0x0D (app code "Open Drone ID") | msg counter | ODID payload`. On BT4 legacy the payload is one 25-byte message; on BT5 LR it is a **Message Pack (type 0xF)**: `[0xF<<4|ver] [0x19] [N] [N*25 bytes]`. ASTM F3411-19 Tables 14 & 17 (verbatim extracts in §1).
2. **BT5 LR = Advertising Extensions on LE Coded PHY S=8, non-connectable, non-scannable.** `ADV_EXT_IND` on 37/38/39 carries only an AuxPtr; the data sits in `AUX_ADV_IND` on a secondary (data) channel, also on Coded PHY. The **controller follows the AuxPtr automatically**; the host just receives an "LE Extended Advertising Report". A Coded-PHY receiver decodes both S=2 and S=8 because the Coding Indicator in FEC block 1 (always S=8) says how block 2 is coded.
3. **Hardware:** original ESP32 = Bluetooth 4.2 only (no `SOC_BLE_50_SUPPORTED`). ESP32-S3, C3, C5, C6, H2 all have `SOC_BLE_50_SUPPORTED (1)` and Espressif's per-chip feature tables list *LE Long Range (Coded PHY S=2/S=8)* and *LE Advertising Extensions* as Supported in controller, Bluedroid and NimBLE. (H2 has no Wi-Fi; irrelevant for this project.)
4. **Critical toolchain fact:** since arduino-esp32 **3.3.0** (what pioarduino "stable" ships: 3.3.12), the built-in `BLE` library runs on the **NimBLE host for every SoC except the original ESP32** (`CONFIG_BT_BLUEDROID_ENABLED=n`, `CONFIG_BT_NIMBLE_ENABLED=y` in the lib-builder defconfigs for esp32s3/c3/c5/c6/h2). The built-in library's extended-scan API (`setExtendedScanCallback`, `setExtScanParams`, `startExtScan`) is compiled **only** under `#if defined(SOC_BLE_50_SUPPORTED) && defined(CONFIG_BLUEDROID_ENABLED)`, and its NimBLE code path only calls `ble_gap_disc()` (legacy scan). The shipped `BLE5_extended_scan` example literally `#error`s: *"NimBLE does not support extended scan yet. Try using Bluedroid."* So on the current S3 build (`node-mode-dualcore`, `remoteid-mesh-dualcore`) **the Bluedroid snippet (3a) will not compile** unless you (a) pin an older pioarduino/arduino 3.2.x core where S3 still used Bluedroid, or (b) use pioarduino's `custom_sdkconfig` hybrid-compile to rebuild the libs with Bluedroid + `CONFIG_BT_BLE_50_FEATURES_SUPPORTED=y` (feature has open bugs), or (c) **switch the S3 to h2zero/NimBLE-Arduino 2.x like the C5 env already does — recommended.**
5. **NimBLE-Arduino 2.x** gives extended scanning on 1M + Coded simultaneously with `-D CONFIG_BT_NIMBLE_EXT_ADV=1` in `build_flags` (must be a global `-D` so it is seen when the library itself compiles), `NimBLEScan::setPhy(NimBLEScan::Phy::SCAN_ALL)` (the method is `setPhy`, not `setScanPhy`; the enum is `SCAN_1M/SCAN_CODED/SCAN_ALL`, not `BLE_HCI_LE_PHY_*_PREF_MASK`), passive scan, duplicates on. Legacy adverts keep arriving in the same `onResult()` with `isLegacyAdvertisement()==true`. Pin `NimBLE-Arduino@^2.5.1` (2.5.1 fixes "Arduino 3.3.11 build/crash with esp32 c5/c6").
6. **Scanning both PHYs halves your on-air duty on each** (the controller alternates PHYs per scan interval); with Wi-Fi promiscuous sniffing on the same radio (coex table: *"Wi-Fi sniffer + BLE scan: supported but unstable"*), expect multi-second detection latency; use passive scan, window == interval, duplicates **not** filtered (ODID content changes every second), and verify `data_status == COMPLETE`.

---

## 1. Open Drone ID over Bluetooth — formats and timing

### 1.1 Message types, Message Pack, sizes (opendroneid-core-c `opendroneid.h`)

```c
#define ODID_MESSAGE_SIZE 25
#define ODID_ID_SIZE 20
#define ODID_STR_SIZE 23
#define ODID_PACK_MAX_MESSAGES 9

typedef enum ODID_messagetype {
    ODID_MESSAGETYPE_BASIC_ID = 0, ODID_MESSAGETYPE_LOCATION = 1,
    ODID_MESSAGETYPE_AUTH = 2,     ODID_MESSAGETYPE_SELF_ID = 3,
    ODID_MESSAGETYPE_SYSTEM = 4,   ODID_MESSAGETYPE_OPERATOR_ID = 5,
    ODID_MESSAGETYPE_PACKED = 0xF, ODID_MESSAGETYPE_INVALID = 0xFF,
} ODID_messagetype_t;

typedef struct __attribute__((__packed__)) ODID_MessagePack_encoded {
    uint8_t ProtoVersion: 4;     // byte 0 low nibble
    uint8_t MessageType : 4;     // byte 0 high nibble (= 0xF)
    uint8_t SingleMessageSize;   // byte 1 = 0x19 (25)
    uint8_t MsgPackSize;         // byte 2 = N
    ODID_Message_encoded Messages[ODID_PACK_MAX_MESSAGES]; // bytes 3..227
} ODID_MessagePack_encoded;
```
Source: https://raw.githubusercontent.com/opendroneid/opendroneid-core-c/master/libopendroneid/opendroneid.h

Every message starts with the header byte `[MessageType:4][ProtoVersion:4]` (type in the **upper** nibble — hence the firmware's `odid[0] & 0xF0` switch). ASTM F3411-19 §5.4.5.4 / Table 4.

The project's bundled `opendroneid.h` (e.g. `/home/user/drone-sentinel/remoteid-c5-5g/src/opendroneid.h`) already defines `ODID_PACK_MAX_MESSAGES 9`, `decodeMessagePack()` and `odid_message_process_pack(ODID_UAS_Data*, uint8_t *pack, size_t buflen)` (used for the Wi-Fi path) — the BT5 path can reuse it.

ASTM F3411-19 Table 13 (Message Pack): *"Message Size … Set to 0x19 (25)"*, *"No of Msgs in Pack (N) … Up to 10"*, *"Messages … Up to 250 bytes"*; §5.4.7.7: *"No more than 10 messages shall (BB50120) be included in a Message Pack."* opendroneid-core-c (tracking F3411-22a / EN 4709-002) caps at **9** → pack = 3 + 9×25 = **228 bytes**; plus 4-byte AD header + app code + counter = **234 bytes of AD data**, which fits inside a single `AUX_ADV_IND` (AdvData max 254, 251 when the extended header is 3 bytes) — **no AUX_CHAIN_IND chaining needed** for ODID.

Message-type table (ASTM F3411-19 Table 3, verbatim from the PDF text):
```
0x0 Basic ID Message   0x1 Location/Vector   0x2 Authentication(A)
0x3 Self-ID(A)         0x4 System(A)         0x5 Operator ID(A)
0xF Message Pack(A)  "A payload mechanism for combining the messages above into a single
                      message pack. Used with Bluetooth Extended Advertising and Wi-Fi
                      Neighbor Awareness Network"   (A = Optional unless required by jurisdiction)
```
(Note: F3411-22a / EN 4709-002 make System and Operator ID mandatory in the EU; the opendroneid README comparison table covers that.)

### 1.2 BT4 Legacy advertising frame (ASTM F3411-19 §5.4.6, Table 14, verbatim)

```
PDU Hdr    2   0x2025   PDU Type 0x2 = ADV_NONCONN_IND – Connectionless Advertisement ... Len 0x25 = 37 Bytes
AD Addr    6            Unique Hardware Address of Bluetooth MAC
AD Info    4   1Eh,16h,0xFFFA   Length 0x1E = 30 Bytes (excluding this field)
                                Type   0x16 = Service Data
                                Mfg Code 0xFFFA = ASTM (Little Endian (FA,FF))
AD App     1   0x0D     Application Code: 0x0D = Open Drone ID
AD Counter 1   0xXX     Msg Counter: Start at 0 for first message sent, increment for each
                        message of the same type. Roll over back to 0 after 0xFF.
ODID Msg   25           Open Drone ID Message
```
§5.4.6.3: *"Bluetooth supports a 'Broadcast Frame' to transmit on the beacon channels with a custom message length limit of 31 bytes. This leaves 25 bytes (after certain header info) available for Open Drone ID messages."* *"These broadcast messages shall (BB40010) be 'un-coded' and conform to Bluetooth Core Specification 5.0, Volume 6, Part B, Sections 2.1 and 2.3.1."*

opendroneid `transmitter-linux/bluetooth.c` builds exactly this buffer: `0x1F /*Advertising_Data_Length*/, 0x1E, 0x16, 0xFA, 0xFF, 0x0D, counter, <25 bytes>` with comment *"1E = The length of the data (30 bytes), 16 = GAP AD Type = 'Service Data - 16-bit UUID', FAFF = 0xFFFA = ASTM International, ASTM Remote ID, 0D = AD Application Code within the ASTM address space = Open Drone ID"* (https://raw.githubusercontent.com/opendroneid/transmitter-linux/master/bluetooth.c). Legacy interval there is clamped to HCI range `0x0020..0x4000` (20 ms – 10.24 s in 0.625 ms units).

So the firmware's current check `payload[1]==0x16 && payload[2]==0xFA && payload[3]==0xFF && payload[4]==0x0D` and `odid = &payload[6]` is correct for a payload whose first AD structure is the ODID one.

### 1.3 BT5 Long Range frame (ASTM F3411-19 §5.4.7, Tables 15–17, verbatim)

General requirements (§5.4.7.1): *"If implementing this specification using Bluetooth 5 Long Range, Legacy (ADV_NONCONN_IND) advertisements must (BB50010) be sent, as described in 5.4.6, for backwards compatibility with less capable receivers. Bluetooth 5 Extended Advertisements (ADV_EXT_IND + AUX_ADV_IND) must (BB50020) be sent as well at the same rate as Dynamic Data (see 5.4.4 Update Rates) and they must (BB50030) be sent on a LE Coded (S=8) PHY. This will add Forward Error Correction (FEC) and can increase the range of the advertisements by a factor of 4. These messages shall (BB50040) conform to Bluetooth Core Specification 5.0, Volume 6, Part B, Section 2.2 (LE Coded PHY, S=8)."* §5.4.1.2 lists the transport as *"Bluetooth 5.x Long Range (must be transmitted concurrently with Legacy mode)"*.

§5.4.7.2: *"Bluetooth 5 adds Extended Advertising that allows for up to 255 byte advertisements on the 'non-beacon' channels by implementing a pointer in the primary beacons directing the receiver to read from the secondary channel."* §5.4.7.3: *"the Primary packet shall (BB50050) be broadcast through all 3 beacon channels, followed by the Secondary packet on the remaining channels."*

Primary packet (Table 15): Preamble `0x3C` *"LE Coded PHY"*; CI `00b` *"Coding Indication: FEC Block 2 is coded using S=8 (longest range)"*; PDU Type `0x7 ADV_EXT_IND (Primary)`; *"Adv Mode 0x0, Non-connectable, Non-scannable with Aux Pkt"*; Ext Hdr Flags `0x19` *"(AdvA, ADI, Aux Ptr)"*; Aux Ptr … *"010 = LE Coded Phy"*; *"Adv Data — Not Populated for this message"*. Table 16: *"Channel = (Current Channel + 9) % 36"*, Offset Units 30 µs, *"Beacon 1: 166 us, Beacon 2: 114 us, Beacon 3: 62 us … based on a Primary Packet time of 1552 us + a T_MAFS of 300 us"*, *"Aux PHY 010: LE Coded Phy"*.

Secondary packet (Table 17):
```
Preamble  0x3C  LE Coded PHY ; CI 00b  FEC Block 2 is coded using S=8
PDU Type  0x7   AUX_ADV_IND (Secondary) ; Length 18 + N*25 Bytes (N = messages in pack)
Ext Hdr Len 9, Adv Mode 0x0 Non-connectable, Non-scannable ; Flags 0x09 (AdvA, ADI)
AD Info   4   1Eh,16h,0xFFFA   Length / Type 0x16 Service Data / 16-bit UUID 0xFFFA (FA,FF)
App Code  1   0x0D   Application Code: 0x0D = Open Drone ID
Counter   1   0xXX   Msg Counter ...
ODID Msg  0xXX       Open Drone ID Message Pack
```
Note: the "0x1E" AD length in Table 17 is nominal; the real AD length byte is `1 + 2 + 1 + 1 + 3 + 25·N = 8 + 25·N` — **parse the AD length byte, never assume 0x1E on the BT5 path.**

Takeaways for a scanner:
* Same UUID / app code / counter on both transports → the same matcher works; only the payload type differs (single message vs 0xF pack).
* **Primary and secondary PHY are both LE Coded** (S=8). A scanner that only listens on 1M never sees the `ADV_EXT_IND`, so **the Coded PHY must be enabled in the scan parameters**; 1M must stay enabled for the mandatory legacy adverts.
* Rate: location/dynamic at least every **1 s**, static (Basic ID, System, Operator ID …) at least every **3 s** (ASTM §5.4.4; ASD-STAN: *"Dynamic messages (UAS location/vector) shall be sent at least every one second(s). Static messages (identification data) shall be sent at least every three second(s)."*). The BT5 pack is sent *"at the same rate as Dynamic Data"* → **≈1 pack/s** containing all current messages. MAVLink ODID service doc: *"at least three messages must be broadcast on the air per second, the BT4 RID transmitter component must advertise at least every 333 ms."* No fixed BLE advertising *interval* is mandated; the standard constrains message update rates.
* The message counter increments per message type on BT4; per pack on BT5 (useful for de-dup/sequence tracking).

### 1.4 EU / Japan (ASD-STAN prEN 4709-002) — what add-on modules transmit

ASD-STAN "Introduction to the European digital RID UAS Standard" (https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf), Table 2: *"Bluetooth 5 Long Range (Coded PHY S8) — Expected range 1 km, Max TX power 10 mW, Android receive: Selected newer models, iOS: None"*; *"Bluetooth 4 Legacy Advertising — 250 m … Android: All models, iOS: All models"*. Note: *"Bluetooth 4 Legacy Advertising and Bluetooth 5 Long Range can be transmitted simultaneously."* Comparison matrix: *ASD-STAN DRI — Broadcast via Bluetooth Legacy Advertising mode: Optional; Long Range mode: Mandatory\*; ASTM F3411-19 — Legacy: Mandatory\*, Long Range: Optional* (\* = one of the allowed methods must be chosen). The document shows Dronetag's add-on: *"It can simultaneously broadcast Bluetooth 4 Legacy Advertisements and Bluetooth 5 Long Range ones."* So **EU add-on modules may legally transmit BT5 LR only** — exactly the case the project currently misses.

opendroneid-core-c README (https://github.com/opendroneid/opendroneid-core-c): *"the ESP32 HW only supports transmitting Bluetooth Legacy Advertising signals. Bluetooth Long Range and Extended Advertising are not supported (ESP32-S3 or ESP32-C3 HW is needed for that)."* and iOS: *"Apple currently does not expose suitable APIs to receive any other transmission method for drone ID signals than BT4 legacy advertising."*

### 1.5 Reference receiver: opendroneid Android app

`Android/app/src/main/java/org/opendroneid/android/bluetooth/BluetoothScanner.java` (https://github.com/opendroneid/receiver-android):
```java
// filter
ScanFilter.Builder builder = new ScanFilter.Builder();
builder.setServiceData(SERVICE_pUUID, OPEN_DRONE_ID_AD_CODE);
// SERVICE_pUUID = ParcelUuid.fromString("0000fffa-0000-1000-8000-00805f9b34fb"); OPEN_DRONE_ID_AD_CODE = { 0x0D }

// "Enable scanning also for devices advertising on an LE Coded PHY S2 or S8"
if (Build.VERSION.SDK_INT >= O && bluetoothAdapter.isLeCodedPhySupported()
        && bluetoothAdapter.isLeExtendedAdvertisingSupported()) {
    scanSettings = new ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .setLegacy(false)
            .setPhy(ScanSettings.PHY_LE_ALL_SUPPORTED).build();
} else { ... SCAN_MODE_LOW_LATENCY only ... }

// onScanResult
byte[] bytes = result.getScanRecord().getBytes();
dataManager.receiveDataBluetooth(bytes, result, logMessageEntry, transportType); // "BT5" if coded PHY else "BT4"
```
i.e. it keys purely on *service-data UUID 0xFFFA + first byte 0x0D*, scans all PHYs, and treats legacy and extended results identically. The raw-byte parser lives in the same folder (`OpenDroneIdParser.java`, `OpenDroneIdDataManager.java`). Supported-phone list (README): only Galaxy S10 / Mate 20 Pro receive BT5 LR reliably; some Qualcomm phones duty-cycle (1 s on / 4 s off) — a useful hint that cheap receivers commonly *time-slice* Coded-PHY scanning.

### 1.6 Bluetooth 5 essentials needed to reason about the scanner

Ellisys "Chapter 4: ADVBE Extended Advertising" (https://ellisys.com/technology/edu_bt01_lecomm_ch04_advbe.pdf): *"ADV_EXT_IND … can only be transmitted on the primary advertising channels … does not include the AdvData."* *"ADV_EXT_IND PDUs include a field called AuxPtr which points to a separate but related packet containing a type of PDU called AUX_ADV_IND. AUX_ADV_IND PDUs are transmitted on the 37 general purpose channels and can include the AdvData field."* *"AuxPtr … tell the scanning device which radio channel the related AUX_ADV_IND PDU will be transmitted on and when it will be transmitted"*. *"AdvData has a maximum size of 254 octets … When performing non-connectable, non-scannable, undirected extended advertising over the LE 1M PHY … leaves a maximum of 251 bytes available for the AdvData field."* *"Application data up to 1,650 bytes can be fragmented and transmitted in one AUX_ADV_IND PDU followed by a series of linked AUX_CHAIN_IND PDUs."* *"Legacy Advertising PDUs may only be transmitted using the LE 1M PHY. In contrast, ADV_EXT_IND PDUs … may use either LE 1M, or the LE Coded PHY … Extended advertising PDUs transmitted on the general-purpose channels may use the LE 1M, LE 2M or LE Coded PHYs."* *"T_MAFS has a default value of 300 µs."* *"To receive application data associated with a received ADV_EXT_IND PDU, a device must next scan on the general-purpose channel indicated by the AuxPtr field."*

Novelbits (https://novelbits.io/bluetooth-long-range-coded-phy/): *"S=2: Data rate = 500 kbps"*, *"S=8: Data rate = 125 kbps"*, *"FEC block 1 is always coded with S=8"*, *"FEC block 2 is coded with S=2 or S=8"*, *"The CI (Coding Indicator) is used to indicate which coding scheme is used in FEC block 2"*, *"The only Primary Advertising type allowed in Coded PHY is of type ADV_EXT_IND."* → a Coded-PHY scanner needs no S2/S8 setting; the preference macros (`ESP_BLE_GAP_PHY_OPTIONS_PREF_S8_CODING`, NimBLE `BLE_HCI_LE_PHY_CODED_S8_PREF`) only affect *connections/transmit*.

**Who follows the AuxPtr?** The Link Layer in the controller: on ESP32 the host only ever sees `HCI LE Extended Advertising Report` events (Bluedroid `ESP_GAP_BLE_EXT_ADV_REPORT_EVT`, NimBLE `BLE_GAP_EVENT_EXT_DISC`) containing the assembled AdvData. Apache NimBLE's controller syscfg says `BLE_LL_CFG_FEAT_LL_EXT_ADV`: *"This option is used to enable/disable support for Extended Advertising Feature. That means extended scanner, advertiser and connect."* (https://raw.githubusercontent.com/apache/mynewt-nimble/master/nimble/controller/syscfg.yml).

---

## 2. ESP32 support matrix for Coded-PHY / extended-advertising scanning

| SoC | `SOC_BLE_50_SUPPORTED` (ESP-IDF `soc_caps.h`) | Controller | Espressif "BLE feature support status" | Arduino 3.3.x host (lib-builder defconfig) | Wi-Fi 2.4 GHz |
|---|---|---|---|---|---|
| ESP32 | **absent** (`SOC_BLE_SUPPORTED (1)`, `SOC_BT_CLASSIC_SUPPORTED (1)`, `SOC_BLE_MULTI_CONN_OPTIMIZATION (1)`) | btdm, BT 4.2 | LE Coded PHY / 2M / Advertising Extensions: *"This feature is not supported on this chip series"* | Bluedroid (`CONFIG_BT_BLE_42_FEATURES_SUPPORTED=y` in defconfig.common) | yes |
| ESP32-S3 | `(1)` | btdm (`libbtdm_app.a`, shared `esp32c3` include dir) | LE Coded PHY, 2M, Extended Advertising, Advertising Extensions, Long Range: **Supported** (controller/Bluedroid/NimBLE); Periodic Adv Sync Transfer: Unsupported | **NimBLE** (`CONFIG_BT_BLUEDROID_ENABLED=n`, `CONFIG_BT_NIMBLE_ENABLED=y`, `CONFIG_BTDM_CTRL_MODE_BLE_ONLY=y`) | yes |
| ESP32-C3 | `(1)` | btdm | LE Long Range (Coded PHY S=2/S=8), 2M, Advertising Extensions: Supported | NimBLE | yes |
| ESP32-C5 | `(1)` + `SOC_ESP_NIMBLE_CONTROLLER (1)`, `SOC_BLE_PERIODIC_ADV_ENH_SUPPORTED`, `SOC_BLE_CTE_SUPPORTED`… | esp-nimble controller | LE Long Range (Coded PHY S=2/S=8), 2 Msym/s, LE Advertising Extensions: Supported | NimBLE | yes (+5 GHz) |
| ESP32-C6 | `(1)` + `SOC_ESP_NIMBLE_CONTROLLER (1)`, `SOC_BLE_USE_WIFI_PWR_CLK_WORKAROUND (1)` | esp-nimble controller | LE 2M, LE Long Range (Coded PHY S=2/S=8), LE Advertising Extensions, PAST: Supported | NimBLE | yes |
| ESP32-H2 | `(1)` + `SOC_ESP_NIMBLE_CONTROLLER (1)` | esp-nimble controller | Long Range, 2M, Advertising Extensions: Supported | NimBLE | **no Wi-Fi** |

Sources: `components/soc/<chip>/include/soc/soc_caps.h` on ESP-IDF master; https://docs.espressif.com/projects/esp-idf/en/latest/<chip>/api-guides/ble/ble-feature-support-status.html for esp32, esp32s3, esp32c3, esp32c5, esp32c6, esp32h2; ESP-FAQ (https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/bt/ble.html): *"the ESP32 hardware only supports Bluetooth LE 4.2. ESP32 has passed Bluetooth LE 5.0 certification, but does not support the new functions of Bluetooth LE 5.0."*; *"ESP32-S3 supports simultaneous broadcasting/scanning/connecting under both 125 Kbps Coded PHY and 1 Mbps PHY modes."*; *"The maximum length is 1650 bytes"* (ext adv). Arduino host selection: `esp32-arduino-lib-builder/configs/defconfig.esp32s3|esp32c3|esp32c5|esp32c6|esp32h2` on `master` (which builds `IDF_BRANCH="release/v5.5"` per `tools/config.sh`, i.e. the 3.3.x libs tag `idf-release_v5.5-b774170f-v3` referenced by arduino-esp32 `release/v3.3.x/package/package_esp32_index.template.json`); arduino-esp32 `libraries/BLE/README.md`: *"NimBLE … is used by all SoCs that are not the ESP32."*, *"Bluedroid will be replaced by NimBLE in version 4.0.0 of the Arduino Core."*

Controller feature flags that reach the precompiled controller at runtime (from `esp_bt.h`/`esp_bt_cfg.h`, expanded wherever `BT_CONTROLLER_INIT_CONFIG_DEFAULT()` is used — i.e. inside NimBLE-Arduino's `NimBLEDevice::init()` with the core's `sdkconfig.h`):
* S3/C3 (`components/bt/include/esp32c3/include/esp_bt.h`, release/v5.5): `BT_CTRL_50_FEATURE_SUPPORT` = `CONFIG_BT_BLE_50_FEATURES_SUPPORTED` (Bluedroid) or `CONFIG_BT_NIMBLE_50_FEATURE_SUPPORT` (NimBLE; IDF default **y** when `SOC_BLE_50_SUPPORTED`) → `.ble_50_feat_supp`; `.scan_duplicate_type = CONFIG_BT_CTRL_SCAN_DUPL_TYPE` (default DEVICE), `.coex_phy_coded_tx_rx_time_limit = CONFIG_BT_CTRL_COEX_PHY_CODED_TX_RX_TLIM_EFF` (default DIS = 0), `.ble_max_act` (default 6).
* C6/C5/H2 (`components/bt/controller/esp32c6/esp_bt_cfg.h`, release/v5.5):
  ```c
  #if CONFIG_BT_NIMBLE_ENABLED
      #if CONFIG_BT_NIMBLE_LL_CFG_FEAT_LE_CODED_PHY
      #define BLE_LL_SCAN_PHY_NUMBER_N (2)      // scan on 1M + Coded
      #else
      #define BLE_LL_SCAN_PHY_NUMBER_N (1)
      #endif
      #if defined(CONFIG_BT_NIMBLE_50_FEATURE_SUPPORT)
      #define DEFAULT_BT_LE_50_FEATURE_SUPPORT (1)
  ```
  `BT_NIMBLE_LL_CFG_FEAT_LE_CODED_PHY` and `BT_NIMBLE_50_FEATURE_SUPPORT` default **y** in `components/bt/host/nimble/Kconfig.in`; the Arduino defconfigs do not override them, so the shipped C5/C6 `sdkconfig.h` is expected to enable 2-PHY scanning (the binary libs tarball could not be inspected directly; verify at runtime by checking `NimBLEScan::start()` returns true / `ble_gap_ext_disc` rc == 0). `BT_NIMBLE_EXT_ADV` defaults **n** in IDF and is **not** set by the Arduino defconfigs → the *core's own* NimBLE host is built without extended scanning; h2zero's NimBLE-Arduino bundles its own host, so `-DCONFIG_BT_NIMBLE_EXT_ADV=1` applies to that copy.

---

## 3. Code

### 3a. arduino-esp32 built-in Bluedroid `BLE` library (works only when `CONFIG_BLUEDROID_ENABLED`)

API as shipped in `libraries/BLE/src/BLEScan.h` (identical on `master` and `release/v3.3.x`):
```cpp
#if defined(CONFIG_BLUEDROID_ENABLED)
#include <esp_gap_ble_api.h>
#endif
#if defined(CONFIG_NIMBLE_ENABLED)
#include <host/ble_gap.h>
#endif
class BLEExtAdvertisingCallbacks;      // forward decl (Bluedroid)
...
#if defined(SOC_BLE_50_SUPPORTED) && defined(CONFIG_BLUEDROID_ENABLED)
  void setExtendedScanCallback(BLEExtAdvertisingCallbacks *cb);
  void setPeriodicScanCallback(BLEPeriodicScanCallbacks *cb);
  esp_err_t stopExtScan();
  esp_err_t setExtScanParams();
  esp_err_t startExtScan(uint32_t duration, uint16_t period);
  esp_err_t setExtScanParams(esp_ble_ext_scan_params_t *ext_scan_params);
#endif
#if defined(CONFIG_NIMBLE_ENABLED)
  void setDuplicateFilter(bool enabled);
  void clearDuplicateCache();
#endif
```
`BLEAdvertisedDevice.h`:
```cpp
#if defined(SOC_BLE_50_SUPPORTED) && defined(CONFIG_BLUEDROID_ENABLED)
class BLEExtAdvertisingCallbacks {
public:
  virtual ~BLEExtAdvertisingCallbacks() {}
#if defined(CONFIG_BLUEDROID_ENABLED)
  virtual void onResult(esp_ble_gap_ext_adv_report_t report) = 0;
#endif
#if defined(CONFIG_NIMBLE_ENABLED)            // dead code: outer guard excludes NimBLE
  virtual void onResult(struct ble_gap_ext_disc_desc report) = 0;
#endif
};
#endif
```
`BLEScan.cpp` (3.3.x): default params and plumbing —
```cpp
esp_ble_ext_scan_params_t ext_scan_params = {
  .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
  .filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
  .scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE,
  .cfg_mask = ESP_BLE_GAP_EXT_SCAN_CFG_UNCODE_MASK | ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK,
  .uncoded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
  .coded_cfg = {BLE_SCAN_TYPE_ACTIVE, 40, 40},
};
esp_err_t BLEScan::setExtScanParams(esp_ble_ext_scan_params_t *p) { return esp_ble_gap_set_ext_scan_params(p); }
esp_err_t BLEScan::startExtScan(uint32_t duration, uint16_t period) { return esp_ble_gap_start_ext_scan(duration, period); }
esp_err_t BLEScan::stopExtScan() { return esp_ble_gap_stop_ext_scan(); }
// handleGAPEvent:
case ESP_GAP_BLE_EXT_ADV_REPORT_EVT:
  if (m_pExtendedScanCb != nullptr) m_pExtendedScanCb->onResult(param->ext_adv_report.params);
```
The NimBLE branch of the same file handles only `BLE_GAP_EVENT_DISC` / `BLE_GAP_EVENT_DISC_COMPLETE` and calls `ble_gap_disc(BLEDevice::m_ownAddrType, duration, &m_scan_params, BLEScan::handleGAPEvent, this)`; `ble_gap_ext_disc` is not used anywhere. The example `libraries/BLE/examples/BLE5_extended_scan/BLE5_extended_scan.ino` starts with:
```cpp
#ifndef CONFIG_BLUEDROID_ENABLED
#error "NimBLE does not support extended scan yet. Try using Bluedroid."
#elif !defined(SOC_BLE_50_SUPPORTED)
#error "This SoC does not support BLE5. Try using ESP32-C3, or ESP32-S3"
```
and its callback distinguishes legacy vs extended with `if (report.event_type & ESP_BLE_GAP_SET_EXT_ADV_PROP_LEGACY) { "BLE4.2" } else { ... report.adv_data_len, report.data_status }`. Comment in the example: *"With this new API advertised device wont be stored in API, it is now user responsibility"* — i.e. once `startExtScan()` is used, **all** reports (legacy included) come through `BLEExtAdvertisingCallbacks::onResult`, not through `BLEAdvertisedDeviceCallbacks`.

ESP-IDF definitions (`esp_gap_ble_api.h`, release/v5.5):
```c
typedef struct {
    esp_ble_gap_adv_type_t event_type;     // uint8_t bitfield
    uint8_t addr_type;
    esp_bd_addr_t addr;                    // uint8_t[6]
#if (CONFIG_BT_BLE_FEAT_PAWR_EN)
    esp_ble_gap_rpt_phy_t primary_phy; esp_ble_gap_rpt_phy_t secondary_phy;
#else
    esp_ble_gap_pri_phy_t primary_phy;     // 1 = 1M, 3 = Coded
    esp_ble_gap_phy_t secondly_phy;        // NOTE spelling: 'secondly_phy' (older IDF: 'secondry_phy')
#endif
    uint8_t sid; uint8_t tx_power; int8_t rssi; uint16_t per_adv_interval;
    uint8_t dir_addr_type; esp_bd_addr_t dir_addr;
    esp_ble_gap_ext_adv_data_status_t data_status;   // 0 COMPLETE, 1 INCOMPLETE (more coming), 2 TRUNCATED
    uint8_t adv_data_len;
    uint8_t adv_data[251];
} esp_ble_gap_ext_adv_report_t;

#define ESP_BLE_ADV_REPORT_EXT_ADV_IND     (1<<0)
#define ESP_BLE_ADV_REPORT_EXT_SCAN_IND    (1<<1)
#define ESP_BLE_ADV_REPORT_EXT_DIRECT_ADV  (1<<2)
#define ESP_BLE_ADV_REPORT_EXT_SCAN_RSP    (1<<3)
#define ESP_BLE_GAP_SET_EXT_ADV_PROP_LEGACY (1 << 4)      // bit 4 of event_type => legacy PDU
#define ESP_BLE_LEGACY_ADV_TYPE_NONCON_IND (0x10)         // legacy ADV_NONCONN_IND report (what ODID BT4 uses)
#define ESP_BLE_LEGACY_ADV_TYPE_IND (0x13) ...
#define ESP_BLE_GAP_PHY_1M 1 / _2M 2 / _CODED 3
#define ESP_BLE_GAP_EXT_SCAN_CFG_UNCODE_MASK 0x01
#define ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK   0x02
typedef struct { esp_ble_scan_type_t scan_type; uint16_t scan_interval; uint16_t scan_window; } esp_ble_ext_scan_cfg_t; // 0.625 ms units, 2.5 ms..40.96 s
typedef enum { BLE_SCAN_DUPLICATE_DISABLE=0, BLE_SCAN_DUPLICATE_ENABLE=1, BLE_SCAN_DUPLICATE_ENABLE_RESET /*BLE5: reset per period*/, BLE_SCAN_DUPLICATE_MAX } esp_ble_scan_duplicate_t;
```
`esp_ble_gap_start_ext_scan(duration, period)`: *"duration: Scan duration in units of 10 ms. Range 0x0001–0xFFFF; 0x0000: Scan continuously until explicitly disabled. period: Time interval between the start of consecutive scan durations, in units of 1.28 seconds; 0x0000: Scan continuously."* (ESP-IDF esp_gap_ble docs). All ext-scan APIs are under `#if (BLE_50_FEATURE_SUPPORT == TRUE)` i.e. `CONFIG_BT_BLE_50_FEATURES_SUPPORTED=y`. ESP-IDF's own `ble50_security_client` example uses `{BLE_SCAN_TYPE_ACTIVE, 40, 40}` for both PHYs, `scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE`, and `esp_ble_gap_start_ext_scan(0, 0)`.

**Minimal Bluedroid sketch (both PHYs, passive, legacy + extended, ODID parse):**
```cpp
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include "opendroneid.h"

#if !defined(CONFIG_BLUEDROID_ENABLED) || !defined(SOC_BLE_50_SUPPORTED)
#error "Needs Bluedroid host on a BLE5 SoC (arduino-esp32 <= 3.2.x on S3/C3, or custom_sdkconfig rebuild)"
#endif

static BLEScan* pScan;

// Walk AD structures; return pointer to ODID bytes (after 0x0D + counter) or nullptr
static const uint8_t* findOdid(const uint8_t* ad, size_t len, size_t* odidLen, uint8_t* counter) {
  size_t i = 0;
  while (i + 1 < len) {
    uint8_t l = ad[i];                 // length of (type + data)
    if (l == 0 || i + 1 + l > len) break;
    const uint8_t* p = &ad[i + 1];
    if (l >= 6 && p[0] == 0x16 && p[1] == 0xFA && p[2] == 0xFF && p[3] == 0x0D) {
      *counter = p[4]; *odidLen = l - 5; return &p[5];
    }
    i += 1 + l;
  }
  return nullptr;
}

class OdidExtCb : public BLEExtAdvertisingCallbacks {
  void onResult(esp_ble_gap_ext_adv_report_t r) override {
    if (r.data_status != ESP_BLE_GAP_EXT_ADV_DATA_COMPLETE) return;   // ODID packs fit one PDU; ignore partials
    bool legacy = r.event_type & ESP_BLE_GAP_SET_EXT_ADV_PROP_LEGACY;  // 0x10 => BT4 ADV_NONCONN_IND etc.
    size_t n; uint8_t ctr;
    const uint8_t* odid = findOdid(r.adv_data, r.adv_data_len, &n, &ctr);
    if (!odid) return;
    // r.addr (uint8_t[6]) = drone MAC, r.rssi dBm, r.primary_phy / r.secondly_phy (1=1M, 3=Coded)
    ODID_UAS_Data uas; memset(&uas, 0, sizeof uas);
    if ((odid[0] >> 4) == ODID_MESSAGETYPE_PACKED) {          // BT5 LR: Message Pack
      odid_message_process_pack(&uas, (uint8_t*)odid, n);     // decodes all N messages
    } else {                                                  // BT4 legacy: single 25-byte message
      decodeOpenDroneID(&uas, (uint8_t*)odid);                // or existing switch on odid[0] & 0xF0
    }
    // ... update UAV table with uas, r.addr, r.rssi, legacy ? "BT4" : "BT5"
  }
};

void setup() {
  BLEDevice::init("");
  pScan = BLEDevice::getScan();
  pScan->setExtendedScanCallback(new OdidExtCb());
  static esp_ble_ext_scan_params_t p = {
    .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
    .filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
    .scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE,          // ODID content changes every second
    .cfg_mask = ESP_BLE_GAP_EXT_SCAN_CFG_UNCODE_MASK | ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK,
    .uncoded_cfg = { BLE_SCAN_TYPE_PASSIVE, 160, 160 },     // 100 ms / 100 ms (0.625 ms units), window == interval
    .coded_cfg   = { BLE_SCAN_TYPE_PASSIVE, 160, 160 },
  };
  pScan->setExtScanParams(&p);
  pScan->startExtScan(0, 0);                                 // continuous
}
void loop() { delay(1000); }
```
Caveat recap: with pioarduino `stable` (arduino 3.3.12) on S3 this does not compile because `CONFIG_BLUEDROID_ENABLED` is undefined (issue https://github.com/espressif/arduino-esp32/issues/11822: *"After updating to Arduino-ESP32 v3.3.0, the default BLE stack is NimBLE, but some code uses Bluedroid-specific APIs (e.g. startExtScan), so it no longer compiles."* — opened 2025-09-12, no maintainer answer visible). Options: pin `platform = https://github.com/pioarduino/platform-espressif32/releases/download/54.03.21/platform-espressif32.zip` (arduino 3.2.x, Bluedroid on S3) — verify the tag exists before relying on it; or pioarduino `custom_sdkconfig` (syntax per issue #533: `custom_sdkconfig =\n    CONFIG_X=y` in platformio.ini; it triggers "HybridCompile" which rebuilds the IDF libs via esp32-arduino-lib-builder; open bugs #533/#546/#549 about rebuilt archives not being linked) with `CONFIG_BT_BLUEDROID_ENABLED=y`, `CONFIG_BT_NIMBLE_ENABLED=n`, `CONFIG_BT_BLE_50_FEATURES_SUPPORTED=y`.

### 3b. h2zero/NimBLE-Arduino 2.x (recommended; what `^2.1.0` resolves to today is 2.5.1)

Build configuration (`nimconfig.h` 2.5.1; docs `Command_line_config.md`, `Bluetooth 5 features.md`):
```c
/**************************************************** 
 *         Extended advertising settings            *
 *        NOT FOR USE WITH ORIGINAL ESP32           *
 ***************************************************/
/** @brief Un-comment to enable extended advertising */
// #define CONFIG_BT_NIMBLE_EXT_ADV 1
// #define CONFIG_BT_NIMBLE_MAX_EXT_ADV_INSTANCES 1      // Range 0-4
// #define CONFIG_BT_NIMBLE_MAX_EXT_ADV_DATA_LEN 1650    // Range 31-1650 (default 251 when unset)
#if CONFIG_BT_NIMBLE_EXT_ADV || CONFIG_BT_NIMBLE_ENABLE_PERIODIC_ADV
#  if defined(CONFIG_IDF_TARGET_ESP32)
#    error Extended advertising is not supported on ESP32.
#  endif
#endif
#if CONFIG_BT_NIMBLE_EXT_ADV
#  define CONFIG_BT_NIMBLE_TRANSPORT_EVT_SIZE 257        // HCI event buffer grows from 70 to 257 bytes
#else
#  define CONFIG_BT_NIMBLE_TRANSPORT_EVT_SIZE 70
#endif
```
Docs: *"Extended advertising is supported when enabled with the config option CONFIG_BT_NIMBLE_EXT_ADV set to a value of 1 … set in nimconfig.h for Arduino, or in build_flags in PlatformIO."* and *"NimBLEScan::start method will scan on both the 1M PHY and the coded PHY standards automatically."* Also: *"NimBLEAdvertising is no longer available for use and is replaced by NimBLEExtAdvertising"* (only matters if the node also advertises). Memory knobs: `CONFIG_BT_NIMBLE_HOST_TASK_STACK_SIZE` (4096), `CONFIG_BT_NIMBLE_MSYS1_BLOCK_COUNT` (12) / size 256, `CONFIG_BT_NIMBLE_ACL_BUF_COUNT` 12, HCI event buffers 30 (hi) + 8 (lo) × 257 B ≈ 9.8 KB with ext adv (vs ≈2.7 KB), `CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_EXTERNAL` (PSRAM), `CONFIG_BT_NIMBLE_PINNED_TO_CORE`, `CONFIG_BT_NIMBLE_ROLE_*_DISABLED` (observer must stay enabled; disabling peripheral/broadcaster saves ~21 kB flash).

Release notes relevant to this project (https://github.com/h2zero/NimBLE-Arduino/releases): 2.3.0 *"Support for esp32c2, esp32c5, esp32c6, esp32h2"*, 2.3.6 *"Support up to 1650 bytes of advertisement with extended advertising"*, 2.3.8 *"Crash on init with esp32 devices with Arduino core 3.3.7 and later"*, *"Memory leak on init/deinit with esp32c6/c5/c2/h2 when NimBLE is enabled in the Arduino core"*, 2.3.9 *"Crash when scanning with esp32c6/c5/c2/h2"*, 2.5.0 *"NimBLEScan user configurable scan response timer"* (`setScanResponseTimeout`), 2.5.1 *"Arduino 3.3.11 build/crash with esp32 c5/c6 variants"* → pin `h2zero/NimBLE-Arduino@^2.5.1`.

API (`NimBLEScan.h` 2.1.3 and 2.5.1 — unchanged):
```cpp
#if CONFIG_BT_NIMBLE_EXT_ADV
    enum Phy { SCAN_1M = 0x01, SCAN_CODED = 0x02, SCAN_ALL = 0x03 };
    void setPhy(Phy phyMask);          // NOT setScanPhy; default is SCAN_ALL
    void setPeriod(uint32_t periodMs); // ext-scan "period", 1.28 s units internally
#endif
bool start(uint32_t duration /*ms, 0=forever*/, bool isContinue = false, bool restart = true);
void setScanCallbacks(NimBLEScanCallbacks* cb, bool wantDuplicates = false);
void setActiveScan(bool active);        // default passive (m_scanParams passive=1)
void setInterval(uint16_t intervalMs);  // ms in 2.x
void setWindow(uint16_t windowMs);
void setDuplicateFilter(uint8_t enabled); // 1 report once, 0 report every time, 2 reset per period (ext scan)
void setFilterPolicy(uint8_t filter);
void setMaxResults(uint8_t maxResults);  // 0 = don't store, callbacks only
bool stop(); bool isScanning(); void clearResults();
class NimBLEScanCallbacks { virtual void onDiscovered(const NimBLEAdvertisedDevice*); virtual void onResult(const NimBLEAdvertisedDevice*); virtual void onScanEnd(const NimBLEScanResults&, int reason); };
```
Implementation facts (`NimBLEScan.cpp` 2.5.1): constructor `m_scanParams{0, 0, BLE_HCI_SCAN_FILT_NO_WL, 0, /*passive*/1, /*filter_duplicates*/1}`; with `CONFIG_BT_NIMBLE_EXT_ADV`, `start()` builds one `ble_gap_ext_disc_params{itvl, window, passive}` and calls `ble_gap_ext_disc(m_ownAddrType, duration/10, m_period, filter_duplicates, filter_policy, limited, (m_phy & SCAN_1M ? &p : NULL), (m_phy & SCAN_CODED ? &p : NULL), handleGapEvent, NULL)` — **the same interval/window is used for both PHYs**. `handleGapEvent` handles `BLE_GAP_EVENT_EXT_DISC` and `BLE_GAP_EVENT_DISC`; legacy is detected by `disc.props & BLE_HCI_ADV_LEGACY_MASK` (0x0010); for extended reports with `data_status == BLE_GAP_EXT_ADV_DATA_STATUS_INCOMPLETE` it waits for the rest before calling back. *"For passive scans or non-scannable advertisements, onDiscovered() fires first, then onResult() immediately."* With `setMaxResults(0)` the device object is deleted after both callbacks.

`NimBLEAdvertisedDevice` (2.5.1): `const NimBLEAddress& getAddress()` (bytes via `getAddress().getBase()->val`, as the C5 firmware already does), `int8_t getRSSI()`, `const std::vector<uint8_t>& getPayload()`, `std::string getServiceData(const NimBLEUUID&)`, `getServiceDataUUID(i)`, `getServiceDataCount()`, `bool isLegacyAdvertisement()`, `isConnectable()`, `isScannable()`, `uint8_t getAdvType()`, `uint8_t getAdvLength()`; under `CONFIG_BT_NIMBLE_EXT_ADV`: `uint8_t getSetId()`, `uint8_t getPrimaryPhy()`, `uint8_t getSecondaryPhy()` (`BLE_HCI_LE_PHY_1M`=1, `_2M`=2, `_CODED`=3), `uint16_t getPeriodicInterval()`. Constructor fills `m_isLegacyAdv{!!(ext_disc.props & BLE_HCI_ADV_LEGACY_MASK)}`, `m_primPhy{ext_disc.prim_phy}`, `m_secPhy{ext_disc.sec_phy}`, `m_payload(ext_disc.data, +length_data)`. **Legacy adverts are still delivered in extended-scan mode** (the controller reports them as extended reports with the legacy bit set; HCI LE Extended Advertising Report event types 0x10/0x12/0x13/0x15 are exactly the legacy PDUs).

NimBLE host constants (`hci_common.h`): `BLE_HCI_ADV_LEGACY_MASK (0x0010)`, `BLE_HCI_ADV_CONN_MASK 0x0001`, `BLE_HCI_ADV_SCAN_MASK 0x0002`, `BLE_HCI_ADV_DATA_STATUS_INCOMPLETE 0x0020`, `BLE_HCI_LE_PHY_1M_PREF_MASK 0x01`, `BLE_HCI_LE_PHY_CODED_PREF_MASK 0x04` (these PREF masks are for *connection* PHY preference, not scanning), `BLE_HCI_MAX_EXT_ADV_DATA_LEN (251)`.

**platformio.ini (S3 and C5 envs):**
```ini
lib_deps =
    h2zero/NimBLE-Arduino@^2.5.1
build_flags =
    -std=gnu++17
    -D CONFIG_BT_NIMBLE_EXT_ADV=1          ; must be a global -D: NimBLE-Arduino reads it when the library compiles
    ; optional tuning
    -D CONFIG_BT_NIMBLE_MAX_EXT_ADV_DATA_LEN=251   ; ODID never exceeds one PDU
    -D CONFIG_BT_NIMBLE_ROLE_PERIPHERAL_DISABLED
    -D CONFIG_BT_NIMBLE_ROLE_BROADCASTER_DISABLED
    -D CONFIG_BT_NIMBLE_ROLE_CENTRAL_DISABLED
```
(The existing `-DCONFIG_BT_NIMBLE_ENABLED=1` in the C5 env is harmless but unnecessary: the 3.3.x core already defines it in `sdkconfig.h`.)

**Minimal NimBLE-Arduino sketch:**
```cpp
#include <NimBLEDevice.h>
#include "opendroneid.h"
#if !CONFIG_BT_NIMBLE_EXT_ADV
#error "Add -D CONFIG_BT_NIMBLE_EXT_ADV=1 to build_flags"
#endif

class OdidScanCb : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    const std::vector<uint8_t>& ad = dev->getPayload();     // full AdvData (legacy or extended)
    size_t i = 0; const uint8_t* odid = nullptr; size_t n = 0;
    while (i + 1 < ad.size()) {                               // walk AD structures (don't assume ODID is first)
      uint8_t l = ad[i]; if (l == 0 || i + 1 + l > ad.size()) break;
      const uint8_t* p = &ad[i + 1];
      if (l >= 6 && p[0] == 0x16 && p[1] == 0xFA && p[2] == 0xFF && p[3] == 0x0D) { odid = &p[5]; n = l - 5; break; }
      i += 1 + l;
    }
    if (!odid) return;
    bool bt5 = !dev->isLegacyAdvertisement();               // BT5 LR: getPrimaryPhy()==BLE_HCI_LE_PHY_CODED (3)
    const uint8_t* mac = dev->getAddress().getBase()->val;  // existing firmware idiom
    int8_t rssi = dev->getRSSI();
    ODID_UAS_Data uas; memset(&uas, 0, sizeof uas);
    if ((odid[0] >> 4) == ODID_MESSAGETYPE_PACKED) odid_message_process_pack(&uas, (uint8_t*)odid, n); // BT5 pack
    else decodeOpenDroneID(&uas, (uint8_t*)odid);                                                    // BT4 single msg
    // ... existing next_uav(mac) / field copy, band = bt5 ? BAND_BLE5 : BAND_BLE
  }
};

void setup() {
  NimBLEDevice::init("DroneID");
  NimBLEScan* s = NimBLEDevice::getScan();
  s->setScanCallbacks(new OdidScanCb(), /*wantDuplicates=*/true); // ODID payload changes every second
  s->setActiveScan(false);                 // ODID is non-connectable, non-scannable: no SCAN_REQ needed
  s->setMaxResults(0);                     // don't buffer devices; callbacks only
  s->setInterval(100); s->setWindow(100);  // continuous listening while scanning
  s->setPhy(NimBLEScan::Phy::SCAN_ALL);    // 1M (legacy BT4) + Coded (BT5 LR)
  s->setPeriod(0);
  s->start(0, false, true);                // 0 = forever
}
void loop() { delay(1000); }
```
If the existing `bleScanTask` keeps calling `getResults(1000,false)` + `clearResults()` that still works, but `start(0)` + callbacks + `setMaxResults(0)` is cheaper and avoids the per-second restart gap during which the controller is not listening on either PHY.

---

## 4. Gotchas

### 4.1 Wi-Fi promiscuous mode + BLE scan on the shared 2.4 GHz radio
* ESP-IDF coexistence guide (esp32s3): *"Wi-Fi, Bluetooth and 802.15.4 modules request RF resources from the coexistence module, and the coexistence module decides who will use the RF resource based on their priority."* Policy: Wi-Fi IDLE → *"RF module is controlled by Bluetooth module"*; CONNECTED → coexistence period ≥100 ms starting at TBTT; *"When both Wi-Fi and BLE are connected, the time slices … each account for 50%."* Table: **Wi-Fi STA connected + BLE scan: stable; SoftAP + BLE scan and Wi-Fi sniffer mode + BLE scan: "Supported but unstable" (C1)**. Requires `CONFIG_ESP_COEX_SW_COEXIST_ENABLE` (Arduino libs enable it) and recommends pinning BT and Wi-Fi tasks to different cores. https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/coexist.html
* This project runs `esp_wifi_set_promiscuous(true)` with channel hopping — the "sniffer + BLE scan" row. Expect lost ADV_EXT_IND/AUX_ADV_IND pairs: a Coded S=8 AUX_ADV_IND with a 234-byte payload is ≈15–17 ms on air (125 kb/s), far longer than a 1M legacy packet (~0.4 ms), so it is far more likely to collide with a Wi-Fi time slice.
* `esp_coexist.h`: `esp_coex_preference_set(ESP_COEX_PREFER_BT|WIFI|BALANCE)` exists but is **deprecated** (*"Use esp_coex_status_bit_set() and esp_coex_status_bit_clear() instead."*). The btdm controller has `CONFIG_BT_CTRL_COEX_PHY_CODED_TX_RX_TLIM` (*"Coexistence: limit on MAX Tx/Rx time for coded-PHY connection … to better avoid dramatic performance deterioration of Wi-Fi"*, default Force Disable) — it concerns Coded-PHY *connections*, not scanning, so nothing to change.
* Scan-window tuning: window == interval keeps the receiver listening whenever the coex arbiter grants BLE; the PHY alternation (below) and Wi-Fi slices then decide the effective duty. Reduce Wi-Fi channel-hop dwell or alternate "BLE-heavy" seconds if BT5 latency is unacceptable.

### 4.2 Scanning two PHYs at once = alternating, not parallel
With both `uncoded_cfg` and `coded_cfg` (or `SCAN_ALL`) the controller scans 1M for one window, then Coded for the next, switching every scan interval. An ESP32 forum thread (*"Problems with simultaneous BLE scan on PHY 1M and PHY Coded"*, https://www.esp32.com/viewtopic.php?t=34187, fetched only as a search snippet; the page itself is behind a bot challenge) reports *"the device first scanning 1M for the duration of scan_window, then switching to Coded PHY, with switching occurring every scan_interval … devices sending advertisement packets every second sometimes not being detected for 20-30 seconds."* Mitigations: window == interval; longer windows (≥ the transmitter's 1 s event) so each PHY gets whole advertising events; or alternate dedicated Coded-only and 1M-only scan periods (NimBLE `setPhy` + `onScanEnd` restart, as in the `NimBLE_extended_scan` example).

### 4.3 Duplicate filtering must be OFF
Controller duplicate filtering is by **device address** by default (`CONFIG_BT_CTRL_SCAN_DUPL_TYPE_DEVICE`: *"Advertising packets with the same address, address type, and advertising type are reported once."*; cache 100 entries, refresh period 0 = never). ODID re-sends the same address with new location data every second → with filtering on you get **one** report per drone, ever. Bluedroid: `scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE`; NimBLE-Arduino: `setScanCallbacks(cb, true)` or `setDuplicateFilter(0)`. (`BLE_SCAN_DUPLICATE_ENABLE_RESET` / NimBLE value 2 reset the cache per ext-scan period — only useful with a nonzero period.)

### 4.4 Advertising data length and buffers
* Per extended report: Bluedroid `adv_data[251]` + `data_status`; NimBLE `BLE_HCI_MAX_EXT_ADV_DATA_LEN (251)` per HCI event, host reassembles chained data up to `CONFIG_BT_NIMBLE_MAX_EXT_ADV_DATA_LEN` (default 251; max 1650 since NimBLE-Arduino 2.3.6). ODID packs are ≤ 234 B of AdvData → one `AUX_ADV_IND`, no chaining, so 251 is enough; just drop reports whose `data_status != COMPLETE`.
* NimBLE HCI event buffer becomes 257 B × 38 buffers when ext adv is on (~+7 KB RAM); keep the host task stack at ≥4096.
* If the node will also *advertise* (Meshtastic-style beacons) with `CONFIG_BT_NIMBLE_EXT_ADV`, the advertising API changes to `NimBLEExtAdvertising`/`NimBLEExtAdvertisement` (h2zero in discussion #669: *"When extended advertisements are enable you must use a different class, NimBLEExtAdvertisement"*).

### 4.5 Active vs passive
ODID BT4 is `ADV_NONCONN_IND`; BT5 LR is *"Non-connectable, Non-scannable"* (ASTM Tables 15/17). Nothing to scan-request, so **passive scanning loses nothing**, avoids transmitting SCAN_REQ (airtime + coex), and in NimBLE-Arduino makes `onResult` fire immediately (no scan-response wait/timeout). The current firmware uses `setActiveScan(true)` — switch to passive.

### 4.6 Known ESP32-S3 Coded-PHY scanning issues (comment threads not readable from this session)
* https://github.com/espressif/esp-idf/issues/15900 "ESP32-S3 Bluedroid Scan extended for coded phy" (IDF v5.4.1): `esp_ble_gap_set_ext_scan_params()` → `BT_BTM: LE ES SetParams: cmd err=0xc` / `BT_HCI: CC evt: op=0x2041, status=0xc` with `coded_cfg.scan_interval = 0x50, scan_window = 0x30`, both PHYs ACTIVE. Labelled Resolution: Done. HCI 0x0C = Command Disallowed; typical causes are calling set-params while a (legacy) scan is already running, or invalid combos — stop any legacy `BLEScan::start()` before `setExtScanParams()`, keep window ≤ interval, and fill both cfgs whenever both mask bits are set.
* https://github.com/espressif/esp-idf/issues/15393 "Scan devices with advertise in BLE Phy Coded S=8" (IDF 5.3.1, S3): the reporter could not see S=8 advertisers after trying `esp_ble_gap_set_preferred_default_phy(...CODED...)` / `..._OPTIONS_PREF_S8_CODING` — those APIs only affect connections; the fix is the extended-scan API with `ESP_BLE_GAP_EXT_SCAN_CFG_CODE_MASK`. Labelled Resolution: Done.
* arduino-esp32 #11822 (above) — 3.3.x removed Bluedroid from the S3 build.
* BT5 LR receivers in general are flaky (opendroneid phone list) — a rooftop test with a known BT5 transmitter (e.g. `transmitter-linux` with an RTL8761B dongle, or `sxjack/remote_id_bt5` on nRF52) is the only way to confirm the S3 path end-to-end.

### 4.7 Parsing details
* Don't assume the ODID AD structure is first or that the length byte is 0x1E on BT5; walk AD structures (snippets above) or use `getServiceData(NimBLEUUID((uint16_t)0xFFFA))` and check `[0] == 0x0D`.
* Message Pack header: `odid[0]>>4 == 0xF`, `odid[1] == 25`, `odid[2] == N ≤ 9 (10 per F3411-19)`, messages at `odid[3 + 25*k]`; `odid_message_process_pack()` in the bundled library validates this.
* Address may be random (TxAdd) on EU modules even though ASTM says "Unique Hardware Address"; key the UAV table on the address as received and on Basic ID when available.
* `isLegacyAdvertisement()` / `event_type & 0x10` is the cheapest BT4-vs-BT5 discriminator; `getPrimaryPhy()==3` / `primary_phy==ESP_BLE_GAP_PHY_CODED` confirms Long Range.

---

## 5. Sources

Standards / ODID
* ASTM F3411-19 (public PDF copy): https://thedroneprofessor.com/wp-content/uploads/2022/11/F3411.40165-UAS-Remote-ID.pdf — §5.4.1, §5.4.5.22–23, §5.4.6 (Table 14), §5.4.7 (Tables 15–17), Table 13; text extracted with pdftotext.
* ASD-STAN, "Direct Remote ID – Introduction to the European digital RID UAS Standard": https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf
* opendroneid-core-c README and `opendroneid.h`: https://github.com/opendroneid/opendroneid-core-c
* opendroneid transmitter-linux `bluetooth.c`/README: https://github.com/opendroneid/transmitter-linux
* opendroneid receiver-android `BluetoothScanner.java`, README phone list: https://github.com/opendroneid/receiver-android
* MAVLink Open Drone ID service: https://mavlink.io/en/services/opendroneid.html

Bluetooth
* Ellisys Expert Education, Ch.4 ADVBE Extended Advertising: https://ellisys.com/technology/edu_bt01_lecomm_ch04_advbe.pdf
* Novelbits, Bluetooth 5 advertisements / Coded PHY: https://novelbits.io/bluetooth-5-advertisements/ , https://novelbits.io/bluetooth-long-range-coded-phy/
* Bluetooth SIG Core 5.4 Link Layer spec (secondary channels, AuxPtr, 1650-octet host data): https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/low-energy-controller/link-layer-specification.html
* Apache NimBLE controller syscfg: https://raw.githubusercontent.com/apache/mynewt-nimble/master/nimble/controller/syscfg.yml ; Mynewt `ble_gap_ext_disc` docs: https://mynewt.apache.org/latest/network/ble_hs/ble_gap.html

Espressif
* `soc_caps.h` per chip: https://github.com/espressif/esp-idf/tree/master/components/soc/{esp32,esp32s3,esp32c3,esp32c5,esp32c6,esp32h2}/include/soc/soc_caps.h
* BLE feature support status pages: https://docs.espressif.com/projects/esp-idf/en/latest/{esp32,esp32s3,esp32c3,esp32c5,esp32c6,esp32h2}/api-guides/ble/ble-feature-support-status.html
* ESP-FAQ BLE: https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/bt/ble.html
* `esp_gap_ble_api.h` (master and release/v5.5): https://github.com/espressif/esp-idf/blob/release/v5.5/components/bt/host/bluedroid/api/include/api/esp_gap_ble_api.h ; GAP docs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/bluetooth/esp_gap_ble.html
* btdm controller Kconfig (C3/S3): https://github.com/espressif/esp-idf/blob/master/components/bt/controller/esp32c3/Kconfig.in ; `esp_bt.h`: components/bt/include/esp32c3/include/esp_bt.h
* esp-nimble controller Kconfig / cfg (C6/C5/H2): components/bt/controller/esp32c6/Kconfig.in, components/bt/controller/esp32c6/esp_bt_cfg.h, components/bt/include/esp32c6/include/esp_bt.h (release/v5.5)
* NimBLE host Kconfig: components/bt/host/nimble/Kconfig.in (release/v5.5)
* Coexistence guide: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/coexist.html ; `esp_coexist.h`
* ble50_security_client example: https://github.com/espressif/esp-idf/tree/master/examples/bluetooth/bluedroid/ble_50/ble50_security_client
* Issues: https://github.com/espressif/esp-idf/issues/15900 , https://github.com/espressif/esp-idf/issues/15393 , https://github.com/espressif/arduino-esp32/issues/11822 , https://github.com/espressif/arduino-esp32/pull/11537

arduino-esp32 / pioarduino
* `libraries/BLE/src/BLEScan.h|.cpp`, `BLEAdvertisedDevice.h`, `examples/BLE5_extended_scan`, `libraries/BLE/README.md` (master & release/v3.3.x): https://github.com/espressif/arduino-esp32
* esp32-arduino-lib-builder `configs/defconfig.*`, `tools/config.sh` (master builds IDF release/v5.5): https://github.com/espressif/esp32-arduino-lib-builder
* pioarduino releases (55.03.312 = Arduino 3.3.12 / IDF 5.5.5): https://github.com/pioarduino/platform-espressif32/releases ; `platform.json`; custom_sdkconfig/HybridCompile issues: https://github.com/pioarduino/platform-espressif32/issues/533 , /issues/546 , /pull/549

NimBLE-Arduino
* Repo, releases: https://github.com/h2zero/NimBLE-Arduino , https://github.com/h2zero/NimBLE-Arduino/releases
* 2.1.3 / 2.5.1 sources: `src/NimBLEScan.h|.cpp`, `src/NimBLEAdvertisedDevice.h|.cpp`, `src/nimconfig.h`, `src/nimble/nimble/host/include/host/ble_gap.h`, `src/nimble/nimble/include/nimble/hci_common.h`
* Docs: `docs/Command_line_config.md`, `docs/Bluetooth 5 features.md`, example `examples/Bluetooth_5/NimBLE_extended_scan`
* Discussion #669 (Coded PHY on XIAO ESP32S3): https://github.com/h2zero/NimBLE-Arduino/discussions/669

Local files inspected (read-only): `/home/user/drone-sentinel/remoteid-c5-5g/platformio.ini`, `/home/user/drone-sentinel/remoteid-c5-5g/src/main.cpp`, `/home/user/drone-sentinel/node-mode-dualcore/platformio.ini`, `/home/user/drone-sentinel/node-mode-dualcore/src/main.cpp`, `/home/user/drone-sentinel/remoteid-mesh-dualcore/platformio.ini`, `/home/user/drone-sentinel/remoteid-c5-5g/src/opendroneid.h`.
