# Level 1 station v3 — bench data plan

The working memory for the bench campaign. Written 2026-10-08, before any
hardware had run, at firmware commit `bd98938` on `level1`. A session that is
told "I'm going ahead with the bench tests now" reads this file first, in
full, and then works the loop in section 1 for every batch of data the user
brings. Everything a fresh session needs is here or linked: what each stage
measures, which constant, line of code, document or mapper row rests on that
measurement, what to change for each outcome, how to verify, and where to log
what was done. Keep this file current: it is edited in the same commit as the
change it describes.

Companion documents: the procedure itself is the bench guide
(`docs/Level1-Station-v3-C5PHY-Bench-Guide.html`, rendered to the `.pdf`
beside it; stages 0–8 on sheets 6–9, the kit index and the skirt record on
sheet 10); the reasoning behind every threshold is
`docs/Level1-Detection-Internals.md`; the root `README.md` carries the
condensed bring-up checklist and the troubleshooting table. The records the
user fills go to `docs/bench/` (see its README). The order the stages are
run in, with every assumption ranked by how likely it is wrong today and the
first sessions written out for helpers, is `docs/Level1-Bench-Run-Order.md`;
the decisions after each measurement stay here.

---

## 0. Ground truth

**Branches.** `level1` holds the station firmware (`level1-c5phy/`), these
docs and the root README; it is pushed directly. The mapper and the home node
live on `level2-main` (`mesh-mapper.py`, `node-mode-dualcore/`, `mapper_test/`,
`docs/REFERENCE.md`) and the mapper alone on `standalone-mapper-meshtastic`
(`mesh-mapper.py`, `mapper_test/`, `docs/REFERENCE.md`, `README.md`); both
take changes through a feature branch and a pull request, never a direct
push, and their shared level 1 functions stay byte-identical
(`docs/tools/mapper-parity.py` checks). The mixed level 1 + 2 station branch
is retired and will be restarted from `level1` plus `level2-main` later.

**Builds and tests.** From `level1-c5phy/`: `pio run -e seeed_xiao_esp32c5`
and `pio run -e seeed_xiao_esp32c5_dualband` (PlatformIO Core 6.2.0 or
newer, the minimum the pinned platform's `engines` field accepts; pioarduino
platform pinned in `platformio.ini` to release 55.03.312-1, Arduino core
3.3.12 / ESP-IDF 5.5). The pin replaced pioarduino's `stable` URL on
2026-10-08, when the two assets were byte-identical: PlatformIO never
re-downloads a platform it installed from a URL, so a `stable` URL can leave
an older copy building for ever, and `level2-main` pins the same release.
Host tests: `make -C level1-c5phy/test/host` (gcc, python3; runs the suite
twice, default plan and `-DDUAL_BAND=1 -DLOWBAND=2`, then `check_json.py`).
CI (`.github/workflows/firmware.yml`) runs the same on every push to
`level1`. Nothing is pushed red: host tests and both builds first. In the
Anthropic cloud container the PlatformIO toolchain download fails TLS
verification until the proxy CA (`/root/.ccr/ca-bundle.crt`) is appended to
the certifi `cacert.pem` files pioarduino's `penv_setup.py` points at; the
user authorised that edit on 2026-10-07; never disable verification instead.
On a Windows machine whose VPN or security product injects a Winsock LSP,
the `uv.exe` that `penv_setup.py` runs crashes with exit 3221225622
(`0xC0000096`) and the build stops at "Failed to install Python dependencies
into penv"; the root `README.md` troubleshooting table has the fix and the
detour.

**Where the numbers live.** Every tunable is a `#define` in
`level1-c5phy/include/config.h`, overridable per station with `-D` in
`stations.ini` (gitignored; `stations.example.ini` documents it; the Station
setup task `tools/station.py` writes it from `custom_*` options:
`custom_node_id`, `custom_station_lat/lon`, `custom_station_heading`,
`custom_antenna_dbi[_24]`, `custom_antenna_beamwidth_deg[_24]`,
`custom_bearing_k[_24]`). Three numbers are not in `config.h`: the bandwidth
bucket edges 0.78 / 0.52 / 0.30 on `r1` (`wb_classify`, `src/main.cpp`, and
duplicated in `test/host/test_level1.c`), the lag set 1 / 4 / 128 / 512 / 2667
(`iq_lag_features`, `src/demod.c`), and the per-window metric constants
(`Q_POWER_MIN` 8, `COH_LIMIT` 32 = ±45°, `MOD_STD_DEG` 4, `MOD_Q_MIN_PCT` 20,
the video search `W_MIN/W_MAX/W_IDEAL`, `PAL_PERIOD`, `NTSC_PERIOD`,
`PERIOD_TOL` 2.5 %, `MIN_SWING` 4, all in `src/demod.c`). The radio ceiling
`C5PHY_MAX_MHZ` defaults to 5945 in `src/fpv_channels.c`.

**Trap: the host test carries its own copy of the class rule.**
`test/host/test_level1.c` does not include `config.h`; it defines fallbacks
for `WB_R128_MIN`, `WB_R2667_MIN`, `WB_R128_LTE_MAX`, `WB_R128_HIGH`,
`WB_R2667_HIGH` and repeats the bucket edges. The first time a threshold
changes, either mirror it there or, better, make the test take them from
`config.h` (add `#include "config.h"`; the Makefile already passes
`-I../../include`) and delete the fallbacks.

**Where a changed number is quoted** (grep the old value across these before
committing; the list is the usual places, not a guarantee):

