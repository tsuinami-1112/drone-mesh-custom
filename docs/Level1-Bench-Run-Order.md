# Level 1 station v3: bench run order and session instructions

Branch `level1`, firmware `level1-c5phy/`, written 2026-10-08 against the
firmware at commit `f38f624` (50-channel plan, analog gate with the envelope
condition, wideband path, pull-in, dual-band variant). Companion to:

- the [bench guide](Level1-Station-v3-C5PHY-Bench-Guide.html): the procedure
  itself, stages 0–8 on sheets 6–9, the kit index and the filter-skirt record on
  sheet 10;
- the [bench data plan](Level1-Bench-Data-Plan.md): what each measurement
  changes, the decision rule for every outcome, what goes back to the lead for
  a decision, and the log. **Every decision after a measurement is taken from
  that plan, not from this document.**
- [`docs/bench/`](bench/README.md): where every raw record goes, one file per
  stage and board, before anything is concluded from it.

This document decides **in which order** the stages are run and **why**, and
writes the first sessions out in full for helpers who are comfortable with a
computer but are not the project lead. Parts 1 and 2 are for the lead; Part 3
onward is for whoever is at the bench. Everything here is on the reference
build (`seeed_xiao_esp32c5`, defaults, bare XIAO with its stock antenna until
the patches come in); the dual-band variant repeats stages 1, 5, 6 and 8 later,
as the data plan describes.

