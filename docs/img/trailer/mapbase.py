"""A night map of the city seen from above: blocks of buildings, avenues strung
with lamps, a diagonal boulevard, a river, a park, a hill. It sits under the
mesh in the relay shot and under the mapper's panels in the map shot."""
import math

from .pixart import *
from .palette import *

STREET = C('#06041a')
BLOCKS = [C('#0f0c2e'), C('#120f38'), C('#0d0a28'), C('#15113f')]
AVENUE, AVENUE_LIT = C('#0d1038'), C('#1c3470')
LAMP_DIM, LAMP_HOT = C('#6a5a3a'), C('#ffd37a')
RIVER, RIVER_HI = C('#0a1a46'), C('#16347f')
PARK, PARK_HI, PARK_LO = C('#0a2a26'), C('#12483e'), C('#071d1c')
HILL_AT = (60, 24)
CORE = (112, 66)            # the busy middle of town


def river_y(x):
    return 112 + 7 * math.sin(x / 33.0 + .6) + 2.5 * math.sin(x / 11.0)


def lift(c, x, y, k=1.0):
    """Blocks near the middle of town glow a little warmer and brighter."""
    d = math.hypot((x - CORE[0]) / 90.0, (y - CORE[1]) / 55.0)
    f = max(0.0, 1.0 - d) ** 1.5 * .5 * k
    return mix(c, C('#4a2f86'), f)


