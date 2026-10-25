#!/usr/bin/env python3
"""Build the Ultima 6 flash layout.  WORK IN PROGRESS: the in-game driver
and the storage it reads; the boot driver and the menu descriptor are next.

What the game asks for, and where it comes from (U6 notes 5b, and a traced
play session of 2239 commands):

  %NAME   the resident loader's names, all on the Game disk (3B).  Stored as
          the file without its 2-byte PRG header, which that loader discards.
  /NAME   `game`'s names: conversations T001-T202 on the Populace disks and
          the chunk files Sxx/Dxx on Surface/Dungeon.  Stored whole.
  !NAME   a chunk file's first track/sector, for the save's own file writes.
  ^ t s   a sector of Surface or Dungeon -- the 610 distinct sectors that
          belong to no file, track 18, and the save area.  Stored raw,
          page aligned, behind a block map per disk (21 entries per track);
          the save area is marked M_LOGGED, because the game writes it,
          and the BAMs M_BAM: read as the original, writes dropped.  Sectors of files are never read this way (traced);
          their entries point at a page of zeros.

Every name is one entry in the cart's directory: a 12-byte key (the name as
sent, prefix included) and 8 bytes of data.  Written world state goes to a
log in U6's save region (see u6bulk.s), whose own directory is searched
first.
"""
import hashlib
import os
import re
import subprocess
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths

from ultima.disks.d64 import D64, SECTORS_PER_TRACK
from ultima.flash.layout import Layout
from ultima.flash import regions
from ultima.launcher import xfer
from ultima.flash import zx
from ultima.pin import Pin


BUILD = paths.BUILD

TAGS = ["1A", "1B", "2A", "2B", "3A", "3B"]
SECTOR_DISKS = {"1A": 0, "1B": 1}           # u6_disk: Surface, Dungeon
KEYLEN, DATALEN = 12, 8
F_ZX, F_LINKS = 0x01, 0x02
M_LOGGED = 0xFF
GRID = 21                                   # block map entries per track
LOGGED = {("1A", 6, s) for s in range(9, 21)}
# The BAMs are read, but always as the original, and their writes dropped
# (u6.inc, M_BAM): the save allocates chunk-file sectors from the BAM, the
# drive's `!` frees the file's old chain first, the cart's cannot -- so a
# logged BAM loses 13 sectors a save and 1A's 74 free ones run out after
# about five, and chunk files are then saved cut short.
BAMS = {("1A", 18, 0), ("1B", 18, 0)}
M_BAM = 0xFE

GAME_ADDR = 0x0200
PIECE_A = (0x2823, 0x28CE)                  # $2823-$28CD
PIECE_B = (0x2989, 0x2B4E)                  # $2989-$2B4D
BULK_A, BULK_B, BULKMAX = 0xD800, 0xDC00, 0x400
SECTORS = {t: 21 if t < 18 else 19 if t < 25 else 18 if t < 31 else 17 for t in range(1, 36)}


def disk_path(tag):
    return paths.disk("u6-" + tag.lower())



def sh(*args):
    subprocess.run(args, check=True)


def symbols(path):
    with open(path) as fh:
        text = fh.read()
    return {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", text, re.M)}


def file_sectors(d):
    """(track, sector) of every sector that belongs to a file."""
    out = set()
    for _name, _t, t, s, _b in d.directory():
        seen = set()
        while t and (t, s) not in seen:
            seen.add((t, s))
            out.add((t, s))
            blk = d.sector(t, s)
            t, s = blk[0], blk[1]
    return out


def key(text):
    raw = text if isinstance(text, bytes) else text.encode("latin1")
    assert len(raw) <= KEYLEN, raw
    return raw.ljust(KEYLEN, b"\x00")


def assemble_drivers():
    """The resident part, then the on-demand part at both origins against
    the resident's symbols."""
    os.makedirs(BUILD, exist_ok=True)
    res_bin, res_sym = os.path.join(BUILD, "u6res.bin"), os.path.join(BUILD, "u6res.sym")
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", HERE,
       "-o", res_bin, "-l", res_sym, os.path.join(HERE, "u6res.s"))
    rsym = symbols(res_sym)
    with open(os.path.join(BUILD, "u6res_syms.inc"), "w") as fh:
        for name, addr in sorted(rsym.items()):
            if (name.startswith("u6_") or name.startswith("tc_")) and name != "tc_sx":
                fh.write(f"{name} = ${addr:04x}\n")
    with open(res_bin, "rb") as fh:
        blob = fh.read()
    origin = PIECE_A[0]
    # acme emits one blob from piece A to the end of piece B; the gap between
    # (the keyboard scan at $28CE-$2988, which stays) must be untouched zeros
    a_end, b_end = rsym["u6_piece_a_end"], rsym["u6_piece_b_end"]
    assert a_end <= PIECE_A[1] and b_end <= PIECE_B[1], (hex(a_end), hex(b_end))
    gap = blob[a_end - origin:PIECE_B[0] - origin]
    assert not any(gap), "resident driver bytes between its pieces"
    pieces = [(PIECE_A[0], blob[:a_end - origin]),
              (PIECE_B[0], blob[PIECE_B[0] - origin:b_end - origin])]
    # $02AE in `game`'s jump table is JMP $29B6, which was a lone RTS
    assert blob[0x29B6 - origin] == 0x60, "$29B6 is no longer an RTS"
    # the REU's code, once for its labels: parts A and B link against them
    # (apply_reu assembles it again with the real flash addresses, and checks
    # that none of these moved)
    reu_syms(reu_defs(0, 0, 0x4600, 0, 0))
    # the on-demand part and, fetched over it when the log is full, the
    # in-game compactor -- each assembled for both halves of the sprite buffer;
    # and the on-demand part's two parts for an REU (u6wc.s)
    log_lo, log_hi = regions.save_base("u6"), regions.REGIONS["u6"][3]
    bulks, packs, bsyms = {}, {}, {}
    for org in (BULK_A, BULK_B):
        for what, src, defs in (("u6bulk", "u6bulk", []), ("u6pack", "u6pack", []),
                                ("u6reua", "u6bulk", ["-DU6_PART_A=1"]),
                                ("u6reub", "u6bulk", ["-DU6_PART_B=1"])):
            out = os.path.join(BUILD, f"{what}_{org:04x}.bin")
            sym = os.path.join(BUILD, f"{what}_{org:04x}.sym")
            sh("acme", "-f", "plain", "-I", paths.ASM, "-I", HERE, "-I", BUILD,
               f"-DBULK_ORG=${org:04x}", f"-DLOG_LO=${log_lo:x}", f"-DLOG_HI=${log_hi:x}", *defs,
               "-o", out, "-l", sym, os.path.join(HERE, f"{src}.s"))
            with open(out, "rb") as fh:
                img = bytearray(fh.read())
            assert len(img) <= BULKMAX, (what, len(img))
            bulks.setdefault(what, {})[org] = img
            bsyms.setdefault(what, {})[org] = symbols(sym)
    packs = bulks.pop("u6pack")
    bsyms.pop("u6pack")
    return pieces, rsym, bulks, packs, bsyms


# `LDA #$35 / STA $01` in the IRQ handlers of `game`, `create` and the
# resident loader: $35 has bit 3 (cassette write) clear, and the 1-bit
# handshake clocks on that line, so an interrupt during a transfer would be
# an extra clock edge.  `ORA #$05 / STA $01` gives the same banking from any
# value the game uses ($34, $35, and the transfer's all-RAM) and keeps bits
# 3-5 as they were; the handlers' own `PLA / STA $01` puts the rest back.
# The ending's overlay: where it sits, where its own loader starts, and its
# IRQ's bank-in (see u6end.s)
END_TRACK, END_SECTORS, END_ORG = 23, (16, 17, 18), 0xC800
END_LOADER, END_IRQ = 0xC8C2, 0xC892

