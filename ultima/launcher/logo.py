#!/usr/bin/env python3
"""The launcher's logo, composed from the games' own data at build time: the
characters it needs, in codes the launcher's texts never print, and the
screen rows that show them.  No sprites: the subtitle is Ultima IV's letter
tiles.

The picture, 320 x 88 pixels (the top 11 character rows; one colour per cell):

  * "Ultima": Ultima V's C64 title without its V -- U5.LOGO drawn into a
    bitmap by the title's own blitter (STARTUP $91ED, run in py65, as the
    attract sequence calls it), each cell in its LOGO.COLORS foreground
    (cyan, light blue), moved 5 cells right and 1 up, the V's cells left out;
  * "TAPECART COLLECTION" in Ultima IV's letter tiles (disk A chunk $41,
    tiles $60-$79 for A-Z, $7A the space, 16 x 16 each; their rule lines join
    into a banner, as on its towns' signs) in cyan, on character rows 9-10,
    with our own fix to its P (U4's has an open bowl and a wide foot, and
    reads as an L): three pixels closing the bowl, four off the foot.

Nothing of the picture is shipped; tests/test_logo.py pins its hash.

The codes are the reverse half of the font, $80-$FF (the launcher prints no
reverse text), then $61-$7F, which only shifted-graphics PETSCII reaches
($60, which shifted space would print, is left alone).  asm/menu.s draws it
from build/logo.s, which `source()` writes."""
import importlib.util

from ultima import paths
from ultima.disks.d64 import D64             # noqa: E402

W, H = 320, 88
ROWS = H // 8
CODES = list(range(0x80, 0x100)) + list(range(0x61, 0x80))
COLOURS = {"c": 3, "b": 14, "w": 1}
COLOUR_CH = {v: k for k, v in COLOURS.items()}

TITLE_MOVE = (5, -1)            # the title's cell (cx, cy) -> the logo's (cx + 5, cy - 1)
TITLE_COLS = 27                 # its cells 0-26 are "Ultima"; from 27 on, the V
BAND_AT = (8, 72)               # the letters' top left, in pixels
BAND_TEXT = "TAPECART COLLECTION"
BAND_COLOUR = "c"
P_FIX = {(6, 9): 1, (7, 9): 1, (8, 9): 1,                   # the bowl closed
         (7, 13): 0, (8, 13): 0, (9, 13): 0, (10, 13): 0}   # the foot narrowed


def _module(game):
    return importlib.import_module(f"ultima.games.{game}.build")


def u5_title():
    """Ultima V's title: (the 8 KiB bitmap its blitter draws, LOGO.COLORS)."""
    from py65.devices.mpu6502 import MPU
    disk = D64(paths.disk("u5-1a"))
    startup, _ok = disk.file("STARTUP")
    logo, _ok = disk.file("U5.LOGO")
    colours, _ok = disk.file("LOGO.COLORS")
    assert startup[:2] == b"\x00\x80" and logo[:2] == b"\x00\xc0", "not the STARTUP and U5.LOGO it was"
    mpu = MPU()
    m = mpu.memory
    m[0x8000:0x8000 + len(startup) - 2] = startup[2:]
    m[0xC000:0xC000 + len(logo) - 2] = logo[2:]
    m[0x6C03] = m[0x6C06] = 0x60        # the disk vectors it calls: nothing to do here
    m[0x91EE] = 0xC0                    # the source page, as the attract sequence sets it
    done = 0x0F10
    m[0x1FF], m[0x1FE] = (done - 1) >> 8, (done - 1) & 0xFF
    mpu.sp, mpu.pc, mpu.a = 0xFD, 0x91ED, 0x40          # into the bitmap at $4000
    for _ in range(5_000_000):
        if mpu.pc == done:
            break
        mpu.step()
    else:
        raise SystemExit("logo: U5's title blitter did not return")
    return bytes(m[0x4000:0x6000]), colours[2:]


def u4_tile(bitmap, t):
    """A 16 x 16 tile of U4's chunk $41 as 16 strings of '0'/'1'."""
    cells = (bitmap[16 * t:16 * t + 8], bitmap[16 * t + 8:16 * t + 16],
             bitmap[0x1000 + 16 * t:0x1000 + 16 * t + 8], bitmap[0x1000 + 16 * t + 8:0x1000 + 16 * t + 16])
    return ["".join("1" if cells[2 * half + k][r] & (0x80 >> b) else "0" for k in (0, 1) for b in range(8))
            for half in (0, 1) for r in range(8)]


