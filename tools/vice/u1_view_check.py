#!/usr/bin/env python3
"""Ultima I: the outdoor view drawn only where it changed (u1view.s), in VICE.

    python -m tools.vice.u1_view_check

Makes a character as u1_town_check does, with hit points raised and the
page's X poked (pw_on), and plays: steps, idle polls, Ztats, Inform, Ready,
an attack, F1, F7 to a coast and beside a castle (animated tiles), a horse
and a frigate boarded (B) and left, a step off a land's edge, Britain, a
dungeon and Lord British's castle entered and left, and a death.  After
each, two draws are stopped just before their flip (u1view.s's view_flip)
and the bitmap drawn ($5C) is checked against the record
of the cells (u1view.s, $3F40/$5F40):

- the record holds ($3FEB/$5FEB = $80);
- the tile the record names is the map's ($6400; off the map, water; a
  monster, either of its frames; the party's tile in the middle), or $FF
  where the map's is one ST animates (0, 4, 6, 12);
- every cell's 32 bitmap bytes are that tile as ST's tile data has it now
  (the animation steps only at a draw's start), and its four colour bytes
  that tile's colour ($1500).

So the bitmap shown next is the view as ST's own renderer draws it.  Each
draw's cycles (the stopwatch from one draw's end to the next) are printed
too.  Screenshots in build/u1_view_*.png (Ztats and the others as they are
shown).  About fifteen minutes.
"""
import os
import re
import sys
import time
from pathlib import Path

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice import menu_check
from tools.vice.u1_powers_check import syms, BRITAIN, PERINIA, CASTLE, LAND, HITS, OVERLAY
from tools.vice.u1_town_check import in_play, new_game, pos
from tools.vice.vice_mon import Vice
from ultima.maps import u1maps

VEHICLE = 0x81F1
ANIMATED = {0, 4, 6, 12}        # recorded as $FF


