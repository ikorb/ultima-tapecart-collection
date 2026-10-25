#!/usr/bin/env python3
"""Ultima VI's maps as PNGs, from its disks (the cart stores these sectors
raw; what play changes are the objects, in the chunk files, not drawn).

    python -m ultima.maps.u6maps [--out build/maps/u6] [what ...]

what: overview, superchunks, dungeons (default: all).

The world is 1024 x 1024 tiles: 8 x 8 superchunks of 16 x 16 chunks of 8 x 8
tiles (docs/reversing-notes/u6.md, read from `game`).  On the
Surface disk (1A), superchunk (x, y)'s chunk numbers are track y + 1, sector
x (16 x 16 bytes), and a bank bit per chunk is in track y + 1 sector 8,
bytes 32x..32x+31 ($238D); chunk c's 64 tile numbers are track 26 + c/64
(bank 0) or 30 + c/64 (bank 1), sector (c/4) & 15, offset (c & 3) x 64
($2699, $27F4).  A dungeon level L (1-5) is the Dungeon disk's (1B) track L:
sectors 0-3 its 32 x 32 chunk numbers row by row, sector 4 bytes $00-$7F the
bank bits, its chunks on that disk's tracks 26-33.  The bank bits' order
(chunk n is byte n/8, bit n & 7), the dungeon map's rows and its bits' place
were chosen by how well the chunks join: tiles equal across chunk borders,
surface superchunk 2,2 1641 (high bit first 1219), dungeon level 1 9684 with
sector 4's first half (the memory map's note says $80-$FF: 2373) and 6890
read as four 16 x 16 blocks.

Tiles: the Game disk's TILES (512 tiles of 32 bytes, its four 8 x 8
multicolour cells upper left, upper right, lower left, lower right) and
COLORS (a byte a tile: its screen-RAM byte), on black ($D021) with light
grey in colour RAM -- measured in VICE on a running game (maps/u6_colours_check.py: the view's cells
against TILES: 332 of 340 cells had COLORS' byte, the rest animated tiles).
Map tiles are 0-255.

- overview.png: the whole surface, 2 x 2 pixels a tile (its average colour),
  its places framed and keyed with a legend, and places.txt (u6places.py:
  shrines, dungeons and caves, runes, the Codex... from the surface's
  object files and the state; the towns inferred from their people).
- superchunks/sc_X_Y.png: one superchunk, 128 x 128 tiles at 16 x 16, with
  the places in it (the legend's x,y the surface's; the frames at
  superchunk-relative squares).
- dungeons/level_L.png: a dungeon level, 256 x 256 tiles at 8 x 8 (halved).
"""
import argparse
import os

from ultima.disks.d64 import D64
from ultima.maps.mapkit import Canvas, label, mark_places, rgb, with_legend, write_places
from ultima.maps import u6places
from ultima import paths

DISKS = {"surface": "u6-1a", "dungeon": "u6-1b", "game": "u6-3b"}
BG, COLRAM = 0, 15


def disk(k):
    return D64(paths.disk(DISKS[k]))


