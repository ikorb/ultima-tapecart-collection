"""Ultima 6's speed patches (ultima/games/u6/u6flood.s, u6light.s, u6view.s): the
map view's line-of-sight flood, light map and draw loop, each rewritten to
do the same in fewer cycles.  The real code, original and patched, is run in
py65 over whole-RAM images captured from VICE (tools/vice/fixtures.py) -- a castle
with the party walking south -- and over those with their tile grids,
light, flags and objects randomised, and everything in memory has to come
out the same (bar the routines' own scratch bytes, named below).

Skipped without py65 (the repository's .venv has it) or the fixtures
(make fixtures).
"""
import importlib.util
import random
import unittest
from tests import fixtures

try:
    from tests import u6run
except ImportError:
    u6run = None

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

FIXTURES = ("u6_castle_0.bin", "u6_castle_21.bin")
# bytes the original and the patched code leave differently, each scratch
# that every reader sets first: $2A (the original's second pass kept a tile
# there), $2B (the flood's last cell: a clear window, which skips the flood,
# leaves the party's), $2C/$2D (the flood's), $52/$54/$55 (the light map's and
# the draw loop's)
SCRATCH = (0x2A, 0x2B, 0x2C, 0x2D, 0x52, 0x54, 0x55)
STACK = range(0x100, 0x1EF)                 # below S: what the flood left there


def span(first, end):
    return range(first, end)