How Part 1 was built: every file of the firmware and its tests was read; the
port was compared line by line with its source, the C5VRX project (its
production `rf.c`/`video.c`, docs and legacy research); and the binaries the
Arduino build links were inspected directly (Espressif `esp-phy-lib`
release/v5.5 and master, `esp32-wifi-lib` release/v5.5, the Arduino
lib-builder configs, pioarduino's `platform.json`), together with the IDF 5.5
PARLIO RX driver and PHY glue and the arduino-esp32 `XIAO_ESP32C5` variant.

---

## Part 1 — How sure are we? (for the lead)

"Chance wrong" is my estimate that the assumption is wrong **today**, from the
code, C5VRX's hardware record and the IDF 5.5 binaries. Settled means 10 % or
less.

### 1a. Settled from the desk (no bench time needed)

| # | Assumption the firmware leans on | What we already have | Chance wrong |
|---|---|---|---|
| D1 | The six undocumented PHY calls exist in the IDF 5.5 C5 `libphy.a` (`phy_disable_agc`, `phy_rfagc_disable`, `phy_wifi_fbw_sel`, `phy_force_rx_gain`, `phy_set_freq`, `phy_chip_set_chan_offset`) | `nm` on `esp-phy-lib` release/v5.5 `esp32c5/libphy.a`: all six global, byte-identical sizes to the IDF 6 blob C5VRX used | 2 % |
| D2 | `lmac_stop_hw_txq` exists | `esp32-wifi-lib` release/v5.5 `libpp.a`: global | 2 % |
| D3 | `phy_track_pll_deinit` exists and stops the PHY's 1 s PLL-tracking timer | A non-static function in IDF's open-source `esp_phy/phy_common.c`, built on every non-ESP32 target. C5VRX never called it (its build removed the timer), so the port's call is its first use, but the symbol is real | 5 % |
| D4 | pioarduino "stable" = Arduino 3.3.12 on IDF 5.5 | `platform.json` 55.03.312 pins Espressif's `esp32-core-3.3.12-libs`; lib-builder branch release/v5.5 | 2 % |
| D5 | XIAO pin map D0=1 D1=0 D2=25 D3=7 D4=23 D5=24 D6=11 D7=12 D8=8 D9=9 D10=10, LED 27 | arduino-esp32 `variants/XIAO_ESP32C5/pins_arduino.h` | 2 % |
| D6 | PARLIO RX accepts two unwired lanes | IDF 5.5 `parlio_rx.c` skips negative pins with a warning; no all-lanes check | 5 % |
| D7 | Register recipe, lane order (Q bits on DIAG 6–9, I bits on DIAG 16–19), 40 MS/s, rising edge, LSB packing, SRAM-ownership write, no heap reservation | Identical to C5VRX-3 production; C5VRX-3 also runs an unreserved heap in that mode. Same board (XIAO C5) | 5 % |
| D8 | `phy_set_freq(uint16_t mhz, int offset)` signature | C5VRX disassembly of the 6.0 blob; same symbol size in 5.5 | 5 % |
| D9 | Gain index 62 = maximum; noise does not clip at 62 | C5VRX walk-around log: `G_act=62 P_med=1 clip=0` with the VTX off | 5 % |

### 1b. Open, most uncertain first

| Rank | Assumption | Chance wrong | Why that number | If wrong: impact / fix size | Earliest test |
|---|---|---|---|---|---|
| **1** | The bearing model: K derived from the antenna gain through a Gaussian main lobe and an empirical scale (`BEARING_K_SCALE` 2.5; 8 dBi → 72° → 2.97 °/dB), applied as strongest sector + K × neighbour difference | **60 %** that K is off by more than half; **40 %** that the model is marginal | No measurement behind it: the scale 2.5 was chosen to reproduce the earlier guess of 3 °/dB. The two neighbours sit 45°–135° off their own axes, in the side-lobe/back region where patch patterns are irregular and box diffraction dominates | The bearing is the project's output; sigma feeds the mapper's fix circle. Scale only: one constant. Non-linear model: new estimator in `bearing.c` (medium) | **Session D**: single-patch pattern sweep (needs the receiver alive, one patch, a pigtail, a VTX outdoors; no switch). Full: stage 6 |
| **2** | The wideband (digital-link) path as a group: candidate envelope `cv2` 0.5–1.5, duty ≥ 75, class edges `r128` ≥ 0.10 / `r2667` ≥ 0.03, the 66.7 µs symbol assumed for DJI (lag 2667), the bandwidth buckets, the 30 MHz ownership radius from a filter-skirt model, pull-in from 3 MHz off | **70 %** that at least one threshold moves; **50 %** that DJI's symbol is not 66.7 µs | All of it from synthetic waveforms; no DJI, Walksnail or HDZero capture has ever been fed to the code (the internals doc says so) | Digital detection quality and false reports from busy Wi-Fi; the analog core only through the shared splitter (rank 10) and the rule that a digital link within 30 MHz of a live analog carrier is not reported. Constants via the data plan's rules; a new lag feature if DJI's symbol differs (a session's work) | Session C (Wi-Fi access point idle and loaded), stage 5 skirt record (session E), stage 8 kits (session H) |
| **3** | `RF_NOISE_POWER` 2.0 is this board's no-signal power in 3-lane mode | **50 %** off by more than 1 dB | C5VRX measured median power 1–2 at gain 62 with four lanes; the constant is a mean; the 3-lane decode cannot read below 2.0 at all | Shifts every `level_db`, the threshold and `nf_dbm`. One constant (data plan stage 1) | **Session B** (B1) |
| **4** | Gain index steps are about 1 dB each (`GAIN_STEP` 3 = 3 dB) | **40 %** off by more than 30 % | Not stated anywhere in C5VRX. Espressif's RF-test library forces gain by index too, so the index is real; the dB per index is unknown | `level_db` of strong signals; **a bearing bias** whenever sectors settle at different gains; the hit decision on strong carriers. Constants, a table if non-linear, maybe equal-gain sectors (small code) | **Session B** (B1c, 5 min); stage 5 slope |
| **5** | The synthesizer follows `phy_set_freq` 60 MHz above the last Wi-Fi centre (E8 5945) | **40 %** (the new +10 MHz pulls for D1–D3 and the −27 MHz pull for L4: about 15 %) | 5945 MHz is 20 MHz above the Wi-Fi band edge; range unknown | Four channels (R8, E6–E8, with them HDZero R8 and Walksnail 5914). `-DC5PHY_MAX_MHZ=5885`, a lead decision (data plan stage 2) | **Session B** (B1b edge), session C |
| **6** | Video detection works on real FM video, PAL included | **35 %** needs changes | Only synthetic video tested; a window holds 6.4 lines; PAL and NTSC line periods differ by 0.7 %; PAL untested anywhere | `video`/`fp` fields and the stage 7 "never none" rule. `demod.c` tuning (medium); no raw capture dump exists to debug with | Quick look session C; full stage 4 (session E) |
| **7** | Sensitivity floor is within about 5 dB of an RX5808 station without the LNA | **35 %** (10 % with the LNA) | On paper kTB + ~6 dB noise figure lands near −95 dBm; the real noise figure and the 3-lane loss are unknown | BOM (LNA), range, whether v3 replaces v2: a lead decision (data plan stage 5) | Stage 5 (session E) |
| **8** | The 6-lane (3-bit) decode costs at most ~1 dB versus C5VRX's 8 lanes | **30 %** (more than 3 dB: 12 %) | Synthetic noise used sigma = 1.0 LSB; the real floor looks like 0.7–1.0 LSB, where the dropped bit matters most | Pin plan and carrier PCB (4-lane needs the underside pads free, frees D6), or the LNA | **Session B** (B1d, a reflash) |
| **9** | The "US" regulatory table accepts every Wi-Fi centre the plan parks on: 36–48, 100–128 (DFS), 144, 169–177 | **30 %** | C5VRX ran with the default table and channel 173; the port sets "US", parks on 149 and now also uses UNII-1 and the DFS block | `tune_fail`, coverage. `RF_COUNTRY_CC`, or `-DSCAN_5G1=0` / `-DLOWBAND=0` (data plan stage 2) | Session B (`wifi_ch` readings), session C |
| **10** | Real FM video keeps a constant envelope: `cv2` ≤ 0.5 (`ANALOG_CV2_MAX`), the third condition of every analog hit since the digital work | **25 %** that real video in multipath exceeds it at times | Model: FM video 0.02–0.3, OFDM about 1; nothing measured. New on the **analog core path** | Analog hits lost in multipath. The splitter is shared with the digital candidate rule, so moving it is a lead decision (data plan, section 4) | **Session B** (B1: `cv2` keyed, then walking the VTX about); stage 5 (`cv2` down to the threshold) |
| **11** | The whole receive chain runs under Arduino / IDF 5.5 (PHY held receive-only, dump engine streaming, pads looped into PARLIO, bytes decoding as I/Q) | **20 %** fails as written; **10 %** needs major work | Same board, registers and blob functions as C5VRX. Differences: Wi-Fi driver version; the Arduino libs are built with BLE, Thread, Zigbee and coexistence compiled in (C5VRX built with none); init order reversed; country code set | Everything. Worst case: debug closed-PHY state under Arduino or move to native ESP-IDF 6.0 (rewrite the Arduino parts of `main.cpp`) | **Session B** (B0, B1). First by necessity, not by uncertainty |
| **12** | 8 ms tune settle and 200 µs switch settle are enough; the first sector after a retune is not systematically low | **15 %** | Public API retunes synchronously; PLL lock is microseconds. But sector 0 is always the first measurement after a tune, so a bias here is silent | A bias away from N in every bearing. `TUNE_SETTLE_MS` or a throw-away window (tiny) | Session C (free check) |
| **13** | Mesh line, heartbeat, position, mapper integration, for analog and wideband reports | **15 %** | Desktop-tested JSON within 191 bytes; the Heltec serial path is the v2 proven setup | Fleet operation; configuration-level fixes | Stage 7 |
| **14** | `phy_set_freq` moves the synthesizer to any in-band MHz | **12 %** | C5VRX never validated it (its roadmap item is unchecked). But Espressif's own RF-test library calls `phy_set_freq` from its channel/frequency routines (`rf_test.o`, `wifi.o`), the disassembly shows a full retune, and the signature matches | 32 of the 40 analog channels become unreachable; the station would be an 8-channel detector | **Session B** (B1b, 10 min) |
| **15** | PE42442 truth table: all lines low = RF4, default `SECTOR_SWITCH_TABLE` matches the cabling | **10 %** from the datasheet, plus human cabling error per station | Datasheet tables 5–6; README documents it | Every bearing rotated by 90°/180°/270°, silently. Config | Stage 6a |

