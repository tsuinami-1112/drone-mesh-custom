"""The home station's corner of the roof: a stair hut with a lamp, the home
mast on top of it, and a lone figure in a hood with a laptop on a crate."""
from .pixart import *
from .palette import *

HUT = (198, 98, 236, 131)           # x0, y0, x1, y1 of the stair hut
MAST_FOOT = (226, 98)
DOOR = (211, 113, 220)              # x0, y0, x1; it runs down to the roof
LAMP = (215, 108)
LAPTOP_AT = (178, 131)              # where the crate under the laptop stands
FIGURE_AT = (168, 125)              # his hips, sitting on an upturned crate


def hut():
    """A stair hut: dark walls rim-lit by the moon on the right and the city on the left."""
    L = new_layer('hut')
    x0, y0, x1, y1 = HUT
    body = [C('#120d20'), C('#181128'), C('#1e1531'), C('#251a3d')]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            L.set(x, y, ramp_at(body, 2.2 - (y - y0) / 14.0, x, y, .8))
    for x in range(x0 - 1, x1 + 2):                      # the roof lip
        L.set(x, y0 - 1, C('#8472b3'))
        L.set(x, y0, C('#4a3a74'))
        L.set(x, y0 + 1, C('#0b0716'))
    for y in range(y0 - 1, y1 + 1):                      # rim light: moon on the right, the city on the left
        L.set(x1, y, C('#6e86c0'))
        L.set(x1 - 1, y, mix(L.get(x1 - 1, y) or INK, C('#6e86c0'), .3))
        L.set(x0, y, mix(L.get(x0, y) or INK, C('#ff7ac8'), .5))
    for k in range(3):                                   # panel seams
        for x in range(x0 + 1, x1):
            L.set(x, y0 + 7 + k * 8, C('#0b0716'))
    # the steel door with a wired-glass slit
    dx0, dy0, dx1 = DOOR
    rect(L, dx0 - 1, dy0 - 1, dx1 - dx0 + 3, y1 - dy0 + 2, C('#403164'))
    rect(L, dx0, dy0, dx1 - dx0 + 1, y1 - dy0 + 1, C('#0e0919'))
    rect(L, dx0 + 2, dy0 + 2, 5, 4, C('#06141e'))
    for yy in range(dy0 + 2, dy0 + 6):
        L.set(dx0 + 4, yy, C('#143246'))
    L.set(dx1 - 1, dy0 + 10, C('#8f7cbc'))               # the handle
    # a caged lamp over the door
    lx, ly = LAMP
    for (x, y) in blob_pts(lx, ly, 2.4, 1.6):
        L.set(x, y, C('#ffe2a8'), True)
    for x in range(lx - 3, lx + 4):
        L.set(x, ly - 2, C('#0b0716'))
    # a vent and a pipe up the side
    rect(L, x0 + 3, y0 + 5, 5, 3, C('#2a1d48'))
    for x in (x0 + 3, x0 + 5, x0 + 7):
        L.set(x, y0 + 6, C('#0b0716'))
    for y in range(y0 - 6, y0):
        L.set(x1 - 5, y, C('#2a1d48'))
        L.set(x1 - 4, y, C('#120c22'))
    rect(L, x1 - 6, y0 - 7, 4, 2, C('#4a3a74'))
    return L


def mast(L, bx, by):
    """The home mast: a pole through the hut's roof with a pale box, an LED and
    a LoRa whip. Mains power, so no panel. Returns the points to hook onto."""
    for y in range(by - 12, by + 1):
        L.set(bx - 1, y, METAL[3])
        L.set(bx, y, METAL[1])
    rect(L, bx - 3, by - 1, 6, 2, METAL[0])
    rect(L, bx + 1, by - 11, 6, 6, PALE[2])               # the Heltec's box
    rect(L, bx + 1, by - 11, 6, 1, PALE[3])
    for y in range(by - 11, by - 5):
        L.set(bx + 6, y, PALE[0])
    rect(L, bx + 1, by - 6, 6, 1, PALE[0])
    led = [(bx + 2, by - 8), (bx + 3, by - 8)]
    for (x, y) in led:
        L.set(x, y, LED_ON, True)
    rect(L, bx - 2, by - 14, 4, 2, METAL[2])              # collar
    top = by - 14 - 16
    for y in range(top, by - 14):
        L.set(bx - 1, y, WHIP)
        L.set(bx, y, METAL[2])
    L.set(bx - 1, top - 1, WHIP_TIP)
    L.set(bx, top - 1, WHIP)
    for y in range(by - 9, by - 5):                       # a short 2.4 GHz stub on the box
        L.set(bx + 8, y, WHIP)
    L.set(bx + 7, by - 8, METAL[1])
    return dict(tip=(bx - 1, top - 1), link=(bx - 1, top + 3), led=led)


