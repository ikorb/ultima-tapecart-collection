#!/usr/bin/env python3
"""Ultima I's spoken and fixed text as plain text, from its disk.

    python -m ultima.dialogue.u1talk [--out build/dialogue/u1]

Writes u1-dialogue.txt: the kings and their quests, the princesses, the
jester and the bard, the guards, the shopkeepers and the tavern's rumours,
the signs at the landmarks, the time machine and Mondain, the space station.
Read from the Ultima I disk (the cart stores these files unchanged).

Ultima I has no Talk command and no conversation files.  Everything a person
says is code in the overlay of the place (TW town, CA castle, OU outdoors,
TM the time machine and Mondain, SP space, DN dungeons; all run at $8C9E,
MI at $7400 holds the shared routines and tables).  Found by
disassembling those overlays; every address below is a
runtime address in the file named.

Text (MI $83DD, $842D, $848E): ASCII, mixed case.  $7C starts a new line
at column 0, $7E a new line at column 1, $7D a new line only if the cursor
is past column 1, $7F n moves n columns right (the texts centre themselves
with it).  Any other byte is a glyph of the font (LO's first KiB, ASCII
order); $0E, a triangle, is the command prompt's marker and is left out.  Two kinds of string:
- inline: `JSR $848E` (or $848A, which first sets column X, row Y) and the
  text after it up to a $00; the routine returns past it.  TM's $A7CE and
  $A7C8 clear the screen first and end in `JMP $848E`.
- table: `JSR $842D` followed by a 16-bit table address, X the index; each
  entry ends with a character that has bit 7 set ($8426 capitalises the
  first letter).  MI's tables: places $7CC0 (84 names), monsters $7A7F,
  weapons $777C, armour $78D4, spells $7888, vehicles $7930, attributes
  $7842, the lords of the four lands $7BDA.

Who says what, and when (verified in the code unless marked inferred):
- Kings (CA): the command Transact while standing at the king's counter
  (tile $6C, CA $95BD).  "Pence": any amount, paid back as 1.5 x the amount
  in hit points ($96AE).  "Service": a quest kept per king in $821E,k
  ($9739).  k is the castle: continent c ($81E4) and the castle's place in
  it, n = 0 or 1, give k = 2c + 1 for n = 1 and 6 - 2c for n = 0 (CA
  $8CB7).  Even k: "Go forth and find" landmark 2 + 21 (3 - c) ($9791);
  odd k: "Go now and kill a" monster 30 + 5c ($97FE).  The landmark's
  visit (OU $94DA) or the monster's death in a dungeon (DN $9822) sets bit
  7, and the king rewards it: even k strength, odd k a gem and a secret
  ($9857, $98EF).
- The princess (CA $8DD3): once the guards are roused she follows the
  player ($9B37); leaving by the west edge with her within 4 columns of it
  saves her ($8DDE): +500 hit points, pence and experience, and with 20
  enemy vessels destroyed ($822B) and 7000 experience ($825C) she tells of
  the time machine and makes it appear ($822A = 1, $8F1E).  Her name is
  $A1A4,k.
- Gwino the jester (CA $9D39) and Iolo the bard (TW $A40C): each turn they
  wander; when the step is blocked, 40 in 256 that they sing; when the
  player blocks it, they steal.  Killing the jester gives a key ($90D7).
- Guards (CA $9C66, TW $A347) attack once roused: by an attack that hits
  ($8EEC/$904B) or a theft caught ($92EF/$94D8).
- Shops (TW $93C9, Transact at a counter): the counter's tile picks the
  shop ($ADA6: tiles $64-$6C), its name is table $ADC6,type entry n (the
  town's layout, below), the buy and sell routines $ADD2 / $ADDE.
- The tavern (TW $99C1): a drink costs 1 pence; at drinks >= stamina / 4
  ($8241) with the wench (slot 1 of the town's people) next to the player
  "Thou hast been seduced!" (half the pence, -1 wisdom, at least 5); else
  181 in 256 that the keeper tells one of eight rumours, chosen by the top
  three bits of a random byte ($9AF1-$9B28, table $ADEA).  For a female
  player ($822C = 1) the "Wench" in the rumour is a "Lecher" (TW $8CAB).
- Landmarks (OU $9464): eight places ($A119), each a text ($9EEC), an
  attribute raised ($A121) and the king whose quest it ends ($A129).
- Time machine: boarding it outdoors (OU $90DB) needs the four gems; TM
  is the journey and the fight (its commands at $920D).
- Space (SP): the station's docking, and the rank of Space Ace at 20 kills.
- Spells: what the player calls out (DN $94A4 table $A8CA, OU $9313).

Towns and castles: layout n of TC (0-1 the castles, 2-9 the towns) serves
place 21c + n (castles) or 21c + 13 + (n - 2) (towns) of every continent c
(TW $8CC6, CA $8CB7; see maps/u1maps.py).  So each continent has a
Britain-like town with the same shops: the shop names repeat four times.
"""
import argparse
import os
from ultima import paths

