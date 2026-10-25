#!/usr/bin/env python3
"""Extract the conversations from Ultima 6's three Populace disks as text.

    python -m ultima.dialogue.u6_dialogue [outdir]      # default: u6-dialogue/

Each file tNNN is one NPC's conversation script: FF NN, the name, F1 and the
look description, F2 and the script.  The bytecode is the PC version's
(Nuvie's ConverseInterpret names the opcodes), with two C64 differences: the
text is in its own character set (below) and JUMP targets and the D2/D4
literals are 16-bit.

Text: $01-$1A are a-z, $41-$5A A-Z, $20-$3F as ASCII, $8D a new line.  '@'
marks the next word as a keyword (highlighted in the game) and '*' waits for
a key.  $n and #n in the text are string and number variables; $2-$7 are
the engine's (title, NPC name, player name, time of day, a party member,
the last input -- inferred from how the scripts use them, see SUBST).

The script is decoded linearly.  After a JUMP or BYE the bytes up to the next
jump target are a data table when a D2 literal points into them; those are
shown as the strings they hold.  Every jump target is checked to fall on an
instruction boundary, which is what says the operand counts below are right.
"""

import os
from ultima import paths
import sys

from ultima.disks.d64 import D64  # noqa: E402

DISKS = [
    ("2A", "Populace A", "u6-2a"),
    ("2B", "Populace B", "u6-2b"),
    ("3A", "Populace C", "u6-3a"),
]

# statements: opcode -> number of $A7-terminated expressions that follow
EXPR_ARGS = {
    0xA1: 1,   # IF
    0xA4: 2,   # SETF npc, flag
    0xA5: 2,   # CLEARF npc, flag
    0xA8: 1,   # ASSIGN (after DECL)
    0xB5: 1,   # DPRINT table, index
    0xB9: 4,   # NEW npc, obj, quality, quantity
    0xBA: 4,   # DELETE npc, obj, quality, quantity
    0xBF: 1,   # PORTRAIT
    0xC4: 1,   # ADDKARMA
    0xC5: 1,   # SUBKARMA
    0xC9: 4,   # GIVE
    0xCD: 2,   # WORKTYPE npc, type
    0xD6: 1,   # RESURRECT
    0xD8: 1,   # SETNAME-like: var, value
    0xD9: 1,   # HEAL
    0xDB: 1,   # CURE
}
NO_ARGS = {0xA2: "ENDIF", 0xA3: "ELSE", 0xB6: "BYE", 0xCB: "WAIT",
           0xEE: "ENDANSWERS", 0xF1: "LOOK", 0xF2: "CONVERSE",
           0xF3: "PREFIX", 0xF6: "ANSWER", 0xF7: "ASK", 0x9E: "SLEEP"}
VARREF = {0xF9: "INPUTSTR", 0xFB: "INPUT", 0xFC: "INPUTNUM"}  # n B2|B3
TEXTARG = {0xEF: "KEYWORDS", 0xF8: "ASKC"}

BINOPS = {0x81: ">", 0x82: ">=", 0x83: "<", 0x84: "<=", 0x85: "!=",
          0x86: "==", 0x90: "+", 0x91: "-", 0x92: "*", 0x93: "/",
          0x94: "or", 0x95: "and"}
FUNCS = {0xA0: ("rand", 2), 0xAB: ("flag", 2), 0xB4: ("data", 2),
         0xBB: ("objcount", 2), 0xC6: ("in_party", 1),
         0xC7: ("party_has", 2), 0x9A: ("can_carry", 1),
         0x9B: ("weight", 2), 0x9D: ("horsed", 1), 0x9F: ("has_obj", 2),
         0xD7: ("nearby", 1), 0xDA: ("wounded", 1), 0xDC: ("poisoned", 1),
         0xDD: ("npc", 2), 0xE0: ("exp", 2), 0xE1: ("level", 2),
         0xE2: ("str", 2), 0xE3: ("int", 2), 0xE4: ("dex", 2),
         0xCA: ("join_party", 1), 0xCC: ("leave_party", 1),
         0xB7: ("index_of_input_in", 2)}