IRQ_WANT = bytes([0xA9, 0x35, 0x85, 0x01])
IRQ_NEW = bytes([0x09, 0x05, 0x85, 0x01])


# `game`'s IRQ from the direction-key search to the queue's end, $1F76-$1FB6:
# replaced whole by u6key.s (same length)
KEY_QUEUE = Pin("#65:396850e75230911a")


def patch(image, addr, load, want, new, what):
    """Patch `image`, a PRG with its 2-byte header, at run-time address addr."""
    off = addr - load + 2
    if bytes(image[off:off + len(want)]) != want:
        raise SystemExit(f"{what}: expected {want.hex(' ')} at {addr:#06x}, "
                         f"found {bytes(image[off:off + len(want)]).hex(' ')}")
    image[off:off + len(new)] = new


# The speed patches: three routines of the map view, rewritten with the same
# effect (u6flood.s, u6light.s, u6view.s; each file's header says how).  Each
# source gives its spans by label; FAST_ORIGINAL is the CRC of what they
# replace -- the whole range from the first byte to the last, tables and the
# spare room between included -- so a different disk is refused.
FAST_SOURCES = {                    # in this order: u6view.s is told where the others' spare room is
    "u6flood.s": [("f_exp", "f_end")],
    "u6light.s": [("l_start", "l_code_end"), ("l_ac", "l_end")],
    "u6view.s": [("v_start", "v_end"), ("v_dark", "v_dark_end"), ("v_lit", "v_lit_end")],
    "u6walk.s": [("w_jump", "w_jump_end"), ("w_tab", "w_tab_end"), ("w_tab2", "w_tab2_end"),
                 ("w_call", "w_call_end"),
                 ("w_walk", "w_end")],             # w_walk is in the init's freed room
    "u6clear.s": [("c_jump", "c_jump_end"), ("c_pre", "c_end")],     # so is c_pre
    "u6chunk.s": [("k_full", "k_box_end"), ("k_end", "k_end_end"), ("k_r2", "k_cells_end"),
                  ("k_r3", "k_3fbd_end"), ("k_rows", "k_rows_end"), ("k_cd", "k_vars_end"),  # these two:
                  ("k_call1", "k_call1_end"), ("k_call2", "k_call2_end")],                    # the init's room
    "u6scan.s": [("s_scan", "s_end"), ("s_hook", "s_hook_end"),          # the keyboard scan, the latch,
                 ("s_pop", "s_pop_end"), ("s_ret", "s_ret_end"), ("s_fire", "s_fire_end")],  # Return as fire
}
FAST_ORIGINAL = {
    (0x1697, 0x178C): 0xDB0C1D7F,           # the draw loop and its helper
    (0x17A3, 0x189F): 0x8DE700FC,           # the line-of-sight flood
    (0x18E8, 0x198E): 0x7C874560,           # the light map and its table
    (0x27CE, 0x27F4): 0x4AD22B65,           # the object pool walk
    (0x17A0, 0x17A3): 0x0AEF5FDF,           # the flood's prologue store, STA $D63C
    (0x25FB, 0x27B1): 0xC1AC165A,           # the window's chunk loops, fetch and object overlay
    (0x33B8, 0x33F2): 0x51F81A0F,           # $3399's copy of one chunk's objects
    (0x3FBD, 0x4001): 0xB0D0AC77,           # the whole window's objects again
    (0x1197, 0x11A0): 0x74D7ABA4,           # the step's two strip calls
    (0x02BA, 0x02BD): 0x5698B8F2,           # the jump table's JMP $27E3 (the old walk's end test)
    (0x02D5, 0x02D8): 0x875A03BB,           # the jump table's JMP $27EA
    (0x338B, 0x338E): 0xC69731FF,           # $338B's JSR $27EA (the old walk's "next node")
    (0x28CE, 0x2989): 0x89CA4238,           # the keyboard scan
    (0x1FB7, 0x1FBE): 0xEAB275D0,           # the IRQ input handler's tail
    (0x046C, 0x046F): 0xC118EB20,           # the read's end, STA $44 / RTS (u6scan.s: Return as fire)
}


def assemble_fast():
    """The speed patches as [(address, bytes)], from the sources."""
    out, labels = [], {}
    for name, spans in FAST_SOURCES.items():
        path = os.path.join(BUILD, name.replace(".s", ".bin"))
        sym = os.path.join(BUILD, name.replace(".s", ".sym"))
        defines = []
        if name == "u6clear.s":             # where the flood starts and where its pass over the cells does
            defines = [f"-Df_exp=${labels['f_exp']:04x}", f"-Df_all=${labels['f_all']:04x}"]
        if name == "u6view.s":              # the spare room: the flood's tail, the light map's middle
            defines = [f"-Dv_dark=${labels['f_end']:04x}", "-Dv_dark_limit=$189f",
                       f"-Dv_lit=${labels['l_code_end']:04x}", f"-Dv_lit_limit=${labels['l_ac']:04x}"]
        sh("acme", "-f", "plain", *defines, "-l", sym, "-o", path, os.path.join(HERE, name))
        mine = symbols(sym)
        labels.update(mine)
        with open(path, "rb") as fh:
            blob = fh.read()
        origin = min(mine[a] for a, _b in spans)
        for first, end in spans:
            out.append((mine[first], blob[mine[first] - origin:mine[end] - origin]))
    return out


def apply_fast(game_file, tiles):
    """Lay the speed patches over `game_file` (a PRG at GAME_ADDR with its
    header), after checking the original and what the patches rely on."""
    def at(addr, n):
        off = addr - GAME_ADDR + 2
        return bytes(game_file[off:off + n])
    for (first, end), crc in FAST_ORIGINAL.items():
        got = zlib.crc32(at(first, end - first))
        if got != crc:
            raise SystemExit(f"speed patches: ${first:04x}-${end - 1:04x} is not the original "
                             f"(CRC {got:08x}, expected {crc:08x})")
    # u6view.s: a lit cell's mask is $FF all through (the AND is left out)
    assert tiles[:2] == b"\x00\x60" and len(tiles) == 2 + 0x4000
    assert tiles[2 + 0x93C0 - 0x6000:2 + 0x93D0 - 0x6000] == b"\xff" * 16, "TILES: level 4's mask"
    # u6view.s: a cell's lower half is 320 bytes (one character row) after its upper
    for row in range(9):
        top = at(0x1E3A + 2 * row, 1)[0] | at(0x1E4C + 2 * row, 1)[0] << 8
        bot = at(0x1E3B + 2 * row, 1)[0] | at(0x1E4D + 2 * row, 1)[0] << 8
        assert bot == top + 0x140, f"view row {row}: the bitmap rows are not 320 apart"
    # u6light.s: the 46 distances it keeps are the original table's, and
    # nothing reads the table past 8 x 5 + 5
    patches = assemble_fast()
    by_addr = dict(patches)
    kept = by_addr[0x1955]                # |n - 5| (11 bytes), then the distances
    assert kept[:11] == bytes(abs(n - 5) for n in range(11))
    assert kept[11:] == at(0x194E, 46), "u6light.s: the distance table is not the original's"
    assert at(0x2061, 1) == b"\x60", "u6scan.s's s_ret branches to an RTS at $2061"
    spans = sorted((addr, addr + len(data)) for addr, data in patches)
    for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
        assert a1 <= b0, f"speed patches overlap: ${a0:04x}-${a1 - 1:04x} and ${b0:04x}-${b1 - 1:04x}"
    for addr, data in patches:
        off = addr - GAME_ADDR + 2
        if any(a <= addr < b for a, b in INIT_FREED):       # in the init's freed room: it must be free
            assert not any(game_file[off:off + len(data)]), f"${addr:04x}: the init's room is not free"
            assert any(a <= addr and addr + len(data) <= b for a, b in INIT_FREED), "a patch over the room's edge"
        game_file[off:off + len(data)] = data


