"""Ultima IV Remastered's tile set, as a second disk A (ultima/games/u4/build.py
lays it out as a fifth block map; the launcher's option points the driver's
disk-A map at it -- a launch-time switch).

What differs from disk A as the build has it otherwise:
- chunk $41, the tile bitmap ($B000-$CFFF), from the kit's tiles.png;
- chunk $4C: colour table 0 at $E1B0 and the font's colours at $E2B0;
- chunk $42, the font (17 frame glyphs redrawn);
- SUBS (chunk $4F): the kit's drawview, gettileaddr, fillrand and
  animate_flags over the original routines, at their addresses (the kit's
  loader copies them there too);
- chunk $50: the title scene's drawview, the same way;
- and character creation as Remastered has it (under the same switch): Vanja Utne's seven pictures ($45-$4B), the cards ($52)
  with their third colour ($9F, one block longer -- disk A block 296, which
  no chunk or record uses -- and the kernel's count for it poked from 5 to
  6 with the map), and the creation code that goes with them ($51: the
  moongate as sprites, the fade between pictures, the cards' colour RAM).
  The units are built as the kit's Makefile builds them (kit_creation():
  the .koa pictures and gen_cards the kit's way, charcreate.s over disk A's
  chunk $51 with 151.binpatch), merged three ways: a byte the kit left
  as the original keeps ours (the disk-swap hook at $692D), a byte both
  changed must agree.  $9D00-$9DFF, where the longer $9F loads, is free
  during creation: nothing loads there, and the only absolute operands into
  it on the four disks are game main's JSR $9DAC/$9DAE (play, after
  creation) and data;
- and the title picture's view (else the map below the logo starts in the
  old tiles).  The title dissolves in a
  picture -- the bitmap from chunk $43 ($4000, rows 0-23, $6525 copies it
  byte by byte), the colours from $9E ($0400) -- whose rows 13-22 are the
  view pre-rendered in the original tiles; the renderer only replaces it a
  second later.  title_view() recovers the view's tile map from the
  original picture (water matched through its vertical animation, one flag
  tile by its nearest match) and renders it as the renderer does -- the new
  bitmap, a colour table per cell -- into both chunks.  Checked against the
  renderer's first frame captured in VICE (tests/data/u4_title_frame.bin).
  One change: the colours ($9E) are all on screen before the dissolve has
  put a byte of the bitmap there, and an empty cell shows its background --
  so a cell whose background is not black (the castle door's two, light
  grey on brown) gets a black one in the picture, as the original's cells
  all are, and the renderer's first frame puts the brown in (else a brown
  block shows during the dissolve).

The kit's drawview colours each of a tile's four 8x8 cells from its own
table; its tables 1-3 live in its loader's RAM ($A800, $A900, $F300), and
$F300 is read in play here (a memmap).  Ours are a boot segment at
$A700-$A9FF, which the driver leaves free for them (its code is in the RAM
under I/O, u4drv.s); with fewer tables 36 tiles would lose a cell's own
colour (the title's castle: a red roof on one tower, grey on the other).
The dungeon (one unit for
both maps) keeps table 0 only.
"""
import os
import re
import subprocess
from pathlib import Path

from ultima.games.u4 import tiles

from ultima import paths

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(paths.EXTERNAL, "u4remastered")
BUILD = paths.BUILD
CC = os.path.join(BUILD, "u4kit", "cc")         # where kit_creation() builds

CREATION = {0x45: "145", 0x46: "146", 0x47: "147", 0x48: "148", 0x49: "149",
            0x4A: "14a", 0x4B: "14b", 0x51: "151", 0x52: "152", 0x9F: "19f"}
LONGER = 0x9F                   # one block more: the kernel's count, poked
# the title picture: its bitmap (chunk $43, rows of 320 bytes) and colours
# ($9E, rows of 40); the view is rows 13-22, 19 tiles from column 1
TITLE_BITMAP, TITLE_COLOURS = 0x43, 0x9E
VIEW_ROW, VIEW_COL, VIEW_H, VIEW_W = 13, 1, 5, 19
WATER = (0, 1, 2)               # animated: their rows scroll

TABLE0 = 0xE1B0                 # the original's one tile_color table
TABLES = 0xA700                 # tables 1-3, a page each (a boot segment)
FONT_COLOURS = 0xE2B0
# the routines' slots: address, size (the kit's relocs.cfg / the analysis's)
SLOTS = {"DRAWVIEW": (0x0E6C, 0xEA), "GETTILEADDR": (0x148B, 0x1E),
         "FILLRAND": (0x14CC, 0x0D), "ANIMATEFLAGS": (0x1504, 0x6E),
         "DRAWVIEWTITLE": (0x6B83, 0xEB)}
