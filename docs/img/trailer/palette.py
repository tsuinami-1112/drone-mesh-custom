"""Colours shared by every shot. Neon on a violet night; each hue means something:
green is our mesh, red is the drone, cyan is radio, lime is the map, amber is a guess."""
from .pixart import C

# the night sky, zenith to horizon glow
SKY = [C(h) for h in ('#05031a', '#0a0724', '#100b33', '#190f46', '#251459', '#36186b',
                      '#4d1a79', '#6c1f83', '#912787', '#b73585', '#dc4b83', '#f4687e')]
INK = C('#0a0620')
BLACK = C('#05030c')                     # the letterbox bars

PINK, PINK_D = C('#ff4fd8'), C('#a81f8c')
CYAN, CYAN_D = C('#5ff3ff'), C('#1c97b4')
RED, RED_D = C('#ff3d6e'), C('#8a1440')
GOLD, GOLD_D = C('#ffd23a'), C('#9a7a14')
BLUE, BLUE_D = C('#2f6bff'), C('#14307c')
AMBER, AMBER_D = C('#ffaa44'), C('#a8651a')
LIME, LIME_D = C('#88ff99'), C('#2f9a46')

MESH, MESH_HOT, MESH_DIM = C('#67ea94'), C('#d4ffe4'), C('#1f7a45')   # the Meshtastic green
RF, RF_HOT, RF_DIM = C('#4fe3ff'), C('#d2f9ff'), C('#17708a')           # a radio wave

WARM = [C('#ffd37a'), C('#ffa94d'), C('#fff0b8')]
COOL = [C('#6ef3ff'), C('#3fb6ff'), C('#a6e2ff')]
HOT = [C('#ff6ad5'), C('#ff3d9a')]
WIN_MIXES = [WARM, WARM, COOL, COOL, WARM + COOL, WARM + HOT, COOL + HOT]

METAL = [C('#2b2a44'), C('#41405f'), C('#5d5c82'), C('#8c8bb0'), C('#c5c4e0')]      # galvanised steel, dark to light
PALE = [C('#8a88ae'), C('#b4b2d2'), C('#d8d7ec'), C('#f0f0fb')]                     # the station's pale enclosure
SOLAR = [C('#0d1a4a'), C('#16307c'), C('#2a56c8'), C('#6fa0ff')]                    # panel cells
