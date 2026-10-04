/*
 * RemoteID Mesh Detect - Dual-Band Edition
 *
 * Supports ESP32-C5 (dual-band 2.4GHz + 5GHz WiFi 6) and ESP32-S3 (2.4GHz only)
 *
 * Detects drones over:
 *   - Open Drone ID (ASTM F3411 / ASD-STAN EN 4709-002): BLE 4 legacy, BLE 5
 *     Long Range extended advertisements, WiFi NAN, WiFi Beacon - on 2.4 GHz
 *     channel 6 and the 5 GHz UNII-3 channels (149-165) Remote ID may use
 *   - DJI proprietary DroneID beacons (WiFi-link DJI aircraft)
 *   - MAVLink telemetry on open WiFi networks
 *   - WiFi / BLE fingerprints of drones and controllers without Remote ID
 *
 * All parsing is in the shared library ../../firmware-common/detect.
 *
 * Output:
 *   USB Serial  - JSON lines for mesh-mapper.py (field "ch" carries the channel;
 *                 36+ means 5 GHz, 0 means BLE)
 *   Serial1 UART (TX=GPIO5, RX=GPIO6) - compact messages for Heltec/Meshtastic relay
 *
 * Channel plan: most of the time on 2.4 GHz channel 6 (the Remote ID channel),
 * with short visits to the 5 GHz Remote ID channels and to 2.4 GHz channels 1
 * and 11 (WiFi-link drone APs, telemetry bridges).
 */

#if !defined(ARDUINO_ARCH_ESP32)
  #error "This program requires an ESP32"
#endif

#include <Arduino.h>
#include <HardwareSerial.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_event.h>
#include <nvs_flash.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "detect.h"

#if !CONFIG_BT_NIMBLE_EXT_ADV
  #error "BLE 5 Long Range needs -D CONFIG_BT_NIMBLE_EXT_ADV=1 in build_flags (see platformio.ini)"
#endif

// ============================================================================
// UART Pins - same wiring as remoteid-mesh-dualcore (Heltec LoRa V4)
// ============================================================================

const int SERIAL1_TX_PIN = 5;   // GPIO5 -> Heltec RX (pin 47)
const int SERIAL1_RX_PIN = 6;   // GPIO6 <- Heltec TX (pin 48)

// ============================================================================
// Board-specific configuration
// ============================================================================

#if defined(CONFIG_IDF_TARGET_ESP32C5) || defined(ARDUINO_XIAO_ESP32C5)
  #define BOARD_IS_C5 1
  #define DUAL_BAND_ENABLED true
  #define BOARD_NAME "XIAO ESP32-C5 (Dual-Band)"
  // C5 is single-core RISC-V
  #define SINGLE_CORE 1
#else
  #define BOARD_IS_C5 0
  #define DUAL_BAND_ENABLED false
  #define BOARD_NAME "XIAO ESP32-S3 (2.4GHz)"
  #define SINGLE_CORE 0
#endif

// ============================================================================
// Detection / channel configuration (override with -D in build_flags)
// ============================================================================

#define CHANNEL_2_4GHZ 6

#ifndef DETECT_HOME_DWELL_MS
#define DETECT_HOME_DWELL_MS 400     // on channel 6 between excursions
#endif
#ifndef DETECT_AWAY_DWELL_MS
#define DETECT_AWAY_DWELL_MS 120     // per other channel (> one beacon interval)
#endif
#ifndef DETECT_MAVLINK
#define DETECT_MAVLINK 1
#endif
#ifndef DETECT_FINGERPRINT
#define DETECT_FINGERPRINT 1
#endif
#define FP_MIN_INTERVAL_MS 30000
#define USB_JSON_MAX 768

// Channels visited between stays on channel 6. 5 GHz UNII-3 is where Remote
// ID is allowed to live on 5 GHz; 1 and 11 are the other common 2.4 GHz AP
// channels.
#if DUAL_BAND_ENABLED
static const uint8_t away_channels[] = { 149, 1, 153, 11, 157, 161, 165 };
#else
static const uint8_t away_channels[] = { 1, 11, 2, 7, 3, 8, 4, 9, 5, 10, 12, 13 };
#endif
#define NUM_AWAY_CHANNELS (sizeof(away_channels) / sizeof(away_channels[0]))

// ============================================================================
// Global state
// ============================================================================

#define MAX_UAVS 8
static DetectRecord uavs[MAX_UAVS];
static portMUX_TYPE uavMux = portMUX_INITIALIZER_UNLOCKED;
static NimBLEScan* pBLEScan = nullptr;
static unsigned long last_status = 0;
static QueueHandle_t printQueue;

// ============================================================================
// UAV Tracking
// ============================================================================

static DetectRecord* next_uav(const uint8_t* mac) {
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].src != DET_SRC_NONE && memcmp(uavs[i].mac, mac, 6) == 0)
      return &uavs[i];
  }
  DetectRecord* slot = nullptr;
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].src == DET_SRC_NONE) { slot = &uavs[i]; break; }
  }
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