CHUNK_OF = {"DRAWVIEW": 0x4F, "GETTILEADDR": 0x4F, "FILLRAND": 0x4F, "ANIMATEFLAGS": 0x4F,
            "DRAWVIEWTITLE": 0x50}


def graphics():
    """(bitmap, [four tables], font glyphs, font colours) from the kit."""
    bm, tabs = tiles.gen_tiles(os.path.join(KIT, "src", "tiles", "tiles.png"))
    fb, fc = tiles.gen_font(os.path.join(KIT, "src", "tiles", "font.png"))
    assert len(bm) == 0x2000 and len(fb) == 0x400 and len(fc) == 0x80
    return bm, tabs, fb, fc


def renderers():
    """{segment: bytes}, each assembled for its slot."""
    work = os.path.join(BUILD, "u4tiles")
    os.makedirs(work, exist_ok=True)
    objs = []
    for name in ("drawview", "drawviewtitle"):
        s = os.path.join(work, name + ".s")
        Path(s).write_text(Path(os.path.join(KIT, "src", "tiles", name + ".s")).read_text())
        o = os.path.join(work, name + ".o")
        subprocess.run(["ca65", "-t", "c64", "-I", os.path.join(KIT, "src", "include"), "-o", o, s],
                       check=True)
        objs.append(o)
    cfg = os.path.join(work, "relocs.cfg")
    files = {seg: os.path.join(work, seg.lower() + ".bin") for seg in SLOTS}
    with open(cfg, "w") as fh:
        fh.write("MEMORY {\n")
        for seg, (addr, size) in SLOTS.items():
            fh.write(f'    {seg}: start = ${addr:04x}, size = ${size:02x}, file = "{files[seg]}";\n')
        fh.write("}\nSEGMENTS {\n")
        for seg in SLOTS:
            fh.write(f"    {seg}: load = {seg}, type = rw;\n")
        fh.write("}\n")
    subprocess.run(["ld65", "-C", cfg, "-o", os.path.join(work, "unused.bin"),
                    "-D", f"tilecolors0=${TABLE0:04x}", "-D", f"tilecolors1=${TABLES:04x}",
                    "-D", f"tilecolors2=${TABLES + 0x100:04x}", "-D", f"tilecolors3=${TABLES + 0x200:04x}",
                    *objs], check=True)
    out = {seg: Path(files[seg]).read_bytes() for seg in SLOTS}
    for seg, (addr, size) in SLOTS.items():
        assert 0 < len(out[seg]) <= size, (seg, len(out[seg]))
    return out


