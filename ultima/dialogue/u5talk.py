#!/usr/bin/env python3
"""Ultima V's conversations as text, from its disks.

    python -m ultima.dialogue.u5talk [--out build/dialogue/u5]

Writes 3A-Towne.txt, 3B-Dwelling.txt, 4A-Castle.txt, 4B-Keep.txt (every
person of the eight places on that disk, place by place) and shops.txt (the
fixed texts of the shopkeepers' overlays and of the T overlay's guards).

The format, as found in the code (addresses are runtime addresses in the
file named; T is the Talk command's overlay, $A700, byte-identical on the
five disks that carry it, 2A and the four town disks):

- Who talks: main.twn $995D reads the place's people table as 512-byte
  record $F8 + ((place - 1) & 7) through $6C30 (temp.subs $6E7B: record r
  is track r >> 3, sectors (r & 7) * 2 and + 1) into $4A00-$4BFF -- so
  track 31 of each town disk, eight places a disk, in u5maps.PLACES' order.
  32 people a place; $4A00 + n is person n's tile, $4AE0 + n what Talk does
  with them (T $A907): 0 "No response!"; 1-$7F a conversation; $81-$88 a
  merchant, whose overlay TALK.xx is loaded by name (T $A80F: the two
  letters from $A834, AR BA HO SH RE GU HE IN); $FF a guard (T $A95F: the
  password at Blackthorn's palace, "half thy gold to charity" at Minoc,
  else a tribute); $FD and $FE are set in play (main.twn $9A1A, $9A2D).
- A conversation n is record $F0 - n of the same disk (T $AD4F), 512 bytes,
  Huffman coded (T $AC56): bits are taken from the low bit of each byte
  up; from the tree's root (T $ACBB) a 0 bit reads the byte at the node, a
  1 bit the next one; a byte below $80 is the distance from that byte to
  the child node, one from $80 up is a symbol; symbol $9B is an escape,
  seven more bits (high first) | $80 being the symbol.  Decoding stops
  after symbol $C0.  Symbols $A0-$FA are text (ASCII | $80), $80 ends a
  string (stored as 0, T $AD7B), the rest are codes.
- A script: five strings -- name, look, greeting, job, bye -- then
  keyword/answer string pairs (T $AE70: keyword k is string 2k + 5, its
  answer 2k + 6; a keyword is matched as a prefix of each word typed,
  capitals and small letters alike), up to a $90.  An answer that is only
  $87 (OR) means "the next keyword's answer" (T $AE2F).  Then labels:
  $90, the label ($91-$9E), the question it asks, the answer to anything
  else, keyword/answer pairs (T $AEB0), up to the next $90 (one label,
  Gwenno's L4 in Britain, has only its text, which ends the talk by her
  joining); $90 $9F ends the script.  Name, job, bye (and thank, work) are answered by T itself
  (T $B5E6, its word list at $B6C1) before the script's keywords are tried;
  the greeting is said only to someone whose name the person knows (a flag
  per place and person at $12C0, T $ADBE), otherwise "I am called <name>"
  half of the times (T $B728).
- Codes in text (T $B476): $81 the player's name, $82 end, $83 pause, $84
  join the party, $85 + three digits: pay that much gold, $86 + one byte:
  receive an item, $87 OR, $88 ask the player's name (the flag is set when
  the answer is the name of a party member, T $B283), $89/$8A karma +1/-1
  (temp.subs $6C34/$6C37), $8B call the guards (main.twn $8006), $8C + a
  label: if the person knows the player's name, go to the label ($FF: back
  to "Your interest?"), $8D new line, $8E runes on/off, $8F wait for a key,
  $91-$9E go to that label, $FE + two bytes: if karma ($2A, BCD) is at
  least the first & $7F, go to the second, $FF back to "Your interest?".
  T prints each answer between quotes, a quote right after a quote left
  out (T $B489) -- which is why the scripts carry quotes of their own.
- $86's byte & $7F (T $B1F0): below $40 one more of equipment item n ($1200
  + n; the names are TALK.AR's list at $B403, which the armoury indexes the
  same way, $BA6F -- inferred), 'A' food, 'B' gold (16-bit), 'C' keys,
  'D' gems, 'E' torches, 'F' $1187, 'G' $1188 (skiffs), 'H'-'J' set the
  flags $11F5, $11F3, $11FB, 'K' and up one more of $11F7.  What F and H-K
  are is read from the words of the scripts that give them (a grapple --
  "one can still fall whilst using it" --, a sextant, the spyglass, the
  badge, skull keys -- "could open even magically locked doors"), not
  checked against the inventory code.

Checked here (asserted): T's decoder and the record arithmetic are the code
described above, byte for byte; the Huffman tree is a proper tree; T is
identical on the four town disks; every conversation a people table names
decodes to its $90 $9F within its 512 bytes, with nothing after; only the
codes above appear, with arguments of the right kind (digits for $85,
labels for $8C/$FE); every label jumped to exists and is defined once.
Records no table names are not decoded (they hold garbage).

Found in the data (the records around them decode cleanly, so these are
the disks' own, and the game behaves as shown -- inferred from T's code,
not played): T pairs keyword and answer strings by position, and four
scripts have a string end too many or too few, which leaves "keywords"
no typed word can match: Mario in Yew (conversation 23 on 3A: after
"...give unto charity!" the rest of the answer and "caug"/"tort" are never
said), Sir Arbuthnot in Greyhaven (15 on 3B: the "y" of "Art thou the one
true Avatar?" is missing, so every answer gets "Oh."), Weblock in
Blackthorn's palace (14 on 4A: "gorn" is answered "hass"), and Temme in
Farthing (5 on 4B: the keyword "an ylem" has a space, and T matches one
word at a time).
"""
import argparse
import os
import re
import textwrap
from collections import OrderedDict