def main():
    s = syms()
    view = {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u1view.bin.sym").read_text())}
    DRAWN = view["view_flip"]           # u1view.s: JSR $1700, after the view is drawn
    worlds = u1maps.continents()
    places = {p[0]: p for p in u1maps.places()}
    ou = u1maps.prg("ou.prg")
    image = menu_check.with_autokey(1)
    for _ in range(3):
        v = Vice(image, port=6536)
        new_game(v)
        if in_play(v, worlds[0]):
            break
        print("not in play after the menus, again")
        v.quit()
    else:
        raise SystemExit("could not start a game")
    bad = 0
    checks = 0

    def stopped(timeout=20):
        seen, t = "", time.time()
        while "Stop on" not in seen and time.time() - t < timeout:
            seen += v._drain(0.2)
        return "Stop on" in seen

    def clock():
        out = v.cmd("r", wait=0.3)
        return int(re.search(r"^\.;\w{4}.*?\s(\d+)\s*$", out, re.M).group(1))

    def check_draw():
        """The bitmap just drawn against the record and the map."""
        nonlocal bad, checks
        zp = v.mem(0x00, 0x7F)
        hidden = zp[0x5C]
        bm = 0x4000 if hidden else 0x2000
        scr = 0x6000 if hidden else 0x0400
        rec = 0x5F40 if hidden else 0x3F40
        record = v.mem(rec, rec + 171)
        tiles = v.mem(0x0C00, 0x13FF)
        colour = v.mem(0x1500, 0x153F)
        world = v.mem(0x6400, 0x73FF)
        party = v.mem(0x1639, 0x1639)[0] >> 1
        screen = v.mem(scr + 40, scr + 40 * 19 - 1)
        rows = [v.mem(bm + 320 * r + 8, bm + 320 * r + 8 + 303) for r in range(1, 19)]
        px, py = zp[0x20], zp[0x21]
        errs = []
        if record[171] != 0x80:
            errs.append(f"record's byte ${record[171]:02x}")
        for ty in range(9):
            for tx in range(19):
                c = record[19 * ty + tx]
                x, y = px - 9 + tx, (py - 4 + ty) & 0xFF
                if (tx, ty) == (9, 4):
                    want = {party}
                elif 0 <= x < 64 and y < 64:
                    b = world[64 * y + x] & 0x7E
                    want = {b >> 1, (b + 2) >> 1} if 0x20 <= b < 0x59 else {b >> 1}
                else:
                    want = {0}
                if c == 0xFF and len(want) == 1 and want <= ANIMATED:
                    c = min(want)               # an animated tile, drawn every time
                if c not in want:
                    errs.append(f"cell {tx},{ty}: record {c:#x}, map {sorted(want)}")
                    continue
                g = tiles[32 * c:32 * c + 32]
                got = rows[2 * ty][16 * tx:16 * tx + 16] + rows[2 * ty + 1][16 * tx:16 * tx + 16]
                cols = [screen[40 * (2 * ty + dy) + 1 + 2 * tx + dx] for dy in (0, 1) for dx in (0, 1)]
                if got != g or any(k != colour[c] for k in cols):
                    errs.append(f"cell {tx},{ty}: not tile {c:#x}")
        checks += 1
        if errs:
            bad += 1
            print(f"    NOT: {len(errs)}: {errs[:6]}", flush=True)
        return not errs

    def draws(what, n=2):
        """n draws checked, from wherever the game is now."""
        v.cmd(f"break {DRAWN:04x}", wait=0.2)
        oks, cyc, last = [], [], None
        for _ in range(n):
            v.sock.sendall(b"x\n")
            if not stopped():
                v.cmd("delete", wait=0.2)
                print(f"{what}: no draw (not outdoors?)", flush=True)
                return
            t = clock()
            if last is not None:
                cyc.append(t - last)
            oks.append(check_draw())
            last = clock()
        v.cmd("delete", wait=0.2)
        p = pos(v)
        print(f"{what}: at {v.mem(LAND, LAND)[0]}:{p[0]},{p[1]}, {sum(oks)} of {n} draws as the map"
              + (f" (the next one {cyc[0]} cycles after)" if cyc else ""), flush=True)

    def teleport(land, x, y, gap=3.0):
        v.tap("\x88", gap=0.8)
        for ch in f"{land}{x:02d}{y:02d}":
            v.tap(ch, gap=0.6)
        v.run(gap)

    try:
        v.poke(HITS, [0x0F, 0x27])
        v.poke(0x825A, [0x0F, 0x27])            # food
        v.poke(s["pw_on"], [0x80])
        draws("in play", 3)
        for k in ";;;//::@@":
            v.tap(k, gap=0.8)
            draws(f"step {k}", 1)
        draws("idle", 4)
        for name, keys in (("Ztats", "z"), ("Inform", "i"), ("Ready", "r"), ("F1", "\x85")):
            v.tap(keys, gap=2.5)
            v.shot(f"build/u1_view_{name.lower()}_shown.png")
            for _ in range(3):
                v.tap(" ", gap=1.5)
            draws(name)
        v.tap("a", gap=1.0)
        v.tap(";", gap=3.0)
        draws("attack")
        # a coast near Britain, then beside Lord British's castle: water and flags
        teleport(0, 20, 38)
        draws("F7 to a coast", 3)
        _i, _n, c, x, y = places[CASTLE]
        teleport(c, x - 1, y)
        draws("beside the castle", 3)
        v.shot("build/u1_view_castle.png")
        v.tap("b", gap=1.0)
        v.tap("h", gap=2.0)
        draws("on a horse")
        for k in "::":
            v.tap(k, gap=0.8)
        v.tap("x", gap=2.0)
        draws("off the horse")
        teleport(0, 20, 38)
        v.tap("b", gap=1.0)
        v.tap("f", gap=2.0)
        draws("in a frigate")
        for k in "::::":
            v.tap(k, gap=0.8)
        draws("sailed")
        v.tap("x", gap=2.0)
        teleport(1, 0, 30)                      # the land's edge: one step west
        for k in "::":
            v.tap(k, gap=1.5)
        draws("off the edge")
        for n, out in ((BRITAIN, "/"), (PERINIA, "k"), (CASTLE, ":")):    # (the castle's gate is west)
            _i, name, c, x, y = places[n]
            teleport(c, x, y)
            v.tap("e", gap=15)
            for _ in range(24):
                v.tap(out, gap=1.5 if out == "/" else 6)
                if bytes(v.mem(OVERLAY + 4, OVERLAY + 15)) == ou[4:16]:
                    break
            v.run(3)
            draws(f"out of {name}", 3)
        v.poke(HITS, [0, 0])                    # dead at the loop's top
        v.tap(" ", gap=20)
        v.shot("build/u1_view_dead.png")
        v.poke(HITS, [0x0F, 0x27])
        for _ in range(3):
            v.tap(" ", gap=3)
        draws("after a death", 3)
        v.shot("build/u1_view_end.png")
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} of {checks} draws bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
