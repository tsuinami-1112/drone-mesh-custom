"""The city at night: sky, moon, stars, planes of towers, and the rooftops the
detector stations stand on. Shared by the title, the first detection and the
24-hour time-lapse."""
import math

from .pixart import *
from .palette import *

# y (canvas rows) -> index into the SKY ramp: deep indigo overhead, a magenta glow low down
SKY_STOPS = [(PIC_Y0, 0.0), (34, 1.7), (58, 3.6), (78, 5.8), (96, 8.0), (114, 9.8), (PIC_Y1, 10.6)]

WINDOWS = {}        # plane name -> [(x, y, w, h, colour)]: every lit window
BEACONS = []        # blinking aircraft lights: (x, y)


def ramp_index(n, u, x, y, soft=.5):
    """Like ramp_at, but returns which step of the ramp the pixel takes."""
    u = max(0.0, min(float(n - 1), u))
    i = int(u)
    if i >= n - 1:
        return n - 1
    f = (u - i - (.5 - soft / 2)) / soft
    f = max(0.0, min(1.0, f))
    return i + 1 if f > bay(x, y) else i


def fog_at(x, y, soft=.4):
    return ramp_at(SKY, piecewise(SKY_STOPS, y), x, y, soft)


def shade(x, y, lift, dark, soft=.22, mist=0.0):
    """A wall's colour: the glow behind it, lifted a little (hazier, farther
    towers) and darkened toward ink for the nearer ones. `mist` lets the
    street-level fog swallow the darkness toward the bottom."""
    u = piecewise(SKY_STOPS, y) + lift
    d = dark * (1.0 - mist * max(0.0, min(1.0, (y - 60) / 60.0)))
    return mix(ramp_at(SKY, u, x, y, soft), INK, d)


# ----------------------------------------------------------------------------
# sky, stars, moon
# ----------------------------------------------------------------------------
def sky():
    """The sky in one layer per step of the ramp, so the time-lapse can
    recolour each step (the sky changes colour as the hours go by)."""
    bands = [new_layer('sky-%d' % k, paint='group') for k in range(len(SKY))]
    for y in range(PIC_Y0, PIC_Y1):
        for x in range(W):
            k = ramp_index(len(SKY), piecewise(SKY_STOPS, y), x, y, .4)
            bands[k].set(x, y, SKY[k])
    # a band that never gets used would have no colour to set: drop the empty ones
    for b in list(bands):
        if not b.pix:
            LAYERS.remove(b)
    return [b for b in bands if b.pix]


STAR_COLORS = [C('#4e397a'), C('#755ea6'), C('#a89ad8'), C('#e6e0ff')]


def stars(count=90, seed=7, y_max=70):
    rng = Rng(seed)
    dim, mid, bright = new_layer('stars-dim'), new_layer('stars-mid'), new_layer('stars-bright')
    for _ in range(count):
        x, y = rng.randint(2, W - 3), rng.randint(PIC_Y0 + 2, y_max)
        r = rng.random()
        if r < .6:
            dim.set(x, y, STAR_COLORS[0], True)
        elif r < .9:
            mid.set(x, y, STAR_COLORS[1], True)
        else:
            bright.set(x, y, STAR_COLORS[3], True)
            for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                bright.set(x + dx, y + dy, STAR_COLORS[1], True)
    return dim, mid, bright


MOON_AT, MOON_R = (206, 66), 12.5


