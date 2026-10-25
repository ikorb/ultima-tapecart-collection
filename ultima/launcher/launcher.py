#!/usr/bin/env python3
"""The launcher's per-game page (asm/page.s): its data, and its flash.

ultima/build.py calls build() once every game is built.  What the page needs to
know about a game comes from that game's build, never from here:

  p["page"]     the flash addresses its info routine reads (slot bases)
  p["options"]  optional: {"caps": CAP_* bits the driver implements,
                           "addr": the driver's options byte in C64 RAM}

and the reset tables come from the fresh image itself: every erase block of
the game's save region (less the launcher's settings block), and every
non-erased page a fresh build puts there, as runs of pages zx02-crunched into
the launcher's region.  So a reset writes back exactly what a newly flashed
cart holds -- including a U6 log that is all $FF, which is no runs at all.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from ultima.launcher import logo
from ultima.flash import regions
from ultima.launcher import xfer
from ultima.flash import zx
from ultima.flash.layout import Layout

from ultima import paths

BUILD = paths.BUILD

PAGE_ORG = 0x5000               # the page, right after the font ...
FONT_ORG = 0x4800               # ... which the menu's PRG starts with
MENU_ORG = 0x8700               # and the menu (asm/menu.s) ends it
BUF_PAGES = 0x38                # asm/page.s decodes a run into $0800-$3FFF
XDATA_END = 0xA000              # the page's export tables end here (menu.s
                                # ends below them: ultima/build.py checks), and
                                # the page's second piece starts (page.s
                                # page_hi, under BASIC's ROM, which the menu
                                # banks out while the page runs)

CAP_FOOD, CAP_PASS, CAP_TILES = 0x01, 0x02, 0x08

# descriptor index order (regions.DESC_INDEX): the page's tables use it
ORDER = sorted(regions.DESC_INDEX, key=regions.DESC_INDEX.get)


def font(lo, extra=None, own_slash=True):
    """The launcher's character set: Ultima I's text font -- the first 1 KiB of
    LO, in ASCII order -- rearranged into the C64's lower-case character set
    order, so CHROUT's mixed-case PETSCII shows as it should: screen codes
    $01-$1A lower case, $41-$5A capitals, $20-$3F as ASCII; $80-$FF the
    reverse of $00-$7F, where the logo's characters go over them (the
    launcher prints no reverse text).  Screen codes with no text glyph in U1's font are
    blank.  U1's '/' is a game symbol, so it gets one drawn to match (the
    launcher prints "60/60", "(Y/N)", "RUN/STOP"); its '<', '>' and '_' are
    too, and the launcher's texts avoid them.)  own_slash=False keeps the
    source font's own '/' (the EasyFlash launcher's, from Ultima VI's ICHARS)."""
    own = {0x2F: bytes([0x00, 0x06, 0x06, 0x0C, 0x18, 0x30, 0x60, 0x60])} if own_slash else {}
    glyph = lambda c: own.get(c) or bytes(lo[c * 8:c * 8 + 8])
    out = bytearray(2048)
    for sc in range(128):
        if sc == 0:
            src = 0x40
        elif sc <= 0x1A:
            src = 0x60 + sc                 # a-z
        elif sc <= 0x1F:
            src = 0x40 + sc                 # [ \ ] ^ _
        elif sc <= 0x3F:
            src = sc
        elif 0x41 <= sc <= 0x5A:
            src = sc                        # A-Z
        else:
            continue
        out[sc * 8:sc * 8 + 8] = glyph(src)
        out[(sc + 128) * 8:(sc + 129) * 8] = bytes(b ^ 0xFF for b in glyph(src))
    for sc, g in (extra or {}).items():     # the logo's (logo.py)
        out[sc * 8:sc * 8 + 8] = g
    return bytes(out)


def display(text):
    """Mixed-case text as the launcher shows it, in PETSCII for the
    lower-case character set: a-z $41-$5A, A-Z $C1-$DA."""
    out = bytearray()
    for ch in text:
        c = ord(ch)
        out.append(c - 0x20 if 0x61 <= c <= 0x7A else c + 0x80 if 0x41 <= c <= 0x5A else c)
    return bytes(out)