from ultima import pin
from ultima.disks.d64 import D64  # noqa: E402

DISK = paths.disk("u1")
OVERLAY = 0x8C9E
BASES = {"MI": 0x7400, "TC": 0x4000}

# MI's tables
PLACES, MONSTERS, WEAPONS, ARMOUR, SPELLS = 0x7CC0, 0x7A7F, 0x777C, 0x78D4, 0x7888
VEHICLES, ATTRIBUTES, LORDS = 0x7930, 0x7842, 0x7BDA
INLINE = {0x848E, 0x848A}                      # MI's inline printers
TABLE = {0x842D, 0x8426}                       # MI's table printers (pointer follows)

PROMPT = 0x0E                                  # glyph 14 of LO's font, a triangle
SHOP_TYPES = ["armour", "food", "weapons", "magic", "pub", "transport"]


class Module:
    def __init__(self, name, data):
        self.name, self.d = name, data
        self.base = BASES.get(name, OVERLAY)
        self.inline_entries = set(INLINE)
        self.used = set()                     # inline sites taken by the sections

    def b(self, a):
        assert self.base <= a < self.base + len(self.d), (self.name, hex(a))
        return self.d[a - self.base]

    def w(self, a):
        return self.b(a) | self.b(a + 1) << 8

    def expect(self, a, hexbytes):
        """The code the extraction relies on is what it was read as (hex, or a
        Pin's "#n:hash" for a longer run)."""
        want = pin.want(hexbytes)
        got = self.d[a - self.base:a - self.base + len(want)]
        assert got == want, f"{self.name} ${a:04X}: {got.hex()} != {want.hex()}"

    def raw_inline(self, a):
        """The text after an inline-print JSR at a: list of tokens, end."""
        toks, o = [], a
        while True:
            c = self.b(o)
            o += 1
            if c == 0:
                return toks, o
            if c == 0x7F:
                toks.append(("tab", self.b(o)))
                o += 1
                continue
            c &= 0x7F
            if c == PROMPT:                   # the command prompt's marker: not shown
                continue
            assert 0x20 <= c <= 0x7E, f"{self.name} ${o - 1:04X}: byte ${c:02X} in a text"
            toks.append(("ch", c))
            assert o - a < 400, f"{self.name} ${a:04X}: unterminated text"

    def inline(self, site):
        """The text printed by the JSR at site (asserts it is one)."""
        assert self.b(site) == 0x20 and self.w(site + 1) in self.inline_entries, \
            f"{self.name} ${site:04X} is not an inline print"
        toks, _ = self.raw_inline(site + 3)
        assert toks, f"{self.name} ${site:04X}: empty text"
        self.used.add(site)
        return toks

    def table(self, ptr, i):
        """Entry i of a bit-7-terminated table at ptr."""
        o = ptr
        for _ in range(i):
            while not self.b(o) & 0x80:
                o += 2 if self.b(o) == 0x7F else 1
            o += 1
        toks = []
        while True:
            c = self.b(o)
            if c == 0x7F:
                toks.append(("tab", self.b(o + 1)))
                o += 2
                continue
            assert 0x20 <= c & 0x7F <= 0x7E, f"{self.name} table ${ptr:04X}[{i}]: ${c:02X}"
            toks.append(("ch", c & 0x7F))
            o += 1
            if c & 0x80:
                return toks

    def sites(self):
        """Every inline-print JSR in the file whose text decodes."""
        out = []
        for i in range(len(self.d) - 3):
            if self.d[i] == 0x20 and (self.d[i + 1] | self.d[i + 2] << 8) in self.inline_entries:
                try:
                    toks, _ = self.raw_inline(self.base + i + 3)
                except AssertionError:
                    continue
                if toks:
                    out.append(self.base + i)
        return out


def flat(toks):
    """A text on one line: its line breaks and column moves as single spaces."""
    return " ".join(say(toks, indent="").split())


def plain(toks):
    return "".join(chr(v) if k == "ch" else "" for k, v in toks)