from ultima.disks.d64 import D64  # noqa: E402
from ultima.maps.u5maps import DISK, PLACES, TOWN_DISKS, TITLE  # noqa: E402
from ultima import paths

TREE = 0xACBB
MERCHANTS = {"AR": "armoury", "BA": "tavern", "HO": "stables", "SH": "shipwright",
             "RE": "reagents", "GU": "guild", "HE": "healer", "IN": "inn"}
ITEM_LIST = 0xB403                      # TALK.AR: the 48 equipment names
STOCK = {0x41: "food", 0x42: "gold", 0x43: "a key", 0x44: "a gem", 0x45: "a torch",
         0x46: "a grapple ($1187)", 0x47: "a skiff ($1188)", 0x48: "a sextant ($11F5)",
         0x49: "the spyglass ($11F3)", 0x4A: "the badge ($11FB)"}
END, OR, LABELS, SCRIPT_END = 0x80, 0x87, 0x90, 0x9F


def disk(tag):
    return D64(paths.disk(DISK[tag]))


def record(d, r):
    """temp.subs $6E7B: a 512-byte record, two sectors."""
    t, s = r >> 3, (r & 7) * 2
    return d.sector(t, s) + d.sector(t, s + 1), (t, s)


def prg(d, name):
    raw, ok = d.file(name)
    assert ok and raw, (d.path, name)
    return raw[0] | raw[1] << 8, raw[2:]


# -- the code this rests on ---------------------------------------------

def check_code(t, twn):
    """Assert that T and main.twn hold the routines the docstring describes."""
    base, m = t

    def at(addr, hexbytes):
        b = bytes.fromhex(hexbytes)
        assert m[addr - base:addr - base + len(b)] == b, f"T ${addr:04X} is not what this reads"

    at(0xAC56, "a000a2bba9ac8642854320a0ac")          # tree root $ACBB, next bit
    at(0xAC6D, "b14430086544")                        # node byte, distance
    at(0xAC79, "c99bd011a207")                        # escape, seven bits
    at(0xAC93, "c9c0d0bf")                            # stops after $C0
    at(0xACA0, "b140ae55ac3d98ac")                    # low bit first
    at(0xAD4F, "a9f038ed4dad")                        # record $F0 - n
    at(0xA832 + 2, b"ARBAHOSHREGUHEIN".hex())          # merchant overlays
    at(0xB6C1, bytes(c | 0x80 for c in b"NAME").hex() + "00")
    tb, tm = twn
    i = tm.find(bytes.fromhex("a90085b3a60aca8a290709f885b2"))
    assert i >= 0 and tb + i == 0x995D, "main.twn's people-table read moved"


