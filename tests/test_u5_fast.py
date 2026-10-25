"""Ultima 5's speed patches (ultima/games/u5/build.py FAST_SOURCES): routines of the
view, the text window and the townspeople, each rewritten to do the same in
fewer cycles.  The real code, original (from the disk files) and patched, is
run in py65 over whole-RAM images captured from VICE (tools/vice/fixtures.py) --
Britannia (tests/data/u5_britannia.bin, the grass row of the overworld walk)
and Yew (u5_town.bin, at noon) -- and over those with the state the routines
read randomised; everything in memory has to come out the same, bar the
routines' own code and the stack below S.

Skipped without py65 (the repository's .venv has it) or the fixtures
(make fixtures).
"""
import importlib.util
import random
import unittest
from tests import fixtures
from ultima import paths
from ultima.disks.d64 import D64

try:
    from tests import u6run as run                     # a flat 64 KiB machine; nothing U6 about it
except ImportError:
    run = None

_spec = importlib.util.find_spec("ultima.games.u5.build")
u5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u5)


FIXTURES = ("u5_britannia.bin", "u5_town.bin")
STACK = range(0x100, 0x1EF)
# the line of sight's scratch (u5los.s): its masks at $7F00 where the
# original kept row numbers, $86 and $B5 -- each written before it is read
# by everything after it (the source's header says where that was checked)
LOS_SCRATCH = set(range(0x7F00, 0x7F79)) | {0x86, 0xB5}
# the view buffers' (u5buf.s): what $51AF and $515E left in $FC/$FD and $BE
BUF_SCRATCH = {0xFC, 0xFD, 0xBE}


def original_file(fname):
    disk = {"MAIN.SUBS": "u5-1a", "UPDATE.HIMEM": "u5-1a", "MAIN.TWN": "u5-3a"}[fname]
    raw = D64(paths.disk(disk)).file(fname)[0]
    return raw[0] | raw[1] << 8, raw[2:]