class Screen:
    """Lays text out the way MI $83DD does, so the centring shows."""

    def __init__(self, col=0):
        self.lines = [" " * col]

    def col(self, n):
        self.lines[-1] = self.lines[-1].ljust(n)[:n] if len(self.lines[-1]) > n else self.lines[-1].ljust(n)
        return self

    def put(self, toks):
        if isinstance(toks, str):
            toks = [("ch", ord(c)) for c in toks]
        for k, v in toks:
            if k == "tab":
                self.lines[-1] += " " * v
            elif v == 0x7C:
                self.lines.append("")
            elif v == 0x7E:
                self.lines.append(" ")
            elif v == 0x7D:
                if len(self.lines[-1]) >= 2:
                    self.lines.append(" ")
                else:
                    self.lines[-1] = " "
            else:
                self.lines[-1] += chr(v)
        return self

    def text(self, indent="    "):
        lines = [ln.rstrip() for ln in self.lines]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        out, blank = [], 0
        for ln in lines:                          # at most one blank line in a row
            blank = blank + 1 if not ln else 0
            if blank < 2:
                out.append(indent + ln if ln else "")
        return "\n".join(out)


def say(*parts, col=0, indent="    "):
    s = Screen(col)
    for p in parts:
        s.put(p)
    return s.text(indent)


def load():
    disk = D64(DISK)
    mods = {}
    for name in ("MI", "TW", "CA", "OU", "TM", "SP", "DN", "TC"):
        data, ok = disk.payload(name)
        assert ok, f"{name} crosses an unreadable sector"
        mods[name] = Module(name, data)
    # TM's own printers clear the screen and then JMP $848E
    mods["TM"].expect(0xA7C8, "#21:5bc16f9d13617b77")
    mods["TM"].inline_entries |= {0xA7C8, 0xA7CE}
    return mods


def check_mi(mi):
    mi.expect(0x83DD, "297f c97c 90f4 f019 c97e f00a c97d")     # the control codes
    mi.expect(0x848E, "68 8db583 68 8db683")
    names = [plain(mi.table(PLACES, i)) for i in range(84)]
    assert names[0] == "The Castle of Lord British" and names[13] == "Britain", names[:14]
    assert all(n and n.isprintable() for n in names)
    assert plain(mi.table(MONSTERS, 30)) == "gelatinous cube", plain(mi.table(MONSTERS, 30))
    assert plain(mi.table(MONSTERS, 6)) == "Ness creature"
    assert [plain(mi.table(SPELLS, i)) for i in (0, 10)] == ["Prayer", "Kill"]
    assert [plain(mi.table(ATTRIBUTES, i)) for i in (0, 6)] == ["Hit points", "Intelligence"]
    return names


def continent_of(place):
    return place // 21


# ---------------------------------------------------------------- castles

