"""A day in a few seconds: the same city from dusk to dusk. The sky changes
colour, the sun crosses it, the moon sets and rises again, the windows go dark
and light, and the station never stops: a week of uptime fills in a grid."""
import math

from .pixart import *
from .fonts import text3, text3_width, text5, text5_width
from .palette import *
from . import hud
from . import meshfont as mf
from . import timeline as TL

T_A, T_B = TL.LAPSE


def ramp4(stops, n):
    """n colours, interpolated across the anchor colours."""
    out = []
    for k in range(n):
        u = k / float(n - 1) * (len(stops) - 1)
        i = min(int(u), len(stops) - 2)
        out.append(mix(stops[i], stops[i + 1], u - i))
    return out


NIGHT = list(SKY)
DAWN = ramp4([C('#1a1f66'), C('#5a3a9a'), C('#e8607a'), C('#ffb070')], len(SKY))
DAY = ramp4([C('#2563d8'), C('#4a90ec'), C('#8cc8f8'), C('#ffe0c0')], len(SKY))
DUSK = ramp4([C('#241466'), C('#6a2a9a'), C('#e04a7a'), C('#ff9a50')], len(SKY))


def sky_times():
    """When each look is at its fullest."""
    return [(0, NIGHT), (T_A + .4, NIGHT), (TL.SUNRISE - .3, DAWN), (TL.SUNRISE + .9, DAY), (TL.SUNSET - .8, DAY),
            (TL.SUNSET + .1, DUSK), (TL.SUNSET + .9, NIGHT), (T_LOOP, NIGHT)]


def recolor_sky():
    looks = sky_times()
    for L in LAYERS:
        if not L.name.startswith('sky-'):
            continue
        k = int(L.name.split('-')[1])
        L.anim = recolor([(t, pal[k]) for (t, pal) in looks])


def fade(layers, keys):
    """Give the named layers an opacity keyframe list (time, opacity); returns its class."""
    cls = tl([(t, dict(o=o)) for (t, o) in keys])
    for L in LAYERS:
        if L.name in layers:
            L.anim = (L.anim + ' ' if L.anim else '') + cls
    return cls


def fades():
    fade({'stars-dim', 'stars-mid', 'stars-bright'},
         [(0, 1), (T_A + .4, 1), (TL.SUNRISE, 0), (TL.SUNSET - .6, 0), (TL.SUNSET + .3, 1), (T_LOOP, 1)])
    cls = fade({'win-far', 'win-mid', 'win-near'} | {L.name for L in LAYERS if L.name.startswith('wbloom-')},
               [(0, 1), (T_A + .5, 1), (TL.SUNRISE + .5, .08), (TL.SUNSET - 1.0, .08), (TL.SUNSET, 1), (T_LOOP, 1)])
    # a window that blinks dark has to dim with the lit ones, or it leaves a black spot by day
    for L in LAYERS:
        if L.name == 'twinkle':
            L.groups += ((cls, None, 'twinkle'),)


def tint():
    """A veil of daylight over the towers: orange at the ends of the day, pale blue at noon."""
    L = new_layer('day-tint', paint='group', style='opacity:0')
    rect(L, 0, PIC_Y0, W, PIC_Y1 - PIC_Y0, C('#000000'))
    L.anim = tl([(0, dict(o=0, f='#ff9a6a')), (T_A + .4, dict(o=0, f='#ff9a6a')),
                 (TL.SUNRISE + .1, dict(o=.26, f='#ff9a6a')), (TL.SUNRISE + 1.0, dict(o=.24, f='#a8d8ff')),
                 (TL.SUNSET - .9, dict(o=.24, f='#a8d8ff')), (TL.SUNSET, dict(o=.28, f='#ff7a5a')),
                 (TL.SUNSET + .8, dict(o=0, f='#ff7a5a')), (T_LOOP, dict(o=0, f='#ff7a5a'))])
    return L


def moon_class():
    """The moon: still at the start, sets as the sun comes up, rises again at dusk
    behind the roofs and settles back where it was."""
    return tl([(0, dict(o=1, x=0, y=0)), (T_A + .1, dict(o=1, x=0, y=0)), (TL.SUNRISE + .1, dict(o=1, x=46, y=52)),
               (TL.SUNRISE + .13, dict(o=0, x=46, y=52)), (TL.SUNSET + .0, dict(o=0, x=-36, y=60)),
               (TL.SUNSET + .03, dict(o=1, x=-36, y=60)), (T_B - .1, dict(o=1, x=0, y=0)), (T_LOOP, dict(o=1, x=0, y=0))])


SUN_REF = (128, 40)


def sun():
    """The sun: a bright disc with a warm bloom crossing the sky from one side to the other."""
    pts = []
    n = 24
    t0, t1 = TL.SUNRISE - .55, TL.SUNSET + .55
    for i in range(n + 1):
        s = i / float(n)
        t = t0 + (t1 - t0) * s
        pts.append((t, -16 + 288 * s, 108 - 92 * math.sin(math.pi * s)))
    cls, hidden = move(pts, ref=SUN_REF)
    with group(cls + (' h' if hidden else ''), None, 'sun'):
        L = new_layer('sun')
        disc = blob_pts(SUN_REF[0], SUN_REF[1], 8, 8)
        for (x, y) in disc:
            d = math.hypot(x + .5 - SUN_REF[0], y + .5 - SUN_REF[1]) / 8.0
            L.set(x, y, ramp_at([C('#ffb347'), C('#ffe08a'), C('#fff6d0')], 2.0 - d * 1.6, x, y, .7), True)
        bloom('sun', disc, (255, 200, 120), ((2.5, .34), (5, .22), (9, .13), (14, .07), (20, .035), (28, .015)))


