#!/usr/bin/env python3
"""Generates claude-level1.svg, the pixel-art header of the level 1 README:
Claude in a hard hat on a cyberpunk rooftop, drones overhead, and a speech
bubble saying "currently under construction".

Everything is drawn on a 256x144 pixel grid and written out as merged
rectangles with crispEdges, so the SVG stays sharp at any size. A little CSS
animation (hovering drones, blinking lights, traffic, rain) rides on top; the
picture without it is complete, and that is what reduced motion shows.

    python3 make_claude_level1.py                       # rewrite claude-level1.svg
    python3 make_claude_level1.py --png /tmp/p.png      # also a PNG of the static frame
    python3 make_claude_level1.py --png /tmp/p.png --scale 10 --crop 100,86,100,56

Standard library only, and deterministic: same script, same bytes.
"""
import argparse
import math
import os
import struct
import zlib

W, H = 256, 144


# ----------------------------------------------------------------------------
# tiny deterministic PRNG (mulberry32) so the art does not depend on the Python
# version's `random` implementation


# ----------------------------------------------------------------------------
class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def random(self):
        self.s = (self.s + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.s
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    def randint(self, a, b):
        return a + int(self.random() * (b - a + 1))

    def choice(self, seq):
        return seq[int(self.random() * len(seq))]

    def chance(self, p):
        return self.random() < p


# ----------------------------------------------------------------------------
# colour helpers


# ----------------------------------------------------------------------------
def C(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hexs(c):
    return '#%02x%02x%02x' % c


def mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t + .5),
            int(a[1] + (b[1] - a[1]) * t + .5),
            int(a[2] + (b[2] - a[2]) * t + .5))


def lum(c):
    return (.299 * c[0] + .587 * c[1] + .114 * c[2]) / 255.0


BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def bay(x, y):
    """4x4 ordered-dither threshold in (0, 1)."""
    return (BAYER[y & 3][x & 3] + .5) / 16.0


def ramp_at(ramp, u, x, y, soft=.5):
    """Pick from a colour ramp at fractional index u, dithering between the two
    neighbouring steps. `soft` is how much of each step is dithered (0 = hard
    bands, 1 = fully smooth)."""
    n = len(ramp) - 1
    u = max(0.0, min(float(n), u))
    i = int(u)
    if i >= n:
        return ramp[n]
    f = (u - i - (.5 - soft / 2)) / soft
    f = max(0.0, min(1.0, f))
    return ramp[i + 1] if f > bay(x, y) else ramp[i]


def piecewise(stops, v):
    if v <= stops[0][0]:
        return stops[0][1]
    for (a, ua), (b, ub) in zip(stops, stops[1:]):
        if v <= b:
            return ua + (ub - ua) * (v - a) / float(b - a)
    return stops[-1][1]


# ----------------------------------------------------------------------------
# layers and drawing primitives


# ----------------------------------------------------------------------------
class Layer:
    """A sparse grid of pixels. `anim` is a CSS class that animates the whole
    layer, `group` wraps neighbouring layers in one shared <g> (e.g. a drone
    that bobs as a unit)."""

    def __init__(self, name, anim=None, group=None, style=None):
        self.name = name
        self.anim = anim
        self.group = group
        self.style = style
        self.pix = {}
        self.emit = set()

    def set(self, x, y, c, emit=False):
        if 0 <= x < W and 0 <= y < H:
            self.pix[(x, y)] = c
            if emit:
                self.emit.add((x, y))

    def get(self, x, y):
        return self.pix.get((x, y))

    def erase(self, x, y):
        self.pix.pop((x, y), None)


LAYERS = []


def new_layer(name, **kw):
    L = Layer(name, **kw)
    LAYERS.append(L)
    return L


def rect(L, x, y, w, h, c, emit=False):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            L.set(xx, yy, c, emit)


def hline(L, x0, x1, y, c, emit=False):
    for x in range(x0, x1 + 1):
        L.set(x, y, c, emit)


def vline(L, x, y0, y1, c, emit=False):
    for y in range(y0, y1 + 1):
        L.set(x, y, c, emit)


