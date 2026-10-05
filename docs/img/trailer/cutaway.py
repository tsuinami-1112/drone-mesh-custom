"""Inside a field station: a drone's broadcast arrives at the 2.4 GHz antenna,
the XIAO decodes it into one line of JSON, sends it down four wires to the
Heltec, and the Heltec puts it on the LoRa mesh."""
from .pixart import *
from .fonts import text3, text3_width, text5
from .palette import *
from . import fx
from . import timeline as TL

T0 = TL.CUTAWAY[0][0]

BOX = (40, 22, 196, 70)             # the pale enclosure: x0, y0, x1, y1
ANT24_AT = (18, 46)                 # the base of the 2.4 GHz whip
LNA_AT = (47, 39)                   # 24 x 14
XIAO_AT = (82, 32)                  # 38 x 26
HELTEC_AT = (146, 30)               # 46 x 30
LORA_AT = (224, 46)                 # the base of the LoRa whip
TERM = (8, 88, 248, 130)            # the console
TEXT0 = (14, 98)                    # top-left of its first line of text

JSON = ('{"mac":"aa:bb:cc:dd:ee:ff","rssi":-62,"node_id":"A1B2","drone_lat":52.520008,'
        '"drone_long":13.404954,"drone_altitude":120,"pilot_lat":52.518,"pilot_long":13.4,'
        '"basic_id":"1581F5FHB229F00202DR","id_type":1,"src":"odid_bcn"}')
COLS = 58

BG0, BG1 = C('#0a0724'), C('#0e0a30')
GRID, GRID_DOT = C('#15133f'), C('#27226a')
WIRE = {'tx': C('#ffd23a'), 'rx': C('#6ae6ff'), 'gnd': C('#8c8bb0'), 'v3': C('#ff5a6a')}
PCB_X, PCB_X_EDGE = C('#12122a'), C('#2a8a8a')
PCB_H, PCB_H_EDGE = C('#150c34'), C('#6a4cff')
GOLD_P = C('#e8c25a')
SHIELD, SHIELD_HI = C('#9a98c0'), C('#d4d3ec')


# ----------------------------------------------------------------------------
# backdrop and the enclosure
# ----------------------------------------------------------------------------
def background():
    L = new_layer('cut-bg')
    for y in range(PIC_Y0, PIC_Y1):
        t = (y - PIC_Y0) / float(PIC_Y1 - PIC_Y0)
        for x in range(W):
            L.set(x, y, ramp_at([BG0, BG1], t * 1.0, x, y, .9))
    G = new_layer('cut-grid')
    for y in range(PIC_Y0 + 3, PIC_Y1, 16):
        for x in range(W):
            if x % 2 == 0:
                G.set(x, y, GRID)
    for x in range(8, W, 16):
        for y in range(PIC_Y0, PIC_Y1):
            if y % 2 == 0:
                G.set(x, y, GRID)
    for y in range(PIC_Y0 + 3, PIC_Y1, 16):
        for x in range(8, W, 16):
            G.set(x, y, GRID_DOT)


def enclosure():
    """The pale IP65 box, drawn as a frame with corner brackets, glands where
    the antenna cables go through, and a membrane vent."""
    L = new_layer('cut-box')
    x0, y0, x1, y1 = BOX
    edge, lit = C('#6f6d9a'), C('#c5c4e0')
    for x in range(x0, x1 + 1):
        L.set(x, y0, edge)
        L.set(x, y1, edge)
    for y in range(y0, y1 + 1):
        L.set(x0, y, edge)
        L.set(x1, y, edge)
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        for i in range(6):                                  # bright corner brackets
            L.set(cx + sx * i, cy, lit)
            L.set(cx, cy + sy * i, lit)
    rect(L, x0 + 62, y0 - 2, 12, 3, C('#2a2858'))           # the membrane vent on top
    for i in range(3):
        L.set(x0 + 64 + i * 3, y0 - 1, lit)
    for (gx, gy) in ((x0, 45), (x1, 45)):                   # cable glands where the coax goes through
        rect(L, gx - 2, gy - 3, 5, 7, C('#2e2c5c'))
        rect(L, gx - 1, gy - 2, 3, 5, lit)
        rect(L, gx, gy - 1, 1, 3, C('#0a0724'))
    return L