# `game`'s one-time init -- the machine setup at $038F, the screen frame at $1302
# (with its 12 bytes of table) and the page-1/actor-table fill at $2077 -- runs
# once, from the boot's hand-off (`JMP $0200`, `$0200` being `JMP $038F`), and
# nothing names its bytes afterwards (docs/developer/u6.md).  So the cart
# runs a relocated copy instead: u6boot.s's hand-off reads it from flash to
# INIT_AT, where nothing lives until the window loads, and jumps there; the
# copy ends in `JMP $03FC`, the main loop's entry.  The 347 bytes in `game`
# are left zero, free for the speed patches.
INIT_AT = 0x4400
INIT_FREED = [(0x038F, 0x03FC), (0x1302, 0x13DA), (0x2077, 0x208D)]


INIT_TAIL = bytes([0x4C, 0xFC, 0x03])   # what the init ends in without the REU's part: JMP $03FC


def relocate_init(game_file):
    """The relocated init as bytes for INIT_AT, ending in a JMP to its own end,
    where a tail goes (INIT_TAIL, or reu_init: u6reu.s); zeroes the freed ranges of game_file."""
    def at(first, end):
        off = first - GAME_ADDR + 2
        return bytes(game_file[off:off + end - first])
    setup, calls = at(0x038F, 0x03F5), at(0x03F5, 0x03FC)
    fill, frame = at(0x2077, 0x208D), at(0x1302, 0x13DA)
    assert zlib.crc32(at(0x038F, 0x03FC)) == 0x55371BA9, "game's init is not the original"
    assert zlib.crc32(fill) == 0xB46E8B67 and zlib.crc32(frame) == 0x9FAEF6CB, "game's init is not the original"
    assert calls == bytes([0x20, 0x77, 0x20, 0x58, 0x20, 0x02, 0x13]), "game's init calls moved"
    fill_at = INIT_AT + len(setup) + 3 + 1 + 3 + 3          # after the setup, JSR fill, CLI, JSR frame, JMP
    frame_at = fill_at + len(fill)
    table_at = frame_at + (0x13CE - 0x1302)
    frame = bytearray(frame)
    for off, old in ((0x13B3, 0x13CE), (0x13B6, 0x13D2), (0x13BB, 0x13D6)):  # the table's three reads
        o = off - 0x1302
        assert frame[o + 1:o + 3] == bytes([old & 0xFF, old >> 8]), "the frame's table reads moved"
        new = table_at + old - 0x13CE
        frame[o + 1:o + 3] = bytes([new & 0xFF, new >> 8])
    end_at = frame_at + len(frame)
    blob = (setup + bytes([0x20, fill_at & 0xFF, fill_at >> 8, 0x58, 0x20, frame_at & 0xFF, frame_at >> 8,
                           0x4C, end_at & 0xFF, end_at >> 8]) + fill + bytes(frame))
    assert INIT_AT + len(blob) == end_at
    for first, end in INIT_FREED:
        off = first - GAME_ADDR + 2
        game_file[off:off + end - first] = bytes(end - first)
    return blob


# The optional REU read cache (u6reu.s): a hook on tc_read, its code in the init's
# freed room, its detection in the relocated init's tail.  Needs the raw sector
# pages' place in flash, so it is applied late.
REU_ROOM = {"RC_CODE": 0x132E, "RC_CODE2": 0x03C9, "RC_VARS": 0x2077}
REU_LIMITS = [(0x132E, 0x13DA), (0x03C9, 0x03FC), (0x2077, 0x208D)]
# what parts A and B (u6wc.s) take from the REU's code: they are assembled
# before it can be (its init needs their flash addresses), so against a first
# assembly of it, and apply_reu checks that the real one put these at the same place
REU_SHARED = ("rc_dma", "rc_set1", "rc_status", "rc_c64", "rc_ra", "rc_ln", "wc_bheld", "wc_spage", "wc_sbank",
              "wc_cap", "wc_ix", "wc_old", "wc_held")


def reu_defs(page_base, n_pages, init_at, part_a_dc, part_a_d8):
    defs = [f"-DRC_BASE=${page_base >> 8:04x}", f"-DRC_PAGES={n_pages}", f"-DRC_INIT=${init_at:04x}",
            f"-DRI_FL_DC=${part_a_dc:06x}", f"-DRI_FL_D8=${part_a_d8:06x}"]
    return defs + [f"-D{k}=${v:04x}" for k, v in REU_ROOM.items()]


def reu_syms(defs):
    """Assemble u6reu.s; its labels, and the shared ones as u6reu_syms.inc."""
    sym = os.path.join(BUILD, "u6reu.sym")
    out = os.path.join(BUILD, "u6reu.bin")
    sh("acme", "-f", "plain", "-I", BUILD, "-I", HERE, *defs, "-l", sym, "-o", out,
       os.path.join(HERE, "u6reu.s"))
    labels = symbols(sym)
    with open(os.path.join(BUILD, "u6reu_syms.inc"), "w") as fh:
        for name in REU_SHARED:
            fh.write(f"{name} = ${labels[name]:04x}\n")
    return labels


def apply_reu(game_file, init_blob, rsym, page_base, n_pages, part_a):
    """Lay the REU cache over game_file; returns the init blob with its tail.
    part_a: part A's flash address for each half (reu_init hands them to the
    resident)."""
    out = os.path.join(BUILD, "u6reu.bin")
    init_at = INIT_AT + len(init_blob)
    before = symbols(os.path.join(BUILD, "u6reu.sym"))
    labels = reu_syms(reu_defs(page_base, n_pages, init_at, part_a[BULK_B], part_a[BULK_A]))
    moved = [n for n in REU_SHARED if labels[n] != before[n]]
    assert not moved, f"u6reu.s: {moved} moved between its two assemblies"
    with open(out, "rb") as fh:
        blob = fh.read()
    origin = min(labels["tc_read"], REU_ROOM["RC_VARS"], REU_ROOM["RC_CODE2"], init_at)
    def part(first, end):
        return blob[first - origin:end - origin]
    def put_at(addr, data):
        off = addr - GAME_ADDR + 2
        game_file[off:off + len(data)] = data
    hook = labels["tc_read"]
    off = hook - GAME_ADDR + 2
    enter = rsym["tc_enter"]
    assert bytes(game_file[off:off + 3]) == bytes([0x20, enter & 0xFF, enter >> 8]), "tc_read does not start with JSR tc_enter"
    for first, end, name in ((REU_ROOM["RC_CODE"], labels["rc_code_end"], "first"),
                             (REU_ROOM["RC_CODE2"], labels["rc_end"], "second"),
                             (REU_ROOM["RC_VARS"], labels["rc_vars_end"], "variables")):
        assert any(a <= first and end <= b for a, b in REU_LIMITS), f"u6reu.s: the {name} piece is outside the room"
        o = first - GAME_ADDR + 2
        assert not any(game_file[o:o + end - first]), f"u6reu.s: the room for the {name} piece is not free"
        put_at(first, part(first, end))
    put_at(hook, part(hook, hook + 3))
    return init_blob + part(init_at, labels["reu_init_end"])


