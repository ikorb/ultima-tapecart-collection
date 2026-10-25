#!/usr/bin/env python3
"""Ultima V's maps as PNGs, from its disks (the cart stores the raw sector
areas and the files unchanged, but for the save slots and the patches the
options apply in RAM).

    python -m ultima.maps.u5maps [--out build/maps/u5] [what ...]

what: britannia, underworld, towns, dungeons (default: all).  The layout is
the one Ultima V Remastered's tools read (Drunella; its src/disks.cfg,
tools/create_maps.sh, mapbuilder.py), here straight from the d64s:

- britannia.png / underworld.png: disk 2A / 2B, tracks 20-35, sectors 0-15,
  one sector a 16 x 16 block, row by row: 256 x 256 tiles.  Their places
  framed and keyed, with a legend and britannia_places.txt /
  underworld_places.txt: the 32 places and 8 dungeons from Enter's own
  coordinate tables (E $A80A/$A832; main.out $8947 holds the same), each
  checked against the tile there, which also gives its kind (E $A85A);
  the shrines (E $ADA8/$ADB0), the Codex (its tile, $11), the moonstones'
  starting squares where the gates show at night (ROSTER $1280/$1288),
  Search's three reagent spots (S $AB72), the falls (main.out $9741) and
  the whirlpool's landing in the Underworld (main.out $9CBE).  Ararat is
  the one place below; the dungeons are at the same squares on both.
- towns/<disk>_<n>_<place>[_<floor>].png: disks 3A (towne), 3B (dwelling),
  4A (castle), 4B (keep), tracks 32-35, four sectors a map (main.twn's read,
  $98FA: track $20 + n/4, sector (n*4) & $0F), the four as 2 x 2 blocks of
  16 x 16 -- 16 maps a disk; towns.txt lists them.  Which place and floor a
  map is comes from the game: main.twn's $98DA takes map = (entry - 1) & 15
  + floor ($09; -1 a basement) from a table of the 32 places' ground floors
  at $81B8 (place 1 first), eight places a disk.  A place has a basement
  when its ground floor has a ladder down (tile $C9; $C8 up), and its maps
  run up to the next place's lowest; every map but a place's top has a
  ladder up (asserted).  The names are the game's own, in the order of the
  Enter command's list (overlay E on 2A -- asserted), which has an empty
  name for places 14-18: the two castles it words on their own ("the
  Castle of Lord British!"), and three huts it calls only "hut": places
  14-16 are Sutek's, Sin'Vraal's and Grendel's, the one person in each
  people table (main.twn's record $F8 + place-1 & 7) being the hut's owner
  (dialogue/u5talk.py).
- dungeons/<n>.png: disk 1B track 35, two sectors each: eight 8 x 8 levels,
  as a plan with the kit's legend (tools/dungeonbuilder.py, src/png/
  dungeon.yaml -- its authors' reading, not checked here).

Graphics: disk 1A's S0-S3 (4 KiB each: 8 x 8 characters, four to a tile in
the order upper left, upper right, lower left, lower right) and COLORS (a
byte a character, foreground high nibble) -- tiles 0-255, the map bytes.
"""
import argparse
import os
import re

from ultima.disks.d64 import D64
from ultima.maps.mapkit import mark_places, with_legend, write_places, Canvas, label, rgb
from ultima import paths

DISK = {t: "u5-" + t.lower() for t in ("1A", "1B", "2A", "2B", "3A", "3B", "4A", "4B")}
TITLE = {"1A": "Program", "1B": "Dungeon", "2A": "Britannia", "2B": "Underworld",
         "3A": "Towne", "3B": "Dwelling", "4A": "Castle", "4B": "Keep"}
TOWN_DISKS = {"3A": "towne", "3B": "dwelling", "4A": "castle", "4B": "keep"}
# (name, whether the Enter command's list of names has it)
PLACES = [("Moonglow", 1), ("Britain", 1), ("Jhelom", 1), ("Yew", 1), ("Minoc", 1), ("Trinsic", 1),
          ("Skara Brae", 1), ("New Magincia", 1),
          ("Fogsbane", 1), ("Stormcrow", 1), ("Greyhaven", 1), ("Waveguide", 1), ("Iolo's Hut", 1),
          ("Sutek's Hut", 0), ("Sin'Vraal's Hut", 0), ("Grendel's Hut", 0),
          ("Castle of Lord British", 0), ("Palace of Blackthorn", 0), ("West Britanny", 1),
          ("North Britanny", 1), ("East Britanny", 1), ("Paws", 1), ("Cove", 1), ("Buccaneer's Den", 1),
          ("Ararat", 1), ("Bordermarch", 1), ("Farthing", 1), ("Windemere", 1), ("Stonegate", 1),
          ("The Lycaeum", 1), ("Empath Abbey", 1), ("Serpent's Hold", 1)]
