#!/usr/bin/env python3
"""Ultima 2: F1 tells where, F7 teleports, B brings a transport (u2powers.s,
the page's X).

    python -m tools.vice.u2_powers_check

U2 from a copy of the cart (the menu picking it at once, MENU_AUTOKEY), a
player made at INTRO's title (C, 15 into each stat, M 1 1, AVATAR, Y --
which goes straight into the game; Y is sent until the record's write is
seen), pw_on poked ($80, as the page's launch poke).  Every key goes
straight into $38 (bit 7 set: one waiting), each after the last was taken
($4075); in ULTIMA from the command loop's poll ($512C):
F7 1 0 2 0 -- the party at (10, 20); F1 -- back at the prompt ($50E7)
before any turn's end ($52C0); F7 to a grass square (where Exit
leaves a horse), B H -- a horse ($13 = $22), X(it) -- on foot again; F7 6 4
-- refused.  Screenshots in build/u2_powers_*.png.
"""
import re
import sys
from pathlib import Path

from tools.vice import menu_check
from tools.vice.vice_mon import Vice
from tools.vice.u3_drive import wait_stop

POLL = 0x512C
LOG = "build/u2_powers_check.log"


def syms():
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u2drv.sym").read_text())}


def main():
    s = syms()
    image = menu_check.with_autokey(2)          # the list's place 2: U2
    v = Vice(image, update_tcrt=True, log=LOG)

    def take(key, secs=0.8):
        """A key into $38 (bit 7: one waiting -- where the IRQ, SUBS $4765,
        puts the KERNAL's), once the last one is taken."""
        for _ in range(100):
            if not v.mem(0x38, 0x38)[0] & 0x80:
                break
            v.run(0.1)
        v.poke(0x38, bytes([key | 0x80]))
        v.run(secs)

    bad = 0
    try:
        v.run_to(0xC093, timeout=90)
        v.delbreaks()
        v.run(10.0)
        text = lambda: " ".join(v.screen()).upper()
        for _ in range(10):                 # C at the title, until creation is up
            take(ord("C"), 3.0)
            if "POINTS" in text():
                break
        print("creation:", "POINTS" in text(), flush=True)
        for ch in "151515151515":
            take(ord(ch), 0.6)
        for ch in "M11":
            take(ord(ch), 1.2)
        for ch in "AVATAR":
            take(ord(ch), 0.4)
        take(0x0D, 1.5)
        # Y, until the record's write ($40AB -> u2_block, T35 S16) shows it
        # was taken: a key in the queue is not always seen
        v.shot("build/u2_powers_made.png")
        made = False
        for _ in range(4):
            v.cmd(f"break {s['u2_blk_write']:04x}", wait=0.2)
            v.poke(0x38, bytes([0x80 | ord("Y")]))
            made = wait_stop(v, 15)
            v.cmd("delete", wait=0.2)
            if made:
                break
        print("the player written:", made, flush=True)
        if not made:
            return 1
        v.poke(s["pw_on"], b"\x80")            # (the driver is in since the boot)
        # Y goes straight into the game
        hit = v.run_to(POLL, timeout=90)
        print("the command loop:", hit, flush=True)
        lines = lambda: " / ".join(r.strip() for r in v.screen()[-4:])
        if not hit:
            return 1
        v.delbreaks()
        v.run(3.0)
        v.cmd("bank ram", wait=0.2)
        where = v.mem(0x8E14, 0x8E14)[0]
        x, y = v.mem(0x02, 0x03)
        print(f"$8E14 = {where}, party at ({x}, {y}), $13 = ${v.mem(0x13, 0x13)[0]:02x}, "
              f"under it $14 = ${v.mem(0x14, 0x14)[0]:02x}, map ${v.mem(0x1000 + y * 64 + x, 0x1000 + y * 64 + x)[0]:02x}",
              flush=True)
        v.shot("build/u2_powers_0.png")
        # F7 1 0 2 0
        take(0x88)
        for ch in "1020":
            take(ord(ch), 0.3)
        print("  text:", lines(), flush=True)
        x, y = v.mem(0x02, 0x03)
        print(f"F7 1020: party at ({x}, {y})", flush=True)
        bad += (x, y) != (10, 20)
        v.run(1.0)
        v.shot("build/u2_powers_1.png")
        # F1: "POSITION X-10 Y-20", and no turn: the prompt ($50E7) comes
        # before the command's end ($52C0, the monsters' turn)
        for _ in range(100):
            if not v.mem(0x38, 0x38)[0] & 0x80:
                break
            v.run(0.1)
        v.cmd("break 52c0", wait=0.2)
        v.cmd("break 50e7", wait=0.2)
        v.poke(0x38, bytes([0x85]))
        stopped = wait_stop(v, 15)
        at = v.pc()
        said = text()                       # (before an idle pass scrolls it)
        print("  text:", lines(), flush=True)
        v.cmd("delete", wait=0.2)
        print(f"F1: stopped at ${at or 0:04x} ($50E7: the prompt, no turn)", flush=True)
        bad += not stopped or at != 0x50E7
        bad += "POSITION X-10 Y-20" not in said
        v.run(1.0)
        print(f"F1: party at {tuple(v.mem(0x02, 0x03))} (stays)", flush=True)
        bad += tuple(v.mem(0x02, 0x03)) != (10, 20)
        v.shot("build/u2_powers_f1.png")
        # to a grass square (map byte $08: tile $04, the one Exit leaves a
        # horse on), B H -- a horse; X(it) -- on foot again
        world = v.mem(0x1000, 0x1FFF)
        gx, gy = next((i % 64, i // 64) for i in range(4096) if world[i] == 0x08
                      and 10 <= i % 64 < 54 and 10 <= i // 64 < 54)
        take(0x88)
        for ch in f"{gx:02d}{gy:02d}":
            take(ord(ch), 0.3)
        v.run(1.0)
        print(f"F7 to grass ({gx}, {gy}):", tuple(v.mem(0x02, 0x03)), f"$14 = ${v.mem(0x14, 0x14)[0]:02x}",
              flush=True)
        take(ord("B"), 0.3)
        take(ord("H"), 0.3)
        print("  text:", lines(), flush=True)
        tile = v.mem(0x13, 0x13)[0]
        print(f"B H: $13 = ${tile:02x} ($22: a horse)", flush=True)
        bad += tile != 0x22
        v.run(1.0)
        v.shot("build/u2_powers_2.png")
        take(ord("X"), 0.3)
        print("  text:", lines(), flush=True)
        tile = v.mem(0x13, 0x13)[0]
        print(f"X: $13 = ${tile:02x} (on foot: $78 and up)", flush=True)
        bad += tile < 0x78
        v.run(1.0)
        v.shot("build/u2_powers_3.png")
        # 64 is refused
        here = tuple(v.mem(0x02, 0x03))
        take(0x88)
        for ch in "64":
            take(ord(ch), 0.3)
        print("  text:", lines(), flush=True)
        print("F7 64:", tuple(v.mem(0x02, 0x03)), "(stays)", flush=True)
        bad += tuple(v.mem(0x02, 0x03)) != here
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
