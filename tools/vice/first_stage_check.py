#!/usr/bin/env python3
"""The first stage (asm/boot.s) in VICE, from copies of the built cart.

    python -m tools.vice.first_stage_check

1. A normal power-on: the loadinfo loads the first stage, which loads the
   launcher; the menu starts, its list on screen.
2. A cart whose settings page carries another save layout: the message,
   and no menu.
3. A journal a power cut left (a U4 slot's new save, with its header): the
   first stage copies it into the slot and erases the journal before the
   menu starts -- read back from the .tcrt VICE writes on a clean exit.
"""
import os
from ultima import paths
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)
from ultima.flash import regions
from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice

IMAGE = "build/ultima-collection.tcrt"


def symbols(path):
    import re
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}


def copy_with(path, patch):
    img = TCRT.read(IMAGE)
    flash = bytearray(img.flash.ljust(regions.FLASH_SIZE, b"\xff"))
    patch(flash)
    TCRT(data_address=img.data_address, data_length=img.data_length,
         call_address=img.call_address, filename="ULTIMACOLLECTION",
         flash=bytes(flash)).write(path, trim=False)
    return path


def main():
    menu = symbols("build/menu.sym")["start"]
    halt = symbols("build/boot.sym")["halt"]
    fails = []

    # 1. a normal power-on
    v = Vice(copy_with("build/boot_ok.tcrt", lambda f: None))
    try:
        t0 = time.time()
        ok = v.run_to(menu, timeout=60)
        prg = regions.launcher_prg(TCRT.read(IMAGE).flash)
        got = bytes(v.mem(0x4800, 0x4800 + len(prg) - 3))
        loaded = got == prg[2:]
        v.run(2.0)
        v.shot("build/boot_ok.png")
        print(f"1. power-on: menu started {ok}, launcher in RAM {loaded}")
        if not (ok and loaded):
            fails.append("power-on")
    finally:
        v.quit()

    # 2. another save layout
    def wrong(f):
        f[regions.SETTINGS + regions.SET_LAYOUT] = regions.LAYOUT + 1
    v = Vice(copy_with("build/boot_wrong.tcrt", wrong))
    try:
        stopped = v.run_to(halt, timeout=60)
        text = " ".join(v.screen()).lower()
        v.go(0.5)                       # (a frame drawn: warp's last one may predate the text)
        v.cmd("", wait=0.3)
        v.shot("build/boot_wrong.png")
        said = "laid out" in text and "write tcrt" in text
        print(f"2. another layout: stopped {stopped}, message {said}")
        if not (stopped and said):
            fails.append("stamp")
    finally:
        v.quit()

    # 3. a journal to finish
    slot = regions.save_base("u4") + 0x1000
    jn, _ = regions.journal("u4")
    page = bytes((i * 13 + 1) & 0xFF for i in range(256))

    def journal(f):
        f[jn:jn + 0x1000] = b"\xff" * 0x1000
        f[jn:jn + 4] = b"JN" + (slot >> 8).to_bytes(2, "little")
        f[jn + 0x100:jn + 0x200] = page
    path = copy_with("build/boot_journal.tcrt", journal)
    v = Vice(path, update_tcrt=True)
    try:
        ok = v.run_to(menu, timeout=60)
        v.run(1.0)
    finally:
        v.quit()
    time.sleep(1.0)
    flash = TCRT.read(path).flash
    copied = bytes(flash[slot:slot + 256]) == page and set(flash[slot + 256:slot + 0x1000]) == {0xFF}
    erased = set(flash[jn:jn + 0x1000]) == {0xFF}
    print(f"3. a journal: menu started {ok}, copied into the slot {copied}, journal erased {erased}")
    if not (ok and copied and erased):
        fails.append("journal")

    print("all good" if not fails else f"FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
