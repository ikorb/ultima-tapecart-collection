#!/usr/bin/env python3
"""Ultima VI's view colours, measured in VICE (what maps/u6maps.py rests on).

    python -m ultima.maps.u6_colours_check

Journey Onward from a copy of the cart (the menu picking U6, MENU_AUTOKEY;
the page's J pokes at $C025, ultima/games/u6/build.py), a minute of play, then the
VIC registers, colour RAM, the screen matrix ($CC00) and the bitmap ($E000)
dumped and every 8 x 8 cell on screen matched against the Game disk's TILES:
for each match, whether the cell's screen byte is COLORS' byte for the tile,
and which colour RAM values there are.  Expected: most cells COLORS' byte,
colour RAM light grey ($F), $D021 black.
"""
import os
from ultima import paths
import sys
from collections import Counter, defaultdict

os.chdir(paths.ROOT)
from tools.vice import menu_check
from ultima.disks.d64 import D64
from tools.vice.vice_mon import Vice


def main():
    image = menu_check.with_autokey(6)
    v = Vice(image, update_tcrt=False, log="build/u6_colours_check.log")
    try:
        print("init:", v.run_to(0x1000, timeout=90), flush=True)
        v.cmd("bank ram", wait=0.2)
        v.poke(0xC025, bytes([0xF0, (0xC054 - 0xC027) & 0xFF]))     # Journey onward
        v.run(60.0)
        v.shot("build/u6_view.png")
        v.cmd("bank io", wait=0.2)
        io, col = v.mem(0xD000, 0xD02E), v.mem(0xD800, 0xDBE7)
        v.cmd("bank ram", wait=0.2)
        scr, bm = v.mem(0xCC00, 0xCFE7), v.mem(0xE000, 0xFF3F)
    finally:
        v.quit()
    print("d011 %02x d016 %02x d021 %02x" % (io[0x11], io[0x16], io[0x21]))
    game = D64(paths.disk("u6-3b"))
    tiles, colors = game.payload("TILES")[0], game.payload("COLORS")[0]
    cells = defaultdict(list)
    for t in range(512):
        for k in range(4):
            cells[bytes(tiles[32 * t + 8 * k:32 * t + 8 * k + 8])].append((t, k))
    seen = []
    for cy in range(25):
        for cx in range(40):
            c = bytes(bm[cy * 320 + cx * 8:cy * 320 + cx * 8 + 8])
            if any(c) and c in cells and len(cells[c]) <= 2:
                t, k = cells[c][0]
                seen.append((t, scr[cy * 40 + cx], col[cy * 40 + cx] & 15))
    same = sum(1 for t, s, _ in seen if s == colors[t])
    print(f"{len(seen)} cells matched to a tile, {same} with COLORS' byte; colour RAM {Counter(c for *_, c in seen)}")
    return 0 if seen and 2 * same > len(seen) and io[0x21] & 15 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
