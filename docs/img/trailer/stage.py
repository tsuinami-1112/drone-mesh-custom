"""The city stage: the world, the stations on its rooftops and the mesh drawn
over them. Returns the positions the other parts of the story hook onto."""
from .pixart import *
from .palette import *
from . import city, stations, mesh, home, lapse, signs
from . import timeline as TL

# node ids as the firmware makes them: the last two bytes of the chip's MAC
IDS = {'hero': 'A1B2', 'S5': 'B07A', 'M1': '7F3C', 'S3': '4C81', 'M2': '09DE', 'S4': '2E90', 'HOME': 'HOME'}
LINKS = [('hero', 'S5'), ('hero', 'M1'), ('S5', 'S3'), ('M1', 'S3'), ('M1', 'M2'), ('S3', 'S4'),
         ('M2', 'S4'), ('S4', 'HOME'), ('M2', 'HOME')]
HERO_AT, HERO_K = (44, 132), 1.4


def build():
    world = {'nodes': {}, 'links': LINKS}
    nodes = world['nodes']
    city.sky()
    city.stars()
    with group(lapse.moon_class(), None, 'moon'):
        disc = city.moon()
        city.moon_halo(disc)
    lapse.sun()
    city.far_towers()
    city.mid_towers()
    city.window_bloom('mid')
    signs.meshtastic_sign()
    L = new_layer('stations-mid')
    nodes['S5'] = stations.small(L, 66, 74)
    nodes['S3'] = stations.small(L, 134, 78)
    nodes['S4'] = stations.small(L, 200, 92)
    city.near_towers()
    city.window_bloom('near')
    signs.trident_sign('near')
    lapse.tint()
    L = new_layer('stations-near')
    nodes['M1'] = stations.medium(L, 96, 102)
    nodes['M2'] = stations.medium(L, 172, 104)
    city.foreground()
    L = new_layer('stations-front')
    nodes['hero'] = stations.hero(L, HERO_AT[0], HERO_AT[1], HERO_K)
    L = new_layer('home')
    home.hut()
    m = home.mast(layer('hut'), *home.MAST_FOOT)
    nodes['HOME'] = m
    crate = new_layer('crate')
    rect(crate, 163, 127, 10, 5, C('#1b1230'))
    rect(crate, 163, 127, 10, 1, C('#4a3a74'))
    rect(crate, 163, 131, 10, 1, C('#0b0716'))
    lap = new_layer('laptop')
    home.laptop(lap, *home.LAPTOP_AT)
    home.usb_cable(new_layer('usb-cable'))
    fig = new_layer('figure')
    home.figure(fig, *home.FIGURE_AT)
    world['disc'] = disc
    # at noon the sun flashes in the hero's solar panel
    gx, gy = HERO_AT[0] - 19, HERO_AT[1] - 33
    with group(vis_class([(TL.NOON - .12, TL.NOON + .2)]), None, 'glint'):
        G = new_layer('glint')
        for (dx, dy) in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
            G.set(gx + dx, gy + dy, C('#ffffff'), True)
        bloom('glint', {(gx, gy)}, (255, 250, 210), ((2.5, .5), (5, .25), (9, .1)))
    return world


def anchors(world):
    """Where the little diamond for each node floats: just above its antenna."""
    return {k: (v['tip'][0], v['tip'][1] - 6) for k, v in world['nodes'].items()}


TAGGED = ('hero', 'M1', 'S3', 'HOME')
MARK = ((0, -2), (-1, -1), (1, -1), (-2, 0), (2, 0), (-1, 1), (1, 1), (0, 2))


def marker_pixels(ax, ay):
    return {(ax + dx, ay + dy) for (dx, dy) in MARK} | {(ax, ay)}


def overlay(world):
    """Links, diamonds and name plates: the 'mesh' read at a glance. The links
    crawl, a dash at a time, so they look alive."""
    anc = anchors(world)
    seq = seq_frames(4, .5, name='lk')
    for f in range(4):
        L = new_layer('mesh-links-%d' % f, anim=seq[f][0], style=seq[f][1])
        for a, b in world['links']:
            for i, (x, y) in enumerate(line_pts(anc[a][0], anc[a][1], anc[b][0], anc[b][1])):
                if (i + f) % 4 < 2:
                    L.set(x, y, MESH, True)
    marks = new_layer('mesh-marks')
    for k, (ax, ay) in anc.items():
        for (x, y) in marker_pixels(ax, ay):
            marks.set(x, y, MESH, True)
        marks.set(ax, ay, MESH_HOT, True)
    tags = new_layer('mesh-tags', anim=vis_class([(0, lapse.T_A), (lapse.T_B + .05, T_LOOP)]))
    for k in TAGGED:
        ax, ay = anc[k]
        style = dict(color=C('#9fe9f5'), plate=C('#06101c'), border=C('#1c4a64'))
        if k == 'hero':
            mesh.node_tag_left(tags, ax, ay, IDS[k], **style)
        else:
            mesh.node_tag(tags, ax, ay - 4, IDS[k], **style)
    return anc


def glows(world, anc):
    """Light: the diamonds, the hut's lamp and the laptop's screen."""
    for k, (ax, ay) in anc.items():
        bloom('mk-' + k, marker_pixels(ax, ay), MESH, ((1.5, .3), (3, .15), (5, .06)))
    x, y = home.LAMP
    bloom('lamp', blob_pts(x, y, 2.4, 1.6), (255, 200, 120), ((1.5, .34), (2.5, .2), (4, .11), (7, .05)))
    cone = new_layer('lamp-cone', alpha=.1)
    for p in poly_pts([(x - 1.5, y + 2), (x + 1.5, y + 2), (x + 10, 131), (x - 10, 131)]):
        cone.set(p[0], p[1], C('#ffdc96'))
    cx, cy = home.LAPTOP_AT
    screen = {(cx + 3 + k // 3, cy - 9 - k) for k in range(9)}
    bloom('laptop', screen, (95, 243, 255), ((1.5, .3), (3, .18), (5.5, .1), (9, .05), (14, .025)))
    pool = new_layer('laptop-pool', alpha=.14)
    for p in blob_pts(cx - 4, 131, 16, 2.4):
        pool.set(p[0], p[1], C('#8af4ff'))
