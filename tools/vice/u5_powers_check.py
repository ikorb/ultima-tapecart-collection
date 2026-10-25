#!/usr/bin/env python3
"""Ultima 5: F7 teleports, B brings a vehicle (u5powers.s, the page's X).

    python -m tools.vice.u5_powers_check

The cart as built, with the saved game of build/fixture_u5created.tcrt
(tools/vice/fixtures.py: a character just made, in Iolo's hut) in U5's save
region, and a menu that picks U5 at once.  pt_opts is poked to POWERS as
the page would set it, before Journey Onward loads anything.  Out of the hut
(south, the door opened, south off the map, Y), MAIN.OUT is the mode root
and its hook is in.  Then, keys into the KERNAL's queue:

- `=` -- "What?" as before, no teleport;
- B H -- a horse ($0C $12); X -- on foot, a horse object left; B -- that
  horse boarded by the game's own Board; X;
- a step south, off the horse's square (B there would board it);
- B S -- a ship ($0C $25, hull $99, two skiffs); X -- a ship object left with
  them; B -- boarded again, hull and skiffs back; X;
- F7 5 8 RETURN 4 3 RETURN -- the party at (58, 43) by Yew, the window and
  the object list's slot 0 following;
- F7 2 5 6, F7 RETURN, F7 A -- given up, the party stays;
- Q Y -- saved: PRTY.DATA's copy of the position ($BC2B/$BC2C) is the new one.

A second run from the saved cart, with pt_opts 0: Journey Onward puts the
party at (58, 43), F7 and B say "What?" (no hooks without the option), E
enters Yew ($0A = 4).  Screenshots in build/u5_powers_*.png.
"""
import sys

from tools.vice import menu_check
from tools.vice.u5_drive import U5
from ultima.flash import regions
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches

FIXTURE = "build/fixture_u5created.tcrt"
WHAT_DONE = 0x827F              # 2A MAIN.OUT: the JMP after "What?" (the text is a bitmap)
BOARD_WHAT_DONE = 0x86EF        # ... and after Board's
IMAGE = "build/u5_powers.tcrt"
LOG = "build/u5_powers_check.log"
DEST = (58, 43)                 # next to Yew


def image():
    """The cart as built with the fixture's save region, picking U5 at once."""
    auto = TCRT.read(menu_check.with_autokey(5))
    flash = bytearray(auto.flash.ljust(regions.FLASH_SIZE, b"\xff"))
    lo, hi = regions.save_region("u5")
    flash[lo:hi] = TCRT.read(FIXTURE).flash[lo:hi]
    TCRT(data_address=auto.data_address, data_length=auto.data_length, call_address=auto.call_address,
         filename="ULTIMACOLLECTION", flash=bytes(flash)).write(IMAGE, trim=False)
    return IMAGE


def journey(u, opts):
    """Boot, the options byte, Journey Onward; True once the game is up."""
    if not u.boot_to_menu():
        return False
    u.v.poke(u.sym["pt_opts"], bytes([opts]))
    ok = u.menu_pick(0)
    u.v.run(25.0)
    u.joystick_patch()
    return ok


