#!/usr/bin/env python3
"""Build the Ultima 3 flash layout.

Each catalog entry is stored as its own page-aligned unit and the in-memory
catalog is rewritten so the entry's start-block field is a flash page number
instead of a disk block.  catalog_find, the ^D parser and all 44 call sites
are untouched, and no "which disk is inserted" notion is needed: the catalog
entry already identifies its content uniquely.

The two disks used to be stored whole, which cost 345 KiB.  The catalog only
ever references 606 of their 1366 blocks -- the highest block used is 284 on
disk A and 381 on disk B, so more than half of each disk is filler that is
never read -- and no two entries share a block.  One unit per entry is
therefore both smaller (152 KiB) and exactly equivalent.  It is also what
compression would need later, since a unit is the thing you would crunch.

The five writable entries go to their own save slots, so a save never means
read-modify-writing a neighbour.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths

from ultima.disks.d64 import D64
from ultima.flash.layout import Layout, image_from
from ultima.flash import zx
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.flash import regions
from ultima.launcher import xfer

from ultima.games.u3 import gold                             # noqa: E402
from ultima.pin import Pin

DISK_A = paths.disk("u3a")
DISK_B = paths.disk("u3b")

BUILD = paths.BUILD

CAT_ADDR = 0xB000
CAT_BLOCK, CAT_BLOCKS = 100, 4      # catalog: disk A blocks 100-103 -> $B000
DOS_BLOCK, DOS_BLOCKS = 92, 4       # DOS module: blocks 92-95      -> $B800
DOS_ADDR = 0xB800
DRIVER_ADDR = 0xBC00
DECODER_ADDR = 0xC500            # the U3 map lists $C500-$C9FF as free
EXOD_BLOCK, EXOD_BLOCKS = 5, 87     # intro, $3000-$86FF
INIT_ADDR = 0x0200                  # init stub; it ends with JMP $8220
CREDITS_ADDR, CREDITS_END = 0x0825, 0x0910   # the boot PRG's title screen

DOS_TRANSFER = 0xBA48               # patched to JMP DRIVER_ADDR
ENTRY_COUNT = 94
ENTRY_SIZE = 8
F_WRITABLE = 0x80
F_COMP = 0x80                    # bit 15 of the catalog start-page field;
                                 # the length byte has no free bit (EXOD is 87
                                 # blocks, which already has bit 6 set)
SAVE_SLOT = 2 * regions.ERASE_BLOCK  # SOSA is 16 blocks; +1 header page > 4 KiB
SAVE_MAGIC = bytes([0xA5, 0x5A])

# The ten program files live on disk A, everything else on disk B.
# Derived from the catalog (docs/reversing-notes/u3.md); asserted below.
DISK_A_FILES = {"EXOD", "TEXT", "SHPS", "DEMO", "ULT3",
                "DDAT", "BOOT", "SUBS", "MUSI", "COPY"}
WRITABLE = ["SOSA", "SOSM", "ROST", "PLRS", "PRTY"]

# ---------------------------------------------------------------------------
# The launcher's options (patches.py, asm/patch.s), all in ULT3 ($5000, the
# engine, loaded once by BOOT).  From the U3 research, checked against a
# disassembly:
#   food: $73D1 LDA #$10 / JSR $7463 -- 0.10 food per living member per
#         turn, the only caller of the food routine; 0.00 instead.
#   pass: three keyboard timeouts.  Surface and towns: $5096 DEC $22 / BEQ
#         $50E9 ("Pass"), the branch made a no-op.  Combat: $7FF4 DEC $22 /
#         BNE $7FFD / LDA #$A0 (a space) / JMP $8007, the JMP sent to the key
#         read at $7FFD instead.  Dungeon: $8B66 DEC $22 / BNE / JMP $8BF5
#         ("PASS"), sent to the key read at $8B6D.
OPTION_PATCHES = [
    patches.Patch(patches.FOOD, 0x73D1, bytes.fromhex("a910206374"),
                  bytes.fromhex("a900206374"), "food"),
    patches.Patch(patches.PASS, 0x5096, bytes.fromhex("c622f04f20ab74"),
                  bytes.fromhex("c622f00020ab74"), "pass: surface"),
    patches.Patch(patches.PASS, 0x7FF4, bytes.fromhex("c622d005a9a04c0780"),
                  bytes.fromhex("c622d005a9a04cfd7f"), "pass: combat"),
    patches.Patch(patches.PASS, 0x8B66, bytes.fromhex("c622d0034cf58b"),
                  bytes.fromhex("c622d0034c6d8b"), "pass: dungeon"),
    # torch: Ignite ("WHOSE TORCH-", $5F63) takes the character's torches,
    # record byte $0F through ($7E),Y, and does SED / SEC / SBC #$01 / STA
    # ($7E),Y, then lights ($4C = $FF): SBC #$00 keeps them.  The bytes
    # occur once in all of U3's units.
    patches.Patch(patches.TORCH, 0x5F86, bytes.fromhex("f838e901917e"),
                  bytes.fromhex("f838e900917e"), "torch: ignite"),
    # Journey onward (the launcher's J): BOOT's main menu reads a key at
    # $1278 (JSR $4711) and J goes to $12A9 -- go there at once.  BOOT is
    # loaded again later in a session, so the driver drops the bit once this
    # has been applied (u3_opt_once).
    patches.Patch(patches.JOURNEY, 0x1278, bytes.fromhex("201147c9d2"),
                  bytes.fromhex("4ca912c9d2"), "journey: BOOT's menu"),
    # ... which BOOT reaches from its demo view, $1169: JSR $B80C (poll) /
    # CMP #$FF / BEQ $1117 (no key: on with the demo) -- on at once instead
    # ($B80F after it only flushes the queue)
    patches.Patch(patches.JOURNEY, 0x116C, bytes.fromhex("c9fff0a7200fb8"),
                  bytes.fromhex("c9ffeaea200fb8"), "journey: BOOT's view"),
    # ITEMS: Ultima III Gold's trainers (3/gold/GOLD-ANALYSIS.md 5.5; the
    # patch lists in Gold's BOOT, $1E36-$1E6D, read out of it).  Our ULT3 is
    # Gold's, so they land as they did there.  Magic: $5355, "NOT A ..." for a
    # class that cannot cast, -> JMP $5368, and $53E3, the MP check, -> JMP
    # $5418: every class casts both schools, for nothing.  Keys: $6823, "WHOSE
    # KEY", -> JMP $684C, the door opens.  Gems: $6404 (surface) and $8D94
    # (dungeon), who and whether a gem, -> the peer.  Powder: the command
    # letters' N entry ($51DB) and combat's ($8122) -> $6122, past the check.
    patches.Patch(patches.ITEMS, 0x5355, bytes.fromhex("20c346cecf"),
                  bytes.fromhex("4c6853cecf"), "items: magic, any class"),
    patches.Patch(patches.ITEMS, 0x53E3, bytes.fromhex("a557290faa"),
                  bytes.fromhex("4c18540faa"), "items: magic, no MP"),
    patches.Patch(patches.ITEMS, 0x6823, bytes.fromhex("20c346d7c8"),
                  bytes.fromhex("4c4c68d7c8"), "items: keys"),
    patches.Patch(patches.ITEMS, 0x6404, bytes.fromhex("20ff46a025b1"),
                  bytes.fromhex("4c1964a025b1"), "items: gems"),
    patches.Patch(patches.ITEMS, 0x8D94, bytes.fromhex("20ff46a025b1"),
                  bytes.fromhex("4ca98da025b1"), "items: gems, dungeon"),
    patches.Patch(patches.ITEMS, 0x51DB, bytes.fromhex("e8602961"),
                  bytes.fromhex("22612961"), "items: powder"),
    patches.Patch(patches.ITEMS, 0x8122, bytes.fromhex("0d61c9d2"),
                  bytes.fromhex("2261c9d2"), "items: powder, combat"),
]
# ... and EXOD, the intro, cut short.  Its sequence, $826C (called from its
# entry, $8239): the display setup ($852A copies $3000-$5FFF to $1000, $8322,
# the frames at $82C5, $B803), then $827E LDY #5 / JSR $8545, a timed
# delay, the "Exodus" scramble-in ($8343), and the waits, each $854E (JSR
# $B80C / CMP #$FF: no key, wait on; C: the disk duplicator; any other key:
# $856E, PLA x4 / JMP $823F, "R BOOT").  Journey onward does not wait for
# the first wait, which comes after the scramble-in: $827E is JMP $8570 -- the tail of $856E's PLA x4, so PLA /
# PLA / JMP $823F: R BOOT right after the display setup, which BOOT needs,
# with the stack as $856E leaves it (three pokes: the menu's list has room
# for three besides the options byte and U6's transfer).  BOOT loads
# everything the game needs itself.  20.7 s -> 12.5 s to BOOT's journey path
# in VICE.
EXOD_CUT, EXOD_TAIL = 0x827E, 0x8570

# ---------------------------------------------------------------------------
# Copy protection.  ULTIMA3-C64-ANALYSIS.md says there is "no protection in
# the load path", but disk A is 175531 bytes -- it carries an error map, and
# all 21 sectors of track 6 are flagged "21 no sync", exactly like U1/U4/U5.
#
# BOOT calls $1DF4 from $103F (right after its inline ^D "L MUSI", before
# `jsr $9A00` to start the music).  That routine opens the drive, reads
# TRACK 6 SECTOR 8 into $F000 with its own private KERNAL block reader at
# $1E00-$1EE4, then reads the error channel -- and if the status is "00",
# i.e. the read SUCCEEDED, it jumps to $1E42, an infinite loop.  It requires
# the read to fail.
#
# With no drive this eventually passes, but only after the KERNAL times out,
# and on a machine with a drive attached it seeks the head to track 6 for
# nothing.  NOP the call: on an original disk the read fails and the routine
# returns having done nothing, so that is exactly faithful.
#
# (An earlier note in the plan called $1E00 dead code.  That was wrong -- it
# came from a scan that silently parsed zero files.)
BOOT_BLOCK = 217                 # BOOT's first block on disk A, loads at $1000
BOOT_ADDR = 0x1000
PROT_CALL = 0x103F               # jsr $1DF4
PROT_BYTES = bytes([0x20, 0xF4, 0x1D])
NOP3 = bytes([0xEA, 0xEA, 0xEA])

# "INSERT SCENARIO DISK", printed by BOOT at $1055 followed by a wait loop at
# $1072-$1078 that spins on $B80C until any key is pressed.  There is nothing
# to swap, so jump straight to the keyboard flush at $1079, skipping both the
# message and the wait.  The message text sits inline after the JSR, so the
# call cannot simply be NOPed -- the string bytes would be executed.
SWAP_PROMPT = 0x1055
SWAP_BYTES = bytes([0x20, 0xC3, 0x46])   # jsr $46C3 (print inline string)
SWAP_SKIP = bytes([0x4C, 0x79, 0x10])    # jmp $1079


def symbols(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
            if m:
                out[m.group(1)] = int(m.group(2), 16)
    return out


def blocks(disk, start, count):
    out = bytearray()
    for n in range(start, start + count):
        out += disk.sector(*D64.from_linear(n))
    return bytes(out)


def unit_from_disks(name):
    """A read-only unit as the disks have it, with Gold's changes: what the
    cart's own patches are made against."""
    a = D64(DISK_A)
    catalog = blocks(a, CAT_BLOCK, CAT_BLOCKS)
    for i in range(ENTRY_COUNT):
        e = catalog[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
        if bytes(c & 0x7F for c in e[:4]).decode("latin1").strip() == name:
            disk = a if name in DISK_A_FILES else D64(DISK_B)
            return gold.apply(name, blocks(disk, e[4] | e[5] << 8, e[6] & 0x7F))
    raise KeyError(name)


def sh(*args):
    subprocess.run(args, check=True)


# EXOD's waits ($854E) take C for the disk duplicator, "R COPY" -- which
# copies the Player Master through a drive that is not there and crashes.  $855E CMP #$C3 / BNE $856E: CMP #$00
# instead, which no key is ($B80C gives $FF for none), so C ends the intro
# like any other key.
COPY_KEY, COPY_WANT, COPY_NEW = 0x855E, bytes.fromhex("c9c3d00c"), bytes.fromhex("c900d00c")


def patch_exod(data):
    out = bytearray(data)
    off = COPY_KEY - 0x3000
    if bytes(out[off:off + 4]) != COPY_WANT:
        raise SystemExit(f"EXOD ${COPY_KEY:04x} is not CMP #$C3 / BNE: {bytes(out[off:off + 4]).hex(' ')}")
    out[off:off + 4] = COPY_NEW
    return out


# SUBS' key wait ($4E9C): its poll, JSR $B80C at $4EB4, goes to
# the driver's kb_take (u3key.s: the first key queued, the rest kept, or
# joystick 2), and the flush after a key, JSR $B80F at $4EBB, is a BIT.
SUBS_ADDR = 0x4100
KEY_POLL, KEY_FLUSH = 0x4EB4, 0x4EBB


def patch_subs_keys(data, kb_take):
    out = bytearray(data)
    for at, want, new in ((KEY_POLL, b"\x20\x0c\xb8", bytes([0x20, kb_take & 0xFF, kb_take >> 8])),
                          (KEY_FLUSH, b"\x20\x0f\xb8", b"\x2c\x0f\xb8")):
        o = at - SUBS_ADDR
        if bytes(out[o:o + 3]) != want:
            raise SystemExit(f"SUBS ${at:04x} is not {want.hex(' ')}: {bytes(out[o:o + 3]).hex(' ')}")
        out[o:o + 3] = new
    return bytes(out)


# ... and ULT3's own command loops, which poll $B80C themselves: each JSR
# $B80C / CMP #$FF / BEQ (wait) / JSR $B80F (flush) -- the surface ($50A9),
# "which player?" ($6F25), $72D8, combat ($7FFD), the dungeon ($8B6D),
# $8F25 -- polls kb_take and flushes nothing.  ($8198 polls without a
# flush, leaving the key queued: left as it is.)
ULT3_ADDR = 0x5000
ULT3_POLLS = (0x50A9, 0x6F25, 0x72D8, 0x7FFD, 0x8B6D, 0x8F25)


def patch_ult3_keys(data, kb_take):
    out = bytearray(data)
    for at in ULT3_POLLS:
        o = at - ULT3_ADDR
        if bytes(out[o:o + 5]) != b"\x20\x0c\xb8\xc9\xff" or out[o + 5] != 0xF0 \
                or bytes(out[o + 7:o + 10]) != b"\x20\x0f\xb8":
            raise SystemExit(f"ULT3 ${at:04x} is not the poll/wait/flush: {bytes(out[o:o + 10]).hex(' ')}")
        out[o + 1:o + 3] = bytes([kb_take & 0xFF, kb_take >> 8])
        out[o + 7] = 0x2C                       # the flush: BIT $B80F
    return bytes(out)


# The gem's peer in colour (u3outm.s, u3dngm.s): the surface's OUTM and the
# dungeon's DNGM replaced whole, over the units they were written against.
PEERS = {"OUTM": ("u3outm.s", "e926101bb40eaa16"), "DNGM": ("u3dngm.s", "0d40d1f68c9d04a1")}
PEER_WINDOW = (0x9400, 0x9800)          # the overlays' window, SHP0 fills it all


def peer_unit(name, data):
    source, digest = PEERS[name]
    import hashlib
    if hashlib.sha256(bytes(data)).hexdigest()[:16] != digest:
        raise SystemExit(f"{name} is not the unit u3/{source} replaces")
    out = os.path.join(BUILD, name.lower() + ".bin")
    sh("acme", "-f", "plain", "-o", out, os.path.join(HERE, source))
    with open(out, "rb") as fh:
        new = fh.read()
    blocks = -(-len(new) // 256)
    assert PEER_WINDOW[0] + blocks * 256 <= PEER_WINDOW[1], f"{name} is {len(new)} bytes"
    return new.ljust(blocks * 256, b"\0")


# Ultima III Gold's ingame keys (u3trainer.s): the hooks Gold's BOOT applied
# for its trainer, always in, to stubs that test the launcher's option.
# (address, original bytes, the stub's symbol, what goes in front of it)
TRAINER_HOOKS = [
    (0x52AF, "4c 0f 52", "tr_board", 0x4C),    # JMP $520F, WHAT? (nothing to board)
    (0x50E5, "c9 a0 d0 0c", "tr_key", 0x4C),   # CMP #$A0 / BNE $50F5 -> JMP / NOP
    (0x801E, "4c fe 80", "tr_fight", 0x4C),    # combat: JMP $80FE
    (0x61DA, "20 c3 46", "tr_other", 0x20),    # Other: JSR $46C3 "NO EFFECT!"
    # the whirlpool's trip, safe for AMBROSIA said on land (always in: by the
    # whirlpool itself both do what the original did)
    (0x762B, "20 08 47 a9 00 91 7e", "tr_pool", 0x20),  # the square -> water
    (0x7777, "a9 16 85 60", "tr_back", 0x20),           # back on a frigate
    (0x6951, "a5 0e 0a 91 7e", "tr_xit", 0x20),         # X-it parks the craft
]
# "AVOID?" (u3avoid.s): a monster reaching the party, a dungeon's encounter
AVOID_HOOKS = [
    (0x78D5, "4c 49 52", "av_monster", 0x4C),  # JMP $5249, the fight
    (0x8E01, "a5 23 18", "av_dungeon", 0x20),  # LDA $23 / CLC, the encounter's kind
]
# Gold's tail, changed in place: (address, original bytes, new bytes)
TRAINER_EDITS = [
    # the teleport's coordinates: Gold refused only 100 and up (CMP #$64), so
    # 64-99 put the party off the 64 x 64 map; now those are refused too
    (0x93AF, "c9 64 60", "c9 40 60"),
    # B's S and H go on into Board past its write to the map (water at $52D0,
    # grass at $52B2: a craft's square is put back), so the party's square
    # keeps its tile (u3trainer.s, tr_xit)
    (0x9367, "4c d0 52", "4c d4 52"),
    (0x9372, "4c b2 52", "4c b6 52"),
]


def patch_ult3_trainer(data, sym):
    out = bytearray(data)
    for at, orig, name, op in TRAINER_HOOKS + AVOID_HOOKS:
        o, want = at - ULT3_ADDR, bytes.fromhex(orig)
        if bytes(out[o:o + len(want)]) != want:
            raise SystemExit(f"ULT3 ${at:04x} is not {orig}: {bytes(out[o:o + len(want)]).hex(' ')}")
        new = bytes([op, sym[name] & 0xFF, sym[name] >> 8]).ljust(len(want), b"\xea")
        out[o:o + len(want)] = new
    for at, orig, new in TRAINER_EDITS:
        o, want = at - ULT3_ADDR, bytes.fromhex(orig)
        if bytes(out[o:o + len(want)]) != want:
            raise SystemExit(f"ULT3 ${at:04x} is not {orig}: {bytes(out[o:o + len(want)]).hex(' ')}")
        out[o:o + len(want)] = bytes.fromhex(new)
    return bytes(out)


# A step on the surface (docs/developer/u3.md, "A step on the surface").
# The footstep (u3step.s): after the move's first click ($710C), $710F's
# wait, second click and a horse's third one ($0E = $14) become JSR st_foot /
# LDA #$00 / RTS, and the IRQ plays the clicks still to come: MUSI's handler
# calls st_tick instead of its player, and every effect ($470E) goes through
# st_fx.  The pin is the footstep from the first click to its RTS ($710A-
# $7135).  And the party's panel: $72EC (food, poison, a turn's bookkeeping)
# ends by drawing it ($730D JSR $71D3 / RTS), and each of its three callers
# draws it again at once (STEP_PANEL_CALLERS: JSR $72EC / JSR $71D3), so
# $72EC's own draw is a BIT.
STEP_FOOT = (0x710A, Pin("#44:5716db2a11d4095a"), 0x710F)
STEP_PANEL = (0x730D, "20 d3 71 60", "2c d3 71 60")
STEP_PANEL_CALLERS = (0x6DC0, 0x7F72, 0x8DD0)
STEP_FX = (0x470E, "4c 3d 4d")                  # SUBS: JMP $4D3D, every effect
MUSI_ADDR = 0x9A00
STEP_TICK = (0x9A75, "48 8a 48 98 48 d8 20 86 9a", 0x9A7B)  # MUSI's IRQ: JSR $9A86


def patch_step(name, data, sym):
    """ULT3's footstep and panel, SUBS' effect vector, MUSI's IRQ."""
    out = bytearray(data)

    def at(addr, base, want):
        o = addr - base
        if out[o:o + len(want)] != want:
            raise SystemExit(f"{name} ${addr:04x} is not {want.hex(' ')}: "
                             f"{bytes(out[o:o + len(want)]).hex(' ')}")
        return o

    def put(o, op, target):
        out[o:o + 3] = bytes([op, target & 0xFF, target >> 8])

    if name == "ULT3":
        start, pin, hook = STEP_FOOT
        at(start, ULT3_ADDR, pin)
        o = hook - ULT3_ADDR
        put(o, 0x20, sym["st_foot"])
        out[o + 3:o + 6] = b"\xa9\x00\x60"      # LDA #$00 / RTS, as at $7133
        addr, orig, new = STEP_PANEL
        o = at(addr, ULT3_ADDR, bytes.fromhex(orig))
        out[o:o + 4] = bytes.fromhex(new)
        for caller in STEP_PANEL_CALLERS:
            at(caller, ULT3_ADDR, bytes.fromhex("20 ec 72 20 d3 71"))
    elif name == "SUBS":
        addr, orig = STEP_FX
        put(at(addr, SUBS_ADDR, bytes.fromhex(orig)), 0x4C, sym["st_fx"])
    elif name == "MUSI":
        addr, orig, hook = STEP_TICK
        at(addr, MUSI_ADDR, bytes.fromhex(orig))
        put(hook - MUSI_ADDR, 0x20, sym["st_tick"])
    return bytes(out)


# Drawing (docs/developer/u3.md, "A step on the surface"): SUBS' message
# window scroll, $4770-$47FB, replaced in place by u3scroll.s; UPDT's line of
# sight, $CA99-$CB00, by u3view.s's one pass (JMP vw_los at $CA99; the
# original's walk at $CAA3 still does the first square, with the step
# tables at $CBE8-$CBFD).
SCROLL = (0x4770, Pin("#140:40b506e9ddba4ef7"))
UPDT_ADDR = 0xCA00
VIEW_LOS = (0xCA99, Pin("#104:84859d9ca316b17e"))
VIEW_TABLES = (0xCBE8, Pin("#22:8563f95aa4414f2e"))


def scroll_code():
    out = os.path.join(BUILD, "u3scroll.bin")
    sh("acme", "-f", "plain", "-o", out, os.path.join(HERE, "u3scroll.s"))
    with open(out, "rb") as fh:
        code = fh.read()
    addr, pin = SCROLL
    assert len(code) <= len(pin), f"u3scroll.s is {len(code)} bytes, the original {len(pin)}"
    return code


def patch_draw(name, data, sym):
    """SUBS' scroll, UPDT's line of sight."""
    out = bytearray(data)

    def at(addr, base, pin):
        o = addr - base
        if out[o:o + len(pin)] != pin:
            raise SystemExit(f"{name} ${addr:04x} is not the code it was written against")
        return o

    if name == "SUBS":
        addr, pin = SCROLL
        o = at(addr, SUBS_ADDR, pin)
        code = scroll_code()
        out[o:o + len(code)] = code
    elif name == "UPDT":
        addr, pin = VIEW_LOS
        o = at(addr, UPDT_ADDR, pin)
        at(VIEW_TABLES[0], UPDT_ADDR, VIEW_TABLES[1])
        out[o:o + 3] = bytes([0x4C, sym["vw_los"] & 0xFF, sym["vw_los"] >> 8])
    return bytes(out)


def patch_boot(data):
    """NOP the track-6 protection call and skip the scenario-disk prompt.

    These used to be applied at an offset into disk A's whole image; BOOT is
    catalog entry 'BOOT' (blocks 217-231, loading at $1000), so the same two
    sites are now offsets into the file itself.
    """
    out = bytearray(data)
    for addr, want, new_bytes, what in (
            (PROT_CALL, PROT_BYTES, NOP3, "track-6 protection call"),
            (SWAP_PROMPT, SWAP_BYTES, SWAP_SKIP, "scenario-disk prompt")):
        off = addr - BOOT_ADDR
        got = bytes(out[off:off + len(want)])
        if got != want:
            raise SystemExit(f"BOOT ${addr:04x} ({what}): expected "
                             f"{want.hex(' ')}, found {got.hex(' ')}")
        out[off:off + len(new_bytes)] = new_bytes
    return bytes(out)


def parts():
    os.makedirs(BUILD, exist_ok=True)
    a, b = D64(DISK_A), D64(DISK_B)

    catalog = bytearray(blocks(a, CAT_BLOCK, CAT_BLOCKS))
    dos = bytearray(blocks(a, DOS_BLOCK, DOS_BLOCKS))

    # sanity: the module we are about to patch must be the one we analysed
    assert dos[DOS_TRANSFER - DOS_ADDR:DOS_TRANSFER - DOS_ADDR + 5] == \
        bytes([0xA9, 0x00, 0x20, 0x90, 0xFF]), "dos_transfer is not where we expect"

    drvbin = os.path.join(BUILD, "u3drv.bin")
    drvsym = os.path.join(BUILD, "u3drv.sym")
    with open(os.path.join(BUILD, "u3_patches.s"), "w") as fh:
        fh.write(patches.asm("PT_TAB", OPTION_PATCHES))
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
       f"-DJOURNAL={regions.journal('u3')[0]}",
       "-I", HERE, "-o", drvbin, "-l", drvsym, os.path.join(HERE, "u3drv.s"))
    with open(drvbin, "rb") as fh:
        blob = fh.read()
    sym = symbols(drvsym)
    # acme emits one blob spanning both pieces with the hole zero filled.  The
    # hole covers DEMO ($C000) and DDAT ($C100-$C4FF), so writing it back would
    # be fatal; asserting it is empty is also what proves the driver stayed
    # inside $BC00-$BFFF.
    driver = blob[:sym["u3_drv_end"] - DRIVER_ADDR]
    hole = blob[len(driver):DECODER_ADDR - DRIVER_ADDR]
    decruncher = blob[DECODER_ADDR - DRIVER_ADDR:]
    if any(hole):
        raise SystemExit("the u3 driver overflowed past $BFFF into DEMO")

    # The credits the boot PRG `ultima` shows while it loads ($0825-$090F:
    # the painter and its text, ORIGIN SYSTEMS ... KENNETH W. ARNOLD), for
    # the init stub to show on a launch that is not Journey onward.  At its
    # own address (it reads its text there); its end, JMP $0910 into the
    # loads, is an RTS.  (LOADed from BASIC, the file is at $0801.)
    boot_prg, ok = a.file("ULTIMA")
    assert ok
    o = lambda addr: 2 + addr - 0x0801
    credits = bytearray(boot_prg[o(CREDITS_ADDR):o(CREDITS_END)])
    at = 0x082C - CREDITS_ADDR
    assert credits[:2] == b"\xa2\x00" and credits[at:at + 3] == b"\x4c\x10\x09", "the credits moved"
    credits[at] = 0x60

    initbin = os.path.join(BUILD, "init_u3.bin")
    sh("acme", "-f", "plain", f"-DCREDITS={CREDITS_ADDR}", f"-DPT_OPTS={sym['pt_opts']}",
       "-o", initbin, os.path.join(paths.ASM, "init_u3.s"))
    with open(initbin, "rb") as fh:
        init = fh.read()

    # $BA48 -> JMP into the replacement
    dos[DOS_TRANSFER - DOS_ADDR:DOS_TRANSFER - DOS_ADDR + 3] = \
        bytes([0x4C, DRIVER_ADDR & 0xFF, DRIVER_ADDR >> 8])

    # ---- one unit per catalog entry -------------------------------------
    # The catalog references 606 blocks of the 1366 on the two disks: more
    # than half of each is never read (the highest block used is 284 on A and
    # 381 on B).  No two entries share a block, so storing each entry as its
    # own page-aligned unit costs nothing and drops 345 KiB to 152 KiB.
    flash = Layout(regions.data_base("u3"))
    save_base = regions.save_base("u3")
    seeded = []
    xslots = {}                 # export/import: the sectors of each save slot
    units = {}
    unit_data = {}              # for the options' signature check
    crunched = []
    for i in range(ENTRY_COUNT):
        e = i * ENTRY_SIZE
        # names are stored with bit 7 set; catalog_find matches on the raw
        # bytes, so decode a copy and never touch +0..+3
        name = bytes(c & 0x7F for c in catalog[e:e + 4]).decode("latin1").strip()
        start = catalog[e + 4] | catalog[e + 5] << 8
        length = catalog[e + 6]
        if not length:
            continue            # unused slot; the driver returns on a zero count

        if name in WRITABLE:
            slot = save_base + WRITABLE.index(name) * SAVE_SLOT
            page = slot >> 8
            catalog[e + 6] = length | F_WRITABLE
            assert length * 256 + 256 <= SAVE_SLOT, f"{name} does not fit a slot"
            # seed from disk B so a fresh cart looks like a fresh disk
            data = blocks(b, start, length)
            unit_data[name] = data
            xslots[name] = xfer.Raw(slot, xfer.BLOCKS,
                                    [D64.from_linear(start + i) for i in range(length)])
            flash.place_at(slot, SAVE_MAGIC + bytes([length, 0]))
            flash.place_at(slot + 0x100, data)
            seeded.append((name, length))
        else:
            data = blocks(a if name in DISK_A_FILES else b, start, length)
            if name == "BOOT":
                data = patch_boot(data)
            if name == "EXOD":
                data = patch_exod(data)
            data = gold.apply(name, data)       # Ultima III Gold's enhancements
            if name in PEERS:
                data = peer_unit(name, data)
                catalog[e + 6] = len(data) // 256   # its length in blocks
            if name == "SUBS":
                data = patch_subs_keys(data, sym["kb_take"])
            if name == "ULT3":
                data = patch_ult3_keys(data, sym["kb_take"])
                data = patch_ult3_trainer(data, sym)
            if name in ("ULT3", "SUBS", "MUSI"):
                data = patch_step(name, data, sym)
            if name in ("SUBS", "UPDT"):
                data = patch_draw(name, data, sym)
            unit_data[name] = data
            stored = zx.smaller(data, zx.sized)
            flags = zx.SEG_COMP
            comp = 0
            if stored is not None:
                comp = F_COMP << 8
                crunched.append(name)
            else:
                stored, flags = data, 0     # a unit that would not shrink stays raw
            offset = flash.add(stored)
            units[name] = (offset, len(stored), flags)
            page = (offset >> 8) | comp

        catalog[e + 4] = page & 0xFF
        catalog[e + 5] = (page >> 8) & 0xFF

    assert len(seeded) == len(WRITABLE), f"writable entries found: {seeded}"
    assert "EXOD" in units, "EXOD is not a catalog entry any more"
    # Catalog entries load wherever the caller says, a page at a time: ULT3
    # is known to go to $5000, anything else might go anywhere.
    patches.check_floating(OPTION_PATCHES, [("ULT3", 0x5000, unit_data["ULT3"]),
                                            ("BOOT", 0x1000, unit_data["BOOT"])],
                           [(n, d) for n, d in unit_data.items() if n not in ("ULT3", "BOOT")],
                           {p.what: {"BOOT" if p.option == patches.JOURNEY else "ULT3"}
                            for p in OPTION_PATCHES})

    # ---- boot segments ---------------------------------------------------
    # EXOD is a catalog entry in its own right (blocks 5-91), so the boot
    # segment and the entry are the same unit -- no second copy.  The DOS
    # module (blocks 92-95) and the catalog (100-103) are not catalog entries
    # at all; they are read straight off the disk here, and both are patched.
    # EXOD is both the $3000 boot segment and a catalog entry, so the menu
    # decrunches the very same blob the catalog points at -- no second copy of
    # 22 KiB, and none of it stored raw.
    exod_off, exod_len, exod_flags = units["EXOD"]
    segments = [
        (exod_off, exod_len, 0x3000, exod_flags),
        (flash.add(bytes(dos)), len(dos), DOS_ADDR, 0),
        (flash.add(bytes(catalog)), len(catalog), CAT_ADDR, 0),
        (flash.add(driver), len(driver), DRIVER_ADDR, 0),
        (flash.add(decruncher), len(decruncher), DECODER_ADDR, 0),
        (flash.add(init), len(init), INIT_ADDR, 0),
        (flash.add(bytes(credits)), len(credits), CREDITS_ADDR, 0),
    ]

    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, dest, flags in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, dest >> 8, flags])
    assert len(desc) <= 64, len(desc)

    save_end = save_base + len(WRITABLE) * SAVE_SLOT
    regions.check("u3", flash.cursor, save_end)
    page = {f"U3_{n}": save_base + WRITABLE.index(n) * SAVE_SLOT for n in ("PLRS", "PRTY")}
    # export/import (xfer.py): the five entries' 24 sectors on the Player
    # Master, which the game never checks the identity of -- so the page
    # does, by the BAM's disk name (the game's own disk duplicator copies it)
    # the 1984 Scenario disk is named "ULTIMA III-SCEN." (the Trilogy's
    # "PLAYER MASTER"); the game's own copier (COPY) copies all of track 18,
    # so a player disk it made is named as its master was
    xf = [xfer.Disk("Scenario", b.sector(18, 0), [xslots[n] for n in WRITABLE],
                    alt="ULTIMA III-SCEN.")]
    # POWERS: Gold's ingame keys, a launch poke of tr_on (the options byte's
    # bit 2 is JOURNEY's in U3); AVOID: "AVOID?" (u3avoid.s), whose hooks are
    # always in and read the options byte -- no RAM patch carries the bit
    options = dict(caps=patches.caps(OPTION_PATCHES) | patches.POWERS | patches.AVOID,
                   addr=sym["pt_opts"],
                   pokes={patches.POWERS: [(sym["tr_on"], 0x80)]})
    exod = unit_data["EXOD"]
    o = EXOD_CUT - 0x3000
    # JSR $852A / JSR $8322 / JSR $82C5 / JSR $B803 / LDY #5 / JSR $8545
    assert bytes(exod[o - 12:o + 5]) == Pin("#17:24d6ae00747963de"), \
        "EXOD $8272"
    assert bytes(exod[0x856E - 0x3000:0x8575 - 0x3000]) == bytes([0x68] * 4 + [0x4C, 0x3F, 0x82])
    cut = bytes([0x4C, EXOD_TAIL & 0xFF, EXOD_TAIL >> 8])
    journey = dict(pokes=[(EXOD_CUT + i, b) for i, b in enumerate(cut)], bits=patches.JOURNEY)
    return dict(name="ULTIMA III", journey=journey, blobs=list(flash.blobs), desc=bytes(desc), page=page,
                options=options, unit_data=unit_data, xfer=xf,
                save_end=save_end, used=flash.used, cursor=flash.cursor,
                seeded=seeded, units=len(units), crunched=crunched,
                driver=len(driver), decruncher=len(decruncher))


def main():
    """Write a standalone image for this game alone -- what the per-game make
    targets and tests use.  ultima/build.py merges parts() instead."""
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "ultima3.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(regions.desc_offset("u3"), p["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="ULTIMA 3", flash=image_from(blobs, p["save_end"]))
    img.write(out, trim=False)
    print(f"{out}")
    print(f"  data {regions.data_base('u3'):#08x}-{p['cursor']:#08x} "
          f"({p['used'] / 1024:.1f} KiB: {p['units']} catalog entries, "
          f"one unit each)")
    print(f"  crunched {len(p['crunched'])} of {p['units']} units; driver "
          f"{p['driver']} bytes at {DRIVER_ADDR:#06x}, decruncher "
          f"{p['decruncher']} bytes at {DECODER_ADDR:#06x}")
    print(f"  saves at {regions.save_base('u3'):#08x}, {len(WRITABLE)} slots of "
          f"{SAVE_SLOT // 1024} KiB: " + ", ".join(f"{n} ({l} blk)" for n, l in p["seeded"]))


if __name__ == "__main__":
    main()
