"""The first detection: the stations blink, a drone arrives and hovers over the
city broadcasting, the rings reach the stations that can hear it, each one
reports over the mesh and the packets hop home."""
import math

from .pixart import *
from .fonts import text3, text3_width
from .palette import *
from . import city, stage, fx, drone, stations, timeline as TL


def ambient(world, anc):
    """Everything that blinks without being asked: station LEDs, the red
    lights on the spires, a few windows."""
    rng = Rng(11)
    for i, (k, node) in enumerate(sorted(world['nodes'].items())):
        led = node.get('led')
        if not led:
            continue
        period = 1.6 + (i % 4) * .4
        fx.blink_layers('led-' + k, led, stations.LED_ON, PALE[1], period, on_frac=.62, phase=rng.uniform(0, period),
                        bands=((1.5, .4), (3, .18)), bloom_color=(80, 255, 150))
    for (x, y) in city.BEACONS:
        period = rng.choice([1.4, 1.8, 2.2, 2.6])
        cls, style = pulse(.3, period, rng.uniform(0, period))
        L = new_layer('beacon', anim=cls, style=style)
        L.set(x, y, RED, True)
        bloom('beacon', [(x, y)], RED, ((1.5, .4), (3, .16)), anim=cls, style=style)
    for plane, count in (('mid', 9), ('near', 7), ('far', 5)):
        wins = city.WINDOWS.get(plane, [])
        for (x, y, w, h, c) in [wins[rng.randint(0, len(wins) - 1)] for _ in range(count)]:
            period = rng.choice([5.25, 7.0, 10.5, 14.0])
            cls, style = pulse(.12, period, rng.uniform(0, period))
            L = new_layer('twinkle', anim=cls, style=style)
            rect(L, x, y, w, h, mix(c, INK, .86))


def reach(world, anc, source):
    """Which stations can hear the drone, and how long a ring takes to get to each."""
    out = {}
    for k, node in world['nodes'].items():
        if k == 'HOME':
            continue
        tip = node['tip']
        d = math.hypot(tip[0] - source[0], tip[1] - source[1])
        if d <= TL.RING_MAX:
            out[k] = d
    return out


ROUTES = {'S3': ['S3', 'S4', 'HOME'], 'M1': ['M1', 'M2', 'HOME'], 'S5': ['S5', 'S3', 'S4', 'HOME'],
          'hero': ['hero', 'M1', 'M2', 'HOME']}
RSSI = {'S3': '-58', 'M1': '-66', 'S5': '-67', 'hero': '-71'}