def char(b):
    if 0x01 <= b <= 0x1A:
        return chr(b + 0x60)
    if 0x20 <= b <= 0x5F:
        return "" if b == 0x5C else chr(b)    # '\\' ends a $/# name
    if b == 0x00:
        return ""
    if b == 0x8D:
        return "\n"
    return None


def text(bs):
    return "".join("<%02X>" % b if char(b) is None else char(b)
                   for b in bs)


class Unknown(Exception):
    pass


class Script:
    def __init__(self, data, names):
        self.d = data
        self.names = names
        self.targets = set()
        self.dataaddrs = set()
        self.strtables = set()      # tables read into $n or printed

    # -- tokens -------------------------------------------------------------

    def expr(self, p, stop=0xA7):
        """Tokens up to and including `stop`: (tokens, next position)."""
        d, toks = self.d, []
        while True:
            b = d[p]
            if b == stop:
                self.last_addrs = [v for k, v in toks if k == "a"]
                if any(t == ("op", 0xB4) or t == ("op", 0xB7) for t in toks):
                    self.dataaddrs.update(v for k, v in toks if k == "a")
                return [(("n" if k == "a" else k), v) for k, v in toks], p + 1
            if b == 0xD3:
                toks.append(("n", d[p + 1]))
                p += 2
            elif b in (0xD2, 0xD4):
                v = d[p + 1] | d[p + 2] << 8
                toks.append(("a" if b == 0xD2 else "n", v))
                p += 3
            elif b < 0x80:
                toks.append(("n", b))
                p += 1
            else:
                toks.append(("op", b))
                p += 1

    def render(self, toks):
        st = []
        for kind, v in toks:
            if kind == "n":
                st.append("self" if v == 0xEB else str(v))
            elif v in (0xB2, 0xB3) and st:
                st.append(("#" if v == 0xB2 else "$") + st.pop())
            elif v in BINOPS and len(st) >= 2:
                b = st.pop()
                a = st.pop()
                st.append("(%s %s %s)" % (a, BINOPS[v], b))
            elif v in FUNCS and len(st) >= FUNCS[v][1]:
                name, n = FUNCS[v]
                args = st[-n:]
                del st[-n:]
                if name in ("flag", "in_party", "nearby", "wounded",
                            "poisoned", "exp", "level", "str", "int",
                            "dex") and args[0].isdigit():
                    args[0] = self.names.get(int(args[0]), args[0])
                st.append("%s(%s)" % (name, ", ".join(args)))
            else:
                st.append("op%02X(%s)" % (v, ", ".join(st)))
                st = st[-1:]
        return " ".join(st)

    # -- decoding -----------------------------------------------------------

    def items(self, start):
        """Linear decode: [(pos, kind, payload)]."""
        d, p, out = self.d, start, []
        after_stop = False
        while p < len(d):
            if after_stop and p not in self.targets and p in self.dataaddrs:
                nxt = min([t for t in self.targets if t > p] + [len(d)])
                if True:
                    out.append((p, "data", d[p:nxt]))
                    p = nxt
                    continue
            b = d[p]
            if b not in (0xA2, 0x00):   # nor are an ENDIF or padding
                after_stop = False
            if char(b) is not None or b == 0x40 or b == 0x00 or b < 0x80:
                q = p + 1
                while (q < len(d) and (d[q] < 0x80 or d[q] == 0x8D)
                       and q not in self.targets
                       and not (d[q - 1] == 0 and q in self.dataaddrs)):
                    q += 1
                if any(d[p:q]):
                    after_stop = False
                out.append((p, "text", d[p:q]))
                p = q
            elif b == 0xB0:
                t = d[p + 1] | d[p + 2] << 8
                self.targets.add(t)
                out.append((p, "jump", t))
                p += 3
                after_stop = True
            elif b == 0xA6:                     # DECL target ASSIGN value
                lhs, p2 = self.expr(p + 1, stop=0xA8)
                rhs, p2 = self.expr(p2)
                if lhs[-1:] == [("op", 0xB3)] and ("op", 0xB4) in rhs:
                    self.strtables.update(self.last_addrs)
                out.append((p, "let", (lhs, rhs)))
                p = p2
            elif b in EXPR_ARGS:
                args, q = [], p + 1
                for _ in range(EXPR_ARGS[b]):
                    e, q = self.expr(q)
                    args.append(e)
                if b == 0xB5:                   # DPRINT table, index
                    self.dataaddrs.add(args[0][0][1])
                    self.strtables.add(args[0][0][1])
                out.append((p, "stmt", (b, args)))
                p = q
            elif b in VARREF:
                out.append((p, "input", (b, d[p + 1], d[p + 2])))
                p += 3
            elif b in NO_ARGS:
                out.append((p, NO_ARGS[b], None))
                p += 1
                if b in (0xB6, 0xEE):
                    after_stop = True
            elif b in TEXTARG:
                q = p + 1
                while q < len(d) and d[q] < 0x80:
                    q += 1
                out.append((p, TEXTARG[b], d[p + 1:q]))
                p = q
            elif b == 0xFF:
                out.append((p, "ident", d[p + 1]))
                p += 2
            else:
                raise Unknown("opcode %02X at $%04X" % (b, p))
        return out

    def decode(self):
        # iterate: data regions and jump targets are only known after a pass
        for _ in range(10):
            before = (len(self.targets), len(self.dataaddrs))
            items = self.items(0)
            if (len(self.targets), len(self.dataaddrs)) == before:
                break
        starts = {p for p, _, _ in items}
        data = [(p, len(x)) for p, k, x in items if k == "data"]
        bad = [t for t in self.targets if t not in starts
               and not any(a <= t < a + n for a, n in data)]
        return items, bad


