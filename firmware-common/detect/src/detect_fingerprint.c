/*
 * detect_fingerprint.c - heuristics for aircraft and controllers that
 * broadcast no Remote ID: WiFi network names, vendor MAC prefixes and BLE
 * device names / manufacturer IDs. Everything here is a hint, reported with
 * a confidence level and a role, never with a position.
 *
 * Sources: Kismet kismet_uav.conf, vendor manuals and FCC filings, the IEEE
 * MA-L/MA-M/MA-S registry (checked prefix by prefix), the Bluetooth SIG
 * company identifier list, MAVLink WiFi bridge firmware defaults.
 *
 * Confidence is "how specific is this as a DRONE indicator", not how sure we
 * are of the vendor: a DJI MAC prefix also covers Osmo cameras and goggles,
 * so it is "low"; a "Spark-XXXXXX" network is only ever a Spark, so "high".
 *
 * Deliberately NOT matched: module-maker prefixes used by toy drones (LB-Link,
 * ICOMM, Earda, Espressif - they are also in every cheap IoT gadget), Xiaomi
 * prefixes (FIMI/Mi Drone share them with phones), GoPro/Insta360 cameras,
 * and one-word names like "Nano", "Air", "Mini" or "drone" that match far
 * too much.
 */
#include <string.h>
#include <ctype.h>
#include <stdio.h>
#include "detect.h"

typedef struct {
  const char *prefix;    /* case-insensitive SSID prefix */
  const char *vendor;
  const char *model;
  uint8_t     role;      /* DetectRole */
  uint8_t     conf;      /* DetectConf */
} ssid_rule_t;

