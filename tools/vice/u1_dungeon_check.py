#!/usr/bin/env python3
"""Ultima I's dungeon levels in VICE against what maps/u1maps.py draws.

    python -m tools.vice.u1_dungeon_check [--shots DIR]

Makes a character as u1_town_check does, walks to the Dungeon of Montor
(continent 0, place 12: the nearest on foot) and enters it.  Then, each level as DN has just built
it at $B407 (11 x 11; a monster is the high nibble of an open square, so the
low nibble is compared, and a chest or coffin may be either) against
u1maps.Dungeons, and DN's seed inputs against the place's: $8262 the place's
index, $81E8/$81E9 its square, $81E4 the continent.  The way down is Klimb on
each level's ladder down, levels 1 to 10, then once up to 9: the party is put
on the ladder through the monitor ($A855/$A856), and its hit points ($823B)
are raised so the monsters cannot end the walk.  About four minutes.
"""
import argparse
import os
import sys

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice import menu_check
from tools.vice.u1_town_check import in_play, new_game, walk
from ultima.maps import u1maps
from tools.vice.vice_mon import Vice

DUNGEON = 12                                    # the Dungeon of Montor
LEVEL, LEVEL_AT, PARTY_X, HITS = 0xA873, 0xB407, 0xA855, 0x823B


def check_level(v, gen, place, n):
    i, name, c, x, y = place
    live = v.mem(LEVEL_AT, LEVEL_AT + 120)
    plan = gen.level(i - 1, x, y, c, n)
    seed = v.mem(0x8262, 0x8262)[0], *v.mem(0x81E8, 0x81E9), v.mem(0x81E4, 0x81E4)[0]
    level = v.mem(LEVEL, LEVEL)[0]
    bad = [(k % 11, k // 11, live[k], p) for k, p in enumerate(plan)
           if not (live[k] & 15 in (u1maps.CHEST, u1maps.COFFIN) if p is None else live[k] & 15 == p)]
    monsters = sum(1 for b in live if b >> 4)
    print(f"{name} level {level}: seed inputs {seed}, {121 - len(bad)} of 121 squares as drawn "
          f"({monsters} monsters){'' if not bad else ', not ' + str(bad)}")
    return level == n and seed == (i - 1, x, y, c) and not bad


def klimb(v, n, ladder):
    """From level n by the ladder at (x, y) to the next."""
    v.poke(PARTY_X, list(ladder))
    for _ in range(4):
        v.tap("k", gap=6)
        if v.mem(LEVEL, LEVEL)[0] != n:
            return
    raise RuntimeError(f"Klimb on level {n} at {ladder} did nothing")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shots", help="write screenshots there")
    a = ap.parse_args()
    world = u1maps.continents()[0]
    place = next(p for p in u1maps.places() if p[0] == DUNGEON)
    gen = u1maps.Dungeons()
    image = menu_check.with_autokey(1)
    for attempt in range(3):                # key timing at the menus is not exact
        v = Vice(image, port=6533)
        new_game(v)
        if in_play(v, world):
            break
        print("not in play after the menus, again")
        v.quit()
    else:
        raise SystemExit("could not start a game")
    ok = True
    try:
        assert v.mem(0x81E4, 0x81E4)[0] & 3 == 0, "not on the first continent"
        walk(v, world, (place[3], place[4]))
        v.tap("e", gap=15)
        assert v.mem(LEVEL, LEVEL)[0] == 1, "not in the dungeon"
        v.poke(HITS, [0x0F, 0x27])                      # 9999
        if a.shots:
            v.shot(os.path.join(a.shots, "u1_dungeon_1.png"))
        ok &= check_level(v, gen, place, 1)
        for n in range(1, 10):                          # down: odd (3, 7), even (7, 3)
            klimb(v, n, (3, 7) if n & 1 else (7, 3))
            ok &= check_level(v, gen, place, n + 1)
        klimb(v, 10, (3, 7))                            # and up again
        ok &= check_level(v, gen, place, 9)
        if a.shots:
            v.shot(os.path.join(a.shots, "u1_dungeon_9.png"))
    finally:
        v.quit()
    print("all as drawn" if ok else "DIFFERENCES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