| Constant / fact | Quoted in |
|---|---|
| `DETECT_LEVEL_DB` 8, `Q_MIN` 40, `ANALOG_CV2_MAX` 0.5 | `config.h`; boot line (`threshold_level_db`, `q_min`); root README "How it works" and bring-up table; `level1-c5phy/README.md` detection section; internals §3; bench guide stages 1, 3, 5; `test_level1.c` gate assertions |
| `RSSI_CAL_*`, `RF_NOISE_POWER[_24]`, the −87 dBm threshold, the −95 reference | `config.h`; sample boot/heartbeat lines in both READMEs and bench guide sheet 4; internals §2–3; bench guide stage 5 ("expect −85 to −90"); `mapper_test/level1_bearing_sim.py` (`level = rssi + 95`) on both mapper branches |
| `WB_*` thresholds, duty 75 / 90, bucket edges | `config.h`; `main.cpp` `wb_classify`; `test_level1.c` fallbacks; internals §4 tables; `level1-c5phy/README.md` wideband table; bench guide stage 8 expected rows; mapper `WIDEBAND_SYSTEMS` (buckets, `duty_min` 90) and both `docs/REFERENCE.md` |
| `WB_ANALOG_OWN_MHZ` 30, `WB_FOLD_MHZ` 25, `PEAK_PICK_MHZ` 20 | `config.h`; `sweep_decide.c` comments; `test_level1.c` `test_sweep_decide` (`sw_rules`); internals §3–5; root README troubleshooting; bench guide sheet 10 |
| Antenna model: 8 dBi → 72°, K 2.97–3.0 °/dB, σ 10°, `BEARING_K_SCALE` 2.5 | `config.h`; `station.py` (`DEFAULT_DBI`, `BEAMWIDTH_MIN_DEG`); `stations.example.ini`; root README antenna section; `level1-c5phy/README.md` setup table; internals §8; bench guide stage 6 and the boot line's `bearing_k` |
| Channel counts 50 / 55 / 58, `C5PHY_MAX_MHZ` 5945, the 60 MHz pull | `fpv_channels.c`; `config.h` comments; both READMEs; internals §6; bench guide stage 2; `test_channels` (expects 50 / 58) |
| `SECTOR_SWITCH_TABLE` | `config.h`; root README "Line states for each sector"; bench guide sheet 2 and stage 6 |
| Power and timing (≈ 200–240 mA, 2.5 s sweep, 2 s `w`) | root README power table and sector section; bench guide power table; internals §10 |
| Status: "nothing bench validated", "nothing has run on hardware", *(model)* markers | bench guide footers (11 occurrences) and cover callout; `level1-c5phy/README.md` line near the top; internals intro note and §10 "what only the bench can prove"; `config.h` comments marked `(model)` |

**Model harness.** `level1-c5phy/test/model/sim_skirt.c` is the FM-through-
filter-skirt model that set `WB_ANALOG_OWN_MHZ` (two filter shapes, three
levels, two video deviations). Re-run it with a filter shape fitted to the
stage 5 skirt record when deciding the radius.

---

## 1. The loop for every batch of data

1. **Record first.** Put what the user brings into `docs/bench/` exactly as it
   came (console lines in a fenced block, record-sheet values as a table, a
   photo described in words), one file per stage and station:
   `docs/bench/YYYY-MM-DD-<board or station id>-stage<N>.md`, with the build
   (commit, environment, extra `-D` flags), the chain (VTX, attenuator, LNA,
   cables, antenna) and the ambient conditions the sheet asks for. Do this
   before interpreting anything; a half-read value is still data.
2. **Decide with the stage's rules** in section 2. Where the rule says "ask",
   put the question and the data to the user and stop at that item; carry on
   with the rest.
3. **Edit.** Constants in `config.h` change only when the data comes from the
   reference build (3-lane decode, `GAIN_MAX` 62, no LNA unless the sheet says
   the LNA was in the chain, in which case follow the LNA rules of stage 5).
   Station-specific numbers (switch table of a different switch, cable loss,
   measured K of one box) go to that station's `stations.ini` as `custom_*`
   options or `-D` flags, and into `stations.example.ini` as a documented
   example, not into the defaults. Every changed number is also changed where
   it is quoted (table above). Replace a *(model)* marker with "measured X
   (model said Y)" rather than deleting the model figure.
4. **Verify.** `make -C level1-c5phy/test/host`, both `pio run` environments,
   and, when the guide's HTML changed, re-render the PDF and check the sheet
   fill (section 3). When a mapper branch changed: `python3 -m py_compile`,
   the parity check, the standalone `mapper_test/test_mesh_direct.py`.
5. **Docs and status.** Move the stage's line in the bench guide footer
   status, the internals §10 bench list and this plan's status fields from
   "model" / "unproven" to what was measured, with the date and the board.
6. **Push `level1`; open PRs for the mapper branches.** Commit message says
   which stage's data drove the change. Then append to the log in section 5.

---

## 2. Stage by stage

Each stage lists what the user delivers, the claims it tests, what in the
repo rests on it, the decision rules and the edits, then a status line.
"Reference build" = `seeed_xiao_esp32c5`, defaults, bare XIAO with the stock
antenna until stage 6.

### Stage 0 — flash and boot (sheet 6)

**Delivers:** the boot line (`"rf"`, `"phy_set_freq"`, `iq_lane_bits`,
`channels`), any `{"info":"error","stage":…,"call":…,"err":…}` line, two `?`
status lines 60 s apart (`captures`, `cap_err`, `bus_stuck`).

