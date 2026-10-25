#!/usr/bin/env python3
"""The page's export to a file and import from it, in VICE with a real 1541
(true drive emulation) -- what tests/test_file_xfer.py checks on a model.

    python -m tools.vice.xfer_file_check [--bounce] [--drive N] [u1 u2 ...]   (default: all six)

Per game: the cart with test_page's seeded save for it; the menu, its page,
E F Y RETURN onto a blank disk; the file on the disk is compared with what
the host model writes for the same cart.  Then a fresh cart with that disk:
I F Y RETURN, and the save region it leaves (written back to the .tcrt on
VICE's clean exit) compared with the seeded one -- Ultima II's and VI's logs
by what they hold, the rest byte for byte.  --drive 9 (10, 11): the disk is
that drive, picked with D at the prompt.  --bounce: E/I, F and Y each
pressed twice, 3 frames apart, as a bouncing key does.  Keys through the keyboard matrix
(vice_mon.tap).  Needs VICE 3.11 or later.  About a minute a game.
"""
import os
from ultima import paths
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)

from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from ultima.flash import regions
from tests import test_page
from tests import test_xfer
from tests import test_file_xfer
from ultima.sim.fakedrive import Disk

IMAGE = "build/ultima-collection.tcrt"
LIST = ["u1", "u2", "u3", "u4", "u5", "u6"]        # the menu's order: keys 1-6
OUT = "build/xfercheck"


def with_flash(flash, path):
    img = TCRT.read(IMAGE)
    img.flash = bytes(flash)
    img.write(path, trim=False)
    return path


def launcher_text(v):
    """The launcher's screen ($4400) as text."""
    d = v.mem(0x4400, 0x4400 + 999)
    rows = []
    for r in range(25):
        row = ""
        for c in d[r * 40:(r + 1) * 40]:
            c &= 0x7F
            row += chr(c + 0x60) if 1 <= c <= 26 else chr(c) if 0x20 <= c < 0x60 else " "
        rows.append(row.rstrip())
    return "\n".join(rows)


def wait_for(v, words, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        v.run(1)
        text = launcher_text(v)
        if any(w.lower() in text.lower() for w in words):
            return text
    raise RuntimeError(f"no {words} on the screen:\n{launcher_text(v)}")


DRIVE = 8
BOUNCE = False


def press(v, key):
    v.tap(key, frames=2, gap=0.06 if BOUNCE else 1)
    if BOUNCE:
        v.tap(key, frames=2, gap=1)


def session(tcrt, disk, game, keys, port):
    """Boot the cart, open the game's page, press E/I F Y RETURN; returns
    the screen at the end."""
    v = Vice(tcrt, port=port, update_tcrt=True,
             extra=[f"-{DRIVE}", disk, f"-drive{DRIVE}type", "1541",
                    f"-drive{DRIVE}truedrive"])
    try:
        wait_for(v, ["Select a game"], 60)
        for attempt in range(5):            # (a key too early is not seen)
            v.tap(str(LIST.index(game) + 1), gap=1)
            try:
                wait_for(v, ["B  Back"], 10)
                break
            except RuntimeError:
                if attempt == 4:
                    raise
        press(v, keys[0])
        press(v, "f")
        wait_for(v, ["(Y/N)"], 30)
        press(v, "y")
        wait_for(v, ["press RETURN"], 30)
        for _ in range(4):                  # D: the next drive, until it is ours
            if f"in drive {DRIVE} and" in launcher_text(v):
                break
            v.tap("d", gap=1)
        v.tap("\r", gap=1)
        return wait_for(v, ["Done.", "Failed", "The file is", "That "], 600)
    finally:
        v.quit()


def check(game, port):
    os.makedirs(OUT, exist_ok=True)
    fresh = bytes(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
    src = bytearray(fresh)
    test_page.SEEDS[game](src, test_page.page_syms())
    disk = os.path.join(OUT, f"{game}.d64")
    with open(disk, "wb") as fh:
        fh.write(test_xfer.blank_d64(b"SAVES"))
    text = session(with_flash(src, os.path.join(OUT, f"{game}_src.tcrt")), disk, game, "e", port)
    ok = "Done." in text
    name = test_file_xfer.NAMES[game]
    got = Disk(Path(disk).read_bytes()).read_file(name)
    # the host model's file for the same cart
    t = test_file_xfer.TestFileXfer if game != "u6" else test_file_xfer.TestU6File
    t.setUpClass()
    c = t("run")
    want = (c.export_file(src, game) if game != "u6" else c.export_file(src)).read_file(name)
    same = got == want
    print(f"{game}: export {'done' if ok else 'FAILED'}; the file {len(got or b'')} bytes, "
          f"{'as the host model writes it' if same else 'NOT as the host model writes it'}")
    # into a fresh cart
    dst = with_flash(fresh, os.path.join(OUT, f"{game}_dst.tcrt"))
    text = session(dst, disk, game, "i", port + 2)
    done = "Done." in text
    flash = TCRT.read(dst).flash.ljust(regions.FLASH_SIZE, b"\xff")
    lo, hi = regions.save_region(game)
    if game == "u6":
        u = test_file_xfer.TestU6File("run")
        equal = test_file_xfer.contents_of(u, flash) == test_file_xfer.contents_of(u, src)
    elif game == "u2":
        tx = test_file_xfer.TestFileXfer("run")
        equal = all(tx.slot_bytes(flash, sl) == tx.slot_bytes(src, sl)
                    for xd in tx.xfer(game) for sl in xd.slots)
    else:
        equal = bytes(flash[lo:hi]) == bytes(src[lo:hi])
    print(f"{game}: import {'done' if done else 'FAILED'}; the save "
          f"{'is the exported one' if equal else 'DIFFERS from the exported one'}")
    if not (ok and same and done and equal):
        print(text)
    return ok and same and done and equal


def main():
    global DRIVE, BOUNCE
    args = sys.argv[1:]
    if args[:1] == ["--bounce"]:
        BOUNCE, args = True, args[1:]
    if args[:1] == ["--drive"]:
        DRIVE, args = int(args[1]), args[2:]
    games = args or LIST
    results = [check(g, 6540 + 4 * i) for i, g in enumerate(games)]
    print("all as on the host" if all(results) else "DIFFERENCES")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
