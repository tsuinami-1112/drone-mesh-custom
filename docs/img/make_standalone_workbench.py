#!/usr/bin/env python3
"""Generates standalone-workbench.svg, the pixel-art header of the standalone
mapper README: a laptop on a hacker's workbench, running the mapper in a dark
room, next to a window whose blinds are half drawn. Beyond them a cyberpunk
city, and drones sweeping it with searchlights; the laptop's map shows their
blips, creeping along the same routes.

Everything is drawn on a 256x144 pixel grid and written out as merged
rectangles with crispEdges, so the SVG stays sharp at any size. A good deal of
CSS animation rides on top (drones, blips, LEDs, the oscilloscope, smoke,
rain); the picture without it is complete, and that is what reduced motion
shows.

    python3 make_standalone_workbench.py                    # rewrite the SVG
    python3 make_standalone_workbench.py --png /tmp/p.png   # also a PNG of the still frame
    python3 make_standalone_workbench.py --png /tmp/p.png --scale 10 --crop 100,40,100,60

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
# layers


# ----------------------------------------------------------------------------
CLIPS = {}      # name -> (x, y, w, h): regions a layer can be cropped to


class Layer:
    """A sparse grid of pixels.

    anim    CSS class(es) that animate the layer; 'h' means hidden until an
            animation shows it (the still frame leaves it out)
    style   inline CSS, normally animation-duration / animation-delay
    groups  nested <g> wrappers, outermost first, each (class, style, uid); a
            drone and its beam share one so they move together
    alpha   draw the whole layer translucent (beams, light stripes)
    clip    name of a CLIPS region the layer is cropped to
    emit    pixels that glow effects must not tint
    """

    def __init__(self, name, anim=None, groups=(), style=None, alpha=None, clip=None):
        self.name = name
        self.anim = anim
        self.groups = tuple(groups)
        self.style = style
        self.alpha = alpha
        self.clip = clip
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
BG = []         # static layers that light effects are allowed to tint


def new_layer(name, **kw):
    L = Layer(name, **kw)
    LAYERS.append(L)
    return L


def layer(name):
    for L in LAYERS:
        if L.name == name:
            return L
    raise KeyError(name)


# ----------------------------------------------------------------------------
# drawing primitives


# ----------------------------------------------------------------------------
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


def line_pts(x0, y0, x1, y1):
    """Bresenham."""
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


def line(L, x0, y0, x1, y1, c, emit=False, dash=None):
    """dash=(on, off) makes a dashed line."""
    for i, (x, y) in enumerate(line_pts(x0, y0, x1, y1)):
        if dash is None or (i % (dash[0] + dash[1])) < dash[0]:
            L.set(x, y, c, emit)


def ell_pts(cx, cy, rx, ry):
    pts = set()
    for y in range(int(cy - ry - 1), int(cy + ry + 2)):
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                pts.add((x, y))
    return pts


def poly_pts(pts):
    """Pixels whose centres fall inside a polygon (even-odd scanline)."""
    ys = [p[1] for p in pts]
    out = set()
    n = len(pts)
    for y in range(int(math.floor(min(ys))), int(math.ceil(max(ys))) + 1):
        yc = y + .5
        xs = []
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            if (y0 <= yc < y1) or (y1 <= yc < y0):
                xs.append(x0 + (yc - y0) * (x1 - x0) / float(y1 - y0))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            for x in range(int(math.ceil(a - .5)), int(math.floor(b - .5)) + 1):
                out.add((x, y))
    return out


def composite_at(layers, x, y):
    for L in reversed(layers):
        c = L.pix.get((x, y))
        if c is not None:
            return L, c
    return None, None


def tint(x, y, color, a, layers=None, max_lum=.66):
    """Blend one visible pixel of the tintable layers toward `color`."""
    L, c = composite_at(layers or BG, x, y)
    if c is None or (x, y) in L.emit or lum(c) > max_lum:
        return
    L.set(x, y, mix(c, color, a))


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
# bitmap font: 3x5 capitals, digits and a little punctuation


# ----------------------------------------------------------------------------
FONT3 = {
    'A': (".#.", "#.#", "###", "#.#", "#.#"),
    'B': ("##.", "#.#", "##.", "#.#", "##."),
    'C': (".##", "#..", "#..", "#..", ".##"),
    'D': ("##.", "#.#", "#.#", "#.#", "##."),
    'E': ("###", "#..", "##.", "#..", "###"),
    'F': ("###", "#..", "##.", "#..", "#.."),
    'G': (".##", "#..", "#.#", "#.#", ".##"),
    'H': ("#.#", "#.#", "###", "#.#", "#.#"),
    'I': ("###", ".#.", ".#.", ".#.", "###"),
    'J': ("..#", "..#", "..#", "#.#", ".#."),
    'K': ("#.#", "#.#", "##.", "#.#", "#.#"),
    'L': ("#..", "#..", "#..", "#..", "###"),
    'M': ("#.#", "###", "###", "#.#", "#.#"),
    'N': ("##.", "#.#", "#.#", "#.#", "#.#"),
    'O': (".#.", "#.#", "#.#", "#.#", ".#."),
    'P': ("##.", "#.#", "##.", "#..", "#.."),
    'Q': (".#.", "#.#", "#.#", "##.", ".##"),
    'R': ("##.", "#.#", "##.", "#.#", "#.#"),
    'S': (".##", "#..", ".#.", "..#", "##."),
    'T': ("###", ".#.", ".#.", ".#.", ".#."),
    'U': ("#.#", "#.#", "#.#", "#.#", "###"),
    'V': ("#.#", "#.#", "#.#", "#.#", ".#."),
    'W': ("#.#", "#.#", "###", "###", "#.#"),
    'X': ("#.#", "#.#", ".#.", "#.#", "#.#"),
    'Y': ("#.#", "#.#", ".#.", ".#.", ".#."),
    'Z': ("###", "..#", ".#.", "#..", "###"),
    '0': ("###", "#.#", "#.#", "#.#", "###"),
    '1': (".#.", "##.", ".#.", ".#.", "###"),
    '2': ("##.", "..#", ".#.", "#..", "###"),
    '3': ("##.", "..#", ".#.", "..#", "##."),
    '4': ("#.#", "#.#", "###", "..#", "..#"),
    '5': ("###", "#..", "##.", "..#", "##."),
    '6': (".##", "#..", "###", "#.#", "###"),
    '7': ("###", "..#", ".#.", ".#.", ".#."),
    '8': ("###", "#.#", "###", "#.#", "###"),
    '9': ("###", "#.#", "###", "..#", "##."),
    '-': ("...", "...", "###", "...", "..."),
    '.': ("...", "...", "...", "...", ".#."),
    ':': ("...", ".#.", "...", ".#.", "..."),
    '>': ("#..", ".#.", "..#", ".#.", "#.."),
    '$': (".##", "##.", ".#.", ".##", "##."),
    '_': ("...", "...", "...", "...", "###"),
    '/': ("..#", "..#", ".#.", "#..", "#.."),
    '+': ("...", ".#.", "###", ".#.", "..."),
    '!': (".#.", ".#.", ".#.", "...", ".#."),
    ' ': ("..", "..", "..", "..", ".."),
}


def text3(L, x, y, s, c, emit=False, vertical=False):
    """3x5 text, one letter per column or (vertical) per row."""
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


def text3_width(s):
    return sum(len(FONT3[ch][0]) + 1 for ch in s) - 1


# ----------------------------------------------------------------------------
# CSS: pieces register their rules as they are used


# ----------------------------------------------------------------------------
CSS = []
STEP = 'steps(1,end) infinite'


def add_css(rule):
    if rule not in CSS:
        CSS.append(rule)


def keyframes(name, frames):
    """frames: {percent: 'css declarations'}"""
    return '@keyframes %s{%s}' % (name, ''.join('%g%%{%s}' % (float(p), d)
                                                for p, d in sorted(frames.items(), key=lambda kv: float(kv[0]))))


def seq_frames(n, period, phase=0.0, name='q'):
    """Class/style pairs for an n-frame loop where frame s shows during the
    s-th slice of every `period` seconds, `phase` seconds late. Frame 0 is the
    still frame."""
    cls = '%s%d' % (name, n)
    add_css('.%s{animation:%s 1s %s}' % (cls, cls, STEP))
    add_css(keyframes(cls, {0: 'opacity:1', '%.3f' % (100.0 / n): 'opacity:0'}))
    out = []
    for s in range(n):
        delay = ((n - s) % n) * period / float(n) + phase
        out.append((cls if s == 0 else cls + ' h',
                    'animation-duration:%gs;animation-delay:-%gs' % (period, delay)))
    return out


def pulse(name, duty, period):
    """Visible for `duty` of each cycle, then off; returns (class, style)."""
    cls = 'pu%d' % round(duty * 100)
    add_css('.%s{animation:%s 1s %s}' % (cls, cls, STEP))
    add_css(keyframes(cls, {0: 'opacity:1', '%.1f' % (duty * 100): 'opacity:0'}))
    return cls, 'animation-duration:%gs' % period


def track(name, points, period, ease='ease-in-out'):
    """A looping route: points are (fraction of the period, dx, dy)."""
    frames = {}
    for (t, dx, dy) in points:
        frames['%.2f' % (t * 100)] = 'transform:translate(%.2fpx,%.2fpx)' % (dx, dy)
    add_css('.%s{animation:%s %gs %s infinite}' % (name, name, period, ease))
    add_css(keyframes(name, frames))
    return name


def css(variant='animated'):
    if variant == 'static':          # nothing moves: the picture a still frame shows
        return '.h{opacity:0}'
    if variant == 'overlays':        # debugging aid: show every hidden overlay
        return '.h{opacity:1}'
    return '.h{opacity:0}' + ''.join(CSS) + \
        '@media (prefers-reduced-motion:reduce){*{animation:none!important}}'


# ----------------------------------------------------------------------------
# still-frame preview


# ----------------------------------------------------------------------------
def hidden_by_default(L):
    return 'h' in (L.anim or '').split()


def flatten(layers):
    """The still frame: what you see before (or without) any animation."""
    img = {}
    for L in layers:
        if hidden_by_default(L):
            continue
        clip = CLIPS.get(L.clip)
        for p, c in L.pix.items():
            if clip and not (clip[0] <= p[0] < clip[0] + clip[2] and clip[1] <= p[1] < clip[1] + clip[3]):
                continue
            if L.alpha is not None:
                c = mix(img.get(p, (0, 0, 0)), c, L.alpha)
            img[p] = c
    return img


def write_png(path, img, scale=4, crop=None, bg=(13, 17, 23)):
    x0, y0, cw, ch = crop or (0, 0, W, H)
    rows = []
    for y in range(y0, y0 + ch):
        row = bytearray()
        for x in range(x0, x0 + cw):
            r, g, b = img.get((x, y), bg)
            row += bytes((r, g, b)) * scale
        rows.extend([b'\x00' + bytes(row)] * scale)
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


def emit_one(L):
    """A layer that needs its own wrapper: animated, styled or translucent."""
    out = emit_run([L])
    if L.anim or L.style:
        out = '<g%s>%s</g>' % (attrs(L.anim, L.style), out)
    if L.alpha is not None:
        out = '<g style="opacity:%g">%s</g>' % (L.alpha, out)
    return out


def emit_nodes(layers, depth=0):
    """Consecutive plain layers are flattened into one block; animated or
    translucent layers and groups keep their own wrapper."""
    out, run, i = [], [], 0

    def flush():
        if run:
            out.append(emit_run(run))
            run.clear()

    while i < len(layers):
        L = layers[i]
        if len(L.groups) > depth:
            flush()
            g = L.groups[depth]
            j = i
            while j < len(layers) and len(layers[j].groups) > depth and layers[j].groups[depth] == g:
                j += 1
            out.append('<g%s>%s</g>' % (attrs(g[0], g[1]), emit_nodes(layers[i:j], depth + 1)))
            i = j
        elif L.anim or L.style or L.alpha is not None:
            flush()
            out.append(emit_one(L))
            i += 1
        else:
            run.append(L)
            i += 1
    flush()
    return ''.join(out)


def emit_layers(layers):
    """Wrap runs of layers that share a clip region, then emit each run."""
    layers = [L for L in layers if L.pix]
    out, i = [], 0
    while i < len(layers):
        j = i
        while j < len(layers) and layers[j].clip == layers[i].clip:
            j += 1
        body = emit_nodes(layers[i:j])
        out.append('<g clip-path="url(#clip-%s)">%s</g>' % (layers[i].clip, body)
                   if layers[i].clip else body)
        i = j
    return ''.join(out)


def clip_defs():
    return '<defs>%s</defs>' % ''.join(
        '<clipPath id="clip-%s"><rect x="%d" y="%d" width="%d" height="%d"/></clipPath>' % ((n,) + r)
        for n, r in sorted(CLIPS.items())) if CLIPS else ''


TITLE = 'A laptop in a dark makerspace, tracking drones'
DESC = ('Pixel art: a dark hacker workbench crowded with electronics, lit by a laptop running the '
        'drone mesh mapper. Beside it a window with half-drawn blinds looks over a cyberpunk city '
        'at night, where drones sweep searchlights back and forth. Their blips drift slowly across '
        'the laptop\'s map.')


def write_svg(path, variant='animated'):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'shape-rendering="crispEdges" role="img" aria-labelledby="t d">'
           '<title id="t">%s</title><desc id="d">%s</desc>%s<style>%s</style>%s</svg>\n'
           % (W, H, W * 3, H * 3, TITLE, DESC, clip_defs(), css(variant), emit_layers(LAYERS)))
    with open(path, 'w') as f:
        f.write(svg)
    return len(svg)


# ----------------------------------------------------------------------------
# palette


# ----------------------------------------------------------------------------
SKY = [C(h) for h in ('#06041a', '#0b0826', '#110c35', '#1a1049', '#26145c',
                      '#37186c', '#4e1a79', '#6d1f82', '#922786', '#b93484',
                      '#dd4a82', '#f4687e')]
FAR_R = [C(h) for h in ('#2d1a5c', '#381c68', '#452073', '#55257e', '#692c88', '#7e3492')]
MID_R = [C(h) for h in ('#160f3a', '#1c1046', '#231252', '#2c155e', '#37186a', '#431c76')]
NEAR_R = [C(h) for h in ('#0a0a22', '#0c0b28', '#0f0e30', '#131238', '#181642', '#1e1a4c')]

PINK, PINK_D = C('#ff4fd8'), C('#a81f8c')
CYAN, CYAN_D = C('#5ff3ff'), C('#1c97b4')
WARM = [C('#ffd37a'), C('#ffa94d'), C('#fff0b8')]
COOL = [C('#6ef3ff'), C('#3fb6ff'), C('#a6e2ff')]
HOT = [C('#ff6ad5'), C('#ff3d9a')]
WIN_MIXES = [WARM, WARM, COOL, COOL, WARM + COOL, WARM + HOT, COOL + HOT]

# the four drones and the colours the mapper gives them
LIME, ORANGE, RED, TEAL = C('#88ff99'), C('#ffaa33'), C('#ff5577'), C('#22ddb0')

# window glass, in picture pixels
GX0, GY0, GW, GH = 12, 18, 87, 65
CLIPS['win'] = (GX0, GY0, GW, GH)
GX1, GY1 = GX0 + GW - 1, GY0 + GH - 1
BENCH_Y = 98        # where the bench top meets the wall
FRONT_Y = 133       # front edge of the bench top


# ----------------------------------------------------------------------------
# the room: brick wall and the bench


# ----------------------------------------------------------------------------
def wall():
    L = new_layer('wall')
    BG.append(L)
    rng = Rng(3)
    base = [C('#0f0f26'), C('#13132d'), C('#181835')]
    mortar = C('#0a0a1b')
    for y in range(0, BENCH_Y):
        row = y // 4
        off = 0 if row % 2 == 0 else 5
        for x in range(W):
            if y % 4 == 3:
                L.set(x, y, mortar)
            elif (x + off) % 10 == 9:
                L.set(x, y, mortar)
            else:
                brick = ((x + off) // 10, row)
                t = Rng(brick[0] * 977 + brick[1] * 131 + 7).random()
                L.set(x, y, base[0] if t < .45 else (base[1] if t < .85 else base[2]))
    return L


BENCH_R = [C('#1b1320'), C('#231a2a'), C('#2b2034'), C('#33263d')]


def bench():
    L = new_layer('bench')
    BG.append(L)
    rng = Rng(21)
    back, front = BENCH_Y, FRONT_Y
    # the work surface: planks running left to right, lighter toward the viewer
    for y in range(back, front):
        t = (y - back) / float(front - back)
        for x in range(W):
            L.set(x, y, ramp_at(BENCH_R, t * 3, x, y, .5))
    for y in (back + 8, back + 17, back + 25):              # plank seams
        hline(L, 0, W - 1, y, C('#120c18'))
        hline(L, 0, W - 1, y + 1, C('#3a2c44'))
    for x0, y0, y1 in ((38, back, back + 8), (170, back + 9, back + 17), (96, back + 18, back + 25),
                       (226, back + 26, front - 1)):
        vline(L, x0, y0, y1, C('#120c18'))
    for _ in range(90):                                      # scratches and grime
        x, y = rng.randint(0, W - 1), rng.randint(back, front - 1)
        w = rng.randint(2, 6)
        hline(L, x, x + w, y, C('#150e1b') if rng.chance(.6) else C('#3d2e48'))
    hline(L, 0, W - 1, back, C('#0a0713'))                   # shadow where bench meets wall
    hline(L, 0, W - 1, back + 1, C('#16101c'))
    # front edge, apron with drawers
    hline(L, 0, W - 1, front, C('#4a3858'))
    hline(L, 0, W - 1, front + 1, C('#2e2238'))
    rect(L, 0, front + 2, W, H - front - 2, C('#150f1a'))
    for x0 in (0, 86, 172):
        rect(L, x0 + 3, front + 3, 80, H - front - 4, C('#1b1422'))
        hline(L, x0 + 3, x0 + 82, front + 3, C('#34283f'))
        vline(L, x0 + 3, front + 3, H - 2, C('#241b2d'))
        vline(L, x0 + 82, front + 3, H - 2, C('#0f0a14'))
    return L


# ----------------------------------------------------------------------------
# the city beyond the window


# ----------------------------------------------------------------------------
SIGN_X = (79, 46)          # x of the two neon signs (their left letters)
SKY_STOPS = [(GY0, 1.0), (GY0 + 14, 3.0), (GY0 + 30, 6.0), (GY0 + 44, 8.8), (GY1, 11.0)]
STYLES = ['flat', 'flat', 'step', 'step3', 'slantL', 'slantR', 'spire', 'antenna', 'dome']


def make_specs(rng, x0, x1, wr, tr, gap=(-2, 1), styles=STYLES):
    specs = []
    x = x0
    while x < x1:
        w = rng.randint(*wr)
        specs.append(dict(x=x, w=w, top=rng.randint(*tr), style=rng.choice(styles),
                          seed=rng.randint(0, 1 << 30)))
        x += w + rng.randint(*gap)
    return specs


def silhouette(sp, base, rng):
    x, w, top, style = sp['x'], sp['w'], sp['top'], sp['style']
    x1 = x + w - 1
    pts, tiers = set(), []

    def R(a, b, c, d, win=True):
        for yy in range(b, d + 1):
            for xx in range(a, c + 1):
                pts.add((xx, yy))
        if win:
            tiers.append((a, b, c, d))

    h = base - top
    if style in ('flat', 'antenna'):
        R(x, top, x1, base)
    elif style == 'step':
        t = top + max(5, int(h * (.18 + .2 * rng.random())))
        ins = max(2, w // 5)
        R(x, t, x1, base)
        R(x + ins, top, x1 - ins, t - 1)
    elif style == 'step3':
        t1 = top + max(4, int(h * .2))
        t2 = t1 + max(4, int(h * .22))
        ins = max(1, w // 7)
        R(x, t2, x1, base)
        R(x + ins, t1, x1 - ins, t2 - 1)
        R(x + 2 * ins, top, x1 - 2 * ins, t1 - 1)
    elif style in ('slantL', 'slantR'):
        cut = min(w - 3, 3 + rng.randint(0, 3))
        for k in range(w):
            kk = k if style == 'slantL' else w - 1 - k
            R(x + k, top + max(0, cut - kk), x + k, base, win=False)
        tiers.append((x, top + cut, x1, base))
    elif style == 'spire':
        sw = max(3, w // 3)
        sx = x + (w - sw) // 2
        stop = top + max(6, int(h * .3))
        R(x, stop, x1, base)
        R(sx, top + 5, sx + sw - 1, stop - 1)
        for k in range(4):
            R(sx + k // 2, top + 5 - k - 1, sx + sw - 1 - k // 2, top + 5 - k - 1, win=False)
        for yy in range(top - 6, top):
            pts.add((sx + sw // 2, yy))
    elif style == 'dome':
        ry = min(6, w // 2)
        for k in range(w):
            t = int(round(ry * (1 - math.sqrt(max(0.0, 1 - ((k - (w - 1) / 2.0) / (w / 2.0)) ** 2)))))
            R(x + k, top + t, x + k, base, win=False)
        tiers.append((x, top + ry, x1, base))
    if style == 'antenna':
        cx = x + rng.randint(1, max(1, w - 2))
        for yy in range(top - rng.randint(4, 9), top):
            pts.add((cx, yy))
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


def draw_skyline(name, specs, base, ramp, ys, rim, top_edge, cfg, fog=None):
    L = new_layer(name, clip='win')
    BG.append(L)
    for sp in specs:
        r = Rng(sp['seed'])
        pts, tiers = silhouette(sp, base, r)
        pts = {p for p in pts if GX0 <= p[0] <= GX1 and GY0 <= p[1] <= GY1}
        for (x, y) in pts:
            L.set(x, y, ramp_at(ramp, piecewise(ys, y), x, y, .3))
        facing = 1 if sp['x'] + sp['w'] / 2.0 < GX0 + GW * .6 else -1
        for (x, y) in pts:
            if (x, y - 1) not in pts:
                L.set(x, y, top_edge)
            elif (x + facing, y) not in pts:
                L.set(x, y, rim)
        place_windows(L, pts, tiers, r, cfg, fog)
    return L


def city():
    sky = new_layer('sky', clip='win')
    BG.append(sky)
    for y in range(GY0, GY1 + 1):
        u = piecewise(SKY_STOPS, y)
        for x in range(GX0, GX1 + 1):
            sky.set(x, y, ramp_at(SKY, u, x, y, .34))
    rng = Rng(7)
    for _ in range(26):
        sky.set(rng.randint(GX0 + 1, GX1 - 1), rng.randint(GY0 + 1, GY0 + 34),
                rng.choice([C('#5b4aa0'), C('#9a8be0')]), True)
    rng = Rng(1112)
    far = make_specs(rng, GX0 - 4, GX1 + 6, (7, 12), (52, 66), gap=(-2, 0),
                     styles=['flat', 'step', 'step3', 'spire', 'antenna', 'slantL', 'slantR'])
    draw_skyline('far', far, GY1 + 2, FAR_R, [(GY0 + 14, 0.0), (GY1, 5.0)],
                 C('#8a3f9e'), C('#6f3496'), dict(w=1, h=1, px=3, py=4, dens=.16), fog=(C('#8a3a98'), .35))
    mid = make_specs(rng, GX0 - 6, GX1 + 6, (9, 16), (58, 72), gap=(-3, 1))
    for sx in SIGN_X:                         # towers tall enough to carry a sign
        for sp in mid:
            if sp['x'] <= sx < sp['x'] + sp['w']:
                sp.update(x=sx - 4, w=13, top=52, style='flat')
    draw_skyline('mid', mid, GY1 + 2, MID_R, [(GY0 + 20, 0.0), (GY1, 5.0)],
                 C('#6a3aa6'), C('#4a2a86'), dict(w=1, h=2, px=3, py=4, dens=.26), fog=(C('#6a2a84'), .15))
    signs = new_layer('city-signs', clip='win')
    BG.append(signs)
    for (x, text, col, dim) in ((SIGN_X[0], 'BAR', PINK, PINK_D), (SIGN_X[1], 'GO', CYAN, CYAN_D)):
        neon_sign_v(signs, x, 56, text, col, dim)
        if text == 'BAR':
            cls, style = flicker(3.7)
            f = new_layer('sign-flicker', anim=cls, style=style, clip='win')
            text3(f, x, 56 + 6, 'A', mix(dim, C('#0b0820'), .35), emit=True)
    air_car('a', GY0 + 36, 21, 1)
    near = make_specs(rng, GX0 - 8, GX1 + 6, (11, 20), (68, 78), gap=(-3, 0))
    draw_skyline('near', near, GY1 + 2, NEAR_R, [(GY0 + 30, 0.0), (GY1, 5.0)],
                 C('#2f4aa8'), C('#27348a'), dict(w=2, h=2, px=4, py=5, dens=.30))
    glow([sky, layer('far')], GX0 + 56, GY1 - 8, 40, (255, 98, 150), amax=.5, levels=3,
         falloff=1.2, ex=1.5, ey=.7, skip_lum=.8)


# ----------------------------------------------------------------------------
# street life: neon, traffic, rain on the glass


# ----------------------------------------------------------------------------
def neon_sign_v(L, x, y, text, col, dim):
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
    glow(BG, x + 1, y + h // 2, 1, col, amax=.5, levels=3, falloff=.8, ex=10, ey=h / 2.0 + 7)


def air_car(name, y, seconds, direction):
    """A little air-car crossing the whole window."""
    start = GX0 - 9 if direction > 0 else GX1 + 3
    trk = track('car' + name, [(0, 0, 0), (1, direction * (GW + 14), 0)], seconds, ease='linear')
    L = new_layer('car-' + name, groups=((trk, '', 'car' + name),), clip='win')
    hull = C('#5a47c0')
    for j, (ox, wd) in enumerate(((2, 4), (1, 6), (0, 7))):
        for i in range(wd):
            xx = ox + i if direction > 0 else 6 - ox - i
            L.set(start + xx, y + j, C('#b9a6ff') if j == 0 else hull)
    front = start + (7 if direction > 0 else -1)
    back = start + (-1 if direction > 0 else 7)
    L.set(front, y + 2, C('#fff6c0'), True)
    L.set(back, y + 2, C('#ff3355'), True)
    for k in range(2, 5):
        L.set(back - direction * (k - 1), y + 2, mix(C('#ff3355'), C('#1a1040'), .4 + .15 * k), True)


def window_rain():
    """Raindrops sliding down the glass: one tile repeating every 30 px."""
    P = 30
    rng = Rng(404)
    L = new_layer('rain', anim='rain', alpha=.55, clip='win')
    add_css('.rain{animation:rain 1.5s linear infinite}')
    add_css(keyframes('rain', {100: 'transform:translateY(%dpx)' % P}))
    tile = [(rng.randint(GX0, GX1), rng.randint(0, P - 1)) for _ in range(9)]
    for k in range(-1, 4):
        for (x, y) in tile:
            for i in range(4):
                L.set(x, y + P * k + i + 18, C('#d6e8ff') if i == 3 else C('#8fb0e8'))


def glass_glare():
    L = new_layer('glare', alpha=.07, clip='win')
    for pts in (((GX0 + 6, GY0), (GX0 + 20, GY0), (GX0 + 52, GY1), (GX0 + 38, GY1)),
                ((GX0 + 24, GY0), (GX0 + 29, GY0), (GX0 + 61, GY1), (GX0 + 56, GY1))):
        for p in poly_pts(list(pts)):
            L.set(p[0], p[1], C('#ffffff'))


# ----------------------------------------------------------------------------
# drones sweeping the city


# ----------------------------------------------------------------------------
DP = dict(o=C('#0f1328'), a=C('#1d2440'), b=C('#2b3660'), c=C('#40508a'),
          d=C('#6679b8'), e=C('#a4b8f0'), f=C('#e8f0ff'))
ROTOR_HI, ROTOR_LO = C('#d6e2ff'), C('#6b80c4')
LAMP = C('#fffbe0')

# Each drone flies a looping route (fractions of the period, then x and y in
# -1..1). The window shows it at full size and the mapper's blip follows the
# same route, slowly, so the two stay in step.
ROUTES = {
    'd1': dict(pts=[(0, 0, 0), (.25, -1, -.2), (.5, 0, .12), (.75, 1, -.2), (1, 0, 0)], period=18),
    'd2': dict(pts=[(0, 0, 0), (.33, 1, .35), (.66, -1, .2), (1, 0, 0)], period=13),
    'd3': dict(pts=[(0, 0, 0), (.5, -1, -.4), (1, 0, 0)], period=10),
    'd4': dict(pts=[(0, 0, 0), (.25, .7, .8), (.5, 0, 0), (.75, -.7, .8), (1, 0, 0)], period=15),
}


def route_track(name, scale, suffix):
    r = ROUTES[name]
    pts = [(t, nx * scale[0], ny * scale[1]) for (t, nx, ny) in r['pts']]
    return track(name + suffix, pts, r['period'])


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


def drone(name, cx, y0, size, color, groups):
    """size: 'M' 26 wide, 'S' 16, 'X' 9. Returns the lamp position. The arm
    LEDs wear the colour the mapper gives this drone."""
    wd = dict(M=26, S=16, X=9)[size]
    x0 = cx - wd // 2
    P = DP
    kw = dict(groups=groups, clip='win')
    body = new_layer('drone-' + name, **kw)
    spin = size == 'M'
    (ca, sa), (cb, sb) = seq_frames(2, .12)
    pa = new_layer('drone-%s-rotor-a' % name, anim=ca if spin else None, style=sa if spin else None, **kw)
    pb = new_layer('drone-%s-rotor-b' % name, anim=cb, style=sb, **kw)
    pcls, pstyle = pulse('led', .5, 1.3)
    led = new_layer('drone-%s-led' % name, anim=pcls,
                    style=pstyle + ';animation-delay:-%.1fs' % ((cx % 7) * .17), **kw)
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
        sym_rect(body, x0, y0, wd, 11, 9, 12, 9, LAMP, True)
        sym_rect(body, x0, y0, wd, 9, 8, 9, 10, P['b'])
        sym_set(led, x0, y0, wd, 2, 4, color, True)
        sym_set(led, x0, y0, wd, 12, 6, color, True)
        rotors(pa, pb, x0, y0, wd, (4,), 9)
        lamp = (cx, y0 + 9)
    elif size == 'S':
        sym_rect(body, x0, y0, wd, 1, 2, 4, 3, P['b'])
        sym_rect(body, x0, y0, wd, 1, 2, 4, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 5, 3, P['c'])
        sym_rect(body, x0, y0, wd, 5, 2, 7, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 7, 4, P['b'])
        sym_rect(body, x0, y0, wd, 6, 5, 7, 5, LAMP, True)
        sym_set(led, x0, y0, wd, 1, 3, color, True)
        sym_set(led, x0, y0, wd, 7, 4, color, True)
        rotors(pa, pb, x0, y0, wd, (2,), 5)
        pb.pix.clear()
        lamp = (cx, y0 + 5)
    else:
        sym_rect(body, x0, y0, wd, 2, 2, 4, 2, P['c'])
        sym_rect(body, x0, y0, wd, 3, 3, 4, 3, LAMP, True)
        sym_rect(body, x0, y0, wd, 0, 1, 1, 1, P['d'])
        sym_set(led, x0, y0, wd, 0, 2, color, True)
        pb.pix.clear()
        lamp = (cx, y0 + 3)
    # a soft halo of the drone's colour around the lamp
    halo = new_layer('drone-%s-halo' % name, alpha=.28, **kw)
    for (dx, dy) in ((0, 0), (-1, 0), (1, 0), (0, 1), (0, -1), (-1, 1), (1, 1), (-2, 0), (2, 0), (0, 2)):
        halo.set(lamp[0] + dx, lamp[1] + dy, mix(color, (255, 255, 255), .3))
    return lamp


def searchlight(name, apex, length, color, groups, period=3.6, phase=0.0):
    """A cone of light that sweeps back and forth: eight frames, each a soft
    cone, a brighter core and a bright spot where it lands. The far end fades
    out through dithering."""
    angles = (-30, -15, 0, 15, 30, 15, 0, -15)
    frames = seq_frames(len(angles), period, phase)
    light = mix((255, 248, 225), color, .18)
    soft = mix(color, (255, 255, 255), .18)
    spotc = mix((255, 255, 255), color, .35)
    ax, ay = apex[0] + .5, apex[1] + 1.0

    def cone(ang, half, ln):
        pts = [(ax, ay)] + [(ax + ln * math.sin(math.radians(ang + d)),
                             ay + ln * math.cos(math.radians(ang + d))) for d in (-half, half)]
        keep = set()
        for (x, y) in poly_pts(pts):
            t = math.hypot(x + .5 - ax, y + .5 - ay) / float(ln)
            if t < .45 or (t < .75 and (x + y) % 2 == 0) or (t < 1.05 and x % 2 == 0 and y % 2 == 0):
                keep.add((x, y))
        return keep

    for s_, ang in enumerate(angles):
        cls, style = frames[s_]
        outer = new_layer('beam-%s-%d-soft' % (name, s_), anim=cls, style=style, groups=groups,
                          alpha=.27, clip='win')
        core = new_layer('beam-%s-%d-core' % (name, s_), anim=cls, style=style, groups=groups,
                         alpha=.42, clip='win')
        spot = new_layer('beam-%s-%d-spot' % (name, s_), anim=cls, style=style, groups=groups,
                         alpha=.7, clip='win')
        for p in cone(ang, 9, length):
            outer.set(p[0], p[1], soft)
        for p in cone(ang, 3.2, length * 1.02):
            core.set(p[0], p[1], light)
        ex = ax + length * .96 * math.sin(math.radians(ang))
        ey = ay + length * .96 * math.cos(math.radians(ang))
        for p in ell_pts(ex, ey, 3.2, 1.5):
            spot.set(p[0], p[1], spotc)


def window_drones():
    plan = (
        # name, size, colour, window cx, y0, window travel, beam length
        ('d3', 'S', RED, 46, 63, (18, 6), 16),
        ('d4', 'X', TEAL, 71, 54, (12, 5), 9),
        ('d2', 'S', ORANGE, 82, 58, (22, 5), 17),
        ('d1', 'M', LIME, 30, 58, (22, 4), 22),
    )
    add_css('.bob{animation:bob 3.4s %s}' % STEP)             # a pixel up, a pixel down
    add_css(keyframes('bob', {0: 'transform:translateY(0)', 25: 'transform:translateY(1px)',
                              50: 'transform:translateY(0)', 75: 'transform:translateY(-1px)'}))
    for k, (name, size, color, cx, y0, amp, blen) in enumerate(plan):
        fly = (route_track(name, amp, 'w'), '', name + 'w')
        bob = ('bob', 'animation-delay:-%.1fs;animation-duration:%.1fs' % (k * .9, 3.0 + k * .4), name + 'b')
        groups = (fly, bob)
        lamp = drone(name, cx, y0, size, color, groups)
        searchlight(name, lamp, blen, color, groups, period=3.6 + k * .4, phase=k * 1.1)


# ----------------------------------------------------------------------------
# the window: frame, mullion, sill and the half-drawn blinds


# ----------------------------------------------------------------------------
FRAME, FRAME_HI, FRAME_LO = C('#1a1f35'), C('#34406a'), C('#0e1122')
BLIND_BOTTOM = 47          # y of the lower rail of the drawn blinds


def window_frame():
    L = new_layer('window-frame')
    BG.append(L)
    ox0, oy0, ox1, oy1 = GX0 - 4, GY0 - 4, GX1 + 4, GY1 + 4
    for y in range(oy0, oy1 + 1):
        for x in range(ox0, ox1 + 1):
            if GX0 <= x <= GX1 and GY0 <= y <= GY1:
                continue
            L.set(x, y, FRAME)
    hline(L, ox0, ox1, oy0, FRAME_HI)
    vline(L, ox0, oy0, oy1, FRAME_HI)
    vline(L, ox1, oy0, oy1, FRAME_LO)
    hline(L, ox0 + 1, ox1, oy1, FRAME_LO)
    for x in range(GX0 - 1, GX1 + 2):                  # inner bevel
        L.set(x, GY0 - 1, FRAME_LO)
    for y in range(GY0, GY1 + 2):
        L.set(GX0 - 1, y, FRAME_LO)
        L.set(GX1 + 1, y, FRAME_HI)
    mx = GX0 + GW // 2                                  # mullion
    rect(L, mx - 1, GY0, 3, GH, FRAME)
    vline(L, mx - 1, GY0, GY1, FRAME_HI)
    vline(L, mx + 1, GY0, GY1, FRAME_LO)
    # sill sticking out below the frame
    rect(L, ox0 - 3, oy1 + 1, ox1 - ox0 + 7, 3, C('#2b3050'))
    hline(L, ox0 - 3, ox1 + 3, oy1 + 1, C('#4a5486'))
    hline(L, ox0 - 3, ox1 + 3, oy1 + 3, C('#161a30'))
    return L


def blinds():
    """Venetian blinds hanging from a head rail, drawn about two thirds of the
    way down, slats a little open. One slat is bent, as there always is."""
    L = new_layer('blinds')
    top = GY0
    rail_hi, rail, rail_lo = C('#4a5486'), C('#2f365c'), C('#171b33')
    rect(L, GX0 - 1, top - 3, GW + 2, 4, rail)
    hline(L, GX0 - 1, GX1 + 1, top - 3, rail_hi)
    hline(L, GX0 - 1, GX1 + 1, top, rail_lo)
    slat = [C('#4b5388'), C('#323a66'), C('#1f2445')]
    y = top + 1
    n = 0
    while y + 3 <= BLIND_BOTTOM - 3:
        for x in range(GX0, GX1 + 1):
            dy = 0
            if n == 5 and x > GX0 + 50:                 # the bent slat droops at the right
                dy = 1 + (x - (GX0 + 50)) // 12
            if n == 6 and x < GX0 + 8:
                dy = -1
            for j in range(3):
                L.set(x, y + j + dy, slat[j])
        y += 4
        n += 1
    # lower rail, with its cap and the pull cord
    ry = BLIND_BOTTOM - 2
    rect(L, GX0 - 1, ry, GW + 2, 3, rail)
    hline(L, GX0 - 1, GX1 + 1, ry, rail_hi)
    hline(L, GX0 - 1, GX1 + 1, ry + 2, rail_lo)
    cx = GX1 - 8
    vline(L, cx, ry + 3, ry + 22, C('#c9cde8'))
    vline(L, cx + 1, ry + 3, ry + 22, C('#6c7098'))
    rect(L, cx - 1, ry + 23, 4, 3, C('#e8d27a'))
    hline(L, cx - 1, cx + 2, ry + 25, C('#a8903c'))
    return L


# ----------------------------------------------------------------------------
# the laptop running the mapper


# ----------------------------------------------------------------------------
# display area of the screen; the bezel is two pixels around it
SX0, SX1, SY0, SY1 = 118, 194, 52, 97
MX0, MX1, MY0, MY1 = SX0, SX1, SY0 + 6, SY0 + 37      # map pane
MAP_BASE = C('#090d13')
UI_PANEL, UI_EDGE = C('#10151b'), C('#243040')
UI_LIME = C('#88ff99')

# where each blip sits on the map, and how far it roams (a fraction of the
# window drone's travel, so it creeps along the same route)
BLIPS = {
    'd1': dict(color=LIME, at=(131, 68), amp=(6.6, 1.2)),
    'd4': dict(color=TEAL, at=(147, 63), amp=(3.6, 1.5)),
    'd3': dict(color=RED, at=(149, 77), amp=(5.4, 1.8)),
    'd2': dict(color=ORANGE, at=(161, 69), amp=(6.6, 1.5)),
}


def quad_icon(L, cx, cy, color):
    """The mapper's quadcopter glyph: four rotors round a hub."""
    bright = mix(color, (255, 255, 255), .45)
    for (ox, oy) in ((-3, -3), (2, -3), (-3, 2), (2, 2)):
        rect(L, cx + ox, cy + oy, 2, 2, color)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            L.set(cx + dx, cy + dy, color)
    L.set(cx, cy, bright)