FIRST_MAPS = 0x81B8                     # main.twn: place 1's entry ($81B7 is an RTS, read as place 0)
LADDER_UP, LADDER_DOWN = 0xC8, 0xC9
FLOORS = {-1: "basement", 0: "ground floor", 1: "first floor", 2: "second floor", 3: "third floor"}
DUNGEONS = ["Deceit", "Despise", "Destard", "Wrong", "Covetous", "Shame", "Hythloth", "Doom"]


def disk(tag):
    return D64(paths.disk(DISK[tag]))


class Tiles:
    def __init__(self, a):
        chars = b"".join(a.payload(f"S{i}")[0][:4096] for i in range(4))
        colours = a.payload("COLORS")[0]
        self.rows = []
        for t in range(256):
            rows = []
            for half in (0, 1):
                for r in range(8):
                    line = b""
                    for k in (2 * half, 2 * half + 1):
                        ch = 4 * t + k
                        fg, bg = bytes(rgb(colours[ch] >> 4)), bytes(rgb(colours[ch] & 15))
                        v = chars[8 * ch + r]
                        line += b"".join(fg if v & (0x80 >> b) else bg for b in range(8))
                    rows.append(line)
            self.rows.append(rows)

    def draw(self, c, x, y, t):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[t][r]


def world(d, tiles, title):
    c = Canvas(256 * 16, 256 * 16 + 12, 0)
    label(c, 2, 2, title)
    for by in range(16):
        for bx in range(16):
            blk = d.sector(20 + by, bx)
            for y in range(16):
                for x in range(16):
                    tiles.draw(c, (bx * 16 + x) * 16, 12 + (by * 16 + y) * 16, blk[16 * y + x])
    return c


# ---- places on the two worlds
ENTER_X, ENTER_Y = 0xA80A, 0xA832       # E (Enter): 32 places then 8 dungeons, x / y
MAIN_OUT_XY = {"2A": 0x8947, "2B": 0x893D}      # main.out's copy, Enter's first test ($8916)
SHRINE_X, SHRINE_Y = 0xADA8, 0xADB0     # E (the mantra), SHRINE $ACB4/$ACBC the same
MOONSTONE_X, MOONSTONE_Y = 0x1280, 0x1288       # (BLANK.)ROSTER: the moonstones, where the gates show
REAGENT_X, REAGENT_Y, REAGENT = 0xAB72, 0xAB75, 0xAB78  # S (Search), at hour 0
ARARAT = 24                             # the one place Enter finds in the Underworld
# E $A85A: the tile under the party says what it is (its words list $A9BD)
KIND = {0x10: "hut", 0x11: "house", 0x12: "keep", 0x13: "village", 0x14: "towne", 0x15: "castle",
        0x16: "cave", 0x17: "mine", 0x18: "dungeon", 0x19: "shrine", 0x1A: "ruins",
        0x1B: "lighthouse", 0x3E: "castle", 0x39: "palace"}
VIRTUES = ["Honesty", "Compassion", "Valor", "Justice", "Sacrifice", "Honor", "Spirituality",
           "Humility"]


def table(tag, name, at, n):
    raw = disk(tag).file(name)[0]
    base = raw[0] | raw[1] << 8
    return list(raw[2 + at - base:2 + at - base + n])


