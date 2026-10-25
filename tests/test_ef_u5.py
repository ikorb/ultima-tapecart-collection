"""The EasyFlash launcher's 5 (ultima/ef/efu5.s): Ultima V from the tapecart,
with its music from the EasyFlash -- on the host, in py65 on efsim's
EasyFlash with the tapecart on sim6502.FakeCart, as tests/test_ef_xfer.py
runs the launcher.

  * with the built collection on the tapecart, the launcher ends at the
    init stub ($0200) with the four boot segments where the menu puts
    them, the patches made (build_efmusic's: the driver's two register
    writes and xyzzy's hook), U5's options byte poked as the page pokes
    it from the settings, $C024 clear, the music's bank selected and the
    cart off;
  * it refuses, and changes nothing, without a tapecart, with a collection
    of another save layout, with another build's descriptor or segments,
    and with a save a power cut left in the journal.

Skipped without py65, or when the EasyFlash build has no Ultima V (its disks
missing).
"""
import os
import unittest

from tests import test_ef_xfer as T                   # noqa: E402
from ultima.sim.sim6502 import FakeCart                # noqa: E402
from ultima.flash import regions                       # noqa: E402

FIVE = ord("5")
ENTRY = 0x0200


@unittest.skipIf(T.EFSim is None, "py65 is not installed (use the repository's .venv)")
class TestEFU5(T.TestEFLauncher):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.p.get("u5"):
            raise unittest.SkipTest("the EasyFlash build has no Ultima V")
        cls.u = cls.p["u5"]

    def tapecart(self, opts=0x00):
        f = super().tapecart()
        f[regions.SETTINGS + self.u["opt_at"]] = opts
        return f

    def start(self, tflash):
        cart = FakeCart(tflash)
        sim, _d, _t, text = self.launch(self.fresh(), [FIVE], tapecart=cart, until=ENTRY)
        return sim, cart, text

    def refused(self, cart, says):
        flash = self.fresh()
        before = bytes(cart.flash) if cart else None
        sim, _d, _t, text = self.launch(flash, [FIVE, T.SPACE, T.L], tapecart=cart)
        self.assertIn(says, text, text[-400:])
        self.assertEqual(bytes(sim.mem.flash()), bytes(flash))
        if cart:
            self.assertEqual(bytes(cart.flash), before)
        # nothing of Ultima V's: the launcher's own bytes where its segments go
        org = self.lsym["PAGE_ORG"]
        launcher = self.p["launcher"]
        self.assertEqual(bytes(sim.mem.ram[0x6C00:0x6C00 + 64]),
                         launcher[0x6C00 - org:0x6C00 - org + 64])
        return text

    def test_5_starts_ultima_v(self):
        for opts, says in ((0x00, "Cheats: none"), (0x35, "Cheats: F U M X"),
                           (0x11, "Cheats: F U"), (0xFF, "Cheats: F U M X")):
            with self.subTest(opts=hex(opts)):
                tflash = self.tapecart(opts)
                sim, cart, text = self.start(tflash)
                m, u = sim.mem, self.u
                self.assertIn(says, text, text[-400:])
                ram = bytearray(0x10000)
                for _a, _n, dest, data in u["segs"]:
                    ram[dest:dest + len(data)] = data
                for addr, old, new in u["patches"]:
                    self.assertEqual(bytes(ram[addr:addr + len(old)]), old)
                    ram[addr:addr + len(new)] = new
                ram[u["pt_opts"]] = opts & u["caps"]
                for _a, n, dest, _data in u["segs"]:
                    self.assertEqual(bytes(m.ram[dest:dest + n]), bytes(ram[dest:dest + n]), hex(dest))
                self.assertEqual(m.ram[u["pt_opts"]], opts & u["caps"])
                self.assertEqual(m.ram[0xC024], 0x00)
                self.assertEqual((m.bank, m.control), (u["bank"], 0x04))
                self.assertEqual(bytes(cart.flash), bytes(tflash), "nothing written to the tapecart")

    def test_nothing_without_the_right_tapecart(self):
        self.refused(None, "none answers")
        wrong = self.tapecart()
        wrong[regions.SETTINGS + regions.SET_LAYOUT] = regions.LAYOUT + 1
        self.refused(FakeCart(wrong), "has no Ultima collection")

    def test_nothing_from_another_build(self):
        u = self.u
        other = self.tapecart()
        other[u["desc_at"] + 4] ^= 0x01                 # a segment's length
        self.refused(FakeCart(other), "another")
        for i, (a, n, _dest, _data) in enumerate(u["segs"]):
            with self.subTest(segment=i):
                other = self.tapecart()
                other[a + n - 1] ^= 0x40                # its last byte
                self.refused(FakeCart(other), "another")

    def test_nothing_with_a_save_cut_short(self):
        """A journal the first stage would finish: anything but $FF $FF at its
        start (asm/boot.s jn_one), a whole one or a header begun."""
        for head in (b"JN" + bytes([0x70, 0x1D]), b"J\xff", b"\xffN"):
            with self.subTest(head=head):
                tflash = self.tapecart()
                j = self.u["journal"]
                tflash[j:j + len(head)] = head
                self.refused(FakeCart(tflash), "cut")


class TestEFU5Absent(unittest.TestCase):
    def test_no_5_without_ultima_vs_disks(self):
        """A build for Ultima VI alone: no Ultima V part, no 5 on the page."""
        import tempfile
        from unittest import mock
        from ultima.ef import build as efb
        saved = efb.BUILD
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(efb, "u5_disks", lambda: False):
            efb.BUILD = tmp
            try:
                p = efb.build()
                with open(os.path.join(tmp, "efpage_data.s")) as fh:
                    data = fh.read()
            finally:
                efb.BUILD = saved
        self.assertIsNone(p["u5"])
        self.assertNotIn("U5L_SRC", data)
        self.assertNotIn("u5_go", p["lsym"])
        self.assertLess(len(p["launcher"]), len(T.built()["launcher"]), "the 5's line and code")


# (TestEFLauncher's own tests are not run again from here)
for _name in [n for n in dir(T.TestEFLauncher) if n.startswith("test_")]:
    if _name not in TestEFU5.__dict__:
        setattr(TestEFU5, _name, None)

if __name__ == "__main__":
    unittest.main()
