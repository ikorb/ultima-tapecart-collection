"""Akalabeth on the cart: the program as the build unpacks it from Genesis
Project's file, its three patches, and the segments the menu loads.

The program runs through BASIC's ROM, which is not here, so it does not run
on the host: tools/vice/u0_check.py plays it from the cart in VICE.  What the
host can check is that nothing in it loads any more -- no GOSUB to the LOAD
routine is left, nor the trainer's -- and that each patch is a run of the
runtime's empty statement over whole statements.
"""
import importlib.util as _il
import os
import unittest

from ultima import paths
from ultima.disks.d64 import D64
from ultima.flash import regions
from ultima.flash import zx
from ultima.flash.tcrt import TCRT

try:
    import py65  # noqa: F401
except ImportError:
    py65 = None


def _load_game(name):
    spec = _il.find_spec(f"ultima.games.{name}.build")
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


u0 = _load_game("u0")
IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
GOSUB, GOTO = 0x1A, 0x19
LOAD_ROUTINE = 0x6261           # FL$ loaded: SYS 57812 FL$,U,1: SYS 65493


@unittest.skipIf(py65 is None, "py65 is not installed (use the repository's .venv)")
class TestU0Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = u0.parts()
        cls.flash = TCRT.read(IMAGE).flash
        disk = D64(paths.disk("u0"))
        main, _ok = disk.file(u0.MAIN_FILE)
        cls.lib = disk.file(u0.LIB_FILE)[0][2:]
        cls.unpacked = u0.unpack(main)
        desc = cls.flash[regions.desc_offset("u0"):regions.desc_offset("u0") + 64]
        cls.entry = desc[0] | desc[1] << 8
        cls.segments = {}
        for i in range(desc[2]):
            o = 3 + 7 * i
            off = desc[o] << 8 | desc[o + 1] << 16
            length = desc[o + 2] | desc[o + 3] << 8
            blob = bytes(cls.flash[off:off + length])
            cls.segments[desc[o + 4] | desc[o + 5] << 8] = \
                zx.unsized(blob) if desc[o + 6] & zx.SEG_COMP else blob

    def at(self, addr):
        return addr - u0.PROG_ORG

    def test_the_unpack_is_the_pinned_program(self):
        self.assertEqual(self.unpacked, u0.PROGRAM)
        self.assertEqual(len(self.unpacked), u0.PROG_END - u0.PROG_ORG)

    def test_the_segments_are_the_program_lib_and_the_init_stub(self):
        self.assertEqual(sorted(self.segments), [u0.INIT_ORG, u0.PROG_ORG, u0.LIB_ORG])
        self.assertEqual(self.segments[u0.PROG_ORG], self.parts["program"])
        self.assertEqual(self.segments[u0.LIB_ORG], self.lib)
        self.assertEqual(self.entry, u0.INIT_ORG)
        init = self.segments[u0.INIT_ORG]
        self.assertEqual(u0.INIT_ORG + len(init), 0x0400, "the stub's segment ends the tape buffer")
        self.assertEqual(init[u0.FLAGS - u0.INIT_ORG:], bytes(4), "the trainer's flags start off")

    def test_the_init_stub_starts_the_runtime(self):
        """MEMBOT/MEMTOP, BASIC's vectors and zero page, $C0, then SYS 2076."""
        init = self.segments[u0.INIT_ORG]
        code = init[:init.index(bytes([0x4C, 0x1C, 0x08])) + 3]
        for call in (0xE453, 0xE3BF):
            self.assertIn(bytes([0x20, call & 0xFF, call >> 8]), code)
        self.assertIn(bytes([0xA9, 0x01, 0x85, 0xC0]), code)
        self.assertEqual(code[-4], 0x58, "CLI before the runtime")
        self.assertEqual(u0.ENTRY, 0x081C)
        self.assertEqual(self.unpacked[self.at(0x0801):self.at(0x0801) + 12],
                         bytes([0x1A, 0x08, 0x01, 0x00, 0x9E]) + b"2076" + bytes([0x14] * 3))

    def test_the_patches_are_whole_runs_of_the_empty_statement(self):
        """The program differs from the unpack only in the three runs, each
        all `:` -- opcode $3A, whose handler only steps on ($0ECB)."""
        prog, orig = self.parts["program"], self.unpacked
        diff = [a + u0.PROG_ORG for a in range(len(prog)) if prog[a] != orig[a]]
        runs = [(first, last) for first, last, *_ in u0.FILLS]
        for a in diff:
            self.assertTrue(any(f <= a <= l for f, l in runs), hex(a))
        for first, last in runs:
            self.assertEqual(prog[self.at(first):self.at(last) + 1],
                             bytes([u0.COLON]) * (last - first + 1))
        handler = 0x087A, 0x0817                    # the opcode table's lo, hi
        lo, hi = (orig[self.at(t) + u0.COLON] for t in handler)
        self.assertEqual(lo | hi << 8, 0x0ECB)

    def test_nothing_loads_and_the_trainer_does_not_ask(self):
        """No GOSUB to the LOAD routine is left (LIB's and the pictures'
        were the only ones), nor the one to the trainer's questions."""
        prog, orig = self.parts["program"], self.unpacked

        def calls(data, target):
            pat = bytes([GOSUB, target >> 8, target & 0xFF])
            return [i + u0.PROG_ORG for i in range(len(data) - 2) if data[i:i + 3] == pat]
        self.assertEqual(len(calls(orig, LOAD_ROUTINE)), 10, "LIB and the 3 x 3 pictures")
        self.assertEqual(calls(prog, LOAD_ROUTINE), [])
        self.assertEqual(calls(orig, 0x76E6), [0x20A2])
        self.assertEqual(calls(prog, 0x76E6), [])

    def test_the_options_poke_the_trainer_s_flags(self):
        o = self.parts["options"]
        self.assertEqual(o["addr"], 0, "no options byte: the game has no driver")
        self.assertEqual(o["caps"], sum(u0.TRAINER))
        self.assertEqual(sorted(a for lst in o["pokes"].values() for a, _v in lst),
                         list(range(0x03FC, 0x0400)))
        self.assertTrue(all(v == 100 for lst in o["pokes"].values() for _a, v in lst))
        # the game's own test, PEEK(n)=100, at each flag's places
        prog = self.parts["program"]
        for flag in range(0x03FC, 0x0400):
            pat = bytes([0xA7, flag >> 8, flag & 0xFF])
            uses = [i + u0.PROG_ORG for i in range(len(prog) - 2) if prog[i:i + 3] == pat]
            outside = [a for a in uses if not 0x76E6 <= a < 0x7850]     # not the trainer's
            self.assertTrue(outside, hex(flag))

    def test_no_segment_is_in_the_menu_s_window(self):
        for dest, data in self.segments.items():
            self.assertTrue(dest + len(data) <= 0x8700 or dest >= 0xA100, hex(dest))

    def test_no_saves(self):
        self.assertEqual(self.parts["save_end"], 0)
        self.assertEqual(regions.save_region("u0"), (0, 0))
        self.assertIsNone(self.parts["xfer"])
        self.assertIsNone(self.parts["journey"])


if __name__ == "__main__":
    unittest.main()
