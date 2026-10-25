#!/usr/bin/env python3
"""Ultima 6 with and without an REU in VICE: is it found (rc_on), and what does
loading a small overlay cost the first and the second time?

    python -m tools.vice.u6_reu_check SAVE_FILE [off|512|256|128]

The load is timed on the monitor's stopwatch from the small-overlay loader's
entry ($2C38) to the end of its load loop ($2C70), Look's overlay (1 KiB) and
then Cast's (a large one is loaded at $3E30: its own entry and exit).
"""
import os
from ultima import paths
import re
import sys
import time

os.chdir(paths.ROOT)
from tools.vice import menu_check
from tools.vice import u6_cart as sb
from tools.vice.vice_mon import Vice

RC_ON = 0x2077


def sw(v):
    out = v.cmd("r", wait=0.4)
    return int(re.search(r"^\.;\w{4}.*?\s(\d+)\s*$", out, re.M).group(1))


def press(v, key):
    """The key into the matrix, without resuming (tap() would, and swallow a breakpoint's report)."""
    for row, keys in enumerate(v.MATRIX):
        if key in keys:
            v.cmd(f"keymatrix {row:x} {keys.index(key):x} +6", wait=0.1)
            return
    raise ValueError(key)


def load_cost(v, key, entry, exit_):
    """Cycles from `entry` to `exit_` while the game runs `key`'s command."""
    v.cmd(f"break {entry:04x}", wait=0.1)
    press(v, key)
    v.sock.sendall(b"x\n")
    if not sb.stop(v, 40):
        v.cmd("delete", wait=0.1)
        return None
    t0 = sw(v)
    v.cmd("delete", wait=0.1)
    v.cmd(f"break {exit_:04x}", wait=0.1)
    v.sock.sendall(b"x\n")
    if not sb.stop(v, 40):
        v.cmd("delete", wait=0.1)
        return None
    t1 = sw(v)
    v.cmd("delete", wait=0.1)
    v.sock.sendall(b"x\n")
    time.sleep(0.2)
    v.cmd("", wait=0.2)
    return t1 - t0


def main():
    save = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "512"
    menu_check.IMAGE = sb.make_cart(save)
    extra = [] if mode == "off" else ["-reu", "-reusize", mode]
    v = Vice(menu_check.with_autokey(6), update_tcrt=False, extra=extra)
    try:
        v.u6_journey_onward()                                  # Journey onward
        v.run(45.0)
        print(f"REU {mode}: rc_on = {v.mem(RC_ON, RC_ON)[0]}", flush=True)
        for label, key, entry, exit_ in (("Look", "l", 0x2C38, 0x2C70), ("Get", "g", 0x2C38, 0x2C70),
                                         ("Look again", "l", 0x2C38, 0x2C70), ("Get again", "g", 0x2C38, 0x2C70)):
            c = load_cost(v, key, entry, exit_)
            print(f"{label:11s} overlay load: {c} cycles" + (f" = {c / 985248:.3f} s" if c else ""), flush=True)
            v.tap("\r", frames=6, gap=1.5)
            v.tap("\r", frames=6, gap=1.5)
        v.shot(f"build/u6reu_{mode}.png")
    finally:
        v.quit()


if __name__ == "__main__":
    main()
