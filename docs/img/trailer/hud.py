"""The film frame around every shot: letterbox bars, a thin frame, small print."""
import math

from .pixart import *
from .fonts import text3, text3_width, text5, text5_width
from .palette import *


def scrim(x0, y0, x1, y1, color=INK, alphas=(.14, .26, .4), step=3, name='scrim', **kw):
    """A soft dark plate behind text: bands of translucent colour, stronger toward the middle."""
    out = []
    for i, a in enumerate(alphas):
        L = new_layer('%s-%d' % (name, i), alpha=a, **kw)
        d = (len(alphas) - 1 - i) * step
        rect(L, x0 - d, y0 - d, (x1 - x0) + 2 * d, (y1 - y0) + 2 * d, color)
        out.append(L)
    # each band is drawn on top of the wider one, so alphas compound; trim the extents to the picture
    for L in out:
        for p in [p for p in L.pix if not (PIC_Y0 <= p[1] < PIC_Y1)]:
            del L.pix[p]
    return out


def hud_panel(x0, y0, x1, y1, name='panel', alpha=.62, edge=C('#3a3a80'), fill=C('#060418')):
    """A translucent dark plate with a thin bright edge, for readouts over a bright sky."""
    P = new_layer(name + '-fill', alpha=alpha)
    rect(P, x0, y0, x1 - x0, y1 - y0, fill)
    E = new_layer(name + '-edge')
    for x in range(x0 + 1, x1 - 1):
        E.set(x, y0, edge)
        E.set(x, y1 - 1, edge)
    for y in range(y0 + 1, y1 - 1):
        E.set(x0, y, edge)
        E.set(x1 - 1, y, edge)
    for (x, y) in ((x0 + 1, y0 + 1), (x1 - 2, y0 + 1), (x0 + 1, y1 - 2), (x1 - 2, y1 - 2)):
        E.set(x, y, mix(edge, fill, .5))
    return P, E


def mark(L, x, y, c=MESH, hot=MESH_HOT):
    """The little three-node logo: a triangle of links."""
    for (a, b) in (((1, 5), (5, 5)), ((1, 5), (3, 1)), ((5, 5), (3, 1))):
        for p in line_pts(x + a[0], y + a[1], x + b[0], y + b[1]):
            L.set(p[0], p[1], c)
    for (nx, ny) in ((0, 4), (4, 4), (2, 0)):
        rect(L, x + nx, y + ny, 2, 2, hot, True)


def bars():
    L = new_layer('bars')
    rect(L, 0, 0, W, TOP_H, BLACK)
    rect(L, 0, PIC_Y1, W, BOT_H, BLACK)
    for x in range(W):
        L.set(x, TOP_H - 1, C('#140f2a'))
        L.set(x, PIC_Y1, C('#140f2a'))
    return L


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
    return F


# ----------------------------------------------------------------------------
# captions: the word of the moment, typed along the bottom bar
# ----------------------------------------------------------------------------
CAPTION_Y = PIC_Y1 + 4
CLIPS['bar'] = (3, PIC_Y1 + 2, W - 6, BOT_H - 4)


def caption(word, accent, detail, t0, t1, type_cps=70.0):
    """A big word and a line of small print, typed in at t0 and gone at t1."""
    with group(vis_class([(t0, t1)]), None, 'caption-%s-%g' % (word, t0)):
        L = new_layer('caption')
        rect(L, 5, CAPTION_Y, 2, 7, accent, True)
        text5(L, 10, CAPTION_Y, word, C('#ffffff'))
        x = 10 + text5_width(word) + 8
        text3(L, x, CAPTION_Y + 1, detail, C('#9fa4d8'))
        width = x + text3_width(detail) + 4
        dur = max(.3, (width - 5) / type_cps)
        cover = new_layer('caption-cover', clip='bar',
                          anim=tl([(0, dict(x=0)), (t0, dict(x=0)), (min(t0 + dur, t1 - .05), dict(x=W)),
                                   (T_LOOP, dict(x=W))], ease='steps(%d,end)' % max(8, int((width - 5) / 3))))
        rect(cover, 4, CAPTION_Y - 2, W - 8, 11, BLACK)


def progress(marks):
    """A thin progress line along the foot of the picture, the way a video player draws one:
    it fills over the loop and ticks mark where each part of the film begins."""
    y = PIC_Y1 - 1
    T = new_layer('progress-ticks')
    for t in marks:
        x = int(round(W * t / T_LOOP))
        for yy in (y - 1, y, y + 1):
            T.set(x, yy, C('#6a6aa8'))
    P = new_layer('progress', style='opacity:0',
                  anim=tl([(0, dict(o=0, x=-W)), (.05, dict(o=1, x=-W)), (T_LOOP - .05, dict(o=1, x=-3)),
                           (T_LOOP, dict(o=0, x=0))]))
    for x in range(W):
        P.set(x, y, MESH)
    P.set(W - 1, y, C('#ffffff'), True)
    P.set(W - 2, y, MESH_HOT, True)
    return P


# ----------------------------------------------------------------------------
# screen effects: cuts, scanlines, vignette
# ----------------------------------------------------------------------------
def glitch(t, seed):
    """A cut: a few frames of coloured tears across the picture."""
    rng = Rng(seed)
    cols = [C('#00e5ff'), C('#ff2bd6'), C('#ffffff'), C('#67ea94')]
    frames = [(t - .07, t - .03), (t - .03, t + .02), (t + .02, t + .07), (t + .07, t + .11)]
    for k, (a, b) in enumerate(frames):
        with group(vis_class([(max(a, 0.0), b)]), None, 'glitch-%g-%d' % (t, k)):
            L = new_layer('glitch-%g-%d' % (t, k), alpha=.8 - k * .12)
            for _ in range(7 - k):
                y = rng.randint(PIC_Y0, PIC_Y1 - 6)
                h = rng.randint(1, 4)
                x = rng.randint(-10, W - 40)
                w = rng.randint(30, 150)
                c = rng.choice(cols)
                for yy in range(y, y + h):
                    for xx in range(max(0, x), min(W, x + w)):
                        L.set(xx, yy, c)
            for _ in range(2):
                y = rng.randint(PIC_Y0, PIC_Y1 - 1)
                for xx in range(W):
                    L.set(xx, y, C('#ffffff'))


def scanlines(alpha=.1):
    """Every other row of the picture a little darker, like a CRT."""
    L = new_layer('scanlines', alpha=alpha)
    for y in range(PIC_Y0 + 1, PIC_Y1, 2):
        rect(L, 0, y, W, 1, C('#000000'))
    return L


def vignette():
    """Darker toward the corners, in three steps."""
    out = []
    for k, d0 in enumerate((.86, .98, 1.1)):
        L = new_layer('vignette-%d' % k, alpha=.13)
        for y in range(PIC_Y0, PIC_Y1):
            for x in range(W):
                d = math.hypot((x + .5 - W / 2.0) / (W / 2.0), (y + .5 - (PIC_Y0 + PIC_Y1) / 2.0) / ((PIC_Y1 - PIC_Y0) / 2.0))
                if d > d0:
                    L.set(x, y, C('#000000'))
        out.append(L)
    return out
