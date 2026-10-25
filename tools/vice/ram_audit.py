#!/usr/bin/env python3
"""Ultima 6: RAM the game does not use -- the evidence, address by address.

    python -m tools.vice.ram_audit corpus
    python -m tools.vice.ram_audit pristine DUMP.bin ...   never written since power-on
    python -m tools.vice.ram_audit zp MM.bmp ...           zero page nothing names
    python -m tools.vice.ram_audit cold MM.bmp ...         game code no session ran
    python -m tools.vice.ram_audit dead MM.bmp ...         a LEAD only: see its caveat
    python -m tools.vice.ram_audit report MM.bmp ...       every untouched run, with its references

Two kinds of evidence, which fail in different ways:

  static   every absolute address the game's code names.  The corpus is all
           the code that can run in play: `game` ($0200-$437E, from 3B) and
           every overlay, from both Surface (1A) and Dungeon (1B): the three
           large ones at $C000 (T3 Cast, T4 Talk, T5 combat), the 18 small
           ones of the table at $2C80 (overlay $34 goes to $D400) and the
           object-file loader's data are not code.  Each piece is
           disassembled linearly by da65 (a desync in strings and tables
           only adds false references, never loses a real one: a safe
           superset), and a reference is any instruction with an absolute,
           absolute-indexed or indirect operand -- plus, for pages, the
           immediate high bytes that build pointers (listed separately,
           being noisy).  Pointers kept in tables are not seen: the
           tables are read from the original and listed in POINTER_TABLES.
  dynamic  VICE's memmap (memmap.py) over the sessions u6_ram_map.py ran:
           an address with no RAM read, write or execute in all of them.
           Blind to everything the sessions did not do, and to $D000-$DFFF.

The report merges both, per address, and prints runs by grade:
  A  no static reference and never touched
  B  no static reference, never touched except written (loaded, not read)
  C  never touched, but referenced (code that ran in no session)
  D  no static reference; the session cannot say (the RAM under I/O)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from ultima import paths

from ultima.games.u6 import build as u6

from tools.vice import memmap

BUILD = paths.BUILD
DA65 = "da65"

# the overlay table at $2C80: (X, first sector's track, sector, sector count, load page)
LARGE = {"T3 Cast": (3, 9, 12), "T4 Talk": (4, 9, 12), "T5 combat": (5, 9, 12)}


def corpus():
    """[(name, load address, bytes)] -- everything that runs in play."""
    d3b = u6.D64(u6.disk_path("3B"))
    game, _ = d3b.file("GAME")
    out = [("game", 0x0200, bytes(game[2:]))]
    for tag in ("1A", "1B"):
        d = u6.D64(u6.disk_path(tag))
        def read(track, sector, count):
            data = bytearray()
            for i in range(count):
                data += d.sector(track, sector + i)
            return bytes(data)
        for name, (t, s, n) in LARGE.items():
            out.append((f"{tag} {name}", 0xC000, read(t, s, n)))
        table = game[2 + 0x2C80 - 0x200:2 + 0x2CC8 - 0x200]
        for i in range(18):
            t, s, n, page = table[i * 4:i * 4 + 4]
            out.append((f"{tag} small ${i * 4:02x}", page << 8, read(t, s, n)))
    return out


def disassemble(name, origin, data):
    path = os.path.join(BUILD, "audit_" + re.sub(r"\W+", "_", name))
    with open(path + ".bin", "wb") as fh:
        fh.write(data)
    out = subprocess.run([DA65, "-S", f"0x{origin:x}", "--cpu", "6502", "-o", path + ".s", path + ".bin"],
                         capture_output=True, text=True)
    return Path(path + ".s").read_text()


OPS = "adc and asl bit cmp cpx cpy dec eor inc jmp jsr lda ldx ldy lsr ora rol ror sbc sta stx sty".split()
BRANCH = re.compile(r"^(?:L[0-9A-F]{4}:)?\s+b(?:cc|cs|eq|mi|ne|pl|vc|vs)\s+L([0-9A-F]{4})\s*$", re.M)
INSTR = re.compile(r"^(?:L[0-9A-F]{4}:)?\s+(%s)\s+\(?(?:\$([0-9A-F]{4})|L([0-9A-F]{4}))(?:\+(\d+))?(,[xy])?\)?(,[xy])?\s*$"
                   % "|".join(OPS), re.M)
IMM = re.compile(r"^(?:L[0-9A-F]{4}:)?\s+(lda|ldx|ldy|cmp|cpx|cpy|adc|sbc|ora|and|eor)\s+#\$([0-9A-F]{2})\s*$", re.M)


def words(data, origin):
    """{value: [places]} for every little-endian 16-bit word of a piece -- the
    pointers in tables, and (minus one) the RTS-trick's."""
    out = {}
    for i in range(len(data) - 1):
        out.setdefault(data[i] | data[i + 1] << 8, []).append(origin + i)
    return out


