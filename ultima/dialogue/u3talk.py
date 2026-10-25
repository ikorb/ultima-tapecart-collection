#!/usr/bin/env python3
"""Ultima III (C64): every conversation and fixed text of the game as plain text.

    python -m ultima.dialogue.u3talk [--out build/dialogue/u3]

Reads the original disks (not the cart: the cart's ULT3 is
Ultima III Gold's), through the game's own catalog -- disk A blocks 100-103,
loaded to $B000: 94 entries of 4-char name, start block, block count,
destination page (docs/reversing-notes/u3.md); the ten program files are on disk A,
everything else on disk B.  Writes u3-dialogue.txt.

What was found (V = verified in the code, I = inferred):

Talking.  The command is T(ransact): ULT3 $6676 "Who will Transact-", then
"DIRECT-" ($669C).  (V) $7AD2 looks for a person of the current MON table on
the square in that direction (32 entries: tile +$00, x +$40, y +$60, flags
+$80).  Found:
  - tile byte $4C (Lord British) -> $6740, his fixed lines (below);
  - else index = flags & $0F; 0 prints "GOOD DAY!" ($672D), 1-15 print entry
    <index> of the TLK unit at $9800 ($6720 -> $8740).
Nobody there: if the square holds a counter (map byte $94-$E7: the letter
tiles) and the one beyond it a merchant (map byte $40), ULT3 loads shop
overlay SHP<n> to $9400 and runs it ($66AF-$6705), n = the party's y & 7 --
so which shop a merchant keeps is a property of the row the party stands on.
Flags bits 7-6 are the person's movement ($79F4): 00 stands still, 40
wanders (moves when a random byte is negative), 80 walks toward the party
($7A65), C0 walks toward the party and attacks when it gets there ($78C6 ->
$5249).  (V for the paths; the words are mine.)  A failed theft ($6621) and
the start of a fight in a town ($7DE2) set guards ($48) -- and the latter
Lord British -- to C0.

TLK units ($9800, one block each, TLKA-TLKS: the letter is the map's, ULT3
$5928 patches the same letter into "L MAPx", "L TLKx", "L MONx").  (V,
$8740) Entry n is the text after the n-th $00 byte; each byte & $7F is a
character, $FF a new line, $00 ends it.  Entry 0 is the empty text before
the first $00.  After the last real entry the block holds residue of other
sectors, which is not shown; an entry no person's index points to is listed
apart as "spoken by nobody".
Dungeons MAPM-MAPS use the same TLK unit for "MISTY WRITING:" ($8E5E): on a
square of value 8 of the current level, entry (level + 1), level = $23
(0-7).  (V)  The other square values of a dungeon level ($1000 + 256 *
level, 16 x 16; dispatch $8E1F): 1 the Time Lord's vision (the square is
then cleared), 2 a fountain, 3 a strange wind, 4 a trap, 5 the brand, 6
gremlins.

Fixed texts, all inline strings: JSR $46C3 (SUBS: print the following bytes
in the text window, $FF a new line, $00 ends, then return after them) or
JSR $46FC (the same at the X/Y position in the registers).  They are taken
from ULT3 (Lord British, the words of the O(ther) command -- INSERT,
SEARCH, DIG, BRIBE, PRAY, known by last letter and length, $6192 -- the
dungeon events, the whirlpool), the shop overlays SHP0-SHP7, the shrine
overlay SHNE and the ending END, plus an appendix of every other inline
string in ULT3 (command prompts, combat, Ztats).  In the
overlays only strings reached by a recursive-descent walk from $9400 count;
the rest is residue of other overlays (SHP4 holds the end of SHP3's list,
SHP5 SHP4's).

Not text, though the analysis's memory map calls them "conversation text":
CONA-CONS are the combat maps (ULT3 $7E9C "L CON@" after "CONFLICT!!"), and
FNTN, TIME, BRND and SHRN hold no strings either -- 121 tile bytes and tables
in the CON layout (I: the pictures shown by $CA03 at those events, as SHNE
$9400-$940C loads SHRN and calls it).

Not covered: BOOT's menus and character creation, EXOD's intro, and the
people of Ambrosia (MONZ: all hostile; one has index 5, but no TLK unit is
loaded there, so T would print from whichever TLK came last -- I).

Town names come from the maps' own letter-tile signs (WELCOME TO MOON...);
Britain has no sign and is named by being next to Lord British's castle (I).
"""
import argparse
import os
import textwrap
from collections import Counter, defaultdict