/* Order matters where one prefix contains another ("Spark-RC-" before "Spark-"). */
static const ssid_rule_t SSID_RULES[] = {
  /* --- DJI / Ryze (WiFi-link aircraft, QuickTransfer hotspots, accessories) --- */
  { "Spark-RC-",      "DJI",    "Spark RC",                DET_ROLE_CONTROLLER, DET_CONF_HIGH },
  { "Spark-",         "DJI",    "Spark",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "MavicAir-",      "DJI",    "Mavic Air",               DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Mavic Mini-",    "DJI",    "Mavic Mini",              DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "MAVIC-MINI-",    "DJI",    "Mavic Mini",              DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Mavic-",         "DJI",    "Mavic Pro (WiFi)",        DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Mavic_",         "DJI",    "Mavic",                   DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Phantom3_",      "DJI",    "Phantom 3 (RC link)",     DET_ROLE_CONTROLLER, DET_CONF_HIGH },
  { "TELLO",          "Ryze",   "Tello",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "RMTT-",          "Ryze",   "RoboMaster TT",           DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "DJI-MAVIC3",     "DJI",    "Mavic 3 (QuickTransfer)", DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "DJI-MINI3",      "DJI",    "Mini 3 (QuickTransfer)",  DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "DJI-MINI4",      "DJI",    "Mini 4 (QuickTransfer)",  DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "DJI-MINI2",      "DJI",    "Mini 2 (QuickTransfer)",  DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "DJI-AIR2S",      "DJI",    "Air 2S (QuickTransfer)",  DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "DJI-AIR3",       "DJI",    "Air 3 (QuickTransfer)",   DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "DJI-FPV",        "DJI",    "FPV",                     DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "DJI RC",         "DJI",    "RC hotspot",              DET_ROLE_CONTROLLER, DET_CONF_MED  },
  { "DJI-RC",         "DJI",    "RC hotspot",              DET_ROLE_CONTROLLER, DET_CONF_MED  },
  { "DJI Goggles",    "DJI",    "Goggles",                 DET_ROLE_ACCESSORY,  DET_CONF_MED  },
  { "OSMO",           "DJI",    "Osmo camera",             DET_ROLE_ACCESSORY,  DET_CONF_LOW  },
  { "Ronin",          "DJI",    "Ronin gimbal",            DET_ROLE_ACCESSORY,  DET_CONF_LOW  },
  { "DJI-",           "DJI",    "",                        DET_ROLE_UNKNOWN,    DET_CONF_MED  },
  { "DJI_",           "DJI",    "",                        DET_ROLE_UNKNOWN,    DET_CONF_MED  },
  { "DJI ",           "DJI",    "",                        DET_ROLE_UNKNOWN,    DET_CONF_MED  },
  /* Remote ID beacons whose vendor IE did not decode still say what they are
   * (DJI "RID-<serial>", ArduRemoteID / hobby modules) */
  { "RID-",           "",       "Remote ID beacon",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "RID_",           "",       "Remote ID beacon",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "ODID",           "",       "Remote ID beacon",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "OpenDroneID",    "",       "Remote ID beacon",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "RemoteID",       "",       "Remote ID beacon",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },

  /* --- Parrot --- */
  { "ANAFI",          "Parrot", "ANAFI",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "AnafiUSA-",      "Parrot", "ANAFI USA",               DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Bebop",          "Parrot", "Bebop",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "ardrone",        "Parrot", "AR.Drone",                DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Disco-",         "Parrot", "Disco",                   DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "SkyController",  "Parrot", "SkyController",           DET_ROLE_CONTROLLER, DET_CONF_HIGH },
  { "Mambo_",         "Parrot", "Mambo",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Swing_",         "Parrot", "Swing",                   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },

  /* --- other manufacturers --- */
  { "Skydio",         "Skydio", "",                        DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Autel",          "Autel",  "EVO",                     DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "EVO-",           "Autel",  "EVO",                     DET_ROLE_AIRCRAFT,   DET_CONF_LOW  },
  { "EVO_",           "Autel",  "EVO",                     DET_ROLE_AIRCRAFT,   DET_CONF_LOW  },
  { "Breeze_",        "Yuneec", "Breeze",                  DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "CGO3",           "Yuneec", "Typhoon (CGO3 camera)",   DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "CGOE10T_",       "Yuneec", "Typhoon H (E10T)",        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Mantis_",        "Yuneec", "Mantis",                  DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "MantisQ_",       "Yuneec", "Mantis Q",                DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "HUBSAN_",        "Hubsan", "",                        DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Hubsan",         "Hubsan", "",                        DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "HolyStone",      "Holy Stone", "",                    DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Potensic",       "Potensic", "",                      DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Dreamer 1_",     "Potensic", "Dreamer",               DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Snaptain-",      "Snaptain", "",                      DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Ruko-",          "Ruko",   "F11",                     DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Ruko_",          "Ruko",   "F11",                     DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "SJRC-",          "SJRC",   "",                        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "SJ-F11",         "SJRC",   "F11",                     DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "FIMI",           "FIMI",   "X8",                      DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Xiaomi_FIMI",    "FIMI",   "",                        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "MiDrone_",       "Xiaomi", "Mi Drone",                DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "EggX_",          "PowerVision", "PowerEgg X",         DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "HoverX1_",       "Zero Zero", "HOVERAir X1",          DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "HOVERAir",       "Zero Zero", "HOVERAir",             DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Vitus-Air-",     "Walkera", "Vitus",                  DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Vitus-Ground-",  "Walkera", "Vitus ground unit",      DET_ROLE_CONTROLLER, DET_CONF_HIGH },
  { "WK-GRD-",        "Walkera", "ground unit",            DET_ROLE_CONTROLLER, DET_CONF_HIGH },
  { "WINGSLANDs6_air_", "Wingsland", "S6",                 DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "SoloLink_",      "3DR",    "Solo controller",         DET_ROLE_CONTROLLER, DET_CONF_HIGH },

  /* --- toy / FPV quads (WiFi camera link) --- */
  { "FPV_WIFI_",      "Syma",   "X5SW/X8 class",           DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "FPV WIFI",       "Syma",   "",                        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "SYMA",           "Syma",   "",                        DET_ROLE_AIRCRAFT,   DET_CONF_LOW  },
  { "udirc-",         "UDI RC", "",                        DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "JJRC-",          "JJRC",   "",                        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "CX-10W",         "Cheerson", "CX-10W",                DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Bugs",           "MJX",    "Bugs",                    DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "MJX",            "MJX",    "",                        DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "Propel Sky Rider", "Propel", "Sky Rider",             DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Sky Rider Vox-", "Propel", "Sky Rider",               DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Propel HD Video Drone", "Propel", "HD Video Drone",   DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "360 Flight-",    "Propel", "360 Flight",              DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "360-L Flight-",  "Propel", "360-L Flight",            DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "YD_UFO",         "Attop",  "UFO toy quad",            DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "YD-UFO",         "Attop",  "UFO toy quad",            DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "YD-1080-UFO",    "Attop",  "UFO toy quad",            DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "XBM-720P-",      "",       "E58-class toy quad",      DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "WiFi-720P-",     "",       "E58-class toy quad",      DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "WI-FI 720P",     "",       "toy quad",                DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "WI-FI UFO",      "",       "toy quad",                DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "WiFi_UFO",       "",       "toy quad",                DET_ROLE_AIRCRAFT,   DET_CONF_MED  },
  { "KY-",            "",       "KY-series toy quad",      DET_ROLE_AIRCRAFT,   DET_CONF_LOW  },

  /* --- FPV goggles --- */
  { "HDZero",         "HDZero", "goggles",                 DET_ROLE_ACCESSORY,  DET_CONF_HIGH },

  /* --- MAVLink WiFi telemetry bridges (ArduPilot / PX4 / INAV / ELRS) --- */
  { "ArduPilot",      "ArduPilot", "ESP8266 telemetry",    DET_ROLE_ACCESSORY,  DET_CONF_MED  },
  { "PixRacer",       "Holybro",   "mavesp8266 telemetry", DET_ROLE_ACCESSORY,  DET_CONF_MED  },
  { "DroneBridge",    "DroneBridge","ESP32 telemetry",     DET_ROLE_ACCESSORY,  DET_CONF_MED  },
  { "CUAVWLINK",      "CUAV",      "PW-Link telemetry",    DET_ROLE_ACCESSORY,  DET_CONF_MED  },
  { "ExpressLRS",     "ExpressLRS","TX backpack",          DET_ROLE_CONTROLLER, DET_CONF_MED  },
  { "mLRS-",          "mLRS",      "wireless bridge",      DET_ROLE_CONTROLLER, DET_CONF_MED  },
  { "IFFRC_",         "IFFRC",     "ESP8266 telemetry",    DET_ROLE_ACCESSORY,  DET_CONF_MED  },
};

/* IEEE registrations. `bits` is the registered prefix length: 24 (MA-L),
 * 28 (MA-M) or 36 (MA-S / IAB). The unused tail of `prefix` is zero. */
typedef struct {
  uint8_t     prefix[5];
  uint8_t     bits;
  const char *vendor;
  const char *model;
  uint8_t     role;
  uint8_t     conf;
} oui_rule_t;

static const oui_rule_t OUI_RULES[] = {
  /* SZ DJI Technology - shared with Osmo cameras, goggles and controllers */
  { { 0x60, 0x60, 0x1F }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x34, 0xD2, 0x62 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x48, 0x1C, 0xB9 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0xE4, 0x7A, 0x2C }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x58, 0xB8, 0x58 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x04, 0xA8, 0x5A }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x8C, 0x58, 0x23 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x0C, 0x9A, 0xE6 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x88, 0x29, 0x85 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x4C, 0x43, 0xF6 }, 24, "DJI", "DJI device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x9C, 0x5A, 0x8A }, 24, "DJI", "DJI device (Baiwang)", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0xEC, 0x72, 0xF7 }, 24, "DJI", "DJI device (Baiwang)", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0xF8, 0x40, 0x68 }, 24, "DJI", "Ronin gimbal",  DET_ROLE_ACCESSORY, DET_CONF_LOW },
  { { 0x20, 0x1F, 0x55 }, 24, "DJI", "Osmo camera",   DET_ROLE_ACCESSORY, DET_CONF_LOW },
  /* Parrot SA - older prefixes shared with Zik headphones / car kits */
  { { 0x00, 0x12, 0x1C }, 24, "Parrot", "Parrot device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x00, 0x26, 0x7E }, 24, "Parrot", "Parrot device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0x90, 0x03, 0xB7 }, 24, "Parrot", "Parrot device", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0xA0, 0x14, 0x3D }, 24, "Parrot", "Bebop / SkyController", DET_ROLE_UNKNOWN, DET_CONF_MED },
  { { 0x90, 0x3A, 0xE6 }, 24, "Parrot", "Bebop 2 / Disco / ANAFI", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  /* Drone-only registrants */
  { { 0x38, 0x1D, 0x14 }, 24, "Skydio",   "Skydio",            DET_ROLE_UNKNOWN,  DET_CONF_MED },
  { { 0xEC, 0x5B, 0xCD, 0xE0 }, 28, "Autel", "EVO",            DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0xE0, 0xB6, 0xF5, 0x80 }, 28, "Yuneec", "Typhoon / Mantis", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x98, 0xAA, 0xFC, 0x70 }, 28, "Hubsan", "Zino / H501",   DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x84, 0x83, 0x19 }, 24, "Zero Zero", "Hover Camera",     DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0xC8, 0x63, 0x14, 0x40 }, 28, "Zero Zero", "HOVERAir",   DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x6C, 0xDF, 0xFB, 0xE0 }, 28, "FIMI", "X8",              DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x54, 0x7D, 0x40 }, 24, "PowerVision", "PowerEgg / water robot", DET_ROLE_UNKNOWN, DET_CONF_LOW },
  { { 0xB0, 0x30, 0xC8 }, 24, "Teal",     "Teal 2",            DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0xEC, 0x71, 0x5E }, 24, "Freefly",  "Astro / Alta",      DET_ROLE_UNKNOWN,  DET_CONF_LOW },
  { { 0xA8, 0xB0, 0x28 }, 24, "CubePilot", "Herelink",         DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0xAC, 0x86, 0xD1, 0x70 }, 28, "Quantum-Systems", "Trinity / Vector", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0xE8, 0xB4, 0x70, 0xC0 }, 28, "Anduril", "Ghost / Altius", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x14, 0xDD, 0x48 }, 24, "Shield AI", "V-BAT / Nova",     DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x74, 0xB8, 0x0F }, 24, "Zipline",  "delivery UAS",      DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x00, 0x1A, 0xF9 }, 24, "AeroVironment", "Raven / Puma", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x28, 0xF5, 0x37, 0xD0 }, 28, "Skyrocket", "Sky Viper",  DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0x48, 0x20 }, 36, "Aeryon", "SkyRanger", DET_ROLE_AIRCRAFT, DET_CONF_MED },
  { { 0x00, 0x50, 0xC2, 0xC3, 0x50 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x00, 0x50, 0xC2, 0xFD, 0x40 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0x7A, 0xD0 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0x86, 0x50 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0xB3, 0xB0 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0xD3, 0x60 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x70, 0xB3, 0xD5, 0xDD, 0x20 }, 36, "Insitu", "ScanEagle ground segment", DET_ROLE_CONTROLLER, DET_CONF_MED },
  { { 0x9C, 0x4B, 0x6B }, 24, "iFlight",  "FPV electronics",   DET_ROLE_ACCESSORY, DET_CONF_LOW },
};

