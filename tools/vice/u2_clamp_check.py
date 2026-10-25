#!/usr/bin/env python3
"""Ultima 2: counts stop at 99 (u2clamp.s, the page's V), in the game.

    python -m tools.vice.u2_clamp_check

U2 from a copy of the cart (MENU_AUTOKEY), a player made as in
u2_powers_check.py.  In ULTIMA's command loop: every weapon count ($8E41-
$8E47) set to 99, a weapon's tile ($2C) put under the party, and G(et) --
ULTIMA $7881: a random weapon, one more of it ($7889, hooked at $7890), or
EMPTY! one time in eight, when it is put back and G pressed again (seen
by breakpoints at $7890 and $7897: the idle passes scroll the text off).  With
cl_on ($80, as the page's launch poke) the count stays 99; without, it is
the original's 00.  Keys into $38 as in u2_powers_check.py.  Screenshots
in build/u2_clamp_*.png.
"""
import sys

from tools.vice import menu_check
from tools.vice.vice_mon import Vice
from tools.vice.u3_drive import wait_stop
from tools.vice.u2_powers_check import POLL, syms

LOG = "build/u2_clamp_check.log"
WEAPON = 0x2C                   # the tile G(et) takes a weapon from ($7862)


def main():
    s = syms()
    image = menu_check.with_autokey(2)          # the list's place 2: U2
    v = Vice(image, update_tcrt=True, log=LOG)

    def take(key, secs=0.8):
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
        for _ in range(10):
            take(ord("C"), 3.0)
            if "POINTS" in text():
                break
        for ch in "151515151515":
            take(ord(ch), 0.6)
        for ch in "M11":
            take(ord(ch), 1.2)
        for ch in "AVATAR":
            take(ord(ch), 0.4)
        take(0x0D, 1.5)
        made = False
        for _ in range(4):
            v.cmd(f"break {s['u2_blk_write']:04x}", wait=0.2)
            v.poke(0x38, bytes([0x80 | ord("Y")]))
            made = wait_stop(v, 15)
            v.cmd("delete", wait=0.2)
            if made:
                break
        print("the player written:", made, flush=True)
        if not made or not v.run_to(POLL, timeout=90):
            return 1
        v.delbreaks()
        v.run(3.0)
        v.cmd("bank ram", wait=0.2)
        hooks = v.mem(0x7890, 0x7892)
        print(f"$7890: {hooks.hex(' ')} (JSR cl_wpn ${s['cl_wpn']:04x})", flush=True)
        bad += hooks != bytes([0x20, s["cl_wpn"] & 0xFF, s["cl_wpn"] >> 8])
        # the tile under the party: its map byte is the tile x 2 (grass, $04,
        # is $08 -- u2_powers_check.py), and $14 comes from the view's
        # drawing after a command (space: a pass)
        x, y = v.mem(0x02, 0x03)
        here = 0x1000 + y * 64 + x
        for on in (True, False):
            v.poke(s["cl_on"], b"\x80" if on else b"\x00")
            v.poke(0x8E41, b"\x99" * 7)
            got = None
            for _ in range(8):                  # EMPTY!: once in eight
                v.poke(here, bytes([WEAPON * 2]))
                take(ord(" "), 1.0)
                under = v.mem(0x14, 0x14)[0]
                # the add's hooked STA, or EMPTY! -- not the text: the idle
                # passes scroll it off before it can be read
                v.brk(0x7890)
                v.brk(0x7897)
                v.poke(0x38, bytes([ord("G") | 0x80]))
                hit = wait_stop(v, 10)
                pc = v.pc() if hit else None
                v.delbreaks()
                v.run(1.0)
                print(f"  G: under ${under:02x}, stopped at {pc and f'${pc:04x}'}", flush=True)
                if pc == 0x7890:
                    got = v.mem(0x8E41, 0x8E47)
                    break
            v.shot(f"build/u2_clamp_{'on' if on else 'off'}.png")
            if got is None:
                print(f"cl_on {'$80' if on else '$00'}: no weapon taken", flush=True)
                bad += 1
                continue
            print(f"cl_on {'$80' if on else '$00'}: weapons $8E41-$8E47 {got.hex(' ')}", flush=True)
            changed = [i for i in range(7) if got[i] != 0x99]
            if on:
                bad += bool(changed)
            else:
                bad += [got[i] for i in changed] != [0x00]
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
