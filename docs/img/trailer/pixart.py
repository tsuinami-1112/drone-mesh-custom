"""A small pixel-art toolkit: sparse layers of pixels, drawing primitives, light
glows, a CSS timeline and SVG output.

Everything is drawn on a W x H pixel grid and written out as merged rectangles
with crispEdges, so the picture stays sharp at any size. Animation is plain CSS
inside the SVG: one story clock (T_LOOP seconds) drives every scripted thing,
and layers that are not on stage at t = 0 carry the class `h` (hidden), so the
picture without animation is a complete still frame.

Standard library only, and deterministic: same code, same bytes.
"""
import contextlib
import math
import struct
import zlib

W, H = 256, 152
TOP_H, BOT_H = 9, 15                       # letterbox bars
PIC_Y0, PIC_Y1 = TOP_H, H - BOT_H          # the picture itself: rows [9, 137), a 2:1 frame
T_LOOP = 42.0                              # seconds


# ----------------------------------------------------------------------------
# a tiny deterministic PRNG (mulberry32), so the art does not depend on the
# Python version's `random`
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

    def uniform(self, a, b):
        return a + (b - a) * self.random()

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
GROUPS = []     # the <g> wrappers new layers are created inside (shots, cameras)


class Layer:
    """A sparse grid of pixels.

    anim    CSS class(es) that animate the layer; 'h' means hidden until an
            animation shows it (the still frame leaves it out)
    style   inline CSS, normally animation-duration / animation-delay
    groups  nested <g> wrappers, outermost first, each (class, style, uid); a
            shot, a camera, a drone and its beam each share one
    alpha   draw the whole layer translucent (beams, light stripes)
    clip    name of a CLIPS region the layer is cropped to
    emit    pixels that glow effects must not tint
    paint   'group': the one colour of the layer is set on its <g> instead of
            each path, so CSS can animate it (the sky changing colour)
    """

    def __init__(self, name, anim=None, groups=(), style=None, alpha=None, clip=None, paint=None):
        self.name = name
        self.anim = anim
        self.groups = tuple(groups)
        self.style = style
        self.alpha = alpha
        self.clip = clip
        self.paint = paint
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
        self.emit.discard((x, y))


LAYERS = []


def new_layer(name, **kw):
    kw['groups'] = tuple(GROUPS) + tuple(kw.get('groups', ()))
    L = Layer(name, **kw)
    LAYERS.append(L)
    return L


def layer(name):
    for L in LAYERS:
        if L.name == name:
            return L
    raise KeyError(name)


@contextlib.contextmanager
def group(cls, style=None, uid=None):
    """Everything drawn inside shares a <g class=cls style=style> wrapper."""
    GROUPS.append((cls, style, uid or cls))
    try:
        yield
    finally:
        GROUPS.pop()


@contextlib.contextmanager
def shot(name, spans=None):
    """Everything drawn inside belongs to one shot of the film: it is on
    screen only during `spans`. (Call vis_class later; this needs the CSS
    helpers below, which are resolved at call time.)"""
    with group(vis_class(spans), None, 'shot-' + name):
        yield


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


def ring_pts(cx, cy, r, half=.5, arc=None):
    """A one-pixel ring of radius r (pixel centres within `half` of the circle).
    arc=(a0, a1) keeps only the angles between them (degrees, 0 = right,
    90 = down, as drawn on screen)."""
    pts = set()
    n = int(math.ceil(r + half)) + 1
    for y in range(int(cy) - n, int(cy) + n + 1):
        for x in range(int(cx) - n, int(cx) + n + 1):
            d = math.hypot(x + .5 - cx, y + .5 - cy)
            if abs(d - r) > half:
                continue
            if arc is not None:
                a = math.degrees(math.atan2(y + .5 - cy, x + .5 - cx)) % 360.0
                a0, a1 = arc[0] % 360.0, arc[1] % 360.0
                if a0 <= a1:
                    if not (a0 <= a <= a1):
                        continue
                elif not (a >= a0 or a <= a1):
                    continue
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
# light: glows that tint what is already drawn, blooms that sit on top
# ----------------------------------------------------------------------------
def composite_at(layers, x, y):
    for L in reversed(layers):
        c = L.pix.get((x, y))
        if c is not None:
            return L, c
    return None, None


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


# ----------------------------------------------------------------------------
# CSS: pieces register their rules as they are used
# ----------------------------------------------------------------------------
CSS = []
STEP = 'steps(1,end) infinite'
EPS = .012           # a "cut" is a very quick change: this many seconds
_TL = [0]


def add_css(rule):
    if rule not in CSS:
        CSS.append(rule)


def keyframes(name, frames):
    """frames: {percent: 'css declarations'}"""
    return '@keyframes %s{%s}' % (name, ''.join('%g%%{%s}' % (float(p), d)
                                                for p, d in sorted(frames.items(), key=lambda kv: float(kv[0]))))


