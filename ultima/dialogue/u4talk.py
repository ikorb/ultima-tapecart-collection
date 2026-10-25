#!/usr/bin/env python3
"""Ultima IV's conversations as text, from its disks or from the cart.

    python -m ultima.dialogue.u4talk [--cart [build/ultima-collection.tcrt]] [--out DIR]

Writes u4-dialogue.txt (default: build/dialogue/u4/), from the original
d64s; with --cart, u4-dialogue-cart.txt from the cart as built -- the
Remastered kit's mixed case and its content fixes (Thevel and the Serpent's
Hold gate guards reachable, triggers and keywords mended), which is what a
player of the collection sees.

How the game does it:
- Talk (game main, chunk $5B, $59CE) in a town or castle (location $1A
  1-16, Castle British's upper floor being location 1 too): the person's
  conversation byte n (the town's people table, map chunk +$4E0; 0 is
  nobody, "FUNNY, NO RESPONSE!") picks page 16 x (location - 1) + n of disk
  B's blocks 1-256, read to $AD00; Lord British (tile $5E) runs his own
  overlay, chunk $87, instead of the talk overlay $78.  Over a counter,
  tile $52 is a shop (the shop overlays, chunk $6D + the shop: not here).
- A page: $00, ten strings ($8D a new line, NUL-terminated) -- name,
  pronoun, LOOK, JOB, HEALTH, the answers to keywords 1 and 2, a question
  and the answers to Y and N -- then keyword 1 at $F0 and 2 at $F6 (only
  their first four letters are compared, as for all of Talk's words), the
  question's trigger at $FC (the keyword after whose answer it is asked:
  3 JOB, 4 HEALTH, 5/6 keyword 1/2, 10 the N answer, which asks again),
  $FD unused, a humility flag at $FE (Y costs 5 humility, N gains 10 if
  not too recently) and the turn-away chance at $FF (out of 256, on
  meeting and before each answer; well below it, the person attacks).
  (ultima/games/u4/remastered.py talk_decode; the talk code is the kit's
  src/talk/talk.s, which differs from the original only in text and case.)
- Talk's own words (NAME, LOOK, JOB, HEAL, JOIN, GIVE, BYE) are answered
  from the page or by the overlay's code; JOIN and GIVE by rules (a
  companion joins if the virtue of the town is high enough, beggars take
  gold), which the header below gives in words.
- Lord British (chunk $87): 28 keywords at its keyword table, each with a
  routine through its jump table (`ASL / TAY / LDA tbl,Y / STA $7E`...);
  each routine's text is shown in code order, alternatives one after the
  other.  HELP is chunk $88: the first of nine hints whose condition holds.
"""
import argparse
import os
import re

from ultima.disks.d64 import D64
from ultima.sim.dis6502 import decode
from ultima import paths


from ultima.games.u4 import build as u4
from ultima.games.u4 import remastered as rm

A, C, B, D = 1, 2, 3, 4
TOWNS = ["Castle British", "Lycaeum", "Empath Abbey", "Serpent's Hold", "Moonglow", "Britain",
         "Jhelom", "Yew", "Minoc", "Trinsic", "Skara Brae", "Magincia", "Paws",
         "Buccaneer's Den", "Vesper", "Cove"]
TOWN_CHUNK, UPPER_FLOOR = 0x5C, 0x6C
TALK_FIRST = 1
PEOPLE, P_TILE, P_X, P_Y, P_CONV = 0x400, 0x00, 0x20, 0x40, 0xE0
# conversations nobody on a town's map has, but code puts someone with: chunk
# $73 (a shop overlay, the inn's by the look of it) stores conversation 16
# into the people table's +$E0 ($8B3x, disk B block 404) in Skara Brae
PLACED = {(10, 16): "nobody on the map: the inn's code (chunk $73) puts him there"}
TRIGGERS = {0: None, 3: "JOB", 4: "HEALTH", 5: "keyword 1", 6: "keyword 2", 10: "the N answer"}
PRIMM, PRIMM_XY, CONSOLE_OUT, WAITKEY, PRINTNAME, PRINTDIGIT = 0x0821, 0x081E, 0x0824, 0x0800, 0x0830, 0x0866
HELP_WHEN = [
    "the first thousand moves", "while the Avatar travels alone", "with no rune",
    "while no virtue is at partial Avatarhood", "with no stone",
    "while a virtue is not yet raised", "without the bell, book and candle",
    "without the whole three-part key", "when all of it is done"]


