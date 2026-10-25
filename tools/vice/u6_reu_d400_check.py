#!/usr/bin/env python3
"""Ultima 6 with an REU: does overlay $34 (1A T19 S8-9, loaded to $D400-$D5FF,
the RAM under the I/O) arrive in RAM when the REU cache serves it?

    python -m tools.vice.u6_reu_d400_check SAVE_FILE [--shifts N] [--clobber]

Journey Onward from a copy of the cart with the save imported (as
tools/vice/u6_cart.py), an REU of 512 KB.  Every page the cache is asked for is
logged (a breakpoint at rc_try: the flash address and the destination), and
after each window shift (as u6_shift_bench.py makes them) $D400-$D5FF (bank
ram) is compared with the overlay on the disk -- a shift leaves the save's
BAM in $D500, which is the original's way: only the whole window's reload
(--teleport: game $25A9, what a moongate does) loads the overlay again, and
that has to put it back.  --clobber fills that RAM with
$00 before each shift, as anything else loaded there would leave it: the
reload has to put the overlay back.
"""
import os
from ultima import paths
import re
import sys

os.chdir(paths.ROOT)
from tools.vice import menu_check
from tools.vice import u6_cart as bench
from tools.vice.u6_shift_bench import resume_until, SHIFT, RENDER
from tools.vice.vice_mon import Vice
import importlib.util
from pathlib import Path

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)


def syms():
    out = {}
    for line in Path("build/u6reu.sym").read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(sys.argv[sys.argv.index("--shifts") + 1]) if "--shifts" in sys.argv else 2
    clobber = "--clobber" in sys.argv
    s = syms()
    d1a = u6.D64(u6.disk_path("1A"))
    overlay = d1a.sector(19, 8) + d1a.sector(19, 9)
    menu_check.IMAGE = bench.make_cart(args[0])
    v = Vice(menu_check.with_autokey(6), update_tcrt=False, extra=["-reu", "-reusize", "512"])
    bad = 0
    try:
        v.u6_journey_onward()                                  # Journey onward
        v.run(45.0)
        print("REU found:", v.mem(s["rc_on"], s["rc_on"])[0])
        mem = v.mem(0xD400, 0xD5FF)
        diff = [i for i in range(512) if mem[i] != overlay[i]]
        print("after Journey Onward, overlay bytes differing:", len(diff), [f"{0xD400 + i:04x}" for i in diff[:40]])
        for k in range(n):
            if clobber:
                v.poke(0xD400, bytes(512))
            got = None
            for way in (4, 1, 2, 8):
                v.poke(0x72, b"\x13" if way != 8 else b"\x14")
                v.cmd(f"joystick 2 {way} +6", wait=0.1)
                v.cmd(f"break {SHIFT:04x}", wait=0.1)
                got = resume_until(v, {SHIFT}, None, 8)
                v.cmd("delete", wait=0.2)
                if got:
                    break
            assert got, "no shift"
            v.cmd(f"break {s['rc_try']:04x}", wait=0.1)
            v.cmd(f"break {RENDER:04x}", wait=0.1)
            reads = []
            while True:
                pc, _ = resume_until(v, {s["rc_try"], RENDER}, None, 600)
                if pc == RENDER:
                    break
                a = v.mem(0x2A40, 0x2A46)                     # tc_addr (3), tc_len (2), tc_dest (2)
                reads.append((a[0] | a[1] << 8 | a[2] << 16, a[3] | a[4] << 8, a[5] | a[6] << 8))
            v.cmd("delete", wait=0.2)
            for r in reads:
                print(f"  flash {r[0]:06x} len {r[1]:04x} -> {r[2]:04x}")
            high = [(p, d) for p, n, d in reads if 0xD0 <= d >> 8 <= 0xDF and n == 0x100 and not p & 0xFF]
            mem = v.mem(0xD400, 0xD5FF)
            diff = [i for i in range(512) if mem[i] != overlay[i]]
            print(f"  overlay bytes differing: {len(diff)}", [f"{0xD400 + i:04x}" for i in diff[:12]])
            ok = len(diff) < 40                               # (the save's BAM is there now: the game's own)
            print(f"shift {k}: {len(reads)} whole pages through the cache, "
                  f"{len(high)} to $D000-$DFFF {[f'{d:04x}' for _, d in high]}; overlay $34 in RAM: {ok}")
            v.run(2.0)
        if "--teleport" in sys.argv:
            # what a moongate does: game $25A9 (the party gathered on the leader, the
            # save, the whole window loaded again, overlay $34 last), called from a
            # stub in the free $CFE8 at the main loop's frame wait, back to the loop
            v.cmd("break 0449", wait=0.1)
            resume_until(v, {0x0449}, None, 30)
            v.cmd("delete", wait=0.2)
            v.poke(0xCFE8, bytes([0x20, 0xA9, 0x25, 0x4C, 0x14, 0x04]))
            v.cmd("r pc = cfe8", wait=0.2)
            v.cmd("break 2628", wait=0.1)                  # ldx #$34 / jmp $2C38: the overlay's reload
            print("reached $2628:", bool(resume_until(v, {0x2628}, None, 120)), flush=True)
            v.cmd("delete", wait=0.2)
            v.cmd("break 0449", wait=0.1)
            got = resume_until(v, {0x0449}, None, 30)
            v.cmd("delete", wait=0.2)
            mem = v.mem(0xD400, 0xD5FF)
            diff = [i for i in range(512) if mem[i] != overlay[i]]
            ok = len(diff) < 40
            bad += not ok
            print(f"teleport: overlay bytes differing {len(diff)}; back in the main loop: {bool(got)}")
            v.run(5.0)
            print("PC after 5 s:", hex(bench.sw(v)[0]))
        v.shot("build/u6_reu_d400.png")
    finally:
        v.quit()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