WHIP = C('#c9c7e6')
WHIP_TIP = C('#ffffff')
LED_ON = C('#7dffa8')


def figure(L, hx, hy, rim=None):
    """A hooded figure sitting on a crate, side-on, facing right: hips at (hx, hy).
    A black silhouette with the screen's light on its front and the city's on its back."""
    body = C('#08060e')
    pix = set()
    for (a, b, r) in (((0, 0), (1.4, -6.2), 2.5),         # torso, leaning toward the laptop
                      ((0, 0.4), (6.6, 0.8), 1.7),        # thigh
                      ((6.6, 0.8), (7.4, 6.6), 1.4),      # shin
                      ((1.6, -6), (4.8, -2.4), 1.2),      # upper arm
                      ((4.8, -2.4), (9.4, -3.2), 1.0)):   # forearm to the keys
        pix |= thick_pts(hx + a[0], hy + a[1], hx + b[0], hy + b[1], r)
    pix |= blob_pts(hx + 2.4, hy - 9.6, 3.1, 3.3)         # the hood
    pix |= poly_pts([(hx - 1.5, hy - 12), (hx - 4.2, hy - 7.2), (hx + 0.5, hy - 7.5)])    # its back, hanging
    for (x, y) in pix:
        L.set(x, y, body)
    # the face is a pocket of darkness in the hood; screen light on the front edge, city light on the back
    for (x, y) in pix:
        if (x + 1, y) not in pix:
            L.set(x, y, mix(body, C('#5ff3ff'), .55))
        elif (x - 1, y) not in pix or (x, y - 1) not in pix:
            L.set(x, y, mix(body, C('#ff7ac8'), .4))
    return pix


def laptop(L, cx, cy):
    """A laptop on a crate, its back to us, the screen's light spilling to the left.
    (cx, cy) is the front-left foot of the crate."""
    rect(L, cx, cy - 6, 12, 6, C('#1b1230'))                 # the crate
    rect(L, cx, cy - 6, 12, 1, C('#4a3a74'))
    for y in range(cy - 6, cy):
        L.set(cx + 11, y, C('#0b0716'))
    rect(L, cx + 1, cy - 4, 10, 1, C('#0b0716'))
    rect(L, cx + 1, cy - 8, 10, 2, C('#2a2a3c'))             # the base
    rect(L, cx + 1, cy - 8, 10, 1, C('#4a4a64'))
    for k in range(9):                                       # the lid, leaning back, seen from behind
        rect(L, cx + 3 + k // 3, cy - 9 - k, 3, 1, C('#1a1a28'))
    for k in range(9):
        L.set(cx + 3 + k // 3, cy - 9 - k, C('#5ff3ff'), True)   # the screen's edge, lit
    L.set(cx + 7, cy - 13, C('#6a6a8a'))                     # a sticker
    return dict(screen=(cx + 3, cy - 17, 3, 9))


def usb_cable(L):
    """The USB cable from the home station inside the hut to the laptop, sagging across the roof."""
    x0, y0 = HUT[0] - 1, 127
    cx, cy = LAPTOP_AT[0] + 12, LAPTOP_AT[1] - 2
    pts = [(x0, y0), ((x0 + cx) // 2 + 2, 130), (cx, cy)]
    for a, b in zip(pts, pts[1:]):
        for (x, y) in line_pts(a[0], a[1], b[0], b[1]):
            L.set(x, y, C('#0a0716'))
            L.set(x, y - 1, mix(L.get(x, y - 1) or C('#1a1230'), C('#4a3a74'), .35))
