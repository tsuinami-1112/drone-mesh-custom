"""The mapper itself, as it looks in the browser: a dark map, an aircraft marker
with its lime broadcast ring and its trail, the pilot, a Remote ID card, the list
of active drones, a heuristic hit with no position, and a level 1 bearing fix."""
import math

from .pixart import *
from .fonts import text3, text3_width
from .palette import *
from . import fx
from .relay import uav
from . import timeline as TL

T0, T1 = TL.MAP[0]
END = T_LOOP

PANEL_BG, PANEL_EDGE, PANEL_HI = C('#0a0e13'), C('#1a3a2a'), C('#2f9a46')
LIME, LIME_HOT = C('#88ff99'), C('#00ff66')
MUTED = C('#7a8aa0')
RED_H = C('#ff3d6e')          # the Remote ID drone's colour
LIME_H = C('#9dff3a')         # the DJI drone's
CYAN_H = C('#3dd8ff')         # the level 1 contact's
AMBER_H = C('#ffaa44')
DJI_B = C('#ff66ff')
AN_B = C('#ffaa33')

PILOT1 = (60, 112)
PATH1 = [(96, 62), (126, 58), (131, 72), (127, 88), (118, 100)]     # where the Remote ID drone has been, and goes
DJI_AT, DJI_PILOT = (140, 36), (152, 60)
L1_STATIONS = ((30, 113), (92, 115))
L1_FIX = (44, 84)


def box(L, x0, y0, x1, y1, edge, fill=None, round_=True):
    if fill is not None:
        rect(L, x0, y0, x1 - x0, y1 - y0, fill)
    for x in range(x0 + (1 if round_ else 0), x1 - (1 if round_ else 0)):
        L.set(x, y0, edge)
        L.set(x, y1 - 1, edge)
    for y in range(y0 + (1 if round_ else 0), y1 - (1 if round_ else 0)):
        L.set(x0, y, edge)
        L.set(x1 - 1, y, edge)


def pilot_marker(cx, cy, color):
    pts = blob_pts(cx + .5, cy + .5, 4.5, 4.5)
    out = {p: color for p in pts}
    for (dx, dy) in ((0, -2), (1, -2), (0, -1), (1, -1)):
        out[(cx + dx, cy + dy)] = C('#08050f')
    for dx in range(-2, 4):
        for dy in (1, 2):
            out[(cx + dx, cy + dy)] = C('#08050f')
    return out


def station_glyph(cx, cy):
    pts = ring_pts(cx + .5, cy + .5, 4.4, .6)
    pts |= {(cx - 2, cy - 2), (cx + 1, cy - 2), (cx - 2, cy + 1), (cx + 1, cy + 1), (cx, cy), (cx - 1, cy - 1),
            (cx, cy - 1), (cx - 1, cy)}
    return pts


def aircraft(cx, cy):
    """A heading-rotated triangle, as the mapper draws an ADS-B aircraft (flying east)."""
    return {(cx + i, cy + j) for (i, j) in ((3, 0), (2, 0), (1, 0), (0, 0), (-3, 0), (2, -1), (1, -1), (0, -1), (-1, -1),
                                           (-2, -2), (-3, -2), (1, 1), (0, 1), (-1, 1), (-2, 2), (-3, 2), (0, 0), (-1, 0), (-2, 0))}


# ----------------------------------------------------------------------------
# static chrome
# ----------------------------------------------------------------------------
def dim():
    L = new_layer('ui-dim', alpha=.4)
    rect(L, 0, PIC_Y0, W, PIC_Y1 - PIC_Y0, C('#04021a'))


def chrome():
    L = new_layer('ui-chrome')
    # the DRONES panel
    px0, py0, px1, py1 = 168, 12, 252, 82
    box(L, px0, py0, px1, py1, PANEL_EDGE, PANEL_BG)
    for x in range(px0 + 3, px1 - 3):
        L.set(x, py0 + 12, C('#16261e'))
    box(L, px1 - 36, py0 + 3, px1 - 24, py0 + 9, LIME, C('#06140c'), round_=False)       # the ON badge
    text3(L, px1 - 34, py0 + 4, 'ON', LIME)
    rect(L, px1 - 20, py0 + 3, 10, 6, C('#0c2a16'))                                         # the toggle
    for x in range(px1 - 19, px1 - 11):
        L.set(x, py0 + 3, LIME)
        L.set(x, py0 + 8, LIME)
    rect(L, px1 - 14, py0 + 4, 3, 4, C('#ffffff'))
    text3(L, px1 - 8, py0 + 4, '-', LIME)
    text3(L, px0 + 22, py0 + 15, 'ACTIVE DRONES', MUTED)
    L.set(px0 + 17, py0 + 16, MUTED)
    L.set(px0 + 18, py0 + 16, MUTED)
    L.set(px0 + 19, py0 + 16, MUTED)
    L.set(px0 + 18, py0 + 17, MUTED)
    box(L, px0 + 4, py0 + 22, px1 - 4, py1 - 3, C('#16301f'), C('#080b10'))
    # the bottom bars: geofencing, settings, map layer
    for (x0, x1, edge, label, lc, tail) in ((8, 66, C('#5a2a3a'), 'GEOFENCING', C('#ff99aa'), '0'),
                                            (84, 160, C('#2f9a46'), 'SETTINGS', LIME, '1/1 USB'),
                                            (166, 250, C('#2f9a46'), 'MAP LAYER', LIME, 'OFFLINE')):
        box(L, x0, 124, x1, 135, edge, C('#07090d'))
        text3(L, x0 + 4, 127, label, lc)
        text3(L, x1 - 4 - text3_width(tail), 127, tail, MUTED if label != 'MAP LAYER' else AMBER_H)
    box(L, 8, 100, 17, 121, C('#2a2f38'), C('#0a0d12'))                                     # the zoom control
    text3(L, 11, 103, '+', C('#c9c7e6'))
    text3(L, 11, 112, '-', C('#c9c7e6'))
    L.set(12, 110, C('#2a2f38'))
    return L