ZP = re.compile(r"^(?:L[0-9A-F]{4}:)?\s+(?:%s|b..|inx|iny)?\s*(\(?)(?:\$([0-9A-F]{2})|L(00[0-9A-F]{2}))(,x\)|\),y|,x|,y)?\s*$" % "|".join(OPS), re.M)
ZPLINE = re.compile(r"^(?:L[0-9A-F]{4}:)?\s+(%s)\s+(\(?)(?:\$([0-9A-F]{2})|L(00[0-9A-F]{2}))(,x\)|\),y|,x|,y)?\s*$" % "|".join(OPS), re.M)


def zero_page():
    """{address: [(piece, mnemonic, mode)]} for every zero-page operand of the corpus."""
    out = {}
    for name, origin, data in corpus():
        text = disassemble(name, origin, data)
        for m in ZPLINE.finditer(text):
            a = int(m.group(3) or m.group(4), 16)
            mode = (m.group(2) or "") + (m.group(5) or "")
            out.setdefault(a, []).append((name, m.group(1), mode or "zp"))
    return out


def refs():
    """{address: [(piece, mnemonic, indexed)]} for every absolute operand; and {hi byte: n} immediates."""
    by_addr, imm = {}, {}
    refs.branches, refs.words = {}, {}
    for name, origin, data in corpus():
        text = disassemble(name, origin, data)
        for m in INSTR.finditer(text):
            a = int(m.group(2) or m.group(3), 16) + int(m.group(4) or 0)
            indexed = bool(m.group(5) or m.group(6))
            by_addr.setdefault(a, []).append((name, m.group(1), indexed))
        for m in BRANCH.finditer(text):
            refs.branches.setdefault(int(m.group(1), 16), []).append(name)
        for v, places in words(data, origin).items():
            refs.words.setdefault(v, []).extend((name, p) for p in places)
        for m in IMM.finditer(text):
            imm[int(m.group(2), 16)] = imm.get(int(m.group(2), 16), 0) + 1
    return by_addr, imm


def windows(by_addr):
    """(named, window): addresses some instruction names, and those a table
    indexed from a named base could reach (up to 255 on)."""
    named, window = set(), set()
    for a, uses in by_addr.items():
        named.add(a)
        if any(idx for _n, _m, idx in uses):
            window.update(range(a, min(a + 256, 0x10000)))
    return named, window


def grade_runs(by_addr, access, lo=0x0200, hi=0xFFF9, minlen=8, strict=True):
    """Runs of addresses with the same grade; access None = no dynamic evidence.
    strict: a table's whole 256-byte window counts as referenced."""
    named, window = windows(by_addr)
    runs, cur = [], None
    for a in range(lo, hi + 1):
        static = a in named or (strict and a in window)
        if access is None:
            g = "D" if not static else "-"
        else:
            bits = access[a]
            ram = bits & memmap.RAM_ANY
            if 0xD000 <= a <= 0xDFFF:
                g = "D" if not static else "-"
            elif not static and not ram:
                g = "A"
            elif not static and not (bits & (memmap.RAM_R | memmap.RAM_X)):
                g = "B"
            elif static and not ram:
                g = "C"
            else:
                g = "-"
        if cur and cur[2] == g:
            cur[1] = a
        else:
            cur = [a, a, g]
            runs.append(cur)
    return [(a, b, g) for a, b, g in runs if g != "-" and b - a + 1 >= minlen]


