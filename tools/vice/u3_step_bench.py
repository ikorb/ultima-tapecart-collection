#!/usr/bin/env python3
"""Ultima 3: what one unblocked step on the surface costs, in VICE cycles, and where it goes.

    python -m tools.vice.u3_step_bench [steps] [--profile] [--clicks] [--horse] [--original] [--fresh]

U3 from a copy of the cart, a fighter made and a party formed (u3_drive.start),
on Sosaria; the party's hit points raised (PLRS $401A, BCD) and, before each
step, any monster within four squares taken off the map (its under-tile put
back, $4F00,X cleared), so no fight interrupts the walk.  Then to and fro along
the longest run of grass (map byte $04) through where the party stands, at most
five squares each way.  The machine on Sosaria is kept as a snapshot
(build/u3step.vsf) and reused while it is newer than the cart; --fresh makes
it again.

ULT3's command loop on the surface: $5096 counts down the idle turns ($22),
$509A JSR $74AB, $509D JSR $46F3 (SUBS $4A68: the animations and all of UPDT,
$CA00), then the poll at $50A9 (the driver's kb_take).  A step here: stopped at
$50A9, the direction key put into the KERNAL's queue ($0277, $C6 = 1), and the
stopwatch read at the turn's stations -- $50AC (the key taken), $6D38 (the
party moved: the direction's name printed and the window scrolled, the
square checked, the footstep), $780B (the turn: food, the party's panel, the
wind), $507E (the monsters), $509A (the status line and the prompt), $509D
($74AB) -- and back at $50A9, after the idle pass's redraw: the next key is
taken there.  Before the steps, the idle pass is timed (from one $50A9 to
the next) and the IRQ's period (from one $9A75, MUSI's handler, to the next).

--original puts back, in RAM, the bytes the cart changes for the step, as
the disks have them (build.unit_from_disks): ULT3's footstep wait at $710F
(u3step.s) and the panel's draw at $730D, SUBS' scroll at $4770
(u3scroll.s), UPDT's line of sight at $CA99 (u3view.s); so a step is timed
as in the original (the IRQ's hook stays; it has nothing to play).  --clicks stops at every write to $D418 (the speaker, $B930) and lists
the bursts, timed from the key taken.  --horse sets $0E = $14, the transport
the footstep plays a third click for.  With --profile the monitor's profiler
runs over all the timed steps; the flat list, call graph and the top
functions' callers/callees go to build/u3step[_orig]_*.txt.  PAL: 985,248
cycles a second.  The numbers are in docs/developer/u3.md.
"""
import os
import re
import sys
import time
from pathlib import Path

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice.u3_drive import image, start
from tools.vice.vice_mon import Vice

PAL = 985248
POLL, TAKEN, IRQ = 0x50A9, 0x50AC, 0x9A75
STATIONS = {0x6D38: "moved", 0x780B: "turn", 0x507E: "monsters",
            0x509A: "status, prompt", 0x509D: "$74AB", POLL: "idle pass"}
GRASS = 0x04
DIRS = {"n": ((0, -1), 0xC0), "s": ((0, 1), 0xAF), "w": ((-1, 0), 0xBA), "e": ((1, 0), 0xBB)}
BACK = {"n": "s", "s": "n", "e": "w", "w": "e"}
SNAP = "build/u3step.vsf"
CART = "build/ultima-collection.tcrt"
# where the cart's step and drawing patches go: unit, load address, the
# patched ranges (build.py STEP_FOOT, STEP_PANEL, SCROLL, VIEW_LOS)
ORIGINAL = [("ULT3", 0x5000, [(0x710F, 6), (0x730D, 1)]),
            ("SUBS", 0x4100, [(0x4770, 0x8C)]),
            ("UPDT", 0xCA00, [(0xCA99, 3)])]


def original_bytes():
    from ultima.games.u3.build import unit_from_disks
    out = []
    for name, base, ranges in ORIGINAL:
        data = unit_from_disks(name)
        out += [(at, list(data[at - base:at - base + n])) for at, n in ranges]
    return out

