#!/usr/bin/env python3
"""The launcher's game options as RAM patches (asm/patch.s).

A patch is (option, address, original bytes, new bytes).  The driver applies
it after a load when the option is on and every original byte is in place,
so it can only ever land in the code it was written for.  The originals are
therefore also the patch's *signature*, and the one thing that has to be
proven at build time is that the signature cannot turn up in something
else: check() takes every unit the game can load (where it lands and its
bytes) and fails unless every unit that has the signature at the patched
address is the intended code.

Options are bits in the driver's options byte; set = the option is ON, i.e.
the original behaviour is switched OFF (the page shows it the other way
round: "food used while walking: off").
"""
from ultima.pin import Pin

FOOD = 0x01                     # no food used while walking
PASS = 0x02                     # no turn passes on an idle keyboard
JOURNEY = 0x04                  # straight to the saved game, this launch only
                                # (set by the page for J, never stored)
TILES = 0x08                    # Ultima IV: Remastered's tile set (no RAM
                                # patch: the page pokes the driver's disk-A
                                # map pointer, ultima/games/u4/tileset.py)

TORCH = 0x10                    # igniting a torch does not use one up (U2-U5:
                                # U1 has none, U6 no options at all; U5's
                                # table is streamed from the cart, patch.s
                                # PT_STREAM)

ITEMS = 0x20                    # spells, keys and gems (U3: and powder) never
                                # used up: U3 (Ultima III Gold's trainers), U4
                                # (the Remastered kit's cheats), U5 (keys never
                                # break, mixtures and MP not needed)
AVOID = 0x40                    # Ultima IV: a monster's attack can be avoided
                                # ("AVOID?"), the Remastered kit's cheat; U3
                                # too (u3avoid.s, hooks always in, no RAM patch)
BALLOON = 0x80                  # Ultima IV: the balloon steered, no drift

POWERS = 0x04                   # Ultima IV: T teleports, B brings a transport, X
                                # wins a fight; U3: Gold's ingame keys; U2: F7
                                # teleports, B brings a transport; U1: the same,
                                # and F1 tells the position.  The
                                # same bit as JOURNEY, but only ever in the settings
                                # and the page's caps: a poke option (the page keeps
                                # poke-only bits out of the driver's options byte).
                                # U5: F7 teleports, B brings a vehicle, patches, so
                                # the bit is in its options byte (U5's Journey
                                # Onward is a poke)
CLAMP = 0x80                    # Ultima II: counts stop at 99 and 9999 instead
                                # of wrapping to 0 (ultima/games/u2/u2clamp.s, hooks
                                # always in, a poke).  The same bit as BALLOON,
                                # which only U4 offers: the page's line for it
                                # has each game's own words and key
STEAL = 0x80                    # Ultima I: no one steals from the party (the
                                # bard, the jester, the dungeon's thieves).  A
                                # bit of U1's options byte, the same as BALLOON
                                # and CLAMP, with its own line on the page

CAPS = {FOOD: "food", PASS: "pass", TORCH: "torch", ITEMS: "items", AVOID: "avoid",
        BALLOON: "balloon"}


class Patch:
    """orig may be a Pin (ultima/pin.py), new then a function of the original
    bytes: resolve() puts both in from the game's own data."""

    def __init__(self, option, addr, orig, new, what):
        if not isinstance(orig, Pin):
            orig, new = bytes(orig), bytes(new)
            assert len(orig) == len(new) and orig != new, what
        assert 0 < len(orig) < 32, what
        self.option, self.addr, self.orig, self.new, self.what = option, addr, orig, new, what

    def resolve(self, data):
        """The original bytes, from data (they must hash as pinned)."""
        if isinstance(self.orig, Pin):
            data = bytes(data[:len(self.orig)])
            assert data == self.orig, f"{self.what}: not the original bytes"
            new = bytes(self.new(data) if callable(self.new) else self.new)
            assert len(new) == len(data) and new != data, self.what
            self.orig, self.new = data, new
        return self

    def __repr__(self):
        return f"<{self.what} ${self.addr:04x}>"


def table(patches):
    out = bytearray()
    for p in patches:
        assert not isinstance(p.orig, Pin), f"{p.what}: not resolved"
        out += bytes([p.option, p.addr & 0xFF, p.addr >> 8, len(p.orig)]) + p.orig + p.new
    return bytes(out + b"\x00")


def asm(label, patches):
    """acme source for the table, under `label`."""
    data = table(patches)
    lines = [f"{label}:"]
    for i in range(0, len(data), 16):
        lines.append("        !byte " + ", ".join(f"${b:02x}" for b in data[i:i + 16]))
    return "\n".join(lines) + "\n"


def caps(patches):
    """The options the page shows (JOURNEY is not one: it is J)."""
    c = 0
    for p in patches:
        c |= p.option
    return c & (FOOD | PASS | TORCH | ITEMS | AVOID | BALLOON)


def check(patches, units, intended):
    """units: [(name, load address, bytes)] -- everything the game loads.
    intended: {patch.what: set of unit names it is for}.  Raises unless the
    signature is found in at least one intended unit and in no other."""
    for p in patches:
        hits = set()
        for name, addr, data in units:
            off = p.addr - addr
            if 0 <= off and off + len(p.orig) <= len(data) and data[off:off + len(p.orig)] == p.orig:
                hits.add(name)
        want = intended[p.what]
        if not hits & want:
            raise SystemExit(f"patch {p.what}: its original bytes are in none of {sorted(want)}")
        if hits - want:
            raise SystemExit(f"patch {p.what}: its original bytes also turn up in "
                             f"{sorted(hits - want)[:8]}")


def check_floating(patches, placed, floating, intended):
    """As check(), for a game whose units load wherever the caller says,
    always to a page boundary: `placed` are the units whose address is
    known, `floating` [(name, bytes)] the rest, and a floating unit counts
    as a hit if it has the signature at any offset with the address's low
    byte -- wherever it might be loaded, it would match there."""
    for p in patches:
        hits = set()
        for name, addr, data in placed:
            off = p.addr - addr
            if 0 <= off and off + len(p.orig) <= len(data) and data[off:off + len(p.orig)] == p.orig:
                hits.add(name)
        for name, data in floating:
            i = data.find(p.orig)
            while i >= 0:
                if (i & 0xFF) == (p.addr & 0xFF):
                    hits.add(name)
                i = data.find(p.orig, i + 1)
        want = intended[p.what]
        if not hits & want:
            raise SystemExit(f"patch {p.what}: its original bytes are in none of {sorted(want)}")
        if hits - want:
            raise SystemExit(f"patch {p.what}: its original bytes also turn up in "
                             f"{sorted(hits - want)[:8]}")


def find(data, pattern, base, count=1, what=""):
    """The load addresses of `pattern` in `data` (loaded at `base`),
    asserting how many there are."""
    hits, i = [], data.find(pattern)
    while i >= 0:
        hits.append(base + i)
        i = data.find(pattern, i + 1)
    if len(hits) != count:
        raise SystemExit(f"{what}: {pattern.hex()} found {len(hits)} times, expected {count}")
    return hits