def runs_of(fresh, lo, hi):
    """[(flash address, bytes)]: the non-erased pages of fresh[lo:hi], as
    runs of consecutive pages, none longer than the page's buffer."""
    out, cur, start = [], bytearray(), None
    for a in range(lo, hi, regions.PAGE):
        pg = fresh[a:a + regions.PAGE]
        if pg == b"\xff" * regions.PAGE or len(cur) == BUF_PAGES * regions.PAGE:
            if cur:
                out.append((start, bytes(cur)))
            cur, start = bytearray(), None
            if pg == b"\xff" * regions.PAGE:
                continue
        if start is None:
            start = a
        cur += pg
    if cur:
        out.append((start, bytes(cur)))
    return out


def reset_table(game, fresh, lay):
    lo, hi = regions.save_region(game)
    runs = runs_of(fresh, lo, hi)
    blocks = (hi - lo) // regions.ERASE_BLOCK
    assert 0 < blocks < 256 and len(runs) < 256
    tab = bytearray(a24(lo) + bytes([blocks, len(runs)]))
    for addr, data in runs:
        stream = zx.sized(data)
        tab += a24(addr) + bytes([len(data) // regions.PAGE]) + a24(lay.add(stream))
    return bytes(tab), runs


def a24(a):
    return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])


def byte_list(values):
    return "!byte " + ", ".join(f"${v:02x}" for v in values)