def reu_slots(entries, bang, n_pages, bsym):
    """Each chunk file's slot for the REU's copy of it (u6wc.s), in its
    `!NAME` entry, whose address and length nothing else reads: address =
    the slot's first page (bank, page), length = its size in pages (the
    file's own and one more, for a file that grows) and, high byte, the
    index of its count.  Bank 3 from page 4, then bank 2 from the read
    cache's end up to the save area's copies; a slot never crosses a bank."""
    c = {k: bsym[k] for k in ("WC_BANK", "WC_SAVE", "WC_SCRATCH", "WC_PART_A", "WC_PART_B",
                              "WC_COUNTS", "WC_CLEAR", "RC_FLAGBANK")}
    assert LOGGED == {("1A", 6, s) for s in range(9, 21)}, "u6wc.s keys the save area's copies by sector 9-20"
    assert c["WC_BANK"] == 2 and c["RC_FLAGBANK"] == 3 and c["WC_COUNTS"] == 0x300 and c["WC_CLEAR"] == 0x400
    assert c["WC_SAVE"] & 0x1F == 0 and c["WC_SAVE"] + 21 <= c["WC_SCRATCH"] < c["WC_PART_A"] \
        and c["WC_PART_A"] + 8 == c["WC_PART_B"] \
        and c["WC_PART_B"] + 8 == 0x100, "the REU's bank 2 layout (u6.inc)"
    cache_end = n_pages - 512                   # the read cache's first free page of bank 2
    assert 0 < cache_end <= c["WC_SAVE"] + 9, f"the read cache ({n_pages} pages) runs into the write cache"
    assert n_pages <= c["WC_COUNTS"], "the read cache's flags run into the counts"
    room = [(3, 4, 0x100), (2, cache_end, c["WC_SAVE"] + 9)]
    assert len(bang) < 0x80, "the chunk files' count indexes meet the save area's ($80 + sector)"
    for ix, (at, name, n) in enumerate(bang):
        for i, (bank, page, end) in enumerate(room):
            if page + n + 1 <= end:
                entries[at][1:3] = [("abs", bank << 16 | page << 8), (n + 1) | ix << 8]
                room[i] = (bank, page + n + 1, end)
                break
        else:
            raise SystemExit(f"no room in the REU for {name}'s copy ({n} pages)")


def put(pieces, addr, data):
    """Fill the placeholder at `addr` in one of the (base, blob) pieces."""
    for i, (base, blob) in enumerate(pieces):
        if base <= addr < base + len(blob):
            blob = bytearray(blob)
            off = addr - base
            assert blob[off:off + len(data)] == b"\xff" * len(data), f"{addr:#06x} placeholder moved"
            blob[off:off + len(data)] = data
            return pieces[:i] + [(base, bytes(blob))] + pieces[i + 1:]
    raise KeyError(hex(addr))


INIT_ADDR = 0x1000


# Export and import of the world (asm/page_u6x.s).  A save rewrites the
# chunk files wherever the BAM has room (U6 notes, save-game §2), so an
# export writes every chunk file -- the log's newest, or the original --
# through a fresh chain and a BAM of its own: the original BAM with the pool
# freed.  The pool is the chunk files' own sectors bar the first (which the
# directory fixes), then what the BAM has free on tracks 1-17, in the order
# the game's own allocator takes them (track 17 down, sector 0 up) -- less
# 1A T5 S20, free in the BAM but read by track and sector (the U6 research:
# the #SU group reads T5 S9-20).
XFER_LABELS = {"1A": "Surface (1A)", "1B": "Dungeon (1B)"}
XFER_NEVER = {("1A", 5, 20)}


