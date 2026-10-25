#!/usr/bin/env python3
"""Ultima III's maps as PNGs, from the units as the cart's build stores them.

    python -m ultima.maps.u3maps [--out build/maps/u3] [what ...]

what: sosaria, ambrosia, towns, dungeons, combat (default: all).  The units
come from ultima/games/u3/build.py (parts(): every catalog entry as flashed, Gold's
changes included).  Graphics: SHPS, the 64 tiles of 16 x 16 (Gold's
bitmap-order permutation undone, gold.shps), coloured by UPDT's table (one
screen-RAM byte a tile, as the game's view: e.g. water $60, grass $50, towns
$10); map bytes are tile x 4.

- sosaria.png, ambrosia.png: SOSA and MAPZ, 64 x 64; the people/monsters of
  SOSM and MONZ drawn on top (ULT3's table at $4F00: tile, x at +$40, y at
  +$60); on Sosaria the 19 entrances (ULT3's table $77E5/$77F8: entry n is
  map letter A + n) framed and lettered, named in a legend on the right
  (the towns by their signs, as dialogue/u3talk.py reads them), with the
  moon gate (MG) and the Great Snake (SN) by their tiles; on Ambrosia its
  four shrines by their tile.  sosaria_places.txt / ambrosia_places.txt
  list them with the tile under each (town, castle, dungeon).
- towns/mapX_<place>.png: MAPA-MAPL, 64 x 64, their MONx people drawn on.
- dungeons/mapX_<dungeon>.png: MAPM-MAPS, eight 16 x 16 levels as a plan,
  the squares by their values as DNGM shows them ($80 wall, $C0 door, $A0
  secret door, $10 ladder up? $20 down? $30 both? -- the kinds inferred from
  their counts, as in u3dngm.s, not traced), other values printed in hex.
  Each dungeon is named by its first misty writing (TLKx entry 1, checked
  here), the Dungeon of Time also by the Time Lord on its level 8; the
  Dungeon of Snake, whose first writing is "CLUES TO FOLLOW!", is the one of
  the seven left over -- its name is not in the game's data.
- combat/conX_<where>.png: the CONx combat maps, 11 x 11, their bytes tile
  x 2 (not x 4).  ULT3 $7E1C patches the letter into "L CON@" ($7EA2):
  C in a dungeon ($62 = 1, as Enter sets it at $58C3); with the party on a
  frigate ($0E = tile 11 x 2)
  S against a pirate, Q against tiles 11-14 (frigate to man-o-war), R
  against anything else; on land A against a pirate (it fights as tile 23,
  a thief) and M against tiles 11-14; otherwise by the terrain under the
  party ($09, tile x 2, as Enter at $58B0 reads it): B brush, F forest, C
  floor, force field or lava, G grass and the rest.  The roles of $0E and
  $4E (the monster's tile x 2) are inferred from the values compared.
"""
import argparse
import importlib.util
import os
import re

from ultima.maps.mapkit import Canvas, mark_places, rgb, with_legend, wrap, write_places
from ultima import paths

KINDS = {5: "dungeon", 6: "town", 7: "castle"}

# MAPM-MAPS: the dungeon's name and the words its first misty writing has
DUNGEONS = {"M": ("Dungeon of Doom", "TO YOUR DOOM"),
            "N": ("Dungeon of Fire", "FIRES OF HELL"),
            "O": ("Dungeon of Time", "TIME AWAITS"),
            "P": ("Dungeon of Snake", "CLUES TO FOLLOW"),
            "Q": ("Perinian Depths", "PERINIAN DEPTHS"),
            "R": ("Mines of Morinia", "MINES OF MORINIA"),
            "S": ("Dardin's Pit", "DARDIN'S PIT")}
TIME_LORD = 1                                   # a dungeon square: the Time Lord (ULT3 $8EA0)

# CONx: where the party fights on it (ULT3 $7E1C)
COMBAT = {"A": "pirates ashore", "B": "brush", "C": "dungeon or floor",
          "F": "forest", "G": "grass", "M": "sea monster ashore",
          "Q": "ship vs sea monster", "R": "ship vs land monster",
          "S": "ship vs pirates"}


def build_units():
    spec = importlib.util.find_spec("ultima.games.u3.build")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parts()["unit_data"]


