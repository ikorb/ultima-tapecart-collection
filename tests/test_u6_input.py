"""Ultima 6's keyboard scan and direction latch (ultima/games/u6/u6scan.s).

The scan: the original ($28CE-$2988 of `game`) and the rewrite run in py65
over a modelled CIA 1 (a key matrix behind $DC00/$DC01) with the stock
KERNAL's decode tables at $E000, for every key alone, every key with every
set of modifiers, and random matrices; the key returned, the modifier in
$48 and the last row select written must agree.

The latch: the routine run frame by frame under a model of the IRQ (it
counts $FC down, builds $47, then s_latch) and of the main loop's wait
$0449 (when $FC has gone negative: $46 = $47, $FC = 8, then a turn of some
frames) -- what each read sees, for taps, holds, two taps, fire.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
import random
import unittest
from pathlib import Path

from ultima.sim import roms


try:
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    MPU = None

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

KERNAL = roms.find("C64", "kernal-901227-03.bin", "x64sc")      # VICE's (ultima/sim/roms.py)

SCAN = 0x28CE
SENTINEL = 0xFFF0
# (row, bit) of the five modifier keys
LSHIFT, RSHIFT, CDOWN, CTRL, STOP = (1, 7), (6, 4), (7, 5), (7, 2), (7, 7)
MODIFIERS = [LSHIFT, RSHIFT, CDOWN, CTRL, STOP]


def game_image():
    """64 KiB: `game` at $0200 as the build reads it, the KERNAL at $E000."""
    mem = bytearray(65536)
    path = os.path.join(u6.BUILD, "u6_game_orig.prg")
    if not os.path.exists(path):
        d3b = u6.D64(u6.disk_path("3B"))
        data = d3b.file("GAME")[0]
    else:
        data = Path(path).read_bytes()
    mem[0x0200:0x0200 + len(data) - 2] = data[2:]
    if KERNAL:
        mem[0xE000:0x10000] = Path(KERNAL).read_bytes()
    return mem


class Keyboard:
    """CIA 1's matrix: rows driven low through $DC00, columns read at $DC01."""

    def __init__(self, down=()):
        self.down = set(down)
        self.select = 0xFF
        self.writes = []

    def write(self, addr, value):
        if addr == 0xDC00:
            self.select = value
        self.writes.append((addr, value))

    def read(self, addr):
        v = 0xFF
        for row, bit in self.down:
            if not self.select & (1 << row):
                v &= ~(1 << bit) & 0xFF
        return v


