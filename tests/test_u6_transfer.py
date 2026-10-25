"""Ultima VI's transfer of the Avatar from Ultima IV or V (asm/page_u6t.s,
and its other half in asm/init_u6.s), on the host.

The page: offered only for a new Avatar (level 3, 370 experience, as
character creation leaves it), the PC's rules (experience / 10 with the
last digit dropped, attributes halved from IV and kept from V) with
creation's values as the floor, and the result as pokes into the boot's
transfer block next to Journey Onward's.  The boot: it writes exactly those
fields into the newest S12 and S13, as a save would, also after compacting
a full log.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
import random
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.launcher.u6log import Log, RESERVE, play, view
from ultima.flash.layout import image_from
from ultima.flash import regions

from tests import test_page
from tests.test_page import seed_u4, seed_u5, seed_u6
from ultima import paths

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

KEY_T, KEY_4, KEY_5, KEY_Y, KEY_N, KEY_B = (ord(c) for c in "T45YNB")
S12, S13 = bytes([1, 0, 6, 12]).ljust(12, b"\x00"), bytes([1, 0, 6, 13]).ljust(12, b"\x00")


def bcd(n):
    return (n // 10) << 4 | n % 10


def expected(strength, dex, intel, xp):
    """What the page should make of converted attributes and experience."""
    xp = max(xp, 370)
    level = 3 + (xp >= 400) + (xp >= 800)
    return [level, strength, dex, intel, 30 * level, 2 * intel, xp & 0xFF, xp >> 8]


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestTransferPage(unittest.TestCase):
    run_page = test_page.TestPage.run_page

    @classmethod
    def setUpClass(cls):
        test_page.TestPage.setUpClass.__func__(cls)
        cls.xf = cls.s["U6_XF"]

    def seeded(self, u4=True, u5=True, u6=True):
        flash = bytearray(self.fresh)
        if u4:
            seed_u4(flash, self.s)
        if u5:
            seed_u5(flash, self.s)
        if u6:
            seed_u6(flash, self.s)
        return flash

    def pokes(self, sim):
        p = sim.mpu.x | sim.mpu.y << 8
        n = sim.mem[p]
        return [(sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8, sim.mem[p + 3 + 3 * i])
                for i in range(n)]

    def transfer_pokes(self, sim):
        """The eight transfer values, checked to be at U6_XF.. in order."""
        got = [pk for pk in self.pokes(sim) if self.xf <= pk[0] < self.xf + 8]
        self.assertEqual([a for a, _v in got], list(range(self.xf, self.xf + 8)))
        return [v for _a, v in got]

    def test_offered_for_a_new_avatar_only(self):
        _sim, _cart, text = self.run_page(self.seeded(), "u6", [KEY_B])
        self.assertIn("T  Transfer from Ultima IV or V", text)
        # no Ultima VI game yet: nothing to transfer into, and T does nothing
        sim, _cart, text = self.run_page(self.seeded(u6=False), "u6", [KEY_T, KEY_B])
        self.assertNotIn("Transfer", text)
        self.assertEqual(sim.mpu.p & 1, 1)
        # an Avatar who has gained experience is no longer new
        flash = self.seeded()
        lo = self.s["U6_LO"]
        log = Log(flash, lo, self.s["U6_MID"], logdir=self.s["U6_MID"] - 12 * 20,
                  logdata=lo + 12 * 256)
        s13 = bytearray(flash[lo + 4 * 256:lo + 5 * 256])      # S13, the fifth
        s13[0x5B] = 0x73
        log.append(S13[:4], [bytes(s13)], False)
        _sim, _cart, text = self.run_page(flash, "u6", [KEY_B])
        self.assertIn("Dupre", text)
        self.assertNotIn("Transfer", text)
        # and the other games' pages never offer it
        _sim, _cart, text = self.run_page(self.seeded(), "u5", [KEY_B])
        self.assertNotIn("Transfer", text)

    def test_from_ultima_iv(self):
        """The played U4 Avatar: STR 19, DEX 22, INT 25, experience 125 --
        halved, and experience 12, so creation's 370 and level 3."""
        sim, _cart, text = self.run_page(self.seeded(), "u6", [KEY_T, KEY_4, KEY_Y])
        self.assertEqual(sim.mpu.p & 1, 0, "not launched")
        last = text.split("<CLR>")[-1]
        self.assertRegex(last, r"4  AVATAR +level 2\n")
        self.assertRegex(last, r"5  tester +level 2\n")
        self.assertEqual(self.transfer_pokes(sim), expected(9, 11, 12, 12))
        # Journey Onward's own pokes come along
        jo = [pk for pk in self.pokes(sim) if not self.xf <= pk[0] < self.xf + 8]
        self.assertEqual([a for a, _v in jo], [0xC025, 0xC026])

    def test_from_ultima_v(self):
        """tester: STR 20, DEX 23, INT 18 kept, experience 150 -> 15 -> 370."""
        sim, _cart, text = self.run_page(self.seeded(), "u6", [KEY_T, KEY_5, KEY_Y])
        self.assertEqual(self.transfer_pokes(sim), expected(20, 23, 18, 15))
        self.assertIn("Intellect   18", text)

    def test_experience_sets_the_level(self):
        """/10 with the last digit dropped: 4009 -> 400 (level 4), 9999 ->
        999 (level 5), 8000 -> 800 (level 5), 3999 -> 399 (level 3)."""
        for xp, want in ((4009, 400), (9999, 999), (8000, 800), (3999, 399)):
            with self.subTest(xp=xp):
                flash = self.seeded(u4=False)
                r = self.s["U5_ROSTER"] + 0x100 + 0x80
                flash[r + 0xC:r + 0xE] = bytes([bcd(xp // 100), bcd(xp % 100)])
                sim, _cart, _text = self.run_page(flash, "u6", [KEY_T, KEY_5, KEY_Y])
                self.assertEqual(self.transfer_pokes(sim), expected(20, 23, 18, want))

    def test_attributes_are_kept_within_one_to_thirty(self):
        flash = self.seeded(u5=False)
        r = regions.save_base("u4") + 2 * 0x1000         # block 273, record 0
        self.assertEqual(r, self.s["U4_ROSTER"])
        flash[r + 0x13:r + 0x16] = bytes([0x50, 0x01, 0x00])    # 50, 1, 0
        sim, _cart, _text = self.run_page(flash, "u6", [KEY_T, KEY_4, KEY_Y])
        self.assertEqual(self.transfer_pokes(sim)[1:4], [25, 1, 1])
        flash = self.seeded(u4=False)
        r = self.s["U5_ROSTER"] + 0x100 + 0x80
        flash[r + 4:r + 7] = bytes([0x30, 0x45, 0x00])          # 30, 45, 0
        sim, _cart, _text = self.run_page(flash, "u6", [KEY_T, KEY_5, KEY_Y])
        self.assertEqual(self.transfer_pokes(sim)[1:4], [30, 30, 1])

    def test_nothing_to_transfer_from(self):
        sim, cart, text = self.run_page(self.seeded(u4=False, u5=False), "u6",
                                        [KEY_T, KEY_Y, KEY_B])
        self.assertIn("There is no saved game of", text)
        self.assertEqual(sim.mpu.p & 1, 1)
        self.assertFalse([c for c in cart.log if c[0] in ("erase", "write")])

    def test_a_game_without_an_avatar_cannot_be_picked(self):
        sim, _cart, text = self.run_page(self.seeded(u4=False), "u6", [KEY_T, KEY_4, KEY_B])
        self.assertNotIn("4  AVATAR", text)
        self.assertEqual(sim.mpu.p & 1, 1, "4 picked a game that has no Avatar")

    def test_no_writes_and_no_transfer_unless_confirmed(self):
        """N goes back to the page; a plain Journey Onward after that pokes
        no transfer.  The page itself never writes anything for it."""
        sim, cart, _text = self.run_page(self.seeded(), "u6", [KEY_T, KEY_5, KEY_N, ord("J")])
        self.assertEqual(sim.mpu.p & 1, 0)
        self.assertFalse([pk for pk in self.pokes(sim) if self.xf <= pk[0] < self.xf + 8])
        self.assertFalse([c for c in cart.log if c[0] in ("erase", "write")])


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestTransferBoot(unittest.TestCase):
    """init_u6.s writes the poked Avatar into S12 and S13."""

    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        cls.isym = u6.symbols(os.path.join(paths.BUILD, "init_u6.sym"))

    def boot(self, flash, values):
        sim = Sim(self.p["boot_image"], 0xC000, self.p["bsym"])
        sim.mem[0xC578:0xC578 + len(self.p["boot_piece2"])] = list(self.p["boot_piece2"])
        sim.mem[u6.INIT_ADDR:u6.INIT_ADDR + len(self.p["init"])] = list(self.p["init"])
        if values:
            a = self.isym["xf_lvl"]
            sim.mem[a:a + 8] = list(values)
        cart = sim.attach_cart(flash)
        # init_u6's own 2-bit receive (g_read): the cart model answers it
        # as the boot driver's 1-bit one
        sim.traps[self.isym["tc_getbyte_guard"]] = sim.traps[self.p["bsym"]["tc_getbyte"]]
        sim.traps[0xC00C] = lambda s: None
        sim.mem[0x01] = 0x35
        sim.call(u6.INIT_ADDR)
        return sim, cart

    def u24(self, sim, name):
        a = self.p["bsym"][name]
        return sim.mem[a] | sim.mem[a + 1] << 8 | sim.mem[a + 2] << 16

    def logged(self, sim, cart):
        a = self.p["bsym"]["u6_dircount"]
        return view(cart.flash, self.u24(sim, "u6_logdir"), sim.mem[a] | sim.mem[a + 1] << 8)

    def seeded(self):
        """The played Surface disk's save area in the log, as page tests have it."""
        flash = bytearray(self.flash)
        lo, hi = self.p["log"]
        seed_u6(flash, dict(U6_LO=lo, U6_MID=lo + (hi - lo) // 2))
        return flash

    def check(self, before, after, values):
        lvl, st, dx, it, hp, mp, xl, xh = values
        s12, s13 = bytearray(before[S12]), bytearray(before[S13])
        for off, v in ((0x8C, st), (0xA3, dx), (0xBA, lvl), (0xD1, it), (0xE8, hp), (0xFF, hp)):
            s12[off] = v
        for off, v in ((0x44, mp), (0x5B, xl), (0x5C, xh)):
            s13[off] = v
        self.assertEqual(after[S12], bytes(s12))
        self.assertEqual(after[S13], bytes(s13))
        for k in before:
            if k not in (S12, S13):
                self.assertEqual(after[k], before[k], k)

    def test_the_avatar_goes_into_the_save_area(self):
        values = [4, 25, 22, 30, 120, 60, 0xC2, 0x01]
        flash = self.seeded()
        sim0, cart0 = self.boot(bytearray(flash), None)
        before = self.logged(sim0, cart0)
        sim, cart = self.boot(flash, values)
        after = self.logged(sim, cart)
        self.check(before, after, values)
        # two pages and two entries more, where the driver's variables say
        self.assertEqual(self.u24(sim, "u6_logdata"), self.u24(sim0, "u6_logdata") + 0x200)
        self.assertEqual(self.u24(sim, "u6_logdir"), self.u24(sim0, "u6_logdir") - 40)

    def test_without_the_pokes_nothing_is_written(self):
        flash = self.seeded()
        sim, cart = self.boot(flash, None)
        self.assertFalse([c for c in cart.log if c[0] in ("erase", "write")])

    def test_after_a_compaction(self):
        """A log with too little room left: the boot compacts it into the
        other half first, then the Avatar goes in there."""
        lo, hi = self.p["log"]
        flash = bytearray(self.flash)
        log = Log(flash, lo, lo + (hi - lo) // 2)
        want = {}
        play(log, random.Random(6), want, RESERVE - 20)
        values = [5, 30, 30, 30, 150, 60, 0xE7, 0x03]
        sim, cart = self.boot(flash, values)
        self.assertGreaterEqual(self.u24(sim, "u6_logdir"), lo + (hi - lo) // 2,
                                "not compacted into the other half")
        self.check(want, self.logged(sim, cart), values)


if __name__ == "__main__":
    unittest.main()
