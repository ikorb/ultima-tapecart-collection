#!/usr/bin/env python3
"""Ultima 2: what one unblocked step on the surface costs, in VICE cycles, and where it goes.

    python -m tools.vice.u2_step_bench [steps] [--profile] [--held] [--paced] [--sid] [--horse]

U2 from a copy of the cart (MENU_AUTOKEY), a player made at INTRO's title as
in u2_powers_check.py, hit points and food raised (BCD, $8E1B/$8E1C and
$8E1D-$8E1F) so nothing ends the walk, then to and fro along the longest run
of grass (map byte $08) from where the party starts, at most five squares
each way.

ULTIMA's command loop: "CMD:" ($50F1), the water rotated ($69A5, $6981),
then the key wait at $512C polls $38 (bit 7: a key waits; the IRQ, SUBS
$4765, puts the KERNAL's there), with an idle pass every 256 polls and a
turn passing on its own after 24 of them.  A step here: stopped at $5106
(the prompt printed, the poll about to start), the direction key put into
$38 (`@ / : ;`), and the stopwatch read at $5186 (the key taken), at the
turn's stations on the way -- $52C0 (the command done), $53DD (the monsters
moved), $543E (the view drawn, SUBS $4087; attacks and food done), $5469
(the status drawn, $403F) -- and back at $5106.  The time from a key landing in $38 to the
poll seeing it is not counted.  Before the steps, the idle pass is timed:
from one arrival at $513D (after 256 polls) to the next.

A move waits until 0.2 s have passed since the last one's click (u2step.s:
st_since, in ticks of the raster IRQ); each step here starts with st_since
poked to $FF, as after a pause, so the step's own cycles are measured.
--paced leaves it alone: the steps back to back, at the floor's pace.
--sid stops at every write to voice 3's control ($D412, the gate) and
lists each with its value and cycles since the key was taken.

--held: the pace of a direction key held down, through the key matrix: the
cycles from one arrival at $5186 (the key taken) to the next.  SUBS sets
$028A = $80 (every key repeats) at $4704, and its raster IRQ ($477A) scans
the keyboard once a frame and puts the KERNAL's key into $38 ($4765).  The
KERNAL's first repeat comes 16 scans after the press, the next every four,
so the party is put on the map's longest straight run of grass (up to 10)
and walks it there and back.  The mean leaves out each way's first three
keys: the press, the first repeat, and the key after it, which is taken
early and waits for the floor (u2step.s) inside its step.

--horse: on a horse ($13 = $22, what Board leaves there): three clicks a
move (the third after the next prompt: give --paced to see it).

With --profile the monitor's profiler runs over all the timed steps; the flat
list, call graph and the top functions' callers/callees and per-instruction
counts go to build/u2step[_held]_*.txt.  PAL: 985,248 cycles a second.
"""
import os
import re
import sys
import time
from pathlib import Path

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice import menu_check
from tools.vice.u2_powers_check import syms
from tools.vice.u3_drive import wait_stop
from tools.vice.vice_mon import Vice

PAL = 985248
PROMPT, TAKEN, IDLE = 0x5106, 0x5186, 0x513D
STATIONS = {0x52C0: "command", 0x53DD: "monsters", 0x543E: "view, attacks, food",
            0x5469: "status", PROMPT: "prompt, water"}
HITS, FOOD = 0x8E1B, 0x8E1D
GRASS = 0x08
DIRS = {"n": ((0, -1), 0xC0), "s": ((0, 1), 0xAF), "w": ((-1, 0), 0xBA), "e": ((1, 0), 0xBB)}
KEYS = {"n": "@", "s": "/", "e": ";", "w": ":"}
BACK = {"n": "s", "s": "n", "e": "w", "w": "e"}


REGS = {}


def sw(v):
    out = v.cmd("r", wait=0.4)
    m = re.search(r"^\.;(\w{4}) (\w\w).*?\s(\d+)\s*$", out, re.M)
    REGS["a"] = int(m.group(2), 16)
    return int(m.group(1), 16), int(m.group(3))


def stop(v, timeout=30):
    seen, t = "", time.time()
    while "Stop on" not in seen and time.time() - t < timeout:
        seen += v._drain(0.2)
    return "Stop on" in seen


