/* WiFi-only drone scanner (original variant, GPIO6/7 pinout)
 *
 * Detects, from 802.11 frames alone:
 *   - Open Drone ID (ASTM F3411 / ASD-STAN EN 4709-002) in WiFi NAN action
 *     frames and WiFi Beacon vendor IEs - every message type incl. Operator ID
 *   - DJI proprietary DroneID beacons (WiFi-link DJI aircraft)
 *   - MAVLink telemetry on open WiFi networks
 *   - WiFi fingerprints (SSID / vendor MAC prefix) of drones and controllers
 *     that broadcast no Remote ID
 *
 * All parsing is in the shared library ../../firmware-common/detect.
 *
 * Output: JSON lines on USB Serial for mesh-mapper.py; compact text on
 * Serial1 (TX=GPIO6, RX=GPIO7) for a Heltec/Meshtastic relay.
 */

#if !defined(ARDUINO_ARCH_ESP32)
  #error "This program requires an ESP32"
#endif

#include <Arduino.h>
#include <HardwareSerial.h>
#include <esp_wifi.h>
#include <nvs_flash.h>
#include <esp_netif.h>
#include <esp_event.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "detect.h"

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

// Custom UART pin definitions for Serial1
const int SERIAL1_RX_PIN = 7;  // GPIO7
const int SERIAL1_TX_PIN = 6;  // GPIO6

#define MAX_UAVS 8
static DetectRecord uavs[MAX_UAVS];
static QueueHandle_t printQueue;
static int packetCount = 0;
static unsigned long last_status = 0;

// Forward declarations
void event_handler(void *ctx, esp_event_base_t event_base, int32_t event_id, void *event_data);
void callback(void *, wifi_promiscuous_pkt_type_t);

void event_handler(void *ctx, esp_event_base_t event_base, int32_t event_id, void *event_data) {
  // No-op handler for now
}

// ---------------------------------------------------------------------------
// UAV table (only the WiFi task touches it, so no locking needed)
// ---------------------------------------------------------------------------
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
      if (uavs[i].last_seen < oldest_time) { oldest_time = uavs[i].last_seen; oldest_idx = i; }
    }
    slot = &uavs[oldest_idx];
  }
  detect_record_init(slot);
  memcpy(slot->mac, mac, 6);
  return slot;
}

// Initialize USB Serial (for JSON output) and Serial1 (mesh relay)
void initializeSerial() {
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, SERIAL1_RX_PIN, SERIAL1_TX_PIN);
  Serial.println("USB Serial (for JSON) and UART (Serial1) initialized.");
  Serial.println("Proto: Remote ID (NAN, Beacon), DJI DroneID, MAVLink, WiFi fingerprints");
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------
static void send_json_fast(const DetectRecord* rec) {
  char json[USB_JSON_MAX];
  if (detect_build_json(json, sizeof(json), rec, nullptr) > 0) Serial.println(json);
}

// Sends UART messages over Serial1, throttled to one every 5 s.
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
// WiFi promiscuous callback: parse, merge into the slot, queue a snapshot.
// Serial output happens in printerTask, never in the WiFi task.
// ---------------------------------------------------------------------------
void callback(void *buffer, wifi_promiscuous_pkt_type_t type) {
  wifi_promiscuous_pkt_t *packet = (wifi_promiscuous_pkt_t *)buffer;
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
  if (!hit) return;

  uint32_t now = millis();
  rec.last_seen = now;
  if (detect_is_heuristic(rec.src)) {
#if !DETECT_FINGERPRINT
    return;
#endif
    if (!detect_throttle(rec.mac, now, FP_MIN_INTERVAL_MS)) return;
  }
  DetectRecord* slot = next_uav(rec.mac);
  detect_record_merge(slot, &rec);
  packetCount++;
  if (printQueue) {
    DetectRecord tmp = *slot;
    BaseType_t woken = pdFALSE;
    xQueueSendFromISR(printQueue, &tmp, &woken);
    if (woken) portYIELD_FROM_ISR();
  }
}

static void printerTask(void *param) {
  DetectRecord rec;
  for (;;) {
    if (xQueueReceive(printQueue, &rec, portMAX_DELAY)) {
      send_json_fast(&rec);
      print_compact_message(&rec);
    }
  }
}

// Mostly channel 6 (Remote ID), short visits to the other 2.4 GHz channels.
static void wifiHopTask(void *param) {
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

void setup() {
  setCpuFrequencyMhz(160);
  nvs_flash_init();
  esp_netif_init();  // Modern replacement for tcpip_adapter_init
  initializeSerial();
  esp_event_loop_create_default();  // Modern replacement
  esp_event_handler_instance_register(ESP_EVENT_ANY_BASE, ESP_EVENT_ANY_ID, &event_handler, NULL, NULL);

  printQueue = xQueueCreate(MAX_UAVS * 2, sizeof(DetectRecord));
  memset(uavs, 0, sizeof(uavs));

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&cfg);
  esp_wifi_set_storage(WIFI_STORAGE_RAM);
  esp_wifi_set_mode(WIFI_MODE_NULL);
  esp_wifi_start();
  wifi_promiscuous_filter_t filt;
  filt.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT;
#if DETECT_MAVLINK
  filt.filter_mask |= WIFI_PROMIS_FILTER_MASK_DATA;
#endif
  esp_wifi_set_promiscuous_filter(&filt);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&callback);
  esp_wifi_set_channel(DETECT_HOME_CHANNEL, WIFI_SECOND_CHAN_NONE);

  xTaskCreate(printerTask, "PrinterTask", 8192, NULL, 1, NULL);
  xTaskCreate(wifiHopTask, "WiFiHopTask", 4096, NULL, 1, NULL);
}

void loop() {
  delay(10);
  unsigned long current_millis = millis();
  if ((current_millis - last_status) > 60000UL) { // Every 60 seconds
    Serial.printf("{\"heartbeat\":\"Device is active and running.\",\"frames\":%d}\n", packetCount);
    last_status = current_millis;
  }
}
