"""The mesh at work, seen from above: several stations hear the same drone, each
sends one packet over the LoRa mesh, the packets hop home by different routes
and the home station's dedup lets the first through and drops its copies."""
import math

from .pixart import *
from .fonts import text3, text3_width
from .palette import *
from . import fx, mapbase
from . import timeline as TL

T0, T1 = TL.RELAY[0]
NODES = {'B07A': (104, 34), '4C81': (134, 54), '7F3C': (88, 74), '09DE': (120, 86), 'A1B2': (52, 86),
         '2E90': (188, 76), 'R': mapbase.HILL_AT, 'HOME': (206, 106)}
DETECTORS = ('B07A', '4C81', '7F3C', '09DE', 'A1B2', '2E90')
LINKS = [('A1B2', '7F3C'), ('7F3C', '4C81'), ('7F3C', '09DE'), ('4C81', '2E90'), ('09DE', 'HOME'), ('2E90', 'HOME'),
         ('B07A', '4C81'), ('B07A', 'R'), ('R', 'A1B2')]
ROUTES = {'09DE': ['09DE', 'HOME'], '4C81': ['4C81', '2E90', 'HOME'], '7F3C': ['7F3C', '09DE', 'HOME'],
          'B07A': ['B07A', '4C81', '2E90', 'HOME']}
QUEUE = {'09DE': .12, '4C81': .2, '7F3C': .28, 'B07A': .36}      # the radio takes a moment to get on air
BEACONS = [16.1 + k for k in range(6)]
V_MAP, R_COV = 50.0, 30.0
DRONE_FROM, DRONE_TO = (96, 62), (126, 58)
WINDOW = .5                                                         # the dedup window, seconds

DRONE_C = C('#ff3d6e')
LIME = C('#88ff99')
LIME_HOT = C('#00ff66')
DUP_C = C('#ff7a99')


def drone_at(t):
    s = max(0.0, min(1.0, (t - T0) / (T1 - T0)))
    return (DRONE_FROM[0] + (DRONE_TO[0] - DRONE_FROM[0]) * s, DRONE_FROM[1] + (DRONE_TO[1] - DRONE_FROM[1]) * s)