def moon():
    L = new_layer('moon')
    cx, cy = MOON_AT
    disc = blob_pts(cx, cy, MOON_R, MOON_R)
    base, lit, shade_c, crater = C('#dbeeff'), C('#f4fbff'), C('#a9c6e6'), C('#8fb0d6')
    for (x, y) in disc:
        d = math.hypot(x + .5 - cx, y + .5 - cy) / MOON_R
        t = ((x + .5 - cx) * -.55 + (y + .5 - cy) * -.45) / MOON_R      # lit from the upper left
        c = ramp_at([shade_c, base, lit], 1.0 + t * 1.05 - d * d * .5, x, y, .7)
        L.set(x, y, c, True)
    rng = Rng(21)
    for (ox, oy, r) in ((-4, -3, 2.6), (3, 2, 3.2), (-2, 5, 1.8), (5, -5, 1.6), (-7, 1, 1.4), (0, -8, 1.3)):
        for (x, y) in blob_pts(cx + ox, cy + oy, r, r * .85):
            if (x, y) in disc:
                L.set(x, y, mix(L.get(x, y), crater, .55 if (x + y) % 2 else .35), True)
    return disc


def moon_halo(disc):
    bloom('moon', disc, (150, 196, 255), ((2.5, .22), (5, .14), (9, .08), (15, .045), (23, .022)))


# ----------------------------------------------------------------------------
# towers
# ----------------------------------------------------------------------------
def paint_block(L, blk, lift, dark, rim=None, rim_side=1, top_edge=None, soft=.22, mist=0.0, y_end=None):
    x0, x1, top = blk
    y_end = PIC_Y1 - 1 if y_end is None else y_end
    for y in range(max(top, PIC_Y0), y_end + 1):
        for x in range(max(x0, 0), min(x1, W - 1) + 1):
            L.set(x, y, shade(x, y, lift, dark, soft, mist))
    if rim:
        x = x0 if rim_side < 0 else x1
        for y in range(max(top, PIC_Y0), y_end + 1):
            if L.get(x, y) is not None:
                L.set(x, y, mix(L.get(x, y), rim[0], rim[1]))
    if top_edge and top >= PIC_Y0:
        for x in range(max(x0, 0), min(x1, W - 1) + 1):
            if L.get(x, top) is not None:
                L.set(x, top, mix(L.get(x, top), top_edge[0], top_edge[1]))


def lit_windows(wl, plane, blk, cfg, rng, fog, dark=None):
    """Lit windows go to their own layer (they switch off by day); the dark
    ones are drawn into the wall by the caller."""
    x0, x1, top = blk
    ww, wh, px, py = cfg['w'], cfg['h'], cfg['px'], cfg['py']
    pal = rng.choice(WIN_MIXES)
    for gy in range(max(top, PIC_Y0) + 2, PIC_Y1 - wh - 2, py):
        band = rng.random()
        rd = cfg['dens'] * (2.4 if band > .86 else (.3 if band < .38 else 1.0))
        for gx in range(max(x0, 0) + 1 + (blk[0] % 2), min(x1, W - 1) - ww + 1, px):
            if dark is not None:
                rect(dark, gx, gy, ww, wh, mix(dark.get(gx, gy) or INK, C('#3a2860'), .5))
            if rng.random() < rd:
                c = rng.choice(pal)
                if fog:
                    c = mix(c, fog_at(gx, gy, .5), fog)
                rect(wl, gx, gy, ww, wh, c, True)
                WINDOWS.setdefault(plane, []).append((gx, gy, ww, wh, c))