Deviations from C5VRX the port introduces (each 5–10 %, cheap to flip; the
first suspects if session B fails): PARLIO created before the PHY routes the
pads (C5VRX does the reverse); BLE/Thread/Zigbee/coexistence compiled in;
`esp_wifi_set_country_code("US")`; start at gain 62 (C5VRX starts at 52);
one-shot captures instead of a ring.

---

## Part 2 — Run order (for the lead)

Most uncertain first, inside the dependency gates. Session B exists because
nothing else can run before the receiver is alive; everything in it after B1 is
ordered by uncertainty. Session D is the main change versus the guide: the most
uncertain high-impact item (the bearing model) moves from last to third, tested
with one patch and no switch. The Wi-Fi part of the wideband checks moves into
session C because it is free there.

| Session | Who | What | Settles (Part 1 ranks) |
|---|---|---|---|
| **A** desk | lead | Host tests (the suite runs twice); both builds; `nm` on the installed libs; libs' sdkconfig for the record; strong-symbol build | D1–D3 on the actual package |
| **B** bench 1 | helpers + lead reachable | B0 flash/boot → B1 receiver alive, noise floor, `cv2` → B1b `phy_set_freq` (R3, cross-checks, E4/E8 edges) → B1c gain scale → B1d 6-lane vs 8-lane | 11, 3, 10, 14, 5, 4, 8, 9 (first readings) |
| **C** bench 2 | helpers | Stage 2 coverage and country → stage 3 selectivity, sector-equality, sweep-versus-hold, the Wi-Fi access point idle and loaded → quick video and `w` look | 9, 5, 12, the Wi-Fi half of 2, first look at 6 |
| **D** outdoors | helpers measure, lead computes | Single-patch pattern sweep, 15° steps, 360° | 1 (early), patch gain |
| **E** bench 3 | helpers + lead | Stage 5 sensitivity and calibration (RX5808 comparison, LNA decision) and the filter-skirt record of sheet 10, **then** stage 4 video (NTSC, PAL, no camera) | 7, 4 (confirm), 10 (confirm), the skirt radius of 2, 6 |
| **F** bench 4 | lead + helper | Stage 6: truth table → sector table → full 4-patch K sweep | 15, 1 (final) |
| **G** field | all | Stage 7 as the guide | 13 |
| **H** kits | lead + helper | Stage 8, one record block per digital kit (OpenIPC, HDZero, DJI O4, Walksnail), as the guide's sheet 9 | 2 |

Hardware to line up in parallel so sessions D–H are not the long pole: four
patches and pigtails, a u.FL removal tool, a turntable or compass marks for 15°
steps, the PE42442 evaluation board, a step attenuator, NTSC and PAL cameras,
access to a v2 RX5808 station, a 5 GHz access point and a laptop to load it,
and whatever digital kit stage 8 will get.

---

## Part 3 — For helpers: words and what the screen shows

**The station** is the small XIAO ESP32-C5 board. It talks to the computer
over USB. The **serial monitor** is the program on the computer that shows what
the station prints and lets you type commands to it. Every line the station
prints is one `{ … }` record with `"name":value` pairs.

**Commands** are typed into the monitor and finished with Enter. The ones used
here:

| You type | What it does |
|---|---|
| `?` | Prints one status line (counters) |
| `h A1` | Hold channel A1 and print a **bench line** twice a second (also `h R3`, `h E8`, `h D1`, …) |
| `g 56` | Fix the receiver gain at 56 (any number 2–62). `g a` = automatic again |
| `v` | Run a video check on the held channel |
| `w` | Run a digital-link ("wideband") check on the held channel; takes about 2 s and prints one line |
| `x` | Stop holding, go back to scanning all channels |

**A bench line** looks like this (yours will have different numbers):

