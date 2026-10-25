#!/usr/bin/env python3
"""The host tests' RAM fixtures (tests/data), captured in VICE from the cart
the disks build -- no saved game needed, nothing of the disks shipped.

    python -m tools.vice.fixtures [u3] [u4] [u5] [u6]      (all by default)

Needs `make` first (build/ultima-collection.tcrt) and VICE with the key
matrix monitor commands (3.11 or later).  Each game runs from a copy of the
cart; the tests that use a fixture skip without it.

u3_screen.bin       Ultima III: a party of one made (u3_drive.start), screen
                    RAM $0400-$07FF in play on Sosaria (test_u3_peer).
u4_title_frame.bin  Ultima IV with Remastered's tile set (the option's pokes
                    at the init stub): the bitmap $2000-$3F3F and screen RAM
                    $0400-$07E7 at the renderer's second frame of the title's
                    view (break at $6B83), the first after the dissolve
                    (test_u4_tileset).
u5_britannia.bin    Ultima V: a character made (Create New Character, every
u5_town.bin         answer A), which saves in Iolo's hut.  Its PRTY.DATA's
                    place outside the hut moved to (58,44); Journey Onward,
                    out of the hut there, a turn passed, sound off: RAM at
                    the key read (u5_britannia.bin).  One step north onto
                    Yew (58,43, the game's own table), Enter, Quit and save;
                    at noon, one step west, sound off: RAM at the key read
                    (u5_town.bin).  For test_u5_fast.
u6_castle_0.bin     Ultima VI: Journey Onward from the cart's base, the party
u6_castle_21.bin    in Lord British's castle; RAM at the main loop's turn
                    start ($0449) after 0 and 21 turns with the joystick
                    held south -- with `game`'s original bytes put back where
                    the speed patches go, which the tests lay on themselves
                    (test_u6_fast, test_u6_init, test_u6_chunk).
"""
import os
import shutil
import sys
import time
from pathlib import Path

from ultima import paths
os.chdir(paths.ROOT)
from ultima.disks.d64 import D64
from ultima.flash import regions
from ultima.flash.tcrt import TCRT
from tools.vice import menu_check
from tools.vice.vice_mon import Vice

CART = "build/ultima-collection.tcrt"
DATA = os.path.join(paths.ROOT, "tests", "data")


def out(name):
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)


def stop(v, timeout=30):
    seen, end = "", time.time() + timeout
    while "Stop on" not in seen and time.time() < end:
        seen += v._drain(0.2)
    return "Stop on" in seen


def resume(v, timeout=30):
    v.sock.sendall(b"x\n")
    return stop(v, timeout)


# ---- Ultima III -------------------------------------------------------------
def u3():
    from tools.vice import u3_drive
    v = u3_drive.start()
    try:
        v.cmd("bank ram", wait=0.2)
        Path(out("u3_screen.bin")).write_bytes(v.mem(0x0400, 0x07FF))
        v.shot("build/fixture_u3.png")
    finally:
        v.kill()


# ---- Ultima IV --------------------------------------------------------------
def u4():
    from ultima.games.u4 import build as u4b
    from ultima.launcher import patches
    pokes = u4b.parts()["options"]["pokes"][patches.TILES]
    menu_check.IMAGE = CART
    v = Vice(menu_check.with_autokey(4), update_tcrt=False)
    try:
        assert v.run_to(0x0200, timeout=90), "U4's init stub never ran"
        for addr, value in pokes:
            v.poke(addr, bytes([value]))
        v.cmd("break 6b83", wait=0.2)
        for _ in range(2):              # the dissolve's frame, then the renderer's
            assert resume(v, 90), "the title's view was never drawn"
        v.cmd("bank ram", wait=0.2)
        frame = bytes(v.mem(0x2000, 0x3F3F)) + bytes(v.mem(0x0400, 0x07E7))
        Path(out("u4_title_frame.bin")).write_bytes(frame)
        v.shot("build/fixture_u4.png")
    finally:
        v.kill()


# ---- Ultima V ---------------------------------------------------------------
PRTY_XY = (45, 62)          # where the hut lets a new character out
YEW_SOUTH = (58, 44)        # one south of Yew


def u5_create(image):
    """Create New Character on a copy of the cart; the game saves the new
    character (in Iolo's hut) as it starts the story: that image."""
    from tools.vice.u5_drive import U5
    menu_check.IMAGE = CART
    u = U5(menu_check.with_autokey(5))
    v = u.v
    try:
        assert u.boot_to_menu() and u.menu_pick(1), "no Create New Character"
        for k in list(b"AVATAR\r") + list(b"M") + list(b"A" * 20):
            u.key(k)
            end = time.time() + 120
            while v.mem(0xC6, 0xC6)[0] and time.time() < end:
                v.run(0.5)
            assert not v.mem(0xC6, 0xC6)[0], f"key {k:02x} never taken"
            v.run(0.7)
        v.run(20.0)                     # into the story: the save is written
    finally:
        v.quit()
    shutil.copy("build/auto.tcrt", image)


def prty_data(flash):
    """PRTY.DATA's slot in the U5 save region: found by the new character's
    way out of the hut."""
    lo, hi = regions.save_region("u5")
    at = flash.find(bytes([0x0F, 0x0F, 0x00, 0x00, *PRTY_XY]), lo, hi)
    assert at >= 0, "no PRTY.DATA with the hut's way out"
    return at


def u5_at_key(u, call):
    """Stop at the key read (JSR $4C15 at `call`), a breakpoint left on it.
    The game waits for a key -- in the read, or after a save in main.twn's
    wait at $922F -- and a Space gets it out: a turn passes, or the wait
    ends; then the main loop comes to the read."""
    v = u.v
    v.cmd(f"break {call:04x}", wait=0.2)
    u.key(ord(" "))
    assert resume(v, 20), "the key read never came"


