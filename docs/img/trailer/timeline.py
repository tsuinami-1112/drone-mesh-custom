"""When things happen, on the one clock the whole SVG runs on (seconds)."""
from .pixart import T_LOOP

# which shot is on screen
CITY = [(0.0, 9.6), (30.5, T_LOOP)]         # the title, the first detection, the time-lapse, the finale
CUTAWAY = [(9.6, 15.4)]
RELAY = [(15.4, 21.8)]
MAP = [(21.8, 30.5)]

# the title
TITLE_OUT = [(0.0, 2.7), (2.8, 2.86), (2.94, 3.0)]               # on, then flickers away
TITLE_IN = [(37.4, 37.46), (37.54, 37.6), (37.7, T_LOOP)]        # flickers back on at the end

# the drone over the city
DRONE_IN, DRONE_HOVER = 3.4, 4.8
HOVER_AT = (112, 36)
EMIT_FIRST, EMIT_PERIOD, EMITS = 4.9, 1.0, 5
RING_V, RING_MAX = 48.0, 78.0

MAPBASE = [(15.4, 30.5)]                    # the night map under the relay and the mapper

# the day in a day: 24 hours in LAPSE seconds, starting at 03:00
LAPSE = (30.5, 37.2)
HOUR0 = 3
SUNRISE, NOON, SUNSET = 31.35, 33.0, 34.7

# the cuts, each with a few frames of glitch: (time, seed)
CUTS = [(3.0, 11), (9.6, 12), (15.4, 13), (21.8, 14), (30.5, 15), (37.4, 16)]

# the bottom bar: (word, accent, small print, from, to); word None is plain small print
TAGLINE = 'SOLAR \u00b7 MESHTASTIC LORA MESH \u00b7 LIVE MAP \u00b7 OFFLINE \u00b7 24/7'
CAPTIONS = [
    (None, None, TAGLINE, 0.0, 3.0),
    ('DETECT', (95, 243, 255), 'REMOTE ID \u00b7 DJI \u00b7 MAVLINK \u00b7 FINGERPRINTS', 3.2, 9.6),
    ('DETECT', (95, 243, 255), 'BLE + WIFI DECODED \u00b7 1 DETECTION = 1 LORA PACKET', 9.6, 15.4),
    ('RELAY', (154, 160, 255), 'MESHTASTIC LORA \u00b7 MULTI-HOP \u00b7 NO INTERNET', 15.4, 21.8),
    ('MAP', (136, 255, 153), 'LIVE POSITION \u00b7 PILOT \u00b7 PATH \u00b7 OFFLINE MAPS', 21.8, 30.5),
    ('24/7', (103, 234, 148), 'SOLAR \u00b7 UNATTENDED \u00b7 SELF-RECOVERING', 30.5, 37.4),
    (None, None, TAGLINE, 37.4, T_LOOP),
]
