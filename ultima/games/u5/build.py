#!/usr/bin/env python3
"""Build the Ultima 5 flash layout.

U5 addresses everything by name through a 17-entry jump table at $6C00, so
the cart-side filesystem is keyed on (disk, filename) -- 236 files across
eight disks, 148 unique by content.  Names repeat across disks with different
contents (`m` and `startup` are entirely different programs depending on the
disk), so the key really is the pair.

The driver finds a file through the cart's own directory lookup (DIR_LOOKUP),
by the disk and name, so no name table lives in the C64's memory.
"""
import os
import re
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths

from ultima.disks.d64 import D64, SECTORS_PER_TRACK, TOTAL_SECTORS as TOTAL_BLOCKS
from ultima.flash.layout import Layout, image_from
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.flash import regions
from ultima.flash import tcsyms
from ultima.games.u5 import armusic                  # noqa: E402
from ultima.launcher import xfer
from ultima.flash import zx


BUILD = paths.BUILD

# disk number -> image tag.  N + $40 is the BAM ID character the game checks,
# so this ordering is the game's, not the labels' (§4 of the analysis).
TAGS = {1: "1A", 2: "2A", 3: "3A", 4: "3B", 5: "4A", 6: "4B", 7: "1B", 8: "2B"}

XYZZY_ADDR = 0x2000
SUBS_ADDR = 0x6C00               # temp.subs, permanently resident
FAST_ADDR = 0x7700               # u5siz.o: fastloader, overlaid by the driver
INIT_ADDR = 0x0200
FAST_LIMIT = 0x7B00              # the sound-effect routine starts here
# The driver has to fit $7700-$7AFF: everything from $7B57 to $7FFF is the
# game's -- main.twn stamps empty-slot markers into $7D00-$7D7F, and a scan
# finds the rest named all over -- and the RAM under I/O is not free either.
# What does not fit goes into three routines inside temp.subs whose only
# entries were the jump-table slots the driver has taken over: (start, the
# first byte that must survive).  u5drv.s explains how they were checked.
HOLES = [(0x6C49, 0x6CAA, "u5_hole_a_end"),     # LOAD by name
         (0x6CAA, 0x6DE0, "u5_hole_d_end"),     # check ID, ensure disk, prompts
         (0x6DE0, 0x6E7B, "u5_hole_c_end"),     # scratch + SAVE
         (0x6EAE, 0x6F4D, "u5_hole_b_end")]     # raw block read
# The cart does the name lookup itself: DIR_SETPARAMS points it at a
# directory in flash and DIR_LOOKUP matches a fixed-length name against it.
# Nothing about the 236 files lives in C64 memory.
DIR_NAMELEN = 13                 # disk number + 12 name bytes
DIR_DATALEN = 8                  # flash address (3), length, load address, flags
F_WRITE = 0x01                   # this file has a save slot
F_ZX = 0x02                      # stored as a zx02 stream (length = the stream's)

# What the game saves, from diffing saves made on copies of the originals
# (5/with-save) against the pristine set.  TLIST on 2B is easy to miss: the
# save disk is not only 2A.  A slot is one erase block -- a header page then
# the data -- because the game does not write back what it read: ROSTER ships
# as 1025 bytes and is saved as 1024, so the length has to live with the data
# rather than in the directory.
WRITABLE = {(2, "ROSTER"), (2, "PRTY.DATA"), (2, "LIST"),
            (2, "SLIST"), (2, "TLIST"), (8, "TLIST")}
# The ROSTER slot's base holds the 1024 bytes the game writes, not the 1025
# it ships with: loaded at $1000, the 1025th byte lands on $1400, the first
# entry of startup's bitmap row table.  Journey Onward loads ROSTER before
# it finds there is no game, and neither "No active game!" nor creation
# goes back through startup's $8025, which builds the table; the next
# Journey Onward then draws text row 0 forty bytes to the left.
ROSTER_LEN = 1024
SAVE_SLOT = 0x1000
SAVE_MAGIC = bytes([0xA5, 0x5A])

# the three jump-table slots this port implements, and what they point at now
VECTORS = {0x6C00: ("u5_block", 0x6EAE),      # raw block read
           0x6C09: ("u5_setdisk", 0x6D47),    # ensure disk N
           0x6C24: ("u5_load", 0x6C49),       # LOAD by inline name
           0x6C2A: ("u5_checkid", 0x6CAA),    # check disk ID
           0x6C2D: ("u5_save", 0x6DE0)}       # disk command + SAVE

# $6C30 (512-byte record) needs no replacement of its own: $6E7B turns a
# record number into a track and sector and then calls $6EAE twice, directly
# rather than through the jump table.  Repointing those two calls is enough.
RECORD_CALLS = [(0x6E9E, 0x6EAE), (0x6EAA, 0x6EAE)]

# ---------------------------------------------------------------------------
# Motor.  U5 runs at $01 = $00 and banks in with $01 = $06; both clear bit 5,
# which starts the tape motor and drops the cart out of command mode.  Every
# immediate operand that reaches $01 has to gain that bit.  The list is from
# §6 of the analysis, which scanned all 236 files and separated the six real
# writers from 51 false positives in graphics data.
MOTOR = [
    ("temp.subs", 0x7685, 0x06, 0x26, "bank I/O + KERNAL in"),
    ("temp.subs", 0x7690, 0x00, 0x20, "bank all-RAM (the steady state)"),
    ("xyzzy",     0x2063, 0x06, 0x26, "boot"),
    ("scratch",   0x2045, 0x06, 0x26, "boot"),
    ("update.himem", 0x1F47, 0x06, 0x26, "boot"),
    ("intro.view", 0x9F36, 0x06, 0x26, "intro"),
]

# ---------------------------------------------------------------------------
# xyzzy.  Two patches drop everything between the drive-type prompt and the
# fastloader install ($208D-$20D4: the prompt, the "UJ" drive reset, the
# u5siz.o load and the install itself), and the KERNAL load of temp.subs at
# $210C.  Both files are segments here.  What is left of xyzzy is the machine
# setup, the $0380 IRQ handler copy and the final `jsr $6C24 "ST*"` that pulls
# `startup` in through the driver.
XYZZY_PATCHES = [
    (0x208D, bytes([0x20, 0x33, 0x21]), bytes([0x4C, 0xD5, 0x20]),
     "drive prompt, drive reset, fastloader install"),
    (0x210C, bytes([0xA9, 0x05, 0xA2, 0xE0]), bytes([0x4C, 0x1A, 0x21]),
     "kernal LOAD of temp.subs"),
]


# ---------------------------------------------------------------------------
# C128 mode (c128.inc, sub128.s, launch128.s).  Two patches to xyzzy's C128
# branch -- which a C64 never takes, so they are made to the one xyzzy both
# machines load -- and one to qs's:
#   * the DDR: xyzzy writes $00 = $00 there, which would leave the cart's
#     motor and write lines floating; the value it loads is still stored in
#     $9D after it.
#   * the music: `m` loaded to $7200 in bank 0, JSR $720F (copy to bank 1,
#     start the player), then `subs.128` loaded over $7700.  The launcher has
#     put `m` in bank 1 already and our driver is at $7700, so this becomes
#     the eighth entry there, the music setup (sub128.s t7), and on to the
#     J-held test at $20F8.
#   * qs (Journey Onward held at boot) reloads subs.128 over $7700; on the
#     cart the cache is in bank 1, loaded once, so the load is jumped over.
#     It runs straight after xyzzy, so the cache's state is still fresh.
C128_SLOTS = 8
C128_DESC_VERSION = 1            # launch128.s checks it: a disk's launcher and
                                 # the cart's page must agree on the layout
XYZZY_C128_PATCHES = [
    (0x2055, bytes([0x85, 0x00]), bytes([0xEA, 0xEA]), "C128: keep the DDR"),
    (0x20D9, bytes.fromhex("a901a2e5a021"), bytes.fromhex("2015774cf820"),
     "C128: the music setup from bank 1, not LOAD m / JSR $720F / LOAD SUB*"),
]
QS_C128_PATCHES = [
    (0x8091, bytes.fromhex("a20020"), bytes.fromhex("4ca180"), "C128: no subs.128 reload"),
]
M_ADDR = 0x7200                  # `m`, the music, in bank 1
B1_ORG = 0xE000                  # sub128.s, in bank 1 (c128.inc)
SUBS128_ADDR = 0x7700            # subs.128 on disk 1A (read for its tables)
C128_PRG_NAME = "ULTIMA V 128"   # what the page saves the launcher as

# ---------------------------------------------------------------------------
# The music on a C64 with an Action Replay (armusic.s, armusic.py, armhook.s).
# Every music gate in the game is `lda $C8 / bpl` -- $C8 bit 7 is "a C128" --
# and becomes `bit $C8 / bvc`: bit 6, "the music is there", which the C128's
# music setup sets (sub128.s t7) and so does armusic.s on a C64 that has an
# AR.  Only bits 0 and 7 of $C8 are used elsewhere (startup and qs AND, OR
# and EOR bit 0), so bit 6 is free.  These are the gates around the songs:
# temp.subs' play ($6C40) and "Volume" toggle ($6C43), the title's walk
# through the score, the combat start, `u` and `w`, the ending.
MUSIC_GATES = [("temp.subs", 0x76B8), ("temp.subs", 0x76C6), ("startup", 0x91D3),
               ("main.combat", 0x86F5), ("u", 0xB4FC), ("u", 0xB640),
               ("w", 0xA781), ("w", 0xA963), ("end", 0xAC81)]
