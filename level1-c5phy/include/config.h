/*
 * Level 1 station v3 (C5 PHY) - configuration
 *
 * The XIAO ESP32-C5's own 5 GHz Wi-Fi radio is the 5.8 GHz FPV receiver:
 * four patch antennas -> SP4T RF switch -> [optional 20 dB LNA + band-pass
 * filter] -> the XIAO's U.FL. The firmware holds the PHY receive-only, pulls raw
 * I/Q off the modem's diagnostic bus through PARLIO, measures power, FM
 * coherence and the envelope per sector, checks analog hits for a video line
 * structure, confirms noise-like carriers as digital video links (wideband) and
 * reports a compass bearing (relative to the box's face N) to mesh-mapper.py
 * over USB and to a Heltec V4 running Meshtastic over UART on D4/D5 - the same
 * two pins every station tier uses.
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
/* STATION_LAT / STATION_LON: the station's surveyed position, WGS84 degrees
 * (e.g. 33.494200 / -111.926100). Optional: define both or neither. When set,
 * the heartbeat carries them and every mapper places the station by itself
 * (shown as "auto"); a position saved by hand in a mapper overrides it there.
 * Normally set through the "Station setup (map)" PlatformIO task, which writes
 * custom_station_lat / custom_station_lon into stations.ini; see the README. */
#ifndef STATION_POS_EVERY
#define STATION_POS_EVERY 5     /* mesh heartbeats: position on the first 3 after boot, then
                                   every 5th (10 min). The 191-byte mesh line has no room for
                                   it in every heartbeat without dropping uptime and temp. */
#endif
#ifndef RF_COUNTRY_CC
#define RF_COUNTRY_CC "US"      /* regulatory table used for the Wi-Fi bootstrap centres */
#endif
#define FIRMWARE_HW "v3"
#define FIRMWARE_RECEIVER "c5phy"

/* ---- Build variants ---------------------------------------------------------
 * The scan plan is R A B E F (40 analog channels) plus the scan points below;
 * fpv_channels.c carries the same defaults for the host tests. */
#ifndef DUAL_BAND
#define DUAL_BAND 0             /* 1: also sweep 2.4 GHz G1..G5 (env seeed_xiao_esp32c5_dualband);
                                   needs dual-band patches and no 5.8 GHz band-pass filter */
#endif
#ifndef SCAN_5G1
#define SCAN_5G1 1              /* D1..D3 5190/5210/5230 MHz: three 40 MHz views over DJI O4's CE band 5170-5250 */
#endif
#ifndef LOWBAND
#define LOWBAND 1               /* 0 none, 1 L4..L8 (5473-5621, reachable from Wi-Fi 100-124),
                                   2 L1..L8: L1-L3 sit 64-138 MHz under Wi-Fi 100, so also set
                                   C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ to 140 or rf_tune refuses them */
#endif
#ifndef GAP_CHANNELS
#define GAP_CHANNELS 1          /* X1 5675, X2 5715: the two holes of the table that no pull-in reaches from a neighbour */
#endif
#define MAX_CHANNELS 64         /* upper bound of the plan (58 with every variant on): the per-channel arrays */

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
 *   (|x| >= 6 instead of 7, about 1.3 dB), which with GAIN_STEP 3 costs nothing.
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

/* ---- Antenna (per station, from Station setup) ------------------------------
 * The patches' gain sets the sector beamwidth and with it the bearing constant
 * and the bearing sigma. A Gaussian main lobe is G(phi) = -12 (phi/bw)^2 dB; for
 * four sectors 90 deg apart the neighbour difference is 4320 phi / bw^2 dB, so
 * phi = bw^2 / 4320 per dB. Real patches are gentler 45-135 deg off axis, hence
 * the measured scale (2.5 reproduces the stage 6 K of 3.0 deg/dB at 72 deg).
 * Station setup writes custom_antenna_dbi (and custom_antenna_beamwidth_deg /
 * custom_bearing_k to override the derivations) into stations.ini. */