def castles(m, names):
    ca, mi = m["CA"], m["MI"]
    # k from the continent and the castle (n): n odd keeps n + 2c, else 6 - (n + 2c)
    ca.expect(0x8CC2, "#24:c10021859514c13e")
    ca.expect(0x9774, "ad7ca1 4a b06d")                  # odd k: kill, even: find
    ca.expect(0x9791, "#27:b4354166bd9a724d")
    ca.expect(0x97FE, "#20:a7e76a0c24ece47c")
    ca.expect(0x9857, "ad7ca1 2901 d072")                # odd k: a gem
    ca.expect(0x98EF, "ade481 0a a8 b90999")              # gem by continent
    ca.expect(0x8DDE, "adbdcd c905 9003")                 # princess x < 5
    ca.expect(0x8E8C, "#19:aec11301bf0ae8a2")
    ca.expect(0x96AE, "ad73a1 854c ad74a1 4a 854d 664c")  # hit points = 1.5 x pence
    dn = m["DN"]                                       # a kill quest: monster 5 of levels
    dn.expect(0x9F4E, "#21:a0b92d66c70e7a91")  # 20 + 5g
    dn.expect(0x9808, "#22:c626bde8cf82b98c")

    def k_of(c, n):
        k = n + 2 * c
        return k if k & 1 else 6 - k

    cols = [ca.b(0xA223 + k) for k in range(8)]
    princess = [plain(ca.table(0xA1A4, k)).strip() for k in range(8)]
    gems = [ca.w(0x9909 + 2 * c) for c in range(4)]

    def quest(k, c):
        if k & 1 == 0:
            place = 2 + 21 * (3 - c)
            target = names[place]
            first = ca.inline(0x977A)
        else:
            mon = 30 + 5 * c
            target = plain(mi.table(MONSTERS, mon))
            first = ca.inline(0x97E7)
        # the target's column, set from $A223,k: centred (a 28-30 column line)
        assert abs(cols[k] - (29 - len(target)) / 2) <= 1, (k, cols[k], target)
        s = Screen(7).put(first)
        s.col(cols[k]).put(target).put(ca.inline(0x97B1))
        return target, s.text("      ")

    out = []
    a = out.append
    a(section("THE KINGS (castles, overlay CA)"))
    a("""How a king is reached: the command Transact ("T") prints "Transact with
King" (CA $95AF) and needs the player on the king's counter.  Each castle's
king keeps one quest at a time (save byte $821E + k).  Lord British is the
king of his own castle and speaks as every other king does.
""")
    a("Not at the counter:")
    a(say(ca.inline(0x95C8)))
    a("\nOnce the guards are roused (an attack that hit, or a theft caught):")
    a(say(ca.inline(0x95E2)))
    a("\nOtherwise, with no quest finished:")
    a(say(ca.inline(0x960A), "<P or S>"))
    a("""
  Anything but P or S:""")
    a(say(ca.inline(0x9641), indent="      "))
    a("  P (\"pence\"):")
    a(say(ca.inline(0x964D), "<amount, up to 4 digits>", indent="      "))
    a("    more than the player has:")
    a(say(ca.inline(0x967B), indent="      "))
    a("    else the pence are taken and:")
    a(say(ca.inline(0x96CA), "<amount x 1.5>", ca.inline(0x96F6), indent="      "))
    a("    (hit points at most 9999)")
    a("  S (\"service\"):")
    a(say(ca.inline(0x972E), indent="      "))
    a("    a quest from this king already open:")
    a(say(ca.inline(0x9741), indent="      "))
    a("    else the castle's quest, on a cleared window (each castle, below).")
    a("\nWith the quest done (the king's byte has bit 7 set):")
    a(say(ca.inline(0x9825), "<the player's name>", ca.inline(0x9831)))
    a("  then the castle's reward (below), and the quest can be taken again.\n")
    a("""The strength reward (even k) is (99 - strength) / 8 points, at least 1
unless strength is already 99 ($987D):""")
    a(say(ca.inline(0x985E), "<n>", ca.inline(0x989B), "<s if n is not 1>", ca.inline(0x98B0)))
    a("")

    for c in range(4):
        for n in range(2):
            place = 21 * c + n
            k = k_of(c, n)
            target, qtext = quest(k, c)
            a("-" * 76)
            a(f"{names[place]}  (castle k = {k}, princess {princess[k]})")
            a(f"  continent {c}, the lands of {flat(mi.table(LORDS, c))}")
            a("-" * 76)
            if k & 1 == 0:
                a(f"Quest: go to {target} (place {2 + 21 * (3 - c)}, continent {3 - c}).")
                a("The visit completes it (OU's landmark table, below).")
            else:
                lv = 2 * c + 3
                a(f"Quest: kill a {target} (monster {30 + 5 * c}), the fifth of the five kinds")
                a(f"on dungeon levels {lv}-{lv + 1}: killing one there completes it (DN $9808).")
            a("  S:")
            a(qtext)
            a("  On return, after \"Thou hast completed thy quest!\":")
            if k & 1 == 0:
                a("      (the strength reward above)")
            else:
                g = gems[c]
                a(say(ca.inline(0x98D0), ca.inline(g), indent="      "))
                if c == 3:
                    a("      (and the storerooms open for nine G(et)s: $A17E = 9, CA $9A8B)")
            a("")
    return out, princess


def princess_section(m, names, princess):
    ca = m["CA"]
    out = []
    a = out.append
    a(section("THE PRINCESSES (castles, CA)"))
    a("""Each castle holds a princess (person slot 1; she starts more than 4 columns
from the west edge in both castle layouts).  She only follows the player once
the guards are roused ($9B37); leaving by the west edge with her within 4
columns of it ($8DDE) saves her.  She is named by the castle's k ($A1A4):
""")
    for c in range(4):
        for n in range(2):
            k = n + 2 * c
            k = k if k & 1 else 6 - k
            a(f"    {princess[k]:10s} {names[21 * c + n]}")
    a("")
    a(say(ca.inline(0x8DEB), "<her name>", ca.inline(0x8E16)))
    a("\n  (each of the three at most 9999, CA $A147)  Then, if the player has destroyed")
    a("  20 enemy vessels and has 7000 experience, counted after her gift ($8E8C):")
    a(say(ca.inline(0x8EA2)))
    a("  -- and the time machine appears ($822A = 1).\n")
    return out


