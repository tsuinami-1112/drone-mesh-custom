#!/usr/bin/env python3
"""Generates level1-rooftop.svg, the pixel-art header of the level 1 README.

A small hacker Clawd in a black hoodie works at a laptop on a lonely rooftop,
monitoring a drone detector: a mast of patch antennas, solar panels and a mess
of cables. A hooded figure sits on the roof's edge, smoking. All around them
walls of apartment towers rise out of the frame, and thin mesh links run from
the mast to other masts on other rooftops.

The picture is a short story that loops: the laptop's map suddenly lights up,
Clawd shouts "!", the smoker flicks his cigarette off the roof and ducks into
cover next to Clawd while two drones buzz past, their pings flying to the
patch antennas and showing up as red dots and lines on the map; when the coast
is clear he lights another cigarette, walks back to the edge and sits down.

Everything is drawn on a 256x144 pixel grid and written out as merged
rectangles with crispEdges, so the SVG stays sharp at any size. The story is
CSS animation; the picture without it (what reduced motion shows) is the calm
first moment of the loop.

    python3 make_level1_rooftop.py                    # rewrite the SVG
    python3 make_level1_rooftop.py --png /tmp/p.png   # also a PNG of the still frame
    python3 make_level1_rooftop.py --png /tmp/p.png --scale 10 --crop 20,80,100,60

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


def bloom(name, tubes, color, bands, groups=(), anim=None, style=None):
    """Light spreading out of a set of lit pixels: bands of translucent colour,
    brightest nearest the tubes. bands: ((distance, alpha), ...), nearest first.
    Returns the layers."""
    tubes = set(tubes)
    pts = list(tubes)
    reach = int(math.ceil(bands[-1][0]))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    rings = [set() for _ in bands]
    for y in range(min(ys) - reach, max(ys) + reach + 1):
        for x in range(min(xs) - reach, max(xs) + reach + 1):
            if (x, y) in tubes:
                continue
            d = min(math.hypot(x - px, y - py) for (px, py) in pts)
            for i, (limit, _) in enumerate(bands):
                if d <= limit:
                    rings[i].add((x, y))
                    break
    out = []
    for i, (limit, alpha) in enumerate(bands):
        if rings[i]:
            L = new_layer('%s-bloom-%g' % (name, limit), alpha=alpha, groups=groups, anim=anim, style=style)
            for (x, y) in rings[i]:
                L.set(x, y, color)
            out.append(L)
    return out


def seg_dist(px, py, x0, y0, x1, y1):
    """Distance from a point to a segment."""
    dx, dy = x1 - x0, y1 - y0
    d2 = dx * dx + dy * dy
    t = 0.0 if d2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / d2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def thick_pts(x0, y0, x1, y1, r):
    """Pixels whose centres lie within r of the segment: a round-capped limb."""
    pts = set()
    for y in range(int(math.floor(min(y0, y1) - r)), int(math.ceil(max(y0, y1) + r)) + 1):
        for x in range(int(math.floor(min(x0, x1) - r)), int(math.ceil(max(x0, x1) + r)) + 1):
            if seg_dist(x + .5, y + .5, x0, y0, x1, y1) <= r:
                pts.add((x, y))
    return pts


def blob_pts(cx, cy, rx, ry):
    """Pixels whose centres lie inside an ellipse centred on (cx, cy)."""
    pts = set()
    for y in range(int(math.floor(cy - ry)) - 1, int(math.ceil(cy + ry)) + 2):
        for x in range(int(math.floor(cx - rx)) - 1, int(math.ceil(cx + rx)) + 2):
            if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1.0:
                pts.add((x, y))
    return pts


def outline_pts(mask):
    """The 4-neighbour border just outside a pixel set."""
    out = set()
    for (x, y) in mask:
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (x + d[0], y + d[1])
            if p not in mask:
                out.add(p)
    return out


def sprite(L, x, y, rows, pal, emit=()):
    """Draw an ASCII sprite: each character is a key of `pal`, '.' is clear.
    Characters listed in `emit` are marked as light emitters."""
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch != '.':
                L.set(x + i, y + j, pal[ch], ch in emit)


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


# The story: one long loop that every scripted thing follows. Each animated
# group gets a keyframe list written against this clock, so they all stay in
# step. Drawn at its position at t = 0, a group's keyframes are offsets from
# there; whatever is not on stage at t = 0 is hidden by default (class h).
T_LOOP = 30.0
EPS = .012           # a "cut" is a very quick change: this many seconds
_TL = [0]


def _fmt(v):
    s = '%.2f' % v
    return s.rstrip('0').rstrip('.') if '.' in s else s


def tl(samples, ease='linear'):
    """Register a keyframe list on the story clock and return its class.
    samples: (t seconds, {'o': opacity, 'x': dx, 'y': dy}) in time order; the
    first must be at t = 0 and the last at T_LOOP."""
    assert samples[0][0] == 0 and abs(samples[-1][0] - T_LOOP) < 1e-6, samples
    name = 'k%d' % _TL[0]
    _TL[0] += 1
    frames = {}
    for (t, v) in samples:
        d = []
        if 'o' in v:
            d.append('opacity:%s' % _fmt(v['o']))
        if 'x' in v or 'y' in v:
            d.append('transform:translate(%spx,%spx)' % (_fmt(v.get('x', 0)), _fmt(v.get('y', 0))))
        key = '%.3f' % (100.0 * t / T_LOOP)
        frames[key] = ';'.join(d)
    add_css('.%s{animation:%s %gs %s infinite}' % (name, name, T_LOOP, ease))
    add_css('@keyframes %s{%s}' % (name, ''.join('%s%%{%s}' % (k.rstrip('0').rstrip('.') if '.' in k else k, frames[k])
                                                  for k in sorted(frames, key=float))))
    return name


def vis(spans):
    """Show something only during some stretches of the loop.

    spans: (start, end) or (start, end, dx, dy) in time order and not
    overlapping. With offsets, the thing is drawn once and parked at (dx, dy)
    for that stretch (a pose reused at several places). Returns (class,
    hidden): the class to put on the group, and whether it starts hidden."""
    moves = any(len(s) > 2 for s in spans)
    samples = []
    state = {'o': 0}
    if moves:
        state.update(x=0, y=0)
    t_prev_end = None
    for s in spans:
        t0, t1 = s[0], s[1]
        pos = {'x': s[2], 'y': s[3]} if len(s) > 2 else {}
        if t_prev_end is not None and abs(t0 - t_prev_end) < 1e-6:
            samples.append((t0 + EPS, dict(o=1, **pos)))
        else:
            if t_prev_end is not None:
                samples.append((t_prev_end + EPS, dict(samples[-1][1], o=0)))
            if t0 > 0:
                samples.append((max(t0 - EPS, 0.0), dict(o=0, **pos)))
            samples.append((t0, dict(o=1, **pos)))
        samples.append((t1, dict(o=1, **pos)))
        t_prev_end = t1
    if t_prev_end is not None and t_prev_end < T_LOOP:
        samples.append((min(t_prev_end + EPS, T_LOOP), dict(samples[-1][1], o=0)))
    hidden = not (spans and spans[0][0] <= 0)
    first = dict(samples[0][1]) if samples else dict(state)
    if not samples or samples[0][0] > 0:
        samples.insert(0, (0.0, dict(first, o=0 if hidden else 1)))
    else:
        samples[0] = (0.0, dict(samples[0][1], o=0 if hidden else 1))
    if samples[-1][0] < T_LOOP:
        samples.append((T_LOOP, dict(samples[-1][1])))
    return tl(samples), hidden


def move(points, ref=None):
    """A thing travelling along a path of (time, x, y) points, visible only
    while it is on the path. It is drawn once, at `ref` (default: the first
    point) and the keyframes carry the offsets. Returns (class, hidden)."""
    ref = ref or (points[0][1], points[0][2])
    samples = []
    for (t, x, y) in points:
        samples.append((t, dict(o=1, x=x - ref[0], y=y - ref[1])))
    t0, t1 = points[0][0], points[-1][0]
    first, last = samples[0][1], samples[-1][1]
    pre, post = [], []
    if t0 > 0:
        pre = [(0.0, dict(first, o=0)), (max(t0 - EPS, 0.0), dict(first, o=0))]
    if t1 < T_LOOP:
        post = [(min(t1 + EPS, T_LOOP), dict(last, o=0)), (T_LOOP, dict(last, o=0))]
    seq = pre + samples + post
    return tl(seq), t0 > 0


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
    """True for layers the still frame leaves out: hidden themselves, or inside
    a group that is."""
    if 'h' in (L.anim or '').split():
        return True
    return any('h' in (g[0] or '').split() for g in L.groups)


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




# ----------------------------------------------------------------------------
# stage geometry, shared by the city, the roof and the people
# ----------------------------------------------------------------------------
EDGE_X = 34                     # the roof's left end: the edge he sits on
PAR_TOP, PAR_BOT = 110, 115     # back parapet: cap rows, then its face
ROOF_Y0, ROOF_Y1 = 116, 130     # roof surface, back edge to front edge
LIP_Y1 = 133                    # front lip of the roof
GAP_X0 = 17                     # the alley between the near tower and the roof edge


# ----------------------------------------------------------------------------
# palette: a violet night over a pink glow, lit by neon
# ----------------------------------------------------------------------------
SKY = [C(h) for h in ('#06041a', '#0b0826', '#110c35', '#1a1049', '#26145c', '#37186c',
                      '#4e1a79', '#6d1f82', '#922786', '#b93484', '#dd4a82', '#f4687e')]
SKY_STOPS = [(0, 0.0), (24, 2.4), (50, 4.5), (72, 6.4), (90, 8.4), (104, 10.0), (116, 11.0), (143, 11.0)]
INK = C('#0a0620')

PINK, PINK_D = C('#ff4fd8'), C('#a81f8c')
CYAN_N, CYAN_D = C('#5ff3ff'), C('#1c97b4')
RED_N, RED_D = C('#ff3d6e'), C('#8a1440')
GOLD_N, GOLD_D = C('#ffd23a'), C('#9a7a14')
BLUE_N, BLUE_D = C('#2f6bff'), C('#14307c')
WARM = [C('#ffd37a'), C('#ffa94d'), C('#fff0b8')]
COOL = [C('#6ef3ff'), C('#3fb6ff'), C('#a6e2ff')]
HOT = [C('#ff6ad5'), C('#ff3d9a')]
WIN_MIXES = [WARM, WARM, COOL, COOL, WARM + COOL, WARM + HOT, COOL + HOT]


def fog_at(x, y, soft=.4):
    return ramp_at(SKY, piecewise(SKY_STOPS, y), x, y, soft)


def shade(x, y, lift, dark, soft=.4, mist=0.0):
    """A wall's colour: the glow behind it (lifted a little, so towers read
    against the sky), darkened toward ink for the nearer ones. `mist` lets the
    street-level fog swallow the darkness toward the bottom of the canyon."""
    u = piecewise(SKY_STOPS, y) + lift
    d = dark * (1.0 - mist * max(0.0, min(1.0, (y - 58) / 54.0)))
    return mix(ramp_at(SKY, u, x, y, soft), INK, d)


# ----------------------------------------------------------------------------
# the sky and the towers
# ----------------------------------------------------------------------------
WINDOWS = []        # every lit window that could flicker: (layer name, x, y, w, h, colour)
MESH_NODES = []     # the masts on other rooftops: where the mesh links end
BEACONS = []        # blinking lights: (x, y, colour)
YB = 143            # towers are drawn down to the bottom of the frame


def sky():
    L = new_layer('sky')
    BG.append(L)
    for y in range(H):
        for x in range(W):
            L.set(x, y, fog_at(x, y, .4))
    rng = Rng(7)
    for _ in range(34):
        L.set(rng.randint(2, W - 3), rng.randint(2, 44), rng.choice([C('#4e397a'), C('#755ea6'), C('#342258')]), True)


def paint_block(L, blk, lift, dark, rim=None, rim_side=1, top_edge=None, soft=.22, mist=0.0):
    x0, x1, top = blk
    for y in range(max(top, 0), YB + 1):
        for x in range(x0, x1 + 1):
            L.set(x, y, shade(x, y, lift, dark, soft, mist))
    if rim:
        for y in range(max(top, 0), YB + 1):
            x = x0 if rim_side < 0 else x1
            L.set(x, y, mix(L.get(x, y), rim[0], rim[1]))
    if top_edge and top >= 0:
        for x in range(x0, x1 + 1):
            L.set(x, top, mix(L.get(x, top), top_edge[0], top_edge[1]))


def lit_windows(L, name, blk, cfg, rng, fog):
    x0, x1, top = blk
    ww, wh, px, py = cfg['w'], cfg['h'], cfg['px'], cfg['py']
    pal = rng.choice(WIN_MIXES)
    for gy in range(max(top, 0) + 2, YB - wh, py):
        band = rng.random()
        rd = cfg['dens'] * (2.4 if band > .86 else (.3 if band < .38 else 1.0))
        for gx in range(x0 + 1 + (blk[0] % 2), x1 - ww + 1, px):
            if rng.random() < rd:
                c = rng.choice(pal)
                if fog:
                    c = mix(c, fog_at(gx, gy, .5), fog)
                rect(L, gx, gy, ww, wh, c, True)
                WINDOWS.append((name, gx, gy, ww, wh, c))


def far_mast(L, x, y):
    """A rooftop mast with a little bundle of patch antennas, drawn in the
    layer; the beacon and the mesh endpoint are recorded."""
    pole, rim = C('#2a1c48'), C('#564096')
    for yy in range(y - 12, y + 1):
        L.set(x, yy, pole)
    L.set(x, y - 12, rim)
    for dx in (-2, -1, 1, 2):
        L.set(x + dx, y - 7, pole)
    L.set(x - 2, y - 8, C('#2f8fae'))
    L.set(x + 2, y - 8, C('#2f8fae'))
    L.set(x - 2, y - 6, C('#d8b24f'))
    L.set(x + 2, y - 6, C('#d8b24f'))
    L.set(x - 1, y - 11, C('#2f8fae'))
    L.set(x + 1, y - 11, C('#d8b24f'))
    BEACONS.append((x, y - 13, RED_N))
    MESH_NODES.append((x, y - 8))


def roof_furniture(L, blk, style, rng):
    x0, x1, top = blk
    if top < 1:
        return
    pole, rim = C('#1c132f'), C('#412e74')
    if style == 'tank':
        cx = x0 + (x1 - x0) // 2
        for y in range(top - 5, top):
            for x in range(cx - 2, cx + 3):
                L.set(x, y, C('#171028'))
        for x in range(cx - 2, cx + 3):
            L.set(x, top - 6, rim)
        for x in (cx - 2, cx + 2):
            L.set(x, top, pole)
    elif style == 'antenna':
        cx = x0 + rng.randint(2, max(2, x1 - x0 - 2))
        for y in range(top - rng.randint(6, 11), top):
            L.set(cx, y, pole)
        BEACONS.append((cx, top - 12, RED_N))
    elif style == 'spire':
        cx = x0 + (x1 - x0) // 2
        for k in range(5):
            for x in range(cx - 2 + k // 2, cx + 3 - k // 2):
                L.set(x, top - 1 - k, shade(x, top - 1 - k, 1.0, .3))
        for y in range(top - 14, top - 5):
            L.set(cx, y, pole)
        BEACONS.append((cx, top - 15, RED_N))
    elif style == 'billboard':
        for x in range(x0 + 1, x1 - 1):
            for y in range(top - 7, top - 1):
                L.set(x, y, C('#0a1019'))
        for x in range(x0 + 1, x1 - 1):
            L.set(x, top - 7, rim)
            L.set(x, top - 2, rim)
        col = rng.choice([CYAN_D, RED_D, GOLD_D])
        for x in range(x0 + 3, x1 - 3, 2):
            L.set(x, top - 5, col, True)
            L.set(x, top - 4, col, True)


# planes, far to near: (blocks, roof furniture, mesh mast x)
P0 = [(17, 30, -20, ''), (28, 42, 12, 'spire'), (40, 52, -10, ''), (50, 64, 22, 'tank'),
      (62, 76, -30, ''), (74, 86, 8, 'spire'), (84, 98, 26, 'billboard'), (96, 112, -12, ''),
      (110, 122, 16, 'antenna'), (120, 134, 30, ''), (132, 146, -20, ''), (144, 158, 10, 'spire'),
      (156, 170, 24, 'tank'), (168, 182, -8, ''), (180, 194, 18, 'antenna'), (192, 206, 32, ''),
      (204, 218, -25, ''), (216, 232, 12, 'spire'), (230, 246, 28, ''), (244, 258, -15, '')]
# the valley in the middle keeps a calm stretch of air for the drones to cross
P1 = [(17, 38, 70, '', 0), (36, 62, 46, 'tank', 0), (60, 88, 76, '', 0), (86, 114, 70, 'billboard', 0),
      (112, 140, 80, '', 0), (138, 166, 72, '', 0), (164, 192, 78, 'tank', 0), (190, 216, 54, 'antenna', 0)]
P1_MASTS = (50, 100, 152, 200)         # x of the rooftop masts the mesh reaches


def far_towers():
    rng = Rng(1112)
    L = new_layer('far')
    BG.append(L)
    for (x0, x1, top, style) in P0:
        blk = (x0, x1, top)
        paint_block(L, blk, 1.8, .2, rim=(C('#a070d8'), .16), rim_side=-1, mist=.7)
        lit_windows(L, 'far', blk, dict(w=1, h=1, px=3, py=4, dens=.2), rng, .5)
        roof_furniture(L, blk, style, rng)
    return L


def mid_towers():
    rng = Rng(204)
    L = new_layer('mid')
    BG.append(L)
    furn = new_layer('mid-masts')
    BG.append(furn)
    for k, (x0, x1, top, style, _) in enumerate(P1):
        blk = (x0, x1, top)
        paint_block(L, blk, .3, .7, rim=(C('#9a64e8'), .36), rim_side=-1 if x0 < 128 else 1,
                    top_edge=(C('#c090ff'), .5), mist=.62)
        lit_windows(L, 'mid', blk, dict(w=2, h=2, px=4, py=5, dens=.3), rng, .12)
        roof_furniture(furn, blk, style, rng)
    for mx in P1_MASTS:
        top = [b for b in P1 if b[0] <= mx <= b[1]][0][2]
        far_mast(furn, mx, top)
    return L


# ----------------------------------------------------------------------------
# the near towers, on either side: their tops are out of the frame
# ----------------------------------------------------------------------------
NEAR_L = (0, 16)
NEAR_R = (204, 255)
TRIDENT_AT = (173, 84)          # top-left of the little Ukrainian trident, on a tower far off
MESH_AT = (226, 17)             # top-left of the Meshtastic neon sign, high on the near tower
MESH_N = 21                     # its side


def apartment_facade(L, x0, x1, rng, cfg, name):
    """A wall of flats: floors of small windows, balcony ledges, AC boxes,
    a drainpipe. Lit windows are noted so a few can flicker."""
    ww, wh, px, py = cfg['w'], cfg['h'], cfg['px'], cfg['py']
    pal_rows = {}
    for gy in range(2, YB - wh, py):
        row = (gy - 2) // py
        band = rng.random()
        rd = cfg['dens'] * (2.2 if band > .84 else (.25 if band < .4 else 1.0))
        pal = rng.choice(WIN_MIXES)
        pal_rows[row] = pal
        for gx in range(x0 + cfg['ox'], x1 - ww + 1, px):
            lit = rng.random() < rd
            if lit:
                c = rng.choice(pal)
                rect(L, gx, gy, ww, wh, c, True)
                WINDOWS.append((name, gx, gy, ww, wh, c))
                if rng.chance(.16):                                   # curtains drawn halfway
                    rect(L, gx, gy, ww, 1, mix(c, INK, .7), True)
            else:
                rect(L, gx, gy, ww, wh, mix(L.get(gx, gy) or INK, C('#21163c'), .55))
            if rng.chance(.12):                                       # an AC box under the sill
                rect(L, gx, gy + wh, ww, 1, C('#4a3b6c'))
        if row % 2 == 1:                                              # balcony ledge
            for x in range(x0, x1 + 1):
                L.set(x, gy + wh + 1, mix(L.get(x, gy + wh + 1) or INK, C('#5f4f88'), .55))
            for x in range(x0 + 1, x1, 2):
                L.set(x, gy + wh, mix(L.get(x, gy + wh) or INK, C('#392a5c'), .6))
    px_ = x0 + (x1 - x0) // 3
    for y in range(0, YB):
        L.set(px_, y, mix(L.get(px_, y), C('#2b1f4a'), .5))           # drainpipe


def near_towers():
    rng = Rng(77)
    L = new_layer('near-left')
    BG.append(L)
    paint_block(L, (NEAR_L[0], NEAR_L[1], -40), 0, .82, rim=(C('#ff7ac8'), .6), rim_side=1)
    apartment_facade(L, NEAR_L[0], NEAR_L[1], rng, dict(w=3, h=3, px=5, py=7, dens=.36, ox=1), 'near-left')
    R = new_layer('near-right')
    BG.append(R)
    paint_block(R, (NEAR_R[0], NEAR_R[1], -40), 0, .84, rim=(C('#5ad0f0'), .42), rim_side=-1)
    apartment_facade(R, NEAR_R[0], NEAR_R[1], rng, dict(w=3, h=3, px=6, py=8, dens=.3, ox=2), 'near-right')
    return L, R


# ----------------------------------------------------------------------------
# the alley under the roof's edge: a glowing drop to the street, far below
# ----------------------------------------------------------------------------
def alley():
    L = new_layer('alley-glow', alpha=.62)
    for y in range(92, YB + 1):
        cov = ((y - 92) / float(YB - 92)) ** 1.1
        for x in range(GAP_X0, EDGE_X):
            if cov > bay(x, y) * .98:
                L.set(x, y, C('#ff7ab0') if y > 124 else C('#d85a98'))
    street = new_layer('alley-street')
    rng = Rng(5)
    for _ in range(18):                              # lights and neon, a long way down
        x, y = rng.randint(GAP_X0, EDGE_X - 1), rng.randint(126, 142)
        street.set(x, y, rng.choice([C('#ffc27a'), C('#ff5a6a'), C('#6ae6ff'), C('#ffd9a0')]), True)
    for x in (22, 29):                               # street lamps in a row
        for y in range(137, 142):
            street.set(x, y, C('#ffdfa8'), True)


# ----------------------------------------------------------------------------
# neon: a red sign off the near tower, and a Ukrainian trident
# ----------------------------------------------------------------------------
def neon_sign_v(L, x, y, text, col, dim, plate=C('#06090f')):
    """Vertical neon sign: dark plate, neon frame, stacked 3x5 letters."""
    h = len(text) * 6 - 1
    rect(L, x - 2, y - 2, 7, h + 4, plate)
    for yy in range(y - 2, y + h + 2):
        L.set(x - 2, yy, dim, True)
        L.set(x + 4, yy, dim, True)
    for xx in range(x - 2, x + 5):
        L.set(xx, y - 2, dim, True)
        L.set(xx, y + h + 1, dim, True)
    text3(L, x, y, text, col, emit=True, vertical=True)


TRIDENT = (                      # the tryzub in the colours of the flag: blue prongs over a yellow base
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


def trident_sign():
    """A small neon tryzub on a tower a long way off: blue over yellow, a touch
    of haze on it so it sits back in the picture and does not shout."""
    L = new_layer('trident')
    BG.append(L)
    x, y = TRIDENT_AT
    w, h = len(TRIDENT[0]), len(TRIDENT)
    wall = layer('mid')
    for yy in range(y - 1, y + h + 1):                 # a dark board behind it
        for xx in range(x - 1, x + w + 1):
            L.set(xx, yy, mix(wall.get(xx, yy) or INK, INK, .5))
    for j, row in enumerate(TRIDENT):
        for i, ch in enumerate(row):
            if ch != '.':
                base = BLUE_N if ch == 'B' else GOLD_N
                c = mix(mix(base, fog_at(x + i, y + j, .5), .14), INK, .1)
                L.set(x + i, y + j, c, True)
    return L


MESH_GREEN, MESH_HOT, MESH_DIM = C('#67ea94'), C('#d4ffe4'), C('#1f7a45')


def mesh_strokes(x0, y0):
    """The Meshtastic mark as two polylines in plate coordinates: a slash, and a peak."""
    return (((x0 + 4, y0 + 14), (x0 + 8, y0 + 7)),
            ((x0 + 9, y0 + 14), (x0 + 13, y0 + 7), (x0 + 17, y0 + 14)))


def meshtastic_sign():
    """The Meshtastic logo as a green neon sign: its slash and peak lit on a
    dark plate, in a rounded neon frame."""
    L = new_layer('meshtastic')
    BG.append(L)
    x0, y0 = MESH_AT
    n = MESH_N
    plate = C('#06180f')
    rect(L, x0, y0, n, n, plate, True)
    for i in range(2, n - 2):                          # the frame, with rounded corners
        for (x, y) in ((x0 + i, y0), (x0 + i, y0 + n - 1), (x0, y0 + i), (x0 + n - 1, y0 + i)):
            L.set(x, y, MESH_GREEN, True)
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x0 + n - 1, y0, -1, 1), (x0, y0 + n - 1, 1, -1),
                             (x0 + n - 1, y0 + n - 1, -1, -1)):
        L.set(cx, cy, mix(plate, wall_behind(cx, cy), .5))
        L.set(cx + sx, cy + sy, MESH_GREEN, True)
    for i in range(2, n - 2):                          # the frame's glow, just inside
        for (x, y) in ((x0 + i, y0 + 1), (x0 + i, y0 + n - 2), (x0 + 1, y0 + i), (x0 + n - 2, y0 + i)):
            if L.get(x, y) == plate:
                L.set(x, y, MESH_DIM, True)
    for stroke in mesh_strokes(x0, y0):
        for (p, q) in zip(stroke, stroke[1:]):
            for (x, y) in line_pts(p[0], p[1], q[0], q[1]):
                for dx in (-1, 1):                     # a dim halo each side makes the tube read thicker
                    if L.get(x + dx, y) == plate:
                        L.set(x + dx, y, MESH_DIM, True)
        for (p, q) in zip(stroke, stroke[1:]):
            for (x, y) in line_pts(p[0], p[1], q[0], q[1]):
                L.set(x, y, MESH_GREEN, True)
    for (x, y) in ((x0 + 8, y0 + 7), (x0 + 13, y0 + 7)):   # the hottest points of the tube
        L.set(x, y, MESH_HOT, True)
    return L


def wall_behind(x, y):
    top, c = composite_at(LAYERS, x, y)
    return c or INK


def city():
    sky()
    far_towers()
    mid_towers()
    trident_sign()
    near_towers()
    meshtastic_sign()
    alley()
    L = layer('near-left')
    neon_sign_v(L, 12, 96, 'BAR', PINK, PINK_D)
    # the neon bleeds onto whatever is near it
    glow(BG, 30, 124, 40, (255, 98, 150), amax=.42, levels=3, falloff=1.1, ex=1.1, ey=1.0, skip_lum=.7)
    glow(BG, 14, 108, 22, (255, 79, 216), amax=.5, levels=3, falloff=1.1, ex=1.0, ey=1.3, skip_lum=.66)
    glow(BG, MESH_AT[0] + MESH_N // 2, MESH_AT[1] + MESH_N // 2, 30, (103, 234, 148), amax=.5, levels=4,
         falloff=1.1, ex=1.0, ey=1.0, skip_lum=.66)
    x, y = TRIDENT_AT
    glow(BG, x + 5, y + 5, 11, (70, 120, 255), amax=.2, levels=3, falloff=1.3, ex=1.0, ey=1.1, skip_lum=.66)
    glow(BG, x + 5, y + 13, 9, (255, 215, 70), amax=.16, levels=3, falloff=1.3, ex=1.0, ey=1.0, skip_lum=.66)


# ----------------------------------------------------------------------------
# the rooftop: parapet, roof, the building's face below, the stair hut
# ----------------------------------------------------------------------------
CONCRETE = [C('#120d1f'), C('#181128'), C('#1e1531'), C('#23193a'), C('#2c1e4a')]
GROUND_Y = 128          # where the small things stand


def roof():
    L = new_layer('roof')
    BG.append(L)
    rng = Rng(99)
    cap_hi, cap, cap_lo = C('#8472b3'), C('#514078'), C('#2c1f4a')
    # the back parapet runs from the roof's end to the right of the frame
    for x in range(EDGE_X, W):
        L.set(x, PAR_TOP, cap_hi)
        L.set(x, PAR_TOP + 1, cap)
        L.set(x, PAR_TOP + 2, cap_lo)
    for y in range(PAR_TOP + 3, PAR_BOT + 1):
        t = (y - PAR_TOP - 3) / float(PAR_BOT - PAR_TOP - 2)
        for x in range(EDGE_X, W):
            L.set(x, y, ramp_at(CONCRETE[:4], t * 3, x, y, .7))
    for x in range(EDGE_X + 24, W, 40):               # expansion joints
        for y in range(PAR_TOP + 3, PAR_BOT + 1):
            L.set(x, y, C('#0d0818'))
            L.set(x + 1, y, C('#322452'))
    for _ in range(40):                                # grime
        L.set(rng.randint(EDGE_X, W - 1), rng.randint(PAR_TOP + 4, PAR_BOT), C('#100a1c'))
    # the roof surface, lighter toward the back where the parapet bounces light
    for y in range(ROOF_Y0, ROOF_Y1 + 1):
        t = (y - ROOF_Y0) / float(ROOF_Y1 - ROOF_Y0)
        for x in range(EDGE_X, W):
            L.set(x, y, ramp_at(CONCRETE[:4], 2.2 - t * 1.6, x, y, .8))
    for sy in (121, 126):                              # membrane seams
        for x in range(EDGE_X, W):
            L.set(x, sy, C('#100a1c'))
            L.set(x, sy + 1, C('#281b44'))
    for sy0, sy1, off in ((ROOF_Y0, 120, 70), (122, 125, 45), (127, ROOF_Y1, 100)):
        for x in range(EDGE_X + off % 50, W, 62):
            for y in range(sy0, sy1 + 1):
                L.set(x, y, C('#100a1c'))
                L.set(x + 1, y, C('#281b44'))
    for _ in range(170):                               # gravel
        L.set(rng.randint(EDGE_X, W - 1), rng.randint(ROOF_Y0, ROOF_Y1),
              rng.choice([C('#312250'), C('#100a1c'), C('#211638')]))
    # the front lip, and the face of the building below it
    for x in range(EDGE_X, W):
        L.set(x, ROOF_Y1 + 1, C('#72609e'))
        L.set(x, ROOF_Y1 + 2, C('#3a2c5c'))
        L.set(x, LIP_Y1, C('#0d0818'))
    for y in range(LIP_Y1 + 1, H):
        for x in range(EDGE_X, W):
            L.set(x, y, mix(ramp_at(CONCRETE[:3], 1.4 - (y - LIP_Y1) / 12.0, x, y, .8), INK, .25))
    # the building's end: a rim of alley light down its corner
    for y in range(PAR_TOP, H):
        L.set(EDGE_X, y, mix(L.get(EDGE_X, y), C('#ff7ac8'), .62))
        L.set(EDGE_X + 1, y, mix(L.get(EDGE_X + 1, y), C('#ff7ac8'), .22))
    # windows of the flats below the roof
    wins = new_layer('roof-face')
    BG.append(wins)
    for (x, c) in ((52, WARM[0]), (53, WARM[0]), (86, COOL[2]), (87, COOL[2]), (131, WARM[1]), (132, WARM[1]),
                   (174, WARM[2]), (175, WARM[2]), (211, COOL[0]), (212, COOL[0]), (248, WARM[0]), (249, WARM[0])):
        rect(wins, x, 138, 1, 3, c, True)
    for x in (66, 118, 160, 196, 234):                 # blinds, dark windows
        rect(wins, x, 138, 3, 3, C('#0b1220'))
    for x in (60, 104, 148, 190, 228):                 # AC boxes
        rect(wins, x, 136, 5, 2, C('#312350'))
        wins.set(x + 1, 137, C('#1a112e'))
    for y in range(LIP_Y1 + 1, H):                     # a drainpipe at the corner
        wins.set(EDGE_X + 3, y, C('#312350'))
        wins.set(EDGE_X + 4, y, C('#1a112e'))
    return L


def puddles():
    """Wet roof: dark water holding the glow of the lights nearest each puddle."""
    L = new_layer('puddles')
    for (cx, cy, rx, ry, hi) in ((52, 124, 8, 1.6, '#5a3a68'), (122, 128, 9, 1.4, '#58b8d8'),
                                 (178, 129, 7, 1.2, '#6a58b0'), (206, 125, 6, 1.2, '#d09860')):
        for (x, y) in blob_pts(cx, cy, rx, ry):
            L.set(x, y, C('#0a0820'))
        for (x, y) in blob_pts(cx - 1, cy - .5, rx * .6, ry * .4):
            L.set(x, y, C(hi))
    return L


def hut():
    """A stair hut at the far end of the roof: a steel door, a lamp, vents."""
    L = new_layer('hut')
    BG.append(L)
    x0, x1, y0, y1 = 224, 250, 94, 128
    body = [C('#171028'), C('#1c142f'), C('#221938')]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            L.set(x, y, ramp_at(body, 1.8 - (y - y0) / 17.0, x, y, .8))
    for x in range(x0 - 1, x1 + 2):                    # the lip
        L.set(x, y0 - 1, C('#72609e'))
        L.set(x, y0, C('#3a2c5c'))
        L.set(x, y0 + 1, C('#0d0818'))
    for y in range(y0, y1 + 1):                        # side shading
        L.set(x1, y, C('#0d0818'))
        L.set(x0, y, C('#322452'))
    for k in range(3):                                 # panel seams
        for x in range(x0, x1 + 1):
            L.set(x, y0 + 8 + k * 9, C('#100a1c'))
    # the steel door with a wired-glass slit
    dx0, dx1, dy0 = 232, 242, 108
    rect(L, dx0 - 1, dy0 - 1, dx1 - dx0 + 3, y1 - dy0 + 2, C('#403164'))
    rect(L, dx0, dy0, dx1 - dx0 + 1, y1 - dy0 + 1, C('#100a1f'))
    rect(L, dx0 + 2, dy0 + 2, 7, 5, C('#070b12'))
    for yy in range(dy0 + 2, dy0 + 7):
        L.set(dx0 + 5, yy, C('#22153e'))
    L.set(dx1 - 1, dy0 + 11, C('#8f7cbc'))             # handle
    # a caged lamp over the door
    for (x, y) in blob_pts(237, 103, 2.4, 1.6):
        L.set(x, y, C('#ffe2a8'), True)
    for x in range(234, 241):
        L.set(x, 101, C('#120d1f'))
    # vents and a pipe up the side
    rect(L, 226, 99, 4, 3, C('#312350'))
    for x in (226, 228):
        L.set(x, 100, C('#0d0818'))
    for y in range(y0 - 6, y0):
        L.set(246, y, C('#312350'))
        L.set(247, y, C('#120d1f'))
    rect(L, 245, y0 - 7, 4, 2, C('#3a2c5c'))
    BEACONS.append((248, y0 - 8, RED_N))
    return L


def hut_light():
    """The lamp's warm cone on the hut, the roof and the parapet."""
    glow(BG, 237, 104, 14, (255, 190, 100), amax=.45, levels=3, falloff=1.2, ex=1.0, ey=.9, skip_lum=.66)
    glow(BG, 237, 127, 16, (255, 190, 100), amax=.3, levels=3, falloff=1.2, ex=1.4, ey=.5, skip_lum=.66)


