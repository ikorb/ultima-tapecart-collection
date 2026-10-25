#!/usr/bin/env python3
"""Ultima 6: the on-demand part kept in its half -- the invariant, in VICE.

    [U6_REU=256] python -m tools.vice.u6_keep_check [--walk SECONDS]

The resident skips fetching u6bulk when u6_keep names the idle half
(u6res.s u6_bulk).  That is only right if nothing but the driver writes to
that half while u6_keep names it.  This watches exactly that: a store into
$D800-$DBFF while u6_keep = $D8 (or $DC00-$DFFF while it is $DC), reaching
RAM ($01's banking), from code that is not the driver (the resident's
pieces, or the half itself).  Any hit is a failure.

Journey Onward from a copy of the cart, then: a control (u6_keep poked to
the idle half during play: the next frame's sprites must hit the watch),
then saves (Shift-S, Y), window shifts (the party's window x put past the
edge, a step: the save, then the four object files), and a walk with
the joystick.  Each save and shift is timed from its start to the next
frame drawn ($08AD), with the fetches of u6bulk counted.
"""
import os
from ultima import paths
import random
import re
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)
from tools.vice import menu_check
from tools.vice.vice_mon import Vice

PAL = 985248
SAVE, SHIFT, RENDER = 0x3E83, 0x22E0, 0x08AD


def symbols(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


R = symbols("build/u6res.sym")
KEEP, CMD, RD = R["u6_keep"], R["u6_cmd"], R["u6_bulk_rd"]
RAM = "(((@cpu:$01 & $03) == $00) || ((@cpu:$01 & $04) == $00))"
# the driver: the resident's two pieces, the half, and the REU's code in the init's room
# (u6reu.s: its DMA fills the half with parts A and B, u6wc.s)
NOT_DRIVER = ("((PC < $03c9) || ((PC > $03f0) && (PC < $132e)) || ((PC > $13d9) && (PC < $2823))"
              " || ((PC > $28cd) && (PC < $2989)) || ((PC > $2b4d) && (PC < $d800)))")


def watches(v):
    for lo, hi, page in ((0xD800, 0xDBFF, 0xD8), (0xDC00, 0xDFFF, 0xDC)):
        v.cmd(f"watch store {lo:04x} {hi:04x} if (@cpu:${KEEP:04x} == ${page:02x}) && {RAM} && {NOT_DRIVER}",
              wait=0.3)


def wait_stop(v, timeout):
    end, seen = time.time() + timeout, ""
    while time.time() < end:
        seen += v._drain(0.5)
        if "Stop on" in seen:
            return seen
    return None


def regs(v):
    out = v.cmd("r", wait=0.4)
    line = [l for l in out.splitlines() if l.startswith(".;")][-1].split()
    return int(line[0][2:], 16), int(line[-1]), out


def timed(v, start, label, timeout=60, at_start=None):
    """Run to `start`, then to the next frame drawn, counting fetches; a
    watch hit on the way is a failure (returned as such).  at_start: what
    Vice.u6_save_keys said (its breakpoint on `start` is armed already;
    True: stopped there)."""
    if at_start:
        seen = "Stop on"
    else:
        if at_start is None:
            v.cmd(f"break {start:04x}", wait=0.2)
        v.sock.sendall(b"x\n")
        seen = wait_stop(v, timeout)
    if not seen:
        v.cmd("", wait=0.3)
        v.shot(f"build/u6_keep_{label.replace(' ', '_')}.png")
        v.cmd("delete", wait=0.2)
        watches(v)
        return None, f"{label}: did not start"
    if "WATCH" in seen.split("Stop on")[-1][:40] or "watch" in seen.lower().split("stop on")[-1][:60]:
        return None, f"{label}: WATCH HIT before it started:\n{seen[-400:]}"
    _, t0, _ = regs(v)
    v.cmd("delete", wait=0.2)
    watches(v)
    v.cmd(f"break {RD:04x}", wait=0.1)
    v.cmd(f"break {RENDER:04x}", wait=0.1)
    fetches = 0
    while True:
        v.sock.sendall(b"x\n")
        seen = wait_stop(v, 300)
        if not seen:
            return None, f"{label}: never drew a frame again"
        pc, sw, out = regs(v)
        if pc == RD:
            fetches += 1
        elif pc == RENDER:
            break
        else:
            return None, f"{label}: WATCH HIT at ${pc:04x}:\n{seen[-400:]}"
    v.cmd("delete", wait=0.2)
    watches(v)
    return (sw - t0, fetches), None


def main():
    walk = 60.0
    if sys.argv[1:2] == ["--walk"]:
        walk = float(sys.argv[2])
    image = menu_check.with_autokey(6)
    extra = ["-reu", "-reusize", os.environ["U6_REU"]] if os.environ.get("U6_REU") else None
    v = Vice(image, update_tcrt=False, extra=extra)       # U6_REU=256: parts A and B (u6wc.s)
    fails = []
    try:
        v.u6_journey_onward()                                  # Journey onward
        v.run(50.0)

        # control: the watch must see the frames' sprites once u6_keep names the idle half
        watches(v)
        idle = 0xD8 if v.mem(0x27, 0x27)[0] & 0x10 else 0xDC
        v.poke(KEEP, bytes([idle]))
        v.sock.sendall(b"x\n")
        seen = wait_stop(v, 10)
        pc = regs(v)[0] if seen else None
        print(f"control: {'the watch fired at $%04x' % pc if seen else 'NO HIT -- the watch sees nothing'}",
              flush=True)
        if not seen:
            fails.append("control")
        v.poke(KEEP, b"\x00")
        v.cmd("delete", wait=0.2)
        watches(v)

        for n in range(2):
            begun = v.u6_save_keys(SAVE)
            if v.keys_stop:                                    # a watch, during the keys
                err = f"save {n}: WATCH HIT during the keys:\n{v.keys_stop[-400:]}"
                print(err, flush=True)
                fails.append(err)
                continue
            got, err = timed(v, SAVE, f"save {n}", at_start=begun)
            if err:
                print(err, flush=True)
                fails.append(err)
                continue
            print(f"save {n}: {got[0] / PAL:.2f} s to the next frame, u6bulk fetched {got[1]}x",
                  flush=True)
            v.run(3)

        for n in range(3):
            for way in (4, 1, 2, 8):                         # west, north, south, east
                v.poke(0x72, b"\x13" if way != 8 else b"\x14")
                v.cmd(f"joystick 2 {way} +6", wait=0.1)
                got, err = timed(v, SHIFT, f"window shift {n}", 5)
                if not err or "did not start" not in err:
                    break
            if err:
                print(err, flush=True)
                fails.append(err)
                continue
            print(f"window shift {n}: {got[0] / PAL:.2f} s to the next frame, "
                  f"u6bulk fetched {got[1]}x", flush=True)
            v.run(3)

        rnd = random.Random(6)
        end = time.time() + walk
        steps = 0
        while time.time() < end:
            v.cmd(f"joystick 2 {rnd.choice((1, 2, 4, 8))} +{rnd.randint(4, 30)}", wait=0.05)
            v.sock.sendall(b"x\n")
            if wait_stop(v, 1.0):
                pc = regs(v)[0]
                print(f"walk: WATCH HIT at ${pc:04x}", flush=True)
                fails.append("walk")
                break
            v.cmd("", wait=0.2)
            steps += 1
        print(f"walk: {steps} joystick pushes, {'no' if 'walk' not in fails else 'a'} watch hit",
              flush=True)
        v.shot("build/u6_keep_check.png")
    finally:
        v.quit()
    print("the kept half was never written by anything else" if not fails else f"FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