```
{"info":"bench","ch":"A1","freq_mhz":5865,"wifi_ch":173,"sector":0,"switch":"000","gain":62,"level_db":0.4,"rssi_dbm":-94.6,"p_mean":2.19,"q_phase":8,"cv2":0.84,"clip":0.0,"cfo_khz":-3120,"mod":0,"noise":1,"stuck":0,"step_std":41.2,"nf_dbm":-95,"captures":1234,"cap_err":0}
```

The fields you will be asked to read:

| Field | Meaning in plain words |
|---|---|
| `wifi_ch` | Which Wi-Fi channel number the radio was parked on before fine-tuning. Just write it down |
| `gain` | Receiver amplification setting, 2 (low) to 62 (high). Automatic mode turns it down in steps of 3 when the signal is very strong |
| `level_db` | How strong the signal is, in dB above "nothing there". About 0 with no transmitter |
| `p_mean` | Raw signal power. About 2 with no transmitter |
| `q_phase` | How much the signal looks like a clean FM carrier, 0–100 %. Noise is under 15; a transmitter nearby is 50 or more |
| `cv2` | How much the signal's strength flickers. A steady FM transmitter reads under 0.3, noise about 0.8–1, a digital link about 1, bursty Wi-Fi above 1.5 |
| `clip` | Percent of samples that overloaded. Should be 0.0 unless the transmitter is very close |
| `cfo_khz` | How far the transmitter sits from the exact channel frequency, in kHz. Random with no transmitter; steady (same number within ±100) with one |
| `mod`, `noise` | 1/0 flags: `mod` 1 means "FM with content" (a camera), `noise` 1 means "just noise" |
| `stuck` | **Must be 0.** 1 means the raw data stream from the radio is frozen |
| `captures`, `cap_err` | How many data windows were taken, and how many failed. `cap_err` must stay 0 |

**Other lines you may see while scanning.** A line starting
`{"type":"analog_fm"` is a detected analog transmitter; `{"type":"wideband"`
is a detected digital link or busy Wi-Fi; `{"heartbeat":true` comes every
minute. Copy them when a step asks; otherwise let them pass.

**Jitter check.** With no transmitter, `p_mean` (second decimal) and
`cfo_khz` must change from line to line. If several lines in a row show exactly
the same `p_mean` and `cfo_khz`, write that down: it is a fault even if `stuck`
says 0.

**VTX** = the small FPV video transmitter used as the test signal. Use its
lowest power setting, keep it a few metres from the station, and keep its
antenna on (never power a VTX without an antenna). Know how to set its channel
(band letter + number, for example A1 = 5865 MHz) and confirm the channel on its
display or LED code.

**Stop rules.** Whenever a step says "stop", stop there, keep the station
running, save the log, and send the log plus the record sheet to the lead. Do
not try to fix things unless the step tells you what to change.

**Saving the log.** Start the monitor from the `level1-c5phy` folder with:

```
pio device monitor -b 115200 --echo -f log2file
```

`--echo` shows what you type; `log2file` writes everything to a
`platformio-device-monitor-*.log` file in the folder. At the end of the session
rename it `YYYY-MM-DD-<board name>-stage<N>.log` (for example
`2026-10-12-bench1-stage1.log`) and hand it in with the record sheet; the lead
files both under `docs/bench/`.

---

## Part 4 — Session A: desk checks (lead, 30–60 min, no hardware)

1. `make -C level1-c5phy/test/host` → the suite runs twice (default plan and
   dual-band) and must end with `ALL TESTS PASSED` and `check_json: … OK` both
   times.
2. Both builds once: `pio run -e seeed_xiao_esp32c5` and
   `pio run -e seeed_xiao_esp32c5_dualband` from `level1-c5phy/` (the first run
   downloads the platform and the Arduino libs). `platformio.ini` pins the
   pioarduino platform to release 55.03.312-1, so the build log's first lines
   must name that release and Arduino core 3.3.12. A Windows build that stops at
   "Failed to install Python dependencies into penv" with exit 3221225622 is a
   VPN or security product crashing the platform's `uv.exe`: the root README's
   troubleshooting table has the fix and a detour.
3. Confirm the blob check on the installed package (expect 6, 1 and 1 lines):
   ```
   P=~/.platformio/packages/framework-arduinoespressif32-libs/esp32c5
   nm --defined-only $P/ld/libphy.a | grep -E " T phy_(disable_agc|rfagc_disable|wifi_fbw_sel|force_rx_gain|set_freq|chip_set_chan_offset)$"
   nm --defined-only $P/lib/libpp.a | grep -w lmac_stop_hw_txq
   nm --defined-only $P/lib/libesp_phy.a | grep -w phy_track_pll_deinit
   ```
   (the Arduino libs package keeps `libphy.a` in `ld/`, the other two in
   `lib/`; done on 2026-10-08 in the cloud container on the pinned platform:
   6, 1 and 1 lines, libs 5.5.5+sha.b774170ff46, and the strong-symbol
   build of step 4 linked. Host `nm` reads RISC-V archives; the toolchain's
   `riscv32-esp-elf-nm` works too.)
4. Strong-symbol build: in `platformio.ini` remove the `; ` in front of the
   commented `-DC5PHY_STRONG_PHY_SYMBOLS=1` line, run
   `pio run -e seeed_xiao_esp32c5`, it must link; put the `; ` back.
