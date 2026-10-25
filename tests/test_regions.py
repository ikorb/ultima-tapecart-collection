import unittest

from ultima.flash import regions


class TestRegions(unittest.TestCase):
    def test_no_region_overlaps(self):
        self.assertEqual(regions.overlaps(), [])

    def test_everything_fits_the_flash(self):
        data = dict(regions.DATA)
        for name, (db, dl, sb, sl) in regions.REGIONS.items():
            with self.subTest(game=name):
                if name in data:
                    self.assertLess(db, dl)
                if name in dict(regions.SAVES):
                    self.assertLess(sb, sl)
                self.assertLessEqual(sl, regions.FLASH_SIZE)

    def test_regions_are_erase_block_aligned(self):
        """A save slot is a whole erase block, so writing one must never touch
        a neighbour -- that is the only alignment the drivers need.  Game
        data is only ever read, and rewritten whole by an update image: its
        regions are whole pages, as every unit in them starts on one."""
        for name, (db, dl, sb, sl) in regions.REGIONS.items():
            with self.subTest(game=name):
                for addr in (sb, sl):
                    self.assertEqual(addr % regions.ERASE_BLOCK, 0, name)
                for addr in (db, dl):
                    self.assertEqual(addr % regions.PAGE, 0, name)
        self.assertEqual(regions.SAVE_AREA % regions.ERASE_BLOCK, 0)

    def test_data_tiles_up_and_saves_tile_down(self):
        """Data regions tile upward from the reserved area with no gaps, so
        reclaiming space in one game moves the free space rather than
        stranding it; save regions tile downward from the top of flash."""
        cursor = regions.RESERVED
        for name, _size in regions.DATA:
            db, dl, _sb, _sl = regions.REGIONS[name]
            self.assertEqual(db, cursor, name)
            cursor = dl
        self.assertEqual(cursor, regions.DATA_END)
        top = regions.FLASH_SIZE
        for name, _size in regions.SAVES:
            _db, _dl, sb, sl = regions.REGIONS[name]
            self.assertEqual(sl, top, name)
            top = sb
        self.assertEqual(top, regions.SAVE_AREA)
        self.assertEqual(regions.free(), regions.SAVE_AREA - regions.DATA_END)

    # Where each game's saves live on a flashed cart.  A new build is flashed
    # with the update image, which keeps everything from SAVE_AREA up -- so
    # these must NEVER change: a save moved is a save lost.  U6's region is
    # pinned by its top only; it may grow downward.  If one ever has to move,
    # raise regions.LAYOUT: the layout stamp tells a cart flashed with the
    # update image that it needs the full .tcrt.
    PINNED = {"u1": 0x1F8000, "u3": 0x1EC000, "u2": 0x1E4000,
              "u4": 0x1DE000, "u5": 0x1D7000}
    JOURNALS = {"u1": (0x1FE000, 0x1000), "u3": (0x1F6000, 0x2000),
                "u4": (0x1E3000, 0x1000), "u5": (0x1DD000, 0x1000)}

    def test_journals_never_move(self):
        """A journal a power cut left is copied by the first stage of the
        build that is on the cart then: it must be where the driver put it."""
        for name, where in self.JOURNALS.items():
            self.assertEqual(regions.journal(name), where, name)
            base, size = where
            lo, hi = regions.save_region(name)
            self.assertEqual(base + size, hi, "the journal ends its region")

    def test_the_first_stage_never_moves(self):
        """The loadinfo is only written by a full flash: these are what it says."""
        self.assertEqual((regions.BOOT_PRG, regions.BOOT_LEN, regions.BOOT_ORG,
                          regions.LAUNCHER_LOC), (0x000800, 0x800, 0x1000, 0x0000F8))
        self.assertLessEqual(regions.BOOT_PRG + regions.BOOT_LEN, regions.MENU_PRG)
        self.assertLess(regions.LAUNCHER_LOC + 5, regions.DESC_BASE)

    def test_save_addresses_never_move(self):
        for name, base in self.PINNED.items():
            self.assertEqual(regions.save_base(name), base, name)
        self.assertEqual(regions.REGIONS["u6"][3], self.PINNED["u5"])

    def test_data_regions_clear_the_reserved_area(self):
        for name, _size in regions.DATA:
            self.assertGreaterEqual(regions.data_base(name), regions.RESERVED, name)

    def test_descriptor_pages_are_distinct_and_inside_the_reserved_area(self):
        """The first six below the C128 page and the first stage; the rest
        (Akalabeth's) at the top of the reserved area, above the launcher's
        PRG (MENU_PRG_END, which ultima/build.py holds it to)."""
        seen = set()
        for game in regions.DESC_INDEX:
            off = regions.desc_offset(game)
            self.assertNotIn(off, seen)
            seen.add(off)
            self.assertLess(off, regions.RESERVED)
            self.assertEqual(off % regions.PAGE, 0)
            self.assertTrue(off < regions.C128_DESC or off >= regions.MENU_PRG_END, game)
        self.assertGreater(regions.MENU_PRG_END, regions.MENU_PRG)

    def test_the_c128_page_never_moves(self):
        """Ultima V's C128 launcher is on the player's disk and reads what to
        load from this page: moved, every disk written before stops working.
        So it is pinned, clear of the games' pages and below the menu."""
        self.assertEqual(regions.C128_DESC, 0x000700)
        self.assertNotIn(regions.C128_DESC, [regions.desc_offset(g) for g in regions.DESC_INDEX])
        self.assertLessEqual(regions.C128_DESC + regions.PAGE, regions.BOOT_PRG)
        self.assertEqual(regions.SETTINGS, 0x1FF000, "the launcher reads the settings too")

    def test_the_launchers_settings_are_the_top_block_and_no_save_slot(self):
        """Above SAVE_AREA, so an update image keeps them; inside U1's
        region, whose six slots and journal end below it (regions.check)."""
        self.assertEqual(regions.SETTINGS, regions.FLASH_SIZE - regions.ERASE_BLOCK)
        self.assertGreaterEqual(regions.SETTINGS, regions.SAVE_AREA)
        self.assertEqual(regions.save_region("u1"), (0x1F8000, regions.SETTINGS))
        with self.assertRaises(SystemExit):
            regions.check("u1", regions.data_base("u1"), regions.SETTINGS + 1)

    def test_check_rejects_an_oversized_game(self):
        db, dl, sb, sl = regions.REGIONS["u1"]
        with self.assertRaises(SystemExit):
            regions.check("u1", dl + 1, sl)
        with self.assertRaises(SystemExit):
            regions.check("u1", dl, sl + 1)


if __name__ == "__main__":
    unittest.main()
