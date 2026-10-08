# Bench records

Raw results from the bench stages of
`docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`, one file per stage and board
or station, written before anything is concluded from them. The plan that
turns them into edits is `docs/Level1-Bench-Data-Plan.md`.

**File name:** `YYYY-MM-DD-<board or station id>-stage<N>.md`, for example
`2026-10-12-bench1-stage5.md` or `2026-11-02-RX01-stage6.md`. A kit block of
stage 8 adds the kit: `-stage8-openipc`. Data that arrives for several stages
at once is split into one file each.

**Contents, in this order:**

1. **Build**: the firmware commit, the environment (`seeed_xiao_esp32c5`,
   `seeed_xiao_esp32c5_dualband` or a station environment), any extra `-D`
   flags, the platform / core version if known.
2. **Chain**: what was between the signal and the U.FL (stock antenna, patch,
   switch, LNA, attenuator setting, cables), the VTX or kit and its setting
   (channel, power, bandwidth, camera standard), distance, anything unusual.
3. **The record sheet's fields**, as a table with the sheet's own labels, blank
   where nothing was measured.
4. **Console lines**, verbatim in a fenced block: the boot line, `?` status
   lines, bench lines (`h`, `v`, `w`), detection or `wideband` lines, error
   lines. Trim repetition, never values.
5. **Observations** in the user's words, and anything that went wrong.

Photos or screenshots are described in words here and kept wherever the user
keeps them; a measured sweep (stage 6, the skirt record) also goes in as a CSV
next to the markdown. Nothing in this directory is ever "cleaned up" after the
fact: a record that turned out wrong gets a note saying so, not an edit.
