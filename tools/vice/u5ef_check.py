#!/usr/bin/env python3
"""Ultima V started from the Ultima VI EasyFlash's 5 (ef/efu5.s), in VICE:
its music from the EasyFlash's bank (armusic.s EF_MUSIC) and the game around it.

    make cart ef
    python -m tools.vice.u5ef_check

Both carts: the EasyFlash as built, and a copy of the collection's .tcrt on
the tape port, written back after each session.  At the init stub ($0200)
tracepoints go on for every store to $DE00-$DFFF -- the EasyFlash's
registers and its RAM, which holds the player's state -- made with I/O in
and the cart's window out ($01 & 7 = 5 or 6): the game's own banking.  The
glue and the driver write the cart's registers at $01 = $27 only, so any
such store is the game's; on a C64 without the cart it would go nowhere,
here it would hit the music or switch the cart.

  1. The title: $C8 bit 6 (the music is there), $0314 at the glue, a song
     playing ($03CE) and the player's state in the cart's RAM moving.
     Create New Character as tools/vice/fixtures.py does it, into the
     story, where the game saves the new character: the roster's slot holds
     the name, U5's journal is erased.
  2. The 5 again, Journey Onward from that save, out of Iolo's hut with the
     joystick (fixtures.py's way), steps in Britannia with the music still
     there, Q to save: PRTY.DATA's slot (zero page $02-$31) has the party
     where it stood ($2D, $2E).

Every tracepoint hit is printed with its PC and $01; none is the pass.
"""
import os
import shutil
import sys
import time

from ultima import paths
os.chdir(paths.ROOT)
from tools.vice import menu_check                    # noqa: E402
from tools.vice.u5_sweep import boot_ef              # noqa: E402
from ultima.flash import regions                     # noqa: E402
from ultima.flash.tcrt import TCRT                   # noqa: E402

TCRT_COPY = "build/u5ef.tcrt"
ROSTER_SLOT, PRTY_SLOT = 3, 4       # build.py's slot order (u5_save_check.py)
NAME = b"avatar"                    # the roster's name: bit 7 set but on the last
HUT = (45, 62)                      # where the hut lets a new character out (fixtures.py)
TRACE = [0]                         # tracepoint hits, over both sessions


def session():
    """The EasyFlash's 5, stopped at the init stub, the tracepoints on; every
    byte the monitor sends kept, so that hits during the harness's own
    waits are seen."""
    u = boot_ef(log="build/u5ef_check.log", update=True)
    v = u.v
    seen = []
    drain = v._drain

    def tee(wait=0.2):
        out = drain(wait)
        seen.append(out)
        return out
    v._drain = tee
    cmd = v.cmd

    def arm():
        for cond in ("$05", "$06"):
            cmd(f"trace store de00 dfff if (@cpu:$01 & $07) == {cond}", wait=0.3)

    def cmd_rearming(text, wait=0.3):
        out = cmd(text, wait)
        if text.strip() == "delete":        # (a bare delete drops tracepoints
            arm()                           # too: the harness's every delbreaks)
        return out
    v.cmd = cmd_rearming
    arm()
    return u, v, seen


def end(v, seen):
    """A clean exit (VICE writes the .tcrt back), and the tracepoint hits;
    the tracepoints must still be there."""
    armed = v.cmd("bk", wait=0.5).count("(Trace store)")
    if armed != 2:
        print(f"  the tracepoints are gone ({armed} left)")
        TRACE[0] += 1000
    v.quit()
    time.sleep(1.0)
    hits = [line.strip() for line in "".join(seen).splitlines()
            if line.lstrip().startswith("#") and "(Trace store" in line]
    TRACE[0] += len(hits)
    for line in hits[:20]:
        print("  store with I/O in: " + line)


def slot(n):
    flash = TCRT.read(TCRT_COPY).flash.ljust(regions.FLASH_SIZE, b"\xff")
    at = regions.save_base("u5") + n * regions.ERASE_BLOCK
    jn = regions.journal("u5")[0]
    return flash[at:at + 2] == b"\xa5\x5a", flash[at + 0x100:at + 0x200], flash[jn:jn + 2] == b"\xff\xff"


