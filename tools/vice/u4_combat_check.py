#!/usr/bin/env python3
"""Ultima 4: X in combat (u4a0.s pw_win, the page's X), in VICE.

    python -m tools.vice.u4_combat_check

Journey Onward from build/u4_saved.tcrt to game main's key read ($408F);
an orc (tile $C0) put into a free object slot east of the party; Attack
($46BB, the main letter table's A) run from there with ';' (east) queued.
At combat's command read ($70EB) X is queued: first with pw_on 0 -- "WHAT?",
the fight goes on to the next turn's read -- then with pw_on 1 -- the foes
go, "VICTORY!", and game main's key read again with the party in Britannia
($1B = 1).  Screenshots in build/u4_combat_*.png.
"""
import re
import sys
from pathlib import Path

from tools.vice import menu_check
from tools.vice import u4_check
from tools.vice.vice_mon import Vice

MAIN_LOOP = 0x408F
ATTACK = 0x46BB
COMBAT_KEY = 0x70EB             # JSR $0800 in combat's command loop
PW_ON = 0x02A7
LOG = "build/u4_combat_check.log"


def syms():
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u4drv.sym").read_text())}


def queue(v, key):
    v.poke(0x0277, bytes([key]))
    v.poke(0x00C6, b"\x01")


def main():
    s = syms()
    image = menu_check.with_autokey(4)
    u4_check.seed_saves(image)
    v = Vice(image, log=LOG, update_tcrt=True)
    bad = 0
    try:
        v.run_to(0x0200, timeout=90)
        v.cmd("bank ram", wait=0.2)
        v.poke(s["pt_opts"], bytes([0x04]))             # Journey onward
        print("main loop:", v.run_to(MAIN_LOOP, timeout=120), flush=True)
        v.cmd("bank ram", wait=0.2)
        mode = v.mem(0x1B, 0x1B)[0]
        x, y = v.mem(0x10, 0x11)
        tiles = v.mem(0xAC60, 0xAC7F)
        slot = next(i for i in range(len(tiles)) if tiles[i] == 0)
        print(f"mode ${mode:02x}, party at ({x}, {y}), object slot {slot}", flush=True)
        for table, val in ((0xAC00, 0xC0), (0xAC20, (x + 1) & 0xFF), (0xAC40, y), (0xAC60, 0xC0)):
            v.poke(table + slot, bytes([val]))
        queue(v, ord(";"))
        v.cmd(f"r pc = {ATTACK:04x}", wait=0.3)
        hit = v.run_to(COMBAT_KEY, timeout=90)
        print("combat's command read:", hit, flush=True)
        v.cmd("bank ram", wait=0.2)
        foes = v.mem(0xAD50, 0xAD5F)
        print("foes:", foes.hex(" "), "mode", v.mem(0x1B, 0x1B).hex(), flush=True)
        bad += not hit or not any(foes)
        v.shot("build/u4_combat_0.png")
        # X with the option off: WHAT?, and the fight goes on
        v.poke(PW_ON, b"\x00")
        queue(v, ord("X"))
        v.run(0.5)
        hit = v.run_to(COMBAT_KEY, timeout=60)
        v.cmd("bank ram", wait=0.2)
        still = v.mem(0xAD50, 0xAD5F)
        print("X off -- next command read:", hit, "foes:", still.hex(" "), flush=True)
        bad += not hit or not any(still)
        v.shot("build/u4_combat_1.png")
        # and on: VICTORY!, back in Britannia
        v.poke(PW_ON, b"\x01")
        queue(v, ord("X"))
        v.run(0.5)
        hit = v.run_to(MAIN_LOOP, timeout=90)
        v.cmd("bank ram", wait=0.2)
        mode = v.mem(0x1B, 0x1B)[0]
        print("X on -- game main's key read:", hit, f"mode ${mode:02x}", flush=True)
        bad += not hit or mode != 1
        v.run(2.0)
        v.shot("build/u4_combat_2.png")
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
