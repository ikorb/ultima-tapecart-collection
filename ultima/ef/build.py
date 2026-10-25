#!/usr/bin/env python3
"""Build Ultima VI for a 1 MiB EasyFlash: build/ultima6-ef.crt.

A side quest beside the tapecart collection (ultima/games/u6/), never a replacement:
the game's own changes -- the fixes, the speed patches, the init moved out of
`game` -- come from ultima/games/u6/build.py's patched_game(), so both builds carry
the same game; what differs is the storage and the drivers (ef/*.s).

    python -m ultima.ef.build [out.crt]       EF_JOURNEY=1: straight into Journey
                                              Onward, past the launcher

The flash map is ultima/ef/efregions.py.  The data is stored as the tapecart build
stores it, but raw wherever the flash allows: the Game disk's files, the
chunk files, the raw sector pages; only the conversations are zx02 (all raw
would be ~812 KiB, more than the 752 below the log).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths
BUILD = os.path.join(paths.BUILD, "ef")

from ultima.disks.d64 import D64                         # noqa: E402
from ultima.flash import zx                                   # noqa: E402
from ultima.ef import efregions as R                       # noqa: E402
from ultima.ef import efcrt                                # noqa: E402
from ultima.launcher import xfer                                 # noqa: E402
from ultima.launcher import launcher                             # noqa: E402
from ultima.flash import regions                              # noqa: E402  (the tapecart's)

from ultima.games.u6 import build as u6                     # noqa: E402
from ultima.games.u5 import build as u5                     # noqa: E402

# EasyFlash's EAPI for the AM29F040, from the eapi submodule (gitlab.com/easyflash/eapi)
EAPI_SRC = os.path.join(paths.EXTERNAL, "eapi", "eapi-am29f040.s")

CART_NAME = "Ultima VI"
KEYLEN, DATALEN = 12, 8
F_ZX, F_LINKS = 0x01, 0x02
INIT_ADDR = 0x1000
TCX_ORG = 0x9000                # the tapecart's tclib in the launcher's RAM (eftc.s)
EL_SLOT = 0xC000                # EAPI's, above it (efpage.s)
U5L_ORG = 0xC300                # efu5.s, after EAPI's slot
SEGBUF = 0x0800                 # where efu5.s reads U5's segments: the transfer buffers'
                                # (efpage.s BUF), all RAM, below every segment but the stub


def sh(*args):
    subprocess.run(args, check=True)


def symbols(path):
    with open(path) as fh:
        text = fh.read()
    return {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", text, re.M)}


def asm(src, name, defines=None, extra_inc=()):
    """Assemble ef/<src> into build/ef/<name>.bin/.sym; returns (blob, symbols)."""
    os.makedirs(BUILD, exist_ok=True)
    out, sym = os.path.join(BUILD, name + ".bin"), os.path.join(BUILD, name + ".sym")
    args = ["acme", "-f", "plain", "-I", HERE, "-I", paths.ASM, "-I", BUILD]
    for k, v in (defines or {}).items():
        args.append(f"-D{k}=${v:x}" if isinstance(v, int) else f"-D{k}={v}")
    src_path = os.path.join(HERE, src)
    if extra_inc:                               # a wrapper: the context's symbols first
        wrap = os.path.join(BUILD, name + "_wrap.s")
        with open(wrap, "w") as fh:
            for inc in extra_inc:
                fh.write(f'!source "{inc}"\n')
            fh.write(f'!source "{src_path}"\n')
        src_path = wrap
    sh(*args, "-o", out, "-l", sym, src_path)
    with open(out, "rb") as fh:
        return fh.read(), symbols(sym)


def spans(blob, syms, origin, parts):
    """[(address, bytes)] of a multi-segment acme blob, by (start, end symbol)."""
    out = []
    for start, end in parts:
        a = start if isinstance(start, int) else syms[start]
        b = syms[end]
        out.append((a, blob[a - origin:b - origin]))
    return out


def context_inc(syms, name):
    """The context's RAM primitives and variables, for efdrv.s."""
    path = os.path.join(BUILD, name)
    with open(path, "w") as fh:
        for k, v in sorted(syms.items()):
            if k.startswith(("k_", "e_", "d_", "zx_")):
                fh.write(f"{k} = ${v:04x}\n")
    return path


