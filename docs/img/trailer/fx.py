"""Reusable effects: blinking lights, radio rings, packets in flight."""
import math

from .pixart import *
from .palette import *


def blink_layers(name, pixels, on_color, off_color, period, on_frac=.5, phase=0.0, bands=None, bloom_color=None):
    """A light that blinks: `pixels` are drawn lit in the picture already; this
    adds an 'off' overlay that covers them for the dark part of each cycle,
    and (if `bands` is given) a bloom that shines only while the light is on."""
    off_cls, off_style = pulse(1.0 - on_frac, period, phase + on_frac * period)
    L = new_layer(name + '-off', anim=off_cls, style=off_style)
    for (x, y) in pixels:
        L.set(x, y, off_color, False)
    if bands:
        on_cls, on_style = pulse(on_frac, period, phase)
        bloom(name, pixels, bloom_color or on_color, bands, anim=on_cls, style=on_style)


def dashed_ring(cx, cy, r, dash=3, clip=None):
    """A ring made of dashes `dash` pixels long, with the same gap; clipped to
    the rows of the picture."""
    pts = set()
    n = int(math.ceil(r)) + 2
    for y in range(int(cy) - n, int(cy) + n + 1):
        if not (PIC_Y0 <= y < PIC_Y1):
            continue
        for x in range(max(0, int(cx) - n), min(W, int(cx) + n + 1)):
            d = math.hypot(x + .5 - cx, y + .5 - cy)
            if abs(d - r) > .55:
                continue
            a = math.atan2(y + .5 - cy, x + .5 - cx) % (2 * math.pi)
            if int(a * r / float(dash)) % 2 == 0:
                pts.add((x, y))
    return pts


def ring_train(name, cx, cy, v, period, t0, t1, rmax, frames=10, tiers=((0, 1.0), (1, .62)), color=RF, dash=3):
    """Radio rings from a transmitter that beacons every `period` seconds
    between t0 and t1: each ring grows at v px/s until it reaches rmax. The
    pattern repeats every period, so it is drawn once as `frames` frames, each
    showing every ring alive at that point of the cycle."""
    cls = vis_class([(t0, t1)])
    life = rmax / float(v)
    seq = seq_frames(frames, period, phase=t0 % period)
    with group(cls, None, 'rings-' + name):
        for s in range(frames):
            tau = s * period / float(frames)
            for k in range(int(math.ceil(life / period)) + 1):
                age = tau + k * period
                r = age * v
                if r < 1.5 or r > rmax:
                    continue
                pts = dashed_ring(cx, cy, r, dash)
                if not pts:
                    continue
                a = 1.0 - .6 * (r / rmax) ** 1.2
                L = new_layer('%s-%d-%d' % (name, s, k), anim=seq[s][0], style=seq[s][1], alpha=round(a, 2))
                c = mix(color, C('#ffffff'), max(0.0, .6 - r / rmax))
                for p in pts:
                    L.set(p[0], p[1], c, True)


def packet(name, route, t_start, speed=95.0, pause=.22, color=MESH_HOT, tail=MESH, repeat=(), emit=True, small=False):
    """A packet hopping along a route of (x, y) points: it leaves at t_start,
    pauses at every node (the radio there rebroadcasts it), and flies the
    straight links at `speed` px/s. `repeat` lists extra start times for the
    same flight. Returns the time of arrival, relative to each start."""
    pts, t = [], 0.0
    pos = route[0]
    pts.append((t, pos[0], pos[1]))
    for i, nxt in enumerate(route[1:], 1):
        d = math.hypot(nxt[0] - pos[0], nxt[1] - pos[1])
        t += d / speed
        pts.append((t, nxt[0], nxt[1]))
        if i < len(route) - 1:
            t += pause
            pts.append((t, nxt[0], nxt[1]))
        pos = nxt
    starts = [t_start] + list(repeat)
    samples = []
    ref = route[0]
    for k, s0 in enumerate(starts):
        samples.append((max(s0 - EPS, 0.0), dict(o=0, x=0, y=0)))
        for (dt, x, y) in pts:
            samples.append((s0 + dt, dict(o=1, x=x - ref[0], y=y - ref[1])))
        samples.append((s0 + t + EPS, dict(o=0, x=route[-1][0] - ref[0], y=route[-1][1] - ref[1])))
    samples.sort(key=lambda s: s[0])
    # a clean, strictly increasing list that starts at 0 and ends at T_LOOP
    clean, last = [], -1.0
    for (tt, v) in samples:
        tt = max(tt, last + 1e-3)
        clean.append((tt, v))
        last = tt
    if clean[0][0] > 0:
        clean.insert(0, (0.0, dict(clean[0][1], o=0)))
    else:
        clean[0] = (0.0, dict(clean[0][1], o=0))
    if clean[-1][0] < T_LOOP:
        clean.append((T_LOOP, dict(clean[-1][1], o=0)))
    cls = tl(clean) + ' h'
    with group(cls, None, 'pkt-' + name):
        x, y = route[0]
        for (r, a) in (((3.2, .25),) if small else ((5.5, .1), (4, .2), (2.8, .34))):
            halo = new_layer('%s-halo-%g' % (name, r), alpha=a)
            for (px, py) in blob_pts(x + .5, y + .5, r, r):
                halo.set(px, py, tail, emit)
        head = new_layer('%s-head' % name)
        rect(head, x - 1, y - 1, 2, 2, color, emit) if small else rect(head, x - 1, y - 1, 3, 3, color, emit)
    return t


def arcs(cx, cy, radii, a0, a1, dash=0, clip_rows=True):
    """Pixels of arcs of the given radii around (cx, cy), between angles a0 and a1 (degrees)."""
    pts = set()
    for r in radii:
        for p in ring_pts(cx, cy, r, .55, arc=(a0, a1)):
            if clip_rows and not (PIC_Y0 <= p[1] < PIC_Y1):
                continue
            if not (0 <= p[0] < W):
                continue
            if dash:
                a = math.atan2(p[1] + .5 - cy, p[0] + .5 - cx) % (2 * math.pi)
                if int(a * r / float(dash)) % 2:
                    continue
            pts.add(p)
    return pts