def roof_furniture(L, blk, style, rng, pole, rim, beacons=True):
    x0, x1, top = blk
    if top < PIC_Y0 + 6:
        return
    if style == 'tank':
        cx = x0 + (x1 - x0) // 2
        for y in range(top - 5, top):
            for x in range(cx - 2, cx + 3):
                L.set(x, y, pole)
        for x in range(cx - 2, cx + 3):
            L.set(x, top - 6, rim)
        for x in (cx - 2, cx + 2):
            L.set(x, top, pole)
    elif style == 'antenna':
        cx = x0 + rng.randint(2, max(2, x1 - x0 - 2))
        for y in range(top - rng.randint(6, 11), top):
            L.set(cx, y, pole)
        if beacons:
            BEACONS.append((cx, top - 12))
    elif style == 'spire':
        cx = x0 + (x1 - x0) // 2
        for k in range(5):
            for x in range(cx - 2 + k // 2, cx + 3 - k // 2):
                L.set(x, top - 1 - k, shade(x, top - 1 - k, 1.0, .3))
        for y in range(top - 14, top - 5):
            L.set(cx, y, pole)
        if beacons:
            BEACONS.append((cx, top - 15))
    elif style == 'billboard':
        for x in range(x0 + 1, x1 - 1):
            for y in range(top - 7, top - 1):
                L.set(x, y, C('#0a1019'))
        for x in range(x0 + 1, x1 - 1):
            L.set(x, top - 7, rim)
            L.set(x, top - 2, rim)


# planes, far to near: (x0, x1, top, furniture)
P0 = [(-4, 12, 88, ''), (10, 24, 79, 'spire'), (22, 36, 85, ''), (34, 50, 73, 'tank'), (48, 62, 83, ''),
      (60, 72, 91, ''), (70, 86, 77, 'antenna'), (84, 98, 87, ''), (96, 112, 71, 'spire'), (110, 124, 81, ''),
      (122, 136, 89, ''), (134, 150, 75, 'tank'), (148, 162, 85, 'antenna'), (160, 174, 79, ''),
      (172, 188, 87, ''), (186, 200, 73, 'spire'), (198, 212, 83, ''), (210, 226, 91, 'tank'),
      (224, 240, 77, ''), (238, 260, 85, 'antenna')]
P1 = [(-6, 16, 90, ''), (14, 38, 82, 'tank'), (36, 60, 96, ''), (58, 80, 74, 'antenna'), (78, 104, 99, ''),
      (102, 124, 88, 'spire'), (122, 146, 78, ''), (144, 166, 94, 'tank'), (164, 190, 70, 'spire'),
      (188, 214, 92, ''), (212, 236, 80, 'antenna'), (234, 262, 98, '')]
P2 = [(-8, 30, 106, ''), (28, 70, 112, 'tank'), (68, 112, 102, ''), (110, 150, 110, ''), (148, 196, 104, 'antenna'),
      (194, 232, 108, ''), (230, 264, 100, '')]


def far_towers():
    rng = Rng(1112)
    L, wl = new_layer('far'), new_layer('win-far')
    for (x0, x1, top, style) in P0:
        blk = (x0, x1, top)
        paint_block(L, blk, 1.1, .12, rim=(C('#a070d8'), .2), rim_side=-1, mist=.75)
        lit_windows(wl, 'far', blk, dict(w=1, h=1, px=3, py=4, dens=.2), rng, .5)
        roof_furniture(L, blk, style, rng, C('#3a2a63'), C('#7a5cb0'))
    return L


def mid_towers():
    rng = Rng(204)
    L, wl = new_layer('mid'), new_layer('win-mid')
    furn = new_layer('mid-furniture')
    for (x0, x1, top, style) in P1:
        blk = (x0, x1, top)
        paint_block(L, blk, -.9, .74, rim=(C('#9a64e8'), .4), rim_side=-1 if x0 < 128 else 1,
                    top_edge=(C('#c090ff'), .55), mist=.5)
        lit_windows(wl, 'mid', blk, dict(w=2, h=2, px=4, py=5, dens=.3), rng, .12)
        roof_furniture(furn, blk, style, rng, C('#1c132f'), C('#412e74'))
    return L


def near_towers():
    rng = Rng(77)
    L, wl = new_layer('near'), new_layer('win-near')
    furn = new_layer('near-furniture')
    for (x0, x1, top, style) in P2:
        blk = (x0, x1, top)
        paint_block(L, blk, -2.4, .9, rim=(C('#ff7ac8'), .55), rim_side=1 if x0 > 100 else -1,
                    top_edge=(C('#e090ff'), .5), mist=.25)
        lit_windows(wl, 'near', blk, dict(w=2, h=3, px=5, py=6, dens=.36), rng, 0, dark=L)
        roof_furniture(furn, blk, style, rng, C('#140d24'), C('#3a2a63'))
    return L


# ----------------------------------------------------------------------------
# the rooftop in the foreground
# ----------------------------------------------------------------------------
ROOF_TOP = 120          # the parapet's lit cap
ROOF_Y0, ROOF_Y1 = 124, 134      # roof surface, back edge to front edge


def foreground():
    """The roof we are standing on: a parapet, gravel, seams and wet patches
    holding the colours of the lights."""
    L = new_layer('roof')
    rng = Rng(99)
    cap_hi, cap, cap_lo = C('#8472b3'), C('#514078'), C('#2c1f4a')
    ramp = [C('#0d0818'), C('#140d24'), C('#1c142f'), C('#241a3d')]
    for x in range(W):
        L.set(x, ROOF_TOP, cap_hi)
        L.set(x, ROOF_TOP + 1, cap)
        L.set(x, ROOF_TOP + 2, cap_lo)
    for y in range(ROOF_TOP + 3, ROOF_Y0):                       # the parapet's face
        t = (y - ROOF_TOP - 3) / float(ROOF_Y0 - ROOF_TOP - 3)
        for x in range(W):
            L.set(x, y, ramp_at(ramp, 1.6 - t * 1.4, x, y, .7))
    for x in range(14, W, 38):                                  # expansion joints
        for y in range(ROOF_TOP + 3, ROOF_Y0):
            L.set(x, y, C('#0a0614'))
            L.set(x + 1, y, C('#2a1d48'))
    for y in range(ROOF_Y0, PIC_Y1):                            # the roof surface: lighter toward the back
        t = (y - ROOF_Y0) / float(PIC_Y1 - ROOF_Y0)
        for x in range(W):
            L.set(x, y, ramp_at(ramp, 2.4 - t * 1.9, x, y, .8))
    for sy in (127, 132):                                       # membrane seams
        for x in range(W):
            L.set(x, sy, C('#0a0614'))
            L.set(x, sy + 1, C('#231a3c'))
    for _ in range(160):                                        # gravel
        L.set(rng.randint(0, W - 1), rng.randint(ROOF_Y0, PIC_Y1 - 1),
              rng.choice([C('#2a1d48'), C('#0a0614'), C('#1a1230')]))
    # wet patches: dark water holding the colours of the lights above, in streaks
    for (cx, cy, rx, ry, hi) in ((92, 130, 11, 1.8, '#5a3a78'), (150, 128, 12, 1.5, '#2a5a78'),
                                 (196, 131, 9, 1.4, '#6a3a88'), (62, 133, 7, 1.0, '#2a4a68')):
        for (x, y) in blob_pts(cx, cy, rx, ry):
            L.set(x, y, C('#07041a'))
        for (x, y) in blob_pts(cx - 1, cy - .3, rx * .7, ry * .5):
            if (x + y) % 2 == 0 or x % 3 == 0:
                L.set(x, y, C(hi))
    return L


def window_bloom(plane):
    """Lit windows glow a little onto the wall round them: one translucent layer per kind of light."""
    lit = {}
    for (x, y, w, h, c) in WINDOWS.get(plane, []):
        for j in range(h):
            for i in range(w):
                lit[(x + i, y + j)] = c
    wall = layer(plane)
    kinds = {'warm': (255, 190, 100), 'cool': (110, 220, 255), 'hot': (255, 90, 200)}
    rings = {k: set() for k in kinds}
    for (px, py), c in lit.items():
        if c[2] > c[0] + 10:
            kind = 'cool'
        elif c[1] < c[0] * .62:
            kind = 'hot'
        else:
            kind = 'warm'
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (px + dx, py + dy)
                if q not in lit and wall.get(q[0], q[1]) is not None:
                    rings[kind].add(q)
    for kind, pts in rings.items():
        if pts:
            L = new_layer('wbloom-%s-%s' % (plane, kind), alpha=.16)
            for (x, y) in pts:
                L.set(x, y, kinds[kind])