def stage():
    roof()
    puddles()
    hut()


# ----------------------------------------------------------------------------
# the detector: a mast of patch antennas, a station box, solar panels, cables
# ----------------------------------------------------------------------------
MAST_X = 138
METAL = [C('#1c132f'), C('#312350'), C('#443568'), C('#72609e'), C('#a4b6cc')]
PCB_E, PCB, PCB_L = C('#0b2230'), C('#2f7f9f'), C('#5bb6d2')
GOLD, GOLD_L, GOLD_DK = C('#d8b24f'), C('#f6dc8a'), C('#8e6e22')
CABLE_BLACK, CABLE_HI = C('#0a0611'), C('#30234e')
CABLE_ORANGE, CABLE_ORANGE_HI = C('#e0752a'), C('#ffb264')
CABLE_WHITE = C('#c9d3e0')

# the antennas the pings fly to: name -> (x, y, w, h), and which way they face
PATCHES = {
    'hl': (128, 72, 3, 8),       # the head's left face
    'hc': (135, 72, 7, 8),       # the head's front face
    'hr': (146, 72, 3, 8),       # the head's right face
    'al': (119, 84, 5, 9),       # crossarm, left
    'ar': (153, 84, 5, 9),       # crossarm, right
}


def patch_face(L, x, y, w, h):
    """A patch antenna seen face-on: a teal board with a gold square on it.
    Narrow ones (3 wide) are side faces, foreshortened."""
    for j in range(h):
        for i in range(w):
            edge = i in (0, w - 1) or j in (0, h - 1)
            L.set(x + i, y + j, PCB_E if edge else (PCB_L if (i == 1 or j == 1) else PCB))
    if w >= 5:
        gx0, gx1, gy0, gy1 = x + 2, x + w - 3, y + 2, y + h - 3
        for j in range(gy0, gy1 + 1):
            for i in range(gx0, gx1 + 1):
                c = GOLD
                if i == gx0 or j == gy0:
                    c = GOLD_L
                if i == gx1 or j == gy1:
                    c = GOLD_DK
                L.set(i, j, c)
    else:
        for j in range(y + 2, y + h - 2):
            L.set(x + 1, j, GOLD_L if j == y + 2 else GOLD)