5. For the station record: `grep -E "COEX_SW_COEXIST|^CONFIG_PM_ENABLE|PHY_CALIBRATION_MODE|BT_ENABLED|PHY_DISABLE_PLL" ~/.platformio/packages/framework-arduinoespressif32-libs/esp32c5/sdkconfig` and `git rev-parse --short HEAD`.

---

## Part 5 — Session B: the first bench session (helpers, lead reachable; about 2 hours)

**Purpose.** Find out whether the radio works as a receiver at all, measure its
"nothing there" level and how steady a real FM signal reads, find out whether
it can tune to any FPV channel, measure what one step of gain is worth, and
compare the two ways of wiring the raw data (6 lanes versus 8 lanes).
Everything is done on a bare board.

**You need.**
- The XIAO ESP32-C5 with its stock antenna clipped onto the tiny gold U.FL
  socket. Nothing else connected to any pin. Do **not** push the board into a
  breadboard or a socket: six of its pins must touch nothing at all.
- A USB-C **data** cable (a charge-only cable shows no port).
- A computer with PlatformIO installed and the `level1` branch checked out,
  terminal opened in the `level1-c5phy` folder.
- A VTX with a camera attached, set to lowest power, that can be set to A1
  (5865), R3 (5732), A7 (5745), B1 (5733) and, if it has them, E4 (5645) and E8
  (5945).
- The record sheet at the end of this part, printed or open.

**Before you start.** Lay the board on a non-conductive surface (paper, wood,
plastic) with only the USB cable attached. VTX off. Note the time.

### B0 — Flash and boot (10 min)

1. Erase the board, then flash, then open the monitor. Run these three commands
   one after another, each from the `level1-c5phy` folder:
   ```
   pio run -e seeed_xiao_esp32c5 -t erase
   pio run -e seeed_xiao_esp32c5 -t upload
   pio device monitor -b 115200 --echo -f log2file
   ```
   If the first command cannot find the board: hold the board's **BOOT** button,
   tap **RESET**, release BOOT, and run the command again. Press RESET once after
   the upload finishes.
2. The first line the station prints starts with
   `{"info":"c5phy v3 station ready"`. In that line find and write down:
   `"rf":` (true or false), `"phy_set_freq":` (true or false),
   `"iq_lane_bits":` (3), `"channels":` (50), `"gain_step":` (3),
   `"bearing_k":` (2.97).
   - `"rf":false` → **stop**. The line just before it starts with
     `{"info":"error"` and names what failed. Copy that whole line onto the
     record sheet.
   - Text like `Guru Meditation` or `abort()`, or the ready line repeating by
     itself → the board is crashing and restarting → **stop**, save the log.
3. Wait about 10 seconds for a line with `"heartbeat":true`. Write down
   `tune_fail`, `cap_err`, `bus_stuck`. All three should be 0.
4. Type `?` and press Enter. Write down `captures`, `cap_err`, `bus_stuck`,
   `heap`, `uptime_s`. Wait 60 seconds. Type `?` again and write the same
   numbers down.
   - Good: `captures` went up by at least 4000; `cap_err` and `bus_stuck` still
     0; `heap` within a few thousand of the first reading; `uptime_s` went up by
     about 60.
   - `uptime_s` smaller than before → the board restarted → **stop**.
   - `cap_err` or `bus_stuck` counting up → note it and continue to B1 (B1 will
     tell more).

### B1 — Is the receiver alive? (15 min)

Channel A1 is special: it is exactly a Wi-Fi channel, so this test does not
involve the fine-tuning function. It tests the receiver alone.

1. VTX still off. Type `h A1` and press Enter. The reply starts with
   `{"info":"hold","ch":"A1"`. Write down its `wifi_ch`.
   - 173 → normal, continue.
   - 169 or 177 → write it down, then also type `h A4` and use A4 (5805) instead
     of A1 for the rest of B1, with the VTX on A4. Tell the lead afterwards.
2. Bench lines now appear twice a second. Watch ten of them and write down
   typical values for `gain`, `level_db`, `p_mean`, `q_phase`, `cv2`, `clip`,
   `stuck`, `noise`, `nf_dbm`.
   Expected with no transmitter: `gain` 62, `level_db` between −2 and +2,
   `p_mean` between 2.0 and 2.8, `q_phase` under 15, `cv2` about 0.8–1.0, `clip`
   0.0, `noise` 1, `mod` 0, `stuck` 0, and the numbers jittering line to line
   (see the jitter check in Part 3).
   - `stuck` 1 → **stop** (the data stream is frozen). Check that truly nothing
     touches the board's pins, then save the log.
   - No jitter (identical `p_mean` and `cfo_khz` for many lines) → **stop**.
   - `p_mean` far above 3 or `clip` above 0 with the VTX off → write it down,
     type `g 50`, write down the new `p_mean` and `clip`, then `g a`. Continue.
   - Lines like `{"info":"bench","err":"capture: …"}` → write one down;
     continue; the lead will look at `cap_err_last` in `?`.
3. This no-signal `p_mean` is the board's noise reading, and this no-signal
   `cv2` is the noise flicker reading. Write both down clearly; they are the
   results the lead needs most from this step.
