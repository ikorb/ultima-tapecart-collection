#!/usr/bin/env python3
"""Boot the collection cart from streaming mode and check the menu works.

    ./menu_check.py                 show the menu
    ./menu_check.py 1 0x6800        auto-pick the game at place 1 (its key:
                                    Ultima I), check it reaches $6800

Loading with an empty name is what SHIFT+RUN/STOP does, so this exercises the
same path as real hardware: the tapecart's initial loader fastloads the menu
and starts it.  No launcher PRG involved.
"""
import os
from ultima import paths
import re
import subprocess
import sys
from pathlib import Path

from ultima.flash.tcrt import TCRT
from ultima.flash import regions

IMAGE = "build/ultima-collection.tcrt"


def symbol(path, name):
    m = re.search(r"^\s*" + name + r"\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text(), re.M)
    if not m:
        raise SystemExit(f"symbol {name} not found")
    return int(m.group(1), 16)


def run(tcrt, break_addr, dump):
    with open("build/mon_menu.txt", "w") as fh:
        fh.write(f'save "{dump}" 0 {break_addr:04x} {break_addr + 0x10:04x}\nquit\n')
    if os.path.exists(dump):
        os.remove(dump)
    subprocess.run(["x64sc", "-warp", "-limitcycles", "600000000",
                    "-tapeport1device", "6", "-tcrt", tcrt,
                    "-initbreak", hex(break_addr),
                    "-moncommands", "build/mon_menu.txt", "-keybuf", "load\n"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=400)
    return os.path.exists(dump)


def with_autokey(key):
    """Splice an auto-selecting menu into the image so a launch can be tested
    without a keypress."""
    subprocess.run(["acme", "-f", "cbm", "-I", paths.ASM,
                    "-I", "build",
                    f"-DMENU_AUTOKEY={key}",
                    "-o", "build/menu_auto.prg", "-l", "build/menu_auto.sym",
                    os.path.join(paths.ASM, "menu.s")], check=True)
    menu = Path("build/menu_auto.prg").read_bytes()
    img = TCRT.read(IMAGE)
    flash = bytearray(img.flash)
    flash[regions.MENU_PRG:regions.MENU_PRG + len(menu)] = menu
    out = "build/auto.tcrt"
    TCRT(data_address=regions.MENU_PRG, data_length=len(menu),
         call_address=symbol("build/menu_auto.sym", "start"),
         filename="ULTIMACOLLECTION", flash=bytes(flash)).write(out, trim=False)
    return out


def main():
    if len(sys.argv) == 1:
        addr = symbol("build/menu.sym", "key_loop")
        ok = run(IMAGE, addr, "build/menu_hit.bin")
        print(f"menu reached its prompt: {'yes' if ok else 'NO'}")
        return 0 if ok else 1

    key, addr = int(sys.argv[1]), int(sys.argv[2], 0)
    ok = run(with_autokey(key), addr, "build/menu_hit.bin")
    print(f"menu launched game {key} -> reached {addr:#06x}: {'yes' if ok else 'NO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
