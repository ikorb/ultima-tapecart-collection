#!/usr/bin/env python3
"""Ultima V's save through the journal (asm/journal.s), in VICE.

    U5_SAVE_FROM=DIR python -m ultima.build build/u5dbg.tcrt
    python -m tools.vice.u5_save_check

Journey Onward from the seeded save (the C64 build's init stub -- tc_init
and the directory setup are its own now -- has to have worked for that),
park at u5_blk_fetched as u5_sweep.py does, and from its stub at $0335 call
$6C2D, the game's save, with an inline block for ROSTER ($1000, 1024 bytes,
what the game itself writes).  Then a clean exit, and the .tcrt read back:
the slot must hold the header ($A5 $5A, the length) and RAM's roster, and
the journal must be erased.
"""
import os
from ultima import paths
import sys
import time

os.chdir(paths.ROOT)
from tools.vice import menu_check
from ultima.flash import regions
from ultima.flash.tcrt import TCRT
from tools.vice.u5_drive import U5
from tools.vice.u5_sweep import STUB, call, dump

ROSTER, LENGTH, SLOT = 0x1000, 0x400, 3          # build.py's slot order: ROSTER is the fourth


def main():
    menu_check.IMAGE = "build/u5dbg.tcrt"
    image = menu_check.with_autokey(5)
    u = U5(image, extra=["-tapecartupdatetcrt"])
    v, s = u.v, u.sym
    try:
        print("menu:", u.boot_to_menu(), flush=True)
        print("journey:", u.menu_pick(0), flush=True)
        v.run(20.0)
        v.cmd("bank ram", wait=0.2)
        print("parked:", v.run_to(s["u5_blk_fetched"], timeout=120), flush=True)
        v.poke(s["u5_disk"], bytes([2]))
        v.poke(ROSTER, bytes((i * 5 + 1) & 0xFF for i in range(LENGTH)))   # a roster to tell apart
        roster = dump(v, ROSTER, LENGTH)
        # sei / jsr $6C2D / "S:ROSTER",0 / start / length / nop / nop
        code = (bytes([0x78, 0x20, 0x2D, 0x6C]) + b"S:ROSTER\x00"
                + ROSTER.to_bytes(2, "little") + LENGTH.to_bytes(2, "little") + b"\xEA\xEA")
        ok = call(v, code, STUB + len(code) - 2, timeout=60)
        print("saved:", ok, flush=True)
    finally:
        v.quit()
    time.sleep(1.0)
    flash = TCRT.read(image).flash
    base = regions.save_base("u5") + SLOT * regions.ERASE_BLOCK
    jn, _ = regions.journal("u5")
    header = bytes(flash[base:base + 4]) == bytes([0xA5, 0x5A]) + LENGTH.to_bytes(2, "little")
    data = bytes(flash[base + 0x100:base + 0x100 + LENGTH]) == roster
    erased = set(flash[jn:jn + 0x1000]) == {0xFF}
    print(f"slot header {header}, the roster in the slot {data}, journal erased {erased}")
    good = ok and header and data and erased
    print("all good" if good else "FAILED")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