4. Switch the VTX on, on A1, a few metres away with the camera connected. Within
   a second the bench lines should change: `level_db` up by 30 or more; `gain`
   may drop below 62 in steps of 3; `q_phase` 50 or more; `cv2` under 0.3;
   `mod` 1; `noise` 0; `cfo_khz` now a steady number (same within ±100 from
   line to line). Write down typical `level_db`, `gain`, `q_phase`, `cv2`,
   `cfo_khz`, `clip`.
   - `level_db` went up but `q_phase` stayed under 20 → write it down and
     double-check the VTX is really on A1. If it is, **stop**.
   - `cv2` above 0.4 with the camera on → write it down with the `level_db`;
     continue, and make sure the lead sees it (it decides whether real video is
     steadier than the firmware assumes).
   - Nothing changed at all → try the VTX on A2 and type `h A2`. If still
     nothing, **stop**.
5. Switch the VTX off. The next line should look like step 2 again. Write "yes"
   or "no".
6. Switch it on again and slowly walk it 1 m closer and 2 m further away, then
   around the room behind furniture and people. `gain` should go down when
   close and back up when far; `level_db` should follow the distance;
   `q_phase` should stay 50 or more. Write down the **highest** `cv2` you see
   during the walk and where the VTX was at that moment.

### B1b — Can it tune to any channel? (10 min)

This is the most important single reading of the session for the lead. R3
(5732 MHz) is 12 MHz away from the nearest Wi-Fi channel, so the station must
use its fine-tuning function to get there.

1. Set the VTX to R3 and leave it on. Type `h R3`. Write down `wifi_ch` from the
   reply (expected 144).
2. Watch ten bench lines. Write down `level_db`, `q_phase`, `cv2`, `cfo_khz`,
   `mod`.
   - Tuning works: it looks like B1 step 4 (`q_phase` 50 or more, `cfo_khz`
     steady within ±2000).
   - Tuning does not work: `level_db` is up but `q_phase` stays low (under 20)
     and `cfo_khz` jumps around.
3. Cross-check A: set the VTX to A7 (5745), type `h A7`. A7 needs no
   fine-tuning, so it must look like B1 step 4. Write down `q_phase` and
   `cfo_khz`.
4. Cross-check B: set the VTX back to R3, type `h B1` (B1 is 5733, one MHz above
   R3, and the radio reaches it from the other side: expected `wifi_ch` 149). If
   tuning works, `q_phase` is high and `cfo_khz` is about 1000 lower than the R3
   reading from step 2. Write down `wifi_ch`, `q_phase` and `cfo_khz`.
5. Edges, if the VTX has these channels: VTX on E4, type `h E4`, write down
   `wifi_ch` (expected 128), `q_phase`, `cfo_khz`. VTX on E8, type `h E8`, write
   down the reply (either a hold line with `wifi_ch` 177, or an error line that
   says `tune failed`) and, if it held, `q_phase` and `cfo_khz`.

### B1c — What is one step of gain worth? (5 min)

1. VTX on A1, type `h A1`. Type `g 62`. Look at `clip`: it must be 0.0 and
   `p_mean` should be under about 50. If `clip` is not 0.0, move the VTX further
   away (or add attenuation) until it is. Do not move the VTX again during this
   step.
2. Type each of these, wait for three bench lines, and write down `p_mean` from
   the third line: `g 62`, `g 56`, `g 50`, `g 44`, `g 38`, `g 32`, `g 26`,
   `g 20`. Stop early if `p_mean` falls below about 8.
3. Type `g a`.

(The lead turns this into dB per step: 10·log10 of the ratio between
neighbouring rows is the worth of 6 index steps; the firmware assumes 6.0 dB
there and steps by 3 indices at a time.)

### B1d — 6 lanes versus 8 lanes (15 min)

This repeats B1 with the firmware reading the radio through 8 pins instead of
6. Nothing is wired; only the firmware changes.

1. Close the monitor (Ctrl+C). Open `platformio.ini` in the `level1-c5phy`
   folder. Find the line `; -DIQ_LANE_BITS=4` and delete the `; ` at its start
   so it reads `-DIQ_LANE_BITS=4`. Save.
2. Run the same three commands as in B0 (erase, upload, monitor). The ready line
   must now show `"iq_lane_bits":4`.
3. Repeat B1 steps 1–4 with the VTX in the same places as before, and write the
   values in the "8 lanes" column of the record sheet. Note: with 8 lanes
   `p_mean` with no transmitter can be below 2 and `level_db` can be negative;
   that is expected here, not a fault.
4. Repeat B1c for `g 62` and `g 56` only.
5. Put the `; ` back in front of `-DIQ_LANE_BITS=4`, save, and run erase +
   upload again so the board is back on the normal build. Confirm
   `"iq_lane_bits":3` in the ready line.

### If B1 failed: two things the lead may ask you to try

- Run B1d anyway (8 lanes). If 8 lanes work and 6 did not, the lead knows where
  to look.
- The lead may send you a small code change in `src/main.cpp` (`setup()`: call
  `rf_start()` before `iq_capture_init()`). Flash it the same way as B0.

### Session B record sheet