def u5_step(v, ret, a):
    """One step from the key read's stop: skip the read (PC to `ret`, the
    instruction after it) with the direction in A, run to the read again."""
    v.cmd(f"r pc = {ret:04x}", wait=0.2)
    v.cmd(f"r a = ${a:02x}", wait=0.2)             # "af" is a register pair to the monitor
    assert resume(v, 60), "no key read after a step"


def u5_ram(u, name):
    """RAM at the key read's stop, with the sound off ($78 = 0, as the
    game's own switch does); $78 put back after."""
    v = u.v
    sound = v.mem(0x78, 0x78)
    v.poke(0x78, b"\x00")
    v.cmd("bank ram", wait=0.2)
    path = out(name)
    if os.path.exists(path):
        os.remove(path)
    v.cmd(f'bsave "{path}" 0 0000 ffff', wait=2.0)
    v.poke(0x78, bytes(sound))
    assert os.path.getsize(path) == 0x10000, f"{name}: no RAM saved"


def u5_yew(created, image):
    """The created character let out south of Yew (u5_britannia.bin) and
    saved in Yew (that image), then at noon a step into the town
    (u5_town.bin)."""
    from tools.vice.u5_drive import U5
    from tools.vice.xfer_file_check import with_flash
    flash = bytearray(TCRT.read(created).flash.ljust(regions.FLASH_SIZE, b"\xff"))
    p = prty_data(flash)
    flash[p + 4:p + 6] = bytes(YEW_SOUTH)
    menu_check.IMAGE = with_flash(flash, "build/fixture_u5yew.tcrt")
    u = U5(menu_check.with_autokey(5))
    v = u.v
    try:
        assert u.boot_to_menu() and u.menu_pick(0), "no Journey Onward"
        v.run(25.0)
        u.joystick_patch()
        for _ in range(3):              # out of the hut, as u5_step_bench.py
            u.push("down")
        u.key(ord("O"))
        v.run(1.0)
        for _ in range(15):
            u.push("down")
        u.key(ord("Y"))
        v.run(25.0)
        assert tuple(v.mem(0x2D, 0x2E)) == YEW_SOUTH, "not let out south of Yew"
        u5_at_key(u, 0x810A)            # main.out's key read
        u5_ram(u, "u5_britannia.bin")
        u5_step(v, 0x810D, 0xC0)        # north
        v.cmd("delete", wait=0.2)
        v.run(1.0)
        u.key(ord("E"))
        v.run(20.0)
        assert v.mem(0x0A, 0x0A)[0] == 4, "not in Yew"
        u.key(ord("Q"))
        v.run(3.0)
        u.key(ord("Y"))
        v.run(20.0)
        # the save is in the flash: the town's fixture after it, at noon
        # (BCD; $57DE sees the hour change at the next turn, the step works
        # out the light radius $0E again)
        v.poke(0x1E, b"\x12")
        u5_at_key(u, 0x8263)            # main.twn's key read
        at = tuple(v.mem(0x2D, 0x2E))
        u5_step(v, 0x8266, 0xBA)        # west
        assert v.mem(0x0A, 0x0A)[0] == 4, "not in Yew"
        assert tuple(v.mem(0x2D, 0x2E)) == ((at[0] - 1) & 255, at[1]), "no step west"
        u5_ram(u, "u5_town.bin")
        v.cmd("delete", wait=0.2)
        v.shot("build/fixture_u5town.png")
    finally:
        v.quit()
    shutil.copy("build/auto.tcrt", image)


def u5():
    created = "build/fixture_u5created.tcrt"
    u5_create(created)
    u5_yew(created, "build/fixture_u5yew_saved.tcrt")


# ---- Ultima VI --------------------------------------------------------------
U6_TURNS = (0, 21)


def u6():
    from ultima.games.u6 import build as u6b
    game, ok = D64(paths.disk("u6-3b")).file("GAME")
    assert ok and game[0] | game[1] << 8 == u6b.GAME_ADDR
    menu_check.IMAGE = CART
    v = Vice(menu_check.with_autokey(6), update_tcrt=False)
    rams = {}
    try:
        v.u6_journey_onward()
        v.run(45.0)
        v.cmd("break 0449", wait=0.1)
        v.cmd("joystick 2 2 +100000", wait=0.1)
        turn = 0
        for n in U6_TURNS:
            while turn < n:
                assert resume(v, 20)
                turn += 1
            assert resume(v, 20)
            v.cmd("bank ram", wait=0.2)
            path = os.path.abspath(f"build/fixture_u6_{n}.bin")
            if os.path.exists(path):
                os.remove(path)
            v.cmd(f'bsave "{path}" 0 0000 ffff', wait=2.0)
            rams[n] = bytearray(Path(path).read_bytes())
        v.cmd("delete", wait=0.2)
        v.shot("build/fixture_u6.png")
    finally:
        v.quit()
    for n, ram in rams.items():
        assert len(ram) == 0x10000
        for addr, data in u6b.assemble_fast():
            o = addr - u6b.GAME_ADDR + 2
            ram[addr:addr + len(data)] = game[o:o + len(data)]
        Path(out(f"u6_castle_{n}.bin")).write_bytes(ram)


GAMES = {"u3": u3, "u4": u4, "u5": u5, "u6": u6}


def main():
    which = sys.argv[1:] or list(GAMES)
    if not os.path.exists(CART):
        raise SystemExit(f"no {CART}: make it first")
    for g in which:
        print(f"{g}...", flush=True)
        GAMES[g]()
    print("fixtures in", DATA)


if __name__ == "__main__":
    main()
