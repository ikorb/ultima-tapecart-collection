#!/usr/bin/env python3
"""Akalabeth from the cart, in VICE: the page's options, the instructions
without their pictures, a character, the way into a dungeon -- and not one
LOAD.

    python -m tools.vice.u0_check [--shots DIR]

Twice: with every option as it was, and with F, G, A and H toggled (unlimited
food and gold, always hit, invincible).  Each run picks Akalabeth in the
menu (0) through the key matrix, toggles its options on the page and
launches it; checks the trainer's flags ($03FC-$03FF, init_u0.s) and that
the game starts without the trainer's questions; pages through the
instructions with Y, every page's text as the game prints it on the text
screen; makes a character (lucky number 42, level 5, a fighter) and buys
food and a rapier -- gold spent, or not; walks the shortest way to the
nearest dungeon, by the map in TE(21,21), with food used or not; and goes
down its ladder.  A breakpoint on the KERNAL's LOAD ($FFD5, $F49E) stops it
all: the program must not touch a drive.

The game's own variables tell its state: the scalars TX/TY (the party's
square) and IN (the dungeon's level), the arrays PW (PW(0) food) and C (C(0)
hit points, C(5) gold), as the Apple original names them.  Keys go in at
the game's GETIN ($FFE4, vice_mon's send_key_at) once it runs.  About seven
minutes.
"""
import argparse
import os
import re
import sys
import time
from collections import deque

from ultima import paths

os.chdir(paths.ROOT)

from tools.vice.vice_mon import Vice                     # noqa: E402

IMAGE = "build/ultima-collection.tcrt"
FLAGS = 0x03FC                  # always hit, invincible, gold, food
ON = 100
MOUNTAIN, DUNGEON = 1, 4        # TE's values: 2 tree, 3 town, 5 castle
STEPS = {(0, -1): "P", (0, 1): "L", (-1, 0): "W", (1, 0): "E"}
PAGES = ["many, many, many years ago", "the player stat's:",
         "the towns and buying items:", "movement:", "thou doest now know",
         "type thy lucky number"]


class Fail(Exception):
    pass


class Game:
    def __init__(self, port):
        self.v = Vice(IMAGE, port=port)
        self.v.run(8)                               # the menu

    # -- the machine -----------------------------------------------------
    def go(self, seconds):
        """Run; a LOAD is a failure."""
        self.v.sock.sendall(b"x\n")
        end, out = time.time() + seconds, ""
        while time.time() < end:
            out += self.v._drain(0.2)
            if "Stop on" in out:
                raise Fail("the game called the KERNAL's LOAD:\n" + out[-400:])
        self.v.sock.sendall(b"\n")
        self.v._drain(0.3)
        self.v.cmd("r")

    def loads_off(self):
        self.v.cmd("break exec ffd5")
        self.v.cmd("break exec f49e")

    def screen(self, base=0x0400):
        s = self.v.mem(base, base + 999)
        char = lambda c: (chr(c + 96) if 1 <= c <= 26 else chr(c) if 32 <= c < 64
                          else chr(c) if 65 <= c <= 90 else " ")
        return "\n".join("".join(char(c) for c in s[r * 40:r * 40 + 40]).rstrip()
                         for r in range(25))

    def wait_text(self, text, timeout=20, base=0x0400):
        end = time.time() + timeout
        while time.time() < end:
            scr = self.screen(base)
            if text.lower() in scr.lower():
                return scr
            self.go(0.5)
        raise Fail(f"no {text!r} on the screen:\n{self.screen(base)}")

    def key(self, ch):
        """At the game's GETIN."""
        self.v.cmd("delete")
        if not self.v.send_key_at(0xFFE4, ch, timeout=30):
            raise Fail(f"the game did not ask for a key ({ch!r})")
        self.loads_off()
        self.go(0.4)

    def tap(self, ch, gap=1.0):
        self.v.tap(ch, frames=6, gap=gap)

    # -- the game's variables --------------------------------------------
    @staticmethod
    def _float(b):
        if b[0] == 0:
            return 0.0
        m = (b[1] | 0x80) << 24 | b[2] << 16 | b[3] << 8 | b[4]
        return (-1 if b[1] & 0x80 else 1) * m * 2.0 ** (b[0] - 160)

    def scalar(self, name):
        z = self.v.mem(0x2D, 0x30)
        lo, hi = z[0] | z[1] << 8, z[2] | z[3] << 8
        d = self.v.mem(lo, hi - 1)
        for i in range(0, len(d), 7):
            if bytes(c & 0x7F for c in d[i:i + 2]).rstrip(b"\0") == name.encode() \
                    and not d[i] & 0x80:
                return self._float(d[i + 2:i + 7])
        raise Fail(f"no variable {name}")

    def array(self, name):
        """(dims, values) of a float or integer array."""
        z = self.v.mem(0x2F, 0x32)
        lo, hi = z[0] | z[1] << 8, z[2] | z[3] << 8
        d = self.v.mem(lo, hi - 1)
        i = 0
        while i < len(d):
            n0, n1, ln, nd = d[i], d[i + 1], d[i + 2] | d[i + 3] << 8, d[i + 4]
            if bytes([n0 & 0x7F, n1 & 0x7F]).rstrip(b"\0") == name.encode() and not \
                    (n1 & 0x80 and not n0 & 0x80):               # not a string array
                dims = [d[i + 5 + 2 * k] << 8 | d[i + 6 + 2 * k] for k in range(nd)]
                base, n = i + 5 + 2 * nd, 1
                for x in dims:
                    n *= x
                if n0 & 0x80:
                    vals = [int.from_bytes(d[base + 2 * k:base + 2 * k + 2], "big", signed=True)
                            for k in range(n)]
                else:
                    vals = [self._float(d[base + 5 * k:base + 5 * k + 5]) for k in range(n)]
                return dims, vals
            i += ln
        raise Fail(f"no array {name}")

    def food(self):
        return self.array("PW")[1][0]

    def gold(self):
        return self.array("C")[1][5]


