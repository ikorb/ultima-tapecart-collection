#!/usr/bin/env python3
"""Ultima II's maps as PNGs, from its disks (the cart stores the files as
they are; the MOB/MON files the game writes later are in the save log).

    python -m ultima.maps.u2maps [--out build/maps/u2]

Every MAP file of both disks -- the Player disk's are Earth's, the Program +
Galactic disk's the planets' (ULTIMA picks the disk by $8E37, the planet
number) -- as build/maps/u2/<disk>_map_NN.png.  A name is MAP + two digits,
$8E13 then $8E14 (ULTIMA $689B): the map, and the kind of place, 0 the
surface, 1-3 towns and castles, 4 and 5 the towers and dungeons.

The game's view is character mode (SUBS $4A83): a tile t is characters 4t to
4t+3 of SHAPES -- left column t*32, right t*32+16, 16 rows each -- in hires,
one colour a tile (SUBS' table $4AC9) on the view's background ($D021 =
$0D, light green: the raster split's table $47C8).  A map byte is the tile
x 4.  The monsters of the matching MON file (32 of them: x at +0, y at +$20,
the tile at +$60, map bytes) are drawn on.

Every map is named by what it is: build/maps/u2/<disk>_map_NN_<where>_<kind>.png,
the where from the time-door sign's eras (Earth) or STARS' planets
(dialogue/u2talk.py), the kind from Enter (below).

Enter (ULTIMA $75D3: on the surface, on foot) goes by the tile under the
party alone, never its position: tile 5 a village -> MAP n1, 6 a town ->
n2, 8 a castle -> n3, 7 a tower -> n4, 9 a dungeon -> n5, n the surface's
own first digit ($8E13, unchanged); tile 10 is a sign ("ANOS: <era>").  A
surface map has every such square framed, keyed by the digit of the map it
leads to (S the sign), with a legend.  Earth's time door is put on the map
at run time, every 8 turns on the next of four squares an era (ULTIMA
$6CA5: T1-T4); door k leads to era k, or k + 1 if k is not below the
current era ($6C08), onto that era's door square k.

Towers and dungeons (kind 4 and 5) are not tiles: 16 levels of 16 x 16,
each square a value (DNGNDRAW $9680 reads level x 256 + y x 16 + x),
drawn as plans: $80 wall (grey), $10 ladder up (Klimb, $79F5) U, $20 down
(Descend, $75BE) D, $30 both UD, $40 chest (Get, $78C9) CH, $C0 door DR
(drawn on the wall face, $979C; Advance passes, Retreat does not), $E0 DX:
drawn and passed as a door, and Descend works on it too (bit 5) -- what
the authors meant by it is not known.  The party enters at (5, 5) on
level 1 (framed).  In a dungeon Klimb goes to the level before and
Descend the next; in a tower the other way round ($79FB, $75C4).  Monsters
(the low three bits) and traps (rolled on each step, more likely deeper)
are not in the files.
"""
import argparse
import os

from ultima.disks.d64 import D64
from ultima.maps.mapkit import Canvas, label, mark_places, rgb, with_legend, wrap, write_places

from ultima.dialogue import u2talk
from ultima import paths

DISKS = {"galactic": "u2a", "player": "u2b"}
BG = 0x0D
COLOURS_AT = 0x4AC9 - 0x4000            # SUBS


class Tiles:
    def __init__(self, shapes, colours):
        bg = bytes(rgb(BG))
        self.rows = []
        for t in range(64):
            fg = bytes(rgb(colours[t]))
            rows = []
            for r in range(16):
                line = b""
                for b in range(2):
                    v = shapes[t * 32 + b * 16 + r]
                    line += b"".join(fg if v & (0x80 >> k) else bg for k in range(8))
                rows.append(line)
            self.rows.append(rows)

    def draw(self, c, x, y, value):
        for r in range(16):
            o = 3 * ((y + r) * c.w + x)
            c.px[o:o + 48] = self.rows[(value >> 2) & 63][r]


ENTER = {5: ("village", 1), 6: ("town", 2), 8: ("castle", 3), 7: ("tower", 4), 9: ("dungeon", 5),
         10: ("sign", None)}                    # ULTIMA $75D3, by tile
KIND = {0: "surface", 1: "village", 2: "town", 3: "castle", 4: "tower", 5: "dungeon"}
MARK = 1                                        # white
DOORS, ULTIMA_ADDR = 0x6CA5, 0x5000             # Earth's time-door squares, 4 an era


def write(c, x, y, text, colour):
    label(c, x, y, text, colour)


def where(tag, nn):
    first = int(nn[0])
    return (f"Earth, {u2talk.ERAS[first]}" if tag == "player" else u2talk.PLANETS[first])


def entrances(data, nn):
    """[(key, x, y, name, kind)] of every square Enter does something on."""
    out = []
    for i, b in enumerate(data[:4096]):
        if b >> 2 in ENTER:
            kind, digit = ENTER[b >> 2]
            target = f"MAP {nn[0]}{digit}" if digit is not None else None
            out.append((digit if digit is not None else "S", i % 64, i // 64,
                        f"{kind}: {target}" if target else "sign (Enter reads the era)", kind))
    return out


def time_doors(ultima, era):
    t = ultima[DOORS - ULTIMA_ADDR + 8 * era:DOORS - ULTIMA_ADDR + 8 * era + 8]
    out = []
    for k in range(4):
        to = k if k < era else k + 1
        out.append((f"T{k + 1}", t[2 * k], t[2 * k + 1], f"time door (at times) to {u2talk.ERAS[to]}",
                    "time door"))
    return out


