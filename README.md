<p align="center">
  <img src="docs/img/claude-level1.svg" width="420" alt="A small friendly orange sunburst character holding a 5.8 GHz patch antenna">
</p>

<h1 align="center">drone-mesh-custom · level 1</h1>

<p align="center">
  Detection stations for drones that broadcast nothing detectable but their 5.8&nbsp;GHz analog video link.<br>
  A XIAO ESP32-C5 is the receiver, four patch antennas on an RF switch give a compass bearing,<br>
  and two stations' bearings cross into a position on the mapper.
</p>

<p align="center"><em>This README is a placeholder while the branch takes shape.</em></p>

| Where | What |
|---|---|
| [`level1-c5phy/`](level1-c5phy/) | Station firmware for the Seeed XIAO ESP32-C5 (PlatformIO) and its desktop tests |
| [`docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf`](docs/Level1-Station-v3-C5PHY-Bench-Guide.pdf) | Hardware, wiring, BOM, calibration and the bench procedure, with the optional LNA + filter stage |
| `mesh-mapper.py` | The shared mapper. The version with level 1 bearing support is on [`level2-main`](../../tree/level2-main) |

Level 2 (Remote ID, DJI DroneID, MAVLink, fingerprints) is on [`level2-main`](../../tree/level2-main).
