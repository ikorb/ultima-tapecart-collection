#!/usr/bin/env python3
"""Build Akalabeth's flash layout.

Akalabeth: World of Doom on the C64 is Andrea Schincaglia's conversion of the
Apple II original (2016), a compiled BASIC program; the build takes it from
Genesis Project's release of it (the disk "accept no limits", main file
`AKALABETH+4  /GP`, with Wertstahl's trainer), the one the manifest knows.
That file is packed: run from its `SYS 2061`, a decruncher unpacks a
cracktro and, at $4000, the game as it is in RAM, which the cracktro moves
to $0801 and starts at $081C.  The build runs the decruncher in py65
(unpack(), below) and takes the program from $4000: $0801-$7A2E, the
runtime, the p-code and the compiled variables' names.

The game loads four files of its own: LIB, the graphics routines, to $C000
as it starts, and three pictures, each a bitmap, screen and colour RAM,
shown between the pages of its instructions.  LIB is a segment here.  The
pictures are not on the cart (30 KiB, 17 KiB packed: there is no room), and
the instructions skip them.  So the program never loads, and needs no
driver: what it would have done goes as patches of its p-code, each a run
of `:`, the runtime's empty statement (opcode $3A, which only steps on):

  $20A2  GOSUB $76E6: Wertstahl's trainer, four questions as the game
         starts.  Its flags are the page's options instead (init_u0.s).
  $691D  PRINT "LOADING...": FL$="LIB": GOSUB $6261 (the LOAD).
  $6AE0  the pictures, from after the POKE 53265,11 that blanks the screen
         for them to before the GOSUB $62A8 that brings the text screen
         back, which both stay.  Each statement here ends where the
         runtime's handler clears its pending operation ($3B, at $0EAC);
         a run of `:` that starts inside one leaves an operation pending,
         and the next RETURN fails.

docs/developer/u0.md has the runtime's format, as far as the patches need it.
"""
import os
import subprocess
import sys

from ultima import paths
from ultima.disks.d64 import D64
from ultima.flash import regions
from ultima.flash import zx
from ultima.flash.layout import Layout, image_from
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.pin import Pin

BUILD = paths.BUILD

MAIN_FILE = "AKALABETH+4  /GP"
LIB_FILE = "LIB"
MAIN = Pin("#20935:ffb6a67eeb155a84")       # the file, load address and all
LIB = Pin("#2217:b90a3756122fdf7c")
PROGRAM = Pin("#29230:b1c4e006ece891de")    # $0801-$7A2E, unpacked

SFX_ENTRY = 0x080D              # the file's SYS 2061
CRACKTRO = 0x3000               # where the decruncher hands over
UNPACKED = 0x4000               # the game's $0801, before the cracktro moves it
PROG_ORG = 0x0801
VARTAB, ARYTAB = 0x784C, 0x7A2F # the variables' names, compiled in; arrays
PROG_END = ARYTAB               # and strings are made as it runs
LIB_ORG = 0xC000
INIT_ORG, FLAGS = 0x0334, 0x03FC
ENTRY = 0x081C                  # SYS 2076: the runtime
POINTERS = 0x1F93               # the runtime's start pointers: VARTAB, ARYTAB

COLON = 0x3A
# (first, last, the bytes there, the byte after, why)
FILLS = [
    (0x20A2, 0x20A4, bytes([0x1A, 0x76, 0xE6]), 0x1A,
     "GOSUB $76E6, the trainer's questions"),
    (0x691D, 0x6932, bytes([0xE7, 0x0A]), 0x1D,
     "PRINT \"LOADING...\": FL$=\"LIB\": GOSUB $6261"),
    (0x6AE0, 0x6BE0, bytes([0xA8, 0x90, 0x40, 0x39, 0x00, 0x00, 0x18, 0x3A]), 0x1A,
     "the instructions' three pictures"),
]
# the end of each run, before the byte after: LIB's GOSUB $6261, the last
# picture's SYS 49209 and `:`
FILL_ENDS = {0x6932: bytes([0x1A, 0x62, 0x61]),
             0x6BE0: bytes([0xA8, 0x90, 0x40, 0x39, 0x00, 0x00, 0x18, 0x3A])}

# The trainer's flags, in init_u0.s's segment: the page pokes 100 into each
# whose option is on.  The game's tests: food at the two places a step uses
# food and in the dungeon (PEEK(1023)), gold where a shop charges (1022), a
# monster's hit (1021), the player's attack (1020).
TRAINER = {
    patches.FOOD: 0x03FF,       # F: food used while walking
    patches.ITEMS: 0x03FE,      # G: gold spent in the shops
    patches.BALLOON: 0x03FD,    # H: monsters can hurt (bit 7, its own key)
    patches.AVOID: 0x03FC,      # A: attacks can miss
}
ON = 100


