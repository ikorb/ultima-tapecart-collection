#!/usr/bin/env python3
"""Ultima IV's maps as PNGs, from the cart as built.

    python -m ultima.maps.u4maps [--tcrt build/ultima-collection.tcrt] [--remastered]
                           [--out build/maps/u4] [--scale N] [what ...]

what: britannia, towns, dungeons, rooms (default: all).  Everything is read
from the cart's flash the way the driver reads it -- each disk's block map,
each block its zx02 stream (or raw) -- so the maps are what the game gets,
the Remastered fixes included (the rooms' start positions, Thevel, the
Serpent's Hold guards).  Graphics: the cart's own tile bitmap (chunk $41)
and colour table ($4C, $E1B0), or with --remastered the kit's tiles and its
four per-cell tables (ultima/games/u4/tileset.py), as the page's G switches them.

- britannia.png: the 256 x 256 overworld (disk C blocks 1-256, 16 x 16 tiles
  each, row by row), the 32 places named in the margin's index
  (britannia_places.txt: game main's entrance table $519A/$51BA).
- towns/NN_name.png: the 16 towns and castles (chunks $5C-$6B, disk B: a
  32 x 32 map, then the people -- 32 tiles, x, y -- drawn on it) and $6C,
  Castle British's upper floor (its two ladders down are on the squares of
  the two ladders up in $5C, (3, 3) and (27, 3)).
- dungeons/name.png: each dungeon's eight 8 x 8 levels (chunks $8C-$93,
  disk D) as a plan: walls, ladders, doors, rooms (Rn) and the rest by kind.
- rooms/name.png: its 16 rooms (disk D block = room + 1), 11 x 11 tiles,
  the party's start positions by the side entered (N E S W, coloured dots),
  the triggers' squares outlined, the level each is on, and "BAD x" where
  the level lets the party walk in from side x but the room has no start
  positions for it (the original disk shows Destard 12 and 14, Hythloth 7
  and 9 -- the Remastered fixes; the cart none).  The Abyss reuses its room
  numbers on several levels, so its pages are shown unchecked.

Tiles are 16 x 16 pixels; --scale 2 or 4 shrinks britannia.png to every
2nd or 4th pixel.
"""
import argparse
import os
import re
from pathlib import Path

from ultima.flash import regions
from ultima.flash import zx
from ultima.maps.mapkit import Canvas, mark_places, rgb, with_legend, wrap, write_places
from ultima.flash.tcrt import TCRT
from ultima import paths

KERNEL_ADDR = 0xA100
CHUNK_CNT, CHUNK_PAGE, CHUNK_BLK, CHUNK_FIRST = 0xA2A9, 0xA309, 0xA369, 0x40
A, C, B, D = 1, 2, 3, 4                 # the game's disk numbers (C is Britannia)
TOWNS = ["Castle British", "Lycaeum", "Empath Abbey", "Serpent's Hold", "Moonglow", "Britain",
         "Jhelom", "Yew", "Minoc", "Trinsic", "Skara Brae", "Magincia", "Paws",
         "Buccaneer's Den", "Vesper", "Cove"]
DUNGEONS = ["Deceit", "Despise", "Destard", "Wrong", "Covetous", "Shame", "Hythloth", "Abyss"]
SHRINES = ["Honesty", "Compassion", "Valor", "Justice", "Sacrifice", "Honor", "Spirituality",
           "Humility"]
PLACES = TOWNS + DUNGEONS + ["shrine of " + s for s in SHRINES]


def symbols(path):
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}


class Cart:
    """U4 as it is in a cart image: blocks by (disk, number), chunks."""

    def __init__(self, tcrt):
        self.flash = TCRT.read(tcrt).flash
        o = regions.desc_offset("u4")
        desc = self.flash[o:o + 64]
        segs = {}
        for i in range(desc[2]):
            e = 3 + 7 * i
            segs[desc[e + 4] | desc[e + 5] << 8] = (desc[e] << 8 | desc[e + 1] << 16,
                                                     desc[e + 2] | desc[e + 3] << 8)
        dest = max(d for d in segs if d <= KERNEL_ADDR)     # (behind u4a0.s at $A006)
        off, length = segs[dest]
        self.kernel = self.flash[off + KERNEL_ADDR - dest:off + length]
        s = symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        k = lambda a: self.kernel[a - KERNEL_ADDR]
        self.maps = {d: k(s["u4_map_lo"] + d - 1) | k(s["u4_map_mid"] + d - 1) << 8
                     | k(s["u4_map_hi"] + d - 1) << 16 for d in (A, C, B, D)}
        self.cache = {}

    def block(self, disk, n):
        key = (disk, n)
        if key not in self.cache:
            e = self.flash[self.maps[disk] + 4 * n:self.maps[disk] + 4 * n + 4]
            addr, length = e[0] | e[1] << 8 | e[2] << 16, e[3]
            self.cache[key] = bytes(self.flash[addr:addr + 256] if length == 0
                                    else zx.decode(self.flash[addr:addr + length]))
        return self.cache[key]

    def chunk_entry(self, c):
        k = lambda a: self.kernel[a - KERNEL_ADDR]
        i = c - CHUNK_FIRST
        return (k(CHUNK_BLK + 2 * i) | k(CHUNK_BLK + 2 * i + 1) << 8, k(CHUNK_CNT + i),
                k(CHUNK_PAGE + i) << 8)

    def chunk(self, c, disk):
        start, count, _dest = self.chunk_entry(c)
        return b"".join(self.block(disk, start + i) for i in range(count))


