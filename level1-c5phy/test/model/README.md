# Models

Not tests: the synthetic-waveform models that set some of `config.h`'s
numbers, kept so a bench measurement can be compared with the model that
preceded it and the model re-fitted. `make` builds and runs them against the
firmware's own `src/demod.c`.

| File | What it models | Sets |
|---|---|---|
| `sim_skirt.c` | FM video (NTSC-like, 4 MHz per 100 IRE and twice that) at 20, 30 and 40 dB over threshold, 0–35 MHz off the tuned channel, through two 40 MHz channel-filter shapes (soft: −16 dB at 25 MHz; sharp: −40 dB at 22 MHz), 3-lane quantised with the firmware's gain loop, then `iq_metrics` and `iq_lag_features`; prints which offsets pass the wideband candidate rule and what the confirmation pass would class them as | `WB_ANALOG_OWN_MHZ` (30). After bench stage 5's skirt record, change the two `design()` calls to a cutoff and tap count that reproduce the measured levels and re-run |

The docs quote the model's numbers with the word *model*; a measurement
replaces them in the same sentence, keeping the model figure.