from ultima import pin
from ultima.disks.d64 import D64  # noqa: E402
from ultima.sim.dis6502 import decode  # noqa: E402
from ultima import paths

DISK_A = paths.disk("u3a")
DISK_B = paths.disk("u3b")
CAT_BLOCK, CAT_BLOCKS, ENTRIES = 100, 4, 94
DISK_A_FILES = {"EXOD", "TEXT", "SHPS", "DEMO", "ULT3", "DDAT", "BOOT", "SUBS", "MUSI", "COPY"}

PRINT, PRINT_AT, DOS = 0x46C3, 0x46FC, 0x46C0       # SUBS' inline-string entries
TALK_PRINT = 0x8740                                 # ULT3: print TLK entry A
TILE_NAMES = 0x8796                                 # ULT3: Look's names, entry tile + 1

MOVES = {0x00: "stands still", 0x40: "wanders", 0x80: "walks toward the party",
         0xC0: "hostile: comes for the party and attacks"}

# letter -> (name, evidence): the sign words must be on the map (checked)
PLACES = {
    "A": ("Lord British's castle", ["BRITISH"]),
    "B": ("Exodus's castle (inferred: the four card panels are here; its only signs say DEATH)", ["DEATH"]),
    "C": ("Britain (no sign; the town beside Lord British's castle, inferred)", []),
    "D": ("Moon", ["WELCOME", "MOON"]),
    "E": ("Yew", ["WELCOME", "YEW"]),
    "F": ("Montor East", ["MONTOR", "EAST"]),
    "G": ("Montor West", ["MONTOR", "WEST"]),
    "H": ("Grey", ["WELCOME", "GREY"]),
    "I": ("Dawn", ["DAWN"]),
    "J": ("Devil Guard (signed DEUIL GUARD: there is no V tile)", ["DEUIL", "GUARD"]),
    "K": ("Fawn", ["WELCOME", "FAWN"]),
    "L": ("Death Gulch", ["DEATH", "GULCH"]),
}
SHOPS = {0: "pub", 1: "grocer", 2: "healer", 3: "weapons", 4: "armour",
         5: "guild", 6: "oracle", 7: "stables"}
SHOP_FIRST = {0: "WELCOME TO", 1: "GROCER", 2: "CLERICAL", 3: "WEAPONS",
              4: "ARMOUR", 5: "GUILD", 6: "RADRION", 7: "EQUINE"}
EVENTS = {1: "Time Lord", 2: "fountain", 3: "wind", 4: "trap", 5: "brand",
          6: "gremlins", 8: "writing"}


# ---- the disks ----------------------------------------------------------

class Unit:
    def __init__(self, name, data, addr):
        self.name, self.data, self.addr = name, bytes(data), addr

    def has(self, a):
        return self.addr <= a < self.addr + len(self.data)

    def at(self, a, n=1):
        assert self.has(a) and self.has(a + n - 1), f"{self.name}: ${a:04X} outside the unit"
        o = a - self.addr
        return self.data[o:o + n]

    def expect(self, a, hexbytes, what):
        """A cheap check that the code is the code this script was written
        against (hex, or a Pin's "#n:hash" for a longer run)."""
        want = pin.want(hexbytes)
        assert self.at(a, len(want)) == want, f"{self.name} ${a:04X} is not {what}"


