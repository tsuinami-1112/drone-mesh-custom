"""The big numerals: 24/7 drawn as a network. Every stroke is a link and the joints and
ends are nodes, so the number is itself a little mesh."""
from .pixart import *

# strokes: polylines on a 9 x 13 glyph box; nodes: where the dots sit
GLYPHS = {
    '2': dict(strokes=[[(0, 2), (2, 0), (6, 0), (8, 2), (8, 5), (0, 12), (8, 12)]],
              nodes=[(0, 2), (8, 4), (0, 12), (8, 12)]),
    '4': dict(strokes=[[(6, 12), (6, 0), (0, 8), (8, 8)]],
              nodes=[(6, 12), (6, 0), (0, 8), (8, 8)]),
    '7': dict(strokes=[[(0, 0), (8, 0), (3, 12)]],
              nodes=[(0, 0), (8, 0), (3, 12)]),
    '/': dict(strokes=[[(0, 12), (8, 0)]],
              nodes=[(0, 12), (8, 0)]),
}


def glyph_pixels(ch, x, y):
    """(stroke pixels, node pixels) of one glyph whose box starts at (x, y), drawn at twice the
    box size: two-pixel strokes, four-pixel nodes."""
    g = GLYPHS[ch]
    lines, dots = set(), set()
    for poly in g['strokes']:
        for (a, b) in zip(poly, poly[1:]):
            lines |= thick_pts(x + a[0] * 2 + 1, y + a[1] * 2 + 1, x + b[0] * 2 + 1, y + b[1] * 2 + 1, .9)
    for (nx, ny) in g['nodes']:
        for dy in range(4):
            for dx in range(4):
                dots.add((x + nx * 2 + dx - 1, y + ny * 2 + dy - 1))
    return lines, dots