def ring_pts(cx, cy, r):
    pts = set()
    for a in range(0, 360, 6):
        pts.add((int(round(cx + r * math.cos(math.radians(a)))),
                 int(round(cy + r * math.sin(math.radians(a))))))
    return pts


def screen_map():
    """A dark street map: river, blocks, a park and streets."""
    L = new_layer('screen-map')
    rng = Rng(77)
    rect(L, MX0, MY0, MX1 - MX0 + 1, MY1 - MY0 + 1, MAP_BASE)
    street, avenue = C('#16222f'), C('#1f3248')
    block = [C('#0d1620'), C('#101b27'), C('#0b131c')]
    for yy in range(MY0 + 3, MY1, 10):
        hline(L, MX0, MX1, yy, street)
    for xx in range(MX0 + 6, MX1, 14):
        vline(L, xx, MY0, MY1, street)
    hline(L, MX0, MX1, MY0 + 13, avenue)                    # one broad avenue
    hline(L, MX0, MX1, MY0 + 14, avenue)
    for bx in range(MX0 + 7, MX1 - 7, 14):          # blocks of buildings
        for by in range(MY0 + 4, MY1 - 6, 10):
            if rng.chance(.7):
                rect(L, bx + 1, by + 1, 11, 8, rng.choice(block))
    # a park and the river
    for p in ell_pts(MX0 + 18, MY1 - 6, 11, 5):
        L.set(p[0], p[1], C('#0b2119'))
    river = line_pts(MX1, MY0 + 2, MX1 - 22, MY0 + 7) + line_pts(MX1 - 22, MY0 + 7, MX0 + 36, MY0 + 18) + \
        line_pts(MX0 + 36, MY0 + 18, MX0 + 6, MY1)
    for (x, y) in river:
        for dy in range(-2, 3):
            L.set(x, y + dy, C('#0c2a42') if abs(dy) < 2 else C('#12385a'))
    for _ in range(24):                              # street lights, labels
        x, y = rng.randint(MX0 + 1, MX1 - 1), rng.randint(MY0 + 1, MY1 - 1)
        hline(L, x, x + rng.randint(1, 3), y, C('#27384c'))