// ============================================================================
// BLE Scanning Callbacks (NimBLE 2.x, extended advertising enabled)
// ============================================================================

class MyAdvertisedDeviceCallbacks : public NimBLEScanCallbacks {
public:
  void onResult(const NimBLEAdvertisedDevice* device) override {
    const std::vector<uint8_t>& payload = device->getPayload();
    if (payload.size() < 5) return;
    uint8_t mac[6];
    const uint8_t* val = device->getAddress().getBase()->val;   // LSB first on the wire
    for (int i = 0; i < 6; i++) mac[i] = val[5 - i];
    DetectRecord rec;
    if (!detect_ble_adv(mac, payload.data(), (int)payload.size(), device->getRSSI(),
                        !device->isLegacyAdvertisement(), &rec)) return;
    queueDetection(&rec);
  }
};

// ============================================================================
// JSON Output (USB Serial -> mesh-mapper.py)
// ============================================================================

static void send_json_fast(const DetectRecord* rec) {
  char json[USB_JSON_MAX];
  if (detect_build_json(json, sizeof(json), rec, nullptr) > 0) Serial.println(json);
}

static const char* bandOf(const DetectRecord* rec) {
  if (rec->channel == 0) return "BLE";
  return rec->channel >= 36 ? "5GHz" : "2.4GHz";
}

// ============================================================================
// Compact Message Output (Serial1 UART -> Heltec/Meshtastic)
// ============================================================================

static void print_compact_message(const DetectRecord* rec) {
  static unsigned long lastSendTime = 0;
  const unsigned long sendInterval = 5000;
  const int MAX_MESH_SIZE = 230;

  if (millis() - lastSendTime < sendInterval) return;
  lastSendTime = millis();

  char mac_str[18];
  snprintf(mac_str, sizeof(mac_str), "%02x:%02x:%02x:%02x:%02x:%02x",
           rec->mac[0], rec->mac[1], rec->mac[2], rec->mac[3], rec->mac[4], rec->mac[5]);

  char mesh_msg[MAX_MESH_SIZE];
  int n = 0;
  if (detect_is_heuristic(rec->src)) {
    n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, "Possible drone[%s] (%s %s) %s RSSI:%d",
                  bandOf(rec), rec->vendor, rec->model[0] ? rec->model : rec->ssid, mac_str, rec->rssi);
  } else {
    n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, "Drone[%s]: %s RSSI:%d", bandOf(rec), mac_str, rec->rssi);
    if (n < MAX_MESH_SIZE && rec->uas_id[0])
      n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, " ID:%s", rec->uas_id);
    if (n < MAX_MESH_SIZE && rec->op_id[0])
      n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, " OP:%s", rec->op_id);
    if (n < MAX_MESH_SIZE && (rec->lat != 0.0 || rec->lon != 0.0))
      n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, " https://maps.google.com/?q=%.6f,%.6f",
                    rec->lat, rec->lon);
  }
  if (n > 0 && n < MAX_MESH_SIZE && Serial1.availableForWrite() >= n) {
    Serial1.println(mesh_msg);
  }

  if (rec->pilot_lat != 0.0 || rec->pilot_lon != 0.0) {
    delay(1000);
    char pilot_msg[MAX_MESH_SIZE];
    int pilot_len = snprintf(pilot_msg, sizeof(pilot_msg),
                             "Pilot: https://maps.google.com/?q=%.6f,%.6f",
                             rec->pilot_lat, rec->pilot_lon);
    if (Serial1.availableForWrite() >= pilot_len) {
      Serial1.println(pilot_msg);
    }
  }
}

// ============================================================================
// Channel Hopping Task
// ============================================================================

void channelHopTask(void* parameter) {
  size_t idx = 0;
  Serial.printf("[HOP] ch%d for %dms, then one of {", CHANNEL_2_4GHZ, DETECT_HOME_DWELL_MS);
  for (size_t i = 0; i < NUM_AWAY_CHANNELS; i++)
    Serial.printf("%d%s", away_channels[i], (i < NUM_AWAY_CHANNELS - 1) ? "," : "");
  Serial.printf("} for %dms\n", DETECT_AWAY_DWELL_MS);

  for (;;) {
    esp_wifi_set_channel(CHANNEL_2_4GHZ, WIFI_SECOND_CHAN_NONE);
    vTaskDelay(pdMS_TO_TICKS(DETECT_HOME_DWELL_MS));
    esp_wifi_set_channel(away_channels[idx], WIFI_SECOND_CHAN_NONE);
    idx = (idx + 1) % NUM_AWAY_CHANNELS;
    vTaskDelay(pdMS_TO_TICKS(DETECT_AWAY_DWELL_MS));
  }
}

// ============================================================================
// BLE supervisor task - keeps the continuous scan running
// ============================================================================

