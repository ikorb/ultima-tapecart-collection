#!/usr/bin/env python3
"""Ultima 6's log compaction, in VICE, from the menu.

    ./u6_compact_check.py [worst]

Seeds U6's save region in a copy of the cart with a log that is nearly full
(u6log.play: a long game's worth of saves; `worst` = every chunk file live),
boots the cart, picks Ultima VI from the menu, and times the init segment
from its entry ($1000) to the cold start ($C00C) on VICE's stopwatch.  A
screenshot is taken mid-compaction.  Then VICE is shut down cleanly so the
flash is written back, and the log the boot driver was handed is read back
out of it and compared with what was seeded.  A second boot must not compact.

Cycle counts are VICE's: the protocol, but not the flash's own erase and
program times, which the emulation does not model.
"""
import os
import random
import re
import sys
from pathlib import Path

from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from tools.vice import menu_check
from ultima.flash import regions
from ultima.launcher import u6log

BUILD = "build"
IMAGE = os.path.join(BUILD, "u6compact.tcrt")


def symbols(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def stopwatch(v):
    out = v.cmd("r", wait=0.5)
    lines = [l for l in out.splitlines() if l.startswith(".;")]
    return int(lines[-1].split()[-1])


def boot(image, bsym, isym, shot=None):
    v = Vice(image, update_tcrt=True)
    try:
        if not v.run_to(0x1000, timeout=120):
            raise SystemExit("the init segment never ran")
        t0 = stopwatch(v)
        if shot:
            if v.run_to(isym["td_page"], timeout=30):
                v.shot(shot)
        if not v.run_to(0xC00C, timeout=600):
            raise SystemExit("the init segment never reached $C00C")
        cycles = stopwatch(v) - t0
        m = v.mem(bsym["u6_logdir"], bsym["u6_logdata"] + 3)
        logdir = m[0] | m[1] << 8 | m[2] << 16
        count = m[3] | m[4] << 8
        o = bsym["u6_logdata"] - bsym["u6_logdir"]
        logdata = m[o] | m[o + 1] << 8 | m[o + 2] << 16
    finally:
        v.quit()                            # clean: the .tcrt is written back
    return cycles, logdir, count, logdata


def main():
    worst = len(sys.argv) > 1 and sys.argv[1] == "worst"
    auto = menu_check.with_autokey(6)
    img = TCRT.read(auto)
    flash = bytearray(img.flash.ljust(regions.FLASH_SIZE, b"\xff"))
    lo, hi = regions.save_base("u6"), regions.REGIONS["u6"][3]
    mid = lo + (hi - lo) // 2
    assert flash[lo:hi] == b"\xff" * (hi - lo), "the image already has a U6 log"
    want = {}
    log = u6log.Log(flash, lo, mid)
    if worst:
        u6log.play(log, random.Random(3), want, 400, files=84, per_save=84, size=(2, 3))
        u6log.play(log, random.Random(4), want, u6log.RESERVE, files=84, per_save=8, size=(2, 3))
    else:
        u6log.play(log, random.Random(6), want, u6log.RESERVE)
    live = sum(len(x) for x in want.values()) // 256
    print(f"seeded: {(log.data - lo) // 256} pages, {len(want)} keys live in {live} pages")
    TCRT(data_address=img.data_address, data_length=img.data_length,
         call_address=img.call_address, filename=img.filename,
         flash=bytes(flash)).write(IMAGE, trim=False)

    bsym = symbols(os.path.join(BUILD, "u6boot.sym"))
    isym = symbols(os.path.join(BUILD, "init_u6.sym"))
    shot = os.path.join(BUILD, "u6compact.png")
    cycles, logdir, count, logdata = boot(IMAGE, bsym, isym, shot)
    print(f"first boot: {cycles} cycles ({cycles / 985248:.1f} s PAL) in the init")
    after = bytearray(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
    ok = True
    if not mid <= logdir < hi:
        print(f"  NOT compacted into half 1: logdir {logdir:#08x}")
        ok = False
    got = u6log.view(after, logdir, count)
    if got != want:
        print(f"  the log differs: {len(got)} keys read back, {len(want)} seeded")
        ok = False
    if after[lo:mid] != b"\xff" * (mid - lo):
        print("  half 0 was not erased")
        ok = False
    if after[logdata:logdir] != b"\xff" * (logdir - logdata):
        print("  the free space is not erased")
        ok = False
    print(f"  compacted: {'yes' if ok else 'NO'}, screenshot {shot}")

    cycles2, logdir2, count2, _ = boot(IMAGE, bsym, isym)
    print(f"second boot: {cycles2} cycles in the init, "
          f"{'unchanged' if (logdir2, count2) == (logdir, count) else 'CHANGED'}")
    return 0 if ok and (logdir2, count2) == (logdir, count) else 1


if __name__ == "__main__":
    sys.exit(main())
