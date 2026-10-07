# Level 1 detection internals

How a level 1 station decides, for whoever maintains the code. Every gate,
feature, threshold and report field of `level1-c5phy/`, with the default of
each constant and the reason it has that value. The user-facing guides are the
[station guide](../README.md) (hardware, wiring, setup, bring-up) and the
[firmware README](../level1-c5phy/README.md) (build, pins, the serial
contract, the bench console); the mapper side of the same records, including
the table that names a digital system, is on level2-main's
[REFERENCE.md](https://github.com/tsuinami-1112/drone-sentinel/blob/level2-main/docs/REFERENCE.md).

Code: [`include/config.h`](../level1-c5phy/include/config.h) (every constant),
[`src/main.cpp`](../level1-c5phy/src/main.cpp) (sweep, gates, reports),
[`src/demod.c`](../level1-c5phy/src/demod.c) (metrics, video, lag features),
[`src/bearing.c`](../level1-c5phy/src/bearing.c),
[`src/report.c`](../level1-c5phy/src/report.c),
[`src/fpv_channels.c`](../level1-c5phy/src/fpv_channels.c),
[`src/c5phy_rf.cpp`](../level1-c5phy/src/c5phy_rf.cpp).

> [!NOTE]
> **Nothing here has run on hardware.** Numbers marked *(model)* come from a
> synthetic-signal model of the firmware (3-bit decode, gain loop reproduced,
> `test/host/test_level1.c`). They are the defaults, exposed as constants, to
> be confirmed or corrected on the bench; the bench guide's record sheets are
> where the measured values go.

Contents: [1 The capture](#1-the-capture) ·
[2 Per-window metrics](#2-per-window-metrics) ·
[3 The analog gate](#3-the-analog-gate) ·
[4 The wideband path](#4-the-wideband-path) ·
[5 Pull-in](#5-pull-in) ·
[6 The channel plan](#6-the-channel-plan) ·
[7 Dual band](#7-dual-band) ·
[8 The antenna model](#8-the-antenna-model) ·
[9 Reports and keys](#9-reports-and-keys) ·
[10 Testing](#10-testing) ·
[11 Parked for later](#11-parked-for-later)

---

## 1. The capture

`iq_capture.cpp` reads the modem's MODEM_DIAG lanes with PARLIO RX at
`IQ_SAMPLE_RATE_HZ` 40 MS/s (every second 80 MS/s modem sample) into one
`IQ_WINDOW_BYTES` 16 KiB DMA buffer: 16 384 samples, **409.6 µs** (the boot
line's `window_us` 409). One byte per sample, I in the high nibble, Q in the
low nibble, each a 4-bit two's complement value: bits 9..6 of the modem's
10-bit sample. Each window is an ordinary one-shot transaction with a 20 ms
timeout; a failed one counts in `cap_err` and the window is skipped. Unlike
C5VRX the station never needs a gapless stream: it looks at a window when it
is done.

With `IQ_LANE_BITS` 3 (the default: six top-side pads) only bits 9..7 are
wired. `demod_init_bits` builds the decode table so that each nibble reads as
the midpoint of the two codes that share its top three bits (-7, -5, ..., 7);
the scale and every threshold stay those of the 4-lane decode (-8..7). The
clip test fires one code early (|x| ≥ 6 instead of 7, about 1.3 dB), which
costs nothing with 3 dB gain steps. The noise floor at `GAIN_MAX` 62 is
`RF_NOISE_POWER` 2.0, mean I²+Q² (C5VRX's 4-lane measurement); the 3-lane
decode never returns 0, so it reads a little higher there, and the bench
measures it in the lane mode that is built (stage 1). An all-zero stuck bus
also reads exactly 2.0 in 3-lane mode, so the `stuck` flag (every sample
identical on the wired lanes) is what to trust, not `p_mean`.

Phase steps between consecutive samples come from a 64 KiB lookup table
(byte pair → int8, 256 units per turn), built once at boot; that is what makes
a 16 K-sample window affordable on a core with a single-precision FPU.

What one 409.6 µs window can and cannot see:

| Signal | In one window | Consequence |
|---|---|---|
| PAL / NTSC video, 64 / 63.56 µs lines | 6.4 lines | enough for the line-period search (≥ 3 sync-shaped pulses, ≥ 2 consecutive periods), never a field (20 / 16.7 ms): `field_hz` is the standard's nominal 50 / 60 |
| LTE-like OFDM, 66.7 µs symbol + 4.69 µs cyclic prefix | 5.7 symbols | the lag-2667 correlation averages over about five symbol pairs: a weak feature (~0.05) per window, hence the 8-window confirmation pass |
| 802.11 OFDM, 3.2 + 0.8 µs | 102 symbols | lag 128 averages well: ~0.18 per window, a clear peak even on one window |
| a Wi-Fi burst, hundreds of µs to a few ms | fills or misses a window | the sweep takes three windows per sector (~1.5 ms) and keeps the minimum level, so a burst raises one window and not the hit; across a burst edge `cv2` reads 1.6-2.7 |
| an FM carrier 10 MHz off the tuned frequency | 90° per sample | never coherent: the coherence gate is the selectivity |

Cost on the C5: `iq_metrics` about 2 ms per window (one pass of integer
sums), one lag autocorrelation about 1 ms (one pass of 16 K LUT decodes and
MACs), so `iq_lag_features` (lags 1, 4, 128, 512 and 2665..2669: nine passes)
plus the metrics is about 10 ms per window. The bench lag scan
(`iq_lag_scan`, 40..3200, step 1 below 400 and 2 above) is about 1760 passes,
two seconds, and only runs from the console.

---

## 2. Per-window metrics

`iq_metrics` (demod.c) fills `IqMetrics` from one window in a single pass;
`iq_lag_features` fills `IqLagFeatures` and is only run on wideband
candidates.

| Metric | Computed as | Used by |
|---|---|---|
| `p_mean` | mean of I²+Q² over the window (LUT, max 128 per sample) | level |
| `level_db` | `(GAIN_MAX - gain) + 10·log10(p_mean / noise_power)` with `p_mean` floored at 0.05; `noise_power` is the band's `RF_NOISE_POWER` (`level_from`, main.cpp). 0 dB = the noise reference at full gain | every gate; `rssi_dbm` = `RSSI_CAL_DBM_AT_NOISE` + level · `RSSI_CAL_SLOPE` + `RSSI_CAL_OFFSET_DB` - `RF_FRONTEND_GAIN_DB` |
| `q_phase_pct` | percent of consecutive sample pairs whose two powers are both ≥ `Q_POWER_MIN` (8, amplitude 2.8 LSB) and whose phase step is within ±`COH_LIMIT` (32 units = ±45°, i.e. an instantaneous frequency within ±5 MHz of the tuned one) | analog gate (`q_phase`), `mod` |
| `env_cv2` | variance / mean² of the sample power: the normalised envelope variance | analog gate, wideband candidate (`cv2`) |
| `cfo_khz` | `arg(Σ s[k]·conj(s[k-1])) / 2π · 40 MHz`: the mean phase step, which is the spectral centroid of whatever is in the 40 MHz view | pull-in target, `fc_mhz`, `freq_peak` |
| `step_std_deg` | standard deviation of the phase step box-averaged over `BOX` 32 samples (0.8 µs); the averaging takes the phase noise of a carrier down by √32 and leaves a video swing (sync, blanking, picture) alone | `mod` |
| `clip_pct` | share of samples with I or Q at full scale | the gain loop (`CLIP_MAX_PCT` 3 %) |
| `noise` | `env_cv2 > 0.5` | bench line |
| `mod` | `step_std_deg > MOD_STD_DEG` (4°) and `q_phase_pct ≥ MOD_Q_MIN_PCT` (20): a coherent carrier with FM deviation, i.e. video rather than a bare CW (CW ~0.3°, video 8-12°); gated on coherence so noise reads 0 | `"carrier":"fm"` / `"cw"` |
| `stuck` | every sample identical on the wired lanes | `bus_stuck` |
| `r1`, `r4`, `r128`, `r512`, `r2667` | \|R(L)\| / R(0) of the decoded window with the window mean removed; `r2667` = the maximum over lags 2665..2669 (66.7 µs is 2666.7 samples). `r1` is the bandwidth proxy, 128 the 802.11 OFDM symbol (3.2 µs), 512 the 11ax symbol (12.8 µs, reported, used by no rule), 2667 the LTE-like symbol (DJI OcuSync) | class, confidence, bandwidth bucket |

Two details of `lag_ratio` matter when the thresholds are revisited. The window
mean is removed because the 4-lane decode (bits 9..6 of a two's complement
sample, a floor) carries -0.5 LSB per component, which would put n·0.5 / R0,
0.19 on bare noise, into every lag; the 3-lane midpoint decode happens to
cancel it. And R(lag) is summed over the n - lag products the lag leaves and
is **not** rescaled against R(0) over all n: the `WB_R*` thresholds were set
with this normalisation and move if it changes.

Model numbers (synthetic waveforms through the 3-bit decode and the gain
loop, two values = S/N 30 / 12 dB):

| Waveform | `q_phase` | `cv2` | `r1` | `r128` | `r2667` |
|---|---|---|---|---|---|
| FM video | 97 / 65 | 0.02 / 0.15 | 0.96 / 0.87 | 0.12 / 0.10 | 0.01 |
| LTE-like 9 MHz (600 × 15 kHz, Tu 66.67 µs, CP 4.69 µs) | 42 / 40 | 0.98 | 0.85 / 0.80 | 0.01 | 0.056 / 0.053 |
| 802.11-like 20 MHz, saturated | 31 / 30 | 0.98 | 0.67 / 0.64 | 0.185 / 0.180 | 0.01 |
| 802.11-like 20 MHz, 30 % duty (300 µs on / 700 µs off) | 3 / 5 | 2.66 / 1.6 | 0.23 | 0.06 | 0.01 |
| 802.11-like 40 MHz, saturated | 8 / 9 | 0.98 | 0.06 | 0.18 | 0.01 |
| single-carrier QPSK, 10 Msym/s, raised cosine | 55 / 50 | 0.28 / 0.37 | 0.84 / 0.79 | 0.01 | 0.02 |
| noise alone | < 1 | ~0.8 | 0.00 | ≤ 0.01 | ≤ 0.01 |

*(model)* The noise floor of every lag feature is about 0.01. The host tests
print this table from the current generators on every run (`make` in
`test/host`, "S/N 30 dB" and "S/N 12 dB" blocks), so that output, not this
page, is where to read the exact numbers after a change to demod.c. Two rows
are worth remembering: FM video's `r128` is 0.10-0.12, above `WB_R128_MIN`, so
the class rule is only ever applied to channels that already failed the analog
gate (the bench `w` on an FM carrier prints `dot11`); and a fast
single-carrier link reads coherent and constant-envelope (q 50-55, cv2 0.3)
and **passes** the analog gate: it would be reported as `analog_fm` with
`"carrier":"fm"` and `"video":"none"`. That is a known limit, not a bug the
tests hide; the test pins only that its lag features carry no OFDM symbol.

---

## 3. The analog gate

Per channel (`scan_freq`), each sector is measured by `measure_sector`:
select the patch, wait `SWITCH_SETTLE_US` 200 µs, start at `GAIN_MAX` and take
up to `WINDOWS_PER_SECTOR` 3 windows, one when the first sits
`QUIET_MARGIN_DB` 3 dB under the threshold (a quiet channel costs one window
per sector). `level_db` = the **minimum** over the windows (a Wi-Fi burst
raises one window, not all three), `q_phase` and `cv2` = the median, `cfo_khz`
the median too. The strongest sector `b` decides:

```
hit = b.windows > 0
   && b.level_db >= DETECT_LEVEL_DB        (8 dB over the noise reference)
   && b.q_phase  >= Q_MIN                  (40 % FM-coherent)
   && b.cv2      <= ANALOG_CV2_MAX         (0.5: constant envelope)
```

| Part | Constant | Why it exists |
|---|---|---|
| level | `DETECT_LEVEL_DB` 8.0 | 8 dB over the measured floor; the sweep's quietest sector level becomes `nf_dbm`. The threshold in dBm (`threshold_dbm`, -87 with the uncalibrated defaults) follows the calibration |
| coherence | `Q_MIN` 40 | the selectivity. An FM carrier within ±5 MHz steps less than 45° per sample; a neighbour 10 MHz away steps 90° and never counts, even though the 40 MHz analog filter lets it raise the level; OFDM and noise step at random. The margins are thin on purpose: an LTE-like OFDM signal reads q 40-42 *(model)*, right at the gate, which is what the third part is for |
| constant envelope | `ANALOG_CV2_MAX` 0.5 | the analog / digital splitter. FM video reads 0.02 (clean) to 0.3 (S/N 12 dB, picture content); OFDM is Gaussian-like at ~1.0; bursty Wi-Fi 1.6-2.7 *(model)*. 0.5 sits between them with a margin both ways |

**The gain loop.** `measure_window` steps the gain down by `GAIN_STEP` while
`clip_pct` > `CLIP_MAX_PCT` (3 %) and retakes, down to `GAIN_MIN` 2; the level
adds `GAIN_MAX - gain` back, so a strong carrier is measured unclipped at the
same scale. The step size had a notch: a 12 dB step took a clipping carrier
(amplitude 7) down to 1.75 LSB, under `Q_POWER_MIN` (power 8, amplitude 2.8),
so its coherence collapsed and the hit was lost; 6 dB left it at 3.5 LSB but
still dropped a carrier just above threshold (a 1 dB notch at S/N 10 dB in the
model, one 6 dB step putting it under the coherence power gate). `GAIN_STEP`
**3** closes the notch; raising `CLIP_MAX_PCT` to 10 % would have too, at the
price of more clipping in every measurement. `GAIN_STEP` is in the boot line
(`gain_step`) so a log says which firmware made a report.

**After the sweep.** Analog hits are sorted strongest first. `PEAK_PICK`
(within `PEAK_PICK_MHZ` 20) folds the same carrier seen on overlapping channels
(R3 5732 / B1 5733 / F1 5740) into the strongest. `ALIAS_GUARD` drops a hit
above the last public 5 GHz centre (5885) whose level is within 2 dB of a hit
within 5 MHz of that centre: what a synthesizer that did not follow
`phy_set_freq` would show, a mirror of the carrier the parked receiver sees;
`alias_drop` counts them, bench stage 2 settles whether the pull works and
`-DC5PHY_MAX_MHZ=5885` removes the channels if it does not. The guard skips
2.4 GHz hits, which all sit under that centre. The strongest
`VIDEO_MAX_PER_SWEEP` 2 hits get the video check (`VIDEO_WINDOWS` 8,
`VIDEO_WINDOW_GAP_MS` 5, `VIDEO_MIN_WINDOWS` 3 windows with a PAL / NTSC line
structure for a verdict); every hit is reported, with the bearing from the
four sector levels (section 8).

---

## 4. The wideband path

A digital video link is the opposite of an FM carrier: wide, noise-like,
continuous. The path has three stages: a candidate rule in the sweep, a fold
across table channels, and a confirmation pass on the strongest survivors
that also takes the bearing.

**Candidate** (`scan_freq`, strongest sector, only when the channel is not an
analog hit):

```
wb = WIDEBAND
  && b.windows == WINDOWS_PER_SECTOR                 (all three windows were taken: the first was above threshold - 3 dB)
  && b.level_min >= DETECT_LEVEL_DB                  (every window above threshold ...)
  && b.level_max - b.level_min <= WB_LEVEL_SPREAD_DB (... within 6 dB of each other: continuous over ~1.5 ms)
  && b.cv2 >= WB_CV2_MIN && b.cv2 <= WB_CV2_MAX      (0.5..1.5: noise-like, but not bursty)
```

**Fold** (`run_sweep`): candidates sorted strongest first; a candidate within
`WB_FOLD_MHZ` 25 of a stronger one is the same emitter (a 10-40 MHz link shows
on every table channel it overlaps, and the table's points are 1-20 MHz
apart), and `span_mhz` keeps the footprint (max - min MHz of the channels
folded together, 0 when alone). A candidate within `PEAK_PICK_MHZ` of an
analog hit is dropped: the analog hit owns that carrier and its sidebands are
not a second emitter. At most `WB_MAX_PER_SWEEP` 2 survivors get a
confirmation pass per sweep.

**Confirmation pass** (`wideband_check`): tune the channel, the strongest
sector, the gain the sweep measured; `WB_WINDOWS` 8 windows `WB_WINDOW_GAP_MS`
5 ms apart, each through `iq_metrics` and `iq_lag_features`. A window is "on"
when its level is within `WB_DUTY_DB` 6 dB of the loudest window; `duty` is
the on windows as a percent of the windows captured. Level, `cv2`, `q_phase`,
the centroid and the five lag features are averaged over the on windows only,
so a TDD link that is off for part of the pass is measured on its on time;
`fc_mhz` = channel + mean centroid / 1000.

**Class** (`wb_classify`), tested in this order:

| Class | Rule | Model value of the deciding feature | Margin |
|---|---|---|---|
| `lte` | `r2667 ≥ WB_R2667_MIN` (0.03) and `r128 < WB_R128_LTE_MAX` (0.05) | 0.053-0.056 | 1.8× over the minimum. The cyclic-prefix share caps it: 4.69 / 71.4 µs = 0.066, so "twice the minimum" was never reachable |
| `dot11` | `r128 ≥ WB_R128_MIN` (0.10) | 0.17-0.19 | 1.8×; the cap is 0.8 / 4.0 µs = 0.20 |
| `wb` | neither | single-carrier links, bursty traffic, anything unknown | |

`lte` is tested first with the `r128 < 0.05` clause so that an 802.11 signal
with a chance correlation at lag 2667 cannot read as `lte` (its `r128` is far
above 0.05), while an LTE-like signal's `r128` is ~0.01 anyway. `r512` is
reported for the day an 11ax-based link needs its own class; no rule uses it.

**Confidence** (`conf`): `high` when the class is named, `duty ≥ 90` and the
deciding feature is at or above its high mark (`WB_R128_HIGH` 0.15,
`WB_R2667_HIGH` 0.04); `med` when the class is named and `duty ≥ WB_DUTY_MIN`;
`low` for `wb`. The high marks are where the model puts a clean link
(0.17-0.19 and 0.043-0.058), not twice the minimum, for the cap reason above.

**Bandwidth bucket** (`bw_mhz`): from `r1`, the one-sample autocorrelation,
which falls with bandwidth (model: LTE-like 9 MHz 0.85, 802.11 20 MHz 0.67,
40 MHz 0.06). Noise decorrelates at lag 1, so the raw `r1` reads S/(S+N) times
the waveform's own value (0.80 at S/N 12 dB for the LTE-like signal, under the
0.78 edge); the bucket is therefore taken on `r1 · (1 + 10^(-level_db/10))`,
capped at 1, while the reported `r1` stays the raw feature:

| Scaled `r1` | `bw_mhz` | Expected there |
|---|---|---|
| ≥ 0.78 | 10 | DJI 10 MHz modes, OcuSync 2 |
| ≥ 0.52 | 20 | DJI 20 MHz modes, Walksnail, 802.11 20 MHz, HDZero's 17 MHz narrow mode |
| ≥ 0.30 | 30 | HDZero's 27 MHz mode (expected from the model's curve, not measured) |
| below | 40 | DJI 40 MHz modes, 802.11 40 MHz |

**Bearing** (`report_wideband`): a report needs `duty ≥ WB_DUTY_MIN` (75);
then one window per sector in the order **N E S W W S E N** at the pass's
gain, keeping the maximum per sector. Interleaving samples every sector twice,
four windows apart, so a bursty link that changes between sectors cannot
masquerade as a bearing; the maximum rather than the mean is what a link with
a duty under 100 % leaves to compare. A sector whose capture failed is set to
the sweep's noise floor and masked (`bearing_estimate_masked`: no neighbour
comparison, a wide sigma). The bearing uses the band's K (section 8) and a
sigma base of `sigma_base + WB_SIGMA_EXTRA_DEG` (10 + 5 at 72° beamwidth: the
levels of a noise-like signal at ~3 LSB rms are coarser than a carrier's), and
`(100 - duty) · 0.2°` is added afterwards. `s_wb_seen` counts the reports
(`wb_seen` in the heartbeat and status line).

| Constant | Default | Why |
|---|---|---|
| `WIDEBAND` | 1 | 0 compiles the path out (the bench `w` stays) |
| `WB_CV2_MIN` / `WB_CV2_MAX` | 0.5 / 1.5 | the candidate's envelope window: above the analog splitter, under bursty Wi-Fi (1.6-2.7, *model*) |
| `WB_LEVEL_SPREAD_DB` | 6.0 | the three sweep windows must agree within this: continuous over ~1.5 ms |
| `WB_WINDOWS` / `WB_WINDOW_GAP_MS` | 8 / 5 | the same shape as the video check; 8 windows average the weak lag-2667 feature and resolve `duty` to 12.5 % |
| `WB_DUTY_DB` | 6.0 | a window "on" within this of the loudest |
| `WB_DUTY_MIN` | 75 | 6 of 8 windows on for a report: a continuous or near-continuous link, not traffic |
| `WB_R128_MIN`, `WB_R2667_MIN`, `WB_R128_LTE_MAX` | 0.10, 0.03, 0.05 | class rule, see above |
| `WB_R128_HIGH`, `WB_R2667_HIGH` | 0.15, 0.04 | `conf` high, see above |
| `WB_MAX_PER_SWEEP` | 2 | confirmation passes per sweep (about 150 ms each) |
| `WB_FOLD_MHZ` | 25 | candidates this close are one emitter; wider than `PEAK_PICK_MHZ` because the links are |
| `WB_SIGMA_EXTRA_DEG` | 5.0 | added to the bearing sigma base |
| `USB_JSON_MAX` | 768 | was 640: the wideband USB record is ~600 bytes |

**Mesh line.** Keyed and paced like analog (`s_last_mesh_report[]` by table
channel, `MESH_REPORT_INTERVAL_MS` 8 s, the first report of a new emitter at
once, a four-deep queue drained `MESH_LINE_GAP_MS` 350 ms apart). Within
`MESH_JSON_MAX` 191 bytes `report_wideband_json` writes `type`, `mac`,
`node_id`, `freq_mhz` (or returns 0), then `rssi`, `bearing_deg`,
`bearing_sigma_deg`, `cls`, `fc_mhz`, `bw_mhz`, `duty`, `conf`, `fp`,
`sector`, `seq`, each only if it still fits (a shorter later field can go in
after a longer one was dropped). Identity and bearing first because a fix
needs them; then what names the system; `band` and `ch` are not sent at all,
the mapper has them from the key. With a 4-character node id the line holds
everything through `duty` plus `sector`; with a 22-character one, through
`bw_mhz`.

---

## 5. Pull-in

A strong constant-envelope carrier between two table channels fails the
coherence gate on both neighbours (a 10 MHz offset steps 90° per sample) while
its centroid sits in `cfo_khz`. `pullin_target` (under `PULLIN`) asks for a
retune when the strongest sector of a channel that is not a hit has
`level_db ≥ DETECT_LEVEL_DB`, `q_phase < Q_MIN`, `cv2 ≤ ANALOG_CV2_MAX` and
`|cfo_khz| ≥ PULLIN_MIN_KHZ` (3000: anything closer is on the channel, and
the centroid of a carrier inside the coherence window is already its
`freq_peak`), and the target `freq + round(cfo / 1000)` lies inside the band's
tuning window. After the analog reports of the sweep, the targets are tried
strongest first, at most `PULLIN_MAX_PER_SWEEP` 2, skipping a target within
`PEAK_PICK_MHZ` of an analog hit (which owns it) or of an earlier attempt this
sweep (both neighbours see the same carrier). Each attempt counts in
`s_pullin` (`pullin` in the heartbeat), then `scan_freq(target)` measures the
four sectors exactly as a table channel. A hit there is reported by
`report_hit` keyed to the nearest table channel (`fpv_nearest`), with
`cfo_khz` and `freq_peak` relative to that channel, so the tracking key stays
a table channel and the carrier's real frequency is still in the record.

The gap points X1 5675 and X2 5715 fill the two 20 MHz holes of the analog
table (between E3 5665 / E2 5685 and E1 5705 / A8 5725): a carrier there is a
table channel with a key of its own rather than a pull-in keyed to a
neighbour.

---

## 6. The channel plan

`fpv_channels.c` holds one table; `build_plan` keeps every entry inside its
band's tuning window, in table order. The host build carries the same
variant defaults as `config.h`.

| Band | Channels | Flag | Purpose | Parked on (nearest public centre) |
|---|---|---|---|---|
| **R** | RaceBand 5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917 | always | analog; HDZero's grid is RaceBand, Walksnail's is 1-5 MHz off it | 132, 140, 144, 153, 161, 169, 177, 177 (R8 +32 MHz) |
| **A** | Boscam A 5865 down to 5725 in 20 MHz steps | always | analog; A1-A7 sit exactly on Wi-Fi 173, 169, 165, 161, 157, 153, 149 and need no undocumented call | exact; A8 on 144 |
| **B** | Boscam B 5733 to 5866, 19 MHz steps | always | analog | 149 to 173 |
| **E** | Boscam E 5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945 | always | analog; E5 is the last public centre, E6-E8 are +20 / +40 / +60 MHz past it | 140, 136, 132, 128, 177, 177, 177, 177 |
| **F** | FatShark 5740 to 5880, 20 MHz steps | always | analog | 149 to 177 |
| **X** | 5675, 5715 | `GAP_CHANNELS` 1 | the two holes of the analog table (section 5) | 136, 144 |
| **D** | 5190, 5210, 5230 | `SCAN_5G1` 1 | three 40 MHz views over DJI O4's CE band 5170-5250 | 36, 40, 44 |
| **L** | Lowband 5362, 5399, 5436 (L1-L3), 5473, 5510, 5547, 5584, 5621 (L4-L8), 37 MHz steps | `LOWBAND` 1 = L4-L8, 2 = L1-L8, 0 = none | analog Lowband and the DJI / Walksnail modes down there; L4-L8 are within 27 MHz of Wi-Fi 100-124 | L4 on 100 (-27), L5-L8 on 100/104, 108, 116, 124; L1 on 48 (+122), L2 on 100 (-101), L3 on 100 (-64): only with `C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ` 140, a pull nothing has proven |
| **G** | 2402, 2422, 2442, 2462, 2482 | `DUAL_BAND` 1 | five 20 MHz steps across the 2.4 GHz ISM band: OcuSync 2 (10 MHz channels 2399.5-2459.5), Wi-Fi-based links | 1, 3, 7, 11, 13 (G1 -10, G5 +10 MHz) |

Count: 40 + 2 + 3 + 5 = **50** by default, 55 with `DUAL_BAND`, 53 with
`LOWBAND` 2, 58 with everything; `MAX_CHANNELS` 64 bounds the per-channel
arrays and `run_sweep` clips the plan to it. The order is R A B E F first: the
tests count on it, and so does everything keyed by channel index within one
build.

**The radio window.** The closed PHY is placed on a public centre with
`esp_wifi_set_channel` and `phy_set_freq` then moves the synthesizer to the
exact MHz; the public 5 GHz centres run from 36 (5180) to 177 (5885), with
UNII-1 (36-48), UNII-2C (100-144) and UNII-3 plus the 5.9 GHz extension
(149-177) in the table, and the 2.4 GHz ones from 1 (2412) to 13 (2472).
`C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ` 60 is how far the pull may go (E8 5945 from
5885), so the tuning windows are 5120..`C5PHY_MAX_MHZ` (5945) and 2352..2532
(`C5_5G_MIN_MHZ`, `C5_24G_MIN_MHZ`, `C5_24G_MAX_MHZ`). C5VRX proved tuning up
to 5885; everything above (R8, E6-E8, and with them HDZero R8 5917 and
Walksnail 5914) and everything under 5180 or more than a few MHz off a centre
rests on `phy_set_freq`, which bench stage 2 proves per direction (`h E8`,
`h D1`, `h L4`). `rf_tune` ranks the centres of the target's band by distance
(`fpv_wifi_bootstrap_rank`) and walks down the list when the regulatory table
(`RF_COUNTRY_CC`, "US") refuses one (173 and 177 in some tables), stopping at
the offset limit; a target with no centre within reach is refused as such
(`tune_fail`, "no public centre within C5PHY_MAX_BOOTSTRAP_OFFSET_MHZ"), not
blamed on the table.

**Sweep time** (estimates; nothing has been timed on hardware). Per channel:
`rf_tune` (a channel set and a synthesizer move, a few ms) + `TUNE_SETTLE_MS`
8 ms + four sectors × (0.2 ms switch settle + one 0.41 ms window + ~2 ms of
metrics on a quiet sector; up to three windows and gain-step retakes on a loud
one): some 20 ms quiet, 50 ms busy. At ~50 ms per channel a 50-channel sweep
is about 2.5 s, 55 channels about 2.8 s, and sweeps run back to back. On top,
per sweep: up to 2 video checks (8 × 5.4 ms + a retune, ~55 ms each), up to
2 wideband confirmations (8 × ~15 ms + 8 interleaved sector windows + a retune,
~150 ms each) and up to 2 pull-ins (one channel's worth each): under half a
second more in the worst case. The console is polled between channels
(`service_io`), so a bench command lands within one channel.

---

## 7. Dual band

`-DDUAL_BAND=1` (environment `seeed_xiao_esp32c5_dualband`, which `extends`
the base one) changes four things.

1. **`rf_start`**: `esp_wifi_set_band_mode(WIFI_BAND_MODE_AUTO)` instead of
   `WIFI_BAND_MODE_5G_ONLY`, so `esp_wifi_set_channel` picks the band from the
   channel number; and `bandwidths.ghz_2g = WIFI_BW40` instead of `WIFI_BW20`.
   BW40 is a hardware requirement for the diagnostic-bus I/Q on 5 GHz (C5VRX
   found no BW20 fallback); the firmware asks for it on 2.4 GHz on the same
   grounds, but C5VRX proved the bus on 5 GHz only, so bench stage 1 on a G
   channel is what confirms it. Everything else in the bring-up (promiscuous
   with an empty filter, the five transmit queues hardware-disabled, AGC off,
   gain forced, the modem front end un-gated) is the same, and the receiver
   still parks on 149 (5745) at start.
2. **`rf_tune`** is unchanged in flow; `fpv_wifi_bootstrap_rank` only ranks
   the centres of the target's band, so a 2.4 GHz channel parks on 1-13 and
   never on a 5 GHz centre. `rf_band_ghz()` says which band the synthesizer is
   on (5 until the first tune, the parked band); the status line shows it as
   `band`.
3. **Per-band calibration.** `struct BandCal { noise_power, cal_dbm_at_noise,
   slope, offset_db, fe_gain_db, antenna_dbi, beamwidth_deg, bearing_k,
   sigma_base }`, filled once in `setup()` by `band_cal_init`: `s_cal[0]` from
   `RF_NOISE_POWER`, `RSSI_CAL_*`, `RF_FRONTEND_GAIN_DB` and the antenna
   constants, `s_cal[1]` from `RF_NOISE_POWER_24`,
   `RSSI_CAL_DBM_AT_NOISE_24`, `RSSI_CAL_SLOPE_24`, `RSSI_CAL_OFFSET_DB_24`,
   `RF_FRONTEND_GAIN_DB_24` and the `*_24` antenna constants. The modem's
   floor and the LNA, if any, differ per band, so each band is calibrated on
   the bench on its own (the `_24` defaults equal the 5.8 GHz ones:
   uncalibrated). `band_idx(freq)` is 1 only when `DUAL_BAND` and the
   frequency is under 3000 MHz; `level_from`, `dbm_from_level`,
   `threshold_dbm` and the bearing take the band's `BandCal`. The noise floor
   is tracked per band (`s_nf_level_min[2]`): `nf_dbm` stays the 5 GHz one
   everywhere, `nf_dbm_24` goes into the USB heartbeat only (the mesh line has
   no room for a second floor), and `threshold_dbm` in the boot line and
   heartbeat is the 5 GHz one. Without `DUAL_BAND`, `s_cal[1]` is a copy of
   `s_cal[0]` and is never selected.
4. **Reports.** The key derivation is the same (`DF:00:47:03:09:8A` for G3);
   `basic_id` gets the `2.4G` prefix from `fpv_band_prefix` (all of 5 GHz,
   D1-D3 included, keeps `5.8G` so the existing strings and fixtures hold);
   the alias guard skips 2.4 GHz hits; `"bands":"2.4+5.8"` in the boot line
   and heartbeat. Station setup writes `extends = env:seeed_xiao_esp32c5_dualband`
   for a station with dual-band patches and the `custom_*_24` antenna options;
   `station.py` warns and ignores `_24` options on a single-band environment.

**Why 2.4 GHz is clutter.** The band is 80 MHz of overlapping Wi-Fi channels
plus Bluetooth; every one of the five 40 MHz views sees access-point traffic.
That traffic is bursty: `cv2` 1.6-2.7 across burst edges and a level spread
over the three sweep windows, so it fails the candidate rule, and a channel
that does pass the rule and then shows `duty` under 75 in the pass is not
reported. What is reported is a saturated 802.11 link (`dot11`, `duty ≥ 90`:
a video link over Wi-Fi, or a busy backhaul) and the OcuSync 2 channels
(`lte`, 10 MHz); the mapper labels `dot11` with `duty < 90` as Wi-Fi traffic
and ranks it low. Expect more wideband reports from a dual-band station, each
with a bearing that is only meaningful if the patches are dual-band: with
5.8 GHz patches the 2.4 GHz pattern is whatever the element happens to do
there, and the 5.8 GHz band-pass filter, if fitted, blinds the band
altogether, which is why the variant is tied to the antennas and not offered
as a flag on the base build. The five extra channels cost about 0.25 s per
sweep.

---

## 8. The antenna model

The patches' gain is entered per station (Station setup, `custom_antenna_dbi`
→ `ANTENNA_GAIN_DBI`) and everything the bearing needs is derived from it in
`band_cal_init`, unless overridden:

| Step | Formula | Constant | Default |
|---|---|---|---|
| gain → beamwidth | `bw = sqrt(32400 / 10^(dBi/10))` degrees: the 32 400 / G rule for a symmetric lobe | `ANTENNA_BEAMWIDTH_DEG` (0 = derive) | 8 dBi → 72° |
| beamwidth → K | `K = BEARING_K_SCALE · bw² / 4320` degrees of bearing per dB of neighbour-sector difference | `BEARING_K_DEG_PER_DB` (0 = derive), `BEARING_K_SCALE` 2.5 | 72° → 3.0 °/dB |
| beamwidth → sigma base | `sigma_base = BEARING_SIGMA_BASE_DEG · bw / 72` | `BEARING_SIGMA_BASE_DEG` 10 | 72° → 10° |
| 2.4 GHz side (dual-band) | the same three, from `ANTENNA_GAIN_DBI_24`, `ANTENNA_BEAMWIDTH_DEG_24`, `BEARING_K_DEG_PER_DB_24` | | 6 dBi → 90°, 4.7 °/dB, 12.5° |

Where the 4320 comes from: a Gaussian main lobe is `G(φ) = -12 (φ / bw)²` dB.
For four sectors 90° apart, a source at φ past the axis of the strongest
sector sees its clockwise neighbour at 90 - φ and the other at 90 + φ, and the
difference of the two neighbour levels is `12 · [(90 + φ)² - (90 - φ)²] / bw²
= 4320 φ / bw²` dB, so φ = bw² / 4320 degrees per dB. Real patches are
gentler than a Gaussian 45-135° off axis (the side of the lobe the neighbours
look through), so the measured K is larger than the Gaussian one by a factor
that belongs to the antenna family, not the station: `BEARING_K_SCALE`, 2.5,
reproduces the 3.0 °/dB of the stage 6 default at 72° and is anchored once per
antenna family.

| Gain | Beamwidth | K (scale 2.5) | sigma base |
|---|---|---|---|
| 6 dBi | 90° | 4.7 °/dB | 12.5° |
| 8 dBi | 72° | 3.0 °/dB | 10.0° |
| 9.5 dBi | 60° | 2.1 °/dB | 8.3° |
| 12 dBi | 45° | 1.2 °/dB | 6.3° |

`bearing.c` then does what it always did: `bearing = az[k] + K · (P[k+1] -
P[k-1])`, clamped to ±`BEARING_MAX_OFFSET_DEG` 45 from the strongest sector's
axis; `sigma = sqrt(sigma_base² + (K · noise_db · √2)²)` with `noise_db` 1 dB
at 10 dB or more over the threshold and 3 dB at it, plus 8° when a neighbour
is within 3 dB of the strongest sector (the sector itself is ambiguous), or
plus 22.5° when a neighbour is masked (no comparison at all). A wider lobe
gives a shallower slope and a noisier bearing, which is what the sigma base
scaling says.

**The boundary holes.** Under about 60° of beamwidth (above ~9.5 dBi) a
source 45° off two axes is more than 6.75 dB down on both, the neighbour
difference saturates and the clamp decides; `station.py` warns at build time
when the derived or entered beamwidth of either band is under 60°
(`BEAMWIDTH_MIN_DEG`). Four sectors want 60-90° patches.

**What stage 6 anchors.** A VTX at 30 m, the box rotated in 15° steps, the
reported `sectors` recorded: the slope of `P[k+1] - P[k-1]` against the true
angle is K. Enter it as `custom_bearing_k` for that station, or, better, set
`BEARING_K_SCALE = K_measured / (bw² / 4320)` for the antenna family in
`platformio.ini`, after which every station flashed with that family's gain
derives the right K. The gain does not enter the dBm calibration: `RSSI_CAL_*`
map `level_db` to the power at the U.FL, and a higher-gain patch delivering
more power for the same field is exactly what stage 5 measures. The boot line
and the USB heartbeat carry `antenna_dbi`, `beamwidth_deg` and `bearing_k` (the
5.8 GHz side) so a log shows which model made a bearing.

---

## 9. Reports and keys

`report_mac` and `report_wb_mac` build the tracking key from the table
channel: `AF:00:bb:cc:hh:ll` for an analog carrier, `DF:00:bb:cc:hh:ll` for a
digital link, with `bb` the band letter's ASCII code, `cc` the channel number
and `hh:ll` the MHz as two bytes (`'R'` = `52`, 4 = `04`, 5769 = `16:89`:
`DF:00:52:04:16:89`; G3 2442 = `DF:00:47:03:09:8A`). The key is a table
channel and not a frequency estimate because two stations that hear the same
emitter must say the same thing for the mapper to intersect their bearings,
and a table channel is the same on every station while `fc_mhz` differs by
each station's centroid error. A pull-in is keyed to the nearest table channel
for the same reason, with the real frequency in `freq_peak`.

A digital link is wider than the grid, so two stations can still fold it to
different table channels (the strongest sector of each decides which point
wins its fold). The mapper therefore merges a wideband report onto the live
wideband track whose `fc_mhz` is within `max(bw, bw') / 2 + 5 MHz` of its
own, never across types; analog reports merge within 10 MHz among analog
tracks (the R3 / B1 / F1 cluster spans 8 MHz). From `fc_mhz`, `bw_mhz`, `cls`
and `duty` it names the system (`system`, `system_conf`) against its
`WIDEBAND_SYSTEMS` table: DJI O4 and O3 by their centres and buckets (`lte`
expected, unverified), OcuSync 2, Walksnail / DJI FPV V1, HDZero, an 802.11
video link (`dot11` on the 5 MHz Wi-Fi grid with `duty ≥ 90`), Wi-Fi traffic
(`dot11`, `duty < 90`), else unknown digital; `system_conf` never exceeds the
station's `conf`. The table and its matching rules are documented on
[level2-main's REFERENCE.md](https://github.com/tsuinami-1112/drone-sentinel/blob/level2-main/docs/REFERENCE.md)
and live in `mesh-mapper.py`, so a new system is a row there, not a firmware
change. `fp` (`cls/bw/fc`, or `NTSC/15736/5734` for video) and `basic_id`
(`5.8G-R4-5769MHz`, `2.4G-G3-2442MHz`) are the human-readable forms the mapper
shows and exports.

Two stations agree on a fix when their rays, each rotated by its station's
heading, cross at more than 8° within 30 s; a fix needs at least two placed
stations. The station never reports a position.

---

## 10. Testing

**Host tests** (`test/host`, `make`; gcc, the plain-C files only: demod.c,
bearing.c, report.c, fpv_channels.c, switch_bits.c). The suite is built and
run twice, with the default plan and with `-DDUAL_BAND=1 -DLOWBAND=2`, and
within each run the signal tests run twice, with four and with three lanes per
component (the 3-lane run puts random bits on the unwired lanes to prove the
masking). `check_json.py` then checks every `JSON_USB` / `JSON_MESH` line:
it parses, carries the keys the mapper keys on, the mesh lines are ≤ 191
bytes, every record kind appears under both tags, and the run ended in
`ALL TESTS PASSED`. What it proves:

| Area | Proven on the desktop |
|---|---|
| decode | the phase-step LUT (90° per sample reads +10 MHz), the 4- and 3-lane nibble decodes |
| noise | `p_mean` ≈ 2.7 at σ = 1, the `noise` / `mod` / `stuck` flags, a dead bus reads stuck (and exactly 2.0 in 3-lane mode), no video on noise |
| carriers | a CW is coherent with the right `cfo_khz` and not `mod`, no video; a carrier 10 MHz off is **not** coherent; a strong one clips |
| video | NTSC and PAL at both sync polarities read the right standard and line rate (±15 Hz) with `sync_q ≥ 50`; a weak PAL case is printed, not gated |
| the analog gate and the lag features | at S/N 30 and 12 dB through the gain loop: FM video passes the gate (level, q ≥ 40, cv2 ≤ 0.5) with `r2667` < 0.02; LTE-like, 802.11-like 20 / 40 MHz and bursty 802.11 fail it; LTE-like classes `lte` with `r2667` over the high mark and `r1` in the 10 MHz bucket; 802.11-like 20 and 40 MHz class `dot11` over the high mark in the 20 and 40 MHz buckets; SC QPSK carries no OFDM symbol (`wb`); noise features under 0.03 / 0.02 |
| the lag scan | 128 on the first 802.11-like window (20 and 40 MHz); 2665..2669 on at least 4 of 8 LTE-like windows (the CP peak is about three sigma over the scan's own noise on one window) |
| bearing | the values of four geometries, the boundary and weak-signal sigmas, the ±45° clamp, the masked cases, NULL mask = all valid |
| channel plan | 50 / 58 channels, R A B E F first, X D L after F8, `fpv_find` by name, lower case and MHz, `fpv_nearest`, D1 / X2 / L4, L1 only with `LOWBAND` 2, G3 only with `DUAL_BAND`, the band of a frequency and of a channel, the `basic_id` prefixes, the bootstrap of R3 / A1 / D1 / L4 / G1 / G3, the second-nearest and farthest ranks, out-of-window targets, that ranking never crosses bands (13 and 24 centres), the top centre 5885 |
| switch bits | every accepted and refused form of the `t` argument, formatting round trips |
| analog report | `mac`, `basic_id`, `fp`, `rssi_raw`; the USB record and a mesh record ≤ 191 bytes with a 22-character node id; the tiny-buffer refusal |
| heartbeat | the USB fields in order (`fe_gain_db`, `bands`, `antenna_dbi`, `beamwidth_deg`, `bearing_k`, `wb_seen`, `pullin`, `tune_fail`), `wb_seen` after `video_seen` on the mesh, the position after `heading` on both and surviving a long node id, `nf_dbm_24` after `nf_dbm` on USB only |
| wideband report | `DF:00:52:04:16:89`, `lte/10/5768.5`, `5.8G-R4-5769MHz` and `5.8G-D1-5190MHz`, `2.4G-G3-2442MHz`; the USB field order in three checked runs; the mesh line ≤ 191 bytes keeping class and centre with a long node id; the tiny-buffer refusal; a 2.4 GHz record |
| sensitivity | a printed table of level and coherence against amplitude for both lane modes (informational) |

The synthetic waveforms are continuous-time CP-OFDM with random QPSK per
subcarrier per symbol (LTE-like 600 × 15 kHz, Tu 66.67 µs, CP 4.69 µs;
802.11-like 52 × 312.5 kHz, Tu 3.2 µs, CP 0.8 µs, continuous and 300 µs on /
700 µs off; 40 MHz 802.11-like, subcarriers -58..58 without the two centre
ones), raised-cosine single-carrier QPSK, FM video with a per-line picture at
4 MHz per 100 IRE, and CW, all +0.5 MHz off the tuned frequency, through the
firmware's own gain loop. They are models of the waveform families, not of
any product: no DJI, Walksnail or HDZero capture has been fed to the code.

**What only the bench can prove** (stages in the bench guide):

- that this core's libphy exports the undocumented calls and the diagnostic
  bus delivers I/Q at all (`"rf":true`, `captures` climbing, `stuck` 0): stages
  0 and 1; and the same on a 2.4 GHz channel under BW40 for the dual-band
  build;
- `RF_NOISE_POWER` in the lane mode built, and the dBm calibration
  (`RSSI_CAL_*`, `DETECT_LEVEL_DB`): stages 1 and 5, per band;
- the synthesizer pull: above 5885 (R8, E6-E8, HDZero R8, Walksnail 5914),
  down to D1-D3 and L4-L8, and the 140 MHz pull of L1-L3 (`tune_fail`,
  `alias_drop`): stage 2, with the regulatory table of the deployment country;
- the features of the real systems: DJI O3 / O4 are proprietary OFDM and
  the `lte` class for them is expected, not verified; HDZero's 27 MHz mode in
  the 30 bucket; Walksnail; an OpenIPC / wfb-ng link as `dot11` with
  `duty ≥ 90`; and that a Wi-Fi access point does **not** produce a wideband
  report unless it is saturated: stages 3 and 8;
- the thresholds under real multipath and with real noise (the quantised
  noise `cv2` of the model is ~0.8, the firmware comment says ~1);
- the switch truth table, the sector pattern and K (`BEARING_K_SCALE`),
  and the digital bearing constant from a rotation on a digital link:
  stages 6 and 8;
- the timing: sweep time, the ~10 ms per confirmation window, the 20 ms
  capture timeout, the bench `w` at about 2 s.

**CI** (`.github/workflows/firmware.yml`): on every push to `level1` and
every pull request that touches `level1-c5phy/` (or the workflow), a `host
tests` job runs `make -C level1-c5phy/test/host`, and a `build` matrix compiles
both environments, `seeed_xiao_esp32c5` and `seeed_xiao_esp32c5_dualband`,
with PlatformIO 6.2.0 (pinned) and keeps each merged `firmware.factory.bin` as
a run artifact for 14 days, for a quick bench flash without the per-station
settings. Every action is pinned to a commit SHA; `.github/dependabot.yml`
opens a weekly pull request when one has a new release. Nothing is published:
a deployed station is flashed from source with its own environment.

---

## 11. Parked for later

**A LoRa control-link presence detector.** Every FPV drone has a control link
even when its video is off, dark or on a system this station cannot class:
ExpressLRS at 2.4 GHz or 868 / 915 MHz and TBS Crossfire at 868 / 915 MHz are
LoRa-modulated, frequency-hopping, a few milliseconds per packet at 50-500
packets per second, and the handset transmits whenever it is switched on. That
makes a control link a **pilot presence** signal: it says a pilot with a live
transmitter is within range, before the drone is up and after the video has
gone, and it is the one emission this station's receiver cannot see (the C5's
Wi-Fi PHY does not cover 868 / 915 MHz, and a 2 ms LoRa chirp hopping across
the band is neither the continuous noise-like channel the wideband path looks
for nor the constant coherent carrier the analog gate wants).

The sketch, kept here so it can be picked up with the reasoning intact:

- **Hardware**: a Semtech LoRa transceiver on a level 2 station's spare pins,
  SX1262 for 868 / 915 MHz and SX1281 for 2.4 GHz, each with its own antenna;
  not on the level 1 station, whose radio is the video receiver and whose
  top-side pins are spent.
- **Method**: no demodulation. Channel activity detection (CAD) or RSSI
  sampling, stepped across the ELRS and Crossfire hopping grids of each band;
  a hopping link lights many channels in turn, so a presence verdict is a
  count of active channels per second against a baseline, with the packet
  rate as a hint of the system.
- **Output**: a presence report with a band, a packet rate and a level, keyed
  to the band and the station, with no bearing: a single antenna and a 2 ms
  packet give nothing to compare sectors on. It would ride into the mapper as
  a new type alongside `analog_fm` and `wideband`, shown as "pilot present
  near station X", never as a position.
- **The complication**: the Heltec V4 next to it is a LoRa transmitter on the
  same 868 / 915 MHz band, at up to 28 dBm, a metre away. Its Meshtastic
  packets would saturate an SX1262 scanner and read as presence. The detector
  must be blanked while the Heltec transmits (the Meshtastic serial module
  gives no transmit strobe, so this means either a hardware tap on the V4's
  LoRa antenna path or a timing model of the mesh traffic), or confine itself
  to 2.4 GHz with the SX1281, where the Heltec never transmits but Wi-Fi and
  the station's own Bluetooth do, and ELRS 2.4 GHz is the common FPV choice
  anyway. Which of the two is right is the first thing to settle on the bench.
- **What it is not**: a replacement for the bearing paths. It adds the one
  thing they cannot give, that a pilot is there at all.
