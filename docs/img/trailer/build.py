"""Draws the whole trailer, shot by shot, back to front.

    city      the title card over the rooftop mesh, the first detection, the 24-hour time-lapse
    cutaway   inside a field station: one broadcast in, one LoRa packet out
    relay     the mesh seen from above, and the home station's dedup
    map       the mapper in the browser
    frame     letterbox bars, captions, cuts, scanlines

Each shot is a group in the SVG that is on screen only during its part of the loop
(see timeline.py); the picture without animation is the opening title card.
"""
import argparse
import os

from .pixart import *
from .fonts import text3, text3_width
from .palette import *
from . import timeline as TL
from . import stage, beat, title, hud, cutaway, mapbase, relay, mapui, lapse

TITLE_TEXT = 'Countersurveillance, 24/7: a mesh of interconnected detectors watching the sky, around the clock'
DESC = ('Pixel-art trailer. Over a night city, solar-powered detector stations on the rooftops are joined by a '
        'glowing mesh, under the words countersurveillance, 24/7. A drone arrives and the rings of its '
        'broadcast reach the stations that can hear it. One station is opened up: its XIAO ESP32-S3 decodes '
        'the broadcast into one line of JSON and its Heltec V4 puts it on the LoRa mesh. The packets hop to '
        'the home station, which keeps the first copy and drops the rest, and the mapper shows the drone, its '
        'pilot and its path on an offline map. Then a day goes by in a few seconds while the stations keep '
        'watching.')


def build():
    """Lay down every layer, in drawing order."""
    with shot('city', TL.CITY):
        world = stage.build()
        anc = stage.overlay(world)
        stage.glows(world, anc)
        beat.ambient(world, anc)
        beat.boot(world, anc)
        beat.drone_beat(world, anc)
        lapse.hud_lapse()
        title.build()
        lapse.recolor_sky()
        lapse.fades()
    with shot('cutaway', TL.CUTAWAY):
        cutaway.build()
    with shot('mapbase', TL.MAPBASE):
        mapbase.base()
    with shot('relay', TL.RELAY):
        relay.build()
    with shot('map', TL.MAP):
        mapui.build()
    # the film frame: screen effects over the picture, then the bars with their captions
    hud.vignette()
    hud.scanlines(.08)
    for t, seed in TL.CUTS:
        hud.glitch(t, seed)
    hud.bars()
    hud.progress([c[0] for c in TL.CUTS[1:5]] + [TL.CUTS[0][0], TL.CUTS[5][0]])
    B = new_layer('bar-text')
    hud.mark(B, 5, 1)
    text3(B, 14, 2, 'DRONE MESH MAPPER', C('#c9c7e6'))
    text3(B, W - 5 - text3_width('LEVEL 2'), 2, 'LEVEL 2', C('#5ff3ff'))
    live_c, live_s = pulse(.62, 1.6, 0.0)
    live = new_layer('live', anim=live_c, style=live_s)
    rect(live, W - 5 - text3_width('LEVEL 2') - 8, 3, 3, 3, LIME, True)
    bloom('live', {(W - 5 - text3_width('LEVEL 2') - 7, 4)}, LIME, ((2, .4), (3.5, .15)), anim=live_c, style=live_s)
    for (word, accent, detail, t0, t1) in TL.CAPTIONS:
        if word is None:
            with group(vis_class([(t0, t1)]), None, 'tagline-%g' % t0):
                text3(new_layer('tagline'), 6, PIC_Y1 + 5, detail, C('#8c8bb0'))
        else:
            hud.caption(word, accent, detail, t0, t1)
    hud.frame()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description='Draw the level 2 README trailer.')
    ap.add_argument('-o', '--out', default=os.path.normpath(os.path.join(here, '..', 'trailer.svg')),
                    help='SVG to write (default: next to the trailer folder)')
    ap.add_argument('--variant', choices=('animated', 'static', 'overlays'), default='animated',
                    help='static: no animation, for pixel-exact checks; overlays: show every hidden overlay')
    ap.add_argument('--png', help='also write a PNG of the still frame')
    ap.add_argument('--scale', type=int, default=4, help='PNG pixels per art pixel')
    ap.add_argument('--crop', help='PNG crop as x,y,w,h in art pixels')
    args = ap.parse_args()
    build()
    if args.png:
        crop = tuple(int(v) for v in args.crop.split(',')) if args.crop else None
        write_png(args.png, flatten(LAYERS), args.scale, crop, bg=(0, 0, 0))
    cull_hidden(LAYERS)
    print('%s: %d bytes' % (args.out, write_svg(args.out, TITLE_TEXT, DESC, args.variant)))


if __name__ == '__main__':
    main()