def load_units():
    a, b = D64(DISK_A), D64(DISK_B)

    def blocks(disk, start, count):
        return b"".join(disk.sector(*D64.from_linear(start + i)) for i in range(count))

    cat = blocks(a, CAT_BLOCK, CAT_BLOCKS)
    units = {}
    for i in range(ENTRIES):
        e = cat[8 * i:8 * i + 8]
        name = bytes(c & 0x7F for c in e[:4]).decode("latin1").strip()
        if e[6]:
            units[name] = Unit(name, blocks(a if name in DISK_A_FILES else b, e[4] | e[5] << 8, e[6]),
                               e[7] << 8)
    for n, addr in [("ULT3", 0x5000), ("SUBS", 0x4100), ("TLKA", 0x9800), ("MONA", 0x4F00),
                    ("MAPA", 0x1000), ("SHP0", 0x9400), ("SHNE", 0x9400), ("END", 0x9400)]:
        assert units[n].addr == addr, f"the catalog does not load {n} at ${addr:04X}"
    assert all(f"TLK{c}" in units for c in "ABCDEFGHIJKLMNOPQRS")
    return units


# ---- text ---------------------------------------------------------------

def char(c):
    c &= 0x7F
    return chr(c) if 0x20 <= c < 0x7F else "{%02X}" % c


def lines(bs):
    """Bytes up to a $00 -> the lines the game prints ($FF a new line)."""
    out = [""]
    for c in bs:
        if c == 0xFF:
            out.append("")
        else:
            out[-1] += char(c)
    return out


def printable(bs):
    return all(c == 0xFF or 0xA0 <= c <= 0xFE for c in bs)


def quoted(ls, indent):
    """'"line', ' line"' in the style of the U6 extract; empty edge lines dropped."""
    while ls and not ls[0].strip():
        ls = ls[1:]
    while ls and not ls[-1].strip():
        ls = ls[:-1]
    if not ls:
        return [indent + '""']
    out = [indent + '"' + ls[0]] + [indent + " " + s for s in ls[1:]]
    out[-1] += '"'
    return out


def tlk_entries(unit):
    """[(index, bytes)] of the TLK unit: entry n follows the n-th $00."""
    parts = unit.data.split(b"\0")
    return list(enumerate(parts))[1:-1]     # the last part is unterminated residue


def inline(unit, jsr):
    """The string after the JSR at `jsr`, or None if it is not one."""
    o = jsr - unit.addr + 3
    end = unit.data.find(b"\0", o)
    if end < 0 or end - o > 400:
        return None
    s = unit.data[o:end]
    if not all(c >= 0xA0 or c in (0x04, 0x1C, 0x1D, 0x1E, 0x1F, 0x8D, 0x84) for c in s):
        return None
    return s


def scan(unit):
    """Every JSR to an inline-string printer whose bytes decode as text."""
    out = {}
    d = unit.data
    for i in range(len(d) - 3):
        if d[i] == 0x20 and d[i + 2] == 0x46 and d[i + 1] in (PRINT & 0xFF, PRINT_AT & 0xFF):
            s = inline(unit, unit.addr + i)
            if s is not None:
                out[unit.addr + i] = s
    return out


def walk(unit, entries):
    """Recursive descent from `entries`; returns the addresses of the
    inline-print JSRs reached (their strings skipped, as the 6502 does)."""
    seen, found, todo = set(), set(), list(entries)
    while todo:
        pc = todo.pop()
        while unit.has(pc) and pc not in seen:
            seen.add(pc)
            ins = decode(unit.data, unit.addr, pc)
            if ins is None:
                break
            mn, mode, n, arg = ins
            nxt = pc + n
            if mn == "jsr" and arg in (PRINT, PRINT_AT, DOS):
                s = inline(unit, pc)
                assert s is not None, f"{unit.name} ${pc:04X}: an inline string that is not one"
                if arg != DOS:
                    found.add(pc)
                pc = pc + 3 + len(s) + 1
                continue
            if mode == "rel":
                todo.append((nxt + (arg - 256 if arg > 127 else arg)) & 0xFFFF)
            if mn == "jsr" and unit.has(arg):
                todo.append(arg)
            if mn == "jmp" and mode == "abs":
                pc = arg
                continue
            if mn in ("rts", "rti", "brk", "jmp"):
                break
            pc = nxt
    return found


