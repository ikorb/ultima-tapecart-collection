#!/usr/bin/env python3
"""Build the Ultima 2 flash layout.

Files are stored individually and deduplicated, not as whole disk images:
Ultima 2 addresses everything by name through four SUBS jump-table vectors,
so a name -> flash page table is all the driver needs.  121 directory entries
collapse to 70 unique read-only blobs (the MONX/MOBX templates are copies of
each other, several MON files are identical, and SHAPES and MONSTERS appear
on both disks).

Both disks carry twelve same-named files with different contents, so the
table carries a disk number per entry and the driver picks with $8E37 -- the
planet number in the player record, which is zero exactly when the game
expects the Player disk.  See u2drv.s.

Writable files -- MOB xx and MON xx on the player disk, plus the player
record at raw T35/S16 -- are seeded raw in the game data with the original
contents, so a fresh cart behaves like fresh disks, and what the game
writes goes to a write log of two 16 KiB halves in the save region
(u2log.s; ultima/launcher/u2log.py is its host model) -- a 4 KiB erase
block each would be 108 KiB for 6.5 KiB of data.
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
from ultima.launcher import u2log
from ultima.launcher import xfer

BUILD = paths.BUILD

# 1 = the Galactic disk ($8E37 != 0), 2 = the Player disk ($8E37 == 0)
DISKS = {1: paths.disk("u2a"), 2: paths.disk("u2b")}

SUBS_ADDR, INTRO_ADDR = 0x4000, 0xC000
DRIVER_ADDR, INIT_ADDR = 0xB100, 0x0200
LOG_ADDR = 0xD000                # the save log's code, under I/O (u2log.s)
# the launcher's X (u2powers.s) in SUBS' disk block code, dead since its two
# vectors ($40AB, $40AE) go to the driver; the RNG follows at $4F79
POWERS_ADDR, POWERS_LIMIT = 0x4E6A, 0x4F79

# the four jump-table entries that are the whole seam
VECTORS = {0x408D: ("u2_load", 0x4B1C),      # LOAD "name" -> addr
           0x4090: ("u2_save", 0x4B55),      # SAVE "name" <- start..end
           0x40AB: ("u2_block", 0x4E6A),     # raw U1/U2 block
           0x40AE: ("u2_cmdchan", 0x4F2D)}   # OPEN 15,8,15

REC_TRACK, REC_SECTOR = 35, 16
NAME_LEN = 8
ENTRY = 13
F_WRITE = 0x80
F_COMP = 0x40


# ---------------------------------------------------------------------------
# Patches.  Each is (file, runtime address, expected bytes, replacement, why).
#
# The copy protection reads track 18 sector 18 and requires the drive to
# report a READ ERROR -- $C034 tests for ASCII '2'.  Stub the routine to
# return that directly; the alternative, letting the read reach the driver,
# would mean inventing a failure for a sector that is not in flash at all.
#
# The two disk-swap prompts are the same kind of thing the U3 port removed:
# print, wait for F1, carry on.  With every file in flash there is nothing to
# swap, so jump straight to the code after the wait.  Note $C9C0 is also the
# retry target of the "is this a player disk" loop at $C9F8 -- safe only
# because the seeded record has $8EFF = 0, which parts() asserts.
#
# $7B42 is the wrong-disk check: it reads T35/S16 into $1000 and compares the
# sector's marker byte with $8E37.  A cartridge always has the right disk, so
# skip the probe and take the success path.
PATCHES = [
    ("INTRO",  0xCED6, bytes([0xA9, 0x12, 0x85, 0xFB, 0x85, 0xFC]),
     bytes([0xA9, 0x32, 0x60]), "track-18 copy protection -> return '2'"),
    ("INTRO",  0xC9C0, bytes([0xA2, 0x04, 0xA0, 0x0C, 0x20, 0x45, 0x40]),
     bytes([0x4C, 0xF2, 0xC9]), '"INSERT PLAYER DISK" prompt'),
    ("INTRO",  0xCE89, bytes([0xA0, 0x0D, 0xA2, 0x03, 0x20, 0x45, 0x40]),
     bytes([0x4C, 0xBC, 0xCE]), '"INSERT PROGRAM DISK" prompt'),
    # "THIS DISK HAS A PLAYER NAMED ... ANY OTHER TO STOP": on the original,
    # stopping goes back to "insert player disk", for another disk.  With
    # that prompt patched out it would find the same player at once and ask
    # again, for ever.  Stopping goes back to the
    # title sequence instead, which shows <P> play / <C> make a player
    # ($C093: after the STARS load, so nothing is loaded twice).
    ("INTRO",  0xCAB9, bytes([0x4C, 0xB4, 0xC9]),
     bytes([0x4C, 0x93, 0xC0]), '"any other key to stop" -> back to the title'),
    ("ULTIMA", 0x7B42, bytes([0x20, 0xAB, 0x40, 0xAD, 0xFF, 0x10]),
     bytes([0x4C, 0xA5, 0x7B]), '"WRONG DISK!!" check'),
    # ULTIMA's entry point is this prompt: $CED3 jumps to $5000, which sets
    # the screen up, asks for the player disk, waits for F1 and only then
    # reads the record.  Skip just the message and the wait ($501A onwards),
    # keeping the screen setup at $5000-$5019 that the rest of the game
    # expects to have run.
    ("ULTIMA", 0x501A, bytes([0x20, 0x06, 0x40, 0xC9, 0xCE]),
     bytes([0x4C, 0x48, 0x50]), '"INSERT PLAYER DISK" prompt in ULTIMA'),
    # The footstep's waits (u2step.s): on foot $6B04 is a fixed loop of 42.5k
    # cycles between the two clicks, on a horse $6AF4 the same after the one.
    # The IRQ plays the clicks (STEP_HOOKS, SUBS_HOOKS): jump past the loop,
    # and on foot past the second JSR $4021.
    ("ULTIMA", 0x6B04, bytes.fromhex("a2 ff a0 20 88 d0 fd ca d0 f8 20 21 40"),
     bytes([0x4C, 0x11, 0x6B]), "the footstep's pause, on foot"),
    ("ULTIMA", 0x6AF4, bytes.fromhex("a2 ff a0 20 88 d0 fd ca d0 f8 4c 94 6b"),
     bytes([0x4C, 0x94, 0x6B]), "the footstep's pause, on a horse"),
]
BASE = {"INTRO": INTRO_ADDR, "ULTIMA": 0x5000, "SUBS": SUBS_ADDR}

# The launcher's options (patches.py, asm/patch.s), all in ULTIMA.  ULTIMA
# is loaded once, by INTRO, which then jumps to it at $CED3: that JMP goes to
# the driver's u2_go instead, which applies them and jumps on.  From the U2
# research, checked against a disassembly:
#   food: four BCD subtractions from $8E1D-$8E1F, each SBC #n -> SBC #$00:
#         a pass ($5163, 0.10), a dungeon turn ($5948 LDA #$10 / JSR $5953),
#         and a move ($6B11 and $6B94, 0.19 each).  Gremlins are elsewhere.
#   pass: three keyboard timeouts, each made to wait for a key: the overworld
#         round counter ($5151 INC $22 / BNE $512C -> LDA #$01), the dungeon
#         countdown ($6D11 DEY / BNE $6CFE -> JMP $6CFE) and the direction
#         prompt ($692B INC $20 / BNE $691E -> LDA #$01).
INTRO_GO = 0xCED3               # JMP $5000
# F1 tells where, F7 teleports, B brings a transport (u2powers.s, the
# launcher's X): hooks always in, to code that tests pw_on.  (address, original, symbol, opcode)
POWER_HOOKS = [
    (0x5233, "4c 02 67", "pw_key", 0x4C),      # a key not a command: ILLEGAL COMMAND!
    (0x72CD, "20 06 40", "pw_board", 0x20),    # Board, nothing here: JSR $4006 " WHAT?"
]
# Counts stop at 99 and 9999 (u2clamp.s, the launcher's V): every BCD add to
# the player record ends in an STA that drops the carry out of the top digit
# (99 + 1 = 0).  Each is a JSR to code that tests cl_on; the attribute's
# four ADCs ($7F6C-$7F79) a JMP, which comes back at $7F7A.
CLAMP_HOOKS = [
    (0x713E, "8d 22 8e", "cl_gld", 0x20),      # a kill's gold
    (0x7248, "8d 22 8e", "cl_gld", 0x20),      # ... the other way
    (0x7932, "8d 22 8e", "cl_gld", 0x20),      # a chest's gold
    (0x7168, "8d 20 8e", "cl_exp", 0x20),      # a kill's experience
    (0x7270, "8d 20 8e", "cl_exp", 0x20),      # ... the other way
    (0x5DBF, "8d 1d 8e", "cl_fod", 0x20),      # food: the shop's 100
    (0x817E, "8d 1d 8e", "cl_fod", 0x20),      # ... Steal's
    (0x64AF, "9d 40 8e", "cl_wpn", 0x20),      # a weapon: the shop
    (0x7890, "9d 40 8e", "cl_wpn", 0x20),      # ... picked up
    (0x7F43, "9d 40 8e", "cl_wpn", 0x20),      # ... HERE TAKE THIS!
    (0x81CB, "9d 40 8e", "cl_wpn", 0x20),      # ... Steal
    (0x639F, "9d 60 8e", "cl_arm", 0x20),      # armour: the shop
    (0x78C2, "9d 60 8e", "cl_arm", 0x20),      # ... picked up
    (0x81A4, "9d 60 8e", "cl_arm", 0x20),      # ... Steal
    (0x5F34, "9d 80 8e", "cl_spl", 0x20),      # spells, five: a shop
    (0x6043, "9d 80 8e", "cl_spl", 0x20),      # ... the other
    (0x70AB, "9d a0 8e", "cl_itm", 0x20),      # an item: a dungeon's chest
    (0x70F7, "9d a0 8e", "cl_itm", 0x20),      # ... another chest
    (0x70DA, "8d 2e 8e", "cl_trc", 0x20),      # torches, 1-4: a chest
    (0x707D, "8d 2f 8e", "cl_key", 0x20),      # keys, two: a chest
    (0x7098, "8d 30 8e", "cl_tol", 0x20),      # tools: a chest
    (0x70C8, "8d a5 8e", "cl_hlm", 0x20),      # helms: a chest
    (0x7961, "8d af 8e", "cl_tri", 0x20),      # tri-lithium: a chest
    (0x7F6C, "bd 15 8e", "cl_att", 0x4C),      # an attribute: ALAKAZAM!
]
# The footstep from the raster IRQ (u2step.s): a move's click, its gate's
# changes from SUBS' IRQ tail, and every effect made to let a click in
# flight finish first.
STEP_HOOKS = [
    (0x6B01, "20 21 40", "st_foot", 0x20),     # on foot: JSR $4021
    (0x6AF1, "20 21 40", "st_horse", 0x20),    # a horse
]
ULTIMA_HOOKS = POWER_HOOKS + CLAMP_HOOKS + STEP_HOOKS
SUBS_HOOKS = [
    (0x47A9, "e6 2d d0", "st_tick", 0x4C),     # the IRQ's tail: INC $2D / BNE $47AF
    (0x40A2, "4c bc 4c", "st_fx", 0x4C),       # the SID block writer: every effect
]
# what st_foot and st_tick take from SUBS: $4021's effect, two blocks for
# $40A2 (their data at $4DDE and $4DEA) and the gate off; the tail after INC $2E
STEP_SUBS = [(0x4021, "4c d9 4d"), (0x4DD9, "20 a2 40 15 d4"), (0x4DE5, "20 a2 40 0e d4"),
             (0x4DF1, "a9 80 20 9f 40 a9 80 8d 12 d4 60"), (0x47AC, "02 e6 2e a5 4d")]
OPTION_PATCHES = [
    patches.Patch(patches.FOOD, 0x5165, bytes.fromhex("ad1f8ee90a"),
                  bytes.fromhex("ad1f8ee900"), "food: pass"),
    patches.Patch(patches.FOOD, 0x5948, bytes.fromhex("a910205359"),
                  bytes.fromhex("a900205359"), "food: dungeon"),
    patches.Patch(patches.FOOD, 0x6B13, bytes.fromhex("ad1f8ee919"),
                  bytes.fromhex("ad1f8ee900"), "food: move"),
    patches.Patch(patches.FOOD, 0x6B96, bytes.fromhex("ad1f8ee919"),
                  bytes.fromhex("ad1f8ee900"), "food: move 2"),
    patches.Patch(patches.PASS, 0x5151, bytes.fromhex("e622d0d7"),
                  bytes.fromhex("a901d0d7"), "pass: overworld"),
    patches.Patch(patches.PASS, 0x6D11, bytes.fromhex("88d0ea"),
                  bytes.fromhex("4cfe6c"), "pass: dungeon"),
    patches.Patch(patches.PASS, 0x692B, bytes.fromhex("e620d0ef"),
                  bytes.fromhex("a901d0ef"), "pass: direction"),
    # torch: Ignite ($798A, "IGNITE TORCH") in a dungeon with torches left
    # ($8E2E, BCD) does SED / SEC / LDA $8E2E / SBC #$01 / STA $8E2E, then
    # lights ($27 = 150): SBC #$00 keeps the count.  (The only other store
    # to $8E2E, $70DA, is a shop's.)
    patches.Patch(patches.TORCH, 0x79AF, bytes.fromhex("ad2e8ee901"),
                  bytes.fromhex("ad2e8ee900"), "torch: ignite"),
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


def writable(name):
    """MOB xx and MON xx on the player disk are the only files the game saves."""
    return name.startswith("MOB ") or name.startswith("MON ")


def parts():
    os.makedirs(BUILD, exist_ok=True)
    disks = {n: D64(f) for n, f in DISKS.items()}


    # the error map is the copy protection; its one flagged sector must be there
    # -- when there is one: the release's stand-ins carry none (docs/developer/disks.md)
    if disks[1].errmap:
        bad = disks[1].bad_sectors()
        assert bad == [(18, 18, 5)], f"disk A's error map is {bad}, expected one T18/S18"

    files = {}                       # (disk, name) -> payload
    for number, d in disks.items():
        for name, _t, _tr, _s, _b in d.directory():
            data, ok = d.file(name)
            if not ok:
                raise SystemExit(f"{name} on disk {number} crosses a bad sector")
            files[(number, name)] = bytearray(data[2:])   # the PRG header is
                                                          # discarded by SETLFS
    # ---- patches --------------------------------------------------------
    applied = []
    for fname, addr, want, new, why in PATCHES:
        for number in disks:
            key = (number, fname)
            if key not in files:
                continue
            img = files[key]
            off = addr - BASE[fname]
            got = bytes(img[off:off + len(want)])
            if got != want:
                raise SystemExit(f"{fname} on disk {number} at {addr:#06x}: expected "
                                 f"{want.hex(' ')}, found {got.hex(' ')} ({why})")
            img[off:off + len(new)] = new
            applied.append((number, fname, addr, why))
    assert len(applied) == len(PATCHES), applied

    # ---- the driver -----------------------------------------------------
    drvbin = os.path.join(BUILD, "u2drv.bin")
    drvsym = os.path.join(BUILD, "u2drv.sym")
    with open(os.path.join(BUILD, "u2_patches.s"), "w") as fh:
        fh.write(patches.asm("PT_TAB", OPTION_PATCHES))
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD, "-I", HERE,
       "-o", drvbin, "-l", drvsym, os.path.join(HERE, "u2drv.s"))
    with open(drvbin, "rb") as fh:
        blob = fh.read()
    sym = symbols(drvsym)
    # one blob from $B100 to the log's end: the driver, a hole to $D000, the
    # save log in the RAM under I/O (u2log.s) -- two segments
    driver = bytearray(blob[:sym["u2_end"] - DRIVER_ADDR])
    hole = blob[sym["u2_end"] - DRIVER_ADDR:LOG_ADDR - DRIVER_ADDR]
    assert not any(hole), "the driver runs into the save log's segment"
    logseg = bytearray(blob[LOG_ADDR - DRIVER_ADDR:sym["lg_end"] - DRIVER_ADDR])
    # the launcher's X, assembled on its own for SUBS; its flag, pw_on, is the
    # driver's (the launch poke's target)
    pwbin = os.path.join(BUILD, "u2powers.bin")
    pwsym = os.path.join(BUILD, "u2powers.sym")
    sh("acme", "-f", "plain", f"-Dpw_on={sym['pw_on']}",
       "-o", pwbin, "-l", pwsym, os.path.join(HERE, "u2powers.s"))
    with open(pwbin, "rb") as fh:
        powers = fh.read()
    psym = symbols(pwsym)
    assert psym["pw_key"] == POWERS_ADDR and psym["pw_end"] <= POWERS_LIMIT, psym
    sym.update(psym)

    # ---- INTRO hands over to ULTIMA through the options -------------------
    intro = files[(1, "INTRO")]
    off = INTRO_GO - INTRO_ADDR
    if bytes(intro[off:off + 3]) != bytes([0x4C, 0x00, 0x50]):
        raise SystemExit(f"INTRO {INTRO_GO:#06x} is not JMP $5000")
    intro[off + 1:off + 3] = bytes([sym["u2_go"] & 0xFF, sym["u2_go"] >> 8])
    ultima = files[(1, "ULTIMA")]
    for at, orig, name, op in ULTIMA_HOOKS:
        off = at - 0x5000
        if bytes(ultima[off:off + 3]) != bytes.fromhex(orig):
            raise SystemExit(f"ULTIMA ${at:04x} is not {orig}: {bytes(ultima[off:off + 3]).hex(' ')}")
        ultima[off:off + 3] = bytes([op, sym[name] & 0xFF, sym[name] >> 8])
    # ULTIMA is the only thing in memory there when u2_go runs
    patches.check(OPTION_PATCHES, [("ULTIMA", 0x5000, bytes(files[(1, "ULTIMA")]))],
                  {p.what: {"ULTIMA"} for p in OPTION_PATCHES})

    # ---- repoint the four jump-table vectors ----------------------------
    subs = files[(1, "SUBS")]
    for vector, (routine, original) in VECTORS.items():
        off = vector - SUBS_ADDR
        if subs[off] != 0x4C or subs[off + 1] | subs[off + 2] << 8 != original:
            raise SystemExit(f"SUBS {vector:#06x} is not JMP {original:#06x}")
        target = sym[routine]
        subs[off + 1] = target & 0xFF
        subs[off + 2] = target >> 8
    for at, orig in STEP_SUBS:
        off = at - SUBS_ADDR
        if bytes(subs[off:off + len(bytes.fromhex(orig))]) != bytes.fromhex(orig):
            raise SystemExit(f"SUBS ${at:04x} is not {orig}")
    for at, orig, name, op in SUBS_HOOKS:
        off = at - SUBS_ADDR
        if bytes(subs[off:off + 3]) != bytes.fromhex(orig):
            raise SystemExit(f"SUBS ${at:04x} is not {orig}: {bytes(subs[off:off + 3]).hex(' ')}")
        subs[off:off + 3] = bytes([op, sym[name] & 0xFF, sym[name] >> 8])
    subs[POWERS_ADDR - SUBS_ADDR:POWERS_ADDR - SUBS_ADDR + len(powers)] = powers

    initbin = os.path.join(BUILD, "init_u2.bin")
    sh("acme", "-f", "plain", "-o", initbin,
       os.path.join(paths.ASM, "init_u2.s"))
    with open(initbin, "rb") as fh:
        init = fh.read()

    # ---- lay the flash out ----------------------------------------------
    flash = Layout(regions.data_base("u2"))
    save_base = regions.save_base("u2")

    # The player record: raw track 35 sector 16, no directory entry.  Disk B's
    # copy is all zeroes -- a valid player disk with no character on it.
    # Its seed and the writable files' are raw pages in the game data: the
    # log (u2log.s) holds whatever the game writes, and a unit it does not
    # hold reads as its seed.
    record = disks[2].sector(REC_TRACK, REC_SECTOR)
    if record[0xFF] != 0:
        raise SystemExit("the seeded player record is not marked as a player "
                         "disk; the patched $C9C0 loop would never exit")
    rec_page = flash.add(bytes(record)) >> 8

    table = bytearray()
    entries = []
    slot_of = {}                # a writable file's name -> its seed
    unit_of = {}                # ... and its unit in the log: index + 1
    for (number, name) in sorted(files, key=lambda k: (k[1], k[0])):
        data = bytes(files[(number, name)])
        wr = number == 2 and writable(name)
        comp = False
        if wr:
            # the log copies and writes whole pages
            assert len(data) <= 256, (name, len(data))
            page = flash.add(data) >> 8
            slot_of[name] = page << 8
            unit_of[name] = len(entries) + 1
            stored = data
        else:
            stored = zx.smaller(data)
            if stored is not None:
                comp = True
            else:
                stored = data       # a unit that would not shrink stays raw
            page = flash.add(stored) >> 8
        if len(name) > NAME_LEN:
            raise SystemExit(f"{name!r} is longer than {NAME_LEN} characters")
        flags = number | (F_WRITE if wr else 0) | (F_COMP if comp else 0)
        table += name.encode("ascii").ljust(NAME_LEN, b"\x00")
        table += bytes([page & 0xFF, page >> 8,
                        len(stored) & 0xFF, len(stored) >> 8, flags])
        entries.append((name, number, len(data), wr, comp, len(stored)))

    count = len(entries)
    capacity = (sym["tc_init"] - sym["u2_table"]) // ENTRY
    if count > capacity:
        raise SystemExit(f"{count} files but the table holds {capacity}")

    # ---- fill the driver's tables ---------------------------------------
    off = sym["u2_recpage"] - DRIVER_ADDR
    assert driver[off:off + 2] == b"\xff\xff", "recpage placeholder moved"
    driver[off] = rec_page & 0xFF
    driver[off + 1] = rec_page >> 8
    driver[sym["u2_count"] - DRIVER_ADDR] = count
    off = sym["lg_base"] - LOG_ADDR
    assert logseg[off:off + 2] == b"\xff\xff", "lg_base placeholder moved"
    assert save_base & 0xFF == 0
    logseg[off] = (save_base >> 8) & 0xFF
    logseg[off + 1] = save_base >> 16
    off = sym["u2_table"] - DRIVER_ADDR
    driver[off:off + len(table)] = table

    segments = [
        (flash.add(bytes(subs)), len(subs), SUBS_ADDR),
        (flash.add(bytes(files[(1, "INTRO")])), len(files[(1, "INTRO")]), INTRO_ADDR),
        (flash.add(bytes(driver)), len(driver), DRIVER_ADDR),
        (flash.add(bytes(logseg)), len(logseg), LOG_ADDR),
        (flash.add(init), len(init), INIT_ADDR),
    ]

    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, dest in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, dest >> 8, 0])
    assert len(desc) <= 64, len(desc)

    save_end = save_base + 2 * u2log.HALF
    regions.check("u2", flash.cursor, save_end)
    # the record's seed, and the log the page resolves units through
    page = dict(U2_REC=rec_page << 8, U2_LOG=save_base)
    # export/import (xfer.py): what the game writes (the U2 research: its
    # save and INTRO's "destroy existing player" rewrite exactly these, and
    # MON 03 through the time door): the MOB and MON files first, as the
    # game does, each scratched and saved (the header is the game's own
    # SAVE address), then the record with a block write
    names = [f"MOB {n}0" for n in range(5)] + ["MON 00", "MON 03"] + \
            [f"MON {n}0" for n in range(1, 5)]
    # (each slot a unit of the log: its seed, and xfer.LOG | unit)
    xf = [xfer.Disk("Player", disks[2].sector(18, 0),
                    [xfer.File(slot_of[n], xfer.LOG | unit_of[n], n,
                               0x3000 if n.startswith("MOB") else 0x8F00,
                               256, 256) for n in names] +
                    [xfer.Raw(rec_page << 8, xfer.LOG | 0, [(REC_TRACK, REC_SECTOR)])],
                    alt="U II-PLAYER DISK")]                # Sierra's 1984 player disk
    # POWERS (the page's X): a launch poke of pw_on, as U3's and U4's;
    # CLAMP (its V) one of cl_on
    options = dict(caps=patches.caps(OPTION_PATCHES) | patches.POWERS | patches.CLAMP,
                   addr=sym["pt_opts"],
                   pokes={patches.POWERS: [(sym["pw_on"], 0x80)],
                          patches.CLAMP: [(sym["cl_on"], 0x80)]})
    # Journey onward (the launcher): the title sequence starts at INTRO $C093
    # (after the STARS load); <P> at its menu goes to $CEBC, which loads
    # ULTIMA -- and ULTIMA reads the player record itself.  So JMP $CEBC
    # at $C093.  INTRO is a boot segment: in RAM before its init runs.
    intro_b = files[(1, "INTRO")]
    assert bytes(intro_b[0x93:0x96]) == bytes([0x20, 0x7E, 0x40]), "U2 INTRO $C093"
    assert bytes(intro_b[0xEBC:0xEC2]) == bytes([0x20, 0x75, 0x40, 0x20, 0x7B, 0x40]), "U2 $CEBC"
    journey = [(0xC093, 0x4C), (0xC094, 0xBC), (0xC095, 0xCE)]
    return dict(name="ULTIMA II", blobs=list(flash.blobs), desc=bytes(desc), page=page,
                journey=journey,
                options=options, ultima=bytes(files[(1, "ULTIMA")]), xfer=xf,
                intro=bytes(files[(1, "INTRO")]),
                save_end=save_end, used=flash.used, cursor=flash.cursor,
                entries=entries, units=unit_of, driver=len(driver),
                applied=applied, capacity=capacity, rec_page=rec_page)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "ultima2.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(regions.desc_offset("u2"), p["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="ULTIMA 2", flash=image_from(blobs, p["save_end"]))
    img.write(out, trim=False)
    wr = [e for e in p["entries"] if e[3]]
    cz = [e for e in p["entries"] if e[4]]
    raw = sum(e[2] for e in p["entries"] if not e[3])
    got = sum(e[5] for e in p["entries"] if not e[3])
    print(f"{out}")
    print(f"  data {regions.data_base('u2'):#08x}-{p['cursor']:#08x} "
          f"({p['used'] / 1024:.1f} KiB: {len(p['entries'])} files, deduplicated)")
    print(f"  crunched {len(cz)} of {len(p['entries']) - len(wr)} read-only units: "
          f"{raw / 1024:.1f} KiB -> {got / 1024:.1f} KiB ({100 * got / raw:.1f}%)")
    print(f"  driver: {p['driver']} bytes at {DRIVER_ADDR:#06x}, table holds "
          f"{len(p['entries'])} of {p['capacity']} entries")
    print(f"  saves at {regions.save_base('u2'):#08x}: a log of two "
          f"{u2log.HALF // 1024} KiB halves for the player record and {len(wr)} files")
    for _n, _f, addr, why in p["applied"]:
        print(f"  patched {addr:#06x}: {why}")


if __name__ == "__main__":
    main()
