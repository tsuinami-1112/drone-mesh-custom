# Drone Sentinel — `level1` branch

This branch is the level 1 station v3: the XIAO ESP32-C5 firmware in
`level1-c5phy/`, its documents in `docs/`, and the root `README.md`. The
mapper and the home node live on `level2-main`; the mapper alone on
`standalone-mapper-meshtastic`. Those two branches take changes only through
a feature branch and a pull request; `level1` is pushed directly. The mixed
level 1 + 2 station branch is retired for now.

## The bench campaign

Nothing in this branch has run on hardware yet. When the user says they are
starting or continuing the bench tests, in any wording ("I'm going ahead with
the bench tests now", "here's the stage 5 record", "the board printed this"),
read `docs/Level1-Bench-Data-Plan.md` in full before anything else. It maps
every stage of the bench guide to the constants, code, documents, mapper rows
and tests that rest on it, gives the decision rule for each outcome, names the
decisions that go back to the user, and holds the log. Work its section 1 loop
for every batch of data:

1. the raw data goes into `docs/bench/` first (its README gives the format);
2. decide with the stage's rules; the plan's section 4 lists what is never
   decided alone;
3. edit the constant and every place it is quoted (the plan's table in
   section 0), replacing a *(model)* figure with the measurement, not deleting it;
4. verify: `make -C level1-c5phy/test/host`, then
   `pio run -e seeed_xiao_esp32c5` and `pio run -e seeed_xiao_esp32c5_dualband`
   from `level1-c5phy/`; a changed bench-guide HTML is re-rendered to its PDF
   and checked with `docs/tools/bench-guide-measure.js`; a changed mapper is
   checked with `docs/tools/mapper-parity.py` across both mapper branches;
5. update the status strings and the plan's status lines and log in the same
   commit; push `level1`; open pull requests for mapper branches.

## House rules

- Every tunable is in `level1-c5phy/include/config.h`; station-specific
  values go to that station's `stations.ini` (gitignored) via the Station
  setup options, never into the defaults.
- `docs/Level1-Detection-Internals.md` is the reasoning behind every
  threshold; keep it true when a number moves. The bench guide HTML and PDF
  are committed together.
- Commits name the bench stage or the finding that drove them. Nothing is
  pushed with the host tests or either build red.
