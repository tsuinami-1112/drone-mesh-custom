"""The mesh itself: where the stations stand, the links between them, the
little tags that float over them."""
from .pixart import *
from .fonts import text3, text3_width
from .palette import *


def node_tag(L, x, y, text, color=MESH, plate=C('#06110c'), border=MESH_DIM):
    """A name plate over a node: a dark plate, a thin border, 3x5 letters, a
    1-pixel leader down to the antenna. (x, y) is where the leader ends."""
    w = text3_width(text) + 4
    x0, y0 = x - w // 2, y - 6 - 5
    rect(L, x0, y0, w, 7, plate)
    for i in range(w):
        L.set(x0 + i, y0, border)
        L.set(x0 + i, y0 + 6, border)
    for j in range(7):
        L.set(x0, y0 + j, border)
        L.set(x0 + w - 1, y0 + j, border)
    text3(L, x0 + 2, y0 + 1, text, color)
    for yy in range(y0 + 7, y):
        L.set(x, yy, border)
    return (x0, y0, w, 7)



def node_tag_left(L, x, y, text, color=MESH, plate=C('#06110c'), border=MESH_DIM):
    """The same plate, to the left of a node and level with it, joined by a short leader."""
    w = text3_width(text) + 4
    x1 = x - 5
    x0, y0 = x1 - w, y - 3
    rect(L, x0, y0, w, 7, plate)
    for i in range(w):
        L.set(x0 + i, y0, border)
        L.set(x0 + i, y0 + 6, border)
    for j in range(7):
        L.set(x0, y0 + j, border)
        L.set(x0 + w - 1, y0 + j, border)
    text3(L, x0 + 2, y0 + 1, text, color)
    for xx in range(x1, x - 2):
        L.set(xx, y, border)
    return (x0, y0, w, 7)