def line(L, x0, y0, x1, y1, c, emit=False, dash=None):
    """Bresenham. dash=(on, off) makes a dashed line."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    i = 0
    while True:
        if dash is None or (i % (dash[0] + dash[1])) < dash[0]:
            L.set(x0, y0, c, emit)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
        i += 1


def line_pts(x0, y0, x1, y1):
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def ell_pts(cx, cy, rx, ry):
    pts = set()
    for y in range(int(cy - ry - 1), int(cy + ry + 2)):
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                pts.add((x, y))
    return pts


def composite_at(layers, x, y):
    for L in reversed(layers):
        c = L.pix.get((x, y))
        if c is not None:
            return L, c
    return None, None


def glow(layers, cx, cy, r, color, amax=.5, levels=3, falloff=1.6,
         ex=1.0, ey=1.0, skip_lum=.62, out=None):
    """Dithered, banded light bloom: tints whatever is already drawn under it.
    `layers` are searched top-down for the visible pixel. Pixels flagged as
    emitters (or bright ones) are left alone so lights stay crisp."""
    for y in range(int(cy - r * ey) - 1, int(cy + r * ey) + 2):
        for x in range(int(cx - r * ex) - 1, int(cx + r * ex) + 2):
            d = math.hypot((x - cx) / ex, (y - cy) / ey)
            if d > r:
                continue
            f = (1 - d / r) ** falloff
            L, c = composite_at(layers, x, y)
            if c is None or (x, y) in L.emit or lum(c) > skip_lum:
                continue
            lvl = min(levels, int(f * levels + bay(x, y)))
            if lvl <= 0:
                continue
            (out or L).set(x, y, mix(c, color, amax * lvl / levels))


# ----------------------------------------------------------------------------
# bitmap fonts


# ----------------------------------------------------------------------------
# lowercase 5-wide face for the speech bubble: (first row, rows). Rows 2..6 are
# the x-height, 0..1 the ascender, 7..8 the descender.
FONT5 = {
    'c': (2, [".###.", "#...#", "#....", "#...#", ".###."]),
    'u': (2, ["#...#", "#...#", "#...#", "#..##", ".##.#"]),
    'r': (2, ["#.##.", "##..#", "#....", "#....", "#...."]),
    'e': (2, [".###.", "#...#", "#####", "#....", ".###."]),
    'n': (2, ["#.##.", "##..#", "#...#", "#...#", "#...#"]),
    't': (1, [".#...", "###..", ".#...", ".#...", ".#..#", "..##."]),
    'l': (0, [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."]),
    'y': (2, ["#...#", "#...#", "#...#", ".####", "....#", "....#", ".###."]),
    'd': (0, ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"]),
    'o': (2, [".###.", "#...#", "#...#", "#...#", ".###."]),
    's': (2, [".####", "#....", ".###.", "....#", "####."]),
    'i': (0, ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."]),
}

# 3x5 capitals and a digit, enough for the signs on the roofs
FONT3 = {
    'E': ("###", "#..", "##.", "#..", "###"),
    'H': ("#.#", "#.#", "###", "#.#", "#.#"),
    'L': ("#..", "#..", "#..", "#..", "###"),
    'M': ("#.#", "###", "###", "#.#", "#.#"),
    'O': (".#.", "#.#", "#.#", "#.#", ".#."),
    'S': (".##", "#..", ".#.", "..#", "##."),
    'T': ("###", ".#.", ".#.", ".#.", ".#."),
    '1': (".#.", "##.", ".#.", ".#.", "###"),
}


def text3(L, x, y, s, c, emit=False, vertical=False):
    """3x5 signage text, one letter per column or (vertical) per row."""
    cx, cy = x, y
    for ch in s:
        glyph = FONT3[ch]
        for j, row in enumerate(glyph):
            for i, v in enumerate(row):
                if v == '#':
                    L.set(cx + i, cy + j, c, emit)
        if vertical:
            cy += 6
        else:
            cx += len(glyph[0]) + 1


def text5(L, x, y, s, c, space=4):
    """Lowercase 5x7 text; `y` is the top of the ascender row."""
    cx = x
    for ch in s:
        if ch == ' ':
            cx += space
            continue
        top, rows = FONT5[ch]
        for j, row in enumerate(rows):
            for i, v in enumerate(row):
                if v == '#':
                    L.set(cx + i, y + top + j, c)
        cx += 6


def text5_width(s, space=4):
    w = 0
    for ch in s:
        w += space if ch == ' ' else 6
    return w - 1


# ----------------------------------------------------------------------------
# preview / output helpers


# ----------------------------------------------------------------------------
# Overlay classes that stay invisible until their animation shows them. The
# static frame (and reduced motion) leaves them out; css() hides them.
HIDDEN_BY_DEFAULT = ('fb', 'pb', 'mb', 'blink', 'tw', 'wf', 'flick')


def flatten(layers):
    """The static frame: what you see before (or without) any animation."""
    img = {}
    for L in layers:
        if L.anim in HIDDEN_BY_DEFAULT:
            continue
        img.update(L.pix)
    return img


def write_png(path, img, scale=4, crop=None, bg=(13, 17, 23)):
    x0, y0, cw, ch = crop or (0, 0, W, H)
    rows = []
    for y in range(y0, y0 + ch):
        line_px = bytearray()
        for x in range(x0, x0 + cw):
            r, g, b = img.get((x, y), bg)
            line_px += bytes((r, g, b)) * scale
        raw = b'\x00' + bytes(line_px)
        rows.extend([raw] * scale)
    raw = b''.join(rows)

    def chunk(t, d):
        return (struct.pack('>I', len(d)) + t + d +
                struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF))

    png = (b'\x89PNG\r\n\x1a\n' +
           chunk(b'IHDR', struct.pack('>IIBBBBB', cw * scale, ch * scale, 8, 2, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


# ----------------------------------------------------------------------------
# palette


# ----------------------------------------------------------------------------
SKY = [C(h) for h in ('#06041a', '#0b0826', '#110c35', '#1a1049', '#26145c',
                      '#37186c', '#4e1a79', '#6d1f82', '#922786', '#b93484',
                      '#dd4a82', '#f4687e')]
SKY_STOPS = [(0, 0.0), (24, 2.4), (50, 4.5), (72, 6.4), (90, 8.4), (104, 10.0), (116, 11.0)]

FAR_R = [C(h) for h in ('#2d1a5c', '#381c68', '#452073', '#55257e', '#692c88', '#7e3492')]
MID_R = [C(h) for h in ('#160f3a', '#1c1046', '#231252', '#2c155e', '#37186a', '#431c76')]
NEAR_R = [C(h) for h in ('#0a0a22', '#0c0b28', '#0f0e30', '#131238', '#181642', '#1e1a4c')]

PINK = C('#ff4fd8')
PINK_D = C('#a81f8c')
CYAN = C('#5ff3ff')
CYAN_D = C('#1c97b4')
WARM = [C('#ffd37a'), C('#ffa94d'), C('#fff0b8')]
COOL = [C('#6ef3ff'), C('#3fb6ff'), C('#a6e2ff')]
HOT = [C('#ff6ad5'), C('#ff3d9a')]
WIN_MIXES = [WARM, WARM, COOL, COOL, WARM + COOL, WARM + HOT, COOL + HOT]

BG = []          # static layers that light effects are allowed to tint


def sky_layer():
    L = new_layer('sky')
    BG.append(L)
    for y in range(H):
        u = piecewise(SKY_STOPS, y)
        for x in range(W):
            L.set(x, y, ramp_at(SKY, u, x, y, .34))
    rng = Rng(7)
    dim, mid, hi = C('#5b4aa0'), C('#9a8be0'), C('#eae4ff')
    for _ in range(95):
        x = rng.randint(2, W - 3)
        y = int(rng.random() ** 1.5 * 76) + 1
        c = dim if rng.chance(.55) else mid
        L.set(x, y, c, True)
    for x, y in ((18, 12), (47, 30), (86, 9), (121, 22), (163, 8), (206, 17), (239, 36),
                 (28, 52), (196, 48)):
        L.set(x, y, hi, True)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            L.set(x + dx, y + dy, mid, True)


# ----------------------------------------------------------------------------
# city


# ----------------------------------------------------------------------------
STYLES = ['flat', 'flat', 'step', 'step3', 'slantL', 'slantR', 'spire', 'antenna', 'tank', 'dome']


def make_specs(rng, x0, x1, wr, tr, gap=(-3, 1), styles=STYLES, cap=()):
    specs = []
    x = x0
    while x < x1:
        w = rng.randint(*wr)
        top = rng.randint(*tr)
        for (cx0, cx1, mintop) in cap:
            if x + w > cx0 and x < cx1:
                top = max(top, mintop)
        specs.append(dict(x=x, w=w, top=top, style=rng.choice(styles),
                          seed=rng.randint(0, 1 << 30)))
        x += w + rng.randint(*gap)
    return specs


def silhouette(sp, base, rng):
    x, w, top, style = sp['x'], sp['w'], sp['top'], sp['style']
    x1 = x + w - 1
    pts = set()
    tiers = []

    def R(a, b, c, d, win=True):
        for yy in range(b, d + 1):
            for xx in range(a, c + 1):
                pts.add((xx, yy))
        if win:
            tiers.append((a, b, c, d))

    h = base - top
    if style in ('flat', 'antenna', 'tank'):
        R(x, top, x1, base)
    elif style == 'step':
        t = top + max(6, int(h * (.18 + .2 * rng.random())))
        ins = max(2, w // 5)
        R(x, t, x1, base)
        R(x + ins, top, x1 - ins, t - 1)
    elif style == 'step3':
        t1 = top + max(5, int(h * .2))
        t2 = t1 + max(5, int(h * .22))
        ins = max(2, w // 7)
        R(x, t2, x1, base)
        R(x + ins, t1, x1 - ins, t2 - 1)
        R(x + 2 * ins, top, x1 - 2 * ins, t1 - 1)
    elif style in ('slantL', 'slantR'):
        cut = min(w - 3, 4 + rng.randint(0, 4))
        for k in range(w):
            kk = k if style == 'slantL' else w - 1 - k
            ct = top + max(0, cut - kk)
            R(x + k, ct, x + k, base, win=False)
        tiers.append((x, top + cut, x1, base))
    elif style == 'spire':
        sw = max(3, w // 3)
        sx = x + (w - sw) // 2
        stop = top + max(8, int(h * .3))
        R(x, stop, x1, base)
        R(sx, top + 6, sx + sw - 1, stop - 1)
        for k in range(6):                      # pointed cap
            R(sx + k // 2, top + 6 - k - 1, sx + sw - 1 - k // 2, top + 6 - k - 1, win=False)
        cx = sx + sw // 2
        for yy in range(top - 7, top):
            pts.add((cx, yy))
    elif style == 'dome':
        ry = min(8, w // 2)
        for k in range(w):
            t = int(round(ry * (1 - math.sqrt(max(0.0, 1 - ((k - (w - 1) / 2.0) / (w / 2.0)) ** 2)))))
            R(x + k, top + t, x + k, base, win=False)
        tiers.append((x, top + ry, x1, base))

    if style == 'antenna':
        cx = x + rng.randint(1, max(1, w - 2))
        for yy in range(top - rng.randint(5, 11), top):
            pts.add((cx, yy))
    if style == 'tank' and w >= 8:
        tx = x + rng.randint(1, w - 6)
        for yy in range(top - 5, top):
            for xx in range(tx, tx + 5):
                pts.add((xx, yy))
        pts.add((tx + 1, top - 6))
        pts.add((tx + 3, top - 6))
    return pts, tiers


def place_windows(L, pts, tiers, rng, cfg, fog=None):
    ww, wh, px, py = cfg['w'], cfg['h'], cfg['px'], cfg['py']
    for (x0, y0, x1, y1) in tiers:
        pal = rng.choice(WIN_MIXES)
        for gy in range(y0 + 2, y1 - wh, py):
            band = rng.random()
            rd = cfg['dens'] * (2.4 if band > .86 else (.3 if band < .38 else 1.0))
            for gx in range(x0 + 2, x1 - ww + 1, px):
                if rng.random() < rd:
                    c = rng.choice(pal)
                    if fog:
                        c = mix(c, fog[0], fog[1])
                    for j in range(wh):
                        for i in range(ww):
                            if (gx + i, gy + j) in pts:
                                L.set(gx + i, gy + j, c, True)


GLOW_X = 150      # x of the horizon glow that building edges face


def draw_skyline(name, specs, base, ramp, ys, soft, rim, top_edge, cfg, fog=None):
    L = new_layer(name)
    BG.append(L)
    for sp in specs:
        r = Rng(sp['seed'])
        pts, tiers = silhouette(sp, base, r)
        for (x, y) in pts:
            u = piecewise(ys, y)
            L.set(x, y, ramp_at(ramp, u, x, y, soft))
        facing = 1 if sp['x'] + sp['w'] / 2.0 < GLOW_X else -1   # edge that looks at the glow
        for (x, y) in pts:
            if (x, y - 1) not in pts:
                L.set(x, y, top_edge)
            elif (x + facing, y) not in pts:
                L.set(x, y, rim)
        place_windows(L, pts, tiers, r, cfg, fog)


def city_layers():
    rng = Rng(1112)
    far = make_specs(rng, -6, 262, (9, 17), (38, 78), gap=(-2, 0),
                     styles=['flat', 'step', 'step3', 'spire', 'spire', 'antenna', 'slantL', 'slantR'],
                     cap=((118, 192, 64),))
    draw_skyline('far', far, 112, FAR_R, [(30, 0.0), (112, 5.0)], .3,
                 C('#8a3f9e'), C('#6f3496'),
                 dict(w=1, h=1, px=3, py=4, dens=.16), fog=(C('#8a3a98'), .35))
    mid = make_specs(rng, -8, 262, (12, 24), (34, 92), gap=(-3, 1),
                     cap=((122, 190, 80),))
    draw_skyline('mid', mid, 114, MID_R, [(30, 0.0), (114, 5.0)], .3,
                 C('#6a3aa6'), C('#4a2a86'),
                 dict(w=1, h=2, px=3, py=4, dens=.24), fog=(C('#6a2a84'), .15))
    near = make_specs(rng, -4, 262, (14, 27), (50, 100), gap=(-3, 0),
                      cap=((120, 192, 92),))
    near[0].update(x=-3, w=26, top=38, style='step')
    near[-1].update(top=36, style='step3')
    draw_skyline('near', near, 118, NEAR_R, [(30, 0.0), (118, 5.0)], .3,
                 C('#2f4aa8'), C('#27348a'),
                 dict(w=2, h=2, px=4, py=5, dens=.30))


# ----------------------------------------------------------------------------
# cyberpunk dressing: horizon glow, neon, billboard, crane


# ----------------------------------------------------------------------------
def layer(name):
    for L in LAYERS:
        if L.name == name:
            return L
    raise KeyError(name)


def top_of(L, x):
    ys = [y for (xx, y) in L.pix if xx == x]
    return min(ys) if ys else None


def sign_v(L, x, y, text, col, dim):
    """Vertical neon sign: dark plate, neon frame, stacked 3x5 letters."""
    h = len(text) * 6 - 1
    rect(L, x - 2, y - 2, 7, h + 4, C('#0b0820'))
    for yy in range(y - 2, y + h + 2):
        L.set(x - 2, yy, dim, True)
        L.set(x + 4, yy, dim, True)
    for xx in range(x - 2, x + 5):
        L.set(xx, y - 2, dim, True)
        L.set(xx, y + h + 1, dim, True)
    text3(L, x, y, text, col, emit=True, vertical=True)
    glow(BG, x + 1, y + h // 2, 1, col, amax=.5, levels=3, falloff=.8, ex=12, ey=h / 2.0 + 9)


def eye_billboard(L, blink, x, y):
    """The repo's purple eye, as a glowing billboard."""
    w, h = 21, 13
    plate, frame, lid = C('#0a0722'), C('#6a3cff'), C('#b79bff')
    rect(L, x, y, w, h, plate)
    for xx in range(x, x + w):
        L.set(xx, y, frame, True)
        L.set(xx, y + h - 1, frame, True)
    for yy in range(y, y + h):
        L.set(x, yy, frame, True)
        L.set(x + w - 1, yy, frame, True)
    cx, cy = x + 10, y + 6
    almond = set()
    for dx in range(-8, 9):
        half = 3.6 * (1 - (dx / 8.6) ** 2) ** .7
        for dy in range(-4, 5):
            if abs(dy) <= half:
                almond.add((cx + dx, cy + dy))
    for p in almond:
        L.set(p[0], p[1], C('#160c42'), True)
    for p in outline_of(almond):
        L.set(p[0], p[1], lid, True)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx * dx + dy * dy <= 9 and (cx + dx, cy + dy) in almond:
                L.set(cx + dx, cy + dy, C('#6a3cff') if dx * dx + dy * dy > 3 else C('#8f6bff'), True)
    for dy in range(-1, 2):
        L.set(cx, cy + dy, C('#080414'), True)
        L.set(cx + 1, cy + dy, C('#080414'), True)
    L.set(cx - 1, cy - 1, C('#ffffff'), True)
    # blink: lids shut to a line
    for p in almond:
        blink.set(p[0], p[1], plate, True)
    for dx in range(-8, 9):
        blink.set(cx + dx, cy, lid, True)
    glow(BG, cx, cy, 1, (110, 64, 255), amax=.55, levels=3, falloff=.7, ex=20, ey=14)