# ----------------------------------------------------------------------------
# the parts
# ----------------------------------------------------------------------------
def whip(L, bx, by, height, name):
    """An antenna: a connector block, a whip, a bright tip."""
    rect(L, bx - 3, by, 7, 4, METAL[2])
    rect(L, bx - 3, by, 7, 1, METAL[4])
    rect(L, bx - 1, by + 4, 3, 2, METAL[1])
    for y in range(by - height, by):
        L.set(bx, y, WHIP_C)
        L.set(bx - 1, y, mix(WHIP_C, BG0, .55))
    rect(L, bx - 1, by - height - 2, 3, 2, C('#ffffff'))
    return (bx, by - height - 2)


WHIP_C = C('#c9c7e6')


def antennas():
    L = new_layer('cut-antennas')
    tip24 = whip(L, ANT24_AT[0], ANT24_AT[1], 18, '2.4')
    tip_lora = whip(L, LORA_AT[0], LORA_AT[1], 20, 'lora')
    text3(L, ANT24_AT[0] - 11, ANT24_AT[1] + 9, '2.4 GHZ', C('#9fe9f5'))
    text3(L, LORA_AT[0] - 12, LORA_AT[1] + 9, 'LORA', C('#9aa0ff'))
    return tip24, tip_lora


def lna():
    x, y = LNA_AT
    L = new_layer('cut-lna')
    rect(L, x, y, 24, 14, C('#0b3a3a'))
    for i in range(24):
        L.set(x + i, y, C('#1f8f8f'))
        L.set(x + i, y + 13, C('#0a2a2a'))
    for j in range(14):
        L.set(x, y + j, C('#1f8f8f'))
        L.set(x + 23, y + j, C('#0a2a2a'))
    rect(L, x + 6, y + 3, 12, 8, SHIELD)                     # the SAW filter and amplifier under a can
    rect(L, x + 6, y + 3, 12, 1, SHIELD_HI)
    text3(L, x + 7, y + 5, 'LNA', C('#1b1d3a'))
    rect(L, x - 3, y + 5, 4, 4, GOLD_P)                      # SMA connectors in and out
    rect(L, x + 23, y + 5, 4, 4, GOLD_P)
    L.set(x - 2, y + 6, C('#6a5a1a'))
    L.set(x + 24, y + 6, C('#6a5a1a'))
    return dict(in_=(x - 3, y + 7), out=(x + 27, y + 7))


def xiao():
    x, y = XIAO_AT
    L = new_layer('cut-xiao')
    rect(L, x, y, 38, 26, PCB_X)
    for i in range(38):
        L.set(x + i, y, PCB_X_EDGE)
        L.set(x + i, y + 25, PCB_X_EDGE)
    for j in range(26):
        L.set(x, y + j, PCB_X_EDGE)
        L.set(x + 37, y + j, C('#0c5a5a'))
    for i in range(2, 36, 3):                                # castellated pads along both long edges
        L.set(x + i, y + 1, GOLD_P)
        L.set(x + i, y + 24, GOLD_P)
    rect(L, x - 3, y + 9, 5, 9, SHIELD)                      # the USB-C port
    rect(L, x - 3, y + 9, 5, 1, SHIELD_HI)
    rect(L, x - 1, y + 11, 2, 5, C('#0a0724'))
    rect(L, x + 14, y + 6, 18, 14, SHIELD)                   # the ESP32-S3 module
    rect(L, x + 14, y + 6, 18, 1, SHIELD_HI)
    for i in range(18):
        L.set(x + 14 + i, y + 19, C('#6f6d9a'))
    text3(L, x + 17, y + 10, 'S3', C('#2b2a5a'))
    rect(L, x + 15, y + 15, 5, 3, C('#5a5890'))              # antenna keep-out, trace
    rect(L, x + 4, y + 10, 3, 3, C('#c5c4e0'))               # the two buttons
    rect(L, x + 4, y + 15, 3, 3, C('#c5c4e0'))
    rect(L, x + 2, y + 3, 4, 3, GOLD_P)                      # the U.FL socket for the antenna
    L.set(x + 3, y + 4, C('#6a5a1a'))
    led = [(x + 9, y + 21), (x + 10, y + 21)]
    for p in led:
        L.set(p[0], p[1], C('#5a3a10'))                      # the user LED, dark until a detection
    return dict(ufl=(x + 4, y + 4), led=led, box=(x, y, 38, 26), mod=(x + 14, y + 6, 18, 14),
                right=(x + 37, y))