def tree_symbols(t):
    """Walk the whole tree once: every symbol and that no node is shared oddly."""
    base, m = t
    seen, leaves, todo = set(), [], [TREE]
    while todo:
        node = todo.pop()
        for b in (0, 1):
            a = node + b
            assert a not in seen, f"tree byte ${a:04X} reached twice"
            seen.add(a)
            v = m[a - base]
            if v & 0x80:
                leaves.append(v)
            else:
                todo.append(a + v)
    assert len(leaves) == len(set(leaves)), "a symbol twice in the tree"
    return set(leaves)


def huffman(t, data):
    base, m = t
    pos = 0
    out = []

    def bit():
        nonlocal pos
        assert pos < len(data) * 8, "ran off the end of the record"
        b = data[pos >> 3] >> (pos & 7) & 1
        pos += 1
        return b

    while True:
        node = TREE
        while True:
            a = node + bit()
            v = m[a - base]
            if v & 0x80:
                break
            node = a + v
        if v == 0x9B:
            v = 0
            for _ in range(7):
                v = v << 1 | bit()
            v |= 0x80
        if v == 0xC0:
            return bytes(out), (pos + 7) // 8
        out.append(v)


# -- parsing --------------------------------------------------------------

TEXT = range(0xA0, 0xFB)
ARGS = {0x85: 3, 0x86: 1, 0x8C: 1, 0xFE: 2}
SIMPLE = {0x81, 0x82, 0x83, 0x84, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8D, 0x8E, 0x8F, 0xFF}


class Script:
    def __init__(self, data, where):
        self.data, self.where, self.i = data, where, 0
        self.head = [self.string() for _ in range(5)]
        self.main = self.pairs()
        self.labels = OrderedDict()
        while True:
            assert self.data[self.i] == LABELS, f"{where}: no $90 at {self.i}"
            label = self.data[self.i + 1]
            self.i += 2
            if label == SCRIPT_END:
                break
            assert 0x91 <= label <= 0x9E and label not in self.labels, f"{where}: label ${label:02X}"
            question = self.string()
            default = self.string() if self.data[self.i] != LABELS else None
            self.labels[label] = (question, default, self.pairs())
        assert self.i == len(data), f"{where}: {len(data) - self.i} bytes after the end"
        self.odd = [kw for kw, ans in self.main + [p for q in self.labels.values() for p in q[2]]
                    if not matchable(kw) or ans is None]
        for s in self.strings():
            for target in self.gotos(s):
                assert target in self.labels, f"{where}: goto ${target:02X}, no such label"

    def string(self):
        j = self.i
        while True:
            assert j < len(self.data), f"{self.where}: string runs off the end"
            c = self.data[j]
            if c == END:
                break
            if c in ARGS:
                arg = self.data[j + 1:j + 1 + ARGS[c]]
                assert len(arg) == ARGS[c] and (
                    c != 0x85 or all(0xB0 <= a <= 0xB9 for a in arg)) and (
                    c != 0x8C or arg[0] == 0xFF or 0x91 <= arg[0] <= 0x9E) and (
                    c != 0xFE or (arg[0] >= 0x80 and 0x91 <= arg[1] <= 0x9E)), \
                    f"{self.where}: ${c:02X} with {arg.hex()}"
                j += 1 + ARGS[c]
                continue
            assert c in TEXT or c in SIMPLE or 0x91 <= c <= 0x9E, f"{self.where}: code ${c:02X}"
            j += 1
        s, self.i = self.data[self.i:j], j + 1
        return s

    def pairs(self):
        """Strings up to the next $90, as T pairs them: by position.  The last
        keyword may have no answer (a stray string end in the original data,
        see odd_keywords)."""
        flat = []
        while self.data[self.i] != LABELS:
            flat.append(self.string())
        flat.append(None)
        return [(flat[k], flat[k + 1]) for k in range(0, len(flat) - 1, 2)]

    def strings(self):
        yield from self.head
        for kw, ans in self.main:
            if ans is not None:
                yield ans
        for q, d, pairs in self.labels.values():
            yield q
            if d is not None:
                yield d
            for kw, ans in pairs:
                if ans is not None:
                    yield ans

    @staticmethod
    def gotos(s):
        i = 0
        while i < len(s):
            c = s[i]
            if 0x91 <= c <= 0x9E:
                yield c
            elif c == 0x8C and s[i + 1] != 0xFF:
                yield s[i + 1]
            elif c == 0xFE:
                yield s[i + 2]
            i += 1 + ARGS.get(c, 0)