def key(text):
    raw = text if isinstance(text, bytes) else text.encode("latin1")
    assert len(raw) <= KEYLEN, raw
    return raw.ljust(KEYLEN, b"\x00")


def a24(a):
    return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])


class Flash:
    """1 MiB in lhlh order; data allocated upward from DATA_LO."""

    def __init__(self):
        self.mem = bytearray(b"\xff" * R.FLASH_SIZE)
        self.cursor = R.DATA_LO

    def put(self, addr, data):
        assert 0 <= addr and addr + len(data) <= R.FLASH_SIZE
        self.mem[addr:addr + len(data)] = data

    def add(self, data, align=1):
        self.cursor = (self.cursor + align - 1) // align * align
        at = self.cursor
        assert at + len(data) <= R.LOG_LO, f"the data runs into the log at {at + len(data):#x}"
        self.put(at, data)
        self.cursor += len(data)
        return at


def eapi_image():
    """EasyFlash's EAPI for the AM29F040 (what VICE emulates; EasyProg puts the
    cart's own in its place when it flashes the image), without its load
    address, padded to the reserved 768 bytes."""
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "eapi-am29f040.prg")
    sh("acme", "-I", os.path.dirname(EAPI_SRC), "-o", out, EAPI_SRC)
    with open(out, "rb") as fh:
        data = fh.read()[2:]
    assert data[:4] == b"eapi" or data[:4] == bytes([0x65, 0x61, 0x70, 0x69]), data[:4]
    assert len(data) <= R.EAPI_SIZE
    return data.ljust(R.EAPI_SIZE, b"\xff")