def hex_outline(cx, cy, r=5):
    pts = [(cx, cy - r), (cx + r, cy - r // 2), (cx + r, cy + r // 2), (cx, cy + r), (cx - r, cy + r // 2),
           (cx - r, cy - r // 2)]
    out = set()
    for a, b in zip(pts, pts[1:] + pts[:1]):
        out |= set(line_pts(a[0], a[1], b[0], b[1]))
    return out


def hex_fill(cx, cy, r=5):
    return poly_pts([(cx, cy - r), (cx + r + .5, cy - r // 2), (cx + r + .5, cy + r // 2), (cx, cy + r + .5),
                     (cx - r, cy + r // 2), (cx - r, cy - r // 2)])


def uav(cx, cy, color):
    """The mapper's marker for an aircraft: an X-frame, four rotor rings, a solid body."""
    pts = set()
    for (dx, dy) in ((-4, -4), (4, -4), (-4, 4), (4, 4)):
        pts |= ring_pts(cx + dx + .5, cy + dy + .5, 2.2, .6)
        pts |= set(line_pts(cx + (dx // 4) * 1, cy + (dy // 4) * 1, cx + dx - (dx // 4) * 2, cy + dy - (dy // 4) * 2))
    pts |= {(cx + i, cy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)}
    return pts


def house(cx, cy):
    pts = set()
    for k in range(5):
        pts |= {(cx - k, cy - 4 + k), (cx + k, cy - 4 + k)}
    pts |= {(cx + i, cy + 1 + j) for i in range(-3, 4) for j in range(0, 4)}
    return pts


def simulate():
    """Who hears each beacon, when their packets leave and when they reach home, and
    what the home station's dedup does with them: exactly its rule, first in wins."""
    events = []
    arrivals = []
    for k, tb in enumerate(BEACONS):
        dx, dy = drone_at(tb)
        for n in ROUTES:
            nx, ny = NODES[n]
            d = math.hypot(nx - dx, ny - dy)
            if d > R_COV:
                continue
            t_hit = tb + d / V_MAP
            t_dep = t_hit + QUEUE[n]
            route = [NODES[r] for r in ROUTES[n]]
            dur = route_time(route)
            events.append(dict(node=n, beacon=k, hit=t_hit, depart=t_dep, arrive=t_dep + dur))
    for e in sorted(events, key=lambda e: e['arrive']):
        arrivals.append(e)
    start = None
    for e in arrivals:
        if start is None or e['arrive'] - start >= WINDOW:
            e['fwd'] = True
            start = e['arrive']
        else:
            e['fwd'] = False
    return events, arrivals


def route_time(route, speed=85.0, pause=.2):
    t = 0.0
    for i in range(1, len(route)):
        t += math.hypot(route[i][0] - route[i - 1][0], route[i][1] - route[i - 1][1]) / speed
        if i < len(route) - 1:
            t += pause
    return t


def build():
    events, arrivals = simulate()
    t_pop = {}
    order = ['R', 'B07A', 'A1B2', '7F3C', '4C81', '09DE', '2E90', 'HOME']
    for i, n in enumerate(order):
        t_pop[n] = T0 + .25 + i * .09
    END = T_LOOP
    dim = new_layer('map-dim', alpha=.5)
    rect(dim, 0, PIC_Y0, W, PIC_Y1 - PIC_Y0, C('#04021a'))
    # --- coverage of each detector: the little circle it can hear within; where they overlap it glows
    for n in DETECTORS:
        with group(vis_class([(t_pop[n], END)]), None, 'cov-' + n):
            fill = new_layer('cov-fill-' + n, alpha=.07)
            for p in blob_pts(NODES[n][0], NODES[n][1], R_COV, R_COV):
                if PIC_Y0 <= p[1] < PIC_Y1:
                    fill.set(p[0], p[1], RF)
            L = new_layer('cov-' + n, alpha=.75)
            for p in fx.dashed_ring(NODES[n][0], NODES[n][1], R_COV, 2):
                L.set(p[0], p[1], RF)
    # --- the links draw themselves in, and crawl
    seq = seq_frames(4, .5, name='lk')
    for (a, b) in LINKS:
        t = max(t_pop[a], t_pop[b]) + .1
        pts = line_pts(NODES[a][0], NODES[a][1], NODES[b][0], NODES[b][1])
        with group(vis_class([(t, END)]), None, 'link-%s-%s' % (a, b)):
            g = new_layer('link-glow-%s-%s' % (a, b), alpha=.18)
            for (x, y) in pts:
                for (dx, dy) in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                    g.set(x + dx, y + dy, MESH)
            for f in range(4):
                L = new_layer('link-%s-%s-%d' % (a, b, f), anim=seq[f][0], style=seq[f][1])
                for i, (x, y) in enumerate(pts):
                    if (i + f) % 4 < 2:
                        L.set(x, y, MESH, True)
    # --- nodes: hexagons with their names
    for n, (x, y) in NODES.items():
        with group(vis_class([(t_pop[n], END)]), None, 'node-' + n):
            L = new_layer('node-' + n)
            if n == 'HOME':
                for p in house(x, y):
                    L.set(p[0], p[1], LIME, True)
                for j in range(3):
                    L.set(x, y + 2 + j + 1, C('#04030a'))
                text3(L, x - 8, y + 8, 'HOME', LIME)
            else:
                for p in hex_outline(x, y):
                    L.set(p[0], p[1], MESH if n != 'R' else C('#9aa0ff'), True)
                if n == 'R':
                    text3(L, x - 1, y - 2, 'R', C('#9aa0ff'))
                    text3(L, x - 11, y + 8, 'ROUTER', C('#9aa0ff'))
                else:
                    L.set(x, y, MESH_HOT, True)
                    text3(L, x - 7, y + 8, n, C('#9fe9f5'))
            bloom('node-' + n, hex_outline(x, y) if n != 'HOME' else house(x, y), MESH if n != 'HOME' else LIME,
                  ((1.5, .26), (3, .12)))
    # --- the drone, with its lime broadcast ring, drifting slowly
    pts = [(t, *drone_at(t)) for t in (T0, T0 + 1.6, T0 + 3.2, T0 + 4.8, T1 + .4)]
    cls, hidden = move(pts, ref=DRONE_FROM)
    with group(cls + (' h' if hidden else ''), None, 'uav'):
        L = new_layer('uav')
        for p in uav(DRONE_FROM[0], DRONE_FROM[1], DRONE_C):
            L.set(p[0], p[1], DRONE_C, True)
        ring = new_layer('uav-ring')
        for p in ring_pts(DRONE_FROM[0] + .5, DRONE_FROM[1] + .5, 9, .6):
            ring.set(p[0], p[1], LIME_HOT, True)
        text3(L, DRONE_FROM[0] - 12 - text3_width('UAS 1581F5'), DRONE_FROM[1] - 2, 'UAS 1581F5', C('#ff9fb8'))
        fx.ring_train('map', DRONE_FROM[0] + .5, DRONE_FROM[1] + .5, V_MAP, 1.0, BEACONS[0], END, R_COV,
                      frames=10, tiers=(), color=RF_HOT)
    # --- each hit, and the packet it sends
    for e in events:
        x, y = NODES[e['node']]
        with group(vis_class([(e['hit'], e['hit'] + .3)]), None, 'hit-%s-%d' % (e['node'], e['beacon'])):
            L = new_layer('hit-%s-%d' % (e['node'], e['beacon']))
            for p in hex_fill(x, y):
                L.set(p[0], p[1], C('#ffffff'), True)
            bloom('hit-%s-%d' % (e['node'], e['beacon']), hex_outline(x, y), RF, ((1.5, .5), (3, .3), (5, .15), (8, .06)))
        route = [NODES[r] for r in ROUTES[e['node']]]
        fx.packet('p-%s-%d' % (e['node'], e['beacon']), route, e['depart'], speed=85, pause=.2)
    # --- home: what arrives, what the dedup does with it
    hx, hy = NODES['HOME']
    for k, e in enumerate(arrivals):
        t = e['arrive']
        if t > T1 - .1:
            continue
        with group(vis_class([(t, t + .32)]), None, 'home-%d' % k):
            L = new_layer('home-hit-%d' % k)
            if e['fwd']:
                for p in house(hx, hy):
                    L.set(p[0], p[1], C('#ffffff'), True)
                bloom('home-fwd-%d' % k, house(hx, hy), LIME_HOT, ((1.5, .5), (3, .3), (5, .16), (8, .07)))
            else:
                for (dx, dy) in ((-2, -2), (2, -2), (-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1), (-2, 2), (2, 2)):
                    L.set(hx + dx, hy - 10 + dy, DUP_C, True)
    # --- the laptop: forwarded detections go out over USB to the mapper
    lx, ly = hx + 17, hy + 6
    with group(vis_class([(t_pop['HOME'], END)]), None, 'laptop'):
        L = new_layer('laptop')
        rect(L, lx - 5, ly - 4, 11, 7, LIME)
        rect(L, lx - 4, ly - 3, 9, 5, C('#04120a'))
        rect(L, lx - 7, ly + 3, 15, 2, C('#2f9a46'))
        text3(L, lx - 14, ly + 7, 'MAPPER.PY', C('#88ff99'))
    for k, e in enumerate(arrivals):
        if e['fwd'] and e['arrive'] < T1 - .5:
            t = e['arrive'] + .05
            fx.packet('usb-%d' % k, [(hx + 4, hy + 4), (lx - 6, ly - 1)], t, speed=60, color=C('#d4ffe4'), tail=LIME,
                      small=True)
            with group(vis_class([(t + .3, t + .55)]), None, 'lap-%d' % k):
                L = new_layer('lap-%d' % k)
                rect(L, lx - 4, ly - 3, 9, 5, C('#88ff99'), True)
    log_panel(arrivals, t_pop['HOME'] + .1, END)
    return events, arrivals


PANEL = (172, 12, 252, 66)


def log_panel(arrivals, t_on, END):
    """The home station's console: the last few packets that reached it, and whether
    the dedup forwarded them or dropped them as copies."""
    x0, y0, x1, y1 = PANEL
    arrivals = [e for e in arrivals if e['arrive'] < T1 - .1]
    with group(vis_class([(t_on, END)]), None, 'dedup-panel'):
        L = new_layer('dedup-panel')
        rect(L, x0, y0, x1 - x0, y1 - y0, C('#04120a'))
        for x in range(x0 + 1, x1 - 1):
            L.set(x, y0, C('#2f9a46'))
            L.set(x, y1 - 1, C('#2f9a46'))
        for y in range(y0 + 1, y1 - 1):
            L.set(x0, y, C('#2f9a46'))
            L.set(x1 - 1, y, C('#2f9a46'))
        for x in range(x0 + 1, x1 - 1):
            L.set(x, y0 + 9, C('#14401e'))
            L.set(x, y1 - 10, C('#14401e'))
        text3(L, x0 + 4, y0 + 2, 'HOME DEDUP 500MS', LIME)
    slots = 5
    for i, e in enumerate(arrivals):
        t_end = arrivals[i + slots]['arrive'] if i + slots < len(arrivals) else END
        s = i % slots
        ty = y0 + 12 + s * 6
        with group(vis_class([(e['arrive'], t_end)]), None, 'log-%d' % i):
            L = new_layer('log-%d' % i)
            text3(L, x0 + 10, ty, e['node'], C('#9fe9f5'))
            text3(L, x0 + 33, ty, 'FWD' if e['fwd'] else 'DUP', LIME if e['fwd'] else DUP_C)
            if not e['fwd']:
                text3(L, x0 + 52, ty, 'COPY', C('#7a4a58'))
        t_next = arrivals[i + 1]['arrive'] if i + 1 < len(arrivals) else END
        with group(vis_class([(e['arrive'], t_next)]), None, 'ptr-%d' % i):
            L = new_layer('ptr-%d' % i)
            text3(L, x0 + 4, ty, '>', C('#ffffff'))
    # the counters
    states = [(0, 0, 0)]
    for e in arrivals:
        rx, f, d = states[-1]
        states.append((rx + 1, f + (1 if e['fwd'] else 0), d + (0 if e['fwd'] else 1)))
    times = [t_on] + [e['arrive'] for e in arrivals] + [END]
    for k, (rx, f, d) in enumerate(states):
        with group(vis_class([(times[k], times[k + 1])]), None, 'cnt-%d' % k):
            L = new_layer('cnt-%d' % k)
            text3(L, x0 + 4, y1 - 7, 'RX %d' % rx, C('#c9c7e6'))
            text3(L, x0 + 28, y1 - 7, 'FWD %d' % f, LIME)
            text3(L, x0 + 56, y1 - 7, 'DUP %d' % d, DUP_C)
