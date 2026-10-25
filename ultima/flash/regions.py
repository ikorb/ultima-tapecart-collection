#!/usr/bin/env python3
"""Flash region map for the whole collection.

One place that decides where each game's data and save areas live, so the
per-game build scripts hold no absolute flash addresses.

The map is laid out from two tables of sizes rather than written out as
addresses: game data grows up from the reserved area, saves sit at fixed
addresses down from the top of flash (see SAVES).  Every save slot is a whole
4 KiB erase block -- writing a save must never mean reading back and
rewriting a neighbour -- and that is the only alignment the drivers need.  Save bases used to be 64 KiB aligned so
ERASE_FLASH_64K would be usable on them, but nothing uses that command, and
the alignment quantised the whole map: shrinking a data region only freed
flash if it happened to cross a 64 KiB boundary.
"""
import contextlib

FLASH_SIZE = 0x200000           # 2 MiB
ERASE_BLOCK = 0x1000
PAGE = 0x100

# $000000-RESERVED is reserved.  The tapecart's own initial loader fastloads
# the first stage (asm/boot.s), BOOT_LEN bytes from BOOT_PRG -- the loadinfo,
# which only a full .tcrt flash writes, so these three never change -- and
# the first stage loads the launcher (MENU_PRG, the menu's PRG) from the
# locator at LAUNCHER_LOC, at whatever length the build gave it.  The menu
# then reads its game list and, once a game is picked, that game's
# descriptor.
RESERVED = 0x008000
MENU_TABLE = 0x000000           # game list: count, then one record per game
LAUNCHER_LOC = 0x0000F8         # the launcher's flash address (3) and length (2)
BOOT_PRG = 0x000800             # the first stage, a PRG, padded to BOOT_LEN
BOOT_LEN = 0x800
BOOT_ORG = 0x1000               # where it runs (the launcher's staging buffers)
DESC_BASE = 0x000100            # descriptor page per game, DESC_BASE + n*256
C128_DESC = DESC_BASE + 6 * PAGE   # Ultima V on a C128: what launch128.s loads
                                # (the seventh descriptor page)
MENU_PRG = BOOT_PRG + BOOT_LEN  # the launcher -- font, page, menu, export
                                # tables -- as one PRG; MENU_PRG_END - MENU_PRG
                                # is how much room it has, and ultima/build.py
                                # checks it

MENU_NAME_LEN = 16
MENU_RECORD = MENU_NAME_LEN + 2  # name, descriptor index, descriptor page

K = 1024

# Game data grows upward from RESERVED, in this order.  A region is whole
# pages (nothing reads game data by erase block: an update image rewrites all
# of it), sized to what the game takes, rounded up to a quarter KiB, plus half
# a KiB of headroom -- so a small change does not need a new map, and a
# larger one stops the build (regions.check) rather than silently overlapping
# the next game.  The figures in the comments are the extents measured.
DATA = [
    # game   data              what it holds
    ("u1",    57 * K + 512),   # 56.8 KiB, crunched
    ("u3",    67 * K + 512),   # 67.0 KiB, crunched
    ("u2",    68 * K),         # 67.3 KiB, crunched, and the raw save seeds
                               # (u2log.py)
    ("u4",   288 * K + 768),   # 288.2 KiB: distinct pages, zx02, + block maps
                               # -- a fifth for the Remastered tile set and
                               # creation (ultima/games/u4/tileset.py)
    ("u5",   483 * K + 512),   # 483.0 KiB: files and raw sectors, zx02 behind
                               # the cart directory and block maps; the C128
                               # pieces; the Action Replay's music (11.5 KiB)
    ("u6",   608 * K + 768),   # 608.0 KiB: Game-disk files raw, the rest zx02,
                               # Surface/Dungeon sectors raw behind block maps,
                               # the on-demand code's two parts for an REU
    ("u0",    15 * K + 512),   # 15.0 KiB: Akalabeth, the program and LIB, zx02
    ("launcher", 4 * K + 768), # 4.25 KiB: what the page restores on a reset,
                               # every game's fresh save slots, a run per page
                               # (the page itself is in the menu's PRG, in the
                               # reserved area)
]

# Save regions sit at the TOP of flash, at addresses that never depend on the
# game data.  That is what lets a new build be flashed without touching the
# saves: the build also writes an update image that stops at SAVE_AREA, and
# the flash tool's "Write data file" at offset 0 erases only what it writes
# (its "Write TCRT" erases everything after the image, saves included).  So
# this table only ever grows at its low end: U6 is last, and its region -- the
# save plus the write log for its world data -- can grow downward without
# moving anyone else's.
SAVES = [
    # game  size       what it holds (from the top of flash down)
    ("u1",   32 * K),  # 6 slots of 4 KiB, the journal, the settings block
    ("u3",   48 * K),  # 5 slots of 8 KiB, the journal (8 KiB)
    ("u2",   32 * K),  # a write log, two halves of 16 KiB (u2log.py)
    ("u4",   24 * K),  # 5 slots of 4 KiB, the journal
    ("u5",   28 * K),  # 6 slots of 4 KiB, the journal
    ("u6",  256 * K),  # the save, and the write log for the chunk files
]


# The launcher's settings: one page in the top erase block of flash, the
# spare seventh block of U1's save region (U1 uses six).  Like the saves it
# is above SAVE_AREA, so an update image keeps it; a reset of U1's saved
# game must leave it alone (check() and the page's reset tables see to it).
SETTINGS = FLASH_SIZE - ERASE_BLOCK
# It starts "UCFG" (asm/page.s), and the byte at SET_LAYOUT says which save
# layout this cart's save area is in: the build seeds the page in the full
# image, and the first stage (asm/boot.s) starts nothing while it is not
# LAYOUT -- an update image flashed over a cart whose saves are laid out
# differently, which a game would misread.  0 (or an erased page) is any
# cart flashed before the stamp.  Raise LAYOUT whenever a save moves or
# changes format.
SET_MAGIC = b"UCFG"
SET_LAYOUT = 0x0C
LAYOUT = 1

