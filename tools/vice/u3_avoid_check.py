#!/usr/bin/env python3
"""Ultima 3: "AVOID?" when a monster reaches the party (u3avoid.s, the page's A).

    python -m tools.vice.u3_avoid_check

U3 from a copy of the cart with A on its page, a fighter made and on Sosaria
(u3_drive.start); the first monster in ULT3's table ($4F00, X at $4F40, Y at
$4F60) is put east of the party and turns are passed (space) until
"AVOID?" waits for a key (SUBS' key wait from av_ask): Y -- no fight, the
monster still there; then again, N -- the fight ($62 = $80, combat).
Screenshots in build/u3_avoid_*.png.
"""
import sys

from tools.vice.u3_drive import start, syms, wait_stop


def at_question(v, s):
    """Let idle turns pass (the game's own) until a monster's step reaches
    av_ask."""
    v.cmd(f"break {s['av_ask']:04x}", wait=0.2)
    ok = wait_stop(v, 90)
    v.cmd("delete", wait=0.2)
    return ok


def key(v, code, bp, shot):
    """At the question's key wait: a screenshot, then the key."""
    v.cmd(f"break {bp}", wait=0.2)
    ok = wait_stop(v, 20)
    v.cmd("delete", wait=0.2)
    v.shot(shot)
    v.poke(0x0277, bytes([code]))
    v.poke(0x00C6, bytes([1]))
    return ok


def put_monster(v):
    v.cmd("bank ram", wait=0.2)
    tiles = v.mem(0x4F00, 0x4F1F)
    i = next((i for i in range(32) if tiles[i]), None)
    x, y = v.mem(0xF7, 0xF8)
    print(f"party at ({x}, {y}); monsters: {tiles.hex(' ')}", flush=True)
    if i is None:
        return None
    v.poke(0x4F40 + i, bytes([(x + 1) & 0x3F]))
    v.poke(0x4F60 + i, bytes([y]))
    return i


def main():
    v = start(page_keys="a")
    s = syms()
    bad = 0
    try:
        v.cmd("bank ram", wait=0.2)
        opts = v.mem(s["pt_opts"], s["pt_opts"])[0]
        print(f"pt_opts ${opts:02x}", flush=True)
        bad += not opts & 0x40
        i = None
        for _ in range(30):                         # a monster to come (idle turns pass)
            i = put_monster(v)
            if i is not None:
                break
            v.run(3.0)
        if i is None:
            print("no monster on the map")
            return 1
        asked = at_question(v, s)
        print("AVOID? asked:", asked, flush=True)
        bad += not asked
        key(v, ord("Y"), bp=f"{s['kb_take']:04x}", shot="build/u3_avoid_0.png")
        # straight on to the monster's next step (idle turns pass): no fight
        # in between, the monster where it was
        asked = at_question(v, s)
        print("AVOID? again:", asked, flush=True)
        bad += not asked
        v.cmd("bank ram", wait=0.2)
        mode = v.mem(0x62, 0x62)[0]
        print(f"after Y: $62 = ${mode:02x} (0: no fight)", flush=True)
        bad += mode != 0
        print("the monster:", v.mem(0x4F00 + i, 0x4F00 + i).hex(),
              "at", v.mem(0x4F40 + i, 0x4F40 + i)[0], v.mem(0x4F60 + i, 0x4F60 + i)[0], flush=True)
        key(v, ord("N"), bp=f"{s['kb_take']:04x}", shot="build/u3_avoid_1b.png")
        v.run(8.0)
        v.cmd("bank ram", wait=0.2)
        mode = v.mem(0x62, 0x62)[0]
        print(f"N: $62 = ${mode:02x} ($80: combat)", flush=True)
        bad += mode != 0x80
        v.shot("build/u3_avoid_2.png")
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
