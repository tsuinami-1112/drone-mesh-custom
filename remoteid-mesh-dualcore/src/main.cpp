/*
 * RemoteID Mesh Detect - Standard dual-core build (XIAO ESP32-S3 / ESP32-C6)
 *
 * Detects drones over:
 *   - Open Drone ID (ASTM F3411 / ASD-STAN EN 4709-002): BLE 4 legacy, BLE 5
 *     Long Range extended advertisements, WiFi NAN action frames, WiFi Beacon
 *     vendor IEs - every message type incl. Operator ID and both Basic IDs
 *   - DJI proprietary DroneID beacons (WiFi-link DJI aircraft)
 *   - MAVLink telemetry on open WiFi networks
 *   - WiFi / BLE fingerprints of drones and controllers without Remote ID
 *
 * All parsing is in the shared library ../../firmware-common/detect.
 *
 * Output:
 *   USB Serial  - one JSON line per detection for mesh-mapper.py
 *   Serial1 UART (TX=GPIO5, RX=GPIO6) - compact text for a Heltec/Meshtastic
 *                 relay, throttled to one message every 5 s
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

// ---------------------------------------------------------------------------
// Configuration (override with -D in platformio.ini build_flags)
// ---------------------------------------------------------------------------
#ifndef DETECT_WIFI_HOP
#define DETECT_WIFI_HOP 1
#endif
#ifndef DETECT_HOME_CHANNEL
#define DETECT_HOME_CHANNEL 6
#endif
#ifndef DETECT_HOME_DWELL_MS
#define DETECT_HOME_DWELL_MS 700
#endif
#ifndef DETECT_AWAY_DWELL_MS
#define DETECT_AWAY_DWELL_MS 250
#endif
#ifndef DETECT_MAVLINK
#define DETECT_MAVLINK 1
#endif
#ifndef DETECT_FINGERPRINT
#define DETECT_FINGERPRINT 1
#endif
#define FP_MIN_INTERVAL_MS 30000
#define USB_JSON_MAX 768

#if defined(CONFIG_IDF_TARGET_ESP32C6) || defined(CONFIG_IDF_TARGET_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C5)
  #define SINGLE_CORE 1
#else
  #define SINGLE_CORE 0
#endif

const int SERIAL1_RX_PIN = 6;
const int SERIAL1_TX_PIN = 5;

// ---------------------------------------------------------------------------
// UAV table: one slot per MAC, frames merged in, snapshots queued out
// ---------------------------------------------------------------------------
#define MAX_UAVS 16
static DetectRecord uavs[MAX_UAVS];
static portMUX_TYPE uavMux = portMUX_INITIALIZER_UNLOCKED;
static NimBLEScan* pBLEScan = nullptr;
static unsigned long last_status = 0;
static QueueHandle_t printQueue;

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

// ---------------------------------------------------------------------------
// BLE: Open Drone ID over BLE 4 and BLE 5 Long Range, BLE name fingerprints
// ---------------------------------------------------------------------------
class DroneScanCallbacks : public NimBLEScanCallbacks {
public:
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    const std::vector<uint8_t>& ad = dev->getPayload();
    if (ad.size() < 5) return;
    uint8_t mac[6];
    const uint8_t* val = dev->getAddress().getBase()->val;   // LSB first on the wire
    for (int i = 0; i < 6; i++) mac[i] = val[5 - i];
    DetectRecord rec;
    if (!detect_ble_adv(mac, ad.data(), (int)ad.size(), dev->getRSSI(),
                        !dev->isLegacyAdvertisement(), &rec)) return;
    queueDetection(&rec);
  }
};

// ---------------------------------------------------------------------------
// WiFi promiscuous callback
// ---------------------------------------------------------------------------
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
    if (len < 72 || len > 600 || (packet->payload[1] & 0x40)) return;   // encrypted / not telemetry-sized
    hit = detect_wifi_data(packet->payload, len, packet->rx_ctrl.rssi, channel, &rec);
  }
#endif
  if (hit) queueDetection(&rec);
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------
static void send_json_fast(const DetectRecord* rec) {
  char json[USB_JSON_MAX];
  if (detect_build_json(json, sizeof(json), rec, nullptr) > 0) Serial.println(json);
}

// Compact human-readable line for a Meshtastic text channel, one per 5 s.
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
    n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, "Possible drone (%s %s) %s RSSI:%d",
                  rec->vendor, rec->model[0] ? rec->model : rec->ssid, mac_str, rec->rssi);
  } else {
    n += snprintf(mesh_msg + n, sizeof(mesh_msg) - n, "Drone: %s RSSI:%d", mac_str, rec->rssi);
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

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------
static void bleScanTask(void* parameter) {
  for (;;) {
    if (pBLEScan && !pBLEScan->isScanning()) pBLEScan->start(0, false, true);
    delay(1000);
  }
}

// Mostly channel 6 (Remote ID), short visits to every other 2.4 GHz channel
// for DJI WiFi-link aircraft, toy-drone APs and MAVLink bridges.
static void wifiHopTask(void* parameter) {
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

static void printerTask(void* param) {
  DetectRecord rec;
  for (;;) {
    if (xQueueReceive(printQueue, &rec, portMAX_DELAY)) {
      send_json_fast(&rec);
      print_compact_message(&rec);
    }
  }
}

// ---------------------------------------------------------------------------
// Setup / loop
// ---------------------------------------------------------------------------
void initializeSerial() {
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, SERIAL1_RX_PIN, SERIAL1_TX_PIN);
}

void setup() {
  setCpuFrequencyMhz(160);
  initializeSerial();
  nvs_flash_init();

  // Everything the radio callbacks touch must exist before a radio is armed.
  printQueue = xQueueCreate(MAX_UAVS * 2, sizeof(DetectRecord));
  memset(uavs, 0, sizeof(uavs));

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

  // Passive scan on both PHYs, duplicates reported (Remote ID re-uses the
  // address with new data every second).
  NimBLEDevice::init("DroneID");
  pBLEScan = NimBLEDevice::getScan();
  pBLEScan->setScanCallbacks(new DroneScanCallbacks(), true);
  pBLEScan->setActiveScan(false);
  pBLEScan->setMaxResults(0);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(100);
  pBLEScan->setPhy(NimBLEScan::Phy::SCAN_ALL);
  pBLEScan->setPeriod(0);
  pBLEScan->start(0, false, true);

#if SINGLE_CORE
  xTaskCreate(bleScanTask, "BLEScanTask", 4096, NULL, 1, NULL);
  xTaskCreate(wifiHopTask, "WiFiHopTask", 4096, NULL, 1, NULL);
  xTaskCreate(printerTask, "PrinterTask", 10000, NULL, 1, NULL);
#else
  xTaskCreatePinnedToCore(bleScanTask, "BLEScanTask", 4096, NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(wifiHopTask, "WiFiHopTask", 4096, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(printerTask, "PrinterTask", 10000, NULL, 1, NULL, 1);
#endif
}

void loop() {
  unsigned long current_millis = millis();
  if ((current_millis - last_status) > 60000UL) {
    Serial.println("{\"heartbeat\":\"Device is active and scanning\"}");
    last_status = current_millis;
  }
  delay(10);
}