def sh(*cmd):
    subprocess.run(cmd, check=True)


def unpack(main):
    """The program as the decruncher leaves it: $0801-$7A2E."""
    try:
        from py65.devices.mpu6502 import MPU
        from py65.memory import ObservableMemory
    except ImportError:
        raise SystemExit("Akalabeth needs py65 to unpack its file: "
                         "python3 -m venv .venv && .venv/bin/pip install py65 "
                         "in the repository (the Makefile uses its python)")
    ram = bytearray(0x10000)
    ram[PROG_ORG:PROG_ORG + len(main) - 2] = main[2:]
    ram[0], ram[1] = 0x2F, 0x37
    mem = ObservableMemory(subject=ram)

    def io_write(addr, value):          # I/O visible: the RAM keeps its byte
        if ram[1] & 0x03 and ram[1] & 0x04:
            return ram[addr]
        return None
    mem.subscribe_to_write(range(0xD000, 0xE000), io_write)
    mpu = MPU(memory=mem)
    mpu.pc, mpu.sp = SFX_ENTRY, 0xF6
    for _ in range(5_000_000):          # ~1.9 million
        if mpu.pc == CRACKTRO:
            break
        mpu.step()
    else:
        raise SystemExit(f"Akalabeth: the unpack never reached ${CRACKTRO:04X} "
                         f"(pc ${mpu.pc:04X})")
    return bytes(ram[UNPACKED:UNPACKED + PROG_END - PROG_ORG])


def program(main):
    """The program, unpacked and checked, with its loads patched out."""
    prog = bytearray(unpack(main))
    if prog != PROGRAM:
        raise SystemExit("Akalabeth: the unpacked program is not the one the build knows")
    at = lambda a: a - PROG_ORG
    t = at(POINTERS)
    assert prog[t:t + 4] == bytes([VARTAB & 0xFF, VARTAB >> 8, ARYTAB & 0xFF, ARYTAB >> 8])
    for first, last, head, after, why in FILLS:
        assert prog[at(first):at(first) + len(head)] == head, why
        end = FILL_ENDS.get(last)
        if end:
            assert prog[at(last) + 1 - len(end):at(last) + 1] == end, why
        assert prog[at(last) + 1] == after, why
        prog[at(first):at(last) + 1] = bytes([COLON]) * (last - first + 1)
    return bytes(prog)


def parts():
    disk = D64(paths.disk("u0"))
    main, _ok = disk.file(MAIN_FILE)
    lib, _ok = disk.file(LIB_FILE)
    if main != MAIN or lib != LIB:
        raise SystemExit("Akalabeth: not the disk the build knows")
    assert lib[:2] == bytes([LIB_ORG & 0xFF, LIB_ORG >> 8])
    prog = program(main)

    initbin = os.path.join(BUILD, "init_u0.bin")
    sh("acme", "-f", "plain", "-o", initbin, os.path.join(paths.ASM, "init_u0.s"))
    with open(initbin, "rb") as fh:
        init = fh.read()
    assert len(init) == 0x0400 - INIT_ORG and init[FLAGS - INIT_ORG:] == bytes(4)

    flash = Layout(regions.data_base("u0"))
    segments = []
    for data, dest in ((prog, PROG_ORG), (lib[2:], LIB_ORG)):
        offset, length, flags = zx.place_segment(flash, data)
        segments.append((offset, length, dest, flags))
    segments.append((flash.add(init), len(init), INIT_ORG, 0))

    desc = bytearray([INIT_ORG & 0xFF, INIT_ORG >> 8, len(segments)])
    for offset, length, dest, flags in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, dest >> 8, flags])
    assert len(desc) <= 64, len(desc)
    regions.check("u0", flash.cursor, 0)

    # every option a poke of the trainer's flag; no options byte, no saves
    options = dict(caps=sum(TRAINER), addr=0,
                   pokes={bit: [(addr, ON)] for bit, addr in TRAINER.items()})
    return dict(name="AKALABETH", blobs=list(flash.blobs), desc=bytes(desc), page={},
                journey=None, options=options, xfer=None, program=prog, lib=lib[2:],
                init=init, save_end=0, used=flash.used, cursor=flash.cursor)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "akalabeth.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(regions.desc_offset("u0"), p["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="AKALABETH", flash=image_from(blobs, p["cursor"]))
    img.write(out, trim=False)
    print(f"{out}")
    print(f"  data {regions.data_base('u0'):#08x}-{p['cursor']:#08x} "
          f"({p['used'] / 1024:.1f} KiB: the program, LIB, the init stub)")


if __name__ == "__main__":
    main()