**Tests:** that this core's libphy exports the undocumented calls
(`phy_disable_agc`, `phy_rfagc_disable`, `phy_wifi_fbw_sel`,
`phy_force_rx_gain`, `phy_set_freq`), that the PHY can be held receive-only
and that PARLIO delivers I/Q windows. The whole station rests on this; it is
the first of the "what only the bench can prove" bullets.

**Rules.**
- `"rf":true`, `"phy_set_freq":true`, `captures` climbing, `cap_err` 0: record
  the platform and core version the build used (from `pio run -v` or
  `platformio.ini`'s pin) in the record and in the bench guide's cover status
  row; update the status strings (section 3) to "stage 0 passed on <board>,
  <date>".
- `"rf":false`: the error line names the call. A `(not exported by libphy)`
  error means this core's libphy lacks the symbol: do not patch around it;
  report to the user with the core version, and look at whether a different
  pioarduino platform version exports it (the pin is in `platformio.ini`).
  Any other failing stage of `rf_start` is a bring-up bug: the sequence is in
  `src/c5phy_rf.cpp`, modelled on C5VRX.
- `"phy_set_freq":false` with `"rf":true`: the radio can only park on public
  centres; `tune_fail` will climb on every off-centre channel. Report; the
  plan has no fallback plan for this (the exact-MHz step is the receiver).
- `cap_err` climbing or `bus_stuck` > 0 with lanes unconnected: PARLIO or
  lane wiring; `IQ_LANE_GPIOS` / `IQ_LANE_DIAG` in `config.h` are the knobs,
  the rule that the six lane pads stay unconnected is in both READMEs.

**Status:** not started.

### Stage 1 — receiver alive (sheet 6)

**Delivers:** on a quiet channel: `level_db`, `p_mean`, `q_phase`, `cv2`,
`gain`, `clip`, `noise`, `stuck`, `nf_dbm`; with a VTX keyed on A1: the rise
in `level_db`, `gain`, `q_phase`, `cv2`, `mod`, `cfo_khz`; dual-band: the same
on `h G3`.

**Tests:** the noise reference (`RF_NOISE_POWER` 2.0 is C5VRX's figure, not
this board's), the noise statistics the gates assume (`q_phase` under 15,
`cv2` about 1 on noise; the model gave 0.8), that FM video reads coherent
(`q_phase` ≥ 50) with a steady envelope (`cv2` ≤ 0.3, gate limit 0.5), that
the offset estimate is right (`cfo_khz` within ±2000 on-channel), and on the
dual-band build that the I/Q bus works at BW40 on 2.4 GHz.

**Rules.**
- `p_mean` on a quiet channel at gain 62, 3-lane build: set `RF_NOISE_POWER`
  to it when it differs from 2.0 by more than 10 %; `RF_NOISE_POWER_24` from
  G3 on the dual-band build. Update the bench guide's "p_mean ≈ 2" and the
  internals §2 row; the host test's 2.75 is the synthetic model's figure and
  stays.
- `cv2` on noise: write the measured value into internals §2 and the guide.
  Under 0.6 it crowds the `noise` flag (0.5) and `WB_CV2_MIN` (0.5): ask the
  user before moving the analog / digital splitter (`ANALOG_CV2_MAX` and
  `WB_CV2_MIN` move together; the cost is on the digital candidate side).
- `q_phase` on noise above 15: the margin to `Q_MIN` 40 shrinks and
  `MOD_Q_MIN_PCT` 20 (demod.c) may read noise as modulated; report with the
  number; a `Q_MIN` change is a design change (ask).
- Keyed VTX `cv2` above 0.3 with the camera on: real video sits closer to
  the splitter than the model; if above 0.4 ask before anything else, since
  `ANALOG_CV2_MAX` 0.5 would start losing analog hits in multipath.
- `cfo_khz` sign: if the VTX is known to sit above the channel and `cfo_khz`
  reads negative (or `freq_peak` in stage 3 lands on the wrong side), I and Q
  are swapped in the lane map; fix in `IQ_LANE_GPIOS` order or the nibble
  decode in `demod.c`, never by negating `cfo_khz` downstream. Ask first:
  it changes every captured value.
- `stuck` 1 on a live board: lane wiring; see stage 0.
- Dual-band `h G3` shows no rise with a 2.4 GHz source: the dual-band
  environment is not usable; mark it so in both READMEs and the bench guide
  until solved, and keep stations on the single-band build.

**Status:** not started.

### Stage 2 — channel coverage (sheet 6)

**Delivers:** `tune_fail` after a heartbeat with the deployment country,
which channels were refused and the error text, `h E4` / `h E8` holds with
their `wifi_ch`, the E8-versus-E5 mirror test, `h D1` / `h L4` (`h G1` /
`h G5`), `alias_drop`.

**Tests:** the regulatory table under `RF_COUNTRY_CC`, that the synthesizer
follows `phy_set_freq` 60 MHz past the last public centre (E8 5945 from
5885), that the D, L and G bootstrap centres hold, and whether the alias
guard ever fires.

**Rules.**
- Refusals fixed by the country code: set `RF_COUNTRY_CC` in `config.h` to
  the deployment country if the user says every station is in that country;
  otherwise it stays per station in `stations.ini`. Refusals of the D or L
  points that no country code fixes: the station drops them with
  `-DSCAN_5G1=0` / `-DLOWBAND=0`; note it in the README troubleshooting row
  that already covers `tune_fail`.
- The synthesizer does not follow (E8 deaf, a VTX on E5 heard on E5, E7, E8
  alike): ask the user whether `C5PHY_MAX_MHZ` 5885 becomes the default (all
  C5 modules share the PHY, so probably yes). If yes: change the default in
  `src/fpv_channels.c`, update the channel counts everywhere (50 → 46,
  55 → 51, "58 at most" → 54 in `config.h`, `main.cpp` and the docs), the
  `test_channels` expectations, the bench guide stage 2 and stage 8 rows
  (HDZero R8 5917 and Walksnail 5914 unreachable) and the root README
  hardware notes; keep `ALIAS_GUARD` on. The mapper rows for 5914 / 5917 stay
  (another receiver may reach them).
- The synthesizer follows 60 MHz: record it; the `LOWBAND` 2 pull of 140 MHz
  (L1–L3) is a separate test only if the user cares about 5362–5436 MHz.
- `alias_drop` climbing on a board where E8 does follow: the guard is
  dropping real carriers; look at the levels (a second emitter within 2 dB of
  one near 5885); `ALIAS_LEVEL_DB` can come down to 1.0 before the guard is
  turned off.

**Status:** not started.

### Stage 3 — selectivity (sheet 6)

**Delivers:** channels reported with a VTX on R3 (R3 alone, or B1 / F1
folded), any hit more than 40 MHz away with its `q_phase` and `cfo_khz`,
`cfo_khz` → `freq_peak` on `h R3`, and the access-point control: `cv2` on
the AP's channel idle, `cls` and `duty` under a long file copy.

**Tests:** `PEAK_PICK` 20 MHz folding, that coherence rejects everything
off-channel (`Q_MIN`), the offset estimate against a known VTX frequency,
and the two Wi-Fi claims: idle traffic never becomes a report
(`WB_CV2_MAX` 1.5 or `WB_DUTY_MIN` 75 stop it), a saturated link is reported
as `dot11` with `duty` ≥ 90 (the mapper labels that "802.11 video link";
under 90 "Wi-Fi traffic").

**Rules.**
- A hit more than 40 MHz from the VTX: if `q_phase` ≥ 40 there, the VTX is
  overloading the front end (check `clip` and `gain` on `h`) or the lane
  decode is wrong; note the level at which it starts and treat it as the
  station's overload point in the README; no constant moves for it.
- `freq_peak` off by more than 1 MHz from the VTX's set frequency on a
  stable `cfo_khz`: see the I/Q swap rule in stage 1 if the sign is wrong;
  if the magnitude is wrong, `DEMOD_SAMPLE_RATE_HZ` (40 MS/s) is not what the
  bus delivers: report, do not tune.
- Idle AP produces a `wideband` report: find which gate let it through from
  the `w` output (`cv2` inside 0.5–1.5 and `duty` ≥ 75 on beacons would mean
  very busy air). First move is `WB_DUTY_MIN` 75 → 90 (the mapper already
  treats under 90 as traffic); `WB_CV2_MAX` stays unless `cv2` on idle Wi-Fi
  reads under 1.5 consistently, then ask.
- Loaded AP reports `dot11` with `duty` under 90: the 90 rule in the mapper's
  802.11 rows is too high for real traffic; hold the change until the OpenIPC
  link in stage 8 gives the duty of a real video link, then set the row's
  `duty_min` between the two (both mapper branches, both REFERENCE tables,
  the root README troubleshooting row).
- B1 / F1 never hit at all with a VTX on R3: fine, note it; `PEAK_PICK` stays
  for the 1 MHz R3 / B1 case.

**Status:** not started.

### Stage 4 — video check (sheet 7)

**Delivers:** `v` output with an NTSC camera (windows with `video:1`,
`std`, `line_hz`, `present`), the same with PAL, the keyed-no-camera case
(`present:0`, `carrier`), and the detection line's `video`, `sync_hz`, `fp`.

**Tests:** the sync-pulse detector on real video (`W_MIN` 128 to `W_MAX` 288
samples, `PERIOD_TOL` 2.5 %, `MIN_SWING` 4, polarity search), PAL in
particular (unproven on this receiver), `VIDEO_MIN_WINDOWS` 3 of 8, and the
`carrier` split (`MOD_STD_DEG` 4° on the box-averaged discriminator).

**Rules.**
- NTSC fails: a detector problem, not a threshold; the per-window `swing`,
  `pulses`, `periods`, `period` from `v` go into the record and to the user
  with a proposed change to `video_window` in `demod.c`; add the failing
  shape to the host test's synthetic cases when the cause is known.
- PAL fails, NTSC passes: same data; look first at `PAL_PERIOD` 2560 against
  the measured `period` and at the swing on the PAL camera; a tolerance
  change is a one-line edit plus the test's PAL cases.
- Keyed, no camera, reads `carrier:"fm"`: `MOD_STD_DEG` 4 is under the VTX's
  idle deviation; raise it to half of the measured `step_std` on the bare
  carrier. Camera on reads `cw`: lower it to half the measured video value.
  Update the internals §2 `mod` row.
- `sync_hz` more than 15 Hz from 15 734 / 15 625 on a real camera: the
  camera's clock, not a bug; widen the `fp` tolerance note in the README if
  the user wants two stations' `fp` to agree on the mapper.

**Status:** not started.

### Stage 5 — sensitivity, calibration and the filter skirt (sheets 7 and 10)

**Delivers:** the level record (input dBm against `level_db`, `gain`,
`q_phase`, `cv2`, hit or not, at −90 … −30 dBm), the measured slope and
floor, the same floor on a v2 RX5808 station, the optional LNA sweep (floor
improvement, clipping onset, `RF_NOISE_POWER` re-measured), the quiet-band
60 s maximum, the dual-band repeat on a G channel, and the skirt record
(six channels 11–31 MHz off a VTX on R4 at `level_db` 35–40: `level_db`,
`q_phase`, `cv2`, pass or not; then two minutes of scanning with the VTX on).

**Tests:** `level_db` linearity (1 dB per dB), the dBm line
(`RSSI_CAL_DBM_AT_NOISE` −95, `RSSI_CAL_SLOPE` 1.0), the floor and so the
v2 / v3 verdict, the gain loop near threshold (`GAIN_STEP` 3,
`CLIP_MAX_PCT` 3: no notch where a carrier just above threshold is lost when
the gain steps), the detection margin (`DETECT_LEVEL_DB` 8 over the quiet
maximum by ≥ 6 dB), the LNA's worth (`RF_FRONTEND_GAIN_DB`), the `_24`
calibration, and the skirt: the real reach of a strong FM carrier's image,
which set `WB_ANALOG_OWN_MHZ` 30 on a model.

**Rules.**
- Slope within 1.0 ± 0.05: keep `RSSI_CAL_SLOPE` 1.0. Outside: set it to the
  fitted slope and say so in the internals §3 table.
- `RSSI_CAL_DBM_AT_NOISE`: the input level at which the fitted line gives
  `level_db` 0 (two points well inside the linear range, e.g. −70 and −50
  dBm). Set it from the first calibrated reference board; a second board
  within 1.5 dB confirms it as the default, otherwise the spread goes into
  the docs as the per-station uncertainty. Then update every "−87 dBm
  threshold" and "−95 reference" quote (table in section 0) to the measured
  figures and mark them measured.
- Floor against the RX5808 station: write the difference into the root README
  hardware section and the bench guide stage 5 line; this is the user's
  decision input, not a constant. If v3 is more than 6 dB deafer, raise the
  LNA question with the LNA sweep's numbers.
- LNA sweep: calibration taken with the LNA in the chain keeps
  `RF_FRONTEND_GAIN_DB` 0 and gets its own `RSSI_CAL_DBM_AT_NOISE` in that
  station's `stations.ini`; a station that adds the LNA to a calibration taken
  without it sets `RF_FRONTEND_GAIN_DB` to the measured gain (the comment in
  `config.h` says 20; replace with the measurement). `RF_NOISE_POWER` with
  the LNA goes to that station too, not to the default. If the LNA improves
  the floor by ≥ 3 dB on the single-band build, the README's "fit it if
  stage 5 shows…" becomes "fit it: +X dB", and the bench guide's optional
  marks on the LNA items go.
- Clipping onset: record the dBm at which `clip` stays above 3 % at
  `GAIN_MIN` 2; that is the station's overload point for the README. Nothing
  to tune: the gain range is the PHY's.
- Notch: a "hit while scanning" column that reads no between two yes
  columns means the gain step still loses a carrier near threshold; try
  `CLIP_MAX_PCT` 10 before `GAIN_STEP` 2 (the internals §3 explains the
  trade), and run the host test's gain-loop cases after.
- Quiet-band maximum: `DETECT_LEVEL_DB` = that maximum + 6 dB, rounded up to
  the half dB, when it comes out above 8; below 8 the default stays (do not
  lower it: the digital candidate rule shares it). A change moves
  `threshold_level_db` in every sample line and the gate quotes (section 0).
- `_24` set: the same four rules on the G-channel sweep →
  `RSSI_CAL_DBM_AT_NOISE_24`, `RSSI_CAL_SLOPE_24`, `RF_NOISE_POWER_24`,
  `RF_FRONTEND_GAIN_DB_24`.
- Per-station offset: `RSSI_CAL_OFFSET_DB` has no `custom_*` option yet; the
  first station that needs one (stage 6 insertion loss, cable loss) gets a
  `custom_rssi_offset_db` option added to `tools/station.py`
  (`ANTENNA_OPTIONS`-style entry, define `RSSI_CAL_OFFSET_DB`, range −10 … 30),
  `tools/station_setup.html`, `stations.example.ini` and the Station setup
  table in `level1-c5phy/README.md`. Convention: the passive loss between the
  antenna's SMA and the U.FL, positive, so `rssi_dbm` refers to the antenna
  connector.
- **Skirt record → `WB_ANALOG_OWN_MHZ`.** A held channel "passes" when
  `level_db` ≥ 8 and `cv2` is within 0.5–1.5 at the same time. Radius needed
  = the largest passing offset + 5 MHz. Over 30: raise `WB_ANALOG_OWN_MHZ`
  to it (round up to 5). Nothing passes beyond 20: set 25 (keep the margin
  over `PEAK_PICK_MHZ`). Between: keep 30. Whatever the outcome, replace the
  model wording in `config.h`, internals §4, the root README troubleshooting
  row and bench guide sheet 10 with the measured offsets, update `sw_rules()`
  and the B4 / A7 case comment in `test_sweep_decide` if the number moved,
  and re-run `test/model/sim_skirt.c` with a filter edge fitted to the
  measured levels (the `design()` calls set cutoff and tap count) so the
  model's numbers in the docs match a filter shape that reproduces the
  record. The two-minute scan must show no `wideband` line: if a `DF:` line
  appears more than the radius away from R4, record its channel, `cls`,
  `cv2` and `fc_mhz`; a second mechanism is at work and needs the user.
- If the skirt passes at offsets where `q_phase` is above 40 (it should not):
  that is an analog hit on a neighbour, i.e. `PEAK_PICK` territory, and
  `PEAK_PICK_MHZ` would need to grow with it; ask.

**Status:** not started.

### Stage 6 — RF switch and pattern (sheet 8)

**Delivers:** the truth table (`t 000` … `t 110` → RF port), `s 0` … `s 3`
following the patch, insertion loss (and with the LNA), the 15° rotation
sweep at 30 m (all four `sectors` per step), the derived K against the boot
line's `bearing_k`, the measured K, and the residuals of `bearing_deg`
against truth.

**Tests:** `SECTOR_SWITCH_TABLE`, the antenna model (`sqrt(32400 / G)`
beamwidth, K = `BEARING_K_SCALE` 2.5 × beamwidth² / 4320, σ base 10° at 72°),
the ±45° clamp, and the loss budget between the patch and the U.FL.

**Rules.**
- Truth table differs from the default table for the PE42442: if the
  reference design uses that board, change `SECTOR_SWITCH_TABLE` in
  `config.h` and the root README "Line states" table; a different switch
  gets its table in `stations.ini` and a line in the README's "Any other
  switch" section.
- Insertion loss: becomes that station's `RSSI_CAL_OFFSET_DB` (see stage 5;
  add the option first); with the LNA in the path the net gain goes to
  `RF_FRONTEND_GAIN_DB` rules of stage 5.