def matchable(kw):
    """A keyword a typed word can start with: text, no codes, no space (T
    $B5A8 cuts the input into words at spaces)."""
    return bool(kw) and all(c in TEXT and c != 0xA0 for c in kw)


def grouped(pairs):
    """[(keywords, answer)]: an answer that is only OR is the next keyword's."""
    out, kws = [], []
    for kw, ans in pairs:
        if matchable(kw):
            kws.append(plain(kw).lower())
        else:
            kws.append("(" + raw(kw) + ": no typed word can match this)")
        if ans == bytes([OR]):
            continue
        out.append((kws, ans))
        kws = []
    assert not kws, "an OR at the end of a keyword list"
    return out


def raw(s):
    """Text with codes as {$xx}, new lines as |."""
    return "".join(chr(c - 0x80) if c in TEXT else "|" if c == 0x8D else f"{{${c:02X}}}"
                   for c in s)


def plain(s):
    return "".join(chr(c - 0x80) for c in s)


def stops(s):
    """Does the string end the answer itself (end, goto, back to the prompt)?"""
    i = 0
    while i < len(s):
        if s[i] in (0x82, 0xFF) or 0x91 <= s[i] <= 0x9E:
            return True
        i += 1 + ARGS.get(s[i], 0)
    return False


def label_name(c):
    return f"L{c - 0x90}"


# -- rendering ------------------------------------------------------------

class Render:
    """The text as T prints it, codes as [actions] on lines of their own."""

    def __init__(self, items, name):
        self.items, self.name = items, name

    def __call__(self, s, quoted=True):
        if s is None:
            return ["[nothing follows: the list ends here in the data]"]
        lines, cur, last = [], "", ""
        runes = False

        def put(ch):
            nonlocal cur, last
            if ch == '"' and last == '"':          # T $B489
                return
            last = ch
            if ch == "\n":
                lines.append(cur)
                cur = ""
            else:
                cur += ch

        def act(text):
            nonlocal cur
            if cur.strip(' "'):
                lines.append(cur)
                cur = ""
            lines.append(f"[{text}]")         # a lone opening quote waits for the text

        if quoted:
            put('"')
        i = 0
        stop = False
        while i < len(s) and not stop:
            c = s[i]
            n = ARGS.get(c, 0)
            arg = s[i + 1:i + 1 + n]
            if c in TEXT:
                ch = chr(c - 0x80)
                if runes and ch != '"':
                    ch = ch.upper()
                put(ch)
            elif c == 0x8D:
                put("\n")
            elif c == 0x81:
                for ch in "<Avatar>":
                    put(ch)
            elif c == 0x8E:
                runes = not runes
                put("{" if runes else "}")
            elif c == 0x82:
                act("conversation ends")
                stop = True
            elif c == 0x83:
                act("pause")
            elif c == 0x84:
                act("joins the party, which ends the talk; with six in the party: \"Thou hast no room for me...\" and on")
            elif c == 0x85:
                act(f"takes {int(plain(arg))} gold; with less: \"Thou hast not enough gold!\" "
                    f"and back to \"Your interest?\"")
            elif c == 0x86:
                act(f"gives {self.item(arg[0])}")
            elif c == 0x87:
                act("the next keyword's answer")
            elif c == 0x88:
                act("asks thy name: \"What is thy name?\"; a party member's name"
                    " makes the person know it (\"A pleasure!\"), else \"If you say so...\"")
                last = "!"
            elif c == 0x89:
                act("karma +1")
            elif c == 0x8A:
                act("karma -1")
            elif c == 0x8B:
                act("calls the guards")
            elif c == 0x8C:
                where = 'back to "Your interest?"' if arg[0] == 0xFF else f"goto {label_name(arg[0])}"
                act(f"if {self.name} knows thy name: {where}")
            elif c == 0x8F:
                act("waits for a key")
            elif 0x91 <= c <= 0x9E:
                act(f"goto {label_name(c)}")
                stop = True
            elif c == 0xFE:
                act(f"if karma >= {arg[0] & 0x7F}: goto {label_name(arg[1])}")
            elif c == 0xFF:
                act('back to "Your interest?"')
                stop = True
            else:
                raise AssertionError(f"code ${c:02X}")
            i += 1 + n
        if quoted and not stop:
            put('"')
        if cur.strip():
            lines.append(cur)
        dead = s[i:]
        if dead:
            lines.append("[never printed: " + " / ".join(self(dead, False)) + "]")
        out = []
        for line in lines:
            line = line.rstrip()
            if line.strip('"') == "" and line:
                continue                        # a lone quote T prints around an action
            if line == "" and (not out or out[-1] == ""):
                continue
            out.append(line)
        while out and out[-1] == "":
            out.pop()
        return out

    def item(self, b):
        b &= 0x7F
        if b < 0x40:
            return f"{self.items[b]} (equipment item {b})" if b < len(self.items) else f"equipment item {b}"
        if b in STOCK:
            return STOCK[b]
        return "a skull key ($11F7)"


