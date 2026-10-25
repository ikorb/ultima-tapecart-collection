"""Ultima I's dungeon plans (ultima/maps/u1maps.py Dungeons) against DN's own
generator: $8FAA run under py65 to $90E3, where it has built the level at
$B407 and goes on to place the monsters, for every dungeon's ten levels.  ST's
generator ($1670, which picks chest or coffin) is a stub that makes it one,
then the other.

Skipped when py65 is not importable; `make test` uses the repository's .venv,
which has it.
"""
import unittest

try:
    from py65.devices.mpu6502 import MPU
except ImportError:                             # no py65 outside the venv
    MPU = None

from ultima.maps import u1maps

GENERATE, BUILT, LEVEL_AT = 0x8FAA, 0x90E3, 0xB407


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestU1Dungeons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dn = u1maps.prg("dn.prg")
        cls.gen = u1maps.Dungeons()
        world = u1maps.continents()
        cls.dungeons = [(i, c, x, y) for i, _n, c, x, y in u1maps.places()
                        if world[c][y * 64 + x] == 7]

    def run_dn(self, index, x, y, continent, n, box):
        cpu = MPU()
        mem = cpu.memory
        mem[u1maps.OVERLAY:u1maps.OVERLAY + len(self.dn)] = list(self.dn)
        mem[0x1670:0x1673] = [0xA9, box - u1maps.CHEST, 0x60]   # $906D: AND #1, ADC #5
        mem[0x8262], mem[0x81E8], mem[0x81E9], mem[0x81E4] = index, x, y, continent
        mem[0xA873] = n
        cpu.pc = GENERATE
        for _ in range(100000):
            if cpu.pc == BUILT:
                return bytes(mem[LEVEL_AT:LEVEL_AT + 121])
            cpu.step()
        self.fail("DN's generator did not get to $90E3")

    def test_every_level(self):
        self.assertEqual(len(self.dungeons), 36)
        for i, c, x, y in self.dungeons:
            for n in range(1, 11):
                for box in (u1maps.CHEST, u1maps.COFFIN):
                    with self.subTest(place=i, level=n, box=box):
                        self.assertEqual(self.run_dn(i - 1, x, y, c, n, box),
                                         bytes(self.gen.level(i - 1, x, y, c, n, box)))

    def test_seed_is_the_dungeon(self):
        """Nothing of the character goes in: only place, square, continent
        and level -- so each dungeon's levels are the same in every game."""
        i, c, x, y = self.dungeons[0]
        levels = {bytes(self.gen.level(i - 1, x, y, c, n, 0)) for n in range(1, 11)}
        self.assertEqual(len(levels), 10)


if __name__ == "__main__":
    unittest.main()
