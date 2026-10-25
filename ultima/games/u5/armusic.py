"""Ultima V's C128 music player, relocated for an Action Replay's 8 KiB RAM.

`m` (disk 1A, $7200) is the player and its 15 songs.  On a C64 with an
Action Replay (4.2 or later) the player's code and tables go into the AR's
RAM at $8000, visible only while the glue (armusic.s) maps it in; its
writable state goes into the RAM's last page, which the AR also shows at
$DF00-$DFFF in the I/O area -- the one place the CPU can write it without
the write reaching the C64's RAM underneath; the 11 bytes it swaps zero
page into go to C64 RAM (the window is full).  The songs are loaded one at
a time, from the cart, into the RAM after the code: each is position
independent (tests/test_u5_armusic.py plays every song from another
address), so any free place will do.

With the Ultima VI EasyFlash instead of an AR (armusic.s EF_MUSIC), a
16 KiB bank of its flash holds the player and every song (relocate's
`resident`), and the window is the EasyFlash's 256 bytes of RAM at $DF00.

What the walk found (dis6502.walk from the entry points and the jump table's
targets): code $7303-$798E, a 16-word jump table at $762B, read-only tables
after the code up to $7BAD; writable: $7219-$7302, the table $7BAE-$7BC3 the
init fills, and $9FF0-$9FFA.  Nothing is self-modified.  The init also sets
a C128 KERNAL vector ($033C/$033D, KEYCHK) that a C64 does not have; those
two stores go.
"""

from ultima.sim import dis6502                                  # noqa: E402

M_LOAD = 0x7200
ENTRIES = {"init": 0x7303, "tick": 0x73BC, "mute": 0x73EC, "unmute": 0x73F5,
           "swap": 0x73DA}
CODE = (0x7303, 0x7BAE)                         # code and read-only tables
VARS = (0x7219, 0x7303)                         # -> the window, from $DF00
WTAB = (0x7BAE, 0x7BC4)                         # -> the window, after VARS
ZPS = (0x9FF0, 0x9FFB)                          # -> C64 RAM (zpsave)
JTAB = (0x762B, 16)                             # jump table: 16 words
HEADER = (0x7CA0, 0x20)                         # song count, 15 offsets
SONGS_END = 0x9FA6
INIT_HDR_LO, INIT_HDR_HI = 0x730F, 0x7313       # lda #$A0 / lda #$7C
# Addresses the code builds from two immediates: (the low byte's operand, the
# high byte's, the address).  $7661/$7667: `adc #$B8 / sta $58 / lda $59 /
# adc #$79` -- the instrument table, 8 bytes an instrument, from $79B8.
IMM_PAIRS = [(0x7662, 0x7668, 0x79B8)]
# Immediates that look like an address's high byte and are not one:
# $9A/$42 is the default timer ($429A), $7F a mask.
NOT_ADDRESSES = {0x7394, 0x753E, 0x742B}
KEYCHK = (0x7305, 0x730F)                       # lda #$B7 / sta $033C / lda #$C6 / sta $033D
# At the end of a song the player starts the selected one ($03CD) at once:
# `sta $03CC / jmp $7449`.  The JMP goes to armusic.s's ar_next instead: the
# same song again -- one that loops, as the title's second does -- still
# starts over at once (it is in the AR's RAM, it was just playing); another
# starts on the next tick, through the request path, and armusic.s's IRQ
# loads it from the cart before that tick if it is not in the AR's RAM.
# (The title walk and the ending set $03CD and leave the rest to this.)
# 20 ms later, and in the gap between two songs, where a load's mute cuts
# nothing.  (An RTS here, the first version, left a looping song ended.)
NEXT_SONG = (0x7887, bytes([0x4C, 0x49, 0x74]))
START_SONG = 0x7449                             # start song A: its $03CE, pointers

AR_BASE = 0x8000
WINDOW = 0xDF00
AR_TOP = 0x9F00                                 # the window's page, as seen at ROML
EF_TOP = 0xC000                                 # an EasyFlash bank in 16K mode


