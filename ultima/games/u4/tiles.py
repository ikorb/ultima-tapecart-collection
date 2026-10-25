"""Ultima IV Remastered's tile set and font, made from the kit's PNGs
(src/tiles/tiles.png, font.png) as its tools/gen_tiles.py and gen_font.py do
-- a Python 3 port of those (Apache 2.0, see NOTICE.md), with a minimal PNG
reader: 8-bit palette, non-interlaced, palette index =
C64 colour, which is what the two files are.

A tile is 16 x 16: its upper half, two 8 x 8 cells, at $B000 + 16 t, its
lower half at $C000 + 16 t; a cell's colour is fg << 4 | bg, the darker of
its two colours the background.  gen_tiles gives the bitmap ($2000) and one
colour table per cell (upper left, upper right, lower left, lower right)."""
import struct
import zlib
from pathlib import Path

VIC_LUMA = [0, 15, 4, 11, 5, 9, 1, 14, 6, 2, 10, 3, 8, 13, 7, 12]


def read_png(path):
    d = Path(path).read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, idat, hdr = 8, b"", None
    while pos < len(d):
        n, typ = struct.unpack(">I4s", d[pos:pos + 8])
        body = d[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, ctype, _c, _f, interlace = hdr
    assert depth == 8 and ctype == 3 and interlace == 0, (path, hdr)
    raw = zlib.decompress(idat)
    rows, prev = [], bytearray(w)
    for y in range(h):
        f = raw[y * (w + 1)]
        line = bytearray(raw[y * (w + 1) + 1:(y + 1) * (w + 1)])
        for x in range(w):
            a = line[x - 1] if x else 0
            b = prev[x]
            c = prev[x - 1] if x else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return w, h, rows


def cell(rows, x0, y0, font):
    cols = {}
    for y in range(8):
        for x in range(8):
            p = rows[y0 + y][x0 + x]
            cols[p] = cols.get(p, 0) + 1
    assert len(cols) <= 2, f"the cell at {x0},{y0} has {len(cols)} colours"
    if len(cols) == 1:
        c = next(iter(cols))
        if font:
            fg, bg = (1, 0) if c == 0 else (c, 0)
        else:
            bg, fg = c, (0 if c else 1)
    else:
        bg, fg = sorted(cols, key=lambda k: VIC_LUMA[k])
    if font and (bg, fg) == (6, 14):
        bg, fg = fg, bg
    out = []
    for y in range(8):
        b = 0
        for x in range(8):
            if rows[y0 + y][x0 + x] == fg:
                b |= 0x80 >> x
        out.append(b)
    return out, (fg << 4) | bg


def gen_tiles(path):
    """(bitmap: $1000 upper halves then $1000 lower, [four colour tables])"""
    _w, _h, rows = read_png(path)
    upper, lower, tables = bytearray(), bytearray(), [bytearray() for _ in range(4)]
    for t in range(256):
        tx, ty = (t & 15) * 16, (t >> 4) * 16
        bm = []
        for k, (cy, cx) in enumerate(((0, 0), (0, 8), (8, 0), (8, 8))):
            b, c = cell(rows, tx + cx, ty + cy, False)
            bm.append(b)
            tables[k].append(c)
        # a half is its two cells, 8 bytes each
        upper += bytes(bm[0] + bm[1])
        lower += bytes(bm[2] + bm[3])
    return bytes(upper + lower), [bytes(t) for t in tables]


def gen_font(path):
    """(128 glyphs x 8, 128 colour bytes)"""
    _w, _h, rows = read_png(path)
    bm, cols = [], []
    for cy in range(0, 32, 8):
        for cx in range(0, 256, 8):
            b, c = cell(rows, cx, cy, True)
            bm += b
            cols.append(c)
    return bytes(bm), bytes(cols)