def variant(disk_a, original_a, chunk_entry, patch):
    """disk_a as build.py has it, with the Remastered tile set (original_a:
    the disk as shipped, to prove no other patch is in a slot).  Returns the
    new image and the segment of tables 1-3 (for TABLES)."""
    img = bytearray(disk_a)
    bm, tabs, fb, fc = graphics()

    def at(chunk, addr):
        start, count, dest = chunk_entry(chunk)
        assert dest <= addr < dest + count * 256, (hex(chunk), hex(addr))
        return (start + (addr - dest) // 256) * 256 + ((addr - dest) & 0xFF)

    for chunk, dest, data in ((0x41, 0xB000, bm), (0x42, 0xE400, fb)):
        start, count, d = chunk_entry(chunk)
        assert (d, count * 256) == (dest, len(data)), (hex(chunk), hex(d), count)
        img[start * 256:start * 256 + len(data)] = data
    for addr, data in ((TABLE0, tabs[0]), (FONT_COLOURS, fc)):
        o = at(0x4C, addr)
        img[o:o + len(data)] = data
    for seg, code in renderers().items():
        addr, size = SLOTS[seg]
        o = at(CHUNK_OF[seg], addr)
        # the slot holds the original routine: nothing else patched it
        assert disk_a[o:o + size] == original_a[o:o + size], f"tile set: {seg}'s slot is patched"
        patch(img, o, bytes(disk_a[o:o + len(code)]), code, f"tile set: {seg}")
    creation(img, disk_a, original_a, chunk_entry)
    title_view(img, disk_a, original_a, chunk_entry, bm, tabs)
    return bytes(img), tabs[1] + tabs[2] + tabs[3]


def cell_colours(tabs, t):
    """The four cells' colours, as the renderer gives them: a table each."""
    return tuple(tabs[k][t] for k in range(4))


def tile_cells(bitmap, t):
    """Tile t's four 8x8 cells: upper left, upper right, lower left, right."""
    return (bitmap[16 * t:16 * t + 8], bitmap[16 * t + 8:16 * t + 16],
            bitmap[0x1000 + 16 * t:0x1000 + 16 * t + 8],
            bitmap[0x1000 + 16 * t + 8:0x1000 + 16 * t + 16])


def view_map(picture, tiles):
    """[(row, col, tile)] of the title picture's view (see the docstring)."""
    def rows16(cells):
        ul, ur, ll, lr = cells
        return [bytes([ul[i], ur[i]]) for i in range(8)] + [bytes([ll[i], lr[i]]) for i in range(8)]
    out, near = [], 0
    for tr in range(VIEW_H):
        for tc in range(VIEW_W):
            r, c = VIEW_ROW + 2 * tr, VIEW_COL + 2 * tc
            got = tuple(bytes(picture[rr * 320 + cc * 8:rr * 320 + cc * 8 + 8])
                        for rr, cc in ((r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)))
            found = [t for t in range(256) if tile_cells(tiles, t) == got]
            if not found:                       # water, a frame of its scroll
                g = rows16(got)
                found = [t for t in WATER for s in range(16)
                         if rows16(tile_cells(tiles, t))[s:] + rows16(tile_cells(tiles, t))[:s] == g]
            if not found:                       # a flag, a frame of its animation
                d = lambda t: sum(bin(x ^ y).count("1")
                                  for x, y in zip(b"".join(tile_cells(tiles, t)), b"".join(got)))
                best, second = sorted(range(256), key=d)[:2]
                # (the one there: 22 bits off its tile, 79 off any other)
                assert d(best) <= 32 and 2 * d(best) < d(second), (tr, tc, best, d(best), d(second))
                found, near = [best], near + 1
            out.append((r, c, found[0]))
    assert near <= 2, f"{near} view tiles matched only by nearness"
    return out


def title_view(img, disk_a, original_a, chunk_entry, bitmap, tabs):
    """The title picture's view in the new tiles (see the docstring)."""
    ts, tc_, td = chunk_entry(0x41)
    tiles = bytes(original_a[ts * 256:(ts + tc_) * 256])
    ps, pc, pd = chunk_entry(TITLE_BITMAP)
    cs, cc, cd = chunk_entry(TITLE_COLOURS)
    assert (pd, pc, cd, cc) == (0x4000, 30, 0x0400, 4), (hex(pd), pc, hex(cd), cc)
    for s, c in ((ps, pc), (cs, cc)):           # nothing else patched them
        assert disk_a[s * 256:(s + c) * 256] == original_a[s * 256:(s + c) * 256]
    picture = bytes(original_a[ps * 256:(ps + pc) * 256])
    for r, c, t in view_map(picture, tiles):
        cells = tile_cells(bitmap, t)
        cols = cell_colours(tabs, t)
        for k, (rr, cc2) in enumerate(((r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1))):
            o = ps * 256 + rr * 320 + cc2 * 8
            img[o:o + 8] = cells[k]
            img[cs * 256 + rr * 40 + cc2] = cols[k] & 0xF0    # (see the docstring)


def binpatch(data, path):
    """The kit's tools/binpatch.py, the same commands and semantics: a
    patch file applied to a file's bytes (load address included)."""
    def args(text):
        vals, inq, qs, hv = [], False, "", None
        for ch in text:
            if ch == '"':
                if inq:
                    vals.extend(ord(x) | 0x80 for x in qs)
                qs, inq = "", not inq
            elif inq:
                qs += ch
            elif ch == " ":
                if hv is not None:
                    vals.append(hv)
                    hv = None
            elif ch.isdigit() or "a" <= ch.lower() <= "f":
                hv = int(ch, 16) if hv is None else hv * 16 + int(ch, 16)
        if hv is not None:
            vals.append(hv)
        return vals

    data, off, ml = bytearray(data), 0, 0
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = re.sub(r"\s*#.*$", "", line).strip()
        for m in re.finditer(r"\b(\w+)\(([^)]*)\)", line):
            cmd, a = m.group(1), args(m.group(2))
            if cmd in ("offset", "truncate"):
                off = a[0]
                assert 0 <= off <= len(data), f"{path}:{n}: {cmd} out of range"
                if cmd == "truncate":
                    del data[off:]
            elif cmd in ("match", "delete"):
                assert bytes(data[off:off + len(a)]) == bytes(a), \
                    f"{path}:{n}: {cmd} failed at {off:04x}"
                if cmd == "delete":
                    del data[off:off + len(a)]
                ml = len(a) if cmd == "match" else 0
            elif cmd == "replace":
                assert len(a) == ml, f"{path}:{n}: replace expected {ml} bytes"
                data[off:off + len(a)] = a
            elif cmd == "insert":
                data[off:off] = a
            elif cmd == "append":
                data += bytes(a)
            else:
                raise SystemExit(f"{path}:{n}: unknown command {cmd}")
    return bytes(data)


def koala(path):
    """A Koala picture: its bitmap, screen colours and colour RAM."""
    d = Path(path).read_bytes()[2:]
    return d[:8000], d[8000:9000], d[9000:10000]


def cards():
    """The kit's tools/gen_cards.py: the eight virtue cards (10 x 14 cells)
    cut out of two Koala pictures -- chunk $52's bitmaps ($4000) and chunk
    $9F's colours ($9800: per card 140 screen colours + 4 pad, then per card
    14 colour-RAM bytes + 2 pad), each as a PRG."""
    cut = []
    for name in ("cards1", "cards2"):
        bm, co, d8 = koala(os.path.join(KIT, "src", "charcreate", name + ".koa"))
        for x in (0, 10, 20, 30):
            cut.append((b"".join(bm[y * 320 + x * 8:][:80] for y in range(14)),
                        b"".join(co[y * 40 + x:][:10] for y in range(14)),
                        bytes(d8[y * 40 + x] for y in range(14))))
    return (b"\x00\x40" + b"".join(c[0] for c in cut),
            b"\x00\x98" + b"".join(c[1] + bytes(4) for c in cut)
            + b"".join(c[2] + bytes(2) for c in cut))


def kit_creation(original_a, chunk_entry):
    """The kit's creation units as its Makefile builds them, from its
    sources and disk A: {name: PRG}.  $51 is charcreate.s, which includes
    disk A's chunk $51 with 151.binpatch applied; $9F is cardcolors.s over
    gen_cards' colours; $52 is gen_cards' bitmaps; $45-$4B are the .koa
    pictures cut to bitmap rows 0-23, screen and colour RAM 0-767."""
    files = os.path.join(CC, "files", "patched")
    os.makedirs(files, exist_ok=True)
    src = os.path.join(KIT, "src", "charcreate")
    start, count, dest = chunk_entry(0x51)
    extracted = bytes([dest & 0xFF, dest >> 8]) + bytes(original_a[start * 256:(start + count) * 256])
    units = {}
    units["152"], c19f = cards()
    for name, data in (("151", binpatch(extracted, os.path.join(KIT, "patches", "151.binpatch"))),
                       ("152", units["152"]), ("19f", c19f)):
        Path(os.path.join(files, name + ".prg")).write_bytes(data)
    inc = ["--bin-include-dir", CC, "-I", CC, "-I", os.path.join(KIT, "src", "include")]
    for name in ("charcreate", "cardcolors"):
        subprocess.run(["ca65", "-t", "c64", *inc, "-o", os.path.join(CC, name + ".o"),
                        os.path.join(src, name + ".s")], check=True)
    lao = os.path.join(CC, "loadaddr.o")
    subprocess.run(["ca65", "-t", "c64", "-o", lao, os.path.join(KIT, "src", "loadaddr.s")],
                   check=True)
    for name, cfg, objs in (("151", "charcreate", ("charcreate", "cardcolors")),
                            ("19f", "cardcolors", ("cardcolors",))):
        prg = os.path.join(CC, name + ".prg")
        subprocess.run(["ld65", "-C", os.path.join(src, cfg + ".cfg"), "-o", prg, lao,
                        *(os.path.join(CC, o + ".o") for o in objs)], check=True)
        units[name] = Path(prg).read_bytes()
    for name in ("145", "146", "147", "148", "149", "14a", "14b"):
        k = Path(os.path.join(src, name + ".koa")).read_bytes()
        units[name] = b"\x00\x40" + k[2:2 + 5888] + k[8002:8002 + 768] + k[9002:9002 + 768]
    return units


def creation(img, disk_a, original_a, chunk_entry):
    """Remastered's character creation over img (see the docstring)."""
    units = kit_creation(original_a, chunk_entry)
    for chunk, name in CREATION.items():
        start, count, dest = chunk_entry(chunk)
        prg = units[name]
        load, kit = prg[0] | prg[1] << 8, prg[2:]
        assert load == dest, (name, hex(load), hex(dest))
        want = count + (chunk == LONGER)
        assert -(-len(kit) // 256) == want, (name, len(kit), want)
        o = start * 256
        for i, b in enumerate(kit):
            orig, ours = original_a[o + i], disk_a[o + i]
            if b == orig:
                continue                # the kit left it: ours stays
            assert ours in (orig, b), \
                f"creation: {name} at {dest + i:#06x}, ours {ours:02x} and the kit's {b:02x}"
            img[o + i] = b