def heltec():
    x, y = HELTEC_AT
    L = new_layer('cut-heltec')
    rect(L, x, y, 46, 30, PCB_H)
    for i in range(46):
        L.set(x + i, y, PCB_H_EDGE)
        L.set(x + i, y + 29, PCB_H_EDGE)
    for j in range(30):
        L.set(x, y + j, PCB_H_EDGE)
        L.set(x + 45, y + j, C('#3a2a90'))
    for i in range(2, 44, 3):
        L.set(x + i, y + 1, GOLD_P)
        L.set(x + i, y + 28, GOLD_P)
    rect(L, x + 3, y + 6, 24, 13, C('#2a2858'))              # the OLED's bezel and glass
    rect(L, x + 4, y + 7, 22, 11, C('#02040a'))
    rect(L, x + 30, y + 7, 12, 11, SHIELD)                   # the LoRa transceiver under its can
    rect(L, x + 30, y + 7, 12, 1, SHIELD_HI)
    text3(L, x + 31, y + 11, 'SX', C('#2b2a5a'))
    rect(L, x + 44, y + 12, 4, 4, GOLD_P)                    # the U.FL socket for the LoRa antenna
    L.set(x + 46, y + 13, C('#6a5a1a'))
    rect(L, x + 4, y + 21, 5, 3, C('#c5c4e0'))               # the PRG and RST buttons
    rect(L, x + 12, y + 21, 5, 3, C('#c5c4e0'))
    return dict(oled=(x + 4, y + 7, 22, 11), ufl=(x + 47, y + 14), left=(x, y), box=(x, y, 46, 30),
                shield=(x + 30, y + 7, 12, 11))


def wires(xi, he):
    """Four jumper wires between the two boards: TX, RX, GND and 3V3."""
    L = new_layer('cut-wires')
    x0, x1 = xi['right'][0] + 1, he['left'][0] - 1
    ys = {'tx': 38, 'rx': 43, 'gnd': 48, 'v3': 53}
    for k, y in ys.items():
        for x in range(x0, x1 + 1):
            L.set(x, y, WIRE[k])
        rect(L, x0 - 1, y - 1, 2, 3, GOLD_P)
        rect(L, x1, y - 1, 2, 3, GOLD_P)
    text3(L, x0 + 2, 30, 'UART', C('#ffd23a'))
    text3(L, x0 - 2, 55, '115200', C('#8c8bb0'))
    return ys


def coax(ant, lna_p, xi, he, lora_tip_base):
    """The two coax runs on the way in (antenna -> LNA -> XIAO) and the one on
    the way out (Heltec -> LoRa antenna). Returns each as a list of points."""
    L = new_layer('cut-coax')
    cb = C('#7c7aa8')
    ant_in = [(ANT24_AT[0] + 1, ANT24_AT[1] + 5), (ANT24_AT[0] + 1, 45), (lna_p['in_'][0], 45)]
    lna_out = [(lna_p['out'][0], 45), (77, 45), (77, xi['ufl'][1]), (xi['ufl'][0], xi['ufl'][1])]
    out = [(he['ufl'][0], 44), (LORA_AT[0] - 1, 44), (LORA_AT[0] - 1, LORA_AT[1] + 4)]
    for path in (ant_in, lna_out, out):
        for a, b in zip(path, path[1:]):
            for (x, y) in line_pts(a[0], a[1], b[0], b[1]):
                L.set(x, y, cb)
    return dict(ant_in=ant_in, lna_out=lna_out, out=out)


