#!/usr/bin/env python3
"""The launcher's page as the real KERNAL draws it, in VICE: Ultima IV's
longest page (eight in the party, tests/test_page.seed_u4_full), the
options toggled in place (F, X, G: one line each, nothing redrawn), and the
Reset question in the rows below the options.

    python -m tools.vice.page_look_check

Screenshots in build/pagelook_*.png; prints the screens and "all good".
"""
import os
from ultima import paths
import sys

os.chdir(paths.ROOT)

from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from ultima.flash import regions
from tests import test_page
from tools.vice.xfer_file_check import launcher_text, wait_for, with_flash

IMAGE = "build/pagelook.tcrt"


def main():
    flash = bytearray(TCRT.read("build/ultima-collection.tcrt").flash.ljust(regions.FLASH_SIZE, b"\xff"))
    test_page.seed_u4_full(flash, test_page.page_syms())
    v = Vice(with_flash(flash, IMAGE), port=6530)
    good = True
    try:
        wait_for(v, ["Select a game"], 60)
        for attempt in range(5):
            v.tap("4", gap=1)
            try:
                page = wait_for(v, ["B  Back"], 10)
                break
            except RuntimeError:
                if attempt == 4:
                    raise
        v.run(1)
        page = launcher_text(v).split("\n")
        v.shot("build/pagelook_page.png")
        print("\n".join(page))
        good &= page[0].strip().lower() == "ultima iv" and "KATRINA" in "\n".join(page).upper()
        good &= page[2].upper().startswith("   AVATARNAMELONGX")
        for key in "fxg":
            v.tap(key, frames=2, gap=1.5)
        after = launcher_text(v).split("\n")
        v.shot("build/pagelook_toggled.png")
        changed = [i for i, (a, b) in enumerate(zip(page, after)) if a != b]
        print("changed rows:", changed)
        for i in changed:
            print(f"  {page[i]!r}\n  {after[i]!r}")
        good &= len(changed) == 3
        good &= any(r.endswith("walking:   off") for r in after)
        good &= any(r.endswith("win:  on") for r in after)
        good &= any(r.endswith("Graphics: remastered".lower()) or r.lower().endswith("graphics: remastered") for r in after)
        v.tap("r", frames=2, gap=1.5)
        ask = launcher_text(v).split("\n")
        v.shot("build/pagelook_reset.png")
        print("\n".join(ask))
        good &= "reset the saved game to a new one?" in "\n".join(ask).lower() and ask[0] == after[0]
        v.tap("n", frames=2, gap=2)
        good &= launcher_text(v).split("\n") == after
    finally:
        v.quit()
    print("all good" if good else "FAILED")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