def xfer_world(disks, starts):
    out = []
    for tag in SECTOR_DISKS:
        d = disks[tag]
        bam = bytearray(d.sector(18, 0))
        files, own = [], []
        for name, _ty, t, s, _b in d.directory():
            assert starts[name] == (t, s), name
            files.append((name, t, s))
            chain, ct, cs = [], t, s
            while ct:
                chain.append((ct, cs))
                blk = d.sector(ct, cs)
                ct, cs = blk[0], blk[1]
            own += chain[1:]

        def is_free(t, s):
            return bool(bam[4 * t + 1 + s // 8] & (1 << (s % 8)))
        free = [(t, s) for t in range(1, 18) for s in range(SECTORS_PER_TRACK[t])
                if is_free(t, s) and (tag, t, s) not in XFER_NEVER]
        pool = sorted(set(own) | set(free), key=lambda ts: (-ts[0], ts[1]))
        for t, s in pool:                           # free in the export's BAM
            bam[4 * t + 1 + s // 8] |= 1 << (s % 8)
        for t in range(1, 36):                      # and the counts true
            bam[4 * t] = sum(1 for s in range(SECTORS_PER_TRACK[t]) if is_free(t, s))
        out.append(dict(files=files, pool=pool, bam=bytes(bam)))
    return out


# The copy-protection questions (the answers have long been published, and
# they only get in the way): Lord British (T005), Mariah
# (T033) and Selganor (T064) each ask one at random.  An answer list is
# ASK ($F7), then per answer KEYWORDS ($EF) words ANSWER ($F6) and its
# statements, then ENDANSWERS ($EE); the catch-all "*" is the one that
# fails -- a JUMP to "that's not it" (Lord British, Selganor) or that text
# and a JUMP back to the question (Mariah).  Its first three bytes become a
# JUMP ($B0, 16-bit) to wherever the first, correct answer goes; the rest of
# it is never reached, and nothing moves.  "bye" still ends the talk.
# Each question as it is stored (u6_text), pinned by its length and SHA-256
# (first 16 digits): found in the conversation by those, no text kept here.
COMPENDIUM = {
    "T005": [(22, "2e66c6df5ad08829"), (51, "a1c380fe46dbf903"), (33, "5f6c6579b9cbd5b4"),
             (68, "a1663f22544fec53"), (32, "9f8e2864173135c3"), (29, "87a6da402040ccb4"),
             (41, "840f841048727074"), (39, "f7b9be329a972e34"), (50, "f7913fb274de2632"),
             (29, "b9db334c8e7c7ac8")],
    "T033": [(39, "5f153faed7ba1309"), (41, "e2dc092711c21ddc"), (40, "e5724ccb278d470d"),
             (40, "eb9c83eef909c4f2"), (40, "626a7689ee0600af")],
    "T064": [(57, "d41d7d8952a013f1"), (61, "1f98ec2d373c5982"), (35, "3205e2dea641840b"),
             (31, "50f1daf96849548f")],
}


def find_question(data, question):
    """Where a pinned question (length, hash) is in a conversation: exactly once."""
    n, h = question
    data = bytes(data)
    at = [i for i in range(len(data) - n + 1)
          if hashlib.sha256(data[i:i + n]).hexdigest()[:16] == h]
    assert len(at) == 1, f"question {h}: found {len(at)} times"
    return at[0]


# The shrines' level check (u6exp.s): T4's exp() returns experience / 50,
# and each shrine's threshold table -- the last 8 bytes of T191-T198 on 3A,
# the low bytes of 0 100 200 ... 6400 -- becomes those / 50.
EXP_ORG, EXP_SECTOR, EXP_TRACK = 0xC650, 15, 4      # T4: track 4 sectors 9-20 at $C000
EXP_OLD = Pin("#71:4bba5c16b71371d5")
SHRINES = [f"T{n}" for n in range(191, 199)]
SHRINE_OLD = bytes([0x00, 0x64, 0xC8, 0x90, 0x20, 0x40, 0x80, 0x00])
SHRINE_NEW = bytes([0x00, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80])

# Rest, the small overlay $20 (1A/1B T24 S16-18 at $C800): two bugs of the
# original.  (address, original bytes, new bytes)
REST_TRACK, REST_SECTORS, REST_ORG = 24, (16, 17, 18), 0xC800
REST_FIXES = [
    # The guard's "I hear something!" goes through $0383, the print that
    # returns from the overlay, so the JMP $C923 after the string -- rest
    # over, party woken -- never ran: the game went on resting ($589F, the
    # hours left), the campfire moved with the view, the party slept, and
    # once the Avatar left the list of actors in sight the moves read stale
    # data and stuck (reproduced in VICE on the original disks).  $0380
    # prints and carries on.
    (0xC93B, bytes([0x20, 0x83, 0x03]), bytes([0x20, 0x80, 0x03])),
    # "Who Will Stand Guard?": the answer less one must be at most $15 (the
    # party size less one); the original's BCS refused it when equal, so the
    # last member could not stand guard.  0 (or Return) still means nobody.
    #   DEX / CPX #$FF / BEQ ok / CPX $15 / BCS ask
    #   DEX / BMI ok   / CPX $15 / BEQ ok / BCS ask      (one hex digit: X <= 14)
    (0xC8E1, bytes.fromhex("ca e0 ff f0 04 e4 15 b0 ec"),
     bytes.fromhex("ca 30 06 e4 15 f0 02 b0 ec")),
]


# The text box's raster split in the opening, the intro and the ending
# (the box's first line flickers now and then, at least on PAL).  Each has a table of split lines, two before the box's
# first character row (a badline), and an IRQ there whose switch routine
# waits out a fixed delay (a JSR into BITs and NOPs) and then stores $D011,
# $D018 and $DD00 -- which have to land in the border between the line
# before the row and cycle 12 of the row, where the VIC takes the bus.  The
# delay counts cycles from an interrupt that jitters by up to 7 of them and
# was tuned for 65-cycle NTSC lines; measured in VICE (PAL), the stores ran
# from cycle 59 of the line before to cycle 1 of the row, the last at cycle
# 12 -- and any later interrupt lands them in the picture.
# Now the IRQ comes one line earlier (the table's values less one), and the
# routine waits for the line before the row itself (CPX $D012 / BCS: 7
# cycles of jitter, and no waiting a frame if it is late), then 43 cycles:
# the stores at cycles 59-73 -- the first after the line's last column, the
# last by cycle 10 of the row -- on 63-cycle PAL and 65-cycle NTSC lines
# alike (tests/test_u6_split.py, every entry delay).  Measured in VICE (PAL),
# the opening over 80 frames: the first store at cycles 59-65, the last by
# cycle 10 of the row, every frame.
SPLIT_FILES = {"OPENING": (0x0652, 0x0662), "INTRO": (0x0467, 0x0469), "END": (0x0424, 0x0426)}
SPLIT_Y = [bytes.fromhex("a9 0b 05 10 a8"), bytes.fromhex("a5 10 09 0b a8")]  # Y = $0B | $10
SPLIT_REST = Pin("#19:8a8eaf2b5f03759f")
SPLIT_LINES = [bytes([0xC1 + 8 * i for i in range(8)]), bytes([0xB1 + 8 * i for i in range(8)])]


def steady_split(data, name, load=0x0200):
    """data: the overlay's file (PRG header first), as the build stores it."""
    var, table = SPLIT_FILES[name]
    out = bytearray(data)
    at = lambda a: a - load + 2
    n = len(SPLIT_REST)
    hits = [(m.start(), m.end() + n, y) for y in SPLIT_Y for m in re.finditer(re.escape(y), bytes(out))
            if out[m.end():m.end() + n] == SPLIT_REST]
    assert len(hits) == 1, (name, len(hits))
    m_start, m_end, y = hits[0]
    rest = bytes(out[m_end - n:m_end])
    start = m_start - 3                         # its JSR to the delay comes first
    assert out[start] == 0x20
    delay = out[start + 1] | out[start + 2] << 8
    assert at(delay) == m_end, f"{name}: the delay does not follow the switch"
    end = out.index(0x60, m_end) + 1            # the delay's RTS
    assert set(out[m_end:end - 1]) <= {0x24, 0xEA}, f"{name}: the delay is not BITs and NOPs"
    new = (y + bytes([0xAE, var & 0xFF, var >> 8,   # ldx split     (the IRQ's line)
                      0xE8,                         # inx
                      0xEC, 0x12, 0xD0,             # - cpx $D012   until the line after
                      0xB0, 0xFB,                   #   bcs -        it has begun
                      0xA2, 0x08, 0xCA, 0xD0, 0xFD,  # 41 cycles
                      0xEA,                         # and 2
                      0xA2, 0x20])                  # ldx #$20
           + rest[:7]                               # lda $DD00 / and #$FC / ora #$01
           + bytes.fromhex("8c 11 d0 8e 18 d0 8d 00 dd 60"))
    assert new[-11:-10] == b"\x01" and new.endswith(bytes.fromhex("8c 11 d0 8e 18 d0 8d 00 dd 60"))
    assert len(new) <= end - start, (name, len(new), end - start)
    out[start:start + len(new)] = new
    out[start + len(new):end] = bytes([0xEA] * (end - start - len(new)))
    t = at(table)
    assert bytes(out[t:t + 8]) in SPLIT_LINES, (name, bytes(out[t:t + 8]).hex())
    out[t:t + 8] = bytes(v - 1 for v in out[t:t + 8])
    # the switch reads the split line from `var`, which the table feeds
    assert bytes([0xB9, table & 0xFF, table >> 8, 0x8D, var & 0xFF, var >> 8]) in out, name
    return bytes(out)


def u6_text(t):
    """The conversations' character set: a-z $01-$1A, the rest ASCII."""
    return bytes(ord(c) - 0x60 if "a" <= c <= "z" else ord(c) for c in t)


def any_answer_is_right(data, questions, name):
    out = bytearray(data)
    for q in questions:
        at = find_question(out, q)
        ask = out.index(0xF7, at)
        end = out.index(0xEE, ask)
        first = out.index(0xF6, ask)
        assert out[first + 1] == 0xB0, f"{name} {q!r}: the first answer is no jump"
        right = out[first + 2:first + 4]
        star = bytes(out).find(bytes([0xEF, 0x2A, 0xF6]), ask, end)
        assert star > 0, f"{name} {q!r}: no catch-all answer"
        out[star + 3:star + 6] = bytes([0xB0]) + right
    return bytes(out)


# The text boxes' "press a key" (checked on the original disks: in the
# Introduction only the joystick's button goes on).  OPENING,
# INTRO and END carry the same routine: port A to outputs, read the keyboard's
# column 4 (Space, among others), port A back to inputs, AND joystick 2 --
# reading whatever rows port A's data register selects, and none of the three
# ever sets it.  After the title menu's keyboard scan (CREATE's code, $0945)
# it is $FF, no row: no key.  The routine now shifts a zero into the data
# register each time it looks (ASL, port A driven), so within eight polls --
# frames -- every row is selected and stays so; X and Y are kept as before
# (INTRO's callers count in X), and port A is left as inputs as before.
KEYWAIT = {"OPENING": 0x0C22, "INTRO": 0x09ED, "END": 0x0AFE}
KEYWAIT_OLD = Pin("#21:38310fcb594239d3")
KEYWAIT_NEW = bytes([0xA9, 0xFF, 0x8D, 0x02, 0xDC,     # LDA #$FF / STA $DC02: port A out
                     0x0E, 0x00, 0xDC,                 # ASL $DC00: one more row selected
                     0xAD, 0x01, 0xDC,                 # LDA $DC01
                     0xEE, 0x02, 0xDC,                 # INC $DC02: port A in ($FF -> $00)
                     0x2D, 0x00, 0xDC,                 # AND $DC00: joystick 2
                     0x29, 0x10, 0x60, 0xEA])          # AND #$10 / RTS (and a spare byte)


def patched_game(disks, irq_ora=True):
    """Every change to the game itself, shared by the tapecart build and the
    EasyFlash one (ultima/ef/build.py): the fixes, the speed patches, the init moved
    out of `game`.  Returns the patched GAME (a PRG with its header, the
    init's room zeroed), the relocated init (for INIT_AT), the patched files
    by (disk, name), and the patched raw sectors by (disk, track, sector):
    T4 S15 with u6exp.s, Rest's T24 S16-17.  irq_ora: the IRQ
    handlers' `LDA #$35` becomes `ORA #$05` (the tapecart's cassette lines);
    the EasyFlash build must keep `LDA #$35`, which hides the cart for the
    handler however $01 stood."""
    game_file, _ok = disks["3B"].file("GAME")
    create_file, _ok = disks["3B"].file("CREATE")
    game_file, create_file = bytearray(game_file), bytearray(create_file)
    # both IRQ handlers bank I/O in with a constant; keep the tape lines
    if irq_ora:
        patch(game_file, 0x1F31, GAME_ADDR, IRQ_WANT, IRQ_NEW, "game IRQ")
        patch(create_file, 0x048C, 0x0200, IRQ_WANT, IRQ_NEW, "create IRQ")
    # Shift-L's "LOAD Game ?" tests the Y/N answer the wrong way round: $3E6C
    # returns carry set for Y, the save prompt above it uses BCC, the load
    # BCS -- so Y did nothing and N reloaded the last save, throwing away
    # everything since (verified in VICE).  Undocumented in the manual; with
    # the branch the right way round, Y loads and N goes back to play.
    patch(game_file, 0x2EF6, GAME_ADDR, bytes([0x20, 0x6C, 0x3E, 0xB0, 0xE5, 0x4C, 0xFC, 0x03]),
          bytes([0x20, 0x6C, 0x3E, 0x90, 0xE5, 0x4C, 0xFC, 0x03]), "load prompt: BCS -> BCC")
    # the IRQ's key queue drops a quick second tap of the same key (u6key.s)
    out = os.path.join(BUILD, "u6key.bin")
    sh("acme", "-f", "plain", "-o", out, os.path.join(HERE, "u6key.s"))
    bits = game_file[0x206D - GAME_ADDR + 2:0x2077 - GAME_ADDR + 2]
    assert [i for i, b in enumerate(bits) if b & 0x10] == [9], "u6key.s: the fire bit moved"
    with open(out, "rb") as fh:
        patch(game_file, 0x1F76, GAME_ADDR, KEY_QUEUE, fh.read(), "the key queue")
    init_blob = relocate_init(game_file)        # first: the speed patches use the room it frees
    apply_fast(game_file, disks["3B"].file("TILES")[0])
    patched = {("3B", "GAME"): game_file, ("3B", "CREATE"): create_file}
    for name in SPLIT_FILES:
        patched[("3B", name)] = steady_split(disks["3B"].file(name)[0], name)
    for name, addr in KEYWAIT.items():
        data = bytearray(patched[("3B", name)])
        patch(data, addr, 0x0200, KEYWAIT_OLD, KEYWAIT_NEW, f"{name}'s key wait")
        patched[("3B", name)] = bytes(data)
    for name, questions in COMPENDIUM.items():
        patched[("2A", name)] = any_answer_is_right(disks["2A"].file(name)[0], questions, name)
    for name in SHRINES:
        data = bytearray(disks["3A"].file(name)[0])
        assert data[-8:] == SHRINE_OLD and data.count(SHRINE_OLD) == 1, \
            f"{name}: the shrine's level table is not where it was"
        data[-8:] = SHRINE_NEW
        patched[("3A", name)] = bytes(data)
    # the shrines' level check: T4's exp() (u6exp.s), in a raw sector
    exp_bin = os.path.join(BUILD, "u6exp.bin")
    sh("acme", "-f", "plain", "-o", exp_bin, os.path.join(HERE, "u6exp.s"))
    with open(exp_bin, "rb") as fh:
        exp_code = fh.read()
    at = EXP_ORG & 0xFF
    assert len(exp_code) <= len(EXP_OLD)
    sectors = {}
    for tag in SECTOR_DISKS:
        sec = bytearray(disks[tag].sector(EXP_TRACK, EXP_SECTOR))
        assert bytes(sec[at:at + len(EXP_OLD)]) == EXP_OLD, f"T4's exp() has moved on {tag}"
        assert (EXP_TRACK, EXP_SECTOR) not in file_sectors(disks[tag])     # (dropped if it were)
        sec[at:at + len(exp_code)] = exp_code
        sectors[(tag, EXP_TRACK, EXP_SECTOR)] = bytes(sec)
    # Rest's two fixes, in raw sectors (REST_FIXES)
    rest = bytearray(b"".join(bytes(disks["1A"].sector(REST_TRACK, s)) for s in REST_SECTORS))
    for addr, want, new in REST_FIXES:
        at = addr - REST_ORG
        assert bytes(rest[at:at + len(want)]) == want, f"Rest: expected {want.hex(' ')} at {addr:#06x}"
        rest[at:at + len(new)] = new
    for tag in SECTOR_DISKS:
        orig = b"".join(bytes(disks[tag].sector(REST_TRACK, s)) for s in REST_SECTORS)
        assert orig == b"".join(bytes(disks["1A"].sector(REST_TRACK, s)) for s in REST_SECTORS), \
            f"the Rest overlay differs on disk {tag}"
        for i, s in enumerate(REST_SECTORS):
            assert (REST_TRACK, s) not in file_sectors(disks[tag])
            if rest[i * 256:(i + 1) * 256] != orig[i * 256:(i + 1) * 256]:
                sectors[(tag, REST_TRACK, s)] = bytes(rest[i * 256:(i + 1) * 256])
    return game_file, init_blob, patched, sectors


def parts():
    disks = {t: D64(disk_path(t)) for t in TAGS}
    pieces, rsym, bulks, packs, bsyms = assemble_drivers()
    game_file, init_blob, patched, fixed_sectors = patched_game(disks)

    flash = Layout(regions.data_base("u6"))
    streams = bytearray()
    stream_at = {}

    def stream(data):
        k = bytes(data)
        if k not in stream_at:
            stream_at[k] = len(streams)
            streams.extend(k)
        return stream_at[k]

    # ---- names --------------------------------------------------------
    entries = []                    # [key, offset in `streams` or None, length, flags, extra]
    starts = {}
    later = {}                      # entries filled in once GAME is placed
    bang = []                       # the `!NAME` entries: (index, name, pages)
    for tag in TAGS:
        d = disks[tag]
        for name, _t, t, s, _b in d.directory():
            data, ok = d.chain(t, s)
            assert ok, (tag, name)
            data = patched.get((tag, name), data)
            if tag == "3B":
                # Raw: the boot driver has no decoder.  "%NAME" (what the
                # resident loader sends; it drops the PRG header) points two
                # bytes into the same data as "/NAME" (whole, as `game`'s
                # loader sends it), so both spellings cost nothing extra.
                if name == "GAME":          # patched with the driver below
                    later["/"] = len(entries)
                    entries.append([key("/GAME"), None, len(data), 0, 0])
                    later["%"] = len(entries)
                    entries.append([key("%GAME"), None, len(data) - 2, 0, 0])
                    continue
                off = stream(data)
                entries.append([key("/" + name), off, len(data), 0, 0])
                entries.append([key("%" + name), off + 2, len(data) - 2, 0, 0])
                continue
            k = "/" + name
            packed = zx.crunch(data)
            if packed is not None and len(packed) < len(data):
                entries.append([key(k), stream(packed), len(packed), F_ZX, 0])
            else:
                entries.append([key(k), stream(data), len(data), 0, 0])
            if tag in SECTOR_DISKS:
                starts[name] = (t, s)
                bang.append((len(entries), name, -(-len(data) // 254)))
                entries.append([key("!" + name), None, 0, 0, t | s << 8])

    # ---- the ending overlay (1A/1B T23 S16-18, at $C800) ------------------
    # It loads `end` with a serial loader of its own at $C8C2, since `end`
    # overwrites `game`'s: replace that with u6end.s, which asks the cart.
    # Everything before it -- the entry, the machine setup, the descriptor
    # chains, the IRQ and NMI -- stays, bar the IRQ's `LDA #$35 / STA $01`.
    end_bin, end_sym = os.path.join(BUILD, "u6end.bin"), os.path.join(BUILD, "u6end.sym")
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", HERE,
       f"-DG_SDIR=${rsym['u6_sdir']:04x}", "-o", end_bin, "-l", end_sym,
       os.path.join(HERE, "u6end.s"))
    with open(end_bin, "rb") as fh:
        end_code = fh.read()
    ending = bytearray(b"".join(bytes(disks["1A"].sector(END_TRACK, s)) for s in END_SECTORS))
    for tag in SECTOR_DISKS:
        assert b"".join(bytes(disks[tag].sector(END_TRACK, s)) for s in END_SECTORS) == ending, \
            f"the ending overlay differs on disk {tag}"
    assert ending[END_LOADER - END_ORG:END_LOADER - END_ORG + 5] == bytes([0xA9, 0x35, 0x85, 0x01, 0x8E]), \
        "the ending overlay's loader has moved"
    irq = ending.find(IRQ_WANT, 0x8A, END_LOADER - END_ORG)
    assert irq == END_IRQ - END_ORG, f"the ending overlay's IRQ bank-in is at {irq:#x}"
    ending[irq:irq + len(IRQ_NEW)] = IRQ_NEW
    ending[END_LOADER - END_ORG:] = end_code.ljust(len(ending) - (END_LOADER - END_ORG), b"\x00")
    assert len(ending) == 3 * 256
    overrides = {(tag, END_TRACK, s): bytes(ending[i * 256:(i + 1) * 256])
                 for tag in SECTOR_DISKS for i, s in enumerate(END_SECTORS)}
    # ---- the shrines' level check (u6exp.s), Rest's fixes -----------------
    for k, data in fixed_sectors.items():
        assert k not in overrides, k
        overrides[k] = data

    # ---- raw sectors behind block maps ----------------------------------
    zero_page = bytes(256)
    pages = [zero_page]
    page_at = {zero_page: 0}
    grids = {}
    for tag, n in SECTOR_DISKS.items():
        d = disks[tag]
        infile = file_sectors(d)
        grid = [None] * (36 * GRID)
        for t in range(1, 36):
            for s in range(SECTORS[t]):
                data = overrides.get((tag, t, s), bytes(d.sector(t, s)))
                if (t, s) in infile:
                    data = zero_page         # read only by name, never like this
                if data not in page_at:
                    page_at[data] = len(pages)
                    pages.append(data)
                grid[t * GRID + s] = (page_at[data], M_LOGGED if (tag, t, s) in LOGGED
                                      else M_BAM if (tag, t, s) in BAMS else 0)
        grids[n] = grid
    page_base = flash.add(b"".join(pages))
    assert page_base % 256 == 0
    reu_slots(entries, bang, len(pages), bsyms["u6reub"][BULK_A])

    stream_base = flash.add(bytes(streams))
    maps = {}
    for n, grid in grids.items():
        table = bytearray()
        for cell in grid:
            if cell is None:
                table += bytes(4)
            else:
                idx, mark = cell
                a = page_base + idx * 256
                table += bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16, mark])
        maps[n] = flash.add(bytes(table))
    pack_at = {org: flash.add(bytes(img)) for org, img in packs.items()}

    def lda3(what, org, label, a):              # lda #lo / lda #mid / lda #hi
        img = bulks[what][org]
        o = bsyms[what][org][label] - org
        assert img[o] == img[o + 5] == img[o + 10] == 0xFF, f"{what}'s {label} placeholders moved"
        img[o], img[o + 5], img[o + 10] = a & 0xFF, (a >> 8) & 0xFF, a >> 16

    for org in packs:
        lda3("u6bulk", org, "b_pfl", pack_at[org])
        lda3("u6reub", org, "b_pfl", pack_at[org])
    bulk_at = {org: flash.add(bytes(img)) for org, img in bulks["u6bulk"].items()}
    reub_at = {org: flash.add(bytes(img)) for org, img in bulks["u6reub"].items()}
    for org in packs:
        lda3("u6reua", org, "b_bfl", reub_at[org])
    reua_at = {org: flash.add(bytes(img)) for org, img in bulks["u6reua"].items()}
    sdir = flash.reserve(len(entries) * (KEYLEN + DATALEN))
    log_lo, log_hi = regions.save_base("u6"), regions.REGIONS["u6"][3]

    def a24(a):
        return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])

    # ---- the in-game resident's tables, then `game` itself ---------------
    fl = bytearray()
    for org in (BULK_B, BULK_A):                  # high byte first, at 0 and 4
        a = bulk_at[org]                          # (u6_bulk)
        fl += bytes([a >> 16, (a >> 8) & 0xFF, a & 0xFF])
        if org == BULK_B:
            fl.append(0xFF)
    n = len(entries)
    tables = {
        "u6_bulkfl": bytes(fl),
        "u6_map_lo": bytes([maps[0] & 0xFF, maps[1] & 0xFF]),
        "u6_map_mid": bytes([(maps[0] >> 8) & 0xFF, (maps[1] >> 8) & 0xFF]),
        "u6_map_hi": bytes([maps[0] >> 16, maps[1] >> 16]),
        "u6_sdir": a24(sdir) + bytes([n & 0xFF, n >> 8]),
        "u6_logdir": a24(log_lo + (log_hi - log_lo) // 2) + b"\x00\x00",  # empty (half 0);
        "u6_logdata": a24(log_lo),                        # the boot driver hands over the real one
    }
    for name, value in tables.items():
        pieces = put(pieces, rsym[name], value)
    game = bytearray(game_file)
    for base, blob in pieces:
        o = base - GAME_ADDR + 2
        game[o:o + len(blob)] = blob
    init_blob = apply_reu(game, init_blob, rsym, page_base, len(pages), reua_at)
    game_at = flash.add(bytes(game))
    init_at = flash.add(init_blob)
    entries[later["/"]][1:3] = [("abs", game_at), len(game)]
    entries[later["%"]][1:3] = [("abs", game_at + 2), len(game) - 2]

    directory = bytearray()
    for k, off, length, flags, extra in entries:
        if isinstance(off, tuple):
            a = off[1]
        elif off is None:
            a = 0
        else:
            a = stream_base + off
        directory += k + a24(a) + bytes([length & 0xFF, length >> 8, flags,
                                         extra & 0xFF, extra >> 8])
    flash.place_at(sdir, bytes(directory))

    # ---- the boot driver, in the resident loader's image -----------------
    boot_bin, boot_sym = os.path.join(BUILD, "u6boot.bin"), os.path.join(BUILD, "u6boot.sym")
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", HERE,
       f"-DG_LOGDIR=${rsym['u6_logdir']:04x}", f"-DG_LOGDATA=${rsym['u6_logdata']:04x}",
       "-o", boot_bin, "-l", boot_sym,
       os.path.join(HERE, "u6boot.s"))
    bsym = symbols(boot_sym)
    with open(boot_bin, "rb") as fh:
        bblob = fh.read()
    b1_end, b2_end = bsym["ub_piece1_end"], bsym["ub_piece2_end"]
    assert b1_end <= 0xC400 and b2_end <= 0xC800
    gap = bblob[b1_end - 0xC16B:0xC578 - 0xC16B]
    assert not any(gap), "boot driver bytes between its pieces"
    piece1 = bytearray(bblob[:b1_end - 0xC16B])
    piece2 = bytearray(bblob[0xC578 - 0xC16B:b2_end - 0xC16B])
    boot_tables = {
        "u6_map_lo": tables["u6_map_lo"], "u6_map_mid": tables["u6_map_mid"],
        "u6_map_hi": tables["u6_map_hi"], "u6_sdir": tables["u6_sdir"],
        "u6_logbase": a24(log_lo), "u6_logtop": a24(log_hi),
        "u6_h0top": a24(log_lo + (log_hi - log_lo) // 2),
        "u6_initsrc": a24(init_at) + bytes([len(init_blob) & 0xFF, len(init_blob) >> 8,
                                            INIT_AT & 0xFF, INIT_AT >> 8]),
    }
    for name, value in boot_tables.items():
        o = bsym[name] - 0xC578
        assert piece2[o:o + len(value)] == b"\xff" * len(value), f"{name} placeholder moved"
        piece2[o:o + len(value)] = value

    u6load, _ok = disks["3B"].file("U6LOAD")
    image = bytearray(u6load[2 + 0x86:][:0x400].ljust(0x400, b"\x00"))
    def boot_patch(addr, want, new, what):
        o = addr - 0xC000
        if bytes(image[o:o + len(want)]) != want:
            raise SystemExit(f"{what}: expected {want.hex(' ')} at {addr:#06x}, found "
                             f"{bytes(image[o:o + len(want)]).hex(' ')}")
        image[o:o + len(new)] = new
    boot_patch(0xC00C, bytes([0x20, 0xE4, 0xC2]), bytes([0xEA] * 3), "drive-code upload")
    ho = bsym["ub_handoff"]
    boot_patch(0xC071, bytes([0x4C, 0x00, 0x02]), bytes([0x4C, ho & 0xFF, ho >> 8]), "start of game")
    boot_patch(0xC135, IRQ_WANT, IRQ_NEW, "resident IRQ")
    boot_patch(0xC16B, bytes([0x8E, 0x47, 0xC2]), bytes([0x8E, 0x47, 0xC2]), "the loader's entry")
    image[0xC16B - 0xC000:0xC16B - 0xC000 + len(piece1)] = piece1
    image[len(image):] = b""

    # ---- the init segment: find the log, compact it, then the cold start --
    with open(os.path.join(BUILD, "u6boot_syms.inc"), "w") as fh:
        for name, addr in sorted(bsym.items()):
            if name.startswith(("u6_", "tc_", "ub_", "b_")):
                fh.write(f"{name} = ${addr:04x}\n")
    init_bin = os.path.join(BUILD, "init_u6.bin")
    sh("acme", "-f", "plain", "-I", paths.ASM, "-I", HERE, "-I", BUILD,
       f"-DLOG_LO=${log_lo:x}", f"-DLOG_HI=${log_hi:x}", "-o", init_bin,
       "-l", os.path.join(BUILD, "init_u6.sym"), os.path.join(paths.ASM, "init_u6.s"))
    with open(init_bin, "rb") as fh:
        init = fh.read()
    assert INIT_ADDR + len(init) <= 0x2000, len(init)     # buffers from $2000

    segments = [(flash.add(bytes(image)), len(image), 0xC000),
                (flash.add(bytes(piece2)), len(piece2), 0xC578),
                (flash.add(init), len(init), INIT_ADDR)]
    desc = bytearray([INIT_ADDR & 0xFF, INIT_ADDR >> 8, len(segments)])
    for offset, length, dest in segments:
        desc += bytes([(offset >> 8) & 0xFF, (offset >> 16) & 0xFF,
                       length & 0xFF, length >> 8, dest & 0xFF, dest >> 8, 0])

    regions.check("u6", flash.cursor, log_hi)
    # the Avatar from Ultima IV or V: the page pokes it into init_u6.s
    isym = symbols(os.path.join(BUILD, "init_u6.sym"))
    assert [isym[k] - isym["xf_lvl"] for k in ("xf_str", "xf_dex", "xf_int", "xf_hp",
                                               "xf_mp", "xf_xp")] == [1, 2, 3, 4, 5, 6]
    page = dict(U6_LO=log_lo, U6_MID=log_lo + (log_hi - log_lo) // 2, U6_HI=log_hi,
                U6_SDIR=sdir, U6_SCOUNT=n, U6_XF=isym["xf_lvl"])
    # export/import of the world: the two disks, told apart by the BAM's ID as
    # the game does ($289C), and what page_u6x.s needs to do the rest
    xf = [xfer.Disk(XFER_LABELS[tag], disks[tag].sector(18, 0), [], check_id=True)
          for tag in SECTOR_DISKS]
    save_area = [page_base + grids[0][6 * GRID + s][0] * 256 for s in range(9, 21)]
    world = xfer_world(disks, starts)
    # Journey onward (the launcher): the cold start's `LDA #$00 / BNE $C036`
    # at $C023 (the operand, $C024, is set when a key was pressed: character
    # creation) falls through to the opening.  BEQ $C054 instead: straight
    # into the $C006 entry -- load `game` and its assets, which reads the
    # saved game -- after the machine setup and the music, as the opening's
    # own way in through `create` ends.
    assert bytes(image[0x23:0x27]) == bytes([0xA9, 0x00, 0xD0, 0x0F]), "U6 cold start $C023"
    assert bytes(image[0x54:0x57]) == bytes([0x20, 0x74, 0xC0]), "U6 $C054"
    journey = [(0xC025, 0xF0), (0xC026, 0xC054 - 0xC027)]
    return dict(name="ULTIMA VI", blobs=list(flash.blobs), flash_cursor=flash.cursor, page=page,
                desc=bytes(desc), save_end=log_hi, used=flash.used, cursor=flash.cursor,
                boot_image=bytes(image), boot_piece2=bytes(piece2), bsym=bsym, init=init,
                game=bytes(game[2:]), init_copy=bytes(init_blob), pieces=pieces, rsym=rsym, bulk_at=bulk_at, pack_at=pack_at,
                reua_at=reua_at, reub_at=reub_at, bulks=bulks, bulk_syms=bsyms,
                maps=maps, sdir=sdir, entries=n, ending=bytes(ending), end_sym=symbols(end_sym), log=(log_lo, log_hi),
                streams=len(streams), pages=len(pages), starts=starts, disks=disks,
                page_base=page_base, xfer=xf, u6x=dict(save=save_area, world=world),
                journey=journey)


if __name__ == "__main__":
    p = parts()
    print(f"U6: {p['entries']} directory entries, {p['streams'] / 1024:.1f} KiB of streams, "
          f"{p['pages']} raw pages ({p['pages'] / 4:.1f} KiB), data up to {p['flash_cursor']:#08x}")
    print(f"  log {p['log'][0]:#08x}-{p['log'][1]:#08x}, bulk at "
          + ", ".join(f"{o:#06x}->{a:#08x}" for o, a in p["bulk_at"].items()))