def sag(p0, p1, depth, n=None):
    """Points along a hanging cable between two points."""
    n = n or max(4, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 2))
    pts = []
    for k in range(n + 1):
        t = k / float(n)
        pts.append((int(round(p0[0] + (p1[0] - p0[0]) * t)),
                    int(round(p0[1] + (p1[1] - p0[1]) * t + depth * 4 * t * (1 - t)))))
    return pts


def cable(L, pts, col, hi=None, thick=1):
    """A cable along a polyline, with a light edge on top where it is free."""
    cells = []
    for (a, b) in zip(pts, pts[1:]):
        cells += line_pts(a[0], a[1], b[0], b[1])
    cset = set(cells)
    for (x, y) in cells:
        for t in range(thick):
            L.set(x, y + t, col)
    if hi is not None:
        for (x, y) in cells:
            if (x, y - 1) not in cset and L.get(x, y - 1) is None:
                L.set(x, y - 1, hi)


def coil(L, cx, cy, rx, ry, col, hi):
    """Slack cable coiled up on the roof."""
    ring = set()
    for a in range(0, 360, 7):
        ring.add((int(round(cx + rx * math.cos(math.radians(a)))), int(round(cy + ry * math.sin(math.radians(a))))))
    for (x, y) in ring:
        L.set(x, y, col)
    for (x, y) in ring:
        if (x, y - 1) not in ring and L.get(x, y - 1) is None:
            L.set(x, y - 1, hi)