def run_scan(image, keys):
    mem = ObservableMemory(subject=list(image))
    kb = Keyboard(keys)
    mem.subscribe_to_write([0xDC00, 0xDC02, 0xDC03], kb.write)
    mem.subscribe_to_read([0xDC01], kb.read)
    m = MPU(memory=mem)
    ret = SENTINEL - 1
    mem[0x1F0], mem[0x1EF] = ret >> 8, ret & 0xFF
    m.sp, m.pc, m.x, m.p = 0xEE, SCAN, 0xFF, 0x20
    for _ in range(20000):
        if m.pc == SENTINEL:
            return m.a, mem[0x48], [w for w in kb.writes if w[0] == 0xDC00][-1], \
                [w for w in kb.writes if w[0] != 0xDC00]
        m.step()
    raise RuntimeError("the scan did not return")


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
@unittest.skipIf(KERNAL is None, "no KERNAL image (VICE's kernal-901227-03.bin)")
class TestU6Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig = game_image()
        cls.new = bytearray(cls.orig)
        for addr, data in u6.assemble_fast():
            if 0x28CE <= addr < 0x2989:
                cls.new[addr:addr + len(data)] = data

    def same(self, keys):
        o, n = run_scan(self.orig, keys), run_scan(self.new, keys)
        self.assertEqual(o, n, f"keys {sorted(keys)}")
        return o

    def test_what_it_relies_on(self):
        """The rows' selects are game's masks at $0225; the five places masked
        out are exactly those whose unshifted decode is below 5."""
        self.assertEqual(bytes(self.orig[0x0225:0x022D]), bytes([0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F]))
        low = {(i >> 3, i & 7) for i in range(64) if self.orig[0xEB81 + i] < 5}
        self.assertEqual(low, set(MODIFIERS))

    def test_no_key_and_every_key_alone(self):
        self.assertEqual(self.same([])[0], 0)
        found = 0
        for r in range(8):
            for b in range(8):
                a = self.same([(r, b)])[0]
                found += a != 0
        self.assertGreater(found, 50)

    def test_every_key_with_every_set_of_modifiers(self):
        for r in range(8):
            for b in range(8):
                if (r, b) in MODIFIERS:
                    continue
                for mask in range(32):
                    mods = [m for i, m in enumerate(MODIFIERS) if mask >> i & 1]
                    self.same([(r, b)] + mods)

    def test_random_matrices(self):
        rng = random.Random(21)
        allkeys = [(r, b) for r in range(8) for b in range(8)]
        for _ in range(3000):
            self.same(rng.sample(allkeys, rng.choice([2, 2, 3, 4, 6])))

    def test_it_is_smaller(self):
        sym = u6.symbols(os.path.join(u6.BUILD, "u6scan.sym"))
        self.assertLessEqual(sym["s_scan_end"] - SCAN, 140)


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestU6Latch(unittest.TestCase):
    """s_latch under a model of the IRQ and the main loop."""

    @classmethod
    def setUpClass(cls):
        cls.sym = u6.symbols(os.path.join(u6.BUILD, "u6scan.sym"))
        cls.image = bytearray(65536)
        for addr, data in u6.assemble_fast():
            if 0x28CE <= addr < 0x2989:
                cls.image[addr:addr + len(data)] = data

    def play(self, inputs, turn=12, latch=True):
        """inputs: $47 as the IRQ builds it, frame by frame.  Returns what
        each read ($46) saw, with the frame it was taken after."""
        mem = list(self.image)
        m = MPU(memory=mem)
        mem[0xFC] = 0x08
        reads, busy = [], 0
        for f, state in enumerate(inputs):
            if mem[0xFC] < 0x80:                    # the IRQ: $1F57
                mem[0xFC] -= 1
                mem[0xFC] &= 0xFF
            mem[0x47] = state                       # $1F69 and the key merge
            if latch:
                ret = SENTINEL - 1
                mem[0x1F0], mem[0x1EF] = ret >> 8, ret & 0xFF
                m.sp, m.pc, m.p = 0xEE, self.sym["s_latch"], 0x20
                while m.pc != SENTINEL:
                    m.step()
            if busy:                                # the main loop
                busy -= 1
            elif mem[0xFC] >= 0x80:                 # $0449: the read
                reads.append((f, mem[0x47]))
                mem[0xFC] = 0x08
                busy = turn
        return reads

    W, N, E, FIRE = 0x04, 0x01, 0x08, 0x10

    def frames(self, n, at=(), key=0):
        out = [0] * n
        for f in at:
            out[f] = key
        return out

    def test_a_tap_between_two_reads_is_read(self):
        # the first read comes after frame 8; a tap at frames 12-14, long
        # before the next read (after frame 8 + 12 + 9)
        inputs = self.frames(60, at=range(12, 15), key=self.W)
        without = [v for _f, v in self.play(inputs, latch=False)]
        self.assertNotIn(self.W, without)           # what the original did
        seen = [v for _f, v in self.play(inputs)]
        self.assertEqual(seen.count(self.W), 1)

    def test_a_key_held_through_a_read_leaves_nothing_behind(self):
        reads = self.play(self.frames(80, at=range(3, 24), key=self.W))
        held = [f for f, v in reads if v == self.W]
        self.assertEqual(len(held), len([f for f, _v in reads if 3 <= f < 24]))
        self.assertTrue(all(v == 0 for f, v in reads if f >= 24))

    def test_holding_is_as_before(self):
        inputs = self.frames(100, at=range(0, 100), key=self.N)
        self.assertEqual(self.play(inputs), self.play(inputs, latch=False))

    def test_two_taps_first_wins_and_no_diagonal(self):
        inputs = self.frames(70)
        for f in (11, 12):
            inputs[f] = self.W
        for f in (16, 17):
            inputs[f] = self.N
        seen = [v for _f, v in self.play(inputs) if v]
        self.assertEqual(seen, [self.W])

    def test_fire_is_not_latched(self):
        inputs = self.frames(60, at=range(12, 15), key=self.FIRE)
        self.assertEqual([v for _f, v in self.play(inputs) if v], [])

    def test_a_tap_again_after_its_read_is_a_new_tap(self):
        inputs = self.frames(90)
        for f in (11, 12, 32, 33):
            inputs[f] = self.E
        seen = [v for _f, v in self.play(inputs) if v]
        self.assertEqual(seen, [self.E, self.E])


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestU6ReturnFire(unittest.TestCase):
    """The read $0449 (from $0455, past its frame wait): popping a Return from
    the key queue sets fire in $46 as well; everything else as it was."""

    @classmethod
    def setUpClass(cls):
        cls.orig = game_image()
        cls.new = bytearray(cls.orig)
        cls.code = set()
        for addr, data in u6.assemble_fast():
            if addr in (0x046C, 0x2084, 0x27ED):
                cls.new[addr:addr + len(data)] = data
                cls.code.update(range(addr, addr + len(data)))

    def read(self, image, queue, held):
        mem = list(image)
        mem[0x45] = len(queue)
        for i, k in enumerate(queue):
            mem[0xD7E4 + i] = k
        mem[0x46] = held                        # what $0451 copied from $47
        m = MPU(memory=mem)
        ret = SENTINEL - 1
        mem[0x1F0], mem[0x1EF] = ret >> 8, ret & 0xFF
        m.sp, m.pc, m.p = 0xEE, 0x0455, 0x20
        for _ in range(5000):
            if m.pc == SENTINEL:
                return mem
            m.step()
        raise RuntimeError("no return")

    def test_return_adds_fire_and_nothing_else_changes(self):
        cases = 0
        for queue in ([], [0x0D], [0x0D, 0x41], [0x41, 0x0D], [0x20], [0x59, 0x4E, 0x0D], [0x2D]):
            for held in (0x00, 0x04, 0x10, 0x14, 0x01):
                o, n = self.read(self.orig, queue, held), self.read(self.new, queue, held)
                want = held | (0x10 if queue[:1] == [0x0D] else 0)
                self.assertEqual(n[0x46], want, (queue, held))
                self.assertEqual(o[0x46], held)
                diff = [a for a in range(65536) if o[a] != n[a] and a != 0x46 and a not in self.code
                        and not 0x100 <= a < 0x200]
                self.assertEqual(diff, [], (queue, held, [hex(a) for a in diff[:8]]))
                self.assertEqual(n[0x44], queue[0] if queue else 0)
                self.assertEqual(n[0x45], max(len(queue) - 1, 0))
                cases += 1
        self.assertEqual(cases, 35)

    def test_the_rts_it_borrows(self):
        self.assertEqual(self.orig[0x2061], 0x60)


if __name__ == "__main__":
    unittest.main()