- Measured K from the neighbour-sector difference slope: the station's
  `custom_bearing_k`; `BEARING_K_SCALE` default = 2.5 × measured / derived
  for the antenna family, once two boxes with the same patches agree within
  15 %. Update the §8 table values, the boot-line samples' `bearing_k`
  (2.97) and the station setup docs. If the patch datasheet beamwidth
  differs from the `sqrt(32400 / G)` figure by more than 15°, prefer the
  datasheet in `custom_antenna_beamwidth_deg` and say so in the README's
  antenna section.
- Bearing residuals: `BEARING_SIGMA_BASE_DEG` = the RMS error at good S/N
  over the sweep (currently 10° at 72°); if the error grows past ±30° off
  the sector axis the `BEARING_MAX_OFFSET_DEG` 45 clamp is hiding it and the
  model's K is wrong off-axis, which is a finding for the user rather than a
  constant. The mapper's `_clamp_sigma` floor (2°) and ceiling (60°) only
  move if the station's σ ever leaves that range.
- Save the sweep table to `docs/bench/` as data, not only the derived K.

**Status:** not started.

### Stage 7 — field acceptance (sheet 8)

**Delivers:** two stations' fix results on ten points (hits inside the 90 %
circle), the mesh copy's completeness (`fp` arriving), 72 h on solar
(brownouts, heartbeat gaps), station current at 5 V.

