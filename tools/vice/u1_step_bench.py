#!/usr/bin/env python3
"""Ultima 1: what one unblocked step outdoors costs, in VICE cycles, and where it goes.

    python -m tools.vice.u1_step_bench [steps] [--profile] [--held]

Makes a character as u1_town_check does and continues with it (hit points
and food raised so nothing ends the walk), then walks to and fro along the
longest run of grass and forest from where the party starts, at most five
squares each way.

OU's command loop waits for a key in `JSR $8DD0` at $8D1A: up to 128 polls of
ST's $1E50, each of which draws the whole 19 x 9 view ($1C8A) into the hidden
bitmap and flips it ($1700); then a turn passes.  So a step is seen only when
the poll after it has drawn the view.  A step here: stopped after a poll
($8DD5), PC to $8DDA with the direction key in A (`@ / ; :`), as if the poll
had returned it; the stopwatch is read at $8D1A, back at the key wait (the
command, the monsters' turn $9A2F, the prompt and the status), and at the end
of the next poll, the view drawn with the party moved.

--held: the pace of a direction key held down, through the key matrix: the
cycles from one arrival at $8D31 (the key handed to MI's $85FD) to the next.
ST repeats a held direction once the CIA's time of day has counted 0.5 s
since the first press, then 0.2 s ($1637) since the last repeat ($1F46).

With --profile the monitor's profiler runs over all the timed steps; the flat
list, call graph and the top functions' callers/callees and per-instruction
counts go to build/u1step[_held]_*.txt.  PAL: 985,248 cycles a second.
"""
import os
import re
import sys
import time
from pathlib import Path

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice import menu_check
from tools.vice.u1_town_check import in_play, new_game, pos
from tools.vice.vice_mon import Vice
from ultima.maps import u1maps

PAL = 985248
WAIT, AFTER = 0x8D1A, 0x8D31            # OU: JSR $8DD0, then JSR $85FD
POLLED, RETURN = 0x8DD5, 0x8DDA         # OU $8DD0: after a poll, its TAX / RTS
HITS, FOOD = 0x823B, 0x825A
DIRS = {"n": ((0, -1), 0x40), "s": ((0, 1), 0x2F), "e": ((1, 0), 0x3B), "w": ((-1, 0), 0x3A)}
KEYS = {"n": "@", "s": "/", "e": ";", "w": ":"}
BACK = {"n": "s", "s": "n", "e": "w", "w": "e"}


def sw(v):
    out = v.cmd("r", wait=0.4)
    m = re.search(r"^\.;(\w{4}).*?\s(\d+)\s*$", out, re.M)
    return int(m.group(1), 16), int(m.group(2))


def stop(v, timeout=30):
    seen, t = "", time.time()
    while "Stop on" not in seen and time.time() - t < timeout:
        seen += v._drain(0.2)
    return "Stop on" in seen


def route(world, at):
    """The direction with the longest run of grass or forest from `at`,
    at most five squares, there and back."""
    best = (0, "e")
    for d, ((dx, dy), _) in DIRS.items():
        n, (x, y) = 0, at
        while n < 5 and 0 <= x + dx < 64 and 0 <= y + dy < 64 and \
                world[(y + dy) * 64 + x + dx] in (1, 2):
            n, x, y = n + 1, x + dx, y + dy
        best = max(best, (n, d))
    n, d = best
    if not n:
        raise SystemExit(f"no grass or forest beside {at}")
    return d * n + BACK[d] * n


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nsteps = int(args[0]) if args else 20
    profile = "--profile" in sys.argv
    held = "--held" in sys.argv
    out = "build/u1step" + ("_held" if held else "")
    world = u1maps.continents()[0]
    image = menu_check.with_autokey(1)
    for _ in range(3):                  # key timing at the menus is not exact
        v = Vice(image, port=6537)
        new_game(v)
        if in_play(v, world):
            break
        print("not in play after the menus, again")
        v.quit()
    else:
        raise SystemExit("could not start a game")
    times = []

    def go(timeout=60):
        v.sock.sendall(b"x\n")
        if not stop(v, timeout):
            v.shot(f"{out}_hung.png")
            print(v.cmd("chis 30", 1.0))
            raise SystemExit("no stop")
        return sw(v)

    try:
        v.poke(HITS, [0x0F, 0x27])      # 9999
        v.poke(FOOD, [0x0F, 0x27])
        here = pos(v)
        dirs = route(world, here)
        print("at", here, "walking", dirs, flush=True)
        if held:
            v.cmd(f"break {AFTER:04x}", wait=0.2)
        else:
            v.cmd(f"break {WAIT:04x}", wait=0.2)
            v.cmd(f"break {POLLED:04x}", wait=0.2)
            while go(15)[0] != POLLED:
                pass
        v.shot(f"{out}_start.png")
        if profile:
            v.cmd("prof on", wait=0.3)
        last, t = None, None
        for i in range(nsteps):
            d = dirs[i % len(dirs)]
            (dx, dy), key = DIRS[d]
            want = (here[0] + dx, here[1] + dy)
            if held:
                if d != last:           # release the other, hold this one
                    v.cmd("keymatrix clear", wait=0.2)
                    row, col = next((r, k.index(KEYS[d])) for r, k in enumerate(Vice.MATRIX)
                                    if KEYS[d] in k)
                    v.cmd(f"keymatrix {row:x} {col:x} on", wait=0.2)
                    last, t = d, None
                pc, t1 = go()
                here = pos(v)               # (the step is still to come)
                print(f"key {i} {d}: " + (f"{t1 - t} cycles ({(t1 - t) / PAL:.3f} s) since the last"
                                          if t is not None else "first"), flush=True)
                if t is not None:
                    times.append((t1 - t, True))
                t = t1
                continue
            v.cmd(f"r pc = {RETURN:04x}", wait=0.2)
            v.cmd(f"r a = ${key:02x}", wait=0.2)
            t0 = sw(v)[1]
            pc, t1 = go()
            if pc != WAIT:
                raise SystemExit(f"stopped at ${pc:04x}, not at the key wait")
            pc, t2 = go()
            if pc != POLLED:
                raise SystemExit(f"stopped at ${pc:04x}, not after a poll")
            here = pos(v)
            moved = here == want
            times.append((t2 - t0, moved, t1 - t0))
            print(f"step {i} {d}: {t1 - t0} cycles to the key wait, {t2 - t0} to the view drawn "
                  f"({(t2 - t0) / PAL:.3f} s), pos {here}", "" if moved else "(did not move)",
                  flush=True)
            if not moved:
                raise SystemExit("blocked: the route is not clear")
        v.cmd("keymatrix clear", wait=0.2)
        v.cmd("delete", wait=0.2)
        if profile:
            v.cmd("prof off", wait=0.3)
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
        v.run(1.5)
        v.shot(f"{out}_end.png")
    finally:
        v.quit()
    moved = [t[0] for t in times if t[1]]
    if moved:
        mean = sum(moved) / len(moved)
        print(f"mean {mean:.0f} cycles = {mean / PAL:.3f} s over {len(moved)} "
              f"{'repeats' if held else 'steps'} (min {min(moved)}, max {max(moved)})")
    if not held and moved:
        part = [t[2] for t in times]
        print(f"of which to the key wait: mean {sum(part) / len(part):.0f}")


if __name__ == "__main__":
    main()