def tile_map(tiles, data, mon, title, places):
    c = Canvas(64 * 16, 64 * 16 + 12, 0)
    label(c, 2, 2, title)
    for y in range(64):
        for x in range(64):
            tiles.draw(c, 16 * x, 12 + 16 * y, data[y * 64 + x])
    if mon:
        for i in range(32):
            x, y, t = mon[i], mon[0x20 + i], mon[0x60 + i]
            if t and x < 64 and y < 64:
                tiles.draw(c, 16 * x, 12 + 16 * y, t)
    if places:
        mark_places(c, places, 16, write, 0, 12, colour=MARK)      # (yellow is lost on the light green)
        c = with_legend(c, places, write, key_colour=MARK)
    return c


CELL = 24
SQUARES = {0x10: ("U", 7), 0x20: ("D", 7), 0x30: ("UD", 7), 0x40: ("CH", 8), 0xC0: ("DR", 9),
           0xE0: ("DX", 4)}
PLAN_LEGEND = ("grey wall ($80), U ladder up ($10, Klimb), D ladder down ($20, Descend), UD both, "
               "CH chest ($40), DR door ($C0), DX door that Descend also works on ($E0, meaning not "
               "known); the party enters at 5,5 on level 1 (framed). In a dungeon Klimb goes to the "
               "level before, Descend to the next; in a tower the other way round.")


def plan(data, title):
    one = 16 * CELL + 2
    w = 4 * (one + 10) + 10
    head = wrap(title, w - 20) + wrap(PLAN_LEGEND, w - 20)
    top = 4 + 12 * len(head) + 6
    c = Canvas(w, 4 * (one + 22) + top, 0)
    for i, line in enumerate(head):
        label(c, 10, 4 + 12 * i, line, 1 if i < len(wrap(title, w - 20)) else 15)
    for L in range(16):
        X0, Y0 = 10 + (L % 4) * (one + 10), top + (L // 4) * (one + 22)
        label(c, X0, Y0, f"level {L + 1}")
        for y in range(16):
            for x in range(16):
                v = data[L * 256 + y * 16 + x]
                X, Y = X0 + 1 + x * CELL, Y0 + 12 + y * CELL
                c.fill(X, Y, CELL, CELL, 11 if v == 0x80 else 0)
                c.frame(X, Y, CELL, CELL, 6)
                if v not in (0, 0x80):
                    text, col = SQUARES.get(v, (f"{v:02X}", 2))
                    label(c, X + (CELL - 8 * len(text)) // 2, Y + 8, text, col)
        if L == 0:
            c.frame(X0 + 1 + 5 * CELL, Y0 + 12 + 5 * CELL, CELL, CELL, 1, 2)
    return c


def slug(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s.lower().replace(".", "")).strip("_").replace("__", "_")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "maps", "u2"))
    a = ap.parse_args()
    disks = {k: D64(paths.disk(v)) for k, v in DISKS.items()}
    a_disk = disks["galactic"]
    subs = a_disk.payload("SUBS")[0]
    ultima = a_disk.file("ULTIMA")[0][2:]
    assert list(ultima[DOORS - ULTIMA_ADDR:DOORS - ULTIMA_ADDR + 8]) == [29, 56, 31, 56, 33, 56, 35, 56]
    tiles = Tiles(a_disk.payload("SHAPES")[0], subs[COLOURS_AT:COLOURS_AT + 64])
    os.makedirs(a.out, exist_ok=True)
    for f in os.listdir(a.out):
        if f.endswith(".png"):
            os.remove(os.path.join(a.out, f))
    index = []
    for tag, d in disks.items():
        names = [e[0] for e in d.directory()]
        files = {n: d.payload(n)[0] for n in names if n.startswith("MAP ")}
        for name in sorted(files):
            data, nn = files[name], name[4:]
            kind = int(nn[1])
            place = f"{where(tag, nn)}, the {KIND[kind]}" if kind else f"{where(tag, nn)}, the surface"
            same = [n for n in sorted(files) if n != name and files[n] == data]
            title = f"{name} ({tag} disk): {place}" + (f" -- the same file as {', '.join(same)}" if same else "")
            if kind in (4, 5):
                c = plan(data, title)
            else:
                mon = d.payload("MON " + nn)[0] if "MON " + nn in names else None
                places = []
                if kind == 0:
                    places = entrances(data, nn)
                    if tag == "player":
                        places += time_doors(ultima, int(nn[0]))
                    write_places(os.path.join(a.out, f"{tag}_map_{nn}_places.txt"),
                                 f"{name}: {place} -- what Enter does on each square (ULTIMA $75D3)"
                                 + ("; T1-T4 the time door's squares (ULTIMA $6CA5)" if tag == "player" else ""),
                                 places) if places else None
                c = tile_map(tiles, data, mon, title + (f", MON {nn} drawn on" if mon else ""), places)
            out = f"{tag}_map_{nn}_{slug(place)}.png"
            c.write(os.path.join(a.out, out))
            index.append(f"{out:52s} {title}")
            print(tag, name, flush=True)
    with open(os.path.join(a.out, "maps.txt"), "w") as fh:
        fh.write("\n".join(index) + "\n")
    print("written to", a.out)


if __name__ == "__main__":
    main()