def castle_people(m):
    ca = m["CA"]
    ca.expect(0x9D4C, "207016 c928 b034")       # sings: 40 in 256
    ca.expect(0x90D7, "a54c c904 d031")         # a key from the jester
    out = []
    a = out.append
    a(section("THE JESTER, THE GUARDS, THE DOORS (castles, CA)"))
    a("Gwino the jester, each turn (while the guards are calm), when his step is")
    a("blocked by something, 40 times in 256:")
    a(say(ca.inline(0x9D59)))
    a("When the player is in his way he takes one of every weapon the player holds")
    a("but the one in hand ($9D8C), and, if the roll goes his way, says:")
    a(say(ca.inline(0x9DB9)))
    a("Killed, he leaves one of the castle's two keys (50:50, $90DD):")
    a(say(ca.inline(0x90EC)))
    a("Unlocking a cell door (tiles $6A, $6B: key 1 or 2; CA $9A91):")
    a(say(ca.inline(0x9ABD), "a", ca.inline(0x9AEC)))
    a(say(ca.inline(0x9ABD), ca.inline(0x9AD5), ca.inline(0x9AEC)))
    a(say(ca.inline(0x9B11)))
    a("Guards, once roused: each one next to the player attacks, every turn ($9C66):")
    a(say(ca.inline(0x9C6C), ca.inline(0x9CB4)))
    a(say(ca.inline(0x9CD9), "<n>", ca.inline(0x9CEE)))
    a("Stealing (tiles $65/$67/$69, the storerooms; $9498):")
    a(say(ca.inline(0x94D8)))
    a(say(ca.inline(0x94FB), "<what>"))
    a("Get in a storeroom without the king's leave (the white gem's king, $9426):")
    a(say(ca.inline(0x942B)))
    a("")
    return out


# ---------------------------------------------------------------- towns

def towns(m, names):
    tw, tc = m["TW"], m["TC"]
    tw.expect(0x93FE, "bda6ad 854c")            # counter tile -> shop type
    tw.expect(0x94AF, "bdc6ad 8dc094 bdc7ad 8dc194 a200")
    tw.expect(0x8CC6, "#17:5d7c2768fead1352")
    shop_of_tile = {0x64 + i: tw.b(0xADA6 + i) for i in range(9)}
    assert sorted(set(shop_of_tile.values())) == list(range(6)), shop_of_tile
    # the six name tables: 8 names each, one after the other, $A907 to $AD24
    ptrs = [tw.w(0xADC6 + 2 * t) for t in range(6)]
    order = sorted(range(6), key=lambda t: ptrs[t])
    shop_names = {}
    for t in range(6):
        shop_names[t] = [flat(tw.table(ptrs[t], i)) for i in range(8)]
    for t, nxt in zip(order, order[1:] + [None]):
        o = ptrs[t]
        for _ in range(8):
            while not tw.b(o) & 0x80:
                o += 2 if tw.b(o) == 0x7F else 1
            o += 1
        assert o == (ptrs[nxt] if nxt is not None else 0xAD24), (t, hex(o))
    # which shops each town layout has: its counter tiles
    tcp = [tc.w(0x4000 + 2 * i) for i in range(10)]
    unused = []
    out = []
    a = out.append
    a(section("THE TOWNS (overlay TW)"))
    a("""Every continent has eight towns; town n of each continent (in the order of
MI's place list) shares one layout, so the same shops stand in four towns.
Shop names (TW $A907-$AD23, by type $ADC6, by layout), where a counter of the
type is in the layout:
""")
    for n in range(8):
        towns_ = [names[21 * c + 13 + n] for c in range(4)]
        layout = tc.d[tcp[2 + n] - 0x4000:tcp[2 + n] - 0x4000 + 684]
        have = sorted({shop_of_tile[b] for b in layout if b in shop_of_tile})
        a(f"  {', '.join(towns_)}:")
        for t in have:
            a(f"      {SHOP_TYPES[t]:9s}  {shop_names[t][n]}")
        unused += [(t, shop_names[t][n]) for t in range(6) if t not in have]
    a("Names in the tables whose layout has no counter of that kind (never shown):")
    for t, name in sorted(unused):
        a(f"      {SHOP_TYPES[t]:9s}  {name}")
    a("")
    a("Transact (\"T\") away from a counter / once the guards are roused:")
    a(say(tw.inline(0x9406)))
    a(say(tw.inline(0x93CE)))
    a("At a counter:  \"" + plain(tw.inline(0x9426)) + "\"  (B or S)")
    a("  after a purchase (TW $A1A7) / a sale ($A1B6) / too dear ($A1C5):")
    a(say(tw.inline(0xA1AA)))
    a(say(tw.inline(0xA1B9)))
    a(say(tw.inline(0xA1C8)))
    a("")
    a("Sell, by shop ($ADDE):")
    sell = [tw.w(0xADDE + 2 * t) for t in range(6)]
    assert sell[1] == 0xA0C8 and sell[3] == 0xA11D and sell[4] == 0xA13E and sell[5] == 0xA0EB, sell
    a("  armour, nothing to sell:")
    a(say(tw.inline(0xA02E), indent="      "))
    a("  weapons, nothing to sell:")
    a(say(tw.inline(0x983F), indent="      "))
    for t in (1, 3, 4, 5):
        a(f"  {SHOP_TYPES[t]}:")
        a(say(tw.inline(sell[t]), indent="      "))
    a("")
    a("Buy food ($959E): X is 5 pence below intelligence 20, 4 below 40, 3 below 60,")
    a("2 below 80, else 1 ($95A0):")
    tw.expect(0x95A0, "ad4782 38 e914 9004 ca d0f8 e8")
    tw.expect(0x95D1, "58")
    a(say(tw.inline(0x95B6)))
    tw.expect(0x9E36, "#24:9851197a80ae28e8")
    a("Transport ($9E23), when none of the four squares around the town (OU $948A)")
    a("is water, grass or forest:")
    a(say(tw.inline(0x9E5C)))
    a("")

    # the tavern
    tw.expect(0x9A1A, "ad4982 c9ff d003 ce4a82")
    tw.expect(0x9A7C, "#24:838ef3b1f1df4d9f")
    tw.expect(0x9AF1, "207016 c94b b001 60")
    tw.expect(0x9B12, "207016 4a 4a 4a 4a 4a 0a aa bdeaad")
    tw.expect(0x8CAB, "ad2c82 f00b a205 bd5ead 9d58ad")
    rumours = [tw.w(0xADEA + 2 * i) for i in range(8)]
    a(section("THE TAVERN (TW, a pub's counter)"))
    a("""B(uy) at a pub's counter.  With no pence at all:""")
    a(say(tw.inline(0x99C9)))
    a("Else one pence goes, and:")
    a(say(tw.inline(0x9A24)))
    a("""
Then, once the drinks this visit reach stamina / 4, with the wench next to
the player (slot 1 of the town's people; two of the eight layouts have none):""")
    a(say(tw.inline(0x9A94)))
    a("""  (half the pence gone, wisdom -1, not below 5)

Otherwise, 181 times in 256 the keeper goes on, with one of eight rumours
picked at random (1 in 8 each, TW $9B12, table $ADEA):""")
    a(say(tw.inline(0x9AF9)))
    a("")
    for i, at in enumerate(rumours):
        a(f"  rumour {i + 1} (${at:04X}):")
        if at == 0x9B8C:
            tw.expect(0x9B9F, "a205 202d84 39ad a92e 4cd783")
            for who, word in (("male", tw.table(0xAD39, 5)),
                              ("female", tw.table(0xAD5E, 0))):
                a(f"    to a {who} player:")
                a(say(Screen(1).put(tw.inline(at)).put(word).put(".").lines[0].strip(),
                      col=0, indent="      "))
            continue
        tw.expect(at, "208e84")
        lines = [tw.inline(at)]
        if at == 0x9CC3:                       # goes on, after a key, with the quest
            tw.expect(0x9D46, "20e185 205aa8 a908 8533 208e84")
            lines.append(None)
            lines.append(tw.inline(0x9D50))
        s = Screen(1)
        for t in lines:
            if t is None:
                a(s.text("      "))
                a("      [a key; the window clears]")
                s = Screen(0)
            else:
                s.put(t)
        a(s.text("      "))
    a("")

    # Iolo
    tw.expect(0xA41F, "207016 c928 b030")
    a(section("IOLO THE BARD AND THE GUARDS (towns, TW)"))
    a("Iolo (person slot 0 of a town, $A40C), when his step is blocked, 40 in 256:")
    a(say(tw.inline(0xA42D)))
    a("When the player is in his way he takes one of every weapon the player holds")
    a("but the one in hand ($A45B), and sometimes says so:")
    a(say(tw.inline(0xA489)))
    a("Guards, once roused (an attack that hit, a theft caught): each one next to the")
    a("player attacks, every turn ($A347):")
    a(say(tw.inline(0xA34E), tw.inline(0xA388)))
    a(say(tw.inline(0xA3AC), "<n>", tw.inline(0xA3C1)))
    a("Stealing ($92D6):")
    a(say(tw.inline(0x92EF)))
    a(say(tw.inline(0x9312), "<what>"))
    a("")
    return out