class Disks:
    """The original disks: blocks and chunks."""

    def __init__(self):
        self.img = {n: D64(f).data for n, (f, _) in u4.DISKS.items()}
        self.kernel = u4.kernel_image(D64(u4.DISKS[A][0]))

    def block(self, disk, n):
        return bytes(self.img[disk][n * 256:(n + 1) * 256])

    def chunk(self, c, disk):
        start, count, dest = u4.chunk_entry(self.kernel, c)
        return dest, b"".join(self.block(disk, start + i) for i in range(count))


class Cart:
    def __init__(self, tcrt):
        from ultima.maps import u4maps
        self.c = u4maps.Cart(tcrt)

    def block(self, disk, n):
        return self.c.block(disk, n)

    def chunk(self, c, disk):
        return self.c.chunk_entry(c)[2], self.c.chunk(c, disk)


def chars(bs):
    return "".join("\n" if b & 0x7F == 0x0D else chr(b & 0x7F) for b in bs)


class Code:
    """An overlay's text, read the way it prints: J_PRIMM's inline strings
    (and J_PRIMM_XY's), a character through J_CONSOLE_OUT, the name, a key
    wait; a JSR to a routine of its own that prints is followed."""

    def __init__(self, dest, data):
        self.base, self.mem = dest, data

    def string(self, at):
        o = at - self.base
        end = self.mem.index(0, o)
        return chars(self.mem[o:end]), self.base + end + 1

    def render(self, start, end, depth=0):
        out, pc, a = [], start, None
        while pc < end:
            ins = decode(self.mem, self.base, pc)
            assert ins, f"no instruction at ${pc:04X}"
            mn, mode, n, arg = ins
            if mn == "lda" and mode == "imm":
                a = arg
            if mn == "jsr" and arg == PRIMM:
                s, pc = self.string(pc + 3)
                out.append(s)
                continue
            if mn == "jsr" and arg == PRIMM_XY:
                s, pc = self.string(pc + 5)
                out.append(s)
                continue
            if mn == "jsr" and arg == CONSOLE_OUT and a is not None:
                out.append(chars([a]))
            elif mn == "jsr" and arg == PRINTNAME:
                out.append("<name>")
            elif mn == "jsr" and arg == PRINTDIGIT:
                out.append("<n>")
            elif mn == "jsr" and arg == WAITKEY:
                out.append("\n")
            elif mn == "jsr" and self.base <= arg < self.base + len(self.mem) and depth < 2 \
                    and self.prints(arg):
                out += self.render(arg, self.routine_end(arg), depth + 1)
            if mn in ("rts", "jmp") and depth:
                break
            pc += n
        return out

    def prints(self, at):
        """Whether the routine at `at` prints a string of its own (or through
        one it calls): the input routine, which echoes keys, does not."""
        pc, end = at, self.routine_end(at)
        while pc < end:
            ins = decode(self.mem, self.base, pc)
            if ins[0] == "jsr" and ins[3] in (PRIMM, PRIMM_XY):
                return True
            if ins[0] == "jsr" and self.base <= ins[3] < self.base + len(self.mem) and ins[3] != at \
                    and self.mem[ins[3] - self.base:ins[3] - self.base + 3] == b"\x20\x21\x08":
                return True
            pc += ins[2]
        return False

    def routine_end(self, at):
        pc = at
        while True:
            ins = decode(self.mem, self.base, pc)
            assert ins
            if ins[0] == "jsr" and ins[3] in (PRIMM, PRIMM_XY):
                pc = self.string(pc + (3 if ins[3] == PRIMM else 5))[1]
                continue
            pc += ins[2]
            if ins[0] in ("rts", "jmp"):
                return pc


