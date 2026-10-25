"""Five of Ultima III Gold's enhancements, in the tapecart build.

Ultima III Gold (MagerValp, 2007) is a fan patch of the C64 Ultima III.  Five
of its changes are taken; docs/reversing-notes/u3-gold.md says what each is
and where:

  * faster tile plotting: SHPS (the tiles), TEXT (the font) and SUBS' 16
    animation frames reordered into C64 bitmap order -- pure permutations of
    the original bytes, computed here from the original disks -- and the code
    that draws them: UPDT's map blitter, SUBS' glyph printer and animations,
    and BOOT's menu map;
  * the save system: only Q writes the saved game; entering a town, leaving
    it, a death, the whirlpool cache the state in RAM under the KERNAL
    ($E000-$F2FF) instead of writing it (ULT3);
  * ask before a map exit throws the party out to Sosaria (ULT3);
  * a default character, keys 1-4 (0: ask, as before) (ULT3);
  * DEL deletes in name entry (BOOT: it was '+').

Gold's code is taken from the Gold disk itself, unpacked on the host as the
disk unpacks itself (goldunpack.py: the game image right after Gold's $BE00,
before BOOT applies any trainer; updt, boot, shp3).  It used to come from the
analysis's unpacked copy, whose game image was a RAM dump from VICE; the
host unpack is byte-identical to it on every range used here.  Every unit is checked to differ from the original only
where the analysis says, so nothing of Gold's that was not asked for -- the
trainers, the fastloader, the keyboard remapping at run time, the dagger
shop -- comes along unnoticed.  (ULT3 carries the trainers' tail code, but
nothing reaches it: their hooks are patches Gold's BOOT applies per answer,
not in this image.)

Gold's BOOT cannot be used as it is: it drops the module loads the cart's
driver serves.  So the original BOOT keeps them and gets Gold's menu block
($1369-$14F1 of the original: one routine where there were a blitter, a frame
routine and three animations), moved up by the $72 Gold's BOOT is shifted
down, its two callers ($114B, $114E) repointed, and the delete key.
"""
import hashlib

from ultima import paths

_unpacked = {}


def _read(name):
    """A file of Gold's, decrunched ("boot.prg", "updt.prg", "shp3.prg"), or
    "game_after_unpack.bin", the 64 KiB after $BE00."""
    if not _unpacked:
        from ultima.games.u3 import goldunpack
        _unpacked.update(goldunpack.unpack(paths.disk("u3gold")))

    key = "game" if name == "game_after_unpack.bin" else name.removesuffix(".prg")
    return _unpacked[key]


# ---- the data: permutations --------------------------------------------------
def shps(orig):
    """64 tiles of 16x16: from 16 rows of 128 bytes (row r, tile t, byte b at
    r*$80 + t*2 + b) to the bitmap order Gold's blitter copies in one go:
    (r>=8)*$400 + t*16 + b*8 + (r&7)."""
    out = bytearray(len(orig))
    for r in range(16):
        for t in range(64):
            for b in range(2):
                out[(r >= 8) * 0x400 + t * 16 + b * 8 + (r & 7)] = orig[r * 0x80 + t * 2 + b]
    return bytes(out)


def text(orig):
    """The font: from 8 rows of 128 characters (r*$80 + c) to 8 bytes a
    character (c*8 + r)."""
    out = bytearray(len(orig))
    for r in range(8):
        for c in range(128):
            out[c * 8 + r] = orig[r * 0x80 + c]
    return bytes(out)


def frames(orig):
    """SUBS' 16 animation frames at $4100-$42FF (i*32 + r*2 + b) to
    (r>=8)*$100 + i*16 + b*8 + (r&7)."""
    out = bytearray(len(orig))
    for i in range(16):
        for r in range(16):
            for b in range(2):
                out[(r >= 8) * 0x100 + i * 16 + b * 8 + (r & 7)] = orig[i * 32 + r * 2 + b]
    return bytes(out)


# ---- the code ----------------------------------------------------------------
def _only(orig, new, base, ranges, what):
    """new equals orig outside `ranges` [(lo, hi)), the addresses Gold changed."""
    assert len(orig) == len(new), (what, len(orig), len(new))
    for i, (a, b) in enumerate(zip(orig, new)):
        addr = base + i
        if a != b and not any(lo <= addr < hi for lo, hi in ranges):
            raise SystemExit(f"Ultima III Gold {what}: an undocumented change at ${addr:04x}")


