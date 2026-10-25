"""Checks on the combined cartridge image."""
import os
import re
import subprocess
import sys
import unittest

from ultima.flash.tcrt import TCRT
from ultima.launcher import launcher
from ultima.flash import regions

# Take the game list from the builder rather than repeating it -- a second
# copy here just means one more place to forget when a game lands.
import importlib.util
from pathlib import Path
from ultima import paths
_spec = importlib.util.find_spec("ultima.build")
_build_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build_all)

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
GAMES = _build_all.GAMES


class TestCollection(unittest.TestCase):
    def menu_org(self):
        """Where asm/menu.s says it lives."""
        src = Path(os.path.join(paths.ASM, "menu.s")).read_text()
        m = re.search(r"^MENU_ORG\s*=\s*\$([0-9a-fA-F]+)", src, re.M)
        self.assertIsNotNone(m, "MENU_ORG not found in menu.s")
        return int(m.group(1), 16)

    def menu_end(self):
        """Where the menu ends: what follows it in the PRG is the page's (U6's
        REU line, the export tables, the page's second piece), done with by
        the time the menu loads a game."""
        return {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            Path(os.path.join(paths.BUILD, "menu.sym")).read_text())}["menu_end"]

    def test_no_game_segment_lands_on_the_menu(self):
        """The menu is still running its load loop while the segments arrive,
        so none of them may overlap it.  This is not hypothetical: the menu
        used to live at $C600 and Ultima 2's INTRO segment ($C000-$CFFF)
        landed on top of it."""
        # (the font, the page, U6's REU line, the export tables and the
        # page's second piece come in the same PRG and may be loaded over:
        # the page is done by then)
        org = self.menu_org()
        length = self.menu_end() - org
        for game in GAMES:
            d = self.flash[regions.desc_offset(game):regions.desc_offset(game) + 64]
            for i in range(d[2]):
                o = 3 + 7 * i
                dest = d[o + 4] | d[o + 5] << 8
                size = d[o + 2] | d[o + 3] << 8
                self.assertTrue(dest + size <= org or dest >= org + length,
                                f"{game} loads ${dest:04x}-${dest + size - 1:04x} "
                                f"over the menu at ${org:04x}-${org + length - 1:04x}")

    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "-m", "ultima.build"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.img = TCRT.read(IMAGE)
        cls.flash = cls.img.flash

    def test_loadinfo_points_at_the_first_stage(self):
        """Fixed for good: the first stage, BOOT_LEN bytes, called at its
        origin -- an update image cannot change the loadinfo."""
        self.assertEqual((self.img.data_address, self.img.data_length, self.img.call_address),
                         (regions.BOOT_PRG, regions.BOOT_LEN, regions.BOOT_ORG))
        boot = self.flash[regions.BOOT_PRG:regions.BOOT_PRG + regions.BOOT_LEN]
        self.assertEqual(boot[0] | boot[1] << 8, regions.BOOT_ORG)
        self.assertEqual(boot[2], 0x4C, "the first stage does not start with a JMP")
        # the initial loader's data address and length are 16-bit
        self.assertLessEqual(self.img.data_address + self.img.data_length, 0x10000)

    def test_the_banner_says_what_build_it_is(self):
        """A release build says "Version x" (the Makefile's VERSION, no date)
        over an empty line; one built with a debug switch
        (U5_SAVE_FROM) says so on that line, in red -- one line more would
        scroll the list into the logo."""
        import importlib.util
        spec = importlib.util.find_spec("ultima.build")
        ba = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ba)
        pet = lambda t: bytes(ord(c) - 0x20 if "a" <= c <= "z" else ord(c) + 0x80 if "A" <= c <= "Z"
                              else ord(c) for c in t)
        prg = regions.launcher_prg(self.flash)
        if os.environ.get("U5_SAVE_FROM") is None:
            self.assertIn(pet(f"    Version {ba.version()}") + b"\r", prg)
            self.assertNotIn(pet("DEBUG"), prg)
        frag = ba.banner_fragment(["U5 seed"], "9.9")
        self.assertIn('28,"    DEBUG, do not flash: U5 seed",5', frag)
        self.assertIn('"    Version 9.9",', frag)
        self.assertEqual(frag.count("13,"), 1, "two lines, as before")
        self.assertTrue(ba.banner_fragment([], "9.9").rstrip().endswith(",13"), "the second line empty")

    def test_the_settings_page_is_stamped(self):
        s = self.flash[regions.SETTINGS:regions.SETTINGS + 256]
        self.assertEqual(s[:4], regions.SET_MAGIC)
        self.assertEqual(s[regions.SET_LAYOUT], regions.LAYOUT)
        self.assertEqual(set(s[4:regions.SET_LAYOUT]) | set(s[regions.SET_LAYOUT + 1:]), {0})

    def test_menu_prg_load_address_is_where_the_menu_expects(self):
        """One PRG: the font at $4800, the page at $5000, the menu at its
        origin -- called there."""
        prg = regions.launcher_prg(self.flash)
        self.assertEqual(prg[0] | prg[1] << 8, launcher.FONT_ORG)
        org = self.menu_org()
        self.assertEqual(org, launcher.MENU_ORG)
        self.assertLess(org, launcher.FONT_ORG + len(prg) - 2)

    def test_game_list(self):
        table = self.flash[regions.MENU_TABLE:regions.MENU_TABLE + 128]
        self.assertEqual(table[0], len(GAMES))
        names = []
        for i in range(table[0]):
            o = 1 + i * regions.MENU_RECORD
            raw = table[o:o + regions.MENU_NAME_LEN].split(b"\x00")[0]
            # mixed-case PETSCII for the launcher's lower-case font
            names.append("".join(chr(b + 0x20) if 0x41 <= b <= 0x5A else
                                 chr(b - 0x80) if 0xC1 <= b <= 0xDA else chr(b) for b in raw))
            self.assertEqual(table[o + regions.MENU_NAME_LEN], regions.DESC_INDEX[GAMES[i]])
            # the descriptor's flash page, which the menu reads it from
            self.assertEqual(table[o + regions.MENU_NAME_LEN + 1] << 8,
                             regions.desc_offset(GAMES[i]))
        roman = {"u1": "I", "u2": "II", "u3": "III", "u4": "IV", "u5": "V", "u6": "VI"}
        # a game's place in the list is its key: 0 Akalabeth, 1-6 Ultima I-VI
        self.assertEqual(names, ["Akalabeth"] + [f"Ultima {roman[g]}" for g in GAMES[1:]])

    def test_every_descriptor_is_present_and_sane(self):
        for game in GAMES:
            with self.subTest(game=game):
                d = self.flash[regions.desc_offset(game):regions.desc_offset(game) + 64]
                entry = d[0] | d[1] << 8
                # the init stub, at $0200 -- except U6's, which compacts the
                # write log and needs room for buffers ($1000), U1's, which
                # carries tc_init (TC_INIT_ELSEWHERE) and would reach page
                # 2's KERNAL variables ($C700, where MA goes later), and
                # Akalabeth's, in the tape buffer up to its trainer's flags
                self.assertEqual(entry, {"u6": 0x1000, "u1": 0xC700, "u0": 0x0334}.get(game, 0x0200),
                                 "entry should be the init stub")
                self.assertGreater(d[2], 0)
                dests = []
                for n in range(d[2]):
                    o = 3 + 7 * n
                    off = d[o] << 8 | d[o + 1] << 16
                    length = d[o + 2] | d[o + 3] << 8
                    dests.append(d[o + 4] | d[o + 5] << 8)
                    self.assertGreater(length, 0)
                    self.assertLessEqual(off + length, len(self.flash))
                self.assertIn(entry, dests, "the init stub must be loaded")

    def test_no_segment_overwrites_the_menu(self):
        """The menu stays resident while it scatter-loads, so nothing it
        loads may land on top of it."""
        menu_lo = self.menu_org()                   # (the rest of the PRG, the
        menu_hi = self.menu_end()                   # page's, may be loaded over)
        for game in GAMES:
            d = self.flash[regions.desc_offset(game):regions.desc_offset(game) + 64]
            for n in range(d[2]):
                o = 3 + 7 * n
                dest = d[o + 4] | d[o + 5] << 8
                end = dest + (d[o + 2] | d[o + 3] << 8)
                with self.subTest(game=game, dest=hex(dest)):
                    self.assertFalse(dest < menu_hi and end > menu_lo,
                                     f"segment ${dest:04x}-${end:04x} overlaps the "
                                     f"menu at ${menu_lo:04x}-${menu_hi:04x}")

    def test_the_menu_clears_u5s_c128_probe(self):
        """xyzzy takes a $4C at $C024 for the C128's editor ROM; on a C64
        that is RAM, which a reset leaves as the last game had it, and U5 then
        takes its C128 path and crashes (after U6, for one).  The menu stores a known value there before the segments, and
        none of U5's lands on it, so xyzzy sees the menu's."""
        prg = regions.launcher_prg(self.flash)
        menu = prg[2 + self.menu_org() - launcher.FONT_ORG:]
        self.assertIn(bytes.fromhex("8d24c0"), menu, "no STA $C024 in the menu")
        d = self.flash[regions.desc_offset("u5"):regions.desc_offset("u5") + 64]
        dests = [d[3 + 7 * n + 4] | d[3 + 7 * n + 5] << 8 for n in range(d[2])]
        self.assertTrue(dests)
        for dest in dests:
            self.assertFalse(0xC000 <= dest <= 0xC024, f"a U5 segment at ${dest:04x}")
        self.assertLess(max(dests), 0xC000, f"U5's segments: {[hex(x) for x in dests]}")

    def test_image_fits_the_flash(self):
        self.assertLessEqual(len(self.flash), regions.FLASH_SIZE)

    def test_reserved_area_is_not_encroached(self):
        for game in GAMES:
            self.assertGreaterEqual(regions.data_base(game), regions.RESERVED)
        self.assertLessEqual(regions.MENU_PRG + len(regions.launcher_prg(self.flash)),
                             regions.MENU_PRG_END)

    def test_the_first_stage_loads_the_whole_launcher(self):
        """The first stage loads the whole PRG -- font, page, menu, the
        page's export tables and its second piece -- through the locator, so
        picking a game loads nothing, and starts it at the menu's origin,
        where a JMP leads to start."""
        loc = self.flash[regions.LAUNCHER_LOC:regions.LAUNCHER_LOC + 5]
        self.assertEqual(int.from_bytes(loc[:3], "little"), regions.MENU_PRG)
        prg = regions.launcher_prg(self.flash)
        self.assertLessEqual(regions.MENU_PRG + len(prg), regions.MENU_PRG_END)
        o = launcher.MENU_ORG - launcher.FONT_ORG + 2
        self.assertEqual(prg[o], 0x4C, "the menu does not start with a JMP")
        page = Path(os.path.join(paths.BUILD, "page.bin")).read_bytes()
        p = launcher.PAGE_ORG - launcher.FONT_ORG + 2
        self.assertEqual(prg[p:p + len(page)], page, "the page is not in the PRG")
        # and the page's export tables after the menu, up to XDATA_END, and
        # the page's second piece from there, loaded with the rest
        xdata = Path(os.path.join(paths.BUILD, "xdata.bin")).read_bytes()
        x = launcher.symbols()["XDATA"] - launcher.FONT_ORG + 2
        self.assertEqual(prg[x:x + len(xdata)], xdata, "the export tables are not in the PRG")
        self.assertLessEqual(launcher.symbols()["XDATA"] + len(xdata), launcher.XDATA_END)
        hi = Path(os.path.join(paths.BUILD, "page_hi.bin")).read_bytes()
        h = launcher.XDATA_END - launcher.FONT_ORG + 2
        self.assertTrue(hi)
        self.assertEqual(prg[h:], hi, "the page's second piece does not end the PRG")

    def test_update_image_stops_below_the_saves(self):
        path = os.path.join(paths.BUILD, "ultima-collection-update.bin")
        update = Path(path).read_bytes()
        self.assertLessEqual(len(update), regions.SAVE_AREA)
        self.assertEqual(update, bytes(self.flash[:len(update)]))
        # and everything the games load lies inside it
        for game in GAMES:
            self.assertLessEqual(regions.REGIONS[game][1], regions.SAVE_AREA)


if __name__ == "__main__":
    unittest.main()
