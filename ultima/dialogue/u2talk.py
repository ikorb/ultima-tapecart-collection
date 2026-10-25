#!/usr/bin/env python3
"""Ultima II's dialogue as text, from its disks.

    python -m ultima.dialogue.u2talk [--out build/dialogue/u2]

Writes u2-dialogue.txt: every town and castle, who stands where and what
each says when Talked to.  Read from the original d64s (the cart stores
these files unchanged).

How the game does it (ULTIMA, loaded at $5000; the Talk command, $8230):
- A place is MAP xy / MON xy / TLK xy, x = $8E13, y = $8E14 (ULTIMA
  $689B).  On Earth (the Player disk) x is the time period, in the order
  of the time-door sign's text ($776F: 0 Legends, 1 9,000,000 B.C., 2 300
  B.C., 3 1990 A.D., 4 2112 A.D.); on a planet (the Program + Galactic
  disk, picked by $8E37) it is the planet, copied there on landing, in
  STARS' list (1 Mercury ... 8 Pluto, 9 X).  y is the place: 0 the
  surface, 1-3 towns and castles (each has a TLK file), 4-5 towers and
  dungeons (none has).
- MON xy holds the 32 people, a field each: x +$00, y +$20, the tile +$60
  (a map byte, the tile x 4), the talk byte +$A0.  The byte's other
  values (0-3) are not Talk's (movement, by the look of it -- inferred).
- Talk ($8230): a talk byte of $80 or more prints string (byte - $80) of
  TLK xy ($5B1C: string n follows the n-th $00 from $9C80; text is ASCII
  with bit 7 set, $8D or $0D a new line, $87 a beep).  Otherwise the tile decides, each line
  inline in ULTIMA: $6C the king (Lord British's lines, $83A6), $60 a
  guard, $64 a jester, $68 a merchant, $F0 a fighter, $F4 a cleric, $F8 a
  wizard, $FC a thief; anyone else "FUNNY, NO RESPONSE!" ($8216).
- One string does more: on X (planet 9), place 3, talk byte $81 (Father
  Antos's blessing) sets $8E36 ($8389).
- A TLK page is 256 bytes; after its last string comes padding or the
  leftovers of the authors' source text, which are not shown.
"""
import argparse
import os

from ultima.disks.d64 import D64
from ultima import paths
from ultima.pin import Pin

GALACTIC, PLAYER = "u2a", "u2b"
LABEL = {GALACTIC: "Program + Galactic", PLAYER: "Player Master"}
ULTIMA_ADDR = 0x5000
ERAS = ["Legends", "9,000,000 B.C.", "300 B.C.", "1990 A.D.", "2112 A.D."]
PLANETS = ["Earth", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune",
           "Pluto", "X"]
# tile -> (what the person is, where Talk's line for it is printed in ULTIMA)
FIXED = {0x6C: ("the king", None), 0x60: ("a guard", 0x824B), 0x64: ("a jester", 0x8273),
         0x68: ("a merchant", 0x8297), 0xF0: ("a fighter", 0x82CA), 0xF4: ("a cleric", 0x82F3),
         0xF8: ("a wizard", 0x8315), 0xFC: ("a thief", 0x8344)}
NO_RESPONSE = 0x8216


def text(bs):
    out = ""
    for b in bs:
        assert b in (0x0D, 0x87, 0x8D) or 0xA0 <= b < 0xE0, f"not text: ${b:02X}"
        out += {0x0D: "\n", 0x87: "", 0x8D: "\n"}.get(b, chr(b & 0x7F))       # $87: a beep
    return out


class Ultima:
    def __init__(self, raw):
        assert raw[:2] == b"\x00\x20", "ULTIMA's header"
        self.p = raw[2:]

    def inline(self, at):
        """The string after the JSR $4006 at `at`."""
        o = at - ULTIMA_ADDR
        assert self.p[o:o + 3] == b"\x20\x06\x40", f"no JSR $4006 at ${at:04X}"
        end = self.p.index(0, o + 3)
        return text(self.p[o + 3:end])

    def check(self):
        """The Talk dispatch is the one this was written against."""
        o = 0x8230 - ULTIMA_ADDR
        assert self.p[o:o + 10] == bytes.fromhex("bda08fc98090034c7483"), "Talk at $8230"
        o = 0x8374 - ULTIMA_ADDR
        assert self.p[o:o + 6] == bytes.fromhex("38e980201c5b"), "the TLK print at $8374"
        o = 0x8389 - ULTIMA_ADDR
        assert self.p[o:o + 26] == Pin("#26:c59b88a7e8e9e7d8"), \
            "Father Antos at $8389"
        for tile, (_who, at) in FIXED.items():
            if at is None:
                continue
            # each line is reached by CMP #tile / BNE just before it
            assert self.p[at - ULTIMA_ADDR - 4:at - ULTIMA_ADDR - 2] == bytes([0xC9, tile]), f"tile ${tile:02X}"