void bleScanTask(void* parameter) {
  for (;;) {
    if (pBLEScan && !pBLEScan->isScanning()) pBLEScan->start(0, false, true);
    delay(1000);
  }
}

// ============================================================================
// WiFi Promiscuous Mode Callback
// ============================================================================

void callback(void* buffer, wifi_promiscuous_pkt_type_t type) {
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
    if (len < 72 || len > 600 || (packet->payload[1] & 0x40)) return;   // encrypted / not telemetry-sized
    hit = detect_wifi_data(packet->payload, len, packet->rx_ctrl.rssi, channel, &rec);
  }
#endif
  if (hit) queueDetection(&rec);
}

// ============================================================================
// Printer Task - outputs on both USB Serial and UART (mesh)
// ============================================================================

void printerTask(void* param) {
  DetectRecord rec;
  for (;;) {
    if (xQueueReceive(printQueue, &rec, portMAX_DELAY)) {
      send_json_fast(&rec);
      print_compact_message(&rec);
    }
  }
}

// ============================================================================
// Initialization
// ============================================================================

void initializeSerial() {
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, SERIAL1_RX_PIN, SERIAL1_TX_PIN);
  delay(100);

  Serial.println("\n========================================");
  Serial.println("    RemoteID Mesh Detect - Dual-Band");
  Serial.println("========================================");
  Serial.printf("Board: %s\n", BOARD_NAME);
#if DUAL_BAND_ENABLED
  Serial.println("Mode:  DUAL-BAND (2.4GHz + 5GHz WiFi)");
#else
  Serial.println("Mode:  SINGLE-BAND (2.4GHz WiFi only)");
#endif
  Serial.println("Proto: Remote ID (BLE4, BLE5 LR, NAN, Beacon), DJI DroneID, MAVLink, fingerprints");
  Serial.printf("UART:  TX=GPIO%d, RX=GPIO%d -> Heltec\n", SERIAL1_TX_PIN, SERIAL1_RX_PIN);
  Serial.println("========================================\n");
}

void setup() {
  setCpuFrequencyMhz(160);
  initializeSerial();

  nvs_flash_init();

  // Everything the radio callbacks touch must exist before a radio is armed.
  printQueue = xQueueCreate(MAX_UAVS * 2, sizeof(DetectRecord));
  memset(uavs, 0, sizeof(uavs));

  // WiFi promiscuous mode
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  wifi_promiscuous_filter_t filt;
  filt.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT;
#if DETECT_MAVLINK
  filt.filter_mask |= WIFI_PROMIS_FILTER_MASK_DATA;
#endif
  esp_wifi_set_promiscuous_filter(&filt);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&callback);
  esp_wifi_set_channel(CHANNEL_2_4GHZ, WIFI_SECOND_CHAN_NONE);
  Serial.printf("WiFi promiscuous mode (starting 2.4GHz ch%d, hopping enabled)\n", CHANNEL_2_4GHZ);

  // BLE: passive scan on both the 1M PHY (BLE 4 legacy) and the coded PHY
  // (BLE 5 Long Range), duplicates reported (new Remote ID data every second)
  NimBLEDevice::init("DroneID");
  pBLEScan = NimBLEDevice::getScan();
  pBLEScan->setScanCallbacks(new MyAdvertisedDeviceCallbacks(), true);
  pBLEScan->setActiveScan(false);
  pBLEScan->setMaxResults(0);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(100);
  pBLEScan->setPhy(NimBLEScan::Phy::SCAN_ALL);
  pBLEScan->setPeriod(0);
  pBLEScan->start(0, false, true);
  Serial.println("BLE scanning initialized (NimBLE, 1M + coded PHY)");

  // FreeRTOS tasks - C5 is single-core, S3 is dual-core
#if SINGLE_CORE
  xTaskCreate(bleScanTask, "BLEScanTask", 4096, NULL, 1, NULL);
  xTaskCreate(printerTask, "PrinterTask", 10000, NULL, 1, NULL);
  xTaskCreate(channelHopTask, "ChannelHopTask", 4096, NULL, 2, NULL);
#else
  xTaskCreatePinnedToCore(bleScanTask, "BLEScanTask", 4096, NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(channelHopTask, "ChannelHopTask", 4096, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(printerTask, "PrinterTask", 10000, NULL, 1, NULL, 1);
#endif

  Serial.println("\n[+] Scanning for drones...\n");
}

// ============================================================================
// Main Loop
// ============================================================================

void loop() {
  unsigned long current_millis = millis();

  if ((current_millis - last_status) > 60000UL) {
#if DUAL_BAND_ENABLED
    Serial.println("{\"heartbeat\":\"active\",\"mode\":\"dual-band\",\"bands\":[\"2.4GHz\",\"5GHz\",\"BLE\"]}");
#else
    Serial.println("{\"heartbeat\":\"active\",\"mode\":\"single-band\",\"bands\":[\"2.4GHz\",\"BLE\"]}");
#endif
    last_status = current_millis;
  }
  delay(10);
}
