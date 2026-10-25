#!/usr/bin/env python3
"""Ultima I's maps as PNGs: the four continents, every place on them named,
the towns and castles, and the dungeons' levels.

    python -m ultima.maps.u1maps [--out build/maps/u1]

Where the world is (MA is not the world map: its bytes are graphics): character creation, GE,
carries it at file offset $959 and puts it at $D000 for the game; OU copies
those 13 pages to $B000 while the party is outdoors (OU $8C9E) and back when
it leaves ($9279).  $B000 starts with four offsets, one a continent (OU
$9840: continent = $81E4 & 3), each to run-length data -- a byte is a count
(its top five bits) and a tile (its low three, stored x 2) -- that OU
decodes to a 64 x 64 map at $6400, ended by a zero.  The tile kinds, by
what OU does with them and by where the places are: 0 water, 1 grass, 2
forest, 3 mountains, 4 a castle, 5 a landmark (tower, pillars, sign
posts), 6 a town, 7 a dungeon.  MI (resident at $7400) lists the 84 places:
$7C18 y with the continent in bits 6-7, $7C6C x, and from $7CC0 their
names, each ending in a character with bit 7 set -- every entry lands on its
tile.

The tiles are the game's own, found by working back from the view renderer
(ST $1C8A): it reads the 19 x 9 tiles around the party from
$6400 ((map byte & $7E) / 2: monsters, $20-$58, alternate with the next
frame by a table at $B700), and per tile v copies 32 bytes from
($14C0,v)/($1480,v) -- $0C00 + 32v: ST's first 2 KiB are the 64 tiles, not
code -- into the bitmap, the first 16 the upper two cells (left, right),
the next 16 the lower two, and $1500,v into both cells' screen RAM (high
nibble the set pixels).  Places are framed and numbered (the names in
places.txt and in the margin).  Each continent's file is named by its lands,
as OU names them ("You are in the lands of", $9DC2: MI's list at $7BDA,
indexed by the continent).

The towns and castles (towns/, castles/: a layout's file is named by the
four places that use it): TW and CA load TC to $4000 and MA to $C700 (TW
$8CD8), take layout n from TC's ten pointers --
$4000 + 2n the two castles (CA), $4004 + 2n the eight towns (TW): town n is
the place's number in its continent less 13, so each layout serves four
towns, one a continent -- and copy it to $CB00.  A layout is 18 rows of 38
glyphs (TW $A51A: rows 1-18, columns 0-37 through MI's $83D7), then the
people: $CDAC type (bit 7: none), $CDBC x, $CDCC y, 16 each.  The glyphs
are MA, swapped in over the text font at $0800 for it (TW $A553): glyph g
is $0800 + 8g, in hires, its colour $1530,g -- TW's table at $A887 (CA's at
$A22B) swapped in.  The same routine swaps both back before the people are
drawn, so a person of type t is glyph $AD98,t (CA: $A21D,t) of the text
font, LO's first KiB (its '/' is the guard), in ST's own colours at $1530.
Checked in VICE (tools/vice/u1_town_check.py): Britain's and Lord
British's castle's bitmap and screen RAM equal to this, every cell, people
included (they move about, so it checks them where they stand); the view
outdoors equal to ST's tiles, as is the continent in RAM to GE's.

The dungeons (dungeons/NN_name.png, NN the place's number; dungeons.txt): DN
builds a level each time the party enters it ($8FAA; on entry and on every
Klimb, $9A89/$9AAE), 11 x 11 at
$B407, with a generator of its own ($A760: two bytes, next = first + 9 +
second + carry, the first moving to the second), seeded from the dungeon and
the level alone: first = place index ($8262, MI's, which OU's Enter looks up
from the square, $9DE4) x 8 ^ x ($81E8) ^ level ($A873), second = y ($81E9)
x 4 ^ continent ($81E4).  So each dungeon's ten levels are the same in every
game.  A plan at $A987 (walls round the edge and on every even x and y) is
filled between the pillars from a table at $A967 ($A773: open, door, secret
door -- its 2 and 9, trapdoors, become secret doors), 2n + 1 walls or force
fields on squares from $A92C/$A93C, n chests or coffins (which of the two is
ST's generator's, $906D), and the ladders ($9083-$90E2).  The squares (DN's
Forward $91E6, Search $A047, Klimb $9982, the spells $95FB-$96A6): 0 open, 1
wall, 2 trapdoor (Forward springs it, Search shows it as 9), 3 secret door (blocks;
Search makes it 4), 4 door, 5 chest, 6 coffin, 7 ladder down, 8 ladder up,
9 trapdoor (shown; Klimb goes down it), 12 force field; a monster is the high
nibble of an open square, placed at run time ($9F4E).  The party comes in on
level 1 at (1, 1), facing south, on the ladder up that leads out.  Checked
against DN's code under py65 (tests/test_u1_dungeons.py) and in VICE
(tools/vice/u1_dungeon_check.py).
"""
import argparse
import os
import re