class Tiles:
    """The 256 tiles as 16 rows of 16 RGB pixels each."""

    def __init__(self, cart, remastered=False):
        if remastered:
            from ultima.games.u4 import tileset
            bitmap, tabs = tileset.graphics()[:2]
        else:
            bitmap = cart.chunk(0x41, A)
            table = cart.chunk(0x4C, A)[0x1B0:0x2B0]
            tabs = [table] * 4
        self.rows = []
        for t in range(256):
            cells = (bitmap[16 * t:16 * t + 8], bitmap[16 * t + 8:16 * t + 16],
                     bitmap[0x1000 + 16 * t:0x1000 + 16 * t + 8],
                     bitmap[0x1000 + 16 * t + 8:0x1000 + 16 * t + 16])
            rows = []
            for half in (0, 1):
                for r in range(8):
                    line = b""
                    for k in (2 * half, 2 * half + 1):
                        fg, bg = bytes(rgb(tabs[k][t] >> 4)), bytes(rgb(tabs[k][t] & 15))
                        line += b"".join(fg if cells[k][r] & (0x80 >> b) else bg for b in range(8))
                    rows.append(line)
            self.rows.append(rows)
        self.font = cart.chunk(0x42, A)

    def draw(self, c, x, y, t):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[t][r]


def grid(tiles, data, w, h, margin=0):
    c = Canvas(w * 16 + 2 * margin, h * 16 + 2 * margin, 11)
    for y in range(h):
        for x in range(w):
            tiles.draw(c, margin + 16 * x, margin + 16 * y, data[y * w + x])
    return c


def text(c, x, y, s, tiles, fg=1, scale=1):
    c.text(x, y, s.upper(), tiles.font, fg, scale, code=lambda ch: ord(ch) & 0x7F)


# ---- the overworld ---------------------------------------------------------
def britannia_map(cart):
    w = bytearray(256 * 256)
    for cy in range(16):
        for cx in range(16):
            d = cart.block(C, cy * 16 + cx + 1)
            for y in range(16):
                w[(cy * 16 + y) * 256 + cx * 16:(cy * 16 + y) * 256 + cx * 16 + 16] = d[16 * y:16 * y + 16]
    return bytes(w)


def places(cart):
    """[(name, x, y)]: game main's entrance table (chunk $5B, $519A/$51BA)."""
    gm = cart.chunk(0x5B, A)
    return [(PLACES[i], gm[0x519A - 0x4000 + i], gm[0x51BA - 0x4000 + i]) for i in range(32)]


def place_kind(i):
    return "castle" if i < 4 else "town" if i < len(TOWNS) else "dungeon" if i < len(TOWNS) + len(DUNGEONS) else "shrine"


