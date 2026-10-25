#!/usr/bin/env python3
"""Build the Ultima 1 tapecart image.

    python -m ultima.games.u1.build [out.tcrt]

Flash layout:
    $000100  boot descriptor: entry address, segment count, segment list
    data_base  units, page aligned and deduplicated (ultima/flash/regions.py)

The driver image is the original 2 KB that HELLO relocates to $C000, with
u1drv.s overlaid on the dead fastloader and the four entry points.  Only those
regions change; the OU memcpy at $C4FD, the counter at $C4F8 and the save
tables at $C5E3/$C5EF survive untouched.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths

from ultima.disks.d64 import D64
from ultima.flash.layout import Layout, image_from
from ultima.flash import zx
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.flash import regions
from ultima.flash import tcsyms
from ultima.launcher import xfer
from ultima.pin import Pin

DISK = paths.disk("u1")

BUILD = paths.BUILD

DESC_OFFSET = regions.desc_offset("u1")
DATA_BASE = regions.data_base("u1")
# Save region: one 4 KiB erase block per slot, so writing one save never
# disturbs another and the driver never needs a read-modify-write.  Erase
# blocks are 4096 bytes on release hardware (READ_DEVICESIZES reports 16
# pages), so this is the smallest independently erasable unit.
SAVE_BASE = regions.save_base("u1")
ERASE_BLOCK = regions.ERASE_BLOCK
SAVE_MAGIC = bytes([0xA5, 0x5A])

F_COMPRESSED = 0x01
F_SAVESLOT = 0x02

DRIVER_ADDR = 0xC000
DECODER_ADDR = 0xC600            # the dead fastload buffer, $C600-$C6FF (not
                                 # $CB00: that is the current settlement's map)
OPTS_ADDR = 0xC52C               # the options, over the original KERNAL load
                                 # routine and its tables ($C52C-$C5E2)
DRIVER_SRC_OFFSET = 0x400        # HELLO payload offset of the $8400 block
# HELLO copies 8 pages to $C000, but its own file only reaches $89FB -- the
# last 516 bytes of that copy are uninitialised RAM.  The real driver is
# $C000-$C5FB, and $C600-$C6FF (the old fastload buffer) and $C700+ (MA's
# area) need no content, so only the real 1532 bytes are stored.
DRIVER_LENGTH = 0x5FC

INIT_ADDR = 0xC700               # the init stub; it ends with JMP $0C00
EXT_ADDR = 0xCE01                # the launcher's X and the options' table, a
                                 # segment of their own (u1drv.s)
OU_ADDR = 0x8C9E                 # where OU runs (LO caches it at $E000)

# the game's own file index -> (name, load address).  Read out of the driver's
# $C597/$C5C3 tables at build time rather than hardcoded, see check_tables().
INDEX_NAMES = ["TC", "MA", "PL", "FI", "GE", "OU", "DN", "TW", "CA", "SP",
               "TM", "ST", "IN", "MI", "LO", "PR", "DD", "RO", "P0", "P1",
               "P2", "P3"]
ENTRIES = len(INDEX_NAMES)
SAVE_FIRST = 16                  # indices 16-21 are the writable ones


# The launcher's options (patches.py, asm/patch.s), applied by the driver
# after every load (u1_done).  From the U1 research, checked in the units:
#   food: MI's food routine ($863A, MI is resident at $7400 for the whole
#         game): once the fraction borrows it takes a whole unit -- jumped
#         over to its no-borrow exit $866A, which keeps the time counter.
#         Every move's cost goes through it; the gremlins' halving does not.
#   pass: the idle loops, 128 polls of the keyboard and then a turn passes
#         -- LDX #$80 / JSR poll / BNE key / DEX / BNE -- in DN, TW and CA:
#         DEX / BNE becomes NOP / BEQ, so the poll goes round until a key.
#         OU's is u1idle.s (IDLE_HOOK), which reads the option itself.
#   steal: the three who steal.  Iolo the bard (TW $A457) and the jester (CA
#         $9D88), when the party stands in their way, take one of every
#         weapon but the readied one (DEC $81F8,X for X = 15..1) -- an RTS
#         where that starts.  A dungeon's thief ($17 at DN $9DDA) steals one
#         weapon ($9EAF) when its attack lands: its entry in the attacks'
#         jumps ($9E81 JMP $9EAF) goes to the ordinary hit ($9DF6), where
#         it goes when there is nothing to take.  (The gremlins' food and
#         the gelatinous cube's armour are left alone.)
OPTION_PATCHES = [
    # (short signatures; patches.check proves each is unique)
    patches.Patch(patches.FOOD, 0x8657, bytes.fromhex("ad5a820d5b"),
                  bytes.fromhex("4c6a860d5b"), "food"),
    patches.Patch(patches.PASS, 0x912C, bytes.fromhex("d003cad0f8"),
                  bytes.fromhex("d003eaf0f8"), "pass: DN"),
    patches.Patch(patches.PASS, 0x8D4A, bytes.fromhex("d003cad0f8"),
                  bytes.fromhex("d003eaf0f8"), "pass: TW"),
    patches.Patch(patches.PASS, 0x8D53, bytes.fromhex("d003cad0f8"),
                  bytes.fromhex("d003eaf0f8"), "pass: CA"),
    patches.Patch(patches.STEAL, 0xA457, bytes.fromhex("a900854ca20f"),
                  bytes.fromhex("6000854ca20f"), "steal: TW"),
    patches.Patch(patches.STEAL, 0x9D88, bytes.fromhex("a900854ca20f"),
                  bytes.fromhex("6000854ca20f"), "steal: CA"),
    patches.Patch(patches.STEAL, 0x9E81, bytes.fromhex("4caf9e4cfc9e"),
                  bytes.fromhex("4cf69d4cfc9e"), "steal: DN"),
]
OPTION_UNITS = {"food": {"MI"}, "pass: DN": {"DN"},
                "pass: TW": {"TW"}, "pass: CA": {"CA"},
                "steal: TW": {"TW"}, "steal: CA": {"CA"}, "steal: DN": {"DN"}}

# F7 teleports, B brings a transport (u1powers.s, the launcher's X): hooks
# in OU, always in, to code that tests pw_on.  (address where OU runs,
# original, symbol)
POWER_HOOKS = [
    (0x8D31, "20 fd 85", "pw_key"),     # the command loop: JSR $85FD, a key
    (0x9082, "20 f6 83", "pw_board"),   # Board, nothing here: JSR $83F6
]
# OU's key wait, timed (u1idle.s): LDX #$80 / JSR $167C -> JMP idle
IDLE_HOOK = (0x8DD0, "a2 80 20", "idle")


# The outdoor view drawn only where it changed (u1view.s, which says how;
# measured with tools/vice/u1_step_bench.py, docs/developer/u1.md).  ST's
# renderer is replaced in place up to its animation (which it calls by the
# clock), its helpers follow ST's end; ST's jump table entries that draw in a
# bitmap, its character routine and OU's start go through hooks in a boot
# segment of their own, in the tape buffer; the animation's timing is another,
# in the KERNAL's unused $02A7-$02FF.  U1_NO_FAST
# leaves it all out (to compare in VICE).
ST_ADDR = 0x0C00
VIEW_ORG = 0x02A7                # u1view.s's lowest section: the animation,
ANIM_LIMIT = 0x0300              # $02A7-$02FF
VIEW_ADDR = 0x0334               # the hooks: the tape buffer and the bytes
VIEW_LIMIT = 0x0400              # around it, $0334-$03FF
ST_END = 0x1F87                  # ST's own end; the helpers up to $1FFD
ST_LIMIT = 0x1FFE                # (init_u1.s's CHROUT stub at $1FFE)
VIEW_RENDERER = (0x1C8A, 0x1DB5, Pin("#299:35369305d0f79f10"))
VIEW_JUMPS = [                   # ST's jump table: (entry, original, hook)
    (0x163A, "4c 8f 17", "h_setup"),
    (0x1649, "4c 10 19", "h_scroll"),
    (0x164C, "4c 9e 19", "h_row"),
    (0x164F, "4c a6 19", "h_eol"),
    (0x1652, "4c 48 1a", "h_win"),
    (0x1661, "4c ad 16", "h_clear"),
    (0x1664, "4c 00 17", "h_flip"),
    (0x168E, "4c ed 17", "h_point"),
    (0x1691, "4c 66 18", "h_line"),
    (0x1694, "4c 6a 18", "h_line2"),
]
VIEW_CHAR = (0x1A78, "48 8e 05 1b")      # PHA / STX $1B05 -> JMP h_char
VIEW_OU = (0x8C9E, "a9 30 85 01")        # LDA #$30 / STA $01 -> JSR h_ou / NOP


def sh(*args):
    subprocess.run(args, check=True)


def symbol(symfile, name):
    pat = re.compile(r"^\s*" + re.escape(name) + r"\s*=\s*\$([0-9a-fA-F]+)")
    for line in Path(symfile).read_text().splitlines():
        m = pat.match(line)
        if m:
            return int(m.group(1), 16)
    raise SystemExit(f"symbol {name!r} not found in {symfile}")


def _seg(placed, dest):
    """(offset, length, flags) from zx.place_segment -> descriptor order."""
    offset, length, flags = placed
    return (offset, length, flags, dest)


def read_tables(driver):
    """Pull the load table out of the original driver image; it is the single
    source of truth for what each index loads and where it goes."""
    names, loads = [], []
    for i in range(ENTRIES):
        o = 0xC597 - DRIVER_ADDR + 2 * i
        names.append(driver[o:o + 2].decode("latin1"))
        o = 0xC5C3 - DRIVER_ADDR + 2 * i
        loads.append(driver[o] | driver[o + 1] << 8)
    return names, loads


def hook_ou(data, drvsym):
    """OU with POWER_HOOKS in: each JSR pointed at its routine."""
    data = bytearray(data)
    for at, orig, name in POWER_HOOKS:
        off = at - OU_ADDR
        if bytes(data[off:off + 3]) != bytes.fromhex(orig):
            raise SystemExit(f"OU ${at:04x} is not {orig}: {bytes(data[off:off + 3]).hex(' ')}")
        target = symbol(drvsym, name)
        data[off + 1:off + 3] = bytes([target & 0xFF, target >> 8])
    at, orig, name = IDLE_HOOK
    off = at - OU_ADDR
    if bytes(data[off:off + 3]) != bytes.fromhex(orig):
        raise SystemExit(f"OU ${at:04x} is not {orig}: {bytes(data[off:off + 3]).hex(' ')}")
    target = symbol(drvsym, name)
    data[off:off + 3] = bytes([0x4C, target & 0xFF, target >> 8])
    return bytes(data)


def assemble_view():
    """u1view.s -> (bytes from VIEW_ORG on, symbols)."""
    path = os.path.join(BUILD, "u1view.bin")
    sh("acme", "-f", "plain", "-o", path, "-l", path + ".sym", os.path.join(HERE, "u1view.s"))
    sym = {m.group(1): int(m.group(2), 16) for m in
           re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path + ".sym").read_text())}
    if sym["anim_end"] > ANIM_LIMIT:
        raise SystemExit(f"u1view.s: the animation runs past $02FF to ${sym['anim_end']:04x}")
    if sym["hooks_end"] > VIEW_LIMIT:
        raise SystemExit(f"u1view.s: the hooks run past $03FF to ${sym['hooks_end']:04x}")
    first, end, _pin = VIEW_RENDERER
    if sym["view_end"] > end:
        raise SystemExit(f"u1view.s: the view runs past ${end:04x} to ${sym['view_end']:04x}")
    if sym["tail_end"] > ST_LIMIT:
        raise SystemExit(f"u1view.s: the helpers run past $1FFD to ${sym['tail_end']:04x}")
    return Path(path).read_bytes(), sym


def view_st(data, view):
    """ST with u1view.s's renderer and its hooks in."""
    blob, sym = view
    at = lambda a: blob[a - VIEW_ORG]
    data = bytearray(data)
    if len(data) != ST_END - ST_ADDR:
        raise SystemExit(f"ST is {len(data)} bytes, not {ST_END - ST_ADDR}")
    data += blob[ST_END - VIEW_ORG:sym["tail_end"] - VIEW_ORG]
    first, end, pin = VIEW_RENDERER
    if data[first - ST_ADDR:end - ST_ADDR] != pin:
        raise SystemExit(f"ST ${first:04x}-${end - 1:04x} is not the original")
    code = blob[first - VIEW_ORG:sym["view_end"] - VIEW_ORG]
    assert first + len(code) <= end
    data[first - ST_ADDR:first - ST_ADDR + len(code)] = code
    hooks = [(a, orig, bytes([0x4C, sym[n] & 0xFF, sym[n] >> 8])) for a, orig, n in VIEW_JUMPS]
    hooks.append((VIEW_CHAR[0], VIEW_CHAR[1], bytes(at(a) for a in range(VIEW_CHAR[0], sym["char_end"]))))
    for a, orig, new in hooks:
        o = a - ST_ADDR
        if data[o:o + len(bytes.fromhex(orig))] != bytes.fromhex(orig):
            raise SystemExit(f"ST ${a:04x} is not {orig}: {data[o:o + 4].hex(' ')}")
        data[o:o + len(new)] = new
    return bytes(data)


