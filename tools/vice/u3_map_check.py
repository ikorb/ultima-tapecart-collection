#!/usr/bin/env python3
"""Ultima 3: Gold's trainer keys leave the map of Sosaria alone.

    python -m tools.vice.u3_map_check

U3 from a copy of the cart with X (Gold's trainer keys) on its page, a fighter
made and on Sosaria (u3_drive.start), beside Lord British's castle (45, 18).
Two trips, each there and back by O(ther), AMBROSIA:

1. On foot on the grass west of Lord British's castle (44, 18): the grass is
   still there in the cached map ($E000) while on Ambrosia and in the map
   ($1000) after the return, and the party comes back on foot ($0E = $7E).
2. By the whirlpool: a frigate ($0E = $16) on the water east of the castle
   (46, 18) and a whirlpool tile ($30) east of it; a step east (;) goes down
   it. The whirlpool tile is water afterwards and the party comes back on a
   frigate where it went down (47, 18), as in the original.

Then the crafts, on foot on the grass at (44, 18):

3. B, S: a frigate, the grass still there; X-it: on foot, the grass still
   there (a frigate is parked on water only).
4. B, H: a horse, the grass still there; X-it: the horse parked ($28), as in
   the original; B: mounted again, grass under it.
5. A frigate on the water at (46, 18): X-it parks it ($2C), B boards it and
   leaves water, as in the original.

Screenshots in build/u3_map_*.png.
"""
import sys

from tools.vice.u3_drive import gkey, start

SOSA, CACHE = 0x1000, 0xE000
ON_FOOT, HORSE, FRIGATE, WHIRLPOOL = 0x7E, 0x14, 0x16, 0x30


def tile(v, base, x, y):
    v.cmd("bank ram", wait=0.2)
    return v.mem(base + y * 64 + x, base + y * 64 + x)[0]


def where(v):
    v.cmd("bank ram", wait=0.2)
    m = v.mem(0x0E, 0x0E)[0], v.mem(0x62, 0x62)[0]
    x, y = v.mem(0xF7, 0xF8)
    return m[0], m[1], x, y


def clear_monsters(v):
    """Every monster of the current map off it, its square's own tile put
    back, so that no fight gets in the way (a fresh fighter loses them)."""
    v.cmd("bank ram", wait=0.2)
    mon = v.mem(0x4F00, 0x4F7F)
    for k in range(32):
        if mon[k]:
            v.poke(SOSA + mon[0x60 + k] * 64 + mon[0x40 + k], bytes([mon[0x20 + k]]))
            v.poke(0x4F00 + k, bytes([0]))


def until(v, mode, timeout=60):
    """Run until $62 (where the party is) is mode."""
    for _ in range(int(timeout / 2)):
        v.run(2.0)
        if where(v)[1] == mode:
            clear_monsters(v)
            v.run(4.0)
            clear_monsters(v)
            return True
    return False


def keys(v, text):
    """Keys at the polls; False if one found none."""
    for k in text:
        if not gkey(v, k):
            return False
        v.run(1.5)
    v.run(1.0)
    return True


def step(v, what, text, x, y, square, craft):
    """Keys, then the square's tile and the party's craft as expected."""
    clear_monsters(v)
    ok = keys(v, text)
    now, (t, _, px, py) = tile(v, SOSA, x, y), where(v)
    good = ok and now == square and t == craft and (px, py) == (x, y)
    print(f"  {what}: square ${now:02x} (want ${square:02x}), craft ${t:02x} (want ${craft:02x})"
          f" at {px} {py}{'' if good else '  BAD'}", flush=True)
    return not good


def ambrosia(v):
    """O, then the word (Other asks for a character first when the party has
    more than one; a digit typed into the word is ignored)."""
    for k in b"O1AMBROSIA":
        if not gkey(v, k):
            return False
        v.run(0.5)
    return True


