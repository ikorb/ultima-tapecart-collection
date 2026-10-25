"""Ultima 6's optional REU read cache (ultima/games/u6/u6reu.s): the real driver and the
real init tail in py65 over the real flash image, with a model of the REU's
registers and DMA (reumodel.py) and of the cart.  Checks that

  * the init finds an REU of 256 KB or more, clears its flag table (the REU's
    contents are noise at power-on, or another session's), and leaves
    rc_on = 1 -- and finds nothing (rc_on = 0, no harm) with a 128 KB REU, an
    Action Replay's RAM at $DF00 (registers that hold values, no DMA), or an
    open bus;
  * a whole-sector read comes from the cart the first time and from the REU
    after, with the same bytes, and the cart not asked for the page again;
  * what the cache does not take -- 64-byte and odd reads, the block map's 4
    bytes, loads by name -- still goes to the cart and comes out right;
  * the REU's registers are only reached with I/O banked in (else no DMA
    happens and the data would be wrong), and $01 is put back.

Skipped without py65.
"""
import importlib.util
import os
import re
import unittest
from pathlib import Path

try:
    from ultima.sim.sim6502 import Sim
    from tests.reumodel import REU
except ImportError:
    Sim = None

from ultima.flash.layout import image_from
from ultima.flash import regions
from ultima import paths

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

CMD, DEST = 0xC000, 0x4000