def build(journey=False):
    disks = {t: D64(u6.disk_path(t)) for t in u6.TAGS}
    game_file, init_blob, patched, fixed_sectors = u6.patched_game(disks, irq_ora=False)
    init_blob += u6.INIT_TAIL                   # it ends in a JMP to here: on into the main loop
    flash = Flash()

    # ---- the in-game resident, into `game` --------------------------------
    rblob, rsym = asm("efres.s", "efres", dict(DRVBANK=R.GAME_DRV_BANK, EAPI_SLOT=R.GAME_SLOT))
    rorigin = 0x132E
    rparts = spans(rblob, rsym, rorigin, [(0x2823, "piece_a_end"), (0x2989, "piece_b_end"),
                                         (0x132E, "room_end")])
    game = bytearray(game_file)
    for addr, data in rparts:
        off = addr - u6.GAME_ADDR + 2
        if addr == 0x132E:                      # the init's room: free in patched_game's GAME
            assert not any(game[off:off + len(data)]), "the init's room at $132E is not free"
        game[off:off + len(data)] = data
    assert game[0x29B6 - u6.GAME_ADDR + 2] == 0x60, "$29B6 is no longer an RTS"
    patched[("3B", "GAME")] = bytes(game)

    # ---- names: the Game disk raw, conversations zx02, chunk files raw -----
    entries = []                    # [key, address, length, flags, extra]
    placed = {}                     # (tag, name) -> address of the whole file
    starts = {}
    for tag in u6.TAGS:
        d = disks[tag]
        for name, _t, t, s, _b in d.directory():
            data, ok = d.chain(t, s)
            assert ok, (tag, name)
            data = patched.get((tag, name), data)
            if tag == "3B":
                at = flash.add(data)
                placed[(tag, name)] = at
                entries.append([key("/" + name), at, len(data), 0, 0])
                entries.append([key("%" + name), at + 2, len(data) - 2, 0, 0])
                continue
            if tag in u6.SECTOR_DISKS:          # chunk files: raw, so a save can compare
                at = flash.add(data)
                entries.append([key("/" + name), at, len(data), 0, 0])
                starts[name] = (t, s)
                entries.append([key("!" + name), 0, 0, 0, t | s << 8])
                continue
            packed = zx.crunch(data)
            if packed is not None and len(packed) < len(data):
                entries.append([key("/" + name), flash.add(packed), len(packed), F_ZX, 0])
            else:
                entries.append([key("/" + name), flash.add(data), len(data), 0, 0])
    init_src = flash.add(init_blob)

    # ---- the ending overlay: efend.s for its own loader -------------------
    eblob, esym = asm("efend.s", "efend")
    ending = bytearray(b"".join(bytes(disks["1A"].sector(u6.END_TRACK, s)) for s in u6.END_SECTORS))
    for tag in u6.SECTOR_DISKS:
        assert b"".join(bytes(disks[tag].sector(u6.END_TRACK, s)) for s in u6.END_SECTORS) == ending, \
            f"the ending overlay differs on disk {tag}"
    lo = u6.END_LOADER - u6.END_ORG
    assert ending[lo:lo + 5] == bytes([0xA9, 0x35, 0x85, 0x01, 0x8E]), "the ending overlay's loader has moved"
    table = bytearray()
    for name in ("THEME2", "ICHARS", "END"):
        at = placed[("3B", name)]
        size = len(patched.get(("3B", name), disks["3B"].file(name)[0]))
        table += key("%" + name) + a24(at + 2) + bytes([(size - 2) & 0xFF, (size - 2) >> 8])
    eblob = bytearray(eblob)
    t = esym["e_files"] - u6.END_LOADER
    assert eblob[t:t + len(table)] == b"\xff" * len(table)
    eblob[t:t + len(table)] = table
    assert len(eblob) <= len(ending) - lo
    ending[lo:] = bytes(eblob).ljust(len(ending) - lo, b"\x00")
    overrides = {(tag, u6.END_TRACK, s): bytes(ending[i * 256:(i + 1) * 256])
                 for tag in u6.SECTOR_DISKS for i, s in enumerate(u6.END_SECTORS)}
    for k, data in fixed_sectors.items():
        assert k not in overrides, k
        overrides[k] = data

    # ---- raw sectors behind block maps (as the tapecart build) ------------
    zero_page = bytes(256)
    pages = [zero_page]
    page_at = {zero_page: 0}
    grids = {}
    for tag, n in u6.SECTOR_DISKS.items():
        d = disks[tag]
        infile = u6.file_sectors(d)
        grid = [None] * (36 * u6.GRID)
        for t in range(1, 36):
            for s in range(u6.SECTORS[t]):
                data = overrides.get((tag, t, s), bytes(d.sector(t, s)))
                if (t, s) in infile:
                    data = zero_page
                if data not in page_at:
                    page_at[data] = len(pages)
                    pages.append(data)
                grid[t * u6.GRID + s] = (page_at[data], u6.M_LOGGED if (tag, t, s) in u6.LOGGED
                                         else u6.M_BAM if (tag, t, s) in u6.BAMS else 0)
        grids[n] = grid
    page_base = flash.add(b"".join(pages), align=256)
    maps = {}
    for n, grid in grids.items():
        tab = bytearray()
        for cell in grid:
            if cell is None:
                tab += bytes(4)
            else:
                idx, mark = cell
                tab += a24(page_base + idx * 256) + bytes([mark])
        maps[n] = flash.add(bytes(tab))

    # ---- the static directory, sorted, in both driver banks' ROMH -----------
    entries.sort(key=lambda e: e[0])
    keys = [e[0] for e in entries]
    assert len(set(keys)) == len(keys), "a key twice in the directory"
    sdir = b"".join(k + a24(a) + bytes([n & 0xFF, n >> 8, f, x & 0xFF, x >> 8])
                    for k, a, n, f, x in entries)
    assert len(sdir) <= R.SDIR_MAX, f"the directory is {len(sdir)} bytes"
    for bank in (R.GAME_DRV_BANK, R.BOOT_DRV_BANK):
        flash.put(R.lin(bank, 1), sdir)

    # ---- the drivers ----------------------------------------------------------
    common = dict(DRVBANK=0, MAP0=maps[0], MAP1=maps[1], SDIR=R.SDIR_CPU, SCOUNT=len(entries),
                  EAPI_LIN=R.EAPI_LIN, LOG_LO=R.LOG_LO, LOG_MID=R.LOG_MID, LOG_HI=R.LOG_HI)
    tiles = placed[("3B", "TILES")] + 2                 # $6000
    gdrv, gsym = asm("efdrv.s", "efdrv_game",
                     dict(common, EF_GAME=1, DRVBANK=R.GAME_DRV_BANK, EAPI_SLOT=R.GAME_SLOT,
                          SLOT_SRC=tiles + R.GAME_SLOT - 0x6000),
                     [context_inc(rsym, "efctx_game.inc")])
    flash.put(R.lin(R.GAME_DRV_BANK), gdrv)

    bblob, bsym = asm("efboot.s", "efboot", dict(DRVBANK=R.BOOT_DRV_BANK, EAPI_SLOT=R.BOOT_SLOT,
                                                  INIT_AT=u6.INIT_AT))
    boot1, boot2 = spans(bblob, bsym, 0xC16B, [(0xC16B, "ub_piece1_end"), (0xC578, "ub_piece2_end")])
    create = placed[("3B", "CREATE")] + 2               # $0200
    bdrv, bdsym = asm("efdrv.s", "efdrv_boot",
                      dict(common, EF_BOOT=1, DRVBANK=R.BOOT_DRV_BANK, EAPI_SLOT=R.BOOT_SLOT,
                           SLOT_SRC=create + R.BOOT_SLOT - 0x0200,
                           INIT_SRC=init_src, INIT_LEN=len(init_blob), INIT_AT=u6.INIT_AT),
                      [context_inc(bsym, "efctx_boot.inc")])
    flash.put(R.lin(R.BOOT_DRV_BANK), bdrv)

    # ---- the boot resident: u6load's $C000 image, patched ------------------
    u6load, _ok = disks["3B"].file("U6LOAD")
    image = bytearray(u6load[2 + 0x86:][:0x400].ljust(0x400, b"\x00"))

    def boot_patch(addr, want, new, what):
        o = addr - 0xC000
        if bytes(image[o:o + len(want)]) != want:
            raise SystemExit(f"{what}: expected {want.hex(' ')} at {addr:#06x}, found "
                             f"{bytes(image[o:o + len(want)]).hex(' ')}")
        image[o:o + len(new)] = new
    boot_patch(0xC00C, bytes([0x20, 0xE4, 0xC2]), bytes([0xEA] * 3), "drive-code upload")
    uj = bsym["ub_journey"]
    boot_patch(0xC054, bytes([0x20, 0x74, 0xC0]), bytes([0x20, uj & 0xFF, uj >> 8]), "Journey onward's setup")
    ho = bsym["ub_handoff"]
    boot_patch(0xC071, bytes([0x4C, 0x00, 0x02]), bytes([0x4C, ho & 0xFF, ho >> 8]), "start of game")
    boot_patch(0xC135, u6.IRQ_WANT, u6.IRQ_WANT, "the resident IRQ's bank-in (kept)")
    image[0xC16B - 0xC000:0xC16B - 0xC000 + len(boot1[1])] = boot1[1]
    assert bytes(image[0x23:0x27]) == bytes([0xA9, 0x00, 0xD0, 0x0F]), "U6 cold start $C023"
    segs = [(flash.add(bytes(image)), len(image), 0xC000),
            (flash.add(boot2[1]), len(boot2[1]), 0xC578)]

    # ---- bank 0: the boot's init, the start code, the stub, EAPI, the name --
    pokes = [(0xC025, 0xF0), (0xC026, 0xC054 - 0xC027)] if journey else []
    iblob, isym = asm("efinit.s", "efinit", dict(LOG_LO=R.LOG_LO, LOG_MID=R.LOG_MID, LOG_HI=R.LOG_HI,
                                                  SEGN=len(segs)))
    iblob = bytearray(iblob)
    o = isym["segs"] - INIT_ADDR
    row = b"".join(a24(a) + bytes([n & 0xFF, n >> 8, d & 0xFF, d >> 8]) for a, n, d in segs)
    assert iblob[o:o + len(row)] == b"\xff" * len(row)
    iblob[o:o + len(row)] = row
    o = isym["pokes"] - INIT_ADDR
    iblob[o] = 3 * len(pokes)
    for i, (a, v) in enumerate(pokes):
        iblob[o + 1 + 3 * i:o + 4 + 3 * i] = bytes([a & 0xFF, a >> 8, v])
    assert INIT_ADDR + len(iblob) <= 0x3000, "efinit runs into its buffer"
    init_lin = flash.add(bytes(iblob))

    # ---- the launcher (efpage.s): the tapecart page's U6 transfer code ------
    xf = [xfer.Disk(u6.XFER_LABELS[tag], disks[tag].sector(18, 0), [], check_id=True)
          for tag in u6.SECTOR_DISKS]
    world = u6.xfer_world(disks, starts)
    save_area = [page_base + grids[0][6 * u6.GRID + sec][0] * 256 for sec in range(9, 21)]
    # its font: the intro's and the ending's text-box font (3B ICHARS, in ASCII
    # order and inverted -- the box's paper is the set bits), arranged as the
    # tapecart launcher arranges Ultima I's
    ichars = disks["3B"].file("ICHARS")[0][2:]
    assert len(ichars) == 0x800
    font_lin = flash.add(launcher.font(bytes(b ^ 0xFF for b in ichars[:0x400]), own_slash=False))
    # the tapecart's tclib, read in when an export or import picks the
    # tapecart, and where that cart keeps Ultima VI's log: its save region,
    # pinned (regions.py), whose layout its settings page stamps
    tblob, tsym = asm("eftc.s", "eftc", dict(TCX_ORG=TCX_ORG))
    assert TCX_ORG + len(tblob) <= EL_SLOT, "the tapecart's tclib runs into EAPI's slot"
    tcx_lin = flash.add(tblob)
    # Ultima V from the tapecart, with its music from here: only when its
    # disks are there too (a build for Ultima VI alone leaves the 5 out)
    ux = u5_part(flash, tsym) if u5_disks() else None
    tp_lo, tp_hi = regions.save_base("u6"), regions.REGIONS["u6"][3]
    page_data(dict(FONT_SRC=font_lin, U6_LO=R.LOG_LO, U6_MID=R.LOG_MID, U6_HI=R.LOG_HI,
                   U6_SDIR=R.lin(R.GAME_DRV_BANK, 1), U6_SCOUNT=len(entries),
                   EFI_SRC=init_lin, EFI_LEN=len(iblob), EFI_POKES=isym["pokes"],
                   EAPI_LIN=R.EAPI_LIN, LOG_LO=R.LOG_LO, LOG_HI=R.LOG_HI,
                   TCX_SRC=tcx_lin, TCX_LEN=len(tblob), TCX_PARM=tsym["tc_addr"],
                   TP_LO=tp_lo, TP_MID=tp_lo + (tp_hi - tp_lo) // 2, TP_HI=tp_hi,
                   TP_SETTINGS=regions.SETTINGS, TP_SET_LAYOUT=regions.SET_LAYOUT,
                   TP_LAYOUT=regions.LAYOUT,
                   **(dict(U5L_SRC=ux["lin"], U5L_LEN=len(ux["blob"]), U5L_ORG=U5L_ORG) if ux else {})),
              xf, world, save_area)
    lblob, lsym = asm("efpage.s", "efpage", dict(TCX_ORG=TCX_ORG))
    assert len(lblob) <= R.LAUNCH_MAX, f"the launcher is {len(lblob) - R.LAUNCH_MAX} bytes over"
    flash.put(R.LAUNCH_LIN, lblob)
    sblob, _ = asm("efstart.s", "efstart", dict(LAUNCH_IMG=R.cpu_of(R.LAUNCH_LIN),
                                                 LAUNCH_PAGES=(len(lblob) + 255) // 256,
                                                 LAUNCH_ORG=lsym["PAGE_ORG"]))
    flash.put(R.lin(0), sblob)
    stub, _ = asm("efstub.s", "efstub")
    assert len(stub) == 0x10000 - R.STUB_CPU
    flash.put(R.STUB_LIN, stub)
    flash.put(R.EAPI_LIN, eapi_image())
    flash.put(R.NAME_LIN, b"ef-nAME:" + CART_NAME.swapcase().encode("ascii").ljust(16, b"\x00"))

    return dict(flash=flash.mem, cursor=flash.cursor, entries=entries, maps=maps, page_base=page_base,
                pages=len(pages), init_src=init_src, segs=segs, rsym=rsym, bsym=bsym, gsym=gsym,
                bdsym=bdsym, game=bytes(game[2:]), boot_image=bytes(image), boot_piece2=boot2[1],
                init=bytes(iblob), init_lin=init_lin, launcher=bytes(lblob), lsym=lsym,
                tcx=bytes(tblob), tsym=tsym, tcx_lin=tcx_lin, tp_log=(tp_lo, tp_hi),
                ending=bytes(ending), esym=esym, placed=placed, starts=starts,
                disks=disks, tiles=tiles, create=create, patched=patched, u5=ux)