def main():
    bad = 0
    img = image()

    def state(v, tag):
        z = v.mem(0, 0x31)
        print(f"{tag}: ({z[0x2D]}, {z[0x2E]}), world ${z[0x09]:02x}, place ${z[0x0A]:02x}, "
              f"window {list(z[2:6])}, slot 0 ({v.mem(0x4A40, 0x4A40)[0]}, {v.mem(0x4A60, 0x4A60)[0]})",
              flush=True)
        return z

    u = U5(tcrt=img, log=LOG)
    v = u.v

    def keys(codes, secs=1.2):
        for c in codes:
            u.key(c)
            v.run(secs)

    def what(code, done=WHAT_DONE):
        """True if the key ends in "What?" (the JMP after it reached)."""
        u.arm(done)
        u.key(code)
        pc = u.stop(10)
        v.delbreaks()
        v.run(1.0)
        return pc == done

    def party():
        z = v.mem(0, 0x31)
        objs = v.mem(0x4A00, 0x4AFF)
        here = [(objs[k], objs[0xC0 + k], objs[0xE0 + k]) for k in range(1, 32)
                if objs[k] and (objs[0x40 + k], objs[0x60 + k]) == (z[0x2D], z[0x2E])]
        return z[0x0C], z[0x17], v.mem(0x4AC0, 0x4AC0)[0], here
    try:
        print("Journey Onward, POWERS:", journey(u, patches.POWERS), flush=True)
        for _ in range(3):                  # out of Iolo's hut, to Britannia
            u.push("down")
        keys([ord("O")])
        for _ in range(15):
            u.push("down")
        keys([ord("Y")], 25.0)
        u.joystick_patch()
        z = state(v, "out")
        hook = v.mem(0x8275, 0x8277)
        print(f"the hook at $8275: {hook.hex(' ')}", flush=True)
        bad += z[0x0A] != 0 or hook != bytes([0x20, 0x7A, 0xA4])
        v.shot("build/u5_powers_0.png")
        here = (z[0x2D], z[0x2E])
        said = what(ord("="))
        print("  = says What?:", said, flush=True)
        bad += not said or (v.mem(0x2D, 0x2D)[0], v.mem(0x2E, 0x2E)[0]) != here
        for vehicle, shape, skiffs, hull in (("H", 0x12, None, None), ("S", 0x25, 2, 0x99)):
            if vehicle == "S":              # off the horse X-it left
                u.push("down")
                v.run(2.0)
                z = state(v, "a step south")
                bad += party()[3] != [] or (z[0x2D], z[0x2E]) == here
            keys([ord("B")], 1.0)
            keys([ord(vehicle)], 3.0)
            got = party()
            print(f"B {vehicle}: shape ${got[0]:02x}, skiffs {got[1]}, hull ${got[2]:02x}, here {got[3]}", flush=True)
            bad += got[0] != shape or (skiffs is not None and got[1:3] != (skiffs, hull))
            v.shot(f"build/u5_powers_b{vehicle.lower()}.png")
            keys([ord("X")], 3.0)
            left = party()
            print(f"  X: shape ${left[0]:02x}, here {left[3]}", flush=True)
            bad += left[0] not in (0x1C, 0x1D) or not left[3]
            keys([ord("B")], 3.0)
            again = party()
            print(f"  B: shape ${again[0]:02x}, skiffs {again[1]}, hull ${again[2]:02x}, here {again[3]}", flush=True)
            bad += again[0] != shape or again[3] or (skiffs is not None and again[1:3] != (skiffs, hull))
            keys([ord("X")], 3.0)
            bad += party()[0] not in (0x1C, 0x1D)
        keys([0x88, ord("5"), ord("8"), 0x0D, ord("4"), ord("3"), 0x0D], 1.0)
        v.run(5.0)
        z = state(v, "F7 58 43")
        v.shot("build/u5_powers_1.png")
        bad += (z[0x2D], z[0x2E]) != DEST or (v.mem(0x4A40, 0x4A40)[0], v.mem(0x4A60, 0x4A60)[0]) != DEST
        for typed, codes in (("256", [ord("2"), ord("5"), ord("6")]), ("RETURN", [0x0D]), ("A", [ord("A")])):
            keys([0x88] + codes, 1.0)
            v.run(3.0)
            z = state(v, f"F7 {typed}")
            bad += (z[0x2D], z[0x2E]) != DEST
        keys([ord("Q")], 3.0)
        keys([ord("Y")], 20.0)
        saved = tuple(v.mem(0xBC2B, 0xBC2C))
        print(f"Q: $BC2B/$BC2C = {saved}", flush=True)
        bad += saved != DEST
    finally:
        v.quit()

    u = U5(tcrt=img, log=LOG)
    v = u.v
    try:
        print("Journey Onward, no options:", journey(u, 0), flush=True)
        z = state(v, "after Journey Onward")
        bad += (z[0x2D], z[0x2E]) != DEST
        v.shot("build/u5_powers_2.png")
        said = what(0x88)
        print("  F7 says What?:", said, flush=True)
        z = state(v, "F7 without the option")
        bad += not said or (z[0x2D], z[0x2E]) != DEST
        said = what(ord("B"), BOARD_WHAT_DONE)
        print("  B says What?:", said, flush=True)
        bad += not said or v.mem(0x0C, 0x0C)[0] not in (0x1C, 0x1D)
        keys([ord("E")], 20.0)
        z = state(v, "E")
        v.shot("build/u5_powers_3.png")
        bad += z[0x0A] != 4
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
