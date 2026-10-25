"""Export and import of saved games through the launcher's page, on the host.

The page (asm/page.s, page_xfer.s) runs in py65 with the KERNAL's I/O calls
trapped onto fakedrive.FakeDrive, a 1541 over a copy of the original disk
image in memory.  For every game with a saved game on disk (U1-U5):

  * export a seeded save (test_page's) onto the original disk, then import
    that disk into a fresh cart: every save slot comes back identical;
  * what the export wrote is what the game itself would find: the slots'
    sectors, or files with the game's load address;
  * a wrong disk is refused, a missing drive reported, and neither the disk
    nor the cart is touched.

Skipped without py65 (the repository's .venv has it).
"""
import json
import os
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64
from ultima.sim.fakedrive import FakeDrive, Disk
from ultima.flash.tcrt import TCRT
from ultima.launcher import launcher
from ultima.flash import regions
from tests import test_page
from ultima.sim import pagesim
from ultima.launcher import u2log
from ultima import paths

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
RET, Y, N_, B, SPACE, CANCEL = 13, ord("Y"), ord("N"), ord("B"), 32, 0x5F

DISKS = {"u1": ["u1"], "u2": ["u2b"], "u3": ["u3b"], "u4": ["u4c"], "u5": ["u5-2a", "u5-2b"]}
WRONG = {"u1": "u4a", "u2": "u2a", "u3": "u3a", "u4": "u4a", "u5": "u5-1a"}


def disk_image(game, i=0):
    with open(paths.disk(DISKS[game][i]), "rb") as fh:
        return fh.read()