**Tests:** the whole chain (mesh pacing `MESH_REPORT_INTERVAL_MS` 8 s,
`HEARTBEAT_MESH_S` 120, the 191-byte line, the home node forwarding), the
mapper's fusion (`BEARING_FUSE_WINDOW_S` 30, `BEARING_OBS_KEEP_S` 300,
`BEARING_MIN_CROSSING_DEG` 8, `BEARING_OUTLIER_DEG` 20, `BEARING_MAX_RANGE_M`
20 km) against the station's σ model, and the power budget.

**Rules.**
- Fewer than 9 of 10 inside the circle with bearings individually sane: the
  σ model is optimistic; raise `BEARING_SIGMA_BASE_DEG` (and `WB_SIGMA_EXTRA_DEG`
  for digital) until the circle holds; too many inside with large circles
  the other way. More than one station's line regularly excluded as an
  outlier: look at `BEARING_OUTLIER_DEG` (mapper branches, PR) only after
  headings and positions are confirmed.
- `mesh_drop` or `usb_drop` climbing in heartbeats: the Heltec queue; raise
  `MESH_REPORT_INTERVAL_MS` or `MESH_LINE_GAP_MS` 350 and document the
  airtime cost.
- Measured current: replace the estimates in the root README power table and
  the bench guide power table; re-check the solar sizing text (20 W / 50 Wh)
  against the measured daily energy.

