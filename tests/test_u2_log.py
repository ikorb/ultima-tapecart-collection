"""Ultima II's save log (ultima/games/u2/u2log.s), the driver's own code run in py65
against the built cart: the init stub's entry (u2_boot) and the append
(u2_append), with tc_sendbyte/tc_getbyte trapped onto FakeCart.

What a unit holds is read the way the game gets it -- through the driver's
table (u2_recpage for the record) -- and checked against a model of what
was last written; u2log.py (what the launcher's page does) must agree.
Reboots, compactions, a generation wrapping, and a power cut at every flash
change of a sequence that compacts.

Skipped without py65 (the repository's .venv has it).
"""
import random
import unittest

try:
    from ultima.sim.sim6502 import Sim, PowerCut
except ImportError:
    Sim = None

from ultima.flash import regions
from ultima.launcher import u2log
from tests import test_u2_build as tb

u2 = tb.u2
SRC = 0x3000                    # where a unit's bytes come from (MOB xx's own)


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU2Log(unittest.TestCase):
    setUpClass = classmethod(tb.TestU2Build.setUpClass.__func__)
    table = tb.TestU2Build.table
    segment = tb.TestU2Build.segment

    @classmethod
    def base(cls):
        return regions.save_base("u2")

    def units(self):
        """unit -> table entry number (0: the record)"""
        return [0] + [i + 1 for i, e in enumerate(self.table()) if e["writable"]]

    def boot(self, flash):
        """A machine after the init stub: driver and log loaded, u2_boot run."""
        sim = Sim(bytes(self.segment(u2.DRIVER_ADDR)), u2.DRIVER_ADDR, self.sym)
        log = self.segment(u2.LOG_ADDR)
        sim.mem[u2.LOG_ADDR:u2.LOG_ADDR + len(log)] = log
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x36
        sim.attach_cart(flash)
        sim.call(self.sym["u2_boot"])
        self.assertEqual(sim.mem[0x01], 0x36, "the banking after the boot")
        return sim

    def write(self, sim, unit, data):
        sim.mem[SRC:SRC + len(data)] = data
        s = self.sym
        sim.mem[s["tc_dest"]], sim.mem[s["tc_dest"] + 1] = SRC & 0xFF, SRC >> 8
        sim.mem[s["tc_len"]], sim.mem[s["tc_len"] + 1] = len(data) & 0xFF, len(data) >> 8
        sim.mpu.a = unit
        sim.call(s["u2_append"])
        self.assertEqual(sim.mem[0x01], 0x36)

    def page_of(self, sim, unit):
        s = self.sym
        if unit == 0:
            return sim.mem[s["u2_recpage"]] | sim.mem[s["u2_recpage"] + 1] << 8
        e = s["u2_table"] + (unit - 1) * u2.ENTRY
        return sim.mem[e + 8] | sim.mem[e + 9] << 8

    def read(self, sim, unit):
        a = self.page_of(sim, unit) << 8
        return bytes(sim.cart.flash[a:a + 256])

    def seed(self, unit):
        if unit == 0:
            a = self.parts["rec_page"] << 8
        else:
            a = self.table()[unit - 1]["page"] << 8
        return bytes(self.flash[a:a + 256])

    def check(self, sim, want, why=""):
        """Every unit as the driver sees it, and as the page would find it."""
        for u in self.units():
            got = self.read(sim, u)
            self.assertEqual(got, want.get(u, self.seed(u)), f"unit {u} {why}")
            seed = self.page_of(self.fresh_sim, u) << 8
            a = u2log.find(sim.cart.flash, self.base(), u, seed)
            self.assertEqual(a, self.page_of(sim, u) << 8, f"unit {u}: the page disagrees {why}")

    def setUp(self):
        self.fresh = bytearray(self.flash.ljust(regions.FLASH_SIZE, b"\xff"))
        self.fresh_sim = self.boot(bytearray(self.fresh))

    def payload(self, rnd, unit):
        return bytes(rnd.randrange(256) for _ in range(256))

    # ------------------------------------------------------------------
    def test_a_fresh_cart_reads_the_seeds(self):
        self.check(self.fresh_sim, {})
        self.assertIsNone(u2log.active(self.fresh_sim.cart.flash, self.base()))

    def test_a_write_reads_back_and_survives_a_reboot(self):
        sim = self.fresh_sim
        rec = bytes(range(256))
        self.write(sim, 0, rec)
        self.check(sim, {0: rec})
        self.assertEqual(u2log.active(sim.cart.flash, self.base()), (0, 0))
        again = self.boot(sim.cart.flash)
        self.check(again, {0: rec}, "after a reboot")

    def test_many_writes_through_compactions(self):
        """300 writes of random units: compactions every ~40, both halves
        taking turns; after each write the driver and the page agree with
        the model, and every 25th a reboot finds the same."""
        rnd = random.Random(2)
        units = self.units()
        sim, want = self.fresh_sim, {}
        gens = set()
        for i in range(300):
            u = rnd.choice(units)
            want[u] = self.payload(rnd, u)
            self.write(sim, u, want[u])
            self.check(sim, want, f"after write {i}")
            gens.add(u2log.active(sim.cart.flash, self.base()))
            if i % 25 == 24:
                sim = self.boot(sim.cart.flash)
                self.check(sim, want, f"after a reboot at {i}")
        self.assertGreaterEqual(len(gens), 5, "no compaction happened")
        self.assertEqual({h for h, _g in gens}, {0, 1})

    def test_a_short_write_and_the_generation_wrapping(self):
        """A unit written short (the rest of its page stays $FF, as the
        original's SAVE would leave the file short), and a log whose half 0
        is at generation 255 compacting into half 1 at generation 0."""
        flash = bytearray(self.fresh)
        u = self.units()[3]
        full = [(0, bytes([0x11] * 256))] * u2log.DATA
        u2log.write(flash, self.base(), full, half=0, gen=255)
        sim = self.boot(flash)
        self.write(sim, u, b"\x42" * 100)
        self.assertEqual(u2log.active(sim.cart.flash, self.base()), (1, 0))
        want = {0: bytes([0x11] * 256), u: b"\x42" * 100 + b"\xff" * 156}
        self.check(sim, want)
        self.check(self.boot(sim.cart.flash), want, "after a reboot")

    def test_a_power_cut_anywhere(self):
        """A sequence that fills the half and compacts, cut after every
        flash change in turn: the reboot finds each unit's last complete
        version (the one being written: old or new), and writes on."""
        rnd = random.Random(5)
        units = self.units()
        flash = bytearray(self.fresh)
        # a half three pages from full, several units in it
        pre, want = [], {}
        for k in range(u2log.DATA - 3):
            u = units[k % 7]
            want[u] = self.payload(rnd, u)
            pre.append((u, want[u]))
        u2log.write(flash, self.base(), pre, half=1, gen=3)
        seq = [(units[(k * 5) % len(units)], self.payload(rnd, 0)) for k in range(6)]

        def run(cut):
            sim = self.boot(bytearray(flash))
            sim.cart.changes, sim.cart.cut_after = 0, cut
            model = dict(want)
            try:
                for u, data in seq:
                    before = dict(model)
                    model[u] = data
                    self.write(sim, u, data)
            except PowerCut:
                return sim.cart.flash, before, (u, data)
            return sim.cart.flash, model, None

        cuts = 0
        for cut in range(0, 400):
            after, model, pending = run(cut)
            again = self.boot(after)
            ok = [model]
            if pending:
                ok.append({**model, pending[0]: pending[1]})
            got = {u: self.read(again, u) for u in units}
            self.assertIn(got, [{u: m.get(u, self.seed(u)) for u in units} for m in ok],
                          f"cut after {cut} flash changes")
            self.write(again, units[1], b"\x5a" * 256)    # and the log goes on
            self.assertEqual(self.read(again, units[1]), b"\x5a" * 256)
            if pending is None:
                break
            cuts += 1
        self.assertGreater(cuts, 20, "the sequence never got to the compaction")


if __name__ == "__main__":
    unittest.main()