REGS = {}


def stop(v, timeout=30):
    seen, t = "", time.time()
    while "Stop on" not in seen and time.time() - t < timeout:
        seen += v._drain(0.2)
    return "Stop on" in seen


def sw(v):
    out = v.cmd("r", wait=0.4)
    m = re.search(r"^\.;(\w{4}) (\w\w).*?\s(\d+)\s*$", out, re.M)
    REGS["a"] = int(m.group(2), 16)
    return int(m.group(1), 16), int(m.group(3))


def route(world, at):
    """The direction with the longest run of grass from `at`, at most five
    squares, there and back (the map wraps)."""
    best = (0, "e")
    for d, ((dx, dy), _) in DIRS.items():
        n, (x, y) = 0, at
        while n < 5 and world[((y + dy) % 64) * 64 + (x + dx) % 64] == GRASS:
            n, x, y = n + 1, (x + dx) % 64, (y + dy) % 64
        best = max(best, (n, d))
    n, d = best
    return d * n + BACK[d] * n if n else ""


def on_sosaria():
    """The snapshot, made again when the cart is newer."""
    if os.path.exists(SNAP) and os.path.getmtime(SNAP) > os.path.getmtime(CART) \
            and "--fresh" not in sys.argv:
        v = Vice(image(), keybuf=None)
        v.run(1.0)
        v.undump(SNAP)
        return v
    v = start()
    v.run(3)
    v.dump(SNAP)
    return v