@unittest.skipIf(u6run is None, "py65 is not installed (use the repository's .venv)")
@fixtures.needs(*FIXTURES)
class TestU6Fast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = u6.assemble_fast()
        cls.base = {n: u6run.fixture(n) for n in FIXTURES}
        cls.code = set()
        for addr, data in cls.patches:
            cls.code.update(range(addr, addr + len(data)))

    def pair(self, ram, only=None):
        """(original machine, patched machine) over `ram`."""
        patches = [(a, d) for a, d in self.patches if only is None or only(a)]
        return u6run.Machine(list(ram)), u6run.Machine(u6run.patched(ram, patches))

    def same(self, o, n, what):
        d = u6run.diff(o.mem, n.mem, ignore=set(SCRATCH) | set(STACK) | self.code)
        self.assertEqual(d, [], f"{what}: {[hex(a) for a in d[:12]]}")

    def randomised(self, rng, name=None):
        ram = list(self.base[name or rng.choice(FIXTURES)])
        flags = lambda t: ram[0xA600 + t] & 0x0C
        opaque = [t for t in range(256) if flags(t) == 4] or [0x10]
        special = [t for t in range(256) if flags(t) in (8, 12)] or [0x10]
        clear = [t for t in range(1, 256) if flags(t) == 0]
        density = rng.choice([0, 0.05, 0.2, 0.4, 0.7])
        for i in range(121):
            r = rng.random()
            ram[0xD6F2 + i] = (rng.choice(opaque) if r < density else
                               rng.choice(special) if r < density + 0.05 else rng.choice(clear))
            ram[0xD76B + i] = rng.choice([0, 0, 0, 0, 0x40, 0x9D, 0x9E, 0xA0, rng.randrange(256)])
            ram[0xD679 + i] = rng.choice([4, 4, 4, 0, 0, 1, 2, 3, 5, 9, rng.randrange(256)])
        if rng.random() < 0.2:
            ram[0xD6F2 + rng.randrange(121)] = 0
        ram[0x26] = rng.choice([0, 1, 2, 3, 5, 7, 9, 12, 0x80, 0xF0, 0xFF])
        ram[0x589B] = 1 if rng.random() < 0.1 else 0
        ram[0x589E] = 1 if rng.random() < 0.1 else 0
        ram[0xFD] = rng.choice([0, 0, 0, 3, 4])
        return ram

    def test_the_flood_is_what_it_was(self):
        rng = random.Random(1)
        for case in range(150):
            ram = self.randomised(rng)
            o, n = self.pair(ram)
            o.call(0x178C)
            n.call(0x178C)
            self.same(o, n, f"flood, case {case}")

    def test_a_clear_window_skips_the_flood_and_gets_the_same_result(self):
        rng = random.Random(7)
        shortcuts = 0
        for case in range(80):
            ram = self.randomised(rng)
            clear = [t for t in range(1, 256) if ram[0xA600 + t] & 0x0C == 0]
            blockers = [t for t in range(256) if ram[0xA600 + t] & 0x0C or t == 0]
            for i in range(121):
                ram[0xD6F2 + i] = rng.choice(clear)
            if case % 3:                                # a blocker, a few, or none at all
                for _ in range(rng.choice([1, 1, 2, 5])):
                    ram[0xD6F2 + rng.randrange(121)] = rng.choice(blockers)
            o, n = self.pair(ram)
            co, cn = o.call(0x178C), n.call(0x178C)
            self.same(o, n, f"clear window, case {case}")
            if case % 3 == 0:
                shortcuts += 1
                self.assertLess(cn, co * 0.8, (case, co, cn))
        self.assertGreater(shortcuts, 20)

    def test_the_light_map_is_what_it_was(self):
        rng = random.Random(2)
        for case in range(150):
            ram = self.randomised(rng)
            for k in range(0x54C0 + 0x1B, 0x54C0 + 0x5D):        # lights $3F04 counts
                if rng.random() < 0.1:
                    ram[k] = 0x62
            o, n = self.pair(ram)
            o.call(0x18E8)
            n.call(0x18E8)
            self.same(o, n, f"light map, case {case}")

    def test_the_draw_loop_is_what_it_was(self):
        rng = random.Random(3)
        for case in range(120):
            ram = self.randomised(rng)
            ram[0x42] = rng.randrange(256)
            o, n = self.pair(ram)
            o.call(0x1697)
            n.call(0x1697)
            self.same(o, n, f"draw, case {case}")

    def test_the_whole_view_is_what_it_was(self):
        """$1631: the window gathered, the flood, the actors, the draw."""
        rng = random.Random(4)
        for case in range(40):
            ram = list(self.base[rng.choice(FIXTURES)])
            if case:
                for _ in range(rng.choice([20, 100, 400])):      # tiles of the planes changed
                    a = rng.choice([0x4800, 0x4C00, 0x5000]) + rng.randrange(1024)
                    ram[a] = rng.choice([0, 0x10, 0x5B, 0x6C, 0x8C, 0xAA, rng.randrange(256)])
                ram[0x26] = rng.choice([0, 3, 7])
            o, n = self.pair(ram)
            o.call(0x1631, limit=2_000_000)
            n.call(0x1631, limit=2_000_000)
            self.same(o, n, f"view, case {case}")

    def walk(self, machine, box):
        """The pool walk as $273E drives it: head, advance, then $27CE until it
        says end, advancing past each node it reports; returns the trace."""
        m, mem = machine, machine.mem
        mem[0x33], mem[0x34], mem[0x80], mem[0x81] = box
        mem[0x50], mem[0x51] = 0x00, 0xA8
        cycles = m.call(0x252B)
        trace = []
        for _ in range(900):
            cycles += m.call(0x27CE)
            p = m.mpu
            trace.append((p.a, p.y, p.p & 0x83, mem[0x4E], mem[0x4F], mem[0x50], mem[0x51]))
            if p.p & 1:
                break
            cycles += m.call(0x252B)
        return trace, cycles

    def test_the_pool_walk_is_what_it_was(self):
        rng = random.Random(5)
        for case in range(60):
            ram = list(self.base[rng.choice(FIXTURES)])
            node = 0xA800
            while node and node < 0xC000 and ram[node] != 0xFF:       # real nodes: move some about
                if rng.random() < 0.3:
                    ram[node + 1], ram[node + 2] = rng.randrange(256), rng.randrange(256)
                node = ram[node + 6] | ram[node + 7] << 8
                if node < 0xA800:
                    break
            box = (rng.randrange(256), rng.randrange(256), rng.choice([8, 8, 16, 255]), rng.choice([8, 8, 16, 255]))
            o, n = self.pair(ram, only=lambda a: a in (0x27CE, 0x038F))
            to, co = self.walk(o, box)
            tn, cn = self.walk(n, box)
            self.assertEqual(to, tn, f"walk, case {case}")
            self.same(o, n, f"walk, case {case}")
            if co > 30000 and len(to) < 20:                     # a walk that mostly misses, as a chunk's does
                self.assertLess(cn, co * 0.8, (case, co, cn))

    def test_the_chunk_overlay_is_what_it_was(self):
        """$273E: one chunk's objects onto the tile layers."""
        rng = random.Random(6)
        for case in range(25):
            ram = list(self.base[rng.choice(FIXTURES)])
            ram[0x7A], ram[0x7B] = rng.randrange(32), rng.randrange(32)
            o, n = self.pair(ram, only=lambda a: a in (0x27CE, 0x038F))
            co, cn = o.call(0x273E), n.call(0x273E)
            self.same(o, n, f"overlay, case {case}")
            self.assertLess(cn, co)

    def test_it_is_faster(self):
        for name in FIXTURES:
            o, n = self.pair(self.base[name])
            before, after = o.call(0x1631), n.call(0x1631)
            self.assertLess(after, before * 0.92, (name, before, after))

    def test_what_the_patches_rely_on(self):
        """build.py refuses anything but the original disk; here the same
        asserts run on the fixture's RAM (the game as the cart loaded it)."""
        ram = self.base[FIXTURES[0]]
        self.assertEqual(ram[0x93C0:0x93D0], [0xFF] * 16)
        for row in range(9):
            top = ram[0x1E3A + 2 * row] | ram[0x1E4C + 2 * row] << 8
            bot = ram[0x1E3B + 2 * row] | ram[0x1E4D + 2 * row] << 8
            self.assertEqual(bot, top + 0x140)
        self.assertEqual(ram[0x0212:0x0212 + 11], [11 * n for n in range(11)])
        self.assertEqual(ram[0x5F37:0x5F37 + 121], [n // 11 for n in range(121)])


if __name__ == "__main__":
    unittest.main()