def wrap(lines, indent):
    out = []
    for line in lines:
        if not line:
            out.append("")
            continue
        out.extend(textwrap.wrap(line, 76 - len(indent), initial_indent=indent,
                                 subsequent_indent=indent + ("  " if line.startswith("[") else ""))
                   or [indent])
    return out


def short_name(s):
    """The name for a header: its text up to the first code or quote."""
    m = re.match(r"[^\x00-\x1f\x7f\"]*", "".join(chr(c - 0x80) if c in TEXT else "\x00" for c in s))
    name = m.group(0).strip(" .")
    return name or "(no name: " + raw(s) + ")"


def render_npc(sc, render, header):
    name = short_name(sc.head[0])
    he = "the person"
    r = Render(render.items, he)
    out = ["=" * 76, header + f"  --  {name}"]
    look = r(sc.head[1], False)
    out += wrap(["Look: You see " + (look[0] if look else "")] + look[1:], "")
    out.append("=" * 76)
    out.append("")
    out.append("Until the person knows thy name, half of the times:")
    out += wrap(r(bytes(c | 0x80 for c in b"I am called ") + sc.head[0]), "    ")
    out.append("Once the person knows thy name:")
    out += wrap(r(sc.head[2]) if sc.head[2] else ["(nothing)"], "    ")
    out.append("")
    out.append(">> name")
    out += wrap(r(bytes(c | 0x80 for c in b"My name is ") + sc.head[0]), "    ")
    out.append("")
    out.append(">> job, work")
    out += wrap(r(sc.head[3]) if sc.head[3] else ["(nothing)"], "    ")
    out.append("")
    out.append(">> bye, thank   (or nothing typed)")
    bye = r(sc.head[4])
    out += wrap(bye + ([] if stops(sc.head[4]) else ["[conversation ends]"]), "    ")
    out.append("")
    for kws, ans in grouped(sc.main):
        out.append(">> " + ", ".join(kws))
        out += wrap(r(ans), "    ")
        out.append("")
    out.append(">> *")
    out.append('    "I cannot help thee with that."')
    out.append("")
    for label, (q, default, pairs) in sc.labels.items():
        out.append(f"({label_name(label)})")
        out += wrap(r(q), "")
        if stops(q):
            if default is None and not pairs:
                out.append("")
                continue
            out.append("[never reached: the answers below]")
        else:
            out.append("You respond-")
        for kws, ans in grouped(pairs):
            out.append("  >> " + ", ".join(kws))
            out += wrap(r(ans), "      ")
        if default is None:
            out.append("  [no answers: the data has none, see the module's docstring]")
        else:
            out.append("  >> *")
            out += wrap(r(default), "      ")
            out.append("  [then back to \"Your interest?\", unless it says otherwise]")
        out.append("")
    return out


# -- the disks -------------------------------------------------------------

HOW_TO_READ = """\
How to read this:
  Each person: the place, the person's number in the place's people table
  (0-31), the conversation's number and where it is on the disk (track,
  sectors).  "Look" is how a talk starts ("You see ..."); then what is said
  on meeting, and every keyword with its answer, as the game prints them.
  The text is the disks' own, typing errors and all.
  >> kw1, kw2   what the player types: the game takes each word typed and
                tries the keywords in order as its start (TELESCOPE matches
                "tele"); name, job, work, bye and thank are answered first
  >> *          anything else
  (... no typed word can match this)
                a "keyword" no input can reach: the original data has a
                string end too many or too few there, which shifts T's
                keyword/answer pairing (T pairs strings by position)
  [ ... ]       what the script does besides talking
  (Ln)          a question the script asks, reached by [goto Ln]; the
                answers to it follow, then back to "Your interest?"
  {...}         printed in runes
  <Avatar>      the player's name
"""