| Item | 6 lanes | 8 lanes |
|---|---|---|
| Ready line: `rf` / `phy_set_freq` / `iq_lane_bits` / `channels` / `gain_step` / `bearing_k` | | |
| First heartbeat: `tune_fail` / `cap_err` / `bus_stuck` | | |
| `?` at 0 s and 60 s: `captures`, `cap_err`, `bus_stuck`, `heap`, `uptime_s` | | |
| `h A1` → `wifi_ch` | | |
| No signal: `gain` / `level_db` / `p_mean` / `q_phase` / `cv2` / `clip` / `stuck` / `nf_dbm`; jitter yes/no | | |
| VTX on A1: `level_db` / `gain` / `q_phase` / `cv2` / `cfo_khz` / `clip` / `mod` | | |
| VTX off again → back to no-signal values? | | |
| Walk-about: gain follows? highest `cv2` and where | | |
| `h R3`: `wifi_ch` / `level_db` / `q_phase` / `cv2` / `cfo_khz` / `mod` | | — |
| `h A7` (VTX on A7): `q_phase` / `cfo_khz` | | — |
| `h B1` (VTX on R3): `wifi_ch` / `q_phase` / `cfo_khz` | | — |
| `h E4`: `wifi_ch` / `q_phase` / `cfo_khz` | | — |
| `h E8`: held or failed / `wifi_ch` / `q_phase` / `cfo_khz` | | — |
| Gain table `p_mean` at g = 62 / 56 / 50 / 44 / 38 / 32 / 26 / 20 | | (62 / 56 only) |
| Any `{"info":"error"…}` or `"err":"capture…"` lines (copy one) | | |
| Log file name, start and end time, VTX model and power setting | | |

---

## Part 6 — Session C: channel coverage and selectivity (helpers, about 1 hour)

**Purpose.** Check that the station can reach all 50 channels, that it reports
a transmitter only on the right channel, that the four "sector" readings agree
when they should, that ordinary Wi-Fi does not get reported as a drone, and
take a first look at video detection.

**You need.** Same as session B, plus a Wi-Fi access point that uses the 5 GHz
band somewhere in the building (most do), and a laptop or phone on it that can
copy a large file for a few minutes.

### C1 — Coverage (15 min)

1. Open the monitor as in B0 step 1 (third command). Type `x` so the station
   scans. Wait for the next `"heartbeat":true` line (up to 60 s). Write down
   `tune_fail` and `channels`. Expected 0 and 50.
2. For each channel in this list, type `h` + the channel and write down the
   reply's `wifi_ch`, or the words `tune failed` if that is what comes back:
   `R1 R4 R8 A1 A8 B4 B8 E1 E4 E5 E6 E8 F1 F8 X1 D1 L4`. Expected `wifi_ch` for
   D1 is 36 and for L4 is 100; the others the lead has.
3. If the VTX has E5 (5885): set it there, type `x`, and let the station scan
   for 10 minutes. Then wait for a heartbeat and write down `alias_drop` and the
   list of channels that appeared in `"type":"analog_fm"` lines (the `"ch"` and
   `"band"` fields).

### C2 — Selectivity, the sector check and Wi-Fi (25 min)

1. VTX on R3, camera on, a few metres away. Type `x`. Within two sweeps (about
   5 s) lines with `"type":"analog_fm"` appear. For one minute, write down every
   distinct `"band"`+`"ch"` that appears. Expected: R3 only, or R3 with B1 and F1
   folded away; nothing more than 40 MHz away from 5732. Also note whether any
   `"type":"wideband"` line appeared (expected: none).
2. In three of those R3 lines copy the four numbers in `"sectors":[…]` and the
   `"sector":` value. On this bare board all four numbers should be within about
   1 dB of each other and `sector` should vary between 0 and 3 at random. If the
   first number is always clearly lower than the other three, write "first
   sector low".
3. Type `h R3`. Write down `rssi_dbm` from a bench line. Compare with
   `rssi_dbm` in the scanning lines from step 1: they should agree within about
   2 dB. Write both down.
4. Any channel more than 40 MHz away that appeared in step 1: type `h` + that
   channel and write down `q_phase`, `cv2` and `cfo_khz`.
5. VTX off. Find the FPV channel nearest to the building's 5 GHz Wi-Fi (A-band
   channels A1–A7 sit on Wi-Fi channels 173–149; D1 sits next to Wi-Fi 36). Type
   `h` + that channel. Expected while the network is idle: `level_db` may be
   raised, `q_phase` under 40, `cv2` above 1.5. Write down `level_db`,
   `q_phase`, `cv2`. Type `w` and copy the whole line it prints.
6. Start a long file copy over that Wi-Fi (several minutes). Type `w` again,
   copy the line. Expected: `cls` `dot11` and `duty` 90 or more.
7. Stop the copy, type `x`, and let the station scan for two minutes with the
   network idle. Expected: no `"type":"wideband"` line. Copy any that appears.

### C3 — Quick video and digital-check look (5 min)

1. VTX on R3 with the camera connected. Type `h R3`, then `v`. Two lines come
   back: one starting `{"info":"video"` and one `{"info":"video_windows"`. Copy
   both lines whole.
2. Still holding R3, type `w` and copy its line. (On an analog transmitter it is
   expected to say `dot11`; that is known and is why the station only runs this
   check on channels that failed the analog test.)
3. Unplug the camera from the VTX (VTX still on), type `v` again, copy both
   lines.

### Session C record sheet