class Tiles:
    def __init__(self, units):
        gold = bytes(units["SHPS"])
        shps = bytearray(len(gold))             # gold.shps() undone
        for r in range(16):
            for t in range(64):
                for b in range(2):
                    shps[r * 0x80 + t * 2 + b] = gold[(r >= 8) * 0x400 + t * 16 + b * 8 + (r & 7)]
        pattern = bytes.fromhex("6050505080801010")
        for name in ("UPDT", "BOOT", "DDRW"):
            i = bytes(units[name]).find(pattern)
            if i >= 0:
                colours = bytes(units[name])[i:i + 64]
                break
        else:
            raise SystemExit("U3: no tile colour table found")
        self.rows = []
        for t in range(64):
            fg, bg = bytes(rgb(colours[t] >> 4)), bytes(rgb(colours[t] & 15))
            rows = []
            for r in range(16):
                line = b""
                for b in range(2):
                    v = shps[r * 0x80 + t * 2 + b]
                    line += b"".join(fg if v & (0x80 >> k) else bg for k in range(8))
                rows.append(line)
            self.rows.append(rows)
        text = bytes(units["TEXT"])             # Gold's order: 8 bytes a character
        self.font = text

    def draw(self, c, x, y, value):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[(value >> 2) & 63][r]

    def text(self, c, x, y, s, fg=1):
        c.text(x, y, s.upper(), self.font, fg, code=lambda ch: ord(ch) & 0x7F)


def grid(tiles, data, w, h, top=0):
    c = Canvas(w * 16, h * 16 + top, 0)
    for y in range(h):
        for x in range(w):
            tiles.draw(c, 16 * x, top + 16 * y, data[y * w + x])
    return c


def people(c, tiles, mon, top=0):
    for i in range(32):
        t, x, y = mon[i], mon[0x40 + i], mon[0x60 + i]
        if t:
            tiles.draw(c, 16 * (x & 63), top + 16 * (y & 63), t)


def entrances(units):
    """[(letter, x, y)]: ULT3 at $5000, its table $77E5 (x) / $77F8 (y)."""
    u = bytes(units["ULT3"])
    xs, ys = u[0x77E5 - 0x5000:0x77E5 - 0x5000 + 19], u[0x77F8 - 0x5000:0x77F8 - 0x5000 + 19]
    return [(chr(65 + i), xs[i], ys[i]) for i in range(19)]


def place_names():
    """MAPA-MAPL as the dialogue extractor names them (from the towns' own
    signs, dialogue/u3talk.py PLACES), the comment after a name left out;
    MAPM-MAPS from DUNGEONS."""
    from ultima.dialogue import u3talk
    names = {k: v[0].split(" (")[0] for k, v in u3talk.PLACES.items()}
    return names | {k: v[0] for k, v in DUNGEONS.items()}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower().replace("'", "")).strip("_")


def fresh(path):
    """path as an empty directory of PNGs: the ones of a run before go."""
    os.makedirs(path, exist_ok=True)
    for f in os.listdir(path):
        if f.endswith(".png"):
            os.remove(os.path.join(path, f))