def u5_disks():
    return all(os.path.exists(paths.disk("u5-" + tag.lower())) for tag in u5.TAGS.values())


def u5_part(flash, tsym):
    """Ultima V's part (efu5.s, ultima/games/u5/build.py build_efmusic): the
    music's bank, a bank with the boot segments as the tapecart holds them
    and the patches, and the launcher's code that uses them."""
    bank = -(-flash.cursor // R.BANK)
    saved = u5.BUILD
    u5.BUILD = os.path.join(BUILD, "u5")    # (a cart build running beside this
    os.makedirs(u5.BUILD, exist_ok=True)    # one writes build/'s own)
    try:
        p = u5.parts()
        e = u5.build_efmusic(p, bank)
    finally:
        u5.BUILD = saved
    at = flash.add(e["image"], align=R.BANK)
    assert at == R.lin(bank), (hex(at), bank)

    # the segments back to back, then the patches: count, address, bytes
    segs = b"".join(data for _a, _n, _d, data in e["segs"])
    plist = b"".join(bytes([len(new), addr & 0xFF, addr >> 8]) + new
                     for addr, _old, new in e["patches"]) + b"\x00"
    assert all(0 < len(new) < 256 for _a, _o, new in e["patches"])
    assert all(n > 0 for _a, n, _d, _data in e["segs"]), "efu5.s copies no empty segment"
    copy_at = flash.add(segs + plist, align=R.BANK)
    assert (copy_at & (R.BANK - 1)) + len(segs) + len(plist) <= R.BANK
    assert all(SEGBUF + len(segs) <= dest or dest + n <= SEGBUF for _a, n, dest, _d in e["segs"]), \
        "efu5.s's buffer overlaps a segment's place"
    assert 0x0800 <= SEGBUF and SEGBUF + len(segs) <= 0x3000, "efu5.s's buffer is not BUF"

    rows = [("r_set", regions.SETTINGS, e["opt_at"] + 1, SEGBUF),
            ("r_desc", e["desc_at"], len(e["desc"]), SEGBUF),
            ("r_jn", e["journal"], 2, SEGBUF)]
    copies, off = [], 0
    for i, (a, n, dest, data) in enumerate(e["segs"]):
        rows.append(("r_segs" if i == 0 else None, a, n, SEGBUF + off))
        copies.append((SEGBUF + off, n, dest))
        off += n
    hexes = lambda b: ", ".join(f"${x:02x}" for x in b)
    lines = ["; generated by ultima/ef/build.py -- do not edit",
             "desc: !byte " + hexes(e["desc"]), "desc_end:", "rows:"]
    for label, a, n, dest in rows:
        lines.append((f"{label}: " if label else "") + "!byte " +
                     hexes(a24(a) + bytes([n & 0xFF, n >> 8, dest & 0xFF, dest >> 8])))
    lines += ["r_segs_end:", "copies:"]
    lines += ["!byte " + hexes(bytes([s & 0xFF, s >> 8, n & 0xFF, n >> 8, d & 0xFF, d >> 8]))
              for s, n, d in copies]
    lines.append("copies_end:")
    with open(os.path.join(BUILD, "efu5_data.s"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    blob, sym = asm("efu5.s", "efu5", dict(
        U5L_ORG=U5L_ORG, TCX_ORG=TCX_ORG, TCX_PARM=tsym["tc_addr"], SEGBUF=SEGBUF,
        U5_BANK=bank, COPY_BANK=R.bank_of(copy_at), COPY_ROM=R.cpu_of(copy_at),
        PATCH_ROM=R.cpu_of(copy_at) + len(segs), SEG_TOTAL=len(segs),
        OPT_AT=e["opt_at"], CAPS=e["caps"], PT_OPTS=e["pt_opts"], ENTRY=u5.INIT_ADDR))
    assert sym["r_segs_end"] + 6 - sym["rows"] < 256 and sym["copies_end"] - sym["copies"] < 256
    assert EL_SLOT + R.EAPI_SIZE <= U5L_ORG and U5L_ORG + len(blob) <= 0xD000
    return dict(e, blob=blob, sym=sym, lin=flash.add(blob), bank=bank, copy_at=copy_at,
                seg_bytes=segs, plist=plist, p=p)


def page_data(syms, disks, world, save_area):
    """build/ef/efpage_data.s: what launcher.py's page_data.s gives the
    transfer code, for Ultima VI alone; the other games' symbols are stubs."""
    def blist(b):
        return "\n".join("        !byte " + ", ".join(f"${x:02x}" for x in b[i:i + 16])
                         for i in range(0, len(b), 16)) or "        !byte 0"
    lines = ["; generated by ultima/ef/build.py -- do not edit"]
    lines += [f"{k} = ${v:x}" for k, v in sorted(syms.items())]
    lines += ["U4_ZP = 0", "C128_BLOCKS = 0", "C128_DATA = 0", "C128_LEN = 0", "C128_LOAD = 0"]
    lines += ["xf_u6:", blist(xfer.table(disks))]
    lines += ["xf_lo: !byte 0, 0, 0, 0, 0, <xf_u6", "xf_hi: !byte 0, 0, 0, 0, 0, >xf_u6"]
    lines += ["u6x_save:", blist(b"".join(a24(a) for a in save_area))]
    for i, w in enumerate(world):
        assert len(w["pool"]) < 256
        lines += [f"u6x_files_{i}:", blist(b"".join(n.encode("latin1") + bytes([t, s]) for n, t, s in w["files"]))]
        lines += [f"u6x_pool_{i}:", blist(b"".join(bytes(ts) for ts in w["pool"]))]
        lines += [f"u6x_bam_{i}:", blist(w["bam"])]
    lines += ["u6x_nfiles: " + blist(bytes(len(w["files"]) for w in world)).strip()]
    lines += ["u6x_npool: " + blist(bytes(len(w["pool"]) for w in world)).strip()]
    for k in ("files", "pool", "bam"):
        n = len(world)
        lines += [f"u6x_{k}_lo: !byte " + ", ".join(f"<u6x_{k}_{i}" for i in range(n)),
                  f"u6x_{k}_hi: !byte " + ", ".join(f">u6x_{k}_{i}" for i in range(n))]
    lines += ['x_magic: !text "UCSV"']
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "efpage_data.s"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(paths.BUILD, "ultima6-ef.crt")
    p = build(journey=os.environ.get("EF_JOURNEY") == "1")
    chips = efcrt.write(out, p["flash"], CART_NAME, skip_banks=R.LOG_BANKS)
    used = p["cursor"] - R.DATA_LO
    print(f"U6 EasyFlash: {len(p['entries'])} directory entries, {p['pages']} raw pages, "
          f"data {used / 1024:.0f} KiB (to {p['cursor']:#07x}, {(R.LOG_LO - p['cursor']) / 1024:.0f} KiB free "
          f"below the log), {chips} chips -> {out}")
    u = p["u5"]
    print(f"  Ultima V from the tapecart (5): music in bank {u['bank']} ({len(u['image'])} bytes), "
          f"its segments and patches in bank {R.bank_of(u['copy_at'])}, the launcher's part "
          f"{len(u['blob'])} bytes" if u else "  no Ultima V disks: no 5 on the launcher")


if __name__ == "__main__":
    main()