@unittest.skipIf(run is None, "py65 is not installed (use the repository's .venv)")
@fixtures.needs(*FIXTURES)
class TestU5Fast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = u5.assemble_fast()
        cls.base = {n: run.fixture(n) for n in FIXTURES}
        # the original routines as the disk has them (RAM may hold self-modified operands)
        cls.orig = []
        for fname, first, end in u5.FAST_ORIGINAL:
            load, data = original_file(fname)
            data = bytearray(data)
            for f, addr, want, new, _why in u5.MOTOR:       # as the build has them, first
                if f.upper() == fname:
                    assert data[addr - load] == want
                    data[addr - load] = new
            cls.orig.append((fname, first, bytes(data[first - load:end - load])))
        cls.code = set()
        for _f, first, data in cls.orig:
            cls.code.update(range(first, first + len(data)))

    def pair(self, ram, fixture):
        """(original machine, patched machine) over `ram`.  main.twn's code is
        only in the town's RAM."""
        town = fixture == "u5_town.bin"
        keep = lambda f: f != "MAIN.TWN" or town
        o = run.patched(ram, [(a, d) for f, a, d in self.orig if keep(f)])
        n = run.patched(o, [(a, d) for f, _ds, a, d in self.patches if keep(f)])
        return run.Machine(o), run.Machine(n)

    def same(self, o, n, what, regs=False, scratch=()):
        d = run.diff(o.mem, n.mem, ignore=self.code | set(STACK) | set(scratch))
        self.assertEqual(d, [], f"{what}: {[hex(a) for a in d[:12]]}")
        if regs:
            self.assertEqual((o.mpu.a, o.mpu.x, o.mpu.y), (n.mpu.a, n.mpu.x, n.mpu.y), what)

    # -- the tile animation ($572B) ------------------------------------------
    def test_the_tile_animation(self):
        rng = random.Random(1)
        for name in FIXTURES:
            for count in range(8):
                ram = list(self.base[name])
                for a in range(0xD000, 0xE000):
                    ram[a] = rng.randrange(256)
                ram[0x572A] = (count + 8 * rng.randrange(32)) & 0xFF
                ram[0xFC], ram[0xFD] = rng.randrange(256), rng.randrange(256)
                o, n = self.pair(ram, name)
                co, cn = o.call(0x572B), n.call(0x572B)
                self.same(o, n, f"{name} count {count}")
                self.assertLess(cn, co / 4, f"{name}: {co} -> {cn} cycles")

    # -- the text window's scroll ($5A90) -----------------------------------
    def test_the_text_scroll(self):
        rng = random.Random(2)
        for name in FIXTURES:
            for _ in range(4):
                ram = list(self.base[name])
                for a in range(0x0400, 0x0800):
                    ram[a] = rng.randrange(256)
                for a in range(0x2000, 0x4000):
                    ram[a] = rng.randrange(256)
                o, n = self.pair(ram, name)
                co, cn = o.call(0x5A90), n.call(0x5A90)
                self.same(o, n, name)
                self.assertLess(cn, co * 0.6, f"{name}: {co} -> {cn} cycles")

    def test_the_row_tables_are_what_the_scroll_assumes(self):
        for name in FIXTURES:
            r = self.base[name]
            for n in range(192):
                self.assertEqual(r[0x1400 + n] | r[0x14C0 + n] << 8, 0x2000 + 320 * (n // 8 + 1) + n % 8)
            for k in range(24):
                self.assertEqual(r[0x03D0 + k] | r[0x03E8 + k] << 8, 0x0400 + 40 * (k + 1))
            self.assertEqual(r[0x72], 0x58)

    # -- a line printed with the scroll in it ($5A59, a carriage return) -----
    def test_a_newline_at_the_bottom(self):
        for name in FIXTURES:
            ram = list(self.base[name])
            ram[0xCA] = 0x17                    # the last row: a CR scrolls
            o, n = self.pair(ram, name)
            o.call(0x5A59, regs={"a": 0x8D, "x": 0x12, "y": 0x34})
            n.call(0x5A59, regs={"a": 0x8D, "x": 0x12, "y": 0x34})
            self.same(o, n, name, regs=True)

    # -- the line of sight ($4D5D) -------------------------------------------
    def view_state(self, rng, name):
        """A fixture with the view's inputs randomised: the tiles (some of
        them blocking sight, the five special ones), the lit squares, the
        light radius and $0D.  Never tile 0: a seen tile 0 looks unreached,
        and two of them side by side push each other for ever -- in the
        original as in the rewrite; no map has it in view."""
        ram = list(self.base[name])
        table = ram[0x513E:0x515E]
        bit = ram[0x651A:0x6522]
        blocks = [t for t in range(256) if table[t >> 3] & bit[t & 7]]
        clear = [t for t in range(1, 256) if not table[t >> 3] & bit[t & 7]]
        special = [0x98, 0x4A, 0x4B, 0xBA, 0xBB]
        density = rng.choice([0, 0.05, 0.15, 0.3, 0.5, 0.8])
        litd = rng.choice([0, 0, 0.05, 0.3])
        for i in range(121):
            r = rng.random()
            ram[0x4880 + i] = (rng.choice(blocks) if r < density else
                               rng.choice(special) if r < density + 0.04 else rng.choice(clear))
            ram[0x4980 + i] = 1 if rng.random() < litd else 0
        ram[0x0E] = rng.choice([0, 1, 1, 2, 3, 5, 9, 0x10, 0x19, 0x22, 0x32, 0x32, 0x40, 0x80, 0xFF])
        ram[0x0D] = rng.choice([0, 0, 0, 0x80, 0x40])
        return ram

    def test_the_line_of_sight(self):
        rng = random.Random(3)
        gain = []
        for k in range(400):
            name = FIXTURES[k % 2]
            ram = self.view_state(rng, name)
            o, n = self.pair(ram, name)
            co, cn = o.call(0x4D5D), n.call(0x4D5D)
            self.same(o, n, f"case {k}", scratch=LOS_SCRATCH)
            gain.append(co - cn)
        # the masks cost ~2k more than the row numbers did, which a view with
        # nothing seen (light radius 0) does not win back
        self.assertGreater(min(gain), -2100)
        self.assertGreater(sum(gain) / len(gain), 4000)

    def test_the_line_of_sight_copies_the_window_when_0a_is_negative(self):
        ram = self.view_state(random.Random(4), FIXTURES[0])
        ram[0x0A] = 0x80
        o, n = self.pair(ram, FIXTURES[0])
        o.call(0x4D5D)
        n.call(0x4D5D)
        self.same(o, n, "$0A negative")

    # -- the view's draw (update.himem $1DE4, through $1D80) -------------------
    def test_the_draw(self):
        rng = random.Random(5)
        for k in range(60):
            name = FIXTURES[k % 2]
            ram = list(self.base[name])
            for i in range(121):
                r = rng.random()
                ram[0x4800 + i] = 0 if r < 0.3 else rng.randrange(256)
                ram[0x4900 + i] = rng.choice([0xF8, 0xFF, rng.randrange(256)])
            for a in list(range(0x0800, 0x0C00 + 0x400)) + list(range(0xC000, 0x10000)):
                if rng.random() < 0.02:
                    ram[a] = rng.randrange(256)
            ram[0xC8] = rng.choice([0, 0, 0x40])        # (bit 7, a C128, calls into the C128 driver)
            for z in range(0x50, 0x5D):
                ram[z] = rng.randrange(256)
            o, n = self.pair(ram, name)
            co, cn = o.call(0x1D80), n.call(0x1D80)
            self.same(o, n, f"case {k}")
            self.assertLess(cn, co * 0.92, f"{co} -> {cn}")

    def test_the_draw_on_a_c128(self):
        """$C8 bit 7: the original calls $1D89 (the C128 driver) before the
        first row, twice between rows (CLI / SEI between), and at the end.
        $1D89 is made a stub that counts the calls and records the I flag."""
        stub = [0xEE, 0xF0, 0x02,       # INC $02F0
                0x08, 0x68,             # PHP / PLA
                0xAE, 0xF0, 0x02,       # LDX $02F0
                0x9D, 0x00, 0x03,       # STA $0300,X: the flags at each call
                0x60]
        for name in FIXTURES:
            ram = list(self.base[name])
            ram[0xC8] = 0x80
            ram[0x1D89:0x1D89 + len(stub)] = stub
            ram[0x02F0] = 0
            o, n = self.pair(ram, name)
            o.call(0x1D80)
            n.call(0x1D80)
            self.assertEqual(o.mem[0x02F0], 1 + 2 * 11 + 1)
            self.same(o, n, name)

    # -- the view's buffers ($4D06) -------------------------------------------
    def test_the_view_buffers(self):
        rng = random.Random(6)
        for k in range(300):
            name = FIXTURES[k % 2]
            ram = list(self.base[name])
            # the party anywhere in the 32 x 32 window, edges and outside included
            ram[0x02] = rng.choice([rng.randrange(32), 0, 1, 4, 5, 26, 27, 31, 36, 250, 255])
            ram[0x03] = rng.choice([rng.randrange(32), 0, 1, 4, 5, 26, 27, 31, 36, 250, 255])
            for a in range(0x4400, 0x4800):
                if rng.random() < 0.3:
                    ram[a] = rng.randrange(256)
            density = rng.choice([0, 0, 0.02, 0.2, 0.6])
            for a in range(0x7E80, 0x7F00):
                ram[a] = sum(1 << b for b in range(8) if rng.random() < density)
            o, n = self.pair(ram, name)
            co, cn = o.call(0x4D06), n.call(0x4D06)
            # X and Y are left as they fall: the line of sight, always next, loads both
            self.same(o, n, f"case {k}", scratch=BUF_SCRATCH)
            self.assertEqual(o.mpu.a, n.mpu.a)
            self.assertLess(cn, co * 0.7, f"{co} -> {cn}")

    # -- the town's walkability map (main.twn $A30F) --------------------------
    def test_the_walkability_map(self):
        rng = random.Random(7)
        name = "u5_town.bin"
        for k in range(40):
            ram = list(self.base[name])
            for a in range(0x4400, 0x4800):
                if rng.random() < 0.5:
                    ram[a] = rng.randrange(256)
            ram[0xA201] = rng.choice([rng.randrange(256), ram[0x4400 + rng.randrange(0x400)]])
            o, n = self.pair(ram, name)
            co, cn = o.call(0xA30F), n.call(0xA30F)
            self.same(o, n, f"case {k}")
            self.assertLess(cn, co * 0.5, f"{co} -> {cn}")

    # -- the whole view update ($4C1B), from the turn's start ----------------
    def test_the_view_update(self):
        for name in FIXTURES:
            for turn in range(4):
                ram = list(self.base[name])
                ram[0x572A] = (ram[0x572A] + turn) & 0xFF
                o, n = self.pair(ram, name)
                o.call(0x4C1B)
                n.call(0x4C1B)
                self.same(o, n, f"{name} turn {turn}", regs=True,
                          scratch=LOS_SCRATCH | BUF_SCRATCH)


if __name__ == "__main__":
    unittest.main()