# And the other way round: C64-only code, `lda $C8 / bmi` over it, that the
# music's glue cannot live with, becomes `bit $C8 / bvs`, skipped wherever
# the music is.  enter.play (Journey Onward) puts the C64's disk-load hooks
# at $0126-$0146 -- sprites off for a load, for the fastloader's timing --
# over the glue's music API and ar_call (found on hardware: every interrupt
# after it ran garbage and was never acknowledged).  The cart needs no such
# hooks; a C64 without an AR still gets them, as the original.
C64_GATES = [("enter.play", 0x802A)]
AR_BASE = 0x8000                 # the AR's RAM at ROML
AR_TABLE = 11 * 3                # armusic.s's jump table in front of the player
AR_PIECES = dict(PIECE_A=0x0123, PIECE_B=0x0200, PIECE_C=0x0335, PIECE_D=0x0100)
AR_ON, AR_OFF, AR_STAGE = 0x20, 0x0A, 0x4000
# temp.subs, the C64 build: $6C40's JMP $7703 (subs.128 on a C128) to the
# glue's play, and $6C46 -- which is not gated -- behind the same test
AR_PLAY_JMP = 0x76BC
AR_RESTART = (0x76BF, bytes.fromhex("adcd038dcc0360"))
AR_HOOK = (0x208D, 0x2090)       # xyzzy: the JMP over the drive prompt, and
                                 # where the hook goes in what it skips

# ---------------------------------------------------------------------------
# Ultima IV's save slots, as ultima/games/u4/build.py lays them out (checked by
# tests/test_u5_build.py): blocks 271-275 of its Britannia disk, one erase
# block each from regions.save_base("u4").  `transfer` reads 273 and 274.
U4_SAVE_FIRST, U4_SAVE_COUNT = 271, 5
U4_PARTY_BLOCK = 273                # track 14 sector 0

# ---------------------------------------------------------------------------
# `transfer`'s prompt ($8165, before anything is read): three lines printed
# from fixed rows and columns, then a key, (A) aborting.  The first two ask
# for the Ultima IV Britannia disk to be swapped in; on the cart the party
# comes from U4's save, so they say that instead -- same lengths, same start
# columns, the new text centred in them, so nothing else moves.
def _hi(text):
    return bytes(0xA0 if c == " " else ord(c) | 0x80 for c in text)


TRANSFER_TEXT = [
    (0x8170, "Please remove the boot disk", " Press any key to transfer "),
    (0x8197, "and insert the Ultima IV BRITANNIA disk", "  the party from your Ultima IV save,  "),
]

# ---------------------------------------------------------------------------
# The main menu's "Number of drives" entry (disk 1A's `startup`, at $8000).
# With every disk on the cart it means nothing, so it goes: the line is not
# printed (a jump over its inline string to the highlight call after it)
# and the cursor stops at the fifth entry.  Its select handler is only
# reachable with the cursor on entry six.  The menu's keys $C1-$CF (A-O) are
# not the drives' digits: $85A2 is `and #$0F / tax / jsr $6C40`, play song
# 1-15, which a C128 (and a C64 with the Action Replay's music) has, so the
# range test stays.
MENU_PATCHES = [
    (0x84ED, bytes([0xA9, 0x15, 0x85]), bytes([0x4C, 0x0B, 0x85]),
     "the drives line: jmp past its string"),
    (0x850B, bytes([0x20, 0x35, 0x8D]), bytes([0x20, 0x35, 0x8D]),
     "(the jump's target: the highlight call)"),
    (0x85C5, bytes([0x06]), bytes([0x05]), "cursor stops at entry five"),
]


def sh(*args):
    subprocess.run(args, check=True)


