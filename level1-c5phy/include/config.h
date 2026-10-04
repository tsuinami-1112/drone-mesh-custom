/*
 * Level 1 station v3 (C5 PHY) - configuration
 *
 * The XIAO ESP32-C5's own 5 GHz Wi-Fi radio is the 5.8 GHz analog FPV receiver:
 * four patch antennas -> SP4T RF switch -> [optional 20 dB LNA + band-pass
 * filter] -> the XIAO's U.FL. The firmware holds the PHY receive-only, pulls raw
 * I/Q off the modem's diagnostic bus through PARLIO, measures power and FM
 * coherence per sector, checks for a video line structure and reports a compass
 * bearing (relative to the box's face N) to mesh-mapper.py over USB and to a
 * Heltec V3 running Meshtastic over UART on D4/D5 - the same two pins every
 * station tier uses.
 *
 * Every value here can be overridden with -D in platformio.ini build_flags.
 * GPIO numbers are the ESP32-C5 GPIO numbers of the Seeed XIAO_ESP32C5 variant;
 * the D-labels in the comments are what is printed on the silkscreen. Every pin
 * this station uses is a top-side castellation: nothing on the underside.
 */
#pragma once

/* ---- Identity -------------------------------------------------------------- */
#ifndef NODE_ID
#define NODE_ID ""              /* "" = derive 4 hex chars from the eFuse MAC (A1B2),
                                   the same scheme as the level 2 remote nodes.
                                   Name the Heltec's Meshtastic node the same. */
#endif
#ifndef STATION_HEADING_DEG
#define STATION_HEADING_DEG 0   /* installer's note: true-north heading of face N.
                                   Reported in the boot line and heartbeat; NOT applied
                                   to bearing_deg. The mapper rotates bearings by the
                                   station heading it holds (pre-filled from this). */
#endif
#ifndef RF_COUNTRY_CC
#define RF_COUNTRY_CC "US"      /* regulatory table used for the 5 GHz bootstrap centres */
#endif
#define FIRMWARE_HW "v3"
#define FIRMWARE_RECEIVER "c5phy"

/* ---- Pins ------------------------------------------------------------------
 * The XIAO ESP32-C5 has eleven top-side GPIOs: D0 D1 D2 D3 D4 D5 D6 on the
 * left, D10 D9 D8 D7 on the right. They are spent as follows:
 *   D4 D5            UART to the Heltec (fixed, every station tier)
 *   D7 D8 D9         SP4T control lines V3 V1 V2
 *   D0 D1 D2 D3 D6 D10   six I/Q lane pads (must stay unconnected)
 * Eight I/Q lanes (C5VRX) would need the underside GPIO2-5 JTAG pads; this
 * station gives up the two least-significant lanes instead, see IQ_LANE_BITS. */
#define PIN_MESH_TX        23   /* D4 -> Heltec RX   (UART 115200, every station tier) */
#define PIN_MESH_RX        24   /* D5 <- Heltec TX */
#define PIN_STATUS_LED     27   /* XIAO ESP32-C5 user LED, on the board (active low) */
#define PIN_BOOT_BUTTON    28   /* on the board */

/* RF switch control lines. The sector table below is a bit pattern over these
 * pins, bit 0 = SWITCH_PINS[0]. Three lines cover a 2-line decoded SP4T
 * (PE42442: V3 spare), a 3-line one, or a tree of SPDTs. A one-hot SP4T with
 * four control inputs does not fit the top side next to six lanes; decode
 * it with two inverters or use a 2-line part. Fill the table in from the
 * bench truth table (stage 6). */
#ifndef SWITCH_PIN_COUNT
#define SWITCH_PIN_COUNT 3
#endif
#ifndef SWITCH_PINS
#define SWITCH_PINS { 8, 9, 12 }            /* D8 = V1, D9 = V2, D7 = V3 */
#endif
#ifndef SECTOR_SWITCH_TABLE
#define SECTOR_SWITCH_TABLE { 0x0, 0x1, 0x2, 0x3 }   /* N, E, S, W -> V1V2V3 = 000 100 010 110 */
#endif
#ifndef SWITCH_SETTLE_US
#define SWITCH_SETTLE_US 200
#endif