def people(d):
    """[(place index 0-7, [(slot, tile, talk byte)])], from track 31."""
    out = []
    for p in range(8):
        rec, _ = record(d, 0xF8 + p)
        out.append([(n, rec[n], rec[0xE0 + n]) for n in range(32)])
    return out


def special(v, place):
    if v == 0xFF:
        if place == 18:
            return ('a guard: "Give now the password, bearer of the Badge!" -- IMPE...'
                    ' answers "Pass, friend!" (T $AA45)')
        if place == 5:
            return 'a guard: "Thou wilt give half thy gold to charity!" (T $A96C)'
        return ('a guard: "A guard demands a <10 per party member> gp tribute to'
                ' Blackthorn!  Dost thou pay?" (T $A9C0)')
    if 0x81 <= v <= 0x88:
        code = "ARBAHOSHREGUHEIN"[2 * (v - 0x81):2 * (v - 0x80)]
        return f"a merchant: TALK.{code} ({MERCHANTS[code]}), see shops.txt"
    return f"talk byte ${v:02X}"


def extract(out_dir):
    t3a = None
    items = None
    totals = []
    for g, tag in enumerate(TOWN_DISKS):
        d = disk(tag)
        t = prg(d, "T")
        if t3a is None:
            t3a = t
            check_code(t, prg(d, "MAIN.TWN"))
            symbols = tree_symbols(t)
            assert {END, 0x9B, 0xC0, SCRIPT_END, LABELS} <= symbols
            ib, im = prg(d, "TALK.AR")
            items, j = [], ITEM_LIST - ib
            for _ in range(48):
                k = j
                while im[k] & 0x80:
                    k += 1
                items.append(plain(bytes(c | 0x80 for c in im[j:k + 1])))
                j = k + 1
            assert items[0] == "Leather Helm" and items[-1] == "Ankh", items
        assert t == t3a, f"T differs on {tag}"
        render = Render(items, "the person")
        title = f"{tag} - {TITLE[tag]}"
        lines = [f"Ultima V (C64) -- conversations on disk {title}", ""]
        body = []
        nnpc = 0
        done = {}
        for p, table in enumerate(people(d)):
            place_no = 8 * g + p + 1
            place = PLACES[8 * g + p][0]
            body += ["", "#" * 76, f"# {place} (place {place_no}, disk {tag})", "#" * 76, ""]
            others = [(n, v) for n, tile, v in table if v >= 0x80]
            kinds = OrderedDict()
            for n, v in others:
                kinds.setdefault(special(v, place_no), []).append(n)
            for what, ns in kinds.items():
                who = f"person {ns[0]}" if len(ns) == 1 else "persons " + ", ".join(map(str, ns))
                body += textwrap.wrap(f"{who}: {what}", 76, subsequent_indent="    ")
            if others:
                body.append("")
            for n, tile, v in table:
                if not 0 < v < 0x80:
                    continue
                rec, (tr, se) = record(d, 0xF0 - v)
                where = f"[{tag} {place}]  person {n}, conversation {v} (T{tr} S{se}-{se + 1})"
                if v in done:
                    body += [f"person {n}: conversation {v}, the same as {done[v]}", ""]
                    continue
                data, _ = huffman(t, rec)
                assert data[-2:] == bytes([LABELS, SCRIPT_END]), f"{where}: no $90 $9F"
                sc = Script(data, where)
                done[v] = f"person {n} in {place}"
                body += render_npc(sc, render, where)
                body.append("")
                nnpc += 1
        lines.append(f"{nnpc} conversations, eight places")
        lines.append("")
        lines += HOW_TO_READ.splitlines()
        text = "\n".join(lines + body).rstrip() + "\n"
        name = f"{tag}-{TOWN_DISKS[tag].capitalize()}.txt"
        with open(os.path.join(out_dir, name), "w") as fh:
            fh.write(text)
        totals.append((name, nnpc))
    shops(out_dir, t3a)
    return totals


# -- the shopkeepers ---------------------------------------------------------