**Status:** not started.

### Stage 8 — digital video links (sheet 9), one block per kit

**Delivers, per kit:** held channel; `level_db`, `q_phase`, `cv2` on `h`;
three `w` results (`duty`, `cls`, `conf`, `bw_mhz`, `fc_mhz`, `cv2`, `r1`,
`r4`, `r128`, `r512`, `r2667`, `scan_lag`, `scan_r`); one `wideband` line per
sweep under `x` and the mapper's `system` / `system_conf`; the rotation
(bearing error at 0 / 15 / 30 / 45°, σ, the digital K); the kit's own
setting (channel, bandwidth, power). The dual-band block repeats it at 2.4
GHz.

**Tests:** everything the wideband path assumes, all of it from a synthetic
model so far: the candidate gate on real links (`cv2` 0.5–1.5, `q_phase`
under 40, level steady within 6 dB over three windows), `WB_DUTY_MIN` 75
against real TDD duty cycles, the class rule (`WB_R128_MIN` 0.10 for 802.11,
`WB_R2667_MIN` 0.03 with `WB_R128_LTE_MAX` 0.05 for the LTE-like class, the
`_HIGH` marks 0.15 / 0.04), the lag 2667 itself (a 66.7 µs symbol is an
assumption about DJI), the bucket edges on `r1`, the centre estimate against
the mapper's 2 MHz match, the `WIDEBAND_SYSTEMS` rows (centres, buckets,
class, `quality`), the 802.11 rows' `duty` 90 split, the mesh line keeping
`cls` / `fc_mhz` / `bw_mhz`, the digital bearing (σ + 5° + 0.2° per missing
duty percent, one K per band), and HDZero's unknown modulation.