# ----------------------------------------------------------------------------
# the numbers
# ----------------------------------------------------------------------------
def hud_lapse():
    spans = [(T_A + .1, T_B)]
    with group(vis_class(spans), None, 'lapse-hud'):
        numerals()
        clock()
        grid()
        meter()


def numerals():
    """24/7 in big letters made of links and nodes."""
    s = '24/7'
    adv = 24
    w = adv * len(s) - 6
    x0 = 106
    hud.scrim(x0 - 6, 14, x0 + w + 6, 45, name='num-scrim')
    shadow, lines, dots = new_layer('num-shadow'), new_layer('num-lines'), new_layer('num-dots')
    alll, alld = set(), set()
    for i, ch in enumerate(s):
        l, d = mf.glyph_pixels(ch, x0 + i * adv, 16)
        alll |= l
        alld |= d
    for p in outline_pts(alll | alld):
        shadow.set(p[0], p[1], INK)
    for p in alll:
        lines.set(p[0], p[1], MESH)
    for p in alld:
        dots.set(p[0], p[1], MESH_HOT, True)
    bloom('num', alll | alld, MESH, ((1.5, .3), (3, .16), (5, .08)))


def clock():
    """The hour, ticking: 24 hours in the length of the shot."""
    span = (T_B - T_A) / 24.0
    for n in range(25):
        h = (TL.HOUR0 + n) % 24
        t0 = T_A + n * span
        t1 = T_A + (n + 1) * span if n < 24 else T_B
        with group(vis_class([(t0, t1)]), None, 'hour-%d' % n):
            L = new_layer('hour-%d' % n)
            text = '%02d:00' % h
            text5(L, W - 8 - text5_width(text), PIC_Y0 + 3, text, C('#ffffff'))


def grid():
    """A week of uptime, an hour to a cell, uncovered column by column by a scanning cursor. Green is
    online; one cell goes amber (the battery ran flat) and the next is green again."""
    x0, y0, w, h = 8, 24, 24, 7
    hud.hud_panel(x0 - 4, y0 - 13, x0 + w * 4 + 4, y0 + h * 4 + 16, name='grid-panel')
    L = new_layer('grid-title')
    text3(L, x0, y0 - 8, 'UPTIME \u00b7 7 DAYS', C('#c9c7e6'))
    rng = Rng(77)
    cells = {}
    for r in range(h):
        for c in range(w):
            col = MESH_DIM if rng.random() > .12 else MESH
            if (r, c) == (3, 14):
                col = AMBER
            cells[(r, c)] = col
    step = .19
    for c in range(w):
        t_c = T_A + .6 + c * step
        with group(vis_class([(t_c, T_B)]), None, 'grid-col-%d' % c):
            G = new_layer('grid-col-%d' % c)
            for r in range(h):
                rect(G, x0 + c * 4, y0 + r * 4, 3, 3, cells[(r, c)], True)
    # the cursor that sweeps across
    cur = new_layer('grid-cursor', anim=tl([(0, dict(x=0)), (T_A + .6, dict(x=0)), (T_A + .6 + w * step, dict(x=w * 4)),
                                            (T_LOOP, dict(x=w * 4))], ease='steps(%d,end)' % w))
    for yy in range(y0 - 1, y0 + h * 4):
        cur.set(x0 - 1, yy, C('#ffffff'), True)
    K = new_layer('grid-legend')
    rect(K, x0, y0 + h * 4 + 4, 3, 3, MESH_DIM)
    text3(K, x0 + 5, y0 + h * 4 + 3, 'ONLINE', C('#c9c7e6'))
    rect(K, x0 + 33, y0 + h * 4 + 4, 3, 3, AMBER)
    text3(K, x0 + 38, y0 + h * 4 + 3, 'FLAT, BACK BY ITSELF', C('#c9c7e6'))


def meter():
    """What the solar panel and the battery are doing as the day goes by."""
    x0, y0, bw = 207, 24, 44
    hud.hud_panel(x0 - 5, y0 - 4, x0 + bw + 5, y0 + 27, name='meter-panel')
    L = new_layer('meter-frame')
    text3(L, x0, y0, 'SOLAR', C('#ffd23a'))
    text3(L, x0, y0 + 12, 'BATTERY', C('#7fe3ff'))
    states = [(T_A, '0 W', 71), (TL.SUNRISE, '6 W', 70), (TL.SUNRISE + .9, '20 W', 76), (TL.NOON, '20 W', 88),
              (TL.SUNSET - 1.0, '8 W', 96), (TL.SUNSET, '0 W', 95), (TL.SUNSET + 1.2, '0 W', 93)]
    for i, (t, watts, pct) in enumerate(states):
        t_end = states[i + 1][0] if i + 1 < len(states) else T_B
        with group(vis_class([(t, t_end)]), None, 'meter-%d' % i):
            S = new_layer('meter-%d' % i)
            text3(S, x0 + bw - text3_width(watts), y0, watts, C('#ffffff'))
            pt = '%d%%' % pct
            text3(S, x0 + bw - text3_width(pt), y0 + 12, pt, C('#ffffff'))
            watts_n = int(watts.split()[0])
            for xx in range(x0, x0 + bw):
                S.set(xx, y0 + 7, C('#2a2858'))
                S.set(xx, y0 + 19, C('#2a2858'))
            for xx in range(x0, x0 + int(bw * min(1.0, watts_n / 20.0))):
                S.set(xx, y0 + 7, C('#ffd23a'), True)
            for xx in range(x0, x0 + int(bw * pct / 100.0)):
                S.set(xx, y0 + 19, C('#7fe3ff'), True)