def drone_beat(world, anc):
    hx, hy = TL.HOVER_AT
    # --- the flight in, and a hover
    pts = []
    t0, t1 = TL.DRONE_IN, TL.DRONE_HOVER
    for i in range(0, 8):
        t = t0 + (t1 - t0) * i / 7.0
        s = (t - t0) / (t1 - t0)
        e = (1 - s) ** 2
        pts.append((t, hx + 170 * e, hy - 14 * e))
    t = t1
    while t < 9.9:
        t += .4
        pts.append((t, hx, hy + .8 * math.sin((t - t1) * 2.2)))
    cls, hidden = move(pts, ref=(hx, hy))
    P = drone.pieces(hx - drone.CENTER[0], hy - drone.CENTER[1])
    with group(cls + (' h' if hidden else ''), None, 'drone'):
        body = new_layer('drone-body')
        for p, c in P['body'].items():
            body.set(p[0], p[1], c)
        rot = seq_frames(2, .14, name='rt')
        for f, key in enumerate(('a', 'b')):
            L = new_layer('drone-rotor-%s' % key, anim=rot[f][0], style=rot[f][1], alpha=.5)
            for p in P[key]:
                L.set(p[0], p[1], drone.BLUR)
        cone = new_layer('drone-cone', alpha=.07)
        for p in poly_pts([(hx - 1, hy + 8), (hx + 1, hy + 8), (hx + 34, hy + 74), (hx - 34, hy + 74)]):
            if PIC_Y0 <= p[1] < PIC_Y1:
                cone.set(p[0], p[1], C('#c8e6ff'))
        cone2 = new_layer('drone-cone-core', alpha=.06)
        for p in poly_pts([(hx - 1, hy + 8), (hx + 1, hy + 8), (hx + 14, hy + 74), (hx - 14, hy + 74)]):
            if PIC_Y0 <= p[1] < PIC_Y1:
                cone2.set(p[0], p[1], C('#e8f4ff'))
        for (key, col, per, ph) in (('red', drone.RED_L, 1.2, .1), ('green', drone.GREEN_L, 1.2, .7)):
            cls2, st2 = pulse(.4, per, ph)
            L = new_layer('drone-' + key, anim=cls2, style=st2)
            L.set(P[key][0], P[key][1], col, True)
            bloom('drone-' + key, [P[key]], col, ((1.5, .45), (3, .2)), anim=cls2, style=st2)
    # --- radio rings
    fx.ring_train('rf', hx, hy + 1, TL.RING_V, TL.EMIT_PERIOD, TL.EMIT_FIRST, 9.7, TL.RING_MAX)
    # --- the lock: once the first station has heard it, brackets close round the drone
    d_first = min(math.hypot(n['tip'][0] - hx, n['tip'][1] - hy) for k, n in world['nodes'].items() if k != 'HOME'
                  and math.hypot(n['tip'][0] - hx, n['tip'][1] - hy) <= TL.RING_MAX)
    t_lock = TL.EMIT_FIRST + d_first / TL.RING_V + .15
    with group(vis_class([(t_lock, t_lock + .06), (t_lock + .14, t_lock + .2), (t_lock + .3, 9.7)]), None, 'lock'):
        L = new_layer('lock')
        for (sx, sy) in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cx, cy = hx + sx * 18, hy + sy * 11
            for i in range(4):
                L.set(cx - sx * i, cy, RED, True)
                L.set(cx, cy - sy * i, RED, True)
        label = ('REMOTE ID', 'ALT 120 M')
        w = max(text3_width(t) for t in label) + 4
        x0, y0 = hx + 24, hy - 6
        rect(L, x0, y0, w, 13, C('#14061a'))
        for x in range(x0, x0 + w):
            L.set(x, y0, C('#6a1a3c'))
            L.set(x, y0 + 12, C('#6a1a3c'))
        for y in range(y0, y0 + 13):
            L.set(x0, y, C('#6a1a3c'))
        text3(L, x0 + 2, y0 + 2, label[0], C('#ff9fb8'))
        text3(L, x0 + 2, y0 + 8, label[1], C('#c9c7e6'))
        bloom('lock', {(hx - 18, hy - 11), (hx + 18, hy - 11), (hx - 18, hy + 11), (hx + 18, hy + 11)}, RED,
              ((2, .3), (4, .12)))
    # --- who hears it, and what they send
    heard = reach(world, anc, (hx, hy))
    emits = [TL.EMIT_FIRST + k * TL.EMIT_PERIOD for k in range(TL.EMITS)]
    arrivals = []
    for k, d in sorted(heard.items(), key=lambda kv: kv[1]):
        times = [e + d / TL.RING_V for e in emits]
        ax, ay = anc[k]
        # the diamond flashes white, with a bloom
        spans = [(t, t + .3) for t in times]
        cls = vis_class(spans)
        with group(cls, None, 'hit-' + k):
            L = new_layer('hit-' + k)
            for p in stage.marker_pixels(ax, ay):
                L.set(p[0], p[1], C('#ffffff'), True)
            bloom('hit-' + k, stage.marker_pixels(ax, ay), RF, ((1.5, .5), (3, .3), (5, .16), (8, .07)))
            for p in fx.dashed_ring(ax, ay, 7, 2):
                L.set(p[0], p[1], RF_HOT, True)
        # the signal strength, a moment longer
        spans = [(t, t + 1.0) for t in times]
        cls = vis_class(spans)
        with group(cls, None, 'rssi-' + k):
            text = RSSI[k]
            w = text3_width(text) + 3
            L = new_layer('rssi-' + k)
            rect(L, ax - w // 2, ay + 5, w, 7, C('#06101c'))
            text3(L, ax - w // 2 + 2, ay + 6, text, RF_HOT)
        # the packet it sends: it leaves a moment later and hops home
        route = [anc[n] for n in ROUTES[k]]
        starts = [t + .22 for t in times]
        dur = fx.packet('p-' + k, route, starts[0], repeat=starts[1:])
        arrivals += [s + dur for s in starts]
    arrivals.sort()
    # --- the home station hears each packet
    ax, ay = anc['HOME']
    cls = vis_class([(t, t + .3) for t in arrivals])
    with group(cls, None, 'home-hit'):
        L = new_layer('home-hit')
        for p in stage.marker_pixels(ax, ay):
            L.set(p[0], p[1], C('#ffffff'), True)
        bloom('home-hit', stage.marker_pixels(ax, ay), MESH_HOT, ((1.5, .5), (3, .3), (5, .16), (8, .07)))
    return arrivals


def boot(world, anc):
    """In the first moments the stations check in, one after another, left to right."""
    order = sorted(anc, key=lambda k: anc[k][0])
    for i, k in enumerate(order):
        t = .7 + i * .2
        ax, ay = anc[k]
        with group(vis_class([(t, t + .25)]), None, 'boot-' + k):
            L = new_layer('boot-' + k)
            for p in stage.marker_pixels(ax, ay):
                L.set(p[0], p[1], C('#ffffff'), True)
            bloom('boot-' + k, stage.marker_pixels(ax, ay), MESH_HOT, ((1.5, .45), (3, .26), (5, .12), (8, .05)))
            for p in fx.dashed_ring(ax, ay, 8, 2):
                L.set(p[0], p[1], MESH_HOT, True)