def trip(v, shot):
    """There and back; the map's tile is read by the caller."""
    bad = 0
    bad += not ambrosia(v)
    ok = until(v, 0xFF)
    print("  on Ambrosia:", ok, "(party tile $%02x, $62 $%02x, at %d %d)" % where(v), flush=True)
    bad += not ok
    v.shot(f"build/u3_map_{shot}a.png")
    return bad


def back(v, shot):
    bad = not ambrosia(v)
    ok = until(v, 0x00)
    print("  back on Sosaria:", ok, "(party tile $%02x, $62 $%02x, at %d %d)" % where(v), flush=True)
    v.shot(f"build/u3_map_{shot}b.png")
    return bad + (not ok)


def main():
    v = start(page_keys="x")
    bad = 0
    try:
        print("start: party tile $%02x, $62 $%02x, at %d %d" % where(v), flush=True)
        clear_monsters(v)
        v.poke(0x401A, bytes([0x99, 0x99]))         # hit points (BCD), for a fight all the same

        print("1. on foot, on the grass west of the castle", flush=True)
        x, y = 44, 18
        v.poke(0xF7, bytes([x, y]))
        v.poke(0x0E, bytes([ON_FOOT]))
        was = tile(v, SOSA, x, y)
        print(f"  ({x}, {y}) is ${was:02x}; the castle (45, 18) ${tile(v, SOSA, 45, 18):02x}", flush=True)
        bad += trip(v, 1)
        cached = tile(v, CACHE, x, y)
        print(f"  cached map: ${cached:02x}", flush=True)
        bad += cached != was
        bad += back(v, 1)
        now, (t, _, px, py) = tile(v, SOSA, x, y), where(v)
        print(f"  map: ${now:02x}, party tile ${t:02x} at {px} {py}", flush=True)
        bad += now != was or t != ON_FOOT or (px, py) != (x, y)

        print("2. by the whirlpool, from a frigate east of the castle", flush=True)
        x, y = 46, 18
        v.poke(0xF7, bytes([x, y]))
        v.poke(0x0E, bytes([FRIGATE]))
        v.poke(SOSA + y * 64 + x + 1, bytes([WHIRLPOOL]))
        print(f"  ({x}, {y}) ${tile(v, SOSA, x, y):02x}, ({x + 1}, {y}) ${tile(v, SOSA, x + 1, y):02x}",
              flush=True)
        for _ in range(5):                          # a key can miss its poll
            gkey(v, ord(";"))
            v.run(2.0)
            if where(v)[1:] != (0, x, y):
                break
        ok = until(v, 0xFF)
        print("  on Ambrosia:", ok, "(party tile $%02x, $62 $%02x, at %d %d)" % where(v), flush=True)
        bad += not ok
        cached = tile(v, CACHE, x + 1, y)
        print(f"  cached map: ({x + 1}, {y}) ${cached:02x}", flush=True)
        bad += cached != 0
        bad += back(v, 2)
        now, (t, _, px, py) = tile(v, SOSA, x + 1, y), where(v)
        print(f"  map: ${now:02x}, party tile ${t:02x} at {px} {py}", flush=True)
        bad += now != 0 or t != FRIGATE or (px, py) != (x + 1, y)

        print("3.-5. the crafts", flush=True)
        x, y = 44, 18
        v.poke(0xF7, bytes([x, y]))
        v.poke(0x0E, bytes([ON_FOOT]))
        bad += step(v, "B, S on grass", b"BS", x, y, 0x04, FRIGATE)
        bad += step(v, "X-it the frigate on grass", b"X", x, y, 0x04, ON_FOOT)
        bad += step(v, "B, H on grass", b"BH", x, y, 0x04, HORSE)
        bad += step(v, "X-it the horse", b"X", x, y, 0x28, ON_FOOT)
        bad += step(v, "B the horse", b"B", x, y, 0x04, HORSE)
        x = 46
        v.poke(0xF7, bytes([x, y]))
        v.poke(0x0E, bytes([FRIGATE]))
        bad += step(v, "X-it a frigate on water", b"X", x, y, 0x2C, ON_FOOT)
        bad += step(v, "B the frigate", b"B", x, y, 0x00, FRIGATE)
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
