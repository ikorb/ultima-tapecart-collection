#!/usr/bin/env python3
"""The save editor's fields against the games' own screens, in VICE.

    python -m tools.vice.editor_game_check GAME SAVE [id=value ...]   (default: EDITS[GAME])

SAVE (a launcher save file, plain or PC64) is edited by the editor's code
(editor/cli.ts) -- distinct values in many fields, so that a field read from
the wrong place or labelled wrongly shows as the wrong number on the wrong
line -- put on a blank disk in a 1541, imported into a fresh cart through
the launcher's page (I, F, Y, RETURN), and the game launched (J, or L for
Ultima I); then the game's own status screens are opened with its keys
(through the keyboard matrix) and screenshotted to build/editor-game/GAME-*.png
for reading.  Needs node and VICE 3.11 or later.
"""
import os
from ultima import paths
import subprocess
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)

from ultima.flash import regions
from tests import test_file_xfer as T
from tools.vice import xfer_file_check as X
from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice

OUT = "build/editor-game"
NAMES = {g: T.NAMES[g] for g in T.NAMES}


def prepare(game, save, edits, port):
    os.makedirs(OUT, exist_ok=True)
    edited = f"{OUT}/{game}_edited.seq"
    r = subprocess.run(["node", "editor/cli.ts", "set", save, edited, *edits], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr)
    data = Path(edited).read_bytes()
    if data[:7] == b"C64File":                  # a PC64 save in: the plain file onto the disk
        data = data[26:]
    disk = f"{OUT}/{game}.d64"
    with open(disk, "wb") as fh:
        fh.write(T.with_file(NAMES[game], data))
    fresh = bytes(TCRT.read(X.IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
    cart = X.with_flash(fresh, f"{OUT}/{game}.tcrt")
    text = X.session(cart, disk, game, "i", port)
    if "Done." not in text:
        raise SystemExit(f"the import failed:\n{text}")
    time.sleep(1.0)
    return cart


def launch(cart, game, port, key, before=""):
    v = Vice(cart, port=port)
    X.wait_for(v, ["Select a game"], 60)
    for _ in range(5):
        v.tap(str(X.LIST.index(game) + 1), gap=1)
        try:
            X.wait_for(v, ["B  Back"], 10)
            break
        except RuntimeError:
            pass
    for k in before:                            # page options first (P: no idle turns)
        v.tap(k, gap=1)
    v.tap(key, gap=1)
    return v


class Shots:
    def __init__(self, v, game):
        self.v, self.game, self.n = v, game, 0

    def __call__(self, what):
        self.n += 1
        path = f"{OUT}/{self.game}-{self.n:02d}-{what}.png"
        self.v.shot(path)
        print("shot", path, flush=True)


def u1(v, shot):
    """Continue the game, character 1, Ztats (space: the next page)."""
    v.run(30)
    v.tap("\r", frames=10, gap=5)
    v.tap("b", frames=20, gap=8)
    v.tap("1", frames=20, gap=20)
    shot("play")
    v.tap("z", frames=10, gap=5)
    shot("ztats")
    v.tap(" ", frames=10, gap=4)
    shot("ztats2")


def u2(v, shot):
    """Ztats: one screen."""
    v.run(40)
    shot("play")
    v.tap("z", frames=10, gap=4)
    shot("ztats")


def u3(v, shot):
    """Ztats for 1: a line for each key (RETURN), cards, marks and the lists last."""
    v.run(45)
    v.tap("z", frames=10, gap=3)
    v.tap("1", frames=10, gap=6)
    for k in range(40):
        v.tap("\r", frames=6, gap=2.5)
        if k % 3 == 2:
            shot(f"ztats{k}")


def u4(v, shot):
    """Ztats for 1, then 0 (the party), F7 for each next page.  The page's P
    first: idle turns would end the Ztats."""
    v.run_to(0x408F, timeout=180)              # game main's key read
    v.run(3)
    v.tap("z", gap=1.5)
    v.tap("1", gap=3)
    shot("ztats1")
    v.tap("\x88", gap=3)
    v.tap("z", gap=1.5)
    v.tap("0", gap=3)
    shot("party")
    for k in range(7):
        v.tap("\x88", gap=3)                   # F7: the next page
        shot(f"party{k + 2}")


def u5(v, shot):
    """Ztats: fire picks the first in the list, east turns the page.  U5
    reads the joystick at $5BE4 (LDA $DC00), repointed at $0334 as
    u5_drive.joystick_patch does; fire is held one frame, or the stats
    page reads it too and closes."""
    v.run(70)
    shot("play")
    v.poke(0x0334, b"\xff")
    v.poke(0x5BE4, bytes([0xAD, 0x34, 0x03]))

    def push(bits, hold):
        v.poke(0x0334, bytes([bits]))
        v.run(hold)
        v.poke(0x0334, b"\xff")
        v.run(3)
    v.tap("z", frames=8, gap=4)
    push(0xEF, 0.02)                            # fire
    shot("ztats")
    for k in range(30):
        push(0xF7, 0.07)                        # east
        shot(f"east{k}")


def u6(v, shot):
    """Journey onward lands in the game: the party panel (a poisoned name
    is drawn differently, game $0F8A)."""
    v.run(45)
    shot("play")


def seq(fmt, ks, first):
    return [fmt.format(k=k, v=first + j) for j, k in enumerate(ks)]


# a distinct value in each field, so that each on the game's screen says which byte it came from
EDITS = {
    "u1": ["p0.str=11", "p0.agi=12", "p0.sta=13", "p0.cha=14", "p0.wis=16", "p0.int=17", "p0.coins=1234",
           "p0.food=456", "p0.exp=789", "p0.hp=321", "p0.race=2", "p0.class=3", "p0.sex=1",
           *seq("p0.weapon.{k}={v}", range(15), 21), *seq("p0.armour.{k}={v}", range(5), 41),
           *seq("p0.spell.{k}={v}", range(10), 51), *seq("p0.gem.{k}={v}", range(4), 61)],
    "u2": ["sex=198", "race=1", "class=2", "str=11", "agi=12", "sta=13", "cha=14", "wis=15", "int=16", "hp=1234",
           "exp=567", "coins=890", "food=345", "torches=21", "keys=22", "tools=23",
           *seq("weapon.{k}={v}", range(9), 31), *seq("armour.{k}={v}", range(6), 41),
           *seq("spell.{k}={v}", range(9), 51), *seq("item.{k}={v}", range(16), 61)],
    "u3": ["plrs0.str=11", "plrs0.dex=12", "plrs0.int=13", "plrs0.wis=14", "plrs0.mp=15", "plrs0.maxhp=2345",
           "plrs0.hp=1234", "plrs0.exp=3456", "plrs0.food=4567", "plrs0.gold=5678", "plrs0.torches=21",
           "plrs0.gems=22", "plrs0.keys=23", "plrs0.powder=24", "plrs0.card4=1", "plrs0.card5=1", "plrs0.card6=1",
           "plrs0.card7=1", "plrs0.race=197", "plrs0.class=215", "plrs0.sex=198", "plrs0.armour=3", "plrs0.weapon=6",
           *seq("plrs0.weapons.{k}={v}", range(1, 16), 31), *seq("plrs0.armours.{k}={v}", range(1, 8), 51)],
    "u4": ["torches=11", "gems=12", "keys=13", "sextant=1", "food=1234", "gold=5678", "rune.0=1", "rune.2=1",
           "stone.1=1", "stone.3=1", "bell=1", "book=0", "candle=1", "keyT=1", "keyL=0", "keyC=1", "horn=1",
           "wheel=0", "skull=1", "p0.weapon=6", "p0.armour=3", "p0.str=21", "p0.dex=22", "p0.int=23", "p0.mp=24",
           "p0.hp=345", "p0.maxhp=800", "p0.exp=4321", *seq("weapons.{k}={v}", range(1, 16), 21),
           *seq("armours.{k}={v}", range(1, 8), 41), *seq("reagent.{k}={v}", range(8), 51),
           *seq("mixture.{k}={v}", range(26), 61)],
    "u6": ["c0.poisoned=0", "karma=36"],
    "u5": ["c0.str=11", "c0.dex=12", "c0.int=13", "c0.mp=14", "c0.hp=77", "c0.maxhp=88", "c0.exp=1234", "c0.eq4=3",
           "c0.eq5=46", "food=2345", "gold=3456", "keys=21", "gems=22", "torches=23", "grapple=24",
           *seq("weapon.{k}={v}", range(26), 31), *seq("armour.{k}={v}", range(16), 61),
           *seq("reagent.{k}={v}", range(8), 91), *seq("scroll.{k}={v}", range(8), 11),
           *seq("potion.{k}={v}", range(8), 21), *seq("spell.{k}={v}", range(48), 40)],
}


GAMES = {"u1": ("l", u1), "u2": ("j", u2), "u3": ("j", u3), "u4": ("j", u4, "p"), "u5": ("j", u5), "u6": ("j", u6)}


def main():
    game, save, *edits = sys.argv[1:]
    edits = edits or EDITS[game]
    port = 6640
    cart = prepare(game, save, edits, port)
    key, show, *before = GAMES[game]
    v = launch(cart, game, port + 4, key, *before)
    try:
        show(v, Shots(v, game))
    finally:
        v.quit()


if __name__ == "__main__":
    main()