def lattice_v(L, x0, x1, y0, y1, c, step=2):
    vline(L, x0, y0, y1, c)
    vline(L, x1, y0, y1, c)
    for i, y in enumerate(range(y0, y1, step)):
        if i % 2 == 0:
            line(L, x0, y, x1, min(y + step, y1), c)
        else:
            line(L, x1, y, x0, min(y + step, y1), c)


def lattice_h(L, x0, x1, y0, y1, c, step=2):
    hline(L, x0, x1, y0, c)
    hline(L, x0, x1, y1, c)
    for i, x in enumerate(range(x0, x1, step)):
        if i % 2 == 0:
            line(L, x, y0, min(x + step, x1), y1, c)
        else:
            line(L, x, y1, min(x + step, x1), y0, c)


def crane(L, beacon, bx, by):
    """Tower crane on the roof of the half-built tower at (bx, by)."""
    c, hi, dk = C('#3a44a0'), C('#6f7be0'), C('#202a70')
    lattice_v(L, bx - 1, bx + 1, by - 16, by, c)
    rect(L, bx - 3, by - 20, 7, 3, dk)                  # operator cab
    L.set(bx + 1, by - 19, C('#ffd37a'), True)
    L.set(bx + 2, by - 19, C('#ffd37a'), True)
    lattice_h(L, bx - 14, bx + 58, by - 23, by - 21, c)
    rect(L, bx - 14, by - 21, 6, 5, dk)                 # counterweight
    hline(L, bx - 14, bx - 9, by - 21, hi)
    vline(L, bx, by - 31, by - 24, c)                    # cat-head
    vline(L, bx - 1, by - 28, by - 24, dk)
    line(L, bx, by - 31, bx + 56, by - 23, c)
    line(L, bx, by - 31, bx - 13, by - 23, c)
    tx = bx + 40                                         # trolley, hook, load
    rect(L, tx - 1, by - 21, 3, 2, dk)
    vline(L, tx, by - 19, by - 8, c)
    rect(L, tx - 1, by - 8, 3, 2, hi)
    line(L, tx, by - 7, tx - 7, by - 3, c)
    line(L, tx, by - 7, tx + 7, by - 3, c)
    rect(L, tx - 8, by - 3, 16, 3, C('#7d89d8'))
    hline(L, tx - 8, tx + 7, by - 3, C('#b8c2ff'))
    hline(L, tx - 8, tx + 7, by - 1, C('#4a54a8'))
    beacon.set(bx, by - 32, C('#ff3355'), True)
    for dx, dy in ((-1, -32), (1, -32), (0, -33), (0, -31)):
        beacon.set(bx + dx, by + dy, C('#9a1f45'))


def city_extras():
    glow([layer('sky'), layer('far')], 150, 106, 100, (255, 98, 150), amax=.55, levels=4,
         falloff=1.3, ex=1.2, ey=.62, skip_lum=.8)
    signs = new_layer('signs')
    BG.append(signs)
    sign_v(signs, 14, 50, 'HOTEL', PINK, PINK_D)
    sign_v(signs, 186, 56, 'MESH', CYAN, CYAN_D)
    eyeblink = new_layer('eye-blink', anim='blink', style='animation-duration:5.5s')
    eye_billboard(signs, eyeblink, 3, 91)
    beacon = new_layer('crane-beacon', anim='pulse', style='animation-duration:1.6s')
    bx = 9
    crane(signs, beacon, bx, top_of(layer('near'), bx))
    glow(BG, bx, top_of(layer('near'), bx) - 32, 9, (255, 60, 100), amax=.6, levels=3, falloff=1.2)


# ----------------------------------------------------------------------------
# rooftop we are standing on


# ----------------------------------------------------------------------------
CAP_Y = 111          # top of the parapet cap
FLOOR_Y = 122        # first row of roof surface
FEET_Y = 134         # where everything stands