def route(world, at):
    """The direction with the longest run of grass from `at`, at most five
    squares, there and back (the map wraps: $5389 AND #$3F)."""
    best = (0, "e")
    for d, ((dx, dy), _) in DIRS.items():
        n, (x, y) = 0, at
        while n < 5 and world[((y + dy) % 64) * 64 + (x + dx) % 64] == GRASS:
            n, x, y = n + 1, (x + dx) % 64, (y + dy) % 64
        best = max(best, (n, d))
    n, d = best
    return d * n + BACK[d] * n if n else ""


def longest(world, most=10):
    """(start, direction, length) of the longest straight run of grass."""
    best = (0, (0, 0), "e")
    for i in range(4096):
        if world[i] != GRASS:
            continue
        for d, ((dx, dy), _) in DIRS.items():
            n, x, y = 0, i % 64, i // 64
            while n < most and world[((y + dy) % 64) * 64 + (x + dx) % 64] == GRASS:
                n, x, y = n + 1, (x + dx) % 64, (y + dy) % 64
            best = max(best, (n, (i % 64, i // 64), d))
    n, at, d = best
    return at, d, n


def new_player(v, s):
    """C at the title, 15 into each stat, M 1 1, AVATAR, Y: in the game."""
    def take(key, secs=0.8):
        for _ in range(100):
            if not v.mem(0x38, 0x38)[0] & 0x80:
                break
            v.run(0.1)
        v.poke(0x38, bytes([key | 0x80]))
        v.run(secs)

    v.run_to(0xC093, timeout=90)
    v.delbreaks()
    v.run(10.0)
    text = lambda: " ".join(v.screen()).upper()
    for _ in range(10):
        take(ord("C"), 3.0)
        if "POINTS" in text():
            break
    for ch in "151515151515":
        take(ord(ch), 0.6)
    for ch in "M11":
        take(ord(ch), 1.2)
    for ch in "AVATAR":
        take(ord(ch), 0.4)
    take(0x0D, 1.5)
    for _ in range(4):
        v.cmd(f"break {s['u2_blk_write']:04x}", wait=0.2)
        v.poke(0x38, bytes([0x80 | ord("Y")]))
        made = wait_stop(v, 15)
        v.cmd("delete", wait=0.2)
        if made:
            return v.run_to(PROMPT, timeout=90)
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nsteps = int(args[0]) if args else 20
    profile = "--profile" in sys.argv
    held = "--held" in sys.argv
    paced = "--paced" in sys.argv
    sid = "--sid" in sys.argv
    OUT = "build/u2step" + ("_held" if held else "")
    v = Vice(menu_check.with_autokey(2), update_tcrt=True, log=f"{OUT}.log")
    times = []

    def go(timeout=30):
        v.sock.sendall(b"x\n")
        if not stop(v, timeout):
            v.shot(f"{OUT}_hung.png")
            raise SystemExit("no stop")
        return sw(v)

    s = syms()
    try:
        if not new_player(v, s):
            raise SystemExit("not in the game")
        v.delbreaks()
        v.run(2.0)
        if not v.run_to(PROMPT, timeout=30):
            raise SystemExit("no prompt")
        if v.mem(0x8E14, 0x8E14)[0]:
            raise SystemExit("not on the surface")
        v.poke(HITS, [0x99, 0x99])
        v.poke(FOOD, [0x99, 0x99, 0x00])
        if "--horse" in sys.argv:
            v.poke(0x13, [0x22])
        world = v.mem(0x1000, 0x1FFF)
        here = tuple(v.mem(0x02, 0x03))
        dirs = route(world, here)
        if held:                        # to the start of the longest run
            here, d, n = longest(world)
            v.poke(0x02, list(here))
            dirs = d * n + BACK[d] * n
        elif not dirs:                  # to the middle of a run of five
            here = next((i % 64, i // 64) for i in range(4096)
                        if all(world[i // 64 * 64 + (i + k) % 64] == GRASS for k in range(-5, 6)))
            v.poke(0x02, list(here))
            dirs = route(world, here)
        print("at", here, "walking", dirs, flush=True)
        v.cmd(f"break {IDLE:04x}", wait=0.2)
        ts = [go()[1] for _ in range(4)]
        v.cmd("delete", wait=0.2)
        idle = [b - a for a, b in zip(ts, ts[1:])]
        print(f"idle pass: {idle} cycles", flush=True)
        if held:
            v.cmd(f"break {TAKEN:04x}", wait=0.2)
            v.cmd(f"break {PROMPT:04x}", wait=0.2)
            if profile:
                v.cmd("prof on", wait=0.3)
            last, t, waits, run = None, None, [], 0
            for i in range(nsteps):
                d = dirs[i % len(dirs)]
                if d != last:           # release the other, hold this one
                    v.cmd("keymatrix clear", wait=0.2)
                    row, col = next((r, k.index(KEYS[d])) for r, k in enumerate(Vice.MATRIX)
                                    if KEYS[d] in k)
                    v.cmd(f"keymatrix {row:x} {col:x} on", wait=0.2)
                    last, t, run = d, None, 0
                pc, t1 = go()
                done = None
                while pc == PROMPT:         # the step done: from here to the next key
                    done = t1
                    pc, t1 = go()
                print(f"key {i} {d}: " + (f"{t1 - t} cycles ({(t1 - t) / PAL:.3f} s) since the last"
                                          + (f", {t1 - done} of them at the key wait" if done else "")
                                          if t is not None else "first"), flush=True)
                run += 1
                if t is not None and run > 3:  # past the first repeat and the next
                    times.append((t1 - t, True, []))
                    waits += [t1 - done] if done else []
                t = t1
            v.cmd("keymatrix clear", wait=0.2)
            if waits:
                print(f"at the key wait: mean {sum(waits) / len(waits):.0f} of each repeat", flush=True)
            dirs = ""
        for a in (TAKEN, *STATIONS) if dirs else ():
            v.cmd(f"break {a:04x}", wait=0.2)
        if sid and dirs:
            v.cmd("watch store d412", wait=0.2)
        v.shot(f"{OUT}_start.png")
        for i in range(-2, nsteps if dirs else -2):     # two untimed: the view after a poked position
            if i == 0 and profile:
                v.cmd("prof on", wait=0.3)
            d = dirs[i % len(dirs)]
            (dx, dy), key = DIRS[d]
            want = ((here[0] + dx) % 64, (here[1] + dy) % 64)
            if not paced:
                v.poke(s["st_since"], [0xFF])
            v.poke(0x38, [key])
            pc, t0 = go()
            while sid and pc != TAKEN:  # the last step's gate, after its prompt
                print(f"  $D412: ${REGS['a']:02x} after the prompt", flush=True)
                pc, t0 = go()
            if pc != TAKEN:
                raise SystemExit(f"stopped at ${pc:04x}, not where the key is taken")
            marks, gates = [], []
            while pc != PROMPT:
                pc, t = go()
                if pc in STATIONS:
                    marks.append((pc, t - t0))
                else:                   # --sid: a write to $D412
                    gates.append(f"${REGS['a']:02x} at {t - t0}")
            here = tuple(v.mem(0x02, 0x03))
            moved = here == want
            total = marks[-1][1]
            parts, last = [], 0
            for pc, t in marks:
                parts.append(f"{STATIONS.get(pc, f'${pc:04x}')} {t - last}")
                last = t
            print(f"step {i} {d}: {total} cycles ({total / PAL:.3f} s), pos {here}"
                  + ("" if moved else " (did not move)") + ": " + ", ".join(parts), flush=True)
            if gates:
                print("  $D412:", ", ".join(gates), flush=True)
            if i >= 0:
                times.append((total, moved, marks))
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
            with open(f"{OUT}_disass.txt", "w") as fh:
                for f in top:
                    fh.write(v.cmd(f"prof disass {f}", wait=3.0))
        v.run(1.5)
        v.shot(f"{OUT}_end.png")
    finally:
        v.quit()
    moved = [t for t in times if t[1]]
    if moved:
        mean = sum(t[0] for t in moved) / len(moved)
        print(f"mean {mean:.0f} cycles = {mean / PAL:.3f} s over {len(moved)} steps "
              f"(min {min(t[0] for t in moved)}, max {max(t[0] for t in moved)})")
        by = {}
        for _, _, marks in moved:
            last = 0
            for pc, t in marks:
                by.setdefault(pc, []).append(t - last)
                last = t
        for pc, ts in by.items():
            print(f"  {STATIONS.get(pc, f'${pc:04x}')}: mean {sum(ts) / len(moved):.0f} "
                  f"(in {len(ts)} of {len(moved)} steps)")


if __name__ == "__main__":
    main()