#ifndef ANTENNA_GAIN_DBI
#define ANTENNA_GAIN_DBI 8.0f           /* 5.8 GHz patches */
#endif
#ifndef ANTENNA_BEAMWIDTH_DEG
#define ANTENNA_BEAMWIDTH_DEG 0.0f      /* 0 = derive from gain: sqrt(32400 / 10^(dBi/10)) -> 8 dBi = 72 deg */
#endif
#ifndef BEARING_K_SCALE
#define BEARING_K_SCALE 2.5f            /* measured K / Gaussian-lobe K; anchored once per antenna family at stage 6 */
#endif
#ifndef BEARING_K_DEG_PER_DB
#define BEARING_K_DEG_PER_DB 0.0f       /* 0 = derive: BEARING_K_SCALE * beamwidth^2 / 4320 (8 dBi -> 3.0 deg/dB) */
#endif
#ifndef ANTENNA_GAIN_DBI_24
#define ANTENNA_GAIN_DBI_24 6.0f        /* dual-band: the 2.4 GHz side of the patches, same rules as above */
#endif
#ifndef ANTENNA_BEAMWIDTH_DEG_24
#define ANTENNA_BEAMWIDTH_DEG_24 0.0f
#endif
#ifndef BEARING_K_DEG_PER_DB_24
#define BEARING_K_DEG_PER_DB_24 0.0f
#endif
#ifndef BEARING_SIGMA_BASE_DEG
#define BEARING_SIGMA_BASE_DEG 10.0f    /* at 72 deg beamwidth; scaled by beamwidth / 72 at runtime */
#endif
#define BEARING_MAX_OFFSET_DEG 45.0f    /* never report further than this from the strongest sector's axis */

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
#define GAIN_STEP 3                     /* gain index steps of ~1 dB each. A 12 dB step took a
                                           clipping carrier (amplitude 7) down to 1.75 LSB, under the
                                           coherence power gate (|s|^2 >= 8): a strong signal lost
                                           its hit. 6 dB left it at 3.5 LSB but still dropped a carrier
                                           just above threshold (model: a 1 dB notch at S/N 10 dB);
                                           3 dB closes the notch. */
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
#define WINDOWS_PER_SECTOR 3            /* level = min over windows (drops Wi-Fi bursts), q and cv2 = median */
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
                                               public centre it was parked on (E8 5945 from 5885 = 60;
                                               LOWBAND 2 needs 140: L1 5362 from 5500) */
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
#define Q_MIN 40                        /* ... and FM coherence (percent) >= this. The coherence gate is the selectivity ... */
#endif
#ifndef ANALOG_CV2_MAX
#define ANALOG_CV2_MAX 0.5f             /* ... and envelope variance/mean^2 <= this: FM video 0.02-0.3, OFDM ~1.0
                                           (model). The analog/digital splitter. */
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

/* ---- Wideband (digital video links) -----------------------------------------
 * A channel whose strongest sector stays above threshold over its windows with
 * a noise-like envelope but fails the analog gate is a candidate; the strongest
 * get a confirmation pass of WB_WINDOWS and a bearing from interleaved sectors.
 * Lag autocorrelations |R(L)|/R0 of the decoded window name the system: the
 * 802.11 OFDM symbol repeats at 3.2 us (lag 128), LTE-like 66.7 us symbols (DJI
 * OcuSync) at lag 2667; the noise floor of the features is ~0.01 (model). */
