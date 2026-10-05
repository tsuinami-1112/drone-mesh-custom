"""The title card, written over the city: just the promise, small and white."""
from .pixart import *
from .fonts import text5, text5_width
from .palette import *
from . import timeline as TL

TITLE = 'COUNTERSURVEILLANCE · 24/7'
TITLE_Y, TRACK = 27, 2                  # centred in the sky; wide letter-spacing keeps it quiet


def build():
    spans = TL.TITLE_OUT + TL.TITLE_IN
    # the title is on at the start of the loop and again at the end; in between it
    # flickers out and, later, back in
    with group(vis_class(spans), None, 'title'):
        x = (W - text5_width(TITLE, TRACK)) // 2
        shadow, T = new_layer('title-shadow'), new_layer('title')
        text5(T, x, TITLE_Y, TITLE, C('#ffffff'), gap=TRACK)
        pixels = set(T.pix)
        for p in outline_pts(pixels):
            shadow.set(p[0], p[1], INK)
        bloom('title', pixels, (190, 215, 255), ((1.5, .14), (3, .06)))