def name_and_look(data):
    i = data.index(0xF1)
    j = data.index(0xF2)
    s = Script(data[:j], {})
    parts = []
    for p, kind, x in s.items(i + 1):
        if kind == "text":
            parts.append(text(x).replace("*", ""))
        elif kind == "stmt" and x[0] == 0xA1:
            parts.append(" {if %s:} " % s.render(x[1][0]))
        elif kind == "ELSE":
            parts.append(" {else:} ")
        elif kind == "ENDIF":
            parts.append(" {end} ")
    look = " ".join("".join(parts).replace("@", "").split())
    return text(data[2:i]), look


def pretty(script, items):
    """The items as readable dialogue, indented by IF and ASK nesting."""
    out = []
    stack = []      # ["if"] or ["ask", in_answer]
    labels = {t for t in script.targets}

    def ind():
        n = 0
        for f in stack:
            n += 1 if f[0] == "if" or f[1] else 0
        return n

    def emit(s, dedent=0):
        pad = "    " * max(0, ind() - dedent)
        for ln in s.split("\n"):
            out.append(pad + ln if ln.strip() else "")

    def pop_to_ask():
        while stack and stack[-1][0] != "ask":
            stack.pop()
        if not stack:
            stack.append(["ask", False])
        return stack[-1]

    started = False
    for p, kind, x in items:
        if kind == "CONVERSE":
            started = True
            continue
        if not started:
            continue
        if p in labels and kind != "data":
            emit("(L%04X)" % p)
        if kind == "text":
            if not text(x).strip():
                continue
            s = text(x).replace("@", "").replace("*", "\n")
            emit("\n".join(ln.rstrip() for ln in s.split("\n")))
        elif kind == "ASK":
            stack.append(["ask", False])
        elif kind == "ASKC":
            stack.append(["ask", False])
            emit("[answer with one of: %s]" % ", ".join(text(x)))
        elif kind == "KEYWORDS":
            f = pop_to_ask()
            f[1] = False
            emit("")
            emit(">> " + ", ".join(text(x).split(",")))
        elif kind == "ANSWER":
            pop_to_ask()[1] = True
        elif kind == "ENDANSWERS":
            pop_to_ask()
            stack.pop()
            emit("[end of answers; anything else carries on here]")
        elif kind == "stmt":
            op, args = x
            if op == 0xA1:
                emit("[if %s]" % script.render(args[0]))
                stack.append(["if"])
            else:
                name = {0xA4: "set flag", 0xA5: "clear flag",
                        0xB5: "print", 0xB9: "new object", 0xBA: "delete object",
                        0xBF: "portrait", 0xC4: "karma +", 0xC5: "karma -",
                        0xC9: "give", 0xCD: "work type",
                        0xD6: "resurrect", 0xD8: "$6 = name of",
                        0xD9: "heal",
                        0xDB: "cure"}.get(op, "op%02X" % op)
                emit("[%s %s]" % (name, ", ".join(script.render(a)
                                                   for a in args)))
        elif kind == "ELSE":
            emit("[else]", dedent=1)
        elif kind == "ENDIF":
            if stack and stack[-1][0] == "if":
                stack.pop()
        elif kind == "let":
            lhs, rhs = x
            emit("[%s = %s]" % (script.render(lhs), script.render(rhs)))
        elif kind == "input":
            op, n, t = x
            emit("[player types %s into %s%d]"
                 % ({0xF9: "text", 0xFB: "a word", 0xFC: "a number"}[op],
                    "#" if t == 0xB2 else "$", n))
        elif kind == "jump":
            emit("[goto L%04X]" % x)
        elif kind == "BYE":
            emit("[conversation ends]")
        elif kind == "SLEEP":
            emit("[falls asleep]")
        elif kind == "data":
            # tables start at the addresses the script indexes; the ones it
            # reads into a string variable or prints are 0-terminated strings
            cuts = sorted({len(x)} | {a - p for a in script.dataaddrs
                                      if p <= a < p + len(x)})
            strs = []
            for a, b in zip(cuts, cuts[1:]):
                pieces = bytes(x[a:b]).split(b"\x00")[:-1]
                if p + a in script.strtables:
                    strs += pieces
                    continue
                # a byte table with strings behind it that nothing indexes
                # directly (T118's "Mead|Ale|Wine"): keep what reads as words
                for i, s in enumerate(pieces):
                    j = len(s)
                    while j and char(s[j - 1]) is not None:
                        j -= 1
                    if i and j:
                        continue
                    s = s[j:]
                    if s[:1] and (s[0] == 0x22 or 0x41 <= s[0] <= 0x5A
                                  and any(c in b"\x01\x05\x09\x0f\x15"
                                          for c in s)):
                        strs.append(s)
            strs = [s for s in strs if text(s).strip()]
            if strs:
                emit("[table L%04X: %s]" % (p, " | ".join(
                    " ".join(text(s).replace("*", " ").replace("@", "").split())
                    for s in strs)))
    # collapse runs of blank lines
    res = []
    for ln in out:
        if ln == "" and res and res[-1] == "":
            continue
        res.append(ln)
    return res