# ----------------------------------------------------------------------------
# labels, the power pill, the console
# ----------------------------------------------------------------------------
def labels(xi, he, lna_p):
    L = new_layer('cut-labels')
    y = BOX[3] - 7
    text3(L, LNA_AT[0] - 3, y, 'LNA 20DB', C('#7fe3ff'))
    text3(L, XIAO_AT[0] + 1, y, 'XIAO ESP32-S3', C('#7fe3ff'))
    text3(L, HELTEC_AT[0] + 1, y, 'HELTEC V4', C('#9aa0ff'))
    text3(L, XIAO_AT[0] + 1, XIAO_AT[1] - 6, 'DETECTOR', C('#4fe3ff'))
    text3(L, HELTEC_AT[0] + 1, HELTEC_AT[1] - 6, 'MESHTASTIC', C('#9aa0ff'))
    text5(L, 8, PIC_Y0 + 3, 'FIELD STATION', C('#ffffff'))
    text3(L, W - 8 - text3_width('NODE A1B2'), PIC_Y0 + 5, 'NODE A1B2', C('#9fe9f5'))
    return L


def sun(L, cx, cy):
    for (x, y) in blob_pts(cx, cy, 2.6, 2.6):
        L.set(x, y, C('#ffd23a'), True)
    for (dx, dy) in ((0, -4), (0, 4), (-4, 0), (4, 0), (-3, -3), (3, -3), (-3, 3), (3, 3)):
        L.set(cx + dx, cy + dy, C('#ffb347'), True)


def pill():
    L = new_layer('cut-pill')
    x0, y0, x1, y1 = 8, 74, 176, 84
    rect(L, x0, y0, x1 - x0, y1 - y0, C('#0b0a24'))
    for x in range(x0 + 2, x1 - 2):
        L.set(x, y0, C('#3a3870'))
        L.set(x, y1 - 1, C('#3a3870'))
    for y in range(y0 + 2, y1 - 2):
        L.set(x0, y, C('#3a3870'))
        L.set(x1 - 1, y, C('#3a3870'))
    for (x, y) in ((x0 + 1, y0 + 1), (x1 - 2, y0 + 1), (x0 + 1, y1 - 2), (x1 - 2, y1 - 2)):
        L.set(x, y, C('#3a3870'))
    sun(L, x0 + 7, y0 + 5)
    text3(L, x0 + 15, y0 + 3, 'SOLAR PANEL · MPPT · LIFEPO4 BATTERY', C('#c9c7e6'))
    text3(L, 188, 77, 'PASSIVE RX ONLY', C('#4fe3ff'))
    return L


def panel(L, box, edge, fill):
    x0, y0, x1, y1 = box
    rect(L, x0, y0, x1 - x0, y1 - y0, fill)
    for x in range(x0 + 1, x1 - 1):
        L.set(x, y0, edge)
        L.set(x, y1 - 1, edge)
    for y in range(y0 + 1, y1 - 1):
        L.set(x0, y, edge)
        L.set(x1 - 1, y, edge)


def tokens(s):
    """Split a JSON line into (text, colour) runs: keys, strings, numbers, punctuation."""
    out, i = [], 0
    key_c, str_c, num_c, pun_c = C('#7fe3ff'), C('#67ea94'), C('#ffb347'), C('#8c8bb0')
    while i < len(s):
        ch = s[i]
        if ch == '"':
            j = s.index('"', i + 1)
            word = s[i:j + 1]
            is_key = j + 1 < len(s) and s[j + 1] == ':'
            out.append((word, key_c if is_key else str_c))
            i = j + 1
        elif ch in '-0123456789.':
            j = i
            while j < len(s) and s[j] in '-0123456789.':
                j += 1
            out.append((s[i:j], num_c))
            i = j
        else:
            out.append((ch, pun_c))
            i += 1
    return out