**Rules, per kit.**
- *Gate.* A kit that reads `cv2` under 0.5 on `h` with `q_phase` ≥ 40 is
  passing the analog gate and will be reported as an `AF:` carrier marked
  `cw` (the single-carrier case the internals §4 names). That is a design
  item, not a constant: bring the user the `w` features (`r1`, `r4`,
  `step_std` from the bench line) and propose a discriminator (`r1` below
  the FM range, `mod` 0 with a wide `cfo_khz` spread, or a symbol-rate line
  in the lag scan); no edit without that discussion. A kit with `q_phase`
  40–45 and `cv2` about 1 (DJI is expected near 40) is safe: `cv2` fails it
  out of the analog gate; note the margin.
- *Duty.* `duty` under 75 on a real link on most `w` presses: lower
  `WB_DUTY_MIN` to the observed value minus one step of 12.5 (never below
  50), and widen the bench guide and README expectations; the σ term stays.
- *Class, 802.11 (OpenIPC).* `r128` ≥ 0.10 and `scan_lag` 128: the model
  holds; mark the row verified. `r128` between 0.05 and 0.10: lower
  `WB_R128_MIN` to 0.6 × the observed value and `WB_R128_HIGH` to the
  observed value (mirror in the test, see the trap in section 0), re-check
  that FM video's `r128` (0.10–0.12 in the model, measured in stage 1's `w`
  if taken) stays clear of the new minimum; if it does not, the `lte`-first
  rule is no longer a safe guard and the user decides. `scan_lag` not 128:
  the link is not on a 3.2 µs symbol (a 10 MHz half-clocked wfb-ng mode would
  show 256); add that lag to `iq_lag_features` and the class rule only with
  the user, since it changes the report fields.
- *Class, DJI O4.* `r2667` ≥ 0.03 with `r128` under 0.05 and `scan_lag`
  2665–2669: verified; raise the O4 row's `quality` from `med` to `high` in
  `WIDEBAND_SYSTEMS` on both mapper branches (O3 stays `med` unless an O3
  unit is tested), and change "expected, unverified" in both REFERENCE
  tables and the internals. `scan_lag` elsewhere: DJI's symbol is not
  66.7 µs; the peak lag is the new feature (rename `r2667` and
  `WB_R2667_*` to the measured lag, update `iq_lag_features`, the class rule,
  `report.c` field names only if the user agrees to break the mapper's
  `r2667` key, the fixtures and both mappers' normalisation list); this is
  a session's work and goes to the user as a proposal with the data first.
  `r2667` present but under 0.03: lower `WB_R2667_MIN` to 0.6 × observed, the
  `_HIGH` mark to observed, test fallbacks mirrored; check the noise floor of
  the feature from a quiet `w` (0.01 in the model) keeps a 2:1 margin.
- *Bucket.* The reported `bw_mhz` against the kit's set bandwidth: a 20 MHz
  link reading 10 or 30 means `r1` sits outside 0.52–0.78 for that spectrum
  shape. Move the edge that is wrong to the midpoint between the measured
  `r1` of the two neighbouring widths (both places: `wb_classify` and the
  test), and record each kit's `r1` per mode in the internals §4 bucket
  table; the mapper tolerates one bucket step, so the rows need no change
  for a single mis-bucket.
- *Centre.* `fc_mhz` against the kit's centre: within 2 MHz, fine. 2–4 MHz
  off consistently: raise the mapper's `WIDEBAND_MATCH_MHZ` to 4 only after
  checking that 5768.5 (O4), 5769 (HDZero) and 5770 (Walksnail) still
  resolve by class and bucket (the ranking rules in `_wb_match`), and note
  which way the bias runs (a 40 MHz link is cut by the filter and biases
  toward the tuned channel). Larger: the wrap past Nyquist or a lane problem;
  user.
- *HDZero and Walksnail.* Whatever `cls`, bucket and `scan_lag` they read is
  the result: set the row's `cls` to it (`'cls': 'wb'` is allowed, the
  matcher then requires that class), keep `quality` `high` only for a row
  whose class and bucket were both measured, and put the measured features
  into the bench guide's "expected" rows for the next bench. If HDZero reads
  as an analog `cw` carrier, see the gate rule above.