def tlk_strings(raw):
    """TLK's strings 1..n: after the first $00, $00-terminated, until the
    first that is empty or not text (padding, the source's leftovers)."""
    p = raw[2:]
    assert p[0] == 0, "a TLK page starts with $00"
    out, o = [], 1
    while o < len(p):
        end = p.find(b"\x00", o)
        if end <= o:
            break
        try:
            out.append(text(p[o:end]))
        except AssertionError:
            break
        o = end + 1
    return out


def people(raw):
    p = raw[2:]
    assert len(p) >= 0xC0
    for i in range(32):
        x, y, tile, talk = p[i], p[0x20 + i], p[0x60 + i], p[0xA0 + i]
        if tile:
            yield i, x, y, tile, talk


def indent(s, by="    "):
    return "\n".join(by + l for l in s.split("\n"))


def place_name(planet, x, y):
    if planet == 0:
        return f"Earth, {ERAS[x]}, place {y}"
    return f"planet {PLANETS[x]}, place {y}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "dialogue", "u2"))
    a = ap.parse_args()
    disks = {name: D64(paths.disk(name)) for name in (GALACTIC, PLAYER)}
    ult = Ultima(disks[GALACTIC].file("ULTIMA")[0])
    ult.check()
    king = [ult.inline(0x83A6) + "<the player's name>", ult.inline(0x83BE).strip("\n"),
            "(the 50 g.p. taken -- or \"" + ult.inline(0x658C).strip() + "\" and no more)",
            ult.inline(0x83E8) + "<0300, 0200, 0100 or 0000>"]
    fixed = {t: (who, ult.inline(at) if at else "\n".join(king)) for t, (who, at) in FIXED.items()}
    nothing = ult.inline(NO_RESPONSE)

    out = ["Ultima II (C64) -- what the people of each town and castle say",
           "",
           "How to read this:",
           "  A place is named by its map file (MAP xy): on Earth x is the time period,",
           "  on a planet x is the planet; y is the place (1-3 are the towns and castles;",
           "  the game names none of them).  Positions are (x, y) on the 64 x 64 map,",
           "  as build/maps/u2/ draws them.",
           "  \"own line\": what that person says, from the place's TLK file.  Everyone else",
           "  says the line of their kind (below), or \"" + nothing + "\".",
           "  Lines nobody has are shown as unreachable: mostly the tails of older texts",
           "  left in the page (\"AN JOSE?\"), once a whole one (a bard's, on Earth).",
           "",
           "Lines by kind (inline in ULTIMA, chosen by the person's tile):"]
    for t, (who, line) in fixed.items():
        out.append(f"  {who} (tile ${t:02X}):")
        out.append(indent(line, "      "))
    out += ["  the king adds that many hit points: 300 below 5000, 200 below 7500, 100 below",
            "  9900, else none ($8407; printed through SUBS $46E0 as four digits).",
            "  Talking needs someone in the direction given (across a counter too); on the",
            "  surface nobody answers.",
            "  anyone else: " + nothing,
            ""]

    count = 0
    for planet, disk in ((0, PLAYER), (1, GALACTIC)):
        d = disks[disk]
        names = [n for n, *_ in d.directory()]
        for name in sorted(n for n in names if n.startswith("TLK ")):
            xy = name[4:]
            x, y = int(xy[0]), int(xy[1])
            pl = 0 if planet == 0 else x
            assert 1 <= y <= 3 and f"MON {xy}" in names and f"MAP {xy}" in names, name
            lines = tlk_strings(d.file(name)[0])
            folks = list(people(d.file(f"MON {xy}")[0]))
            title = place_name(pl, x, y)
            out += ["=" * 76, f"{title}   (MAP / MON / {name}, {LABEL[disk]} disk)",
                    "=" * 76, ""]
            used = set()
            own = [(talk - 0x80, i, px, py, tile) for i, px, py, tile, talk in folks if talk >= 0x80]
            for n, i, px, py, tile in sorted(own):
                assert 1 <= n <= len(lines), f"{name}: string {n} of {len(lines)}"
                used.add(n)
                out.append(f"[{px:2d},{py:2d}] own line {n} (tile ${tile:02X}):")
                out.append(indent(lines[n - 1]))
                if (pl, y, n) == (9, 3, 1):
                    out.append("    [and the blessing is given: $8E36 = 1]")
                out.append("")
            for n in range(1, len(lines) + 1):
                if n not in used:
                    out.append(f"(line {n} is in the file, but nobody here has it -- unreachable):")
                    out.append(indent(lines[n - 1]))
                    out.append("")
            kinds = {}
            for i, px, py, tile, talk in folks:
                if talk < 0x80:
                    kinds.setdefault(tile, []).append((px, py))
            for tile, where in sorted(kinds.items()):
                who = FIXED[tile][0] if tile in FIXED else f"tile ${tile:02X}"
                says = "their kind's line" if tile in FIXED else nothing
                out.append(f"{len(where)} x {who}: {says}  at " + " ".join(f"[{x},{y}]" for x, y in where))
            out.append("")
            count += 1
    assert count == 16, count
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "u2-dialogue.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("written", path)


if __name__ == "__main__":
    main()
