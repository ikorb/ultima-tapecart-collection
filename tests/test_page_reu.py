"""The launcher's REU line on Ultima VI's page (asm/page_reu.s), in py65 with
the REU model (reumodel.py) at $DF00: the page as the image has it, the line
below the saved game --

  * an REU of 256 KB to 16 MB: its size, "for loads and saves";
  * one whose verify reports no difference: "for loads only", and why;
  * 128 KB: "too small to use"; an Action Replay's RAM at $DF00, an open bus,
    no REU: no line at all;
  * only on Ultima VI's page; and every line within the 40 columns;

and that the game's own init agrees (ultima/games/u6/u6reu.s reu_init): with the
broken verify it keeps the read cache and leaves the write cache off (the
resident fetches the plain u6bulk), else parts A and B.

Skipped without py65.
"""
import os
import re
import unittest
from pathlib import Path

try:
    from ultima.sim.sim6502 import Sim
    from tests.reumodel import REU
except ImportError:
    Sim = None

from ultima.launcher import launcher
from ultima.flash import regions
from ultima.sim.screenmodel import Screen
from ultima.flash.tcrt import TCRT
from tests.test_page import IMAGE, launcher_prg, screen
from ultima import paths


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestPageReu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flash = bytes(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cls.image = launcher_prg()
        cls.sym = launcher.symbols()

    def page(self, game="u6", kind=None, kb=512, verify_works=True):
        """The page of `game`, B pressed at once: its screen, as text."""
        sim = Sim(self.image, launcher.FONT_ORG, self.sym)
        sim.attach_cart(bytearray(self.flash))
        if kind:
            self.reu = REU(sim, kind, kb, verify_works=verify_works, strict_io=False)
        out, keys = bytearray(), [ord("B")]
        scr = Screen(sim.mem)

        def getin(s):
            if not keys:
                raise AssertionError("the page wants another key:\n" + screen(out))
            s.mpu.a = keys.pop(0)
            s.mpu.p &= ~0x82

        def chrout(s):
            out.append(s.mpu.a)
            scr.put(s.mpu.a)
        sim.traps[0xFFD2] = chrout
        sim.traps[0xFFF0] = scr.plot
        sim.traps[0xFFE4] = getin
        sim.traps[0xFF9F] = lambda s: None
        sim.mem[0], sim.mem[1] = 0x2F, 0x37
        sim.mem[0x0300:0x0310] = list(b"ULTIMA X".ljust(16, b"\x00"))
        sim.mpu.a, sim.mpu.x, sim.mpu.y = regions.DESC_INDEX[game], 0x00, 0x03
        sim.call(launcher.PAGE_ORG)
        return screen(out)

    def reu_lines(self, text):
        return [l for l in text.splitlines() if "REU" in l or "verify" in l]

    def test_an_reu_its_size_and_both_uses(self):
        for kb in (256, 512, 1024, 2048, 16384):
            with self.subTest(kb=kb):
                text = self.page(kind="reu", kb=kb)
                self.assertEqual(self.reu_lines(text), [f"   REU: {kb} KB, for loads and saves"])
                self.assertTrue(self.reu.verifies, "no verify made")
                self.assertEqual([v[3] for v in self.reu.verifies], [True, False, False],
                                 "the same, then the last byte, then the first")

    def test_a_blank_line_before_it(self):
        """Between the saved game (here: none) and the REU line."""
        lines = self.page(kind="reu", kb=512).splitlines()
        at = next(i for i, line in enumerate(lines) if "REU" in line)
        self.assertEqual((lines[at - 2].strip(), lines[at - 1]), ("No saved game", ""))

    def test_a_broken_verify_is_said(self):
        text = self.page(kind="reu", kb=512, verify_works=False)
        self.assertEqual(self.reu_lines(text), ["   REU: 512 KB, for loads only",
                                                "     its verify command failed"])

    def test_too_small_and_none(self):
        self.assertEqual(self.reu_lines(self.page(kind="reu", kb=128)), ["   REU: 128 KB, too small to use"])
        for kind in ("ar", "none", None):
            with self.subTest(kind=kind):
                self.assertEqual(self.reu_lines(self.page(kind=kind)), [])

    def test_only_on_ultima_vi_s_page(self):
        for g in ("u1", "u4", "u5"):
            with self.subTest(game=g):
                self.assertEqual(self.reu_lines(self.page(g, kind="reu")), [])

    def test_the_lines_fit(self):
        for kb, ok in ((16384, True), (512, False)):
            text = self.page(kind="reu", kb=kb, verify_works=ok)
            for line in self.reu_lines(text):
                self.assertLess(len(line), 40, line)

    def test_it_sits_after_the_menu_and_before_the_export_tables(self):
        ps = launcher.symbols()
        rs = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "page_reu.sym")).read_text())}
        ms = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "menu.sym")).read_text())}
        self.assertLessEqual(ms["menu_end"], ps["REU_ORG"])
        self.assertLessEqual(rs["reu_line_end"], ps["XDATA"])
        self.assertEqual(bytes(self.image[ps["REU_ORG"] - launcher.FONT_ORG:][:4]),
                         Path(os.path.join(paths.BUILD, "page_reu.bin")).read_bytes()[:4])


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestGameAgrees(unittest.TestCase):
    """reu_init's own verify test: the write cache only if verify works."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.find_spec("ultima.games.u6.build")
        cls.u6 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.u6)
        cls.p = cls.u6.parts()
        cls.reusym = cls.u6.symbols(os.path.join(paths.BUILD, "u6reu.sym"))

    def init(self, verify_works):
        u6, p = self.u6, self.p
        sim = Sim(p["game"], u6.GAME_ADDR, p["rsym"])
        sim.attach_cart(bytearray(regions.FLASH_SIZE))
        reu = REU(sim, "reu", 512, verify_works=verify_works)
        sim.mem[u6.INIT_AT:u6.INIT_AT + len(p["init_copy"])] = list(p["init_copy"])
        sim.traps[0x03FC] = lambda s: None
        sim.mem[1] = 0x34
        before = bytes(sim.mem[p["rsym"]["u6_bulkfl"]:p["rsym"]["u6_bulkfl"] + 7])
        sim.call(self.reusym["reu_init"])
        after = bytes(sim.mem[p["rsym"]["u6_bulkfl"]:p["rsym"]["u6_bulkfl"] + 7])
        return sim.mem[self.reusym["rc_on"]], before, after, reu

    def test_verify_works_parts_a_and_b(self):
        on, before, after, reu = self.init(True)
        self.assertEqual(on, 1)
        a = self.p["reua_at"]
        self.assertEqual(after, bytes([a[0xDC00] >> 16, a[0xDC00] >> 8 & 0xFF, a[0xDC00] & 0xFF, 0xFF,
                                       a[0xD800] >> 16, a[0xD800] >> 8 & 0xFF, a[0xD800] & 0xFF]))
        self.assertEqual([v[3] for v in reu.verifies], [True, False, False])

    def test_a_broken_verify_the_read_cache_alone(self):
        on, before, after, reu = self.init(False)
        self.assertEqual(on, 1, "the read cache stays")
        self.assertEqual(after, before, "the write cache was switched on")


if __name__ == "__main__":
    unittest.main()
