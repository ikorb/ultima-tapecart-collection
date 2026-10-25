"""Ultima 6: the map window's objects placed in one walk of the pool
(ultima/games/u6/u6chunk.s) instead of one walk per chunk.

The real code, original and patched, runs in py65 over the whole-RAM images
captured from VICE (tools/vice/fixtures.py), with the object pool's nodes moved
about so that many fall into the boxes and onto the same cells, some of
them $FE nodes and $FF tiles, $29 either way; the chunk reads ($2809, the
loader) are served from the Surface disk.  Everything in memory has to come
out the same, bar the old walk's temporary $42, the buffers $D740-$D7BF the
new code no longer goes through, and for $3FBD $7B (see u6chunk.s).

Skipped without py65 (the repository's .venv has it) or the fixtures
(make fixtures).
"""
import importlib.util
import os
import random
import unittest
from pathlib import Path
from tests import fixtures

try:
    from tests import u6run
except ImportError:
    u6run = None

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

FIXTURES = ("u6_castle_0.bin", "u6_castle_21.bin")
SCRATCH = {0x42} | set(range(0xD740, 0xD7C0))
STACK = range(0x100, 0x1F0)
LOADER = 0x2809


class Run:
    """A py65 machine that serves the loader's chunk reads from a disk."""

    def __init__(self, ram, disk):
        self.m = u6run.Machine(list(ram))
        self.disk = disk
        self.reads = 0

    def _load(self):
        mem = self.m.mem
        t, s, off, cnt = mem[0x0204], mem[0x0205], mem[0x0206], mem[0x0207]
        dest = mem[0x0208] | mem[0x0209] << 8
        data = self.disk.sector(t, s)
        n = cnt or 256
        for i in range(n):
            mem[(dest + i) & 0xFFFF] = data[(off + i) & 0xFF]
        self.reads += 1

    def run(self, start, stop=u6run.SENTINEL, regs=None, limit=8_000_000):
        m, mem = self.m.mpu, self.m.mem
        regs = regs or {}
        m.a, m.x, m.y = regs.get("a", 0), regs.get("x", 0), regs.get("y", 0)
        ret = u6run.SENTINEL - 1
        mem[0x1F0], mem[0x1EF] = ret >> 8, ret & 0xFF
        m.sp = 0xEE
        m.pc = start
        m.p = 0x20
        c0 = m.processorCycles
        for _ in range(limit):
            if m.pc == stop:
                return m.processorCycles - c0
            if m.pc == LOADER:
                self._load()
                lo, hi = mem[0x101 + m.sp], mem[0x102 + m.sp]
                m.sp = (m.sp + 2) & 0xFF
                m.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                m.a = m.x = m.y = 0
                m.p &= ~1                       # carry clear: the read worked
                continue
            m.step()
        raise RuntimeError(f"${start:04x} did not reach ${stop:04x}")