def mast():
    L = new_layer('mast')
    BG.append(L)
    x = MAST_X
    # the pole, 3 wide: lit on the left, shaded on the right
    for y in range(66, 126):
        L.set(x - 2, y, C('#574388'))
        L.set(x - 1, y, METAL[2])
        L.set(x, y, METAL[1])
    for y in (72, 84, 96, 108, 118):                           # clamps
        for dx in range(-3, 2):
            L.set(x + dx, y, METAL[3] if dx < 0 else METAL[0])
    # tripod and ballast
    for (a, b) in (((x - 1, 112), (x - 9, 125)), ((x, 112), (x + 8, 125))):
        for (px, py) in line_pts(a[0], a[1], b[0], b[1]):
            L.set(px, py, METAL[1])
            L.set(px + 1, py, METAL[0])
    for (px, py) in line_pts(x - 6, 119, x + 5, 119):
        L.set(px, py, METAL[1])
    for bx in (x - 11, x + 6):
        for j in range(4):
            for i in range(6):
                L.set(bx + i, 122 + j, C('#604f86') if j == 0 else (C('#3a2c5c') if i < 5 else C('#231a38')))
    # the whip on top, with its beacon recorded for blinking
    for y in range(56, 70):
        L.set(x, y, METAL[4] if y % 5 else METAL[3])
    BEACONS.append((x, 55, RED_N))
    # head: housing, then a patch on each face
    for y in range(70, 82):
        for xx in range(x - 7, x + 8):
            L.set(xx, y, C('#1e1532'))
    for xx in range(x - 7, x + 8):
        L.set(xx, 70, METAL[3])
        L.set(xx, 81, METAL[0])
    for k in ('hl', 'hc', 'hr'):
        patch_face(L, *PATCHES[k])
    # crossarm with a patch at each end
    for xx in range(x - 16, x + 17):
        L.set(xx, 92, METAL[3])
        L.set(xx, 93, METAL[1])
    for k in ('al', 'ar'):
        px, py, pw, ph = PATCHES[k]
        patch_face(L, px, py, pw, ph)
        for yy in range(py + ph, 92):
            L.set(px + pw // 2, yy, METAL[2])
    # coax down the pole to the station box
    for y in range(82, 100):
        L.set(x - 4, y, CABLE_BLACK)
        L.set(x - 5, y, CABLE_HI) if y % 3 == 0 else None
    for (a, b, d) in (((PATCHES['al'][0] + 2, 93), (x - 3, 98), 2), ((PATCHES['ar'][0] + 2, 93), (x + 2, 98), 2)):
        cable(L, sag(a, b, d), CABLE_BLACK, CABLE_HI)
    # the station box
    bx0, by0, bw, bh = x - 5, 100, 11, 11
    for j in range(bh):
        for i in range(bw):
            L.set(bx0 + i, by0 + j, METAL[3] if j == 0 else (C('#443568') if j == 1 else C('#261942')))
    for j in range(2, bh):
        L.set(bx0, by0 + j, METAL[2])
        L.set(bx0 + bw - 1, by0 + j, METAL[0])
    for i in range(bw):
        L.set(bx0 + i, by0 + bh - 1, METAL[0])
    for i in (1, 9):                                           # screws
        L.set(bx0 + i, by0 + 2, METAL[4])
    for i in range(3):                                         # a label
        L.set(bx0 + 2 + i, by0 + 4, C('#c9d3e0'))
    for i in (2, 4, 6):
        L.set(bx0 + i, by0 + 7, C('#130c22'))
    for dx in (-2, 0, 2):                                      # glands underneath
        L.set(x + dx, by0 + bh, METAL[0])
        L.set(x + dx, by0 + bh + 1, METAL[0])
    return L


def station_leds():
    """The three switch-line LEDs on the box front: lit differently each time
    the switch steps to another sector."""
    x, y = MAST_X, 107
    cols = (C('#5aff8a'), C('#ffcf4a'), C('#ff4a5a'))
    return [(x - 3 + 2 * i, y, cols[i]) for i in range(3)]


def solar():
    L = new_layer('solar')
    BG.append(L)
    frame_hi, frame_s, frame_lo = C('#b4c0d4'), C('#716292'), C('#312648')
    panels = ((156, 117), (176, 117), (196, 117))
    for (x0, y0) in panels:
        w, h = 17, 9
        face = poly_pts([(x0 + 2, y0), (x0 + w + 1, y0), (x0 + w - 1, y0 + h - 1), (x0, y0 + h - 1)])
        for (x, y) in face:
            L.set(x, y, C('#10285a'))
        for (x, y) in face:                                      # cells: a lit corner on each
            cx, cy = (x - x0) % 6, (y - y0) % 4
            if cx in (0,) or cy == 0:
                L.set(x, y, C('#08183a'))
            elif cx == 1 and cy == 1:
                L.set(x, y, C('#3a78d0'))
            elif (x + y) % 7 == 0:
                L.set(x, y, C('#1c4688'))
        for (x, y) in face:                                      # a sheen across the glass
            if (x - x0) - 2 * (y - y0) in (6, 7):
                L.set(x, y, mix(L.get(x, y), C('#9fd0ff'), .45))
        for k in range(h):                                       # the frame
            lx, rx = x0 + int(round(2 * (1 - k / float(h - 1)))), x0 + w + int(round(1 - 2 * k / float(h - 1)))
            L.set(lx, y0 + k, frame_s)
            L.set(rx, y0 + k, frame_lo)
        for x in range(x0 + 2, x0 + w + 2):
            L.set(x, y0, frame_hi)
        for x in range(x0, x0 + w):
            L.set(x, y0 + h - 1, frame_lo)
        for lx in (x0 + 2, x0 + w - 3):                          # legs
            L.set(lx, y0 + h, METAL[1])
            L.set(lx, y0 + h + 1, METAL[0])
    # a battery and charge controller beside the mast's right foot
    for j in range(7):
        for i in range(8):
            L.set(148 + i, 120 + j, C('#4a3b6c') if j == 0 else (C('#2b1e4a') if i < 7 else C('#120d1f')))
    for i in range(3):
        L.set(150 + i, 123, CABLE_ORANGE)
    L.set(154, 122, C('#5aff8a'), True)
    return L


def mast_cables():
    """Cables everywhere, none of them tidy."""
    L = new_layer('cables')
    # panel to panel to battery: orange and black runs under the panels
    for (a, b, d) in (((165, 126), (156, 125), 2), ((185, 126), (172, 128), 2), ((205, 126), (190, 128), 2),
                      ((196, 127), (156, 129), 2)):
        cable(L, sag(a, b, d), CABLE_BLACK, CABLE_HI)
    for (a, b, d) in (((164, 127), (156, 123), 1), ((184, 127), (170, 129), 2)):
        cable(L, sag(a, b, d), CABLE_ORANGE, CABLE_ORANGE_HI)
    # up the pole to the station box, loosely taped
    for y in range(111, 124):
        L.set(MAST_X + 2, y, CABLE_ORANGE if y % 2 else CABLE_BLACK)
    # the mess between the mast and the laptop
    cable(L, sag((MAST_X + 1, 124), (111, 127), 2), CABLE_BLACK, CABLE_HI)
    cable(L, sag((MAST_X, 125), (111, 128), 3), CABLE_ORANGE, CABLE_ORANGE_HI)
    cable(L, sag((MAST_X - 2, 125), (111, 126), 3, 22), CABLE_WHITE)
    for (px, py) in ((110, 126), (110, 127)):                     # a plug in the laptop's side
        L.set(px, py, C('#c9d3e0'))
    cable(L, sag((MAST_X + 3, 126), (122, 129), 2), CABLE_BLACK, CABLE_HI)
    coil(L, 124, 126, 4, 1.4, CABLE_BLACK, CABLE_HI)
    for (x, y) in ((126, 125), (119, 128), (131, 125)):          # cable ties
        L.set(x, y, C('#e8eef6'))
    return L


def mast_light():
    """A cool wash of city light down the mast."""
    glow(BG, MAST_X, 100, 16, (110, 170, 220), amax=.18, levels=2, falloff=1.1, ex=.7, ey=2.2, skip_lum=.62)


# ----------------------------------------------------------------------------
# the laptop on its crate, and what mapper.py shows
# ----------------------------------------------------------------------------
SX0, SY0, SW, SH = 87, 112, 22, 12      # the display, in picture pixels
OBS = (14, 9)                           # this station, on the little map (display coordinates)
NODES = ((3, 8), (9, 2), (19, 3))       # other stations of the mesh, on the map

RED_DOT, RED_HOT, RED_LINE, RED_TRAIL = C('#ff2a45'), C('#ff8a9a'), C('#c42340'), C('#7a1a2e')


def laptop():
    L = new_layer('laptop')
    BG.append(L)
    # lid: bezel round the display
    for y in range(SY0 - 1, SY0 + SH + 1):
        for x in range(SX0 - 1, SX0 + SW + 1):
            L.set(x, y, C('#120d1c'))
    for x in range(SX0 - 1, SX0 + SW + 1):
        L.set(x, SY0 - 1, C('#3b2c5a'))
        L.set(x, SY0 + SH, C('#07050c'))
    for y in range(SY0, SY0 + SH):
        L.set(SX0 - 1, y, C('#2a1e42'))
        L.set(SX0 + SW, y, C('#07050c'))
    L.set(SX0 + SW // 2, SY0 - 1, C('#1f6a3a'))           # webcam
    # hinge, then the keyboard deck, wider toward us
    for x in range(SX0 - 2, SX0 + SW + 2):
        L.set(x, SY0 + SH + 1, C('#211734'))
    for x in range(SX0 - 3, SX0 + SW + 3):
        L.set(x, SY0 + SH + 2, C('#413260'))
        L.set(x, SY0 + SH + 3, C('#1a122a'))
    for x in range(SX0 - 3, SX0 + SW + 3, 2):             # keys
        L.set(x, SY0 + SH + 2, C('#5d4c80'))
    for x in range(SX0 - 4, SX0 + SW + 4):                # the front lip
        L.set(x, SY0 + SH + 4, C('#0e0818'))
    return L


def display_pixels(L, on):
    """The little map: this station at the bottom, other stations of the mesh
    joined by their links. `on` is the lit version, drawn over the dim one."""
    ox, oy = SX0, SY0
    if on:
        base, grid, link, node, cross, hot = C('#08121e'), C('#102a40'), C('#1f98b0'), C('#5ee0f5'), C('#6ae6ff'), C('#e8fdff')
        title, led = C('#88ff99'), C('#5aff8a')
    else:
        base, grid, link, node, cross, hot = C('#04070b'), C('#08111b'), C('#0d3a46'), C('#14606e'), C('#1f8fa3'), C('#3aa8bc')
        title, led = C('#1f5a2e'), C('#14502a')
    rect(L, ox, oy, SW, SH, base)
    for gx in (5, 11, 17):
        for y in range(1, SH):
            L.set(ox + gx, oy + y, grid)
    for gy in (4, 8):
        for x in range(SW):
            L.set(ox + x, oy + gy, grid)
    # title strip: a squiggle that stands for "mapper.py"
    for x in range(SW):
        L.set(ox + x, oy, C('#04070b') if not on else C('#050c14'))
    for dx in (1, 2, 4, 6, 7, 9, 10):
        L.set(ox + dx, oy, title)
    L.set(ox + SW - 2, oy, led, True)
    # the mesh: other stations and the links between them
    pts = [OBS] + list(NODES)
    for (a, b) in ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3)):
        for (x, y) in line_pts(pts[a][0], pts[a][1], pts[b][0], pts[b][1]):
            if L.get(ox + x, oy + y) in (base, grid):
                L.set(ox + x, oy + y, link)
    for (nx, ny) in NODES:
        rect(L, ox + nx - 1, oy + ny - 1, 2, 2, node)
    cx, cy = OBS
    for d in (-2, -1, 1, 2):
        L.set(ox + cx + d, oy + cy, cross)
        L.set(ox + cx, oy + cy + d, cross)
    L.set(ox + cx, oy + cy, hot)


def dot_pixels(L, pos, hot=True):
    x, y = SX0 + pos[0], SY0 + pos[1]
    rect(L, x, y, 2, 2, RED_DOT)
    L.set(x, y, RED_HOT if hot else RED_DOT, True)


def trail_pixel(L, pos):
    L.set(SX0 + pos[0], SY0 + pos[1], RED_TRAIL, True)


def bearing_pixels(L, pos):
    """The ray from this station through the drone, a little past it."""
    ox, oy = SX0 + OBS[0], SY0 + OBS[1]
    dx, dy = pos[0] - OBS[0], pos[1] - OBS[1]
    n = math.hypot(dx, dy)
    ex, ey = SX0 + pos[0] + dx / n * 2, SY0 + pos[1] + dy / n * 2
    for (x, y) in line_pts(ox, oy, int(round(ex)), int(round(ey))):
        if (x, y) != (ox, oy) and SX0 <= x < SX0 + SW and SY0 + 1 <= y < SY0 + SH:
            L.set(x, y, RED_LINE, True)


def screen_glare():
    L = new_layer('screen-glare', alpha=.07)
    for (x, y) in poly_pts([(SX0 + 3, SY0), (SX0 + 9, SY0), (SX0 + 5, SY0 + SH), (SX0 - 1, SY0 + SH)]):
        if SX0 <= x < SX0 + SW:
            L.set(x, y, C('#ffffff'))
    return L


