/*
 * =============================================================================
 * REMOTE NODE - Drone Detector + Mesh Sender
 * colonelpanichacks
 *
 * Dual-core ESP32S3 firmware:
 *   Core 0: WiFi promiscuous sniffing - Open Drone ID (NAN action frames and
 *           Beacon vendor IEs), DJI DroneID beacons, MAVLink telemetry on open
 *           networks, drone/controller access-point fingerprints. Hops across
 *           the 2.4 GHz channels, weighted towards channel 6 (the Remote ID
 *           channel).
 *   Core 1: BLE scanning - Open Drone ID over BLE 4 legacy advertisements AND
 *           BLE 5 Long Range (coded PHY) extended advertisements, which the
 *           European / Japanese add-on Remote ID modules use. Plus BLE device
 *           name fingerprints of controllers.
 *
 * All protocol parsing lives in the shared library ../../firmware-common/detect
 * (unit-tested on a desktop); this file is radio set-up, aggregation and I/O.
 *
 * Detected drone JSON is sent to:
 *   - USB Serial (for local monitoring / direct mesh-mapper.py connection)
 *   - Serial1 UART (GPIO5 TX / GPIO6 RX -> Heltec V3 running Meshtastic)
 *
 * USB output NEVER blocks: on this board Serial is the native USB CDC
 * (HWCDC), whose write() waits on the TX ring when an attached host stops
 * draining (~2s per call worst case). Everything steady-state goes through a
 * non-blocking ring that drops oldest-first, so a stalled or absent host can
 * never back up printerTask and stall mesh sending. Same disease the home
 * node was hardened against; see main_home.cpp's header for the full story.
 *
 * JSON format (matches mesh-mapper.py; fields are omitted when unknown):
 *   {"mac":"xx:xx:xx:xx:xx:xx","rssi":-50,"node_id":"A1B2",
 *    "drone_lat":0.0,"drone_long":0.0,"drone_altitude":0,
 *    "pilot_lat":0.0,"pilot_long":0.0,"basic_id":"...","op_id":"...",
 *    "id_type":1,"src":"odid_ble5","ua_type":2,"eu_cat":1,"eu_class":2, ...}
 *   See firmware-common/README.md for the full field list.
 *
 * Build-time knobs (platformio.ini build_flags, all optional):
 *   -DDETECT_WIFI_HOP=0        stay on channel 6 only (maximum Remote ID
 *                              duty cycle, no DJI WiFi-link / toy-drone APs
 *                              on other channels)
 *   -DDETECT_HOME_DWELL_MS=700 time on channel 6 between excursions
 *   -DDETECT_AWAY_DWELL_MS=250 time on each other channel
 *   -DDETECT_MAVLINK=0         do not capture data frames
 *   -DDETECT_FINGERPRINT=0     drop heuristic (no Remote ID) hits
 * =============================================================================
 */

#if !defined(ARDUINO_ARCH_ESP32)
  #error "This program requires an ESP32S3"
#endif

#include <Arduino.h>
#include <HardwareSerial.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_mac.h>
#include <nvs_flash.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "detect.h"

#if !CONFIG_BT_NIMBLE_EXT_ADV
  #error "BLE 5 Long Range needs -D CONFIG_BT_NIMBLE_EXT_ADV=1 in build_flags (see platformio.ini)"
#endif

// =============================================================================
// Detection configuration
// =============================================================================
#ifndef DETECT_WIFI_HOP
#define DETECT_WIFI_HOP 1
#endif
#ifndef DETECT_HOME_CHANNEL
#define DETECT_HOME_CHANNEL 6       // ASTM / ASD-STAN Remote ID WiFi channel
#endif
#ifndef DETECT_HOME_DWELL_MS
#define DETECT_HOME_DWELL_MS 700
#endif
#ifndef DETECT_AWAY_DWELL_MS
#define DETECT_AWAY_DWELL_MS 250    // > 2 beacon intervals of a WiFi-link drone AP
#endif
#ifndef DETECT_MAVLINK
#define DETECT_MAVLINK 1
#endif
#ifndef DETECT_FINGERPRINT
#define DETECT_FINGERPRINT 1
#endif