def console():
    """The console: the line the XIAO writes. Returns the layers of each of its rows."""
    L = new_layer('cut-term')
    panel(L, TERM, C('#2f9a46'), C('#04030a'))
    x0, y0 = TERM[0], TERM[1]
    for x in range(x0 + 1, TERM[2] - 1):
        L.set(x, y0 + 8, C('#14401e'))
    text3(L, x0 + 4, y0 + 2, 'XIAO · USB SERIAL · 115200', C('#88ff99'))
    badge = '<= 230 B = ONE LORA PACKET'
    text3(L, TERM[2] - 4 - text3_width(badge), y0 + 2, badge, C('#ffb347'))
    rows = []
    chars = [(ch, c) for (tok, c) in tokens(JSON) for ch in tok]
    for r in range(0, len(chars), COLS):
        row = new_layer('cut-json-%d' % (r // COLS))
        cx, cy = TEXT0[0], TEXT0[1] + (r // COLS) * 6
        for (ch, c) in chars[r:r + COLS]:
            text3(row, cx, cy, ch, c)
            cx += 4
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------
# the shot
# ----------------------------------------------------------------------------
OLED_C = C('#9fd8ff')


def oled_screens(he):
    """The Heltec's OLED: idle, then a TX screen with a progress bar, then the next one."""
    x, y, w, h = he['oled']
    idle = new_layer('oled-idle')
    text3(idle, x + 3, y + 1, 'MESH', OLED_C)
    for i, hh in enumerate((2, 3, 4)):                          # signal bars
        rect(idle, x + 18 + i * 2, y + 6 - hh, 1, hh, OLED_C)
    text3(idle, x + 3, y + 6, 'READY', C('#4a6a8a'))
    out = []
    for n, spans in (('01', [(12.25, 14.9)]), ('02', [(14.9, 15.4)])):
        with group(vis_class(spans), None, 'oled-tx-' + n):
            L = new_layer('oled-tx-' + n)
            rect(L, x + 1, y + 1, w - 2, h - 2, C('#02040a'))
            text3(L, x + 3, y + 1, 'TX ' + n, OLED_C)
            for i in range(18):
                L.set(x + 3 + i, y + 7, OLED_C)
                L.set(x + 3 + i, y + 8, OLED_C)
    return idle


def glow_rect(name, x0, y0, x1, y1, color, bands=((1.5, .26), (3, .1))):
    """A soft glow along the outline of a rectangle."""
    edge = set()
    for x in range(x0, x1):
        edge |= {(x, y0), (x, y1 - 1)}
    for y in range(y0, y1):
        edge |= {(x0, y), (x1 - 1, y)}
    bloom(name, edge, color, bands)


def build(world=None):
    background()
    enclosure()
    tip24, tip_lora = antennas()
    lp = lna()
    xi = xiao()
    he = heltec()
    ys = wires(xi, he)
    cx = coax(None, lp, xi, he, None)
    labels(xi, he, lp)
    pill()
    rows = console()
    oled_screens(he)
    # light: the boards, the enclosure and the console glow a little in their own colours
    glow_rect('cut-box-glow', BOX[0], BOX[1], BOX[2] + 1, BOX[3] + 1, (150, 150, 220), ((1.5, .18), (3, .08)))
    bx, by, bw, bh = xi['box']
    glow_rect('cut-xiao-glow', bx, by, bx + bw, by + bh, (40, 200, 200))
    bx, by, bw, bh = he['box']
    glow_rect('cut-heltec-glow', bx, by, bx + bw, by + bh, (120, 90, 255))
    glow_rect('cut-term-glow', TERM[0], TERM[1], TERM[2], TERM[3], (60, 255, 120), ((1.5, .2), (3, .08)))
    bloom('cut-whips', {(ANT24_AT[0], y) for y in range(tip24[1], ANT24_AT[1])} |
          {(LORA_AT[0], y) for y in range(tip_lora[1], LORA_AT[1])}, (200, 200, 255), ((1.5, .2), (3, .08)))

    # --- the broadcast arrives: arcs close in on the 2.4 GHz whip, twice
    for k, t in enumerate((10.1, 13.6)):
        cls = vis_class([(t, t + .6)])
        seq = seq_frames(4, .6, phase=t, name='ra')
        with group(cls, None, 'rf-in-%d' % k):
            for f in range(4):
                L = new_layer('rf-in-%d-%d' % (k, f), anim=seq[f][0], style=seq[f][1])
                radii = [r - 5 * f for r in (24, 17, 10)]
                for p in fx.arcs(tip24[0], tip24[1] + 2, [r for r in radii if r > 2], 150, 260, dash=3):
                    L.set(p[0], p[1], RF, True)
    # --- the antenna flashes, the pulse runs down the coax into the LNA
    for k, t in enumerate((10.7, 14.2)):
        with group(vis_class([(t, t + .3)]), None, 'ant-hit-%d' % k):
            L = new_layer('ant-hit-%d' % k)
            for p in blob_pts(tip24[0] + .5, tip24[1] + 1, 2, 2):
                L.set(p[0], p[1], C('#ffffff'), True)
            bloom('ant-hit-%d' % k, blob_pts(tip24[0] + .5, tip24[1] + 1, 2, 2), RF, ((2, .5), (4, .28), (7, .12)))
        fx.packet('rf-a%d' % k, cx['ant_in'], t + .05, speed=95, color=RF_HOT, tail=RF, small=True)
        with group(vis_class([(t + .39, t + .68)]), None, 'lna-hit-%d' % k):
            L = new_layer('lna-hit-%d' % k, alpha=.55)
            rect(L, LNA_AT[0], LNA_AT[1], 24, 14, C('#5ff3ff'))
        fx.packet('rf-b%d' % k, cx['lna_out'], t + .45, speed=95, color=RF_HOT, tail=RF, small=True)
    # --- the XIAO decodes: its module glows, its LED blinks
    for k, (t, t_end) in enumerate(((11.35, 13.2), (14.75, 15.3))):
        with group(vis_class([(t, t_end)]), None, 'xiao-on-%d' % k):
            m = xi['mod']
            L = new_layer('xiao-glow-%d' % k, alpha=.5)
            rect(L, m[0], m[1], m[2], m[3], C('#5ff3ff'))
        with group(vis_class([(t, t + .45)]), None, 'xiao-led-%d' % k):
            L = new_layer('xiao-led-%d' % k)
            for p in xi['led']:
                L.set(p[0], p[1], C('#ffd23a'), True)
            bloom('xiao-led-%d' % k, xi['led'], (255, 190, 60), ((1.5, .5), (3, .26), (5, .1)))
    # --- the console: one row at a time
    CLIPS['term'] = (TEXT0[0], TEXT0[1] - 1, COLS * 4, 6 * 5 + 1)
    for r in range(len(rows)):
        t0 = 11.35 + r * .34
        cover = new_layer('cover-%d' % r, anim=tl([(0, dict(x=0)), (t0, dict(x=0)), (t0 + .34, dict(x=COLS * 4 + 2)),
                                                    (T_LOOP, dict(x=COLS * 4 + 2))], ease='steps(%d,end)' % COLS),
                          clip='term')
        rect(cover, TEXT0[0] - 1, TEXT0[1] + r * 6 - 1, COLS * 4 + 1, 6, C('#04030a'))
    # --- the UART: three bursts down the TX wire
    for k, t in enumerate((11.6, 11.8, 12.0)):
        route = [(he['left'][0] - 25, ys['tx']), (he['left'][0] - 1, ys['tx'])]
        fx.packet('uart%d' % k, route, t, speed=110, color=C('#fff2b0'), tail=C('#ffd23a'), small=True)
    # --- the Heltec: shield glow, then the pulse out to the LoRa antenna
    for k, t in enumerate((12.25, 14.95)):
        with group(vis_class([(t, t + .7)]), None, 'sx-on-%d' % k):
            sh = he['shield']
            L = new_layer('sx-glow-%d' % k, alpha=.5)
            rect(L, sh[0], sh[1], sh[2], sh[3], C('#67ea94'))
    fx.packet('lora-out', cx['out'], 12.3, speed=90, color=MESH_HOT, tail=MESH, small=True)
    # --- the LoRa mesh: arcs flow off the antenna
    t = 12.7
    cls = vis_class([(t, 15.4)])
    seq = seq_frames(6, 1.0, phase=t, name='rl')
    with group(cls, None, 'lora-arcs'):
        for f in range(6):
            L = new_layer('lora-arc-%d' % f, anim=seq[f][0], style=seq[f][1])
            for k in range(2):
                r = 5 + f * 5.2 + k * 31
                if r > 34:
                    continue
                for p in fx.arcs(LORA_AT[0], LORA_AT[1] - 26, [r], -70, 70, dash=3):
                    L.set(p[0], p[1], MESH, True)
        text3(new_layer('lora-mesh-label'), LORA_AT[0] - 13, 61, 'TO MESH >>', C('#67ea94'))