typedef struct {
  const char *prefix;
  const char *vendor;
  const char *model;
  uint8_t     role;
  uint8_t     conf;
} ble_rule_t;

static const ble_rule_t BLE_NAME_RULES[] = {
  { "DJI RC",        "DJI",    "RC",             DET_ROLE_CONTROLLER, DET_CONF_MED },
  { "DJI-RC",        "DJI",    "RC",             DET_ROLE_CONTROLLER, DET_CONF_MED },
  { "RC-N1",         "DJI",    "RC-N1",          DET_ROLE_CONTROLLER, DET_CONF_MED },
  { "DJI Goggles",   "DJI",    "Goggles",        DET_ROLE_ACCESSORY,  DET_CONF_MED },
  { "DJI",           "DJI",    "",               DET_ROLE_UNKNOWN,    DET_CONF_LOW },
  /* Parrot BLE-controlled minidrones advertise <family>_<digits> */
  { "RS_",           "Parrot", "Rolling Spider", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Mars_",         "Parrot", "Airborne Cargo", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Travis_",       "Parrot", "Airborne Cargo", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Maclane_",      "Parrot", "Airborne Night", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Swat_",         "Parrot", "Airborne Night", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Blaze_",        "Parrot", "Airborne Night", DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "NewZ_",         "Parrot", "Hydrofoil",      DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Orak_",         "Parrot", "Hydrofoil",      DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Mambo_",        "Parrot", "Mambo",          DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Swing_",        "Parrot", "Swing",          DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "ANAFI",         "Parrot", "ANAFI",          DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Bebop",         "Parrot", "Bebop",          DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Skycontroller", "Parrot", "SkyController",  DET_ROLE_CONTROLLER, DET_CONF_MED },
  { "Parrot",        "Parrot", "",               DET_ROLE_UNKNOWN,    DET_CONF_LOW },
  { "Skydio",        "Skydio", "",               DET_ROLE_UNKNOWN,    DET_CONF_MED },
  { "Autel",         "Autel",  "",               DET_ROLE_UNKNOWN,    DET_CONF_MED },
  { "HOVERAir",      "Zero Zero", "HOVERAir",    DET_ROLE_AIRCRAFT,   DET_CONF_HIGH },
  { "Hover",         "Zero Zero", "HOVERAir",    DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Tello",         "Ryze",   "Tello",          DET_ROLE_AIRCRAFT,   DET_CONF_MED },
  { "Hubsan",        "Hubsan", "",               DET_ROLE_UNKNOWN,    DET_CONF_LOW },
  { "Zino",          "Hubsan", "Zino",           DET_ROLE_AIRCRAFT,   DET_CONF_LOW },
};

/* Bluetooth SIG company identifiers (manufacturer-specific AD, type 0xFF) */
typedef struct {
  uint16_t    company;
  const char *vendor;
  const char *model;
  uint8_t     role;
  uint8_t     conf;
} ble_company_rule_t;

static const ble_company_rule_t BLE_COMPANY_RULES[] = {
  { 0x08AA, "DJI",       "DJI device",   DET_ROLE_UNKNOWN,  DET_CONF_LOW },   /* also Osmo, Mic, RoboMaster */
  { 0x0043, "Parrot",    "Parrot device",DET_ROLE_UNKNOWN,  DET_CONF_LOW },   /* also audio / car kits */
  { 0x09F3, "Zero Zero", "HOVERAir",     DET_ROLE_AIRCRAFT, DET_CONF_MED },
};

static bool ci_prefix(const char *s, const char *prefix)
{
  for (; *prefix; s++, prefix++) {
    if (*s == '\0') return false;
    if (tolower((unsigned char)*s) != tolower((unsigned char)*prefix)) return false;
  }
  return true;
}

static void apply(DetectRecord *out, const char *vendor, const char *model, uint8_t role, uint8_t conf)
{
  snprintf(out->vendor, sizeof(out->vendor), "%s", vendor);
  snprintf(out->model, sizeof(out->model), "%s", model);
  out->role = role;
  out->conf = conf;
}

bool detect_fingerprint_ssid(const char *ssid, DetectRecord *out)
{
  if (!ssid || !ssid[0]) return false;
  for (size_t i = 0; i < sizeof(SSID_RULES) / sizeof(SSID_RULES[0]); i++) {
    const ssid_rule_t *r = &SSID_RULES[i];
    if (ci_prefix(ssid, r->prefix)) {
      apply(out, r->vendor, r->model, r->role, r->conf);
      return true;
    }
  }
  return false;
}

static bool prefix_match(const uint8_t mac[6], const uint8_t *prefix, uint8_t bits)
{
  int full = bits / 8, rem = bits % 8;
  if (memcmp(mac, prefix, (size_t)full) != 0) return false;
  if (rem == 0) return true;
  uint8_t mask = (uint8_t)(0xFF << (8 - rem));
  return (mac[full] & mask) == (prefix[full] & mask);
}

bool detect_fingerprint_oui(const uint8_t mac[6], DetectRecord *out)
{
  for (size_t i = 0; i < sizeof(OUI_RULES) / sizeof(OUI_RULES[0]); i++) {
    const oui_rule_t *r = &OUI_RULES[i];
    if (prefix_match(mac, r->prefix, r->bits)) {
      apply(out, r->vendor, r->model, r->role, r->conf);
      return true;
    }
  }
  return false;
}

bool detect_fingerprint_ble_name(const char *name, DetectRecord *out)
{
  if (!name || !name[0]) return false;
  for (size_t i = 0; i < sizeof(BLE_NAME_RULES) / sizeof(BLE_NAME_RULES[0]); i++) {
    const ble_rule_t *r = &BLE_NAME_RULES[i];
    if (ci_prefix(name, r->prefix)) {
      apply(out, r->vendor, r->model, r->role, r->conf);
      return true;
    }
  }
  return false;
}

bool detect_fingerprint_ble_company(uint16_t company, DetectRecord *out)
{
  for (size_t i = 0; i < sizeof(BLE_COMPANY_RULES) / sizeof(BLE_COMPANY_RULES[0]); i++) {
    const ble_company_rule_t *r = &BLE_COMPANY_RULES[i];
    if (r->company == company) {
      apply(out, r->vendor, r->model, r->role, r->conf);
      return true;
    }
  }
  return false;
}