# what each part of RAM holds in play (the U6 memory map, section 1); name, first, last
LAYOUT = [
    ("page 1: sprite sort buckets, number entry, stack", 0x0100, 0x01FF),
    ("game: parameter block, jump table, init, code, tables", 0x0200, 0x437E),
    ("chunk bank bits of the window", 0x4380, 0x43FF),
    ("chunk index map", 0x4400, 0x47FF),
    ("tile planes 1-3", 0x4800, 0x53FF),
    ("save state (T6 S9-20)", 0x5400, 0x5FFF),
    ("TILES (tiles 0-255, then objects)", 0x6000, 0x9FFF),
    ("COLORS", 0xA000, 0xA1FF),
    ("TILEFLAGS and sprite tables", 0xA200, 0xA7FF),
    ("object pool", 0xA800, 0xBFFF),
    ("overlay area", 0xC000, 0xCBFF),
    ("colour matrix", 0xCC00, 0xCFE7),
    ("matrix tail, sprite pointers", 0xCFE8, 0xCFFF),
    ("CHARS (font)", 0xD000, 0xD3FF),
    ("overlay $34 and loader buffers", 0xD400, 0xD7FF),
    ("sprite images, two halves", 0xD800, 0xDFFF),
    ("bitmap", 0xE000, 0xFF3F),
    ("sprite blocks $FD, $FE", 0xFF40, 0xFFBF),
    ("line buffer, load temporaries", 0xFFC0, 0xFFF9),
]


def region(a):
    for name, lo, hi in LAYOUT:
        if lo <= a <= hi:
            return name
    return "?"


def content(ram, a, b):
    """A word for what the bytes of a run are, from a RAM image."""
    seg = bytes(ram[a:b + 1])
    if len(set(seg)) == 1:
        return f"all ${seg[0]:02x}"
    if len(set(seg[0::2])) == 1 and len(set(seg[1::2])) == 1:
        return f"${seg[0]:02x},${seg[1]:02x} repeating"
    return "data/code"


LINE = re.compile(r"^\s*(?:L[0-9A-F]{4}:)?\s*(\.byte|\.word|\.addr|[a-z]{3})\s+(.*?)\s*;\s*([0-9A-F]{4})((?: [0-9A-F]{2})+)")
ENDS = ("rts", "rti", "jmp")


def instructions(data, origin):
    """[(address, length, mnemonic, operand)] from da65's linear sweep."""
    path = os.path.join(BUILD, "audit_sweep")
    with open(path + ".bin", "wb") as fh:
        fh.write(data)
    subprocess.run([DA65, "-S", f"0x{origin:x}", "--cpu", "6502", "--comments", "4", "-o", path + ".s",
                    path + ".bin"], check=True, capture_output=True)
    out = []
    for line in Path(path + ".s").read_text().splitlines():
        m = LINE.match(line)
        if m:
            out.append((int(m.group(3), 16), len(m.group(4).split()), m.group(1), m.group(2)))
    return out


def dead_blocks(data, origin, access):
    """Blocks of straight-line code (da65's sweep; a block ends at RTS/RTI/JMP)
    that no session executed or read, whose first byte nothing jumps, branches
    or points to, and none of whose bytes any instruction names.  Returns
    [(first, last, entry_words)] -- entry_words: how many table words equal the
    entry (or entry - 1), the RTS trick, which would make it live."""
    by_addr, _imm = refs()
    named, window = windows(by_addr)
    jump_targets = {a for a, uses in by_addr.items() if any(m in ("jsr", "jmp") for _n, m, _i in uses)}
    ins = instructions(data, origin)
    blocks, cur = [], []
    for item in ins:
        cur.append(item)
        if item[2] in ENDS:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out = []
    for blk in blocks:
        first = blk[0][0]
        last = blk[-1][0] + blk[-1][1] - 1
        span = range(first, last + 1)
        if any(access[a] & memmap.RAM_ANY for a in span):
            continue
        if first in jump_targets or first in refs.branches:
            continue
        if any(a in named or a in window for a in span):
            continue
        if any(a in refs.branches or a in jump_targets for a in span):
            continue
        ew = len(refs.words.get(first, [])) + len(refs.words.get((first - 1) & 0xFFFF, []))
        out.append((first, last, ew))
    return out


