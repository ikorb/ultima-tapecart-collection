#!/usr/bin/env python3
"""A save edited by the save editor, played: Ultima IV in VICE.

    python -m tools.vice.editor_vice_check [--tcrt]

The seeded U4 save exported by the page (host model), edited by the editor's
code (editor/cli.ts: the Avatar's strength 25, gold 4321), put on a blank disk
in a 1541 (true drive emulation); a fresh cart imports it through the page
(I, F, Y, RETURN -- xfer_file_check.py's session), then a second session
launches U4 with J and parks at game main's key read ($408F): the edited
values must be in the game's RAM (chunk $80 at $AA00: the Avatar's strength
at $AA13, gold at $AB13), and a screenshot of the Ztats screen is taken
(build/editor-vice/ztats.png).  Needs node and VICE 3.11 or later.

With --tcrt the edit is made in the cart image itself (cli.ts set CART OUT
--game=4: what an emulator user does), with no disk and no import; the
edited image is booted as it is.
"""
import os
from ultima import paths
import subprocess
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)

from ultima.flash import regions
from tests import test_file_xfer as T
from tools.vice import xfer_file_check as X
from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice

OUT = "build/editor-vice"
MAIN_LOOP = 0x408F


def main():
    os.makedirs(OUT, exist_ok=True)
    T.TestFileXfer.setUpClass()
    tx = T.TestFileXfer("run")
    f0 = tx.export_file(tx.seeded("u4"), "u4").read_file(T.NAMES["u4"])
    with open(f"{OUT}/u4.seq", "wb") as fh:
        fh.write(f0)
    r = subprocess.run(["node", "editor/cli.ts", "set", f"{OUT}/u4.seq", f"{OUT}/u4_edited.seq",
                        "p0.str=25", "gold=4321"], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr)
    edited = Path(f"{OUT}/u4_edited.seq").read_bytes()
    if "--tcrt" in sys.argv:
        seeded = X.with_flash(bytes(tx.seeded("u4")), f"{OUT}/u4_seeded.tcrt")
        cart = f"{OUT}/u4_edited.tcrt"
        r = subprocess.run(["node", "editor/cli.ts", "set", seeded, cart, "p0.str=25", "gold=4321", "--game=4"],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr)
        imported = r.returncode == 0
    else:
        disk = f"{OUT}/u4.d64"
        with open(disk, "wb") as fh:
            fh.write(T.with_file(T.NAMES["u4"], edited))
        fresh = bytes(TCRT.read(X.IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cart = X.with_flash(fresh, f"{OUT}/u4.tcrt")
        text = X.session(cart, disk, "u4", "i", 6620)
        imported = "Done." in text
        print("imported:", imported)
        time.sleep(1.0)

    v = Vice(cart, port=6624)
    ok = False
    try:
        X.wait_for(v, ["Select a game"], 60)
        for _ in range(5):
            v.tap("4", gap=1)
            try:
                X.wait_for(v, ["B  Back"], 10)
                break
            except RuntimeError:
                pass
        v.tap("j", gap=1)
        print("game main:", v.run_to(MAIN_LOOP, timeout=180))
        v.cmd("bank ram", wait=0.2)
        ram = v.mem(0xAA00, 0xAB20)
        strength, gold = ram[0x13], ram[0x113:0x115]
        print(f"the Avatar's strength ${strength:02x}, gold {bytes(gold).hex()}")
        ok = strength == 0x25 and bytes(gold) == b"\x43\x21"
        v.cmd("bank cpu", wait=0.2)
        v.tap("z", gap=1.5)
        v.tap("1", gap=2.0)
        v.run(2.0)
        v.shot(f"{OUT}/ztats.png")
    finally:
        v.quit()
    good = imported and ok
    print("all good" if good else "FAILED")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