@unittest.skipIf(u6run is None, "py65 is not installed (use the repository's .venv)")
@fixtures.needs(*FIXTURES)
class TestU6Chunk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = u6.assemble_fast()
        cls.base = {n: u6run.fixture(n) for n in FIXTURES}
        cls.code = set()
        for addr, data in cls.patches:
            cls.code.update(range(addr, addr + len(data)))
        cls.disk = u6.D64(u6.disk_path("1A"))

    def pair(self, ram):
        return Run(ram, self.disk), Run(u6run.patched(ram, self.patches), self.disk)

    def same(self, o, n, what, also=()):
        d = u6run.diff(o.m.mem, n.m.mem, ignore=SCRATCH | set(STACK) | self.code | set(also))
        self.assertEqual(d, [], f"{what}: {[hex(a) for a in d[:12]]}")

    def view_chunk(self, ram):
        """$7A/$7B as $2242 sets them for this RAM."""
        m = u6run.Machine(list(ram))
        m.call(0x2242)
        return m.mem[0x7A], m.mem[0x7B]

    def scramble(self, rng, ram, near, spread=(-12, 44)):
        """Move pool nodes into the tile boxes around `near` (x, y), make
        some of them $FE nodes or $FF tiles; the walk order stays."""
        nx, ny = near
        node, seen = 0xA800, 0
        while 0xA800 <= node < 0xC000 and seen < 900:
            if ram[node] == 0xFF and node != 0xA800:
                break
            if node != 0xA800 and rng.random() < 0.45:
                ram[node + 1] = (nx + rng.randrange(*spread)) & 0xFF
                ram[node + 2] = (ny + rng.randrange(*spread)) & 0xFF
                r = rng.random()
                if r < 0.15:
                    ram[node] = 0xFE
                    ram[node + 3] = rng.choice([0xFF, 0xFF, 0x00, rng.randrange(256)])
                elif r < 0.19:
                    ram[node] = 0xFD                    # (just below the $FE test)
                elif r < 0.25:
                    ram[node + 3] = rng.choice([0xFF, 0x00])
            node = ram[node + 6] | ram[node + 7] << 8
            seen += 1
        ram[0x29] = rng.choice([0, 0, 1, 0x80])

    def randomised(self, rng, near=None):
        ram = list(self.base[rng.choice(FIXTURES)])
        x, y = self.view_chunk(ram)
        if near:
            self.scramble(rng, ram, near(x, y), spread=(-3, 11))
        else:
            self.scramble(rng, ram, (8 * x, 8 * y))
        for a in range(0x4C00, 0x5400):              # old objects in planes 2 and 3
            if rng.random() < 0.1:
                ram[a] = rng.choice([0xFF, rng.randrange(256)])
        return ram

    def test_the_whole_window_again_3fbd(self):
        rng = random.Random(11)
        for case in range(40):
            ram = self.randomised(rng)
            o, n = self.pair(ram)
            co, cn = o.run(0x3FBD), n.run(0x3FBD)
            self.same(o, n, f"$3FBD, case {case}", also=(0x7B,))
            self.assertLess(cn, co / 4, (case, co, cn))

    def test_one_chunk_3399(self):
        rng = random.Random(12)
        for case in range(40):
            dx, dy = rng.randrange(32), rng.randrange(32)
            ram = self.randomised(rng, near=lambda x, y: ((8 * x + dx) & 0xF8, (8 * y + dy) & 0xF8))
            x, y = self.view_chunk(ram)
            regs = {"x": (8 * x + dx) & 0xFF, "a": (8 * y + dy) & 0xFF}
            o, n = self.pair(ram)
            o.run(0x3399, regs=regs)
            n.run(0x3399, regs=regs)
            self.same(o, n, f"$3399, case {case}")

    def test_a_step_over_a_chunk_line(self):
        rng = random.Random(13)
        new = {0x2663: u6.symbols(os.path.join(u6.BUILD, "u6chunk.sym"))["k_row"],
               0x262D: u6.symbols(os.path.join(u6.BUILD, "u6chunk.sym"))["k_col"]}
        for case in range(60):
            ram = self.randomised(rng)
            ram[0x46] = rng.choice([0, 2, 8, 10, 0xFF])
            ram[0x74], ram[0x75] = rng.choice([0, 8, 16, 24]), rng.choice([0, 8, 16, 24])
            entry = rng.choice([0x2663, 0x262D])
            o, n = self.pair(ram)
            co, cn = o.run(entry), n.run(new[entry])
            self.same(o, n, f"strip ${entry:04x}, case {case}")
            self.assertEqual((o.reads, n.reads), (4, 4))
            self.assertLess(cn, co * 0.6, (case, co, cn))

    def test_a_window_load(self):
        rng = random.Random(14)
        for case in range(12):
            ram = self.randomised(rng)
            ram[0x22E3] = 0x60                         # the window's own loads: not here
            ram[0x76] = ram[0x77] = 0                  # as $25F3 left them
            o, n = self.pair(ram)
            co = o.run(0x25FB, stop=0x2C38)
            cn = n.run(0x25FB, stop=0x2C38)
            self.same(o, n, f"window load, case {case}", also=(0x55,))     # (its row counter: every reader sets it first)
            self.assertEqual((o.reads, n.reads), (16, 16))
            self.assertLess(cn, co / 2, (case, co, cn))

    def test_the_step_calls_the_new_strips(self):
        sym = u6.symbols(os.path.join(u6.BUILD, "u6chunk.sym"))
        by = dict(self.patches)
        self.assertEqual(by[0x1197], bytes([0x20, sym["k_row"] & 0xFF, sym["k_row"] >> 8]))
        self.assertEqual(by[0x119D], bytes([0x20, sym["k_col"] & 0xFF, sym["k_col"] >> 8]))

    def test_nothing_else_points_into_what_it_rewrites(self):
        """Every absolute operand of `game` and of every overlay of both disks
        (ram_audit.corpus, da65's linear sweep: a superset) that names a byte
        u6chunk.s writes must come from code it replaces -- a table it
        overwrote that something else still read cost a run: $27F4, the
        sprite builder's offsets ($093B), which a first version clobbered.
        It found the old walk's entries $27E3 (the jump table's $02BA) and
        $27EA ($02D5, $338B) too, which u6walk.s now re-points."""
        import re
        import subprocess
        import tempfile
        from tools.vice import ram_audit
        sym = u6.symbols(os.path.join(u6.BUILD, "u6chunk.sym"))
        spans = dict(u6.FAST_SOURCES)["u6chunk.s"]
        written = set()
        for a, b in spans:
            written.update(range(sym[a], sym[b]))
        replaced = [r for r in u6.FAST_ORIGINAL if r[0] in (0x25FB, 0x33B8, 0x3FBD, 0x1197, 0x02BA, 0x02D5, 0x338B)]
        replaced.append((0x27CE, 0x27F4))                   # u6walk.s's: dead since
        kept = {0x3FBD}                                     # entries that are still there
        # data that the linear sweep reads as instructions, each looked at:
        allowed = {(0x4375, 0x2749),    # game: `2C 49 27` in the bytes after its last RTS
                   (0xC804, 0x2629),    # T5 combat: text bytes ($C7FE-..., after an RTS)
                   (0xC9DC, 0x26CE),    # small $18 (Look): its tables $C9D5/$C9DF/$C9E9
                   (0xC92B, 0x279B),    # small $30: the table at $C91A and on
                   (0xC95D, 0x266C)}    # small $30: the same tables
        line = re.compile(r";\s+([0-9A-F]{4})\s+([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{2})\s")
        absolute = {0x0D, 0x0E, 0x19, 0x1D, 0x1E, 0x20, 0x2C, 0x2D, 0x2E, 0x39, 0x3D, 0x3E, 0x4C, 0x4D, 0x4E,
                    0x59, 0x5D, 0x5E, 0x6C, 0x6D, 0x6E, 0x79, 0x7D, 0x7E, 0x8C, 0x8D, 0x8E, 0x99, 0x9D, 0xAC,
                    0xAD, 0xAE, 0xB9, 0xBC, 0xBD, 0xBE, 0xCC, 0xCD, 0xCE, 0xD9, 0xDD, 0xDE, 0xEC, 0xED, 0xEE,
                    0xF9, 0xFD, 0xFE}
        bad, seen = [], 0
        with tempfile.TemporaryDirectory() as tmp:
            for name, origin, data in ram_audit.corpus():
                path = os.path.join(tmp, "piece")
                with open(path + ".bin", "wb") as fh:
                    fh.write(data)
                subprocess.run(["da65", "-S", f"0x{origin:x}", "--cpu", "6502", "--comments", "4",
                                "-o", path + ".s", path + ".bin"], check=True, capture_output=True)
                for m in line.finditer(Path(path + ".s").read_text()):
                    at, op = int(m.group(1), 16), int(m.group(2), 16)
                    if op not in absolute:
                        continue
                    seen += 1
                    target = int(m.group(4) + m.group(3), 16)
                    if target not in written or target in kept or (at, target) in allowed:
                        continue
                    if name == "game" and any(a <= at < b for a, b in replaced):
                        continue
                    bad.append(f"{name} ${at:04x} -> ${target:04x}")
        self.assertGreater(seen, 3000)                      # it did look at the code
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
