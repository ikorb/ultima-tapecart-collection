"""Ultima 6's in-game log compaction (ultima/games/u6/u6pack.s), on the host.

When a save finds the write log full, the on-demand part fetches the
compactor over itself, the log is compacted into the other half, and the
command runs again.  These tests fill the log to a few pages short, run a
whole save through the game's driver (as test_u6_driver.py does), and check
that nothing was dropped -- wherever in the save the compaction happened,
including in the middle of a chunk file -- and that a power cut during it
leaves the log as it was before.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
import random
import unittest

try:
    from ultima.sim.sim6502 import Sim, PowerCut
except ImportError:
    Sim = None

from ultima.flash.layout import image_from
from ultima.launcher.u6log import E, KEYLEN, Log, play, view
from ultima.flash import regions
from ultima import paths

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

CMD = 0xC000


def key(k):
    return k.ljust(KEYLEN, b"\x00")


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Pack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        lo, hi = cls.p["log"]
        cls.lo, cls.mid, cls.hi = lo, lo + (hi - lo) // 2, hi

    # -- harness ---------------------------------------------------------
    def nearly_full(self, free):
        """Half 0, a long game's worth of saves, then single sectors until
        at most `free` pages are left."""
        flash = bytearray(self.flash)
        want = {}
        log = Log(flash, self.lo, self.mid)
        rng = random.Random(free)
        play(log, rng, want, 40)
        while log.free() > free:
            pg = rng.randbytes(256)
            log.append(bytes([1, 0, 6, 9]), [pg], False)
            want[key(bytes([1, 0, 6, 9]))] = pg
        return flash, want, log

    def game(self, flash, log):
        sim = Sim(self.p["game"], u6.GAME_ADDR, self.p["rsym"])
        cart = sim.attach_cart(flash)
        sim.mem[0x27] = 0x00                # half A shown: B is idle
        r = self.p["rsym"]
        count = (self.mid - log.dir) // E
        for name, value in (("u6_logdir", log.dir), ("u6_logdata", log.data)):
            sim.mem[r[name]:r[name] + 3] = [value & 0xFF, value >> 8 & 0xFF, value >> 16]
        sim.mem[r["u6_dircount"]:r["u6_dircount"] + 2] = [count & 0xFF, count >> 8]
        return sim, cart

    def run_cmd(self, sim, cmd, disk=None):
        if disk is not None:
            sim.mpu.x = {"1A": 0, "1B": 2}[disk]
            sim.call(0x2823)
        sim.mem[CMD:CMD + len(cmd)] = list(cmd)
        sim.mpu.x, sim.mpu.y = CMD & 0xFF, CMD >> 8
        sim.call(0x29BE)
        return sim.mpu.p & 1

    def u24(self, sim, name):
        a = self.p["rsym"][name]
        return sim.mem[a] | sim.mem[a + 1] << 8 | sim.mem[a + 2] << 16

    def log_view(self, sim, flash):
        a = self.p["rsym"]["u6_dircount"]
        return view(flash, self.u24(sim, "u6_logdir"), sim.mem[a] | sim.mem[a + 1] << 8)

    def save(self, sim, want):
        """A save as the game makes it (traced): a chunk file, the BAM, the
        save area.  `want` gets what the log should then say."""
        start = self.p["starts"]["SCC"]
        chain = [start, (16, 17), (16, 18)]
        new = bytes((i * 11 + 5) & 0xFF for i in range(254 * 2 + 77))
        self.assertEqual(self.run_cmd(sim, b"!SCC\xff\x00\x40", "1A"), 0)
        pages = []
        for i, (t, s) in enumerate(chain):
            if i + 1 < len(chain):
                sec = bytes(chain[i + 1]) + new[254 * i:254 * (i + 1)]
            else:
                tail = new[254 * i:]
                sec = (bytes([0, len(tail) + 1]) + tail).ljust(256, b"\x00")
            pages.append(sec)
            sim.mem[0x5000:0x5100] = list(sec)
            self.assertEqual(self.run_cmd(sim, bytes([0x26, t, s, 0, 0, 0x00, 0x50])), 0)
        want[key(b"/SCC")] = b"".join(pages)
        bam = bytes(range(256))
        sim.mem[0x5000:0x5100] = list(bam)
        self.assertEqual(self.run_cmd(sim, bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])), 0)
        for s in range(9, 21):
            pg = bytes([s ^ 0x5A]) * 256
            sim.mem[0x5000:0x5100] = list(pg)
            self.assertEqual(self.run_cmd(sim, bytes([0x26, 6, s, 0, 0, 0x00, 0x50])), 0)
            want[key(bytes([1, 0, 6, s]))] = pg
        return new

    # -- tests -------------------------------------------------------------
    def test_a_save_into_a_full_log_loses_nothing(self):
        """For a few fill levels, so the compaction lands at different
        points of the save: in the chunk file's session, at the BAM, among
        the save sectors."""
        for free in (2, 3, 4, 6, 9, 14):
            with self.subTest(free=free):
                flash, want, log = self.nearly_full(free)
                sim, cart = self.game(flash, log)
                new = self.save(sim, want)
                erases = [c for c in cart.log if c[0] == "erase"]
                self.assertEqual(len(erases), 64, "not exactly one compaction")
                self.assertTrue(self.mid <= self.u24(sim, "u6_logdir") < self.hi,
                                "the log did not move to half 1")
                self.assertEqual(self.log_view(sim, cart.flash), want)
                self.assertEqual(cart.flash[self.lo:self.mid], b"\xff" * (self.mid - self.lo))
                self.assertEqual(cart.flash[self.hi - E:self.hi - E + 16],
                                 b"\xfeLOG" + bytes(8) + bytes([1, 0, 0xFE, 0xFF]))
                # and the game reads its save back through the driver
                self.assertEqual(self.run_cmd(sim, b"/SCC\x80\x00\x40"), 0)
                self.assertEqual(bytes(sim.mem[0x4000:0x4000 + len(new)]), new)
                self.assertEqual(self.run_cmd(sim, bytes([0x5E, 6, 12, 0, 0, 0x00, 0x40]), "1A"), 0)
                self.assertEqual(bytes(sim.mem[0x4000:0x4100]), bytes([12 ^ 0x5A]) * 256)

    def test_the_game_screen_is_put_back(self):
        flash, want, log = self.nearly_full(3)
        sim, _cart = self.game(flash, log)
        sim.mem[0xCC00 + 24 * 40 + 23] = 0x89   # the frame's colour there: the
                                                # access light puts it back (u6.inc)
        before = bytes(sim.mem[0xCC00:0xD000]) + bytes(sim.mem[0xE000:0x10000])
        self.save(sim, want)
        after = bytes(sim.mem[0xCC00:0xD000]) + bytes(sim.mem[0xE000:0x10000])
        self.assertEqual(before, after)

    def test_a_power_cut_in_a_compaction_keeps_the_log_as_it_was(self):
        """Snapshot the log at the compaction's first erase; cut the power at
        points through the rest of it; boot.  The log must say what it said
        at the snapshot -- everything before the save that triggered it."""
        flash, want, log = self.nearly_full(4)
        snap, erases = {}, []

        def erase(cart):
            if not erases:
                snap["view"] = self.log_view(sim, cart.flash)
            erases.append(cart.changes)

        sim, cart = self.game(bytearray(flash), log)
        cart.before_erase = erase
        self.save(sim, dict(want))
        blocks = (self.mid - self.lo) // 0x1000
        self.assertEqual(len(erases), 2 * blocks)
        at = [e - erases[0] for e in erases]       # changes into the compaction
        header = at[blocks]                         # written just before the old half goes
        for k in (0, 1, at[blocks - 1] + 1, (at[blocks - 1] + header) // 2,
                  header - E - 1, header - E, header - 7, header - 1, header,
                  at[blocks + 1], at[-1]):
            with self.subTest(cut=k):
                sim, cart = self.game(bytearray(flash), log)
                cart.cut_after = erases[0] + k
                with self.assertRaises(PowerCut):
                    self.save(sim, dict(want))
                bsim, bcart = self.boot(cart.flash)
                b = self.p["bsym"]
                n = bsim.mem[b["u6_dircount"]] | bsim.mem[b["u6_dircount"] + 1] << 8
                d = sum(bsim.mem[b["u6_logdir"] + i] << 8 * i for i in range(3))
                self.assertEqual(view(bcart.flash, d, n), snap["view"])

    def boot(self, flash):
        sim = Sim(self.p["boot_image"], 0xC000, self.p["bsym"])
        sim.mem[0xC578:0xC578 + len(self.p["boot_piece2"])] = list(self.p["boot_piece2"])
        sim.mem[u6.INIT_ADDR:u6.INIT_ADDR + len(self.p["init"])] = list(self.p["init"])
        cart = sim.attach_cart(flash)
        # init_u6's own 2-bit receive (g_read), answered as the 1-bit one
        isym = u6.symbols(os.path.join(paths.BUILD, "init_u6.sym"))
        sim.traps[isym["tc_getbyte_guard"]] = sim.traps[self.p["bsym"]["tc_getbyte"]]
        sim.traps[0xC00C] = lambda s: None
        sim.mem[0x01] = 0x35
        sim.call(u6.INIT_ADDR)
        return sim, cart


if __name__ == "__main__":
    unittest.main()