def clear_monsters(v):
    """Monsters within four squares off the map; how many are left."""
    x, y = v.mem(0xF7, 0xF8)
    mon = v.mem(0x4F00, 0x4F7F)
    left = 0
    for k in range(32):
        if not mon[k]:
            continue
        mx, my = mon[0x40 + k], mon[0x60 + k]
        if max(min((mx - x) % 64, (x - mx) % 64), min((my - y) % 64, (y - my) % 64)) <= 4:
            v.poke(0x1000 + my * 64 + mx, [mon[0x20 + k]])
            v.poke(0x4F00 + k, [0])
        else:
            left += 1
    return left


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nsteps = int(args[0]) if args else 20
    profile = "--profile" in sys.argv
    clicks = "--clicks" in sys.argv
    original = "--original" in sys.argv
    OUT = "build/u3step" + ("_orig" if original else "")
    v = on_sosaria()
    times, monsters = [], []

    def go(timeout=30):
        v.sock.sendall(b"x\n")
        if not stop(v, timeout):
            v.shot(f"{OUT}_hung.png")
            raise SystemExit("no stop")
        return sw(v)

    try:
        v.cmd(f"break {POLL:04x}", wait=0.2)
        go()
        if v.mem(0x62, 0x62)[0]:
            raise SystemExit("not on Sosaria")
        v.poke(0x401A, [0x09, 0x99])
        if original:
            for at, data in original_bytes():
                v.poke(at, data)
        if "--horse" in sys.argv:
            v.poke(0x0E, [0x14])
        world = v.mem(0x1000, 0x1FFF)
        here = tuple(v.mem(0xF7, 0xF8))
        dirs = route(world, here)
        if not dirs:                    # to the middle of a run of five
            here = next((i % 64, i // 64) for i in range(4096)
                        if all(world[i // 64 * 64 + (i + k) % 64] == GRASS for k in range(-5, 6)))
            v.poke(0xF7, list(here))
            dirs = route(world, here)
        print("at", here, "walking", dirs, flush=True)
        ts = [go()[1] for _ in range(4)]
        print(f"idle pass: {[b - a for a, b in zip(ts, ts[1:])]} cycles", flush=True)
        v.cmd("delete", wait=0.2)
        v.cmd(f"break {IRQ:04x}", wait=0.2)
        ts = [go()[1] for _ in range(4)]
        print(f"IRQ period: {[b - a for a, b in zip(ts, ts[1:])]} cycles", flush=True)
        v.cmd("delete", wait=0.2)
        v.cmd(f"break {POLL:04x}", wait=0.2)
        go()
        for a in (TAKEN, *STATIONS):
            if a != POLL:
                v.cmd(f"break {a:04x}", wait=0.2)
        if clicks:
            v.cmd("watch store d418", wait=0.2)
        v.shot(f"{OUT}_start.png")
        for i in range(-2, nsteps):     # two untimed: the view after a poked position
            if i == 0 and profile:
                v.cmd("prof on", wait=0.3)
            left = clear_monsters(v)
            d = dirs[i % len(dirs)]
            (dx, dy), key = DIRS[d]
            want = ((here[0] + dx) % 64, (here[1] + dy) % 64)
            v.poke(0x0277, [key])
            v.poke(0xC6, [1])
            pc, t0 = go()
            while pc not in (TAKEN, *STATIONS):     # --clicks: the last step's, after its prompt
                pc, t0 = go()
            if pc != TAKEN:
                raise SystemExit(f"stopped at ${pc:04x}, not where the key is taken")
            marks, writes = [], []
            while pc != POLL:
                pc, t = go()
                if pc in STATIONS:
                    marks.append((pc, t - t0))
                else:                   # --clicks: a write to $D418
                    writes.append(t - t0)
            here = tuple(v.mem(0xF7, 0xF8))
            moved = here == want
            total = marks[-1][1]
            parts, last = [], 0
            for p, t in marks:
                parts.append(f"{STATIONS[p]} {t - last}")
                last = t
            print(f"step {i} {d}: {total} cycles ({total / PAL:.3f} s), pos {here}"
                  + ("" if moved else " (did not move)") + ": " + ", ".join(parts), flush=True)
            if writes:                  # bursts: writes less than 5k cycles apart
                bursts = [[writes[0]]]
                for w in writes[1:]:
                    if w - bursts[-1][-1] < 5000:
                        bursts[-1].append(w)
                    else:
                        bursts.append([w])
                print("  $D418: " + ", ".join(f"{len(b)} writes at {b[0]}-{b[-1]}" for b in bursts),
                      flush=True)
            if v.mem(0x62, 0x62)[0]:
                raise SystemExit("not on Sosaria any more")
            if i >= 0:
                times.append((total, moved, marks))
                monsters.append(left)
        v.cmd("delete", wait=0.2)
        if profile:
            v.cmd("prof off", wait=0.3)
            flat = v.cmd("prof flat 80", wait=3.0)
            Path(f"{OUT}_flat.txt").write_text(flat)
            Path(f"{OUT}_graph.txt").write_text(v.cmd("prof graph depth 6", wait=6.0))
            top = re.findall(r"^\s*[\d,]+\s+[\d.]+%\s+[\d,]+\s+[\d.]+%\s+([0-9a-f]{4})", flat, re.M)[:14]
            with open(f"{OUT}_func.txt", "w") as fh:
                for f in top:
                    fh.write(v.cmd(f"prof func {f}", wait=1.5))
        v.run(1.5)
        v.shot(f"{OUT}_end.png")
    finally:
        v.quit()
    print("monsters on the map:", monsters)
    moved = [t for t in times if t[1]]
    if moved:
        mean = sum(t[0] for t in moved) / len(moved)
        print(f"mean {mean:.0f} cycles = {mean / PAL:.3f} s over {len(moved)} steps "
              f"(min {min(t[0] for t in moved)}, max {max(t[0] for t in moved)})")
        by = {}
        for _, _, marks in moved:
            last = 0
            for p, t in marks:
                by.setdefault(p, []).append(t - last)
                last = t
        for p, ts in by.items():
            print(f"  {STATIONS[p]}: mean {sum(ts) / len(moved):.0f} "
                  f"(in {len(ts)} of {len(moved)} steps)")


if __name__ == "__main__":
    main()