def strings(base, m):
    """Texts in an overlay: inline after JSR $4C00 (0-terminated), and T's
    $A70C kind (bit 7 set, the last character's clear).  A heuristic scan:
    runs of at least three characters, mostly letters."""
    found = {}
    i = 0
    while i < len(m) - 3:
        if m[i:i + 3] == b"\x20\x00\x4c":
            j = i + 3
            while j < len(m) and m[j] != 0:
                j += 1
            s = m[i + 3:j]
            if s and all(c >= 0x80 for c in s):
                found[base + i + 3] = (text_of(s), base + j)
            i = j + 1
            continue
        i += 1
    i = 0
    while i < len(m):
        j = i
        while j < len(m) and (m[j] in TEXT or m[j] in (0x8D, 0x84)):
            j += 1
        if j < len(m) and 0x20 <= m[j] < 0x7B and j - i >= 2:
            for k in range(i, j - 2):
                # a run may start with table bytes that look like text
                if k > i and not (0xC1 <= m[k] <= 0xDA or m[k] == 0xA2):
                    continue
                txt = text_of(bytes(m[k:j]) + bytes([m[j] | 0x80]))
                if wordy(txt) and not any(a <= base + k <= e for a, (_, e) in found.items()):
                    found[base + k] = (txt, base + j)
                    break
            i = j + 1
        else:
            i = j + 1 if j > i else i + 1
    return sorted((a, t) for a, (t, _) in found.items())


def wordy(txt):
    """Looks like words: mostly letters, every word with a vowel, no camel case."""
    words = re.findall(r"[A-Za-z]+", txt)
    letters = sum(len(w) for w in words)
    return (letters >= 4 and letters >= 0.75 * len(txt.replace(" ", "").replace("|", ""))
            and not re.search(r"[a-z][A-Z]|[A-Z]{2,}[a-z]|[A-Za-z][0-9]|[0-9][A-Za-z]", txt)
            and all(re.search("[aeiouyAEIOUY]", w) or w.isupper() or len(w) == 1 for w in words))


def text_of(s):
    return "".join("|" if c == 0x8D else "" if c == 0x84 else chr(c & 0x7F) for c in s)


def shops(out_dir, t):
    out = ["Ultima V (C64) -- the shopkeepers' texts", "",
           "Merchants talk through overlays of their own, TALK.xx at $A900, loaded",
           "by T ($A80F) for a person whose talk byte is $81-$88.  Their texts are",
           "fixed strings, not scripts: listed here by address as a scan finds them",
           "(T's kind -- bit 7 set but on the last character -- and inline after",
           "JSR $4C00); '|' is a new line, '####' a number the code fills in.",
           "Which string is said when is the overlay's code, not decoded here.", ""]
    where = {}
    for tag in TOWN_DISKS:
        d = disk(tag)
        for name, _, _, _, _ in d.directory():
            n = name.upper()
            if n.startswith("TALK.") or n == "SELL.ARMS":
                where.setdefault(n, []).append((tag, d))
    places = {}
    for g, tag in enumerate(TOWN_DISKS):
        for p, table in enumerate(people(disk(tag))):
            for n, tile, v in table:
                if 0x81 <= v <= 0x88:
                    code = "ARBAHOSHREGUHEIN"[2 * (v - 0x81):2 * (v - 0x80)]
                    places.setdefault("TALK." + code, []).append(PLACES[8 * g + p][0])
    for name in sorted(where):
        blobs = {prg(d, name) for _, d in where[name]}
        assert len(blobs) == 1, f"{name} differs between disks"
        base, m = blobs.pop()
        kind = MERCHANTS.get(name[5:], "selling to an armoury" if name == "SELL.ARMS" else "?")
        out.append("=" * 76)
        out.append(f"{name} ({kind}), ${base:04X}, on {' '.join(t for t, _ in where[name])}")
        if name in places:
            out += textwrap.wrap("in: " + ", ".join(OrderedDict.fromkeys(places[name])), 76)
        out.append("=" * 76)
        for addr, s in strings(base, m):
            out.append(f"${addr:04X}  {s}")
        out.append("")
    base, m = t
    out.append("=" * 76)
    out.append("T (the Talk command), $A700: what it says itself")
    out.append("=" * 76)
    for addr, s in strings(base, m):
        out.append(f"${addr:04X}  {s}")
    with open(os.path.join(out_dir, "shops.txt"), "w") as fh:
        fh.write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "dialogue", "u5"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for name, n in extract(a.out):
        print(f"{os.path.join(a.out, name)}: {n} conversations")
    print(os.path.join(a.out, "shops.txt"))


if __name__ == "__main__":
    main()
