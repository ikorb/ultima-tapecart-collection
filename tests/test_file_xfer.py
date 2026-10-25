"""A saved game to and from one file on any disk (asm/page_file.s), on the
host: the page in py65, the KERNAL's I/O on fakedrive.FakeDrive over a blank
disk, the cart on FakeCart.

  * every game's save goes out to "ULTIMA ... SAVE" (a SEQ file) and comes
    back into a fresh cart slot for slot -- Ultima VI's as its write log's
    chunk files and save-area sectors, into a new log half;
  * a second export replaces the file;
  * a damaged, cut-short, another game's or missing file is refused, and
    the cart is left as it was (Ultima VI: the log half in use, too);
  * no drive is reported.

Skipped without py65 (the repository's .venv has it).
"""
import random
import unittest


from tests import test_xfer
from tests import test_u6_xfer
from tests.test_xfer import Sim, blank_d64, RET, Y, N_, B, SPACE
from ultima.sim.fakedrive import Disk
from ultima.launcher.u6log import Log
from ultima.flash import regions
from tests import test_page
from ultima.launcher import u2log

E, I, F = ord("E"), ord("I"), ord("F")
NAMES = {"u1": b"ULTIMA I SAVE", "u2": b"ULTIMA II SAVE", "u3": b"ULTIMA III SAVE",
         "u4": b"ULTIMA IV SAVE", "u5": b"ULTIMA V SAVE", "u6": b"ULTIMA VI SAVE"}


def with_file(name, data, ftype=0x81):
    d = Disk(blank_d64())
    d.write_file(name, data, ftype)
    return bytes(d.data)