# ULT3: the dispatchers, the twelve "which player?" calls, the save system, the
# dungeon dispatcher and the tail (GOLD-ANALYSIS.md §4, §5.3, §5.4)
ULT3_CHANGES = [(0x50C3, 0x50E1),
                (0x530B, 0x530D), (0x5AD2, 0x5AD4), (0x5F64, 0x5F66), (0x5FA6, 0x5FA8),
                (0x6106, 0x6108), (0x614F, 0x6151), (0x63FD, 0x63FF), (0x65E9, 0x65EB),
                (0x668D, 0x668F), (0x6832, 0x6834), (0x69DA, 0x69DC), (0x8D8D, 0x8D8F),
                (0x649F, 0x64AA), (0x64CB, 0x64E1), (0x64F8, 0x64FB), (0x6DA2, 0x6DB5),
                (0x7727, 0x7732), (0x774D, 0x7759),
                (0x8B7F, 0x8BA5),
                (0x922F, 0x9400)]
# SUBS: the frames, the glyph printer, the animations and their jump table
# entries (§3)
# (the analysis gives the water animation as $491B-$495D; it runs to $4962)
SUBS_CHANGES = [(0x4100, 0x4300), (0x46D8, 0x46DB), (0x48CE, 0x4963), (0x4A87, 0x4AA3),
                (0x4ABE, 0x4C19), (0x4ECF, 0x4F00)]
# UPDT: the blitter and the saved/restored zero page (§3)
UPDT_CHANGES = [(0xCB01, 0xCBE8), (0xCC66, 0xCC94)]

# BOOT (original addresses): Gold's block is Gold $12F7-$1480, i.e. original
# $1369-$14F2; it references itself (its variables and self-modified
# operands, Gold $1336-$1407) and SUBS.  Gold's BOOT is the original shifted
# down by $72 from Gold $1060 on.
BOOT_ADDR = 0x1000
BOOT_SHIFT = 0x72
BOOT_BLOCK = (0x1369, 0x14F2)           # original addresses
BOOT_CODE_END = 0x1401                  # Gold: code to $1400, then data
BOOT_CALLERS = (0x114B, 0x114E)         # JSR $144B, the frame routine
BOOT_DELETE = 0x1B2E                    # CMP #$AB ('+') -> #$94 (DEL)
BOOT_TABLE = (0x1407, 0x1447)           # Gold: the 64-byte tile colour table


def boot(orig):
    gb = _read("boot.prg")
    assert gb[:2] == bytes([0x00, 0x10]), "Gold's BOOT does not load at $1000"
    gb = gb[2:]
    out = bytearray(orig)
    lo, hi = BOOT_BLOCK
    g0, g1 = lo - BOOT_SHIFT, hi - BOOT_SHIFT
    block = bytearray(gb[g0 - BOOT_ADDR:g1 - BOOT_ADDR])
    # relocate: walk Gold's code (to BOOT_CODE_END) and move every absolute
    # operand that points into Gold's shifted BOOT up by the shift
    pc = g0
    while pc < BOOT_CODE_END:
        op = block[pc - g0]
        n = _len(op)
        if n == 3:
            t = block[pc - g0 + 1] | block[pc - g0 + 2] << 8
            if 0x1060 <= t < 0x1F00:
                assert g0 <= t < g1, f"Gold's menu block reaches out to ${t:04x} at ${pc:04x}"
                t += BOOT_SHIFT
                block[pc - g0 + 1:pc - g0 + 3] = bytes([t & 0xFF, t >> 8])
        pc += n
    assert pc == BOOT_CODE_END, "Gold's menu code does not end on an instruction boundary"
    # the tile colour table is the original's, only moved
    t0, t1 = BOOT_TABLE
    assert bytes(block[t0 - g0:t1 - g0]) == bytes(orig[0x1461 - BOOT_ADDR:0x14A1 - BOOT_ADDR])
    out[lo - BOOT_ADDR:hi - BOOT_ADDR] = block
    for at in BOOT_CALLERS:                 # JSR $144B -> the block's one entry
        o = at - BOOT_ADDR
        assert bytes(out[o:o + 3]) == bytes([0x20, 0x4B, 0x14]), f"BOOT ${at:04x}"
        out[o + 1:o + 3] = bytes([lo & 0xFF, lo >> 8])
    o = BOOT_DELETE - BOOT_ADDR
    assert out[o] == 0xAB, "BOOT's delete key test moved"
    out[o] = 0x94
    return bytes(out)