# ---- the game -----------------------------------------------------------

def checks(units):
    u = units["ULT3"]
    u.expect(TALK_PRINT, "a8 a9 00 85 7e a9 98 85 7f", "the TLK print (Y = entry, from $9800)")
    u.expect(0x8759, "a1 7e f0 06", "the entry search (counting $00s)")
    u.expect(0x876E, "a1 7e f0 0e c9 ff f0 0b 29 7f", "the TLK print loop ($00 ends, $FF new line)")
    u.expect(0x6716, "bd 00 4f c9 4c d0 03 4c 40 67", "Talk's Lord British test (tile $4C)")
    u.expect(0x6720, "bd 80 4f 29 0f f0 06 20 40 87", "Talk's index (flags & $0F)")
    u.expect(0x66CE, "20 08 47 c9 40", "the merchant test (map byte $40)")
    u.expect(0x66B2, "c9 94 b0 03 4c 1e 52 c9 e8", "the counter test ($94-$E7)")
    u.expect(0x66D8, "a5 f8 29 07 18 69 b0 8d f5 66", "the shop number (party y & 7)")
    u.expect(0x66EF, "04 cc a0 d3 c8 d0", "\"L SHP@\"")
    u.expect(0x5928, "18 a5 7b 69 c1 8d 3f 59 8d 47 59", "the map letter patched into L MAPx / L TLKx")
    u.expect(0x8E71, "a5 23 18 69 01 20 40 87", "the misty writing (entry = level + 1)")
    u.expect(0x8E4D, "c9 08", "the misty writing's square value")
    u.expect(0x91DF, "#16:9880d260ea3a2008",
             "the dungeon square lookup ($1000 + level * 256 + y * 16 + x)")
    u.expect(0x598B, "c9 f8", "the shrine tile ($F8)")
    u.expect(0x7AD2, "a9 20 85 50", "the person search (32 entries)")
    units["SHNE"].expect(0x9432, "a5 f7 29 03 f0 26 c9 01 f0 41 c9 02 f0 5c",
                         "the shrine kind (party x & 3)")
    u.expect(0x8FFA, "#20:66be0b6cbcc67345",
             "the fountain kind (party x & 3)")
    u.expect(0x6198, "#66:51399dd19fdd7d57",
             "Other's words (last letter, 8 - length)")
    u.expect(0x62BD, "a5 09 c9 7c", "SEARCH's shrine test")
    u.expect(0x63AF, "#21:de83b42a59c432e8",
             "PRAY's place test")
    u.expect(0x58F9, "a9 1e 8d bc 62", "the card order's start")
    u.expect(0x6305, "a5 f7 c9 21", "DIG's first place")
    units["SUBS"].expect(PRINT, "4c 3b 47", "SUBS' inline print")
    units["SUBS"].expect(PRINT_AT, "4c 18 4c", "SUBS' inline print at X/Y")


def tile_names(u3):
    parts = u3.at(TILE_NAMES, 1200).split(b"\0")
    names = ["".join(char(c) for c in p) for p in parts[1:65]]
    assert names[0] == "WATER" and names[18] == "GUARD" and names[19] == "LORD BRITISH" \
        and names[16] == "MERCHANT" and names[62] == "SHRINE", names
    return names


def signs(names, m):
    """Words spelled in letter tiles (38-57) on a 64 x 64 map."""
    words = []
    for y in range(64):
        run = ""
        for x in range(65):
            t = m[y * 64 + x] >> 2 if x < 64 else 0
            if 38 <= t <= 57:
                run += names[t]
            else:
                if len(run) >= 2:
                    words.append(run)
                run = ""
    return words


def entrances(u3):
    xs, ys = u3.at(0x77E5, 19), u3.at(0x77F8, 19)
    return {chr(65 + i): (xs[i], ys[i]) for i in range(19)}


