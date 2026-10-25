#!/usr/bin/env python3
"""Ultima I's screen in VICE against what maps/u1maps.py draws.

    python -m tools.vice.u1_town_check [--shots DIR]

Boots the cart (the menu's autokey build, U1), makes a character through
the keyboard matrix (VICE's `keymatrix` monitor command -- U1 scans the
keyboard itself, `$1E08`, and takes nothing from the KERNAL's queue), and
continues the game with it.  Then, each against u1maps' own tables:

- outdoors: the continent decoded at $6400 (map byte & $7E, / 2) against
  GE's, and the 19 x 9 view (bitmap and screen RAM) against ST's tiles, but
  for monsters and the party (an animated tile may show any of its frames);
- Britain, walked to and entered with E: every cell of the 38 x 18 layout
  (MA's glyph, TW's colour), and every person (the text font's glyph by its
  type, ST's colour; people move, so their types are compared with the
  layout's and their cells wherever they now are);
- Lord British's castle beside it, the same with CA's tables.

The bitmap shown is the one $DD00 and $D018 select (U1 double-buffers).
Needs VICE 3.11 or later (`keymatrix`).  About four minutes.
"""
import argparse
import os
from ultima import paths
import sys
from collections import deque

os.chdir(paths.ROOT)

from tools.vice import menu_check
from ultima.maps import u1maps
from tools.vice.vice_mon import Vice

KEYS = {(0, -1): "@", (-1, 0): ":", (1, 0): ";", (0, 1): "/"}
BRITAIN, CASTLE = (29, 32), (30, 31)        # continent 0, places 14 and 1
OVERLAY = 0x8C9E


def pos(v):
    m = v.mem(0x20, 0x21)
    return m[0], m[1]


def new_game(v):
    """Title, a) a character (Strength, Agility, Stamina +10; human male
    fighter "Test"), saved, b) continue with it."""
    v.run(25)
    v.tap("\r", gap=4)
    v.tap("a", frames=10, gap=12)
    for _ in range(3):
        for _ in range(10):
            v.tap("\x1d", gap=0.3)
        v.tap("\x11", gap=0.3)
    v.tap("\r", gap=3)
    for k in "aaa":
        v.tap(k, gap=2)
    v.type("test", gap=0.5)
    v.tap("\r", gap=4)
    v.tap("y", gap=5)
    v.tap("b", gap=6)
    v.tap("1", gap=5)


def in_play(v, world, timeout=40):
    """Has the continent been decoded to $6400 yet?"""
    import time
    end = time.time() + timeout
    while time.time() < end:
        ram = v.mem(0x6400, 0x73FF)
        if sum((b & 0x7E) >> 1 == w for b, w in zip(ram, world)) > 4000:
            return True
        v.run(2)
    return False


def path(world, a, b, ok=(1, 2)):
    prev, q = {a: None}, deque([a])
    while q:
        p = q.popleft()
        if p == b:
            break
        for d in KEYS:
            n = (p[0] + d[0], p[1] + d[1])
            if n not in prev and 0 <= n[0] < 64 and 0 <= n[1] < 64 and \
                    (n == b or world[n[1] * 64 + n[0]] in ok):
                prev[n] = p
                q.append(n)
    out, p = [], b
    while prev[p]:
        out.append((p[0] - prev[p][0], p[1] - prev[p][1]))
        p = prev[p]
    return out[::-1]


def walk(v, world, b, tries=8):
    """Step by step on grass and forest; a step is repeated until the party
    has moved (a monster's turn or a fight may take a key)."""
    while pos(v) != b:
        a = pos(v)
        d = path(world, a, b)[0]
        want = (a[0] + d[0], a[1] + d[1])
        for _ in range(tries):
            v.tap(KEYS[d], gap=0.8)
            if pos(v) == want:
                break
        else:
            raise RuntimeError(f"stuck at {a} going {d}")


def shown(v):
    """(bitmap, screen RAM) the VIC shows."""
    v.cmd("bank cpu")
    dd00, d018 = v.mem(0xDD00, 0xDD00)[0], v.mem(0xD018, 0xD018)[0]
    bank = (3 - (dd00 & 3)) * 0x4000
    bm, scr = bank + (d018 & 8) * 0x400, bank + (d018 >> 4) * 0x400
    return v.mem(bm, bm + 0x1FFF), v.mem(scr, scr + 0x3FF)


def cell(bm, scr, x, y):
    """The layout's cell (x, y) on screen: it starts at row 1, column 1."""
    c = (1 + y) * 40 + 1 + x
    return bytes(bm[8 * c:8 * c + 8]), scr[c]


def frames(tiles_st, t):
    """Every state tile t reaches under ST's animations ($1DB5): the water
    (0) through $1B06 -- the upper right and lower left cells swapped, each
    half's 16 bytes rotated by one, swapped back -- and pairs of bytes
    swapped in the castle's (4), the town's (6) and tile 12."""
    g = bytearray(tiles_st[32 * t:32 * t + 32])
    swaps = {4: [(9, 10)], 6: [(3, 4)], 12: [(2, 3), (10, 11)]}
    seen = []
    while bytes(g) not in seen:
        seen.append(bytes(g))
        if t == 0:
            g[8:16], g[16:24] = g[16:24], g[8:16]
            g[0:16] = g[15:16] + g[0:15]
            g[16:32] = g[31:32] + g[16:31]
            g[8:16], g[16:24] = g[16:24], g[8:16]
        for a, b in swaps.get(t, []):
            g[a], g[b] = g[b], g[a]
    return seen