def resum(body):
    """body (header included) with its two check bytes."""
    s1 = s2 = 0
    for b in body:
        s1 = (s1 + b) & 255
        s2 = (s2 + s1) & 255
    return bytes(body) + bytes([s1, s2])


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestFileXfer(unittest.TestCase):
    setUpClass = classmethod(test_xfer.TestXfer.setUpClass.__func__)
    run_page = test_xfer.TestXfer.run_page
    xfer = test_xfer.TestXfer.xfer
    seeded = test_xfer.TestXfer.seeded
    slot_bytes = test_xfer.TestXfer.slot_bytes

    def export_file(self, flash, game, disk=None):
        cart, drv = self.run_page(bytearray(flash), game, [E, F, Y, RET, SPACE, B],
                                  disk or blank_d64())
        text = test_page.screen(drv.screen)
        self.assertIn("Done.", text, text[-400:])
        self.assertEqual(bytes(cart.flash), bytes(flash), "an export changed the cart")
        self.assertEqual(drv.disk.file_type(NAMES[game]), 1, "a SEQ file")
        return drv.disk

    def import_file(self, flash, game, disk):
        cart, drv = self.run_page(bytearray(flash), game, [I, F, Y, RET, SPACE, B], disk)
        return cart.flash, test_page.screen(drv.screen)

    def test_a_save_goes_to_a_file_and_back(self):
        for game in test_xfer.DISKS:
            with self.subTest(game=game):
                src = self.seeded(game)
                disk = self.export_file(src, game)
                flash, text = self.import_file(self.fresh, game, bytes(disk.data))
                self.assertIn("Done.", text, text[-400:])
                for xd in self.xfer(game):
                    for sl in xd.slots:
                        self.assertEqual(self.slot_bytes(flash, sl), self.slot_bytes(src, sl),
                                         f"{game} slot at {sl.base:#x}")
                lo, hi = regions.save_region(game)
                if game != "u2":
                    self.assertEqual(bytes(flash[lo:hi]), bytes(src[lo:hi]))
                else:
                    self.assertEqual(u2log.active(flash, lo), (0, 0), "a fresh cart's")

    def test_an_empty_slot_stays_empty(self):
        """Ultima I with one character of four: the other slots go out as
        empty and come back erased."""
        src = self.seeded("u1")
        before = [self.slot_bytes(src, sl) for xd in self.xfer("u1") for sl in xd.slots]
        self.assertIn(None, before, "the seed leaves a slot empty")
        disk = self.export_file(src, "u1")
        flash, _text = self.import_file(self.seeded("u1"), "u1", bytes(disk.data))
        after = [self.slot_bytes(flash, sl) for xd in self.xfer("u1") for sl in xd.slots]
        self.assertEqual(after, before)

    def test_a_second_export_replaces_the_file(self):
        disk = self.export_file(self.seeded("u4"), "u4")
        first = disk.read_file(NAMES["u4"])
        again = self.export_file(self.seeded("u4"), "u4", bytes(disk.data))
        names = [bytes(e[5:21]).rstrip(b"\xa0") for _t, _s, _o, e in again.entries()
                 if e[2] & 0x07]
        self.assertEqual(names, [NAMES["u4"]])
        self.assertEqual(again.read_file(NAMES["u4"]), first)

    def refused(self, game, disk, words):
        flash = self.seeded(game)
        before = bytes(flash)
        after, text = self.import_file(flash, game, disk)
        self.assertIn(words, text, text[-400:])
        self.assertNotIn("Done.", text)
        self.assertEqual(bytes(after), before)

    def test_a_bad_file_is_refused(self):
        good = self.export_file(self.seeded("u3"), "u3").read_file(NAMES["u3"])
        rng = random.Random(3)
        for k in range(8):                      # a byte changed anywhere
            at = rng.randrange(6, len(good))
            bad = bytearray(good)
            bad[at] ^= 1 << rng.randrange(8)
            with self.subTest(at=at):
                self.refused("u3", with_file(NAMES["u3"], bytes(bad)), "The file is damaged.")
        for n in (3, 7, len(good) // 2, len(good) - 1):     # cut short
            with self.subTest(cut=n):
                self.refused("u3", with_file(NAMES["u3"], good[:n]), "The file is")
        self.refused("u3", with_file(NAMES["u3"], good + b"\x00"), "The file is damaged.")
        self.refused("u3", with_file(NAMES["u3"], b"HELLO, WORLD"), "not a saved game file")
        u4 = self.export_file(self.seeded("u4"), "u4").read_file(NAMES["u4"])
        self.refused("u3", with_file(NAMES["u3"], u4), "another game's")
        self.refused("u3", blank_d64(), "62,file not found")
        self.refused("u3", with_file(NAMES["u3"], good, 0x82), "64,file type mismatch")

    def test_the_game_is_its_number(self):
        """The header's game byte is the game's number, 1-6, not the page's
        descriptor index (U3 is index 1, U2 2, U4 3 ...)."""
        for game, number in (("u1", 1), ("u2", 2), ("u3", 3), ("u4", 4), ("u5", 5)):
            with self.subTest(game=game):
                good = self.export_file(self.seeded(game), game).read_file(NAMES[game])
                self.assertEqual(good[4], number)
        # the index in its place: another game's
        u3 = self.export_file(self.seeded("u3"), "u3").read_file(NAMES["u3"])
        self.refused("u3", with_file(NAMES["u3"], resum(u3[:4] + bytes([1]) + u3[5:-2])),
                     "another game's")

    def test_no_drive_is_reported(self):
        for keys in ([E, F, Y, RET, test_xfer.CANCEL, B], [I, F, Y, RET, test_xfer.CANCEL, B]):
            flash = self.seeded("u5")
            before = bytes(flash)
            cart, drv = self.run_page(flash, "u5", keys, None)
            text = test_page.screen(drv.screen)
            self.assertIn("Drive 8 is not there", text)
            self.assertEqual(bytes(cart.flash), before)

    def test_no_export_tables_no_export(self):
        """A cart flashed with only the update image may load the launcher
        at an older, shorter length, without the export tables and the
        page's second piece (page_file.s), which end the PRG: E and I
        refuse, and nothing is read or written."""
        from ultima.launcher import launcher
        flash = self.seeded("u4")
        image = bytearray(self.image)
        self.assertEqual(launcher.symbols()["hi_magic"] + 4 - launcher.FONT_ORG, len(image))
        self.assertEqual(bytes(image[-4:]), b"UCSV")
        x = launcher.symbols()["XDATA"] - launcher.FONT_ORG
        image[x - 200:] = bytes(len(image) - x + 200)       # RAM as it may be
        self.image, keep = bytes(image), self.image
        try:
            for k in (E, I):
                cart, drv = self.run_page(bytearray(flash), "u4", [k, SPACE, B], blank_d64())
                text = test_page.screen(drv.screen)
                self.assertIn("needs the full .tcrt image", text)
                self.assertNotIn("(D)isks", text)
                self.assertEqual(bytes(cart.flash), bytes(flash))
                self.assertIsNone(drv.disk.read_file(NAMES["u4"]))
        finally:
            self.image = keep

    def test_only_d_or_f_answers(self):
        """Other keys at "(D)isks or (F)ile?" are not taken (a bouncing E or
        I must not cancel); RUN/STOP and <- go back."""
        flash = self.seeded("u2")
        cart, drv = self.run_page(bytearray(flash), "u2",
                                  [E, ord("X"), E, test_xfer.CANCEL, I, I, ord("N"), 0x03, B],
                                  blank_d64())
        text = test_page.screen(drv.screen)
        self.assertEqual(text.count("(D)isks"), 2)
        self.assertNotIn("Insert", text)
        self.assertNotIn("(Y/N)", text)
        self.assertEqual(bytes(cart.flash), bytes(flash))

    def test_only_y_or_n_answers(self):
        """The (Y/N) question takes Y or N and nothing else: F bouncing (the
        user's C64 on hardware) used to answer it "no"."""
        flash = self.seeded("u2")
        cart, drv = self.run_page(bytearray(flash), "u2", [E, F, F, ord("X"), N_, B], blank_d64())
        text = test_page.screen(drv.screen)
        self.assertEqual(text.count("(Y/N)"), 1)
        self.assertNotIn("Insert", text)
        self.assertEqual(bytes(cart.flash), bytes(flash))
        # and with Y after the bounce, the export goes ahead
        cart, drv = self.run_page(bytearray(flash), "u2", [E, F, F, Y, RET, SPACE, B], blank_d64())
        text = test_page.screen(drv.screen)
        self.assertIn("Done.", text, text[-400:])
        self.assertIsNotNone(drv.disk.read_file(NAMES["u2"]))
        # RUN/STOP and <- are N
        for k in (0x03, test_xfer.CANCEL):
            cart, drv = self.run_page(bytearray(flash), "u2", [I, F, k, B], blank_d64())
            self.assertNotIn("Insert", test_page.screen(drv.screen))

    def test_another_drive(self):
        """D at a disk prompt: the next drive, 8 to 11 and round, kept in the
        settings page for the next time."""
        D = ord("D")
        flash = self.seeded("u4")
        self.device = 9
        try:
            cart, drv = self.run_page(flash, "u4", [E, F, Y, RET, D, RET, SPACE, B], blank_d64())
            text = test_page.screen(drv.screen)
            self.assertIn("Drive 8 is not there", text)
            self.assertIn("in drive 9 and press RETURN", text)
            self.assertIn("Done.", text, text[-400:])
            self.assertIsNotNone(drv.disk.read_file(NAMES["u4"]))
            self.assertEqual(cart.flash[regions.SETTINGS + 0x10], 9)
            # remembered: an import from it, no D this time
            after, text = self.import_file(self.fresh[:regions.SETTINGS] +
                                           bytes(cart.flash[regions.SETTINGS:]), "u4",
                                           bytes(drv.disk.data))
            self.assertIn("Done.", text, text[-400:])
            self.assertNotIn("not there", text)
            # 9, 10, 11, then 8 again, stored as 0
            cart, drv = self.run_page(bytearray(cart.flash), "u4",
                                      [E, F, Y, D, D, D, test_xfer.CANCEL, B], blank_d64())
            text = test_page.screen(drv.screen)
            for n in (10, 11, 8):
                self.assertIn(f"in drive {n} and press RETURN", text)
            self.assertEqual(cart.flash[regions.SETTINGS + 0x10], 0)
            # the C128 launcher's instructions name the drive
            flash = bytearray(self.fresh)
            flash[regions.SETTINGS:regions.SETTINGS + 256] = cart.flash[regions.SETTINGS:
                                                                        regions.SETTINGS + 256]
            flash[regions.SETTINGS + 0x10] = 10
            self.device = 10
            cart, drv = self.run_page(flash, "u5", [ord("C"), RET, SPACE, B], blank_d64())
            text = test_page.screen(drv.screen)
            self.assertIn('DLOAD"ULTIMA V 128",U10', text, text[-600:])
            self.assertIn("this disk\n in drive 10,", text)
        finally:
            del self.device


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6File(unittest.TestCase):
    setUpClass = classmethod(test_u6_xfer.TestU6Xfer.setUpClass.__func__)
    run_page = test_u6_xfer.TestU6Xfer.run_page
    active = test_u6_xfer.TestU6Xfer.active
    party_only = test_u6_xfer.TestU6Xfer.party_only
    imported = test_u6_xfer.TestU6Xfer.imported

    def export_file(self, flash):
        cart, drv, _d, text = self.run_page(bytearray(flash), [E, F, Y, RET, SPACE, B], blank_d64())
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(cart.flash), bytes(flash), "an export changed the cart")
        return drv.disk

    def import_file(self, flash, disk):
        cart, drv, _d, text = self.run_page(bytearray(flash), [I, F, Y, RET, SPACE, B], disk)
        return cart.flash, text

    def logged_world(self):
        """A log with new versions of some chunk files and of part of the
        save area, as test_u6_xfer's export test makes it."""
        flash = bytearray(self.fresh)
        log = Log(flash, self.lo, self.mid)
        rng = random.Random(6)
        for name in ("SCC", "SDD", "SAA", "DAA"):
            n = rng.randint(1, 7)
            content = rng.randbytes(254 * (n - 1) + rng.randint(1, 254))
            pages = []
            for i in range(n):
                part = content[254 * i:254 * (i + 1)]
                link = bytes([17, i]) if i + 1 < n else bytes([0, len(part) + 1])
                pages.append((link + part).ljust(256, b"\x00"))
            log.append(b"/" + name.encode(), pages, True)
        for s in (9, 12, 13, 20):
            log.append(bytes([1, 0, 6, s]), [rng.randbytes(256)], False)
        log.append(b"/SCC", [bytes([0, 5, 9, 8, 7, 6]).ljust(256, b"\x00")], True)  # a newer one
        return flash

    def test_a_world_goes_to_a_file_and_back(self):
        src = self.logged_world()
        disk = self.export_file(src)
        flash, text = self.import_file(self.fresh, bytes(disk.data))
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(contents_of(self, flash), contents_of(self, src))
        # into an existing log: the other half, which becomes the one in use
        old = self.party_only()
        gen0, base0, _l = self.active(old)
        flash, text = self.import_file(old, bytes(disk.data))
        gen, base, _l = self.active(flash)
        self.assertEqual(gen, gen0 + 1)
        self.assertNotEqual(base, base0)
        self.assertEqual(contents_of(self, flash), contents_of(self, src))

    def test_a_played_world_goes_to_a_file_and_back(self):
        played = {tag: test_u6_xfer.original(tag, test_u6_xfer.PLAYED) for tag in test_u6_xfer.DISKS}
        src, _t = self.imported(self.fresh, played["1A"], played["1B"])
        disk = self.export_file(src)
        flash, text = self.import_file(self.fresh, bytes(disk.data))
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(contents_of(self, flash), contents_of(self, src))

    def test_a_bad_file_leaves_the_log(self):
        src = self.logged_world()
        good = self.export_file(src).read_file(NAMES["u6"])
        self.assertEqual(good[4], 6)                    # the game's number
        old = self.party_only()
        before = self.active(old)
        for bad in (good[:-1], good[:len(good) // 2], good[:-2] + bytes([good[-2] ^ 1, good[-1]]),
                    good[:6] + b"\x03" + good[7:]):
            flash, text = self.import_file(old, with_file(NAMES["u6"], bad))
            self.assertIn("The file is", text, text[-400:])
            self.assertNotIn("Done.", text)
            self.assertEqual(self.active(flash), before)


def contents_of(t, flash):
    return test_u6_xfer.contents(t.active(flash)[2])


if __name__ == "__main__":
    unittest.main()
