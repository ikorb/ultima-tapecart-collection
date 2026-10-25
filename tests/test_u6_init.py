"""Ultima 6's one-time init, run from a copy in flash (ultima/games/u6/build.py
relocate_init, u6boot.s's hand-off): the original `$038F` and the relocated
copy at `$4400` leave the machine the same -- every byte of memory, the
registers' worth of hardware writes included -- when they reach `$03FC`,
the main loop's entry.  Also: the boot piece fits, and the freed ranges are
free (nothing in `game` as built names them).

Skipped without py65.
"""
import importlib.util
import unittest
from tests import fixtures

try:
    from tests import u6run
except ImportError:
    u6run = None

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)


@unittest.skipIf(u6run is None, "py65 is not installed (use the repository's .venv)")
@fixtures.needs("u6_castle_0.bin", "u6_castle_21.bin")
class TestU6Init(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        disk = u6.D64(u6.disk_path("3B"))
        cls.original = bytearray(disk.file("GAME")[0])
        cls.relocated = bytearray(cls.original)
        cls.blob = u6.relocate_init(cls.relocated)

    def test_the_relocated_init_does_what_the_original_did(self):
        for name in ("u6_castle_0.bin", "u6_castle_21.bin"):
            ram = u6run.fixture(name)
            # the images as the boot leaves them: the game's own bytes, original init and all
            ram[0x200:0x200 + len(self.original) - 2] = list(self.original[2:])
            ram[0x1F40:0x1F42] = [0, 0]
            a = u6run.Machine(list(ram))
            u6run.run_to(a, 0x038F, 0x03FC)
            moved = list(ram)
            moved[0x200:0x200 + len(self.relocated) - 2] = list(self.relocated[2:])
            moved[u6.INIT_AT:u6.INIT_AT + len(self.blob) + 3] = list(self.blob + u6.INIT_TAIL)
            b = u6run.Machine(moved)
            u6run.run_to(b, u6.INIT_AT, 0x03FC)
            freed = set()
            for first, end in u6.INIT_FREED:
                freed.update(range(first, end))
            blobspan = set(range(u6.INIT_AT, u6.INIT_AT + len(self.blob) + 3))
            d = u6run.diff(a.mem, b.mem, ignore=freed | blobspan | set(range(0x100, 0x1F0)))
            self.assertEqual(d, [], f"{name}: {[hex(x) for x in d[:12]]}")

    def test_the_freed_bytes_are_zero_and_the_rest_is_untouched(self):
        for first, end in u6.INIT_FREED:
            self.assertEqual(bytes(self.relocated[first - 0x200 + 2:end - 0x200 + 2]), bytes(end - first))
        keep = set()
        for first, end in u6.INIT_FREED:
            keep.update(range(first - 0x200 + 2, end - 0x200 + 2))
        for i in range(len(self.original)):
            if i not in keep:
                self.assertEqual(self.relocated[i], self.original[i], hex(i + 0x200 - 2))

    def test_the_copy_fits_where_it_lands(self):
        self.assertEqual(len(self.blob), 350)
        self.assertLess(u6.INIT_AT + len(self.blob), 0x4800)      # inside the chunk index map


if __name__ == "__main__":
    unittest.main()