def labels():
    out = {}
    for line in Path(os.path.join(paths.BUILD, "u6reu.sym")).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Reu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        cls.disks = cls.p["disks"]
        cls.sym = labels()
        cls.pages = cls.p["pages"]

    def boot(self, kind="reu", kb=512, init=True):
        sim = Sim(self.p["game"], u6.GAME_ADDR, self.p["rsym"])
        self.cart = sim.attach_cart(self.flash)
        self.reu = REU(sim, kind, kb)
        sim.mem[0x27] = 0x00
        sim.mem[u6.INIT_AT:u6.INIT_AT + len(self.p["init_copy"])] = list(self.p["init_copy"])
        sim.traps[0x03FC] = lambda s: None            # the init's end: JMP $03FC
        sim.mem[1] = 0x34
        if init:
            sim.call(self.sym["reu_init"])
        self.sim = sim
        return sim

    def on(self):
        return self.sim.mem[self.sym["rc_on"]]

    def read(self, tag, t, s, off=0, cnt=0, dest=DEST):
        self.sim.mpu.x = {"1A": 0, "1B": 2}[tag]
        self.sim.call(0x2823)
        cmd = bytes([0x5E, t, s, off, cnt, dest & 0xFF, dest >> 8])
        self.sim.mem[CMD:CMD + len(cmd)] = list(cmd)
        self.sim.mpu.x, self.sim.mpu.y = CMD & 0xFF, CMD >> 8
        self.sim.mem[dest:dest + 256] = [0xA5] * 256
        before = len(self.cart.log)
        self.sim.call(0x29BE)
        n = cnt or 256
        return bytes(self.sim.mem[dest:dest + n]), [e for e in self.cart.log[before:] if e[0] == "read"]

    def sectors(self):
        out = []
        for tag in ("1A", "1B"):
            d = self.disks[tag]
            infile = u6.file_sectors(d)
            for t in (1, 2, 3, 4, 5, 19, 20, 24, 26, 30, 33, 35):
                for s in (0, 5, 9, 11, 16):
                    fixed = t == u6.REST_TRACK and s in u6.REST_SECTORS     # test_u6_rest
                    if s < u6.SECTORS[t] and (t, s) not in infile and not (tag == "1A" and t == 6) \
                            and not fixed:
                        out.append((tag, t, s))
        return out

    # -- the init ---------------------------------------------------------
    def test_the_init_finds_the_reu_and_clears_its_flags(self):
        """The read cache's flags and the write cache's counts (u6wc.s): bank 3's
        first kilobyte."""
        self.boot()
        self.assertEqual(self.on(), 1)
        self.assertLessEqual(self.pages, 0x300)
        flags = self.reu.ram[3 * 65536:3 * 65536 + 0x400]
        self.assertEqual(bytes(flags), bytes(0x400), "the flags and counts are not clear")
        self.assertNotEqual(bytes(self.reu.ram[3 * 65536 + 0x400:3 * 65536 + 0x440]), bytes(64),
                            "the REU past them was touched")
        self.assertEqual(self.sim.mem[1], 0x34, "$01 not put back")

    def test_a_128k_reu_an_action_replay_and_nothing_are_not_used(self):
        for kind, kb in (("reu", 128), ("ar", 512), ("none", 512)):
            self.boot(kind, kb)
            self.assertEqual(self.on(), 0, (kind, kb))
            want = bytes(self.disks["1A"].sector(26, 4))
            got, reads = self.read("1A", 26, 4)
            self.assertEqual(got, want)
            got, reads2 = self.read("1A", 26, 4)
            self.assertEqual(got, want)
            self.assertTrue(reads2, "no REU: every read goes to the cart")

    # -- the cache --------------------------------------------------------
    def test_a_sector_comes_from_the_cart_once_and_then_from_the_reu(self):
        self.boot()
        want = bytes(self.disks["1A"].sector(26, 4))
        got, reads = self.read("1A", 26, 4)
        self.assertEqual(got, want)
        self.assertIn(256, [n for _t, _a, n in reads])
        dma = len(self.reu.log)
        got, reads = self.read("1A", 26, 4)
        self.assertEqual(got, want)
        self.assertNotIn(256, [n for _t, _a, n in reads], "the page was fetched from the cart again")
        self.assertGreater(len(self.reu.log), dma)
        self.assertEqual(self.sim.mem[1], 0x34)

    def test_every_sector_is_right_twice_and_the_second_time_is_cheap(self):
        self.boot()
        cheap = 0
        for tag, t, s in self.sectors():
            want = bytes(self.disks[tag].sector(t, s))
            a, ra = self.read(tag, t, s)
            b, rb = self.read(tag, t, s)
            self.assertEqual(a, want, (tag, t, s))
            self.assertEqual(b, want, (tag, t, s, "second"))
            if 256 not in [n for _t, _a, n in rb]:
                cheap += 1
        self.assertGreater(cheap, 100)

    def test_a_cached_page_is_not_the_stale_noise_of_the_reu(self):
        self.boot()
        for _ in range(3):
            got, _r = self.read("1A", 30, 4)
            self.assertEqual(got, bytes(self.disks["1A"].sector(30, 4)))

    def test_what_the_cache_does_not_take_goes_on_to_the_cart(self):
        self.boot()
        d = self.disks["1A"]
        want = bytes(d.sector(26, 4))
        for off, cnt in ((0, 64), (64, 64), (0x40, 16), (34, 222), (0, 128)):
            for _ in range(2):
                got, reads = self.read("1A", 26, 4, off, cnt)
                self.assertEqual(got, want[off:off + cnt], (off, cnt))
                self.assertTrue(any(n == cnt for _t, _a, n in reads), (off, cnt, "went to the cart"))

    def test_loads_by_name_are_untouched(self):
        self.boot()
        for tag, name in (("2A", "T005"), ("3A", "T201")):
            from tests.test_u6_driver import chain_bytes
            want = chain_bytes(self.disks[tag], name)
            cmd = b"/" + name.encode() + b"\x80" + bytes([DEST & 0xFF, DEST >> 8])
            self.sim.mem[CMD:CMD + len(cmd)] = list(cmd)
            self.sim.mpu.x, self.sim.mpu.y = CMD & 0xFF, CMD >> 8
            self.sim.call(0x29BE)
            self.assertEqual(bytes(self.sim.mem[DEST:DEST + len(want)]), want, name)

    def test_the_ram_under_the_io(self):
        """Overlay $34 (1A T19 S8-9) goes to $D400-$D5FF, the save's BAM (T18 S0) to
        $D500 too: RAM under the I/O, which a DMA with the I/O banked in does not
        reach.  A moongate's window reload after a save: the BAM in $D500, then
        overlay $34 from the REU over it -- it has to arrive (the first version
        left the BAM there, and the game ran into it on real hardware)."""
        self.boot()
        d = self.disks["1A"]
        ovl, bam = bytes(d.sector(19, 8)) + bytes(d.sector(19, 9)), bytes(d.sector(18, 0))
        for k, dest in enumerate((0xD400, 0xD500)):          # the boot's load: misses
            got, reads = self.read("1A", 19, 8 + k, dest=dest)
            self.assertEqual(got, ovl[k * 256:k * 256 + 256])
            self.assertIn(256, [n for _t, _a, n in reads])
        for _ in range(2):                                   # two saves, two reloads
            got, _r = self.read("1A", 18, 0, dest=0xD500)
            self.assertEqual(got, bam)
            for k, dest in enumerate((0xD400, 0xD500)):
                got, reads = self.read("1A", 19, 8 + k, dest=dest)
                self.assertEqual(got, ovl[k * 256:k * 256 + 256], f"overlay $34 page {k} at ${dest:04X}")
                self.assertNotIn(256, [n for _t, _a, n in reads], "not from the REU")
        self.assertEqual(self.reu.io_hits, 0, "a DMA reached the chips")
        self.assertEqual(self.sim.mem[1], 0x34)

    def test_the_reu_is_only_reached_with_io_banked_in(self):
        """A hit's data came by DMA (the model does nothing with I/O out), $01 is back."""
        self.boot()
        self.read("1A", 26, 4)
        dma = len(self.reu.log)
        got, reads = self.read("1A", 26, 4)
        self.assertEqual(got, bytes(self.disks["1A"].sector(26, 4)))
        self.assertGreater(len(self.reu.log), dma)
        self.assertEqual(self.sim.mem[1], 0x34)


if __name__ == "__main__":
    unittest.main()