// Heuristic (fingerprint) hits repeat with every beacon, ~10x per second per
// network. One report per device per 30 s is plenty for a "possible drone"
// flag and keeps them off the LoRa airtime budget.
#define FP_MIN_INTERVAL_MS 30000

// A Meshtastic text message carries at most ~233 bytes. The JSON builder
// drops low-priority fields to fit; USB gets the full record.
#define MESH_JSON_MAX 230
#define USB_JSON_MAX  768

// =============================================================================
// Pin Definitions
// =============================================================================
// UART to Heltec V3 (Meshtastic)
static const int SERIAL1_TX_PIN = 5;   // GPIO5 -> Heltec RX
static const int SERIAL1_RX_PIN = 6;   // GPIO6 <- Heltec TX

// LED on XIAO ESP32S3 (active LOW / inverted logic)
#define LED_PIN 21

// =============================================================================
// Unique Node ID (derived from ESP32 MAC at boot)
// Used by home node to deduplicate detections from multiple remote nodes
// =============================================================================
static char nodeId[5] = "0000";  // 4-char hex, e.g. "A1B2"

static void generateNodeId() {
  uint8_t mac[6];
  esp_efuse_mac_get_default(mac);
  // Use last 2 bytes of factory MAC -> unique 4-hex-char ID per board
  snprintf(nodeId, sizeof(nodeId), "%02X%02X", mac[4], mac[5]);
}

// =============================================================================
// Non-blocking USB output ring
//
// Two tasks write USB output here (printerTask: detections/heartbeat,
// uartForwardTask: Heltec echoes), so all ring access is mutex-guarded.
// Nothing steady-state calls Serial.print directly. txFlush() pushes queued
// bytes only as far as availableForWrite() permits, so a host that stops
// reading can never stall the node. When the queue fills, the OLDEST bytes
// are dropped: a fresh detection is worth more than a stale one.
// =============================================================================
#define TXQ_SIZE       8192
#define TXQ_MAX_DRAIN  1024    // Max bytes pushed to USB per flush

static uint8_t  txq[TXQ_SIZE];
static volatile size_t txHead = 0;   // write index
static volatile size_t txTail = 0;   // read index
static uint32_t txDroppedBytes = 0;
static SemaphoreHandle_t txqMutex = nullptr;

static inline size_t txUsed() {
  return (txHead >= txTail) ? (txHead - txTail) : (TXQ_SIZE - txTail + txHead);
}

static inline size_t txFree() {
  return TXQ_SIZE - txUsed() - 1;   // keep one slot free to distinguish states
}

static void txWrite(const char* data, size_t len) {
  if (len == 0) return;
  if (len > TXQ_SIZE - 1) {           // absurdly long, keep the tail of it
    data += (len - (TXQ_SIZE - 1));
    len = TXQ_SIZE - 1;
  }
  if (!txqMutex) return;
  if (xSemaphoreTake(txqMutex, pdMS_TO_TICKS(50)) != pdTRUE) return;  // drop rather than block
  if (txFree() < len) {
    // Drop whole bytes from the oldest end until `len` bytes fit.
    while (txFree() < len && txUsed() > 0) {
      txTail = (txTail + 1) % TXQ_SIZE;
      txDroppedBytes++;
    }
  }
  for (size_t i = 0; i < len; i++) {
    txq[txHead] = (uint8_t)data[i];
    txHead = (txHead + 1) % TXQ_SIZE;
  }
  xSemaphoreGive(txqMutex);
}

static void txPrintln(const char* s) {
  txWrite(s, strlen(s));
  txWrite("\n", 1);
}

static void txPrintf(const char* fmt, ...) {
  char buf[256];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  if (n > 0) txWrite(buf, (size_t)min((int)sizeof(buf) - 1, n));
}

