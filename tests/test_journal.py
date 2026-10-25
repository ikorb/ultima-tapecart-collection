"""Saves that a power cut cannot lose (asm/journal.s), the first stage's
part in it (asm/boot.s), its stamp check, and its load of the launcher.

Each journaled driver's real save routine runs in py65 from the built cart,
its segments loaded as the menu loads them, against the model cart; then the
power is cut at every flash operation's edges (and a sample of the bytes in
between), and the first stage's own repair code runs on what is left.  The
slot must then hold the old save or the new one, whole -- never neither.

Skipped without py65 (the repository's .venv has it).
"""
import os
import re
import unittest
from pathlib import Path

from ultima.flash import regions
from ultima.flash import zx
from ultima.flash.tcrt import TCRT
from ultima import paths

try:
    from ultima.sim.sim6502 import Sim, PowerCut
except ImportError:
    Sim = None

BUILD = paths.BUILD
IMAGE = os.path.join(BUILD, "ultima-collection.tcrt")


def symbols(name):
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(BUILD, name)).read_text())}


def segments(flash, game):
    """[(dest, bytes)] of a game's descriptor, crunched ones decoded."""
    o = regions.desc_offset(game)
    d = flash[o:o + 64]
    out = []
    for n in range(d[2]):
        e = 3 + 7 * n
        off, length = d[e] << 8 | d[e + 1] << 16, d[e + 2] | d[e + 3] << 8
        dest, flags = d[e + 4] | d[e + 5] << 8, d[e + 6]
        data = bytes(flash[off:off + length])
        if flags & 1:
            data = zx.decode(data[2:])
        out.append((dest, data))
    return out