def counts(times):
    """'N ACTIVE' in the panel header, changing as contacts arrive; times[i] is when the (i+1)-th arrives."""
    edges = [0.0] + list(times) + [END]
    for n in range(len(times) + 1):
        spans = [(max(edges[n], TL.MAP[0][0] + .0), edges[n + 1])]
        with group(vis_class(spans), None, 'count-%d' % n):
            L = new_layer('count-%d' % n)
            text3(L, 172, 16, '%d ACTIVE' % n, LIME)


def list_item(i, mac, color, t, left=None, dashed=False):
    x0, x1 = 172, 248
    y0 = 38 + i * 11
    with group(vis_class([(t, END)]), None, 'item-%d' % i):
        L = new_layer('item-%d' % i)
        edge = AMBER_H if dashed else color
        for x in range(x0, x1):
            if (not dashed) or (x % 3) != 2:
                L.set(x, y0, edge)
                L.set(x, y0 + 9, edge)
        for y in range(y0, y0 + 10):
            if (not dashed) or (y % 3) != 2:
                L.set(x0, y, edge)
                L.set(x1 - 1, y, edge)
        if left:
            rect(L, x0, y0, 2, 10, left)
        text3(L, x0 + 5, y0 + 2, mac, AMBER_H if dashed else color)


def trail(pts, t_list, color, name):
    """A flight path that grows as the aircraft goes: segment i appears at t_list[i]."""
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        with group(vis_class([(t_list[i], END)]), None, 'trail-%s-%d' % (name, i)):
            L = new_layer('trail-%s-%d' % (name, i))
            for p in line_pts(a[0], a[1], b[0], b[1]):
                L.set(p[0], p[1], color)


def contact(name, pos_pts, color, t_on, pilot=None, t_pilot=None):
    """An aircraft marker with its lime ring: it follows pos_pts [(t, x, y)]; the pilot's marker stands still."""
    ref = (pos_pts[0][1], pos_pts[0][2])
    cls, hidden = move([(t, x, y) for (t, x, y) in pos_pts], ref=ref)
    # the marker is on from t_on: it sits at the first point until then
    with group(vis_class([(t_on, END)]), None, 'contact-' + name):
        with group(cls, None, 'contact-move-' + name):
            L = new_layer('uav-' + name)
            for p in uav(ref[0], ref[1], color):
                L.set(p[0], p[1], color, True)
            ring = new_layer('uav-ring-' + name)
            for p in ring_pts(ref[0] + .5, ref[1] + .5, 9.5, .6):
                ring.set(p[0], p[1], LIME_HOT, True)
            bloom('uav-' + name, ring.pix.keys(), (0, 255, 102), ((1.5, .25), (3, .1)))
    if pilot:
        with group(vis_class([(t_pilot, END)]), None, 'pilot-' + name):
            L = new_layer('pilot-' + name)
            for p, c in pilot_marker(pilot[0], pilot[1], color).items():
                L.set(p[0], p[1], c, True)
            ping = new_layer('pilot-ring-' + name)
            for p in ring_pts(pilot[0] + .5, pilot[1] + .5, 6.5, .5):
                ping.set(p[0], p[1], color, True)


def pop(name, x, y, t, color=LIME_HOT, r=13):
    """A quick ring: a new contact announces itself."""
    with group(vis_class([(t, t + .3)]), None, 'pop-' + name):
        L = new_layer('pop-' + name)
        for p in fx.dashed_ring(x + .5, y + .5, r, 2):
            L.set(p[0], p[1], color, True)