/* I/Q lanes. Each MODEM_DIAG bit is driven out through a GPIO pad and read
 * back from the same pad by PARLIO RX, so a lane pad must stay unconnected:
 * no resistor, no probe, no PCB trace. PARLIO data order is Q[6..9] then
 * I[6..9]; a lane set to -1 is not wired and reads as a constant.
 *
 * IQ_LANE_BITS 3 (default): bits 9..7 of Q and I on six top-side pads. The
 *   missing bit 6 is read as the midpoint of the two codes it would have told
 *   apart (demod_init_bits), so the level, coherence and video code run
 *   unchanged with one bit less resolution. Referenced to its own measured
 *   noise floor the 3-lane decode tracks the 4-lane one within 0.2 dB (test/host
 *   sensitivity table); the floor itself (RF_NOISE_POWER) must be measured on
 *   the bench in the lane mode that is built, and reads a little higher here
 *   because the decode never returns 0. The clip test fires one code early
 *   (|x| >= 6 instead of 7, about 1.3 dB), which with GAIN_STEP 6 costs nothing.
 * IQ_LANE_BITS 4: the eight lanes exactly as C5VRX proved them, which needs
 *   the underside GPIO2, 3, 4, 5 pads and frees D6 (GPIO11); D2 stays a lane
 *   (Q8 in that mode, Q9 in this one). */
#define IQ_LANE_COUNT 8
#ifndef IQ_LANE_BITS
#define IQ_LANE_BITS 3
#endif
#if IQ_LANE_BITS != 3 && IQ_LANE_BITS != 4
#error "IQ_LANE_BITS must be 3 (six top-side lane pads) or 4 (C5VRX's eight lanes)"
#endif
#ifndef IQ_LANE_GPIOS
#if IQ_LANE_BITS == 4
#define IQ_LANE_GPIOS { 1, 0, 25, 7, 10, 5, 3, 4 }       /* Q6 D0, Q7 D1, Q8 D2, Q9 D3, I6 D10, I7..I9 GPIO5 3 4 */
#else
#define IQ_LANE_GPIOS { -1, 1, 0, 25, -1, 7, 10, 11 }    /* Q7 D0, Q8 D1, Q9 D2, I7 D3, I8 D10, I9 D6 */
#endif
#endif
#define IQ_LANE_DIAG  { 6, 7, 8, 9, 16, 17, 18, 19 }   /* MODEM_DIAG bit per lane */

/* ---- Sectors --------------------------------------------------------------- */
#define SECTOR_COUNT 4
#ifndef SECTOR_AZIMUTH_DEG
#define SECTOR_AZIMUTH_DEG { 0.0f, 90.0f, 180.0f, 270.0f }  /* N E S W, relative to face N */
#endif
#define SECTOR_NAMES { "N", "E", "S", "W" }

/* ---- Receiver -------------------------------------------------------------- */
#define IQ_SAMPLE_RATE_HZ  40000000UL   /* PARLIO RX clock; every second 80 MS/s modem sample */
#define IQ_WINDOW_BYTES    16384        /* one byte per sample: I high nibble, Q low nibble = 409.6 us */
#ifndef GAIN_MAX
#define GAIN_MAX 62                     /* PHY RX gain index; 62 = full gain */
#endif
#ifndef GAIN_MIN
#define GAIN_MIN 2
#endif
#ifndef GAIN_STEP
#define GAIN_STEP 6                     /* gain index steps of ~1 dB each. A 12 dB step took a
                                           clipping carrier (amplitude 7) down to 1.75 LSB, under the
                                           coherence power gate (|s|^2 >= 8): a strong signal lost
                                           its hit. 6 dB leaves it at 3.5 LSB. */
#endif
#ifndef CLIP_MAX_PCT
#define CLIP_MAX_PCT 3.0f               /* above this share of full-scale samples: step the gain down, retake */
#endif
#ifndef RF_NOISE_POWER
#define RF_NOISE_POWER 2.0f             /* mean I^2+Q^2 with no signal at GAIN_MAX: C5VRX's 4-lane
                                           measurement. Measure it on this board in the lane mode built
                                           (bench stage 1). A dead I/Q bus shows every sample identical,
                                           which the firmware flags (stuck / bus_stuck); when the stuck
                                           pattern is all zeros it also reads exactly 2.0 in 3-lane mode. */
