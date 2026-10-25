#!/usr/bin/env python3
"""Ultima 5: what one unblocked step costs, in VICE cycles, and where it goes.

    python -m tools.vice.u5_step_bench out [steps] [dirs] [--via DIRS] [--quiet] [--noon | --hour BCD] [--profile] [--c128] [--image TCRT]
    python -m tools.vice.u5_step_bench town [steps] [dirs] [--via DIRS] [--quiet] [--noon | --hour BCD] [--profile] [--c128] [--image TCRT]

The images: a cart with a character saved in Iolo's hut ("out") or in a
town ("town").  tools/vice/fixtures.py makes both from the built cart
(build/fixture_u5created.tcrt, build/fixture_u5yew_saved.tcrt, the
defaults); --image another, e.g. one seeded from a saved game's disks
(U5_SAVE_FROM=DIR python -m ultima.build OUT.tcrt, DIR holding its
u5-2a.d64 and u5-2b.d64; with U5_NO_FAST=1 as well the original routines,
for a before/after).

"out": Journey Onward, out of the hut (south x3, O + south, south until
"Dost thou wish to leave?", Y), then the steps in Britannia.  "town":
Journey Onward, the steps there.

A step: the game waits for a key inside `JSR $4C15` (main.out $810A,
main.twn $8263; U5 has no idle pass), so a joystick push gets it out once,
and from then on each step stops at that JSR, skips it -- PC to the
instruction after it (main.out $810D, main.twn $8266) with the direction in
A as the joystick table $5C2C gives it ($BB east, $BA west, $C0 north, $AF
south) -- and runs to the JSR again on the monitor's stopwatch.  The time
spent waiting for the key is not counted.  `dirs` (e/w/n/s) is cycled;
--via walks a route first, untimed, retrying a square until it is reached.

--quiet turns the sound effects off ($78 = 0, as the game's own switch
does): the walking sound, effect 7 from main.out $82E4, is ~54k cycles a
step, ~42k of them a fixed pause between two clicks.  --noon sets the hour
($1E, BCD) to 12 before the walk (give --via at least one step, so the light
radius $0E is worked out again before the timed steps).  With --profile the
monitor's profiler runs over all the timed steps; the flat list, call graph,
the top functions' callers/callees and per-instruction counts go to
build/u5step_<mode>[_quiet]_*.txt, and RAM (bank ram) after the last step to
..._ram.bin.  PAL: 985,248 cycles a second.  The numbers are in docs/developer/u5.md.
--c128: the same in C128 mode (x128, build/u5c128.d64 from make play128).
"""
import os
from ultima import paths
import re
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)
from tools.vice import menu_check
from tools.vice.u5_drive import U5

PAL = 985248
DIRS = {"e": 0xBB, "w": 0xBA, "n": 0xC0, "s": 0xAF}
MODES = {
    # image, key read call, key returned
    "out": ("build/fixture_u5created.tcrt", 0x810A, 0x810D),
    "town": ("build/fixture_u5yew_saved.tcrt", 0x8263, 0x8266),   # main.twn, the same on 3A-4B
}


def sw(v):
    out = v.cmd("r", wait=0.4)
    m = re.search(r"^\.;(\w{4}).*?\s(\d+)\s*$", out, re.M)
    return int(m.group(1), 16), int(m.group(2))