def shops_of(m):
    """{shop: [(merchant x, y, party x, y)]}: every merchant square ($40)
    with a counter between it and a square two away that the party can
    stand on (not a merchant, wall $8C, void $90 or counter)."""
    out = defaultdict(list)
    for y in range(64):
        for x in range(64):
            if m[y * 64 + x] != 0x40:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                cx, cy, px, py = x - dx, y - dy, x - 2 * dx, y - 2 * dy
                if not (0 <= px < 64 and 0 <= py < 64):
                    continue
                stand = m[py * 64 + px]
                if 0x94 <= m[cy * 64 + cx] < 0xE8 and stand not in (0x40, 0x8C, 0x90) \
                        and not 0x94 <= stand < 0xE8:
                    out[py & 7].append((x, y, px, py))
    return out


def person(names, mon, i):
    t, x, y, f = mon[i], mon[0x40 + i], mon[0x60 + i], mon[0x80 + i]
    return f"#{i:02d} {tile_name(names, t):12s} x {x:2d} y {y:2d}  {MOVES[f & 0xC0]}"


def tile_name(names, t):
    """Look's name; tile 63 is past the tile names (Look would say RANGER)."""
    t = (t >> 2) & 63
    return names[t] if t < 63 else "tile 63"


def towns(units, names, out):
    u3 = units["ULT3"]
    places = entrances(u3)
    total = 0
    for letter in "ABCDEFGHIJKL":
        name, evidence = PLACES[letter]
        m = units["MAP" + letter].data[:4096]
        mon = units["MON" + letter].data
        tlk = units["TLK" + letter]
        words = signs(names, m)
        for w in evidence:
            assert w in words, f"MAP{letter}: no sign {w} (signs: {words})"
        x, y = places[letter]
        entries = dict(tlk_entries(tlk))
        people = [i for i in range(32) if mon[i]]
        said = defaultdict(list)
        for i in people:
            if mon[i] != 0x4C and mon[0x80 + i] & 0x0F:
                said[mon[0x80 + i] & 0x0F].append(i)
        for k in said:
            assert k in entries and printable(entries[k]) and entries[k].strip(b"\xff"), \
                f"TLK{letter} entry {k} is spoken but is not text"
        out += ["=" * 76, f"MAP{letter}  {name}",
                f"  on Sosaria at x {x}, y {y}; text TLK{letter}; people MON{letter} "
                f"({len(people)}); signs: {', '.join(words) or 'none'}", "=" * 76, ""]
        for k in sorted(said):
            out.append(f"TLK{letter} entry {k}, said by")
            out += ["    " + person(names, mon, i) for i in said[k]]
            out += quoted(lines(entries[k]), "        ")
            out.append("")
            total += 1
        lb = [i for i in people if mon[i] == 0x4C]
        if lb:
            out.append("Lord British (his own lines, see LORD BRITISH below)")
            out += ["    " + person(names, mon, i) for i in lb]
            out.append("")
        quiet = [i for i in people if mon[i] != 0x4C and not mon[0x80 + i] & 0x0F]
        if quiet:
            out.append('"GOOD DAY!" (index 0)')
            kinds = Counter(tile_name(names, mon[i]) for i in quiet)
            out.append("    " + ", ".join(f"{k} x{n}" if n > 1 else k for k, n in sorted(kinds.items())))
            out.append("")
        shops = shops_of(m)
        if shops:
            out.append("Shops (T across a counter to a merchant; the overlay is SHP<party y & 7>)")
            for s in sorted(shops):
                where = "; ".join(f"merchant x {mx} y {my} from x {px} y {py}" for mx, my, px, py in shops[s])
                out.append(f"    SHP{s} {SHOPS[s]:8s} {where}")
            out.append("")
        spare = [(k, v) for k, v in entries.items() if k not in said and printable(v) and v.strip(b"\xff")]
        if spare:
            out.append(f"In TLK{letter} but spoken by nobody (no person's index; likely left over):")
            for k, v in spare:
                out.append(f"    entry {k}: " + " / ".join(s for s in lines(v) if s))
            out.append("")
    return total