from ultima import paths
from ultima.disks.d64 import D64

from ultima.maps.mapkit import mark_places, with_legend, write_places, Canvas, label, rgb
from ultima import paths

GE_WORLD = 0x959
MI_ADDR, LANDS, PLACES_Y, PLACES_X, NAMES = 0x7400, 0x7BDA, 0x7C18, 0x7C6C, 0x7CC0
KINDS = [("water", 6), ("grass", 13), ("forest", 5), ("mountains", 12),
         ("castle", 1), ("landmark", 3), ("town", 7), ("dungeon", 2)]
T = 16                                  # pixels a tile
ST_ADDR, TILE_COLOURS = 0x0C00, 0x1500


def prg(name):
    """A file of Ultima I's disk ("st.prg": ST), without its load address."""
    return D64(paths.disk("u1")).file(name[:-4].upper())[0][2:]


class Tiles:
    """ST's 64 tiles: 32 bytes each at $0C00 + 32v, colour $1500,v."""

    def __init__(self):
        st = prg("st.prg")
        colours = st[TILE_COLOURS - ST_ADDR:TILE_COLOURS - ST_ADDR + 64]
        self.rows = []
        for v in range(64):
            g = st[32 * v:32 * v + 32]
            fg, bg = bytes(rgb(colours[v] >> 4)), bytes(rgb(colours[v] & 15))
            bits = lambda x: b"".join(fg if x & (0x80 >> k) else bg for k in range(8))
            self.rows.append([bits(g[r]) + bits(g[8 + r]) for r in range(8)] +
                             [bits(g[16 + r]) + bits(g[24 + r]) for r in range(8)])

    def draw(self, c, x, y, v):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[v][r]


def continents():
    ge = prg("ge.prg")
    offs = [ge[GE_WORLD + 2 * i] | ge[GE_WORLD + 2 * i + 1] << 8 for i in range(4)]
    out = []
    for c in range(4):
        o, tiles = GE_WORLD + offs[c], []
        while ge[o]:
            tiles += [ge[o] & 7] * (ge[o] >> 3)
            o += 1
        assert len(tiles) == 4096, (c, len(tiles))
        out.append(tiles)
    return out


def strings(mi, at, n):
    """n of MI's strings from at, each ending in a character with bit 7 set."""
    o, out = at - MI_ADDR, []
    while len(out) < n:
        s = bytearray()
        while not mi[o] & 0x80:
            s.append(mi[o])
            o += 1
        s.append(mi[o] & 0x7F)
        o += 1
        out.append(s.decode("latin1"))
    return out


def places():
    mi = prg("mi.prg")
    ys = mi[PLACES_Y - MI_ADDR:PLACES_Y - MI_ADDR + 84]
    xs = mi[PLACES_X - MI_ADDR:PLACES_X - MI_ADDR + 84]
    names = strings(mi, NAMES, 84)
    return [(i + 1, names[i], ys[i] >> 6, xs[i], ys[i] & 63) for i in range(84)]


def lands():
    """The four continents' names: "Lord British", "the Feudal Lords", ..."""
    return strings(prg("mi.prg"), LANDS, 4)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def short(name):
    """A castle's name without "The Castle (of)" or "'s Castle"."""
    return re.sub(r"^(The Castle of |The Castle |The )|'s Castle$", "", name)


TC_ADDR, OVERLAY = 0x4000, 0x8C9E
LAYOUT = {"tw": (0xA887, 0xAD98), "ca": (0xA22B, 0xA21D)}    # (colours, people's glyphs)


