"""Ultima VI's shrine level check (ultima/games/u6/u6exp.s, build.py SHRINES): the
Talk overlay's exp() returns experience / 50 instead of its low byte, and
the eight shrines' threshold tables are divided by 50 to match -- checked on
what the cart stores: T4's sector through the block maps, the shrine
conversations through the static directory, and the stored exp() run in
py65.

Skipped without py65 (the repository's .venv has it)."""
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64
from ultima.dialogue import u6_dialogue
from tests import test_u6_compendium as tc
from ultima import paths

u6 = tc.u6


THRESHOLDS = [0, 100, 200, 400, 800, 1600, 3200, 6400]     # the PC's, by level


class TestShrine(unittest.TestCase):
    setUpClass = classmethod(tc.TestCompendium.setUpClass.__func__)
    stored = tc.TestCompendium.stored

    def stored_sector(self, n, t, s):
        m = self.p["maps"][n] + (t * u6.GRID + s) * 4
        a = self.flash[m] | self.flash[m + 1] << 8 | self.flash[m + 2] << 16
        return bytes(self.flash[a:a + 256])

    def test_t4_differs_only_in_exp(self):
        at, n = u6.EXP_ORG & 0xFF, len(u6.EXP_OLD)
        for tag, disk in u6.SECTOR_DISKS.items():
            d = D64(paths.disk("u6-" + tag.lower()))
            for s in range(9, 21):
                with self.subTest(disk=tag, sector=s):
                    got, orig = self.stored_sector(disk, 4, s), bytes(d.sector(4, s))
                    if s != u6.EXP_SECTOR:
                        self.assertEqual(got, orig)
                        continue
                    self.assertEqual(orig[at:at + n], u6.EXP_OLD)
                    self.assertEqual(got[:at], orig[:at])
                    self.assertEqual(got[at + n:], orig[at + n:])
                    self.assertNotEqual(got[at:at + n], orig[at:at + n])

    def test_the_shrines_tables(self):
        disk = D64(paths.disk("u6-3a"))

        for name in u6.SHRINES:
            with self.subTest(name=name):
                data, orig = self.stored(name), disk.file(name)[0]
                self.assertEqual(data[:-8], orig[:-8])
                self.assertEqual(orig[-8:], u6.SHRINE_OLD)
                self.assertEqual(data[-8:], u6.SHRINE_NEW)
                _items, bad = u6_dialogue.Script(data, {}).decode()
                self.assertEqual(bad, [])

    def test_the_check_is_the_pcs(self):
        """exp / 50 (at most 199) >= the new table's entry, unsigned, exactly
        when experience >= the PC's threshold, at every level."""
        for level in range(8):
            for xp in range(10000):
                self.assertEqual(min(xp // 50, 199) >= u6.SHRINE_NEW[level],
                                 xp >= THRESHOLDS[level], (level, xp))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_exp_runs_as_documented(self):
        """The stored code: experience += delta (16-bit), the result slot
        gets min(exp / 50, 199), $F2 is popped and $9D counted; a character
        with no stat slot is left alone."""
        sim = Sim(self.stored_sector(0, 4, u6.EXP_SECTOR), 0xC600, {})

        def actor(s):                   # $CA99: Y = the actor ($EB: self)
            s.mpu.y = s.mpu.a

        def slot(s):                    # $02F0: the named characters 1-15
            if 1 <= s.mpu.y <= 15:
                s.mpu.y -= 1
                s.mpu.p |= 1
            else:
                s.mpu.p &= ~1
        sim.traps[0xCA99] = actor
        sim.traps[0x02F0] = slot
        m = sim.mem
        cases = [(x, 0) for x in list(range(0, 10000, 7)) + [49, 50, 99, 255, 256, 9949,
                                                             9950, 9999]]
        cases += [(1234, 5), (250, 6), (9990, 9), (65000, 200), (40000, 0)]
        for who in (1, 3, 15):
            for xp, delta in cases:
                with self.subTest(actor=who, xp=xp, delta=delta):
                    sl = who - 1
                    m[0x585B + 2 * sl], m[0x585C + 2 * sl] = xp & 0xFF, xp >> 8
                    m[0xF2], m[0x9D] = 0x10, 0x40
                    m[0xD553 + 0x10], m[0xD554 + 0x10] = who, delta
                    sim.mpu.x = 0x10
                    sim.call(0xC650)
                    new = (xp + delta) & 0xFFFF
                    self.assertEqual(m[0x585B + 2 * sl] | m[0x585C + 2 * sl] << 8, new)
                    self.assertEqual(m[0xD553 + 0x10], min(new // 50, 199))
                    self.assertEqual((m[0xF2], m[0x9D]), (0x0F, 0x41))
        m[0x585B:0x587A] = [0x5A] * 31
        m[0xF2] = 0x10
        m[0xD553 + 0x10] = 200
        sim.mpu.x = 0x10
        sim.call(0xC650)
        self.assertEqual(list(m[0x585B:0x587A]), [0x5A] * 31, "a stranger's has no slot")


if __name__ == "__main__":
    unittest.main()