def relocate(m, zpsave, code_at, next_song, resident=False):
    """m: `m`'s bytes (no load address).  zpsave: where the 11 zero-page
    bytes go; code_at: where in the AR's RAM the code goes (armusic.s puts
    its jump table in front); next_song: where the end of a song goes
    (armusic.s ar_next, see NEXT_SONG).  Returns (the image for code_at: code, tables,
    the song header and an end offset after it; a dict of addresses).

    resident: every song stays after the header, as in `m` -- an EasyFlash
    bank holds them all (armusic.s EF_MUSIC) -- so the player's init points
    at each from the header as the original does, and a song's end keeps
    the original's JMP (next_song is not used)."""
    b = lambda a: m[a - M_LOAD]
    # the walk: every instruction, from the entries and the jump table
    code_mem = m[:CODE[1] - M_LOAD]
    jt = [b(JTAB[0] + 2 * i) | b(JTAB[0] + 2 * i + 1) << 8 for i in range(JTAB[1])]
    code = _walk(code_mem, list(ENTRIES.values()) + jt)
    lo = min(code)
    assert lo == CODE[0], hex(lo)
    code_end = max(pc + code[pc][2] for pc in code)
    assert code_end <= CODE[1] and all(CODE[0] <= t < code_end for t in jt)

    delta = code_at - CODE[0]
    win_tab = WINDOW + (VARS[1] - VARS[0])
    assert win_tab + (WTAB[1] - WTAB[0]) <= WINDOW + 0x100, "the window is full"

    def where(t):
        if CODE[0] <= t < CODE[1]:
            return t + delta
        if VARS[0] <= t < VARS[1]:
            return WINDOW + t - VARS[0]
        if WTAB[0] <= t < WTAB[1]:
            return win_tab + t - WTAB[0]
        if ZPS[0] <= t < ZPS[1]:
            return zpsave + t - ZPS[0]
        if M_LOAD <= t < 0xA000:
            raise ValueError(f"the player refers to ${t:04x}, which has no new home")
        return t

    img = bytearray(m[CODE[0] - M_LOAD:CODE[1] - M_LOAD])
    for pc, (mn, mode, n, arg) in sorted(code.items()):
        if mode in ("abs", "abx", "aby", "ind"):
            new = where(arg)
            if mode == "ind":
                assert new & 0xFF != 0xFF, "JMP ($xxFF) wraps on a 6502"
            o = pc - CODE[0]
            img[o + 1], img[o + 2] = new & 0xFF, new >> 8
    for i, t in enumerate(jt):                   # the table's targets
        o = JTAB[0] + 2 * i - CODE[0]
        img[o], img[o + 1] = (t + delta) & 0xFF, (t + delta) >> 8
    for lo_at, hi_at, addr in IMM_PAIRS:
        new = where(addr)
        assert img[lo_at - 1 - CODE[0]] == 0x69 and img[hi_at - 1 - CODE[0]] == 0x69, hex(lo_at)
        assert img[lo_at - CODE[0]] == addr & 0xFF and img[hi_at - CODE[0]] == addr >> 8
        img[lo_at - CODE[0]], img[hi_at - CODE[0]] = new & 0xFF, new >> 8
    # and nothing else that could be one: every immediate in the range of
    # the player's high bytes is either handled or known not to be an address
    handled = {INIT_HDR_LO + 1, INIT_HDR_HI + 1} | {hi for _lo, hi, _a in IMM_PAIRS}
    for pc, (mn, mode, n, arg) in code.items():
        if mode == "imm" and M_LOAD >> 8 <= arg < 0xA0 and pc + 1 not in handled:
            assert pc + 1 in NOT_ADDRESSES, f"${pc:04x}: {mn} #${arg:02x} -- an address?"
    at, was = NEXT_SONG
    assert bytes(m[at - M_LOAD:at - M_LOAD + 3]) == was
    if not resident:
        img[at - CODE[0]:at - CODE[0] + 3] = bytes([0x4C, next_song & 0xFF, next_song >> 8])
    for a in range(*KEYCHK):                     # C128 only
        img[a - CODE[0]] = 0xEA
    header_at = code_at + len(img)
    # the init reads the song header at ($50), set from two immediates
    for at, value in ((INIT_HDR_LO, header_at & 0xFF), (INIT_HDR_HI, header_at >> 8)):
        o = at - CODE[0]
        assert img[o] == 0xA9, hex(at)
        img[o + 1] = value
    head = bytes(m[HEADER[0] - M_LOAD:HEADER[0] - M_LOAD + HEADER[1]])
    end = SONGS_END - HEADER[0]                 # after the last offset: the end
    if resident:
        out = img + bytes(m[HEADER[0] - M_LOAD:SONGS_END - M_LOAD])
        top = EF_TOP
    else:
        out = img + head + bytes([end >> 8, end & 0xFF])
        top = AR_TOP
    assert code_at + len(out) < top
    return bytes(out), dict(
        entries={name: t + delta for name, t in ENTRIES.items()},
        start=START_SONG + delta,
        header=header_at, top=top,
        pointers=WINDOW + 0x7229 - VARS[0],     # song X's pointer: +2X, +2X+1
        mute=WINDOW + 0x7219 - VARS[0],         # $FF = muted
        count=WINDOW + 0x721F - VARS[0])


def songs(m):
    """[(offset of song X's data from the header, its length)] for X = 1..15."""
    h = HEADER[0] - M_LOAD
    assert m[h] == 0 and m[h + 1] == 15
    offs = [m[h + 2 + 2 * i] << 8 | m[h + 3 + 2 * i] for i in range(15)]
    ends = offs[1:] + [SONGS_END - HEADER[0]]
    return [(o, e - o) for o, e in zip(offs, ends)]


def _walk(mem, entries):
    """dis6502.walk, with the player's one indirect jump (through the jump
    table, whose targets are entries here) taken as the end of a path."""
    code, todo = {}, list(entries)
    end = M_LOAD + len(mem)
    while todo:
        pc = todo.pop()
        while M_LOAD <= pc < end and pc not in code:
            ins = dis6502.decode(mem, M_LOAD, pc)
            if ins is None:
                raise ValueError(f"undocumented opcode at ${pc:04x}")
            code[pc] = ins
            mn, mode, n, arg = ins
            if mode == "rel":
                todo.append((pc + 2 + (arg - 256 if arg & 0x80 else arg)) & 0xFFFF)
            if mn == "jsr":
                todo.append(arg)
            if mn == "jmp":
                if mode == "abs":
                    todo.append(arg)
                break
            if mn in ("rts", "rti", "brk"):
                break
            pc += n
    return code