// Push queued bytes to USB, strictly bounded and strictly non-blocking.
static void txFlush() {
  size_t budget = TXQ_MAX_DRAIN;
  if (!txqMutex) return;
  if (xSemaphoreTake(txqMutex, pdMS_TO_TICKS(50)) != pdTRUE) return;
  while (txUsed() > 0 && budget > 0) {
    // availableForWrite() is how much the CDC ring will take right now.
    // Writing only that much guarantees write() returns without waiting.
    int room = Serial.availableForWrite();
    if (room <= 0) break;             // host not draining - try again next pass

    size_t chunk = txUsed();
    if (chunk > (size_t)room) chunk = (size_t)room;
    if (chunk > budget) chunk = budget;
    // Do not wrap past the end of the ring in one write
    if (txTail + chunk > TXQ_SIZE) chunk = TXQ_SIZE - txTail;

    size_t wrote = Serial.write(&txq[txTail], chunk);
    if (wrote == 0) break;            // made no progress, do not spin
    txTail = (txTail + wrote) % TXQ_SIZE;
    budget -= wrote;
  }
  xSemaphoreGive(txqMutex);
}

// =============================================================================
// UAV Tracking
//
// One slot per aircraft MAC. Remote ID spreads identity and position over
// separate messages (and BLE 4 sends one message per advertisement), so each
// frame is merged into the slot and a snapshot of the slot is what gets sent.
// The WiFi callback (core 0) and the BLE callback (NimBLE host task) both
// touch the table, hence the spinlock.
// =============================================================================
#define MAX_UAVS 32
static DetectRecord uavs[MAX_UAVS];
static portMUX_TYPE uavMux = portMUX_INITIALIZER_UNLOCKED;
static NimBLEScan* pBLEScan = nullptr;
static unsigned long last_status = 0;

// Thread-safe print queue (BLE callback + WiFi callback -> printer task)
static QueueHandle_t printQueue;

static DetectRecord* next_uav(const uint8_t* mac) {
  // First: find existing entry for this MAC
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].src != DET_SRC_NONE && memcmp(uavs[i].mac, mac, 6) == 0)
      return &uavs[i];
  }
  // Second: find empty slot
  DetectRecord* slot = nullptr;
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].src == DET_SRC_NONE) { slot = &uavs[i]; break; }
  }
  // Fallback: evict oldest entry
  if (!slot) {
    uint32_t oldest_time = UINT32_MAX;
    int oldest_idx = 0;
    for (int i = 0; i < MAX_UAVS; i++) {
      if (uavs[i].last_seen < oldest_time) {
        oldest_time = uavs[i].last_seen;
        oldest_idx = i;
      }
    }
    slot = &uavs[oldest_idx];
  }
  detect_record_init(slot);
  memcpy(slot->mac, mac, 6);
  return slot;
}

// Called from the WiFi promiscuous callback and the BLE scan callback.
static void queueDetection(DetectRecord* rec) {
  uint32_t now = millis();
  rec->last_seen = now;

  if (detect_is_heuristic(rec->src)) {
#if !DETECT_FINGERPRINT
    return;
#endif
    if (!detect_throttle(rec->mac, now, FP_MIN_INTERVAL_MS)) return;
  }

  DetectRecord tmp;
  portENTER_CRITICAL(&uavMux);
  DetectRecord* slot = next_uav(rec->mac);
  detect_record_merge(slot, rec);
  tmp = *slot;
  portEXIT_CRITICAL(&uavMux);

  if (printQueue) {
    BaseType_t woken = pdFALSE;
    xQueueSendFromISR(printQueue, &tmp, &woken);
    if (woken) portYIELD_FROM_ISR();
  }
}

// =============================================================================
// BLE scan callback - Open Drone ID (BLE 4 + BLE 5 Long Range) and names
// =============================================================================
class DroneScanCallbacks : public NimBLEScanCallbacks {
public:
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    const std::vector<uint8_t>& ad = dev->getPayload();
    if (ad.size() < 5) return;