def stop(v, timeout=30):
    seen, t = "", time.time()
    while "Stop on" not in seen and time.time() - t < timeout:
        seen += v._drain(0.2)
    return "Stop on" in seen


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1)
            if not a.startswith("--") and sys.argv[i - 1] not in ("--via", "--image", "--hour")]
    profile = "--profile" in sys.argv
    quiet = "--quiet" in sys.argv
    noon = "--noon" in sys.argv
    mode = args[0]
    nsteps = int(args[1]) if len(args) > 1 else 10
    dirs = args[2] if len(args) > 2 else "e"
    via = sys.argv[sys.argv.index("--via") + 1] if "--via" in sys.argv else ""
    image, call, ret = MODES[mode]
    if "--image" in sys.argv:
        image = sys.argv[sys.argv.index("--image") + 1]
    if len(args) > 3:
        call, ret = int(args[3], 16), int(args[4], 16)
    c128 = "--c128" in sys.argv
    times = []
    if c128:
        # C128 mode: the launcher from build/u5c128.d64 (make play128), Journey
        # Onward by xyzzy's C128 J test ($20F8 LDA $D5 -> LDA #$22); keys and
        # the joystick through VICE's own commands (the C128's queue and page 3
        # are not the C64's)
        import shutil
        from tools.vice.vice_mon import Vice
        shutil.copy(image, "build/u5step_128.tcrt")
        v = Vice("build/u5step_128.tcrt", emu="x128", update_tcrt=False,
                 extra=["-8", os.path.abspath("build/u5c128.d64")],
                 keybuf='run"ultima v 128"\n', log=f"build/u5step_{mode}_128.log")
        u = None

        def push(direction):
            v.joystick(2, {"down": 2, "up": 1, "left": 4, "right": 8, "fire": 0x10}[direction], 30)
            v.run(1.0)

        def key(ch):
            v.tap(ch.lower(), frames=6, gap=1.0)
    else:
        menu_check.IMAGE = image
        u = U5(menu_check.with_autokey(5), log=f"build/u5step_{mode}.log")
        v = u.v
        push = u.push

        def key(ch):
            u.key(ord(ch))
    try:
        if c128:
            print("xyzzy:", v.run_to(0x20F8, timeout=240), flush=True)
            v.poke(0x20F8, bytes([0xA9, 0x22]))
            v.run(40.0)
        else:
            print("menu:", u.boot_to_menu(), flush=True)
            print("journey:", u.menu_pick(0), flush=True)
            v.run(25.0)
            u.joystick_patch()
        if mode == "out":
            for _ in range(3):
                push("down")
            key("O")
            v.run(1.0)
            push("down")
            for _ in range(14):
                push("down")
            key("Y")
            v.run(25.0)
        shot = v.vic_shot if c128 else v.shot      # (x128's screenshot is the VDC's)
        shot(f"build/u5step_{mode}_start.png")
        zp = v.mem(0x00, 0x2F)
        print(f"pos {zp[0x2D]},{zp[0x2E]}  location $0A {zp[0x0A]:02x}  level $09 {zp[0x09]:02x}  "
              f"transport $0C {zp[0x0C]:02x}  hour $1E {zp[0x1E]:02x}  light $0E {zp[0x0E]:02x}", flush=True)
        if noon or "--hour" in sys.argv:    # BCD; $57DE sees the hour change at the next turn
            hour = int(sys.argv[sys.argv.index("--hour") + 1], 16) if "--hour" in sys.argv else 0x12
            v.poke(0x1E, bytes([hour]))
        # the game waits inside the read: one joystick push gets it out
        v.cmd(f"break {ret:04x}", wait=0.2)
        for _ in range(4):              # (on a C128 a press sometimes falls between reads)
            if c128:
                v.joystick(2, 0x10, 40)
            else:
                v.poke(u.JOY_BYTE, bytes([u.JOY["fire"]]))
            v.sock.sendall(b"x\n")
            if stop(v, 15):
                break
        else:
            raise SystemExit("the key read never returned")
        v.cmd("delete", wait=0.2)
        if not c128:
            v.poke(u.JOY_BYTE, b"\xff")
        v.cmd(f"break {call:04x}", wait=0.2)
        def step(d, prof=False):
            # skip the read: as if it had returned the direction
            v.cmd(f"r pc = {ret:04x}", wait=0.2)
            v.cmd(f"r a = ${DIRS[d]:02x}", wait=0.2)   # "af" is a register pair to the monitor
            t0 = sw(v)[1]
            v.sock.sendall(b"x\n")
            ok = stop(v, 60)
            t1 = sw(v)[1]
            if not ok:
                shot(f"build/u5step_{mode}_hung.png")
                print(v.cmd("chis 30", 1.0))
                raise SystemExit("no key read after a step")
            return t1 - t0, tuple(v.mem(0x2D, 0x2E))

        MOVE = {"e": (1, 0), "w": (-1, 0), "n": (0, -1), "s": (0, 1)}
        pos = tuple(v.mem(0x2D, 0x2E))
        for d in via:                   # untimed, until each square is reached
            want = ((pos[0] + MOVE[d][0]) & 255, (pos[1] + MOVE[d][1]) & 255)
            for _ in range(8):
                _, pos = step(d)
                if pos == want:
                    break
            else:
                shot(f"build/u5step_{mode}_stuck.png")
                raise SystemExit(f"stuck at {pos}, wanted {want}")
        print("at", pos, " light $0E", hex(v.mem(0x0E, 0x0E)[0]), flush=True)
        if quiet:
            v.poke(0x78, b"\x00")             # sound off: $6112 (BIT $78 / BPL) skips every effect
        if profile:
            v.cmd("prof on", wait=0.3)         # flushes: from here on, the timed steps only
        for i in range(nsteps):
            d = dirs[i % len(dirs)]
            cyc, new = step(d, profile)
            moved = new != pos
            pos = new
            times.append((cyc, moved, pos))
            print(f"step {i} {d}: {cyc} cycles ({cyc / PAL:.3f} s), pos {pos[0]},{pos[1]}",
                  "" if moved else "(did not move)", flush=True)
        v.cmd("delete", wait=0.2)
        v.cmd("delete", wait=0.2)
        v.run(1.5)                  # (a stop can catch the VIC mid-frame: let it finish one)
        shot(f"build/u5step_{mode}_end.png")
        if profile:
            v.cmd("prof off", wait=0.3)
            out = f"build/u5step_{mode}{'_quiet' if quiet else ''}"
            flat = v.cmd("prof flat 80", wait=3.0)
            Path(f"{out}_flat.txt").write_text(flat)
            Path(f"{out}_graph.txt").write_text(v.cmd("prof graph depth 6", wait=6.0))
            top = re.findall(r"^\s*[\d,]+\s+[\d.]+%\s+[\d,]+\s+[\d.]+%\s+([0-9a-f]{4})", flat, re.M)[:14]
            with open(f"{out}_func.txt", "w") as fh:
                for f in top:
                    fh.write(v.cmd(f"prof func {f}", wait=1.5))
            with open(f"{out}_disass.txt", "w") as fh:
                for f in top:
                    fh.write(v.cmd(f"prof disass {f}", wait=3.0))
            v.cmd("bank ram00" if c128 else "bank ram", wait=0.2)
            v.cmd(f'bsave "{os.path.abspath(out)}_ram.bin" 0 0000 ffff', wait=2.0)
    finally:
        v.quit()
    moved = [t for t, m, _ in times if m]
    if moved:
        mean = sum(moved) / len(moved)
        print(f"mean {mean:.0f} cycles = {mean / PAL:.3f} s over {len(moved)} steps that moved "
              f"(min {min(moved)}, max {max(moved)})")


if __name__ == "__main__":
    main()
