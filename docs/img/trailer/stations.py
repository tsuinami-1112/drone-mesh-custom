"""A field station on a pole, at three sizes: a solar panel, a pale IP65 box
with an LED, a LoRa whip on top and a shorter 2.4 GHz antenna to one side.
Far ones are a few pixels; the hero is drawn in detail."""
from .pixart import *
from .palette import *

WHIP = C('#c9c7e6')
WHIP_TIP = C('#ffffff')
CABLE = C('#0c0a1c')
LED_ON = C('#7dffa8')


def _panel(L, x0, x1, y_left, rise, thick, cell=4):
    """A solar panel seen from the side, tilted up toward the right: columns
    x0..x1, its top edge `rise` pixels higher at the right end than at the
    left. A frame, cells split by thin grid lines, a lighter top row of
    cells. Returns the underside (x, y) of every column."""
    under = {}
    n = x1 - x0
    for x in range(x0, x1 + 1):
        top = y_left - int(round(rise * (x - x0) / float(n)))
        for k in range(thick):
            y = top + k
            if k == 0:
                c = METAL[3]                             # the lit top edge of the frame
            elif k == thick - 1:
                c = METAL[1]
            elif (x - x0) % cell == 0 or k == thick // 2:
                c = SOLAR[0]                             # the grid between the cells
            elif k == 1:
                c = SOLAR[3]                             # the glass catches the sky along the top
            else:
                c = SOLAR[2]
            L.set(x, y, c)
        under[x] = top + thick
    for k in range(thick):                               # the end caps of the frame
        L.set(x0, y_left + k, METAL[2])
        L.set(x1, y_left - rise + k, METAL[3])
    return under