def tidy(parts):
    s = "".join(parts)
    s = re.sub(r"\n{3,}", "\n\n", s).strip("\n")
    return s


def indent(s, by="    "):
    return "\n".join((by + l) if l else "" for l in s.split("\n"))


def field(label, text, col=10):
    lines = text.split("\n")
    return "\n".join([f"  {label:<{col - 2}}{lines[0]}"] + [" " * col + l for l in lines[1:]])


def conversation(page, n, who, out):
    c = rm.talk_decode(page)
    he = c["pronoun"]
    out.append(f"--- {n}: {c['name']}   ({who})")
    out.append(field("LOOK", "You see " + c["description"]))
    out.append(field("NAME", f"{he} says: I am {c['name']}"))
    for key, word in (("job", "JOB"), ("health", "HEAL"), ("keyword_response_1", c["keyword_1"]),
                      ("keyword_response_2", c["keyword_2"])):
        out.append(field(word, c[key]))
    trig = c["trigger"]
    assert trig in TRIGGERS, trig
    if TRIGGERS[trig]:
        hum = page[0xFE]
        assert hum in (0, 1) and page[0xFD] == 0
        out.append(f"  after {TRIGGERS[trig]}, {he} asks:")
        out.append(field("", c["question"]))
        out.append(field("Y", c["question_yes_answer"] + ("   [humility -5]" if hum else "")))
        out.append(field("N", c["question_no_answer"] + ("   [humility +10]" if hum else "")))
    elif c["question"].strip():
        out.append("  (a question no answer leads to:)")
        out.append(field("", c["question"]))
    if page[0xFF]:
        out.append(f"  may turn away or attack: {page[0xFF]} in 256")
    out.append("")


def lord_british(src, out):
    dest, data = src.chunk(0x87, C)
    code = Code(dest, data)
    m = re.search(rb"\x0a\xa8\xb9(..)\x85\x7e\xb9..\x85\x7f\x6c\x7e\x00", data, re.S)
    assert m, "LB's keyword dispatch"
    jt = m.group(1)[0] | m.group(1)[1] << 8
    up = bytes(b & 0x7F for b in data).upper()
    k = up.find(b"    BYE NAMELOOKJOB HEAL")
    assert k > 0, "LB's keyword table"
    words = [up[k + 4 * i:k + 4 * i + 4].decode().strip() for i in range(28)]
    targets = [data[jt - dest + 2 * i] | data[jt - dest + 2 * i + 1] << 8 for i in range(28)]
    assert words[1] == "BYE" and words[27] == "VIRT" and targets[0] == targets[1]
    m = re.search(rb"\xe6\x25\x4c(..)", data[:0x20], re.S)
    assert m, "LB's first meeting"
    intro = m.group(1)[0] | m.group(1)[1] << 8
    table = dest + k
    assert max(targets) < intro < table
    ends = sorted(set(targets)) + [intro]
    out += ["=" * 76, "Lord British (Castle British; chunk $87)", "=" * 76, ""]
    out.append("The first time he is spoken to:")
    out.append(indent(tidy(code.render(intro, table))))
    out.append("")
    out.append("After that (a dead Avatar is brought back, then his greeting, and a level for")
    out.append("each of the party who has earned one):")
    out.append(indent(tidy(code.render(dest + 3, m.start() + dest + 2) + code.render(m.start() + dest + 5, jt - 3))))
    out.append("")
    for i in range(1, 28):
        t = targets[i]
        end = next(e for e in ends if e > t)
        out.append(f">> {words[i]}")
        said = tidy(code.render(t, end))
        assert said or words[i] == "HELP", words[i]
        out.append(indent(said or "[his hints: HELP, below]"))
        out.append("")
    hdest, hdata = src.chunk(0x88, C)
    help_ = Code(hdest, hdata)
    starts = []
    for m in re.finditer(rb"\x4c(..)", hdata[:0xA0], re.S):
        a = m.group(1)[0] | m.group(1)[1] << 8
        if hdest <= a < hdest + len(hdata) and hdata[a - hdest] == 0x20 and \
                hdata[a - hdest + 3:a - hdest + 6] == b"\x20\x21\x08":
            starts.append(a)
    assert len(starts) == 9, starts
    out.append(">> HELP   (chunk $88: the first hint whose condition holds, in this order)")
    for when, s in zip(HELP_WHEN, starts):
        out.append(f"  {when}:")
        out.append(indent(tidy(help_.render(s, _help_end(help_, s))), " " * 6))
        out.append("")