def base():
    L = new_layer('map-base')
    rng = Rng(2024)
    rect(L, 0, PIC_Y0, W, PIC_Y1 - PIC_Y0, STREET)
    xs, x = [], -4
    while x < W + 8:
        xs.append(x)
        x += rng.randint(13, 21)
    ys, y = [], PIC_Y0 - 5
    while y < PIC_Y1 + 8:
        ys.append(y)
        y += rng.randint(11, 16)
    park = (152, 38, 192, 64)
    boulevard = ((-6, 30), (262, 96))

    def in_river(px, py):
        return abs(py - river_y(px)) < 6.5

    def near_boulevard(px, py, w):
        return seg_dist(px + .5, py + .5, boulevard[0][0], boulevard[0][1], boulevard[1][0], boulevard[1][1]) < w

    # blocks, each cut into a few buildings
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            bx0, bx1 = xs[i] + (3 if i % 3 == 0 else 2), xs[i + 1] - (2 if (i + 1) % 3 == 0 else 1)
            by0, by1 = ys[j] + (3 if j % 3 == 0 else 2), ys[j + 1] - (2 if (j + 1) % 3 == 0 else 1)
            if bx1 - bx0 < 4 or by1 - by0 < 4:
                continue
            is_park = park[0] <= bx0 <= park[2] and park[1] <= by0 <= park[3]
            if is_park:
                for yy in range(by0, by1):
                    for xx in range(bx0, bx1):
                        c = PARK
                        r = rng.random()
                        if r < .22:
                            c = PARK_HI
                        elif r < .34:
                            c = PARK_LO
                        L.set(xx, yy, c)
                continue
            # cut the block into buildings
            parts = [(bx0, by0, bx1, by1)]
            for _ in range(rng.randint(1, 3)):
                k = rng.randint(0, len(parts) - 1)
                px0, py0, px1, py1 = parts.pop(k)
                if px1 - px0 >= py1 - py0 and px1 - px0 >= 8:
                    cut = rng.randint(px0 + 4, px1 - 4)
                    parts += [(px0, py0, cut, py1), (cut + 1, py0, px1, py1)]
                elif py1 - py0 >= 8:
                    cut = rng.randint(py0 + 4, py1 - 4)
                    parts += [(px0, py0, px1, cut), (px0, cut + 1, px1, py1)]
                else:
                    parts.append((px0, py0, px1, py1))
            for (px0, py0, px1, py1) in parts:
                col = rng.choice(BLOCKS)
                for yy in range(max(py0, PIC_Y0), min(py1, PIC_Y1)):
                    for xx in range(max(px0, 0), min(px1, W)):
                        if in_river(xx, yy):
                            continue
                        c = lift(col, xx, yy)
                        if yy == py0 or xx == px0:
                            c = mix(c, C('#3a2f80'), .35)           # a roof edge catching light
                        L.set(xx, yy, c)
    # avenues: wider, a lit centre line with warm lamps
    for i, x in enumerate(xs):
        for yy in range(PIC_Y0, PIC_Y1):
            if in_river(x, yy):
                continue
            if i % 3 == 0:
                for dx in (0, 1, 2):
                    L.set(x + dx, yy, AVENUE)
                L.set(x + 1, yy, LAMP_HOT if yy % 6 == 0 else AVENUE_LIT)
            elif yy % 5 == 0:
                L.set(x, yy, LAMP_DIM)
    for j, y in enumerate(ys):
        for xx in range(W):
            if in_river(xx, y):
                continue
            if j % 3 == 0 and PIC_Y0 <= y + 1 < PIC_Y1:
                for dy in (0, 1, 2):
                    if PIC_Y0 <= y + dy < PIC_Y1:
                        L.set(xx, y + dy, AVENUE)
                L.set(xx, y + 1, LAMP_HOT if xx % 6 == 0 else AVENUE_LIT)
            elif xx % 5 == 0 and PIC_Y0 <= y < PIC_Y1:
                L.set(xx, y, LAMP_DIM)
    # the diagonal boulevard, with lamps, and two roundabouts
    for (px, py) in line_pts(boulevard[0][0], boulevard[0][1], boulevard[1][0], boulevard[1][1]):
        for (dx, dy) in ((0, -1), (0, 0), (0, 1)):
            if PIC_Y0 <= py + dy < PIC_Y1 and not in_river(px, py + dy):
                L.set(px + dx, py + dy, AVENUE if dy else (LAMP_HOT if px % 6 == 0 else AVENUE_LIT))
    for (cx, cy) in ((60, 48), (172, 80)):
        for (x, y) in blob_pts(cx, cy, 5, 5):
            L.set(x, y, AVENUE)
        for (x, y) in blob_pts(cx, cy, 2.5, 2.5):
            L.set(x, y, PARK_HI)
        for (x, y) in blob_pts(cx, cy, 5, 5) - blob_pts(cx, cy, 4, 4):
            L.set(x, y, LAMP_HOT if (x + y) % 3 == 0 else AVENUE_LIT)
    # the river: banks strung with lamps, bridges, a sheen
    for xx in range(W):
        cy = river_y(xx)
        for yy in range(int(cy - 8), int(cy + 9)):
            if not (PIC_Y0 <= yy < PIC_Y1):
                continue
            d = abs(yy - cy)
            if d < 5.5:
                L.set(xx, yy, RIVER_HI if (d < 1.6 and (xx + yy) % 3 == 0) else RIVER)
            elif d < 6.5:
                L.set(xx, yy, C('#1c2f78'))
            elif d < 7.5 and xx % 4 == 0:
                L.set(xx, yy, LAMP_DIM)
    for bx in (38, 112, 176, 232):
        cy = river_y(bx)
        for yy in range(int(cy - 7), int(cy + 8)):
            if PIC_Y0 <= yy < PIC_Y1:
                for dx in (0, 1, 2):
                    L.set(bx + dx, yy, AVENUE_LIT if dx == 1 else AVENUE)
                if (yy % 3) == 0:
                    L.set(bx + 1, yy, LAMP_HOT)
    # a hill with contour lines: the router stands on top of it
    hx, hy = HILL_AT
    for k, (rx, ry) in enumerate(((22, 14), (17, 11), (12, 8), (7, 5))):
        for (x, y) in blob_pts(hx, hy, rx, ry) - blob_pts(hx, hy, rx - 1.2, ry - 1.2):
            if PIC_Y0 <= y < PIC_Y1 and (x + y) % 2 == 0:
                L.set(x, y, C('#1c4a52') if k % 2 == 0 else C('#2a6a6a'))
    return L


def glows():
    """Warm light spilling off the avenues, and a vignette."""
    out = []
    return out