    // ble_addr_t stores the address least-significant byte first; reverse it
    // so the MAC string reads the way the address is printed everywhere else.
    uint8_t mac[6];
    const uint8_t* val = dev->getAddress().getBase()->val;
    for (int i = 0; i < 6; i++) mac[i] = val[5 - i];

    DetectRecord rec;
    bool extended = !dev->isLegacyAdvertisement();   // BLE 5 extended advert (Long Range)
    if (!detect_ble_adv(mac, ad.data(), (int)ad.size(), dev->getRSSI(), extended, &rec)) return;
    queueDetection(&rec);
  }
};

// =============================================================================
// WiFi Promiscuous Callback - management frames (Remote ID NAN + Beacon, DJI
// DroneID, SSID/OUI fingerprints) and data frames (MAVLink on open networks)
// =============================================================================
static void wifiCallback(void* buffer, wifi_promiscuous_pkt_type_t type) {
  wifi_promiscuous_pkt_t* packet = (wifi_promiscuous_pkt_t*)buffer;
  int len = packet->rx_ctrl.sig_len;
  if (len <= 0) return;
  uint8_t channel = (uint8_t)packet->rx_ctrl.channel;

  DetectRecord rec;
  bool hit = false;
  if (type == WIFI_PKT_MGMT) {
    hit = detect_wifi_mgmt(packet->payload, len, packet->rx_ctrl.rssi, channel, &rec);
  }
#if DETECT_MAVLINK
  else if (type == WIFI_PKT_DATA) {
    // Nearly all data frames are encrypted (Protected bit) or far larger than
    // a telemetry datagram; reject those before touching the parser.
    if (len < 72 || len > 600 || (packet->payload[1] & 0x40)) return;
    hit = detect_wifi_data(packet->payload, len, packet->rx_ctrl.rssi, channel, &rec);
  }
#endif
  if (hit) queueDetection(&rec);
}

// =============================================================================
// JSON Output - Sends to USB Serial + UART (Heltec V3 mesh)
// =============================================================================
static void send_json(const DetectRecord* rec) {
  char json[USB_JSON_MAX];
  if (detect_build_json(json, sizeof(json), rec, nodeId) <= 0) return;

  // USB Serial (local monitoring / direct connection to mesh-mapper.py).
  // Queued, never blocking - a stalled host must not back up mesh sending.
  txPrintln(json);

  // LED flash on detection (quick blink)
  digitalWrite(LED_PIN, LOW);   // ON (inverted)
}

// Send to the Heltec V3, paced. Meshtastic's serial module frames its input
// with readBytes(237 bytes / 250ms timeout): writes closer together than that
// are coalesced into one packet (and the overflow splits into a broken
// fragment), so one message per window is the fastest reliable rate. LoRa
// airtime cannot move messages faster than this anyway. Pending detections sit
// in a small queue; when it overflows the OLDEST is dropped - the home node's
// dedup makes a fresher position strictly better than a stale one.
#define MESH_SEND_INTERVAL_MS 350
#define MESH_QUEUE_DEPTH      4

static char     meshPending[MESH_QUEUE_DEPTH][MESH_JSON_MAX + 8];
static int      meshPendHead = 0;      // next slot to send
static int      meshPendCount = 0;
static uint32_t lastMeshSend = 0;
static uint32_t meshDropped = 0;

// Only ever called from printerTask, so no locking is needed.
static void send_to_mesh(const DetectRecord* rec) {
  int slot = (meshPendHead + meshPendCount) % MESH_QUEUE_DEPTH;
  if (meshPendCount == MESH_QUEUE_DEPTH) {
    meshPendHead = (meshPendHead + 1) % MESH_QUEUE_DEPTH;   // drop oldest
    meshPendCount--;
    meshDropped++;
  }
  // The builder drops low-priority fields so the line fits one LoRa packet.
  if (detect_build_json(meshPending[slot], MESH_JSON_MAX, rec, nodeId) <= 0) return;
  meshPendCount++;
}

