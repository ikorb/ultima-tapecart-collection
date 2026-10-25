#!/usr/bin/env python3
"""Ultima VI's page and the REU (asm/page_reu.s), in VICE: the page with
REUs of several sizes and with none, read off the screen; then, with a
512 KB one, the game launched from the page (Journey onward) and its init's
verdict read from RAM: rc_on and part A in u6_bulkfl (the write cache on).

    python -m tools.vice.page_reu_check

Screenshots in build/pagereu_*.png; prints the REU lines and "all good".
"""
import os
from ultima import paths

os.chdir(paths.ROOT)

import importlib.util
from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from ultima.flash import regions
from tests import test_page
from tools.vice.xfer_file_check import launcher_text, wait_for, with_flash

IMAGE = "build/pagereu.tcrt"
_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)


def open_page(v):
    wait_for(v, ["Select a game"], 60)
    for attempt in range(5):
        v.tap("6", gap=1)
        try:
            wait_for(v, ["B  Back"], 10)
            break
        except RuntimeError:
            if attempt == 4:
                raise
    v.run(1)
    return launcher_text(v).split("\n")


def main():
    flash = bytearray(TCRT.read("build/ultima-collection.tcrt").flash.ljust(regions.FLASH_SIZE, b"\xff"))
    test_page.seed_u6(flash, test_page.page_syms())     # a saved game: J is offered
    image = with_flash(flash, IMAGE)
    want = {512: ["   REU: 512 KB, for loads and saves"],
            16384: ["   REU: 16384 KB, for loads and saves"],
            128: ["   REU: 128 KB, too small to use"],
            None: []}
    good = True
    for kb, lines in want.items():
        extra = ["-reu", "-reusize", str(kb)] if kb else ["+reu"]
        v = Vice(image, port=6530 + 2 * list(want).index(kb), extra=extra)
        try:
            page = open_page(v)
            v.shot(f"build/pagereu_{kb or 'none'}.png")
            got = [l.rstrip() for l in page if "REU" in l or "verify" in l]
            print(f"{kb or 'no'} REU: {got}")
            good &= got == lines
            if kb == 512:
                # launch it: J (Journey onward), and the init's verdict once it has run
                rsym = u6.symbols("build/u6res.sym")
                reusym = u6.symbols("build/u6reu.sym")
                v.tap("j", gap=1)
                v.run(60)
                rc_on = v.mem(reusym["rc_on"], reusym["rc_on"])[0]
                fl = v.mem(rsym["u6_bulkfl"], rsym["u6_bulkfl"] + 6)
                v.shot("build/pagereu_game.png")
                p = u6.parts()
                a = p["reua_at"]
                part_a = bytes([a[0xDC00] >> 16, a[0xDC00] >> 8 & 0xFF, a[0xDC00] & 0xFF, 0xFF,
                                a[0xD800] >> 16, a[0xD800] >> 8 & 0xFF, a[0xD800] & 0xFF])
                print(f"  launched: rc_on = {rc_on}, u6_bulkfl = {fl.hex(' ')} "
                      f"({'part A: the write cache on' if fl == part_a else 'NOT part A'})")
                good &= rc_on == 1 and fl == part_a
        finally:
            v.quit()
    print("all good" if good else "FAILED")
    if not good:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
