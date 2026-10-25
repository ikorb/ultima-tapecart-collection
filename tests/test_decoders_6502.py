"""Run the 6502 zx02 decoders themselves, on the host, against real units.

zx.decode proves the *format* the build writes; this proves the 6502 code the
drivers carry decodes it: asm/zx02s.s (Ultima 4 and 5) and asm/zx02a.s (the
zero-page-free variant for Ultima 6, which decodes with interrupts on).  Both
run instruction by instruction under py65, fed through the same trap that
stands in for tc_stream_byte (see sim6502.py), and must reproduce each unit
exactly, consume the whole stream, and -- for zx02s.s -- leave the zero page
it borrows as it found it.

Skipped when py65 is not importable; `make test` uses the repository's .venv,
which has it.
"""
import os
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:                             # no py65 outside the venv
    Sim = None

from ultima.disks.d64 import D64
from ultima.flash import zx
from ultima import paths


def units():
    """A spread of real units: map sectors, tables, code, text."""
    out = []
    surface = D64(paths.disk("u6-1a"))
    for t in (20, 26, 30, 33, 35):
        for s in range(0, 16, 5):
            out.append(("U6 1A T%d S%d" % (t, s), bytes(surface.sector(t, s))))
    game = D64(paths.disk("u6-3b"))
    for name in ("COLORS", "TILEFLAGS", "POINTER"):
        out.append(("U6 " + name, game.file(name)[0][2:]))
    pop = D64(paths.disk("u6-2a"))

    out.append(("U6 T001", pop.file("T001")[0]))
    u4 = D64(paths.disk("u4c"))
    for blk in (1, 100, 200, 300):
        out.append(("U4 C block %d" % blk, bytes(u4.sector(*D64.from_linear(blk)))))
    return out


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestDecoders6502(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = [(n, u, zx.crunch(u)) for n, u in units()]
        cls.units = [(n, u, s) for n, u, s in cls.units if s is not None]

    def check(self, sim, decode, zp=None):
        for name, unit, stream in self.units:
            with self.subTest(unit=name):
                if zp is not None:
                    sim.mem[zp:zp + 4] = [0x11, 0x22, 0x33, 0x44]
                got, rest = decode(stream, 0x4000, len(unit))
                self.assertEqual(got, unit)
                self.assertEqual(rest, b"", "the decoder left stream bytes unread")
                if zp is not None:
                    self.assertEqual(list(sim.mem[zp:zp + 4]), [0x11, 0x22, 0x33, 0x44],
                                     "zx02s.s did not restore its zero page")

    def test_zx02s_the_decoder_u4_and_u5_ship(self):
        sim = Sim.assemble(os.path.join(paths.ASM, "zx02s.s"), 0x1000,
                           defines={"ZX_ZP": 0xFB})
        self.check(sim, sim.zx02s_decode, zp=0xFB)

    def test_zx02a_the_zero_page_free_variant(self):
        sim = Sim.assemble(os.path.join(paths.ASM, "zx02a.s"), 0x1000)
        self.check(sim, sim.zx02a_decode)
        # and it really does not touch the zero page
        before = list(sim.mem[0:0x100])
        name, unit, stream = self.units[0]
        sim.zx02a_decode(stream, 0x4000, len(unit))
        self.assertEqual(list(sim.mem[2:0x100]), before[2:0x100])


if __name__ == "__main__":
    unittest.main()