def popup(t_open, t_close):
    """The Remote ID card for the drone, typed in row by row."""
    x0, y0, x1, y1 = 74, 8, 166, 88
    CLIPS['card'] = (x0 + 2, y0 + 2, x1 - x0 - 4, y1 - y0 - 4)
    with group(vis_class([(t_open, t_close)]), None, 'popup'):
        L = new_layer('popup')
        box(L, x0, y0, x1, y1, C('#2f6a3c'), C('#0a0d12'))
        for x in range(x0 + 1, x1 - 1):
            L.set(x, y0 + 1, C('#10261a'))
        for (x, y) in ((117, y1), (118, y1), (119, y1), (118, y1 + 1)):
            L.set(x, y, C('#2f6a3c'))
        rows = [
            (15, [('60:60:1F:AA:BB:01', C('#ffffff'))]),
            (23, [('REMOTE ID', MUTED)]),
            (29, [('SOURCE ', MUTED), ('WIFI BEACON', C('#dde6ee'))]),
            (35, [('SERIAL NUMBER', MUTED)]),
            (41, [('1581F5FHB229F00202DR', C('#ffffff'))]),
            (47, [('OPERATOR ID', MUTED)]),
            (53, [('DEU87ASTRDGE12K8', C('#ffffff'))]),
            (59, [('UA TYPE ', MUTED), ('MULTIROTOR', C('#dde6ee'))]),
            (65, [('EU CATEGORY ', MUTED), ('OPEN C1', C('#dde6ee'))]),
            (71, [('ALT 120', C('#dde6ee')), ('  SPD 13', C('#dde6ee')), ('  HDG 100', C('#dde6ee'))]),
        ]
        for (y, parts) in rows:
            x = x0 + 5
            for (txt, c) in parts:
                text3(L, x, y, txt, c)
                x += text3_width(txt) + 2
        for (bx, label) in ((x0 + 5, 'GMAPS DRONE'), (x0 + 50, 'GMAPS PILOT')):
            box(L, bx, 78, bx + 42, 85, C('#2f6a3c'))
            text3(L, bx + 3, 79, label, LIME)
        box(L, x1 - 36, y0 + 13, x1 - 5, y0 + 20, C('#4a5a6a'))
        text3(L, x1 - 34, y0 + 14, 'UNKNOWN', C('#aab6c4'))
        # a row is typed in at a time: covers slide away to the right
        ys = [14, 22, 28, 34, 40, 46, 52, 58, 64, 70, 77]
        for r, ty in enumerate(ys):
            t0 = t_open + .15 + r * .13
            cover = new_layer('popup-cover-%d' % r, clip='card',
                              anim=tl([(0, dict(x=0)), (t0, dict(x=0)), (t0 + .13, dict(x=90)), (T_LOOP, dict(x=90))],
                                      ease='steps(18,end)'))
            rect(cover, x0 + 3, ty - 1, 88, 7 if r < 10 else 9, C('#0a0d12'))


def banner(t_on, t_off):
    """The strip across the top of the map when something with no Remote ID is heard."""
    x0, y0, x1, y1 = 22, 12, 150, 22
    CLIPS['banner'] = (x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2)
    with group(vis_class([(t_on, t_off)]), None, 'banner'):
        L = new_layer('banner')
        box(L, x0, y0, x1, y1, LIME_HOT, C('#03120a'))
        text3(L, x0 + 5, y0 + 3, 'POSSIBLE DRONE, NO REMOTE ID', LIME)
        cover = new_layer('banner-cover', clip='banner',
                          anim=tl([(0, dict(x=0)), (t_on, dict(x=0)), (t_on + .5, dict(x=130)), (T_LOOP, dict(x=130))],
                                  ease='steps(28,end)'))
        rect(cover, x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2, C('#03120a'))