def hero(L, bx, by, k=1.0):
    """The big one: pole, panel, box, battery and antennas, drawn at k times
    the base size. (bx, by) is the foot of the pole. Returns the points other
    things hook onto."""
    def S(n):
        return max(1, int(round(n * k)))

    pw = 2 if k < 1.8 else 3
    # battery box on the ground beside the pole
    bw_, bh_ = S(12), S(7)
    rect(L, bx + 2, by - bh_, bw_, bh_, METAL[1])
    rect(L, bx + 2, by - bh_, bw_, 1, METAL[3])
    rect(L, bx + 2, by - 1, bw_, 1, METAL[0])
    for x in range(bx + 3, bx + bw_ + 1):
        L.set(x, by - S(4), METAL[0])
    rect(L, bx + 4, by - bh_ + 1, 2, 1, C('#ffb347'), True)
    rect(L, bx + bw_ - 4, by - bh_ + 1, 4, 1, METAL[2])
    # the pole, with a lit left edge
    top = by - S(31)
    for y in range(top, by + 1):
        L.set(bx - 1, y, METAL[3])
        L.set(bx, y, METAL[1])
        if pw == 3:
            L.set(bx + 1, y, METAL[0])
    rect(L, bx - 3, by - 1, 6 + pw - 2, 2, METAL[0])         # base plate
    L.set(bx - 3, by - 1, METAL[2])
    L.set(bx + 2 + pw - 2, by - 1, METAL[2])
    # the LoRa whip on top, the highest thing for miles
    rect(L, bx - 2, top - 2, 3 + pw, 2, METAL[2])
    rect(L, bx - 1, top - 3, 1 + pw, 1, METAL[3])
    whip_top = top - 3 - S(16)
    for y in range(whip_top, top - 3):
        L.set(bx - 1, y, WHIP)
        L.set(bx, y, METAL[2])
    L.set(bx - 1, whip_top - 1, WHIP_TIP)
    L.set(bx, whip_top - 1, WHIP)
    # the solar panel, tilted to face the sky, held on a strut
    under = _panel(L, bx - S(23), bx - 3, by - S(19), S(8), S(7), cell=S(4))
    mid = bx - S(13)
    for (x, y) in line_pts(bx - 1, by - S(12), mid, under[mid]):
        L.set(x, y, METAL[1])
    mid = bx - S(8)
    for (x, y) in line_pts(bx - 1, by - S(14), mid, under[mid]):
        L.set(x, y, METAL[0])
    # the pale enclosure, lit from the city
    bx0, by0, bw, bh = bx + pw, by - S(24), S(11), S(11)
    rect(L, bx0, by0, bw, bh, PALE[2])
    rect(L, bx0, by0, bw, 1, PALE[3])
    for y in range(by0, by0 + bh):
        L.set(bx0, y, PALE[3])
        L.set(bx0 + bw - 1, y, PALE[0])
    rect(L, bx0, by0 + bh - 1, bw, 1, PALE[0])
    rect(L, bx0 + 1, by0 + S(3), bw - 2, 1, PALE[1])           # the lid seam
    rect(L, bx0 + bw - S(4), by0 + S(5), S(3), S(3), PALE[1])  # a membrane vent
    L.set(bx0 + bw - S(4) + S(3) // 2, by0 + S(5) + S(3) // 2, PALE[0])
    for x in (bx0 + S(2), bx0 + S(5), bx0 + S(8)):             # cable glands
        rect(L, x, by0 + bh, 1, 2, CABLE)
        L.set(x, by0 + bh - 1, METAL[0])
    led = [(bx0 + S(2) + i, by0 + S(5)) for i in range(max(2, S(2)))]
    for (x, y) in led:
        L.set(x, y, LED_ON, True)
    # the 2.4 GHz antenna, a short whip off the side of the box
    rect(L, bx0 + bw, by0 + 2, 2, 2, METAL[1])
    for y in range(by0 - S(5), by0 + 3):
        L.set(bx0 + bw + 2, y, WHIP)
    L.set(bx0 + bw + 2, by0 - S(5) - 1, WHIP_TIP)
    # coax up the pole and a drooping tail across the roof
    for y in range(top - 2, by0 + 3):
        L.set(bx + pw, y, CABLE)
    for (x, y) in line_pts(bx0 + 2, by0 + bh + 2, bx0 - 8, by + 1):
        L.set(x, y, CABLE)
    return dict(tip=(bx - 1, whip_top - 1), link=(bx - 1, whip_top + 3), led=led, box=(bx0, by0, bw, bh),
                ant24=(bx0 + bw + 2, by0 - S(5) - 1), whip=(bx - 1, whip_top))


MID = ("...t...",
       "...w...",
       "...w...",
       "...w..a",
       "sSSp..a",
       "ssSpbb.",
       ".sSpbl.",
       "...pBB.",
       "...p...",
       "...p...")
MID_PAL = {'t': WHIP_TIP, 'w': WHIP, 'a': WHIP, 'p': METAL[2], 's': SOLAR[1], 'S': SOLAR[2],
           'b': PALE[2], 'B': PALE[0], 'l': LED_ON}


def medium(L, bx, by):
    """A mid-distance station: foot of the pole at (bx, by)."""
    sprite(L, bx - 3, by - 9, MID, MID_PAL, emit='l')
    return dict(tip=(bx, by - 9), link=(bx, by - 8), led=[(bx + 2, by - 3)], ant24=(bx + 3, by - 6))


SMALL = ("..t..",
         "..w..",
         "..w..",
         "sSp..",
         "ssplb",
         "..pbB",
         "..p..")
SMALL_PAL = {'t': WHIP_TIP, 'w': WHIP, 'p': METAL[2], 's': SOLAR[1], 'S': SOLAR[2],
             'b': PALE[2], 'B': PALE[0], 'l': LED_ON}


def small(L, bx, by):
    """A far-off station."""
    sprite(L, bx - 2, by - 6, SMALL, SMALL_PAL, emit='l')
    return dict(tip=(bx, by - 6), link=(bx, by - 5), led=[(bx + 2, by - 2)], ant24=None)