class Tiles:
    def __init__(self, game):
        tiles, colors = game.payload("TILES")[0], game.payload("COLORS")[0]
        self.rows, self.avg = [], []
        for t in range(256):
            pal = [rgb(BG), rgb(colors[t] >> 4), rgb(colors[t] & 15), rgb(COLRAM)]
            rows = [b""] * 16
            acc = [0, 0, 0]
            for k in range(4):
                cell = tiles[32 * t + 8 * k:32 * t + 8 * k + 8]
                for r in range(8):
                    line = b""
                    for p in range(4):
                        c = pal[(cell[r] >> (6 - 2 * p)) & 3]
                        line += bytes(c) * 2
                        for i in range(3):
                            acc[i] += c[i]
                    rows[8 * (k >> 1) + r] += line
            self.rows.append(rows)
            self.avg.append(tuple(a // 128 for a in acc))

    def draw(self, c, x, y, t):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[t][r]

    def draw_half(self, c, x, y, t):
        for r in range(8):
            row = self.rows[t][2 * r]
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 24] = b"".join(row[6 * i:6 * i + 3] for i in range(8))


def chunk_tiles(d, c, bank):
    t = (30 if bank else 26) + (c >> 6)
    s = (c >> 2) & 15
    o = (c & 3) * 64
    return d.sector(t, s)[o:o + 64]


def superchunk(d, sx, sy):
    """128 x 128 tile numbers of superchunk (sx, sy)."""
    idx = d.sector(sy + 1, sx)
    bits = d.sector(sy + 1, 8)[32 * sx:32 * sx + 32]
    out = bytearray(128 * 128)
    for n in range(256):
        bank = bits[n >> 3] >> (n & 7) & 1
        ch = chunk_tiles(d, idx[n], bank)
        cy, cx = n >> 4, n & 15
        for y in range(8):
            out[(cy * 8 + y) * 128 + cx * 8:(cy * 8 + y) * 128 + cx * 8 + 8] = ch[8 * y:8 * y + 8]
    return bytes(out)


def overview(tiles, out):
    d = disk("surface")
    c = Canvas(1024 * 2, 1024 * 2 + 12, 0)
    label(c, 2, 2, "Ultima VI: the surface, 2 x 2 pixels a tile (superchunks 8 x 8, numbered x,y)")
    for sy in range(8):
        for sx in range(8):
            m = superchunk(d, sx, sy)
            for y in range(128):
                o = 3 * ((12 + (sy * 128 + y) * 2) * c.w + sx * 256)
                line = b"".join(bytes(tiles.avg[m[y * 128 + x]]) * 2 for x in range(128))
                c.px[o:o + len(line)] = line
                c.px[o + 3 * c.w:o + 3 * c.w + len(line)] = line
            label(c, sx * 256 + 2, 12 + sy * 256 + 2, f"{sx},{sy}", 1)
    here = sorted_places()
    mark_places(c, here, 2, write, 0, 12)
    with_legend(c, here, write).write(os.path.join(out, "overview.png"))
    write_places(os.path.join(out, "places.txt"), PLACES_NOTE, here)


def write(c, x, y, text, colour):
    label(c, x, y, text, colour)


PLACES_NOTE = ("Ultima VI's places on the surface (maps/u6places.py says how each is found): S1-S8 the "
               "shrines (S without a conversation), D<n> the dungeons and caves by the game's own list, "
               "L ladders down with no name, R<n> the runes, CX the Codex, B the balloon basket, A the "
               "Avatar's start, LB Lord British; T<n> the towns, inferred from where their people start")
ORDER = ["S", "D", "L", "R", "CX", "B", "A", "LB", "T"]


def sorted_places():
    def key(p):
        k = str(p[0])
        head = k.rstrip("0123456789")
        return ORDER.index(head), int(k[len(head):] or 0)
    return sorted(u6places.places(), key=key)


def superchunks(tiles, out):
    d = disk("surface")
    every = sorted_places()
    for sy in range(8):
        for sx in range(8):
            m = superchunk(d, sx, sy)
            c = Canvas(128 * 16, 128 * 16 + 12, 0)
            label(c, 2, 2, f"superchunk {sx},{sy}: tiles x {sx * 128}-{sx * 128 + 127}, "
                           f"y {sy * 128}-{sy * 128 + 127}")
            for y in range(128):
                for x in range(128):
                    tiles.draw(c, 16 * x, 12 + 16 * y, m[y * 128 + x])
            here = [(k, x - sx * 128, y - sy * 128, f"{name}  ({x},{y})", kind) for k, x, y, name, kind in every
                    if x >> 7 == sx and y >> 7 == sy]
            if here:
                mark_places(c, here, 16, write, 0, 12)
                c = with_legend(c, here, write)
            c.write(os.path.join(out, "superchunks", f"sc_{sx}_{sy}.png"))
        print(" row", sy, flush=True)


def dungeons(tiles, out):
    d = disk("dungeon")
    for L in range(1, 6):
        idx = b"".join(d.sector(L, s) for s in range(4))
        bits = d.sector(L, 4)[:0x80]
        c = Canvas(256 * 8, 256 * 8 + 12, 0)
        label(c, 2, 2, f"dungeon level {L} (disk 1B track {L}), 8 x 8 pixels a tile")
        for n in range(1024):
            bank = bits[n >> 3] >> (n & 7) & 1
            ch = chunk_tiles(d, idx[n], bank)
            cy, cx = n >> 5, n & 31
            for y in range(8):
                for x in range(8):
                    tiles.draw_half(c, (cx * 8 + x) * 8, 12 + (cy * 8 + y) * 8, ch[8 * y + x])
        c.write(os.path.join(out, "dungeons", f"level_{L}.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u6"))
    ap.add_argument("what", nargs="*", default=["overview", "superchunks", "dungeons"])
    a = ap.parse_args()
    tiles = Tiles(disk("game"))
    os.makedirs(a.out, exist_ok=True)
    for w in a.what:
        print(w, flush=True)
        globals()[w](tiles, a.out)
    print("written to", a.out)


if __name__ == "__main__":
    main()