def roof_layer():
    L = new_layer('roof')
    BG.append(L)
    rng = Rng(99)
    cap_hi, cap, cap_lo = C('#8f8bbd'), C('#605c8e'), C('#403c6c')
    face = [C('#17132f'), C('#1f1a3d'), C('#27224a'), C('#2c2753')]
    # parapet cap
    hline(L, 0, W - 1, CAP_Y, cap_hi)
    hline(L, 0, W - 1, CAP_Y + 1, cap)
    hline(L, 0, W - 1, CAP_Y + 2, cap_lo)
    # parapet face: shadowed under the cap, lighter lower down
    for y in range(CAP_Y + 3, FLOOR_Y):
        t = (y - CAP_Y - 3) / float(FLOOR_Y - CAP_Y - 4)
        for x in range(W):
            L.set(x, y, ramp_at(face, t * 3, x, y, .7))
    for x in range(0, W, 32):                       # expansion joints
        vline(L, x, CAP_Y + 3, FLOOR_Y - 1, C('#110e24'))
        vline(L, x + 1, CAP_Y + 3, FLOOR_Y - 1, C('#2f2a58'))
    for _ in range(70):                             # grime
        L.set(rng.randint(0, W - 1), rng.randint(CAP_Y + 4, FLOOR_Y - 1), C('#120f28'))
    hline(L, 0, W - 1, FLOOR_Y - 1, C('#3b3566'))
    # roof surface
    fl = [C('#1b1738'), C('#201b42'), C('#261f4a')]
    for y in range(FLOOR_Y, 140):
        t = (y - FLOOR_Y) / 17.0
        for x in range(W):
            L.set(x, y, ramp_at(fl, t * 2, x, y, .8))
    # panel seams: horizontal runs plus staggered verticals
    for sy in (127, 133, 138):
        hline(L, 0, W - 1, sy, C('#120f26'))
        hline(L, 0, W - 1, sy + 1, C('#322b5e'))
    for sy0, sy1, off in ((FLOOR_Y, 126, 10), (128, 132, 38), (134, 137, 22)):
        for x in range(off, W, 56):
            vline(L, x, sy0, sy1, C('#120f26'))
            vline(L, x + 1, sy0, sy1, C('#322b5e'))
    for _ in range(140):                            # gravel
        L.set(rng.randint(0, W - 1), rng.randint(FLOOR_Y, 139),
              rng.choice([C('#322b5e'), C('#120f26'), C('#2b2452')]))
    # hazard stripe along the front edge
    hline(L, 0, W - 1, 139, C('#0b0818'))
    for y in range(140, 144):
        for x in range(W):
            L.set(x, y, C('#f5b82e') if ((x + y) // 4) % 2 == 0 else C('#1a1426'))


# ----------------------------------------------------------------------------
# Claude


# ----------------------------------------------------------------------------
O_OUT, O0, O1, O2, O3, O4 = (C('#45190f'), C('#8a3a26'), C('#b8523a'),
                             C('#d97757'), C('#eb9068'), C('#f8b690'))
Y_OUT, Y0, Y1, Y2, Y3, Y4 = (C('#5e3208'), C('#c47a12'), C('#e8a21e'),
                             C('#ffc933'), C('#ffdf6a'), C('#fff5b8'))
EYE = C('#150a14')
GLINT = C('#e6fcff')

CLAUDE_CX = 150
BX = CLAUDE_CX - 22          # body left edge (body is 45 wide, centre column 22)
BY = FEET_Y - 38             # row of the hat brim's top


def outline_of(mask, avoid=()):
    out = set()
    for (x, y) in mask:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (x + dx, y + dy)
            if p not in mask and not any(p in a for a in avoid):
                out.add(p)
    return out


def bevel(mask, p, base, hi, lo):
    """Light from the upper left: lit edge, shaded edge."""
    x, y = p
    if (x - 1, y) not in mask or (x, y - 1) not in mask:
        return hi
    if (x + 1, y) not in mask or (x, y + 1) not in mask:
        return lo
    return base


def body_color(lx, ly):
    c = O2
    if ly in (5, 6):
        c = O1                      # shadow cast by the brim
    if ly >= 7:
        if lx in (0, 1):
            c = O3
        if lx == 0 and ly >= 10:
            c = O4
        if lx in (43, 44):
            c = O1
        if lx == 44 and ly >= 27:
            c = O0
        if ly in (29, 30):
            c = O1
        if (lx >= 43 and ly >= 29) or (lx == 0 and ly == 29):
            c = O0
    return c


def raised_arm(lx0, ly0, lx1, ly1, brush=5):
    """Pixel mask of a thick diagonal arm plus a mitten-shaped hand."""
    m = set()
    r = brush // 2
    for (x, y) in line_pts(lx0, ly0, lx1, ly1):
        for j in range(brush):
            for i in range(brush):
                m.add((x - r + i, y - r + j))
    hx, hy = lx1 - 3, ly1 - 4
    for j in range(7):
        for i in range(7):
            if (i, j) in ((0, 0), (6, 0), (0, 1), (6, 1), (6, 6)):
                continue
            m.add((hx + i, hy + j))
    return m


def lay_mask(lay):
    return {(x - BX, y - BY) for (x, y) in lay.pix}


def claude_layers():
    legs = new_layer('claude-legs')
    body = new_layer('claude-body', group='breathe')
    armA = new_layer('claude-arm-a', group='breathe', anim='fa')
    armB = new_layer('claude-arm-b', group='breathe', anim='fb')
    blink = new_layer('claude-blink', group='breathe', anim='blink')
    led = new_layer('claude-led', group='breathe', anim='pulse')

    def put(L, lx, ly, c, emit=False):
        L.set(BX + lx, BY + ly, c, emit)

    # ---- masks (local coordinates, origin = left end of the body, brim top row)
    body_m = {(x, y) for y in range(1, 31) for x in range(0, 45)
              if not (x in (0, 44) and y == 30)}
    larm_m = {(x, y) for y in range(18, 29) for x in range(-5, 0)
              if (x, y) not in ((-5, 18), (-5, 28))}
    leg_xs = (5, 13, 27, 35)
    leg_m = {(x + i, y) for x in leg_xs for i in range(5) for y in range(31, 39)}

    widths = [13, 19, 23, 27, 29, 31, 33, 35, 35, 37, 37, 37]
    dome_m, dome_rows = set(), {}
    for r, w in enumerate(widths):
        x0, x1 = 22 - w // 2, 22 + w // 2
        dome_rows[r] = (x0, x1)
        for x in range(x0, x1 + 1):
            dome_m.add((x, -12 + r))
    brim_rows = {0: (3, 41), 1: (2, 42), 2: (2, 42), 3: (3, 41)}
    brim_m = {(x, y) for y, (a, b) in brim_rows.items() for x in range(a, b + 1)}
    hat_m = dome_m | brim_m

    # ---- legs
    for (x, y) in leg_m:
        i = x - max(lx for lx in leg_xs if lx <= x)
        c = O1
        if i == 0:
            c = O2
        if i == 4:
            c = O0
        if y == 31:
            c = O0
        if y == 38:
            c = O_OUT if i in (1, 2, 3) else O0
        put(legs, x, y, c)

    # ---- body
    for (x, y) in body_m:
        put(body, x, y, body_color(x, y))
    for (x, y) in larm_m:
        c = O2
        if x == -5:
            c = O3
        elif x == -1:
            c = O1
        if y == 28 or (x == -4 and y == 27):
            c = O1
        put(body, x, y, c)
    # eyes
    for ex in (12, 29):
        for y in range(10, 18):
            for i in range(4):
                put(body, ex + i, y, EYE)
        put(body, ex, 11, GLINT)
        put(body, ex, 12, GLINT)
    # blink overlay: lids down
    for ex in (12, 29):
        for y in range(10, 18):
            for i in range(4):
                put(blink, ex + i, y, body_color(ex + i, y))
        for i in range(4):
            put(blink, ex + i, 14, EYE)

    # ---- hat
    for (x, y) in dome_m:
        r = y + 12
        x0, x1 = dome_rows[r]
        c = Y2
        if r >= 1:
            if x <= x0 + 2:
                c = Y3
            if x >= x1 - 3:
                c = Y1
            if x == x1 and r >= 3:
                c = Y0
        if 18 <= x <= 26 and r >= 1:
            c = Y3
            if 21 <= x <= 23 and 2 <= r <= 8:
                c = Y4
        if x in (17, 27) and r >= 2:
            c = Y1
        if r == 0:
            c = Y4 if 19 <= x <= 25 else Y3
        if r == 11 and not (18 <= x <= 26):
            c = Y1
        if (x - x0, r) in ((3, 3), (3, 4), (2, 5), (2, 6), (4, 2)):
            c = Y4
        put(body, x, y, c)
    for (x, y) in brim_m:
        if y == 0:
            c = Y3 if x < 33 else Y2
            if 8 <= x <= 16:
                c = Y4
        elif y == 1:
            c = Y2 if x < 36 else Y1
        elif y == 2:
            c = Y1 if x < 38 else Y0
        else:
            c = Y0
        put(body, x, y, c)
    for x in range(3, 42):               # line under the brim
        put(body, x, 4, Y_OUT)
    # headlamp, centred on the ridge
    frame, lens = C('#2b3358'), C('#bff9ff')
    for x in range(18, 27):
        put(body, x, -7, frame, True)
        put(body, x, -3, frame, True)
    for y in (-6, -5, -4):
        put(body, 18, y, frame, True)
        put(body, 26, y, frame, True)
        for x in range(19, 26):
            put(body, x, y, lens, True)
    for x in range(21, 24):
        put(body, x, -5, C('#ffffff'), True)
    # mesh-node antenna with a blinking LED
    for y in range(-19, -12):
        put(body, 22, y, C('#8b97bf'))
    put(led, 22, -20, C('#7ffcff'), True)
    for dx, dy in ((-1, -20), (1, -20), (0, -21)):
        put(led, 22 + dx, dy, C('#2a8fa8'))

    # ---- raised arm, two wave frames
    for lay, tip in ((armA, (51, 7)), (armB, (55, 10))):
        m = raised_arm(46, 23, tip[0], tip[1])
        m -= body_m
        for p in m:
            c = bevel(m, p, O2, O3, O1)
            if p[0] <= 47 and p[1] >= 18:
                c = O1
            put(lay, p[0], p[1], c)
        for p in outline_of(m, (body_m, hat_m)):
            put(lay, p[0], p[1], O_OUT)

    # ---- backlight from the glowing horizon: pink on the left edge, a warmer
    # magenta on the right (a cyan rim on orange would only turn grey)
    RIM_L, RIM_R = (255, 110, 215), (255, 130, 205)
    for lay in (body, armA, armB):
        mask = lay_mask(lay)
        for (x, y), c in list(lay.pix.items()):
            lx, ly = x - BX, y - BY
            if lay is not body:                          # the two wave frames
                if (lx + 1, ly) not in mask and ly > 8:
                    lay.pix[(x, y)] = mix(c, RIM_R, .40)
                continue
            if lx in (-5, 0, 1) and 9 <= ly <= 28:
                lay.pix[(x, y)] = mix(c, RIM_L, .30)
            if lx == 44 and 9 <= ly <= 28:
                lay.pix[(x, y)] = mix(c, RIM_R, .38)
            if -12 <= ly < 0:
                x0r, x1r = dome_rows[ly + 12]
                if lx == x0r:
                    lay.pix[(x, y)] = mix(c, RIM_L, .28)
                if lx == x1r:
                    lay.pix[(x, y)] = mix(c, RIM_R, .35)

    # ---- outlines for the static parts
    whole = body_m | larm_m | hat_m
    for (lx, ly) in outline_of(whole, (leg_m,)):
        near_hat = any((lx + dx, ly + dy) in hat_m
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        c = Y_OUT if near_hat and ly < 4 else O_OUT
        put(legs if ly >= 31 else body, lx, ly, c)
    for (lx, ly) in outline_of(leg_m, (whole,)):
        if ly >= 31:
            put(legs, lx, ly, O_OUT)


# ----------------------------------------------------------------------------
# speech bubble


# ----------------------------------------------------------------------------
BUB_X, BUB_Y, BUB_W, BUB_H = 36, 43, 101, 32
LINES = ("currently under", "construction")


def rounded_rect(x, y, w, h, inset=(2, 1)):
    m = set()
    for j in range(h):
        d = 0
        if j < len(inset):
            d = inset[j]
        elif h - 1 - j < len(inset):
            d = inset[h - 1 - j]
        for i in range(d, w - d):
            m.add((x + i, y + j))
    return m


def bubble_layers():
    L = new_layer('bubble')
    paper, paper_lo = C('#fff5df'), C('#eadcc2')
    ink, ink_shadow, edge = C('#2a1650'), C('#d5c4e8'), C('#1b0e33')
    outer = rounded_rect(BUB_X, BUB_Y, BUB_W, BUB_H)
    inner = rounded_rect(BUB_X + 1, BUB_Y + 1, BUB_W - 2, BUB_H - 2, (1, 0))
    # tail: leans toward Claude's hat
    tail_x, tail_len = BUB_X + 78, 12
    tail_in = set()
    for k in range(tail_len):
        wdt = max(1, 9 - (k * 9) // tail_len)
        x0 = tail_x + (k * 18) // tail_len
        for i in range(wdt):
            tail_in.add((x0 + i, BUB_Y + BUB_H - 1 + k))
    for p in sorted(outer | tail_in):
        L.set(p[0], p[1], edge)
    for (x, y) in inner | {p for p in tail_in if p[1] > BUB_Y + BUB_H - 2}:
        L.set(x, y, paper)
    for x in range(BUB_X + 3, BUB_X + BUB_W - 3):       # hazard stripe along the top edge
        for j in (1, 2):
            L.set(x, BUB_Y + j, C('#ffc933') if ((x + j) // 3) % 2 == 0 else C('#2a1650'))
    for x in range(BUB_X + 2, BUB_X + BUB_W - 2):       # soft underside
        L.set(x, BUB_Y + BUB_H - 2, paper_lo)
    # the tail gets an outline of its own
    for (x, y) in outline_of(tail_in, (inner,)):
        if y >= BUB_Y + BUB_H - 1:
            L.set(x, y, edge)
    for (x, y) in tail_in:                             # open the seam where tail meets bubble
        if y == BUB_Y + BUB_H - 1:
            L.set(x, y, paper)
    yt = BUB_Y + 7
    ends = []
    for n, line_text in enumerate(LINES):
        tw = text5_width(line_text)
        x0 = BUB_X + 1 + (BUB_W - 2 - tw) // 2
        y0 = yt + 11 * n
        text5(L, x0 + 1, y0 + 1, line_text, ink_shadow)
        text5(L, x0, y0, line_text, ink)
        ends.append((x0 + tw, y0))
    # blinking cursor right after the last word, in Claude orange
    cur = new_layer('cursor', anim='pulse', style='animation-duration:1.1s')
    ex, ey = ends[-1]
    rect(cur, ex + 3, ey - 1, 4, 8, O2)
    rect(cur, ex + 3, ey - 1, 1, 8, O3)
    rect(cur, ex + 6, ey - 1, 1, 8, O1)


# ----------------------------------------------------------------------------
# construction site props


# ----------------------------------------------------------------------------
STEEL = [C('#2a3158'), C('#454f80'), C('#6b79ad'), C('#98a8dc')]
CONE_O, CONE_OL, CONE_OD = C('#ff7a1a'), C('#ffa352'), C('#c4520c')
CONE_W, CONE_WD = C('#f4f1ff'), C('#b4b2d2')
PLATE, PLATE_L = C('#1f1838'), C('#3a3060')
AMBER, AMBER_D = C('#ffb62e'), C('#a86a08')


def contact_shadow(cx, cy, rx, ry, a=.5):
    for y in range(cy - ry - 1, cy + ry + 2):
        for x in range(cx - rx - 1, cx + rx + 2):
            d = math.hypot((x - cx) / float(rx), (y - cy) / float(ry))
            if d >= 1:
                continue
            aa = a if d < .6 else (a * .55 if d < .85 else (a * .4 if (x + y) % 2 == 0 else 0))
            if aa > 0:
                tint(x, y, (6, 4, 18), aa)


def cone(L, x, y):
    """9 wide, 11 tall; (x, y) is the top-left."""
    rows = [(4, 1, 'o'), (3, 3, 'o'), (3, 3, 'o'), (2, 5, 'w'), (2, 5, 'o'),
            (1, 7, 'o'), (1, 7, 'w'), (1, 7, 'o'), (0, 9, 'o')]
    for j, (ox, wd, k) in enumerate(rows):
        for i in range(wd):
            if k == 'w':
                c = CONE_W if i < wd - 2 else CONE_WD
            else:
                c = CONE_OL if i == 0 else (CONE_OD if i >= wd - 2 else CONE_O)
            L.set(x + ox + i, y + j, c)
    for j in (9, 10):
        for i in range(9):
            L.set(x + i, y + j, PLATE_L if (j == 9 and i < 8) else PLATE)


def crate(L, x, y, w, h, strap=True):
    wood, wood_l, wood_d, edge = C('#8f6038'), C('#b07a48'), C('#5e3c22'), C('#2e1b10')
    for j in range(h):
        for i in range(w):
            c = wood
            if j == 0 or i == 0:
                c = wood_l
            if j == h - 1 or i == w - 1:
                c = wood_d
            if j in (h // 2,) and 0 < i < w - 1:
                c = wood_d
            L.set(x + i, y + j, c)
    for i in range(w):
        L.set(x + i, y - 1, edge)
        L.set(x + i, y + h, edge)
    for j in range(-1, h + 1):
        L.set(x - 1, y + j, edge)
        L.set(x + w, y + j, edge)
    if strap:
        for j in range(h):
            L.set(x + w // 2, y + j, STEEL[2])
            L.set(x + w // 2 + 1, y + j, STEEL[1])


def barricade(L, x, y):
    """Sawhorse barrier, 30 wide x 18 tall, with a flasher on the left end."""
    leg = STEEL
    for (lx0) in (x + 3, x + 20):
        line(L, lx0 + 3, y + 11, lx0, y + 17, leg[1])
        line(L, lx0 + 4, y + 11, lx0 + 1, y + 17, leg[0])
        line(L, lx0 + 3, y + 11, lx0 + 6, y + 17, leg[2])
        line(L, lx0 + 4, y + 11, lx0 + 7, y + 17, leg[1])
        L.set(lx0 - 1, y + 17, PLATE_L)
        L.set(lx0, y + 17, leg[1])
        L.set(lx0 + 6, y + 17, leg[1])
        L.set(lx0 + 7, y + 17, PLATE_L)
    for (ry) in (y + 2, y + 7):
        for i in range(30):
            for j in range(4):
                stripe = ((i + j) // 4) % 2 == 0
                c = CONE_W if stripe else CONE_O
                if j == 3:
                    c = CONE_WD if stripe else CONE_OD
                if j == 0:
                    c = C('#ffffff') if stripe else CONE_OL
                L.set(x + i, ry + j, c)
        for j in range(4):
            L.set(x - 1, ry + j, PLATE)
            L.set(x + 30, ry + j, PLATE)
        for i in range(30):
            L.set(x + i, ry - 1, PLATE)
            L.set(x + i, ry + 4, PLATE)
    # flasher housing on top of the left end
    for j in range(4):
        for i in range(5):
            L.set(x + 2 + i, y - 3 + j, C('#2a2240') if j in (0, 3) or i in (0, 4) else AMBER_D)
    L.set(x + 3, y - 2, AMBER)
    L.set(x + 4, y - 2, AMBER)
    L.set(x + 3, y - 1, AMBER)
    L.set(x + 4, y - 1, AMBER)


def patch_panel(L, x, y, w=12, h=10):
    """5.8 GHz patch antenna board: teal PCB, gold patch."""
    edge, pcb, pcb_l, pcb_d = C('#0f2a3c'), C('#2f7f9f'), C('#5bb6d2'), C('#1f5a75')
    gold, gold_l, gold_d = C('#d8b24f'), C('#f2d27a'), C('#8e6e22')
    for j in range(h):
        for i in range(w):
            c = pcb
            if i == 0 or j == 0:
                c = pcb_l
            if i == w - 1 or j == h - 1:
                c = pcb_d
            L.set(x + i, y + j, c)
    for i in range(-1, w + 1):
        L.set(x + i, y - 1, edge)
        L.set(x + i, y + h, edge)
    for j in range(h):
        L.set(x - 1, y + j, edge)
        L.set(x + w, y + j, edge)
    for j in range(3, h - 3):
        for i in range(3, w - 3):
            c = gold
            if i == 3 or j == 3:
                c = gold_l
            if i == w - 4 or j == h - 4:
                c = gold_d
            L.set(x + i, y + j, c)
    L.set(x + w // 2, y + h // 2, edge)
    for i in (2, w - 3):
        L.set(x + i, y + 1, C('#a8b8e0'))
        L.set(x + i, y + h - 2, C('#a8b8e0'))


def mast(L, cx, base_y):
    """Scaffold + antenna mast, centred on cx. Returns the beacon position."""
    st = STEEL
    lx, rx = cx - 12, cx + 11
    top = base_y - 36
    for px in (lx, rx):                     # scaffold posts
        for y in range(top, base_y + 1):
            L.set(px, y, st[2])
            L.set(px + 1, y, st[0])
    for py in (base_y - 1, base_y - 17, top):   # decks
        for x in range(lx - 1, rx + 3):
            L.set(x, py, C('#ffc933') if ((x + py) // 3) % 2 == 0 else C('#1a1426'))
            L.set(x, py + 1, C('#6b4a08') if ((x + py) // 3) % 2 == 0 else C('#0b0818'))
    line(L, lx + 2, base_y - 2, rx - 1, base_y - 16, st[1])
    line(L, rx - 1, base_y - 18, lx + 2, top - 1 + 2, st[1])
    # the mast itself
    mtop = base_y - 70
    for y in range(mtop, base_y - 1):
        L.set(cx - 1, y, st[3] if y % 9 else st[2])
        L.set(cx, y, st[2])
        L.set(cx + 1, y, st[0])
    for y in range(mtop, base_y - 1, 9):
        for dx in (-2, 2):
            L.set(cx + dx, y, st[1])
    # guy wires
    line(L, cx, mtop + 8, lx, top, st[1], dash=(1, 1))
    line(L, cx, mtop + 8, rx + 1, top, st[1], dash=(1, 1))
    # crossbar with the installed panel on the left and an empty bracket on the right
    cb = base_y - 58
    for x in range(cx - 5, cx + 12):
        L.set(x, cb, st[3])
        L.set(x, cb + 1, st[1])
    patch_panel(L, cx - 16, cb - 4, 12, 10)
    for dx in (-5, -4):
        L.set(cx + dx, cb - 3, st[2])
    for y in range(cb - 3, cb + 1):
        L.set(cx + 10, y, st[2])
    L.set(cx + 10, cb - 4, C('#ffe27a'))        # bolt heads waiting for the panel
    L.set(cx + 6, cb - 1, C('#ffe27a'))
    # whip antenna + beacon
    for y in range(mtop - 6, mtop):
        L.set(cx, y, st[2])
    return cx, mtop - 7


def plate(L, x, y, text):
    """A small yellow site plate with stencilled text."""
    w = 2 + sum(len(FONT3[ch][0]) + 1 for ch in text)
    for j in range(7):
        for i in range(w):
            edge = j in (0, 6) or i in (0, w - 1)
            L.set(x + i, y + j, C('#7a4a08') if edge else (C('#ffd23a') if j < 3 else C('#f0b020')))
    text3(L, x + 2, y + 1, text, C('#2a1650'))
    L.set(x + 1, y + 1, C('#fff2a8'))
    L.set(x + w - 2, y + 1, C('#fff2a8'))


def props_layers():
    L = new_layer('props')
    BG.append(L)
    # cones, barricade, crates, and the antenna mast
    for (cx, cy) in ((108, 134), (194, 134), (48, 134)):
        contact_shadow(cx, cy - 1, 8, 2, .5)
    contact_shadow(85, FEET_Y - 1, 18, 2, .5)
    contact_shadow(246, FEET_Y - 1, 14, 2, .5)
    contact_shadow(216, FEET_Y - 1, 24, 2, .5)
    cone(L, 104, FEET_Y - 10)
    cone(L, 190, FEET_Y - 10)
    cone(L, 44, FEET_Y - 10)
    barricade(L, 70, FEET_Y - 17)
    crate(L, 232, FEET_Y - 11, 12, 11)
    crate(L, 241, FEET_Y - 19, 10, 8, strap=False)
    crate(L, 245, FEET_Y - 8, 8, 8, strap=False)
    bx, by = mast(L, 216, FEET_Y)
    plate(L, 216 - 5, FEET_Y - 14, 'L1')
    beacon = new_layer('mast-beacon', anim='pulse', style='animation-duration:1.4s;animation-delay:-.5s')
    beacon.set(bx, by, C('#7ffcff'), True)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        beacon.set(bx + dx, by + dy, C('#2a8fa8'))


# ----------------------------------------------------------------------------
# drones


# ----------------------------------------------------------------------------
DP = dict(o=C('#0f1328'), a=C('#1d2440'), b=C('#2b3660'), c=C('#40508a'),
          d=C('#6679b8'), e=C('#a4b8f0'), f=C('#e8f0ff'))
RED, GREEN, LAMP = C('#ff4466'), C('#3dffa8'), C('#fffbe0')
ROTOR_HI, ROTOR_LO = C('#d6e2ff'), C('#6b80c4')


def dim_pal(pal, k, toward=C('#3a1f6a')):
    return {n: mix(c, toward, k) for n, c in pal.items()}


def sym_set(L, x0, y0, wd, lx, ly, c, emit=False):
    L.set(x0 + lx, y0 + ly, c, emit)
    L.set(x0 + wd - 1 - lx, y0 + ly, c, emit)


def sym_rect(L, x0, y0, wd, lx0, ly0, lx1, ly1, c, emit=False):
    for ly in range(ly0, ly1 + 1):
        for lx in range(lx0, lx1 + 1):
            sym_set(L, x0, y0, wd, lx, ly, c, emit)


def rotors(L_a, L_b, x0, y0, wd, centres, pw):
    """Two spinning-rotor frames: a blade line plus a dithered disc whose
    phase flips between the frames."""
    for cxl in centres:
        for cx in (x0 + cxl, x0 + wd - 1 - cxl):
            for i in range(-(pw // 2), pw // 2 + 1):
                L_a.set(cx + i, y0, ROTOR_LO if abs(i) >= pw // 2 - 1 else ROTOR_HI)
                if abs(i) <= pw // 2 - 2:
                    L_b.set(cx + i, y0, ROTOR_HI)
                if abs(i) <= pw // 2 - 1:
                    (L_a if (cx + i) % 2 == 0 else L_b).set(cx + i, y0 + 1, ROTOR_LO)


def drone(name, cx, y0, size, pal, group):
    """size: 'L' 40 wide, 'M' 26, 'S' 16, 'X' 9. Returns (x0, lamp position)."""
    wd = dict(L=40, M=26, S=16, X=9)[size]
    x0 = cx - wd // 2
    body = new_layer('drone-' + name, group=group)
    pa = new_layer('drone-%s-props-a' % name, group=group)
    pb = new_layer('drone-%s-props-b' % name, group=group, anim='pb')
    pa.anim = 'pa'
    led_l = new_layer('drone-%s-led' % name, group=group, anim='pulse',
                      style='animation-duration:1.3s;animation-delay:%.1fs' % (-(cx % 7) * .17))
    P = pal
    if size == 'L':
        sym_rect(body, x0, y0, wd, 3, 2, 9, 5, P['b'])
        sym_rect(body, x0, y0, wd, 4, 2, 8, 2, P['d'])
        sym_rect(body, x0, y0, wd, 3, 3, 3, 4, P['c'])
        sym_rect(body, x0, y0, wd, 9, 3, 9, 5, P['a'])
        sym_rect(body, x0, y0, wd, 4, 5, 8, 5, P['a'])
        sym_rect(body, x0, y0, wd, 10, 4, 13, 4, P['c'])
        sym_rect(body, x0, y0, wd, 10, 5, 13, 5, P['a'])
        # hull + canopy
        sym_rect(body, x0, y0, wd, 15, 2, 19, 2, P['e'])
        sym_rect(body, x0, y0, wd, 14, 3, 19, 3, P['d'])
        sym_rect(body, x0, y0, wd, 13, 4, 19, 4, P['e'])
        sym_rect(body, x0, y0, wd, 13, 5, 19, 5, P['d'])
        sym_rect(body, x0, y0, wd, 13, 6, 19, 7, P['c'])
        sym_rect(body, x0, y0, wd, 13, 8, 19, 9, P['b'])
        sym_rect(body, x0, y0, wd, 14, 10, 19, 10, P['a'])
        sym_rect(body, x0, y0, wd, 16, 5, 16, 9, P['b'])        # panel seam
        sym_rect(body, x0, y0, wd, 18, 7, 19, 7, C('#5ff3ff'), True)  # status bar
        # lamp housing + lens
        sym_rect(body, x0, y0, wd, 16, 11, 19, 12, P['a'])
        sym_rect(body, x0, y0, wd, 16, 13, 17, 13, P['o'])
        sym_rect(body, x0, y0, wd, 18, 13, 19, 13, LAMP, True)
        # skids
        sym_rect(body, x0, y0, wd, 14, 11, 14, 14, P['b'])
        sym_rect(body, x0, y0, wd, 12, 15, 15, 15, P['c'])
        led_l.set(x0 + 3, y0 + 5, RED, True)
        led_l.set(x0 + wd - 4, y0 + 5, GREEN, True)
        rotors(pa, pb, x0, y0, wd, (6,), 13)
        return x0, (cx, y0 + 13)
    if size == 'M':
        sym_rect(body, x0, y0, wd, 2, 2, 6, 4, P['b'])
        sym_rect(body, x0, y0, wd, 2, 2, 6, 2, P['d'])
        sym_rect(body, x0, y0, wd, 6, 3, 6, 4, P['a'])
        sym_rect(body, x0, y0, wd, 7, 3, 9, 3, P['c'])
        sym_rect(body, x0, y0, wd, 7, 4, 9, 4, P['a'])
        sym_rect(body, x0, y0, wd, 9, 2, 12, 2, P['e'])
        sym_rect(body, x0, y0, wd, 9, 3, 12, 3, P['d'])
        sym_rect(body, x0, y0, wd, 8, 4, 12, 5, P['c'])
        sym_rect(body, x0, y0, wd, 8, 6, 12, 7, P['b'])
        sym_rect(body, x0, y0, wd, 9, 8, 12, 8, P['a'])
        sym_rect(body, x0, y0, wd, 11, 9, 12, 9, P['o'])
        sym_rect(body, x0, y0, wd, 9, 8, 9, 10, P['b'])
        led_l.set(x0 + 2, y0 + 4, RED, True)
        led_l.set(x0 + wd - 3, y0 + 4, GREEN, True)
        rotors(pa, pb, x0, y0, wd, (4,), 9)
        return x0, (cx, y0 + 9)
    if size == 'S':
        sym_rect(body, x0, y0, wd, 1, 2, 4, 3, P['b'])
        sym_rect(body, x0, y0, wd, 1, 2, 4, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 5, 3, P['c'])
        sym_rect(body, x0, y0, wd, 5, 2, 7, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 7, 4, P['b'])
        sym_rect(body, x0, y0, wd, 6, 5, 7, 5, P['a'])
        led_l.set(x0 + 1, y0 + 3, RED, True)
        led_l.set(x0 + wd - 2, y0 + 3, GREEN, True)
        rotors(pa, pb, x0, y0, wd, (2,), 5)
        pb.pix.clear()
        pa.anim = None
        return x0, (cx, y0 + 5)
    # 'X': a speck with a blinking light
    sym_rect(body, x0, y0, wd, 2, 2, 4, 2, P['c'])
    sym_rect(body, x0, y0, wd, 3, 3, 4, 3, P['b'])
    sym_rect(body, x0, y0, wd, 0, 1, 1, 1, P['d'])
    led_l.set(x0 + 4, y0 + 4, RED, True)
    pa.anim = None
    pb.pix.clear()
    return x0, (cx, y0 + 4)


def tint(x, y, color, a, layers=None):
    L, c = composite_at(layers or BG, x, y)
    if c is None or (x, y) in L.emit or lum(c) > .66:
        return
    L.set(x, y, mix(c, color, a))


def spot_beam(cx, y0, y1, hw0=3.0, hw1=27.0, color=(255, 226, 150)):
    """Cone of light as clean nested bands (bright core, softer sides, a
    checkerboard fringe) that tint whatever is behind them."""
    for y in range(y0, y1 + 1):
        t = (y - y0) / float(y1 - y0)
        hw = hw0 + (hw1 - hw0) * t
        taper = 1 - .62 * t
        apex = max(0.0, 1 - t / .16) * .16
        for x in range(int(cx - hw) - 1, int(cx + hw) + 2):
            s_ = abs(x - cx) / hw
            if s_ >= 1:
                continue
            if s_ < .30:
                a = .30
            elif s_ < .60:
                a = .21
            elif s_ < .84:
                a = .12
            else:
                a = .06 if (x + y) % 2 == 0 else 0
            a = a * taper + (apex if s_ < .6 else 0)
            if a > 0:
                tint(x, y, color, a)


def light_pool(cx, cy, rx, ry, color=(255, 206, 120)):
    """Where the beam lands: two clean bands and a dithered fringe."""
    for y in range(cy - ry - 1, cy + ry + 2):
        for x in range(cx - rx - 1, cx + rx + 2):
            d = math.hypot((x - cx) / float(rx), (y - cy) / float(ry))
            if d >= 1:
                continue
            if d < .5:
                a = .44
            elif d < .8:
                a = .26
            else:
                a = .12 if (x + y) % 2 == 0 else 0
            if a > 0:
                tint(x, y, color, a)


def mesh_link(x0, y0, x1, y1, col=C('#2fb4c8'), period=.6):
    a = new_layer('mesh-a', anim='ma', style='animation-duration:%.1fs' % period)
    b = new_layer('mesh-b', anim='mb', style='animation-duration:%.1fs' % period)
    for i, (x, y) in enumerate(line_pts(x0, y0, x1, y1)):
        if i % 5 < 3:
            a.set(x, y, col)
        if (i + 2) % 5 < 3:
            b.set(x, y, col)


def drones():
    for (a, b) in (((150, 23), (92, 17)), ((150, 23), (236, 43)), ((150, 23), (192, 16)),
                   ((192, 16), (232, 25)), ((92, 17), (78, 36)), ((92, 17), (118, 12)),
                   ((232, 25), (236, 43)), ((216, 63), (236, 43)), ((150, 23), (176, 33))):
        mesh_link(a[0], a[1], b[0], b[1])
    near = DP
    mid = dim_pal(DP, .22)
    far = dim_pal(DP, .5)
    # far -> near so nearer drones overlap farther ones
    for (cx, y) in ((16, 22), (118, 9), (246, 44), (176, 30)):
        drone('x%d' % cx, cx, y, 'X', far, ('bob', 'animation-delay:%.1fs' % (-cx % 5 * .6)))
    drone('s1', 78, 31, 'S', far, ('bob', 'animation-delay:-1.3s;animation-duration:3.4s'))
    drone('s2', 192, 13, 'S', far, ('bob', 'animation-delay:-2.1s;animation-duration:2.8s'))
    drone('m1', 92, 12, 'M', mid, ('bob', 'animation-delay:-.8s;animation-duration:3.8s'))
    drone('m2', 232, 20, 'M', mid, ('bob', 'animation-delay:-2.6s;animation-duration:3.1s'))
    # the drone fitting the second antenna panel
    pcx, py0 = 236, 38
    drone('p', pcx, py0, 'M', near, ('bob', 'animation-delay:-.4s;animation-duration:3s'))
    pl = new_layer('panel-load', group=('bob', 'animation-delay:-.4s;animation-duration:3s'))
    for dx in (-5, 5):
        line(pl, pcx + dx, py0 + 9, pcx + dx, py0 + 22, DP['c'])
    patch_panel(pl, pcx - 6, py0 + 22, 12, 10)
    x0, lamp = drone('lead', CLAUDE_CX, 18, 'L', near, ('bob', 'animation-delay:-1.9s'))
    lead = [L for L in LAYERS if L.name == 'drone-lead']
    glow(BG + lead, lamp[0], lamp[1] + 1, 7, (255, 244, 200), amax=.75, levels=3,
         falloff=1.1, ex=1.15, ey=.8)


# ----------------------------------------------------------------------------
# wet roof


# ----------------------------------------------------------------------------
def puddle(L, cx, cy, rx, ry):
    """A dark patch of standing water that reflects the sky."""
    base = [C('#0d0a2a'), C('#171340'), C('#26205c')]
    pts = ell_pts(cx, cy, rx, ry)
    for (x, y) in pts:
        t = (y - (cy - ry)) / float(2 * ry)
        L.set(x, y, ramp_at(base, (1 - t) * 2, x, y, .8))
        if (x, y - 1) not in pts:
            L.set(x, y, C('#34307a'))


def wet_roof():
    L = new_layer('puddles')
    BG.append(L)
    puddle(L, CLAUDE_CX, 136, 34, 3)


def claude_shadow():
    contact_shadow(CLAUDE_CX, FEET_Y, 26, 3, .55)


def reflect_claude(R):
    """Mirror the bottom of Claude into the puddle under him, darkened and
    rippled."""
    puddle_c = C('#14113a')
    pix = {}
    for L in LAYERS:
        if L.name.startswith('claude-legs') or L.name == 'claude-body':
            pix.update(L.pix)
    for (x, y), c in pix.items():
        if y > FEET_Y or y < FEET_Y - 3:
            continue
        ry = 2 * FEET_Y + 1 - y
        rx = x + (1 if ry in (137, 138) else 0)
        if ry <= 138 and (rx, ry) in layer('puddles').pix:
            R.set(rx, ry, mix(c, puddle_c, .62 if ry < 137 else .78))


# ----------------------------------------------------------------------------
# atmosphere: traffic, twinkle, flicker, rain, vignette, frame


# ----------------------------------------------------------------------------
CARS = []          # (css class, base x, direction, seconds)


def place_before(L, ref_name):
    LAYERS.remove(L)
    LAYERS.insert(LAYERS.index(layer(ref_name)), L)


def place_after(L, ref):
    """Put L directly above `ref` (a layer or a layer name) in the stack."""
    LAYERS.remove(L)
    LAYERS.insert(LAYERS.index(layer(ref) if isinstance(ref, str) else ref) + 1, L)


def hover_car(name, pref_x, pref_y, direction, behind, seconds, haze=0.0):
    """A little air-car crossing the whole picture, tucked between two
    skyline layers so towers pass in front of it. Its start position (what
    you see before/without animation) is the clear spot nearest pref."""
    L = new_layer('car-' + name, anim='car' + name, style='animation-duration:%ds' % seconds)
    sky_c = C('#3a1f6a')
    body, top, win = (mix(c, sky_c, haze) for c in (C('#5a47c0'), C('#b9a6ff'), C('#6ef3ff')))
    for j, (ox, wd) in enumerate(((2, 5), (1, 7), (0, 9))):
        for i in range(wd):
            xx = ox + i if direction > 0 else 8 - ox - i
            L.set(xx, j, top if j == 0 else body)
    for ox in (3, 4):
        L.set(ox if direction > 0 else 8 - ox, 1, win, True)
    front = 9 if direction > 0 else -1
    back = -1 if direction > 0 else 9
    L.set(front, 2, C('#fff6c0'), True)
    L.set(front + direction, 2, C('#ffb84a'), True)
    L.set(back, 2, C('#ff3355'), True)
    for k in range(2, 6):
        L.set(back - direction * (k - 1), 2, mix(C('#ff3355'), C('#1a1040'), .45 + .1 * k), True)
    place_before(L, behind)
    above = [M for M in LAYERS[LAYERS.index(L) + 1:] if M.anim is None or M.group is not None]
    pts = list(L.pix)
    best = None
    for oy in range(-14, 15):
        for ox in range(-90, 91):
            cx, cy = pref_x + ox, pref_y + oy
            if cx < 6 or cx > W - 16 or cy < 6 or cy > 100:
                continue
            if any((cx + x, cy + y) in M.pix for (x, y) in pts for M in above):
                continue
            cost = abs(ox) + 3 * abs(oy)
            if best is None or cost < best[0]:
                best = (cost, cx, cy)
    _, bx, by = best
    L.pix = {(x + bx, y + by): c for (x, y), c in L.pix.items()}
    L.emit = {(x + bx, y + by) for (x, y) in L.emit}
    CARS.append(('car' + name, bx, direction, seconds))


def twinkle():
    sky = layer('sky')
    stars = sorted(p for p in sky.emit if p[1] < 60)
    for n, dur in enumerate((3.1, 4.3, 5.7)):
        L = new_layer('twinkle%d' % n, anim='tw',
                      style='animation-duration:%.1fs;animation-delay:-%.1fs' % (dur, n * 1.3))
        for p in stars[n::7]:
            L.set(p[0], p[1], sky.get(p[0], p[1]))
        place_after(L, sky)


def window_flicker():
    """Some lit windows go dark now and then. Each overlay sits right above
    its own skyline layer, so nearer towers still hide it correctly."""
    rng = Rng(55)
    for name, count in (('mid', 14), ('near', 18)):
        src = layer(name)
        cand = [p for p in sorted(src.emit) if lum(src.pix.get(p, (0, 0, 0))) > .45]
        for n, dur in enumerate((7, 9, 11)):
            L = new_layer('winflick-%s%d' % (name, n), anim='wf',
                          style='animation-duration:%ds;animation-delay:-%ds' % (dur, n * 3))
            for _ in range(count // 3):
                x, y = cand[rng.randint(0, len(cand) - 1)]
                c = src.pix[(x, y)]
                for dx in (0, 1):
                    for dy in (0, 1):
                        q = (x + dx, y + dy)
                        if src.pix.get(q) == c:
                            L.set(q[0], q[1], mix(c, C('#100a30'), .88))
            place_after(L, src)


def neon_flicker():
    for (x, y, text, idx, dim, dur) in ((14, 50, 'HOTEL', 3, PINK_D, 3.3), (186, 56, 'MESH', 2, CYAN_D, 4.1)):
        L = new_layer('flick-' + text, anim='flick', style='animation-duration:%.1fs' % dur)
        text3(L, x, y + 6 * idx, text[idx], mix(dim, C('#0b0820'), .35), emit=True)
        place_after(L, 'signs')


RAIN_PERIOD, RAIN_SHIFT = 48, 16


def rain():
    rng = Rng(404)
    L = new_layer('rain', anim='rain')
    tile = []
    for _ in range(11):
        x, y = rng.randint(-30, W + 30), rng.randint(0, RAIN_PERIOD - 1)
        tile.append((x, y))
    for k in range(-1, 5):
        for (x, y) in tile:
            for i in range(5):
                px, py = x - RAIN_SHIFT * k - i // 3, y + RAIN_PERIOD * k + i
                L.set(px, py, C('#8fb0f0') if i == 4 else C('#4a64a8'))


def vignette():
    for y in range(H):
        for x in range(W):
            dx, dy = (x - W / 2.0) / (W / 2.0), (y - H / 2.0) / (H / 2.0)
            d = math.sqrt(dx * dx * .8 + dy * dy * .9)
            if d <= .78:
                continue
            a = min(.5, ((d - .78) / .5) ** 1.4 * .5)
            lvl = min(3, int(a * 3 / .5 + bay(x, y) - .05))
            if lvl > 0:
                L, c = composite_at(BG, x, y)
                if c is not None:
                    L.set(x, y, mix(c, (4, 2, 14), .5 * lvl / 3.0))


CORNERS = ({(0, 0), (1, 0), (0, 1), (W - 1, 0), (W - 2, 0), (W - 1, 1),
            (0, H - 1), (1, H - 1), (0, H - 2), (W - 1, H - 1), (W - 2, H - 1), (W - 1, H - 2)})


def frame():
    """One-pixel frame with stepped corners, so the picture reads as a card on
    light and dark pages alike."""
    for L in LAYERS:
        for p in CORNERS:
            L.erase(*p)
    F = new_layer('frame')
    hi, lo = C('#6a56c0'), C('#241a5c')
    ring = {(x, y) for x in range(W) for y in (0, H - 1)}
    ring |= {(x, y) for y in range(H) for x in (0, W - 1)}
    ring |= {(1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)}
    for (x, y) in ring - CORNERS:
        F.set(x, y, hi if (x < W // 2 and y < H // 2) or x == 0 or y == 0 else lo)


# ----------------------------------------------------------------------------
# SVG output


# ----------------------------------------------------------------------------
def rects_for(pixels):
    """Merge a set of pixels into as few rectangles as a row-run + vertical
    stacking pass can manage."""
    rows = {}
    for (x, y) in pixels:
        rows.setdefault(y, []).append(x)
    runs = {}
    for y, xs in rows.items():
        xs.sort()
        out, start, prev = [], xs[0], xs[0]
        for x in xs[1:]:
            if x != prev + 1:
                out.append((start, prev - start + 1))
                start = x
            prev = x
        out.append((start, prev - start + 1))
        runs[y] = out
    rects, active = [], {}
    for y in range(min(rows), max(rows) + 2):
        cur = set(runs.get(y, ()))
        for key in [k for k in active if k not in cur]:
            y0 = active.pop(key)
            rects.append((key[0], y0, key[1], y - y0))
        for key in cur:
            active.setdefault(key, y)
    return rects


def path_d(rects):
    rects = sorted(rects, key=lambda r: (r[1], r[0]))
    d, px, py = [], 0, 0
    for i, (x, y, w, h) in enumerate(rects):
        d.append('M%d %d' % (x, y) if i == 0 else 'm%d %d' % (x - px, y - py))
        d.append('h%dv%dh%dz' % (w, h, -w))
        px, py = x, y
    return ''.join(d)


def paths_for(pix):
    by = {}
    for p, c in pix.items():
        by.setdefault(c, set()).add(p)
    return ''.join('<path fill="%s" d="%s"/>' % (hexs(c), path_d(rects_for(by[c])))
                   for c in sorted(by, key=lambda c: (-len(by[c]), c)))


def attrs(cls, style):
    out = ''
    if cls:
        out += ' class="%s"' % cls
    if style:
        out += ' style="%s"' % style
    return out


def emit_run(run):
    flat = {}
    for L in run:
        flat.update(L.pix)
    return paths_for(flat) if flat else ''


def emit_layers(layers, nested=False):
    """Consecutive plain layers are flattened into one block; animated layers
    and groups keep their own wrapper so CSS can move them."""
    layers = [L for L in layers if L.pix]
    out, run, i = [], [], 0

    def flush():
        if run:
            out.append(emit_run(run))
            run.clear()

    while i < len(layers):
        L = layers[i]
        if L.group is not None and not nested:
            flush()
            j = i
            while j < len(layers) and layers[j].group == L.group:
                j += 1
            cls, style = (L.group, '') if isinstance(L.group, str) else L.group
            out.append('<g%s>%s</g>' % (attrs(cls, style), emit_layers(layers[i:j], nested=True)))
            i = j
            continue
        if L.anim is not None:
            flush()
            out.append('<g%s>%s</g>' % (attrs(L.anim, L.style), emit_run([L])))
        else:
            run.append(L)
        i += 1
    flush()
    return ''.join(out)


def car_keys(bx, d):
    """Keyframes: drive off one edge, reappear at the other, land on the base x."""
    exit_x = W + 12 if d > 0 else -12
    enter_x = -12 if d > 0 else W + 12
    first, second = abs(exit_x - bx), abs(bx - enter_x)
    f = 100.0 * first / (first + second)
    return ('0%%{transform:translateX(0)}%.1f%%{transform:translateX(%dpx)}'
            '%.1f%%{transform:translateX(%dpx)}100%%{transform:translateX(0)}'
            % (f, exit_x - bx, f + .1, enter_x - bx))


def css(variant='animated'):
    hidden = ','.join('.' + c for c in HIDDEN_BY_DEFAULT)
    if variant == 'static':          # nothing moves: the picture a still frame shows
        return hidden + '{opacity:0}'
    if variant == 'overlays':        # debugging aid: show every hidden overlay
        return hidden + '{opacity:1}.fa,.pa,.ma{opacity:0}'
    step = 'steps(1,end) infinite'   # everything moves in whole pixels
    return ''.join([
        hidden + '{opacity:0}',
        '.bob{animation:bob 3.4s %s}' % step,
        '@keyframes bob{0%{transform:translateY(0)}25%{transform:translateY(1px)}'
        '50%{transform:translateY(0)}75%{transform:translateY(-1px)}}',
        '.breathe{animation:breathe 2.4s %s}' % step,
        '@keyframes breathe{0%{transform:translateY(0)}50%{transform:translateY(1px)}}',
        # a frame that is on first (fa, pa, ma) and its twin that is on second
        '.fa,.pa,.ma,.pulse{animation:on-off 1s %s}' % step,
        '.fb,.pb,.mb{animation:off-on 1s %s}' % step,
        '@keyframes on-off{0%{opacity:1}50%{opacity:0}}',
        '@keyframes off-on{0%{opacity:0}50%{opacity:1}}',
        '.fa,.fb{animation-duration:.9s}',          # Claude waving
        '.pa,.pb{animation-duration:.12s}',         # rotors
        '.ma,.mb{animation-duration:.6s}',          # mesh-link dashes
        # overlays that appear briefly: blinks, a star going dark, a window, a neon letter
        '.blink{animation:blink 4.6s %s}' % step,
        '@keyframes blink{0%{opacity:0}95%{opacity:1}98%{opacity:0}}',
        '.tw{animation:tw 4s %s}' % step,
        '@keyframes tw{0%{opacity:0}70%{opacity:1}85%{opacity:0}}',
        '.wf{animation:wf 8s %s}' % step,
        '@keyframes wf{0%{opacity:0}40%{opacity:1}68%{opacity:0}}',
        '.flick{animation:flick 3.5s %s}' % step,
        '@keyframes flick{0%{opacity:0}88%{opacity:1}90%{opacity:0}92%{opacity:1}'
        '94%{opacity:0}96%{opacity:1}98%{opacity:0}}',
        # rain: one tile repeats every RAIN_PERIOD px down / RAIN_SHIFT px left
        '.rain{animation:rain .6s linear infinite}',
        '@keyframes rain{to{transform:translate(-%dpx,%dpx)}}' % (RAIN_SHIFT, RAIN_PERIOD),
        ''.join('.%s{animation:%s %ds linear infinite}@keyframes %s{%s}'
                % (n, n, secs, n, car_keys(bx, d)) for (n, bx, d, secs) in CARS),
        '@media (prefers-reduced-motion:reduce){*{animation:none!important}}',
    ])


TITLE = 'Claude is currently under construction'
DESC = ('Pixel art: Claude, an orange block-shaped mascot in a yellow hard hat, waves from a '
        'cyberpunk rooftop at night. Drones hover overhead, one lowering a 5.8 GHz patch '
        'antenna onto a mast. A speech bubble reads: currently under construction.')


def write_svg(path, variant='animated'):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'shape-rendering="crispEdges" role="img" aria-labelledby="t d">'
           '<title id="t">%s</title><desc id="d">%s</desc><style>%s</style>%s</svg>\n'
           % (W, H, W * 3, H * 3, TITLE, DESC, css(variant), emit_layers(LAYERS)))
    with open(path, 'w') as f:
        f.write(svg)
    return len(svg)


# ----------------------------------------------------------------------------
# build + main


# ----------------------------------------------------------------------------
def flasher():
    """The barricade's amber lamp; its glow is an overlay that blinks."""
    L = new_layer('flasher', anim='pulse', style='animation-duration:1.2s')
    glow(BG, 74, 116, 9, (255, 176, 40), amax=.85, levels=3, falloff=1.0, out=L)
    rect(L, 73, 115, 2, 2, C('#fff2b0'), True)


def build():
    """Draw the layers back to front."""
    sky_layer()
    city_layers()
    city_extras()
    rain()                       # falls in front of the city, behind the roof
    roof_layer()
    props_layers()
    flasher()
    wet_roof()
    spot_beam(CLAUDE_CX, 33, 133)
    light_pool(CLAUDE_CX, 135, 34, 5)
    claude_shadow()
    refl = new_layer('reflection')
    claude_layers()
    reflect_claude(refl)
    drones()
    bubble_layers()
    hover_car('A', 170, 44, 1, 'mid', 26, haze=.35)
    hover_car('B', 46, 94, -1, 'rain', 19)
    twinkle()
    window_flicker()
    neon_flicker()
    frame()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description='Draw the level 1 README header.')
    ap.add_argument('-o', '--out', default=os.path.join(here, 'claude-level1.svg'),
                    help='SVG to write (default: next to this script)')
    ap.add_argument('--variant', choices=('animated', 'static', 'overlays'), default='animated',
                    help='static: no animation, for pixel-exact checks; '
                         'overlays: show every hidden overlay, to check their stacking')
    ap.add_argument('--png', help='also write a PNG of the static frame')
    ap.add_argument('--scale', type=int, default=4, help='PNG pixels per art pixel')
    ap.add_argument('--crop', help='PNG crop as x,y,w,h in art pixels')
    args = ap.parse_args()
    build()
    print('%s: %d bytes' % (args.out, write_svg(args.out, args.variant)))
    if args.png:
        crop = tuple(int(v) for v in args.crop.split(',')) if args.crop else None
        write_png(args.png, flatten(LAYERS), args.scale, crop)


if __name__ == '__main__':
    main()