def banner_ticker():
    """The alert banner's text scrolls past, like a ticker."""
    words = (4, 2, 5, 3, 6, 2, 4, 3)
    pattern = []
    for wd in words:
        pattern += [True] * wd + [False] * 2
    frames = seq_frames(4, 3.2)
    for k in range(4):
        cls, style = frames[k]
        L = new_layer('ticker-%d' % k, anim=cls, style=style)
        for i, x in enumerate(range(129, 183)):
            if pattern[(i + 3 * k) % len(pattern)]:
                L.set(x, SY0 + 2, C('#7dff8a'))
                L.set(x, SY0 + 3, C('#2fbf50'))


def screen_glare():
    L = new_layer('screen-glare', alpha=.06)
    for pts in (((150, SY0), (166, SY0), (140, SY1), (124, SY1)), ((170, SY0), (176, SY0), (150, SY1), (144, SY1))):
        for p in poly_pts(list(pts)):
            if SX0 <= p[0] <= SX1:
                L.set(p[0], p[1], C('#ffffff'))


def screen_ui():
    """Chrome of the mapper page that sits over the map and the blips: alert
    banner, the Active Drones panel, buttons, and the terminal running the
    mapper."""
    L = new_layer('screen-ui')
    rect(L, SX0, SY0, SX1 - SX0 + 1, 6, C('#05070b'))                 # top strip
    # green alert banner, like the mapper's "Possible drone" strip
    rect(L, 127, SY0 + 1, 58, 4, C('#003700'))
    hline(L, 127, 184, SY0 + 1, C('#00b33c'))
    hline(L, 127, 184, SY0 + 4, C('#00b33c'))
    # left toggle and zoom buttons
    rect(L, SX0 + 2, MY0 + 2, 7, 3, UI_PANEL)
    hline(L, SX0 + 2, SX0 + 8, MY0 + 2, UI_EDGE)
    hline(L, SX0 + 3, SX0 + 5, MY0 + 3, C('#5a6a82'))
    rect(L, SX0 + 2, MY1 - 8, 4, 7, UI_PANEL)
    hline(L, SX0 + 3, SX0 + 4, MY1 - 6, C('#8aa0ba'))
    hline(L, SX0 + 3, SX0 + 4, MY1 - 3, C('#8aa0ba'))
    # right-hand panel: the active drones, one box per drone in its own colour
    px0, px1, py0, py1 = 167, SX1 - 1, MY0 + 1, MY1 - 6
    rect(L, px0, py0, px1 - px0 + 1, py1 - py0 + 1, UI_PANEL)
    for x in range(px0, px1 + 1):
        L.set(x, py0, UI_EDGE)
        L.set(x, py1, UI_EDGE)
    for y in range(py0, py1 + 1):
        L.set(px0, y, UI_EDGE)
        L.set(px1, y, UI_EDGE)
    text3(L, px0 + 3, py0 + 2, 'ACTIVE', UI_LIME)
    for k, name in enumerate(('d4', 'd3', 'd1', 'd2')):
        col = BLIPS[name]['color']
        y = py0 + 9 + k * 5
        for x in range(px0 + 3, px1 - 1):
            L.set(x, y, col)
            L.set(x, y + 3, col)
        for yy in (y + 1, y + 2):
            L.set(px0 + 3, yy, col)
            L.set(px1 - 2, yy, col)
        hline(L, px0 + 5, px0 + 5 + 2 + k % 3 * 2, y + 1, mix(col, (0, 0, 0), .35))
        hline(L, px0 + 5, px0 + 11 + k % 2 * 3, y + 2, mix(col, (0, 0, 0), .5))
    # the capsule buttons along the bottom of the map
    for (x0, x1, col) in ((SX0 + 8, SX0 + 22, C('#ff7aa8')), (SX0 + 31, SX0 + 44, UI_LIME),
                          (SX1 - 22, SX1 - 3, UI_LIME)):
        rect(L, x0, MY1 - 3, x1 - x0 + 1, 3, UI_PANEL)
        hline(L, x0, x1, MY1 - 3, mix(col, (0, 0, 0), .35))
        hline(L, x0 + 2, x0 + 2 + (x1 - x0) // 2, MY1 - 1, mix(col, (0, 0, 0), .15))
    # terminal strip: where the mapper is running
    ty = MY1 + 1
    rect(L, SX0, ty, SX1 - SX0 + 1, SY1 - ty + 1, C('#04070a'))
    hline(L, SX0, SX1, ty, C('#1d2a36'))
    cmd = '$ MESH-MAPPER.PY'
    text3(L, SX0 + 3, ty + 2, cmd, C('#58e873'))
    hline(L, SX0 + 3, SX0 + 40, ty + 7, C('#0a1118'))
    return text3_width(cmd)


def map_markers():
    """Flight paths, level 1 stations with the bearings that cross on a drone, and
    the observer (this base station)."""
    # flight paths: the route each drone flies, dotted behind its blip
    for name, b in BLIPS.items():
        L = new_layer('trail-' + name, alpha=.55)
        r = ROUTES[name]
        pts = [(b['at'][0] + nx * b['amp'][0], b['at'][1] + ny * b['amp'][1]) for (_, nx, ny) in r['pts']]
        for (p0, p1) in zip(pts, pts[1:]):
            for i, (x, y) in enumerate(line_pts(int(round(p0[0])), int(round(p0[1])),
                                                int(round(p1[0])), int(round(p1[1])))):
                if i % 2 == 0:
                    L.set(x, y, b['color'])
    # level 1 stations and the bearings that cross on the teal drone
    tx, ty = BLIPS['d4']['at']
    marks = new_layer('stations')
    for (sx, sy, col) in ((124, 84, C('#ffaa33')), (168, 79, C('#ff5fd0'))):
        rect(marks, sx - 1, sy - 1, 3, 3, col)
    bear = new_layer('bearings', alpha=.7)
    for (sx, sy, col) in ((124, 84, C('#ffaa33')), (168, 79, C('#ff5fd0'))):
        dx, dy = tx - sx, ty - sy
        ex, ey = tx + dx * .45, ty + dy * .45
        for i, (x, y) in enumerate(line_pts(sx, sy, int(round(ex)), int(round(ey)))):
            if i % 3 != 2 and MX0 <= x <= 168 and MY0 + 1 <= y <= MY1 - 5:
                bear.set(x, y, col)
    # the observer: a crosshair, like the mapper's
    obs = new_layer('observer')
    ox, oy = 137, 82
    for d in range(-3, 4):
        if d:
            obs.set(ox + d, oy, C('#4fe8ff'))
            obs.set(ox, oy + d, C('#4fe8ff'))
    obs.set(ox, oy, C('#bff9ff'))


def blips():
    """The blips: the same routes as the window drones, a fraction as far."""
    for name, b in BLIPS.items():
        trk = route_track(name, b['amp'], 'm')
        grp = ((trk, '', name + 'm'),)
        cx, cy = b['at']
        icon = new_layer('blip-' + name, groups=grp)
        quad_icon(icon, cx, cy, b['color'])
        frames = seq_frames(3, 2.4, phase=0.5 * list(BLIPS).index(name))
        for k, rad in enumerate((5, 7, 9)):
            cls, style = frames[k]
            ring = new_layer('blip-%s-ring%d' % (name, k), groups=grp, anim=cls, style=style,
                             alpha=.55 - .15 * k)
            for p in ring_pts(cx, cy, rad):
                ring.set(p[0], p[1], b['color'])


def terminal_cursor(text_w):
    ty = MY1 + 1
    cls, style = pulse('cursor', .55, 1.1)
    L = new_layer('cursor', anim=cls, style=style)
    rect(L, SX0 + 3 + text_w + 2, ty + 2, 3, 5, C('#58e873'))


def laptop():
    """Bezel, hinge, keyboard deck and lip. Light from the screen is added
    later by lighting()."""
    L = new_layer('laptop')
    bez, bez_hi, bez_lo = C('#14171f'), C('#2f3548'), C('#080a10')
    x0, x1, y0, y1 = SX0 - 2, SX1 + 2, SY0 - 2, SY1 + 2
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if (x in (x0, x1)) and (y in (y0, y1)):
                continue
            L.set(x, y, bez)
    hline(L, x0 + 1, x1 - 1, y0, bez_hi)
    vline(L, x0, y0 + 1, y1 - 1, bez_hi)
    vline(L, x1, y0 + 1, y1 - 1, bez_lo)
    hline(L, x0 + 1, x1 - 1, y1, bez_lo)
    rect(L, SX0 - 1, SY0 - 1, SX1 - SX0 + 3, SY1 - SY0 + 3, C('#020306'))     # glass edge
    L.set((SX0 + SX1) // 2, y0 + 1, C('#1f6a3a'))                               # webcam
    # hinge
    rect(L, x0 - 4, y1 + 1, x1 - x0 + 9, 2, C('#232838'))
    hline(L, x0 - 4, x1 + 4, y1 + 1, C('#3c4560'))
    # keyboard deck: a trapezoid, wider toward the viewer
    dy0, dy1 = y1 + 3, y1 + 21
    deck, deck_hi, deck_lo = C('#1c202c'), C('#323a52'), C('#0e1019')
    for y in range(dy0, dy1 + 1):
        t = (y - dy0) / float(dy1 - dy0)
        a, b = int(round(x0 - 6 - 8 * t)), int(round(x1 + 6 + 8 * t))
        for x in range(a, b + 1):
            L.set(x, y, deck)
        L.set(a, y, deck_hi)
        L.set(b, y, deck_lo)
    hline(L, x0 - 6, x1 + 6, dy0, deck_hi)
    # lip at the front
    for y in range(dy1 + 1, dy1 + 4):
        a, b = x0 - 14, x1 + 14
        hline(L, a, b, y, C('#2a3044') if y == dy1 + 1 else (C('#161a26') if y == dy1 + 2 else C('#0a0c14')))
    # keys
    keys = new_layer('keys')
    for r in range(4):
        y = dy0 + 3 + r * 3
        t = (y - dy0) / float(dy1 - dy0)
        a, b = int(round(x0 - 2 - 8 * t)), int(round(x1 + 2 + 8 * t))
        for x in range(a, b - 2, 4):
            keys.set(x, y, C('#4a5470'))
            keys.set(x + 1, y, C('#4a5470'))
            keys.set(x + 2, y, C('#4a5470'))
            keys.set(x, y + 1, C('#2c3348'))
            keys.set(x + 1, y + 1, C('#2c3348'))
            keys.set(x + 2, y + 1, C('#2c3348'))
    rect(keys, (x0 + x1) // 2 - 11, dy1 - 5, 23, 4, C('#232a3e'))               # trackpad
    hline(keys, (x0 + x1) // 2 - 11, (x0 + x1) // 2 + 11, dy1 - 5, C('#3a4560'))


# ----------------------------------------------------------------------------
# helpers for small hardware


# ----------------------------------------------------------------------------
METAL = [C('#232838'), C('#363d56'), C('#4f5878'), C('#7e89b0'), C('#aab4d8')]
PCB_G = [C('#0d3b2a'), C('#146b45'), C('#1f8f5c'), C('#3bbf85')]


def box(L, x, y, w, h, front, top, light=None, dark=None, top_h=2):
    """A little box seen from slightly above: lit top, front face, a lit left
    edge and a shaded bottom/right."""
    for j in range(h):
        for i in range(w):
            L.set(x + i, y + j, top if j < top_h else front)
    if light is not None:
        vline(L, x, y + top_h, y + h - 1, light)
    if dark is not None:
        hline(L, x, x + w - 1, y + h - 1, dark)
        vline(L, x + w - 1, y + top_h, y + h - 1, dark)


def disc_pts(cx, cy, r):
    return {(x, y) for y in range(int(cy - r) - 1, int(cy + r) + 2)
            for x in range(int(cx - r) - 1, int(cx + r) + 2) if (x - cx) ** 2 + (y - cy) ** 2 <= r * r}


# ----------------------------------------------------------------------------
# the wall above the bench: shelf, notes, pegboard


# ----------------------------------------------------------------------------
SHELF_Y = 30


def shelf():
    L = new_layer('shelf')
    BG.append(L)
    x0, x1, y = 112, 250, SHELF_Y
    for x in range(x0, x1 + 1):
        L.set(x, y, C('#6a5478'))
        L.set(x, y + 1, C('#3d2f4c'))
        L.set(x, y + 2, C('#1c1426'))
    for bx in (122, 182, 242):                                   # brackets
        vline(L, bx, y + 3, y + 8, METAL[1])
        L.set(bx + 1, y + 4, METAL[1])
        L.set(bx + 2, y + 5, METAL[0])
        hline(L, bx - 1, bx + 2, y + 3, METAL[2])
    # parts bins
    for k, col in enumerate((C('#c2364a'), C('#e08a2c'), C('#1f9f9a'), C('#7a46c8'))):
        bx = 114 + k * 9
        box(L, bx, y - 10, 8, 10, mix(col, (0, 0, 0), .45), mix(col, (255, 255, 255), .15), light=col,
            dark=mix(col, (0, 0, 0), .7), top_h=2)
        rect(L, bx + 1, y - 7, 6, 3, C('#d8d4c4'))                # label
        hline(L, bx + 2, bx + 5, y - 6, C('#4a4660'))
        hline(L, bx + 3, bx + 4, y - 3, C('#9a96b0'))             # pull
    # filament spools, face on
    for (cx, col) in ((184, C('#ff7a2a')), (196, C('#22c3b8'))):
        for (px, py) in disc_pts(cx, y - 6, 6):
            L.set(px, py, col)
        for (px, py) in disc_pts(cx, y - 6, 3):
            L.set(px, py, mix(col, (0, 0, 0), .55))
        for (px, py) in disc_pts(cx, y - 6, 1):
            L.set(px, py, C('#0c0e14'))
        for (px, py) in ell_pts(cx - 3, y - 9, 2, 1):
            L.set(px, py, mix(col, (255, 255, 255), .45))
    # a cactus in a pot
    rect(L, 208, y - 4, 7, 4, C('#b5532c'))
    hline(L, 207, 215, y - 4, C('#d97a48'))
    hline(L, 208, 214, y - 1, C('#7a3318'))
    rect(L, 210, y - 11, 3, 7, C('#2f9a4e'))
    rect(L, 208, y - 8, 2, 3, C('#2f9a4e'))
    rect(L, 213, y - 9, 2, 3, C('#2f9a4e'))
    vline(L, 210, y - 11, y - 5, C('#58c878'))
    L.set(211, y - 12, C('#ff5fa8'))
    # the rubber duck every debugging session needs
    for (px, py) in ell_pts(222, y - 3, 4, 2.5):
        L.set(px, py, C('#ffd23a'))
    for (px, py) in disc_pts(225, y - 7, 2.2):
        L.set(px, py, C('#ffd23a'))
    hline(L, 227, 229, y - 6, C('#ff8a1e'))
    L.set(225, y - 8, C('#1a1020'))
    hline(L, 219, 224, y - 2, C('#c79a1a'))
    # a roll of tape and a jar of resistors
    for (px, py) in ell_pts(238, y - 3, 3.5, 3.5):
        L.set(px, py, C('#3a7ad0'))
    for (px, py) in ell_pts(238, y - 3, 1.5, 1.5):
        L.set(px, py, C('#0c0e14'))
    rect(L, 243, y - 8, 7, 8, C('#2b3a4a'))
    hline(L, 243, 249, y - 8, C('#7aa0b8'))
    for k in range(5):
        L.set(244 + (k * 3) % 6, y - 6 + k % 4, [C('#e08a2c'), C('#c2364a'), C('#3fb6ff')][k % 3])
    # the strip of LEDs under the board
    strip = new_layer('shelf-led')
    for x in range(x0 + 1, x1):
        t = (x - x0) / float(x1 - x0)
        strip.set(x, y + 3, mix(C('#5ff3ff'), C('#ff4fd8'), min(1.0, max(0.0, (t - .3) / .5))), True)
    BG.append(strip)


def clock():
    """A red LED alarm clock showing the small hours."""
    L = new_layer('clock')
    BG.append(L)
    x, y = 150, SHELF_Y - 10
    box(L, x, y, 25, 10, C('#10121a'), C('#262a3a'), light=C('#232838'), dark=C('#07080d'), top_h=2)
    red = C('#ff3b4a')
    text3(L, x + 2, y + 3, '03', red, emit=True)
    text3(L, x + 13, y + 3, '17', red, emit=True)
    cls, style = pulse('colon', .5, 2)
    colon = new_layer('clock-colon', anim=cls, style=style)
    colon.set(x + 11, y + 4, red, True)
    colon.set(x + 11, y + 6, red, True)
    glow(BG, x + 12, y + 5, 12, (255, 59, 74), amax=.35, levels=3, falloff=1.2, ex=1.3, ey=.8)


def sticky_notes():
    L = new_layer('notes')
    BG.append(L)
    for (x, y, col, lines) in ((121, 36, C('#ffe27a'), (5, 3, 4)), (131, 39, C('#ff9ac8'), (4, 5)),
                               (153, 37, C('#8af0b0'), (3, 5, 2))):
        rect(L, x, y, 8, 8, col)
        hline(L, x, x + 7, y, mix(col, (255, 255, 255), .35))
        hline(L, x, x + 7, y + 7, mix(col, (0, 0, 0), .25))
        for k, ln in enumerate(lines):
            hline(L, x + 1, x + ln, y + 2 + 2 * k, C('#4a3a58'))
        L.set(x + 3, y - 1, C('#d8d4c4'))                       # strip of tape
        L.set(x + 4, y - 1, C('#d8d4c4'))


def pliers(L, x, y):
    """Pliers hanging on a pegboard hook."""
    for k in range(8):
        L.set(x + 1, y + 7 + k // 2 + 2, C('#d9364a'))
        L.set(x + 3, y + 7 + k // 2 + 2, C('#d9364a'))
    for j in range(8):
        L.set(x + 1 + (j % 2), y + j, METAL[3])
        L.set(x + 2, y + j, METAL[2])
    for j in range(10, 17):
        L.set(x, y + j, C('#d9364a'))
        L.set(x + 4, y + j, C('#a82636'))
        L.set(x + 1, y + j, C('#ff5568'))


def pegboard():
    L = new_layer('pegboard')
    BG.append(L)
    x0, y0, x1, y1 = 206, 36, 250, 66
    rect(L, x0, y0, x1 - x0 + 1, y1 - y0 + 1, C('#3a2c2e'))
    for yy in range(y0 + 2, y1, 4):
        for xx in range(x0 + 2, x1, 4):
            L.set(xx, yy, C('#1c1216'))
    hline(L, x0, x1, y0, C('#5a4448'))
    vline(L, x0, y0, y1, C('#5a4448'))
    hline(L, x0, x1, y1, C('#1a1014'))
    vline(L, x1, y0, y1, C('#1a1014'))
    pliers(L, 212, 40)
    for k, (col, ln) in enumerate(((C('#f5c542'), 17), (C('#d9364a'), 15), (C('#3a7ad0'), 18))):
        x = 222 + k * 4
        rect(L, x, 40, 3, 7, col)
        vline(L, x, 40, 46, mix(col, (255, 255, 255), .3))
        vline(L, x + 1, 47, 40 + ln, METAL[3])
    for (x, col) in ((234, C('#3a7ad0')), (239, C('#2f9a4e'))):           # cutters, strippers
        rect(L, x, 52, 3, 8, col)
        vline(L, x + 1, 40, 51, METAL[3])
        L.set(x, 48, METAL[2])
        L.set(x + 2, 48, METAL[2])
    rect(L, 244, 42, 4, 9, C('#f5c542'))                               # glue gun
    rect(L, 243, 51, 3, 6, C('#2a2e3d'))
    L.set(247, 41, METAL[3])
    L.set(247, 40, C('#ff7a2a'))


def scope():
    """A bench oscilloscope; its trace is drawn later by scope_trace()."""
    L = new_layer('scope')
    BG.append(L)
    x, y, w, h = 206, 68, 44, 32
    box(L, x, y, w, h, C('#252b3d'), C('#3b4360'), light=C('#4a5478'), dark=C('#10131e'), top_h=3)
    rect(L, x + 3, y + 6, 26, 21, C('#06090e'))                       # screen bezel
    hline(L, x + 3, x + 28, y + 6, C('#0b0e16'))
    for yy in range(y + 8, y + 26):                                   # phosphor
        for xx in range(x + 5, x + 28):
            L.set(xx, yy, C('#04120e'))
    for xx in range(x + 5, x + 28, 5):                                # graticule
        vline(L, xx, y + 8, y + 25, C('#0b3a2a'))
    for yy in range(y + 8, y + 26, 4):
        hline(L, x + 5, x + 27, yy, C('#0b3a2a'))
    hline(L, x + 5, x + 27, y + 16, C('#0f5a3e'))
    # controls
    for (kx, ky) in ((37, 11), (37, 20)):
        for (px, py) in disc_pts(x + kx, y + ky, 3):
            L.set(px, py, METAL[2])
        for (px, py) in disc_pts(x + kx, y + ky, 1.5):
            L.set(px, py, METAL[0])
        L.set(x + kx - 1, y + ky - 3, METAL[4])
    for k in range(3):
        rect(L, x + 32 + k * 4, y + 26, 3, 2, [C('#d9364a'), C('#f5c542'), C('#2f9a4e')][k])
    for k in range(2):                                                   # BNC connectors
        for (px, py) in disc_pts(x + 8 + k * 9, y + 29, 1.6):
            L.set(px, py, METAL[4])
    rect(L, x + 3, y + h, 5, 2, C('#0a0c14'))
    rect(L, x + w - 8, y + h, 5, 2, C('#0a0c14'))


def scope_trace():
    """Four frames of a waveform that scrolls across the scope's screen."""
    x, y = 206, 68
    frames = seq_frames(4, .8)
    for k in range(4):
        cls, style = frames[k]
        L = new_layer('scope-trace-%d' % k, anim=cls, style=style)
        prev = None
        for xx in range(x + 6, x + 27):
            ph = (xx - (x + 6)) / 21.0 * 2 * math.pi * 2 + k * math.pi / 2
            v = math.sin(ph)
            v = max(-1, min(1, v * 1.6))                              # a clipped, squarish wave
            yy = int(round(y + 16.5 - v * 5))
            L.set(xx, yy, C('#7dffc8'), True)
            if prev is not None:
                for q in range(min(prev, yy), max(prev, yy) + 1):
                    L.set(xx, q, mix(C('#7dffc8'), C('#04120e'), .35) if q != yy else C('#7dffc8'), True)
            prev = yy


# ----------------------------------------------------------------------------
# the left of the bench


# ----------------------------------------------------------------------------
def desk_lamp(L):
    """An articulated lamp, switched off, rising in front of the window: a
    silhouette against the neon sky, edge-lit by the city."""
    dark, rim = C('#05040b'), C('#d04aa8')
    for (px, py) in ell_pts(15, 110, 8, 2.2):                    # base
        L.set(px, py, dark)
    for (px, py) in ell_pts(14, 109, 5, 1):
        L.set(px, py, C('#2a1840'))
    segs = (((15, 109), (17, 94)), ((17, 94), (13, 80)), ((13, 80), (24, 69)))
    for (p0, p1) in segs:
        for (x, y) in line_pts(p0[0], p0[1], p1[0], p1[1]):
            L.set(x, y, dark)
            L.set(x + 1, y, dark)
            L.set(x + 2, y, dark)
            if y < 82:
                L.set(x + 3, y, rim)
    for (px, py) in disc_pts(17, 94, 1.5):                       # joints
        L.set(px, py, C('#2a2040'))
    for (px, py) in disc_pts(13, 80, 1.5):
        L.set(px, py, C('#2a2040'))
    # the shade: a cone hanging off the last arm, opening toward the bench
    for j in range(8):
        w = 5 + j
        for i in range(w):
            L.set(20 + i - j // 2 + 2, 66 + j, dark)
    hline(L, 18, 31, 73, rim)
    for (px, py) in ell_pts(27, 74, 5, 1.2):
        L.set(px, py, C('#1a1226'))


def goggles(L, x, y):
    """FPV goggles with their two patch antennas."""
    body, top, foam = C('#0e1018'), C('#2b3144'), C('#1b1e2a')
    rect(L, x - 2, y + 3, 2, 3, C('#d9702a'))                     # strap
    rect(L, x + 22, y + 3, 2, 3, C('#d9702a'))
    box(L, x, y, 22, 8, body, top, light=C('#2b3144'), dark=C('#06070b'), top_h=2)
    rect(L, x + 2, y + 6, 18, 2, foam)
    for cx in (x + 6, x + 15):
        for (px, py) in disc_pts(cx, y + 4, 3):
            L.set(px, py, C('#04050a'))
        L.set(cx - 1, y + 3, C('#3fb6ff'))
        L.set(cx, y + 3, C('#7de8ff'))
    for ax in (x + 3, x + 18):                                     # antennas
        vline(L, ax, y - 8, y - 1, C('#c8c4d8'))
        rect(L, ax - 1, y - 11, 3, 3, C('#e8e4f0'))
        hline(L, ax - 1, ax + 1, y - 9, C('#4fb8c8'))


def multimeter(L, x, y):
    box(L, x, y, 11, 17, C('#d9a21c'), C('#f5c542'), light=C('#ffe27a'), dark=C('#7a5a0a'), top_h=1)
    rect(L, x + 1, y + 2, 9, 5, C('#10141c'))
    rect(L, x + 2, y + 3, 7, 3, C('#9ad8a8'))
    for k, v in enumerate((1, 0, 1, 1)):                           # a few LCD segments
        if v:
            vline(L, x + 3 + k * 2, y + 3, y + 5, C('#1c4a2c'))
    for (px, py) in disc_pts(x + 5, y + 11, 3.2):
        L.set(px, py, C('#1a1c26'))
    for (px, py) in disc_pts(x + 5, y + 11, 1.4):
        L.set(px, py, C('#6a6e86'))
    L.set(x + 5, y + 8, C('#ffffff'))
    for k, col in enumerate((C('#10121a'), C('#d9364a'), C('#10121a'))):
        for (px, py) in disc_pts(x + 2 + k * 3.5, y + 15, 1):
            L.set(px, py, col)
    # leads
    for (px, py) in line_pts(x + 6, y + 16, x + 14, y + 19):
        L.set(px, py, C('#d9364a'))
    for (px, py) in line_pts(x + 2, y + 16, x - 5, y + 20):
        L.set(px, py, C('#12141c'))


def soldering_station(L):
    x, y = 50, 100
    box(L, x, y, 18, 12, C('#232838'), C('#3b4360'), light=C('#4a5478'), dark=C('#0c0e16'), top_h=2)
    rect(L, x + 2, y + 4, 12, 7, C('#1a0608'))
    text3(L, x + 3, y + 5, '320', C('#ff3b3b'), emit=True)
    for (px, py) in disc_pts(x + 15, y + 8, 1.6):
        L.set(px, py, METAL[3])
    # the iron in its spring stand
    for k in range(7):                                             # coil
        hline(L, 71, 74, 106 + k, METAL[3] if k % 2 else METAL[1])
    vline(L, 70, 104, 112, METAL[1])
    for (px, py) in line_pts(80, 96, 73, 107):                      # the iron, handle to tip
        L.set(px, py, C('#14161f'))
        L.set(px + 1, py, C('#14161f'))
    for (px, py) in line_pts(76, 101, 73, 106):
        L.set(px - 1, py, C('#d9702a'))
    for (x_, y_) in ((72, 108), (73, 108), (72, 107)):
        L.set(x_, y_, C('#ff7a1a'), True)
    L.set(72, 107, C('#ffe27a'), True)


def solder_smoke():
    """Wisps rising from the iron tip, three frames."""
    frames = seq_frames(3, 2.4)
    shapes = (((72, 105), (73, 103), (72, 101), (73, 99)),
              ((73, 105), (72, 103), (73, 101), (74, 99), (73, 97)),
              ((72, 105), (73, 103), (74, 101), (73, 99), (74, 97), (75, 95)))
    for k in range(3):
        cls, style = frames[k]
        L = new_layer('smoke-%d' % k, anim=cls, style=style, alpha=.55)
        for (x, y) in shapes[k]:
            L.set(x, y, C('#c9c4e0'))
            if (x + y) % 2 == 0:
                L.set(x + 1, y, C('#8a86a8'))


def breadboard(L, x, y):
    w, h = 36, 9
    rect(L, x, y, w, h, C('#d6d0be'))
    hline(L, x, x + w - 1, y, C('#f0ecdc'))
    hline(L, x, x + w - 1, y + h - 1, C('#8a8470'))
    for xx in range(x + 1, x + w - 1, 2):
        for yy in (y + 2, y + 3, y + 5, y + 6):
            L.set(xx, yy, C('#a49e8a'))
    hline(L, x + 1, x + w - 2, y + 4, C('#6a6452'))
    hline(L, x + 1, x + w - 2, y + 1, C('#d9364a'))
    hline(L, x + 1, x + w - 2, y + 7, C('#3a7ad0'))
    # an ESP32 module on the right end, with its antenna trace
    box(L, x + 24, y - 3, 11, 11, C('#10131c'), C('#222838'), light=C('#222838'), dark=C('#05060a'), top_h=1)
    rect(L, x + 28, y - 1, 6, 5, METAL[3])
    hline(L, x + 28, x + 33, y - 1, METAL[4])
    for k in range(4):
        L.set(x + 25 + k * 2, y + 4, C('#d8b24f'))
    for k, yy in enumerate((y - 2, y, y - 2, y)):
        hline(L, x + 25 + (k % 2), x + 26 + (k % 2), yy, C('#d8b24f'))
    # components and jumper wires
    rect(L, x + 7, y + 1, 2, 3, C('#d9364a'))                       # LEDs
    L.set(x + 7, y + 1, C('#ff8a96'))
    rect(L, x + 12, y + 1, 2, 3, C('#f5c542'))
    L.set(x + 12, y + 1, C('#fff1a8'))
    hline(L, x + 17, x + 21, y + 3, C('#c9a46a'))                    # resistor
    for xx, col in ((18, C('#d9364a')), (19, C('#10121a')), (20, C('#f5c542'))):
        L.set(x + xx, y + 3, col)
    for (xx, col, ln) in ((4, C('#2f9a4e'), 5), (10, C('#e08a2c'), 6), (22, C('#3a7ad0'), 5)):
        vline(L, x + xx, y + 1, y + ln, col)


def fpv_quad(L, x, y):
    """A bare FPV frame seen from above: light carbon arms, silver motors, a
    labelled battery and a camera."""
    carbon, carbon_hi, carbon_lo = C('#4a5478'), C('#8a96c4'), C('#262c44')
    cx, cy = x + 15, y + 7
    for (mx, my) in ((3, 2), (27, 2), (3, 12), (27, 12)):
        for (px, py) in line_pts(x + mx, y + my, cx, cy):
            for k in range(3):
                L.set(px, py + k - 1, carbon)
            L.set(px, py - 1, carbon_hi)
            L.set(px, py + 1, carbon_lo)
    rect(L, cx - 6, cy - 3, 13, 8, C('#2f3650'))                    # body plates
    hline(L, cx - 6, cx + 6, cy - 3, C('#6a76a0'))
    hline(L, cx - 6, cx + 6, cy + 4, C('#10131c'))
    rect(L, cx - 5, cy - 5, 11, 5, C('#d9702a'))                    # battery
    hline(L, cx - 5, cx + 5, cy - 5, C('#ffa24a'))
    hline(L, cx - 5, cx + 5, cy - 1, C('#8a4a1a'))
    rect(L, cx - 2, cy - 4, 5, 2, C('#f4f0e0'))                      # its label
    hline(L, cx - 1, cx + 1, cy - 3, C('#2a1a10'))
    rect(L, cx - 2, cy + 5, 5, 3, C('#0a0b10'))                      # camera
    L.set(cx, cy + 6, C('#3fb6ff'))
    L.set(cx - 1, cy + 6, C('#7de8ff'))
    for (mx, my) in ((3, 2), (27, 2), (3, 12), (27, 12)):             # motors
        for (px, py) in disc_pts(x + mx, y + my, 3.6):
            L.set(px, py, METAL[1])
        for (px, py) in disc_pts(x + mx, y + my, 2.8):
            L.set(px, py, METAL[3])
        for (px, py) in disc_pts(x + mx, y + my, 1.4):
            L.set(px, py, C('#d9364a'))
        L.set(x + mx - 2, y + my - 2, METAL[4])
    for (px, py) in line_pts(x + 33, y + 11, x + 38, y + 8):           # a spare prop
        L.set(px, py, C('#c8d0ec'))
        L.set(px, py + 1, C('#6a74a0'))


def heltec(L, x, y):
    """The base radio: a Heltec board with its OLED and a LoRa antenna."""
    box(L, x, y, 14, 8, C('#0f1a3a'), C('#1f3270'), light=C('#2a4390'), dark=C('#060a1c'), top_h=1)
    rect(L, x + 1, y + 2, 7, 4, C('#05070e'))
    for k in range(3):                                              # OLED text
        hline(L, x + 2, x + 2 + (3 + k % 2 * 2), y + 2 + k, C('#7de8ff'))
    rect(L, x + 9, y + 2, 3, 3, C('#10131c'))
    L.set(x + 12, y + 2, C('#d8b24f'))
    rect(L, x + 12, y - 1, 2, 1, METAL[3])                          # connector
    # antenna
    for yy in range(y - 12, y + 1):
        L.set(x + 12, yy, C('#0a0b10'))
        L.set(x + 13, yy, C('#1c1f2c'))
    L.set(x + 12, y - 13, C('#0a0b10'))
    L.set(x + 13, y - 13, C('#1c1f2c'))
    # USB-C cable into the laptop
    for (px, py) in line_pts(x + 14, y + 5, x + 19, y + 2):
        L.set(px, py, C('#0a0b10'))
        L.set(px, py + 1, C('#242838'))


def heltec_led(x, y):
    cls, style = pulse('heltec', .35, 1.7)
    L = new_layer('heltec-led', anim=cls, style=style)
    L.set(x + 10, y + 6, C('#7dff9a'), True)
    L.set(x + 9, y + 6, C('#1f6a3a'))
    halo = new_layer('heltec-halo', anim=cls, style=style, alpha=.35)
    for (dx, dy) in ((9, 5), (11, 6), (10, 7), (10, 5)):
        halo.set(x + dx, y + dy, C('#7dff9a'))


def left_bench():
    lamp = new_layer('lamp')
    BG.append(lamp)
    desk_lamp(lamp)
    lamp.emit = set(lamp.pix)
    L = new_layer('bench-left')
    BG.append(L)
    solder_smoke()
    multimeter(L, 34, 101)
    soldering_station(L)
    goggles(L, 12, 112)
    fpv_quad(L, 36, 113)
    breadboard(L, 14, 123)
    heltec(L, 87, 108)
    heltec_led(87, 108)


# ----------------------------------------------------------------------------
# the right and the front of the bench


# ----------------------------------------------------------------------------
def raspberry_pi(L, x, y):
    """A Raspberry Pi with an active cooler (its fan is animated later)."""
    rect(L, x, y + 2, 24, 9, PCB_G[1])
    hline(L, x, x + 23, y + 2, PCB_G[3])
    hline(L, x, x + 23, y + 10, PCB_G[0])
    vline(L, x + 23, y + 2, y + 10, PCB_G[0])
    rect(L, x + 2, y, 20, 2, C('#0a0b10'))                          # GPIO header
    for k in range(10):
        L.set(x + 3 + 2 * k, y, C('#d8b24f'))
        if k % 3 == 0:
            L.set(x + 3 + 2 * k, y + 1, C('#d8b24f'))
    rect(L, x + 7, y + 4, 8, 6, METAL[2])                           # heatsink
    rect(L, x + 7, y + 4, 8, 1, METAL[4])
    for xx in range(x + 7, x + 15, 2):
        vline(L, xx, y + 5, y + 9, METAL[1])
    rect(L, x + 17, y + 3, 6, 4, METAL[3])                          # USB stacks
    rect(L, x + 17, y + 7, 6, 4, METAL[3])
    hline(L, x + 17, x + 22, y + 3, METAL[4])
    hline(L, x + 18, x + 21, y + 5, C('#05060a'))
    hline(L, x + 18, x + 21, y + 9, C('#05060a'))
    rect(L, x + 2, y + 5, 3, 3, C('#10131c'))                       # chips
    rect(L, x + 2, y + 9, 1, 1, C('#d9364a'), True)                  # power LED
    rect(L, x + 25, y + 5, 7, 3, C('#3a7ad0'))                      # ethernet cable out
    hline(L, x + 25, x + 31, y + 5, C('#6aa4f0'))
    for (px, py) in line_pts(x + 31, y + 6, x + 34, y + 12):
        L.set(px, py, C('#3a7ad0'))


def pi_fan_and_led(x, y):
    frames = seq_frames(2, .16)
    for k in range(2):
        cls, style = frames[k]
        L = new_layer('pi-fan-%d' % k, anim=cls, style=style)
        for (px, py) in disc_pts(x + 11, y + 7, 3):
            L.set(px, py, C('#10131c'))
        if k == 0:
            for d in (-2, -1, 0, 1, 2):
                L.set(x + 11 + d, y + 7, C('#aab4d8'))
                L.set(x + 11, y + 7 + d, C('#aab4d8'))
        else:
            for d in (-2, -1, 0, 1, 2):
                L.set(x + 11 + d, y + 7 + d, C('#aab4d8'))
                L.set(x + 11 + d, y + 7 - d, C('#aab4d8'))
    cls, style = pulse('pi', .3, 1.1)
    led = new_layer('pi-led', anim=cls, style=style)
    led.set(x + 4, y + 9, C('#7dff9a'), True)


def patch_antenna(L, x, y):
    """A 5.8 GHz patch antenna on a stand."""
    edge, pcb, pcb_l, pcb_d = C('#0f2a3c'), C('#2f7f9f'), C('#5bb6d2'), C('#1f5a75')
    gold, gold_l, gold_d = C('#d8b24f'), C('#f2d27a'), C('#8e6e22')
    w, h = 12, 10
    for j in range(h):
        for i in range(w):
            c = pcb_l if (i == 0 or j == 0) else (pcb_d if (i == w - 1 or j == h - 1) else pcb)
            L.set(x + i, y + j, c)
    for i in range(-1, w + 1):
        L.set(x + i, y - 1, edge)
        L.set(x + i, y + h, edge)
    for j in range(h):
        L.set(x - 1, y + j, edge)
        L.set(x + w, y + j, edge)
    for j in range(3, h - 3):
        for i in range(3, w - 3):
            L.set(x + i, y + j, gold_l if (i == 3 or j == 3) else (gold_d if (i == w - 4 or j == h - 4) else gold))
    L.set(x + w // 2, y + h // 2, edge)
    for yy in range(y + h + 1, y + h + 8):
        L.set(x + 5, yy, METAL[4])
        L.set(x + 6, yy, METAL[3])
        L.set(x + 7, yy, METAL[1])
    for (px, py) in ell_pts(x + 6, y + h + 8, 6, 1.8):
        L.set(px, py, METAL[1])
    hline(L, x + 2, x + 9, y + h + 8, METAL[3])
    for (px, py) in disc_pts(x + 6, y + h + 1, 1.4):                   # swivel
        L.set(px, py, METAL[3])
    for (px, py) in line_pts(x + 5, y + h + 6, x - 6, y + h + 9):    # coax to the Pi
        L.set(px, py, C('#0a0b10'))


def rtl_sdr(L, x, y):
    """An RTL-SDR dongle with a magnetic-mount whip."""
    rect(L, x + 3, y, 9, 4, C('#2a5ab0'))
    hline(L, x + 3, x + 11, y, C('#5a8ae0'))
    hline(L, x + 3, x + 11, y + 3, C('#10306a'))
    rect(L, x, y + 1, 3, 2, METAL[4])
    L.set(x + 9, y + 1, C('#7dff9a'), True)
    for (px, py) in ell_pts(x + 18, y + 3, 3.4, 1.4):
        L.set(px, py, C('#10131c'))
    for yy in range(y - 12, y + 2):
        L.set(x + 18, yy, METAL[4] if yy % 2 else METAL[3])


def mug(L, x, y):
    rect(L, x, y + 1, 8, 9, C('#1e3a4a'))
    vline(L, x, y + 1, y + 9, C('#3a6a84'))
    hline(L, x, x + 7, y + 9, C('#0c1a24'))
    vline(L, x + 7, y + 1, y + 9, C('#0c1a24'))
    for (px, py) in ell_pts(x + 3.5, y + 1, 4, 1.4):
        L.set(px, py, C('#4a2c1a'))
    rect(L, x + 8, y + 3, 2, 1, C('#1e3a4a'))                       # handle
    rect(L, x + 9, y + 4, 1, 3, C('#1e3a4a'))
    rect(L, x + 8, y + 7, 2, 1, C('#1e3a4a'))
    for (px, py) in ((x + 3, y + 5), (x + 4, y + 5), (x + 3, y + 6), (x + 2, y + 6), (x + 5, y + 6), (x + 4, y + 7)):
        L.set(px, py, C('#7de8ff'))                                  # a Wi-Fi glyph, sort of
    frames = seq_frames(3, 3.0)
    wisps = (((x + 3, y - 1), (x + 4, y - 3)), ((x + 4, y - 2), (x + 3, y - 4), (x + 4, y - 6)),
             ((x + 3, y - 3), (x + 4, y - 5), (x + 3, y - 7), (x + 5, y - 8)))
    for k in range(3):
        cls, style = frames[k]
        S = new_layer('steam-%d' % k, anim=cls, style=style, alpha=.5)
        for (px, py) in wisps[k]:
            S.set(px, py, C('#d8d4f0'))


def notebook(L, x, y):
    rect(L, x, y, 24, 7, C('#e0dccb'))
    vline(L, x + 12, y, y + 6, C('#a8a392'))
    hline(L, x, x + 23, y, C('#f4f0e0'))
    hline(L, x, x + 23, y + 6, C('#8a8672'))
    for k in range(3):
        hline(L, x + 1, x + 10, y + 2 + k * 2, C('#9ab8d8'))
        hline(L, x + 13, x + 22, y + 2 + k * 2, C('#9ab8d8'))
    for (a, b, yy) in ((2, 6, 2), (2, 9, 4), (14, 19, 2), (14, 17, 4), (14, 21, 6)):
        hline(L, x + a, x + b, y + yy - (yy == 6), C('#2a3a8a'))
    for (px, py) in line_pts(x + 15, y + 2, x + 22, y + 5):            # a pen
        L.set(px, py, C('#d9364a'))


def cables(L):
    """A tangle of USB and power cables."""
    runs = (((222, 128), (230, 125), (238, 129), (246, 126), (252, 129), C('#ff7a2a')),
            ((224, 131), (234, 128), (244, 131), C('#14161f')),
            ((228, 126), (236, 130), (245, 127), (251, 130), C('#e8e4f0')),
            ((230, 129), (240, 131), (250, 128), C('#d9364a')))
    for run in runs:
        col = run[-1]
        pts = run[:-1]
        for (p0, p1) in zip(pts, pts[1:]):
            for (px, py) in line_pts(p0[0], p0[1], p1[0], p1[1]):
                L.set(px, py, col)
                L.set(px, py + 1, mix(col, (0, 0, 0), .45))
    rect(L, 220, 127, 3, 2, METAL[4])
    rect(L, 253, 127, 2, 3, METAL[3])


def tools_front(L):
    # pliers lying flat
    for (px, py) in line_pts(64, 127, 72, 128):
        L.set(px, py, METAL[3])
        L.set(px, py + 1, METAL[2])
    for (px, py) in line_pts(72, 128, 78, 126):
        L.set(px, py, C('#d9364a'))
        L.set(px, py + 1, C('#a82636'))
    for (px, py) in line_pts(72, 129, 78, 130):
        L.set(px, py, C('#d9364a'))
    # a screwdriver
    rect(L, 82, 128, 5, 2, C('#f5c542'))
    hline(L, 82, 86, 128, C('#ffe27a'))
    hline(L, 87, 95, 128, METAL[3])
    hline(L, 87, 95, 129, METAL[1])
    # side cutters
    for (px, py) in line_pts(98, 127, 104, 130):
        L.set(px, py, C('#3a7ad0'))
        L.set(px, py + 1, C('#1f4a90'))
    for (px, py) in line_pts(98, 130, 104, 127):
        L.set(px, py, METAL[3])
    # a spool of solder
    for (px, py) in ell_pts(92, 120, 5, 3.6):
        L.set(px, py, METAL[3])
    for (px, py) in ell_pts(92, 120, 2.6, 1.8):
        L.set(px, py, C('#8a1f2a'))
    for (px, py) in ell_pts(91, 118, 2.4, 1):
        L.set(px, py, METAL[4])


def stickers():
    """Stickers on the drawer fronts."""
    L = new_layer('stickers')
    BG.append(L)

    def spr(x, y, rows, pal):
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch != '.':
                    L.set(x + i, y + j, pal[ch])
    # a skull
    spr(14, 136, ("..WWWW..", ".WWWWWW.", ".W.WW.W.", ".WWWWWW.", "..W..W..", "..WWWW.."),
        {'W': C('#e8e4f0')})
    # three nodes joined up: the mesh
    for (px, py) in ((46, 139), (53, 137), (51, 141)):
        for (qx, qy) in disc_pts(px, py, 1.2):
            L.set(qx, qy, C('#5ff3ff'))
    for (p0, p1) in (((46, 139), (53, 137)), ((53, 137), (51, 141)), ((46, 139), (51, 141))):
        for (qx, qy) in line_pts(p0[0], p0[1], p1[0], p1[1]):
            if (qx, qy) not in ((46, 139), (53, 137), (51, 141)):
                L.set(qx, qy, C('#3a7ad0'))
    # radio waves
    for r in (2, 4, 6):
        for a in range(-50, 51, 10):
            L.set(int(round(100 + r * math.cos(math.radians(a)))), int(round(139 + r * math.sin(math.radians(a)))),
                  C('#ffaa33'))
    L.set(98, 139, C('#ffaa33'))
    # the purple eye
    for (px, py) in ell_pts(137, 139, 5, 2.4):
        L.set(px, py, C('#5e30eb'))
    for (px, py) in disc_pts(137, 139, 1.5):
        L.set(px, py, C('#0c0818'))
    L.set(136, 138, C('#ffffff'))
    # a lightning bolt
    for (px, py) in ((190, 136), (189, 137), (188, 138), (189, 138), (190, 138), (189, 139), (188, 140), (187, 141)):
        L.set(px, py, C('#ffe27a'))
    # 5.8G
    rect(L, 220, 136, 17, 7, C('#0e1a26'))
    text3(L, 221, 137, '5.8G', C('#5ff3ff'))
    hline(L, 220, 236, 136, C('#1f6a8a'))
    hline(L, 220, 236, 142, C('#1f6a8a'))


def right_bench():
    L = new_layer('bench-right')
    BG.append(L)
    raspberry_pi(L, 212, 107)
    patch_antenna(L, 240, 100)
    rtl_sdr(L, 216, 121)
    pi_fan_and_led(212, 107)


def front_bench():
    L = new_layer('bench-front')
    BG.append(L)
    notebook(L, 118, 125)
    mug(L, 190, 121)
    cables(L)
    tools_front(L)
    stickers()


# ----------------------------------------------------------------------------
# lighting: the laptop, the scope, the neon from the window, the LED strip


# ----------------------------------------------------------------------------
def lighting():
    # the laptop screen is the main light: a cool cyan wash over wall and bench
    glow(BG, 156, 78, 1, (70, 215, 255), amax=.5, levels=3, falloff=.9, ex=62, ey=48, skip_lum=.7)
    glow(BG, 156, 112, 1, (70, 215, 255), amax=.4, levels=3, falloff=.9, ex=62, ey=20, skip_lum=.7)
    # the scope's green phosphor
    glow(BG, 219, 80, 1, (60, 255, 170), amax=.4, levels=3, falloff=.9, ex=26, ey=20, skip_lum=.7)
    # neon from the window spills onto the wall around it
    glow(BG, 55, 50, 1, (255, 70, 180), amax=.42, levels=3, falloff=.9, ex=60, ey=50, skip_lum=.7)
    # the LED strip under the shelf
    for x in range(120, 250, 14):
        t = (x - 112) / 138.0
        col = mix((95, 243, 255), (255, 79, 216), min(1.0, max(0.0, (t - .3) / .5)))
        glow(BG, x, 36, 9, col, amax=.45, levels=3, falloff=1.1, ex=1.6, ey=.8, skip_lum=.7)
    # the soldering iron and its display
    glow(BG, 72, 108, 7, (255, 120, 30), amax=.5, levels=3, falloff=1.2, skip_lum=.7)
    glow(BG, 60, 106, 1, (255, 50, 50), amax=.35, levels=3, falloff=.9, ex=12, ey=8, skip_lum=.7)


def blind_stripes():
    """Light through the slats of the blinds, thrown across the bench: soft
    pink bands, brighter near the window."""
    for strength, (y0, y1), name in ((.17, (90, 112), 'near'), (.1, (112, 133), 'far')):
        L = new_layer('stripes-' + name, alpha=strength)
        for k in range(7):
            x0 = 10 + k * 13
            top_dx = (y0 - 90) * .9
            bot_dx = (y1 - 90) * .9
            quad = [(x0 + top_dx, y0), (x0 + 5 + top_dx, y0), (x0 + 5 + bot_dx, y1), (x0 + bot_dx, y1)]
            for p in poly_pts(quad):
                if 0 <= p[0] <= 102 and not (GX0 - 4 <= p[0] <= GX1 + 4 and p[1] < 90):
                    L.set(p[0], p[1], C('#ff5ac8'))


# ----------------------------------------------------------------------------
# small lights and the frame


# ----------------------------------------------------------------------------
def flicker(duration, delay=0.0):
    """Class and style for an overlay that blinks on in short bursts."""
    add_css('.fl{animation:fl 1s %s}' % STEP)
    add_css(keyframes('fl', {0: 'opacity:0', 88: 'opacity:1', 90: 'opacity:0', 92: 'opacity:1',
                             94: 'opacity:0', 96: 'opacity:1', 98: 'opacity:0'}))
    return 'fl h', 'animation-duration:%gs;animation-delay:-%gs' % (duration, delay)


def breathe(period, lo=.35):
    add_css('.br{animation:br 1s ease-in-out infinite alternate}')
    add_css(keyframes('br', {0: 'opacity:%g' % lo, 100: 'opacity:1'}))
    return 'br', 'animation-duration:%gs' % period


def keyboard_backlight():
    """A cyan-to-magenta glow leaking between the keys, breathing slowly."""
    cls, style = breathe(4.5)
    L = new_layer('keyboard-glow', anim=cls, style=style, alpha=.55)
    x0, x1, y1 = SX0 - 2, SX1 + 2, SY1 + 2
    dy0 = y1 + 3
    for r in range(4):
        y = dy0 + 3 + r * 3 + 2
        t = (y - dy0) / 18.0
        a, b = int(round(x0 - 2 - 8 * t)), int(round(x1 + 2 + 8 * t))
        for x in range(a, b + 1):
            col = mix(C('#5ff3ff'), C('#ff4fd8'), (x - a) / float(max(1, b - a)))
            L.set(x, y, col)


def bench_lights():
    # the breadboard's two LEDs take turns
    for k, (x, col, hi) in enumerate(((14 + 7, C('#ff4a5a'), C('#ffb0b8')), (14 + 12, C('#ffd23a'), C('#fff1a8')))):
        cls, style = pulse('bb%d' % k, .5, 1.6)
        L = new_layer('led-%d' % k, anim=cls, style=style + (';animation-delay:-.8s' if k else ''))
        rect(L, x, 124, 2, 3, col, True)
        L.set(x, 124, hi, True)
        halo = new_layer('led-%d-halo' % k, anim=cls, style=style + (';animation-delay:-.8s' if k else ''), alpha=.4)
        for (dx, dy) in ((-1, 0), (2, 0), (0, -1), (1, -1), (0, 3), (1, 3), (-1, 2), (2, 2)):
            halo.set(x + dx, 124 + dy, col)
    # the Heltec's OLED changes its mind
    frames = seq_frames(2, 1.6)
    cls, style = frames[1]
    L = new_layer('oled-b', anim=cls, style=style)
    rect(L, 88, 110, 7, 4, C('#05070e'))
    for k, ln in enumerate((5, 3, 4)):
        hline(L, 89, 89 + ln, 110 + k, C('#7de8ff'))
    hline(L, 89, 90, 113, C('#7de8ff'))


def frame():
    """One-pixel frame with stepped corners, so the picture reads as a card on
    light and dark pages alike."""
    corners = {(0, 0), (1, 0), (0, 1), (W - 1, 0), (W - 2, 0), (W - 1, 1),
               (0, H - 1), (1, H - 1), (0, H - 2), (W - 1, H - 1), (W - 2, H - 1), (W - 1, H - 2)}
    for L in LAYERS:
        for p in corners:
            L.erase(*p)
    F = new_layer('frame')
    hi, lo = C('#6a56c0'), C('#241a5c')
    ring = {(x, y) for x in range(W) for y in (0, H - 1)}
    ring |= {(x, y) for y in range(H) for x in (0, W - 1)}
    ring |= {(1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)}
    for (x, y) in ring - corners:
        F.set(x, y, hi if (x < W // 2 and y < H // 2) or x == 0 or y == 0 else lo)


# ----------------------------------------------------------------------------
# build + main


# ----------------------------------------------------------------------------
def build():
    """Draw the layers back to front."""
    wall()
    # the window: city and drones behind the glass, then the frame and blinds
    city()
    window_drones()
    window_rain()
    glass_glare()
    window_frame()
    blinds()
    # the wall above the bench
    shelf()
    clock()
    sticky_notes()
    pegboard()
    # the bench, back to front
    bench()
    scope()
    scope_trace()
    left_bench()
    right_bench()
    laptop()
    front_bench()
    # what the laptop shows
    screen_map()
    map_markers()
    blips()
    text_w = screen_ui()
    banner_ticker()
    terminal_cursor(text_w)
    screen_glare()
    # light, life, and the frame
    lighting()
    blind_stripes()
    keyboard_backlight()
    bench_lights()
    frame()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description='Draw the standalone mapper README header.')
    ap.add_argument('-o', '--out', default=os.path.join(here, 'standalone-workbench.svg'),
                    help='SVG to write (default: next to this script)')
    ap.add_argument('--variant', choices=('animated', 'static', 'overlays'), default='animated',
                    help='static: no animation, for pixel-exact checks; '
                         'overlays: show every hidden overlay, to check their stacking')
    ap.add_argument('--png', help='also write a PNG of the still frame')
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