| Item | Reading |
|---|---|
| Heartbeat `tune_fail` / `channels` | |
| `wifi_ch` or "tune failed" for R1 R4 R8 A1 A8 B4 B8 E1 E4 E5 E6 E8 F1 F8 X1 D1 L4 | |
| 10 min with VTX on E5: `alias_drop`, channels reported | |
| VTX on R3 scanning: channels reported in 1 min; any `wideband` line? | |
| Three `sectors` arrays and `sector` values; "first sector low"? | |
| `rssi_dbm` held vs scanning | |
| Stray channel(s): `q_phase` / `cv2` / `cfo_khz` | |
| Wi-Fi channel idle: `level_db` / `q_phase` / `cv2`; `w` line | |
| Wi-Fi channel under a file copy: `w` line | |
| Two minutes scanning, network idle: `wideband` lines (expected none) | |
| `v` with camera: both lines; `w` on the held R3 | |
| `v` without camera: both lines | |

---

## Part 7 — Session D: single-patch pattern sweep (helpers outdoors; lead computes K)

**Purpose.** The bearing the station reports depends on how each patch
antenna's signal strength falls off as the transmitter moves off its centre
line. Nobody has measured this yet; the firmware derives its constant from the
antenna gain through a formula with an unmeasured fudge factor. This session
measures one patch's pattern all the way round. The lead then works out the
bearing constant and whether the method is sound, before any switch or box is
built.

**You need.**
- The XIAO with the stock antenna removed and one 5.8 GHz patch antenna
  connected through a u.FL-to-SMA pigtail. The u.FL socket is fragile: press
  the plug straight down until it clicks; to remove, lift straight up with a
  u.FL tool or a fingernail under the plug; never twist or pull on the cable.
  Rated for only a few dozen cycles.
- A laptop on battery (the monitor runs on it), and the patch fixed to
  something you can rotate in 15° steps: a turntable with angle marks, or a
  tripod with a compass rose taped on. The patch must stay at the same height
  and position while it turns; only its direction changes.
- The VTX with camera, lowest power, on A1, on a stand 20–30 m away at the same
  height, with clear line of sight, no people or cars moving between.
- An open outdoor space; ideally no buildings within 20 m to the sides.

**Steps.**
1. Point the patch straight at the VTX. This is 0°. Type `h A1`. Type `g a`
   (automatic gain). Watch ten bench lines: `q_phase` should be 50 or more.
   Write down `level_db`, `gain`, `q_phase`, `cv2`. If `q_phase` is low,
   something is wrong with the setup (channel, line of sight): fix it before
   continuing.
2. Turn the patch 15° clockwise (to 15°). Wait for five bench lines and write
   down the middle value of `level_db` and the `gain` and `q_phase` that go
   with it.
3. Repeat step 2 for every 15° step up to 345° (24 rows in total). Keep everyone
   still during each reading.
4. Go back to 0° and read again; it should match row 1 within 1 dB. Write it
   down.
5. If time allows, repeat the whole sweep with a second patch from the same
   batch (the four patches must behave alike).

**Record sheet.** One row per angle: angle, `level_db`, `gain`, `q_phase`,
note (for example "car passed"). Plus VTX distance, height, channel, weather,
patch serial/mark, and the stock-antenna `level_db` at the same spot if you
have time to swap back once.

**For the lead.** From the pattern g(θ) build the four sector responses
P_k(θ) = g(θ − az_k) for az = 0/90/180/270, compute the neighbour difference
D(θ) = P_{k+1} − P_{k−1} over θ ∈ [−45°, 45°] around each axis, fit θ ≈ K·D,
and check monotonicity and the side-lobe region. Correct `level_db` with the
measured dB-per-gain-step from B1c wherever `gain` changed during the sweep.
Compare K with the boot line's derived `bearing_k` (2.97 at 8 dBi); the data
plan's stage 6 rule turns the ratio into `BEARING_K_SCALE` (2.5 × measured /
derived) for the antenna family, and the on-axis level against the stock
antenna gives the patch gain to enter in Station setup.

---

## Part 8 — Later sessions (lead; the guide's own checklists plus these notes)

- **Session E, stage 5 first:** as the guide, including the filter-skirt record
  of sheet 10; fit the slope separately in the gain-stepped region and the
  fixed-62 region (confirms B1c); record `cv2` down to the threshold (confirms
  rank 10); measure the floor in both lane modes if B1d showed a difference;
  the LNA and the v2/v3 verdict are lead decisions (data plan stage 5). **Then
  stage 4:** as the guide; before the PAL attempt consider adding a raw-window
  dump command to the bench console so failed windows can be replayed through
  `test/host`.
- **Session F, stage 6:** as the guide and the README section "Checking the
  mapping on the bench" (`t 000/100/010/110` → ports; `s 0..3` → patches; walk
  the VTX clockwise → `sector` 0→1→2→3). Use the session D pattern to predict
  the sweep before running it; the data plan's stage 6 rules place the measured
  K (`custom_bearing_k` per station, `BEARING_K_SCALE` per antenna family).
- **Session G, stage 7:** as the guide.
- **Session H, stage 8:** one record block per digital kit as the guide's
  sheet 9; the data plan's stage 8 rules are long and specific, read them
  before the kit is switched on. Keep any analog VTX off or more than 30 MHz
  away during stage 8.
- **Dual-band:** stages 1, 5, 6 and 8 repeated on the `seeed_xiao_esp32c5_dualband`
  build with dual-band patches, per the data plan; not part of the sessions
  above.

Recommended small firmware additions (not part of this document; proposals for
the lead): a raw I/Q window dump command; the ready line reporting whether
`phy_track_pll_deinit` and `lmac_stop_hw_txq` resolved (today only the four
mandatory PHY calls and `phy_set_freq` are reported).