def symbols(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
            if m:
                out[m.group(1)] = int(m.group(2), 16)
    return out


def disk_path(tag, where=None):
    """Disk `tag` (1A..4B): its stand-in, or u5-<tag>.d64 in `where` (the
    U5_SAVE_FROM debug seed)."""
    if where is None:
        return paths.disk("u5-" + tag.lower())
    return os.path.join(where, f"u5-{tag.lower()}.d64")



# The launcher's food option (patches.py, asm/patch.s), applied by the
# driver after every load.  main.subs ($4C00, disk 1A, loaded once per
# session) $5F9B runs every turn; on an hour change it either prints
# "Starving!" and hurts everyone (no food) or, at 06, 12 and 18 o'clock,
# takes a ration per living member ($5FE4-$6026).  Jumped over to $6027,
# which keeps the hour's bookkeeping.  Camping (p.prg, dng.precom) and the
# monsters that eat rations still take food.
# U5 has no idle pass.
#
# Torches: lighting one ends `sed / [lda $1186 / clc |
# sec] / sbc #$01 / sta $1186 / cld`, the party's torch count, at five places
# -- MAIN.OUT on 2A and on 2B, 2B's STARTUP, MAIN.TWN (the same on 3A-4B) and
# MAIN.DNG on 1B, whose `lda $1186 / beq` still wants one to light.  The
# STA becomes a BIT: the torch lights, the count stays.  (The CLC sites'
# SBC #$01 took two in BCD: a bug of the original's, which on uses none.)
# The only other stores to $1186 are the shops' (S), which sell them.  The
# table is streamed from the cart (patch.s PT_STREAM), so it can be long.
TORCH_SITES = [("2A", 0x8D32, "MAIN.OUT"), ("2B", 0x8D28, "MAIN.OUT"),
               ("2B", 0x8D25, "STARTUP"), ("3A-4B", 0x8C7F, "MAIN.TWN"),
               ("1B", 0x8B53, "MAIN.DNG")]
OPTION_PATCHES = [
    patches.Patch(patches.FOOD, 0x5FE4, bytes.fromhex("ad80110d8111d014"),
                  bytes.fromhex("4c27600d8111d014"), "food"),
] + [patches.Patch(patches.TORCH, addr, bytes.fromhex("8d8611"), bytes.fromhex("2c8611"),
                   f"torch: {name} {where}") for where, addr, name in TORCH_SITES]

# Spells, keys and gems never used up (U3's and U4's ITEMS for U5; the party's counts are the roster's $1184 keys, $1185
# gems, $1240+ the mixtures, a character's MP at +7 of its $1080 record).
#   Keys: Jimmy uses one up only when it fails, "Key broke!" then SED / [LDA
#   $1184 /] SEC / SBC #$01 / STA $1184 -- in S (the chests), CMD.DNG (two),
#   MAIN.COMBAT and MAIN.TWN; the STA becomes a BIT, so a key still has to
#   be there ("No keys!") and never breaks.  The other stores to $1184 are
#   S's finds (an add), and MAIN.TWN's and BLACKTHORN's taking them all.
#   Gems: View, "You have none!" for none, then the same decrement -- in
#   MAIN.DNG, MAIN.OUT (2A, 2B), 2B's STARTUP and MAIN.TWN: STA -> BIT.
#   Spells: Cast (C, 1B-4B, and OC, 2B/3A/4A/4B, the same code 4 bytes on)
#   reads the mixture ($A7AC LDA $1240,Y / BNE, else "None mixed!") and
#   uses it up, then SBC #cost from the MP (the cost stored into the SBC's
#   operand at $A7DA) and "M.P. too low!" on a borrow.  The LDA becomes a
#   JMP past the use ($A7CA), and the cost's store a BIT, so it stays the 0
#   the file has and the MP is stored back unchanged.  The level check after
#   it (a circle above the caster's level: "Failed!") stays.  Three-byte
#   signatures, as the torches' (patches.check proves each unique where it
#   lands): the table is streamed from the cart after every named load
#   (patch.s PT_STREAM), 211 bytes now, 61 before.
KEY_SITES = [("1B-4B", 0xAF9F, "S"), ("1B", 0xB254, "CMD.DNG"), ("1B", 0xB2C8, "CMD.DNG"),
             ("1B-4B", 0x8D56, "MAIN.COMBAT"), ("3A-4B", 0x8EC0, "MAIN.TWN")]
GEM_SITES = [("1B", 0x8ECC, "MAIN.DNG"), ("2A", 0x90B9, "MAIN.OUT"), ("2B", 0x90AF, "MAIN.OUT"),
             ("2B", 0x90AC, "STARTUP"), ("3A-4B", 0x927D, "MAIN.TWN")]
# (where, the mixture's LDA, the cost's STA, name)
CAST_SITES = [("1B-4B", 0xA7AC, 0xA7DA, "C"), ("2B 3A 4A 4B", 0xA7B0, 0xA7DE, "OC")]
OPTION_PATCHES += [patches.Patch(patches.ITEMS, addr, bytes.fromhex("8d8411"),
                                 bytes.fromhex("2c8411"), f"items: key {name} {addr:04x}")
                   for where, addr, name in KEY_SITES]
OPTION_PATCHES += [patches.Patch(patches.ITEMS, addr, bytes.fromhex("8d8511"),
                                 bytes.fromhex("2c8511"), f"items: gem {name} {where}")
                   for where, addr, name in GEM_SITES]
for _where, _mix, _cost, _name in CAST_SITES:
    _past = _mix + 0x1E                     # TYA after the mixture's STA
    OPTION_PATCHES += [
        patches.Patch(patches.ITEMS, _mix, bytes.fromhex("b94012"),
                      bytes([0x4C, _past & 0xFF, _past >> 8]), f"items: mixture {_name}"),
        patches.Patch(patches.ITEMS, _cost, bytes([0x8D, _cost + 0xC & 0xFF, _cost >> 8]),
                      bytes([0x2C, _cost + 0xC & 0xFF, _cost >> 8]), f"items: MP {_name}")]


# The launcher's X (POWERS, bit 2 of the options byte: U5 does Journey Onward
# with a poke, not the bit): F7 teleports, B(oard) with nothing to board
# brings a vehicle (u5powers.s, appended to MAIN.OUT on 2A and 2B, two JMPs
# at its start).  The patches are the hooks, two of the command loop's
# "What?"s, JSR $4C00 / "What?" / JMP to the end of the turn: the one for a
# key it does not know becomes JSR TELE, Board's when there is nothing to
# board JSR TELE + 3.  The JMP's target is in the signature, which keeps
# them out of 2B's STARTUP, an older MAIN.OUT with the first hook at the
# same place (and no load path found to it).  Per disk: the two hooks, the
# end of the turn, the code's address (MAIN.OUT's end), the store of the raw
# key in the command loop, the end of a blocked ship's move (heading and
# sailing cleared, back to the loop).  tele_sites() checks each against the
# file.
WHAT = bytes([0x20, 0x00, 0x4C]) + _hi("What?") + bytes([0x8D, 0x00, 0x4C])
TELE = {2: dict(hook=0x8275, board=0x86E5, turn=0x9502, TELE=0xA47A, key_store=0x810F, blocked=0x84E9),
        8: dict(hook=0x826B, board=0x86DB, turn=0x94F8, TELE=0xA470, key_store=0x8105, blocked=0x84DF)}


def _tele_sig(t):
    return WHAT + bytes([t["turn"] & 0xFF, t["turn"] >> 8])


def _jsr(t, entry):
    return bytes([0x20, t["TELE"] + entry & 0xFF, t["TELE"] + entry >> 8]) + _tele_sig(t)[3:]


OPTION_PATCHES += [patches.Patch(patches.POWERS, t[site], _tele_sig(t), _jsr(t, entry),
                                 f"powers: {what} MAIN.OUT {TAGS[n]}")
                   for n, t in TELE.items() for site, entry, what in (("hook", 0, "F7"), ("board", 3, "B"))]


def tele_sites(files):
    """u5powers.s's defines for each MAIN.OUT, read off the code they come
    from, which must be as expected."""
    out = {}
    for n, t in TELE.items():
        load, body = pick(files, n, "MAIN.OUT")
        at = lambda a, k: bytes(body[a - load:a - load + k])
        w = lambda a: body[a - load] | body[a - load + 1] << 8
        h, ks, bl = t["hook"], t["key_store"], t["blocked"]
        if (at(h, 13) != _tele_sig(t) or at(t["board"], 13) != _tele_sig(t)
                or at(t["board"] - 0x33, 9) != bytes([0x20, 0x00, 0x4C]) + _hi("Board ")
                or at(ks, 1) != b"\x8d" or at(bl, 3) != bytes([0xA9, 0x00, 0x8D]) or at(bl + 5, 1) != b"\x8d"
                or at(bl + 8, 4) != bytes([0x20, 0x2A, 0x4C, 0x4C]) or at(0x8003, 1) != b"\x4c"):
            raise SystemExit(f"powers: MAIN.OUT on {TAGS[n]} is not the code u5powers.s was written for")
        if load + len(body) != t["TELE"]:
            raise SystemExit(f"powers: MAIN.OUT on {TAGS[n]} ends at ${load + len(body):04x}, "
                             f"not ${t['TELE']:04x}")
        out[n] = dict(TELE=t["TELE"], TURN=t["turn"], KEY=w(ks + 1), HEADING=w(bl + 3),
                      SAILING=w(bl + 6), LOOP=w(bl + 12))
    return out


def _site_disks(where):
    return {"1B-4B": ["1B", "2A", "2B", "3A", "3B", "4A", "4B"],
            "3A-4B": ["3A", "3B", "4A", "4B"]}.get(where, where.split())


def option_units():
    """patches.check's intended units: which (disk:file) each patch is for."""
    tag = {t: n for n, t in TAGS.items()}
    out = {"food": {"1:MAIN.SUBS"}}
    for where, _addr, name in TORCH_SITES:
        disks = ["3A", "3B", "4A", "4B"] if where == "3A-4B" else [where]
        out[f"torch: {name} {where}"] = {f"{tag[d]}:{name}" for d in disks}
    for where, addr, name in KEY_SITES:
        out[f"items: key {name} {addr:04x}"] = {f"{tag[d]}:{name}" for d in _site_disks(where)}
    for where, _addr, name in GEM_SITES:
        out[f"items: gem {name} {where}"] = {f"{tag[d]}:{name}" for d in _site_disks(where)}
    for where, _mix, _cost, name in CAST_SITES:
        for what in ("mixture", "MP"):
            out[f"items: {what} {name}"] = {f"{tag[d]}:{name}" for d in _site_disks(where)}
    for n in TELE:
        for what in ("F7", "B"):
            out[f"powers: {what} MAIN.OUT {TAGS[n]}"] = {f"{n}:MAIN.OUT"}
    return out


def caps():
    """The options U5's page offers: the patches', and X (POWERS), which
    patches.caps() leaves to the games where it is a poke."""
    return patches.caps(OPTION_PATCHES) | patches.POWERS


# ---------------------------------------------------------------------------
# The speed patches (measured with tools/vice/u5_step_bench.py;
# docs/developer/u5.md).  Routines of
# the view, the text window and the townspeople, rewritten in place with the
# same effect; each source's header says how.  FAST_SOURCES: the source, the
# file it goes into (disk, name -- main.twn is the same file on 3A-4B, so
# every copy gets it) and its spans by label.  FAST_ORIGINAL: the CRC of what
# each span replaces, the whole range given (the original's dead bytes after
# a shorter rewrite included), so other disks are refused.
TWN_DISKS = (3, 4, 5, 6)
# (source, [(file, disks, first label, end label)], labels it takes from the
# sources before it); in this order
FAST_SOURCES = [
    ("u5anim.s", [("MAIN.SUBS", (1,), "anim", "anim_end")], ()),
    ("u5scroll.s", [("MAIN.SUBS", (1,), "scroll", "scroll_end")], ()),
    ("u5los.s", [("MAIN.SUBS", (1,), "los", "los_end")], ()),
    ("u5draw.s", [("UPDATE.HIMEM", (1,), "draw", "draw_end")], ()),
    ("u5buf.s", [("MAIN.SUBS", (1,), "buf", "buf_end")],
     ("u5bufcells", "u5buf_l", "u5buf_r")),
    ("u5walk.s", [("MAIN.TWN", TWN_DISKS, "w_drv", "w_drv_end"),
                  ("MAIN.TWN", TWN_DISKS, "w_tail", "w_tail_end"),
                  ("MAIN.SUBS", (1,), "w_seg", "w_seg_end")], ()),
]
FAST_ORIGINAL = {
    ("MAIN.SUBS", 0x572B, 0x57DE): 0x9EE6363A,      # the tile animation and its two helpers
    ("MAIN.SUBS", 0x5A90, 0x5B14): 0x7113D8E4,      # the text window's scroll
    ("MAIN.SUBS", 0x4D5D, 0x4E49): 0x6693C16C,      # the line of sight and its private tables
    ("MAIN.SUBS", 0x4D06, 0x4D51): 0xCC1F57AE,        # the view's buffers
    ("MAIN.SUBS", 0x515E, 0x5184): 0x23B8DE79,         # their old lit-square helper: u5walk.s's room
    ("MAIN.TWN", 0xA30F, 0xA345): 0x19112F39,          # the town's walkability map: the driver
    ("MAIN.TWN", 0xA35C, 0xA373): 0x9413008B,          # ... and its 16 bytes a call
    ("UPDATE.HIMEM", 0x1DE4, 0x1F8B): 0x84889522,   # the view's draw and its helper (after MOTOR: $1F47 = $26)
}
# u5scroll.s has the row tables' addresses built in: the tables startup and
# qs copy to $1400/$14C0 (bitmap lines 0-191) and $03D0/$03E8 (screen rows
# 0-23), file addresses of the four tables in each.
ROW_TABLES = {"STARTUP": (0x8F5F, 0x901F, 0x90DF, 0x90F8), "QS": (0x823F, 0x82FF, 0x83BF, 0x83D8)}


def assemble_fast():
    """The speed patches as [(file name, disks, address, bytes)]."""
    out, labels = [], {}
    for src, spans, takes in FAST_SOURCES:
        blob, sym = asm(src, src.replace(".s", ".bin"), **{k: labels[k] for k in takes})
        labels.update(sym)
        origin = min(sym[first] for _f, _d, first, _e in spans)
        for fname, disks, first, end in spans:
            out.append((fname, disks, sym[first], blob[sym[first] - origin:sym[end] - origin]))
    return out


def apply_fast(files):
    """Lay the speed patches over `files` ((disk, name) -> [load, body]),
    after checking that what they replace is the original."""
    def body(disk, fname):
        return pick(files, disk, fname)
    for (fname, first, end), crc in FAST_ORIGINAL.items():
        for disk in next(d for _s, spans, _t in FAST_SOURCES for f, d, _a, _b in spans if f == fname):
            load, data = body(disk, fname)
            got = zlib.crc32(bytes(data[first - load:end - load]))
            if got != crc:
                raise SystemExit(f"speed patches: {fname} on disk {disk} ${first:04x}-${end - 1:04x} "
                                 f"is not the original (CRC {got:08x}, expected {crc:08x})")
    for fname, (blo, bhi, slo, shi) in ROW_TABLES.items():
        load, data = body(1, fname)
        at = lambda a, i: data[a - load + i]
        for n in range(192):
            if at(blo, n) | at(bhi, n) << 8 != 0x2000 + 320 * (n // 8 + 1) + n % 8:
                raise SystemExit(f"speed patches: {fname}'s bitmap line {n} is not where u5scroll.s has it")
        for k in range(24):
            if at(slo, k) | at(shi, k) << 8 != 0x0400 + 40 * (k + 1):
                raise SystemExit(f"speed patches: {fname}'s screen row {k} is not where u5scroll.s has it")
    for fname, disks, addr, data in assemble_fast():
        if not any(f == fname and a <= addr and addr + len(data) <= e for f, a, e in FAST_ORIGINAL):
            raise SystemExit(f"speed patch {fname} ${addr:04x}: outside the ranges checked")
        for disk in disks:
            load, image = body(disk, fname)
            image[addr - load:addr - load + len(data)] = data


def seed_saves_from(files, where):
    """Fill the save slots from another set of disks instead of the shipped one.

    Set U5_SAVE_FROM=5/with-save/saved-01-startposition to build an image that
    starts with that save already in flash.  Journey Onward then works without
    a character-creation run, which is the only practical way to *debug* the
    in-game paths -- reaching them otherwise means typing a name at a prompt
    the monitor cannot reach.  Debug only; the shipped image seeds the slots
    from the pristine disks.
    """
    for n, name in sorted(WRITABLE):
        d = D64(disk_path(TAGS[n], where))
        data, ok = d.file(name)
        if not ok:
            raise SystemExit(f"{name} on disk {n} in {where}: bad sector")
        files[(n, name)] = [data[0] | data[1] << 8, bytearray(data[2:])]
    return where


def sector_runs(disks):
    """Per disk, the contiguous run of linear blocks that raw reads can touch.

    It is the span of the blocks marked allocated in the BAM but belonging to
    no directory entry -- the private data area main.twn, main.out, main.dng
    and t read through $6C00 -- extended to the end of the disk.  Storing the
    whole span rather than just the orphan blocks costs 42 KiB and turns the
    mapping into two numbers per disk instead of a 683-entry table.

    Disk 1A has no such area; its only raw read is `transfer`'s track 14
    sector 0, which is a sector of an *Ultima IV* player disk: parts() maps
    disk 1's entry to U4's save slots instead (U4_PARTY_BLOCK).
    """
    runs = {}
    for n, d in disks.items():
        used = set()
        for name, _ty, t, s, _b in d.directory():
            tt, ss, seen = t, s, set()
            while tt and (tt, ss) not in seen:
                seen.add((tt, ss)); used.add((tt, ss))
                sec = d.sector(tt, ss); tt, ss = sec[0], sec[1]
        used.add((18, 0))
        tt, ss = 18, 1
        while tt:
            used.add((tt, ss)); sec = d.sector(tt, ss); tt, ss = sec[0], sec[1]
        bam = d.sector(18, 0)
        alloc = set()
        for track in range(1, 36):
            e = 4 + (track - 1) * 4
            bits = bam[e + 1] | bam[e + 2] << 8 | bam[e + 3] << 16
            for sec in range(SECTORS_PER_TRACK[track]):
                if not (bits >> sec) & 1:
                    alloc.add((track, sec))
        # track 18 is the directory; track 6 on disk 1A is unformatted
        orphans = {(t, s) for (t, s) in alloc - used if t not in (6, 18)}
        if not orphans:
            runs[n] = None
            continue
        first = min(D64.linear(t, s) for t, s in orphans)
        runs[n] = (first, TOTAL_BLOCKS - first)
    return runs


def inline_patterns(files):
    """Every wildcard name the code passes to $6C24, found by walking the
    inline strings after each `JSR $6C24`.

    Names that a call site self-modifies -- `TALK.XX` patches its two digits
    -- come out as exact names at run time and are already directory entries,
    so only the literal `*` and `?` patterns matter here."""
    out = set()
    for (_n, _name), (_load, body) in files.items():
        i = 0
        while True:
            i = body.find(b"\x20\x24\x6c", i)
            if i < 0:
                break
            j = i + 3
            s = bytearray()
            while j < len(body) and body[j] != 0 and len(s) <= DIR_NAMELEN:
                s.append(body[j])
                j += 1
            txt = bytes(s).decode("latin1", "replace")
            if s and j < len(body) and body[j] == 0 \
                    and re.fullmatch(r"[A-Z0-9.*?]+", txt) and ("*" in txt or "?" in txt):
                out.add(txt)
            i += 1
    return sorted(out)


def resolve(pattern, names):
    """CBM DOS pattern match against a directory, in directory order: `*`
    matches the rest, `?` matches one character, and a pattern shorter than
    the name does not match without a `*`."""
    for name in names:
        i = 0
        while True:
            if i == len(pattern):
                if i == len(name):
                    return name
                break
            if pattern[i] == "*":
                return name
            if i >= len(name):
                break
            if pattern[i] != "?" and pattern[i] != name[i]:
                break
            i += 1
    return None


def pick(files, disk, name):
    """(disk, name) lookup that ignores case -- the directory is uppercase
    PETSCII, the analysis writes the names in lower case."""
    for (n, nm), v in files.items():
        if n == disk and nm.lower() == name.lower():
            return v
    raise SystemExit(f"{name!r} is not on disk {disk}")


def patch(image, offset, want, new, what):
    got = bytes(image[offset:offset + len(want)])
    if got != want:
        raise SystemExit(f"{what} at +{offset:#06x}: expected {want.hex(' ')}, "
                         f"found {got.hex(' ')}")
    image[offset:offset + len(new)] = new


def assemble_driver(name, **defines):
    """u5drv.s (with `defines`) -> (the blob, its symbols, the resident part).

    acme emits one blob from the lowest hole to the end of the resident
    part, with everything between zero filled.  The four pieces are sliced
    out and everything else is checked to be zero: that is what proves no
    piece grew past its end -- the resident part into the sound-effect
    routine at $7B00, a hole into the live code after it."""
    drvbin = os.path.join(BUILD, f"{name}.bin")
    drvsym = os.path.join(BUILD, f"{name}.sym")
    args = [f"-D{k}={v}" for k, v in defines.items()] + [f"-DJOURNAL={regions.journal('u5')[0]}"]
    sh("acme", "-f", "plain", *args, "-I", paths.ASM, "-I", BUILD,
       "-I", HERE, "-o", drvbin, "-l", drvsym, os.path.join(HERE, "u5drv.s"))
    with open(drvbin, "rb") as fh:
        blob = bytearray(fh.read())
    sym = symbols(drvsym)
    origin = HOLES[0][0]
    if sym["u5_drv_end"] > FAST_LIMIT:
        raise SystemExit(f"{name}: the resident driver reaches $7B00")
    pieces = [(FAST_ADDR, sym["u5_drv_end"])]
    for start, limit, end_sym in HOLES:
        if sym[end_sym] > limit:
            raise SystemExit(f"{name}: the hole at {start:#06x} overflows")
        pieces.append((start, sym[end_sym]))
    used = bytearray(len(blob))
    for start, end in pieces:
        used[start - origin:end - origin] = b"\x01" * (end - start)
    stray = [origin + i for i, b in enumerate(blob) if b and not used[i]]
    if stray:
        raise SystemExit(f"{name}: driver bytes outside its pieces at {stray[0]:#06x}")
    return blob, sym, blob[FAST_ADDR - origin:sym["u5_drv_end"] - origin]


def install_driver(fast, subs, blob, sym, driver):
    """The driver into u5siz.o and the holes of temp.subs, and temp.subs'
    jump table pointed at it."""
    # the sound-effect routine at $7B00-$7B56 is live in both builds, so the
    # overlay goes on top of u5siz.o rather than replacing the whole file --
    # and the file keeps its original length, so reloading it can never reach
    # the game's scratch area
    fast[0:len(driver)] = driver
    # the holes go into temp.subs itself, so a reload of it keeps them
    origin = HOLES[0][0]
    for start, limit, end_sym in HOLES:
        piece = blob[start - origin:sym[end_sym] - origin]
        subs[start - SUBS_ADDR:start - SUBS_ADDR + len(piece)] = piece
    for vector, (routine, original) in VECTORS.items():
        off = vector - SUBS_ADDR
        if subs[off] != 0x4C or subs[off + 1] | subs[off + 2] << 8 != original:
            raise SystemExit(f"temp.subs {vector:#06x} is not JMP {original:#06x}")
        target = sym[routine]
        subs[off + 1] = target & 0xFF
        subs[off + 2] = target >> 8
    for addr, original in RECORD_CALLS:
        off = addr - SUBS_ADDR
        if subs[off] | subs[off + 1] << 8 != original:
            raise SystemExit(f"temp.subs {addr:#06x} does not point at {original:#06x}")
        subs[off] = sym["u5_block"] & 0xFF
        subs[off + 1] = sym["u5_block"] >> 8


def asm(src, out, fmt="plain", **defines):
    """acme on games/u5/`src` -> (bytes, symbols); numbers as $hex."""
    args = [f"-D{k}=${v:x}" if isinstance(v, int) else f"-D{k}={v}" for k, v in defines.items()]
    path = os.path.join(BUILD, out)
    sh("acme", "-f", fmt, *args, "-I", paths.ASM, "-I", BUILD,
       "-I", HERE, "-o", path, "-l", path + ".sym", os.path.join(HERE, src))
    with open(path, "rb") as fh:
        return fh.read(), symbols(path + ".sym")


def build_armusic(flash, files, sym):
    """The Action Replay's music: the songs and the stage image (armusic.s,
    with the relocated player) into the flash, and the hook for xyzzy.
    `sym` is the C64 driver's."""
    _load, m = pick(files, 1, "m")
    m = bytes(m)
    songs_flash = flash.add(m[armusic.HEADER[0] - M_ADDR:armusic.SONGS_END - M_ADDR])
    img, rel = armusic.relocate(m, AR_PIECES["PIECE_D"], AR_BASE + AR_TABLE,
                                next_song=AR_BASE + 8 * 3)      # armusic.s ar_next
    with open(os.path.join(BUILD, "arplayer.bin"), "wb") as fh:
        fh.write(img)
    e = rel["entries"]
    defs = dict(AR_PIECES, AR_BASE=AR_BASE, AR_CODE=AR_BASE + AR_TABLE,
                AR_P_INIT=e["init"], AR_P_TICK=e["tick"], AR_P_MUTE=e["mute"],
                AR_P_UNMUTE=e["unmute"], AR_P_SWAP=e["swap"], AR_P_START=rel["start"], AR_HEADER=rel["header"],
                AR_POINTERS=rel["pointers"], AR_MUTEB=rel["mute"], AR_TOP=rel["top"],
                SONGS_FLASH=songs_flash)
    for name in ("tc_enter", "tc_leave", "tc_sendbyte", "tc_send_addr_len", "tc_getbyte",
                 "tc_addr", "tc_len", "tc_fetch", "tc_sb_call", "u5_arget"):
        defs[name] = sym[name]
    stage, ssym = asm("armusic.s", "armusic.bin", **defs)
    assert ssym["arinit"] == AR_STAGE
    for name in ("AR_J_GET", "AR_J_PICK"):     # the driver's jumps into the AR
        assert ssym[name] == sym[name], name
    stage_flash = flash.add(stage)
    hook, _hsym = asm("armhook.s", "armhook.bin", AR_ON=AR_ON, AR_OFF=AR_OFF,
                      STAGE=AR_STAGE, STAGE_FLASH=stage_flash, STAGE_LEN=len(stage),
                      tc_addr=sym["tc_addr"], tc_read=sym["tc_read"])
    return dict(stage=stage, ssym=ssym, stage_flash=stage_flash, songs_flash=songs_flash,
                hook=hook, img=img, rel=rel, songs=armusic.songs(m))


# ---------------------------------------------------------------------------
# The music with the Ultima VI EasyFlash cart in place of an AR (armusic.s
# EF_MUSIC, efhook.s): ultima/ef/efu5.s starts this build's Ultima V from the
# tapecart with it.  Nothing here goes into the tapecart's image: the
# launcher reads the C64 build's segments from the tapecart, makes sure they
# are this build's (`segs` below), and changes them in RAM (`patches`): the
# driver's two writes of the AR's register become the EasyFlash's,
# and xyzzy's hook takes the stage from the cart.
EF_ON, EF_OFF = 0x07, 0x04          # $DE02: 16K mode; off


def build_efmusic(p, bank):
    """For EasyFlash bank `bank`, from parts()'s `p`: the bank's image (the
    jump table, the player with every song and the 2-bit receive at $8000,
    the stage after them), the hook, and what the launcher needs."""
    sym = p["sym"]
    m = bytes([b for k, b in p["bodies"].items() if k[0] == 1 and k[1].lower() == "m"][0])
    img, rel = armusic.relocate(m, AR_PIECES["PIECE_D"], AR_BASE + AR_TABLE,
                                next_song=None, resident=True)
    with open(os.path.join(BUILD, "efplayer.bin"), "wb") as fh:
        fh.write(img)
    e = rel["entries"]
    defs = dict(AR_PIECES, EF_MUSIC=1, AR_BASE=AR_BASE, AR_CODE=AR_BASE + AR_TABLE,
                AR_P_INIT=e["init"], AR_P_TICK=e["tick"], AR_P_MUTE=e["mute"],
                AR_P_UNMUTE=e["unmute"], AR_P_SWAP=e["swap"], AR_P_START=rel["start"],
                AR_MUTEB=rel["mute"])
    for name in ("tc_getbyte", "tc_fetch", "tc_sb_call", "u5_arget"):
        defs[name] = sym[name]
    blob, ssym = asm("armusic.s", "efmusic.bin", **defs)
    assert ssym["arinit"] == AR_STAGE
    for name in ("AR_J_GET", "AR_J_PICK"):     # the driver's jumps into the bank
        assert ssym[name] == sym[name], name
    ar = p["ar"]["ssym"]
    for name in ("aplay", "arestart"):         # temp.subs' jumps into the glue
        assert ssym[name] == ar[name], name
    split = ssym["ar_block"] - AR_STAGE
    stage, block = blob[:split], blob[split:]
    stage_rom = AR_BASE + (len(block) + 0xFF & ~0xFF)
    image = block.ljust(stage_rom - AR_BASE, b"\xff") + stage
    assert AR_BASE + len(image) <= armusic.EF_TOP, f"the bank is {len(image)} bytes"
    hook, _hsym = asm("efhook.s", "efhook.bin", BANK=bank, STAGE_ROM=stage_rom,
                      STAGE_PAGES=(len(stage) + 0xFF) // 0x100, STAGE=AR_STAGE)

    # the C64 build's segments as the tapecart holds them
    flash = image_from(p["blobs"], regions.FLASH_SIZE)
    desc = p["desc"]
    assert desc[:2] == bytes([INIT_ADDR & 0xFF, INIT_ADDR >> 8])
    segs = []
    for i in range(desc[2]):
        row = desc[3 + 7 * i:10 + 7 * i]
        at, length, dest = row[0] << 8 | row[1] << 16, row[2] | row[3] << 8, row[4] | row[5] << 8
        assert row[6] == 0, "efu5.s reads raw segments only"
        segs.append((at, length, dest, bytes(flash[at:at + length])))

    def seg_at(addr, n):
        for _a, length, dest, data in segs:
            if dest <= addr and addr + n <= dest + length:
                return data[addr - dest:addr - dest + n]
        raise SystemExit(f"{addr:#06x} is in no segment")
    patches_ = []
    for addr, new, what in ((sym["u5_armap"] + 4, bytes([0xA9, EF_ON, 0x8D, 0x02, 0xDE]),
                             "u5_armap: lda #AR_ON / sta $DE00"),
                            (sym["u5_arout"], bytes([0xA2, EF_OFF, 0x8E, 0x02, 0xDE]),
                             "u5_arout: ldx #AR_OFF / stx $DE00"),
                            (AR_HOOK[1], hook, "xyzzy's AR hook")):
        old = seg_at(addr, len(new))
        if what.startswith("u5_"):
            want = bytes([new[0], AR_ON if new[0] == 0xA9 else AR_OFF, new[2], 0x00, 0xDE])
            if old != want:
                raise SystemExit(f"{what} at {addr:#06x}: expected {want.hex(' ')}, found {old.hex(' ')}")
        else:
            assert old == p["ar"]["hook"][:len(new)], what
        patches_.append((addr, old, new))
    return dict(image=image, block=block, stage=stage, stage_rom=stage_rom, ssym=ssym,
                hook=hook, img=img, rel=rel, patches=patches_, segs=segs, desc=desc,
                desc_at=regions.desc_offset("u5"), journal=regions.journal("u5")[0],
                opt_at=4 + regions.DESC_INDEX["u5"], caps=caps(), pt_opts=sym["pt_opts"])


def build_c128(flash, files, placed, sym, fast, subs, caps):
    """The C128 launcher and what it loads (launch128.s), into the flash.
    `sym`, `fast` and `subs` are the C128 build of the driver."""

    # subs.128's tables, from the file itself
    load, orig = pick(files, 1, "subs.128")
    assert load == SUBS128_ADDR
    t = lambda a, n: bytes(orig[a - SUBS128_ADDR:a - SUBS128_ADDR + n])
    letters, first, last = t(0x787D, 12), t(0x7889, 11), t(0x7894, 11)
    assert letters == b"CEIMPRSTUVZ\x00", letters
    with open(os.path.join(BUILD, "sub128_data.s"), "w") as fh:
        fh.write("; generated by ultima/games/u5/build.py from disk 1A's subs.128\n")
        for name, data in (("letters", letters), ("first", first), ("last", last),
                           ("kbuf", t(0x7979, 41)), ("tag", t(0x777A, 1))):
            fh.write(f"{name}: !byte " + ", ".join(f"${v:02x}" for v in data) + "\n")
    far, _ = asm("c128far.s", "c128far.bin")
    b1, b1sym = asm("sub128.s", "sub128.bin", U5_C128_LD=sym["u5_c128_ld"],
                    U5_C128_LETTER=sym["u5_c128_letter"])
    # the driver's reads through bank 1: C_PICK/C_GET and C_BACK, one blob
    # from $0113 to slice (c128fast.s)
    ctr, csym = asm("c128fast.s", "c128fast.bin", B1_PICK=b1sym["b1_pick"], B1_GET=b1sym["b1_get"])
    c_pick, c_back = csym["C_PICK"], csym["C_BACK"]
    c_fast = ctr[:csym["c_fast_end"] - c_pick]
    c_backp = ctr[c_back - c_pick:csym["c_back_end"] - c_pick]
    assert sym["C_GET"] == csym["C_GET"] and len(c_fast) == 16 and len(c_backp) == 6
    jt = b1sym["jt"] - 0xE000                   # one entry per slot, 3 apart
    for i, name in enumerate(("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7")):
        assert b1[jt + 3 * i] | b1[jt + 3 * i + 1] << 8 == b1sym[name], name

    SEG_ZX, SEG_B1, SEG_ON = 1, 2, 0x80
    segs = []

    def seg(data, dest, bank1=False):
        packed = zx.crunch(data)
        flags = SEG_ON | (SEG_B1 if bank1 else 0)
        if packed is not None and len(packed) < len(data):
            data, flags = packed, flags | SEG_ZX
        segs.append((flash.add(bytes(data)), len(data), dest, flags))

    m_key = next(k for k in files if k[0] == 1 and k[1].lower() == "m")
    offset, length, mload, mflags = placed[m_key]
    assert mload == M_ADDR, mload
    segs.append((offset, length, M_ADDR, SEG_ON | SEG_B1 | (SEG_ZX if mflags & F_ZX else 0)))
    seg(b1, B1_ORG, bank1=True)
    seg(far, 0x0200)
    seg(c_fast, c_pick)
    seg(c_backp, c_back)
    xyzzy_key = next(k for k in files if k[0] == 1 and k[1].lower() == "xyzzy")
    xoff, xlen, xload, _f = placed[xyzzy_key]
    segs.append((xoff, xlen, xload, SEG_ON))
    seg(subs, SUBS_ADDR)
    seg(fast, FAST_ADDR)
    # What the launcher loads, and the driver's addresses, go in a page at a
    # fixed place (regions.C128_DESC) rather than into the launcher: the
    # launcher is on the player's disk, and has to work with the next build.
    opt_at = 4 + regions.DESC_INDEX["u5"]         # "UCFG", then a byte per game
    w = lambda v: bytes([v & 0xFF, v >> 8])
    desc = bytearray(b"U5C128" + bytes([C128_DESC_VERSION]))
    desc += w(sym["tc_init"]) + w(sym["u5_dirinit"]) + w(sym["pt_opts"])
    desc += bytes([caps, opt_at]) + w(XYZZY_ADDR)
    for a, n, dest, flags in segs:
        desc += bytes([flags, a & 0xFF, (a >> 8) & 0xFF, a >> 16]) + w(n) + w(dest)
    desc += b"\x00"
    assert len(desc) <= regions.PAGE and opt_at < 16
    with open(os.path.join(BUILD, "launch128_data.s"), "w") as fh:
        fh.write("; generated by ultima/games/u5/build.py -- both fixed (regions.py)\n")
        fh.write(f"SETTINGS_AT = ${regions.SETTINGS:x}\nC128_DESC = ${regions.C128_DESC:x}\n")
    prg, lsym = asm("launch128.s", "launch128.prg", fmt="cbm")
    assert prg[:2] == bytes([0x01, 0x1C])
    return dict(prg=prg, addr=flash.add(prg), segs=segs, far=far, b1=b1, b1sym=b1sym,
                c_fast=bytes(c_fast), c_back=bytes(c_backp),
                lsym=lsym, sym=sym, fast=bytes(fast), subs=bytes(subs), desc=bytes(desc))


def parts():
    os.makedirs(BUILD, exist_ok=True)
    disks = {n: D64(disk_path(t)) for n, t in TAGS.items()}

    # (disk, name) -> [load address, payload].  Directory order is preserved:
    # the inline names include patterns as short as `D*` and `G*`, and CBM DOS
    # takes the first directory match, so the order is part of the semantics.
    files = {}
    order = {n: [] for n in disks}
    for n, d in disks.items():
        for name, _t, _tr, _s, _b in d.directory():
            data, ok = d.file(name)
            if not ok:
                raise SystemExit(f"{name} on disk {n} crosses a bad sector")
            files[(n, name)] = [data[0] | data[1] << 8, bytearray(data[2:])]
            order[n].append(name)

    save_from = os.environ.get("U5_SAVE_FROM")
    if save_from:
        print(f"  u5: SAVE SLOTS SEEDED FROM {seed_saves_from(files, save_from)}")

    # ---- motor and xyzzy patches ---------------------------------------
    applied = []
    for fname, addr, want, new, why in MOTOR:
        hits = 0
        for (n, name), (load, body) in files.items():
            if name.lower() != fname.lower():
                continue
            off = addr - load
            if not 0 <= off < len(body):
                raise SystemExit(f"{fname} on disk {n} does not cover {addr:#06x}")
            patch(body, off, bytes([want]), bytes([new]), f"{fname} {why}")
            hits += 1
        if not hits:
            raise SystemExit(f"{fname} is not on any disk")
        applied.append((fname, addr, why, hits))

    for addr, want, new, why in XYZZY_PATCHES:
        for (n, name), (load, body) in files.items():
            if name.lower() == "xyzzy":
                patch(body, addr - load, want, new, f"xyzzy {why}")
        applied.append(("xyzzy", addr, why, 1))

    for fname, addr in MUSIC_GATES:
        hits = 0
        for (n, name), (load, body) in files.items():
            off = addr - load
            if name.lower() == fname and 0 <= off < len(body) and \
                    bytes(body[off:off + 3]) == bytes([0xA5, 0xC8, 0x10]):
                body[off:off + 2] = bytes([0x24, 0xC8])
                body[off + 2] = 0x50
                hits += 1
        if not hits:
            raise SystemExit(f"music gate {fname} {addr:#06x}: not found")
        applied.append((fname, addr, f"music gate: bit $C8 / bvc (x{hits})", hits))
    for fname, addr in C64_GATES:
        hits = 0
        for (n, name), (load, body) in files.items():
            off = addr - load
            if name.lower() == fname and 0 <= off < len(body) and \
                    bytes(body[off:off + 3]) == bytes([0xA5, 0xC8, 0x30]):
                body[off:off + 3] = bytes([0x24, 0xC8, 0x70])
                hits += 1
        if not hits:
            raise SystemExit(f"C64 gate {fname} {addr:#06x}: not found")
        applied.append((fname, addr, f"C64 gate: bit $C8 / bvs (x{hits})", hits))
    for addr, want, new, why in XYZZY_C128_PATCHES:
        load, body = pick(files, 1, "xyzzy")
        patch(body, addr - load, want, new, f"xyzzy {why}")
        applied.append(("xyzzy", addr, why, 1))
    for addr, want, new, why in QS_C128_PATCHES:
        load, body = pick(files, 1, "qs")
        patch(body, addr - load, want, new, f"qs {why}")
        applied.append(("qs", addr, why, 1))

    load, body = files[(1, "TRANSFER")]
    for addr, was, now in TRANSFER_TEXT:
        assert len(was) == len(now), now
        patch(body, addr - load, _hi(was), _hi(now), "transfer prompt")
    applied.append(("transfer", 0x8170, "prompt: the party comes from U4's save", 1))

    load, body = files[(1, "STARTUP")]
    for addr, want, new, why in MENU_PATCHES:
        patch(body, addr - load, want, new, f"startup menu: {why}")
    applied.append(("startup", 0x84ED, "no Number of drives in the menu", 1))

    if os.environ.get("U5_NO_FAST"):        # debug: the original routines, to compare in VICE
        print("  u5: SPEED PATCHES LEFT OUT (U5_NO_FAST)")
    else:
        apply_fast(files)

    # the launcher's X: F7 teleports, B brings a vehicle, appended to MAIN.OUT (u5powers.s)
    for n, defines in tele_sites(files).items():
        blob, _sym = asm("u5powers.s", f"u5powers_{TAGS[n]}.bin", **defines)
        pick(files, n, "MAIN.OUT")[1].extend(blob)
    applied.append(("MAIN.OUT", TELE[2]["TELE"], "F7 teleports, B brings a vehicle, behind X (u5powers.s, 2A and 2B)", 2))

    # ---- driver ---------------------------------------------------------
    patches.check(OPTION_PATCHES, [(f"{n}:{name}", load, bytes(body))
                                   for (n, name), (load, body) in files.items()],
                  option_units())
    fast_key = next(k for k in files
                    if k[0] == 1 and k[1].lower() == "u5siz.o")
    subs_key = next(k for k in files
                    if k[0] == 1 and k[1].lower() == "temp.subs")
    # the C128 build (U5_C128, c128.inc) starts from the same two files
    fast128 = bytearray(files[fast_key][1])
    subs128 = bytearray(files[subs_key][1])
    blob, sym, driver = assemble_driver("u5drv")
    # tc_init and the directory setup are the init stub's (asm/init_u5.s):
    # the C64 driver has no entries of its own at $7700 any more
    if "tc_init" in sym or "u5_dirinit" in sym:
        raise SystemExit("the C64 driver has tc_init or u5_dirinit again")
    fast = files[fast_key][1]
    subs = files[subs_key][1]
    install_driver(fast, subs, blob, sym, driver)

    blob128, sym128, driver128 = assemble_driver("u5drv128", U5_C128=1)
    if driver128[:3 * C128_SLOTS] != bytes([0x20, 0x00, 0x02]) * C128_SLOTS:
        raise SystemExit("the C128 driver does not start with its JSR C_FAR entries")
    install_driver(fast128, subs128, blob128, sym128, driver128)

    initbin = os.path.join(BUILD, "init_u5.bin")
    tcsyms.tcinit_include(os.path.join(BUILD, "u5drv.sym"), os.path.join(BUILD, "u5_tcinit.s"),
                          extra=("tc_enter", "tc_sendbyte", "tc_leave", "u5_dirpage", "u5_dircount",
                                 "CMD_DIR_SETPARAMS", "DIR_NAMELEN", "DIR_DATALEN"))
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
       "-o", initbin, "-l", os.path.join(BUILD, "init_u5.sym"),
       os.path.join(paths.ASM, "init_u5.s"))
    with open(initbin, "rb") as fh:
        init = fh.read()

    # ---- lay the flash out ----------------------------------------------
    # Everything the game loads by name is a zx02 stream, packed end to end
    # in one blob with the sectors below -- nothing needs page alignment any
    # more, the directory holds 24-bit addresses.  The exceptions stay raw:
    # the save slots (the game writes them) and the three files the menu
    # also loads as boot segments, which it cannot decode.
    flash = Layout(regions.data_base("u5"))
    save_base = regions.save_base("u5")
    streams = bytearray()
    stream_at = {}                  # stored bytes -> offset inside `streams`

    def stream(data):
        key = bytes(data)
        if key not in stream_at:
            stream_at[key] = len(streams)
            streams.extend(key)
        return stream_at[key]

    placed, slot, seeded = {}, 0, []
    pending = {}                    # (disk, name) -> (stream offset, length, load, flags)
    for n in sorted(order):
        for name in order[n]:
            load, body = files[(n, name)]
            if (n, name.upper()) in WRITABLE:
                if (n, name.upper()) == (2, "ROSTER"):
                    body = body[:ROSTER_LEN]
                base = save_base + slot * SAVE_SLOT
                if len(body) + 0x100 > SAVE_SLOT:
                    raise SystemExit(f"{name} on disk {n} does not fit a slot")
                flash.place_at(base, SAVE_MAGIC +
                               bytes([len(body) & 0xFF, len(body) >> 8]))
                flash.place_at(base + 0x100, bytes(body))
                placed[(n, name)] = (base, len(body), load, F_WRITE)
                seeded.append((n, name, len(body)))
                slot += 1
            elif (n, name) in (fast_key, subs_key) or \
                    (n == 1 and name.lower() == "xyzzy"):
                continue          # raw, placed last: boot segments too
            else:
                packed = zx.crunch(body)
                if packed is not None and len(packed) < len(body):
                    pending[(n, name)] = (stream(packed), len(packed), load, F_ZX)
                else:
                    pending[(n, name)] = (stream(body), len(body), load, 0)
    if len(seeded) != len(WRITABLE):
        raise SystemExit(f"save slots seeded: {seeded}, expected {sorted(WRITABLE)}")

    # ---- the raw-sector runs, one zx02 stream per block ------------------
    # A block map per disk replaces the arithmetic: four bytes per block of
    # the run, the stream's 24-bit address and its length (0 = a raw page).
    runs = sector_runs(disks)
    rfirst, rmaps, sector_bytes = [], {}, 0
    for n in sorted(disks):
        if runs[n] is None:
            rfirst.append(0xFFFF)     # every block is "below the run": refused
            continue
        first, count = runs[n]
        entries = []
        for b in range(first, first + count):
            page = bytes(disks[n].sector(*D64.from_linear(b)))
            packed = zx.crunch(page)
            if len(packed) <= 255:
                entries.append((stream(packed), len(packed)))
            else:
                entries.append((stream(page), 0))
            sector_bytes += 256
        rmaps[n] = entries
        rfirst.append(first)
    assert all(first + count == TOTAL_BLOCKS
               for first, count in (r for r in runs.values() if r)), runs

    # The Program disk (1) has no raw-sector area, so its entry is free for
    # "the Ultima IV disk" that `transfer` asks for (see u5_checkid): a run
    # from U4's block 273 (track 14 sector 0, the party) whose map points at
    # U4's own save slots on the cart, raw.  Blocks past the two it reads
    # point at the first -- every run must reach the last block, since the
    # driver checks only the lower bound.
    assert runs[1] is None, "disk 1 has a raw-sector area of its own now"
    rfirst[0] = U4_PARTY_BLOCK
    u4_slot = lambda b: regions.save_base("u4") + (b - U4_SAVE_FIRST) * regions.ERASE_BLOCK
    u4_map = [u4_slot(b) if b < U4_SAVE_FIRST + U4_SAVE_COUNT else u4_slot(U4_PARTY_BLOCK)
              for b in range(U4_PARTY_BLOCK, TOTAL_BLOCKS)]
    u4_map_addr = flash.add(b"".join(bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16, 0])
                                     for a in u4_map))

    stream_base = flash.add(bytes(streams))
    for key, (off, length, load, flags) in pending.items():
        placed[key] = (stream_base + off, length, load, flags)
    rmap_addr = [0] * 8
    rmap_addr[0] = u4_map_addr
    for n, entries in rmaps.items():
        table = b"".join(bytes([(stream_base + o) & 0xFF, ((stream_base + o) >> 8) & 0xFF,
                                (stream_base + o) >> 16, ln]) for o, ln in entries)
        rmap_addr[n - 1] = flash.add(table)

    for name, values in (("u5_rfirst_lo", [v & 0xFF for v in rfirst]),
                         ("u5_rfirst_hi", [v >> 8 for v in rfirst]),
                         ("u5_rmap_lo", [a & 0xFF for a in rmap_addr]),
                         ("u5_rmap_mid", [(a >> 8) & 0xFF for a in rmap_addr]),
                         ("u5_rmap_hi", [a >> 16 for a in rmap_addr])):
        for body, sy in ((subs, sym), (subs128, sym128)):
            off = sy[name] - SUBS_ADDR
            assert body[off:off + 8] == b"\xff" * 8, f"{name} placeholder moved"
            body[off:off + 8] = bytes(values)

    # the options' patch table, streamed from here after every named load
    pt_table = patches.table(OPTION_PATCHES)
    pt_at = flash.add(pt_table)
    for body, sy in ((subs, sym), (subs128, sym128)):
        off = sy["pt_where"] - SUBS_ADDR
        assert body[off:off + 5] == b"\xff" * 5, "pt_where placeholder moved"
        body[off:off + 5] = bytes([pt_at & 0xFF, (pt_at >> 8) & 0xFF, pt_at >> 16,
                                   len(pt_table) & 0xFF, len(pt_table) >> 8])

    # ---- the directory the cart searches --------------------------------
    # One entry per (disk, file), plus one per wildcard pattern the code
    # actually uses.  DIR_LOOKUP matches binary with no wildcards, but it does
    # not need them: the directories on the original disks are fixed, so what
    # `D*` resolves to on a given disk is a build-time fact.  Resolving it
    # here is also what keeps the directory small -- emitting an alias for
    # every possible prefix would multiply it tenfold, and the cart scans it
    # linearly.
    patterns = inline_patterns(files)
    names = []                      # (disk, entry name, file the entry means)
    for n in sorted(order):
        for name in order[n]:
            names.append((n, name, name))
        for pat in patterns:
            target = resolve(pat, order[n])
            if target is not None:
                names.append((n, pat, target))
    aliases = sum(1 for n, name, target in names if name != target)

    # The driver file has to be placed after everything that patches it, and
    # the directory after the driver file -- but the driver needs to know
    # where the directory is.  Its size does not depend on any of that, so
    # reserve it here and fill it in below.
    dir_off = flash.reserve(len(names) * (DIR_NAMELEN + DIR_DATALEN))

    for body, sy in ((fast, sym), (fast128, sym128)):
        off = sy["u5_dirpage"] - FAST_ADDR
        assert body[off:off + 4] == b"\xff\xff\xff\xff", "dir placeholders moved"
        body[off] = (dir_off >> 8) & 0xFF
        body[off + 1] = (dir_off >> 16) & 0xFF
        body[off + 2] = len(names) & 0xFF
        body[off + 3] = len(names) >> 8

    xyzzy_key = (1, next(nm for nm in order[1] if nm.lower() == "xyzzy"))
    # the Action Replay's music: temp.subs (the C64's) to its play and
    # restart, xyzzy's C64 path to the hook
    ar = build_armusic(flash, files, sym)
    off = AR_PLAY_JMP - SUBS_ADDR
    assert bytes(subs[off:off + 3]) == bytes([0x4C, 0x03, 0x77]), "temp.subs $76BC"
    subs[off + 1:off + 3] = ar["ssym"]["aplay"].to_bytes(2, "little")
    at, was = AR_RESTART
    off = at - SUBS_ADDR
    assert bytes(subs[off:off + 7]) == was, "temp.subs $76BF"
    rts = 0x76B7                    # the play gate's RTS
    assert subs[rts - SUBS_ADDR] == 0x60
    subs[off:off + 7] = bytes([0x24, 0xC8, 0x50, (rts - (at + 4)) & 0xFF, 0x4C]) + \
        ar["ssym"]["arestart"].to_bytes(2, "little")
    xload, xbody = files[xyzzy_key]
    jmp, hook_at = AR_HOOK
    assert bytes(xbody[jmp - xload:jmp - xload + 3]) == bytes([0x4C, 0xD5, 0x20]), "xyzzy $208D"
    xbody[jmp - xload + 1:jmp - xload + 3] = hook_at.to_bytes(2, "little")
    xbody[hook_at - xload:hook_at - xload + len(ar["hook"])] = ar["hook"]
    for key, body in ((fast_key, fast), (subs_key, subs),
                      (xyzzy_key, files[xyzzy_key][1])):
        placed[key] = (flash.add(bytes(body)), len(body), files[key][0], 0)

    entries = [(n, name, placed[(n, target)]) for n, name, target in names]

    directory = bytearray()
    for n, name, (offset, length, load, flags) in entries:
        raw = name.encode("ascii")
        if len(raw) > DIR_NAMELEN - 1:
            raise SystemExit(f"{name!r} does not fit {DIR_NAMELEN - 1} bytes")
        directory += bytes([n]) + raw.ljust(DIR_NAMELEN - 1, b"\x00")
        directory += bytes([offset & 0xFF, (offset >> 8) & 0xFF, offset >> 16,
                            length & 0xFF, length >> 8,
                            load & 0xFF, load >> 8, flags])
    flash.place_at(dir_off, bytes(directory))

    segments = [
        (placed[xyzzy_key][0], placed[xyzzy_key][1], XYZZY_ADDR),
        (placed[subs_key][0], len(subs), SUBS_ADDR),
        (placed[fast_key][0], len(fast), FAST_ADDR),
        (flash.add(init), len(init), INIT_ADDR),
    ]

    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, dest in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, dest >> 8, 0])
    assert len(desc) <= 64, len(desc)

    c128 = build_c128(flash, files, placed, sym128, fast128, subs128,
                      caps=caps())

    save_end = save_base + slot * SAVE_SLOT
    regions.check("u5", flash.cursor, save_end)
    page = dict(U5_ROSTER=[b for (n, name), (b, _l, _d, _f) in placed.items()
                           if (n, name.upper()) == (2, "ROSTER")][0],
                # the C128 launcher, which the page saves to a disk
                C128_DATA=c128["addr"] + 2, C128_LEN=len(c128["prg"]) - 2,
                C128_LOAD=c128["prg"][0] | c128["prg"][1] << 8,
                C128_BLOCKS=-(-len(c128["prg"]) // 254))       # (254 bytes a block)
    assert page["C128_BLOCKS"] < 10, "the page prints one digit"
    # export/import (xfer.py): the six files, five on 2A and TLIST on 2B,
    # scratched and saved as the game does.  Lengths as the game writes
    # them: ROSTER 1024 (1025 as shipped), TLIST 256 or 512 (U5 research).
    lengths = {"ROSTER": (1024, 1025), "PRTY.DATA": (48, 48), "LIST": (512, 512),
               "SLIST": (512, 512), "TLIST": (256, 512)}
    def xslot(n, name):
        (base, _l, load, _f), = [v for (dn, nm), v in placed.items()
                                 if (dn, nm.upper()) == (n, name)]
        return xfer.File(base, xfer.BYTES, name, load, *lengths[name])
    xf = [xfer.Disk("Britannia (2A)", disks[2].sector(18, 0),
                    [xslot(2, n) for n in ("ROSTER", "PRTY.DATA", "LIST", "SLIST", "TLIST")]),
          xfer.Disk("Underworld (2B)", disks[8].sector(18, 0), [xslot(8, "TLIST")])]
    options = dict(caps=caps(), addr=sym["pt_opts"])
    # Journey onward (the launcher): the original goes straight to it when J
    # is held as `xyzzy` starts ($2109 LDA $C5 / ... / CMP #$22); make that
    # read say J.  xyzzy is a boot segment, in RAM before its init runs.
    xload, xbody = next(v for (n, nm), v in files.items() if (n, nm.upper()) == (1, "XYZZY"))
    assert bytes(xbody[0x2109 - xload:0x210B - xload]) == bytes([0xA5, 0xC5]), "xyzzy $2109"
    journey = [(0x2109, 0xA9), (0x210A, 0x22)]      # LDA $C5 -> LDA #$22
    return dict(name="ULTIMA V", blobs=list(flash.blobs), desc=bytes(desc), page=page, c128=c128,
                pt_table=pt_table, pt_at=pt_at,
                ar=ar, sym=sym,
                options=options, xfer=xf, journey=journey,
                save_end=save_end, used=flash.used, cursor=flash.cursor,
                files=len(files), unique=len(set(o for o, _l, _d, _f in placed.values())),
                applied=applied, driver=len(driver), holes=sum(sym[e] - a for a, _l, e in HOLES),
                runs=runs, sector_bytes=sector_bytes, rmaps=rmaps, rmap_addr=rmap_addr,
                u4_map=u4_map, rfirst=rfirst,
                stream_base=stream_base, streams=len(streams), dir_off=dir_off,
                targets={(n, name): target for n, name, target in names},
                bodies={k: bytes(v[1]) for k, v in files.items()},
                loads={k: v[0] for k, v in files.items()},
                seeded=seeded, slots=slot, entries=len(entries),
                aliases=aliases, patterns=patterns, directory=len(directory))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "ultima5.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(regions.desc_offset("u5"), p["desc"]),
                                (regions.C128_DESC, p["c128"]["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="ULTIMA 5", flash=image_from(blobs, p["save_end"]))
    img.write(out, trim=False)
    print(f"{out}")
    print(f"  data {regions.data_base('u5'):#08x}-{p['cursor']:#08x} "
          f"({p['used'] / 1024:.1f} KiB: {p['files']} files on 8 disks, "
          f"{p['unique']} unique)")
    print(f"  driver {p['driver']} bytes at {FAST_ADDR:#06x} "
          f"({0x7B00 - FAST_ADDR - p['driver']} spare before the sound routine), "
          f"{p['holes']} more in temp.subs")
    print(f"  saves at {regions.save_base('u5'):#08x}, {p['slots']} slots of "
          f"{SAVE_SLOT // 1024} KiB: "
          + ", ".join(f"{n}/{nm} ({sz}b)" for n, nm, sz in p['seeded']))
    print(f"  cart directory: {p['entries']} entries in {p['directory'] / 1024:.1f} KiB "
          f"({p['aliases']} of them wildcard aliases for "
          f"{len(p['patterns'])} patterns)")
    print(f"  raw sector runs: {p['sector_bytes'] / 1024:.1f} KiB -- "
          + ", ".join(f"{n}:{r[0]}+{r[1]}" if r else f"{n}:none"
                      for n, r in sorted(p['runs'].items())))
    for fname, addr, why, hits in p["applied"]:
        print(f"  patched {fname} {addr:#06x} x{hits}: {why}")


if __name__ == "__main__":
    main()