def level1(t0):
    """Two level 1 stations hear the analog video link of a drone that broadcasts nothing else:
    each reports a bearing, the rays cross, and the mapper fixes a position."""
    hue = CYAN_H
    for k, (sx, sy) in enumerate(L1_STATIONS):
        with group(vis_class([(t0 + k * .12, END)]), None, 'l1-st-%d' % k):
            L = new_layer('l1-st-%d' % k)
            for p in station_glyph(sx, sy):
                L.set(p[0], p[1], AMBER_H, True)
            text3(L, sx + 7, sy - 2, 'RX0%d' % (k + 1), AMBER_H)
    fx_, fy_ = L1_FIX
    rays = []
    for (sx, sy) in L1_STATIONS:
        d = math.hypot(fx_ - sx, fy_ - sy)
        ux, uy = (fx_ - sx) / d, (fy_ - sy) / d
        rays.append((sx, sy, sx + ux * (d + 90), sy + uy * (d + 90), ux, uy, d))
    # each ray extends from its station in three steps, wedge and all
    for k, (sx, sy, ex, ey, ux, uy, d) in enumerate(rays):
        for step in range(3):
            frac = (step + 1) / 3.0
            t = t0 + .3 + k * .12 + step * .12
            span = [(t, t + .12)] if step < 2 else [(t, END)]
            with group(vis_class(span), None, 'l1-ray-%d-%d' % (k, step)):
                L = new_layer('l1-ray-%d-%d' % (k, step))
                x1_, y1_ = sx + (ex - sx) * frac, sy + (ey - sy) * frac
                for p in line_pts(int(sx), int(sy), int(x1_), int(y1_)):
                    if PIC_Y0 <= p[1] < PIC_Y1 and 0 <= p[0] < 166:
                        L.set(p[0], p[1], hue, True)
        with group(vis_class([(t0 + .66 + k * .05, END)]), None, 'l1-wedge-%d' % k):
            Wd = new_layer('l1-wedge-%d' % k, alpha=.14)
            a = math.atan2(uy, ux)
            pts = [(sx, sy)] + [(sx + math.cos(a + da) * (d + 90), sy + math.sin(a + da) * (d + 90))
                                for da in (-.16, -.08, 0, .08, .16)]
            for p in poly_pts(pts):
                if PIC_Y0 <= p[1] < PIC_Y1 and 0 <= p[0] < 166:
                    Wd.set(p[0], p[1], hue)
    t_fix = t0 + .8
    with group(vis_class([(t_fix, END)]), None, 'l1-fix'):
        fill = new_layer('l1-fix-fill', alpha=.1)
        for p in blob_pts(fx_ + .5, fy_ + .5, 11, 11):
            fill.set(p[0], p[1], hue)
        L = new_layer('l1-fix')
        for p in fx.dashed_ring(fx_ + .5, fy_ + .5, 11, 3):
            L.set(p[0], p[1], hue, True)
        for p in uav(fx_, fy_, hue):
            L.set(p[0], p[1], hue, True)
        for p in ring_pts(fx_ + .5, fy_ + .5, 9.5, .6):
            L.set(p[0], p[1], LIME_HOT, True)
        text3(L, fx_ + 13, fy_ - 9, 'BEARING FIX', C('#9fe9f5'))
        text3(L, fx_ + 13, fy_ - 3, '+-45 M', C('#9fe9f5'))


def plane():
    """An aircraft from the ADS-B overlay crossing the top of the map."""
    ref = (40, 30)
    pts = [(T0 - .1, -14, 30), (T1 + .5, 170, 30)]
    cls, hidden = move(pts, ref=ref)
    with group(cls + (' h' if hidden else ''), None, 'plane'):
        L = new_layer('plane')
        for p in aircraft(*ref):
            L.set(p[0], p[1], CYAN_H, True)
        tr = new_layer('plane-trail', alpha=.5)
        for p in line_pts(ref[0] - 32, ref[1], ref[0] - 6, ref[1]):
            if (p[0] % 3) != 2:
                tr.set(p[0], p[1], CYAN_H)


def build():
    dim()
    plane()
    # --- the Remote ID drone: it has been tracked since before this shot
    ts = [T0, T0 + .9, T0 + 1.7, T0 + 2.4]
    pts = [(ts[0] - .0, *PATH1[1]), (ts[1], *PATH1[2]), (ts[2], *PATH1[3]), (ts[3], *PATH1[4]), (T1 + .5, *PATH1[4])]
    trail(PATH1, [0.0 if False else T0, T0 + .0, ts[1], ts[2]], RED_H, 'c1')
    contact('c1', pts, RED_H, T0, pilot=PILOT1, t_pilot=T0 + .3)
    # --- the DJI DroneID contact
    t_dji = 27.0
    contact('c2', [(t_dji, DJI_AT[0], DJI_AT[1]), (T1 + .5, DJI_AT[0] + 10, DJI_AT[1] + 4)], LIME_H, t_dji, pilot=DJI_PILOT,
            t_pilot=t_dji + .3)
    pop('c2', DJI_AT[0], DJI_AT[1], t_dji)
    pop('c2p', DJI_PILOT[0], DJI_PILOT[1], t_dji + .3, LIME_H, 9)
    # --- the card for the first drone
    popup(24.4, 26.8)
    # --- a guess: something with no Remote ID
    banner(28.0, 30.4)
    # --- level 1: a bearing fix on a silent drone
    level1(29.0)
    chrome()
    t_items = [T0, t_dji, 28.1, 29.8]
    counts(t_items)
    list_item(0, '60:60:1F:AA:BB:01', RED_H, t_items[0])
    list_item(1, '9C:9C:1F:00:00:02', LIME_H, t_items[1], left=DJI_B)
    list_item(2, '34:D2:62:00:00:03', AMBER_H, t_items[2], dashed=True)
    list_item(3, 'AF:00:52:03:16:64', CYAN_H, t_items[3], left=AN_B)