def laptop_light():
    """The screen is the only light on the roof that is not the city's."""
    glow(BG, SX0 + SW // 2, SY0 + 6, 1, (90, 200, 230), amax=.4, levels=3, falloff=.9, ex=30, ey=19, skip_lum=.7)
    glow(BG, SX0 + SW // 2, 127, 1, (90, 200, 230), amax=.3, levels=3, falloff=.9, ex=30, ey=7, skip_lum=.7)


def screen_idle():
    L = new_layer('screen')
    display_pixels(L, False)
    return L


def radar():
    """A faint sweep turning round this station, so the map looks alive."""
    frames = seq_frames(8, 3.2)
    ox, oy = SX0 + OBS[0], SY0 + OBS[1]
    for k in range(8):
        cls, style = frames[k]
        L = new_layer('radar-%d' % k, anim=cls, style=style, alpha=.32)
        a = math.radians(k * 45)
        ex, ey = ox + 11 * math.cos(a), oy - 11 * math.sin(a)
        for (x, y) in line_pts(ox, oy, int(round(ex)), int(round(ey))):
            if (x, y) != (ox, oy) and SX0 <= x < SX0 + SW and SY0 + 1 <= y < SY0 + SH:
                L.set(x, y, CYAN_N)


# ----------------------------------------------------------------------------
# the hooded figure: a rig of joints drawn as a black silhouette
# ----------------------------------------------------------------------------
HUMAN = C('#08060e')
RIM_COOL, RIM_RED = C('#2fb4c8'), C('#b02a9a')
EMBER, EMBER_HI = C('#ff8a2a'), C('#ffd9a0')
CIG_PAPER = C('#d8d2c4')
FLAME, FLAME_HI = C('#ff9a30'), C('#fff2b0')

# Poses are written facing left, with the hip at (0, 0) and y pointing down.
#   chest: where the shoulders meet the torso     head: centre of the hood
#   tip:   the back of the hood                   arm/arm2: shoulder, elbow, hand
#   leg/leg2: knee, foot                          cig: (hand, tip) of a cigarette
POSES = {
    # sitting on the roof's edge, hand at his mouth
    'sit_a': dict(chest=(-1.5, -8), head=(-3, -12.3), tip=(1.8, -11.3),
                  arm=((-2, -8), (-5, -5.5), (-6.2, -10.2)), arm2=((-1, -8), (-3.6, -4.4), (-5.6, -2.8)),
                  leg=((-7, -.3), (-7.4, 8.2)), leg2=((-6.4, .8), (-6.2, 8.8)), cig=((-6.2, -10.2), (-8.9, -10.8))),
    # the hand drops to his knee; he looks up and lets the smoke go
    'sit_b': dict(chest=(-1.0, -8.3), head=(-2.4, -12.8), tip=(2.4, -12.3),
                  arm=((-1.5, -8), (-3.6, -4), (-6.5, -2.6)), arm2=((-.5, -8), (-2.8, -4.4), (-5.2, -2.4)),
                  leg=((-7, -.3), (-7.0, 8.6)), leg2=((-6.4, .8), (-6.6, 9.0)), cig=((-6.5, -2.6), (-9.0, -1.9))),
    # he hears something and looks back over his shoulder
    'sit_look': dict(chest=(-1.0, -8.2), head=(-1.0, -12.6), tip=(-5.2, -11.6),
                     arm=((-1.5, -8), (-3.6, -4), (-6.5, -2.6)), arm2=((-.5, -8), (-2.8, -4.4), (-5.2, -2.4)),
                     leg=((-7, -.3), (-7.0, 8.6)), leg2=((-6.4, .8), (-6.6, 9.0)), cig=((-6.5, -2.6), (-9.0, -1.9))),
    # winding up
    'sit_wind': dict(chest=(-.2, -8.2), head=(-1.8, -12.6), tip=(2.8, -12.2),
                     arm=((-1, -8), (1.5, -7), (2.6, -11.5)), arm2=((-.5, -8), (-2.8, -4.4), (-5.2, -2.4)),
                     leg=((-7, -.3), (-7.0, 8.6)), leg2=((-6.4, .8), (-6.6, 9.0)), cig=((2.6, -11.5), (0.4, -11.9))),
    # the flick
    'sit_throw': dict(chest=(-2.0, -8), head=(-3.4, -12.4), tip=(1.4, -11.4),
                      arm=((-2.6, -8), (-6.4, -9.2), (-10.4, -11.4)), arm2=((-1, -8), (-3.6, -4.4), (-5.6, -2.8)),
                      leg=((-7, -.3), (-7.4, 8.2)), leg2=((-6.4, .8), (-6.2, 8.8)), cig=None),
    'stand': dict(chest=(0, -10), head=(-.6, -14.8), tip=(3.4, -13.9),
                  arm=((0, -9.5), (-1.2, -4.5), (-1.4, .2)), arm2=((.5, -9.5), (1.4, -4.4), (1.8, .4)),
                  leg=((-1.2, 6.5), (-1.6, 13)), leg2=((1.6, 6.6), (2.0, 13)), cig=None),
    'crouch': dict(chest=(-2.2, -7.2), head=(-3.8, -11.2), tip=(.6, -10.4),
                   arm=((-2.4, -7.0), (-4.8, -4.0), (-6.4, -2.8)), arm2=((-1.8, -7.0), (-3.8, -3.8), (-5.6, -2.4)),
                   leg=((-6.0, -1.6), (-6.4, 3.0)), leg2=((2.6, 1.4), (7.0, 3.0)), cig=None),
    'peek': dict(chest=(-1.8, -7.8), head=(-3.0, -12.2), tip=(1.4, -11.6),
                 arm=((-2.0, -7.6), (-4.6, -4.4), (-6.2, -2.8)), arm2=((-1.4, -7.6), (-3.6, -4.0), (-5.4, -2.4)),
                 leg=((-6.0, -1.6), (-6.4, 3.0)), leg2=((2.6, 1.4), (7.0, 3.0)), cig=None),
    'run_a': dict(chest=(-5.0, -6.8), head=(-7.8, -9.0), tip=(-3.0, -9.6),
                  arm=((-4.6, -6.4), (-7.2, -3.6), (-9.4, -4.4)), arm2=((-4.0, -6.4), (-1.4, -3.8), (.8, -4.6)),
                  leg=((-5.6, 2.4), (-8.8, 7.0)), leg2=((2.0, 3.4), (5.0, 7.4)), cig=None),
    'run_b': dict(chest=(-4.8, -7.0), head=(-7.6, -9.4), tip=(-2.8, -10.0),
                  arm=((-4.4, -6.6), (-1.8, -4.0), (.2, -5.2)), arm2=((-3.8, -6.6), (-6.6, -4.0), (-8.8, -5.0)),
                  leg=((-2.6, 2.8), (-2.8, 7.4)), leg2=((-.6, 1.6), (1.0, 5.2)), cig=None),
    'run_c': dict(chest=(-5.0, -6.8), head=(-7.8, -9.0), tip=(-3.0, -9.6),
                  arm=((-4.6, -6.4), (-1.4, -3.8), (.8, -4.6)), arm2=((-4.0, -6.4), (-7.2, -3.6), (-9.4, -4.4)),
                  leg=((2.0, 3.4), (5.0, 7.4)), leg2=((-5.6, 2.4), (-8.8, 7.0)), cig=None),
    'run_d': dict(chest=(-4.8, -7.0), head=(-7.6, -9.4), tip=(-2.8, -10.0),
                  arm=((-4.4, -6.6), (-6.6, -4.0), (-8.8, -5.0)), arm2=((-3.8, -6.6), (-1.8, -4.0), (.2, -5.2)),
                  leg=((-.6, 1.6), (1.0, 5.2)), leg2=((-2.6, 2.8), (-2.8, 7.4)), cig=None),
    # a cigarette from a pocket, to the mouth, then the lighter
    'pocket': dict(chest=(0, -10), head=(-.6, -14.3), tip=(3.4, -13.4),
                   arm=((0, -9.5), (2.4, -6), (.4, -4.2)), arm2=((.5, -9.5), (1.2, -4.4), (1.6, .4)),
                   leg=((-.4, 6.5), (-.8, 13)), leg2=((.8, 6.6), (1.2, 13)), cig=None),
    'to_mouth': dict(chest=(0, -10), head=(-.8, -14.3), tip=(3.2, -13.4),
                     arm=((0, -9.5), (-2.4, -7), (-3.4, -12.4)), arm2=((.5, -9.5), (1.2, -4.4), (1.6, .4)),
                     leg=((-.4, 6.5), (-.8, 13)), leg2=((.8, 6.6), (1.2, 13)), cig=((-3.4, -12.4), (-6.2, -13.0))),
    'light': dict(chest=(-.2, -10), head=(-1.6, -14.4), tip=(2.6, -13.6),
                  arm=((-.4, -9.5), (-2.8, -7), (-5.6, -11.8)), arm2=((.2, -9.5), (-1.8, -8), (-5.4, -13.2)),
                  leg=((-.4, 6.5), (-.8, 13)), leg2=((.8, 6.6), (1.2, 13)), cig=((-4.2, -12.6), (-6.8, -13.4))),
    'exhale': dict(chest=(0, -10), head=(-.4, -14.7), tip=(3.6, -14.1),
                   arm=((0, -9.5), (-1, -4.5), (-1.2, .2)), arm2=((.5, -9.5), (1.2, -4.4), (1.6, .4)),
                   leg=((-.4, 6.5), (-.8, 13)), leg2=((.8, 6.6), (1.2, 13)), cig=((-1.2, .2), (-3.4, .8))),
    'walk_a': dict(chest=(0, -10), head=(-.8, -14.3), tip=(3.2, -13.4),
                   arm=((0, -9.5), (1.8, -5), (2.2, -1)), arm2=((.5, -9.5), (-1.8, -5), (-3.3, -1.6)),
                   leg=((-3, 5.5), (-5, 12.5)), leg2=((2, 6.5), (4.2, 12.8)), cig=((-.9, -12.6), (-3.4, -12.6))),
    'walk_b': dict(chest=(0, -10), head=(-.8, -14.3), tip=(3.2, -13.4),
                   arm=((0, -9.5), (-.6, -4.8), (-.6, -.4)), arm2=((.5, -9.5), (.8, -4.6), (1, -.2)),
                   leg=((-.5, 6.3), (-.8, 12.6)), leg2=((1.5, 5.4), (1.4, 10.8)), cig=((-.9, -12.6), (-3.4, -12.6))),
    'walk_c': dict(chest=(0, -10), head=(-.8, -14.3), tip=(3.2, -13.4),
                   arm=((0, -9.5), (-1.8, -5), (-3.3, -1.6)), arm2=((.5, -9.5), (1.8, -5), (2.2, -1)),
                   leg=((2, 6.5), (4.2, 12.8)), leg2=((-3, 5.5), (-5, 12.5)), cig=((-.9, -12.6), (-3.4, -12.6))),
    'walk_d': dict(chest=(0, -10), head=(-.8, -14.3), tip=(3.2, -13.4),
                   arm=((0, -9.5), (.8, -4.6), (1, -.2)), arm2=((.5, -9.5), (-.6, -4.8), (-.6, -.4)),
                   leg=((1.5, 5.4), (1.4, 10.8)), leg2=((-.5, 6.3), (-.8, 12.6)), cig=((-.9, -12.6), (-3.4, -12.6))),
}


def lerp_pose(a, b, t):
    """A pose part-way between two."""
    out = {}
    for k in a:
        va, vb = a[k], b[k]
        if va is None or vb is None:
            out[k] = va if t < .5 else vb
        elif isinstance(va[0], (int, float)):
            out[k] = (va[0] + (vb[0] - va[0]) * t, va[1] + (vb[1] - va[1]) * t)
        else:
            out[k] = tuple((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t) for p, q in zip(va, vb))
    return out


def human_pixels(pose, hip, face=-1):
    """The silhouette as {pixel: part}, part in body / hood / limb. face=-1
    looks left, +1 right (the pose is mirrored)."""
    hx, hy = hip
    sgn = -1 if face > 0 else 1

    def P(p):
        return (hx + sgn * p[0], hy + p[1])

    px = {}

    def add(pts, tag):
        for p in pts:
            px[p] = tag

    def limb(a, b, r, tag='limb'):
        a, b = P(a), P(b)
        add(thick_pts(a[0], a[1], b[0], b[1], r), tag)

    far_leg, far_arm = pose['leg2'], pose['arm2']
    limb((0, 0), far_leg[0], 1.8)
    limb(far_leg[0], far_leg[1], 1.6)
    f = P((far_leg[1][0] - 1.2, far_leg[1][1] + .4))
    add(blob_pts(f[0], f[1], 1.9, 1.1), 'limb')
    limb(far_arm[0], far_arm[1], 1.3)
    limb(far_arm[1], far_arm[2], 1.1)
    ch = pose['chest']
    limb((0, 0), ch, 3.5, 'body')
    hp = P((0, 0))
    add(blob_pts(hp[0], hp[1] + .2, 3.9, 2.4), 'body')                # the hem of the hoodie
    hd, tip = P(pose['head']), P(pose['tip'])
    add(blob_pts(hd[0], hd[1], 3.3, 3.6), 'hood')
    add(poly_pts([(hd[0] + sgn * 1.6, hd[1] - 2.8), tip, (hd[0] + sgn * 2.4, hd[1] + 3.0),
                  (hd[0] + sgn * 0.6, hd[1] + 3.2)]), 'hood')
    cp = P(ch)
    add(blob_pts(cp[0] + sgn * 1.2, cp[1] + 1.2, 3.9, 2.6), 'body')   # shoulders under the hood
    near_leg = pose['leg']
    limb((0, 0), near_leg[0], 2.0)
    limb(near_leg[0], near_leg[1], 1.7)
    f = P((near_leg[1][0] - 1.4, near_leg[1][1] + .4))
    add(blob_pts(f[0], f[1], 2.0, 1.2), 'limb')
    arm = pose['arm']
    limb(arm[0], arm[1], 1.5)
    limb(arm[1], arm[2], 1.3)
    return px


def human_layer(L, pose, hip, face=-1, rim=True):
    """Draw a pose into a layer: black, with a cyan rim light from the laptop
    on one side and a red one from the neon on the other."""
    px = human_pixels(pose, hip, face)
    # drop stray pixels the rounding left on their own
    for p in [p for p in px if not any((p[0] + d[0], p[1] + d[1]) in px for d in ((1, 0), (-1, 0), (0, 1), (0, -1)))]:
        del px[p]
    for p in px:
        L.set(p[0], p[1], HUMAN)
    if rim:
        for (x, y) in px:
            right_open = (x + 1, y) not in px
            left_open = (x - 1, y) not in px
            top_open = (x, y - 1) not in px
            if right_open:
                L.set(x, y, RIM_COOL)
            elif left_open:
                L.set(x, y, RIM_RED)
            elif top_open and px[(x, y)] in ('hood', 'body'):
                L.set(x, y, mix(HUMAN, RIM_COOL, .45))
    return px


def cig_pixels(pose, hip, face=-1):
    """A cigarette in the hand: its paper pixels and the ember at the end."""
    if not pose.get('cig'):
        return [], None
    hx, hy = hip
    sgn = -1 if face > 0 else 1
    (ax, ay), (bx, by) = pose['cig']
    a = (int(round(hx + sgn * ax)), int(round(hy + ay)))
    b = (int(round(hx + sgn * bx)), int(round(hy + by)))
    pts = line_pts(a[0], a[1], b[0], b[1])
    return pts[:-1], pts[-1]


# ----------------------------------------------------------------------------
# Clawd, small, in a black hoodie, hunched over the laptop
# ----------------------------------------------------------------------------
CLAWD_X, CLAWD_Y = 71, 118           # top-left of the sprite; his feet are on GROUND_Y
CP = {'k': C('#0d0915'), 'h': C('#322350'), 'c': C('#2f7f98'), 'r': C('#9a2a8a'),
      'o': C('#d97757'), 'd': C('#7c3322'), 'e': C('#150a14'), 'w': C('#bff9ff'),
      's': C('#d6dce8'), 'l': C('#b8523a'), 'L': C('#6a2a1c')}


def _row(*segs):
    s = ''.join(segs)
    assert len(s) == 13, s
    return s


CLAWD = (
    _row('....', 'h' * 5, '....'),
    _row('..h', 'k' * 7, 'c', '..'),
    _row('.h', 'k' * 9, 'c.'),
    _row('.kk', 'd' * 7, 'kc.'),
    _row('.kk', 'oeoooeo', 'kc.'),
    _row('.kk', 'oeoooeo', 'kc.'),
    _row('.kkk', 'o' * 5, 'kkc.'),
    _row('.kkkk', 's', 'k', 's', 'kkkc.'),
    _row('kkkkk', 's', 'k', 's', 'kkkkc'),
    _row('kk', 'h' * 9, 'kc'),
    _row('..ll.l.l.ll..'[:13]),
)


def clawd_body(L):
    sprite(L, CLAWD_X, CLAWD_Y, CLAWD, CP, emit='w')
    for j in range(2, 10):                      # a red rim from the neon on his left edge
        for i in range(0, 4):
            if CLAWD[j][i] == 'k':
                L.set(CLAWD_X + i, CLAWD_Y + j, CP['r'])
                break


def clawd_eyes(L, kind):
    """Eye overlays: 'blink', 'up' (watching the sky) and 'wide' (alarmed)."""
    x0, y0 = CLAWD_X, CLAWD_Y
    for ex in (4, 8):
        if kind == 'blink':
            L.set(x0 + ex, y0 + 4, CP['o'])
        elif kind == 'up':
            L.set(x0 + ex, y0 + 5, CP['o'])
            L.set(x0 + ex, y0 + 3, CP['e'])
        elif kind == 'wide':
            L.set(x0 + ex, y0 + 3, CP['e'])
            L.set(x0 + ex - 1, y0 + 4, CP['w'], True)
            L.set(x0 + ex + 1, y0 + 4, CP['w'], True)


def clawd_arm(L, row):
    """The sleeve reaching the keyboard, one key row up or down."""
    x0, y0 = CLAWD_X, CLAWD_Y
    L.set(x0 + 13, y0 + row, CP['k'])
    L.set(x0 + 14, y0 + row, CP['k'])
    L.set(x0 + 15, y0 + row, CP['o'])
    L.set(x0 + 13, y0 + row, CP['c'])


BUBBLE = (
    ".ooooo.",
    "oWWWWWo",
    "oWWRWWo",
    "oWWRWWo",
    "oWWRWWo",
    "oWWWWWo",
    "oWWRWWo",
    "oWWWWWo",
    ".ooooo.",
    "..oWo..",
    "...o...",
)


def bubble(L):
    """The "!" over his head."""
    pal = {'o': C('#0d0915'), 'W': C('#f4f6fa'), 'R': C('#ff2a45')}
    sprite(L, CLAWD_X + 3, CLAWD_Y - 11, BUBBLE, pal, emit='WR')


# ----------------------------------------------------------------------------
# the story, on one clock (T_LOOP seconds)
#
#    0.0  calm: he smokes on the edge, Clawd types
#    4.2  the first ping lands: the map lights up, Clawd shouts "!"
#    5.0  he flicks the cigarette off the roof and runs for cover next to Clawd
#    5.4  the first drone enters from the right, flying to the left;
#         pings fly from it to the patch antennas, red dots and lines on the map
#   11.8  a second, farther drone crosses the other way
#   18.4  the coast is clear: he stands, lights another cigarette,
#   22.1  walks back along the roof, sits down on the edge and carries on
# ----------------------------------------------------------------------------
SEAT = (EDGE_X + 6, 126)
FEET_Y = 125.4                       # where the soles of standing feet land
COVER_X = 62                         # where he crouches, next to Clawd
T_ALERT = 4.2
T_CLEAR = 19.2
ARRIVE_A = [T_ALERT + .9 * k for k in range(7)]       # a ping from drone A lands on the mast
ARRIVE_B = [12.6 + .9 * k for k in range(7)]
FLIGHT = 1.15                                          # seconds a ping takes to reach the mast


def drone_a(t):
    """The first drone: right to left, close and fast."""
    return 268 - 52.0 * (t - 5.4), 55 + 4 * math.sin((t - 5.4) * 1.5)


def drone_b(t):
    """The second: left to right, higher and farther off."""
    return -14 + 46.0 * (t - 11.8), 41 + 3 * math.sin((t - 11.8) * 1.8)


# ---- the people ------------------------------------------------------------
POSES['rise_a'] = lerp_pose(POSES['sit_throw'], POSES['crouch'], .7)
POSES['duck'] = lerp_pose(POSES['run_b'], POSES['crouch'], .6)
POSES['rise_b'] = lerp_pose(POSES['crouch'], POSES['stand'], .55)
POSES['sit_down1'] = lerp_pose(POSES['stand'], POSES['sit_b'], .45)
POSES['sit_down2'] = lerp_pose(POSES['stand'], POSES['sit_b'], .8)


def on_ground(key, x):
    """The hip that puts a pose's lowest foot on the roof."""
    p = POSES[key]
    return (x, FEET_Y - max(p['leg'][1][1], p['leg2'][1][1]))


def human_frames():
    """(start, end, pose, face, hip, lit): what the figure is doing when."""
    F = []
    sit = lambda a, b, k: F.append((a, b, k, -1, SEAT, True))
    sit(0.0, 2.2, 'sit_a')
    sit(2.2, 3.5, 'sit_b')
    sit(3.5, 4.3, 'sit_a')
    sit(4.3, 4.65, 'sit_look')
    sit(4.65, 4.95, 'sit_wind')
    sit(4.95, 5.3, 'sit_throw')
    F.append((5.3, 5.5, 'rise_a', 1, (SEAT[0] + 1, 119.5), False))
    cyc = ('run_a', 'run_b', 'run_c', 'run_d')
    x0, x1, n = SEAT[0] + 2, COVER_X, 8
    for k in range(n):
        x = x0 + (x1 - x0) * k / float(n - 1)
        F.append((5.5 + k * .125, 5.5 + (k + 1) * .125, cyc[k % 4], 1, on_ground(cyc[k % 4], int(round(x))), False))
    F.append((6.5, 6.8, 'duck', 1, (COVER_X, 120), False))
    cx = COVER_X
    cr = on_ground('crouch', cx)
    pk = on_ground('peek', cx)
    # he only looks up when a searchlight is not sweeping across his hiding place
    low = [(6.8, 7.1), (7.8, 10.4), (11.0, 13.0), (13.7, 14.6), (15.4, 17.0), (17.8, 18.4)]
    up = [(7.1, 7.8), (10.4, 11.0), (13.0, 13.7), (14.6, 15.4), (17.0, 17.8)]
    for (a, b) in low:
        F.append((a, b, 'crouch', 1, cr, False))
    for (a, b) in up:
        F.append((a, b, 'peek', 1, pk, False))
    F.append((18.4, 18.7, 'rise_b', 1, (COVER_X, 117), False))
    F.append((18.7, 19.2, 'stand', -1, on_ground('stand', COVER_X), False))
    F.append((19.2, 19.7, 'pocket', -1, on_ground('pocket', COVER_X), False))
    F.append((19.7, 20.3, 'to_mouth', -1, on_ground('to_mouth', COVER_X), False))
    F.append((20.3, 21.5, 'light', -1, on_ground('light', COVER_X), False))
    F.append((21.5, 22.1, 'exhale', -1, on_ground('exhale', COVER_X), True))
    walk = ('walk_a', 'walk_b', 'walk_c', 'walk_d')
    wx0, wx1, wn = COVER_X, SEAT[0] + 1, 8
    for k in range(wn):
        x = wx0 + (wx1 - wx0) * k / float(wn)
        key = walk[k % 4]
        F.append((22.1 + k * .4, 22.1 + (k + 1) * .4, key, -1, on_ground(key, int(round(x))), True))
    F.append((25.3, 25.7, 'sit_down1', -1, (SEAT[0], 119), True))
    F.append((25.7, 26.1, 'sit_down2', -1, (SEAT[0], 123), True))
    sit(26.1, 27.3, 'sit_b')
    sit(27.3, 28.6, 'sit_a')
    sit(28.6, 29.5, 'sit_b')
    sit(29.5, 30.0, 'sit_a')
    return F


WISP = (                             # a thread of smoke, four frames, rising
    ((0, -1), (1, -2)),
    ((1, -2), (0, -3), (1, -4)),
    ((0, -3), (-1, -4), (0, -5), (1, -6)),
    ((-1, -5), (0, -6), (-1, -7), (0, -8)),
)
SMOKE = C('#e6d2f6')


def smoke_at(group, tip, period=2.0, strength=.55, tag='smoke'):
    frames = seq_frames(4, period, phase=(tip[0] * 7 + tip[1] * 3) % 10 * .1)
    for k, pts in enumerate(WISP):
        cls, style = frames[k]
        L = new_layer('%s-%d' % (tag, k), anim=cls, style=style, groups=group, alpha=strength)
        for (dx, dy) in pts:
            L.set(tip[0] + dx, tip[1] + dy, SMOKE)


def ember_at(group, tip, bright_every=3.2, delay=0.0, glow_a=.4):
    halo = new_layer('ember-halo', groups=group, alpha=glow_a)
    for (dx, dy) in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
        halo.set(tip[0] + dx, tip[1] + dy, C('#ff7a1a'))
    L = new_layer('ember', groups=group)
    L.set(tip[0], tip[1], EMBER, True)
    cls, style = pulse('ember', .2, bright_every)
    H = new_layer('ember-hi', groups=group, anim=cls, style=style + ';animation-delay:-%gs' % delay)
    H.set(tip[0], tip[1], EMBER_HI, True)


def gvis(spans, uid):
    """A group descriptor that shows its layers only during the given spans."""
    cls, hidden = vis(spans)
    return (cls + (' h' if hidden else ''), '', uid)


def pose_group(spans_by_key):
    """One figure: every pose drawn once and parked wherever it is needed."""
    # all the poses sharing a key and a facing are one drawing, shown in several places
    for (key, face), items in spans_by_key.items():
        pose = POSES[key]
        base = items[0][2]
        offs = [(a, b, h[0] - base[0], h[1] - base[1]) for (a, b, h, lit) in items]
        if all(o[2] == 0 and o[3] == 0 for o in offs):
            offs = [(o[0], o[1]) for o in offs]
        grp = (gvis(offs, 'p-%s-%d' % (key, face)),)
        lit = items[0][3]
        body = new_layer('human-' + key, groups=grp)
        human_layer(body, pose, base, face)
        paper, ember = cig_pixels(pose, base, face)
        if paper:
            cg = new_layer('cig-' + key, groups=grp)
            for p in paper:
                cg.set(p[0], p[1], CIG_PAPER)
            if lit:
                ember_at(grp, ember, delay=(len(key) * .37) % 3)
                smoke_at(grp, (ember[0], ember[1]), period=2.0 + (len(key) % 3) * .3, tag='smoke-' + key)
            else:
                cg.set(ember[0], ember[1], CIG_PAPER)
        if key == 'light':
            flame_at(grp, ember)
        if key == 'exhale':
            smoke_at(grp, (base[0] - 3, base[1] - 17), period=1.4, strength=.7, tag='puff')


def flame_at(group, tip):
    """The lighter's flame at the end of the cigarette, flickering."""
    frames = seq_frames(2, .26)
    for k in range(2):
        cls, style = frames[k]
        L = new_layer('flame-%d' % k, groups=group, anim=cls, style=style)
        L.set(tip[0], tip[1] - 1, FLAME_HI, True)
        L.set(tip[0], tip[1] - 2, FLAME, True)
        if k == 0:
            L.set(tip[0], tip[1] - 3, FLAME, True)
            L.set(tip[0] - 1, tip[1] - 2, FLAME, True)
        else:
            L.set(tip[0] + 1, tip[1] - 2, FLAME, True)
    halo = new_layer('flame-glow', groups=group, alpha=.32)
    for (x, y) in blob_pts(tip[0], tip[1] - 1, 4.2, 3.4):
        if (x - tip[0]) ** 2 + (y - tip[1] + 1) ** 2 <= 4 or (x + y) % 2 == 0:
            halo.set(x, y, C('#ff9a30'))


def cig_flight():
    """The cigarette he flicks off the roof: an arc, then a fall into the alley."""
    hand = (SEAT[0] + POSES['sit_throw']['arm'][2][0], SEAT[1] + POSES['sit_throw']['arm'][2][1])
    x0, y0 = hand[0] - 1.0, hand[1]
    pts = []
    for k in range(0, 14):
        t = 5.05 + .1 * k
        s = t - 5.05
        pts.append((t, x0 - 15.0 * s, y0 - 7.0 * s + 62.0 * s * s))
    cls, hidden = move(pts, ref=(int(round(x0)), int(round(y0))))
    grp = ((cls + (' h' if hidden else ''), '', 'cig-flight'),)
    L = new_layer('cig-flight', groups=grp)
    bx, by = int(round(x0)), int(round(y0))
    L.set(bx + 1, by, CIG_PAPER)
    L.set(bx + 2, by, CIG_PAPER)
    L.set(bx, by, EMBER, True)
    tr = new_layer('cig-flight-trail', groups=grp, alpha=.5)
    tr.set(bx + 3, by - 1, C('#ff9a30'))
    tr.set(bx + 4, by - 2, C('#ff7a1a'))


def people():
    """Clawd, the bubble, the smoker: back to front."""
    # Clawd hops when the alert comes; everything of his moves together
    hop = tl([(0, {'y': 0}), (T_ALERT - EPS, {'y': 0}), (T_ALERT, {'y': -2}), (T_ALERT + .16, {'y': -2}),
              (T_ALERT + .3, {'y': 0}), (T_LOOP, {'y': 0})])
    grp = ((hop, '', 'clawd-hop'),)
    body = new_layer('clawd', groups=grp)
    clawd_body(body)
    (ca, sa), (cb, sb) = seq_frames(2, .7)
    a = new_layer('clawd-arm-a', groups=grp, anim=ca, style=sa)
    clawd_arm(a, 8)
    b = new_layer('clawd-arm-b', groups=grp, anim=cb, style=sb)
    clawd_arm(b, 9)
    # eyes: wide at the alarm, then on the sky while the drones are about; a blink or two
    for kind, spans in (('wide', [(T_ALERT, 5.6)]), ('up', [(5.6, 18.0)]),
                        ('blink', [(1.4, 1.52), (9.3, 9.42), (21.2, 21.32), (27.6, 27.72), (13.9, 14.02)])):
        e = new_layer('clawd-eyes-' + kind, groups=grp + (gvis(spans, 'ce-' + kind),))
        clawd_eyes(e, kind)
    # the "!" bubble
    bub = new_layer('bubble', groups=grp + (gvis([(T_ALERT + .05, 6.7)], 'bubble'),))
    bubble(bub)
    # the smoker, and the cigarette he throws away
    spans = {}
    for (a, b_, key, face, hip, lit) in human_frames():
        spans.setdefault((key, face), []).append((a, b_, (int(round(hip[0])), int(round(hip[1]))), lit))
    order = []
    for (a, b_, key, face, hip, lit) in human_frames():
        if (key, face) not in order:
            order.append((key, face))
    pose_group(dict((k, spans[k]) for k in order))
    cig_flight()


# ---- the mesh: dotted links from the mast to the masts on other rooftops ----
WHIP = (MAST_X, 56)                     # where the links leave the mast
PING, PING_HI = C('#ff5a9a'), C('#ffd0ea')


def mesh_links():
    """Dotted cyan lines that crawl, and small packets that run along them
    after each burst of detections."""
    frames = seq_frames(4, .8)
    for ph in range(4):
        cls, style = frames[ph]
        L = new_layer('mesh-%d' % ph, anim=cls, style=style, alpha=.6)
        for (nx, ny) in MESH_NODES:
            for i, (x, y) in enumerate(line_pts(WHIP[0], WHIP[1], nx, ny)):
                if (i + ph) % 4 < 2:
                    L.set(x, y, CYAN_N)


def mesh_packets():
    for t0 in (4.6, 11.5, 19.0):
        for j, (nx, ny) in enumerate(MESH_NODES):
            t = t0 + .18 * j
            cls, hidden = move([(t, WHIP[0], WHIP[1]), (t + 1.5, nx, ny)])
            grp = ((cls + (' h' if hidden else ''), '', 'pk-%g-%d' % (t0, j)),)
            L = new_layer('packet', groups=grp)
            rect(L, WHIP[0], WHIP[1], 2, 2, C('#e8fdff'), True)
            halo = new_layer('packet-halo', groups=grp, alpha=.4)
            for (dx, dy) in ((-1, 0), (2, 0), (0, -1), (1, -1), (-1, 1), (2, 1), (0, 2), (1, 2)):
                halo.set(WHIP[0] + dx, WHIP[1] + dy, CYAN_N)


# ---- the drones ------------------------------------------------------------
DP = dict(o=C('#0f1328'), a=C('#1d2440'), b=C('#2b3660'), c=C('#40508a'),
          d=C('#6679b8'), e=C('#a4b8f0'), f=C('#e8f0ff'))
ROTOR_HI, ROTOR_LO = C('#d6e2ff'), C('#6b80c4')
LAMP = C('#fffbe0')
BEAM = (214, 238, 255)                      # the searchlight's cold white
SEARCH_ANGLES = (-75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75)     # degrees from straight down
CLIPS['sky'] = (0, 0, W, 112)               # the beams end at the parapet
CLIPS['behind'] = (0, 0, NEAR_R[0], 112)    # the second drone flies behind the near tower on the right
CLIPS['behind-ping'] = (0, 0, NEAR_R[0], H)     # and so do its pings
POOLS = []                                  # where each searchlight lands: filled by drones(), drawn later


def sym_set(L, x0, y0, wd, lx, ly, c, emit=False):
    L.set(x0 + lx, y0 + ly, c, emit)
    L.set(x0 + wd - 1 - lx, y0 + ly, c, emit)


def sym_rect(L, x0, y0, wd, lx0, ly0, lx1, ly1, c, emit=False):
    for ly in range(ly0, ly1 + 1):
        for lx in range(lx0, lx1 + 1):
            sym_set(L, x0, y0, wd, lx, ly, c, emit)


def rotor_discs(L_a, L_b, x0, y0, wd, centres, pw):
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


def drone(name, cx, y0, size, color, groups, clip=None):
    """`size`: M is 26 wide, S is 16. The arm LEDs wear `color`."""
    wd = dict(M=26, S=16)[size]
    x0 = cx - wd // 2
    P = DP
    (ca, sa), (cb, sb) = seq_frames(2, .12)
    body = new_layer('drone-' + name, groups=groups, clip=clip)
    pa = new_layer('drone-%s-rotor-a' % name, anim=ca, style=sa, groups=groups, clip=clip)
    pb = new_layer('drone-%s-rotor-b' % name, anim=cb, style=sb, groups=groups, clip=clip)
    pcls, pstyle = pulse('led', .5, 1.3)
    led = new_layer('drone-%s-led' % name, anim=pcls,
                      style=pstyle + ';animation-delay:-%.1fs' % ((cx % 7) * .17), groups=groups, clip=clip)
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
        rotor_discs(pa, pb, x0, y0, wd, (4,), 9)
        lamp = (cx, y0 + 9)
    else:
        sym_rect(body, x0, y0, wd, 1, 2, 4, 3, P['b'])
        sym_rect(body, x0, y0, wd, 1, 2, 4, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 5, 3, P['c'])
        sym_rect(body, x0, y0, wd, 5, 2, 7, 2, P['d'])
        sym_rect(body, x0, y0, wd, 5, 3, 7, 4, P['b'])
        sym_rect(body, x0, y0, wd, 6, 5, 7, 5, LAMP, True)
        sym_set(led, x0, y0, wd, 1, 3, color, True)
        sym_set(led, x0, y0, wd, 7, 4, color, True)
        rotor_discs(pa, pb, x0, y0, wd, (2,), 5)
        pb.pix.clear()
        lamp = (cx, y0 + 5)
    halo = new_layer('drone-%s-halo' % name, alpha=.3, groups=groups, clip=clip)
    for (dx, dy) in ((0, 0), (-1, 0), (1, 0), (0, 1), (0, -1), (-1, 1), (1, 1), (-2, 0), (2, 0), (0, 2)):
        halo.set(lamp[0] + dx, lamp[1] + dy, mix(color, (255, 255, 255), .3))
    lens = new_layer('drone-%s-lens' % name, alpha=.5, groups=groups, clip=clip)       # the searchlight's lens, flaring
    for (x, y) in blob_pts(lamp[0], lamp[1], 2.4, 1.8):
        lens.set(x, y, BEAM)
    star = new_layer('drone-%s-star' % name, alpha=.4, groups=groups, clip=clip)
    for d in (2, 3):
        for (dx, dy) in ((d, 0), (-d, 0), (0, d)):
            star.set(lamp[0] + dx, lamp[1] + dy, BEAM)
    return lamp


# ---- the searchlight --------------------------------------------------------
def beam_a(t):
    """Where the first drone points its light, in degrees from straight down
    (negative is to the left): a slow sweep from side to side."""
    return -10 + 38 * math.sin(2 * math.pi * (t - 5.4) / 3.4)


def beam_b(t):
    return 5 + 34 * math.sin(2 * math.pi * (t - 11.8) / 4.0)


def fade_samples(times, values):
    """Keyframes for an opacity that changes smoothly, dropping the points that
    lie on a straight run."""
    out = [(0.0, {'o': 0})]
    n = len(times)
    for i in range(n):
        if 0 < i < n - 1 and abs(values[i] - values[i - 1]) < 1e-3 and abs(values[i] - values[i + 1]) < 1e-3:
            continue
        out.append((max(times[i], out[-1][0] + 1e-3), {'o': round(values[i], 3)}))
    out.append((T_LOOP, {'o': 0}))
    return out


def beam_layers(name, apex, length_to, move_g, times, thetas, half_outer, half_core, strength, clip='sky'):
    """One translucent cone for each angle the light passes through; they
    cross-fade as it turns, so the sweep is smooth."""
    ax, ay = apex[0] + .5, apex[1] + 1.0
    for ang in SEARCH_ANGLES:
        weights = [max(0.0, 1 - abs(th - ang) / 15.0) for th in thetas]
        if max(weights) <= 0:
            continue
        g = (tl(fade_samples(times, weights)) + ' h', '', 'beam-%s-%d' % (name, ang))
        length = min(170.0, (length_to - ay) / max(.25, math.cos(math.radians(ang))))
        for (half, alpha, tag) in ((half_outer, .16 * strength, 'o'), (half_core, .3 * strength, 'c')):
            cone = new_layer('beam-%s-%d-%s' % (name, ang, tag), groups=(move_g, g), alpha=alpha, clip=clip)
            pts = [(ax, ay)] + [(ax + length * math.sin(math.radians(ang + d)),
                                 ay + length * math.cos(math.radians(ang + d))) for d in (-half, half)]
            for (x, y) in poly_pts(pts):
                cone.set(x, y, BEAM)


def pool_samples(times, pts, thetas, lamp_dy):
    """Where the light lands on the parapet, and how bright the pool is."""
    out = []
    for t, (_, x, y), th in zip(times, pts, thetas):
        hit = x + (112 - (y + lamp_dy)) * math.tan(math.radians(th))
        o = max(0.0, min(1.0, (65 - abs(th)) / 10.0))               # fades as the light turns to the horizon
        o *= max(0.0, min(1.0, (hit - 2) / 8.0)) * max(0.0, min(1.0, (254 - hit) / 8.0))
        out.append((t, o, hit))
    return out


def drones():
    for (name, fn, size, t0, t1, ref, beam_fn) in (('a', drone_a, 'M', 5.2, 11.0, (128, 48), beam_a),
                                                   ('b', drone_b, 'S', 11.6, 18.2, (128, 36), beam_b)):
        pts, t = [], t0
        while t < t1 + 1e-9:
            x, y = fn(t)
            pts.append((t, x, y))
            t += .25
        cls, hidden = move(pts, ref=ref)
        move_g = (cls + (' h' if hidden else ''), '', 'drone-' + name)
        lamp_dy = 9 if size == 'M' else 5
        bt = [t0 + i * .1 for i in range(int(round((t1 - t0) / .1)) + 1)]
        thetas = [beam_fn(t) for t in bt]
        POOLS.append((name, pool_samples(bt, [(t,) + fn(t) for t in bt], thetas, lamp_dy)))
        small = size == 'S'
        clip = 'behind' if name == 'b' else None
        # the light first, so the drone sits in front of it
        beam_layers(name, (ref[0], ref[1] + lamp_dy), 118, move_g, bt, thetas, 8 if small else 11,
                    3 if small else 4.5, .7 if small else 1.0, clip or 'sky')
        drone(name, ref[0], ref[1], size, RED_N, (move_g,), clip)


def search_pools():
    """The pools of light the searchlights throw on the parapet."""
    for name, pool in POOLS:
        samples = [(0.0, {'o': 0, 'x': 0, 'y': 0})]
        n = len(pool)
        for i, (t, o, hit) in enumerate(pool):
            if 0 < i < n - 1 and o == 0 and pool[i - 1][1] == 0 and pool[i + 1][1] == 0:
                continue
            samples.append((max(t, samples[-1][0] + 1e-3), {'o': round(o, 3), 'x': int(round(hit)) - 128, 'y': 0}))
        samples.append((T_LOOP, dict(samples[-1][1], o=0)))
        grp = ((tl(samples) + ' h', '', 'pool-' + name),)
        outer = new_layer('pool-%s-o' % name, groups=grp, alpha=.2)
        for (x, y) in blob_pts(128, 113, 10, 2.4):
            outer.set(x, y, BEAM)
        core = new_layer('pool-%s-c' % name, groups=grp, alpha=.32)
        for (x, y) in blob_pts(128, 113, 5, 1.3):
            core.set(x, y, BEAM)


# ---- the pings -------------------------------------------------------------
def patch_centre(name):
    x, y, w, h = PATCHES[name]
    return (x + w // 2, y + h // 2)


def arc_pts(radius, ang, half=38.0):
    """Pixels on an arc of a circle centred on the origin, bulging toward `ang`."""
    pts = []
    for i in range(-8, 9):
        a = ang + math.radians(half * i / 8.0)
        pts.append((int(round(radius * math.cos(a))), int(round(radius * math.sin(a)))))
    out = set()
    for (p, q) in zip(pts, pts[1:]):
        out.update(line_pts(p[0], p[1], q[0], q[1]))
    return out


def one_ping(k, pass_name, arrive, fn, strength):
    s = arrive - FLIGHT
    dx, dy = fn(s)
    if dx > 190:
        target = ('ar', 'hr')[k % 2]
    elif dx > 120:
        target = 'hc'
    else:
        target = ('al', 'hl')[k % 2]
    tx, ty = patch_centre(target)
    dist = math.hypot(dx - tx, dy - ty)
    ux, uy = (dx - tx) / dist, (dy - ty) / dist
    reach = min(dist, 125.0)
    sx, sy = tx + ux * reach, ty + uy * reach
    if sx > 248:                                   # a ping from off the picture enters at the edge
        f = (248 - tx) / (sx - tx)
        sx, sy = tx + (sx - tx) * f, ty + (sy - ty) * f
    if sx < 8:
        f = (8 - tx) / (sx - tx)
        sx, sy = tx + (sx - tx) * f, ty + (sy - ty) * f
    cls, hidden = move([(s, sx, sy), (arrive, tx, ty)], ref=(int(round(sx)), int(round(sy))))
    grp = ((cls + (' h' if hidden else ''), '', 'ping-%s-%d' % (pass_name, k)),)
    ang = math.atan2(ty - sy, tx - sx)
    ox, oy = int(round(sx)), int(round(sy))
    clip = 'behind-ping' if pass_name == 'b' else None
    front = new_layer('ping-front', groups=grp, alpha=.9 * strength, clip=clip)
    for (x, y) in arc_pts(6.5, ang):
        front.set(ox + x, oy + y, PING_HI, True)
    rear = new_layer('ping-rear', groups=grp, alpha=.55 * strength, clip=clip)
    for r in (2.5, 4.5):
        for (x, y) in arc_pts(r, ang):
            rear.set(ox + x, oy + y, PING, True)
    return target


def pings():
    flashes = {}
    for k, a in enumerate(ARRIVE_A):
        flashes.setdefault(one_ping(k, 'a', a, drone_a, 1.0), []).append((a, a + .24))
    for k, a in enumerate(ARRIVE_B):
        flashes.setdefault(one_ping(k, 'b', a, drone_b, .8), []).append((a, a + .24))
    # a patch lights up when a ping lands on it
    for name, spans in flashes.items():
        x, y, w, h = PATCHES[name]
        grp = (gvis(spans, 'flash-' + name),)
        L = new_layer('flash-' + name, groups=grp, alpha=.55)
        rect(L, x, y, w, h, C('#e8fdff'))
        halo = new_layer('flash-halo-' + name, groups=grp, alpha=.35)
        for (px, py) in outline_pts({(i, j) for i in range(x, x + w) for j in range(y, y + h)}):
            halo.set(px, py, CYAN_N)


# ---- what the map shows ----------------------------------------------------
def map_dots(fn, arrivals, row):
    """Where each ping puts a drone on the little map: east-west from how far
    along the sky it was when the ping left, so a hover shows as a cluster."""
    out = []
    for a in arrivals:
        x, y = fn(a - FLIGHT)
        mx = max(1, min(20, int(round(2 + 18.0 * (x - 20) / 230.0))))
        my = max(1, min(5, int(round(row + (y - 44) / 14.0))))
        out.append((mx, my))
    return out


def screen_story():
    """The map lights up, then red dots and rays appear as each ping lands."""
    on = new_layer('screen-on', groups=(gvis([(T_ALERT, T_CLEAR)], 'screen-on'),))
    display_pixels(on, True)
    fl = new_layer('screen-flash', groups=(gvis([(T_ALERT, T_ALERT + .1)], 'screen-flash'),), alpha=.5)
    rect(fl, SX0, SY0, SW, SH, C('#6ae6ff'))
    for dots, arrivals, end, tag in ((map_dots(drone_a, ARRIVE_A, 3), ARRIVE_A, 11.6, 'a'),
                                     (map_dots(drone_b, ARRIVE_B, 1), ARRIVE_B, T_CLEAR - .2, 'b')):
        for k, pos in enumerate(dots):
            a = arrivals[k]
            nxt = arrivals[k + 1] if k + 1 < len(arrivals) else a + .9
            cur = new_layer('dot-%s-%d' % (tag, k), groups=(gvis([(a, nxt)], 'dot-%s-%d' % (tag, k)),))
            bearing_pixels(cur, pos)
            dot_pixels(cur, pos)
            tr = new_layer('trail-%s-%d' % (tag, k), groups=(gvis([(nxt, end)], 'trail-%s-%d' % (tag, k)),))
            trail_pixel(tr, pos)


def screen_glow():
    """While the map is lit its light washes brighter over Clawd and the roof."""
    L = new_layer('screen-glow', groups=(gvis([(T_ALERT, T_CLEAR)], 'screen-glow'),), alpha=.16)
    for (x, y) in blob_pts(SX0 + SW // 2, SY0 + 10, 26, 15):
        if (x + y) % 2 == 0 and not (SX0 - 1 <= x <= SX0 + SW and SY0 - 1 <= y <= SY0 + SH):
            L.set(x, y, C('#8af4ff'))


# ---- small lights ----------------------------------------------------------
def blinkers():
    for i, (x, y, col) in enumerate(BEACONS):
        cls, style = pulse('bc', .16, 1.5 + (i % 5) * .37)
        L = new_layer('beacon-%d' % i, anim=cls, style=style + ';animation-delay:-%.2fs' % ((i * .53) % 3))
        L.set(x, y, col, True)
        halo = new_layer('beacon-halo-%d' % i, anim=cls, style=style + ';animation-delay:-%.2fs' % ((i * .53) % 3),
                         alpha=.24)
        for dy in range(-3, 4):                          # a round glow, dithered toward its edge
            for dx in range(-3, 4):
                d = math.hypot(dx, dy)
                if 0 < d <= 1.1 or (1.1 < d <= 2.5 and (dx + dy) % 2 == 0):
                    halo.set(x + dx, y + dy, col)
    # the station box: its three switch-line LEDs step through the four sectors
    frames = seq_frames(4, 1.6)
    dim = [(x, y, mix(c, INK, .72)) for (x, y, c) in station_leds()]
    base = new_layer('station-leds-dim')
    for (x, y, c) in dim:
        base.set(x, y, c)
    for ph, bits in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0))):
        cls, style = frames[ph]
        L = new_layer('station-leds-%d' % ph, anim=cls, style=style)
        Hh = new_layer('station-leds-halo-%d' % ph, anim=cls, style=style, alpha=.3)
        for b, (x, y, c) in zip(bits, station_leds()):
            if b:
                L.set(x, y, c, True)
                for (dx, dy) in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    Hh.set(x + dx, y + dy, c)
    # a few windows go dark for a moment, and the neon stutters
    rng = Rng(31)
    cand = []
    for (name, x, y, w, h, c) in WINDOWS:
        top, topc = composite_at(LAYERS, x, y)
        if top is not None and top.name == name and topc == c and y < 104:
            cand.append((x, y, w, h, c))
    for k in range(18):
        x, y, w, h, c = cand[rng.randint(0, len(cand) - 1)]
        period = 4.0 + rng.random() * 8
        cls, style = pulse('wb', .1, period)
        L = new_layer('window-blink-%d' % k, anim=cls + ' h', style=style + ';animation-delay:-%.2fs' % (rng.random() * period))
        rect(L, x, y, w, h, mix(c, INK, .8))
    # the "A" of the pink sign gives out now and then, the trident hums
    cls, style = flicker(3.7)
    L = new_layer('bar-flicker', anim=cls, style=style)
    text3(L, 12, 96 + 6, 'A', mix(PINK_D, INK, .55), emit=True, vertical=False)
    cls, style = flicker(5.3, 1.7)                     # the Meshtastic tube stutters too
    fm = new_layer('mesh-flicker', anim=cls, style=style)
    for stroke in mesh_strokes(*MESH_AT):
        for (p, q) in zip(stroke, stroke[1:]):
            for (x, y) in line_pts(p[0], p[1], q[0], q[1]):
                fm.set(x, y, MESH_DIM, True)
    cls, style = flicker(7.3, 2.0)
    tri = new_layer('trident-dim', anim=cls, style=style)
    x, y = TRIDENT_AT
    for j, row in enumerate(TRIDENT):
        for i, ch in enumerate(row):
            if ch != '.':
                tri.set(x + i, y + j, BLUE_D if ch == 'B' else GOLD_D, True)


def flicker(duration, delay=0.0):
    """Class and style for an overlay that blinks on in short bursts."""
    add_css('.fl{animation:fl 1s %s}' % STEP)
    add_css(keyframes('fl', {0: 'opacity:0', 88: 'opacity:1', 90: 'opacity:0', 92: 'opacity:1',
                             94: 'opacity:0', 96: 'opacity:1', 98: 'opacity:0'}))
    return 'fl h', 'animation-duration:%gs;animation-delay:-%gs' % (duration, delay)


# ---- life on the roof and in the air ------------------------------------------
def roof_props():
    """A pack of cigarettes and a lighter by his seat."""
    L = new_layer('props')
    rect(L, 49, 126, 3, 3, C('#d8e0f0'))
    rect(L, 49, 127, 3, 2, C('#e83a5a'))
    L.set(49, 126, C('#ffffff'))
    L.set(53, 128, C('#5ee0f5'))
    L.set(54, 128, C('#5ee0f5'))
    L.set(53, 127, C('#c9d3e0'))
    return L


def vent():
    """A vent stack on the roof, breathing steam."""
    x0, y0 = 219, 113
    L = new_layer('vent')
    BG.append(L)
    for y in range(y0, ROOF_Y1 - 1):
        for x in range(x0, x0 + 4):
            L.set(x, y, C('#3c2e66') if x == x0 else (C('#2a2150') if x < x0 + 3 else C('#14102c')))
    for x in range(x0 - 1, x0 + 5):
        L.set(x, y0 - 1, C('#7a68b8'))
        L.set(x, y0, C('#4a3c80'))
    for y in range(y0 + 5, ROOF_Y1 - 1, 5):
        for x in range(x0, x0 + 4):
            L.set(x, y, C('#14102c'))
    puffs = (
        ((0, 0), (1, -1)),
        ((1, -2), (0, -3), (2, -4)),
        ((0, -4), (2, -5), (1, -7), (3, -8)),
        ((2, -7), (1, -9), (3, -10), (2, -12)),
    )
    frames = seq_frames(4, 2.4)
    for k, pts in enumerate(puffs):
        cls, style = frames[k]
        S = new_layer('steam-%d' % k, anim=cls, style=style, alpha=.4)
        for (dx, dy) in pts:
            rect(S, x0 + 1 + dx, y0 - 3 + dy, 2, 2, C('#ffd0ea'))


def air_cars():
    """Far-off air traffic crossing the whole canyon, slowly, once per loop."""
    for (y, left_to_right, col_front, col_back, name) in ((19, True, '#ffe9a8', '#ff3d6e', 'a'),
                                                          (93, False, '#9fe8ff', '#ff3d6e', 'b')):
        xa, xb = (-8, 262) if left_to_right else (262, -8)
        cls, hidden = move([(.4, xa, y), (T_LOOP - .6, xb, y)], ref=(128, y))
        grp = ((cls + (' h' if hidden else ''), '', 'car-' + name),)
        L = new_layer('car-' + name, groups=grp)
        d = 1 if left_to_right else -1
        for j, (ox, wd) in enumerate(((1, 2), (0, 4))):
            for i in range(wd):
                xx = ox + i if left_to_right else 3 - ox - i
                L.set(128 + xx, y + j, C('#2a2058') if j == 0 else C('#3a2c78'))
        L.set(128 + (4 if left_to_right else -1), y + 1, C(col_front), True)
        L.set(128 + (-1 if left_to_right else 4), y + 1, C(col_back), True)
        L.set(128 + (-2 if left_to_right else 5), y + 1, mix(C(col_back), INK, .55), True)


def window_people():
    """Somebody stands in a few of the lit windows of the near towers."""
    rng = Rng(808)
    warm = [(n, x, y, w, h, c) for (n, x, y, w, h, c) in WINDOWS
            if n.startswith('near') and w == 3 and h == 3 and y < 100 and c in WARM]
    for k in range(min(7, len(warm))):
        n, x, y, w, h, c = warm.pop(rng.randint(0, len(warm) - 1))
        L = layer(n)
        dark = mix(c, C('#1a0a2a'), .86)
        L.set(x + 1, y + 1, dark, True)
        L.set(x + 1, y + 2, dark, True)
        if rng.chance(.5):
            L.set(x + 2 if rng.chance(.5) else x, y + 2, dark, True)


def tv_windows():
    """Blue televisions flickering behind the glass."""
    rng = Rng(909)
    cool = [(n, x, y, w, h, c) for (n, x, y, w, h, c) in WINDOWS
            if n.startswith('near') and w == 3 and y < 100 and c in COOL]
    for k in range(min(6, len(cool))):
        n, x, y, w, h, c = cool.pop(rng.randint(0, len(cool) - 1))
        cls, style = seq_frames(2, .7 + .19 * k, phase=.23 * k)[1]
        L = new_layer('tv-%d' % k, anim=cls, style=style)
        rect(L, x, y, w, h, mix(c, C('#2030c0'), .55), True)
        L.set(x + 1, y + 1, C('#e8f4ff'), True)


# ---- light and glow ----------------------------------------------------------
def neon_pulse(period):
    """A neon that breathes: its bloom swells and eases, slowly."""
    add_css('.np{animation:np 1s ease-in-out infinite alternate}')
    add_css(keyframes('np', {0: 'opacity:.72', 100: 'opacity:1'}))
    return 'np', 'animation-duration:%gs' % period


def neon_dip(duration, delay):
    """A bloom that dips whenever its tube stutters (see flicker())."""
    add_css('.nd{animation:nd 1s %s}' % STEP)
    add_css(keyframes('nd', {0: 'opacity:1', 88: 'opacity:.35', 90: 'opacity:1', 92: 'opacity:.35',
                             94: 'opacity:1', 96: 'opacity:.35', 98: 'opacity:1'}))
    return 'nd', 'animation-duration:%gs;animation-delay:-%gs' % (duration, delay)


def sign_bloom(name, tubes, color, bands, breathe, stutter):
    pc, ps = neon_pulse(breathe)
    dc, ds = neon_dip(*stutter)
    return bloom(name, tubes, color, bands, groups=((pc, ps, 'np-' + name), (dc, ds, 'nd-' + name)))


def neon_blooms():
    """The glow round the neon signs: the Meshtastic mark is the brightest
    light on its tower, the little trident glows softly in blue and yellow.
    (The pink BAR sign already has all the glow it needs.)"""
    tubes = {p for p, c in layer('meshtastic').pix.items() if c in (MESH_GREEN, MESH_HOT)}
    sign_bloom('mesh', tubes, MESH_GREEN, ((1.5, .34), (2.5, .22), (3.5, .14), (5, .08), (7.5, .04)),
               3.6, (5.3, 1.7))
    x, y = TRIDENT_AT
    for tag, ch, col in (('blue', 'B', BLUE_N), ('gold', 'Y', GOLD_N)):
        pix = {(x + i, y + j) for j, row in enumerate(TRIDENT) for i, c in enumerate(row) if c == ch}
        sign_bloom('tri-' + tag, pix, col, ((1.5, .2), (2.5, .11), (4, .05)), 4.4, (7.3, 2.0))
    street = set(layer('alley-street').pix)                 # lights far down in the alley
    bloom('street', street, (255, 200, 150), ((1.5, .28), (2.5, .12)))


def window_bloom():
    """The lit windows of the near towers glow a little onto the wall round them."""
    lit = {}
    for (name, x, y, w, h, c) in WINDOWS:
        if not name.startswith('near') or y > 104:
            continue
        top, topc = composite_at(LAYERS, x, y)
        if top is None or top.name != name or topc != c:
            continue
        for j in range(h):
            for i in range(w):
                lit[(x + i, y + j)] = c
    ring = {}
    for (px, py), c in lit.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (px + dx, py + dy)
                if q not in lit:
                    ring.setdefault(c, set()).add(q)
    for k, c in enumerate(sorted(ring)):
        L = new_layer('window-bloom-%d' % k, alpha=.15)
        for (x, y) in ring[c]:
            L.set(x, y, c)


def hut_lighting():
    """The caged lamp over the hut door: a bloom, a cone down the door, a pool on the roof."""
    lamp = blob_pts(237, 103, 2.4, 1.6)
    dc, ds = neon_dip(9.1, 3.3)
    bloom('hut', lamp, (255, 200, 120), ((1.5, .34), (2.5, .2), (4, .11), (6.5, .05)), groups=((dc, ds, 'nd-hut'),))
    cone = new_layer('hut-cone', alpha=.1)
    for p in poly_pts([(235.5, 105), (238.5, 105), (250, 128), (224, 128)]):
        cone.set(p[0], p[1], C('#ffdc96'))
    pool = new_layer('hut-pool', alpha=.14)
    for p in blob_pts(237, 128, 14, 2):
        pool.set(p[0], p[1], C('#ffdc96'))
    cls, style = flicker(9.1, 3.3)                          # the bulb stutters now and then
    dim = new_layer('hut-lamp-dim', anim=cls, style=style)
    for p in lamp:
        dim.set(p[0], p[1], C('#8a6a48'), True)


def laptop_halos():
    """The screen's light: a halo round the lid, a pool on the roof in front,
    brighter while the map is lit, with red spilling off it each time a ping lands."""
    display = {(SX0 + i, SY0 + j) for i in range(SW) for j in range(SH)}
    bloom('lap', display, (90, 200, 230), ((1.5, .14), (3, .07)))
    pool = new_layer('lap-pool', alpha=.12)
    for p in blob_pts(98, 129, 22, 2.6):
        pool.set(p[0], p[1], C('#8af4ff'))
    on = (gvis([(T_ALERT, T_CLEAR)], 'lap-on'),)
    bloom('lap-on', display, (120, 230, 255), ((1.5, .2), (3, .11), (5.5, .05)), groups=on)
    pool_on = new_layer('lap-pool-on', groups=on, alpha=.1)
    for p in blob_pts(98, 129, 24, 2.8):
        pool_on.set(p[0], p[1], C('#8af4ff'))
    spans = [(a, a + .22) for a in ARRIVE_A + ARRIVE_B]
    bloom('lap-alarm', display, (255, 70, 100), ((1.5, .26), (3, .13), (5.5, .06)),
          groups=(gvis(spans, 'lap-alarm'),))


# ----------------------------------------------------------------------------
# frame, output, build
# ----------------------------------------------------------------------------
def frame():
    """One-pixel frame with stepped corners, so the picture reads as a card on
    light and dark pages alike."""
    corners = {(0, 0), (1, 0), (0, 1), (W - 1, 0), (W - 2, 0), (W - 1, 1),
               (0, H - 1), (1, H - 1), (0, H - 2), (W - 1, H - 1), (W - 2, H - 1), (W - 1, H - 2)}
    for L in LAYERS:
        for p in corners:
            L.erase(*p)
    F = new_layer('frame')
    hi, lo = C('#4a5d78'), C('#141b28')
    ring = {(x, y) for x in range(W) for y in (0, H - 1)}
    ring |= {(x, y) for y in range(H) for x in (0, W - 1)}
    ring |= {(1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)}
    for (x, y) in ring - corners:
        F.set(x, y, hi if (x < W // 2 and y < H // 2) or x == 0 or y == 0 else lo)


def cull_hidden(layers):
    """Drop pixels that a static opaque layer above them covers completely: the
    sky behind the towers, the towers behind the roof. They would only bloat
    the SVG."""
    covered = set()
    for L in reversed(layers):
        if L.anim or L.style or L.groups or L.alpha is not None or L.clip:
            continue
        for p in [p for p in L.pix if p in covered]:
            del L.pix[p]
        covered.update(L.pix)


TITLE = 'A lonely rooftop in a canyon of towers, watching for drones'
DESC = ('Pixel art: a tiny Clawd in a black hoodie works at a laptop on a rooftop, monitoring a mast of '
        'patch antennas wired to solar panels. A hooded figure sits smoking on the roof edge. Walls of '
        'apartment towers rise out of the frame all round, a Meshtastic logo glowing green on one of them '
        'and a small yellow and blue trident on another, and mesh links run from the mast to other '
        'rooftops. When the laptop lights up, the smoker flicks his cigarette away and ducks into cover '
        'while two drones glide across the rooftops sweeping searchlights over the roof; their pings '
        'fly to the antennas and show as red dots and lines on the map. Then he lights another cigarette '
        'and sits back down.')


def clip_defs():
    return '<defs>%s</defs>' % ''.join(
        '<clipPath id="clip-%s"><rect x="%d" y="%d" width="%d" height="%d"/></clipPath>' % ((n,) + r)
        for n, r in sorted(CLIPS.items())) if CLIPS else ''


def write_svg(path, variant='animated'):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'shape-rendering="crispEdges" role="img" aria-labelledby="t d">'
           '<title id="t">%s</title><desc id="d">%s</desc>%s<style>%s</style>%s</svg>\n'
           % (W, H, W * 3, H * 3, TITLE, DESC, clip_defs(), css(variant), emit_layers(LAYERS)))
    with open(path, 'w') as f:
        f.write(svg)
    return len(svg)


def build():
    """Draw the layers back to front."""
    city()
    window_bloom()
    neon_blooms()
    window_people()
    air_cars()
    mesh_links()
    mesh_packets()
    drones()
    stage()
    hut_light()
    hut_lighting()
    roof_props()
    search_pools()
    mast()
    solar()
    vent()
    mast_cables()
    mast_light()
    laptop()
    screen_idle()
    people()
    screen_story()
    radar()
    screen_glare()
    screen_glow()
    laptop_halos()
    pings()
    laptop_light()
    blinkers()
    tv_windows()
    frame()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description='Draw the level 1 README header.')
    ap.add_argument('-o', '--out', default=os.path.join(here, 'level1-rooftop.svg'),
                    help='SVG to write (default: next to this script)')
    ap.add_argument('--variant', choices=('animated', 'static', 'overlays'), default='animated',
                    help='static: no animation, for pixel-exact checks; '
                         'overlays: show every hidden overlay, to check their stacking')
    ap.add_argument('--png', help='also write a PNG of the still frame')
    ap.add_argument('--scale', type=int, default=4, help='PNG pixels per art pixel')
    ap.add_argument('--crop', help='PNG crop as x,y,w,h in art pixels')
    args = ap.parse_args()
    build()
    if args.png:                                    # the preview shows the layers as drawn
        crop = tuple(int(v) for v in args.crop.split(',')) if args.crop else None
        write_png(args.png, flatten(LAYERS), args.scale, crop)
    cull_hidden(LAYERS)
    print('%s: %d bytes' % (args.out, write_svg(args.out, args.variant)))


if __name__ == '__main__':
    main()