def dungeons(units, out):
    u3 = units["ULT3"]
    places = entrances(u3)
    out += ["=" * 76, "DUNGEONS -- the misty writings", "=" * 76, "",
            "On a square of value 8, \"MISTY WRITING:\" and the TLK entry of the level",
            "(entry 1 on level 1 ...).  'squares' counts the level's writing squares;",
            "other events on the level are listed by kind and count.", ""]
    n = 0
    for letter in "MNOPQRS":
        x, y = places[letter]
        tlk = dict(tlk_entries(units["TLK" + letter]))
        m = units["MAP" + letter].data
        out.append(f"MAP{letter}  the dungeon at x {x}, y {y} on Sosaria (text TLK{letter})")
        for level in range(8):
            sq = Counter(m[level * 256:(level + 1) * 256])
            text = tlk[level + 1]
            assert printable(text) and text.strip(b"\xff"), f"TLK{letter} entry {level + 1} is not text"
            other = ", ".join(f"{EVENTS[v]} {sq[v]}" for v in (1, 2, 3, 4, 5, 6) if sq[v])
            w = " / ".join(s for s in lines(text) if s)
            note = f"{sq[8]} square{'s' if sq[8] != 1 else ''}" if sq[8] else "no square: never shown"
            out.append(f"    level {level + 1}: {w:34s} ({note}{'; ' + other if other else ''})")
            n += 1
        out.append("")
    return n


def strings_of(unit, jsrs):
    return [(a, inline(unit, a)) for a in sorted(jsrs)]


def overlay(units, name, title, out):
    u = units[name]
    found = scan(u)
    reached = walk(u, [u.addr])
    assert reached and reached <= set(found), f"{name}: walk and scan disagree"
    out += [f"{name}  {title}  ($9400)"]
    out += ["  " + x for x in NOTES.get(name, [])]
    for a, s in strings_of(u, reached):
        if any(x.strip() for x in lines(s)):
            out += quoted(lines(s), "    ")
    left = sorted(set(found) - reached)
    if left:
        out.append(f"    [not reached from $9400, residue: {len(left)} strings at "
                   + ", ".join(f"${a:04X}" for a in left) + "]")
    out.append("")
    return len(reached)


def ult3_text(u3, a):
    s = inline(u3, a)
    assert s is not None, f"ULT3 ${a:04X}: no string"
    return s