static void meshQueueDrain() {
  if (meshPendCount == 0) return;
  uint32_t now = millis();
  if ((uint32_t)(now - lastMeshSend) < MESH_SEND_INTERVAL_MS) return;

  const char* msg = meshPending[meshPendHead];
  int len = strlen(msg);
  if (Serial1.availableForWrite() >= len + 2) {   // +2 for println's \r\n
    Serial1.println(msg);
    lastMeshSend = now;
    meshPendHead = (meshPendHead + 1) % MESH_QUEUE_DEPTH;
    meshPendCount--;
  }
}

// =============================================================================
// FreeRTOS Tasks
// =============================================================================

// Printer task: dequeues records and outputs JSON (runs on core 1)
static void printerTask(void* param) {
  DetectRecord rec;
  for (;;) {
    // Bounded wait instead of portMAX_DELAY so queued mesh messages keep
    // draining even when no new detections arrive.
    if (xQueueReceive(printQueue, &rec, pdMS_TO_TICKS(100))) {
      send_json(&rec);
      send_to_mesh(&rec);
    }
    meshQueueDrain();
    txFlush();   // runs at least every 100ms even with zero detections
  }
}

// BLE supervisor: the scan runs continuously from callbacks; restart it if
// the controller ever stops it (runs on core 1)
static void bleScanTask(void* param) {
  for (;;) {
    if (pBLEScan && !pBLEScan->isScanning()) {
      pBLEScan->start(0, false, true);   // 0 = forever
    }
    delay(1000);
  }
}

// WiFi channel plan (runs on core 0). Remote ID lives on channel 6, so most
// of the time is spent there; the other channels are visited briefly to catch
// DJI WiFi-link aircraft, toy-drone / FPV access points and MAVLink bridges,
// which sit on whatever channel their AP picked. 12/13 are legal receive
// channels in Europe and Japan.
static void wifiHopTask(void* param) {
  static const uint8_t away[] = { 1, 11, 2, 7, 3, 8, 4, 9, 5, 10, 12, 13 };
  size_t idx = 0;
  for (;;) {
#if DETECT_WIFI_HOP
    esp_wifi_set_channel(DETECT_HOME_CHANNEL, WIFI_SECOND_CHAN_NONE);
    vTaskDelay(pdMS_TO_TICKS(DETECT_HOME_DWELL_MS));
    esp_wifi_set_channel(away[idx], WIFI_SECOND_CHAN_NONE);
    idx = (idx + 1) % (sizeof(away) / sizeof(away[0]));
    vTaskDelay(pdMS_TO_TICKS(DETECT_AWAY_DWELL_MS));
#else
    vTaskDelay(pdMS_TO_TICKS(1000));
#endif
  }
}

// UART forward task: anything the Heltec sends back gets echoed to USB
// (mesh acknowledgments, Meshtastic debug output, etc.)
static void uartForwardTask(void* param) {
  static char lineBuf[512];
  static int linePos = 0;

  for (;;) {
    while (Serial1.available()) {
      char c = Serial1.read();
      if (c == '\n' || c == '\r') {
        if (linePos > 0) {
          lineBuf[linePos] = '\0';
          txPrintln(lineBuf);   // queued, never blocking
          linePos = 0;
        }
      } else if (linePos < (int)sizeof(lineBuf) - 1) {
        lineBuf[linePos++] = c;
      }
    }
    delay(10);
  }
}