# The journals (asm/journal.s): one block (two for U3's 8 KiB slots) at the
# top of each fixed-slot save region, below the settings block.  A save is
# written there first -- the slot's pages from the journal's second page on,
# then a header on its first page, JOURNAL_MAGIC and the slot's flash
# address bits 8-23 -- then into the slot itself, and the journal's first
# block is erased.  A power cut anywhere leaves either the old save in its
# slot (the header was not written) or a whole new one in the journal, which
# the first stage copies into the slot at the next power-on.
JOURNAL = {"u1": 4 * 1024, "u3": 8 * 1024, "u4": 4 * 1024, "u5": 4 * 1024}
JOURNAL_MAGIC = b"JN"


def journal(game):
    """(base, size) of a game's journal."""
    return save_region(game)[1] - JOURNAL[game], JOURNAL[game]


def _lay_out():
    out, cursor = {}, RESERVED
    data = {}
    for name, size in DATA:
        assert size % PAGE == 0, f"{name} data is not whole pages"
        data[name] = (cursor, cursor + size)
        cursor += size
    top = FLASH_SIZE
    saves = {}
    for name, size in SAVES:
        assert size % ERASE_BLOCK == 0, f"{name} save size is not whole erase blocks"
        saves[name] = (top - size, top)
        top -= size
    assert cursor <= top, f"game data runs {cursor - top} bytes into the save area"
    for name in saves.keys() | data.keys():
        db, dl = data.get(name, (0, 0))
        sb, sl = saves.get(name, (0, 0))
        out[name] = (db, dl, sb, sl)
    return out, cursor, top


REGIONS, DATA_END, SAVE_AREA = _lay_out()


def free():
    """Bytes between the end of the game data and the save area."""
    return SAVE_AREA - DATA_END


# The page's tables are by descriptor index; the first six descriptors are
# pages 1-6 of flash, the seventh page is U5's C128 descriptor and the first
# stage follows, so Akalabeth's (and any after it) are the top pages of the
# reserved area, below which the launcher's PRG must end.
DESC_INDEX = {"u1": 0, "u3": 1, "u2": 2, "u4": 3, "u5": 4, "u6": 5, "u0": 6}
FIRST_PAGES = 6
MENU_PRG_END = RESERVED - (len(DESC_INDEX) - FIRST_PAGES) * PAGE


def data_base(game):
    return REGIONS[game][0]


def save_region(game):
    """(base, end) of a game's save region, less the settings block."""
    _db, _dl, sb, sl = REGIONS[game]
    return sb, min(sl, SETTINGS) if sb <= SETTINGS < sl else sl


def save_base(game):
    return REGIONS[game][2]


def desc_offset(game):
    i = DESC_INDEX[game]
    if i < FIRST_PAGES:
        return DESC_BASE + i * PAGE
    return RESERVED - (i - FIRST_PAGES + 1) * PAGE


# Off while a build runs on the reference disks rather than on stand-ins (the
# manifest's trace, verify's reference run): those make no cart, and their
# save units hold the master's residue where a cart has the generated base --
# U5 stores the save files' sectors in its raw runs, which then compress
# worse.  Only a cart has to fit.
_CHECKING = [True]


@contextlib.contextmanager
def unchecked():
    """Builds inside run without check(): not a cart (see _CHECKING)."""
    _CHECKING.append(False)
    try:
        yield
    finally:
        _CHECKING.pop()


def check(game, data_end, save_end):
    """Raise if a game has outgrown the region it was given."""
    if not _CHECKING[-1]:
        return
    db, dl, sb, sl = REGIONS[game]
    if data_end > dl:
        raise SystemExit(f"{game}: data reaches {data_end:#08x}, region ends {dl:#08x} "
                         f"({(data_end - dl) / 1024:.1f} KiB over)")
    if save_end > sl:
        raise SystemExit(f"{game}: saves reach {save_end:#08x}, region ends {sl:#08x}")
    if sb <= SETTINGS < sl and save_end > SETTINGS:
        raise SystemExit(f"{game}: saves reach {save_end:#08x}, into the launcher's "
                         f"settings at {SETTINGS:#08x}")
    if game in JOURNAL and save_end > journal(game)[0]:
        raise SystemExit(f"{game}: saves reach {save_end:#08x}, into its journal at "
                         f"{journal(game)[0]:#08x}")
    if sb % ERASE_BLOCK:
        raise SystemExit(f"{game}: save base {sb:#08x} is not erase-block aligned")


def overlaps():
    """[(a, b)] for any pair of regions that collide -- used by the tests."""
    spans = []
    for name, (db, dl, sb, sl) in REGIONS.items():
        if dl > db:
            spans.append((db, dl, f"{name} data"))
        if sl > sb:
            spans.append((sb, sl, f"{name} save"))
    spans.sort()
    bad = []
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        if a1 > b0:
            bad.append((an, bn))
    return bad


def launcher_prg(flash):
    """The launcher's PRG as the first stage finds it, through the locator."""
    loc = flash[LAUNCHER_LOC:LAUNCHER_LOC + 5]
    addr, length = int.from_bytes(loc[:3], "little"), int.from_bytes(loc[3:], "little")
    return bytes(flash[addr:addr + length])
