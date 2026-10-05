"""The drone: a quadcopter seen from the front, rotors blurring, a camera ball
under its belly and a red and a green light on its arms."""
from .pixart import *
from .palette import *

BODY_C, BODY_L, ARM_C, GIMBAL_C = C('#1b1730'), C('#403870'), C('#2c2646'), C('#2e2850')
RIM = C('#9a78ff')
LENS = C('#9fe9f5')
BLUR = C('#b4b2d8')
RED_L, GREEN_L = C('#ff3d6e'), C('#37ff8a')
WIDTH, HEIGHT = 27, 14          # the sprite's box; (x, y) is its top-left corner
CENTER = (13, 6)                # the middle of the body, inside the box


def pieces(x, y):
    """The drone with its top-left at (x, y): a dict with the body (pixel ->
    colour), two looks of rotor blur (a, b), the pixels of the red and the
    green light, the strobe and the lens."""
    body = {}

    def put(px, py, c):
        body[(x + px, y + py)] = c

    for (a, b) in (((9, 7), (5, 5)), ((9, 8), (5, 6)), ((17, 7), (21, 5)), ((17, 8), (21, 6))):   # arms
        for (px, py) in line_pts(a[0], a[1], b[0], b[1]):
            put(px, py, ARM_C)
    for (mx, my) in ((3, 3), (21, 3)):                                                            # motors
        for dy in range(3):
            for dx in range(4):
                put(mx + dx, my + dy, BODY_L if dy == 0 else ARM_C)
    for py in range(5, 10):                                                                       # the body
        for px in range(9, 18):
            put(px, py, BODY_C)
    for px in range(10, 17):
        put(px, 4, BODY_C)
    for px in range(9, 18):
        put(px, 5, mix(BODY_C, RIM, .6))                                                          # the lit shoulder
    put(9, 6, mix(BODY_C, RIM, .35))
    put(17, 6, mix(BODY_C, RIM, .35))
    for px in range(11, 16):                                                                      # the dark glass of the nose
        put(px, 8, C('#0a2a38'))
    for (px, py) in (line_pts(10, 10, 8, 13) + line_pts(16, 10, 18, 13) + [(7, 13), (8, 13), (18, 13), (19, 13)]):
        put(px, py, ARM_C)                                                                        # landing legs
    for py in range(10, 14):                                                                      # the camera ball
        for px in range(11, 16):
            if not ((px in (11, 15)) and py in (10, 13)):
                put(px, py, GIMBAL_C)
    put(12, 11, BODY_L)
    put(13, 12, LENS)
    put(14, 12, LENS)
    a, b = set(), set()
    for (cx, cy) in ((4.5, 2.2), (22.5, 2.2)):                                                    # rotor blur: two looks
        for (px, py) in blob_pts(cx, cy, 4.7, 1.5):
            a.add((x + px, y + py))
            if (px + py) % 2 == 0:
                b.add((x + px, y + py))
    return dict(body=body, a=a, b=b, red=(x + 3, y + 4), green=(x + 24, y + 4), strobe=(x + 13, y + 4),
                lens=(x + 13, y + 12))