- *Mapper label.* `system` / `system_conf` as the mapper printed them go into
  the record. A wrong label with correct firmware fields is a table problem:
  centres (the kit's real channel plan), buckets, class or ranking; fix in
  both mapper branches, run the parity check, update both REFERENCE tables
  and the standalone `test_mesh_direct.py` expectation, and the
  `level1_bearing_sim.py` fixture features on both branches to measured DJI
  values when O4 is done.
- *Wi-Fi split.* Combine with stage 3: the loaded AP's `duty` and the OpenIPC
  link's `duty` set `duty_min` of the "802.11 video link" row and `duty_max`
  of "Wi-Fi traffic" to the midpoint; if they overlap, the split needs a
  second feature (`r128` at `conf` high, or the 5 MHz grid alone) and the
  user decides.
- *Bearing.* Digital K within 20 % of the analog K: fine, note. Further off:
  the one-K-per-band assumption is wrong for noise-like levels; bring the two
  numbers to the user (a per-type K is a small change in `report_wideband`
  plus a `BandCal` field). σ from the residuals: `WB_SIGMA_EXTRA_DEG` so that
  the analog base plus it covers the digital RMS error; the 0.2°-per-percent
  duty term is checked against the low-duty kits (DJI at range).
- *Mesh.* The `wideband` mesh line with the real node id must still carry
  `cls` and `fc_mhz`; if a long node id cuts them, the order in
  `report_wideband_json` is the knob and `test_wideband_report` the proof.
- *2.4 GHz block.* The same rules on the `_24` constants; a 2.4 GHz kit that
  cannot be heard at all while G3 passed stage 1 is a bandwidth or filter
  question for the user.

**Status:** not started for every kit (OpenIPC, HDZero, DJI O4, Walksnail;
2.4 GHz block).

### After all stages

- The status strings (section 3) say what was measured, on which board,
  when; the *(model)* markers that remain are listed in the internals §10 as
  still open.
- The bench guide's "expected" rows for stage 8 carry measured values, so
  the next station's bench is a comparison, not an experiment.
- A short "Measured on hardware" section at the top of the internals doc
  replaces the "Nothing here has run on hardware" note.

---

## 3. Mechanics

**Status strings.** The bench guide footer text is repeated on all ten
sheets and once in the cover's status row: edit with one replace over the
file (the string currently ends "nothing bench validated"); keep it short,
the footer is 9 px on one line. The cover callout "nothing in this station
has run on hardware yet" and `level1-c5phy/README.md`'s "Nothing in this
directory has run on hardware" change at stage 0; the internals intro note
at the first measured constant.

**Rendering the bench guide.** After editing the HTML:

```
node docs/tools/bench-guide-measure.js docs/Level1-Station-v3-C5PHY-Bench-Guide.html
```

prints the free millimetres on every sheet under print media (needs
Playwright's Chromium; the sheets are fixed A4 boxes with `overflow: hidden`
and the footer pinned, so a negative number means text runs into the
footer). Then

```
chrome --headless --no-sandbox --disable-gpu --print-to-pdf=docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf \
       --no-pdf-header-footer file:///<abs path>/docs/Level1-Station-v3-C5PHY-Bench-Guide.html
```

(in the cloud container `chrome` is
`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, add
`--user-data-dir=<scratch dir>`), and look at the changed pages with
`pdftoppm -f N -l N -r 80 -png`. Sheets 2, 5, 7, 8 and 9 are within a line
of their footers: anything added there needs something removed. Commit the
HTML and the PDF together.

**Mapper changes.** Worktrees from `origin/level2-main` and
`origin/standalone-mapper-meshtastic`, a feature branch each, the same edit
in both `mesh-mapper.py` files, `python3 docs/tools/mapper-parity.py <l2>
<standalone>` must print ALL SAME, `python3 -m py_compile` both, run the
standalone `mapper_test/test_mesh_direct.py`, update both `docs/REFERENCE.md`
(the standalone README's one-line mention if the behaviour changed), push,
open two pull requests with the usual footer; the user merges.

**Commit hygiene.** One commit per data batch where possible, message
naming the stage and the board; this plan's status and log edited in the
same commit; `level1` pushed directly; CI green before the next batch.

---

## 4. Decisions that go to the user, with the data

Do not make these alone, whatever the numbers say:

- the analog / digital splitter (`ANALOG_CV2_MAX` = `WB_CV2_MIN` 0.5) and
  `Q_MIN` 40 (stages 1, 3, 8);
- the radio ceiling default `C5PHY_MAX_MHZ` 5885 if the synthesizer does not
  pull (stage 2);
- the v2 / v3 verdict and whether the LNA becomes standard (stage 5);
- an I/Q lane swap (stages 1, 3);
- a new or renamed lag feature, a single-carrier class, a per-type bearing
  constant, the Wi-Fi split's second feature (stage 8);
- any constant whose measured value lies inside the margin the docs give
  for a *different* gate (the two gates share `DETECT_LEVEL_DB`; the
  envelope limits meet at 0.5).

Everything else in section 2 is a rule: apply it, verify, push, log.

---

## 5. Log

Append one line per batch: date, board or station, stage, what came in,
what changed (commit), what is still open.

| Date | Board / station | Stage | Data | Edits (commit) | Open |
|---|---|---|---|---|---|
| 2026-10-08 | — | plan written | no hardware yet | `docs/Level1-Bench-Data-Plan.md`, `CLAUDE.md`, `docs/bench/`, `docs/tools/`, `test/model/` | all stages |
| 2026-10-08 | user's Windows bench PC; cloud container | session A (desk) | `pio run` on the PC stopped at the penv dependency step: a VPN's Winsock LSP crashes `uv.exe` (exit 3221225622); after the pin, the PC's PlatformIO Core 6.1.19 refused the platform (`IncompatiblePlatform`, needs 6.2.0): `pio upgrade`. In the container, on the pinned platform: host tests pass, both environments and the strong-symbol build link (RAM 44.8 %, flash 28.8 %), the six PHY calls are global in `esp32c5/ld/libphy.a`, `lmac_stop_hw_txq` and `phy_track_pll_deinit` in `lib/`; libs 5.5.5+sha.b774170ff46, Arduino 3.3.12; sdkconfig: `CONFIG_BT_ENABLED=y`, `CONFIG_ESP_COEX_SW_COEXIST_ENABLE=y`, `CONFIG_ESP_PHY_CALIBRATION_MODE=0`, no `CONFIG_PM_ENABLE` | platform pinned to pioarduino 55.03.312-1; README troubleshooting rows; run-order session A step 3 path; this note | the user's own build after the `uv.exe` mitigation, then stage 0 |