#endif
#ifndef WINDOWS_PER_SECTOR
#define WINDOWS_PER_SECTOR 3            /* level = min over windows (drops Wi-Fi bursts), q = median */
#endif
#ifndef QUIET_MARGIN_DB
#define QUIET_MARGIN_DB 3.0f            /* one window is enough when it sits this far under the threshold */
#endif
#ifndef BW40
#define BW40 1                          /* analog filter: 1 = BW40 (full video), 0 = BW20 (+3 dB SNR) */
#endif
#ifndef TUNE_SETTLE_MS
#define TUNE_SETTLE_MS 8
#endif
#ifndef C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ
#define C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ 60   /* how far phy_set_freq may pull the synthesizer from the
                                               public centre it was parked on (E8 5945 from 5885 = 60) */
#endif
#ifndef ALIAS_GUARD
#define ALIAS_GUARD 1                   /* drop a hit above the last public centre (5885) that merely
                                           mirrors a carrier at that centre: what a synthesizer that did
                                           not follow phy_set_freq would show (bench stage 2 settles it) */
#endif

/* ---- Detection ------------------------------------------------------------- */
#ifndef DETECT_LEVEL_DB
#define DETECT_LEVEL_DB 8.0f            /* hit: level_db >= this on the strongest sector ... */
#endif
#ifndef Q_MIN
#define Q_MIN 40                        /* ... and FM coherence (percent) >= this. The coherence gate is the selectivity. */
#endif
#ifndef PEAK_PICK
#define PEAK_PICK 1                     /* fold hits within PEAK_PICK_MHZ of a stronger hit into it (R3/B1/F1 overlap) */
#endif
#ifndef PEAK_PICK_MHZ
#define PEAK_PICK_MHZ 20
#endif
#ifndef VIDEO_CHECK
#define VIDEO_CHECK 1
#endif
#define VIDEO_WINDOWS        8
#define VIDEO_WINDOW_GAP_MS  5
#define VIDEO_MIN_WINDOWS    3          /* windows that must carry a line structure for a video verdict */
#define VIDEO_MAX_PER_SWEEP  2          /* strongest hits that get the (slow) video check each sweep */
#ifndef LOWBAND
#define LOWBAND 0                       /* 1 adds L1..L8 (5362-5621 MHz); outside the C5's 5 GHz window, left off */
#endif

/* ---- Level -> dBm calibration (bench stage 5) -------------------------------
 * level_db = (GAIN_MAX - gain) + 10*log10(p_mean / RF_NOISE_POWER)
 * rssi_dbm = RSSI_CAL_DBM_AT_NOISE + level_db * RSSI_CAL_SLOPE + RSSI_CAL_OFFSET_DB - RF_FRONTEND_GAIN_DB
 * The defaults are kTB over ~20 MHz plus a ~6 dB noise figure, not a measurement.
 * With the optional LNA fitted, calibrate with it in the chain and leave
 * RF_FRONTEND_GAIN_DB at 0; use RF_FRONTEND_GAIN_DB (20) only to carry a
 * calibration taken without the LNA over to a station that has one. */
#ifndef RSSI_CAL_DBM_AT_NOISE
#define RSSI_CAL_DBM_AT_NOISE (-95.0f)
#endif
#ifndef RSSI_CAL_SLOPE
#define RSSI_CAL_SLOPE 1.0f
#endif
#ifndef RSSI_CAL_OFFSET_DB
#define RSSI_CAL_OFFSET_DB 0.0f
#endif
#ifndef RF_FRONTEND_GAIN_DB
#define RF_FRONTEND_GAIN_DB 0.0f        /* 20.0 when the optional LNA+filter is in the chain (see above) */
#endif

/* ---- Bearing --------------------------------------------------------------- */
#ifndef BEARING_K_DEG_PER_DB
#define BEARING_K_DEG_PER_DB 3.0f       /* from the stage 6 pattern sweep */
#endif
#ifndef BEARING_SIGMA_BASE_DEG
#define BEARING_SIGMA_BASE_DEG 10.0f
#endif
#define BEARING_MAX_OFFSET_DEG 45.0f    /* never report further than this from the strongest sector's axis */

/* ---- Reporting ------------------------------------------------------------- */
#define HEARTBEAT_USB_S          60
#define HEARTBEAT_MESH_S         120
#ifndef MESH_REPORT_INTERVAL_MS
#define MESH_REPORT_INTERVAL_MS  8000   /* per emitter; the first report of a new emitter goes at once */
#endif
#define MESH_LINE_GAP_MS         350    /* pacing between lines into the Heltec */
#define MESH_JSON_MAX            191    /* one Meshtastic TEXTMSG as the v2 station proved it */
#define USB_JSON_MAX             640
#define BENCH_PRINT_MS           500    /* bench line rate while holding a channel */