FIXED = [
    ("T(RANSACT), THE TALK COMMAND (ULT3 $6676)", [
        (0x6676, "the command"),
        (0x669C, "then a direction"),
        (0x672D, "a person whose index is 0"),
    ]),
    ("LORD BRITISH (ULT3 $6740; the record fields are inferred)", [
        (0x6744, "on T to him (tile $4C), for the character who transacts"),
        (0x67E8, "if its max hit points (+$1C, hundreds) exceed its experience (+$1E, hundreds)"),
        (0x6770, "else at 2500 max hit points or more"),
        (0x678C, "else from 500 up without the Mark of Kings (+$0E bit 7)"),
        (0x67C0, "else: max hit points + 100, and a sound"),
    ]),
    ("O(THER COMMAND) (ULT3 $612E): a word of up to 8 letters, known by its last\n"
     "letter and its length only ($6192), so any word of that shape works", [
        (0x612E, "the command"),
        (0x615E, "the word"),
        (0x61EE, "INSERT (6 letters, T): a direction; the square must be a panel, map byte $7C "
                 "(MAPB x 30-33, y 11)"),
        (0x6203, "  then which card: Love, Sol, Moons, Death go to x 30, 31, 32, 33 and in that "
                 "order ($62BC from $1E); a card not held: \"NONE LEFT!\"; a wrong one sets "
                 "the character's hit points (+$1A) to 0 and deals 255 damage; the fourth loads the ending (R END)"),
        (0x62DB, "SEARCH (6, H) on a shrine square ($09 = $7C, the tile under the party / 2): "
                 "the card of bit (x & 3) of +$0E"),
        (0x633C, "DIG (3, G), outdoors, at x 33 y 3 (+$3F) or x 19 y 44 (+$2F); "
                 "elsewhere \"NOT HERE!\""),
        (0x634C, "BRIBE (5, E): a direction, a person there"),
        (0x636A, "  without 100 gold; with it 100 gold goes, and a guard (tile $48) leaves "
                 "(anyone else: \"NO EFFECT!\")"),
        (0x63C6, "PRAY (4, Y) with $62 = 2 (in a town, I) at x 48 y 48, when $63 (the party's x on Sosaria "
                 "before entering, $58AA) is ULT3 $77E9 = 34: Yew's Circle of Light"),
        (0x61DA, "any other word (EVOCARE, 7 letters, E, goes to $6982 instead: on the surface "
                 "at x 10, y 59 or 56 with the Mark of Snake, +$0E bit 6, the party crosses "
                 "the Silver Snake -- no text)"),
    ]),
    ("THE DUNGEONS' EVENTS (ULT3 $8E1F: the value of the square)", [
        (0x8E5E, "value 8, then the level's TLK entry (see DUNGEONS)"),
        (0x8EA0, "value 1, the Time Lord (the square is cleared; TIME is loaded and shown)"),
        (0x8FA4, "value 2, a fountain (FNTN is loaded and shown)"),
        (0x8FE7, "  no such player"),
        (0x900E, "  party x & 3 = 3: cures poison"),
        (0x9041, "  x & 3 = 0: poisons"),
        (0x9079, "  x & 3 = 1: hit points to the maximum"),
        (0x9092, "  x & 3 = 2: damage"),
        (0x90C6, "value 3"),
        (0x8F45, "value 4, a trap"),
        (0x8F67, "  evaded"),
        (0x9148, "value 5, the brand (BRND is loaded and shown)"),
        (0x91BD, "  a mark: bit 4 + (party x & 3) of +$0E, and damage"),
        (0x910D, "value 6"),
    ]),
    ("SHRINES (ULT3 $5992, E(nter) on a shrine tile $F8; then SHNE, below)", [
        (0x5874, "the command"),
        (0x5992, "on a shrine"),
    ]),
    ("THE WHIRLPOOL AND AMBROSIA (ULT3)", [
        (0x7572, "the whirlpool takes the ship"),
        (0x7652, "then"),
        (0x76BB, "on Ambrosia"),
    ]),
]

# under each overlay's title: what picks among its strings (V: read in the code)
NOTES = {
    "SHP0": ["You pay what you type (two digits, $50): under 7 \"LEAVE MY SHOP!\"; 7-9",
             "\"Thank you,\"; then one saying each for 10-19, 20-29 ... 90-99 (SHP0 $94AA:",
             "CMP #$10, #$20 ... #$90), in the order below."],
    "SHP6": ["You offer a digit d (hundreds of gold, $50); verse d + 1 of the rhyme",
             "below (SHP6 $9471: CMP #$01 ... #$09), so 0 gives the first."],
    "SHP7": ["Between the strings: $61 printed before \"-Horses cost,\" and twice it",
             "before \"00gp.\" (SHP7 $9400-$9438)."],
    "SHNE": ["The kind is the party's x & 3: 0 STRENGTH, 1 DEXTERITY, 2 INTELLIGENCE,",
             "3 WISDOM (SHNE $9432); see the shrine tiles on Ambrosia above."],
}


def fixed(units, out):
    u3 = units["ULT3"]
    n = 0
    for title, items in FIXED:
        out += ["=" * 76, title, "=" * 76, ""]
        for a, why in items:
            if why:
                out += textwrap.wrap(why, 76, initial_indent=f"  ${a:04X}  ",
                                     subsequent_indent=" " * 9 + " " * (len(why) - len(why.lstrip())))
            out += quoted(lines(ult3_text(u3, a)), "        ")
            n += 1
        out.append("")
    return n