def britannia(cart, tiles, out, scale=1):
    world = britannia_map(cart)
    c = grid(tiles, world, 256, 256)
    marks = [(i + 1, x, y, name, place_kind(i)) for i, (name, x, y) in enumerate(places(cart))]
    # the Shrine of Spirituality has no square: its entry repeats Humility's,
    # and the shrine is reached only through Minoc's moongate at a double
    # full moon
    spirit = PLACES.index("shrine of Spirituality")
    assert marks[spirit][1:3] == marks[PLACES.index("shrine of Humility")][1:3]
    marks[spirit] = (spirit + 1, None, None,
                     "shrine of Spirituality: through Minoc's moongate at a double full moon", "shrine")

    def write(c_, x, y, s, fg):
        text(c_, x, y, s, tiles, fg)
    mark_places(c, marks, 16, write)
    if scale > 1:
        small = Canvas(c.w // scale, c.h // scale)
        for y in range(small.h):
            for x in range(small.w):
                o = 3 * (y * scale * c.w + x * scale)
                small.px[3 * (y * small.w + x):3 * (y * small.w + x) + 3] = c.px[o:o + 3]
        c = small
    with_legend(c, marks, write).write(os.path.join(out, "britannia.png"))
    write_places(os.path.join(out, "britannia_places.txt"),
                 "Britannia's places: game main's entrance table (chunk $5B, $519A/$51BA); "
                 "the sextant reading after each name", 
                 [(k, x, y, f"{name}  (sextant {chr(65 + y // 16)}'{chr(65 + y % 16)}\" "
                             f"{chr(65 + x // 16)}'{chr(65 + x % 16)}\")" if x is not None else name, kind)
                  for k, x, y, name, kind in marks])


# ---- towns -----------------------------------------------------------------
def towns(cart, tiles, out):
    for n in range(17):
        chunk = 0x5C + n
        data = cart.chunk(chunk, B)
        c = grid(tiles, data[:1024], 32, 32, margin=16)
        people = data[1024:1024 + 256]
        for i in range(32):
            t, x, y = people[i], people[32 + i], people[64 + i]
            if t:
                tiles.draw(c, 16 + 16 * x, 16 + 16 * y, t)
        name = TOWNS[n] if n < 16 else "Castle British, upper floor"
        text(c, 16, 4, f"{name}  (chunk ${chunk:02X})", tiles, 1)
        c.write(os.path.join(out, "towns", f"{n + 1:02d}_{slug(name)}.png"))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ---- dungeons --------------------------------------------------------------
KINDS = {0x00: ("", 12), 0x10: ("U", 7), 0x20: ("D", 7), 0x30: ("UD", 7), 0x40: ("CH", 8),
         0x50: ("CE", 15), 0x60: ("HO", 15), 0x70: ("OB", 14), 0x80: ("TR", 2), 0x90: ("FO", 3),
         0xB0: ("AL", 1), 0xC0: ("DR", 9), 0xE0: ("SD", 4)}
FIELDS = {0: ("PF", 5), 1: ("EF", 14), 2: ("FF", 2), 3: ("SF", 4)}
CELL = 40


def square(t):
    """(label, colour) of a level square; None for a wall."""
    k = t & 0xF0
    if k == 0xF0:
        return None
    if k == 0xD0:
        return (f"R{t & 15}", 1)
    if k == 0xA0:
        return FIELDS.get(t & 15, ("F?", 2))
    return KINDS.get(k, (f"{t:02X}", 10))


def levels(cart, d):
    return cart.chunk(0x8C + d, D)


def level_canvas(lv, L, tiles):
    c = Canvas(8 * CELL + 2, 8 * CELL + 14, 0)
    text(c, 1, 2, f"LEVEL {L + 1}", tiles, 1)
    for y in range(8):
        for x in range(8):
            t = lv[L * 64 + y * 8 + x]
            X, Y = 1 + x * CELL, 13 + y * CELL
            s = square(t)
            if s is None:
                c.fill(X, Y, CELL, CELL, 11)
                continue
            label, col = s
            c.fill(X, Y, CELL, CELL, 0)
            c.frame(X, Y, CELL, CELL, 6)
            if label:
                text(c, X + (CELL - 8 * len(label)) // 2, Y + CELL // 2 - 4, label, tiles, col)
    return c


DUNGEON_LEGEND = ("U ladder up, D down, UD both, Rn room n, DR door, SD secret door, CH chest, "
                  "OB orb, TR trap, FO fountain, AL altar; fields: PF poison, EF energy, FF fire, "
                  "SF sleep")


def dungeon_sheet(lv, name, tiles, marks=None):
    """The eight levels side by side, four a row.  marks: {L: [(x, y, colour)]}
    framed squares (a route's)."""
    one = level_canvas(lv, 0, tiles)
    w = 4 * (one.w + 12) + 12
    legend = wrap(DUNGEON_LEGEND, w - 24)
    top = 18 + 12 * len(legend) + 10
    c = Canvas(w, 2 * (one.h + 12) + top, 0)
    text(c, 12, 6, name, tiles, 1)
    for i, line in enumerate(legend):
        text(c, 12, 18 + 12 * i, line, tiles, 15)
    for L in range(8):
        lc = level_canvas(lv, L, tiles)
        for x, y, col in (marks or {}).get(L, []):
            lc.frame(1 + x * CELL + 2, 13 + y * CELL + 2, CELL - 4, CELL - 4, col, 3)
        c.blit(lc, 12 + (L % 4) * (one.w + 12), top + (L // 4) * (one.h + 12))
    return c


def dungeons(cart, tiles, out):
    for d, name in enumerate(DUNGEONS):
        dungeon_sheet(levels(cart, d), name, tiles).write(os.path.join(out, "dungeons", f"{d + 1}_{slug(name)}.png"))


# ---- rooms -----------------------------------------------------------------
SIDES = (("N", 0x40, 7), ("E", 0x50, 5), ("S", 0x60, 3), ("W", 0x70, 10))


def room_page(cart, room):
    return cart.block(D, room + 1)


def room_canvas(page, label, tiles):
    c = Canvas(11 * 16 + 4, 11 * 16 + 16, 0)
    text(c, 2, 2, label, tiles, 1)
    for y in range(11):
        for x in range(11):
            tiles.draw(c, 2 + 16 * x, 14 + 16 * y, page[0x80 + y * 11 + x])
    for i in range(4):                          # the triggers
        tr = page[4 * i:4 * i + 4]
        if tr[0]:
            for xy, col in ((tr[1], 7), (tr[2], 2), (tr[3], 2)):
                c.frame(2 + 16 * (xy >> 4), 14 + 16 * (xy & 15), 16, 16, col, 2)
    for k, (side, o, col) in enumerate(SIDES):   # the start positions
        for i in range(8):
            x, y = page[o + i], page[o + 8 + i]
            if (x, y) == (0, 0):
                continue
            c.fill(2 + 16 * x + 2 + 6 * (k % 2), 14 + 16 * y + 2 + 6 * (k // 2), 5, 5, col)
    for i in range(16):                          # the monsters
        t, x, y = page[0x10 + i], page[0x20 + i], page[0x30 + i]
        if t:
            tiles.draw(c, 2 + 16 * x, 14 + 16 * y, t)
    return c


DIRS = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


def room_places(lv, room):
    """[(level, x, y)] of room n's squares."""
    return [(L, x, y) for L in range(8) for y in range(8) for x in range(8)
            if lv[L * 64 + y * 8 + x] == 0xD0 | room]


def enterable(lv, room):
    """The sides the party can walk into room n from: its square's neighbour
    on that side is not a wall (the levels wrap)."""
    out = set()
    for L, x, y in room_places(lv, room):
        for side, (dx, dy) in DIRS.items():
            t = lv[L * 64 + ((y + dy) % 8) * 8 + (x + dx) % 8]
            if t & 0xF0 != 0xF0:
                out.add(side)
    return out


def room_sheet(cart, d, tiles):
    one = room_canvas(room_page(cart, 0), "", tiles)
    lv = levels(cart, d)
    w = 4 * (one.w + 8) + 8
    head = [(line, 15) for line in wrap(
        f"{DUNGEONS[d]}: rooms (start positions by the side entered: N yellow, E green, S cyan, "
        f"W light red; triggers: yellow the square, red the squares it changes; BAD X: enterable "
        f"from X, no start positions there)", w - 16)]
    if DUNGEONS[d] == "Abyss":
        head += [(line, 10) for line in wrap(
            "The Abyss: room pages $70-$7F; its levels reuse room numbers, which page is which "
            "is not checked", w - 16)]
    top = 6 + 12 * len(head) + 6
    c = Canvas(w, 4 * (one.h + 8) + top, 0)
    for i, (line, col) in enumerate(head):
        text(c, 8, 6 + 12 * i, line, tiles, col)
    for r in range(16):
        page = room_page(cart, 16 * d + r)
        missing = [s for s, o, _ in SIDES if all(page[o + i] == 0 and page[o + 8 + i] == 0 for i in range(8))]
        # (the Abyss reuses its room numbers on several levels -- R0 on 1, 3,
        # 5 and 7 -- so its rooms are not simply $70 + n; where they are was
        # not looked into, and nothing is flagged there)
        bad = [s for s in missing if s in enterable(lv, r)] if DUNGEONS[d] != "Abyss" else []
        where = room_places(lv, r) if DUNGEONS[d] != "Abyss" else []
        label = f"ROOM {r}" + (f" L{where[0][0] + 1}" if where else "") + (f" BAD {''.join(bad)}" if bad else "")
        c.blit(room_canvas(page, label, tiles), 8 + (r % 4) * (one.w + 8), top + (r // 4) * (one.h + 8))
    return c


def rooms(cart, tiles, out):
    for d, name in enumerate(DUNGEONS):
        room_sheet(cart, d, tiles).write(os.path.join(out, "rooms", f"{d + 1}_{slug(name)}.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tcrt", default=os.path.join(paths.BUILD, "ultima-collection.tcrt"))
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u4"))
    ap.add_argument("--remastered", action="store_true", help="the kit's tile set (the page's G)")
    ap.add_argument("--scale", type=int, default=1, help="britannia.png: every Nth pixel")
    ap.add_argument("what", nargs="*", default=["britannia", "towns", "dungeons", "rooms"])
    a = ap.parse_args()
    cart = Cart(a.tcrt)
    tiles = Tiles(cart, a.remastered)
    for w in a.what:
        print(w, flush=True)
        if w == "britannia":
            britannia(cart, tiles, a.out, a.scale)
        else:
            globals()[w](cart, tiles, a.out)
    print("written to", a.out)


if __name__ == "__main__":
    main()