def tile_places(world, tiles_named):
    """[(x, y, tile)] of every square whose tile is one of tiles_named."""
    return [(i % 64, i // 64, b >> 2) for i, b in enumerate(world) if b >> 2 in tiles_named]


# tiles found on the maps by kind (their names are Look's, ULT3 $8796)
MOON_GATE, SNAKE_1, SNAKE_2, SHRINE = 34, 58, 59, 62


def outdoors(units, tiles, out, name, mapname, monname, places, header):
    world = bytes(units[mapname])[:4096]
    c = grid(tiles, world, 64, 64, top=12)
    tiles.text(c, 2, 2, f"{name} ({mapname}, {monname} drawn on)")
    people(c, tiles, bytes(units[monname]), top=12)
    mark_places(c, places, 16, tiles.text, 0, 12)
    with_legend(c, places, tiles.text).write(os.path.join(out, f"{name.lower()}.png"))
    write_places(os.path.join(out, f"{name.lower()}_places.txt"), header, places)


def sosaria(units, tiles, out):
    world = bytes(units["SOSA"])[:4096]
    names = place_names()
    places = []
    for letter, x, y in entrances(units):
        kind = KINDS.get(world[y * 64 + x] >> 2, f"tile {world[y * 64 + x] >> 2}")
        places.append((letter, x, y, names[letter], kind))
    snake = tile_places(world, (SNAKE_1, SNAKE_2))
    places += [("MG", x, y, "moon gate", "moon gate") for x, y, _t in tile_places(world, (MOON_GATE,))]
    places += [("SN", snake[0][0], snake[0][1], "the Great Snake", "snake")]
    outdoors(units, tiles, out, "Sosaria", "SOSA", "SOSM", places,
             "Sosaria's places: A-S the entrances (ULT3 $77E5/$77F8: entry n loads MAP<A+n>; "
             "the towns' names from their signs, dialogue/u3talk.py), MG and SN by their tiles")


def ambrosia(units, tiles, out):
    world = bytes(units["MAPZ"])[:4096]
    places = [(i + 1, x, y, "shrine", "shrine") for i, (x, y, _t) in enumerate(tile_places(world, (SHRINE,)))]
    outdoors(units, tiles, out, "Ambrosia", "MAPZ", "MONZ", places,
             "Ambrosia's shrines, by their tile (which shrine is which was not looked into)")


def towns(units, tiles, out):
    places = {letter: (x, y) for letter, x, y in entrances(units)}
    names = place_names()
    fresh(os.path.join(out, "towns"))
    for i in range(12):
        letter = chr(65 + i)
        x, y = places[letter]
        c = grid(tiles, bytes(units[f"MAP{letter}"])[:4096], 64, 64, top=12)
        tiles.text(c, 2, 2, f"MAP{letter}: {names[letter]}, at x {x}, y {y} on Sosaria (MON{letter} drawn on)")
        people(c, tiles, bytes(units[f"MON{letter}"]), top=12)
        c.write(os.path.join(out, "towns", f"map{letter.lower()}_{slug(names[letter])}.png"))


SQ = {0x80: ("", 11), 0xC0: ("DR", 9), 0xA0: ("SD", 4), 0x10: ("U", 7), 0x20: ("D", 7),
      0x30: ("UD", 7), 0x00: ("", 0)}
CELL = 28


def first_writing(units, letter):
    """TLKx entry 1, the misty writing of level 1, as one line."""
    entry = bytes(units[f"TLK{letter}"]).split(b"\0")[1]
    return " ".join("".join(chr(b & 0x7F) for b in s) for s in entry.split(b"\xff") if s)


def dungeons(units, tiles, out):
    places = {letter: (x, y) for letter, x, y in entrances(units)}
    fresh(os.path.join(out, "dungeons"))
    for i in range(7):
        letter = chr(65 + 12 + i)
        data = bytes(units[f"MAP{letter}"])
        name, words = DUNGEONS[letter]
        writing = first_writing(units, letter)
        assert words in writing, f"MAP{letter}: its first writing is {writing!r}, not {words!r}"
        assert (TIME_LORD in data[7 * 256:8 * 256]) == (letter == "O"), f"MAP{letter}: the Time Lord"
        one = 16 * CELL + 2
        c = Canvas(4 * (one + 10) + 10, 2 * (one + 24) + 34, 0)
        x, y = places[letter]
        tiles.text(c, 10, 4, f"MAP{letter}: {name}, at x {x}, y {y} on Sosaria -- grey wall, "
                             f"DR door, SD secret door, U/D/UD ladders (inferred), other values hex")
        for L in range(8):
            X0, Y0 = 10 + (L % 4) * (one + 10), 30 + (L // 4) * (one + 24)
            tiles.text(c, X0, Y0, f"LEVEL {L + 1}")
            for yy in range(16):
                for xx in range(16):
                    v = data[L * 256 + yy * 16 + xx]
                    label, col = SQ.get(v, (f"{v:02X}", 10))
                    X, Y = X0 + 1 + xx * CELL, Y0 + 12 + yy * CELL
                    c.fill(X, Y, CELL, CELL, 11 if v == 0x80 else 0)
                    c.frame(X, Y, CELL, CELL, 6)
                    if label:
                        tiles.text(c, X + (CELL - 8 * len(label)) // 2, Y + CELL // 2 - 4, label, col)
        c.write(os.path.join(out, "dungeons", f"map{letter.lower()}_{slug(name)}.png"))


def combat(units, tiles, out):
    fresh(os.path.join(out, "combat"))
    assert sorted(n for n in units if n.startswith("CON")) == [f"CON{k}" for k in COMBAT]
    for k, where in COMBAT.items():
        header = wrap(f"CON{k}: {where}", 11 * 16 - 4)
        top = 4 + 10 * len(header)
        c = grid(tiles, [b << 1 for b in units[f"CON{k}"][:121]], 11, 11, top=top)
        for n, line in enumerate(header):
            tiles.text(c, 2, 2 + 10 * n, line)
        c.write(os.path.join(out, "combat", f"con{k.lower()}_{slug(where)}.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u3"))
    ap.add_argument("what", nargs="*", default=["sosaria", "ambrosia", "towns", "dungeons", "combat"])
    a = ap.parse_args()
    units = build_units()
    tiles = Tiles(units)
    os.makedirs(a.out, exist_ok=True)
    for w in a.what:
        print(w, flush=True)
        globals()[w](units, tiles, a.out)
    print("written to", a.out)


if __name__ == "__main__":
    main()