def shrines_on_ambrosia(units, out):
    m = units["MAPZ"].data[:4096]
    kinds = ["STRENGTH", "DEXTERITY", "INTELLIGENCE", "WISDOM"]     # SHNE $9432
    where = [(i % 64, i // 64) for i, b in enumerate(m) if b == 0xF8]
    assert where, "no shrine tile on Ambrosia"
    out.append("Shrine tiles on Ambrosia (MAPZ) and their kind (SHNE: party x & 3):")
    for x, y in where:
        out.append(f"    x {x:2d} y {y:2d}  {kinds[x & 3]}")
    out.append("")


def appendix(units, shown, out):
    u3 = units["ULT3"]
    out += ["=" * 76, "EVERY OTHER MESSAGE IN ULT3 (inline strings, by address; not all are", "speech)",
            "=" * 76, ""]
    n = 0
    for a, s in sorted(scan(u3).items()):
        if a in shown or not any(0xC1 <= (c | 0x80) <= 0xFA for c in s):
            continue
        out.append(f"  ${a:04X}  " + " / ".join(x for x in lines(s) if x))
        n += 1
    out.append("")
    return n


HEADER = """\
Ultima III: Exodus (C64) -- what the people say, and the game's other fixed
texts, from the original disks.  Made by ultima/dialogue/u3talk.py.

How to read this
  Text is as the game stores it: upper case for speech, a few lines in
  mixed case.  A quoted block is one message; its lines are the screen's
  (at most 16 characters a line).
  #nn          the person's place in the map's MON table (0-31)
  GUARD ...    what Look calls the person's tile
  x, y         where the person starts on the 64 x 64 map
  stands still / wanders / walks toward the party / hostile: the movement
               bits of the person's flags; a hostile person attacks
  TLKx entry n the person's index (flags & $0F) picks entry n of the
               place's TLK unit; 0 is "GOOD DAY!"
  Shops are not people's lines: T toward a merchant across a counter runs
  shop overlay SHP<the party's row & 7>; their texts are under SHOPS.
  In the shops' and the ending's texts, numbers, names and the player's
  answers are printed between the strings; a string ending without a new
  line continues on the same line (a lone letter or digit on a string's
  first line -- Y, N, 0-4, T, K ... -- is the echo of the key pressed).
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "dialogue", "u3"))
    a = ap.parse_args()
    units = load_units()
    checks(units)
    names = tile_names(units["ULT3"])
    out = HEADER.splitlines() + [""]

    out += ["#" * 76, "TOWNS AND CASTLES", "#" * 76, ""]
    n_town = towns(units, names, out)
    out += ["#" * 76, "DUNGEONS", "#" * 76, ""]
    n_dng = dungeons(units, out)

    out += ["#" * 76, "FIXED TEXTS", "#" * 76, ""]
    n_fixed = fixed(units, out)
    shrines_on_ambrosia(units, out)

    out += ["=" * 76, "SHOPS, THE SHRINE, THE END (overlays at $9400)", "=" * 76, ""]
    n_ov = 0
    for s in range(8):
        name = f"SHP{s}"
        first = inline(units[name], min(walk(units[name], [0x9400])))
        assert SHOP_FIRST[s] in "".join(lines(first)).upper(), f"{name} is not the {SHOPS[s]}"
        n_ov += overlay(units, name, f"the {SHOPS[s]}", out)
    n_ov += overlay(units, "SHNE", "the shrine (loads SHRN, the picture)", out)
    n_ov += overlay(units, "END", "the ending", out)

    shown = {x for _, items in FIXED for x, _ in items}
    n_rest = appendix(units, shown, out)

    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "u3-dialogue.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"{n_town} town lines, {n_dng} dungeon writings, {n_fixed} fixed ULT3 texts, "
          f"{n_ov} overlay strings, {n_rest} other ULT3 messages -> {path}")


if __name__ == "__main__":
    main()
