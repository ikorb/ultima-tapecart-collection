"""The launcher's logo: what the built image holds -- the font in the menu's
PRG, the screen rows and colours in the menu -- drawn the way the VIC draws
it, against the picture logo.py composes from the games' data; and that
picture, pinned by its hash."""
import hashlib
import os
import unittest
from pathlib import Path

from ultima.flash.tcrt import TCRT
from ultima.launcher import launcher
from ultima.launcher import logo
from ultima.flash import regions
from ultima import paths

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
COLOUR = {3: "c", 14: "b", 1: "w"}


class TestLogo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img = TCRT.read(IMAGE)
        prg = regions.launcher_prg(img.flash)
        cls.mem = bytearray(0x10000)
        org = prg[0] | prg[1] << 8
        cls.mem[org:org + len(prg) - 2] = prg[2:]
        cls.sym = launcher.symbols(os.path.join(paths.BUILD, "menu.sym"))
        cls.lg = logo.build()

    def table(self, name, n):
        a = self.sym[name]
        return self.mem[a:a + n]

    def test_the_picture_is_the_one_it_was(self):
        """Ultima V's title less its V, Ultima IV's letter tiles, our P: the
        composition's hash, so that a change to it, or to what it reads, shows."""
        self.assertEqual(hashlib.sha256("\n".join(logo.art()).encode()).hexdigest()[:16],
                         "675f4113d143f699")

    def test_it_is_drawn_as_the_art_says(self):
        s, lg = self.sym, self.lg
        w, h, left = s["LOGO_W"], s["LOGO_H"], s["LOGO_LEFT"]
        scr, col = self.table("logo_scr", w * h), self.table("logo_col", w * h)
        font = self.mem[launcher.FONT_ORG:launcher.FONT_ORG + 2048]
        art = logo.art()
        for y in range(logo.H):
            got = []
            for x in range(logo.W):
                cx, cy = x // 8, y // 8
                ch = "."
                if cy < h and left <= cx < left + w:
                    i = cy * w + cx - left
                    if font[scr[i] * 8 + y % 8] & 0x80 >> (x % 8):
                        ch = COLOUR[col[i]]
                got.append(ch)
            self.assertEqual("".join(got), art[y], f"logo row {y}")

    def test_it_needs_no_sprites(self):
        """The red band behind "Collection" was eight sprites; nothing in the
        menu turns one on now (look_off still clears them for the games)."""
        self.assertNotIn("logo_spr", self.sym)
        src = Path(os.path.join(paths.ASM, "menu.s")).read_text()
        self.assertNotIn("sta $d015", src.replace("stx $d015", ""))

    def test_it_leaves_every_text_character_alone(self):
        """The logo's codes are the reverse half, which the launcher never
        prints, and codes whose place in the font has no glyph (a font built
        from a solid block shows which)."""
        text = launcher.font(bytes([0xFF]) * 1024)
        for code in self.lg["glyphs"]:
            self.assertIn(code, logo.CODES)
            self.assertNotEqual(code, 0x60)         # shifted space
            if code < 0x80:
                self.assertEqual(text[code * 8:code * 8 + 8], bytes(8), f"${code:02x}")


if __name__ == "__main__":
    unittest.main()