def settlements(out, where):
    tc, ma = prg("tc.prg"), prg("ma.prg")
    font, st = prg("lo.prg")[:1024], prg("st.prg")
    text_colours = st[0x1530 - ST_ADDR:0x1530 - ST_ADDR + 128]
    ov = {k: prg(f"{k}.prg") for k in LAYOUT}
    ptr = [tc[2 * i] | tc[2 * i + 1] << 8 for i in range(10)]
    lines = []
    for n in range(10):
        kind = "ca" if n < 2 else "tw"
        number = n if n < 2 else n - 2
        col_at, who_at = LAYOUT[kind]
        colours = ov[kind][col_at - OVERLAY:col_at - OVERLAY + 128]
        glyph_of = ov[kind][who_at - OVERLAY:who_at - OVERLAY + 128]
        data = tc[ptr[n] - TC_ADDR:ptr[n] - TC_ADDR + 764]
        # the places that use it: castles 0-1, towns 13-20 of each continent's 21
        users = [name for i, name, _c, _x, _y in where
                 if ((i - 1) % 21 == number if kind == "ca" else (i - 1) % 21 - 13 == number)]
        S = 2
        TOP = 40
        c = Canvas(38 * 8 * S, 18 * 8 * S + TOP, 0)
        what = "castle" if kind == "ca" else "town"
        label(c, 2, 2, f"{what} layout {number} (TC ${ptr[n]:04X}; the people as the layout places them):")
        label(c, 2, 14, ", ".join(users[:2]) + ",")
        label(c, 2, 26, ", ".join(users[2:]))
        def put(x, y, g, glyphs=ma, colours=colours):
            g &= 0x7F
            c.hires(x * 8 * S, TOP + y * 8 * S, glyphs[8 * g:8 * g + 8], colours[g] >> 4, colours[g] & 15, scale=S)
        for y in range(18):
            for x in range(38):
                put(x, y, data[38 * y + x])
        people = data[684:]
        for i in range(16):
            t, x, y = people[i], people[16 + i], people[32 + i]
            if not t & 0x80 and x < 38 and y < 18:
                put(x, y, glyph_of[t], font, text_colours)
        sub = "castles" if kind == "ca" else "towns"
        named = slug("_".join(short(u) for u in users)) if kind == "ca" else slug("_".join(users))
        c.write(os.path.join(out, sub, f"{what}_{number}_{named}.png"))
        lines.append(f"{what} layout {number}: {', '.join(users)}")
    with open(os.path.join(out, "settlements.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


GEN_FILL, GEN_X, GEN_Y, GEN_PLAN = 0xA967, 0xA92C, 0xA93C, 0xA987
WALL, SECRET_DOOR, DOOR, CHEST, COFFIN, DOWN, UP, FIELD = 1, 3, 4, 5, 6, 7, 8, 12


class Dungeons:
    """DN's level generator, $8FAA-$90E2, as the game runs it on entering a
    level: its own two-byte generator ($A760), seeded from the dungeon and
    the level alone."""

    def __init__(self):
        dn = prg("dn.prg")
        at = lambda a, n: dn[a - OVERLAY:a - OVERLAY + n]
        self.fill, self.xs, self.ys = at(GEN_FILL, 20), at(GEN_X, 16), at(GEN_Y, 16)
        self.plan = at(GEN_PLAN, 121)

    def level(self, index, x, y, continent, n, box=None):
        """Level n (1-10) of the dungeon that is MI's place index (0-83) at
        (x, y) on the continent: 121 squares, row by row.  The chests and
        coffins are box: the game picks 5 or 6 for each with ST's generator."""
        seed = [(index << 3 ^ x ^ n) & 0xFF, (y << 2 ^ continent) & 0xFF]

        def rnd():                              # $A760; N is the old first byte's
            a = seed[0] + 9
            a = (a & 0xFF) + seed[1] + (a >> 8)
            seed[:] = [a & 0xFF, seed[0]]
            return seed[0]

        def fill():                             # $A773
            while (r := rnd() & 0x1F) >= 20:
                pass
            return SECRET_DOOR if self.fill[r] in (2, 9) else self.fill[r]

        m = list(self.plan)

        def put(v, x, y):
            m[y * 11 + x] = v
        for a in (8, 6, 4, 2):                  # between the pillars
            for b in (9, 7, 5, 3, 1):
                put(fill(), a, b)
                put(fill(), b, a)
        for _ in range(2 * n + 1):              # walls and fields
            v = FIELD if rnd() >= 0xA0 else WALL
            i = rnd() & 15
            put(v, *((self.xs[i], self.ys[i]) if n & 1 else (self.ys[i], self.xs[i])))
        for _ in range(n):                      # chests and coffins
            a, b = 2 * ((rnd() & 3) + 1), 2 * ((rnd() & 3) + 1)
            rnd()
            if seed[1] & 0x80:                  # BMI after $A760: its LDX's flags
                a += 1
            else:
                b += 1
            put(box, a, b)
        put(0, 1, 2)
        put(DOWN if n & 1 else UP, 3, 7)
        put(UP if n & 1 else DOWN, 7, 3)
        if n == 10:
            put(0, 7, 3)
        if n == 1:
            put(UP, 1, 1)
            put(0, 7, 3)
        return m


SQUARES = {WALL: ("", 11), SECRET_DOOR: ("SD", 4), DOOR: ("DR", 8), None: ("CC", 13),
           DOWN: ("D", 7), UP: ("U", 7), FIELD: ("FF", 14), 0: ("", 0)}
CELL = 24


def dungeons(out, world, where):
    gen = Dungeons()
    lines = []
    for i, name, c, x, y in where:
        if world[c][y * 64 + x] != 7:
            continue
        one = 11 * CELL + 2
        left, top = 20, 52
        cv = Canvas(5 * (one + left + 8) + 10, top + 2 * (one + 32), 0)
        write(cv, 10, 4, f"{i}: {name}, continent {c} at x {x}, y {y} -- in at (1, 1) on level 1, "
                         f"facing south", 1)
        write(cv, 10, 16, "grey wall, SD secret door (a wall until searched), DR door, FF force "
                          "field, U/D ladder up/down (level 1's U leads out),", 1)
        write(cv, 10, 28, "CC chest or coffin (which, the game picks on entering the level); "
                          "monsters are placed at run time", 1)
        for n in range(1, 11):
            X0 = 10 + left + ((n - 1) % 5) * (one + left + 8)
            Y0 = top + ((n - 1) // 5) * (one + 32)
            write(cv, X0, Y0, f"LEVEL {n}", 1)
            m = gen.level(i - 1, x, y, c, n)
            for k in range(11):
                write(cv, X0 + 1 + k * CELL + (CELL - 8 * len(str(k))) // 2, Y0 + 12, str(k), 15)
                write(cv, X0 - 4 - 8 * len(str(k)), Y0 + 22 + k * CELL + CELL // 2 - 4, str(k), 15)
            for yy in range(11):
                for xx in range(11):
                    v = m[yy * 11 + xx]
                    text, col = SQUARES[v]
                    X, Y = X0 + 1 + xx * CELL, Y0 + 22 + yy * CELL
                    cv.fill(X, Y, CELL, CELL, 11 if v == WALL else 0)
                    cv.frame(X, Y, CELL, CELL, 6)
                    if text:
                        write(cv, X + (CELL - 8 * len(text)) // 2, Y + CELL // 2 - 4, text, col)
        cv.write(os.path.join(out, "dungeons", f"{i:02}_{slug(name)}.png"))
        lines.append(f"{i:2}  continent {c}  x {x:2}  y {y:2}  {name}")
    with open(os.path.join(out, "dungeons.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def write(c, x, y, text, colour):
    label(c, x, y, text, colour)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u1"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    world, where, tiles, names = continents(), places(), Tiles(), lands()
    every = []
    for c in range(4):
        here = [p for p in where if p[2] == c]
        c_ = Canvas(64 * T + 32, 64 * T + 32, 0)
        castles = [n for _i, n, _c, x, y in here if world[c][y * 64 + x] == 4]
        label(c_, 4, 2, f"continent {c}, the lands of {names[c]} ({' / '.join(castles)})")
        for y in range(64):
            for x in range(64):
                tiles.draw(c_, 16 + x * T, 16 + y * T, world[c][y * 64 + x])
        marks = [(i, x, y, name, KINDS[world[c][y * 64 + x]][0], KINDS[world[c][y * 64 + x]][1])
                 for i, name, _c, x, y in here]
        mark_places(c_, marks, T, write, 16, 16)
        with_legend(c_, marks, write).write(os.path.join(a.out, f"continent_{c}_{slug(names[c])}.png"))
        every += [(i, x, y, f"{name} (continent {c})", kind) for i, x, y, name, kind, _ in marks]
    write_places(os.path.join(a.out, "places.txt"),
                 "Ultima I's 84 places (MI $7C18/$7C6C, names from $7CC0)", every)
    settlements(a.out, where)
    dungeons(a.out, world, where)
    print("written to", a.out)


if __name__ == "__main__":
    main()