// =============================================================================
// Arduino Entry Points
// =============================================================================
void setup() {
  delay(3000);  // Boot delay (Meshtastic serial init timing)
  setCpuFrequencyMhz(160);

  // Generate unique node ID from ESP32 factory MAC
  generateNodeId();

  // Serial init
  Serial.begin(115200);

  // Must exist before the first txPrintln below - txWrite drops anything
  // queued while this is null, which silently ate the boot banner.
  txqMutex = xSemaphoreCreateMutex();
  // Without a TX ring buffer, availableForWrite() tops out at the 128-byte
  // hardware FIFO. The detection JSON is ~200 bytes, so the send gate
  // (availableForWrite() >= len) could NEVER pass and the remote node never
  // transmitted a single detection. The buffer must be set before begin().
  Serial1.setTxBufferSize(1024);
  Serial1.begin(115200, SERIAL_8N1, SERIAL1_RX_PIN, SERIAL1_TX_PIN);

  // LED init
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // OFF (inverted logic on XIAO)

  txPrintln("");
  txPrintln("Mesh Detect - Node Mode / REMOTE");
  txPrintf("Node ID: %s   Remote ID (BLE4/BLE5-LR/NAN/Beacon) + DJI DroneID + MAVLink + fingerprints -> mesh\n", nodeId);
#if DETECT_WIFI_HOP
  txPrintf("WiFi: ch%d %dms, other channels %dms each\n", DETECT_HOME_CHANNEL, DETECT_HOME_DWELL_MS, DETECT_AWAY_DWELL_MS);
#else
  txPrintf("WiFi: fixed ch%d\n", DETECT_HOME_CHANNEL);
#endif

  nvs_flash_init();

  // Everything the radio callbacks touch must exist BEFORE any radio is armed.
  // esp_wifi_set_promiscuous_rx_cb() starts delivering frames immediately, and
  // the callback pushes to printQueue - creating the queue afterwards left a
  // window where a frame arriving on a busy channel hit a null handle and
  // panicked at boot.
  printQueue = xQueueCreate(MAX_UAVS * 2, sizeof(DetectRecord));
  memset(uavs, 0, sizeof(uavs));

  // WiFi promiscuous mode. Management frames carry Remote ID / DJI / SSIDs;
  // data frames are only needed for MAVLink on open networks.
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  wifi_promiscuous_filter_t filt;
  filt.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT;
#if DETECT_MAVLINK
  filt.filter_mask |= WIFI_PROMIS_FILTER_MASK_DATA;
#endif
  esp_wifi_set_promiscuous_filter(&filt);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&wifiCallback);
  esp_wifi_set_channel(DETECT_HOME_CHANNEL, WIFI_SECOND_CHAN_NONE);

  // BLE scanner: passive (Remote ID is non-connectable, non-scannable), with
  // duplicates reported because the same address re-broadcasts new data every
  // second, on both the 1M PHY (BLE 4 legacy) and the coded PHY (BLE 5 Long
  // Range). Legacy adverts are still reported in extended-scan mode.
  NimBLEDevice::init("DroneID");
  pBLEScan = NimBLEDevice::getScan();
  pBLEScan->setScanCallbacks(new DroneScanCallbacks(), /*wantDuplicates=*/true);
  pBLEScan->setActiveScan(false);
  pBLEScan->setMaxResults(0);           // callbacks only, nothing buffered
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(100);
  pBLEScan->setPhy(NimBLEScan::Phy::SCAN_ALL);
  pBLEScan->setPeriod(0);
  pBLEScan->start(0, false, true);

  // Launch FreeRTOS tasks on separate cores
  xTaskCreatePinnedToCore(bleScanTask,     "BLE",     4096,  NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(wifiHopTask,     "WiFiHop", 4096,  NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(printerTask,     "Print",   10000, NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(uartForwardTask, "UART_FW", 4096,  NULL, 1, NULL, 1);

  txPrintln("Scanning.");
  txPrintln("");
}

void loop() {
  unsigned long now = millis();

  // Heartbeat every 60 seconds (queued, never blocking)
  if (now - last_status > 60000UL) {
    txPrintln("{\"heartbeat\":\"remote_node active\"}");
    last_status = now;
  }

  // LED off after brief flash (set ON by send_json)
  static unsigned long ledOffTime = 0;
  static bool ledOn = false;
  if (digitalRead(LED_PIN) == LOW) {
    if (!ledOn) { ledOn = true; ledOffTime = now; }
    if (now - ledOffTime > 80) {
      digitalWrite(LED_PIN, HIGH);  // OFF
      ledOn = false;
    }
  }

  delay(10);
}