def seq_frames(n, period, phase=0.0, name='q'):
    """Class/style pairs for an n-frame loop: frame s shows during the s-th
    slice of every `period` seconds, the whole cycle starting `phase` seconds
    into the loop (frame s from phase + s*period/n, repeating). The frame that
    is on at t = 0 is the one the still frame shows."""
    cls = '%s%d' % (name, n)
    add_css('.%s{animation:%s 1s %s}' % (cls, cls, STEP))
    add_css(keyframes(cls, {0: 'opacity:1', '%.3f' % (100.0 / n): 'opacity:0'}))
    on_at_zero = int((((-phase) % period) + 1e-9) // (period / float(n))) % n
    out = []
    for s in range(n):
        delay = (((n - s) % n) * period / float(n) - phase) % period
        out.append((cls if s == on_at_zero else cls + ' h',
                    'animation-duration:%gs;animation-delay:-%gs' % (period, delay)))
    return out


def pulse(duty, period, phase=0.0):
    """Visible for `duty` of each cycle (the cycle starts `phase` seconds into
    the loop), then off; returns (class, style). The class carries `h` when the
    thing is off at t = 0, so the still frame agrees with the first frame."""
    cls = 'pu%d' % round(duty * 100)
    add_css('.%s{animation:%s 1s %s}' % (cls, cls, STEP))
    add_css(keyframes(cls, {0: 'opacity:1', '%.1f' % (duty * 100): 'opacity:0'}))
    delay = (-phase) % period
    style = 'animation-duration:%gs' % period
    if delay:
        style += ';animation-delay:-%gs' % delay
    on_at_zero = delay < duty * period - 1e-9
    return (cls if on_at_zero else cls + ' h'), style


def _fmt(v):
    s = '%.2f' % v
    return s.rstrip('0').rstrip('.') if '.' in s else s


def tl(samples, ease='linear'):
    """Register a keyframe list on the story clock and return its class.
    samples: (t seconds, {'o': opacity, 'x': dx, 'y': dy, 'f': '#rrggbb'}) in
    time order; the first must be at t = 0 and the last at T_LOOP."""
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
        if 'f' in v:
            d.append('fill:%s' % v['f'])
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


def vis_class(spans):
    """vis() as a class string, with the hidden marker added when needed."""
    cls, hidden = vis(spans)
    return cls + (' h' if hidden else '')


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


def recolor(points):
    """A layer whose single colour changes over the loop: (time, colour) points
    covering the whole loop. Returns the class (give the layer paint='group')."""
    return tl([(t, dict(f=hexs(c))) for (t, c) in points])


def css(variant='animated'):
    if variant == 'static':          # nothing moves: the picture a still frame shows
        return '.h{opacity:0}'
    if variant == 'overlays':        # debugging aid: show every hidden overlay
        return '.h{opacity:1}'
    return '.h{opacity:0}' + ''.join(CSS) + \
        '@media (prefers-reduced-motion:reduce){*{animation:none!important}}'


# ----------------------------------------------------------------------------
# the still frame, as a preview and for checks
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
        if hidden_by_default(L) or (L.style and 'opacity:0' in L.style.split(';')):
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
# culling: drop pixels that a static opaque layer above them covers completely
# ----------------------------------------------------------------------------
def cull_hidden(layers):
    """The sky behind the towers, the towers behind the roof: they would only
    bloat the SVG. Layers are compared only with others inside the same
    wrappers (the same shot, the same camera). Whatever lies under a static,
    opaque layer is dropped; only such layers hide things in turn."""
    scopes = {}
    for L in layers:
        scopes.setdefault(L.groups, []).append(L)
    for members in scopes.values():
        covered = set()
        for L in reversed(members):
            if L.clip:
                continue
            for p in [p for p in L.pix if p in covered]:
                del L.pix[p]
                L.emit.discard(p)
            if not (L.anim or L.style or L.alpha is not None or L.paint):
                covered.update(L.pix)


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


def paths_for(pix, plain=False):
    """One <path> per colour. plain=True leaves the colour off (it is set on
    the wrapper, for layers whose colour CSS animates)."""
    by = {}
    for p, c in pix.items():
        by.setdefault(c, set()).add(p)
    if plain:
        assert len(by) == 1, 'a recoloured layer has one colour'
        return '<path d="%s"/>' % path_d(rects_for(next(iter(by.values()))))
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
    if L.paint == 'group':
        c = next(iter(L.pix.values()))
        out = '<g%s>%s</g>' % (attrs(L.anim, ((L.style + ';') if L.style else '') + 'fill:%s' % hexs(c)),
                               paths_for(L.pix, plain=True))
    else:
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
        elif L.anim or L.style or L.alpha is not None or L.paint:
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


def write_svg(path, title, desc, variant='animated', scale=3):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'shape-rendering="crispEdges" role="img" aria-labelledby="t d">'
           '<title id="t">%s</title><desc id="d">%s</desc>%s<style>%s</style>%s</svg>\n'
           % (W, H, W * scale, H * scale, title, desc, clip_defs(), css(variant), emit_layers(LAYERS)))
    with open(path, 'w') as f:
        f.write(svg)
    return len(svg)