def view_ou(data, view):
    """OU's start through h_ou, which drops the view's record."""
    _blob, sym = view
    at, orig = VIEW_OU
    data = bytearray(data)
    o = at - OU_ADDR
    if data[o:o + 4] != bytes.fromhex(orig):
        raise SystemExit(f"OU ${at:04x} is not {orig}: {data[o:o + 4].hex(' ')}")
    data[o:o + 4] = bytes([0x20, sym["h_ou"] & 0xFF, sym["h_ou"] >> 8, 0xEA])
    return bytes(data)


def parts():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "ultima1.tcrt")
    os.makedirs(BUILD, exist_ok=True)

    disk = D64(DISK)

    # ---- driver image: original, then our overlay -----------------------
    hello, ok = disk.payload("HELLO")
    assert ok, "HELLO crosses an unreadable sector"
    driver = bytearray(hello[DRIVER_SRC_OFFSET:])
    assert len(driver) == DRIVER_LENGTH, (
        f"driver image is {len(driver)} bytes, expected {DRIVER_LENGTH} "
        f"($C000-$C5FB)")

    names, loads = read_tables(driver)
    if names != INDEX_NAMES:
        raise SystemExit(f"driver name table changed: {names}")

    view = None if os.environ.get("U1_NO_FAST") else assemble_view()
    if not view:
        print("  u1: VIEW PATCH LEFT OUT (U1_NO_FAST)")

    drvbin = os.path.join(BUILD, "u1drv.bin")
    drvsym = os.path.join(BUILD, "u1drv.sym")
    with open(os.path.join(BUILD, "u1_patches.s"), "w") as fh:
        fh.write(patches.asm("PT_TAB", OPTION_PATCHES))
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD, "-I", HERE,
       f"-DJOURNAL={regions.journal('u1')[0]}", f"-DPT_PASS={patches.PASS}",
       "-o", drvbin, "-l", drvsym, os.path.join(HERE, "u1drv.s"))
    tcsyms.tcinit_include(drvsym, os.path.join(BUILD, "u1_tcinit.s"))
    with open(drvbin, "rb") as fh:
        blob = fh.read()
    # acme emits one blob spanning the overlay, the decruncher and the
    # segment at $CE01 with the holes zero filled.  The holes cover the save
    # tables at $C5E3, MA (graphics) at $C700-$CAFF and the settlement at
    # $CB00-$CDFF, so they must not be written back -- and asserting they are
    # empty is what proves each piece stayed inside its room.
    sym = lambda name: symbol(drvsym, name) - DRIVER_ADDR
    drv_end, opt_end, zx_end, ext_end = (sym(n) for n in ("u1_drv_end", "u1_opt_end",
                                                         "u1_zx_end", "u1_ext_end"))
    overlay = blob[:drv_end]
    options = blob[OPTS_ADDR - DRIVER_ADDR:opt_end]
    decruncher = blob[DECODER_ADDR - DRIVER_ADDR:zx_end]
    ext = blob[EXT_ADDR - DRIVER_ADDR:ext_end]
    assert len(blob) == ext_end, "something after the segment at $CE01"
    if any(blob[drv_end:OPTS_ADDR - DRIVER_ADDR]):
        raise SystemExit("the u1 overlay overflowed past $C4D7 into $C4F8 and the OU copy")
    if any(blob[opt_end:DECODER_ADDR - DRIVER_ADDR]):
        raise SystemExit("the u1 options overflowed into the save tables at $C5E3")
    if any(blob[zx_end:EXT_ADDR - DRIVER_ADDR]):
        raise SystemExit("something of the u1 driver between $C6ED and $CE01")
    # Slice at the symbol, not at DRIVER_LENGTH.  The overlay only replaces
    # $C000-$C490; everything above it in the image is original and load
    # bearing -- the OU memcpy at $C4FD and the save start/end tables at
    # $C5E3/$C5EF, which are read back a few lines below.  Copying the whole
    # 1532 bytes zero-fills those tables and every save silently writes zero
    # bytes to offset zero.

    driver[0:len(overlay)] = overlay
    driver[OPTS_ADDR - DRIVER_ADDR:opt_end] = options
    table_at = symbol(drvsym, "u1_table") - DRIVER_ADDR

    # save ranges, straight out of the driver's own $C5E3/$C5EF tables
    save_len, save_start = [], []
    for j in range(ENTRIES - SAVE_FIRST):
        o = 0xC5E3 - DRIVER_ADDR + 2 * j
        start = driver[o] | driver[o + 1] << 8
        o = 0xC5EF - DRIVER_ADDR + 2 * j
        end = driver[o] | driver[o + 1] << 8
        save_start.append(start)
        save_len.append(end - start)

    # ---- place every unit -----------------------------------------------
    flash = Layout(DATA_BASE)
    units = []
    loaded = []                 # (name, load address, bytes): the options' check
    for i, name in enumerate(INDEX_NAMES):
        if i >= SAVE_FIRST:
            # writable: gets its own erase block rather than a data unit
            j = i - SAVE_FIRST
            block = SAVE_BASE + j * ERASE_BLOCK
            units.append((block, save_len[j], save_start[j], F_SAVESLOT))
            continue
        try:
            data, readable = disk.payload(name)
        except KeyError:
            data, readable = b"", False
        if name == "PR" or not readable or not data:
            # PL is not on the disk; PR sits on the deliberately unformatted
            # track 6.  A zero length makes the driver return C set, exactly
            # as the original does -- for PR that keeps the table the game
            # already has at $12C0, which is the point of the protection.
            # PR by name: a copy whose track 6 was formatted reads as a file.
            units.append((0, 0, loads[i], 0))
            continue
        if name == "OU":
            data = hook_ou(data, drvsym)
            if view:
                data = view_ou(data, view)
        if name == "ST" and view:
            data = view_st(data, view)
        loaded.append((name, loads[i], bytes(data)))
        stored, flags = zx.smaller(data), F_COMPRESSED
        if stored is None:
            stored, flags = data, 0     # a unit that would not shrink stays raw
        units.append((flash.add(stored), len(stored), loads[i], flags))

    patches.check(OPTION_PATCHES, loaded, OPTION_UNITS)

    # Seed the slots the shipped disk already has content for, so a fresh cart
    # behaves like a fresh disk: DD (drive type) and RO (an empty 64-byte
    # roster).  P0-P3 are absent on this disk -- it was played and blanked --
    # so they stay erased and read back as "no save".
    for i, name in enumerate(INDEX_NAMES):
        if i < SAVE_FIRST:
            continue
        j = i - SAVE_FIRST
        try:
            data, readable = disk.payload(name)
        except KeyError:
            continue
        if not readable or not data:
            continue
        data = data[:save_len[j]]
        block = SAVE_BASE + j * ERASE_BLOCK
        flash.place_at(block, SAVE_MAGIC + bytes([len(data) & 0xFF, len(data) >> 8]))
        flash.place_at(block + 0x100, data)

    # ---- patch the unit table into the driver ---------------------------
    for i, (offset, length, dest, flags) in enumerate(units):
        assert offset % 256 == 0, f"unit {i} is not page aligned"
        if flags & F_SAVESLOT:
            assert offset % ERASE_BLOCK == 0, f"save slot {i} is not erase-block aligned"
        e = table_at + i * 8
        driver[e + 0] = (offset >> 8) & 0xFF
        driver[e + 1] = (offset >> 16) & 0xFF
        driver[e + 2] = length & 0xFF
        driver[e + 3] = (length >> 8) & 0xFF
        driver[e + 4] = dest & 0xFF
        driver[e + 5] = (dest >> 8) & 0xFF
        driver[e + 6] = flags

    # ---- boot segments ---------------------------------------------------
    lo, ok = disk.payload("LO")
    assert ok, "LO crosses an unreadable sector"
    initbin = os.path.join(BUILD, "init_u1.bin")
    initsym = os.path.join(BUILD, "init_u1.sym")
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
       "-o", initbin, "-l", initsym, os.path.join(paths.ASM, "init_u1.s"))
    init = Path(initbin).read_bytes()
    # boot_u1.s (the standalone launcher, run-u1test) calls the stub's tc_init
    with open(os.path.join(BUILD, "u1_init.s"), "w") as fh:
        fh.write(f"U1_TC_INIT = ${symbol(initsym, 'tc_init'):04x}   ; generated by ultima/games/u1/build.py\n")
    # LO is 3.5 KiB of title screen and loader; crunching it is free here
    # because the menu can decrunch a segment.
    segments = [
        (flash.add(bytes(driver)), len(driver), 0, DRIVER_ADDR),
        _seg(zx.place_segment(flash, lo), 0x0800),
        (flash.add(decruncher), len(decruncher), 0, DECODER_ADDR),
        (flash.add(init), len(init), 0, INIT_ADDR),
        (flash.add(ext), len(ext), 0, EXT_ADDR),
    ]
    if view:
        blob, sym = view
        hooks = blob[VIEW_ADDR - VIEW_ORG:sym["hooks_end"] - VIEW_ORG]
        segments.append((flash.add(hooks), len(hooks), 0, VIEW_ADDR))
        anim = blob[:sym["anim_end"] - VIEW_ORG]
        segments.append((flash.add(anim), len(anim), 0, VIEW_ORG))

    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, flags, dest in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, (length >> 8) & 0xFF,
                       dest & 0xFF, (dest >> 8) & 0xFF, flags])
    assert len(desc) <= 64, len(desc)

    # Emit the image out to the end of the save region, and do not trim it.
    # Unwritten tail is "assumed erased" per the TCRT spec, but that is only
    # true of a virgin cart -- on a reused one, stale bytes in an unseeded
    # save block could pass the $A5$5A check and be read back as a save.
    # Covering the region explicitly makes the flash tool erase it.
    save_end = SAVE_BASE + (ENTRIES - SAVE_FIRST) * ERASE_BLOCK
    regions.check("u1", flash.cursor, save_end)
    # for the launcher page (asm/page.s): the roster slot and the first
    # character's; the others follow one erase block apart
    page = dict(U1_RO=SAVE_BASE + (17 - SAVE_FIRST) * ERASE_BLOCK,
                U1_P0=SAVE_BASE + (18 - SAVE_FIRST) * ERASE_BLOCK)
    # export/import (xfer.py): the roster and the four characters, files on
    # the one disk, saved as the game saves them (scratch, then SAVE); a
    # character slot with nothing in it is skipped, and one missing on the
    # disk is erased on the cart (the original would say "Disk error.")
    bam = disk.sector(18, 0)
    slots = [xfer.File(page["U1_RO"], xfer.BYTES, "RO", save_start[1], 64, 64)]
    slots += [xfer.File(page["U1_P0"] + i * ERASE_BLOCK, xfer.BYTES, f"P{i}",
                        save_start[2 + i], save_len[2 + i], save_len[2 + i], optional=True)
              for i in range(4)]
    assert save_len[1] == 64 and save_len[2:] == [458] * 4, (save_len,)
    xf = [xfer.Disk("Ultima I", bam, slots)]
    # POWERS (the page's X): a launch poke of pw_on, as U2's
    options = dict(caps=patches.caps(OPTION_PATCHES) | patches.POWERS,
                   addr=symbol(drvsym, "pt_opts"),
                   pokes={patches.POWERS: [(symbol(drvsym, "pw_on"), 0x80)]})
    return dict(name="ULTIMA I", blobs=list(flash.blobs), desc=bytes(desc), page=page,
                options=options, loaded=loaded, xfer=xf,
                save_end=save_end, used=flash.used, cursor=flash.cursor)
    img = TCRT(data_address=0, data_length=3, call_address=0x0801,
               filename="ULTIMA 1", flash=flash.image(size=save_end))
    img.write(out, trim=False)

def main():
    """Write a standalone image for this game alone -- what the per-game
    make targets and tests use.  ultima/build.py merges parts() instead."""
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BUILD, "u1.tcrt")
    p = parts()
    blobs = list(p["blobs"]) + [(DESC_OFFSET, p["desc"])]
    img = TCRT(data_address=0, data_length=0, call_address=0,
               filename="ULTIMA 1", flash=image_from(blobs, p["save_end"]))
    img.write(out, trim=False)
    print(f"{out}")
    print(f"  data ends {p['cursor']:#08x}, saves end {p['save_end']:#08x}, "
          f"{p['used']/1024:.1f} KiB placed")


if __name__ == "__main__":
    main()
