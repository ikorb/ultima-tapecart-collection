#!/usr/bin/env python3
"""Ultima 4: Quit & save in a dungeon, and the game loaded back into it.

    python -m tools.vice.u4_dungeon_check

The Remastered kit's dungeon save (ultima/games/u4/u4ff.s at $FF00) and the
driver's copy of the temporary map (u4drv.s, chunk $7E): Journey Onward from
build/u4_saved.tcrt, into Deceit the way an earlier check went -- the party
on the first dungeon's square ($51AA/$51CA), the entrance tile under it ($48
= $09), Enter ($4FDA) run from the main loop's key read ($408F) -- then Quit
($582A) run from there, in the dungeon.  The cart must see the temporary
map's copy go into its slot (block 271) and chunks $7F and $80 and record $1A
written; then the image is booted again, Journey Onward, and the game has
to be in the dungeon ($1B = 3) with Deceit's level loaded.  Screenshots in
build/u4_dungeon_*.png.
"""
import re
import sys
import time
from pathlib import Path

from tools.vice import menu_check
from ultima.flash import regions
from tools.vice import u4_check
from tools.vice.vice_mon import Vice

MAIN_LOOP = 0x408F              # game main's key read, between commands
ENTER = 0x4FDA
QUIT = 0x582A
LOG = "build/u4_dungeon_check.log"


def syms():
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u4drv.sym").read_text())}


def journey(v, s):
    v.run_to(0x0200, timeout=90)
    v.cmd("bank ram", wait=0.2)
    v.poke(s["pt_opts"], bytes([0x04]))             # Journey onward
    return v.run_to(MAIN_LOOP, timeout=120)


def cart_log():
    return Path(LOG).read_text(errors="replace")


def main():
    s = syms()
    image = menu_check.with_autokey(4)
    u4_check.seed_saves(image)
    base = regions.save_base("u4")
    v = Vice(image, log=LOG, update_tcrt=True)
    bad = 0
    try:
        print("main loop:", journey(v, s), flush=True)
        x, y = v.mem(0x51AA, 0x51AA)[0], v.mem(0x51CA, 0x51CA)[0]
        v.poke(0x10, bytes([x]))
        v.poke(0x11, bytes([y]))
        v.poke(0x48, b"\x09")
        v.poke(0x21, bytes([100]))                  # light
        v.cmd(f"r pc = {ENTER:04x}", wait=0.3)
        print("in the dungeon's loop:", v.run_to(MAIN_LOOP, timeout=60), flush=True)
        mode = v.mem(0x1B, 0x1B)[0]
        print(f"game mode ${mode:02x} (3 = a dungeon)", flush=True)
        bad += mode != 3
        v.run(3.0)
        v.run_to(MAIN_LOOP, timeout=60)
        v.shot("build/u4_dungeon_in.png")
        # stop at dg_save's end (after its last save, before cmd_done), where
        # RAM is what went into the slots
        ff = Path("build/u4ff.bin").read_bytes()
        end = 0xFF00 + ff.find(bytes.fromhex("a904204208 4c1e62".replace(" ", "")) ) + 5
        v.cmd(f"r pc = {QUIT:04x}", wait=0.3)
        print("Quit, at the save's end:", v.run_to(end, timeout=60), flush=True)
        v.cmd("bank ram", wait=0.2)
        want = {0: v.mem(0xDF00, 0xDFFF),           # the driver's copy of chunk $7E
                1: v.mem(0xAC00, 0xACFF),           # chunk $7F
                2: v.mem(0xAA00, 0xAAFF), 3: v.mem(0xAB00, 0xABFF),     # chunk $80
                4: v.mem(0x0010, 0x002F)}           # record $1A
        v.shot("build/u4_dungeon_saved.png")
    finally:
        v.quit()
    time.sleep(2)
    # what the save left in the slots (VICE wrote the cart back on its way out)
    from ultima.flash.tcrt import TCRT
    flash = TCRT.read(image).flash
    for slot, data in want.items():
        at = base + slot * regions.ERASE_BLOCK
        ok = bytes(flash[at:at + len(data)]) == data
        bad += not ok
        print(f"  slot {slot}: {'as in RAM' if ok else 'DIFFERENT'}", flush=True)

    # the same image again: Journey onward goes on in the dungeon
    v = Vice(image, log=LOG, update_tcrt=True)
    try:
        print("reloaded, main loop:", journey(v, s), flush=True)
        mode = v.mem(0x1B, 0x1B)[0]
        print(f"game mode ${mode:02x} (3 = a dungeon)", flush=True)
        bad += mode != 3
        v.run(3.0)
        v.shot("build/u4_dungeon_loaded.png")
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