def world_tile(d, x, y):
    return d.sector(20 + y // 16, x // 16)[16 * (y % 16) + x % 16]


def places(tag):
    """[(key, x, y, name, kind)] on disk tag's world, each checked against
    the tile there."""
    d = disk(tag)
    xs, ys = table("2A", "E", ENTER_X, 40), table("2A", "E", ENTER_Y, 40)
    for t in ("2A", "2B"):
        o = MAIN_OUT_XY[t]
        assert table(t, "MAIN.OUT", o, 40) == xs and table(t, "MAIN.OUT", o + 40, 40) == ys, t
    out = []
    for n in range(32):
        if (n == ARARAT) == (tag == "2B"):
            t = world_tile(d, xs[n], ys[n])
            assert t in KIND, (PLACES[n][0], hex(t))
            out.append((n + 1, xs[n], ys[n], PLACES[n][0], KIND[t]))
    for n, name in enumerate(DUNGEONS):
        x, y = xs[32 + n], ys[32 + n]
        t = world_tile(d, x, y)
        if 0x16 <= t <= 0x18:                   # (Doom only below)
            out.append((f"D{n + 1}", x, y, name + (", level 8" if tag == "2B" and name != "Doom" else ""),
                        KIND[t]))
    if tag == "2A":
        sx, sy = table("2A", "E", SHRINE_X, 8), table("2A", "E", SHRINE_Y, 8)
        assert table("2A", "SHRINE", 0xACB4, 8) == sx and table("2A", "SHRINE", 0xACBC, 8) == sy
        for v in range(8):
            if (sx[v], sy[v]) != (0, 0):        # Spirituality has no square
                assert world_tile(d, sx[v], sy[v]) == 0x19
                out.append((f"S{v + 1}", sx[v], sy[v], f"shrine of {VIRTUES[v]}", "shrine"))
        codex = [(i % 256, i // 256) for i in range(65536) if world_tile(d, i % 256, i // 256) == 0x11]
        assert len(codex) == 1
        out.append(("CX", *codex[0], "Shrine of the Codex", "shrine"))
        # as a new game starts them: the template character creation copies
        # (1A's BLANK.ROSTER; a played 2A's ROSTER holds where they are now)
        mx, my = table("1A", "BLANK.ROSTER", MOONSTONE_X, 8), table("1A", "BLANK.ROSTER", MOONSTONE_Y, 8)
        for v in range(8):
            assert world_tile(d, mx[v], my[v]) == 0x05
            out.append((f"M{v + 1}", mx[v], my[v], f"moongate, moonstone of {VIRTUES[v]} (at the start)",
                        "moongate"))
        rx, ry, rk = (table("2A", "S", a, 3) for a in (REAGENT_X, REAGENT_Y, REAGENT))
        for v in range(3):
            out.append((f"R{v + 1}", rx[v], ry[v],
                        {6: "nightshade", 7: "mandrake root"}[rk[v]] + " (Search at midnight)", "reagent"))
        out.append(("F", 54, 138, "the falls: down into the Underworld here", "falls"))
    else:
        out.append(("W", 34, 18, "the whirlpool comes out here", "whirlpool"))
    return out


PLACES_NOTE = {"2A": ("places 1-32 and dungeons D1-D8: Enter's tables (E $A80A/$A832, main.out's copy); "
               "shrines S1-S8: E $ADA8/$ADB0 (Spirituality has no square); CX: the Codex's tile ($11); "
               "M1-M8: the moonstones at the start (ROSTER $1280/$1288; gates show there 8pm-5am); "
               "R1-R3: Search's reagent spots (S $AB72); F: the falls (main.out $9741); "
               "the whirlpool lands in the Underworld"),
               "2B": ("Ararat (25) and dungeons D1-D8: Enter's tables (E $A80A/$A832, main.out's copy; "
                      "a dungeon entered from here starts at level 8, E $A7CF, Doom at 1); "
                      "W: the whirlpool's landing (main.out $9CBE)")}


def marked_world(tag, tiles, title, out, png):
    c = world(disk(tag), tiles, title)
    here = places(tag)

    def write(c_, x, y, text, colour):
        label(c_, x, y, text, colour)
    mark_places(c, here, 16, write, 0, 12)
    with_legend(c, here, write).write(os.path.join(out, png))
    write_places(os.path.join(out, png.replace(".png", "_places.txt")), title + ": " + PLACES_NOTE[tag], here)


def britannia(tiles, out):
    marked_world("2A", tiles, "Britannia (disk 2A, tracks 20-35)", out, "britannia.png")


def underworld(tiles, out):
    marked_world("2B", tiles, "the Underworld (disk 2B, tracks 20-35)", out, "underworld.png")


def town_map(d, n):
    t, s = 32 + n // 4, (n * 4) & 15
    return [d.sector(t, s + i) for i in range(4)]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def town_names():
    """{(disk tag, map): (place, floor or None)}, from the game's tables."""
    entries = []
    for tag in TOWN_DISKS:
        raw, _ = disk(tag).file("MAIN.TWN")
        assert raw[:2] == b"\x00\x80", tag
        entries.append(raw[2 + FIRST_MAPS - 0x8000:][:32])
    assert len(set(entries)) == 1, "main.twn's place table differs between the disks"
    known = bytes(b & 0x7F for b in disk("2A").file("E")[0]).decode("latin-1")
    at = [known.find(name.upper()) for name, has in PLACES if has]
    assert -1 not in at and at == sorted(at), "E's names are not PLACES' order"
    names = {}
    for g, tag in enumerate(TOWN_DISKS):
        maps = [b"".join(town_map(disk(tag), n)) for n in range(16)]
        ground = [entries[0][8 * g + i] - 1 for i in range(8)]
        assert all(m >> 4 == g for m in ground), (tag, ground)
        ground = [m & 15 for m in ground]
        low = [m - (LADDER_DOWN in maps[m]) for m in ground]
        assert low[0] == 0 and all(a < b for a, b in zip(low, low[1:])), (tag, low)
        for i in range(8):
            top = (low[i + 1] if i < 7 else 16) - 1
            for n in range(low[i], top + 1):
                assert n == top or LADDER_UP in maps[n], (tag, n)
                floor = FLOORS[n - ground[i]] if top > low[i] else None
                names[tag, n] = (PLACES[8 * g + i][0], floor)
    return names


def towns(tiles, out):
    names = town_names()
    os.makedirs(os.path.join(out, "towns"), exist_ok=True)
    for f in os.listdir(os.path.join(out, "towns")):
        if f.endswith(".png"):
            os.remove(os.path.join(out, "towns", f))
    index = []
    for tag, kind in TOWN_DISKS.items():
        d = disk(tag)
        for n in range(16):
            t, s = 32 + n // 4, (n * 4) & 15
            blocks = town_map(d, n)
            place, floor = names[tag, n]
            title = place + (f", {floor}" if floor else "")
            index.append(f"{tag} map {n:2d}  track {t}, sectors {s:2d}-{s + 3:2d}  {title}")
            c = Canvas(32 * 16, 32 * 16 + 24, 0)
            label(c, 2, 2, title)
            label(c, 2, 12, f"{kind} disk ({tag}), map {n}: track {t}, sectors {s}-{s + 3}", 15)
            for i, blk in enumerate(blocks):
                ox, oy = (i & 1) * 16, (i >> 1) * 16
                for y in range(16):
                    for x in range(16):
                        tiles.draw(c, (ox + x) * 16, 24 + (oy + y) * 16, blk[16 * y + x])
            c.write(os.path.join(out, "towns", f"{tag.lower()}_{n:02d}_{slug(title)}.png"))
    with open(os.path.join(out, "towns.txt"), "w") as fh:
        fh.write("\n".join(index) + "\n")


LEGEND = {0x00: "", 0x04: "", 0x08: "CE", 0x10: "U", 0x20: "D", 0x30: "UD", 0x40: "CH", 0x41: "CH",
          0x42: "CH", 0x44: "CH", 0x60: "HO", 0x61: "HO", 0x62: "BT", 0x68: "CE", 0x69: "CE",
          0x70: "CH", 0x80: "PF", 0x81: "SF", 0x82: "FF", 0x83: "EF", 0xC0: "", 0xD0: "SD", 0xE0: "DR"}
CELL = 40


def square(v):
    if v == 0xB0 or v == 0xC0:
        return None, 11
    if 0xB1 <= v <= 0xBF:
        return "TX", 15
    if v & 0xF0 == 0x50:
        return "FO", 3
    if v & 0xF0 == 0xF0:
        return f"R{v & 15}", 1
    return LEGEND.get(v, f"{v:02X}"), {0x10: 7, 0x20: 7, 0x30: 7, 0xE0: 9, 0xD0: 4}.get(v, 10)


def dungeons(tiles, out):
    d = disk("1B")
    for n, name in enumerate(DUNGEONS):
        data = d.sector(35, 2 * n) + d.sector(35, 2 * n + 1)
        one = 8 * CELL + 2
        c = Canvas(4 * (one + 12) + 12, 2 * (one + 24) + 42, 0)
        label(c, 12, 4, f"{name} (disk 1B, track 35, sectors {2 * n}-{2 * n + 1}) -- the U5 Remastered kit's legend:")
        label(c, 12, 16, "grey wall, U/D/UD ladders, DR door, SD secret door, CH chest, FO fountain, "
                         "Rn room, TX wall with text, HO hole, CE ceiling hole, xF field, BT bomb trap")
        for L in range(8):
            X0, Y0 = 12 + (L % 4) * (one + 12), 32 + (L // 4) * (one + 24)
            label(c, X0, Y0, f"level {L + 1}")
            for y in range(8):
                for x in range(8):
                    v = data[L * 64 + y * 8 + x]
                    text, col = square(v)
                    X, Y = X0 + 1 + x * CELL, Y0 + 12 + y * CELL
                    c.fill(X, Y, CELL, CELL, 11 if text is None else 0)
                    c.frame(X, Y, CELL, CELL, 6)
                    if text:
                        label(c, X + (CELL - 8 * len(text)) // 2, Y + CELL // 2 - 4, text, col)
        c.write(os.path.join(out, "dungeons", f"{n + 1}_{name.lower()}.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u5"))
    ap.add_argument("what", nargs="*", default=["britannia", "underworld", "towns", "dungeons"])
    a = ap.parse_args()
    tiles = Tiles(disk("1A"))
    os.makedirs(a.out, exist_ok=True)
    for w in a.what:
        print(w, flush=True)
        globals()[w](tiles, a.out)
    print("written to", a.out)


if __name__ == "__main__":
    main()
