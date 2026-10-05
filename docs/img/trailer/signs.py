"""Neon on the towers: the Meshtastic mark in green, and a small blue and yellow
trident for the Ukrainian friends who helped build this."""
from .pixart import *
from .palette import *

MESH_AT, MESH_N = (59, 78), 21           # top-left of the Meshtastic sign, and its side
TRIDENT_AT = (242, 100)                  # top-left of the little trident
TRIDENT = (                              # blue prongs over a yellow base
    ".....B.....",
    "....BBB....",
    "BB..BBB..BB",
    "BBB..B..BBB",
    "B.B..B..B.B",
    "B.B..B..B.B",
    "B.B..B..B.B",
    "B.BB.B.BB.B",
    "B.BB.B.BB.B",
    ".YY.YYY.YY.",
    ".Y.Y.Y.Y.Y.",
    ".Y.YY.YY.Y.",
    ".Y..YYY..Y.",
    ".YYYYYYYYY.",
    "...YYYYY...",
    "...Y.Y.Y...",
    "....YYY....",
    ".....Y.....",
)
BLUE_N, GOLD_N = C('#2f6bff'), C('#ffd23a')


def neon_pulse(period):
    """A neon that breathes: its bloom swells and eases, slowly. It starts at full glow
    (one period in, on the way down) so the still frame agrees with the first frame."""
    add_css('.np{animation:np 1s ease-in-out infinite alternate}')
    add_css(keyframes('np', {0: 'opacity:.72', 100: 'opacity:1'}))
    return 'np', 'animation-duration:%gs;animation-delay:-%gs' % (period, period)


def neon_dip(duration, delay):
    """A bloom that dips whenever its tube stutters."""
    add_css('.nd{animation:nd 1s %s}' % STEP)
    add_css(keyframes('nd', {0: 'opacity:1', 88: 'opacity:.35', 90: 'opacity:1', 92: 'opacity:.35',
                             94: 'opacity:1', 96: 'opacity:.35', 98: 'opacity:1'}))
    return 'nd', 'animation-duration:%gs;animation-delay:-%gs' % (duration, delay)


def sign_bloom(name, tubes, color, bands, breathe, stutter):
    pc, ps = neon_pulse(breathe)
    dc, ds = neon_dip(*stutter)
    return bloom(name, tubes, color, bands, groups=((pc, ps, 'np-' + name), (dc, ds, 'nd-' + name)))


def mesh_strokes(x0, y0):
    """The Meshtastic mark as two polylines: a slash, and a peak."""
    return (((x0 + 4, y0 + 14), (x0 + 8, y0 + 7)),
            ((x0 + 9, y0 + 14), (x0 + 13, y0 + 7), (x0 + 17, y0 + 14)))


def meshtastic_sign():
    """The Meshtastic logo as a green neon sign: its slash and peak lit on a dark plate,
    in a rounded neon frame."""
    L = new_layer('meshtastic')
    x0, y0 = MESH_AT
    n = MESH_N
    plate = C('#06180f')
    rect(L, x0, y0, n, n, plate, True)
    for i in range(2, n - 2):
        for (x, y) in ((x0 + i, y0), (x0 + i, y0 + n - 1), (x0, y0 + i), (x0 + n - 1, y0 + i)):
            L.set(x, y, MESH, True)
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x0 + n - 1, y0, -1, 1), (x0, y0 + n - 1, 1, -1), (x0 + n - 1, y0 + n - 1, -1, -1)):
        top, c = composite_at(LAYERS, cx, cy)
        L.set(cx, cy, mix(plate, c or INK, .5))
        L.set(cx + sx, cy + sy, MESH, True)
    for i in range(2, n - 2):
        for (x, y) in ((x0 + i, y0 + 1), (x0 + i, y0 + n - 2), (x0 + 1, y0 + i), (x0 + n - 2, y0 + i)):
            if L.get(x, y) == plate:
                L.set(x, y, MESH_DIM, True)
    for stroke in mesh_strokes(x0, y0):
        for (p, q) in zip(stroke, stroke[1:]):
            for (x, y) in line_pts(p[0], p[1], q[0], q[1]):
                for dx in (-1, 1):
                    if L.get(x + dx, y) == plate:
                        L.set(x + dx, y, MESH_DIM, True)
        for (p, q) in zip(stroke, stroke[1:]):
            for (x, y) in line_pts(p[0], p[1], q[0], q[1]):
                L.set(x, y, MESH, True)
    for (x, y) in ((x0 + 8, y0 + 7), (x0 + 13, y0 + 7)):
        L.set(x, y, MESH_HOT, True)
    tubes = {p for p, c in L.pix.items() if c in (MESH, MESH_HOT)}
    sign_bloom('mesh', tubes, MESH, ((1.5, .34), (2.5, .22), (3.5, .14), (5, .08), (7.5, .04)), 3.6, (5.3, 1.7))
    return L


def trident_sign(wall_layer_name):
    """A small neon trident on a tower: blue over yellow, a touch of haze on it so it sits
    back in the picture and does not shout."""
    L = new_layer('trident')
    x, y = TRIDENT_AT
    w, h = len(TRIDENT[0]), len(TRIDENT)
    for yy in range(y - 1, y + h + 1):
        for xx in range(x - 1, x + w + 1):
            top, c = composite_at(LAYERS, xx, yy)
            L.set(xx, yy, mix(c or INK, INK, .5))
    for j, row in enumerate(TRIDENT):
        for i, ch in enumerate(row):
            if ch != '.':
                L.set(x + i, y + j, mix(BLUE_N if ch == 'B' else GOLD_N, INK, .1), True)
    for tag, ch, col in (('blue', 'B', BLUE_N), ('gold', 'Y', GOLD_N)):
        pix = {(x + i, y + j) for j, row in enumerate(TRIDENT) for i, c in enumerate(row) if c == ch}
        sign_bloom('tri-' + tag, pix, col, ((1.5, .2), (2.5, .11), (4, .05)), 4.4, (7.3, 2.0))
    return L