class Cut(Exception):
    pass


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestJournal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img = TCRT.read(IMAGE)
        cls.flash = bytes(img.flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cls.boot = cls.flash[regions.BOOT_PRG:regions.BOOT_PRG + regions.BOOT_LEN]
        cls.bsym = symbols("boot.sym")

    # ---- the machines ------------------------------------------------
    def machine(self, game, symfile, flash):
        sym = symbols(symfile)
        sim = Sim(b"", 0, sym)
        for dest, data in segments(flash, game):
            sim.mem[dest:dest + len(data)] = list(data)
        cart = sim.attach_cart(flash)
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x37
        return sim, cart, sym

    def first_stage(self, flash, routine="journals"):
        """The first stage's routine on `flash`; the cart after it."""
        sim = Sim(self.boot[2:], regions.BOOT_ORG, self.bsym)
        cart = sim.attach_cart(flash)
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x37
        sim.call(self.bsym["tc_init"])
        sim.call(self.bsym[routine])
        return sim, cart

    # ---- one save per game: (sim, flash) -> the slot written ---------
    def save_u1(self, flash, data):
        sim, cart, sym = self.machine("u1", "u1drv.sym", flash)
        e = (16 + 0) * 8                       # slot 0, file table index 16
        t = sym["u1_table"]
        src = sim.mem[t + e + 4] | sim.mem[t + e + 5] << 8
        n = sim.mem[t + e + 2] | sim.mem[t + e + 3] << 8
        sim.mem[src:src + n] = list(data[:n])
        sim.mpu.x = 0
        return sim, cart, lambda: sim.call(0xC483)

    def save_u3(self, flash, data):
        sim, cart, sym = self.machine("u3", "u3drv.sym", flash)
        slot = regions.save_base("u3") + 3 * 0x2000     # SOSA, 16 blocks: two erase blocks
        sim.mem[sym["u3_writable"]] = 1
        sim.mem[sym["u3_base"]], sim.mem[sym["u3_base"] + 1] = slot >> 8 & 0xFF, slot >> 16
        sim.mem[sym["u3_blocks"]] = 16
        sim.mem[sym["p_dest_lo"]], sim.mem[sym["p_dest_page"]] = 0, 0x40
        sim.mem[0x4000:0x5000] = list(data[:0x1000])
        return sim, cart, lambda: sim.call(sym["u3_do_save"])

    def save_u4(self, flash, data):
        from py65.memory import ObservableMemory
        sim, cart, sym = self.machine("u4", "u4drv.sym", flash)
        om = ObservableMemory(subject=sim.mem)   # u4_in's NMI hold: timer A stopped
        om.subscribe_to_read([0xDD0E], lambda a: 0x08)
        sim.mpu.memory = sim.mem = om
        sim.mem[0x01] = 0x35
        sim.call(sym["u4_init"])
        sim.mem[sym["u4_disk"]] = 2
        sim.mem[0xAC00:0xAD00] = list(data[:256])
        blk = 272                                 # chunk $7F: slot 1

        def run():
            sim.mem[0xA000:0xA006] = [2, 1, 0x00, 0xAC, blk & 0xFF, blk >> 8]
            sim.call(sym["u4_transfer"])
        return sim, cart, run

    def save_u5(self, flash, data):
        sim, cart, sym = self.machine("u5", "u5drv.sym", flash)
        slot = regions.save_base("u5") + 3 * 0x1000     # ROSTER, 1025 bytes
        sim.mem[sym["u5_wsrc"]], sim.mem[sym["u5_wsrc"] + 1] = 0x00, 0x40
        sim.mem[sym["u5_wlen"]], sim.mem[sym["u5_wlen"] + 1] = 1025 & 0xFF, 1025 >> 8
        sim.mem[0x4000:0x4401] = list(data[:1025])
        tc = sym["tc_addr"]

        def run():
            sim.mem[tc:tc + 3] = [0, slot >> 8 & 0xFF, slot >> 16]
            sim.call(sym["u5_jwrite"])
        return sim, cart, run

    SLOTS = {"u1": lambda: (regions.save_base("u1"), 0x1000),
             "u3": lambda: (regions.save_base("u3") + 3 * 0x2000, 0x2000),
             "u4": lambda: (regions.save_base("u4") + 0x1000, 0x1000),
             "u5": lambda: (regions.save_base("u5") + 3 * 0x1000, 0x1000)}

    # ---- the tests ---------------------------------------------------
    def journaled(self, game):
        """The uncut save: through the journal, then the slot; the journal
        erased.  Returns (old slot, new slot, the flash changes of each op)."""
        data = bytes((i * 29 + 7) & 0xFF for i in range(0x1000))
        base, size = self.SLOTS[game]()
        jn, jsize = regions.journal(game)
        sim, cart, run = getattr(self, f"save_{game}")(bytearray(self.flash), data)
        run()
        old = self.flash[base:base + size]
        new = bytes(cart.flash[base:base + size])
        self.assertNotEqual(old, new, "the save changed nothing")
        ops = [(e[0], e[1]) for e in cart.log if e[0] in ("erase", "write")]
        in_jn = lambda a: jn <= a < jn + jsize
        first_slot = next(i for i, (op, a) in enumerate(ops) if base <= a < base + size)
        self.assertTrue(ops[0] == ("erase", jn) and all(in_jn(a) for _op, a in ops[:first_slot]),
                        f"{game}: the journal first: {ops}")
        self.assertIn(("write", jn), ops[:first_slot], "the journal's header")
        self.assertEqual(ops[first_slot - 1], ("write", jn), "the header last")
        self.assertEqual(ops[-1], ("erase", jn), "the journal erased at the end")
        self.assertEqual(set(cart.flash[jn:jn + 0x1000]), {0xFF})
        # the journal held exactly what the slot got (checked before jr_end)
        return old, new, cart.changes, data

    def cut_sweep(self, game):
        old, new, total, data = self.journaled(game)
        base, size = self.SLOTS[game]()
        jn, _ = regions.journal(game)
        # every operation's edges, and a sample of the bytes between
        sim, cart, run = getattr(self, f"save_{game}")(bytearray(self.flash), data)
        run()
        points, c = set(range(0, total + 1, 97)), 0
        for e in cart.log:
            if e[0] == "erase":
                points |= {c, c + 1}
                c += 1
            elif e[0] == "write":
                points |= {c, c + 1, c + e[2] - 1, c + e[2]}
                c += e[2]
        self.assertEqual(c, total)
        outcomes = set()
        for k in sorted(p for p in points if p <= total):
            with self.subTest(game=game, cut_after=k):
                sim, cart, run = getattr(self, f"save_{game}")(bytearray(self.flash), data)
                cart.cut_after = k
                try:
                    run()
                except PowerCut:
                    pass
                _s, after = self.first_stage(bytes(cart.flash))
                slot = bytes(after.flash[base:base + size])
                self.assertIn(slot, (old, new), f"{game}: cut after {k} of {total} changes")
                self.assertEqual(after.flash[jn:jn + 2], b"\xff\xff", "the journal is done with")
                outcomes.add(slot == new)
        self.assertEqual(outcomes, {False, True})

    def test_u1(self):
        self.cut_sweep("u1")

    def test_u3_two_erase_blocks(self):
        self.cut_sweep("u3")

    def test_u4(self):
        self.cut_sweep("u4")

    def test_u5(self):
        self.cut_sweep("u5")

    def test_the_first_stage_leaves_a_journal_without_a_header(self):
        """An unfinished copy: the slot keeps the old save, nothing is erased."""
        flash = bytearray(self.flash)
        jn, _ = regions.journal("u4")
        flash[jn + 0x100:jn + 0x200] = bytes(256)
        _s, cart = self.first_stage(bytes(flash))
        self.assertEqual(bytes(cart.flash), bytes(flash))
        self.assertFalse([e for e in cart.log if e[0] in ("erase", "write")])

    def test_the_first_stage_erases_a_header_that_names_no_slot(self):
        for name, mid, hi in (("unaligned", 0x01, None), ("below the region", 0x00, 0x10),
                              ("the journal itself", None, None), ("above it", 0xF0, 0x1F)):
            with self.subTest(name):
                flash = bytearray(self.flash)
                jn, _ = regions.journal("u4")
                home = regions.save_base("u4")
                m = (home >> 8 & 0xFF) | 1 if name == "unaligned" else (jn >> 8 & 0xFF) if mid is None else mid
                h = (jn >> 16) if hi is None else hi
                flash[jn:jn + 4] = b"JN" + bytes([m, h])
                flash[jn + 0x100:jn + 0x200] = bytes(256)
                _s, cart = self.first_stage(bytes(flash))
                self.assertEqual([(e[0], e[1]) for e in cart.log if e[0] in ("erase", "write")],
                                 [("erase", jn)])

    def test_the_stamp(self):
        _s, _c = self.first_stage(self.flash, "stamp")        # the built image: it returns
        for name, patch in (("erased", b"\xff" * 16), ("before the stamp", b"UCFG" + bytes(12)),
                            ("another layout", b"UCFG" + bytes(8) + bytes([regions.LAYOUT + 1]) + bytes(3))):
            with self.subTest(name):
                flash = bytearray(self.flash)
                flash[regions.SETTINGS:regions.SETTINGS + 16] = patch
                sim = Sim(self.boot[2:], regions.BOOT_ORG, self.bsym)
                sim.attach_cart(bytes(flash))
                printed = []
                sim.traps[0xFFD2] = lambda s: printed.append(s.mpu.a)

                def stop(s):
                    raise Cut()
                sim.traps[self.bsym["halt"]] = stop
                sim.call(self.bsym["tc_init"])
                with self.assertRaises(Cut):
                    sim.call(self.bsym["stamp"])
                text = bytes(printed).decode("latin-1").lower()
                self.assertIn("laid out", text)
                self.assertIn("write tcrt", text)

    def test_the_first_stage_loads_the_launcher(self):
        sim = Sim(self.boot[2:], regions.BOOT_ORG, self.bsym)
        sim.attach_cart(self.flash)
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x37

        def menu(s):
            raise Cut()
        sim.traps[0x8700] = menu
        sim.call(self.bsym["tc_init"])
        with self.assertRaises(Cut):
            sim.call(self.bsym["go"])
        prg = regions.launcher_prg(self.flash)
        org = prg[0] | prg[1] << 8
        self.assertEqual(bytes(sim.mem[org:org + len(prg) - 2]), prg[2:])


if __name__ == "__main__":
    unittest.main()