def _len(op):
    """6502 instruction length (the documented opcodes Gold's code uses)."""
    three = {0x0D, 0x0E, 0x19, 0x1D, 0x1E, 0x20, 0x2C, 0x2D, 0x2E, 0x39, 0x3D, 0x3E, 0x4C,
             0x4D, 0x4E, 0x59, 0x5D, 0x5E, 0x6C, 0x6D, 0x6E, 0x79, 0x7D, 0x7E, 0x8C, 0x8D,
             0x8E, 0x99, 0x9D, 0xAC, 0xAD, 0xAE, 0xB9, 0xBC, 0xBD, 0xBE, 0xCC, 0xCD, 0xCE,
             0xD9, 0xDD, 0xDE, 0xEC, 0xED, 0xEE, 0xF9, 0xFD, 0xFE}
    one = {0x00, 0x08, 0x0A, 0x18, 0x28, 0x2A, 0x38, 0x40, 0x48, 0x4A, 0x58, 0x60, 0x68,
           0x6A, 0x78, 0x88, 0x8A, 0x98, 0x9A, 0xA8, 0xAA, 0xB8, 0xBA, 0xC8, 0xCA, 0xD8,
           0xE8, 0xEA, 0xF8}
    return 3 if op in three else 1 if op in one else 2


def apply(name, data):
    """The unit `name` (a catalog entry's bytes, as build.py read them) with
    Gold's changes, or unchanged."""
    if name == "SHPS":
        new = shps(data)
        assert new == _game()[0x0800:0x0800 + len(new)], "SHPS is not Gold's permutation"
        return new
    if name == "TEXT":
        new = text(data)
        assert new == _game()[0xB400:0xB400 + len(new)], "TEXT is not Gold's permutation"
        return new
    if name == "SUBS":
        new = bytearray(_game()[0x4100:0x4100 + len(data)])
        _only(data, new, 0x4100, SUBS_CHANGES, "SUBS")
        assert bytes(new[:0x200]) == frames(data[:0x200]), "SUBS' frames are not Gold's permutation"
        return bytes(new)
    if name == "UPDT":
        gu = _read("updt.prg")
        assert gu[:2] == bytes([0x00, 0xCA])
        new = gu[2:] + data[len(gu) - 2:]       # Gold's file is shorter: the rest as it was
        _only(data, new, 0xCA00, UPDT_CHANGES, "UPDT")
        return new
    if name == "ULT3":
        new = _game()[0x5000:0x5000 + len(data)]
        _only(data, new, 0x5000, ULT3_CHANGES, "ULT3")
        return new
    if name == "BOOT":
        return boot(data)
    if name == "SHP3":
        return shp3(data)
    return data


# The dagger shop (docs/reversing-notes/u3-gold.md): SHP3,
# the weapon shop at $9400, asks "AMOUNT-" for daggers and buys that many.
# $9502's ADC #1 becomes ADC $977D, the count, which moves the rest of the
# file up a byte -- hence Gold's many +1 operands -- and the new code is in
# the old file's dead tail.  So the unit is taken whole; what is checked is
# that it loads where the original does, fits its blocks, and calls nothing
# out of itself that the original does not but jump-table entries: SUBS'
# $46DE and $46EA (the number input) and the DOS module's $B809, all of
# which the analysis lists and our build leaves in place.
SHP3_NEW_CALLS = {0x46DE, 0x46EA, 0xB809}


def _calls_out(data, base):
    """Absolute JSR/JMP targets outside the unit, by a linear scan (text and
    tables give a few spurious ones on both sides alike)."""
    out, i = set(), 0
    while i + 2 < len(data):
        if data[i] in (0x20, 0x4C):
            t = data[i + 1] | data[i + 2] << 8
            if not base <= t < base + len(data):
                out.add(t)
        i += 1
    return out


def shp3(orig):
    g = _read("shp3.prg")
    assert g[:2] == bytes([0x00, 0x94]), "Gold's SHP3 does not load at $9400"
    new = g[2:]
    assert len(new) <= len(orig), "Gold's SHP3 is longer than the original's blocks"
    new = new + orig[len(new):]
    extra = _calls_out(new[:len(g) - 2], 0x9400) - _calls_out(orig, 0x9400)
    assert extra == SHP3_NEW_CALLS, f"Gold's SHP3 calls out to {sorted(map(hex, extra))}"
    return bytes(new)


_game_cache = []


def _game():
    if not _game_cache:
        g = _read("game_after_unpack.bin")
        assert len(g) == 0x10000
        _game_cache.append(g)
    return _game_cache[0]


def fingerprint():
    """The Gold sources' hashes (the build prints them; tests pin them)."""
    return {n: hashlib.sha1(_read(n)).hexdigest()[:12]
            for n in ("game_after_unpack.bin", "updt.prg", "boot.prg", "shp3.prg")}