def path_to_dungeon(te, start):
    """The shortest walk to the nearest dungeon, round the mountains."""
    get = lambda x, y: te[x + 21 * y]
    seen, todo = {start: []}, deque([start])
    while todo:
        x, y = todo.popleft()
        if get(x, y) == DUNGEON:
            return seen[(x, y)]
        for (dx, dy), k in STEPS.items():
            n = (x + dx, y + dy)
            if 0 <= n[0] < 21 and 0 <= n[1] < 21 and n not in seen and get(*n) != MOUNTAIN:
                seen[n] = seen[(x, y)] + [k]
                todo.append(n)
    raise Fail("no dungeon to walk to")


def play(options, port, shots):
    g = Game(port)
    try:
        # the menu, the page, its options, launch
        g.tap("0", gap=2)
        page = g.screen(0x4400)
        if "Akalabeth" not in page.replace("akalabeth", "Akalabeth"):
            raise Fail("Akalabeth's page did not open:\n" + page)
        for k in options:
            g.tap(k.lower())
        page = g.screen(0x4400)
        g.loads_off()
        g.tap("l", gap=0.5)
        scr = g.wait_text("press a key to continue")
        flags = bytes(g.v.mem(FLAGS, FLAGS + 3))
        want = bytes(ON if k in options else 0 for k in "AHGF")
        if flags != want:
            raise Fail(f"the trainer's flags are {flags.hex()}, not {want.hex()}")
        if "trained" in scr.lower():
            raise Fail("the trainer asked its questions")
        print(f"  launched: flags {flags.hex()}, the credits up, no questions")

        # the title, and the instructions with Y
        g.tap(" ")
        g.wait_text("instructions (y/n)")
        g.tap("y")
        for text in PAGES:
            g.tap(" ")
            g.wait_text(text)
            d011 = g.v.mem(0xD011, 0xD011)[0]
            if d011 & 0x20 or not d011 & 0x10:
                raise Fail(f"{text!r}: the screen is not text, on ($D011 {d011:02x})")
            if shots:
                g.v.shot(os.path.join(shots, f"u0_{len(options)}_{PAGES.index(text)}.png"))
        print(f"  the instructions: {len(PAGES) - 1} pages of text, no picture, no load")

        # a character: lucky number 42, level 5, these qualities, a fighter
        for k in "42\r5\r":
            g.tap(k, gap=0.6)
        g.wait_text("shalt thou play with these qualities")
        g.key("Y")
        g.go(1)
        g.key("F")
        g.go(2)
        gold = g.gold()
        for k in "FFF":                     # 30 food
            g.key(k)
        g.key("R")                          # a rapier, 8 gold
        g.go(1)
        spent = gold - g.gold()
        if ("G" in options) != (spent == 0):
            raise Fail(f"gold {gold:g} -> {g.gold():g} with the options {options!r}")
        g.key("Q")
        g.go(3)
        print(f"  a fighter, food {g.food():g}, gold {gold:g} -> {g.gold():g}")

        # the way to the nearest dungeon
        _dims, te = g.array("TE")
        x, y = int(g.scalar("TX")), int(g.scalar("TY"))
        walk = path_to_dungeon(te, (x, y))
        food = g.food()
        for k in walk:
            g.key(k)
            g.go(0.6)
        now = (int(g.scalar("TX")), int(g.scalar("TY")))
        if te[now[0] + 21 * now[1]] != DUNGEON:
            raise Fail(f"walked {''.join(walk)} from {(x, y)} to {now}, not a dungeon")
        used = food - g.food()
        if ("F" in options) != (used == 0):
            raise Fail(f"food {food:g} -> {g.food():g} over {len(walk)} steps, options {options!r}")
        print(f"  walked {''.join(walk)} from {(x, y)} to the dungeon at {now}, food used {used:g}")

        g.key("X")
        g.go(3)
        level = g.scalar("IN")
        if level < 1:
            raise Fail(f"not in the dungeon (IN = {level:g})")
        for k in "PPWP":
            g.key(k)
            g.go(0.6)
        if shots:
            g.v.shot(os.path.join(shots, f"u0_{len(options)}_dungeon.png"))
        print(f"  down the ladder: dungeon level {level:g}, hit points {g.array('C')[1][0]:g}")
    finally:
        g.v.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shots", help="screenshots of the pages and the dungeon into DIR")
    args = ap.parse_args()
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    ok = True
    for options, port in (("", 6640), ("FGAH", 6642)):
        print(f"options {options or 'as they were'}:")
        try:
            play(options, port, args.shots)
        except Fail as e:
            print(f"  FAILED: {e}")
            ok = False
    print("all good" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
