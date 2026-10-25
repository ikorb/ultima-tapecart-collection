#!/usr/bin/env python3
"""Ultima I: F7 teleports, B brings a transport (u1powers.s, the page's X),
and the thieves' patches (the page's S), in VICE.

    python -m tools.vice.u1_powers_check

Makes a character as u1_town_check does, then pokes pw_on ($80, as the
page's launch poke) and the options byte, pt_opts, as S sets it (STEAL).
Keys through the key matrix:
- F7 without pw_on: nothing moves;
- F7 2 4 0 2 0: the party on land 2 at (40, 20), the land's map decoded at
  $6400 as u1maps draws it; F1: the position shown (the screenshot), the
  party where it was;
- B H: a horse ($81F1 = 1); X(it): on foot, the horse on the map;
- F7 to Britain (land 0, place 14), E: TW in, its theft patched ($A457 an
  RTS); out through the south gate;
- F7 to the Dungeon of Perinia (land 0, place 5), E: DN in, its thief's
  jump patched ($9E81 JMP $9DF6); K(limb) out;
- pt_opts cleared, F7 to Lord British's castle (place 1), E: CA in, its
  jester's theft as on the disk ($9D88 LDA #$00).
After each, the segment at $CE01 (u1powers.s and the options' table) is
compared with the build's, but for its own variables: nothing the game ran
wrote there.  Screenshots
in build/u1_powers_*.png.  About five minutes.
"""
import os
import re
import sys
from pathlib import Path

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice import menu_check
from tools.vice.u1_town_check import in_play, new_game, pos
from ultima.games.u1 import build as u1
from ultima.launcher import patches
from ultima.maps import u1maps
from tools.vice.vice_mon import Vice

HITS, LAND, VEHICLE, OVERLAY = 0x823B, 0x81E4, 0x81F1, 0x8C9E
BRITAIN, PERINIA, CASTLE = 14, 5, 1             # u1maps.places()' numbers


def syms():
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u1drv.sym").read_text())}


def main():
    s = syms()
    blob = Path("build/u1drv.bin").read_bytes()
    ext = blob[u1.EXT_ADDR - u1.DRIVER_ADDR:s["u1_ext_end"] - u1.DRIVER_ADDR]
    worlds = u1maps.continents()
    places = {p[0]: p for p in u1maps.places()}
    ou = u1maps.prg("ou.prg")
    image = menu_check.with_autokey(1)
    for attempt in range(3):                # key timing at the menus is not exact
        v = Vice(image, port=6534)
        new_game(v)
        if in_play(v, worlds[0]):
            break
        print("not in play after the menus, again")
        v.quit()
    else:
        raise SystemExit("could not start a game")
    bad = 0

    def check(what, ok):
        nonlocal bad
        print(f"{what}: {'ok' if ok else 'NOT'}", flush=True)
        bad += not ok

    own = {s[n] for n in ("pw_on", "pw_l", "pw_x", "pw_t")}     # its variables

    def segment(when):
        live = v.mem(u1.EXT_ADDR, u1.EXT_ADDR + len(ext) - 1)
        diff = [u1.EXT_ADDR + i for i in range(len(ext))
                if live[i] != ext[i] and u1.EXT_ADDR + i not in own]
        check(f"the segment at $CE01 as built, {when}"
              + (f" (not at {', '.join(f'${a:04x}' for a in diff[:8])})" if diff else ""), not diff)

    def outdoors():             # (OU's first four bytes are u1view.s's hook)
        return bytes(v.mem(OVERLAY + 4, OVERLAY + 15)) == ou[4:16]

    def teleport(land, x, y, gap=3.0):
        v.tap("\x88", gap=0.8)
        for ch in f"{land}{x:02d}{y:02d}":
            v.tap(ch, gap=0.6)
        v.run(gap)

    def enter(n, overlay_at, want, name):
        _i, _name, c, x, y = places[n]
        teleport(c, x, y)
        check(f"F7 to {name} ({c}: {x}, {y})", (v.mem(LAND, LAND)[0], *pos(v)) == (c, x, y))
        v.tap("e", gap=15)
        got = bytes(v.mem(overlay_at, overlay_at + len(want) - 1))
        check(f"{name}: ${overlay_at:04x} {got.hex(' ')} (want {want.hex(' ')})", got == want)
        v.shot(f"build/u1_powers_{n}.png")
        segment(f"in {name}")

    try:
        v.poke(HITS, [0x0F, 0x27])                      # 9999: no monster ends it
        segment("in play")
        here = (v.mem(LAND, LAND)[0], *pos(v))
        teleport(2, 40, 20)
        check("F7 without pw_on: nowhere", (v.mem(LAND, LAND)[0], *pos(v)) == here)
        v.poke(s["pw_on"], [0x80])
        v.poke(s["pt_opts"], [patches.STEAL])
        v.shot("build/u1_powers_0.png")
        teleport(2, 40, 20)
        check("F7 2 40 20", (v.mem(LAND, LAND)[0], *pos(v)) == (2, 40, 20))
        check("land 2's map at $6400", in_play(v, worlds[2], timeout=10))
        v.tap("\x85", gap=1.5)                         # F1
        check("F1: the party stays", (v.mem(LAND, LAND)[0], *pos(v)) == (2, 40, 20))
        v.shot("build/u1_powers_land2.png")
        # B H on whatever square this is (nothing to board there)
        v.tap("b", gap=1.0)
        v.tap("h", gap=2.0)
        check("B H: a horse", v.mem(VEHICLE, VEHICLE)[0] == 1)
        v.shot("build/u1_powers_horse.png")
        x, y = pos(v)
        under = worlds[2][y * 64 + x]
        v.tap("x", gap=2.0)
        if under <= 2:                                  # water, grass, forest: X-it leaves it
            on_map = (v.mem(0x6400 + y * 64 + x, 0x6400 + y * 64 + x)[0] & 0x7E) >> 1
            check(f"X: on foot, the horse on the map (tile {on_map:#x})",
                  v.mem(VEHICLE, VEHICLE)[0] == 0 and on_map == 9)
        else:
            print(f"(X-it not tried: square kind {under})")
        v.shot("build/u1_powers_xit.png")
        segment("outdoors")
        # Britain: TW's theft patched (pt_opts has STEAL)
        enter(BRITAIN, 0xA457, bytes.fromhex("6000854ca20f"), "Britain")
        for _ in range(12):                             # out through the south gate
            v.tap("/", gap=1.5)
            if outdoors():
                break
        v.run(3)
        check("out of Britain", outdoors())
        # the Dungeon of Perinia: DN's thief patched
        enter(PERINIA, 0x9E81, bytes.fromhex("4cf69d4cfc9e"), "the Dungeon of Perinia")
        for _ in range(4):
            v.tap("k", gap=6)
            if outdoors():
                break
        v.run(3)
        check("out of the dungeon", outdoors())
        # the castle with S off again: CA as on the disk
        v.poke(s["pt_opts"], [0])
        enter(CASTLE, 0x9D88, bytes.fromhex("a900854ca20f"), "Lord British's castle (S off)")
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