def u4_tiles():
    u4 = _module("u4")
    disk = D64(paths.disk("u4a"))

    start, count, _dest = u4.chunk_entry(u4.kernel_image(disk), 0x41)
    return disk.data[start * 256:(start + count) * 256]


def art():
    """The picture: 88 strings of 320 characters, '.' black, else a COLOURS key."""
    px = [["."] * W for _ in range(H)]
    bitmap, colours = u5_title()
    dx, dy = TITLE_MOVE
    for cy in range(25):
        for cx in range(TITLE_COLS):
            lx, ly = cx + dx, cy + dy
            cell = bitmap[cy * 320 + cx * 8:cy * 320 + cx * 8 + 8]
            if not any(cell):
                continue
            assert 0 <= lx < 40 and 0 <= ly < ROWS, f"title cell {cx},{cy} off the logo"
            ch = COLOUR_CH[colours[cy * 40 + cx] >> 4]
            for r in range(8):
                for b in range(8):
                    if cell[r] & (0x80 >> b):
                        px[ly * 8 + r][lx * 8 + b] = ch
    tiles = u4_tiles()
    x0, y0 = BAND_AT
    for i, letter in enumerate(BAND_TEXT):
        tile = u4_tile(tiles, 0x7A if letter == " " else 0x60 + ord(letter) - ord("A"))
        for y in range(16):
            for x in range(16):
                on = P_FIX.get((x, y), tile[y][x] == "1") if letter == "P" else tile[y][x] == "1"
                if on:
                    px[y0 + y][x0 + 16 * i + x] = BAND_COLOUR
    return ["".join(r) for r in px]


def build():
    px = art()
    glyphs, codes = {}, {}
    screen = [[0x20] * 40 for _ in range(ROWS)]
    colour = [[1] * 40 for _ in range(ROWS)]
    for cy in range(ROWS):
        for cx in range(40):
            fg = {ch for r in px[cy * 8:cy * 8 + 8] for ch in r[cx * 8:cx * 8 + 8] if ch in COLOURS}
            assert len(fg) <= 1, f"logo cell {cx},{cy} has more than one colour: {fg}"
            if fg:
                colour[cy][cx] = COLOURS[fg.pop()]
            g = bytes(int("".join("1" if ch in COLOURS else "0"
                                  for ch in px[cy * 8 + r][cx * 8:cx * 8 + 8]), 2)
                      for r in range(8))
            if not any(g):
                continue
            if g not in codes:
                assert len(codes) < len(CODES), "the logo needs more characters than are free"
                codes[g] = CODES[len(codes)]
                glyphs[codes[g]] = g
            screen[cy][cx] = codes[g]

    # the rectangle of character cells the logo uses
    used = [cx for r in screen for cx, c in enumerate(r) if c != 0x20]
    last = max(cy for cy, r in enumerate(screen) if any(c != 0x20 for c in r))
    left, right = min(used), max(used)
    return dict(glyphs=glyphs, screen=screen, colour=colour,
                left=left, width=right - left + 1, height=last + 1)


def source(lg):
    """build/logo.s for asm/menu.s: the rectangle's rows and their colours."""
    out = [";;; generated by logo.py from the games' data",
           f"LOGO_LEFT = {lg['left']}",
           f"LOGO_W    = {lg['width']}",
           f"LOGO_H    = {lg['height']}"]
    b = lambda data: [f"        !byte {', '.join(f'${v:02x}' for v in data[i:i + 16])}"
                      for i in range(0, len(data), 16)]
    out.append("logo_scr:")
    for r in lg["screen"][:lg["height"]]:
        out += b(r[lg["left"]:lg["left"] + lg["width"]])
    out.append("logo_col:")
    for r in lg["colour"][:lg["height"]]:
        out += b(r[lg["left"]:lg["left"] + lg["width"]])
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    lg = build()
    print(f"{len(lg['glyphs'])} characters of {len(CODES)}, cells {lg['left']}+{lg['width']} x {lg['height']}")