def build(parts, fresh):
    """parts: {game: its build's parts()}; fresh: the flash image of every
    game's blobs.  Returns (blobs -- the reset runs, in the launcher's
    region --, the page, the runs, the font); ultima/build.py puts the page and
    the font in the menu's PRG."""
    os.makedirs(BUILD, exist_ok=True)
    db, dl = regions.data_base("launcher"), regions.REGIONS["launcher"][1]
    lay = Layout(db)

    lines = [f"; generated by launcher.py -- do not edit",
             f"SETTINGS = ${regions.SETTINGS:x}",
             ]
    for g in ORDER:
        for name, value in sorted(parts[g]["page"].items()):
            lines.append(f"{name} = ${value:x}")
    caps, opt = [], []
    for g in ORDER:
        o = parts[g].get("options") or {}
        caps.append(o.get("caps", 0))
        addr = o.get("addr", 0)
        assert not 0xD000 <= addr < 0xE000, f"{g}: an options byte under I/O cannot be poked"
        assert not addr or addr >> 8, f"{g}: the page takes a zero high byte for no options byte"
        opt.append(addr)
    # what of the settings goes into the driver's options byte: its caps less
    # the options that are pokes (the U4 tile set, its powers)
    ptm = [c & ~sum({b for b in ((parts[g].get("options") or {}).get("pokes") or {})})
           for c, g in zip(caps, ORDER)]
    lines += ["ptm:    " + byte_list(ptm)]
    lines += ["caps:   " + byte_list(caps),
              "opt_lo: " + byte_list([a & 0xFF for a in opt]),
              "opt_hi: " + byte_list([a >> 8 for a in opt])]
    # options that are pokes rather than a bit in the driver's byte (the U4
    # tile set: the disk-A map pointer): per game a count, then bit, address
    # and value per poke; the page adds those whose bit is set
    have = []
    for g in ORDER:
        pk = (parts[g].get("options") or {}).get("pokes") or {}
        entries = [(bit, a, v) for bit, lst in sorted(pk.items()) for a, v in lst]
        for bit, a, _v in entries:
            assert not 0xD000 <= a < 0xE000, f"{g}: an option poke under I/O"
            assert bit & caps[ORDER.index(g)], f"{g}: an option poke for a bit it does not offer"
        if entries:
            lines.append(f"op_{g}: " + byte_list(bytes([len(entries)]) + b"".join(
                bytes([bit, a & 0xFF, a >> 8, v]) for bit, a, v in entries)))
            have.append(g)
    lines += ["op_lo: !byte " + ", ".join(f"<op_{g}" if g in have else "0" for g in ORDER),
              "op_hi: !byte " + ", ".join(f">op_{g}" if g in have else "0" for g in ORDER)]
    # the reset tables; a game with no saves (Akalabeth) has none, and its
    # page offers no reset and shows no saved game
    all_runs, saves = {}, [g for g in ORDER if regions.save_region(g)[1]]
    for g in saves:
        tab, all_runs[g] = reset_table(g, fresh, lay)
        lines.append(f"rs_{g}: " + byte_list(tab))
    lines += ["rs_lo: !byte " + ", ".join(f"<rs_{g}" if g in saves else "0" for g in ORDER),
              "rs_hi: !byte " + ", ".join(f">rs_{g}" if g in saves else "0" for g in ORDER)]
    # Journey onward: the pokes that send a game straight to its saved game
    # (a list of pokes, or {"pokes": [...], "bits": n}: bits the page ORs
    # into the options byte, for patches the driver applies as it loads)
    jo_or = []
    for g in ORDER:
        jo = parts[g].get("journey")
        bits = 0
        if isinstance(jo, dict):
            jo, bits = jo.get("pokes", []), jo.get("bits", 0)
            assert not bits or parts[g].get("options"), f"{g}: journey bits need an options byte"
        jo_or.append(bits)
        if jo is not None and (jo or bits):
            assert len(jo) <= 3, f"{g}: of the menu's twelve pokes, one is the options', " \
                                 "eight Ultima VI's transfer (page_u6t.s)"
            for addr, _v in jo:
                assert not 0xD000 <= addr < 0xE000, f"{g}: a poke under I/O"
            lines.append(f"jo_{g}: " + byte_list(bytes([len(jo)]) + b"".join(
                bytes([a & 0xFF, a >> 8, v]) for a, v in jo)))
        else:
            parts[g] = dict(parts[g], journey=None)
    lines.append("jo_or: " + byte_list(jo_or))
    lines += ["jo_lo: !byte " + ", ".join(f"<jo_{g}" if parts[g].get("journey") else "0"
                                          for g in ORDER),
              "jo_hi: !byte " + ", ".join(f">jo_{g}" if parts[g].get("journey") else "0"
                                          for g in ORDER)]
    # export/import (xfer.py; Ultima VI's world, page_u6x.s): too big for
    # the page itself, so they sit at XDATA, after the menu, as the end of
    # the launcher's PRG (ultima/build.py), loaded with the rest at power-on.
    # Only xf_lo/xf_hi stay in the page.
    items = []                          # (label, bytes, or a list of labels)
    for g in ORDER:
        if parts[g].get("xfer"):
            items.append((f"xf_{g}", xfer.table(parts[g]["xfer"])))
    u6x = parts["u6"].get("u6x")
    if u6x:
        items.append(("u6x_save", b"".join(a24(a) for a in u6x["save"])))
        n = len(u6x["world"])
        for i, w in enumerate(u6x["world"]):
            items.append((f"u6x_files_{i}", b"".join(
                name.encode("latin1") + bytes([t, s]) for name, t, s in w["files"])))
            items.append((f"u6x_pool_{i}", b"".join(bytes(ts) for ts in w["pool"])))
            items.append((f"u6x_bam_{i}", bytes(w["bam"])))
        assert all(len(w["pool"]) < 256 for w in u6x["world"])
        items += [("u6x_nfiles", bytes(len(w["files"]) for w in u6x["world"])),
                  ("u6x_npool", bytes(len(w["pool"]) for w in u6x["world"]))]
        for k in ("files", "pool", "bam"):
            names = [f"u6x_{k}_{i}" for i in range(n)]
            items += [(f"u6x_{k}_lo", ("lo", names)), (f"u6x_{k}_hi", ("hi", names))]
    size = sum(len(v) if isinstance(v, bytes) else len(v[1]) for _n, v in items)
    xbase = (XDATA_END - size) & ~0xFF
    addr, at = {}, xbase
    for n_, v in items:
        addr[n_] = at
        at += len(v) if isinstance(v, bytes) else len(v[1])
    xblob = b"".join(v if isinstance(v, bytes) else
                     bytes((addr[x] & 0xFF) if v[0] == "lo" else addr[x] >> 8 for x in v[1])
                     for _n, v in items)
    lines += [f"XDATA = ${xbase:x}", f"XDATA_END = ${XDATA_END:x}"]
    # Ultima VI's REU line (asm/page_reu.s): page.s is full, so it is a page of
    # its own just below the export tables, in the launcher's PRG too
    # (ultima/build.py puts it there and checks the menu ends before it)
    lines += [f"REU_ORG = ${xbase - 0x200:x}"]
    with open(os.path.join(BUILD, "xdata.bin"), "wb") as fh:
        fh.write(xblob)
    lines += [f"{n_} = ${a:x}" for n_, a in addr.items()]
    with open(os.path.join(BUILD, "xfer.json"), "w") as fh:     # for the tests
        json.dump({g: [d.describe() for d in parts[g]["xfer"]]
                   for g in ORDER if parts[g].get("xfer")}, fh, indent=1)
    lines += ["xf_lo: !byte " + ", ".join(f"<xf_{g}" if parts[g].get("xfer") else "0"
                                          for g in ORDER),
              "xf_hi: !byte " + ", ".join(f">xf_{g}" if parts[g].get("xfer") else "0"
                                          for g in ORDER)]
    with open(os.path.join(BUILD, "page_data.s"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # acme emits one blob from PAGE_ORG to the second piece's end, the hole
    # between (the menu, the REU line, the export tables) zero filled: the
    # two pieces go to build/page.bin and build/page_hi.bin
    whole, sym = os.path.join(BUILD, "page_all.bin"), os.path.join(BUILD, "page.sym")
    subprocess.run(["acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
                    "-o", whole, "-l", sym, os.path.join(paths.ASM, "page.s")], check=True)
    psym = symbols(sym)
    blob = Path(whole).read_bytes()
    page, hi = blob[:psym["page_end"] - PAGE_ORG], blob[XDATA_END - PAGE_ORG:]
    assert PAGE_ORG + len(page) <= MENU_ORG, "the page runs into the menu"
    assert not any(blob[len(page):XDATA_END - PAGE_ORG]), "page.s has code between its pieces"
    assert XDATA_END + len(hi) == psym["page_hi_end"]
    for name, data in (("page.bin", page), ("page_hi.bin", hi)):
        with open(os.path.join(BUILD, name), "wb") as fh:
            fh.write(data)
    with open(os.path.join(BUILD, "page_reu_syms.inc"), "w") as fh:
        for name in ("pr", "prdec16", "REU_ORG"):
            fh.write(f"{name} = ${psym[name]:x}\n")
    subprocess.run(["acme", "-f", "plain", "-I", paths.ASM, "-I", BUILD,
                    "-o", os.path.join(BUILD, "page_reu.bin"), "-l", os.path.join(BUILD, "page_reu.sym"),
                    os.path.join(paths.ASM, "page_reu.s")], check=True)

    lo = next(d for n, _a, d in parts["u1"]["loaded"] if n == "LO")
    if lay.cursor > dl:
        raise SystemExit(f"launcher: {lay.cursor - dl} bytes over its region")
    return list(lay.blobs), page, all_runs, font(lo, logo.build()["glyphs"])


def opt_addr(game, path=os.path.join(BUILD, "page_data.s")):
    """The options byte address build() put in the page's tables."""
    text = Path(path).read_text()
    row = lambda n: [int(v, 16) for v in re.search(rf"^{n}:\s+!byte (.*)$", text, re.M)
                     .group(1).replace("$", "").split(", ")]
    i = regions.DESC_INDEX[game]
    return row("opt_lo")[i] | row("opt_hi")[i] << 8


def symbols(path=os.path.join(BUILD, "page.sym")):
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}
