"""What the map renderers share: an RGB canvas, the C64's colours, text in a
game's own 8x8 font, and a PNG writer (zlib only -- the workspace has no
Pillow, and needs none).

    c = Canvas(w, h)
    c.fill(x, y, w, h, colour)          # colour: 0-15 (the C64's) or (r, g, b)
    c.hires(x, y, cell_bytes, fg, bg)   # an 8x8 hires cell
    c.text(x, y, "TEXT", font, fg)      # font: 8 bytes a glyph, by index
    c.write("out.png")

Every game's overworld marks its places the same way (mark_places,
with_legend, write_places): a yellow frame round the square and its key
(a number or letter) beside it, a legend on the image's right -- key, name,
coordinates -- and the same list as places.txt.
"""
import os
import struct
import zlib



# VICE's "pepto" palette
PALETTE = [(0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF), (0x68, 0x37, 0x2B), (0x70, 0xA4, 0xB2),
           (0x6F, 0x3D, 0x86), (0x58, 0x8D, 0x43), (0x35, 0x28, 0x79), (0xB8, 0xC7, 0x6F),
           (0x6F, 0x4F, 0x25), (0x43, 0x39, 0x00), (0x9A, 0x67, 0x59), (0x44, 0x44, 0x44),
           (0x6C, 0x6C, 0x6C), (0x9A, 0xD2, 0x84), (0x6C, 0x5E, 0xB5), (0x95, 0x95, 0x95)]


def u1_font():
    """Ultima I's text font, the launcher's: the first 1 KiB of LO, ASCII
    order (128 glyphs, 8 bytes each; '/' is a game symbol there).  For the
    games whose own font is not handy."""
    from ultima import paths
    from ultima.disks.d64 import D64
    data = D64(paths.disk("u1")).file("LO")[0][2:2 + 1024]
    out = bytearray(data)
    out[0x2F * 8:0x2F * 8 + 8] = bytes([0x00, 0x06, 0x06, 0x0C, 0x18, 0x30, 0x60, 0x60])
    return bytes(out)


def label(c, x, y, s, fg=1, font=None, scale=1):
    """Text in U1's font (or the given one), ASCII."""
    c.text(x, y, s, font or u1_font(), fg, scale, code=lambda ch: ord(ch) & 0x7F)