class Described:
    """A disk from build/xfer.json; its slots as attribute objects."""
    def __init__(self, d):
        self.label = d["label"]
        self.slots = [type("Slot", (), dict(sl))() for sl in d["slots"]]
        for sl, raw in zip(self.slots, d["slots"]):
            if "sectors" in raw:
                sl.sectors = [tuple(x) for x in raw["sectors"]]


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestXfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fresh = bytes(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cls.image = test_page.launcher_prg()
        cls.sym = launcher.symbols()
        cls.s = test_page.page_syms()

    def run_page(self, flash, game, keys, disk):
        """keys: ints, or ("swap", image) -- another disk in the drive."""
        cart, drv, _taken, _text = pagesim.run_page(flash, game, keys, disk, self.image, self.sym,
                                                    getattr(self, "device", 8), name="ULTIMA X",
                                                    limit=400_000_000)
        return cart, drv

    def xfer(self, game):
        """The game's disks and slots, as its build described them."""
        with open(os.path.join(paths.BUILD, "xfer.json")) as fh:
            return [Described(d) for d in json.load(fh)[game]]

    def seeded(self, game):
        flash = bytearray(self.fresh)
        test_page.SEEDS[game](flash, self.s)
        return flash

    def import_keys(self, game, disks):
        keys = [ord("I"), ord("D"), Y, RET]
        for d in disks[1:]:
            keys += [("swap", d), RET]
        return keys + [SPACE, B]

    def slot_bytes(self, flash, sl):
        """What a slot holds, as far as the game can tell."""
        base = sl.base
        if sl.hdr & 0x80:           # Ultima II: its unit's newest, or its seed
            base = u2log.find(flash, self.s["U2_LOG"], sl.hdr & 0x7F, base)
            n = len(sl.sectors) * 256 if hasattr(sl, "sectors") else sl.hi
            return bytes(flash[base:base + n])
        if sl.hdr == 0:
            n = len(sl.sectors) * 256 if hasattr(sl, "sectors") else sl.hi
            return bytes(flash[base:base + n])
        hdr = bytes(flash[base:base + 4])
        if hdr[:2] != b"\xa5\x5a":
            return None
        n = hdr[2] * 256 if sl.hdr == 2 else hdr[2] | hdr[3] << 8
        return hdr + bytes(flash[base + 0x100:base + 0x100 + n])

    def test_another_editions_name_is_taken_a_relabel_is_not(self):
        """The 1984 Scenario disk is "ULTIMA III-SCEN." (the Trilogy's "PLAYER
        MASTER"): an import from it is done; a cracker's relabel is refused."""
        disk = bytearray(disk_image("u3"))
        o = D64.offset(18, 0)
        for name, done in ((b"ULTIMA III-SCEN.", True), (b"ULTIMA III", False)):
            disk[o + 0x90:o + 0xA0] = name.ljust(16, b"\xa0")
            keys = self.import_keys("u3", [bytes(disk)])
            if not done:
                keys = keys[:4] + [CANCEL, SPACE, B]
            cart, drv = self.run_page(bytearray(self.fresh), "u3", keys, bytes(disk))
            text = test_page.screen(drv.screen)
            self.assertEqual("Done." in text, done, text[-300:])
            self.assertEqual("That is not the" in text, not done, text[-300:])

    def test_a_save_goes_to_disk_and_back(self):
        for game in DISKS:
            with self.subTest(game=game):
                src = self.seeded(game)
                images = [disk_image(game, i) for i in range(len(DISKS[game]))]
                done = self.export_all(src, game, images)
                text = done["text"]
                self.assertIn("Done.", text, text[-400:])
                # the disks hold what the game would read
                for disk, xd in zip(done["disks"], self.xfer(game)):
                    for sl in xd.slots:
                        self.check_on_disk(src, disk, sl)
                # and they import back into a fresh cart, slot for slot
                cart, drv = self.run_page(bytearray(self.fresh), game,
                                          self.import_keys(game, [bytes(d.data)
                                                                  for d in done["disks"]]),
                                          bytes(done["disks"][0].data))
                text = test_page.screen(drv.screen)
                self.assertIn("Done.", text, text[-400:])
                for xd in self.xfer(game):
                    for sl in xd.slots:
                        self.assertEqual(self.slot_bytes(cart.flash, sl), self.slot_bytes(src, sl),
                                         f"{game} slot at {sl.base:#x}")
                # byte for byte, down to the $FF after the data -- but for
                # Ultima II's log, which the import writes as a new half
                lo, hi = regions.save_region(game)
                if game != "u2":
                    self.assertEqual(bytes(cart.flash[lo:hi]), bytes(src[lo:hi]))
                else:
                    self.assertEqual(u2log.active(cart.flash, lo), (0, 0), "a fresh cart's")
                    self.assertEqual(len(u2log.units(cart.flash, lo)), len(xd.slots))

    def export_all(self, flash, game, images):
        """Export, swapping in each disk when asked; returns the disks."""
        disks = [Disk(images[0])]
        sim = Sim(self.image, launcher.FONT_ORG, self.sym)
        cart = sim.attach_cart(bytearray(flash))
        drv = FakeDrive(sim)
        drv.disk = disks[0]
        ks = [ord("E"), ord("D"), Y, RET]
        for img in images[1:]:
            ks += [("swap", img), RET]
        ks += [SPACE, B]

        def getin(s):
            while ks and isinstance(ks[0], tuple):
                drv.swap(ks.pop(0)[1])
                disks.append(drv.disk)
            if not ks:
                raise AssertionError("wants a key:\n" + test_page.screen(drv.screen))
            k = ks.pop(0)
            s.mpu.a = k
            s.mpu.p = (s.mpu.p & ~0x82) | (0 if k else 0x02)
        sim.traps[0xFFE4] = getin
        sim.traps[0xFF9F] = lambda s: None
        sim.mem[0], sim.mem[1] = 0x2F, 0x37
        sim.mem[0x0300:0x0310] = list(b"ULTIMA X".ljust(16, b"\x00"))
        sim.mpu.a, sim.mpu.x, sim.mpu.y = regions.DESC_INDEX[game], 0x00, 0x03
        sim.call(launcher.PAGE_ORG, limit=400_000_000)
        self.assertEqual(bytes(cart.flash), bytes(flash), "an export changed the cart")
        return dict(disks=disks, text=test_page.screen(drv.screen))

    def check_on_disk(self, flash, disk, sl):
        have = self.slot_bytes(flash, sl)
        if hasattr(sl, "sectors"):
            data = have[4:] if sl.hdr in (1, 2) else have   # (LOG slots: none)
            got = b"".join(bytes(disk.sector(t, s)) for t, s in sl.sectors)
            self.assertEqual(got, data[:len(got)], f"sectors of the slot at {sl.base:#x}")
        else:
            f = disk.read_file(sl.name.upper().encode())
            if have is None:            # nothing saved there: left alone
                return
            data = have[4:] if sl.hdr in (1, 2) else have   # (LOG slots: none)
            self.assertIsNotNone(f, sl.name)
            self.assertEqual(f[:2], bytes([sl.load & 0xFF, sl.load >> 8]), sl.name)
            self.assertEqual(f[2:], data, sl.name)

    def test_a_wrong_disk_is_refused(self):
        for game in DISKS:
            with self.subTest(game=game):
                with open(paths.disk(WRONG[game]), "rb") as fh:
                    wrong = fh.read()

                for key in (ord("E"), ord("I")):
                    flash = self.seeded(game)
                    before = bytes(flash)
                    cart, drv = self.run_page(flash, game, [key, ord("D"), Y, RET, CANCEL, B], wrong)
                    self.assertIn("That is not the", test_page.screen(drv.screen))
                    self.assertEqual(bytes(cart.flash), before)
                    self.assertEqual(bytes(drv.disk.data), wrong)

    def test_no_drive_is_reported(self):
        flash = self.seeded("u4")
        before = bytes(flash)
        cart, drv = self.run_page(flash, "u4", [ord("I"), ord("D"), Y, RET, CANCEL, B], None)
        text = test_page.screen(drv.screen)
        self.assertIn("Drive 8 is not there", text)
        # a failed CHKOUT leaves the screen as the output: the drive command
        # must not be printed there (it was, on hardware: "i0")
        self.assertNotIn("i0", text.lower())
        self.assertEqual(bytes(cart.flash), before)

    def test_the_c128_launcher_goes_to_disk(self):
        """Ultima V's page writes its C128 launcher (launch128.s) as a PRG,
        byte for byte what the build made, and leaves the cart alone; the
        other games' pages have no such key."""
        with open(os.path.join(paths.BUILD, "launch128.prg"), "rb") as fh:
            prg = fh.read()
        before = bytes(self.fresh)
        cart, drv = self.run_page(bytearray(self.fresh), "u5", [ord("C"), RET, SPACE, B],
                                  blank_d64())
        text = test_page.screen(drv.screen)
        self.assertIn("The C128 launcher is on the disk.", text, text[-400:])
        self.assertIn('DLOAD"ULTIMA V 128"', text)
        blocks = -(-len(prg) // 254)
        self.assertIn(f"Insert a disk with {blocks} blocks free", text)
        self.assertEqual(drv.disk.read_file(b"ULTIMA V 128"), prg)
        self.assertEqual(bytes(cart.flash), before)
        # and again over it: scratched first, so still one file
        cart, drv2 = self.run_page(bytearray(self.fresh), "u5", [ord("C"), RET, SPACE, B],
                                   bytes(drv.disk.data))
        names = [bytes(e[5:21]).rstrip(b"\xa0") for _t, _s, _o, e in drv2.disk.entries()
                 if e[2] & 0x07]
        self.assertEqual(names, [b"ULTIMA V 128"])
        self.assertEqual(drv2.disk.read_file(b"ULTIMA V 128"), prg)
        for game in ("u1", "u4"):
            cart, drv = self.run_page(bytearray(self.fresh), game, [ord("C"), B], blank_d64())
            self.assertNotIn("C128", test_page.screen(drv.screen))


def blank_d64(name=b"BLANK", ident=b"00"):
    """A freshly formatted 1541 disk: the BAM with everything free but the
    directory track's two sectors, and an empty directory."""
    spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
    img = bytearray(sum(spt) * 256)
    off = lambda t, s: (sum(spt[:t - 1]) + s) * 256
    bam = bytearray(256)
    bam[0:4] = bytes([18, 1, 0x41, 0])
    for t in range(1, 36):
        free = set(range(spt[t - 1])) - ({0, 1} if t == 18 else set())
        bits = sum(1 << s for s in free)
        bam[4 * t:4 * t + 4] = bytes([len(free), bits & 0xFF, (bits >> 8) & 0xFF, bits >> 16])
    bam[0x90:0xAB] = name.ljust(16, b"\xa0") + b"\xa0\xa0" + ident + b"\xa0" + b"2A" + b"\xa0" * 4
    img[off(18, 0):off(18, 0) + 256] = bam
    img[off(18, 1) + 1] = 0xFF
    return bytes(img)


if __name__ == "__main__":
    unittest.main()