SUBST = """\
How to read this (the meanings of $2-$7 are inferred from context):
  $2 the player's title (milord / milady)   $3 the NPC's name
  $4 the player's name                      $5 the time of day
  $6 a party member's name (set by the script, usually whoever pays)
  $7 what the player last typed             $0, $1 strings from a table
  #n a number variable
  >> kw1, kw2   what the player asks, as the script stores it (at most
                four letters); '*' is anything else
  [ ... ]       what the script does besides talking; (Lxxxx) marks a place
                that [goto Lxxxx] jumps to (file offsets)"""


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "u6-dialogue"
    os.makedirs(outdir, exist_ok=True)
    disks = []
    for tag, label, img in DISKS:
        disk = D64(paths.disk(img))
        files = [(n, disk.file(n)[0]) for n, *_ in disk.directory()]
        disks.append((tag, label, files))
    names = {}
    for _, _, files in disks:
        for n, data in files:
            names[data[1]] = name_and_look(data)[0]
    problems = 0
    for tag, label, files in disks:
        lines = ["Ultima VI (C64) -- conversations on disk %s, %s" % (tag, label),
                 "files %s-%s, %d NPCs" % (files[0][0], files[-1][0], len(files)),
                 "", SUBST, ""]
        for fname, data in files:
            name, look = name_and_look(data)
            s = Script(data, names)
            items, bad = s.decode()
            if bad:
                problems += 1
                print("%s %s: jump targets off instruction boundaries: %s"
                      % (tag, fname, ", ".join("$%04X" % t for t in bad)),
                      file=sys.stderr)
            lines += ["=" * 76,
                      "[Disk %s, %s]  %s  --  %s" % (tag, label, fname, name),
                      "Look: %s" % look, "=" * 76, ""]
            lines += pretty(s, items)
            lines.append("")
        path = os.path.join(outdir, "%s-%s.txt" % (tag, label.replace(" ", "-")))
        with open(path, "w") as f:
            f.write("\n".join(lines))
        print("%s: %d conversations -> %s" % (tag, len(files), path))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