def power_on(a):
    """VICE's power-on RAM: four $00 then four $FF, from $0002 on."""
    return 0x00 if ((a - 2) & 4) == 0 else 0xFF


def pristine(ram):
    """[bool] -- the byte still holds its power-on value: nothing has written it
    since the machine was switched on (the boot, the loads and the game
    included).  Real hardware's RAM starts differently, so a game that read
    such a byte would be reading noise: the original cannot depend on one."""
    return [ram[a] == power_on(a) for a in range(65536)]


def pristine_runs(rams, minlen=8, lo=0x0200, hi=0xFFF9):
    """Runs still pristine in all the images."""
    flags = [pristine(r) for r in rams]
    runs, cur = [], None
    for a in range(lo, hi + 1):
        if all(f[a] for f in flags):
            if cur:
                cur[1] = a
            else:
                cur = [a, a]
                runs.append(cur)
        else:
            cur = None
    return [(x, y) for x, y in runs if y - x + 1 >= minlen]


def cold_blocks(data, origin, access, minlen=24):
    """Blocks of game code (as dead_blocks) that no session executed or read,
    with how they are entered: [(first, last, callers, branches_in)] --
    callers: JSR/JMP sites naming the first byte; branches_in: branch or
    jump targets inside the block other than its first byte (an entry
    elsewhere would make moving it harder).  These are the candidates to
    move out of RAM into flash and fetch when used."""
    by_addr, _imm = refs()
    ins = instructions(data, origin)
    blocks, cur = [], []
    for item in ins:
        cur.append(item)
        if item[2] in ENDS:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out = []
    for blk in blocks:
        first = blk[0][0]
        last = blk[-1][0] + blk[-1][1] - 1
        if last - first + 1 < minlen:
            continue
        if any(access[a] & (memmap.RAM_X | memmap.RAM_R) for a in range(first, last + 1)):
            continue
        callers = sum(1 for n, m, _i in by_addr.get(first, []) if m in ("jsr", "jmp"))
        inside = sum(len(by_addr[a]) for a in range(first + 1, last + 1) if a in by_addr) + \
            sum(len(refs.branches[a]) for a in range(first + 1, last + 1) if a in refs.branches)
        out.append((first, last, callers, inside))
    return out


def untouched_runs(access, lo=0x0200, hi=0xFFF9, minlen=4):
    """Runs never read, written or executed as RAM (outside the I/O-ambiguous $D000-$DFFF)."""
    runs, cur = [], None
    for addr in range(lo, hi + 1):
        free = not (access[addr] & memmap.RAM_ANY) and not 0xD000 <= addr <= 0xDFFF
        if free:
            if cur:
                cur[1] = addr
            else:
                cur = [addr, addr]
                runs.append(cur)
        else:
            cur = None
    return [(x, y) for x, y in runs if y - x + 1 >= minlen]