def wrap(s, width, scale=1):
    """s broken at spaces into lines of at most width pixels (8 x scale a
    letter)."""
    most = max(1, width // (8 * scale))
    lines, line = [], ""
    for word in s.split(" "):
        if line and len(line) + 1 + len(word) > most:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    lines.append(line)
    assert all(len(ln) <= most for ln in lines), f"a word longer than {most} letters: {s!r}"
    return lines


def rgb(c):
    return PALETTE[c & 15] if isinstance(c, int) else c


class Canvas:
    def __init__(self, w, h, colour=0):
        self.w, self.h = w, h
        self.px = bytearray(bytes(rgb(colour)) * (w * h))

    def put(self, x, y, colour):
        if 0 <= x < self.w and 0 <= y < self.h:
            o = 3 * (y * self.w + x)
            self.px[o:o + 3] = bytes(rgb(colour))

    def fill(self, x, y, w, h, colour):
        c = bytes(rgb(colour))
        for yy in range(max(0, y), min(self.h, y + h)):
            x0, x1 = max(0, x), min(self.w, x + w)
            if x1 > x0:
                o = 3 * (yy * self.w + x0)
                self.px[o:o + 3 * (x1 - x0)] = c * (x1 - x0)

    def frame(self, x, y, w, h, colour, t=1):
        self.fill(x, y, w, t, colour)
        self.fill(x, y + h - t, w, t, colour)
        self.fill(x, y, t, h, colour)
        self.fill(x + w - t, y, t, h, colour)

    def hires(self, x, y, cell, fg, bg, scale=1):
        f, b = bytes(rgb(fg)), bytes(rgb(bg))
        for r in range(8):
            bits = cell[r]
            for cbit in range(8):
                col = f if bits & (0x80 >> cbit) else b
                if scale == 1:
                    xx, yy = x + cbit, y + r
                    if 0 <= xx < self.w and 0 <= yy < self.h:
                        o = 3 * (yy * self.w + xx)
                        self.px[o:o + 3] = col
                else:
                    self.fill(x + cbit * scale, y + r * scale, scale, scale, col)

    def glyph(self, x, y, cell, fg, scale=1):
        """An 8x8 glyph, its set pixels only."""
        for r in range(8):
            for cbit in range(8):
                if cell[r] & (0x80 >> cbit):
                    self.fill(x + cbit * scale, y + r * scale, scale, scale, fg)

    def text(self, x, y, s, font, fg, scale=1, code=None):
        """s in the font's order: code(ch) -> glyph index (default ord).
        Text that would not fit the canvas is an error, not cut off."""
        if x < 0 or y < 0 or x + 8 * scale * len(s) > self.w or y + 8 * scale > self.h:
            raise ValueError(f"text off the {self.w}x{self.h} canvas at ({x}, {y}): {s!r}")
        for i, ch in enumerate(s):
            g = (code or ord)(ch)
            self.glyph(x + 8 * scale * i, y, font[8 * g:8 * g + 8], fg, scale)

    def line(self, x0, y0, x1, y1, colour, t=1):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i // n
            y = y0 + (y1 - y0) * i // n
            self.fill(x - t // 2, y - t // 2, t, t, colour)

    def blit(self, other, x, y):
        for yy in range(other.h):
            if 0 <= y + yy < self.h:
                o = 3 * ((y + yy) * self.w + x)
                self.px[o:o + 3 * other.w] = other.px[3 * yy * other.w:3 * (yy + 1) * other.w]

    def write(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        raw = b"".join(b"\x00" + bytes(self.px[3 * y * self.w:3 * (y + 1) * self.w])
                       for y in range(self.h))

        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---- places on an overworld map: one way for every game --------------------
# (the keys are outlined in black: yellow alone was lost on light ground)
# A place is (key, x, y, name, kind[, colour]): its key on the map (a number
# or letter), its square, what the legend calls it, what it is ("town",
# "dungeon", ...), and the legend's colour for its name (default white).
# x None: a place with no square on the map (listed, not marked).
PLACE_COLOUR = 7                                # yellow


def mark_places(c, places, tile, write, ox=0, oy=0, colour=PLACE_COLOUR):
    """A frame round each place's square (tile pixels a square, from ox/oy)
    and its key beside it; write(c, x, y, text, colour) draws text in the
    game's font."""
    for key, x, y, *_ in places:
        if x is None:
            continue
        X, Y = ox + x * tile, oy + y * tile
        c.frame(X - 2, Y - 2, tile + 4, tile + 4, colour, 2)
        k = str(key)
        kx = X + tile + 3 if X + tile + 4 + 8 * len(k) <= c.w else X - 4 - 8 * len(k)
        kx = max(1, min(kx, c.w - 1 - 8 * len(k)))
        ky = max(1, min(Y + (tile - 8) // 2, c.h - 9))
        outlined(c, kx, ky, k, write, colour)


def outlined(c, x, y, text, write, colour, edge=0):
    """text with a one-pixel outline (black), readable on any background:
    drawn in the edge colour at the eight neighbouring offsets, then itself."""
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        write(c, x + dx, y + dy, text, edge)
    write(c, x, y, text, colour)


def with_legend(c, places, write, title="Places", colour=1, key_colour=PLACE_COLOUR):
    """c with a panel on its right: each place's key, name and x,y, in as
    many columns as its height needs."""
    kw = max(len(str(p[0])) for p in places)
    lines = [(str(p[0]).rjust(kw), f"  {p[3]}" + (f"  {p[1]},{p[2]}" if p[1] is not None else ""),
              p[5] if len(p) > 5 else colour)
             for p in places]
    per = max(1, (c.h - 28) // 12)
    cols = [lines[i:i + per] for i in range(0, len(lines), per)]
    cw = 8 * max(len(k) + len(t) for k, t, _ in lines) + 24
    out = Canvas(c.w + 16 + cw * len(cols), max(c.h, 28 + 12 * min(per, len(lines))), 0)
    out.blit(c, 0, 0)
    write(out, c.w + 16, 4, title, colour)
    for n, col in enumerate(cols):
        for i, (k, t, fg) in enumerate(col):
            X, Y = c.w + 16 + n * cw, 20 + 12 * i
            write(out, X, Y, k, key_colour)
            write(out, X + 8 * len(k), Y, t, fg)
    return out


def write_places(path, header, places):
    """places.txt: the header, then key, kind, x, y and name a line."""
    kw = max(len(str(p[0])) for p in places)
    nw = max(len(p[4]) for p in places)
    with open(path, "w") as fh:
        fh.write(header.rstrip("\n") + "\n")
        for key, x, y, name, kind, *_ in places:
            where = f"x {x:3d}  y {y:3d}" if x is not None else "(no square) "
            fh.write(f"{str(key):>{kw}}  {kind:{nw}s}  {where}  {name}\n")
