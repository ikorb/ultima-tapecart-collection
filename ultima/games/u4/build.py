#!/usr/bin/env python3
"""Build the Ultima 4 flash layout.

U4 addresses data by linear block number, and not every access comes from
the kernel's chunk/record tables -- the routine at $0A7F in chunk $4F
computes a block number by hand (($60 << 4 | $61) + 1, so blocks 1-256: the
overworld map, four 256-byte map chunks around the party into $E800-$EBFF)
and reads it straight through $A103.  So the block numbering is preserved
exactly: every caller works, table-driven or not.

What changed is how a block reaches flash.  The four disks used to be stored
whole, 2732 pages.  They hold only 1579 distinct ones -- the same code, music
and map pages recur across disks -- so every distinct page is now stored
once, zx02-crunched on its own, and a per-disk BLOCK MAP in flash (683
four-byte entries: the stream's 24-bit address and its length) says where.
The driver reads the map entries for a request and decodes each block
straight out of flash, so nothing about the map has to live in C64 RAM.
686 KiB became 403 with the dedup alone and 224 crunched.

Crunching per page rather than per chunk is what keeps block numbering
intact: any block can be fetched alone, which $0A7F needs.  It is also no
worse -- per chunk, every (chunk, disk) pair has to be stored, most of them
nonsense combinations, and that measured 245 KiB against 210 here.

Saves are the exception.  Chunks $7E/$7F/$80 and record $1A write blocks
271-275 of disk C, so those five blocks are redirected to their own 4 KiB
erase blocks in the save region, seeded from disk C so a fresh cart says
"NO ACTIVE GAME!" exactly like the factory disks do.  Disk 2's map points
those five entries at the slots, so reads find them with no special case.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths

from ultima.disks.d64 import D64
from ultima.flash.layout import Layout, image_from
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.flash import regions
from ultima.games.u4 import remastered               # noqa: E402  (ultima/games/u4/remastered.py)
from ultima.games.u4 import tileset                  # noqa: E402  (ultima/games/u4/tileset.py)
from ultima.launcher import xfer
from ultima.flash import zx
from ultima.pin import Pin

BUILD = paths.BUILD

# The game's disk numbers are NOT in disk-letter order, and are a different
# numbering from the 1541 BAM disk IDs.  The authoritative source is block 0
# byte 0 of each image, which the swap overlay loads as record $00 and
# compares against $5E; every entry here is asserted against it below.
DISKS = {
    1: (paths.disk("u4a"), "ULTIMA DISK"),
    2: (paths.disk("u4c"), "BRITANNIA DISK"),
    3: (paths.disk("u4b"), "TOWN DISK"),
    4: (paths.disk("u4d"), "DUNGEON DISK"),
}

BOOT_FILE = "ULTIMA"
BOOT_ADDR = 0x0801
KERNEL_SRC = 0x0974             # where the kernel image sits inside the boot PRG
KERNEL_ADDR = 0xA100
KERNEL_LEN = 0x600

IRQ_ENTRY = 0xA696              # the kernel's IRQ entry: pushes, then JMP ($A116)
IRQ_KERNAL = 0xA6AC             # its way on to the KERNAL, $A116's default
GLUE_ADDR = 0xA45E              # LOADBLK -- the driver's front half starts here
GLUE_LIMIT = 0xA674             # BANKOUT; the glue must not reach it
LIB_ADDR = 0xD000                # the rest of the driver, in the RAM under I/O
INIT_ADDR = 0x0200

# kernel tables, used here only to locate chunk $50 for the protection patch
CHUNK_CNT = 0xA2A9
CHUNK_PAGE = 0xA309
CHUNK_BLK = 0xA369
CHUNK_FIRST = 0x40

SAVE_DISK = 2                   # Britannia
TILESET = 5                     # the fifth block map: disk A with Remastered's tiles
SAVE_FIRST = 271
SAVE_COUNT = 5
SAVE_SLOT = regions.ERASE_BLOCK
BLOCKS = 683

# ---------------------------------------------------------------------------
# Copy protection.  Chunk $50 at $6C6E reads block 115 (track 6 sector 10)
# and bails out if the read SUCCEEDS -- on an original, track 6 is
# unformatted.  The notes suggest replacing the `BCS` at $6C8F; patching one
# instruction earlier also skips the pointless read itself.
PROT_ADDR = 0x6C8C
PROT_BYTES = bytes([0x20, 0x03, 0xA1, 0xB0, 0x05])      # jsr $A103 / bcs $6C96
PROT_PATCH = bytes([0x4C, 0x96, 0x6C, 0xEA, 0xEA])      # jmp $6C96

# The disk-swap overlay.  Three copies exist on disk A (chunks $4F, $51, and
# a block shared by $50 and $9A).  Rather than hardcode their addresses, find
# them by the body they all share and walk back to the `STA $5E` that starts
# each one -- the two variants differ in their prologue length.
SWAP_BODY = re.compile(
    rb"\xA5\x5E\xC9\x02\xF0.\xC9\x04\xF0.\xA9\x01\x85\x5F\xA5\x5E\xC5\x52\xF0", re.S)
SWAP_ENTRY = bytes([0x85, 0x5E])
SWAP_SITES = 3

# The main menu's "Number of drives" line ($6800 page, disk A).  With every
# disk on the cart it means nothing: jump over its print, move "Return to
# the view" down a row into the gap -- a blank row under "OPTIONS:", one
# below the last entry -- and send the N key back to the
# key poll at $6858 instead of the drives prompt at $6E38.  The page is found
# by its bytes, which must occur exactly once; (address, old, new) below are
# relative to the drives line's `ldx #$0B` at $680F.  The Return line is on
# the page before ($67F5): the chunk loads its blocks to consecutive pages,
# and they are consecutive in the image, which `patch` checks byte for byte.
MENU_AT = 0x680F
MENU_SIG = bytes.fromhex("a2 0b a0 12 20 1e 08") + bytes(c | 0x80 for c in b"Number of drives-")
MENU_PATCHES = [
    (0x67F5, bytes([0xA2, 0x0B, 0xA0, 0x11, 0x20, 0x1E, 0x08, 0xD2]),
     bytes([0xA2, 0x0B, 0xA0, 0x12, 0x20, 0x1E, 0x08, 0xD2]), "Return to the view a row down"),
    (0x680F, bytes([0xA2, 0x0B, 0xA0]), bytes([0x4C, 0x29, 0x68]), "jmp past the drives line"),
    (0x688D, bytes([0xC9, 0xCE, 0xD0, 0x03, 0x4C, 0x38, 0x6E]),
     bytes([0xC9, 0xCE, 0xD0, 0x03, 0x4C, 0x58, 0x68]), "N: back to the poll"),
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


def kernel_image(disk_a):
    boot, ok = disk_a.payload(BOOT_FILE)
    if not ok:
        raise SystemExit("the ULTIMA boot file does not read cleanly")
    image = boot[KERNEL_SRC - BOOT_ADDR:][:KERNEL_LEN]
    assert len(image) == KERNEL_LEN, len(image)
    assert image[:3] == bytes([0x4C, 0x2E, 0xA1]), "kernel does not start with its jump table"
    assert image[GLUE_ADDR - KERNEL_ADDR:GLUE_ADDR - KERNEL_ADDR + 3] == bytes([0xBA, 0x8E, 0x08]), \
        "LOADBLK is not where we expect it"
    return bytearray(image)


def chunk_entry(kernel, index):
    i = index - CHUNK_FIRST
    start = (kernel[CHUNK_BLK - KERNEL_ADDR + i * 2]
             | kernel[CHUNK_BLK - KERNEL_ADDR + i * 2 + 1] << 8)
    return start, kernel[CHUNK_CNT - KERNEL_ADDR + i], kernel[CHUNK_PAGE - KERNEL_ADDR + i] << 8


def patch(image, offset, want, new, what):
    """want: the bytes there (or their Pin); new: bytes, or a function of the
    bytes found."""
    got = bytes(image[offset:offset + len(want)])
    if got != want:
        raise SystemExit(f"{what}: expected {want.hex(' ')} at {offset:#07x}, found {got.hex(' ')}")
    if callable(new):
        new = new(got)
    image[offset:offset + len(new)] = new


# The launcher's options (patches.py, asm/patch.s), all in disk A's code.
# Runtime addresses; the driver patches RAM after each LOADBLK when the
# original bytes are there.  From the U4 research:
#   food: $6273 in the end-of-turn routine $621E (chunk $5B, block 35):
#         LDA $1F / JSR $6500 (food -= party size / 100) / BCS / JSR $641E
#         (starving) -- jumped over.  Combat and gremlins are elsewhere.
#   pass: the key read $0800 returns 0 after a timeout; two callers turn
#         that into "Pass": the main loop ($408F, block 1) and the combat
#         prompt ($70EB, block 49).  Both are sent back to the read instead.
OPTION_PATCHES = [
    patches.Patch(patches.FOOD, 0x6273, bytes.fromhex("a51f200065"),
                  bytes.fromhex("4c7d620065"), "food"),
    patches.Patch(patches.PASS, 0x4094, bytes.fromhex("d0034c0641"),
                  bytes.fromhex("d0034c8f40"), "pass: main loop"),
    patches.Patch(patches.PASS, 0x70EE, bytes.fromhex("d0034c0641"),
                  bytes.fromhex("d0034ceb70"), "pass: combat"),
    # torch: Ignite ($5516 in game main) is LDY #8 / JSR $8450 -- use up
    # item 8, the torches, carry set if there was one -- / BCS to the lit
    # path: SEC / NOP / NOP lights one without using it (the Remastered
    # kit's cheat, docs/reversing-notes/u4-remastered.md).
    patches.Patch(patches.TORCH, 0x5516, bytes.fromhex("a008205084b003"),
                  bytes.fromhex("a00838eaeab003"), "torch: ignite"),
    # Journey onward (the launcher's J): the title draws its logo ($6031-
    # $605B, about 20 s of waits), sets up ($676C), loads and starts the
    # music, then shows the animated view ($67A2, until a key) and the menu,
    # whose J goes to $6954.  The logo's first step jumps to JOURNEY_AT
    # instead, which does the rest up to the view and goes to $6954.  The
    # title is only shown once a session.
    patches.Patch(patches.JOURNEY, 0x6031, bytes.fromhex("20926020"),
                  bytes.fromhex("4ce07120"), "journey: the title"),
]

# The Remastered kit's cheats (docs/reversing-notes/u4-remastered.md, each
# checked there against the original chunk).  ITEMS: Cast, $48A1
# LDY $48EF (the spell's mixture count, then its MP) -> JMP $48DD, the cast:
# no mixture, no MP; Jimmy, $5551, the BEQ over "use up a key" (LDY #$0A /
# JSR $8450) goes to the unlock itself; Peer, $57CD LDY #9 / JSR $8450 (use
# up a gem) -> JMP $57D7.  AVOID and BALLOON hook helpers in $5B's tail
# (u4fix.s: fx_avoid & co, fx_balloon_*), and BALLOON stops the wind's drift
# in SUBS ($0B15, the drift routine, an RTS).
_FX = remastered.helpers()[1]
A0_CODE, _A0 = remastered.helpers("u4a0")
A0_ORG = 0xA006
assert _A0["ac_start"] == A0_ORG
FF_CODE, _FF = remastered.helpers("u4ff")
FF_ORG = 0xFF00
CREDITS_ADDR, CREDITS_END = 0x0839, 0x095B     # the boot PRG's title screen
# the kit's T and B (u4pw.s): one blob from $02A7, two pieces, the KERNAL's
# vectors between them left alone
PW_CODE, _PW = remastered.helpers("u4pw")
PW_A, PW_B = 0x02A7, 0x0334
assert _PW["pw_on"] == PW_A
assert _A0["pw_on"] == _PW["pw_on"], "u4a0.s pw_win tests another pw_on"
assert _A0["fx_horse"] == _FF["fx_horse"], "u4a0.s fx_attack goes on to another fx_horse"
PW_PIECES = [(PW_CODE[:_PW["pw_end_a"] - PW_A], PW_A),
             (PW_CODE[PW_B - PW_A:_PW["pw_end_b"] - PW_A], PW_B)]
assert not any(PW_CODE[_PW["pw_end_a"] - PW_A:PW_B - PW_A]), "u4pw.s wrote into $0314-$0333"
assert _FF["fx_horse"] == FF_ORG
_w = lambda a: bytes([a & 0xFF, a >> 8])
OPTION_PATCHES += [
    patches.Patch(patches.ITEMS, 0x48A1, bytes.fromhex("acef48b940ab"),
                  bytes.fromhex("4cdd48b940ab"), "items: magic"),
    patches.Patch(patches.ITEMS, 0x554E, bytes.fromhex("c93af0034c7841a0"),
                  bytes.fromhex("c93af00d4c7841a0"), "items: keys"),
    patches.Patch(patches.ITEMS, 0x57CD, bytes.fromhex("a009205084b0"),
                  bytes.fromhex("4cd7575084b0"), "items: gems"),
    patches.Patch(patches.AVOID, 0x66FB, bytes.fromhex("205783a658"),     # (to the page's end)
                  b"\x20" + _w(_FX["fx_avoid"]) + bytes.fromhex("a658"), "avoid: attacked"),
    patches.Patch(patches.AVOID, 0x62D7, bytes.fromhex("a9a48540a510"),
                  b"\x20" + _w(_FX["fx_avoid_trolls"]) + bytes.fromhex("eaa510"), "avoid: trolls"),
    patches.Patch(patches.AVOID, 0x6D14, bytes.fromhex("0a0a698c8540"),
                  b"\x0a\x20" + _w(_FX["fx_avoid_dng"]) + bytes.fromhex("8540"), "avoid: dungeon"),
] + [
    # LDA $1E / CMP #$18 / BNE (the transport is the balloon) / JMP $41F7
    patches.Patch(patches.BALLOON, at - 6, bytes.fromhex("a51ec918d0034cf741"),
                  bytes.fromhex("a51ec918d0034c") + _w(_FX["fx_balloon_" + d]), "balloon: " + d)
    for d, at in (("n", 0x424D), ("w", 0x4427), ("e", 0x44F0))
] + [
    # south: two stale near-copies of this block (disk A 256, chunk $9B's at
    # $4100; disk C 275, a save slot's seed) agree up to page offset $69
    patches.Patch(patches.BALLOON, 0x434E, Pin("#29:5726f7e584b449e0"),
                  lambda orig: bytes.fromhex("4c") + _w(_FX["fx_balloon_s"]) + orig[3:], "balloon: s"),
] + [
    patches.Patch(patches.BALLOON, 0x0B15, bytes.fromhex("a51ec918d024"),
                  bytes.fromhex("601ec918d024"), "balloon: no drift"),
]
# Where that goes: chunk $50's residue $71E0-$72FF (source text; nothing
# points into it -- the Remastered analysis, notes/overlays-charcreate.md).
# It is only ever reached by the journey patch, before the J handler loads
# game main over it.  The body is the title's own $676C-$67A1 -- straight
# code, absolute operands only -- then JMP $6954.
JOURNEY_AT = 0x71E0
JOURNEY_FROM = (0x676C, 0x67A2)
JOURNEY_TO = 0x6954
# Meanwhile the display is off -- the title's map and the logo's pictures,
# half drawn, would show -- and back on at the end, with the title's colours
# ($0400) black: game main never turns it on again (it stayed off), and it
# draws its own screen after its load.
JOURNEY_BLANK = bytes.fromhex("ad 11 d0 29 ef 8d 11 d0")     # $D011: DEN off
JOURNEY_UNBLANK = bytes.fromhex(
    "a9 00 aa 9d 00 04 9d 00 05 9d 00 06 9d 00 07 e8 d0 f1"  # $0400-$07FF = 0
    "ad 11 d0 09 10 8d 11 d0")                                  # DEN on
JOURNEY_BODY = Pin("#54:afb6c55553a3e468")    # $676C-$67A1: $1B, $53 = 0; $51, $52 = 1; $4D = $FF;
                                                  # JSR $6B7A; $6062 = 0; the view's tables; load the
                                                  # music ($55), init it and start it

# the block each is in, on disk 1 (its page offset is the address's low byte)
OPTION_BLOCKS = {"food": 35, "pass: main loop": 1, "pass: combat": 49,
                 "journey: the title": 221, "torch: ignite": 22,
                 "items: magic": 9, "items: keys": 22, "items: gems": 24,
                 "avoid: attacked": 39, "avoid: trolls": 35, "avoid: dungeon": 46,
                 "balloon: n": 3, "balloon: s": 4, "balloon: w": 5, "balloon: e": 5,
                 "balloon: no drift": 84}


def resolve_options(disk_a):
    """The options' pinned originals, from disk A's bytes."""
    for p in OPTION_PATCHES:
        p.resolve(disk_a[OPTION_BLOCKS[p.what] * 256 + (p.addr & 0xFF):])


def check_options(images):
    """Every block of every disk can be loaded to any page, so a patch's
    signature must not turn up at its page offset in any block but the one
    it is for (or a byte-identical copy of it: disk A's block 72 is block
    35's twin)."""
    units = [(f"{n}:{b}", 0, bytes(img[b * 256:(b + 1) * 256]))
             for n, img in images.items() for b in range(len(img) // 256)]
    for p in OPTION_PATCHES:
        page = bytes(images[1][OPTION_BLOCKS[p.what] * 256:][:256])
        mine = {u for u, _a, d in units if d == page}
        at = p.addr & 0xFF
        patches.check([patches.Patch(p.option, at, p.orig, p.new, p.what)],
                      [(u, 0, d) for u, _a, d in units], {p.what: mine})


def build_driver():
    """Assemble the driver and split it into its two segments.

    acme emits one blob spanning $A45E to the end of the part at $D000, the
    hole between them zero-filled.  Asserting the hole is empty is what
    proves the glue never grew past $A674 into BANKOUT.
    """
    binpath = os.path.join(BUILD, "u4drv.bin")
    sympath = os.path.join(BUILD, "u4drv.sym")
    with open(os.path.join(BUILD, "u4_patches.s"), "w") as fh:
        fh.write(patches.asm("PT_TAB", OPTION_PATCHES))
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
       f"-DJOURNAL={regions.journal('u4')[0]}",
       "-o", binpath, "-l", sympath, os.path.join(HERE, "u4drv.s"))
    with open(binpath, "rb") as fh:
        blob = bytearray(fh.read())
    sym = symbols(sympath)

    glue = blob[:sym["u4_glue_end"] - GLUE_ADDR]
    hole = blob[len(glue):LIB_ADDR - GLUE_ADDR]
    lib = blob[LIB_ADDR - GLUE_ADDR:]
    if any(hole):
        raise SystemExit("driver glue overflowed past $A674 into BANKOUT/BANKIN")
    assert sym["u4_transfer"] == GLUE_ADDR
    return glue, lib, sym


def parts():
    os.makedirs(BUILD, exist_ok=True)

    images = {}
    for number, (name, label) in DISKS.items():
        d = D64(name)
        ident = d.sector(1, 0)[0]
        if ident != number:
            raise SystemExit(f"{name}: block 0 byte 0 is {ident}, not the "
                             f"{label} disk number {number}")
        images[number] = bytearray(d.data)

    disk_a = D64(DISKS[1][0])
    kernel = kernel_image(disk_a)
    resolve_options(images[1])

    glue, lib, sym = build_driver()

    initbin = os.path.join(BUILD, "init_u4.bin")
    # The credits the boot PRG shows while it loads ($0839-$095A, the
    # painter and its text, ORIGIN SYSTEMS ... COPYRIGHT (C) 1985), for the
    # init stub on a launch that is not Journey onward; its end, JMP $095B
    # into the loads, is an RTS.  Chunk $4F loads over it afterwards, as it
    # did over the original.
    boot, _ok = disk_a.payload(BOOT_FILE)
    credits = bytearray(boot[CREDITS_ADDR - BOOT_ADDR:CREDITS_END - BOOT_ADDR])
    at = 0x0840 - CREDITS_ADDR
    assert credits[:2] == b"\xa2\x00" and credits[at:at + 3] == b"\x4c\x5b\x09", "the credits moved"
    credits[at] = 0x60
    sh("acme", "-f", "plain", f"-DU4_INIT={sym['u4_init']}", f"-DCREDITS={CREDITS_ADDR}",
       f"-DPT_OPTS={sym['pt_opts']}", "-o", initbin,
       os.path.join(paths.ASM, "init_u4.s"))
    with open(initbin, "rb") as fh:
        init = fh.read()
    if len(init) > 0x86:
        raise SystemExit(f"init stub is {len(init)} bytes and would overwrite $0286")

    # ---- patch disk A ---------------------------------------------------
    start, count, dest = chunk_entry(kernel, 0x50)
    assert dest == 0x6000 and count == 19, (start, count, hex(dest))
    off = (start + (PROT_ADDR - dest) // 256) * 256 + (PROT_ADDR & 0xFF)
    patch(images[1], off, PROT_BYTES, PROT_PATCH, "track-6 protection check")

    setdisk = sym["u4_setdisk"]
    jmp_setdisk = bytes([0x4C, setdisk & 0xFF, setdisk >> 8])
    sites = []
    for m in SWAP_BODY.finditer(bytes(images[1])):
        back = bytes(images[1][m.start() - 12:m.start()])
        j = back.rfind(SWAP_ENTRY)
        if j < 0:
            raise SystemExit(f"swap overlay at {m.start():#07x} has no STA $5E prologue")
        entry = m.start() - (12 - j)
        patch(images[1], entry, SWAP_ENTRY, jmp_setdisk, "disk-swap overlay entry")
        sites.append(entry)
    if len(sites) != SWAP_SITES:
        raise SystemExit(f"found {len(sites)} disk-swap overlays on disk A, expected {SWAP_SITES}")
    for number in (2, 3, 4):
        if SWAP_BODY.search(bytes(images[number])):
            raise SystemExit(f"disk {number} unexpectedly carries the swap overlay too")

    hits = [m.start() for m in re.finditer(re.escape(MENU_SIG), bytes(images[1]))]
    if len(hits) != 1:
        raise SystemExit(f"the menu's drives line: {len(hits)} matches on disk A, expected 1")
    for addr, want, new, why in MENU_PATCHES:
        patch(images[1], hits[0] + addr - MENU_AT, want, new, f"main menu: {why}")
    for number in (2, 3, 4):
        if MENU_SIG in bytes(images[number]):
            raise SystemExit(f"disk {number} unexpectedly carries the main menu too")

    # ---- Journey onward's short way past the title (JOURNEY_AT) ------------
    start, count, dest = chunk_entry(kernel, 0x50)
    at = lambda a: (start + (a - dest) // 256) * 256 + (a & 0xFF)
    lo, hi = JOURNEY_FROM
    body = bytes(images[1][at(lo):at(lo) + hi - lo])
    assert body == JOURNEY_BODY, "the title's $676C-$67A1 is not the code it was"
    stub = JOURNEY_BLANK + body + JOURNEY_UNBLANK + bytes([0x4C, JOURNEY_TO & 0xFF, JOURNEY_TO >> 8])
    o = at(JOURNEY_AT)
    assert JOURNEY_AT + len(stub) <= dest + count * 256
    patch(images[1], o, bytes(images[1][o:o + len(stub)]), stub, "journey onward: past the title")
    journey_at = o

    # ---- Ultima IV Remastered's fixes (remastered.py) ----------------------
    fixes, talk_skipped = remastered.apply(images, lambda c: chunk_entry(kernel, c), patch)

    check_options(images)

    # ---- the Remastered tile set: a second disk A (tileset.py) ------------
    # Laid out below as a fifth block map, TILESET; the launcher's option
    # points the driver's disk-A map at it.  Pages both share are stored once.
    images[TILESET], tables = tileset.variant(images[1], disk_a.data,
                                              lambda c: chunk_entry(kernel, c), patch)
    check_options({1: images[TILESET], 2: images[2], 3: images[3], 4: images[4]})

    # ---- lay the flash out ----------------------------------------------
    # Every distinct page once, zx02-crunched, the streams packed end to end
    # in one blob (they need no alignment: the map holds byte addresses).
    # A map entry is the stream's 24-bit flash address and its length; a
    # length of 0 means a raw page, which is what the save slots are.
    flash = Layout(regions.data_base("u4"))
    save_base = regions.save_base("u4")
    streams = {}                # page content -> offset inside the blob
    blob = bytearray()
    blockunits = {}             # number -> [(content, None) or (None, save page)]
    for number in sorted(images):         # (TILESET: disk A, other tiles)
        units = []
        for block in range(BLOCKS):
            if number == SAVE_DISK and SAVE_FIRST <= block < SAVE_FIRST + SAVE_COUNT:
                units.append(("save", save_base + (block - SAVE_FIRST) * SAVE_SLOT))
                continue
            page = bytes(images[number][block * 256:(block + 1) * 256])
            if page not in streams:
                zx02 = zx.crunch(page)
                if len(zx02) > 255:
                    # does not shrink (a Remastered picture's): stored raw,
                    # length 0, as the save slots are read
                    streams[page] = (len(blob), 0)
                    blob += page
                else:
                    streams[page] = (len(blob), len(zx02))
                    blob += zx02
            units.append(("page", page))
        blockunits[number] = units
    blob_base = flash.add(bytes(blob))

    blockmap = {}
    for number, units in blockunits.items():
        entries = []
        for kind, what in units:
            if kind == "save":
                entries.append((what, 0))
            else:
                off, length = streams[what]
                entries.append((blob_base + off, length))
        blockmap[number] = entries
    pages = len(streams)

    map_addr = {}
    for number in sorted(blockmap):
        table = b"".join(bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16, n])
                         for a, n in blockmap[number])
        map_addr[number] = flash.place_at(flash.reserve(len(table)), table)

    seeded = []
    for i in range(SAVE_COUNT):
        block = SAVE_FIRST + i
        data = images[SAVE_DISK][block * 256:(block + 1) * 256]
        flash.place_at(save_base + i * SAVE_SLOT, bytes(data))
        seeded.append(block)

    # ---- fill the driver's flash map ------------------------------------
    for i, number in enumerate(n for n in sorted(map_addr) if n != TILESET):
        for name, shift in (("u4_map_lo", 0), ("u4_map_mid", 8), ("u4_map_hi", 16)):
            o = sym[name] - GLUE_ADDR + i
            assert glue[o] == 0xFF, f"{name} placeholder moved"
            glue[o] = (map_addr[number] >> shift) & 0xFF
    off = sym["u4_savepage"] - GLUE_ADDR
    assert glue[off:off + 2] == b"\xff\xff", "savepage placeholder moved"
    glue[off] = (save_base >> 8) & 0xFF
    glue[off + 1] = (save_base >> 16) & 0xFF

    kernel[GLUE_ADDR - KERNEL_ADDR:GLUE_ADDR - KERNEL_ADDR + len(glue)] = glue

    # the music through a load (u4drv.s u4_irq): the kernel's IRQ entry
    # ($A696, which BANKOUT puts in RAM's $FFFE) goes to the driver's, which
    # keeps the interrupted $01; and its way to the KERNAL ($A6AC, the
    # default in $A116, where the music's handler chains) keeps $01's
    # cassette bits.  The old exit ($A6B3) was reached only through the
    # frame $A696 pushed; the new $A6AC runs over it.
    for at, old, new in (
            (IRQ_ENTRY, bytes.fromhex("48 8a 48"), bytes([0x4C, sym["u4_irq"] & 0xFF, sym["u4_irq"] >> 8])),
            (IRQ_KERNAL, bytes.fromhex("a9 36 85 01 6c fe ff a9 35 85 01"),
             bytes.fromhex("a5 01 29 38 09 06 85 01 6c fe ff"))):
        o = at - KERNEL_ADDR
        assert kernel[o:o + len(old)] == old, f"the kernel's IRQ stub at ${at:04X} is not as expected"
        kernel[o:o + len(new)] = new

    # $A006-$A9FF in one: Remastered's active character and attack fixes
    # (u4a0.s, resident), the kernel, the tile set's colour tables 1-3 (for
    # both: only its renderer reads them) -- the descriptor has room for 8
    assert A0_ORG + len(A0_CODE) <= KERNEL_ADDR and KERNEL_ADDR + len(kernel) == tileset.TABLES
    high = bytes(A0_CODE).ljust(KERNEL_ADDR - A0_ORG, b"\0") + bytes(kernel) + bytes(tables)
    segments = [
        (flash.add(high), len(high), A0_ORG),
        (flash.add(bytes(lib)), len(lib), LIB_ADDR),
        (flash.add(init), len(init), INIT_ADDR),
        # and its save in a dungeon (u4ff.s), under the KERNAL
        (flash.add(FF_CODE), len(FF_CODE), FF_ORG),
        # the boot PRG's credits, for the init stub
        (flash.add(bytes(credits)), len(credits), CREDITS_ADDR),
        # the kit's T and B (u4pw.s), in pages 2 and 3
        (flash.add(bytes(PW_PIECES[0][0])), len(PW_PIECES[0][0]), PW_PIECES[0][1]),
        (flash.add(bytes(PW_PIECES[1][0])), len(PW_PIECES[1][0]), PW_PIECES[1][1]),
    ]

    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, dest in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, dest >> 8, 0])
    assert len(desc) <= 64, len(desc)

    save_end = save_base + SAVE_COUNT * SAVE_SLOT
    regions.check("u4", flash.cursor, save_end)
    page = dict(U4_ROSTER=save_base + (273 - SAVE_FIRST) * SAVE_SLOT,   # the party
                U4_ZP=save_base + (275 - SAVE_FIRST) * SAVE_SLOT)       # $1F: its size
    # export/import (xfer.py): the five save blocks on the Britannia disk,
    # which the game recognises by T1/S0 byte 0 (its disk number, 2)
    brit = D64(DISKS[SAVE_DISK][0])

    xf = [xfer.Disk("Britannia", brit.sector(18, 0),
                    [xfer.Raw(save_base + i * SAVE_SLOT, xfer.NONE,
                              [D64.from_linear(SAVE_FIRST + i)]) for i in range(SAVE_COUNT)],
                    check=(1, 0, 0, SAVE_DISK), alt="BRITANNIA")]   # the 1986 disk's name
    # the tile set: its option pokes disk 1's entry of the driver's map table
    tile_pokes = [(sym[name], (map_addr[TILESET] >> shift) & 0xFF)
                  for name, shift in (("u4_map_lo", 0), ("u4_map_mid", 8), ("u4_map_hi", 16))]
    # ... and Remastered's creation: chunk $9F is a block longer (tileset.py)
    cnt = CHUNK_CNT + tileset.LONGER - CHUNK_FIRST
    assert kernel[cnt - KERNEL_ADDR] == chunk_entry(kernel, tileset.LONGER)[1] == 5
    tile_pokes.append((cnt, 6))
    options = dict(caps=patches.caps(OPTION_PATCHES) | patches.TILES | patches.POWERS,
                   addr=sym["pt_opts"],
                   pokes={patches.TILES: tile_pokes, patches.POWERS: [(_PW["pw_on"], 1)]})
    journey = dict(pokes=[], bits=patches.JOURNEY)
    return dict(name="ULTIMA IV", blobs=list(flash.blobs), desc=bytes(desc), page=page,
                remastered=fixes, talk_skipped=talk_skipped, journey_at=journey_at,
                options=options, xfer=xf, journey=journey,
                save_end=save_end, used=flash.used, cursor=flash.cursor,
                blockmap=blockmap, map_addr=map_addr, pages=pages, seeded=seeded,
                images={n: bytes(i) for n, i in images.items()}, crunched=len(blob),
                glue=len(glue), lib=len(lib), sites=sites, menu_at=hits[0])


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "ultima4.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(regions.desc_offset("u4"), p["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="ULTIMA 4", flash=image_from(blobs, p["save_end"]))
    img.write(out, trim=False)
    print(f"{out}")
    print(f"  data {regions.data_base('u4'):#08x}-{p['cursor']:#08x} "
          f"({p['used'] / 1024:.1f} KiB: {p['pages']} distinct pages for "
          f"{len(DISKS) * BLOCKS} blocks, zx02 to {p['crunched'] / 1024:.1f} KiB, "
          f"plus the block maps)")
    for number, addr in sorted(p["map_addr"].items()):
        label = DISKS[number][1] if number in DISKS else "A, Remastered tiles"
        print(f"    disk {number} ({label:<14}) map at {addr:#08x}")
    print(f"  driver: {p['glue']} bytes of glue at {GLUE_ADDR:#06x} "
          f"({GLUE_LIMIT - GLUE_ADDR - p['glue']} spare), {p['lib']} bytes of tclib "
          f"at {LIB_ADDR:#06x}")
    print(f"  swap overlays patched at file offsets: "
          + ", ".join(f"{s:#07x}" for s in p["sites"]))
    print(f"  saves at {regions.save_base('u4'):#08x}, {SAVE_COUNT} slots of "
          f"{SAVE_SLOT // 1024} KiB, seeded from disk {SAVE_DISK} blocks "
          + ", ".join(str(b) for b in p["seeded"]))


if __name__ == "__main__":
    main()