# ---------------------------------------------------------------- outdoors

def landmarks(m, names):
    ou, mi = m["OU"], m["MI"]
    ou.expect(0x9464, "#17:dbc4ddb4183aa4a7")
    ou.expect(0x94C4, "ae41a1 202d84 ec9e")
    ou.expect(0x94D2, "ae41a1 bc29a1")
    ou.expect(0x9503, "ae41a1 bd21a1 d05d e004")
    where = [ou.b(0xA119 + i) for i in range(8)]
    stat = [ou.b(0xA121 + i) for i in range(8)]
    king = [ou.b(0xA129 + i) for i in range(8)]
    out = []
    a = out.append
    a(section("THE LANDMARKS (outdoors, OU: Enter at a sign post, grave, tower...)"))
    a("""Entering one of these eight places shows its text (table $9EEC); the first
visit raises an attribute ($A121) unless this was also the last landmark
entered ($8263), and it completes the quest of the king who sent the player
there ($A129).
""")
    quests = {}
    for i in range(8):
        if king[i] != 0xFF:
            k = king[i]
            assert k % 2 == 0, k
            c = (6 - k) // 2                   # the castle on continent c with n = 0
            assert where[i] == 2 + 21 * (3 - c), (i, where[i], k)
            quests[k] = i
    assert sorted(quests) == [0, 2, 4, 6], quests
    castle_of = {k: names[21 * ((6 - k) // 2)] for k in quests}
    for i in range(8):
        p = where[i]
        gain = ("a weapon (the first the player has none of, $950B)" if stat[i] == 0 and i == 4
                else "nothing" if stat[i] == 0
                else plain(mi.table(ATTRIBUTES, stat[i])).lower())
        a("-" * 76)
        a(f"{names[p]}  (place {p}, continent {continent_of(p)})")
        a(f"  raises: {gain}" + (f"; ends the quest of {castle_of[king[i]]}" if king[i] != 0xFF else ""))
        a("-" * 76)
        a(say(ou.table(0x9EEC, i)))
        a("")
    a("With a quest open for this place ($94E6):")
    a(say(ou.inline(0x94E6)))
    a("")
    return out


def time_machine(m):
    ou, tm = m["OU"], m["TM"]
    ou.expect(0x90DB, "#20:84289f68c3eebff9")
    out = []
    a = out.append
    a(section("THE TIME MACHINE (OU boarding it, TM the journey and Mondain)"))
    a("Board (\"B\") the time machine without all four gems (OU $90F3):")
    a(say(ou.inline(0x9101)))
    a("  with none of them:")
    a(say(ou.inline(0x9174), indent="      "))
    a("  with some (each gem drawn in its hole):")
    a(say(ou.inline(0x91FB), indent="      "))
    a("\nWith all four, TM runs: the craft (TM $8E5A), one screen after another:")
    for site in (0x8E5D, 0x8F8F, 0x9094, 0x90FB):
        a(say(tm.inline(site)))
        a("      [a key]")
    a("""
Face to face with Mondain.  What the commands say there (TM's command table
$920D: Get $9842, Inform $9918, Quit $99AB, Steal $99C9, Transact $99F6):""")
    tm.expect(0x988C, "#16:2cc8c156e0241faf")
    a("  Get, not next to the gem / next to it (which costs 3/4 of the player's hit")
    a("  points, $988C):")
    a(say(tm.inline(0x986A), indent="      "))
    a(say(tm.inline(0x98C6), "<n>", tm.inline(0x98D6), indent="      "))
    a(say(tm.inline(0x98F4), indent="      "))
    a("  Inform, before / after the gem is gone:")
    a(say(tm.inline(0x9977), indent="      "))
    a(say(tm.inline(0x991D), indent="      "))
    a("  Quit, after the command's name:")
    a(say(tm.inline(0x99AB), indent="      "))
    a("  Steal:")
    a(say(tm.inline(0x99C9), indent="      "))
    a("  Transact:")
    a(say(tm.inline(0x99F6), indent="      "))
    a("  Cast Kill (\"INTERFICIO-NUNC!\") at him ($97E1):")
    a(say(tm.inline(0x97E9), indent="      "))
    a("\nMondain's turn ($9CE9):")
    a(say(tm.inline(0x9BC0)))
    a(say(tm.inline(0x9CE6), tm.inline(0x9D21)))
    for spell in (0x9D85, 0x9DCB, 0x9E3D):
        a(say(tm.inline(0x9D57), tm.inline(spell)))
    a(say(tm.inline(0x9DEE)))
    a(say(tm.inline(0x9E85), "<n>", tm.inline(0x9E97)))
    a("\nHis hit points gone ($936B):")
    tm.expect(0x9380, "ad1799 d012")
    tm.expect(0x990E, "ad6782 1003 4c9793")
    a(say(tm.inline(0x936B)))
    a("  if the gem has not been destroyed yet:")
    a(say(tm.inline(0x9385), indent="      "))
    a("  with both done, in either order ($9383, $9911):")
    a(say(tm.inline(0x9397)))
    a("      [and the screen, scrolling in from the right ($948A, TM $94C3):]")
    tm.expect(0x948A, "a21b bdc294")
    a("      " + "".join(chr(tm.b(0x94C3 + i) & 0x7F) for i in range(0x1B)).strip())
    a("\nThe player's hit points gone ($9ED1):")
    a(say(tm.inline(0x9ED1)))
    a(say(tm.inline(0x9EEF)))
    a("")
    return out


def space(m):
    sp = m["SP"]
    out = []
    a = out.append
    a(section("SPACE (overlay SP): the station and the rank of Space Ace"))
    sp.expect(0x8FD9, "ad4a82 c901 d005 ad4982 c9f4 b053")
    sp.expect(0x903A, "adf081 c905 f044 c904 f040")
    sp.expect(0x9AA5, "ad2b82 c914 9022 f023")
    a("Docking at a space station ($8F9C):")
    a(say(sp.inline(0x8F9C)))
    a("  with less than 500 pence:")
    a(say(sp.inline(0x8FE7), indent="      "))
    a("  else, unless the player wears a vacuum suit or a reflect suit:")
    a(say(sp.inline(0x9045), indent="      "))
    a("The 20th enemy vessel destroyed ($9AA5: $822B reaches 20):")
    s = Screen(6).put(sp.inline(0x9ADC))
    s.col(9).put(sp.inline(0x9AF8)).col(10).put(sp.inline(0x9B0D))
    a(s.text())
    a("  every one after it:")
    a(say(sp.inline(0x9AAE), indent="      "))
    a("Out of fuel:")
    a(say(sp.inline(0x8DC5)))
    a("")
    return out


def spells(m):
    ou, dn, mi = m["OU"], m["DN"], m["MI"]
    dn.expect(0x9479, "#20:ea61647d14285018")
    dn.expect(0x94A4, "48 208e84 7e00 68 48 aa ca 202d84 caa8")
    ou.expect(0x9306, "#18:9d196d522c03d48d")
    out = []
    a = out.append
    a(section("WHAT THE PLAYER CALLS OUT: SPELLS"))
    a("In a dungeon (DN $94A4, table $A8CA by spell number):")
    a(f"    {'Prayer':14s} " + flat(dn.inline(0x948A))
      + "   (and then one of the other ten, at random)")
    for s in range(1, 11):
        a(f"    {plain(mi.table(SPELLS, s)):14s} " + plain(dn.table(0xA8CA, s - 1)))
    a("Outdoors (OU $9313): an attack spell other than Kill / Kill:")
    a("    " + flat(ou.table(0x9394, 0)) + "  /  " + flat(ou.table(0x9394, 1)))
    ou.expect(0x93BA, "208e84 7e")
    a("    Prayer: " + flat(ou.inline(0x93BA)))
    a("")
    return out


def section(title):
    return "=" * 76 + "\n" + title + "\n" + "=" * 76 + "\n"


def leftovers(m):
    """Every other inline text of the modules used: the game's messages."""
    out = ["=" * 76, "EVERYTHING ELSE THESE OVERLAYS PRINT (game messages, not speech)",
           "=" * 76, "",
           "Found by scanning each file for JSR $848E / $848A (TM also $A7C8/$A7CE)",
           "with a text after it that decodes; one line each, \" / \" a line break.", ""]
    for name in ("TW", "CA", "OU", "TM", "SP", "DN"):
        mod = m[name]
        found = mod.sites()
        assert mod.used <= set(found), (name, sorted(hex(x) for x in mod.used - set(found)))
        rest = [s for s in found if s not in mod.used]
        out.append(f"{name}: {len(found)} texts, {len(mod.used)} quoted above, {len(rest)} here")
        for s in rest:
            toks, _ = mod.raw_inline(s + 3)
            t = say(toks, indent="").replace("\n", " / ")
            t = " ".join(t.split()) if t.strip() else repr(plain(toks))
            out.append(f"  ${s:04X}  {t}")
        out.append("")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "dialogue", "u1"))
    a = ap.parse_args()
    m = load()
    names = check_mi(m["MI"])
    out = ["Ultima I (C64) -- what is said: kings, princesses, the jester and the bard,",
           "guards, shopkeepers, the tavern, the landmarks, the time machine and Mondain",
           "",
           "How to read this:",
           "  Ultima I has no conversations: nobody can be Talked to.  What people say",
           "  is fixed text in the code of the place (towns TW, castles CA, outdoors OU,",
           "  the time machine TM, space SP, dungeons DN), said when the player does",
           "  something -- Transact with a king or at a shop counter, buy a drink -- or",
           "  when a person acts.  Each section says what brings it on; $xxxx are",
           "  addresses in that overlay (they all run at $8C9E).",
           "  Text is laid out as on the screen, centring included.  <...> marks what",
           "  the game fills in (a name, a number); [ ... ] what happens in between.",
           "  The rules quoted (chances, conditions) are read from the code; where",
           "  something is inferred and not read, it says so.",
           ""]
    body, princess = castles(m, names)
    out += body
    out += princess_section(m, names, princess)
    out += castle_people(m)
    out += towns(m, names)
    out += landmarks(m, names)
    out += time_machine(m)
    out += space(m)
    out += spells(m)
    out += leftovers(m)
    text = "\n".join(out).rstrip() + "\n"
    assert "\x00" not in text
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "u1-dialogue.txt")
    with open(path, "w") as fh:
        fh.write(text)
    print("written", path, f"({text.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