#ifndef WIDEBAND
#define WIDEBAND 1
#endif
#ifndef WB_CV2_MIN
#define WB_CV2_MIN 0.5f                 /* candidate envelope window: noise-like ... */
#endif
#ifndef WB_CV2_MAX
#define WB_CV2_MAX 1.5f                 /* ... but not bursty (Wi-Fi traffic reads 1.6-2.7 in the model) */
#endif
#ifndef WB_LEVEL_SPREAD_DB
#define WB_LEVEL_SPREAD_DB 6.0f         /* max-min of the sector's windows must stay within this: continuous over ~1.5 ms */
#endif
#ifndef WB_WINDOWS
#define WB_WINDOWS 8                    /* confirmation pass, strongest sector */
#endif
#ifndef WB_WINDOW_GAP_MS
#define WB_WINDOW_GAP_MS 5
#endif
#ifndef WB_DUTY_DB
#define WB_DUTY_DB 6.0f                 /* a window counts as "on" within this of the loudest window */
#endif
#ifndef WB_DUTY_MIN
#define WB_DUTY_MIN 75                  /* percent of windows "on" for a report */
#endif
#ifndef WB_R128_MIN
#define WB_R128_MIN 0.10f               /* |R(128)|/R0 >= this: 802.11 OFDM symbol timing (3.2 us) (model: 0.17-0.19) */
#endif
#ifndef WB_R2667_MIN
#define WB_R2667_MIN 0.03f              /* |R(2667)|/R0 >= this: LTE-like 66.7 us symbols (DJI OcuSync) (model: 0.05) */
#endif
#ifndef WB_R128_LTE_MAX
#define WB_R128_LTE_MAX 0.05f           /* and for the lte class R128 must stay under this */
#endif
#ifndef WB_R128_HIGH
#define WB_R128_HIGH 0.15f              /* conf "high" (with duty >= 90): the deciding feature from here (model 0.17-0.19) */
#endif
#ifndef WB_R2667_HIGH
#define WB_R2667_HIGH 0.04f             /* (model 0.043-0.058). The CP share caps R128 at 0.8/4 us = 0.2 and R2667 at
                                           4.7/71 us = 0.066: twice the minimum is out of reach for both */
#endif
#ifndef WB_MAX_PER_SWEEP
#define WB_MAX_PER_SWEEP 2              /* confirmation passes per sweep */
#endif
#ifndef WB_FOLD_MHZ
#define WB_FOLD_MHZ 25                  /* wideband candidates within this of a stronger one are the same emitter */
#endif
#ifndef WB_SIGMA_EXTRA_DEG
#define WB_SIGMA_EXTRA_DEG 5.0f         /* added to the bearing sigma of a wideband report (coarser levels at ~3 LSB rms) */
#endif

/* ---- Pull-in (off-channel analog carriers) ----------------------------------
 * A strong constant-envelope carrier between two table channels fails the
 * coherence gate on both (a 10 MHz offset steps 90 deg per sample). Its
 * centroid is in cfo_khz: retune onto it once and measure again. */
#ifndef PULLIN
#define PULLIN 1
#endif
#ifndef PULLIN_MIN_KHZ
#define PULLIN_MIN_KHZ 3000             /* |cfo| from here: retune onto the centroid and re-measure */
#endif
#ifndef PULLIN_MAX_PER_SWEEP
#define PULLIN_MAX_PER_SWEEP 2
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

/* ---- 2.4 GHz calibration (dual-band only) -----------------------------------
 * The same meaning as the 5.8 GHz constants above, for the 2.4 GHz plan: the
 * modem's noise floor and the LNA, if any, differ per band. */
#ifndef RF_NOISE_POWER_24
#define RF_NOISE_POWER_24 2.0f
#endif
#ifndef RSSI_CAL_DBM_AT_NOISE_24
#define RSSI_CAL_DBM_AT_NOISE_24 (-95.0f)
#endif
#ifndef RSSI_CAL_SLOPE_24
#define RSSI_CAL_SLOPE_24 1.0f
#endif
#ifndef RSSI_CAL_OFFSET_DB_24
#define RSSI_CAL_OFFSET_DB_24 0.0f
#endif
#ifndef RF_FRONTEND_GAIN_DB_24
#define RF_FRONTEND_GAIN_DB_24 0.0f
#endif

/* ---- Reporting ------------------------------------------------------------- */
#define HEARTBEAT_USB_S          60
#define HEARTBEAT_MESH_S         120
#ifndef MESH_REPORT_INTERVAL_MS
#define MESH_REPORT_INTERVAL_MS  8000   /* per emitter; the first report of a new emitter goes at once */
#endif
#define MESH_LINE_GAP_MS         350    /* pacing between lines into the Heltec */
#define MESH_JSON_MAX            191    /* one Meshtastic TEXTMSG as the v2 station proved it */
#define USB_JSON_MAX             768    /* the wideband record is ~600 bytes */
#define BENCH_PRINT_MS           500    /* bench line rate while holding a channel */