def report(access, ram, minlen=8):
    """Every run the sessions never touched, with what else is known about it."""
    by_addr, _imm = refs()
    named, window = windows(by_addr)
    rows = []
    for lo, hi in untouched_runs(access, minlen=minlen):
        inside = [a for a in range(lo, hi + 1) if a in named]
        win = [a for a in range(lo, hi + 1) if a in window and a not in named]
        br = [a for a in range(lo, hi + 1) if a in refs.branches]
        wd = sorted({v for v in range(lo, hi + 2) if v in refs.words})
        who = sorted({n.split()[-1] if n.startswith("1") else n for a in inside for n, _m, _i in by_addr[a]})
        rows.append((lo, hi, region(lo), content(ram, lo, hi), len(inside), len(win), len(br), len(wd), who))
    return rows


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "report"
    by_addr, imm = refs()
    if what == "corpus":
        for name, origin, data in corpus():
            print(f"{name:22s} ${origin:04x}-${origin + len(data) - 1:04x} {len(data)}")
        return
    if what == "cold":
        access = None
        for path in sys.argv[2:]:
            bmp = memmap.read_bmp(path)
            access = bmp if access is None else bytearray(x | y for x, y in zip(access, bmp))
        game = corpus()[0]
        total = 0
        print("cold blocks of game (never executed or read in the sessions):")
        for first, last, callers, inside in sorted(cold_blocks(game[2], game[1], access), key=lambda t: t[0] - t[1]):
            total += last - first + 1
            print(f"${first:04x}-${last:04x} {last - first + 1:5d}  called from {callers} sites, {inside} references inside")
        print("total", total)
        return
    if what == "pristine":
        rams = [Path(p).read_bytes() for p in sys.argv[2:]]
        by_addr, _imm = refs()
        named, window = windows(by_addr)
        total = 0
        print(f"{'run':15s} {'bytes':>5s}  named table  region")
        for lo, hi in pristine_runs(rams):
            n = sum(1 for a in range(lo, hi + 1) if a in named)
            w = sum(1 for a in range(lo, hi + 1) if a in window and a not in named)
            total += hi - lo + 1
            print(f"${lo:04x}-${hi:04x} {hi - lo + 1:7d}  {n:5d} {w:5d}  {region(lo)}")
        print("total", total)
        return
    if what == "zp":
        zp = zero_page()
        named = set(zp)
        window = set()
        for a, uses in zp.items():
            for _n, _m, mode in uses:
                if mode in (",x", ",y", ",x)"):
                    window.update(range(a, 0x100))
                if mode.startswith("(") or mode == "(":
                    named.add(a + 1)
        access = None
        for path in sys.argv[2:]:
            bmp = memmap.read_bmp(path)
            access = bmp if access is None else bytearray(x | y for x, y in zip(access, bmp))
        print("zero page: addresses no instruction of the corpus names (direct or by indirect pair):")
        free = [a for a in range(0x02, 0x100) if a not in named]
        print(" ".join(f"${a:02x}" for a in free))
        print("also outside every indexed window:", " ".join(f"${a:02x}" for a in free if a not in window))
        print("and never touched in the sessions:", " ".join(f"${a:02x}" for a in free
              if a not in window and (access is None or not access[a] & memmap.RAM_ANY)))
        return
    if what == "dead":
        access = None
        for path in sys.argv[2:]:
            bmp = memmap.read_bmp(path)
            access = bmp if access is None else bytearray(x | y for x, y in zip(access, bmp))
        print("CAVEAT: routines reached through split tables (a low-byte table and a high-byte table,"
              " like $422F/$4242) are invisible to this scan; $37D4, the one block it finds with no"
              " pointer at all, is the handler of actor type $81.  A lead, not a proof.")
        game = corpus()[0]
        for first, last, ew in dead_blocks(game[2], game[1], access):
            print(f"${first:04x}-${last:04x} {last - first + 1:5d}  entry words: {ew}")
        return
    if what == "refs":
        print(len(by_addr), "distinct addresses referenced")
        return
    access = None
    for path in sys.argv[2:]:
        bmp = memmap.read_bmp(path)
        access = bmp if access is None else bytearray(x | y for x, y in zip(access, bmp))
    with open(os.path.join(paths.ROOT, "tests", "data", "u6_castle_0.bin"), "rb") as fh:
        ram = fh.read()
    print(f"{'run':15s} {'bytes':>5s}  {'named':>5s} {'table':>5s} {'branch':>6s} {'word':>5s}  region / content")
    for lo, hi, reg, what, n, win, br, wd, who in report(access, ram):
        print(f"${lo:04x}-${hi:04x} {hi - lo + 1:7d}  {n:5d} {win:5d} {br:6d} {wd:5d}  {reg}; {what}")


if __name__ == "__main__":
    main()