def _help_end(code, start):
    """A hint runs to its JMP back to the conversation."""
    pc = start
    while True:
        ins = decode(code.mem, code.base, pc)
        if ins[0] == "jsr" and ins[3] == PRIMM:
            pc = code.string(pc + 3)[1]
            continue
        if ins[0] == "jmp":
            return pc
        pc += ins[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cart", nargs="?", const=os.path.join(paths.BUILD, "ultima-collection.tcrt"))
    ap.add_argument("--out", default=os.path.join(paths.BUILD, "dialogue", "u4"))
    a = ap.parse_args()
    src = Cart(a.cart) if a.cart else Disks()
    what = "the cart as built (the Remastered kit's text)" if a.cart else "the original disks"
    out = [f"Ultima IV (C64) -- the conversations, from {what}",
           "",
           "How to read this:",
           "  Each town: who stands where (x, y on its 32 x 32 map, as build/maps/u4/towns",
           "  draws it) with which conversation, then the conversations.  In one:",
           "  LOOK, NAME, JOB, HEAL and the two keywords are what the player can ask (the",
           "  first four letters count); the question comes after the answer named, and",
           "  Y or N gets the answer shown.  Talk also always knows:",
           "    BYE   \"<he> says: Bye.\"     anything else   \"That, I cannot help thee with.\"",
           "    JOIN  in the eight virtue towns a companion joins if the Avatar's virtue there",
           "          is high enough and the party has room (else \"Thou art not <virtue>",
           "          enough for me to join thee.\"); elsewhere \"I cannot join thee.\"",
           "    GIVE  a beggar asks \"How much-\" and is thankful (compassion, and honesty",
           "          when it leaves no gold); anyone else \"I do not need thy gold, keep it!\"",
           "  On meeting: \"You meet <LOOK>\" and, half the time, the NAME answer.",
           "  Shopkeepers (over a counter) and Hawkwind run the shops' own code: not here.",
           ""]
    for t in range(16):
        chunks = [TOWN_CHUNK + t] + ([UPPER_FLOOR] if t == 0 else [])
        users = {}
        for ch in chunks:
            _dest, data = src.chunk(ch, B)
            p = data[PEOPLE:]
            for i in range(32):
                tile, conv = p[P_TILE + i], p[P_CONV + i]
                if tile and conv:
                    where = f"[{p[P_X + i]},{p[P_Y + i]}]" + (" upstairs" if ch == UPPER_FLOOR else "")
                    users.setdefault(conv, []).append(where)
        out += ["=" * 76, f"{TOWNS[t]}   (location {t + 1}; conversations: disk B blocks "
                f"{TALK_FIRST + 16 * t}-{TALK_FIRST + 16 * t + 15})", "=" * 76, ""]
        for n in range(1, 17):
            page = src.block(B, TALK_FIRST + 16 * t + n - 1)
            who = ("at " + " ".join(users[n])) if n in users else \
                PLACED.get((t, n), "nobody here has it -- unreachable")
            conversation(page, n, who, out)
        for n in sorted(users):
            if not 1 <= n <= 16:
                out.append(f"(at {' '.join(users[n])}: conversation byte ${n:02X}, not one of the "
                           "town's 16 -- not followed here)")
                out.append("")
        if t == 0:
            lord_british(src, out)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "u4-dialogue-cart.txt" if a.cart else "u4-dialogue.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("written", path)


if __name__ == "__main__":
    main()