def title_and_create():
    u, v, seen = session()
    ok = made = True
    try:
        v.run(15.0)
        v.cmd("bank ram", wait=0.2)
        c8 = v.mem(0xC8, 0xC8)[0]
        irq = int.from_bytes(v.mem(0x0314, 0x0315), "little")
        song = v.mem(0x03CE, 0x03CE)[0]
        v.cmd("bank io", wait=0.2)
        st1 = v.mem(0xDF00, 0xDFFF)
        v.run(2.0)
        st2 = v.mem(0xDF00, 0xDFFF)
        v.cmd("bank ram", wait=0.2)
        moving = sum(a != b for a, b in zip(st1, st2))
        title = bool(c8 & 0x40 and 0x0100 <= irq < 0x0174 and song and moving)
        ok &= title
        print(f"title: $C8 = ${c8:02x}, $0314 = ${irq:04x}, song {song}, "
              f"{moving} bytes of the player's state moved in 2 s: {'ok' if title else 'BAD'}", flush=True)
        made = bool(u.boot_to_menu() and u.menu_pick(1))
        for k in list(b"AVATAR\r") + list(b"M") + list(b"A" * 20):
            u.key(k)
            deadline = time.time() + 120
            while v.mem(0xC6, 0xC6)[0] and time.time() < deadline:
                v.run(0.5)
            made &= not v.mem(0xC6, 0xC6)[0]
            v.run(0.7)
        v.run(25.0)                     # into the story: the save is written
    finally:
        end(v, seen)
    header, data, clean = slot(ROSTER_SLOT)
    name = bytes(c & 0x7F for c in data[:len(NAME)])
    saved = header and name == NAME and clean
    print(f"created: {'ok' if made else 'BAD'}; the roster's slot {name!r}, the journal "
          f"{'erased' if clean else 'NOT erased'}: {'ok' if saved else 'BAD'}", flush=True)
    return ok and made and saved


def journey_and_walk():
    u, v, seen = session()
    ok, where = True, None
    try:
        ok &= bool(u.boot_to_menu() and u.menu_pick(0))
        v.run(25.0)
        u.joystick_patch()
        for _ in range(3):              # out of the hut, as fixtures.py
            u.push("down")
        u.key(ord("O"))
        v.run(1.0)
        for _ in range(15):
            u.push("down")
        u.key(ord("Y"))
        v.run(25.0)
        for d in ("down", "down", "left", "left", "left", "down"):
            u.push(d)
        v.run(2.0)
        v.cmd("bank ram", wait=0.2)
        where = tuple(v.mem(0x2D, 0x2E))
        c8 = v.mem(0xC8, 0xC8)[0]
        song = v.mem(0x03CE, 0x03CE)[0]
        v.shot(os.path.abspath("build/u5ef_check.png"))
        u.key(ord("Q"))                 # quit and save
        v.run(3.0)
        u.key(ord("Y"))
        v.run(15.0)
        out = bool(c8 & 0x40 and song and where != HUT)
        ok &= out
        print(f"Britannia: at {where}, $C8 = ${c8:02x}, song {song}: {'ok' if out else 'BAD'} "
              f"(build/u5ef_check.png)", flush=True)
    finally:
        end(v, seen)
    header, data, clean = slot(PRTY_SLOT)
    pos = tuple(data[0x2D - 0x02:0x2F - 0x02])     # PRTY.DATA is zero page $02-$31
    saved = header and pos == where and clean
    print(f"saved: PRTY.DATA has the party at {pos}: {'ok' if saved else 'BAD'}", flush=True)
    return ok and saved


def main():
    shutil.copy("build/ultima-collection.tcrt", TCRT_COPY)
    menu_check.IMAGE = TCRT_COPY
    ok = title_and_create()
    ok = journey_and_walk() and ok
    print(f"stores to $DE00-$DFFF with I/O in and the cart out: {TRACE[0]}")
    ok &= TRACE[0] == 0
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