def check_outdoors(v, world, tiles_st, colours):
    ram = v.mem(0x6400, 0x73FF)
    live = [(b & 0x7E) >> 1 for b in ram]
    monster = [0x20 <= (b & 0x7E) < 0x59 for b in ram]
    monsters = sum(monster)
    same = sum(1 for i in range(4096) if not monster[i] and live[i] == world[i])
    print(f"outdoors: map at $6400 {same} of {4096 - monsters} squares as decoded ({monsters} monsters)")
    bm, scr = shown(v)
    px, py = pos(v)
    bad, checked = [], 0
    for ty in range(9):
        for tx in range(19):
            x, y = px - 9 + tx, py - 4 + ty
            if (tx, ty) == (9, 4):
                continue                            # the party
            b = ram[y * 64 + x] & 0x7E if 0 <= x < 64 and 0 <= y < 64 else 0
            if 0x20 <= b < 0x59:
                continue                            # a monster
            t = b >> 1
            states = frames(tiles_st, t)
            for k, (cx, cy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
                bits, col = cell(bm, scr, 2 * tx + cx, 2 * ty + cy)
                want = {g[(k >> 1) * 16 + (k & 1) * 8:][:8] for g in states}
                checked += 1
                if bits not in want or col != colours[t]:
                    bad.append((x, y, k, t, bits.hex(), hex(col), hex(colours[t])))
    print(f"outdoors: view {checked - len(bad)} of {checked} cells as ST's tiles"
          + (f", not {bad}" if bad else ""))
    return same == 4096 - monsters and not bad


def check_settlement(v, kind, n, name):
    tc, ma, lo, st = (u1maps.prg(f) for f in ("tc.prg", "ma.prg", "lo.prg", "st.prg"))
    ov = u1maps.prg(f"{kind}.prg")
    col_at, who_at = u1maps.LAYOUT[kind]
    colours = ov[col_at - OVERLAY:col_at - OVERLAY + 128]
    who = ov[who_at - OVERLAY:who_at - OVERLAY + 128]
    text_colours = st[0x1530 - u1maps.ST_ADDR:][:128]
    p = tc[2 * n] | tc[2 * n + 1] << 8
    layout = tc[p - u1maps.TC_ADDR:p - u1maps.TC_ADDR + 764]
    live = v.mem(0xCB00, 0xCB00 + 763)
    bm, scr = shown(v)
    people = {}
    for i in range(16):
        t, x, y = live[684 + i], live[700 + i], live[716 + i]
        if not t & 0x80:
            people[(x, y)] = t
    px, py = pos(v)
    ok_map = live[:684] == layout[:684]
    types = sorted(layout[684:700]) == sorted(live[684:700])
    bad = []
    for y in range(18):
        for x in range(38):
            bits, col = cell(bm, scr, x, y)
            if (x, y) == (px, py):
                g, font, cols = 0x7B, lo, text_colours
            elif (x, y) in people:
                g, font, cols = who[people[(x, y)]], lo, text_colours
            else:
                g, font, cols = live[38 * y + x] & 0x7F, ma, colours
            if bits != font[8 * g:8 * g + 8] or (bits != bytes(8) and col != cols[g]):
                bad.append((x, y))
    print(f"{name}: layout in RAM {'=' if ok_map else '!='} TC's; people's types "
          f"{'=' if types else '!='} the layout's ({len(people)}); "
          f"{684 - len(bad)} of 684 cells as drawn{'' if not bad else ', not ' + str(bad[:10])}")
    return ok_map and types and not bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shots", help="write screenshots there")
    a = ap.parse_args()
    world = u1maps.continents()[0]
    st = u1maps.prg("st.prg")
    tiles_st = st[:0x800]
    colours = st[u1maps.TILE_COLOURS - u1maps.ST_ADDR:][:64]
    image = menu_check.with_autokey(1)
    for attempt in range(3):                # key timing at the menus is not exact
        v = Vice(image, port=6532)
        new_game(v)
        if in_play(v, world):
            break
        if a.shots:
            v.shot(os.path.join(a.shots, f"u1_not_in_play_{attempt}.png"))
        print("not in play after the menus, again")
        v.quit()
    else:
        raise SystemExit("could not start a game")
    ok = True
    try:
        assert v.mem(0x81E4, 0x81E4)[0] & 3 == 0, "not on the first continent"
        ok &= check_outdoors(v, world, tiles_st, colours)
        walk(v, world, BRITAIN)
        v.tap("e", gap=15)
        if a.shots:
            v.shot(os.path.join(a.shots, "u1_britain.png"))
        ok &= check_settlement(v, "tw", 2 + 0, "Britain (town layout 0)")
        for _ in range(10):                     # out through the south gate
            v.tap("/", gap=1.5)
            if pos(v) == BRITAIN:
                break
        else:
            raise RuntimeError("did not leave Britain")
        v.run(5)
        walk(v, world, CASTLE)
        v.tap("e", gap=15)
        if a.shots:
            v.shot(os.path.join(a.shots, "u1_castle.png"))
        ok &= check_settlement(v, "ca", 0, "Lord British's castle (castle layout 0)")
    finally:
        v.quit()
    print("all as drawn" if ok else "DIFFERENCES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
