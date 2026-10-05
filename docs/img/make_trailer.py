#!/usr/bin/env python3
"""Draws trailer.svg, the animated pixel-art header of the README.

    python3 make_trailer.py                       # rewrite trailer.svg next to this script
    python3 make_trailer.py --png /tmp/p.png      # also a PNG of the still frame
    python3 make_trailer.py --variant static      # the same picture with no animation

The picture is a short film that loops: a title card over a city whose rooftops
carry solar-powered detector stations joined by a mesh; a drone arrives, its
broadcast reaches the stations that can hear it, one of them is opened up to show
how a detection becomes a single LoRa packet, the mesh relays the packets home
and the home station drops the duplicates, the mapper puts the drone and its
pilot on the map, and a day goes by in a few seconds.

All the drawing code is in the `trailer/` folder next to this script. Standard
library only, and deterministic: same code, same bytes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trailer.build import main  # noqa: E402

if __name__ == '__main__':
    main()
